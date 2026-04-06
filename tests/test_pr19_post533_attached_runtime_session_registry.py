"""tests/test_pr19_post533_attached_runtime_session_registry.py
================================================================
Tests for PR package 19 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Authoritative Attached Runtime Session Registry.

This test suite verifies that:

1. The registry module exists with the correct public API (enums, dataclasses,
   functions, sentinels).
2. ``register_session()`` creates an active entry with all required fields
   (session_id, device_id, runtime_session_id, attachment_state,
   invalidation_reason, posture, host_role).
3. ``register_session()`` for a device that already has an active session
   automatically moves the old entry to ``replaced`` state.
4. ``reconnect_session()`` restores ``active`` state without changing
   ``runtime_session_id``.
5. ``reattach_session()`` restores ``active`` state and preserves
   ``runtime_session_id``.
6. ``detach_session()`` moves an entry to ``detached`` state (recoverable).
7. ``invalidate_session()`` moves an entry to ``invalidated`` state (terminal).
8. ``lookup_active_session()`` and ``lookup_session_by_device()`` return None
   for non-active entries by default.
9. Multi-session and replace-old-session scenarios behave correctly.
10. Ring-buffer capacity (128) is enforced with FIFO eviction.
11. ``build_registry_snapshot()`` returns accurate counts.
12. ``core.runtime`` re-exports all PR-19 symbols.
13. The projection sentinel is present and not UNAVAILABLE.
14. All 12 policy sentinels are non-empty strings.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — RegistryEntryState enum: all values, from_string(), is_active(),
     is_terminal(), is_recoverable().
C  — RegistryTransition enum: all values, from_string().
D  — InvalidationReason enum: all values, from_string().
E  — AttachedSessionRegistryEntry: construction and default fields.
F  — AttachedSessionRegistryEntry: is_active(), is_terminal(), is_recoverable().
G  — AttachedSessionRegistryEntry: to_dict() contains all required keys.
H  — AttachedSessionRegistryEntry: to_json() and from_dict() round-trip.
I  — AttachedSessionRegistrySnapshot: construction and to_dict().
J  — AttachedSessionRegistry: initial state (empty buffer, zero indices).
K  — AttachedSessionRegistry: push_new() appends entry and updates indices.
L  — AttachedSessionRegistry: get_active_for_device() returns active entry.
M  — AttachedSessionRegistry: get_active_for_device() returns None for non-active.
N  — AttachedSessionRegistry: get_by_session_id() with active_only=True.
O  — AttachedSessionRegistry: get_by_session_id() with active_only=False.
P  — AttachedSessionRegistry: supersede_active_for_device() replaces old entry.
Q  — AttachedSessionRegistry: apply_transition() valid transitions.
R  — AttachedSessionRegistry: apply_transition() illegal transitions return unchanged.
S  — AttachedSessionRegistry: list_all_active() returns only active entries.
T  — AttachedSessionRegistry: list_all() returns all entries newest first.
U  — AttachedSessionRegistry: size() and capacity().
V  — AttachedSessionRegistry: clear() resets buffer and indices.
W  — AttachedSessionRegistry: snapshot() returns correct counts.
X  — AttachedSessionRegistry: FIFO eviction at capacity (128 entries).
Y  — register_session(): creates active entry with all required fields.
Z  — register_session(): runtime_session_id is a non-empty UUID-like string.
AA — register_session(): replaces old active entry for same device.
AB — register_session(): new runtime_session_id differs from old one.
AC — register_session(): lookup by old session_id returns None (active_only).
AD — reconnect_session(): restores active state.
AE — reconnect_session(): preserves runtime_session_id.
AF — reconnect_session(): sets last_transition to reconnect.
AG — reconnect_session(): sets invalidation_reason to none.
AH — reconnect_session(): no-op on already-active entry.
AI — reattach_session(): restores active state from detached.
AJ — reattach_session(): preserves runtime_session_id.
AK — reattach_session(): can update posture, host_role, coordination_role.
AL — detach_session(): moves active entry to detached state.
AM — detach_session(): sets invalidation_reason to detached.
AN — detach_session(): sets last_transition to detach.
AO — detach_session(): detached entry not returned by lookup_session_by_device.
AP — invalidate_session(): moves active entry to invalidated state (terminal).
AQ — invalidate_session(): sets invalidation_reason appropriately.
AR — invalidate_session(): terminal — further transitions are no-ops.
AS — lookup_active_session(): returns active entry by session_id.
AT — lookup_active_session(): returns None for replaced entry (active_only=True).
AU — lookup_active_session(): returns non-active entry when active_only=False.
AV — lookup_session_by_device(): returns active entry by device_id.
AW — lookup_session_by_device(): returns None after detach.
AX — list_active_sessions(): returns all active entries.
AY — list_active_sessions(): excludes replaced/detached/invalidated entries.
AZ — build_registry_snapshot(): correct active_count after operations.
BA — build_registry_snapshot(): correct replaced_count after replace.
BB — build_registry_snapshot(): correct detached_count after detach.
BC — build_registry_snapshot(): correct invalidated_count after invalidate.
BD — build_registry_snapshot(): policy_sentinels list is non-empty.
BE — Multi-session: two devices each have independent active sessions.
BF — Multi-session overlap: register new session supersedes old session.
BG — Multi-session: reconnect after multi-session does not affect other device.
BH — Reconnect scenario: detach then reconnect returns original runtime_session_id.
BI — Reattach scenario: detach then reattach returns original runtime_session_id.
BJ — Replace-old-session: old entry is retrievable with active_only=False.
BK — Replace-old-session: new entry is active, old is replaced.
BL — Singleton reset: reset_session_registry() creates fresh singleton.
BM — Explicit registry parameter: all functions accept explicit registry.
BN — Invalidation after replace: old replaced entry cannot be reactivated.
BO — core.runtime re-exports: all PR-19 symbols accessible from core.runtime.
BP — projection.py sentinel: ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19
     present and not UNAVAILABLE.
BQ — ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL contains 'package=19'.
BR — AttachedSessionRegistryEntry: metadata merging in transitions.
BS — AttachedSessionRegistry: session_id index updated on push_new.
BT — detach_session(): custom invalidation reason is preserved.
BU — invalidate_session(): bad_posture reason.
BV — reconnect_session(): after invalidate is a no-op (terminal state).
BW — register_session() for device with detached (not active) entry: no old supersede.
BX — build_registry_snapshot(): total_count matches buffer size.
BY — Snapshot: to_dict() is JSON-serialisable.
BZ — Snapshot: to_json() produces valid JSON.
"""

from __future__ import annotations

import json
import uuid

import pytest

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from core.attached_runtime_session_registry import (
    ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY,
    ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL,
    AttachedSessionRegistry,
    AttachedSessionRegistryEntry,
    AttachedSessionRegistrySnapshot,
    InvalidationReason,
    REGISTRY_DEVICE_HAS_AT_MOST_ONE_ACTIVE_SESSION_POLICY,
    REGISTRY_DETACH_REQUIRES_EXPLICIT_SIGNAL_POLICY,
    REGISTRY_DISPATCH_MUST_CONSULT_REGISTRY_POLICY,
    REGISTRY_INVALIDATED_ENTRY_IS_TERMINAL_POLICY,
    REGISTRY_IS_SINGLE_TRUTH_SOURCE_POLICY,
    REGISTRY_LOOKUP_RETURNS_ACTIVE_ONLY_BY_DEFAULT_POLICY,
    REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY,
    REGISTRY_RECONCILIATION_MUST_CONSULT_REGISTRY_POLICY,
    REGISTRY_REGISTER_REPLACES_OLD_SESSION_POLICY,
    REGISTRY_REUSE_MUST_CONSULT_REGISTRY_POLICY,
    RegistryEntryState,
    RegistryTransition,
    build_registry_snapshot,
    detach_session,
    get_session_registry,
    invalidate_session,
    list_active_sessions,
    lookup_active_session,
    lookup_session_by_device,
    reattach_session,
    reconnect_session,
    register_session,
    reset_session_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry() -> AttachedSessionRegistry:
    """Return a fresh, isolated AttachedSessionRegistry for each test."""
    return AttachedSessionRegistry()


def _make_entry(**kwargs) -> AttachedSessionRegistryEntry:
    """Return a minimal active entry using sensible defaults."""
    defaults = dict(
        device_id="dev-test",
        session_id="sess-test",
        runtime_session_id=str(uuid.uuid4()),
        attachment_state=RegistryEntryState.active,
        invalidation_reason=InvalidationReason.none,
        posture="join_runtime",
        host_role="",
        coordination_role="",
        capability_tier="",
    )
    defaults.update(kwargs)
    return AttachedSessionRegistryEntry(**defaults)


# ===========================================================================
# A — Authority / policy sentinel presence and correctness
# ===========================================================================


class TestAuthoritySentinels:
    def test_A1_authority_sentinel_non_empty(self):
        assert ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY
        assert isinstance(ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY, str)

    def test_A2_authority_sentinel_contains_module_name(self):
        assert "attached_runtime_session_registry" in ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY

    def test_A3_pr19_sentinel_non_empty(self):
        assert ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL
        assert isinstance(ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL, str)

    def test_A4_pr19_sentinel_contains_package_19(self):
        assert "package=19" in ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL

    def test_A5_registry_is_single_truth_source_policy_non_empty(self):
        assert REGISTRY_IS_SINGLE_TRUTH_SOURCE_POLICY
        assert "REGISTRY_IS_SINGLE_TRUTH_SOURCE" in REGISTRY_IS_SINGLE_TRUTH_SOURCE_POLICY

    def test_A6_device_has_at_most_one_active_session_policy_non_empty(self):
        assert REGISTRY_DEVICE_HAS_AT_MOST_ONE_ACTIVE_SESSION_POLICY

    def test_A7_register_replaces_old_session_policy_non_empty(self):
        assert REGISTRY_REGISTER_REPLACES_OLD_SESSION_POLICY

    def test_A8_reconnect_preserves_runtime_session_id_policy_non_empty(self):
        assert REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY

    def test_A9_detach_requires_explicit_signal_policy_non_empty(self):
        assert REGISTRY_DETACH_REQUIRES_EXPLICIT_SIGNAL_POLICY

    def test_A10_invalidated_entry_is_terminal_policy_non_empty(self):
        assert REGISTRY_INVALIDATED_ENTRY_IS_TERMINAL_POLICY

    def test_A11_dispatch_must_consult_registry_policy_non_empty(self):
        assert REGISTRY_DISPATCH_MUST_CONSULT_REGISTRY_POLICY

    def test_A12_reuse_must_consult_registry_policy_non_empty(self):
        assert REGISTRY_REUSE_MUST_CONSULT_REGISTRY_POLICY

    def test_A13_reconciliation_must_consult_registry_policy_non_empty(self):
        assert REGISTRY_RECONCILIATION_MUST_CONSULT_REGISTRY_POLICY

    def test_A14_lookup_returns_active_only_by_default_policy_non_empty(self):
        assert REGISTRY_LOOKUP_RETURNS_ACTIVE_ONLY_BY_DEFAULT_POLICY

    def test_A15_all_policy_sentinels_are_strings(self):
        sentinels = [
            ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY,
            REGISTRY_IS_SINGLE_TRUTH_SOURCE_POLICY,
            REGISTRY_DEVICE_HAS_AT_MOST_ONE_ACTIVE_SESSION_POLICY,
            REGISTRY_REGISTER_REPLACES_OLD_SESSION_POLICY,
            REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY,
            REGISTRY_DETACH_REQUIRES_EXPLICIT_SIGNAL_POLICY,
            REGISTRY_INVALIDATED_ENTRY_IS_TERMINAL_POLICY,
            REGISTRY_DISPATCH_MUST_CONSULT_REGISTRY_POLICY,
            REGISTRY_REUSE_MUST_CONSULT_REGISTRY_POLICY,
            REGISTRY_RECONCILIATION_MUST_CONSULT_REGISTRY_POLICY,
            REGISTRY_LOOKUP_RETURNS_ACTIVE_ONLY_BY_DEFAULT_POLICY,
            ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL,
        ]
        for s in sentinels:
            assert isinstance(s, str) and s


# ===========================================================================
# B — RegistryEntryState enum
# ===========================================================================


class TestRegistryEntryState:
    def test_B1_all_values_exist(self):
        assert RegistryEntryState.active
        assert RegistryEntryState.replaced
        assert RegistryEntryState.detached
        assert RegistryEntryState.invalidated

    def test_B2_from_string_active(self):
        assert RegistryEntryState.from_string("active") == RegistryEntryState.active

    def test_B3_from_string_replaced(self):
        assert RegistryEntryState.from_string("replaced") == RegistryEntryState.replaced

    def test_B4_from_string_detached(self):
        assert RegistryEntryState.from_string("detached") == RegistryEntryState.detached

    def test_B5_from_string_invalidated(self):
        assert RegistryEntryState.from_string("invalidated") == RegistryEntryState.invalidated

    def test_B6_from_string_invalid_with_default(self):
        assert (
            RegistryEntryState.from_string("bogus", RegistryEntryState.detached)
            == RegistryEntryState.detached
        )

    def test_B7_from_string_invalid_without_default(self):
        # Falls back to active
        assert RegistryEntryState.from_string("bogus") == RegistryEntryState.active

    def test_B8_is_active_true(self):
        assert RegistryEntryState.active.is_active()

    def test_B9_is_active_false_for_non_active(self):
        assert not RegistryEntryState.detached.is_active()
        assert not RegistryEntryState.replaced.is_active()
        assert not RegistryEntryState.invalidated.is_active()

    def test_B10_is_terminal_replaced_and_invalidated(self):
        assert RegistryEntryState.replaced.is_terminal()
        assert RegistryEntryState.invalidated.is_terminal()

    def test_B11_is_terminal_false_for_active_and_detached(self):
        assert not RegistryEntryState.active.is_terminal()
        assert not RegistryEntryState.detached.is_terminal()

    def test_B12_is_recoverable_detached_only(self):
        assert RegistryEntryState.detached.is_recoverable()
        assert not RegistryEntryState.active.is_recoverable()
        assert not RegistryEntryState.replaced.is_recoverable()
        assert not RegistryEntryState.invalidated.is_recoverable()

    def test_B13_string_values(self):
        assert RegistryEntryState.active.value == "active"
        assert RegistryEntryState.replaced.value == "replaced"
        assert RegistryEntryState.detached.value == "detached"
        assert RegistryEntryState.invalidated.value == "invalidated"


# ===========================================================================
# C — RegistryTransition enum
# ===========================================================================


class TestRegistryTransition:
    def test_C1_all_values_exist(self):
        assert RegistryTransition.register
        assert RegistryTransition.reconnect
        assert RegistryTransition.reattach
        assert RegistryTransition.detach
        assert RegistryTransition.invalidate
        assert RegistryTransition.replace

    def test_C2_from_string_valid(self):
        assert RegistryTransition.from_string("reconnect") == RegistryTransition.reconnect
        assert RegistryTransition.from_string("detach") == RegistryTransition.detach

    def test_C3_from_string_invalid_with_default(self):
        assert (
            RegistryTransition.from_string("bogus", RegistryTransition.detach)
            == RegistryTransition.detach
        )

    def test_C4_string_values(self):
        assert RegistryTransition.register.value == "register"
        assert RegistryTransition.reconnect.value == "reconnect"
        assert RegistryTransition.reattach.value == "reattach"
        assert RegistryTransition.detach.value == "detach"
        assert RegistryTransition.invalidate.value == "invalidate"
        assert RegistryTransition.replace.value == "replace"


# ===========================================================================
# D — InvalidationReason enum
# ===========================================================================


class TestInvalidationReason:
    def test_D1_all_values_exist(self):
        assert InvalidationReason.none
        assert InvalidationReason.replaced
        assert InvalidationReason.detached
        assert InvalidationReason.disconnected
        assert InvalidationReason.disabled
        assert InvalidationReason.invalidated
        assert InvalidationReason.bad_posture
        assert InvalidationReason.missing_session
        assert InvalidationReason.missing_device

    def test_D2_from_string_valid(self):
        assert InvalidationReason.from_string("replaced") == InvalidationReason.replaced
        assert InvalidationReason.from_string("bad_posture") == InvalidationReason.bad_posture

    def test_D3_from_string_invalid_with_default(self):
        assert (
            InvalidationReason.from_string("bogus", InvalidationReason.detached)
            == InvalidationReason.detached
        )

    def test_D4_string_values(self):
        assert InvalidationReason.none.value == "none"
        assert InvalidationReason.replaced.value == "replaced"
        assert InvalidationReason.detached.value == "detached"
        assert InvalidationReason.invalidated.value == "invalidated"


# ===========================================================================
# E — AttachedSessionRegistryEntry construction and defaults
# ===========================================================================


class TestAttachedSessionRegistryEntryConstruction:
    def test_E1_minimal_construction(self):
        e = AttachedSessionRegistryEntry(device_id="dev1")
        assert e.device_id == "dev1"
        assert e.attachment_state == RegistryEntryState.active
        assert e.invalidation_reason == InvalidationReason.none
        assert e.posture == "join_runtime"
        assert isinstance(e.runtime_session_id, str) and e.runtime_session_id
        assert isinstance(e.entry_id, str) and e.entry_id

    def test_E2_all_required_fields_present(self):
        e = AttachedSessionRegistryEntry(
            device_id="dev1",
            session_id="sess1",
            posture="join_runtime",
            host_role="full_runtime_host",
        )
        assert e.session_id == "sess1"
        assert e.posture == "join_runtime"
        assert e.host_role == "full_runtime_host"

    def test_E3_runtime_session_id_is_unique_per_instance(self):
        e1 = AttachedSessionRegistryEntry(device_id="dev1")
        e2 = AttachedSessionRegistryEntry(device_id="dev1")
        assert e1.runtime_session_id != e2.runtime_session_id

    def test_E4_entry_id_is_unique_per_instance(self):
        e1 = AttachedSessionRegistryEntry(device_id="dev1")
        e2 = AttachedSessionRegistryEntry(device_id="dev1")
        assert e1.entry_id != e2.entry_id


# ===========================================================================
# F — AttachedSessionRegistryEntry helpers
# ===========================================================================


class TestAttachedSessionRegistryEntryHelpers:
    def test_F1_is_active_true_for_active(self):
        e = _make_entry()
        assert e.is_active()

    def test_F2_is_active_false_for_detached(self):
        e = _make_entry(attachment_state=RegistryEntryState.detached)
        assert not e.is_active()

    def test_F3_is_terminal_for_replaced(self):
        e = _make_entry(attachment_state=RegistryEntryState.replaced)
        assert e.is_terminal()

    def test_F4_is_terminal_for_invalidated(self):
        e = _make_entry(attachment_state=RegistryEntryState.invalidated)
        assert e.is_terminal()

    def test_F5_is_recoverable_for_detached(self):
        e = _make_entry(attachment_state=RegistryEntryState.detached)
        assert e.is_recoverable()

    def test_F6_not_recoverable_for_invalidated(self):
        e = _make_entry(attachment_state=RegistryEntryState.invalidated)
        assert not e.is_recoverable()


# ===========================================================================
# G — AttachedSessionRegistryEntry.to_dict() required keys
# ===========================================================================


class TestAttachedSessionRegistryEntryToDict:
    def test_G1_contains_session_id(self):
        e = _make_entry(session_id="s1")
        d = e.to_dict()
        assert "session_id" in d
        assert d["session_id"] == "s1"

    def test_G2_contains_device_id(self):
        e = _make_entry(device_id="d1")
        d = e.to_dict()
        assert "device_id" in d
        assert d["device_id"] == "d1"

    def test_G3_contains_runtime_session_id(self):
        e = _make_entry()
        d = e.to_dict()
        assert "runtime_session_id" in d
        assert d["runtime_session_id"] == e.runtime_session_id

    def test_G4_contains_attachment_state(self):
        e = _make_entry()
        d = e.to_dict()
        assert "attachment_state" in d
        assert d["attachment_state"] == "active"

    def test_G5_contains_invalidation_reason(self):
        e = _make_entry(invalidation_reason=InvalidationReason.detached)
        d = e.to_dict()
        assert "invalidation_reason" in d
        assert d["invalidation_reason"] == "detached"

    def test_G6_contains_posture(self):
        e = _make_entry(posture="join_runtime")
        d = e.to_dict()
        assert "posture" in d
        assert d["posture"] == "join_runtime"

    def test_G7_contains_host_role(self):
        e = _make_entry(host_role="full_runtime_host")
        d = e.to_dict()
        assert "host_role" in d
        assert d["host_role"] == "full_runtime_host"

    def test_G8_to_dict_is_json_serialisable(self):
        e = _make_entry()
        s = json.dumps(e.to_dict())
        assert s


# ===========================================================================
# H — AttachedSessionRegistryEntry round-trip
# ===========================================================================


class TestAttachedSessionRegistryEntryRoundTrip:
    def test_H1_from_dict_round_trip(self):
        e = _make_entry(session_id="s1", device_id="d1", posture="join_runtime")
        d = e.to_dict()
        e2 = AttachedSessionRegistryEntry.from_dict(d)
        assert e2.session_id == "s1"
        assert e2.device_id == "d1"
        assert e2.runtime_session_id == e.runtime_session_id
        assert e2.attachment_state == RegistryEntryState.active
        assert e2.posture == "join_runtime"

    def test_H2_to_json_and_back(self):
        e = _make_entry(session_id="s2")
        raw = e.to_json()
        d = json.loads(raw)
        e2 = AttachedSessionRegistryEntry.from_dict(d)
        assert e2.session_id == "s2"
        assert e2.runtime_session_id == e.runtime_session_id

    def test_H3_from_dict_raises_on_non_dict(self):
        with pytest.raises(ValueError):
            AttachedSessionRegistryEntry.from_dict("not a dict")


# ===========================================================================
# I — AttachedSessionRegistrySnapshot
# ===========================================================================


class TestAttachedSessionRegistrySnapshot:
    def test_I1_construction_defaults(self):
        snap = AttachedSessionRegistrySnapshot()
        assert snap.entries == []
        assert snap.active_count == 0
        assert snap.total_count == 0
        assert isinstance(snap.snapshot_id, str) and snap.snapshot_id

    def test_I2_to_dict_contains_required_keys(self):
        snap = AttachedSessionRegistrySnapshot(active_count=1, total_count=2)
        d = snap.to_dict()
        assert "snapshot_id" in d
        assert "entries" in d
        assert "active_count" in d
        assert "replaced_count" in d
        assert "detached_count" in d
        assert "invalidated_count" in d
        assert "total_count" in d
        assert "snapshotted_at" in d
        assert "policy_sentinels" in d

    def test_I3_to_json_is_valid(self):
        snap = AttachedSessionRegistrySnapshot()
        raw = snap.to_json()
        d = json.loads(raw)
        assert "snapshot_id" in d


# ===========================================================================
# J — AttachedSessionRegistry initial state
# ===========================================================================


class TestAttachedSessionRegistryInitialState:
    def test_J1_buffer_is_empty_on_init(self):
        r = _make_registry()
        assert r.size() == 0

    def test_J2_capacity_is_128(self):
        r = _make_registry()
        assert r.capacity() == 128

    def test_J3_list_all_active_is_empty(self):
        r = _make_registry()
        assert r.list_all_active() == []

    def test_J4_get_active_for_device_returns_none(self):
        r = _make_registry()
        assert r.get_active_for_device("nonexistent") is None


# ===========================================================================
# K — AttachedSessionRegistry: push_new
# ===========================================================================


class TestAttachedSessionRegistryPushNew:
    def test_K1_push_increases_size(self):
        r = _make_registry()
        e = _make_entry(device_id="d1", session_id="s1")
        r.push_new(e)
        assert r.size() == 1

    def test_K2_push_active_entry_updates_active_by_device(self):
        r = _make_registry()
        e = _make_entry(device_id="d1", session_id="s1")
        r.push_new(e)
        found = r.get_active_for_device("d1")
        assert found is not None
        assert found.entry_id == e.entry_id

    def test_K3_push_non_active_entry_does_not_update_active_by_device(self):
        r = _make_registry()
        e = _make_entry(
            device_id="d1", attachment_state=RegistryEntryState.detached
        )
        r.push_new(e)
        assert r.get_active_for_device("d1") is None


# ===========================================================================
# L/M — AttachedSessionRegistry: get_active_for_device
# ===========================================================================


class TestGetActiveForDevice:
    def test_L1_returns_active_entry(self):
        r = _make_registry()
        e = _make_entry(device_id="d1")
        r.push_new(e)
        result = r.get_active_for_device("d1")
        assert result is not None
        assert result.device_id == "d1"

    def test_M1_returns_none_for_detached(self):
        r = _make_registry()
        e = _make_entry(
            device_id="d1", attachment_state=RegistryEntryState.detached
        )
        r.push_new(e)
        assert r.get_active_for_device("d1") is None

    def test_M2_returns_none_for_unknown_device(self):
        r = _make_registry()
        assert r.get_active_for_device("unknown") is None


# ===========================================================================
# N/O — get_by_session_id
# ===========================================================================


class TestGetBySessionId:
    def test_N1_returns_active_entry_by_session_id(self):
        r = _make_registry()
        e = _make_entry(device_id="d1", session_id="s1")
        r.push_new(e)
        result = r.get_by_session_id("s1", active_only=True)
        assert result is not None
        assert result.session_id == "s1"

    def test_N2_returns_none_for_non_active_with_active_only_true(self):
        r = _make_registry()
        e = _make_entry(
            device_id="d1",
            session_id="s1",
            attachment_state=RegistryEntryState.detached,
        )
        r.push_new(e)
        assert r.get_by_session_id("s1", active_only=True) is None

    def test_O1_returns_non_active_entry_with_active_only_false(self):
        r = _make_registry()
        e = _make_entry(
            device_id="d1",
            session_id="s1",
            attachment_state=RegistryEntryState.detached,
        )
        r.push_new(e)
        result = r.get_by_session_id("s1", active_only=False)
        assert result is not None

    def test_O2_returns_none_for_unknown_session_id(self):
        r = _make_registry()
        assert r.get_by_session_id("nonexistent", active_only=False) is None


# ===========================================================================
# P — supersede_active_for_device
# ===========================================================================


class TestSupersedeActiveForDevice:
    def test_P1_supersede_moves_old_entry_to_replaced(self):
        r = _make_registry()
        e1 = _make_entry(device_id="d1", session_id="s1")
        r.push_new(e1)
        old = r.supersede_active_for_device("d1")
        assert old is not None
        assert old.attachment_state == RegistryEntryState.replaced
        assert old.invalidation_reason == InvalidationReason.replaced

    def test_P2_supersede_returns_none_if_no_active(self):
        r = _make_registry()
        assert r.supersede_active_for_device("d1") is None

    def test_P3_after_supersede_device_has_no_active(self):
        r = _make_registry()
        e1 = _make_entry(device_id="d1", session_id="s1")
        r.push_new(e1)
        r.supersede_active_for_device("d1")
        assert r.get_active_for_device("d1") is None


# ===========================================================================
# Q/R — apply_transition
# ===========================================================================


class TestApplyTransition:
    def test_Q1_active_to_detached_via_detach(self):
        r = _make_registry()
        e = _make_entry()
        r.push_new(e)
        updated = r.apply_transition(e, RegistryTransition.detach)
        assert updated.attachment_state == RegistryEntryState.detached

    def test_Q2_active_to_invalidated_via_invalidate(self):
        r = _make_registry()
        e = _make_entry()
        r.push_new(e)
        updated = r.apply_transition(e, RegistryTransition.invalidate)
        assert updated.attachment_state == RegistryEntryState.invalidated

    def test_Q3_detached_to_active_via_reconnect(self):
        r = _make_registry()
        e = _make_entry(attachment_state=RegistryEntryState.detached)
        r.push_new(e)
        updated = r.apply_transition(e, RegistryTransition.reconnect)
        assert updated.attachment_state == RegistryEntryState.active

    def test_Q4_transition_preserves_runtime_session_id(self):
        r = _make_registry()
        e = _make_entry()
        r.push_new(e)
        original_rsid = e.runtime_session_id
        updated = r.apply_transition(e, RegistryTransition.detach)
        assert updated.runtime_session_id == original_rsid

    def test_Q5_transition_records_previous_state(self):
        r = _make_registry()
        e = _make_entry()
        r.push_new(e)
        updated = r.apply_transition(e, RegistryTransition.detach)
        assert updated.previous_state == RegistryEntryState.active

    def test_R1_illegal_transition_returns_original(self):
        r = _make_registry()
        # invalidated → reconnect is illegal
        e = _make_entry(attachment_state=RegistryEntryState.invalidated)
        r.push_new(e)
        result = r.apply_transition(e, RegistryTransition.reconnect)
        assert result.attachment_state == RegistryEntryState.invalidated

    def test_R2_illegal_transition_on_replaced_returns_original(self):
        r = _make_registry()
        e = _make_entry(attachment_state=RegistryEntryState.replaced)
        r.push_new(e)
        result = r.apply_transition(e, RegistryTransition.reconnect)
        assert result.attachment_state == RegistryEntryState.replaced


# ===========================================================================
# S/T — list_all_active and list_all
# ===========================================================================


class TestListEntries:
    def test_S1_list_all_active_returns_only_active(self):
        r = _make_registry()
        e_active = _make_entry(device_id="d1")
        e_detached = _make_entry(
            device_id="d2", attachment_state=RegistryEntryState.detached
        )
        r.push_new(e_active)
        r.push_new(e_detached)
        active_list = r.list_all_active()
        assert len(active_list) == 1
        assert active_list[0].device_id == "d1"

    def test_T1_list_all_returns_all_entries(self):
        r = _make_registry()
        e1 = _make_entry(device_id="d1")
        e2 = _make_entry(device_id="d2", attachment_state=RegistryEntryState.detached)
        r.push_new(e1)
        r.push_new(e2)
        all_list = r.list_all()
        assert len(all_list) == 2

    def test_T2_list_all_newest_first(self):
        r = _make_registry()
        e1 = _make_entry(device_id="d1")
        e2 = _make_entry(device_id="d2")
        r.push_new(e1)
        r.push_new(e2)
        all_list = r.list_all()
        assert all_list[0].device_id == "d2"


# ===========================================================================
# U/V — size, capacity, clear
# ===========================================================================


class TestSizeCapacityClear:
    def test_U1_size_reflects_entries(self):
        r = _make_registry()
        assert r.size() == 0
        r.push_new(_make_entry())
        assert r.size() == 1

    def test_U2_capacity_is_128(self):
        assert _make_registry().capacity() == 128

    def test_V1_clear_resets_buffer(self):
        r = _make_registry()
        r.push_new(_make_entry(device_id="d1", session_id="s1"))
        r.clear()
        assert r.size() == 0

    def test_V2_clear_resets_indices(self):
        r = _make_registry()
        r.push_new(_make_entry(device_id="d1", session_id="s1"))
        r.clear()
        assert r.get_active_for_device("d1") is None
        assert r.get_by_session_id("s1") is None


# ===========================================================================
# W — snapshot counts
# ===========================================================================


class TestSnapshotCounts:
    def test_W1_active_count(self):
        r = _make_registry()
        r.push_new(_make_entry(device_id="d1"))
        snap = r.snapshot()
        assert snap.active_count == 1

    def test_W2_detached_count(self):
        r = _make_registry()
        r.push_new(
            _make_entry(device_id="d1", attachment_state=RegistryEntryState.detached)
        )
        snap = r.snapshot()
        assert snap.detached_count == 1
        assert snap.active_count == 0

    def test_W3_replaced_count(self):
        r = _make_registry()
        r.push_new(
            _make_entry(device_id="d1", attachment_state=RegistryEntryState.replaced)
        )
        snap = r.snapshot()
        assert snap.replaced_count == 1

    def test_W4_invalidated_count(self):
        r = _make_registry()
        r.push_new(
            _make_entry(
                device_id="d1", attachment_state=RegistryEntryState.invalidated
            )
        )
        snap = r.snapshot()
        assert snap.invalidated_count == 1


# ===========================================================================
# X — FIFO eviction at capacity
# ===========================================================================


class TestFIFOEviction:
    def test_X1_fifo_eviction_at_capacity(self):
        r = AttachedSessionRegistry(capacity=5)
        entries = []
        for i in range(5):
            e = _make_entry(device_id=f"d{i}", session_id=f"s{i}")
            r.push_new(e)
            entries.append(e)
        # Push one more to evict oldest
        e_new = _make_entry(device_id="d5", session_id="s5")
        r.push_new(e_new)
        assert r.size() == 5
        # d0 should be evicted
        all_ids = [e.device_id for e in r.list_all()]
        assert "d0" not in all_ids
        assert "d5" in all_ids


# ===========================================================================
# Y/Z — register_session
# ===========================================================================


class TestRegisterSession:
    def test_Y1_creates_active_entry(self):
        r = _make_registry()
        e = register_session("dev1", session_id="s1", registry=r)
        assert e.attachment_state == RegistryEntryState.active

    def test_Y2_entry_has_correct_session_id(self):
        r = _make_registry()
        e = register_session("dev1", session_id="s1", registry=r)
        assert e.session_id == "s1"

    def test_Y3_entry_has_correct_device_id(self):
        r = _make_registry()
        e = register_session("dev1", session_id="s1", registry=r)
        assert e.device_id == "dev1"

    def test_Y4_entry_has_no_invalidation_reason(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        assert e.invalidation_reason == InvalidationReason.none

    def test_Y5_entry_has_posture(self):
        r = _make_registry()
        e = register_session("dev1", posture="join_runtime", registry=r)
        assert e.posture == "join_runtime"

    def test_Y6_entry_has_host_role(self):
        r = _make_registry()
        e = register_session("dev1", host_role="full_runtime_host", registry=r)
        assert e.host_role == "full_runtime_host"

    def test_Z1_runtime_session_id_is_non_empty_uuid_like(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        assert e.runtime_session_id
        # Should be UUID-shaped (36 chars with hyphens)
        assert len(e.runtime_session_id) == 36

    def test_Z2_last_transition_is_register(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        assert e.last_transition == RegistryTransition.register


# ===========================================================================
# AA/AB/AC — register_session replaces old active session
# ===========================================================================


class TestRegisterSessionReplaces:
    def test_AA1_old_active_entry_becomes_replaced(self):
        r = _make_registry()
        e1 = register_session("dev1", session_id="s1", registry=r)
        register_session("dev1", session_id="s2", registry=r)
        old = r.get_by_session_id("s1", active_only=False)
        assert old is not None
        assert old.attachment_state == RegistryEntryState.replaced

    def test_AB1_new_registration_has_different_runtime_session_id(self):
        r = _make_registry()
        e1 = register_session("dev1", session_id="s1", registry=r)
        e2 = register_session("dev1", session_id="s2", registry=r)
        assert e1.runtime_session_id != e2.runtime_session_id

    def test_AC1_lookup_by_old_session_id_returns_none_when_active_only(self):
        r = _make_registry()
        register_session("dev1", session_id="s1", registry=r)
        register_session("dev1", session_id="s2", registry=r)
        assert lookup_active_session("s1", registry=r) is None

    def test_AC2_lookup_by_new_session_id_returns_active(self):
        r = _make_registry()
        register_session("dev1", session_id="s1", registry=r)
        e2 = register_session("dev1", session_id="s2", registry=r)
        result = lookup_active_session("s2", registry=r)
        assert result is not None
        assert result.entry_id == e2.entry_id


# ===========================================================================
# AD/AE/AF/AG/AH — reconnect_session
# ===========================================================================


class TestReconnectSession:
    def test_AD1_restores_active_from_detached(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        e_rec = reconnect_session(e_det, registry=r)
        assert e_rec.attachment_state == RegistryEntryState.active

    def test_AE1_preserves_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        original_rsid = e.runtime_session_id
        e_det = detach_session(e, registry=r)
        e_rec = reconnect_session(e_det, registry=r)
        assert e_rec.runtime_session_id == original_rsid

    def test_AF1_last_transition_is_reconnect(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        e_rec = reconnect_session(e_det, registry=r)
        assert e_rec.last_transition == RegistryTransition.reconnect

    def test_AG1_invalidation_reason_is_none_after_reconnect(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        e_rec = reconnect_session(e_det, registry=r)
        assert e_rec.invalidation_reason == InvalidationReason.none

    def test_AH1_reconnect_on_already_active_stays_active(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_rec = reconnect_session(e, registry=r)
        assert e_rec.attachment_state == RegistryEntryState.active


# ===========================================================================
# AI/AJ/AK — reattach_session
# ===========================================================================


class TestReattachSession:
    def test_AI1_restores_active_from_detached(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        e_rea = reattach_session(e_det, registry=r)
        assert e_rea.attachment_state == RegistryEntryState.active

    def test_AJ1_preserves_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        original_rsid = e.runtime_session_id
        e_det = detach_session(e, registry=r)
        e_rea = reattach_session(e_det, registry=r)
        assert e_rea.runtime_session_id == original_rsid

    def test_AK1_can_update_host_role_on_reattach(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        e_rea = reattach_session(e_det, host_role="full_runtime_host", registry=r)
        assert e_rea.host_role == "full_runtime_host"


# ===========================================================================
# AL/AM/AN/AO — detach_session
# ===========================================================================


class TestDetachSession:
    def test_AL1_moves_to_detached(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        assert e_det.attachment_state == RegistryEntryState.detached

    def test_AM1_default_invalidation_reason_is_detached(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        assert e_det.invalidation_reason == InvalidationReason.detached

    def test_AN1_last_transition_is_detach(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        assert e_det.last_transition == RegistryTransition.detach

    def test_AO1_detached_entry_not_returned_by_lookup_session_by_device(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        detach_session(e, registry=r)
        assert lookup_session_by_device("dev1", registry=r) is None


# ===========================================================================
# AP/AQ/AR — invalidate_session
# ===========================================================================


class TestInvalidateSession:
    def test_AP1_moves_to_invalidated(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_inv = invalidate_session(e, registry=r)
        assert e_inv.attachment_state == RegistryEntryState.invalidated

    def test_AQ1_default_invalidation_reason(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_inv = invalidate_session(e, registry=r)
        assert e_inv.invalidation_reason == InvalidationReason.invalidated

    def test_AQ2_custom_invalidation_reason(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_inv = invalidate_session(e, InvalidationReason.bad_posture, registry=r)
        assert e_inv.invalidation_reason == InvalidationReason.bad_posture

    def test_AR1_terminal_state_reconnect_is_noop(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_inv = invalidate_session(e, registry=r)
        e_rec = reconnect_session(e_inv, registry=r)
        # Should still be invalidated (illegal transition)
        assert e_rec.attachment_state == RegistryEntryState.invalidated

    def test_AR2_terminal_state_reattach_is_noop(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_inv = invalidate_session(e, registry=r)
        e_rea = reattach_session(e_inv, registry=r)
        assert e_rea.attachment_state == RegistryEntryState.invalidated


# ===========================================================================
# AS/AT/AU — lookup_active_session
# ===========================================================================


class TestLookupActiveSession:
    def test_AS1_returns_active_entry(self):
        r = _make_registry()
        register_session("dev1", session_id="s1", registry=r)
        result = lookup_active_session("s1", registry=r)
        assert result is not None
        assert result.session_id == "s1"

    def test_AT1_returns_none_for_replaced_entry(self):
        r = _make_registry()
        register_session("dev1", session_id="s1", registry=r)
        register_session("dev1", session_id="s2", registry=r)
        assert lookup_active_session("s1", registry=r) is None

    def test_AU1_returns_entry_with_active_only_false(self):
        r = _make_registry()
        register_session("dev1", session_id="s1", registry=r)
        register_session("dev1", session_id="s2", registry=r)
        result = lookup_active_session("s1", active_only=False, registry=r)
        assert result is not None
        assert result.attachment_state == RegistryEntryState.replaced


# ===========================================================================
# AV/AW — lookup_session_by_device
# ===========================================================================


class TestLookupSessionByDevice:
    def test_AV1_returns_active_entry_by_device(self):
        r = _make_registry()
        e = register_session("dev1", session_id="s1", registry=r)
        result = lookup_session_by_device("dev1", registry=r)
        assert result is not None
        assert result.entry_id == e.entry_id

    def test_AW1_returns_none_after_detach(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        detach_session(e, registry=r)
        assert lookup_session_by_device("dev1", registry=r) is None

    def test_AW2_returns_none_for_unknown_device(self):
        r = _make_registry()
        assert lookup_session_by_device("unknown", registry=r) is None


# ===========================================================================
# AX/AY — list_active_sessions
# ===========================================================================


class TestListActiveSessions:
    def test_AX1_returns_all_active_entries(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        register_session("dev2", registry=r)
        active = list_active_sessions(registry=r)
        assert len(active) == 2

    def test_AY1_excludes_detached_entries(self):
        r = _make_registry()
        e1 = register_session("dev1", registry=r)
        register_session("dev2", registry=r)
        detach_session(e1, registry=r)
        active = list_active_sessions(registry=r)
        device_ids = {e.device_id for e in active}
        assert "dev1" not in device_ids
        assert "dev2" in device_ids

    def test_AY2_excludes_invalidated_entries(self):
        r = _make_registry()
        e1 = register_session("dev1", registry=r)
        invalidate_session(e1, registry=r)
        active = list_active_sessions(registry=r)
        assert len(active) == 0


# ===========================================================================
# AZ/BA/BB/BC/BD — build_registry_snapshot
# ===========================================================================


class TestBuildRegistrySnapshot:
    def test_AZ1_active_count_correct(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        register_session("dev2", registry=r)
        snap = build_registry_snapshot(registry=r)
        assert snap.active_count == 2

    def test_BA1_replaced_count_correct(self):
        r = _make_registry()
        register_session("dev1", session_id="s1", registry=r)
        register_session("dev1", session_id="s2", registry=r)
        snap = build_registry_snapshot(registry=r)
        assert snap.replaced_count == 1

    def test_BB1_detached_count_correct(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        detach_session(e, registry=r)
        snap = build_registry_snapshot(registry=r)
        assert snap.detached_count == 1

    def test_BC1_invalidated_count_correct(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        invalidate_session(e, registry=r)
        snap = build_registry_snapshot(registry=r)
        assert snap.invalidated_count == 1

    def test_BD1_policy_sentinels_non_empty(self):
        r = _make_registry()
        snap = build_registry_snapshot(registry=r)
        assert snap.policy_sentinels
        assert len(snap.policy_sentinels) > 0

    def test_BX1_total_count_matches_buffer_size(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        register_session("dev2", registry=r)
        snap = build_registry_snapshot(registry=r)
        assert snap.total_count == r.size()


# ===========================================================================
# BE/BF/BG — Multi-session scenarios
# ===========================================================================


class TestMultiSessionScenarios:
    def test_BE1_two_devices_independent_active_sessions(self):
        r = _make_registry()
        e1 = register_session("dev1", session_id="s1", registry=r)
        e2 = register_session("dev2", session_id="s2", registry=r)
        assert e1.is_active()
        assert e2.is_active()
        snap = build_registry_snapshot(registry=r)
        assert snap.active_count == 2

    def test_BF1_new_session_supersedes_old(self):
        r = _make_registry()
        e1 = register_session("dev1", session_id="s1", registry=r)
        e2 = register_session("dev1", session_id="s2", registry=r)
        # e1 should now be replaced
        old = r.get_by_session_id("s1", active_only=False)
        assert old.attachment_state == RegistryEntryState.replaced
        # e2 is the active one
        active = lookup_session_by_device("dev1", registry=r)
        assert active.entry_id == e2.entry_id

    def test_BG1_reconnect_of_one_device_does_not_affect_other(self):
        r = _make_registry()
        e1 = register_session("dev1", registry=r)
        e2 = register_session("dev2", registry=r)
        e1_det = detach_session(e1, registry=r)
        reconnect_session(e1_det, registry=r)
        # dev2 should still be active unchanged
        dev2_active = lookup_session_by_device("dev2", registry=r)
        assert dev2_active is not None
        assert dev2_active.entry_id == e2.entry_id


# ===========================================================================
# BH/BI — Reconnect/reattach preserving runtime_session_id
# ===========================================================================


class TestReconnectReattachPreservesRsid:
    def test_BH1_detach_then_reconnect_same_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        original_rsid = e.runtime_session_id
        e_det = detach_session(e, registry=r)
        e_rec = reconnect_session(e_det, registry=r)
        assert e_rec.runtime_session_id == original_rsid

    def test_BI1_detach_then_reattach_same_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        original_rsid = e.runtime_session_id
        e_det = detach_session(e, registry=r)
        e_rea = reattach_session(e_det, registry=r)
        assert e_rea.runtime_session_id == original_rsid


# ===========================================================================
# BJ/BK — Replace-old-session retrievable
# ===========================================================================


class TestReplaceOldSession:
    def test_BJ1_old_entry_retrievable_with_active_only_false(self):
        r = _make_registry()
        register_session("dev1", session_id="s1", registry=r)
        register_session("dev1", session_id="s2", registry=r)
        old = r.get_by_session_id("s1", active_only=False)
        assert old is not None
        assert old.session_id == "s1"
        assert old.attachment_state == RegistryEntryState.replaced

    def test_BK1_new_entry_is_active_old_is_replaced(self):
        r = _make_registry()
        e1 = register_session("dev1", session_id="s1", registry=r)
        e2 = register_session("dev1", session_id="s2", registry=r)
        assert e2.is_active()
        old = r.get_by_session_id("s1", active_only=False)
        assert old.attachment_state == RegistryEntryState.replaced


# ===========================================================================
# BL — Singleton reset
# ===========================================================================


class TestSingletonReset:
    def test_BL1_reset_creates_fresh_registry(self):
        # Register via singleton
        e = register_session("dev1", session_id="s1")
        assert lookup_session_by_device("dev1") is not None
        # Reset
        reset_session_registry()
        # Should now be empty
        assert lookup_session_by_device("dev1") is None

    def test_BL2_get_session_registry_returns_same_singleton(self):
        r1 = get_session_registry()
        r2 = get_session_registry()
        assert r1 is r2

    def test_BL3_reset_creates_new_singleton(self):
        r1 = get_session_registry()
        reset_session_registry()
        r2 = get_session_registry()
        assert r1 is not r2


# ===========================================================================
# BM — Explicit registry parameter
# ===========================================================================


class TestExplicitRegistryParameter:
    def test_BM1_register_session_with_explicit_registry(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        assert r.size() == 1
        assert e.is_active()

    def test_BM2_detach_session_with_explicit_registry(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(e, registry=r)
        assert r.get_active_for_device("dev1") is None

    def test_BM3_lookup_with_explicit_registry(self):
        r = _make_registry()
        register_session("dev1", session_id="s1", registry=r)
        result = lookup_active_session("s1", registry=r)
        assert result is not None


# ===========================================================================
# BN — Invalidation of replaced entry
# ===========================================================================


class TestInvalidationOfReplacedEntry:
    def test_BN1_replaced_entry_cannot_be_reactivated_via_reconnect(self):
        r = _make_registry()
        e1 = register_session("dev1", session_id="s1", registry=r)
        register_session("dev1", session_id="s2", registry=r)
        # e1 is now replaced
        old = r.get_by_session_id("s1", active_only=False)
        result = reconnect_session(old, registry=r)
        assert result.attachment_state == RegistryEntryState.replaced


# ===========================================================================
# BR — metadata merging
# ===========================================================================


class TestMetadataMerging:
    def test_BR1_metadata_preserved_across_detach(self):
        r = _make_registry()
        e = register_session("dev1", metadata={"key": "val"}, registry=r)
        e_det = detach_session(e, registry=r)
        assert e_det.metadata.get("key") == "val"

    def test_BR2_metadata_merged_on_reconnect(self):
        r = _make_registry()
        e = register_session("dev1", metadata={"a": 1}, registry=r)
        e_det = detach_session(e, registry=r)
        e_rec = reconnect_session(e_det, metadata={"b": 2}, registry=r)
        assert e_rec.metadata.get("a") == 1
        assert e_rec.metadata.get("b") == 2


# ===========================================================================
# BS — session_id index updated on push_new
# ===========================================================================


class TestSessionIdIndex:
    def test_BS1_session_id_index_updated_on_push(self):
        r = _make_registry()
        e = _make_entry(device_id="d1", session_id="s-unique")
        r.push_new(e)
        result = r.get_by_session_id("s-unique", active_only=False)
        assert result is not None
        assert result.session_id == "s-unique"


# ===========================================================================
# BT/BU — custom invalidation reasons
# ===========================================================================


class TestCustomInvalidationReasons:
    def test_BT1_custom_detach_reason_preserved(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_det = detach_session(
            e, reason=InvalidationReason.disconnected, registry=r
        )
        assert e_det.invalidation_reason == InvalidationReason.disconnected

    def test_BU1_bad_posture_invalidation_reason(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_inv = invalidate_session(
            e, InvalidationReason.bad_posture, registry=r
        )
        assert e_inv.invalidation_reason == InvalidationReason.bad_posture


# ===========================================================================
# BV — reconnect after invalidate is no-op (terminal)
# ===========================================================================


class TestTerminalStateNoOp:
    def test_BV1_reconnect_after_invalidate_noop(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e_inv = invalidate_session(e, registry=r)
        e_rec = reconnect_session(e_inv, registry=r)
        assert e_rec.attachment_state == RegistryEntryState.invalidated


# ===========================================================================
# BW — register_session for device with detached (not active) entry
# ===========================================================================


class TestRegisterForDetachedDevice:
    def test_BW1_register_for_detached_device_creates_new_session(self):
        r = _make_registry()
        e = register_session("dev1", session_id="s1", registry=r)
        e_det = detach_session(e, registry=r)
        # Now register new session for same device (old is detached, not active)
        e_new = register_session("dev1", session_id="s2", registry=r)
        assert e_new.is_active()
        # Old detached entry remains in detached state (supersede only affects active entries)
        old = r.get_by_session_id("s1", active_only=False)
        assert old.attachment_state == RegistryEntryState.detached

    def test_BW2_new_entry_has_new_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", session_id="s1", registry=r)
        e_det = detach_session(e, registry=r)
        e_new = register_session("dev1", session_id="s2", registry=r)
        assert e_new.runtime_session_id != e.runtime_session_id


# ===========================================================================
# BY/BZ — Snapshot serialisation
# ===========================================================================


class TestSnapshotSerialisation:
    def test_BY1_snapshot_to_dict_is_json_serialisable(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        snap = build_registry_snapshot(registry=r)
        s = json.dumps(snap.to_dict())
        assert s

    def test_BZ1_snapshot_to_json_is_valid(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        snap = build_registry_snapshot(registry=r)
        d = json.loads(snap.to_json())
        assert "snapshot_id" in d
        assert "entries" in d


# ===========================================================================
# BO — core.runtime re-exports
# ===========================================================================


class TestCoreRuntimeReexports:
    def test_BO1_all_pr19_symbols_in_core_runtime(self):
        import core.runtime as rt

        symbols = [
            "ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY",
            "REGISTRY_IS_SINGLE_TRUTH_SOURCE_POLICY",
            "REGISTRY_DEVICE_HAS_AT_MOST_ONE_ACTIVE_SESSION_POLICY",
            "REGISTRY_REGISTER_REPLACES_OLD_SESSION_POLICY",
            "REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY",
            "REGISTRY_DETACH_REQUIRES_EXPLICIT_SIGNAL_POLICY",
            "REGISTRY_INVALIDATED_ENTRY_IS_TERMINAL_POLICY",
            "REGISTRY_DISPATCH_MUST_CONSULT_REGISTRY_POLICY",
            "REGISTRY_REUSE_MUST_CONSULT_REGISTRY_POLICY",
            "REGISTRY_RECONCILIATION_MUST_CONSULT_REGISTRY_POLICY",
            "REGISTRY_LOOKUP_RETURNS_ACTIVE_ONLY_BY_DEFAULT_POLICY",
            "ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL",
            "RegistryEntryState",
            "RegistryTransition",
            "InvalidationReason",
            "AttachedSessionRegistryEntry",
            "AttachedSessionRegistrySnapshot",
            "AttachedSessionRegistry",
            "register_session",
            "reconnect_session",
            "reattach_session",
            "detach_session",
            "invalidate_session",
            "lookup_active_session",
            "lookup_session_by_device",
            "list_active_sessions",
            "build_registry_snapshot",
            "get_session_registry",
            "reset_session_registry",
        ]
        for sym in symbols:
            assert hasattr(rt, sym), f"core.runtime missing symbol: {sym}"


# ===========================================================================
# BP — projection.py sentinel
# ===========================================================================


class TestProjectionSentinel:
    def test_BP1_sentinel_present_and_not_unavailable(self):
        try:
            from core.routes.projection import (
                ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19,
            )
        except ImportError:
            pytest.skip("projection module not importable in this environment")

        assert ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19
        assert "UNAVAILABLE" not in ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19

    def test_BP2_sentinel_references_pr19(self):
        try:
            from core.routes.projection import (
                ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19,
            )
        except ImportError:
            pytest.skip("projection module not importable in this environment")

        assert "PR19" in ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19


# ===========================================================================
# BQ — PR19 sentinel contains 'package=19'
# ===========================================================================


class TestPR19Sentinel:
    def test_BQ1_pr19_sentinel_contains_package_19(self):
        assert "package=19" in ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL

    def test_BQ2_pr19_sentinel_contains_registry(self):
        assert "registry" in ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL.lower()
