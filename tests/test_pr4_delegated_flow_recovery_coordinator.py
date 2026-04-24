#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr4_delegated_flow_recovery_coordinator.py
======================================================
PR-4 — DelegatedFlowRecoveryCoordinator — test suite.

Coverage
--------
A  — Module importable; authority sentinel and PR-4 sentinel present.
B  — All 9 policy sentinels are non-empty strings with expected keywords.
C  — RecoveryAction enum has all 7 required values.
D  — RecoveryTrigger enum has all 8 required values.
E  — RecoveryTriggerContext dataclass has required fields; to_dict() works.
F  — RecoveryDecisionArtifact has required fields; to_dict() and to_json() work.
G  — RecoveryDecisionArtifact.from_dict() round-trips correctly.
H  — RecoveryAttemptRecord has required fields; to_dict() and to_json() work.
I  — RecoveryAttemptRecord.from_dict() round-trips correctly.
J  — RecoveryCoordinatorSnapshot has required fields; to_dict() works.
K  — DelegatedFlowRecoveryCoordinator instantiates with default capacity.
L  — get_delegated_flow_recovery_coordinator() returns singleton; reset clears it.
M  — decide: missing flow_id → fail_closed.
N  — decide: has_partial_result=True → preserve_partial_then_resume.
O  — decide: checkpoint_available=True → replay_from_checkpoint.
P  — decide: binding_state=released, trigger=android_binding_lost → redispatch_runtime.
Q  — decide: continuity_decision=continuity_resume, active flow → resume_in_place.
R  — decide: duplicate in-progress attempt → suppress_duplicate_recovery.
S  — decide: no context after flow_id → require_review or resume_in_place (fail-safe).
T  — decide: partial result overrides checkpoint (partial takes priority).
U  — decide_from_continuity_artifact: enriches ctx from artifact dict.
V  — begin_attempt: returns (RecoveryAttemptRecord, RecoveryDecisionArtifact).
W  — begin_attempt: duplicate flow_id → suppressed attempt record.
X  — complete_attempt: state transitions to completed; deregisters active attempt.
Y  — complete_attempt: success=False → failed state.
Z  — suppress_attempt: state transitions to suppressed.
AA — build_snapshot: empty coordinator → snapshot with zero decisions.
AB — build_snapshot: after decisions → counts, recent_artifacts correct.
AC — list_recent: returns newest-first up to n items.
AD — get_by_artifact_id: returns artifact by id; None for unknown id.
AE — list_recent_attempts: returns newest-first attempt records.
AF — decide_recovery convenience wrapper: returns RecoveryDecisionArtifact.
AG — decide_recovery_from_continuity_artifact convenience wrapper.
AH — begin_recovery_attempt convenience wrapper.
AI — complete_recovery_attempt convenience wrapper.
AJ — suppress_recovery_attempt convenience wrapper.
AK — RecoveryAction.from_string: known value, unknown value, non-string.
AL — RecoveryTrigger.from_string: known value, unknown value.
AM — RecoveryAction.is_executable: True for executable actions, False otherwise.
AN — Ring-buffer capacity respected: oldest artifact evicted when full.
AO — artifact.to_dict() → from_dict() round-trip preserves all fields.
AP — Coordinator records each decision in ring-buffer.
AQ — active_attempt_count in snapshot reflects in-progress attempts.
AR — RecoveryAttemptState enum has all 4 required values.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_coordinator():
    from core.delegated_flow_recovery_coordinator import (
        DelegatedFlowRecoveryCoordinator,
    )
    return DelegatedFlowRecoveryCoordinator(capacity=16)


def _ctx(**kwargs):
    from core.delegated_flow_recovery_coordinator import RecoveryTriggerContext
    return RecoveryTriggerContext(**kwargs)


# ---------------------------------------------------------------------------
# A — Module importable; sentinels present
# ---------------------------------------------------------------------------


class TestModuleSentinels:
    def test_module_is_importable(self):
        import core.delegated_flow_recovery_coordinator  # noqa: F401

    def test_authority_sentinel_is_non_empty_string(self):
        from core.delegated_flow_recovery_coordinator import (
            DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY,
        )
        assert isinstance(DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY, str)
        assert len(DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY) > 0
        assert "DelegatedFlowRecoveryCoordinator" in DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY

    def test_pr4_sentinel_is_non_empty_string(self):
        from core.delegated_flow_recovery_coordinator import (
            DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL,
        )
        assert isinstance(DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL, str)
        assert "package=4" in DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL


# ---------------------------------------------------------------------------
# B — All 9 policy sentinels are non-empty strings
# ---------------------------------------------------------------------------


class TestPolicySentinels:
    def test_all_9_sentinels_are_strings(self):
        from core.delegated_flow_recovery_coordinator import (
            DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY,
            DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL,
            RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY,
            IDEMPOTENT_RECOVERY_GUARD_IS_PER_FLOW_POLICY,
            PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY,
            DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY,
            REDISPATCH_REQUIRES_BINDING_INVALIDATION_POLICY,
            RECOVERY_ARTIFACTS_MUST_BE_AUDITABLE_POLICY,
            FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_POLICY,
        )
        sentinels = [
            DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY,
            DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL,
            RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY,
            IDEMPOTENT_RECOVERY_GUARD_IS_PER_FLOW_POLICY,
            PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY,
            DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY,
            REDISPATCH_REQUIRES_BINDING_INVALIDATION_POLICY,
            RECOVERY_ARTIFACTS_MUST_BE_AUDITABLE_POLICY,
            FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_POLICY,
        ]
        assert len(sentinels) == 9
        for s in sentinels:
            assert isinstance(s, str)
            assert len(s) > 0


# ---------------------------------------------------------------------------
# C — RecoveryAction enum has all 7 required values
# ---------------------------------------------------------------------------


class TestRecoveryActionEnum:
    def test_all_7_values_present(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        expected = {
            "resume_in_place",
            "replay_from_checkpoint",
            "redispatch_runtime",
            "preserve_partial_then_resume",
            "suppress_duplicate_recovery",
            "fail_closed",
            "require_review",
        }
        actual = {v.value for v in RecoveryAction}
        assert expected == actual


# ---------------------------------------------------------------------------
# D — RecoveryTrigger enum has all 8 required values
# ---------------------------------------------------------------------------


class TestRecoveryTriggerEnum:
    def test_all_8_values_present(self):
        from core.delegated_flow_recovery_coordinator import RecoveryTrigger
        expected = {
            "v2_restart",
            "android_binding_lost",
            "continuity_decision",
            "explicit_operator_request",
            "session_reconnect",
            "process_recreation",
            "checkpoint_available",
            "unknown",
        }
        actual = {v.value for v in RecoveryTrigger}
        assert expected == actual


# ---------------------------------------------------------------------------
# E — RecoveryTriggerContext
# ---------------------------------------------------------------------------


class TestRecoveryTriggerContext:
    def test_default_construction(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryTriggerContext,
            RecoveryTrigger,
        )
        ctx = RecoveryTriggerContext()
        assert ctx.trigger == RecoveryTrigger.unknown
        assert ctx.flow_id == ""
        assert ctx.has_partial_result is False

    def test_to_dict_has_required_keys(self):
        from core.delegated_flow_recovery_coordinator import RecoveryTriggerContext
        ctx = RecoveryTriggerContext(flow_id="flow-1", session_id="sess-1")
        d = ctx.to_dict()
        for key in (
            "trigger", "flow_id", "flow_lineage_id", "session_id",
            "contract_id", "tracker_id", "device_id", "binding_id",
            "continuity_artifact_id", "continuity_decision",
            "has_partial_result", "partial_result_payload",
            "checkpoint_available", "checkpoint_boundary_phase",
            "binding_state", "recovery_attempt_id", "metadata",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_json_is_valid_json(self):
        from core.delegated_flow_recovery_coordinator import RecoveryTriggerContext
        ctx = RecoveryTriggerContext(flow_id="flow-1")
        j = ctx.to_json()
        parsed = json.loads(j)
        assert parsed["flow_id"] == "flow-1"


# ---------------------------------------------------------------------------
# F — RecoveryDecisionArtifact
# ---------------------------------------------------------------------------


class TestRecoveryDecisionArtifact:
    def test_default_construction(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryDecisionArtifact,
            RecoveryAction,
        )
        art = RecoveryDecisionArtifact()
        assert art.action == RecoveryAction.fail_closed
        assert isinstance(art.artifact_id, str)
        assert len(art.artifact_id) > 0

    def test_to_dict_has_required_keys(self):
        from core.delegated_flow_recovery_coordinator import RecoveryDecisionArtifact
        art = RecoveryDecisionArtifact(flow_id="flow-1")
        d = art.to_dict()
        for key in (
            "artifact_id", "recovery_attempt_id", "trigger", "action",
            "policy_reference", "detail", "flow_id", "flow_lineage_id",
            "session_id", "contract_id", "tracker_id", "device_id",
            "binding_id", "continuity_artifact_id", "continuity_decision",
            "flow_entity_phase", "binding_state_at_decision",
            "tracker_phase_at_decision", "checkpoint_boundary_phase",
            "has_partial_result", "is_executable", "extension_payload",
            "timestamp",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_json_is_valid_json(self):
        from core.delegated_flow_recovery_coordinator import RecoveryDecisionArtifact
        art = RecoveryDecisionArtifact(flow_id="flow-1")
        j = art.to_json()
        parsed = json.loads(j)
        assert parsed["flow_id"] == "flow-1"


# ---------------------------------------------------------------------------
# G — RecoveryDecisionArtifact.from_dict() round-trip
# ---------------------------------------------------------------------------


class TestRecoveryDecisionArtifactRoundTrip:
    def test_round_trip(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryDecisionArtifact,
            RecoveryAction,
            RecoveryTrigger,
        )
        orig = RecoveryDecisionArtifact(
            flow_id="flow-42",
            flow_lineage_id="lin-42",
            action=RecoveryAction.resume_in_place,
            trigger=RecoveryTrigger.v2_restart,
            policy_reference="MY_POLICY",
            detail="test detail",
            continuity_decision="continuity_resume",
            has_partial_result=False,
            is_executable=True,
            extension_payload={"operator_tag": "test"},
        )
        restored = RecoveryDecisionArtifact.from_dict(orig.to_dict())
        assert restored.artifact_id == orig.artifact_id
        assert restored.flow_id == orig.flow_id
        assert restored.action == orig.action
        assert restored.trigger == orig.trigger
        assert restored.policy_reference == orig.policy_reference
        assert restored.extension_payload == orig.extension_payload
        assert restored.is_executable == orig.is_executable


# ---------------------------------------------------------------------------
# H — RecoveryAttemptRecord
# ---------------------------------------------------------------------------


class TestRecoveryAttemptRecord:
    def test_default_construction(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryAttemptRecord,
            RecoveryAttemptState,
        )
        rec = RecoveryAttemptRecord()
        assert rec.state == RecoveryAttemptState.in_progress
        assert isinstance(rec.attempt_id, str)
        assert len(rec.attempt_id) > 0

    def test_to_dict_has_required_keys(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAttemptRecord
        rec = RecoveryAttemptRecord(flow_id="flow-1")
        d = rec.to_dict()
        for key in (
            "attempt_id", "flow_id", "flow_lineage_id", "trigger",
            "state", "action_decided", "artifact_id",
            "started_at", "completed_at", "metadata",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_json_is_valid_json(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAttemptRecord
        rec = RecoveryAttemptRecord(flow_id="flow-1")
        j = rec.to_json()
        parsed = json.loads(j)
        assert parsed["flow_id"] == "flow-1"


# ---------------------------------------------------------------------------
# I — RecoveryAttemptRecord.from_dict() round-trip
# ---------------------------------------------------------------------------


class TestRecoveryAttemptRecordRoundTrip:
    def test_round_trip(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryAttemptRecord,
            RecoveryAttemptState,
            RecoveryAction,
            RecoveryTrigger,
        )
        orig = RecoveryAttemptRecord(
            flow_id="flow-1",
            trigger=RecoveryTrigger.v2_restart,
            state=RecoveryAttemptState.completed,
            action_decided=RecoveryAction.resume_in_place,
            artifact_id="art-1",
        )
        restored = RecoveryAttemptRecord.from_dict(orig.to_dict())
        assert restored.attempt_id == orig.attempt_id
        assert restored.flow_id == orig.flow_id
        assert restored.trigger == orig.trigger
        assert restored.state == orig.state
        assert restored.action_decided == orig.action_decided


# ---------------------------------------------------------------------------
# J — RecoveryCoordinatorSnapshot
# ---------------------------------------------------------------------------


class TestRecoveryCoordinatorSnapshot:
    def test_to_dict_has_required_keys(self):
        from core.delegated_flow_recovery_coordinator import RecoveryCoordinatorSnapshot
        snap = RecoveryCoordinatorSnapshot()
        d = snap.to_dict()
        for key in (
            "snapshot_id", "total_decisions", "action_counts",
            "active_attempt_count", "recent_artifacts", "recent_attempts",
            "policy_sentinels", "timestamp",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_json_is_valid_json(self):
        from core.delegated_flow_recovery_coordinator import RecoveryCoordinatorSnapshot
        snap = RecoveryCoordinatorSnapshot()
        j = snap.to_json()
        parsed = json.loads(j)
        assert "snapshot_id" in parsed


# ---------------------------------------------------------------------------
# K — DelegatedFlowRecoveryCoordinator instantiation
# ---------------------------------------------------------------------------


class TestCoordinatorInstantiation:
    def test_instantiates_with_default_capacity(self):
        from core.delegated_flow_recovery_coordinator import (
            DelegatedFlowRecoveryCoordinator,
        )
        c = DelegatedFlowRecoveryCoordinator()
        assert c is not None

    def test_instantiates_with_custom_capacity(self):
        from core.delegated_flow_recovery_coordinator import (
            DelegatedFlowRecoveryCoordinator,
        )
        c = DelegatedFlowRecoveryCoordinator(capacity=8)
        assert c is not None


# ---------------------------------------------------------------------------
# L — Singleton management
# ---------------------------------------------------------------------------


class TestSingletonManagement:
    def test_get_returns_same_instance(self):
        from core.delegated_flow_recovery_coordinator import (
            get_delegated_flow_recovery_coordinator,
            reset_delegated_flow_recovery_coordinator,
        )
        reset_delegated_flow_recovery_coordinator()
        a = get_delegated_flow_recovery_coordinator()
        b = get_delegated_flow_recovery_coordinator()
        assert a is b

    def test_reset_clears_singleton(self):
        from core.delegated_flow_recovery_coordinator import (
            get_delegated_flow_recovery_coordinator,
            reset_delegated_flow_recovery_coordinator,
        )
        a = get_delegated_flow_recovery_coordinator()
        reset_delegated_flow_recovery_coordinator()
        b = get_delegated_flow_recovery_coordinator()
        assert a is not b


# ---------------------------------------------------------------------------
# M — decide: missing flow_id → fail_closed
# ---------------------------------------------------------------------------


class TestDecideMissingFlowId:
    def test_missing_flow_id_returns_fail_closed(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx()  # flow_id=""
        art = c.decide(ctx)
        assert art.action == RecoveryAction.fail_closed

    def test_fail_closed_has_policy_reference(self):
        c = _fresh_coordinator()
        art = c.decide(_ctx())
        assert art.policy_reference != ""


# ---------------------------------------------------------------------------
# N — decide: has_partial_result=True → preserve_partial_then_resume
# ---------------------------------------------------------------------------


class TestDecidePartialResult:
    def test_partial_result_flag_returns_preserve(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-1", has_partial_result=True)
        art = c.decide(ctx)
        assert art.action == RecoveryAction.preserve_partial_then_resume

    def test_preserve_has_partial_result_true(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-1", has_partial_result=True)
        art = c.decide(ctx)
        assert art.has_partial_result is True


# ---------------------------------------------------------------------------
# O — decide: checkpoint_available=True → replay_from_checkpoint
# ---------------------------------------------------------------------------


class TestDecideCheckpoint:
    def test_checkpoint_returns_replay(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(
            flow_id="flow-1",
            checkpoint_available=True,
            checkpoint_boundary_phase="dispatched",
        )
        art = c.decide(ctx)
        assert art.action == RecoveryAction.replay_from_checkpoint

    def test_checkpoint_boundary_phase_preserved_in_artifact(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(
            flow_id="flow-1",
            checkpoint_available=True,
            checkpoint_boundary_phase="executing",
        )
        art = c.decide(ctx)
        assert art.checkpoint_boundary_phase == "executing"


# ---------------------------------------------------------------------------
# P — decide: binding_state=released, trigger=android_binding_lost → redispatch
# ---------------------------------------------------------------------------


class TestDecideRedispatch:
    def test_released_binding_returns_redispatch(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryAction,
            RecoveryTrigger,
        )
        c = _fresh_coordinator()
        ctx = _ctx(
            flow_id="flow-1",
            trigger=RecoveryTrigger.android_binding_lost,
            binding_state="released",
        )
        art = c.decide(ctx)
        assert art.action == RecoveryAction.redispatch_runtime

    def test_invalidated_binding_returns_redispatch(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(
            flow_id="flow-1",
            binding_state="invalidated",
        )
        art = c.decide(ctx)
        assert art.action == RecoveryAction.redispatch_runtime

    def test_bound_binding_does_not_trigger_redispatch(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(
            flow_id="flow-1",
            binding_state="bound",
            continuity_decision="continuity_resume",
        )
        art = c.decide(ctx)
        assert art.action != RecoveryAction.redispatch_runtime


# ---------------------------------------------------------------------------
# Q — decide: continuity_resume → resume_in_place
# ---------------------------------------------------------------------------


class TestDecideResumeInPlace:
    def test_continuity_resume_returns_resume_in_place(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(
            flow_id="flow-1",
            continuity_decision="continuity_resume",
        )
        art = c.decide(ctx)
        assert art.action == RecoveryAction.resume_in_place

    def test_resume_in_place_is_executable(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(
            flow_id="flow-1",
            continuity_decision="continuity_resume",
        )
        art = c.decide(ctx)
        assert art.is_executable is True


# ---------------------------------------------------------------------------
# R — decide: duplicate in-progress attempt → suppress_duplicate_recovery
# ---------------------------------------------------------------------------


class TestDecideDuplicateSuppression:
    def test_duplicate_returns_suppress(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        flow_id = "flow-dup"
        # Register first attempt manually
        c._register_attempt(flow_id, "attempt-1")
        ctx = _ctx(flow_id=flow_id, continuity_decision="continuity_resume")
        art = c.decide(ctx)
        assert art.action == RecoveryAction.suppress_duplicate_recovery

    def test_suppress_includes_existing_attempt_in_detail(self):
        c = _fresh_coordinator()
        flow_id = "flow-dup2"
        c._register_attempt(flow_id, "attempt-xyz")
        ctx = _ctx(flow_id=flow_id)
        art = c.decide(ctx)
        assert "attempt-xyz" in art.detail

    def test_after_deregister_no_longer_suppressed(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        flow_id = "flow-dup3"
        c._register_attempt(flow_id, "attempt-aaa")
        c._deregister_attempt(flow_id)
        ctx = _ctx(flow_id=flow_id, continuity_decision="continuity_resume")
        art = c.decide(ctx)
        assert art.action != RecoveryAction.suppress_duplicate_recovery


# ---------------------------------------------------------------------------
# S — decide: no context after flow_id → require_review or resume_in_place
# ---------------------------------------------------------------------------


class TestDecideMinimalContext:
    def test_flow_id_only_no_crash(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-minimal")
        art = c.decide(ctx)
        # Should not crash; result is either resume_in_place or require_review
        assert art.action in (
            RecoveryAction.resume_in_place,
            RecoveryAction.require_review,
            RecoveryAction.fail_closed,
        )


# ---------------------------------------------------------------------------
# T — decide: partial result overrides checkpoint
# ---------------------------------------------------------------------------


class TestDecidePartialOverridesCheckpoint:
    def test_partial_result_takes_priority_over_checkpoint(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(
            flow_id="flow-1",
            has_partial_result=True,
            checkpoint_available=True,
        )
        art = c.decide(ctx)
        assert art.action == RecoveryAction.preserve_partial_then_resume


# ---------------------------------------------------------------------------
# U — decide_from_continuity_artifact: enriches ctx from artifact dict
# ---------------------------------------------------------------------------


class TestDecideFromContinuityArtifact:
    def test_enriches_flow_id_from_artifact(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryTriggerContext,
            RecoveryTrigger,
        )
        c = _fresh_coordinator()
        ctx = RecoveryTriggerContext(
            trigger=RecoveryTrigger.continuity_decision,
        )
        artifact_dict = {
            "artifact_id": "cda-1",
            "decision": "continuity_resume",
            "flow_id": "flow-from-cda",
            "flow_lineage_id": "lin-cda",
            "session_id": "sess-cda",
        }
        art = c.decide_from_continuity_artifact(ctx, artifact_dict)
        assert art.flow_id == "flow-from-cda"
        assert art.continuity_decision == "continuity_resume"
        assert art.continuity_artifact_id == "cda-1"

    def test_ctx_flow_id_overrides_artifact_flow_id(self):
        from core.delegated_flow_recovery_coordinator import RecoveryTriggerContext
        c = _fresh_coordinator()
        ctx = RecoveryTriggerContext(flow_id="ctx-flow")
        artifact_dict = {"artifact_id": "cda-2", "flow_id": "art-flow", "decision": "continuity_resume"}
        art = c.decide_from_continuity_artifact(ctx, artifact_dict)
        assert art.flow_id == "ctx-flow"


# ---------------------------------------------------------------------------
# V — begin_attempt: returns (RecoveryAttemptRecord, RecoveryDecisionArtifact)
# ---------------------------------------------------------------------------


class TestBeginAttempt:
    def test_begin_returns_attempt_and_artifact(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryAttemptRecord,
            RecoveryDecisionArtifact,
        )
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-v", continuity_decision="continuity_resume")
        attempt, artifact = c.begin_attempt(ctx)
        assert isinstance(attempt, RecoveryAttemptRecord)
        assert isinstance(artifact, RecoveryDecisionArtifact)

    def test_begin_registers_active_attempt(self):
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-v2", continuity_decision="continuity_resume")
        attempt, _ = c.begin_attempt(ctx)
        assert c._check_duplicate("flow-v2") == attempt.attempt_id

    def test_begin_attempt_id_links_to_artifact(self):
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-v3", continuity_decision="continuity_resume")
        attempt, artifact = c.begin_attempt(ctx)
        assert attempt.artifact_id == artifact.artifact_id


# ---------------------------------------------------------------------------
# W — begin_attempt: duplicate flow_id → suppressed attempt record
# ---------------------------------------------------------------------------


class TestBeginAttemptDuplicate:
    def test_duplicate_begin_returns_suppressed_attempt(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAttemptState
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-dup-begin", continuity_decision="continuity_resume")
        attempt1, _ = c.begin_attempt(ctx)
        attempt2, art2 = c.begin_attempt(ctx)
        assert attempt2.state == RecoveryAttemptState.suppressed

    def test_duplicate_action_is_suppress(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-dup-begin2")
        c.begin_attempt(ctx)
        _, art2 = c.begin_attempt(ctx)
        assert art2.action == RecoveryAction.suppress_duplicate_recovery


# ---------------------------------------------------------------------------
# X — complete_attempt: state transitions to completed
# ---------------------------------------------------------------------------


class TestCompleteAttempt:
    def test_complete_returns_completed_state(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAttemptState
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-x", continuity_decision="continuity_resume")
        attempt, _ = c.begin_attempt(ctx)
        updated = c.complete_attempt(attempt.attempt_id, "flow-x", success=True)
        assert updated is not None
        assert updated.state == RecoveryAttemptState.completed

    def test_complete_deregisters_flow(self):
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-x2", continuity_decision="continuity_resume")
        attempt, _ = c.begin_attempt(ctx)
        c.complete_attempt(attempt.attempt_id, "flow-x2")
        assert c._check_duplicate("flow-x2") is None

    def test_complete_sets_completed_at(self):
        import time
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-x3", continuity_decision="continuity_resume")
        attempt, _ = c.begin_attempt(ctx)
        before = time.time()
        updated = c.complete_attempt(attempt.attempt_id, "flow-x3")
        assert updated.completed_at >= before


# ---------------------------------------------------------------------------
# Y — complete_attempt: success=False → failed state
# ---------------------------------------------------------------------------


class TestCompleteAttemptFailed:
    def test_success_false_returns_failed(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAttemptState
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-y", continuity_decision="continuity_resume")
        attempt, _ = c.begin_attempt(ctx)
        updated = c.complete_attempt(attempt.attempt_id, "flow-y", success=False)
        assert updated.state == RecoveryAttemptState.failed


# ---------------------------------------------------------------------------
# Z — suppress_attempt: state transitions to suppressed
# ---------------------------------------------------------------------------


class TestSuppressAttempt:
    def test_suppress_returns_suppressed_state(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAttemptState
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-z", continuity_decision="continuity_resume")
        attempt, _ = c.begin_attempt(ctx)
        updated = c.suppress_attempt(attempt.attempt_id, "flow-z")
        assert updated is not None
        assert updated.state == RecoveryAttemptState.suppressed


# ---------------------------------------------------------------------------
# AA — build_snapshot: empty coordinator
# ---------------------------------------------------------------------------


class TestBuildSnapshotEmpty:
    def test_empty_snapshot_zero_decisions(self):
        c = _fresh_coordinator()
        snap = c.build_snapshot()
        assert snap.total_decisions == 0
        assert snap.active_attempt_count == 0
        assert snap.recent_artifacts == []

    def test_empty_snapshot_has_policy_sentinels(self):
        c = _fresh_coordinator()
        snap = c.build_snapshot()
        assert len(snap.policy_sentinels) == 9


# ---------------------------------------------------------------------------
# AB — build_snapshot: after decisions
# ---------------------------------------------------------------------------


class TestBuildSnapshotAfterDecisions:
    def test_snapshot_counts_actions(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        c = _fresh_coordinator()
        for i in range(3):
            c.decide(_ctx(flow_id=f"flow-{i}", continuity_decision="continuity_resume"))
        snap = c.build_snapshot()
        assert snap.total_decisions == 3
        assert snap.action_counts.get("resume_in_place", 0) == 3

    def test_snapshot_recent_artifacts_not_empty(self):
        c = _fresh_coordinator()
        c.decide(_ctx(flow_id="flow-ab", continuity_decision="continuity_resume"))
        snap = c.build_snapshot()
        assert len(snap.recent_artifacts) >= 1


# ---------------------------------------------------------------------------
# AC — list_recent: returns newest-first
# ---------------------------------------------------------------------------


class TestListRecent:
    def test_list_recent_newest_first(self):
        c = _fresh_coordinator()
        flow_ids = [f"flow-{i}" for i in range(5)]
        for fid in flow_ids:
            c.decide(_ctx(flow_id=fid, continuity_decision="continuity_resume"))
        recent = c.list_recent(3)
        assert len(recent) == 3
        # Most recent is the last one created
        assert recent[0].flow_id == "flow-4"


# ---------------------------------------------------------------------------
# AD — get_by_artifact_id
# ---------------------------------------------------------------------------


class TestGetByArtifactId:
    def test_returns_artifact_by_id(self):
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-ad", continuity_decision="continuity_resume")
        art = c.decide(ctx)
        found = c.get_by_artifact_id(art.artifact_id)
        assert found is art

    def test_returns_none_for_unknown_id(self):
        c = _fresh_coordinator()
        assert c.get_by_artifact_id("nonexistent-id") is None


# ---------------------------------------------------------------------------
# AE — list_recent_attempts
# ---------------------------------------------------------------------------


class TestListRecentAttempts:
    def test_list_recent_attempts_newest_first(self):
        c = _fresh_coordinator()
        for i in range(3):
            ctx = _ctx(
                flow_id=f"flow-ae-{i}",
                continuity_decision="continuity_resume",
            )
            c.begin_attempt(ctx)
        attempts = c.list_recent_attempts(2)
        assert len(attempts) == 2
        assert attempts[0].flow_id == "flow-ae-2"


# ---------------------------------------------------------------------------
# AF — decide_recovery convenience wrapper
# ---------------------------------------------------------------------------


class TestConvenienceDecideRecovery:
    def test_decide_recovery_returns_artifact(self):
        from core.delegated_flow_recovery_coordinator import (
            decide_recovery,
            RecoveryDecisionArtifact,
        )
        c = _fresh_coordinator()
        art = decide_recovery(
            "flow-af",
            continuity_decision="continuity_resume",
            coordinator=c,
        )
        assert isinstance(art, RecoveryDecisionArtifact)

    def test_decide_recovery_missing_flow_returns_fail_closed(self):
        from core.delegated_flow_recovery_coordinator import (
            decide_recovery,
            RecoveryAction,
        )
        c = _fresh_coordinator()
        art = decide_recovery("", coordinator=c)
        assert art.action == RecoveryAction.fail_closed


# ---------------------------------------------------------------------------
# AG — decide_recovery_from_continuity_artifact convenience wrapper
# ---------------------------------------------------------------------------


class TestConvenienceDecideFromContinuity:
    def test_returns_artifact(self):
        from core.delegated_flow_recovery_coordinator import (
            decide_recovery_from_continuity_artifact,
            RecoveryTriggerContext,
            RecoveryDecisionArtifact,
        )
        c = _fresh_coordinator()
        ctx = RecoveryTriggerContext()
        cad = {
            "artifact_id": "cda-ag",
            "decision": "continuity_resume",
            "flow_id": "flow-ag",
        }
        art = decide_recovery_from_continuity_artifact(ctx, cad, coordinator=c)
        assert isinstance(art, RecoveryDecisionArtifact)
        assert art.flow_id == "flow-ag"


# ---------------------------------------------------------------------------
# AH — begin_recovery_attempt convenience wrapper
# ---------------------------------------------------------------------------


class TestConvenienceBeginRecoveryAttempt:
    def test_returns_attempt_and_artifact(self):
        from core.delegated_flow_recovery_coordinator import (
            begin_recovery_attempt,
            RecoveryAttemptRecord,
            RecoveryDecisionArtifact,
        )
        c = _fresh_coordinator()
        attempt, artifact = begin_recovery_attempt(
            "flow-ah",
            continuity_decision="continuity_resume",
            coordinator=c,
        )
        assert isinstance(attempt, RecoveryAttemptRecord)
        assert isinstance(artifact, RecoveryDecisionArtifact)


# ---------------------------------------------------------------------------
# AI — complete_recovery_attempt convenience wrapper
# ---------------------------------------------------------------------------


class TestConvenienceCompleteRecoveryAttempt:
    def test_returns_completed_record(self):
        from core.delegated_flow_recovery_coordinator import (
            begin_recovery_attempt,
            complete_recovery_attempt,
            RecoveryAttemptState,
        )
        c = _fresh_coordinator()
        attempt, _ = begin_recovery_attempt(
            "flow-ai",
            continuity_decision="continuity_resume",
            coordinator=c,
        )
        updated = complete_recovery_attempt(
            attempt.attempt_id, "flow-ai", coordinator=c
        )
        assert updated.state == RecoveryAttemptState.completed


# ---------------------------------------------------------------------------
# AJ — suppress_recovery_attempt convenience wrapper
# ---------------------------------------------------------------------------


class TestConvenienceSuppressRecoveryAttempt:
    def test_returns_suppressed_record(self):
        from core.delegated_flow_recovery_coordinator import (
            begin_recovery_attempt,
            suppress_recovery_attempt,
            RecoveryAttemptState,
        )
        c = _fresh_coordinator()
        attempt, _ = begin_recovery_attempt(
            "flow-aj",
            continuity_decision="continuity_resume",
            coordinator=c,
        )
        updated = suppress_recovery_attempt(
            attempt.attempt_id, "flow-aj", coordinator=c
        )
        assert updated.state == RecoveryAttemptState.suppressed


# ---------------------------------------------------------------------------
# AK — RecoveryAction.from_string
# ---------------------------------------------------------------------------


class TestRecoveryActionFromString:
    def test_known_value(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        assert RecoveryAction.from_string("resume_in_place") == RecoveryAction.resume_in_place

    def test_unknown_value_defaults_to_fail_closed(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        assert RecoveryAction.from_string("nonexistent_value") == RecoveryAction.fail_closed

    def test_non_string_defaults_to_fail_closed(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        assert RecoveryAction.from_string(None) == RecoveryAction.fail_closed  # type: ignore

    def test_custom_default(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        result = RecoveryAction.from_string("bad_value", RecoveryAction.require_review)
        assert result == RecoveryAction.require_review


# ---------------------------------------------------------------------------
# AL — RecoveryTrigger.from_string
# ---------------------------------------------------------------------------


class TestRecoveryTriggerFromString:
    def test_known_value(self):
        from core.delegated_flow_recovery_coordinator import RecoveryTrigger
        assert RecoveryTrigger.from_string("v2_restart") == RecoveryTrigger.v2_restart

    def test_unknown_value_defaults_to_unknown(self):
        from core.delegated_flow_recovery_coordinator import RecoveryTrigger
        assert RecoveryTrigger.from_string("nonexistent") == RecoveryTrigger.unknown

    def test_non_string_defaults_to_unknown(self):
        from core.delegated_flow_recovery_coordinator import RecoveryTrigger
        assert RecoveryTrigger.from_string(123) == RecoveryTrigger.unknown  # type: ignore


# ---------------------------------------------------------------------------
# AM — RecoveryAction.is_executable
# ---------------------------------------------------------------------------


class TestRecoveryActionIsExecutable:
    def test_executable_actions(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        for action in (
            RecoveryAction.resume_in_place,
            RecoveryAction.replay_from_checkpoint,
            RecoveryAction.redispatch_runtime,
            RecoveryAction.preserve_partial_then_resume,
        ):
            assert action.is_executable is True, f"{action} should be executable"

    def test_non_executable_actions(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAction
        for action in (
            RecoveryAction.suppress_duplicate_recovery,
            RecoveryAction.fail_closed,
            RecoveryAction.require_review,
        ):
            assert action.is_executable is False, f"{action} should not be executable"


# ---------------------------------------------------------------------------
# AN — Ring-buffer capacity respected
# ---------------------------------------------------------------------------


class TestRingBufferCapacity:
    def test_oldest_artifact_evicted_when_full(self):
        from core.delegated_flow_recovery_coordinator import (
            DelegatedFlowRecoveryCoordinator,
        )
        c = DelegatedFlowRecoveryCoordinator(capacity=3)
        artifacts = []
        for i in range(4):
            ctx = _ctx(flow_id=f"flow-{i}", continuity_decision="continuity_resume")
            art = c.decide(ctx)
            artifacts.append(art)
        # Only 3 artifacts in buffer; oldest (flow-0) should be gone
        recent = c.list_recent(10)
        flow_ids = {a.flow_id for a in recent}
        assert "flow-0" not in flow_ids
        assert "flow-3" in flow_ids


# ---------------------------------------------------------------------------
# AO — artifact.to_dict() → from_dict() round-trip
# ---------------------------------------------------------------------------


class TestArtifactRoundTripFull:
    def test_full_round_trip_preserves_all_standard_fields(self):
        from core.delegated_flow_recovery_coordinator import (
            RecoveryDecisionArtifact,
            RecoveryAction,
            RecoveryTrigger,
        )
        orig = RecoveryDecisionArtifact(
            recovery_attempt_id="att-rt",
            trigger=RecoveryTrigger.android_binding_lost,
            action=RecoveryAction.redispatch_runtime,
            policy_reference="REDISPATCH_POLICY",
            detail="binding lost",
            flow_id="flow-rt",
            flow_lineage_id="lin-rt",
            session_id="sess-rt",
            contract_id="cont-rt",
            tracker_id="track-rt",
            device_id="dev-rt",
            binding_id="bind-rt",
            continuity_artifact_id="cda-rt",
            continuity_decision="new_attachment",
            flow_entity_phase="executing",
            binding_state_at_decision="released",
            tracker_phase_at_decision="in_progress",
            checkpoint_boundary_phase="dispatched",
            has_partial_result=True,
            is_executable=True,
            extension_payload={"truth_hint": "realign"},
        )
        restored = RecoveryDecisionArtifact.from_dict(orig.to_dict())
        assert restored.artifact_id == orig.artifact_id
        assert restored.recovery_attempt_id == orig.recovery_attempt_id
        assert restored.trigger == orig.trigger
        assert restored.action == orig.action
        assert restored.flow_id == orig.flow_id
        assert restored.binding_state_at_decision == orig.binding_state_at_decision
        assert restored.has_partial_result == orig.has_partial_result
        assert restored.extension_payload == orig.extension_payload


# ---------------------------------------------------------------------------
# AP — Coordinator records each decision in ring-buffer
# ---------------------------------------------------------------------------


class TestCoordinatorRecordsDecisions:
    def test_each_decide_call_adds_to_buffer(self):
        c = _fresh_coordinator()
        assert len(c.list_recent(100)) == 0
        c.decide(_ctx(flow_id="flow-1", continuity_decision="continuity_resume"))
        c.decide(_ctx(flow_id="flow-2", continuity_decision="continuity_resume"))
        assert len(c.list_recent(100)) == 2


# ---------------------------------------------------------------------------
# AQ — active_attempt_count in snapshot reflects in-progress attempts
# ---------------------------------------------------------------------------


class TestActiveAttemptCountInSnapshot:
    def test_count_increments_after_begin(self):
        c = _fresh_coordinator()
        snap_before = c.build_snapshot()
        ctx = _ctx(flow_id="flow-aq", continuity_decision="continuity_resume")
        c.begin_attempt(ctx)
        snap_after = c.build_snapshot()
        assert snap_after.active_attempt_count == snap_before.active_attempt_count + 1

    def test_count_decrements_after_complete(self):
        c = _fresh_coordinator()
        ctx = _ctx(flow_id="flow-aq2", continuity_decision="continuity_resume")
        attempt, _ = c.begin_attempt(ctx)
        c.complete_attempt(attempt.attempt_id, "flow-aq2")
        snap = c.build_snapshot()
        assert snap.active_attempt_count == 0


# ---------------------------------------------------------------------------
# AR — RecoveryAttemptState enum has all 4 required values
# ---------------------------------------------------------------------------


class TestRecoveryAttemptStateEnum:
    def test_all_4_values_present(self):
        from core.delegated_flow_recovery_coordinator import RecoveryAttemptState
        expected = {"in_progress", "completed", "suppressed", "failed"}
        actual = {v.value for v in RecoveryAttemptState}
        assert expected == actual
