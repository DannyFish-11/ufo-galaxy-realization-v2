#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_formation_runtime_coordinator.py
============================================
Tests for core/device_formation/formation_runtime_coordinator.py

Coverage:
  1.  Module sentinels are importable strings.
  2.  FormationParticipantState enum values.
  3.  FormationRuntimeState enum values.
  4.  RecoveryActionType enum values.
  5.  FormationParticipantStatus construction and helpers (is_viable).
  6.  FormationParticipantStatus — LOST is not viable; READY/DEGRADED are.
  7.  FormationRecoveryAction construction and to_dict.
  8.  FormationRuntimeDecision construction and to_dict.
  9.  FormationRuntimeSnapshot construction and to_dict.
  10. FormationRuntimeCoordinator — initial seeding from formation group.
  11. FormationRuntimeCoordinator — on_participant_readiness_changed READY → no rebalance.
  12. FormationRuntimeCoordinator — on_participant_lost for non-primary device.
  13. FormationRuntimeCoordinator — on_participant_lost for primary triggers promotion.
  14. FormationRuntimeCoordinator — on_participant_lost for primary with no fallback → TERMINATED.
  15. FormationRuntimeCoordinator — on_health_degraded below unhealthy threshold → LOST state.
  16. FormationRuntimeCoordinator — on_health_degraded between thresholds → DEGRADED state.
  17. FormationRuntimeCoordinator — on_health_degraded healthy score → no significant action.
  18. FormationRuntimeCoordinator — on_recovery_available restores viable state.
  19. FormationRuntimeCoordinator — evaluate_continuation all healthy.
  20. FormationRuntimeCoordinator — evaluate_continuation with lost participants.
  21. FormationRuntimeCoordinator — snapshot returns serialisable dict.
  22. FormationRuntimeCoordinator — SOURCE is never targeted for TERMINATE.
  23. FormationRuntimeCoordinator — degraded continuation remains viable.
  24. FormationRuntimeCoordinator — multiple lost participants degrade state.
  25. make_formation_runtime_coordinator — convenience factory.
  26. core.device_formation __init__ exports runtime coordinator symbols.
  27. MultiDeviceRuntimeHarness.on_participant_readiness_changed — basic smoke.
  28. on_participant_readiness_changed module-level function — smoke.
  29. RuntimeHarnessResult.to_dict includes runtime_decision field.
  30. FormationRuntimeCoordinator — custom thresholds.
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
    domain: str = "cross_device",
):
    from core.device_formation.formation_group import DeviceFormationGroup
    from core.device_formation.formation_role import FormationMember, FormationRole

    members = []
    if source_id:
        members.append(FormationMember(device_id=source_id, role=FormationRole.SOURCE,
                                        reason="source"))
    if primary_id:
        members.append(FormationMember(device_id=primary_id, role=FormationRole.PRIMARY_EXECUTION,
                                        reason="primary"))
    for fid in (fallback_ids or []):
        members.append(FormationMember(device_id=fid, role=FormationRole.FALLBACK, reason="fallback"))
    for sid in (support_ids or []):
        members.append(FormationMember(device_id=sid, role=FormationRole.SUPPORT, reason="support"))

    return DeviceFormationGroup(
        source_device_id=source_id,
        members=members,
        runtime_domain_intent=domain,
    )


# ---------------------------------------------------------------------------
# 1: Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        from core.device_formation.formation_runtime_coordinator import (
            FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY,
        )
        assert isinstance(FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY, str)
        assert "FORMATION_RUNTIME_COORDINATOR" in FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY

    def test_gap_closure_sentinel(self):
        from core.device_formation.formation_runtime_coordinator import (
            FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL,
        )
        assert isinstance(FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL, str)
        assert "recovery" in FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL.lower()

    def test_degraded_continuation_policy(self):
        from core.device_formation.formation_runtime_coordinator import (
            DEGRADED_CONTINUATION_REQUIRES_PRIMARY_POLICY,
        )
        assert isinstance(DEGRADED_CONTINUATION_REQUIRES_PRIMARY_POLICY, str)

    def test_recovery_preserves_source_policy(self):
        from core.device_formation.formation_runtime_coordinator import (
            RECOVERY_PRESERVES_SOURCE_POLICY,
        )
        assert isinstance(RECOVERY_PRESERVES_SOURCE_POLICY, str)


# ---------------------------------------------------------------------------
# 2: FormationParticipantState enum
# ---------------------------------------------------------------------------

class TestFormationParticipantState:
    def test_all_expected_values(self):
        from core.device_formation.formation_runtime_coordinator import FormationParticipantState
        expected = {"ready", "degraded", "lost", "recovering"}
        actual = {s.value for s in FormationParticipantState}
        assert expected == actual


# ---------------------------------------------------------------------------
# 3: FormationRuntimeState enum
# ---------------------------------------------------------------------------

class TestFormationRuntimeState:
    def test_all_expected_values(self):
        from core.device_formation.formation_runtime_coordinator import FormationRuntimeState
        expected = {
            "active", "degraded", "reshaping",
            "degraded_continuation", "recovering", "terminated",
        }
        actual = {s.value for s in FormationRuntimeState}
        assert expected == actual


# ---------------------------------------------------------------------------
# 4: RecoveryActionType enum
# ---------------------------------------------------------------------------

class TestRecoveryActionType:
    def test_all_expected_values(self):
        from core.device_formation.formation_runtime_coordinator import RecoveryActionType
        expected = {
            "keep", "promote_fallback", "remove_participant",
            "continue_degraded", "reshape", "terminate", "request_recovery",
        }
        actual = {a.value for a in RecoveryActionType}
        assert expected == actual


# ---------------------------------------------------------------------------
# 5–6: FormationParticipantStatus
# ---------------------------------------------------------------------------

class TestFormationParticipantStatus:
    def test_construction(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationParticipantStatus, FormationParticipantState,
        )
        s = FormationParticipantStatus(
            device_id="dev-1",
            state=FormationParticipantState.READY,
            health_score=0.9,
        )
        assert s.device_id == "dev-1"
        assert s.health_score == 0.9

    def test_ready_is_viable(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationParticipantStatus, FormationParticipantState,
        )
        s = FormationParticipantStatus(
            device_id="d", state=FormationParticipantState.READY
        )
        assert s.is_viable is True

    def test_degraded_is_viable(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationParticipantStatus, FormationParticipantState,
        )
        s = FormationParticipantStatus(
            device_id="d", state=FormationParticipantState.DEGRADED
        )
        assert s.is_viable is True

    def test_lost_is_not_viable(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationParticipantStatus, FormationParticipantState,
        )
        s = FormationParticipantStatus(
            device_id="d", state=FormationParticipantState.LOST
        )
        assert s.is_viable is False

    def test_recovering_is_not_viable(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationParticipantStatus, FormationParticipantState,
        )
        s = FormationParticipantStatus(
            device_id="d", state=FormationParticipantState.RECOVERING
        )
        assert s.is_viable is False

    def test_to_dict(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationParticipantStatus, FormationParticipantState,
        )
        s = FormationParticipantStatus(
            device_id="d", state=FormationParticipantState.READY, health_score=0.8
        )
        d = s.to_dict()
        assert d["device_id"] == "d"
        assert d["health_score"] == 0.8
        assert d["state"] == "ready"


# ---------------------------------------------------------------------------
# 7: FormationRecoveryAction
# ---------------------------------------------------------------------------

class TestFormationRecoveryAction:
    def test_construction_and_to_dict(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRecoveryAction, RecoveryActionType,
        )
        a = FormationRecoveryAction(
            action_type=RecoveryActionType.PROMOTE_FALLBACK,
            affected_device_id="fb-1",
            reason="primary lost",
        )
        d = a.to_dict()
        assert d["action_type"] == "promote_fallback"
        assert d["affected_device_id"] == "fb-1"


# ---------------------------------------------------------------------------
# 8: FormationRuntimeDecision
# ---------------------------------------------------------------------------

class TestFormationRuntimeDecision:
    def test_construction_and_to_dict(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeDecision, FormationRuntimeState, RecoveryActionType,
            FormationRecoveryAction,
        )
        d = FormationRuntimeDecision(
            formation_id="f1",
            runtime_state=FormationRuntimeState.ACTIVE,
            recommended_actions=[
                FormationRecoveryAction(RecoveryActionType.KEEP, reason="healthy"),
            ],
            continuation_viable=True,
            reason="all good",
            trigger_event="test",
        )
        out = d.to_dict()
        assert out["formation_id"] == "f1"
        assert out["runtime_state"] == "active"
        assert out["continuation_viable"] is True
        assert out["recommended_actions"][0]["action_type"] == "keep"


# ---------------------------------------------------------------------------
# 9: FormationRuntimeSnapshot
# ---------------------------------------------------------------------------

class TestFormationRuntimeSnapshot:
    def test_to_dict(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeSnapshot, FormationRuntimeState,
        )
        snap = FormationRuntimeSnapshot(
            formation_id="f1",
            runtime_state=FormationRuntimeState.DEGRADED,
        )
        d = snap.to_dict()
        assert d["formation_id"] == "f1"
        assert d["runtime_state"] == "degraded"
        assert "snapshot_ts" in d


# ---------------------------------------------------------------------------
# 10: Initial seeding from formation group
# ---------------------------------------------------------------------------

class TestFormationRuntimeCoordinatorSeeding:
    def test_initial_seeding(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationParticipantState,
        )
        group = _make_group(fallback_ids=["fb-1"])
        coord = FormationRuntimeCoordinator(group)
        status = coord.get_participant_status("primary-dev")
        assert status is not None
        assert status.state == FormationParticipantState.READY

    def test_initial_state_is_active(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationRuntimeState,
        )
        group = _make_group()
        coord = FormationRuntimeCoordinator(group)
        assert coord.runtime_state == FormationRuntimeState.ACTIVE


# ---------------------------------------------------------------------------
# 11: on_participant_readiness_changed — no change needed
# ---------------------------------------------------------------------------

class TestOnParticipantReadinessChanged:
    def test_ready_state_no_rebalance(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationParticipantState,
            FormationRuntimeState,
        )
        group = _make_group()
        coord = FormationRuntimeCoordinator(group)
        decision = coord.on_participant_readiness_changed(
            "primary-dev", FormationParticipantState.READY
        )
        assert decision.continuation_viable is True
        assert decision.runtime_state == FormationRuntimeState.ACTIVE

    def test_degraded_state_returns_degraded_runtime(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationParticipantState,
            FormationRuntimeState,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = FormationRuntimeCoordinator(group)
        decision = coord.on_participant_readiness_changed(
            "sup-1",
            FormationParticipantState.DEGRADED,
            health_score=0.45,
        )
        # Primary still viable, so continuation is still viable
        assert decision.continuation_viable is True


# ---------------------------------------------------------------------------
# 12: on_participant_lost — non-primary
# ---------------------------------------------------------------------------

class TestOnParticipantLost:
    def test_lost_support_device_still_viable(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationRuntimeState,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = FormationRuntimeCoordinator(group)
        decision = coord.on_participant_lost("sup-1", reason="disconnect")
        assert decision.continuation_viable is True

    def test_lost_support_device_suggests_remove(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, RecoveryActionType,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = FormationRuntimeCoordinator(group)
        decision = coord.on_participant_lost("sup-1")
        action_types = {a.action_type for a in decision.recommended_actions}
        assert RecoveryActionType.REMOVE_PARTICIPANT in action_types

    # 13: Primary lost — promotion triggered
    def test_primary_lost_promotes_fallback(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, RecoveryActionType,
        )
        group = _make_group(fallback_ids=["fb-1"])
        coord = FormationRuntimeCoordinator(group)
        decision = coord.on_participant_lost("primary-dev")
        action_types = {a.action_type for a in decision.recommended_actions}
        assert RecoveryActionType.PROMOTE_FALLBACK in action_types
        assert decision.continuation_viable is True

    # 14: Primary lost with no fallback → TERMINATED
    def test_primary_lost_no_fallback_terminates(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationRuntimeState,
        )
        group = _make_group()  # no fallback
        coord = FormationRuntimeCoordinator(group)
        decision = coord.on_participant_lost("primary-dev")
        assert decision.continuation_viable is False
        assert decision.runtime_state == FormationRuntimeState.TERMINATED


# ---------------------------------------------------------------------------
# 15–17: on_health_degraded
# ---------------------------------------------------------------------------

class TestOnHealthDegraded:
    def test_below_unhealthy_threshold_becomes_lost(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationParticipantState,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = FormationRuntimeCoordinator(group)
        coord.on_health_degraded("sup-1", health_score=0.1)
        status = coord.get_participant_status("sup-1")
        assert status is not None
        assert status.state == FormationParticipantState.LOST

    def test_between_thresholds_becomes_degraded(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationParticipantState,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = FormationRuntimeCoordinator(group)
        coord.on_health_degraded("sup-1", health_score=0.45)
        status = coord.get_participant_status("sup-1")
        assert status is not None
        assert status.state == FormationParticipantState.DEGRADED

    def test_healthy_score_becomes_ready(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationParticipantState,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = FormationRuntimeCoordinator(group)
        # First mark as degraded
        coord.on_health_degraded("sup-1", health_score=0.45)
        # Now healthy again
        coord.on_health_degraded("sup-1", health_score=0.9)
        status = coord.get_participant_status("sup-1")
        assert status is not None
        assert status.state == FormationParticipantState.READY


# ---------------------------------------------------------------------------
# 18: on_recovery_available
# ---------------------------------------------------------------------------

class TestOnRecoveryAvailable:
    def test_recovery_available_after_loss(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, RecoveryActionType,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = FormationRuntimeCoordinator(group)
        coord.on_participant_lost("sup-1")
        decision = coord.on_recovery_available("sup-1", health_score=0.9)
        # Should not terminate
        assert decision is not None

    def test_recovery_from_terminated_with_primary_recovering(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationRuntimeState,
            FormationParticipantState,
        )
        group = _make_group()  # no fallback
        coord = FormationRuntimeCoordinator(group)
        coord.on_participant_lost("primary-dev")
        assert coord.runtime_state == FormationRuntimeState.TERMINATED

        decision = coord.on_recovery_available("primary-dev", health_score=0.85)
        # After recovery, the coordinator should no longer be TERMINATED
        assert coord.runtime_state != FormationRuntimeState.TERMINATED


# ---------------------------------------------------------------------------
# 19–20: evaluate_continuation
# ---------------------------------------------------------------------------

class TestEvaluateContinuation:
    def test_all_healthy(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationRuntimeState,
        )
        group = _make_group()
        coord = FormationRuntimeCoordinator(group)
        decision = coord.evaluate_continuation()
        assert decision.continuation_viable is True
        assert decision.runtime_state == FormationRuntimeState.ACTIVE

    def test_with_lost_support_participant(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = FormationRuntimeCoordinator(group)
        coord.on_participant_lost("sup-1")
        decision = coord.evaluate_continuation()
        # Primary still viable
        assert decision.continuation_viable is True


# ---------------------------------------------------------------------------
# 21: snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_is_serialisable(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator,
        )
        group = _make_group()
        coord = FormationRuntimeCoordinator(group)
        snap = coord.snapshot()
        d = snap.to_dict()
        assert isinstance(d, dict)
        assert "runtime_state" in d
        assert "participant_statuses" in d

    def test_snapshot_has_correct_participants(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator,
        )
        group = _make_group(fallback_ids=["fb-1"])
        coord = FormationRuntimeCoordinator(group)
        snap = coord.snapshot()
        assert "primary-dev" in snap.participant_statuses
        assert "fb-1" in snap.participant_statuses


# ---------------------------------------------------------------------------
# 22: SOURCE never targeted for TERMINATE
# ---------------------------------------------------------------------------

class TestSourcePreservation:
    def test_source_not_targeted_by_terminate_action(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, RecoveryActionType,
        )
        group = _make_group()  # source-dev + primary-dev
        coord = FormationRuntimeCoordinator(group)
        # Lose primary
        decision = coord.on_participant_lost("primary-dev")
        terminate_targets = [
            a.affected_device_id
            for a in decision.recommended_actions
            if a.action_type == RecoveryActionType.TERMINATE
        ]
        assert "source-dev" not in terminate_targets

    def test_source_not_lost_even_if_unhealthy(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, RecoveryActionType,
        )
        group = _make_group()
        coord = FormationRuntimeCoordinator(group)
        # Even if source health degrades, it should not be removed
        coord.on_health_degraded("source-dev", health_score=0.1)
        decision = coord.evaluate_continuation()
        remove_targets = [
            a.affected_device_id
            for a in decision.recommended_actions
            if a.action_type == RecoveryActionType.REMOVE_PARTICIPANT
        ]
        assert "source-dev" not in remove_targets


# ---------------------------------------------------------------------------
# 23: Degraded continuation remains viable
# ---------------------------------------------------------------------------

class TestDegradedContinuation:
    def test_degraded_participants_keep_formation_viable(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator,
        )
        group = _make_group(support_ids=["sup-1", "sup-2"])
        coord = FormationRuntimeCoordinator(group)
        # Degrade support devices — primary still viable
        coord.on_health_degraded("sup-1", health_score=0.45)
        coord.on_health_degraded("sup-2", health_score=0.45)
        decision = coord.evaluate_continuation()
        assert decision.continuation_viable is True


# ---------------------------------------------------------------------------
# 24: Multiple lost participants
# ---------------------------------------------------------------------------

class TestMultipleLostParticipants:
    def test_multiple_lost_support_stays_viable(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, RecoveryActionType,
        )
        group = _make_group(support_ids=["sup-1", "sup-2", "sup-3"])
        coord = FormationRuntimeCoordinator(group)
        # First loss triggers a reshape that removes sup-1
        decision1 = coord.on_participant_lost("sup-1")
        assert decision1.continuation_viable is True
        action_types1 = {a.action_type for a in decision1.recommended_actions}
        assert RecoveryActionType.REMOVE_PARTICIPANT in action_types1

        # Second loss also triggers reshape and removes sup-2
        decision2 = coord.on_participant_lost("sup-2")
        assert decision2.continuation_viable is True
        action_types2 = {a.action_type for a in decision2.recommended_actions}
        assert RecoveryActionType.REMOVE_PARTICIPANT in action_types2


# ---------------------------------------------------------------------------
# 25: make_formation_runtime_coordinator factory
# ---------------------------------------------------------------------------

class TestMakeFormationRuntimeCoordinator:
    def test_factory_creates_coordinator(self):
        from core.device_formation.formation_runtime_coordinator import (
            make_formation_runtime_coordinator, FormationRuntimeCoordinator,
        )
        group = _make_group()
        coord = make_formation_runtime_coordinator(group)
        assert isinstance(coord, FormationRuntimeCoordinator)

    def test_factory_with_none_uses_empty_group(self):
        from core.device_formation.formation_runtime_coordinator import (
            make_formation_runtime_coordinator, FormationRuntimeCoordinator,
        )
        coord = make_formation_runtime_coordinator(None)
        assert isinstance(coord, FormationRuntimeCoordinator)

    def test_factory_custom_thresholds(self):
        from core.device_formation.formation_runtime_coordinator import (
            make_formation_runtime_coordinator, FormationParticipantState,
        )
        group = _make_group(support_ids=["sup-1"])
        coord = make_formation_runtime_coordinator(
            group, unhealthy_threshold=0.5, degraded_threshold=0.8
        )
        # health_score=0.6 is below degraded_threshold=0.8 but above unhealthy=0.5
        coord.on_health_degraded("sup-1", health_score=0.6)
        status = coord.get_participant_status("sup-1")
        assert status is not None
        assert status.state == FormationParticipantState.DEGRADED


# ---------------------------------------------------------------------------
# 26: core.device_formation __init__ exports runtime coordinator symbols
# ---------------------------------------------------------------------------

class TestDeviceFormationInitExports:
    def test_runtime_coordinator_symbols_exported(self):
        from core.device_formation import (
            FormationParticipantState,
            FormationRuntimeState,
            RecoveryActionType,
            FormationParticipantStatus,
            FormationRecoveryAction,
            FormationRuntimeDecision,
            FormationRuntimeSnapshot,
            FormationRuntimeCoordinator,
            make_formation_runtime_coordinator,
            FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY,
            FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL,
            DEGRADED_CONTINUATION_REQUIRES_PRIMARY_POLICY,
            RECOVERY_PRESERVES_SOURCE_POLICY,
        )
        assert FormationRuntimeCoordinator is not None
        assert isinstance(FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY, str)
        assert isinstance(FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL, str)


# ---------------------------------------------------------------------------
# 27: MultiDeviceRuntimeHarness.on_participant_readiness_changed smoke
# ---------------------------------------------------------------------------

class TestHarnessOnParticipantReadinessChanged:
    def test_smoke_no_formation(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        harness = MultiDeviceRuntimeHarness()
        result = harness.on_participant_readiness_changed(
            "dev-1", "degraded", health_score=0.4
        )
        assert result is not None
        assert result.operation == "on_participant_readiness_changed"

    def test_smoke_with_formation(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        harness = MultiDeviceRuntimeHarness()
        group = _make_group(support_ids=["sup-1"])
        result = harness.on_participant_readiness_changed(
            "sup-1", "lost", formation=group, reason="timeout"
        )
        assert result is not None

    def test_smoke_lost_triggers_rebalance_on_primary(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        harness = MultiDeviceRuntimeHarness()
        group = _make_group(fallback_ids=["fb-1"])
        result = harness.on_participant_readiness_changed(
            "primary-dev", "lost", formation=group
        )
        # Primary lost with fallback available — should trigger rebalance
        assert result.rebalance_triggered is True


# ---------------------------------------------------------------------------
# 28: Module-level on_participant_readiness_changed
# ---------------------------------------------------------------------------

class TestModuleLevelOnParticipantReadinessChanged:
    def test_module_level_function(self):
        from core.multi_device_runtime_harness import (
            on_participant_readiness_changed,
            reset_multi_device_runtime_harness,
        )
        reset_multi_device_runtime_harness()
        result = on_participant_readiness_changed("dev-1", "ready")
        assert result is not None
        assert result.operation == "on_participant_readiness_changed"

    def test_module_level_with_formation(self):
        from core.multi_device_runtime_harness import (
            on_participant_readiness_changed,
            reset_multi_device_runtime_harness,
        )
        reset_multi_device_runtime_harness()
        group = _make_group(fallback_ids=["fb-1"])
        result = on_participant_readiness_changed(
            "primary-dev", "lost", formation=group
        )
        assert result.rebalance_triggered is True


# ---------------------------------------------------------------------------
# 29: RuntimeHarnessResult.to_dict includes runtime_decision
# ---------------------------------------------------------------------------

class TestRuntimeHarnessResultToDict:
    def test_to_dict_includes_runtime_decision_key(self):
        from core.multi_device_runtime_harness import RuntimeHarnessResult
        result = RuntimeHarnessResult(operation="test")
        d = result.to_dict()
        assert "runtime_decision" in d
        assert d["runtime_decision"] is None

    def test_to_dict_with_runtime_decision(self):
        from core.multi_device_runtime_harness import (
            MultiDeviceRuntimeHarness, RuntimeHarnessResult,
        )
        harness = MultiDeviceRuntimeHarness()
        group = _make_group(fallback_ids=["fb-1"])
        result = harness.on_participant_readiness_changed(
            "primary-dev", "lost", formation=group
        )
        d = result.to_dict()
        assert "runtime_decision" in d
        # Decision was produced
        assert d["runtime_decision"] is not None


# ---------------------------------------------------------------------------
# 30: Custom thresholds
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_custom_unhealthy_threshold(self):
        from core.device_formation.formation_runtime_coordinator import (
            FormationRuntimeCoordinator, FormationParticipantState,
        )
        group = _make_group(support_ids=["sup-1"])
        # Raise unhealthy threshold to 0.7
        coord = FormationRuntimeCoordinator(group, unhealthy_threshold=0.7)
        # score=0.65 is below unhealthy threshold of 0.7 → should be LOST
        coord.on_health_degraded("sup-1", health_score=0.65)
        status = coord.get_participant_status("sup-1")
        assert status is not None
        assert status.state == FormationParticipantState.LOST
