"""tests/test_pr_device_router_single_dispatch.py
===================================================
PR-S3: Make DeviceRouter the single dispatch and cross-device orchestration
entry.

Coverage
--------
1.  CANONICAL_DISPATCH_AUTHORITY sentinel exists and points to DeviceRouter.
2.  DeviceRouter class docstring references PR-S3 / single dispatch authority.
3.  android_bridge.AndroidBridge.assign_task delegates to DeviceRouter when
    the device is registered in the router.
4.  android_bridge.AndroidBridge.assign_task falls back to send_to_device
    when the device is NOT in the router (compatibility mode).
5.  GUI action adapters (click, swipe, input_text, screenshot, query_elements)
    remain in AndroidBridge but are documented as translation adapters.
6.  repo_coordinator.RepoCoordinator.dispatch_agent_to_android delegates to
    DeviceRouter.route_task() as primary path.
7.  repo_coordinator.dispatch_agent_to_android falls back gracefully when
    DeviceRouter raises an exception.
8.  cross_device_coordinator.CrossDeviceCoordinator class docstring documents
    it as a DeviceRouter-internal coordinator (not public entry).
9.  execute_cross_device_task docstring says "Called by DeviceRouter only."
10. legacy_paths registry: DeviceRouter.route_task has ACTIVE status.
11. legacy_paths registry: AndroidBridge.assign_task has LEGACY_COMPATIBILITY
    status with PR-S3 guardrail.
12. legacy_paths registry: RepoCoordinator.dispatch_agent_to_android has
    LEGACY_COMPATIBILITY status with PR-S3 guardrail.
13. DeviceRouter.route_task is importable and callable.
14. DeviceRouter.dispatch_task is importable and callable.
15. assign_task: task_id is tracked in local state before delegate attempt.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. CANONICAL_DISPATCH_AUTHORITY sentinel
# ---------------------------------------------------------------------------


class TestCanonicalDispatchAuthoritySentinel:
    """CANONICAL_DISPATCH_AUTHORITY exists and points to DeviceRouter."""

    def test_sentinel_importable(self):
        from galaxy_gateway.device_router import CANONICAL_DISPATCH_AUTHORITY
        assert CANONICAL_DISPATCH_AUTHORITY is not None

    def test_sentinel_value(self):
        from galaxy_gateway.device_router import CANONICAL_DISPATCH_AUTHORITY
        assert CANONICAL_DISPATCH_AUTHORITY == "galaxy_gateway.device_router.DeviceRouter"

    def test_sentinel_is_string(self):
        from galaxy_gateway.device_router import CANONICAL_DISPATCH_AUTHORITY
        assert isinstance(CANONICAL_DISPATCH_AUTHORITY, str)


# ---------------------------------------------------------------------------
# 2. DeviceRouter class docstring references PR-S3
# ---------------------------------------------------------------------------


class TestDeviceRouterDocstring:
    """DeviceRouter docstring references the PR-S3 consolidation."""

    def test_docstring_references_prs3(self):
        from galaxy_gateway.device_router import DeviceRouter
        doc = DeviceRouter.__doc__ or ""
        assert "PR-S3" in doc, "DeviceRouter docstring must reference PR-S3"

    def test_docstring_references_single_dispatch(self):
        from galaxy_gateway.device_router import DeviceRouter
        doc = DeviceRouter.__doc__ or ""
        assert "single" in doc.lower() and "dispatch" in doc.lower(), (
            "DeviceRouter docstring must describe single dispatch authority"
        )

    def test_docstring_references_android_bridge(self):
        from galaxy_gateway.device_router import DeviceRouter
        doc = DeviceRouter.__doc__ or ""
        assert "AndroidBridge" in doc, (
            "DeviceRouter docstring should name AndroidBridge as a delegator"
        )

    def test_docstring_references_repo_coordinator(self):
        from galaxy_gateway.device_router import DeviceRouter
        doc = DeviceRouter.__doc__ or ""
        assert "RepoCoordinator" in doc, (
            "DeviceRouter docstring should name RepoCoordinator as a delegator"
        )


# ---------------------------------------------------------------------------
# 3. AndroidBridge.assign_task delegates to DeviceRouter when device is in router
# ---------------------------------------------------------------------------


class TestAndroidBridgeAssignTaskDelegatesToRouter:
    """assign_task delegates to DeviceRouter.dispatch_task when device is registered."""

    @pytest.mark.asyncio
    async def test_assign_task_calls_device_router_dispatch(self):
        """When device is in DeviceRouter, assign_task should call dispatch_task."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.device_router import Device

        # Build a mock router with the device registered
        mock_router_device = MagicMock(spec=Device)
        mock_router_device.device_id = "android_001"
        mock_router = MagicMock()
        mock_router.devices = {"android_001": mock_router_device}
        expected_result = {"success": True, "task_id": "t1"}
        mock_router.dispatch_task = AsyncMock(return_value=expected_result)

        bridge = AndroidBridge()
        # Patch the module-level singleton in galaxy_gateway.device_router so the
        # lazy import inside assign_task picks up the mock.
        with patch("galaxy_gateway.device_router.device_router", mock_router):
            result = await bridge.assign_task(
                "android_001", "task_001", "screenshot", {}, priority=5, timeout=30
            )

        mock_router.dispatch_task.assert_called_once()
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_assign_task_delegates_with_correct_task_id(self):
        """assign_task passes task_id into the task dict sent to DeviceRouter."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.device_router import Device

        mock_device = MagicMock(spec=Device)
        mock_device.device_id = "android_002"
        mock_router = MagicMock()
        mock_router.devices = {"android_002": mock_device}
        dispatched_tasks = []

        async def _capture_dispatch(task_dict, device):
            dispatched_tasks.append(task_dict)
            return {"success": True}

        mock_router.dispatch_task = _capture_dispatch

        bridge = AndroidBridge()
        with patch("galaxy_gateway.device_router.device_router", mock_router):
            await bridge.assign_task(
                "android_002", "my_task_id", "some_type", {"key": "val"}
            )

        assert len(dispatched_tasks) == 1
        assert dispatched_tasks[0]["task_id"] == "my_task_id"


# ---------------------------------------------------------------------------
# 4. AndroidBridge.assign_task fallback when device NOT in router
# ---------------------------------------------------------------------------


class TestAndroidBridgeAssignTaskFallback:
    """assign_task falls back to send_to_device when device not in router."""

    @pytest.mark.asyncio
    async def test_assign_task_falls_back_to_send_to_device(self):
        """When device is absent from DeviceRouter, falls back to send_to_device."""
        from galaxy_gateway.android_bridge import AndroidBridge, AndroidDevice

        mock_router = MagicMock()
        mock_router.devices = {}  # device NOT in router

        bridge = AndroidBridge()
        # Insert a fake AndroidDevice with websocket into bridge._devices
        fake_device = MagicMock(spec=AndroidDevice)
        fake_device.connected = True
        fake_ws = MagicMock()
        fake_ws.send_json = AsyncMock()
        fake_device.websocket = fake_ws
        bridge._devices["android_fallback"] = fake_device

        sent_messages = []

        async def _fake_send(device_id, message, wait_response=False, timeout=30.0):
            sent_messages.append((device_id, message))
            return {"success": True}

        bridge.send_to_device = _fake_send  # type: ignore[method-assign]

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            result = await bridge.assign_task(
                "android_fallback", "task_fb", "generic", {}
            )

        # Should have fallen back to send_to_device
        assert len(sent_messages) == 1
        assert sent_messages[0][0] == "android_fallback"
        assert result == {"success": True}


# ---------------------------------------------------------------------------
# 5. GUI action adapters are translation adapters (not independent dispatch)
# ---------------------------------------------------------------------------


class TestAndroidBridgeGUIAdapters:
    """GUI action methods are documented as translation adapters (PR-S3)."""

    def test_click_docstring_mentions_adapter(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        doc = AndroidBridge.click.__doc__ or ""
        assert "adapter" in doc.lower(), "click() must document itself as adapter"

    def test_swipe_docstring_mentions_adapter(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        doc = AndroidBridge.swipe.__doc__ or ""
        assert "adapter" in doc.lower()

    def test_input_text_docstring_mentions_adapter(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        doc = AndroidBridge.input_text.__doc__ or ""
        assert "adapter" in doc.lower()

    def test_screenshot_docstring_mentions_adapter(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        doc = AndroidBridge.screenshot.__doc__ or ""
        assert "adapter" in doc.lower()

    def test_query_elements_docstring_mentions_adapter(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        doc = AndroidBridge.query_elements.__doc__ or ""
        assert "adapter" in doc.lower()

    def test_gui_action_adapters_reference_prs3(self):
        """At least click and swipe reference PR-S3."""
        from galaxy_gateway.android_bridge import AndroidBridge
        for method_name in ("click", "swipe"):
            doc = getattr(AndroidBridge, method_name).__doc__ or ""
            assert "PR-S3" in doc, f"{method_name}() docstring must reference PR-S3"


# ---------------------------------------------------------------------------
# 6. RepoCoordinator.dispatch_agent_to_android delegates to DeviceRouter
# ---------------------------------------------------------------------------


class TestRepoCoordinatorDelegatesToRouter:
    """dispatch_agent_to_android delegates to DeviceRouter.route_task."""

    @pytest.mark.asyncio
    async def test_dispatch_agent_calls_route_task(self):
        """When DeviceRouter is available, dispatch_agent_to_android uses route_task."""
        from core.repo_coordinator import RepoCoordinator

        coordinator = RepoCoordinator()
        # Register the device in the local table
        coordinator.android_devices["dev_rc_01"] = {
            "device_id": "dev_rc_01",
            "device_type": "android",
            "status": "online",
            "websocket_url": "ws://localhost/test",
            "endpoint": "",
        }

        route_task_calls = []

        async def _fake_route_task(command, context=None):
            route_task_calls.append((command, context))
            return {"success": True, "routed_via": "device_router"}

        mock_router = MagicMock()
        mock_router.route_task = _fake_route_task

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            result = await coordinator.dispatch_agent_to_android(
                "dev_rc_01", "screenshot", {"quality": 80}
            )

        assert len(route_task_calls) == 1
        assert route_task_calls[0][1]["device_id"] == "dev_rc_01"
        assert result["routed_via"] == "device_router"

    @pytest.mark.asyncio
    async def test_dispatch_agent_passes_device_id_in_context(self):
        """dispatch_agent_to_android passes device_id in route_task context."""
        from core.repo_coordinator import RepoCoordinator

        coordinator = RepoCoordinator()
        coordinator.android_devices["dev_rc_02"] = {
            "device_id": "dev_rc_02",
            "device_type": "android",
            "status": "online",
            "websocket_url": "",
            "endpoint": "",
        }

        captured_context = {}

        async def _capture_context(command, context=None):
            captured_context.update(context or {})
            return {"success": True}

        mock_router = MagicMock()
        mock_router.route_task = _capture_context

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            await coordinator.dispatch_agent_to_android(
                "dev_rc_02", "take_screenshot", {"resolution": "1080p"}
            )

        assert captured_context.get("device_id") == "dev_rc_02"
        assert captured_context.get("source") == "repo_coordinator"

    @pytest.mark.asyncio
    async def test_dispatch_agent_returns_not_found_for_unregistered_device(self):
        """Returns error dict when device not registered in coordinator."""
        from core.repo_coordinator import RepoCoordinator

        coordinator = RepoCoordinator()
        result = await coordinator.dispatch_agent_to_android(
            "nonexistent_device", "screenshot", {}
        )
        assert result["success"] is False
        assert "not found" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# 7. RepoCoordinator fallback when DeviceRouter raises
# ---------------------------------------------------------------------------


class TestRepoCoordinatorFallback:
    """dispatch_agent_to_android falls back gracefully when router raises."""

    @pytest.mark.asyncio
    async def test_fallback_on_router_exception(self):
        """When DeviceRouter raises, falls back to direct send path."""
        from core.repo_coordinator import RepoCoordinator

        coordinator = RepoCoordinator()
        coordinator.android_devices["dev_rc_fb"] = {
            "device_id": "dev_rc_fb",
            "device_type": "android",
            "status": "online",
            "websocket_url": "",
            "endpoint": "http://localhost/api",
        }

        async def _raise_route_task(command, context=None):
            raise RuntimeError("router unavailable")

        mock_router = MagicMock()
        mock_router.route_task = _raise_route_task

        # Patch _send_via_http to return success
        async def _fake_http(endpoint, message):
            return {"success": True, "via": "http_fallback"}

        coordinator._send_via_http = _fake_http  # type: ignore[method-assign]

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            result = await coordinator.dispatch_agent_to_android(
                "dev_rc_fb", "generic", {}
            )

        # Should have fallen through to HTTP fallback
        assert result.get("via") == "http_fallback"


# ---------------------------------------------------------------------------
# 8. CrossDeviceCoordinator class docstring — DeviceRouter-internal
# ---------------------------------------------------------------------------


class TestCrossDeviceCoordinatorDocstring:
    """CrossDeviceCoordinator docstring declares it DeviceRouter-internal."""

    def test_class_docstring_references_prs3(self):
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        doc = CrossDeviceCoordinator.__doc__ or ""
        assert "PR-S3" in doc

    def test_class_docstring_says_internal(self):
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        doc = CrossDeviceCoordinator.__doc__ or ""
        assert "internal" in doc.lower()

    def test_class_docstring_references_device_router(self):
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        doc = CrossDeviceCoordinator.__doc__ or ""
        assert "DeviceRouter" in doc


# ---------------------------------------------------------------------------
# 9. execute_cross_device_task docstring — "Called by DeviceRouter only"
# ---------------------------------------------------------------------------


class TestExecuteCrossDeviceTaskDocstring:
    """execute_cross_device_task is documented as called by DeviceRouter only."""

    def test_method_docstring_says_called_by_device_router(self):
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        doc = CrossDeviceCoordinator.execute_cross_device_task.__doc__ or ""
        assert "DeviceRouter" in doc

    def test_method_docstring_discourages_direct_call(self):
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        doc = CrossDeviceCoordinator.execute_cross_device_task.__doc__ or ""
        assert "only" in doc.lower() or "external" in doc.lower()


# ---------------------------------------------------------------------------
# 10–12. legacy_paths registry entries
# ---------------------------------------------------------------------------


class TestLegacyPathsRegistry:
    """Legacy paths registry is updated per PR-S3."""

    def test_device_router_route_task_is_active(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get(
            "galaxy_gateway.device_router.DeviceRouter.route_task"
        )
        assert entry is not None, "DeviceRouter.route_task must be in registry"
        assert entry.status == LegacyPathStatus.ACTIVE, (
            f"Expected ACTIVE, got {entry.status}"
        )

    def test_device_router_route_task_pr_guardrail_updated(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY.get(
            "galaxy_gateway.device_router.DeviceRouter.route_task"
        )
        assert entry is not None
        assert "PR-S3" in (entry.pr_guardrail_added or "") or "PR-S3" in (entry.notes or ""), (
            "DeviceRouter.route_task entry must reference PR-S3"
        )

    def test_android_bridge_assign_task_is_legacy_compatibility(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get(
            "galaxy_gateway.android_bridge.AndroidBridge.assign_task"
        )
        assert entry is not None, "AndroidBridge.assign_task must be in registry"
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_android_bridge_assign_task_guardrail_is_prs3(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY.get(
            "galaxy_gateway.android_bridge.AndroidBridge.assign_task"
        )
        assert entry is not None
        assert entry.pr_guardrail_added == "PR-S3"

    def test_repo_coordinator_dispatch_is_legacy_compatibility(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get(
            "core.repo_coordinator.RepoCoordinator.dispatch_agent_to_android"
        )
        assert entry is not None, (
            "RepoCoordinator.dispatch_agent_to_android must be in registry"
        )
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_repo_coordinator_dispatch_guardrail_is_prs3(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY.get(
            "core.repo_coordinator.RepoCoordinator.dispatch_agent_to_android"
        )
        assert entry is not None
        assert entry.pr_guardrail_added == "PR-S3"

    def test_cross_device_coordinator_still_legacy_compatibility(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get(
            "galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator"
        )
        assert entry is not None
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY


# ---------------------------------------------------------------------------
# 13–14. DeviceRouter methods are importable and callable
# ---------------------------------------------------------------------------


class TestDeviceRouterMethodsImportable:
    """DeviceRouter.route_task and dispatch_task are importable and callable."""

    def test_route_task_is_coroutine_function(self):
        from galaxy_gateway.device_router import DeviceRouter
        assert asyncio.iscoroutinefunction(DeviceRouter.route_task)

    def test_dispatch_task_is_coroutine_function(self):
        from galaxy_gateway.device_router import DeviceRouter
        assert asyncio.iscoroutinefunction(DeviceRouter.dispatch_task)

    def test_device_router_singleton_importable(self):
        from galaxy_gateway.device_router import device_router, DeviceRouter
        assert isinstance(device_router, DeviceRouter)


# ---------------------------------------------------------------------------
# 15. assign_task tracks task_id in local state before delegation
# ---------------------------------------------------------------------------


class TestAndroidBridgeAssignTaskLocalState:
    """assign_task updates local device state before attempting dispatch."""

    @pytest.mark.asyncio
    async def test_current_task_id_set_in_local_state(self):
        """local device state is updated regardless of dispatch outcome."""
        from galaxy_gateway.android_bridge import AndroidBridge, AndroidDevice

        bridge = AndroidBridge()
        # Register a fake device in the bridge (simulating connected Android)
        fake_device = MagicMock(spec=AndroidDevice)
        fake_device.connected = True
        fake_device.current_task_id = None
        bridge._devices["state_test_device"] = fake_device

        # Router has no device — forces fallback
        mock_router = MagicMock()
        mock_router.devices = {}

        async def _fake_send(device_id, msg, wait_response=False, timeout=30.0):
            return {"success": True}

        bridge.send_to_device = _fake_send  # type: ignore[method-assign]

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            await bridge.assign_task(
                "state_test_device", "local_state_task_id", "some_type", {}
            )

        # current_task_id must have been set in the bridge's local device cache
        assert bridge._devices["state_test_device"].current_task_id == "local_state_task_id"
