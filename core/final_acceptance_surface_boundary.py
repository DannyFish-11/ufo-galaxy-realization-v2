#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final acceptance surface boundary contract (PR13v2)."""

from __future__ import annotations

from typing import Any, Dict

FINAL_ACCEPTANCE_SURFACE_BOUNDARY_AUTHORITY = (
    "FINAL_ACCEPTANCE_SURFACE_BOUNDARY_AUTHORITY_V1: "
    "core.final_acceptance_surface_boundary defines the composition-only "
    "boundary contract for final outward/product/operator surfaces. "
    "It composes canonical runtime/governance/truth authorities and canonical "
    "backend contracts; it does not re-assemble authority truth/state/dispatch."
)

FINAL_ACCEPTANCE_SURFACE_BOUNDARY_PR13V2_SENTINEL = (
    "FINAL_ACCEPTANCE_SURFACE_BOUNDARY_PR13V2_SENTINEL::"
    "package=13::profile=final-acceptance-surface-boundary-v1"
)

FINAL_ACCEPTANCE_SURFACE_NO_AUTHORITY_REASSEMBLY_POLICY = (
    "FINAL_ACCEPTANCE_SURFACE_NO_AUTHORITY_REASSEMBLY_POLICY_V1: "
    "final composition/product-facing/operator-facing surfaces are consumption "
    "layers only and must not redefine authority truth/state/dispatch."
)


def build_final_acceptance_surface_boundary(
    *,
    surface: str,
    consumer_role: str,
    canonical_backend_contract: str,
    product_surface: str,
) -> Dict[str, Any]:
    """Build a machine-checkable boundary block for final composition surfaces."""
    return {
        "authority": FINAL_ACCEPTANCE_SURFACE_BOUNDARY_AUTHORITY,
        "sentinel": FINAL_ACCEPTANCE_SURFACE_BOUNDARY_PR13V2_SENTINEL,
        "surface": surface,
        "consumer_role": consumer_role,
        "product_surface": product_surface,
        "no_authority_reassembly": True,
        "policy": FINAL_ACCEPTANCE_SURFACE_NO_AUTHORITY_REASSEMBLY_POLICY,
        "canonical_runtime_governance_truth_authority": {
            "runtime_mainline": "core.runtime_truth_output_chain.build_output_chain_snapshot",
            "governance": "core.unified_execution_governance.build_unified_execution_governance_snapshot",
            "truth_authority": "core.v2_android_truth_ssot.build_v2_android_truth_block",
            "acceptance_closure": "core.cross_repo_acceptance_chain.build_cross_repo_acceptance_chain",
        },
        "control_plane_backend_contract": {
            "contract_builder": canonical_backend_contract,
            "operator_surface": "core.operator_surface.get_operator_surface",
            "projection_surface": "core.routes.projection._assemble_runtime_truth_payload",
        },
        "frontend_operator_board_projection_consumption": {
            "operator": "core.routes.operator",
            "projection": "core.routes.projection",
            "panel": "core.unified_panel_aggregation",
            "diagnostics": "core.cross_repo_acceptance_chain",
        },
        "android_v2_contract_alignment": {
            "android_ingress_to_v2_truth_chain": (
                "galaxy_gateway.android.handlers -> core.android_participant_truth_ingress "
                "-> core.v2_android_truth_ssot -> core.canonical_session_truth"
            ),
            "narrative_consistency_required": True,
        },
    }

