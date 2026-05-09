"""
tests/test_prc_android_durable_continuity_bridge.py
=====================================================
PR-C regression suite: Android durable continuity identity bridge into V2
continuity/session coordination.

Validates:
1. Android durable continuity fields are ingested by the registry.
2. Reconnect/resume logic can preserve continuity when valid durable identity
   is supplied by the Android side.
3. Mismatched durable_session_id safely falls back to new_attachment.
4. Missing durable continuity values are handled safely (backward compat).
5. Existing V2 continuity semantics (runtime_attachment_session_id, etc.)
   are not broken by the new durable fields.
6. ContinuityEventContext and ContinuityDecisionArtifact carry durable fields.
7. FlowContinuityCoordinator.decide_reconnect propagates durable fields.
8. _extract_durable_continuity_fields helper extraction is correct.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset():
    from core.attached_runtime_session_registry import reset_session_registry
    reset_session_registry()


# ===========================================================================
# A — AttachedSessionRegistryEntry carries durable continuity fields
# ===========================================================================

class TestRegistryEntryDurableFields:
    """AttachedSessionRegistryEntry stores durable_session_id and continuity_epoch."""

    def setup_method(self):
        _reset()

    def test_default_values_are_empty(self):
        from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
        e = AttachedSessionRegistryEntry(device_id="dev-001")
        assert e.durable_session_id == ""
        assert e.continuity_epoch == 0

    def test_explicit_values_stored(self):
        from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
        e = AttachedSessionRegistryEntry(
            device_id="dev-001",
            durable_session_id="dsid-abc",
            continuity_epoch=3,
        )
        assert e.durable_session_id == "dsid-abc"
        assert e.continuity_epoch == 3

    def test_to_dict_includes_durable_fields(self):
        from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
        e = AttachedSessionRegistryEntry(
            device_id="dev-001",
            durable_session_id="dsid-xyz",
            continuity_epoch=7,
        )
        d = e.to_dict()
        assert d["durable_session_id"] == "dsid-xyz"
        assert d["continuity_epoch"] == 7

    def test_from_dict_round_trips_durable_fields(self):
        from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
        e = AttachedSessionRegistryEntry(
            device_id="dev-001",
            durable_session_id="dsid-round",
            continuity_epoch=12,
        )
        restored = AttachedSessionRegistryEntry.from_dict(e.to_dict())
        assert restored.durable_session_id == "dsid-round"
        assert restored.continuity_epoch == 12

    def test_from_dict_missing_durable_fields_defaults_safe(self):
        from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
        d = {"device_id": "dev-001"}
        e = AttachedSessionRegistryEntry.from_dict(d)
        assert e.durable_session_id == ""
        assert e.continuity_epoch == 0


# ===========================================================================
# B — register_session stores durable continuity fields
# ===========================================================================

class TestRegisterSessionDurableFields:
    """register_session stores durable_session_id and continuity_epoch."""

    def setup_method(self):
        _reset()

    def test_durable_fields_stored_on_register(self):
        from core.attached_runtime_session_registry import register_session
        entry = register_session(
            "dev-001",
            durable_session_id="dsid-reg",
            continuity_epoch=5,
        )
        assert entry.durable_session_id == "dsid-reg"
        assert entry.continuity_epoch == 5

    def test_absent_durable_fields_default_safely(self):
        from core.attached_runtime_session_registry import register_session
        entry = register_session("dev-002")
        assert entry.durable_session_id == ""
        assert entry.continuity_epoch == 0

    def test_durable_fields_round_trip_via_to_dict(self):
        from core.attached_runtime_session_registry import (
            register_session,
            AttachedSessionRegistryEntry,
        )
        entry = register_session(
            "dev-003",
            durable_session_id="dsid-rt",
            continuity_epoch=9,
        )
        d = entry.to_dict()
        restored = AttachedSessionRegistryEntry.from_dict(d)
        assert restored.durable_session_id == "dsid-rt"
        assert restored.continuity_epoch == 9


# ===========================================================================
# C — reconnect_session preserves / updates durable continuity fields
# ===========================================================================

class TestReconnectSessionDurableFields:
    """reconnect_session preserves and updates durable continuity fields."""

    def setup_method(self):
        _reset()

    def test_reconnect_preserves_existing_durable_fields(self):
        from core.attached_runtime_session_registry import (
            register_session,
            reconnect_session,
            detach_session,
        )
        entry = register_session(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-orig",
            continuity_epoch=2,
        )
        detached = detach_session(entry)
        reconnected = reconnect_session(
            detached,
            runtime_attachment_session_id="att-1",
            # no new durable fields → preserve existing
        )
        assert reconnected.durable_session_id == "dsid-orig"
        assert reconnected.continuity_epoch == 2

    def test_reconnect_updates_durable_fields_when_supplied(self):
        from core.attached_runtime_session_registry import (
            register_session,
            reconnect_session,
            detach_session,
        )
        entry = register_session(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-v1",
            continuity_epoch=1,
        )
        detached = detach_session(entry)
        reconnected = reconnect_session(
            detached,
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-v2",
            continuity_epoch=2,
        )
        assert reconnected.durable_session_id == "dsid-v2"
        assert reconnected.continuity_epoch == 2

    def test_reconnect_preserves_runtime_session_id(self):
        """Core PR-G invariant: runtime_session_id preserved across reconnect."""
        from core.attached_runtime_session_registry import (
            register_session,
            reconnect_session,
            detach_session,
        )
        entry = register_session(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-orig",
        )
        orig_runtime_session_id = entry.runtime_session_id
        detached = detach_session(entry)
        reconnected = reconnect_session(
            detached,
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-orig",
        )
        assert reconnected.runtime_session_id == orig_runtime_session_id


# ===========================================================================
# D — classify_reconnect_outcome with durable_session_id
# ===========================================================================

class TestClassifyReconnectOutcomeDurableFields:
    """classify_reconnect_outcome validates durable_session_id (PR-C)."""

    def setup_method(self):
        _reset()

    def test_matching_durable_session_id_grants_continuity_resume(self):
        from core.attached_runtime_session_registry import (
            register_session,
            detach_session,
            classify_reconnect_outcome,
        )
        register_session(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-match",
            continuity_epoch=1,
        )
        outcome, entry = classify_reconnect_outcome(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-match",
        )
        assert outcome == "continuity_resume"
        assert entry is not None

    def test_mismatched_durable_session_id_yields_new_attachment(self):
        """Durable identity mismatch means different session era → new attachment."""
        from core.attached_runtime_session_registry import (
            register_session,
            classify_reconnect_outcome,
        )
        register_session(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-original",
            continuity_epoch=1,
        )
        outcome, entry = classify_reconnect_outcome(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-different",
        )
        assert outcome == "new_attachment"
        assert entry is None

    def test_absent_durable_session_id_in_client_is_non_constraining(self):
        """If the client doesn't send durable_session_id, continuity check passes."""
        from core.attached_runtime_session_registry import (
            register_session,
            classify_reconnect_outcome,
        )
        register_session(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-stored",
        )
        # Client sends no durable_session_id (older Android client or not configured)
        outcome, entry = classify_reconnect_outcome(
            "dev-001",
            runtime_attachment_session_id="att-1",
            # durable_session_id absent
        )
        assert outcome == "continuity_resume"
        assert entry is not None

    def test_absent_durable_session_id_in_registry_is_backward_compat(self):
        """Registry entry with no durable_session_id → client's value is ignored."""
        from core.attached_runtime_session_registry import (
            register_session,
            classify_reconnect_outcome,
        )
        register_session(
            "dev-001",
            runtime_attachment_session_id="att-1",
            # no durable_session_id stored
        )
        # Client sends a durable_session_id; registry has none → cannot mismatch
        outcome, entry = classify_reconnect_outcome(
            "dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-new",
        )
        assert outcome == "continuity_resume"
        assert entry is not None

    def test_no_existing_entry_always_new_attachment(self):
        """No prior entry → new_attachment regardless of durable fields."""
        from core.attached_runtime_session_registry import classify_reconnect_outcome
        outcome, entry = classify_reconnect_outcome(
            "dev-unknown",
            runtime_attachment_session_id="att-x",
            durable_session_id="dsid-x",
        )
        assert outcome == "new_attachment"
        assert entry is None

    def test_mismatched_attachment_id_yields_new_attachment_ignoring_durable(self):
        """Wrong runtime_attachment_session_id → new_attachment even if durable matches."""
        from core.attached_runtime_session_registry import (
            register_session,
            classify_reconnect_outcome,
        )
        register_session(
            "dev-001",
            runtime_attachment_session_id="att-correct",
            durable_session_id="dsid-match",
        )
        outcome, entry = classify_reconnect_outcome(
            "dev-001",
            runtime_attachment_session_id="att-wrong",
            durable_session_id="dsid-match",
        )
        assert outcome == "new_attachment"
        assert entry is None

    def test_lower_continuity_epoch_yields_new_attachment(self):
        """Older continuity epoch must not resume a newer stored session era."""
        from core.attached_runtime_session_registry import (
            register_session,
            classify_reconnect_outcome,
        )
        register_session(
            "dev-001",
            runtime_attachment_session_id="att-epoch",
            durable_session_id="dsid-epoch",
            continuity_epoch=8,
        )
        outcome, entry = classify_reconnect_outcome(
            "dev-001",
            runtime_attachment_session_id="att-epoch",
            durable_session_id="dsid-epoch",
            continuity_epoch=7,
        )
        assert outcome == "new_attachment"
        assert entry is None


# ===========================================================================
# E — ContinuityEventContext carries durable fields
# ===========================================================================

class TestContinuityEventContextDurableFields:
    """ContinuityEventContext carries durable_session_id and continuity_epoch."""

    def test_default_values(self):
        from core.flow_continuity_coordinator import ContinuityEventContext
        ctx = ContinuityEventContext()
        assert ctx.durable_session_id == ""
        assert ctx.continuity_epoch == 0

    def test_explicit_values_stored(self):
        from core.flow_continuity_coordinator import ContinuityEventContext
        ctx = ContinuityEventContext(
            durable_session_id="dsid-ctx",
            continuity_epoch=4,
        )
        assert ctx.durable_session_id == "dsid-ctx"
        assert ctx.continuity_epoch == 4

    def test_to_dict_includes_durable_fields(self):
        from core.flow_continuity_coordinator import ContinuityEventContext
        ctx = ContinuityEventContext(
            durable_session_id="dsid-dict",
            continuity_epoch=8,
        )
        d = ctx.to_dict()
        assert d["durable_session_id"] == "dsid-dict"
        assert d["continuity_epoch"] == 8


# ===========================================================================
# F — ContinuityDecisionArtifact carries durable fields
# ===========================================================================

class TestContinuityDecisionArtifactDurableFields:
    """ContinuityDecisionArtifact carries and round-trips durable fields."""

    def test_default_values(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact
        a = ContinuityDecisionArtifact()
        assert a.durable_session_id == ""
        assert a.continuity_epoch == 0

    def test_explicit_values_stored(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact
        a = ContinuityDecisionArtifact(
            durable_session_id="dsid-art",
            continuity_epoch=6,
        )
        assert a.durable_session_id == "dsid-art"
        assert a.continuity_epoch == 6

    def test_to_dict_includes_durable_fields(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact
        a = ContinuityDecisionArtifact(
            durable_session_id="dsid-d",
            continuity_epoch=11,
        )
        d = a.to_dict()
        assert d["durable_session_id"] == "dsid-d"
        assert d["continuity_epoch"] == 11

    def test_from_dict_round_trips_durable_fields(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact
        a = ContinuityDecisionArtifact(
            durable_session_id="dsid-rt",
            continuity_epoch=13,
        )
        restored = ContinuityDecisionArtifact.from_dict(a.to_dict())
        assert restored.durable_session_id == "dsid-rt"
        assert restored.continuity_epoch == 13

    def test_from_dict_missing_durable_fields_defaults_safe(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact
        a = ContinuityDecisionArtifact.from_dict({})
        assert a.durable_session_id == ""
        assert a.continuity_epoch == 0


# ===========================================================================
# G — FlowContinuityCoordinator.decide_reconnect propagates durable fields
# ===========================================================================

class TestFlowContinuityCoordinatorDurableFields:
    """decide_reconnect propagates durable_session_id and continuity_epoch."""

    def setup_method(self):
        _reset()

    def _make_coordinator_with_mock(self, classify_return: str, capture: dict = None):
        from core.flow_continuity_coordinator import FlowContinuityCoordinator

        class _MockRegistry:
            pass

        def _mock_classify(device_id, *, runtime_attachment_session_id="",
                           durable_session_id="", registry=None, **kwargs):
            if capture is not None:
                capture["device_id"] = device_id
                capture["runtime_attachment_session_id"] = runtime_attachment_session_id
                capture["durable_session_id"] = durable_session_id
            return classify_return

        c = FlowContinuityCoordinator()
        c._classify_reconnect_outcome = _mock_classify
        c._get_session_registry = lambda: _MockRegistry()
        return c

    def test_durable_fields_propagated_to_artifact_on_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        captured: dict = {}
        c = self._make_coordinator_with_mock("continuity_resume", captured)
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-001",
            runtime_attachment_session_id="att-1",
            durable_session_id="dsid-flow",
            continuity_epoch=7,
        )
        artifact = c.decide_reconnect(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume
        # durable fields propagated into artifact
        assert artifact.durable_session_id == "dsid-flow"
        assert artifact.continuity_epoch == 7
        # durable_session_id was passed to classify_fn
        assert captured.get("durable_session_id") == "dsid-flow"

    def test_mismatched_durable_id_produces_new_attachment(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock("new_attachment")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-002",
            runtime_attachment_session_id="att-2",
            durable_session_id="dsid-wrong",
        )
        artifact = c.decide_reconnect(ctx)
        assert artifact.decision == ContinuityDecision.new_attachment

    def test_no_durable_fields_still_resumes_via_attachment_id(self):
        """Existing PR-G path not broken: attachment ID alone still resumes."""
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock("continuity_resume")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-003",
            runtime_attachment_session_id="att-3",
            # no durable fields
        )
        artifact = c.decide_reconnect(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume

    def test_durable_session_id_passed_to_classify_fn(self):
        """classify_fn receives durable_session_id from ctx."""
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        captured: dict = {}
        c = self._make_coordinator_with_mock("new_attachment", captured)
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-004",
            runtime_attachment_session_id="att-4",
            durable_session_id="dsid-captured",
            continuity_epoch=3,
        )
        c.decide_reconnect(ctx)
        assert captured.get("durable_session_id") == "dsid-captured"

    def test_registry_tuple_outcome_is_supported(self):
        """Real classify_reconnect_outcome returns (outcome, entry) tuple."""
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )

        class _Entry:
            durable_session_id = "dsid-registry"
            continuity_epoch = 9

        c = self._make_coordinator_with_mock(("continuity_resume", _Entry()))
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-005",
            runtime_attachment_session_id="att-5",
        )
        artifact = c.decide_reconnect(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume
        assert artifact.durable_session_id == "dsid-registry"
        assert artifact.continuity_epoch == 9


# ===========================================================================
# H — _extract_durable_continuity_fields helper
# ===========================================================================

class TestExtractDurableContinuityFields:
    """_extract_durable_continuity_fields extracts Android continuity fields."""

    def test_extracts_present_fields(self):
        from galaxy_gateway.android.handlers.registration import (
            _extract_durable_continuity_fields,
        )
        msg = {
            "durable_session_id": "dsid-extract",
            "session_continuity_epoch": 5,
        }
        dsid, epoch = _extract_durable_continuity_fields(msg)
        assert dsid == "dsid-extract"
        assert epoch == 5

    def test_absent_fields_return_defaults(self):
        from galaxy_gateway.android.handlers.registration import (
            _extract_durable_continuity_fields,
        )
        dsid, epoch = _extract_durable_continuity_fields({})
        assert dsid == ""
        assert epoch == 0

    def test_none_durable_session_id_treated_as_empty(self):
        from galaxy_gateway.android.handlers.registration import (
            _extract_durable_continuity_fields,
        )
        dsid, epoch = _extract_durable_continuity_fields(
            {"durable_session_id": None, "session_continuity_epoch": 3}
        )
        assert dsid == ""
        assert epoch == 3

    def test_non_numeric_epoch_defaults_to_zero(self):
        from galaxy_gateway.android.handlers.registration import (
            _extract_durable_continuity_fields,
        )
        dsid, epoch = _extract_durable_continuity_fields(
            {"durable_session_id": "dsid-x", "session_continuity_epoch": "not-a-number"}
        )
        assert dsid == "dsid-x"
        assert epoch == 0

    def test_string_numeric_epoch_parsed_correctly(self):
        from galaxy_gateway.android.handlers.registration import (
            _extract_durable_continuity_fields,
        )
        dsid, epoch = _extract_durable_continuity_fields(
            {"durable_session_id": "dsid-y", "session_continuity_epoch": "7"}
        )
        assert dsid == "dsid-y"
        assert epoch == 7


# ===========================================================================
# I — End-to-end: reconnect preserves session era via durable identity
# ===========================================================================

class TestDurableContinuityEndToEnd:
    """End-to-end: Android supplies valid durable identity → continuity preserved."""

    def setup_method(self):
        _reset()

    def test_fresh_registration_followed_by_continuity_resume(self):
        """Full cycle: register → detach → reconnect with durable ID → resume."""
        from core.attached_runtime_session_registry import (
            register_session,
            detach_session,
            reconnect_session,
            classify_reconnect_outcome,
        )

        # First registration (Android first connect)
        entry = register_session(
            "dev-e2e",
            runtime_attachment_session_id="att-e2e",
            durable_session_id="dsid-e2e",
            continuity_epoch=1,
        )
        original_runtime_session_id = entry.runtime_session_id

        # Simulated disconnect
        detached = detach_session(entry)

        # Android reconnects with same durable identity
        outcome, existing = classify_reconnect_outcome(
            "dev-e2e",
            runtime_attachment_session_id="att-e2e",
            durable_session_id="dsid-e2e",
        )
        assert outcome == "continuity_resume"
        assert existing is not None

        reconnected = reconnect_session(
            existing,
            runtime_attachment_session_id="att-e2e",
            durable_session_id="dsid-e2e",
            continuity_epoch=2,
        )

        # runtime_session_id preserved (PR-G invariant)
        assert reconnected.runtime_session_id == original_runtime_session_id
        # Durable fields updated
        assert reconnected.durable_session_id == "dsid-e2e"
        assert reconnected.continuity_epoch == 2
        # Session is active again
        assert reconnected.attachment_state.value == "active"
        # Reconnect counter incremented
        assert reconnected.reconnect_count == 1

    def test_stale_era_cold_restart_triggers_new_attachment(self):
        """Cold restart with different durable_session_id → new session era."""
        from core.attached_runtime_session_registry import (
            register_session,
            classify_reconnect_outcome,
        )

        register_session(
            "dev-stale",
            runtime_attachment_session_id="att-stale",
            durable_session_id="dsid-era-1",
            continuity_epoch=5,
        )

        # Android cold-restarted with a new durable_session_id
        outcome, entry = classify_reconnect_outcome(
            "dev-stale",
            runtime_attachment_session_id="att-stale",
            durable_session_id="dsid-era-2",
        )
        assert outcome == "new_attachment"
        assert entry is None

    def test_no_durable_fields_at_all_backward_compat(self):
        """Backward compat: older Android client sends no durable fields → still works."""
        from core.attached_runtime_session_registry import (
            register_session,
            classify_reconnect_outcome,
        )

        register_session(
            "dev-old",
            runtime_attachment_session_id="att-old",
        )

        outcome, entry = classify_reconnect_outcome(
            "dev-old",
            runtime_attachment_session_id="att-old",
        )
        assert outcome == "continuity_resume"
        assert entry is not None
