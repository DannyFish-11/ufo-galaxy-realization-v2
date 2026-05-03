from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_route_task_uses_explicit_target_devices_without_local_selection() -> None:
    from galaxy_gateway.device_router import Device, DeviceRouter

    router = DeviceRouter()
    router.devices.clear()
    router.task_queue.clear()

    device = Device("desktop_1", "windows", ["screen"])
    router.devices["desktop_1"] = device

    def _unexpected_select(analysis):
        raise AssertionError("_select_devices should not run")

    router._select_devices = _unexpected_select  # type: ignore[method-assign]
    router._analyze_command = AsyncMock(
        side_effect=AssertionError("_analyze_command should not run")
    )
    router.dispatch_task = AsyncMock(
        return_value={"success": True, "task_id": "t1"}
    )  # type: ignore[method-assign]

    result = await router.route_task(
        "open settings",
        {
            "_command_router_pre_analyzed": True,
            "_pre_analysis": {
                "task_type": "system_control",
                "exec_mode": "windows",
                "target_device_type": "windows",
                "actions": ["open"],
            },
            "target_device_ids": ["desktop_1"],
            "device_id": "desktop_1",
        },
    )

    assert result["success"] is True
    router.dispatch_task.assert_awaited_once()
