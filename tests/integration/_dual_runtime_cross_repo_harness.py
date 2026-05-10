"""Harness helpers for V2↔Android true dual-runtime cross-repo regressions."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pytest

DUAL_RUNTIME_EVIDENCE_ENV = "DUAL_RUNTIME_CROSS_REPO_EVIDENCE_PATH"
LEGACY_REAL_ANDROID_EVIDENCE_ENV = "REAL_ANDROID_GOVERNANCE_EVIDENCE_PATH"

_CANONICAL_ANDROID_TO_V2_TYPES = (
    "device_register",
    "capability_report",
    "device_state_snapshot",
    "device_execution_event",
)

_V2_ACK_TYPES = {
    "device_register_ack",
    "capability_report_ack",
    "device_state_snapshot_ack",
    "device_execution_event_ack",
    "heartbeat_ack",
}


def resolve_evidence_path() -> str:
    return (
        os.environ.get(DUAL_RUNTIME_EVIDENCE_ENV, "").strip()
        or os.environ.get(LEGACY_REAL_ANDROID_EVIDENCE_ENV, "").strip()
    )


def load_evidence_or_skip() -> Dict[str, Any]:
    path = resolve_evidence_path()
    if not path:
        pytest.skip(
            f"{DUAL_RUNTIME_EVIDENCE_ENV} (or {LEGACY_REAL_ANDROID_EVIDENCE_ENV}) not set"
        )
    evidence_path = Path(path)
    if not evidence_path.is_file():
        pytest.skip(f"Cross-repo evidence file does not exist: {evidence_path}")
    with evidence_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise AssertionError("Dual-runtime cross-repo evidence must be a JSON object.")
    return payload


def _iter_messages(evidence: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for key in ("messages", "aip_messages", "events"):
        value = evidence.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item


def _normalise_message(msg: Dict[str, Any], fallback_device_id: str) -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    return {
        "version": str(msg.get("version") or "3.0"),
        "type": str(msg.get("type") or "").strip().lower(),
        "message_id": str(msg.get("message_id") or uuid.uuid4()),
        "device_id": str(msg.get("device_id") or fallback_device_id),
        "timestamp": int(msg.get("timestamp") or now_ms),
        **{k: v for k, v in msg.items() if k not in {"version", "type", "message_id", "device_id", "timestamp"}},
    }


def extract_canonical_android_runtime_messages(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    fallback_device_id = str(evidence.get("device_id") or "").strip()
    msgs_by_type: Dict[str, Dict[str, Any]] = {}
    for raw in _iter_messages(evidence):
        normalised = _normalise_message(raw, fallback_device_id)
        msg_type = normalised.get("type")
        if msg_type in _CANONICAL_ANDROID_TO_V2_TYPES and msg_type not in msgs_by_type:
            msgs_by_type[msg_type] = normalised

    for message_type, payload_key in (
        ("device_state_snapshot", "device_state_snapshot_payload"),
        ("device_execution_event", "device_execution_event_payload"),
    ):
        payload = evidence.get(payload_key)
        if message_type not in msgs_by_type and isinstance(payload, dict):
            msgs_by_type[message_type] = _normalise_message(
                {"type": message_type, "payload": payload},
                fallback_device_id,
            )

    missing = [m for m in _CANONICAL_ANDROID_TO_V2_TYPES if m not in msgs_by_type]
    if missing:
        raise AssertionError(
            f"Dual-runtime evidence missing canonical Android→V2 messages: {missing}"
        )
    return [msgs_by_type[m] for m in _CANONICAL_ANDROID_TO_V2_TYPES]


def evidence_declares_real_android_runtime(evidence: Dict[str, Any]) -> bool:
    if evidence.get("is_real_device_e2e_verified") is True:
        return True
    if evidence.get("is_real_device_verified") is True:
        return True
    verification_kind = str(evidence.get("verification_kind", "") or "").strip().lower()
    if verification_kind in {"real_device", "real_runtime"}:
        return True
    return (
        str(evidence.get("evidence_origin", "") or "").strip().lower()
        == "android_runtime_real_device"
    )


def evidence_declares_v2_runtime_participation(evidence: Dict[str, Any]) -> bool:
    if evidence.get("is_v2_runtime_verified") is True:
        return True
    if evidence.get("is_dual_runtime_verified") is True:
        return True
    return any(
        str(msg.get("type", "")).strip().lower() in _V2_ACK_TYPES
        for msg in _iter_messages(evidence)
    )
