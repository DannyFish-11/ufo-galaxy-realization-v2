"""
tests/test_device_registration.py
==================================

Tests for the device registration fix (Pydantic AIPMessage validation).

Coverage:
  a) register_device accepts legacy ``message_type`` input and maps it to
     the canonical ``type`` field via ``normalise_legacy_payload()``.
  b) The REST API returns HTTP 400 when ``device_id`` is missing / empty.
  c) ``galaxy_core.GalaxyCore.register_device`` succeeds with a full payload.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def devices_client():
    """TestClient backed by the devices sub-router."""
    from core.routes.devices import create_router
    app = FastAPI()
    router = create_router()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# =============================================================================
# a) normalise_legacy_payload: message_type → type mapping
# =============================================================================

class TestNormaliseLegacyPayload:
    """Unit tests for the ``normalise_legacy_payload`` helper."""

    def test_message_type_promoted_to_type(self):
        """A payload with only ``message_type`` gets ``type`` set correctly."""
        from galaxy_gateway.protocol.compat import normalise_legacy_payload
        from galaxy_gateway.protocol.aip_v3 import MessageType

        raw = {
            "message_type": MessageType.DEVICE_REGISTER,
            "device_id": "test-device-01",
            "timestamp": "2026-03-15T13:06:31.417410",
        }
        result = normalise_legacy_payload(raw)
        assert result["type"] == MessageType.DEVICE_REGISTER.value
        # original dict is not mutated
        assert "type" not in raw

    def test_type_not_overwritten_when_already_present(self):
        """Existing ``type`` must not be overwritten."""
        from galaxy_gateway.protocol.compat import normalise_legacy_payload
        from galaxy_gateway.protocol.aip_v3 import MessageType

        raw = {
            "type": MessageType.DEVICE_HEARTBEAT.value,
            "message_type": MessageType.DEVICE_REGISTER.value,
            "device_id": "d",
        }
        result = normalise_legacy_payload(raw)
        assert result["type"] == MessageType.DEVICE_HEARTBEAT.value

    def test_device_id_promoted_from_payload(self):
        """When top-level ``device_id`` is absent, it is pulled from ``payload``."""
        from galaxy_gateway.protocol.compat import normalise_legacy_payload
        from galaxy_gateway.protocol.aip_v3 import MessageType

        raw = {
            "type": MessageType.DEVICE_REGISTER.value,
            "payload": {"device_id": "device-from-payload"},
        }
        result = normalise_legacy_payload(raw)
        assert result["device_id"] == "device-from-payload"

    def test_device_id_not_overwritten_when_already_present(self):
        """Existing top-level ``device_id`` must not be overwritten."""
        from galaxy_gateway.protocol.compat import normalise_legacy_payload
        from galaxy_gateway.protocol.aip_v3 import MessageType

        raw = {
            "type": MessageType.DEVICE_REGISTER.value,
            "device_id": "top-level-id",
            "payload": {"device_id": "payload-id"},
        }
        result = normalise_legacy_payload(raw)
        assert result["device_id"] == "top-level-id"

    def test_full_legacy_dict_parsed_to_aip_message(self):
        """After normalisation a legacy dict should be parseable as AIPMessage."""
        from galaxy_gateway.protocol.compat import normalise_legacy_payload
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType

        raw = {
            "message_type": MessageType.DEVICE_REGISTER,
            "payload": {"device_id": "legacy-device"},
        }
        normalised = normalise_legacy_payload(raw)
        msg = AIPMessage(**normalised)
        assert msg.type == MessageType.DEVICE_REGISTER
        assert msg.device_id == "legacy-device"


# =============================================================================
# b) API validation: missing / empty device_id returns 4xx
# =============================================================================

class TestAPIDeviceRegistrationValidation:
    """REST API-level validation for device registration."""

    def test_missing_device_id_returns_422(self, devices_client):
        """Omitting ``device_id`` entirely should return HTTP 422 (Pydantic)."""
        r = devices_client.post(
            "/api/v1/devices/register",
            json={"device_type": "android"},
        )
        assert r.status_code == 422

    def test_empty_device_id_returns_400(self, devices_client):
        """Supplying an empty string for ``device_id`` should return HTTP 400."""
        r = devices_client.post(
            "/api/v1/devices/register",
            json={"device_id": "", "device_type": "android"},
        )
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "device_id" in detail.lower()

    def test_whitespace_only_device_id_returns_400(self, devices_client):
        """A whitespace-only ``device_id`` should also return HTTP 400."""
        r = devices_client.post(
            "/api/v1/devices/register",
            json={"device_id": "   ", "device_type": "android"},
        )
        assert r.status_code == 400


# =============================================================================
# c) GalaxyCore.register_device succeeds with a full payload
# =============================================================================

class TestGalaxyCoreRegisterDevice:
    """Integration tests for GalaxyCore.register_device."""

    def test_register_device_success(self):
        """register_device with a full payload must not raise and must return
        success=True."""
        import asyncio
        from core.galaxy_core import GalaxyCore

        core = GalaxyCore()
        device_id = f"pytest-{uuid.uuid4().hex[:8]}"
        result = asyncio.run(
            core.register_device(
                device_id=device_id,
                device_type="android",
                name="Test Device",
                endpoint="ws://127.0.0.1:9000",
            )
        )
        assert result["success"] is True
        assert result["device_id"] == device_id

    def test_register_device_stored_in_devices(self):
        """After registration the device should appear in core.devices."""
        import asyncio
        from core.galaxy_core import GalaxyCore

        core = GalaxyCore()
        device_id = f"pytest-{uuid.uuid4().hex[:8]}"
        asyncio.run(
            core.register_device(
                device_id=device_id,
                device_type="windows",
                name="Win Desktop",
            )
        )
        assert device_id in core.devices
        assert core.devices[device_id]["device_type"] == "windows"
