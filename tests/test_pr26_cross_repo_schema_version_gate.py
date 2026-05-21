from __future__ import annotations

import re
from pathlib import Path

from contracts.cross_repo_schema_version_gate import (
    ANDROID_AIP_MODELS_ANCHOR,
    ANDROID_AIP_MODELS_SOURCE_SHA,
    ANDROID_AUDITED_REF,
    ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION,
    ANDROID_COMPLETION_CLOSURE_ANCHOR,
    ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA,
    CROSS_REPO_SCHEMA_GATE_VERSION,
    REQUIRED_AIP_MESSAGE_TYPES,
    build_cross_repo_schema_gate_manifest,
    build_projection_schema_gate_metadata,
    evaluate_android_uplink_schema_gate,
    verify_cross_repo_schema_gate,
)


def _read_message_type_wire_values() -> set[str]:
    repo_root = Path(__file__).resolve().parent.parent
    aip_source = (repo_root / "galaxy_gateway" / "protocol" / "aip_v3.py").read_text(encoding="utf-8")
    match = re.search(
        r"class MessageType\(str, Enum\):.*?(?:\nclass TaskStatus)",
        aip_source,
        flags=re.DOTALL,
    )
    assert match is not None, "Unable to find MessageType enum in aip_v3.py"
    return set(re.findall(r"\b[A-Z0-9_]+\s*=\s*\"([a-z0-9_]+)\"", match.group(0)))


def test_cross_repo_schema_gate_manifest_is_versioned_and_anchored() -> None:
    manifest = build_cross_repo_schema_gate_manifest()
    assert manifest["gate_version"] == CROSS_REPO_SCHEMA_GATE_VERSION
    assert manifest["android_audited_ref"] == ANDROID_AUDITED_REF
    assert manifest["android_aip_models_source_sha"] == ANDROID_AIP_MODELS_SOURCE_SHA
    assert manifest["android_completion_closure_source_sha"] == ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA
    assert manifest["android_anchors"]["aip_models"] == ANDROID_AIP_MODELS_ANCHOR
    assert (
        manifest["android_anchors"]["completion_closure_uplink_contract"]
        == ANDROID_COMPLETION_CLOSURE_ANCHOR
    )
    assert len(ANDROID_AUDITED_REF) == 40
    assert len(ANDROID_AIP_MODELS_SOURCE_SHA) == 40
    assert len(ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA) == 40


def test_required_aip_message_types_are_present_in_v2_enum() -> None:
    wire_values = _read_message_type_wire_values()
    assert REQUIRED_AIP_MESSAGE_TYPES.issubset(wire_values)


def test_verify_cross_repo_schema_gate_passes_for_minimal_valid_payload() -> None:
    runtime_truth_payload = {
        "outward_truth": {},
        "task_truth": {},
        "startup_readiness": {},
        "runtime_decision_reasoning": {},
        "shared_execution_visibility": {"completion_state": "not_started"},
        "participation_truth_consumption": {},
        "truth_acceptance_closure_contract": {
            "authority_truth_source": {},
            "acceptance_closure_truth": {
                "authority_completion_truth": False,
                "acceptance_completion_truth": False,
                "closure_candidate_state": "not_started",
                "completion_state": "not_started",
            },
            "outward_projection_truth": {},
            "diagnostics_snapshot": {},
            "gate_candidate": {},
            "schema_gate": build_projection_schema_gate_metadata(),
        },
    }
    report = verify_cross_repo_schema_gate(
        message_type_values=_read_message_type_wire_values(),
        runtime_truth_payload=runtime_truth_payload,
    )
    assert report.passed, report.issues


def test_runtime_schema_gate_rejects_completion_uplink_without_schema_version() -> None:
    decision = evaluate_android_uplink_schema_gate(
        message_type="handoff_result",
        message={
            "type": "handoff_result",
            "payload": {
                "completion_closure_contract_version": ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION,
            },
        },
    )
    assert decision is not None
    assert decision.action == "reject"
    assert decision.reason == "missing_schema_version_metadata"


def test_runtime_schema_gate_degrades_old_reconciliation_uplink_schema_version() -> None:
    decision = evaluate_android_uplink_schema_gate(
        message_type="reconciliation_signal",
        message={
            "type": "reconciliation_signal",
            "payload": {"schema_version": "0"},
        },
    )
    assert decision is not None
    assert decision.action == "degrade"
    assert decision.reason in {"legacy_schema_version_compat", "older_schema_version_compat"}


def test_runtime_schema_gate_rejects_completion_contract_mismatch() -> None:
    decision = evaluate_android_uplink_schema_gate(
        message_type="handoff_envelope_v2_result",
        message={
            "type": "handoff_envelope_v2_result",
            "payload": {
                "schema_version": "1",
                "completion_closure_contract_version": "0",
            },
        },
    )
    assert decision is not None
    assert decision.action == "reject"
    assert decision.reason == "completion_closure_contract_mismatch"


def test_runtime_schema_gate_accepts_matching_uplink_schema_version() -> None:
    decision = evaluate_android_uplink_schema_gate(
        message_type="device_state_snapshot",
        message={
            "type": "device_state_snapshot",
            "payload": {"schema_version": "1"},
        },
    )
    assert decision is not None
    assert decision.action == "accept"
    assert decision.reason == "schema_version_gate_matched"
