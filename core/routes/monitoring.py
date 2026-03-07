"""
UFO Galaxy - Monitoring & Infrastructure Routes
=================================================

Routes:
  GET /api/v1/monitoring/dashboard    - 监控仪表盘
  GET /api/v1/monitoring/health       - 健康检查聚合
  GET /api/v1/monitoring/alerts       - 告警列表
  GET /api/v1/monitoring/metrics      - 系统指标
  GET /metrics                        - Prometheus 指标
  GET /health/metrics                 - Prometheus 指标 (别名)
  GET /api/v1/monitoring/performance  - 性能指标
  GET /api/v1/health/unified          - 统一健康仪表盘
  GET /api/v1/health/quick            - 快速健康概览
  GET /api/v1/concurrency/status      - 并发管理器状态
  GET /api/v1/errors/summary          - 错误追踪概览
  GET /api/v1/discovery/status        - 节点发现服务状态
  GET /api/v1/security/audit          - 审计日志
  GET /api/v1/security/stats          - 安全统计
  GET /api/v1/config/status           - 配置管理器状态
  GET /api/v1/config/versions         - 配置版本历史
"""

import logging
import time as _time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.responses import Response

import time

_startup_time = time.time()

logger = logging.getLogger("UFO-Galaxy.API")


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

        return Response(content="\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")

    @router.get("/api/v1/monitoring/performance")
    async def monitoring_performance():
        """性能指标仪表盘"""
        from core.performance import PerformanceMonitor
        perf = PerformanceMonitor.instance()
        return JSONResponse(perf.get_dashboard())

    @router.get("/api/v1/health/unified")
    async def unified_health_dashboard():
        """统一健康仪表盘（整合所有健康子系统）"""
        try:
            from core.health_integration import get_unified_health_manager
            uhm = get_unified_health_manager()
            return JSONResponse(uhm.get_dashboard())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/health/quick")
    async def unified_health_quick():
        """快速健康概览"""
        try:
            from core.health_integration import get_unified_health_manager
            uhm = get_unified_health_manager()
            return JSONResponse(uhm.get_quick_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/concurrency/status")
    async def concurrency_status():
        """并发管理器状态"""
        try:
            from core.concurrency_manager import get_concurrency_manager
            mgr = get_concurrency_manager()
            return JSONResponse(mgr.get_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/errors/summary")
    async def error_summary():
        """错误追踪概览"""
        try:
            from core.error_framework import get_error_tracker
            tracker = get_error_tracker()
            return JSONResponse(tracker.get_summary())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/discovery/status")
    async def discovery_status():
        """节点发现服务状态"""
        try:
            from core.node_discovery import get_node_discovery
            disc = get_node_discovery()
            return JSONResponse(disc.get_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/security/audit")
    async def security_audit_logs():
        """审计日志（最近 50 条）"""
        try:
            from core.security_middleware import get_security_manager
            sec = get_security_manager()
            return JSONResponse(sec.audit.get_recent(50))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/security/stats")
    async def security_stats():
        """安全统计仪表盘"""
        try:
            from core.security_middleware import get_security_manager
            sec = get_security_manager()
            return JSONResponse(sec.get_dashboard())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/config/status")
    async def config_manager_status():
        """配置管理器状态"""
        try:
            from core.config_hot_reload import get_config_manager
            mgr = get_config_manager()
            return JSONResponse(mgr.get_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/config/versions")
    async def config_version_history():
        """配置版本历史"""
        try:
            from core.config_hot_reload import get_config_manager
            mgr = get_config_manager()
            return JSONResponse(mgr.versions.get_history(20))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    return router
