"""Dedicated handler for Android DEVICE_ACCEPTANCE_REPORT uplink."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from core.android_acceptance_evidence_store import ingest_device_acceptance_report
from core.android_evaluator_artifact_ingress import ingest_android_evaluator_artifact
from core.unified_action_lifecycle_surface import (
    ActionLifecyclePhase,
    ActionOrigin,
    ClosureState,
    UnifiedActionLifecycleSurface,
    derive_visible_action,
)
from galaxy_gateway.android.handlers.evaluator_artifact_report import (
    _truth_reconciled_flag,
)

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_device_acceptance_report(
    _bridge: "AndroidBridge", _websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """摄取 Android acceptance 证据并返回结构化 ACK。"""
    msg_type = message.get("type")
    device_id = str(message.get("device_id") or "")
    payload = message.get("payload")
    payload_dict = payload if isinstance(payload, dict) else {}

    record = ingest_device_acceptance_report(
        device_id=device_id,
        payload=payload_dict,
        message_id=str(message.get("message_id") or ""),
    )
    logger.info(
        "android acceptance report ingested: device_id=%s acceptance_tag=%s mapped_proof=%s",
        device_id,
        record.acceptance_tag,
        record.mapped_android_proof_class,
    )
    evaluator_outcome = ingest_android_evaluator_artifact(
        {
            "type": "governance_artifact",
            "device_id": device_id,
            "message_id": message.get("message_id"),
            "task_id": str(message.get("task_id") or payload_dict.get("task_id") or ""),
            "payload": {
                **payload_dict,
                "evaluator_kind": "acceptance",
                "session_id": str(payload_dict.get("session_id") or message.get("session_id") or ""),
                "contract_id": str(payload_dict.get("contract_id") or message.get("contract_id") or ""),
                "trace_id": str(payload_dict.get("trace_id") or message.get("trace_id") or ""),
            },
        }
    )
    ack_type = (
        f"{msg_type}_ack"
        if isinstance(msg_type, str) and msg_type.strip()
        else "device_acceptance_report_ack"
    )
    action_surface = UnifiedActionLifecycleSurface(
        action_id=str(message.get("message_id") or ""),
        session_id=str(payload_dict.get("session_id") or message.get("session_id") or ""),
        task_id=str(message.get("task_id") or payload_dict.get("task_id") or ""),
        device_id=device_id,
        phase=ActionLifecyclePhase.accepted,
        origin=ActionOrigin.android_device,
        accepted=True,
        acceptance_tag=record.acceptance_tag,
        execution_state="accepted",
        closure_state=ClosureState.handoff_pending,
        closure_reason="android_acceptance_report_received",
        last_android_event="acceptance_report",
    )
    visible_action = derive_visible_action(action_surface)
    return {
        "type": ack_type,
        "device_id": device_id,
        "status": "received",
        "message_id": message.get("message_id"),
        "acceptance_evidence_ingested": True,
        "acceptance_tag": record.acceptance_tag,
        "mapped_android_proof_class": record.mapped_android_proof_class,
        "mapped_evidence_trust_level": record.mapped_evidence_trust_level,
        "evidence_snapshot_id": record.snapshot_id,
        "evaluator_kind": "acceptance",
        "evaluator_artifact_ingested": bool(evaluator_outcome.was_stored),
        "truth_ingress_reconciled": _truth_reconciled_flag(evaluator_outcome),
        "canonical_update": evaluator_outcome.canonical_update or "",
        "ingress_reject_reason": evaluator_outcome.reject_reason or "",
        "action_lifecycle_surface": action_surface.to_dict(),
        "visible_action": visible_action,
    }
