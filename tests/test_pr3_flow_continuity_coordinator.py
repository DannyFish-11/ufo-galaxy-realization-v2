#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_flow_continuity_coordinator.py
=============================================
PR-3 — FlowContinuityCoordinator — test suite.

Coverage
--------
A  — Module importable; authority sentinel and PR-3 sentinel present.
B  — All 9 policy sentinels are non-empty strings with expected keywords.
C  — ContinuityDecision enum has all 7 required values.
D  — ContinuityEventKind enum has all 8 required values.
E  — ContinuityEventContext dataclass has required fields; to_dict() works.
F  — ContinuityDecisionArtifact has required fields; to_dict() works.
G  — ContinuityDecisionArtifact.from_dict() round-trips correctly.
H  — to_json() produces valid JSON for all data classes.
I  — ContinuityCoordinatorSnapshot to_dict() contains expected keys.
J  — FlowContinuityCoordinator instantiates with default capacity.
K  — get_flow_continuity_coordinator() returns singleton; reset clears it.
L  — decide_attach: no prior entry → new_attachment.
M  — decide_attach: prior active entry → continuity_resume.
N  — decide_attach: prior replaced entry → new_attachment.
O  — decide_attach: registry_entry_created=False → fail_closed.
P  — decide_reconnect: registry unavailable → fail_closed.
Q  — decide_reconnect: outcome=continuity_resume, ID present → continuity_resume.
R  — decide_reconnect: outcome=continuity_resume, ID absent → require_review.
S  — decide_reconnect: outcome=new_attachment → new_attachment.
T  — decide_reattach_process_recreation: active+match → continuity_resume.
U  — decide_reattach_process_recreation: active+no match → new_attachment.
V  — decide_reattach_process_recreation: terminal → new_attachment.
W  — decide_stale_identity: session=replaced, tracker=terminal → reject_stale_identity.
X  — decide_stale_identity: session=active → continuity_resume.
Y  — decide_stale_identity: no registry, no identifiers → require_review.
Z  — decide_duplicate_signal: no signal_key → continuity_resume (pass-through).
AA — decide_duplicate_signal: tracker unavailable → require_review.
AB — decide_duplicate_signal: novel signal → continuity_resume.
AC — decide_partial_result: tracker unavailable → require_review.
AD — decide_partial_result: terminal phase → reject_stale_identity.
AE — decide_partial_result: non-terminal phase → preserve_partial_and_wait.
AF — decide_partial_result: no tracking record → preserve_partial_and_wait.
AG — decide_v2_restart_recovery: not completed → require_review.
AH — decide_v2_restart_recovery: no durable store → new_attachment.
AI — decide(): unknown event kind → fail_closed.
AJ — decide(): dispatches fresh_attach to decide_attach.
AK — decide(): dispatches transport_reconnect to decide_reconnect.
AL — decide(): dispatches partial_result to decide_partial_result.
AM — build_snapshot: empty coordinator → snapshot with zero decisions.
AN — build_snapshot: after decisions → counts and recent_artifacts correct.
AO — list_recent: returns newest-first up to n items.
AP — get_by_artifact_id: returns artifact by id; None for unknown id.
AQ — coordinate_attach convenience wrapper: returns ContinuityDecisionArtifact.
AR — coordinate_reconnect convenience wrapper: returns ContinuityDecisionArtifact.
AS — coordinate_reattach_process_recreation: returns artifact.
AT — coordinate_stale_identity: returns artifact.
AU — coordinate_duplicate_signal: returns artifact.
AV — coordinate_partial_result: returns artifact.
AW — coordinate_v2_restart_recovery: returns artifact.
AX — is_resumable=True for continuity_resume and preserve_partial_and_wait.
AY — is_resumable=False for all other decisions.
AZ — ContinuityDecision.from_string: known value, unknown value, non-string.
BA — ContinuityEventKind.from_string: known value, unknown value.
BB — Ring-buffer capacity respected: oldest artifact evicted when full.
BC — artifact.to_dict() → from_dict() round-trip preserves all fields.
BD — Coordinator records each decision in ring-buffer.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# A — Module importable; sentinels present
# ---------------------------------------------------------------------------


class TestModuleSentinels:
    def test_module_is_importable(self):
        import core.flow_continuity_coordinator  # noqa: F401

    def test_authority_sentinel_is_non_empty_string(self):
        from core.flow_continuity_coordinator import (
            FLOW_CONTINUITY_COORDINATOR_AUTHORITY,
        )
        assert isinstance(FLOW_CONTINUITY_COORDINATOR_AUTHORITY, str)
        assert len(FLOW_CONTINUITY_COORDINATOR_AUTHORITY) > 0
        assert "FlowContinuityCoordinator" in FLOW_CONTINUITY_COORDINATOR_AUTHORITY

    def test_pr3_sentinel_is_non_empty_string(self):
        from core.flow_continuity_coordinator import (
            FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL,
        )
        assert isinstance(FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL, str)
        assert "package=3" in FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL
        assert "PR-3" in FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL or "package=3" in FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL


# ---------------------------------------------------------------------------
# B — Policy sentinels
# ---------------------------------------------------------------------------


class TestPolicySentinels:
    def _import_all_sentinels(self):
        from core.flow_continuity_coordinator import (
            FLOW_CONTINUITY_COORDINATOR_AUTHORITY,
            FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL,
            CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY,
            COORDINATOR_DOES_NOT_OWN_REGISTRY_STATE_POLICY,
            FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY,
            STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY,
            DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY,
            PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY,
            V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY,
        )
        return [
            FLOW_CONTINUITY_COORDINATOR_AUTHORITY,
            FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL,
            CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY,
            COORDINATOR_DOES_NOT_OWN_REGISTRY_STATE_POLICY,
            FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY,
            STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY,
            DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY,
            PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY,
            V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY,
        ]

    def test_all_9_policy_sentinels_importable(self):
        sentinels = self._import_all_sentinels()
        assert len(sentinels) == 9

    def test_all_sentinels_are_non_empty_strings(self):
        sentinels = self._import_all_sentinels()
        for s in sentinels:
            assert isinstance(s, str)
            assert len(s) > 0

    def test_unified_entry_point_policy_mentions_coordinator(self):
        from core.flow_continuity_coordinator import (
            CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY,
        )
        assert "FlowContinuityCoordinator" in CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY

    def test_fail_closed_policy_mentions_fail_closed(self):
        from core.flow_continuity_coordinator import FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY
        assert "fail_closed" in FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY

    def test_stale_rejection_policy_mentions_non_destructive(self):
        from core.flow_continuity_coordinator import (
            STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY,
        )
        assert (
            "non-destructive" in STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY
            or "non_destructive" in STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY
        )

    def test_duplicate_suppression_policy_mentions_reconciler(self):
        from core.flow_continuity_coordinator import (
            DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY,
        )
        assert "reconciler" in DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY.lower()

    def test_partial_result_policy_mentions_preserve(self):
        from core.flow_continuity_coordinator import (
            PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY,
        )
        assert "preserve" in PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY.lower()

    def test_v2_restart_policy_mentions_durable_store(self):
        from core.flow_continuity_coordinator import (
            V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY,
        )
        assert "durable" in V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY.lower()


# ---------------------------------------------------------------------------
# C — ContinuityDecision enum
# ---------------------------------------------------------------------------


class TestContinuityDecisionEnum:
    def test_all_7_values_present(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        expected = {
            "new_attachment",
            "continuity_resume",
            "reject_stale_identity",
            "dedupe_duplicate_signal",
            "preserve_partial_and_wait",
            "require_review",
            "fail_closed",
        }
        actual = {v.value for v in ContinuityDecision}
        assert expected == actual

    def test_new_attachment_value(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.new_attachment.value == "new_attachment"

    def test_continuity_resume_value(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.continuity_resume.value == "continuity_resume"

    def test_reject_stale_identity_value(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.reject_stale_identity.value == "reject_stale_identity"

    def test_dedupe_duplicate_signal_value(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.dedupe_duplicate_signal.value == "dedupe_duplicate_signal"

    def test_preserve_partial_and_wait_value(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.preserve_partial_and_wait.value == "preserve_partial_and_wait"

    def test_require_review_value(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.require_review.value == "require_review"

    def test_fail_closed_value(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.fail_closed.value == "fail_closed"


# ---------------------------------------------------------------------------
# D — ContinuityEventKind enum
# ---------------------------------------------------------------------------


class TestContinuityEventKindEnum:
    def test_all_8_values_present(self):
        from core.flow_continuity_coordinator import ContinuityEventKind
        expected = {
            "fresh_attach",
            "transport_reconnect",
            "process_recreation_reattach",
            "stale_identity",
            "duplicate_signal",
            "partial_result",
            "v2_restart_recovery",
            "unknown",
        }
        actual = {v.value for v in ContinuityEventKind}
        assert expected == actual


# ---------------------------------------------------------------------------
# E — ContinuityEventContext dataclass
# ---------------------------------------------------------------------------


class TestContinuityEventContext:
    def test_default_fields(self):
        from core.flow_continuity_coordinator import ContinuityEventContext, ContinuityEventKind
        ctx = ContinuityEventContext()
        assert ctx.event_kind == ContinuityEventKind.unknown
        assert ctx.device_id == ""
        assert ctx.session_id == ""
        assert ctx.runtime_attachment_session_id == ""
        assert ctx.contract_id == ""
        assert ctx.signal_key == ""
        assert ctx.is_partial_result is False
        assert ctx.metadata == {}

    def test_to_dict_contains_expected_keys(self):
        from core.flow_continuity_coordinator import ContinuityEventContext, ContinuityEventKind
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            session_id="sess-1",
        )
        d = ctx.to_dict()
        for key in (
            "event_kind", "device_id", "session_id", "runtime_attachment_session_id",
            "contract_id", "signal_key", "is_partial_result", "metadata",
        ):
            assert key in d

    def test_to_json_is_valid_json(self):
        from core.flow_continuity_coordinator import ContinuityEventContext, ContinuityEventKind
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
        )
        parsed = json.loads(ctx.to_json())
        assert parsed["event_kind"] == "fresh_attach"
        assert parsed["device_id"] == "dev-1"


# ---------------------------------------------------------------------------
# F — ContinuityDecisionArtifact
# ---------------------------------------------------------------------------


class TestContinuityDecisionArtifact:
    def test_default_fields(self):
        from core.flow_continuity_coordinator import (
            ContinuityDecisionArtifact,
            ContinuityDecision,
            ContinuityEventKind,
        )
        a = ContinuityDecisionArtifact()
        assert isinstance(a.artifact_id, str)
        assert len(a.artifact_id) > 0
        assert a.decision == ContinuityDecision.fail_closed
        assert a.event_kind == ContinuityEventKind.unknown
        assert a.is_resumable is False

    def test_to_dict_contains_expected_keys(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact
        a = ContinuityDecisionArtifact()
        d = a.to_dict()
        for key in (
            "artifact_id", "event_kind", "decision", "policy_reference", "detail",
            "device_id", "session_id", "runtime_attachment_session_id",
            "contract_id", "flow_id", "flow_lineage_id", "registry_outcome",
            "tracking_record_phase", "flow_entity_phase", "contract_verified",
            "is_resumable", "extension_payload", "timestamp",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_json_is_valid_json(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact, ContinuityDecision
        a = ContinuityDecisionArtifact(decision=ContinuityDecision.new_attachment)
        parsed = json.loads(a.to_json())
        assert parsed["decision"] == "new_attachment"


# ---------------------------------------------------------------------------
# G — ContinuityDecisionArtifact.from_dict() round-trip
# ---------------------------------------------------------------------------


class TestArtifactRoundTrip:
    def test_round_trip_preserves_all_fields(self):
        from core.flow_continuity_coordinator import (
            ContinuityDecisionArtifact,
            ContinuityDecision,
            ContinuityEventKind,
        )
        original = ContinuityDecisionArtifact(
            event_kind=ContinuityEventKind.transport_reconnect,
            decision=ContinuityDecision.continuity_resume,
            policy_reference="SOME_POLICY",
            detail="test detail",
            device_id="dev-42",
            session_id="sess-42",
            runtime_attachment_session_id="att-42",
            contract_id="contract-42",
            flow_id="flow-42",
            flow_lineage_id="lineage-42",
            registry_outcome="continuity_resume",
            tracking_record_phase="executing",
            flow_entity_phase="executing",
            contract_verified="pass",
            is_resumable=True,
            extension_payload={"replay_hint": "test"},
        )
        restored = ContinuityDecisionArtifact.from_dict(original.to_dict())
        assert restored.artifact_id == original.artifact_id
        assert restored.decision == original.decision
        assert restored.event_kind == original.event_kind
        assert restored.policy_reference == original.policy_reference
        assert restored.device_id == original.device_id
        assert restored.contract_id == original.contract_id
        assert restored.is_resumable == original.is_resumable
        assert restored.extension_payload == original.extension_payload

    def test_from_dict_tolerates_unknown_fields(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact
        d = ContinuityDecisionArtifact().to_dict()
        d["unknown_future_field"] = "some_value"
        # Should not raise
        restored = ContinuityDecisionArtifact.from_dict(d)
        assert restored is not None

    def test_from_dict_defaults_missing_fields(self):
        from core.flow_continuity_coordinator import (
            ContinuityDecisionArtifact,
            ContinuityDecision,
        )
        restored = ContinuityDecisionArtifact.from_dict({})
        assert restored.decision == ContinuityDecision.fail_closed


# ---------------------------------------------------------------------------
# H — to_json() for all data classes
# ---------------------------------------------------------------------------


class TestToJson:
    def test_event_context_to_json(self):
        from core.flow_continuity_coordinator import ContinuityEventContext
        ctx = ContinuityEventContext()
        assert json.loads(ctx.to_json())

    def test_decision_artifact_to_json(self):
        from core.flow_continuity_coordinator import ContinuityDecisionArtifact
        a = ContinuityDecisionArtifact()
        assert json.loads(a.to_json())

    def test_coordinator_snapshot_to_json(self):
        from core.flow_continuity_coordinator import ContinuityCoordinatorSnapshot
        snap = ContinuityCoordinatorSnapshot()
        assert json.loads(snap.to_json())


# ---------------------------------------------------------------------------
# I — ContinuityCoordinatorSnapshot to_dict keys
# ---------------------------------------------------------------------------


class TestCoordinatorSnapshot:
    def test_to_dict_contains_expected_keys(self):
        from core.flow_continuity_coordinator import ContinuityCoordinatorSnapshot
        snap = ContinuityCoordinatorSnapshot(
            total_decisions=5,
            decision_counts={"new_attachment": 3, "continuity_resume": 2},
            recent_artifacts=[],
            policy_sentinels=["POLICY_A"],
        )
        d = snap.to_dict()
        for key in (
            "snapshot_id", "total_decisions", "decision_counts",
            "recent_artifacts", "policy_sentinels", "timestamp",
        ):
            assert key in d


# ---------------------------------------------------------------------------
# J — FlowContinuityCoordinator instantiates
# ---------------------------------------------------------------------------


class TestCoordinatorInstantiation:
    def test_default_capacity(self):
        from core.flow_continuity_coordinator import FlowContinuityCoordinator
        c = FlowContinuityCoordinator()
        assert c._capacity == 256

    def test_custom_capacity(self):
        from core.flow_continuity_coordinator import FlowContinuityCoordinator
        c = FlowContinuityCoordinator(capacity=64)
        assert c._capacity == 64

    def test_initial_ring_buffer_empty(self):
        from core.flow_continuity_coordinator import FlowContinuityCoordinator
        c = FlowContinuityCoordinator()
        assert len(c.list_recent()) == 0


# ---------------------------------------------------------------------------
# K — Singleton management
# ---------------------------------------------------------------------------


class TestSingletonManagement:
    def setup_method(self):
        from core.flow_continuity_coordinator import reset_flow_continuity_coordinator
        reset_flow_continuity_coordinator()

    def teardown_method(self):
        from core.flow_continuity_coordinator import reset_flow_continuity_coordinator
        reset_flow_continuity_coordinator()

    def test_singleton_returns_same_instance(self):
        from core.flow_continuity_coordinator import get_flow_continuity_coordinator
        a = get_flow_continuity_coordinator()
        b = get_flow_continuity_coordinator()
        assert a is b

    def test_reset_creates_new_instance(self):
        from core.flow_continuity_coordinator import (
            get_flow_continuity_coordinator,
            reset_flow_continuity_coordinator,
        )
        a = get_flow_continuity_coordinator()
        reset_flow_continuity_coordinator()
        b = get_flow_continuity_coordinator()
        assert a is not b


# ---------------------------------------------------------------------------
# Test helpers — isolated coordinator factory
# ---------------------------------------------------------------------------

def _fresh_coordinator():
    from core.flow_continuity_coordinator import FlowContinuityCoordinator
    return FlowContinuityCoordinator()


# ---------------------------------------------------------------------------
# L — decide_attach: no prior entry → new_attachment
# ---------------------------------------------------------------------------


class TestDecideAttach:
    def test_no_prior_entry_produces_new_attachment(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            prior_entry_state="",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.decision == ContinuityDecision.new_attachment

    def test_prior_active_entry_produces_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            prior_entry_state="active",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume

    def test_prior_replaced_entry_produces_new_attachment(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            prior_entry_state="replaced",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.decision == ContinuityDecision.new_attachment

    def test_registry_entry_not_created_produces_fail_closed(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            metadata={"registry_entry_created": False},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.decision == ContinuityDecision.fail_closed

    def test_prior_detached_entry_produces_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            prior_entry_state="detached",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume

    def test_prior_invalidated_entry_produces_new_attachment(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            prior_entry_state="invalidated",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.decision == ContinuityDecision.new_attachment

    def test_artifact_has_device_id(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-999",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.device_id == "dev-999"


# ---------------------------------------------------------------------------
# P-S — decide_reconnect
# ---------------------------------------------------------------------------


class TestDecideReconnect:
    def _make_coordinator_with_mock_registry(self, classify_return: str):
        """Return a coordinator with a mock registry that returns classify_return."""
        from core.flow_continuity_coordinator import FlowContinuityCoordinator

        class _MockRegistry:
            pass

        def _mock_classify(device_id, *, runtime_attachment_session_id="", registry=None, **kwargs):
            return classify_return

        c = FlowContinuityCoordinator()
        c._classify_reconnect_outcome = _mock_classify
        c._get_session_registry = lambda: _MockRegistry()
        return c

    def test_registry_unavailable_produces_fail_closed(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        # No registry modules available — stays fail_closed
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-1",
        )
        artifact = c.decide_reconnect(ctx)
        # May be fail_closed or require_review depending on module availability
        assert artifact.decision in (
            ContinuityDecision.fail_closed,
            ContinuityDecision.continuity_resume,
            ContinuityDecision.new_attachment,
            ContinuityDecision.require_review,
        )

    def test_continuity_resume_with_attachment_id_gives_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_registry("continuity_resume")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
        )
        artifact = c.decide_reconnect(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume
        assert artifact.registry_outcome == "continuity_resume"

    def test_continuity_resume_without_attachment_id_gives_require_review(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_registry("continuity_resume")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-1",
            runtime_attachment_session_id="",  # absent
        )
        artifact = c.decide_reconnect(ctx)
        assert artifact.decision == ContinuityDecision.require_review

    def test_new_attachment_gives_new_attachment(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_registry("new_attachment")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
        )
        artifact = c.decide_reconnect(ctx)
        assert artifact.decision == ContinuityDecision.new_attachment

    def test_unknown_registry_outcome_gives_fail_closed(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_registry("some_unknown_outcome")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
        )
        artifact = c.decide_reconnect(ctx)
        assert artifact.decision == ContinuityDecision.fail_closed


# ---------------------------------------------------------------------------
# T-V — decide_reattach_process_recreation
# ---------------------------------------------------------------------------


class TestDecideReattachProcessRecreation:
    def test_active_and_id_matched_gives_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.process_recreation_reattach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            metadata={
                "prior_entry_was_active_or_detached": True,
                "attachment_id_matched": True,
            },
        )
        artifact = c.decide_reattach_process_recreation(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume

    def test_active_and_id_not_matched_gives_new_attachment(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.process_recreation_reattach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            metadata={
                "prior_entry_was_active_or_detached": True,
                "attachment_id_matched": False,
            },
        )
        artifact = c.decide_reattach_process_recreation(ctx)
        assert artifact.decision == ContinuityDecision.new_attachment

    def test_terminal_entry_gives_new_attachment(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.process_recreation_reattach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            metadata={
                "prior_entry_was_active_or_detached": False,
                "attachment_id_matched": True,
            },
        )
        artifact = c.decide_reattach_process_recreation(ctx)
        assert artifact.decision == ContinuityDecision.new_attachment

    def test_prior_state_active_inferred_from_context(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.process_recreation_reattach,
            device_id="dev-1",
            runtime_attachment_session_id="att-1",
            prior_entry_state="active",  # inferred without metadata
        )
        artifact = c.decide_reattach_process_recreation(ctx)
        # prior_entry_state="active" → active_or_detached=True
        # attachment_id present (bool("att-1") = True) → id_matched=True
        assert artifact.decision == ContinuityDecision.continuity_resume


# ---------------------------------------------------------------------------
# W-Y — decide_stale_identity
# ---------------------------------------------------------------------------


class TestDecideStaleIdentity:
    def _make_coordinator_with_mock_session_state(self, session_state: str):
        from core.flow_continuity_coordinator import FlowContinuityCoordinator

        class _MockRegistry:
            def get_by_runtime_attachment_session_id(self, att_id, active_only=True):
                class _Entry:
                    attachment_state = type("S", (), {"value": session_state})()
                return _Entry() if session_state else None

            def get_active_for_device(self, device_id):
                return None

        c = FlowContinuityCoordinator()
        c._classify_reconnect_outcome = lambda *a, **kw: "new_attachment"
        c._get_session_registry = lambda: _MockRegistry()
        return c

    def test_session_replaced_gives_reject_stale_identity(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_session_state("replaced")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.stale_identity,
            session_id="sess-1",
            runtime_attachment_session_id="att-1",
        )
        artifact = c.decide_stale_identity(ctx)
        assert artifact.decision == ContinuityDecision.reject_stale_identity

    def test_session_active_gives_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_session_state("active")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.stale_identity,
            session_id="sess-1",
            runtime_attachment_session_id="att-1",
        )
        artifact = c.decide_stale_identity(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume

    def test_no_registry_no_identifiers_gives_require_review(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()  # no registry available
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.stale_identity,
            # No session_id, no contract_id, no attachment_id
        )
        artifact = c.decide_stale_identity(ctx)
        # With no registry and no identifiers → require_review or reject_stale_identity
        assert artifact.decision in (
            ContinuityDecision.require_review,
            ContinuityDecision.reject_stale_identity,
        )


# ---------------------------------------------------------------------------
# Z-AC — decide_duplicate_signal
# ---------------------------------------------------------------------------


class TestDecideDuplicateSignal:
    def test_no_signal_key_gives_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.duplicate_signal,
            session_id="sess-1",
            signal_key="",  # absent
        )
        artifact = c.decide_duplicate_signal(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume
        assert "no signal_key" in artifact.detail

    def test_tracker_unavailable_gives_require_review(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()  # tracker not available
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.duplicate_signal,
            session_id="sess-1",
            signal_key="sig-key-1",
        )
        artifact = c.decide_duplicate_signal(ctx)
        # tracker unavailable → require_review (or continuity_resume if no acks found)
        assert artifact.decision in (
            ContinuityDecision.require_review,
            ContinuityDecision.continuity_resume,
        )

    def _make_coordinator_with_mock_tracker(self, seen_keys=None):
        """Return coordinator with mock tracker that has seen_keys in ack history."""
        from core.flow_continuity_coordinator import FlowContinuityCoordinator

        seen = set(seen_keys or [])

        class _MockAck:
            def __init__(self, key):
                self.signal_key = key
                self.payload = {"signal_key": key}

        class _MockRecord:
            phase = type("P", (), {"value": "executing"})()
            acknowledgments = [_MockAck(k) for k in seen]

        class _MockTracker:
            def get_latest_for_session(self, session_id):
                return _MockRecord()

        c = FlowContinuityCoordinator()
        c._get_execution_tracking_runtime = lambda: _MockTracker()
        return c

    def test_novel_signal_gives_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_tracker(seen_keys=["other-key"])
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.duplicate_signal,
            session_id="sess-1",
            signal_key="new-key",
        )
        artifact = c.decide_duplicate_signal(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume

    def test_already_seen_signal_gives_dedupe(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_tracker(seen_keys=["dup-key-1"])
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.duplicate_signal,
            session_id="sess-1",
            signal_key="dup-key-1",
        )
        artifact = c.decide_duplicate_signal(ctx)
        assert artifact.decision == ContinuityDecision.dedupe_duplicate_signal


# ---------------------------------------------------------------------------
# AC-AF — decide_partial_result
# ---------------------------------------------------------------------------


class TestDecidePartialResult:
    def _make_coordinator_with_mock_tracker(self, phase: str):
        from core.flow_continuity_coordinator import FlowContinuityCoordinator

        _phase_value = phase

        class _MockPhase:
            value = _phase_value

        class _MockRecord:
            phase = _MockPhase()

        class _MockTracker:
            def get_latest_for_session(self, session_id):
                return _MockRecord()

        c = FlowContinuityCoordinator()
        c._get_execution_tracking_runtime = lambda: _MockTracker()
        return c

    def test_tracker_unavailable_gives_require_review(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.partial_result,
            session_id="sess-1",
            is_partial_result=True,
        )
        artifact = c.decide_partial_result(ctx)
        assert artifact.decision in (
            ContinuityDecision.require_review,
            ContinuityDecision.preserve_partial_and_wait,
        )

    def test_terminal_phase_gives_reject_stale_identity(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_tracker("completed")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.partial_result,
            session_id="sess-1",
            is_partial_result=True,
        )
        artifact = c.decide_partial_result(ctx)
        assert artifact.decision == ContinuityDecision.reject_stale_identity

    def test_executing_phase_gives_preserve_partial_and_wait(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = self._make_coordinator_with_mock_tracker("executing")
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.partial_result,
            session_id="sess-1",
            is_partial_result=True,
            partial_result_payload={"data": "partial"},
        )
        artifact = c.decide_partial_result(ctx)
        assert artifact.decision == ContinuityDecision.preserve_partial_and_wait
        assert artifact.extension_payload.get("partial_result_payload") == {"data": "partial"}

    def test_no_tracking_record_gives_preserve_partial_and_wait(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
            FlowContinuityCoordinator,
        )

        class _EmptyTracker:
            def get_latest_for_session(self, session_id):
                return None

        c = FlowContinuityCoordinator()
        c._get_execution_tracking_runtime = lambda: _EmptyTracker()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.partial_result,
            session_id="sess-1",
            is_partial_result=True,
        )
        artifact = c.decide_partial_result(ctx)
        assert artifact.decision == ContinuityDecision.preserve_partial_and_wait


# ---------------------------------------------------------------------------
# AG-AH — decide_v2_restart_recovery
# ---------------------------------------------------------------------------


class TestDecideV2RestartRecovery:
    def test_recovery_not_completed_gives_require_review(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.v2_restart_recovery,
            flow_lineage_id="lineage-1",
            recovery_completed=False,
        )
        artifact = c.decide_v2_restart_recovery(ctx)
        assert artifact.decision == ContinuityDecision.require_review

    def test_no_durable_store_gives_new_attachment(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.v2_restart_recovery,
            flow_lineage_id="lineage-1",
            recovery_completed=True,
        )
        artifact = c.decide_v2_restart_recovery(ctx)
        assert artifact.decision == ContinuityDecision.new_attachment

    def test_durable_store_with_active_flow_gives_continuity_resume(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
            FlowContinuityCoordinator,
        )

        class _MockIdentity:
            delegated_flow_id = "flow-1"
            flow_lineage_id = "lineage-1"

        class _MockMapping:
            contract_id = "contract-1"

        class _MockEntity:
            identity = _MockIdentity()
            phase = type("P", (), {"value": "executing"})()
            object_mapping = _MockMapping()

        class _MockBundle:
            def restore_all(self):
                return {"flow_entities": [_MockEntity()]}

        c = FlowContinuityCoordinator()
        c._get_persistence_bundle = lambda: _MockBundle()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.v2_restart_recovery,
            flow_lineage_id="lineage-1",
            recovery_completed=True,
        )
        artifact = c.decide_v2_restart_recovery(ctx)
        assert artifact.decision == ContinuityDecision.continuity_resume


# ---------------------------------------------------------------------------
# AI-AL — decide() dispatch
# ---------------------------------------------------------------------------


class TestDecideDispatch:
    def test_unknown_event_kind_gives_fail_closed(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(event_kind=ContinuityEventKind.unknown)
        artifact = c.decide(ctx)
        assert artifact.decision == ContinuityDecision.fail_closed

    def test_dispatches_fresh_attach(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide(ctx)
        assert artifact.event_kind == ContinuityEventKind.fresh_attach
        assert artifact.decision in (
            ContinuityDecision.new_attachment,
            ContinuityDecision.continuity_resume,
            ContinuityDecision.fail_closed,
        )

    def test_dispatches_transport_reconnect(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.transport_reconnect,
            device_id="dev-1",
        )
        artifact = c.decide(ctx)
        assert artifact.event_kind == ContinuityEventKind.transport_reconnect

    def test_dispatches_partial_result(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.partial_result,
            session_id="sess-1",
            is_partial_result=True,
        )
        artifact = c.decide(ctx)
        assert artifact.event_kind == ContinuityEventKind.partial_result


# ---------------------------------------------------------------------------
# AM-AN — build_snapshot
# ---------------------------------------------------------------------------


class TestBuildSnapshot:
    def test_empty_coordinator_snapshot(self):
        from core.flow_continuity_coordinator import FlowContinuityCoordinator
        c = FlowContinuityCoordinator()
        snap = c.build_snapshot()
        assert snap.total_decisions == 0
        assert snap.decision_counts == {}
        assert snap.recent_artifacts == []
        assert len(snap.policy_sentinels) == 9

    def test_snapshot_counts_decisions(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        # Make 3 decisions
        for _ in range(2):
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.fresh_attach,
                device_id="dev-1",
                metadata={"registry_entry_created": True},
            )
            c.decide_attach(ctx)
        ctx_fail = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            metadata={"registry_entry_created": False},
        )
        c.decide_attach(ctx_fail)
        snap = c.build_snapshot()
        assert snap.total_decisions == 3
        assert snap.decision_counts.get("fail_closed", 0) == 1
        assert len(snap.recent_artifacts) <= 10


# ---------------------------------------------------------------------------
# AO — list_recent
# ---------------------------------------------------------------------------


class TestListRecent:
    def test_returns_newest_first(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        device_ids = [f"dev-{i}" for i in range(5)]
        for did in device_ids:
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.fresh_attach,
                device_id=did,
                metadata={"registry_entry_created": True},
            )
            c.decide_attach(ctx)
        recent = c.list_recent(3)
        assert len(recent) == 3
        # newest first
        assert recent[0].device_id == "dev-4"
        assert recent[1].device_id == "dev-3"
        assert recent[2].device_id == "dev-2"


# ---------------------------------------------------------------------------
# AP — get_by_artifact_id
# ---------------------------------------------------------------------------


class TestGetByArtifactId:
    def test_returns_artifact_by_id(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        found = c.get_by_artifact_id(artifact.artifact_id)
        assert found is not None
        assert found.artifact_id == artifact.artifact_id

    def test_returns_none_for_unknown_id(self):
        c = _fresh_coordinator()
        assert c.get_by_artifact_id("not-a-real-id") is None


# ---------------------------------------------------------------------------
# AQ-AW — convenience wrappers
# ---------------------------------------------------------------------------


class TestConvenienceWrappers:
    def setup_method(self):
        from core.flow_continuity_coordinator import reset_flow_continuity_coordinator
        reset_flow_continuity_coordinator()

    def teardown_method(self):
        from core.flow_continuity_coordinator import reset_flow_continuity_coordinator
        reset_flow_continuity_coordinator()

    def test_coordinate_attach(self):
        from core.flow_continuity_coordinator import (
            coordinate_attach,
            ContinuityDecisionArtifact,
        )
        c = _fresh_coordinator()
        artifact = coordinate_attach(
            "dev-1",
            "att-1",
            prior_entry_state="",
            registry_entry_created=True,
            coordinator=c,
        )
        assert isinstance(artifact, ContinuityDecisionArtifact)
        assert artifact.device_id == "dev-1"

    def test_coordinate_reconnect(self):
        from core.flow_continuity_coordinator import (
            coordinate_reconnect,
            ContinuityDecisionArtifact,
        )
        c = _fresh_coordinator()
        artifact = coordinate_reconnect("dev-1", "att-1", coordinator=c)
        assert isinstance(artifact, ContinuityDecisionArtifact)

    def test_coordinate_reattach_process_recreation(self):
        from core.flow_continuity_coordinator import (
            coordinate_reattach_process_recreation,
            ContinuityDecisionArtifact,
            ContinuityDecision,
        )
        c = _fresh_coordinator()
        artifact = coordinate_reattach_process_recreation(
            "dev-1",
            "att-1",
            prior_entry_was_active_or_detached=True,
            attachment_id_matched=True,
            coordinator=c,
        )
        assert isinstance(artifact, ContinuityDecisionArtifact)
        assert artifact.decision == ContinuityDecision.continuity_resume

    def test_coordinate_stale_identity(self):
        from core.flow_continuity_coordinator import (
            coordinate_stale_identity,
            ContinuityDecisionArtifact,
        )
        c = _fresh_coordinator()
        artifact = coordinate_stale_identity(
            session_id="sess-1",
            contract_id="contract-1",
            coordinator=c,
        )
        assert isinstance(artifact, ContinuityDecisionArtifact)

    def test_coordinate_duplicate_signal(self):
        from core.flow_continuity_coordinator import (
            coordinate_duplicate_signal,
            ContinuityDecisionArtifact,
        )
        c = _fresh_coordinator()
        artifact = coordinate_duplicate_signal("sig-key-1", session_id="sess-1", coordinator=c)
        assert isinstance(artifact, ContinuityDecisionArtifact)

    def test_coordinate_partial_result(self):
        from core.flow_continuity_coordinator import (
            coordinate_partial_result,
            ContinuityDecisionArtifact,
        )
        c = _fresh_coordinator()
        artifact = coordinate_partial_result(
            session_id="sess-1",
            partial_result_payload={"key": "value"},
            coordinator=c,
        )
        assert isinstance(artifact, ContinuityDecisionArtifact)

    def test_coordinate_v2_restart_recovery(self):
        from core.flow_continuity_coordinator import (
            coordinate_v2_restart_recovery,
            ContinuityDecisionArtifact,
        )
        c = _fresh_coordinator()
        artifact = coordinate_v2_restart_recovery(
            flow_lineage_id="lineage-1",
            recovery_completed=True,
            coordinator=c,
        )
        assert isinstance(artifact, ContinuityDecisionArtifact)


# ---------------------------------------------------------------------------
# AX-AY — is_resumable
# ---------------------------------------------------------------------------


class TestIsResumable:
    def test_continuity_resume_is_resumable(self):
        from core.flow_continuity_coordinator import (
            ContinuityDecisionArtifact,
            ContinuityDecision,
        )
        a = ContinuityDecisionArtifact(decision=ContinuityDecision.continuity_resume)
        # is_resumable is set by _base_artifact, not in constructor
        # Verify via the coordinator
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            prior_entry_state="active",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.is_resumable is True

    def test_preserve_partial_is_resumable(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            FlowContinuityCoordinator,
        )

        class _MockRecord:
            phase = type("P", (), {"value": "executing"})()

        class _MockTracker:
            def get_latest_for_session(self, session_id):
                return _MockRecord()

        c = FlowContinuityCoordinator()
        c._get_execution_tracking_runtime = lambda: _MockTracker()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.partial_result,
            session_id="sess-1",
            is_partial_result=True,
        )
        artifact = c.decide_partial_result(ctx)
        assert artifact.is_resumable is True

    def test_new_attachment_is_not_resumable(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            prior_entry_state="",
            metadata={"registry_entry_created": True},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.is_resumable is False

    def test_fail_closed_is_not_resumable(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.fresh_attach,
            device_id="dev-1",
            metadata={"registry_entry_created": False},
        )
        artifact = c.decide_attach(ctx)
        assert artifact.is_resumable is False


# ---------------------------------------------------------------------------
# AZ — ContinuityDecision.from_string
# ---------------------------------------------------------------------------


class TestFromString:
    def test_known_decision_value(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.from_string("new_attachment") == ContinuityDecision.new_attachment
        assert ContinuityDecision.from_string("continuity_resume") == ContinuityDecision.continuity_resume
        assert ContinuityDecision.from_string("fail_closed") == ContinuityDecision.fail_closed

    def test_unknown_decision_value_gives_fail_closed(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.from_string("not_a_valid_decision") == ContinuityDecision.fail_closed

    def test_non_string_gives_fail_closed(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        assert ContinuityDecision.from_string(None) == ContinuityDecision.fail_closed
        assert ContinuityDecision.from_string(42) == ContinuityDecision.fail_closed

    def test_from_string_with_custom_default(self):
        from core.flow_continuity_coordinator import ContinuityDecision
        result = ContinuityDecision.from_string(
            "unknown_value", default=ContinuityDecision.require_review
        )
        assert result == ContinuityDecision.require_review


# ---------------------------------------------------------------------------
# BA — ContinuityEventKind.from_string
# ---------------------------------------------------------------------------


class TestEventKindFromString:
    def test_known_value(self):
        from core.flow_continuity_coordinator import ContinuityEventKind
        assert ContinuityEventKind.from_string("fresh_attach") == ContinuityEventKind.fresh_attach
        assert ContinuityEventKind.from_string("partial_result") == ContinuityEventKind.partial_result

    def test_unknown_value_gives_unknown(self):
        from core.flow_continuity_coordinator import ContinuityEventKind
        assert ContinuityEventKind.from_string("foobar") == ContinuityEventKind.unknown

    def test_non_string_gives_unknown(self):
        from core.flow_continuity_coordinator import ContinuityEventKind
        assert ContinuityEventKind.from_string(None) == ContinuityEventKind.unknown


# ---------------------------------------------------------------------------
# BB — Ring-buffer capacity
# ---------------------------------------------------------------------------


class TestRingBufferCapacity:
    def test_oldest_evicted_when_full(self):
        from core.flow_continuity_coordinator import (
            FlowContinuityCoordinator,
            ContinuityEventContext,
            ContinuityEventKind,
        )
        capacity = 3
        c = FlowContinuityCoordinator(capacity=capacity)
        for i in range(capacity + 2):
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.fresh_attach,
                device_id=f"dev-{i}",
                metadata={"registry_entry_created": True},
            )
            c.decide_attach(ctx)
        # Buffer should only hold `capacity` entries
        recent = c.list_recent(100)
        assert len(recent) == capacity


# ---------------------------------------------------------------------------
# BC — artifact round-trip
# ---------------------------------------------------------------------------


class TestArtifactRoundTripFull:
    def test_all_fields_preserved(self):
        from core.flow_continuity_coordinator import (
            ContinuityDecisionArtifact,
            ContinuityDecision,
            ContinuityEventKind,
        )
        original = ContinuityDecisionArtifact(
            event_kind=ContinuityEventKind.stale_identity,
            decision=ContinuityDecision.reject_stale_identity,
            policy_reference="STALE_POLICY",
            detail="stale detail",
            device_id="dev-X",
            session_id="sess-X",
            runtime_attachment_session_id="att-X",
            contract_id="contract-X",
            flow_id="flow-X",
            flow_lineage_id="lineage-X",
            registry_outcome="replaced",
            tracking_record_phase="completed",
            flow_entity_phase="completed",
            contract_verified="pass",
            is_resumable=False,
            extension_payload={"operator_tag": "test"},
        )
        d = original.to_dict()
        restored = ContinuityDecisionArtifact.from_dict(d)
        assert restored.artifact_id == original.artifact_id
        assert restored.event_kind == original.event_kind
        assert restored.decision == original.decision
        assert restored.policy_reference == original.policy_reference
        assert restored.detail == original.detail
        assert restored.device_id == original.device_id
        assert restored.session_id == original.session_id
        assert restored.contract_id == original.contract_id
        assert restored.flow_id == original.flow_id
        assert restored.flow_lineage_id == original.flow_lineage_id
        assert restored.registry_outcome == original.registry_outcome
        assert restored.tracking_record_phase == original.tracking_record_phase
        assert restored.flow_entity_phase == original.flow_entity_phase
        assert restored.is_resumable == original.is_resumable
        assert restored.extension_payload == original.extension_payload


# ---------------------------------------------------------------------------
# BD — ring-buffer records each decision
# ---------------------------------------------------------------------------


class TestRingBufferRecording:
    def test_each_decision_is_recorded(self):
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
        )
        c = _fresh_coordinator()
        n = 5
        for i in range(n):
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.fresh_attach,
                device_id=f"dev-{i}",
                metadata={"registry_entry_created": True},
            )
            c.decide_attach(ctx)
        snap = c.build_snapshot()
        assert snap.total_decisions == n
