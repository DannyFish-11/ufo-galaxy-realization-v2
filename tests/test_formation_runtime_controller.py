#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_formation_runtime_controller.py
==========================================
Tests for core/device_formation/formation_runtime_controller.py

Coverage:
  1.  Module sentinels are importable strings.
  2.  FormationTriggerType enum values.
  3.  DegradedContinuationDecision enum values.
  4.  FormationTriggerEvent construction and to_dict.
  5.  FormationRecoveryPlan construction and to_dict.
  6.  process_trigger — PARTICIPANT_LOST dispatches to on_participant_lost.
  7.  process_trigger — READINESS_CHANGED dispatches to on_readiness_changed.
  8.  process_trigger — HEALTH_DEGRADED dispatches to on_health_degraded.
  9.  process_trigger — ROLE_INSTABILITY dispatches to on_role_instability.
  10. process_trigger — PARTICIPANT_JOINED dispatches to on_participant_joined.
  11. on_participant_lost — SOURCE lost → AWAIT_RECOVERY.
  12. on_participant_lost — PRIMARY lost with fallback → RESHAPE_AND_CONTINUE.
  13. on_participant_lost — PRIMARY lost without fallback → ABORT.
  14. on_participant_lost — SUPPORT lost → CONTINUE_DEGRADED.
  15. on_participant_lost — RELAY lost → CONTINUE_DEGRADED.
  16. on_participant_lost — OBSERVER lost → CONTINUE_DEGRADED.
  17. on_participant_lost — FALLBACK lost → CONTINUE_DEGRADED.
  18. on_participant_lost — device not in formation → CONTINUE_DEGRADED, not degraded.
  19. on_participant_lost — empty formation, no crash.
  20. on_readiness_changed — device becoming unready → delegates to lost path.
  21. on_readiness_changed — device becoming ready → CONTINUE_DEGRADED, not degraded.
  22. on_health_degraded — below unhealthy threshold → delegates to lost path.
  23. on_health_degraded — in degraded band → CONTINUE_DEGRADED with is_degraded=True.
  24. on_health_degraded — above degraded threshold → CONTINUE_DEGRADED, not degraded.
  25. on_role_instability — SOURCE role → AWAIT_RECOVERY.
  26. on_role_instability — PRIMARY role with fallback → RESHAPE_AND_CONTINUE.
  27. on_role_instability — SUPPORT role → CONTINUE_DEGRADED.
  28. on_role_instability — device not in formation → CONTINUE_DEGRADED.
  29. on_participant_joined — formation has no primary → suggest re-resolve.
  30. on_participant_joined — healthy formation → no action required.
  31. on_participant_joined — no fallback → suggest re-resolve.
  32. Reshape after PRIMARY loss produces a formation with a new primary.
  33. Recovery plan to_dict contains expected keys.
  34. FormationRuntimeController never raises on None formation.
  35. core.device_formation __init__ exports controller symbols.
  36. Module-level convenience functions are callable.
  37. Custom thresholds affect health_degraded routing.
  38. recovery_hints are populated on PRIMARY loss.
  39. recovery_hints are populated on SOURCE loss.
  40. process_trigger with unknown trigger type — returns CONTINUE_DEGRADED safely.
"""

from __future__ import annotations

from typing import List, Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_group(
    *,
    source_id: Optional[str] = "source-dev",
    primary_id: Optional[str] = "primary-dev",
    fallback_ids: Optional[List[str]] = None,
    support_ids: Optional[List[str]] = None,
    relay_ids: Optional[List[str]] = None,
    observer_ids: Optional[List[str]] = None,
    domain: str = "cross_device",
):
    from core.device_formation.formation_group import DeviceFormationGroup
    from core.device_formation.formation_role import FormationMember, FormationRole

    members = []
    if source_id:
        members.append(FormationMember(device_id=source_id, role=FormationRole.SOURCE, reason="s"))
    if primary_id:
        members.append(FormationMember(device_id=primary_id, role=FormationRole.PRIMARY_EXECUTION, reason="p"))
    for fid in (fallback_ids or []):
        members.append(FormationMember(device_id=fid, role=FormationRole.FALLBACK, reason="f"))
    for sid in (support_ids or []):
        members.append(FormationMember(device_id=sid, role=FormationRole.SUPPORT, reason="sup"))
    for rid in (relay_ids or []):
        members.append(FormationMember(device_id=rid, role=FormationRole.RELAY, reason="relay"))
    for oid in (observer_ids or []):
        members.append(FormationMember(device_id=oid, role=FormationRole.OBSERVER, reason="obs"))

    return DeviceFormationGroup(
        source_device_id=source_id,
        members=members,
        runtime_domain_intent=domain,
    )


def _trigger(
    trigger_type,
    device_id: str = "test-dev",
    *,
    health_score: Optional[float] = None,
    is_reachable: bool = True,
    reason: Optional[str] = None,
    session_id: Optional[str] = None,
):
    from core.device_formation.formation_runtime_controller import FormationTriggerEvent
    return FormationTriggerEvent(
        trigger_type=trigger_type,
        device_id=device_id,
        health_score=health_score,
        is_reachable=is_reachable,
        reason=reason,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# 1: Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        from core.device_formation.formation_runtime_controller import (
            FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY,
        )
        assert isinstance(FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY, str)
        assert "AUTHORITY" in FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY

    def test_pr2_sentinel(self):
        from core.device_formation.formation_runtime_controller import (
            FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL,
        )
        assert isinstance(FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL, str)
        assert "PR-2" in FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL

    def test_source_loss_policy(self):
        from core.device_formation.formation_runtime_controller import (
            SOURCE_LOSS_REQUIRES_AWAIT_RECOVERY_POLICY,
        )
        assert isinstance(SOURCE_LOSS_REQUIRES_AWAIT_RECOVERY_POLICY, str)
        assert "AWAIT_RECOVERY" in SOURCE_LOSS_REQUIRES_AWAIT_RECOVERY_POLICY

    def test_primary_loss_policy(self):
        from core.device_formation.formation_runtime_controller import (
            PRIMARY_LOSS_WITH_FALLBACK_TRIGGERS_RESHAPE_POLICY,
        )
        assert isinstance(PRIMARY_LOSS_WITH_FALLBACK_TRIGGERS_RESHAPE_POLICY, str)
        assert "RESHAPE" in PRIMARY_LOSS_WITH_FALLBACK_TRIGGERS_RESHAPE_POLICY

    def test_non_critical_loss_policy(self):
        from core.device_formation.formation_runtime_controller import (
            NON_CRITICAL_LOSS_CONTINUES_DEGRADED_POLICY,
        )
        assert isinstance(NON_CRITICAL_LOSS_CONTINUES_DEGRADED_POLICY, str)
        assert "CONTINUE_DEGRADED" in NON_CRITICAL_LOSS_CONTINUES_DEGRADED_POLICY


# ---------------------------------------------------------------------------
# 2–3: Enum values
# ---------------------------------------------------------------------------

class TestFormationTriggerType:
    def test_all_expected_values(self):
        from core.device_formation.formation_runtime_controller import FormationTriggerType
        expected = {
            "participant_lost", "readiness_changed", "health_degraded",
            "role_instability", "participant_joined",
        }
        actual = {t.value for t in FormationTriggerType}
        assert expected == actual


class TestDegradedContinuationDecision:
    def test_all_expected_values(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        expected = {"continue_degraded", "reshape_and_continue", "await_recovery", "abort"}
        actual = {d.value for d in DegradedContinuationDecision}
        assert expected == actual


# ---------------------------------------------------------------------------
# 4–5: Data classes
# ---------------------------------------------------------------------------

class TestFormationTriggerEvent:
    def test_construction(self):
        from core.device_formation.formation_runtime_controller import (
            FormationTriggerEvent, FormationTriggerType,
        )
        e = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id="dev-1",
            health_score=0.0,
            is_reachable=False,
        )
        assert e.device_id == "dev-1"
        assert e.health_score == 0.0

    def test_to_dict(self):
        from core.device_formation.formation_runtime_controller import (
            FormationTriggerEvent, FormationTriggerType,
        )
        e = FormationTriggerEvent(
            trigger_type=FormationTriggerType.HEALTH_DEGRADED,
            device_id="d",
            session_id="sess-1",
        )
        d = e.to_dict()
        assert d["device_id"] == "d"
        assert d["session_id"] == "sess-1"
        assert d["trigger_type"] == "health_degraded"


class TestFormationRecoveryPlan:
    def test_construction(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRecoveryPlan, DegradedContinuationDecision,
            FormationTriggerEvent, FormationTriggerType,
        )
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id="d",
        )
        plan = FormationRecoveryPlan(
            continuation_decision=DegradedContinuationDecision.ABORT,
            trigger_event=event,
            reason="test abort",
        )
        assert plan.continuation_decision == DegradedContinuationDecision.ABORT
        assert plan.reason == "test abort"

    def test_to_dict(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRecoveryPlan, DegradedContinuationDecision,
            FormationTriggerEvent, FormationTriggerType,
        )
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id="d",
        )
        plan = FormationRecoveryPlan(
            continuation_decision=DegradedContinuationDecision.AWAIT_RECOVERY,
            trigger_event=event,
            is_degraded=True,
            reason="source lost",
        )
        d = plan.to_dict()
        assert d["continuation_decision"] == "await_recovery"
        assert d["is_degraded"] is True


# ---------------------------------------------------------------------------
# 6–10: process_trigger dispatch
# ---------------------------------------------------------------------------

class TestProcessTriggerDispatch:
    def setup_method(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRuntimeController,
        )
        self.ctrl = FormationRuntimeController()

    def test_participant_lost_dispatch(self):
        from core.device_formation.formation_runtime_controller import (
            FormationTriggerType, DegradedContinuationDecision,
        )
        group = _make_group()
        event = _trigger(FormationTriggerType.PARTICIPANT_LOST, "source-dev")
        plan = self.ctrl.process_trigger(event, group)
        assert plan.continuation_decision == DegradedContinuationDecision.AWAIT_RECOVERY

    def test_readiness_changed_dispatch(self):
        from core.device_formation.formation_runtime_controller import FormationTriggerType
        group = _make_group()
        event = _trigger(FormationTriggerType.READINESS_CHANGED, "source-dev",
                         is_reachable=False)
        plan = self.ctrl.process_trigger(event, group)
        assert plan is not None

    def test_health_degraded_dispatch(self):
        from core.device_formation.formation_runtime_controller import FormationTriggerType
        group = _make_group()
        event = _trigger(FormationTriggerType.HEALTH_DEGRADED, "primary-dev",
                         health_score=0.1)
        plan = self.ctrl.process_trigger(event, group)
        assert plan is not None

    def test_role_instability_dispatch(self):
        from core.device_formation.formation_runtime_controller import FormationTriggerType
        group = _make_group()
        event = _trigger(FormationTriggerType.ROLE_INSTABILITY, "source-dev")
        plan = self.ctrl.process_trigger(event, group)
        assert plan is not None

    def test_participant_joined_dispatch(self):
        from core.device_formation.formation_runtime_controller import FormationTriggerType
        group = _make_group()
        event = _trigger(FormationTriggerType.PARTICIPANT_JOINED, "new-dev")
        plan = self.ctrl.process_trigger(event, group)
        assert plan is not None


# ---------------------------------------------------------------------------
# 11–19: on_participant_lost
# ---------------------------------------------------------------------------

class TestOnParticipantLost:
    def setup_method(self):
        from core.device_formation.formation_runtime_controller import FormationRuntimeController
        self.ctrl = FormationRuntimeController()

    def _event(self, device_id):
        from core.device_formation.formation_runtime_controller import (
            FormationTriggerEvent, FormationTriggerType,
        )
        return FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id=device_id,
            is_reachable=False,
        )

    def test_source_lost_await_recovery(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group()
        plan = self.ctrl.on_participant_lost(self._event("source-dev"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.AWAIT_RECOVERY
        assert plan.is_degraded is True
        assert "source-dev" in plan.affected_device_ids

    def test_primary_lost_with_fallback_reshape(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group(fallback_ids=["fallback-1"])
        plan = self.ctrl.on_participant_lost(self._event("primary-dev"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.RESHAPE_AND_CONTINUE
        assert plan.is_degraded is True
        assert "primary-dev" in plan.affected_device_ids

    def test_primary_lost_no_fallback_abort(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group()  # no fallback
        plan = self.ctrl.on_participant_lost(self._event("primary-dev"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.ABORT
        assert plan.is_degraded is True

    def test_support_lost_continue_degraded(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group(support_ids=["sup-1"])
        plan = self.ctrl.on_participant_lost(self._event("sup-1"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED
        assert plan.is_degraded is True

    def test_relay_lost_continue_degraded(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group(relay_ids=["relay-1"])
        plan = self.ctrl.on_participant_lost(self._event("relay-1"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED

    def test_observer_lost_continue_degraded(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group(observer_ids=["obs-1"])
        plan = self.ctrl.on_participant_lost(self._event("obs-1"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED

    def test_fallback_lost_continue_degraded(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group(fallback_ids=["fb-1"])
        plan = self.ctrl.on_participant_lost(self._event("fb-1"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED
        assert plan.is_degraded is True

    def test_device_not_in_formation_no_op(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group()
        plan = self.ctrl.on_participant_lost(self._event("unknown-dev"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED
        assert plan.is_degraded is False

    def test_empty_formation_no_crash(self):
        from core.device_formation.formation_group import EMPTY_FORMATION_GROUP
        plan = self.ctrl.on_participant_lost(self._event("any-dev"), EMPTY_FORMATION_GROUP)
        assert plan is not None


# ---------------------------------------------------------------------------
# 20–21: on_readiness_changed
# ---------------------------------------------------------------------------

class TestOnReadinessChanged:
    def setup_method(self):
        from core.device_formation.formation_runtime_controller import FormationRuntimeController
        self.ctrl = FormationRuntimeController()

    def test_device_becoming_unready_delegates_to_lost(self):
        from core.device_formation.formation_runtime_controller import (
            DegradedContinuationDecision, FormationTriggerEvent, FormationTriggerType,
        )
        group = _make_group()
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.READINESS_CHANGED,
            device_id="source-dev",
            is_reachable=False,
            health_score=0.0,
        )
        plan = self.ctrl.on_readiness_changed(event, group)
        assert plan.continuation_decision == DegradedContinuationDecision.AWAIT_RECOVERY

    def test_device_becoming_ready_no_action(self):
        from core.device_formation.formation_runtime_controller import (
            DegradedContinuationDecision, FormationTriggerEvent, FormationTriggerType,
        )
        group = _make_group()
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.READINESS_CHANGED,
            device_id="support-dev",
            is_reachable=True,
            health_score=0.9,
        )
        plan = self.ctrl.on_readiness_changed(event, group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED
        assert plan.is_degraded is False


# ---------------------------------------------------------------------------
# 22–24: on_health_degraded
# ---------------------------------------------------------------------------

class TestOnHealthDegraded:
    def setup_method(self):
        from core.device_formation.formation_runtime_controller import FormationRuntimeController
        self.ctrl = FormationRuntimeController()

    def _event(self, device_id, health_score, is_reachable=True):
        from core.device_formation.formation_runtime_controller import (
            FormationTriggerEvent, FormationTriggerType,
        )
        return FormationTriggerEvent(
            trigger_type=FormationTriggerType.HEALTH_DEGRADED,
            device_id=device_id,
            health_score=health_score,
            is_reachable=is_reachable,
        )

    def test_below_unhealthy_delegates_to_lost(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group()
        plan = self.ctrl.on_health_degraded(self._event("source-dev", 0.1), group)
        assert plan.continuation_decision == DegradedContinuationDecision.AWAIT_RECOVERY

    def test_degraded_band_continue_degraded(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group()
        plan = self.ctrl.on_health_degraded(self._event("primary-dev", 0.5), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED
        assert plan.is_degraded is True
        assert "primary-dev" in plan.affected_device_ids

    def test_above_degraded_threshold_no_action(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group()
        plan = self.ctrl.on_health_degraded(self._event("primary-dev", 0.8), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED
        assert plan.is_degraded is False


# ---------------------------------------------------------------------------
# 25–28: on_role_instability
# ---------------------------------------------------------------------------

class TestOnRoleInstability:
    def setup_method(self):
        from core.device_formation.formation_runtime_controller import FormationRuntimeController
        self.ctrl = FormationRuntimeController()

    def _event(self, device_id):
        from core.device_formation.formation_runtime_controller import (
            FormationTriggerEvent, FormationTriggerType,
        )
        return FormationTriggerEvent(
            trigger_type=FormationTriggerType.ROLE_INSTABILITY,
            device_id=device_id,
        )

    def test_source_role_instability_await_recovery(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group()
        plan = self.ctrl.on_role_instability(self._event("source-dev"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.AWAIT_RECOVERY

    def test_primary_role_instability_with_fallback_reshape(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group(fallback_ids=["fb-1"])
        plan = self.ctrl.on_role_instability(self._event("primary-dev"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.RESHAPE_AND_CONTINUE

    def test_support_role_instability_continue_degraded(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group(support_ids=["sup-1"])
        plan = self.ctrl.on_role_instability(self._event("sup-1"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED

    def test_device_not_in_formation(self):
        from core.device_formation.formation_runtime_controller import DegradedContinuationDecision
        group = _make_group()
        plan = self.ctrl.on_role_instability(self._event("ghost-dev"), group)
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED
        assert plan.is_degraded is False


# ---------------------------------------------------------------------------
# 29–31: on_participant_joined
# ---------------------------------------------------------------------------

class TestOnParticipantJoined:
    def setup_method(self):
        from core.device_formation.formation_runtime_controller import FormationRuntimeController
        self.ctrl = FormationRuntimeController()

    def _event(self, device_id):
        from core.device_formation.formation_runtime_controller import (
            FormationTriggerEvent, FormationTriggerType,
        )
        return FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_JOINED,
            device_id=device_id,
        )

    def test_no_primary_suggests_re_resolve(self):
        group = _make_group(primary_id=None)
        plan = self.ctrl.on_participant_joined(self._event("new-dev"), group)
        assert plan.is_degraded is True
        assert plan.recovery_hints.get("suggest_re_resolve") is True

    def test_healthy_formation_no_action(self):
        group = _make_group(fallback_ids=["fb-1"])
        plan = self.ctrl.on_participant_joined(self._event("extra-dev"), group)
        assert plan.is_degraded is False
        assert plan.recovery_hints.get("suggest_re_resolve") is False

    def test_no_fallback_suggests_re_resolve(self):
        group = _make_group()  # no fallback
        plan = self.ctrl.on_participant_joined(self._event("new-dev"), group)
        assert plan.is_degraded is True


# ---------------------------------------------------------------------------
# 32: Reshape after PRIMARY loss produces a new primary
# ---------------------------------------------------------------------------

class TestReshapeProducesNewPrimary:
    def test_new_primary_after_primary_loss(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRuntimeController, DegradedContinuationDecision,
        )
        from core.device_formation.formation_role import FormationRole
        group = _make_group(fallback_ids=["fb-promo"])
        ctrl = FormationRuntimeController()
        event = _trigger(
            __import__(
                "core.device_formation.formation_runtime_controller",
                fromlist=["FormationTriggerType"],
            ).FormationTriggerType.PARTICIPANT_LOST,
            "primary-dev",
            is_reachable=False,
        )
        plan = ctrl.on_participant_lost(event, group)
        assert plan.continuation_decision == DegradedContinuationDecision.RESHAPE_AND_CONTINUE
        # New formation should have a PRIMARY_EXECUTION member
        roles = [
            getattr(m, "role", None)
            for m in getattr(plan.reshaped_formation, "members", [])
        ]
        assert FormationRole.PRIMARY_EXECUTION in roles


# ---------------------------------------------------------------------------
# 33: to_dict contains expected keys
# ---------------------------------------------------------------------------

class TestRecoveryPlanToDict:
    def test_to_dict_keys(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRecoveryPlan, DegradedContinuationDecision,
            FormationTriggerEvent, FormationTriggerType,
        )
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id="d",
        )
        plan = FormationRecoveryPlan(
            continuation_decision=DegradedContinuationDecision.ABORT,
            trigger_event=event,
            affected_device_ids=["d"],
            is_degraded=True,
            reason="abort",
        )
        d = plan.to_dict()
        for key in (
            "continuation_decision", "trigger_event", "affected_device_ids",
            "is_degraded", "reason", "recovery_hints",
        ):
            assert key in d


# ---------------------------------------------------------------------------
# 34: Never raises on None formation
# ---------------------------------------------------------------------------

class TestNeverRaises:
    def test_none_formation_no_crash(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRuntimeController, FormationTriggerType,
        )
        ctrl = FormationRuntimeController()
        event = _trigger(FormationTriggerType.PARTICIPANT_LOST, "dev-1")
        plan = ctrl.process_trigger(event, None)
        assert plan is not None

    def test_participant_lost_none_formation(self):
        from core.device_formation.formation_runtime_controller import FormationRuntimeController
        ctrl = FormationRuntimeController()
        event = _trigger(
            __import__(
                "core.device_formation.formation_runtime_controller",
                fromlist=["FormationTriggerType"],
            ).FormationTriggerType.PARTICIPANT_LOST,
            "dev-x",
        )
        plan = ctrl.on_participant_lost(event, None)
        assert plan is not None


# ---------------------------------------------------------------------------
# 35: __init__ exports
# ---------------------------------------------------------------------------

class TestInitExports:
    def test_controller_symbols_exported(self):
        from core.device_formation import (
            FormationTriggerType,
            FormationTriggerEvent,
            DegradedContinuationDecision,
            FormationRecoveryPlan,
            FormationRuntimeController,
            on_participant_lost,
            on_readiness_changed,
            on_health_degraded,
            on_role_instability,
            on_participant_joined,
            FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY,
            FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL,
        )
        assert FormationRuntimeController is not None
        assert isinstance(FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY, str)
        assert isinstance(FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL, str)


# ---------------------------------------------------------------------------
# 36: Module-level convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def _group(self):
        return _make_group()

    def test_on_participant_lost_convenience(self):
        from core.device_formation.formation_runtime_controller import (
            on_participant_lost, FormationTriggerEvent, FormationTriggerType,
        )
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id="source-dev",
            is_reachable=False,
        )
        plan = on_participant_lost(event, self._group())
        assert plan is not None

    def test_on_readiness_changed_convenience(self):
        from core.device_formation.formation_runtime_controller import (
            on_readiness_changed, FormationTriggerEvent, FormationTriggerType,
        )
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.READINESS_CHANGED,
            device_id="primary-dev",
            is_reachable=False,
            health_score=0.0,
        )
        plan = on_readiness_changed(event, self._group())
        assert plan is not None

    def test_on_health_degraded_convenience(self):
        from core.device_formation.formation_runtime_controller import (
            on_health_degraded, FormationTriggerEvent, FormationTriggerType,
        )
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.HEALTH_DEGRADED,
            device_id="primary-dev",
            health_score=0.1,
        )
        plan = on_health_degraded(event, self._group())
        assert plan is not None

    def test_on_role_instability_convenience(self):
        from core.device_formation.formation_runtime_controller import (
            on_role_instability, FormationTriggerEvent, FormationTriggerType,
        )
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.ROLE_INSTABILITY,
            device_id="source-dev",
        )
        plan = on_role_instability(event, self._group())
        assert plan is not None

    def test_on_participant_joined_convenience(self):
        from core.device_formation.formation_runtime_controller import (
            on_participant_joined, FormationTriggerEvent, FormationTriggerType,
        )
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_JOINED,
            device_id="new-dev",
        )
        plan = on_participant_joined(event, self._group())
        assert plan is not None


# ---------------------------------------------------------------------------
# 37: Custom thresholds affect health_degraded routing
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_custom_unhealthy_threshold(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRuntimeController, DegradedContinuationDecision,
            FormationTriggerEvent, FormationTriggerType,
        )
        # With a high unhealthy threshold (0.8), score=0.5 is below threshold
        # and should trigger the lost path for PRIMARY → ABORT (no fallback)
        ctrl = FormationRuntimeController(unhealthy_threshold=0.8, degraded_threshold=0.95)
        group = _make_group()
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.HEALTH_DEGRADED,
            device_id="primary-dev",
            health_score=0.5,
        )
        plan = ctrl.on_health_degraded(event, group)
        # 0.5 < 0.8 (unhealthy) → treated as lost → PRIMARY with no fallback → ABORT
        assert plan.continuation_decision == DegradedContinuationDecision.ABORT


# ---------------------------------------------------------------------------
# 38–39: recovery_hints are populated
# ---------------------------------------------------------------------------

class TestRecoveryHints:
    def test_primary_loss_recovery_hints(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRuntimeController, FormationTriggerEvent, FormationTriggerType,
        )
        ctrl = FormationRuntimeController()
        group = _make_group(fallback_ids=["fb-1"])
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id="primary-dev",
            is_reachable=False,
        )
        plan = ctrl.on_participant_lost(event, group)
        assert plan.recovery_hints.get("primary_lost") is True

    def test_source_loss_recovery_hints(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRuntimeController, FormationTriggerEvent, FormationTriggerType,
        )
        ctrl = FormationRuntimeController()
        group = _make_group()
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_LOST,
            device_id="source-dev",
            is_reachable=False,
        )
        plan = ctrl.on_participant_lost(event, group)
        assert plan.recovery_hints.get("source_lost") is True
        assert plan.recovery_hints.get("device_id") == "source-dev"


# ---------------------------------------------------------------------------
# 40: Unknown trigger type — safe no-op
# ---------------------------------------------------------------------------

class TestUnknownTriggerType:
    def test_unknown_trigger_returns_continue_degraded(self):
        from core.device_formation.formation_runtime_controller import (
            FormationRuntimeController, FormationTriggerEvent, FormationTriggerType,
            DegradedContinuationDecision,
        )
        from unittest.mock import patch

        ctrl = FormationRuntimeController()
        group = _make_group()
        event = FormationTriggerEvent(
            trigger_type=FormationTriggerType.PARTICIPANT_JOINED,
            device_id="dev-x",
        )
        # Force the trigger_type to a string value that won't match any enum check
        # in process_trigger, exercising the "unknown trigger type" fallback path.
        with patch.object(event, "trigger_type", "completely_unknown_trigger"):
            plan = ctrl.process_trigger(event, group)
        assert plan is not None
        assert plan.continuation_decision == DegradedContinuationDecision.CONTINUE_DEGRADED
        assert "unknown" in plan.reason

    def test_any_valid_trigger_returns_valid_decision(self):
        """Every valid FormationTriggerType produces a valid DegradedContinuationDecision."""
        from core.device_formation.formation_runtime_controller import (
            FormationRuntimeController, FormationTriggerEvent, FormationTriggerType,
            DegradedContinuationDecision,
        )
        ctrl = FormationRuntimeController()
        group = _make_group()
        for trigger_type in FormationTriggerType:
            event = FormationTriggerEvent(
                trigger_type=trigger_type,
                device_id="dev-x",
            )
            plan = ctrl.process_trigger(event, group)
            assert isinstance(plan.continuation_decision, DegradedContinuationDecision), (
                f"trigger {trigger_type} returned non-DegradedContinuationDecision"
            )
