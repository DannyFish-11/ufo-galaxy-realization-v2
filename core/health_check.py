"""
UFO Galaxy - 生产级健康检查模块
================================

提供深度健康检查、指标收集和告警功能。
支持 /health、/health/ready、/health/live 端点。
"""

import asyncio
import logging
import os
import platform
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.Health")

# 启动时间
_start_time = time.time()


def get_system_metrics() -> Dict[str, Any]:
    """收集系统指标"""
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": round(time.time() - _start_time, 1),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python_version": platform.python_version(),
        },
    }

    # 内存信息
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
        # psutil 未安装时使用基础方法
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            mem_total = int(lines[0].split()[1]) / 1024  # MB
            mem_avail = int(lines[2].split()[1]) / 1024  # MB
            metrics["memory"] = {
                "total_mb": round(mem_total, 1),
                "available_mb": round(mem_avail, 1),
                "used_percent": round((1 - mem_avail / mem_total) * 100, 1),
            }
        except Exception:
            metrics["memory"] = {"note": "psutil not installed"}

        try:
            load = os.getloadavg()
            metrics["cpu"] = {
                "count": os.cpu_count() or 1,
                "load_avg_1m": round(load[0], 2),
                "load_avg_5m": round(load[1], 2),
            }
        except Exception:
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
            core_running = sum(
                1 for s in services.values()
                if s.get("status") == "running" and s.get("type") == "core"
            )
            checks["core_services"] = {
                "ready": core_running > 0,
                "running": core_running,
                "total": sum(1 for s in services.values() if s.get("type") == "core"),
            }
            if core_running == 0:
                overall_ready = False

        # 检查 LLM API 可用性
        if self.config:
            has_api = any([
                os.environ.get("OPENAI_API_KEY"),
                os.environ.get("GEMINI_API_KEY"),
                os.environ.get("OPENROUTER_API_KEY"),
                os.environ.get("XAI_API_KEY"),
            ])
            checks["llm_api"] = {"available": has_api}

        # 运行自定义检查
        for name, check_func in self._checks.items():
            try:
                result = await check_func() if asyncio.iscoroutinefunction(check_func) else check_func()
                checks[name] = result
                if isinstance(result, dict) and not result.get("ready", True):
                    overall_ready = False
            except Exception as e:
                checks[name] = {"ready": False, "error": str(e)}
                overall_ready = False

        return {
            "status": "ready" if overall_ready else "not_ready",
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
        status_code = 200 if result["status"] == "ready" else 503
        return JSONResponse(result, status_code=status_code)

    @router.get("/health/deep")
    async def deep_health():
        """深度健康检查（含系统指标）"""
        result = await checker.check_deep()
        return JSONResponse(result)

    @router.get("/metrics")
    async def metrics():
        """系统指标（Prometheus 兼容格式可后续扩展）"""
        m = get_system_metrics()
        return JSONResponse(m)

    return router, checker
