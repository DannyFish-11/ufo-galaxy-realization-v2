"""tests/test_prg_attachment_session_continuity.py
====================================================
Tests for PR-G: Server-Side Continuity Handling for Android Runtime
Attachment Sessions.

This test suite verifies that:

1. PR-G policy sentinels are present in attached_runtime_session_registry.
2. ``AttachedSessionRegistryEntry`` carries ``runtime_attachment_session_id`` field.
3. ``register_session()`` accepts and stores ``runtime_attachment_session_id``.
4. ``runtime_attachment_session_id`` is preserved across reconnect transitions.
5. ``lookup_session_by_runtime_attachment_id()`` returns the correct entry.
6. ``resolve_reconnect_continuity()`` returns ``restore_existing`` when a
   non-terminal session exists for the device.
7. ``resolve_reconnect_continuity()`` returns ``restore_existing`` when the
   supplied ``runtime_attachment_session_id`` matches the stored value.
8. ``resolve_reconnect_continuity()`` returns ``register_new`` when no
   recoverable session exists.
9. ``resolve_reconnect_continuity()`` returns ``register_new`` when the
   supplied ``runtime_attachment_session_id`` does not match any stored entry
   for that device, and no other non-terminal session exists.
10. Multiple reconnects are idempotent — no duplicate active sessions.
11. After invalidation, ``resolve_reconnect_continuity()`` returns
    ``register_new`` (terminal entry is not recoverable).
12. ``to_dict()`` / ``from_dict()`` round-trip preserves
    ``runtime_attachment_session_id``.
13. PR-G sentinels are importable from ``core.runtime.source_dispatch_orchestrator``.
14. PR-G sentinels are importable from ``core.runtime`` (re-export).
15. ``ReconnectContinuityVerdict`` enum has all required values.
16. Fallback: when ``runtime_attachment_session_id`` is empty and a non-terminal
    device entry exists, verdict is ``restore_existing`` (device-keyed fallback).

Coverage groups
---------------
A  — Policy sentinels present in registry module.
B  — ReconnectContinuityVerdict enum values.
C  — AttachedSessionRegistryEntry.runtime_attachment_session_id field.
D  — register_session() accepts and stores runtime_attachment_session_id.
E  — runtime_attachment_session_id preserved through reconnect transition.
F  — runtime_attachment_session_id preserved through detach/reattach cycle.
G  — lookup_session_by_runtime_attachment_id() finds active entry.
H  — lookup_session_by_runtime_attachment_id() returns None for non-active.
I  — lookup_session_by_runtime_attachment_id() returns None for empty input.
J  — resolve_reconnect_continuity(): restore_existing when non-terminal exists.
K  — resolve_reconnect_continuity(): restore_existing with matching identity.
L  — resolve_reconnect_continuity(): register_new when no session exists.
M  — resolve_reconnect_continuity(): register_new after invalidation (terminal).
N  — resolve_reconnect_continuity(): register_new when identity mismatch and
     no other non-terminal entry for device.
O  — resolve_reconnect_continuity(): idempotent — multiple calls same result.
P  — Multiple reconnects do not create duplicate active sessions.
Q  — to_dict / from_dict round-trip preserves runtime_attachment_session_id.
R  — PR-G sentinels importable from orchestrator module.
S  — PR-G sentinels importable from core.runtime re-export.
T  — Fallback: empty runtime_attachment_session_id + non-terminal entry → restore.
U  — register_session() without runtime_attachment_session_id defaults to empty string.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.attached_runtime_session_registry import (
        ATTACHMENT_SESSION_CONTINUITY_PRG_SENTINEL,
        RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_CLIENT_IDENTITY_PRG_POLICY,
        RECONNECT_CONTINUITY_JUDGMENT_IS_IDEMPOTENT_PRG_POLICY,
        RECONNECT_RESTORES_IDENTITY_WITHOUT_NEW_RUNTIME_SESSION_ID_PRG_POLICY,
        NEW_ATTACHMENT_AFTER_RECONNECT_REPLACES_OLD_SESSION_PRG_POLICY,
        ReconnectContinuityVerdict,
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
        lookup_session_by_runtime_attachment_id,
        resolve_reconnect_continuity,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.runtime.source_dispatch_orchestrator import (
        ANDROID_ATTACHMENT_SESSION_CONTINUITY_PRG_SENTINEL,
        DISPATCH_TARGET_CONTINUITY_REQUIRES_ACTIVE_SESSION_PRG_POLICY,
        RECONNECT_CONTINUITY_VERDICT_GATES_SESSION_IDENTITY_PRG_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.runtime import (
        ANDROID_ATTACHMENT_SESSION_CONTINUITY_PRG_SENTINEL as _rt_prg_sentinel,
        DISPATCH_TARGET_CONTINUITY_REQUIRES_ACTIVE_SESSION_PRG_POLICY as _rt_dispatch_policy,
        RECONNECT_CONTINUITY_VERDICT_GATES_SESSION_IDENTITY_PRG_POLICY as _rt_verdict_policy,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

_skip_registry = pytest.mark.skipif(
    not _REGISTRY_AVAILABLE, reason="registry module unavailable"
)
_skip_orchestrator = pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE, reason="orchestrator module unavailable"
)
_skip_runtime = pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE, reason="core.runtime exports unavailable"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh() -> "AttachedSessionRegistry":
    return AttachedSessionRegistry()


# ===========================================================================
# A — Policy sentinels present in registry module
# ===========================================================================


@_skip_registry
class TestPolicysentinels:
    def test_AA1_prg_sentinel_non_empty(self):
        assert ATTACHMENT_SESSION_CONTINUITY_PRG_SENTINEL
        assert "PRG" in ATTACHMENT_SESSION_CONTINUITY_PRG_SENTINEL

    def test_AA2_canonical_client_identity_policy_non_empty(self):
        assert RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_CLIENT_IDENTITY_PRG_POLICY
        assert "runtime_attachment_session_id" in RUNTIME_ATTACHMENT_SESSION_ID_IS_CANONICAL_CLIENT_IDENTITY_PRG_POLICY

    def test_AA3_idempotent_policy_non_empty(self):
        assert RECONNECT_CONTINUITY_JUDGMENT_IS_IDEMPOTENT_PRG_POLICY
        assert "idempotent" in RECONNECT_CONTINUITY_JUDGMENT_IS_IDEMPOTENT_PRG_POLICY.lower()

    def test_AA4_restore_identity_policy_non_empty(self):
        assert RECONNECT_RESTORES_IDENTITY_WITHOUT_NEW_RUNTIME_SESSION_ID_PRG_POLICY

    def test_AA5_new_attachment_replaces_policy_non_empty(self):
        assert NEW_ATTACHMENT_AFTER_RECONNECT_REPLACES_OLD_SESSION_PRG_POLICY


# ===========================================================================
# B — ReconnectContinuityVerdict enum
# ===========================================================================


@_skip_registry
class TestReconnectContinuityVerdictEnum:
    def test_BA1_restore_existing_value(self):
        assert ReconnectContinuityVerdict.restore_existing == "restore_existing"

    def test_BA2_register_new_value(self):
        assert ReconnectContinuityVerdict.register_new == "register_new"

    def test_BA3_is_str_enum(self):
        assert isinstance(ReconnectContinuityVerdict.restore_existing, str)

    def test_BA4_two_values(self):
        values = {v.value for v in ReconnectContinuityVerdict}
        assert values == {"restore_existing", "register_new"}


# ===========================================================================
# C — AttachedSessionRegistryEntry.runtime_attachment_session_id field
# ===========================================================================


@_skip_registry
class TestEntryRuntimeAttachmentSessionIdField:
    def test_CA1_field_exists_with_empty_default(self):
        entry = AttachedSessionRegistryEntry(device_id="dev-1")
        assert hasattr(entry, "runtime_attachment_session_id")
        assert entry.runtime_attachment_session_id == ""

    def test_CA2_field_can_be_set(self):
        entry = AttachedSessionRegistryEntry(
            device_id="dev-1",
            runtime_attachment_session_id="rt-attach-abc",
        )
        assert entry.runtime_attachment_session_id == "rt-attach-abc"

    def test_CA3_to_dict_includes_field(self):
        entry = AttachedSessionRegistryEntry(
            device_id="dev-1",
            runtime_attachment_session_id="rt-attach-xyz",
        )
        d = entry.to_dict()
        assert "runtime_attachment_session_id" in d
        assert d["runtime_attachment_session_id"] == "rt-attach-xyz"

    def test_CA4_to_dict_empty_when_not_set(self):
        entry = AttachedSessionRegistryEntry(device_id="dev-1")
        d = entry.to_dict()
        assert d["runtime_attachment_session_id"] == ""


# ===========================================================================
# D — register_session() accepts and stores runtime_attachment_session_id
# ===========================================================================


@_skip_registry
class TestRegisterSessionWithRuntimeAttachmentId:
    def test_DA1_stores_when_supplied(self):
        reg = _fresh()
        entry = register_session(
            "dev-d1",
            runtime_attachment_session_id="rt-attach-d1",
            registry=reg,
        )
        assert entry.runtime_attachment_session_id == "rt-attach-d1"

    def test_DA2_empty_when_not_supplied(self):
        reg = _fresh()
        entry = register_session("dev-d2", registry=reg)
        assert entry.runtime_attachment_session_id == ""

    def test_DA3_new_registration_generates_new_runtime_session_id(self):
        reg = _fresh()
        e1 = register_session(
            "dev-d3",
            runtime_attachment_session_id="rt-a1",
            registry=reg,
        )
        e2 = register_session(
            "dev-d3",
            runtime_attachment_session_id="rt-a2",
            registry=reg,
        )
        assert e1.runtime_session_id != e2.runtime_session_id

    def test_DA4_stored_on_active_entry(self):
        reg = _fresh()
        entry = register_session(
            "dev-d4",
            runtime_attachment_session_id="rt-attach-d4",
            registry=reg,
        )
        assert entry.is_active()
        assert entry.runtime_attachment_session_id == "rt-attach-d4"


# ===========================================================================
# E — runtime_attachment_session_id preserved through reconnect
# ===========================================================================


@_skip_registry
class TestRuntimeAttachmentIdPreservedThroughReconnect:
    def test_EA1_preserved_after_detach_reconnect(self):
        reg = _fresh()
        entry = register_session(
            "dev-e1",
            runtime_attachment_session_id="rt-e1",
            registry=reg,
        )
        detached = detach_session(entry, registry=reg)
        reconnected = reconnect_session(detached, registry=reg)
        assert reconnected.runtime_attachment_session_id == "rt-e1"

    def test_EA2_runtime_session_id_also_preserved(self):
        reg = _fresh()
        entry = register_session(
            "dev-e2",
            runtime_attachment_session_id="rt-e2",
            registry=reg,
        )
        original_rsid = entry.runtime_session_id
        detached = detach_session(entry, registry=reg)
        reconnected = reconnect_session(detached, registry=reg)
        assert reconnected.runtime_session_id == original_rsid

    def test_EA3_reconnect_count_increments(self):
        reg = _fresh()
        entry = register_session(
            "dev-e3",
            runtime_attachment_session_id="rt-e3",
            registry=reg,
        )
        detached = detach_session(entry, registry=reg)
        reconnected = reconnect_session(detached, registry=reg)
        assert reconnected.reconnect_count == 1


# ===========================================================================
# F — runtime_attachment_session_id preserved through detach/reattach cycle
# ===========================================================================


@_skip_registry
class TestRuntimeAttachmentIdPreservedThroughReattach:
    def test_FA1_preserved_after_detach_reattach(self):
        reg = _fresh()
        entry = register_session(
            "dev-f1",
            runtime_attachment_session_id="rt-f1",
            registry=reg,
        )
        detached = detach_session(entry, registry=reg)
        reattached = reattach_session(detached, registry=reg)
        assert reattached.runtime_attachment_session_id == "rt-f1"
        assert reattached.is_active()


# ===========================================================================
# G — lookup_session_by_runtime_attachment_id() finds active entry
# ===========================================================================


@_skip_registry
class TestLookupByRuntimeAttachmentId:
    def test_GA1_finds_active_entry(self):
        reg = _fresh()
        entry = register_session(
            "dev-g1",
            runtime_attachment_session_id="rt-lookup-1",
            registry=reg,
        )
        found = lookup_session_by_runtime_attachment_id("rt-lookup-1", registry=reg)
        assert found is not None
        assert found.entry_id == entry.entry_id

    def test_GA2_returns_none_when_not_found(self):
        reg = _fresh()
        register_session("dev-g2", runtime_attachment_session_id="rt-lookup-2", registry=reg)
        result = lookup_session_by_runtime_attachment_id("nonexistent-id", registry=reg)
        assert result is None


# ===========================================================================
# H — lookup_session_by_runtime_attachment_id() returns None for non-active
# ===========================================================================


@_skip_registry
class TestLookupByRuntimeAttachmentIdNonActive:
    def test_HA1_returns_none_for_detached_when_active_only(self):
        reg = _fresh()
        entry = register_session(
            "dev-h1",
            runtime_attachment_session_id="rt-h1",
            registry=reg,
        )
        detach_session(entry, registry=reg)
        result = lookup_session_by_runtime_attachment_id(
            "rt-h1", active_only=True, registry=reg
        )
        assert result is None

    def test_HA2_returns_entry_for_detached_when_not_active_only(self):
        reg = _fresh()
        entry = register_session(
            "dev-h2",
            runtime_attachment_session_id="rt-h2",
            registry=reg,
        )
        detach_session(entry, registry=reg)
        result = lookup_session_by_runtime_attachment_id(
            "rt-h2", active_only=False, registry=reg
        )
        assert result is not None
        assert result.runtime_attachment_session_id == "rt-h2"


# ===========================================================================
# I — lookup_session_by_runtime_attachment_id() returns None for empty input
# ===========================================================================


@_skip_registry
class TestLookupByRuntimeAttachmentIdEmpty:
    def test_IA1_empty_string_returns_none(self):
        reg = _fresh()
        register_session("dev-i1", runtime_attachment_session_id="rt-i1", registry=reg)
        result = lookup_session_by_runtime_attachment_id("", registry=reg)
        assert result is None

    def test_IA2_none_equivalent_empty_returns_none(self):
        reg = _fresh()
        result = lookup_session_by_runtime_attachment_id("", registry=reg)
        assert result is None


# ===========================================================================
# J — resolve_reconnect_continuity(): restore_existing when non-terminal exists
# ===========================================================================


@_skip_registry
class TestResolveReconnectContinuityRestoreExisting:
    def test_JA1_active_session_gives_restore_verdict(self):
        reg = _fresh()
        register_session("dev-j1", registry=reg)
        verdict = resolve_reconnect_continuity("dev-j1", registry=reg)
        assert verdict == ReconnectContinuityVerdict.restore_existing

    def test_JA2_detached_session_gives_restore_verdict(self):
        reg = _fresh()
        entry = register_session("dev-j2", registry=reg)
        detach_session(entry, registry=reg)
        verdict = resolve_reconnect_continuity("dev-j2", registry=reg)
        assert verdict == ReconnectContinuityVerdict.restore_existing


# ===========================================================================
# K — resolve_reconnect_continuity(): restore_existing with matching identity
# ===========================================================================


@_skip_registry
class TestResolveReconnectContinuityWithMatchingIdentity:
    def test_KA1_matching_runtime_attachment_id_gives_restore(self):
        reg = _fresh()
        register_session(
            "dev-k1",
            runtime_attachment_session_id="rt-k1",
            registry=reg,
        )
        verdict = resolve_reconnect_continuity(
            "dev-k1",
            runtime_attachment_session_id="rt-k1",
            registry=reg,
        )
        assert verdict == ReconnectContinuityVerdict.restore_existing

    def test_KA2_matching_after_detach_gives_restore(self):
        reg = _fresh()
        entry = register_session(
            "dev-k2",
            runtime_attachment_session_id="rt-k2",
            registry=reg,
        )
        detach_session(entry, registry=reg)
        verdict = resolve_reconnect_continuity(
            "dev-k2",
            runtime_attachment_session_id="rt-k2",
            registry=reg,
        )
        assert verdict == ReconnectContinuityVerdict.restore_existing


# ===========================================================================
# L — resolve_reconnect_continuity(): register_new when no session exists
# ===========================================================================


@_skip_registry
class TestResolveReconnectContinuityRegisterNew:
    def test_LA1_no_session_gives_register_new(self):
        reg = _fresh()
        verdict = resolve_reconnect_continuity("dev-l1", registry=reg)
        assert verdict == ReconnectContinuityVerdict.register_new

    def test_LA2_unknown_device_gives_register_new(self):
        reg = _fresh()
        register_session("dev-l2-other", registry=reg)
        verdict = resolve_reconnect_continuity("dev-l2-unknown", registry=reg)
        assert verdict == ReconnectContinuityVerdict.register_new


# ===========================================================================
# M — resolve_reconnect_continuity(): register_new after invalidation (terminal)
# ===========================================================================


@_skip_registry
class TestResolveReconnectContinuityAfterInvalidation:
    def test_MA1_invalidated_session_gives_register_new(self):
        reg = _fresh()
        entry = register_session("dev-m1", registry=reg)
        invalidate_session(entry, registry=reg)
        verdict = resolve_reconnect_continuity("dev-m1", registry=reg)
        assert verdict == ReconnectContinuityVerdict.register_new

    def test_MA2_replaced_session_also_gives_register_new_when_no_other_entry(self):
        reg = _fresh()
        # Registering twice replaces the first; if we then invalidate the new one,
        # only a replaced (terminal) entry remains.
        entry1 = register_session("dev-m2", registry=reg)
        entry2 = register_session("dev-m2", registry=reg)  # replaces entry1
        invalidate_session(entry2, registry=reg)
        # Both entries are now terminal (entry1=replaced, entry2=invalidated)
        verdict = resolve_reconnect_continuity("dev-m2", registry=reg)
        assert verdict == ReconnectContinuityVerdict.register_new


# ===========================================================================
# N — resolve_reconnect_continuity(): register_new when identity mismatch
# ===========================================================================


@_skip_registry
class TestResolveReconnectContinuityIdentityMismatch:
    def test_NA1_mismatch_but_device_has_active_entry_gives_restore(self):
        """Device fallback: even if runtime_attachment_session_id doesn't match,
        a non-terminal entry for the device gives restore_existing (step 2 fallback)."""
        reg = _fresh()
        register_session(
            "dev-n1",
            runtime_attachment_session_id="rt-n1-original",
            registry=reg,
        )
        # Supply a different id — identity mismatch, but step 2 still finds the device
        verdict = resolve_reconnect_continuity(
            "dev-n1",
            runtime_attachment_session_id="rt-n1-different",
            registry=reg,
        )
        # Step 2 fallback kicks in — device has a non-terminal entry
        assert verdict == ReconnectContinuityVerdict.restore_existing

    def test_NA2_completely_new_device_with_unknown_id_gives_register_new(self):
        reg = _fresh()
        verdict = resolve_reconnect_continuity(
            "dev-n2-new",
            runtime_attachment_session_id="rt-never-seen",
            registry=reg,
        )
        assert verdict == ReconnectContinuityVerdict.register_new


# ===========================================================================
# O — resolve_reconnect_continuity(): idempotent
# ===========================================================================


@_skip_registry
class TestResolveReconnectContinuityIdempotent:
    def test_OA1_multiple_calls_same_verdict(self):
        reg = _fresh()
        register_session(
            "dev-o1",
            runtime_attachment_session_id="rt-o1",
            registry=reg,
        )
        verdicts = [
            resolve_reconnect_continuity(
                "dev-o1",
                runtime_attachment_session_id="rt-o1",
                registry=reg,
            )
            for _ in range(5)
        ]
        assert all(v == ReconnectContinuityVerdict.restore_existing for v in verdicts)

    def test_OA2_does_not_mutate_registry(self):
        reg = _fresh()
        register_session("dev-o2", registry=reg)
        size_before = reg.size()
        resolve_reconnect_continuity("dev-o2", registry=reg)
        resolve_reconnect_continuity("dev-o2", registry=reg)
        assert reg.size() == size_before


# ===========================================================================
# P — Multiple reconnects do not create duplicate active sessions
# ===========================================================================


@_skip_registry
class TestNoduplicateActiveSessions:
    def test_PA1_single_active_session_after_reconnects(self):
        reg = _fresh()
        entry = register_session(
            "dev-p1",
            runtime_attachment_session_id="rt-p1",
            registry=reg,
        )
        for _ in range(3):
            detached = detach_session(entry, registry=reg)
            entry = reconnect_session(detached, registry=reg)

        active = reg.list_all_active()
        dev_active = [e for e in active if e.device_id == "dev-p1"]
        assert len(dev_active) == 1

    def test_PA2_runtime_session_id_stable_through_reconnects(self):
        reg = _fresh()
        entry = register_session(
            "dev-p2",
            runtime_attachment_session_id="rt-p2",
            registry=reg,
        )
        original_rsid = entry.runtime_session_id
        for _ in range(3):
            detached = detach_session(entry, registry=reg)
            entry = reconnect_session(detached, registry=reg)

        assert entry.runtime_session_id == original_rsid


# ===========================================================================
# Q — to_dict / from_dict round-trip preserves runtime_attachment_session_id
# ===========================================================================


@_skip_registry
class TestToFromDictRoundTrip:
    def test_QA1_round_trip_with_value(self):
        entry = AttachedSessionRegistryEntry(
            device_id="dev-q1",
            runtime_attachment_session_id="rt-q1",
        )
        d = entry.to_dict()
        restored = AttachedSessionRegistryEntry.from_dict(d)
        assert restored.runtime_attachment_session_id == "rt-q1"

    def test_QA2_round_trip_with_empty_value(self):
        entry = AttachedSessionRegistryEntry(device_id="dev-q2")
        d = entry.to_dict()
        restored = AttachedSessionRegistryEntry.from_dict(d)
        assert restored.runtime_attachment_session_id == ""

    def test_QA3_from_dict_without_field_defaults_to_empty(self):
        """Backward compatibility: older dicts without the field deserialise cleanly."""
        d = {
            "device_id": "dev-q3",
            "attachment_state": "active",
            "invalidation_reason": "none",
        }
        entry = AttachedSessionRegistryEntry.from_dict(d)
        assert entry.runtime_attachment_session_id == ""


# ===========================================================================
# R — PR-G sentinels importable from orchestrator
# ===========================================================================


@_skip_orchestrator
class TestOrchestratorPRGSentinels:
    def test_RA1_prg_sentinel_non_empty(self):
        assert ANDROID_ATTACHMENT_SESSION_CONTINUITY_PRG_SENTINEL
        assert "PRG" in ANDROID_ATTACHMENT_SESSION_CONTINUITY_PRG_SENTINEL

    def test_RA2_dispatch_target_continuity_policy_non_empty(self):
        assert DISPATCH_TARGET_CONTINUITY_REQUIRES_ACTIVE_SESSION_PRG_POLICY
        assert "active" in DISPATCH_TARGET_CONTINUITY_REQUIRES_ACTIVE_SESSION_PRG_POLICY.lower()

    def test_RA3_verdict_gates_identity_policy_non_empty(self):
        assert RECONNECT_CONTINUITY_VERDICT_GATES_SESSION_IDENTITY_PRG_POLICY
        assert "resolve_reconnect_continuity" in RECONNECT_CONTINUITY_VERDICT_GATES_SESSION_IDENTITY_PRG_POLICY


# ===========================================================================
# S — PR-G sentinels importable from core.runtime re-export
# ===========================================================================


@_skip_runtime
class TestCoreRuntimePRGReexports:
    def test_SA1_prg_sentinel_re_exported(self):
        assert _rt_prg_sentinel
        assert "PRG" in _rt_prg_sentinel

    def test_SA2_dispatch_policy_re_exported(self):
        assert _rt_dispatch_policy

    def test_SA3_verdict_policy_re_exported(self):
        assert _rt_verdict_policy


# ===========================================================================
# T — Fallback: empty runtime_attachment_session_id + non-terminal entry → restore
# ===========================================================================


@_skip_registry
class TestFallbackDeviceKeyedContinuity:
    def test_TA1_empty_id_with_active_device_entry_gives_restore(self):
        reg = _fresh()
        register_session("dev-t1", registry=reg)
        verdict = resolve_reconnect_continuity(
            "dev-t1",
            runtime_attachment_session_id="",
            registry=reg,
        )
        assert verdict == ReconnectContinuityVerdict.restore_existing

    def test_TA2_empty_id_with_no_device_entry_gives_register_new(self):
        reg = _fresh()
        verdict = resolve_reconnect_continuity(
            "dev-t2-unknown",
            runtime_attachment_session_id="",
            registry=reg,
        )
        assert verdict == ReconnectContinuityVerdict.register_new


# ===========================================================================
# U — register_session() without runtime_attachment_session_id defaults to empty
# ===========================================================================


@_skip_registry
class TestRegisterSessionDefaultRuntimeAttachmentId:
    def test_UA1_defaults_to_empty_string(self):
        reg = _fresh()
        entry = register_session("dev-u1", registry=reg)
        assert entry.runtime_attachment_session_id == ""

    def test_UA2_explicit_empty_string_is_stored_as_empty(self):
        reg = _fresh()
        entry = register_session(
            "dev-u2", runtime_attachment_session_id="", registry=reg
        )
        assert entry.runtime_attachment_session_id == ""
