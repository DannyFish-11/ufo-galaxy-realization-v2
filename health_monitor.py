"""
Galaxy 健康监控系统（可选独立看门狗 / Prometheus 导出器）
========================================================

实时监控所有节点的健康状态，自动重启失败的节点，并暴露 Prometheus /metrics。

功能：
1. 实时监控所有节点
2. 自动重启失败的节点
3. 发送告警通知
4. 生成健康报告
5. Web 仪表板 + Prometheus /metrics

【它与主应用的关系 —— 避免"隐藏入口点"误解】
--------------------------------------------------------------------
本文件是一个【独立进程】服务(自带 FastAPI app + uvicorn,默认端口 9100),
**不由 `python main.py` 启动**,也【不需要】被它启动:

  - 主应用(端口 9000)已经通过 `core/routes/monitoring.py` 暴露了等价的
    `/metrics`(Prometheus)、`/api/v1/slo/metrics`、`/health/ready` —— 用的是
    同一个 `core.slo_metrics.get_slo_metrics()`。所以跑 `python main.py` 时这些
    指标/就绪端点【已经有了】,不缺。
  - 节点健康巡检 + 自动重启,在主路径上由已接线的
    `core.health_integration.UnifiedHealthManager`(core/startup.py 步骤 15)承担。

因此本文件定位为【可选的独立看门狗 / 导出器】:
  - 由 `daemon/galaxy_daemon.py` 作为受管子进程拉起(`python -m health_monitor
    --watchdog`),用于不跑完整主应用、只想要一个轻量节点看门狗的部署;
  - 或手动 `python health_monitor.py` 单独起一个健康仪表板 / Prometheus 抓取点。
既不是死代码(daemon 与若干结构测试都依赖它),也不该塞进主启动(会与上述两处
重复巡检 / 重复暴露端点)。

作者：Galaxy Team
日期：2026-01-23
"""

import asyncio
import httpx
import json
import time
from datetime import datetime
from typing import Dict, List
from pathlib import Path
from fastapi import FastAPI, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from nodes.common.cors_config import get_cors_origins

# 导入系统管理器
# 实现体已从 system_manager.py 搬到 launcher/nodes.py（原样移动，非重写）。
# system_manager.py 在步骤 8 删除；这里直接指向新家，不经它的 re-export 中转。
from launcher.nodes import NODES, NodeConfig, SystemManager

# SLO 指标
from core.slo_metrics import get_slo_metrics

# 记录 health_monitor 进程启动时间
_hm_start_time = time.time()

app = FastAPI(title="Galaxy Health Monitor", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# =============================================================================
# 健康监控器
# =============================================================================


class HealthMonitor:
    """健康监控器"""

    def __init__(self, manager: SystemManager, check_interval: int = 30):
        self.manager = manager
        self.check_interval = check_interval
        self.health_history: Dict[str, List[Dict]] = {}
        self.alert_count: Dict[str, int] = {}

        # ===== 集成：初始化能力和连接管理器 =====
        try:
            from core.capability_manager import get_capability_manager
            from core.connection_manager import get_connection_manager

            self.capability_manager = get_capability_manager()
            self.connection_manager = get_connection_manager()
        except Exception as e:
            print(f"⚠️  能力/连接管理器初始化失败: {e}")
            self.capability_manager = None
            self.connection_manager = None

    async def check_node(self, config: NodeConfig) -> Dict:
        """检查单个节点"""
        t0 = time.monotonic()
        is_healthy = await self.manager.check_node_health(config, timeout=5)
        latency_ms = (time.monotonic() - t0) * 1000.0

        # --- SLO: record heartbeat result and command latency ---
        slo = get_slo_metrics()
        slo.record_heartbeat(is_healthy)
        slo.record_command_latency(latency_ms)

        status = {
            "node_id": config.id,
            "name": config.name,
            "port": config.port,
            "group": config.group,
            "healthy": is_healthy,
            "latency_ms": round(latency_ms, 2),
            "timestamp": datetime.now().isoformat(),
        }

        # 记录历史
        if config.id not in self.health_history:
            self.health_history[config.id] = []

        self.health_history[config.id].append(status)

        # 只保留最近 100 条记录
        if len(self.health_history[config.id]) > 100:
            self.health_history[config.id] = self.health_history[config.id][-100:]

        return status

    async def check_all(self) -> List[Dict]:
        """检查所有节点"""
        all_configs = []
        for group in NODES.values():
            all_configs.extend(group)

        tasks = [self.check_node(config) for config in all_configs]
        results = await asyncio.gather(*tasks)

        return results

    async def monitor_loop(self):
        """监控循环"""
        print(f"🔍 健康监控已启动（间隔 {self.check_interval} 秒）")

        while True:
            try:
                results = await self.check_all()

                # 统计
                healthy_count = sum(1 for r in results if r["healthy"])
                total_count = len(results)

                print(f"[{datetime.now().strftime('%H:%M:%S')}] " f"健康: {healthy_count}/{total_count}")

                # 检查是否需要告警
                for result in results:
                    if not result["healthy"]:
                        await self.handle_unhealthy_node(result)

            except Exception as e:
                print(f"❌ 监控错误: {e}")

            await asyncio.sleep(self.check_interval)

    async def handle_unhealthy_node(self, status: Dict):
        """处理不健康的节点"""
        node_id = status["node_id"]

        # 增加告警计数
        if node_id not in self.alert_count:
            self.alert_count[node_id] = 0

        self.alert_count[node_id] += 1

        print(f"⚠️  节点 {status['name']} 不健康（告警次数: {self.alert_count[node_id]}）")

        # 如果连续 3 次不健康，尝试重启
        if self.alert_count[node_id] >= 3:
            print(f"🔄 尝试重启节点 {status['name']}...")
            # --- SLO: record reconnect attempt ---
            get_slo_metrics().record_reconnect(node_id)
            try:
                restart_result = await self.manager.restart_node(node_id)
                if restart_result:
                    print(f"✅ 节点 {status['name']} 重启成功")
                else:
                    print(f"❌ 节点 {status['name']} 重启失败")
            except Exception as e:
                print(f"❌ 节点 {status['name']} 重启异常: {e}")
            self.alert_count[node_id] = 0

    def get_summary(self) -> Dict:
        """获取摘要"""
        summary = {"total_nodes": 0, "healthy_nodes": 0, "unhealthy_nodes": 0, "groups": {}}

        for group_name, configs in NODES.items():
            group_summary = {"total": len(configs), "healthy": 0, "unhealthy": 0}

            for config in configs:
                if config.id in self.health_history and self.health_history[config.id]:
                    latest = self.health_history[config.id][-1]
                    if latest["healthy"]:
                        group_summary["healthy"] += 1
                    else:
                        group_summary["unhealthy"] += 1

            summary["groups"][group_name] = group_summary
            summary["total_nodes"] += group_summary["total"]
            summary["healthy_nodes"] += group_summary["healthy"]
            summary["unhealthy_nodes"] += group_summary["unhealthy"]

        # ===== 集成：添加能力和连接状态 =====
        if self.capability_manager:
            try:
                cap_stats = self.capability_manager.get_stats()
                summary["capabilities"] = cap_stats
            except Exception as e:
                summary["capabilities"] = {"error": str(e)}

        if self.connection_manager:
            try:
                conn_stats = self.connection_manager.get_stats()
                summary["connections"] = conn_stats
            except Exception as e:
                summary["connections"] = {"error": str(e)}

        return summary


# =============================================================================
# 全局实例
# =============================================================================

manager = SystemManager()
monitor = HealthMonitor(manager)

# =============================================================================
# API 端点
# =============================================================================


def _get_authority_boundary_status() -> dict:
    """Return a snapshot of the V6 center authority boundary for diagnostics.

    This is called from health/readiness endpoints so that authority-boundary
    structural integrity is observable at runtime without adding any overhead
    to per-request hot paths.
    """
    try:
        from core.center_authority_boundary import evaluate_center_authority_boundary

        report = evaluate_center_authority_boundary()
        return {
            "status": "intact" if report.all_domains_intact else "degraded",
            "all_domains_intact": report.all_domains_intact,
            "degraded_domains": report.degraded_domains,
            "report_id": report.report_id,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/")
async def root():
    """首页 — JSON status endpoint; UI via main SONARA dashboard at :8080"""
    summary = monitor.get_summary()
    return {
        "service": "Galaxy Health Monitor",
        "dashboard": "http://localhost:8080",
        "summary": summary,
    }


@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    results = await monitor.check_all()
    summary = monitor.get_summary()

    response = {"summary": summary, "nodes": results}

    # Surface authority boundary integrity (V6) for structural diagnostics.
    # This is read-only and non-blocking — it does not affect the request path.
    try:
        response["authority_boundary"] = _get_authority_boundary_status()
    except Exception:
        pass

    # Surface federation health summary if available
    try:
        from core.galaxy_federation import get_federation, _federation_enabled

        fed = get_federation()
        peers = fed.list_peers()
        response["federation"] = {
            "instance_id": fed.instance_id,
            "enabled": _federation_enabled(),
            "peers_count": len(peers),
            "alive": sum(1 for p in peers if p["status"] == "healthy"),
            "degraded": sum(1 for p in peers if p["status"] == "degraded"),
            "offline": sum(1 for p in peers if p["status"] == "offline"),
        }
    except Exception:
        pass

    return response


@app.get("/api/history/{node_id}")
async def get_history(node_id: str):
    """获取节点历史"""
    if node_id not in monitor.health_history:
        return {"error": "Node not found"}

    return {"node_id": node_id, "history": monitor.health_history[node_id]}


# =============================================================================
# SLO 指标端点  (PR-G2)
# =============================================================================


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus text-format SLO metrics scrape endpoint.

    Returns all galaxy_slo_* metrics in Prometheus exposition format.
    Compatible with Prometheus ``scrape_configs`` and Grafana data sources.

    Example::

        curl http://localhost:9100/metrics
    """
    return PlainTextResponse(
        content=get_slo_metrics().prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/api/v1/slo/metrics")
async def slo_metrics_json():
    """JSON snapshot of all SLO metrics.

    Returns the same data as ``/metrics`` but as a structured JSON object,
    which is easier to consume from dashboards or scripts.

    Schema::

        {
          "startup":          {"duration_ms": float|null, "recorded_at": float|null},
          "heartbeat":        {"total": int, "failures": int, "loss_rate": float},
          "reconnect":        {"attempts_total": int},
          "command_latency":  {"sample_count": int, "p50_ms": float|null, "p95_ms": float|null}
        }
    """
    return get_slo_metrics().snapshot()


@app.get("/api/v1/authority/boundary")
async def authority_boundary():
    """V6 center authority boundary integrity status.

    Returns a structured snapshot of the four center authority domain
    boundaries.  Intended for health dashboards, readiness probes, and
    diagnostic tooling.

    This endpoint does **not** gate any request path — it is purely
    observational.

    Schema::

        {
          "status":             "intact" | "degraded" | "error",
          "all_domains_intact": bool,
          "degraded_domains":   list[str],
          "report_id":          str
        }
    """
    return _get_authority_boundary_status()


@app.get("/health/ready")
async def health_ready():
    """Readiness probe — surfaces V6 center authority boundary status.

    Returns HTTP 200 when all four center authority domain boundaries are
    INTACT.  Returns HTTP 503 when the boundary is degraded or the V6 module
    is unavailable, so that readiness probes and load-balancers can surface
    structural integrity regressions without any per-request overhead.

    This endpoint does **not** gate any request path — it is a boundary /
    startup / readiness layer check only.

    Response schema::

        {
          "ready":              bool,
          "status":             "intact" | "degraded" | "error",
          "all_domains_intact": bool,
          "degraded_domains":   list[str],
          "report_id":          str        (omitted on error)
        }
    """
    boundary = _get_authority_boundary_status()
    ready = boundary.get("status") == "intact"
    payload = {"ready": ready, **boundary}
    status_code = 200 if ready else 503
    return JSONResponse(content=payload, status_code=status_code)


# =============================================================================
# 启动服务
# =============================================================================


@app.on_event("startup")
async def startup_event():
    """启动时开始监控循环，并记录启动耗时"""
    startup_ms = (time.time() - _hm_start_time) * 1000.0
    get_slo_metrics().record_startup(startup_ms)
    asyncio.create_task(monitor.monitor_loop())


if __name__ == "__main__":
    import argparse
    import uvicorn

    # daemon/galaxy_daemon.py 以 `python -m health_monitor --watchdog` 拉起本进程,
    # 但此前 __main__ 直接 uvicorn.run、把 --watchdog 静默丢弃(argv 根本没被解析)。
    # 这里显式解析,让守护进程的调用意图变得诚实可读,并允许覆盖端口。
    try:
        from core.port_config import get_service_port

        _default_port = get_service_port("health_monitor")
    except Exception:
        _default_port = 9100

    _parser = argparse.ArgumentParser(
        description="Galaxy 独立健康看门狗 / Prometheus 导出器(可选;主应用已内置等价端点)"
    )
    _parser.add_argument(
        "--watchdog",
        action="store_true",
        help="以看门狗模式运行(节点巡检 + 自动重启循环由 startup 事件启动;"
        "本进程即独立看门狗,该标志用于让 daemon 的调用意图显式化)",
    )
    _parser.add_argument(
        "--port",
        type=int,
        default=_default_port,
        help=f"HTTP 监听端口(默认 {_default_port})",
    )
    _parser.add_argument("--host", default="0.0.0.0", help="HTTP 监听地址(默认 0.0.0.0)")
    _args = _parser.parse_args()

    print(
        f"🩺 Galaxy Health Monitor 独立启动 "
        f"(watchdog={'on' if _args.watchdog else 'off'}, "
        f"http://{_args.host}:{_args.port}) —— 主应用(:9000)已内置等价 /metrics"
        f"、/api/v1/slo/metrics、/health/ready,本进程为可选独立看门狗/导出器。"
    )
    # 启动 Web 服务（监控循环通过 startup 事件自动启动）
    uvicorn.run(app, host=_args.host, port=_args.port)
