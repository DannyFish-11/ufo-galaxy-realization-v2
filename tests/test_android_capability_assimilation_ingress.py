from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _make_registration_message(device_id: str = "cap_dev_01", **overrides):
    from galaxy_gateway.android.capabilities import DeviceCapability

    msg = {
        "version": "3.0",
        "type": "device_register",
        "message_id": "msg-cap-001",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "name": "Cap Phone",
        "model": "Pixel 7",
        "platform": "android",
        "device_type": "android_phone",
        "capabilities": DeviceCapability.GUI_READ | DeviceCapability.INPUT_TOUCH,
    }
    msg.update(overrides)
    return msg


def _reset_runtime_state():
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer

        reset_capability_assimilation_layer()
    except Exception:
        pass
    try:
        from core.mesh.body_mesh_registry import reset_body_mesh_registry

        reset_body_mesh_registry()
    except Exception:
        pass
    try:
        from galaxy_gateway.device_router import device_router

        device_router.devices.clear()
    except Exception:
        pass
    try:
        from galaxy_gateway.android.handlers.registration import clear_registration_gaps

        clear_registration_gaps()
    except Exception:
        pass
    try:
        from core.unified import device_manager as _udm_mod

        _udm_mod.UnifiedDeviceManager._instance = None
    except Exception:
        pass


@pytest.mark.asyncio
async def test_android_registration_assimilates_capabilities_for_routing_queries():
    from core.capability_network_runtime_policy import query_routable_executors
    from galaxy_gateway.android_bridge import AndroidBridge

    _reset_runtime_state()
    bridge = AndroidBridge()
    ws = _make_ws()

    await bridge._handle_device_register(ws, _make_registration_message("cap_dev_01"))

    executors = query_routable_executors(required_capabilities=["gui_read", "input_touch"])
    matching = [executor for executor in executors if executor.node_id == "cap_dev_01"]
    assert matching, "Registered Android device must become queryable from canonical routing executors"
    assert set(matching[0].capabilities) >= {"gui_read", "input_touch"}

    _reset_runtime_state()
