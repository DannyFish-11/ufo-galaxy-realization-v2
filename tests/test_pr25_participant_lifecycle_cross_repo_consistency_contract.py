"""PR-25: V2↔Android participant lifecycle/governance consistency contract tests."""

from __future__ import annotations

from contracts.participant_lifecycle_cross_repo_contract import (
    ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_ALLOWED,
    ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_BLOCKED,
    ANDROID_FORMAL_STATE_CLASS_BY_WIRE,
    ANDROID_FORMAL_WIRE_VALUES,
    ANDROID_AUDITED_REF,
    CRITICAL_TRIGGER_SEMANTIC_MAPPINGS,
    PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_AUTHORITY,
    PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_VERSION,
    V2_STATE_CLASS_BY_STATE,
    V2_TERMINAL_STATES,
    build_participant_lifecycle_cross_repo_contract_manifest,
    verify_participant_lifecycle_cross_repo_contract,
)
from contracts.participant_lifecycle_schema import ParticipantLifecycleState

SHA1_HASH_LENGTH = 40


def test_authority_sentinel_and_version_present() -> None:
    assert "PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_AUTHORITY" in (
        PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_AUTHORITY
    )
    assert PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_VERSION == "1.0.0"
    assert len(ANDROID_AUDITED_REF) == SHA1_HASH_LENGTH


def test_v2_state_class_mapping_covers_all_states() -> None:
    assert set(V2_STATE_CLASS_BY_STATE.keys()) == set(ParticipantLifecycleState)


def test_android_formal_wire_values_and_state_classes_are_closed() -> None:
    expected = {"starting", "ready", "degraded", "recovering", "unavailable_failed"}
    assert set(ANDROID_FORMAL_WIRE_VALUES) == expected
    assert set(ANDROID_FORMAL_STATE_CLASS_BY_WIRE.keys()) == expected


def test_android_capability_gates_partition_is_complete() -> None:
    assert ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_ALLOWED.isdisjoint(
        ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_BLOCKED
    )
    assert (
        ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_ALLOWED
        | ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_BLOCKED
    ) == ANDROID_FORMAL_WIRE_VALUES


def test_terminal_boundary_is_v2_only() -> None:
    assert V2_TERMINAL_STATES == {ParticipantLifecycleState.TERMINAL}


def test_critical_trigger_semantic_mapping_count_and_uniqueness() -> None:
    assert len(CRITICAL_TRIGGER_SEMANTIC_MAPPINGS) >= 5
    keys = {
        (m.trigger.value, m.v2_from_state.value, m.v2_to_state.value)
        for m in CRITICAL_TRIGGER_SEMANTIC_MAPPINGS
    }
    assert len(keys) == len(CRITICAL_TRIGGER_SEMANTIC_MAPPINGS)


def test_verify_contract_passes_on_calibrated_snapshot() -> None:
    report = verify_participant_lifecycle_cross_repo_contract()
    assert report.passed, f"Unexpected issues: {report.issues}"
    assert report.issues == []


def test_verify_contract_detects_android_wire_drift() -> None:
    report = verify_participant_lifecycle_cross_repo_contract(
        android_wire_values={"starting", "ready", "degraded", "recovering"}
    )
    assert not report.passed
    assert any("missing" in issue.lower() for issue in report.issues)


def test_manifest_contains_machine_checkable_sections() -> None:
    payload = build_participant_lifecycle_cross_repo_contract_manifest()
    assert payload["v2_role"] == "canonical_governance_center"
    assert payload["android_role"] == "bounded_relative_subject_runtime"
    assert isinstance(payload["android_audited_ref"], str) and len(payload["android_audited_ref"]) == SHA1_HASH_LENGTH
    assert isinstance(payload["android_formal_source_sha"], str) and len(payload["android_formal_source_sha"]) == SHA1_HASH_LENGTH
    assert isinstance(payload["android_anchor"], str) and payload["android_anchor"].endswith(
        "FormalParticipantLifecycleState.kt"
    )
    assert payload["android_formal_wire_values"] == sorted(ANDROID_FORMAL_WIRE_VALUES)
    assert payload["verification"]["passed"] is True
    assert payload["critical_trigger_semantic_mappings"]
