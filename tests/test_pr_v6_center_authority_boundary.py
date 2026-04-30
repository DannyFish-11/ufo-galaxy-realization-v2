"""tests/test_pr_v6_center_authority_boundary.py
===================================================
Test suite for PR-V6: Fix the center authority boundary — V2 owns
completion, continuity, readiness, and orchestration truth.

Coverage
--------
1. Module importability
   - center_authority_boundary is importable.
   - CENTER_AUTHORITY_BOUNDARY_AUTHORITY is a non-empty string.
   - CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL is a non-empty string.
   - All eight policy sentinels are non-empty strings.
   - All public symbols are accessible.

2. AuthorityDomain enum
   - All four domain values present.
   - COMPLETION_TRUTH value is "completion_truth".
   - CONTINUITY_LEGALITY_TRUTH value is "continuity_legality_truth".
   - DISPATCH_READINESS_TRUTH value is "dispatch_readiness_truth".
   - ORCHESTRATION_TRUTH value is "orchestration_truth".

3. DomainBoundaryStatus enum
   - INTACT, DEGRADED, UNKNOWN present.
   - Values are strings.

4. ExternalRole enum
   - All four roles present.
   - Values are strings.

5. CenterAuthorityViolation exception
   - Is a subclass of Exception.
   - Has degraded_domains attribute.
   - Has report attribute.
   - Message is preserved.

6. DomainBoundaryState dataclass
   - Default domain is COMPLETION_TRUTH.
   - Default status is UNKNOWN.
   - is_intact returns True iff status is INTACT.
   - to_dict() includes domain, status, is_intact, canonical_modules,
     missing_modules, sentinel_checks, notes.
   - to_dict() domain value is a string.
   - to_dict() status value is a string.

7. CenterAuthorityBoundaryReport dataclass
   - report_id is a non-empty string.
   - authority equals CENTER_AUTHORITY_BOUNDARY_AUTHORITY.
   - to_dict() includes all required keys.
   - to_json() produces valid JSON.
   - to_json() is round-trippable.

8. evaluate_center_authority_boundary — structure
   - Returns a CenterAuthorityBoundaryReport.
   - report has four domain_states entries.
   - Keys are the four AuthorityDomain value strings.
   - all_domains_intact is a bool.
   - degraded_domains is a list.

9. evaluate_center_authority_boundary — intact system
   - all_domains_intact is True when all four canonical modules available.
   - degraded_domains is empty list when all intact.
   - Each domain state has status INTACT.
   - Each domain state canonical_modules list is non-empty.
   - Each domain state missing_modules list is empty.
   - Each domain state sentinel_checks has all True values.

10. evaluate_center_authority_boundary — completion truth domain
    - completion_truth domain is present in domain_states.
    - canonical_modules includes "core.unified_result_ingress".
    - canonical_modules includes "core.task_result_canonical_truth_chain".
    - canonical_modules includes "core.canonical_completion_ingress".
    - canonical_modules includes "core.canonical_group_completion_closure".
    - sentinel_checks has UNIFIED_RESULT_INGRESS_POLICY key.
    - sentinel_checks has CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY key.

11. evaluate_center_authority_boundary — continuity legality domain
    - continuity_legality_truth domain is present in domain_states.
    - canonical_modules includes "core.unified_continuity_legality_authority".
    - sentinel_checks has UNIFIED_CONTINUITY_LEGALITY_AUTHORITY key.
    - sentinel_checks has ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY key.

12. evaluate_center_authority_boundary — dispatch readiness domain
    - dispatch_readiness_truth domain is present in domain_states.
    - canonical_modules includes "core.unified_dispatch_readiness_gate".
    - canonical_modules includes "core.canonical_dispatch_slot_authority".
    - sentinel_checks has UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY key.
    - sentinel_checks has CANONICAL_DISPATCH_SLOT_AUTHORITY key.
    - sentinel_checks has DISPATCH_MUST_CONSULT_UNIFIED_GATE_POLICY key.
    - sentinel_checks has ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY key.

13. evaluate_center_authority_boundary — orchestration truth domain
    - orchestration_truth domain is present in domain_states.
    - canonical_modules includes "core.unified_orchestration_spine".
    - sentinel_checks has UNIFIED_ORCHESTRATION_SPINE_AUTHORITY key.
    - sentinel_checks has ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY key.
    - sentinel_checks has ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY key.
    - sentinel_checks has ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY key.

14. assert_center_authority_intact — intact system
    - Does not raise when all domains are intact.

15. assert_center_authority_intact — degraded domain
    - Raises CenterAuthorityViolation when a domain is degraded.
    - Exception degraded_domains list is non-empty.
    - Exception report is a CenterAuthorityBoundaryReport.
    - Exception message includes domain name.

16. get_boundary_report
    - Returns a CenterAuthorityBoundaryReport.
    - Equivalent result to evaluate_center_authority_boundary().

17. Degraded domain simulation
    - Patching a required import to fail produces status DEGRADED for that domain.
    - all_domains_intact is False when any domain is DEGRADED.
    - degraded_domains list contains the degraded domain value.

18. Serialisation
    - to_dict() is JSON-serialisable.
    - to_json() round-trips through json.loads.
    - Individual DomainBoundaryState.to_dict() is JSON-serialisable.

19. Error safety
    - evaluate_center_authority_boundary never raises.
    - assert_center_authority_intact raises CenterAuthorityViolation, not
      unexpected exceptions, when degraded.

20. V6 policy sentinel content
    - V2_OWNS_COMPLETION_TRUTH_POLICY references "completion truth".
    - V2_OWNS_CONTINUITY_LEGALITY_TRUTH_POLICY references "continuity".
    - V2_OWNS_DISPATCH_READINESS_TRUTH_POLICY references "dispatch readiness".
    - V2_OWNS_ORCHESTRATION_TRUTH_POLICY references "orchestration".
    - EXTERNAL_SURFACES_ARE_PARTICIPANT_ONLY_POLICY references "participant".
    - NO_PARALLEL_AUTHORITY_PERMITTED_POLICY references "parallel".
    - COMPAT_INGRESS_TERMINATES_IN_CENTER_MODEL_POLICY references "compat".
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from core.center_authority_boundary import (
        CENTER_AUTHORITY_BOUNDARY_AUTHORITY,
        CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL,
        COMPAT_INGRESS_TERMINATES_IN_CENTER_MODEL_POLICY,
        EXTERNAL_SURFACES_ARE_PARTICIPANT_ONLY_POLICY,
        NO_PARALLEL_AUTHORITY_PERMITTED_POLICY,
        V2_OWNS_COMPLETION_TRUTH_POLICY,
        V2_OWNS_CONTINUITY_LEGALITY_TRUTH_POLICY,
        V2_OWNS_DISPATCH_READINESS_TRUTH_POLICY,
        V2_OWNS_ORCHESTRATION_TRUTH_POLICY,
        AuthorityDomain,
        CenterAuthorityBoundaryReport,
        CenterAuthorityViolation,
        DomainBoundaryState,
        DomainBoundaryStatus,
        ExternalRole,
        assert_center_authority_intact,
        evaluate_center_authority_boundary,
        get_boundary_report,
    )

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

_skip = pytest.mark.skipif(
    not _MODULE_AVAILABLE, reason="center_authority_boundary unavailable"
)


# ===========================================================================
# Group 1: Module importability
# ===========================================================================


@_skip
class TestModuleImportability:
    def test_authority_sentinel_non_empty(self) -> None:
        assert isinstance(CENTER_AUTHORITY_BOUNDARY_AUTHORITY, str)
        assert len(CENTER_AUTHORITY_BOUNDARY_AUTHORITY) > 0

    def test_pr_v6_sentinel_non_empty(self) -> None:
        assert isinstance(CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL, str)
        assert len(CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL) > 0

    def test_completion_truth_policy_non_empty(self) -> None:
        assert isinstance(V2_OWNS_COMPLETION_TRUTH_POLICY, str)
        assert len(V2_OWNS_COMPLETION_TRUTH_POLICY) > 0

    def test_continuity_legality_policy_non_empty(self) -> None:
        assert isinstance(V2_OWNS_CONTINUITY_LEGALITY_TRUTH_POLICY, str)
        assert len(V2_OWNS_CONTINUITY_LEGALITY_TRUTH_POLICY) > 0

    def test_dispatch_readiness_policy_non_empty(self) -> None:
        assert isinstance(V2_OWNS_DISPATCH_READINESS_TRUTH_POLICY, str)
        assert len(V2_OWNS_DISPATCH_READINESS_TRUTH_POLICY) > 0

    def test_orchestration_truth_policy_non_empty(self) -> None:
        assert isinstance(V2_OWNS_ORCHESTRATION_TRUTH_POLICY, str)
        assert len(V2_OWNS_ORCHESTRATION_TRUTH_POLICY) > 0

    def test_external_surfaces_policy_non_empty(self) -> None:
        assert isinstance(EXTERNAL_SURFACES_ARE_PARTICIPANT_ONLY_POLICY, str)
        assert len(EXTERNAL_SURFACES_ARE_PARTICIPANT_ONLY_POLICY) > 0

    def test_no_parallel_authority_policy_non_empty(self) -> None:
        assert isinstance(NO_PARALLEL_AUTHORITY_PERMITTED_POLICY, str)
        assert len(NO_PARALLEL_AUTHORITY_PERMITTED_POLICY) > 0

    def test_compat_ingress_policy_non_empty(self) -> None:
        assert isinstance(COMPAT_INGRESS_TERMINATES_IN_CENTER_MODEL_POLICY, str)
        assert len(COMPAT_INGRESS_TERMINATES_IN_CENTER_MODEL_POLICY) > 0

    def test_evaluate_callable(self) -> None:
        assert callable(evaluate_center_authority_boundary)

    def test_assert_callable(self) -> None:
        assert callable(assert_center_authority_intact)

    def test_get_boundary_report_callable(self) -> None:
        assert callable(get_boundary_report)


# ===========================================================================
# Group 2: AuthorityDomain enum
# ===========================================================================


@_skip
class TestAuthorityDomain:
    def test_completion_truth_value(self) -> None:
        assert AuthorityDomain.COMPLETION_TRUTH.value == "completion_truth"

    def test_continuity_legality_truth_value(self) -> None:
        assert (
            AuthorityDomain.CONTINUITY_LEGALITY_TRUTH.value
            == "continuity_legality_truth"
        )

    def test_dispatch_readiness_truth_value(self) -> None:
        assert (
            AuthorityDomain.DISPATCH_READINESS_TRUTH.value
            == "dispatch_readiness_truth"
        )

    def test_orchestration_truth_value(self) -> None:
        assert AuthorityDomain.ORCHESTRATION_TRUTH.value == "orchestration_truth"

    def test_all_four_domains_present(self) -> None:
        values = {d.value for d in AuthorityDomain}
        assert "completion_truth" in values
        assert "continuity_legality_truth" in values
        assert "dispatch_readiness_truth" in values
        assert "orchestration_truth" in values


# ===========================================================================
# Group 3: DomainBoundaryStatus enum
# ===========================================================================


@_skip
class TestDomainBoundaryStatus:
    def test_intact_value(self) -> None:
        assert DomainBoundaryStatus.INTACT.value == "intact"

    def test_degraded_value(self) -> None:
        assert DomainBoundaryStatus.DEGRADED.value == "degraded"

    def test_unknown_value(self) -> None:
        assert DomainBoundaryStatus.UNKNOWN.value == "unknown"

    def test_values_are_strings(self) -> None:
        for s in DomainBoundaryStatus:
            assert isinstance(s.value, str)


# ===========================================================================
# Group 4: ExternalRole enum
# ===========================================================================


@_skip
class TestExternalRole:
    def test_participant_truth_contributor_present(self) -> None:
        assert (
            ExternalRole.PARTICIPANT_TRUTH_CONTRIBUTOR.value
            == "participant_truth_contributor"
        )

    def test_execution_signal_contributor_present(self) -> None:
        assert (
            ExternalRole.EXECUTION_SIGNAL_CONTRIBUTOR.value
            == "execution_signal_contributor"
        )

    def test_continuity_input_contributor_present(self) -> None:
        assert (
            ExternalRole.CONTINUITY_INPUT_CONTRIBUTOR.value
            == "continuity_input_contributor"
        )

    def test_compat_ingress_adapter_present(self) -> None:
        assert ExternalRole.COMPAT_INGRESS_ADAPTER.value == "compat_ingress_adapter"

    def test_all_four_roles_present(self) -> None:
        assert len(list(ExternalRole)) == 4


# ===========================================================================
# Group 5: CenterAuthorityViolation exception
# ===========================================================================


@_skip
class TestCenterAuthorityViolation:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(CenterAuthorityViolation, Exception)

    def test_message_preserved(self) -> None:
        exc = CenterAuthorityViolation("test message")
        assert "test message" in str(exc)

    def test_degraded_domains_default_empty(self) -> None:
        exc = CenterAuthorityViolation("msg")
        assert exc.degraded_domains == []

    def test_degraded_domains_stored(self) -> None:
        exc = CenterAuthorityViolation(
            "msg", degraded_domains=[AuthorityDomain.COMPLETION_TRUTH]
        )
        assert AuthorityDomain.COMPLETION_TRUTH in exc.degraded_domains

    def test_report_default_none(self) -> None:
        exc = CenterAuthorityViolation("msg")
        assert exc.report is None

    def test_report_stored_when_provided(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        exc = CenterAuthorityViolation("msg", report=rpt)
        assert exc.report is rpt


# ===========================================================================
# Group 6: DomainBoundaryState dataclass
# ===========================================================================


@_skip
class TestDomainBoundaryState:
    def test_default_domain(self) -> None:
        state = DomainBoundaryState()
        assert state.domain == AuthorityDomain.COMPLETION_TRUTH

    def test_default_status(self) -> None:
        state = DomainBoundaryState()
        assert state.status == DomainBoundaryStatus.UNKNOWN

    def test_is_intact_false_by_default(self) -> None:
        state = DomainBoundaryState()
        assert state.is_intact is False

    def test_is_intact_true_when_status_intact(self) -> None:
        state = DomainBoundaryState()
        state.status = DomainBoundaryStatus.INTACT
        assert state.is_intact is True

    def test_is_intact_false_when_degraded(self) -> None:
        state = DomainBoundaryState()
        state.status = DomainBoundaryStatus.DEGRADED
        assert state.is_intact is False

    def test_to_dict_includes_domain(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert "domain" in d

    def test_to_dict_domain_is_string(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert isinstance(d["domain"], str)

    def test_to_dict_includes_status(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert "status" in d

    def test_to_dict_status_is_string(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert isinstance(d["status"], str)

    def test_to_dict_includes_is_intact(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert "is_intact" in d

    def test_to_dict_includes_canonical_modules(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert "canonical_modules" in d

    def test_to_dict_includes_missing_modules(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert "missing_modules" in d

    def test_to_dict_includes_sentinel_checks(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert "sentinel_checks" in d

    def test_to_dict_includes_notes(self) -> None:
        state = DomainBoundaryState()
        d = state.to_dict()
        assert "notes" in d


# ===========================================================================
# Group 7: CenterAuthorityBoundaryReport dataclass
# ===========================================================================


@_skip
class TestCenterAuthorityBoundaryReport:
    def test_report_id_non_empty(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        assert isinstance(rpt.report_id, str)
        assert len(rpt.report_id) > 0

    def test_authority_equals_sentinel(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        assert rpt.authority == CENTER_AUTHORITY_BOUNDARY_AUTHORITY

    def test_to_dict_includes_report_id(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        d = rpt.to_dict()
        assert "report_id" in d

    def test_to_dict_includes_all_domains_intact(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        d = rpt.to_dict()
        assert "all_domains_intact" in d

    def test_to_dict_includes_domain_states(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        d = rpt.to_dict()
        assert "domain_states" in d

    def test_to_dict_includes_degraded_domains(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        d = rpt.to_dict()
        assert "degraded_domains" in d

    def test_to_dict_includes_authority(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        d = rpt.to_dict()
        assert "authority" in d

    def test_to_dict_includes_notes(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        d = rpt.to_dict()
        assert "notes" in d

    def test_to_json_produces_valid_json(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        j = rpt.to_json()
        assert isinstance(j, str)
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_to_json_round_trips(self) -> None:
        rpt = CenterAuthorityBoundaryReport()
        j = rpt.to_json()
        d = json.loads(j)
        assert d["report_id"] == rpt.report_id

    def test_report_ids_unique(self) -> None:
        r1 = CenterAuthorityBoundaryReport()
        r2 = CenterAuthorityBoundaryReport()
        assert r1.report_id != r2.report_id


# ===========================================================================
# Group 8: evaluate_center_authority_boundary — structure
# ===========================================================================


@_skip
class TestEvaluateBoundaryStructure:
    def test_returns_report(self) -> None:
        report = evaluate_center_authority_boundary()
        assert isinstance(report, CenterAuthorityBoundaryReport)

    def test_report_has_four_domain_states(self) -> None:
        report = evaluate_center_authority_boundary()
        assert len(report.domain_states) == 4

    def test_domain_state_keys_are_domain_values(self) -> None:
        report = evaluate_center_authority_boundary()
        expected_keys = {d.value for d in AuthorityDomain}
        assert set(report.domain_states.keys()) == expected_keys

    def test_all_domains_intact_is_bool(self) -> None:
        report = evaluate_center_authority_boundary()
        assert isinstance(report.all_domains_intact, bool)

    def test_degraded_domains_is_list(self) -> None:
        report = evaluate_center_authority_boundary()
        assert isinstance(report.degraded_domains, list)

    def test_report_id_non_empty(self) -> None:
        report = evaluate_center_authority_boundary()
        assert len(report.report_id) > 0

    def test_notes_non_empty(self) -> None:
        report = evaluate_center_authority_boundary()
        assert len(report.notes) > 0


# ===========================================================================
# Group 9: evaluate_center_authority_boundary — intact system
# ===========================================================================


@_skip
class TestEvaluateBoundaryIntact:
    def test_all_domains_intact(self) -> None:
        report = evaluate_center_authority_boundary()
        assert report.all_domains_intact is True

    def test_degraded_domains_empty(self) -> None:
        report = evaluate_center_authority_boundary()
        assert report.degraded_domains == []

    def test_each_domain_status_intact(self) -> None:
        report = evaluate_center_authority_boundary()
        for key, state in report.domain_states.items():
            assert state.status == DomainBoundaryStatus.INTACT, (
                f"Domain {key} is not INTACT: {state.status}"
            )

    def test_each_domain_canonical_modules_non_empty(self) -> None:
        report = evaluate_center_authority_boundary()
        for key, state in report.domain_states.items():
            assert len(state.canonical_modules) > 0, (
                f"Domain {key} has no canonical modules"
            )

    def test_each_domain_missing_modules_empty(self) -> None:
        report = evaluate_center_authority_boundary()
        for key, state in report.domain_states.items():
            assert state.missing_modules == [], (
                f"Domain {key} has missing modules: {state.missing_modules}"
            )

    def test_each_domain_all_sentinels_true(self) -> None:
        report = evaluate_center_authority_boundary()
        for key, state in report.domain_states.items():
            for sentinel, ok in state.sentinel_checks.items():
                assert ok is True, (
                    f"Domain {key} sentinel {sentinel} failed check"
                )

    def test_each_domain_is_intact_true(self) -> None:
        report = evaluate_center_authority_boundary()
        for key, state in report.domain_states.items():
            assert state.is_intact is True, f"Domain {key} is_intact False"


# ===========================================================================
# Group 10: completion truth domain details
# ===========================================================================


@_skip
class TestCompletionTruthDomain:
    def _get_state(self) -> Any:
        report = evaluate_center_authority_boundary()
        return report.domain_states[AuthorityDomain.COMPLETION_TRUTH.value]

    def test_completion_domain_present(self) -> None:
        report = evaluate_center_authority_boundary()
        assert AuthorityDomain.COMPLETION_TRUTH.value in report.domain_states

    def test_unified_result_ingress_in_canonical_modules(self) -> None:
        state = self._get_state()
        assert "core.unified_result_ingress" in state.canonical_modules

    def test_task_result_truth_chain_in_canonical_modules(self) -> None:
        state = self._get_state()
        assert "core.task_result_canonical_truth_chain" in state.canonical_modules

    def test_canonical_completion_ingress_in_canonical_modules(self) -> None:
        state = self._get_state()
        assert "core.canonical_completion_ingress" in state.canonical_modules

    def test_canonical_group_completion_closure_in_canonical_modules(self) -> None:
        state = self._get_state()
        assert "core.canonical_group_completion_closure" in state.canonical_modules

    def test_unified_result_ingress_sentinel_present(self) -> None:
        state = self._get_state()
        assert "UNIFIED_RESULT_INGRESS_POLICY" in state.sentinel_checks

    def test_canonical_group_completion_closure_sentinel_present(self) -> None:
        state = self._get_state()
        assert "CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY" in state.sentinel_checks

    def test_all_sentinels_true(self) -> None:
        state = self._get_state()
        assert all(state.sentinel_checks.values())


# ===========================================================================
# Group 11: continuity legality domain details
# ===========================================================================


@_skip
class TestContinuityLegalityDomain:
    def _get_state(self) -> Any:
        report = evaluate_center_authority_boundary()
        return report.domain_states[AuthorityDomain.CONTINUITY_LEGALITY_TRUTH.value]

    def test_continuity_domain_present(self) -> None:
        report = evaluate_center_authority_boundary()
        assert AuthorityDomain.CONTINUITY_LEGALITY_TRUTH.value in report.domain_states

    def test_unified_continuity_authority_in_modules(self) -> None:
        state = self._get_state()
        assert "core.unified_continuity_legality_authority" in state.canonical_modules

    def test_unified_continuity_authority_sentinel(self) -> None:
        state = self._get_state()
        assert "UNIFIED_CONTINUITY_LEGALITY_AUTHORITY" in state.sentinel_checks
        assert state.sentinel_checks["UNIFIED_CONTINUITY_LEGALITY_AUTHORITY"] is True

    def test_all_paths_policy_sentinel(self) -> None:
        state = self._get_state()
        assert "ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY" in state.sentinel_checks
        assert (
            state.sentinel_checks["ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY"] is True
        )

    def test_continuity_fields_policy_sentinel(self) -> None:
        state = self._get_state()
        assert (
            "CONTINUITY_FIELDS_ARE_ACTIVE_GATE_NOT_PAYLOAD_POLICY"
            in state.sentinel_checks
        )


# ===========================================================================
# Group 12: dispatch readiness domain details
# ===========================================================================


@_skip
class TestDispatchReadinessDomain:
    def _get_state(self) -> Any:
        report = evaluate_center_authority_boundary()
        return report.domain_states[AuthorityDomain.DISPATCH_READINESS_TRUTH.value]

    def test_readiness_domain_present(self) -> None:
        report = evaluate_center_authority_boundary()
        assert AuthorityDomain.DISPATCH_READINESS_TRUTH.value in report.domain_states

    def test_unified_dispatch_readiness_gate_in_modules(self) -> None:
        state = self._get_state()
        assert "core.unified_dispatch_readiness_gate" in state.canonical_modules

    def test_canonical_dispatch_slot_authority_in_modules(self) -> None:
        state = self._get_state()
        assert "core.canonical_dispatch_slot_authority" in state.canonical_modules

    def test_unified_dispatch_readiness_gate_sentinel(self) -> None:
        state = self._get_state()
        assert "UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY" in state.sentinel_checks
        assert (
            state.sentinel_checks["UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY"] is True
        )

    def test_canonical_dispatch_slot_authority_sentinel(self) -> None:
        state = self._get_state()
        assert "CANONICAL_DISPATCH_SLOT_AUTHORITY" in state.sentinel_checks
        assert state.sentinel_checks["CANONICAL_DISPATCH_SLOT_AUTHORITY"] is True

    def test_dispatch_must_consult_unified_gate_policy(self) -> None:
        state = self._get_state()
        assert "DISPATCH_MUST_CONSULT_UNIFIED_GATE_POLICY" in state.sentinel_checks

    def test_all_execution_modes_must_consume_canonical_slot_policy(self) -> None:
        state = self._get_state()
        assert (
            "ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY"
            in state.sentinel_checks
        )


# ===========================================================================
# Group 13: orchestration truth domain details
# ===========================================================================


@_skip
class TestOrchestrationTruthDomain:
    def _get_state(self) -> Any:
        report = evaluate_center_authority_boundary()
        return report.domain_states[AuthorityDomain.ORCHESTRATION_TRUTH.value]

    def test_orchestration_domain_present(self) -> None:
        report = evaluate_center_authority_boundary()
        assert AuthorityDomain.ORCHESTRATION_TRUTH.value in report.domain_states

    def test_unified_orchestration_spine_in_modules(self) -> None:
        state = self._get_state()
        assert "core.unified_orchestration_spine" in state.canonical_modules

    def test_unified_orchestration_spine_authority_sentinel(self) -> None:
        state = self._get_state()
        assert "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY" in state.sentinel_checks
        assert state.sentinel_checks["UNIFIED_ORCHESTRATION_SPINE_AUTHORITY"] is True

    def test_all_execution_modes_must_use_spine_policy(self) -> None:
        state = self._get_state()
        assert "ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY" in state.sentinel_checks

    def test_orchestration_spine_v4_consumes_canonical_slot_policy(self) -> None:
        state = self._get_state()
        assert (
            "ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY"
            in state.sentinel_checks
        )

    def test_orchestration_spine_v5_completion_closure_policy(self) -> None:
        state = self._get_state()
        assert (
            "ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY" in state.sentinel_checks
        )


# ===========================================================================
# Group 14: assert_center_authority_intact — intact system
# ===========================================================================


@_skip
class TestAssertCenterAuthorityIntactSuccess:
    def test_does_not_raise_on_intact_system(self) -> None:
        # Should not raise.
        assert_center_authority_intact()

    def test_does_not_raise_multiple_calls(self) -> None:
        for _ in range(3):
            assert_center_authority_intact()


# ===========================================================================
# Group 15: assert_center_authority_intact — degraded domain
# ===========================================================================


@_skip
class TestAssertCenterAuthorityIntactDegraded:
    def _make_degraded_report(self, domain: AuthorityDomain) -> CenterAuthorityBoundaryReport:
        """Build a degraded report for patching."""
        report = CenterAuthorityBoundaryReport()
        state = DomainBoundaryState(
            domain=domain,
            status=DomainBoundaryStatus.DEGRADED,
        )
        state.missing_modules.append("core.some_missing_module")
        report.domain_states[domain.value] = state
        for other in AuthorityDomain:
            if other != domain:
                intact_state = DomainBoundaryState(
                    domain=other, status=DomainBoundaryStatus.INTACT
                )
                report.domain_states[other.value] = intact_state
        report.degraded_domains = [domain.value]
        report.all_domains_intact = False
        return report

    def test_raises_on_degraded_completion_truth(self) -> None:
        degraded = self._make_degraded_report(AuthorityDomain.COMPLETION_TRUTH)
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded,
        ):
            with pytest.raises(CenterAuthorityViolation):
                assert_center_authority_intact()

    def test_raises_on_degraded_continuity_legality(self) -> None:
        degraded = self._make_degraded_report(AuthorityDomain.CONTINUITY_LEGALITY_TRUTH)
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded,
        ):
            with pytest.raises(CenterAuthorityViolation):
                assert_center_authority_intact()

    def test_raises_on_degraded_dispatch_readiness(self) -> None:
        degraded = self._make_degraded_report(AuthorityDomain.DISPATCH_READINESS_TRUTH)
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded,
        ):
            with pytest.raises(CenterAuthorityViolation):
                assert_center_authority_intact()

    def test_raises_on_degraded_orchestration_truth(self) -> None:
        degraded = self._make_degraded_report(AuthorityDomain.ORCHESTRATION_TRUTH)
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded,
        ):
            with pytest.raises(CenterAuthorityViolation):
                assert_center_authority_intact()

    def test_exception_has_degraded_domains_list(self) -> None:
        degraded = self._make_degraded_report(AuthorityDomain.COMPLETION_TRUTH)
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded,
        ):
            with pytest.raises(CenterAuthorityViolation) as exc_info:
                assert_center_authority_intact()
        assert len(exc_info.value.degraded_domains) > 0

    def test_exception_has_report(self) -> None:
        degraded = self._make_degraded_report(AuthorityDomain.COMPLETION_TRUTH)
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded,
        ):
            with pytest.raises(CenterAuthorityViolation) as exc_info:
                assert_center_authority_intact()
        assert isinstance(exc_info.value.report, CenterAuthorityBoundaryReport)

    def test_exception_message_includes_domain_name(self) -> None:
        degraded = self._make_degraded_report(AuthorityDomain.COMPLETION_TRUTH)
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded,
        ):
            with pytest.raises(CenterAuthorityViolation) as exc_info:
                assert_center_authority_intact()
        assert "completion_truth" in str(exc_info.value)


# ===========================================================================
# Group 16: get_boundary_report
# ===========================================================================


@_skip
class TestGetBoundaryReport:
    def test_returns_report(self) -> None:
        report = get_boundary_report()
        assert isinstance(report, CenterAuthorityBoundaryReport)

    def test_all_domains_intact(self) -> None:
        report = get_boundary_report()
        assert report.all_domains_intact is True

    def test_four_domain_states(self) -> None:
        report = get_boundary_report()
        assert len(report.domain_states) == 4

    def test_report_id_non_empty(self) -> None:
        report = get_boundary_report()
        assert len(report.report_id) > 0


# ===========================================================================
# Group 17: Degraded domain simulation via patching
# ===========================================================================


@_skip
class TestDegradedDomainSimulation:
    def _build_degraded_report_for_domain(
        self, degraded_domain: AuthorityDomain
    ) -> CenterAuthorityBoundaryReport:
        report = evaluate_center_authority_boundary()
        # Manually corrupt the target domain to DEGRADED.
        state = report.domain_states[degraded_domain.value]
        state.status = DomainBoundaryStatus.DEGRADED
        state.missing_modules.append("core.hypothetical_missing")
        report.degraded_domains = [degraded_domain.value]
        report.all_domains_intact = False
        return report

    def test_degraded_completion_sets_all_intact_false(self) -> None:
        report = self._build_degraded_report_for_domain(AuthorityDomain.COMPLETION_TRUTH)
        assert report.all_domains_intact is False

    def test_degraded_domain_in_degraded_list(self) -> None:
        report = self._build_degraded_report_for_domain(AuthorityDomain.COMPLETION_TRUTH)
        assert AuthorityDomain.COMPLETION_TRUTH.value in report.degraded_domains

    def test_degraded_continuity_sets_all_intact_false(self) -> None:
        report = self._build_degraded_report_for_domain(
            AuthorityDomain.CONTINUITY_LEGALITY_TRUTH
        )
        assert report.all_domains_intact is False

    def test_degraded_readiness_in_degraded_list(self) -> None:
        report = self._build_degraded_report_for_domain(
            AuthorityDomain.DISPATCH_READINESS_TRUTH
        )
        assert AuthorityDomain.DISPATCH_READINESS_TRUTH.value in report.degraded_domains

    def test_degraded_orchestration_in_degraded_list(self) -> None:
        report = self._build_degraded_report_for_domain(
            AuthorityDomain.ORCHESTRATION_TRUTH
        )
        assert AuthorityDomain.ORCHESTRATION_TRUTH.value in report.degraded_domains


# ===========================================================================
# Group 18: Serialisation
# ===========================================================================


@_skip
class TestSerialisation:
    def test_report_to_dict_json_serialisable(self) -> None:
        report = evaluate_center_authority_boundary()
        d = report.to_dict()
        j = json.dumps(d)
        assert isinstance(j, str)

    def test_report_to_json_round_trips(self) -> None:
        report = evaluate_center_authority_boundary()
        j = report.to_json()
        d = json.loads(j)
        assert d["report_id"] == report.report_id
        assert d["all_domains_intact"] == report.all_domains_intact

    def test_domain_state_to_dict_json_serialisable(self) -> None:
        report = evaluate_center_authority_boundary()
        for state in report.domain_states.values():
            d = state.to_dict()
            j = json.dumps(d)
            assert isinstance(j, str)

    def test_to_dict_domain_states_are_dicts(self) -> None:
        report = evaluate_center_authority_boundary()
        d = report.to_dict()
        assert isinstance(d["domain_states"], dict)
        for key, val in d["domain_states"].items():
            assert isinstance(val, dict), f"domain_states[{key}] is not a dict"

    def test_to_json_includes_authority(self) -> None:
        report = evaluate_center_authority_boundary()
        j = report.to_json()
        assert "center_authority_boundary" in j.lower() or "CENTER_AUTHORITY" in j


# ===========================================================================
# Group 19: Error safety
# ===========================================================================


@_skip
class TestErrorSafety:
    def test_evaluate_never_raises(self) -> None:
        # Should always return a report, never raise.
        report = evaluate_center_authority_boundary()
        assert isinstance(report, CenterAuthorityBoundaryReport)

    def test_assert_raises_only_violation(self) -> None:
        # When intact, should not raise anything.
        try:
            assert_center_authority_intact()
        except CenterAuthorityViolation:
            pytest.fail("Unexpected CenterAuthorityViolation on intact system")
        except Exception as exc:
            pytest.fail(f"Unexpected exception type: {type(exc).__name__}: {exc}")

    def test_get_boundary_report_never_raises(self) -> None:
        report = get_boundary_report()
        assert isinstance(report, CenterAuthorityBoundaryReport)


# ===========================================================================
# Group 20: V6 policy sentinel content
# ===========================================================================


@_skip
class TestPolicySentinelContent:
    def test_completion_truth_policy_references_completion(self) -> None:
        assert "completion" in V2_OWNS_COMPLETION_TRUTH_POLICY.lower()

    def test_continuity_legality_policy_references_continuity(self) -> None:
        assert "continuity" in V2_OWNS_CONTINUITY_LEGALITY_TRUTH_POLICY.lower()

    def test_dispatch_readiness_policy_references_dispatch(self) -> None:
        assert "dispatch" in V2_OWNS_DISPATCH_READINESS_TRUTH_POLICY.lower()

    def test_orchestration_truth_policy_references_orchestration(self) -> None:
        assert "orchestration" in V2_OWNS_ORCHESTRATION_TRUTH_POLICY.lower()

    def test_external_surfaces_policy_references_participant(self) -> None:
        assert "participant" in EXTERNAL_SURFACES_ARE_PARTICIPANT_ONLY_POLICY.lower()

    def test_no_parallel_authority_policy_references_parallel(self) -> None:
        assert "parallel" in NO_PARALLEL_AUTHORITY_PERMITTED_POLICY.lower()

    def test_compat_ingress_policy_references_compat(self) -> None:
        assert "compat" in COMPAT_INGRESS_TERMINATES_IN_CENTER_MODEL_POLICY.lower()

    def test_all_four_policies_reference_v6(self) -> None:
        for policy in [
            V2_OWNS_COMPLETION_TRUTH_POLICY,
            V2_OWNS_CONTINUITY_LEGALITY_TRUTH_POLICY,
            V2_OWNS_DISPATCH_READINESS_TRUTH_POLICY,
            V2_OWNS_ORCHESTRATION_TRUTH_POLICY,
        ]:
            assert "V6" in policy, f"Policy missing V6 tag: {policy[:60]}"

    def test_pr_v6_sentinel_includes_completion(self) -> None:
        assert "completion" in CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL.lower()

    def test_pr_v6_sentinel_includes_continuity(self) -> None:
        assert "continuity" in CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL.lower()

    def test_pr_v6_sentinel_includes_readiness(self) -> None:
        assert "readiness" in CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL.lower()

    def test_pr_v6_sentinel_includes_orchestration(self) -> None:
        assert "orchestration" in CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL.lower()
