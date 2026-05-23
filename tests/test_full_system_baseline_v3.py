#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_full_system_baseline_v3.py
======================================
V3 Full-System Baseline — focused validation test suite.

Coverage matrix
---------------
Group A — Module-level imports, sentinels, enums
  A01. Module importable; authority and sentinel strings present.
  A02. SubsystemState has exactly five values.
  A03. SubsystemState ordinal ordering.
  A04. SubsystemState.is_blocking: declared_not_proven → True, implemented_and_evidenced → False.
  A05. V3SubsystemId has exactly twelve values.
  A06. V3BaselineVerdict has exactly four values.

Group B — Data class round-trips
  B01. SubsystemEntry round-trips through to_dict/from_dict.
  B02. V3BaselineReport round-trips through to_dict/from_dict.
  B03. V3BaselineReport.to_json produces valid JSON.
  B04. V3BaselineReport.subsystem() lookup by id.

Group C — Verdict derivation (unit-level)
  C01. All evidenced + android present → closed_and_evidenced.
  C02. All evidenced + android absent → partially_closed_blocking_gaps.
  C03. Any declared_not_proven → partially_closed_blocking_gaps.
  C04. Any contract_only → partially_closed_blocking_gaps.
  C05. Empty subsystem list → insufficient_evidence_to_conclude.

Group D — Baseline report construction
  D01. build_v3_baseline_report() returns V3BaselineReport.
  D02. Report has exactly twelve subsystem entries.
  D03. Report overall_verdict is a valid V3BaselineVerdict.
  D04. Android evidence absent → non-closed verdict.
  D05. blocking_gaps non-empty when android evidence absent.
  D06. open_questions non-empty.
  D07. evidence_linkage non-empty.

Group E — Evidence closure gate
  E01. evaluate_evidence_closure_gate returns ClosureGateResult.
  E02. Gate fails at standard level when android evidence absent.
  E03. Gate passes at minimum level when all subsystems implemented_but_not_closed.
  E04. Gate fails at strict level when overall verdict is not closed_and_evidenced.
  E05. ClosureGateResult.to_json produces valid JSON.

Group F — Singleton behaviour
  F01. get_v3_baseline_report returns same instance on consecutive calls.
  F02. reset_v3_baseline_report clears the singleton.
"""

from __future__ import annotations

import json
import importlib
import pytest
from typing import List

# ---------------------------------------------------------------------------
# Skip guard — skip all tests if the module cannot be imported (should not
# happen in a healthy repo, but protects against unrelated import errors).
# ---------------------------------------------------------------------------


def _can_import(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


_BASELINE_AVAILABLE = _can_import("core.full_system_baseline_v3")
_GATE_AVAILABLE = _can_import("core.full_system_evidence_closure_gate")

pytestmark = pytest.mark.skipif(
    not _BASELINE_AVAILABLE,
    reason="core.full_system_baseline_v3 not importable",
)


# ---------------------------------------------------------------------------
# Imports (inside functions for test isolation where needed at module level)
# ---------------------------------------------------------------------------

from core.full_system_baseline_v3 import (  # noqa: E402
    FULL_SYSTEM_BASELINE_V3_AUTHORITY,
    FULL_SYSTEM_BASELINE_V3_SENTINEL,
    ANDROID_EVIDENCE_ABSENCE_DOWNGRADES_VERDICT_POLICY,
    DECLARED_NOT_PROVEN_BLOCKS_CLOSED_VERDICT_POLICY,
    SubsystemState,
    V3SubsystemId,
    V3BaselineVerdict,
    SubsystemEntry,
    BlockingGap,
    OpenQuestion,
    V3BaselineReport,
    FullSystemBaselineV3Evaluator,
    build_v3_baseline_report,
    get_v3_baseline_report,
    reset_v3_baseline_report,
)

# ---------------------------------------------------------------------------
# Group A — Module-level imports, sentinels, enums
# ---------------------------------------------------------------------------


class TestGroupA_ModuleLevel:
    def test_A01_module_importable_sentinels_present(self) -> None:
        assert FULL_SYSTEM_BASELINE_V3_AUTHORITY
        assert FULL_SYSTEM_BASELINE_V3_SENTINEL
        assert ANDROID_EVIDENCE_ABSENCE_DOWNGRADES_VERDICT_POLICY
        assert DECLARED_NOT_PROVEN_BLOCKS_CLOSED_VERDICT_POLICY

    def test_A02_subsystem_state_has_five_values(self) -> None:
        assert len(list(SubsystemState)) == 5

    def test_A03_subsystem_state_ordinal_ordering(self) -> None:
        assert SubsystemState.declared_not_proven.ordinal() == 0
        assert SubsystemState.test_only.ordinal() == 1
        assert SubsystemState.contract_only.ordinal() == 2
        assert SubsystemState.implemented_but_not_closed.ordinal() == 3
        assert SubsystemState.implemented_and_evidenced.ordinal() == 4

    def test_A04_subsystem_state_is_blocking(self) -> None:
        assert SubsystemState.declared_not_proven.is_blocking() is True
        assert SubsystemState.test_only.is_blocking() is True
        assert SubsystemState.contract_only.is_blocking() is True
        assert SubsystemState.implemented_but_not_closed.is_blocking() is False
        assert SubsystemState.implemented_and_evidenced.is_blocking() is False

    def test_A05_v3_subsystem_id_has_twelve_values(self) -> None:
        assert len(list(V3SubsystemId)) == 12

    def test_A06_v3_baseline_verdict_has_four_values(self) -> None:
        assert len(list(V3BaselineVerdict)) == 4


# ---------------------------------------------------------------------------
# Group B — Data class round-trips
# ---------------------------------------------------------------------------


class TestGroupB_DataClassRoundTrips:
    def test_B01_subsystem_entry_round_trip(self) -> None:
        entry = SubsystemEntry(
            subsystem_id="v2_release_gate",
            state=SubsystemState.implemented_and_evidenced,
            rationale="test rationale",
            evidence_module="core.foo",
            known_gaps=["gap1"],
            grounding_signals={"overall_verdict": "open"},
        )
        d = entry.to_dict()
        recovered = SubsystemEntry.from_dict(d)
        assert recovered.subsystem_id == entry.subsystem_id
        assert recovered.state == entry.state
        assert recovered.rationale == entry.rationale
        assert recovered.evidence_module == entry.evidence_module
        assert recovered.known_gaps == entry.known_gaps
        assert recovered.grounding_signals == entry.grounding_signals

    def test_B02_v3_baseline_report_round_trip(self) -> None:
        report = V3BaselineReport(
            overall_verdict=V3BaselineVerdict.partially_closed_blocking_gaps,
            subsystems=[
                SubsystemEntry(
                    subsystem_id="v2_release_gate",
                    state=SubsystemState.implemented_but_not_closed,
                )
            ],
            blocking_gaps=[BlockingGap(gap_id="g1", description="test gap")],
            open_questions=[OpenQuestion(question_id="q1", question="is it done?")],
            evidence_linkage={"foo": "bar"},
            scorecard={"overall": {"code_present_count": 1}},
            summary="test summary",
            generated_at="2026-01-01T00:00:00+00:00",
            android_evidence_state={"detected": True, "complete": False},
        )
        d = report.to_dict()
        recovered = V3BaselineReport.from_dict(d)
        assert recovered.overall_verdict == report.overall_verdict
        assert len(recovered.subsystems) == 1
        assert recovered.subsystems[0].subsystem_id == "v2_release_gate"
        assert len(recovered.blocking_gaps) == 1
        assert len(recovered.open_questions) == 1
        assert recovered.scorecard == report.scorecard
        assert recovered.android_evidence_state == report.android_evidence_state

    def test_B03_v3_baseline_report_to_json_valid(self) -> None:
        report = V3BaselineReport(overall_verdict=V3BaselineVerdict.insufficient_evidence_to_conclude)
        j = report.to_json()
        parsed = json.loads(j)
        assert "overall_verdict" in parsed
        assert "subsystems" in parsed
        assert "blocking_gaps" in parsed
        assert "open_questions" in parsed
        assert "scorecard" in parsed

    def test_B04_report_subsystem_lookup(self) -> None:
        report = V3BaselineReport(
            subsystems=[
                SubsystemEntry(subsystem_id="v2_release_gate"),
                SubsystemEntry(subsystem_id="cross_repo_evidence_pipeline"),
            ]
        )
        found = report.subsystem("cross_repo_evidence_pipeline")
        assert found is not None
        assert found.subsystem_id == "cross_repo_evidence_pipeline"
        assert report.subsystem("nonexistent") is None


# ---------------------------------------------------------------------------
# Group C — Verdict derivation (unit-level)
# ---------------------------------------------------------------------------


def _make_subsystems(states: List[SubsystemState]) -> List[SubsystemEntry]:
    return [SubsystemEntry(subsystem_id=f"s{i}", state=s) for i, s in enumerate(states)]


class TestGroupC_VerdictDerivation:
    """Tests for _derive_verdict using the evaluator's static method."""

    def test_C01_all_evidenced_android_present_is_closed(self) -> None:
        subsystems = _make_subsystems([SubsystemState.implemented_and_evidenced] * 12)
        verdict = FullSystemBaselineV3Evaluator._derive_verdict(subsystems, android_evidence_present=True)
        assert verdict == V3BaselineVerdict.closed_and_evidenced

    def test_C02_all_evidenced_android_absent_is_partial(self) -> None:
        subsystems = _make_subsystems([SubsystemState.implemented_and_evidenced] * 12)
        verdict = FullSystemBaselineV3Evaluator._derive_verdict(subsystems, android_evidence_present=False)
        assert verdict == V3BaselineVerdict.partially_closed_blocking_gaps

    def test_C03_declared_not_proven_forces_partial(self) -> None:
        subsystems = _make_subsystems(
            [SubsystemState.implemented_and_evidenced] * 11 + [SubsystemState.declared_not_proven]
        )
        verdict = FullSystemBaselineV3Evaluator._derive_verdict(subsystems, android_evidence_present=True)
        assert verdict == V3BaselineVerdict.partially_closed_blocking_gaps

    def test_C04_contract_only_forces_partial(self) -> None:
        subsystems = _make_subsystems([SubsystemState.implemented_and_evidenced] * 11 + [SubsystemState.contract_only])
        verdict = FullSystemBaselineV3Evaluator._derive_verdict(subsystems, android_evidence_present=True)
        assert verdict == V3BaselineVerdict.partially_closed_blocking_gaps

    def test_C05_empty_subsystems_is_insufficient(self) -> None:
        verdict = FullSystemBaselineV3Evaluator._derive_verdict([], android_evidence_present=True)
        assert verdict == V3BaselineVerdict.insufficient_evidence_to_conclude


# ---------------------------------------------------------------------------
# Group D — Baseline report construction
# ---------------------------------------------------------------------------


class TestGroupD_BaselineReport:
    def test_D01_build_returns_v3_baseline_report(self) -> None:
        report = build_v3_baseline_report()
        assert isinstance(report, V3BaselineReport)

    def test_D02_report_has_twelve_subsystems(self) -> None:
        report = build_v3_baseline_report()
        assert len(report.subsystems) == 12

    def test_D03_report_verdict_is_valid(self) -> None:
        report = build_v3_baseline_report()
        valid_verdicts = {v.value for v in V3BaselineVerdict}
        assert report.overall_verdict.value in valid_verdicts

    def test_D04_android_absent_means_non_closed_verdict(self) -> None:
        report = build_v3_baseline_report()
        if not report.android_evidence_present:
            assert report.overall_verdict != V3BaselineVerdict.closed_and_evidenced

    def test_D05_blocking_gaps_nonempty_when_android_absent(self) -> None:
        report = build_v3_baseline_report()
        if not report.android_evidence_present:
            # Must have at least the android_cross_repo_evidence_absent gap
            gap_ids = [g.gap_id for g in report.blocking_gaps]
            assert "android_cross_repo_evidence_absent" in gap_ids

    def test_D06_open_questions_nonempty(self) -> None:
        report = build_v3_baseline_report()
        assert len(report.open_questions) > 0

    def test_D07_evidence_linkage_nonempty(self) -> None:
        report = build_v3_baseline_report()
        assert len(report.evidence_linkage) > 0

    def test_D08_scorecard_distinguishes_present_wired_evidenced(self) -> None:
        report = build_v3_baseline_report()
        scorecard = report.scorecard
        assert "overall" in scorecard
        assert "subsystems" in scorecard
        assert report.subsystems[0].subsystem_id in scorecard["subsystems"]
        sample = scorecard["subsystems"][report.subsystems[0].subsystem_id]
        assert "code_present" in sample
        assert "code_wired" in sample
        assert "code_evidenced" in sample
        assert "blocked_by_missing_cross_repo_evidence" in sample

    def test_D09_structured_evidence_linkage_contains_underlying_verdicts(self) -> None:
        report = build_v3_baseline_report()
        acceptance = report.evidence_linkage.get("system_final_acceptance_verdict", {})
        cross_repo = report.evidence_linkage.get("cross_repo_evidence_pipeline", {})
        assert isinstance(acceptance, dict)
        assert isinstance(cross_repo, dict)
        assert "grounding_signals" in acceptance
        assert "acceptance_verdict" in acceptance["grounding_signals"]
        assert "pipeline_verdict" in cross_repo["grounding_signals"]

    def test_D10_all_subsystems_have_valid_state(self) -> None:
        valid_states = {s.value for s in SubsystemState}
        report = build_v3_baseline_report()
        for entry in report.subsystems:
            assert (
                entry.state.value in valid_states
            ), f"Subsystem {entry.subsystem_id!r} has invalid state {entry.state!r}"

    def test_D11_report_is_json_serialisable(self) -> None:
        report = build_v3_baseline_report()
        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["overall_verdict"] == report.overall_verdict.value
        assert len(parsed["subsystems"]) == 12

    def test_D12_blocking_subsystems_property_consistent(self) -> None:
        report = build_v3_baseline_report()
        blocking = report.blocking_subsystems
        for entry in blocking:
            assert entry.state.is_blocking(), (
                f"Subsystem {entry.subsystem_id!r} in blocking_subsystems " f"but state {entry.state!r} is not blocking"
            )

    def test_D13_android_evidence_state_exposes_precise_closure_dimensions(self) -> None:
        report = build_v3_baseline_report()
        state = report.android_evidence_state
        required = {
            "detected",
            "complete",
            "fresh",
            "authority_clear",
            "routine_cross_repo_delivery",
            "closure_grade",
            "pipeline_verdict",
            "closure_blocking_reasons",
        }
        assert required.issubset(set(state.keys()))

    def test_D14_blocking_gaps_expose_closure_scope_and_priority(self) -> None:
        report = build_v3_baseline_report()
        if report.blocking_gaps:
            for gap in report.blocking_gaps:
                assert gap.closure_scope in {"repo_local", "cross_repo", "runtime_proof"}
                assert gap.execution_priority in {"high", "medium", "low"}
                assert isinstance(gap.blocker_classification, str)

    def test_D15_open_questions_expose_actionable_scope_metadata(self) -> None:
        report = build_v3_baseline_report()
        actionable_prefixes = ("run ", "verify ", "confirm ", "produce ")
        for question in report.open_questions:
            assert question.closure_scope in {"repo_local", "cross_repo", "runtime_proof"}
            assert question.execution_priority in {"high", "medium", "low"}
            assert isinstance(question.next_action_hint, str)
            assert len(question.next_action_hint) > 0
            assert question.next_action_hint.lower().startswith(actionable_prefixes)

    def test_D16_scorecard_reports_scope_breakdown_for_closure_driving(self) -> None:
        report = build_v3_baseline_report()
        overall = report.scorecard.get("overall", {})
        gap_scope_counts = overall.get("blocking_gap_scope_counts", {})
        question_scope_counts = overall.get("open_question_scope_counts", {})
        for key in ("repo_local", "cross_repo", "runtime_proof"):
            assert key in gap_scope_counts
            assert key in question_scope_counts


# ---------------------------------------------------------------------------
# Group E — Evidence closure gate
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _GATE_AVAILABLE,
    reason="core.full_system_evidence_closure_gate not importable",
)
class TestGroupE_EvidenceClosureGate:
    def test_E01_evaluate_returns_closure_gate_result(self) -> None:
        from core.full_system_evidence_closure_gate import (
            evaluate_evidence_closure_gate,
            ClosureGateResult,
            ClosureLevel,
        )

        result = evaluate_evidence_closure_gate(ClosureLevel.standard)
        assert isinstance(result, ClosureGateResult)

    def test_E02_standard_gate_fails_when_android_absent(self) -> None:
        from core.full_system_evidence_closure_gate import (
            evaluate_evidence_closure_gate,
            ClosureLevel,
        )

        report = build_v3_baseline_report()
        if not report.android_evidence_present:
            result = evaluate_evidence_closure_gate(ClosureLevel.standard)
            assert result.gate_passed is False
            # At least one fail reason must mention android
            assert any("android" in r.lower() or "cross-repo" in r.lower() for r in result.fail_reasons)

    def test_E03_minimum_gate_does_not_fail_on_android_absence_alone(self) -> None:
        """minimum level: android evidence absence alone should not be a fail reason.
        The minimum gate only fails if subsystems are below implemented_but_not_closed."""
        from core.full_system_evidence_closure_gate import (
            evaluate_evidence_closure_gate,
            ClosureLevel,
        )

        report = build_v3_baseline_report()
        result = evaluate_evidence_closure_gate(ClosureLevel.minimum)
        # At minimum level, android absence should not be a fail reason
        android_fail = any("android" in r.lower() and "evidence" in r.lower() for r in result.fail_reasons)
        assert not android_fail

    def test_E04_strict_gate_fails_when_verdict_not_closed(self) -> None:
        from core.full_system_evidence_closure_gate import (
            evaluate_evidence_closure_gate,
            ClosureLevel,
        )

        report = build_v3_baseline_report()
        if report.overall_verdict.value != "closed_and_evidenced":
            result = evaluate_evidence_closure_gate(ClosureLevel.strict)
            assert result.gate_passed is False

    def test_E05_closure_gate_result_json_roundtrip(self) -> None:
        from core.full_system_evidence_closure_gate import (
            evaluate_evidence_closure_gate,
            ClosureLevel,
        )

        result = evaluate_evidence_closure_gate(ClosureLevel.standard)
        j = result.to_json()
        parsed = json.loads(j)
        assert "gate_passed" in parsed
        assert "closure_level" in parsed
        assert "verdict" in parsed
        assert "fail_reasons" in parsed

    def test_E06_standard_gate_fails_when_android_evidence_detected_but_not_closure_grade(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core.full_system_evidence_closure_gate import (
            evaluate_evidence_closure_gate,
            ClosureLevel,
        )
        import core.full_system_baseline_v3 as baseline_mod

        synthetic = V3BaselineReport(
            overall_verdict=V3BaselineVerdict.partially_closed_blocking_gaps,
            subsystems=_make_subsystems([SubsystemState.implemented_but_not_closed] * 12),
            android_evidence_present=True,
            android_evidence_state={
                "detected": True,
                "complete": False,
                "fresh": True,
                "authority_clear": True,
                "routine_cross_repo_delivery": True,
                "closure_grade": False,
                "closure_blocking_reasons": ["android_evidence_not_complete"],
            },
        )
        monkeypatch.setattr(baseline_mod, "build_v3_baseline_report", lambda: synthetic)
        result = evaluate_evidence_closure_gate(ClosureLevel.standard)
        assert result.gate_passed is False
        assert any("closure-grade" in reason for reason in result.fail_reasons)

    def test_E07_standard_gate_fails_when_overall_verdict_not_closure_grade(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core.full_system_evidence_closure_gate import (
            evaluate_evidence_closure_gate,
            ClosureLevel,
        )
        import core.full_system_baseline_v3 as baseline_mod

        synthetic = V3BaselineReport(
            overall_verdict=V3BaselineVerdict.partially_closed_blocking_gaps,
            subsystems=_make_subsystems([SubsystemState.implemented_but_not_closed] * 12),
            android_evidence_present=True,
            android_evidence_state={
                "detected": True,
                "complete": True,
                "fresh": True,
                "authority_clear": True,
                "routine_cross_repo_delivery": True,
                "closure_grade": True,
                "closure_blocking_reasons": [],
            },
        )
        monkeypatch.setattr(baseline_mod, "build_v3_baseline_report", lambda: synthetic)
        result = evaluate_evidence_closure_gate(ClosureLevel.standard)
        assert result.gate_passed is False
        assert any("standard level requires closure-grade baseline verdict" in reason for reason in result.fail_reasons)


# ---------------------------------------------------------------------------
# Group F — Singleton behaviour
# ---------------------------------------------------------------------------


class TestGroupF_Singleton:
    def test_F01_get_returns_same_instance(self) -> None:
        reset_v3_baseline_report()
        r1 = get_v3_baseline_report()
        r2 = get_v3_baseline_report()
        assert r1 is r2

    def test_F02_reset_clears_singleton(self) -> None:
        reset_v3_baseline_report()
        r1 = get_v3_baseline_report()
        reset_v3_baseline_report()
        r2 = get_v3_baseline_report()
        # After reset a new instance is returned (not the same object)
        assert r1 is not r2
