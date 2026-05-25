"""
Galaxy - Observability Routes (PR-C / Phase E / PR-7)
======================================================

**Output authority notice**
----------------------------
The endpoints in this module are **operational observability endpoints**.
They surface live diagnostic information about routing, gateway, NATS bus,
and trace state for dashboard/debugging consumers.

For canonical projection truth (topology, routing, OneAPI, continuum posture),
use the dedicated projection endpoints instead:

    GET /api/v1/projection/runtime-truth
        ← core.projection.runtime_truth_compiler.compile_runtime_truth()
        ← RUNTIME_TRUTH_COMPILER_AUTHORITY sentinel (canonical)

    GET /api/v1/projection/desktop-status-board
        ← canonical integrated desktop status board payload (PR-8)

The ``/api/v1/observability/model-route`` endpoint in this module exposes
live routing diagnostics sourced directly from ``MultiLLMRouter`` (legacy/
compatibility diagnostic surface).  For canonical routing truth, prefer
the ``topology`` block in ``GET /api/v1/projection/runtime-truth``.

See ``docs/PROJECTION_OUTPUT_AUTHORITY.md`` for the full canonical output
authority model and endpoint directory.

Dashboard 可观测性端点，提供：
  - 活跃模型路由及 Fallback 状态 (兼容性/诊断用途)
  - 网关 / 设备在线状态
  - 近期工具 / 设备调用记录
  - 按 task_id 或 command_id 查询 trace
  - NATS Bus 健康与统计 (Phase E)
  - 统一执行观测模式 schema (PR-7, read-only, additive)

Routes:
  GET /api/v1/observability/model-route              - 活跃 LLM 路由 + Fallback（兼容诊断）
  GET /api/v1/observability/gateway                  - 网关 & 设备在线状态汇总
  GET /api/v1/observability/recent-calls             - 近期工具 / 设备调用（最多 50 条）
  GET /api/v1/observability/trace/{id}               - 按 task_id 或 command_id 查 trace
  GET /api/v1/observability/stats                    - trace 存储统计
  GET /health/nats                                   - NATS bus 连接状态与统计 (Phase E)
  GET /api/v1/observability/nats                     - NATS bus + MasterBrain 拓扑 (Phase E)
  GET /api/v1/observability/bus-events               - 最近 NATS 总线事件 (Phase E)
  GET /api/v1/observability/execution/schema         - 统一执行 schema 元数据 (PR-7)
  GET /api/v1/observability/execution/recent-events  - 最近统一执行事件 (PR-7)
  GET /api/v1/observability/execution/trace/{id}     - 统一 trace 上下文查询 (PR-7)
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
        活跃模型路由及 Fallback 状态（兼容性诊断端点）。

        **Compatibility notice**: This endpoint sources routing data directly
        from ``MultiLLMRouter`` for diagnostic/legacy dashboard consumers.
        For canonical routing truth assembled through the single projection
        path, prefer ``GET /api/v1/projection/runtime-truth`` (topology block)
        or ``GET /api/v1/projection/desktop-status-board`` (integrated payload).

        返回当前 MultiLLMRouter 的默认模型、所有提供商状态（含 fallback 列表）
        以及最近一次路由决策。
        """
        try:
            from core.llm.route_authority import get_llm_route_authority
            router_inst = get_llm_route_authority().execution_router
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
            from core.nats_posture import evaluate_nats_posture, build_default_posture_snapshot
            posture = evaluate_nats_posture()
            bus_stats = posture.get("bus", {})
        except Exception as exc:
            posture = build_default_posture_snapshot()
            bus_stats = {"error": str(exc)}

        brain_status = None
        try:
            from core.master_brain import master_brain_enabled

            if master_brain_enabled():
                from core.master_brain import get_master_brain
                brain = get_master_brain()
                if brain is not None:
                    brain_status = brain.get_status()
        except Exception:
            pass

        connected = posture.get("connected", bus_stats.get("connected", False))
        noop = posture.get("noop_mode", bus_stats.get("noop_mode", True))
        status = "noop" if noop else ("connected" if connected else "disconnected")
        nats_required = bool(posture.get("required", False))
        system_mode = str(posture.get("system_mode", "desktop-local"))
        _posture_nats_url = posture.get("nats_url")
        nats_url = str(
            _posture_nats_url
            if _posture_nats_url is not None
            else os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222")
        )

        if connected:
            message = "NATS is connected and operating as the internal scheduling mainline."
        elif nats_required:
            message = (
                f"[ERROR] NATS is REQUIRED (fabric_strict mode) but not connected to {nats_url}. "
                "Start NATS: nats-server -p 4222"
            )
        else:
            message = (
                f"NATS is not connected ({nats_url}). "
                f"System is running in '{system_mode}' mode — NATS is optional."
            )

        return JSONResponse({
            "status": status,
            "system_mode": system_mode,
            "required": nats_required,
            "posture": posture.get("posture"),
            "assertion_ok": posture.get("assertion_ok", True),
            "violation_reason": posture.get("violation_reason", ""),
            "nats_url": nats_url,
            "noop_mode": noop,
            "bus": bus_stats,
            "master_brain": brain_status,
            "message": message,
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
            from core.master_brain import master_brain_enabled

            if master_brain_enabled():
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

    # ── PR-7: Unified Execution Observability (read-only, additive) ──────

    @router.get("/api/v1/observability/execution/schema")
    async def execution_schema_meta():
        """Return metadata describing the unified execution observability schema.

        Exposes the stable enum values for :class:`ExecutorLevel` and
        :class:`FallbackReason` so that consumers can validate / display
        them without importing Python modules.

        This endpoint is read-only and additive (PR-7).
        """
        try:
            from core.execution_observability import ExecutorLevel, FallbackReason

            return JSONResponse({
                "schema_version": "pr7-v1",
                "executor_levels": [e.value for e in ExecutorLevel],
                "fallback_reasons": [r.value for r in FallbackReason],
                "trace_fields": [
                    "trace_id",
                    "runtime_session_id",
                    "task_id",
                    "action_id",
                ],
                "event_fields": [
                    "event_id",
                    "timestamp",
                    "trace",
                    "executor_level",
                    "fallback",
                    "tri_state_phase",
                    "runtime_domain",
                    "message",
                    "metadata",
                ],
                "description": (
                    "Unified execution observability schema (PR-7). "
                    "Use normalizers from core.execution_observability.normalizers "
                    "to convert existing path payloads into ExecutionEvent objects."
                ),
            })
        except Exception as exc:
            logger.warning("execution/schema error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    @router.get("/api/v1/observability/execution/recent-events")
    async def execution_recent_events(
        limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
    ):
        """Return the most recent unified execution events from GatewayTraceStore.

        Normalises existing ``GatewayTraceStore`` records into the PR-7
        :class:`~core.execution_observability.ExecutionEvent` schema.

        This endpoint is read-only and additive (PR-7).
        """
        try:
            from core.command_router import get_gateway_trace_store
            from core.execution_observability.normalizers import normalize_observability_payload

            store = get_gateway_trace_store()
            raw_entries = store.recent(limit)
            events = []
            for entry in raw_entries:
                try:
                    ev = normalize_observability_payload(entry)
                    events.append(ev.to_dict())
                except Exception as inner_exc:
                    logger.debug("execution/recent-events: normalise error: %s", inner_exc)
                    events.append({"raw": entry, "normalise_error": str(inner_exc)})

            return JSONResponse({
                "count": len(events),
                "schema_version": "pr7-v1",
                "events": events,
            })
        except Exception as exc:
            logger.warning("execution/recent-events error: %s", exc)
            return JSONResponse({"error": str(exc), "count": 0, "events": []})

    @router.get("/api/v1/observability/execution/trace/{trace_id}")
    async def execution_trace_lookup(
        trace_id: str,
    ):
        """Look up a unified execution trace by trace_id / task_id / command_id.

        Normalises the raw GatewayTraceStore result into the PR-7
        :class:`~core.execution_observability.TraceCorrelation` shape so
        that callers get a consistent envelope regardless of which orchestration
        path originated the trace.

        This endpoint is read-only and additive (PR-7).
        """
        try:
            from core.command_router import get_gateway_trace_store
            from core.execution_observability import TraceCorrelation
            from core.execution_observability.normalizers import normalize_observability_payload

            store = get_gateway_trace_store()

            # Try command_id first, then task_id (mirrors existing trace endpoint)
            entry = store.lookup_by_command_id(trace_id)
            if entry is not None:
                ev = normalize_observability_payload(entry)
                return JSONResponse({
                    "found": True,
                    "id_type": "command_id",
                    "schema_version": "pr7-v1",
                    "trace": ev.trace.to_dict(),
                    "event": ev.to_dict(),
                })

            entries = store.lookup_by_task_id(trace_id)
            if entries:
                # Return the trace correlation from the first entry; all share
                # the same task_id so traces are consistent.
                events = []
                for raw in entries:
                    try:
                        ev = normalize_observability_payload(raw)
                        events.append(ev.to_dict())
                    except Exception:
                        events.append({"raw": raw})
                first_trace = TraceCorrelation(
                    trace_id=entries[0].get("trace_id", trace_id),
                    runtime_session_id=entries[0].get("runtime_session_id", ""),
                    task_id=trace_id,
                ).to_dict()
                return JSONResponse({
                    "found": True,
                    "id_type": "task_id",
                    "schema_version": "pr7-v1",
                    "trace": first_trace,
                    "count": len(events),
                    "events": events,
                })

            return JSONResponse(
                {
                    "found": False,
                    "trace_id": trace_id,
                    "schema_version": "pr7-v1",
                },
                status_code=404,
            )
        except Exception as exc:
            logger.warning("execution/trace error: %s", exc)
            return JSONResponse({"error": str(exc), "found": False}, status_code=500)

    # ── PR-10: Orchestration Review Surface ───────────────────────────────

    @router.get("/api/v1/observability/orchestration-review")
    async def orchestration_review():
        """Return the V2 orchestration operator review snapshot (PR-10).

        Closes the observability and operator-review gaps described in PR-10
        by exposing a unified, read-only review surface that consolidates:

        - **execution_path_summary** — why the current execution path was
          chosen or rejected (sourced from
          ``core.runtime_decision_observability``).
        - **fallback_cascade** — full ordered degradation trace showing each
          fallback step, its reason, and the final execution tier (sourced from
          ``core.execution_observability.fallback_schema`` and
          ``core.windows_execution_arbiter``).
        - **recovery_review** — how the most recent interrupted execution was
          handled: decision kind, resumability, interruption class/reason, and
          resume attempt count (sourced from
          ``core.runtime.runtime_observability_sink``).
        - **reconciliation_review** — whether the most recent Android advisory
          truth update was accepted, rejected (V2 terminal state wins), or
          partially applied (sourced from
          ``core.android_participant_truth_ingress``).
        - **legacy_dispatch** — counters for LEGACY_DISPATCH compat surface
          invocations (closes COMPAT-007).

        **Authority boundary**

        This endpoint is **read-only and observational**.  It does not
        re-compute or replace any canonical decision logic.  Fields are
        annotated with ``source_authority`` to identify the originating
        canonical module.

        See ``docs/ORCHESTRATION_OBSERVABILITY_REVIEW.md`` for the full
        operator guide.
        """
        try:
            from core.orchestration_review_surface import (
                build_orchestration_review_snapshot,
            )

            snapshot = build_orchestration_review_snapshot()
            return JSONResponse(snapshot.to_dict())
        except Exception as exc:
            logger.warning("orchestration-review error: %s", exc)
            return JSONResponse(
                {
                    "error": str(exc),
                    "_partial": True,
                    "_partial_reasons": [f"assembly_error: {exc}"],
                },
                status_code=200,
            )

    @router.get("/api/v1/observability/execution-legibility")
    async def execution_legibility():
        """Return a compact legibility summary for the current execution state (PR-10).

        Provides a single-page operator view covering the four highest-value
        legibility dimensions:

        1. **path** — which execution path is active and why.
        2. **fallback** — whether a fallback occurred and how many steps.
        3. **recovery** — whether the last interruption is resumable.
        4. **legacy_usage** — whether legacy dispatch surfaces are being invoked.

        This endpoint is a **compact projection** of
        ``GET /api/v1/observability/orchestration-review``.  For the full
        structured snapshot, use the orchestration-review endpoint.

        **Authority boundary**: read-only, observational surface only.
        """
        try:
            from core.orchestration_review_surface import (
                build_orchestration_review_snapshot,
            )

            snapshot = build_orchestration_review_snapshot()

            # Build compact legibility dict
            path_info: dict = {}
            if snapshot.execution_path_summary is not None:
                ps = snapshot.execution_path_summary
                path_info = {
                    "execution_path": ps.execution_path,
                    "outcome": ps.outcome,
                    "primary_reason": ps.primary_reason,
                    "hard_gate_active": ps.hard_gate_active,
                }

            fallback_info: dict = {}
            if snapshot.fallback_cascade is not None:
                fc = snapshot.fallback_cascade
                fallback_info = {
                    "had_fallback": fc.had_fallback,
                    "total_steps": fc.total_steps,
                    "final_tier": fc.final_tier,
                    "degraded_from_preferred": fc.degraded_from_preferred,
                }

            recovery_info: dict = {}
            if snapshot.recovery_review is not None:
                rr = snapshot.recovery_review
                recovery_info = {
                    "decision_kind": rr.decision_kind,
                    "is_resumable": rr.is_resumable,
                    "interruption_class": rr.interruption_class,
                    "resume_attempt_count": rr.resume_attempt_count,
                }

            legacy_info: dict = {}
            if snapshot.legacy_dispatch is not None:
                ld = snapshot.legacy_dispatch
                legacy_info = {
                    "total_legacy_dispatch_count": ld.total_legacy_dispatch_count,
                    "per_surface_counts": ld.per_surface_counts,
                }

            return JSONResponse({
                "schema_version": "pr10-v1",
                "assembled_at": snapshot.assembled_at,
                "path": path_info,
                "fallback": fallback_info,
                "recovery": recovery_info,
                "legacy_usage": legacy_info,
                "_partial": snapshot._partial,
            })
        except Exception as exc:
            logger.warning("execution-legibility error: %s", exc)
            return JSONResponse(
                {"error": str(exc), "_partial": True, "schema_version": "pr10-v1"},
                status_code=200,
            )

    # ── PR-4: Execution evidence state (canonical truth observability) ──────

    @router.get("/api/v1/observability/execution/evidence-state")
    async def execution_evidence_state(
        device_id: Optional[str] = Query(default=None, description="Filter by device_id"),
        max_entries: int = Query(default=50, ge=1, le=200, description="Max entries to return"),
    ):
        """
        Canonical execution evidence state for operator observability (PR-4).

        Returns a snapshot of recent execution evidence records showing:
        - What actually executed (evidence state: completed_strong, android_delegated, etc.)
        - How trustworthy the evidence is (trust_level: trusted / provisional / quarantine)
        - The acceptance verdict (accept / accept_provisional / quarantine / reject)
        - Whether the four-step truth chain completed for each result
        - Android-side proof class field presence (cross-repo integration status)
        - Operator-visible warnings for results requiring attention

        This endpoint is the canonical answer to:
        "What actually executed, how trustworthy is the evidence, which result is
        canonical, and does the runtime-visible state reflect that truth consistently?"

        Use this endpoint for operator dashboards, board projections, and any surface
        that needs to distinguish canonically accepted results from provisional or
        quarantined ones.
        """
        try:
            from core.operator_execution_observability_surface import (
                build_operator_execution_observability_snapshot,
                OPERATOR_EXECUTION_OBSERVABILITY_CONTRACT_VERSION,
            )
            snapshot = build_operator_execution_observability_snapshot(
                max_entries=max_entries,
                device_id=device_id or None,
            )
            return JSONResponse(snapshot.to_dict())
        except Exception as exc:
            logger.warning("execution/evidence-state error: %s", exc)
            return JSONResponse(
                {
                    "error": str(exc),
                    "schema_version": "4.0.0",
                    "_partial": True,
                },
                status_code=200,
            )

    @router.get("/api/v1/observability/execution/evidence-state/{task_id}")
    async def execution_evidence_state_for_task(task_id: str):
        """
        Canonical execution evidence state for a specific task_id (PR-4).

        Returns the most recent execution evidence entry for the given task,
        or 404 if no evidence has been recorded for that task.
        """
        try:
            from core.operator_execution_observability_surface import (
                get_latest_operator_evidence_entry_for_task,
            )
            entry = get_latest_operator_evidence_entry_for_task(task_id)
            if entry is None:
                return JSONResponse(
                    {"task_id": task_id, "found": False, "entry": None},
                    status_code=200,
                )
            return JSONResponse({"task_id": task_id, "found": True, "entry": entry.to_dict()})
        except Exception as exc:
            logger.warning("execution/evidence-state/%s error: %s", task_id, exc)
            return JSONResponse(
                {"error": str(exc), "task_id": task_id, "_partial": True},
                status_code=200,
            )

    return router
