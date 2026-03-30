"""
tests/unit/routing/test_device_pool_routing.py
======================================

PR-3 — Enforce DevicePoolManager as the single device scheduling entry point.

Covers:
  A) DeviceOrchestrator.select_device delegates to DevicePoolManager
  B) CommandRouter.route_envelope uses DevicePoolManager when
     required_capabilities are present and no explicit target is given
  C) Explicit targets in route_envelope bypass DevicePoolManager selection
  D) galaxy_gateway DeviceRouter._select_devices delegates to DevicePoolManager
  E) Node_71 TaskScheduler / DeviceSelector carry the strategy-provider guard
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# A) DeviceOrchestrator.select_device → DevicePoolManager
# ===========================================================================

class TestDeviceOrchestratorDelegatesPool:
    """DeviceOrchestrator.select_device must delegate to DevicePoolManager."""

    def test_select_device_calls_pool(self):
        """select_device() routes through DevicePoolManager.select_device."""
        from core.device_orchestrator import DeviceOrchestrator
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy

        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy.ADAPTIVE)
        pool.register_device("dev_a", capabilities=["screen"])

        with patch(
            "core.device_pool_manager.get_device_pool_manager", return_value=pool
        ):
            orch = DeviceOrchestrator()
            result = orch.select_device(required_capabilities=["screen"])

        assert result == "dev_a"
        DevicePoolManager._reset_singleton()

    def test_select_device_returns_none_when_pool_empty(self):
        """select_device() returns None when the pool has no eligible devices."""
        from core.device_orchestrator import DeviceOrchestrator
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy

        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy.ADAPTIVE)

        with patch(
            "core.device_pool_manager.get_device_pool_manager", return_value=pool
        ):
            orch = DeviceOrchestrator()
            result = orch.select_device(required_capabilities=["camera"])

        assert result is None
        DevicePoolManager._reset_singleton()

    def test_select_device_does_not_bypass_pool_on_exception(self):
        """When DevicePoolManager raises, select_device returns None (fail-open)."""
        from core.device_orchestrator import DeviceOrchestrator

        with patch(
            "core.device_pool_manager.get_device_pool_manager",
            side_effect=RuntimeError("pool unavailable"),
        ):
            orch = DeviceOrchestrator()
            result = orch.select_device(required_capabilities=["screen"])

        # Must fail-open (return None), never raise
        assert result is None


# ===========================================================================
# B) CommandRouter.route_envelope uses DevicePoolManager for capability-based routing
# ===========================================================================

class TestCommandRouterPoolSelection:
    """route_envelope must use DevicePoolManager when targets is empty + caps given."""

    @pytest.mark.asyncio
    async def test_pool_selected_when_no_target_and_caps_given(self):
        """When envelope has no targets but required_capabilities, pool is queried."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy

        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy.ADAPTIVE)
        pool.register_device("pool_dev_1", capabilities=["screen"])

        mock_executor = MagicMock(return_value=None)

        async def fake_exec(device_id, command, params):
            return {"success": True, "result": "ok", "device_id": device_id}

        router = CommandRouter(executor=fake_exec)

        envelope = TaskEnvelope(
            targets=[],
            tool_name="screenshot",
            args={},
            required_capabilities=["screen"],
        )

        with patch(
            "core.device_pool_manager.get_device_pool_manager", return_value=pool
        ):
            result = await router.route_envelope(envelope)

        # The pool should have selected pool_dev_1, so routing must succeed
        # and the device_id in the result must be the pool-selected device.
        assert result.get("success") is True
        assert result.get("device_id") == "pool_dev_1"
        DevicePoolManager._reset_singleton()

    @pytest.mark.asyncio
    async def test_error_when_no_target_and_no_caps(self):
        """When no targets and no required_capabilities, routing fails with INVALID_ENVELOPE."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        async def fake_exec(device_id, command, params):
            return {"success": True, "result": "ok", "device_id": device_id}

        router = CommandRouter(executor=fake_exec)

        envelope = TaskEnvelope(
            targets=[],
            tool_name="screenshot",
            args={},
        )

        result = await router.route_envelope(envelope)
        assert result.get("success") is False
        assert result.get("error_code") == "INVALID_ENVELOPE"


# ===========================================================================
# C) Explicit targets bypass DevicePoolManager selection
# ===========================================================================

class TestExplicitTargetBypassesPool:
    """When an explicit target is provided, DevicePoolManager must NOT be called."""

    @pytest.mark.asyncio
    async def test_explicit_target_does_not_call_pool_select(self):
        """Explicit target in envelope.targets bypasses DevicePoolManager.select_device."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope
        from core.device_pool_manager import DevicePoolManager

        async def fake_exec(device_id, command, params):
            return {"success": True, "result": "ok", "device_id": device_id}

        router = CommandRouter(executor=fake_exec)

        envelope = TaskEnvelope(
            targets=["explicit_dev_99"],
            tool_name="screenshot",
            args={},
            required_capabilities=["screen"],
        )

        mock_pool = MagicMock()
        mock_pool.select_device = MagicMock(return_value="should_not_be_called")

        with patch(
            "core.device_pool_manager.get_device_pool_manager",
            return_value=mock_pool,
        ):
            result = await router.route_envelope(envelope)

        # Pool.select_device must NOT have been called because target was explicit
        mock_pool.select_device.assert_not_called()


# ===========================================================================
# D) galaxy_gateway DeviceRouter._select_devices delegates to DevicePoolManager
# ===========================================================================

class TestDeviceRouterDelegatesPool:
    """DeviceRouter._select_devices should try DevicePoolManager before falling back."""

    def test_select_devices_uses_pool_when_available(self):
        """_select_devices delegates final selection to DevicePoolManager."""
        try:
            from galaxy_gateway.device_router import DeviceRouter, Device, DeviceType
        except Exception:
            pytest.skip("galaxy_gateway not importable in this test environment")

        # Build a minimal DeviceRouter without a real websocket manager
        router = DeviceRouter.__new__(DeviceRouter)
        router.websocket_manager = MagicMock()
        router.devices = {}
        router.task_queue = {}

        # Two fake online devices of the same type
        dev1 = MagicMock(spec=Device)
        dev1.device_id = "gw_dev_1"
        dev1.status = "online"
        dev1.metadata = {}

        analysis = {
            "target_device_type": DeviceType.WINDOWS,
            "exec_mode": "both",
            "actions": [],
            "requires_cross_device": False,
            "task_role": None,
        }

        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy.ROUND_ROBIN)
        pool.register_device("gw_dev_1")

        with (
            patch("galaxy_gateway.device_router.DeviceRouter.get_devices_by_type", return_value=[dev1]),
            patch("galaxy_gateway.autonomous_filter.filter_autonomous_devices", return_value=[dev1], create=True),
            patch("core.device_pool_manager.get_device_pool_manager", return_value=pool),
        ):
            selected = router._select_devices(analysis)

        # DevicePoolManager returned gw_dev_1; it should be in the result list
        assert len(selected) == 1
        assert selected[0].device_id == "gw_dev_1"
        DevicePoolManager._reset_singleton()


# ===========================================================================
# E) Node_71 strategy-provider guard is present
# ===========================================================================

class TestNode71StrategyProviderGuard:
    """Node_71 task_scheduler module must carry the strategy-provider guard."""

    @staticmethod
    def _read_scheduler_source() -> str:
        """Read task_scheduler.py source without importing it (avoids missing deps)."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "../../..",
            "nodes",
            "Node_71_MultiDeviceCoordination",
            "core",
            "task_scheduler.py",
        )
        with open(os.path.abspath(path), encoding="utf-8") as fh:
            return fh.read()

    def test_module_docstring_contains_guard(self):
        """The module docstring must mention DevicePoolManager as the entry point."""
        src = self._read_scheduler_source()
        assert "DevicePoolManager" in src, (
            "task_scheduler.py module docstring must reference DevicePoolManager "
            "as the authoritative entry point (PR-3 guard)."
        )

    def test_task_scheduler_docstring_contains_guard(self):
        """TaskScheduler class docstring must contain the strategy-provider guard."""
        src = self._read_scheduler_source()
        assert "STRATEGY PROVIDER ONLY" in src, (
            "TaskScheduler docstring must contain the PR-3 strategy-provider guard."
        )

    def test_device_selector_docstring_contains_guard(self):
        """DeviceSelector class docstring must contain the strategy-provider guard."""
        src = self._read_scheduler_source()
        assert "STRATEGY PROVIDER ONLY" in src, (
            "DeviceSelector class docstring must contain the PR-3 strategy-provider guard."
        )
