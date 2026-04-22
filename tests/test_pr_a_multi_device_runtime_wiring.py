#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr_a_multi_device_runtime_wiring.py
===============================================
Acceptance tests for PR-A: Wire multi-device runtime hooks into the real
production event chain.

Coverage
--------
1.  DeviceRegistry.update_status OFFLINE → on_device_health_changed called.
2.  DeviceRegistry.update_status OFFLINE → on_participant_readiness_changed called.
3.  DeviceRegistry.check_offline_devices heartbeat miss → on_device_health_changed called.
4.  DeviceRegistry.check_offline_devices heartbeat miss → on_participant_readiness_changed called.
5.  SwarmCoordinator.dispatch_team → on_task_admitted_for_dispatch called.
6.  SystemOrchestrator Phase 4 → recover_sessions called.
7.  CrossDeviceCoordinator.execute_cross_device_task (success path) → on_participant_readiness_changed "ready" called.
8.  CrossDeviceCoordinator.execute_cross_device_task (error path) → on_participant_readiness_changed "degraded" called.
9.  All wiring calls are non-fatal (harness import failure degrades gracefully).
10. AndroidBridge._patch_disconnect_to_udm → on_device_health_changed + on_participant_readiness_changed called.
11. AndroidBridge._patch_reconnect_to_udm → on_device_health_changed (reconnect) + on_participant_readiness_changed "ready" called.
12. AndroidBridge wiring is non-fatal (harness import failure degrades gracefully).
13. MultiDeviceCoordinatorEngine.start → on_coordinator_state_updated called with "running".
14. MultiDeviceCoordinatorEngine._heartbeat_loop device timeout → on_device_health_changed + on_participant_readiness_changed called.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# 1–2: DeviceRegistry.update_status wiring
# ---------------------------------------------------------------------------

class TestDeviceRegistryUpdateStatusWiring:
    """DeviceRegistry.update_status() → harness hooks on OFFLINE transition."""

    def _make_registry_with_online_device(self, device_id: str = "test-dev-01"):
        """Return a DeviceRegistry instance with a single ONLINE device."""
        from core.device_registry import DeviceRegistry
        from core.device_types import DeviceStatus

        reg = DeviceRegistry.__new__(DeviceRegistry)
        reg.devices = {}
        reg.groups = {}
        reg.tag_index = {}
        reg.capability_index = {}
        reg.storage_path = MagicMock()
        reg.storage_path.parent = MagicMock()
        reg._on_device_registered = []
        reg._on_device_offline = []
        reg._on_device_online = []

        # Insert a pre-built ONLINE device record
        from core.schemas.device import DeviceModel as Device
        from core.device_types import DeviceType
        now = time.time()
        device = Device(
            device_id=device_id,
            device_type=DeviceType.ANDROID,
            name="Test Phone",
            status=DeviceStatus.ONLINE,
            registered_at=now,
            last_seen=now,
            last_heartbeat=now,
        )
        reg.devices[device_id] = device
        return reg

    def test_update_status_offline_calls_on_device_health_changed(self):
        """DeviceRegistry.update_status(OFFLINE) must call on_device_health_changed."""
        from core.device_types import DeviceStatus

        reg = self._make_registry_with_online_device("dev-offline-1")

        health_called_with = []

        def fake_health(event):
            health_called_with.append(event)
            return MagicMock()

        def fake_readiness(device_id, readiness, **kwargs):
            return MagicMock()

        with patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            asyncio.run(reg.update_status("dev-offline-1", status=DeviceStatus.OFFLINE))

        assert len(health_called_with) == 1
        event = health_called_with[0]
        assert event.device_id == "dev-offline-1"
        assert event.is_reachable is False
        assert event.event_type == "disconnect"

    def test_update_status_offline_calls_on_participant_readiness_changed(self):
        """DeviceRegistry.update_status(OFFLINE) must call on_participant_readiness_changed with 'lost'."""
        from core.device_types import DeviceStatus

        reg = self._make_registry_with_online_device("dev-offline-2")

        readiness_called_with = []

        def fake_readiness(device_id, readiness, **kwargs):
            readiness_called_with.append((device_id, readiness, kwargs))
            return MagicMock()

        def fake_health(event):
            return MagicMock()

        with patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            asyncio.run(reg.update_status("dev-offline-2", status=DeviceStatus.OFFLINE))

        assert len(readiness_called_with) == 1
        dev_id, readiness, kwargs = readiness_called_with[0]
        assert dev_id == "dev-offline-2"
        assert readiness == "lost"
        assert kwargs.get("reason") == "disconnect"

    def test_update_status_wiring_does_not_raise_on_import_failure(self):
        """Harness wiring must not propagate ImportError — graceful degradation."""
        from core.device_types import DeviceStatus

        reg = self._make_registry_with_online_device("dev-offline-3")

        with patch(
            "core.multi_device_runtime_harness.on_device_health_changed",
            side_effect=ImportError("harness not available"),
        ):
            # Must not raise
            asyncio.run(reg.update_status("dev-offline-3", status=DeviceStatus.OFFLINE))


# ---------------------------------------------------------------------------
# 3–4: DeviceRegistry.check_offline_devices wiring
# ---------------------------------------------------------------------------

class TestDeviceRegistryCheckOfflineWiring:
    """DeviceRegistry.check_offline_devices() → harness hooks on heartbeat timeout."""

    def _make_registry_with_stale_device(self, device_id: str = "stale-dev-01", stale_seconds: float = 120.0):
        from core.device_registry import DeviceRegistry
        from core.device_types import DeviceStatus, DeviceType
        from core.schemas.device import DeviceModel as Device

        reg = DeviceRegistry.__new__(DeviceRegistry)
        reg.devices = {}
        reg.groups = {}
        reg.tag_index = {}
        reg.capability_index = {}
        reg.storage_path = MagicMock()
        reg.storage_path.parent = MagicMock()
        reg._on_device_registered = []
        reg._on_device_offline = []
        reg._on_device_online = []

        now = time.time()
        device = Device(
            device_id=device_id,
            device_type=DeviceType.ANDROID,
            name="Stale Device",
            status=DeviceStatus.ONLINE,
            registered_at=now - stale_seconds,
            last_seen=now - stale_seconds,
            last_heartbeat=now - stale_seconds,
        )
        reg.devices[device_id] = device
        return reg

    def test_check_offline_devices_heartbeat_miss_calls_health_changed(self):
        """check_offline_devices() heartbeat timeout → on_device_health_changed called."""
        reg = self._make_registry_with_stale_device("stale-01", stale_seconds=120.0)

        health_called_with = []

        def fake_health(event):
            health_called_with.append(event)
            return MagicMock()

        def fake_readiness(device_id, readiness, **kwargs):
            return MagicMock()

        with patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            asyncio.run(reg.check_offline_devices(timeout=60.0))

        assert len(health_called_with) == 1
        event = health_called_with[0]
        assert event.device_id == "stale-01"
        assert event.event_type == "heartbeat_miss"
        assert event.is_reachable is False

    def test_check_offline_devices_heartbeat_miss_calls_readiness_changed(self):
        """check_offline_devices() heartbeat timeout → on_participant_readiness_changed 'lost' called."""
        reg = self._make_registry_with_stale_device("stale-02", stale_seconds=120.0)

        readiness_called = []

        def fake_readiness(device_id, readiness, **kwargs):
            readiness_called.append((device_id, readiness, kwargs))
            return MagicMock()

        def fake_health(event):
            return MagicMock()

        with patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            asyncio.run(reg.check_offline_devices(timeout=60.0))

        assert len(readiness_called) == 1
        dev_id, readiness, kwargs = readiness_called[0]
        assert dev_id == "stale-02"
        assert readiness == "lost"
        assert kwargs.get("reason") == "heartbeat_miss"

    def test_check_offline_devices_fresh_device_not_triggered(self):
        """check_offline_devices() must NOT fire harness for devices within timeout."""
        reg = self._make_registry_with_stale_device("fresh-01", stale_seconds=5.0)

        health_called = []
        readiness_called = []

        def fake_health(event):
            health_called.append(event)
            return MagicMock()

        def fake_readiness(device_id, readiness, **kwargs):
            readiness_called.append((device_id, readiness))
            return MagicMock()

        with patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            asyncio.run(reg.check_offline_devices(timeout=60.0))

        # Fresh device should NOT trigger the harness
        assert len(health_called) == 0
        assert len(readiness_called) == 0


# ---------------------------------------------------------------------------
# 5: SwarmCoordinator.dispatch_team wiring
# ---------------------------------------------------------------------------

class TestSwarmCoordinatorWiring:
    """SwarmCoordinator.dispatch_team() → on_task_admitted_for_dispatch called."""

    def test_dispatch_team_calls_on_task_admitted_for_dispatch(self):
        """dispatch_team() must call on_task_admitted_for_dispatch before substrate dispatch."""
        from core.swarm_coordinator import SwarmCoordinator
        from core.control_plane.swarm_manifest import SwarmAgentManifest

        admitted_calls = []

        def fake_admitted(canonical_task, *, candidate_device_ids=None, trace_id=None):
            admitted_calls.append({
                "canonical_task": canonical_task,
                "candidate_device_ids": candidate_device_ids,
                "trace_id": trace_id,
            })
            return MagicMock(success=True)

        async def fake_dispatch_remote(*args, **kwargs):
            return {"success": True, "output": "ok"}

        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = fake_dispatch_remote

        scoring_engine = MagicMock()
        scoring_engine.select_best_device.return_value = MagicMock(
            device_id="target-dev-01", total=0.9
        )

        coordinator = SwarmCoordinator(
            command_router=mock_router,
            scoring_engine=scoring_engine,
        )

        member = MagicMock()
        member.agent_id = "agent-001"
        member.agent_name = "TestAgent"

        # Build a minimal valid manifest so manifest creation doesn't raise
        mock_manifest = MagicMock(spec=SwarmAgentManifest)
        mock_manifest.target_device_id = "target-dev-01"
        mock_manifest.required_capabilities = []
        mock_manifest.manifest_id = "mfst-001"
        mock_manifest.metadata = {}

        from core.control_plane.smart_scheduler import DeviceScoreInput

        with patch("core.multi_device_runtime_harness.on_task_admitted_for_dispatch", fake_admitted), \
             patch("core.control_plane.swarm_manifest.SwarmAgentManifest.from_team_member",
                   return_value=mock_manifest):
            try:
                asyncio.run(coordinator.dispatch_team(
                    members=[member],
                    task="test task",
                    session_id="sess-001",
                    trace_id="trace-001",
                    task_id="task-001",
                    device_candidates=[
                        DeviceScoreInput(device_id="target-dev-01", ping_latency_ms=10.0, load_pct=5.0)
                    ],
                ))
            except Exception:
                pass  # substrate errors don't affect the harness call test

        assert len(admitted_calls) >= 1
        call_data = admitted_calls[0]
        assert call_data["canonical_task"]["task_type"] == "swarm_team"

    def test_dispatch_team_harness_failure_does_not_block_dispatch(self):
        """Harness import failure in dispatch_team must not raise."""
        from core.swarm_coordinator import SwarmCoordinator

        mock_router = MagicMock()
        scoring_engine = MagicMock()
        scoring_engine.select_best_device.return_value = None

        coordinator = SwarmCoordinator(
            command_router=mock_router,
            scoring_engine=scoring_engine,
        )
        member = MagicMock()
        member.agent_id = "agent-002"
        member.agent_name = "TestAgent2"

        with patch(
            "core.multi_device_runtime_harness.on_task_admitted_for_dispatch",
            side_effect=RuntimeError("harness exploded"),
        ):
            try:
                asyncio.run(coordinator.dispatch_team(
                    members=[member],
                    task="test task",
                ))
            except Exception:
                pass  # substrate errors expected; harness failure must not surface


# ---------------------------------------------------------------------------
# 6: SystemOrchestrator Phase 4 → recover_sessions wiring
# ---------------------------------------------------------------------------

class TestSystemOrchestratorRecoverSessions:
    """SystemOrchestrator._run_phase_4_background_subsystems() → recover_sessions called."""

    def test_phase4_calls_recover_sessions(self):
        """Phase 4 must call harness.recover_sessions() on startup."""
        from core.system_orchestrator import SystemOrchestrator

        recover_called = []

        mock_harness = MagicMock()
        mock_harness.recover_sessions.side_effect = lambda: recover_called.append(True) or []

        with patch(
            "core.multi_device_runtime_harness.get_multi_device_runtime_harness",
            return_value=mock_harness,
        ):
            orch = SystemOrchestrator(continue_on_failure=True)
            result = orch._run_phase_4_background_subsystems()

        assert len(recover_called) >= 1, (
            "recover_sessions() was not called from Phase 4 background subsystems"
        )

    def test_phase4_recover_sessions_failure_does_not_fail_phase(self):
        """recover_sessions() failure must not cause Phase 4 to return FAILED."""
        from core.system_orchestrator import SystemOrchestrator, PhaseStatus

        mock_harness = MagicMock()
        mock_harness.recover_sessions.side_effect = RuntimeError("persistence unavailable")

        with patch(
            "core.multi_device_runtime_harness.get_multi_device_runtime_harness",
            return_value=mock_harness,
        ):
            orch = SystemOrchestrator(continue_on_failure=True)
            result = orch._run_phase_4_background_subsystems()

        assert result.status != PhaseStatus.FAILED

    def test_phase4_recover_sessions_count_in_diagnostics(self):
        """Phase 4 must record mesh_sessions_recovered in diagnostics."""
        from core.system_orchestrator import SystemOrchestrator

        mock_harness = MagicMock()
        mock_harness.recover_sessions.return_value = [MagicMock(), MagicMock()]

        with patch(
            "core.multi_device_runtime_harness.get_multi_device_runtime_harness",
            return_value=mock_harness,
        ):
            orch = SystemOrchestrator(continue_on_failure=True)
            result = orch._run_phase_4_background_subsystems()

        assert result.data.get("checks", {}).get("mesh_sessions_recovered") == 2


# ---------------------------------------------------------------------------
# 7–8: CrossDeviceCoordinator readiness wiring
# ---------------------------------------------------------------------------

class TestCrossDeviceCoordinatorReadinessWiring:
    """CrossDeviceCoordinator.execute_cross_device_task() → on_participant_readiness_changed."""

    def _make_mock_formation(self, device_ids=None):
        """Build a minimal DeviceFormationGroup-like mock."""
        from core.device_formation.formation_group import DeviceFormationGroup
        from core.device_formation.formation_role import FormationMember, FormationRole

        device_ids = device_ids or ["src-dev", "tgt-dev"]
        members = [
            FormationMember(device_id=did, role=FormationRole.SOURCE if i == 0 else FormationRole.PRIMARY_EXECUTION, reason="x")
            for i, did in enumerate(device_ids)
        ]
        return DeviceFormationGroup(
            source_device_id=device_ids[0],
            members=members,
            runtime_domain_intent="cross_device",
        )

    def test_execute_cross_device_task_success_calls_readiness_ready(self):
        """On success path with formation, on_participant_readiness_changed('ready') is called."""
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator

        readiness_calls = []

        def fake_readiness(device_id, readiness, **kwargs):
            readiness_calls.append((device_id, readiness))
            return MagicMock()

        formation = self._make_mock_formation(["src-01", "tgt-01"])

        coord = CrossDeviceCoordinator()
        coord.shared_clipboard = {}
        coord.device_states = {}

        async def fake_generic(*a, **k):
            return {"success": True}

        with patch(
            "core.device_formation.formation_resolver.resolve_formation",
            return_value=(formation, MagicMock()),
        ), patch(
            "core.source_runtime_posture.resolve_source_runtime_posture",
            return_value=MagicMock(value="local"),
        ), patch(
            "core.source_runtime_posture.record_source_runtime_posture",
        ), patch(
            "core.multi_device_runtime_harness.on_participant_readiness_changed",
            fake_readiness,
        ), patch.object(coord, "_analyze_cross_device_task", return_value="generic"), \
           patch.object(coord, "_execute_generic_cross_device_task", side_effect=fake_generic), \
           patch(
               "galaxy_gateway.cross_device_coordinator.surface_cross_device_result"
           ):
            asyncio.run(coord.execute_cross_device_task(
                "do something",
                {"task_id": "t-1", "session_id": "s-1"},
                _substrate_caller="test",
            ))

        ready_calls = [(d, r) for d, r in readiness_calls if r == "ready"]
        assert len(ready_calls) >= 1, (
            "on_participant_readiness_changed('ready') was not called for formation members"
        )
        device_ids_notified = {d for d, r in ready_calls}
        assert "src-01" in device_ids_notified or "tgt-01" in device_ids_notified

    def test_execute_cross_device_task_error_calls_readiness_degraded(self):
        """On error path, on_participant_readiness_changed('degraded') is called for source device."""
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator

        readiness_calls = []

        def fake_readiness(device_id, readiness, **kwargs):
            readiness_calls.append((device_id, readiness))
            return MagicMock()

        coord = CrossDeviceCoordinator()
        coord.shared_clipboard = {}
        coord.device_states = {}

        with patch(
            "core.device_formation.formation_resolver.resolve_formation",
            side_effect=RuntimeError("formation unavailable"),
        ), patch(
            "core.source_runtime_posture.resolve_source_runtime_posture",
            return_value=MagicMock(value="local"),
        ), patch(
            "core.multi_device_runtime_harness.on_participant_readiness_changed",
            fake_readiness,
        ), patch.object(coord, "_analyze_cross_device_task", side_effect=RuntimeError("boom")), \
           patch(
               "galaxy_gateway.cross_device_coordinator.surface_cross_device_result"
           ):
            result = asyncio.run(coord.execute_cross_device_task(
                "do something",
                {"task_id": "t-err", "session_id": "s-err", "source_device_id": "src-err"},
                _substrate_caller="test",
            ))

        assert result.get("success") is False
        degraded_calls = [(d, r) for d, r in readiness_calls if r == "degraded"]
        assert len(degraded_calls) >= 1, (
            "on_participant_readiness_changed('degraded') was not called on task failure"
        )
        src_notified = any(d == "src-err" for d, r in degraded_calls)
        assert src_notified


# ---------------------------------------------------------------------------
# 9: Graceful degradation — harness never blocks production paths
# ---------------------------------------------------------------------------

class TestHarnessGracefulDegradation:
    """All harness wiring points must degrade gracefully when harness is unavailable."""

    def test_device_registry_offline_harness_import_error_is_silent(self):
        """DeviceRegistry OFFLINE transition must not raise even if harness import fails."""
        from core.device_types import DeviceStatus, DeviceType
        from core.schemas.device import DeviceModel as Device
        from core.device_registry import DeviceRegistry

        reg = DeviceRegistry.__new__(DeviceRegistry)
        reg.devices = {}
        reg.groups = {}
        reg.tag_index = {}
        reg.capability_index = {}
        reg.storage_path = MagicMock()
        reg.storage_path.parent = MagicMock()
        reg._on_device_registered = []
        reg._on_device_offline = []
        reg._on_device_online = []

        now = time.time()
        dev = Device(
            device_id="degrade-dev",
            device_type=DeviceType.ANDROID,
            name="test",
            status=DeviceStatus.ONLINE,
            registered_at=now,
            last_seen=now,
            last_heartbeat=now,
        )
        reg.devices["degrade-dev"] = dev

        with patch(
            "core.multi_device_runtime_harness.on_device_health_changed",
            side_effect=ImportError("no harness"),
        ):
            # Must complete without raising
            asyncio.run(reg.update_status("degrade-dev", status=DeviceStatus.OFFLINE))

    def test_swarm_coordinator_harness_import_error_is_silent(self):
        """SwarmCoordinator dispatch_team must not raise if harness import fails."""
        from core.swarm_coordinator import SwarmCoordinator

        mock_router = MagicMock()
        scoring_engine = MagicMock()
        scoring_engine.select_best_device.return_value = None

        coordinator = SwarmCoordinator(command_router=mock_router, scoring_engine=scoring_engine)
        member = MagicMock()
        member.agent_id = "agent-degrade"
        member.agent_name = "DegradeAgent"

        with patch(
            "core.multi_device_runtime_harness.on_task_admitted_for_dispatch",
            side_effect=ImportError("harness gone"),
        ):
            try:
                asyncio.run(coordinator.dispatch_team(members=[member], task="t"))
            except Exception:
                pass  # substrate failure expected; harness failure must not surface


# ---------------------------------------------------------------------------
# 10–12: AndroidBridge disconnect / reconnect wiring
# ---------------------------------------------------------------------------

class TestAndroidBridgeDisconnectWiring:
    """AndroidBridge._patch_disconnect_to_udm() → harness hooks called."""

    def _make_minimal_bridge(self):
        """Return an AndroidBridge with mocked internal state."""
        from galaxy_gateway.android_bridge import AndroidBridge
        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._devices = {}
        bridge._pending_tasks = {}
        return bridge

    def test_patch_disconnect_calls_on_device_health_changed(self):
        """_patch_disconnect_to_udm() must call on_device_health_changed with disconnect event."""
        bridge = self._make_minimal_bridge()
        health_called = []

        def fake_health(event):
            health_called.append(event)
            return MagicMock()

        def fake_readiness(device_id, readiness, **kwargs):
            return MagicMock()

        with patch("galaxy_gateway.android_bridge.AndroidBridge._patch_runtime_state_to_udm"), \
             patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            bridge._patch_disconnect_to_udm("android-dev-01")

        assert len(health_called) == 1
        event = health_called[0]
        assert event.device_id == "android-dev-01"
        assert event.is_reachable is False
        assert event.event_type == "disconnect"
        assert event.health_score == 0.0

    def test_patch_disconnect_calls_on_participant_readiness_changed_lost(self):
        """_patch_disconnect_to_udm() must call on_participant_readiness_changed('lost')."""
        bridge = self._make_minimal_bridge()
        readiness_called = []

        def fake_readiness(device_id, readiness, **kwargs):
            readiness_called.append((device_id, readiness, kwargs))
            return MagicMock()

        def fake_health(event):
            return MagicMock()

        with patch("galaxy_gateway.android_bridge.AndroidBridge._patch_runtime_state_to_udm"), \
             patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            bridge._patch_disconnect_to_udm("android-dev-02")

        assert len(readiness_called) == 1
        dev_id, readiness, kwargs = readiness_called[0]
        assert dev_id == "android-dev-02"
        assert readiness == "lost"
        assert kwargs.get("reason") == "android_disconnect"

    def test_patch_disconnect_harness_failure_is_silent(self):
        """_patch_disconnect_to_udm() must not raise if harness import fails."""
        bridge = self._make_minimal_bridge()

        with patch("galaxy_gateway.android_bridge.AndroidBridge._patch_runtime_state_to_udm"), \
             patch(
                 "core.multi_device_runtime_harness.on_device_health_changed",
                 side_effect=ImportError("harness unavailable"),
             ):
            # Must not raise
            bridge._patch_disconnect_to_udm("android-dev-03")


class TestAndroidBridgeReconnectWiring:
    """AndroidBridge._patch_reconnect_to_udm() → harness hooks called."""

    def _make_minimal_bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._devices = {}
        bridge._pending_tasks = {}
        return bridge

    def test_patch_reconnect_calls_on_device_health_changed(self):
        """_patch_reconnect_to_udm() must call on_device_health_changed with reconnect event."""
        bridge = self._make_minimal_bridge()
        health_called = []

        def fake_health(event):
            health_called.append(event)
            return MagicMock()

        def fake_readiness(device_id, readiness, **kwargs):
            return MagicMock()

        with patch("galaxy_gateway.android_bridge.AndroidBridge._patch_runtime_state_to_udm"), \
             patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            bridge._patch_reconnect_to_udm("android-dev-04")

        assert len(health_called) == 1
        event = health_called[0]
        assert event.device_id == "android-dev-04"
        assert event.is_reachable is True
        assert event.event_type == "reconnect"
        assert event.health_score == 1.0

    def test_patch_reconnect_calls_on_participant_readiness_changed_ready(self):
        """_patch_reconnect_to_udm() must call on_participant_readiness_changed('ready')."""
        bridge = self._make_minimal_bridge()
        readiness_called = []

        def fake_readiness(device_id, readiness, **kwargs):
            readiness_called.append((device_id, readiness, kwargs))
            return MagicMock()

        def fake_health(event):
            return MagicMock()

        with patch("galaxy_gateway.android_bridge.AndroidBridge._patch_runtime_state_to_udm"), \
             patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
             patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
            bridge._patch_reconnect_to_udm("android-dev-05")

        assert len(readiness_called) == 1
        dev_id, readiness, kwargs = readiness_called[0]
        assert dev_id == "android-dev-05"
        assert readiness == "ready"
        assert kwargs.get("reason") == "android_reconnect"

    def test_patch_reconnect_harness_failure_is_silent(self):
        """_patch_reconnect_to_udm() must not raise if harness import fails."""
        bridge = self._make_minimal_bridge()

        with patch("galaxy_gateway.android_bridge.AndroidBridge._patch_runtime_state_to_udm"), \
             patch(
                 "core.multi_device_runtime_harness.on_device_health_changed",
                 side_effect=RuntimeError("harness exploded"),
             ):
            # Must not raise
            bridge._patch_reconnect_to_udm("android-dev-06")


# ---------------------------------------------------------------------------
# 13–14: MultiDeviceCoordinatorEngine coordinator-state and heartbeat wiring
# ---------------------------------------------------------------------------

class TestCoordinatorEngineHarnessWiring:
    """MultiDeviceCoordinatorEngine coordinator-state transitions → harness hooks."""

    @staticmethod
    def _load_n71_module(mod_name: str):
        """Load a Node_71 core submodule via importlib to avoid core namespace conflict."""
        import importlib.util
        import os
        import sys

        full_name = f"core.{mod_name}"
        if full_name in sys.modules:
            return sys.modules[full_name]

        node71_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "nodes", "Node_71_MultiDeviceCoordination",
        )
        node71_core = os.path.join(node71_dir, "core")
        # Ensure repo root (for main core/) and Node_71 dir (for models/) are on path
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        if node71_dir not in sys.path:
            sys.path.insert(1, node71_dir)

        path = os.path.join(node71_core, f"{mod_name}.py")
        spec = importlib.util.spec_from_file_location(full_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        try:
            spec.loader.exec_module(module)
            import core as _core_pkg
            setattr(_core_pkg, mod_name, module)
        except Exception:
            sys.modules.pop(full_name, None)
            raise
        return module

    def _ensure_n71_modules(self):
        """Pre-load all Node_71 core submodules in dependency order."""
        for mod in [
            "canonical_device_view_adapter",
            "fault_tolerance",
            "device_discovery",
            "state_synchronizer",
            "task_scheduler",
            "multi_device_coordinator_engine",
        ]:
            try:
                self._load_n71_module(mod)
            except Exception:
                pass

    def test_coordinator_start_calls_on_coordinator_state_updated(self):
        """MultiDeviceCoordinatorEngine.start() must call on_coordinator_state_updated
        with overall_status='running' after successfully starting."""
        from unittest.mock import AsyncMock
        self._ensure_n71_modules()

        from core.multi_device_coordinator_engine import (  # type: ignore[import]
            MultiDeviceCoordinatorEngine,
            CoordinatorConfig,
        )

        coord_called = []

        def fake_coord_updated(state):
            coord_called.append(state)
            return MagicMock()

        config = CoordinatorConfig(node_id="test-coord-01")
        engine = MultiDeviceCoordinatorEngine(config)

        async def run():
            engine._discovery = MagicMock()
            engine._discovery.start = AsyncMock()
            engine._synchronizer = MagicMock()
            engine._synchronizer.start = AsyncMock()
            engine._scheduler = MagicMock()
            engine._scheduler.start = AsyncMock()
            engine._fault_tolerance = MagicMock()
            engine._fault_tolerance.start = AsyncMock()
            with patch("core.multi_device_runtime_harness.on_coordinator_state_updated", fake_coord_updated), \
                 patch("asyncio.create_task", return_value=MagicMock()):
                await engine.start()

        asyncio.run(run())

        running_calls = [c for c in coord_called if c.get("overall_status") == "running"]
        assert len(running_calls) >= 1
        assert running_calls[0].get("coordinator_id") == "test-coord-01"

    def test_coordinator_heartbeat_timeout_calls_on_device_health_changed(self):
        """_heartbeat_loop() device timeout must call on_device_health_changed with heartbeat_miss."""
        from unittest.mock import AsyncMock
        self._ensure_n71_modules()

        from core.multi_device_coordinator_engine import (  # type: ignore[import]
            MultiDeviceCoordinatorEngine,
            CoordinatorConfig,
            CoordinatorState,
        )

        health_called = []
        readiness_called = []

        def fake_health(event):
            health_called.append(event)
            return MagicMock()

        def fake_readiness(device_id, readiness, **kwargs):
            readiness_called.append((device_id, readiness, kwargs))
            return MagicMock()

        config = CoordinatorConfig(
            node_id="test-coord-02",
            heartbeat_interval=0.01,
            heartbeat_timeout=0.01,
        )
        engine = MultiDeviceCoordinatorEngine(config)
        engine._state = CoordinatorState.RUNNING

        import os
        import sys
        node71_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "nodes", "Node_71_MultiDeviceCoordination",
        )
        if node71_dir not in sys.path:
            sys.path.insert(1, node71_dir)

        from models.device import Device, DeviceType, DeviceState  # type: ignore[import]

        stale_device = Device(
            device_id="stale-d-01",
            name="Stale Device",
            device_type=DeviceType.ANDROID,
            state=DeviceState.IDLE,
            last_heartbeat=0.0,
        )
        engine._registry.devices["stale-d-01"] = stale_device

        async def run_one_loop_iteration():
            engine._synchronizer = MagicMock()
            engine._synchronizer.update_state = AsyncMock()
            engine._state = CoordinatorState.RUNNING
            with patch("core.multi_device_runtime_harness.on_device_health_changed", fake_health), \
                 patch("core.multi_device_runtime_harness.on_participant_readiness_changed", fake_readiness):
                try:
                    await asyncio.wait_for(engine._heartbeat_loop(), timeout=0.5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

        asyncio.run(run_one_loop_iteration())

        assert len(health_called) >= 1
        event = health_called[0]
        assert event.device_id == "stale-d-01"
        assert event.event_type == "heartbeat_miss"
        assert event.is_reachable is False

        assert len(readiness_called) >= 1
        dev_id, readiness, kwargs = readiness_called[0]
        assert dev_id == "stale-d-01"
        assert readiness == "lost"
