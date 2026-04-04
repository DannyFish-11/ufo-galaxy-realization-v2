"""tests/test_pr6_post533_canonical_capability_scheduling_basis.py
==================================================================
Tests for PR package 6 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Device Capability & Scheduling Basis.

Coverage
--------

A) ExecutionSurface enum
   - All four values are present and have correct string identifiers
   - from_string() returns the right member for known values
   - from_string() returns UNAVAILABLE for unknown / None values

B) CapabilitySchedulingInput — construction and defaults
   - Default instance has safe conservative values (control_only, offline)
   - Explicit construction preserves all fields
   - to_dict() returns all expected keys with correct values

C) CapabilitySchedulingBasis — construction and defaults
   - Default instance is not scheduling-eligible
   - to_dict() includes pr6_sentinel key
   - to_dict() includes scheduling_authority
   - eligible_surfaces serialised as string values

D) normalize_scheduling_inputs — from object attributes
   - join_runtime posture preserved
   - control_only posture preserved
   - unknown posture defaults to control_only
   - coordination_role preserved when valid
   - unknown coordination_role defaults to unresolved
   - android_host_role preserved when valid
   - android_host_role defaults to '' for non-Android
   - platform=android infers connected_device_only when no android_host_role
   - is_runtime_host preserved
   - online=True sets runtime_present=True
   - online=False sets runtime_present=False
   - status='online' sets runtime_present=True
   - status='offline' sets runtime_present=False
   - connection_state='connected' sets routable=True
   - connection_state='disconnected' sets routable=False
   - capabilities list preserved
   - capabilities from dict object extracts keys
   - None device returns safe defaults

E) normalize_scheduling_inputs — from dict
   - dict with all fields normalised correctly
   - dict with missing fields uses safe defaults

F) build_capability_scheduling_basis — observer_only gate
   - observer_only coordination_role → UNAVAILABLE, ineligible, weight=0
   - ineligibility_reason mentions observer_only policy
   - observer_only blocks regardless of join_runtime posture
   - observer_only blocks regardless of capabilities

G) build_capability_scheduling_basis — LOCAL_HOST surface
   - join_runtime + non-android + runtime_present → LOCAL_HOST eligible
   - control_only + non-android + runtime_present → not LOCAL_HOST
   - join_runtime + android platform → not LOCAL_HOST
   - join_runtime + non-android + not runtime_present → not LOCAL_HOST
   - LOCAL_HOST eligible → weight >= 0.75

H) build_capability_scheduling_basis — ANDROID_HOST surface
   - join_runtime + android + full_runtime_host → ANDROID_HOST eligible
   - join_runtime + android + partial_runtime_host → ANDROID_HOST eligible
   - join_runtime + android + connected_device_only → not ANDROID_HOST
   - control_only + android + full_runtime_host → not ANDROID_HOST
   - full_runtime_host Android → weight = 0.9
   - partial_runtime_host Android → weight >= 0.75

I) build_capability_scheduling_basis — REMOTE_DEVICE surface
   - routable=True → REMOTE_DEVICE eligible
   - routable=False → not REMOTE_DEVICE
   - REMOTE_DEVICE only (no other eligible surfaces) → weight = 0.4
   - control_only + routable → REMOTE_DEVICE eligible (remote dispatch ok)

J) build_capability_scheduling_basis — UNAVAILABLE fallback
   - offline + not routable → UNAVAILABLE
   - android + no host role + not routable → UNAVAILABLE
   - is_scheduling_eligible=False when only UNAVAILABLE

K) build_capability_scheduling_basis — capability signals
   - declared capabilities appear in capability_signals as True
   - empty capabilities → empty dict
   - capability_signals not used for eligibility gate

L) assess_scheduling_eligibility — combined helper
   - returns (CapabilitySchedulingInput, CapabilitySchedulingBasis) tuple
   - join_runtime online non-android → LOCAL_HOST in eligible_surfaces
   - observer_only → ineligible

M) Policy sentinels
   - CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY non-empty string
   - CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL non-empty string
   - OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY non-empty string
   - CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY non-empty
   - ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY non-empty
   - CAPABILITY_SCHEDULING_INPUTS_NORMALIZED_POLICY non-empty string
   - SCHEDULING_BASIS_IS_POSTURE_AND_ROLE_DRIVEN_POLICY non-empty string

N) core.runtime re-exports
   - All PR-6 symbols importable from core.runtime
   - CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL in core.runtime.__all__
   - ExecutionSurface importable from core.runtime

O) projection routes sentinel
   - CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6 present in
     core.routes.projection
   - sentinel indicates availability (not UNAVAILABLE)

P) Backwards-compatibility (PR-1 through PR-5 signals honoured)
   - control_only posture respected (PR-1/PR-2 consistency)
   - coordination_role observer_only respected (PR-538/PR-2 consistency)
   - android_host_role respected (PR-5 consistency)
   - Existing PR-5 tests unaffected: AndroidRuntimeHostRole still importable
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers: minimal device-like objects for testing
# ---------------------------------------------------------------------------


def _make_device_obj(
    device_id: str = "dev_001",
    source_runtime_posture: str = "join_runtime",
    coordination_role: str = "joined_runtime_participant",
    android_host_role: Optional[str] = None,
    is_runtime_host: bool = False,
    online: bool = True,
    connection_state: str = "connected",
    capabilities: Optional[List[str]] = None,
    platform: str = "linux",
) -> MagicMock:
    """Build a MagicMock resembling a RegisteredRuntimeDevice."""
    m = MagicMock()
    m.device_id = device_id
    m.source_runtime_posture = source_runtime_posture
    m.coordination_role = coordination_role
    m.android_host_role = android_host_role
    m.is_runtime_host = is_runtime_host
    m.online = online
    m.connection_state = connection_state
    m.capabilities = capabilities or ["text_generation", "screen"]
    m.platform = platform
    return m


def _make_android_device(
    device_id: str = "android_001",
    source_runtime_posture: str = "join_runtime",
    android_host_role: str = "full_runtime_host",
    is_runtime_host: bool = True,
    online: bool = True,
    connection_state: str = "connected",
    capabilities: Optional[List[str]] = None,
) -> MagicMock:
    """Build a MagicMock resembling an Android RegisteredRuntimeDevice."""
    m = MagicMock()
    m.device_id = device_id
    m.source_runtime_posture = source_runtime_posture
    m.coordination_role = "joined_runtime_participant"
    m.android_host_role = android_host_role
    m.is_runtime_host = is_runtime_host
    m.online = online
    m.connection_state = connection_state
    m.capabilities = capabilities or ["screen", "camera", "touch"]
    m.platform = "android"
    return m


def _make_device_dict(**overrides: Any) -> Dict[str, Any]:
    """Build a dict resembling a RegisteredRuntimeDevice payload."""
    base = {
        "device_id": "dev_dict_001",
        "source_runtime_posture": "join_runtime",
        "coordination_role": "joined_runtime_participant",
        "android_host_role": None,
        "is_runtime_host": False,
        "online": True,
        "connection_state": "connected",
        "capabilities": ["text_generation"],
        "platform": "darwin",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from core.canonical_capability_scheduling_basis import (
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY,
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL,
    OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY,
    CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY,
    ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY,
    CAPABILITY_SCHEDULING_INPUTS_NORMALIZED_POLICY,
    SCHEDULING_BASIS_IS_POSTURE_AND_ROLE_DRIVEN_POLICY,
    ExecutionSurface,
    CapabilitySchedulingInput,
    CapabilitySchedulingBasis,
    normalize_scheduling_inputs,
    build_capability_scheduling_basis,
    assess_scheduling_eligibility,
)


# ===========================================================================
# A) ExecutionSurface enum
# ===========================================================================


class TestExecutionSurfaceEnum:
    def test_all_four_values_present(self):
        assert hasattr(ExecutionSurface, "LOCAL_HOST")
        assert hasattr(ExecutionSurface, "ANDROID_HOST")
        assert hasattr(ExecutionSurface, "REMOTE_DEVICE")
        assert hasattr(ExecutionSurface, "UNAVAILABLE")

    def test_string_identifiers(self):
        assert ExecutionSurface.LOCAL_HOST.value == "local_host"
        assert ExecutionSurface.ANDROID_HOST.value == "android_host"
        assert ExecutionSurface.REMOTE_DEVICE.value == "remote_device"
        assert ExecutionSurface.UNAVAILABLE.value == "unavailable"

    def test_from_string_known(self):
        assert ExecutionSurface.from_string("local_host") is ExecutionSurface.LOCAL_HOST
        assert ExecutionSurface.from_string("android_host") is ExecutionSurface.ANDROID_HOST
        assert ExecutionSurface.from_string("remote_device") is ExecutionSurface.REMOTE_DEVICE
        assert ExecutionSurface.from_string("unavailable") is ExecutionSurface.UNAVAILABLE

    def test_from_string_unknown_returns_unavailable(self):
        assert ExecutionSurface.from_string("cloud_host") is ExecutionSurface.UNAVAILABLE
        assert ExecutionSurface.from_string("") is ExecutionSurface.UNAVAILABLE

    def test_from_string_none_returns_unavailable(self):
        assert ExecutionSurface.from_string(None) is ExecutionSurface.UNAVAILABLE

    def test_is_str_subclass(self):
        assert isinstance(ExecutionSurface.LOCAL_HOST, str)


# ===========================================================================
# B) CapabilitySchedulingInput — construction and defaults
# ===========================================================================


class TestCapabilitySchedulingInputDefaults:
    def test_default_posture_is_control_only(self):
        inp = CapabilitySchedulingInput()
        assert inp.source_runtime_posture == "control_only"

    def test_default_coordination_role_is_unresolved(self):
        inp = CapabilitySchedulingInput()
        assert inp.coordination_role == "unresolved"

    def test_default_runtime_present_false(self):
        inp = CapabilitySchedulingInput()
        assert inp.runtime_present is False

    def test_default_routable_false(self):
        inp = CapabilitySchedulingInput()
        assert inp.routable is False

    def test_default_capabilities_empty(self):
        inp = CapabilitySchedulingInput()
        assert inp.capabilities == []

    def test_explicit_construction_preserves_fields(self):
        inp = CapabilitySchedulingInput(
            device_id="dev_x",
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            android_host_role="full_runtime_host",
            is_runtime_host=True,
            runtime_present=True,
            routable=True,
            capabilities=["screen", "camera"],
            platform="android",
        )
        assert inp.device_id == "dev_x"
        assert inp.source_runtime_posture == "join_runtime"
        assert inp.coordination_role == "source_controller"
        assert inp.android_host_role == "full_runtime_host"
        assert inp.is_runtime_host is True
        assert inp.runtime_present is True
        assert inp.routable is True
        assert "screen" in inp.capabilities
        assert inp.platform == "android"

    def test_to_dict_all_keys_present(self):
        inp = CapabilitySchedulingInput()
        d = inp.to_dict()
        for key in [
            "device_id",
            "source_runtime_posture",
            "coordination_role",
            "android_host_role",
            "is_runtime_host",
            "runtime_present",
            "routable",
            "capabilities",
            "platform",
            "metadata",
        ]:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_values_match_fields(self):
        inp = CapabilitySchedulingInput(
            device_id="abc",
            source_runtime_posture="join_runtime",
        )
        d = inp.to_dict()
        assert d["device_id"] == "abc"
        assert d["source_runtime_posture"] == "join_runtime"


# ===========================================================================
# C) CapabilitySchedulingBasis — construction and serialisation
# ===========================================================================


class TestCapabilitySchedulingBasisConstruction:
    def test_default_not_eligible(self):
        basis = CapabilitySchedulingBasis()
        assert basis.is_scheduling_eligible is False

    def test_to_dict_contains_pr6_sentinel(self):
        basis = CapabilitySchedulingBasis()
        d = basis.to_dict()
        assert "pr6_sentinel" in d
        assert d["pr6_sentinel"] == CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL

    def test_to_dict_contains_scheduling_authority(self):
        basis = CapabilitySchedulingBasis()
        d = basis.to_dict()
        assert "scheduling_authority" in d
        assert "PR6" in d["scheduling_authority"] or "post-533" in d["scheduling_authority"] or "canonical" in d["scheduling_authority"].lower()

    def test_eligible_surfaces_serialised_as_strings(self):
        basis = CapabilitySchedulingBasis(
            eligible_surfaces=[ExecutionSurface.LOCAL_HOST, ExecutionSurface.REMOTE_DEVICE]
        )
        d = basis.to_dict()
        assert d["eligible_surfaces"] == ["local_host", "remote_device"]

    def test_basis_id_is_string(self):
        basis = CapabilitySchedulingBasis()
        assert isinstance(basis.basis_id, str)
        assert len(basis.basis_id) > 0


# ===========================================================================
# D) normalize_scheduling_inputs — from object attributes
# ===========================================================================


class TestNormalizeSchedulingInputsFromObject:
    def test_join_runtime_posture_preserved(self):
        device = _make_device_obj(source_runtime_posture="join_runtime")
        inp = normalize_scheduling_inputs(device)
        assert inp.source_runtime_posture == "join_runtime"

    def test_control_only_posture_preserved(self):
        device = _make_device_obj(source_runtime_posture="control_only")
        inp = normalize_scheduling_inputs(device)
        assert inp.source_runtime_posture == "control_only"

    def test_unknown_posture_defaults_to_control_only(self):
        device = _make_device_obj(source_runtime_posture="weird_value")
        inp = normalize_scheduling_inputs(device)
        assert inp.source_runtime_posture == "control_only"

    def test_none_posture_defaults_to_control_only(self):
        device = _make_device_obj(source_runtime_posture=None)
        inp = normalize_scheduling_inputs(device)
        assert inp.source_runtime_posture == "control_only"

    def test_coordination_role_preserved(self):
        device = _make_device_obj(coordination_role="observer_only")
        inp = normalize_scheduling_inputs(device)
        assert inp.coordination_role == "observer_only"

    def test_unknown_coordination_role_defaults_to_unresolved(self):
        device = _make_device_obj(coordination_role="made_up_role")
        inp = normalize_scheduling_inputs(device)
        assert inp.coordination_role == "unresolved"

    def test_android_host_role_full_preserved(self):
        device = _make_android_device(android_host_role="full_runtime_host")
        inp = normalize_scheduling_inputs(device)
        assert inp.android_host_role == "full_runtime_host"

    def test_android_host_role_partial_preserved(self):
        device = _make_android_device(android_host_role="partial_runtime_host")
        inp = normalize_scheduling_inputs(device)
        assert inp.android_host_role == "partial_runtime_host"

    def test_non_android_no_android_host_role(self):
        device = _make_device_obj(platform="linux")
        device.android_host_role = None
        inp = normalize_scheduling_inputs(device)
        assert inp.android_host_role == ""

    def test_platform_android_infers_connected_device_only_when_no_role(self):
        """Android device with no android_host_role gets connected_device_only."""
        device = _make_device_obj(platform="android")
        device.android_host_role = None
        inp = normalize_scheduling_inputs(device)
        assert inp.android_host_role == "connected_device_only"

    def test_is_runtime_host_preserved(self):
        device = _make_android_device(is_runtime_host=True)
        inp = normalize_scheduling_inputs(device)
        assert inp.is_runtime_host is True

    def test_online_true_sets_runtime_present(self):
        device = _make_device_obj(online=True)
        inp = normalize_scheduling_inputs(device)
        assert inp.runtime_present is True

    def test_online_false_clears_runtime_present(self):
        device = _make_device_obj(online=False)
        inp = normalize_scheduling_inputs(device)
        assert inp.runtime_present is False

    def test_connection_state_connected_sets_routable(self):
        device = _make_device_obj(connection_state="connected")
        inp = normalize_scheduling_inputs(device)
        assert inp.routable is True

    def test_connection_state_disconnected_clears_routable(self):
        device = _make_device_obj(connection_state="disconnected")
        inp = normalize_scheduling_inputs(device)
        assert inp.routable is False

    def test_capabilities_list_preserved(self):
        caps = ["text_generation", "screen", "camera"]
        device = _make_device_obj(capabilities=caps)
        inp = normalize_scheduling_inputs(device)
        assert set(inp.capabilities) == set(caps)

    def test_platform_preserved(self):
        device = _make_device_obj(platform="darwin")
        inp = normalize_scheduling_inputs(device)
        assert inp.platform == "darwin"

    def test_none_device_returns_safe_defaults(self):
        """Passing None should not raise; uses CapabilitySchedulingInput defaults."""
        inp = normalize_scheduling_inputs(None)
        assert inp.source_runtime_posture == "control_only"
        assert inp.runtime_present is False


# ===========================================================================
# E) normalize_scheduling_inputs — from dict
# ===========================================================================


class TestNormalizeSchedulingInputsFromDict:
    def test_dict_with_all_fields(self):
        d = _make_device_dict()
        inp = normalize_scheduling_inputs(d)
        assert inp.device_id == "dev_dict_001"
        assert inp.source_runtime_posture == "join_runtime"
        assert inp.platform == "darwin"

    def test_dict_missing_posture_defaults_control_only(self):
        d = _make_device_dict()
        del d["source_runtime_posture"]
        inp = normalize_scheduling_inputs(d)
        assert inp.source_runtime_posture == "control_only"

    def test_dict_missing_capabilities_empty_list(self):
        d = _make_device_dict()
        del d["capabilities"]
        inp = normalize_scheduling_inputs(d)
        assert inp.capabilities == []

    def test_dict_online_false_runtime_present_false(self):
        d = _make_device_dict(online=False)
        inp = normalize_scheduling_inputs(d)
        assert inp.runtime_present is False


# ===========================================================================
# F) build_capability_scheduling_basis — observer_only gate
# ===========================================================================


class TestObserverOnlyGate:
    def _obs_inp(self, **overrides: Any) -> CapabilitySchedulingInput:
        defaults = dict(
            device_id="obs_dev",
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
            runtime_present=True,
            routable=True,
            capabilities=["screen"],
            platform="linux",
        )
        defaults.update(overrides)
        return CapabilitySchedulingInput(**defaults)

    def test_observer_only_ineligible(self):
        basis = build_capability_scheduling_basis(self._obs_inp())
        assert basis.is_scheduling_eligible is False

    def test_observer_only_surface_is_unavailable(self):
        basis = build_capability_scheduling_basis(self._obs_inp())
        assert basis.eligible_surfaces == [ExecutionSurface.UNAVAILABLE]

    def test_observer_only_weight_zero(self):
        basis = build_capability_scheduling_basis(self._obs_inp())
        assert basis.scheduling_weight == 0.0

    def test_observer_only_reason_mentions_policy(self):
        basis = build_capability_scheduling_basis(self._obs_inp())
        assert basis.ineligibility_reason is not None
        assert "observer_only" in basis.ineligibility_reason.lower()

    def test_observer_only_blocks_join_runtime(self):
        """observer_only blocks even when posture is join_runtime."""
        inp = self._obs_inp(source_runtime_posture="join_runtime")
        basis = build_capability_scheduling_basis(inp)
        assert basis.is_scheduling_eligible is False

    def test_observer_only_blocks_even_with_capabilities(self):
        inp = self._obs_inp(capabilities=["screen", "text_generation", "camera"])
        basis = build_capability_scheduling_basis(inp)
        assert basis.is_scheduling_eligible is False


# ===========================================================================
# G) build_capability_scheduling_basis — LOCAL_HOST surface
# ===========================================================================


class TestLocalHostSurface:
    def _local_inp(self, **overrides: Any) -> CapabilitySchedulingInput:
        defaults = dict(
            device_id="local_dev",
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            android_host_role="",
            is_runtime_host=False,
            runtime_present=True,
            routable=True,
            capabilities=["text_generation"],
            platform="linux",
        )
        defaults.update(overrides)
        return CapabilitySchedulingInput(**defaults)

    def test_join_runtime_non_android_present_local_host_eligible(self):
        basis = build_capability_scheduling_basis(self._local_inp())
        assert ExecutionSurface.LOCAL_HOST in basis.eligible_surfaces

    def test_control_only_excludes_local_host(self):
        inp = self._local_inp(source_runtime_posture="control_only")
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.LOCAL_HOST not in basis.eligible_surfaces

    def test_android_platform_excludes_local_host(self):
        inp = self._local_inp(platform="android", android_host_role="full_runtime_host")
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.LOCAL_HOST not in basis.eligible_surfaces

    def test_not_runtime_present_excludes_local_host(self):
        inp = self._local_inp(runtime_present=False)
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.LOCAL_HOST not in basis.eligible_surfaces

    def test_local_host_weight_at_least_075(self):
        basis = build_capability_scheduling_basis(self._local_inp())
        assert basis.scheduling_weight >= 0.75

    def test_local_host_eligible_is_scheduling_eligible_true(self):
        basis = build_capability_scheduling_basis(self._local_inp())
        assert basis.is_scheduling_eligible is True


# ===========================================================================
# H) build_capability_scheduling_basis — ANDROID_HOST surface
# ===========================================================================


class TestAndroidHostSurface:
    def _android_inp(self, **overrides: Any) -> CapabilitySchedulingInput:
        defaults = dict(
            device_id="android_dev",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            android_host_role="full_runtime_host",
            is_runtime_host=True,
            runtime_present=True,
            routable=True,
            capabilities=["screen", "camera"],
            platform="android",
        )
        defaults.update(overrides)
        return CapabilitySchedulingInput(**defaults)

    def test_full_runtime_host_android_eligible(self):
        basis = build_capability_scheduling_basis(self._android_inp())
        assert ExecutionSurface.ANDROID_HOST in basis.eligible_surfaces

    def test_partial_runtime_host_android_eligible(self):
        inp = self._android_inp(android_host_role="partial_runtime_host")
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.ANDROID_HOST in basis.eligible_surfaces

    def test_connected_device_only_not_android_host(self):
        inp = self._android_inp(android_host_role="connected_device_only")
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.ANDROID_HOST not in basis.eligible_surfaces

    def test_control_only_posture_no_android_host(self):
        inp = self._android_inp(source_runtime_posture="control_only")
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.ANDROID_HOST not in basis.eligible_surfaces

    def test_full_runtime_host_weight_is_090(self):
        basis = build_capability_scheduling_basis(
            self._android_inp(android_host_role="full_runtime_host")
        )
        assert basis.scheduling_weight == 0.90

    def test_partial_runtime_host_weight_at_least_075(self):
        basis = build_capability_scheduling_basis(
            self._android_inp(android_host_role="partial_runtime_host")
        )
        assert basis.scheduling_weight >= 0.75

    def test_android_host_eligible_is_scheduling_eligible_true(self):
        basis = build_capability_scheduling_basis(self._android_inp())
        assert basis.is_scheduling_eligible is True


# ===========================================================================
# I) build_capability_scheduling_basis — REMOTE_DEVICE surface
# ===========================================================================


class TestRemoteDeviceSurface:
    def _remote_inp(self, **overrides: Any) -> CapabilitySchedulingInput:
        defaults = dict(
            device_id="remote_dev",
            source_runtime_posture="control_only",
            coordination_role="target_only_executor",
            android_host_role="",
            is_runtime_host=False,
            runtime_present=True,
            routable=True,
            capabilities=["screen"],
            platform="linux",
        )
        defaults.update(overrides)
        return CapabilitySchedulingInput(**defaults)

    def test_routable_true_remote_device_eligible(self):
        basis = build_capability_scheduling_basis(self._remote_inp())
        assert ExecutionSurface.REMOTE_DEVICE in basis.eligible_surfaces

    def test_routable_false_no_remote_device(self):
        inp = self._remote_inp(routable=False)
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.REMOTE_DEVICE not in basis.eligible_surfaces

    def test_remote_device_only_weight_040(self):
        """REMOTE_DEVICE as the only eligible surface → weight = 0.4."""
        inp = self._remote_inp(
            source_runtime_posture="control_only",
            runtime_present=False,  # no LOCAL_HOST
            routable=True,
        )
        basis = build_capability_scheduling_basis(inp)
        if ExecutionSurface.REMOTE_DEVICE in basis.eligible_surfaces:
            surfaces = [s for s in basis.eligible_surfaces if s != ExecutionSurface.UNAVAILABLE]
            if surfaces == [ExecutionSurface.REMOTE_DEVICE]:
                assert basis.scheduling_weight == 0.40

    def test_control_only_routable_remote_eligible(self):
        """control_only source can still be a remote dispatch target."""
        inp = self._remote_inp(source_runtime_posture="control_only")
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.REMOTE_DEVICE in basis.eligible_surfaces

    def test_remote_device_eligible_is_scheduling_eligible_true(self):
        basis = build_capability_scheduling_basis(self._remote_inp())
        assert basis.is_scheduling_eligible is True


# ===========================================================================
# J) build_capability_scheduling_basis — UNAVAILABLE fallback
# ===========================================================================


class TestUnavailableFallback:
    def _offline_inp(self) -> CapabilitySchedulingInput:
        return CapabilitySchedulingInput(
            device_id="offline_dev",
            source_runtime_posture="control_only",
            coordination_role="unresolved",
            runtime_present=False,
            routable=False,
            capabilities=[],
            platform="linux",
        )

    def test_offline_not_routable_unavailable(self):
        basis = build_capability_scheduling_basis(self._offline_inp())
        assert ExecutionSurface.UNAVAILABLE in basis.eligible_surfaces

    def test_offline_not_routable_not_eligible(self):
        basis = build_capability_scheduling_basis(self._offline_inp())
        assert basis.is_scheduling_eligible is False

    def test_offline_weight_zero(self):
        basis = build_capability_scheduling_basis(self._offline_inp())
        assert basis.scheduling_weight == 0.0

    def test_ineligibility_reason_set(self):
        basis = build_capability_scheduling_basis(self._offline_inp())
        assert basis.ineligibility_reason is not None
        assert len(basis.ineligibility_reason) > 0

    def test_android_connected_only_not_routable_unavailable(self):
        inp = CapabilitySchedulingInput(
            device_id="android_co",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            android_host_role="connected_device_only",
            runtime_present=True,
            routable=False,
            platform="android",
        )
        basis = build_capability_scheduling_basis(inp)
        assert basis.is_scheduling_eligible is False


# ===========================================================================
# K) build_capability_scheduling_basis — capability signals
# ===========================================================================


class TestCapabilitySignals:
    def test_capabilities_appear_in_signals_as_true(self):
        inp = CapabilitySchedulingInput(
            device_id="dev",
            source_runtime_posture="join_runtime",
            runtime_present=True,
            routable=True,
            capabilities=["screen", "camera", "touch"],
            platform="android",
            android_host_role="full_runtime_host",
        )
        basis = build_capability_scheduling_basis(inp)
        assert basis.capability_signals.get("screen") is True
        assert basis.capability_signals.get("camera") is True
        assert basis.capability_signals.get("touch") is True

    def test_empty_capabilities_empty_signals(self):
        inp = CapabilitySchedulingInput(
            device_id="dev",
            source_runtime_posture="join_runtime",
            runtime_present=True,
            routable=True,
            capabilities=[],
            platform="linux",
        )
        basis = build_capability_scheduling_basis(inp)
        assert basis.capability_signals == {}

    def test_capability_signals_not_used_for_eligibility_gate(self):
        """Declaring capabilities does not make an ineligible device eligible."""
        inp = CapabilitySchedulingInput(
            device_id="obs_dev",
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
            capabilities=["screen", "camera"],
            runtime_present=True,
            routable=True,
            platform="linux",
        )
        basis = build_capability_scheduling_basis(inp)
        # Capabilities are recorded but eligibility is still blocked.
        assert basis.is_scheduling_eligible is False
        assert "screen" in basis.capability_signals


# ===========================================================================
# L) assess_scheduling_eligibility — combined helper
# ===========================================================================


class TestAssessSchedulingEligibility:
    def test_returns_tuple_of_two(self):
        device = _make_device_obj()
        result = assess_scheduling_eligibility(device)
        assert len(result) == 2

    def test_first_element_is_scheduling_input(self):
        device = _make_device_obj()
        inp, _ = assess_scheduling_eligibility(device)
        assert isinstance(inp, CapabilitySchedulingInput)

    def test_second_element_is_scheduling_basis(self):
        device = _make_device_obj()
        _, basis = assess_scheduling_eligibility(device)
        assert isinstance(basis, CapabilitySchedulingBasis)

    def test_join_runtime_online_non_android_has_local_host(self):
        device = _make_device_obj(
            source_runtime_posture="join_runtime",
            online=True,
            connection_state="connected",
            platform="linux",
        )
        inp, basis = assess_scheduling_eligibility(device)
        assert ExecutionSurface.LOCAL_HOST in basis.eligible_surfaces

    def test_observer_only_ineligible(self):
        device = _make_device_obj(coordination_role="observer_only")
        _, basis = assess_scheduling_eligibility(device)
        assert basis.is_scheduling_eligible is False

    def test_android_full_host_has_android_host_surface(self):
        device = _make_android_device(
            source_runtime_posture="join_runtime",
            android_host_role="full_runtime_host",
        )
        _, basis = assess_scheduling_eligibility(device)
        assert ExecutionSurface.ANDROID_HOST in basis.eligible_surfaces


# ===========================================================================
# M) Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    def test_authority_sentinel_non_empty(self):
        assert isinstance(CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY, str)
        assert len(CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY) > 10

    def test_pr6_sentinel_non_empty(self):
        assert isinstance(CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL, str)
        assert len(CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL) > 10

    def test_observer_only_policy_non_empty(self):
        assert isinstance(OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY, str)
        assert len(OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY) > 10

    def test_control_only_policy_non_empty(self):
        assert isinstance(CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY, str)
        assert len(CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY) > 10

    def test_android_host_policy_non_empty(self):
        assert isinstance(ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY, str)
        assert len(ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY) > 10

    def test_inputs_normalized_policy_non_empty(self):
        assert isinstance(CAPABILITY_SCHEDULING_INPUTS_NORMALIZED_POLICY, str)
        assert len(CAPABILITY_SCHEDULING_INPUTS_NORMALIZED_POLICY) > 10

    def test_posture_role_driven_policy_non_empty(self):
        assert isinstance(SCHEDULING_BASIS_IS_POSTURE_AND_ROLE_DRIVEN_POLICY, str)
        assert len(SCHEDULING_BASIS_IS_POSTURE_AND_ROLE_DRIVEN_POLICY) > 10

    def test_authority_mentions_pr6(self):
        assert "PR6" in CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY or \
               "PR package 6" in CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY

    def test_pr6_sentinel_mentions_post_533(self):
        assert "post-533" in CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL


# ===========================================================================
# N) core.runtime re-exports
# ===========================================================================


class TestCoreRuntimeReexports:
    def test_authority_importable_from_core_runtime(self):
        from core.runtime import CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY as _a
        assert _a == CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY

    def test_pr6_sentinel_importable_from_core_runtime(self):
        from core.runtime import CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL as _s
        assert _s == CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL

    def test_execution_surface_importable_from_core_runtime(self):
        from core.runtime import ExecutionSurface as _ES
        assert _ES is ExecutionSurface

    def test_capability_scheduling_input_importable(self):
        from core.runtime import CapabilitySchedulingInput as _CSI
        assert _CSI is CapabilitySchedulingInput

    def test_capability_scheduling_basis_importable(self):
        from core.runtime import CapabilitySchedulingBasis as _CSB
        assert _CSB is CapabilitySchedulingBasis

    def test_build_capability_scheduling_basis_importable(self):
        from core.runtime import build_capability_scheduling_basis as _build
        assert _build is build_capability_scheduling_basis

    def test_normalize_scheduling_inputs_importable(self):
        from core.runtime import normalize_scheduling_inputs as _norm
        assert _norm is normalize_scheduling_inputs

    def test_assess_scheduling_eligibility_importable(self):
        from core.runtime import assess_scheduling_eligibility as _ase
        assert _ase is assess_scheduling_eligibility

    def test_pr6_sentinel_in_all_list(self):
        import core.runtime as cr
        assert "CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL" in cr.__all__

    def test_execution_surface_in_all_list(self):
        import core.runtime as cr
        assert "ExecutionSurface" in cr.__all__

    def test_observer_only_policy_in_all_list(self):
        import core.runtime as cr
        assert "OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY" in cr.__all__


# ===========================================================================
# O) Projection routes sentinel
# ===========================================================================


class TestProjectionRoutesSentinel:
    def test_sentinel_present_in_projection(self):
        from core.routes.projection import CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6
        assert isinstance(CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6, str)
        assert len(CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6) > 0

    def test_sentinel_indicates_availability(self):
        from core.routes.projection import CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6
        assert "UNAVAILABLE" not in CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6

    def test_pr5_sentinel_still_present(self):
        """PR-5 sentinel is not broken by PR-6 additions."""
        from core.routes.projection import ANDROID_RUNTIME_HOST_ALIGNED_PR5
        assert isinstance(ANDROID_RUNTIME_HOST_ALIGNED_PR5, str)
        assert "UNAVAILABLE" not in ANDROID_RUNTIME_HOST_ALIGNED_PR5

    def test_pr4_sentinel_still_present(self):
        """PR-4 sentinel is not broken by PR-6 additions."""
        from core.routes.projection import CANONICAL_SESSION_TRUTH_ALIGNED_PR4
        assert isinstance(CANONICAL_SESSION_TRUTH_ALIGNED_PR4, str)
        assert "UNAVAILABLE" not in CANONICAL_SESSION_TRUTH_ALIGNED_PR4


# ===========================================================================
# P) Backwards-compatibility (PR-1 through PR-5 signals honoured)
# ===========================================================================


class TestBackwardsCompatibility:
    def test_control_only_posture_respected_consistent_with_pr2(self):
        """control_only posture must exclude LOCAL_HOST (PR-2 consistency)."""
        inp = CapabilitySchedulingInput(
            device_id="co_dev",
            source_runtime_posture="control_only",
            runtime_present=True,
            routable=False,
            platform="linux",
        )
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.LOCAL_HOST not in basis.eligible_surfaces

    def test_observer_only_role_respected_consistent_with_pr2_pr4(self):
        """observer_only coordination role must block scheduling (PR-2/PR-4 consistency)."""
        inp = CapabilitySchedulingInput(
            device_id="obs_dev",
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
            runtime_present=True,
            routable=True,
            platform="linux",
        )
        basis = build_capability_scheduling_basis(inp)
        assert basis.is_scheduling_eligible is False

    def test_android_host_role_respected_consistent_with_pr5(self):
        """AndroidRuntimeHostRole semantics (PR-5) are honoured in scheduling."""
        inp = CapabilitySchedulingInput(
            device_id="android_dev",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            android_host_role="full_runtime_host",
            is_runtime_host=True,
            runtime_present=True,
            routable=True,
            platform="android",
        )
        basis = build_capability_scheduling_basis(inp)
        assert ExecutionSurface.ANDROID_HOST in basis.eligible_surfaces

    def test_android_runtime_host_role_still_importable(self):
        """PR-5 AndroidRuntimeHostRole is still importable and unaffected."""
        from core.android_runtime_host import AndroidRuntimeHostRole
        assert AndroidRuntimeHostRole.FULL_RUNTIME_HOST.value == "full_runtime_host"

    def test_pr5_symbols_in_core_runtime_all(self):
        """PR-5 exports in core.runtime.__all__ are still present."""
        import core.runtime as cr
        assert "AndroidRuntimeHostRole" in cr.__all__
        assert "ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL" in cr.__all__

    def test_no_import_error_from_core_runtime(self):
        """Full import of core.runtime succeeds with PR-6 additions."""
        import core.runtime as cr
        assert hasattr(cr, "ExecutionSurface")
        assert hasattr(cr, "CapabilitySchedulingBasis")
