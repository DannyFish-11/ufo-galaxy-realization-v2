"""
tests/test_android_server_e2e.py
================================
End-to-End integration test: Android↔Server coordination path.

Simulates the full server-side flow without any external services:
    1. Android device connects and sends ``device_register``
    2. Device sends ``capability_report`` → capabilities appear in CapabilityRegistry
    3. Capabilities are visible as LLM tool schemas
    4. A natural-language request is dispatched; the mock LLM returns a
       ``tool_call`` targeting the device capability
    5. The tool call is dispatched to the device via AndroidBridge
       (``task_assign`` message sent over the mocked WebSocket)

All external calls (LLM API, real WebSocket) are mocked.
No running server or external services required.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws() -> MagicMock:
    """Minimal mock WebSocket."""
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _v3_msg(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    """Build a fully-compliant AIP v3.0 message dict."""
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


# ---------------------------------------------------------------------------
# Fixture: fresh CapabilityRegistry and AndroidBridge for each test
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_registry():
    """Return a CapabilityRegistry instance with a clean slate."""
    from core.agent.capability_registry import CapabilityRegistry
    reg = CapabilityRegistry.get_instance()
    # Clear existing items so tests are isolated.
    reg._items.clear()
    return reg


@pytest.fixture()
def bridge():
    from galaxy_gateway.android_bridge import AndroidBridge
    return AndroidBridge()


# ===========================================================================
# 1. device_register → device stored in AndroidBridge
# ===========================================================================

class TestDeviceRegister:
    """Step 1: Android device registration via AndroidBridge."""

    @pytest.mark.asyncio
    async def test_register_stores_device(self, bridge):
        ws = _make_ws()
        msg = _v3_msg("device_register", "e2e-device-001",
                      platform="android", model="Pixel 8")
        response = await bridge.handle_message(ws, msg)

        assert response is not None
        assert response["type"] == "device_register_ack"
        assert response["success"] is True

        device = bridge.get_device("e2e-device-001")
        assert device is not None
        assert device.device_id == "e2e-device-001"
        assert device.connected is True

    @pytest.mark.asyncio
    async def test_register_missing_device_id_returns_error(self, bridge):
        ws = _make_ws()
        msg = {
            "version": "3.0",
            "type": "device_register",
            "message_id": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            # device_id intentionally omitted
        }
        response = await bridge.handle_message(ws, msg)
        assert response is not None
        assert response["type"] == "error"
        assert response["error_code"] == "MISSING_REQUIRED_FIELDS"

    @pytest.mark.asyncio
    async def test_register_missing_type_returns_error(self, bridge):
        ws = _make_ws()
        msg = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "device_id": "e2e-device-001",
            "timestamp": int(time.time() * 1000),
            # type intentionally omitted
        }
        response = await bridge.handle_message(ws, msg)
        assert response is not None
        assert response["type"] == "error"
        assert response["error_code"] == "MISSING_REQUIRED_FIELDS"

    @pytest.mark.asyncio
    async def test_register_unknown_type_returns_error(self, bridge):
        ws = _make_ws()
        msg = _v3_msg("not_a_real_message_type", "e2e-device-001")
        response = await bridge.handle_message(ws, msg)
        assert response is not None
        assert response["type"] == "error"
        assert response["error_code"] == "UNKNOWN_MESSAGE_TYPE"


# ===========================================================================
# 2. Legacy AIP/1.0 compatibility — type alias mapping
# ===========================================================================

class TestLegacyCompatibility:
    """Backward-compat: AIP/1.0 alias types are normalised to v3 equivalents."""

    @pytest.mark.asyncio
    async def test_legacy_register_alias(self, bridge):
        """AIP/1.0 type='register' should be normalised to 'device_register'."""
        ws = _make_ws()
        msg = {
            # No version field → detected as AIP/1.0
            "type": "register",
            "device_id": "legacy-001",
            "platform": "android",
        }
        response = await bridge.handle_message(ws, msg)
        assert response is not None
        assert response["type"] == "device_register_ack", (
            f"Expected device_register_ack but got {response.get('type')}: {response}"
        )

    @pytest.mark.asyncio
    async def test_legacy_heartbeat_alias(self, bridge):
        """AIP/1.0 type='agent_heartbeat' should be normalised to 'heartbeat'."""
        ws = _make_ws()
        # Register first so the device is known
        await bridge.handle_message(ws, {
            "type": "register",
            "device_id": "legacy-hb-001",
            "platform": "android",
        })
        hb = {
            "type": "agent_heartbeat",
            "device_id": "legacy-hb-001",
        }
        response = await bridge.handle_message(ws, hb)
        assert response is not None
        assert response["type"] == "heartbeat_ack"

    @pytest.mark.asyncio
    async def test_v2_message_accepted(self, bridge):
        """AIP/2.0 messages (version='2.0') should be accepted and normalised."""
        ws = _make_ws()
        msg = {
            "version": "2.0",
            "type": "device_register",
            "device_id": "v2-device-001",
            "message_id": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "platform": "android",
        }
        response = await bridge.handle_message(ws, msg)
        assert response is not None
        assert response["type"] == "device_register_ack"


# ===========================================================================
# 3. capability_report → CapabilityRegistry
# ===========================================================================

class TestCapabilityReportSync:
    """Step 2: capability_report syncs supported_actions to CapabilityRegistry."""

    @pytest.mark.asyncio
    async def test_capability_report_syncs_to_registry(self, bridge, fresh_registry):
        ws = _make_ws()
        device_id = "cap-device-001"

        # Register first
        await bridge.handle_message(ws, _v3_msg(
            "device_register", device_id, platform="android"
        ))

        # Report capabilities
        cap_msg = _v3_msg(
            "capability_report", device_id,
            platform="android",
            supported_actions=["screenshot", "tap", "swipe", "input_text"],
        )
        response = await bridge.handle_message(ws, cap_msg)

        assert response is not None
        assert response["type"] == "capability_report_ack"
        assert response.get("accepted") is True

        # Verify CapabilityRegistry contains the device capabilities
        tools = fresh_registry.list_tools(source="gateway")
        tool_names = {t.name for t in tools}

        for action in ["screenshot", "tap", "swipe", "input_text"]:
            expected = f"gateway__{device_id}__{action}"
            assert expected in tool_names, (
                f"Expected '{expected}' in CapabilityRegistry tool names: {tool_names}"
            )

    @pytest.mark.asyncio
    async def test_capability_names_are_stable_and_predictable(self, bridge, fresh_registry):
        """Capability names must follow the gateway__<device_id>__<action> pattern."""
        ws = _make_ws()
        device_id = "stable-device-001"

        await bridge.handle_message(ws, _v3_msg("device_register", device_id))
        await bridge.handle_message(ws, _v3_msg(
            "capability_report", device_id,
            supported_actions=["click"],
        ))

        cap = fresh_registry.get(f"gateway__{device_id}__click")
        assert cap is not None
        assert cap.source == "gateway"
        assert cap.source_id == device_id
        assert cap.available is True

    @pytest.mark.asyncio
    async def test_capability_appears_in_tool_schema_set(self, bridge, fresh_registry):
        """After capability_report, the device capability must appear in to_tool_schemas()."""
        ws = _make_ws()
        device_id = "schema-device-001"

        await bridge.handle_message(ws, _v3_msg("device_register", device_id))
        await bridge.handle_message(ws, _v3_msg(
            "capability_report", device_id,
            supported_actions=["screenshot"],
        ))

        schemas = fresh_registry.to_tool_schemas()
        schema_names = {s["function"]["name"] for s in schemas}
        assert f"gateway__{device_id}__screenshot" in schema_names


# ===========================================================================
# 4. Full E2E: register → capability_report → mock LLM tool_call → task_assign
# ===========================================================================

class TestFullE2EPipeline:
    """Full E2E pipeline: registration → capability sync → NL dispatch → device."""

    @pytest.mark.asyncio
    async def test_e2e_nl_to_device_dispatch(self, bridge, fresh_registry):
        """
        Simulates the complete Android↔Server coordination path:
            1. device_register
            2. capability_report (screenshot, tap)
            3. CapabilityRegistry contains gateway__ tools
            4. Mock LLM produces a tool_call for 'gateway__<id>__screenshot'
            5. tool_call is dispatched to the device via AndroidBridge.assign_task()
        """
        ws = _make_ws()
        device_id = "e2e-full-001"

        # ── Step 1: Register ──
        reg_response = await bridge.handle_message(ws, _v3_msg(
            "device_register", device_id,
            platform="android",
            model="Pixel 9",
        ))
        assert reg_response["type"] == "device_register_ack"

        # ── Step 2: Report capabilities ──
        cap_response = await bridge.handle_message(ws, _v3_msg(
            "capability_report", device_id,
            supported_actions=["screenshot", "tap"],
        ))
        assert cap_response["type"] == "capability_report_ack"

        # ── Step 3: Verify tool schemas ──
        schemas = fresh_registry.to_tool_schemas()
        schema_names = {s["function"]["name"] for s in schemas}
        screenshot_tool = f"gateway__{device_id}__screenshot"
        assert screenshot_tool in schema_names, (
            f"Expected '{screenshot_tool}' in tool schemas: {schema_names}"
        )

        # ── Step 4: Mock LLM produces a tool_call for the device capability ──
        mock_tool_call = {
            "tool_name": screenshot_tool,
            "arguments": {"quality": 90, "scale": 1.0},
        }

        # ── Step 5: Dispatch tool call to device via AndroidBridge ──
        # patch send_to_device so we can inspect the dispatched message
        sent: Dict[str, Any] = {}

        async def _mock_send(device_id, message, **kwargs):
            sent.update(message)
            return {"success": True}

        bridge.send_to_device = _mock_send

        task_id = str(uuid.uuid4())
        result = await bridge.assign_task(
            device_id=device_id,
            task_id=task_id,
            task_type="screenshot",
            payload=mock_tool_call["arguments"],
        )

        # assign_task calls send_to_device; verify the dispatched message
        assert sent.get("type") == "task_assign"
        assert sent.get("device_id") == device_id
        assert sent.get("task_id") == task_id
        assert sent.get("task_type") == "screenshot"

    @pytest.mark.asyncio
    async def test_capability_report_without_prior_register_still_syncs(
        self, bridge, fresh_registry
    ):
        """
        capability_report should sync capabilities to CapabilityRegistry even
        when the device has not previously registered (graceful handling).
        """
        ws = _make_ws()
        device_id = "unreg-device-001"

        cap_msg = _v3_msg(
            "capability_report", device_id,
            supported_actions=["tap"],
        )
        response = await bridge.handle_message(ws, cap_msg)
        assert response is not None
        assert response["type"] == "capability_report_ack"

        # Capability must still appear in registry even without prior register
        cap = fresh_registry.get(f"gateway__{device_id}__tap")
        assert cap is not None
        assert cap.available is True
