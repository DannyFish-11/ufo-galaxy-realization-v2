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
DUAL_RUNTIME_PROTECTED_ENV = "DUAL_RUNTIME_CROSS_REPO_PROTECTED_VERIFICATION"

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

_TERMINAL_EXECUTION_PHASES = {
    "succeeded",
    "success",
    "completed",
    "failed",
    "failure",
    "error",
    # Keep both spellings for backward compatibility across emitters.
    "cancelled",
    "canceled",
    "aborted",
    "timed_out",
    "timeout",
    "interrupted",
    "interrupt",
}


def _is_protected_verification() -> bool:
    value = os.environ.get(DUAL_RUNTIME_PROTECTED_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def resolve_evidence_path() -> str:
    return (
        os.environ.get(DUAL_RUNTIME_EVIDENCE_ENV, "").strip()
        or os.environ.get(LEGACY_REAL_ANDROID_EVIDENCE_ENV, "").strip()
    )


def load_evidence_or_skip() -> Dict[str, Any]:
    path = resolve_evidence_path()
    if not path:
        reason = f"{DUAL_RUNTIME_EVIDENCE_ENV} (or {LEGACY_REAL_ANDROID_EVIDENCE_ENV}) not set"
        if _is_protected_verification():
            raise AssertionError(reason)
        pytest.skip(reason)
    evidence_path = Path(path)
    if not evidence_path.is_file():
        reason = f"Cross-repo evidence file does not exist: {evidence_path}"
        if _is_protected_verification():
            raise AssertionError(reason)
        pytest.skip(reason)
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
        raise AssertionError(f"Dual-runtime evidence missing canonical Android→V2 messages: {missing}")
    return [msgs_by_type[m] for m in _CANONICAL_ANDROID_TO_V2_TYPES]


def evidence_declares_real_android_runtime(evidence: Dict[str, Any]) -> bool:
    if evidence.get("is_real_device_e2e_verified") is True:
        return True
    if evidence.get("is_real_device_verified") is True:
        return True
    verification_kind = str(evidence.get("verification_kind", "") or "").strip().lower()
    if verification_kind in {"real_device", "real_runtime"}:
        return True
    return str(evidence.get("evidence_origin", "") or "").strip().lower() == "android_runtime_real_device"


def evidence_declares_v2_runtime_participation(evidence: Dict[str, Any]) -> bool:
    if evidence.get("is_v2_runtime_verified") is True:
        return True
    if evidence.get("is_dual_runtime_verified") is True:
        return True
    return any(str(msg.get("type", "")).strip().lower() in _V2_ACK_TYPES for msg in _iter_messages(evidence))


def _find_message(evidence: Dict[str, Any], expected_type: str) -> Dict[str, Any] | None:
    return next(
        (msg for msg in _iter_messages(evidence) if str(msg.get("type", "")).strip().lower() == expected_type),
        None,
    )


def _extract_execution_payload(evidence: Dict[str, Any]) -> Dict[str, Any]:
    execution_msg = _find_message(evidence, "device_execution_event")
    if isinstance(execution_msg, dict):
        payload = execution_msg.get("payload")
        if isinstance(payload, dict):
            return payload
    payload = evidence.get("device_execution_event_payload")
    return payload if isinstance(payload, dict) else {}


def build_dual_runtime_cross_repo_evidence_report(evidence: Dict[str, Any]) -> Dict[str, Any]:
    messages = list(_iter_messages(evidence))
    types = [str(msg.get("type", "")).strip().lower() for msg in messages]
    replay_missing = [t for t in _CANONICAL_ANDROID_TO_V2_TYPES if t not in types]

    replay_status = "not_evidenced"
    replay_detail: Dict[str, Any] = {"missing_types": replay_missing}
    if not replay_missing:
        positions = [types.index(t) for t in _CANONICAL_ANDROID_TO_V2_TYPES]
        in_order = positions == sorted(positions)
        replay_status = "evidenced" if in_order else "failed"
        replay_detail = {"positions": positions, "in_order": in_order}

    reconnect_marker = (
        evidence.get("reconnect_continuity_verified") is True
        or any("reconnect" in t or "resume" in t for t in types)
        or any(
            str(msg.get("correlation_id", "")).strip()
            for msg in messages
            if str(msg.get("type", "")).strip().lower() == "heartbeat"
        )
    )
    recovery_marker = (
        evidence.get("recovery_behavior_verified") is True
        or isinstance(evidence.get("recovery_state"), dict)
        or any("recovery" in t for t in types)
        or any(
            isinstance(msg.get("payload"), dict) and any("recovery" in str(k).lower() for k in msg["payload"].keys())
            for msg in messages
        )
    )

    execution_payload = _extract_execution_payload(evidence)
    execution_phase = str(execution_payload.get("phase", "")).strip().lower()
    # Prefer explicit closure flag when present; phase inference is backward-compatible fallback.
    if "closure_complete" in evidence:
        closure_complete = evidence.get("closure_complete") is True
    else:
        closure_complete = execution_phase in _TERMINAL_EXECUTION_PHASES

    behavior_checks = {
        "replay_ordering": {"status": replay_status, "detail": replay_detail},
        "reconnect_continuity": {
            "status": "evidenced" if reconnect_marker else "not_evidenced",
            "detail": {"signal_detected": reconnect_marker},
        },
        "recovery_behavior": {
            "status": "evidenced" if recovery_marker else "not_evidenced",
            "detail": {"signal_detected": recovery_marker},
        },
        "closure_completeness": {
            "status": "evidenced" if closure_complete else "not_evidenced",
            "detail": {"execution_phase": execution_phase or None},
        },
    }

    has_failed = any(v["status"] == "failed" for v in behavior_checks.values())
    all_evidenced = all(v["status"] == "evidenced" for v in behavior_checks.values())
    dual_runtime_declared = evidence_declares_real_android_runtime(
        evidence
    ) and evidence_declares_v2_runtime_participation(evidence)

    if has_failed:
        overall_state = "failed"
    elif all_evidenced and dual_runtime_declared:
        overall_state = "evidenced"
    else:
        overall_state = "partially_run"

    return {
        "schema_version": "1.0",
        "overall_state": overall_state,
        "dual_runtime_declared": dual_runtime_declared,
        "android_runtime_declared": evidence_declares_real_android_runtime(evidence),
        "v2_runtime_declared": evidence_declares_v2_runtime_participation(evidence),
        "behavior_checks": behavior_checks,
        "message_counts": {"total_messages": len(messages), "unique_types": sorted(set(types))},
    }


def build_dual_runtime_cross_repo_evidence_report_from_environment() -> Dict[str, Any]:
    path = resolve_evidence_path()
    if not path:
        return {
            "schema_version": "1.0",
            "overall_state": "not_run",
            "reason": f"{DUAL_RUNTIME_EVIDENCE_ENV} (or {LEGACY_REAL_ANDROID_EVIDENCE_ENV}) not set",
        }
    evidence_path = Path(path)
    if not evidence_path.is_file():
        return {
            "schema_version": "1.0",
            "overall_state": "failed",
            "reason": f"Cross-repo evidence file does not exist: {evidence_path}",
        }
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schema_version": "1.0",
            "overall_state": "failed",
            "reason": f"Unable to parse cross-repo evidence JSON: {exc}",
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": "1.0",
            "overall_state": "failed",
            "reason": "Dual-runtime cross-repo evidence must be a JSON object.",
        }

    report = build_dual_runtime_cross_repo_evidence_report(payload)
    report["evidence_path"] = str(evidence_path)
    return report
