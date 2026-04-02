"""
core/cross_device_result_surface.py
=====================================
PR-519: Cross-Device Result Surface Closure.

**Architecture role**
---------------------
This module is the canonical **cross-device result surface authority** that
closes the gap (GAP-517-007) where cross-device execution outcomes remained
as transport-local raw dicts without being normalised into canonical result
structures or surfaced through the runtime/audit/operator layers.

It provides :func:`surface_cross_device_result` — the single function that
must be called at the end of every cross-device execution path to:

1. Normalise the raw result dict into a :class:`~core.cross_device_execution_chain.ResultEnvelope`.
2. Record a :class:`~core.cross_device_execution_chain.ChainExecutionRecord` in
   the :class:`~core.cross_device_execution_chain.CrossDeviceChainSingleton`.
3. Update :class:`~core.task_graph_runtime.TaskGraphRuntime` via
   ``complete_from_result_envelope()``.
4. Emit a :class:`~core.replay_foundation.ReplayEventKind` runtime event to
   :class:`~core.replay_foundation.ReplayFoundation`.
5. Build and return a
   :class:`~core.multi_device_control_integrity.ResultSurfaceRecord` that
   tracks which canonical surfaces were updated and exposes any gaps as
   structured warnings.

Canonical call chain::

    CommandRouter.route_envelope()
        → DeviceRouter.route_task()                (substrate)
            → CrossDeviceCoordinator / dispatch    (substrate)
                → surface_cross_device_result()    ← THIS MODULE
                    → ResultEnvelope
                    → CrossDeviceChainSingleton
                    → TaskGraphRuntime
                    → ReplayFoundation
                    → ResultSurfaceRecord (observability)

Transport/substrate boundary
-----------------------------
This module sits *above* the gateway transport substrate.  The gateway may
produce raw result dicts; this module is responsible for normalising those
dicts into canonical result artifacts.  Gateway transport code must NOT be
modified to depend on this module — only the return-path wiring in
``CrossDeviceCoordinator`` and ``DeviceRouter`` calls ``surface_cross_device_result()``.

Public API
----------
Sentinels::

    CROSS_DEVICE_RESULT_SURFACE_AUTHORITY
    CROSS_DEVICE_RESULT_SURFACE_LAYER_POSITION
    CROSS_DEVICE_RESULT_SURFACE_INTEGRATED
    CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED

Functions::

    surface_cross_device_result(raw_result, *, task_id, device_id, ...) -> ResultSurfaceRecord

Resolves
--------
- **GAP-517-007**: cross-device results normalised and surfaced through
  ``ResultEnvelope``, ``ChainExecutionRecord``, ``TaskGraphRuntime``, and
  ``ReplayFoundation``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Authority sentinel — import from consumer modules to signal write-through
#: into canonical result surfaces.
CROSS_DEVICE_RESULT_SURFACE_AUTHORITY = (
    "CROSS_DEVICE_RESULT_SURFACE::PR519_CANONICAL_RESULT_SURFACE_AUTHORITY_V1"
)

#: Architectural layer position (sits above gateway substrate, layer 12).
CROSS_DEVICE_RESULT_SURFACE_LAYER_POSITION = 12

#: Wiring sentinel — added to cross_device_coordinator.py and device_router.py
#: to signal that their result paths have been integrated with this module.
CROSS_DEVICE_RESULT_SURFACE_INTEGRATED = (
    "CROSS_DEVICE_RESULT_SURFACE::INTEGRATED_V1: "
    "execute_cross_device_task / route_task result paths are wired through "
    "surface_cross_device_result() so that all cross-device execution outcomes "
    "are normalised into ResultEnvelope and surfaced through TaskGraphRuntime, "
    "ReplayFoundation, and CrossDeviceChainSingleton.  Resolves GAP-517-007."
)

#: Gap-resolution sentinel — importable evidence that GAP-517-007 is closed.
CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED = (
    "CROSS_DEVICE_RESULT_SURFACE::GAP_517_007_RESOLVED: "
    "Cross-device results are now normalised into ResultEnvelope and surfaced "
    "through TaskGraphRuntime.complete_from_result_envelope(), "
    "ReplayFoundation runtime events, and CrossDeviceChainSingleton records."
)


# ---------------------------------------------------------------------------
# surface_cross_device_result
# ---------------------------------------------------------------------------

def surface_cross_device_result(
    raw_result: Dict[str, Any],
    *,
    task_id: str = "",
    device_id: str = "",
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    route_mode: str = "cross_device",
    source_device_id: str = "",
    target_device_ids: Optional[List[str]] = None,
    steps_completed: Optional[Any] = None,
    legacy_path_used: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Any:
    """Normalise a raw cross-device execution result and surface it canonically.

    This is the **single exit-point** that every cross-device execution path
    must call before returning a result to its caller.  It ensures that every
    execution outcome is visible through the canonical runtime, audit, and
    operator layers.

    Steps performed (all non-fatal — failures are recorded as surface gaps):

    1. Build a :class:`~core.cross_device_execution_chain.ResultEnvelope` from
       the raw dict using
       :func:`~core.cross_device_execution_chain.build_result_envelope`.
    2. Record a :class:`~core.cross_device_execution_chain.ChainExecutionRecord`
       in the :class:`~core.cross_device_execution_chain.CrossDeviceChainSingleton`
       via :func:`~core.cross_device_execution_chain.record_chain_execution`.
    3. Update :class:`~core.task_graph_runtime.TaskGraphRuntime` via
       ``complete_from_result_envelope()``.
    4. Emit a ``TASK_COMPLETED`` / ``TASK_FAILED`` runtime event to
       :class:`~core.replay_foundation.ReplayFoundation` via
       :func:`~core.replay_foundation.emit_runtime_event`.
    5. Build and return a
       :class:`~core.multi_device_control_integrity.ResultSurfaceRecord`
       tracking which surfaces were updated.

    Parameters
    ----------
    raw_result:
        The raw result dict returned by the executing device/coordinator.
    task_id:
        Canonical task ID.  Taken from ``raw_result["task_id"]`` if omitted.
    device_id:
        Target device that executed the task.
    trace_id:
        Distributed trace ID.
    session_id:
        Session ID.
    route_mode:
        Routing mode (e.g. ``"cross_device"``, ``"multi_device"``).
    source_device_id:
        Device that originated the request (for audit records).
    target_device_ids:
        All devices that participated in execution.
    steps_completed:
        Explicit list of :class:`~core.cross_device_execution_chain.CanonicalChainStep`
        values; defaults to the full canonical chain.
    legacy_path_used:
        Name of legacy path, if any.
    extra:
        Additional metadata for chain record / surface record.

    Returns
    -------
    ResultSurfaceRecord
        A record describing which canonical surfaces were updated and any
        surface gaps detected.
    """
    _extra = extra or {}
    _task_id = task_id or raw_result.get("task_id", "")
    _device_id = device_id or raw_result.get("device_id", "")
    _trace_id = trace_id or raw_result.get("trace_id")
    _target_ids = list(target_device_ids or ([_device_id] if _device_id else []))

    envelope = None
    chain_record = None
    graph_updated = False
    replay_updated = False
    surface_gap_reasons: List[str] = []

    # ── Step 1: Build ResultEnvelope ──────────────────────────────────────
    try:
        from core.cross_device_execution_chain import build_result_envelope
        envelope = build_result_envelope(
            raw_result,
            task_id=_task_id,
            device_id=_device_id,
            route_mode=route_mode,
            trace_id=_trace_id,
            session_id=session_id,
        )
    except Exception as exc:
        logger.warning(
            "surface_cross_device_result: build_result_envelope failed "
            "(task_id=%s): %s",
            _task_id,
            exc,
        )
        surface_gap_reasons.append(
            f"GAP-517-007: ResultEnvelope build failed: {exc}"
        )

    # ── Step 2: Record ChainExecutionRecord ───────────────────────────────
    try:
        from core.cross_device_execution_chain import record_chain_execution
        chain_record = record_chain_execution(
            task_id=_task_id,
            trace_id=_trace_id,
            device_id=_device_id,
            route_mode=route_mode,
            steps_completed=steps_completed,
            legacy_path_used=legacy_path_used,
            result_envelope=envelope,
            extra=_extra,
        )
    except Exception as exc:
        logger.warning(
            "surface_cross_device_result: record_chain_execution failed "
            "(task_id=%s): %s",
            _task_id,
            exc,
        )
        surface_gap_reasons.append(
            f"GAP-517-007: chain_execution record failed: {exc}"
        )

    # ── Step 3: Update TaskGraphRuntime ───────────────────────────────────
    if envelope is not None and _task_id:
        try:
            from core.task_graph_runtime import (
                get_task_graph_runtime,
                WorkflowContributorKind,
            )
            tgr = get_task_graph_runtime()
            # If the task is not yet in the graph, register a minimal node so
            # complete_from_result_envelope() can transition it.
            if tgr.get_node_by_task_id(_task_id) is None:
                from core.task_graph_runtime import GraphNode, GraphNodeState
                _node = GraphNode(
                    node_id=_task_id,
                    task_id=_task_id,
                    trace_id=_trace_id or "",
                    device_id=_device_id,
                    contributor=WorkflowContributorKind.COMMAND_ROUTER,
                    state=GraphNodeState.RUNNING,
                )
                tgr.register_node(_node)
            tgr.complete_from_result_envelope(
                envelope,
                contributor=WorkflowContributorKind.COMMAND_ROUTER,
            )
            graph_updated = True
        except Exception as exc:
            logger.warning(
                "surface_cross_device_result: TaskGraphRuntime update failed "
                "(task_id=%s): %s",
                _task_id,
                exc,
            )
            surface_gap_reasons.append(
                f"GAP-517-007: TaskGraphRuntime update failed: {exc}"
            )

    # ── Step 4: Emit to ReplayFoundation ──────────────────────────────────
    if _task_id:
        try:
            from core.replay_foundation import emit_runtime_event, ReplayEventKind
            _success = envelope.success if envelope is not None else bool(
                raw_result.get("success", False)
            )
            _event_kind = (
                ReplayEventKind.TASK_COMPLETED
                if _success
                else ReplayEventKind.TASK_FAILED
            )
            emit_runtime_event(
                _event_kind,
                task_id=_task_id,
                trace_id=_trace_id or "",
                source="cross_device_result_surface",
            )
            replay_updated = True
        except Exception as exc:
            logger.warning(
                "surface_cross_device_result: ReplayFoundation emit failed "
                "(task_id=%s): %s",
                _task_id,
                exc,
            )
            surface_gap_reasons.append(
                f"GAP-517-007: ReplayFoundation emit failed: {exc}"
            )

    # ── Step 5: Build ResultSurfaceRecord ─────────────────────────────────
    # OperatorSurface is a read-only projection of TaskGraphRuntime — updating
    # TGR (step 3) means OperatorSurface will reflect the result on its next
    # query.  Mark operator_surface_updated=graph_updated accordingly.
    try:
        from core.multi_device_control_integrity import build_result_surface_record
        surface_record = build_result_surface_record(
            task_id=_task_id,
            trace_id=_trace_id,
            source_device_id=source_device_id,
            target_device_ids=_target_ids,
            result_envelope_produced=(envelope is not None),
            operator_surface_updated=graph_updated,  # TGR-backed; readable via OperatorSurface
            task_graph_updated=graph_updated,
            replay_foundation_updated=replay_updated,
            projection_updated=False,  # projection reads from TGR; no direct write needed
            surface_gap_reasons=surface_gap_reasons,
            extra={
                "route_mode": route_mode,
                "legacy_path_used": legacy_path_used,
                "chain_record_id": (
                    chain_record.record_id if chain_record is not None else ""
                ),
                **_extra,
            },
        )
    except Exception as exc:
        logger.warning(
            "surface_cross_device_result: ResultSurfaceRecord build failed "
            "(task_id=%s): %s",
            _task_id,
            exc,
        )
        # Return a minimal fallback object
        from types import SimpleNamespace
        surface_record = SimpleNamespace(
            task_id=_task_id,
            is_canonically_surfaced=False,
            surface_gap_reasons=surface_gap_reasons + [str(exc)],
            result_envelope_produced=(envelope is not None),
            task_graph_updated=graph_updated,
            replay_foundation_updated=replay_updated,
        )

    if surface_gap_reasons:
        logger.warning(
            "surface_cross_device_result: incomplete surface coverage "
            "task_id=%s gaps=%s",
            _task_id,
            surface_gap_reasons,
        )
    else:
        logger.debug(
            "surface_cross_device_result: all surfaces updated task_id=%s "
            "graph=%s replay=%s",
            _task_id,
            graph_updated,
            replay_updated,
        )

    return surface_record
