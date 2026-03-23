"""
Node 71 - Canonical Device Intake and Authority Boundary Tests (PR-7)

Tests covering:
1. Node_71 can ingest/use canonical projected device views.
2. Node_71 local state does not define canonical device truth.
3. Grouping/task coordination still works after normalisation.
4. Representative local state updates remain coordination-local,
   not canonical registration mutations.
"""
import sys
import os
import asyncio
import time

import pytest

# Ensure the Node_71 directory is on the path so local modules resolve.
_NODE71_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _NODE71_DIR not in sys.path:
    sys.path.insert(0, _NODE71_DIR)

# Import the canonical adapter directly to avoid circular-import through
# core/__init__.py → models.device → core.device_types → core/__init__.py.
from core.canonical_device_view_adapter import (
    CoordinationDeviceView,
    CoordinationDeviceStatus,
    adapt_registered_runtime_device,
    adapt_registered_runtime_device_dict,
    refresh_coordination_view,
)


# ---------------------------------------------------------------------------
# Minimal stand-in for RegisteredRuntimeDevice (avoids full galaxy imports)
# ---------------------------------------------------------------------------

class _FakeCapabilityProfile:
    """Minimal stand-in for RuntimeCapabilityProfile."""
    def __init__(self, names):
        self.names = list(names)


class _FakeRRD:
    """Minimal stand-in for RegisteredRuntimeDevice for unit-testing the adapter."""
    def __init__(
        self,
        device_id: str,
        device_name: str = "",
        device_type: str = "unknown",
        status: str = "offline",
        capabilities=None,
        metadata: dict = None,
    ):
        self.device_id = device_id
        self.device_name = device_name
        self.device_type = device_type
        self.status = status
        self.capabilities = capabilities or _FakeCapabilityProfile([])
        self.metadata = metadata or {}

    def to_dict(self):
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "status": self.status,
            "capabilities": {"names": list(self.capabilities.names)},
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def online_rrd():
    """Canonical projected device view — online device."""
    return _FakeRRD(
        device_id="canonical-phone-001",
        device_name="Test Phone",
        device_type="android_phone",
        status="online",
        capabilities=_FakeCapabilityProfile(["screen", "camera"]),
        metadata={"owner": "test_user"},
    )


@pytest.fixture
def offline_rrd():
    """Canonical projected device view — offline device."""
    return _FakeRRD(
        device_id="canonical-tablet-002",
        device_name="Test Tablet",
        device_type="android_tablet",
        status="offline",
    )


@pytest.fixture
def busy_rrd():
    """Canonical projected device view — busy device."""
    return _FakeRRD(
        device_id="canonical-pc-003",
        device_name="Test PC",
        device_type="windows_desktop",
        status="busy",
        capabilities=_FakeCapabilityProfile(["keyboard", "screen"]),
    )


# ---------------------------------------------------------------------------
# 1. Canonical device view intake
# ---------------------------------------------------------------------------

class TestCanonicalDeviceViewIngestion:
    """Node_71 can ingest and use canonical projected device views."""

    def test_adapt_online_rrd_produces_available_view(self, online_rrd):
        """Adapting an online RRD should yield an AVAILABLE coordination view."""
        view = adapt_registered_runtime_device(online_rrd)
        assert isinstance(view, CoordinationDeviceView)
        assert view.device_id == "canonical-phone-001"
        assert view.device_name == "Test Phone"
        assert view.device_type == "android_phone"
        assert view.coordination_status == CoordinationDeviceStatus.AVAILABLE
        assert view.canonical_status == "online"

    def test_adapt_offline_rrd_produces_unavailable_view(self, offline_rrd):
        """Adapting an offline RRD should yield an UNAVAILABLE coordination view."""
        view = adapt_registered_runtime_device(offline_rrd)
        assert view.coordination_status == CoordinationDeviceStatus.UNAVAILABLE
        assert view.canonical_status == "offline"

    def test_adapt_busy_rrd_produces_busy_view(self, busy_rrd):
        """Adapting a busy RRD should yield a BUSY coordination view."""
        view = adapt_registered_runtime_device(busy_rrd)
        assert view.coordination_status == CoordinationDeviceStatus.BUSY
        assert view.canonical_status == "busy"

    def test_adapt_from_dict_online(self, online_rrd):
        """adapt_registered_runtime_device_dict should work from a serialised projection."""
        data = online_rrd.to_dict()
        view = adapt_registered_runtime_device_dict(data)
        assert view.device_id == "canonical-phone-001"
        assert view.coordination_status == CoordinationDeviceStatus.AVAILABLE

    def test_adapt_extracts_capabilities_from_profile(self, online_rrd):
        """Capabilities should be extracted from the canonical profile."""
        view = adapt_registered_runtime_device(online_rrd)
        assert "screen" in view.capabilities
        assert "camera" in view.capabilities

    def test_adapt_preserves_metadata(self, online_rrd):
        """Metadata from the canonical projection should be preserved."""
        view = adapt_registered_runtime_device(online_rrd)
        assert view.metadata.get("owner") == "test_user"

    def test_adapt_requires_non_empty_device_id(self):
        """adapt_registered_runtime_device must raise on missing device_id."""
        rrd = _FakeRRD(device_id="")
        with pytest.raises(ValueError, match="device_id"):
            adapt_registered_runtime_device(rrd)

    def test_adapt_dict_requires_non_empty_device_id(self):
        """adapt_registered_runtime_device_dict must raise on missing device_id."""
        with pytest.raises(ValueError, match="device_id"):
            adapt_registered_runtime_device_dict({"device_id": ""})

    def test_ingested_at_is_recent(self, online_rrd):
        """ingested_at should be set to a recent timestamp."""
        before = time.time()
        view = adapt_registered_runtime_device(online_rrd)
        after = time.time()
        assert before <= view.ingested_at <= after

    def test_refresh_coordination_view_preserves_local_state(self, online_rrd):
        """refresh_coordination_view should preserve coordination-local task state."""
        view = adapt_registered_runtime_device(online_rrd)
        view.mark_task_assigned("task-xyz")

        updated_rrd = _FakeRRD(
            device_id=online_rrd.device_id,
            device_name="Updated Phone Name",
            status="online",
        )
        refreshed = refresh_coordination_view(view, updated_rrd)

        # Canonical fields updated
        assert refreshed.device_name == "Updated Phone Name"
        # Coordination-local task state preserved
        assert refreshed.current_task_id == "task-xyz"
        assert "task-xyz" in refreshed.assigned_task_ids
        assert refreshed.coordination_status == CoordinationDeviceStatus.BUSY

    def test_coordination_view_is_available_for_task_when_online(self, online_rrd):
        """is_available_for_task() should return True for an AVAILABLE view."""
        view = adapt_registered_runtime_device(online_rrd)
        assert view.is_available_for_task() is True

    def test_coordination_view_not_available_when_offline(self, offline_rrd):
        """is_available_for_task() should return False for an UNAVAILABLE view."""
        view = adapt_registered_runtime_device(offline_rrd)
        assert view.is_available_for_task() is False


# ---------------------------------------------------------------------------
# 2. Local state does not define canonical device truth
# ---------------------------------------------------------------------------

class TestLocalStateDoesNotDefineCanonicalTruth:
    """Node_71 local state must not define canonical device truth.

    Coordination-local mutations (mark_task_assigned, mark_task_released,
    coordination_status changes) are scoped to the CoordinationDeviceView and
    must not be confused with canonical state.
    """

    def test_mark_task_assigned_sets_busy_coordination_status(self, online_rrd):
        """mark_task_assigned sets coordination_status to BUSY (local only)."""
        view = adapt_registered_runtime_device(online_rrd)
        assert view.coordination_status == CoordinationDeviceStatus.AVAILABLE
        assert view.canonical_status == "online"  # canonical unchanged

        view.mark_task_assigned("task-001")

        # Coordination status changed locally
        assert view.coordination_status == CoordinationDeviceStatus.BUSY
        # Canonical status unchanged — it reflects the RRD projection
        assert view.canonical_status == "online"

    def test_mark_task_released_restores_available_status(self, online_rrd):
        """mark_task_released restores AVAILABLE status when canonical shows online."""
        view = adapt_registered_runtime_device(online_rrd)
        view.mark_task_assigned("task-001")
        view.mark_task_released("task-001")

        assert view.coordination_status == CoordinationDeviceStatus.AVAILABLE
        assert view.current_task_id is None
        assert "task-001" not in view.assigned_task_ids

    def test_canonical_status_not_mutated_by_local_operations(self, online_rrd):
        """Canonical status field remains unchanged by any local coordination operations."""
        view = adapt_registered_runtime_device(online_rrd)
        original_canonical = view.canonical_status

        view.mark_task_assigned("task-002")
        assert view.canonical_status == original_canonical  # unchanged

        view.mark_task_released("task-002")
        assert view.canonical_status == original_canonical  # still unchanged

    def test_two_views_of_same_device_independent(self, online_rrd):
        """Two separate CoordinationDeviceViews for the same canonical device
        do not share state — each is independently scoped."""
        view_a = adapt_registered_runtime_device(online_rrd)
        view_b = adapt_registered_runtime_device(online_rrd)

        view_a.mark_task_assigned("task-a")
        assert view_b.current_task_id is None  # view_b unaffected

    def test_to_dict_excludes_canonical_write_back_intent(self, online_rrd):
        """CoordinationDeviceView.to_dict() should contain coordination fields
        and the canonical_status field (read-only) but no write authority signal."""
        view = adapt_registered_runtime_device(online_rrd)
        d = view.to_dict()
        assert "coordination_status" in d
        assert "canonical_status" in d
        # Should not contain UDM-write-back fields
        assert "udm_update" not in d
        assert "write_to_udm" not in d

    def test_group_ids_are_coordination_local(self, online_rrd):
        """Group membership is coordination-local and not part of canonical projection."""
        view = adapt_registered_runtime_device(online_rrd)
        view.group_ids.append("group-001")
        assert view.group_ids == ["group-001"]
        # Adapting the same canonical projection again yields empty group_ids
        fresh_view = adapt_registered_runtime_device(online_rrd)
        assert fresh_view.group_ids == []


# ---------------------------------------------------------------------------
# 3. Grouping and task coordination work after normalisation
# ---------------------------------------------------------------------------

class TestGroupingAndCoordinationBehavior:
    """Coordination features (grouping, task scheduling) work with canonical views."""

    def test_list_available_views_from_multiple_ingested_devices(self):
        """list_canonical_views(available_only=True) returns only schedulable devices."""
        views = {}
        for did, status in [
            ("d-001", "online"),
            ("d-002", "offline"),
            ("d-003", "busy"),
            ("d-004", "online"),
        ]:
            rrd = _FakeRRD(device_id=did, status=status)
            v = adapt_registered_runtime_device(rrd)
            views[did] = v

        available = [v for v in views.values() if v.is_available_for_task()]
        assert len(available) == 2
        assert all(v.coordination_status == CoordinationDeviceStatus.AVAILABLE for v in available)

    def test_task_assignment_and_release_cycle(self):
        """Full assignment → release cycle works correctly."""
        rrd = _FakeRRD(device_id="dev-x", status="online")
        view = adapt_registered_runtime_device(rrd)

        assert view.is_available_for_task()

        view.mark_task_assigned("task-999")
        assert not view.is_available_for_task()
        assert view.current_task_id == "task-999"

        view.mark_task_released("task-999")
        assert view.is_available_for_task()
        assert view.current_task_id is None

    def test_group_membership_tracking_in_coordination_view(self):
        """Group IDs can be added to and removed from a CoordinationDeviceView."""
        rrd = _FakeRRD(device_id="grp-dev-001", status="online")
        view = adapt_registered_runtime_device(rrd)

        view.group_ids.append("warehouse-group")
        assert "warehouse-group" in view.group_ids

        view.group_ids.remove("warehouse-group")
        assert "warehouse-group" not in view.group_ids

    def test_multiple_task_assignments_tracked(self):
        """Multiple task IDs are tracked in assigned_task_ids."""
        rrd = _FakeRRD(device_id="multi-task-dev", status="online")
        view = adapt_registered_runtime_device(rrd)

        view.mark_task_assigned("task-alpha")
        view.mark_task_assigned("task-beta")
        assert "task-alpha" in view.assigned_task_ids
        assert "task-beta" in view.assigned_task_ids

    def test_to_dict_round_trips_coordination_fields(self):
        """CoordinationDeviceView.to_dict() should contain all expected fields."""
        rrd = _FakeRRD(
            device_id="rt-dev",
            device_name="Round Trip",
            device_type="android_phone",
            status="online",
            capabilities=_FakeCapabilityProfile(["screen"]),
        )
        view = adapt_registered_runtime_device(rrd)
        # Before task assignment: AVAILABLE
        d_before = view.to_dict()
        assert d_before["device_id"] == "rt-dev"
        assert d_before["device_name"] == "Round Trip"
        assert d_before["coordination_status"] == CoordinationDeviceStatus.AVAILABLE.value

        # After task assignment: BUSY
        view.group_ids.append("grp-1")
        view.mark_task_assigned("t-1")
        d_after = view.to_dict()
        assert d_after["coordination_status"] == CoordinationDeviceStatus.BUSY.value
        assert d_after["current_task_id"] == "t-1"
        assert "grp-1" in d_after["group_ids"]


# ---------------------------------------------------------------------------
# 4. Coordination-local updates do not represent canonical registration mutations
# ---------------------------------------------------------------------------

class TestCoordinationLocalUpdateBoundary:
    """Local state updates are coordination-local, not canonical registration mutations."""

    def test_coordination_status_enum_values_are_well_defined(self):
        """CoordinationDeviceStatus has the expected values."""
        assert CoordinationDeviceStatus.AVAILABLE.value == "available"
        assert CoordinationDeviceStatus.BUSY.value == "busy"
        assert CoordinationDeviceStatus.UNAVAILABLE.value == "unavailable"

    def test_refreshed_view_from_canonical_reflects_canonical_status(self):
        """After a canonical refresh, coordination_status is re-derived from canonical."""
        rrd = _FakeRRD(device_id="refresh-dev", status="online")
        view = adapt_registered_runtime_device(rrd)
        view.mark_task_assigned("t-x")  # goes BUSY

        # Refresh with an offline canonical projection (no active task → should go UNAVAILABLE)
        offline_rrd = _FakeRRD(device_id="refresh-dev", status="offline")
        # mark_task_released first to simulate task completion
        view.mark_task_released("t-x")
        refreshed = refresh_coordination_view(view, offline_rrd)
        # canonical says offline → UNAVAILABLE
        assert refreshed.coordination_status == CoordinationDeviceStatus.UNAVAILABLE
        assert refreshed.canonical_status == "offline"

    def test_coordination_view_does_not_expose_udm_write_methods(self):
        """CoordinationDeviceView must not have UDM write methods."""
        rrd = _FakeRRD(device_id="check-dev", status="online")
        view = adapt_registered_runtime_device(rrd)
        # These would imply canonical authority — must not exist on the view
        assert not hasattr(view, "save_to_udm")
        assert not hasattr(view, "push_to_registry")
        assert not hasattr(view, "register_with_udm")
        assert not hasattr(view, "canonical_update")

    def test_idle_canonical_status_maps_to_available(self):
        """'idle' canonical status should map to AVAILABLE coordination status."""
        rrd = _FakeRRD(device_id="idle-dev", status="idle")
        view = adapt_registered_runtime_device(rrd)
        assert view.coordination_status == CoordinationDeviceStatus.AVAILABLE

    def test_maintenance_canonical_status_maps_to_unavailable(self):
        """'maintenance' canonical status should map to UNAVAILABLE coordination status."""
        rrd = _FakeRRD(device_id="maint-dev", status="maintenance")
        view = adapt_registered_runtime_device(rrd)
        assert view.coordination_status == CoordinationDeviceStatus.UNAVAILABLE

    def test_error_canonical_status_maps_to_unavailable(self):
        """'error' canonical status should map to UNAVAILABLE coordination status."""
        rrd = _FakeRRD(device_id="err-dev", status="error")
        view = adapt_registered_runtime_device(rrd)
        assert view.coordination_status == CoordinationDeviceStatus.UNAVAILABLE

    def test_unknown_canonical_status_maps_to_unavailable(self):
        """Unknown canonical status should map to UNAVAILABLE (safe default)."""
        rrd = _FakeRRD(device_id="unk-dev", status="some_unknown_status")
        view = adapt_registered_runtime_device(rrd)
        assert view.coordination_status == CoordinationDeviceStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Engine-level canonical intake (integration)
# ---------------------------------------------------------------------------

class TestEngineCanonicalIntake:
    """MultiDeviceCoordinatorEngine canonical intake integration tests."""

    @pytest.fixture
    def engine(self):
        """Create a minimal engine without network services."""
        from core.multi_device_coordinator_engine import (
            MultiDeviceCoordinatorEngine, CoordinatorConfig
        )
        from core.device_discovery import DiscoveryConfig
        from core.state_synchronizer import SyncConfig
        from core.task_scheduler import SchedulerConfig

        config = CoordinatorConfig(
            node_id="test-pr7-coordinator",
            discovery_config=DiscoveryConfig(
                mdns_enabled=False,
                upnp_enabled=False,
                broadcast_enabled=False,
            ),
            sync_config=SyncConfig(gossip_interval=1.0),
            scheduler_config=SchedulerConfig(task_timeout=5.0),
            heartbeat_interval=2.0,
        )
        return MultiDeviceCoordinatorEngine(config)

    def test_engine_has_canonical_views_attribute(self, engine):
        """Engine should expose _canonical_views dict."""
        assert hasattr(engine, "_canonical_views")
        assert isinstance(engine._canonical_views, dict)

    def test_engine_ingest_canonical_device_view(self, engine):
        """ingest_canonical_device_view should add a CoordinationDeviceView."""
        rrd = _FakeRRD(device_id="eng-dev-001", device_name="Engine Device", status="online")
        result = engine.ingest_canonical_device_view(rrd)
        assert result is True
        view = engine.get_canonical_view("eng-dev-001")
        assert view is not None
        assert view.device_id == "eng-dev-001"
        assert view.coordination_status == CoordinationDeviceStatus.AVAILABLE

    def test_engine_ingest_canonical_device_view_dict(self, engine):
        """ingest_canonical_device_view_dict should add a CoordinationDeviceView."""
        data = {
            "device_id": "eng-dev-002",
            "device_name": "Dict Device",
            "status": "online",
            "capabilities": {"names": ["camera"]},
            "metadata": {},
        }
        result = engine.ingest_canonical_device_view_dict(data)
        assert result is True
        view = engine.get_canonical_view("eng-dev-002")
        assert view is not None
        assert "camera" in view.capabilities

    def test_engine_ingest_updates_stats(self, engine):
        """Ingesting a new device should increment devices_registered stat."""
        initial = engine._stats["devices_registered"]
        rrd = _FakeRRD(device_id="stat-dev", status="online")
        engine.ingest_canonical_device_view(rrd)
        assert engine._stats["devices_registered"] == initial + 1

    def test_engine_ingest_refresh_does_not_double_count(self, engine):
        """Re-ingesting the same device should refresh, not create duplicate."""
        rrd = _FakeRRD(device_id="refresh-eng-dev", status="online")
        engine.ingest_canonical_device_view(rrd)
        initial_count = engine._stats["devices_registered"]

        # Re-ingest — should refresh, not add new stat
        engine.ingest_canonical_device_view(rrd)
        assert engine._stats["devices_registered"] == initial_count

    def test_engine_remove_canonical_device_view(self, engine):
        """remove_canonical_device_view should remove device from coordination runtime."""
        rrd = _FakeRRD(device_id="rem-dev", status="online")
        engine.ingest_canonical_device_view(rrd)
        assert engine.get_canonical_view("rem-dev") is not None

        result = engine.remove_canonical_device_view("rem-dev")
        assert result is True
        assert engine.get_canonical_view("rem-dev") is None

    def test_engine_remove_nonexistent_canonical_view(self, engine):
        """remove_canonical_device_view returns False for unknown device."""
        assert engine.remove_canonical_device_view("nonexistent") is False

    def test_engine_list_canonical_views(self, engine):
        """list_canonical_views should list all ingested views."""
        for i, status in enumerate(["online", "offline", "online"]):
            rrd = _FakeRRD(device_id=f"list-dev-{i}", status=status)
            engine.ingest_canonical_device_view(rrd)

        all_views = engine.list_canonical_views()
        assert len(all_views) == 3

        available = engine.list_canonical_views(available_only=True)
        assert len(available) == 2

    def test_engine_stats_include_canonical_view_counts(self, engine):
        """get_stats() should include canonical_views_total/available/busy fields."""
        for did, status in [("sv-001", "online"), ("sv-002", "busy"), ("sv-003", "offline")]:
            engine.ingest_canonical_device_view(_FakeRRD(device_id=did, status=status))

        stats = engine.get_stats()
        assert "canonical_views_total" in stats
        assert "canonical_views_available" in stats
        assert "canonical_views_busy" in stats
        assert stats["canonical_views_total"] == 3
        assert stats["canonical_views_available"] == 1
        assert stats["canonical_views_busy"] == 1

    def test_engine_register_device_is_coordination_local(self, engine):
        """register_device() works as before but is clearly coordination-local."""
        from models.device import Device, DeviceType, DeviceState, Capability
        device = Device(
            device_id="legacy-dev-001",
            name="Legacy Device",
            device_type=DeviceType.SENSOR,
            state=DeviceState.IDLE,
        )
        success = engine.register_device(device)
        assert success is True
        # Device is in local registry (coordination-local)
        found = engine.get_device("legacy-dev-001")
        assert found is not None
        # But it is NOT in canonical views (different intake path)
        assert engine.get_canonical_view("legacy-dev-001") is None

    def test_engine_update_device_state_is_coordination_local(self, engine):
        """update_device_state() updates coordination-local state only."""
        from models.device import Device, DeviceType, DeviceState
        device = Device(
            device_id="state-dev",
            name="State Device",
            device_type=DeviceType.SENSOR,
            state=DeviceState.IDLE,
        )
        engine.register_device(device)
        success = engine.update_device_state("state-dev", DeviceState.BUSY)
        assert success is True
        # Local registry state changed
        found = engine.get_device("state-dev")
        assert found.state == DeviceState.BUSY

    @pytest.mark.asyncio
    async def test_engine_task_coordination_with_canonical_views(self, engine):
        """Grouping and task coordination work after canonical view ingestion."""
        await engine.start()

        # Ingest canonical views
        for did, status in [("coord-dev-a", "online"), ("coord-dev-b", "online")]:
            engine.ingest_canonical_device_view(_FakeRRD(device_id=did, status=status))

        # Group coordination
        group_id = engine.create_device_group("test-group", ["coord-dev-a", "coord-dev-b"])
        assert group_id is not None

        grp = engine.get_device_group(group_id)
        assert grp is not None
        assert "coord-dev-a" in grp
        assert "coord-dev-b" in grp

        await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_broadcast_to_group_works(self, engine):
        """broadcast_to_group works after canonical view ingestion and group creation."""
        await engine.start()

        # Register devices in legacy registry for broadcast (backward compat)
        from models.device import Device, DeviceType, DeviceState
        for did in ["bcast-a", "bcast-b"]:
            engine.register_device(Device(
                device_id=did, name=did, device_type=DeviceType.SENSOR,
                state=DeviceState.IDLE,
            ))
            # Also ingest canonical view
            engine.ingest_canonical_device_view(_FakeRRD(device_id=did, status="online"))

        group_id = engine.create_device_group("bcast-group", ["bcast-a", "bcast-b"])
        result = await engine.broadcast_to_group(group_id, "ping", {})
        assert result["success"] is True

        await engine.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
