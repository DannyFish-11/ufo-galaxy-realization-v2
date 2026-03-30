"""
galaxy_gateway/android/handlers/capability_report.py

Handles capability_report messages from Android devices.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


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

    return MessageBuilder.capability_report_ack(
        device_id=device_id or "unknown",
        accepted=True,
        message="capability_report accepted",
    )
