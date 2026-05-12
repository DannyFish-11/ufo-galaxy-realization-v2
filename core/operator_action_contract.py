"""
core/operator_action_contract.py
==================================
PR-3: Operator Control-Plane Activation — canonical operator action contract.

Defines the request/response models and authority sentinels for the operator
control plane's action capability.  All operator-originated actions that must
enter the canonical runtime/orchestration path MUST use the types defined here.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  OPERATOR ACTION CONTRACT  (this module, Layer 10 — action surface)  │
    │                                                                       │
    │  Defines the wire contract for operator-originated actions:           │
    │    • OperatorActionKind      — enumerated action types                │
    │    • OperatorActionRequest   — inbound action request model           │
    │    • OperatorActionResult    — outbound action result model           │
    │                                                                       │
    │  All action endpoints in core/routes/operator.py accept              │
    │  OperatorActionRequest bodies and return OperatorActionResult dicts.  │
    │                                                                       │
    │  Actions enter the system via:                                        │
    │    OperatorSurface.execute_operator_action()                          │
    │        → DesktopPresenceRuntime.handle_request(source="operator")     │
    │        → tri-state lifecycle → OpenClawd / e2e orchestration          │
    │                                                                       │
    │  This module does NOT introduce a parallel execution engine.          │
    │  It is a contract + entry-point layer only.                           │
    └──────────────────────────────────────────────────────────────────────┘

Canonical path constraint
-------------------------
Every operator action MUST enter the system through
:meth:`~core.operator_surface.OperatorSurface.execute_operator_action`, which
delegates to :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request`.

Non-goals
---------
- No parallel orchestration engine.
- No bypass of the canonical tri-state lifecycle.
- No speculative action types unsupported by current code.

Public API
----------
Authority sentinels::

    OPERATOR_ACTION_CONTRACT_AUTHORITY
    OPERATOR_CONTROL_PLANE_IS_CANONICAL_AUTHORITY
    OPERATOR_ACTION_ENTRY_MODE

Enums::

    OperatorActionKind

Dataclasses::

    OperatorActionRequest
    OperatorActionResult

Helpers::

    build_operator_action_result_from_runtime_result()
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

OPERATOR_ACTION_CONTRACT_AUTHORITY: str = (
    "OPERATOR_ACTION_CONTRACT_V1: "
    "core.operator_action_contract defines the canonical operator-action wire "
    "contract.  All operator-originated actions must use OperatorActionRequest "
    "and enter the canonical runtime via OperatorSurface.execute_operator_action(). "
    "This module does NOT introduce a parallel execution engine."
)

OPERATOR_CONTROL_PLANE_IS_CANONICAL_AUTHORITY: str = (
    "OPERATOR_CONTROL_PLANE_IS_CANONICAL: "
    "The operator control plane is wired into the canonical "
    "DesktopPresenceRuntime.handle_request() path.  It does not bypass the "
    "tri-state lifecycle, the OpenClawd core, or the canonical dispatch chain."
)

OPERATOR_ACTION_ENTRY_MODE: str = "operator_action"
"""Entry-mode tag stamped on requests originating from the operator control plane.

Propagated into DesktopPresenceRuntime.handle_request(entry_mode=...) and
visible in ingress_carrier_context so operator-originated actions can be
identified and traced through all downstream layers without changing routing
logic.
"""

# ---------------------------------------------------------------------------
# OperatorActionKind
# ---------------------------------------------------------------------------


class OperatorActionKind(str, Enum):
    """Enumeration of operator-panel action types supported by the current runtime.

    Only action kinds that the current canonical code can honestly support are
    included here.  Speculative kinds not backed by real orchestration paths are
    intentionally absent.

    dispatch
        Submit a natural-language or structured task for execution via the
        canonical DesktopPresenceRuntime → OpenClawd → dispatch chain.
        Maps to ``DesktopPresenceRuntime.handle_request(source="operator")``.

    device_dispatch
        Submit a device-targeted task.  Same canonical path as ``dispatch``
        with ``device_id`` forwarded so the routing layer can prefer the
        requested Android device.

    flow_cancel
        Request cancellation of a specific delegated flow via
        ``DelegatedFlowEntityRuntime.advance_flow_phase(signal=cancel)``.
        Safe semantics: a flow that is already terminal is not affected.
    """

    dispatch = "dispatch"
    device_dispatch = "device_dispatch"
    flow_cancel = "flow_cancel"
    retry_admission = "retry_admission"
    request_capability_revalidation = "request_capability_revalidation"
    reopen_session_continuity = "reopen_session_continuity"
    rebind_session_continuity = "rebind_session_continuity"
    trigger_recovery = "trigger_recovery"
    acknowledge_recovery = "acknowledge_recovery"
    suspend_participant = "suspend_participant"
    isolate_device = "isolate_device"
    switch_path_selection = "switch_path_selection"
    reevaluate_path_selection = "reevaluate_path_selection"
    reopen_closure = "reopen_closure"
    finalize_closure = "finalize_closure"
    reject_closure = "reject_closure"
    acknowledge_blocker = "acknowledge_blocker"
    escalate_dependency_failure = "escalate_dependency_failure"


# ---------------------------------------------------------------------------
# OperatorActionRequest
# ---------------------------------------------------------------------------


@dataclass
class OperatorActionRequest:
    """Inbound model for an operator-panel action.

    Fields
    ------
    action_kind
        The kind of action the operator wants to take (required).
    message
        Natural-language task message for ``dispatch`` / ``device_dispatch``
        actions.  May be empty for ``flow_cancel``.
    device_id
        Target device ID for ``device_dispatch``.  Optional for ``dispatch``.
    flow_id
        Target flow ID for ``flow_cancel``.  Ignored for dispatch actions.
    session_id
        Operator session ID.  Forwarded to DesktopPresenceRuntime for
        continuity tracing.  Auto-generated when empty.
    user_id
        Operator user ID.  Forwarded for audit-trail purposes.  Defaults to
        ``"operator"``.
    required_capabilities
        Optional capability filter forwarded to routing.  Only relevant for
        ``dispatch`` / ``device_dispatch``.
    context
        Optional conversation context list forwarded to the runtime core.
    """

    action_kind: str = OperatorActionKind.dispatch.value
    message: str = ""
    device_id: Optional[str] = None
    flow_id: Optional[str] = None
    session_id: str = ""
    user_id: str = "operator"
    required_capabilities: List[str] = field(default_factory=list)
    context: List[Dict[str, Any]] = field(default_factory=list)
    approval_token: Optional[str] = None
    action_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_kind": self.action_kind,
            "message": self.message,
            "device_id": self.device_id,
            "flow_id": self.flow_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "required_capabilities": list(self.required_capabilities),
            "context": list(self.context),
            "approval_token": self.approval_token,
            "action_notes": self.action_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperatorActionRequest":
        return cls(
            action_kind=data.get("action_kind", OperatorActionKind.dispatch.value),
            message=data.get("message", ""),
            device_id=data.get("device_id"),
            flow_id=data.get("flow_id"),
            session_id=data.get("session_id", ""),
            user_id=data.get("user_id", "operator"),
            required_capabilities=list(data.get("required_capabilities") or []),
            context=list(data.get("context") or []),
            approval_token=data.get("approval_token"),
            action_notes=str(data.get("action_notes") or ""),
        )


# ---------------------------------------------------------------------------
# OperatorActionResult
# ---------------------------------------------------------------------------


@dataclass
class OperatorActionResult:
    """Outbound model for the result of an operator-panel action.

    Fields
    ------
    action_id
        Unique ID for this action invocation.
    action_kind
        The kind of action that was executed.
    accepted
        True when the action was successfully submitted to the canonical runtime.
        For ``dispatch`` / ``device_dispatch`` this is True once
        ``DesktopPresenceRuntime.handle_request()`` returns without exception.
        For ``flow_cancel`` this is True once the cancellation signal is applied.
    runtime_session_id
        The ``runtime_session_id`` returned by
        ``DesktopPresenceRuntime.handle_request()``.  Empty for ``flow_cancel``.
    trace_id
        Trace ID from the runtime result.  Alias of ``runtime_session_id`` in
        most cases.
    operator_entry_mode
        Always :data:`OPERATOR_ACTION_ENTRY_MODE` (``"operator_action"``).  Confirms
        that this action entered the system through the operator control plane.
    runtime_result
        The raw result dict returned by
        ``DesktopPresenceRuntime.handle_request()``.  Empty dict for non-dispatch
        actions or when the runtime did not return a dict.
    error
        Non-empty when the action failed before or during runtime delegation.
    generated_at
        Unix epoch timestamp when this result was built.
    authority
        Module authority sentinel.
    """

    action_id: str = field(default_factory=lambda: f"opact_{uuid.uuid4().hex[:12]}")
    action_kind: str = OperatorActionKind.dispatch.value
    accepted: bool = False
    runtime_session_id: str = ""
    trace_id: str = ""
    operator_entry_mode: str = OPERATOR_ACTION_ENTRY_MODE
    runtime_result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    generated_at: float = field(default_factory=time.time)
    authority: str = OPERATOR_ACTION_CONTRACT_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "accepted": self.accepted,
            "runtime_session_id": self.runtime_session_id,
            "trace_id": self.trace_id,
            "operator_entry_mode": self.operator_entry_mode,
            "runtime_result": dict(self.runtime_result),
            "error": self.error,
            "generated_at": self.generated_at,
            "authority": self.authority,
        }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def build_operator_action_result_from_runtime_result(
    *,
    action_kind: str,
    runtime_result: Dict[str, Any],
) -> OperatorActionResult:
    """Build an :class:`OperatorActionResult` from a raw DesktopPresenceRuntime result.

    Args:
        action_kind: The :class:`OperatorActionKind` value for this action.
        runtime_result: The dict returned by
            ``DesktopPresenceRuntime.handle_request()``.

    Returns:
        A populated :class:`OperatorActionResult` with ``accepted=True`` and
        runtime correlation IDs extracted from the result dict.
    """
    rsid = runtime_result.get("runtime_session_id", "")
    tid = runtime_result.get("trace_id", rsid)
    return OperatorActionResult(
        action_kind=action_kind,
        accepted=True,
        runtime_session_id=rsid,
        trace_id=tid,
        operator_entry_mode=OPERATOR_ACTION_ENTRY_MODE,
        runtime_result=dict(runtime_result),
    )
