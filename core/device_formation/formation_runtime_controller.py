#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/device_formation/formation_runtime_controller.py
=======================================================
Formation Runtime Controller — PR-2 (Formation Rebalance and Runtime
Recovery Hooks).

Background
----------
The existing :mod:`formation_rebalance_engine` provides a **stateless**
engine that evaluates a health-signal snapshot and returns a reshaping
decision.  It closes the static-resolution gap in ``formation_resolver.py``
but stops short of providing **trigger-point-driven** recovery semantics:
there are no named trigger hooks for readiness changes, participant loss,
role instability, or partial-formation degradation.

This module closes that remaining gap by providing:

1. :class:`FormationTriggerType` — named trigger categories that the runtime
   raises to signal formation-relevant state changes.

2. :class:`FormationTriggerEvent` — a structured event carrying the trigger
   type, affected device, and contextual metadata (session, formation,
   health, reason).

3. :class:`DegradedContinuationDecision` — the set of decisions that the
   controller can produce: continue degraded, reshape and continue, await
   recovery, or abort.

4. :class:`FormationRecoveryPlan` — the complete recovery output, containing
   the continuation decision, a (possibly reshaped) formation, a policy, and
   rich diagnostics.

5. :class:`FormationRuntimeController` — processes trigger events and returns
   :class:`FormationRecoveryPlan` objects.  Internally delegates all
   reshaping to :class:`~.formation_rebalance_engine.FormationRebalanceEngine`
   so that recovery policy stays consistent with health-evaluation policy.

Trigger semantics
-----------------
+----------------------------+-----------------------------------------------+
| Trigger type               | Controller action                             |
+============================+===============================================+
| PARTICIPANT_LOST           | SOURCE → AWAIT_RECOVERY.                      |
|                            | PRIMARY + fallback available → RESHAPE.       |
|                            | PRIMARY + no fallback → ABORT.                |
|                            | Non-critical (SUPPORT/RELAY/OBSERVER) →       |
|                            |   CONTINUE_DEGRADED.                          |
+----------------------------+-----------------------------------------------+
| READINESS_CHANGED          | Treated as a low-health signal (score = 0.0,  |
|                            | is_reachable = False).  Same role-routing as  |
|                            | PARTICIPANT_LOST.                             |
+----------------------------+-----------------------------------------------+
| HEALTH_DEGRADED            | Score below unhealthy threshold → same as     |
|                            | PARTICIPANT_LOST role-routing.                |
|                            | Score in degraded band → CONTINUE_DEGRADED    |
|                            |   with WARN annotation.                       |
+----------------------------+-----------------------------------------------+
| ROLE_INSTABILITY           | Re-evaluates whether the device can continue  |
|                            | in its current role.  Follows PRIMARY_LOST    |
|                            | or SUPPORT_LOST routing depending on role.    |
+----------------------------+-----------------------------------------------+
| PARTICIPANT_JOINED         | Returns current formation unchanged with      |
|                            | CONTINUE_DEGRADED or RESHAPE hint if the      |
|                            | group was previously degraded.                |
+----------------------------+-----------------------------------------------+

Design principles
-----------------
- **Additive only** — does not modify ``formation_resolver.py``,
  ``formation_rebalance_engine.py``, or any other existing module.
- **Delegates reshaping** — the controller never duplicates rebalance logic;
  it always calls :func:`~.formation_rebalance_engine.apply_rebalance` or
  :func:`~.formation_rebalance_engine.maybe_promote_fallback`.
- **Graceful degradation** — every public method returns a valid
  :class:`FormationRecoveryPlan` even when inputs are partial or malformed.
- **Stateless** — the controller does not store formation state; callers are
  responsible for updating their formation reference from the plan.

Sentinels
---------
:data:`FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY`
    Affirms this module is the canonical formation trigger and recovery layer.
:data:`FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL`
    Affirms this module closes the PR-2 trigger-point gap.
:data:`SOURCE_LOSS_REQUIRES_AWAIT_RECOVERY_POLICY`
    Affirms that loss of the SOURCE device triggers AWAIT_RECOVERY, not ABORT.
:data:`PRIMARY_LOSS_WITH_FALLBACK_TRIGGERS_RESHAPE_POLICY`
    Affirms that loss of the PRIMARY device when a FALLBACK exists triggers
    RESHAPE_AND_CONTINUE rather than ABORT.
:data:`NON_CRITICAL_LOSS_CONTINUES_DEGRADED_POLICY`
    Affirms that loss of SUPPORT/RELAY/OBSERVER members triggers
    CONTINUE_DEGRADED, not ABORT.

Public API
----------
Enums:
    :class:`FormationTriggerType`
    :class:`DegradedContinuationDecision`

Classes:
    :class:`FormationTriggerEvent`
    :class:`FormationRecoveryPlan`
    :class:`FormationRuntimeController`

Functions:
    :func:`on_participant_lost`
    :func:`on_readiness_changed`
    :func:`on_health_degraded`
    :func:`on_role_instability`
    :func:`on_participant_joined`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .formation_group import DeviceFormationGroup, EMPTY_FORMATION_GROUP
from .formation_policy import FormationPolicy, DEFAULT_LOCAL_FORMATION_POLICY
from .formation_role import FormationMember, FormationRole

__all__ = [
    # Sentinels
    "FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY",
    "FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL",
    "SOURCE_LOSS_REQUIRES_AWAIT_RECOVERY_POLICY",
    "PRIMARY_LOSS_WITH_FALLBACK_TRIGGERS_RESHAPE_POLICY",
    "NON_CRITICAL_LOSS_CONTINUES_DEGRADED_POLICY",
    # Enums
    "FormationTriggerType",
    "DegradedContinuationDecision",
    # Classes
    "FormationTriggerEvent",
    "FormationRecoveryPlan",
    "FormationRuntimeController",
    # Module-level convenience functions
    "on_participant_lost",
    "on_readiness_changed",
    "on_health_degraded",
    "on_role_instability",
    "on_participant_joined",
]

logger = logging.getLogger("Galaxy.DeviceFormation.RuntimeController")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY: str = (
    "FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY: "
    "core/device_formation/formation_runtime_controller.py is the canonical "
    "formation trigger-point and runtime recovery hook layer for Galaxy."
)

FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL: str = (
    "FORMATION_RUNTIME_CONTROLLER_PR2: "
    "This module implements PR-2 (Formation Rebalance and Runtime Recovery Hooks). "
    "It provides named trigger hooks and recovery plan semantics that were deferred "
    "from formation_rebalance_engine.py (stateless evaluation) and "
    "multi_device_runtime_harness.py (integration wiring)."
)

SOURCE_LOSS_REQUIRES_AWAIT_RECOVERY_POLICY: str = (
    "RECOVERY_POLICY: Loss of the SOURCE device always produces "
    "DegradedContinuationDecision.AWAIT_RECOVERY.  The SOURCE member is the "
    "origin of the formation and its loss is not a locally recoverable condition."
)

PRIMARY_LOSS_WITH_FALLBACK_TRIGGERS_RESHAPE_POLICY: str = (
    "RECOVERY_POLICY: Loss of the PRIMARY_EXECUTION device when at least one "
    "FALLBACK device is present triggers DegradedContinuationDecision.RESHAPE_AND_CONTINUE. "
    "The best FALLBACK is promoted to PRIMARY_EXECUTION."
)

NON_CRITICAL_LOSS_CONTINUES_DEGRADED_POLICY: str = (
    "RECOVERY_POLICY: Loss of a SUPPORT, RELAY, or OBSERVER member produces "
    "DegradedContinuationDecision.CONTINUE_DEGRADED.  These roles are not "
    "execution-critical and their absence does not prevent task completion."
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FormationTriggerType(str, Enum):
    """Named trigger types that the runtime raises to signal formation-relevant
    state changes."""

    PARTICIPANT_LOST = "participant_lost"
    """A device has disconnected or become permanently unreachable."""

    READINESS_CHANGED = "readiness_changed"
    """A device's readiness state changed (e.g. became unready or offline)."""

    HEALTH_DEGRADED = "health_degraded"
    """A device's health score dropped below a threshold."""

    ROLE_INSTABILITY = "role_instability"
    """A device can no longer reliably fulfil its assigned formation role."""

    PARTICIPANT_JOINED = "participant_joined"
    """A new device has become available and may join the formation."""


class DegradedContinuationDecision(str, Enum):
    """Decision produced by the controller for a given formation trigger."""

    CONTINUE_DEGRADED = "continue_degraded"
    """Proceed with the remaining viable participants.  Non-critical members
    may have been removed but the formation can still complete its task."""

    RESHAPE_AND_CONTINUE = "reshape_and_continue"
    """Reshape the formation (e.g. promote a fallback) and continue.  The
    ``reshaped_formation`` field of :class:`FormationRecoveryPlan` contains
    the new formation."""

    AWAIT_RECOVERY = "await_recovery"
    """Pause execution and wait for a recovery signal.  Produced when the
    SOURCE device is lost or when no viable reshaping path exists."""

    ABORT = "abort"
    """Abort the formation.  Produced when no viable participants remain after
    removing the lost device."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FormationTriggerEvent:
    """A structured event that signals a formation-relevant runtime change.

    Attributes
    ----------
    trigger_type:
        The kind of trigger being raised.
    device_id:
        The device this event concerns.
    formation_id:
        Optional formation ID this event is scoped to.
    session_id:
        Optional mesh session ID this event is scoped to.
    health_score:
        Optional health score at the time of the trigger.
    is_reachable:
        Whether the device is still reachable at event time.
    reason:
        Optional human-readable description of the trigger cause.
    metadata:
        Arbitrary additional context from the caller.
    """

    trigger_type: FormationTriggerType
    device_id: str
    formation_id: Optional[str] = None
    session_id: Optional[str] = None
    health_score: Optional[float] = None
    is_reachable: bool = True
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_type": self.trigger_type.value,
            "device_id": self.device_id,
            "formation_id": self.formation_id,
            "session_id": self.session_id,
            "health_score": self.health_score,
            "is_reachable": self.is_reachable,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass
class FormationRecoveryPlan:
    """Recovery plan produced by :class:`FormationRuntimeController`.

    Attributes
    ----------
    continuation_decision:
        What the formation should do next.
    trigger_event:
        The event that produced this plan.
    reshaped_formation:
        The new formation after reshaping, or the original formation if no
        reshaping was needed or possible.  Never ``None`` — falls back to
        :data:`~.formation_group.EMPTY_FORMATION_GROUP`.
    reshaping_policy:
        The formation policy aligned with the (possibly reshaped) formation.
    affected_device_ids:
        IDs of devices that were removed, promoted, or demoted.
    is_degraded:
        ``True`` if the resulting formation is operating below full capacity.
    reason:
        Human-readable explanation of the recovery decision.
    recovery_hints:
        Structured hints for downstream consumers (e.g. mesh session coordinator,
        task dispatcher).
    rebalance_decision:
        The underlying :class:`~.formation_rebalance_engine.RebalanceDecision`
        if a rebalance was performed; ``None`` otherwise.
    """

    continuation_decision: DegradedContinuationDecision
    trigger_event: FormationTriggerEvent
    reshaped_formation: DeviceFormationGroup = field(
        default_factory=lambda: EMPTY_FORMATION_GROUP
    )
    reshaping_policy: FormationPolicy = field(
        default_factory=lambda: DEFAULT_LOCAL_FORMATION_POLICY
    )
    affected_device_ids: List[str] = field(default_factory=list)
    is_degraded: bool = False
    reason: str = ""
    recovery_hints: Dict[str, Any] = field(default_factory=dict)
    rebalance_decision: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "continuation_decision": self.continuation_decision.value,
            "trigger_event": self.trigger_event.to_dict(),
            "formation_id": getattr(self.reshaped_formation, "formation_id", None),
            "affected_device_ids": list(self.affected_device_ids),
            "is_degraded": self.is_degraded,
            "reason": self.reason,
            "recovery_hints": dict(self.recovery_hints),
        }


# ---------------------------------------------------------------------------
# FormationRuntimeController
# ---------------------------------------------------------------------------


class FormationRuntimeController:
    """Processes formation trigger events and produces recovery plans.

    This controller provides the trigger-point layer that connects runtime
    state changes (disconnects, readiness changes, health events) to the
    formation reshaping / recovery decision layer.

    It delegates all reshaping work to
    :class:`~.formation_rebalance_engine.FormationRebalanceEngine` so that
    recovery decisions remain consistent with the health-evaluation policy.

    Usage::

        controller = FormationRuntimeController()

        # Device disconnects mid-session
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id="phone_01",
            session_id="mesh-session-abc",
        )
        plan = controller.process_trigger(event, current_formation)

        if plan.continuation_decision == DegradedContinuationDecision.RESHAPE_AND_CONTINUE:
            current_formation = plan.reshaped_formation

    Parameters
    ----------
    unhealthy_threshold:
        Passed to the internal :class:`~.formation_rebalance_engine.FormationRebalanceEngine`.
    degraded_threshold:
        Passed to the internal :class:`~.formation_rebalance_engine.FormationRebalanceEngine`.
    """

    def __init__(
        self,
        unhealthy_threshold: float = 0.3,
        degraded_threshold: float = 0.6,
    ) -> None:
        self._unhealthy_threshold = unhealthy_threshold
        self._degraded_threshold = degraded_threshold

    # ------------------------------------------------------------------
    # Primary public entry point
    # ------------------------------------------------------------------

    def process_trigger(
        self,
        event: FormationTriggerEvent,
        formation: Optional[DeviceFormationGroup] = None,
    ) -> FormationRecoveryPlan:
        """Process a formation trigger event and return a recovery plan.

        Dispatches to the appropriate named hook based on
        ``event.trigger_type``.

        Parameters
        ----------
        event:
            The trigger event to process.
        formation:
            The current :class:`~.formation_group.DeviceFormationGroup`.
            If ``None``, uses :data:`~.formation_group.EMPTY_FORMATION_GROUP`.

        Returns
        -------
        FormationRecoveryPlan
            Never raises.
        """
        try:
            group = formation if formation is not None else EMPTY_FORMATION_GROUP
            t = event.trigger_type

            if t == FormationTriggerType.PARTICIPANT_LOST:
                return self.on_participant_lost(event, group)
            if t == FormationTriggerType.READINESS_CHANGED:
                return self.on_readiness_changed(event, group)
            if t == FormationTriggerType.HEALTH_DEGRADED:
                return self.on_health_degraded(event, group)
            if t == FormationTriggerType.ROLE_INSTABILITY:
                return self.on_role_instability(event, group)
            if t == FormationTriggerType.PARTICIPANT_JOINED:
                return self.on_participant_joined(event, group)

            # Unknown trigger type — safe no-op
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=group,
                reason=f"unknown trigger type: {t!r}",
                is_degraded=False,
            )

        except Exception as exc:
            logger.warning(
                "FormationRuntimeController.process_trigger: unexpected error: %s", exc
            )
            safe_group = formation if formation is not None else EMPTY_FORMATION_GROUP
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=safe_group,
                reason=f"controller error: {exc}",
                is_degraded=True,
            )

    # ------------------------------------------------------------------
    # Named trigger hooks
    # ------------------------------------------------------------------

    def on_participant_lost(
        self,
        event: FormationTriggerEvent,
        formation: Optional[DeviceFormationGroup] = None,
    ) -> FormationRecoveryPlan:
        """Hook: a device has been lost (disconnected or permanently unreachable).

        Role-based routing:

        - **SOURCE lost** → :attr:`~DegradedContinuationDecision.AWAIT_RECOVERY`
        - **PRIMARY lost, fallback available** → :attr:`~DegradedContinuationDecision.RESHAPE_AND_CONTINUE`
        - **PRIMARY lost, no fallback** → :attr:`~DegradedContinuationDecision.ABORT`
        - **FALLBACK lost** → :attr:`~DegradedContinuationDecision.CONTINUE_DEGRADED`
        - **SUPPORT / RELAY / OBSERVER lost** → :attr:`~DegradedContinuationDecision.CONTINUE_DEGRADED`
        - **No formation** → :attr:`~DegradedContinuationDecision.ABORT`

        Parameters
        ----------
        event:
            Trigger event with ``trigger_type == PARTICIPANT_LOST``.
        formation:
            Current formation group.

        Returns
        -------
        FormationRecoveryPlan
        """
        try:
            group = formation if formation is not None else EMPTY_FORMATION_GROUP
            lost_id = event.device_id

            role = self._find_role(group, lost_id)

            if role is None:
                # Device not in formation — no-op
                return FormationRecoveryPlan(
                    continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                    trigger_event=event,
                    reshaped_formation=group,
                    reason=f"device {lost_id!r} not found in formation",
                    is_degraded=False,
                )

            if role == FormationRole.SOURCE:
                return FormationRecoveryPlan(
                    continuation_decision=DegradedContinuationDecision.AWAIT_RECOVERY,
                    trigger_event=event,
                    reshaped_formation=group,
                    affected_device_ids=[lost_id],
                    is_degraded=True,
                    reason=(
                        f"SOURCE device {lost_id!r} lost; formation cannot continue "
                        "without origin — awaiting recovery"
                    ),
                    recovery_hints={"source_lost": True, "device_id": lost_id},
                )

            if role == FormationRole.PRIMARY_EXECUTION:
                return self._handle_primary_loss(event, group, lost_id)

            # Non-critical roles: FALLBACK, SUPPORT, RELAY, OBSERVER, MERGE_OWNER, UNASSIGNED
            new_group, policy, rebalance_dec = self._remove_and_rebalance(group, lost_id)
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=new_group,
                reshaping_policy=policy,
                affected_device_ids=[lost_id],
                is_degraded=True,
                reason=(
                    f"non-critical member {lost_id!r} (role={role.value}) removed; "
                    "formation continues degraded"
                ),
                rebalance_decision=rebalance_dec,
                recovery_hints={"removed_role": role.value, "device_id": lost_id},
            )

        except Exception as exc:
            logger.warning("on_participant_lost: unexpected error: %s", exc)
            safe = formation if formation is not None else EMPTY_FORMATION_GROUP
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=safe,
                reason=f"on_participant_lost error: {exc}",
                is_degraded=True,
            )

    def on_readiness_changed(
        self,
        event: FormationTriggerEvent,
        formation: Optional[DeviceFormationGroup] = None,
    ) -> FormationRecoveryPlan:
        """Hook: a device's readiness state changed (e.g. became unready).

        Treats an unready device as a health score of ``0.0`` with
        ``is_reachable=False`` and delegates to
        :meth:`on_participant_lost` semantics.

        If the device is becoming *ready* (``event.is_reachable=True`` and
        ``event.health_score >= degraded_threshold``), returns
        :attr:`~DegradedContinuationDecision.CONTINUE_DEGRADED` with no
        reshaping (caller should decide whether to admit the device).

        Parameters
        ----------
        event:
            Trigger event with ``trigger_type == READINESS_CHANGED``.
        formation:
            Current formation group.

        Returns
        -------
        FormationRecoveryPlan
        """
        try:
            group = formation if formation is not None else EMPTY_FORMATION_GROUP
            score = event.health_score
            reachable = event.is_reachable

            # Device is becoming ready — no recovery needed
            if reachable and score is not None and score >= self._degraded_threshold:
                return FormationRecoveryPlan(
                    continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                    trigger_event=event,
                    reshaped_formation=group,
                    reason=(
                        f"device {event.device_id!r} readiness improved "
                        f"(score={score:.2f}); no recovery action required"
                    ),
                    is_degraded=False,
                    recovery_hints={"readiness_improved": True},
                )

            # Device is becoming unready — treat as participant lost
            lost_event = FormationTriggerEvent(
                trigger_type=FormationTriggerType.PARTICIPANT_LOST,
                device_id=event.device_id,
                formation_id=event.formation_id,
                session_id=event.session_id,
                health_score=0.0,
                is_reachable=False,
                reason=event.reason or "readiness_changed: device unready",
                metadata=dict(event.metadata),
            )
            plan = self.on_participant_lost(lost_event, group)
            # Preserve the original trigger event for traceability
            return FormationRecoveryPlan(
                continuation_decision=plan.continuation_decision,
                trigger_event=event,
                reshaped_formation=plan.reshaped_formation,
                reshaping_policy=plan.reshaping_policy,
                affected_device_ids=plan.affected_device_ids,
                is_degraded=plan.is_degraded,
                reason=f"readiness_changed → {plan.reason}",
                recovery_hints=plan.recovery_hints,
                rebalance_decision=plan.rebalance_decision,
            )

        except Exception as exc:
            logger.warning("on_readiness_changed: unexpected error: %s", exc)
            safe = formation if formation is not None else EMPTY_FORMATION_GROUP
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=safe,
                reason=f"on_readiness_changed error: {exc}",
                is_degraded=True,
            )

    def on_health_degraded(
        self,
        event: FormationTriggerEvent,
        formation: Optional[DeviceFormationGroup] = None,
    ) -> FormationRecoveryPlan:
        """Hook: a device's health score has dropped below a threshold.

        Decision routing:

        - Score **below unhealthy_threshold** → treated as participant lost
          (delegates to :meth:`on_participant_lost`).
        - Score **in the degraded band** [unhealthy, degraded) → returns
          :attr:`~DegradedContinuationDecision.CONTINUE_DEGRADED` with a WARN
          annotation and no reshaping.
        - Score **above degraded_threshold** → treated as a no-op (device
          recovered above the warn threshold).

        Parameters
        ----------
        event:
            Trigger event with ``trigger_type == HEALTH_DEGRADED``.
        formation:
            Current formation group.

        Returns
        -------
        FormationRecoveryPlan
        """
        try:
            group = formation if formation is not None else EMPTY_FORMATION_GROUP
            score = event.health_score if event.health_score is not None else 0.0

            if score >= self._degraded_threshold:
                # Score recovered above warn threshold — no action
                return FormationRecoveryPlan(
                    continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                    trigger_event=event,
                    reshaped_formation=group,
                    reason=(
                        f"device {event.device_id!r} health score {score:.2f} is "
                        f"above degraded threshold {self._degraded_threshold:.2f}; "
                        "no recovery action required"
                    ),
                    is_degraded=False,
                )

            if score >= self._unhealthy_threshold:
                # Degraded band — warn but keep
                return FormationRecoveryPlan(
                    continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                    trigger_event=event,
                    reshaped_formation=group,
                    affected_device_ids=[event.device_id],
                    is_degraded=True,
                    reason=(
                        f"device {event.device_id!r} health score {score:.2f} is "
                        f"in degraded band [{self._unhealthy_threshold:.2f}, "
                        f"{self._degraded_threshold:.2f}); "
                        "continuing with degraded participant"
                    ),
                    recovery_hints={
                        "degraded_device": event.device_id,
                        "health_score": score,
                    },
                )

            # Below unhealthy threshold — treat as lost
            lost_event = FormationTriggerEvent(
                trigger_type=FormationTriggerType.PARTICIPANT_LOST,
                device_id=event.device_id,
                formation_id=event.formation_id,
                session_id=event.session_id,
                health_score=score,
                is_reachable=event.is_reachable,
                reason=event.reason or f"health_degraded: score={score:.2f}",
                metadata=dict(event.metadata),
            )
            plan = self.on_participant_lost(lost_event, group)
            return FormationRecoveryPlan(
                continuation_decision=plan.continuation_decision,
                trigger_event=event,
                reshaped_formation=plan.reshaped_formation,
                reshaping_policy=plan.reshaping_policy,
                affected_device_ids=plan.affected_device_ids,
                is_degraded=plan.is_degraded,
                reason=f"health_degraded(score={score:.2f}) → {plan.reason}",
                recovery_hints=plan.recovery_hints,
                rebalance_decision=plan.rebalance_decision,
            )

        except Exception as exc:
            logger.warning("on_health_degraded: unexpected error: %s", exc)
            safe = formation if formation is not None else EMPTY_FORMATION_GROUP
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=safe,
                reason=f"on_health_degraded error: {exc}",
                is_degraded=True,
            )

    def on_role_instability(
        self,
        event: FormationTriggerEvent,
        formation: Optional[DeviceFormationGroup] = None,
    ) -> FormationRecoveryPlan:
        """Hook: a device can no longer reliably fulfil its assigned role.

        Re-evaluates the device as if it were partially healthy (score at
        the boundary of the degraded threshold) and delegates to the
        appropriate recovery path.

        For **SOURCE** instability: AWAIT_RECOVERY.
        For **PRIMARY** instability: RESHAPE if fallback available, else ABORT.
        For other roles: CONTINUE_DEGRADED after removing the device from the
        formation.

        Parameters
        ----------
        event:
            Trigger event with ``trigger_type == ROLE_INSTABILITY``.
        formation:
            Current formation group.

        Returns
        -------
        FormationRecoveryPlan
        """
        try:
            group = formation if formation is not None else EMPTY_FORMATION_GROUP
            dev_id = event.device_id
            role = self._find_role(group, dev_id)

            if role is None:
                return FormationRecoveryPlan(
                    continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                    trigger_event=event,
                    reshaped_formation=group,
                    reason=f"device {dev_id!r} not in formation; role instability ignored",
                    is_degraded=False,
                )

            # Treat role instability as the device having dropped to just below
            # the unhealthy threshold so that reshaping logic is invoked.
            lost_event = FormationTriggerEvent(
                trigger_type=FormationTriggerType.PARTICIPANT_LOST,
                device_id=dev_id,
                formation_id=event.formation_id,
                session_id=event.session_id,
                health_score=0.0,
                is_reachable=False,
                reason=event.reason or f"role_instability: device cannot fulfil {role.value!r}",
                metadata=dict(event.metadata),
            )
            plan = self.on_participant_lost(lost_event, group)
            return FormationRecoveryPlan(
                continuation_decision=plan.continuation_decision,
                trigger_event=event,
                reshaped_formation=plan.reshaped_formation,
                reshaping_policy=plan.reshaping_policy,
                affected_device_ids=plan.affected_device_ids,
                is_degraded=plan.is_degraded,
                reason=f"role_instability({role.value}) → {plan.reason}",
                recovery_hints={
                    **plan.recovery_hints,
                    "unstable_role": role.value,
                },
                rebalance_decision=plan.rebalance_decision,
            )

        except Exception as exc:
            logger.warning("on_role_instability: unexpected error: %s", exc)
            safe = formation if formation is not None else EMPTY_FORMATION_GROUP
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=safe,
                reason=f"on_role_instability error: {exc}",
                is_degraded=True,
            )

    def on_participant_joined(
        self,
        event: FormationTriggerEvent,
        formation: Optional[DeviceFormationGroup] = None,
    ) -> FormationRecoveryPlan:
        """Hook: a new device has become available.

        The controller does not automatically admit the new device into the
        formation — that decision belongs to the formation resolver.  Instead
        it returns a plan indicating whether the formation is currently
        degraded (in which case the caller may want to trigger re-resolution)
        or healthy (no action required).

        Parameters
        ----------
        event:
            Trigger event with ``trigger_type == PARTICIPANT_JOINED``.
        formation:
            Current formation group.

        Returns
        -------
        FormationRecoveryPlan
        """
        try:
            group = formation if formation is not None else EMPTY_FORMATION_GROUP
            primary_id = getattr(group, "primary_execution_device_id", None)
            fallback_ids = getattr(group, "fallback_device_ids", [])

            if primary_id is None:
                is_degraded = True
                reason = (
                    f"new participant {event.device_id!r} available; "
                    "formation has no primary — re-resolution recommended"
                )
            elif not fallback_ids:
                is_degraded = True
                reason = (
                    f"new participant {event.device_id!r} available; "
                    "formation has no fallback — caller may admit as fallback"
                )
            else:
                is_degraded = False
                reason = (
                    f"new participant {event.device_id!r} available; "
                    "formation is healthy — no immediate action required"
                )

            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=group,
                is_degraded=is_degraded,
                reason=reason,
                recovery_hints={
                    "new_device_id": event.device_id,
                    "suggest_re_resolve": is_degraded,
                },
            )

        except Exception as exc:
            logger.warning("on_participant_joined: unexpected error: %s", exc)
            safe = formation if formation is not None else EMPTY_FORMATION_GROUP
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.CONTINUE_DEGRADED,
                trigger_event=event,
                reshaped_formation=safe,
                reason=f"on_participant_joined error: {exc}",
                is_degraded=True,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_role(
        self,
        group: DeviceFormationGroup,
        device_id: str,
    ) -> Optional[FormationRole]:
        """Return the :class:`FormationRole` of *device_id* in *group*, or None."""
        members = getattr(group, "members", [])
        for m in members:
            if getattr(m, "device_id", None) == device_id:
                return getattr(m, "role", None)
        return None

    def _handle_primary_loss(
        self,
        event: FormationTriggerEvent,
        group: DeviceFormationGroup,
        lost_id: str,
    ) -> FormationRecoveryPlan:
        """Handle the loss of a PRIMARY_EXECUTION device."""
        fallback_ids = getattr(group, "fallback_device_ids", [])

        if not fallback_ids:
            # No fallback available — abort
            # Still remove the primary from the formation for safety
            new_group, policy, rebalance_dec = self._remove_and_rebalance(group, lost_id)
            return FormationRecoveryPlan(
                continuation_decision=DegradedContinuationDecision.ABORT,
                trigger_event=event,
                reshaped_formation=new_group,
                reshaping_policy=policy,
                affected_device_ids=[lost_id],
                is_degraded=True,
                reason=(
                    f"PRIMARY device {lost_id!r} lost and no FALLBACK available; "
                    "formation cannot continue — aborting"
                ),
                rebalance_decision=rebalance_dec,
                recovery_hints={"primary_lost": True, "no_fallback": True},
            )

        # Promote the best fallback
        try:
            from .formation_rebalance_engine import (
                FormationHealthSignal,
                apply_rebalance,
            )
            health_map = {
                lost_id: FormationHealthSignal(
                    device_id=lost_id,
                    health_score=0.0,
                    is_reachable=False,
                    reason=event.reason or "participant_lost",
                )
            }
            new_group, rebalance_dec = apply_rebalance(group, health_map)
            policy = DEFAULT_LOCAL_FORMATION_POLICY
            promoted = list(getattr(rebalance_dec, "promoted_device_ids", []))
        except Exception as exc:
            logger.warning("_handle_primary_loss: rebalance error: %s", exc)
            new_group = group
            rebalance_dec = None
            promoted = []
            policy = DEFAULT_LOCAL_FORMATION_POLICY

        new_primary = getattr(new_group, "primary_execution_device_id", None)
        return FormationRecoveryPlan(
            continuation_decision=DegradedContinuationDecision.RESHAPE_AND_CONTINUE,
            trigger_event=event,
            reshaped_formation=new_group,
            reshaping_policy=policy,
            affected_device_ids=[lost_id] + promoted,
            is_degraded=True,
            reason=(
                f"PRIMARY device {lost_id!r} lost; promoted fallback to primary "
                f"(new primary: {new_primary!r})"
            ),
            rebalance_decision=rebalance_dec,
            recovery_hints={
                "primary_lost": True,
                "promoted_device_ids": promoted,
                "new_primary": new_primary,
            },
        )

    def _remove_and_rebalance(
        self,
        group: DeviceFormationGroup,
        device_id: str,
    ) -> Tuple[DeviceFormationGroup, FormationPolicy, Any]:
        """Remove *device_id* from the formation and return the result."""
        try:
            from .formation_rebalance_engine import (
                FormationHealthSignal,
                apply_rebalance,
            )
            health_map = {
                device_id: FormationHealthSignal(
                    device_id=device_id,
                    health_score=0.0,
                    is_reachable=False,
                )
            }
            new_group, decision = apply_rebalance(group, health_map)
            return new_group, DEFAULT_LOCAL_FORMATION_POLICY, decision
        except Exception as exc:
            logger.warning("_remove_and_rebalance: error: %s", exc)
            return group, DEFAULT_LOCAL_FORMATION_POLICY, None


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_default_controller: Optional[FormationRuntimeController] = None


def _get_default_controller() -> FormationRuntimeController:
    global _default_controller
    if _default_controller is None:
        _default_controller = FormationRuntimeController()
    return _default_controller


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def on_participant_lost(
    event: FormationTriggerEvent,
    formation: Optional[DeviceFormationGroup] = None,
    *,
    controller: Optional[FormationRuntimeController] = None,
) -> FormationRecoveryPlan:
    """Convenience wrapper: process a PARTICIPANT_LOST trigger.

    Parameters
    ----------
    event:
        Trigger event (should have ``trigger_type == PARTICIPANT_LOST``).
    formation:
        Current formation group.
    controller:
        Optional explicit controller instance; uses the module default if not
        provided.

    Returns
    -------
    FormationRecoveryPlan
    """
    c = controller or _get_default_controller()
    return c.on_participant_lost(event, formation)


def on_readiness_changed(
    event: FormationTriggerEvent,
    formation: Optional[DeviceFormationGroup] = None,
    *,
    controller: Optional[FormationRuntimeController] = None,
) -> FormationRecoveryPlan:
    """Convenience wrapper: process a READINESS_CHANGED trigger."""
    c = controller or _get_default_controller()
    return c.on_readiness_changed(event, formation)


def on_health_degraded(
    event: FormationTriggerEvent,
    formation: Optional[DeviceFormationGroup] = None,
    *,
    controller: Optional[FormationRuntimeController] = None,
) -> FormationRecoveryPlan:
    """Convenience wrapper: process a HEALTH_DEGRADED trigger."""
    c = controller or _get_default_controller()
    return c.on_health_degraded(event, formation)


def on_role_instability(
    event: FormationTriggerEvent,
    formation: Optional[DeviceFormationGroup] = None,
    *,
    controller: Optional[FormationRuntimeController] = None,
) -> FormationRecoveryPlan:
    """Convenience wrapper: process a ROLE_INSTABILITY trigger."""
    c = controller or _get_default_controller()
    return c.on_role_instability(event, formation)


def on_participant_joined(
    event: FormationTriggerEvent,
    formation: Optional[DeviceFormationGroup] = None,
    *,
    controller: Optional[FormationRuntimeController] = None,
) -> FormationRecoveryPlan:
    """Convenience wrapper: process a PARTICIPANT_JOINED trigger."""
    c = controller or _get_default_controller()
    return c.on_participant_joined(event, formation)
