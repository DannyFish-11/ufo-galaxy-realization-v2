"""tests/test_pr7a_v2_continuity_reconnect_recovery.py
==========================================================
PR-7A (sequence 11) regression suite — Close V2-side continuity,
reconnect, and recovery loops against real Android behavior.

Problem statement
-----------------
Close continuity, reconnect, and recovery paths against real Android behavior
rather than mock-only assumptions. Harden session reuse, attached runtime
handling, evidence ingress, recovery closure, duplicate result handling, and
offline replay interpretation so they work with true Android behavior and expose
canonical convergence or degradation outcomes.

Acceptance criteria
-------------------
* V2 recovery logic can participate in real dual-repo reconnect/recovery flows.
* Truth gaps become diagnosable.
* Recovery is no longer only supported by mock Android protocol tests.

Coverage groups
---------------
A.  Policy sentinel accessibility — all 7 policy sentinels importable and
    well-formed (POLICY:: prefix, non-empty).
B.  Session reuse hardening — absent ID, epoch mismatch, durable conflict,
    ID mismatch, no prior entry, and successful continuity_resume.
C.  Attached runtime truth assessment — android_confirmed, locally_inferred
    (stale signal), locally_inferred (no signal age), and unverifiable.
D.  Evidence ingress provenance classification — real_android, replay_queue,
    locally_synthesised, unknown_provenance, and flag-based overrides.
E.  Recovery closure quality assessment — full_convergence, partial_convergence,
    degraded_recovery, and no_recovery grading.
F.  Duplicate result handling — first_delivery accepted, confirmed_duplicate
    suppressed, out_of_order_replay suppressed, state not mutated on duplicate.
G.  Offline replay sequence interpretation — convergence_eligible, stale_dropped,
    duplicate_suppressed, gap_exposed, and mixed sequences.
H.  Build recovery participation report — dual_repo_participation_eligible flag,
    overall quality downgrade, cross-device isolation, JSON serialisability.
I.  Contract version and sentinel coverage — sentinel non-empty, POLICY:: prefix
    on all policy constants, contract version present.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest


# ===========================================================================
# A — Policy sentinel accessibility
# ===========================================================================


class TestPolicySentinelAccessibility:
    """A01–A09: All sentinels and policy constants are importable and well-formed."""

    def test_A01_sentinel_importable(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL,
        )
        assert isinstance(V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL, str)
        assert len(V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL) > 0
        assert "PR7A_SEQ11_V2" in V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL

    def test_A02_contract_version_importable(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION,
        )
        assert isinstance(V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION, str)
        assert "7a" in V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION.lower()

    def test_A03_session_reuse_absent_id_policy(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY,
        )
        assert isinstance(SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY, str)
        assert SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY.startswith("POLICY::")

    def test_A04_session_reuse_epoch_mismatch_policy(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            SESSION_REUSE_MUST_REJECT_EPOCH_MISMATCH_POLICY,
        )
        assert isinstance(SESSION_REUSE_MUST_REJECT_EPOCH_MISMATCH_POLICY, str)
        assert SESSION_REUSE_MUST_REJECT_EPOCH_MISMATCH_POLICY.startswith("POLICY::")

    def test_A05_attached_runtime_truth_policy(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            ATTACHED_RUNTIME_TRUTH_MUST_BE_GRADED_BEFORE_DELEGATION_POLICY,
        )
        assert isinstance(
            ATTACHED_RUNTIME_TRUTH_MUST_BE_GRADED_BEFORE_DELEGATION_POLICY, str
        )
        assert ATTACHED_RUNTIME_TRUTH_MUST_BE_GRADED_BEFORE_DELEGATION_POLICY.startswith(
            "POLICY::"
        )

    def test_A06_evidence_ingress_provenance_policy(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY,
        )
        assert isinstance(EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY, str)
        assert EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY.startswith(
            "POLICY::"
        )

    def test_A07_recovery_closure_quality_policy(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            RECOVERY_CLOSURE_QUALITY_MUST_BE_GRADED_POLICY,
        )
        assert isinstance(RECOVERY_CLOSURE_QUALITY_MUST_BE_GRADED_POLICY, str)
        assert RECOVERY_CLOSURE_QUALITY_MUST_BE_GRADED_POLICY.startswith("POLICY::")

    def test_A08_duplicate_result_suppression_policy(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            DUPLICATE_RESULT_MUST_BE_SUPPRESSED_BEFORE_STATE_MUTATION_POLICY,
        )
        assert isinstance(
            DUPLICATE_RESULT_MUST_BE_SUPPRESSED_BEFORE_STATE_MUTATION_POLICY, str
        )
        assert (
            DUPLICATE_RESULT_MUST_BE_SUPPRESSED_BEFORE_STATE_MUTATION_POLICY.startswith(
                "POLICY::"
            )
        )

    def test_A09_offline_replay_policy(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            OFFLINE_REPLAY_MUST_RESPECT_SESSION_EPOCH_AND_SEQUENCE_POLICY,
        )
        assert isinstance(
            OFFLINE_REPLAY_MUST_RESPECT_SESSION_EPOCH_AND_SEQUENCE_POLICY, str
        )
        assert (
            OFFLINE_REPLAY_MUST_RESPECT_SESSION_EPOCH_AND_SEQUENCE_POLICY.startswith(
                "POLICY::"
            )
        )


# ===========================================================================
# B — Session reuse hardening
# ===========================================================================


class TestSessionReuseHardening:
    """B01–B09: classify_session_reuse against real Android reconnect scenarios."""

    def _classify(self, **kwargs):
        from core.v2_android_recovery_continuity_hardening import classify_session_reuse
        return classify_session_reuse(**kwargs)

    def test_B01_absent_attachment_id_none(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id=None,
            stored_attachment_id="stored-id",
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.new_attachment_absent_id
        assert "absent" in result.diagnosis.lower()

    def test_B02_absent_attachment_id_empty_string(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="",
            stored_attachment_id="stored-id",
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.new_attachment_absent_id

    def test_B03_no_prior_entry(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="new-id",
            stored_attachment_id=None,
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.new_attachment_no_prior_entry

    def test_B04_epoch_mismatch(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="same-id",
            stored_attachment_id="same-id",
            presented_epoch=2,
            stored_epoch=1,
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.new_attachment_epoch_mismatch
        assert "epoch" in result.diagnosis.lower()

    def test_B05_durable_session_id_conflict(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="same-id",
            stored_attachment_id="same-id",
            presented_durable_session_id="durable-A",
            stored_durable_session_id="durable-B",
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.new_attachment_durable_conflict
        assert "conflict" in result.diagnosis.lower()

    def test_B06_attachment_id_mismatch(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="new-id",
            stored_attachment_id="old-id",
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.new_attachment_id_mismatch

    def test_B07_successful_continuity_resume(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="stable-id",
            stored_attachment_id="stable-id",
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.continuity_resume

    def test_B08_continuity_resume_with_matching_epoch(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="stable-id",
            stored_attachment_id="stable-id",
            presented_epoch=3,
            stored_epoch=3,
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.continuity_resume

    def test_B09_assessment_is_json_serialisable(self) -> None:
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="stable-id",
            stored_attachment_id="stable-id",
        )
        import json
        data = json.loads(result.to_json())
        assert data["outcome"] == "continuity_resume"
        assert "_sentinel" in data

    def test_B10_epoch_none_both_does_not_trigger_mismatch(self) -> None:
        """When both epochs are None, epoch check is skipped (not a mismatch)."""
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="stable-id",
            stored_attachment_id="stable-id",
            presented_epoch=None,
            stored_epoch=None,
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.continuity_resume

    def test_B11_durable_none_both_does_not_trigger_conflict(self) -> None:
        """When both durable IDs are None, conflict check is skipped."""
        result = self._classify(
            device_id="dev-1",
            presented_attachment_id="stable-id",
            stored_attachment_id="stable-id",
            presented_durable_session_id=None,
            stored_durable_session_id=None,
        )
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        assert result.outcome == SessionReuseOutcome.continuity_resume


# ===========================================================================
# C — Attached runtime truth assessment
# ===========================================================================


class TestAttachedRuntimeTruthAssessment:
    """C01–C07: assess_attached_runtime_truth grading."""

    def _assess(self, **kwargs):
        from core.v2_android_recovery_continuity_hardening import (
            assess_attached_runtime_truth,
        )
        return assess_attached_runtime_truth(**kwargs)

    def test_C01_android_confirmed_fresh_signal(self) -> None:
        result = self._assess(
            device_id="dev-1",
            runtime_attachment_session_id="att-id",
            registry_entry_present=True,
            last_signal_age_seconds=30.0,
        )
        from core.v2_android_recovery_continuity_hardening import AttachedRuntimeTruth
        assert result.truth == AttachedRuntimeTruth.android_confirmed

    def test_C02_locally_inferred_stale_signal(self) -> None:
        result = self._assess(
            device_id="dev-1",
            runtime_attachment_session_id="att-id",
            registry_entry_present=True,
            last_signal_age_seconds=300.0,  # > 120s threshold
        )
        from core.v2_android_recovery_continuity_hardening import AttachedRuntimeTruth
        assert result.truth == AttachedRuntimeTruth.locally_inferred
        assert "stale" in result.diagnosis.lower()

    def test_C03_locally_inferred_no_signal_age(self) -> None:
        result = self._assess(
            device_id="dev-1",
            runtime_attachment_session_id="att-id",
            registry_entry_present=True,
            last_signal_age_seconds=None,
        )
        from core.v2_android_recovery_continuity_hardening import AttachedRuntimeTruth
        assert result.truth == AttachedRuntimeTruth.locally_inferred

    def test_C04_unverifiable_no_registry_entry(self) -> None:
        result = self._assess(
            device_id="dev-1",
            runtime_attachment_session_id=None,
            registry_entry_present=False,
            last_signal_age_seconds=None,
        )
        from core.v2_android_recovery_continuity_hardening import AttachedRuntimeTruth
        assert result.truth == AttachedRuntimeTruth.unverifiable

    def test_C05_unverifiable_missing_attachment_id(self) -> None:
        result = self._assess(
            device_id="dev-1",
            runtime_attachment_session_id=None,
            registry_entry_present=True,
            last_signal_age_seconds=10.0,
        )
        from core.v2_android_recovery_continuity_hardening import AttachedRuntimeTruth
        assert result.truth == AttachedRuntimeTruth.unverifiable

    def test_C06_assessment_to_dict_includes_truth(self) -> None:
        result = self._assess(
            device_id="dev-1",
            runtime_attachment_session_id="att-id",
            registry_entry_present=True,
            last_signal_age_seconds=5.0,
        )
        d = result.to_dict()
        assert "truth" in d
        assert d["truth"] == "android_confirmed"
        assert "_sentinel" in d

    def test_C07_threshold_boundary_exact_match_is_confirmed(self) -> None:
        """Signal age exactly at threshold is android_confirmed (≤ threshold)."""
        result = self._assess(
            device_id="dev-1",
            runtime_attachment_session_id="att-id",
            registry_entry_present=True,
            last_signal_age_seconds=120.0,
        )
        from core.v2_android_recovery_continuity_hardening import AttachedRuntimeTruth
        assert result.truth == AttachedRuntimeTruth.android_confirmed

    def test_C08_threshold_boundary_just_above_is_inferred(self) -> None:
        """Signal age just above threshold is locally_inferred."""
        result = self._assess(
            device_id="dev-1",
            runtime_attachment_session_id="att-id",
            registry_entry_present=True,
            last_signal_age_seconds=120.1,
        )
        from core.v2_android_recovery_continuity_hardening import AttachedRuntimeTruth
        assert result.truth == AttachedRuntimeTruth.locally_inferred


# ===========================================================================
# D — Evidence ingress provenance classification
# ===========================================================================


class TestEvidenceIngressClassification:
    """D01–D08: classify_evidence_ingress provenance."""

    def _classify(self, **kwargs):
        from core.v2_android_recovery_continuity_hardening import (
            classify_evidence_ingress,
        )
        return classify_evidence_ingress(**kwargs)

    def test_D01_real_android_originated_via_hint(self) -> None:
        result = self._classify(
            evidence_id="ev-1",
            device_id="dev-1",
            provenance_hint="real_android",
        )
        from core.v2_android_recovery_continuity_hardening import (
            EvidenceIngressProvenance,
        )
        assert result.provenance == EvidenceIngressProvenance.real_android_originated
        assert result.is_degraded is False

    def test_D02_replay_queue_via_hint(self) -> None:
        result = self._classify(
            evidence_id="ev-2",
            device_id="dev-1",
            provenance_hint="replay_queue",
        )
        from core.v2_android_recovery_continuity_hardening import (
            EvidenceIngressProvenance,
        )
        assert result.provenance == EvidenceIngressProvenance.replay_queue_drained
        assert result.is_degraded is False

    def test_D03_locally_synthesised_via_hint(self) -> None:
        result = self._classify(
            evidence_id="ev-3",
            device_id="dev-1",
            provenance_hint="locally_synthesised",
        )
        from core.v2_android_recovery_continuity_hardening import (
            EvidenceIngressProvenance,
        )
        assert result.provenance == EvidenceIngressProvenance.locally_synthesised
        assert result.is_degraded is True

    def test_D04_unknown_provenance_none_hint(self) -> None:
        result = self._classify(
            evidence_id="ev-4",
            device_id="dev-1",
            provenance_hint=None,
        )
        from core.v2_android_recovery_continuity_hardening import (
            EvidenceIngressProvenance,
        )
        assert result.provenance == EvidenceIngressProvenance.unknown_provenance
        assert result.is_degraded is True

    def test_D05_unknown_provenance_unrecognized_hint(self) -> None:
        result = self._classify(
            evidence_id="ev-5",
            device_id="dev-1",
            provenance_hint="some_other_thing",
        )
        from core.v2_android_recovery_continuity_hardening import (
            EvidenceIngressProvenance,
        )
        assert result.provenance == EvidenceIngressProvenance.unknown_provenance

    def test_D06_from_replay_queue_flag_overrides(self) -> None:
        result = self._classify(
            evidence_id="ev-6",
            device_id="dev-1",
            provenance_hint=None,
            from_replay_queue=True,
        )
        from core.v2_android_recovery_continuity_hardening import (
            EvidenceIngressProvenance,
        )
        assert result.provenance == EvidenceIngressProvenance.replay_queue_drained

    def test_D07_from_local_synthesis_flag_overrides(self) -> None:
        result = self._classify(
            evidence_id="ev-7",
            device_id="dev-1",
            provenance_hint="real_android",
            from_local_synthesis=True,
        )
        from core.v2_android_recovery_continuity_hardening import (
            EvidenceIngressProvenance,
        )
        assert result.provenance == EvidenceIngressProvenance.locally_synthesised
        assert result.is_degraded is True

    def test_D08_assessment_is_json_serialisable(self) -> None:
        result = self._classify(
            evidence_id="ev-8",
            device_id="dev-1",
            provenance_hint="real_android",
        )
        import json
        data = json.loads(result.to_json())
        assert data["provenance"] == "real_android_originated"
        assert "_sentinel" in data


# ===========================================================================
# E — Recovery closure quality assessment
# ===========================================================================


class TestRecoveryClosureQualityAssessment:
    """E01–E08: assess_recovery_closure_quality graded outcomes."""

    def _assess(self, **kwargs):
        from core.v2_android_recovery_continuity_hardening import (
            assess_recovery_closure_quality,
        )
        return assess_recovery_closure_quality(**kwargs)

    def test_E01_full_convergence_all_resolved(self) -> None:
        result = self._assess(
            device_id="dev-1",
            session_id="sess-1",
            resolved_task_count=5,
            unresolved_task_count=0,
            degraded_task_count=0,
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert result.quality == RecoveryClosureQuality.full_convergence

    def test_E02_full_convergence_trivial_no_tasks(self) -> None:
        result = self._assess(
            device_id="dev-1",
            session_id=None,
            resolved_task_count=0,
            unresolved_task_count=0,
            degraded_task_count=0,
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert result.quality == RecoveryClosureQuality.full_convergence

    def test_E03_partial_convergence_some_unresolved(self) -> None:
        result = self._assess(
            device_id="dev-1",
            session_id="sess-1",
            resolved_task_count=3,
            unresolved_task_count=2,
            degraded_task_count=0,
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert result.quality == RecoveryClosureQuality.partial_convergence

    def test_E04_degraded_recovery_some_degraded(self) -> None:
        result = self._assess(
            device_id="dev-1",
            session_id="sess-1",
            resolved_task_count=4,
            unresolved_task_count=0,
            degraded_task_count=2,
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert result.quality == RecoveryClosureQuality.degraded_recovery

    def test_E05_no_recovery_nothing_resolved(self) -> None:
        result = self._assess(
            device_id="dev-1",
            session_id="sess-1",
            resolved_task_count=0,
            unresolved_task_count=5,
            degraded_task_count=0,
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert result.quality == RecoveryClosureQuality.no_recovery

    def test_E06_gap_descriptions_preserved(self) -> None:
        gaps = ["task t1 missing result", "task t2 stale evidence"]
        result = self._assess(
            device_id="dev-1",
            session_id="sess-1",
            resolved_task_count=2,
            unresolved_task_count=1,
            degraded_task_count=0,
            gap_descriptions=gaps,
        )
        assert result.gap_descriptions == gaps

    def test_E07_assessment_to_dict_has_quality(self) -> None:
        result = self._assess(
            device_id="dev-1",
            session_id="sess-1",
            resolved_task_count=3,
            unresolved_task_count=0,
            degraded_task_count=0,
        )
        d = result.to_dict()
        assert d["quality"] == "full_convergence"
        assert "_sentinel" in d

    def test_E08_partial_convergence_mixed_unresolved_and_degraded(self) -> None:
        result = self._assess(
            device_id="dev-1",
            session_id="sess-1",
            resolved_task_count=2,
            unresolved_task_count=1,
            degraded_task_count=1,
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert result.quality == RecoveryClosureQuality.partial_convergence


# ===========================================================================
# F — Duplicate result handling
# ===========================================================================


class TestDuplicateResultHandling:
    """F01–F08: classify_result_delivery — first delivery, duplicate, replay, stale."""

    def _classify(self, **kwargs):
        from core.v2_android_recovery_continuity_hardening import (
            classify_result_delivery,
        )
        return classify_result_delivery(**kwargs)

    def test_F01_first_delivery_accepted(self) -> None:
        seen = set()
        result = self._classify(
            task_id="t1",
            device_id="dev-1",
            idempotency_key="t1:seq1",
            durable_seen_keys=seen,
            task_already_terminal=False,
        )
        from core.v2_android_recovery_continuity_hardening import (
            ResultDeliveryClassification,
        )
        assert result.classification == ResultDeliveryClassification.first_delivery
        assert result.should_suppress is False
        assert "t1:seq1" in seen  # key registered

    def test_F02_confirmed_duplicate_suppressed(self) -> None:
        seen = {"t1:seq1"}
        result = self._classify(
            task_id="t1",
            device_id="dev-1",
            idempotency_key="t1:seq1",
            durable_seen_keys=seen,
            task_already_terminal=False,
        )
        from core.v2_android_recovery_continuity_hardening import (
            ResultDeliveryClassification,
        )
        assert result.classification == ResultDeliveryClassification.confirmed_duplicate
        assert result.should_suppress is True

    def test_F03_out_of_order_replay_suppressed(self) -> None:
        seen = set()
        result = self._classify(
            task_id="t1",
            device_id="dev-1",
            idempotency_key="t1:seq2",
            durable_seen_keys=seen,
            task_already_terminal=True,
        )
        from core.v2_android_recovery_continuity_hardening import (
            ResultDeliveryClassification,
        )
        assert result.classification == ResultDeliveryClassification.out_of_order_replay
        assert result.should_suppress is True

    def test_F04_state_not_mutated_on_confirmed_duplicate(self) -> None:
        """Duplicate detection runs before state mutation; idempotency key
        is NOT re-added for a confirmed_duplicate (it was already present)."""
        seen = {"t1:seq1"}
        result = self._classify(
            task_id="t1",
            device_id="dev-1",
            idempotency_key="t1:seq1",
            durable_seen_keys=seen,
        )
        # seen should not have grown
        assert seen == {"t1:seq1"}
        assert result.should_suppress is True

    def test_F05_two_different_tasks_both_first_delivery(self) -> None:
        seen = set()
        r1 = self._classify(
            task_id="tA",
            device_id="dev-1",
            idempotency_key="tA:seq1",
            durable_seen_keys=seen,
        )
        r2 = self._classify(
            task_id="tB",
            device_id="dev-1",
            idempotency_key="tB:seq1",
            durable_seen_keys=seen,
        )
        from core.v2_android_recovery_continuity_hardening import (
            ResultDeliveryClassification,
        )
        assert r1.classification == ResultDeliveryClassification.first_delivery
        assert r2.classification == ResultDeliveryClassification.first_delivery
        assert r1.should_suppress is False
        assert r2.should_suppress is False

    def test_F06_assessment_to_dict_has_classification(self) -> None:
        seen = set()
        result = self._classify(
            task_id="t1",
            device_id="dev-1",
            idempotency_key="t1:seq1",
            durable_seen_keys=seen,
        )
        d = result.to_dict()
        assert d["classification"] == "first_delivery"
        assert "_sentinel" in d

    def test_F07_out_of_order_replay_does_not_register_idempotency_key(self) -> None:
        """An out_of_order_replay should_suppress=True and NOT add to seen keys."""
        seen = set()
        result = self._classify(
            task_id="t1",
            device_id="dev-1",
            idempotency_key="t1:replay",
            durable_seen_keys=seen,
            task_already_terminal=True,
        )
        assert result.should_suppress is True
        # Key should NOT be in seen (no registration for replayed out-of-order)
        assert "t1:replay" not in seen

    def test_F08_first_delivery_json_serialisable(self) -> None:
        seen = set()
        result = self._classify(
            task_id="t1",
            device_id="dev-1",
            idempotency_key="t1:seq1",
            durable_seen_keys=seen,
        )
        import json
        data = json.loads(result.to_json())
        assert data["classification"] == "first_delivery"
        assert data["should_suppress"] is False


# ===========================================================================
# G — Offline replay sequence interpretation
# ===========================================================================


class TestOfflineReplaySequenceInterpretation:
    """G01–G10: interpret_replay_sequence against real Android behaviors."""

    def _interpret(self, items, **kwargs):
        from core.v2_android_recovery_continuity_hardening import (
            interpret_replay_sequence,
        )
        return interpret_replay_sequence(items, **kwargs)

    def test_G01_all_convergence_eligible_within_epoch(self) -> None:
        items = [
            {"item_id": "i1", "session_epoch": 3, "sequence_position": 1},
            {"item_id": "i2", "session_epoch": 3, "sequence_position": 2},
            {"item_id": "i3", "session_epoch": 3, "sequence_position": 3},
        ]
        results = self._interpret(items, expected_epoch=3)
        from core.v2_android_recovery_continuity_hardening import (
            ReplayItemClassification,
        )
        assert all(
            r.classification == ReplayItemClassification.convergence_eligible
            for r in results
        )

    def test_G02_stale_epoch_items_dropped(self) -> None:
        items = [
            {"item_id": "i1", "session_epoch": 1, "sequence_position": 1},
            {"item_id": "i2", "session_epoch": 3, "sequence_position": 2},
        ]
        results = self._interpret(items, expected_epoch=3)
        from core.v2_android_recovery_continuity_hardening import (
            ReplayItemClassification,
        )
        assert results[0].classification == ReplayItemClassification.stale_dropped
        assert results[1].classification == ReplayItemClassification.convergence_eligible

    def test_G03_duplicate_suppressed(self) -> None:
        seen = {"idem-key-1"}
        items = [
            {"item_id": "i1", "idempotency_key": "idem-key-1"},
        ]
        results = self._interpret(items, seen_idempotency_keys=seen)
        from core.v2_android_recovery_continuity_hardening import (
            ReplayItemClassification,
        )
        assert results[0].classification == ReplayItemClassification.duplicate_suppressed

    def test_G04_gap_exposed_on_sequence_jump(self) -> None:
        items = [
            {"item_id": "i1", "session_epoch": 3, "sequence_position": 1},
            {"item_id": "i2", "session_epoch": 3, "sequence_position": 5},  # gap!
        ]
        results = self._interpret(items, expected_epoch=3)
        from core.v2_android_recovery_continuity_hardening import (
            ReplayItemClassification,
        )
        assert results[0].classification == ReplayItemClassification.convergence_eligible
        assert results[1].classification == ReplayItemClassification.gap_exposed
        assert "gap" in results[1].diagnosis.lower()

    def test_G05_empty_sequence_produces_empty_result(self) -> None:
        results = self._interpret([])
        assert results == []

    def test_G06_no_epoch_check_when_expected_epoch_none(self) -> None:
        """When expected_epoch is None, items pass epoch check regardless of item epoch."""
        items = [
            {"item_id": "i1", "session_epoch": 99},
            {"item_id": "i2", "session_epoch": 1},
        ]
        results = self._interpret(items, expected_epoch=None)
        from core.v2_android_recovery_continuity_hardening import (
            ReplayItemClassification,
        )
        assert all(
            r.classification == ReplayItemClassification.convergence_eligible
            for r in results
        )

    def test_G07_mixed_scenario_real_android_behavior(self) -> None:
        """A realistic offline replay: some items stale, some duplicate, one gap, some ok."""
        seen: set[str] = set()
        items = [
            {"item_id": "i1", "session_epoch": 3, "sequence_position": 1},
            {"item_id": "i2", "session_epoch": 1, "sequence_position": 2},  # stale epoch
            {"item_id": "i3", "session_epoch": 3, "sequence_position": 2, "idempotency_key": "idem-1"},
            {"item_id": "i4", "session_epoch": 3, "sequence_position": 2, "idempotency_key": "idem-1"},  # dup
            {"item_id": "i5", "session_epoch": 3, "sequence_position": 7},  # gap after 2
        ]
        results = self._interpret(items, expected_epoch=3, seen_idempotency_keys=seen)
        from core.v2_android_recovery_continuity_hardening import (
            ReplayItemClassification,
        )
        assert results[0].classification == ReplayItemClassification.convergence_eligible
        assert results[1].classification == ReplayItemClassification.stale_dropped
        assert results[2].classification == ReplayItemClassification.convergence_eligible
        assert results[3].classification == ReplayItemClassification.duplicate_suppressed
        assert results[4].classification == ReplayItemClassification.gap_exposed

    def test_G08_item_assessment_is_dict_serialisable(self) -> None:
        items = [{"item_id": "i1", "session_epoch": 3, "sequence_position": 1}]
        results = self._interpret(items, expected_epoch=3)
        d = results[0].to_dict()
        assert "classification" in d
        assert "diagnosis" in d

    def test_G09_gap_exposed_item_still_registers_idempotency_key(self) -> None:
        """Even a gap_exposed item registers its key to prevent future duplicates."""
        seen: set[str] = set()
        items = [
            {"item_id": "i1", "session_epoch": 3, "sequence_position": 1},
            {"item_id": "i2", "session_epoch": 3, "sequence_position": 5},  # gap
        ]
        self._interpret(items, expected_epoch=3, seen_idempotency_keys=seen)
        assert "i1" in seen
        assert "i2" in seen  # gap_exposed item registers its key

    def test_G10_consecutive_positions_no_gap(self) -> None:
        """Consecutive sequence positions 1, 2, 3, 4 produce no gaps."""
        items = [
            {"item_id": f"i{n}", "session_epoch": 3, "sequence_position": n}
            for n in range(1, 5)
        ]
        results = self._interpret(items, expected_epoch=3)
        from core.v2_android_recovery_continuity_hardening import (
            ReplayItemClassification,
        )
        assert all(
            r.classification == ReplayItemClassification.convergence_eligible
            for r in results
        )


# ===========================================================================
# H — Build recovery participation report
# ===========================================================================


class TestBuildRecoveryParticipationReport:
    """H01–H09: build_recovery_participation_report overall quality and eligibility."""

    def _make_session_reuse(self, outcome_name: str):
        from core.v2_android_recovery_continuity_hardening import (
            SessionReuseAssessment,
            SessionReuseOutcome,
        )
        return SessionReuseAssessment(
            device_id="dev-1",
            presented_attachment_id="att-id",
            stored_attachment_id="att-id",
            presented_epoch=None,
            stored_epoch=None,
            presented_durable_session_id=None,
            stored_durable_session_id=None,
            outcome=SessionReuseOutcome(outcome_name),
            diagnosis="test",
        )

    def _make_runtime_truth(self, truth_name: str):
        from core.v2_android_recovery_continuity_hardening import (
            AttachedRuntimeTruth,
            AttachedRuntimeTruthAssessment,
        )
        return AttachedRuntimeTruthAssessment(
            device_id="dev-1",
            runtime_attachment_session_id="att-id",
            truth=AttachedRuntimeTruth(truth_name),
            diagnosis="test",
        )

    def _make_evidence(self, provenance_name: str, is_degraded: bool = False):
        from core.v2_android_recovery_continuity_hardening import (
            EvidenceIngressAssessment,
            EvidenceIngressProvenance,
        )
        return EvidenceIngressAssessment(
            evidence_id="ev-1",
            device_id="dev-1",
            provenance=EvidenceIngressProvenance(provenance_name),
            is_degraded=is_degraded,
            diagnosis="test",
        )

    def _make_closure(self, quality_name: str):
        from core.v2_android_recovery_continuity_hardening import (
            RecoveryClosureAssessment,
            RecoveryClosureQuality,
        )
        return RecoveryClosureAssessment(
            device_id="dev-1",
            session_id="sess-1",
            quality=RecoveryClosureQuality(quality_name),
            resolved_task_count=3,
            unresolved_task_count=0,
            degraded_task_count=0,
            diagnosis="test",
        )

    def _build(self, session_reuse, runtime_truth, evidence, closure, replay_items=None):
        from core.v2_android_recovery_continuity_hardening import (
            build_recovery_participation_report,
        )
        return build_recovery_participation_report(
            device_id="dev-1",
            session_id="sess-1",
            session_reuse=session_reuse,
            attached_runtime_truth=runtime_truth,
            evidence_ingress=evidence,
            recovery_closure=closure,
            replay_items=replay_items,
        )

    def test_H01_full_eligibility_all_green(self) -> None:
        report = self._build(
            self._make_session_reuse("continuity_resume"),
            self._make_runtime_truth("android_confirmed"),
            self._make_evidence("real_android_originated"),
            self._make_closure("full_convergence"),
        )
        assert report.dual_repo_participation_eligible is True
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert report.overall_recovery_quality == RecoveryClosureQuality.full_convergence

    def test_H02_not_eligible_when_new_attachment(self) -> None:
        report = self._build(
            self._make_session_reuse("new_attachment_absent_id"),
            self._make_runtime_truth("android_confirmed"),
            self._make_evidence("real_android_originated"),
            self._make_closure("full_convergence"),
        )
        assert report.dual_repo_participation_eligible is False

    def test_H03_not_eligible_when_unverifiable_runtime(self) -> None:
        report = self._build(
            self._make_session_reuse("continuity_resume"),
            self._make_runtime_truth("unverifiable"),
            self._make_evidence("real_android_originated"),
            self._make_closure("full_convergence"),
        )
        assert report.dual_repo_participation_eligible is False

    def test_H04_degraded_when_evidence_is_degraded(self) -> None:
        report = self._build(
            self._make_session_reuse("continuity_resume"),
            self._make_runtime_truth("android_confirmed"),
            self._make_evidence("unknown_provenance", is_degraded=True),
            self._make_closure("full_convergence"),
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert report.overall_recovery_quality == RecoveryClosureQuality.degraded_recovery

    def test_H05_degraded_when_runtime_is_locally_inferred(self) -> None:
        report = self._build(
            self._make_session_reuse("continuity_resume"),
            self._make_runtime_truth("locally_inferred"),
            self._make_evidence("real_android_originated"),
            self._make_closure("full_convergence"),
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert report.overall_recovery_quality == RecoveryClosureQuality.degraded_recovery

    def test_H06_no_recovery_when_closure_is_no_recovery(self) -> None:
        report = self._build(
            self._make_session_reuse("continuity_resume"),
            self._make_runtime_truth("android_confirmed"),
            self._make_evidence("real_android_originated"),
            self._make_closure("no_recovery"),
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert report.overall_recovery_quality == RecoveryClosureQuality.no_recovery
        assert report.dual_repo_participation_eligible is False

    def test_H07_eligible_with_degraded_recovery(self) -> None:
        """degraded_recovery is still eligible for dual-repo participation."""
        report = self._build(
            self._make_session_reuse("continuity_resume"),
            self._make_runtime_truth("android_confirmed"),
            self._make_evidence("real_android_originated"),
            self._make_closure("degraded_recovery"),
        )
        assert report.dual_repo_participation_eligible is True

    def test_H08_report_is_json_serialisable(self) -> None:
        report = self._build(
            self._make_session_reuse("continuity_resume"),
            self._make_runtime_truth("android_confirmed"),
            self._make_evidence("real_android_originated"),
            self._make_closure("full_convergence"),
        )
        import json
        data = json.loads(report.to_json())
        assert "_sentinel" in data
        assert data["dual_repo_participation_eligible"] is True
        assert data["contract_version"] == "7a.seq11.0.0"

    def test_H09_replay_gap_degrades_overall_quality(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            ReplayItemClassification,
            ReplaySequenceItemAssessment,
        )
        gap_item = ReplaySequenceItemAssessment(
            sequence_index=1,
            item_id="i2",
            session_epoch=3,
            expected_epoch=3,
            sequence_position=5,
            last_accepted_position=1,
            classification=ReplayItemClassification.gap_exposed,
            diagnosis="gap",
        )
        report = self._build(
            self._make_session_reuse("continuity_resume"),
            self._make_runtime_truth("android_confirmed"),
            self._make_evidence("real_android_originated"),
            self._make_closure("full_convergence"),
            replay_items=[gap_item],
        )
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        assert report.overall_recovery_quality == RecoveryClosureQuality.degraded_recovery


# ===========================================================================
# I — Contract version and sentinel coverage
# ===========================================================================


class TestContractVersionAndSentinelCoverage:
    """I01–I06: Sentinel format, contract version, and POLICY:: coverage."""

    def test_I01_sentinel_contains_pr7a_seq11(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL,
        )
        assert "PR7A_SEQ11_V2" in V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL

    def test_I02_contract_version_is_string(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION,
        )
        assert isinstance(V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION, str)
        assert V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION != ""

    def test_I03_all_policy_constants_have_policy_prefix(self) -> None:
        import core.v2_android_recovery_continuity_hardening as mod
        policy_names = [
            "SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY",
            "SESSION_REUSE_MUST_REJECT_EPOCH_MISMATCH_POLICY",
            "SESSION_REUSE_MUST_REJECT_DURABLE_ID_CONFLICT_POLICY",
            "ATTACHED_RUNTIME_TRUTH_MUST_BE_GRADED_BEFORE_DELEGATION_POLICY",
            "EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY",
            "RECOVERY_CLOSURE_QUALITY_MUST_BE_GRADED_POLICY",
            "DUPLICATE_RESULT_MUST_BE_SUPPRESSED_BEFORE_STATE_MUTATION_POLICY",
            "OFFLINE_REPLAY_MUST_RESPECT_SESSION_EPOCH_AND_SEQUENCE_POLICY",
        ]
        for name in policy_names:
            value = getattr(mod, name)
            assert isinstance(value, str), f"{name} should be a string"
            assert value.startswith("POLICY::"), f"{name} should start with POLICY::"
            assert len(value) > len("POLICY::"), f"{name} should have content after POLICY::"

    def test_I04_session_reuse_outcome_enum_values(self) -> None:
        from core.v2_android_recovery_continuity_hardening import SessionReuseOutcome
        expected = {
            "continuity_resume",
            "new_attachment_absent_id",
            "new_attachment_epoch_mismatch",
            "new_attachment_durable_conflict",
            "new_attachment_no_prior_entry",
            "new_attachment_id_mismatch",
        }
        actual = {m.value for m in SessionReuseOutcome}
        assert actual == expected

    def test_I05_recovery_closure_quality_enum_values(self) -> None:
        from core.v2_android_recovery_continuity_hardening import RecoveryClosureQuality
        expected = {
            "full_convergence",
            "partial_convergence",
            "degraded_recovery",
            "no_recovery",
        }
        actual = {m.value for m in RecoveryClosureQuality}
        assert actual == expected

    def test_I06_result_delivery_classification_enum_values(self) -> None:
        from core.v2_android_recovery_continuity_hardening import (
            ResultDeliveryClassification,
        )
        expected = {
            "first_delivery",
            "confirmed_duplicate",
            "out_of_order_replay",
            "stale_result",
        }
        actual = {m.value for m in ResultDeliveryClassification}
        assert actual == expected
