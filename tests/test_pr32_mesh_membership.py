"""tests/test_pr32_mesh_membership.py
=======================================
Tests for PR-32: Mesh Membership Contract.

Coverage:
  1.  Serialisation stability — to_dict / to_json / from_dict round-trips.
  2.  Stable field names — all documented fields present in to_dict output.
  3.  Enum values — MeshMemberRole, MeshAuthorityScope, MeshRoutingIntent.
  4.  MeshParticipationHints — sub-contract correctness.
  5.  from_body_mesh_entry — adapter from BodyEntry / BodyMeshRegistry.
  6.  from_device_formation_summary — adapter from FormationSummary.
  7.  from_cross_device_routing_summary — adapter from CrossDeviceAssignmentSummary.
  8.  build_mesh_membership — convenience factory.
  9.  Graceful handling of partial / missing data (None inputs, missing attrs).
  10. contracts package root re-exports.
  11. core.unified package re-exports.
  12. BodyMeshRegistry.get_mesh_memberships() integration helper.
  13. Projection endpoint — GET /api/v1/mesh/memberships (additive, read-only).
  14. to_compact_summary helper.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_body_entry(
    device_id: str = "dev_001",
    roles=None,
    session_id: str = "sess_001",
    body_score: float = 2.5,
    metadata: dict = None,
) -> Any:
    """Return a mock shaped like core.mesh.body_mesh_registry.BodyEntry."""
    m = MagicMock()
    m.device_id = device_id
    # Use actual DeviceRole values when available; fall back to strings.
    if roles is None:
        try:
            from core.mesh.body_mesh_registry import DeviceRole
            roles = [DeviceRole.PERCEPTION, DeviceRole.ACTION]
        except ImportError:
            roles = []
    m.roles = roles
    m.session_id = session_id
    m.body_score = body_score
    m.metadata = metadata or {"display_name": device_id}
    return m


def _make_formation_summary(
    formation_id: str = "formation_001",
    source_device_id: str = "phone_001",
    primary_device_id: str = "tablet_002",
    fallback: list = None,
    support: list = None,
    observer: list = None,
    relay: list = None,
    merge_owner: str = None,
    barrier_posture: str = "wait_primary",
    multi_req: bool = True,
    merge_req: bool = False,
) -> Any:
    """Return a mock shaped like core.device_formation.FormationSummary."""
    m = MagicMock()
    m.formation_id = formation_id
    m.source_device_id = source_device_id
    m.primary_execution_device_id = primary_device_id
    m.fallback_device_ids = fallback or ["fallback_003"]
    m.support_device_ids = support or ["support_004"]
    m.observer_device_ids = observer or []
    m.relay_device_ids = relay or []
    m.merge_owner_device_id = merge_owner
    m.barrier_posture = barrier_posture
    m.multi_device_required = multi_req
    m.merge_confirmation_required = merge_req
    return m


def _make_routing_summary(
    source_device_id: str = "phone_001",
    primary_execution_device_id: str = "tablet_002",
    posture: str = "local_preferred",
    trace_id: str = "trace_abc",
    fallback: list = None,
    support: list = None,
    observer: list = None,
    relay: list = None,
) -> Any:
    """Return a mock shaped like core.cross_device_policy.CrossDeviceAssignmentSummary."""
    m = MagicMock()
    m.source_device_id = source_device_id
    m.primary_execution_device_id = primary_execution_device_id
    m.posture = posture
    m.trace_id = trace_id
    m.fallback_device_ids = fallback or []
    m.support_device_ids = support or []
    m.observer_device_ids = observer or []
    m.relay_device_ids = relay or []
    return m


# ---------------------------------------------------------------------------
# 1. Serialisation stability
# ---------------------------------------------------------------------------

class TestSerialisationStability:
    """MeshMembership serialises and round-trips correctly."""

    def test_to_dict_returns_serialisable_dict(self):
        from contracts.mesh_membership import MeshMembership
        m = MeshMembership(mesh_id="mesh_a", member_device_id="dev_001")
        result = m.to_dict()
        assert isinstance(result, dict)
        assert result["mesh_id"] == "mesh_a"
        assert result["member_device_id"] == "dev_001"
        # Must be JSON-serialisable
        json.dumps(result)

    def test_to_json_returns_valid_json(self):
        from contracts.mesh_membership import MeshMembership
        m = MeshMembership(mesh_id="mesh_b", member_device_id="dev_002")
        raw = m.to_json()
        parsed = json.loads(raw)
        assert parsed["mesh_id"] == "mesh_b"
        assert parsed["member_device_id"] == "dev_002"

    def test_from_dict_round_trip(self):
        from contracts.mesh_membership import MeshMembership
        original = MeshMembership(
            mesh_id="mesh_c",
            member_device_id="dev_003",
            member_runtime_id="runtime_x",
        )
        data = original.to_dict()
        restored = MeshMembership.from_dict(data)
        assert restored.mesh_id == original.mesh_id
        assert restored.member_device_id == original.member_device_id
        assert restored.member_runtime_id == original.member_runtime_id

    def test_to_json_from_json_round_trip(self):
        from contracts.mesh_membership import MeshMembership, MeshMemberRole
        original = MeshMembership(
            mesh_id="mesh_d",
            member_device_id="dev_004",
            roles=[MeshMemberRole.PRIMARY, MeshMemberRole.SOURCE],
        )
        raw = original.to_json()
        restored = MeshMembership.from_dict(json.loads(raw))
        assert restored.roles == ["primary", "source"]

    def test_to_compact_summary_keys(self):
        from contracts.mesh_membership import MeshMembership
        m = MeshMembership(mesh_id="mesh_e", member_device_id="dev_005")
        compact = m.to_compact_summary()
        for key in ("membership_id", "mesh_id", "member_device_id", "roles",
                    "authority_scope", "routing_intent", "hints"):
            assert key in compact, f"Missing key in compact summary: {key}"


# ---------------------------------------------------------------------------
# 2. Stable field names
# ---------------------------------------------------------------------------

class TestStableFieldNames:
    """All documented fields are present in to_dict output."""

    _REQUIRED_FIELDS = [
        "membership_id",
        "mesh_id",
        "member_device_id",
        "member_runtime_id",
        "roles",
        "authority_scope",
        "routing_intent",
        "source_device_id",
        "primary_device_id",
        "fallback_device_ids",
        "support_device_ids",
        "observer_device_ids",
        "relay_device_ids",
        "merge_owner_device_id",
        "barrier_posture",
        "multi_device_required",
        "merge_confirmation_required",
        "member_online",
        "member_health_score",
        "hints",
        "metadata",
        "created_at",
    ]

    def test_all_documented_fields_present(self):
        from contracts.mesh_membership import MeshMembership
        m = MeshMembership(mesh_id="mesh_x", member_device_id="dev_x")
        result = m.to_dict()
        for field in self._REQUIRED_FIELDS:
            assert field in result, f"Missing field: {field}"

    def test_hints_sub_fields(self):
        from contracts.mesh_membership import MeshMembership
        m = MeshMembership(mesh_id="mesh_y", member_device_id="dev_y")
        hints = m.to_dict()["hints"]
        for field in (
            "is_primary", "is_source", "is_fallback", "is_relay",
            "is_observer", "has_execution_authority",
            "multi_device_required", "merge_confirmation_required",
        ):
            assert field in hints, f"Missing hints field: {field}"


# ---------------------------------------------------------------------------
# 3. Enum values
# ---------------------------------------------------------------------------

class TestEnumValues:
    def test_mesh_member_role_values(self):
        from contracts.mesh_membership import MeshMemberRole
        assert MeshMemberRole.SOURCE.value == "source"
        assert MeshMemberRole.PRIMARY.value == "primary"
        assert MeshMemberRole.SUPPORT.value == "support"
        assert MeshMemberRole.FALLBACK.value == "fallback"
        assert MeshMemberRole.OBSERVER.value == "observer"
        assert MeshMemberRole.RELAY.value == "relay"
        assert MeshMemberRole.MERGE_OWNER.value == "merge_owner"
        assert MeshMemberRole.UNASSIGNED.value == "unassigned"

    def test_mesh_authority_scope_values(self):
        from contracts.mesh_membership import MeshAuthorityScope
        assert MeshAuthorityScope.MESH_AUTHORITY.value == "mesh_authority"
        assert MeshAuthorityScope.EXECUTION_AUTHORITY.value == "execution_authority"
        assert MeshAuthorityScope.OBSERVE_ONLY.value == "observe_only"
        assert MeshAuthorityScope.RELAY_ONLY.value == "relay_only"
        assert MeshAuthorityScope.NONE.value == "none"

    def test_mesh_routing_intent_values(self):
        from contracts.mesh_membership import MeshRoutingIntent
        assert MeshRoutingIntent.LOCAL_PREFERRED.value == "local_preferred"
        assert MeshRoutingIntent.LOCAL_THEN_EXPAND.value == "local_then_expand"
        assert MeshRoutingIntent.REMOTE_REQUIRED.value == "remote_required"
        assert MeshRoutingIntent.SPLIT_EXECUTION.value == "split_execution"
        assert MeshRoutingIntent.MIRRORED_OBSERVATION.value == "mirrored_observation"
        assert MeshRoutingIntent.UNDECIDED.value == "undecided"


# ---------------------------------------------------------------------------
# 4. MeshParticipationHints
# ---------------------------------------------------------------------------

class TestMeshParticipationHints:
    def test_defaults_are_false(self):
        from contracts.mesh_membership import MeshParticipationHints
        h = MeshParticipationHints()
        assert h.is_primary is False
        assert h.is_source is False
        assert h.is_fallback is False
        assert h.is_relay is False
        assert h.is_observer is False
        assert h.has_execution_authority is False
        assert h.multi_device_required is False
        assert h.merge_confirmation_required is False

    def test_to_dict_serialisable(self):
        from contracts.mesh_membership import MeshParticipationHints
        h = MeshParticipationHints(is_primary=True, has_execution_authority=True)
        d = h.to_dict()
        assert d["is_primary"] is True
        assert d["has_execution_authority"] is True
        json.dumps(d)

    def test_hints_reflected_in_membership(self):
        from contracts.mesh_membership import (
            MeshMembership, MeshMemberRole, MeshAuthorityScope,
        )
        m = MeshMembership(
            mesh_id="m",
            member_device_id="d",
            roles=[MeshMemberRole.PRIMARY],
            authority_scope=MeshAuthorityScope.MESH_AUTHORITY,
        )
        # hints are set by build_mesh_membership; here we check the default
        # MeshMembership still has a hints object
        assert m.hints is not None


# ---------------------------------------------------------------------------
# 5. from_body_mesh_entry adapter
# ---------------------------------------------------------------------------

class TestFromBodyMeshEntry:
    def test_basic_entry(self):
        from contracts.mesh_membership import from_body_mesh_entry
        entry = _make_body_entry("phone_001")
        m = from_body_mesh_entry(entry, mesh_id="my_mesh")
        assert m.member_device_id == "phone_001"
        assert m.mesh_id in ("my_mesh", "sess_001")  # session_id may override

    def test_body_roles_preserved_in_metadata(self):
        from contracts.mesh_membership import from_body_mesh_entry
        entry = _make_body_entry("phone_002")
        m = from_body_mesh_entry(entry, mesh_id="m")
        # Original body mesh roles should be in metadata
        body_roles = m.metadata.get("body_mesh_roles")
        assert body_roles is not None
        assert isinstance(body_roles, list)

    def test_authority_nonzero_score(self):
        from contracts.mesh_membership import from_body_mesh_entry, MeshAuthorityScope
        entry = _make_body_entry("dev_scored", body_score=3.0)
        m = from_body_mesh_entry(entry, mesh_id="m")
        assert m.authority_scope == MeshAuthorityScope.EXECUTION_AUTHORITY.value

    def test_authority_zero_score(self):
        from contracts.mesh_membership import from_body_mesh_entry, MeshAuthorityScope
        entry = _make_body_entry("dev_zero", body_score=0.0)
        m = from_body_mesh_entry(entry, mesh_id="m")
        assert m.authority_scope == MeshAuthorityScope.NONE.value

    def test_primary_device_id_passed_through(self):
        from contracts.mesh_membership import from_body_mesh_entry
        entry = _make_body_entry("dev_a")
        m = from_body_mesh_entry(entry, mesh_id="m", primary_device_id="dev_b")
        assert m.primary_device_id == "dev_b"

    def test_none_entry_graceful(self):
        """from_body_mesh_entry should not raise on None."""
        from contracts.mesh_membership import from_body_mesh_entry
        # None has no device_id so result gets a generated id
        result = from_body_mesh_entry(None, mesh_id="m")
        assert result is not None
        assert result.mesh_id == "m"

    def test_bad_entry_graceful(self):
        """Entries with missing attrs should not raise."""
        from contracts.mesh_membership import from_body_mesh_entry
        result = from_body_mesh_entry(object(), mesh_id="m")
        assert result is not None

    def test_real_body_entry(self):
        """Test with an actual BodyEntry from BodyMeshRegistry."""
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        from contracts.mesh_membership import from_body_mesh_entry
        reg = BodyMeshRegistry()
        reg.register("real_dev", roles=[DeviceRole.ACTION])
        entry = reg.get("real_dev")
        m = from_body_mesh_entry(entry, mesh_id="real_mesh")
        assert m.member_device_id == "real_dev"
        assert "action" in m.metadata.get("body_mesh_roles", [])
        json.dumps(m.to_dict())  # Must be serialisable


# ---------------------------------------------------------------------------
# 6. from_device_formation_summary adapter
# ---------------------------------------------------------------------------

class TestFromDeviceFormationSummary:
    def test_returns_list(self):
        from contracts.mesh_membership import from_device_formation_summary
        summary = _make_formation_summary()
        result = from_device_formation_summary(summary, mesh_id="mesh_form")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_unique_devices(self):
        from contracts.mesh_membership import from_device_formation_summary
        summary = _make_formation_summary(
            source_device_id="dev_s",
            primary_device_id="dev_p",
            fallback=["dev_f"],
            support=["dev_sup"],
        )
        result = from_device_formation_summary(summary)
        ids = [m.member_device_id for m in result]
        assert len(ids) == len(set(ids)), "Duplicate device IDs"

    def test_primary_gets_mesh_authority(self):
        from contracts.mesh_membership import (
            from_device_formation_summary, MeshAuthorityScope, MeshMemberRole,
        )
        summary = _make_formation_summary(
            source_device_id="dev_s",
            primary_device_id="dev_p",
        )
        result = from_device_formation_summary(summary)
        primary_ms = [m for m in result if m.member_device_id == "dev_p"]
        assert primary_ms
        assert primary_ms[0].authority_scope == MeshAuthorityScope.MESH_AUTHORITY.value
        assert MeshMemberRole.PRIMARY.value in primary_ms[0].roles

    def test_observer_gets_observe_only(self):
        from contracts.mesh_membership import (
            from_device_formation_summary, MeshAuthorityScope,
        )
        summary = _make_formation_summary(observer=["obs_dev"])
        result = from_device_formation_summary(summary)
        obs_ms = [m for m in result if m.member_device_id == "obs_dev"]
        if obs_ms:
            assert obs_ms[0].authority_scope == MeshAuthorityScope.OBSERVE_ONLY.value

    def test_barrier_posture_preserved(self):
        from contracts.mesh_membership import from_device_formation_summary
        summary = _make_formation_summary(barrier_posture="wait_all")
        result = from_device_formation_summary(summary)
        for m in result:
            assert m.barrier_posture == "wait_all"

    def test_multi_device_required_flag(self):
        from contracts.mesh_membership import from_device_formation_summary
        summary = _make_formation_summary(multi_req=True)
        result = from_device_formation_summary(summary)
        for m in result:
            assert m.multi_device_required is True

    def test_none_summary_returns_empty(self):
        from contracts.mesh_membership import from_device_formation_summary
        assert from_device_formation_summary(None) == []

    def test_empty_summary_returns_empty(self):
        from contracts.mesh_membership import from_device_formation_summary
        m = MagicMock()
        m.formation_id = "f"
        m.source_device_id = None
        m.primary_execution_device_id = None
        m.fallback_device_ids = []
        m.support_device_ids = []
        m.observer_device_ids = []
        m.relay_device_ids = []
        m.merge_owner_device_id = None
        m.barrier_posture = None
        m.multi_device_required = False
        m.merge_confirmation_required = False
        result = from_device_formation_summary(m)
        assert result == []

    def test_all_members_serialisable(self):
        from contracts.mesh_membership import from_device_formation_summary
        summary = _make_formation_summary()
        result = from_device_formation_summary(summary)
        for m in result:
            json.dumps(m.to_dict())


# ---------------------------------------------------------------------------
# 7. from_cross_device_routing_summary adapter
# ---------------------------------------------------------------------------

class TestFromCrossDeviceRoutingSummary:
    def test_returns_list(self):
        from contracts.mesh_membership import from_cross_device_routing_summary
        summary = _make_routing_summary()
        result = from_cross_device_routing_summary(summary, mesh_id="mesh_route")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_routing_posture_mapped(self):
        from contracts.mesh_membership import (
            from_cross_device_routing_summary, MeshRoutingIntent,
        )
        summary = _make_routing_summary(posture="local_preferred")
        result = from_cross_device_routing_summary(summary)
        for m in result:
            assert m.routing_intent == MeshRoutingIntent.LOCAL_PREFERRED.value

    def test_split_execution_posture(self):
        from contracts.mesh_membership import (
            from_cross_device_routing_summary, MeshRoutingIntent,
        )
        summary = _make_routing_summary(posture="split_execution")
        result = from_cross_device_routing_summary(summary)
        for m in result:
            assert m.routing_intent == MeshRoutingIntent.SPLIT_EXECUTION.value

    def test_unknown_posture_maps_to_undecided(self):
        from contracts.mesh_membership import (
            from_cross_device_routing_summary, MeshRoutingIntent,
        )
        summary = _make_routing_summary(posture="unknown_posture")
        result = from_cross_device_routing_summary(summary)
        for m in result:
            assert m.routing_intent == MeshRoutingIntent.UNDECIDED.value

    def test_none_summary_returns_empty(self):
        from contracts.mesh_membership import from_cross_device_routing_summary
        assert from_cross_device_routing_summary(None) == []

    def test_all_members_serialisable(self):
        from contracts.mesh_membership import from_cross_device_routing_summary
        summary = _make_routing_summary(
            fallback=["fb_1"],
            support=["sup_1"],
            observer=["obs_1"],
            relay=["rel_1"],
        )
        result = from_cross_device_routing_summary(summary)
        for m in result:
            json.dumps(m.to_dict())

    def test_real_routing_summary(self):
        """Adapter works with an actual CrossDeviceAssignmentSummary."""
        from core.cross_device_policy import build_assignment_summary, DEFAULT_LOCAL_ROUTING_POLICY
        from contracts.mesh_membership import from_cross_device_routing_summary
        routing = build_assignment_summary(DEFAULT_LOCAL_ROUTING_POLICY)
        result = from_cross_device_routing_summary(routing)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 8. build_mesh_membership factory
# ---------------------------------------------------------------------------

class TestBuildMeshMembership:
    def test_minimal_call(self):
        from contracts.mesh_membership import build_mesh_membership
        m = build_mesh_membership(
            mesh_id="minimal_mesh",
            member_device_id="dev_min",
        )
        assert m.mesh_id == "minimal_mesh"
        assert m.member_device_id == "dev_min"

    def test_full_call(self):
        from contracts.mesh_membership import (
            build_mesh_membership, MeshMemberRole, MeshAuthorityScope, MeshRoutingIntent,
        )
        m = build_mesh_membership(
            mesh_id="full_mesh",
            member_device_id="dev_full",
            membership_id="fixed_id",
            member_runtime_id="runtime_001",
            roles=[MeshMemberRole.PRIMARY, MeshMemberRole.SOURCE],
            authority_scope=MeshAuthorityScope.MESH_AUTHORITY,
            routing_intent=MeshRoutingIntent.LOCAL_PREFERRED,
            source_device_id="dev_src",
            primary_device_id="dev_full",
            fallback_device_ids=["dev_fb"],
            support_device_ids=["dev_sup"],
            observer_device_ids=["dev_obs"],
            relay_device_ids=["dev_relay"],
            merge_owner_device_id="dev_full",
            barrier_posture="wait_primary",
            multi_device_required=True,
            merge_confirmation_required=True,
            member_online=True,
            member_health_score=0.9,
            metadata={"tag": "test"},
        )
        assert m.membership_id == "fixed_id"
        assert m.member_runtime_id == "runtime_001"
        assert "primary" in m.roles
        assert m.authority_scope == "mesh_authority"
        assert m.routing_intent == "local_preferred"
        assert m.fallback_device_ids == ["dev_fb"]
        assert m.multi_device_required is True
        assert m.hints.is_primary is True
        assert m.hints.is_source is True
        assert m.hints.has_execution_authority is True
        assert m.hints.multi_device_required is True
        json.dumps(m.to_dict())

    def test_auto_membership_id(self):
        from contracts.mesh_membership import build_mesh_membership
        m1 = build_mesh_membership("m", "d")
        m2 = build_mesh_membership("m", "d")
        assert m1.membership_id != m2.membership_id

    def test_hints_computed_correctly(self):
        from contracts.mesh_membership import (
            build_mesh_membership, MeshMemberRole, MeshAuthorityScope,
        )
        m = build_mesh_membership(
            mesh_id="m",
            member_device_id="d",
            roles=[MeshMemberRole.FALLBACK],
            authority_scope=MeshAuthorityScope.OBSERVE_ONLY,
        )
        assert m.hints.is_fallback is True
        assert m.hints.has_execution_authority is False


# ---------------------------------------------------------------------------
# 9. Graceful handling of partial / missing data
# ---------------------------------------------------------------------------

class TestGracefulPartialData:
    def test_from_body_mesh_entry_empty_roles(self):
        from contracts.mesh_membership import from_body_mesh_entry
        entry = _make_body_entry(roles=[])
        m = from_body_mesh_entry(entry)
        assert m is not None
        assert "unassigned" in m.roles

    def test_from_formation_summary_missing_attrs(self):
        from contracts.mesh_membership import from_device_formation_summary
        # Object with no relevant attrs
        result = from_device_formation_summary(object())
        assert isinstance(result, list)

    def test_from_routing_summary_missing_attrs(self):
        from contracts.mesh_membership import from_cross_device_routing_summary
        result = from_cross_device_routing_summary(object())
        assert isinstance(result, list)

    def test_membership_default_fields(self):
        from contracts.mesh_membership import MeshMembership, MeshAuthorityScope, MeshRoutingIntent
        m = MeshMembership(mesh_id="m", member_device_id="d")
        assert m.roles == []
        assert m.authority_scope == MeshAuthorityScope.NONE.value
        assert m.routing_intent == MeshRoutingIntent.UNDECIDED.value
        assert m.source_device_id is None
        assert m.primary_device_id is None
        assert m.fallback_device_ids == []
        assert m.member_online is None
        assert m.member_health_score is None
        assert m.metadata == {}


# ---------------------------------------------------------------------------
# 10. contracts package root re-exports
# ---------------------------------------------------------------------------

class TestContractsPackageExports:
    def test_mesh_membership_importable(self):
        from contracts import MeshMembership  # noqa: F401

    def test_mesh_member_role_importable(self):
        from contracts import MeshMemberRole  # noqa: F401

    def test_mesh_authority_scope_importable(self):
        from contracts import MeshAuthorityScope  # noqa: F401

    def test_mesh_routing_intent_importable(self):
        from contracts import MeshRoutingIntent  # noqa: F401

    def test_mesh_participation_hints_importable(self):
        from contracts import MeshParticipationHints  # noqa: F401

    def test_from_body_mesh_entry_importable(self):
        from contracts import from_body_mesh_entry  # noqa: F401

    def test_from_device_formation_summary_importable(self):
        from contracts import from_device_formation_summary  # noqa: F401

    def test_from_cross_device_routing_summary_importable(self):
        from contracts import from_cross_device_routing_summary  # noqa: F401

    def test_build_mesh_membership_importable(self):
        from contracts import build_mesh_membership  # noqa: F401


# ---------------------------------------------------------------------------
# 11. core.unified package re-exports
# ---------------------------------------------------------------------------

class TestCoreUnifiedExports:
    def test_mesh_membership_importable(self):
        from core.unified import MeshMembership  # noqa: F401

    def test_mesh_member_role_importable(self):
        from core.unified import MeshMemberRole  # noqa: F401

    def test_mesh_authority_scope_importable(self):
        from core.unified import MeshAuthorityScope  # noqa: F401

    def test_mesh_routing_intent_importable(self):
        from core.unified import MeshRoutingIntent  # noqa: F401

    def test_mesh_participation_hints_importable(self):
        from core.unified import MeshParticipationHints  # noqa: F401

    def test_from_body_mesh_entry_importable(self):
        from core.unified import from_body_mesh_entry  # noqa: F401

    def test_from_device_formation_summary_importable(self):
        from core.unified import from_device_formation_summary  # noqa: F401

    def test_from_cross_device_routing_summary_importable(self):
        from core.unified import from_cross_device_routing_summary  # noqa: F401

    def test_build_mesh_membership_importable(self):
        from core.unified import build_mesh_membership  # noqa: F401


# ---------------------------------------------------------------------------
# 12. BodyMeshRegistry.get_mesh_memberships() integration
# ---------------------------------------------------------------------------

class TestBodyMeshRegistryIntegration:
    def setup_method(self):
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()

    def test_empty_registry_returns_empty(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry
        reg = BodyMeshRegistry()
        result = reg.get_mesh_memberships(mesh_id="m")
        assert result == []

    def test_returns_one_per_device(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        reg = BodyMeshRegistry()
        reg.register("dev_a", roles=[DeviceRole.PERCEPTION])
        reg.register("dev_b", roles=[DeviceRole.ACTION])
        result = reg.get_mesh_memberships(mesh_id="m")
        assert len(result) == 2
        ids = {m.member_device_id for m in result}
        assert ids == {"dev_a", "dev_b"}

    def test_all_memberships_serialisable(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        reg = BodyMeshRegistry()
        reg.register("dev_c", roles=[DeviceRole.PRESENCE])
        result = reg.get_mesh_memberships(mesh_id="m")
        for m in result:
            json.dumps(m.to_dict())

    def test_session_filter(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        reg = BodyMeshRegistry()
        reg.register("dev_s1", roles=[DeviceRole.ACTION], session_id="sess_a")
        reg.register("dev_s2", roles=[DeviceRole.PERCEPTION], session_id="sess_b")
        result = reg.get_mesh_memberships(session_id="sess_a")
        assert len(result) == 1
        assert result[0].member_device_id == "dev_s1"

    def test_primary_device_identified(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        reg = BodyMeshRegistry()
        reg.register("dev_low", roles=[DeviceRole.PERCEPTION])
        reg.register("dev_high", roles=[DeviceRole.ACTION])
        reg.score_entry("dev_high", 5.0)
        result = reg.get_mesh_memberships(mesh_id="m")
        for m in result:
            assert m.primary_device_id == "dev_high"


# ---------------------------------------------------------------------------
# 13. Projection endpoint — GET /api/v1/mesh/memberships
# ---------------------------------------------------------------------------

class TestProjectionEndpoint:
    def test_endpoint_registered_in_router(self):
        """Router has GET /api/v1/mesh/memberships route."""
        from core.routes.projection import create_router
        router = create_router()
        route_paths = [r.path for r in router.routes]
        assert "/api/v1/mesh/memberships" in route_paths

    def test_endpoint_returns_valid_structure(self):
        """Endpoint response has expected keys."""
        import asyncio
        from core.routes.projection import create_router
        from unittest.mock import patch

        router = create_router()

        # Find the route handler
        handler = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/v1/mesh/memberships":
                handler = route.endpoint
                break

        assert handler is not None

        with patch("core.mesh.body_mesh_registry.get_body_mesh_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.get_mesh_memberships.return_value = []
            mock_reg.return_value = mock_registry

            response = asyncio.get_event_loop().run_until_complete(handler())
            body = json.loads(response.body)
            assert "mesh_id" in body
            assert "total" in body
            assert "memberships" in body
            assert isinstance(body["memberships"], list)

    def test_endpoint_handles_exception_gracefully(self):
        """Endpoint does not raise when registry throws."""
        import asyncio
        from core.routes.projection import create_router
        from unittest.mock import patch

        router = create_router()
        handler = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/v1/mesh/memberships":
                handler = route.endpoint
                break

        with patch(
            "core.mesh.body_mesh_registry.get_body_mesh_registry",
            side_effect=RuntimeError("registry unavailable"),
        ):
            response = asyncio.get_event_loop().run_until_complete(handler())
            body = json.loads(response.body)
            assert body["total"] == 0
            assert "error" in body


# ---------------------------------------------------------------------------
# 14. to_compact_summary
# ---------------------------------------------------------------------------

class TestCompactSummary:
    def test_compact_summary_is_serialisable(self):
        from contracts.mesh_membership import build_mesh_membership, MeshMemberRole
        m = build_mesh_membership(
            mesh_id="mesh_compact",
            member_device_id="dev_compact",
            roles=[MeshMemberRole.PRIMARY],
            member_online=True,
            member_health_score=0.8,
        )
        compact = m.to_compact_summary()
        json.dumps(compact)

    def test_compact_summary_contains_key_fields(self):
        from contracts.mesh_membership import MeshMembership
        m = MeshMembership(mesh_id="m", member_device_id="d")
        compact = m.to_compact_summary()
        assert compact["mesh_id"] == "m"
        assert compact["member_device_id"] == "d"
        assert "hints" in compact
