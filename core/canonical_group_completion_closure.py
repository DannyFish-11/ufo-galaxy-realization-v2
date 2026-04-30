"""core/canonical_group_completion_closure.py
==============================================
PR-V5: Canonicalize group completion, delegated completion, and partial
failure semantics.

Problem addressed
-----------------
Prior to this module, advanced execution modes (parallel fan-out, delegated,
handoff, wake-routed, cross-device, hybrid) each maintained their own
completion truth:

* Subtask success could be mistakenly treated as group completion.
* Delegated ACK was not clearly distinguished from delegated terminal
  completion.
* Handoff terminal outcomes were not aligned with a canonical closure.
* Blocked-device exclusion had no defined effect on the completion contract.
* Partial success, degraded success, aggregate timeout, partial failure, and
  aggregate failure had no unified contract.

This module closes those gaps by providing a **single canonical completion
closure** that all advanced execution modes MUST pass through to decide
whether an orchestration has reached a terminal state, and what that terminal
state means.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────┐
    │  ADVANCED EXECUTION MODES                                    │
    │  parallel fan-out · delegated · handoff/takeover             │
    │  wake-routed · cross-device · hybrid                         │
    └──────────────────────┬───────────────────────────────────────┘
                           │  device result signals
                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │  CANONICAL GROUP COMPLETION CLOSURE   (this module)          │
    │  apply_completion_closure(context, contract) → outcome       │
    └──────────────────────┬───────────────────────────────────────┘
                           │  CanonicalCompletionOutcome
                           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │  CANONICAL COMPLETION INGRESS  (canonical_completion_ingress)│
    │  Future resolution / awaiter unblocking                      │
    └──────────────────────────────────────────────────────────────┘

Key semantics enforced
----------------------
1. **Subtask success ≠ group completion** — a group reaches
   ``CanonicalTerminalKind.complete`` only when the effective expected result
   count is satisfied, not when any individual subtask succeeds.

2. **Delegated ACK ≠ delegated terminal completion** — a
   ``DeviceResultSignal`` with ``signal_kind=SignalKind.delegated_ack`` is a
   non-terminal acknowledgement; it does not advance the closure toward any
   terminal state.

3. **Handoff terminal outcomes align with canonical closure** — handoff and
   takeover modes contribute ``SignalKind.handoff_terminal`` signals that pass
   through the same closure function as all other modes.

4. **Blocked-device exclusion has an explicit semantic** — the
   ``CompletionContract.blocked_device_exclusion`` field controls whether
   blocked slots shrink the effective expected count
   (``"exclude_from_contract"``), count as failures
   (``"promote_to_partial_failure"``), or abort the entire orchestration
   (``"abort_on_any_blocked"``).

5. **Aggregate timeout produces a canonical terminal state** — when
   ``CompletionContract.aggregate_timeout_seconds`` elapses before the
   expected results arrive, the closure produces
   ``CanonicalTerminalKind.aggregate_timeout``.

6. **Degraded success is explicitly allowed or prohibited** — the
   ``CompletionContract.degraded_success_allowed`` field controls whether a
   best-effort orchestration where some devices are excluded / timed-out
   may still produce ``CanonicalTerminalKind.degraded_success`` instead of
   ``CanonicalTerminalKind.partial_success`` or
   ``CanonicalTerminalKind.aggregate_failure``.

7. **Partial failure has a canonical definition** — when
   ``partial_failure_policy == "fail_all"`` and at least one device returns a
   failure signal, the outcome is
   ``CanonicalTerminalKind.partial_failure`` rather than
   ``CanonicalTerminalKind.partial_success``.

8. **Aggregate failure has a canonical definition** — when every device in the
   effective expected set returns a failure signal the outcome is
   ``CanonicalTerminalKind.aggregate_failure`` regardless of the
   ``partial_failure_policy``.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Composing, not duplicating** — delegates slot evaluation to
  :mod:`core.unified_orchestration_spine` and in-memory group tracking to
  :mod:`core.goal_result_aggregator`.
- **Stateless closure function** — :func:`apply_completion_closure` is a
  pure function; the coordinator singleton only holds audit state.
- **Graceful under incomplete data** — when not enough signals have arrived
  the function returns ``CanonicalTerminalKind.in_progress``.
- **Serialisable** — all public dataclasses expose ``to_dict()`` /
  ``to_json()``.

Authority sentinels
-------------------
:data:`CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY`
:data:`SUBTASK_SUCCESS_DOES_NOT_CONSTITUTE_GROUP_COMPLETION_POLICY`
:data:`DELEGATED_ACK_DISTINCT_FROM_DELEGATED_TERMINAL_POLICY`
:data:`HANDOFF_TERMINAL_ALIGNS_WITH_CANONICAL_CLOSURE_POLICY`
:data:`BLOCKED_DEVICE_EXCLUSION_SEMANTIC_IS_EXPLICIT_POLICY`
:data:`AGGREGATE_TIMEOUT_PRODUCES_CANONICAL_TERMINAL_POLICY`
:data:`DEGRADED_SUCCESS_REQUIRES_EXPLICIT_ALLOWANCE_POLICY`
:data:`PARTIAL_FAILURE_HAS_CANONICAL_DEFINITION_POLICY`
:data:`AGGREGATE_FAILURE_HAS_CANONICAL_DEFINITION_POLICY`
:data:`ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY`

Public API
----------
Enums::

    SignalKind
    CanonicalTerminalKind

Dataclasses::

    DeviceResultSignal
    CompletionClosureContext
    CanonicalCompletionOutcome

Functions::

    apply_completion_closure(context, contract) -> CanonicalCompletionOutcome
    get_completion_closure_coordinator() -> CompletionClosureCoordinator
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.CanonicalGroupCompletionClosure")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY: str = (
    "CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY::"
    "core.canonical_group_completion_closure::PR-V5::"
    "canonical-group-completion-delegated-completion-partial-failure-semantics::"
    "single-canonical-completion-closure-for-all-advanced-execution-modes"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

SUBTASK_SUCCESS_DOES_NOT_CONSTITUTE_GROUP_COMPLETION_POLICY: str = (
    "POLICY::SUBTASK_SUCCESS_DOES_NOT_CONSTITUTE_GROUP_COMPLETION_V1: "
    "A DeviceResultSignal with signal_kind=SignalKind.subtask_result and "
    "is_success=True does NOT advance the closure to a terminal state unless "
    "the effective expected result count is satisfied.  Individual subtask "
    "success is non-terminal at the group level; group completion is reached "
    "only when all results (success or failure) required by the "
    "CompletionContract have arrived.  "
    "PR-V5, canonical group completion closure."
)

DELEGATED_ACK_DISTINCT_FROM_DELEGATED_TERMINAL_POLICY: str = (
    "POLICY::DELEGATED_ACK_DISTINCT_FROM_DELEGATED_TERMINAL_V1: "
    "A DeviceResultSignal with signal_kind=SignalKind.delegated_ack is a "
    "non-terminal acknowledgement that the delegated execution was received "
    "by the target device.  It does NOT contribute to the effective result "
    "count and does NOT cause the closure to emit any terminal state.  Only "
    "a signal with signal_kind=SignalKind.delegated_terminal advances the "
    "delegated execution toward a canonical terminal state.  "
    "PR-V5, canonical group completion closure."
)

HANDOFF_TERMINAL_ALIGNS_WITH_CANONICAL_CLOSURE_POLICY: str = (
    "POLICY::HANDOFF_TERMINAL_ALIGNS_WITH_CANONICAL_CLOSURE_V1: "
    "Handoff and takeover execution modes produce terminal outcomes by "
    "contributing DeviceResultSignal entries with "
    "signal_kind=SignalKind.handoff_terminal.  These signals pass through "
    "the same apply_completion_closure() function as all other modes, "
    "ensuring that handoff terminal outcomes are subject to the same "
    "CompletionContract semantics (partial_failure_policy, "
    "blocked_device_exclusion, degraded_success_allowed, "
    "aggregate_timeout_seconds) as parallel, delegated, and other advanced "
    "modes.  Handoff completion is NOT a private completion reality.  "
    "PR-V5, canonical group completion closure."
)

BLOCKED_DEVICE_EXCLUSION_SEMANTIC_IS_EXPLICIT_POLICY: str = (
    "POLICY::BLOCKED_DEVICE_EXCLUSION_SEMANTIC_IS_EXPLICIT_V1: "
    "The CompletionContract.blocked_device_exclusion field determines how "
    "blocked (non-ready) devices affect the canonical completion outcome: "
    "  'exclude_from_contract' — blocked devices shrink the effective "
    "    expected result count; the contract is satisfied by the remaining "
    "    ready devices only.  "
    "  'promote_to_partial_failure' — each blocked device is treated as a "
    "    failure signal; the partial_failure_policy governs the outcome.  "
    "  'abort_on_any_blocked' — the presence of any blocked device causes "
    "    the orchestration to be aborted immediately.  "
    "When blocked_device_exclusion is 'exclude_from_contract' and all ready "
    "devices succeed, the outcome is 'complete' (or 'degraded_success' when "
    "some slots were excluded and degraded_success_allowed=True).  "
    "PR-V5, canonical group completion closure."
)

AGGREGATE_TIMEOUT_PRODUCES_CANONICAL_TERMINAL_POLICY: str = (
    "POLICY::AGGREGATE_TIMEOUT_PRODUCES_CANONICAL_TERMINAL_V1: "
    "When CompletionContract.aggregate_timeout_seconds is set and the elapsed "
    "time since the CompletionClosureContext.started_at exceeds this value "
    "without the required results having arrived, apply_completion_closure() "
    "returns CanonicalTerminalKind.aggregate_timeout.  This is a canonical "
    "terminal state; callers MUST treat it as final and close the orchestration "
    "rather than continuing to wait for results.  "
    "PR-V5, canonical group completion closure."
)

DEGRADED_SUCCESS_REQUIRES_EXPLICIT_ALLOWANCE_POLICY: str = (
    "POLICY::DEGRADED_SUCCESS_REQUIRES_EXPLICIT_ALLOWANCE_V1: "
    "A 'degraded_success' outcome (some devices excluded or timed out but "
    "the remaining results all succeeded) is only produced when "
    "CompletionContract.degraded_success_allowed=True.  When "
    "degraded_success_allowed=False, the same scenario produces "
    "'partial_success' or 'aggregate_failure' depending on the "
    "partial_failure_policy and failure count.  This ensures degraded "
    "success is an explicit opt-in rather than an accidental default.  "
    "PR-V5, canonical group completion closure."
)

PARTIAL_FAILURE_HAS_CANONICAL_DEFINITION_POLICY: str = (
    "POLICY::PARTIAL_FAILURE_HAS_CANONICAL_DEFINITION_V1: "
    "When CompletionContract.partial_failure_policy == 'fail_all' and at "
    "least one device result is a failure, the canonical terminal state is "
    "'partial_failure'.  This terminal state signals that the orchestration "
    "cannot be considered complete; the caller MUST abort or retry.  "
    "'partial_failure' is distinct from 'partial_success' (which applies "
    "when partial failures are tolerated) and 'aggregate_failure' (which "
    "requires all devices to have failed).  "
    "PR-V5, canonical group completion closure."
)

AGGREGATE_FAILURE_HAS_CANONICAL_DEFINITION_POLICY: str = (
    "POLICY::AGGREGATE_FAILURE_HAS_CANONICAL_DEFINITION_V1: "
    "When every device in the effective expected set returns a failure "
    "signal, the canonical terminal state is 'aggregate_failure', regardless "
    "of the partial_failure_policy.  'aggregate_failure' supersedes "
    "'partial_failure' and 'partial_success' when no device succeeded.  "
    "PR-V5, canonical group completion closure."
)

ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY: str = (
    "POLICY::ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_V1: "
    "All advanced execution modes — parallel fan-out, delegated runtime, "
    "handoff, takeover, wake-routed, cross-device, hybrid — MUST produce "
    "their canonical terminal state by calling apply_completion_closure(). "
    "No mode may maintain a private completion contract or emit a terminal "
    "state outside this closure.  Mode-local success/failure signals are "
    "inputs to the closure (DeviceResultSignal), not independent completion "
    "realities.  "
    "PR-V5, canonical group completion closure."
)

# ---------------------------------------------------------------------------
# SignalKind — classification of device result signals
# ---------------------------------------------------------------------------


class SignalKind(str, Enum):
    """Classification of a device result signal entering the closure.

    Values
    ------
    subtask_result
        A parallel-fan-out subtask completed (success or failure).  This is
        a non-terminal signal at the group level until all expected subtasks
        have arrived.
    delegated_ack
        The target device acknowledged receiving a delegated execution
        request.  NON-TERMINAL — does not advance the closure.  Callers
        MUST NOT treat this as delegated terminal completion.
    delegated_terminal
        A delegated execution reached its terminal state (success or
        failure).  This is a terminal signal for its slot.
    handoff_terminal
        A handoff or takeover execution reached its terminal state.
        Terminal signal for its slot.
    device_blocked
        A device was excluded from dispatch (blocked slot from canonical
        dispatch-slot authority).  The effect on the contract depends on
        CompletionContract.blocked_device_exclusion.
    timeout_signal
        The aggregate timeout expired.  Signals that the closure should
        produce aggregate_timeout without waiting for further results.
    local_terminal
        A local or single-device-remote execution reached its terminal
        state.
    wake_terminal
        A wake-routed execution reached its terminal state.
    """

    subtask_result = "subtask_result"
    delegated_ack = "delegated_ack"
    delegated_terminal = "delegated_terminal"
    handoff_terminal = "handoff_terminal"
    device_blocked = "device_blocked"
    timeout_signal = "timeout_signal"
    local_terminal = "local_terminal"
    wake_terminal = "wake_terminal"


# ---------------------------------------------------------------------------
# CanonicalTerminalKind — the set of canonical terminal states
# ---------------------------------------------------------------------------


class CanonicalTerminalKind(str, Enum):
    """Canonical terminal (and non-terminal) states for the completion closure.

    Non-terminal
    ------------
    in_progress
        Not enough result signals have arrived to determine a terminal
        state.  The orchestration is still waiting for device results.

    Terminal — success family
    -------------------------
    complete
        All required results received and all succeeded.
    degraded_success
        All received results succeeded but some devices were excluded/timed-
        out.  Only produced when CompletionContract.degraded_success_allowed
        is True.

    Terminal — partial family
    -------------------------
    partial_success
        Some devices succeeded and some failed; the partial_failure_policy
        permits this outcome (policy is ``"best_effort"`` or
        ``"require_majority"`` with majority met).

    Terminal — failure family
    -------------------------
    partial_failure
        At least one device failed and partial_failure_policy is
        ``"fail_all"``.  The orchestration cannot be considered complete.
    aggregate_failure
        All devices in the effective expected set returned failure signals.
    aggregate_timeout
        The aggregate timeout elapsed before the required results arrived.
    aborted
        The orchestration was explicitly aborted (e.g. all devices blocked
        with ``blocked_device_exclusion="abort_on_any_blocked"`` or the
        caller injected an abort signal).
    """

    in_progress = "in_progress"
    complete = "complete"
    degraded_success = "degraded_success"
    partial_success = "partial_success"
    partial_failure = "partial_failure"
    aggregate_failure = "aggregate_failure"
    aggregate_timeout = "aggregate_timeout"
    aborted = "aborted"

    @property
    def is_terminal(self) -> bool:
        """True when this state is a terminal (final) state."""
        return self != CanonicalTerminalKind.in_progress


# ---------------------------------------------------------------------------
# DeviceResultSignal
# ---------------------------------------------------------------------------


@dataclass
class DeviceResultSignal:
    """A single result signal from one device slot.

    Fields
    ------
    device_id
        The device that contributed this signal.
    signal_kind
        The :class:`SignalKind` classifying this signal.
    is_success
        True when the signal represents a successful outcome.  For
        ``delegated_ack`` this is always False (the signal is non-terminal).
        For ``timeout_signal`` and ``device_blocked`` this field has no
        completion-contract meaning.
    result_payload
        Optional raw result payload for observability.
    received_at
        Unix timestamp when the signal was received.
    signal_id
        Unique identifier for this signal (idempotency key).
    """

    device_id: str
    signal_kind: str = SignalKind.subtask_result.value
    is_success: bool = False
    result_payload: Optional[Dict[str, Any]] = None
    received_at: float = field(default_factory=time.time)
    signal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def is_terminal_signal(self) -> bool:
        """True when this signal kind contributes to the terminal result count."""
        return self.signal_kind not in (
            SignalKind.delegated_ack.value,
            SignalKind.device_blocked.value,
        )

    @property
    def is_blocked_signal(self) -> bool:
        """True when this represents a device that was blocked from dispatch."""
        return self.signal_kind == SignalKind.device_blocked.value

    @property
    def is_timeout_signal(self) -> bool:
        """True when this is the aggregate timeout sentinel."""
        return self.signal_kind == SignalKind.timeout_signal.value

    @property
    def is_ack_signal(self) -> bool:
        """True when this is a non-terminal delegated ACK."""
        return self.signal_kind == SignalKind.delegated_ack.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "signal_kind": self.signal_kind,
            "is_success": self.is_success,
            "is_terminal_signal": self.is_terminal_signal,
            "is_ack_signal": self.is_ack_signal,
            "result_payload": self.result_payload,
            "received_at": self.received_at,
            "signal_id": self.signal_id,
        }


# ---------------------------------------------------------------------------
# CompletionClosureContext
# ---------------------------------------------------------------------------


@dataclass
class CompletionClosureContext:
    """Full context supplied to the canonical completion closure.

    Fields
    ------
    orchestration_id
        Identifier of the orchestration being evaluated.
    execution_mode
        The execution mode (value from ExecutionMode enum).
    signals
        All :class:`DeviceResultSignal` entries received so far.
    expected_device_ids
        The full set of device IDs targeted by this orchestration.  Includes
        both ready and blocked devices.
    started_at
        Unix timestamp when the orchestration was dispatched (for timeout
        evaluation).
    group_id
        Optional fan-out group identifier.
    trace_id
        Optional trace identifier for observability.
    """

    orchestration_id: str = field(
        default_factory=lambda: f"ctx_{uuid.uuid4().hex[:10]}"
    )
    execution_mode: str = "single_device_remote"
    signals: List[DeviceResultSignal] = field(default_factory=list)
    expected_device_ids: List[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    group_id: Optional[str] = None
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orchestration_id": self.orchestration_id,
            "execution_mode": self.execution_mode,
            "signals": [s.to_dict() for s in self.signals],
            "expected_device_ids": list(self.expected_device_ids),
            "started_at": self.started_at,
            "group_id": self.group_id,
            "trace_id": self.trace_id,
        }


# ---------------------------------------------------------------------------
# CanonicalCompletionOutcome
# ---------------------------------------------------------------------------


@dataclass
class CanonicalCompletionOutcome:
    """Result of applying the canonical completion closure.

    Fields
    ------
    terminal_kind
        The :class:`CanonicalTerminalKind` determined by the closure.
    is_terminal
        True when the terminal_kind is a final state.
    effective_expected_count
        The number of results that the closure required (after blocked-device
        exclusion adjustment).
    success_count
        Number of terminal signals that were successful.
    failure_count
        Number of terminal signals that were failures.
    blocked_count
        Number of device_blocked signals received.
    ack_count
        Number of non-terminal delegated_ack signals (informational only).
    policy_reference
        The policy sentinel string that governed the terminal decision.
    evidence
        Dict of key evidence values used to reach the decision.
    orchestration_id
        Passed through from the context for correlation.
    evaluated_at
        Unix timestamp when the closure was evaluated.
    """

    terminal_kind: str = CanonicalTerminalKind.in_progress.value
    is_terminal: bool = False
    effective_expected_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    blocked_count: int = 0
    ack_count: int = 0
    policy_reference: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    orchestration_id: str = ""
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "terminal_kind": self.terminal_kind,
            "is_terminal": self.is_terminal,
            "effective_expected_count": self.effective_expected_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "blocked_count": self.blocked_count,
            "ack_count": self.ack_count,
            "policy_reference": self.policy_reference,
            "evidence": dict(self.evidence),
            "orchestration_id": self.orchestration_id,
            "evaluated_at": self.evaluated_at,
            "authority": CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# apply_completion_closure — the canonical closure function
# ---------------------------------------------------------------------------


def apply_completion_closure(
    context: CompletionClosureContext,
    contract: Any,
) -> CanonicalCompletionOutcome:
    """Apply the canonical completion closure.

    This is the **single canonical function** that all advanced execution modes
    MUST use to determine whether an orchestration has reached a terminal state.

    Parameters
    ----------
    context:
        :class:`CompletionClosureContext` carrying all device signals received
        so far and the orchestration metadata.
    contract:
        A :class:`~core.unified_orchestration_spine.CompletionContract` (or
        duck-typed equivalent with ``expected_result_count``,
        ``partial_failure_policy``, ``aggregation_mode``,
        ``blocked_device_exclusion``, ``degraded_success_allowed``, and
        ``aggregate_timeout_seconds`` attributes).

    Returns
    -------
    CanonicalCompletionOutcome
        Always returns a valid outcome; never raises.

    Semantics
    ---------
    1. ACK signals are counted but excluded from the terminal result count.
    2. Blocked signals are handled per ``contract.blocked_device_exclusion``.
    3. Timeout check is performed before result-count evaluation.
    4. Terminal kind is resolved in priority order:
       aggregate_failure > partial_failure > aggregate_timeout >
       aborted > complete > degraded_success > partial_success > in_progress
    """
    try:
        return _apply_closure_impl(context, contract)
    except Exception as exc:
        logger.warning(
            "canonical_group_completion_closure: error in apply_completion_closure: %s",
            exc,
            exc_info=True,
        )
        return CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.in_progress.value,
            is_terminal=False,
            orchestration_id=context.orchestration_id,
            policy_reference=CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY,
            evidence={"error": str(exc)},
        )


def _apply_closure_impl(
    context: CompletionClosureContext,
    contract: Any,
) -> CanonicalCompletionOutcome:
    """Internal implementation of the canonical completion closure."""
    # ----------------------------------------------------------------
    # Extract contract fields with safe defaults
    # ----------------------------------------------------------------
    expected_result_count: int = getattr(contract, "expected_result_count", 0)
    partial_failure_policy: str = getattr(contract, "partial_failure_policy", "best_effort")
    aggregation_mode: str = getattr(contract, "aggregation_mode", "all_required")
    blocked_device_exclusion: str = getattr(
        contract, "blocked_device_exclusion", "exclude_from_contract"
    )
    degraded_success_allowed: bool = getattr(contract, "degraded_success_allowed", False)
    aggregate_timeout_seconds: Optional[float] = getattr(
        contract, "aggregate_timeout_seconds", None
    )

    # ----------------------------------------------------------------
    # Classify signals
    # ----------------------------------------------------------------
    ack_signals: List[DeviceResultSignal] = []
    blocked_signals: List[DeviceResultSignal] = []
    timeout_signals: List[DeviceResultSignal] = []
    terminal_signals: List[DeviceResultSignal] = []

    for sig in context.signals:
        if sig.is_ack_signal:
            ack_signals.append(sig)
        elif sig.is_blocked_signal:
            blocked_signals.append(sig)
        elif sig.is_timeout_signal:
            timeout_signals.append(sig)
        else:
            terminal_signals.append(sig)

    ack_count = len(ack_signals)
    blocked_count = len(blocked_signals)
    success_count = sum(1 for s in terminal_signals if s.is_success)
    failure_count = sum(1 for s in terminal_signals if not s.is_success)
    terminal_arrived = len(terminal_signals)

    # ----------------------------------------------------------------
    # Apply blocked-device exclusion semantic
    # ----------------------------------------------------------------
    if blocked_device_exclusion == "abort_on_any_blocked" and blocked_count > 0:
        return CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.aborted.value,
            is_terminal=True,
            effective_expected_count=expected_result_count,
            success_count=success_count,
            failure_count=failure_count,
            blocked_count=blocked_count,
            ack_count=ack_count,
            policy_reference=BLOCKED_DEVICE_EXCLUSION_SEMANTIC_IS_EXPLICIT_POLICY,
            evidence={
                "blocked_device_exclusion": blocked_device_exclusion,
                "blocked_count": blocked_count,
                "decision": "abort_on_any_blocked triggered",
            },
            orchestration_id=context.orchestration_id,
        )

    if blocked_device_exclusion == "promote_to_partial_failure":
        # Treat each blocked device as a failure
        failure_count += blocked_count
    # "exclude_from_contract": reduce effective expected count by the number
    # of blocked devices so they do not count toward the required total.
    exclusion_adjustment = (
        blocked_count if blocked_device_exclusion == "exclude_from_contract" else 0
    )
    effective_expected_count = max(0, expected_result_count - exclusion_adjustment)

    # ----------------------------------------------------------------
    # Check for explicit timeout signal or wall-clock timeout
    # ----------------------------------------------------------------
    timed_out = bool(timeout_signals)
    if not timed_out and aggregate_timeout_seconds is not None:
        elapsed = time.time() - context.started_at
        if elapsed >= aggregate_timeout_seconds and terminal_arrived < effective_expected_count:
            timed_out = True

    # ----------------------------------------------------------------
    # Aggregate failure — all required results arrived and none succeeded.
    # This check precedes partial_failure so that aggregate_failure
    # supersedes it when every device returned a failure signal.
    # ----------------------------------------------------------------
    if effective_expected_count > 0 and terminal_arrived >= effective_expected_count:
        if success_count == 0:
            return CanonicalCompletionOutcome(
                terminal_kind=CanonicalTerminalKind.aggregate_failure.value,
                is_terminal=True,
                effective_expected_count=effective_expected_count,
                success_count=0,
                failure_count=failure_count,
                blocked_count=blocked_count,
                ack_count=ack_count,
                policy_reference=AGGREGATE_FAILURE_HAS_CANONICAL_DEFINITION_POLICY,
                evidence={
                    "terminal_arrived": terminal_arrived,
                    "effective_expected_count": effective_expected_count,
                    "success_count": 0,
                    "failure_count": failure_count,
                    "decision": "aggregate_failure: no successes",
                },
                orchestration_id=context.orchestration_id,
            )

    # ----------------------------------------------------------------
    # Partial failure — fail_all policy and at least one failure
    # ----------------------------------------------------------------
    if partial_failure_policy == "fail_all" and failure_count > 0:
        return CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.partial_failure.value,
            is_terminal=True,
            effective_expected_count=effective_expected_count,
            success_count=success_count,
            failure_count=failure_count,
            blocked_count=blocked_count,
            ack_count=ack_count,
            policy_reference=PARTIAL_FAILURE_HAS_CANONICAL_DEFINITION_POLICY,
            evidence={
                "partial_failure_policy": partial_failure_policy,
                "failure_count": failure_count,
                "decision": "partial_failure: fail_all policy violated",
            },
            orchestration_id=context.orchestration_id,
        )

    # ----------------------------------------------------------------
    # Aggregate timeout
    # ----------------------------------------------------------------
    if timed_out:
        return CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.aggregate_timeout.value,
            is_terminal=True,
            effective_expected_count=effective_expected_count,
            success_count=success_count,
            failure_count=failure_count,
            blocked_count=blocked_count,
            ack_count=ack_count,
            policy_reference=AGGREGATE_TIMEOUT_PRODUCES_CANONICAL_TERMINAL_POLICY,
            evidence={
                "aggregate_timeout_seconds": aggregate_timeout_seconds,
                "terminal_arrived": terminal_arrived,
                "effective_expected_count": effective_expected_count,
                "decision": "aggregate_timeout: not all results arrived before timeout",
            },
            orchestration_id=context.orchestration_id,
        )

    # ----------------------------------------------------------------
    # Not yet enough results — still in progress
    # ----------------------------------------------------------------
    if effective_expected_count == 0:
        # No results expected (all blocked + exclude_from_contract)
        # Treat as aborted if blocked_count > 0, else in_progress
        if blocked_count > 0 and terminal_arrived == 0:
            return CanonicalCompletionOutcome(
                terminal_kind=CanonicalTerminalKind.aborted.value,
                is_terminal=True,
                effective_expected_count=0,
                success_count=0,
                failure_count=0,
                blocked_count=blocked_count,
                ack_count=ack_count,
                policy_reference=BLOCKED_DEVICE_EXCLUSION_SEMANTIC_IS_EXPLICIT_POLICY,
                evidence={
                    "blocked_device_exclusion": blocked_device_exclusion,
                    "blocked_count": blocked_count,
                    "decision": "all devices blocked, effective_expected_count=0 → aborted",
                },
                orchestration_id=context.orchestration_id,
            )
        # Zero expected and zero blocked: edge case, treat as in_progress
        return CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.in_progress.value,
            is_terminal=False,
            effective_expected_count=0,
            success_count=success_count,
            failure_count=failure_count,
            blocked_count=blocked_count,
            ack_count=ack_count,
            policy_reference=ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY,
            evidence={"decision": "effective_expected_count=0, no results yet"},
            orchestration_id=context.orchestration_id,
        )

    # ----------------------------------------------------------------
    # any_success aggregation: complete on first successful terminal
    # ----------------------------------------------------------------
    if aggregation_mode == "any_success" and success_count >= 1:
        return CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.complete.value,
            is_terminal=True,
            effective_expected_count=effective_expected_count,
            success_count=success_count,
            failure_count=failure_count,
            blocked_count=blocked_count,
            ack_count=ack_count,
            policy_reference=ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY,
            evidence={
                "aggregation_mode": aggregation_mode,
                "success_count": success_count,
                "decision": "complete: any_success satisfied",
            },
            orchestration_id=context.orchestration_id,
        )

    if terminal_arrived < effective_expected_count:
        return CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.in_progress.value,
            is_terminal=False,
            effective_expected_count=effective_expected_count,
            success_count=success_count,
            failure_count=failure_count,
            blocked_count=blocked_count,
            ack_count=ack_count,
            policy_reference=SUBTASK_SUCCESS_DOES_NOT_CONSTITUTE_GROUP_COMPLETION_POLICY,
            evidence={
                "terminal_arrived": terminal_arrived,
                "effective_expected_count": effective_expected_count,
                "decision": (
                    "in_progress: subtask results received but group not yet complete"
                ),
            },
            orchestration_id=context.orchestration_id,
        )

    # ----------------------------------------------------------------
    # All expected results have arrived.  Determine success/partial outcome.
    # ----------------------------------------------------------------
    # At this point: terminal_arrived >= effective_expected_count
    # and success_count > 0 (aggregate_failure was already handled above).

    has_excluded_devices = (
        blocked_device_exclusion == "exclude_from_contract"
        and blocked_count > 0
    )

    if failure_count == 0:
        # All succeeded
        if has_excluded_devices and degraded_success_allowed:
            terminal_kind = CanonicalTerminalKind.degraded_success.value
            policy_ref = DEGRADED_SUCCESS_REQUIRES_EXPLICIT_ALLOWANCE_POLICY
            decision = "degraded_success: all received results succeeded, some devices excluded"
        else:
            terminal_kind = CanonicalTerminalKind.complete.value
            policy_ref = ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY
            decision = "complete: all required results received and succeeded"

        return CanonicalCompletionOutcome(
            terminal_kind=terminal_kind,
            is_terminal=True,
            effective_expected_count=effective_expected_count,
            success_count=success_count,
            failure_count=0,
            blocked_count=blocked_count,
            ack_count=ack_count,
            policy_reference=policy_ref,
            evidence={
                "has_excluded_devices": has_excluded_devices,
                "degraded_success_allowed": degraded_success_allowed,
                "decision": decision,
            },
            orchestration_id=context.orchestration_id,
        )

    # Some failures but not all (aggregate_failure already handled).
    # Decide between partial_success and partial_failure.
    # require_majority: need more than half of effective expected to succeed.
    if partial_failure_policy == "require_majority":
        majority = effective_expected_count // 2 + 1
        if success_count >= majority:
            return CanonicalCompletionOutcome(
                terminal_kind=CanonicalTerminalKind.partial_success.value,
                is_terminal=True,
                effective_expected_count=effective_expected_count,
                success_count=success_count,
                failure_count=failure_count,
                blocked_count=blocked_count,
                ack_count=ack_count,
                policy_reference=ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY,
                evidence={
                    "partial_failure_policy": partial_failure_policy,
                    "majority": majority,
                    "success_count": success_count,
                    "decision": "partial_success: majority succeeded",
                },
                orchestration_id=context.orchestration_id,
            )
        else:
            return CanonicalCompletionOutcome(
                terminal_kind=CanonicalTerminalKind.partial_failure.value,
                is_terminal=True,
                effective_expected_count=effective_expected_count,
                success_count=success_count,
                failure_count=failure_count,
                blocked_count=blocked_count,
                ack_count=ack_count,
                policy_reference=PARTIAL_FAILURE_HAS_CANONICAL_DEFINITION_POLICY,
                evidence={
                    "partial_failure_policy": partial_failure_policy,
                    "majority": majority,
                    "success_count": success_count,
                    "decision": "partial_failure: majority not reached",
                },
                orchestration_id=context.orchestration_id,
            )

    # best_effort: partial success
    return CanonicalCompletionOutcome(
        terminal_kind=CanonicalTerminalKind.partial_success.value,
        is_terminal=True,
        effective_expected_count=effective_expected_count,
        success_count=success_count,
        failure_count=failure_count,
        blocked_count=blocked_count,
        ack_count=ack_count,
        policy_reference=ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY,
        evidence={
            "partial_failure_policy": partial_failure_policy,
            "success_count": success_count,
            "failure_count": failure_count,
            "decision": "partial_success: best_effort policy, some succeeded",
        },
        orchestration_id=context.orchestration_id,
    )


# ---------------------------------------------------------------------------
# CompletionClosureCoordinator — audit ring-buffer singleton
# ---------------------------------------------------------------------------


class CompletionClosureCoordinator:
    """In-process audit ring-buffer for canonical completion closure decisions.

    Records every :class:`CanonicalCompletionOutcome` produced by
    :func:`apply_completion_closure` so operator surfaces can inspect the
    closure history without re-deriving it.

    Thread-safe.  Outcomes are stored in a fixed-size deque (newest last).
    """

    _MAX_ENTRIES: int = 512

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._outcomes: Deque[CanonicalCompletionOutcome] = deque(
            maxlen=self._MAX_ENTRIES
        )

    def record(self, outcome: CanonicalCompletionOutcome) -> None:
        """Append *outcome* to the audit buffer."""
        with self._lock:
            self._outcomes.append(outcome)
        if outcome.is_terminal:
            logger.info(
                "canonical_group_completion_closure: terminal outcome "
                "orchestration_id=%r kind=%r success=%d failure=%d",
                outcome.orchestration_id,
                outcome.terminal_kind,
                outcome.success_count,
                outcome.failure_count,
            )

    def snapshot(self) -> List[CanonicalCompletionOutcome]:
        """Return a point-in-time snapshot of recorded outcomes."""
        with self._lock:
            return list(self._outcomes)

    def clear(self) -> None:
        """Clear the audit buffer (test helper)."""
        with self._lock:
            self._outcomes.clear()


_coordinator: CompletionClosureCoordinator = CompletionClosureCoordinator()


def get_completion_closure_coordinator() -> CompletionClosureCoordinator:
    """Return the process-local :class:`CompletionClosureCoordinator` singleton."""
    return _coordinator


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY",
    "SUBTASK_SUCCESS_DOES_NOT_CONSTITUTE_GROUP_COMPLETION_POLICY",
    "DELEGATED_ACK_DISTINCT_FROM_DELEGATED_TERMINAL_POLICY",
    "HANDOFF_TERMINAL_ALIGNS_WITH_CANONICAL_CLOSURE_POLICY",
    "BLOCKED_DEVICE_EXCLUSION_SEMANTIC_IS_EXPLICIT_POLICY",
    "AGGREGATE_TIMEOUT_PRODUCES_CANONICAL_TERMINAL_POLICY",
    "DEGRADED_SUCCESS_REQUIRES_EXPLICIT_ALLOWANCE_POLICY",
    "PARTIAL_FAILURE_HAS_CANONICAL_DEFINITION_POLICY",
    "AGGREGATE_FAILURE_HAS_CANONICAL_DEFINITION_POLICY",
    "ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY",
    "SignalKind",
    "CanonicalTerminalKind",
    "DeviceResultSignal",
    "CompletionClosureContext",
    "CanonicalCompletionOutcome",
    "apply_completion_closure",
    "CompletionClosureCoordinator",
    "get_completion_closure_coordinator",
]
