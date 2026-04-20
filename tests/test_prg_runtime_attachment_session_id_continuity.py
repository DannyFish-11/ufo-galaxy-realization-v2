"""tests/test_prg_runtime_attachment_session_id_continuity.py
=============================================================
Tests for PR-G: runtime_attachment_session_id canonical handling +
continuity reconnect consumer.

Coverage groups
---------------
A  — PR-G sentinels present in contracts/dispatch_continuity.py.
B  — PR-G sentinels present in core/attached_runtime_session.py.
C  — PR-G sentinels present in core/attached_runtime_session_registry.py.
D  — DispatchContinuityContext carries prior_runtime_attachment_session_id.
E  — build_dispatch_continuity_context propagates prior_runtime_attachment_session_id.
F  — AttachedRuntimeSessionRecord.to_dict() exposes runtime_attachment_session_id.
G  — AttachedRuntimeSessionRecord.from_dict() round-trips runtime_attachment_session_id.
H  — attach_runtime_session: runtime_attachment_session_id propagated to record.
I  — attach_runtime_session: session_id used as fallback when runtime_attachment_session_id absent.
J  — AttachedSessionRegistryEntry carries runtime_attachment_session_id field.
K  — register_session: explicit runtime_attachment_session_id stored.
L  — register_session: fallback UUID generated when runtime_attachment_session_id absent.
M  — register_session: different device registrations get independent attachment IDs.
N  — AttachedSessionRegistryEntry.to_dict() / from_dict() round-trips runtime_attachment_session_id.
O  — lookup_session_by_attachment_id returns active entry by attachment id.
P  — lookup_session_by_attachment_id returns None for unknown id.
Q  — lookup_session_by_attachment_id respects active_only flag.
R  — classify_reconnect_outcome: continuity_resume when id matches active entry.
S  — classify_reconnect_outcome: continuity_resume when id matches detached entry.
T  — classify_reconnect_outcome: new_attachment when id does not match.
U  — classify_reconnect_outcome: new_attachment when no entry exists.
V  — classify_reconnect_outcome: new_attachment for terminal (replaced) entry.
W  — classify_reconnect_outcome: continuity_resume fallback when no id supplied (backward compat).
X  — classify_reconnect_outcome: new_attachment fallback when no id and no entry.
Y  — reconnect_session: preserves runtime_attachment_session_id through reconnect.
Z  — reconnect_session: caller may update runtime_attachment_session_id on reconnect.
AA — Idempotent reconnect: multiple reconnects do not create duplicate attachment IDs.
AB — New registration supersedes old session; old entry moves to replaced state.
AC — Attachment ID index updated correctly after supersede.
AD — classify_reconnect_outcome: new_attachment when existing entry is invalidated.
AE — DispatchContinuityContext round-trip preserves prior_runtime_attachment_session_id.
AF — reset_session_registry provides test isolation.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

from contracts.dispatch_continuity import (
    DISPATCH_CONTINUITY_PR_G_SENTINEL,
    RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_CONTINUITY_IDENTITY,
    CONTINUITY_CONSUMER_MUST_CONSUME_RUNTIME_ATTACHMENT_SESSION_ID_POLICY,
    RECONNECT_CONTINUITY_RESUME_REQUIRES_MATCHING_ATTACHMENT_ID_POLICY,
    DispatchContinuityContext,
    DispatchContinuityClass,
    build_dispatch_continuity_context,
)

from core.attached_runtime_session import (
    ATTACHED_RUNTIME_SESSION_PR_G_SENTINEL,
    RUNTIME_ATTACHMENT_SESSION_ID_CANONICAL_FIELD_POLICY,
    attach_runtime_session,
    reset_attached_runtime_session_runtime,
    AttachedRuntimeSessionRecord,
    AttachmentState,
)

from core.attached_runtime_session_registry import (
    ATTACHED_RUNTIME_REGISTRY_PR_G_SENTINEL,
    REGISTRY_RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_IDENTITY_PR_G_POLICY,
    REGISTRY_RECONNECT_OUTCOME_CLASSIFICATION_PR_G_POLICY,
    REGISTRY_FALLBACK_WHEN_ATTACHMENT_ID_ABSENT_PR_G_POLICY,
    AttachedSessionRegistry,
    AttachedSessionRegistryEntry,
    RegistryEntryState,
    RegistryTransition,
    InvalidationReason,
    register_session,
    reconnect_session,
    reattach_session,
    detach_session,
    invalidate_session,
    lookup_session_by_attachment_id,
    classify_reconnect_outcome,
    reset_session_registry,
    get_session_registry,
    _RECONNECT_OUTCOME_CONTINUITY_RESUME,
    _RECONNECT_OUTCOME_NEW_ATTACHMENT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry() -> AttachedSessionRegistry:
    """Return a fresh isolated registry for each test."""
    return AttachedSessionRegistry(capacity=32)


def _make_device_id() -> str:
    return f"dev_{uuid.uuid4().hex[:8]}"


def _make_attachment_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# A — PR-G sentinels: contracts/dispatch_continuity.py
# ---------------------------------------------------------------------------

class TestPRGSentinelsDispatchContinuity:
    """PR-G sentinels present in contracts/dispatch_continuity.py."""

    def test_pr_g_sentinel_present(self):
        assert DISPATCH_CONTINUITY_PR_G_SENTINEL
        assert "PR_G" in DISPATCH_CONTINUITY_PR_G_SENTINEL or "PR-G" in DISPATCH_CONTINUITY_PR_G_SENTINEL.upper() or "package=G" in DISPATCH_CONTINUITY_PR_G_SENTINEL

    def test_canonical_identity_sentinel(self):
        assert RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_CONTINUITY_IDENTITY
        assert "runtime_attachment_session_id" in RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_CONTINUITY_IDENTITY.lower()

    def test_continuity_consumer_policy(self):
        assert CONTINUITY_CONSUMER_MUST_CONSUME_RUNTIME_ATTACHMENT_SESSION_ID_POLICY
        assert "runtime_attachment_session_id" in CONTINUITY_CONSUMER_MUST_CONSUME_RUNTIME_ATTACHMENT_SESSION_ID_POLICY.lower()

    def test_reconnect_matching_policy(self):
        assert RECONNECT_CONTINUITY_RESUME_REQUIRES_MATCHING_ATTACHMENT_ID_POLICY
        assert "runtime_attachment_session_id" in RECONNECT_CONTINUITY_RESUME_REQUIRES_MATCHING_ATTACHMENT_ID_POLICY.lower()


# ---------------------------------------------------------------------------
# B — PR-G sentinels: core/attached_runtime_session.py
# ---------------------------------------------------------------------------

class TestPRGSentinelsAttachedRuntimeSession:
    """PR-G sentinels present in core/attached_runtime_session.py."""

    def test_pr_g_sentinel_present(self):
        assert ATTACHED_RUNTIME_SESSION_PR_G_SENTINEL
        assert "PR_G" in ATTACHED_RUNTIME_SESSION_PR_G_SENTINEL or "package=G" in ATTACHED_RUNTIME_SESSION_PR_G_SENTINEL

    def test_canonical_field_policy(self):
        assert RUNTIME_ATTACHMENT_SESSION_ID_CANONICAL_FIELD_POLICY
        assert "runtime_attachment_session_id" in RUNTIME_ATTACHMENT_SESSION_ID_CANONICAL_FIELD_POLICY.lower()


# ---------------------------------------------------------------------------
# C — PR-G sentinels: core/attached_runtime_session_registry.py
# ---------------------------------------------------------------------------

class TestPRGSentinelsRegistry:
    """PR-G sentinels present in core/attached_runtime_session_registry.py."""

    def test_pr_g_sentinel_present(self):
        assert ATTACHED_RUNTIME_REGISTRY_PR_G_SENTINEL
        assert "PR_G" in ATTACHED_RUNTIME_REGISTRY_PR_G_SENTINEL or "package=G" in ATTACHED_RUNTIME_REGISTRY_PR_G_SENTINEL

    def test_canonical_identity_policy(self):
        assert REGISTRY_RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_IDENTITY_PR_G_POLICY
        assert "runtime_attachment_session_id" in REGISTRY_RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_IDENTITY_PR_G_POLICY.lower()

    def test_classification_policy(self):
        assert REGISTRY_RECONNECT_OUTCOME_CLASSIFICATION_PR_G_POLICY
        assert "classify_reconnect_outcome" in REGISTRY_RECONNECT_OUTCOME_CLASSIFICATION_PR_G_POLICY.lower()

    def test_fallback_policy(self):
        assert REGISTRY_FALLBACK_WHEN_ATTACHMENT_ID_ABSENT_PR_G_POLICY
        assert "fallback" in REGISTRY_FALLBACK_WHEN_ATTACHMENT_ID_ABSENT_PR_G_POLICY.lower()


# ---------------------------------------------------------------------------
# D — DispatchContinuityContext: prior_runtime_attachment_session_id field
# ---------------------------------------------------------------------------

class TestDispatchContinuityContextPRGField:
    """DispatchContinuityContext carries prior_runtime_attachment_session_id."""

    def test_field_defaults_to_none(self):
        ctx = DispatchContinuityContext()
        assert ctx.prior_runtime_attachment_session_id is None

    def test_field_accepts_value(self):
        aid = _make_attachment_id()
        ctx = DispatchContinuityContext(prior_runtime_attachment_session_id=aid)
        assert ctx.prior_runtime_attachment_session_id == aid

    def test_field_persists_in_to_dict(self):
        aid = _make_attachment_id()
        ctx = DispatchContinuityContext(prior_runtime_attachment_session_id=aid)
        d = ctx.to_dict()
        assert d.get("prior_runtime_attachment_session_id") == aid

    def test_field_is_optional_for_backward_compat(self):
        ctx = DispatchContinuityContext(prior_dispatch_id="disp_001")
        assert ctx.prior_runtime_attachment_session_id is None


# ---------------------------------------------------------------------------
# E — build_dispatch_continuity_context: prior_runtime_attachment_session_id
# ---------------------------------------------------------------------------

class TestBuildDispatchContinuityContextPRG:
    """build_dispatch_continuity_context propagates prior_runtime_attachment_session_id."""

    def test_propagates_attachment_id(self):
        aid = _make_attachment_id()
        ctx = build_dispatch_continuity_context(
            prior_runtime_attachment_session_id=aid,
            originating_device_id="dev_abc",
        )
        assert ctx.prior_runtime_attachment_session_id == aid

    def test_omitted_defaults_to_none(self):
        ctx = build_dispatch_continuity_context(originating_device_id="dev_abc")
        assert ctx.prior_runtime_attachment_session_id is None

    def test_all_fields_together(self):
        aid = _make_attachment_id()
        ctx = build_dispatch_continuity_context(
            prior_dispatch_id="d001",
            prior_session_id="s001",
            prior_runtime_attachment_session_id=aid,
            originating_device_id="dev_abc",
        )
        assert ctx.prior_dispatch_id == "d001"
        assert ctx.prior_session_id == "s001"
        assert ctx.prior_runtime_attachment_session_id == aid


# ---------------------------------------------------------------------------
# F — AttachedRuntimeSessionRecord.to_dict() exposes runtime_attachment_session_id
# ---------------------------------------------------------------------------

class TestAttachedRuntimeSessionRecordToDict:
    """to_dict() exposes runtime_attachment_session_id explicitly."""

    def test_to_dict_includes_runtime_attachment_session_id(self):
        aid = _make_attachment_id()
        record = AttachedRuntimeSessionRecord(
            device_id="dev_001",
            session_id=aid,
        )
        d = record.to_dict()
        assert "runtime_attachment_session_id" in d
        assert d["runtime_attachment_session_id"] == aid

    def test_to_dict_runtime_attachment_session_id_matches_session_id(self):
        aid = _make_attachment_id()
        record = AttachedRuntimeSessionRecord(device_id="dev_001", session_id=aid)
        d = record.to_dict()
        assert d["runtime_attachment_session_id"] == d["session_id"]

    def test_to_dict_empty_session_id(self):
        record = AttachedRuntimeSessionRecord(device_id="dev_001")
        d = record.to_dict()
        assert "runtime_attachment_session_id" in d
        assert d["runtime_attachment_session_id"] == ""


# ---------------------------------------------------------------------------
# G — AttachedRuntimeSessionRecord.from_dict() round-trip
# ---------------------------------------------------------------------------

class TestAttachedRuntimeSessionRecordFromDict:
    """from_dict() round-trips runtime_attachment_session_id."""

    def test_round_trip_via_to_dict(self):
        aid = _make_attachment_id()
        record = AttachedRuntimeSessionRecord(device_id="dev_001", session_id=aid)
        d = record.to_dict()
        restored = AttachedRuntimeSessionRecord.from_dict(d)
        assert restored.session_id == aid
        assert restored.runtime_attachment_session_id == aid

    def test_from_dict_reads_runtime_attachment_session_id_key(self):
        aid = _make_attachment_id()
        d = {
            "device_id": "dev_001",
            "runtime_attachment_session_id": aid,
            "attachment_state": "attached",
        }
        record = AttachedRuntimeSessionRecord.from_dict(d)
        assert record.session_id == aid


# ---------------------------------------------------------------------------
# H — attach_runtime_session: runtime_attachment_session_id propagated
# ---------------------------------------------------------------------------

class TestAttachRuntimeSessionPRG:
    """attach_runtime_session propagates runtime_attachment_session_id."""

    def setup_method(self):
        reset_attached_runtime_session_runtime()

    def test_runtime_attachment_session_id_stored(self):
        aid = _make_attachment_id()
        record = attach_runtime_session(
            "dev_001",
            runtime_attachment_session_id=aid,
        )
        assert record.runtime_attachment_session_id == aid
        assert record.session_id == aid

    def test_runtime_attachment_session_id_takes_priority_over_session_id(self):
        aid = _make_attachment_id()
        record = attach_runtime_session(
            "dev_001",
            session_id="old_session",
            runtime_attachment_session_id=aid,
        )
        assert record.runtime_attachment_session_id == aid

    def test_attachment_state_is_attached(self):
        aid = _make_attachment_id()
        record = attach_runtime_session(
            "dev_001",
            runtime_attachment_session_id=aid,
        )
        assert record.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# I — attach_runtime_session: session_id used as fallback
# ---------------------------------------------------------------------------

class TestAttachRuntimeSessionFallback:
    """session_id used as fallback when runtime_attachment_session_id absent."""

    def setup_method(self):
        reset_attached_runtime_session_runtime()

    def test_session_id_fallback(self):
        sid = _make_attachment_id()
        record = attach_runtime_session("dev_001", session_id=sid)
        assert record.runtime_attachment_session_id == sid

    def test_no_id_yields_empty(self):
        record = attach_runtime_session("dev_001")
        assert record.runtime_attachment_session_id == ""


# ---------------------------------------------------------------------------
# J — AttachedSessionRegistryEntry: runtime_attachment_session_id field
# ---------------------------------------------------------------------------

class TestRegistryEntryField:
    """AttachedSessionRegistryEntry carries runtime_attachment_session_id."""

    def test_field_defaults_to_empty(self):
        entry = AttachedSessionRegistryEntry(device_id="dev_001")
        assert entry.runtime_attachment_session_id == ""

    def test_field_accepts_value(self):
        aid = _make_attachment_id()
        entry = AttachedSessionRegistryEntry(
            device_id="dev_001",
            runtime_attachment_session_id=aid,
        )
        assert entry.runtime_attachment_session_id == aid


# ---------------------------------------------------------------------------
# K — register_session: explicit runtime_attachment_session_id stored
# ---------------------------------------------------------------------------

class TestRegisterSessionPRG:
    """register_session stores explicit runtime_attachment_session_id."""

    def setup_method(self):
        reset_session_registry()

    def test_explicit_attachment_id_stored(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        assert entry.runtime_attachment_session_id == aid
        assert entry.is_active()

    def test_explicit_attachment_id_in_to_dict(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        d = entry.to_dict()
        assert d["runtime_attachment_session_id"] == aid


# ---------------------------------------------------------------------------
# L — register_session: fallback UUID generated when id absent
# ---------------------------------------------------------------------------

class TestRegisterSessionFallback:
    """register_session generates a fallback UUID when runtime_attachment_session_id absent."""

    def setup_method(self):
        reset_session_registry()

    def test_fallback_id_generated(self):
        entry = register_session("dev_001")
        assert entry.runtime_attachment_session_id
        # Should look like a UUID
        assert len(entry.runtime_attachment_session_id) == 36

    def test_fallback_ids_are_unique_across_calls(self):
        reset_session_registry()
        e1 = register_session("dev_001")
        reset_session_registry()
        e2 = register_session("dev_001")
        assert e1.runtime_attachment_session_id != e2.runtime_attachment_session_id


# ---------------------------------------------------------------------------
# M — register_session: different devices get independent attachment IDs
# ---------------------------------------------------------------------------

class TestRegisterSessionIndependentIDs:
    """Different device registrations get independent attachment IDs."""

    def setup_method(self):
        reset_session_registry()

    def test_different_devices_different_ids(self):
        e1 = register_session("dev_001")
        e2 = register_session("dev_002")
        assert e1.runtime_attachment_session_id != e2.runtime_attachment_session_id

    def test_same_explicit_id_stored_independently(self):
        aid1, aid2 = _make_attachment_id(), _make_attachment_id()
        e1 = register_session("dev_001", runtime_attachment_session_id=aid1)
        e2 = register_session("dev_002", runtime_attachment_session_id=aid2)
        assert e1.runtime_attachment_session_id == aid1
        assert e2.runtime_attachment_session_id == aid2


# ---------------------------------------------------------------------------
# N — AttachedSessionRegistryEntry: to_dict / from_dict round-trip
# ---------------------------------------------------------------------------

class TestRegistryEntryRoundTrip:
    """AttachedSessionRegistryEntry.to_dict() / from_dict() round-trips attachment id."""

    def setup_method(self):
        reset_session_registry()

    def test_to_dict_includes_field(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        d = entry.to_dict()
        assert d["runtime_attachment_session_id"] == aid

    def test_from_dict_restores_field(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        d = entry.to_dict()
        restored = AttachedSessionRegistryEntry.from_dict(d)
        assert restored.runtime_attachment_session_id == aid


# ---------------------------------------------------------------------------
# O — lookup_session_by_attachment_id: returns active entry
# ---------------------------------------------------------------------------

class TestLookupByAttachmentId:
    """lookup_session_by_attachment_id returns the correct entry."""

    def setup_method(self):
        reset_session_registry()

    def test_returns_active_entry(self):
        aid = _make_attachment_id()
        register_session("dev_001", runtime_attachment_session_id=aid)
        found = lookup_session_by_attachment_id(aid)
        assert found is not None
        assert found.runtime_attachment_session_id == aid
        assert found.device_id == "dev_001"

    def test_returns_none_for_unknown_id(self):
        assert lookup_session_by_attachment_id("nonexistent-id-xyz") is None

    def test_returns_none_for_empty_id(self):
        assert lookup_session_by_attachment_id("") is None


# ---------------------------------------------------------------------------
# P — lookup_session_by_attachment_id: None for unknown id
# ---------------------------------------------------------------------------
# (covered above in test_returns_none_for_unknown_id)


# ---------------------------------------------------------------------------
# Q — lookup_session_by_attachment_id: respects active_only flag
# ---------------------------------------------------------------------------

class TestLookupByAttachmentIdActiveOnly:
    """lookup_session_by_attachment_id respects active_only=False."""

    def setup_method(self):
        reset_session_registry()

    def test_active_only_true_does_not_return_detached(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        detach_session(entry)
        assert lookup_session_by_attachment_id(aid, active_only=True) is None

    def test_active_only_false_returns_detached(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        detach_session(entry)
        found = lookup_session_by_attachment_id(aid, active_only=False)
        assert found is not None
        assert found.runtime_attachment_session_id == aid


# ---------------------------------------------------------------------------
# R — classify_reconnect_outcome: continuity_resume when id matches active
# ---------------------------------------------------------------------------

class TestClassifyReconnectOutcome:
    """classify_reconnect_outcome decision logic."""

    def setup_method(self):
        reset_session_registry()

    def test_continuity_resume_matching_active(self):
        aid = _make_attachment_id()
        register_session("dev_001", runtime_attachment_session_id=aid)
        outcome, entry = classify_reconnect_outcome("dev_001", runtime_attachment_session_id=aid)
        assert outcome == _RECONNECT_OUTCOME_CONTINUITY_RESUME
        assert entry is not None
        assert entry.runtime_attachment_session_id == aid

    # S — continuity_resume when id matches detached entry
    def test_continuity_resume_matching_detached(self):
        aid = _make_attachment_id()
        e = register_session("dev_001", runtime_attachment_session_id=aid)
        detach_session(e)
        outcome, entry = classify_reconnect_outcome("dev_001", runtime_attachment_session_id=aid)
        assert outcome == _RECONNECT_OUTCOME_CONTINUITY_RESUME
        assert entry is not None

    # T — new_attachment when id does not match
    def test_new_attachment_non_matching_id(self):
        aid1 = _make_attachment_id()
        aid2 = _make_attachment_id()
        register_session("dev_001", runtime_attachment_session_id=aid1)
        outcome, entry = classify_reconnect_outcome("dev_001", runtime_attachment_session_id=aid2)
        assert outcome == _RECONNECT_OUTCOME_NEW_ATTACHMENT
        assert entry is None

    # U — new_attachment when no entry exists
    def test_new_attachment_no_entry(self):
        outcome, entry = classify_reconnect_outcome("dev_unknown")
        assert outcome == _RECONNECT_OUTCOME_NEW_ATTACHMENT
        assert entry is None

    # V — new_attachment for replaced (terminal) entry
    def test_new_attachment_replaced_entry(self):
        aid = _make_attachment_id()
        e = register_session("dev_001", runtime_attachment_session_id=aid)
        # Register again to supersede/replace the old entry
        register_session("dev_001", runtime_attachment_session_id=_make_attachment_id())
        outcome, entry = classify_reconnect_outcome("dev_001", runtime_attachment_session_id=aid)
        # The old aid is now on a replaced entry; should be new_attachment
        assert outcome == _RECONNECT_OUTCOME_NEW_ATTACHMENT

    # W — continuity_resume fallback when no id supplied
    def test_continuity_resume_fallback_no_id(self):
        aid = _make_attachment_id()
        register_session("dev_001", runtime_attachment_session_id=aid)
        outcome, entry = classify_reconnect_outcome("dev_001")
        assert outcome == _RECONNECT_OUTCOME_CONTINUITY_RESUME
        assert entry is not None

    # X — new_attachment fallback when no id and no entry
    def test_new_attachment_fallback_no_id_no_entry(self):
        outcome, entry = classify_reconnect_outcome("dev_neverregistered")
        assert outcome == _RECONNECT_OUTCOME_NEW_ATTACHMENT
        assert entry is None


# ---------------------------------------------------------------------------
# Y — reconnect_session: preserves runtime_attachment_session_id
# ---------------------------------------------------------------------------

class TestReconnectSessionPRG:
    """reconnect_session preserves runtime_attachment_session_id."""

    def setup_method(self):
        reset_session_registry()

    def test_preserves_attachment_id_through_reconnect(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        detached = detach_session(entry)
        reconnected = reconnect_session(detached)
        assert reconnected.runtime_attachment_session_id == aid

    # Z — caller may update runtime_attachment_session_id on reconnect
    def test_caller_can_update_attachment_id_on_reconnect(self):
        aid1 = _make_attachment_id()
        aid2 = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid1)
        detached = detach_session(entry)
        reconnected = reconnect_session(detached, runtime_attachment_session_id=aid2)
        assert reconnected.runtime_attachment_session_id == aid2

    def test_reconnect_increments_reconnect_count(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        detached = detach_session(entry)
        reconnected = reconnect_session(detached)
        assert reconnected.reconnect_count == 1

    def test_reconnect_restores_active_state(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        detached = detach_session(entry)
        reconnected = reconnect_session(detached)
        assert reconnected.is_active()


# ---------------------------------------------------------------------------
# AA — Idempotent reconnect: multiple reconnects don't create duplicates
# ---------------------------------------------------------------------------

class TestIdempotentReconnect:
    """Multiple reconnects are idempotent and don't create duplicate IDs."""

    def setup_method(self):
        reset_session_registry()

    def test_multiple_reconnects_preserve_same_attachment_id(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        reg = get_session_registry()
        # Simulate repeated detach/reconnect cycles
        for _ in range(3):
            entry = detach_session(entry)
            entry = reconnect_session(entry)
        assert entry.runtime_attachment_session_id == aid
        assert entry.reconnect_count == 3

    def test_at_most_one_active_entry_per_device_after_reconnect(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        entry = detach_session(entry)
        entry = reconnect_session(entry)
        active_entries = [e for e in get_session_registry().list_all() if e.is_active() and e.device_id == "dev_001"]
        assert len(active_entries) == 1


# ---------------------------------------------------------------------------
# AB — New registration supersedes old session
# ---------------------------------------------------------------------------

class TestNewRegistrationSupersedes:
    """New registration supersedes old active session."""

    def setup_method(self):
        reset_session_registry()

    def test_old_entry_moves_to_replaced(self):
        aid1 = _make_attachment_id()
        e1 = register_session("dev_001", runtime_attachment_session_id=aid1)
        aid2 = _make_attachment_id()
        e2 = register_session("dev_001", runtime_attachment_session_id=aid2)
        # e1 should now be replaced
        all_entries = get_session_registry().list_all()
        replaced_entries = [e for e in all_entries if e.entry_id == e1.entry_id]
        assert replaced_entries
        assert replaced_entries[0].attachment_state == RegistryEntryState.replaced

    def test_only_new_entry_is_active(self):
        aid1 = _make_attachment_id()
        register_session("dev_001", runtime_attachment_session_id=aid1)
        aid2 = _make_attachment_id()
        e2 = register_session("dev_001", runtime_attachment_session_id=aid2)
        active_entries = [e for e in get_session_registry().list_all() if e.is_active() and e.device_id == "dev_001"]
        assert len(active_entries) == 1
        assert active_entries[0].runtime_attachment_session_id == aid2


# ---------------------------------------------------------------------------
# AC — Attachment ID index updated after supersede
# ---------------------------------------------------------------------------

class TestAttachmentIdIndexAfterSupersede:
    """Attachment ID index reflects latest registration."""

    def setup_method(self):
        reset_session_registry()

    def test_lookup_returns_new_entry_after_supersede(self):
        aid1 = _make_attachment_id()
        register_session("dev_001", runtime_attachment_session_id=aid1)
        aid2 = _make_attachment_id()
        register_session("dev_001", runtime_attachment_session_id=aid2)
        found = lookup_session_by_attachment_id(aid2)
        assert found is not None
        assert found.runtime_attachment_session_id == aid2

    def test_lookup_old_id_returns_none_after_supersede(self):
        aid1 = _make_attachment_id()
        register_session("dev_001", runtime_attachment_session_id=aid1)
        register_session("dev_001", runtime_attachment_session_id=_make_attachment_id())
        # old attachment_id entry is now replaced (non-active)
        assert lookup_session_by_attachment_id(aid1, active_only=True) is None


# ---------------------------------------------------------------------------
# AD — classify_reconnect_outcome: new_attachment when invalidated
# ---------------------------------------------------------------------------

class TestClassifyInvalidated:
    """classify_reconnect_outcome returns new_attachment for invalidated entry."""

    def setup_method(self):
        reset_session_registry()

    def test_new_attachment_invalidated_entry(self):
        aid = _make_attachment_id()
        entry = register_session("dev_001", runtime_attachment_session_id=aid)
        invalidate_session(entry)
        outcome, found = classify_reconnect_outcome("dev_001", runtime_attachment_session_id=aid)
        assert outcome == _RECONNECT_OUTCOME_NEW_ATTACHMENT
        assert found is None


# ---------------------------------------------------------------------------
# AE — DispatchContinuityContext round-trip with PR-G field
# ---------------------------------------------------------------------------

class TestDispatchContinuityContextRoundTrip:
    """DispatchContinuityContext round-trips prior_runtime_attachment_session_id."""

    def test_round_trip_to_dict_from_dict(self):
        aid = _make_attachment_id()
        ctx = build_dispatch_continuity_context(
            prior_runtime_attachment_session_id=aid,
            originating_device_id="dev_001",
        )
        d = ctx.to_dict()
        restored = DispatchContinuityContext.from_dict(d)
        assert restored.prior_runtime_attachment_session_id == aid

    def test_round_trip_to_json(self):
        import json
        aid = _make_attachment_id()
        ctx = build_dispatch_continuity_context(prior_runtime_attachment_session_id=aid)
        json_str = ctx.to_json()
        parsed = json.loads(json_str)
        assert parsed["prior_runtime_attachment_session_id"] == aid

    def test_backward_compat_context_without_field(self):
        ctx = build_dispatch_continuity_context(originating_device_id="dev_001")
        d = ctx.to_dict()
        restored = DispatchContinuityContext.from_dict(d)
        assert restored.prior_runtime_attachment_session_id is None


# ---------------------------------------------------------------------------
# AF — reset_session_registry provides test isolation
# ---------------------------------------------------------------------------

class TestResetSessionRegistry:
    """reset_session_registry provides clean state for each test."""

    def test_reset_clears_entries(self):
        register_session("dev_001")
        reset_session_registry()
        reg = get_session_registry()
        assert reg.size() == 0
