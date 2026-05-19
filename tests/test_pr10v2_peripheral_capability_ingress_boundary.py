#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-10V2 peripheral capability ingress boundary regression tests."""

from __future__ import annotations

from core.peripheral_capability_boundary import (
    ANDROID_LINK_MUST_FLOW_THROUGH_CANONICAL_CHAIN_POLICY,
    NO_NEW_PARALLEL_PERIPHERAL_RUNTIME_POLICY,
    OUTWARD_PROJECTION_OPERATOR_ARE_CONSUMERS_NOT_GOVERNANCE_POLICY,
    PERIPHERAL_CAPABILITY_BOUNDARY_AUTHORITY,
    PERIPHERAL_CAPABILITY_BOUNDARY_PR10V2_SENTINEL,
    PERIPHERAL_CAPABILITY_SURFACE_REGISTRY,
    PERIPHERAL_LAYERS_ARE_INGRESS_NOT_RUNTIME_AUTHORITY_POLICY,
    SPECIALISTS_AS_TOOLS_SUBLAYER_NOT_PARALLEL_MAINLINE_POLICY,
    PeripheralCapabilityRole,
    build_peripheral_capability_boundary_snapshot,
    classify_peripheral_capability_surface,
    get_android_integration_surface_paths,
    get_surfaces_by_peripheral_role,
)


def test_pr10v2_authority_and_sentinel_strings() -> None:
    assert "peripheral_capability_boundary" in PERIPHERAL_CAPABILITY_BOUNDARY_AUTHORITY
    assert "pr10v2" in PERIPHERAL_CAPABILITY_BOUNDARY_PR10V2_SENTINEL.lower()


def test_policy_sentinels_are_non_empty() -> None:
    for policy in (
        PERIPHERAL_LAYERS_ARE_INGRESS_NOT_RUNTIME_AUTHORITY_POLICY,
        SPECIALISTS_AS_TOOLS_SUBLAYER_NOT_PARALLEL_MAINLINE_POLICY,
        OUTWARD_PROJECTION_OPERATOR_ARE_CONSUMERS_NOT_GOVERNANCE_POLICY,
        ANDROID_LINK_MUST_FLOW_THROUGH_CANONICAL_CHAIN_POLICY,
        NO_NEW_PARALLEL_PERIPHERAL_RUNTIME_POLICY,
    ):
        assert isinstance(policy, str)
        assert policy


def test_role_registry_covers_all_declared_roles() -> None:
    roles = {surface.role for surface in PERIPHERAL_CAPABILITY_SURFACE_REGISTRY}
    assert set(PeripheralCapabilityRole) <= roles


def test_mainline_surfaces_remain_authorities() -> None:
    mainline = get_surfaces_by_peripheral_role(
        PeripheralCapabilityRole.runtime_mainline_authority
    )
    module_paths = {surface.module_path for surface in mainline}
    assert "core.desktop_presence_runtime" in module_paths
    assert "core.openclawd" in module_paths
    assert "core.command_router" in module_paths
    assert "galaxy_gateway.device_router" in module_paths
    assert all(not surface.may_not_claim_runtime_authority for surface in mainline)


def test_specialists_as_tools_and_peripheral_ingress_are_not_parallel_control() -> None:
    specialists = get_surfaces_by_peripheral_role(
        PeripheralCapabilityRole.specialists_as_tools_sublayer
    )
    ingress = get_surfaces_by_peripheral_role(
        PeripheralCapabilityRole.peripheral_capability_ingress
    )
    assert any(surface.module_path == "core.agent.kernel" for surface in specialists)
    assert any(surface.module_path == "core.multimodal.ingest_runtime" for surface in ingress)
    assert any(surface.module_path == "core.continuation_rebind_registry" for surface in ingress)
    assert any(surface.module_path == "galaxy_gateway.android_bridge" for surface in ingress)
    assert all(surface.may_not_claim_runtime_authority for surface in specialists + ingress)


def test_projection_operator_surfaces_remain_consumers() -> None:
    projection = get_surfaces_by_peripheral_role(
        PeripheralCapabilityRole.outward_projection_operator_surface
    )
    module_paths = {surface.module_path for surface in projection}
    assert "core.routes.projection" in module_paths
    assert "core.pr4_operator_action_governance" in module_paths
    assert all(surface.may_not_claim_runtime_authority for surface in projection)


def test_classifier_supports_surface_id_and_module_path() -> None:
    assert classify_peripheral_capability_surface("multimodal_ingest_runtime") == (
        PeripheralCapabilityRole.peripheral_capability_ingress.value
    )
    assert classify_peripheral_capability_surface("core.agent.kernel") == (
        PeripheralCapabilityRole.specialists_as_tools_sublayer.value
    )
    assert classify_peripheral_capability_surface("unknown.module") == "unknown"


def test_android_link_surfaces_reference_android_and_v2_real_chain() -> None:
    link_surfaces = get_android_integration_surface_paths()
    assert "galaxy_gateway.android_bridge" in link_surfaces
    assert "galaxy_gateway.device_router" in link_surfaces
    assert "android.GalaxyWebSocketClient" in link_surfaces
    assert "android.GalaxyConnectionService" in link_surfaces
    assert "android.RuntimeController" in link_surfaces


def test_snapshot_exposes_role_counts_and_android_link_surfaces() -> None:
    snapshot = build_peripheral_capability_boundary_snapshot()
    assert snapshot["authority"] == PERIPHERAL_CAPABILITY_BOUNDARY_AUTHORITY
    assert snapshot["sentinel"] == PERIPHERAL_CAPABILITY_BOUNDARY_PR10V2_SENTINEL
    assert snapshot["total_surfaces"] >= 10
    assert snapshot["by_role"][PeripheralCapabilityRole.peripheral_capability_ingress.value] >= 3
    assert "android.GalaxyWebSocketClient" in snapshot["android_v2_link_surfaces"]


def test_canonical_execution_chain_marks_peripheral_ingress_side_paths() -> None:
    from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY

    assert (
        SIDE_PATH_MODULE_REGISTRY["core.multimodal.ingest_runtime"]
        == "peripheral_multimodal_ingress_shell_adapter"
    )
    assert (
        SIDE_PATH_MODULE_REGISTRY["core.multimodal.ingress_bus"]
        == "peripheral_multimodal_ingress_transport"
    )
    assert (
        SIDE_PATH_MODULE_REGISTRY["core.continuation_rebind_registry"]
        == "continuation_rebind_ingress_adapter"
    )
    assert (
        SIDE_PATH_MODULE_REGISTRY["galaxy_gateway.android_bridge"]
        == "android_protocol_handoff_ingress_adapter"
    )


def test_capability_registry_annotations_include_ingress_boundary_contract() -> None:
    from core.agent.capability_registry import CapabilityItem, CapabilityRegistry

    registry = CapabilityRegistry.get_instance()
    item_name = "skill__pr10v2_peripheral_boundary_test"
    registry.inject_item(
        CapabilityItem(
            name=item_name,
            description="test item",
            source="skill",
            source_id="pr10v2",
            parameters={"type": "object", "properties": {}},
            available=True,
        )
    )
    stored = registry.get(item_name)
    assert stored is not None
    contract = dict((stored.metadata or {}).get("ingress_boundary_contract") or {})
    assert contract.get("role") == "capability_ingress_surface"
    assert contract.get("may_not_claim_runtime_authority") is True
    assert "galaxy_gateway.device_router.DeviceRouter" in contract.get(
        "runtime_mainline_authority", []
    )
    registry.eject(item_name)


def test_projection_foundational_truth_includes_peripheral_boundary_snapshot() -> None:
    from core.routes.projection import _build_foundational_system_truth

    foundational = _build_foundational_system_truth({})
    boundary = dict(foundational.get("peripheral_capability_ingress_boundary") or {})
    assert boundary.get("authority") == PERIPHERAL_CAPABILITY_BOUNDARY_AUTHORITY
    assert boundary.get("sentinel") == PERIPHERAL_CAPABILITY_BOUNDARY_PR10V2_SENTINEL
    assert "core.peripheral_capability_boundary.build_peripheral_capability_boundary_snapshot" in foundational.get(
        "source_of_truth_refs", []
    )
