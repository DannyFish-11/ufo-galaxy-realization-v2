"""Machine-verifiable tests for core.closure_phase_execution_plan."""

from __future__ import annotations

from core.closure_phase_execution_plan import (
    ANDROID_REPOSITORY,
    CLOSURE_PLAN_AUTHORITY,
    V2_REPOSITORY,
    build_closure_phase_execution_plan,
)
from core.complete_joint_system_review import REVIEW_AUTHORITY, StageGate, StageVerdict


_EXPECTED_ISSUES = {f"R{i}" for i in range(1, 14)}


def test_plan_builds_from_complete_joint_review_baseline() -> None:
    plan = build_closure_phase_execution_plan()
    assert plan.authority == CLOSURE_PLAN_AUTHORITY
    assert plan.baseline_authority == REVIEW_AUTHORITY
    assert plan.baseline_stage == StageVerdict.MID_STAGE_CONSOLIDATION


def test_plan_maps_all_remaining_issues() -> None:
    plan = build_closure_phase_execution_plan()
    assert set(plan.remaining_issue_ids) == _EXPECTED_ISSUES
    assert set(plan.issue_to_prs.keys()) == _EXPECTED_ISSUES
    for issue_id, prs in plan.issue_to_prs.items():
        assert len(prs) == 1, f"{issue_id} should map to exactly one planned PR"


def test_pr_sequence_is_explicit_and_complete() -> None:
    plan = build_closure_phase_execution_plan()
    seq = [pr.sequence for pr in plan.pr_sequence]
    assert seq == list(range(1, 14))
    planned_issue_ids = {issue_id for pr in plan.pr_sequence for issue_id in pr.issue_ids}
    assert planned_issue_ids == _EXPECTED_ISSUES


def test_pr_ownership_has_explicit_repositories() -> None:
    plan = build_closure_phase_execution_plan()
    for pr in plan.pr_sequence:
        assert pr.repositories
        for repo in pr.repositories:
            assert repo in (V2_REPOSITORY, ANDROID_REPOSITORY)


def test_stage_gate_block_grouping_exists_for_p0_p1_p2() -> None:
    plan = build_closure_phase_execution_plan()
    blocks = {block.block_id: block for block in plan.closure_blocks}
    assert blocks["B-P0-RUNTIME-CLOSURE"].stage_gate == StageGate.P0_BEFORE_RUNTIME_CLOSURE
    assert set(blocks["B-P0-RUNTIME-CLOSURE"].issue_ids) == {"R1", "R2", "R3"}
    assert blocks["B-P2-ENHANCEMENT"].stage_gate == StageGate.P2_ENHANCEMENT
    assert set(blocks["B-P2-ENHANCEMENT"].issue_ids) == {"R13"}


def test_stage_transitions_define_mid_to_late_and_late_to_near_acceptance() -> None:
    plan = build_closure_phase_execution_plan()
    transitions = {(t.from_stage, t.to_stage): t for t in plan.stage_transitions}

    mid_to_late = transitions[(StageVerdict.MID_STAGE_CONSOLIDATION, StageVerdict.LATE_INTEGRATION)]
    assert set(mid_to_late.required_issue_ids) == {"R1", "R2", "R3"}
    assert mid_to_late.required_block_ids == ["B-P0-RUNTIME-CLOSURE"]
    assert len(mid_to_late.acceptance_conditions) >= 3

    late_to_near = transitions[(StageVerdict.LATE_INTEGRATION, StageVerdict.NEAR_CLOSURE)]
    assert set(late_to_near.required_issue_ids) == {"R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"}
    assert len(late_to_near.required_block_ids) == 5
    assert len(late_to_near.acceptance_conditions) >= 3


def test_dependency_graph_matches_blocks_and_declares_ordering() -> None:
    plan = build_closure_phase_execution_plan()
    block_ids = {block.block_id for block in plan.closure_blocks}
    assert set(plan.dependency_graph.keys()) == block_ids
    for block_id, deps in plan.dependency_graph.items():
        assert isinstance(deps, list), f"{block_id} dependency entry must be a list"
        for dep in deps:
            assert dep in block_ids, f"{block_id} has unknown dependency {dep}"


def test_serialization_contains_required_top_level_keys() -> None:
    payload = build_closure_phase_execution_plan().to_dict()
    assert payload["authority"] == CLOSURE_PLAN_AUTHORITY
    assert payload["baseline_authority"] == REVIEW_AUTHORITY
    assert payload["baseline_stage"] == StageVerdict.MID_STAGE_CONSOLIDATION.value
    assert set(payload["remaining_issue_ids"]) == _EXPECTED_ISSUES
    assert len(payload["pr_sequence"]) == 13
    assert len(payload["closure_blocks"]) == 7
    assert len(payload["stage_transitions"]) == 2
