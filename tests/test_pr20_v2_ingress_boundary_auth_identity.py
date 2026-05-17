from __future__ import annotations

import time
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _v3(msg_type: str, device_id: str, **extra: Any) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


@pytest.fixture()
def bridge():
    from galaxy_gateway.android_bridge import AndroidBridge

    return AndroidBridge()


@pytest.mark.asyncio
async def test_register_ack_explicitly_distinguishes_auth_registration_and_participation(
    bridge, monkeypatch
):
    monkeypatch.delenv("GALAXY_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)
    monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)

    resp = await bridge.handle_message(
        _make_ws(),
        _v3("device_register", "pr20-ingress-a"),
    )

    assert resp["type"] == "device_register_ack"
    assert resp["success"] is True
    assert resp["connection_accepted"] is True
    assert resp["registration_success"] is True
    assert resp["participation_eligible"] is False
    assert resp["authentication_enforced"] is False
    assert "ingress_boundary" in resp
    assert resp["ingress_boundary"]["registration"]["success"] is True


@pytest.mark.asyncio
async def test_register_rejects_ingress_identity_mismatch(bridge, monkeypatch):
    monkeypatch.delenv("GALAXY_AUTH_ENABLED", raising=False)

    resp = await bridge.handle_message(
        _make_ws(),
        _v3(
            "device_register",
            "payload-device-id",
            _ingress_connection_device_id="path-device-id",
        ),
    )

    assert resp["type"] == "device_register_ack"
    assert resp["success"] is False
    assert resp["error_code"] == "INGRESS_IDENTITY_MISMATCH"
    assert resp["registration_success"] is False
    assert resp["participation_eligible"] is False
    assert resp["ingress_boundary"]["identity"]["matched"] is False


@pytest.mark.asyncio
async def test_register_rejects_when_auth_enforced_without_token(bridge, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("GALAXY_API_TOKEN", "pr20-secret")
    monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
    monkeypatch.delenv("GALAXY_DEV_MODE", raising=False)

    resp = await bridge.handle_message(
        _make_ws(),
        _v3("device_register", "pr20-auth-missing"),
    )

    assert resp["success"] is False
    assert resp["error_code"] == "INGRESS_AUTHENTICATION_FAILED"
    assert resp["authentication_enforced"] is True
    assert resp["authentication_success"] is False
    assert resp["registration_success"] is False


@pytest.mark.asyncio
async def test_register_accepts_when_auth_enforced_and_token_valid(bridge, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("GALAXY_API_TOKEN", "pr20-secret")
    monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
    monkeypatch.delenv("GALAXY_DEV_MODE", raising=False)

    resp = await bridge.handle_message(
        _make_ws(),
        _v3("device_register", "pr20-auth-ok", token="pr20-secret"),
    )

    assert resp["success"] is True
    assert resp["authentication_enforced"] is True
    assert resp["authentication_success"] is True
    assert resp["identity_match_success"] is True
    assert resp["registration_success"] is True
