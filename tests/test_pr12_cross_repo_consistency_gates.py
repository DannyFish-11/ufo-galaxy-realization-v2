"""tests/test_pr12_cross_repo_consistency_gates.py
===================================================
PR-12: Cross-repository consistency gates — test suite.

Tests cover:
- Module authority sentinels and PR-12 sentinel
- Policy sentinels are non-empty strings
- ConsistencyGateKind and GateVerdict enum completeness
- ConsistencyGateResult dataclass structure and invariants
- ConsistencyGateSnapshot dataclass structure and to_dict()
- Individual gate runner functions: schema_vocabulary, session_family,
  execution_enum, terminal_state, descriptor_field, transitional_marker
- run_all_consistency_gates() aggregate runner
- build_consistency_gate_snapshot() CI-friendly snapshot builder
- Projection alignment sentinel
- Gate results are non-breaking (no exceptions raised on drift)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.cross_repo_consistency_gates import (
    CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY,
    CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL,
    DESCRIPTOR_FIELDS_MUST_REMAIN_CANONICAL_POLICY,
    GATES_ARE_NON_BREAKING_POLICY,
    SESSION_FAMILY_DRIFT_IS_HIGH_SEVERITY_POLICY,
    TERMINAL_STATE_SET_IS_CLOSED_AND_GATED_POLICY,
    TRANSITIONAL_ALLOWANCES_MUST_BE_EXPLICIT_POLICY,
    UNRESOLVED_SURFACES_ARE_DRIFT_INDICATORS_POLICY,
    ConsistencyGateKind,
    ConsistencyGateResult,
    ConsistencyGateSnapshot,
    GateVerdict,
    build_consistency_gate_snapshot,
    run_all_consistency_gates,
    run_descriptor_field_gate,
    run_execution_enum_gate,
    run_schema_vocabulary_gate,
    run_session_family_gate,
    run_terminal_state_gate,
    run_transitional_marker_gate,
)

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Authority and policy sentinel tests
# ---------------------------------------------------------------------------


def test_consistency_gates_authority_sentinel():
    assert CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY.startswith(
        "CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY::"
    )
    assert "core.cross_repo_consistency_gates" in CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY


def test_pr12_sentinel_present():
    assert CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL.startswith(
        "CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL::"
    )
    assert "PR12" in CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL
    assert "cross-repo-consistency-gates-v1" in CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL
    assert "core.cross_repo_consistency_gates" in CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL


def test_policy_sentinels_are_non_empty_strings():
    for sentinel in [
        GATES_ARE_NON_BREAKING_POLICY,
        UNRESOLVED_SURFACES_ARE_DRIFT_INDICATORS_POLICY,
        TRANSITIONAL_ALLOWANCES_MUST_BE_EXPLICIT_POLICY,
        TERMINAL_STATE_SET_IS_CLOSED_AND_GATED_POLICY,
        DESCRIPTOR_FIELDS_MUST_REMAIN_CANONICAL_POLICY,
        SESSION_FAMILY_DRIFT_IS_HIGH_SEVERITY_POLICY,
    ]:
        assert isinstance(sentinel, str) and len(sentinel) > 0


def test_gates_are_non_breaking_policy_mentions_ci():
    assert "CI" in GATES_ARE_NON_BREAKING_POLICY or "ci" in GATES_ARE_NON_BREAKING_POLICY.lower()


def test_transitional_allowances_policy_mentions_retirement():
    assert "retirement" in TRANSITIONAL_ALLOWANCES_MUST_BE_EXPLICIT_POLICY.lower()


def test_terminal_state_closed_policy_mentions_closed():
    assert "closed" in TERMINAL_STATE_SET_IS_CLOSED_AND_GATED_POLICY.lower()


def test_session_family_policy_mentions_high_severity():
    assert "high-severity" in SESSION_FAMILY_DRIFT_IS_HIGH_SEVERITY_POLICY.lower()


# ---------------------------------------------------------------------------
# ConsistencyGateKind enum tests
# ---------------------------------------------------------------------------


def test_consistency_gate_kind_has_six_values():
    values = set(ConsistencyGateKind)
    assert len(values) == 6


def test_consistency_gate_kind_contains_expected_values():
    values = {k.value for k in ConsistencyGateKind}
    assert values == {
        "schema_vocabulary",
        "session_family",
        "execution_enum",
        "terminal_state",
        "descriptor_field",
        "transitional_marker",
    }


def test_consistency_gate_kind_values_are_lowercase():
    for kind in ConsistencyGateKind:
        assert kind.value == kind.value.lower()


# ---------------------------------------------------------------------------
# GateVerdict enum tests
# ---------------------------------------------------------------------------


def test_gate_verdict_has_three_values():
    values = set(GateVerdict)
    assert len(values) == 3


def test_gate_verdict_contains_expected_values():
    values = {v.value for v in GateVerdict}
    assert values == {"pass", "warn", "fail"}


# ---------------------------------------------------------------------------
# ConsistencyGateResult dataclass tests
# ---------------------------------------------------------------------------


def test_consistency_gate_result_passed_property_pass():
    result = ConsistencyGateResult(
        gate_id="test_gate",
        kind=ConsistencyGateKind.schema_vocabulary,
        verdict=GateVerdict.pass_,
        drift_detected=False,
        details="clean",
        issues=(),
    )
    assert result.passed is True


def test_consistency_gate_result_passed_property_warn():
    result = ConsistencyGateResult(
        gate_id="test_gate",
        kind=ConsistencyGateKind.terminal_state,
        verdict=GateVerdict.warn,
        drift_detected=False,
        details="warned",
        issues=("some warning",),
    )
    assert result.passed is True


def test_consistency_gate_result_passed_property_fail():
    result = ConsistencyGateResult(
        gate_id="test_gate",
        kind=ConsistencyGateKind.execution_enum,
        verdict=GateVerdict.fail,
        drift_detected=True,
        details="failed",
        issues=("drift detected",),
    )
    assert result.passed is False


def test_consistency_gate_result_has_checked_at():
    result = ConsistencyGateResult(
        gate_id="test_gate",
        kind=ConsistencyGateKind.schema_vocabulary,
        verdict=GateVerdict.pass_,
        drift_detected=False,
        details="clean",
    )
    assert result.checked_at > 0


def test_consistency_gate_result_is_frozen():
    result = ConsistencyGateResult(
        gate_id="test_gate",
        kind=ConsistencyGateKind.schema_vocabulary,
        verdict=GateVerdict.pass_,
        drift_detected=False,
        details="clean",
    )
    with pytest.raises((AttributeError, TypeError)):
        result.gate_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ConsistencyGateSnapshot tests
# ---------------------------------------------------------------------------


def test_consistency_gate_snapshot_is_clean_when_no_drift():
    snap = ConsistencyGateSnapshot(
        generated_at=1.0,
        total_gates=6,
        passed_gates=6,
        warned_gates=0,
        failed_gates=0,
        drift_detected=False,
        gate_results=[],
    )
    assert snap.is_clean() is True


def test_consistency_gate_snapshot_not_clean_when_drift():
    snap = ConsistencyGateSnapshot(
        generated_at=1.0,
        total_gates=6,
        passed_gates=5,
        warned_gates=0,
        failed_gates=1,
        drift_detected=True,
        gate_results=[],
    )
    assert snap.is_clean() is False


def test_consistency_gate_snapshot_to_dict_structure():
    snap = build_consistency_gate_snapshot()
    d = snap.to_dict()
    assert "generated_at" in d
    assert "total_gates" in d
    assert "passed_gates" in d
    assert "warned_gates" in d
    assert "failed_gates" in d
    assert "drift_detected" in d
    assert "is_clean" in d
    assert "summary" in d
    assert "gate_results" in d
    assert isinstance(d["gate_results"], list)


def test_consistency_gate_snapshot_to_dict_gate_result_structure():
    snap = build_consistency_gate_snapshot()
    d = snap.to_dict()
    for gr in d["gate_results"]:
        assert "gate_id" in gr
        assert "kind" in gr
        assert "verdict" in gr
        assert "drift_detected" in gr
        assert "details" in gr
        assert "issues" in gr
        assert "checked_at" in gr
        assert isinstance(gr["issues"], list)


# ---------------------------------------------------------------------------
# Individual gate runner tests
# ---------------------------------------------------------------------------


def test_run_schema_vocabulary_gate_returns_result():
    result = run_schema_vocabulary_gate()
    assert isinstance(result, ConsistencyGateResult)
    assert result.gate_id == "schema_vocabulary"
    assert result.kind == ConsistencyGateKind.schema_vocabulary


def test_run_schema_vocabulary_gate_passes():
    result = run_schema_vocabulary_gate()
    assert result.passed, (
        f"schema_vocabulary gate unexpectedly failed: {result.details}\n"
        + "\n".join(result.issues)
    )
    assert not result.drift_detected


def test_run_schema_vocabulary_gate_details_non_empty():
    result = run_schema_vocabulary_gate()
    assert isinstance(result.details, str) and len(result.details) > 0


def test_run_session_family_gate_returns_result():
    result = run_session_family_gate()
    assert isinstance(result, ConsistencyGateResult)
    assert result.gate_id == "session_family"
    assert result.kind == ConsistencyGateKind.session_family


def test_run_session_family_gate_passes():
    result = run_session_family_gate()
    assert result.passed, (
        f"session_family gate unexpectedly failed: {result.details}\n"
        + "\n".join(result.issues)
    )
    assert not result.drift_detected


def test_run_execution_enum_gate_returns_result():
    result = run_execution_enum_gate()
    assert isinstance(result, ConsistencyGateResult)
    assert result.gate_id == "execution_enum"
    assert result.kind == ConsistencyGateKind.execution_enum


def test_run_execution_enum_gate_passes():
    result = run_execution_enum_gate()
    assert result.passed, (
        f"execution_enum gate unexpectedly failed: {result.details}\n"
        + "\n".join(result.issues)
    )
    assert not result.drift_detected


def test_run_terminal_state_gate_returns_result():
    result = run_terminal_state_gate()
    assert isinstance(result, ConsistencyGateResult)
    assert result.gate_id == "terminal_state"
    assert result.kind == ConsistencyGateKind.terminal_state


def test_run_terminal_state_gate_no_drift():
    result = run_terminal_state_gate()
    # terminal_state gate may warn about documented cross-module differences
    # (intentional, not drift), but must not report drift_detected=True
    assert not result.drift_detected, (
        f"terminal_state gate detected unexpected drift: {result.details}\n"
        + "\n".join(result.issues)
    )


def test_run_terminal_state_gate_closed_set_invariant_satisfied():
    result = run_terminal_state_gate()
    # If there are only warnings (not failures), the closed-set invariant is met
    assert result.verdict in (GateVerdict.pass_, GateVerdict.warn), (
        f"terminal_state gate failed (closed-set invariant violated): "
        f"{result.details}"
    )


def test_run_descriptor_field_gate_returns_result():
    result = run_descriptor_field_gate()
    assert isinstance(result, ConsistencyGateResult)
    assert result.gate_id == "descriptor_field"
    assert result.kind == ConsistencyGateKind.descriptor_field


def test_run_descriptor_field_gate_passes():
    result = run_descriptor_field_gate()
    assert result.passed, (
        f"descriptor_field gate unexpectedly failed: {result.details}\n"
        + "\n".join(result.issues)
    )
    assert not result.drift_detected


def test_run_transitional_marker_gate_returns_result():
    result = run_transitional_marker_gate()
    assert isinstance(result, ConsistencyGateResult)
    assert result.gate_id == "transitional_marker"
    assert result.kind == ConsistencyGateKind.transitional_marker


def test_run_transitional_marker_gate_passes():
    result = run_transitional_marker_gate()
    assert result.passed, (
        f"transitional_marker gate unexpectedly failed: {result.details}\n"
        + "\n".join(result.issues)
    )
    assert not result.drift_detected


def test_transitional_marker_gate_details_mentions_allowances():
    result = run_transitional_marker_gate()
    assert "allowance" in result.details.lower()


# ---------------------------------------------------------------------------
# run_all_consistency_gates aggregate runner tests
# ---------------------------------------------------------------------------


def test_run_all_consistency_gates_returns_sequence():
    results = run_all_consistency_gates()
    assert len(results) == 6


def test_run_all_consistency_gates_returns_correct_kinds():
    results = run_all_consistency_gates()
    kinds = [r.kind for r in results]
    assert ConsistencyGateKind.schema_vocabulary in kinds
    assert ConsistencyGateKind.session_family in kinds
    assert ConsistencyGateKind.execution_enum in kinds
    assert ConsistencyGateKind.terminal_state in kinds
    assert ConsistencyGateKind.descriptor_field in kinds
    assert ConsistencyGateKind.transitional_marker in kinds


def test_run_all_consistency_gates_all_have_unique_ids():
    results = run_all_consistency_gates()
    ids = [r.gate_id for r in results]
    assert len(ids) == len(set(ids)), "Duplicate gate_ids found"


def test_run_all_consistency_gates_gate_order():
    results = run_all_consistency_gates()
    expected_order = [
        "schema_vocabulary",
        "session_family",
        "execution_enum",
        "terminal_state",
        "descriptor_field",
        "transitional_marker",
    ]
    assert [r.gate_id for r in results] == expected_order


def test_run_all_consistency_gates_all_results_non_null():
    results = run_all_consistency_gates()
    for result in results:
        assert result is not None
        assert isinstance(result, ConsistencyGateResult)


def test_run_all_consistency_gates_no_drift_detected():
    results = run_all_consistency_gates()
    drifting = [r for r in results if r.drift_detected]
    assert len(drifting) == 0, (
        f"Unexpected drift detected in gates: "
        + ", ".join(f"{r.gate_id}({r.verdict.value})" for r in drifting)
    )


# ---------------------------------------------------------------------------
# build_consistency_gate_snapshot tests
# ---------------------------------------------------------------------------


def test_build_consistency_gate_snapshot_returns_snapshot():
    snap = build_consistency_gate_snapshot()
    assert isinstance(snap, ConsistencyGateSnapshot)


def test_build_consistency_gate_snapshot_total_gates_is_six():
    snap = build_consistency_gate_snapshot()
    assert snap.total_gates == 6


def test_build_consistency_gate_snapshot_passed_plus_failed_equals_total():
    snap = build_consistency_gate_snapshot()
    # passed_gates includes warn-level gates too
    assert snap.passed_gates + snap.failed_gates == snap.total_gates


def test_build_consistency_gate_snapshot_gate_results_length():
    snap = build_consistency_gate_snapshot()
    assert len(snap.gate_results) == snap.total_gates


def test_build_consistency_gate_snapshot_is_clean():
    snap = build_consistency_gate_snapshot()
    assert snap.is_clean(), (
        f"Snapshot not clean: {snap.summary}\n"
        + "\n".join(
            f"  {r.gate_id}: {r.verdict.value}" for r in snap.gate_results
        )
    )


def test_build_consistency_gate_snapshot_summary_non_empty():
    snap = build_consistency_gate_snapshot()
    assert isinstance(snap.summary, str) and len(snap.summary) > 0


def test_build_consistency_gate_snapshot_summary_mentions_gates():
    snap = build_consistency_gate_snapshot()
    assert "gate" in snap.summary.lower()


def test_build_consistency_gate_snapshot_generated_at_positive():
    snap = build_consistency_gate_snapshot()
    assert snap.generated_at > 0


def test_build_consistency_gate_snapshot_to_dict_is_clean():
    snap = build_consistency_gate_snapshot()
    d = snap.to_dict()
    assert d["is_clean"] is True
    assert d["drift_detected"] is False


def test_build_consistency_gate_snapshot_to_dict_verdicts_are_strings():
    snap = build_consistency_gate_snapshot()
    d = snap.to_dict()
    for gr in d["gate_results"]:
        assert isinstance(gr["verdict"], str)
        assert gr["verdict"] in ("pass", "warn", "fail")


# ---------------------------------------------------------------------------
# Non-breaking behavior tests
# ---------------------------------------------------------------------------


def test_all_gate_runners_do_not_raise():
    """Gate runners must never raise exceptions (GATES_ARE_NON_BREAKING_POLICY)."""
    for runner in [
        run_schema_vocabulary_gate,
        run_session_family_gate,
        run_execution_enum_gate,
        run_terminal_state_gate,
        run_descriptor_field_gate,
        run_transitional_marker_gate,
    ]:
        try:
            result = runner()
            assert isinstance(result, ConsistencyGateResult)
        except Exception as exc:
            pytest.fail(
                f"Gate runner {runner.__name__} raised an exception: {exc!r}. "
                "Gate runners must be non-breaking."
            )


def test_build_consistency_gate_snapshot_does_not_raise():
    """Snapshot builder must never raise exceptions."""
    try:
        snap = build_consistency_gate_snapshot()
        assert isinstance(snap, ConsistencyGateSnapshot)
    except Exception as exc:
        pytest.fail(
            f"build_consistency_gate_snapshot raised an exception: {exc!r}. "
            "Snapshot builder must be non-breaking."
        )


# ---------------------------------------------------------------------------
# Cross-module consistency integration tests
# ---------------------------------------------------------------------------


def test_schema_vocabulary_gate_no_unresolved_surfaces():
    """Verify the schema vocabulary gate finds no unresolved surfaces."""
    from core.cross_repo_protocol_consistency import (
        ProtocolSurfaceClass,
        get_protocol_surface_catalogue,
    )
    unresolved = [
        r
        for r in get_protocol_surface_catalogue()
        if r.surface_class == ProtocolSurfaceClass.unresolved
    ]
    assert len(unresolved) == 0, (
        f"Unresolved surfaces found (would cause schema_vocabulary gate drift): "
        + str([r.surface_id for r in unresolved])
    )


def test_execution_enum_gate_terminal_phases_align_with_canonical_terminal_states():
    """Verify all terminal execution phases map to CanonicalTerminalState values."""
    from core.cross_repo_protocol_consistency import (
        CanonicalTerminalState,
        get_delegated_execution_status_catalogue,
    )
    canonical_values = {s.value for s in CanonicalTerminalState}
    for record in get_delegated_execution_status_catalogue():
        if record.is_terminal:
            assert record.phase_value in canonical_values, (
                f"Terminal execution phase '{record.phase_value}' is not in "
                "CanonicalTerminalState. All terminal phases must correspond "
                "to canonical terminal state values."
            )


def test_transitional_marker_gate_all_allowances_have_retirement_condition():
    """Verify every transitional allowance has a non-empty retirement_condition."""
    from core.cross_repo_protocol_consistency import get_transitional_allowance_catalogue
    for record in get_transitional_allowance_catalogue():
        assert record.retirement_condition, (
            f"Transitional allowance '{record.allowance_id}' has no "
            "retirement_condition. All allowances must be explicit."
        )


def test_transitional_marker_gate_all_surfaces_have_retirement_pathway():
    """Verify transitional surfaces in PR-4 catalogue have retirement pathways."""
    from core.cross_repo_protocol_consistency import (
        ProtocolSurfaceClass,
        get_protocol_surface_catalogue,
    )
    for record in get_protocol_surface_catalogue():
        if record.surface_class == ProtocolSurfaceClass.transitional:
            assert record.retirement_pathway, (
                f"Transitional surface '{record.surface_id}' has no "
                "retirement_pathway."
            )


# ---------------------------------------------------------------------------
# Projection alignment sentinel test
# ---------------------------------------------------------------------------


def test_projection_alignment_sentinel_is_available():
    pytest.importorskip(
        "fastapi", reason="projection module requires fastapi"
    )
    from core.routes.projection import CROSS_REPO_CONSISTENCY_GATES_ALIGNED_PR12
    assert "CROSS_REPO_CONSISTENCY_GATES_ALIGNED_PR12_V1" in (
        CROSS_REPO_CONSISTENCY_GATES_ALIGNED_PR12
    )
    assert "PR-12" in CROSS_REPO_CONSISTENCY_GATES_ALIGNED_PR12
