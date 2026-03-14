"""
Galaxy - Observability Routes (PR-C / Phase E)
===============================================

Dashboard 可观测性端点，提供：
  - 活跃模型路由及 Fallback 状态
  - 网关 / 设备在线状态
  - 近期工具 / 设备调用记录
  - 按 task_id 或 command_id 查询 trace
  - NATS Bus 健康与统计 (Phase E)

Routes:
  GET /api/v1/observability/model-route        - 活跃 LLM 路由 + Fallback 列表
  GET /api/v1/observability/gateway            - 网关 & 设备在线状态汇总
  GET /api/v1/observability/recent-calls       - 近期工具 / 设备调用（最多 50 条）
  GET /api/v1/observability/trace/{id}         - 按 task_id 或 command_id 查 trace
  GET /api/v1/observability/stats              - trace 存储统计
  GET /health/nats                             - NATS bus 连接状态与统计 (Phase E)
  GET /api/v1/observability/nats               - NATS bus + MasterBrain 拓扑 (Phase E)
  GET /api/v1/observability/bus-events         - 最近 NATS 总线事件 (Phase E)
"""

import logging
import os
import time as _time
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API")

_startup_time = _time.time()


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create observability routes router."""
    router = APIRouter()

    # ── 活跃 LLM 路由 + Fallback ─────────────────────────────────────────

    @router.get("/api/v1/observability/model-route")
    async def model_route_status():
        """
        活跃模型路由及 Fallback 状态。

        返回当前 MultiLLMRouter 的默认模型、所有提供商状态（含 fallback 列表）
        以及最近一次路由决策。
        """
        try:
            from core.multi_llm_router import get_llm_router
            router_inst = get_llm_router()
            status = router_inst.get_status()
            providers = router_inst.get_provider_status()
            default_model = router_inst.get_default_model()

            # 构建 fallback 列表：把非 primary 的、可用的 provider 标为 fallback
            fallbacks = [
                p for p in providers
                if not p.get("is_primary", False) and p.get("available", False)
            ]

            return JSONResponse({
                "default_model": default_model,
                "active_provider": status.get("active_provider"),
                "providers": providers,
                "fallbacks": fallbacks,
                "router_stats": status,
                "uptime_seconds": round(_time.time() - _startup_time, 1),
            })
        except Exception as exc:
            logger.warning("observability/model-route error: %s", exc)
            return JSONResponse(
                {"error": str(exc), "default_model": None, "providers": [], "fallbacks": []},
                status_code=200,
            )

    # ── 网关 / 设备在线状态 ───────────────────────────────────────────────

    @router.get("/api/v1/observability/gateway")
    async def gateway_status():
        """
        网关及设备在线状态汇总。

        整合：
          - WebSocket connection_manager 中的 active_devices
          - DeviceRegistry 中的注册设备及在线状态
          - CommandRouter 统计信息
        """
        active_ws: list = []
        try:
            from core.routes._shared import connection_manager
            active_ws = list(connection_manager.active_devices.keys())
        except Exception as exc:
            logger.debug("gateway_status ws error: %s", exc)

        registered_devices: list = []
        online_count = 0
        try:
            from core.device_registry import DeviceRegistry
            registry = DeviceRegistry.get_instance()
            for dev in registry.list_devices():
                online = dev.is_online()
                # Serialize capabilities: DeviceCapability objects → strings / dicts
                caps = []
                for c in (dev.capabilities or []):
                    if hasattr(c, "to_dict"):
                        caps.append(c.to_dict())
                    elif hasattr(c, "name"):
                        caps.append(c.name)
                    else:
                        caps.append(str(c))
                registered_devices.append({
                    "device_id": dev.device_id,
                    "device_type": dev.device_type,
                    "online": online,
                    "status": dev.status.value,
                    "last_seen": dev.last_seen,
                    "capabilities": caps,
                })
                if online:
                    online_count += 1
        except Exception as exc:
            logger.debug("gateway_status registry error: %s", exc)

        router_stats: dict = {}
        try:
            from core.command_router import get_command_router
            router_stats = get_command_router().get_stats()
        except Exception as exc:
            logger.debug("gateway_status router error: %s", exc)

        return JSONResponse({
            "websocket_active_devices": active_ws,
            "websocket_active_count": len(active_ws),
            "registered_devices": registered_devices,
            "registered_count": len(registered_devices),
            "online_count": online_count,
            "command_router_stats": router_stats,
        })

    # ── 近期工具 / 设备调用 ───────────────────────────────────────────────

    @router.get("/api/v1/observability/recent-calls")
    async def recent_calls(
        limit: int = Query(default=50, ge=1, le=200, description="返回条数"),
    ):
        """
        近期工具 / 设备调用记录（来自 GatewayTraceStore）。

        最新的 limit 条，按时间倒序排列。
        """
        try:
            from core.command_router import get_gateway_trace_store
            store = get_gateway_trace_store()
            entries = store.recent(limit)
            return JSONResponse({
                "count": len(entries),
                "calls": entries,
            })
        except Exception as exc:
            logger.warning("observability/recent-calls error: %s", exc)
            return JSONResponse({"error": str(exc), "count": 0, "calls": []})

    # ── Trace 查询（按 task_id 或 command_id）────────────────────────────

    @router.get("/api/v1/observability/trace/{trace_id}")
    async def trace_lookup(
        trace_id: str,
        id_type: Optional[str] = Query(
            default=None,
            description="'task_id' 或 'command_id'，不传时自动尝试两者",
        ),
    ):
        """
        按 task_id 或 command_id 查询 trace 记录。

        - 传 id_type=task_id：返回该 task 下的所有命令 trace 列表
        - 传 id_type=command_id：返回单条 trace
        - 不传 id_type：先按 command_id 查，未命中再按 task_id 查
        """
        try:
            from core.command_router import get_gateway_trace_store
            store = get_gateway_trace_store()

            if id_type == "command_id":
                entry = store.lookup_by_command_id(trace_id)
                if entry is None:
                    return JSONResponse(
                        {"found": False, "trace_id": trace_id, "id_type": "command_id"},
                        status_code=404,
                    )
                return JSONResponse({"found": True, "id_type": "command_id", "trace": entry})

            if id_type == "task_id":
                entries = store.lookup_by_task_id(trace_id)
                return JSONResponse({
                    "found": bool(entries),
                    "id_type": "task_id",
                    "count": len(entries),
                    "traces": entries,
                })

            # 自动尝试：先 command_id，再 task_id
            entry = store.lookup_by_command_id(trace_id)
            if entry is not None:
                return JSONResponse({"found": True, "id_type": "command_id", "trace": entry})

            entries = store.lookup_by_task_id(trace_id)
            return JSONResponse({
                "found": bool(entries),
                "id_type": "task_id",
                "count": len(entries),
                "traces": entries,
            })

        except Exception as exc:
            logger.warning("observability/trace error: %s", exc)
            return JSONResponse({"error": str(exc), "found": False}, status_code=500)

    # ── Trace 统计 ────────────────────────────────────────────────────────

    @router.get("/api/v1/observability/stats")
    async def observability_stats():
        """
        GatewayTraceStore 整体统计信息。

        返回 total_recorded / total_success / total_failed /
        unique_command_ids / unique_task_ids。
        """
        try:
            from core.command_router import get_gateway_trace_store
            store = get_gateway_trace_store()
            return JSONResponse(store.stats())
        except Exception as exc:
            logger.warning("observability/stats error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    # ── Phase E: NATS Bus health ──────────────────────────────────────────

    @router.get("/health/nats")
    async def nats_health():
        """NATS control-plane health — bus stats, connection status, subscriptions.

        Returns::

            {
              "status": "connected" | "disconnected" | "noop",
              "noop_mode": bool,
              "bus": { "connected": bool, "published": int, ... },
              "master_brain": { "started": bool, "workers": int, ... } | null
            }
        """
        try:
            from core.nats_bus import nats_bus
            bus_stats = nats_bus.get_stats()
        except Exception as exc:
            bus_stats = {"error": str(exc)}

        brain_status = None
        try:
            if os.environ.get("GALAXY_MASTER_BRAIN_ENABLED", "").lower() in ("true", "1"):
                from core.master_brain import get_master_brain
                brain = get_master_brain()
                if brain is not None:
                    brain_status = brain.get_status()
        except Exception:
            pass

        connected = bus_stats.get("connected", False)
        noop = bus_stats.get("noop_mode", True)
        status = "noop" if noop else ("connected" if connected else "disconnected")
        return JSONResponse({
            "status": status,
            "noop_mode": noop,
            "bus": bus_stats,
            "master_brain": brain_status,
        })

    @router.get("/api/v1/observability/nats")
    async def nats_observability():
        """NATS Bus + MasterBrain topology and statistics (Phase E).

        Returns bus stats, worker topology, recent events, and NATSExecutor stats.
        """
        result: dict = {}

        try:
            from core.nats_bus import nats_bus
            result["bus"] = nats_bus.get_stats()
        except Exception as exc:
            result["bus"] = {"error": str(exc)}

        try:
            if os.environ.get("GALAXY_MASTER_BRAIN_ENABLED", "").lower() in ("true", "1"):
                from core.master_brain import get_master_brain
                brain = get_master_brain()
                if brain is not None:
                    result["topology"] = brain.get_worker_topology()
                    result["master_brain"] = brain.get_status()
        except Exception as exc:
            result["topology"] = {"error": str(exc)}

        try:
            from core.command_router import get_nats_executor
            nats_exec = get_nats_executor()
            result["nats_executor"] = nats_exec.get_stats()
        except Exception as exc:
            result["nats_executor"] = {"error": str(exc)}

        return JSONResponse(result)

    @router.get("/api/v1/observability/bus-events")
    async def bus_events(limit: int = Query(default=50, le=200)):
        """Recent NATS bus events from the EventBus (Phase E).

        Returns the last *limit* events related to NATS connectivity and workers.
        """
        try:
            from integration.event_bus import event_bus
            # event_bus.recent_events() if it exists, otherwise fall back to stats
            if hasattr(event_bus, "recent_events"):
                events = event_bus.recent_events(limit=limit)
            elif hasattr(event_bus, "get_stats"):
                events = event_bus.get_stats()
            else:
                events = {}
            return JSONResponse({"events": events})
        except Exception as exc:
            logger.warning("bus-events error: %s", exc)
            return JSONResponse({"error": str(exc), "events": []}, status_code=500)

    return router
