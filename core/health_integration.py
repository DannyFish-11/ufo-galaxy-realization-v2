"""
健康检查整合层 (Health Integration Layer)
==========================================

将分散的 3 个健康相关模块统一整合：
  - health_check.py      → HealthChecker (K8s 探针、基础指标)
  - monitoring.py         → MonitoringManager (熔断器、告警、聚合器、指标采集)
  - system_load_monitor.py → SystemLoadMonitor (CPU/内存/磁盘/网络详细采集)

同时连接新增的：
  - error_framework.py    → ErrorTracker (错误追踪与统计)
  - concurrency_manager.py → ConcurrencyManager (并发状态)
  - node_discovery.py     → NodeDiscoveryService (节点发现状态)

对外提供单一入口 UnifiedHealthManager。
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.HealthIntegration")


class UnifiedHealthManager:
    """
    统一健康管理器

    整合所有健康/监控子系统，提供：
    - 单一入口查询系统整体健康
    - 自动将 SystemLoadMonitor 指标灌入 MetricsCollector
    - 自动将 ErrorTracker 峰值检测接入 AlertManager
    - 将并发管理和节点发现状态纳入健康聚合
    """

    def __init__(self):
        # 延迟赋值——由 wire() 统一连接
        self._monitoring = None      # MonitoringManager
        self._load_monitor = None    # SystemLoadMonitor
        self._error_tracker = None   # ErrorTracker
        self._concurrency = None     # ConcurrencyManager
        self._discovery = None       # NodeDiscoveryService
        self._health_checker = None  # HealthChecker

        self._running = False
        self._sync_task: Optional[asyncio.Task] = None

    def wire(
        self,
        monitoring=None,
        load_monitor=None,
        error_tracker=None,
        concurrency=None,
        discovery=None,
        health_checker=None,
    ):
        """连接各子系统（可选，缺失的会跳过）"""
        self._monitoring = monitoring
        self._load_monitor = load_monitor
        self._error_tracker = error_tracker
        self._concurrency = concurrency
        self._discovery = discovery
        self._health_checker = health_checker

        # 向 HealthAggregator 注册额外检查
        if monitoring and monitoring.health:
            if load_monitor:
                monitoring.health.register_check(
                    "system_load", self._check_system_load
                )
            if error_tracker:
                monitoring.health.register_check(
                    "error_rate", self._check_error_rate
                )
            if concurrency:
                monitoring.health.register_check(
                    "concurrency", self._check_concurrency
                )
            if discovery:
                monitoring.health.register_check(
                    "node_discovery", self._check_discovery
                )

        logger.info(
            "UnifiedHealthManager 已连接 "
            f"(monitoring={'Y' if monitoring else 'N'}, "
            f"load={'Y' if load_monitor else 'N'}, "
            f"errors={'Y' if error_tracker else 'N'}, "
            f"concurrency={'Y' if concurrency else 'N'}, "
            f"discovery={'Y' if discovery else 'N'})"
        )

    async def start(self):
        """启动同步循环"""
        if self._running:
            return
        self._running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("UnifiedHealthManager 已启动")

    async def stop(self):
        """停止"""
        self._running = False
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        logger.info("UnifiedHealthManager 已停止")

    # ─── 同步循环：将 SystemLoadMonitor 指标灌入 MetricsCollector ───

    async def _sync_loop(self):
        """定期同步各子系统指标"""
        while self._running:
            try:
                await asyncio.sleep(15)
                self._sync_load_metrics()
                self._check_error_spikes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"同步循环异常: {e}")

    def _sync_load_metrics(self):
        """将 SystemLoadMonitor 数据灌入 MetricsCollector"""
        if not self._load_monitor or not self._monitoring:
            return

        try:
            load = self._load_monitor.get_system_load()
            mc = self._monitoring.metrics

            mc.record("load.cpu_percent", load.cpu.usage_percent)
            mc.record("load.memory_percent", load.memory.usage_percent)
            mc.record("load.disk_percent", load.disk.usage_percent)
            mc.record("load.network_connections", load.network.connections_count)
            mc.record("load.overall_score", load.overall_load_score())
            mc.record("load.cpu_load_avg_1m", load.cpu.load_avg_1m)
            mc.record("load.swap_percent", load.memory.swap_percent)
        except Exception as e:
            logger.debug(f"同步负载指标失败: {e}")

    def _check_error_spikes(self):
        """检测错误峰值并触发告警"""
        if not self._error_tracker or not self._monitoring:
            return

        try:
            from core.monitoring import AlertSeverity

            summary = self._error_tracker.get_summary()
            rate_1m = summary.get("error_rate_1m", 0)

            if rate_1m > 1.0:
                self._monitoring.alerts.fire(
                    AlertSeverity.CRITICAL,
                    "error_framework",
                    f"错误率过高: {rate_1m:.2f}/s (1分钟窗口)",
                    metadata={"error_rate": rate_1m},
                )
            elif rate_1m > 0.5:
                self._monitoring.alerts.fire(
                    AlertSeverity.WARNING,
                    "error_framework",
                    f"错误率升高: {rate_1m:.2f}/s (1分钟窗口)",
                    metadata={"error_rate": rate_1m},
                )
            elif rate_1m < 0.1:
                self._monitoring.alerts.resolve(
                    "error_framework",
                    f"错误率过高: {rate_1m:.2f}/s (1分钟窗口)",
                )
                self._monitoring.alerts.resolve(
                    "error_framework",
                    f"错误率升高: {rate_1m:.2f}/s (1分钟窗口)",
                )
        except Exception as e:
            logger.debug(f"错误峰值检测失败: {e}")

    # ─── HealthAggregator 注册的检查函数 ───

    def _check_system_load(self) -> Dict:
        """系统负载检查"""
        try:
            score = self._load_monitor.get_load_score()
            if score > 0.9:
                return {"status": "unhealthy", "load_score": score}
            elif score > 0.7:
                return {"status": "degraded", "load_score": score}
            return {"status": "healthy", "load_score": round(score, 4)}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _check_error_rate(self) -> Dict:
        """错误率检查"""
        try:
            summary = self._error_tracker.get_summary()
            rate = summary.get("error_rate_1m", 0)
            total = summary.get("total_errors", 0)
            if rate > 1.0:
                return {"status": "unhealthy", "error_rate": rate, "total": total}
            elif rate > 0.5:
                return {"status": "degraded", "error_rate": rate, "total": total}
            return {"status": "healthy", "error_rate": round(rate, 3), "total": total}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _check_concurrency(self) -> Dict:
        """并发状态检查"""
        try:
            status = self._concurrency.get_status()
            conc = status.get("concurrency", {})
            active = conc.get("global_active", 0)
            max_c = conc.get("global_max", 50)
            usage = active / max_c if max_c > 0 else 0

            locks = status.get("locks", {})
            if usage > 0.9:
                return {"status": "degraded", "usage": round(usage, 2), "locks": locks}
            return {"status": "healthy", "usage": round(usage, 2), "active": active, "max": max_c}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _check_discovery(self) -> Dict:
        """节点发现状态检查"""
        try:
            status = self._discovery.get_status()
            healthy = status.get("healthy_nodes", 0)
            total = status.get("total_nodes", 0)
            return {
                "status": "healthy",
                "total_nodes": total,
                "healthy_nodes": healthy,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    # ─── 统一仪表盘 ───

    def get_dashboard(self) -> Dict[str, Any]:
        """获取统一健康仪表盘"""
        dashboard = {"timestamp": time.time()}

        # 监控系统（熔断器 + 告警 + 组件健康 + 指标）
        if self._monitoring:
            dashboard["monitoring"] = self._monitoring.get_full_dashboard()

        # 系统负载详情
        if self._load_monitor:
            try:
                dashboard["system_load"] = self._load_monitor.export_stats()
            except Exception:
                dashboard["system_load"] = {"error": "unavailable"}

        # 错误追踪
        if self._error_tracker:
            try:
                dashboard["errors"] = self._error_tracker.get_summary()
            except Exception:
                dashboard["errors"] = {"error": "unavailable"}

        # 并发管理
        if self._concurrency:
            try:
                dashboard["concurrency"] = self._concurrency.get_status()
            except Exception:
                dashboard["concurrency"] = {"error": "unavailable"}

        # 节点发现
        if self._discovery:
            try:
                dashboard["node_discovery"] = self._discovery.get_status()
            except Exception:
                dashboard["node_discovery"] = {"error": "unavailable"}

        return dashboard

    def get_quick_status(self) -> Dict[str, str]:
        """快速状态概览（适合 /health 端点）"""
        result = {}

        if self._monitoring:
            health = self._monitoring.health.get_status()
            result["overall"] = health.get("overall", "unknown")
            result["components"] = {
                k: v.get("status", "unknown")
                for k, v in health.get("components", {}).items()
            }

        if self._load_monitor:
            try:
                result["load_score"] = round(self._load_monitor.get_load_score(), 4)
            except Exception:
                result["load_score"] = -1

        if self._error_tracker:
            try:
                summary = self._error_tracker.get_summary()
                result["error_rate_1m"] = summary.get("error_rate_1m", 0)
                result["total_errors"] = summary.get("total_errors", 0)
            except Exception:
                pass

        return result


# ───────────────────── 单例 ─────────────────────

_instance: Optional[UnifiedHealthManager] = None


def get_unified_health_manager() -> UnifiedHealthManager:
    global _instance
    if _instance is None:
        _instance = UnifiedHealthManager()
    return _instance
