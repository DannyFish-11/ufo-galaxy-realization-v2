"""Canonical Android evaluator artifact report ingress handler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from core.android_evaluator_artifact_ingress import ingest_android_evaluator_artifact

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

_REPORT_TO_EVALUATOR_KIND = {
    "device_readiness_report": "readiness",
    "device_governance_report": "governance",
    "device_strategy_report": "strategy",
}


def _resolve_evaluator_kind(msg_type: str, payload: Dict[str, Any]) -> str:
    if not msg_type:
        return ""
    mapped = _REPORT_TO_EVALUATOR_KIND.get(msg_type.strip().lower(), "")
    if mapped:
        return mapped
    raw = payload.get("evaluator_kind")
    return str(raw).strip().lower() if isinstance(raw, str) else ""


async def handle_evaluator_artifact_report(
    _bridge: "AndroidBridge", _websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Ingest Android readiness/governance/strategy reports via canonical evaluator ingress."""
    msg_type = str(message.get("type") or "")
    device_id = str(message.get("device_id") or "")
    payload = message.get("payload")
    payload_dict = payload if isinstance(payload, dict) else {}
    evaluator_kind = _resolve_evaluator_kind(msg_type, payload_dict)

    canonical_message: Dict[str, Any] = {
        "type": "governance_artifact",
        "device_id": device_id,
        "task_id": str(message.get("task_id") or payload_dict.get("task_id") or ""),
        "message_id": message.get("message_id"),
        "payload": {
            **payload_dict,
            "evaluator_kind": evaluator_kind,
            "session_id": str(payload_dict.get("session_id") or message.get("session_id") or ""),
            "contract_id": str(payload_dict.get("contract_id") or message.get("contract_id") or ""),
            "trace_id": str(payload_dict.get("trace_id") or message.get("trace_id") or ""),
        },
    }

    outcome = ingest_android_evaluator_artifact(canonical_message)
    reject_reason: str = outcome.reject_reason or ""
    canonical_update: str = outcome.canonical_update or ""
    truth_reconciled: Optional[bool] = None
    if outcome.truth_reconcile_outcome is not None:
        truth_reconciled = bool(getattr(outcome.truth_reconcile_outcome, "was_reconciled", False))

    logger.info(
        "android evaluator report ingested: type=%s device_id=%s evaluator_kind=%s stored=%s reject=%s",
        msg_type,
        device_id,
        evaluator_kind,
        outcome.was_stored,
        reject_reason,
    )

    ack_type = f"{msg_type}_ack" if msg_type else "device_evaluator_report_ack"
    return {
        "type": ack_type,
        "device_id": device_id,
        "status": "received",
        "message_id": message.get("message_id"),
        "evaluator_kind": evaluator_kind,
        "evaluator_artifact_ingested": bool(outcome.was_stored),
        "truth_ingress_reconciled": truth_reconciled,
        "canonical_update": canonical_update,
        "ingress_reject_reason": reject_reason,
    }
