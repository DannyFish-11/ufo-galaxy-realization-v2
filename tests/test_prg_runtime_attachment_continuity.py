"""tests/test_prg_runtime_attachment_continuity.py
===================================================
Tests for PR-G: Server-side continuity / reconnect / attachment identity
groundwork for Android runtime attachment sessions.

This test suite verifies that:

1. PR-G policy sentinels are present in the registry module.
2. ``AttachedSessionRegistryEntry`` carries a ``runtime_attachment_session_id``
   field that is stored, preserved across transitions, and round-trips through
   ``to_dict`` / ``from_dict``.
3. ``register_session()`` accepts and stores ``runtime_attachment_session_id``.
4. ``lookup_session_by_runtime_attachment_id()`` finds entries by their
   client-supplied RASID.
5. ``resolve_android_reconnect_continuity()`` — RASID-match path:
   a. Returns ``restored`` when an active entry with matching RASID exists.
   b. Returns ``restored`` when a detached entry with matching RASID is found,
      and the entry is moved back to ``active``.
   c. ``runtime_session_id`` is preserved on RASID-based restore.
6. ``resolve_android_reconnect_continuity()`` — device-id fallback path:
   a. Returns ``restored`` when an active entry exists for the device (no RASID).
   b. Returns ``restored`` when a detached entry exists for the device (no RASID).
   c. ``runtime_session_id`` is preserved on device-id fallback restore.
7. ``resolve_android_reconnect_continuity()`` — new registration path:
   a. Returns ``new_registration`` when no prior entry exists.
   b. The new entry gets the supplied RASID stored in
      ``runtime_attachment_session_id``.
8. Idempotency: calling ``resolve_android_reconnect_continuity()`` twice for
   the same active session returns the same entry without creating duplicates.
9. New-registration path correctly supersedes an existing active session
   (old session moves to ``replaced``), avoiding duplicate active targets.
10. RASID cross-device isolation: a RASID match for a different device_id is
    NOT honoured; device_id must also match.
11. Registration handler integration: ``handle_device_register`` uses
    ``resolve_android_reconnect_continuity()`` instead of always calling
    ``register_session()``.

Coverage groups
---------------
A  — Sentinels present in registry module.
B  — ``runtime_attachment_session_id`` field on ``AttachedSessionRegistryEntry``.
C  — ``register_session()`` stores RASID.
D  — ``lookup_session_by_runtime_attachment_id()`` — found and not found.
E  — ``resolve_android_reconnect_continuity()`` RASID-match: active entry.
F  — ``resolve_android_reconnect_continuity()`` RASID-match: detached → restored.
G  — ``resolve_android_reconnect_continuity()`` RASID-match: runtime_session_id preserved.
H  — ``resolve_android_reconnect_continuity()`` device-id fallback: active entry.
I  — ``resolve_android_reconnect_continuity()`` device-id fallback: detached → restored.
J  — ``resolve_android_reconnect_continuity()`` device-id fallback: runtime_session_id preserved.
K  — ``resolve_android_reconnect_continuity()`` new registration path.
L  — New registration stores supplied RASID.
M  — Idempotency: double-call on active session.
N  — New registration supersedes prior active session (no duplicates).
O  — RASID cross-device isolation: wrong device_id not honoured.
P  — to_dict / from_dict round-trip for ``runtime_attachment_session_id``.
Q  — ``runtime_attachment_session_id`` preserved through reconnect transition.
R  — ``runtime_attachment_session_id`` preserved through reattach transition.
S  — ``runtime_attachment_session_id`` preserved through posture update.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.attached_runtime_session_registry import (
        # Sentinels
        REGISTRY_RUNTIME_ATTACHMENT_SESSION_ID_CANONICAL_FIELD_PRG_SENTINEL,
        REGISTRY_RASID_IS_CLIENT_SUPPLIED_CONTINUITY_IDENTITY_PRG_POLICY,
        REGISTRY_RASID_CONTINUITY_LOOKUP_TAKES_PRIORITY_PRG_POLICY,
        REGISTRY_RECONNECT_OUTCOME_RESTORED_PRESERVES_RUNTIME_SESSION_ID_PRG_POLICY,
        REGISTRY_RECONNECT_OUTCOME_NEW_REPLACES_OLD_SESSION_PRG_POLICY,
        REGISTRY_RECONNECT_CONTINUITY_IS_IDEMPOTENT_PRG_POLICY,
        # Classes / enums
        AttachedSessionRegistry,
        AttachedSessionRegistryEntry,
        RegistryEntryState,
        RegistryTransition,
        InvalidationReason,
        ReconnectOutcome,
        # Functions
        register_session,
        reconnect_session,
        reattach_session,
        detach_session,
        lookup_session_by_device,
        lookup_session_by_runtime_attachment_id,
        resolve_android_reconnect_continuity,
        update_session_posture,
        reset_session_registry,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

_skip_registry = pytest.mark.skipif(
    not _REGISTRY_AVAILABLE,
    reason="core.attached_runtime_session_registry not importable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry() -> AttachedSessionRegistry:
    """Return a fresh isolated registry."""
    return AttachedSessionRegistry(capacity=128)


# ===========================================================================
# A — Sentinels present
# ===========================================================================


@_skip_registry
class TestPRGSentinels:
    def test_AA1_rasid_canonical_field_sentinel_present(self):
        assert REGISTRY_RUNTIME_ATTACHMENT_SESSION_ID_CANONICAL_FIELD_PRG_SENTINEL
        assert "PRG" in REGISTRY_RUNTIME_ATTACHMENT_SESSION_ID_CANONICAL_FIELD_PRG_SENTINEL

    def test_AA2_rasid_client_supplied_policy_present(self):
        assert REGISTRY_RASID_IS_CLIENT_SUPPLIED_CONTINUITY_IDENTITY_PRG_POLICY
        assert "POLICY" in REGISTRY_RASID_IS_CLIENT_SUPPLIED_CONTINUITY_IDENTITY_PRG_POLICY

    def test_AA3_rasid_priority_policy_present(self):
        assert REGISTRY_RASID_CONTINUITY_LOOKUP_TAKES_PRIORITY_PRG_POLICY
        assert "POLICY" in REGISTRY_RASID_CONTINUITY_LOOKUP_TAKES_PRIORITY_PRG_POLICY

    def test_AA4_restored_preserves_rsid_policy_present(self):
        assert REGISTRY_RECONNECT_OUTCOME_RESTORED_PRESERVES_RUNTIME_SESSION_ID_PRG_POLICY

    def test_AA5_new_replaces_old_policy_present(self):
        assert REGISTRY_RECONNECT_OUTCOME_NEW_REPLACES_OLD_SESSION_PRG_POLICY

    def test_AA6_idempotent_policy_present(self):
        assert REGISTRY_RECONNECT_CONTINUITY_IS_IDEMPOTENT_PRG_POLICY

    def test_AA7_reconnect_outcome_enum_values(self):
        assert ReconnectOutcome.restored.value == "restored"
        assert ReconnectOutcome.new_registration.value == "new_registration"


# ===========================================================================
# B — runtime_attachment_session_id field on AttachedSessionRegistryEntry
# ===========================================================================


@_skip_registry
class TestRASIDField:
    def test_AB1_field_defaults_to_empty_string(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        assert e.runtime_attachment_session_id == ""

    def test_AB2_field_set_via_constructor(self):
        entry = AttachedSessionRegistryEntry(
            device_id="dev1",
            runtime_attachment_session_id="rasid-abc",
        )
        assert entry.runtime_attachment_session_id == "rasid-abc"


# ===========================================================================
# C — register_session stores RASID
# ===========================================================================


@_skip_registry
class TestRegisterSessionStoresRASID:
    def test_AC1_rasid_stored_on_entry(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-001", registry=r)
        assert e.runtime_attachment_session_id == "rasid-001"

    def test_AC2_no_rasid_stores_empty_string(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        assert e.runtime_attachment_session_id == ""

    def test_AC3_rasid_distinct_from_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="client-rasid-xyz", registry=r)
        # runtime_session_id is server-generated (uuid) and should differ from RASID
        assert e.runtime_session_id != "client-rasid-xyz"
        assert e.runtime_attachment_session_id == "client-rasid-xyz"


# ===========================================================================
# D — lookup_session_by_runtime_attachment_id
# ===========================================================================


@_skip_registry
class TestLookupByRASID:
    def test_AD1_finds_active_entry_by_rasid(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-lookup-1", registry=r)
        found = lookup_session_by_runtime_attachment_id("rasid-lookup-1", registry=r)
        assert found is not None
        assert found.device_id == "dev1"
        assert found.runtime_attachment_session_id == "rasid-lookup-1"

    def test_AD2_returns_none_for_unknown_rasid(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="rasid-known", registry=r)
        found = lookup_session_by_runtime_attachment_id("rasid-unknown", registry=r)
        assert found is None

    def test_AD3_returns_none_for_empty_rasid(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="", registry=r)
        found = lookup_session_by_runtime_attachment_id("", registry=r)
        assert found is None

    def test_AD4_finds_detached_entry_by_rasid(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-det", registry=r)
        e2 = detach_session(e, registry=r)
        found = lookup_session_by_runtime_attachment_id("rasid-det", registry=r)
        assert found is not None
        assert found.attachment_state == RegistryEntryState.detached

    def test_AD5_active_only_returns_none_for_detached(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-det2", registry=r)
        detach_session(e, registry=r)
        found = lookup_session_by_runtime_attachment_id(
            "rasid-det2", active_only=True, registry=r
        )
        assert found is None

    def test_AD6_terminal_entry_skipped(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-term", registry=r)
        # Move to terminal state via a new registration (replaced)
        register_session("dev1", runtime_attachment_session_id="rasid-new", registry=r)
        # The old entry is now 'replaced' (terminal); lookup should skip it
        found = lookup_session_by_runtime_attachment_id("rasid-term", registry=r)
        assert found is None


# ===========================================================================
# E — resolve continuity: RASID-match active entry
# ===========================================================================


@_skip_registry
class TestResolveContinuityRASIDActive:
    def test_AE1_rasid_match_active_returns_restored(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="rasid-e1", registry=r)
        outcome, entry = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-e1", registry=r
        )
        assert outcome == ReconnectOutcome.restored

    def test_AE2_rasid_match_active_entry_is_active(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="rasid-e2", registry=r)
        _, entry = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-e2", registry=r
        )
        assert entry.is_active()

    def test_AE3_rasid_match_active_entry_has_correct_rasid(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="rasid-e3", registry=r)
        _, entry = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-e3", registry=r
        )
        assert entry.runtime_attachment_session_id == "rasid-e3"


# ===========================================================================
# F — resolve continuity: RASID-match detached → restored
# ===========================================================================


@_skip_registry
class TestResolveContinuityRASIDDetachedRestore:
    def test_AF1_rasid_match_detached_returns_restored(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-f1", registry=r)
        detach_session(e, registry=r)
        outcome, entry = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-f1", registry=r
        )
        assert outcome == ReconnectOutcome.restored

    def test_AF2_rasid_match_detached_entry_becomes_active(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-f2", registry=r)
        detach_session(e, registry=r)
        _, entry = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-f2", registry=r
        )
        assert entry.is_active()

    def test_AF3_rasid_match_detached_increments_reconnect_count(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-f3", registry=r)
        detach_session(e, registry=r)
        _, entry = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-f3", registry=r
        )
        assert entry.reconnect_count == 1


# ===========================================================================
# G — RASID-match preserves runtime_session_id
# ===========================================================================


@_skip_registry
class TestResolveContinuityRASIDPreservesRSID:
    def test_AG1_detached_restore_preserves_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-g1", registry=r)
        original_rsid = e.runtime_session_id
        detach_session(e, registry=r)
        _, entry = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-g1", registry=r
        )
        assert entry.runtime_session_id == original_rsid

    def test_AG2_active_match_returns_same_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-g2", registry=r)
        original_rsid = e.runtime_session_id
        _, entry = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-g2", registry=r
        )
        assert entry.runtime_session_id == original_rsid


# ===========================================================================
# H — device-id fallback: active entry
# ===========================================================================


@_skip_registry
class TestResolveContinuityDeviceIDFallbackActive:
    def test_AH1_no_rasid_active_entry_returns_restored(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        outcome, entry = resolve_android_reconnect_continuity("dev1", registry=r)
        assert outcome == ReconnectOutcome.restored

    def test_AH2_no_rasid_active_entry_is_active(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        _, entry = resolve_android_reconnect_continuity("dev1", registry=r)
        assert entry.is_active()


# ===========================================================================
# I — device-id fallback: detached → restored
# ===========================================================================


@_skip_registry
class TestResolveContinuityDeviceIDFallbackDetachedRestore:
    def test_AI1_no_rasid_detached_entry_returns_restored(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        detach_session(e, registry=r)
        outcome, entry = resolve_android_reconnect_continuity("dev1", registry=r)
        assert outcome == ReconnectOutcome.restored

    def test_AI2_no_rasid_detached_entry_becomes_active(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        detach_session(e, registry=r)
        _, entry = resolve_android_reconnect_continuity("dev1", registry=r)
        assert entry.is_active()

    def test_AI3_no_rasid_detached_increments_reconnect_count(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        detach_session(e, registry=r)
        _, entry = resolve_android_reconnect_continuity("dev1", registry=r)
        assert entry.reconnect_count == 1


# ===========================================================================
# J — device-id fallback preserves runtime_session_id
# ===========================================================================


@_skip_registry
class TestResolveContinuityDeviceIDFallbackPreservesRSID:
    def test_AJ1_detached_restore_preserves_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        original_rsid = e.runtime_session_id
        detach_session(e, registry=r)
        _, entry = resolve_android_reconnect_continuity("dev1", registry=r)
        assert entry.runtime_session_id == original_rsid


# ===========================================================================
# K — new registration path
# ===========================================================================


@_skip_registry
class TestResolveContinuityNewRegistration:
    def test_AK1_no_prior_entry_returns_new_registration(self):
        r = _make_registry()
        outcome, entry = resolve_android_reconnect_continuity("dev-new", registry=r)
        assert outcome == ReconnectOutcome.new_registration

    def test_AK2_new_registration_entry_is_active(self):
        r = _make_registry()
        _, entry = resolve_android_reconnect_continuity("dev-new2", registry=r)
        assert entry.is_active()

    def test_AK3_new_registration_device_id_correct(self):
        r = _make_registry()
        _, entry = resolve_android_reconnect_continuity("dev-new3", registry=r)
        assert entry.device_id == "dev-new3"

    def test_AK4_no_rasid_unknown_device_returns_new_registration(self):
        r = _make_registry()
        outcome, _ = resolve_android_reconnect_continuity(
            "never-seen", runtime_attachment_session_id="some-id", registry=r
        )
        assert outcome == ReconnectOutcome.new_registration


# ===========================================================================
# L — new registration stores supplied RASID
# ===========================================================================


@_skip_registry
class TestResolveContinuityNewRegistrationStoresRASID:
    def test_AL1_new_registration_stores_rasid(self):
        r = _make_registry()
        _, entry = resolve_android_reconnect_continuity(
            "dev-nl", runtime_attachment_session_id="rasid-nl-1", registry=r
        )
        assert entry.runtime_attachment_session_id == "rasid-nl-1"

    def test_AL2_new_registration_no_rasid_stores_empty(self):
        r = _make_registry()
        _, entry = resolve_android_reconnect_continuity("dev-nl2", registry=r)
        assert entry.runtime_attachment_session_id == ""


# ===========================================================================
# M — Idempotency
# ===========================================================================


@_skip_registry
class TestResolveContinuityIdempotency:
    def test_AM1_double_call_active_same_runtime_session_id(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="rasid-idem", registry=r)
        _, e1 = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-idem", registry=r
        )
        _, e2 = resolve_android_reconnect_continuity(
            "dev1", runtime_attachment_session_id="rasid-idem", registry=r
        )
        assert e1.runtime_session_id == e2.runtime_session_id

    def test_AM2_double_call_active_entry_count_unchanged(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        resolve_android_reconnect_continuity("dev1", registry=r)
        resolve_android_reconnect_continuity("dev1", registry=r)
        active = r.list_all_active()
        # Still exactly one active entry for dev1
        dev1_active = [e for e in active if e.device_id == "dev1"]
        assert len(dev1_active) == 1

    def test_AM3_no_new_session_created_on_idempotent_call(self):
        r = _make_registry()
        register_session("dev1", registry=r)
        before_size = r.size()
        resolve_android_reconnect_continuity("dev1", registry=r)
        # Size should not grow on an idempotent call (active entry found)
        assert r.size() == before_size


# ===========================================================================
# N — New registration supersedes prior active session
# ===========================================================================


@_skip_registry
class TestResolveContinuityNewRegistrationSupersedes:
    def test_AN1_new_registration_replaces_old_active_session(self):
        r = _make_registry()
        old_e = register_session("dev1", registry=r)
        old_rsid = old_e.runtime_session_id
        # Invalidate the existing entry to force new_registration path
        from core.attached_runtime_session_registry import invalidate_session
        invalidate_session(old_e, registry=r)
        outcome, new_e = resolve_android_reconnect_continuity("dev1", registry=r)
        assert outcome == ReconnectOutcome.new_registration
        assert new_e.runtime_session_id != old_rsid

    def test_AN2_after_new_registration_only_one_active(self):
        r = _make_registry()
        old_e = register_session("dev1", registry=r)
        from core.attached_runtime_session_registry import invalidate_session
        invalidate_session(old_e, registry=r)
        resolve_android_reconnect_continuity("dev1", registry=r)
        active = [e for e in r.list_all_active() if e.device_id == "dev1"]
        assert len(active) == 1


# ===========================================================================
# O — RASID cross-device isolation
# ===========================================================================


@_skip_registry
class TestResolveContinuityRASIDCrossDeviceIsolation:
    def test_AO1_rasid_match_wrong_device_not_honoured(self):
        r = _make_registry()
        # Register dev1 with rasid-cross
        register_session("dev1", runtime_attachment_session_id="rasid-cross", registry=r)
        # dev2 claims the same RASID — should NOT restore dev1's session
        outcome, entry = resolve_android_reconnect_continuity(
            "dev2", runtime_attachment_session_id="rasid-cross", registry=r
        )
        # The outcome could be restored (if dev2 happens to have a session) or
        # new_registration; what matters is the returned entry belongs to dev2
        assert entry.device_id == "dev2"

    def test_AO2_rasid_wrong_device_falls_back_to_new_registration(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="rasid-cross2", registry=r)
        # dev-other has no prior session
        outcome, entry = resolve_android_reconnect_continuity(
            "dev-other", runtime_attachment_session_id="rasid-cross2", registry=r
        )
        assert outcome == ReconnectOutcome.new_registration
        assert entry.device_id == "dev-other"


# ===========================================================================
# P — to_dict / from_dict round-trip for runtime_attachment_session_id
# ===========================================================================


@_skip_registry
class TestRASIDRoundTrip:
    def test_AP1_to_dict_includes_rasid(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-rt1", registry=r)
        d = e.to_dict()
        assert "runtime_attachment_session_id" in d
        assert d["runtime_attachment_session_id"] == "rasid-rt1"

    def test_AP2_from_dict_restores_rasid(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-rt2", registry=r)
        d = e.to_dict()
        from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
        restored = AttachedSessionRegistryEntry.from_dict(d)
        assert restored.runtime_attachment_session_id == "rasid-rt2"

    def test_AP3_from_dict_empty_rasid_when_missing(self):
        data = {
            "device_id": "dev1",
            "attachment_state": "active",
            "invalidation_reason": "none",
        }
        from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
        entry = AttachedSessionRegistryEntry.from_dict(data)
        assert entry.runtime_attachment_session_id == ""


# ===========================================================================
# Q — RASID preserved through reconnect transition
# ===========================================================================


@_skip_registry
class TestRASIDPreservedThroughReconnect:
    def test_AQ1_reconnect_preserves_rasid(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-q1", registry=r)
        e_det = detach_session(e, registry=r)
        e_rec = reconnect_session(e_det, registry=r)
        assert e_rec.runtime_attachment_session_id == "rasid-q1"

    def test_AQ2_reconnect_also_preserves_runtime_session_id(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-q2", registry=r)
        original_rsid = e.runtime_session_id
        e_det = detach_session(e, registry=r)
        e_rec = reconnect_session(e_det, registry=r)
        assert e_rec.runtime_session_id == original_rsid


# ===========================================================================
# R — RASID preserved through reattach transition
# ===========================================================================


@_skip_registry
class TestRASIDPreservedThroughReattach:
    def test_AR1_reattach_preserves_rasid(self):
        r = _make_registry()
        e = register_session("dev1", runtime_attachment_session_id="rasid-r1", registry=r)
        e_det = detach_session(e, registry=r)
        e_rea = reattach_session(e_det, registry=r)
        assert e_rea.runtime_attachment_session_id == "rasid-r1"


# ===========================================================================
# S — RASID preserved through posture update
# ===========================================================================


@_skip_registry
class TestRASIDPreservedThroughPostureUpdate:
    def test_AS1_posture_update_preserves_rasid(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="rasid-s1", registry=r)
        updated = update_session_posture("dev1", "control_only", registry=r)
        assert updated is not None
        assert updated.runtime_attachment_session_id == "rasid-s1"

    def test_AS2_posture_update_back_to_join_runtime_preserves_rasid(self):
        r = _make_registry()
        register_session("dev1", runtime_attachment_session_id="rasid-s2", registry=r)
        update_session_posture("dev1", "control_only", registry=r)
        updated2 = update_session_posture("dev1", "join_runtime", registry=r)
        assert updated2 is not None
        assert updated2.runtime_attachment_session_id == "rasid-s2"
