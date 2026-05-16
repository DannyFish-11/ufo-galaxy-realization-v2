"""Dedicated handler for Android DEVICE_ACCEPTANCE_REPORT uplink."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from core.android_acceptance_evidence_store import ingest_device_acceptance_report

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
    return {
        "type": f"{msg_type}_ack" if msg_type else "ack",
        "device_id": device_id,
        "status": "received",
        "message_id": message.get("message_id"),
        "acceptance_evidence_ingested": True,
        "acceptance_tag": record.acceptance_tag,
        "mapped_android_proof_class": record.mapped_android_proof_class,
        "mapped_evidence_trust_level": record.mapped_evidence_trust_level,
        "evidence_snapshot_id": record.snapshot_id,
    }
