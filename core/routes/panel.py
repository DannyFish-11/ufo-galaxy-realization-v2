"""
core/routes/panel.py
=====================
PR-1: Unified Panel API Route — GET /api/v1/panel/unified

Exposes the single canonical unified runtime/panel aggregation endpoint.
Downstream consumers (CLI status boards, Windows GUI, Android app, dashboard)
MUST read from this endpoint instead of fanning out across multiple separate
operator, projection, and Android-ecosystem endpoints.

Routes
------
  GET /api/v1/panel/unified
      Returns the current :class:`~core.unified_panel_aggregation.UnifiedPanelPayload`
      as a JSON object.  The payload aggregates all canonical state families:

      - Operator/control-plane projection (task counts, device presence,
        topology, capability providers, active flow count).
      - Shell/presence manifestation (desktop_shell_state, presence_tristate,
        manifestation_summary).
      - Android runtime/ecosystem state (ecosystem counts + per-device
        execution-phase digest sourced from android_device_state_store).
      - Continuum/flow execution state (tri_state_phase, runtime_domain,
        presence_intensity, coherence).
      - Execution readiness verdict (READY/BLOCKED/DEGRADED/UNKNOWN).
      - Active surface spec (SurfaceType for the current interaction mode).

      Query parameters:
          mode (str, default "chat"): Interaction mode forwarded to
              SurfaceSelector for the active_surface_spec field.

Design constraints
------------------
- **Read-only** — this router never writes state, sends commands, or triggers
  actions.
- **Single aggregation surface** — all sub-state is assembled by
  :mod:`~core.unified_panel_aggregation`, which reads from canonical singletons
  and does NOT introduce a second truth store.
- **Graceful degradation** — if any sub-source is unavailable its section is
  left at default empty/zero values and the endpoint still returns 200.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.Panel")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

PANEL_ROUTES_AUTHORITY: str = (
    "PANEL_ROUTES_V1: core/routes/panel.py is the canonical owner of the "
    "/api/v1/panel/* route surface.  All handlers consume "
    "UnifiedPanelAggregationService projections — no raw subsystem internals."
)


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the unified panel router.

    The ``service_manager`` and ``config`` parameters are accepted for
    signature compatibility with all other ``core/routes/`` module factories
    (see ``core/api_routes.py``).  They are intentionally unused here because
    this router's only handler delegates entirely to
    :func:`~core.unified_panel_aggregation.build_unified_panel_payload`, which
    reads from singleton sources directly.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/panel/unified
    # ------------------------------------------------------------------

    @router.get("/api/v1/panel/unified")
    async def get_unified_panel(
        mode: str = Query(default="chat", description="Interaction mode for surface spec"),
    ) -> JSONResponse:
        """Return the canonical unified runtime/panel payload.

        Aggregates operator/control-plane, shell/presence, Android ecosystem,
        continuum/flow execution, execution readiness, and active surface spec
        into a single :class:`~core.unified_panel_aggregation.UnifiedPanelPayload`.

        This is the **single canonical read endpoint** for panel clients.
        Prefer this over calling /api/v1/operator/snapshot,
        /api/v1/projection/runtime, and /api/v1/operator/devices/ecosystem
        separately.

        Query parameters
        ----------------
        mode : str
            Interaction mode string (``chat``, ``deep_thinking``,
            ``control_console``, etc.) forwarded to :class:`SurfaceSelector`
            to set the ``active_surface_spec`` field.  Defaults to ``"chat"``.

        Response schema
        ---------------
        The response is the JSON serialisation of
        :class:`~core.unified_panel_aggregation.UnifiedPanelPayload`.  Key
        families:

        - ``payload_id``, ``generated_at``, ``schema_version`` — identity
        - ``active_task_count``, ``active_flow_count``,
          ``online_device_count``, ... — operator/control-plane
        - ``desktop_shell_state``, ``presence_tristate``,
          ``manifestation_summary`` — shell/presence
        - ``tri_state_phase``, ``runtime_domain``,
          ``presence_intensity``, ``coherence`` — continuum/flow execution
        - ``android_ecosystem``, ``android_device_execution_digest`` — Android
        - ``readiness_verdict``, ``blocked_dimensions`` — execution readiness
        - ``active_surface_spec`` — surface type for ``mode``
        - ``_source`` — provenance authority string
        """
        try:
            from core.unified_panel_aggregation import build_unified_panel_payload
            payload = build_unified_panel_payload(mode=mode)
            return JSONResponse(content=payload.to_dict())
        except Exception as exc:
            logger.error("get_unified_panel endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": PANEL_ROUTES_AUTHORITY},
                status_code=500,
            )

    @router.get("/api/v1/panel/feed")
    async def get_panel_feed() -> JSONResponse:
        """面板实时数据(桌面 Electron 面板的 IPC 契约 snake_case 字段)。

        把真实后端数据(MCP/Skills 来自 CapabilityRegistry、OpenClawd 运行状态、
        LLM 路由 providers、统一记忆后端)聚合成 usePanelData 直接消费的形状。
        每个来源都 best-effort：取不到就略过该字段，前端用其默认值兜底。
        """
        feed: dict = {}

        # 相位 / presence(复用统一面板聚合)
        try:
            from core.unified_panel_aggregation import build_unified_panel_payload
            p = build_unified_panel_payload(mode="chat").to_dict()
            for k in ("tri_state_phase", "presence_intensity", "coherence"):
                if k in p:
                    feed[k] = p[k]
        except Exception:  # noqa: BLE001
            pass

        # MCP 服务器 + Skills(来自 CapabilityRegistry)
        try:
            from core.agent.capability_registry import get_capability_registry
            reg = get_capability_registry()
            mcp_by_server: dict = {}
            for it in reg.list_tools(source="mcp"):
                sid = getattr(it, "source_id", "") or "mcp"
                e = mcp_by_server.setdefault(sid, {"name": sid, "url": "", "status": "online", "toolsCount": 0})
                e["toolsCount"] += 1
                if not e["url"]:
                    e["url"] = (getattr(it, "metadata", {}) or {}).get("url", "")
                if not getattr(it, "available", True):
                    e["status"] = "error"
            if mcp_by_server:
                feed["mcp_servers"] = list(mcp_by_server.values())
            skills = []
            for it in reg.list_tools(source="skill"):
                skills.append({
                    "name": getattr(it, "name", "skill"),
                    "version": (getattr(it, "metadata", {}) or {}).get("version", "1.0.0"),
                    "status": "loaded" if getattr(it, "available", True) else "error",
                    "description": getattr(it, "description", "")[:60],
                })
            # 把"统一记忆"作为一个真实条目并入 skills(取代面板里写死的假 memory)
            try:
                from core.memory import get_unified_memory
                um = get_unified_memory()
                skills.append({
                    "name": "memory",
                    "version": "2.0.0",
                    "status": "loaded" if um.enabled else "unloaded",
                    "description": "统一记忆: " + (",".join(um.backend_names) or "none"),
                })
            except Exception:  # noqa: BLE001
                pass
            if skills:
                feed["skills"] = skills
        except Exception:  # noqa: BLE001
            pass

        # LLM 路由 active providers
        try:
            from core.multi_llm_router import get_llm_router
            r = get_llm_router()
            provs = list(getattr(r, "providers", {}) or {})
            if provs:
                feed["llm_routing"] = {"active_providers": provs, "last_model_used": getattr(r, "_last_model", "") or ""}
        except Exception:  # noqa: BLE001
            pass

        # OpenClawd 运行状态
        try:
            from core.openclawd import get_openclawd
            st = await get_openclawd().get_status()
            if isinstance(st, dict):
                feed["openclawd_status"] = {
                    "runtimeState": str(st.get("runtime_state") or st.get("state") or "RUNNING").upper(),
                    "phase": st.get("phase", "silent"),
                    "coherence": st.get("coherence", 0.95),
                    "activeTasks": st.get("active_tasks", 0),
                    "completedTasks": st.get("completed_tasks", 0),
                    "connectedDevices": st.get("connected_devices", 0),
                    "lastTick": st.get("last_tick", 0),
                    "uptime": st.get("uptime", 0),
                }
        except Exception:  # noqa: BLE001
            pass

        # 节点/设备拓扑（真实设备列表 + 边）
        try:
            from core.routes._shared import registered_devices
            import time as _time
            devs = dict(registered_devices)
            topo_nodes = []
            topo_edges = []
            healthy_cnt = 0
            for did, d in devs.items():
                d = d or {}
                status_raw = str(d.get("status", "online")).lower()
                status = "online" if status_raw in ("online", "healthy", "connected") else \
                         "degraded" if status_raw in ("degraded", "slow") else "offline"
                if status == "online":
                    healthy_cnt += 1
                role_raw = str(d.get("role", d.get("type", "participant"))).lower()
                role = "controller" if "controller" in role_raw or "desktop" in role_raw else \
                       "gateway" if "gateway" in role_raw else \
                       "wearable" if "wear" in role_raw or "watch" in role_raw else "participant"
                topo_nodes.append({
                    "id": did,
                    "label": d.get("name") or d.get("label") or did[:12],
                    "role": role,
                    "status": status,
                    "x": d.get("x", 0.5),
                    "y": d.get("y", 0.5),
                    "lastSeen": d.get("last_seen", int(_time.time() * 1000)),
                    "messageCount": d.get("message_count", 0),
                })
                # 每个设备都通过本机（"desktop_local"）连接
                topo_edges.append({
                    "from": "desktop_local",
                    "to": did,
                    "label": role_raw,
                    "active": status == "online",
                    "messageRate": d.get("message_rate", 0),
                })
            # 本机节点始终存在
            topo_nodes.insert(0, {
                "id": "desktop_local",
                "label": "本机 Desktop",
                "role": "controller",
                "status": "online",
                "x": 0.5,
                "y": 0.15,
                "lastSeen": int(_time.time() * 1000),
                "messageCount": 0,
            })
            feed["node_topology"] = {
                "total_nodes": len(devs),
                "healthy_nodes": healthy_cnt,
                "degraded_nodes": len(devs) - healthy_cnt,
            }
            feed["topology_nodes"] = topo_nodes
            feed["topology_edges"] = topo_edges
        except Exception:  # noqa: BLE001
            pass

        # Mesh 会话（NATS bus 真实状态）
        try:
            from core.nats_bus import get_nats_bus
            import time as _time
            bus = get_nats_bus()
            stats = bus.get_stats()
            noop = bool(stats.get("noop_mode"))
            connected = bool(stats.get("connected"))
            feed["mesh_session"] = {
                "sessionId": "local" if noop else "nats-mesh",
                "status": "closed" if noop else ("active" if connected else "pending"),
                "barrierStatus": "n/a" if noop else "open",
                "tickSequence": stats.get("messages_received", 0),
                "participants": [],
                "createdAt": int(_time.time() * 1000),
            }
            # NATS 订阅主题作为消息日志条目
            subjects = stats.get("active_subjects", [])
            feed["nats_messages"] = [
                {
                    "id": f"sub-{i}",
                    "timestamp": int(_time.time() * 1000),
                    "topic": s,
                    "direction": "in",
                    "payload": "",
                    "msgType": s.split(".")[0] if s else "sub",
                }
                for i, s in enumerate(subjects[:20])
            ]
        except Exception:  # noqa: BLE001
            # 无 NATS 时返回空列表，不伪造
            feed.setdefault("mesh_session", {
                "sessionId": "local",
                "status": "closed",
                "barrierStatus": "n/a",
                "tickSequence": 0,
                "participants": [],
                "createdAt": 0,
            })
            feed.setdefault("nats_messages", [])

        # 成本汇总（真实累计：来自 CostTracker，取代面板里写死的 0）
        try:
            from core.cost_tracker import get_cost_tracker
            cs = get_cost_tracker().get_summary()
            feed["cost_summary"] = {
                "total_usd": round(float(cs.get("total_cost_usd", 0.0)), 6),
                "tokens_input": int(cs.get("total_input_tokens", 0)),
                "tokens_output": int(cs.get("total_output_tokens", 0)),
            }
        except Exception:  # noqa: BLE001
            pass

        return JSONResponse(content={"success": True, "feed": feed})

    return router
