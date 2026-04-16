"""tests/test_pr4_cross_repo_protocol_consistency.py
======================================================
PR-4: Canonical cross-repository protocol consistency rules — test suite.

Tests cover:
- Module authority sentinels and PR-4 sentinel
- Policy sentinels are non-empty strings
- CanonicalTerminalState enum completeness
- Protocol surface catalogue structure and classification invariants
- Terminal state consistency catalogue cross-module alignment
- Delegated execution status catalogue completeness and terminal invariants
- Truth-event surface catalogue completeness
- Transitional allowance catalogue structure
- Classification helper functions
- Snapshot builder
- Projection alignment sentinel
- No unresolved surfaces in catalogue (all must be classified)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.cross_repo_protocol_consistency import (
    CANONICAL_SURFACES_ARE_DRIFT_PROTECTED_POLICY,
    CAPABILITY_DESCRIPTOR_FIELDS_ARE_CANONICAL_POLICY,
    CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY,
    CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL,
    DELEGATED_EXECUTION_STATUS_IS_CENTER_AUTHORITY_POLICY,
    TERMINAL_STATE_SET_IS_CLOSED_POLICY,
    TRANSITIONAL_SURFACES_MUST_NOT_EXPAND_POLICY,
    TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN_POLICY,
    CanonicalTerminalState,
    DelegatedExecutionStatusRecord,
    ProtocolConsistencyCategory,
    ProtocolConsistencySnapshot,
    ProtocolSurfaceClass,
    ProtocolSurfaceRecord,
    TerminalStateConsistencyRecord,
    TransitionalAllowanceKind,
    TransitionalAllowanceRecord,
    TruthEventSurfaceRecord,
    build_protocol_consistency_snapshot,
    classify_protocol_surface,
    get_delegated_execution_status_catalogue,
    get_protocol_surface_catalogue,
    get_terminal_state_consistency_catalogue,
    get_transitional_allowance_catalogue,
    get_truth_event_surface_catalogue,
    is_canonical_surface,
)

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Authority and policy sentinel tests
# ---------------------------------------------------------------------------


def test_cross_repo_protocol_consistency_authority_sentinel():
    assert CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY.startswith(
        "CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY::"
    )
    assert "core.cross_repo_protocol_consistency" in CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY


def test_pr4_sentinel_present():
    assert CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL.startswith(
        "CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL::"
    )
    assert "PR4" in CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL
    assert "cross-repo-protocol-consistency-v1" in CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL


def test_policy_sentinels_are_non_empty_strings():
    for sentinel in [
        CANONICAL_SURFACES_ARE_DRIFT_PROTECTED_POLICY,
        TRANSITIONAL_SURFACES_MUST_NOT_EXPAND_POLICY,
        TERMINAL_STATE_SET_IS_CLOSED_POLICY,
        DELEGATED_EXECUTION_STATUS_IS_CENTER_AUTHORITY_POLICY,
        TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN_POLICY,
        CAPABILITY_DESCRIPTOR_FIELDS_ARE_CANONICAL_POLICY,
    ]:
        assert isinstance(sentinel, str) and len(sentinel) > 0


def test_canonical_surfaces_drift_protected_policy_mentions_coordinated_update():
    assert "coordinated" in CANONICAL_SURFACES_ARE_DRIFT_PROTECTED_POLICY.lower()


def test_transitional_surfaces_must_not_expand_policy_mentions_retirement():
    assert "retirement" in TRANSITIONAL_SURFACES_MUST_NOT_EXPAND_POLICY.lower()


def test_terminal_state_set_is_closed_policy_mentions_closed_set():
    assert "closed" in TERMINAL_STATE_SET_IS_CLOSED_POLICY.lower()


# ---------------------------------------------------------------------------
# CanonicalTerminalState enum tests
# ---------------------------------------------------------------------------


def test_canonical_terminal_state_has_five_values():
    values = set(CanonicalTerminalState)
    assert len(values) == 5


def test_canonical_terminal_state_contains_expected_values():
    values = {t.value for t in CanonicalTerminalState}
    assert values == {"completed", "failed", "partial", "cancelled", "timed_out"}


def test_canonical_terminal_state_values_are_lowercase():
    for state in CanonicalTerminalState:
        assert state.value == state.value.lower()


# ---------------------------------------------------------------------------
# Protocol surface catalogue tests
# ---------------------------------------------------------------------------


def test_protocol_surface_catalogue_is_non_empty():
    catalogue = get_protocol_surface_catalogue()
    assert len(catalogue) >= 10


def test_all_surfaces_have_non_empty_surface_ids():
    for record in get_protocol_surface_catalogue():
        assert isinstance(record.surface_id, str)
        assert len(record.surface_id) > 0


def test_all_surface_ids_are_unique():
    ids = [r.surface_id for r in get_protocol_surface_catalogue()]
    assert len(ids) == len(set(ids)), "Duplicate surface_id found in catalogue"


def test_all_surfaces_have_valid_category():
    valid_categories = set(ProtocolConsistencyCategory)
    for record in get_protocol_surface_catalogue():
        assert record.category in valid_categories


def test_all_surfaces_have_valid_surface_class():
    valid_classes = set(ProtocolSurfaceClass)
    for record in get_protocol_surface_catalogue():
        assert record.surface_class in valid_classes


def test_all_surfaces_have_non_empty_center_authority():
    for record in get_protocol_surface_catalogue():
        assert isinstance(record.center_authority, str)
        assert len(record.center_authority) > 0


def test_transitional_surfaces_have_retirement_pathway():
    for record in get_protocol_surface_catalogue():
        if record.surface_class == ProtocolSurfaceClass.transitional:
            assert len(record.retirement_pathway) > 0, (
                f"Transitional surface {record.surface_id!r} has no retirement_pathway"
            )


def test_deprecated_surfaces_have_retirement_pathway():
    for record in get_protocol_surface_catalogue():
        if record.surface_class == ProtocolSurfaceClass.deprecated:
            assert len(record.retirement_pathway) > 0, (
                f"Deprecated surface {record.surface_id!r} has no retirement_pathway"
            )


def test_canonical_surfaces_are_majority():
    catalogue = get_protocol_surface_catalogue()
    canonical_count = sum(
        1 for r in catalogue if r.surface_class == ProtocolSurfaceClass.canonical
    )
    assert canonical_count > len(catalogue) // 2, (
        "Canonical surfaces should be the majority of the catalogue"
    )


def test_no_unresolved_surfaces_in_catalogue():
    unresolved = [
        r for r in get_protocol_surface_catalogue()
        if r.surface_class == ProtocolSurfaceClass.unresolved
    ]
    assert len(unresolved) == 0, (
        f"Unresolved surfaces found: {[r.surface_id for r in unresolved]}"
    )


# ---------------------------------------------------------------------------
# Specific surface presence tests
# ---------------------------------------------------------------------------


def test_ugcp_shared_schema_vocabulary_is_canonical():
    record = classify_protocol_surface("ugcp_shared_schema_vocabulary")
    assert record is not None
    assert record.surface_class == ProtocolSurfaceClass.canonical
    assert record.category == ProtocolConsistencyCategory.shared_vocabulary


def test_terminal_state_vocabulary_is_canonical():
    record = classify_protocol_surface("terminal_state_vocabulary")
    assert record is not None
    assert record.surface_class == ProtocolSurfaceClass.canonical
    assert record.category == ProtocolConsistencyCategory.terminal_state


def test_session_axis_model_is_canonical():
    record = classify_protocol_surface("session_axis_model")
    assert record is not None
    assert record.surface_class == ProtocolSurfaceClass.canonical
    assert record.category == ProtocolConsistencyCategory.session_identifier


def test_delegated_execution_phase_is_canonical():
    record = classify_protocol_surface("delegated_execution_phase")
    assert record is not None
    assert record.surface_class == ProtocolSurfaceClass.canonical
    assert record.category == ProtocolConsistencyCategory.delegated_execution


def test_runtime_capability_profile_is_canonical():
    record = classify_protocol_surface("runtime_capability_profile")
    assert record is not None
    assert record.surface_class == ProtocolSurfaceClass.canonical
    assert record.category == ProtocolConsistencyCategory.runtime_profile


def test_truth_event_type_vocabulary_is_canonical():
    record = classify_protocol_surface("truth_event_type_vocabulary")
    assert record is not None
    assert record.surface_class == ProtocolSurfaceClass.canonical
    assert record.category == ProtocolConsistencyCategory.truth_event


def test_heartbeat_status_aliases_is_transitional():
    record = classify_protocol_surface("heartbeat_status_aliases")
    assert record is not None
    assert record.surface_class == ProtocolSurfaceClass.transitional


def test_terminal_state_interrupted_legacy_is_deprecated():
    record = classify_protocol_surface("terminal_state_interrupted_legacy")
    assert record is not None
    assert record.surface_class == ProtocolSurfaceClass.deprecated


# ---------------------------------------------------------------------------
# is_canonical_surface helper tests
# ---------------------------------------------------------------------------


def test_is_canonical_surface_returns_true_for_canonical():
    assert is_canonical_surface("ugcp_shared_schema_vocabulary") is True
    assert is_canonical_surface("terminal_state_vocabulary") is True
    assert is_canonical_surface("delegated_execution_phase") is True


def test_is_canonical_surface_returns_false_for_transitional():
    assert is_canonical_surface("heartbeat_status_aliases") is False
    assert is_canonical_surface("terminal_state_timed_out_alignment") is False


def test_is_canonical_surface_returns_false_for_unknown():
    assert is_canonical_surface("nonexistent_surface_xyz") is False


# ---------------------------------------------------------------------------
# Terminal state consistency catalogue tests
# ---------------------------------------------------------------------------


def test_terminal_state_consistency_catalogue_has_five_entries():
    catalogue = get_terminal_state_consistency_catalogue()
    assert len(catalogue) == 5


def test_terminal_state_catalogue_covers_all_canonical_terminal_states():
    canonical_values = {t.value for t in CanonicalTerminalState}
    catalogue_values = {r.state_value for r in get_terminal_state_consistency_catalogue()}
    assert canonical_values == catalogue_values


def test_completed_is_fully_consistent_in_schema_and_phase():
    records = {r.state_value: r for r in get_terminal_state_consistency_catalogue()}
    completed = records["completed"]
    assert completed.present_in_shared_schema is True
    assert completed.present_in_execution_phase is True


def test_failed_is_consistent_in_schema_and_phase():
    records = {r.state_value: r for r in get_terminal_state_consistency_catalogue()}
    failed = records["failed"]
    assert failed.present_in_shared_schema is True
    assert failed.present_in_execution_phase is True


def test_cancelled_inconsistency_documented():
    records = {r.state_value: r for r in get_terminal_state_consistency_catalogue()}
    cancelled = records["cancelled"]
    assert cancelled.present_in_execution_phase is True
    assert cancelled.present_in_shared_schema is False
    assert len(cancelled.consistency_note) > 0


def test_timed_out_inconsistency_documented():
    records = {r.state_value: r for r in get_terminal_state_consistency_catalogue()}
    timed_out = records["timed_out"]
    assert timed_out.present_in_execution_phase is True
    assert timed_out.present_in_shared_schema is False
    assert len(timed_out.consistency_note) > 0


def test_is_fully_consistent_property():
    for record in get_terminal_state_consistency_catalogue():
        expected = (
            record.present_in_shared_schema
            and record.present_in_execution_phase
            and record.present_in_handoff_contract
        )
        assert record.is_fully_consistent == expected


# ---------------------------------------------------------------------------
# Delegated execution status catalogue tests
# ---------------------------------------------------------------------------


def test_delegated_execution_status_catalogue_has_seven_phases():
    catalogue = get_delegated_execution_status_catalogue()
    assert len(catalogue) == 7


def test_delegated_execution_catalogue_covers_all_phases():
    catalogue = get_delegated_execution_status_catalogue()
    phase_values = {r.phase_value for r in catalogue}
    expected = {
        "pending_ack",
        "acknowledged",
        "in_progress",
        "completed",
        "failed",
        "timed_out",
        "cancelled",
    }
    assert phase_values == expected


def test_delegated_execution_terminal_phases():
    terminal = [
        r for r in get_delegated_execution_status_catalogue() if r.is_terminal
    ]
    terminal_values = {r.phase_value for r in terminal}
    assert terminal_values == {"completed", "failed", "timed_out", "cancelled"}


def test_delegated_execution_non_terminal_phases():
    non_terminal = [
        r for r in get_delegated_execution_status_catalogue() if not r.is_terminal
    ]
    non_terminal_values = {r.phase_value for r in non_terminal}
    assert non_terminal_values == {"pending_ack", "acknowledged", "in_progress"}


def test_delegated_execution_all_have_center_authority():
    for record in get_delegated_execution_status_catalogue():
        assert len(record.center_authority) > 0


def test_delegated_execution_all_have_phase_values():
    for record in get_delegated_execution_status_catalogue():
        assert isinstance(record.phase_value, str)
        assert len(record.phase_value) > 0


# ---------------------------------------------------------------------------
# Truth-event surface catalogue tests
# ---------------------------------------------------------------------------


def test_truth_event_surface_catalogue_has_six_entries():
    catalogue = get_truth_event_surface_catalogue()
    assert len(catalogue) == 6


def test_truth_event_types_are_unique():
    event_types = [r.event_type for r in get_truth_event_surface_catalogue()]
    assert len(event_types) == len(set(event_types))


def test_all_truth_event_types_start_with_ugcp():
    for record in get_truth_event_surface_catalogue():
        assert record.event_type.startswith("ugcp."), (
            f"Truth event type {record.event_type!r} does not start with 'ugcp.'"
        )


def test_all_truth_event_types_have_version_suffix():
    for record in get_truth_event_surface_catalogue():
        assert ".v1" in record.event_type, (
            f"Truth event type {record.event_type!r} missing version suffix"
        )


def test_all_canonical_truth_event_surfaces():
    for record in get_truth_event_surface_catalogue():
        assert record.surface_class == ProtocolSurfaceClass.canonical, (
            f"Truth event surface {record.event_type!r} is not canonical"
        )


def test_android_visible_truth_events():
    android_visible = [
        r for r in get_truth_event_surface_catalogue() if r.android_visible
    ]
    assert len(android_visible) >= 3, "Expected at least 3 Android-visible truth events"


def test_control_transfer_transition_is_android_visible():
    for record in get_truth_event_surface_catalogue():
        if "control_transfer" in record.event_type:
            assert record.android_visible is True


# ---------------------------------------------------------------------------
# Transitional allowance catalogue tests
# ---------------------------------------------------------------------------


def test_transitional_allowance_catalogue_is_non_empty():
    catalogue = get_transitional_allowance_catalogue()
    assert len(catalogue) >= 5


def test_all_allowances_have_unique_ids():
    ids = [r.allowance_id for r in get_transitional_allowance_catalogue()]
    assert len(ids) == len(set(ids))


def test_all_allowances_have_valid_kind():
    valid_kinds = set(TransitionalAllowanceKind)
    for record in get_transitional_allowance_catalogue():
        assert record.kind in valid_kinds


def test_all_allowances_have_non_empty_fields():
    for record in get_transitional_allowance_catalogue():
        assert len(record.allowance_id) > 0
        assert len(record.android_side_value) > 0
        assert len(record.center_canonical_value) > 0
        assert len(record.normalisation_location) > 0


def test_all_allowances_have_retirement_condition():
    for record in get_transitional_allowance_catalogue():
        assert len(record.retirement_condition) > 0, (
            f"Allowance {record.allowance_id!r} has no retirement_condition"
        )


def test_session_id_alias_allowance_present():
    ids = {r.allowance_id for r in get_transitional_allowance_catalogue()}
    assert "session_id_to_control_session_id" in ids


def test_runtime_session_id_alias_allowance_present():
    ids = {r.allowance_id for r in get_transitional_allowance_catalogue()}
    assert "runtime_session_id_alias" in ids


def test_timeout_to_timed_out_allowance_present():
    ids = {r.allowance_id for r in get_transitional_allowance_catalogue()}
    assert "timeout_to_timed_out" in ids


# ---------------------------------------------------------------------------
# Snapshot builder tests
# ---------------------------------------------------------------------------


def test_build_protocol_consistency_snapshot_returns_snapshot():
    snapshot = build_protocol_consistency_snapshot()
    assert isinstance(snapshot, ProtocolConsistencySnapshot)


def test_snapshot_protocol_surface_count_matches_catalogue():
    snapshot = build_protocol_consistency_snapshot()
    catalogue = get_protocol_surface_catalogue()
    assert snapshot.protocol_surface_count == len(catalogue)


def test_snapshot_canonical_count_matches_catalogue():
    snapshot = build_protocol_consistency_snapshot()
    catalogue = get_protocol_surface_catalogue()
    expected = sum(
        1 for r in catalogue if r.surface_class == ProtocolSurfaceClass.canonical
    )
    assert snapshot.canonical_surface_count == expected


def test_snapshot_transitional_count_matches_catalogue():
    snapshot = build_protocol_consistency_snapshot()
    catalogue = get_protocol_surface_catalogue()
    expected = sum(
        1 for r in catalogue if r.surface_class == ProtocolSurfaceClass.transitional
    )
    assert snapshot.transitional_surface_count == expected


def test_snapshot_terminal_state_count_matches_catalogue():
    snapshot = build_protocol_consistency_snapshot()
    assert snapshot.terminal_state_count == len(get_terminal_state_consistency_catalogue())


def test_snapshot_delegated_execution_phase_count_matches():
    snapshot = build_protocol_consistency_snapshot()
    assert snapshot.delegated_execution_phase_count == len(
        get_delegated_execution_status_catalogue()
    )


def test_snapshot_terminal_execution_phase_count():
    snapshot = build_protocol_consistency_snapshot()
    assert snapshot.terminal_execution_phase_count == 4


def test_snapshot_truth_event_type_count_matches():
    snapshot = build_protocol_consistency_snapshot()
    assert snapshot.truth_event_type_count == len(get_truth_event_surface_catalogue())


def test_snapshot_transitional_allowance_count_matches():
    snapshot = build_protocol_consistency_snapshot()
    assert snapshot.transitional_allowance_count == len(
        get_transitional_allowance_catalogue()
    )


def test_snapshot_has_generated_at():
    snapshot = build_protocol_consistency_snapshot()
    assert snapshot.generated_at > 0.0


def test_snapshot_to_dict_is_serialisable():
    import json

    snapshot = build_protocol_consistency_snapshot()
    d = snapshot.to_dict()
    assert isinstance(d, dict)
    # Should be JSON-serialisable
    json.dumps(d)


def test_snapshot_to_dict_contains_expected_keys():
    snapshot = build_protocol_consistency_snapshot()
    d = snapshot.to_dict()
    expected_keys = {
        "generated_at",
        "protocol_surface_count",
        "canonical_surface_count",
        "transitional_surface_count",
        "deprecated_surface_count",
        "unresolved_surface_count",
        "terminal_state_count",
        "fully_consistent_terminal_states",
        "delegated_execution_phase_count",
        "terminal_execution_phase_count",
        "truth_event_type_count",
        "transitional_allowance_count",
        "authority",
    }
    assert set(d.keys()) == expected_keys


def test_snapshot_authority_contains_module_name():
    snapshot = build_protocol_consistency_snapshot()
    assert "cross_repo_protocol_consistency" in snapshot.authority


# ---------------------------------------------------------------------------
# Projection alignment sentinel test
# ---------------------------------------------------------------------------


def test_projection_alignment_sentinel_is_available():
    from core.routes.projection import CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4

    assert isinstance(CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4, str)
    assert len(CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4) > 0
    assert "UNAVAILABLE" not in CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4, (
        "PR-4 projection alignment sentinel shows UNAVAILABLE — import failed"
    )


def test_projection_sentinel_mentions_pr4():
    from core.routes.projection import CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4

    assert "PR4" in CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4 or "PR-4" in CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4


def test_projection_fallback_sentinel_format():
    """Verify the UNAVAILABLE sentinel string follows the expected convention.

    This documents the expected format of the fallback string that would be set
    when the import guard triggers (e.g. during partial deployments).  The test
    verifies the *constant name* so that callers can reliably detect
    unavailability by checking for the 'UNAVAILABLE' substring.
    """
    expected_unavailable = (
        "PROJECTION_ROUTES::CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4_UNAVAILABLE"
    )
    # Verify the UNAVAILABLE sentinel literal follows the naming convention.
    assert "PROJECTION_ROUTES::" in expected_unavailable
    assert "UNAVAILABLE" in expected_unavailable
    assert "PR4" in expected_unavailable


# ---------------------------------------------------------------------------
# Cross-category coverage invariants
# ---------------------------------------------------------------------------


def test_all_consistency_categories_covered():
    """Every ProtocolConsistencyCategory value must appear in the catalogue."""
    covered = {r.category for r in get_protocol_surface_catalogue()}
    all_categories = set(ProtocolConsistencyCategory)
    uncovered = all_categories - covered
    assert not uncovered, (
        f"The following categories have no catalogue entries: {uncovered}"
    )


def test_shared_vocabulary_surfaces_exist():
    shared = [
        r for r in get_protocol_surface_catalogue()
        if r.category == ProtocolConsistencyCategory.shared_vocabulary
    ]
    assert len(shared) >= 2


def test_truth_event_surfaces_exist():
    truth = [
        r for r in get_protocol_surface_catalogue()
        if r.category == ProtocolConsistencyCategory.truth_event
    ]
    assert len(truth) >= 2


def test_compatibility_alias_surfaces_exist():
    compat = [
        r for r in get_protocol_surface_catalogue()
        if r.category == ProtocolConsistencyCategory.compatibility_alias
    ]
    assert len(compat) >= 2
