"""tests/test_pr3_canonical_session_axis.py
=============================================
PR-3: Canonical session axis — test suite.

Tests cover:
- Module authority sentinels and PR-3 sentinel
- Session family catalogue completeness
- Session identifier catalogue correctness (roles, aliases, priorities)
- Android session mapping catalogue completeness
- Classification helper functions
- Snapshot builder
- Projection alignment sentinel
- Invariants documented in UGCP_SESSION_AXIS_V1.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.canonical_session_axis import (
    ANDROID_SESSION_IDS_ARE_CLAIMS_POLICY,
    ALIAS_RESOLUTION_ORDER_IS_CANONICAL_POLICY,
    BARE_SESSION_IS_NOT_CANONICAL_POLICY,
    CANONICAL_SESSION_AXIS_AUTHORITY,
    CANONICAL_SESSION_AXIS_PR3_SENTINEL,
    CENTER_IS_SESSION_RESOLUTION_AUTHORITY_POLICY,
    MESH_SESSION_IS_OPTIONAL_OVERLAY_POLICY,
    RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY,
    SESSION_FAMILIES_ARE_DISJOINT_POLICY,
    TRANSFER_SESSION_TERMINAL_IS_NON_RECOVERABLE_POLICY,
    SessionContinuityClass,
    SessionFamily,
    SessionFamilyRecord,
    SessionIdentifierRecord,
    SessionIdentifierRole,
    AndroidSessionMapping,
    SessionAxisSnapshot,
    build_session_axis_snapshot,
    classify_identifier_role,
    get_android_session_mapping_catalogue,
    get_session_family_catalogue,
    get_session_identifier_catalogue,
    resolve_session_family_for_identifier,
)

# ---------------------------------------------------------------------------
# Sentinel tests
# ---------------------------------------------------------------------------


def test_canonical_session_axis_authority_sentinel():
    assert CANONICAL_SESSION_AXIS_AUTHORITY.startswith(
        "CANONICAL_SESSION_AXIS_AUTHORITY::"
    )
    assert "core.canonical_session_axis" in CANONICAL_SESSION_AXIS_AUTHORITY


def test_pr3_sentinel_present():
    assert CANONICAL_SESSION_AXIS_PR3_SENTINEL.startswith(
        "CANONICAL_SESSION_AXIS_PR3_SENTINEL::"
    )
    assert "PR3" in CANONICAL_SESSION_AXIS_PR3_SENTINEL
    assert "canonical-session-axis-v1" in CANONICAL_SESSION_AXIS_PR3_SENTINEL


def test_policy_sentinels_are_non_empty():
    for sentinel in [
        SESSION_FAMILIES_ARE_DISJOINT_POLICY,
        BARE_SESSION_IS_NOT_CANONICAL_POLICY,
        CENTER_IS_SESSION_RESOLUTION_AUTHORITY_POLICY,
        RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY,
        TRANSFER_SESSION_TERMINAL_IS_NON_RECOVERABLE_POLICY,
        MESH_SESSION_IS_OPTIONAL_OVERLAY_POLICY,
        ANDROID_SESSION_IDS_ARE_CLAIMS_POLICY,
        ALIAS_RESOLUTION_ORDER_IS_CANONICAL_POLICY,
    ]:
        assert isinstance(sentinel, str) and len(sentinel) > 0


# ---------------------------------------------------------------------------
# Session family catalogue tests
# ---------------------------------------------------------------------------


def test_session_family_catalogue_has_five_families():
    catalogue = get_session_family_catalogue()
    assert len(catalogue) == 5


def test_session_family_catalogue_contains_all_families():
    families = {r.family for r in get_session_family_catalogue()}
    assert families == {
        SessionFamily.conversation,
        SessionFamily.control,
        SessionFamily.runtime_attachment,
        SessionFamily.delegation_transfer,
        SessionFamily.mesh,
    }


def test_each_family_has_canonical_identifier():
    for record in get_session_family_catalogue():
        assert isinstance(record.canonical_identifier, str)
        assert len(record.canonical_identifier) > 0


def test_conversation_family_record():
    catalogue = {r.family: r for r in get_session_family_catalogue()}
    rec = catalogue[SessionFamily.conversation]
    assert rec.canonical_identifier == "conversation_session_id"
    assert rec.continuity_class == SessionContinuityClass.persistent
    assert rec.recovery_allowed is True
    assert "session_manager" in rec.authority_module


def test_control_family_record():
    catalogue = {r.family: r for r in get_session_family_catalogue()}
    rec = catalogue[SessionFamily.control]
    assert rec.canonical_identifier == "control_session_id"
    assert rec.continuity_class == SessionContinuityClass.request_scoped
    assert rec.recovery_allowed is False


def test_runtime_attachment_family_record():
    catalogue = {r.family: r for r in get_session_family_catalogue()}
    rec = catalogue[SessionFamily.runtime_attachment]
    assert rec.canonical_identifier == "runtime_attachment_session_id"
    assert rec.continuity_class == SessionContinuityClass.persistent
    assert rec.recovery_allowed is True
    assert rec.terminal_requires_new_handshake is True
    assert "attached_runtime_session_registry" in rec.authority_module


def test_delegation_transfer_family_record():
    catalogue = {r.family: r for r in get_session_family_catalogue()}
    rec = catalogue[SessionFamily.delegation_transfer]
    assert rec.canonical_identifier == "delegation_transfer_session_id"
    assert rec.continuity_class == SessionContinuityClass.transfer_scoped
    assert rec.recovery_allowed is False
    assert rec.terminal_requires_new_handshake is True


def test_mesh_family_record():
    catalogue = {r.family: r for r in get_session_family_catalogue()}
    rec = catalogue[SessionFamily.mesh]
    assert rec.canonical_identifier == "mesh_session_id"
    assert rec.continuity_class == SessionContinuityClass.overlay
    assert "mesh_session" in rec.authority_module


def test_family_record_to_dict():
    for record in get_session_family_catalogue():
        d = record.to_dict()
        assert "family" in d
        assert "canonical_identifier" in d
        assert "continuity_class" in d
        assert "authority_module" in d
        assert "recovery_allowed" in d
        assert "terminal_requires_new_handshake" in d
        assert "description" in d


# ---------------------------------------------------------------------------
# Session identifier catalogue tests
# ---------------------------------------------------------------------------


def test_session_identifier_catalogue_is_non_empty():
    catalogue = get_session_identifier_catalogue()
    assert len(catalogue) >= 10


def test_each_family_has_exactly_one_canonical_identifier():
    by_family: dict = {}
    for record in get_session_identifier_catalogue():
        if record.role == SessionIdentifierRole.canonical:
            by_family.setdefault(record.family, []).append(record)

    # All five session families must have exactly one canonical identifier record.
    for family in SessionFamily:
        assert family in by_family, f"No canonical identifier for {family}"
        assert len(by_family[family]) == 1, (
            f"Multiple canonical identifiers for {family}: "
            f"{[r.field_name for r in by_family[family]]}"
        )


def test_canonical_identifiers_have_priority_one():
    for record in get_session_identifier_catalogue():
        if record.role == SessionIdentifierRole.canonical:
            assert record.resolution_priority == 1, (
                f"Canonical identifier {record.field_name!r} should have "
                f"resolution_priority=1, got {record.resolution_priority}"
            )


def test_all_aliases_resolve_to_known_canonical_names():
    canonical_names = {
        r.field_name
        for r in get_session_identifier_catalogue()
        if r.role == SessionIdentifierRole.canonical
    }
    # Also include the explicit canonical names from family records
    family_canonical = {r.canonical_identifier for r in get_session_family_catalogue()}
    all_canonical = canonical_names | family_canonical

    for record in get_session_identifier_catalogue():
        assert record.canonical_name in all_canonical, (
            f"Identifier {record.field_name!r} resolves to "
            f"{record.canonical_name!r} which is not in canonical names set"
        )


def test_runtime_attachment_session_id_is_canonical():
    rec = classify_identifier_role("runtime_attachment_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.canonical
    assert rec.family == SessionFamily.runtime_attachment


def test_runtime_session_id_is_alias():
    rec = classify_identifier_role("runtime_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.alias
    assert rec.canonical_name == "runtime_attachment_session_id"


def test_attached_session_id_is_alias():
    rec = classify_identifier_role("attached_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.alias
    assert rec.canonical_name == "runtime_attachment_session_id"
    assert "runtime_attachment" in rec.family.value


def test_delegation_transfer_session_id_is_canonical():
    rec = classify_identifier_role("delegation_transfer_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.canonical
    assert rec.family == SessionFamily.delegation_transfer


def test_transfer_session_id_is_alias():
    rec = classify_identifier_role("transfer_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.alias
    assert rec.canonical_name == "delegation_transfer_session_id"


def test_handoff_session_id_is_alias():
    rec = classify_identifier_role("handoff_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.alias
    assert rec.canonical_name == "delegation_transfer_session_id"


def test_mesh_session_id_is_canonical():
    rec = classify_identifier_role("mesh_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.canonical
    assert rec.family == SessionFamily.mesh


def test_conversation_session_id_is_canonical():
    rec = classify_identifier_role("conversation_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.canonical
    assert rec.family == SessionFamily.conversation


def test_control_session_id_is_canonical_for_control_family():
    rec = classify_identifier_role("control_session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.canonical
    assert rec.family == SessionFamily.control
    assert rec.canonical_name == "control_session_id"


def test_session_id_is_legacy_bare():
    rec = classify_identifier_role("session_id")
    assert rec is not None
    assert rec.role == SessionIdentifierRole.legacy_bare


def test_classify_unknown_identifier_returns_none():
    assert classify_identifier_role("totally_unknown_field") is None
    assert classify_identifier_role("") is None


def test_identifier_record_to_dict():
    for record in get_session_identifier_catalogue():
        d = record.to_dict()
        assert "field_name" in d
        assert "family" in d
        assert "role" in d
        assert "canonical_name" in d
        assert "resolution_priority" in d


# ---------------------------------------------------------------------------
# Android session mapping catalogue tests
# ---------------------------------------------------------------------------


def test_android_mapping_catalogue_is_non_empty():
    catalogue = get_android_session_mapping_catalogue()
    assert len(catalogue) >= 5


def test_android_mapping_covers_runtime_attachment():
    families = {m.family for m in get_android_session_mapping_catalogue()}
    assert SessionFamily.runtime_attachment in families


def test_android_mapping_covers_delegation_transfer():
    families = {m.family for m in get_android_session_mapping_catalogue()}
    assert SessionFamily.delegation_transfer in families


def test_android_mapping_covers_mesh():
    families = {m.family for m in get_android_session_mapping_catalogue()}
    assert SessionFamily.mesh in families


def test_android_mesh_session_id_is_canonical_match():
    for mapping in get_android_session_mapping_catalogue():
        if mapping.android_field == "mesh_session_id":
            assert mapping.classification == "CANONICAL_MATCH"
            assert mapping.center_canonical_field == "mesh_session_id"
            break
    else:
        pytest.fail("mesh_session_id not found in Android mapping catalogue")


def test_android_runtime_session_id_is_transitional_alias():
    for mapping in get_android_session_mapping_catalogue():
        if mapping.android_field == "runtime_session_id":
            assert mapping.classification == "TRANSITIONAL_ALIAS"
            assert mapping.center_canonical_field == "runtime_attachment_session_id"
            break
    else:
        pytest.fail("runtime_session_id not found in Android mapping catalogue")


def test_android_transfer_session_id_is_transitional_alias():
    for mapping in get_android_session_mapping_catalogue():
        if mapping.android_field == "transfer_session_id":
            assert mapping.classification == "TRANSITIONAL_ALIAS"
            assert mapping.center_canonical_field == "delegation_transfer_session_id"
            break
    else:
        pytest.fail("transfer_session_id not found in Android mapping catalogue")


def test_android_attached_session_id_is_transitional_alias():
    for mapping in get_android_session_mapping_catalogue():
        if mapping.android_field == "attached_session_id":
            assert mapping.classification == "TRANSITIONAL_ALIAS"
            assert mapping.center_canonical_field == "runtime_attachment_session_id"
            break
    else:
        pytest.fail("attached_session_id not found in Android mapping catalogue")


def test_android_mapping_to_dict():
    for mapping in get_android_session_mapping_catalogue():
        d = mapping.to_dict()
        assert "android_field" in d
        assert "center_canonical_field" in d
        assert "family" in d
        assert "classification" in d


# ---------------------------------------------------------------------------
# Classification helper tests
# ---------------------------------------------------------------------------


def test_resolve_session_family_for_runtime_session_id():
    family_rec = resolve_session_family_for_identifier("runtime_session_id")
    assert family_rec is not None
    assert family_rec.family == SessionFamily.runtime_attachment
    assert family_rec.canonical_identifier == "runtime_attachment_session_id"


def test_resolve_session_family_for_mesh_session_id():
    family_rec = resolve_session_family_for_identifier("mesh_session_id")
    assert family_rec is not None
    assert family_rec.family == SessionFamily.mesh


def test_resolve_session_family_for_unknown_returns_none():
    assert resolve_session_family_for_identifier("unknown_field") is None


def test_session_family_from_string():
    assert SessionFamily.from_string("conversation") == SessionFamily.conversation
    assert SessionFamily.from_string("runtime_attachment") == SessionFamily.runtime_attachment
    assert SessionFamily.from_string("mesh") == SessionFamily.mesh
    assert SessionFamily.from_string("UNKNOWN") is None
    assert SessionFamily.from_string("unknown", SessionFamily.conversation) == SessionFamily.conversation


# ---------------------------------------------------------------------------
# Snapshot builder tests
# ---------------------------------------------------------------------------


def test_build_session_axis_snapshot_structure():
    snap = build_session_axis_snapshot()
    assert isinstance(snap, SessionAxisSnapshot)
    assert snap.snapshot_id.startswith("sax_")
    assert snap.created_at > 0
    assert snap.family_count == 5
    assert snap.identifier_count >= 10
    assert snap.android_mapping_count >= 5


def test_build_session_axis_snapshot_catalogues_match_count():
    snap = build_session_axis_snapshot()
    assert len(snap.family_records) == snap.family_count
    assert len(snap.identifier_records) == snap.identifier_count
    assert len(snap.android_mappings) == snap.android_mapping_count


def test_build_session_axis_snapshot_to_dict():
    snap = build_session_axis_snapshot()
    d = snap.to_dict()
    assert "snapshot_id" in d
    assert "created_at" in d
    assert "family_count" in d
    assert "identifier_count" in d
    assert "android_mapping_count" in d
    assert "family_records" in d
    assert "identifier_records" in d
    assert "android_mappings" in d


# ---------------------------------------------------------------------------
# Invariant tests (from UGCP_SESSION_AXIS_V1.md §7)
# ---------------------------------------------------------------------------


def test_invariant_five_families():
    """Invariant 1: exactly five session families."""
    assert len(get_session_family_catalogue()) == 5


def test_invariant_canonical_identifier_uniqueness():
    """Invariant 2: each family has exactly one canonical identifier."""
    by_family: dict = {}
    for record in get_session_identifier_catalogue():
        if record.role == SessionIdentifierRole.canonical:
            fam = record.family
            assert fam not in by_family, (
                f"Duplicate canonical identifier for {fam}: "
                f"{by_family[fam]} and {record.field_name}"
            )
            by_family[fam] = record.field_name

    # All five families must have exactly one canonical identifier record.
    for family in SessionFamily:
        assert family in by_family, f"No canonical identifier for {family}"


def test_invariant_all_aliases_resolve():
    """Invariant 3: every alias/legacy_bare resolves to a known canonical name."""
    canonical_names = {
        r.canonical_identifier for r in get_session_family_catalogue()
    }
    for record in get_session_identifier_catalogue():
        assert record.canonical_name in canonical_names, (
            f"Identifier {record.field_name!r} resolves to "
            f"{record.canonical_name!r} which is not a known canonical name"
        )


def test_invariant_android_mappings_non_empty_per_family():
    """Invariant 4: Android mapping catalogue covers key families."""
    families = {m.family for m in get_android_session_mapping_catalogue()}
    for required_family in [
        SessionFamily.runtime_attachment,
        SessionFamily.delegation_transfer,
        SessionFamily.mesh,
    ]:
        assert required_family in families, (
            f"Android mapping catalogue missing entries for {required_family}"
        )


def test_invariant_canonical_fields_have_priority_one():
    """Invariant 5: canonical identifiers have resolution_priority=1."""
    for record in get_session_identifier_catalogue():
        if record.role == SessionIdentifierRole.canonical:
            assert record.resolution_priority == 1, (
                f"Canonical identifier {record.field_name!r} has priority "
                f"{record.resolution_priority}, expected 1"
            )


# ---------------------------------------------------------------------------
# Projection alignment sentinel test
# ---------------------------------------------------------------------------


def test_projection_alignment_sentinel_present():
    try:
        from core.routes.projection import CANONICAL_SESSION_AXIS_ALIGNED_PR3
    except ImportError:
        pytest.skip("projection route not importable in this environment")

    assert isinstance(CANONICAL_SESSION_AXIS_ALIGNED_PR3, str)
    assert "CANONICAL_SESSION_AXIS_ALIGNED_PR3" in CANONICAL_SESSION_AXIS_ALIGNED_PR3
    assert "UNAVAILABLE" not in CANONICAL_SESSION_AXIS_ALIGNED_PR3


# ---------------------------------------------------------------------------
# Documentation presence tests
# ---------------------------------------------------------------------------


def test_canonical_session_axis_architecture_doc_exists():
    repo_root = Path(__file__).resolve().parents[1]
    doc = repo_root / "docs" / "architecture" / "CANONICAL_SESSION_AXIS_V1.md"
    assert doc.exists(), f"Architecture doc not found: {doc}"
    text = doc.read_text(encoding="utf-8").lower()
    for required_term in [
        "conversation",
        "control",
        "runtime_attachment",
        "delegation_transfer",
        "mesh",
        "canonical",
        "alias",
        "android",
        "reconnect",
    ]:
        assert required_term in text, (
            f"Required term {required_term!r} not found in CANONICAL_SESSION_AXIS_V1.md"
        )


def test_ugcp_session_axis_doc_exists():
    repo_root = Path(__file__).resolve().parents[1]
    doc = repo_root / "docs" / "ugcp" / "UGCP_SESSION_AXIS_V1.md"
    assert doc.exists(), f"UGCP session axis doc not found: {doc}"
    text = doc.read_text(encoding="utf-8").lower()
    for required_term in [
        "conversation_session_id",
        "runtime_attachment_session_id",
        "delegation_transfer_session_id",
        "mesh_session_id",
        "transitional_alias",
        "canonical_match",
        "android",
        "reconnect",
    ]:
        assert required_term in text, (
            f"Required term {required_term!r} not found in UGCP_SESSION_AXIS_V1.md"
        )
