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


# ===========================================================================
# 5. PR-S2: WS handler v3-only parsing via compat normalisation
# ===========================================================================

class TestPRS2WSv3Parsing:
    """
    PR-S2 verification: WS entry points parse AIP v3 only, with legacy input
    normalised exclusively through ``galaxy_gateway.protocol.compat``.

    These tests target ``android_bridge.handle_message()`` directly — the same
    code path used by ``_handle_android_ws`` in the gateway app — to verify:

    1. Pure AIP v3 messages are processed unchanged.
    2. Legacy AIP/1.0 (no version, alias type) messages are accepted and
       normalised to v3 before processing.
    3. AIP/2.0 messages (version='2.0') are accepted and normalised.
    4. After normalisation, the message seen by downstream handlers always
       carries ``version='3.0'`` and canonical v3 type names.
    5. The ``normalise_to_v3_dict`` helper in compat preserves extra
       application-level fields (platform, model, etc.).
    """

    # --- 5.1  Pure v3 messages ---

    @pytest.mark.asyncio
    async def test_pure_v3_device_register_accepted(self, bridge):
        """Native AIP/3.0 device_register is processed without normalisation."""
        ws = _make_ws()
        response = await bridge.handle_message(ws, _v3_msg(
            "device_register", "prs2-v3-001", platform="android",
        ))
        assert response is not None
        assert response["type"] == "device_register_ack"
        assert response.get("success") is True

    @pytest.mark.asyncio
    async def test_pure_v3_heartbeat_accepted(self, bridge):
        """Native AIP/3.0 heartbeat type='heartbeat' is processed correctly."""
        ws = _make_ws()
        # Register first
        await bridge.handle_message(ws, _v3_msg("device_register", "prs2-v3-hb"))
        response = await bridge.handle_message(ws, _v3_msg("heartbeat", "prs2-v3-hb"))
        assert response is not None
        assert response["type"] == "heartbeat_ack"

    @pytest.mark.asyncio
    async def test_pure_v3_capability_report_accepted(self, bridge, fresh_registry):
        """Native AIP/3.0 capability_report syncs to CapabilityRegistry."""
        ws = _make_ws()
        device_id = "prs2-v3-cap-001"
        await bridge.handle_message(ws, _v3_msg("device_register", device_id))
        response = await bridge.handle_message(ws, _v3_msg(
            "capability_report", device_id,
            supported_actions=["tap", "screenshot"],
        ))
        assert response is not None
        assert response["type"] == "capability_report_ack"
        assert fresh_registry.get(f"gateway__{device_id}__tap") is not None

    # --- 5.2  Legacy AIP/1.0 — normalised via compat ---

    @pytest.mark.asyncio
    async def test_legacy_v1_register_normalised_via_compat(self, bridge):
        """
        AIP/1.0 message without 'version' and type='register' must be
        normalised to v3 exclusively through compat.  The bridge must NOT
        implement its own legacy parsing branch.
        """
        ws = _make_ws()
        legacy_msg = {
            # No version field → AIP/1.0 detection in compat
            "type": "register",
            "device_id": "prs2-legacy-001",
            "platform": "android",
        }
        response = await bridge.handle_message(ws, legacy_msg)
        assert response is not None
        assert response["type"] == "device_register_ack", (
            f"Expected device_register_ack, got: {response}"
        )

    @pytest.mark.asyncio
    async def test_legacy_v1_heartbeat_alias_normalised_via_compat(self, bridge):
        """AIP/1.0 'agent_heartbeat' is normalised to 'heartbeat' via compat."""
        ws = _make_ws()
        # Register with legacy alias first
        await bridge.handle_message(ws, {
            "type": "registration",
            "device_id": "prs2-legacy-hb",
        })
        response = await bridge.handle_message(ws, {
            "type": "agent_heartbeat",
            "device_id": "prs2-legacy-hb",
        })
        assert response is not None
        assert response["type"] == "heartbeat_ack"

    @pytest.mark.asyncio
    async def test_legacy_v1_normalised_type_seen_by_handler(self, bridge):
        """
        After compat normalisation, the message dict seen inside handle_message
        must have version='3.0' and a canonical v3 type name — not the legacy alias.
        """
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict

        legacy_input = {"type": "register", "device_id": "prs2-type-check"}
        normalised = normalise_to_v3_dict(legacy_input)

        assert normalised["version"] == "3.0"
        assert normalised["type"] == "device_register", (
            f"Expected 'device_register', got: {normalised['type']}"
        )

    # --- 5.3  AIP/2.0 — normalised via compat ---

    @pytest.mark.asyncio
    async def test_v2_message_normalised_via_compat(self, bridge):
        """AIP/2.0 messages (version='2.0') are accepted and normalised to v3."""
        ws = _make_ws()
        v2_msg = {
            "version": "2.0",
            "type": "device_register",
            "device_id": "prs2-v2-001",
            "message_id": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "platform": "android",
        }
        response = await bridge.handle_message(ws, v2_msg)
        assert response is not None
        assert response["type"] == "device_register_ack"

    @pytest.mark.asyncio
    async def test_v2_normalised_version_field(self):
        """normalise_to_v3_dict converts AIP/2.0 version to '3.0'."""
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict

        v2_input = {
            "version": "2.0",
            "type": "heartbeat",
            "device_id": "prs2-v2-ver",
        }
        normalised = normalise_to_v3_dict(v2_input)
        assert normalised["version"] == "3.0"
        assert normalised["type"] == "heartbeat"

    # --- 5.4  Extra fields preserved after normalisation ---

    def test_normalise_to_v3_dict_preserves_extra_fields(self):
        """
        normalise_to_v3_dict must keep extra top-level fields (platform, model,
        os_version, supported_actions) so that downstream handlers like
        AndroidDevice.from_registration() can read them.
        """
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict

        raw = {
            "type": "register",
            "device_id": "prs2-extra-001",
            "platform": "android",
            "model": "Pixel 9",
            "os_version": "14",
            "supported_actions": ["tap", "screenshot"],
        }
        normalised = normalise_to_v3_dict(raw)

        assert normalised["version"] == "3.0"
        assert normalised["type"] == "device_register"
        assert normalised["platform"] == "android"
        assert normalised["model"] == "Pixel 9"
        assert normalised["os_version"] == "14"
        assert normalised["supported_actions"] == ["tap", "screenshot"]

    def test_normalise_to_v3_dict_v3_passthrough_preserves_extra(self):
        """v3 messages pass through normalise_to_v3_dict with extra fields intact."""
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict

        raw = {
            "version": "3.0",
            "type": "device_register",
            "device_id": "prs2-v3-extra",
            "platform": "android",
            "model": "Pixel 8",
        }
        normalised = normalise_to_v3_dict(raw)
        assert normalised["version"] == "3.0"
        assert normalised["platform"] == "android"
        assert normalised["model"] == "Pixel 8"

    # --- 5.5  v3 schema enforcement: all 5 canonical type names ---

    @pytest.mark.asyncio
    @pytest.mark.parametrize("msg_type,expected_response_type", [
        ("device_register", "device_register_ack"),
        ("heartbeat", "heartbeat_ack"),
        ("capability_report", "capability_report_ack"),
    ])
    async def test_v3_canonical_types_processed(
        self, bridge, fresh_registry, msg_type, expected_response_type
    ):
        """Downstream handlers expect canonical v3 type names."""
        ws = _make_ws()
        device_id = f"prs2-canon-{msg_type.replace('_', '-')}"
        # Pre-register for heartbeat/capability_report tests
        if msg_type != "device_register":
            await bridge.handle_message(ws, _v3_msg("device_register", device_id))
        msg = _v3_msg(msg_type, device_id, supported_actions=["tap"])
        response = await bridge.handle_message(ws, msg)
        assert response is not None
        assert response["type"] == expected_response_type
