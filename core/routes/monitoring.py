"""
Galaxy - Monitoring & Infrastructure Routes
============================================

**Domain authority notice**
----------------------------
This module owns the ``/api/v1/monitoring/*`` route surface only.

Health and diagnostics routes have been extracted to dedicated domain
modules as part of Batch PR-4 API decomposition:
  - Health:      ``core/routes/health.py``      (``/api/v1/health/*``)
  - Diagnostics: ``core/routes/diagnostics.py`` (concurrency, errors,
                 discovery, security, config sub-paths)

Routes owned by this module:
  GET /api/v1/monitoring/dashboard    - 监控仪表盘
  GET /api/v1/monitoring/health       - 健康检查聚合
  GET /api/v1/monitoring/alerts       - 告警列表
  GET /api/v1/monitoring/metrics      - 系统指标
  GET /metrics                        - Prometheus 指标 (includes SLO + operational SLO)
  GET /health/metrics                 - Prometheus 指标 (别名)
  GET /api/v1/monitoring/performance  - 性能指标
  GET /api/v1/slo/metrics             - SLO 指标 JSON (PR-G2)
  GET /api/v1/slo/operational         - Operational SLO 指标 JSON (PR-I)
"""

import logging
import time as _time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.responses import Response

_startup_time = _time.time()

logger = logging.getLogger("Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create monitoring and infrastructure routes router."""
    router = APIRouter()

    from core.monitoring import get_monitoring_manager, AlertSeverity

    monitoring = get_monitoring_manager()

    monitoring.health.register_check("api", lambda: {"status": "healthy"})
    monitoring.health.register_check("cache", lambda: {
        "status": "healthy",
        "backend": "memory",
    })

    @router.get("/api/v1/monitoring/dashboard")
    async def monitoring_dashboard():
        """完整监控仪表盘"""
        from core.performance import PerformanceMonitor
        from core.command_router import get_command_router
        perf = PerformanceMonitor.instance()

        dashboard = monitoring.get_full_dashboard()
        dashboard["performance"] = perf.get_dashboard()
        dashboard["command_router"] = get_command_router().get_stats()
        return JSONResponse(dashboard)

    @router.get("/api/v1/monitoring/health")
    async def monitoring_health():
        """健康检查聚合"""
        return JSONResponse(monitoring.health.get_status())

    @router.get("/api/v1/monitoring/alerts")
    async def monitoring_alerts():
        """告警列表"""
        return JSONResponse({
            "active": monitoring.alerts.get_active_alerts(),
            "history": monitoring.alerts.get_history(50),
        })

    @router.get("/api/v1/monitoring/metrics")
    async def monitoring_metrics():
        """系统指标"""
        return JSONResponse(monitoring.metrics.get_dashboard())

    @router.get("/metrics")
    @router.get("/health/metrics")
    async def prometheus_metrics():
        """Prometheus-compatible metrics endpoint (text/plain)"""
        lines = []
        lines.append(f"# HELP process_uptime_seconds Time since process start")
        lines.append(f"# TYPE process_uptime_seconds gauge")
        lines.append(f"process_uptime_seconds {_time.time() - _startup_time:.1f}")

        try:
            status = monitoring.health.get_status()
            lines.append(f"# HELP galaxy_active_nodes Number of active nodes")
            lines.append(f"# TYPE galaxy_active_nodes gauge")
            lines.append(f"galaxy_active_nodes {status.get('nodes_active', 0)}")
            lines.append(f"# HELP galaxy_connected_devices Number of connected devices")
            lines.append(f"# TYPE galaxy_connected_devices gauge")
            lines.append(f"galaxy_connected_devices {status.get('devices_connected', 0)}")
        except Exception:
            pass

        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            rss = usage.ru_maxrss * 1024  # KB → bytes
            lines.append(f"# HELP process_resident_memory_bytes Resident memory size in bytes")
            lines.append(f"# TYPE process_resident_memory_bytes gauge")
            lines.append(f"process_resident_memory_bytes {rss}")
            lines.append(f"# HELP process_cpu_seconds_total Total CPU time")
            lines.append(f"# TYPE process_cpu_seconds_total counter")
            lines.append(f"process_cpu_seconds_total {usage.ru_utime + usage.ru_stime:.2f}")
        except Exception:
            pass

        # PR-G2: SLO metrics (startup, heartbeat, reconnect, command latency)
        try:
            from core.slo_metrics import get_slo_metrics
            lines.append(get_slo_metrics().prometheus_text().rstrip("\n"))
        except Exception:
            pass

        # PR-I: Operational SLO metrics (dispatch, recovery, fallback, audit persistence)
        try:
            from core.operational_slo_metrics import get_operational_slo_metrics
            lines.append(get_operational_slo_metrics().prometheus_text().rstrip("\n"))
        except Exception:
            pass

        return Response(content="\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")

    @router.get("/api/v1/monitoring/performance")
    async def monitoring_performance():
        """性能指标仪表盘"""
        from core.performance import PerformanceMonitor
        perf = PerformanceMonitor.instance()
        return JSONResponse(perf.get_dashboard())

    # PR-G2: SLO metrics JSON endpoint
    @router.get("/api/v1/slo/metrics")
    async def slo_metrics():
        """SLO metrics JSON endpoint (PR-G2).

        Returns a JSON snapshot of the process-level SLO indicators:
        startup duration, heartbeat loss rate, reconnect total, and
        command latency percentiles.
        """
        from core.slo_metrics import get_slo_metrics
        return JSONResponse(get_slo_metrics().snapshot())

    # PR-I: Operational SLO metrics JSON endpoint
    @router.get("/api/v1/slo/operational")
    async def operational_slo_metrics():
        """Operational SLO metrics JSON endpoint (PR-I).

        Returns a JSON snapshot of runtime orchestration counters so
        operators can inspect dispatch, recovery, fallback, routing
        rejection, startup recovery scan, and durable-audit persistence
        outcomes without ad-hoc log inspection.
        """
        from core.operational_slo_metrics import get_operational_slo_metrics
        return JSONResponse(get_operational_slo_metrics().snapshot())

    return router
