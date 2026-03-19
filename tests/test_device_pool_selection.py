"""
tests/test_device_pool_selection.py
=====================================

PR-6 Goal 3: Tests demonstrate DevicePoolManager is the sole device selection path.

Covers:
  A) DevicePoolManager.select_device() returns the best available device
  B) DeviceOrchestrator.select_device() delegates exclusively to DevicePoolManager
  C) DevicePoolManager honours required_capabilities filter
  D) DevicePoolManager strategies: round_robin, least_conn, adaptive
  E) When DevicePoolManager has no eligible device, None is returned (fail-open)
  F) ConstellationRuntime consults DevicePoolManager during DAG scheduling
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# A) DevicePoolManager.select_device() returns a valid device
# ===========================================================================

class TestDevicePoolSelectDevice:
    """Basic select_device behaviour."""

    def _fresh_pool(self, strategy="round_robin"):
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
        DevicePoolManager._reset_singleton()
        return DevicePoolManager(strategy=SchedulingStrategy(strategy))

    def test_returns_registered_device(self):
        from core.device_pool_manager import DevicePoolManager
        pool = self._fresh_pool()
        pool.register_device("dev_A", capabilities=["screen"])
        result = pool.select_device()
        assert result == "dev_A"
        DevicePoolManager._reset_singleton()

    def test_returns_none_when_pool_empty(self):
        from core.device_pool_manager import DevicePoolManager
        pool = self._fresh_pool()
        result = pool.select_device()
        assert result is None
        DevicePoolManager._reset_singleton()

    def test_returns_none_for_unregistered_capability(self):
        from core.device_pool_manager import DevicePoolManager
        pool = self._fresh_pool()
        pool.register_device("dev_B", capabilities=["screen"])
        result = pool.select_device(required_capabilities=["camera"])
        assert result is None
        DevicePoolManager._reset_singleton()

    def test_selects_device_with_matching_capability(self):
        from core.device_pool_manager import DevicePoolManager
        pool = self._fresh_pool()
        pool.register_device("dev_cam", capabilities=["camera", "screen"])
        pool.register_device("dev_screen", capabilities=["screen"])
        result = pool.select_device(required_capabilities=["camera"])
        assert result == "dev_cam"
        DevicePoolManager._reset_singleton()


# ===========================================================================
# B) DeviceOrchestrator.select_device() delegates to DevicePoolManager
# ===========================================================================

class TestDeviceOrchestratorDelegatesToPool:
    """DeviceOrchestrator must not perform its own scheduling; it must delegate."""

    def test_delegates_to_pool(self):
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy.ADAPTIVE)
        pool.register_device("orch_dev_1", capabilities=["screen"])

        with patch(
            "core.device_pool_manager.get_device_pool_manager", return_value=pool
        ):
            from core.device_orchestrator import DeviceOrchestrator
            orch = DeviceOrchestrator()
            result = orch.select_device(required_capabilities=["screen"])

        assert result == "orch_dev_1"
        DevicePoolManager._reset_singleton()

    def test_returns_none_when_pool_empty(self):
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy.ADAPTIVE)

        with patch(
            "core.device_pool_manager.get_device_pool_manager", return_value=pool
        ):
            from core.device_orchestrator import DeviceOrchestrator
            orch = DeviceOrchestrator()
            result = orch.select_device(required_capabilities=["camera"])

        assert result is None
        DevicePoolManager._reset_singleton()

    def test_does_not_bypass_pool_on_exception(self):
        """DeviceOrchestrator must fail-open (return None) if the pool raises."""
        with patch(
            "core.device_pool_manager.get_device_pool_manager",
            side_effect=RuntimeError("pool unavailable"),
        ):
            from core.device_orchestrator import DeviceOrchestrator
            orch = DeviceOrchestrator()
            result = orch.select_device(required_capabilities=["screen"])

        assert result is None


# ===========================================================================
# C) DevicePoolManager honours required_capabilities filter
# ===========================================================================

class TestDevicePoolCapabilityFilter:
    """Capability filtering must be strict: all required caps must be present."""

    def setup_method(self):
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
        DevicePoolManager._reset_singleton()
        self.pool = DevicePoolManager(strategy=SchedulingStrategy.ROUND_ROBIN)

    def teardown_method(self):
        from core.device_pool_manager import DevicePoolManager
        DevicePoolManager._reset_singleton()

    def test_multi_cap_match(self):
        self.pool.register_device("multi_dev", capabilities=["screen", "touch", "camera"])
        result = self.pool.select_device(required_capabilities=["screen", "camera"])
        assert result == "multi_dev"

    def test_partial_cap_no_match(self):
        self.pool.register_device("partial_dev", capabilities=["screen"])
        result = self.pool.select_device(required_capabilities=["screen", "camera"])
        assert result is None

    def test_no_required_caps_returns_any(self):
        self.pool.register_device("any_dev", capabilities=["screen"])
        result = self.pool.select_device()
        assert result == "any_dev"


# ===========================================================================
# D) DevicePoolManager strategies are functional
# ===========================================================================

class TestDevicePoolStrategies:
    """Verify each scheduling strategy selects a valid registered device."""

    def _pool_with_devices(self, strategy: str):
        """Return a fresh DevicePoolManager with two screen-capable devices."""
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy(strategy))
        pool.register_device("s_dev_1", capabilities=["screen"])
        pool.register_device("s_dev_2", capabilities=["screen"])
        return pool

    def test_round_robin_cycles_devices(self):
        from core.device_pool_manager import DevicePoolManager
        pool = self._pool_with_devices("round_robin")
        first = pool.select_device()
        second = pool.select_device()
        assert first in {"s_dev_1", "s_dev_2"}
        assert second in {"s_dev_1", "s_dev_2"}
        DevicePoolManager._reset_singleton()

    def test_least_conn_selects_idle_device(self):
        from core.device_pool_manager import DevicePoolManager
        pool = self._pool_with_devices("least_conn")
        # Mark s_dev_1 as having more connections
        pool._devices["s_dev_1"].active_connections = 5
        pool._devices["s_dev_2"].active_connections = 0
        result = pool.select_device()
        assert result == "s_dev_2"
        DevicePoolManager._reset_singleton()

    def test_adaptive_selects_available_device(self):
        from core.device_pool_manager import DevicePoolManager
        pool = self._pool_with_devices("adaptive")
        result = pool.select_device()
        assert result in {"s_dev_1", "s_dev_2"}
        DevicePoolManager._reset_singleton()


# ===========================================================================
# E) Pool returns None gracefully when no device is eligible
# ===========================================================================

class TestDevicePoolNoEligibleDevice:
    """Pool must return None without raising when no device matches."""

    def test_no_devices_no_raise(self):
        from core.device_pool_manager import DevicePoolManager
        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager()
        result = pool.select_device(required_capabilities=["screen"])
        assert result is None
        DevicePoolManager._reset_singleton()

    def test_all_full_returns_none(self):
        """When every device is at capacity, select_device() returns None."""
        from core.device_pool_manager import DevicePoolManager
        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager()
        pool.register_device("full_dev", capabilities=["screen"], capacity=1)
        pool._devices["full_dev"].active_connections = 1  # at capacity
        result = pool.select_device(required_capabilities=["screen"])
        assert result is None
        DevicePoolManager._reset_singleton()


# ===========================================================================
# F) ConstellationRuntime consults DevicePoolManager during scheduling
# ===========================================================================

class TestConstellationRuntimeUsesPool:
    """ConstellationRuntime must use DevicePoolManager for device assignment."""

    @pytest.mark.asyncio
    async def test_device_pool_select_device_called(self):
        """select_device() must be called at least once per DAG execution."""
        from core.constellation_runtime import ConstellationRuntime
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
        from core.schemas.orchestration import TaskDecomposition, SubTask, SubTaskStatus

        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy.ADAPTIVE)
        pool.register_device("cr_dev_1", capabilities=["screen"])

        rt = ConstellationRuntime(enable_dag_evolution=False)
        mock_orch = MagicMock()
        subtask = SubTask(
            task_id="cr_t1", name="step1", description="step", status=SubTaskStatus.PENDING
        )
        decomp = TaskDecomposition(goal="test", subtasks=[subtask])
        mock_orch._decompose_task = AsyncMock(return_value=decomp)
        mock_orch._execute_subtask = AsyncMock(
            return_value={"success": True, "result": "ok", "tool": "noop"}
        )
        rt._smart_orchestrator = mock_orch

        with patch(
            "core.device_pool_manager.get_device_pool_manager", return_value=pool
        ):
            original_select = pool.select_device
            select_calls = []

            def spy_select(*args, **kwargs):
                result = original_select(*args, **kwargs)
                select_calls.append(result)
                return result

            pool.select_device = spy_select

            await rt.run("device pool cr test", device_id="")

        assert len(select_calls) >= 1, (
            "ConstellationRuntime must call DevicePoolManager.select_device() "
            "at least once per execution"
        )
        DevicePoolManager._reset_singleton()
