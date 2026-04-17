#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/device_formation/formation_rebalance_engine.py
=====================================================
Formation Rebalance Engine — PR-next (architecture gap closure).

Background
----------
The existing ``formation_resolver.py`` (PR-17) computes a
:class:`~.formation_group.DeviceFormationGroup` from static signals at
formation-assembly time.  Its own docstring explicitly defers:

    "Does not implement live membership rebalancing or health-driven
    reshaping (planned for future work)."

``docs/MULTI_DEVICE_RUNTIME_MATURITY.md`` identifies this as the second
major maturity gap for the formation layer:

    "formation_resolver does not implement live membership rebalancing
    or health-driven reshaping."

This module closes that gap by providing:

1. :class:`FormationHealthSignal` — a minimal health signal (score + reason)
   that callers attach to devices to communicate liveness to the engine.

2. :class:`RebalanceDecision` — the outcome of a rebalance evaluation:
   which devices should be promoted, demoted, removed, or kept.

3. :class:`FormationRebalanceEngine` — a stateless engine that accepts a
   :class:`~.formation_group.DeviceFormationGroup` plus a health-signal map
   and produces a :class:`RebalanceDecision`.

4. :func:`evaluate_formation_health` — evaluate whether a formation is
   healthy without necessarily triggering a rebalance.

5. :func:`apply_rebalance` — convenience wrapper: evaluates health signals
   and returns a reshaped :class:`DeviceFormationGroup`.

6. Recovery hooks: :func:`maybe_promote_fallback` and
   :func:`maybe_remove_unhealthy` for targeted, scoped formation surgery
   without a full rebalance pass.

Design principles
-----------------
- **Additive only** — does not modify ``formation_resolver.py`` or any
  existing module.
- **Stateless** — the engine consumes a snapshot and returns a new one;
  it does not own persistent state.
- **Graceful degradation** — every function returns a valid result even
  with partial or empty inputs.
- **Health-signal agnostic** — the engine accepts any numeric score; the
  meaning of a score threshold is configurable.
- **Formation integrity** — a rebalance always preserves the SOURCE member
  and always ensures at least one PRIMARY_EXECUTION member in the result.

Sentinels
---------
:data:`FORMATION_REBALANCE_ENGINE_IS_AUTHORITY`
    Affirms this module is the canonical formation-rebalance layer.
:data:`FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL`
    Affirms this module closes the gap deferred in ``formation_resolver.py``.
:data:`REBALANCE_MUST_PRESERVE_SOURCE_POLICY`
    Affirms that rebalance never removes the SOURCE member.
:data:`REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY`
    Affirms that rebalance always ensures a PRIMARY_EXECUTION member exists.
:data:`HEALTH_THRESHOLD_GOVERNS_REMOVAL_POLICY`
    Affirms that only devices below the configured health threshold are
    considered for removal or demotion.

Public API
----------
Classes:
    :class:`FormationHealthSignal`
    :class:`DeviceHealthMap`
    :class:`MemberRebalanceAction`
    :class:`RebalanceDecision`
    :class:`FormationRebalanceEngine`

Functions:
    :func:`evaluate_formation_health`
    :func:`apply_rebalance`
    :func:`maybe_promote_fallback`
    :func:`maybe_remove_unhealthy`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .formation_group import DeviceFormationGroup, EMPTY_FORMATION_GROUP
from .formation_policy import BarrierPosture, FormationPolicy, DEFAULT_LOCAL_FORMATION_POLICY
from .formation_role import FormationMember, FormationRole

__all__ = [
    # Sentinels
    "FORMATION_REBALANCE_ENGINE_IS_AUTHORITY",
    "FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL",
    "REBALANCE_MUST_PRESERVE_SOURCE_POLICY",
    "REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY",
    "HEALTH_THRESHOLD_GOVERNS_REMOVAL_POLICY",
    # Classes
    "FormationHealthSignal",
    "MemberRebalanceAction",
    "RebalanceDecision",
    "FormationRebalanceEngine",
    # Functions
    "evaluate_formation_health",
    "apply_rebalance",
    "maybe_promote_fallback",
    "maybe_remove_unhealthy",
]

logger = logging.getLogger("Galaxy.DeviceFormation.RebalanceEngine")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

FORMATION_REBALANCE_ENGINE_IS_AUTHORITY: str = (
    "FORMATION_REBALANCE_ENGINE_IS_AUTHORITY: "
    "core/device_formation/formation_rebalance_engine.py is the canonical "
    "formation-rebalance and health-driven reshaping layer."
)

FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL: str = (
    "FORMATION_REBALANCE_GAP_CLOSURE: "
    "This module closes the gap deferred in formation_resolver.py: "
    "'Does not implement live membership rebalancing or health-driven "
    "reshaping (planned for future work).' "
    "See docs/MULTI_DEVICE_RUNTIME_MATURITY.md §formation_resolver."
)

REBALANCE_MUST_PRESERVE_SOURCE_POLICY: str = (
    "REBALANCE_POLICY: The SOURCE member of a formation is NEVER removed "
    "during a rebalance pass.  The origin device must always be traceable."
)

REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY: str = (
    "REBALANCE_POLICY: A rebalance pass always ensures at least one "
    "PRIMARY_EXECUTION member exists in the reshaped formation.  If the "
    "current primary is unhealthy, the best FALLBACK device is promoted."
)

HEALTH_THRESHOLD_GOVERNS_REMOVAL_POLICY: str = (
    "REBALANCE_POLICY: Only devices whose health score is strictly below "
    "the configured unhealthy_threshold are candidates for removal or "
    "demotion.  Devices at or above the threshold are retained."
)

# ---------------------------------------------------------------------------
# Default health thresholds
# ---------------------------------------------------------------------------

_DEFAULT_UNHEALTHY_THRESHOLD: float = 0.3
"""Health score below this value marks a device as unhealthy."""

_DEFAULT_DEGRADED_THRESHOLD: float = 0.6
"""Health score below this value (but above unhealthy) marks degraded."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FormationHealthSignal:
    """Health signal for one device in a formation.

    Attributes
    ----------
    device_id:
        The device this signal applies to.
    health_score:
        Normalised health score in ``[0.0, 1.0]``.  ``1.0`` = fully healthy;
        ``0.0`` = unreachable / failed.
    is_reachable:
        Whether the device is currently reachable via the transport layer.
    reason:
        Optional human-readable reason for the current score.
    """

    device_id: str
    health_score: float = 1.0
    is_reachable: bool = True
    reason: Optional[str] = None

    def is_healthy(self, threshold: float = _DEFAULT_UNHEALTHY_THRESHOLD) -> bool:
        return self.is_reachable and self.health_score >= threshold

    def is_degraded(
        self,
        unhealthy_threshold: float = _DEFAULT_UNHEALTHY_THRESHOLD,
        degraded_threshold: float = _DEFAULT_DEGRADED_THRESHOLD,
    ) -> bool:
        return (
            self.is_reachable
            and self.health_score >= unhealthy_threshold
            and self.health_score < degraded_threshold
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "health_score": self.health_score,
            "is_reachable": self.is_reachable,
            "reason": self.reason,
        }


# Convenience type alias
DeviceHealthMap = Dict[str, FormationHealthSignal]


class MemberRebalanceAction(str, Enum):
    """Action to apply to a formation member during rebalance."""

    KEEP = "keep"
    """Member is healthy; keep its current role."""

    PROMOTE_TO_PRIMARY = "promote_to_primary"
    """Promote this FALLBACK device to PRIMARY_EXECUTION."""

    DEMOTE_TO_FALLBACK = "demote_to_fallback"
    """Demote this degraded device from PRIMARY to FALLBACK."""

    REMOVE = "remove"
    """Remove this unhealthy device from the active formation."""

    WARN = "warn"
    """Flag this device as degraded but keep it in its role for now."""


@dataclass
class RebalanceDecision:
    """Result of a formation rebalance evaluation.

    Attributes
    ----------
    original_formation_id:
        Formation ID of the input ``DeviceFormationGroup``.
    rebalance_needed:
        Whether any membership or role changes are required.
    actions:
        Mapping of device_id → recommended :class:`MemberRebalanceAction`.
    new_primary_device_id:
        Device ID of the new primary after promotion (if any).
    removed_device_ids:
        Device IDs that should be removed from the formation.
    promoted_device_ids:
        Device IDs that have been promoted to PRIMARY_EXECUTION.
    demoted_device_ids:
        Device IDs that have been demoted from PRIMARY_EXECUTION.
    reason:
        Human-readable summary of the rebalance decision.
    healthy_device_count:
        Number of devices that are healthy after rebalance.
    """

    original_formation_id: str = ""
    rebalance_needed: bool = False
    actions: Dict[str, MemberRebalanceAction] = field(default_factory=dict)
    new_primary_device_id: Optional[str] = None
    removed_device_ids: List[str] = field(default_factory=list)
    promoted_device_ids: List[str] = field(default_factory=list)
    demoted_device_ids: List[str] = field(default_factory=list)
    reason: str = "no rebalance needed"
    healthy_device_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_formation_id": self.original_formation_id,
            "rebalance_needed": self.rebalance_needed,
            "actions": {k: v.value for k, v in self.actions.items()},
            "new_primary_device_id": self.new_primary_device_id,
            "removed_device_ids": list(self.removed_device_ids),
            "promoted_device_ids": list(self.promoted_device_ids),
            "demoted_device_ids": list(self.demoted_device_ids),
            "reason": self.reason,
            "healthy_device_count": self.healthy_device_count,
        }


# ---------------------------------------------------------------------------
# FormationRebalanceEngine
# ---------------------------------------------------------------------------


class FormationRebalanceEngine:
    """Stateless engine that evaluates and applies health-driven formation rebalance.

    Usage::

        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, health_map)
        if decision.rebalance_needed:
            new_group, new_policy = engine.reshape(group, decision)

    Parameters
    ----------
    unhealthy_threshold:
        Health score below which a device is considered unhealthy and
        eligible for removal / demotion.  Default: 0.3.
    degraded_threshold:
        Health score below which (but above unhealthy) a device is
        considered degraded and flagged with WARN.  Default: 0.6.
    """

    def __init__(
        self,
        unhealthy_threshold: float = _DEFAULT_UNHEALTHY_THRESHOLD,
        degraded_threshold: float = _DEFAULT_DEGRADED_THRESHOLD,
    ) -> None:
        self._unhealthy_threshold = unhealthy_threshold
        self._degraded_threshold = degraded_threshold

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def evaluate(
        self,
        group: DeviceFormationGroup,
        health_map: Optional[DeviceHealthMap] = None,
    ) -> RebalanceDecision:
        """Evaluate health signals and compute a :class:`RebalanceDecision`.

        Parameters
        ----------
        group:
            The current :class:`~.formation_group.DeviceFormationGroup`.
        health_map:
            Mapping of device_id → :class:`FormationHealthSignal`.
            Devices not present in the map are assumed healthy.

        Returns
        -------
        RebalanceDecision
            Never raises; returns a safe no-op decision on error.
        """
        try:
            return self._evaluate_inner(group, health_map or {})
        except Exception as exc:
            logger.warning("FormationRebalanceEngine.evaluate: unexpected error: %s", exc)
            return RebalanceDecision(
                original_formation_id=getattr(group, "formation_id", ""),
                reason=f"evaluation error: {exc}",
            )

    def reshape(
        self,
        group: DeviceFormationGroup,
        decision: RebalanceDecision,
    ) -> Tuple[DeviceFormationGroup, FormationPolicy]:
        """Apply a :class:`RebalanceDecision` to produce a reshaped formation.

        Parameters
        ----------
        group:
            The current :class:`~.formation_group.DeviceFormationGroup`.
        decision:
            The :class:`RebalanceDecision` from :meth:`evaluate`.

        Returns
        -------
        Tuple[DeviceFormationGroup, FormationPolicy]
            The reshaped group and a new policy.  If no rebalance is
            needed, returns the original group and a re-derived policy.
            Never raises.
        """
        try:
            if not decision.rebalance_needed:
                return group, self._derive_policy(group)
            return self._reshape_inner(group, decision)
        except Exception as exc:
            logger.warning("FormationRebalanceEngine.reshape: unexpected error: %s", exc)
            return group, DEFAULT_LOCAL_FORMATION_POLICY

    # ------------------------------------------------------------------
    # Internal evaluation
    # ------------------------------------------------------------------

    def _evaluate_inner(
        self,
        group: DeviceFormationGroup,
        health_map: DeviceHealthMap,
    ) -> RebalanceDecision:
        actions: Dict[str, MemberRebalanceAction] = {}
        removed: List[str] = []
        promoted: List[str] = []
        demoted: List[str] = []
        new_primary: Optional[str] = None
        formation_id = getattr(group, "formation_id", "")

        members = getattr(group, "members", []) or []
        if not members:
            return RebalanceDecision(
                original_formation_id=formation_id,
                reason="empty formation — no rebalance needed",
            )

        # Classify each member
        primary_device_id: Optional[str] = None
        source_device_id: Optional[str] = getattr(group, "source_device_id", None)
        fallback_members: List[FormationMember] = []
        primary_unhealthy = False

        for member in members:
            dev_id = getattr(member, "device_id", None)
            if not dev_id:
                continue
            role = getattr(member, "role", None)
            signal = health_map.get(dev_id)
            score = signal.health_score if signal is not None else 1.0
            reachable = signal.is_reachable if signal is not None else True

            is_healthy = reachable and score >= self._unhealthy_threshold
            is_degraded = (
                reachable and score >= self._unhealthy_threshold and score < self._degraded_threshold
            )

            if role == FormationRole.SOURCE:
                # Never remove SOURCE
                actions[dev_id] = MemberRebalanceAction.KEEP
                continue

            if role == FormationRole.PRIMARY_EXECUTION:
                primary_device_id = dev_id
                if not is_healthy:
                    actions[dev_id] = MemberRebalanceAction.DEMOTE_TO_FALLBACK
                    demoted.append(dev_id)
                    primary_unhealthy = True
                elif is_degraded:
                    actions[dev_id] = MemberRebalanceAction.WARN
                else:
                    actions[dev_id] = MemberRebalanceAction.KEEP

            elif role == FormationRole.FALLBACK:
                fallback_members.append(member)
                if not is_healthy:
                    actions[dev_id] = MemberRebalanceAction.REMOVE
                    removed.append(dev_id)
                elif is_degraded:
                    actions[dev_id] = MemberRebalanceAction.WARN
                else:
                    actions[dev_id] = MemberRebalanceAction.KEEP

            else:
                # SUPPORT, OBSERVER, RELAY, MERGE_OWNER, UNASSIGNED
                if not is_healthy:
                    actions[dev_id] = MemberRebalanceAction.REMOVE
                    removed.append(dev_id)
                elif is_degraded:
                    actions[dev_id] = MemberRebalanceAction.WARN
                else:
                    actions[dev_id] = MemberRebalanceAction.KEEP

        # If primary was demoted / absent, promote best fallback
        if primary_unhealthy or primary_device_id is None:
            best_fallback = self._pick_best_fallback(
                fallback_members, health_map, removed
            )
            if best_fallback:
                actions[best_fallback] = MemberRebalanceAction.PROMOTE_TO_PRIMARY
                if best_fallback in removed:
                    removed.remove(best_fallback)
                promoted.append(best_fallback)
                new_primary = best_fallback

        rebalance_needed = bool(removed or promoted or demoted)
        healthy_count = sum(
            1
            for m in members
            if getattr(m, "device_id", None)
            and actions.get(getattr(m, "device_id", ""), MemberRebalanceAction.KEEP)
            not in (MemberRebalanceAction.REMOVE,)
        )

        if not rebalance_needed:
            reason = "all formation members are healthy"
        else:
            parts = []
            if promoted:
                parts.append(f"promoted {promoted} to PRIMARY_EXECUTION")
            if demoted:
                parts.append(f"demoted {demoted} from PRIMARY_EXECUTION")
            if removed:
                parts.append(f"removed unhealthy {removed}")
            reason = "; ".join(parts) if parts else "rebalance computed"

        return RebalanceDecision(
            original_formation_id=formation_id,
            rebalance_needed=rebalance_needed,
            actions=actions,
            new_primary_device_id=new_primary,
            removed_device_ids=removed,
            promoted_device_ids=promoted,
            demoted_device_ids=demoted,
            reason=reason,
            healthy_device_count=healthy_count,
        )

    # ------------------------------------------------------------------
    # Internal reshape
    # ------------------------------------------------------------------

    def _reshape_inner(
        self,
        group: DeviceFormationGroup,
        decision: RebalanceDecision,
    ) -> Tuple[DeviceFormationGroup, FormationPolicy]:
        members = list(getattr(group, "members", []) or [])
        new_members: List[FormationMember] = []
        new_primary_id = decision.new_primary_device_id

        for member in members:
            dev_id = getattr(member, "device_id", None)
            if not dev_id:
                continue
            action = decision.actions.get(dev_id, MemberRebalanceAction.KEEP)

            if action == MemberRebalanceAction.REMOVE:
                logger.info(
                    "Formation reshape: removing unhealthy device %s (formation=%s)",
                    dev_id,
                    decision.original_formation_id,
                )
                continue

            if action == MemberRebalanceAction.PROMOTE_TO_PRIMARY:
                new_members.append(
                    FormationMember(
                        device_id=dev_id,
                        role=FormationRole.PRIMARY_EXECUTION,
                        reason=f"promoted from FALLBACK during formation rebalance ({decision.reason})",
                        capabilities=getattr(member, "capabilities", []),
                        is_local=getattr(member, "is_local", False),
                    )
                )
                logger.info(
                    "Formation reshape: promoted %s to PRIMARY_EXECUTION (formation=%s)",
                    dev_id,
                    decision.original_formation_id,
                )

            elif action == MemberRebalanceAction.DEMOTE_TO_FALLBACK:
                new_members.append(
                    FormationMember(
                        device_id=dev_id,
                        role=FormationRole.FALLBACK,
                        reason=f"demoted from PRIMARY_EXECUTION during formation rebalance ({decision.reason})",
                        capabilities=getattr(member, "capabilities", []),
                        is_local=getattr(member, "is_local", False),
                    )
                )
                logger.info(
                    "Formation reshape: demoted %s to FALLBACK (formation=%s)",
                    dev_id,
                    decision.original_formation_id,
                )

            else:
                new_members.append(member)

        # Ensure there is always at least one PRIMARY_EXECUTION
        has_primary = any(
            getattr(m, "role", None) == FormationRole.PRIMARY_EXECUTION
            for m in new_members
        )
        if not has_primary:
            # Last resort: promote first remaining non-SOURCE member
            for m in new_members:
                role = getattr(m, "role", None)
                if role not in (FormationRole.SOURCE, FormationRole.OBSERVER):
                    new_members[new_members.index(m)] = FormationMember(
                        device_id=m.device_id,
                        role=FormationRole.PRIMARY_EXECUTION,
                        reason="emergency promotion during reshape — no primary available",
                        capabilities=getattr(m, "capabilities", []),
                        is_local=getattr(m, "is_local", False),
                    )
                    logger.warning(
                        "Formation reshape: emergency PRIMARY_EXECUTION promotion "
                        "for %s (formation=%s)",
                        m.device_id,
                        decision.original_formation_id,
                    )
                    break

        # Determine new primary id for merge_owner fallback
        effective_primary_id = new_primary_id or next(
            (
                getattr(m, "device_id", None)
                for m in new_members
                if getattr(m, "role", None) == FormationRole.PRIMARY_EXECUTION
            ),
            getattr(group, "source_device_id", None),
        )

        new_group = DeviceFormationGroup(
            task_id=getattr(group, "task_id", None),
            trace_id=getattr(group, "trace_id", None),
            source_device_id=getattr(group, "source_device_id", None),
            source_runtime_posture=getattr(group, "source_runtime_posture", "control_only"),
            members=new_members,
            merge_owner_device_id=(
                getattr(group, "merge_owner_device_id", None)
                if getattr(group, "merge_owner_device_id", None) not in decision.removed_device_ids
                else effective_primary_id
            ),
            barrier_posture=getattr(group, "barrier_posture", BarrierPosture.WAIT_PRIMARY.value),
            formation_reason=(
                f"reshaped from {decision.original_formation_id}: {decision.reason}"
            ),
            runtime_domain_intent=getattr(group, "runtime_domain_intent", "local"),
        )

        policy = self._derive_policy(new_group)
        return new_group, policy

    def _pick_best_fallback(
        self,
        fallback_members: List[FormationMember],
        health_map: DeviceHealthMap,
        already_removed: List[str],
    ) -> Optional[str]:
        """Return the device_id of the healthiest eligible fallback device."""
        candidates = [
            m for m in fallback_members
            if getattr(m, "device_id", None) not in already_removed
        ]
        if not candidates:
            return None
        # Sort by health score descending
        def _score(m: FormationMember) -> float:
            sig = health_map.get(getattr(m, "device_id", ""))
            return sig.health_score if sig is not None else 1.0

        candidates.sort(key=_score, reverse=True)
        return getattr(candidates[0], "device_id", None)

    def _derive_policy(self, group: DeviceFormationGroup) -> FormationPolicy:
        """Derive a :class:`FormationPolicy` from the (reshaped) group."""
        from .formation_policy import FormationPolicy
        members = getattr(group, "members", []) or []
        is_cross_device = (
            getattr(group, "runtime_domain_intent", "local") == "cross_device"
            or len({getattr(m, "device_id", None) for m in members if getattr(m, "device_id", None)}) > 1
        )
        has_fallback = any(
            getattr(m, "role", None) == FormationRole.FALLBACK for m in members
        )
        barrier_str = getattr(group, "barrier_posture", BarrierPosture.WAIT_PRIMARY.value)
        try:
            barrier = BarrierPosture(barrier_str)
        except (ValueError, KeyError):
            barrier = BarrierPosture.WAIT_PRIMARY
        return FormationPolicy(
            multi_device_required=is_cross_device,
            merge_confirmation_required=False,
            fallback_intent="promote_fallback_device" if has_fallback else "fail_task",
            barrier_posture=barrier,
        )


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def evaluate_formation_health(
    group: DeviceFormationGroup,
    health_map: Optional[DeviceHealthMap] = None,
    *,
    unhealthy_threshold: float = _DEFAULT_UNHEALTHY_THRESHOLD,
    degraded_threshold: float = _DEFAULT_DEGRADED_THRESHOLD,
) -> RebalanceDecision:
    """Evaluate formation health without applying any changes.

    Parameters
    ----------
    group:
        The current :class:`~.formation_group.DeviceFormationGroup`.
    health_map:
        Mapping of device_id → :class:`FormationHealthSignal`.
    unhealthy_threshold:
        Health score below which a device is unhealthy.
    degraded_threshold:
        Health score below which (but above unhealthy) a device is degraded.

    Returns
    -------
    RebalanceDecision
    """
    engine = FormationRebalanceEngine(
        unhealthy_threshold=unhealthy_threshold,
        degraded_threshold=degraded_threshold,
    )
    return engine.evaluate(group, health_map)


def apply_rebalance(
    group: DeviceFormationGroup,
    health_map: Optional[DeviceHealthMap] = None,
    *,
    unhealthy_threshold: float = _DEFAULT_UNHEALTHY_THRESHOLD,
    degraded_threshold: float = _DEFAULT_DEGRADED_THRESHOLD,
) -> Tuple[DeviceFormationGroup, RebalanceDecision]:
    """Evaluate and apply a formation rebalance in one step.

    Parameters
    ----------
    group:
        The current :class:`~.formation_group.DeviceFormationGroup`.
    health_map:
        Mapping of device_id → :class:`FormationHealthSignal`.
    unhealthy_threshold:
        Health score below which a device is unhealthy.
    degraded_threshold:
        Health score below which (but above unhealthy) a device is degraded.

    Returns
    -------
    Tuple[DeviceFormationGroup, RebalanceDecision]
        The (possibly reshaped) formation group and the decision that was
        applied.
    """
    try:
        engine = FormationRebalanceEngine(
            unhealthy_threshold=unhealthy_threshold,
            degraded_threshold=degraded_threshold,
        )
        decision = engine.evaluate(group, health_map)
        new_group, _ = engine.reshape(group, decision)
        return new_group, decision
    except Exception as exc:
        logger.warning("apply_rebalance: unexpected error: %s", exc)
        return group, RebalanceDecision(
            original_formation_id=getattr(group, "formation_id", ""),
            reason=f"apply_rebalance error: {exc}",
        )


def maybe_promote_fallback(
    group: DeviceFormationGroup,
    unhealthy_primary_id: str,
    best_fallback_id: str,
) -> DeviceFormationGroup:
    """Targeted surgery: promote a specific fallback device to PRIMARY_EXECUTION.

    Use this when the caller already knows which device to promote
    (e.g. from its own health monitoring), without running the full
    rebalance engine.

    Parameters
    ----------
    group:
        The current :class:`~.formation_group.DeviceFormationGroup`.
    unhealthy_primary_id:
        Device ID of the unhealthy primary to demote.
    best_fallback_id:
        Device ID of the fallback device to promote.

    Returns
    -------
    DeviceFormationGroup
        The reshaped group.
    """
    try:
        health_map: DeviceHealthMap = {
            unhealthy_primary_id: FormationHealthSignal(
                device_id=unhealthy_primary_id,
                health_score=0.0,
                is_reachable=False,
                reason="explicit unhealthy signal from maybe_promote_fallback caller",
            ),
        }
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, health_map)
        # Override the promoted device selection if the engine picked differently
        if best_fallback_id and best_fallback_id not in decision.promoted_device_ids:
            decision.promoted_device_ids = [best_fallback_id]
            decision.new_primary_device_id = best_fallback_id
            decision.rebalance_needed = True
            from .formation_role import FormationRole as _FR
            decision.actions[best_fallback_id] = MemberRebalanceAction.PROMOTE_TO_PRIMARY
        new_group, _ = engine.reshape(group, decision)
        return new_group
    except Exception as exc:
        logger.warning("maybe_promote_fallback: error: %s", exc)
        return group


def maybe_remove_unhealthy(
    group: DeviceFormationGroup,
    unhealthy_device_ids: List[str],
) -> DeviceFormationGroup:
    """Targeted surgery: remove a set of known-unhealthy devices from a formation.

    Parameters
    ----------
    group:
        The current :class:`~.formation_group.DeviceFormationGroup`.
    unhealthy_device_ids:
        List of device IDs to remove.  SOURCE is never removed.

    Returns
    -------
    DeviceFormationGroup
        The reshaped group with specified devices removed.
    """
    try:
        if not unhealthy_device_ids:
            return group
        health_map: DeviceHealthMap = {
            dev_id: FormationHealthSignal(
                device_id=dev_id,
                health_score=0.0,
                is_reachable=False,
                reason="explicit unhealthy signal from maybe_remove_unhealthy caller",
            )
            for dev_id in unhealthy_device_ids
        }
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, health_map)
        new_group, _ = engine.reshape(group, decision)
        return new_group
    except Exception as exc:
        logger.warning("maybe_remove_unhealthy: error: %s", exc)
        return group
