"""
tests/test_pr8_distributed_runtime_boundary.py
================================================
PR-8: Distributed Runtime Boundary Convergence — regression tests.

Locks the following invariants:

1.  Module sentinels — authority and PR8 sentinel are correctly formatted.
2.  Policy sentinels — all five policy strings are non-empty and contain
    expected keywords.
3.  DistributedRuntimeLayerRole enum — all five expected roles are present.
4.  DistributedRuntimeSurface dataclass — structure and to_dict().
5.  DistributedRuntimeBoundaryReport dataclass — structure and to_dict().
6.  Registry is non-empty and contains correct surface types.
7.  classify_distributed_surface() — found and not-found cases.
8.  get_surfaces_by_distributed_role() — filters correctly for each role.
9.  build_distributed_runtime_boundary_report() — aggregate builder
    correctness (counts and constrained_surfaces).
10. Distributed runtime main chain has exactly 5 surfaces and they are
    the canonical chain nodes.
11. Transport / relay / dispatch surfaces are NOT classified as main chain.
12. Handoff / takeover prototype surfaces are NOT classified as main chain
    and all have may_not_claim_distributed_control_plane=True.
13. Projection / diagnostics / operator surfaces are NOT main chain and
    all have may_not_claim_distributed_control_plane=True.
14. Android participation surfaces are present and two of them have
    may_not_claim_distributed_control_plane=False (they ARE first-class).
15. SIDE_PATH_MODULE_REGISTRY in canonical_execution_chain contains the
    PR-8 entries for transport, handoff/takeover, and diagnostics modules.
16. PR-8 entries in SIDE_PATH_MODULE_REGISTRY are NOT in
    MINIMAL_RUNTIME_MAINLINE_MODULES.
17. android_runtime_host module is importable and provides
    AndroidRuntimeHostRole (Android first-class node contract).
"""

from __future__ import annotations

import pytest

from core.distributed_runtime_boundary import (
    DISTRIBUTED_RUNTIME_BOUNDARY_AUTHORITY,
    DISTRIBUTED_RUNTIME_BOUNDARY_PR8_SENTINEL,
    TRANSPORT_RELAY_IS_NOT_DISTRIBUTED_CONTROL_PLANE_POLICY,
    HANDOFF_TAKEOVER_IS_PROTOTYPE_NOT_FULL_MESH_POLICY,
    PROJECTION_DIAGNOSTICS_MUST_NOT_CLAIM_RUNTIME_AUTHORITY_POLICY,
    ANDROID_IS_FIRST_CLASS_RUNTIME_HOST_NODE_POLICY,
    NO_NEW_PARALLEL_DISTRIBUTED_RUNTIME_POLICY,
    DISTRIBUTED_RUNTIME_SURFACE_REGISTRY,
    DistributedRuntimeBoundaryReport,
    DistributedRuntimeLayerRole,
    DistributedRuntimeSurface,
    build_distributed_runtime_boundary_report,
    classify_distributed_surface,
    get_distributed_runtime_registry,
    get_surfaces_by_distributed_role,
)


# ---------------------------------------------------------------------------
# 1. Module sentinels
# ---------------------------------------------------------------------------


class TestModuleSentinels:
    def test_authority_sentinel_is_nonempty_string(self):
        assert isinstance(DISTRIBUTED_RUNTIME_BOUNDARY_AUTHORITY, str)
        assert len(DISTRIBUTED_RUNTIME_BOUNDARY_AUTHORITY) > 0

    def test_authority_sentinel_contains_module_path(self):
        assert "distributed_runtime_boundary" in DISTRIBUTED_RUNTIME_BOUNDARY_AUTHORITY

    def test_pr8_sentinel_is_nonempty_string(self):
        assert isinstance(DISTRIBUTED_RUNTIME_BOUNDARY_PR8_SENTINEL, str)
        assert len(DISTRIBUTED_RUNTIME_BOUNDARY_PR8_SENTINEL) > 0

    def test_pr8_sentinel_contains_pr8_keyword(self):
        assert "pr8" in DISTRIBUTED_RUNTIME_BOUNDARY_PR8_SENTINEL.lower()


# ---------------------------------------------------------------------------
# 2. Policy sentinels
# ---------------------------------------------------------------------------


class TestPolicySentinels:
    def test_transport_relay_policy_is_nonempty(self):
        assert isinstance(
            TRANSPORT_RELAY_IS_NOT_DISTRIBUTED_CONTROL_PLANE_POLICY, str
        )
        assert len(TRANSPORT_RELAY_IS_NOT_DISTRIBUTED_CONTROL_PLANE_POLICY) > 0

    def test_transport_relay_policy_contains_keywords(self):
        policy = TRANSPORT_RELAY_IS_NOT_DISTRIBUTED_CONTROL_PLANE_POLICY.lower()
        assert "transport" in policy
        assert "control_plane" in policy or "control plane" in policy

    def test_handoff_takeover_prototype_policy_is_nonempty(self):
        assert isinstance(
            HANDOFF_TAKEOVER_IS_PROTOTYPE_NOT_FULL_MESH_POLICY, str
        )
        assert len(HANDOFF_TAKEOVER_IS_PROTOTYPE_NOT_FULL_MESH_POLICY) > 0

    def test_handoff_takeover_prototype_policy_contains_keywords(self):
        policy = HANDOFF_TAKEOVER_IS_PROTOTYPE_NOT_FULL_MESH_POLICY.lower()
        assert "prototype" in policy
        assert "mesh" in policy

    def test_projection_diagnostics_policy_is_nonempty(self):
        assert isinstance(
            PROJECTION_DIAGNOSTICS_MUST_NOT_CLAIM_RUNTIME_AUTHORITY_POLICY, str
        )
        assert len(
            PROJECTION_DIAGNOSTICS_MUST_NOT_CLAIM_RUNTIME_AUTHORITY_POLICY
        ) > 0

    def test_projection_diagnostics_policy_contains_keywords(self):
        policy = (
            PROJECTION_DIAGNOSTICS_MUST_NOT_CLAIM_RUNTIME_AUTHORITY_POLICY.lower()
        )
        assert "projection" in policy or "diagnostic" in policy
        assert "authority" in policy

    def test_android_first_class_policy_is_nonempty(self):
        assert isinstance(ANDROID_IS_FIRST_CLASS_RUNTIME_HOST_NODE_POLICY, str)
        assert len(ANDROID_IS_FIRST_CLASS_RUNTIME_HOST_NODE_POLICY) > 0

    def test_android_first_class_policy_contains_keywords(self):
        policy = ANDROID_IS_FIRST_CLASS_RUNTIME_HOST_NODE_POLICY.lower()
        assert "android" in policy
        assert "first" in policy or "runtime_host" in policy or "runtime host" in policy

    def test_no_new_parallel_runtime_policy_is_nonempty(self):
        assert isinstance(NO_NEW_PARALLEL_DISTRIBUTED_RUNTIME_POLICY, str)
        assert len(NO_NEW_PARALLEL_DISTRIBUTED_RUNTIME_POLICY) > 0

    def test_no_new_parallel_runtime_policy_contains_keywords(self):
        policy = NO_NEW_PARALLEL_DISTRIBUTED_RUNTIME_POLICY.lower()
        assert "parallel" in policy
        assert "distributed" in policy


# ---------------------------------------------------------------------------
# 3. DistributedRuntimeLayerRole enum
# ---------------------------------------------------------------------------


class TestDistributedRuntimeLayerRoleEnum:
    def test_all_five_roles_are_present(self):
        roles = {r.value for r in DistributedRuntimeLayerRole}
        assert "distributed_runtime_main_chain" in roles
        assert "transport_relay_dispatch_layer" in roles
        assert "handoff_takeover_prototype" in roles
        assert "projection_diagnostics_operator" in roles
        assert "android_participation_runtime_node" in roles

    def test_role_count_is_five(self):
        assert len(list(DistributedRuntimeLayerRole)) == 5


# ---------------------------------------------------------------------------
# 4. DistributedRuntimeSurface dataclass
# ---------------------------------------------------------------------------


class TestDistributedRuntimeSurface:
    def _sample(self) -> DistributedRuntimeSurface:
        return DistributedRuntimeSurface(
            surface_id="test_surface",
            module_path="core.test_surface",
            surface_name="Test Surface",
            distributed_role=DistributedRuntimeLayerRole.transport_relay_dispatch_layer,
            is_distributed_runtime_main_chain=False,
            may_not_claim_distributed_control_plane=True,
            notes="test notes",
        )

    def test_surface_has_required_fields(self):
        s = self._sample()
        assert s.surface_id == "test_surface"
        assert s.module_path == "core.test_surface"
        assert s.surface_name == "Test Surface"
        assert (
            s.distributed_role
            == DistributedRuntimeLayerRole.transport_relay_dispatch_layer
        )
        assert s.is_distributed_runtime_main_chain is False
        assert s.may_not_claim_distributed_control_plane is True
        assert s.notes == "test notes"

    def test_to_dict_returns_all_fields(self):
        s = self._sample()
        d = s.to_dict()
        assert d["surface_id"] == "test_surface"
        assert d["distributed_role"] == "transport_relay_dispatch_layer"
        assert d["is_distributed_runtime_main_chain"] is False
        assert d["may_not_claim_distributed_control_plane"] is True


# ---------------------------------------------------------------------------
# 5. DistributedRuntimeBoundaryReport dataclass
# ---------------------------------------------------------------------------


class TestDistributedRuntimeBoundaryReport:
    def test_report_has_required_fields(self):
        report = DistributedRuntimeBoundaryReport(
            total_surfaces=10,
            main_chain_count=5,
            transport_relay_count=2,
            handoff_takeover_prototype_count=1,
            projection_diagnostics_count=1,
            android_participation_count=1,
            constrained_surfaces=["a", "b"],
        )
        assert report.total_surfaces == 10
        assert report.main_chain_count == 5
        assert report.generated_at > 0

    def test_to_dict_returns_all_fields(self):
        report = DistributedRuntimeBoundaryReport(
            total_surfaces=3,
            main_chain_count=1,
            transport_relay_count=1,
            handoff_takeover_prototype_count=0,
            projection_diagnostics_count=1,
            android_participation_count=0,
            constrained_surfaces=["x"],
        )
        d = report.to_dict()
        assert d["total_surfaces"] == 3
        assert d["main_chain_count"] == 1
        assert d["constrained_surfaces"] == ["x"]
        assert "generated_at" in d


# ---------------------------------------------------------------------------
# 6. Registry non-empty and correct surface types
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registry_is_nonempty(self):
        registry = get_distributed_runtime_registry()
        assert len(registry) > 0

    def test_all_entries_are_distributed_runtime_surface_instances(self):
        for entry in get_distributed_runtime_registry():
            assert isinstance(entry, DistributedRuntimeSurface)

    def test_all_entries_have_nonempty_surface_id(self):
        for entry in get_distributed_runtime_registry():
            assert entry.surface_id, (
                f"surface_id must not be empty: {entry.module_path}"
            )

    def test_all_entries_have_nonempty_module_path(self):
        for entry in get_distributed_runtime_registry():
            assert entry.module_path, (
                f"module_path must not be empty: {entry.surface_id}"
            )

    def test_surface_ids_are_unique(self):
        ids = [s.surface_id for s in get_distributed_runtime_registry()]
        assert len(ids) == len(set(ids)), "Duplicate surface_id entries found"


# ---------------------------------------------------------------------------
# 7. classify_distributed_surface()
# ---------------------------------------------------------------------------


class TestClassifyDistributedSurface:
    def test_found_returns_surface(self):
        result = classify_distributed_surface("device_router_dispatch")
        assert result is not None
        assert result.surface_id == "device_router_dispatch"

    def test_not_found_returns_none(self):
        result = classify_distributed_surface("__nonexistent_surface__")
        assert result is None

    def test_android_runtime_node_is_found(self):
        result = classify_distributed_surface("android_runtime_node")
        assert result is not None
        assert (
            result.distributed_role
            == DistributedRuntimeLayerRole.distributed_runtime_main_chain
        )

    def test_takeover_tracking_is_found_as_prototype(self):
        result = classify_distributed_surface("takeover_tracking_prototype")
        assert result is not None
        assert (
            result.distributed_role
            == DistributedRuntimeLayerRole.handoff_takeover_prototype
        )


# ---------------------------------------------------------------------------
# 8. get_surfaces_by_distributed_role()
# ---------------------------------------------------------------------------


class TestGetSurfacesByRole:
    def test_main_chain_surfaces_are_nonempty(self):
        surfaces = get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.distributed_runtime_main_chain
        )
        assert len(surfaces) > 0

    def test_transport_relay_surfaces_are_nonempty(self):
        surfaces = get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.transport_relay_dispatch_layer
        )
        assert len(surfaces) > 0

    def test_handoff_takeover_prototype_surfaces_are_nonempty(self):
        surfaces = get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.handoff_takeover_prototype
        )
        assert len(surfaces) > 0

    def test_projection_diagnostics_surfaces_are_nonempty(self):
        surfaces = get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.projection_diagnostics_operator
        )
        assert len(surfaces) > 0

    def test_android_participation_surfaces_are_nonempty(self):
        surfaces = get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.android_participation_runtime_node
        )
        assert len(surfaces) > 0

    def test_filtered_surfaces_have_correct_role(self):
        for role in DistributedRuntimeLayerRole:
            for surface in get_surfaces_by_distributed_role(role):
                assert surface.distributed_role == role


# ---------------------------------------------------------------------------
# 9. build_distributed_runtime_boundary_report()
# ---------------------------------------------------------------------------


class TestBuildBoundaryReport:
    def test_report_total_matches_registry_size(self):
        report = build_distributed_runtime_boundary_report()
        assert report.total_surfaces == len(DISTRIBUTED_RUNTIME_SURFACE_REGISTRY)

    def test_report_main_chain_count_is_positive(self):
        report = build_distributed_runtime_boundary_report()
        assert report.main_chain_count > 0

    def test_report_count_sum_equals_total(self):
        report = build_distributed_runtime_boundary_report()
        summed = (
            report.main_chain_count
            + report.transport_relay_count
            + report.handoff_takeover_prototype_count
            + report.projection_diagnostics_count
            + report.android_participation_count
        )
        assert summed == report.total_surfaces

    def test_report_constrained_surfaces_nonempty(self):
        report = build_distributed_runtime_boundary_report()
        assert len(report.constrained_surfaces) > 0

    def test_report_generated_at_is_recent(self):
        import time
        before = time.time()
        report = build_distributed_runtime_boundary_report()
        after = time.time()
        assert before <= report.generated_at <= after + 1.0

    def test_report_to_dict_is_complete(self):
        report = build_distributed_runtime_boundary_report()
        d = report.to_dict()
        required_keys = {
            "total_surfaces",
            "main_chain_count",
            "transport_relay_count",
            "handoff_takeover_prototype_count",
            "projection_diagnostics_count",
            "android_participation_count",
            "constrained_surfaces",
            "generated_at",
        }
        assert required_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# 10. Distributed runtime main chain — exactly 5 surfaces, correct modules
# ---------------------------------------------------------------------------


class TestMainChainExactComposition:
    def _main_chain_surfaces(self):
        return get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.distributed_runtime_main_chain
        )

    def test_main_chain_has_exactly_five_surfaces(self):
        assert len(self._main_chain_surfaces()) == 5

    def test_main_chain_includes_desktop_presence_runtime(self):
        ids = {s.surface_id for s in self._main_chain_surfaces()}
        assert "desktop_presence_runtime_shell" in ids

    def test_main_chain_includes_openclawd(self):
        ids = {s.surface_id for s in self._main_chain_surfaces()}
        assert "openclawd_subject_core" in ids

    def test_main_chain_includes_command_router(self):
        ids = {s.surface_id for s in self._main_chain_surfaces()}
        assert "command_router_cross_device_loop" in ids

    def test_main_chain_includes_device_router(self):
        ids = {s.surface_id for s in self._main_chain_surfaces()}
        assert "device_router_dispatch" in ids

    def test_main_chain_includes_android_runtime_node(self):
        ids = {s.surface_id for s in self._main_chain_surfaces()}
        assert "android_runtime_node" in ids

    def test_main_chain_surfaces_have_is_distributed_runtime_main_chain_true(self):
        for s in self._main_chain_surfaces():
            assert s.is_distributed_runtime_main_chain is True, (
                f"{s.surface_id} should have is_distributed_runtime_main_chain=True"
            )

    def test_main_chain_surfaces_have_may_not_claim_false(self):
        for s in self._main_chain_surfaces():
            assert s.may_not_claim_distributed_control_plane is False, (
                f"{s.surface_id} is main chain — must have "
                "may_not_claim_distributed_control_plane=False"
            )


# ---------------------------------------------------------------------------
# 11. Transport / relay surfaces are NOT classified as main chain
# ---------------------------------------------------------------------------


class TestTransportRelayIsNotMainChain:
    def _transport_surfaces(self):
        return get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.transport_relay_dispatch_layer
        )

    def test_transport_surfaces_are_not_main_chain(self):
        for s in self._transport_surfaces():
            assert s.is_distributed_runtime_main_chain is False, (
                f"{s.surface_id} is transport/relay — must NOT be main chain"
            )

    def test_agent_bridge_is_transport_relay(self):
        surface = classify_distributed_surface("agent_bridge_handoff_relay")
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.transport_relay_dispatch_layer
        )

    def test_transport_surfaces_have_may_not_claim_true(self):
        for s in self._transport_surfaces():
            assert s.may_not_claim_distributed_control_plane is True, (
                f"{s.surface_id} is transport/relay — must have "
                "may_not_claim_distributed_control_plane=True"
            )


# ---------------------------------------------------------------------------
# 12. Handoff / takeover prototype surfaces: NOT main chain, all constrained
# ---------------------------------------------------------------------------


class TestHandoffTakeoverPrototypes:
    def _prototype_surfaces(self):
        return get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.handoff_takeover_prototype
        )

    def test_prototypes_are_not_main_chain(self):
        for s in self._prototype_surfaces():
            assert s.is_distributed_runtime_main_chain is False, (
                f"{s.surface_id} is prototype — must NOT be main chain"
            )

    def test_all_prototypes_have_may_not_claim_true(self):
        for s in self._prototype_surfaces():
            assert s.may_not_claim_distributed_control_plane is True, (
                f"{s.surface_id} is handoff/takeover prototype — "
                "must have may_not_claim_distributed_control_plane=True"
            )

    def test_takeover_tracking_is_prototype(self):
        surface = classify_distributed_surface("takeover_tracking_prototype")
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.handoff_takeover_prototype
        )

    def test_canonical_handoff_path_is_prototype(self):
        surface = classify_distributed_surface("canonical_handoff_path")
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.handoff_takeover_prototype
        )

    def test_android_delegated_lifecycle_coordinator_is_prototype(self):
        surface = classify_distributed_surface(
            "android_delegated_runtime_lifecycle_coordinator"
        )
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.handoff_takeover_prototype
        )

    def test_handoff_envelope_v2_contract_is_prototype(self):
        surface = classify_distributed_surface("handoff_envelope_v2_contract")
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.handoff_takeover_prototype
        )


# ---------------------------------------------------------------------------
# 13. Projection / diagnostics surfaces: NOT main chain, all constrained
# ---------------------------------------------------------------------------


class TestProjectionDiagnosticsLayer:
    def _proj_surfaces(self):
        return get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.projection_diagnostics_operator
        )

    def test_proj_surfaces_are_not_main_chain(self):
        for s in self._proj_surfaces():
            assert s.is_distributed_runtime_main_chain is False

    def test_all_proj_surfaces_have_may_not_claim_true(self):
        for s in self._proj_surfaces():
            assert s.may_not_claim_distributed_control_plane is True, (
                f"{s.surface_id} is projection/diagnostics — "
                "must have may_not_claim_distributed_control_plane=True"
            )

    def test_distributed_release_gate_is_diagnostics(self):
        surface = classify_distributed_surface("distributed_release_gate_skeleton")
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.projection_diagnostics_operator
        )

    def test_center_distributed_review_is_diagnostics(self):
        surface = classify_distributed_surface(
            "center_distributed_agent_system_review"
        )
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.projection_diagnostics_operator
        )

    def test_android_delegated_runtime_audit_is_diagnostics(self):
        surface = classify_distributed_surface("android_delegated_runtime_audit")
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.projection_diagnostics_operator
        )


# ---------------------------------------------------------------------------
# 14. Android participation surfaces — first-class node status
# ---------------------------------------------------------------------------


class TestAndroidParticipationSurfaces:
    def _android_surfaces(self):
        return get_surfaces_by_distributed_role(
            DistributedRuntimeLayerRole.android_participation_runtime_node
        )

    def test_android_participation_surfaces_are_nonempty(self):
        assert len(self._android_surfaces()) > 0

    def test_android_participation_surfaces_are_not_main_chain(self):
        for s in self._android_surfaces():
            assert s.is_distributed_runtime_main_chain is False

    def test_android_runtime_host_classification_has_may_not_claim_false(self):
        surface = classify_distributed_surface("android_runtime_host_classification")
        assert surface is not None
        assert surface.may_not_claim_distributed_control_plane is False, (
            "android_runtime_host_classification is a first-class node "
            "classification surface — may_not_claim_distributed_control_plane "
            "must be False (it IS the authority for Android node status)"
        )

    def test_android_gateway_handlers_are_present(self):
        surface = classify_distributed_surface("android_gateway_handlers")
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.android_participation_runtime_node
        )

    def test_android_originated_authority_boundary_is_present(self):
        surface = classify_distributed_surface(
            "android_originated_authority_boundary"
        )
        assert surface is not None
        assert (
            surface.distributed_role
            == DistributedRuntimeLayerRole.android_participation_runtime_node
        )


# ---------------------------------------------------------------------------
# 15. SIDE_PATH_MODULE_REGISTRY contains PR-8 entries
# ---------------------------------------------------------------------------


class TestCanonicalExecutionChainPr8Entries:
    def _registry(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        return SIDE_PATH_MODULE_REGISTRY

    def test_delegated_runtime_dispatch_intent_is_registered(self):
        registry = self._registry()
        assert "core.delegated_runtime_dispatch_intent" in registry
        assert registry["core.delegated_runtime_dispatch_intent"] == (
            "dispatch_intent_helper"
        )

    def test_canonical_handoff_path_is_registered_as_prototype(self):
        registry = self._registry()
        assert "core.canonical_handoff_path" in registry
        assert "prototype" in registry["core.canonical_handoff_path"]

    def test_takeover_tracking_is_registered_as_prototype(self):
        registry = self._registry()
        assert "core.takeover_tracking" in registry
        assert "prototype" in registry["core.takeover_tracking"]

    def test_android_handoff_v2_response_ingress_is_registered(self):
        registry = self._registry()
        assert "core.android_handoff_v2_response_ingress" in registry
        assert "prototype" in registry["core.android_handoff_v2_response_ingress"]

    def test_android_delegated_lifecycle_coordinator_is_registered(self):
        registry = self._registry()
        assert "core.android_delegated_runtime_lifecycle_coordinator" in registry
        assert "prototype" in (
            registry["core.android_delegated_runtime_lifecycle_coordinator"]
        )

    def test_handoff_envelope_v2_is_registered(self):
        registry = self._registry()
        assert "contracts.handoff_envelope_v2" in registry
        assert "prototype" in registry["contracts.handoff_envelope_v2"]

    def test_android_delegated_runtime_audit_is_registered_as_diagnostics(self):
        registry = self._registry()
        assert "core.android_delegated_runtime_audit" in registry
        assert "read_only" in (
            registry["core.android_delegated_runtime_audit"]
        )

    def test_distributed_release_gate_skeleton_is_registered(self):
        registry = self._registry()
        assert "core.distributed_release_gate_skeleton" in registry
        assert "diagnostic" in registry["core.distributed_release_gate_skeleton"]

    def test_center_distributed_review_is_registered(self):
        registry = self._registry()
        assert "core.center_distributed_agent_system_review" in registry
        assert "operator" in (
            registry["core.center_distributed_agent_system_review"].lower()
        )

    def test_flow_level_truth_ownership_is_registered(self):
        registry = self._registry()
        assert "core.flow_level_truth_ownership" in registry
        assert "diagnostics" in registry["core.flow_level_truth_ownership"]

    def test_ownership_transfer_proof_quality_is_registered(self):
        registry = self._registry()
        assert "core.ownership_transfer_proof_quality" in registry
        assert "diagnostics" in registry["core.ownership_transfer_proof_quality"]


# ---------------------------------------------------------------------------
# 16. PR-8 side-path entries are NOT in MINIMAL_RUNTIME_MAINLINE_MODULES
# ---------------------------------------------------------------------------


class TestPr8EntriesNotInMainline:
    def test_pr8_side_path_entries_are_not_in_mainline(self):
        from core.canonical_execution_chain import (
            MINIMAL_RUNTIME_MAINLINE_MODULES,
            SIDE_PATH_MODULE_REGISTRY,
        )
        pr8_entries = [
            "core.delegated_runtime_dispatch_intent",
            "core.canonical_handoff_path",
            "core.takeover_tracking",
            "core.android_handoff_v2_response_ingress",
            "core.android_delegated_runtime_lifecycle_coordinator",
            "contracts.handoff_envelope_v2",
            "core.android_delegated_runtime_audit",
            "core.distributed_release_gate_skeleton",
            "core.center_distributed_agent_system_review",
            "core.flow_level_truth_ownership",
            "core.ownership_transfer_proof_quality",
        ]
        for entry in pr8_entries:
            assert entry in SIDE_PATH_MODULE_REGISTRY, (
                f"PR-8 entry {entry!r} must be in SIDE_PATH_MODULE_REGISTRY"
            )
            assert entry not in MINIMAL_RUNTIME_MAINLINE_MODULES, (
                f"PR-8 side-path entry {entry!r} must NOT be in "
                "MINIMAL_RUNTIME_MAINLINE_MODULES"
            )


# ---------------------------------------------------------------------------
# 17. android_runtime_host module is importable and provides key symbols
# ---------------------------------------------------------------------------


class TestAndroidRuntimeHostContract:
    def test_android_runtime_host_is_importable(self):
        from core.android_runtime_host import AndroidRuntimeHostRole
        assert AndroidRuntimeHostRole is not None

    def test_android_runtime_host_role_has_full_runtime_host(self):
        from core.android_runtime_host import AndroidRuntimeHostRole
        roles = {r.value for r in AndroidRuntimeHostRole}
        # Must have some form of 'full' or 'runtime_host' role
        assert any(
            "full" in r.lower() or "runtime" in r.lower()
            for r in roles
        ), f"AndroidRuntimeHostRole has no first-class runtime role: {roles}"

    def test_classify_android_runtime_host_is_callable(self):
        from core.android_runtime_host import classify_android_runtime_host
        assert callable(classify_android_runtime_host)
