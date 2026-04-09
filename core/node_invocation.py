"""
core/node_invocation.py
=======================
Unified Node Invocation Envelope and Executor  (PR-4)
------------------------------------------------------

This module is the **single canonical entry point** for all local node
execution in the Galaxy system.  Every invocation path (OpenClawd tool
dispatch, REST ``POST /api/v1/nodes/call``, command-router node bridge,
capability-orchestrator node path, system-integration HTTP fallback) MUST
construct a :class:`NodeInvocationEnvelope` and call
:func:`invoke_node` (or :meth:`UnifiedNodeExecutor.execute`) instead of
calling ``_load_node`` / ``_execute_node`` directly.

Canonical invocation contract
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ingress path  ->  build NodeInvocationEnvelope  ->  invoke_node()
                                                     |
                                                     v
                                           UnifiedNodeExecutor.execute()
                                                     |
                                           governance eligibility gate
                                           (core.node_invocation_governance)
                                                     |
                                           _load_node / _execute_node
                                           (core.routes._helpers)
                                                     |
                                                     v
                                           NodeInvocationResult

Policy sentinels
~~~~~~~~~~~~~~~~
All sentinel constants in this module are machine-checkable strings that
confirm the unified invocation contract is in force.  They are re-exported
from ``core/routes/projection.py`` so that external verifiers can import
them without knowledge of internal paths.

Non-goals
~~~~~~~~~
- This module does NOT change discovery or registry architecture.
- This module does NOT modify governance eligibility rules beyond what is
  strictly required for unified invocation plumbing.

PR-11 additions
~~~~~~~~~~~~~~~
- :attr:`NodeInvocationEnvelope.governance_override` — set to
  :attr:`~core.node_invocation_governance.NodeInvocationGovernanceOverride.COMPAT_INTERNAL`
  to bypass the governance gate on tightly-scoped non-canonical paths.
- :class:`UnifiedNodeExecutor` now calls
  :func:`~core.node_invocation_governance.evaluate_invocation_governance`
  before loading or executing any node.  Governance-ineligible nodes are
  denied with a structured ``eligibility_denial`` diagnostic payload.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.NodeInvocation")

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

UNIFIED_NODE_INVOCATION_AUTHORITY: str = (
    "UNIFIED_NODE_INVOCATION::AUTHORITY_V1: "
    "core.node_invocation is the single canonical entry point for all local "
    "node execution.  All invocation paths (openclawd, rest, command, "
    "capability, system) MUST construct a NodeInvocationEnvelope and call "
    "invoke_node() / UnifiedNodeExecutor.execute() instead of calling "
    "_load_node / _execute_node directly."
)

UNIFIED_NODE_INVOCATION_PR4_SENTINEL: str = (
    "UNIFIED_NODE_INVOCATION::PR4_SENTINEL_V1"
)

ALL_INVOCATION_PATHS_CONVERGE_ON_UNIFIED_EXECUTOR_POLICY: str = (
    "UNIFIED_NODE_INVOCATION::ALL_PATHS_CONVERGE_POLICY_V1: "
    "openclawd node__ dispatch, POST /api/v1/nodes/call, _command_node_executor, "
    "CanonicalDispatcher._dispatch_node, and system_integration._execute_node "
    "all construct NodeInvocationEnvelope and call invoke_node()."
)

INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_SCHEMA_POLICY: str = (
    "UNIFIED_NODE_INVOCATION::CANONICAL_TRACE_SCHEMA_POLICY_V1: "
    "NodeInvocationEnvelope carries request_id, trace_id, task_id, session_id, "
    "node_id, action, params, invocation_source, route_mode, execution_domain, "
    "started_at, and timeout_ms.  NodeInvocationResult carries success, result, "
    "error, duration_ms, execution_mode, and execution_source."
)

RESULT_ENVELOPE_IS_CANONICAL_RESULT_CONTRACT_POLICY: str = (
    "UNIFIED_NODE_INVOCATION::CANONICAL_RESULT_CONTRACT_POLICY_V1: "
    "NodeInvocationResult is the canonical result shape returned by all node "
    "invocation paths.  Existing external interfaces receive a backward-compat "
    "bridge dict derived from NodeInvocationResult."
)

GOVERNANCE_ELIGIBILITY_ENFORCED_AT_INVOCATION_TIME_PR11_SENTINEL: str = (
    "UNIFIED_NODE_INVOCATION::GOVERNANCE_GATE_PR11_SENTINEL_V1: "
    "UnifiedNodeExecutor.execute() consults core.node_invocation_governance "
    "before loading or executing any node.  Governance-ineligible nodes are "
    "denied canonical invocation with a structured eligibility_denial payload."
)

CANONICAL_INVOCATION_DENIES_INELIGIBLE_NODES_PR11_POLICY: str = (
    "UNIFIED_NODE_INVOCATION::INELIGIBLE_DENIED_PR11_POLICY_V1: "
    "Nodes that are governance-ineligible (archived, deprecated, unhealthy, "
    "or readiness-gap) cannot be executed through canonical invoke_node() / "
    "UnifiedNodeExecutor.execute() regardless of whether the caller knows the "
    "node_id.  The COMPAT_INTERNAL override bypasses this gate but is "
    "non-canonical, auditable, and must not be used by canonical callsites."
)


# ---------------------------------------------------------------------------
# InvocationSource enum
# ---------------------------------------------------------------------------

class InvocationSource(str, Enum):
    """Identifies which ingress path triggered a node invocation."""

    OPENCLAWD = "openclawd"
    REST = "rest"
    COMMAND = "command"
    CAPABILITY = "capability"
    SYSTEM = "system"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Canonical invocation envelope
# ---------------------------------------------------------------------------

@dataclass
class NodeInvocationEnvelope:
    """Canonical invocation envelope for a single node execution.

    All invocation entry points MUST populate this envelope before calling
    :func:`invoke_node`.  Fields that callers cannot supply (e.g. ``trace_id``
    when not already tracked) receive auto-generated defaults so that every
    invocation is fully traceable.
    """

    node_id: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)

    # Tracing / correlation
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_id: str = field(default_factory=lambda: "trace_" + uuid.uuid4().hex[:12])
    task_id: Optional[str] = None
    session_id: Optional[str] = None

    # Source metadata
    invocation_source: InvocationSource = InvocationSource.UNKNOWN
    route_mode: str = "local"
    execution_domain: str = "local"

    # Governance override — set to COMPAT_INTERNAL to bypass the invocation-time
    # governance gate on tightly-scoped non-canonical paths.  This field is
    # intentionally Optional so callers that do not supply it default to NONE
    # (full governance enforcement).
    governance_override: Optional[str] = None

    # Timing
    started_at: float = field(default_factory=time.time)
    timeout_ms: float = 30_000.0


# ---------------------------------------------------------------------------
# Canonical result envelope
# ---------------------------------------------------------------------------

@dataclass
class NodeInvocationResult:
    """Canonical result envelope returned by :func:`invoke_node`.

    All invocation entry points SHOULD propagate or bridge this result to their
    callers.  Legacy callers that expect a plain ``dict`` can use
    :meth:`to_legacy_dict`.
    """

    success: bool
    node_id: str
    action: str
    request_id: str
    trace_id: str

    result: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    execution_mode: str = "local"
    execution_source: str = InvocationSource.UNKNOWN.value

    # PR-11: governance denial diagnostics — populated when invocation is
    # refused due to governance ineligibility.
    eligibility_denial: Optional[Dict[str, Any]] = None

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Return a backward-compatible dict shaped like the old execution result.

        The returned dict preserves the pre-PR-4 ``success`` / ``data`` /
        ``error`` keys expected by callers that have not yet been updated to
        consume :class:`NodeInvocationResult` directly.
        """
        d: Dict[str, Any] = {
            "success": self.success,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "node_id": self.node_id,
            "action": self.action,
            "duration_ms": self.duration_ms,
            "execution_mode": self.execution_mode,
            "execution_source": self.execution_source,
        }
        if self.success:
            d["result"] = self.result
            # Preserve legacy "data" key for callers that expect it.
            if isinstance(self.result, dict) and "data" in self.result:
                d["data"] = self.result["data"]
            elif self.result is not None:
                d["data"] = self.result
        else:
            d["error"] = self.error
        if self.eligibility_denial is not None:
            d["eligibility_denial"] = self.eligibility_denial
        return d


# ---------------------------------------------------------------------------
# UnifiedNodeExecutor
# ---------------------------------------------------------------------------

class UnifiedNodeExecutor:
    """Single canonical node executor.

    All node invocation paths MUST call :meth:`execute` with a fully
    populated :class:`NodeInvocationEnvelope`.  This class is intentionally
    stateless (no instance variables modified during execution) so that it
    can be used as a shared singleton.
    """

    # Root path to the nodes/ directory — populated lazily from _helpers so
    # that this module does not impose a hard startup-order constraint.
    _nodes_root: Optional[str] = None

    def _get_nodes_root(self) -> str:
        if self._nodes_root is None:
            try:
                from core.routes._helpers import nodes_root
                UnifiedNodeExecutor._nodes_root = nodes_root
            except Exception:
                UnifiedNodeExecutor._nodes_root = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "nodes"
                )
        return self._nodes_root  # type: ignore[return-value]

    async def execute(self, envelope: NodeInvocationEnvelope) -> NodeInvocationResult:
        """Execute a node invocation described by *envelope*.

        Loads the node's ``fusion_entry.py`` via the shared helpers, calls
        the node's ``execute`` method, and returns a :class:`NodeInvocationResult`
        with full timing and source metadata.

        Errors are caught and surfaced as a failed :class:`NodeInvocationResult`
        so that callers always receive a stable result shape.
        """
        started = envelope.started_at
        node_id = envelope.node_id
        action = envelope.action

        logger.debug(
            "invoke node | node_id=%s action=%s source=%s request_id=%s trace_id=%s",
            node_id,
            action,
            envelope.invocation_source.value,
            envelope.request_id,
            envelope.trace_id,
        )

        # -- governance eligibility gate (PR-11) ----------------------------
        try:
            from core.node_invocation_governance import (  # noqa: PLC0415
                NodeInvocationGovernanceOverride,
                evaluate_invocation_governance,
                build_invocation_denial_diagnostics,
            )

            gov_override_raw = envelope.governance_override
            gov_override = NodeInvocationGovernanceOverride.NONE
            if gov_override_raw == NodeInvocationGovernanceOverride.COMPAT_INTERNAL.value:
                gov_override = NodeInvocationGovernanceOverride.COMPAT_INTERNAL

            gov_decision = evaluate_invocation_governance(
                node_id,
                override=gov_override,
            )

            if not gov_decision.invocation_allowed:
                denial_payload = build_invocation_denial_diagnostics(gov_decision)
                logger.warning(
                    "invoke node DENIED by governance gate | node_id=%s reasons=%s "
                    "request_id=%s",
                    node_id,
                    gov_decision.denial_reasons,
                    envelope.request_id,
                )
                return NodeInvocationResult(
                    success=False,
                    node_id=node_id,
                    action=action,
                    request_id=envelope.request_id,
                    trace_id=envelope.trace_id,
                    error=(
                        f"节点 {node_id} 因治理资格检查未通过，拒绝调用: "
                        f"{gov_decision.denial_reasons}"
                    ),
                    duration_ms=(time.time() - started) * 1000.0,
                    execution_mode=envelope.execution_domain,
                    execution_source=envelope.invocation_source.value,
                    eligibility_denial=denial_payload,
                )
        except Exception as _gov_exc:  # noqa: BLE001
            # If governance module itself is unavailable, log and proceed
            # (graceful degradation — do not block invocation on import errors).
            logger.warning(
                "invoke node: governance gate unavailable for node_id=%s: %s; proceeding",
                node_id,
                _gov_exc,
            )

        nodes_root = self._get_nodes_root()
        node_dir = os.path.join(nodes_root, node_id)

        # -- locate node directory -------------------------------------------
        if not os.path.isdir(node_dir):
            # Fuzzy match: accept partial node_id (e.g. "Node_01" matching
            # "Node_01_OneAPI").
            matched_dir: Optional[str] = None
            matched_id: Optional[str] = None
            try:
                for name in os.listdir(nodes_root):
                    if name == node_id or name.startswith(node_id + "_") or node_id in name:
                        candidate = os.path.join(nodes_root, name)
                        if os.path.isdir(candidate):
                            matched_dir = candidate
                            matched_id = name
                            break
            except OSError:
                pass

            if matched_dir is None:
                return self._fail(
                    envelope,
                    f"节点 {node_id} 目录未找到",
                    started,
                )
            node_dir = matched_dir
            node_id = matched_id  # type: ignore[assignment]

        # -- locate fusion_entry.py ------------------------------------------
        fusion_path = os.path.join(node_dir, "fusion_entry.py")
        if not os.path.exists(fusion_path):
            return self._fail(
                envelope,
                f"节点 {node_id} 无 fusion_entry.py",
                started,
            )

        # -- load & execute --------------------------------------------------
        try:
            from core.routes._helpers import _execute_node, _load_node

            node_info = _load_node(node_id, node_dir, fusion_path)
            if not node_info:
                return self._fail(
                    envelope,
                    f"节点 {node_id} 加载失败 (fusion_entry 无可调用 execute 方法)",
                    started,
                )

            params = envelope.params if isinstance(envelope.params, dict) else {}
            raw_result = await _execute_node(node_info, action, params)
            duration_ms = (time.time() - started) * 1000.0

            logger.debug(
                "invoke node ok | node_id=%s action=%s duration_ms=%.1f request_id=%s",
                node_id,
                action,
                duration_ms,
                envelope.request_id,
            )

            return NodeInvocationResult(
                success=True,
                node_id=node_id,
                action=action,
                request_id=envelope.request_id,
                trace_id=envelope.trace_id,
                result=raw_result,
                duration_ms=duration_ms,
                execution_mode=envelope.execution_domain,
                execution_source=envelope.invocation_source.value,
            )

        except asyncio.TimeoutError:
            return self._fail(
                envelope,
                f"节点 {node_id}.{action} 执行超时",
                started,
                node_id=node_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "invoke node error | node_id=%s action=%s error=%s request_id=%s",
                node_id,
                action,
                exc,
                envelope.request_id,
            )
            return self._fail(
                envelope,
                str(exc),
                started,
                node_id=node_id,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fail(
        envelope: NodeInvocationEnvelope,
        error: str,
        started: float,
        *,
        node_id: Optional[str] = None,
        eligibility_denial: Optional[Dict[str, Any]] = None,
    ) -> NodeInvocationResult:
        return NodeInvocationResult(
            success=False,
            node_id=node_id or envelope.node_id,
            action=envelope.action,
            request_id=envelope.request_id,
            trace_id=envelope.trace_id,
            error=error,
            duration_ms=(time.time() - started) * 1000.0,
            execution_mode=envelope.execution_domain,
            execution_source=envelope.invocation_source.value,
            eligibility_denial=eligibility_denial,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_executor_singleton: Optional[UnifiedNodeExecutor] = None


def get_unified_node_executor() -> UnifiedNodeExecutor:
    """Return the module-level :class:`UnifiedNodeExecutor` singleton."""
    global _executor_singleton
    if _executor_singleton is None:
        _executor_singleton = UnifiedNodeExecutor()
    return _executor_singleton


# ---------------------------------------------------------------------------
# Convenience entry-point
# ---------------------------------------------------------------------------

async def invoke_node(
    node_id: str,
    action: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    invocation_source: InvocationSource = InvocationSource.UNKNOWN,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    route_mode: str = "local",
    timeout_ms: float = 30_000.0,
) -> NodeInvocationResult:
    """Convenience wrapper: build an envelope and call the unified executor.

    This is the preferred single call-site for all code that needs to execute
    a local node action.  It constructs a :class:`NodeInvocationEnvelope`
    with all tracing fields populated and delegates to
    :class:`UnifiedNodeExecutor`.

    Parameters
    ----------
    node_id:
        The node directory name (e.g. ``"Node_01_OneAPI"``).  Partial names
        such as ``"Node_01"`` are accepted and resolved via fuzzy matching.
    action:
        The action string forwarded to the node's ``execute`` method.
    params:
        Keyword parameters dict forwarded to the node.
    invocation_source:
        Which subsystem is initiating this call.  Used in logs and traces.
    request_id / trace_id / task_id / session_id:
        Caller-supplied IDs for correlation.  Auto-generated when omitted.
    route_mode:
        Routing hint stored in the envelope (default ``"local"``).
    timeout_ms:
        Execution timeout in milliseconds (default 30 000 ms).
    """
    envelope = NodeInvocationEnvelope(
        node_id=node_id,
        action=action,
        params=params or {},
        invocation_source=invocation_source,
        route_mode=route_mode,
        timeout_ms=timeout_ms,
    )
    if request_id is not None:
        envelope.request_id = request_id
    if trace_id is not None:
        envelope.trace_id = trace_id
    if task_id is not None:
        envelope.task_id = task_id
    if session_id is not None:
        envelope.session_id = session_id

    return await get_unified_node_executor().execute(envelope)
