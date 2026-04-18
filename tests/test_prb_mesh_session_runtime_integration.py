"""tests/test_prb_mesh_session_runtime_integration.py
======================================================
Tests for PR-B: MeshSession Lifecycle Runtime Integration.

Coverage:
  1.  find_sessions_for_device — returns session_id when source_device_id matches.
  2.  find_sessions_for_device — returns session_id when primary_device_id matches.
  3.  find_sessions_for_device — returns empty list for unknown device.
  4.  find_sessions_for_device — excludes terminal sessions by default.
  5.  find_sessions_for_device — includes terminal sessions when only_non_terminal=False.
  6.  handle_device_register — creates+activates a mesh session for the registered device.
  7.  handle_device_register — mesh session failure is non-fatal (registration still succeeds).
  8.  _patch_disconnect_to_udm — terminates active mesh session on device disconnect.
  9.  _patch_disconnect_to_udm — mesh session terminate failure is non-fatal.
  10. check_offline_devices — suspends active mesh session on heartbeat-miss.
  11. SwarmCoordinator.dispatch_team — creates+activates+terminates mesh session.
  12. SwarmCoordinator.dispatch_team — terminates with outcome=failed on member errors.
  13. SwarmCoordinator.dispatch_team — mesh session wiring failure is non-fatal.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_coordinator():
    """Return a fresh MeshSessionLifecycleCoordinator backed by a stub store."""
    from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

    store = MagicMock()
    store.save = MagicMock()
    store.load = MagicMock(return_value=None)
    store.mark_terminal = MagicMock()
    return MeshSessionLifecycleCoordinator(store=store)


def _make_session(device_id: str, session_id: Optional[str] = None):
    from contracts.mesh_session import build_mesh_session

    return build_mesh_session(
        source_device_id=device_id,
        primary_device_id=device_id,
        session_id=session_id or str(uuid.uuid4()),
    )


# ---------------------------------------------------------------------------
# 1–5: find_sessions_for_device
# ---------------------------------------------------------------------------


class TestFindSessionsForDevice:
    """MeshSessionLifecycleCoordinator.find_sessions_for_device"""

    def test_returns_session_id_for_source_device(self):
        coord = _fresh_coordinator()
        sess = _make_session("dev_source_01")
        record = coord.create_session(sess)
        assert record is not None

        result = coord.find_sessions_for_device("dev_source_01")
        assert record.session_id in result

    def test_returns_session_id_for_primary_device(self):
        from contracts.mesh_session import build_mesh_session

        coord = _fresh_coordinator()
        sess = build_mesh_session(
            source_device_id="source_device",
            primary_device_id="primary_device_01",
        )
        record = coord.create_session(sess)
        assert record is not None

        result = coord.find_sessions_for_device("primary_device_01")
        assert record.session_id in result

    def test_returns_empty_for_unknown_device(self):
        coord = _fresh_coordinator()
        sess = _make_session("dev_known")
        coord.create_session(sess)

        result = coord.find_sessions_for_device("dev_unknown_xyz")
        assert result == []

    def test_excludes_terminal_sessions_by_default(self):
        coord = _fresh_coordinator()
        sess = _make_session("dev_term_01")
        record = coord.create_session(sess)
        assert record is not None
        coord.activate_session(record.session_id)
        coord.terminate_session(record.session_id, outcome="completed")

        result = coord.find_sessions_for_device("dev_term_01")
        assert result == []

    def test_includes_terminal_sessions_when_flag_false(self):
        coord = _fresh_coordinator()
        sess = _make_session("dev_term_02")
        record = coord.create_session(sess)
        assert record is not None
        coord.activate_session(record.session_id)
        coord.terminate_session(record.session_id, outcome="completed")

        result = coord.find_sessions_for_device("dev_term_02", only_non_terminal=False)
        assert record.session_id in result


# ---------------------------------------------------------------------------
# 6–7: handle_device_register
# ---------------------------------------------------------------------------


class TestHandleDeviceRegister:
    """galaxy_gateway.android.handlers.registration.handle_device_register"""

    @pytest.mark.asyncio
    async def test_registration_creates_and_activates_mesh_session(self):
        """Successful device registration must leave an ACTIVE mesh session in the coordinator."""
        from core.mesh.mesh_session_lifecycle import (
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )
        from galaxy_gateway.android.handlers.registration import handle_device_register

        reset_lifecycle_coordinator()

        device_id = f"android_test_{uuid.uuid4().hex[:8]}"
        message = {
            "type": "register",
            "device_id": device_id,
            "device_type": "android_phone",
            "platform": "android",
            "model": "Test Phone",
        }

        bridge = MagicMock()
        bridge._write_registration_to_udm = MagicMock()
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        bridge._sync_device_router_session = MagicMock()

        stub_store = MagicMock()
        stub_store.save = MagicMock()
        stub_store.load = MagicMock(return_value=None)
        stub_store.mark_terminal = MagicMock()

        with patch(
            "core.mesh.mesh_session_persistence.get_persistence_store",
            return_value=stub_store,
        ):
            result = await handle_device_register(bridge, MagicMock(), message)

        assert result.get("success") is True, f"Registration failed: {result}"

        coord = get_lifecycle_coordinator()
        active_ids = coord.find_sessions_for_device(device_id)
        assert len(active_ids) >= 1, (
            f"Expected at least one active mesh session for device {device_id}, "
            f"found: {active_ids}"
        )
        record = coord.get_record(active_ids[0])
        assert record is not None
        assert record.status == "active", f"Expected 'active', got '{record.status}'"

    @pytest.mark.asyncio
    async def test_registration_succeeds_even_if_mesh_session_fails(self):
        """Mesh session creation failure must not prevent device registration from succeeding."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = f"android_fail_{uuid.uuid4().hex[:8]}"
        message = {
            "type": "register",
            "device_id": device_id,
            "device_type": "android_phone",
            "platform": "android",
        }

        bridge = MagicMock()
        bridge._write_registration_to_udm = MagicMock()
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        bridge._sync_device_router_session = MagicMock()

        with patch(
            "core.mesh.mesh_session_lifecycle.get_lifecycle_coordinator",
            side_effect=RuntimeError("simulated lifecycle failure"),
        ):
            result = await handle_device_register(bridge, MagicMock(), message)

        assert result.get("success") is True, (
            f"Registration should succeed even when mesh session wiring fails: {result}"
        )


# ---------------------------------------------------------------------------
# 8–9: _patch_disconnect_to_udm
# ---------------------------------------------------------------------------


class TestPatchDisconnectToUdm:
    """galaxy_gateway.android_bridge.AndroidBridge._patch_disconnect_to_udm"""

    def _build_bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        return bridge

    def test_disconnect_terminates_active_mesh_session(self):
        """_patch_disconnect_to_udm must terminate the active mesh session for the device."""
        from core.mesh.mesh_session_lifecycle import (
            activate_durable_session,
            create_durable_session,
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )

        reset_lifecycle_coordinator()

        stub_store = MagicMock()
        stub_store.save = MagicMock()
        stub_store.load = MagicMock(return_value=None)
        stub_store.mark_terminal = MagicMock()

        device_id = f"disc_dev_{uuid.uuid4().hex[:8]}"

        with patch(
            "core.mesh.mesh_session_persistence.get_persistence_store",
            return_value=stub_store,
        ):
            sess = _make_session(device_id)
            record = create_durable_session(sess)
            assert record is not None
            activate_durable_session(record.session_id)
            session_id = record.session_id

            bridge = self._build_bridge()
            bridge._patch_runtime_state_to_udm = MagicMock()
            # UCM import may fail in test env; the bridge wraps it in try/except.
            bridge._patch_disconnect_to_udm(device_id)

        coord = get_lifecycle_coordinator()
        updated = coord.get_record(session_id)
        assert updated is not None
        assert updated.status in {"cancelled", "failed", "completed"}, (
            f"Expected terminal status after disconnect, got '{updated.status}'"
        )

    def test_disconnect_is_nonfatal_when_mesh_session_terminate_fails(self):
        """_patch_disconnect_to_udm must not raise even if mesh session termination fails."""
        bridge = self._build_bridge()
        bridge._patch_runtime_state_to_udm = MagicMock()

        with patch(
            "core.mesh.mesh_session_lifecycle.get_lifecycle_coordinator",
            side_effect=RuntimeError("simulated"),
        ):
            bridge._patch_disconnect_to_udm("some_device")  # must not raise


# ---------------------------------------------------------------------------
# 10: check_offline_devices
# ---------------------------------------------------------------------------


class TestCheckOfflineDevices:
    """core.device_registry.DeviceRegistry.check_offline_devices"""

    @pytest.mark.asyncio
    async def test_heartbeat_miss_suspends_active_mesh_session(self):
        """check_offline_devices must suspend the active mesh session for a timed-out device."""
        import time as _time

        from core.device_registry import DeviceRegistry, DeviceStatus
        from core.mesh.mesh_session_lifecycle import (
            activate_durable_session,
            create_durable_session,
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )

        reset_lifecycle_coordinator()

        stub_store = MagicMock()
        stub_store.save = MagicMock()
        stub_store.load = MagicMock(return_value=None)
        stub_store.mark_terminal = MagicMock()

        device_id = f"hb_miss_{uuid.uuid4().hex[:8]}"

        # Create and activate a mesh session for the device
        with patch(
            "core.mesh.mesh_session_persistence.get_persistence_store",
            return_value=stub_store,
        ):
            sess = _make_session(device_id)
            record = create_durable_session(sess)
            assert record is not None
            activate_durable_session(record.session_id)
            session_id = record.session_id

            # Build a minimal in-memory registry with a timed-out device
            from core.schemas.device import DeviceModel

            registry = DeviceRegistry.__new__(DeviceRegistry)
            registry.devices = {}
            registry._on_device_registered = []
            registry._on_device_online = []
            registry._on_device_offline = []

            dev = DeviceModel(
                device_id=device_id,
                status=DeviceStatus.ONLINE,
                last_heartbeat=_time.time() - 999.0,
            )
            registry.devices[device_id] = dev

            await registry.check_offline_devices(timeout=60.0)

        coord = get_lifecycle_coordinator()
        updated = coord.get_record(session_id)
        assert updated is not None
        assert updated.status == "suspended", (
            f"Expected 'suspended' after heartbeat-miss, got '{updated.status}'"
        )


# ---------------------------------------------------------------------------
# 11–13: SwarmCoordinator.dispatch_team mesh session lifecycle
# ---------------------------------------------------------------------------


class TestSwarmCoordinatorMeshSession:
    """core.swarm_coordinator.SwarmCoordinator.dispatch_team mesh session wiring."""

    def _make_member(self, agent_id: str = "agent_01"):
        m = MagicMock()
        m.agent_id = agent_id
        m.agent_name = f"Agent {agent_id}"
        m.role_in_team = "executor"
        m.provider = "openai"
        m.model = "gpt-4"
        m.template = "default"
        m.task = ""
        m.required_capabilities = []
        m.metadata = {}
        return m

    @pytest.mark.asyncio
    async def test_dispatch_team_creates_activates_then_terminates_mesh_session(self):
        """dispatch_team must create+activate a mesh session, then terminate it on completion."""
        from core.mesh.mesh_session_lifecycle import (
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )
        from core.swarm_coordinator import SwarmCoordinator

        reset_lifecycle_coordinator()

        stub_store = MagicMock()
        stub_store.save = MagicMock()
        stub_store.load = MagicMock(return_value=None)
        stub_store.mark_terminal = MagicMock()

        member = self._make_member()

        with patch(
            "core.mesh.mesh_session_persistence.get_persistence_store",
            return_value=stub_store,
        ):
            coordinator = SwarmCoordinator()
            coordinator._command_router = MagicMock()
            coordinator._scoring_engine = MagicMock()
            coordinator._scoring_engine.select_best_device.return_value = MagicMock(
                device_id="device_01", total=0.9
            )
            coordinator._ledger = MagicMock()

            async def fake_dispatch(manifest):
                return {"success": True, "output": "ok", "latency_ms": 10}

            with patch.object(coordinator, "_dispatch_one", side_effect=fake_dispatch):
                session_id = str(uuid.uuid4())
                task_id = f"task_{uuid.uuid4().hex[:8]}"

                result = await coordinator.dispatch_team(
                    members=[member],
                    task="test task",
                    session_id=session_id,
                    task_id=task_id,
                )

        coord = get_lifecycle_coordinator()
        # The session should now be terminal (completed)
        # session_id is used as mesh session id
        record = coord.get_record(session_id)
        assert record is not None, (
            f"Expected mesh session record for session_id={session_id}"
        )
        assert record.status == "completed", (
            f"Expected 'completed' after successful dispatch, got '{record.status}'"
        )

    @pytest.mark.asyncio
    async def test_dispatch_team_terminates_with_failed_on_member_error(self):
        """dispatch_team must terminate mesh session with outcome=failed when a member fails."""
        from core.mesh.mesh_session_lifecycle import (
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )
        from core.swarm_coordinator import SwarmCoordinator

        reset_lifecycle_coordinator()

        stub_store = MagicMock()
        stub_store.save = MagicMock()
        stub_store.load = MagicMock(return_value=None)
        stub_store.mark_terminal = MagicMock()

        member = self._make_member()

        with patch(
            "core.mesh.mesh_session_persistence.get_persistence_store",
            return_value=stub_store,
        ):
            coordinator = SwarmCoordinator()
            coordinator._command_router = MagicMock()
            coordinator._scoring_engine = MagicMock()
            coordinator._scoring_engine.select_best_device.return_value = MagicMock(
                device_id="device_02", total=0.8
            )
            coordinator._ledger = MagicMock()

            async def fake_dispatch_fail(manifest):
                raise RuntimeError("device unreachable")

            with patch.object(coordinator, "_dispatch_one", side_effect=fake_dispatch_fail):
                session_id = str(uuid.uuid4())
                task_id = f"task_{uuid.uuid4().hex[:8]}"

                result = await coordinator.dispatch_team(
                    members=[member],
                    task="test failing task",
                    session_id=session_id,
                    task_id=task_id,
                )

        coord = get_lifecycle_coordinator()
        record = coord.get_record(session_id)
        assert record is not None
        assert record.status == "failed", (
            f"Expected 'failed' after member exception, got '{record.status}'"
        )

    @pytest.mark.asyncio
    async def test_dispatch_team_proceeds_when_mesh_session_wiring_unavailable(self):
        """dispatch_team must not raise and must return a TeamResult even if mesh lifecycle import fails."""
        from core.swarm_coordinator import SwarmCoordinator

        coordinator = SwarmCoordinator()
        coordinator._command_router = MagicMock()
        coordinator._scoring_engine = MagicMock()
        coordinator._scoring_engine.select_best_device.return_value = MagicMock(
            device_id="device_03", total=0.7
        )
        coordinator._ledger = MagicMock()

        member = self._make_member()

        async def fake_dispatch_ok(manifest):
            return {"success": True, "output": "done", "latency_ms": 5}

        with patch.object(coordinator, "_dispatch_one", side_effect=fake_dispatch_ok), \
             patch(
                "core.mesh.mesh_session_lifecycle.get_lifecycle_coordinator",
                side_effect=RuntimeError("simulated import failure"),
            ):
            result = await coordinator.dispatch_team(
                members=[member],
                task="task that is fine",
            )

        from core.agent_team import TeamResult

        assert isinstance(result, TeamResult)
        assert len(result.member_results) == 1
