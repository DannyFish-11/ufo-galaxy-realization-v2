"""core/mesh/android_mesh_participant_signal_adapter.py
=======================================================
Android Mesh Participant Signal Adapter — PR-2 (dual-repo runtime integration).

This module wires the center-side mesh runtime closure path to consume real
Android participant signals, replacing the V2-only closure semantics that
previously made ``runtime_closed`` reachable only through internal batch tests.

Problem addressed
-----------------
Prior to this module, ``evaluate_center_runtime_status()`` and
:class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`
derived all coordinator state from V2-internal operations (batch
:class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRuntimeEngine` runs or
manual calls to ``on_participant_result``).  There was no path for real
Android-originated signals — readiness confirmations, barrier arrival
notifications, or task completion uplinks — to drive the center-side
``runtime_closed`` status through live coordination.

This module:

1. Defines :class:`AndroidMeshParticipantSignalKind` — enum for the
   categorisation of Android-originated mesh participation signals.

2. Defines :class:`AndroidMeshParticipantSignal` — typed, immutable carrier
   for a single Android-originated mesh participation signal with identity
   fields (``device_id``, ``session_id``) and optional result/failure payloads.

3. Defines :class:`AndroidMeshParticipationRecord` — aggregate per-device
   record of all Android-originated signals for a single mesh session.  Tracks
   readiness, barrier arrival, and completion state.

4. Provides :func:`apply_android_participation_signal` — applies a single
   :class:`AndroidMeshParticipantSignal` to a live
   :class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`,
   driving real coordinator state transitions (pending→ready→working→completed)
   from Android truth.

5. Provides :func:`evaluate_center_runtime_status_with_android_signals` —
   evaluates the center-side runtime status by first applying all provided
   Android participant signals to a live coordinator, then calling
   :func:`~core.mesh.mesh_runtime_center_state.evaluate_center_runtime_status`
   on the resulting coordinator state.  This is the primary path through which
   ``runtime_closed`` becomes reachable from real Android participation.

6. Provides :func:`build_android_participation_record` — constructs an
   :class:`AndroidMeshParticipationRecord` from a list of signals for a given
   device/session, exposing the aggregated Android participation truth for
   operator observability.

7. Provides :func:`classify_android_proof_quality` — classifies the proof
   quality of an Android participant's contribution to a mesh session as one
   of ``live``, ``partial``, or ``missing``, based on the signals received.

8. Four policy sentinels and one PR sentinel documenting the authority
   boundary and signal routing rules.

Authority boundary
------------------
Android-originated mesh participation signals enter V2 through this adapter
as the canonical routing path.  The adapter respects the V2-is-canonical
authority established in :mod:`core.android_participant_truth_ingress`:

* ``readiness_confirmed`` signals drive :meth:`on_participant_ready` on the
  live coordinator.
* ``barrier_reached`` signals drive :meth:`on_participant_working` (entering
  active execution phase, approaching barrier) on the live coordinator.
* ``task_completed`` signals drive :meth:`on_participant_result` on the live
  coordinator, triggering barrier evaluation and potential ``runtime_closed``.
* ``task_failed`` signals drive :meth:`on_participant_failed` on the live
  coordinator.
* ``participant_dropped`` signals drive :meth:`on_participant_dropped` on the
  live coordinator.

Design
------
- **Additive only** — does not modify any prior module.
- **Grounded in real runtime** — transitions are driven by real Android signals
  forwarded through the live coordinator, not by internal batch simulation.
- **Non-raising** — all public functions return valid objects without raising.
- **Composable** — works alongside the existing batch
  :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRuntimeEngine` path; the
  two paths are not mutually exclusive.

Sentinels
---------
:data:`ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL`
    Asserts this module is the Android mesh participant signal adapter (PR-2).
:data:`ANDROID_SIGNALS_DRIVE_COORDINATOR_POLICY`
    Policy: Android mesh signals MUST drive live coordinator state transitions.
:data:`RUNTIME_CLOSED_FROM_ANDROID_SIGNALS_POLICY`
    Policy: ``runtime_closed`` MUST be reachable through real Android signals.
:data:`ANDROID_PROOF_QUALITY_IMPACTS_READINESS_POLICY`
    Policy: Android participant proof quality MUST be propagated to the center
    readiness impact classification.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PR-2 authority sentinel
# ---------------------------------------------------------------------------

ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL: str = (
    "SENTINEL::ANDROID_MESH_SIGNAL_ADAPTER_PR2: "
    "adapter wiring Android-originated mesh participation signals into the V2 "
    "center-side mesh runtime closure path; "
    "package=PR-2::android-mesh-signal-adapter::"
    "runtime_closed-reachable-from-real-android-participation"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ANDROID_SIGNALS_DRIVE_COORDINATOR_POLICY: str = (
    "POLICY::ANDROID_SIGNALS_DRIVE_COORDINATOR: "
    "Android-originated mesh participation signals (readiness_confirmed, "
    "barrier_reached, task_completed, task_failed, participant_dropped) MUST "
    "be translated into live coordinator events via apply_android_participation_signal(). "
    "No synthetic coordinator state manipulation is permitted — coordinator "
    "transitions MUST be driven by the real LiveMeshSessionCoordinator methods "
    "on_participant_ready(), on_participant_working(), on_participant_result(), "
    "on_participant_failed(), and on_participant_dropped()."
)

RUNTIME_CLOSED_FROM_ANDROID_SIGNALS_POLICY: str = (
    "POLICY::RUNTIME_CLOSED_FROM_ANDROID_SIGNALS: "
    "The center-side runtime_closed status MUST be reachable through real "
    "Android participant signals — not only through V2-internal batch "
    "simulation.  evaluate_center_runtime_status_with_android_signals() is "
    "the canonical path: Android signals are applied to a live coordinator, "
    "and evaluate_center_runtime_status() is called on the resulting state.  "
    "This makes runtime_closed reachable when all Android participants have "
    "signalled task_completed."
)

ANDROID_PROOF_QUALITY_IMPACTS_READINESS_POLICY: str = (
    "POLICY::ANDROID_PROOF_QUALITY_IMPACTS_READINESS: "
    "The proof quality of Android participant contributions (live, partial, "
    "or missing) MUST be classified by classify_android_proof_quality() and "
    "propagated to the center readiness impact.  When proof quality is "
    "'missing' for any participant, the center readiness impact MUST include "
    "'android_proof_missing'.  When quality is 'partial', the impact MUST "
    "include 'android_proof_partial'.  These impact flags are surfaced in "
    "the operator snapshot for diagnostic visibility."
)

ANDROID_SIGNAL_ROUTING_NON_RAISING_POLICY: str = (
    "POLICY::ANDROID_SIGNAL_ROUTING_NON_RAISING: "
    "All public functions in this adapter MUST return valid objects without "
    "raising exceptions.  Errors from signal routing (e.g. unknown device_id, "
    "coordinator not found, unrecognised signal kind) MUST be captured in the "
    "return value's error_reason field and logged at WARNING level.  The caller "
    "MUST NOT need to handle exceptions from this adapter."
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    ANDROID_SIGNALS_DRIVE_COORDINATOR_POLICY,
    RUNTIME_CLOSED_FROM_ANDROID_SIGNALS_POLICY,
    ANDROID_PROOF_QUALITY_IMPACTS_READINESS_POLICY,
    ANDROID_SIGNAL_ROUTING_NON_RAISING_POLICY,
)


# ---------------------------------------------------------------------------
# AndroidMeshParticipantSignalKind enum
# ---------------------------------------------------------------------------


class AndroidMeshParticipantSignalKind(str, Enum):
    """Kind of Android-originated mesh participation signal.

    Values
    ------
    readiness_confirmed
        Android device has confirmed it is ready to participate in this mesh
        session.  Maps to ``on_participant_ready()`` on the coordinator.
    barrier_reached
        Android device has completed its active work and arrived at the
        coordination barrier.  Maps to ``on_participant_working()`` followed
        by the barrier tracking logic.
    task_completed
        Android device has completed its assigned mesh task and is uploading
        a result.  Maps to ``on_participant_result()`` on the coordinator,
        which triggers barrier evaluation.
    task_failed
        Android device has failed to complete its mesh task.  Maps to
        ``on_participant_failed()`` on the coordinator.
    participant_dropped
        Android device has disconnected or been dropped from the session.
        Maps to ``on_participant_dropped()`` on the coordinator.
    unknown
        Unrecognised signal kind; routed to audit-only handling.
    """

    readiness_confirmed = "readiness_confirmed"
    barrier_reached = "barrier_reached"
    task_completed = "task_completed"
    task_failed = "task_failed"
    participant_dropped = "participant_dropped"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "AndroidMeshParticipantSignalKind":
        """Return the matching kind or ``unknown`` for unrecognised values."""
        if not value:
            return cls.unknown
        normalised = str(value).strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.unknown

    def drives_coordinator_transition(self) -> bool:
        """Return True iff this signal kind drives a live coordinator state change."""
        return self in (
            AndroidMeshParticipantSignalKind.readiness_confirmed,
            AndroidMeshParticipantSignalKind.barrier_reached,
            AndroidMeshParticipantSignalKind.task_completed,
            AndroidMeshParticipantSignalKind.task_failed,
            AndroidMeshParticipantSignalKind.participant_dropped,
        )


# ---------------------------------------------------------------------------
# AndroidMeshParticipantSignal dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidMeshParticipantSignal:
    """Typed, immutable carrier for a single Android-originated mesh
    participation signal.

    Attributes
    ----------
    signal_kind
        The :class:`AndroidMeshParticipantSignalKind` classifying this signal.
    device_id
        Android device identifier.  Used to look up the participant in the
        live coordinator.
    session_id
        Mesh session identifier.  Used to correlate signals with the correct
        coordinator instance.
    signal_id
        UUID assigned to this signal instance for idempotency / audit.
    received_at
        Unix timestamp (float) when this signal was received by V2.
    result_payload
        For ``task_completed`` signals: the Android-side task result payload.
        Empty dict when not applicable.
    failure_reason
        For ``task_failed`` and ``participant_dropped`` signals: human-readable
        failure or dropout reason string.
    barrier_sequence
        For ``barrier_reached`` signals: optional sequence/order indicator
        to support multi-step barrier protocols.
    metadata
        Optional extension metadata.
    """

    signal_kind: AndroidMeshParticipantSignalKind = AndroidMeshParticipantSignalKind.unknown
    device_id: str = ""
    session_id: str = ""
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    received_at: float = field(default_factory=time.time)
    result_payload: Dict[str, Any] = field(default_factory=dict)
    failure_reason: str = ""
    barrier_sequence: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_kind": self.signal_kind.value,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "signal_id": self.signal_id,
            "received_at": self.received_at,
            "result_payload": dict(self.result_payload),
            "failure_reason": self.failure_reason,
            "barrier_sequence": self.barrier_sequence,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# AndroidMeshParticipationRecord dataclass
# ---------------------------------------------------------------------------


@dataclass
class AndroidMeshParticipationRecord:
    """Aggregated per-device record of all Android-originated signals for a
    single mesh session.

    Tracks the highest-fidelity participation state observed from Android
    signals.  Used by :func:`classify_android_proof_quality` to determine
    the proof quality of an Android participant's contribution.

    Attributes
    ----------
    device_id
        Android device identifier.
    session_id
        Mesh session identifier.
    readiness_confirmed
        True iff a ``readiness_confirmed`` signal has been received.
    barrier_reached
        True iff a ``barrier_reached`` signal has been received.
    task_completed
        True iff a ``task_completed`` signal has been received.
    task_failed
        True iff a ``task_failed`` signal has been received.
    participant_dropped
        True iff a ``participant_dropped`` signal has been received.
    result_payload
        Result payload from the most recent ``task_completed`` signal.
    failure_reason
        Failure reason from the most recent ``task_failed`` or
        ``participant_dropped`` signal.
    signal_count
        Total number of signals received for this device/session.
    last_signal_at
        Unix timestamp of the most recently processed signal.
    errors
        List of error strings accumulated during signal processing.
    """

    device_id: str = ""
    session_id: str = ""
    readiness_confirmed: bool = False
    barrier_reached: bool = False
    task_completed: bool = False
    task_failed: bool = False
    participant_dropped: bool = False
    result_payload: Dict[str, Any] = field(default_factory=dict)
    failure_reason: str = ""
    signal_count: int = 0
    last_signal_at: float = field(default_factory=time.time)
    errors: List[str] = field(default_factory=list)

    def update_from_signal(self, signal: AndroidMeshParticipantSignal) -> None:
        """Update this record with a new signal."""
        self.signal_count += 1
        self.last_signal_at = signal.received_at
        kind = signal.signal_kind
        if kind == AndroidMeshParticipantSignalKind.readiness_confirmed:
            self.readiness_confirmed = True
        elif kind == AndroidMeshParticipantSignalKind.barrier_reached:
            self.barrier_reached = True
        elif kind == AndroidMeshParticipantSignalKind.task_completed:
            self.task_completed = True
            if signal.result_payload:
                self.result_payload = dict(signal.result_payload)
        elif kind == AndroidMeshParticipantSignalKind.task_failed:
            self.task_failed = True
            if signal.failure_reason:
                self.failure_reason = signal.failure_reason
        elif kind == AndroidMeshParticipantSignalKind.participant_dropped:
            self.participant_dropped = True
            if signal.failure_reason:
                self.failure_reason = signal.failure_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "session_id": self.session_id,
            "readiness_confirmed": self.readiness_confirmed,
            "barrier_reached": self.barrier_reached,
            "task_completed": self.task_completed,
            "task_failed": self.task_failed,
            "participant_dropped": self.participant_dropped,
            "result_payload": dict(self.result_payload),
            "failure_reason": self.failure_reason,
            "signal_count": self.signal_count,
            "last_signal_at": self.last_signal_at,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# AndroidSignalApplicationOutcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidSignalApplicationOutcome:
    """Result of applying a single :class:`AndroidMeshParticipantSignal` to a
    live :class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`.

    Attributes
    ----------
    signal
        The signal that was processed.
    applied
        True iff the signal was successfully routed to a coordinator method.
    coordinator_method_called
        Name of the coordinator method that was called (e.g.
        ``'on_participant_ready'``).  Empty string when ``applied`` is False.
    error_reason
        Non-empty string when ``applied`` is False, describing why the signal
        could not be applied.
    """

    signal: AndroidMeshParticipantSignal
    applied: bool = False
    coordinator_method_called: str = ""
    error_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied,
            "coordinator_method_called": self.coordinator_method_called,
            "error_reason": self.error_reason,
            "signal": self.signal.to_dict(),
        }


# ---------------------------------------------------------------------------
# Proof quality classification
# ---------------------------------------------------------------------------

AndroidProofQuality = str  # "live" | "partial" | "missing"

_PROOF_QUALITY_LIVE = "live"
_PROOF_QUALITY_PARTIAL = "partial"
_PROOF_QUALITY_MISSING = "missing"


def classify_android_proof_quality(
    record: AndroidMeshParticipationRecord,
) -> str:
    """Classify the proof quality of an Android participant's contribution.

    Parameters
    ----------
    record:
        :class:`AndroidMeshParticipationRecord` aggregating all signals from
        an Android device for a single mesh session.

    Returns
    -------
    str
        One of ``"live"``, ``"partial"``, or ``"missing"``:

        * ``"live"`` — the participant signalled ``task_completed`` (with
          optional ``barrier_reached``) — full participation proof observed.
        * ``"partial"`` — the participant signalled ``readiness_confirmed``
          and/or ``barrier_reached`` but did NOT signal ``task_completed``
          or ``task_failed`` — participation started but not concluded.
        * ``"missing"`` — no signals have been received for this participant
          (``signal_count == 0``), or the participant was dropped with no
          other completion signal.
    """
    if record.task_completed:
        return _PROOF_QUALITY_LIVE
    if record.task_failed:
        # Failure is a definitive terminal signal — treat as partial (not missing).
        return _PROOF_QUALITY_PARTIAL
    if record.readiness_confirmed or record.barrier_reached:
        return _PROOF_QUALITY_PARTIAL
    if record.participant_dropped and record.signal_count > 0:
        return _PROOF_QUALITY_PARTIAL
    return _PROOF_QUALITY_MISSING


def classify_android_proof_quality_for_signals(
    signals: List[AndroidMeshParticipantSignal],
    device_id: str,
    session_id: str,
) -> str:
    """Convenience wrapper: classify proof quality from a raw signal list.

    Builds a :class:`AndroidMeshParticipationRecord` from ``signals`` filtered
    to the given ``device_id`` / ``session_id``, then delegates to
    :func:`classify_android_proof_quality`.
    """
    record = build_android_participation_record(signals, device_id=device_id, session_id=session_id)
    return classify_android_proof_quality(record)


# ---------------------------------------------------------------------------
# Build participation record from signal list
# ---------------------------------------------------------------------------


def build_android_participation_record(
    signals: List[AndroidMeshParticipantSignal],
    *,
    device_id: str = "",
    session_id: str = "",
) -> AndroidMeshParticipationRecord:
    """Build an :class:`AndroidMeshParticipationRecord` from a list of signals.

    Filters ``signals`` to those matching ``device_id`` and ``session_id``
    (when non-empty) and applies them in order to build the aggregate record.

    Parameters
    ----------
    signals:
        Ordered list of :class:`AndroidMeshParticipantSignal` instances.
    device_id:
        If non-empty, only signals matching this device ID are included.
    session_id:
        If non-empty, only signals matching this session ID are included.

    Returns
    -------
    AndroidMeshParticipationRecord
        Always returns a valid record; never raises.
    """
    record = AndroidMeshParticipationRecord(
        device_id=device_id,
        session_id=session_id,
    )
    try:
        for sig in signals or []:
            if device_id and sig.device_id != device_id:
                continue
            if session_id and sig.session_id != session_id:
                continue
            record.update_from_signal(sig)
    except Exception as exc:
        record.errors.append(f"build_participation_record_error:{exc}")
        _logger.warning("build_android_participation_record: %s", exc)
    return record


# ---------------------------------------------------------------------------
# Apply a single Android signal to a live coordinator
# ---------------------------------------------------------------------------


def apply_android_participation_signal(
    coordinator: Any,
    signal: AndroidMeshParticipantSignal,
) -> AndroidSignalApplicationOutcome:
    """Apply a single :class:`AndroidMeshParticipantSignal` to a live
    :class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`.

    Routes the signal to the appropriate coordinator lifecycle method based on
    :attr:`signal.signal_kind`:

    * ``readiness_confirmed`` → ``coordinator.on_participant_ready(device_id)``
    * ``barrier_reached`` → ``coordinator.on_participant_working(device_id)``
    * ``task_completed`` → ``coordinator.on_participant_result(device_id, payload)``
    * ``task_failed`` → ``coordinator.on_participant_failed(device_id, reason=...)``
    * ``participant_dropped`` → ``coordinator.on_participant_dropped(device_id, reason=...)``

    Parameters
    ----------
    coordinator:
        A :class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`
        instance.  Must expose the ``on_participant_*`` methods.
    signal:
        The :class:`AndroidMeshParticipantSignal` to apply.

    Returns
    -------
    AndroidSignalApplicationOutcome
        Always returns a valid outcome; never raises.
    """
    if coordinator is None:
        return AndroidSignalApplicationOutcome(
            signal=signal,
            applied=False,
            error_reason="coordinator_is_none",
        )

    kind = signal.signal_kind
    did = signal.device_id

    if not kind.drives_coordinator_transition():
        return AndroidSignalApplicationOutcome(
            signal=signal,
            applied=False,
            error_reason=f"signal_kind_does_not_drive_coordinator:{kind.value}",
        )

    try:
        if kind == AndroidMeshParticipantSignalKind.readiness_confirmed:
            coordinator.on_participant_ready(did)
            method = "on_participant_ready"

        elif kind == AndroidMeshParticipantSignalKind.barrier_reached:
            # Barrier reached means the participant is in the active working
            # phase and has arrived at the coordination barrier.  We drive the
            # coordinator to the "working" state here; the barrier release
            # itself is managed by on_participant_result() via barrier tracking.
            coordinator.on_participant_working(did)
            method = "on_participant_working"

        elif kind == AndroidMeshParticipantSignalKind.task_completed:
            payload = dict(signal.result_payload) if signal.result_payload else {"success": True}
            coordinator.on_participant_result(did, payload)
            method = "on_participant_result"

        elif kind == AndroidMeshParticipantSignalKind.task_failed:
            coordinator.on_participant_failed(did, reason=signal.failure_reason or "android_task_failed")
            method = "on_participant_failed"

        elif kind == AndroidMeshParticipantSignalKind.participant_dropped:
            coordinator.on_participant_dropped(did, reason=signal.failure_reason or "android_participant_dropped")
            method = "on_participant_dropped"

        else:
            return AndroidSignalApplicationOutcome(
                signal=signal,
                applied=False,
                error_reason=f"unhandled_signal_kind:{kind.value}",
            )

        _logger.info(
            "android_mesh_signal_applied: session_id=%s device_id=%s kind=%s method=%s",
            signal.session_id,
            did,
            kind.value,
            method,
        )
        return AndroidSignalApplicationOutcome(
            signal=signal,
            applied=True,
            coordinator_method_called=method,
        )

    except Exception as exc:
        _logger.warning(
            "apply_android_participation_signal: error applying %s for device=%s: %s",
            kind.value,
            did,
            exc,
        )
        return AndroidSignalApplicationOutcome(
            signal=signal,
            applied=False,
            error_reason=f"coordinator_method_error:{exc}",
        )


# ---------------------------------------------------------------------------
# Evaluate center runtime status with Android signals
# ---------------------------------------------------------------------------


def evaluate_center_runtime_status_with_android_signals(
    coordinator_state: Any,
    android_signals: List[AndroidMeshParticipantSignal],
    *,
    register_android_devices: bool = True,
) -> Any:
    """Evaluate center-side mesh runtime status driven by real Android signals.

    This is the canonical path through which ``runtime_closed`` becomes
    reachable from real Android participation.

    The function:

    1. Wraps ``coordinator_state`` in a live
       :class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`.
    2. Optionally registers any Android device IDs not already present as
       participants (when ``register_android_devices=True``).
    3. Applies each :class:`AndroidMeshParticipantSignal` in order via
       :func:`apply_android_participation_signal`, driving real coordinator
       state transitions.
    4. Calls :func:`~core.mesh.mesh_runtime_center_state.evaluate_center_runtime_status`
       on the coordinator's post-signal state.
    5. Attaches ``android_participation_summary`` and
       ``android_proof_quality_map`` to the result metadata for observability.

    Parameters
    ----------
    coordinator_state:
        A :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
        providing the baseline coordinator state.  May be ``None``; the
        function returns a ``pending_participants`` state in that case.
    android_signals:
        Ordered list of :class:`AndroidMeshParticipantSignal` instances from
        Android participants.  Applied in order.
    register_android_devices:
        When ``True`` (default), device IDs present in ``android_signals`` but
        absent from ``coordinator_state.participants`` are registered as
        participants before signals are applied.  This supports the case where
        Android devices self-register via signals rather than through a prior
        coordinator setup phase.

    Returns
    -------
    MeshRuntimeCenterState
        Always returns a valid
        :class:`~core.mesh.mesh_runtime_center_state.MeshRuntimeCenterState`;
        never raises.  The ``metadata`` field includes:

        * ``android_participation_summary`` — dict mapping device_id to
          :class:`AndroidMeshParticipationRecord` summaries.
        * ``android_proof_quality_map`` — dict mapping device_id to proof
          quality string (``"live"``, ``"partial"``, or ``"missing"``).
        * ``android_signals_applied`` — count of signals successfully applied.
        * ``android_signals_total`` — total number of signals provided.
    """
    from core.mesh.mesh_runtime_center_state import (  # noqa: PLC0415
        MeshRuntimeCenterState,
        MeshRuntimeCenterStatus,
        evaluate_center_runtime_status,
    )

    errors: List[str] = []

    if coordinator_state is None:
        return MeshRuntimeCenterState(
            status=MeshRuntimeCenterStatus.pending_participants,
            errors=["coordinator_state_is_none"],
            deferred_or_constrained=["no coordinator state provided; android signals cannot be applied"],
            metadata={
                "android_participation_summary": {},
                "android_proof_quality_map": {},
                "android_signals_applied": 0,
                "android_signals_total": len(android_signals or []),
            },
        )

    try:
        from core.mesh.live_mesh_session_coordinator import LiveMeshSessionCoordinator  # noqa: PLC0415

        live_coord = LiveMeshSessionCoordinator(coordinator_state)
    except Exception as exc:
        errors.append(f"live_coordinator_construction_error:{exc}")
        _logger.warning("evaluate_center_runtime_status_with_android_signals: %s", exc)
        return evaluate_center_runtime_status(coordinator_state)

    signals_total = len(android_signals or [])
    signals_applied = 0

    # --- Optional: register Android devices not already in coordinator ---
    if register_android_devices and android_signals:
        try:
            existing_device_ids: List[str] = [
                getattr(p, "device_id", "")
                for p in (getattr(coordinator_state, "participants", []) or [])
            ]
            seen_device_ids: List[str] = []
            for sig in android_signals:
                did = sig.device_id
                if did and did not in existing_device_ids and did not in seen_device_ids:
                    live_coord.add_participant(did, roles=["android_participant"])
                    seen_device_ids.append(did)
                    _logger.info(
                        "android_mesh_signal_adapter: auto-registered android participant=%s session=%s",
                        did,
                        sig.session_id,
                    )
        except Exception as exc:
            errors.append(f"android_device_registration_error:{exc}")
            _logger.warning("evaluate_center_runtime_status_with_android_signals: registration: %s", exc)

    # --- Apply Android signals in order ---
    participation_records: Dict[str, AndroidMeshParticipationRecord] = {}

    for sig in android_signals or []:
        did = sig.device_id
        # Build/update participation record
        if did not in participation_records:
            participation_records[did] = AndroidMeshParticipationRecord(
                device_id=did,
                session_id=sig.session_id,
            )
        participation_records[did].update_from_signal(sig)

        # Apply to coordinator
        outcome = apply_android_participation_signal(live_coord, sig)
        if outcome.applied:
            signals_applied += 1
        else:
            errors.append(
                f"signal_not_applied:{sig.signal_kind.value}:{did}:{outcome.error_reason}"
            )

    # --- Resolve coordinator state for evaluation ---
    # When all participants are accounted-for (all completed or failed/dropped),
    # finalize() runs the batch engine which resolves coordinator status to
    # "completed"/"partial"/"failed" — the statuses that map correctly to
    # runtime_closed in evaluate_center_runtime_status().  For in-progress
    # sessions (not all participants done), we use the live state directly so
    # that barrier_active / runtime_active statuses are correctly reflected.
    try:
        if live_coord.is_complete:
            # All participants accounted-for: finalize to get the canonical
            # "completed"/"partial"/"failed" coordinator state.
            final_result = live_coord.finalize()
            if final_result is not None and hasattr(final_result, "coordinator_state"):
                post_signal_state = final_result.coordinator_state
            else:
                post_signal_state = live_coord.state
        else:
            # Session still in progress: use the live intermediate state.
            post_signal_state = live_coord.state
    except Exception as exc:
        errors.append(f"coordinator_state_resolution_error:{exc}")
        _logger.warning(
            "evaluate_center_runtime_status_with_android_signals: state resolution: %s", exc
        )
        post_signal_state = live_coord.state

    try:
        center_state = evaluate_center_runtime_status(post_signal_state)
    except Exception as exc:
        errors.append(f"evaluate_center_runtime_status_error:{exc}")
        _logger.warning(
            "evaluate_center_runtime_status_with_android_signals: evaluation error: %s", exc
        )
        center_state = evaluate_center_runtime_status(coordinator_state)

    # --- Build proof quality map ---
    proof_quality_map: Dict[str, str] = {}
    participation_summary: Dict[str, Any] = {}
    for did, rec in participation_records.items():
        quality = classify_android_proof_quality(rec)
        proof_quality_map[did] = quality
        participation_summary[did] = rec.to_dict()

    # Classify readiness impact based on proof quality
    readiness_impact_notes: List[str] = []
    for did, quality in proof_quality_map.items():
        if quality == _PROOF_QUALITY_MISSING:
            readiness_impact_notes.append(f"android_proof_missing:{did}")
        elif quality == _PROOF_QUALITY_PARTIAL:
            readiness_impact_notes.append(f"android_proof_partial:{did}")

    # --- Attach metadata to center state ---
    android_metadata: Dict[str, Any] = {
        "android_participation_summary": participation_summary,
        "android_proof_quality_map": proof_quality_map,
        "android_signals_applied": signals_applied,
        "android_signals_total": signals_total,
        "android_readiness_impact_notes": readiness_impact_notes,
        "android_signal_adapter_sentinel": ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL,
    }
    if errors:
        android_metadata["android_adapter_errors"] = errors

    # Merge metadata into existing center_state metadata
    merged_metadata = dict(center_state.metadata or {})
    merged_metadata.update(android_metadata)

    from dataclasses import replace  # noqa: PLC0415

    return replace(center_state, metadata=merged_metadata)


# ---------------------------------------------------------------------------
# Batch helper: apply multiple signals and return all outcomes
# ---------------------------------------------------------------------------


def apply_android_participation_signals_batch(
    coordinator: Any,
    signals: List[AndroidMeshParticipantSignal],
) -> List[AndroidSignalApplicationOutcome]:
    """Apply a list of Android participation signals to a coordinator.

    Applies each signal in order.  Continues on individual failures.

    Parameters
    ----------
    coordinator:
        :class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`
        instance.
    signals:
        Ordered list of :class:`AndroidMeshParticipantSignal` instances.

    Returns
    -------
    List[AndroidSignalApplicationOutcome]
        One outcome per signal, in the same order.  Never raises.
    """
    outcomes: List[AndroidSignalApplicationOutcome] = []
    for sig in signals or []:
        try:
            outcome = apply_android_participation_signal(coordinator, sig)
        except Exception as exc:
            _logger.warning("apply_android_participation_signals_batch: %s", exc)
            outcome = AndroidSignalApplicationOutcome(
                signal=sig,
                applied=False,
                error_reason=f"unexpected_error:{exc}",
            )
        outcomes.append(outcome)
    return outcomes


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinel
    "ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL",
    # Policy sentinels
    "ANDROID_SIGNALS_DRIVE_COORDINATOR_POLICY",
    "RUNTIME_CLOSED_FROM_ANDROID_SIGNALS_POLICY",
    "ANDROID_PROOF_QUALITY_IMPACTS_READINESS_POLICY",
    "ANDROID_SIGNAL_ROUTING_NON_RAISING_POLICY",
    # Enums
    "AndroidMeshParticipantSignalKind",
    # Dataclasses
    "AndroidMeshParticipantSignal",
    "AndroidMeshParticipationRecord",
    "AndroidSignalApplicationOutcome",
    # Functions
    "apply_android_participation_signal",
    "apply_android_participation_signals_batch",
    "build_android_participation_record",
    "classify_android_proof_quality",
    "classify_android_proof_quality_for_signals",
    "evaluate_center_runtime_status_with_android_signals",
]
