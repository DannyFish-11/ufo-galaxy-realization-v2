"""
galaxy_gateway/android/handlers/capability_report.py

Handles capability_report messages from Android devices.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role derivation helper
# ---------------------------------------------------------------------------

def _derive_roles_from_supported_actions(supported_actions: List) -> "List":
    """Derive :class:`~core.mesh.body_mesh_registry.DeviceRole` values from a
    list of supported action strings reported by the device.

    Mapping:
    - PERCEPTION  — actions containing any of: camera, photo, scan, mic,
                    audio, record, sensor
    - ACTION      — actions containing any of: tap, swipe, type, keyboard,
                    click, input, write, exec, shell, install
    - PRESENCE    — actions containing any of: screenshot, screen, display,
                    notify, notification, speak, tts

    A device with no matched roles defaults to ACTION to ensure every device
    has at least one role.
    """
    try:
        from core.mesh.body_mesh_registry import DeviceRole
    except ImportError:
        return []

    _PERCEPTION_KEYWORDS = {"camera", "photo", "scan", "mic", "audio", "record", "sensor"}
    _ACTION_KEYWORDS = {"tap", "swipe", "type", "keyboard", "click", "input", "write", "exec", "shell", "install"}
    _PRESENCE_KEYWORDS = {"screenshot", "screen", "display", "notify", "notification", "speak", "tts"}

    roles: List = []
    actions_lower = {(a.lower() if isinstance(a, str) else str(a).lower()) for a in supported_actions}

    if any(k in action for action in actions_lower for k in _PERCEPTION_KEYWORDS):
        roles.append(DeviceRole.PERCEPTION)
    if any(k in action for action in actions_lower for k in _ACTION_KEYWORDS):
        roles.append(DeviceRole.ACTION)
    if any(k in action for action in actions_lower for k in _PRESENCE_KEYWORDS):
        roles.append(DeviceRole.PRESENCE)

    if not roles:
        roles.append(DeviceRole.ACTION)

    return roles


async def handle_capability_report(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理设备能力上报，持久化 supported_actions 并同步到 CapabilityRegistry。

    能力命名规则（稳定且可被 LLM tool schema 使用）：
        ``gateway__<device_id>__<action_name>``

    新字段（Round 3）
    -----------------
    ``capability_schemas`` : list[dict]
        每个元素描述一条能力的完整 schema::

            {
              "action"    : "tap",
              "params"    : { ... },      # 可选 JSON Schema
              "returns"   : { ... },      # 可选
              "version"   : "1.0",        # 可选
              "exec_mode" : "local",      # "local"|"remote"|"both"，缺省 "both"
              "tags"      : ["ui", ...]   # 可选标签
            }

    若客户端仅上报 ``supported_actions``（旧格式），则以 exec_mode="both"
    补全，保持向后兼容。
    """
    device_id = message.get("device_id")
    platform = message.get("platform")
    supported_actions = message.get("supported_actions", [])
    version = message.get("version")
    capability_schemas: list = message.get("capability_schemas") or []

    logger.info(
        "Capability report from %s: platform=%s, actions=%s, version=%s, schemas=%d",
        device_id, platform, supported_actions, version, len(capability_schemas),
    )

    async with bridge._lock:
        if device_id in bridge._devices:
            bridge._devices[device_id].supported_actions = list(supported_actions)
            bridge._devices[device_id].last_heartbeat = time.time()

    # ── 1. Sync to GatewayCapabilityRegistry (exec_mode-aware) ────────────
    if device_id:
        try:
            from galaxy_gateway.capability_registry import get_gateway_capability_registry
            gw_reg = get_gateway_capability_registry()

            schema_by_action: dict = {}
            for schema_entry in capability_schemas:
                if isinstance(schema_entry, dict) and schema_entry.get("action"):
                    schema_by_action[schema_entry["action"]] = schema_entry

            upserted = 0
            for action in supported_actions:
                action_str = action if isinstance(action, str) else str(action)
                schema_dict = schema_by_action.get(action_str, {})
                if version and not schema_dict.get("version"):
                    schema_dict = {**schema_dict, "version": str(version)}
                gw_reg.upsert(device_id, action_str, schema_dict)
                upserted += 1

            logger.info(
                "capability_report: upserted %d capabilities for device %s to GatewayCapabilityRegistry",
                upserted, device_id,
            )
        except Exception as gw_sync_err:
            logger.warning(
                "capability_report: GatewayCapabilityRegistry sync failed: %s", gw_sync_err
            )

    # ── 2. Sync to LLM CapabilityRegistry (unchanged — backward compat) ───
    if device_id and supported_actions:
        try:
            from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
            reg = CapabilityRegistry.get_instance()
            for action in supported_actions:
                action_str = action if isinstance(action, str) else str(action)
                cap_name = f"gateway__{device_id}__{action_str}"
                reg.register(CapabilityItem(
                    name=cap_name,
                    description=f"Android device {device_id} action: {action_str} (platform={platform})",
                    source="gateway",
                    source_id=device_id,
                    available=True,
                    metadata={"device_id": device_id, "platform": platform, "action": action_str},
                ))
            logger.info(
                "capability_report: synced %d actions for device %s to CapabilityRegistry",
                len(supported_actions), device_id,
            )
        except Exception as sync_err:
            logger.warning("capability_report: CapabilityRegistry sync failed: %s", sync_err)

    # ── 3. Update BodyMeshRegistry roles based on supported_actions ───────────
    # This ensures that even if a device registered with no/partial capabilities,
    # a subsequent capability_report can update its body mesh role assignment.
    # Behaviour is idempotent: re-registration merges roles.
    if device_id:
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole
            _roles = _derive_roles_from_supported_actions(supported_actions)
            get_body_mesh_registry().register(
                device_id,
                roles=_roles,
                metadata={"capability_report_trigger": True, "platform": platform},
            )
            logger.info(
                "BodyMeshRegistry: updated device_id=%s roles=%s via capability_report",
                device_id, [r.value for r in _roles],
            )
        except Exception as _bmr_exc:
            logger.debug(
                "capability_report: BodyMeshRegistry update non-fatal: device_id=%s error=%s",
                device_id, _bmr_exc,
            )

    return MessageBuilder.capability_report_ack(
        device_id=device_id or "unknown",
        accepted=True,
        message="capability_report accepted",
    )
