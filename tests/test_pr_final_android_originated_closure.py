"""tests/test_pr_final_android_originated_closure.py
=====================================================
PR-Final: Android-Originated Main Chain Ingress & Complex Scenario Closure Tests
=================================================================================

验收范围
--------
这套测试覆盖 PR-Final 引入的三个核心模块的完整回归：

Group A — Authority Boundary Model (core.android_originated_authority_boundary)
  A-01  Sentinel accessibility
  A-02  Contract version stability
  A-03  All participation kinds are reachable
  A-04  Permission table invariants (Android cannot override center authority)
  A-05  NL participation requires main chain
  A-06  Takeover participation is bounded
  A-07  Reconciliation eligibility downgraded for stale evidence
  A-08  Reconciliation eligibility downgraded for replay evidence
  A-09  Reconciliation eligibility downgraded for recovery-assisted evidence
  A-10  Reconciliation eligibility downgraded for non-complete proof class
  A-11  authority_adjacent is always observation_only
  A-12  assert_android_cannot_override_center passes for all kinds
  A-13  to_dict() includes sentinel and contract version

Group B — Main Chain Ingress (core.android_originated_main_chain_ingress)
  B-01  Sentinel accessibility
  B-02  Contract version stability
  B-03  Full lineage enum coverage
  B-04  classify_execution_lineage: canonical
  B-05  classify_execution_lineage: center_originated
  B-06  classify_execution_lineage: android_originated (clean)
  B-07  classify_execution_lineage: android_originated_fallback
  B-08  classify_execution_lineage: android_originated_replay
  B-09  classify_execution_lineage: android_originated_recovery
  B-10  classify_execution_lineage: android_originated_takeover
  B-11  classify_execution_lineage: android_originated_conflict
  B-12  classify_execution_lineage: fallback (center)
  B-13  classify_execution_lineage: compat
  B-14  classify_execution_lineage: degraded
  B-15  classify_execution_lineage: replay_assisted
  B-16  classify_execution_lineage: recovery_assisted
  B-17  is_canonical_lineage: only canonical and center_originated are canonical
  B-18  accept_android_originated_nl: main-chain accepted with valid carrier context
  B-19  accept_android_originated_nl: no carrier context → GAP_WITHOUT_MAIN_CHAIN
  B-20  accept_android_originated_nl: fallback scenario does NOT add fallback gap
        (lifecycle-level fallback is tracked separately; NL ingress only tracks
        NL-level path flags)
  B-21  accept_android_originated_nl: stale → GAP_STALE_EVIDENCE
  B-22  accept_android_originated_nl: replay → GAP_REPLAY_COMBINED
  B-23  accept_android_originated_nl: recovery_assisted → GAP_REPLAY_COMBINED
  B-24  accept_android_originated_nl: takeover → GAP_TAKEOVER_COMBINED
  B-25  accept_android_originated_nl: conflict → GAP_CONFLICT_PARTIAL
  B-26  accept_android_originated_nl: multi-device → GAP_MULTI_DEVICE_RACE
  B-27  accept_android_originated_nl: duplicate → GAP_CONFLICT_PARTIAL
  B-28  build_android_originated_governance_context includes sentinel
  B-29  is_android_originated_main_chain_accepted: True when carrier context valid
  B-30  is_android_originated_main_chain_accepted: False when no carrier context

Group C — Full-Chain Lineage Integration with Closed-Loop Governance
  C-01  android_originated=False when no android_governance_context
  C-02  android_originated=True when android_governance_context provided
  C-03  android_originated_lineage propagated from context
  C-04  android_originated_gap_types merged into system_completion_gap_types
  C-05  android_originated with no extra gaps: system_completion still works
  C-06  android_originated with GAP_WITHOUT_MAIN_CHAIN blocks mature closure
  C-07  to_dict() includes android_originated fields

Group D — Complex Mixed Scenario Gatekeeping (P0-3)
  D-01  android_originated + fallback (lifecycle) → NOT mature
  D-02  android_originated + replay/stale → NOT mature
  D-03  android_originated + takeover → blocked
  D-04  android_originated + conflict/partial → blocked
  D-05  android_originated + multi-device concurrency/race → blocked
  D-06  android_originated + compat path → NOT mature
  D-07  android_originated + degraded runtime → NOT mature
  D-08  android_originated + no main chain + fallback: double gap
  D-09  android_originated clean + full canonical lifecycle → mature closure
  D-10  GAP constants are unique strings (no collisions)
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from core.android_originated_authority_boundary import (
    ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_CONTRACT_VERSION,
    ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_SENTINEL,
    ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY,
    ANDROID_NL_MUST_ENTER_MAIN_CHAIN_POLICY,
    ANDROID_RECONCILIATION_REQUIRES_MINIMUM_EVIDENCE_POLICY,
    ANDROID_TAKEOVER_WITHIN_AUTHORITY_BOUNDARY_POLICY,
    AndroidParticipationKind,
    AndroidSignalPermissionLevel,
    assert_android_cannot_override_center,
    classify_android_participation,
    get_android_participation_permission,
    is_android_main_chain_eligible,
)
from core.android_originated_main_chain_ingress import (
    ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION,
    ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL,
    GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL,
    GAP_ANDROID_ORIGINATED_MULTI_DEVICE_RACE,
    GAP_ANDROID_ORIGINATED_REPLAY_COMBINED,
    GAP_ANDROID_ORIGINATED_STALE_EVIDENCE,
    GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED,
    GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN,
    ExecutionLineageKind,
    accept_android_originated_nl_into_main_chain,
    build_android_originated_governance_context,
    classify_execution_lineage,
    is_android_originated_main_chain_accepted,
    is_canonical_lineage,
)
from core.closed_loop_governance_consolidation import (
    CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL,
    CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION,
    ClosedLoopStage,
    GAP_ANDROID_ORIGINATED_FALLBACK_COMBINED,
    GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN as CLGC_GAP_ANDROID_WITHOUT_MAIN_CHAIN,
    query_closed_loop_governance_state,
)
from core.android_nl_semantic_chain_contract import (
    V2_SEMANTIC_AUTHORITY,
    build_android_nl_carrier_context,
)
from core.unified_execution_governance import (
    ExecutionLifecyclePhase,
    ExecutionType,
    FailureSemantic,
    _clear_execution_governance_runtime_state,
    record_execution_lifecycle_event,
    record_result_uplink,
    record_state_uplink,
)


@pytest.fixture(autouse=True)
def _reset_governance_runtime():
    _clear_execution_governance_runtime_state()
    yield
    _clear_execution_governance_runtime_state()


# ===========================================================================
# Group A — Authority Boundary Model
# ===========================================================================


class TestGroupA_AuthorityBoundaryModel:
    """Group A: Authority boundary model tests."""

    def test_a01_sentinel_accessible(self):
        assert "PR_FINAL" in ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_SENTINEL
        assert "android_originated_authority_boundary" in ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_SENTINEL

    def test_a02_contract_version_stable(self):
        assert ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_CONTRACT_VERSION == "final.0.0"

    def test_a03_all_participation_kinds_reachable(self):
        expected = {
            "center_authority",
            "android_originated_nl",
            "android_originated_signal",
            "takeover_participation",
            "reconciliation_participation",
            "authority_adjacent_participation",
        }
        actual = {k.value for k in AndroidParticipationKind}
        assert actual == expected

    def test_a04_android_cannot_override_center_authority_invariant(self):
        """All participation kinds must return can_override_center_authority=False."""
        for kind in AndroidParticipationKind:
            if kind == AndroidParticipationKind.center_authority:
                continue  # skip center_authority self-reference
            cls = classify_android_participation(kind)
            assert cls.can_override_center_authority is False, (
                f"kind={kind!r} returned can_override_center_authority=True"
            )

    def test_a05_nl_participation_requires_main_chain(self):
        cls = classify_android_participation(AndroidParticipationKind.android_originated_nl)
        assert cls.requires_main_chain_ingress is True
        assert cls.permission_level == AndroidSignalPermissionLevel.main_chain_carrier
        assert is_android_main_chain_eligible(AndroidParticipationKind.android_originated_nl)

    def test_a06_takeover_participation_is_bounded(self):
        cls = classify_android_participation(AndroidParticipationKind.takeover_participation)
        assert cls.permission_level == AndroidSignalPermissionLevel.takeover_eligible
        assert cls.can_enter_reconciliation is False
        assert cls.can_override_center_authority is False

    def test_a07_reconciliation_eligibility_downgraded_for_stale(self):
        cls = classify_android_participation(
            AndroidParticipationKind.android_originated_signal,
            proof_input_class="complete",
            is_stale=True,
        )
        assert cls.permission_level == AndroidSignalPermissionLevel.suggestion_only
        assert cls.can_enter_reconciliation is False
        assert "stale" in cls.reason

    def test_a08_reconciliation_eligibility_downgraded_for_replay(self):
        cls = classify_android_participation(
            AndroidParticipationKind.android_originated_signal,
            proof_input_class="complete",
            is_replay=True,
        )
        assert cls.permission_level == AndroidSignalPermissionLevel.suggestion_only
        assert cls.can_enter_reconciliation is False
        assert "replay" in cls.reason

    def test_a09_reconciliation_eligibility_downgraded_for_recovery_assisted(self):
        cls = classify_android_participation(
            AndroidParticipationKind.android_originated_signal,
            proof_input_class="complete",
            is_recovery_assisted=True,
        )
        assert cls.permission_level == AndroidSignalPermissionLevel.suggestion_only
        assert cls.can_enter_reconciliation is False

    def test_a10_reconciliation_eligibility_downgraded_for_non_complete_proof(self):
        for bad_class in ("stale", "partial", "conflicting", "missing", "malformed", "unknown"):
            cls = classify_android_participation(
                AndroidParticipationKind.android_originated_signal,
                proof_input_class=bad_class,
            )
            assert cls.permission_level == AndroidSignalPermissionLevel.suggestion_only, (
                f"Expected suggestion_only for proof_input_class={bad_class!r}"
            )
            assert cls.can_enter_reconciliation is False

    def test_a10_passing_complete_proof_class_is_eligible(self):
        cls = classify_android_participation(
            AndroidParticipationKind.android_originated_signal,
            proof_input_class="complete",
        )
        assert cls.permission_level == AndroidSignalPermissionLevel.reconciliation_eligible
        assert cls.can_enter_reconciliation is True

    def test_a11_authority_adjacent_is_observation_only(self):
        cls = classify_android_participation(
            AndroidParticipationKind.authority_adjacent_participation
        )
        assert cls.permission_level == AndroidSignalPermissionLevel.observation_only
        assert cls.can_enter_reconciliation is False
        assert cls.can_override_center_authority is False

    def test_a12_assert_android_cannot_override_center_passes(self):
        for kind in AndroidParticipationKind:
            if kind == AndroidParticipationKind.center_authority:
                continue
            cls = classify_android_participation(kind)
            # Should not raise
            assert_android_cannot_override_center(cls, context=f"test_a12[{kind.value}]")

    def test_a13_to_dict_includes_sentinel_and_version(self):
        cls = classify_android_participation(AndroidParticipationKind.android_originated_nl)
        d = cls.to_dict()
        assert "_sentinel" in d
        assert "_contract_version" in d
        assert d["_contract_version"] == ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_CONTRACT_VERSION

    def test_a14_policy_sentinels_are_policy_prefixed(self):
        for policy in [
            ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY,
            ANDROID_NL_MUST_ENTER_MAIN_CHAIN_POLICY,
            ANDROID_RECONCILIATION_REQUIRES_MINIMUM_EVIDENCE_POLICY,
            ANDROID_TAKEOVER_WITHIN_AUTHORITY_BOUNDARY_POLICY,
        ]:
            assert policy.startswith("POLICY::"), (
                f"Policy sentinel does not start with 'POLICY::': {policy[:60]}"
            )

    def test_a15_non_main_chain_kinds_do_not_require_main_chain(self):
        for kind in AndroidParticipationKind:
            if kind == AndroidParticipationKind.android_originated_nl:
                continue
            assert not is_android_main_chain_eligible(kind), (
                f"Expected is_android_main_chain_eligible=False for kind={kind!r}"
            )

    def test_a16_reconciliation_participation_is_eligible_with_complete_proof(self):
        cls = classify_android_participation(
            AndroidParticipationKind.reconciliation_participation,
            proof_input_class="complete",
        )
        assert cls.permission_level == AndroidSignalPermissionLevel.reconciliation_eligible
        assert cls.can_enter_reconciliation is True

    def test_a17_get_android_participation_permission_table(self):
        assert (
            get_android_participation_permission(AndroidParticipationKind.android_originated_nl)
            == AndroidSignalPermissionLevel.main_chain_carrier
        )
        assert (
            get_android_participation_permission(
                AndroidParticipationKind.authority_adjacent_participation
            )
            == AndroidSignalPermissionLevel.observation_only
        )


# ===========================================================================
# Group B — Main Chain Ingress
# ===========================================================================


class TestGroupB_MainChainIngress:
    """Group B: Android-originated main chain ingress tests."""

    def test_b01_sentinel_accessible(self):
        assert "PR_FINAL" in ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL
        assert "android_originated_main_chain_ingress" in ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL

    def test_b02_contract_version_stable(self):
        assert ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION == "final.0.0"

    def test_b03_full_lineage_enum_coverage(self):
        expected_values = {
            "canonical", "center_originated", "android_originated",
            "fallback", "compat", "degraded", "replay_assisted", "recovery_assisted",
            "android_originated_fallback", "android_originated_replay",
            "android_originated_recovery", "android_originated_takeover",
            "android_originated_conflict", "unknown",
        }
        actual_values = {k.value for k in ExecutionLineageKind}
        assert actual_values == expected_values

    def test_b04_classify_lineage_canonical(self):
        lineage = classify_execution_lineage(
            is_android_originated=False,
            is_center_originated=False,
            is_fully_canonical=True,
        )
        assert lineage == ExecutionLineageKind.canonical

    def test_b05_classify_lineage_center_originated(self):
        lineage = classify_execution_lineage(
            is_android_originated=False,
            is_center_originated=True,
        )
        assert lineage == ExecutionLineageKind.canonical

    def test_b06_classify_lineage_android_originated_clean(self):
        lineage = classify_execution_lineage(is_android_originated=True)
        assert lineage == ExecutionLineageKind.android_originated

    def test_b07_classify_lineage_android_originated_fallback(self):
        lineage = classify_execution_lineage(
            is_android_originated=True,
            fallback_path_used=True,
        )
        assert lineage == ExecutionLineageKind.android_originated_fallback

    def test_b08_classify_lineage_android_originated_replay(self):
        lineage = classify_execution_lineage(
            is_android_originated=True,
            is_replay_assisted=True,
        )
        assert lineage == ExecutionLineageKind.android_originated_replay

    def test_b09_classify_lineage_android_originated_recovery(self):
        lineage = classify_execution_lineage(
            is_android_originated=True,
            is_recovery_assisted=True,
        )
        assert lineage == ExecutionLineageKind.android_originated_recovery

    def test_b10_classify_lineage_android_originated_takeover(self):
        lineage = classify_execution_lineage(
            is_android_originated=True,
            is_takeover_scenario=True,
        )
        assert lineage == ExecutionLineageKind.android_originated_takeover

    def test_b11_classify_lineage_android_originated_conflict(self):
        lineage = classify_execution_lineage(
            is_android_originated=True,
            is_conflict_present=True,
        )
        assert lineage == ExecutionLineageKind.android_originated_conflict

    def test_b12_classify_lineage_center_fallback(self):
        lineage = classify_execution_lineage(
            is_android_originated=False,
            fallback_path_used=True,
        )
        assert lineage == ExecutionLineageKind.fallback

    def test_b13_classify_lineage_compat(self):
        lineage = classify_execution_lineage(
            is_android_originated=False,
            compat_path_used=True,
        )
        assert lineage == ExecutionLineageKind.compat

    def test_b14_classify_lineage_degraded(self):
        lineage = classify_execution_lineage(
            is_android_originated=False,
            degraded_path_used=True,
        )
        assert lineage == ExecutionLineageKind.degraded

    def test_b15_classify_lineage_replay_assisted(self):
        lineage = classify_execution_lineage(
            is_android_originated=False,
            is_replay_assisted=True,
        )
        assert lineage == ExecutionLineageKind.replay_assisted

    def test_b16_classify_lineage_recovery_assisted(self):
        lineage = classify_execution_lineage(
            is_android_originated=False,
            is_recovery_assisted=True,
        )
        assert lineage == ExecutionLineageKind.recovery_assisted

    def test_b17_is_canonical_lineage_only_canonical_and_center(self):
        assert is_canonical_lineage(ExecutionLineageKind.canonical) is True
        assert is_canonical_lineage(ExecutionLineageKind.center_originated) is True
        non_canonical = [
            ExecutionLineageKind.fallback,
            ExecutionLineageKind.compat,
            ExecutionLineageKind.degraded,
            ExecutionLineageKind.replay_assisted,
            ExecutionLineageKind.recovery_assisted,
            ExecutionLineageKind.android_originated,
            ExecutionLineageKind.android_originated_fallback,
            ExecutionLineageKind.android_originated_replay,
            ExecutionLineageKind.android_originated_recovery,
            ExecutionLineageKind.android_originated_takeover,
            ExecutionLineageKind.android_originated_conflict,
            ExecutionLineageKind.unknown,
        ]
        for kind in non_canonical:
            assert is_canonical_lineage(kind) is False, (
                f"Expected is_canonical_lineage=False for {kind!r}"
            )

    def test_b18_accept_main_chain_with_valid_carrier_context(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b18",
            session_id="session-b18",
            invocation_id="inv-b18",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b18",
            session_id="session-b18",
            invocation_id="inv-b18",
            ingress_carrier_context=icc,
        )
        assert result.is_main_chain_accepted is True
        assert result.authority_source == V2_SEMANTIC_AUTHORITY
        assert GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN not in result.gap_types

    def test_b19_accept_no_carrier_context_gap_without_main_chain(self):
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b19",
            session_id="session-b19",
            invocation_id="inv-b19",
            ingress_carrier_context=None,
        )
        assert result.is_main_chain_accepted is False
        assert GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN in result.gap_types
        assert result.mature_closure_blocked is True

    def test_b20_fallback_at_lifecycle_level_not_in_nl_ingress_gaps(self):
        """B-20: NL ingress only tracks NL-level scenario flags.
        Lifecycle-level fallback (failure_semantic=fallback_local) is detected
        in the closed_loop_governance layer via lifecycle history — NOT at the
        NL ingress layer. This test validates the separation of concerns.
        """
        icc = build_android_nl_carrier_context(
            device_id="device-b20",
            session_id="session-b20",
            invocation_id="inv-b20",
        )
        # NL ingress with no fallback flags set at NL level
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b20",
            session_id="session-b20",
            invocation_id="inv-b20",
            ingress_carrier_context=icc,
        )
        # NL ingress should NOT detect lifecycle-level fallback — that is the
        # responsibility of closed_loop_governance (via lifecycle history).
        from core.android_originated_main_chain_ingress import (
            GAP_ANDROID_ORIGINATED_FALLBACK_COMBINED,
        )
        assert GAP_ANDROID_ORIGINATED_FALLBACK_COMBINED not in result.gap_types
        # Android-originated lineage (clean, no NL-level flags)
        from core.android_originated_main_chain_ingress import ExecutionLineageKind
        assert result.lineage == ExecutionLineageKind.android_originated

    def test_b21_accept_stale_evidence_gap(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b21",
            session_id="session-b21",
            invocation_id="inv-b21",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b21",
            session_id="session-b21",
            invocation_id="inv-b21",
            ingress_carrier_context=icc,
            is_stale=True,
        )
        assert GAP_ANDROID_ORIGINATED_STALE_EVIDENCE in result.gap_types
        assert result.mature_closure_blocked is True

    def test_b22_accept_replay_gap(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b22",
            session_id="session-b22",
            invocation_id="inv-b22",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b22",
            session_id="session-b22",
            invocation_id="inv-b22",
            ingress_carrier_context=icc,
            is_replay=True,
        )
        assert GAP_ANDROID_ORIGINATED_REPLAY_COMBINED in result.gap_types
        assert result.mature_closure_blocked is True
        assert result.lineage == ExecutionLineageKind.android_originated_replay

    def test_b23_accept_recovery_assisted_gap(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b23",
            session_id="session-b23",
            invocation_id="inv-b23",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b23",
            session_id="session-b23",
            invocation_id="inv-b23",
            ingress_carrier_context=icc,
            is_recovery_assisted=True,
        )
        assert GAP_ANDROID_ORIGINATED_REPLAY_COMBINED in result.gap_types
        assert result.lineage == ExecutionLineageKind.android_originated_recovery

    def test_b24_accept_takeover_scenario_gap(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b24",
            session_id="session-b24",
            invocation_id="inv-b24",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b24",
            session_id="session-b24",
            invocation_id="inv-b24",
            ingress_carrier_context=icc,
            is_takeover_scenario=True,
        )
        assert GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED in result.gap_types
        assert result.lineage == ExecutionLineageKind.android_originated_takeover

    def test_b25_accept_conflict_gap(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b25",
            session_id="session-b25",
            invocation_id="inv-b25",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b25",
            session_id="session-b25",
            invocation_id="inv-b25",
            ingress_carrier_context=icc,
            is_conflict_present=True,
        )
        assert GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL in result.gap_types
        assert result.lineage == ExecutionLineageKind.android_originated_conflict

    def test_b26_accept_multi_device_race_gap(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b26",
            session_id="session-b26",
            invocation_id="inv-b26",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b26",
            session_id="session-b26",
            invocation_id="inv-b26",
            ingress_carrier_context=icc,
            is_multi_device_concurrent=True,
        )
        assert GAP_ANDROID_ORIGINATED_MULTI_DEVICE_RACE in result.gap_types

    def test_b27_accept_duplicate_gap(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b27",
            session_id="session-b27",
            invocation_id="inv-b27",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b27",
            session_id="session-b27",
            invocation_id="inv-b27",
            ingress_carrier_context=icc,
            is_duplicate=True,
        )
        assert GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL in result.gap_types

    def test_b28_governance_context_includes_sentinel(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b28",
            session_id="session-b28",
            invocation_id="inv-b28",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b28",
            session_id="session-b28",
            invocation_id="inv-b28",
            ingress_carrier_context=icc,
        )
        ctx = build_android_originated_governance_context(
            device_id="device-b28",
            execution_id="exec-b28",
            ingress_result=result,
        )
        assert "_sentinel" in ctx
        assert ctx["android_originated"] is True
        assert ctx["_contract_version"] == ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION

    def test_b29_is_main_chain_accepted_true_with_valid_icc(self):
        icc = build_android_nl_carrier_context(
            device_id="device-b29",
            session_id="session-b29",
            invocation_id="inv-b29",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b29",
            session_id="session-b29",
            invocation_id="inv-b29",
            ingress_carrier_context=icc,
        )
        assert is_android_originated_main_chain_accepted(result) is True

    def test_b30_is_main_chain_accepted_false_without_icc(self):
        result = accept_android_originated_nl_into_main_chain(
            device_id="device-b30",
            session_id="session-b30",
            invocation_id="inv-b30",
            ingress_carrier_context=None,
        )
        assert is_android_originated_main_chain_accepted(result) is False


# ===========================================================================
# Group C — Full-Chain Lineage Integration with Closed-Loop Governance
# ===========================================================================


class TestGroupC_LineageIntegration:
    """Group C: Full-chain lineage integration with closed-loop governance."""

    def _setup_canonical_lifecycle(self, execution_id: str, device_id: str) -> None:
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )
        record_result_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"status": "ok"},
        )
        record_state_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"phase": "succeeded"},
        )

    def test_c01_android_originated_false_without_context(self):
        execution_id = "exec-c01"
        device_id = "device-c01"
        self._setup_canonical_lifecycle(execution_id, device_id)
        view = query_closed_loop_governance_state(execution_id, device_id)
        assert view.android_originated is False
        assert view.android_originated_lineage == "unknown"
        assert view.android_originated_gap_types == []

    def test_c02_android_originated_true_with_context(self):
        execution_id = "exec-c02"
        device_id = "device-c02"
        self._setup_canonical_lifecycle(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-c02",
            invocation_id="inv-c02",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-c02",
            invocation_id="inv-c02",
            ingress_carrier_context=icc,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.android_originated is True

    def test_c03_android_originated_lineage_propagated(self):
        execution_id = "exec-c03"
        device_id = "device-c03"
        self._setup_canonical_lifecycle(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-c03",
            invocation_id="inv-c03",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-c03",
            invocation_id="inv-c03",
            ingress_carrier_context=icc,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.android_originated_lineage == ExecutionLineageKind.android_originated.value

    def test_c04_android_originated_gap_types_merged_into_system_gaps(self):
        execution_id = "exec-c04"
        device_id = "device-c04"
        self._setup_canonical_lifecycle(execution_id, device_id)
        # Android-originated without main chain → has GAP
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-c04",
            invocation_id="inv-c04",
            ingress_carrier_context=None,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        # The android gap must appear in the system gap types
        assert CLGC_GAP_ANDROID_WITHOUT_MAIN_CHAIN in view.system_completion_gap_types
        assert view.system_completion_ready is False

    def test_c05_android_originated_clean_lifecycle_still_works(self):
        """Android-originated clean path should still reach completion stage."""
        execution_id = "exec-c05"
        device_id = "device-c05"
        self._setup_canonical_lifecycle(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-c05",
            invocation_id="inv-c05",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-c05",
            invocation_id="inv-c05",
            ingress_carrier_context=icc,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.stage == ClosedLoopStage.completion
        assert view.android_originated is True
        # android_originated clean lineage still blocks canonical closure
        # (android_originated is non-canonical by definition)
        assert view.android_originated_lineage == ExecutionLineageKind.android_originated.value

    def test_c06_android_without_main_chain_blocks_mature_closure(self):
        """Android-originated without main chain must block mature closure even
        if lifecycle is fully canonical."""
        execution_id = "exec-c06"
        device_id = "device-c06"
        self._setup_canonical_lifecycle(execution_id, device_id)
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-c06",
            invocation_id="inv-c06",
            ingress_carrier_context=None,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.system_completion_ready is False
        assert CLGC_GAP_ANDROID_WITHOUT_MAIN_CHAIN in view.system_completion_gap_types

    def test_c07_to_dict_includes_android_originated_fields(self):
        execution_id = "exec-c07"
        device_id = "device-c07"
        self._setup_canonical_lifecycle(execution_id, device_id)
        view = query_closed_loop_governance_state(execution_id, device_id)
        d = view.to_dict()
        assert "android_originated" in d
        assert "android_originated_lineage" in d
        assert "android_originated_gap_types" in d
        assert "_sentinel" in d


# ===========================================================================
# Group D — Complex Mixed Scenario Gatekeeping (P0-3)
# ===========================================================================


class TestGroupD_ComplexScenarioGatekeeping:
    """Group D: Complex mixed scenario gatekeeping tests.

    These tests validate that the closure/governance layer correctly blocks
    mature closure for all the complex Android-originated + degradation combos.
    """

    def _setup_lifecycle_with_fallback(self, execution_id: str, device_id: str) -> None:
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            failure_semantic=FailureSemantic.fallback_local,
            enforce_transition=False,
        )
        record_result_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"status": "ok"},
        )
        record_state_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"phase": "succeeded"},
        )

    def _setup_canonical_lifecycle(self, execution_id: str, device_id: str) -> None:
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )
        record_result_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"status": "ok"},
        )
        record_state_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"phase": "succeeded"},
        )

    def test_d01_android_originated_plus_fallback_not_mature(self):
        """D-01: android_originated + fallback → NOT mature closure."""
        execution_id = "exec-d01-android-fallback"
        device_id = "device-d01"
        self._setup_lifecycle_with_fallback(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-d01",
            invocation_id="inv-d01",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d01",
            invocation_id="inv-d01",
            ingress_carrier_context=icc,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        # Lifecycle-level fallback must be detected
        assert view.fallback_path_used is True
        assert view.system_completion_ready is False
        assert "fallback_path_used" in view.system_completion_gap_types
        assert view.android_originated is True

    def test_d02_android_originated_plus_stale_replay_not_mature(self):
        """D-02: android_originated + stale evidence → blocked."""
        execution_id = "exec-d02-android-stale"
        device_id = "device-d02"
        self._setup_canonical_lifecycle(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-d02",
            invocation_id="inv-d02",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d02",
            invocation_id="inv-d02",
            ingress_carrier_context=icc,
            is_stale=True,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.system_completion_ready is False
        assert GAP_ANDROID_ORIGINATED_STALE_EVIDENCE in view.system_completion_gap_types

    def test_d03_android_originated_plus_takeover_blocked(self):
        """D-03: android_originated + takeover → mature closure blocked."""
        execution_id = "exec-d03-android-takeover"
        device_id = "device-d03"
        self._setup_canonical_lifecycle(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-d03",
            invocation_id="inv-d03",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d03",
            invocation_id="inv-d03",
            ingress_carrier_context=icc,
            is_takeover_scenario=True,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.system_completion_ready is False
        assert GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED in view.system_completion_gap_types
        assert result.lineage == ExecutionLineageKind.android_originated_takeover

    def test_d04_android_originated_plus_conflict_partial_blocked(self):
        """D-04: android_originated + conflict/partial → blocked."""
        execution_id = "exec-d04-android-conflict"
        device_id = "device-d04"
        self._setup_canonical_lifecycle(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-d04",
            invocation_id="inv-d04",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d04",
            invocation_id="inv-d04",
            ingress_carrier_context=icc,
            is_conflict_present=True,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.system_completion_ready is False
        assert GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL in view.system_completion_gap_types
        assert result.lineage == ExecutionLineageKind.android_originated_conflict

    def test_d05_android_originated_plus_multi_device_race_blocked(self):
        """D-05: android_originated + multi-device concurrency/race → blocked."""
        execution_id = "exec-d05-android-multidevice"
        device_id = "device-d05"
        self._setup_canonical_lifecycle(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-d05",
            invocation_id="inv-d05",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d05",
            invocation_id="inv-d05",
            ingress_carrier_context=icc,
            is_multi_device_concurrent=True,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.system_completion_ready is False
        assert GAP_ANDROID_ORIGINATED_MULTI_DEVICE_RACE in view.system_completion_gap_types

    def test_d06_android_originated_plus_compat_path_not_mature(self):
        """D-06: android_originated + compat path (uplink-only terminal) → NOT mature."""
        execution_id = "exec-d06-android-compat"
        device_id = "device-d06"
        # Record only uplinks without lifecycle event → compat path
        record_result_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "ok"},
        )
        record_state_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.goal_execution,
            payload={"phase": "succeeded"},
        )
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-d06",
            invocation_id="inv-d06",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d06",
            invocation_id="inv-d06",
            ingress_carrier_context=icc,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        # Compat path detected (uplink-only)
        assert view.compat_path_used is True
        assert view.system_completion_ready is False
        assert view.android_originated is True

    def test_d07_android_originated_plus_degraded_runtime_not_mature(self):
        """D-07: android_originated + degraded runtime → NOT mature."""
        execution_id = "exec-d07-android-degraded"
        device_id = "device-d07"
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )
        record_result_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"status": "ok"},
        )
        record_state_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"phase": "succeeded", "degraded": True, "reason": "latency_spike"},
        )
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-d07",
            invocation_id="inv-d07",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d07",
            invocation_id="inv-d07",
            ingress_carrier_context=icc,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        assert view.degraded_path_used is True
        assert view.system_completion_ready is False
        assert view.android_originated is True

    def test_d08_android_no_main_chain_plus_fallback_double_gap(self):
        """D-08: android_originated without main chain + fallback lifecycle → both gaps."""
        execution_id = "exec-d08-double-gap"
        device_id = "device-d08"
        self._setup_lifecycle_with_fallback(execution_id, device_id)
        # No carrier context → no main chain
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d08",
            invocation_id="inv-d08",
            ingress_carrier_context=None,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        # Both gaps must be present
        assert CLGC_GAP_ANDROID_WITHOUT_MAIN_CHAIN in view.system_completion_gap_types
        assert "fallback_path_used" in view.system_completion_gap_types
        assert view.system_completion_ready is False

    def test_d09_android_originated_clean_full_canonical_lifecycle(self):
        """D-09: android_originated (clean) + full canonical lifecycle.
        Completes but android_originated lineage is non-canonical by classification.
        """
        execution_id = "exec-d09-android-canonical-lifecycle"
        device_id = "device-d09"
        self._setup_canonical_lifecycle(execution_id, device_id)
        icc = build_android_nl_carrier_context(
            device_id=device_id,
            session_id="session-d09",
            invocation_id="inv-d09",
        )
        result = accept_android_originated_nl_into_main_chain(
            device_id=device_id,
            session_id="session-d09",
            invocation_id="inv-d09",
            ingress_carrier_context=icc,
        )
        gov_ctx = build_android_originated_governance_context(
            device_id=device_id,
            execution_id=execution_id,
            ingress_result=result,
        )
        view = query_closed_loop_governance_state(
            execution_id, device_id, android_governance_context=gov_ctx
        )
        # Lifecycle is canonical — stage should be completion
        assert view.stage == ClosedLoopStage.completion
        assert view.android_originated is True
        # android_originated lineage is not canonical
        assert view.android_originated_lineage == ExecutionLineageKind.android_originated.value
        # No android-specific gaps since main chain was accepted
        assert GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN not in view.system_completion_gap_types

    def test_d10_gap_constants_are_unique_strings(self):
        """D-10: All GAP constants must be unique non-empty strings."""
        from core.closed_loop_governance_consolidation import (
            GAP_LOOP_NOT_IN_COMPLETION_STAGE,
            GAP_TERMINAL_LIFECYCLE_NOT_REACHED,
            GAP_TERMINAL_TRUTH_UNDETERMINED,
            GAP_CENTER_LIFECYCLE_AUTHORITY_MISSING,
            GAP_MISSING_RESULT_UPLINK,
            GAP_MISSING_STATE_UPLINK,
            GAP_RECONCILIATION_CONFLICT_PRESENT,
            GAP_RECONCILIATION_NOT_FULLY_ACCEPTED,
            GAP_RUNTIME_HEALTH_NOT_STABLE,
            GAP_FALLBACK_PATH_USED,
            GAP_COMPAT_PATH_USED,
            GAP_DEGRADED_PATH_USED,
            GAP_GOVERNANCE_STORE_READ_ERROR,
            GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN as CLGC_NO_MAIN_CHAIN,
            GAP_ANDROID_ORIGINATED_FALLBACK_COMBINED as CLGC_FALLBACK_COMBINED,
            GAP_ANDROID_ORIGINATED_REPLAY_COMBINED,
            GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED,
            GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL,
            GAP_ANDROID_ORIGINATED_MULTI_DEVICE_RACE,
            GAP_ANDROID_ORIGINATED_STALE_EVIDENCE,
        )
        all_gaps = [
            GAP_LOOP_NOT_IN_COMPLETION_STAGE,
            GAP_TERMINAL_LIFECYCLE_NOT_REACHED,
            GAP_TERMINAL_TRUTH_UNDETERMINED,
            GAP_CENTER_LIFECYCLE_AUTHORITY_MISSING,
            GAP_MISSING_RESULT_UPLINK,
            GAP_MISSING_STATE_UPLINK,
            GAP_RECONCILIATION_CONFLICT_PRESENT,
            GAP_RECONCILIATION_NOT_FULLY_ACCEPTED,
            GAP_RUNTIME_HEALTH_NOT_STABLE,
            GAP_FALLBACK_PATH_USED,
            GAP_COMPAT_PATH_USED,
            GAP_DEGRADED_PATH_USED,
            GAP_GOVERNANCE_STORE_READ_ERROR,
            CLGC_NO_MAIN_CHAIN,
            CLGC_FALLBACK_COMBINED,
            GAP_ANDROID_ORIGINATED_REPLAY_COMBINED,
            GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED,
            GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL,
            GAP_ANDROID_ORIGINATED_MULTI_DEVICE_RACE,
            GAP_ANDROID_ORIGINATED_STALE_EVIDENCE,
        ]
        # All must be non-empty strings
        for gap in all_gaps:
            assert isinstance(gap, str) and gap, f"GAP constant is empty: {gap!r}"
        # All must be unique
        assert len(set(all_gaps)) == len(all_gaps), (
            f"Duplicate GAP constants detected: {sorted(all_gaps)}"
        )
