#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/device_formation/formation_runtime_coordinator.py
=======================================================
Formation Runtime Coordinator — PR-2 (Formation Rebalance and Runtime Recovery Hooks).

Background
----------
The existing :mod:`~core.device_formation.formation_rebalance_engine` provides a
*stateless* evaluation / reshape primitive for health-driven formation changes.
The existing :mod:`~core.multi_device_runtime_harness` provides coarse integration
hooks (coordinator-state persistence and health-event entry points).

What has been missing is a **stateful runtime coordinator** that:

* Tracks the liveness state of each formation participant across its lifetime.
* Exposes **explicit trigger points** — ``on_participant_readiness_changed``,
  ``on_participant_lost``, ``on_health_degraded``, ``on_recovery_available`` —
  that callers invoke as runtime conditions change.
* Evaluates whether a formation can **continue in a degraded state**, should be
  *reshaped*, or must be terminated.
* Produces **recovery-oriented decisions** (promote fallback, remove unhealthy,
  continue degraded, request full rebalance) that callers can act on without
  re-implementing the decision logic.

This module closes that gap.  It is designed to sit above
:class:`~.formation_rebalance_engine.FormationRebalanceEngine` (which handles the
low-level membership arithmetic) and below any full distributed scheduler.

Design principles
-----------------
- **Additive only** — does not modify ``formation_resolver.py``,
  ``formation_rebalance_engine.py``, or any other existing module.
- **Stateful but serialisable** — the coordinator tracks participant states
  in a plain dict; :meth:`FormationRuntimeCoordinator.snapshot` returns a
  JSON-compatible dict for persistence.
- **Recovery-oriented** — every trigger method returns a
  :class:`FormationRuntimeDecision` so callers can immediately act on the
  recommendation without a separate evaluation step.
- **Graceful degradation** — every public method is guarded; unexpected errors
  produce a safe no-op decision rather than raising.
- **Threshold-configurable** — minimum viable participant count and health
  thresholds are constructor arguments with sensible defaults.

Sentinels
---------
:data:`FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY`
    Identifies this module as the canonical runtime-coordinator layer for
    formation lifecycle management.
:data:`FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL`
    Affirms this module closes the gap of missing runtime recovery hooks in
    the formation stack.
:data:`DEGRADED_CONTINUATION_REQUIRES_PRIMARY_POLICY`
    Affirms that degraded-continuation mode still requires a viable
    PRIMARY_EXECUTION member.
:data:`RECOVERY_PRESERVES_SOURCE_POLICY`
    Affirms that recovery never terminates the SOURCE member's participation.

Public API
----------
Enumerations:
    :class:`FormationParticipantState`
    :class:`FormationRuntimeState`
    :class:`RecoveryActionType`

Data classes:
    :class:`FormationParticipantStatus`
    :class:`FormationRecoveryAction`
    :class:`FormationRuntimeDecision`
    :class:`FormationRuntimeSnapshot`

Classes:
    :class:`FormationRuntimeCoordinator`

Functions:
    :func:`make_formation_runtime_coordinator`
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .formation_group import DeviceFormationGroup, EMPTY_FORMATION_GROUP
from .formation_role import FormationRole

__all__ = [
    # Sentinels
    "FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY",
    "FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL",
    "DEGRADED_CONTINUATION_REQUIRES_PRIMARY_POLICY",
    "RECOVERY_PRESERVES_SOURCE_POLICY",
    # Enumerations
    "FormationParticipantState",
    "FormationRuntimeState",
    "RecoveryActionType",
    # Data classes
    "FormationParticipantStatus",
    "FormationRecoveryAction",
    "FormationRuntimeDecision",
    "FormationRuntimeSnapshot",
    # Class
    "FormationRuntimeCoordinator",
    # Convenience
    "make_formation_runtime_coordinator",
]

logger = logging.getLogger("Galaxy.DeviceFormation.RuntimeCoordinator")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY: str = (
    "FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY: "
    "core/device_formation/formation_runtime_coordinator.py is the canonical "
    "stateful runtime coordinator for formation lifecycle and recovery-oriented "
    "reshaping.  It sits above FormationRebalanceEngine (stateless arithmetic) "
    "and below any full distributed scheduler."
)

FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL: str = (
    "FORMATION_RECOVERY_HOOKS_GAP_CLOSURE: "
    "This module closes the gap of missing formation runtime recovery hooks "
    "identified in docs/FOLLOWUP_IMPLEMENTATION_ROADMAP.md §B5 and the "
    "PR-2 problem statement: explicit trigger points for readiness changes, "
    "participant loss, health degradation, and recovery availability."
)

DEGRADED_CONTINUATION_REQUIRES_PRIMARY_POLICY: str = (
    "DEGRADED_CONTINUATION_POLICY: A formation may continue in "
    "DEGRADED_CONTINUATION state only when at least one PRIMARY_EXECUTION "
    "member remains viable.  If no viable primary exists the coordinator "
    "transitions to TERMINATED unless a fallback promotion is possible."
)

RECOVERY_PRESERVES_SOURCE_POLICY: str = (
    "RECOVERY_POLICY: Recovery and reshaping never remove the SOURCE member "
    "from the formation.  The origin device's participation record is "
    "preserved across all state transitions."
)

# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

_DEFAULT_UNHEALTHY_THRESHOLD: float = 0.3
_DEFAULT_DEGRADED_THRESHOLD: float = 0.6
_DEFAULT_MIN_VIABLE_PARTICIPANTS: int = 1  # at minimum: primary must be viable


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FormationParticipantState(str, Enum):
    """Liveness state of a single formation participant."""

    READY = "ready"
    """Participant is healthy and actively contributing."""

    DEGRADED = "degraded"
    """Participant is reachable but with degraded health score."""

    LOST = "lost"
    """Participant is unreachable / disconnected."""

    RECOVERING = "recovering"
    """Participant was lost but is signalling re-availability."""


class FormationRuntimeState(str, Enum):
    """Overall runtime state of the formation."""

    ACTIVE = "active"
    """All participants are healthy; nominal operation."""

    DEGRADED = "degraded"
    """One or more participants are degraded; formation viable but impaired."""

    RESHAPING = "reshaping"
    """Formation is undergoing a rebalance (transient)."""

    DEGRADED_CONTINUATION = "degraded_continuation"
    """Running with reduced participants; at least one PRIMARY remains viable."""

    RECOVERING = "recovering"
    """A previously terminated or degraded formation is attempting recovery."""

    TERMINATED = "terminated"
    """Formation cannot continue; no viable primary execution path exists."""


class RecoveryActionType(str, Enum):
    """Recommended recovery action from the coordinator."""

    KEEP = "keep"
    """No action needed; formation is healthy."""

    PROMOTE_FALLBACK = "promote_fallback"
    """Promote a fallback device to PRIMARY_EXECUTION."""

    REMOVE_PARTICIPANT = "remove_participant"
    """Remove a lost / unhealthy participant from the active formation."""

    CONTINUE_DEGRADED = "continue_degraded"
    """Continue execution with remaining viable participants."""

    RESHAPE = "reshape"
    """Run a full formation rebalance pass via FormationRebalanceEngine."""

    TERMINATE = "terminate"
    """Formation cannot continue; signal terminal state to the caller."""

    REQUEST_RECOVERY = "request_recovery"
    """Signal that a previously-lost participant is now available for recovery."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FormationParticipantStatus:
    """Runtime liveness record for one formation participant.

    Attributes
    ----------
    device_id:
        Device identifier.
    state:
        Current :class:`FormationParticipantState`.
    role:
        String representation of the :class:`~.formation_role.FormationRole`.
    health_score:
        Last known health score in ``[0.0, 1.0]``.
    last_update_ts:
        Epoch timestamp of the last state update.
    reason:
        Optional human-readable reason for the current state.
    """

    device_id: str
    state: FormationParticipantState = FormationParticipantState.READY
    role: str = "unassigned"
    health_score: float = 1.0
    last_update_ts: float = field(default_factory=time.time)
    reason: Optional[str] = None

    @property
    def is_viable(self) -> bool:
        """Return True if this participant can contribute to execution."""
        return self.state in (
            FormationParticipantState.READY,
            FormationParticipantState.DEGRADED,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "state": self.state.value,
            "role": self.role,
            "health_score": self.health_score,
            "last_update_ts": self.last_update_ts,
            "reason": self.reason,
        }


@dataclass
class FormationRecoveryAction:
    """A single recommended recovery action.

    Attributes
    ----------
    action_type:
        The :class:`RecoveryActionType` to apply.
    affected_device_id:
        Device ID this action targets (if applicable).
    reason:
        Human-readable explanation of why this action is recommended.
    """

    action_type: RecoveryActionType
    affected_device_id: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "affected_device_id": self.affected_device_id,
            "reason": self.reason,
        }


@dataclass
class FormationRuntimeDecision:
    """Decision produced by the :class:`FormationRuntimeCoordinator` after a trigger.

    Attributes
    ----------
    formation_id:
        Formation this decision applies to.
    runtime_state:
        The :class:`FormationRuntimeState` after applying this decision.
    recommended_actions:
        Ordered list of :class:`FormationRecoveryAction` for the caller to apply.
    new_group:
        Reshaped :class:`~.formation_group.DeviceFormationGroup` if a reshape
        was performed; ``None`` if the existing group is unchanged.
    continuation_viable:
        ``True`` when the formation can continue in some form (active, degraded,
        or degraded-continuation).
    reason:
        Human-readable summary of the decision.
    trigger_event:
        The trigger event type that produced this decision.
    """

    formation_id: str = ""
    runtime_state: FormationRuntimeState = FormationRuntimeState.ACTIVE
    recommended_actions: List[FormationRecoveryAction] = field(default_factory=list)
    new_group: Optional[DeviceFormationGroup] = None
    continuation_viable: bool = True
    reason: str = ""
    trigger_event: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formation_id": self.formation_id,
            "runtime_state": self.runtime_state.value,
            "recommended_actions": [a.to_dict() for a in self.recommended_actions],
            "new_group": (
                getattr(self.new_group, "to_dict", lambda: None)()
                if self.new_group is not None
                else None
            ),
            "continuation_viable": self.continuation_viable,
            "reason": self.reason,
            "trigger_event": self.trigger_event,
        }


@dataclass
class FormationRuntimeSnapshot:
    """Serialisable snapshot of all runtime state for a formation.

    Suitable for persistence or diagnostic emission.

    Attributes
    ----------
    formation_id:
        Formation identifier.
    runtime_state:
        Current :class:`FormationRuntimeState`.
    participant_statuses:
        Mapping of device_id → :class:`FormationParticipantStatus`.
    snapshot_ts:
        Epoch timestamp when the snapshot was taken.
    """

    formation_id: str = ""
    runtime_state: FormationRuntimeState = FormationRuntimeState.ACTIVE
    participant_statuses: Dict[str, FormationParticipantStatus] = field(
        default_factory=dict
    )
    snapshot_ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formation_id": self.formation_id,
            "runtime_state": self.runtime_state.value,
            "participant_statuses": {
                k: v.to_dict() for k, v in self.participant_statuses.items()
            },
            "snapshot_ts": self.snapshot_ts,
        }


# ---------------------------------------------------------------------------
# FormationRuntimeCoordinator
# ---------------------------------------------------------------------------


class FormationRuntimeCoordinator:
    """Stateful runtime coordinator for formation lifecycle and recovery hooks.

    This coordinator tracks participant readiness across the lifetime of a
    formation, exposes explicit trigger points for runtime condition changes,
    and produces :class:`FormationRuntimeDecision` objects that callers can
    act on immediately.

    It delegates the low-level membership arithmetic to
    :class:`~.formation_rebalance_engine.FormationRebalanceEngine` and does
    not own persistent state (use :meth:`snapshot` + persistence layer for
    durability).

    Usage::

        coordinator = FormationRuntimeCoordinator(formation_group)

        # Device disconnects
        decision = coordinator.on_participant_lost("phone_01", reason="disconnect")
        if decision.continuation_viable:
            if decision.new_group:
                # apply the reshaped formation
                current_group = decision.new_group
        else:
            # handle terminal state

        # Device health degrades
        decision = coordinator.on_health_degraded("tablet_02", health_score=0.2)

        # Device comes back online
        decision = coordinator.on_recovery_available("phone_01", health_score=0.85)

    Parameters
    ----------
    group:
        The initial :class:`~.formation_group.DeviceFormationGroup` to manage.
    unhealthy_threshold:
        Health score below which a device is unhealthy.  Default: 0.3.
    degraded_threshold:
        Health score below which (but above unhealthy) a device is degraded.
        Default: 0.6.
    min_viable_participant_count:
        Minimum number of *viable* (non-SOURCE) participants required for
        degraded continuation.  Default: 1 (at least a primary must be viable).
    """

    def __init__(
        self,
        group: DeviceFormationGroup,
        *,
        unhealthy_threshold: float = _DEFAULT_UNHEALTHY_THRESHOLD,
        degraded_threshold: float = _DEFAULT_DEGRADED_THRESHOLD,
        min_viable_participant_count: int = _DEFAULT_MIN_VIABLE_PARTICIPANTS,
    ) -> None:
        self._group = group
        self._unhealthy_threshold = unhealthy_threshold
        self._degraded_threshold = degraded_threshold
        self._min_viable_participant_count = min_viable_participant_count
        self._runtime_state: FormationRuntimeState = FormationRuntimeState.ACTIVE
        self._participant_statuses: Dict[str, FormationParticipantStatus] = {}
        self._formation_id: str = getattr(group, "formation_id", "") or ""

        # Seed participant statuses from the initial group
        self._seed_from_group(group)

    # ------------------------------------------------------------------
    # Public trigger points — main entry surface for callers
    # ------------------------------------------------------------------

    def on_participant_readiness_changed(
        self,
        device_id: str,
        new_state: FormationParticipantState,
        *,
        health_score: Optional[float] = None,
        reason: Optional[str] = None,
    ) -> FormationRuntimeDecision:
        """Trigger: a participant's readiness state has changed.

        Call this when a device transitions between ready, degraded, lost, or
        recovering states regardless of the trigger source (heartbeat, lifecycle
        event, policy evaluation, etc.).

        Parameters
        ----------
        device_id:
            Device whose readiness changed.
        new_state:
            The new :class:`FormationParticipantState`.
        health_score:
            Updated health score.  If None, the previous score is retained
            (or defaulted to ``1.0`` for READY, ``0.0`` for LOST).
        reason:
            Human-readable reason for the change.

        Returns
        -------
        FormationRuntimeDecision
        """
        try:
            effective_score = self._effective_score(new_state, health_score)
            self._update_participant(
                device_id, new_state, effective_score, reason or new_state.value
            )
            return self._evaluate_and_decide("readiness_changed")
        except Exception as exc:
            logger.warning(
                "on_participant_readiness_changed: unexpected error: %s", exc
            )
            return self._safe_noop_decision("readiness_changed")

    def on_participant_lost(
        self,
        device_id: str,
        *,
        reason: Optional[str] = None,
    ) -> FormationRuntimeDecision:
        """Trigger: a participant has been lost (disconnect / timeout).

        This is the primary hook for connection-loss events.  The coordinator
        marks the device LOST and immediately evaluates whether the formation
        can continue.

        Parameters
        ----------
        device_id:
            Device that was lost.
        reason:
            Optional human-readable reason.

        Returns
        -------
        FormationRuntimeDecision
        """
        try:
            self._update_participant(
                device_id,
                FormationParticipantState.LOST,
                0.0,
                reason or "participant_lost",
            )
            return self._evaluate_and_decide("participant_lost")
        except Exception as exc:
            logger.warning("on_participant_lost: unexpected error: %s", exc)
            return self._safe_noop_decision("participant_lost")

    def on_health_degraded(
        self,
        device_id: str,
        health_score: float,
        *,
        reason: Optional[str] = None,
    ) -> FormationRuntimeDecision:
        """Trigger: a participant's health score has fallen below a threshold.

        Call this when a health monitor detects that a device's score has
        dropped.  The coordinator classifies the score (degraded vs unhealthy)
        and evaluates whether the formation needs to react.

        Parameters
        ----------
        device_id:
            Device whose health degraded.
        health_score:
            Current health score in ``[0.0, 1.0]``.
        reason:
            Optional human-readable reason.

        Returns
        -------
        FormationRuntimeDecision
        """
        try:
            if health_score < self._unhealthy_threshold:
                new_state = FormationParticipantState.LOST
            elif health_score < self._degraded_threshold:
                new_state = FormationParticipantState.DEGRADED
            else:
                new_state = FormationParticipantState.READY

            self._update_participant(
                device_id, new_state, health_score, reason or "health_degraded"
            )
            return self._evaluate_and_decide("health_degraded")
        except Exception as exc:
            logger.warning("on_health_degraded: unexpected error: %s", exc)
            return self._safe_noop_decision("health_degraded")

    def on_recovery_available(
        self,
        device_id: str,
        *,
        health_score: float = 1.0,
        reason: Optional[str] = None,
    ) -> FormationRuntimeDecision:
        """Trigger: a previously-lost participant signals re-availability.

        Use this when a device that was marked LOST reconnects or its health
        score recovers above threshold.  The coordinator transitions it to
        RECOVERING and evaluates whether the formation can be promoted out of
        a degraded or terminated state.

        Parameters
        ----------
        device_id:
            Device that is now available for recovery.
        health_score:
            Current health score.  Default: 1.0.
        reason:
            Optional human-readable reason.

        Returns
        -------
        FormationRuntimeDecision
        """
        try:
            self._update_participant(
                device_id,
                FormationParticipantState.RECOVERING,
                health_score,
                reason or "recovery_available",
            )

            # If the formation was terminated and a primary candidate is recovering
            # we attempt to promote it back to active
            if self._runtime_state == FormationRuntimeState.TERMINATED:
                decision = self._evaluate_and_decide("recovery_available")
                if decision.continuation_viable:
                    # Confirm recovery — mark participant READY
                    self._update_participant(
                        device_id,
                        FormationParticipantState.READY,
                        health_score,
                        "recovery_confirmed",
                    )
                    self._runtime_state = FormationRuntimeState.RECOVERING
                return decision

            return self._evaluate_and_decide("recovery_available")
        except Exception as exc:
            logger.warning("on_recovery_available: unexpected error: %s", exc)
            return self._safe_noop_decision("recovery_available")

    def evaluate_continuation(self) -> FormationRuntimeDecision:
        """Evaluate the current formation state and return a decision.

        Call this at any time to get the coordinator's current assessment of
        the formation without triggering a state change.

        Returns
        -------
        FormationRuntimeDecision
        """
        try:
            return self._evaluate_and_decide("evaluate_continuation")
        except Exception as exc:
            logger.warning("evaluate_continuation: unexpected error: %s", exc)
            return self._safe_noop_decision("evaluate_continuation")

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------

    @property
    def runtime_state(self) -> FormationRuntimeState:
        """Current :class:`FormationRuntimeState`."""
        return self._runtime_state

    @property
    def current_group(self) -> DeviceFormationGroup:
        """Current (possibly reshaped) :class:`~.formation_group.DeviceFormationGroup`."""
        return self._group

    def get_participant_status(
        self, device_id: str
    ) -> Optional[FormationParticipantStatus]:
        """Return the :class:`FormationParticipantStatus` for a device, or None."""
        return self._participant_statuses.get(device_id)

    def snapshot(self) -> FormationRuntimeSnapshot:
        """Return a serialisable snapshot of current runtime state."""
        return FormationRuntimeSnapshot(
            formation_id=self._formation_id,
            runtime_state=self._runtime_state,
            participant_statuses=dict(self._participant_statuses),
            snapshot_ts=time.time(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _seed_from_group(self, group: DeviceFormationGroup) -> None:
        """Initialise participant statuses from a formation group."""
        members = getattr(group, "members", []) or []
        for member in members:
            dev_id = getattr(member, "device_id", None)
            if not dev_id:
                continue
            role = getattr(member, "role", FormationRole.UNASSIGNED)
            role_str = role.value if hasattr(role, "value") else str(role)
            health = getattr(member, "health_score", 1.0) or 1.0
            self._participant_statuses[dev_id] = FormationParticipantStatus(
                device_id=dev_id,
                state=FormationParticipantState.READY,
                role=role_str,
                health_score=health,
            )

    def _update_participant(
        self,
        device_id: str,
        state: FormationParticipantState,
        health_score: float,
        reason: str,
    ) -> None:
        """Update (or create) a participant status record."""
        existing = self._participant_statuses.get(device_id)
        role_str = existing.role if existing is not None else "unassigned"
        # Try to derive role from current group if not already tracked
        if existing is None:
            members = getattr(self._group, "members", []) or []
            for m in members:
                if getattr(m, "device_id", None) == device_id:
                    r = getattr(m, "role", FormationRole.UNASSIGNED)
                    role_str = r.value if hasattr(r, "value") else str(r)
                    break
        self._participant_statuses[device_id] = FormationParticipantStatus(
            device_id=device_id,
            state=state,
            role=role_str,
            health_score=health_score,
            last_update_ts=time.time(),
            reason=reason,
        )
        logger.debug(
            "FormationRuntimeCoordinator: %s → state=%s score=%.2f reason=%s",
            device_id,
            state.value,
            health_score,
            reason,
        )

    def _effective_score(
        self,
        state: FormationParticipantState,
        explicit_score: Optional[float],
    ) -> float:
        """Return an appropriate health score for a state transition."""
        if explicit_score is not None:
            return explicit_score
        if state == FormationParticipantState.READY:
            return 1.0
        if state == FormationParticipantState.LOST:
            return 0.0
        if state == FormationParticipantState.DEGRADED:
            return (self._unhealthy_threshold + self._degraded_threshold) / 2.0
        if state == FormationParticipantState.RECOVERING:
            return self._degraded_threshold
        return 1.0

    def _evaluate_and_decide(
        self, trigger_event: str
    ) -> FormationRuntimeDecision:
        """Core evaluation: inspect participant states and produce a decision."""
        source_id = getattr(self._group, "source_device_id", None)
        members = getattr(self._group, "members", []) or []

        viable_primaries: List[str] = []
        viable_fallbacks: List[str] = []
        lost_ids: List[str] = []
        degraded_ids: List[str] = []
        recovering_ids: List[str] = []

        for member in members:
            dev_id = getattr(member, "device_id", None)
            if not dev_id:
                continue
            role = getattr(member, "role", None)
            status = self._participant_statuses.get(dev_id)
            state = status.state if status else FormationParticipantState.READY

            if state == FormationParticipantState.LOST:
                lost_ids.append(dev_id)
            elif state == FormationParticipantState.DEGRADED:
                degraded_ids.append(dev_id)
            elif state == FormationParticipantState.RECOVERING:
                recovering_ids.append(dev_id)

            if role == FormationRole.PRIMARY_EXECUTION and state != FormationParticipantState.LOST:
                viable_primaries.append(dev_id)
            elif role == FormationRole.FALLBACK and state not in (
                FormationParticipantState.LOST,
            ):
                viable_fallbacks.append(dev_id)

        actions: List[FormationRecoveryAction] = []
        new_group: Optional[DeviceFormationGroup] = None

        # Decide what to do
        if not lost_ids and not degraded_ids and not recovering_ids:
            # All healthy — nominal
            self._runtime_state = FormationRuntimeState.ACTIVE
            return FormationRuntimeDecision(
                formation_id=self._formation_id,
                runtime_state=FormationRuntimeState.ACTIVE,
                recommended_actions=[
                    FormationRecoveryAction(RecoveryActionType.KEEP, reason="all participants healthy")
                ],
                continuation_viable=True,
                reason="all formation participants are healthy",
                trigger_event=trigger_event,
            )

        # Build health map for the rebalance engine
        health_map = self._build_health_map()

        if not viable_primaries:
            # No viable primary — try to promote a fallback
            if viable_fallbacks:
                best_fallback = self._pick_best_viable_fallback(viable_fallbacks)
                actions.append(
                    FormationRecoveryAction(
                        RecoveryActionType.PROMOTE_FALLBACK,
                        affected_device_id=best_fallback,
                        reason=f"primary not viable; promote fallback {best_fallback}",
                    )
                )
                new_group = self._reshape_with_engine(health_map)
                self._runtime_state = FormationRuntimeState.RESHAPING
                continuation_viable = True
                reason = f"primary lost; reshaping — promoting fallback {best_fallback}"
            else:
                # No fallback available — check if recovering participants can help
                if recovering_ids:
                    actions.append(
                        FormationRecoveryAction(
                            RecoveryActionType.REQUEST_RECOVERY,
                            affected_device_id=recovering_ids[0],
                            reason="no viable primary; recovery candidate pending",
                        )
                    )
                    self._runtime_state = FormationRuntimeState.RECOVERING
                    continuation_viable = False
                    reason = "no viable primary or fallback; awaiting recovery"
                else:
                    actions.append(
                        FormationRecoveryAction(
                            RecoveryActionType.TERMINATE,
                            reason="no viable primary or fallback; formation cannot continue",
                        )
                    )
                    self._runtime_state = FormationRuntimeState.TERMINATED
                    continuation_viable = False
                    reason = "formation terminated — no viable primary or fallback"
        elif lost_ids:
            # Primary is viable but some participants are lost — remove them
            for dev_id in lost_ids:
                if dev_id != source_id:  # never remove SOURCE
                    actions.append(
                        FormationRecoveryAction(
                            RecoveryActionType.REMOVE_PARTICIPANT,
                            affected_device_id=dev_id,
                            reason=f"participant {dev_id} is lost",
                        )
                    )
            new_group = self._reshape_with_engine(health_map)

            viable_non_source = sum(
                1
                for m in members
                if getattr(m, "device_id", None) not in lost_ids
                and getattr(m, "device_id", None) != source_id
            )
            if viable_non_source >= self._min_viable_participant_count:
                actions.append(
                    FormationRecoveryAction(
                        RecoveryActionType.CONTINUE_DEGRADED,
                        reason=f"{len(lost_ids)} participant(s) lost; degraded continuation viable",
                    )
                )
                self._runtime_state = FormationRuntimeState.DEGRADED_CONTINUATION
                continuation_viable = True
                reason = (
                    f"degraded continuation — {len(lost_ids)} participant(s) removed, "
                    f"{viable_non_source} viable"
                )
            else:
                actions.append(
                    FormationRecoveryAction(
                        RecoveryActionType.RESHAPE,
                        reason="participant loss reduces viable count below minimum; reshape required",
                    )
                )
                self._runtime_state = FormationRuntimeState.RESHAPING
                continuation_viable = True
                reason = "reshaping — viable participant count at minimum"
        elif degraded_ids:
            # Primary viable; some participants degraded
            actions.append(
                FormationRecoveryAction(
                    RecoveryActionType.CONTINUE_DEGRADED,
                    reason=f"{len(degraded_ids)} participant(s) degraded; viable for now",
                )
            )
            if degraded_ids:
                actions.append(
                    FormationRecoveryAction(
                        RecoveryActionType.RESHAPE,
                        reason="degraded participants detected; consider reshaping",
                    )
                )
            self._runtime_state = FormationRuntimeState.DEGRADED
            continuation_viable = True
            reason = f"degraded continuation — {len(degraded_ids)} participant(s) impaired"
        else:
            # Only recovering participants — transition out of terminated/recovering
            self._runtime_state = FormationRuntimeState.RECOVERING
            actions.append(
                FormationRecoveryAction(
                    RecoveryActionType.REQUEST_RECOVERY,
                    reason="participants recovering; awaiting readiness confirmation",
                )
            )
            continuation_viable = False
            reason = "recovery in progress; awaiting participant confirmation"

        logger.info(
            "FormationRuntimeCoordinator(%s): %s → %s (viable=%s, trigger=%s)",
            self._formation_id,
            trigger_event,
            self._runtime_state.value,
            continuation_viable,
            trigger_event,
        )

        return FormationRuntimeDecision(
            formation_id=self._formation_id,
            runtime_state=self._runtime_state,
            recommended_actions=actions,
            new_group=new_group,
            continuation_viable=continuation_viable,
            reason=reason,
            trigger_event=trigger_event,
        )

    def _build_health_map(self) -> Dict[str, Any]:
        """Build a health map compatible with :class:`~.formation_rebalance_engine.FormationHealthSignal`."""
        try:
            from .formation_rebalance_engine import FormationHealthSignal

            hmap: Dict[str, Any] = {}
            for dev_id, status in self._participant_statuses.items():
                hmap[dev_id] = FormationHealthSignal(
                    device_id=dev_id,
                    health_score=status.health_score,
                    is_reachable=(
                        status.state
                        not in (
                            FormationParticipantState.LOST,
                        )
                    ),
                    reason=status.reason,
                )
            return hmap
        except Exception as exc:
            logger.debug("_build_health_map: %s", exc)
            return {}

    def _reshape_with_engine(
        self, health_map: Dict[str, Any]
    ) -> Optional[DeviceFormationGroup]:
        """Apply a full rebalance pass via :class:`~.formation_rebalance_engine.FormationRebalanceEngine`."""
        try:
            from .formation_rebalance_engine import apply_rebalance

            new_group, decision = apply_rebalance(self._group, health_map)
            if decision.rebalance_needed:
                self._group = new_group
                logger.info(
                    "FormationRuntimeCoordinator(%s): reshape applied — %s",
                    self._formation_id,
                    decision.reason,
                )
            return new_group
        except Exception as exc:
            logger.warning("_reshape_with_engine: %s", exc)
            return None

    def _pick_best_viable_fallback(self, viable_fallbacks: List[str]) -> str:
        """Return the fallback device with the highest health score."""
        best = viable_fallbacks[0]
        best_score = 0.0
        for dev_id in viable_fallbacks:
            status = self._participant_statuses.get(dev_id)
            score = status.health_score if status else 0.0
            if score > best_score:
                best_score = score
                best = dev_id
        return best

    def _safe_noop_decision(self, trigger_event: str) -> FormationRuntimeDecision:
        """Return a safe no-op decision when an error occurs."""
        return FormationRuntimeDecision(
            formation_id=self._formation_id,
            runtime_state=self._runtime_state,
            recommended_actions=[
                FormationRecoveryAction(
                    RecoveryActionType.KEEP,
                    reason="safe no-op: error during evaluation",
                )
            ],
            continuation_viable=True,
            reason="no-op decision due to evaluation error",
            trigger_event=trigger_event,
        )


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def make_formation_runtime_coordinator(
    group: Optional[DeviceFormationGroup] = None,
    *,
    unhealthy_threshold: float = _DEFAULT_UNHEALTHY_THRESHOLD,
    degraded_threshold: float = _DEFAULT_DEGRADED_THRESHOLD,
    min_viable_participant_count: int = _DEFAULT_MIN_VIABLE_PARTICIPANTS,
) -> FormationRuntimeCoordinator:
    """Create a :class:`FormationRuntimeCoordinator` from a formation group.

    Parameters
    ----------
    group:
        Formation group to coordinate.  Falls back to
        :data:`~.formation_group.EMPTY_FORMATION_GROUP` when ``None``.
    unhealthy_threshold:
        Health score below which a device is unhealthy.
    degraded_threshold:
        Health score below which (but above unhealthy) a device is degraded.
    min_viable_participant_count:
        Minimum number of viable non-SOURCE participants for degraded
        continuation.

    Returns
    -------
    FormationRuntimeCoordinator
        Never raises.
    """
    try:
        return FormationRuntimeCoordinator(
            group or EMPTY_FORMATION_GROUP,
            unhealthy_threshold=unhealthy_threshold,
            degraded_threshold=degraded_threshold,
            min_viable_participant_count=min_viable_participant_count,
        )
    except Exception as exc:
        logger.warning("make_formation_runtime_coordinator: error: %s", exc)
        return FormationRuntimeCoordinator(EMPTY_FORMATION_GROUP)
