"""
galaxy_gateway/android/handlers/registration.py

Handles device registration messages and unregistered message types.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, List

from galaxy_gateway.android.message_builder import MessageBuilder
from galaxy_gateway.android.models import AndroidDevice

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role derivation helpers
# ---------------------------------------------------------------------------

def _derive_body_mesh_roles(capabilities: int) -> List[Any]:
    """Derive :class:`~core.mesh.body_mesh_registry.DeviceRole` values from a
    ``DeviceCapability`` bitmask.

    Mapping:
    - PERCEPTION  — any of SENSOR_CAMERA, SENSOR_MIC, SENSOR_MOTION
    - ACTION      — any of INPUT_TOUCH, INPUT_KEYBOARD, GUI_WRITE, SYSTEM_SHELL
    - PRESENCE    — any of GUI_READ, GUI_SCREENSHOT, SYSTEM_NOTIFICATION

    A device that has none of the above defaults to the ACTION role to ensure
    every registered device has at least one role.
    """
    try:
        from core.mesh.body_mesh_registry import DeviceRole
        from galaxy_gateway.android.capabilities import DeviceCapability as DC
    except ImportError:
        return []

    roles: List = []
    has = DC.has_capability

    if has(capabilities, DC.SENSOR_CAMERA) or has(capabilities, DC.SENSOR_MIC) or has(capabilities, DC.SENSOR_MOTION):
        roles.append(DeviceRole.PERCEPTION)
    if has(capabilities, DC.INPUT_TOUCH) or has(capabilities, DC.INPUT_KEYBOARD) or has(capabilities, DC.GUI_WRITE) or has(capabilities, DC.SYSTEM_SHELL):
        roles.append(DeviceRole.ACTION)
    if has(capabilities, DC.GUI_READ) or has(capabilities, DC.GUI_SCREENSHOT) or has(capabilities, DC.SYSTEM_NOTIFICATION):
        roles.append(DeviceRole.PRESENCE)

    if not roles:
        roles.append(DeviceRole.ACTION)

    return roles


async def handle_device_register(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理设备注册，失败时向网关日志输出结构化错误。

    Registration flow (PR-2):
    1. Write canonical identity/state to UDM (SSOT).
    2. Update local ``_devices`` as transport/session cache only.

    PR-G: extracts ``runtime_attachment_session_id`` from the message and
    propagates it to the attach and registry paths for canonical identity
    handling.  Falls back to generating a new stable ID when absent (backward
    compatibility with older clients).
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

        # PR-G: extract canonical runtime attachment session identity.
        # Prefer the explicit field; fall back to a generated UUID so that
        # older clients that do not supply the field remain compatible.
        inbound_attachment_id = (
            message.get("runtime_attachment_session_id")
            or message.get("session_id")
            or ""
        )
        if not inbound_attachment_id:
            inbound_attachment_id = str(uuid.uuid4())
            logger.debug(
                "handle_device_register: runtime_attachment_session_id absent in "
                "message, generated fallback: device_id=%s attachment_id=%s",
                device_id, inbound_attachment_id,
            )

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

        # PR-C / PR-G: attach runtime session with canonical runtime_attachment_session_id
        # so the device enters the attached runtime session registry and becomes visible
        # as a managed runtime node with a stable attachment identity.
        try:
            from core.attached_runtime_session import attach_runtime_session
            _attach_record = attach_runtime_session(
                device_id,
                source_runtime_posture="join_runtime",
                runtime_attachment_session_id=inbound_attachment_id,
                attach_reason="android_device_register",
                metadata={"registration_trigger": "android_device_register"},
            )
            logger.info(
                "attach_runtime_session: device_id=%s state=%s runtime_attachment_session_id=%s",
                device_id, _attach_record.attachment_state, _attach_record.runtime_attachment_session_id,
            )
        except Exception as _attach_exc:
            logger.debug(
                "android_bridge: attach_runtime_session non-fatal: device_id=%s error=%s",
                device_id, _attach_exc,
            )

        # PR-C / PR-G: register in the authoritative attached runtime session registry
        # with the canonical runtime_attachment_session_id for stable identity lookup.
        try:
            from core.attached_runtime_session_registry import register_session
            _reg_entry = register_session(
                device_id,
                posture="join_runtime",
                runtime_attachment_session_id=inbound_attachment_id,
                metadata={"registration_trigger": "android_device_register"},
            )
            logger.info(
                "attached_runtime_session_registry: registered device_id=%s "
                "runtime_session_id=%s runtime_attachment_session_id=%s",
                device_id, _reg_entry.runtime_session_id,
                _reg_entry.runtime_attachment_session_id,
            )
        except Exception as _reg_exc:
            logger.debug(
                "android_bridge: attached_runtime_session_registry non-fatal: device_id=%s error=%s",
                device_id, _reg_exc,
            )

        # PR-C: assign Body Mesh roles based on device capability bitmask so
        # that the BodyMeshRegistry (and downstream presence/projection paths)
        # can correctly classify the device.
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            _cap_flags = message.get("capabilities", device.capabilities)
            _roles = _derive_body_mesh_roles(_cap_flags)
            get_body_mesh_registry().register(
                device_id,
                roles=_roles,
                metadata={"registration_trigger": "android_device_register", "platform": device.platform.value if device.platform else None},
            )
            logger.info(
                "BodyMeshRegistry: registered device_id=%s roles=%s",
                device_id, [r.value for r in _roles],
            )
        except Exception as _mesh_exc:
            logger.debug(
                "android_bridge: BodyMeshRegistry registration non-fatal: device_id=%s error=%s",
                device_id, _mesh_exc,
            )

        logger.info(
            "Android device registered: device_id=%s model=%s platform=%s "
            "runtime_attachment_session_id=%s",
            device_id, device.model, device.platform, inbound_attachment_id,
        )

        ack = MessageBuilder.device_register_ack(
            device_id=device_id,
            success=True,
            session_id=str(uuid.uuid4()),
            message="Registration successful",
        )
        # PR-G: echo back the canonical runtime_attachment_session_id so the
        # client can confirm and persist it for reconnect continuity.
        ack["runtime_attachment_session_id"] = inbound_attachment_id
        return ack

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


async def handle_device_reconnect(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle a device reconnect message.

    PR-G: This handler is the canonical continuity reconnect consumer.  It
    extracts ``runtime_attachment_session_id`` from the inbound message and
    uses :func:`~core.attached_runtime_session_registry.classify_reconnect_outcome`
    to determine whether the reconnect should restore an existing runtime
    attachment continuity (``continuity_resume``) or create a new attachment
    session (``new_attachment``).

    Continuity resume
        The existing registry entry is reconnected via
        :func:`~core.attached_runtime_session_registry.reconnect_session`.
        The stable ``runtime_session_id`` and ``runtime_attachment_session_id``
        are preserved.

    New attachment
        The reconnect is treated as a fresh registration:
        :func:`~core.attached_runtime_session_registry.register_session` is
        called with the supplied ``runtime_attachment_session_id`` (or a
        generated fallback if absent).

    Backward compatibility
        Older clients that do not supply ``runtime_attachment_session_id`` are
        handled gracefully: the existing session is resumed when one exists,
        or a new attachment is created when no prior session is found.
    """
    device_id = message.get("device_id")

    try:
        # PR-G: extract canonical attachment identity from the reconnect message.
        inbound_attachment_id = (
            message.get("runtime_attachment_session_id")
            or message.get("session_id")
            or ""
        )

        # Update local transport/session cache so the bridge sees the new socket.
        async with bridge._lock:
            if device_id in bridge._devices:
                bridge._devices[device_id].websocket = websocket
            else:
                device = AndroidDevice.from_registration(message)
                device.websocket = websocket
                bridge._devices[device_id] = device

        bridge._sync_device_router_session(device_id, websocket=websocket, connected=True)

        # PR-G: classify reconnect outcome
        outcome = "new_attachment"
        existing_entry = None
        try:
            from core.attached_runtime_session_registry import (
                classify_reconnect_outcome,
                reconnect_session,
                register_session,
            )
            outcome, existing_entry = classify_reconnect_outcome(
                device_id,
                runtime_attachment_session_id=inbound_attachment_id,
            )
        except Exception as _cls_exc:
            logger.debug(
                "handle_device_reconnect: classify_reconnect_outcome non-fatal: "
                "device_id=%s error=%s",
                device_id, _cls_exc,
            )

        resolved_attachment_id = inbound_attachment_id

        if outcome == "continuity_resume" and existing_entry is not None:
            logger.info(
                "handle_device_reconnect: continuity_resume: device_id=%s "
                "runtime_attachment_session_id=%s reconnect_count=%s",
                device_id,
                existing_entry.runtime_attachment_session_id,
                existing_entry.reconnect_count,
            )
            resolved_attachment_id = existing_entry.runtime_attachment_session_id
            try:
                reconnect_session(
                    existing_entry,
                    runtime_attachment_session_id=resolved_attachment_id,
                    metadata={"reconnect_trigger": "android_device_reconnect"},
                )
            except Exception as _rec_exc:
                logger.debug(
                    "handle_device_reconnect: reconnect_session non-fatal: "
                    "device_id=%s error=%s",
                    device_id, _rec_exc,
                )
        else:
            # new_attachment: treat as a fresh registration
            if not resolved_attachment_id:
                resolved_attachment_id = str(uuid.uuid4())
            logger.info(
                "handle_device_reconnect: new_attachment: device_id=%s "
                "runtime_attachment_session_id=%s",
                device_id, resolved_attachment_id,
            )
            try:
                register_session(
                    device_id,
                    posture="join_runtime",
                    runtime_attachment_session_id=resolved_attachment_id,
                    metadata={"reconnect_trigger": "android_device_reconnect"},
                )
            except Exception as _reg_exc:
                logger.debug(
                    "handle_device_reconnect: register_session non-fatal: "
                    "device_id=%s error=%s",
                    device_id, _reg_exc,
                )

        # Also update the attached_runtime_session record so both stores align.
        try:
            from core.attached_runtime_session import attach_runtime_session
            attach_runtime_session(
                device_id,
                source_runtime_posture="join_runtime",
                runtime_attachment_session_id=resolved_attachment_id,
                attach_reason=f"android_device_reconnect:{outcome}",
                metadata={"reconnect_trigger": "android_device_reconnect"},
            )
        except Exception as _attach_exc:
            logger.debug(
                "handle_device_reconnect: attach_runtime_session non-fatal: "
                "device_id=%s error=%s",
                device_id, _attach_exc,
            )

        ack = {
            "type": "reconnect_ack",
            "device_id": device_id,
            "success": True,
            "continuity_outcome": outcome,
            "runtime_attachment_session_id": resolved_attachment_id,
            "message": f"Reconnect processed: {outcome}",
        }
        return ack

    except Exception as exc:
        logger.error(
            "Device reconnect failed: device_id=%s error=%s",
            device_id, exc,
        )
        return {
            "type": "reconnect_ack",
            "device_id": device_id or "unknown",
            "success": False,
            "continuity_outcome": "error",
            "message": f"Reconnect failed: {exc}",
        }


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
