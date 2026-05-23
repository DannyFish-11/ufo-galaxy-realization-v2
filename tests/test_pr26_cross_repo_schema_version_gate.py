from __future__ import annotations

import re
from pathlib import Path

from contracts.cross_repo_schema_version_gate import (
    ANDROID_AIP_MODELS_ANCHOR,
    ANDROID_AIP_MODELS_SOURCE_SHA,
    ANDROID_AUDITED_REF,
    ANDROID_CANONICAL_DEDUPE_CONTRACT_VERSION,
    ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION,
    ANDROID_COMPLETION_CLOSURE_ANCHOR,
    ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA,
    CROSS_REPO_SCHEMA_GATE_VERSION,
    REQUIRED_DIAGNOSTICS_SNAPSHOT_FIELDS,
    REQUIRED_PARTICIPATION_TRUTH_FIELDS,
    REQUIRED_SCHEMA_GATE_METADATA_FIELDS,
    REQUIRED_SHARED_EXECUTION_VISIBILITY_FIELDS,
    REQUIRED_STARTUP_READINESS_FIELDS,
    REQUIRED_AIP_MESSAGE_TYPES,
    build_cross_repo_schema_gate_manifest,
    build_projection_schema_gate_metadata,
    evaluate_android_uplink_dedupe_contract,
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
    assert manifest["android_canonical_dedupe_contract_version"] == ANDROID_CANONICAL_DEDUPE_CONTRACT_VERSION
    assert manifest["android_audited_ref"] == ANDROID_AUDITED_REF
    assert manifest["android_aip_models_source_sha"] == ANDROID_AIP_MODELS_SOURCE_SHA
    assert manifest["android_completion_closure_source_sha"] == ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA
    assert manifest["android_anchors"]["aip_models"] == ANDROID_AIP_MODELS_ANCHOR
    assert manifest["android_anchors"]["completion_closure_uplink_contract"] == ANDROID_COMPLETION_CLOSURE_ANCHOR
    assert len(ANDROID_AUDITED_REF) == 40
    assert len(ANDROID_AIP_MODELS_SOURCE_SHA) == 40
    assert len(ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA) == 40


def test_cross_repo_schema_gate_manifest_exposes_android_dedupe_contracts() -> None:
    manifest = build_cross_repo_schema_gate_manifest()
    contracts = manifest["android_dedupe_contracts"]
    assert set(contracts) == {"result", "reconciliation", "replay"}
    assert "goal_execution_result" in contracts["result"]["message_types"]
    assert contracts["result"]["dedup_key"]["enforced"] is True
    assert "reconciliation_signal" in contracts["reconciliation"]["message_types"]
    assert contracts["replay"]["dedup_key"]["fields"] == [
        "replay_session_id",
        "replay_item_id",
        "replay_seq",
    ]
    assert REQUIRED_SHARED_EXECUTION_VISIBILITY_FIELDS.issubset(set(manifest["required_shared_execution_visibility_fields"]))
    assert REQUIRED_STARTUP_READINESS_FIELDS.issubset(set(manifest["required_startup_readiness_fields"]))
    assert REQUIRED_PARTICIPATION_TRUTH_FIELDS.issubset(set(manifest["required_participation_truth_fields"]))
    assert REQUIRED_DIAGNOSTICS_SNAPSHOT_FIELDS.issubset(set(manifest["required_diagnostics_snapshot_fields"]))
    assert REQUIRED_SCHEMA_GATE_METADATA_FIELDS.issubset(set(manifest["required_schema_gate_metadata_fields"]))


def test_required_aip_message_types_are_present_in_v2_enum() -> None:
    wire_values = _read_message_type_wire_values()
    assert REQUIRED_AIP_MESSAGE_TYPES.issubset(wire_values)


def test_verify_cross_repo_schema_gate_passes_for_minimal_valid_payload() -> None:
    runtime_truth_payload = {
        "outward_truth": {},
        "task_truth": {},
        "startup_readiness": {
            "ready_to_route": False,
            "readiness_notes": ["contract-test"],
        },
        "runtime_decision_reasoning": {},
        "shared_execution_visibility": {
            "completion_state": "not_started",
            "closure_candidate_state": "not_started",
            "authority_completion_truth": False,
            "acceptance_completion_truth": False,
            "advisory_evidence_only": True,
            "canonical_confirmation_present": False,
            "evidence_provenance": "unknown",
            "evidence_completeness": "unknown",
            "surface_execution_stage": None,
        },
        "participation_truth_consumption": {
            "participation_tier": "runtime_present",
            "device_lifecycle_stage": None,
            "all_device_participation_matrix": {},
            "completion_state": "not_started",
        },
        "truth_acceptance_closure_contract": {
            "authority_truth_source": {},
            "acceptance_closure_truth": {
                "authority_completion_truth": False,
                "acceptance_completion_truth": False,
                "acceptance_verdict": "pending",
                "closure_quality": "open",
                "evidence_completeness": "unknown",
                "evidence_provenance": "unknown",
                "advisory_evidence_only": True,
                "canonical_confirmation_present": False,
                "repo_mutation_completion_truth": "unknown",
                "closure_candidate_state": "not_started",
                "completion_state": "not_started",
                "is_fully_closed": False,
            },
            "outward_projection_truth": {},
            "diagnostics_snapshot": {
                "chain_overall_status": "open",
                "failure_boundaries": [],
            },
            "gate_candidate": {},
            "schema_gate": build_projection_schema_gate_metadata(),
        },
    }
    report = verify_cross_repo_schema_gate(
        message_type_values=_read_message_type_wire_values(),
        runtime_truth_payload=runtime_truth_payload,
    )
    assert report.passed, report.issues


def test_verify_cross_repo_schema_gate_rejects_missing_shared_execution_contract_fields() -> None:
    report = verify_cross_repo_schema_gate(
        message_type_values=_read_message_type_wire_values(),
        runtime_truth_payload={
            "outward_truth": {},
            "task_truth": {},
            "startup_readiness": {"ready_to_route": True, "readiness_notes": []},
            "runtime_decision_reasoning": {},
            "shared_execution_visibility": {"completion_state": "in_progress"},
            "participation_truth_consumption": {
                "participation_tier": "runtime_present",
                "device_lifecycle_stage": None,
                "all_device_participation_matrix": {},
                "completion_state": "in_progress",
            },
            "truth_acceptance_closure_contract": {
                "authority_truth_source": {},
                "acceptance_closure_truth": {
                    "authority_completion_truth": False,
                    "acceptance_completion_truth": False,
                    "acceptance_verdict": "pending",
                    "closure_quality": "open",
                    "evidence_completeness": "unknown",
                    "evidence_provenance": "unknown",
                    "advisory_evidence_only": True,
                    "canonical_confirmation_present": False,
                    "repo_mutation_completion_truth": "unknown",
                    "closure_candidate_state": "in_progress",
                    "completion_state": "in_progress",
                    "is_fully_closed": False,
                },
                "outward_projection_truth": {},
                "diagnostics_snapshot": {"chain_overall_status": "open", "failure_boundaries": []},
                "gate_candidate": {},
                "schema_gate": build_projection_schema_gate_metadata(),
            },
        },
    )
    assert report.passed is False
    assert any("shared_execution_visibility is missing required fields:" in issue for issue in report.issues)


def test_verify_cross_repo_schema_gate_rejects_schema_gate_sha_drift() -> None:
    metadata = build_projection_schema_gate_metadata()
    metadata["android_aip_models_source_sha"] = "0" * 40
    report = verify_cross_repo_schema_gate(
        message_type_values=_read_message_type_wire_values(),
        runtime_truth_payload={
            "outward_truth": {},
            "task_truth": {},
            "startup_readiness": {"ready_to_route": False, "readiness_notes": []},
            "runtime_decision_reasoning": {},
            "shared_execution_visibility": {
                "completion_state": "not_started",
                "closure_candidate_state": "not_started",
                "authority_completion_truth": False,
                "acceptance_completion_truth": False,
                "advisory_evidence_only": True,
                "canonical_confirmation_present": False,
                "evidence_provenance": "unknown",
                "evidence_completeness": "unknown",
                "surface_execution_stage": None,
            },
            "participation_truth_consumption": {
                "participation_tier": "runtime_present",
                "device_lifecycle_stage": None,
                "all_device_participation_matrix": {},
                "completion_state": "not_started",
            },
            "truth_acceptance_closure_contract": {
                "authority_truth_source": {},
                "acceptance_closure_truth": {
                    "authority_completion_truth": False,
                    "acceptance_completion_truth": False,
                    "acceptance_verdict": "pending",
                    "closure_quality": "open",
                    "evidence_completeness": "unknown",
                    "evidence_provenance": "unknown",
                    "advisory_evidence_only": True,
                    "canonical_confirmation_present": False,
                    "repo_mutation_completion_truth": "unknown",
                    "closure_candidate_state": "not_started",
                    "completion_state": "not_started",
                    "is_fully_closed": False,
                },
                "outward_projection_truth": {},
                "diagnostics_snapshot": {"chain_overall_status": "open", "failure_boundaries": []},
                "gate_candidate": {},
                "schema_gate": metadata,
            },
        },
    )
    assert report.passed is False
    assert any("schema_gate.android_aip_models_source_sha drift detected:" in issue for issue in report.issues)


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


def test_android_result_dedupe_contract_accepts_canonical_fields() -> None:
    decision = evaluate_android_uplink_dedupe_contract(
        message_type="goal_execution_result",
        message={
            "version": "3.0",
            "type": "goal_execution_result",
            "payload": {
                "task_id": "task-1",
                "idempotency_key": "goal_execution_result:task-1",
                "completion_emission_id": "emit-1",
            },
        },
    )
    assert decision is not None
    assert decision.action == "accept"
    assert decision.contract_class == "result"


def test_android_result_dedupe_contract_degrades_missing_stable_identity() -> None:
    decision = evaluate_android_uplink_dedupe_contract(
        message_type="task_result",
        message={
            "version": "3.0",
            "type": "task_result",
            "payload": {"task_id": "task-1"},
        },
    )
    assert decision is not None
    assert decision.action == "degrade"
    assert decision.reason == "missing_canonical_result_dedupe_fields"
    assert "idempotency_key" in decision.evidence["missing_fields"]
    assert "completion_emission_id" in decision.evidence["missing_fields"]


def test_android_reconciliation_dedupe_contract_accepts_scope_and_signal_identity() -> None:
    decision = evaluate_android_uplink_dedupe_contract(
        message_type="reconciliation_signal",
        message={
            "version": "3.0",
            "type": "reconciliation_signal",
            "payload": {
                "contract_id": "contract-1",
                "reconciliation_id": "recon-7",
            },
        },
    )
    assert decision is not None
    assert decision.action == "accept"
    assert decision.contract_class == "reconciliation"


def test_android_reconciliation_dedupe_contract_degrades_missing_identity() -> None:
    decision = evaluate_android_uplink_dedupe_contract(
        message_type="device_execution_event",
        message={
            "version": "3.0",
            "type": "device_execution_event",
            "payload": {"runtime_session_id": "session-1"},
        },
    )
    assert decision is not None
    assert decision.action == "degrade"
    assert decision.reason == "missing_canonical_reconciliation_dedupe_fields"
    assert decision.evidence["subject_identity_present"] is True
    assert decision.evidence["reconciliation_identity_present"] is False
