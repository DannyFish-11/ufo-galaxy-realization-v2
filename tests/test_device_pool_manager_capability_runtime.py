from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def test_select_device_prefers_canonical_runtime_candidates() -> None:
    from core.device_pool_manager import DevicePoolManager, SchedulingStrategy

    DevicePoolManager._reset_singleton()
    pool = DevicePoolManager(strategy=SchedulingStrategy.LEAST_CONN)
    pool.reset()
    pool.register_device("device_allowed", capabilities=["vlm"], device_type="android")
    pool.register_device("device_blocked", capabilities=["vlm"], device_type="android")

    canonical = [SimpleNamespace(node_id="device_allowed")]
    with patch(
        "core.capability_network_runtime_policy.query_routable_executors",
        return_value=canonical,
    ):
        selected = pool.select_device(required_capabilities=["vlm"])

    assert selected == "device_allowed"


def test_select_device_returns_none_when_canonical_runtime_has_no_matching_executor() -> None:
    from core.device_pool_manager import DevicePoolManager, SchedulingStrategy

    DevicePoolManager._reset_singleton()
    pool = DevicePoolManager(strategy=SchedulingStrategy.LEAST_CONN)
    pool.reset()
    pool.register_device("device_only_local", capabilities=["vlm"], device_type="android")

    with patch(
        "core.capability_network_runtime_policy.query_routable_executors",
        return_value=[],
    ):
        selected = pool.select_device(required_capabilities=["vlm"])

    assert selected is None
