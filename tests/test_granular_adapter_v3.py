"""
tests/test_granular_adapter_v3.py
==================================

Tests for PR-S3 "GranularAdapter v3-only" contract.

1. Native AIP v3 payloads flow through the adapter successfully.
2. Legacy (v1/v2) payloads are normalised through compat *first*, then
   accepted by the adapter as v3 AIPMessage objects.
3. Raw legacy payloads sent *directly* to the adapter (bypassing compat)
   are rejected with :class:`AIPAdapterVersionError`.
4. Downstream business logic sees v3-normalised fields; no v2 fallbacks.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from galaxy_gateway.android_granular_adapter import (
    AndroidGranularAdapter,
    AIPAdapterVersionError,
)
from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
from galaxy_gateway.protocol.compat import parse_message_compat


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_adb():
    """Return a mock ADB executor whose shell/pull/install are all AsyncMocks."""
    adb = MagicMock()
    adb.shell = AsyncMock(return_value="ok")
    adb.pull = AsyncMock(return_value="ok")
    adb.install = AsyncMock(return_value="ok")
    return adb


@pytest.fixture()
def adapter(mock_adb):
    """Return a ready AndroidGranularAdapter backed by a mock ADB executor."""
    return AndroidGranularAdapter(mock_adb)


DEVICE_ID = "test-device-001"


# ---------------------------------------------------------------------------
# 1. Native v3 payloads flow through the adapter successfully
# ---------------------------------------------------------------------------


class TestV3NativeFlow:
    """AIP v3 AIPMessage objects must be dispatched without error."""

    @pytest.mark.asyncio
    async def test_v3_command_click_dispatched(self, adapter):
        """v3 COMMAND message with click payload is dispatched successfully."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND,
            device_id=DEVICE_ID,
            payload={"command": "click", "params": {"x": 100, "y": 200}},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert result is not None
        assert result.type == MessageType.COMMAND_RESULT
        assert result.payload["success"] is True

    @pytest.mark.asyncio
    async def test_v3_device_register_dispatched(self, adapter):
        """v3 DEVICE_REGISTER message is dispatched (falls through to extended)."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.DEVICE_REGISTER,
            device_id=DEVICE_ID,
        )
        # Verify no AIPAdapterVersionError is raised for a valid v3 message.
        # The adapter may return any AIPMessage (success or error) for this type.
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v3_heartbeat_dispatched(self, adapter):
        """v3 DEVICE_HEARTBEAT message does not raise AIPAdapterVersionError."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.DEVICE_HEARTBEAT,
            device_id=DEVICE_ID,
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v3_capability_report_dispatched(self, adapter):
        """v3 CAPABILITY_REPORT message does not raise AIPAdapterVersionError."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.CAPABILITY_REPORT,
            device_id=DEVICE_ID,
            payload={"platform": "android", "supported_actions": ["click"], "version": "3.0"},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v3_task_assign_dispatched(self, adapter):
        """v3 TASK_ASSIGN message does not raise AIPAdapterVersionError."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.TASK_ASSIGN,
            device_id=DEVICE_ID,
            payload={"task_id": "t-001", "action": "screenshot"},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v3_command_result_dispatched(self, adapter):
        """v3 COMMAND_RESULT message does not raise AIPAdapterVersionError."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND_RESULT,
            device_id=DEVICE_ID,
            payload={"success": True, "output": "done"},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v3_screenshot_command_returns_base64_or_note(self, adapter, mock_adb):
        """v3 COMMAND/screenshot sets up the correct adb calls."""
        mock_adb.shell = AsyncMock(return_value="ok")
        mock_adb.pull = AsyncMock(return_value="ok")
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND,
            device_id=DEVICE_ID,
            payload={"command": "screenshot", "params": {}},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert result is not None
        assert result.type == MessageType.COMMAND_RESULT
        # Either image_base64 or a note key is present (file may not exist in test env)
        assert "image_base64" in result.payload or "note" in result.payload

    @pytest.mark.asyncio
    async def test_v3_gui_click_dispatched(self, adapter):
        """v3 GUI_CLICK message is dispatched via extended handler."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.GUI_CLICK,
            device_id=DEVICE_ID,
            payload={"x": 50, "y": 75},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert result is not None
        assert result.type == MessageType.COMMAND_RESULT
        assert result.payload["success"] is True

    @pytest.mark.asyncio
    async def test_response_carries_v3_message_type(self, adapter):
        """Success responses use v3 MessageType.COMMAND_RESULT, not a v2 type."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND,
            device_id=DEVICE_ID,
            payload={"command": "home", "params": {}},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert result.type == MessageType.COMMAND_RESULT

    @pytest.mark.asyncio
    async def test_error_response_carries_v3_error_type(self, adapter):
        """Error responses use v3 MessageType.ERROR."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND,
            device_id=DEVICE_ID,
            payload={"command": "nonexistent_command_xyz", "params": {}},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert result is not None
        assert result.type == MessageType.ERROR
        assert result.payload["success"] is False


# ---------------------------------------------------------------------------
# 2. Legacy → compat → adapter flow
# ---------------------------------------------------------------------------


class TestLegacyViaCompatFlow:
    """Legacy (v1/v2) messages normalised through compat are accepted."""

    @pytest.mark.asyncio
    async def test_v1_register_via_compat_then_adapter(self, adapter):
        """AIP/1.0 'register' is first normalised by compat, then accepted."""
        raw = {"type": "register", "device_id": "legacy-001"}
        msg = parse_message_compat(raw)
        # Verify compat produces a v3 AIPMessage before it reaches the adapter.
        assert msg.version.startswith("3")
        assert msg.type == MessageType.DEVICE_REGISTER
        # Adapter must accept the compat-normalised message without error
        result = await adapter.dispatch_aip_message("legacy-001", msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v1_heartbeat_via_compat_then_adapter(self, adapter):
        """AIP/1.0 'heartbeat' flows compat → adapter without error."""
        raw = {"type": "heartbeat", "device_id": "legacy-002"}
        msg = parse_message_compat(raw)
        assert msg.version.startswith("3")
        result = await adapter.dispatch_aip_message("legacy-002", msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v1_command_result_via_compat_then_adapter(self, adapter):
        """AIP/1.0 'command_result' maps to TASK_RESULT via compat then adapter."""
        raw = {"type": "command_result", "device_id": "legacy-003", "payload": {"output": "done"}}
        msg = parse_message_compat(raw)
        assert msg.version.startswith("3")
        assert msg.type == MessageType.TASK_RESULT
        result = await adapter.dispatch_aip_message("legacy-003", msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v2_device_register_via_compat_then_adapter(self, adapter):
        """AIP/2.0 device_register is bumped to v3 by compat, then adapter."""
        raw = {
            "version": "2.0",
            "type": "device_register",
            "device_id": "v2-dev-001",
        }
        msg = parse_message_compat(raw)
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_REGISTER
        result = await adapter.dispatch_aip_message("v2-dev-001", msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v2_heartbeat_via_compat_then_adapter(self, adapter):
        """AIP/2.0 heartbeat is bumped to v3 by compat, then adapter."""
        raw = {"version": "2.0", "type": "heartbeat", "device_id": "v2-dev-002"}
        msg = parse_message_compat(raw)
        assert msg.version == "3.0"
        result = await adapter.dispatch_aip_message("v2-dev-002", msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v1_task_execute_via_compat_maps_to_task_submit(self, adapter):
        """AIP/1.0 'task_execute' is mapped to TASK_SUBMIT by compat."""
        raw = {"type": "task_execute", "device_id": "legacy-004"}
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.TASK_SUBMIT
        result = await adapter.dispatch_aip_message("legacy-004", msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v1_status_update_via_compat_maps_to_device_status(self, adapter):
        """AIP/1.0 'status_update' → DEVICE_STATUS via compat, then adapter."""
        raw = {"type": "status_update", "device_id": "legacy-005"}
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.DEVICE_STATUS
        result = await adapter.dispatch_aip_message("legacy-005", msg)
        assert isinstance(result, AIPMessage)


# ---------------------------------------------------------------------------
# 3. Direct legacy payload to adapter must be rejected
# ---------------------------------------------------------------------------


class TestDirectLegacyRejected:
    """AIPMessage objects with version < 3.0 must be rejected by the adapter."""

    @pytest.mark.asyncio
    async def test_version_2_message_rejected(self, adapter):
        """AIPMessage(version='2.0') passed directly raises AIPAdapterVersionError."""
        msg = AIPMessage(
            version="2.0",
            type=MessageType.DEVICE_REGISTER,
            device_id="bad-dev",
        )
        with pytest.raises(AIPAdapterVersionError, match="v3-only"):
            await adapter.dispatch_aip_message("bad-dev", msg)

    @pytest.mark.asyncio
    async def test_version_1_message_rejected(self, adapter):
        """AIPMessage(version='1.0') passed directly raises AIPAdapterVersionError."""
        msg = AIPMessage(
            version="1.0",
            type=MessageType.DEVICE_HEARTBEAT,
            device_id="bad-dev-v1",
        )
        with pytest.raises(AIPAdapterVersionError, match="v3-only"):
            await adapter.dispatch_aip_message("bad-dev-v1", msg)

    @pytest.mark.asyncio
    async def test_empty_version_rejected(self, adapter):
        """AIPMessage with empty version string is rejected."""
        msg = AIPMessage(
            version="",
            type=MessageType.COMMAND,
            device_id="bad-dev-empty",
            payload={"command": "click", "params": {}},
        )
        with pytest.raises(AIPAdapterVersionError, match="v3-only"):
            await adapter.dispatch_aip_message("bad-dev-empty", msg)

    @pytest.mark.asyncio
    async def test_error_message_names_parse_message_compat(self, adapter):
        """The rejection error message tells the caller to use parse_message_compat."""
        msg = AIPMessage(
            version="2.0",
            type=MessageType.DEVICE_REGISTER,
            device_id="bad-dev",
        )
        with pytest.raises(AIPAdapterVersionError) as exc_info:
            await adapter.dispatch_aip_message("bad-dev", msg)
        assert "parse_message_compat" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_v3_version_accepted(self, adapter):
        """Sanity check: version='3.0' is accepted (no error raised)."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.DEVICE_REGISTER,
            device_id="ok-dev",
        )
        # Must not raise AIPAdapterVersionError for a valid v3 message.
        result = await adapter.dispatch_aip_message("ok-dev", msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_v3_minor_version_accepted(self, adapter):
        """version='3.1' (a future minor v3) is also accepted."""
        msg = AIPMessage(
            version="3.1",
            type=MessageType.DEVICE_REGISTER,
            device_id="ok-dev-31",
        )
        result = await adapter.dispatch_aip_message("ok-dev-31", msg)
        assert isinstance(result, AIPMessage)


# ---------------------------------------------------------------------------
# 4. Downstream business logic uses v3-normalised fields (no v2 fallbacks)
# ---------------------------------------------------------------------------


class TestDownstreamV3Fields:
    """Adapter output must use v3 field names and MessageType values."""

    @pytest.mark.asyncio
    async def test_success_response_has_no_legacy_type(self, adapter):
        """COMMAND_RESULT type value must be the v3 string, not a legacy alias."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND,
            device_id=DEVICE_ID,
            payload={"command": "back", "params": {}},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        # v3 type value must be used
        assert result.type.value == "command_result"

    @pytest.mark.asyncio
    async def test_error_response_type_is_v3_error(self, adapter):
        """Error response type value must be v3 'error', not a legacy string."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND,
            device_id=DEVICE_ID,
            payload={"command": "unknown_xyz", "params": {}},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert result.type.value == "error"

    @pytest.mark.asyncio
    async def test_correlation_id_propagated(self, adapter):
        """Response correlation_id must match the original message_id."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND,
            device_id=DEVICE_ID,
            payload={"command": "home", "params": {}},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert result.correlation_id == msg.message_id

    @pytest.mark.asyncio
    async def test_device_id_preserved_in_response(self, adapter):
        """Response device_id must match the original device_id."""
        msg = AIPMessage(
            version="3.0",
            type=MessageType.COMMAND,
            device_id=DEVICE_ID,
            payload={"command": "volume_up", "params": {}},
        )
        result = await adapter.dispatch_aip_message(DEVICE_ID, msg)
        assert result.device_id == DEVICE_ID
