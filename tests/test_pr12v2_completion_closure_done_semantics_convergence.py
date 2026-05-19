from __future__ import annotations


def test_shared_execution_visibility_separates_authority_truth_from_done_summary():
    from core.routes.projection import _derive_shared_execution_visibility

    payload = {
        "runtime_decision_reasoning": {
            "closure_basis": {
                "task_completed": True,
                "problem_solved": True,
                "is_fully_closed": False,
                "acceptance_verdict": "accept_provisional",
            }
        },
        "operational_state_board": {
            "task_execution_visibility": {
                "task_initiated": True,
                "result_closure_established": True,
            }
        },
    }

    visibility = _derive_shared_execution_visibility(payload)

    assert visibility["completion_state"] == "closed"
    assert visibility["closure_candidate_state"] == "closed"
    assert visibility["authority_completion_truth"] is False
    assert visibility["acceptance_completion_truth"] is False
    assert visibility["operator_visible_done_summary_role"] == "operator_visible_interpretation_only"
    assert visibility["repo_mutation_completion_truth"] == "unknown"


def test_truth_acceptance_closure_contract_exposes_distinct_completion_truth_layers():
    from core.routes.projection import _build_truth_acceptance_closure_contract

    truth_payload = {
        "shared_execution_visibility": {
            "acceptance_verdict": "accept_provisional",
            "is_fully_closed": False,
            "completion_state": "closed",
            "closure_candidate_state": "closed",
            "authority_completion_truth": False,
            "operator_visible_done_summary": "completion=closed | acceptance=accept_provisional",
            "operator_visible_done_summary_role": "operator_visible_interpretation_only",
        }
    }

    contract = _build_truth_acceptance_closure_contract(
        truth_payload=truth_payload,
        cross_repo_acceptance_chain={},
    )

    acceptance = contract["acceptance_closure_truth"]
    outward = contract["outward_projection_truth"]
    assert acceptance["authority_completion_truth"] is False
    assert acceptance["acceptance_completion_truth"] is False
    assert acceptance["closure_candidate_state"] == "closed"
    assert acceptance["repo_mutation_completion_truth"] == "unknown"
    assert outward["operator_visible_done_summary_role"] == "operator_visible_interpretation_only"


def test_cross_repo_truth_boundary_contract_keeps_closure_visibility_as_candidate():
    from core.cross_repo_acceptance_chain import _build_truth_boundary_contract

    contract = _build_truth_boundary_contract(
        stages=[],
        gate={},
        overall_status="failed",
        truth_payload={
            "shared_execution_visibility": {
                "completion_state": "closed",
                "acceptance_verdict": "accept_provisional",
                "is_fully_closed": False,
                "authority_completion_truth": False,
                "operator_visible_done_summary": "completion=closed | acceptance=accept_provisional",
            }
        },
        board_payload={},
    )

    acceptance = contract["acceptance_closure_truth"]
    outward = contract["outward_projection_truth"]
    assert acceptance["closure_candidate_visible"] is True
    assert acceptance["result_closure_visible"] is True
    assert acceptance["authority_completion_truth"] is False
    assert acceptance["acceptance_completion_truth"] is False
    assert acceptance["acceptance_verdict"] == "accept_provisional"
    assert outward["operator_visible_done_summary_role"] == "operator_visible_interpretation_only"
