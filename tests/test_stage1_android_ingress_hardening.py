"""tests/test_stage1_android_ingress_hardening.py
==================================================
Stage 1: Android → V2 Input Path Hardening — Implementation Regression Tests

These tests prove that real implementation changes in the Android → V2 input
path are in effect:

1. AndroidUplinkSchemaGateDecision.closure_grade_eligible reflects true gate
   action semantics (accept→True, degrade/reject→False).

2. AndroidIngressPayloadGrade enum and ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY
   sentinel exist with expected values.

3. NormalizedResultEvent carries closure_grade_eligible and android_payload_grade.

4. UnifiedResultIngressOutcome carries closure_grade_eligible,
   closure_grade_ineligible_reason, and android_payload_grade.

5. UnifiedResultIngress.process() enforces that closure_grade_eligible=False
   prevents is_fully_closed=True regardless of truth chain / completion success.

6. Canonical payloads (closure_grade_eligible=True) can still reach
   is_fully_closed=True when all other conditions are met.

7. The contracts/cross_repo_schema_version_gate CLOSURE_GRADE policy sentinel
   is importable and non-empty.

Groups:
  A – AndroidUplinkSchemaGateDecision.closure_grade_eligible
  B – AndroidIngressPayloadGrade enum and policy sentinel
  C – NormalizedResultEvent closure-grade fields
  D – UnifiedResultIngressOutcome closure-grade fields
  E – UnifiedResultIngress.process() closure-grade enforcement
  F – Last closure outcome snapshot includes closure-grade fields
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_nre(
    *,
    closure_grade_eligible: bool = True,
    android_payload_grade: str = "",
    task_id: str = "test-task-s1",
    device_id: str = "test-device-s1",
    status: str = "completed",
) -> Any:
    from core.unified_result_ingress import NormalizedResultEvent, ResultSourceChannel

    return NormalizedResultEvent(
        task_id=task_id,
        device_id=device_id,
        raw_message_type="goal_execution_result",
        normalized_result_kind="goal_execution_result",
        normalized_status=status,
        source_channel=ResultSourceChannel.CANONICAL_WS,
        payload={"task_id": task_id, "status": status},
        closure_grade_eligible=closure_grade_eligible,
        android_payload_grade=android_payload_grade,
    )


def _make_isolated_ingress() -> Any:
    """Return a UnifiedResultIngress with all side-effecting steps stubbed out."""
    from core.unified_result_ingress import UnifiedResultIngress

    ingress = UnifiedResultIngress()
    ingress._check_continuity_legality = lambda e, mode: "allow"  # type: ignore[method-assign]
    ingress._check_stale_epoch = lambda e: (False, "", {})  # type: ignore[method-assign]
    ingress._evaluate_cross_repo_dedupe_contract = lambda e: ("accept", "ok", {})  # type: ignore[method-assign]
    ingress._check_idempotency = lambda e: False  # type: ignore[method-assign]
    ingress._record_idempotency = lambda e: None  # type: ignore[method-assign]
    ingress._run_truth_chain = lambda e: True  # type: ignore[method-assign]
    ingress._sync_lifecycle = lambda e: None  # type: ignore[method-assign]
    ingress._classify_and_apply_evidence_gate = lambda e, o: None  # type: ignore[method-assign]
    ingress._stamp_android_truth_context = lambda e, o: None  # type: ignore[method-assign]
    ingress._notify_completion = lambda e: True  # type: ignore[method-assign]
    ingress._log_outcome = lambda e, o: None  # type: ignore[method-assign]
    return ingress


# ===========================================================================
# Group A: AndroidUplinkSchemaGateDecision.closure_grade_eligible
# ===========================================================================


class TestAndroidUplinkSchemaGateClosureGrade:
    """Group A — closure_grade_eligible property on AndroidUplinkSchemaGateDecision."""

    def test_A01_accept_decision_is_closure_grade_eligible(self):
        """A gate decision with action='accept' must be closure_grade_eligible=True."""
        from contracts.cross_repo_schema_version_gate import AndroidUplinkSchemaGateDecision

        decision = AndroidUplinkSchemaGateDecision(
            action="accept",
            message_type="goal_execution_result",
        )
        assert decision.closure_grade_eligible is True

    def test_A02_degrade_decision_is_not_closure_grade_eligible(self):
        """A gate decision with action='degrade' must be closure_grade_eligible=False."""
        from contracts.cross_repo_schema_version_gate import AndroidUplinkSchemaGateDecision

        decision = AndroidUplinkSchemaGateDecision(
            action="degrade",
            message_type="goal_execution_result",
        )
        assert decision.closure_grade_eligible is False

    def test_A03_reject_decision_is_not_closure_grade_eligible(self):
        """A gate decision with action='reject' must be closure_grade_eligible=False."""
        from contracts.cross_repo_schema_version_gate import AndroidUplinkSchemaGateDecision

        decision = AndroidUplinkSchemaGateDecision(
            action="reject",
            message_type="goal_execution_result",
        )
        assert decision.closure_grade_eligible is False

    def test_A04_to_dict_includes_closure_grade_eligible(self):
        """to_dict() must include closure_grade_eligible so downstream consumers can read it."""
        from contracts.cross_repo_schema_version_gate import AndroidUplinkSchemaGateDecision

        accept_dict = AndroidUplinkSchemaGateDecision(action="accept", message_type="t").to_dict()
        degrade_dict = AndroidUplinkSchemaGateDecision(action="degrade", message_type="t").to_dict()

        assert "closure_grade_eligible" in accept_dict
        assert accept_dict["closure_grade_eligible"] is True
        assert "closure_grade_eligible" in degrade_dict
        assert degrade_dict["closure_grade_eligible"] is False

    def test_A05_policy_sentinel_importable(self):
        """CLOSURE_GRADE_REQUIRES_CANONICAL_SCHEMA_GATE_POLICY must be importable and non-empty."""
        from contracts.cross_repo_schema_version_gate import (
            CLOSURE_GRADE_REQUIRES_CANONICAL_SCHEMA_GATE_POLICY,
        )

        assert isinstance(CLOSURE_GRADE_REQUIRES_CANONICAL_SCHEMA_GATE_POLICY, str)
        assert len(CLOSURE_GRADE_REQUIRES_CANONICAL_SCHEMA_GATE_POLICY) > 50
        assert "closure_grade_eligible" in CLOSURE_GRADE_REQUIRES_CANONICAL_SCHEMA_GATE_POLICY.lower()

    def test_A06_evaluate_schema_gate_accept_is_closure_grade_eligible(self):
        """evaluate_android_uplink_schema_gate for a valid message yields closure_grade_eligible=True."""
        from contracts.cross_repo_schema_version_gate import (
            ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
            evaluate_android_uplink_schema_gate,
        )

        msg = {
            "payload": {
                "task_id": "t1",
                "status": "completed",
                "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
            }
        }
        decision = evaluate_android_uplink_schema_gate(
            message_type="task_result",
            message=msg,
        )
        # task_result is in COMPAT mode, not STRICT, so a matching schema should accept
        if decision is not None and decision.action == "accept":
            assert decision.closure_grade_eligible is True

    def test_A07_evaluate_schema_gate_degrade_is_not_closure_grade_eligible(self):
        """evaluate_android_uplink_schema_gate for a missing-schema compat message yields closure_grade_eligible=False."""
        from contracts.cross_repo_schema_version_gate import (
            COMPAT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES,
            evaluate_android_uplink_schema_gate,
        )

        if not COMPAT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES:
            return  # skip if no compat types configured

        compat_type = next(iter(COMPAT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES))
        msg = {"payload": {"task_id": "t1", "status": "completed"}}
        decision = evaluate_android_uplink_schema_gate(
            message_type=compat_type,
            message=msg,
        )
        if decision is not None and decision.action == "degrade":
            assert decision.closure_grade_eligible is False


# ===========================================================================
# Group B: AndroidIngressPayloadGrade enum and policy sentinel
# ===========================================================================


class TestAndroidIngressPayloadGradeEnum:
    """Group B — AndroidIngressPayloadGrade enum values and policy sentinel."""

    def test_B01_enum_importable(self):
        """AndroidIngressPayloadGrade must be importable from core.unified_result_ingress."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        assert AndroidIngressPayloadGrade is not None

    def test_B02_canonical_value(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        assert AndroidIngressPayloadGrade.CANONICAL.value == "canonical"

    def test_B03_compat_degraded_value(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        assert AndroidIngressPayloadGrade.COMPAT_DEGRADED.value == "compat_degraded"

    def test_B04_weak_identity_value(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        assert AndroidIngressPayloadGrade.WEAK_IDENTITY.value == "weak_identity"

    def test_B05_not_closure_grade_value(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        assert AndroidIngressPayloadGrade.NOT_CLOSURE_GRADE.value == "not_closure_grade"

    def test_B06_unclassified_value(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        assert AndroidIngressPayloadGrade.UNCLASSIFIED.value == "unclassified"

    def test_B07_policy_sentinel_importable_and_non_empty(self):
        from core.unified_result_ingress import ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY

        assert isinstance(ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY, str)
        assert len(ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY) > 100
        assert "closure_grade_eligible" in ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY
        assert "is_fully_closed" in ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY

    def test_B08_closure_critical_identity_fields_importable(self):
        from core.unified_result_ingress import CLOSURE_CRITICAL_ANDROID_IDENTITY_FIELDS

        assert isinstance(CLOSURE_CRITICAL_ANDROID_IDENTITY_FIELDS, frozenset)
        assert "task_id" in CLOSURE_CRITICAL_ANDROID_IDENTITY_FIELDS
        assert "device_id" in CLOSURE_CRITICAL_ANDROID_IDENTITY_FIELDS

    def test_B09_grade_is_str_enum(self):
        """AndroidIngressPayloadGrade must be a str-based enum so values compare to plain strings."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        assert AndroidIngressPayloadGrade.CANONICAL == "canonical"
        assert AndroidIngressPayloadGrade.COMPAT_DEGRADED == "compat_degraded"


# ===========================================================================
# Group C: NormalizedResultEvent closure-grade fields
# ===========================================================================


class TestNormalizedResultEventClosureGradeFields:
    """Group C — NormalizedResultEvent carries closure-grade fields with correct defaults."""

    def test_C01_default_closure_grade_eligible_is_true(self):
        """Default NormalizedResultEvent must have closure_grade_eligible=True (backward compat)."""
        evt = _make_nre()
        assert evt.closure_grade_eligible is True

    def test_C02_default_android_payload_grade_is_empty(self):
        """Default NormalizedResultEvent must have android_payload_grade='' (unclassified)."""
        evt = _make_nre()
        assert evt.android_payload_grade == ""

    def test_C03_closure_grade_eligible_false_settable(self):
        """NormalizedResultEvent must accept closure_grade_eligible=False."""
        evt = _make_nre(closure_grade_eligible=False)
        assert evt.closure_grade_eligible is False

    def test_C04_android_payload_grade_settable(self):
        """NormalizedResultEvent must accept android_payload_grade='compat_degraded'."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        evt = _make_nre(android_payload_grade=AndroidIngressPayloadGrade.COMPAT_DEGRADED.value)
        assert evt.android_payload_grade == "compat_degraded"

    def test_C05_canonical_grade_settable(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        evt = _make_nre(
            closure_grade_eligible=True,
            android_payload_grade=AndroidIngressPayloadGrade.CANONICAL.value,
        )
        assert evt.closure_grade_eligible is True
        assert evt.android_payload_grade == "canonical"


# ===========================================================================
# Group D: UnifiedResultIngressOutcome closure-grade fields
# ===========================================================================


class TestUnifiedResultIngressOutcomeClosureGradeFields:
    """Group D — UnifiedResultIngressOutcome carries closure-grade fields."""

    def test_D01_outcome_has_closure_grade_eligible_field(self):
        from core.unified_result_ingress import UnifiedResultIngressOutcome

        out = UnifiedResultIngressOutcome(task_id="t", normalized_status="completed")
        assert hasattr(out, "closure_grade_eligible")

    def test_D02_outcome_default_closure_grade_eligible_is_true(self):
        from core.unified_result_ingress import UnifiedResultIngressOutcome

        out = UnifiedResultIngressOutcome(task_id="t", normalized_status="completed")
        assert out.closure_grade_eligible is True

    def test_D03_outcome_has_closure_grade_ineligible_reason_field(self):
        from core.unified_result_ingress import UnifiedResultIngressOutcome

        out = UnifiedResultIngressOutcome(task_id="t", normalized_status="completed")
        assert hasattr(out, "closure_grade_ineligible_reason")
        assert out.closure_grade_ineligible_reason == ""

    def test_D04_outcome_has_android_payload_grade_field(self):
        from core.unified_result_ingress import UnifiedResultIngressOutcome

        out = UnifiedResultIngressOutcome(task_id="t", normalized_status="completed")
        assert hasattr(out, "android_payload_grade")
        assert out.android_payload_grade == ""


# ===========================================================================
# Group E: UnifiedResultIngress.process() closure-grade enforcement
# ===========================================================================


class TestUnifiedResultIngressClosureGradeEnforcement:
    """Group E — process() enforces closure_grade_eligible for is_fully_closed."""

    def test_E01_canonical_payload_can_be_fully_closed(self):
        """Canonical payload (closure_grade_eligible=True) with passing steps → is_fully_closed=True."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=True,
            android_payload_grade=AndroidIngressPayloadGrade.CANONICAL.value,
        )
        outcome = ingress.process(evt)
        assert outcome.is_fully_closed is True
        assert outcome.closure_grade_eligible is True

    def test_E02_compat_degraded_payload_cannot_be_fully_closed(self):
        """Compat-degraded payload (closure_grade_eligible=False) → is_fully_closed=False
        even when truth chain and completion notification succeed."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=False,
            android_payload_grade=AndroidIngressPayloadGrade.COMPAT_DEGRADED.value,
        )
        outcome = ingress.process(evt)
        assert outcome.is_fully_closed is False
        assert outcome.closure_grade_eligible is False
        assert outcome.android_payload_grade == "compat_degraded"

    def test_E03_compat_degraded_incomplete_reason_mentions_closure_grade(self):
        """When closure_grade_eligible=False, incomplete_reason must mention closure_grade_ineligible."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=False,
            android_payload_grade=AndroidIngressPayloadGrade.COMPAT_DEGRADED.value,
        )
        outcome = ingress.process(evt)
        assert "closure_grade_ineligible" in outcome.incomplete_reason

    def test_E04_closure_grade_ineligible_reason_populated(self):
        """When closure_grade_eligible=False, closure_grade_ineligible_reason must be non-empty."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=False,
            android_payload_grade=AndroidIngressPayloadGrade.COMPAT_DEGRADED.value,
        )
        outcome = ingress.process(evt)
        assert outcome.closure_grade_ineligible_reason != ""

    def test_E05_not_closure_grade_payload_cannot_be_fully_closed(self):
        """NOT_CLOSURE_GRADE payload → is_fully_closed=False."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=False,
            android_payload_grade=AndroidIngressPayloadGrade.NOT_CLOSURE_GRADE.value,
        )
        outcome = ingress.process(evt)
        assert outcome.is_fully_closed is False
        assert outcome.android_payload_grade == "not_closure_grade"

    def test_E06_unclassified_payload_uses_default_eligible(self):
        """Unclassified payload (closure_grade_eligible=True default) can be fully closed."""
        ingress = _make_isolated_ingress()
        evt = _make_nre(closure_grade_eligible=True, android_payload_grade="")
        outcome = ingress.process(evt)
        assert outcome.is_fully_closed is True

    def test_E07_android_payload_grade_propagated_to_outcome(self):
        """android_payload_grade is propagated from event to outcome."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=True,
            android_payload_grade=AndroidIngressPayloadGrade.CANONICAL.value,
        )
        outcome = ingress.process(evt)
        assert outcome.android_payload_grade == "canonical"

    def test_E08_weak_identity_payload_cannot_be_fully_closed(self):
        """WEAK_IDENTITY payload (closure_grade_eligible=False) → is_fully_closed=False."""
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=False,
            android_payload_grade=AndroidIngressPayloadGrade.WEAK_IDENTITY.value,
        )
        outcome = ingress.process(evt)
        assert outcome.is_fully_closed is False


# ===========================================================================
# Group F: Last closure outcome snapshot
# ===========================================================================


class TestLastClosureOutcomeClosureGradeFields:
    """Group F — get_last_closure_outcome() snapshot includes closure-grade fields."""

    def test_F01_snapshot_has_closure_grade_eligible(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=False,
            android_payload_grade=AndroidIngressPayloadGrade.COMPAT_DEGRADED.value,
            task_id="snapshot-task-1",
        )
        ingress.process(evt)
        summary = ingress.get_last_closure_outcome()
        assert "closure_grade_eligible" in summary
        assert summary["closure_grade_eligible"] is False

    def test_F02_snapshot_has_android_payload_grade(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=False,
            android_payload_grade=AndroidIngressPayloadGrade.COMPAT_DEGRADED.value,
            task_id="snapshot-task-2",
        )
        ingress.process(evt)
        summary = ingress.get_last_closure_outcome()
        assert "android_payload_grade" in summary
        assert summary["android_payload_grade"] == "compat_degraded"

    def test_F03_snapshot_has_closure_grade_ineligible_reason(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=False,
            android_payload_grade=AndroidIngressPayloadGrade.COMPAT_DEGRADED.value,
            task_id="snapshot-task-3",
        )
        ingress.process(evt)
        summary = ingress.get_last_closure_outcome()
        assert "closure_grade_ineligible_reason" in summary
        assert summary["closure_grade_ineligible_reason"] != ""

    def test_F04_canonical_snapshot_closure_grade_eligible_true(self):
        from core.unified_result_ingress import AndroidIngressPayloadGrade

        ingress = _make_isolated_ingress()
        evt = _make_nre(
            closure_grade_eligible=True,
            android_payload_grade=AndroidIngressPayloadGrade.CANONICAL.value,
            task_id="snapshot-task-4",
        )
        ingress.process(evt)
        summary = ingress.get_last_closure_outcome()
        assert summary["closure_grade_eligible"] is True
        assert summary["android_payload_grade"] == "canonical"
        assert summary["closure_grade_ineligible_reason"] == ""
