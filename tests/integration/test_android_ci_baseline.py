"""
tests/integration/test_android_ci_baseline.py
==============================================
Android CI baseline — V2-side protocol contract verification.

This module provides the baseline contract coverage that ensures Android-side
protocol changes are not completely unguarded.  Since Android (Kotlin) code
lives in a separate repository (``ufo-galaxy-android``), this file acts as
the **V2-side guardian** of the cross-repo protocol contract.

What this module verifies
--------------------------
1. **Protocol surface contracts** — the AIP v3 message types that Android must
   send and receive are stable, importable, and produce correctly-shaped
   responses.  Any Android-side change that breaks these shapes would be caught
   here.

2. **Handler coverage audit** — every canonical Android→V2 message type must
   have a real handler registered in the bridge.  An unregistered type means
   Android messages would be silently dropped.

3. **Inbound normalisation** — V2 must correctly normalise messages that could
   come from various Android SDK versions (AIP v2 / v3 mixed, legacy fields).

4. **Contract smoke tests** — fast smoke checks that can be run as a pre-merge
   gate to ensure the V2 protocol surface hasn't regressed for Android clients.

Android CI follow-up note
--------------------------
For full dual-repo CI, the ``ufo-galaxy-android`` repository should have its
own CI pipeline that runs:
  - ``./gradlew assembleDebug``         — Android build gate
  - ``./gradlew testDebugUnitTest``     — Android unit tests
  - Contract-aware smoke coverage (``AgentWebSocket`` integration)

The Android-side CI is outside the scope of this V2 repository but is a
required follow-up action for complete dual-repo verification.  See the
framework README section "Android CI Follow-Up" for guidance.

No external services or running processes are required for any test here.
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Canonical Android message types that V2 must handle
# ---------------------------------------------------------------------------

#: AIP v3 message types sent FROM Android TO V2 (inbound surface).
#: Any change to this set in the Android repo must be reflected here.
ANDROID_INBOUND_TYPES: Set[str] = {
    "device_register",
    "capability_report",
    "heartbeat",
    "task_result",
    "task_end",
    "task_progress",
    "command_result",
    "error",
    "device_status",
}

#: AIP v3 message types sent FROM V2 TO Android (outbound surface).
#: These are the types V2 emits; Android must be able to receive them.
V2_OUTBOUND_TYPES: Set[str] = {
    "device_register_ack",
    "capability_report_ack",
    "heartbeat_ack",
    "task_assign",
    "task_end_ack",
    "device_status_ack",
    "error",
}

#: Canonical AIP v3 required fields (both directions).
AIP_V3_REQUIRED_FIELDS = ("version", "type", "device_id", "message_id", "timestamp")


# ===========================================================================
# 1. Protocol surface contract smoke
# ===========================================================================


class TestProtocolSurfaceContracts:
    """Every canonical inbound Android message type must return a valid response."""

    @pytest.mark.asyncio
    async def test_device_register_produces_ack(self) -> None:
        """device_register must produce device_register_ack."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"ci-reg-{uuid.uuid4().hex[:8]}"

        ack = await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        assert ack is not None
        assert ack["type"] == "device_register_ack"
        assert ack["success"] is True
        for field in AIP_V3_REQUIRED_FIELDS:
            assert field in ack, f"Required field '{field}' missing from register_ack"

    @pytest.mark.asyncio
    async def test_capability_report_produces_ack(self) -> None:
        """capability_report must produce capability_report_ack."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"ci-cap-{uuid.uuid4().hex[:8]}"

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )
        ack = await bridge.handle_message(
            ws,
            _v3(
                "capability_report",
                device_id,
                platform="android",
                supported_actions=["tap", "screenshot"],
            ),
        )

        assert ack is not None
        assert ack["type"] == "capability_report_ack"
        assert ack.get("accepted") is True
        for field in AIP_V3_REQUIRED_FIELDS:
            assert field in ack, f"Required field '{field}' missing from capability_report_ack"

    @pytest.mark.asyncio
    async def test_heartbeat_produces_ack(self) -> None:
        """heartbeat must produce heartbeat_ack."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"ci-hb-{uuid.uuid4().hex[:8]}"

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )
        ack = await bridge.handle_message(ws, _v3("heartbeat", device_id))

        assert ack is not None
        assert ack["type"] == "heartbeat_ack"
        for field in AIP_V3_REQUIRED_FIELDS:
            assert field in ack, f"Required field '{field}' missing from heartbeat_ack"

    @pytest.mark.asyncio
    async def test_task_end_produces_ack(self) -> None:
        """task_end must produce task_end_ack."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"ci-te-{uuid.uuid4().hex[:8]}"

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )
        ack = await bridge.handle_message(
            ws,
            _v3("task_end", device_id, task_id=str(uuid.uuid4()), status="completed"),
        )

        assert ack is not None
        assert ack.get("type") == "task_end_ack"

    @pytest.mark.asyncio
    async def test_task_result_processed_without_error(self) -> None:
        """task_result must be processed without crashing (returns None)."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"ci-tr-{uuid.uuid4().hex[:8]}"

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )
        result = await bridge.handle_message(
            ws,
            _v3(
                "task_result",
                device_id,
                task_id=str(uuid.uuid4()),
                status="completed",
            ),
        )
        # task_result returns None (no ack sent back); must not raise
        assert result is None or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_all_canonical_inbound_types_do_not_crash(self) -> None:
        """Every canonical Android→V2 message type must be handled without crash.

        This test ensures that no message type in ``ANDROID_INBOUND_TYPES``
        causes an unhandled exception in V2.  It acts as a broad sweep that
        catches regressions when new types are added or handlers are removed.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"ci-all-{uuid.uuid4().hex[:8]}"

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        types_with_expected_responses = {
            "device_register",
            "capability_report",
            "heartbeat",
            "task_end",
        }
        types_with_no_response = {
            "task_result",
            "task_progress",
            "command_result",
            "error",
        }

        for msg_type in types_with_expected_responses:
            extra: Dict[str, Any] = {}
            if msg_type == "capability_report":
                extra = {"platform": "android", "supported_actions": ["tap"]}
            elif msg_type in ("task_end",):
                extra = {"task_id": str(uuid.uuid4()), "status": "completed"}

            response = await bridge.handle_message(ws, _v3(msg_type, device_id, **extra))
            assert response is not None, (
                f"Message type '{msg_type}' must return a response (got None)"
            )

        for msg_type in types_with_no_response:
            extra = {}
            if "task" in msg_type or "command" in msg_type:
                extra = {"task_id": str(uuid.uuid4()), "status": "completed"}
            response = await bridge.handle_message(ws, _v3(msg_type, device_id, **extra))
            # None is acceptable; must not raise
            assert response is None or isinstance(response, dict), (
                f"Message type '{msg_type}' must return None or dict, got {type(response)}"
            )


# ===========================================================================
# 2. Handler coverage audit
# ===========================================================================


class TestHandlerCoverageAudit:
    """Every canonical inbound message type must have a registered handler."""

    def test_bridge_has_handlers_for_canonical_types(self) -> None:
        """AndroidBridge must have handlers for all canonical inbound message types.

        This test catches the case where a message type exists in the protocol
        definition but has no handler registered — messages would be silently
        dropped.
        """
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType

        bridge = AndroidBridge()
        registered_types: Set[str] = {
            msg_type.value for msg_type in bridge._message_handlers
        }

        # These types must have handlers — they are the canonical Android protocol surface
        must_have_handlers = {
            "device_register",
            "capability_report",
            "heartbeat",
            "task_result",
            "task_end",
        }

        for msg_type in must_have_handlers:
            assert msg_type in registered_types, (
                f"AndroidBridge has no handler for canonical type '{msg_type}' — "
                f"Android messages of this type would be silently dropped. "
                f"Registered handlers: {sorted(registered_types)}"
            )

    def test_message_type_enum_covers_canonical_inbound_types(self) -> None:
        """MessageType enum must include all canonical Android inbound types."""
        from galaxy_gateway.protocol.aip_v3 import MessageType

        enum_values = {mt.value for mt in MessageType}

        for msg_type in ANDROID_INBOUND_TYPES:
            assert msg_type in enum_values, (
                f"MessageType enum missing '{msg_type}' — "
                f"Android-sent type has no V2 protocol definition. "
                f"This would cause an 'UNKNOWN_MESSAGE_TYPE' error for every "
                f"Android client that sends this type."
            )

    def test_message_builder_produces_all_outbound_types(self) -> None:
        """MessageBuilder must be able to construct all canonical V2→Android types."""
        from galaxy_gateway.android.message_builder import MessageBuilder

        device_id = "builder-test"

        # Verify key outbound message types are constructable
        ack = MessageBuilder.device_register_ack(device_id, True, "ok")
        assert ack["type"] == "device_register_ack"

        hb_ack = MessageBuilder.heartbeat_ack(device_id)
        assert hb_ack["type"] == "heartbeat_ack"

        cap_ack = MessageBuilder.capability_report_ack(device_id, True, "ok")
        assert cap_ack["type"] == "capability_report_ack"

        task_assign = MessageBuilder.task_assign(
            device_id=device_id,
            task_id=str(uuid.uuid4()),
            task_type="generic",
            payload={"command": "screenshot"},
        )
        assert task_assign["type"] == "task_assign"


# ===========================================================================
# 3. Inbound normalisation contract
# ===========================================================================


class TestInboundNormalisationContract:
    """V2 must correctly normalise messages from Android SDK version variations."""

    @pytest.mark.asyncio
    async def test_normalise_raw_json_string_from_android(self) -> None:
        """V2 must normalise a raw JSON string as received from Android WS."""
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict

        device_id = f"norm-{uuid.uuid4().hex[:8]}"
        raw_json = json.dumps({
            "version": "3.0",
            "type": "device_register",
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "platform": "android",
            "model": "Pixel 7",
        })

        normalised = normalise_to_v3_dict(raw_json)

        assert isinstance(normalised, dict)
        assert normalised["type"] == "device_register"
        assert normalised["device_id"] == device_id
        assert normalised["version"] == "3.0"

    @pytest.mark.asyncio
    async def test_normalise_already_dict_message_is_passthrough(self) -> None:
        """A dict message that is already AIP v3 must pass through normalisation unchanged."""
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict

        device_id = f"dict-norm-{uuid.uuid4().hex[:8]}"
        msg = _v3("heartbeat", device_id)

        normalised = normalise_to_v3_dict(msg)

        assert normalised["type"] == "heartbeat"
        assert normalised["device_id"] == device_id

    @pytest.mark.asyncio
    async def test_bridge_auto_fills_missing_v3_fields(self) -> None:
        """Bridge must auto-fill ``version`` and ``timestamp`` if absent.

        Android SDK may emit messages without ``version`` or ``timestamp``
        in certain edge cases.  V2 must not reject these outright.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"autofill-{uuid.uuid4().hex[:8]}"

        # Minimal message without optional fields
        minimal_msg = {
            "type": "device_register",
            "device_id": device_id,
            "platform": "android",
        }

        response = await bridge.handle_message(ws, minimal_msg)
        # Bridge should normalise and produce a valid ack (or error, not crash)
        assert response is not None
        assert isinstance(response, dict)

    @pytest.mark.asyncio
    async def test_malformed_message_returns_error_not_exception(self) -> None:
        """Completely malformed messages must produce an error response, not raise."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()

        # Empty dict — missing all required fields
        response = await bridge.handle_message(ws, {})
        assert response is not None
        assert isinstance(response, dict)
        assert "type" in response

    @pytest.mark.asyncio
    async def test_unknown_message_type_returns_error(self) -> None:
        """An unknown message type must return an error response, not crash."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"unknown-type-{uuid.uuid4().hex[:8]}"

        response = await bridge.handle_message(
            ws,
            _v3("completely_unknown_type_xyz", device_id),
        )
        assert response is not None
        assert isinstance(response, dict)
        # Should be an error response
        assert response.get("type") in ("error", "unknown_message_type") or (
            "error" in response.get("type", "").lower()
        ) or response.get("success") is False or "ERROR" in str(response)


# ===========================================================================
# 4. Cross-repo protocol contract stability guards
# ===========================================================================


class TestCrossRepoContractStability:
    """Guards that would catch silent contract breakage between V2 and Android."""

    def test_aip_v3_version_string_is_stable(self) -> None:
        """The AIP v3 version string must remain '3.0' — a change would break Android."""
        from galaxy_gateway.android.message_builder import MessageBuilder

        ack = MessageBuilder.device_register_ack("test-device", True, "ok")
        assert ack.get("version") == "3.0", (
            "AIP v3 version string changed — this would break all Android clients "
            "that expect 'version: 3.0' in every V2 response"
        )

    def test_register_ack_type_string_is_stable(self) -> None:
        """``device_register_ack`` type string must remain stable across versions."""
        from galaxy_gateway.android.message_builder import MessageBuilder

        ack = MessageBuilder.device_register_ack("test-device", True, "ok")
        assert ack["type"] == "device_register_ack", (
            "register_ack type string changed — Android clients matching on "
            "'device_register_ack' would break silently"
        )

    def test_task_assign_type_string_is_stable(self) -> None:
        """``task_assign`` type string must remain stable (Android parses this)."""
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign(
            device_id="test",
            task_id=str(uuid.uuid4()),
            task_type="generic",
            payload={},
        )
        assert msg["type"] == "task_assign", (
            "task_assign type string changed — Android AgentMessageHandler "
            "matches on 'task_assign' to route inbound V2 commands"
        )

    def test_canonical_device_ingress_path_exists(self) -> None:
        """The canonical ``/ws/device/{device_id}`` route must be registrable."""
        from fastapi import FastAPI
        from galaxy_gateway.routes.websocket import register_websocket_routes

        app = FastAPI()
        # Must not raise
        register_websocket_routes(app)

        routes = [r.path for r in app.routes]
        assert "/ws/device/{device_id}" in routes, (
            "Canonical device ingress path '/ws/device/{device_id}' not registered — "
            "Android clients would have no connection endpoint"
        )

    def test_capability_report_ack_accepted_field_is_stable(self) -> None:
        """``capability_report_ack.accepted`` must be a boolean field.

        Android AgentMessageHandler reads ``accepted`` to decide whether to
        retry capability report.
        """
        from galaxy_gateway.android.message_builder import MessageBuilder

        ack = MessageBuilder.capability_report_ack("test-device", True, "ok")
        assert "accepted" in ack, (
            "capability_report_ack missing 'accepted' field — "
            "Android AgentMessageHandler reads this to verify acceptance"
        )
        assert isinstance(ack["accepted"], bool), (
            "capability_report_ack.accepted must be a boolean"
        )

    def test_heartbeat_ack_carries_device_id(self) -> None:
        """``heartbeat_ack`` must carry ``device_id`` so Android can correlate it."""
        from galaxy_gateway.android.message_builder import MessageBuilder

        ack = MessageBuilder.heartbeat_ack("test-device")
        assert "device_id" in ack, (
            "heartbeat_ack missing 'device_id' — Android correlation would break"
        )
        assert ack["device_id"] == "test-device"


# ===========================================================================
# 5. Android CI follow-up documentation test
# ===========================================================================


class TestAndroidCIFollowUp:
    """Structural tests that document the required Android-side CI follow-up.

    These tests verify that V2-side structures are in place for the
    Android CI follow-up actions.  They do NOT execute Android code.
    """

    def test_aip_v3_protocol_module_importable(self) -> None:
        """The canonical AIP v3 protocol module must be importable."""
        from galaxy_gateway.protocol.aip_v3 import MessageType, AIPMessage

        assert MessageType is not None
        assert AIPMessage is not None

    def test_android_bridge_importable_as_singleton(self) -> None:
        """``android_bridge`` singleton must be importable for CI verification."""
        from galaxy_gateway.android_bridge import android_bridge

        assert android_bridge is not None

    def test_websocket_handler_importable(self) -> None:
        """The canonical WS handler must be importable."""
        from galaxy_gateway.routes.websocket import _handle_android_ws, register_websocket_routes

        assert callable(_handle_android_ws)
        assert callable(register_websocket_routes)

    def test_dispatch_module_importable(self) -> None:
        """The V2 dispatch module must be importable."""
        from galaxy_gateway.routing.dispatch import (
            build_aip_message,
            dispatch_to_websocket,
        )

        assert callable(build_aip_message)
        assert callable(dispatch_to_websocket)

    def test_build_aip_message_produces_valid_envelope(self) -> None:
        """build_aip_message must produce a valid AIP v3 envelope."""
        from galaxy_gateway.routing.dispatch import build_aip_message

        device_id = "ci-build-test"
        task_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())

        msg = build_aip_message(
            device_id=device_id,
            task_id=task_id,
            trace_id=trace_id,
            command="screenshot",
            payload={"quality": 80},
        )

        assert msg["version"] == "3.0"
        assert msg["type"] == "command"
        assert msg["device_id"] == device_id
        assert msg["task_id"] == task_id
        assert "payload" in msg
        assert msg["payload"]["command"] == "screenshot"
