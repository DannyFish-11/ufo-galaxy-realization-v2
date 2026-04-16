"""tests/test_pr5_device_node_domain_governance.py
===================================================
PR-5: Device/node domain governance — test suite.

Tests cover:
- Module authority sentinels and PR-5 sentinel
- Policy sentinels are non-empty strings and mention expected keywords
- DomainKind enum completeness
- DeviceDomainResponsibility enum completeness
- NodeDomainResponsibility enum completeness
- BridgeRelationshipKind enum completeness
- RegistrySurfaceDomain enum completeness
- RegistrySurfaceRole enum completeness
- DomainDefinition dataclass structure and to_dict()
- BridgeRelationship dataclass structure and to_dict()
- RegistrySurfaceClassification dataclass structure and to_dict()
- DomainGovernanceSnapshot dataclass structure and to_dict()
- get_device_domain_definition() returns correct device domain definition
- get_node_domain_definition() returns correct node domain definition
- get_bridge_relationships() returns all three bridge kinds
- get_bridge_relationship() by kind lookup
- classify_registry_surface() surface lookup
- get_surfaces_by_domain() domain filter
- get_authoritative_surfaces() filter
- build_domain_governance_snapshot() aggregate builder
- get_governance_summary() compact summary
- Projection alignment sentinel
- Domain separation invariants (devices are not nodes, nodes are not devices)
"""

from __future__ import annotations

import pytest

from core.device_node_domain_governance import (
    BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY,
    CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY,
    DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY,
    DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY,
    DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL,
    NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY,
    BridgeRelationship,
    BridgeRelationshipKind,
    DeviceDomainResponsibility,
    DomainDefinition,
    DomainGovernanceSnapshot,
    DomainKind,
    NodeDomainResponsibility,
    RegistrySurfaceClassification,
    RegistrySurfaceDomain,
    RegistrySurfaceRole,
    build_domain_governance_snapshot,
    classify_registry_surface,
    get_authoritative_surfaces,
    get_bridge_relationship,
    get_bridge_relationships,
    get_device_domain_definition,
    get_governance_summary,
    get_node_domain_definition,
    get_surfaces_by_domain,
)


# ---------------------------------------------------------------------------
# Authority and policy sentinel tests
# ---------------------------------------------------------------------------


def test_authority_sentinel_format():
    assert DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY.startswith(
        "DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY::"
    )
    assert "core.device_node_domain_governance" in DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY


def test_pr5_sentinel_format():
    assert DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL.startswith(
        "DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL::"
    )
    assert "PR5" in DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL
    assert "device-node-domain-governance-v1" in DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL
    assert "core.device_node_domain_governance" in DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL


def test_policy_sentinels_are_non_empty_strings():
    for sentinel in [
        DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY,
        NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY,
        BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY,
        CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY,
    ]:
        assert isinstance(sentinel, str) and len(sentinel) > 0


def test_device_domain_policy_mentions_identity():
    assert "identity" in DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY.lower()


def test_device_domain_policy_mentions_ssot():
    assert "ssot" in DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY.lower()


def test_node_domain_policy_mentions_dispatch():
    assert "dispatch" in NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY.lower()


def test_bridge_policy_mentions_not_collapse():
    policy = BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY.lower()
    assert "bridge" in policy
    assert "collapse" in policy


def test_center_governs_policy_mentions_equivalence():
    policy = CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY.lower()
    assert "equivalence" in policy
    assert "center" in policy


# ---------------------------------------------------------------------------
# DomainKind enum tests
# ---------------------------------------------------------------------------


def test_domain_kind_has_two_values():
    assert len(set(DomainKind)) == 2


def test_domain_kind_contains_device_and_node():
    values = {k.value for k in DomainKind}
    assert values == {"device", "node"}


# ---------------------------------------------------------------------------
# DeviceDomainResponsibility enum tests
# ---------------------------------------------------------------------------


def test_device_domain_responsibility_has_seven_values():
    assert len(set(DeviceDomainResponsibility)) == 7


def test_device_domain_responsibility_contains_expected_values():
    values = {r.value for r in DeviceDomainResponsibility}
    assert "device_identity" in values
    assert "runtime_hosting" in values
    assert "connectivity" in values
    assert "registration" in values
    assert "ssot_aligned_state" in values
    assert "presence_lifecycle" in values
    assert "capability_evidence" in values


def test_device_domain_responsibility_values_are_lowercase():
    for r in DeviceDomainResponsibility:
        assert r.value == r.value.lower()


# ---------------------------------------------------------------------------
# NodeDomainResponsibility enum tests
# ---------------------------------------------------------------------------


def test_node_domain_responsibility_has_eight_values():
    assert len(set(NodeDomainResponsibility)) == 8


def test_node_domain_responsibility_contains_expected_values():
    values = {r.value for r in NodeDomainResponsibility}
    assert "executable_unit_registration" in values
    assert "capability_hosting" in values
    assert "orchestration_targeting" in values
    assert "dispatch_semantics" in values
    assert "invocation_governance" in values
    assert "boundary_enforcement" in values
    assert "execution_lifecycle" in values
    assert "capability_sync" in values


def test_node_domain_responsibility_values_are_lowercase():
    for r in NodeDomainResponsibility:
        assert r.value == r.value.lower()


# ---------------------------------------------------------------------------
# BridgeRelationshipKind enum tests
# ---------------------------------------------------------------------------


def test_bridge_relationship_kind_has_three_values():
    assert len(set(BridgeRelationshipKind)) == 3


def test_bridge_relationship_kind_contains_expected_values():
    values = {k.value for k in BridgeRelationshipKind}
    assert values == {"runtime_host", "capability_host", "dispatch_target"}


# ---------------------------------------------------------------------------
# RegistrySurfaceDomain enum tests
# ---------------------------------------------------------------------------


def test_registry_surface_domain_has_four_values():
    assert len(set(RegistrySurfaceDomain)) == 4


def test_registry_surface_domain_contains_expected_values():
    values = {d.value for d in RegistrySurfaceDomain}
    assert "device" in values
    assert "node" in values
    assert "bridge" in values
    assert "shared_projection" in values


# ---------------------------------------------------------------------------
# RegistrySurfaceRole enum tests
# ---------------------------------------------------------------------------


def test_registry_surface_role_has_seven_values():
    assert len(set(RegistrySurfaceRole)) == 7


def test_registry_surface_role_contains_expected_values():
    values = {r.value for r in RegistrySurfaceRole}
    assert "ssot" in values
    assert "canonical_registry" in values
    assert "projection" in values
    assert "cache" in values
    assert "compat_facade" in values
    assert "adapter" in values
    assert "bridge" in values


# ---------------------------------------------------------------------------
# DomainDefinition dataclass tests
# ---------------------------------------------------------------------------


def test_domain_definition_to_dict_has_required_keys():
    defn = get_device_domain_definition()
    d = defn.to_dict()
    assert "domain" in d
    assert "responsibilities" in d
    assert "authority_surfaces" in d
    assert "description" in d
    assert "lifecycle_kind" in d
    assert "authority" in d


def test_domain_definition_to_dict_domain_is_string():
    d = get_device_domain_definition().to_dict()
    assert isinstance(d["domain"], str)


def test_domain_definition_to_dict_responsibilities_is_list():
    d = get_device_domain_definition().to_dict()
    assert isinstance(d["responsibilities"], list)
    assert len(d["responsibilities"]) > 0


def test_domain_definition_to_dict_authority_surfaces_is_list():
    d = get_device_domain_definition().to_dict()
    assert isinstance(d["authority_surfaces"], list)
    assert len(d["authority_surfaces"]) > 0


# ---------------------------------------------------------------------------
# BridgeRelationship dataclass tests
# ---------------------------------------------------------------------------


def test_bridge_relationship_to_dict_has_required_keys():
    bridges = get_bridge_relationships()
    assert len(bridges) > 0
    for bridge in bridges:
        d = bridge.to_dict()
        assert "kind" in d
        assert "center_surface" in d
        assert "device_domain_role" in d
        assert "node_domain_role" in d
        assert "description" in d
        assert "android_relevance" in d


def test_bridge_relationship_kind_is_string_in_dict():
    for bridge in get_bridge_relationships():
        d = bridge.to_dict()
        assert isinstance(d["kind"], str)


def test_bridge_relationship_center_surface_is_list():
    for bridge in get_bridge_relationships():
        d = bridge.to_dict()
        assert isinstance(d["center_surface"], list)
        assert len(d["center_surface"]) > 0


# ---------------------------------------------------------------------------
# RegistrySurfaceClassification dataclass tests
# ---------------------------------------------------------------------------


def test_registry_surface_classification_to_dict_has_required_keys():
    surfaces = get_authoritative_surfaces()
    assert len(surfaces) > 0
    for surface in surfaces:
        d = surface.to_dict()
        assert "module_path" in d
        assert "surface_name" in d
        assert "domain" in d
        assert "role" in d
        assert "notes" in d
        assert "is_authoritative" in d


def test_authoritative_surfaces_all_have_is_authoritative_true():
    for surface in get_authoritative_surfaces():
        assert surface.is_authoritative is True


# ---------------------------------------------------------------------------
# get_device_domain_definition() tests
# ---------------------------------------------------------------------------


def test_get_device_domain_definition_returns_device_domain():
    defn = get_device_domain_definition()
    assert defn.domain == DomainKind.device


def test_get_device_domain_definition_lifecycle_is_presence():
    defn = get_device_domain_definition()
    assert "presence" in defn.lifecycle_kind


def test_get_device_domain_definition_has_udm_surface():
    defn = get_device_domain_definition()
    surfaces_str = " ".join(defn.authority_surfaces)
    assert "UnifiedDeviceManager" in surfaces_str or "unified_device_manager" in surfaces_str


def test_get_device_domain_definition_responsibilities_include_identity():
    defn = get_device_domain_definition()
    assert "device_identity" in defn.responsibilities


def test_get_device_domain_definition_responsibilities_include_presence_lifecycle():
    defn = get_device_domain_definition()
    assert "presence_lifecycle" in defn.responsibilities


def test_get_device_domain_definition_description_mentions_ssot():
    defn = get_device_domain_definition()
    assert "SSOT" in defn.description or "ssot" in defn.description.lower()


# ---------------------------------------------------------------------------
# get_node_domain_definition() tests
# ---------------------------------------------------------------------------


def test_get_node_domain_definition_returns_node_domain():
    defn = get_node_domain_definition()
    assert defn.domain == DomainKind.node


def test_get_node_domain_definition_lifecycle_is_execution():
    defn = get_node_domain_definition()
    assert "execution" in defn.lifecycle_kind


def test_get_node_domain_definition_has_node_fabric_registry():
    defn = get_node_domain_definition()
    surfaces_str = " ".join(defn.authority_surfaces)
    assert "NodeFabricRegistry" in surfaces_str or "node_fabric_registry" in surfaces_str


def test_get_node_domain_definition_responsibilities_include_dispatch():
    defn = get_node_domain_definition()
    assert "dispatch_semantics" in defn.responsibilities


def test_get_node_domain_definition_responsibilities_include_invocation_governance():
    defn = get_node_domain_definition()
    assert "invocation_governance" in defn.responsibilities


def test_get_node_domain_definition_description_does_not_claim_device_identity():
    defn = get_node_domain_definition()
    # The node domain does not own device identity
    assert "device identity" not in defn.description.lower() or "does not own" in defn.description.lower()


# ---------------------------------------------------------------------------
# get_bridge_relationships() tests
# ---------------------------------------------------------------------------


def test_get_bridge_relationships_returns_three_bridges():
    bridges = get_bridge_relationships()
    assert len(bridges) == 3


def test_get_bridge_relationships_contains_all_three_kinds():
    kinds = {b.kind for b in get_bridge_relationships()}
    assert BridgeRelationshipKind.runtime_host in kinds
    assert BridgeRelationshipKind.capability_host in kinds
    assert BridgeRelationshipKind.dispatch_target in kinds


def test_get_bridge_relationships_returns_new_list_each_call():
    bridges1 = get_bridge_relationships()
    bridges2 = get_bridge_relationships()
    assert bridges1 is not bridges2


# ---------------------------------------------------------------------------
# get_bridge_relationship() tests
# ---------------------------------------------------------------------------


def test_get_bridge_relationship_runtime_host():
    bridge = get_bridge_relationship(BridgeRelationshipKind.runtime_host)
    assert bridge is not None
    assert bridge.kind == BridgeRelationshipKind.runtime_host


def test_get_bridge_relationship_capability_host():
    bridge = get_bridge_relationship(BridgeRelationshipKind.capability_host)
    assert bridge is not None
    assert bridge.kind == BridgeRelationshipKind.capability_host


def test_get_bridge_relationship_dispatch_target():
    bridge = get_bridge_relationship(BridgeRelationshipKind.dispatch_target)
    assert bridge is not None
    assert bridge.kind == BridgeRelationshipKind.dispatch_target


def test_get_bridge_relationship_unknown_returns_none():
    # Pass a string value that is not a valid BridgeRelationshipKind — should
    # not match any bridge and return None via the loop exhaustion path.
    result = get_bridge_relationship("nonexistent_kind")  # type: ignore[arg-type]
    assert result is None


# ---------------------------------------------------------------------------
# classify_registry_surface() tests
# ---------------------------------------------------------------------------


def test_classify_registry_surface_finds_udm():
    result = classify_registry_surface(
        "core.unified.unified_device_manager.UnifiedDeviceManager"
    )
    assert result is not None
    assert result.domain == RegistrySurfaceDomain.device
    assert result.role == RegistrySurfaceRole.ssot
    assert result.is_authoritative is True


def test_classify_registry_surface_finds_node_fabric_registry():
    result = classify_registry_surface(
        "core.nodes.node_fabric_registry.NodeFabricRegistry"
    )
    assert result is not None
    assert result.domain == RegistrySurfaceDomain.node
    assert result.is_authoritative is True


def test_classify_registry_surface_finds_compat_facade():
    result = classify_registry_surface("core.node_registry.NodeRegistry")
    assert result is not None
    assert result.role == RegistrySurfaceRole.compat_facade
    assert result.is_authoritative is False


def test_classify_registry_surface_finds_capability_assimilation():
    result = classify_registry_surface(
        "core.capability_assimilation.CapabilityAssimilationLayer"
    )
    assert result is not None
    assert result.domain == RegistrySurfaceDomain.bridge


def test_classify_registry_surface_returns_none_for_unknown():
    result = classify_registry_surface("core.completely_unknown_module")
    assert result is None


# ---------------------------------------------------------------------------
# get_surfaces_by_domain() tests
# ---------------------------------------------------------------------------


def test_get_surfaces_by_domain_device_returns_device_surfaces():
    surfaces = get_surfaces_by_domain(RegistrySurfaceDomain.device)
    assert len(surfaces) > 0
    for s in surfaces:
        assert s.domain == RegistrySurfaceDomain.device


def test_get_surfaces_by_domain_node_returns_node_surfaces():
    surfaces = get_surfaces_by_domain(RegistrySurfaceDomain.node)
    assert len(surfaces) > 0
    for s in surfaces:
        assert s.domain == RegistrySurfaceDomain.node


def test_get_surfaces_by_domain_bridge_returns_bridge_surfaces():
    surfaces = get_surfaces_by_domain(RegistrySurfaceDomain.bridge)
    assert len(surfaces) > 0
    for s in surfaces:
        assert s.domain == RegistrySurfaceDomain.bridge


def test_get_surfaces_by_domain_all_have_domain():
    for domain in RegistrySurfaceDomain:
        surfaces = get_surfaces_by_domain(domain)
        for s in surfaces:
            assert s.domain == domain


# ---------------------------------------------------------------------------
# get_authoritative_surfaces() tests
# ---------------------------------------------------------------------------


def test_get_authoritative_surfaces_returns_non_empty():
    surfaces = get_authoritative_surfaces()
    assert len(surfaces) > 0


def test_get_authoritative_surfaces_all_true():
    for s in get_authoritative_surfaces():
        assert s.is_authoritative is True


def test_udm_is_in_authoritative_surfaces():
    paths = [s.module_path for s in get_authoritative_surfaces()]
    assert any("unified_device_manager" in p.lower() or "UnifiedDeviceManager" in p for p in paths)


def test_node_registry_compat_facade_is_not_authoritative():
    result = classify_registry_surface("core.node_registry.NodeRegistry")
    assert result is not None
    assert result.is_authoritative is False


# ---------------------------------------------------------------------------
# build_domain_governance_snapshot() tests
# ---------------------------------------------------------------------------


def test_build_domain_governance_snapshot_returns_snapshot():
    snapshot = build_domain_governance_snapshot()
    assert isinstance(snapshot, DomainGovernanceSnapshot)


def test_build_domain_governance_snapshot_device_domain_is_device():
    snapshot = build_domain_governance_snapshot()
    assert snapshot.device_domain.domain == DomainKind.device


def test_build_domain_governance_snapshot_node_domain_is_node():
    snapshot = build_domain_governance_snapshot()
    assert snapshot.node_domain.domain == DomainKind.node


def test_build_domain_governance_snapshot_has_three_bridges():
    snapshot = build_domain_governance_snapshot()
    assert len(snapshot.bridge_relationships) == 3


def test_build_domain_governance_snapshot_has_catalogue():
    snapshot = build_domain_governance_snapshot()
    assert len(snapshot.registry_surface_catalogue) > 0


def test_build_domain_governance_snapshot_has_authority():
    snapshot = build_domain_governance_snapshot()
    assert snapshot.authority == DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY


def test_build_domain_governance_snapshot_generated_at_positive():
    snapshot = build_domain_governance_snapshot()
    assert snapshot.generated_at > 0


def test_build_domain_governance_snapshot_to_dict_is_json_serialisable():
    import json

    snapshot = build_domain_governance_snapshot()
    d = snapshot.to_dict()
    # Should not raise
    serialised = json.dumps(d)
    assert len(serialised) > 0


def test_build_domain_governance_snapshot_to_dict_has_sentinel():
    snapshot = build_domain_governance_snapshot()
    d = snapshot.to_dict()
    assert "sentinel" in d
    assert "PR5" in d["sentinel"]


def test_build_domain_governance_snapshot_to_dict_has_bridges():
    snapshot = build_domain_governance_snapshot()
    d = snapshot.to_dict()
    assert "bridge_relationships" in d
    assert isinstance(d["bridge_relationships"], list)
    assert len(d["bridge_relationships"]) == 3


def test_build_domain_governance_snapshot_to_dict_has_catalogue():
    snapshot = build_domain_governance_snapshot()
    d = snapshot.to_dict()
    assert "registry_surface_catalogue" in d
    assert isinstance(d["registry_surface_catalogue"], list)
    assert len(d["registry_surface_catalogue"]) > 0


# ---------------------------------------------------------------------------
# get_governance_summary() tests
# ---------------------------------------------------------------------------


def test_get_governance_summary_returns_dict():
    summary = get_governance_summary()
    assert isinstance(summary, dict)


def test_get_governance_summary_has_required_keys():
    summary = get_governance_summary()
    assert "authority" in summary
    assert "sentinel" in summary
    assert "device_domain" in summary
    assert "node_domain" in summary
    assert "bridge_relationships" in summary
    assert "total_catalogued_surfaces" in summary
    assert "authoritative_surfaces" in summary
    assert "governance_model" in summary


def test_get_governance_summary_bridge_relationships_has_three():
    summary = get_governance_summary()
    assert len(summary["bridge_relationships"]) == 3


def test_get_governance_summary_mentions_bridge_preserving():
    summary = get_governance_summary()
    assert "bridge" in summary["governance_model"].lower()


def test_get_governance_summary_mentions_no_false_equivalence():
    summary = get_governance_summary()
    assert "equivalence" in summary["governance_model"].lower()


def test_get_governance_summary_device_domain_has_responsibilities():
    summary = get_governance_summary()
    assert summary["device_domain"]["responsibility_count"] > 0


def test_get_governance_summary_node_domain_has_responsibilities():
    summary = get_governance_summary()
    assert summary["node_domain"]["responsibility_count"] > 0


def test_get_governance_summary_device_lifecycle_mentions_presence():
    summary = get_governance_summary()
    assert "presence" in summary["device_domain"]["lifecycle_kind"]


def test_get_governance_summary_node_lifecycle_mentions_execution():
    summary = get_governance_summary()
    assert "execution" in summary["node_domain"]["lifecycle_kind"]


# ---------------------------------------------------------------------------
# Projection alignment sentinel test
# ---------------------------------------------------------------------------


def test_projection_alignment_sentinel_present():
    pytest.importorskip(
        "fastapi", reason="projection module requires fastapi"
    )
    from core.routes.projection import DEVICE_NODE_DOMAIN_GOVERNANCE_ALIGNED_PR5

    assert "DEVICE_NODE_DOMAIN_GOVERNANCE_ALIGNED_PR5_V1" in (
        DEVICE_NODE_DOMAIN_GOVERNANCE_ALIGNED_PR5
    )
    assert "PR-5" in DEVICE_NODE_DOMAIN_GOVERNANCE_ALIGNED_PR5


# ---------------------------------------------------------------------------
# Domain separation invariants
# ---------------------------------------------------------------------------


def test_device_domain_does_not_have_dispatch_responsibility():
    defn = get_device_domain_definition()
    assert "dispatch_semantics" not in defn.responsibilities


def test_device_domain_does_not_have_invocation_governance_responsibility():
    defn = get_device_domain_definition()
    assert "invocation_governance" not in defn.responsibilities


def test_node_domain_does_not_have_device_identity_responsibility():
    defn = get_node_domain_definition()
    assert "device_identity" not in defn.responsibilities


def test_node_domain_does_not_have_presence_lifecycle_responsibility():
    defn = get_node_domain_definition()
    assert "presence_lifecycle" not in defn.responsibilities


def test_node_domain_does_not_have_registration_responsibility():
    defn = get_node_domain_definition()
    assert "registration" not in defn.responsibilities


def test_device_domain_and_node_domain_have_no_shared_responsibilities():
    device_resp = set(get_device_domain_definition().responsibilities)
    node_resp = set(get_node_domain_definition().responsibilities)
    overlap = device_resp & node_resp
    assert len(overlap) == 0, f"Unexpected shared responsibilities: {overlap}"


def test_device_domain_and_node_domain_have_different_lifecycle_kinds():
    device_lifecycle = get_device_domain_definition().lifecycle_kind
    node_lifecycle = get_node_domain_definition().lifecycle_kind
    assert device_lifecycle != node_lifecycle


def test_no_surface_is_both_device_and_node_domain():
    # A surface cannot claim two different domain ownerships
    device_paths = {s.module_path for s in get_surfaces_by_domain(RegistrySurfaceDomain.device)}
    node_paths = {s.module_path for s in get_surfaces_by_domain(RegistrySurfaceDomain.node)}
    overlap = device_paths & node_paths
    assert len(overlap) == 0, f"Surfaces in both device and node domain: {overlap}"


def test_bridge_surfaces_are_not_in_device_or_node_domain():
    bridge_paths = {s.module_path for s in get_surfaces_by_domain(RegistrySurfaceDomain.bridge)}
    device_paths = {s.module_path for s in get_surfaces_by_domain(RegistrySurfaceDomain.device)}
    node_paths = {s.module_path for s in get_surfaces_by_domain(RegistrySurfaceDomain.node)}
    assert len(bridge_paths & device_paths) == 0
    assert len(bridge_paths & node_paths) == 0


def test_compat_facade_surfaces_are_not_authoritative():
    all_surfaces = []
    for domain in RegistrySurfaceDomain:
        all_surfaces.extend(get_surfaces_by_domain(domain))
    compat_facades = [s for s in all_surfaces if s.role == RegistrySurfaceRole.compat_facade]
    assert len(compat_facades) > 0
    for s in compat_facades:
        assert s.is_authoritative is False, (
            f"Compat facade {s.surface_name!r} must not be authoritative"
        )


def test_ssot_surfaces_are_authoritative():
    all_surfaces = []
    for domain in RegistrySurfaceDomain:
        all_surfaces.extend(get_surfaces_by_domain(domain))
    ssot_surfaces = [s for s in all_surfaces if s.role == RegistrySurfaceRole.ssot]
    assert len(ssot_surfaces) > 0
    for s in ssot_surfaces:
        assert s.is_authoritative is True, (
            f"SSOT surface {s.surface_name!r} must be authoritative"
        )


def test_projection_surfaces_are_not_authoritative():
    all_surfaces = []
    for domain in RegistrySurfaceDomain:
        all_surfaces.extend(get_surfaces_by_domain(domain))
    projection_surfaces = [s for s in all_surfaces if s.role == RegistrySurfaceRole.projection]
    assert len(projection_surfaces) > 0
    for s in projection_surfaces:
        assert s.is_authoritative is False, (
            f"Projection surface {s.surface_name!r} must not be authoritative"
        )


def test_android_relevance_is_present_in_all_bridges():
    for bridge in get_bridge_relationships():
        assert isinstance(bridge.android_relevance, str)
        assert len(bridge.android_relevance) > 0


def test_android_is_mentioned_as_device_domain_participant_in_bridges():
    # Android should be mentioned as a device-domain participant, not a node
    for bridge in get_bridge_relationships():
        relevance = bridge.android_relevance.lower()
        assert "android" in relevance
        # Android should not be called a node in bridge descriptions
        assert "android is a node" not in relevance
