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
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: 相位/presence 聚合失败: %s", exc)

        # 修复:build_unified_panel_payload() 算出的 tri_state_phase 走的是
        # DesktopPresenceRuntime._continuum_state(单例上从未被赋值)→ 兜底走
        # core.cognitive_field_engine(模块路径本身就是错的,ModuleNotFoundError
        # 被静默吞掉)这条死路径,结果这个字段【永远是 "silent"】——WS 断线重连
        # 期间(App.tsx 会退回到 IPC feed)面板因此被错误拉回"待机",跟桌面
        # 覆盖层实际显示的相位完全脱节。这里改用 GalaxyPresenceBridge 的真实
        # 实时状态(同一份驱动覆盖层"暖金氛围光"的状态)覆盖掉上面这个死值，
        # 让面板与覆盖层从同一个真相来源读数据。
        try:
            from core.lumiv_websocket_bridge import get_current_phase
            feed["tri_state_phase"] = get_current_phase()
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: 相位覆盖失败,沿用聚合值: %s", exc)

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
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: MCP/Skills 聚合失败: %s", exc)

        # LLM 路由 active providers
        try:
            from core.multi_llm_router import get_llm_router
            r = get_llm_router()
            provs = list(getattr(r, "providers", {}) or {})
            if provs:
                feed["llm_routing"] = {"active_providers": provs, "last_model_used": getattr(r, "_last_model", "") or ""}
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: LLM 路由聚合失败: %s", exc)

        # OpenClawd 运行状态
        #
        # 修复:get_openclawd().get_status() 实际返回的是嵌套结构
        # {"openclawd": {"initialized", "request_count", "uptime_seconds", ...},
        #  "agent_factory": {"total_agents", "by_state", ...}, "llm_router": {...}, ...}——
        # 之前这里直接 st.get("runtime_state")/st.get("phase")/st.get("active_tasks") 等
        # 顶层键从来就不存在,每次都无声地落到 .get(..., 默认值),导致面板"运行"永远显示
        # RUNNING、"任务"永远是 0 活跃、诊断抽屉 uptime 永远是 0s——看起来像实时遥测,
        # 实际是写死的默认值。这里改成从真实嵌套字段取。
        try:
            from core.openclawd import get_openclawd
            st = await get_openclawd().get_status()
            if isinstance(st, dict):
                oc = st.get("openclawd", {}) or {}
                by_state = (st.get("agent_factory", {}) or {}).get("by_state", {}) or {}
                active_agent_states = ("working", "waiting", "splitting")
                # 设备计数统一读 UDM(SSOT):端设备(手机/手表/PC 等非 iot)与
                # 智能设备(iot:HA 镜像 + mDNS 发现)分开计,语义不混;UDM 不可用
                # 时回退 legacy registered_devices 缓存(旧行为)。
                smart_devices = 0
                try:
                    from core.unified.device_manager import get_unified_device_manager
                    _all = get_unified_device_manager().list_devices() or []
                    smart_devices = sum(
                        1 for d in _all
                        if str(getattr(d, "device_type", "")) == "iot" and d.is_online()
                    )
                    connected_devices = sum(
                        1 for d in _all
                        if str(getattr(d, "device_type", "")) != "iot" and d.is_online()
                    )
                except Exception:  # noqa: BLE001
                    try:
                        from core.routes._shared import registered_devices as _rd
                        connected_devices = len(_rd)
                    except Exception:  # noqa: BLE001
                        connected_devices = 0
                try:
                    from core.nats_bus import get_nats_bus as _get_bus
                    last_tick = int(_get_bus().get_stats().get("messages_received", 0))
                except Exception:  # noqa: BLE001
                    last_tick = 0
                feed["openclawd_status"] = {
                    "runtimeState": "RUNNING" if oc.get("initialized") else "RESTARTING",
                    "phase": feed.get("tri_state_phase", "silent"),
                    "coherence": feed.get("coherence", 0.0),
                    "activeTasks": sum(by_state.get(s, 0) for s in active_agent_states),
                    "completedTasks": by_state.get("completed", 0),
                    "connectedDevices": connected_devices,
                    "smartDevices": smart_devices,
                    "lastTick": last_tick,
                    "uptime": oc.get("uptime_seconds", 0),
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: OpenClawd 状态聚合失败: %s", exc)

        # 智能设备明细(UDM SSOT 里的 iot 设备:HA 镜像 + mDNS 发现),在线优先,
        # 封顶 50 条防大家庭刷爆 feed。面板「维态·设备网格」tab 据此渲染明细。
        try:
            from core.unified.device_manager import get_unified_device_manager
            _iot = [
                d for d in (get_unified_device_manager().list_devices() or [])
                if str(getattr(d, "device_type", "")) == "iot"
            ]
            _iot.sort(key=lambda d: (not d.is_online(), d.device_name or d.device_id))
            feed["smart_devices"] = [
                {
                    "deviceId": d.device_id,
                    "name": d.device_name or d.device_id,
                    "domain": (d.metadata or {}).get("ha_domain")
                    or (d.metadata or {}).get("service_type", ""),
                    "state": (d.metadata or {}).get("ha_state", ""),
                    "online": d.is_online(),
                    "protocol": (d.metadata or {}).get("protocol", ""),
                }
                for d in _iot[:50]
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: 智能设备明细聚合失败: %s", exc)
            feed["smart_devices"] = []

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
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: 节点拓扑聚合失败: %s", exc)

        # Mesh 会话（NATS bus 连接状态 + BodyMeshRegistry 真实参与者）
        try:
            from core.nats_bus import get_nats_bus
            import time as _time
            bus = get_nats_bus()
            stats = bus.get_stats()
            noop = bool(stats.get("noop_mode"))
            connected = bool(stats.get("connected"))

            # 修复:之前 participants 无条件写死 []、barrierStatus 无条件写死 "open"——
            # NATS bus 本身只是消息总线,没有"参与者"/"barrier"概念,之前的 "open" 纯属
            # 编造。真实的 mesh 参与者来自 BodyMeshRegistry(设备注册进 mesh 时写入),
            # 这里改成读它的真实条目;没有条目时诚实显示空列表 + "n/a",不再编造状态。
            participants = []
            try:
                from core.mesh.body_mesh_registry import get_body_mesh_registry
                for entry in get_body_mesh_registry().list_entries():
                    roles = sorted(r.value for r in entry.roles)
                    participants.append({
                        "nodeId": entry.device_id,
                        "role": roles[0] if roles else "participant",
                        "status": "active" if entry.session_id else "idle",
                        "lastSeen": int(entry.registered_at * 1000),
                    })
            except Exception:  # noqa: BLE001
                pass

            feed["mesh_session"] = {
                "sessionId": "local" if noop else "nats-mesh",
                "status": "closed" if noop else ("active" if connected else "pending"),
                "barrierStatus": "active" if participants else "n/a",
                "tickSequence": stats.get("messages_received", 0),
                "participants": participants,
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
        except Exception as exc:  # noqa: BLE001
            # 无 NATS 时返回空列表，不伪造
            logger.debug("panel feed: Mesh/NATS 聚合失败: %s", exc)
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
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: 成本汇总聚合失败: %s", exc)

        # URL 哨兵抓到的"缺协议头请求 URL"记录 → 面板 DiagnosticsDrawer 里直接展示,
        # 让用户在面板上就能看到并复制,不必去翻 logs/lumiv.log。平时为空、零打扰。
        try:
            from core.ollama_url_sentinel import recent_catches
            feed["diagnostics"] = [
                {
                    "ts": c.get("ts", ""),
                    "url": c.get("url", ""),
                    "culprit": c.get("culprit", ""),
                }
                for c in recent_catches()
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: 诊断哨兵聚合失败: %s", exc)

        # 启动每阶段耗时 → 面板「⏱ 启动耗时」展示,定位"加载半天"卡在哪段。
        try:
            from core.startup_timing import recent_timings
            feed["startup_timing"] = list(recent_timings())
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed: 启动计时聚合失败: %s", exc)

        return JSONResponse(content={"success": True, "feed": feed})

    @router.get("/api/v1/diagnostics/url-sentinel")
    async def get_url_sentinel() -> JSONResponse:
        """URL 哨兵抓到的"缺协议头请求 URL"记录(纯 JSON,方便直接开浏览器看/复制)。

        面板不方便时,浏览器打开 http://<host>:<port>/api/v1/diagnostics/url-sentinel
        即可;平时为空数组。"""
        try:
            from core.ollama_url_sentinel import recent_catches
            catches = recent_catches()
        except Exception:  # noqa: BLE001
            catches = []
        return JSONResponse(content={"success": True, "count": len(catches), "catches": catches})

    @router.get("/api/v1/diagnostics/startup-timing")
    async def get_startup_timing() -> JSONResponse:
        """本次启动各阶段耗时(纯 JSON,浏览器可直接开)。定位"加载半天"卡哪段。"""
        try:
            from core.startup_timing import recent_timings
            timings = list(recent_timings())
        except Exception:  # noqa: BLE001
            timings = []
        return JSONResponse(content={"success": True, "count": len(timings), "timings": timings})

    return router
