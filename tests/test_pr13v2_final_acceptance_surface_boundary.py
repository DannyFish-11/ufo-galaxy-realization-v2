from __future__ import annotations


def test_boundary_module_exports_pr13v2_sentinels() -> None:
    from core.final_acceptance_surface_boundary import (
        FINAL_ACCEPTANCE_SURFACE_BOUNDARY_AUTHORITY,
        FINAL_ACCEPTANCE_SURFACE_BOUNDARY_PR13V2_SENTINEL,
        FINAL_INTEGRATION_BOUNDARY_CONVERGENCE_POLICY,
        FINAL_ACCEPTANCE_SURFACE_NO_AUTHORITY_REASSEMBLY_POLICY,
    )

    assert "AUTHORITY" in FINAL_ACCEPTANCE_SURFACE_BOUNDARY_AUTHORITY
    assert "PR13V2" in FINAL_ACCEPTANCE_SURFACE_BOUNDARY_PR13V2_SENTINEL
    assert "FINAL_INTEGRATION_BOUNDARY_CONVERGENCE_POLICY" in FINAL_INTEGRATION_BOUNDARY_CONVERGENCE_POLICY
    assert "NO_AUTHORITY_REASSEMBLY" in FINAL_ACCEPTANCE_SURFACE_NO_AUTHORITY_REASSEMBLY_POLICY


def test_boundary_builder_exposes_final_integration_boundary_axes() -> None:
    from core.final_acceptance_surface_boundary import build_final_acceptance_surface_boundary

    boundary = build_final_acceptance_surface_boundary(
        surface="panel",
        consumer_role="product_panel_consumption_only",
        canonical_backend_contract="core.v2_unified_state_contract.build_control_plane_surface_contract",
        product_surface="/api/v1/panel/unified",
    )

    assert boundary["no_parallel_final_integration_framework"] is True
    assert boundary["outward_surfaces_consume_canonical_outputs_only"] is True
    integration = boundary["final_integration_boundary"]
    assert set(integration.keys()) >= {
        "center_authority",
        "subject_runtime_authority",
        "distributed_contract",
        "outward_consumption",
        "product_facing_integration",
        "operator_facing_integration",
    }
    assert integration["center_authority"]["truth_convergence"] == (
        "core.v2_android_truth_ssot.build_v2_android_truth_block"
    )
    assert integration["distributed_contract"]["contract_version"] == "distributed_subject_contract_v1"
    assert integration["outward_consumption"]["canonical_outputs_only"] is True
    assert integration["product_facing_integration"]["surface"] == "/api/v1/panel/unified"
    assert "core.android_participant_truth_ingress" in boundary["android_v2_contract_alignment"][
        "android_ingress_to_v2_truth_chain"
    ]


def test_projection_truth_acceptance_contract_exposes_final_acceptance_boundary() -> None:
    from core.routes.projection import _build_truth_acceptance_closure_contract

    contract = _build_truth_acceptance_closure_contract(
        truth_payload={},
        cross_repo_acceptance_chain={},
    )
    boundary = contract["final_acceptance_surface_boundary"]
    assert boundary["surface"] == "projection_runtime_truth_contract"
    assert boundary["no_authority_reassembly"] is True
    assert boundary["outward_surfaces_consume_canonical_outputs_only"] is True
    assert (
        boundary["canonical_runtime_governance_truth_authority"]["truth_authority"]
        == "core.v2_android_truth_ssot.build_v2_android_truth_block"
    )
    assert boundary["final_integration_boundary"]["outward_consumption"]["canonical_outputs_only"] is True


def test_operator_consumption_boundary_exposes_final_acceptance_boundary() -> None:
    from core.routes.operator import _operator_consumption_contract_boundary

    boundary = _operator_consumption_contract_boundary()
    final_boundary = boundary["final_acceptance_surface_boundary"]
    assert final_boundary["surface"] == "operator"
    assert final_boundary["consumer_role"] == "operator_board_projection_consumer_only"
    assert final_boundary["no_authority_reassembly"] is True
    assert final_boundary["final_integration_boundary"]["operator_facing_integration"]["surface"] == "operator"


def test_unified_panel_payload_serializes_final_acceptance_boundary_field() -> None:
    from core.unified_panel_aggregation import UnifiedPanelPayload

    payload = UnifiedPanelPayload()
    data = payload.to_dict()
    assert "final_acceptance_surface_boundary" in data
    assert data["final_acceptance_surface_boundary"] == {}
