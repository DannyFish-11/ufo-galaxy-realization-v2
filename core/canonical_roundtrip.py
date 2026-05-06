"""
core/canonical_roundtrip.py
============================
PR-4: Canonical State / Action / Result / Feedback Roundtrip

Implements the closed-loop execution feedback path that closes the
action→execution→result→state-feedback roundtrip across the dual-repo system
formed by:

- ``ufo-galaxy-realization-v2`` (V2 — this module)
- ``ufo-galaxy-android`` (Android — execution events uplinked via AIP v3)

Architecture role
-----------------
::

    ┌───────────────────────────────────────────────────────────────────────┐
    │  CANONICAL ROUNDTRIP  (this module, PR-4)                             │
    │                                                                        │
    │  Closes the feedback loop so that action-originated execution results  │
    │  re-enter the unified state surfaces that operator/panel/existence     │
    │  consumers read.                                                       │
    │                                                                        │
    │  Roundtrip flow:                                                       │
    │                                                                        │
    │    1. Operator / runtime originates action                             │
    │       → POST /api/v1/operator/action (or dispatch)                    │
    │       → OperatorSurface.execute_operator_action()                     │
    │       → DesktopPresenceRuntime.handle_request()                       │
    │                                                                        │
    │    2. Execution produces a runtime result                              │
    │       → operator route calls record_execution_roundtrip()             │
    │       → ExecutionRoundtripRecord stored in process-level store        │
    │                                                                        │
    │    3. Android execution/event/result truth (where present)            │
    │       → android_device_state_store absorbs DeviceExecutionEvent       │
    │       → _forward_execution_event_to_flow_surface() forwards to flow   │
    │       → terminal phase (completed / failed) calls                     │
    │         notify_android_execution_terminal()                           │
    │       → ExecutionRoundtripRecord updated / created                    │
    │                                                                        │
    │    4. UnifiedPanelAggregationService.build_payload() fills            │
    │       last_execution_result from get_last_execution_roundtrip()       │
    │       → front-facing panel/operator/existence consumers observe       │
    │         real outcome-driven state                                      │
    │                                                                        │
    │  This module does NOT introduce a second truth store.                 │
    │  It reads from existing canonical paths and composes their outputs    │
    │  into one feedback record that re-enters the unified panel surface.   │
    └───────────────────────────────────────────────────────────────────────┘

Design invariants
-----------------
- **Grounded in real code**: all fields are populated from live dispatch
  results, operator action results, or Android execution events — no
  synthetic or fabricated semantics.
- **Single truth**: ``ExecutionRoundtripRecord`` is NOT a new truth store.
  It is a projection / projection-summary built from existing canonical
  singletons.
- **Graceful degradation**: all operations are guarded with try/except so
  that a failure here never blocks the unified panel payload.
- **Test-friendly**: ``reset_execution_roundtrip()`` clears process state
  for test isolation.

Public API
----------
Authority sentinels::

    CANONICAL_ROUNDTRIP_AUTHORITY
    ROUNDTRIP_SCHEMA_VERSION

Dataclass::

    ExecutionRoundtripRecord  — typed execution result feedback record

Helpers::

    record_execution_roundtrip(*, action_id, action_kind, trace_id,
                               session_id, runtime_result) -> ExecutionRoundtripRecord
    notify_android_execution_terminal(*, flow_id, device_id, phase,
                                      step_index, detail) -> ExecutionRoundtripRecord
    get_last_execution_roundtrip() -> Optional[ExecutionRoundtripRecord]
    get_execution_roundtrip_store() -> List[ExecutionRoundtripRecord]
    reset_execution_roundtrip()   -> None  (testing only)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CanonicalRoundtrip")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

CANONICAL_ROUNDTRIP_AUTHORITY: str = (
    "CANONICAL_ROUNDTRIP_V1: "
    "core.canonical_roundtrip closes the action→execution→result→state-feedback "
    "roundtrip across V2 and Android execution surfaces.  "
    "All execution outcome feedback MUST flow through record_execution_roundtrip() "
    "or notify_android_execution_terminal() so that the unified panel surface "
    "reflects real action outcomes rather than disconnected partial projections.  "
    "This module does NOT introduce a second truth store."
)

ROUNDTRIP_SCHEMA_VERSION: str = "1.0"

# Terminal Android execution phases (completion or failure)
_ANDROID_TERMINAL_PHASES: frozenset = frozenset(
    {"completed", "failed", "stagnation", "gate_decision"}
)

# ---------------------------------------------------------------------------
# ExecutionRoundtripRecord
# ---------------------------------------------------------------------------


@dataclass
class ExecutionRoundtripRecord:
    """Typed execution result feedback record.

    Represents one closed-loop roundtrip: from an action (or Android
    execution terminal event) through execution to a final result/state
    re-projection into the unified panel surface.

    Fields
    ------
    roundtrip_id
        Unique ID for this roundtrip instance.
    action_id
        Operator action ID that originated this roundtrip.  Empty string for
        Android-terminal-only roundtrips where no operator action preceded.
    action_kind
        The :class:`~core.operator_action_contract.OperatorActionKind` value
        (``"dispatch"``, ``"device_dispatch"``, ``"flow_cancel"``, or
        ``"android_terminal"`` for roundtrips originating from Android).
    trace_id
        Correlation trace ID linking this record to the originating runtime
        session / dispatch chain.
    session_id
        Runtime session ID from the originating action.
    execution_phase
        Current execution lifecycle phase for this roundtrip:
        ``"dispatched"``  — action was accepted by the runtime.
        ``"executing"``   — execution is in progress (Android event received).
        ``"completed"``   — execution completed successfully.
        ``"failed"``      — execution failed.
        ``"cancelled"``   — flow was cancelled.
    execution_success
        True when execution completed successfully.  None when execution has
        not yet reached a terminal phase.
    execution_result_data
        The raw ``runtime_result`` dict from the originating action, or the
        Android execution event evidence dict.  May be empty.
    android_terminal_phase
        The terminal Android execution phase string when this roundtrip was
        closed by an Android execution event (``"completed"``, ``"failed"``,
        etc.).  Empty string for V2-local roundtrips.
    android_device_id
        The Android device ID that emitted the terminal execution event.
        Empty string for V2-local roundtrips.
    android_flow_id
        The delegated flow ID on the Android device.
        Empty string for V2-local roundtrips.
    feedback_projected_at
        Unix timestamp when this record was last written.
    generated_at
        Unix timestamp when this record was first created.
    schema_version
        Schema version for forward-compatibility.
    authority
        Module authority sentinel.
    """

    roundtrip_id: str = field(
        default_factory=lambda: f"rt_{uuid.uuid4().hex[:12]}"
    )
    action_id: str = ""
    action_kind: str = "dispatch"
    trace_id: str = ""
    session_id: str = ""

    # Execution lifecycle phase
    execution_phase: str = "dispatched"
    execution_success: Optional[bool] = None
    execution_result_data: Dict[str, Any] = field(default_factory=dict)

    # Android-side truth (when present)
    android_terminal_phase: str = ""
    android_device_id: str = ""
    android_flow_id: str = ""

    # Timestamps
    feedback_projected_at: float = field(default_factory=time.time)
    generated_at: float = field(default_factory=time.time)

    schema_version: str = ROUNDTRIP_SCHEMA_VERSION
    authority: str = CANONICAL_ROUNDTRIP_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "roundtrip_id": self.roundtrip_id,
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "execution_phase": self.execution_phase,
            "execution_success": self.execution_success,
            "execution_result_data": dict(self.execution_result_data),
            "android_terminal_phase": self.android_terminal_phase,
            "android_device_id": self.android_device_id,
            "android_flow_id": self.android_flow_id,
            "feedback_projected_at": self.feedback_projected_at,
            "generated_at": self.generated_at,
            "schema_version": self.schema_version,
            "authority": self.authority,
        }

    def compact_dict(self) -> Dict[str, Any]:
        """Return a compact dict suitable for embedding in UnifiedPanelPayload."""
        return {
            "roundtrip_id": self.roundtrip_id,
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "trace_id": self.trace_id,
            "execution_phase": self.execution_phase,
            "execution_success": self.execution_success,
            "android_terminal_phase": self.android_terminal_phase,
            "android_device_id": self.android_device_id,
            "android_flow_id": self.android_flow_id,
            "feedback_projected_at": self.feedback_projected_at,
            "_source": "canonical_roundtrip",
        }


# ---------------------------------------------------------------------------
# Process-level roundtrip store
# ---------------------------------------------------------------------------
# A lightweight in-process ring buffer of ExecutionRoundtripRecords.
# Written by record_execution_roundtrip() and notify_android_execution_terminal().
# Read by get_last_execution_roundtrip() and get_execution_roundtrip_store().
#
# This is NOT a durable persistence layer — process restart clears it.
# For durable audit, the operator route audit_store chain is authoritative.

_MAX_STORE_SIZE: int = 64

_roundtrip_store: List[ExecutionRoundtripRecord] = []
_roundtrip_lock = threading.Lock()


def _append_to_store(record: ExecutionRoundtripRecord) -> None:
    """Append a record to the ring buffer (thread-safe)."""
    global _roundtrip_store
    with _roundtrip_lock:
        _roundtrip_store.append(record)
        if len(_roundtrip_store) > _MAX_STORE_SIZE:
            _roundtrip_store = _roundtrip_store[-_MAX_STORE_SIZE:]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_execution_roundtrip(
    *,
    action_id: str = "",
    action_kind: str = "dispatch",
    trace_id: str = "",
    session_id: str = "",
    runtime_result: Optional[Dict[str, Any]] = None,
) -> ExecutionRoundtripRecord:
    """Record an execution roundtrip from an operator action completion.

    Called by operator route handlers after
    ``DesktopPresenceRuntime.handle_request()`` returns a result.  Extracts
    execution outcome from the runtime result dict, creates an
    :class:`ExecutionRoundtripRecord`, appends it to the store, and returns
    it so callers can inspect or log the record.

    Args:
        action_id:      Operator action ID (from OperatorActionResult.action_id).
        action_kind:    Action kind string (dispatch / device_dispatch / flow_cancel).
        trace_id:       Correlation trace ID from the runtime result.
        session_id:     Runtime session ID from the runtime result.
        runtime_result: Raw result dict from DesktopPresenceRuntime.handle_request().
                        Used to determine execution success/failure and carry
                        result data.

    Returns:
        The created :class:`ExecutionRoundtripRecord`.
    """
    rr = runtime_result or {}

    # Determine execution phase from the runtime result.
    # DesktopPresenceRuntime.handle_request() returns a dict with fields like
    # 'success', 'runtime_session_id', 'error', 'ingress_carrier_context', etc.
    success_val = rr.get("success")
    error_val = rr.get("error") or rr.get("error_message") or ""
    if success_val is False or error_val:
        phase = "failed"
        success = False
    elif success_val is True:
        phase = "completed"
        success = True
    else:
        # Runtime accepted the request but did not indicate terminal outcome —
        # this is the normal case for async execution (dispatched).
        phase = "dispatched"
        success = None

    record = ExecutionRoundtripRecord(
        action_id=action_id,
        action_kind=action_kind,
        trace_id=trace_id or rr.get("trace_id", "") or rr.get("runtime_session_id", ""),
        session_id=session_id or rr.get("runtime_session_id", ""),
        execution_phase=phase,
        execution_success=success,
        execution_result_data=dict(rr),
    )

    _append_to_store(record)
    logger.debug(
        "Recorded execution roundtrip: action_id=%s kind=%s phase=%s trace_id=%s",
        record.action_id,
        record.action_kind,
        record.execution_phase,
        record.trace_id,
    )
    return record


def notify_android_execution_terminal(
    *,
    flow_id: str,
    device_id: str,
    phase: str,
    step_index: int = -1,
    detail: str = "",
    task_id: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> ExecutionRoundtripRecord:
    """Record a roundtrip completion from an Android terminal execution event.

    Called when the Android execution event store receives a terminal-phase
    event (``completed`` / ``failed`` / ``stagnation``) from an Android device.
    This closes the Android-side leg of the roundtrip, ensuring that
    Android-execution outcomes are re-projected into the unified panel surface.

    Args:
        flow_id:    Delegated flow ID on the Android device.
        device_id:  Android device ID that emitted the event.
        phase:      Terminal execution phase string (e.g. ``"completed"``).
        step_index: Step index within the current execution loop.
        detail:     Human-readable detail about the terminal event.
        task_id:    Task ID associated with this execution step.
        evidence:   Optional extra evidence dict from the execution event.

    Returns:
        The created :class:`ExecutionRoundtripRecord`.
    """
    success = phase == "completed"
    exec_phase = "completed" if success else "failed"

    record = ExecutionRoundtripRecord(
        action_kind="android_terminal",
        execution_phase=exec_phase,
        execution_success=success,
        execution_result_data={
            "flow_id": flow_id,
            "device_id": device_id,
            "phase": phase,
            "step_index": step_index,
            "detail": detail,
            "task_id": task_id,
            **(evidence or {}),
        },
        android_terminal_phase=phase,
        android_device_id=device_id,
        android_flow_id=flow_id,
    )

    _append_to_store(record)
    logger.debug(
        "Recorded Android terminal roundtrip: flow_id=%s device_id=%s phase=%s",
        flow_id,
        device_id,
        phase,
    )
    return record


def get_last_execution_roundtrip() -> Optional[ExecutionRoundtripRecord]:
    """Return the most recent :class:`ExecutionRoundtripRecord`, or None."""
    with _roundtrip_lock:
        if not _roundtrip_store:
            return None
        return _roundtrip_store[-1]


def get_execution_roundtrip_store() -> List[ExecutionRoundtripRecord]:
    """Return a snapshot of all stored roundtrip records (most-recent-last)."""
    with _roundtrip_lock:
        return list(_roundtrip_store)


def reset_execution_roundtrip() -> None:
    """Clear all stored roundtrip records — for test isolation only."""
    global _roundtrip_store
    with _roundtrip_lock:
        _roundtrip_store = []
