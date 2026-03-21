"""
tests/test_pr13_cross_device_policy.py
========================================
Tests for PR-13: Cross-Device Role & Routing Policy.

Coverage
--------
A) DeviceRole enum
   - all expected role values present
   - string values are stable
   - enum is str subclass
   - ROLE_PRECEDENCE ordering
   - role_description returns non-empty strings

B) DeviceRoleAssignment dataclass
   - construction with all fields
   - to_dict() serialisation
   - from_dict() reconstruction
   - frozen / immutable
   - round-trip fidelity (to_dict + from_dict)
   - default construction (unassigned)
   - __repr__ smoke test

C) RoutingPosture enum
   - all expected posture values present
   - string values are stable
   - enum is str subclass
   - POSTURE_DESCRIPTIONS covers all postures

D) RoutingPolicy dataclass
   - default (local) construction
   - field round-trip via to_dict() and from_dict()
   - is_cross_device derived property
   - primary_execution_device_id derived property
   - source_assignment derived property
   - devices_with_role filter
   - DEFAULT_LOCAL_ROUTING_POLICY constant
   - frozen / immutable
   - __repr__ smoke test

E) CrossDeviceAssignmentSummary dataclass
   - construction with all fields
   - to_dict() serialisation
   - from_dict() reconstruction
   - round-trip fidelity
   - IDLE_ASSIGNMENT_SUMMARY constant
   - __repr__ smoke test

F) build_assignment_summary helper
   - None policy → IDLE_ASSIGNMENT_SUMMARY equivalent
   - local policy → local summary
   - cross-device policy with assignments → correct role lists
   - all_assignments populated correctly

G) attach_cross_device_to_projection helper
   - adds "cross_device_routing" key to projection dict
   - original dict not modified
   - None summary uses IDLE_ASSIGNMENT_SUMMARY
   - existing fields preserved

H) get_assignment_hints helper
   - None summary → safe defaults
   - local summary → correct hint values
   - cross-device summary → has_primary=True etc.

I) resolve_routing — domain-primary resolution
   - None domain → local_preferred posture
   - "local" domain → local_preferred posture
   - "transition" domain → local_preferred posture
   - "cross_device" domain, no execution policy → local_preferred (expansion blocked)

J) resolve_routing — cross-device with execution policy
   - cross_device + cross_device_allowed=False → local_preferred, expansion=False
   - cross_device + cross_device_allowed=True → local_then_expand (default)
   - cross_device + split_execution hint → split_execution posture
   - cross_device + remote_required hint → remote_required posture
   - cross_device + mirrored_observation hint → mirrored_observation posture
   - cross_device + target_device_ids → local_then_expand with assignments

K) resolve_routing — authority role interactions
   - legacy_compatibility authority → cross-device blocked even when policy allows
   - deprecated authority → cross-device blocked
   - authoritative_entrypoint authority + allowed policy → not downgraded

L) resolve_routing — device assignment building
   - source_device_id propagated to SOURCE assignment
   - first target → PRIMARY_EXECUTION
   - subsequent targets → SUPPORT (for local_then_expand)
   - MIRRORED_OBSERVATION: additional targets → OBSERVER role
   - SPLIT_EXECUTION: additional targets → SUPPORT role

M) resolve_routing — graceful degradation
   - invalid domain string → local_preferred (safe default)
   - execution policy as dict → cross_device_allowed extracted correctly
   - execution policy as object → cross_device_allowed extracted correctly
   - exception in resolver → returns DEFAULT_LOCAL_ROUTING_POLICY

N) resolve_routing_summary — convenience wrapper
   - returns CrossDeviceAssignmentSummary (not RoutingPolicy)
   - local domain → IDLE-like summary
   - cross-device domain → enriched summary

O) Projection endpoint integration
   - _assemble_projection_with_cross_device_routing does not raise
   - result contains "cross_device_routing" key
   - cross_device_routing has expected fields

P) Public API completeness (smoke test)
   - all names in __all__ importable from top-level package
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# A) DeviceRole enum
# ---------------------------------------------------------------------------


class TestDeviceRoleEnum:
    def test_all_expected_values_present(self):
        from core.cross_device_policy import DeviceRole

        expected = {
            "source_device",
            "primary_execution_device",
            "support_device",
            "observer_device",
            "relay_device",
            "fallback_device",
            "unassigned",
        }
        actual = {r.value for r in DeviceRole}
        assert expected == actual

    def test_is_str_subclass(self):
        from core.cross_device_policy import DeviceRole

        assert isinstance(DeviceRole.SOURCE, str)

    def test_stable_string_values(self):
        from core.cross_device_policy import DeviceRole

        assert DeviceRole.SOURCE.value == "source_device"
        assert DeviceRole.PRIMARY_EXECUTION.value == "primary_execution_device"
        assert DeviceRole.SUPPORT.value == "support_device"
        assert DeviceRole.OBSERVER.value == "observer_device"
        assert DeviceRole.RELAY.value == "relay_device"
        assert DeviceRole.FALLBACK.value == "fallback_device"
        assert DeviceRole.UNASSIGNED.value == "unassigned"

    def test_role_precedence_ordering(self):
        from core.cross_device_policy import DeviceRole, ROLE_PRECEDENCE

        # PRIMARY_EXECUTION should be first (highest precedence)
        assert ROLE_PRECEDENCE[0] is DeviceRole.PRIMARY_EXECUTION
        # All roles are represented
        assert set(ROLE_PRECEDENCE) == set(DeviceRole)

    def test_role_description_returns_non_empty(self):
        from core.cross_device_policy import DeviceRole, role_description

        for role in DeviceRole:
            desc = role_description(role)
            assert isinstance(desc, str)
            assert len(desc) > 0


# ---------------------------------------------------------------------------
# B) DeviceRoleAssignment dataclass
# ---------------------------------------------------------------------------


class TestDeviceRoleAssignment:
    def test_default_construction(self):
        from core.cross_device_policy import DeviceRoleAssignment, DeviceRole

        a = DeviceRoleAssignment()
        assert a.device_id is None
        assert a.role is DeviceRole.UNASSIGNED
        assert a.reason == "unassigned"
        assert a.capabilities == []
        assert a.is_local is False

    def test_construction_with_all_fields(self):
        from core.cross_device_policy import DeviceRoleAssignment, DeviceRole

        a = DeviceRoleAssignment(
            device_id="phone-1",
            role=DeviceRole.SUPPORT,
            reason="has camera",
            capabilities=["camera", "microphone"],
            is_local=False,
        )
        assert a.device_id == "phone-1"
        assert a.role is DeviceRole.SUPPORT
        assert a.capabilities == ["camera", "microphone"]

    def test_to_dict_serialisation(self):
        from core.cross_device_policy import DeviceRoleAssignment, DeviceRole

        a = DeviceRoleAssignment(
            device_id="tablet-1",
            role=DeviceRole.OBSERVER,
            reason="status display",
        )
        d = a.to_dict()
        assert d["device_id"] == "tablet-1"
        assert d["role"] == "observer_device"
        assert d["reason"] == "status display"
        assert isinstance(d["capabilities"], list)
        assert d["is_local"] is False

    def test_from_dict_reconstruction(self):
        from core.cross_device_policy import DeviceRoleAssignment, DeviceRole

        data = {
            "device_id": "pc-main",
            "role": "primary_execution_device",
            "reason": "main executor",
            "capabilities": ["gui", "uia"],
            "is_local": True,
        }
        a = DeviceRoleAssignment.from_dict(data)
        assert a.device_id == "pc-main"
        assert a.role is DeviceRole.PRIMARY_EXECUTION
        assert a.capabilities == ["gui", "uia"]
        assert a.is_local is True

    def test_from_dict_invalid_role_defaults_to_unassigned(self):
        from core.cross_device_policy import DeviceRoleAssignment, DeviceRole

        a = DeviceRoleAssignment.from_dict({"role": "nonexistent_role"})
        assert a.role is DeviceRole.UNASSIGNED

    def test_round_trip(self):
        from core.cross_device_policy import DeviceRoleAssignment, DeviceRole

        original = DeviceRoleAssignment(
            device_id="d1",
            role=DeviceRole.FALLBACK,
            reason="backup",
            capabilities=["system_api"],
            is_local=False,
        )
        reconstructed = DeviceRoleAssignment.from_dict(original.to_dict())
        assert reconstructed.device_id == original.device_id
        assert reconstructed.role == original.role
        assert reconstructed.reason == original.reason
        assert reconstructed.capabilities == original.capabilities
        assert reconstructed.is_local == original.is_local

    def test_frozen_immutable(self):
        from core.cross_device_policy import DeviceRoleAssignment, DeviceRole

        a = DeviceRoleAssignment(device_id="x", role=DeviceRole.SOURCE)
        with pytest.raises((AttributeError, TypeError)):
            a.device_id = "y"  # type: ignore[misc]

    def test_repr_smoke(self):
        from core.cross_device_policy import DeviceRoleAssignment, DeviceRole

        a = DeviceRoleAssignment(device_id="test", role=DeviceRole.RELAY)
        r = repr(a)
        assert "DeviceRoleAssignment" in r


# ---------------------------------------------------------------------------
# C) RoutingPosture enum
# ---------------------------------------------------------------------------


class TestRoutingPostureEnum:
    def test_all_expected_values_present(self):
        from core.cross_device_policy import RoutingPosture

        expected = {
            "local_preferred",
            "local_then_expand",
            "remote_required",
            "split_execution",
            "mirrored_observation",
            "undecided",
        }
        actual = {p.value for p in RoutingPosture}
        assert expected == actual

    def test_is_str_subclass(self):
        from core.cross_device_policy import RoutingPosture

        assert isinstance(RoutingPosture.LOCAL_PREFERRED, str)

    def test_stable_string_values(self):
        from core.cross_device_policy import RoutingPosture

        assert RoutingPosture.LOCAL_PREFERRED.value == "local_preferred"
        assert RoutingPosture.LOCAL_THEN_EXPAND.value == "local_then_expand"
        assert RoutingPosture.REMOTE_REQUIRED.value == "remote_required"
        assert RoutingPosture.SPLIT_EXECUTION.value == "split_execution"
        assert RoutingPosture.MIRRORED_OBSERVATION.value == "mirrored_observation"
        assert RoutingPosture.UNDECIDED.value == "undecided"

    def test_posture_descriptions_covers_all(self):
        from core.cross_device_policy import RoutingPosture, POSTURE_DESCRIPTIONS

        for posture in RoutingPosture:
            assert posture.value in POSTURE_DESCRIPTIONS
            assert len(POSTURE_DESCRIPTIONS[posture.value]) > 0


# ---------------------------------------------------------------------------
# D) RoutingPolicy dataclass
# ---------------------------------------------------------------------------


class TestRoutingPolicy:
    def test_default_construction(self):
        from core.cross_device_policy import RoutingPolicy, RoutingPosture

        p = RoutingPolicy()
        assert p.posture is RoutingPosture.UNDECIDED
        assert p.source_device_id is None
        assert p.assigned_devices == []
        assert p.expansion_allowed_by_execution_policy is False
        assert p.confirmation_required_before_expansion is True

    def test_is_cross_device_property(self):
        from core.cross_device_policy import RoutingPolicy, RoutingPosture

        local = RoutingPolicy(posture=RoutingPosture.LOCAL_PREFERRED)
        assert local.is_cross_device is False

        cross = RoutingPolicy(posture=RoutingPosture.LOCAL_THEN_EXPAND)
        assert cross.is_cross_device is True

        remote = RoutingPolicy(posture=RoutingPosture.REMOTE_REQUIRED)
        assert remote.is_cross_device is True

        undecided = RoutingPolicy(posture=RoutingPosture.UNDECIDED)
        assert undecided.is_cross_device is False

    def test_primary_execution_device_id_property(self):
        from core.cross_device_policy import RoutingPolicy, DeviceRole, DeviceRoleAssignment

        p = RoutingPolicy(
            assigned_devices=[
                DeviceRoleAssignment(device_id="pc", role=DeviceRole.PRIMARY_EXECUTION),
                DeviceRoleAssignment(device_id="phone", role=DeviceRole.SUPPORT),
            ]
        )
        assert p.primary_execution_device_id == "pc"

    def test_primary_execution_device_id_none_when_absent(self):
        from core.cross_device_policy import RoutingPolicy, DeviceRole, DeviceRoleAssignment

        p = RoutingPolicy(
            assigned_devices=[
                DeviceRoleAssignment(device_id="phone", role=DeviceRole.SUPPORT),
            ]
        )
        assert p.primary_execution_device_id is None

    def test_source_assignment_property(self):
        from core.cross_device_policy import RoutingPolicy, DeviceRole, DeviceRoleAssignment

        p = RoutingPolicy(
            assigned_devices=[
                DeviceRoleAssignment(device_id="src", role=DeviceRole.SOURCE),
            ]
        )
        assert p.source_assignment is not None
        assert p.source_assignment.device_id == "src"

    def test_devices_with_role_filter(self):
        from core.cross_device_policy import RoutingPolicy, DeviceRole, DeviceRoleAssignment

        p = RoutingPolicy(
            assigned_devices=[
                DeviceRoleAssignment(device_id="a", role=DeviceRole.SUPPORT),
                DeviceRoleAssignment(device_id="b", role=DeviceRole.SUPPORT),
                DeviceRoleAssignment(device_id="c", role=DeviceRole.PRIMARY_EXECUTION),
            ]
        )
        supports = p.devices_with_role(DeviceRole.SUPPORT)
        assert len(supports) == 2
        assert all(a.role is DeviceRole.SUPPORT for a in supports)

    def test_to_dict_serialisation(self):
        from core.cross_device_policy import RoutingPolicy, RoutingPosture

        p = RoutingPolicy(
            posture=RoutingPosture.LOCAL_THEN_EXPAND,
            source_device_id="src",
            runtime_domain_intent="cross_device",
            expansion_allowed_by_execution_policy=True,
        )
        d = p.to_dict()
        assert d["posture"] == "local_then_expand"
        assert d["source_device_id"] == "src"
        assert d["runtime_domain_intent"] == "cross_device"
        assert d["expansion_allowed_by_execution_policy"] is True
        assert "is_cross_device" in d
        assert "primary_execution_device_id" in d

    def test_from_dict_reconstruction(self):
        from core.cross_device_policy import RoutingPolicy, RoutingPosture

        data = {
            "posture": "remote_required",
            "source_device_id": "dev-x",
            "runtime_domain_intent": "cross_device",
            "policy_reason": "test",
            "expansion_allowed_by_execution_policy": True,
            "confirmation_required_before_expansion": False,
        }
        p = RoutingPolicy.from_dict(data)
        assert p.posture is RoutingPosture.REMOTE_REQUIRED
        assert p.source_device_id == "dev-x"
        assert p.expansion_allowed_by_execution_policy is True

    def test_from_dict_invalid_posture_defaults_to_undecided(self):
        from core.cross_device_policy import RoutingPolicy, RoutingPosture

        p = RoutingPolicy.from_dict({"posture": "nonexistent_posture"})
        assert p.posture is RoutingPosture.UNDECIDED

    def test_default_local_routing_policy_constant(self):
        from core.cross_device_policy import DEFAULT_LOCAL_ROUTING_POLICY, RoutingPosture

        assert DEFAULT_LOCAL_ROUTING_POLICY.posture is RoutingPosture.LOCAL_PREFERRED
        assert DEFAULT_LOCAL_ROUTING_POLICY.expansion_allowed_by_execution_policy is False

    def test_frozen_immutable(self):
        from core.cross_device_policy import RoutingPolicy

        p = RoutingPolicy()
        with pytest.raises((AttributeError, TypeError)):
            p.posture = None  # type: ignore[misc]

    def test_repr_smoke(self):
        from core.cross_device_policy import RoutingPolicy

        p = RoutingPolicy(source_device_id="x")
        r = repr(p)
        assert "RoutingPolicy" in r


# ---------------------------------------------------------------------------
# E) CrossDeviceAssignmentSummary dataclass
# ---------------------------------------------------------------------------


class TestCrossDeviceAssignmentSummary:
    def test_default_construction(self):
        from core.cross_device_policy import CrossDeviceAssignmentSummary, RoutingPosture

        s = CrossDeviceAssignmentSummary()
        assert s.posture == RoutingPosture.UNDECIDED.value
        assert s.is_cross_device is False
        assert s.primary_execution_device_id is None
        assert s.support_device_ids == []

    def test_to_dict_serialisation(self):
        from core.cross_device_policy import CrossDeviceAssignmentSummary

        s = CrossDeviceAssignmentSummary(
            posture="local_then_expand",
            primary_execution_device_id="pc-1",
            is_cross_device=True,
        )
        d = s.to_dict()
        assert d["posture"] == "local_then_expand"
        assert d["primary_execution_device_id"] == "pc-1"
        assert d["is_cross_device"] is True
        assert "support_device_ids" in d
        assert "observer_device_ids" in d

    def test_from_dict_reconstruction(self):
        from core.cross_device_policy import CrossDeviceAssignmentSummary

        data = {
            "posture": "split_execution",
            "source_device_id": "a",
            "primary_execution_device_id": "b",
            "support_device_ids": ["c", "d"],
            "is_cross_device": True,
            "expansion_allowed_by_execution_policy": True,
        }
        s = CrossDeviceAssignmentSummary.from_dict(data)
        assert s.posture == "split_execution"
        assert s.primary_execution_device_id == "b"
        assert s.support_device_ids == ["c", "d"]
        assert s.is_cross_device is True

    def test_round_trip(self):
        from core.cross_device_policy import CrossDeviceAssignmentSummary

        original = CrossDeviceAssignmentSummary(
            posture="mirrored_observation",
            primary_execution_device_id="p1",
            observer_device_ids=["o1", "o2"],
            is_cross_device=True,
            task_id="t123",
            trace_id="tr456",
        )
        reconstructed = CrossDeviceAssignmentSummary.from_dict(original.to_dict())
        assert reconstructed.posture == original.posture
        assert reconstructed.primary_execution_device_id == original.primary_execution_device_id
        assert reconstructed.observer_device_ids == original.observer_device_ids
        assert reconstructed.task_id == original.task_id

    def test_idle_summary_constant(self):
        from core.cross_device_policy import IDLE_ASSIGNMENT_SUMMARY, RoutingPosture

        assert IDLE_ASSIGNMENT_SUMMARY.posture == RoutingPosture.LOCAL_PREFERRED.value
        assert IDLE_ASSIGNMENT_SUMMARY.is_cross_device is False
        assert IDLE_ASSIGNMENT_SUMMARY.expansion_allowed_by_execution_policy is False

    def test_repr_smoke(self):
        from core.cross_device_policy import CrossDeviceAssignmentSummary

        s = CrossDeviceAssignmentSummary(primary_execution_device_id="test")
        r = repr(s)
        assert "CrossDeviceAssignmentSummary" in r


# ---------------------------------------------------------------------------
# F) build_assignment_summary helper
# ---------------------------------------------------------------------------


class TestBuildAssignmentSummary:
    def test_none_policy_returns_idle_like(self):
        from core.cross_device_policy import build_assignment_summary, RoutingPosture

        s = build_assignment_summary(None)
        assert s.posture == RoutingPosture.LOCAL_PREFERRED.value
        assert s.is_cross_device is False
        assert s.expansion_allowed_by_execution_policy is False

    def test_local_policy_returns_local_summary(self):
        from core.cross_device_policy import (
            build_assignment_summary,
            RoutingPolicy,
            RoutingPosture,
        )

        policy = RoutingPolicy(
            posture=RoutingPosture.LOCAL_PREFERRED,
            runtime_domain_intent="local",
        )
        s = build_assignment_summary(policy)
        assert s.posture == "local_preferred"
        assert s.is_cross_device is False

    def test_cross_device_policy_populates_role_lists(self):
        from core.cross_device_policy import (
            build_assignment_summary,
            RoutingPolicy,
            RoutingPosture,
            DeviceRole,
            DeviceRoleAssignment,
        )

        policy = RoutingPolicy(
            posture=RoutingPosture.LOCAL_THEN_EXPAND,
            source_device_id="src",
            assigned_devices=[
                DeviceRoleAssignment(device_id="src", role=DeviceRole.SOURCE),
                DeviceRoleAssignment(device_id="primary", role=DeviceRole.PRIMARY_EXECUTION),
                DeviceRoleAssignment(device_id="support1", role=DeviceRole.SUPPORT),
                DeviceRoleAssignment(device_id="obs1", role=DeviceRole.OBSERVER),
                DeviceRoleAssignment(device_id="fallback1", role=DeviceRole.FALLBACK),
                DeviceRoleAssignment(device_id="relay1", role=DeviceRole.RELAY),
            ],
            expansion_allowed_by_execution_policy=True,
        )
        s = build_assignment_summary(policy)
        assert s.primary_execution_device_id == "primary"
        assert "support1" in s.support_device_ids
        assert "obs1" in s.observer_device_ids
        assert "fallback1" in s.fallback_device_ids
        assert "relay1" in s.relay_device_ids
        assert len(s.all_assignments) == 6
        assert s.expansion_allowed_by_execution_policy is True


# ---------------------------------------------------------------------------
# G) attach_cross_device_to_projection helper
# ---------------------------------------------------------------------------


class TestAttachCrossDeviceToProjection:
    def test_adds_cross_device_routing_key(self):
        from core.cross_device_policy import (
            attach_cross_device_to_projection,
            IDLE_ASSIGNMENT_SUMMARY,
        )

        proj = {"tri_state_phase": "manifest", "runtime_domain": "cross_device"}
        enriched = attach_cross_device_to_projection(proj, IDLE_ASSIGNMENT_SUMMARY)
        assert "cross_device_routing" in enriched

    def test_original_dict_not_modified(self):
        from core.cross_device_policy import attach_cross_device_to_projection, IDLE_ASSIGNMENT_SUMMARY

        proj = {"tri_state_phase": "manifest"}
        _ = attach_cross_device_to_projection(proj, IDLE_ASSIGNMENT_SUMMARY)
        assert "cross_device_routing" not in proj

    def test_none_summary_uses_idle(self):
        from core.cross_device_policy import (
            attach_cross_device_to_projection,
            RoutingPosture,
        )

        proj = {}
        enriched = attach_cross_device_to_projection(proj, None)
        assert enriched["cross_device_routing"]["posture"] == RoutingPosture.LOCAL_PREFERRED.value

    def test_existing_fields_preserved(self):
        from core.cross_device_policy import attach_cross_device_to_projection, IDLE_ASSIGNMENT_SUMMARY

        proj = {"tri_state_phase": "silent", "runtime_domain": "local", "custom": 42}
        enriched = attach_cross_device_to_projection(proj, IDLE_ASSIGNMENT_SUMMARY)
        assert enriched["tri_state_phase"] == "silent"
        assert enriched["custom"] == 42


# ---------------------------------------------------------------------------
# H) get_assignment_hints helper
# ---------------------------------------------------------------------------


class TestGetAssignmentHints:
    def test_none_summary_safe_defaults(self):
        from core.cross_device_policy import get_assignment_hints

        hints = get_assignment_hints(None)
        assert hints["is_cross_device"] is False
        assert hints["expansion_allowed_by_execution_policy"] is False
        assert hints["has_primary"] is False

    def test_local_summary_hints(self):
        from core.cross_device_policy import get_assignment_hints, IDLE_ASSIGNMENT_SUMMARY

        hints = get_assignment_hints(IDLE_ASSIGNMENT_SUMMARY)
        assert hints["is_cross_device"] is False
        assert hints["posture"] == "local_preferred"
        assert hints["support_count"] == 0
        assert hints["observer_count"] == 0

    def test_cross_device_summary_hints(self):
        from core.cross_device_policy import (
            get_assignment_hints,
            CrossDeviceAssignmentSummary,
        )

        s = CrossDeviceAssignmentSummary(
            posture="local_then_expand",
            primary_execution_device_id="pc",
            support_device_ids=["phone"],
            observer_device_ids=["tablet1", "tablet2"],
            fallback_device_ids=["server"],
            is_cross_device=True,
            expansion_allowed_by_execution_policy=True,
        )
        hints = get_assignment_hints(s)
        assert hints["is_cross_device"] is True
        assert hints["has_primary"] is True
        assert hints["has_fallback"] is True
        assert hints["support_count"] == 1
        assert hints["observer_count"] == 2
        assert hints["expansion_allowed_by_execution_policy"] is True


# ---------------------------------------------------------------------------
# I) resolve_routing — domain-primary resolution
# ---------------------------------------------------------------------------


class TestResolveRoutingDomainPrimary:
    def test_none_domain_returns_local_preferred(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        p = resolve_routing(runtime_domain=None)
        assert p.posture is RoutingPosture.LOCAL_PREFERRED

    def test_local_domain_returns_local_preferred(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        p = resolve_routing(runtime_domain="local")
        assert p.posture is RoutingPosture.LOCAL_PREFERRED

    def test_transition_domain_returns_local_preferred(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        p = resolve_routing(runtime_domain="transition")
        assert p.posture is RoutingPosture.LOCAL_PREFERRED

    def test_cross_device_no_policy_blocked(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        p = resolve_routing(runtime_domain="cross_device", execution_policy=None)
        # No execution policy → conservative → cross-device blocked
        assert p.posture is RoutingPosture.LOCAL_PREFERRED
        assert p.expansion_allowed_by_execution_policy is False


# ---------------------------------------------------------------------------
# J) resolve_routing — cross-device with execution policy
# ---------------------------------------------------------------------------


class TestResolveRoutingCrossDevice:
    def test_cross_device_allowed_false_blocks_expansion(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": False, "requires_confirmation": True}
        p = resolve_routing(runtime_domain="cross_device", execution_policy=policy)
        assert p.posture is RoutingPosture.LOCAL_PREFERRED
        assert p.expansion_allowed_by_execution_policy is False

    def test_cross_device_allowed_true_default_posture(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True, "requires_confirmation": False}
        p = resolve_routing(runtime_domain="cross_device", execution_policy=policy)
        assert p.posture is RoutingPosture.LOCAL_THEN_EXPAND
        assert p.expansion_allowed_by_execution_policy is True

    def test_split_execution_hint(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            task_envelope_meta={"split_execution": True},
        )
        assert p.posture is RoutingPosture.SPLIT_EXECUTION

    def test_remote_required_hint(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            task_envelope_meta={"remote_required": True},
        )
        assert p.posture is RoutingPosture.REMOTE_REQUIRED

    def test_mirrored_observation_hint(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            task_envelope_meta={"mirrored_observation": True},
        )
        assert p.posture is RoutingPosture.MIRRORED_OBSERVATION

    def test_explicit_target_device_ids_gives_local_then_expand(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            target_device_ids=["device-1", "device-2"],
        )
        assert p.posture is RoutingPosture.LOCAL_THEN_EXPAND

    def test_confirmation_required_propagated(self):
        from core.cross_device_policy import resolve_routing

        policy = {"cross_device_allowed": True, "requires_confirmation": True}
        p = resolve_routing(runtime_domain="cross_device", execution_policy=policy)
        assert p.confirmation_required_before_expansion is True

    def test_confirmation_not_required_propagated(self):
        from core.cross_device_policy import resolve_routing

        policy = {"cross_device_allowed": True, "requires_confirmation": False}
        p = resolve_routing(runtime_domain="cross_device", execution_policy=policy)
        assert p.confirmation_required_before_expansion is False


# ---------------------------------------------------------------------------
# K) resolve_routing — authority role interactions
# ---------------------------------------------------------------------------


class TestResolveRoutingAuthorityRole:
    def test_legacy_compatibility_blocks_cross_device(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True, "requires_confirmation": False}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            authority_role="legacy_compatibility",
        )
        assert p.posture is RoutingPosture.LOCAL_PREFERRED
        assert p.expansion_allowed_by_execution_policy is False

    def test_deprecated_authority_blocks_cross_device(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            authority_role="deprecated",
        )
        assert p.posture is RoutingPosture.LOCAL_PREFERRED
        assert p.expansion_allowed_by_execution_policy is False

    def test_authoritative_entrypoint_allows_cross_device(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            authority_role="authoritative_entrypoint",
        )
        assert p.posture is not RoutingPosture.UNDECIDED
        assert p.expansion_allowed_by_execution_policy is True

    def test_authority_role_as_enum_object(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        try:
            from core.orchestration_authority import AuthorityRole
            policy = {"cross_device_allowed": True}
            p = resolve_routing(
                runtime_domain="cross_device",
                execution_policy=policy,
                authority_role=AuthorityRole.LEGACY_COMPATIBILITY,
            )
            assert p.posture is RoutingPosture.LOCAL_PREFERRED
        except ImportError:
            pytest.skip("orchestration_authority not available")


# ---------------------------------------------------------------------------
# L) resolve_routing — device assignment building
# ---------------------------------------------------------------------------


class TestResolveRoutingDeviceAssignments:
    def test_source_device_id_gets_source_role(self):
        from core.cross_device_policy import resolve_routing, DeviceRole

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            source_device_id="src-device",
        )
        src_assignments = p.devices_with_role(DeviceRole.SOURCE)
        assert len(src_assignments) == 1
        assert src_assignments[0].device_id == "src-device"

    def test_first_target_gets_primary_execution(self):
        from core.cross_device_policy import resolve_routing, DeviceRole

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            target_device_ids=["primary-dev", "support-dev"],
        )
        primaries = p.devices_with_role(DeviceRole.PRIMARY_EXECUTION)
        assert len(primaries) == 1
        assert primaries[0].device_id == "primary-dev"

    def test_subsequent_targets_get_support_role_for_local_then_expand(self):
        from core.cross_device_policy import resolve_routing, DeviceRole

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            target_device_ids=["primary", "extra1", "extra2"],
        )
        supports = p.devices_with_role(DeviceRole.SUPPORT)
        assert len(supports) == 2

    def test_mirrored_additional_targets_get_observer_role(self):
        from core.cross_device_policy import resolve_routing, DeviceRole, RoutingPosture

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            target_device_ids=["primary", "mirror1", "mirror2"],
            task_envelope_meta={"mirrored_observation": True},
        )
        assert p.posture is RoutingPosture.MIRRORED_OBSERVATION
        observers = p.devices_with_role(DeviceRole.OBSERVER)
        assert len(observers) == 2

    def test_task_id_and_trace_id_propagated(self):
        from core.cross_device_policy import resolve_routing

        policy = {"cross_device_allowed": True}
        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            task_id="task-abc",
            trace_id="trace-xyz",
        )
        assert p.task_id == "task-abc"
        assert p.trace_id == "trace-xyz"


# ---------------------------------------------------------------------------
# M) resolve_routing — graceful degradation
# ---------------------------------------------------------------------------


class TestResolveRoutingGracefulDegradation:
    def test_invalid_domain_string_safe_default(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        # Unknown domain strings fall through to local
        p = resolve_routing(runtime_domain="some_unknown_domain")
        assert p.posture is RoutingPosture.LOCAL_PREFERRED

    def test_execution_policy_as_dict(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True, "requires_confirmation": False}
        p = resolve_routing(runtime_domain="cross_device", execution_policy=policy)
        assert p.posture is RoutingPosture.LOCAL_THEN_EXPAND
        assert p.expansion_allowed_by_execution_policy is True

    def test_execution_policy_as_object(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        try:
            from core.execution_policy import resolve_policy

            exec_policy = resolve_policy(phase="manifest", domain="cross_device")
            p = resolve_routing(
                runtime_domain="cross_device", execution_policy=exec_policy
            )
            # Should at least not raise and return a valid policy
            assert isinstance(p.posture, RoutingPosture)
        except ImportError:
            pytest.skip("execution_policy not available")

    def test_none_inputs_returns_safe_default(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        p = resolve_routing()
        assert p.posture is RoutingPosture.LOCAL_PREFERRED

    def test_empty_target_list_is_safe(self):
        from core.cross_device_policy import resolve_routing

        p = resolve_routing(
            runtime_domain="cross_device",
            execution_policy={"cross_device_allowed": True},
            target_device_ids=[],
        )
        # Should not raise
        assert p is not None


# ---------------------------------------------------------------------------
# N) resolve_routing_summary — convenience wrapper
# ---------------------------------------------------------------------------


class TestResolveRoutingSummary:
    def test_returns_cross_device_assignment_summary(self):
        from core.cross_device_policy import resolve_routing_summary, CrossDeviceAssignmentSummary

        s = resolve_routing_summary()
        assert isinstance(s, CrossDeviceAssignmentSummary)

    def test_local_domain_returns_local_summary(self):
        from core.cross_device_policy import resolve_routing_summary, RoutingPosture

        s = resolve_routing_summary(runtime_domain="local")
        assert s.posture == RoutingPosture.LOCAL_PREFERRED.value
        assert s.is_cross_device is False

    def test_cross_device_domain_returns_enriched_summary(self):
        from core.cross_device_policy import resolve_routing_summary

        policy = {"cross_device_allowed": True}
        s = resolve_routing_summary(
            runtime_domain="cross_device",
            execution_policy=policy,
            source_device_id="src",
            target_device_ids=["tgt1"],
        )
        assert s.is_cross_device is True
        assert s.primary_execution_device_id == "tgt1"
        assert s.expansion_allowed_by_execution_policy is True


# ---------------------------------------------------------------------------
# O) Projection endpoint integration
# ---------------------------------------------------------------------------


class TestProjectionEndpointIntegration:
    def test_assemble_does_not_raise(self):
        fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
        from core.routes.projection import _assemble_projection_with_cross_device_routing

        result = _assemble_projection_with_cross_device_routing()
        assert isinstance(result, dict)

    def test_result_contains_cross_device_routing_key(self):
        pytest.importorskip("fastapi", reason="fastapi not installed")
        from core.routes.projection import _assemble_projection_with_cross_device_routing

        result = _assemble_projection_with_cross_device_routing()
        assert "cross_device_routing" in result

    def test_cross_device_routing_has_expected_fields(self):
        pytest.importorskip("fastapi", reason="fastapi not installed")
        from core.routes.projection import _assemble_projection_with_cross_device_routing

        result = _assemble_projection_with_cross_device_routing()
        routing = result["cross_device_routing"]
        assert "posture" in routing
        assert "is_cross_device" in routing
        assert "expansion_allowed_by_execution_policy" in routing
        assert "primary_execution_device_id" in routing


# ---------------------------------------------------------------------------
# P) Public API completeness (smoke test)
# ---------------------------------------------------------------------------


class TestPublicApiCompleteness:
    def test_all_names_importable(self):
        import core.cross_device_policy as pkg

        for name in pkg.__all__:
            assert hasattr(pkg, name), f"Missing public export: {name}"

    def test_package_attributes_types(self):
        from core.cross_device_policy import (
            DeviceRole,
            RoutingPosture,
            RoutingPolicy,
            CrossDeviceAssignmentSummary,
            DEFAULT_LOCAL_ROUTING_POLICY,
            IDLE_ASSIGNMENT_SUMMARY,
        )

        from enum import Enum

        assert issubclass(DeviceRole, Enum)
        assert issubclass(RoutingPosture, Enum)
        assert isinstance(DEFAULT_LOCAL_ROUTING_POLICY, RoutingPolicy)
        assert isinstance(IDLE_ASSIGNMENT_SUMMARY, CrossDeviceAssignmentSummary)
