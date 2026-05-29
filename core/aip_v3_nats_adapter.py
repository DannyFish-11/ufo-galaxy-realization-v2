"""
core/aip_v3_nats_adapter.py
===========================
PR-AIPV3-NATS: AIP v3 ↔ NATS Message Format Adapter

Converts between the legacy contracts.py message formats and the canonical
AIP v3 protocol (as defined in AipModels.kt and galaxy_gateway/android/handlers).

This is the convergence layer: NATS transports AIP v3 messages, period.
Legacy TaskDispatchModel / WorkerRegistrationModel etc. are translated
at the boundary so existing callers continue to work unchanged.

Mapping:
    TaskDispatchModel     → AIP v3 TASK_ASSIGN
    TaskResultModel       → AIP v3 TASK_RESULT
    WorkerRegistrationModel → AIP v3 DEVICE_REGISTER
    WorkerHeartbeatModel  → AIP v3 HEARTBEAT
    WorkerShutdownModel   → AIP v3 (device_unregister implied)
    AgentEventModel       → AIP v3 event type (mapped per event_type)

Design principles:
    - Additive only: all existing methods keep working
    - Bidirectional: can convert both ways (legacy ↔ AIP v3)
    - Non-blocking: conversion never raises; on failure returns the input unchanged
    - Wire format: all messages carry {"type": "<msg_type>", ...payload}
      so subscribers can identify the message type without inspecting payload shapes.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AIP v3 message type constants (mirroring AipModels.kt MsgType)
# ---------------------------------------------------------------------------

# Core lifecycle
AIP_DEVICE_REGISTER = "device_register"
AIP_HEARTBEAT = "heartbeat"
AIP_HEARTBEAT_ACK = "heartbeat_ack"
AIP_CAPABILITY_REPORT = "capability_report"

# Task / execution
AIP_TASK_SUBMIT = "task_submit"
AIP_TASK_ASSIGN = "task_assign"
AIP_TASK_RESULT = "task_result"
AIP_COMMAND_RESULT = "command_result"
AIP_GOAL_EXECUTION = "goal_execution"
AIP_GOAL_RESULT = "goal_result"
AIP_GOAL_EXECUTION_RESULT = "goal_execution_result"
AIP_TASK_CANCEL = "task_cancel"
AIP_CANCEL_RESULT = "cancel_result"

# Mesh
AIP_MESH_JOIN = "mesh_join"
AIP_MESH_LEAVE = "mesh_leave"
AIP_MESH_RESULT = "mesh_result"
AIP_MESH_TOPOLOGY = "mesh_topology"
AIP_COORD_SYNC = "coord_sync"

# Advanced
AIP_PEER_ANNOUNCE = "peer_announce"
AIP_PEER_EXCHANGE = "peer_exchange"
AIP_TAKEOVER_REQUEST = "takeover_request"
AIP_TAKEOVER_RESPONSE = "takeover_response"
AIP_DELEGATED_EXECUTION_SIGNAL = "delegated_execution_signal"
AIP_RECONCILIATION_SIGNAL = "reconciliation_signal"

# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ensure_device_id(device_id: Optional[str]) -> str:
    return device_id or f"device_{uuid.uuid4().hex[:8]}"


def _safe_dict(data: Any) -> Dict[str, Any]:
    """Convert a Pydantic model or dict to a plain dict."""
    if data is None:
        return {}
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if v is not None}
    if hasattr(data, "model_dump"):
        return {k: v for k, v in data.model_dump(mode="json", exclude_none=True).items() if v is not None}
    return {}


# ---------------------------------------------------------------------------
# Legacy → AIP v3 conversions
# ---------------------------------------------------------------------------


def to_aip_device_register(registration: Any) -> Dict[str, Any]:
    """Convert WorkerRegistrationModel → AIP v3 device_register message.

    WorkerRegistrationModel fields:
        worker_id, worker_type, capabilities, metadata, registered_at
    """
    try:
        data = _safe_dict(registration)
        return {
            "type": AIP_DEVICE_REGISTER,
            "device_id": data.get("worker_id", ""),
            "device_type": data.get("worker_type", "worker"),
            "capabilities": data.get("capabilities", []),
            "metadata": data.get("metadata", {}),
            "timestamp": _now_ms(),
            "_aip_version": "3.0",
        }
    except Exception as exc:
        logger.debug("to_aip_device_register conversion failed: %s", exc)
        return _safe_dict(registration)


def to_aip_heartbeat(heartbeat: Any) -> Dict[str, Any]:
    """Convert WorkerHeartbeatModel → AIP v3 heartbeat message.

    WorkerHeartbeatModel fields:
        worker_id, timestamp, status, metadata
    """
    try:
        data = _safe_dict(heartbeat)
        return {
            "type": AIP_HEARTBEAT,
            "device_id": data.get("worker_id", ""),
            "status": data.get("status", "online"),
            "metadata": data.get("metadata", {}),
            "timestamp": data.get("timestamp") or _now_ms(),
            "_aip_version": "3.0",
        }
    except Exception as exc:
        logger.debug("to_aip_heartbeat conversion failed: %s", exc)
        return _safe_dict(heartbeat)


def to_aip_task_assign(dispatch: Any) -> Dict[str, Any]:
    """Convert TaskDispatchModel → AIP v3 task_assign message.

    TaskDispatchModel fields:
        task_id, target_worker_id, action, params, priority, timeout_ms, trace_id
    """
    try:
        data = _safe_dict(dispatch)
        return {
            "type": AIP_TASK_ASSIGN,
            "task_id": data.get("task_id", ""),
            "device_id": data.get("target_worker_id", ""),
            "action": data.get("action", ""),
            "params": data.get("params", {}),
            "priority": data.get("priority", "normal"),
            "timeout_ms": data.get("timeout_ms", 30000),
            "trace_id": data.get("trace_id", ""),
            "timestamp": _now_ms(),
            "_aip_version": "3.0",
        }
    except Exception as exc:
        logger.debug("to_aip_task_assign conversion failed: %s", exc)
        return _safe_dict(dispatch)


def to_aip_task_result(result: Any) -> Dict[str, Any]:
    """Convert TaskResultModel → AIP v3 task_result / goal_execution_result message.

    TaskResultModel fields:
        task_id, worker_id, status, result, error, duration_ms, trace_id
    """
    try:
        data = _safe_dict(result)
        status = data.get("status", "")
        # Map status to appropriate AIP v3 type
        msg_type = AIP_TASK_RESULT
        if status in ("completed", "goal_completed"):
            msg_type = AIP_GOAL_EXECUTION_RESULT

        return {
            "type": msg_type,
            "task_id": data.get("task_id", ""),
            "device_id": data.get("worker_id", ""),
            "status": status,
            "result": data.get("result"),
            "error": data.get("error"),
            "duration_ms": data.get("duration_ms", 0),
            "trace_id": data.get("trace_id", ""),
            "timestamp": _now_ms(),
            "_aip_version": "3.0",
        }
    except Exception as exc:
        logger.debug("to_aip_task_result conversion failed: %s", exc)
        return _safe_dict(result)


def to_aip_worker_shutdown(shutdown: Any) -> Dict[str, Any]:
    """Convert WorkerShutdownModel → AIP v3 device_unregister message.

    WorkerShutdownModel fields:
        worker_id, reason, timestamp
    """
    try:
        data = _safe_dict(shutdown)
        return {
            "type": AIP_DEVICE_REGISTER,  # Re-register with status=offline
            "device_id": data.get("worker_id", ""),
            "device_type": "worker",
            "status": "offline",
            "reason": data.get("reason", "shutdown"),
            "timestamp": _now_ms(),
            "_aip_version": "3.0",
        }
    except Exception as exc:
        logger.debug("to_aip_worker_shutdown conversion failed: %s", exc)
        return _safe_dict(shutdown)


def to_aip_agent_event(event: Any) -> Dict[str, Any]:
    """Convert AgentEventModel → appropriate AIP v3 event message."""
    try:
        data = _safe_dict(event)
        event_type = data.get("event_type", "")
        # Map event types to AIP v3 types
        type_map = {
            "worker_registered": AIP_DEVICE_REGISTER,
            "worker_shutdown": AIP_HEARTBEAT,  # heartbeat with status=offline
            "task_dispatched": AIP_TASK_ASSIGN,
            "task_completed": AIP_TASK_RESULT,
            "capability_registered": AIP_CAPABILITY_REPORT,
            "mesh_join": AIP_MESH_JOIN,
            "mesh_leave": AIP_MESH_LEAVE,
        }
        aip_type = type_map.get(event_type, event_type)
        return {
            "type": aip_type,
            "event_type": event_type,
            "payload": data.get("payload", {}),
            "timestamp": data.get("timestamp") or _now_ms(),
            "trace_id": data.get("trace_id", ""),
            "_aip_version": "3.0",
        }
    except Exception as exc:
        logger.debug("to_aip_agent_event conversion failed: %s", exc)
        return _safe_dict(event)


# ---------------------------------------------------------------------------
# AIP v3 → Legacy conversions (for subscribers that expect old format)
# ---------------------------------------------------------------------------


def from_aip_to_legacy(aip_msg: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an AIP v3 message back to a flat dict compatible with legacy consumers.

    This is used on the subscriber side: NATS subscriber receives AIP v3 message,
    converts it to a flat dict so existing handlers don't need to change.
    """
    if not isinstance(aip_msg, dict):
        return aip_msg if isinstance(aip_msg, dict) else {}

    msg_type = aip_msg.get("type", "")
    try:
        if msg_type == AIP_DEVICE_REGISTER:
            return {
                "worker_id": aip_msg.get("device_id", ""),
                "worker_type": aip_msg.get("device_type", "unknown"),
                "capabilities": aip_msg.get("capabilities", []),
                "metadata": aip_msg.get("metadata", {}),
                "registered_at": aip_msg.get("timestamp", _now_ms()),
                "_aip_converted": True,
            }
        elif msg_type == AIP_HEARTBEAT:
            return {
                "worker_id": aip_msg.get("device_id", ""),
                "status": aip_msg.get("status", "online"),
                "metadata": aip_msg.get("metadata", {}),
                "timestamp": aip_msg.get("timestamp", _now_ms()),
                "_aip_converted": True,
            }
        elif msg_type == AIP_TASK_ASSIGN:
            return {
                "task_id": aip_msg.get("task_id", ""),
                "target_worker_id": aip_msg.get("device_id", ""),
                "action": aip_msg.get("action", ""),
                "params": aip_msg.get("params", {}),
                "priority": aip_msg.get("priority", "normal"),
                "timeout_ms": aip_msg.get("timeout_ms", 30000),
                "trace_id": aip_msg.get("trace_id", ""),
                "timestamp": aip_msg.get("timestamp", _now_ms()),
                "_aip_converted": True,
            }
        elif msg_type in (AIP_TASK_RESULT, AIP_GOAL_EXECUTION_RESULT, AIP_COMMAND_RESULT):
            return {
                "task_id": aip_msg.get("task_id", ""),
                "worker_id": aip_msg.get("device_id", ""),
                "status": aip_msg.get("status", ""),
                "result": aip_msg.get("result"),
                "error": aip_msg.get("error"),
                "duration_ms": aip_msg.get("duration_ms", 0),
                "trace_id": aip_msg.get("trace_id", ""),
                "timestamp": aip_msg.get("timestamp", _now_ms()),
                "_aip_converted": True,
            }
        elif msg_type in (AIP_MESH_JOIN, AIP_MESH_LEAVE, AIP_MESH_RESULT):
            return {
                "device_id": aip_msg.get("device_id", ""),
                "session_id": aip_msg.get("session_id", aip_msg.get("task_id", "")),
                "mesh_id": aip_msg.get("mesh_id", ""),
                "result": aip_msg.get("result", {}),
                "timestamp": aip_msg.get("timestamp", _now_ms()),
                "_aip_converted": True,
            }
        elif msg_type == AIP_CAPABILITY_REPORT:
            return {
                "device_id": aip_msg.get("device_id", ""),
                "capabilities": aip_msg.get("capabilities", []),
                "timestamp": aip_msg.get("timestamp", _now_ms()),
                "_aip_converted": True,
            }
        else:
            # Unknown type — return as-is with _aip_converted flag
            return {**aip_msg, "_aip_converted": True}
    except Exception as exc:
        logger.debug("from_aip_to_legacy conversion failed: %s", exc)
        return aip_msg


# ---------------------------------------------------------------------------
# Unified conversion dispatcher
# ---------------------------------------------------------------------------


def to_aip_v3(legacy_msg: Any, msg_kind: str = "") -> Dict[str, Any]:
    """Convert a legacy message to AIP v3 format.

    Args:
        legacy_msg: The legacy message (TaskDispatchModel, WorkerRegistrationModel, etc.)
        msg_kind: Optional hint for the message kind:
            "task_dispatch", "task_result", "heartbeat",
            "worker_registration", "worker_shutdown", "agent_event"

    Returns:
        AIP v3 message dict with "type" field set.
    """
    if isinstance(legacy_msg, dict) and legacy_msg.get("type") and legacy_msg.get("_aip_version"):
        # Already AIP v3
        return legacy_msg

    kind = msg_kind.lower()
    dispatchers = {
        "task_dispatch": to_aip_task_assign,
        "task_assign": to_aip_task_assign,
        "task_result": to_aip_task_result,
        "heartbeat": to_aip_heartbeat,
        "worker_registration": to_aip_device_register,
        "worker_shutdown": to_aip_worker_shutdown,
        "agent_event": to_aip_agent_event,
    }

    converter = dispatchers.get(kind)
    if converter:
        return converter(legacy_msg)

    # Auto-detect from dict keys
    data = _safe_dict(legacy_msg)
    if "target_worker_id" in data:
        return to_aip_task_assign(legacy_msg)
    if "worker_id" in data and "status" in data:
        return to_aip_heartbeat(legacy_msg)
    if "worker_id" in data and "registered_at" in data:
        return to_aip_device_register(legacy_msg)
    if "worker_id" in data and "reason" in data:
        return to_aip_worker_shutdown(legacy_msg)
    if "status" in data and "result" in data:
        return to_aip_task_result(legacy_msg)
    if "event_type" in data:
        return to_aip_agent_event(legacy_msg)

    # Fallback: wrap as generic AIP v3 message
    return {
        "type": msg_kind or "unknown",
        "payload": data,
        "timestamp": _now_ms(),
        "_aip_version": "3.0",
        "_aip_auto_detected": False,
    }
