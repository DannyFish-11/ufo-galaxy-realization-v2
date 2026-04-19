"""tests/test_pri_target_selection_policy.py
=============================================
Tests for PR-I: Policy-driven target selection and failure handling for
multi-device runtime execution.

Coverage:
  A.  TargetSelectionPolicyKind enum has all required values.
  B.  FailureHandlingPolicyKind enum has all required values.
  C.  DegradedReadinessPolicyKind enum has all required values.
  D.  TargetSelectionDecision round-trips through to_dict / from_dict.
  E.  FailureHandlingDecision round-trips through to_dict / from_dict.
  F.  build_target_selection_decision populates all fields correctly.
  G.  build_failure_handling_decision populates all fields correctly.
  H.  build_failure_handling_decision derives recommended_action from policy_kind.
  I.  apply_target_selection_policy: explicit_executor_type takes priority.
  J.  apply_target_selection_policy: mesh_topology selected when prefer_mesh_topology=True.
  K.  apply_target_selection_policy: readiness_weighted selection among candidates.
  L.  apply_target_selection_policy: fallback_local when no suitable remote candidate.
  M.  apply_failure_handling_policy: non-recoverable failure → reject_with_reason.
  N.  apply_failure_handling_policy: recoverable + retry budget → retry.
  O.  apply_failure_handling_policy: retry budget exhausted + allow_fallback_local → fallback_local.
  P.  apply_failure_handling_policy: retry budget exhausted + no fallback → reject_with_reason.
  Q.  apply_failure_handling_policy: recoverable unknown failure_kind treated as recoverable.
  R.  apply_degraded_readiness_policy: degraded + alternative_available → fallback_local.
  S.  apply_degraded_readiness_policy: degraded + no alternative + allow_degraded=True → accept.
  T.  apply_degraded_readiness_policy: degraded + no alternative + allow_degraded=False → reject.
  U.  apply_degraded_readiness_policy: fully-ready target returns not-degraded decision.
  V.  Sentinel constants are importable from contracts.execution_target_policy.
  W.  Sentinel constants are importable from core.runtime.execution_target_policy_engine.
  X.  apply_target_selection_policy never raises (graceful degradation).
  Y.  apply_failure_handling_policy never raises (graceful degradation).
  Z.  apply_degraded_readiness_policy never raises (graceful degradation).
  AA. TargetSelectionDecision.to_json() round-trips correctly.
  AB. FailureHandlingDecision.to_json() round-trips correctly.
  AC. build_target_selection_decision with no args produces a valid default_local decision.
  AD. build_failure_handling_decision with no args produces a valid reject decision.
  AE. apply_target_selection_policy: readiness_weighted prefers ready over degraded candidates.
  AF. apply_failure_handling_policy: wait_and_requeue for readiness_recovering with retry budget.
  AG. FailureHandlingDecision carries degraded_readiness_policy field.
  AH. Contracts exported from contracts.__init__ are importable.
  AI. Backward compatibility: existing execution paths (local, remote_handoff, fallback_local)
      remain functional and are not altered by the policy engine.
  AJ. apply_target_selection_policy: candidates_considered list is populated.
  AK. apply_failure_handling_policy: is_recoverable=False for capability_mismatch.
  AL. apply_failure_handling_policy: is_recoverable=True for device_disconnect.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import pytest

from contracts.execution_target_policy import (
    BACKWARD_COMPAT_DURING_POLICY_MIGRATION_POLICY,
    EXECUTION_TARGET_POLICY_IS_AUTHORITY,
    EXECUTION_TARGET_POLICY_PR_I_SENTINEL,
    FAILURE_HANDLING_IS_EXPLICIT_POLICY,
    POLICY_SEPARATION_FROM_ROUTING_MECHANICS_POLICY,
    TARGET_SELECTION_IS_POLICY_DRIVEN_POLICY,
    DegradedReadinessPolicyKind,
    FailureHandlingDecision,
    FailureHandlingPolicyKind,
    TargetSelectionDecision,
    TargetSelectionPolicyKind,
    build_failure_handling_decision,
    build_target_selection_decision,
)
from core.runtime.execution_target_policy_engine import (
    DEGRADED_READINESS_POLICY_ENGINE_USES_THRESHOLD_POLICY,
    EXECUTION_TARGET_POLICY_ENGINE_IS_AUTHORITY,
    FAILURE_HANDLING_POLICY_ENGINE_CLASSIFIES_RECOVERABLE_POLICY,
    POLICY_ENGINE_PR_I_SENTINEL,
    TARGET_SELECTION_POLICY_ENGINE_APPLIES_EXPLICIT_TYPES_POLICY,
    apply_degraded_readiness_policy,
    apply_failure_handling_policy,
    apply_target_selection_policy,
)


# ---------------------------------------------------------------------------
# A. TargetSelectionPolicyKind enum
# ---------------------------------------------------------------------------


class TestTargetSelectionPolicyKindEnum:
    """TargetSelectionPolicyKind has all required values."""

    def test_explicit_executor_type(self):
        assert TargetSelectionPolicyKind.explicit_executor_type == "explicit_executor_type"

    def test_readiness_weighted(self):
        assert TargetSelectionPolicyKind.readiness_weighted == "readiness_weighted"

    def test_mesh_topology(self):
        assert TargetSelectionPolicyKind.mesh_topology == "mesh_topology"

    def test_capability_match(self):
        assert TargetSelectionPolicyKind.capability_match == "capability_match"

    def test_fallback_local(self):
        assert TargetSelectionPolicyKind.fallback_local == "fallback_local"

    def test_default_local(self):
        assert TargetSelectionPolicyKind.default_local == "default_local"

    def test_is_str_enum(self):
        assert isinstance(TargetSelectionPolicyKind.explicit_executor_type, str)

    def test_all_required_values_present(self):
        values = {e.value for e in TargetSelectionPolicyKind}
        assert "explicit_executor_type" in values
        assert "readiness_weighted" in values
        assert "mesh_topology" in values
        assert "capability_match" in values
        assert "fallback_local" in values
        assert "default_local" in values


# ---------------------------------------------------------------------------
# B. FailureHandlingPolicyKind enum
# ---------------------------------------------------------------------------


class TestFailureHandlingPolicyKindEnum:
    """FailureHandlingPolicyKind has all required values."""

    def test_retry(self):
        assert FailureHandlingPolicyKind.retry == "retry"

    def test_fallback_local(self):
        assert FailureHandlingPolicyKind.fallback_local == "fallback_local"

    def test_reject_with_reason(self):
        assert FailureHandlingPolicyKind.reject_with_reason == "reject_with_reason"

    def test_escalate_to_operator(self):
        assert FailureHandlingPolicyKind.escalate_to_operator == "escalate_to_operator"

    def test_wait_and_requeue(self):
        assert FailureHandlingPolicyKind.wait_and_requeue == "wait_and_requeue"

    def test_is_str_enum(self):
        assert isinstance(FailureHandlingPolicyKind.retry, str)

    def test_all_required_values_present(self):
        values = {e.value for e in FailureHandlingPolicyKind}
        assert "retry" in values
        assert "fallback_local" in values
        assert "reject_with_reason" in values
        assert "escalate_to_operator" in values
        assert "wait_and_requeue" in values


# ---------------------------------------------------------------------------
# C. DegradedReadinessPolicyKind enum
# ---------------------------------------------------------------------------


class TestDegradedReadinessPolicyKindEnum:
    """DegradedReadinessPolicyKind has all required values."""

    def test_accept_degraded(self):
        assert DegradedReadinessPolicyKind.accept_degraded == "accept_degraded"

    def test_fallback_local(self):
        assert DegradedReadinessPolicyKind.fallback_local == "fallback_local"

    def test_wait_for_recovery(self):
        assert DegradedReadinessPolicyKind.wait_for_recovery == "wait_for_recovery"

    def test_reject_degraded(self):
        assert DegradedReadinessPolicyKind.reject_degraded == "reject_degraded"

    def test_escalate(self):
        assert DegradedReadinessPolicyKind.escalate == "escalate"

    def test_is_str_enum(self):
        assert isinstance(DegradedReadinessPolicyKind.accept_degraded, str)

    def test_all_required_values_present(self):
        values = {e.value for e in DegradedReadinessPolicyKind}
        assert "accept_degraded" in values
        assert "fallback_local" in values
        assert "wait_for_recovery" in values
        assert "reject_degraded" in values
        assert "escalate" in values


# ---------------------------------------------------------------------------
# D. TargetSelectionDecision round-trip
# ---------------------------------------------------------------------------


class TestTargetSelectionDecisionRoundTrip:
    """TargetSelectionDecision serialises and deserialises correctly."""

    def _make_decision(self) -> TargetSelectionDecision:
        return TargetSelectionDecision(
            policy_kind=TargetSelectionPolicyKind.explicit_executor_type.value,
            selected_executor_type="android_device",
            selected_device_id="dev_001",
            selected_session_id="sess_001",
            decision_reason="explicit executor type declared",
            candidates_considered=["dev_001", "dev_002"],
            trace_id="trace_001",
            task_id="task_001",
            mesh_session_id="mesh_001",
            readiness="ready",
            metadata={"key": "value"},
        )

    def test_to_dict_has_required_fields(self):
        d = self._make_decision()
        result = d.to_dict()
        assert "decision_id" in result
        assert result["policy_kind"] == "explicit_executor_type"
        assert result["selected_executor_type"] == "android_device"
        assert result["selected_device_id"] == "dev_001"
        assert result["selected_session_id"] == "sess_001"
        assert result["decision_reason"] == "explicit executor type declared"
        assert result["candidates_considered"] == ["dev_001", "dev_002"]
        assert result["trace_id"] == "trace_001"
        assert result["task_id"] == "task_001"
        assert result["mesh_session_id"] == "mesh_001"
        assert result["readiness"] == "ready"
        assert result["metadata"] == {"key": "value"}

    def test_from_dict_restores_fields(self):
        d = self._make_decision()
        restored = TargetSelectionDecision.from_dict(d.to_dict())
        assert restored.decision_id == d.decision_id
        assert restored.policy_kind == "explicit_executor_type"
        assert restored.selected_executor_type == "android_device"
        assert restored.selected_device_id == "dev_001"
        assert restored.decision_reason == "explicit executor type declared"

    def test_from_dict_handles_unknown_policy_kind(self):
        data = {"policy_kind": "nonexistent_kind", "decision_reason": "test"}
        restored = TargetSelectionDecision.from_dict(data)
        assert restored.policy_kind == "default_local"

    def test_from_dict_handles_empty_dict(self):
        restored = TargetSelectionDecision.from_dict({})
        assert restored.policy_kind == "default_local"
        assert restored.selected_executor_type is None

    def test_to_dict_candidates_considered_is_list(self):
        d = self._make_decision()
        result = d.to_dict()
        assert isinstance(result["candidates_considered"], list)


# ---------------------------------------------------------------------------
# E. FailureHandlingDecision round-trip
# ---------------------------------------------------------------------------


class TestFailureHandlingDecisionRoundTrip:
    """FailureHandlingDecision serialises and deserialises correctly."""

    def _make_decision(self) -> FailureHandlingDecision:
        return FailureHandlingDecision(
            policy_kind=FailureHandlingPolicyKind.fallback_local.value,
            failure_kind="transport_error",
            is_recoverable=True,
            recommended_action="proceed_local",
            decision_reason="transport error; falling back to local",
            degraded_readiness_policy=DegradedReadinessPolicyKind.fallback_local.value,
            prior_executor_type="android_device",
            prior_device_id="dev_001",
            trace_id="trace_001",
            task_id="task_001",
            errors=["err_001"],
            metadata={"key": "value"},
        )

    def test_to_dict_has_required_fields(self):
        d = self._make_decision()
        result = d.to_dict()
        assert "decision_id" in result
        assert result["policy_kind"] == "fallback_local"
        assert result["failure_kind"] == "transport_error"
        assert result["is_recoverable"] is True
        assert result["recommended_action"] == "proceed_local"
        assert result["decision_reason"] == "transport error; falling back to local"
        assert result["degraded_readiness_policy"] == "fallback_local"
        assert result["prior_executor_type"] == "android_device"
        assert result["prior_device_id"] == "dev_001"
        assert result["trace_id"] == "trace_001"
        assert result["task_id"] == "task_001"
        assert result["errors"] == ["err_001"]
        assert result["metadata"] == {"key": "value"}

    def test_from_dict_restores_fields(self):
        d = self._make_decision()
        restored = FailureHandlingDecision.from_dict(d.to_dict())
        assert restored.decision_id == d.decision_id
        assert restored.policy_kind == "fallback_local"
        assert restored.failure_kind == "transport_error"
        assert restored.is_recoverable is True
        assert restored.degraded_readiness_policy == "fallback_local"

    def test_from_dict_handles_unknown_policy_kind(self):
        data = {"policy_kind": "nonexistent_kind", "failure_kind": "some_err"}
        restored = FailureHandlingDecision.from_dict(data)
        assert restored.policy_kind == "reject_with_reason"

    def test_from_dict_handles_empty_dict(self):
        restored = FailureHandlingDecision.from_dict({})
        assert restored.policy_kind == "reject_with_reason"
        assert restored.failure_kind == "unknown"

    def test_from_dict_strips_unknown_degraded_policy(self):
        data = {"degraded_readiness_policy": "nonexistent_value"}
        restored = FailureHandlingDecision.from_dict(data)
        assert restored.degraded_readiness_policy is None


# ---------------------------------------------------------------------------
# F. build_target_selection_decision
# ---------------------------------------------------------------------------


class TestBuildTargetSelectionDecision:
    """build_target_selection_decision populates all fields correctly."""

    def test_all_fields_populated(self):
        decision = build_target_selection_decision(
            policy_kind=TargetSelectionPolicyKind.explicit_executor_type,
            selected_executor_type="node_service",
            selected_device_id="node_01",
            selected_session_id="sess_abc",
            decision_reason="explicit node_service target",
            candidates_considered=["node_01"],
            trace_id="trace_abc",
            task_id="task_abc",
            mesh_session_id="mesh_abc",
            readiness="ready",
            metadata={"test": True},
        )
        assert decision.policy_kind == "explicit_executor_type"
        assert decision.selected_executor_type == "node_service"
        assert decision.selected_device_id == "node_01"
        assert decision.selected_session_id == "sess_abc"
        assert decision.decision_reason == "explicit node_service target"
        assert decision.candidates_considered == ["node_01"]
        assert decision.trace_id == "trace_abc"
        assert decision.task_id == "task_abc"
        assert decision.mesh_session_id == "mesh_abc"
        assert decision.readiness == "ready"
        assert decision.metadata == {"test": True}

    def test_defaults_produce_valid_decision(self):
        decision = build_target_selection_decision()
        assert decision.decision_id  # non-empty
        assert decision.policy_kind == "default_local"
        assert decision.selected_executor_type is None
        assert decision.candidates_considered == []

    def test_has_unique_decision_id(self):
        d1 = build_target_selection_decision()
        d2 = build_target_selection_decision()
        assert d1.decision_id != d2.decision_id

    def test_policy_kind_enum_accepted(self):
        decision = build_target_selection_decision(
            policy_kind=TargetSelectionPolicyKind.readiness_weighted,
        )
        assert decision.policy_kind == "readiness_weighted"


# ---------------------------------------------------------------------------
# G. build_failure_handling_decision
# ---------------------------------------------------------------------------


class TestBuildFailureHandlingDecision:
    """build_failure_handling_decision populates all fields correctly."""

    def test_all_fields_populated(self):
        decision = build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.retry,
            failure_kind="transport_error",
            is_recoverable=True,
            recommended_action="retry_after_delay",
            decision_reason="transient transport error",
            degraded_readiness_policy=DegradedReadinessPolicyKind.wait_for_recovery,
            prior_executor_type="android_device",
            prior_device_id="dev_123",
            trace_id="trace_xyz",
            task_id="task_xyz",
            errors=["conn_refused"],
            metadata={"attempt": 1},
        )
        assert decision.policy_kind == "retry"
        assert decision.failure_kind == "transport_error"
        assert decision.is_recoverable is True
        assert decision.recommended_action == "retry_after_delay"
        assert decision.decision_reason == "transient transport error"
        assert decision.degraded_readiness_policy == "wait_for_recovery"
        assert decision.prior_executor_type == "android_device"
        assert decision.prior_device_id == "dev_123"
        assert decision.trace_id == "trace_xyz"
        assert decision.task_id == "task_xyz"
        assert decision.errors == ["conn_refused"]
        assert decision.metadata == {"attempt": 1}

    def test_defaults_produce_valid_decision(self):
        decision = build_failure_handling_decision()
        assert decision.decision_id  # non-empty
        assert decision.policy_kind == "reject_with_reason"
        assert decision.failure_kind == "unknown"
        assert decision.is_recoverable is False

    def test_has_unique_decision_id(self):
        d1 = build_failure_handling_decision()
        d2 = build_failure_handling_decision()
        assert d1.decision_id != d2.decision_id


# ---------------------------------------------------------------------------
# H. build_failure_handling_decision derives recommended_action
# ---------------------------------------------------------------------------


class TestBuildFailureHandlingDecisionDerivedAction:
    """build_failure_handling_decision derives recommended_action from policy_kind."""

    def test_retry_derives_retry_after_delay(self):
        d = build_failure_handling_decision(policy_kind=FailureHandlingPolicyKind.retry)
        assert d.recommended_action == "retry_after_delay"

    def test_fallback_local_derives_proceed_local(self):
        d = build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.fallback_local
        )
        assert d.recommended_action == "proceed_local"

    def test_reject_derives_reject_task(self):
        d = build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.reject_with_reason
        )
        assert d.recommended_action == "reject_task"

    def test_escalate_derives_escalate(self):
        d = build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.escalate_to_operator
        )
        assert d.recommended_action == "escalate"

    def test_wait_and_requeue_derives_wait_and_requeue(self):
        d = build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.wait_and_requeue
        )
        assert d.recommended_action == "wait_and_requeue"

    def test_explicit_recommended_action_overrides_derived(self):
        d = build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.retry,
            recommended_action="custom_action",
        )
        assert d.recommended_action == "custom_action"


# ---------------------------------------------------------------------------
# I. apply_target_selection_policy: explicit_executor_type priority
# ---------------------------------------------------------------------------


class TestApplyTargetSelectionPolicyExplicitType:
    """apply_target_selection_policy: explicit_executor_type takes priority."""

    def test_android_device_explicit(self):
        decision = apply_target_selection_policy(
            executor_target_type="android_device",
            candidate_device_ids=["dev_001"],
            readiness_map={"dev_001": "ready"},
            task_id="task_001",
            trace_id="trace_001",
        )
        assert decision.policy_kind == "explicit_executor_type"
        assert decision.selected_executor_type == "android_device"
        assert "explicit" in decision.decision_reason.lower()

    def test_node_service_explicit(self):
        decision = apply_target_selection_policy(
            executor_target_type="node_service",
        )
        assert decision.policy_kind == "explicit_executor_type"
        assert decision.selected_executor_type == "node_service"

    def test_go_worker_explicit(self):
        decision = apply_target_selection_policy(
            executor_target_type="go_worker",
        )
        assert decision.policy_kind == "explicit_executor_type"
        assert decision.selected_executor_type == "go_worker"

    def test_local_explicit(self):
        decision = apply_target_selection_policy(
            executor_target_type="local",
        )
        assert decision.policy_kind == "explicit_executor_type"
        assert decision.selected_executor_type == "local"

    def test_explicit_overrides_mesh_topology(self):
        mesh_session = {
            "session_id": "mesh_001",
            "participants": [
                {"device_id": "mesh_dev_01", "status": "active"}
            ],
        }
        decision = apply_target_selection_policy(
            executor_target_type="node_service",
            mesh_session=mesh_session,
            prefer_mesh_topology=True,
        )
        # Explicit type still wins
        assert decision.policy_kind == "explicit_executor_type"
        assert decision.selected_executor_type == "node_service"


# ---------------------------------------------------------------------------
# J. apply_target_selection_policy: mesh_topology
# ---------------------------------------------------------------------------


class TestApplyTargetSelectionPolicyMeshTopology:
    """apply_target_selection_policy: mesh_topology selected when prefer_mesh_topology=True."""

    def test_mesh_topology_with_active_participant(self):
        mesh_session = {
            "session_id": "mesh_001",
            "participants": [
                {"device_id": "mesh_dev_01", "status": "active", "role": "participant"},
                {"device_id": "mesh_dev_02", "status": "inactive"},
            ],
        }
        decision = apply_target_selection_policy(
            executor_target_type=None,
            mesh_session=mesh_session,
            prefer_mesh_topology=True,
            mesh_session_id="mesh_001",
            trace_id="trace_001",
        )
        assert decision.policy_kind == "mesh_topology"
        assert decision.selected_executor_type == "android_device"
        assert decision.selected_device_id == "mesh_dev_01"

    def test_mesh_topology_ignored_without_prefer_flag(self):
        mesh_session = {
            "session_id": "mesh_001",
            "participants": [
                {"device_id": "mesh_dev_01", "status": "active"},
            ],
        }
        # Without prefer_mesh_topology=True, should fall through to other policies
        decision = apply_target_selection_policy(
            executor_target_type=None,
            mesh_session=mesh_session,
            prefer_mesh_topology=False,
        )
        # Should not be mesh_topology
        assert decision.policy_kind != "mesh_topology"

    def test_mesh_topology_skipped_without_active_participants(self):
        mesh_session = {
            "session_id": "mesh_001",
            "participants": [
                {"device_id": "mesh_dev_01", "status": "inactive"},
            ],
        }
        decision = apply_target_selection_policy(
            executor_target_type=None,
            mesh_session=mesh_session,
            prefer_mesh_topology=True,
        )
        # No active participants → should not apply mesh_topology
        assert decision.policy_kind != "mesh_topology"

    def test_mesh_topology_candidates_considered_populated(self):
        mesh_session = {
            "session_id": "mesh_001",
            "participants": [
                {"device_id": "mesh_dev_01", "status": "active"},
                {"device_id": "mesh_dev_02", "status": "active"},
            ],
        }
        decision = apply_target_selection_policy(
            executor_target_type=None,
            mesh_session=mesh_session,
            prefer_mesh_topology=True,
        )
        assert decision.policy_kind == "mesh_topology"
        assert len(decision.candidates_considered) == 2


# ---------------------------------------------------------------------------
# K. apply_target_selection_policy: readiness_weighted
# ---------------------------------------------------------------------------


class TestApplyTargetSelectionPolicyReadinessWeighted:
    """apply_target_selection_policy: readiness_weighted selection among candidates."""

    def test_ready_candidate_selected(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=["dev_001"],
            readiness_map={"dev_001": "ready"},
        )
        assert decision.policy_kind == "readiness_weighted"
        assert decision.selected_device_id == "dev_001"
        assert decision.readiness == "ready"

    def test_ready_preferred_over_degraded(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=["dev_degraded", "dev_ready"],
            readiness_map={"dev_degraded": "degraded", "dev_ready": "ready"},
        )
        assert decision.policy_kind == "readiness_weighted"
        assert decision.selected_device_id == "dev_ready"

    def test_degraded_selected_when_no_ready_alternative(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=["dev_001"],
            readiness_map={"dev_001": "degraded"},
        )
        assert decision.policy_kind == "readiness_weighted"
        assert decision.selected_device_id == "dev_001"
        assert decision.readiness == "degraded"


# ---------------------------------------------------------------------------
# L. apply_target_selection_policy: fallback_local
# ---------------------------------------------------------------------------


class TestApplyTargetSelectionPolicyFallbackLocal:
    """apply_target_selection_policy: fallback_local when no suitable remote candidate."""

    def test_no_candidates_yields_fallback_local(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=[],
            readiness_map={},
        )
        assert decision.policy_kind == "fallback_local"
        assert decision.selected_executor_type == "local"

    def test_no_ready_or_degraded_candidate_yields_fallback_local(self):
        # Candidates present but none with useful readiness
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=["dev_001"],
            readiness_map={"dev_001": "unknown"},
        )
        assert decision.policy_kind == "fallback_local"
        assert decision.selected_executor_type == "local"

    def test_fallback_local_has_decision_reason(self):
        decision = apply_target_selection_policy(executor_target_type=None)
        assert decision.policy_kind == "fallback_local"
        assert len(decision.decision_reason) > 0


# ---------------------------------------------------------------------------
# M. apply_failure_handling_policy: non-recoverable
# ---------------------------------------------------------------------------


class TestApplyFailureHandlingPolicyNonRecoverable:
    """apply_failure_handling_policy: non-recoverable failure → reject_with_reason."""

    def test_capability_mismatch_rejected(self):
        decision = apply_failure_handling_policy(
            failure_kind="capability_mismatch",
            task_id="task_001",
            trace_id="trace_001",
        )
        assert decision.policy_kind == "reject_with_reason"
        assert decision.is_recoverable is False

    def test_policy_rejection_rejected(self):
        decision = apply_failure_handling_policy(failure_kind="policy_rejection")
        assert decision.policy_kind == "reject_with_reason"
        assert decision.is_recoverable is False

    def test_terminal_loss_rejected(self):
        decision = apply_failure_handling_policy(failure_kind="terminal_loss")
        assert decision.policy_kind == "reject_with_reason"
        assert decision.is_recoverable is False

    def test_config_error_rejected(self):
        decision = apply_failure_handling_policy(failure_kind="config_error")
        assert decision.policy_kind == "reject_with_reason"
        assert decision.is_recoverable is False

    def test_non_recoverable_decision_has_reason(self):
        decision = apply_failure_handling_policy(failure_kind="capability_mismatch")
        assert len(decision.decision_reason) > 0
        assert "capability_mismatch" in decision.decision_reason


# ---------------------------------------------------------------------------
# N. apply_failure_handling_policy: recoverable + retry budget
# ---------------------------------------------------------------------------


class TestApplyFailureHandlingPolicyRetry:
    """apply_failure_handling_policy: recoverable + retry budget → retry."""

    def test_transport_error_retry(self):
        decision = apply_failure_handling_policy(
            failure_kind="transport_error",
            allow_retry=True,
            max_retry_count=3,
            current_retry_count=0,
        )
        assert decision.policy_kind == "retry"
        assert decision.is_recoverable is True

    def test_heartbeat_miss_retry(self):
        decision = apply_failure_handling_policy(
            failure_kind="heartbeat_miss",
            allow_retry=True,
            max_retry_count=2,
            current_retry_count=1,
        )
        assert decision.policy_kind == "retry"
        assert decision.is_recoverable is True

    def test_retry_carries_failure_kind(self):
        decision = apply_failure_handling_policy(
            failure_kind="transport_error",
            allow_retry=True,
        )
        assert decision.failure_kind == "transport_error"


# ---------------------------------------------------------------------------
# O. apply_failure_handling_policy: retry budget exhausted + allow_fallback
# ---------------------------------------------------------------------------


class TestApplyFailureHandlingPolicyFallbackAfterRetry:
    """apply_failure_handling_policy: retry budget exhausted + allow_fallback_local → fallback_local."""

    def test_fallback_after_retry_exhaustion(self):
        decision = apply_failure_handling_policy(
            failure_kind="transport_error",
            allow_retry=True,
            max_retry_count=3,
            current_retry_count=3,  # exhausted
            allow_fallback_local=True,
        )
        assert decision.policy_kind == "fallback_local"
        assert decision.is_recoverable is True

    def test_fallback_when_retry_disabled(self):
        decision = apply_failure_handling_policy(
            failure_kind="device_disconnect",
            allow_retry=False,
            allow_fallback_local=True,
        )
        assert decision.policy_kind == "fallback_local"
        assert decision.is_recoverable is True

    def test_fallback_decision_has_reason(self):
        decision = apply_failure_handling_policy(
            failure_kind="transport_error",
            allow_retry=True,
            max_retry_count=1,
            current_retry_count=1,
            allow_fallback_local=True,
        )
        assert "fallback" in decision.decision_reason.lower() or "local" in decision.decision_reason.lower()


# ---------------------------------------------------------------------------
# P. apply_failure_handling_policy: retry exhausted + no fallback
# ---------------------------------------------------------------------------


class TestApplyFailureHandlingPolicyRejectAfterRetryExhausted:
    """apply_failure_handling_policy: retry budget exhausted + no fallback → reject_with_reason."""

    def test_reject_when_no_fallback_allowed(self):
        decision = apply_failure_handling_policy(
            failure_kind="transport_error",
            allow_retry=False,
            allow_fallback_local=False,
        )
        assert decision.policy_kind == "reject_with_reason"

    def test_reject_when_retry_exhausted_and_no_fallback(self):
        decision = apply_failure_handling_policy(
            failure_kind="transport_error",
            allow_retry=True,
            max_retry_count=2,
            current_retry_count=2,
            allow_fallback_local=False,
        )
        assert decision.policy_kind == "reject_with_reason"


# ---------------------------------------------------------------------------
# Q. apply_failure_handling_policy: unknown failure_kind treated as recoverable
# ---------------------------------------------------------------------------


class TestApplyFailureHandlingPolicyUnknownFailureKind:
    """apply_failure_handling_policy: recoverable unknown failure_kind treated as recoverable."""

    def test_unknown_failure_kind_treated_as_recoverable(self):
        decision = apply_failure_handling_policy(
            failure_kind="some_completely_unknown_failure",
            allow_retry=True,
            max_retry_count=1,
            current_retry_count=0,
        )
        # Unknown failure_kind → treated as recoverable → retry
        assert decision.is_recoverable is True

    def test_unknown_failure_kind_with_no_retry_budget(self):
        decision = apply_failure_handling_policy(
            failure_kind="some_completely_unknown_failure",
            allow_retry=False,
            allow_fallback_local=True,
        )
        # No retry → fallback_local
        assert decision.policy_kind == "fallback_local"


# ---------------------------------------------------------------------------
# R. apply_degraded_readiness_policy: degraded + alternative → fallback_local
# ---------------------------------------------------------------------------


class TestApplyDegradedReadinessPolicyFallbackWithAlternative:
    """apply_degraded_readiness_policy: degraded + alternative_available → fallback_local."""

    def test_degraded_with_alternative_yields_fallback_local(self):
        decision = apply_degraded_readiness_policy(
            readiness="degraded",
            device_id="dev_001",
            executor_type="android_device",
            alternative_available=True,
            task_id="task_001",
            trace_id="trace_001",
        )
        assert decision.policy_kind == "fallback_local"
        assert decision.is_recoverable is True
        assert decision.degraded_readiness_policy == "fallback_local"

    def test_recovering_with_alternative_yields_fallback_local(self):
        decision = apply_degraded_readiness_policy(
            readiness="recovering",
            device_id="dev_001",
            alternative_available=True,
        )
        assert decision.policy_kind == "fallback_local"
        assert decision.degraded_readiness_policy == "fallback_local"

    def test_fallback_carries_device_id(self):
        decision = apply_degraded_readiness_policy(
            readiness="degraded",
            device_id="dev_xyz",
            alternative_available=True,
        )
        assert decision.prior_device_id == "dev_xyz"


# ---------------------------------------------------------------------------
# S. apply_degraded_readiness_policy: degraded + no alternative + allow_degraded=True
# ---------------------------------------------------------------------------


class TestApplyDegradedReadinessPolicyAcceptDegraded:
    """apply_degraded_readiness_policy: degraded + no alternative + allow_degraded=True → accept."""

    def test_degraded_no_alternative_allow_degraded(self):
        decision = apply_degraded_readiness_policy(
            readiness="degraded",
            device_id="dev_001",
            alternative_available=False,
            allow_degraded_execution=True,
        )
        assert decision.degraded_readiness_policy == "accept_degraded"
        assert decision.is_recoverable is True
        assert decision.recommended_action == "accept_degraded"

    def test_accept_degraded_carries_device_id(self):
        decision = apply_degraded_readiness_policy(
            readiness="degraded",
            device_id="dev_xyz",
            alternative_available=False,
            allow_degraded_execution=True,
        )
        assert decision.prior_device_id == "dev_xyz"


# ---------------------------------------------------------------------------
# T. apply_degraded_readiness_policy: degraded + no alternative + allow_degraded=False
# ---------------------------------------------------------------------------


class TestApplyDegradedReadinessPolicyRejectDegraded:
    """apply_degraded_readiness_policy: degraded + no alternative + allow_degraded=False → reject."""

    def test_degraded_no_alternative_no_allow_degraded(self):
        decision = apply_degraded_readiness_policy(
            readiness="degraded",
            device_id="dev_001",
            alternative_available=False,
            allow_degraded_execution=False,
        )
        assert decision.policy_kind == "reject_with_reason"
        assert decision.degraded_readiness_policy == "reject_degraded"
        assert decision.is_recoverable is True  # still recoverable in principle

    def test_reject_degraded_has_reason(self):
        decision = apply_degraded_readiness_policy(
            readiness="degraded",
            alternative_available=False,
            allow_degraded_execution=False,
        )
        assert len(decision.decision_reason) > 0


# ---------------------------------------------------------------------------
# U. apply_degraded_readiness_policy: fully-ready target
# ---------------------------------------------------------------------------


class TestApplyDegradedReadinessPolicyFullyReady:
    """apply_degraded_readiness_policy: fully-ready target returns not-degraded decision."""

    def test_ready_target_returns_not_degraded(self):
        decision = apply_degraded_readiness_policy(
            readiness="ready",
            device_id="dev_001",
        )
        assert decision.degraded_readiness_policy is None
        assert decision.failure_kind == "readiness_not_degraded"

    def test_routable_target_returns_not_degraded(self):
        decision = apply_degraded_readiness_policy(
            readiness="routable",
            device_id="dev_001",
        )
        assert decision.degraded_readiness_policy is None


# ---------------------------------------------------------------------------
# V. Sentinel constants from contracts.execution_target_policy
# ---------------------------------------------------------------------------


class TestContractSentinels:
    """Sentinel constants are importable from contracts.execution_target_policy."""

    def test_execution_target_policy_is_authority_importable(self):
        assert isinstance(EXECUTION_TARGET_POLICY_IS_AUTHORITY, str)
        assert len(EXECUTION_TARGET_POLICY_IS_AUTHORITY) > 0

    def test_target_selection_is_policy_driven_policy_importable(self):
        assert isinstance(TARGET_SELECTION_IS_POLICY_DRIVEN_POLICY, str)
        assert "PR-I" in TARGET_SELECTION_IS_POLICY_DRIVEN_POLICY

    def test_failure_handling_is_explicit_policy_importable(self):
        assert isinstance(FAILURE_HANDLING_IS_EXPLICIT_POLICY, str)
        assert "PR-I" in FAILURE_HANDLING_IS_EXPLICIT_POLICY

    def test_policy_separation_from_routing_importable(self):
        assert isinstance(POLICY_SEPARATION_FROM_ROUTING_MECHANICS_POLICY, str)
        assert "PR-I" in POLICY_SEPARATION_FROM_ROUTING_MECHANICS_POLICY

    def test_backward_compat_policy_importable(self):
        assert isinstance(BACKWARD_COMPAT_DURING_POLICY_MIGRATION_POLICY, str)
        assert "PR-I" in BACKWARD_COMPAT_DURING_POLICY_MIGRATION_POLICY

    def test_pr_i_sentinel_importable(self):
        assert isinstance(EXECUTION_TARGET_POLICY_PR_I_SENTINEL, str)
        assert "PR-I" in EXECUTION_TARGET_POLICY_PR_I_SENTINEL


# ---------------------------------------------------------------------------
# W. Sentinel constants from core.runtime.execution_target_policy_engine
# ---------------------------------------------------------------------------


class TestEngineSentinels:
    """Sentinel constants are importable from core.runtime.execution_target_policy_engine."""

    def test_engine_is_authority_importable(self):
        assert isinstance(EXECUTION_TARGET_POLICY_ENGINE_IS_AUTHORITY, str)
        assert "PR-I" in EXECUTION_TARGET_POLICY_ENGINE_IS_AUTHORITY

    def test_engine_pr_i_sentinel_importable(self):
        assert isinstance(POLICY_ENGINE_PR_I_SENTINEL, str)
        assert "PR-I" in POLICY_ENGINE_PR_I_SENTINEL

    def test_explicit_types_policy_importable(self):
        assert isinstance(TARGET_SELECTION_POLICY_ENGINE_APPLIES_EXPLICIT_TYPES_POLICY, str)

    def test_failure_classifies_recoverable_policy_importable(self):
        assert isinstance(FAILURE_HANDLING_POLICY_ENGINE_CLASSIFIES_RECOVERABLE_POLICY, str)

    def test_degraded_readiness_threshold_policy_importable(self):
        assert isinstance(DEGRADED_READINESS_POLICY_ENGINE_USES_THRESHOLD_POLICY, str)


# ---------------------------------------------------------------------------
# X. apply_target_selection_policy never raises
# ---------------------------------------------------------------------------


class TestApplyTargetSelectionPolicyGracefulDegradation:
    """apply_target_selection_policy never raises (graceful degradation)."""

    def test_all_none_inputs_returns_decision(self):
        decision = apply_target_selection_policy()
        assert isinstance(decision, TargetSelectionDecision)

    def test_invalid_mesh_session_returns_decision(self):
        decision = apply_target_selection_policy(
            mesh_session={"broken": True, "participants": "not_a_list"},
            prefer_mesh_topology=True,
        )
        assert isinstance(decision, TargetSelectionDecision)

    def test_returns_valid_decision_on_empty_inputs(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=None,
            mesh_session=None,
            readiness_map=None,
        )
        assert isinstance(decision, TargetSelectionDecision)
        assert decision.decision_id  # non-empty


# ---------------------------------------------------------------------------
# Y. apply_failure_handling_policy never raises
# ---------------------------------------------------------------------------


class TestApplyFailureHandlingPolicyGracefulDegradation:
    """apply_failure_handling_policy never raises (graceful degradation)."""

    def test_all_none_inputs_returns_decision(self):
        decision = apply_failure_handling_policy()
        assert isinstance(decision, FailureHandlingDecision)

    def test_empty_failure_kind_returns_decision(self):
        decision = apply_failure_handling_policy(failure_kind="")
        assert isinstance(decision, FailureHandlingDecision)

    def test_returns_valid_decision_on_minimal_input(self):
        decision = apply_failure_handling_policy(failure_kind="transport_error")
        assert decision.decision_id  # non-empty


# ---------------------------------------------------------------------------
# Z. apply_degraded_readiness_policy never raises
# ---------------------------------------------------------------------------


class TestApplyDegradedReadinessPolicyGracefulDegradation:
    """apply_degraded_readiness_policy never raises (graceful degradation)."""

    def test_all_none_inputs_returns_decision(self):
        decision = apply_degraded_readiness_policy()
        assert isinstance(decision, FailureHandlingDecision)

    def test_none_readiness_returns_decision(self):
        decision = apply_degraded_readiness_policy(readiness=None, device_id="dev_001")
        assert isinstance(decision, FailureHandlingDecision)

    def test_empty_readiness_returns_decision(self):
        decision = apply_degraded_readiness_policy(readiness="")
        assert isinstance(decision, FailureHandlingDecision)


# ---------------------------------------------------------------------------
# AA. TargetSelectionDecision.to_json() round-trip
# ---------------------------------------------------------------------------


class TestTargetSelectionDecisionToJson:
    """TargetSelectionDecision.to_json() round-trips correctly."""

    def test_to_json_is_valid_json(self):
        decision = build_target_selection_decision(
            policy_kind=TargetSelectionPolicyKind.readiness_weighted,
            selected_executor_type="android_device",
            decision_reason="selected by readiness",
        )
        j = decision.to_json()
        parsed = json.loads(j)
        assert parsed["policy_kind"] == "readiness_weighted"
        assert parsed["selected_executor_type"] == "android_device"

    def test_from_dict_after_json_round_trip(self):
        decision = build_target_selection_decision(
            policy_kind=TargetSelectionPolicyKind.mesh_topology,
            selected_device_id="dev_mesh_01",
            trace_id="tr_001",
        )
        j = decision.to_json()
        restored = TargetSelectionDecision.from_dict(json.loads(j))
        assert restored.decision_id == decision.decision_id
        assert restored.selected_device_id == "dev_mesh_01"
        assert restored.trace_id == "tr_001"


# ---------------------------------------------------------------------------
# AB. FailureHandlingDecision.to_json() round-trip
# ---------------------------------------------------------------------------


class TestFailureHandlingDecisionToJson:
    """FailureHandlingDecision.to_json() round-trips correctly."""

    def test_to_json_is_valid_json(self):
        decision = build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.retry,
            failure_kind="transport_error",
            is_recoverable=True,
        )
        j = decision.to_json()
        parsed = json.loads(j)
        assert parsed["policy_kind"] == "retry"
        assert parsed["failure_kind"] == "transport_error"
        assert parsed["is_recoverable"] is True

    def test_from_dict_after_json_round_trip(self):
        decision = build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.fallback_local,
            failure_kind="device_disconnect",
            prior_device_id="dev_abc",
        )
        j = decision.to_json()
        restored = FailureHandlingDecision.from_dict(json.loads(j))
        assert restored.decision_id == decision.decision_id
        assert restored.failure_kind == "device_disconnect"
        assert restored.prior_device_id == "dev_abc"


# ---------------------------------------------------------------------------
# AC. build_target_selection_decision with no args → valid default_local
# ---------------------------------------------------------------------------


class TestBuildTargetSelectionDecisionDefaults:
    """build_target_selection_decision with no args produces a valid default_local decision."""

    def test_default_local_policy(self):
        decision = build_target_selection_decision()
        assert decision.policy_kind == "default_local"

    def test_decision_id_is_hex_string(self):
        decision = build_target_selection_decision()
        # decision_id should be a hex string (UUID4.hex)
        assert len(decision.decision_id) == 32
        int(decision.decision_id, 16)  # should not raise

    def test_timestamp_is_positive(self):
        decision = build_target_selection_decision()
        assert decision.timestamp > 0


# ---------------------------------------------------------------------------
# AD. build_failure_handling_decision with no args → valid reject decision
# ---------------------------------------------------------------------------


class TestBuildFailureHandlingDecisionDefaults:
    """build_failure_handling_decision with no args produces a valid reject decision."""

    def test_default_reject_with_reason(self):
        decision = build_failure_handling_decision()
        assert decision.policy_kind == "reject_with_reason"

    def test_default_failure_kind_is_unknown(self):
        decision = build_failure_handling_decision()
        assert decision.failure_kind == "unknown"

    def test_default_is_not_recoverable(self):
        decision = build_failure_handling_decision()
        assert decision.is_recoverable is False


# ---------------------------------------------------------------------------
# AE. apply_target_selection_policy: readiness_weighted prefers ready over degraded
# ---------------------------------------------------------------------------


class TestReadinessWeightedPreference:
    """apply_target_selection_policy: readiness_weighted prefers ready over degraded candidates."""

    def test_ready_candidate_wins_over_degraded(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=["dev_degraded", "dev_ready", "dev_unknown"],
            readiness_map={
                "dev_degraded": "degraded",
                "dev_ready": "ready",
                "dev_unknown": "unknown",
            },
        )
        assert decision.policy_kind == "readiness_weighted"
        assert decision.selected_device_id == "dev_ready"

    def test_degraded_wins_over_unknown(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=["dev_unknown", "dev_degraded"],
            readiness_map={
                "dev_unknown": "unknown",
                "dev_degraded": "degraded",
            },
        )
        assert decision.policy_kind == "readiness_weighted"
        assert decision.selected_device_id == "dev_degraded"


# ---------------------------------------------------------------------------
# AF. apply_failure_handling_policy: wait_and_requeue for readiness_recovering
# ---------------------------------------------------------------------------


class TestWaitAndRequeueForRecovering:
    """apply_failure_handling_policy: wait_and_requeue for readiness_recovering with retry budget."""

    def test_readiness_recovering_with_budget_yields_wait_and_requeue(self):
        decision = apply_failure_handling_policy(
            failure_kind="readiness_recovering",
            allow_retry=True,
            max_retry_count=2,
            current_retry_count=0,
        )
        assert decision.policy_kind == "wait_and_requeue"
        assert decision.is_recoverable is True

    def test_temporary_unavailable_with_budget_yields_wait_and_requeue(self):
        decision = apply_failure_handling_policy(
            failure_kind="temporary_unavailable",
            allow_retry=True,
            max_retry_count=2,
            current_retry_count=0,
        )
        assert decision.policy_kind == "wait_and_requeue"


# ---------------------------------------------------------------------------
# AG. FailureHandlingDecision carries degraded_readiness_policy field
# ---------------------------------------------------------------------------


class TestFailureHandlingDecisionDegradedPolicyField:
    """FailureHandlingDecision carries degraded_readiness_policy field."""

    def test_degraded_readiness_policy_in_to_dict(self):
        decision = build_failure_handling_decision(
            degraded_readiness_policy=DegradedReadinessPolicyKind.accept_degraded,
        )
        d = decision.to_dict()
        assert d["degraded_readiness_policy"] == "accept_degraded"

    def test_degraded_readiness_policy_none_in_to_dict(self):
        decision = build_failure_handling_decision()
        d = decision.to_dict()
        assert d["degraded_readiness_policy"] is None

    def test_degraded_readiness_policy_restored_from_dict(self):
        decision = build_failure_handling_decision(
            degraded_readiness_policy=DegradedReadinessPolicyKind.reject_degraded,
        )
        restored = FailureHandlingDecision.from_dict(decision.to_dict())
        assert restored.degraded_readiness_policy == "reject_degraded"


# ---------------------------------------------------------------------------
# AH. Contracts exported from contracts.__init__ are importable
# ---------------------------------------------------------------------------


class TestContractsInitExports:
    """Contracts exported from contracts.__init__ are importable."""

    def test_target_selection_policy_kind_importable(self):
        from contracts import TargetSelectionPolicyKind as _TSP
        assert _TSP.explicit_executor_type == "explicit_executor_type"

    def test_failure_handling_policy_kind_importable(self):
        from contracts import FailureHandlingPolicyKind as _FHP
        assert _FHP.retry == "retry"

    def test_degraded_readiness_policy_kind_importable(self):
        from contracts import DegradedReadinessPolicyKind as _DRP
        assert _DRP.accept_degraded == "accept_degraded"

    def test_target_selection_decision_importable(self):
        from contracts import TargetSelectionDecision as _TSD
        d = _TSD()
        assert d.policy_kind == "default_local"

    def test_failure_handling_decision_importable(self):
        from contracts import FailureHandlingDecision as _FHD
        d = _FHD()
        assert d.policy_kind == "reject_with_reason"

    def test_build_target_selection_decision_importable(self):
        from contracts import build_target_selection_decision as _btsd
        result = _btsd()
        assert isinstance(result, TargetSelectionDecision)

    def test_build_failure_handling_decision_importable(self):
        from contracts import build_failure_handling_decision as _bfhd
        result = _bfhd()
        assert isinstance(result, FailureHandlingDecision)

    def test_pr_i_sentinel_importable(self):
        from contracts import EXECUTION_TARGET_POLICY_PR_I_SENTINEL as sentinel
        assert "PR-I" in sentinel


# ---------------------------------------------------------------------------
# AI. Backward compatibility: existing execution paths remain functional
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Backward compatibility: existing execution paths remain functional."""

    def test_local_dispatch_path_unaffected(self):
        """Local dispatch path still works without consulting policy engine."""
        from contracts.source_dispatch import (
            SourceDispatchMode,
            build_source_dispatch_decision,
        )
        decision = build_source_dispatch_decision(
            trace_id="trace_compat",
            mode=SourceDispatchMode.local,
            decision_reason="local_preferred",
        )
        assert decision.mode == SourceDispatchMode.local

    def test_remote_handoff_path_unaffected(self):
        """Remote handoff dispatch path still works without consulting policy engine."""
        from contracts.source_dispatch import (
            SourceDispatchMode,
            build_source_dispatch_decision,
        )
        decision = build_source_dispatch_decision(
            trace_id="trace_compat_remote",
            mode=SourceDispatchMode.remote_handoff,
            decision_reason="explicit_target_device",
        )
        assert decision.mode == SourceDispatchMode.remote_handoff

    def test_fallback_local_path_unaffected(self):
        """Fallback local dispatch path still works."""
        from contracts.source_dispatch import (
            SourceDispatchMode,
            build_source_dispatch_decision,
        )
        decision = build_source_dispatch_decision(
            trace_id="trace_compat_fallback",
            mode=SourceDispatchMode.fallback_local,
            decision_reason="remote_handoff_failed",
        )
        assert decision.mode == SourceDispatchMode.fallback_local

    def test_policy_engine_does_not_alter_routing_state(self):
        """Policy engine functions are pure; they do not alter any routing state."""
        # Call policy engine functions multiple times and verify no shared mutable state
        d1 = apply_target_selection_policy(executor_target_type="android_device")
        d2 = apply_target_selection_policy(executor_target_type="node_service")
        # Both decisions are independent
        assert d1.selected_executor_type == "android_device"
        assert d2.selected_executor_type == "node_service"
        assert d1.decision_id != d2.decision_id


# ---------------------------------------------------------------------------
# AJ. apply_target_selection_policy: candidates_considered list populated
# ---------------------------------------------------------------------------


class TestCandidatesConsideredPopulated:
    """apply_target_selection_policy: candidates_considered list is populated."""

    def test_candidates_considered_in_mesh_topology(self):
        mesh_session = {
            "session_id": "m_001",
            "participants": [
                {"device_id": "dev_a", "status": "active"},
                {"device_id": "dev_b", "status": "active"},
            ],
        }
        decision = apply_target_selection_policy(
            mesh_session=mesh_session,
            prefer_mesh_topology=True,
        )
        assert "dev_a" in decision.candidates_considered
        assert "dev_b" in decision.candidates_considered

    def test_candidates_considered_in_readiness_weighted(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=["dev_x", "dev_y"],
            readiness_map={"dev_x": "ready", "dev_y": "degraded"},
        )
        assert "dev_x" in decision.candidates_considered
        assert "dev_y" in decision.candidates_considered

    def test_candidates_considered_in_fallback_local(self):
        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=["dev_z"],
            readiness_map={},
        )
        assert decision.policy_kind == "fallback_local"
        assert "dev_z" in decision.candidates_considered


# ---------------------------------------------------------------------------
# AK. apply_failure_handling_policy: is_recoverable=False for capability_mismatch
# ---------------------------------------------------------------------------


class TestIsRecoverableForCapabilityMismatch:
    """apply_failure_handling_policy: is_recoverable=False for capability_mismatch."""

    def test_capability_mismatch_is_not_recoverable(self):
        decision = apply_failure_handling_policy(failure_kind="capability_mismatch")
        assert decision.is_recoverable is False

    def test_exec_mode_mismatch_is_not_recoverable(self):
        decision = apply_failure_handling_policy(failure_kind="exec_mode_mismatch")
        assert decision.is_recoverable is False

    def test_registration_failure_is_not_recoverable(self):
        decision = apply_failure_handling_policy(failure_kind="registration_failure")
        assert decision.is_recoverable is False


# ---------------------------------------------------------------------------
# AL. apply_failure_handling_policy: is_recoverable=True for device_disconnect
# ---------------------------------------------------------------------------


class TestIsRecoverableForDeviceDisconnect:
    """apply_failure_handling_policy: is_recoverable=True for device_disconnect."""

    def test_device_disconnect_is_recoverable(self):
        decision = apply_failure_handling_policy(
            failure_kind="device_disconnect",
            allow_retry=False,
            allow_fallback_local=True,
        )
        assert decision.is_recoverable is True

    def test_transport_error_is_recoverable(self):
        decision = apply_failure_handling_policy(
            failure_kind="transport_error",
            allow_retry=True,
        )
        assert decision.is_recoverable is True

    def test_session_detached_is_recoverable(self):
        decision = apply_failure_handling_policy(
            failure_kind="session_detached",
            allow_retry=True,
        )
        assert decision.is_recoverable is True
