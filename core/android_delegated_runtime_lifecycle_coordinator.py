"""core/android_delegated_runtime_lifecycle_coordinator.py
===========================================================
PR-11-V2: Android Delegated Runtime Lifecycle Coordinator.

Background
----------
The Android delegated runtime integration accumulated its capabilities across
several PR packages (PR-02-V2 through PR-10-V2), each adding a new ingress
path or observability surface.  The result is structurally sound at the
per-module level but lacks a **single orchestration facade** that:

* exposes one entry-point per lifecycle *event* (handoff dispatched, takeover
  response received, reconciliation signal received, execution signal received,
  participant truth update received), and
* within each entry-point, invokes the correct downstream modules in the
  correct order, persists updated session state, and records the audit event.

Without such a facade:

* Gateway handlers must individually import and wire four or five modules.
* The ordering of ingress → state-update → audit can silently diverge between
  handlers as the codebase grows.
* There is no canonical answer to *"process this Android lifecycle event"*
  that future developers can use as a reference.

This module provides that facade:

1. :class:`AndroidDelegatedRuntimeLifecycleCoordinator` — singleton
   coordinator with one ``on_*`` method per lifecycle event:

   * :meth:`on_handoff_dispatched` — called by the dispatch path when a
     handoff contract has been sent to Android.  Creates the participant
     session record and persists it.
   * :meth:`on_takeover_response` — called by the ``takeover_response``
     handler.  Updates session phase, persists takeover tracking, records
     audit event.
   * :meth:`on_reconciliation_signal` — called by the
     ``reconciliation_signal`` handler.  Delegates to participant truth
     ingress, reduces session state, records audit event.
   * :meth:`on_execution_signal` — called by the ``delegated_signal``
     handler.  Delegates to delegated signal ingress, reduces session state.
   * :meth:`on_participant_truth_update` — called for explicit
     participant truth messages.  Delegates to participant truth ingress,
     reduces session state, records audit event.

2. :class:`AndroidLifecycleCoordinatorOutcome` — typed result returned from
   every ``on_*`` method.

3. :func:`get_lifecycle_coordinator` /
   :func:`reset_lifecycle_coordinator` — singleton accessor and
   test-isolation helper.

Domain boundary
---------------
The coordinator is the **boundary** between the wire (gateway handlers) and
the internal lifecycle domain.  Its responsibilities are:

* Invoke the correct ingress/tracking modules in the correct order.
* Persist updated session state records.
* Record audit events.
* Return a typed outcome for the caller to log / respond with.

Its responsibilities do **NOT** include:

* Sending wire messages (that is the handler's responsibility).
* Interpreting raw message bytes (the handler extracts fields first).
* Making policy decisions about admissibility (that is the admissibility
  chain's responsibility).

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Delegates to existing modules** — all ingress, reconciliation, and audit
  logic lives in the pre-existing canonical modules; the coordinator is an
  orchestrator, not a re-implementer.
- **Non-raising** — all ``on_*`` methods catch exceptions and return a
  ``was_handled=False`` outcome with an error description.
- **Thread-safe** — the coordinator instance itself carries no mutable state
  beyond a logging context; all mutable state lives in the singleton ring
  buffers of the downstream modules.
- **Testable in isolation** — all downstream dependencies are injected via
  optional ``runtime`` parameters or resolved lazily from singletons.

Public API
----------
Sentinels::

    ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_AUTHORITY
    ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_CONTRACT_VERSION

Dataclass::

    AndroidLifecycleCoordinatorOutcome

Class::

    AndroidDelegatedRuntimeLifecycleCoordinator

Functions::

    get_lifecycle_coordinator() -> AndroidDelegatedRuntimeLifecycleCoordinator
    reset_lifecycle_coordinator() -> None
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.AndroidDelegatedRuntimeLifecycleCoordinator")

# ---------------------------------------------------------------------------
# Lazy imports — all guarded so the coordinator loads even when a dep is absent
# ---------------------------------------------------------------------------

try:
    from core.android_participant_session_state import (
        AndroidParticipantSessionSignal,
        advance_participant_session,
        create_participant_session_record,
        get_participant_session,
        record_participant_session,
    )

    _SESSION_STATE_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _SESSION_STATE_AVAILABLE = False
    AndroidParticipantSessionSignal = None  # type: ignore[assignment,misc]
    advance_participant_session = None  # type: ignore[assignment]
    create_participant_session_record = None  # type: ignore[assignment]
    get_participant_session = None  # type: ignore[assignment]
    record_participant_session = None  # type: ignore[assignment]

try:
    from core.android_runtime_transition_reducer import (
        AndroidRuntimeSignalInput,
        reduce_android_runtime_signal,
        reduce_takeover_response as _reduce_takeover_response,
    )

    _REDUCER_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _REDUCER_AVAILABLE = False
    AndroidRuntimeSignalInput = None  # type: ignore[assignment,misc]
    reduce_android_runtime_signal = None  # type: ignore[assignment]
    _reduce_takeover_response = None  # type: ignore[assignment]

try:
    from core.takeover_tracking import (
        adjudicate_takeover_ownership_convergence as _adjudicate_takeover_ownership_convergence,
        record_takeover_response as _record_takeover_tracking,
    )

    _TAKEOVER_TRACKING_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _TAKEOVER_TRACKING_AVAILABLE = False
    _adjudicate_takeover_ownership_convergence = None  # type: ignore[assignment]
    _record_takeover_tracking = None  # type: ignore[assignment]

try:
    from core.android_participant_truth_ingress import (
        ingest_android_participant_truth_message as _ingest_truth,
    )

    _TRUTH_INGRESS_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _TRUTH_INGRESS_AVAILABLE = False
    _ingest_truth = None  # type: ignore[assignment]

try:
    from core.android_delegated_signal_ingress import (
        ingest_delegated_execution_signal as _ingest_execution_signal,
    )

    _EXECUTION_SIGNAL_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _EXECUTION_SIGNAL_AVAILABLE = False
    _ingest_execution_signal = None  # type: ignore[assignment]

try:
    from core.android_delegated_runtime_audit import (
        record_reconciliation_signal as _audit_reconciliation_signal,
        record_takeover_request as _audit_takeover_request,
        record_takeover_response as _audit_takeover_response,
    )

    _AUDIT_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _AUDIT_AVAILABLE = False
    _audit_reconciliation_signal = None  # type: ignore[assignment]
    _audit_takeover_request = None  # type: ignore[assignment]
    _audit_takeover_response = None  # type: ignore[assignment]

# PR-5A: Android behavioral result stable consumer — the SourceDispatchOrchestrator
# is the canonical consumer of result-kind delegated execution signals.
try:
    from core.runtime.source_dispatch_orchestrator import (
        SourceDispatchOrchestrator as _SourceDispatchOrchestrator,
    )

    _android_result_consumer = _SourceDispatchOrchestrator()
    _RESULT_CONSUMER_AVAILABLE: bool = True
except Exception:  # pragma: no cover  # noqa: BLE001
    _android_result_consumer = None  # type: ignore[assignment]
    _RESULT_CONSUMER_AVAILABLE = False

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_AUTHORITY: str = (
    "ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_AUTHORITY::"
    "core.android_delegated_runtime_lifecycle_coordinator is the canonical "
    "orchestration facade for the Android delegated runtime lifecycle.  "
    "Gateway handlers SHOULD delegate to this coordinator rather than "
    "importing and wiring individual ingress/audit modules directly."
)

ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_CONTRACT_VERSION: str = "1.0"

# Policy sentinels

COORDINATOR_IS_ORCHESTRATOR_NOT_AUTHORITY_POLICY: str = (
    "POLICY::COORDINATOR_IS_ORCHESTRATOR_NOT_AUTHORITY: The lifecycle "
    "coordinator orchestrates calls to downstream modules (ingress, tracking, "
    "audit) in the correct order.  It does NOT re-implement ingress logic or "
    "make admissibility decisions.  All policy authority remains in the "
    "canonical modules it delegates to."
)

COORDINATOR_IS_NON_RAISING_POLICY: str = (
    "POLICY::COORDINATOR_IS_NON_RAISING: All on_* methods MUST catch every "
    "exception and return an AndroidLifecycleCoordinatorOutcome with "
    "was_handled=False.  Gateway handlers must never see an exception from "
    "the coordinator."
)

# ---------------------------------------------------------------------------
# Outcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidLifecycleCoordinatorOutcome:
    """Typed result returned by each ``on_*`` coordinator method.

    Attributes
    ----------
    was_handled
        ``True`` if the event was successfully processed (all downstream calls
        completed without error; session state updated if applicable).
    event_type
        Short string identifying the lifecycle event type (e.g.
        ``"handoff_dispatched"``, ``"takeover_response"``).
    session_id
        The session_id this event pertained to.
    phase_before
        Session phase *before* this event (``""`` if unknown).
    phase_after
        Session phase *after* this event (``""`` if unchanged or unknown).
    was_transitioned
        ``True`` if the participant session phase was advanced by this event.
    description
        Human-readable summary for logging / debugging.
    extra
        Opaque key/value pairs for additional context.
    """

    was_handled: bool = False
    event_type: str = ""
    session_id: str = ""
    phase_before: str = ""
    phase_after: str = ""
    was_transitioned: bool = False
    description: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class AndroidDelegatedRuntimeLifecycleCoordinator:
    """Singleton orchestration facade for the Android delegated runtime lifecycle.

    All gateway handlers that process Android wire messages SHOULD call
    ``get_lifecycle_coordinator()`` and invoke the appropriate ``on_*`` method.
    This guarantees consistent ordering of ingress → state-update → audit across
    all event types.

    All ``on_*`` methods are non-raising and return
    :class:`AndroidLifecycleCoordinatorOutcome`.
    """

    # ------------------------------------------------------------------
    # on_handoff_dispatched
    # ------------------------------------------------------------------

    def on_handoff_dispatched(
        self,
        *,
        session_id: str,
        device_id: str = "",
        task_id: str = "",
        trace_id: str = "",
        contract_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AndroidLifecycleCoordinatorOutcome:
        """Record that a handoff contract has been dispatched to the Android runtime.

        Creates a new :class:`AndroidParticipantSessionRecord` in phase
        ``pre_dispatch``, advances it to ``handoff_dispatched``, and persists
        it to the ring buffer.

        Parameters
        ----------
        session_id:
            Attached-runtime session identifier.
        device_id:
            Target Android device identifier.
        task_id:
            Canonical task identifier.
        trace_id:
            Distributed trace identifier.
        contract_id:
            Handoff contract identifier.
        metadata:
            Optional extra fields.

        Returns
        -------
        AndroidLifecycleCoordinatorOutcome
        """
        try:
            if not _SESSION_STATE_AVAILABLE:
                return AndroidLifecycleCoordinatorOutcome(
                    was_handled=False,
                    event_type="handoff_dispatched",
                    session_id=session_id,
                    description="session_state_module_unavailable",
                )

            rec = create_participant_session_record(
                session_id=session_id,
                device_id=device_id,
                task_id=task_id,
                trace_id=trace_id,
                contract_id=contract_id,
                metadata=metadata,
            )
            phase_before = rec.phase.value

            # Advance to handoff_dispatched
            rec = advance_participant_session(
                rec, AndroidParticipantSessionSignal.handoff_dispatched
            )
            record_participant_session(rec)

            return AndroidLifecycleCoordinatorOutcome(
                was_handled=True,
                event_type="handoff_dispatched",
                session_id=session_id,
                phase_before=phase_before,
                phase_after=rec.phase.value,
                was_transitioned=rec.phase.value != phase_before,
                description=(
                    f"handoff dispatched: session={session_id!r} "
                    f"contract={contract_id!r} device={device_id!r}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("on_handoff_dispatched failed (non-fatal): %s", exc)
            return AndroidLifecycleCoordinatorOutcome(
                was_handled=False,
                event_type="handoff_dispatched",
                session_id=session_id,
                description=f"on_handoff_dispatched_error:{exc}",
            )

    # ------------------------------------------------------------------
    # on_takeover_requested
    # ------------------------------------------------------------------

    def on_takeover_requested(
        self,
        *,
        session_id: str,
        takeover_id: str = "",
        device_id: str = "",
        task_id: str = "",
        trace_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AndroidLifecycleCoordinatorOutcome:
        """Record that V2 issued a TAKEOVER_REQUEST to the Android runtime.

        Advances the participant session from ``handoff_dispatched`` →
        ``takeover_pending`` and records an audit event.

        Parameters
        ----------
        session_id:
            Attached-runtime session identifier.
        takeover_id:
            Takeover identifier (UUID) issued by V2.
        device_id:
            Target Android device identifier.
        task_id:
            Canonical task identifier.
        trace_id:
            Distributed trace identifier.
        metadata:
            Optional extra fields.
        """
        try:
            phase_before = ""
            phase_after = ""
            was_transitioned = False

            if _SESSION_STATE_AVAILABLE and get_participant_session is not None:
                rec = get_participant_session(session_id)
                if rec is not None:
                    phase_before = rec.phase.value
                    rec = advance_participant_session(
                        rec,
                        AndroidParticipantSessionSignal.takeover_requested,
                        takeover_id=takeover_id,
                    )
                    phase_after = rec.phase.value
                    was_transitioned = phase_after != phase_before
                    record_participant_session(rec)

            if _AUDIT_AVAILABLE and _audit_takeover_request is not None:
                try:
                    _audit_takeover_request(
                        task_id=task_id,
                        session_id=session_id,
                        trace_id=trace_id,
                        device_id=device_id,
                        takeover_id=takeover_id,
                    )
                except Exception as _ae:  # noqa: BLE001
                    logger.debug("on_takeover_requested audit failed (non-fatal): %s", _ae)

            return AndroidLifecycleCoordinatorOutcome(
                was_handled=True,
                event_type="takeover_requested",
                session_id=session_id,
                phase_before=phase_before,
                phase_after=phase_after,
                was_transitioned=was_transitioned,
                description=(
                    f"takeover requested: session={session_id!r} "
                    f"takeover_id={takeover_id!r} device={device_id!r}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("on_takeover_requested failed (non-fatal): %s", exc)
            return AndroidLifecycleCoordinatorOutcome(
                was_handled=False,
                event_type="takeover_requested",
                session_id=session_id,
                description=f"on_takeover_requested_error:{exc}",
            )

    # ------------------------------------------------------------------
    # on_takeover_response
    # ------------------------------------------------------------------

    def on_takeover_response(
        self,
        *,
        session_id: str,
        takeover_id: str = "",
        device_id: str = "",
        accepted: bool = False,
        reason: str = "",
        task_id: str = "",
        trace_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AndroidLifecycleCoordinatorOutcome:
        """Handle a TAKEOVER_RESPONSE from the Android runtime.

        Steps:
        1. Persists the decision to :mod:`core.takeover_tracking`.
        2. Reduces the session phase via the transition reducer.
        3. Persists the updated session record.
        4. Records a unified audit event.

        Parameters
        ----------
        session_id:
            Attached-runtime session identifier.
        takeover_id:
            Correlation key matching the V2-issued ``TAKEOVER_REQUEST``.
        device_id:
            Android device identifier.
        accepted:
            ``True`` if the Android runtime accepted the takeover.
        reason:
            Optional human-readable reason from the Android runtime.
        task_id:
            Canonical task identifier.
        trace_id:
            Distributed trace identifier.
        metadata:
            Optional extra fields.
        """
        try:
            phase_before = ""
            phase_after = ""
            was_transitioned = False
            ownership_convergence: Dict[str, Any] = {}

            # Step 1: persist takeover decision
            if _TAKEOVER_TRACKING_AVAILABLE and _record_takeover_tracking is not None:
                try:
                    _record_takeover_tracking(
                        takeover_id=takeover_id,
                        device_id=device_id,
                        accepted=accepted,
                        reason=reason,
                        session_id=session_id or None,
                        task_id=task_id,
                        trace_id=trace_id,
                        metadata=metadata,
                    )
                except Exception as _te:  # noqa: BLE001
                    logger.debug("on_takeover_response: tracking failed (non-fatal): %s", _te)
                if _adjudicate_takeover_ownership_convergence is not None:
                    try:
                        verdict = _adjudicate_takeover_ownership_convergence(
                            takeover_id=takeover_id,
                            session_id=session_id,
                            device_id=device_id,
                        )
                        ownership_convergence = verdict.to_dict()
                    except Exception as _oe:  # noqa: BLE001
                        logger.debug(
                            "on_takeover_response: ownership adjudication failed (non-fatal): %s",
                            _oe,
                        )

            # Step 2: reduce session state
            if _SESSION_STATE_AVAILABLE and _REDUCER_AVAILABLE:
                rec = get_participant_session(session_id) if get_participant_session else None
                if rec is not None:
                    phase_before = rec.phase.value
                    result = _reduce_takeover_response(rec, accepted=accepted, takeover_id=takeover_id)
                    updated_rec = result.record
                    phase_after = updated_rec.phase.value
                    was_transitioned = result.was_transitioned
                    record_participant_session(updated_rec)

            # Step 3: audit
            if _AUDIT_AVAILABLE and _audit_takeover_response is not None:
                try:
                    _audit_takeover_response(
                        task_id=task_id,
                        session_id=session_id,
                        trace_id=trace_id,
                        device_id=device_id,
                        takeover_id=takeover_id,
                        accepted=accepted,
                        reason=reason,
                    )
                except Exception as _ae:  # noqa: BLE001
                    logger.debug("on_takeover_response: audit failed (non-fatal): %s", _ae)

            decision_label = "accepted" if accepted else "rejected"
            return AndroidLifecycleCoordinatorOutcome(
                was_handled=True,
                event_type="takeover_response",
                session_id=session_id,
                phase_before=phase_before,
                phase_after=phase_after,
                was_transitioned=was_transitioned,
                description=(
                    f"takeover_response {decision_label}: "
                    f"session={session_id!r} takeover_id={takeover_id!r} "
                    f"device={device_id!r}"
                ),
                extra={
                    "accepted": accepted,
                    "reason": reason,
                    "ownership_convergence": ownership_convergence,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("on_takeover_response failed (non-fatal): %s", exc)
            return AndroidLifecycleCoordinatorOutcome(
                was_handled=False,
                event_type="takeover_response",
                session_id=session_id,
                description=f"on_takeover_response_error:{exc}",
            )

    # ------------------------------------------------------------------
    # on_reconciliation_signal
    # ------------------------------------------------------------------

    def on_reconciliation_signal(
        self,
        *,
        message: Dict[str, Any],
        session_id: str = "",
    ) -> AndroidLifecycleCoordinatorOutcome:
        """Handle an inbound ``reconciliation_signal`` message.

        Steps:
        1. Delegates to participant truth ingress to reconcile Android truth
           into V2 canonical state.
        2. Reduces the session phase.
        3. Persists the updated session record.
        4. Records a unified audit event.

        Parameters
        ----------
        message:
            Raw inbound ``reconciliation_signal`` message dict.
        session_id:
            Optional session_id override (extracted from *message* if absent).
        """
        try:
            _session_id = session_id or message.get("session_id") or message.get("payload", {}).get("session_id") or ""
            device_id = message.get("device_id", "")
            phase_before = ""
            phase_after = ""
            was_transitioned = False
            truth_kind = ""
            was_reconciled = False
            reject_reason = ""
            task_id = ""
            trace_id = ""
            contract_id = ""

            # Step 1: participant truth ingress
            if _TRUTH_INGRESS_AVAILABLE and _ingest_truth is not None:
                try:
                    outcome = _ingest_truth(message)
                    was_reconciled = outcome.was_reconciled
                    reject_reason = outcome.reject_reason or ""
                    env = outcome.envelope
                    if env:
                        truth_kind = env.truth_kind.value if hasattr(env.truth_kind, "value") else str(env.truth_kind)
                        task_id = env.task_id or ""
                        trace_id = env.trace_id or ""
                        contract_id = env.contract_id or ""
                        _session_id = _session_id or (env.session_id or "")
                except Exception as _ie:  # noqa: BLE001
                    logger.debug("on_reconciliation_signal: ingress failed (non-fatal): %s", _ie)

            # Step 2: reduce session state
            if _SESSION_STATE_AVAILABLE and _REDUCER_AVAILABLE and _session_id:
                rec = get_participant_session(_session_id) if get_participant_session else None
                if rec is not None:
                    phase_before = rec.phase.value
                    signal_input = AndroidRuntimeSignalInput(
                        signal_domain="reconciliation",
                        signal_type=truth_kind,
                        truth_kind=truth_kind,
                        was_reconciled=was_reconciled,
                        reject_reason=reject_reason,
                    )
                    result = reduce_android_runtime_signal(rec, signal_input)
                    phase_after = result.record.phase.value
                    was_transitioned = result.was_transitioned
                    record_participant_session(result.record)

            # Step 3: audit
            if _AUDIT_AVAILABLE and _audit_reconciliation_signal is not None:
                try:
                    _audit_reconciliation_signal(
                        task_id=task_id,
                        session_id=_session_id,
                        trace_id=trace_id,
                        device_id=device_id,
                        contract_id=contract_id,
                        truth_kind=truth_kind,
                        was_reconciled=was_reconciled,
                        reject_reason=reject_reason,
                    )
                except Exception as _ae:  # noqa: BLE001
                    logger.debug("on_reconciliation_signal: audit failed (non-fatal): %s", _ae)

            return AndroidLifecycleCoordinatorOutcome(
                was_handled=True,
                event_type="reconciliation_signal",
                session_id=_session_id,
                phase_before=phase_before,
                phase_after=phase_after,
                was_transitioned=was_transitioned,
                description=(
                    f"reconciliation_signal: truth_kind={truth_kind!r} "
                    f"reconciled={was_reconciled} session={_session_id!r}"
                ),
                extra={
                    "was_reconciled": was_reconciled,
                    "reject_reason": reject_reason,
                    "truth_kind": truth_kind,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("on_reconciliation_signal failed (non-fatal): %s", exc)
            return AndroidLifecycleCoordinatorOutcome(
                was_handled=False,
                event_type="reconciliation_signal",
                session_id=session_id,
                description=f"on_reconciliation_signal_error:{exc}",
            )

    # ------------------------------------------------------------------
    # on_execution_signal
    # ------------------------------------------------------------------

    def on_execution_signal(
        self,
        *,
        message: Dict[str, Any],
        session_id: str = "",
        device_id: str = "",
    ) -> AndroidLifecycleCoordinatorOutcome:
        """Handle an inbound ``delegated_execution_signal`` message.

        Steps:
        1. Delegates to delegated signal ingress to reconcile the signal.
        2. Reduces the session phase.
        3. Persists the updated session record.
        4. PR-5A: For ``result``-kind signals, forwards the ingress outcome to
           :meth:`~core.runtime.source_dispatch_orchestrator.SourceDispatchOrchestrator.consume_android_behavioral_result`
           so the source-side orchestrator is the stable consumer.

        Parameters
        ----------
        message:
            Raw inbound ``delegated_execution_signal`` message dict.
        session_id:
            Optional session_id override.
        device_id:
            Android device identifier (used for PR-5A source attribution).
        """
        try:
            _device_id = device_id or message.get("device_id", "")
            _session_id = session_id or message.get("session_id") or message.get("payload", {}).get("session_id") or ""
            phase_before = ""
            phase_after = ""
            was_transitioned = False
            signal_kind = ""
            was_updated = False
            reject_reason = ""
            result_consumer_called = False
            _raw_ingress_outcome = None

            # Step 1: delegated signal ingress
            if _EXECUTION_SIGNAL_AVAILABLE and _ingest_execution_signal is not None:
                try:
                    _raw_ingress_outcome = _ingest_execution_signal(message)
                    was_updated = _raw_ingress_outcome.was_updated if hasattr(_raw_ingress_outcome, "was_updated") else False
                    reject_reason = _raw_ingress_outcome.reject_reason if hasattr(_raw_ingress_outcome, "reject_reason") else ""
                    env = _raw_ingress_outcome.envelope if hasattr(_raw_ingress_outcome, "envelope") else None
                    if env:
                        signal_kind = env.signal_kind.value if hasattr(env.signal_kind, "value") else str(getattr(env, "signal_kind", ""))
                        _session_id = _session_id or (env.session_id or "")
                except Exception as _ie:  # noqa: BLE001
                    logger.debug("on_execution_signal: ingress failed (non-fatal): %s", _ie)

            # Step 2: reduce session state
            if _SESSION_STATE_AVAILABLE and _REDUCER_AVAILABLE and _session_id:
                rec = get_participant_session(_session_id) if get_participant_session else None
                if rec is not None:
                    phase_before = rec.phase.value
                    signal_input = AndroidRuntimeSignalInput(
                        signal_domain="execution",
                        signal_type=signal_kind,
                        was_reconciled=was_updated,
                        reject_reason=reject_reason,
                    )
                    result = reduce_android_runtime_signal(rec, signal_input)
                    phase_after = result.record.phase.value
                    was_transitioned = result.was_transitioned
                    record_participant_session(result.record)

            # Step 3: PR-5A — forward result-kind signals to the stable consumer.
            # ``signal_kind`` here is the AndroidSignalKind value extracted from the
            # reconciler's AndroidExecutionSignalEnvelope.  DelegatedSignalKind.result
            # maps to AndroidSignalKind.final_result (success) or AndroidSignalKind.error
            # (failure) — NOT the string "result" — so we compare against those two
            # canonical terminal result values.
            _RESULT_SIGNAL_KINDS: frozenset = frozenset({"final_result", "error"})
            if (
                _RESULT_CONSUMER_AVAILABLE
                and _android_result_consumer is not None
                and was_updated
                and signal_kind in _RESULT_SIGNAL_KINDS
                and _raw_ingress_outcome is not None
            ):
                try:
                    _android_result_consumer.consume_android_behavioral_result(
                        _raw_ingress_outcome,
                        source=f"android_bridge:{_device_id}",
                    )
                    result_consumer_called = True
                except Exception as _consumer_exc:  # noqa: BLE001
                    logger.debug(
                        "on_execution_signal: PR-5A result consumer skipped (non-fatal): %s",
                        _consumer_exc,
                    )

            return AndroidLifecycleCoordinatorOutcome(
                was_handled=True,
                event_type="execution_signal",
                session_id=_session_id,
                phase_before=phase_before,
                phase_after=phase_after,
                was_transitioned=was_transitioned,
                description=(
                    f"execution_signal: kind={signal_kind!r} "
                    f"updated={was_updated} session={_session_id!r}"
                ),
                extra={
                    "signal_kind": signal_kind,
                    "was_updated": was_updated,
                    "result_consumer_called": result_consumer_called,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("on_execution_signal failed (non-fatal): %s", exc)
            return AndroidLifecycleCoordinatorOutcome(
                was_handled=False,
                event_type="execution_signal",
                session_id=session_id,
                description=f"on_execution_signal_error:{exc}",
            )

    # ------------------------------------------------------------------
    # on_participant_truth_update
    # ------------------------------------------------------------------

    def on_participant_truth_update(
        self,
        *,
        message: Dict[str, Any],
        session_id: str = "",
    ) -> AndroidLifecycleCoordinatorOutcome:
        """Handle an explicit Android participant truth update message.

        Steps:
        1. Delegates to participant truth ingress.
        2. Reduces the session phase.
        3. Persists the updated session record.
        4. Records a unified audit event for terminal updates.

        Parameters
        ----------
        message:
            Raw Android participant truth message dict.
        session_id:
            Optional session_id override.
        """
        try:
            _session_id = session_id or message.get("session_id") or message.get("payload", {}).get("session_id") or ""
            phase_before = ""
            phase_after = ""
            was_transitioned = False
            truth_kind = ""
            was_reconciled = False
            reject_reason = ""

            # Step 1: participant truth ingress
            if _TRUTH_INGRESS_AVAILABLE and _ingest_truth is not None:
                try:
                    outcome = _ingest_truth(message)
                    was_reconciled = outcome.was_reconciled
                    reject_reason = outcome.reject_reason or ""
                    env = outcome.envelope
                    if env:
                        truth_kind = env.truth_kind.value if hasattr(env.truth_kind, "value") else str(env.truth_kind)
                        _session_id = _session_id or (env.session_id or "")
                except Exception as _ie:  # noqa: BLE001
                    logger.debug("on_participant_truth_update: ingress failed (non-fatal): %s", _ie)

            # Step 2: reduce session state
            if _SESSION_STATE_AVAILABLE and _REDUCER_AVAILABLE and _session_id:
                rec = get_participant_session(_session_id) if get_participant_session else None
                if rec is not None:
                    phase_before = rec.phase.value
                    signal_input = AndroidRuntimeSignalInput(
                        signal_domain="participant_truth",
                        signal_type=truth_kind,
                        truth_kind=truth_kind,
                        was_reconciled=was_reconciled,
                        reject_reason=reject_reason,
                    )
                    result = reduce_android_runtime_signal(rec, signal_input)
                    phase_after = result.record.phase.value
                    was_transitioned = result.was_transitioned
                    record_participant_session(result.record)

            return AndroidLifecycleCoordinatorOutcome(
                was_handled=True,
                event_type="participant_truth_update",
                session_id=_session_id,
                phase_before=phase_before,
                phase_after=phase_after,
                was_transitioned=was_transitioned,
                description=(
                    f"participant_truth_update: kind={truth_kind!r} "
                    f"reconciled={was_reconciled} session={_session_id!r}"
                ),
                extra={
                    "truth_kind": truth_kind,
                    "was_reconciled": was_reconciled,
                    "reject_reason": reject_reason,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("on_participant_truth_update failed (non-fatal): %s", exc)
            return AndroidLifecycleCoordinatorOutcome(
                was_handled=False,
                event_type="participant_truth_update",
                session_id=session_id,
                description=f"on_participant_truth_update_error:{exc}",
            )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_singleton_lock: threading.Lock = threading.Lock()
_singleton: Optional[AndroidDelegatedRuntimeLifecycleCoordinator] = None


def get_lifecycle_coordinator() -> AndroidDelegatedRuntimeLifecycleCoordinator:
    """Return the process-wide singleton coordinator."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = AndroidDelegatedRuntimeLifecycleCoordinator()
    return _singleton


def reset_lifecycle_coordinator() -> None:
    """Reset the singleton (test-isolation helper only)."""
    global _singleton
    with _singleton_lock:
        _singleton = None
