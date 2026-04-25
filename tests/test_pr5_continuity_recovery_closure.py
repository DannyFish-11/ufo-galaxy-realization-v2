#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_continuity_recovery_closure.py
===============================================
PR-5: ContinuityRecoveryClosure — Recovery Decision Matrix and end-to-end
closure validator — test suite.

Coverage
--------
A  — Module importable; authority sentinel and PR-5 sentinel present.
B  — All 7 policy sentinels are non-empty strings with expected keywords.
C  — RecoveryScenario enum has all 9 required values.
D  — RecoveryClosureVerdict enum has all 4 required values.
E  — RecoveryPathEntry dataclass has required fields; to_dict() works.
F  — RecoveryPathEntry to_json() returns valid JSON.
G  — RecoveryClosureOutcome dataclass has required fields; to_dict() works.
H  — RecoveryClosureOutcome.from_dict() round-trips correctly.
I  — RecoveryClosureOutcome to_json() returns valid JSON.
J  — RecoveryClosureReport dataclass has required fields; to_dict() works.
K  — RecoveryClosureReport to_json() returns valid JSON.
L  — RECOVERY_DECISION_MATRIX has all 9 scenario entries.
M  — RECOVERY_DECISION_MATRIX: every entry has non-empty owning_coordinator.
N  — RECOVERY_DECISION_MATRIX: every entry has non-empty canonical_decision.
O  — RECOVERY_DECISION_MATRIX: every entry has non-empty policy_reference.
P  — RECOVERY_DECISION_MATRIX: v2_process_restart entry uses RuntimeRestartRecoveryCoordinator.
Q  — RECOVERY_DECISION_MATRIX: android_transport_reconnect entry uses FlowContinuityCoordinator.
R  — RECOVERY_DECISION_MATRIX: delegated_flow_checkpoint_replay entry uses DelegatedFlowRecoveryCoordinator.
S  — RECOVERY_DECISION_MATRIX: offline_queue_replay_on_reconnect entry uses OfflineQueueRecoveryBoundary.
T  — ContinuityRecoveryClosure instantiates with default matrix.
U  — ContinuityRecoveryClosure instantiates with custom matrix.
V  — validate_all returns a RecoveryClosureReport.
W  — validate_all: scenarios_total equals len(RECOVERY_DECISION_MATRIX).
X  — validate_all: no scenarios_failed in normal validation run.
Y  — validate_all: report contains pr5_sentinel.
Z  — validate_all: outcomes list has same length as matrix.
AA — validate_all: all outcome scenarios are in RecoveryScenario.
AB — validate_all: policy_sentinels dict has expected keys.
AC — validate_all: report is JSON-serialisable.
AD — Deferred entry: verdict is deferred; not listed in failed.
AE — Deferred entry: listed in deferred_items.
AF — all_closed=True when no failed and no deferred scenarios.
AG — all_closed=False when deferred scenarios exist.
AH — get_recovery_closure_report convenience function returns report.
AI — reset_recovery_closure resets singleton.
AJ — run_recovery_closure_validation convenience function returns report.
AK — RecoveryScenario.from_string: known value → member.
AL — RecoveryScenario.from_string: unknown value → safe default.
AM — RecoveryClosureVerdict.from_string: known value → member.
AN — RecoveryClosureVerdict.from_string: unknown value → advisory.
AO — RecoveryClosureOutcome.outcome_id is auto-generated and unique.
AP — RecoveryClosureReport.report_id is auto-generated and unique.
AQ — validate_all with offline_queue_replay scenario: exercised without exception.
AR — validate_all with v2_process_restart scenario: exercised without exception.
AS — validate_all: advisory outcomes do not set all_closed=False (only failed does).
AT — RecoveryPathEntry deferred=True: validate_all sets it as deferred not advisory.
"""

from __future__ import annotations

import json
import uuid
from typing import List

import pytest


# ---------------------------------------------------------------------------
# A — Module importable; sentinels present
# ---------------------------------------------------------------------------


class TestModuleSentinels:
    def test_module_is_importable(self):
        import core.continuity_recovery_closure  # noqa: F401

    def test_authority_sentinel_is_non_empty_string(self):
        from core.continuity_recovery_closure import (
            CONTINUITY_RECOVERY_CLOSURE_AUTHORITY,
        )
        assert isinstance(CONTINUITY_RECOVERY_CLOSURE_AUTHORITY, str)
        assert len(CONTINUITY_RECOVERY_CLOSURE_AUTHORITY) > 0
        assert "ContinuityRecoveryClosure" in CONTINUITY_RECOVERY_CLOSURE_AUTHORITY
        assert "PR-5" in CONTINUITY_RECOVERY_CLOSURE_AUTHORITY

    def test_pr5_sentinel_is_non_empty_string(self):
        from core.continuity_recovery_closure import (
            CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL,
        )
        assert isinstance(CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL, str)
        assert "PR-5" in CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL
        assert "package=5" in CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL


# ---------------------------------------------------------------------------
# B — All 7 policy sentinels are non-empty strings with expected keywords
# ---------------------------------------------------------------------------


class TestPolicySentinels:
    def test_recovery_decision_matrix_is_authoritative_policy(self):
        from core.continuity_recovery_closure import (
            RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY,
        )
        assert isinstance(RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY, str)
        assert "RECOVERY_DECISION_MATRIX" in RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY

    def test_recovery_path_entries_must_be_exercised_policy(self):
        from core.continuity_recovery_closure import (
            RECOVERY_PATH_ENTRIES_MUST_BE_EXERCISED_POLICY,
        )
        assert isinstance(RECOVERY_PATH_ENTRIES_MUST_BE_EXERCISED_POLICY, str)
        assert "RecoveryPathEntry" in RECOVERY_PATH_ENTRIES_MUST_BE_EXERCISED_POLICY

    def test_in_flight_delegated_work_recovery_is_bounded_policy(self):
        from core.continuity_recovery_closure import (
            IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY,
        )
        assert isinstance(IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY, str)
        assert "DelegatedFlowRecoveryCoordinator" in IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY

    def test_canonical_state_reconstruction_is_deterministic_policy(self):
        from core.continuity_recovery_closure import (
            CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_POLICY,
        )
        assert isinstance(CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_POLICY, str)
        assert "deterministic" in CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_POLICY.lower()

    def test_stale_replay_suppression_precedes_state_mutation_policy(self):
        from core.continuity_recovery_closure import (
            STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY,
        )
        assert isinstance(STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY, str)
        assert "suppression" in STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY.lower()

    def test_offline_queue_replay_requires_bounded_authority_policy(self):
        from core.continuity_recovery_closure import (
            OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY,
        )
        assert isinstance(OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY, str)
        assert "bounded" in OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY.lower()

    def test_recovery_closure_deferred_items_are_documented_policy(self):
        from core.continuity_recovery_closure import (
            RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_POLICY,
        )
        assert isinstance(RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_POLICY, str)
        assert "deferred" in RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_POLICY.lower()


# ---------------------------------------------------------------------------
# C — RecoveryScenario enum has all 9 required values
# ---------------------------------------------------------------------------


class TestRecoveryScenarioEnum:
    def test_all_required_values_present(self):
        from core.continuity_recovery_closure import RecoveryScenario
        required = {
            "v2_process_restart",
            "android_transport_reconnect",
            "android_process_recreation",
            "delegated_flow_checkpoint_replay",
            "delegated_flow_partial_result",
            "duplicate_signal_after_reconnect",
            "stale_identity_signal",
            "partial_result_after_terminal",
            "offline_queue_replay_on_reconnect",
        }
        actual = {m.value for m in RecoveryScenario}
        assert required.issubset(actual)


# ---------------------------------------------------------------------------
# D — RecoveryClosureVerdict enum has all 4 required values
# ---------------------------------------------------------------------------


class TestRecoveryClosureVerdictEnum:
    def test_all_required_values_present(self):
        from core.continuity_recovery_closure import RecoveryClosureVerdict
        required = {"passed", "advisory", "deferred", "failed"}
        actual = {m.value for m in RecoveryClosureVerdict}
        assert required.issubset(actual)


# ---------------------------------------------------------------------------
# E — RecoveryPathEntry dataclass has required fields; to_dict() works
# ---------------------------------------------------------------------------


class TestRecoveryPathEntry:
    def test_construction_and_to_dict(self):
        from core.continuity_recovery_closure import RecoveryPathEntry, RecoveryScenario
        entry = RecoveryPathEntry(
            scenario=RecoveryScenario.v2_process_restart,
            owning_coordinator="TestCoordinator",
            canonical_decision="run_recovery",
            policy_reference="TEST_POLICY",
        )
        d = entry.to_dict()
        assert d["scenario"] == "v2_process_restart"
        assert d["owning_coordinator"] == "TestCoordinator"
        assert d["canonical_decision"] == "run_recovery"
        assert d["policy_reference"] == "TEST_POLICY"
        assert d["deferred"] is False

    def test_deferred_field(self):
        from core.continuity_recovery_closure import RecoveryPathEntry, RecoveryScenario
        entry = RecoveryPathEntry(
            scenario=RecoveryScenario.offline_queue_replay_on_reconnect,
            owning_coordinator="TestCoordinator",
            canonical_decision="ordered_replay",
            policy_reference="TEST_POLICY",
            deferred=True,
            notes="Not yet closed",
        )
        assert entry.deferred is True
        d = entry.to_dict()
        assert d["deferred"] is True
        assert d["notes"] == "Not yet closed"


# ---------------------------------------------------------------------------
# F — RecoveryPathEntry to_json() returns valid JSON
# ---------------------------------------------------------------------------


class TestRecoveryPathEntryJson:
    def test_to_json_is_valid(self):
        from core.continuity_recovery_closure import RecoveryPathEntry, RecoveryScenario
        entry = RecoveryPathEntry(
            scenario=RecoveryScenario.android_transport_reconnect,
            owning_coordinator="FlowContinuityCoordinator",
            canonical_decision="continuity_resume or new_attachment",
            policy_reference="CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY",
        )
        data = json.loads(entry.to_json())
        assert data["scenario"] == "android_transport_reconnect"


# ---------------------------------------------------------------------------
# G — RecoveryClosureOutcome dataclass has required fields; to_dict() works
# ---------------------------------------------------------------------------


class TestRecoveryClosureOutcome:
    def test_construction_and_to_dict(self):
        from core.continuity_recovery_closure import (
            RecoveryClosureOutcome,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        outcome = RecoveryClosureOutcome(
            scenario=RecoveryScenario.v2_process_restart,
            verdict=RecoveryClosureVerdict.passed,
            observed_decision="run_recovery",
            expected_decision="run_recovery",
        )
        d = outcome.to_dict()
        assert d["scenario"] == "v2_process_restart"
        assert d["verdict"] == "passed"
        assert d["observed_decision"] == "run_recovery"
        assert "outcome_id" in d
        assert "validated_at" in d


# ---------------------------------------------------------------------------
# H — RecoveryClosureOutcome.from_dict() round-trips correctly
# ---------------------------------------------------------------------------


class TestRecoveryClosureOutcomeRoundTrip:
    def test_round_trip(self):
        from core.continuity_recovery_closure import (
            RecoveryClosureOutcome,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        original = RecoveryClosureOutcome(
            scenario=RecoveryScenario.stale_identity_signal,
            verdict=RecoveryClosureVerdict.passed,
            observed_decision="reject_stale_identity",
            expected_decision="reject_stale_identity",
            evidence={"artifact_id": "abc123"},
            notes="Test note",
        )
        restored = RecoveryClosureOutcome.from_dict(original.to_dict())
        assert restored.scenario == original.scenario
        assert restored.verdict == original.verdict
        assert restored.observed_decision == original.observed_decision
        assert restored.evidence == original.evidence
        assert restored.outcome_id == original.outcome_id


# ---------------------------------------------------------------------------
# I — RecoveryClosureOutcome to_json() returns valid JSON
# ---------------------------------------------------------------------------


class TestRecoveryClosureOutcomeJson:
    def test_to_json_is_valid(self):
        from core.continuity_recovery_closure import (
            RecoveryClosureOutcome,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        outcome = RecoveryClosureOutcome(
            scenario=RecoveryScenario.duplicate_signal_after_reconnect,
            verdict=RecoveryClosureVerdict.passed,
        )
        data = json.loads(outcome.to_json())
        assert data["scenario"] == "duplicate_signal_after_reconnect"


# ---------------------------------------------------------------------------
# J — RecoveryClosureReport dataclass has required fields; to_dict() works
# ---------------------------------------------------------------------------


class TestRecoveryClosureReport:
    def test_construction_and_to_dict(self):
        from core.continuity_recovery_closure import RecoveryClosureReport
        report = RecoveryClosureReport(
            scenarios_total=5,
            scenarios_passed=4,
            scenarios_advisory=1,
        )
        d = report.to_dict()
        assert d["scenarios_total"] == 5
        assert d["scenarios_passed"] == 4
        assert d["scenarios_advisory"] == 1
        assert "report_id" in d
        assert "pr5_sentinel" in d
        assert "generated_at" in d
        assert "policy_sentinels" in d


# ---------------------------------------------------------------------------
# K — RecoveryClosureReport to_json() returns valid JSON
# ---------------------------------------------------------------------------


class TestRecoveryClosureReportJson:
    def test_to_json_is_valid(self):
        from core.continuity_recovery_closure import RecoveryClosureReport
        report = RecoveryClosureReport(scenarios_total=1)
        data = json.loads(report.to_json())
        assert data["scenarios_total"] == 1


# ---------------------------------------------------------------------------
# L — RECOVERY_DECISION_MATRIX has all 9 scenario entries
# ---------------------------------------------------------------------------


class TestRecoveryDecisionMatrix:
    def test_all_9_scenarios_present(self):
        from core.continuity_recovery_closure import (
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
        )
        matrix_scenarios = {e.scenario for e in RECOVERY_DECISION_MATRIX}
        required = set(RecoveryScenario)
        assert required.issubset(matrix_scenarios), (
            f"Missing scenarios: {required - matrix_scenarios}"
        )

    def test_length_is_9(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        assert len(RECOVERY_DECISION_MATRIX) == 9


# ---------------------------------------------------------------------------
# M, N, O — Matrix entries have non-empty coordinator/decision/policy
# ---------------------------------------------------------------------------


class TestMatrixEntryFields:
    def test_all_entries_have_owning_coordinator(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        for entry in RECOVERY_DECISION_MATRIX:
            assert entry.owning_coordinator, (
                f"Entry {entry.scenario.value} has empty owning_coordinator"
            )

    def test_all_entries_have_canonical_decision(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        for entry in RECOVERY_DECISION_MATRIX:
            assert entry.canonical_decision, (
                f"Entry {entry.scenario.value} has empty canonical_decision"
            )

    def test_all_entries_have_policy_reference(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        for entry in RECOVERY_DECISION_MATRIX:
            assert entry.policy_reference, (
                f"Entry {entry.scenario.value} has empty policy_reference"
            )


# ---------------------------------------------------------------------------
# P–S — Specific matrix entries reference correct coordinators
# ---------------------------------------------------------------------------


class TestMatrixEntryCoordinators:
    def _get_entry(self, scenario_value: str):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX, RecoveryScenario
        scenario = RecoveryScenario(scenario_value)
        for entry in RECOVERY_DECISION_MATRIX:
            if entry.scenario == scenario:
                return entry
        return None

    def test_v2_process_restart_uses_runtime_restart_recovery_coordinator(self):
        entry = self._get_entry("v2_process_restart")
        assert entry is not None
        assert "RuntimeRestartRecoveryCoordinator" in entry.owning_coordinator

    def test_android_transport_reconnect_uses_flow_continuity_coordinator(self):
        entry = self._get_entry("android_transport_reconnect")
        assert entry is not None
        assert "FlowContinuityCoordinator" in entry.owning_coordinator

    def test_delegated_flow_checkpoint_replay_uses_delegated_flow_recovery_coordinator(self):
        entry = self._get_entry("delegated_flow_checkpoint_replay")
        assert entry is not None
        assert "DelegatedFlowRecoveryCoordinator" in entry.owning_coordinator

    def test_offline_queue_replay_uses_offline_queue_recovery_boundary(self):
        entry = self._get_entry("offline_queue_replay_on_reconnect")
        assert entry is not None
        assert "OfflineQueueRecoveryBoundary" in entry.owning_coordinator


# ---------------------------------------------------------------------------
# T, U — ContinuityRecoveryClosure instantiation
# ---------------------------------------------------------------------------


class TestContinuityRecoveryClosureInstantiation:
    def test_instantiates_with_default_matrix(self):
        from core.continuity_recovery_closure import ContinuityRecoveryClosure
        c = ContinuityRecoveryClosure()
        assert c is not None

    def test_instantiates_with_custom_matrix(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RecoveryPathEntry,
            RecoveryScenario,
        )
        custom = [
            RecoveryPathEntry(
                scenario=RecoveryScenario.v2_process_restart,
                owning_coordinator="TestCoordinator",
                canonical_decision="run_recovery",
                policy_reference="TEST_POLICY",
            )
        ]
        c = ContinuityRecoveryClosure(matrix=custom)
        assert c is not None


# ---------------------------------------------------------------------------
# V–AC — validate_all behaviour
# ---------------------------------------------------------------------------


class TestValidateAll:
    def _fresh_closure(self):
        from core.continuity_recovery_closure import ContinuityRecoveryClosure
        return ContinuityRecoveryClosure()

    def test_returns_recovery_closure_report(self):
        from core.continuity_recovery_closure import RecoveryClosureReport
        report = self._fresh_closure().validate_all()
        assert isinstance(report, RecoveryClosureReport)

    def test_scenarios_total_equals_matrix_length(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        report = self._fresh_closure().validate_all()
        assert report.scenarios_total == len(RECOVERY_DECISION_MATRIX)

    def test_no_scenarios_failed_in_normal_run(self):
        report = self._fresh_closure().validate_all()
        assert report.scenarios_failed == 0

    def test_report_contains_pr5_sentinel(self):
        report = self._fresh_closure().validate_all()
        assert "PR-5" in report.pr5_sentinel

    def test_outcomes_length_matches_matrix(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        report = self._fresh_closure().validate_all()
        assert len(report.outcomes) == len(RECOVERY_DECISION_MATRIX)

    def test_all_outcome_scenarios_in_recovery_scenario_enum(self):
        from core.continuity_recovery_closure import RecoveryScenario
        report = self._fresh_closure().validate_all()
        valid_values = {s.value for s in RecoveryScenario}
        for outcome in report.outcomes:
            assert outcome.scenario.value in valid_values

    def test_policy_sentinels_dict_has_expected_keys(self):
        report = self._fresh_closure().validate_all()
        expected_keys = {
            "CONTINUITY_RECOVERY_CLOSURE_AUTHORITY",
            "RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY",
            "IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY",
        }
        for key in expected_keys:
            assert key in report.policy_sentinels

    def test_report_is_json_serialisable(self):
        report = self._fresh_closure().validate_all()
        serialised = json.loads(report.to_json())
        assert serialised["scenarios_total"] == report.scenarios_total


# ---------------------------------------------------------------------------
# AD–AG — Deferred entry handling
# ---------------------------------------------------------------------------


class TestDeferredEntries:
    def test_deferred_entry_verdict_is_deferred(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RecoveryPathEntry,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        matrix = [
            RecoveryPathEntry(
                scenario=RecoveryScenario.v2_process_restart,
                owning_coordinator="TestCoordinator",
                canonical_decision="run_recovery",
                policy_reference="TEST_POLICY",
                deferred=True,
                notes="Deferred for later PR",
            )
        ]
        c = ContinuityRecoveryClosure(matrix=matrix)
        report = c.validate_all()
        assert report.scenarios_deferred == 1
        assert report.scenarios_failed == 0
        assert report.outcomes[0].verdict == RecoveryClosureVerdict.deferred

    def test_deferred_entry_listed_in_deferred_items(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RecoveryPathEntry,
            RecoveryScenario,
        )
        matrix = [
            RecoveryPathEntry(
                scenario=RecoveryScenario.v2_process_restart,
                owning_coordinator="TestCoordinator",
                canonical_decision="run_recovery",
                policy_reference="TEST_POLICY",
                deferred=True,
                notes="Deferred for later PR",
            )
        ]
        c = ContinuityRecoveryClosure(matrix=matrix)
        report = c.validate_all()
        assert len(report.deferred_items) == 1
        assert "v2_process_restart" in report.deferred_items[0]

    def test_all_closed_false_when_deferred_scenarios_exist(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RecoveryPathEntry,
            RecoveryScenario,
        )
        matrix = [
            RecoveryPathEntry(
                scenario=RecoveryScenario.v2_process_restart,
                owning_coordinator="TestCoordinator",
                canonical_decision="run_recovery",
                policy_reference="TEST_POLICY",
                deferred=True,
            )
        ]
        c = ContinuityRecoveryClosure(matrix=matrix)
        report = c.validate_all()
        assert report.all_closed is False

    def test_all_closed_true_when_no_failed_and_no_deferred(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RecoveryPathEntry,
            RecoveryScenario,
        )
        matrix = [
            RecoveryPathEntry(
                scenario=RecoveryScenario.v2_process_restart,
                owning_coordinator="TestCoordinator",
                canonical_decision="run_recovery",
                policy_reference="TEST_POLICY",
                deferred=False,
            )
        ]
        c = ContinuityRecoveryClosure(matrix=matrix)
        report = c.validate_all()
        # With no deferred and no failed entries, all_closed should be True
        assert report.all_closed is True


# ---------------------------------------------------------------------------
# AH–AJ — Convenience functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    def test_get_recovery_closure_report_returns_report(self):
        from core.continuity_recovery_closure import (
            get_recovery_closure_report,
            RecoveryClosureReport,
        )
        report = get_recovery_closure_report()
        assert isinstance(report, RecoveryClosureReport)

    def test_reset_recovery_closure_resets_singleton(self):
        from core.continuity_recovery_closure import (
            get_recovery_closure,
            reset_recovery_closure,
        )
        a = get_recovery_closure()
        reset_recovery_closure()
        b = get_recovery_closure()
        assert a is not b

    def test_run_recovery_closure_validation_returns_report(self):
        from core.continuity_recovery_closure import (
            run_recovery_closure_validation,
            RecoveryClosureReport,
        )
        report = run_recovery_closure_validation()
        assert isinstance(report, RecoveryClosureReport)


# ---------------------------------------------------------------------------
# AK–AN — Enum from_string helpers
# ---------------------------------------------------------------------------


class TestEnumFromString:
    def test_recovery_scenario_from_string_known(self):
        from core.continuity_recovery_closure import RecoveryScenario
        s = RecoveryScenario.from_string("v2_process_restart")
        assert s == RecoveryScenario.v2_process_restart

    def test_recovery_scenario_from_string_unknown_returns_default(self):
        from core.continuity_recovery_closure import RecoveryScenario
        s = RecoveryScenario.from_string("unknown_scenario_xyz")
        assert s == RecoveryScenario.v2_process_restart  # safe default

    def test_recovery_closure_verdict_from_string_known(self):
        from core.continuity_recovery_closure import RecoveryClosureVerdict
        v = RecoveryClosureVerdict.from_string("failed")
        assert v == RecoveryClosureVerdict.failed

    def test_recovery_closure_verdict_from_string_unknown_returns_advisory(self):
        from core.continuity_recovery_closure import RecoveryClosureVerdict
        v = RecoveryClosureVerdict.from_string("unknown_xyz")
        assert v == RecoveryClosureVerdict.advisory


# ---------------------------------------------------------------------------
# AO–AP — Auto-generated IDs
# ---------------------------------------------------------------------------


class TestAutoGeneratedIds:
    def test_outcome_id_is_unique_per_instance(self):
        from core.continuity_recovery_closure import (
            RecoveryClosureOutcome,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        a = RecoveryClosureOutcome(
            scenario=RecoveryScenario.v2_process_restart,
            verdict=RecoveryClosureVerdict.passed,
        )
        b = RecoveryClosureOutcome(
            scenario=RecoveryScenario.v2_process_restart,
            verdict=RecoveryClosureVerdict.passed,
        )
        assert a.outcome_id != b.outcome_id

    def test_report_id_is_unique_per_instance(self):
        from core.continuity_recovery_closure import RecoveryClosureReport
        a = RecoveryClosureReport()
        b = RecoveryClosureReport()
        assert a.report_id != b.report_id


# ---------------------------------------------------------------------------
# AQ–AR — Key scenarios exercised without exception
# ---------------------------------------------------------------------------


class TestKeyScenarioExercised:
    def _run_single_scenario(self, scenario_value: str):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
        )
        scenario = RecoveryScenario(scenario_value)
        matrix = [e for e in RECOVERY_DECISION_MATRIX if e.scenario == scenario]
        c = ContinuityRecoveryClosure(matrix=matrix)
        return c.validate_all()

    def test_offline_queue_replay_exercised_without_exception(self):
        from core.continuity_recovery_closure import RecoveryClosureVerdict
        report = self._run_single_scenario("offline_queue_replay_on_reconnect")
        assert report.scenarios_total == 1
        assert report.scenarios_failed == 0

    def test_v2_process_restart_exercised_without_exception(self):
        report = self._run_single_scenario("v2_process_restart")
        assert report.scenarios_total == 1
        assert report.scenarios_failed == 0


# ---------------------------------------------------------------------------
# AS — Advisory outcomes do not set all_closed=False (only failed does)
# ---------------------------------------------------------------------------


class TestAdvisoryDoesNotBlockClosed:
    def test_advisory_does_not_set_all_closed_false(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RecoveryPathEntry,
            RecoveryScenario,
            RecoveryClosureVerdict,
            RecoveryClosureOutcome,
        )
        # Build a custom closure that always returns advisory
        class AdvisoryOnlyClosure(ContinuityRecoveryClosure):
            def _validate_entry(self, entry):
                return RecoveryClosureOutcome(
                    scenario=entry.scenario,
                    verdict=RecoveryClosureVerdict.advisory,
                    observed_decision="advisory_test",
                    expected_decision=entry.canonical_decision,
                )

        matrix = [
            RecoveryPathEntry(
                scenario=RecoveryScenario.v2_process_restart,
                owning_coordinator="TestCoordinator",
                canonical_decision="run_recovery",
                policy_reference="TEST_POLICY",
            )
        ]
        c = AdvisoryOnlyClosure(matrix=matrix)
        report = c.validate_all()
        # advisory should not prevent all_closed=True
        assert report.scenarios_failed == 0
        assert report.scenarios_deferred == 0
        assert report.all_closed is True


# ---------------------------------------------------------------------------
# AT — RecoveryPathEntry deferred=True: validate_all classifies as deferred
# ---------------------------------------------------------------------------


class TestDeferredVsAdvisory:
    def test_deferred_entry_is_not_advisory(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RecoveryPathEntry,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        matrix = [
            RecoveryPathEntry(
                scenario=RecoveryScenario.offline_queue_replay_on_reconnect,
                owning_coordinator="OfflineQueueRecoveryBoundary",
                canonical_decision="ordered_replay_with_dedup",
                policy_reference="OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY",
                deferred=True,
                notes="Explicitly deferred",
            )
        ]
        c = ContinuityRecoveryClosure(matrix=matrix)
        report = c.validate_all()
        outcome = report.outcomes[0]
        assert outcome.verdict == RecoveryClosureVerdict.deferred
        assert report.scenarios_advisory == 0
        assert report.scenarios_deferred == 1
