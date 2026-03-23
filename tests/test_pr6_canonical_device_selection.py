"""
tests/test_pr6_canonical_device_selection.py
=============================================

Tests for PR-6: Cross-device and orchestration consumers resolve devices
from canonical projected device views.

Coverage
--------

A) DeviceParticipationStatus dataclass
   - frozen / immutable
   - default values (safe-off)
   - to_dict() serialisation

B) CanonicalDeviceSelectionEntry
   - construction and field access
   - device_id property
   - to_dict() serialisation

C) assess_device_participation — canonical-only derivation
   - offline device → not runtime_present, not routable, not eligible
   - online device without connection → runtime_present but not routable
   - online device with connected state → all flags True
   - router_liveness can affirm routability
   - router_liveness can deny routability (override canonical connected)
   - router_liveness does not change identity fields
   - missing device (empty device_id) → registered=False

D) assess_device_participation — runtime enrichment semantics
   - router_liveness enriches routable, not identity
   - orchestration_override forces orchestration_eligible
   - autonomy.runtime_enabled contributes to orchestration_eligible

E) select_cross_device_candidates
   - empty list → empty result
   - only eligible devices returned
   - router_liveness enrichment applied
   - non-eligible devices filtered out

F) select_orchestration_candidates
   - only orchestration_eligible devices returned
   - capability filter: missing capability → excluded
   - capability filter: all caps present → included
   - router_liveness enrichment passed through

G) device_score_input_from_canonical
   - produces DeviceScoreInput with correct device_id
   - capabilities from canonical device transferred
   - latency / load / sandbox_level accepted

H) CrossDeviceCoordinator — canonical device resolution helpers
   - _get_canonical_devices projects from router
   - _get_canonical_online_devices returns only eligible devices
   - _get_canonical_devices_by_type filters by device type

I) SwarmCoordinator — canonical device candidate bridge
   - device_candidates_from_canonical returns DeviceScoreInput list
   - only orchestration_eligible devices included
   - capability filter applied
   - router_liveness enrichment used

J) cross_device_policy package — DeviceParticipationStatus re-export
   - DeviceParticipationStatus importable from core.cross_device_policy

K) Eligibility semantics stability
   - all five semantics defined and stable
   - registered always True for valid devices
   - cross_device_eligible is conjunction of registered+runtime_present+routable
   - orchestration_eligible requires cross_device_eligible

L) Router-local state cannot override canonical identity truth
   - router_liveness False does not delete canonical device_id
   - router_liveness False sets routable=False, not registered=False
   - identity fields (device_id, device_name) come only from canonical device

M) Existing coordination behavior (functional preservation)
   - CrossDeviceCoordinator can resolve devices with empty router
   - SwarmCoordinator.device_candidates_from_canonical empty input → empty result
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Helpers: minimal RegisteredRuntimeDevice-like objects for testing
# ---------------------------------------------------------------------------


def _make_device(
    device_id: str = "dev_001",
    device_name: str = "Test Device",
    online: bool = False,
    status: str = "offline",
    conn_state: str = "disconnected",
    capabilities: Optional[List[str]] = None,
    runtime_enabled: bool = False,
) -> Any:
    """Build a minimal object conforming to RegisteredRuntimeDevice field surface."""
    conn = MagicMock()
    conn.state = conn_state

    autonomy = MagicMock()
    autonomy.runtime_enabled = runtime_enabled

    cap_profile = MagicMock()
    cap_profile.capabilities = list(capabilities or [])

    device = MagicMock()
    device.device_id = device_id
    device.device_name = device_name
    device.online = online
    device.status = status
    device.connection = conn
    device.capabilities = cap_profile
    device.autonomy = autonomy

    # to_dict
    device.to_dict.return_value = {
        "device_id": device_id,
        "device_name": device_name,
        "online": online,
        "status": status,
    }
    return device


# ---------------------------------------------------------------------------
# A) DeviceParticipationStatus
# ---------------------------------------------------------------------------


class TestDeviceParticipationStatus:
    def test_import(self):
        from core.device_selection import DeviceParticipationStatus
        assert DeviceParticipationStatus is not None

    def test_defaults_all_false(self):
        from core.device_selection import DeviceParticipationStatus
        s = DeviceParticipationStatus()
        assert s.registered is True   # default is True (safe: caller is asserting existence)
        assert s.runtime_present is False
        assert s.routable is False
        assert s.cross_device_eligible is False
        assert s.orchestration_eligible is False

    def test_frozen(self):
        from core.device_selection import DeviceParticipationStatus
        s = DeviceParticipationStatus()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            s.registered = False  # type: ignore[misc]

    def test_to_dict_keys(self):
        from core.device_selection import DeviceParticipationStatus
        s = DeviceParticipationStatus(
            registered=True, runtime_present=True, routable=True,
            cross_device_eligible=True, orchestration_eligible=True,
            participation_reason="all-eligible",
        )
        d = s.to_dict()
        assert d["registered"] is True
        assert d["runtime_present"] is True
        assert d["routable"] is True
        assert d["cross_device_eligible"] is True
        assert d["orchestration_eligible"] is True
        assert d["participation_reason"] == "all-eligible"

    def test_to_dict_serialisable(self):
        import json
        from core.device_selection import DeviceParticipationStatus
        s = DeviceParticipationStatus(runtime_present=True, routable=True,
                                      cross_device_eligible=True)
        json.dumps(s.to_dict())  # should not raise


# ---------------------------------------------------------------------------
# B) CanonicalDeviceSelectionEntry
# ---------------------------------------------------------------------------


class TestCanonicalDeviceSelectionEntry:
    def test_import(self):
        from core.device_selection import CanonicalDeviceSelectionEntry
        assert CanonicalDeviceSelectionEntry is not None

    def test_construction(self):
        from core.device_selection import (
            CanonicalDeviceSelectionEntry,
            DeviceParticipationStatus,
        )
        dev = _make_device("d1")
        status = DeviceParticipationStatus(registered=True, runtime_present=True,
                                           routable=True, cross_device_eligible=True,
                                           orchestration_eligible=True)
        entry = CanonicalDeviceSelectionEntry(device=dev, participation=status)
        assert entry.device_id == "d1"
        assert entry.participation.cross_device_eligible is True

    def test_device_id_property(self):
        from core.device_selection import (
            CanonicalDeviceSelectionEntry,
            DeviceParticipationStatus,
        )
        dev = _make_device("dev_xyz")
        entry = CanonicalDeviceSelectionEntry(
            device=dev, participation=DeviceParticipationStatus()
        )
        assert entry.device_id == "dev_xyz"

    def test_frozen(self):
        from core.device_selection import (
            CanonicalDeviceSelectionEntry,
            DeviceParticipationStatus,
        )
        dev = _make_device()
        entry = CanonicalDeviceSelectionEntry(device=dev, participation=DeviceParticipationStatus())
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            entry.device = None  # type: ignore[misc]

    def test_to_dict_has_device_and_participation(self):
        from core.device_selection import (
            CanonicalDeviceSelectionEntry,
            DeviceParticipationStatus,
        )
        dev = _make_device("d2")
        entry = CanonicalDeviceSelectionEntry(
            device=dev, participation=DeviceParticipationStatus(registered=True)
        )
        d = entry.to_dict()
        assert "device" in d
        assert "participation" in d
        assert d["participation"]["registered"] is True


# ---------------------------------------------------------------------------
# C) assess_device_participation — canonical-only derivation
# ---------------------------------------------------------------------------


class TestAssessDeviceParticipation:
    def test_offline_device_not_eligible(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(online=False, status="offline", conn_state="disconnected")
        status = assess_device_participation(dev)
        assert status.registered is True
        assert status.runtime_present is False
        assert status.routable is False
        assert status.cross_device_eligible is False
        assert status.orchestration_eligible is False

    def test_online_device_without_connection_not_routable(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(online=True, status="online", conn_state="disconnected")
        status = assess_device_participation(dev)
        assert status.runtime_present is True
        assert status.routable is False
        assert status.cross_device_eligible is False

    def test_online_connected_device_fully_eligible(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(online=True, status="online", conn_state="connected",
                           runtime_enabled=True)
        status = assess_device_participation(dev)
        assert status.registered is True
        assert status.runtime_present is True
        assert status.routable is True
        assert status.cross_device_eligible is True
        assert status.orchestration_eligible is True

    def test_router_liveness_affirms_routability(self):
        from core.device_selection import assess_device_participation
        # canonical says disconnected, router says connected
        dev = _make_device(device_id="d1", online=True, status="online",
                           conn_state="disconnected")
        status = assess_device_participation(dev, router_liveness={"d1": True})
        assert status.routable is True
        assert status.cross_device_eligible is True

    def test_router_liveness_denies_routability(self):
        from core.device_selection import assess_device_participation
        # canonical says connected, router says not reachable
        dev = _make_device(device_id="d1", online=True, status="online",
                           conn_state="connected", runtime_enabled=True)
        status = assess_device_participation(dev, router_liveness={"d1": False})
        assert status.routable is False
        assert status.cross_device_eligible is False

    def test_router_liveness_does_not_change_registered(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(device_id="d1", online=True, status="online",
                           conn_state="connected")
        status = assess_device_participation(dev, router_liveness={"d1": False})
        # router_liveness=False should not affect 'registered'
        assert status.registered is True

    def test_missing_device_id_not_registered(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(device_id="")
        status = assess_device_participation(dev)
        assert status.registered is False
        assert status.cross_device_eligible is False

    def test_busy_status_counts_as_runtime_present(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(online=False, status="busy", conn_state="connected")
        status = assess_device_participation(dev)
        assert status.runtime_present is True

    def test_reconnecting_connection_is_routable(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(online=True, status="online", conn_state="reconnecting")
        status = assess_device_participation(dev)
        assert status.routable is True

    def test_participation_reason_nonempty(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(online=False, status="offline", conn_state="disconnected")
        status = assess_device_participation(dev)
        assert status.participation_reason
        assert len(status.participation_reason) > 0


# ---------------------------------------------------------------------------
# D) assess_device_participation — runtime enrichment semantics
# ---------------------------------------------------------------------------


class TestAssessParticipationEnrichment:
    def test_orchestration_override_true(self):
        from core.device_selection import assess_device_participation
        # device is cross_device_eligible, override=True
        dev = _make_device(online=True, status="online", conn_state="connected")
        status = assess_device_participation(dev, orchestration_override=True)
        assert status.orchestration_eligible is True

    def test_orchestration_override_false(self):
        from core.device_selection import assess_device_participation
        # even if device has runtime_enabled, override=False disables orch
        dev = _make_device(online=True, status="online", conn_state="connected",
                           runtime_enabled=True)
        status = assess_device_participation(dev, orchestration_override=False)
        assert status.orchestration_eligible is False

    def test_autonomy_runtime_enabled_contributes(self):
        from core.device_selection import assess_device_participation
        dev = _make_device(online=True, status="online", conn_state="connected",
                           runtime_enabled=True)
        status = assess_device_participation(dev)
        assert status.orchestration_eligible is True

    def test_no_autonomy_still_orch_eligible_when_runtime_present(self):
        from core.device_selection import assess_device_participation
        # runtime_enabled=False but device is online and routable
        dev = _make_device(online=True, status="online", conn_state="connected",
                           runtime_enabled=False)
        status = assess_device_participation(dev)
        # orchestration_eligible = cross_device_eligible AND (runtime_enabled OR runtime_present)
        # runtime_present=True, so True
        assert status.orchestration_eligible is True


# ---------------------------------------------------------------------------
# E) select_cross_device_candidates
# ---------------------------------------------------------------------------


class TestSelectCrossDeviceCandidates:
    def test_empty_input(self):
        from core.device_selection import select_cross_device_candidates
        result = select_cross_device_candidates([])
        assert result == []

    def test_none_input(self):
        from core.device_selection import select_cross_device_candidates
        result = select_cross_device_candidates(None)  # type: ignore
        assert result == []

    def test_only_eligible_returned(self):
        from core.device_selection import select_cross_device_candidates
        eligible = _make_device("e1", online=True, status="online", conn_state="connected")
        ineligible = _make_device("e2", online=False, status="offline", conn_state="disconnected")
        result = select_cross_device_candidates([eligible, ineligible])
        ids = [entry.device_id for entry in result]
        assert "e1" in ids
        assert "e2" not in ids

    def test_router_liveness_enrichment_applied(self):
        from core.device_selection import select_cross_device_candidates
        # canonical says disconnected, but router says live
        dev = _make_device("d1", online=True, status="online", conn_state="disconnected")
        result = select_cross_device_candidates([dev], router_liveness={"d1": True})
        assert len(result) == 1
        assert result[0].device_id == "d1"

    def test_non_eligible_filtered_out(self):
        from core.device_selection import select_cross_device_candidates
        dev = _make_device("d2", online=False, status="offline", conn_state="disconnected")
        result = select_cross_device_candidates([dev])
        assert result == []

    def test_result_type_is_entry(self):
        from core.device_selection import (
            select_cross_device_candidates,
            CanonicalDeviceSelectionEntry,
        )
        dev = _make_device("d1", online=True, status="online", conn_state="connected")
        result = select_cross_device_candidates([dev])
        assert all(isinstance(e, CanonicalDeviceSelectionEntry) for e in result)


# ---------------------------------------------------------------------------
# F) select_orchestration_candidates
# ---------------------------------------------------------------------------


class TestSelectOrchestrationCandidates:
    def test_only_orchestration_eligible_returned(self):
        from core.device_selection import select_orchestration_candidates
        orch = _make_device("o1", online=True, status="online", conn_state="connected",
                            runtime_enabled=True)
        non_orch = _make_device("o2", online=False, status="offline", conn_state="disconnected")
        result = select_orchestration_candidates([orch, non_orch])
        ids = [e.device_id for e in result]
        assert "o1" in ids
        assert "o2" not in ids

    def test_capability_filter_excludes_missing(self):
        from core.device_selection import select_orchestration_candidates
        dev = _make_device("c1", online=True, status="online", conn_state="connected",
                           capabilities=["screen"])
        result = select_orchestration_candidates(
            [dev], required_capabilities=["screen", "camera"]
        )
        assert result == []

    def test_capability_filter_includes_matching(self):
        from core.device_selection import select_orchestration_candidates
        dev = _make_device("c2", online=True, status="online", conn_state="connected",
                           capabilities=["screen", "camera", "microphone"])
        result = select_orchestration_candidates(
            [dev], required_capabilities=["screen", "camera"]
        )
        assert len(result) == 1
        assert result[0].device_id == "c2"

    def test_no_capability_filter_passes_all_eligible(self):
        from core.device_selection import select_orchestration_candidates
        dev = _make_device("c3", online=True, status="online", conn_state="connected")
        result = select_orchestration_candidates([dev])
        assert len(result) == 1

    def test_router_liveness_enrichment_passed_through(self):
        from core.device_selection import select_orchestration_candidates
        dev = _make_device("d1", online=True, status="online", conn_state="disconnected")
        result = select_orchestration_candidates([dev], router_liveness={"d1": True})
        assert len(result) == 1


# ---------------------------------------------------------------------------
# G) device_score_input_from_canonical
# ---------------------------------------------------------------------------


class TestDeviceScoreInputFromCanonical:
    def _make_entry(self, device_id="dev_01", caps=None):
        from core.device_selection import (
            CanonicalDeviceSelectionEntry,
            DeviceParticipationStatus,
        )
        dev = _make_device(device_id, capabilities=caps or ["screen"])
        status = DeviceParticipationStatus(
            registered=True, runtime_present=True, routable=True,
            cross_device_eligible=True, orchestration_eligible=True,
        )
        return CanonicalDeviceSelectionEntry(device=dev, participation=status)

    def test_produces_score_input(self):
        from core.device_selection import device_score_input_from_canonical
        entry = self._make_entry()
        result = device_score_input_from_canonical(entry)
        assert result is not None
        assert result.device_id == "dev_01"

    def test_capabilities_transferred(self):
        from core.device_selection import device_score_input_from_canonical
        entry = self._make_entry(caps=["screen", "camera"])
        result = device_score_input_from_canonical(entry)
        assert "screen" in result.capabilities
        assert "camera" in result.capabilities

    def test_latency_and_load(self):
        from core.device_selection import device_score_input_from_canonical
        entry = self._make_entry()
        result = device_score_input_from_canonical(
            entry, ping_latency_ms=42.5, load_pct=30.0
        )
        assert result.ping_latency_ms == 42.5
        assert result.load_pct == 30.0

    def test_sandbox_level_override(self):
        from core.device_selection import device_score_input_from_canonical
        from core.control_plane.smart_scheduler import SandboxLevel
        entry = self._make_entry()
        result = device_score_input_from_canonical(entry, sandbox_level=SandboxLevel.STRICT)
        assert result.sandbox_level == SandboxLevel.STRICT


# ---------------------------------------------------------------------------
# H) CrossDeviceCoordinator — canonical device resolution helpers
# ---------------------------------------------------------------------------


class TestCrossDeviceCoordinatorCanonicalHelpers:
    def _make_coordinator(self):
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        return CrossDeviceCoordinator()

    def test_get_canonical_devices_empty_router(self):
        """With an empty router, _get_canonical_devices returns empty list."""
        coord = self._make_coordinator()
        with patch("galaxy_gateway.cross_device_coordinator.device_router") as mock_router:
            mock_router.devices = {}
            result = coord._get_canonical_devices()
        assert result == []

    def test_get_canonical_devices_projects_from_router(self):
        """_get_canonical_devices wraps each router device through canonical projection."""
        coord = self._make_coordinator()

        fake_router_device = MagicMock()
        fake_router_device.device_id = "r1"
        fake_router_device.device_type = "android"
        fake_router_device.device_name = "Phone"
        fake_router_device.capabilities = []
        fake_router_device.websocket = object()  # non-None → connected
        fake_router_device.metadata = {}

        with patch("galaxy_gateway.cross_device_coordinator.device_router") as mock_router:
            mock_router.devices = {"r1": fake_router_device}
            result = coord._get_canonical_devices()

        assert len(result) == 1
        # The result should be a RegisteredRuntimeDevice (has device_id attribute)
        assert hasattr(result[0], "device_id")
        assert result[0].device_id == "r1"

    def test_get_canonical_online_devices_filters_eligible(self):
        """_get_canonical_online_devices returns only cross-device-eligible devices."""
        coord = self._make_coordinator()

        online_dev = MagicMock()
        online_dev.device_id = "online1"
        online_dev.device_type = "android"
        online_dev.device_name = "OnlinePhone"
        online_dev.capabilities = []
        online_dev.websocket = object()  # connected
        online_dev.metadata = {}

        offline_dev = MagicMock()
        offline_dev.device_id = "offline1"
        offline_dev.device_type = "windows"
        offline_dev.device_name = "OfflinePC"
        offline_dev.capabilities = []
        offline_dev.websocket = None  # not connected
        offline_dev.metadata = {}

        with patch("galaxy_gateway.cross_device_coordinator.device_router") as mock_router:
            mock_router.devices = {
                "online1": online_dev,
                "offline1": offline_dev,
            }
            result = coord._get_canonical_online_devices()

        # Only the online (connected) device should be cross-device eligible
        ids = [d.device_id for d in result]
        assert "online1" in ids
        assert "offline1" not in ids

    def test_get_canonical_devices_by_type_filters(self):
        """_get_canonical_devices_by_type returns only matching device type."""
        coord = self._make_coordinator()

        android_dev = MagicMock()
        android_dev.device_id = "phone1"
        android_dev.device_type = "android"
        android_dev.device_name = "AndroidPhone"
        android_dev.capabilities = []
        android_dev.websocket = object()  # connected
        android_dev.metadata = {}

        windows_dev = MagicMock()
        windows_dev.device_id = "pc1"
        windows_dev.device_type = "windows"
        windows_dev.device_name = "WindowsPC"
        windows_dev.capabilities = []
        windows_dev.websocket = object()  # connected
        windows_dev.metadata = {}

        from core.device_types import DeviceType

        with patch("galaxy_gateway.cross_device_coordinator.device_router") as mock_router:
            mock_router.devices = {
                "phone1": android_dev,
                "pc1": windows_dev,
            }
            result = coord._get_canonical_devices_by_type(
                DeviceType.ANDROID, cross_device_eligible_only=False
            )

        ids = [d.device_id for d in result]
        assert "phone1" in ids
        assert "pc1" not in ids


# ---------------------------------------------------------------------------
# I) SwarmCoordinator — canonical device candidate bridge
# ---------------------------------------------------------------------------


class TestSwarmCoordinatorCanonicalBridge:
    def _make_coordinator(self):
        from core.swarm_coordinator import SwarmCoordinator
        return SwarmCoordinator()

    def test_device_candidates_from_canonical_empty(self):
        coord = self._make_coordinator()
        result = coord.device_candidates_from_canonical([])
        assert result == []

    def test_device_candidates_from_canonical_eligible(self):
        coord = self._make_coordinator()
        dev = _make_device(
            device_id="s1", online=True, status="online", conn_state="connected",
            capabilities=["screen"], runtime_enabled=True,
        )
        result = coord.device_candidates_from_canonical([dev])
        assert len(result) == 1
        assert result[0].device_id == "s1"

    def test_device_candidates_from_canonical_ineligible_excluded(self):
        coord = self._make_coordinator()
        dev = _make_device(
            device_id="s2", online=False, status="offline", conn_state="disconnected",
        )
        result = coord.device_candidates_from_canonical([dev])
        assert result == []

    def test_device_candidates_capability_filter(self):
        coord = self._make_coordinator()
        dev_has = _make_device(
            device_id="s3", online=True, status="online", conn_state="connected",
            capabilities=["screen", "camera"],
        )
        dev_missing = _make_device(
            device_id="s4", online=True, status="online", conn_state="connected",
            capabilities=["screen"],
        )
        result = coord.device_candidates_from_canonical(
            [dev_has, dev_missing], required_capabilities=["camera"]
        )
        ids = [r.device_id for r in result]
        assert "s3" in ids
        assert "s4" not in ids

    def test_device_candidates_latency_map(self):
        coord = self._make_coordinator()
        dev = _make_device(
            device_id="s5", online=True, status="online", conn_state="connected",
        )
        result = coord.device_candidates_from_canonical(
            [dev], latency_map={"s5": 99.0}
        )
        assert len(result) == 1
        assert result[0].ping_latency_ms == 99.0

    def test_device_candidates_router_liveness_enrichment(self):
        coord = self._make_coordinator()
        # canonical says disconnected, but router liveness says live
        dev = _make_device(
            device_id="s6", online=True, status="online", conn_state="disconnected",
        )
        result = coord.device_candidates_from_canonical(
            [dev], router_liveness={"s6": True}
        )
        assert len(result) == 1

    def test_device_candidates_from_canonical_none_input_safe(self):
        """None canonical_devices input does not raise."""
        coord = self._make_coordinator()
        result = coord.device_candidates_from_canonical(None)  # type: ignore
        assert result == []


# ---------------------------------------------------------------------------
# J) cross_device_policy package — DeviceParticipationStatus re-export
# ---------------------------------------------------------------------------


class TestCrossDevicePolicyReExport:
    def test_participation_status_importable_from_policy(self):
        from core.cross_device_policy import DeviceParticipationStatus
        assert DeviceParticipationStatus is not None

    def test_participation_status_is_same_class(self):
        from core.cross_device_policy import DeviceParticipationStatus as FromPolicy
        from core.device_selection import DeviceParticipationStatus as FromSelector
        assert FromPolicy is FromSelector

    def test_other_policy_exports_still_present(self):
        from core.cross_device_policy import (
            DeviceRole,
            RoutingPosture,
            RoutingPolicy,
            resolve_routing,
            DeviceParticipationStatus,
        )
        assert DeviceRole is not None
        assert RoutingPosture is not None
        assert RoutingPolicy is not None
        assert resolve_routing is not None
        assert DeviceParticipationStatus is not None


# ---------------------------------------------------------------------------
# K) Eligibility semantics stability
# ---------------------------------------------------------------------------


class TestEligibilitySemantics:
    def test_all_five_semantics_present(self):
        from core.device_selection import DeviceParticipationStatus
        s = DeviceParticipationStatus()
        assert hasattr(s, "registered")
        assert hasattr(s, "runtime_present")
        assert hasattr(s, "routable")
        assert hasattr(s, "cross_device_eligible")
        assert hasattr(s, "orchestration_eligible")

    def test_registered_true_for_valid_devices(self):
        from core.device_selection import assess_device_participation
        dev = _make_device("valid_id")
        status = assess_device_participation(dev)
        assert status.registered is True

    def test_cross_device_eligible_requires_all_three(self):
        from core.device_selection import assess_device_participation
        # registered + runtime_present + NOT routable → not eligible
        dev = _make_device("d1", online=True, status="online", conn_state="disconnected")
        status = assess_device_participation(dev)
        assert status.registered is True
        assert status.runtime_present is True
        assert status.routable is False
        assert status.cross_device_eligible is False

    def test_orchestration_requires_cross_device_eligible(self):
        from core.device_selection import assess_device_participation
        # not routable → cross_device_eligible=False → orchestration_eligible=False
        dev = _make_device("d2", online=True, status="online", conn_state="disconnected",
                           runtime_enabled=True)
        status = assess_device_participation(dev)
        assert status.cross_device_eligible is False
        assert status.orchestration_eligible is False


# ---------------------------------------------------------------------------
# L) Router-local state cannot override canonical identity truth
# ---------------------------------------------------------------------------


class TestRouterCannotOverrideIdentity:
    def test_router_liveness_false_does_not_remove_device_id(self):
        from core.device_selection import assess_device_participation
        dev = _make_device("canon_id", online=True, status="online", conn_state="connected")
        status = assess_device_participation(dev, router_liveness={"canon_id": False})
        # router said not routable, but device_id identity is not erased
        # (registered stays True — existence is canonical, not router-derived)
        assert status.registered is True

    def test_router_liveness_false_sets_routable_not_registered(self):
        from core.device_selection import assess_device_participation
        dev = _make_device("d1", online=True, status="online", conn_state="connected")
        status = assess_device_participation(dev, router_liveness={"d1": False})
        assert status.routable is False
        assert status.registered is True  # identity unaffected

    def test_canonical_device_id_not_replaced_by_router(self):
        """Canonical device_id is the only identity source."""
        from core.device_selection import assess_device_participation
        dev = _make_device("canonical_device_id")
        status = assess_device_participation(dev, router_liveness={"different_id": True})
        # The router liveness for a different device_id has no effect on dev
        # (routable stays False because "canonical_device_id" is not in the liveness map)
        assert status.registered is True


# ---------------------------------------------------------------------------
# M) Functional preservation
# ---------------------------------------------------------------------------


class TestFunctionalPreservation:
    def test_coordinator_get_canonical_devices_empty_router(self):
        """CrossDeviceCoordinator._get_canonical_devices does not raise with empty router."""
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        coord = CrossDeviceCoordinator()
        with patch("galaxy_gateway.cross_device_coordinator.device_router") as mock_router:
            mock_router.devices = {}
            result = coord._get_canonical_devices()
        assert result == []

    def test_swarm_empty_candidates_result(self):
        from core.swarm_coordinator import SwarmCoordinator
        sc = SwarmCoordinator()
        result = sc.device_candidates_from_canonical([])
        assert isinstance(result, list)
        assert len(result) == 0

    def test_select_cross_device_never_raises(self):
        """select_cross_device_candidates never raises even on bad input."""
        from core.device_selection import select_cross_device_candidates
        bad = MagicMock()
        bad.device_id = None
        bad.online = None
        bad.status = None
        bad.connection = None
        bad.autonomy = None
        bad.capabilities = None
        # Should not raise
        result = select_cross_device_candidates([bad])
        assert isinstance(result, list)

    def test_assess_participation_never_raises(self):
        """assess_device_participation never raises even on malformed input."""
        from core.device_selection import assess_device_participation
        result = assess_device_participation(None)  # type: ignore
        assert result is not None
        assert result.registered is False
