"""
Galaxy - 生产级健康检查模块
================================

提供深度健康检查、指标收集和告警功能。
支持 /health、/health/ready、/health/live 端点。
"""

import asyncio
import logging
import os
import platform
import time
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger("Galaxy.Health")

# 启动时间
_start_time = time.time()

#: 就绪判据的**唯一**取值。``check_readiness()`` 产出它,``/health/ready`` 路由
#: 按它决定 200/503,``python -m core.health_check`` 按它决定退出码 0/1。
#:
#: 写成常量而不是让三处各写一个字面量 "ready":我在给本模块补 __main__ 时就是
#: 另列了一张 ("healthy","ok","alive") 的同义词表,结果正常值 "ready" 不在表里,
#: 一台健康的机器被判成 exit 1。判据分散写就会这样漂。
HEALTHY_STATUS = "ready"


def get_system_metrics() -> Dict[str, Any]:
    """收集系统指标

    优先委托 SystemLoadMonitor（更丰富的数据），不可用时回退到直接采集。
    返回格式保持向后兼容。
    """
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": round(time.time() - _start_time, 1),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python_version": platform.python_version(),
        },
    }

    # 优先尝试 SystemLoadMonitor（读共享单例的后台采样缓存，绝不现算）
    #
    # 真机复现过:这里之前每次都 `SystemLoadMonitor()` 现 new 一个全新实例、
    # 直接调用 get_system_load() —— 它内部要枚举全部进程(psutil.process_iter)，
    # Windows 上单次就要 2-5 秒，而这个函数是从 /metrics、/health/deep 两个
    # async 路由里同步直接调用的，每次命中都会把整个事件循环卡住 2-5 秒。
    # 现在改用真正共享、由 core.startup.bootstrap_subsystems 启动了后台采样
    # 循环的单例，只读它的缓存；缓存还没有(刚启动的一瞬间)才落到下面更便宜的
    # 直接采集分支，而不是现算一次昂贵的完整负载。
    try:
        from core.system_load_monitor import get_monitor

        monitor = get_monitor()
        load = monitor.get_cached_load()
        if load is None:
            raise LookupError("no cached load sample yet")
        metrics["memory"] = {
            "total_mb": round(load.memory.total_bytes / 1024 / 1024, 1),
            "available_mb": round(load.memory.available_bytes / 1024 / 1024, 1),
            "used_percent": load.memory.usage_percent,
        }
        metrics["cpu"] = {
            "count": load.cpu.core_count,
            "percent": load.cpu.usage_percent,
            "load_avg_1m": load.cpu.load_avg_1m,
            "load_avg_5m": load.cpu.load_avg_5m,
        }
        metrics["disk"] = {}
        if load.disk.total_bytes > 0:
            metrics["disk"]["/"] = {
                "total_gb": round(load.disk.total_bytes / 1024**3, 1),
                "free_gb": round(load.disk.free_bytes / 1024**3, 1),
                "used_percent": load.disk.usage_percent,
            }
        return metrics
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # 回退: 直接采集
    try:
        import psutil

        mem = psutil.virtual_memory()
        metrics["memory"] = {
            "total_mb": round(mem.total / 1024 / 1024, 1),
            "available_mb": round(mem.available / 1024 / 1024, 1),
            "used_percent": mem.percent,
        }
        metrics["cpu"] = {
            "count": psutil.cpu_count(),
            "percent": psutil.cpu_percent(interval=0.1),
        }
        metrics["disk"] = {}
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                if part.mountpoint in ("/", "/home"):
                    metrics["disk"][part.mountpoint] = {
                        "total_gb": round(usage.total / 1024**3, 1),
                        "free_gb": round(usage.free / 1024**3, 1),
                        "used_percent": usage.percent,
                    }
            except PermissionError:
                pass
    except ImportError:
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                lines = f.readlines()
            mem_total = int(lines[0].split()[1]) / 1024
            mem_avail = int(lines[2].split()[1]) / 1024
            metrics["memory"] = {
                "total_mb": round(mem_total, 1),
                "available_mb": round(mem_avail, 1),
                "used_percent": round((1 - mem_avail / mem_total) * 100, 1),
            }
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            metrics["memory"] = {"note": "psutil not installed"}

        try:
            load = os.getloadavg()
            metrics["cpu"] = {
                "count": os.cpu_count() or 1,
                "load_avg_1m": round(load[0], 2),
                "load_avg_5m": round(load[1], 2),
            }
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            metrics["cpu"] = {"count": os.cpu_count() or 1}

    return metrics


class HealthChecker:
    """健康检查器"""

    def __init__(self, service_manager=None, config=None):
        self.service_manager = service_manager
        self.config = config
        self._checks: Dict[str, callable] = {}
        self._last_check_results: Dict[str, Any] = {}
        self._check_interval = 30  # 秒
        self._last_check_time = 0

    def register_check(self, name: str, check_func):
        """注册自定义健康检查"""
        self._checks[name] = check_func

    async def check_liveness(self) -> Dict[str, Any]:
        """存活检查 - 进程是否在运行"""
        return {
            "status": "alive",
            "uptime_seconds": round(time.time() - _start_time, 1),
            "timestamp": datetime.now().isoformat(),
        }

    async def check_readiness(self) -> Dict[str, Any]:
        """就绪检查 - 服务是否可以接受请求"""
        checks = {}
        overall_ready = True

        # 检查核心服务
        if self.service_manager:
            services = self.service_manager.get_status()
            core_running = sum(1 for s in services.values() if s.get("status") == "running" and s.get("type") == "core")
            checks["core_services"] = {
                "ready": core_running > 0,
                "running": core_running,
                "total": sum(1 for s in services.values() if s.get("type") == "core"),
            }
            if core_running == 0:
                overall_ready = False

        # 检查 LLM API 可用性
        if self.config:
            has_api = any(
                [
                    os.environ.get("OPENAI_API_KEY"),
                    os.environ.get("GEMINI_API_KEY"),
                    os.environ.get("OPENROUTER_API_KEY"),
                    os.environ.get("XAI_API_KEY"),
                ]
            )
            checks["llm_api"] = {"available": has_api}

        # 运行自定义检查
        for name, check_func in list(self._checks.items()):
            try:
                result = await check_func() if asyncio.iscoroutinefunction(check_func) else check_func()
                checks[name] = result
                if isinstance(result, dict) and not result.get("ready", True):
                    overall_ready = False
            except Exception as e:
                logger.debug("Fallback triggered: %s", e)
                checks[name] = {"ready": False, "error": str(e)}
                overall_ready = False

        return {
            "status": HEALTHY_STATUS if overall_ready else "not_ready",
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
        }

    async def check_deep(self) -> Dict[str, Any]:
        """深度健康检查 - 包含系统指标"""
        readiness = await self.check_readiness()
        metrics = get_system_metrics()

        # 节点状态
        node_status = {}
        if self.service_manager:
            services = self.service_manager.get_status()
            for name, info in services.items():
                if info.get("type") == "node":
                    node_status[name] = info.get("status", "unknown")

        return {
            "status": readiness["status"],
            "readiness": readiness,
            "system_metrics": metrics,
            "nodes": {
                "total": len(node_status),
                "running": sum(1 for s in node_status.values() if s == "running"),
                "status": node_status,
            },
            "timestamp": datetime.now().isoformat(),
        }


def create_health_routes(service_manager=None, config=None):
    """创建健康检查路由"""
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    router = APIRouter(tags=["health"])
    checker = HealthChecker(service_manager, config)

    @router.get("/health")
    async def health():
        """基础健康检查"""
        result = await checker.check_liveness()
        return JSONResponse(result)

    @router.get("/health/live")
    async def liveness():
        """Kubernetes 存活探针"""
        result = await checker.check_liveness()
        return JSONResponse(result, status_code=200)

    @router.get("/health/ready")
    async def readiness():
        """Kubernetes 就绪探针"""
        result = await checker.check_readiness()
        status_code = 200 if result["status"] == HEALTHY_STATUS else 503
        return JSONResponse(result, status_code=status_code)

    @router.get("/health/deep")
    async def deep_health():
        """深度健康检查（含系统指标）"""
        result = await checker.check_deep()
        return JSONResponse(result)

    # 这里曾有一条 ``@router.get("/metrics")``,返回 get_system_metrics() 的 JSON。
    #
    # 它**从来没有生效过**:统一启动器先挂步骤 3 的权威 API 层(其中
    # core/routes/monitoring.py 已把 /metrics 与 /health/metrics 指向同一个
    # Prometheus 处理函数),再挂步骤 4 的健康检查层。FastAPI 里重复路径先注册的赢,
    # 所以这一条永远命不中 —— 是一条"存在但从不生效"的死路由。
    #
    # 删而不是改路径:两者的语义本来就该由 monitoring 那条承担。/metrics 是给
    # Prometheus 抓取端用的,必须是 text/plain 的 exposition 格式;这里返回 JSON,
    # 抓取端会直接解析失败。也就是说即使它"赢"了,也是错的那个赢。
    #
    # 这份 JSON 指标没有丢:check_deep() 里嵌着同一个 get_system_metrics(),
    # 走 /health/deep 拿得到。

    return router, checker


# ---------------------------------------------------------------------------
# ``python -m core.health_check`` —— 让名字不再骗人
# ---------------------------------------------------------------------------
#
# 这个模块此前**没有** ``__main__`` 守卫。于是 ``python -m core.health_check``
# 会静默 **exit 0 而什么也不做** —— 实测过：无输出、无副作用、返回码 0。
#
# 静默的成功比崩溃更糟。它的名字（health_check）明摆着在邀请人当 CLI 用，
# 而"跑了、绿了、什么都没查"会让人以为系统健康 —— 自动化脚本尤其：
# ``python -m core.health_check && deploy`` 会无条件放行。
#
# 本模块的真实身份是**路由工厂**（``create_health_routes()`` 给 app 装配用），
# 不是 CLI。但既然名字会招来 CLI 调用，就得让这条路径要么真的有用、要么响亮
# 地失败，不能继续假装成功。这里选前者：用模块**自己已有的** HealthChecker
# 跑一次一次性检查，并按结果给出**非零退出码**。
#
# 与另外四个健康面的分工（写在这里，因为"看着像重复"正是它们被反复合并/误删
# 的原因）：
#
#   launcher/health_checks.py   启动面：启动完成后跑一次，探网关/Node_71/NATS
#   health_monitor.py           独立的常驻 FastAPI 服务（/status /history /metrics）
#   core/health_check.py        路由工厂（本模块）：给 app 装 /health/*
#   scripts/health_check.{sh,ps1}  运维面：从**进程外**探端口与 HTTP
#
# 四件事，不是一件事的四份拷贝。真正重复的只有"探一个 HTTP 端点"这种两三行的
# 动作，把它们强行合并成一个模块只会让四类调用方互相牵制。


def _main() -> int:
    """一次性健康检查。返回进程退出码。"""
    import json
    import sys

    checker = HealthChecker()
    try:
        result = asyncio.run(checker.check_deep())
    except Exception as exc:  # noqa: BLE001
        print(f"健康检查执行失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    # 退出码来自结论本身,不是"跑完了就算成功"。
    #
    # 判据与 ``/health/ready`` 路由用的是**同一条**:该路由写的是
    # ``status_code = 200 if result["status"] == "ready" else 503``。
    # 这里照抄那一条,而不是另列一张"healthy/ok/alive"的同义词表 ——
    # 我第一版就是那么写的,结果 ``check_readiness`` 返回的正常值 ``"ready"``
    # 不在表里,一台健康的机器被判成 exit 1。两处判据分开写就会这样漂。
    return 0 if result.get("status") == HEALTHY_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(_main())
