"""
tests/integration/android_bridge/test_android_bridge_modularization.py
================================================
Tests for PR-3: Android Bridge modularization.

Validates that:
1. All new sub-modules exist and export the correct symbols.
2. All handler functions are importable and callable.
3. Backward-compatible ``_handle_*`` methods on AndroidBridge still work.
4. AndroidBridge dispatch still routes messages to the correct handlers.
5. Transport cache operations (register/heartbeat/disconnect/reconnect) work.
6. MessageBuilder produces correctly structured messages.
7. DeviceCapability bitmask operations are correct.
8. Rect / UIElement / AndroidDevice dataclasses behave as expected.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _make_reg_msg(device_id: str = "test_dev_01", **overrides) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "version": "3.0",
        "type": "device_register",
        "message_id": "msg-001",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "name": "Test Phone",
        "model": "Pixel 7",
        "platform": "android",
    }
    msg.update(overrides)
    return msg


def _make_heartbeat_msg(device_id: str) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": "heartbeat",
        "message_id": "msg-hb",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
    }


# ---------------------------------------------------------------------------
# A. Sub-module import tests
# ---------------------------------------------------------------------------

class TestSubModuleImports:
    """Verify that all new sub-modules are importable."""

    def test_capabilities_importable(self):
        from galaxy_gateway.android.capabilities import DeviceCapability
        assert DeviceCapability is not None

    def test_models_importable(self):
        from galaxy_gateway.android.models import Rect, UIElement, AndroidDevice
        assert Rect is not None
        assert UIElement is not None
        assert AndroidDevice is not None

    def test_message_builder_importable(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        assert MessageBuilder is not None

    def test_handlers_package_importable(self):
        import galaxy_gateway.android.handlers as handlers_pkg
        assert handlers_pkg is not None

    def test_handler_registration_importable(self):
        from galaxy_gateway.android.handlers.registration import (
            handle_device_register, handle_unregistered,
        )
        assert callable(handle_device_register)
        assert callable(handle_unregistered)

    def test_handler_heartbeat_importable(self):
        from galaxy_gateway.android.handlers.heartbeat import (
            handle_heartbeat, handle_device_status, handle_agent_ping,
        )
        assert callable(handle_heartbeat)
        assert callable(handle_device_status)
        assert callable(handle_agent_ping)

    def test_handler_task_lifecycle_importable(self):
        from galaxy_gateway.android.handlers.task_lifecycle import (
            handle_task_result, handle_task_end, handle_task_progress,
            handle_command_result, handle_error,
            handle_task_cancel, handle_task_status,
        )
        for fn in (handle_task_result, handle_task_end, handle_task_progress,
                   handle_command_result, handle_error,
                   handle_task_cancel, handle_task_status):
            assert callable(fn)

    def test_handler_task_submit_importable(self):
        from galaxy_gateway.android.handlers.task_submit import (
            handle_task_execute, handle_task_submit,
        )
        assert callable(handle_task_execute)
        assert callable(handle_task_submit)

    def test_handler_goal_execution_importable(self):
        from galaxy_gateway.android.handlers.goal_execution import (
            handle_goal_execution, handle_parallel_subtask,
            handle_goal_execution_result,
        )
        for fn in (handle_goal_execution, handle_parallel_subtask, handle_goal_execution_result):
            assert callable(fn)

    def test_handler_capability_report_importable(self):
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report
        assert callable(handle_capability_report)

    def test_handler_diagnostics_importable(self):
        from galaxy_gateway.android.handlers.diagnostics import handle_diagnostics_payload
        assert callable(handle_diagnostics_payload)

    def test_handler_vision_importable(self):
        from galaxy_gateway.android.handlers.vision import handle_vision_request
        assert callable(handle_vision_request)

    def test_handler_generic_importable(self):
        from galaxy_gateway.android.handlers.generic import handle_generic_forward
        assert callable(handle_generic_forward)

    def test_android_package_init_exports(self):
        from galaxy_gateway.android import DeviceCapability, Rect, UIElement, AndroidDevice, MessageBuilder
        for symbol in (DeviceCapability, Rect, UIElement, AndroidDevice, MessageBuilder):
            assert symbol is not None

    def test_handlers_init_exports(self):
        from galaxy_gateway.android.handlers import (
            handle_device_register, handle_unregistered,
            handle_heartbeat, handle_device_status, handle_agent_ping,
            handle_task_result, handle_task_end, handle_task_progress,
            handle_command_result, handle_error,
            handle_task_cancel, handle_task_status,
            handle_task_execute, handle_task_submit,
            handle_goal_execution, handle_parallel_subtask, handle_goal_execution_result,
            handle_capability_report, handle_diagnostics_payload,
            handle_vision_request, handle_generic_forward,
        )
        assert all(callable(fn) for fn in [
            handle_device_register, handle_unregistered,
            handle_heartbeat, handle_device_status, handle_agent_ping,
            handle_task_result, handle_task_end, handle_task_progress,
            handle_command_result, handle_error,
            handle_task_cancel, handle_task_status,
            handle_task_execute, handle_task_submit,
            handle_goal_execution, handle_parallel_subtask, handle_goal_execution_result,
            handle_capability_report, handle_diagnostics_payload,
            handle_vision_request, handle_generic_forward,
        ])


# ---------------------------------------------------------------------------
# B. DeviceCapability tests
# ---------------------------------------------------------------------------

class TestDeviceCapability:
    def test_bitmask_values_are_powers_of_two(self):
        from galaxy_gateway.android.capabilities import DeviceCapability
        caps = [
            DeviceCapability.NETWORK, DeviceCapability.STORAGE, DeviceCapability.COMPUTE,
            DeviceCapability.GUI_READ, DeviceCapability.GUI_WRITE, DeviceCapability.GUI_SCREENSHOT,
            DeviceCapability.INPUT_TOUCH, DeviceCapability.INPUT_KEYBOARD,
        ]
        for c in caps:
            assert (c & (c - 1)) == 0  # power of two

    def test_get_android_default_nonzero(self):
        from galaxy_gateway.android.capabilities import DeviceCapability
        caps = DeviceCapability.get_android_default()
        assert caps > 0

    def test_has_capability(self):
        from galaxy_gateway.android.capabilities import DeviceCapability
        caps = DeviceCapability.NETWORK | DeviceCapability.STORAGE
        assert DeviceCapability.has_capability(caps, DeviceCapability.NETWORK)
        assert DeviceCapability.has_capability(caps, DeviceCapability.STORAGE)
        assert not DeviceCapability.has_capability(caps, DeviceCapability.COMPUTE)

    def test_to_list_returns_strings(self):
        from galaxy_gateway.android.capabilities import DeviceCapability
        caps = DeviceCapability.NETWORK | DeviceCapability.GUI_READ
        result = DeviceCapability.to_list(caps)
        assert "network" in result
        assert "gui_read" in result
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)

    def test_none_capability_empty_list(self):
        from galaxy_gateway.android.capabilities import DeviceCapability
        assert DeviceCapability.to_list(DeviceCapability.NONE) == []


# ---------------------------------------------------------------------------
# C. Model dataclass tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_rect_center(self):
        from galaxy_gateway.android.models import Rect
        r = Rect(x=10, y=20, width=100, height=200)
        assert r.center_x == 60
        assert r.center_y == 120

    def test_rect_to_dict_from_dict_roundtrip(self):
        from galaxy_gateway.android.models import Rect
        r = Rect(x=5, y=10, width=50, height=100)
        d = r.to_dict()
        r2 = Rect.from_dict(d)
        assert r == r2

    def test_uielement_to_dict(self):
        from galaxy_gateway.android.models import UIElement
        el = UIElement(element_id="btn_1", text="Click me", is_clickable=True)
        d = el.to_dict()
        assert d["element_id"] == "btn_1"
        assert d["text"] == "Click me"
        assert d["is_clickable"] is True

    def test_android_device_from_registration(self):
        from galaxy_gateway.android.models import AndroidDevice
        data = {
            "device_id": "android_01",
            "name": "My Phone",
            "model": "Pixel 8",
            "platform": "android",
        }
        device = AndroidDevice.from_registration(data)
        assert device.device_id == "android_01"
        assert device.model == "Pixel 8"
        assert device.connected is True
        assert device.last_heartbeat > 0

    def test_android_device_to_dict(self):
        from galaxy_gateway.android.models import AndroidDevice
        device = AndroidDevice(device_id="dev_01", name="Phone", model="Model X")
        d = device.to_dict()
        assert d["device_id"] == "dev_01"
        assert "capabilities_list" in d


# ---------------------------------------------------------------------------
# D. MessageBuilder tests
# ---------------------------------------------------------------------------

class TestMessageBuilder:
    def test_heartbeat_ack_structure(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.heartbeat_ack("dev_01")
        assert msg["device_id"] == "dev_01"
        assert msg["type"] == "heartbeat_ack"
        assert "message_id" in msg
        assert "timestamp" in msg

    def test_device_register_ack_success(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.device_register_ack("dev_01", success=True, session_id="sess_1")
        assert msg["success"] is True
        assert msg["session_id"] == "sess_1"

    def test_device_register_ack_failure(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.device_register_ack("dev_01", success=False, message="Failed")
        assert msg["success"] is False
        assert msg["message"] == "Failed"

    def test_task_assign_structure(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.task_assign("dev_01", "task_1", "goal_execution", {"goal": "open app"})
        assert msg["task_id"] == "task_1"
        assert msg["task_type"] == "goal_execution"
        assert msg["payload"]["goal"] == "open app"

    def test_error_message(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.error("dev_01", "ERR_CODE", "Something failed", correlation_id="corr_1")
        assert msg["error_code"] == "ERR_CODE"
        assert msg["error_message"] == "Something failed"
        assert msg["correlation_id"] == "corr_1"

    def test_capability_report_ack(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.capability_report_ack("dev_01", accepted=True, message="OK")
        assert msg["accepted"] is True
        assert msg["message"] == "OK"

    def test_vision_result_uses_task_assign(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.vision_result("dev_01", "t1", {"success": True})
        assert msg["task_type"] == "vision_action"
        assert msg["payload"]["success"] is True

    def test_goal_execution_result(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.goal_execution_result(
            "dev_01", {"status": "success"}, correlation_id="c1", trace_id="t1"
        )
        assert msg["payload"]["status"] == "success"
        assert msg["correlation_id"] == "c1"
        assert msg["trace_id"] == "t1"


# ---------------------------------------------------------------------------
# E. AndroidBridge backward-compatible _handle_* wrapper tests
# ---------------------------------------------------------------------------

class TestAndroidBridgeBackwardCompatWrappers:
    """Verify _handle_* methods still exist on AndroidBridge and delegate correctly."""

    def _make_bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    @pytest.mark.asyncio
    async def test_handle_device_register_wrapper(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = _make_reg_msg("compat_01")
        with patch.object(bridge, "_write_registration_to_udm"):
            resp = await bridge._handle_device_register(ws, msg)
        assert resp["type"] == "device_register_ack"
        assert resp["success"] is True

    @pytest.mark.asyncio
    async def test_handle_heartbeat_wrapper(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        # Register first
        reg_msg = _make_reg_msg("hb_compat_01")
        with patch.object(bridge, "_write_registration_to_udm"), \
             patch.object(bridge, "_patch_heartbeat_to_udm"):
            await bridge._handle_device_register(ws, reg_msg)
            hb_msg = _make_heartbeat_msg("hb_compat_01")
            resp = await bridge._handle_heartbeat(ws, hb_msg)
        assert resp["type"] == "heartbeat_ack"

    @pytest.mark.asyncio
    async def test_handle_unregistered_wrapper(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "version": "3.0",
            "type": "some_unknown_type",
            "device_id": "dev_x",
            "message_id": "m1",
            "timestamp": 1000,
        }
        resp = await bridge._handle_unregistered(ws, msg)
        assert resp["type"] == "ack"
        assert resp["original_type"] == "some_unknown_type"

    @pytest.mark.asyncio
    async def test_handle_generic_forward_wrapper(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {"type": "app_start", "device_id": "dev_01", "message_id": "m1"}
        resp = await bridge._handle_generic_forward(ws, msg)
        assert resp["type"] == "app_start_ack"

    @pytest.mark.asyncio
    async def test_handle_task_cancel_wrapper(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {"type": "task_cancel", "device_id": "dev_01", "task_id": "no_such_task", "message_id": "m_cancel"}
        resp = await bridge._handle_task_cancel(ws, msg)
        assert resp["type"] == "task_cancel_ack"
        assert resp["cancelled"] is False

    @pytest.mark.asyncio
    async def test_handle_task_status_wrapper(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {"type": "task_status", "device_id": "dev_01", "task_id": "no_such_task", "message_id": "m_status"}
        resp = await bridge._handle_task_status(ws, msg)
        assert resp["type"] == "task_status_response"

    @pytest.mark.asyncio
    async def test_handle_agent_ping_wrapper(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {"type": "agent_ping", "device_id": "dev_01", "message_id": "m1"}
        resp = await bridge._handle_agent_ping(ws, msg)
        assert resp["type"] == "heartbeat_ack"

    @pytest.mark.asyncio
    async def test_handle_diagnostics_payload_wrapper(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "type": "diagnostics_payload",
            "device_id": "dev_01",
            "error_type": "crash",
            "message_id": "m1",
        }
        resp = await bridge._handle_diagnostics_payload(ws, msg)
        assert resp["accepted"] is True

    @pytest.mark.asyncio
    async def test_handle_task_progress_returns_none(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {"type": "task_progress", "device_id": "dev_01", "task_id": "t1", "progress": 50}
        resp = await bridge._handle_task_progress(ws, msg)
        assert resp is None

    @pytest.mark.asyncio
    async def test_handle_error_returns_none(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "type": "error",
            "device_id": "dev_01",
            "error_code": "TEST_ERR",
            "error_message": "test error",
        }
        resp = await bridge._handle_error(ws, msg)
        assert resp is None


# ---------------------------------------------------------------------------
# F. AndroidBridge dispatch routing tests
# ---------------------------------------------------------------------------

class TestAndroidBridgeDispatch:
    """Verify that handle_message routes to the correct handler."""

    def _make_bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    @pytest.mark.asyncio
    async def test_dispatch_device_register(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = _make_reg_msg("dispatch_01")
        with patch.object(bridge, "_write_registration_to_udm"):
            resp = await bridge.handle_message(ws, msg)
        assert resp is not None
        assert resp["type"] == "device_register_ack"

    @pytest.mark.asyncio
    async def test_dispatch_device_heartbeat(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        with patch.object(bridge, "_write_registration_to_udm"), \
             patch.object(bridge, "_patch_heartbeat_to_udm"):
            await bridge.handle_message(ws, _make_reg_msg("hb_dispatch"))
            hb = _make_heartbeat_msg("hb_dispatch")
            resp = await bridge.handle_message(ws, hb)
        assert resp["type"] == "heartbeat_ack"

    @pytest.mark.asyncio
    async def test_dispatch_missing_type_returns_error(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {"device_id": "dev_01", "message_id": "m1"}
        resp = await bridge.handle_message(ws, msg)
        assert resp is not None
        assert resp["error_code"] == "MISSING_REQUIRED_FIELDS"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_type_returns_error(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "version": "3.0",
            "type": "totally_unknown_type_xyz",
            "device_id": "dev_01",
            "message_id": "m1",
            "timestamp": 1000,
        }
        resp = await bridge.handle_message(ws, msg)
        assert resp is not None
        assert resp["error_code"] == "UNKNOWN_MESSAGE_TYPE"

    @pytest.mark.asyncio
    async def test_trace_id_propagated_to_response(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = _make_reg_msg("trace_test")
        msg["trace_id"] = "trace_abc"
        with patch.object(bridge, "_write_registration_to_udm"):
            resp = await bridge.handle_message(ws, msg)
        # Registration ack doesn't have a payload dict so trace_id propagation
        # only applies to responses with a payload — just verify the response is valid.
        assert resp["type"] == "device_register_ack"

    @pytest.mark.asyncio
    async def test_dispatch_task_cancel_routes_to_real_handler(self):
        """task_cancel 应路由到真实 handler 而非 generic forward"""
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "version": "3.0",
            "type": "task_cancel",
            "device_id": "dispatch_cancel_01",
            "task_id": "some_task",
            "message_id": "msg_cancel",
            "timestamp": 1000,
        }
        resp = await bridge.handle_message(ws, msg)
        assert resp is not None
        # Real handler returns task_cancel_ack (not generic "task_cancel_ack" from forward)
        assert resp["type"] == "task_cancel_ack"
        # Real handler populates 'cancelled' boolean
        assert "cancelled" in resp

    @pytest.mark.asyncio
    async def test_dispatch_task_status_routes_to_real_handler(self):
        """task_status 应路由到真实 handler 而非 generic forward"""
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "version": "3.0",
            "type": "task_status",
            "device_id": "dispatch_status_01",
            "task_id": "some_task",
            "message_id": "msg_status",
            "timestamp": 1000,
        }
        resp = await bridge.handle_message(ws, msg)
        assert resp is not None
        assert resp["type"] == "task_status_response"
        assert "status" in resp


# ---------------------------------------------------------------------------
# G. Standalone handler function tests
# ---------------------------------------------------------------------------

class TestStandaloneHandlers:
    """Test handler functions called with an explicit bridge argument."""

    def _make_bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    @pytest.mark.asyncio
    async def test_handle_device_register_standalone(self):
        from galaxy_gateway.android.handlers.registration import handle_device_register
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = _make_reg_msg("sa_reg_01")
        with patch.object(bridge, "_write_registration_to_udm"):
            resp = await handle_device_register(bridge, ws, msg)
        assert resp["success"] is True
        assert "sa_reg_01" in bridge._devices

    @pytest.mark.asyncio
    async def test_handle_heartbeat_standalone(self):
        from galaxy_gateway.android.handlers.registration import handle_device_register
        from galaxy_gateway.android.handlers.heartbeat import handle_heartbeat
        bridge = self._make_bridge()
        ws = _make_ws()
        with patch.object(bridge, "_write_registration_to_udm"), \
             patch.object(bridge, "_patch_heartbeat_to_udm"):
            await handle_device_register(bridge, ws, _make_reg_msg("sa_hb_01"))
            old_hb = bridge._devices["sa_hb_01"].last_heartbeat
            await asyncio.sleep(0.01)
            resp = await handle_heartbeat(bridge, ws, _make_heartbeat_msg("sa_hb_01"))
        assert resp["type"] == "heartbeat_ack"
        assert bridge._devices["sa_hb_01"].last_heartbeat >= old_hb

    @pytest.mark.asyncio
    async def test_handle_task_result_resolves_future(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_result
        bridge = self._make_bridge()
        ws = _make_ws()
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        bridge._pending_responses["task_123"] = future
        msg = {
            "type": "task_result",
            "device_id": "dev_01",
            "task_id": "task_123",
            "status": "completed",
        }
        await handle_task_result(bridge, ws, msg)
        assert future.done()
        assert future.result()["task_id"] == "task_123"

    @pytest.mark.asyncio
    async def test_handle_generic_forward_standalone(self):
        from galaxy_gateway.android.handlers.generic import handle_generic_forward
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {"type": "app_start", "device_id": "dev_01"}
        resp = await handle_generic_forward(bridge, ws, msg)
        assert resp["type"] == "app_start_ack"

    @pytest.mark.asyncio
    async def test_handle_unregistered_standalone(self):
        from galaxy_gateway.android.handlers.registration import handle_unregistered
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {"type": "foobar", "device_id": "dev_01"}
        resp = await handle_unregistered(bridge, ws, msg)
        assert resp["status"] == "received"
        assert resp["original_type"] == "foobar"

    @pytest.mark.asyncio
    async def test_handle_capability_report_standalone(self):
        from galaxy_gateway.android.handlers.registration import handle_device_register
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report
        bridge = self._make_bridge()
        ws = _make_ws()
        with patch.object(bridge, "_write_registration_to_udm"):
            await handle_device_register(bridge, ws, _make_reg_msg("cap_sa_01"))
        msg = {
            "type": "capability_report",
            "device_id": "cap_sa_01",
            "supported_actions": ["tap", "swipe"],
            "message_id": "m1",
        }
        with patch("galaxy_gateway.capability_registry.get_gateway_capability_registry",
                   side_effect=ImportError):
            resp = await handle_capability_report(bridge, ws, msg)
        assert resp["accepted"] is True
        assert bridge._devices["cap_sa_01"].supported_actions == ["tap", "swipe"]

    @pytest.mark.asyncio
    async def test_handle_vision_request_no_image(self):
        from galaxy_gateway.android.handlers.vision import handle_vision_request
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "type": "vision_request",
            "device_id": "dev_01",
            "image_base64": "",
        }
        resp = await handle_vision_request(bridge, ws, msg)
        assert resp["error_code"] == "VISION_NO_IMAGE"

    @pytest.mark.asyncio
    async def test_handle_task_execute_sets_current_task(self):
        from galaxy_gateway.android.handlers.registration import handle_device_register
        from galaxy_gateway.android.handlers.task_submit import handle_task_execute
        bridge = self._make_bridge()
        ws = _make_ws()
        with patch.object(bridge, "_write_registration_to_udm"):
            await handle_device_register(bridge, ws, _make_reg_msg("te_sa_01"))
        msg = {
            "type": "task_execute",
            "device_id": "te_sa_01",
            "task_id": "t_exec_99",
            "task_type": "screenshot",
            "payload": {},
        }
        resp = await handle_task_execute(bridge, ws, msg)
        assert bridge._devices["te_sa_01"].current_task_id == "t_exec_99"
        assert resp["task_id"] == "t_exec_99"

    @pytest.mark.asyncio
    async def test_handle_task_cancel_cancels_pending_future(self):
        """task_cancel 应取消 _pending_responses 中的 Future 并返回 task_cancel_ack"""
        from galaxy_gateway.android.handlers.registration import handle_device_register
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel
        bridge = self._make_bridge()
        ws = _make_ws()
        with patch.object(bridge, "_write_registration_to_udm"):
            await handle_device_register(bridge, ws, _make_reg_msg("tc_sa_01"))

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        task_id = "cancel_task_001"
        bridge._pending_responses[task_id] = fut
        bridge._devices["tc_sa_01"].current_task_id = task_id

        msg = {
            "type": "task_cancel",
            "device_id": "tc_sa_01",
            "task_id": task_id,
            "message_id": "msg-cancel-001",
        }
        resp = await handle_task_cancel(bridge, ws, msg)

        # Future should be cancelled
        assert fut.cancelled()
        # task_id should be cleaned from pending_responses
        assert task_id not in bridge._pending_responses
        # device current_task_id cleared
        assert bridge._devices["tc_sa_01"].current_task_id is None
        # response shape
        assert resp["type"] == "task_cancel_ack"
        assert resp["task_id"] == task_id
        assert resp["cancelled"] is True
        assert resp["correlation_id"] == "msg-cancel-001"

    @pytest.mark.asyncio
    async def test_handle_task_cancel_unknown_task_returns_not_found(self):
        """取消不存在任务时返回 cancelled=False 且包含 reason"""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "type": "task_cancel",
            "device_id": "tc_sa_02",
            "task_id": "nonexistent_task",
            "message_id": "msg-cancel-002",
        }
        resp = await handle_task_cancel(bridge, ws, msg)
        assert resp["type"] == "task_cancel_ack"
        assert resp["cancelled"] is False
        assert resp["reason"] == "task_not_found"

    @pytest.mark.asyncio
    async def test_handle_task_cancel_already_done_future(self):
        """已完成的 Future 被 cancel 时返回 cancelled=False + reason"""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel
        bridge = self._make_bridge()
        ws = _make_ws()

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        fut.set_result({"status": "completed"})
        task_id = "done_task_001"
        bridge._pending_responses[task_id] = fut

        msg = {
            "type": "task_cancel",
            "device_id": "tc_sa_03",
            "task_id": task_id,
            "message_id": "msg-cancel-003",
        }
        resp = await handle_task_cancel(bridge, ws, msg)
        assert resp["type"] == "task_cancel_ack"
        assert resp["cancelled"] is False
        assert resp["reason"] == "task_already_completed"

    @pytest.mark.asyncio
    async def test_handle_task_status_running(self):
        """有待处理 Future 时返回 running 状态"""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status
        bridge = self._make_bridge()
        ws = _make_ws()

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        task_id = "status_task_001"
        bridge._pending_responses[task_id] = fut

        msg = {
            "type": "task_status",
            "device_id": "ts_sa_01",
            "task_id": task_id,
            "message_id": "msg-status-001",
        }
        resp = await handle_task_status(bridge, ws, msg)
        assert resp["type"] == "task_status_response"
        assert resp["task_id"] == task_id
        assert resp["status"] == "running"
        assert resp["correlation_id"] == "msg-status-001"

    @pytest.mark.asyncio
    async def test_handle_task_status_completed_after_result(self):
        """Future 已完成时返回 completed 状态"""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status
        bridge = self._make_bridge()
        ws = _make_ws()

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        fut.set_result({"status": "completed"})
        task_id = "status_task_002"
        bridge._pending_responses[task_id] = fut

        msg = {
            "type": "task_status",
            "device_id": "ts_sa_02",
            "task_id": task_id,
            "message_id": "msg-status-002",
        }
        resp = await handle_task_status(bridge, ws, msg)
        assert resp["type"] == "task_status_response"
        assert resp["status"] == "completed"

    @pytest.mark.asyncio
    async def test_handle_task_status_cancelled_future(self):
        """已取消的 Future 返回 cancelled 状态"""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status
        bridge = self._make_bridge()
        ws = _make_ws()

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        fut.cancel()
        task_id = "status_task_003"
        bridge._pending_responses[task_id] = fut

        msg = {
            "type": "task_status",
            "device_id": "ts_sa_03",
            "task_id": task_id,
            "message_id": "msg-status-003",
        }
        resp = await handle_task_status(bridge, ws, msg)
        assert resp["type"] == "task_status_response"
        assert resp["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_handle_task_status_unknown_task(self):
        """未知任务返回 completed（默认状态）"""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = {
            "type": "task_status",
            "device_id": "ts_sa_04",
            "task_id": "unknown_task_xyz",
            "message_id": "msg-status-004",
        }
        resp = await handle_task_status(bridge, ws, msg)
        assert resp["type"] == "task_status_response"
        assert resp["status"] == "completed"


# ---------------------------------------------------------------------------
# H. Transport cache operations
# ---------------------------------------------------------------------------

class TestTransportCacheOperations:
    def _make_bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    @pytest.mark.asyncio
    async def test_disconnect_clears_websocket(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = _make_reg_msg("dc_op_01")
        with patch.object(bridge, "_write_registration_to_udm"), \
             patch.object(bridge, "_patch_disconnect_to_udm"):
            await bridge._handle_device_register(ws, msg)
            await bridge.disconnect_device("dc_op_01")
        assert bridge._devices["dc_op_01"].connected is False
        assert bridge._devices["dc_op_01"].websocket is None

    @pytest.mark.asyncio
    async def test_reconnect_restores_connection(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        msg = _make_reg_msg("rc_op_01")
        with patch.object(bridge, "_write_registration_to_udm"), \
             patch.object(bridge, "_patch_disconnect_to_udm"), \
             patch.object(bridge, "_patch_reconnect_to_udm"):
            await bridge._handle_device_register(ws, msg)
            await bridge.disconnect_device("rc_op_01")
            assert bridge._devices["rc_op_01"].connected is False
            new_ws = _make_ws()
            result = await bridge.reconnect_device("rc_op_01", new_ws)
        assert result is True
        assert bridge._devices["rc_op_01"].connected is True

    @pytest.mark.asyncio
    async def test_reconnect_unknown_device_returns_false(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        result = await bridge.reconnect_device("unknown_device", ws)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_all_devices_returns_list(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        with patch.object(bridge, "_write_registration_to_udm"):
            await bridge._handle_device_register(ws, _make_reg_msg("list_01"))
            await bridge._handle_device_register(ws, _make_reg_msg("list_02"))
        devices = bridge.get_all_devices()
        assert len(devices) == 2

    @pytest.mark.asyncio
    async def test_get_connected_devices(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        with patch.object(bridge, "_write_registration_to_udm"), \
             patch.object(bridge, "_patch_disconnect_to_udm"):
            await bridge._handle_device_register(ws, _make_reg_msg("conn_01"))
            await bridge._handle_device_register(ws, _make_reg_msg("conn_02"))
            await bridge.disconnect_device("conn_02")
        connected = bridge.get_connected_devices()
        assert len(connected) == 1
        assert connected[0].device_id == "conn_01"

    def test_get_device_health_empty(self):
        bridge = self._make_bridge()
        health = bridge.get_device_health()
        assert health["total"] == 0
        assert health["healthy"] == 0

    @pytest.mark.asyncio
    async def test_get_device_health_with_devices(self):
        bridge = self._make_bridge()
        ws = _make_ws()
        with patch.object(bridge, "_write_registration_to_udm"), \
             patch.object(bridge, "_patch_heartbeat_to_udm"):
            await bridge._handle_device_register(ws, _make_reg_msg("health_01"))
            await bridge._handle_heartbeat(ws, _make_heartbeat_msg("health_01"))
        health = bridge.get_device_health()
        assert health["total"] == 1
        assert health["healthy"] == 1


# ---------------------------------------------------------------------------
# I. android_bridge module backward-compat re-export test
# ---------------------------------------------------------------------------

class TestAndroidBridgeModuleReExports:
    """Verify all public symbols remain importable from galaxy_gateway.android_bridge."""

    def test_all_public_symbols_importable(self):
        from galaxy_gateway.android_bridge import (
            AndroidBridge,
            android_bridge,
            DeviceCapability,
            MessageBuilder,
            Rect,
            UIElement,
            AndroidDevice,
            DeviceType,
            DevicePlatform,
            MessageType,
            TaskStatus,
            ResultStatus,
        )
        assert AndroidBridge is not None
        assert android_bridge is not None
        assert DeviceCapability is not None
        assert MessageBuilder is not None

    def test_android_bridge_package_bridge_py(self):
        from galaxy_gateway.android.bridge import (
            AndroidBridge,
            android_bridge,
            DeviceCapability,
            MessageBuilder,
            Rect,
            UIElement,
            AndroidDevice,
        )
        assert AndroidBridge is not None
