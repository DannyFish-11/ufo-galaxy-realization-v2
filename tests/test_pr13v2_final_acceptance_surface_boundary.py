from __future__ import annotations


def test_boundary_module_exports_pr13v2_sentinels() -> None:
    from core.final_acceptance_surface_boundary import (
        FINAL_ACCEPTANCE_SURFACE_BOUNDARY_AUTHORITY,
        FINAL_ACCEPTANCE_SURFACE_BOUNDARY_PR13V2_SENTINEL,
        FINAL_ACCEPTANCE_SURFACE_NO_AUTHORITY_REASSEMBLY_POLICY,
    )

    assert "AUTHORITY" in FINAL_ACCEPTANCE_SURFACE_BOUNDARY_AUTHORITY
    assert "PR13V2" in FINAL_ACCEPTANCE_SURFACE_BOUNDARY_PR13V2_SENTINEL
    assert "NO_AUTHORITY_REASSEMBLY" in FINAL_ACCEPTANCE_SURFACE_NO_AUTHORITY_REASSEMBLY_POLICY


def test_projection_truth_acceptance_contract_exposes_final_acceptance_boundary() -> None:
    from core.routes.projection import _build_truth_acceptance_closure_contract

    contract = _build_truth_acceptance_closure_contract(
        truth_payload={},
        cross_repo_acceptance_chain={},
    )
    boundary = contract["final_acceptance_surface_boundary"]
    assert boundary["surface"] == "projection_runtime_truth_contract"
    assert boundary["no_authority_reassembly"] is True
    assert (
        boundary["canonical_runtime_governance_truth_authority"]["truth_authority"]
        == "core.v2_android_truth_ssot.build_v2_android_truth_block"
    )


def test_operator_consumption_boundary_exposes_final_acceptance_boundary() -> None:
    from core.routes.operator import _operator_consumption_contract_boundary

    boundary = _operator_consumption_contract_boundary()
    final_boundary = boundary["final_acceptance_surface_boundary"]
    assert final_boundary["surface"] == "operator"
    assert final_boundary["consumer_role"] == "operator_board_projection_consumer_only"
    assert final_boundary["no_authority_reassembly"] is True


def test_unified_panel_payload_serializes_final_acceptance_boundary_field() -> None:
    from core.unified_panel_aggregation import UnifiedPanelPayload

    payload = UnifiedPanelPayload()
    data = payload.to_dict()
    assert "final_acceptance_surface_boundary" in data
    assert data["final_acceptance_surface_boundary"] == {}
