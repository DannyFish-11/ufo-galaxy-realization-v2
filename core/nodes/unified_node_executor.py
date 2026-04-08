"""
core/nodes/unified_node_executor.py
=====================================
Galaxy Unified Node Invocation Executor — PR-35 (post-533 MAIN repo side)

This module is the **single canonical authority** for all node invocation paths.
All entry points that need to execute a local node MUST construct a
:class:`NodeInvocationEnvelope` and call :func:`invoke_node`.

Entry points converged here
---------------------------
- OpenClawd ``node__<id>__<action>`` tool dispatch
- ``POST /api/v1/nodes/call`` HTTP route
- Command-router → node execution bridge
- CapabilityOrchestrator in-process node execution
- SystemIntegration capability-orchestrator node execution (HTTP fallback)

Design goals
------------
- Single execution envelope so every call site carries the same trace fields.
- Single result envelope so downstream consumers can rely on a stable shape.
- Full backward compatibility: ``invoke_node()`` returns the inner ``result``
  dict when a caller only consumes the legacy ``{"success": ..., "result": ...}``
  shape; the full :class:`NodeInvocationResult` is also available.
- Minimal coupling: the module has no hard FastAPI / pydantic dependency.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Nodes.UnifiedNodeExecutor")

# ─────────────────────────────────────────────────────────────────────────────
# Authority / Policy sentinels — PR-35
# ─────────────────────────────────────────────────────────────────────────────

UNIFIED_NODE_INVOCATION_EXECUTOR_AUTHORITY: str = (
    "UNIFIED_NODE_INVOCATION_EXECUTOR::core/nodes/unified_node_executor.py::"
    "package=35::post-533-dual-repo-runtime-unification"
)

UNIFIED_NODE_INVOCATION_EXECUTOR_PR35_SENTINEL: str = (
    "UNIFIED_NODE_INVOCATION_EXECUTOR_PR35::"
    "all-node-invocation-paths-converge-on-invoke_node::"
    "canonical-envelope-and-result-contract::"
    "package=35::post-533-dual-repo-runtime-unification"
)

ALL_NODE_INVOCATION_PATHS_MUST_USE_UNIFIED_EXECUTOR_PR35_POLICY: str = (
    "POLICY::ALL_NODE_INVOCATION_PATHS_MUST_USE_UNIFIED_EXECUTOR_PR35: "
    "Every node invocation entry point (OpenClawd tool dispatch, POST /api/v1/nodes/call, "
    "command-router bridge, capability-orchestrator, system-integration) MUST construct a "
    "NodeInvocationEnvelope and call invoke_node().  Direct calls to _load_node / "
    "_execute_node from these entry points are DEPRECATED; helpers remain available "
    "only for the unified executor itself."
)

INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_CARRIER_PR35_POLICY: str = (
    "POLICY::INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_CARRIER_PR35: "
    "NodeInvocationEnvelope carries request_id, trace_id, task_id, session_id, "
    "invocation_source, and route_mode.  These fields MUST be present on every "
    "node invocation so that logs and traces can identify the invocation source "
    "consistently across all paths."
)

RESULT_ENVELOPE_SHAPE_IS_STABLE_PR35_POLICY: str = (
    "POLICY::RESULT_ENVELOPE_SHAPE_IS_STABLE_PR35: "
    "NodeInvocationResult exposes success, result, error, duration_ms, request_id, "
    "trace_id, node_id, action, and invocation_source.  This shape MUST NOT be "
    "changed in a backward-incompatible way.  Existing consumers relying on the "
    "legacy dict shape {'success': ..., 'result': ..., 'error': ...} are served "
    "by the to_legacy_dict() helper."
)

NO_PARALLEL_NODE_EXECUTION_AUTHORITY_PR35_POLICY: str = (
    "POLICY::NO_PARALLEL_NODE_EXECUTION_AUTHORITY_PR35: "
    "invoke_node() is the sole canonical node execution authority.  No additional "
    "parallel node execution engine, duplicate fusion_entry dispatch loop, or "
    "alternate in-process node call path is introduced by PR-35 or any subsequent "
    "package that builds on it."
)


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class InvocationSource(str, Enum):
    """Identifies which entry point triggered the node invocation."""

    OPENCLAWD_TOOL = "openclawd_tool"          # node__<id>__<action>
    API_NODES_CALL = "api_nodes_call"          # POST /api/v1/nodes/call
    COMMAND_ROUTER = "command_router"          # command-router node bridge
    CAPABILITY_ORCHESTRATOR = "capability_orchestrator"  # CapabilityOrchestrator
    SYSTEM_INTEGRATION = "system_integration"  # SystemIntegration HTTP path
    UNKNOWN = "unknown"


class RouteMode(str, Enum):
    """How the node was located / routed to."""

    FUSION_ENTRY = "fusion_entry"   # loaded via fusion_entry.py (in-process)
    HTTP_FALLBACK = "http_fallback" # called via HTTP /execute endpoint
    REGISTRY = "registry"          # routed via NodeRegistry / NodeFabricRegistry
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Envelope & result dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NodeInvocationEnvelope:
    """Canonical invocation envelope for all node execution paths.

    Callers SHOULD supply ``trace_id`` / ``task_id`` / ``session_id`` when
    available.  ``request_id`` is auto-generated if not provided.
    """

    node_id: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)

    # Trace / correlation
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None

    # Routing metadata
    invocation_source: InvocationSource = InvocationSource.UNKNOWN
    route_mode: RouteMode = RouteMode.UNKNOWN

    # Timing — filled by invoke_node()
    enqueued_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "action": self.action,
            "params": self.params,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "invocation_source": self.invocation_source.value
                if isinstance(self.invocation_source, InvocationSource)
                else str(self.invocation_source),
            "route_mode": self.route_mode.value
                if isinstance(self.route_mode, RouteMode)
                else str(self.route_mode),
            "enqueued_at": self.enqueued_at,
        }


@dataclass
class NodeInvocationResult:
    """Canonical result envelope returned by :func:`invoke_node`.

    ``result`` holds the raw value returned by the node's ``execute``
    function/method.  ``error`` is ``None`` on success.
    """

    success: bool
    result: Any
    error: Optional[str]
    duration_ms: float

    # Echo of key envelope fields for traceability
    request_id: str
    trace_id: Optional[str]
    node_id: str
    action: str
    invocation_source: str

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Return a shape compatible with legacy ``{"success", "result", "error"}`` consumers."""
        d: Dict[str, Any] = {"success": self.success, "result": self.result}
        if not self.success:
            d["error"] = self.error
        return d

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "node_id": self.node_id,
            "action": self.action,
            "invocation_source": self.invocation_source,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Core execution helper (thin wrapper around _helpers primitives)
# ─────────────────────────────────────────────────────────────────────────────

async def _run_via_fusion_entry(
    envelope: NodeInvocationEnvelope,
    node_dir: str,
    fusion_path: str,
) -> NodeInvocationResult:
    """Load and execute a node via its fusion_entry.py (in-process path)."""
    from core.routes._helpers import _load_node, _execute_node

    start = time.monotonic()
    try:
        node_info = _load_node(envelope.node_id, node_dir, fusion_path)
        if node_info is None:
            return NodeInvocationResult(
                success=False,
                result=None,
                error=f"节点 {envelope.node_id} 的 fusion_entry.py 无可调用 execute 方法",
                duration_ms=(time.monotonic() - start) * 1000,
                request_id=envelope.request_id,
                trace_id=envelope.trace_id,
                node_id=envelope.node_id,
                action=envelope.action,
                invocation_source=envelope.invocation_source.value
                    if isinstance(envelope.invocation_source, InvocationSource)
                    else str(envelope.invocation_source),
            )

        raw = await _execute_node(node_info, envelope.action, envelope.params)
        return NodeInvocationResult(
            success=True,
            result=raw,
            error=None,
            duration_ms=(time.monotonic() - start) * 1000,
            request_id=envelope.request_id,
            trace_id=envelope.trace_id,
            node_id=envelope.node_id,
            action=envelope.action,
            invocation_source=envelope.invocation_source.value
                if isinstance(envelope.invocation_source, InvocationSource)
                else str(envelope.invocation_source),
        )
    except Exception as exc:
        logger.warning(
            "invoke_node[%s] fusion_entry execution failed: %s",
            envelope.node_id,
            exc,
        )
        return NodeInvocationResult(
            success=False,
            result=None,
            error=str(exc),
            duration_ms=(time.monotonic() - start) * 1000,
            request_id=envelope.request_id,
            trace_id=envelope.trace_id,
            node_id=envelope.node_id,
            action=envelope.action,
            invocation_source=envelope.invocation_source.value
                if isinstance(envelope.invocation_source, InvocationSource)
                else str(envelope.invocation_source),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Public API — single canonical entry point
# ─────────────────────────────────────────────────────────────────────────────

async def invoke_node(
    envelope: NodeInvocationEnvelope,
    *,
    node_dir: Optional[str] = None,
    fusion_path: Optional[str] = None,
) -> NodeInvocationResult:
    """Execute a node via the unified canonical path.

    Parameters
    ----------
    envelope:
        Fully constructed :class:`NodeInvocationEnvelope`.
    node_dir:
        Absolute path to the node directory (``nodes/<key>``).  When omitted
        the executor resolves it from ``nodes_root`` using ``envelope.node_id``.
    fusion_path:
        Absolute path to ``fusion_entry.py``.  Inferred from ``node_dir`` when
        omitted.

    Returns
    -------
    NodeInvocationResult
        A stable, trace-enriched result envelope.  Use
        ``result.to_legacy_dict()`` for backward-compatible shapes.
    """
    import os as _os
    from core.routes._helpers import nodes_root as _nodes_root

    # Stamp enqueued_at if not already set
    if envelope.enqueued_at is None:
        envelope.enqueued_at = time.time()

    # Resolve node_dir / fusion_path
    if node_dir is None:
        node_dir = _os.path.join(_nodes_root, envelope.node_id)

    if fusion_path is None:
        fusion_path = _os.path.join(node_dir, "fusion_entry.py")

    # --- Validate node exists ---
    if not _os.path.isdir(node_dir):
        return NodeInvocationResult(
            success=False,
            result=None,
            error=f"节点目录不存在: {node_dir}",
            duration_ms=0.0,
            request_id=envelope.request_id,
            trace_id=envelope.trace_id,
            node_id=envelope.node_id,
            action=envelope.action,
            invocation_source=envelope.invocation_source.value
                if isinstance(envelope.invocation_source, InvocationSource)
                else str(envelope.invocation_source),
        )

    if not _os.path.exists(fusion_path):
        return NodeInvocationResult(
            success=False,
            result=None,
            error=f"节点 {envelope.node_id} 无 fusion_entry.py",
            duration_ms=0.0,
            request_id=envelope.request_id,
            trace_id=envelope.trace_id,
            node_id=envelope.node_id,
            action=envelope.action,
            invocation_source=envelope.invocation_source.value
                if isinstance(envelope.invocation_source, InvocationSource)
                else str(envelope.invocation_source),
        )

    # Mark route_mode as FUSION_ENTRY (the only local path available here)
    if envelope.route_mode == RouteMode.UNKNOWN:
        envelope.route_mode = RouteMode.FUSION_ENTRY

    logger.debug(
        "invoke_node node_id=%s action=%s source=%s request_id=%s",
        envelope.node_id,
        envelope.action,
        envelope.invocation_source,
        envelope.request_id,
    )

    return await _run_via_fusion_entry(envelope, node_dir, fusion_path)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience builder
# ─────────────────────────────────────────────────────────────────────────────

def build_envelope(
    node_id: str,
    action: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    invocation_source: InvocationSource = InvocationSource.UNKNOWN,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    route_mode: RouteMode = RouteMode.UNKNOWN,
) -> NodeInvocationEnvelope:
    """Convenience factory for building a :class:`NodeInvocationEnvelope`."""
    return NodeInvocationEnvelope(
        node_id=node_id,
        action=action,
        params=params or {},
        request_id=request_id or str(uuid.uuid4()),
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        invocation_source=invocation_source,
        route_mode=route_mode,
    )
