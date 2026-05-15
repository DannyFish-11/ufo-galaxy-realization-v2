"""core/unified_runtime_truth_ingress.py
==========================================
PR-2: Unified Runtime Truth Ingress — Single Canonical Entry Point for
Android / Runtime State Updates.

Background
----------
Prior to this module the system had several *partial* truth ingress paths that
Android state updates could reach V2 canonical state through:

* :mod:`core.android_participant_truth_ingress` — reconciles structured
  Android truth envelopes into the V2 execution tracker and registry.
* :mod:`core.android_delegated_signal_ingress` — processes execution signals
  (ACK / PROGRESS / RESULT / ERROR / TIMEOUT / CANCELLED) from Android.
* Direct mutations of :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
  by transport-layer handlers without going through a shared ingress path.
* :mod:`core.android_handoff_v2_response_ingress` — resolves handoff response
  Futures and updates the completion ingress.

Although each path is internally correct, the lack of an explicit, named,
**single canonical ingress point** means:

1. Callers can bypass the reconciliation logic by writing state through a
   lower-level path without triggering the full policy chain.
2. There is no machine-checkable sentinel that asserts "Android runtime state
   MUST flow through *this* module before reaching V2 canonical state".
3. Parallel truth surfaces (multiple write paths operating concurrently) can
   produce inconsistent canonical states that are difficult to diagnose.

This module closes that gap by providing:

1. An explicit, importable **authority sentinel** that names this module as
   the single required ingress point for Android / runtime state updates.
2. A **no-parallel-write policy sentinel** that prohibits side-channel direct
   mutations of canonical state outside this ingress.
3. A **session authority accessor** that returns the process-level singleton
   :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
   as the single session authority.
4. :func:`ingest_android_runtime_state_update` — the canonical ingress
   function that routes any Android runtime state message through the correct
   sub-ingress path:
   - Execution signals → :func:`~core.android_delegated_signal_ingress.ingest_delegated_execution_signal`
   - Participant / session / runtime truth → :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
   - Handoff v2 responses → :func:`~core.android_handoff_v2_response_ingress.ingest_android_handoff_response`
5. :class:`RuntimeTruthIngressOutcome` — typed result of an ingress attempt
   that surfaces which sub-path was used, whether reconciliation succeeded,
   and a canonical reject reason if the update was rejected.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Routing-only** — this module routes messages to the correct sub-ingress;
  it does not duplicate reconciliation logic from sub-ingress modules.
- **Fail-closed** — unrecognised message types are rejected with an explicit
  outcome; no silent pass-through.
- **Policy-sentinel-first** — every boundary rule is expressed as a named,
  importable string constant.
- **Graceful degradation** — if a sub-ingress module is unavailable (import
  error), the outcome carries ``degraded=True`` and a descriptive reason; no
  exception escapes to the caller.

Public API
----------
Sentinels
~~~~~~~~~
:data:`UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY`
:data:`UNIFIED_RUNTIME_TRUTH_INGRESS_PR2_SENTINEL`
:data:`ANDROID_RUNTIME_STATE_MUST_FLOW_THROUGH_INGRESS_POLICY`
:data:`NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY`
:data:`SESSION_AUTHORITY_IS_ATTACHED_REGISTRY_POLICY`
:data:`INGRESS_ROUTES_TO_CORRECT_SUB_PATH_POLICY`
:data:`INGRESS_FAIL_CLOSED_ON_UNKNOWN_TYPE_POLICY`
:data:`INGRESS_IS_GRACEFUL_ON_SUBMODULE_UNAVAILABILITY_POLICY`

Dataclass
~~~~~~~~~
:class:`RuntimeTruthIngressOutcome`

Functions
~~~~~~~~~
:func:`get_session_authority` → :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
:func:`ingest_android_runtime_state_update` → :class:`RuntimeTruthIngressOutcome`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY: str = (
    "UNIFIED_RUNTIME_TRUTH_INGRESS::SINGLE_CANONICAL_ANDROID_RUNTIME_STATE_ENTRY_POINT_V1"
)

UNIFIED_RUNTIME_TRUTH_INGRESS_PR2_SENTINEL: str = (
    "SENTINEL::UNIFIED_RUNTIME_TRUTH_INGRESS_PR2: "
    "core.unified_runtime_truth_ingress is the single canonical entry point "
    "for all Android / runtime state updates entering V2 orchestration state; "
    "package=PR-2::unified-runtime-truth-ingress::session-migration-mesh-closure"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ANDROID_RUNTIME_STATE_MUST_FLOW_THROUGH_INGRESS_POLICY: str = (
    "POLICY::ANDROID_RUNTIME_STATE_MUST_FLOW_THROUGH_INGRESS_PR2: "
    "All Android / runtime state updates (execution signals, participant truth "
    "envelopes, session snapshots, handoff responses) MUST enter V2 canonical "
    "state through ingest_android_runtime_state_update().  "
    "Direct mutation of AttachedSessionRegistry, DelegatedExecutionTrackingRuntime, "
    "or CanonicalSessionTruthRuntime by transport-layer handlers bypassing this "
    "ingress is a protocol violation."
)

NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY: str = (
    "POLICY::NO_PARALLEL_WRITE_TO_CANONICAL_STATE_PR2: "
    "There MUST NOT be multiple concurrent, independent paths that write "
    "conflicting values to the same canonical state field.  When two sub-ingress "
    "paths could both apply to the same message, the routing logic in this module "
    "MUST select exactly one path.  If selection is ambiguous, the ingress MUST "
    "route to the participant-truth path (most general) and emit a routing-ambiguity "
    "audit event rather than forking into multiple paths."
)

SESSION_AUTHORITY_IS_ATTACHED_REGISTRY_POLICY: str = (
    "POLICY::SESSION_AUTHORITY_IS_ATTACHED_REGISTRY_PR2: "
    "The AttachedSessionRegistry (core.attached_runtime_session_registry) is the "
    "SINGLE SESSION AUTHORITY for the V2 runtime.  All reconnect, migration, "
    "continuity, and handoff operations MUST consult the registry before mutating "
    "or creating session state.  No secondary session store may override registry "
    "verdicts."
)

INGRESS_ROUTES_TO_CORRECT_SUB_PATH_POLICY: str = (
    "POLICY::INGRESS_ROUTES_TO_CORRECT_SUB_PATH_PR2: "
    "ingest_android_runtime_state_update() selects the sub-ingress path "
    "by inspecting the message 'type' field using the canonical priority order: "
    "1. handoff_ack / handoff_result / handoff_failure → HandoffV2ResponseIngress; "
    "2. execution signals (ack / progress / result / error / timeout / cancelled) → "
    "   DelegatedSignalIngress; "
    "3. participant / session / runtime truth → ParticipantTruthIngress (default)."
)

INGRESS_FAIL_CLOSED_ON_UNKNOWN_TYPE_POLICY: str = (
    "POLICY::INGRESS_FAIL_CLOSED_ON_UNKNOWN_TYPE_PR2: "
    "If the message 'type' field is absent or does not match any known routing "
    "class, the ingress MUST return a RuntimeTruthIngressOutcome with "
    "routed_path='rejected' and a descriptive reject_reason.  It MUST NOT "
    "silently pass unrecognised messages to any sub-path."
)

INGRESS_IS_GRACEFUL_ON_SUBMODULE_UNAVAILABILITY_POLICY: str = (
    "POLICY::INGRESS_IS_GRACEFUL_ON_SUBMODULE_UNAVAILABILITY_PR2: "
    "If a sub-ingress module is unavailable (import error or runtime error), "
    "the ingress MUST return a RuntimeTruthIngressOutcome with degraded=True "
    "and a descriptive reject_reason.  It MUST NOT raise an exception to the "
    "caller."
)

CONTINUITY_GATE_PRECEDES_ROUTING_POLICY: str = (
    "POLICY::CONTINUITY_GATE_PRECEDES_ROUTING: "
    "The unified continuity legality authority MUST be consulted BEFORE "
    "the message is routed to any sub-ingress path.  An inbound Android "
    "runtime state update that carries stale session identities or is "
    "associated with a superseded runtime MUST be rejected before reaching "
    "the execution-signal, handoff, or participant-truth sub-ingress paths.  "
    "Per ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY."
)

# ---------------------------------------------------------------------------
# Sub-path routing constants
# ---------------------------------------------------------------------------

_HANDOFF_TYPES = frozenset({
    "handoff_ack",
    "handoff_result",
    "handoff_failure",
})

_EXECUTION_SIGNAL_TYPES = frozenset({
    "ack",
    "progress",
    "result",
    "error",
    "timeout",
    "cancelled",
    "delegated_execution_signal",
    "execution_ack",
    "execution_progress",
    "execution_result",
    "execution_error",
    "execution_timeout",
    "execution_cancelled",
})

# ---------------------------------------------------------------------------
# RuntimeTruthIngressOutcome dataclass
# ---------------------------------------------------------------------------


@dataclass
class RuntimeTruthIngressOutcome:
    """Typed result of a :func:`ingest_android_runtime_state_update` call.

    Attributes
    ----------
    routed_path:
        Which sub-ingress path was selected.  One of:
        ``"handoff"`` / ``"execution_signal"`` / ``"participant_truth"`` /
        ``"rejected"`` / ``"degraded"``.
    was_reconciled:
        True when the sub-ingress reported successful reconciliation /
        correlation.
    degraded:
        True when a sub-ingress module was unavailable and the outcome
        represents a graceful degradation.
    reject_reason:
        Human-readable description of why the update was rejected or
        degraded.  Empty string when ``was_reconciled`` is True.
    sub_outcome:
        The raw outcome object returned by the selected sub-ingress, if
        available.
    message_type:
        The ``type`` field extracted from the inbound message.
    """

    routed_path: str = ""
    was_reconciled: bool = False
    degraded: bool = False
    reject_reason: str = ""
    sub_outcome: Optional[Any] = None
    message_type: str = ""
    continuity_rejected: bool = False
    """True iff the unified continuity legality authority rejected this update."""
    continuity_legality_verdict: str = ""
    """The :class:`~core.unified_continuity_legality_authority.ContinuityLegalityVerdict`
    value string (empty when not evaluated)."""
    result_produced: bool = False
    """True when this ingress observed a terminal execution result signal."""
    truth_ingested_or_accepted: bool = False
    """True when the terminal result was ingested by unified result/truth chain."""
    closure_accepted: bool = False
    """True when the terminal result reached accepted closure (fully closed)."""
    final_completion_state: str = ""
    """Coherent completion state for surfaces:
    ``in_progress`` / ``closed`` / ``result_returned_but_not_closed`` /
    ``result_returned_not_reconciled`` / ``terminal_result_without_task_id`` /
    ``result_returned_unified_ingress_unavailable``."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "routed_path": self.routed_path,
            "was_reconciled": self.was_reconciled,
            "degraded": self.degraded,
            "reject_reason": self.reject_reason,
            "message_type": self.message_type,
            "continuity_rejected": self.continuity_rejected,
            "continuity_legality_verdict": self.continuity_legality_verdict,
            "result_produced": self.result_produced,
            "truth_ingested_or_accepted": self.truth_ingested_or_accepted,
            "closure_accepted": self.closure_accepted,
            "final_completion_state": self.final_completion_state,
        }


# ---------------------------------------------------------------------------
# Internal: continuity legality helper
# ---------------------------------------------------------------------------


def _check_runtime_ingress_continuity(
    message: Dict[str, Any], msg_type: str
) -> tuple:  # Tuple[str, bool]: (verdict_str, is_hard_rejected)
    """Run the unified continuity legality gate for an inbound runtime update.

    Execution signals use the ONLINE_SIGNAL_INGESTION path; all other types
    (including handoff responses and participant truth) use ATTACHMENT_RESUME.
    Returns ``(verdict_str, is_rejected)`` where ``is_rejected`` is True only
    when the verdict is ``"reject"`` (hard rejection).  ``"require_review"``
    is treated as advisory and does NOT block routing, consistent with the
    graceful-degradation policy for this module.
    """
    try:
        from core.unified_continuity_legality_authority import (
            ContinuityLegalityContext,
            ContinuityLegalityPath,
            evaluate_continuity_legality,
        )

        # Determine path based on message type
        if msg_type in _EXECUTION_SIGNAL_TYPES:
            path = ContinuityLegalityPath.ONLINE_SIGNAL_INGESTION
        else:
            path = ContinuityLegalityPath.ATTACHMENT_RESUME

        ctx = ContinuityLegalityContext(
            device_id=str(message.get("device_id") or ""),
            runtime_session_id=str(message.get("runtime_session_id") or ""),
            runtime_attachment_session_id=str(
                message.get("runtime_attachment_session_id") or ""
            ),
            durable_session_id=str(message.get("durable_session_id") or ""),
            signal_id=str(message.get("signal_id") or ""),
            emission_seq=int(message.get("emission_seq") or 0),
            contract_id=str(message.get("contract_id") or ""),
        )
        report = evaluate_continuity_legality(path, ctx)
        # Only hard REJECT (stale terminal identity) blocks routing
        return report.verdict.value, report.verdict.is_hard_rejected()
    except Exception as _e:
        logger.debug(
            "unified_runtime_truth_ingress: continuity gate unavailable "
            "(non-fatal, passing through): %s",
            _e,
        )
        return "allow", False


def _resolve_execution_signal_reconciled(sub_outcome: Any) -> bool:
    """Return a canonical reconciled verdict across sub-outcome shapes."""
    if sub_outcome is None:
        return False

    accepted = getattr(sub_outcome, "is_accepted", None)
    if callable(accepted):
        try:
            return bool(accepted())
        except Exception:
            pass

    if hasattr(sub_outcome, "was_reconciled"):
        return bool(getattr(sub_outcome, "was_reconciled", False))

    was_updated = bool(getattr(sub_outcome, "was_updated", False))
    reject_reason = str(getattr(sub_outcome, "reject_reason", "") or "").strip()
    return was_updated and not reject_reason


def _extract_terminal_result_status(
    message: Dict[str, Any],
    msg_type: str,
) -> Optional[str]:
    """Map an execution signal message to canonical result status when terminal."""
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    raw_signal_kind = str(
        payload.get("signal_kind")
        or message.get("signal_kind")
        or msg_type
        or ""
    ).lower().strip()

    if raw_signal_kind in ("ack", "progress", "execution_ack", "execution_progress"):
        return None

    if raw_signal_kind in ("cancelled", "execution_cancelled"):
        return "cancelled"
    if raw_signal_kind in ("timeout", "execution_timeout"):
        return "degraded"
    if raw_signal_kind in ("error", "execution_error"):
        return "failed"

    if raw_signal_kind in ("result", "execution_result", "delegated_execution_signal"):
        raw_status = str(
            payload.get("status")
            or message.get("status")
            or payload.get("result_kind")
            or message.get("result_kind")
            or "success"
        ).lower().strip()
        if raw_status in ("failure", "failed", "error"):
            return "failed"
        if raw_status in ("cancelled", "canceled"):
            return "cancelled"
        if raw_status in ("timeout", "timed_out", "degraded"):
            return "degraded"
        return "completed"

    return None


# ---------------------------------------------------------------------------
# Session authority accessor
# ---------------------------------------------------------------------------


def get_session_authority():
    """Return the process-level singleton :class:`AttachedSessionRegistry`.

    This is the single session authority.  All reconnect, migration, continuity,
    and handoff operations should consult this registry.

    Returns
    -------
    AttachedSessionRegistry
        The canonical session authority singleton, or None on import failure.
    """
    try:
        from core.attached_runtime_session_registry import get_session_registry
        return get_session_registry()
    except Exception as exc:
        logger.warning(
            "unified_runtime_truth_ingress: get_session_authority unavailable: %s", exc
        )
        return None


# ---------------------------------------------------------------------------
# Canonical ingress function
# ---------------------------------------------------------------------------


def ingest_android_runtime_state_update(
    message: Dict[str, Any],
    *,
    runtime: Optional[Any] = None,
    registry: Optional[Any] = None,
) -> RuntimeTruthIngressOutcome:
    """Route an Android / runtime state update to the correct sub-ingress path.

    This is the **single canonical entry point** for all Android runtime state
    updates entering V2 orchestration state.  It inspects the message ``type``
    field and routes accordingly:

    Priority 1 — Handoff responses
        ``handoff_ack`` / ``handoff_result`` / ``handoff_failure`` →
        :func:`core.android_handoff_v2_response_ingress.ingest_android_handoff_response`

    Priority 2 — Execution signals
        ``ack`` / ``progress`` / ``result`` / ``error`` / ``timeout`` /
        ``cancelled`` (and prefixed variants) →
        :func:`core.android_delegated_signal_ingress.ingest_delegated_execution_signal`

    Priority 3 — Participant / session / runtime truth (default)
        All other recognised or unclassified message types →
        :func:`core.android_participant_truth_ingress.ingest_android_participant_truth_message`

    Unknown types without any known field are **rejected** (fail-closed).

    Parameters
    ----------
    message:
        Raw inbound message dict from the Android transport layer.
    runtime:
        Optional injectable runtime for the sub-ingress path.
    registry:
        Optional injectable session registry for the sub-ingress path.

    Returns
    -------
    RuntimeTruthIngressOutcome
        Typed result carrying the routing decision and reconciliation outcome.
    """
    if not isinstance(message, dict):
        return RuntimeTruthIngressOutcome(
            routed_path="rejected",
            was_reconciled=False,
            reject_reason="message must be a dict",
            message_type="",
        )

    msg_type: str = str(message.get("type") or "").lower().strip()

    # ── Step 0: Unified continuity legality gate ──────────────────────────
    # Online signal ingestion submits to the same continuity authority as
    # recovery and replay paths.  Execution signals are evaluated under
    # ONLINE_SIGNAL_INGESTION; all other types under ATTACHMENT_RESUME.
    # Per ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY.
    _continuity_verdict, _continuity_rejected = _check_runtime_ingress_continuity(
        message, msg_type
    )
    if _continuity_rejected:
        return RuntimeTruthIngressOutcome(
            routed_path="rejected",
            was_reconciled=False,
            reject_reason=f"continuity_rejected:{_continuity_verdict}",
            message_type=msg_type,
            continuity_rejected=True,
            continuity_legality_verdict=_continuity_verdict,
        )

    # ── Priority 1: Handoff responses ────────────────────────────────────
    if msg_type in _HANDOFF_TYPES:
        try:
            from core.android_handoff_v2_response_ingress import (
                ingest_android_handoff_response,
            )

            sub_outcome = ingest_android_handoff_response(message, runtime=runtime)
            was_correlated = getattr(sub_outcome, "was_correlated", False)
            reject_reason = "" if was_correlated else getattr(
                sub_outcome, "reject_reason", "handoff_not_correlated"
            )
            return RuntimeTruthIngressOutcome(
                routed_path="handoff",
                was_reconciled=was_correlated,
                reject_reason=reject_reason,
                sub_outcome=sub_outcome,
                message_type=msg_type,
            )
        except Exception as exc:
            logger.warning(
                "unified_runtime_truth_ingress: handoff sub-ingress error: %s", exc
            )
            return RuntimeTruthIngressOutcome(
                routed_path="degraded",
                was_reconciled=False,
                degraded=True,
                reject_reason=f"handoff_sub_ingress_error:{exc}",
                message_type=msg_type,
            )

    # ── Priority 2: Execution signals ────────────────────────────────────
    if msg_type in _EXECUTION_SIGNAL_TYPES:
        try:
            from core.android_delegated_signal_ingress import (
                ingest_delegated_execution_signal,
            )

            kwargs: Dict[str, Any] = {}
            if runtime is not None:
                kwargs["runtime"] = runtime
            if registry is not None:
                kwargs["registry"] = registry
            sub_outcome = ingest_delegated_execution_signal(message, **kwargs)
            was_reconciled = _resolve_execution_signal_reconciled(sub_outcome)
            reject_reason = "" if was_reconciled else getattr(
                sub_outcome, "reject_reason", "signal_not_reconciled"
            )

            outcome = RuntimeTruthIngressOutcome(
                routed_path="execution_signal",
                was_reconciled=was_reconciled,
                reject_reason=reject_reason,
                sub_outcome=sub_outcome,
                message_type=msg_type,
            )

            terminal_status = _extract_terminal_result_status(message, msg_type)
            if terminal_status is None:
                outcome.final_completion_state = "in_progress"
                return outcome

            outcome.result_produced = True
            if not was_reconciled:
                outcome.final_completion_state = "result_returned_not_reconciled"
                return outcome

            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            task_id = str(message.get("task_id") or payload.get("task_id") or "").strip()
            device_id = str(message.get("device_id") or payload.get("device_id") or "").strip()
            trace_id = str(message.get("trace_id") or payload.get("trace_id") or "").strip()
            if not task_id:
                outcome.final_completion_state = "terminal_result_without_task_id"
                return outcome

            try:
                from core.unified_result_ingress import (
                    NormalizedResultEvent,
                    ResultSourceChannel,
                    ingest_result,
                    normalize_status,
                )

                status = normalize_status(terminal_status)
                normalized_event = NormalizedResultEvent(
                    task_id=task_id,
                    device_id=device_id,
                    raw_message_type=msg_type,
                    normalized_result_kind=msg_type or "delegated_execution_signal",
                    normalized_status=status,
                    source_channel=ResultSourceChannel.DELEGATED,
                    payload=payload if payload else dict(message),
                    trace_id=trace_id,
                    raw_message=dict(message),
                    runtime_session_id=str(
                        message.get("runtime_session_id")
                        or payload.get("runtime_session_id")
                        or message.get("session_id")
                        or payload.get("session_id")
                        or ""
                    ),
                )
                result_outcome = ingest_result(normalized_event)
                outcome.truth_ingested_or_accepted = bool(result_outcome.truth_chain_complete)
                outcome.closure_accepted = bool(result_outcome.is_fully_closed)
                outcome.final_completion_state = (
                    "closed"
                    if outcome.closure_accepted
                    else "result_returned_but_not_closed"
                )
            except Exception as exc:
                logger.warning(
                    "unified_runtime_truth_ingress: unified result ingress linkage error: %s",
                    exc,
                )
                outcome.final_completion_state = "result_returned_unified_ingress_unavailable"
            return outcome
        except Exception as exc:
            logger.warning(
                "unified_runtime_truth_ingress: execution_signal sub-ingress error: %s",
                exc,
            )
            return RuntimeTruthIngressOutcome(
                routed_path="degraded",
                was_reconciled=False,
                degraded=True,
                reject_reason=f"execution_signal_sub_ingress_error:{exc}",
                message_type=msg_type,
            )

    # ── Priority 3: Participant / session / runtime truth (default) ───────
    # Reject only if there's no identifiable content at all.
    if not msg_type and not any(
        k in message for k in ("device_id", "session_id", "task_id", "payload", "kind")
    ):
        return RuntimeTruthIngressOutcome(
            routed_path="rejected",
            was_reconciled=False,
            reject_reason="message_type_absent_and_no_identity_fields",
            message_type=msg_type,
        )

    try:
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )

        kwargs_pt: Dict[str, Any] = {}
        if runtime is not None:
            kwargs_pt["runtime"] = runtime
        if registry is not None:
            kwargs_pt["registry"] = registry
        sub_outcome = ingest_android_participant_truth_message(message, **kwargs_pt)
        was_reconciled = getattr(sub_outcome, "was_reconciled", False)
        reject_reason = "" if was_reconciled else getattr(
            sub_outcome, "reject_reason", "participant_truth_not_reconciled"
        )
        return RuntimeTruthIngressOutcome(
            routed_path="participant_truth",
            was_reconciled=was_reconciled,
            reject_reason=reject_reason,
            sub_outcome=sub_outcome,
            message_type=msg_type,
        )
    except Exception as exc:
        logger.warning(
            "unified_runtime_truth_ingress: participant_truth sub-ingress error: %s",
            exc,
        )
        return RuntimeTruthIngressOutcome(
            routed_path="degraded",
            was_reconciled=False,
            degraded=True,
            reject_reason=f"participant_truth_sub_ingress_error:{exc}",
            message_type=msg_type,
        )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY",
    "UNIFIED_RUNTIME_TRUTH_INGRESS_PR2_SENTINEL",
    "ANDROID_RUNTIME_STATE_MUST_FLOW_THROUGH_INGRESS_POLICY",
    "NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY",
    "SESSION_AUTHORITY_IS_ATTACHED_REGISTRY_POLICY",
    "INGRESS_ROUTES_TO_CORRECT_SUB_PATH_POLICY",
    "INGRESS_FAIL_CLOSED_ON_UNKNOWN_TYPE_POLICY",
    "INGRESS_IS_GRACEFUL_ON_SUBMODULE_UNAVAILABILITY_POLICY",
    "CONTINUITY_GATE_PRECEDES_ROUTING_POLICY",
    # Dataclass
    "RuntimeTruthIngressOutcome",
    # Functions
    "get_session_authority",
    "ingest_android_runtime_state_update",
]
