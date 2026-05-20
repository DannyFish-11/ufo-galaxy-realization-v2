"""
galaxy_gateway/android/handlers/generic.py

Generic forward handler for message types without specific handlers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Tuple

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

GENERIC_FORWARD_TRANSPORT_ONLY_POLICY = (
    "ANDROID_BRIDGE::GENERIC_FORWARD_TRANSPORT_ONLY_V1: "
    "handle_generic_forward() is a transitional transport ACK path only. "
    "It must not absorb canonical governance, acceptance, or runtime-state ingress."
)

GENERIC_FORWARD_CANONICAL_INGRESS_GUARD_POLICY = (
    "ANDROID_BRIDGE::GENERIC_FORWARD_CANONICAL_INGRESS_GUARD_V1: "
    "High-value Android reports and runtime-state uplinks must use their "
    "dedicated canonical ingress handlers, not handle_generic_forward()."
)

GENERIC_FORWARD_COMPAT_GATE_POLICY = (
    "ANDROID_BRIDGE::GENERIC_FORWARD_COMPAT_WHITELIST_GATE_V1: "
    "handle_generic_forward() only accepts explicitly enumerated compat message types. "
    "Unclassified messages must be rejected at the contract boundary."
)

_CANONICAL_INGRESS_HANDLER_BY_MESSAGE_TYPE = {
    "device_readiness_report": "android_evaluator_artifact_ingress",
    "device_governance_report": "android_evaluator_artifact_ingress",
    "device_strategy_report": "android_evaluator_artifact_ingress",
    "device_acceptance_report": "android_acceptance_report_ingress",
    "device_state_snapshot": "android_device_state_snapshot_ingress",
    "device_execution_event": "android_device_execution_event_ingress",
}

_GENERIC_FORWARD_COMPAT_MESSAGE_TYPES: Tuple[str, ...] = (
    "agent_config_update",
    "agent_restart",
    "ui_tree_request",
    "action_execute",
    "action_sequence_execute",
    "app_start",
    "app_stop",
    "system_command",
    "cancel_result",
)
_GENERIC_FORWARD_COMPAT_MESSAGE_TYPE_SET = frozenset(_GENERIC_FORWARD_COMPAT_MESSAGE_TYPES)


def _normalize_message_type(message_type: Any) -> str:
    return str(message_type or "").strip().lower()


def is_generic_forward_blocked_message_type(message_type: Any) -> bool:
    """Return whether a message type must bypass generic forward.

    Args:
        message_type: String wire message type such as ``device_readiness_report``.

    Returns:
        True when the message type requires canonical ingress routing.
    """
    return _normalize_message_type(message_type) in _CANONICAL_INGRESS_HANDLER_BY_MESSAGE_TYPE


def is_generic_forward_compat_message_type(message_type: Any) -> bool:
    """Return whether a message type is allowed through generic-forward compat gate."""
    return _normalize_message_type(message_type) in _GENERIC_FORWARD_COMPAT_MESSAGE_TYPE_SET


def get_generic_forward_compat_allowlist() -> Tuple[str, ...]:
    """Return the canonical bounded allowlist for generic-forward compat path."""
    return _GENERIC_FORWARD_COMPAT_MESSAGE_TYPES


async def handle_generic_forward(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """通用占位处理器：记录日志并返回 ACK（后续可扩展为实际转发逻辑）"""
    msg_type = message.get("type")
    device_id = message.get("device_id")
    normalized_type = _normalize_message_type(msg_type)
    if normalized_type in _CANONICAL_INGRESS_HANDLER_BY_MESSAGE_TYPE:
        logger.warning(
            "Rejected canonical-ingress message from generic_forward: type=%s device_id=%s handler=%s",
            normalized_type,
            device_id,
            _CANONICAL_INGRESS_HANDLER_BY_MESSAGE_TYPE[normalized_type],
        )
        return {
            "type": "error",
            "device_id": device_id,
            "status": "rejected",
            "message_id": message.get("message_id"),
            "original_type": normalized_type,
            "error_code": "CANONICAL_INGRESS_REQUIRED",
            "error_message": (
                f"{normalized_type} must use its dedicated canonical ingress handler, "
                "not handle_generic_forward"
            ),
            "canonical_ingress_required": True,
            "canonical_ingress_handler": _CANONICAL_INGRESS_HANDLER_BY_MESSAGE_TYPE[normalized_type],
        }
    if normalized_type not in _GENERIC_FORWARD_COMPAT_MESSAGE_TYPE_SET:
        logger.warning(
            "Rejected non-allowlisted message from generic_forward: type=%s device_id=%s",
            normalized_type,
            device_id,
        )
        return {
            "type": "error",
            "device_id": device_id,
            "status": "rejected",
            "message_id": message.get("message_id"),
            "original_type": normalized_type,
            "error_code": "GENERIC_FORWARD_TYPE_NOT_ALLOWED",
            "error_message": (
                f"Message type {normalized_type or '<empty>'} is not allowed through "
                "generic_forward; request explicit compat allowlist inclusion for "
                "bounded legacy support, or route it to a dedicated handler"
            ),
            "compat_policy": GENERIC_FORWARD_COMPAT_GATE_POLICY,
            "allowed_compat_types": list(_GENERIC_FORWARD_COMPAT_MESSAGE_TYPES),
        }
    logger.debug("Received %s from %s: forwarding", msg_type, device_id)
    return {
        "type": f"{msg_type}_ack" if msg_type else "ack",
        "device_id": device_id,
        "status": "received",
        "message_id": message.get("message_id"),
    }
