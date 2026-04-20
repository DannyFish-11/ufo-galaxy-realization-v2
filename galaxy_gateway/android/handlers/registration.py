"""
galaxy_gateway/android/handlers/registration.py

Handles device registration messages and unregistered message types.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict

from galaxy_gateway.android.message_builder import MessageBuilder
from galaxy_gateway.android.models import AndroidDevice

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_device_register(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理设备注册，失败时向网关日志输出结构化错误。

    Registration flow (PR-2):
    1. Write canonical identity/state to UDM (SSOT).
    2. Update local ``_devices`` as transport/session cache only.
    """
    device_id = message.get("device_id")

    try:
        # Step 1 — canonical write to UDM (SSOT); must happen before local cache update.
        bridge._write_registration_to_udm(device_id, message)

        # Step 2 — update local transport/session cache.
        async with bridge._lock:
            device = AndroidDevice.from_registration(message)
            device.websocket = websocket
            bridge._devices[device_id] = device

        bridge._sync_device_router_session(device_id, websocket=websocket, connected=True)

        # PR-G: emit device lifecycle (attach) so the observability sink records
        # the registration event in the production path.
        try:
            from core.runtime.runtime_observability_sink import emit_device_lifecycle_event
            emit_device_lifecycle_event(
                device_id,
                event_kind="attach",
                new_state="online",
                reason="android_device_register",
            )
        except Exception:
            pass

        # PR-B: Create and activate a durable mesh session for this device so that
        # the MeshSessionLifecycleCoordinator is aware of the device's registration.
        # The session tracks this device as both source and primary participant so
        # that disconnect handling can later locate and terminate it.
        try:
            from contracts.mesh_session import build_mesh_session
            from core.mesh.mesh_session_lifecycle import (
                create_durable_session,
                activate_durable_session,
            )
            _mesh_session = build_mesh_session(
                source_device_id=device_id,
                primary_device_id=device_id,
                metadata={"registration_trigger": "android_device_register"},
            )
            _record = create_durable_session(
                _mesh_session,
                metadata={"device_id": device_id, "trigger": "device_register"},
            )
            if _record:
                activate_durable_session(_record.session_id)
                logger.info(
                    "Mesh session created+activated for device: device_id=%s session_id=%s",
                    device_id, _record.session_id,
                )
        except Exception as _mesh_exc:
            logger.debug(
                "android_bridge: mesh session create/activate non-fatal: device_id=%s error=%s",
                device_id, _mesh_exc,
            )

        # PR-C: Attach runtime session — promotes the device from "registered object"
        # to "attached runtime node" visible in the AttachedRuntimeSessionRegistry.
        # Uses join_runtime posture (default) so the record achieves attachment_state=attached.
        # Idempotent: repeated registration/reconnect refreshes the existing record.
        try:
            from core.attached_runtime_session import attach_runtime_session
            _raw_posture = message.get("source_runtime_posture")
            if isinstance(_raw_posture, str) and _raw_posture.strip():
                _posture = _raw_posture.lower().strip()
            else:
                _posture = "join_runtime"
            attach_runtime_session(
                device_id,
                source_runtime_posture=_posture,
                attach_reason="android_device_register",
                metadata={"platform": "android", "trigger": "device_register"},
            )
            logger.info(
                "Attached runtime session for device: device_id=%s posture=%s",
                device_id, _posture,
            )
        except Exception as _attach_exc:
            logger.debug(
                "android_bridge: attach_runtime_session non-fatal: device_id=%s error=%s",
                device_id, _attach_exc,
            )

        # PR-C: BodyMeshRegistry role assignment — infer roles from capabilities
        # and register the device in the mesh so it becomes a projection/participation candidate.
        # Idempotent: repeated calls merge/update roles rather than duplicating entries.
        try:
            from galaxy_gateway.android_bridge import DeviceCapability
            from core.mesh.device_role_allocator import get_device_role_allocator
            raw_caps = message.get("capabilities", 0)
            if isinstance(raw_caps, int):
                caps_list = DeviceCapability.to_list(raw_caps)
            elif isinstance(raw_caps, (list, tuple)):
                caps_list = [str(c) for c in raw_caps]
            else:
                caps_list = []
            _alloc_result = get_device_role_allocator().allocate(
                device_id=device_id,
                capabilities=caps_list,
                extra_metadata={"platform": "android", "trigger": "device_register"},
            )
            logger.info(
                "BodyMeshRegistry roles assigned: device_id=%s roles=%s",
                device_id, [r.value for r in _alloc_result.roles_assigned],
            )
        except Exception as _role_exc:
            logger.debug(
                "android_bridge: body mesh role assignment non-fatal: device_id=%s error=%s",
                device_id, _role_exc,
            )

        logger.info(
            "Android device registered: device_id=%s model=%s platform=%s",
            device_id, device.model, device.platform,
        )

        return MessageBuilder.device_register_ack(
            device_id=device_id,
            success=True,
            session_id=str(uuid.uuid4()),
            message="Registration successful",
        )

    except Exception as exc:
        _SENSITIVE_FIELDS = frozenset({
            "websocket", "image_base64", "token", "password",
            "credential", "secret", "auth", "api_key",
        })
        safe_payload = {k: v for k, v in message.items() if k not in _SENSITIVE_FIELDS}
        logger.error(
            "Device registration failed: device_id=%s error=%s payload=%s",
            device_id, exc, safe_payload,
        )
        return MessageBuilder.device_register_ack(
            device_id=device_id or "unknown",
            success=False,
            message=f"Registration failed: {exc}",
        )


async def handle_unregistered(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """通用处理器 — 记录日志并返回 ACK，防止消息被静默丢弃"""
    msg_type = message.get("type", "unknown")
    device_id = message.get("device_id", "unknown")
    logger.info(
        "Unhandled message type '%s' from device '%s', returning ACK",
        msg_type, device_id,
    )
    return {
        "type": "ack",
        "device_id": device_id,
        "original_type": msg_type,
        "status": "received",
        "note": "No specific handler registered for this message type",
    }
