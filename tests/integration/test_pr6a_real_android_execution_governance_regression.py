"""PR-6A real Android-participating governance regression paths.

These regressions consume a real Android runtime evidence artifact instead of
Python stubs/protocol-only simulation.  The artifact path is provided via:

    REAL_ANDROID_GOVERNANCE_EVIDENCE_PATH=/abs/path/to/android_runtime_evidence.json
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, Tuple

import pytest

from core.android_device_state_store import (
    absorb_device_execution_event,
    absorb_device_state_snapshot,
    reset_android_device_state_store,
)
from core.unified_execution_governance import (
    ExecutionType,
    _clear_execution_governance_runtime_state,
    _register_active_execution,
    evaluate_execution_governance,
    get_execution_runtime_snapshot,
)
from core.unified_governance_semantics import build_unified_governance_state


_REAL_ANDROID_EVIDENCE_ENV = "REAL_ANDROID_GOVERNANCE_EVIDENCE_PATH"
_ACTIVE_OR_TERMINAL_QUALITY = {
    "android_remote_confirmed",
    "conflicting_remote",
    "stale_remote",
}


def _load_real_android_runtime_evidence() -> Dict[str, Any]:
    path = os.environ.get(_REAL_ANDROID_EVIDENCE_ENV, "").strip()
    if not path:
        pytest.skip(f"{_REAL_ANDROID_EVIDENCE_ENV} not set")
    if not os.path.isfile(path):
        pytest.skip(f"{_REAL_ANDROID_EVIDENCE_ENV} does not exist: {path}")
    with open(path, "r", encoding="utf-8") as f:
        evidence = json.load(f)
    if not isinstance(evidence, dict):
        raise AssertionError("Real Android runtime evidence must be a JSON object.")
    return evidence


def _find_message_by_type(messages: list[Any], message_type: str) -> Dict[str, Any] | None:
    """Return first AIP message matching *message_type* after strip/lower normalization."""
    return next(
        (
            m
            for m in messages
            if isinstance(m, dict) and str(m.get("type", "")).strip().lower() == message_type
        ),
        None,
    )


def _extract_runtime_payloads(evidence: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    # Android runtime evidence has appeared under multiple top-level list keys
    # across cross-repo iterations; support all known variants for compatibility.
    messages = evidence.get("messages")
    if not isinstance(messages, list):
        messages = evidence.get("aip_messages")
    if not isinstance(messages, list):
        messages = evidence.get("events")
    if not isinstance(messages, list):
        messages = []

    state_msg = _find_message_by_type(messages, "device_state_snapshot")
    event_msg = _find_message_by_type(messages, "device_execution_event")

    snapshot_payload = evidence.get("device_state_snapshot_payload")
    execution_payload = evidence.get("device_execution_event_payload")
    device_id = str(evidence.get("device_id", "") or "").strip()

    if isinstance(state_msg, dict):
        snapshot_payload = state_msg.get("payload", snapshot_payload)
        device_id = device_id or str(state_msg.get("device_id", "") or "").strip()
    if isinstance(event_msg, dict):
        execution_payload = event_msg.get("payload", execution_payload)
        device_id = device_id or str(event_msg.get("device_id", "") or "").strip()

    if not isinstance(snapshot_payload, dict):
        raise AssertionError("Missing device_state_snapshot payload in real Android evidence.")
    if not isinstance(execution_payload, dict):
        raise AssertionError("Missing device_execution_event payload in real Android evidence.")
    if not device_id:
        raise AssertionError("Missing device_id in real Android evidence.")

    return device_id, snapshot_payload, execution_payload


def _extract_real_participation_claim(evidence: Dict[str, Any]) -> bool:
    if evidence.get("is_real_device_e2e_verified") is True:
        return True
    if evidence.get("is_real_device_verified") is True:
        return True
    verification_kind = str(evidence.get("verification_kind", "") or "").strip().lower()
    if verification_kind == "real_device":
        return True
    return str(evidence.get("evidence_origin", "") or "").strip().lower() == "android_runtime_real_device"


def test_real_android_artifact_declares_real_runtime_participation() -> None:
    evidence = _load_real_android_runtime_evidence()
    assert _extract_real_participation_claim(evidence), (
        "Evidence must explicitly prove real-device Android runtime participation "
        "(verification_kind=real_device or equivalent boolean marker)."
    )


def test_real_android_runtime_participation_drives_v2_governance_regression_path() -> None:
    evidence = _load_real_android_runtime_evidence()
    device_id, snapshot_payload, execution_payload = _extract_runtime_payloads(evidence)

    _clear_execution_governance_runtime_state()
    reset_android_device_state_store()
    try:
        absorb_device_state_snapshot(device_id, snapshot_payload)
        absorb_device_execution_event(device_id, execution_payload)

        _register_active_execution(
            device_id,
            ExecutionType.takeover_request,
            f"tk_{uuid.uuid4().hex[:8]}",
        )
        _register_active_execution(
            device_id,
            ExecutionType.delegated_execution,
            f"dg_{uuid.uuid4().hex[:8]}",
        )

        blocked = evaluate_execution_governance(
            ExecutionType.goal_execution,
            device_id,
            execution_id=f"incoming_{uuid.uuid4().hex[:8]}",
            register_if_accepted=False,
        )
        assert blocked.accepted is False
        assert blocked.conflict is True
        assert blocked.active_conflicting_type == ExecutionType.takeover_request

        snapshot = get_execution_runtime_snapshot(device_ids=[device_id])
        per_device = next(
            d for d in snapshot.get("devices", []) if d.get("device_id") == device_id
        )
        assert per_device["active_execution_count"] == 2
        assert "goal_execution" in per_device["blocked_execution_types"]
        assert per_device["android_lifecycle_truth_quality"] in _ACTIVE_OR_TERMINAL_QUALITY

        governance = build_unified_governance_state(device_ids=[device_id])
        device_view = next(
            d for d in governance.get("devices", []) if d.get("device_id") == device_id
        )
        delegated = device_view["governance_precedence"]["delegated_execution"]
        causality = delegated["decision_causality"]
        assert causality["active_execution_count"] == 2
        assert "goal_execution" in causality["blocked_execution_types"]
        assert causality["android_lifecycle_truth_quality"] == per_device["android_lifecycle_truth_quality"]
        assert causality["android_lifecycle_truth_governance_impact"] == per_device[
            "android_lifecycle_truth_governance_impact"
        ]
    finally:
        _clear_execution_governance_runtime_state()
        reset_android_device_state_store()
