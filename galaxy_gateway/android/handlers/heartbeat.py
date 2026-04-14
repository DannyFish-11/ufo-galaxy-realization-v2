"""
galaxy_gateway/android/handlers/heartbeat.py

Handles heartbeat, device status, and agent ping messages.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_heartbeat(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理心跳，未注册设备仍回 ACK 并输出警告。

    Heartbeat flow (PR-2):
    1. Patch canonical runtime state in UDM (last_heartbeat + ONLINE).
    2. Keep local transport cache in sync for operational use.
    """
    device_id = message.get("device_id")

    # Step 1 — canonical patch to UDM.
    bridge._patch_heartbeat_to_udm(device_id)

    # Step 2 — update local transport cache.
    async with bridge._lock:
        if device_id in bridge._devices:
            bridge._devices[device_id].last_heartbeat = time.time()
            bridge._devices[device_id].connected = True
            bridge._sync_device_router_session(
                device_id,
                connected=True,
            )
        else:
            logger.warning(
                "Heartbeat from unregistered device: device_id=%s; ACK sent",
                device_id,
            )

    return MessageBuilder.heartbeat_ack(device_id)


async def handle_device_status(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理设备状态上报（battery, cpu, memory 等）。

    Status update flow (PR-2):
    1. Patch canonical runtime state in UDM (last_heartbeat + metadata).
    2. Keep local transport cache in sync.
    """
    device_id = message.get("device_id")
    status_payload = message.get("status") or message.get("payload") or {}

    # Step 1 — canonical patch to UDM (merge status metadata, update last_seen).
    if device_id:
        meta_patch: Dict[str, Any] = {}
        if isinstance(status_payload, dict) and status_payload:
            meta_patch["metadata"] = {"device_status_report": status_payload}
        bridge._patch_runtime_state_to_udm(device_id, meta_patch, source="android_bridge_status")

    # Step 2 — update local transport cache.
    async with bridge._lock:
        if device_id in bridge._devices:
            bridge._devices[device_id].last_heartbeat = time.time()
            bridge._devices[device_id].connected = True
            bridge._sync_device_router_session(
                device_id,
                connected=True,
            )

    logger.info(
        "Device status update: device_id=%s status=%s",
        device_id, status_payload,
    )

    return {
        "version": "3.0",
        "type": "device_status_ack",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "status": "received",
    }


async def handle_agent_ping(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理 agent_ping 请求，返回 heartbeat_ack"""
    device_id = message.get("device_id")
    logger.debug("Agent ping from %s", device_id)
    return MessageBuilder.heartbeat_ack(device_id)


async def handle_agent_status(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理 agent_status（readiness/posture 证据）."""
    device_id = message.get("device_id")
    status_payload = message.get("status") or message.get("payload") or {}

    if device_id:
        meta_patch: Dict[str, Any] = {}
        if isinstance(status_payload, dict) and status_payload:
            meta_patch["metadata"] = {"agent_status_report": status_payload}
        bridge._patch_runtime_state_to_udm(device_id, meta_patch, source="android_bridge_agent_status")

    async with bridge._lock:
        if device_id in bridge._devices:
            bridge._devices[device_id].last_heartbeat = time.time()
            bridge._devices[device_id].connected = True
            bridge._sync_device_router_session(device_id, connected=True)

    return {
        "version": "3.0",
        "type": "agent_status_ack",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "status": "received",
    }
