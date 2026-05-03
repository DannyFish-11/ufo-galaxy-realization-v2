"""PR-4B: Android runtime WS profile center-side alignment tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from galaxy_gateway.android.runtime_ws_profile import (
    ANDROID_RUNTIME_WS_PROFILE_AUTHORITY,
    ANDROID_RUNTIME_WS_PROFILE_PR4B_SENTINEL,
    classify_android_runtime_ws_mapping,
)
from galaxy_gateway.android_bridge import AndroidBridge, MessageType
from galaxy_gateway.protocol.ingress_classifier import (
    IngressMessageClass,
    classify_ingress_kind,
)
from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


def test_runtime_ws_profile_sentinels_exist() -> None:
    assert ANDROID_RUNTIME_WS_PROFILE_AUTHORITY.startswith("ANDROID_RUNTIME_WS_PROFILE_AUTHORITY::")
    assert ANDROID_RUNTIME_WS_PROFILE_PR4B_SENTINEL.startswith("ANDROID_RUNTIME_WS_PROFILE_PR4B_SENTINEL::")


def test_runtime_ws_profile_mapping_covers_transfer_and_mesh() -> None:
    delegated = classify_android_runtime_ws_mapping(MessageType.DELEGATED_EXECUTION_SIGNAL.value)
    mesh = classify_android_runtime_ws_mapping(MessageType.MESH_TOPOLOGY.value)
    transfer = classify_android_runtime_ws_mapping(MessageType.FILE_TRANSFER.value)

    assert delegated.semantic_family == "transfer_delegated_execution"
    assert delegated.handling_level == "canonical"
    assert mesh.semantic_family == "mesh_participation"
    assert mesh.handling_level == "compat-forwarded"
    assert transfer.semantic_family == "transfer_signal"
    assert transfer.handling_level == "compat-forwarded"


def test_normalized_ingress_kind_and_classifier_cover_runtime_ws_extensions() -> None:
    assert classify_ingress_kind(IngressEventKind.DELEGATED_EXECUTION_SIGNAL) == IngressMessageClass.EXECUTION
    assert classify_ingress_kind(IngressEventKind.FILE_TRANSFER) == IngressMessageClass.CONTROL
    assert classify_ingress_kind(IngressEventKind.MESH_TOPOLOGY) == IngressMessageClass.TRANSPORT
    assert classify_ingress_kind(IngressEventKind.AGENT_STATUS) == IngressMessageClass.PRESENCE


@pytest.mark.asyncio
async def test_bridge_handles_agent_status_mesh_and_transfer_signals_explicitly() -> None:
    bridge = AndroidBridge()
    ws = _make_ws()

    reg = {
        "type": MessageType.DEVICE_REGISTER.value,
        "device_id": "android-pr4b-001",
        "platform": "android",
        "version": "3.0",
    }
    await bridge.handle_message(ws, reg)

    agent_status = {
        "type": MessageType.AGENT_STATUS.value,
        "device_id": "android-pr4b-001",
        "status": {"readiness": "ready", "posture": "foreground"},
    }
    mesh = {
        "type": MessageType.MESH_TOPOLOGY.value,
        "device_id": "android-pr4b-001",
        "payload": {"mesh_session_id": "mesh-1", "state": "joined"},
    }
    transfer = {
        "type": MessageType.FILE_TRANSFER.value,
        "device_id": "android-pr4b-001",
        "payload": {"transfer_id": "tx-1"},
    }

    status_resp = await bridge.handle_message(ws, agent_status)
    mesh_resp = await bridge.handle_message(ws, mesh)
    transfer_resp = await bridge.handle_message(ws, transfer)

    assert status_resp is not None and status_resp["type"] == "agent_status_ack"
    assert mesh_resp is not None and mesh_resp["type"] in ("mesh_topology_ack", "mesh_topology")
    assert transfer_resp is not None and transfer_resp["type"] == "file_transfer_ack"
