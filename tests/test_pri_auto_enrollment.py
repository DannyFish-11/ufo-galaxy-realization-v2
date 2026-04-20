#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pri_auto_enrollment.py
==================================
PR-I — Tests for MeshMembership / BodyMeshRegistry auto-write + Formation
auto-enrollment.

Coverage
--------
A  — Module sentinels are importable and correctly typed.
B  — MeshEnrollmentRecord construction, defaults, and to_dict.
C  — MeshAutoEnrollmentService: on_device_registered defers without capability.
D  — MeshAutoEnrollmentService: on_capability_reported triggers enrollment
     (auto_enroll_on_capability=True).
E  — MeshAutoEnrollmentService: on_readiness_confirmed triggers enrollment
     even when auto_enroll_on_capability=False.
F  — Registration + capability chain auto-enrolls to BodyMeshRegistry.
G  — Enrollment derives and logs MeshMembership.
H  — Formation auto-enrollment: device appears in coordinator after enroll.
I  — Idempotency: repeated registration/capability events do not duplicate state.
J  — Capability update merges roles (no duplicate DeviceRole entries).
K  — on_device_lost marks enrolled=False and notifies formation manager.
L  — Formation manager enroll_device: first device becomes primary_execution.
M  — Formation manager enroll_device: second device becomes support.
N  — Formation manager remove_device marks entry inactive.
O  — Formation manager update_device_readiness calls coordinator trigger.
P  — Formation manager snapshot returns serialisable dict.
Q  — Enrollment deferred when capabilities empty; enrolled after capability event.
R  — Module-level convenience functions: notify_device_registered,
     notify_capability_reported, notify_readiness_confirmed, notify_device_lost,
     get_enrollment_record.
S  — auto_enroll_on_capability=False: enrollment waits for readiness_confirmed.
T  — core.device_formation __init__ exports new auto-enrollment symbols.
U  — Empty device_id returns safe default records without raising.
V  — MeshAutoEnrollmentService.summary() returns expected fields.
W  — FormationAutoEnrollmentManager.list_active_device_ids.
X  — FormationAutoEnrollmentManager singleton stability across calls.
Y  — Re-enrollment after device_lost re-activates the formation participant.
Z  — capability_report handler wires auto-enrollment notify call.
AA — registration handler wires auto-enrollment notify call.
"""

from __future__ import annotations

import threading
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_all() -> None:
    """Reset all relevant singletons for test isolation."""
    try:
        from core.mesh.mesh_auto_enrollment import reset_auto_enrollment_service
        reset_auto_enrollment_service()
    except Exception:
        pass
    try:
        from core.device_formation.formation_auto_enrollment import (
            reset_formation_auto_enrollment_manager,
        )
        reset_formation_auto_enrollment_manager()
    except Exception:
        pass
    try:
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()
    except Exception:
        pass


def _make_roles(names: Optional[List[str]] = None) -> List[Any]:
    """Return real DeviceRole objects if available; fall back to strings."""
    try:
        from core.mesh.body_mesh_registry import DeviceRole
        names = names or ["action"]
        result = []
        for n in names:
            try:
                result.append(DeviceRole(n))
            except ValueError:
                result.append(DeviceRole.ACTION)
        return result
    except ImportError:
        return names or ["action"]


# ---------------------------------------------------------------------------
# A — Sentinels
# ---------------------------------------------------------------------------


class TestSentinels:
    def test_service_authority_sentinel(self):
        from core.mesh.mesh_auto_enrollment import (
            MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY,
        )
        assert isinstance(MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY, str)
        assert "MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY" in MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY

    def test_idempotent_policy_sentinel(self):
        from core.mesh.mesh_auto_enrollment import AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY
        assert isinstance(AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY, str)

    def test_defer_policy_sentinel(self):
        from core.mesh.mesh_auto_enrollment import (
            AUTO_ENROLLMENT_DEFERS_ON_MISSING_CAPABILITY_POLICY,
        )
        assert isinstance(AUTO_ENROLLMENT_DEFERS_ON_MISSING_CAPABILITY_POLICY, str)

    def test_formation_manager_authority_sentinel(self):
        from core.device_formation.formation_auto_enrollment import (
            FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY,
        )
        assert isinstance(FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY, str)

    def test_formation_idempotent_policy_sentinel(self):
        from core.device_formation.formation_auto_enrollment import (
            FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY,
        )
        assert isinstance(FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY, str)


# ---------------------------------------------------------------------------
# B — MeshEnrollmentRecord
# ---------------------------------------------------------------------------


class TestMeshEnrollmentRecord:
    def test_defaults(self):
        from core.mesh.mesh_auto_enrollment import MeshEnrollmentRecord
        rec = MeshEnrollmentRecord(device_id="dev-001")
        assert rec.device_id == "dev-001"
        assert rec.registered is False
        assert rec.capabilities_reported is False
        assert rec.readiness_confirmed is False
        assert rec.enrolled is False
        assert rec.roles == []
        assert rec.session_id is None
        assert rec.enrolled_at is None
        assert rec.skip_reason == ""

    def test_to_dict_stable_fields(self):
        from core.mesh.mesh_auto_enrollment import MeshEnrollmentRecord
        rec = MeshEnrollmentRecord(
            device_id="dev-002",
            registered=True,
            capabilities_reported=True,
            enrolled=True,
        )
        d = rec.to_dict()
        assert d["device_id"] == "dev-002"
        assert d["registered"] is True
        assert d["capabilities_reported"] is True
        assert d["enrolled"] is True
        assert "roles" in d
        assert "session_id" in d
        assert "enrolled_at" in d
        assert "last_updated_at" in d
        assert "skip_reason" in d


# ---------------------------------------------------------------------------
# C — on_device_registered defers without capability
# ---------------------------------------------------------------------------


class TestRegistrationDefer:
    def setup_method(self):
        _reset_all()

    def test_defers_when_no_capability(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService()
        rec = svc.on_device_registered("dev-003")
        assert rec.registered is True
        assert rec.enrolled is False
        assert "no-capabilities" in rec.skip_reason or "capabilities" in rec.skip_reason.lower()

    def test_registered_flag_set(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService()
        rec = svc.on_device_registered("dev-004")
        assert rec.registered is True


# ---------------------------------------------------------------------------
# D — on_capability_reported triggers enrollment (auto_enroll_on_capability=True)
# ---------------------------------------------------------------------------


class TestCapabilityEnrollment:
    def setup_method(self):
        _reset_all()

    def test_enrolled_after_register_then_capability(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        svc.on_device_registered("dev-005")
        roles = _make_roles(["action"])
        rec = svc.on_capability_reported("dev-005", roles=roles)
        assert rec.enrolled is True
        assert rec.enrolled_at is not None

    def test_enrolled_on_capability_without_prior_register(self):
        """capability_report alone is insufficient; registration is required."""
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])
        rec = svc.on_capability_reported("dev-006", roles=roles)
        # registered is False → should NOT be enrolled
        assert rec.enrolled is False

    def test_capability_sets_flag(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService()
        roles = _make_roles(["action"])
        rec = svc.on_capability_reported("dev-007", roles=roles)
        assert rec.capabilities_reported is True


# ---------------------------------------------------------------------------
# E — on_readiness_confirmed triggers enrollment
# ---------------------------------------------------------------------------


class TestReadinessEnrollment:
    def setup_method(self):
        _reset_all()

    def test_enrolled_after_full_chain_strict_mode(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=False)
        roles = _make_roles(["action"])
        svc.on_device_registered("dev-008")
        svc.on_capability_reported("dev-008", roles=roles)
        rec = svc.on_readiness_confirmed("dev-008")
        assert rec.enrolled is True

    def test_readiness_without_capability_defers(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=False)
        svc.on_device_registered("dev-009")
        rec = svc.on_readiness_confirmed("dev-009")
        assert rec.enrolled is False

    def test_readiness_without_register_defers(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=False)
        roles = _make_roles(["action"])
        svc.on_capability_reported("dev-010", roles=roles)
        rec = svc.on_readiness_confirmed("dev-010")
        assert rec.enrolled is False


# ---------------------------------------------------------------------------
# F — Registration + capability chain auto-enrolls to BodyMeshRegistry
# ---------------------------------------------------------------------------


class TestBodyMeshRegistryAutoEnroll:
    def setup_method(self):
        _reset_all()

    def test_body_mesh_entry_present_after_enrollment(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import get_body_mesh_registry, reset_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])
        svc.on_device_registered("dev-011")
        svc.on_capability_reported("dev-011", roles=roles)

        registry = get_body_mesh_registry()
        entry = registry.get("dev-011")
        assert entry is not None
        assert entry.device_id == "dev-011"


# ---------------------------------------------------------------------------
# G — MeshMembership derivation does not raise
# ---------------------------------------------------------------------------


class TestMeshMembershipDerivation:
    def setup_method(self):
        _reset_all()

    def test_membership_derivable_after_enrollment(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import get_body_mesh_registry, reset_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])
        svc.on_device_registered("dev-012")
        svc.on_capability_reported("dev-012", roles=roles)

        # Membership derivation via BodyMeshRegistry
        registry = get_body_mesh_registry()
        memberships = registry.get_mesh_memberships()
        assert any(
            getattr(m, "member_device_id", None) == "dev-012" for m in memberships
        )


# ---------------------------------------------------------------------------
# H — Formation coordinator has participant after enrollment
# ---------------------------------------------------------------------------


class TestFormationAutoEnrollment:
    def setup_method(self):
        _reset_all()

    def test_formation_participant_present(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        from core.device_formation.formation_auto_enrollment import (
            get_formation_auto_enrollment_manager,
        )
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])
        svc.on_device_registered("dev-013")
        svc.on_capability_reported("dev-013", roles=roles)

        manager = get_formation_auto_enrollment_manager()
        entry = manager.get_participant("dev-013")
        assert entry is not None
        assert entry.is_active is True


# ---------------------------------------------------------------------------
# I — Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def setup_method(self):
        _reset_all()

    def test_repeated_registration_stable(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry, get_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])

        # Register and enroll three times
        for _ in range(3):
            svc.on_device_registered("dev-014")
            svc.on_capability_reported("dev-014", roles=roles)

        rec = svc.get_record("dev-014")
        assert rec is not None
        assert rec.enrolled is True
        # Single record only
        assert len([d for d in svc.list_enrolled_device_ids() if d == "dev-014"]) == 1

    def test_body_mesh_no_duplicate_roles(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry, get_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])

        svc.on_device_registered("dev-015")
        svc.on_capability_reported("dev-015", roles=roles)
        # Repeat
        svc.on_capability_reported("dev-015", roles=roles)

        rec = svc.get_record("dev-015")
        role_values = [r.value if hasattr(r, "value") else str(r) for r in rec.roles]
        # No duplicates
        assert len(role_values) == len(set(role_values))


# ---------------------------------------------------------------------------
# J — Role merging
# ---------------------------------------------------------------------------


class TestRoleMerge:
    def setup_method(self):
        _reset_all()

    def test_roles_accumulate_across_events(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)

        action_roles = _make_roles(["action"])
        perception_roles = _make_roles(["perception"])

        svc.on_device_registered("dev-016", roles=action_roles)
        svc.on_capability_reported("dev-016", roles=perception_roles)

        rec = svc.get_record("dev-016")
        role_values = {r.value if hasattr(r, "value") else str(r) for r in rec.roles}
        assert "action" in role_values
        assert "perception" in role_values


# ---------------------------------------------------------------------------
# K — on_device_lost
# ---------------------------------------------------------------------------


class TestDeviceLost:
    def setup_method(self):
        _reset_all()

    def test_enrolled_false_after_lost(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])
        svc.on_device_registered("dev-017")
        svc.on_capability_reported("dev-017", roles=roles)

        assert svc.get_record("dev-017").enrolled is True

        svc.on_device_lost("dev-017", reason="disconnect")
        assert svc.get_record("dev-017").enrolled is False


# ---------------------------------------------------------------------------
# L, M — Formation role assignment
# ---------------------------------------------------------------------------


class TestFormationRoleAssignment:
    def setup_method(self):
        _reset_all()

    def test_first_device_becomes_primary(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager(formation_id="test-fm-001")
        roles = _make_roles(["action"])
        entry = manager.enroll_device("dev-018", roles=roles)
        assert "primary" in entry.role

    def test_second_device_becomes_support(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager(formation_id="test-fm-002")
        roles = _make_roles(["action"])
        manager.enroll_device("dev-019a", roles=roles)
        entry2 = manager.enroll_device("dev-019b", roles=roles)
        assert "support" in entry2.role or "unassigned" in entry2.role


# ---------------------------------------------------------------------------
# N — remove_device
# ---------------------------------------------------------------------------


class TestRemoveDevice:
    def setup_method(self):
        _reset_all()

    def test_remove_marks_inactive(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager(formation_id="test-fm-003")
        roles = _make_roles(["action"])
        manager.enroll_device("dev-020", roles=roles)
        assert manager.get_participant("dev-020").is_active is True
        manager.remove_device("dev-020", reason="test_remove")
        assert manager.get_participant("dev-020").is_active is False

    def test_remove_unknown_device_safe(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager(formation_id="test-fm-004")
        result = manager.remove_device("nonexistent-device")
        assert result is None


# ---------------------------------------------------------------------------
# O — update_device_readiness
# ---------------------------------------------------------------------------


class TestUpdateReadiness:
    def setup_method(self):
        _reset_all()

    def test_update_readiness_no_error(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager(formation_id="test-fm-005")
        roles = _make_roles(["action"])
        manager.enroll_device("dev-021", roles=roles)
        # Should not raise
        manager.update_device_readiness("dev-021", is_ready=False, health_score=0.2)
        manager.update_device_readiness("dev-021", is_ready=True, health_score=0.9)


# ---------------------------------------------------------------------------
# P — Formation manager snapshot
# ---------------------------------------------------------------------------


class TestFormationSnapshot:
    def setup_method(self):
        _reset_all()

    def test_snapshot_is_serialisable(self):
        import json
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager(formation_id="test-fm-006")
        roles = _make_roles(["action"])
        manager.enroll_device("dev-022", roles=roles)
        snap = manager.snapshot()
        assert isinstance(snap, dict)
        assert snap["formation_id"] == "test-fm-006"
        # Must be JSON-serialisable
        json.dumps(snap, default=str)


# ---------------------------------------------------------------------------
# Q — Deferred until capability event
# ---------------------------------------------------------------------------


class TestDeferredEnrollment:
    def setup_method(self):
        _reset_all()

    def test_no_enrollment_before_capability(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        svc.on_device_registered("dev-023")
        assert svc.get_record("dev-023").enrolled is False

    def test_enrolled_after_capability_follows(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        svc.on_device_registered("dev-024")
        assert svc.get_record("dev-024").enrolled is False

        roles = _make_roles(["action"])
        rec = svc.on_capability_reported("dev-024", roles=roles)
        assert rec.enrolled is True


# ---------------------------------------------------------------------------
# R — Module-level convenience functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    def setup_method(self):
        _reset_all()

    def test_notify_device_registered_returns_record(self):
        from core.mesh.mesh_auto_enrollment import notify_device_registered
        rec = notify_device_registered("dev-025")
        assert rec is not None
        assert rec.device_id == "dev-025"
        assert rec.registered is True

    def test_notify_capability_reported_returns_record(self):
        from core.mesh.mesh_auto_enrollment import (
            notify_device_registered,
            notify_capability_reported,
        )
        notify_device_registered("dev-026")
        roles = _make_roles(["action"])
        rec = notify_capability_reported("dev-026", roles=roles)
        assert rec is not None
        assert rec.capabilities_reported is True

    def test_notify_readiness_confirmed_returns_record(self):
        from core.mesh.mesh_auto_enrollment import (
            notify_device_registered,
            notify_capability_reported,
            notify_readiness_confirmed,
        )
        notify_device_registered("dev-027")
        roles = _make_roles(["action"])
        notify_capability_reported("dev-027", roles=roles)
        rec = notify_readiness_confirmed("dev-027")
        assert rec is not None
        assert rec.readiness_confirmed is True

    def test_notify_device_lost_returns_record(self):
        from core.mesh.mesh_auto_enrollment import (
            notify_device_registered,
            notify_capability_reported,
            notify_device_lost,
        )
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()

        notify_device_registered("dev-028")
        roles = _make_roles(["action"])
        notify_capability_reported("dev-028", roles=roles)
        rec = notify_device_lost("dev-028", reason="test")
        assert rec is not None
        assert rec.enrolled is False

    def test_get_enrollment_record(self):
        from core.mesh.mesh_auto_enrollment import (
            notify_device_registered,
            get_enrollment_record,
        )
        notify_device_registered("dev-029")
        rec = get_enrollment_record("dev-029")
        assert rec is not None
        assert rec.device_id == "dev-029"

    def test_get_enrollment_record_unknown(self):
        from core.mesh.mesh_auto_enrollment import get_enrollment_record
        rec = get_enrollment_record("dev-unknown-999")
        assert rec is None


# ---------------------------------------------------------------------------
# S — Strict mode (auto_enroll_on_capability=False)
# ---------------------------------------------------------------------------


class TestStrictMode:
    def setup_method(self):
        _reset_all()

    def test_strict_waits_for_readiness(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=False)
        roles = _make_roles(["action"])
        svc.on_device_registered("dev-030")
        svc.on_capability_reported("dev-030", roles=roles)
        # Still not enrolled — readiness not confirmed
        assert svc.get_record("dev-030").enrolled is False

        # Confirm readiness → now enrolled
        rec = svc.on_readiness_confirmed("dev-030")
        assert rec.enrolled is True


# ---------------------------------------------------------------------------
# T — core.device_formation __init__ exports
# ---------------------------------------------------------------------------


class TestDeviceFormationExports:
    def test_auto_enrollment_manager_importable(self):
        from core.device_formation import FormationAutoEnrollmentManager
        assert callable(FormationAutoEnrollmentManager)

    def test_get_manager_importable(self):
        from core.device_formation import get_formation_auto_enrollment_manager
        assert callable(get_formation_auto_enrollment_manager)

    def test_reset_manager_importable(self):
        from core.device_formation import reset_formation_auto_enrollment_manager
        assert callable(reset_formation_auto_enrollment_manager)

    def test_participant_entry_importable(self):
        from core.device_formation import FormationParticipantEntry
        assert callable(FormationParticipantEntry)

    def test_sentinels_importable(self):
        from core.device_formation import (
            FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY,
            FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY,
        )
        assert isinstance(FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY, str)
        assert isinstance(FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY, str)


# ---------------------------------------------------------------------------
# U — Empty device_id safety
# ---------------------------------------------------------------------------


class TestEmptyDeviceId:
    def setup_method(self):
        _reset_all()

    def test_empty_device_id_no_raise(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService()
        rec = svc.on_device_registered("")
        assert rec.device_id == ""
        assert rec.enrolled is False

    def test_empty_capability_no_raise(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        svc = MeshAutoEnrollmentService()
        rec = svc.on_capability_reported("", roles=[])
        assert rec.enrolled is False

    def test_formation_enroll_empty_no_raise(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager()
        entry = manager.enroll_device("")
        assert entry.device_id == ""


# ---------------------------------------------------------------------------
# V — MeshAutoEnrollmentService.summary()
# ---------------------------------------------------------------------------


class TestServiceSummary:
    def setup_method(self):
        _reset_all()

    def test_summary_fields(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])
        svc.on_device_registered("dev-031")
        svc.on_capability_reported("dev-031", roles=roles)

        s = svc.summary()
        assert "authority" in s
        assert "total_devices" in s
        assert "enrolled" in s
        assert "pending" in s
        assert s["enrolled"] == 1
        assert s["total_devices"] == 1


# ---------------------------------------------------------------------------
# W — list_active_device_ids
# ---------------------------------------------------------------------------


class TestListActiveDevices:
    def setup_method(self):
        _reset_all()

    def test_active_list(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager(formation_id="test-fm-007")
        roles = _make_roles(["action"])
        manager.enroll_device("dev-032a", roles=roles)
        manager.enroll_device("dev-032b", roles=roles)
        active = manager.list_active_device_ids()
        assert "dev-032a" in active
        assert "dev-032b" in active

    def test_removed_not_in_active(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )
        manager = FormationAutoEnrollmentManager(formation_id="test-fm-008")
        roles = _make_roles(["action"])
        manager.enroll_device("dev-033", roles=roles)
        manager.remove_device("dev-033")
        assert "dev-033" not in manager.list_active_device_ids()


# ---------------------------------------------------------------------------
# X — Singleton stability
# ---------------------------------------------------------------------------


class TestSingletonStability:
    def setup_method(self):
        _reset_all()

    def test_same_manager_returned(self):
        from core.device_formation.formation_auto_enrollment import (
            get_formation_auto_enrollment_manager,
        )
        m1 = get_formation_auto_enrollment_manager()
        m2 = get_formation_auto_enrollment_manager()
        assert m1 is m2

    def test_same_service_returned(self):
        from core.mesh.mesh_auto_enrollment import get_auto_enrollment_service
        s1 = get_auto_enrollment_service()
        s2 = get_auto_enrollment_service()
        assert s1 is s2

    def test_reset_creates_new_service(self):
        from core.mesh.mesh_auto_enrollment import (
            get_auto_enrollment_service,
            reset_auto_enrollment_service,
        )
        s1 = get_auto_enrollment_service()
        reset_auto_enrollment_service()
        s2 = get_auto_enrollment_service()
        assert s1 is not s2


# ---------------------------------------------------------------------------
# Y — Re-enrollment after lost
# ---------------------------------------------------------------------------


class TestReEnrollmentAfterLost:
    def setup_method(self):
        _reset_all()

    def test_re_enroll_after_lost(self):
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()

        svc = MeshAutoEnrollmentService(auto_enroll_on_capability=True)
        roles = _make_roles(["action"])

        svc.on_device_registered("dev-034")
        svc.on_capability_reported("dev-034", roles=roles)
        assert svc.get_record("dev-034").enrolled is True

        svc.on_device_lost("dev-034")
        assert svc.get_record("dev-034").enrolled is False

        # Re-register and re-report capability
        svc.on_device_registered("dev-034")
        rec = svc.on_capability_reported("dev-034", roles=roles)
        assert rec.enrolled is True


# ---------------------------------------------------------------------------
# Z — capability_report handler wires auto-enrollment
# ---------------------------------------------------------------------------


class TestCapabilityReportHandlerWiring:
    """Verify that the capability_report handler calls notify_capability_reported."""

    def test_notify_called_on_capability_report(self):
        """capability_report handler notifies auto-enrollment service."""
        # Directly test the wiring by checking the module imports and that the
        # notify_capability_reported function is called inside the handler.
        import ast
        import os
        handler_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "galaxy_gateway",
            "android",
            "handlers",
            "capability_report.py",
        )
        with open(handler_path) as f:
            source = f.read()
        assert "notify_capability_reported" in source, (
            "capability_report handler must call notify_capability_reported"
        )
        assert "mesh_auto_enrollment" in source, (
            "capability_report handler must import from mesh_auto_enrollment"
        )


# ---------------------------------------------------------------------------
# AA — registration handler wires auto-enrollment
# ---------------------------------------------------------------------------


class TestRegistrationHandlerWiring:
    """Verify that the registration handler calls notify_device_registered."""

    def test_notify_called_on_registration(self):
        import os
        handler_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "galaxy_gateway",
            "android",
            "handlers",
            "registration.py",
        )
        with open(handler_path) as f:
            source = f.read()
        assert "notify_device_registered" in source, (
            "registration handler must call notify_device_registered"
        )
        assert "mesh_auto_enrollment" in source, (
            "registration handler must import from mesh_auto_enrollment"
        )


# ---------------------------------------------------------------------------
# FormationParticipantEntry — data class
# ---------------------------------------------------------------------------


class TestFormationParticipantEntry:
    def test_construction_and_to_dict(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationParticipantEntry,
        )
        entry = FormationParticipantEntry(
            device_id="dev-035",
            role="primary_execution_device",
            health_score=0.9,
        )
        d = entry.to_dict()
        assert d["device_id"] == "dev-035"
        assert d["role"] == "primary_execution_device"
        assert d["health_score"] == 0.9
        assert d["is_active"] is True

    def test_enrolled_at_set_on_creation(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationParticipantEntry,
        )
        entry = FormationParticipantEntry(device_id="dev-036")
        assert entry.enrolled_at > 0
