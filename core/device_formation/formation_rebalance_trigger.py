#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_formation.formation_rebalance_trigger
===================================================

PR-3 — Formation & Routing Hardening: Formation Rebalance Trigger.

Background
----------
The :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator`
provides stateful per-participant lifecycle management and produces
:class:`~.formation_runtime_coordinator.FormationRuntimeDecision` values
when triggered.  The :class:`~.formation_rebalance_engine.FormationRebalanceEngine`
reshapes a :class:`~.formation_group.DeviceFormationGroup` based on health
signals.

What was still missing was a **lightweight bridge** that:

1. Accepts runtime-change events from outside the formation stack
   (e.g. from ``DeviceRouter``, ``MultiDeviceRuntimeHarness``, or health
   monitors) using a simple, event-driven API.
2. Routes each event to the appropriate coordinator trigger method.
3. Drives the ``FormationRebalanceEngine`` when the coordinator recommends
   a reshape.
4. Returns an updated ``DeviceFormationGroup`` and a structured
   ``FormationRebuildResult`` so callers can act on the outcome without
   reimplementing the evaluation logic.

This module closes that bridge gap.  It does not modify any existing module.

Design principles
-----------------
- **Additive only** — does not modify ``formation_resolver.py``,
  ``formation_rebalance_engine.py``, ``formation_runtime_coordinator.py``,
  or any other existing module.
- **Event-driven** — callers push discrete runtime-change events through
  :func:`on_runtime_event`; the trigger routes and evaluates internally.
- **Stateless input, stateful coordinator** — the trigger accepts a
  ``FormationRuntimeCoordinator`` instance (owned by the caller) and a
  snapshot ``DeviceFormationGroup``; it returns a new group without
  mutating either input directly.
- **Graceful degradation** — every public function is guarded; unexpected
  errors produce a safe no-op result rather than raising.

Sentinels
---------
:data:`FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY`
    Identifies this module as the canonical runtime-event bridge for
    formation rebalance triggering.
:data:`FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY`
    Affirms that this module bridges coordinator decisions to the engine
    reshape pass, closing the gap between runtime event reception and
    formation membership update.
:data:`FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY`
    Affirms that the trigger does not own coordinator or group state; it
    is a stateless routing bridge.

Public API
----------
Enumerations:
    :class:`FormationRuntimeEventType`

Data classes:
    :class:`FormationRuntimeEvent`
    :class:`FormationRebuildResult`

Functions:
    :func:`on_runtime_event`
    :func:`trigger_rebalance_if_needed`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .formation_group import DeviceFormationGroup, EMPTY_FORMATION_GROUP
from .formation_rebalance_engine import (
    FormationHealthSignal,
    FormationRebalanceEngine,
    DeviceHealthMap,
    apply_rebalance,
)
from .formation_runtime_coordinator import (
    FormationRuntimeCoordinator,
    FormationRuntimeDecision,
    RecoveryActionType,
)

__all__ = [
    # Sentinels
    "FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY",
    "FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY",
    "FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY",
    # Enumerations
    "FormationRuntimeEventType",
    # Data classes
    "FormationRuntimeEvent",
    "FormationRebuildResult",
    # Functions
    "on_runtime_event",
    "trigger_rebalance_if_needed",
]

logger = logging.getLogger("Galaxy.DeviceFormation.RebalanceTrigger")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY: str = (
    "FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY: "
    "core/device_formation/formation_rebalance_trigger.py is the canonical "
    "runtime-event bridge that routes health/liveness events to the "
    "FormationRuntimeCoordinator and drives the FormationRebalanceEngine "
    "when a reshape is required."
)

FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY: str = (
    "FORMATION_TRIGGER_POLICY: This module bridges FormationRuntimeCoordinator "
    "(stateful participant lifecycle) to FormationRebalanceEngine (stateless "
    "membership arithmetic), closing the gap between 'coordinator recommends "
    "reshape' and 'formation group is actually reshaped.'  Resolves PR-3 "
    "requirement: dynamic formation reevaluation when participant availability, "
    "capability, or runtime health changes."
)

FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY: str = (
    "FORMATION_TRIGGER_POLICY: This module is a stateless routing bridge.  "
    "The FormationRuntimeCoordinator (owned by the caller) holds participant "
    "state.  The DeviceFormationGroup (passed as a snapshot) is never "
    "mutated; a new group is returned when reshaping is applied."
)


# ---------------------------------------------------------------------------
# FormationRuntimeEventType
# ---------------------------------------------------------------------------


class FormationRuntimeEventType(str, Enum):
    """Discrete runtime-change event types the trigger can process."""

    PARTICIPANT_READY = "participant_ready"
    """A participant has signalled readiness (joined or recovered)."""

    PARTICIPANT_LOST = "participant_lost"
    """A participant has become unreachable or disconnected."""

    HEALTH_DEGRADED = "health_degraded"
    """A participant's health score has dropped below a threshold."""

    RECOVERY_AVAILABLE = "recovery_available"
    """A previously-lost participant is signalling re-availability."""

    CAPABILITY_CHANGED = "capability_changed"
    """A participant's declared capabilities have changed at runtime."""

    EXPLICIT_REBALANCE_REQUEST = "explicit_rebalance_request"
    """An external authority has explicitly requested a rebalance pass."""


# ---------------------------------------------------------------------------
# FormationRuntimeEvent
# ---------------------------------------------------------------------------


@dataclass
class FormationRuntimeEvent:
    """A discrete runtime-change event to be processed by the trigger.

    Attributes
    ----------
    event_type:
        :class:`FormationRuntimeEventType` describing what changed.
    device_id:
        The device this event concerns.
    health_score:
        Current health score for the device (0.0–1.0).  Used for
        ``HEALTH_DEGRADED`` events; ignored for others.
    reason:
        Optional human-readable explanation.
    metadata:
        Optional event-specific metadata.
    """

    event_type: FormationRuntimeEventType
    device_id: str
    health_score: float = 1.0
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "device_id": self.device_id,
            "health_score": self.health_score,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# FormationRebuildResult
# ---------------------------------------------------------------------------


@dataclass
class FormationRebuildResult:
    """Result of processing a :class:`FormationRuntimeEvent`.

    Attributes
    ----------
    original_formation_id:
        ``formation_id`` of the input :class:`DeviceFormationGroup`.
    reshaped:
        Whether the formation group was actually reshaped.
    new_group:
        The (potentially updated) :class:`DeviceFormationGroup`.  When
        ``reshaped`` is ``False`` this is identical to the input group.
    coordinator_decision:
        The :class:`~.formation_runtime_coordinator.FormationRuntimeDecision`
        produced by the coordinator for the event.
    reason:
        Human-readable summary of what happened.
    """

    original_formation_id: str = ""
    reshaped: bool = False
    new_group: DeviceFormationGroup = field(default_factory=lambda: EMPTY_FORMATION_GROUP)
    coordinator_decision: Optional[FormationRuntimeDecision] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "original_formation_id": self.original_formation_id,
            "reshaped": self.reshaped,
            "new_group": (
                self.new_group.to_dict()
                if hasattr(self.new_group, "to_dict")
                else {}
            ),
            "reason": self.reason,
        }
        if self.coordinator_decision is not None:
            result["coordinator_decision"] = (
                self.coordinator_decision.to_dict()
                if hasattr(self.coordinator_decision, "to_dict")
                else {}
            )
        return result


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def on_runtime_event(
    event: FormationRuntimeEvent,
    group: DeviceFormationGroup,
    coordinator: FormationRuntimeCoordinator,
    health_map: Optional[DeviceHealthMap] = None,
) -> FormationRebuildResult:
    """Process a runtime-change event and return an updated formation.

    Routes *event* to the appropriate
    :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator`
    trigger method, then drives :func:`~.formation_rebalance_engine.apply_rebalance`
    when the coordinator recommends a reshape.

    Parameters
    ----------
    event:
        The runtime-change event to process.
    group:
        Current :class:`~.formation_group.DeviceFormationGroup` snapshot.
    coordinator:
        Stateful :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator`
        instance.  Its internal state is updated in-place by each trigger call.
    health_map:
        Optional map of ``device_id → FormationHealthSignal`` used when
        the coordinator recommends a full ``RESHAPE`` action.

    Returns
    -------
    FormationRebuildResult
        Includes the (possibly updated) formation group, the coordinator
        decision, and a human-readable reason.
    """
    try:
        return _on_runtime_event_inner(
            event=event,
            group=group,
            coordinator=coordinator,
            health_map=health_map or {},
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "on_runtime_event: unexpected error processing event %s for %s: %s",
            event.event_type.value,
            event.device_id,
            exc,
        )
        return FormationRebuildResult(
            original_formation_id=getattr(group, "formation_id", ""),
            reshaped=False,
            new_group=group,
            reason=f"error processing event: {exc}",
        )


def trigger_rebalance_if_needed(
    group: DeviceFormationGroup,
    coordinator: FormationRuntimeCoordinator,
    health_map: Optional[DeviceHealthMap] = None,
) -> FormationRebuildResult:
    """Evaluate formation health and apply a rebalance if recommended.

    This is a convenience entry point for callers that have already decided
    a health check is warranted (e.g. on a periodic poll or after a batch
    of health signals).  It calls
    :meth:`~.formation_runtime_coordinator.FormationRuntimeCoordinator.evaluate_continuation`
    and then reshapes the formation if the coordinator recommends it.

    Parameters
    ----------
    group:
        Current :class:`~.formation_group.DeviceFormationGroup` snapshot.
    coordinator:
        Stateful coordinator instance.
    health_map:
        Optional health signals to use for the rebalance pass.

    Returns
    -------
    FormationRebuildResult
    """
    try:
        decision = coordinator.evaluate_continuation()
        return _apply_decision(
            group=group,
            decision=decision,
            health_map=health_map or {},
            reason_prefix="trigger_rebalance_if_needed",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "trigger_rebalance_if_needed: error: %s", exc
        )
        return FormationRebuildResult(
            original_formation_id=getattr(group, "formation_id", ""),
            reshaped=False,
            new_group=group,
            reason=f"error: {exc}",
        )


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------


def _on_runtime_event_inner(
    event: FormationRuntimeEvent,
    group: DeviceFormationGroup,
    coordinator: FormationRuntimeCoordinator,
    health_map: DeviceHealthMap,
) -> FormationRebuildResult:
    """Route event to coordinator and apply rebalance when recommended."""
    formation_id = getattr(group, "formation_id", "")
    evt = event.event_type

    # Route to the appropriate coordinator trigger.
    if evt == FormationRuntimeEventType.PARTICIPANT_READY:
        decision = coordinator.on_participant_readiness_changed(
            device_id=event.device_id,
            is_ready=True,
            reason=event.reason,
        )

    elif evt == FormationRuntimeEventType.PARTICIPANT_LOST:
        decision = coordinator.on_participant_lost(
            device_id=event.device_id,
            reason=event.reason,
        )

    elif evt == FormationRuntimeEventType.HEALTH_DEGRADED:
        # Build a minimal health signal from the event.
        signal = FormationHealthSignal(
            device_id=event.device_id,
            health_score=event.health_score,
            is_reachable=event.health_score > 0.0,
            reason=event.reason,
        )
        decision = coordinator.on_health_degraded(
            device_id=event.device_id,
            health_score=event.health_score,
            reason=event.reason,
        )
        # Merge health signal into the health map for potential reshape.
        if event.device_id not in health_map:
            health_map = dict(health_map)
            health_map[event.device_id] = signal

    elif evt == FormationRuntimeEventType.RECOVERY_AVAILABLE:
        decision = coordinator.on_recovery_available(
            device_id=event.device_id,
            reason=event.reason,
        )

    elif evt in (
        FormationRuntimeEventType.CAPABILITY_CHANGED,
        FormationRuntimeEventType.EXPLICIT_REBALANCE_REQUEST,
    ):
        # Treat capability changes and explicit requests as a readiness
        # signal that warrants a full continuation evaluation.
        decision = coordinator.evaluate_continuation()

    else:
        logger.debug(
            "on_runtime_event: unrecognised event type %r, "
            "falling through to evaluate_continuation",
            evt,
        )
        decision = coordinator.evaluate_continuation()

    return _apply_decision(
        group=group,
        decision=decision,
        health_map=health_map,
        reason_prefix=f"event={evt.value}",
    )


def _apply_decision(
    group: DeviceFormationGroup,
    decision: FormationRuntimeDecision,
    health_map: DeviceHealthMap,
    reason_prefix: str,
) -> FormationRebuildResult:
    """Apply a coordinator decision to the formation group."""
    formation_id = getattr(group, "formation_id", "")

    # Check whether any recommended action requires a reshape.
    needs_reshape = _decision_requires_reshape(decision)

    if not needs_reshape:
        return FormationRebuildResult(
            original_formation_id=formation_id,
            reshaped=False,
            new_group=group,
            coordinator_decision=decision,
            reason=(
                f"{reason_prefix}: coordinator decision does not require reshape "
                f"(runtime_state={getattr(decision, 'runtime_state', 'unknown')})"
            ),
        )

    # Drive the rebalance engine.
    try:
        new_group, rebalance_decision = apply_rebalance(
            group=group,
            health_map=health_map,
        )
        reshaped = getattr(rebalance_decision, "rebalance_needed", False)
        reason = (
            f"{reason_prefix}: reshape applied — "
            f"rebalance_needed={reshaped}, "
            f"promoted={getattr(rebalance_decision, 'promoted_device_ids', [])}, "
            f"removed={getattr(rebalance_decision, 'removed_device_ids', [])}"
        )
        logger.info(
            "formation_rebalance_trigger: %s | formation_id=%s",
            reason,
            formation_id,
        )
        return FormationRebuildResult(
            original_formation_id=formation_id,
            reshaped=reshaped,
            new_group=new_group,
            coordinator_decision=decision,
            reason=reason,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "formation_rebalance_trigger: rebalance engine error: %s", exc
        )
        return FormationRebuildResult(
            original_formation_id=formation_id,
            reshaped=False,
            new_group=group,
            coordinator_decision=decision,
            reason=f"{reason_prefix}: rebalance engine error: {exc}",
        )


def _decision_requires_reshape(decision: FormationRuntimeDecision) -> bool:
    """Return True when any recommended action in *decision* warrants a reshape."""
    if decision is None:
        return False

    reshape_actions = {
        RecoveryActionType.RESHAPE,
        RecoveryActionType.PROMOTE_FALLBACK,
        RecoveryActionType.REMOVE_PARTICIPANT,
    }

    recommended = getattr(decision, "recommended_actions", [])
    for action in recommended:
        action_type = getattr(action, "action_type", None)
        if action_type in reshape_actions:
            return True

    return False
