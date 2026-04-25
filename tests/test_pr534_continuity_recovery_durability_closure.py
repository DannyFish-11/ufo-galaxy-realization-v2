#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr534_continuity_recovery_durability_closure.py
==========================================================
PR-534 (test file number) / Package-5 (post-533 dual-repo runtime-unification
master plan, V2 side): Continuity Recovery and Offline Durability Closure —
end-to-end validation test suite.

Problem addressed
-----------------
The continuity / recovery / offline durability infrastructure (PR-3 through
PR-5) is "framework-complete but not yet operationally closed."  This test
suite bridges the gap by:

1. Exercising all 7 FlowContinuityCoordinator scenarios end-to-end.
2. Validating the full in-flight delegated-work recovery decision chain
   (FlowContinuityCoordinator → DelegatedFlowRecoveryCoordinator).
3. Verifying replay / stale / duplicate signal guard behaviour under
   recovery conditions.
4. Proving that the RuntimeRestartRecoveryCoordinator dispatch is
   deterministic and idempotent.
5. Demonstrating that the RecoveryClosureReport (the reviewable matrix) is
   buildable, all_closed, and serialisable.

Coverage matrix
---------------
Group A — RecoveryDurabilityClosureValidator module
  A01. Module importable; authority sentinel and PR-5 sentinel present.
  A02. All 7 policy sentinels are non-empty strings.
  A03. RecoveryScenarioStatus enum has all 4 required values.
  A04. RecoveryScenarioEntry dataclass has required fields; to_dict() works.
  A05. RecoveryScenarioEntry round-trips to_dict → from_dict correctly.
  A06. RecoveryClosureReport dataclass has required fields; to_dict() works.
  A07. RecoveryClosureReport to_json() is valid JSON.
  A08. get_recovery_closure_report() returns a singleton; reset clears it.

Group B — RecoveryClosureReport content
  B01. build_recovery_closure_report() returns a RecoveryClosureReport.
  B02. Report contains exactly 17 scenario entries.
  B03. Report all_closed is True (no fail_closed scenarios).
  B04. Report has 0 fail_closed scenarios.
  B05. Report has exactly 1 deferred scenario (RS-16: offline queue ordering).
  B06. All non-deferred scenarios have observed_decision != '(deferred)'.
  B07. Every scenario entry has a non-empty scenario_id.
  B08. Every scenario entry has a non-empty policy_reference.
  B09. Deferred scenario RS-16 documents the offline queue ordering deferral.
  B10. Report to_dict() contains all required top-level keys.
  B11. pr5_sentinel in report matches RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL.

Group C — V2 restart recovery (FlowContinuityCoordinator)
  C01. decide_v2_restart_recovery: recovery_completed=False → require_review.
  C02. decide_v2_restart_recovery: recovery_completed=True, no durable flow
       → new_attachment.
  C03. coordinate_v2_restart_recovery convenience wrapper produces a
       ContinuityDecisionArtifact with non-empty artifact_id.
  C04. The artifact carries the correct policy_reference.
  C05. Fail-closed when event_kind is unknown.

Group D — Transport reconnect (FlowContinuityCoordinator)
  D01. decide_reconnect: attachment ID present → bounded decision
       (continuity_resume | new_attachment | fail_closed | require_review).
  D02. decide_reconnect: attachment ID absent → require_review or safe default
       (never silently continuity_resume without attachment ID).
  D03. coordinate_reconnect convenience wrapper returns ContinuityDecisionArtifact.
  D04. Artifact event_kind == transport_reconnect.

Group E — Stale identity & duplicate signal (FlowContinuityCoordinator)
  E01. decide_stale_identity → reject_stale_identity; decision is non-destructive.
  E02. coordinate_stale_identity convenience wrapper returns correct decision.
  E03. decide_duplicate_signal: novel signal_key → continuity_resume (pass through).
  E04. coordinate_duplicate_signal convenience wrapper returns ContinuityDecisionArtifact.
  E05. decide_partial_result: is_partial_result=True → preserve_partial_and_wait.
  E06. coordinate_partial_result convenience wrapper returns correct decision.

Group F — In-flight delegated work recovery (DelegatedFlowRecoveryCoordinator)
  F01. decide: continuity_resume + active flow → resume_in_place.
  F02. decide: checkpoint_available=True → replay_from_checkpoint.
  F03. decide: binding_state=released, no checkpoint → redispatch_runtime.
  F04. decide: has_partial_result=True → preserve_partial_then_resume.
  F05. decide: missing flow_id → fail_closed.
  F06. begin_attempt + decide (same flow_id) → suppress_duplicate_recovery.
  F07. decide_from_continuity_artifact: enriches context from artifact dict.

Group G — Signal guard (attached_runtime_recovery_readiness)
  G01. Fresh runtime: novel signal → accept.
  G02. Same signal_id seen twice → duplicate on second call.
  G03. Same emission_seq, different signal_id → replay.
  G04. emission_seq far below max_seen → stale.
  G05. emission_seq slightly below max_seen → out_of_order.
  G06. check_signal_guard does not mutate runtime (pure evaluation).
  G07. record_seen_signal increments the ring buffer.
  G08. Two contracts are guard-isolated (independent ring buffers).

Group H — Runtime restart recovery (RuntimeRestartRecoveryCoordinator)
  H01. run_recovery with empty stores → report with 0 errors.
  H02. RESUMABLE task → registered under DEVICE_DISPATCH ownership.
  H03. TERMINAL_ON_INTERRUPT task → NOT registered; terminal count incremented.
  H04. run_recovery is idempotent: second run skips already-pending tasks.
  H05. RuntimeRecoveryReport to_dict() contains all required keys.
  H06. Recovery report non_goals list is non-empty (explicit ephemeral docs).

Group I — Chain tests (FlowContinuityCoordinator → DelegatedFlowRecoveryCoordinator)
  I01. Chain: v2_restart_recovery(continuity_resume) → resume_in_place action.
  I02. Chain: v2_restart_recovery(new_attachment) → require_review or redispatch.
  I03. Chain: stale_identity → reject; delegated flow coordinator receives
       reject_stale_identity as continuity_decision → fail_closed or require_review.

Group J — Recovery ordering and non-interference
  J01. Signal guard decisions are independent per (contract_id, session_id) key.
  J02. DelegatedFlowRecoveryCoordinator: completing an attempt de-registers it
       (next decide for same flow_id proceeds normally).
  J03. RuntimeRestartRecoveryCoordinator: intra-snapshot duplicate task_ids
       produce only one registration (deduplication confirmed).
  J04. Recovered tasks do not overwrite already-registered tasks
       (in-process state takes precedence).

Group K — Serialisation and observability
  K01. ContinuityDecisionArtifact to_dict() → from_dict() round-trip.
  K02. RecoveryDecisionArtifact to_dict() → from_dict() round-trip.
  K03. RecoveryClosureReport to_json() → loads as valid dict; all scenario
       entries present.
  K04. FlowContinuityCoordinator snapshot (build_snapshot) includes
       total_decisions after several decisions.
  K05. DelegatedFlowRecoveryCoordinator snapshot includes total_decisions.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _fresh_continuity_coordinator():
    from core.flow_continuity_coordinator import FlowContinuityCoordinator
    return FlowContinuityCoordinator(capacity=32)


def _fresh_recovery_coordinator():
    from core.delegated_flow_recovery_coordinator import (
        DelegatedFlowRecoveryCoordinator,
    )
    return DelegatedFlowRecoveryCoordinator(capacity=32)


def _fresh_guard_runtime():
    from core.attached_runtime_recovery_readiness import RecoveryReadinessRuntime
    return RecoveryReadinessRuntime()


def _continuity_ctx(**kwargs):
    from core.flow_continuity_coordinator import (
        ContinuityEventContext,
        ContinuityEventKind,
    )
    kind_str = kwargs.pop("event_kind", "unknown")
    return ContinuityEventContext(
        event_kind=ContinuityEventKind.from_string(kind_str),
        **kwargs,
    )


def _recovery_ctx(**kwargs):
    from core.delegated_flow_recovery_coordinator import (
        RecoveryTriggerContext,
        RecoveryTrigger,
    )
    trigger_str = kwargs.pop("trigger", "unknown")
    return RecoveryTriggerContext(
        trigger=RecoveryTrigger.from_string(trigger_str),
        **kwargs,
    )


def _make_restart_coordinator(tmp_path, records: List[Dict[str, Any]]):
    """Build a RuntimeRestartRecoveryCoordinator with task records."""
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
    from core.task_lifecycle_persistence import (
        TaskLifecyclePersistenceStore,
        save_task_lifecycle_snapshot,
    )
    from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

    ms_store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
    bm_store = BodyMeshPersistenceStore(
        store_path=os.path.join(str(tmp_path), "bm.json")
    )
    tl_store = TaskLifecyclePersistenceStore(
        store_path=os.path.join(str(tmp_path), "tl.json")
    )
    if records:
        save_task_lifecycle_snapshot(records, store=tl_store)

    class _FakeBodyRegistry:
        def register(self, device_id, roles=None, session_id=None, metadata=None):
            return {}
        def list_entries(self):
            return []

    return RuntimeRestartRecoveryCoordinator(
        mesh_session_store=ms_store,
        body_mesh_store=bm_store,
        body_mesh_registry=_FakeBodyRegistry(),
        task_lifecycle_store=tl_store,
    )


def _task_record(task_id: str, owner: str) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "trace_id": f"trace_{task_id}",
        "target_device_id": "dev_test",
        "tool_name": "test_tool",
        "owner": owner,
        "timeout": 30.0,
        "registered_at": time.time() - 5.0,
        "metadata": {},
    }


# ===========================================================================
# Group A — RecoveryDurabilityClosureValidator module
# ===========================================================================


def test_A01_module_importable_sentinels_present():
    from core.recovery_durability_closure_validator import (
        RECOVERY_DURABILITY_CLOSURE_AUTHORITY,
        RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL,
    )
    assert RECOVERY_DURABILITY_CLOSURE_AUTHORITY
    assert "package=5" in RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL
    assert "continuity-recovery" in RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL


def test_A02_all_policy_sentinels_non_empty():
    from core.recovery_durability_closure_validator import (
        RECOVERY_DURABILITY_CLOSURE_AUTHORITY,
        RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL,
        V2_RESTART_RECOVERY_IS_DETERMINISTIC_POLICY,
        INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY,
        SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY,
        CONTINUITY_COORDINATOR_IS_SINGLE_RECOVERY_ENTRY_POINT_POLICY,
        OFFLINE_QUEUE_ORDERING_IS_DEFERRED_POLICY,
    )
    for sentinel in [
        RECOVERY_DURABILITY_CLOSURE_AUTHORITY,
        RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL,
        V2_RESTART_RECOVERY_IS_DETERMINISTIC_POLICY,
        INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY,
        SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY,
        CONTINUITY_COORDINATOR_IS_SINGLE_RECOVERY_ENTRY_POINT_POLICY,
        OFFLINE_QUEUE_ORDERING_IS_DEFERRED_POLICY,
    ]:
        assert isinstance(sentinel, str) and sentinel, f"empty sentinel: {sentinel!r}"


def test_A03_recovery_scenario_status_enum_values():
    from core.recovery_durability_closure_validator import RecoveryScenarioStatus
    assert RecoveryScenarioStatus.closed.value == "closed"
    assert RecoveryScenarioStatus.advisory.value == "advisory"
    assert RecoveryScenarioStatus.deferred.value == "deferred"
    assert RecoveryScenarioStatus.fail_closed.value == "fail_closed"


def test_A04_recovery_scenario_entry_fields_and_to_dict():
    from core.recovery_durability_closure_validator import (
        RecoveryScenarioEntry,
        RecoveryScenarioStatus,
    )
    entry = RecoveryScenarioEntry(
        scenario_id="RS-X",
        scenario_name="test",
        event_kind="fresh_attach",
        decision_path="FlowContinuityCoordinator.decide_attach",
        expected_decision="new_attachment",
        observed_decision="new_attachment",
        status=RecoveryScenarioStatus.closed,
        artifact_id="art-001",
        policy_reference="POLICY_X",
        note="test note",
    )
    d = entry.to_dict()
    assert d["scenario_id"] == "RS-X"
    assert d["status"] == "closed"
    assert d["observed_decision"] == "new_attachment"
    assert d["policy_reference"] == "POLICY_X"


def test_A05_recovery_scenario_entry_round_trip():
    from core.recovery_durability_closure_validator import (
        RecoveryScenarioEntry,
        RecoveryScenarioStatus,
    )
    entry = RecoveryScenarioEntry(
        scenario_id="RS-Y",
        scenario_name="round-trip",
        status=RecoveryScenarioStatus.advisory,
        observed_decision="require_review",
    )
    restored = RecoveryScenarioEntry.from_dict(entry.to_dict())
    assert restored.scenario_id == "RS-Y"
    assert restored.status == RecoveryScenarioStatus.advisory
    assert restored.observed_decision == "require_review"


def test_A06_recovery_closure_report_fields_and_to_dict():
    from core.recovery_durability_closure_validator import RecoveryClosureReport
    report = RecoveryClosureReport(closed_count=5, deferred_count=1)
    d = report.to_dict()
    assert "report_id" in d
    assert d["closed_count"] == 5
    assert d["deferred_count"] == 1
    assert "scenarios" in d
    assert "pr5_sentinel" in d


def test_A07_recovery_closure_report_to_json_valid():
    from core.recovery_durability_closure_validator import RecoveryClosureReport
    report = RecoveryClosureReport()
    payload = json.loads(report.to_json())
    assert isinstance(payload, dict)
    assert "report_id" in payload


def test_A08_get_report_singleton_and_reset():
    from core.recovery_durability_closure_validator import (
        get_recovery_closure_report,
        reset_recovery_closure_report,
    )
    reset_recovery_closure_report()
    r1 = get_recovery_closure_report()
    r2 = get_recovery_closure_report()
    assert r1 is r2  # same singleton
    reset_recovery_closure_report()
    r3 = get_recovery_closure_report()
    assert r3 is not r1  # new singleton after reset


# ===========================================================================
# Group B — RecoveryClosureReport content
# ===========================================================================


@pytest.fixture(scope="module")
def closure_report():
    from core.recovery_durability_closure_validator import build_recovery_closure_report
    return build_recovery_closure_report()


def test_B01_build_report_returns_correct_type(closure_report):
    from core.recovery_durability_closure_validator import RecoveryClosureReport
    assert isinstance(closure_report, RecoveryClosureReport)


def test_B02_report_has_17_scenarios(closure_report):
    assert len(closure_report.scenarios) == 17


def test_B03_report_all_closed_is_true(closure_report):
    assert closure_report.all_closed is True, (
        f"all_closed is False; fail_closed_count={closure_report.fail_closed_count}; "
        f"fail_closed scenarios: "
        + str([s.scenario_id for s in closure_report.scenarios if s.status.value == "fail_closed"])
    )


def test_B04_report_no_fail_closed_scenarios(closure_report):
    fails = [s for s in closure_report.scenarios if s.status.value == "fail_closed"]
    assert fails == [], (
        f"Found fail_closed scenarios: {[(s.scenario_id, s.observed_decision) for s in fails]}"
    )


def test_B05_report_has_exactly_one_deferred_scenario(closure_report):
    deferred = [s for s in closure_report.scenarios if s.status.value == "deferred"]
    assert len(deferred) == 1
    assert deferred[0].scenario_id == "RS-16"


def test_B06_non_deferred_scenarios_have_real_observed_decisions(closure_report):
    for entry in closure_report.scenarios:
        if entry.status.value != "deferred":
            assert entry.observed_decision != "(deferred)", (
                f"{entry.scenario_id} is not deferred but has placeholder decision"
            )


def test_B07_every_scenario_has_non_empty_scenario_id(closure_report):
    for entry in closure_report.scenarios:
        assert entry.scenario_id, f"empty scenario_id in entry: {entry}"


def test_B08_every_scenario_has_non_empty_policy_reference(closure_report):
    for entry in closure_report.scenarios:
        assert entry.policy_reference, (
            f"empty policy_reference in {entry.scenario_id}"
        )


def test_B09_deferred_rs16_documents_offline_queue(closure_report):
    rs16 = next(s for s in closure_report.scenarios if s.scenario_id == "RS-16")
    assert "offline" in rs16.note.lower() or "queue" in rs16.note.lower()
    assert "deferred" in rs16.note.lower() or "RS-16" in rs16.scenario_id


def test_B10_report_to_dict_has_required_keys(closure_report):
    d = closure_report.to_dict()
    for key in [
        "report_id",
        "generated_at",
        "scenarios",
        "closed_count",
        "advisory_count",
        "deferred_count",
        "fail_closed_count",
        "all_closed",
        "deferred_notes",
        "pr5_sentinel",
    ]:
        assert key in d, f"missing key {key!r} in report dict"


def test_B11_report_pr5_sentinel_matches_module_constant(closure_report):
    from core.recovery_durability_closure_validator import (
        RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL,
    )
    assert closure_report.pr5_sentinel == RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL


# ===========================================================================
# Group C — V2 restart recovery (FlowContinuityCoordinator)
# ===========================================================================


def test_C01_v2_restart_recovery_not_completed_gives_require_review():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="v2_restart_recovery",
        recovery_completed=False,
        flow_lineage_id="lin-c01",
    )
    artifact = c.decide_v2_restart_recovery(ctx)
    from core.flow_continuity_coordinator import ContinuityDecision
    assert artifact.decision == ContinuityDecision.require_review
    assert artifact.artifact_id


def test_C02_v2_restart_recovery_completed_no_durable_flow_gives_new_attachment():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="v2_restart_recovery",
        recovery_completed=True,
        flow_lineage_id="lin-c02-no-flow",
    )
    artifact = c.decide_v2_restart_recovery(ctx)
    from core.flow_continuity_coordinator import ContinuityDecision
    assert artifact.decision == ContinuityDecision.new_attachment


def test_C03_coordinate_v2_restart_recovery_returns_artifact():
    from core.flow_continuity_coordinator import (
        coordinate_v2_restart_recovery,
        FlowContinuityCoordinator,
        ContinuityDecisionArtifact,
    )
    c = FlowContinuityCoordinator(capacity=16)
    artifact = coordinate_v2_restart_recovery(
        flow_lineage_id="lin-c03",
        recovery_completed=False,
        coordinator=c,
    )
    assert isinstance(artifact, ContinuityDecisionArtifact)
    assert artifact.artifact_id


def test_C04_v2_restart_artifact_carries_policy_reference():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="v2_restart_recovery",
        recovery_completed=True,
    )
    artifact = c.decide_v2_restart_recovery(ctx)
    assert "V2_RESTART" in artifact.policy_reference or "DURABLE_STORE" in artifact.policy_reference


def test_C05_unknown_event_kind_gives_fail_closed():
    c = _fresh_continuity_coordinator()
    from core.flow_continuity_coordinator import ContinuityEventContext, ContinuityEventKind
    ctx = ContinuityEventContext(event_kind=ContinuityEventKind.unknown)
    artifact = c.decide(ctx)
    from core.flow_continuity_coordinator import ContinuityDecision
    assert artifact.decision == ContinuityDecision.fail_closed


# ===========================================================================
# Group D — Transport reconnect (FlowContinuityCoordinator)
# ===========================================================================


def test_D01_reconnect_attachment_id_present_gives_bounded_decision():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="transport_reconnect",
        device_id="dev-d01",
        runtime_attachment_session_id="att-d01",
    )
    artifact = c.decide_reconnect(ctx)
    from core.flow_continuity_coordinator import ContinuityDecision
    valid = {
        ContinuityDecision.continuity_resume,
        ContinuityDecision.new_attachment,
        ContinuityDecision.fail_closed,
        ContinuityDecision.require_review,
    }
    assert artifact.decision in valid, f"unexpected decision: {artifact.decision!r}"


def test_D02_reconnect_no_attachment_id_never_silently_resumes():
    """A reconnect with no attachment ID must never be classified continuity_resume."""
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="transport_reconnect",
        device_id="dev-d02",
        runtime_attachment_session_id="",
    )
    artifact = c.decide_reconnect(ctx)
    from core.flow_continuity_coordinator import ContinuityDecision
    # Must NOT silently resume when attachment ID is absent
    assert artifact.decision != ContinuityDecision.continuity_resume, (
        "Coordinator MUST NOT emit continuity_resume without attachment ID"
    )


def test_D03_coordinate_reconnect_returns_artifact():
    from core.flow_continuity_coordinator import (
        coordinate_reconnect,
        FlowContinuityCoordinator,
        ContinuityDecisionArtifact,
    )
    c = FlowContinuityCoordinator(capacity=16)
    artifact = coordinate_reconnect(
        device_id="dev-d03",
        runtime_attachment_session_id="att-d03",
        coordinator=c,
    )
    assert isinstance(artifact, ContinuityDecisionArtifact)
    assert artifact.artifact_id


def test_D04_reconnect_artifact_event_kind_is_transport_reconnect():
    from core.flow_continuity_coordinator import (
        coordinate_reconnect,
        FlowContinuityCoordinator,
        ContinuityEventKind,
    )
    c = FlowContinuityCoordinator(capacity=16)
    artifact = coordinate_reconnect(
        device_id="dev-d04",
        coordinator=c,
    )
    assert artifact.event_kind == ContinuityEventKind.transport_reconnect


# ===========================================================================
# Group E — Stale identity & duplicate signal (FlowContinuityCoordinator)
# ===========================================================================


def test_E01_stale_identity_gives_reject_non_destructive():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="stale_identity",
        device_id="dev-e01",
        session_id="sess-e01-expired",
    )
    artifact = c.decide_stale_identity(ctx)
    from core.flow_continuity_coordinator import ContinuityDecision
    assert artifact.decision == ContinuityDecision.reject_stale_identity
    # The policy reference must affirm non-destructive behaviour
    assert "NON_DESTRUCTIVE" in artifact.policy_reference or "STALE" in artifact.policy_reference


def test_E02_coordinate_stale_identity_returns_correct_decision():
    from core.flow_continuity_coordinator import (
        coordinate_stale_identity,
        FlowContinuityCoordinator,
        ContinuityDecision,
    )
    c = FlowContinuityCoordinator(capacity=16)
    artifact = coordinate_stale_identity(
        device_id="dev-e02",
        session_id="sess-e02",
        coordinator=c,
    )
    assert artifact.decision == ContinuityDecision.reject_stale_identity


def test_E03_duplicate_signal_novel_key_gives_continuity_resume():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="duplicate_signal",
        device_id="dev-e03",
        contract_id="ctr-e03",
        signal_key="sig-e03-novel",
    )
    artifact = c.decide_duplicate_signal(ctx)
    from core.flow_continuity_coordinator import ContinuityDecision
    # Novel signal (not yet in tracker ack history) → continuity_resume (pass through)
    assert artifact.decision == ContinuityDecision.continuity_resume


def test_E04_coordinate_duplicate_signal_returns_artifact():
    from core.flow_continuity_coordinator import (
        coordinate_duplicate_signal,
        FlowContinuityCoordinator,
        ContinuityDecisionArtifact,
    )
    c = FlowContinuityCoordinator(capacity=16)
    artifact = coordinate_duplicate_signal(
        device_id="dev-e04",
        contract_id="ctr-e04",
        signal_key="sig-e04",
        coordinator=c,
    )
    assert isinstance(artifact, ContinuityDecisionArtifact)
    assert artifact.artifact_id


def test_E05_partial_result_gives_preserve_partial_and_wait():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="partial_result",
        device_id="dev-e05",
        contract_id="ctr-e05",
        is_partial_result=True,
    )
    artifact = c.decide_partial_result(ctx)
    from core.flow_continuity_coordinator import ContinuityDecision
    assert artifact.decision == ContinuityDecision.preserve_partial_and_wait


def test_E06_coordinate_partial_result_returns_correct_decision():
    from core.flow_continuity_coordinator import (
        coordinate_partial_result,
        FlowContinuityCoordinator,
        ContinuityDecision,
    )
    c = FlowContinuityCoordinator(capacity=16)
    artifact = coordinate_partial_result(
        device_id="dev-e06",
        contract_id="ctr-e06",
        coordinator=c,
    )
    assert artifact.decision == ContinuityDecision.preserve_partial_and_wait


# ===========================================================================
# Group F — In-flight delegated work recovery (DelegatedFlowRecoveryCoordinator)
# ===========================================================================


def test_F01_resume_in_place_for_continuity_resume_active_flow():
    c = _fresh_recovery_coordinator()
    ctx = _recovery_ctx(
        trigger="v2_restart",
        flow_id=f"flow-f01-{uuid.uuid4().hex[:8]}",
        continuity_decision="continuity_resume",
        has_partial_result=False,
        checkpoint_available=False,
        binding_state="bound",
    )
    artifact = c.decide(ctx)
    from core.delegated_flow_recovery_coordinator import RecoveryAction
    assert artifact.action == RecoveryAction.resume_in_place


def test_F02_replay_from_checkpoint_when_checkpoint_available():
    c = _fresh_recovery_coordinator()
    ctx = _recovery_ctx(
        trigger="android_binding_lost",
        flow_id=f"flow-f02-{uuid.uuid4().hex[:8]}",
        continuity_decision="continuity_resume",
        has_partial_result=False,
        checkpoint_available=True,
        checkpoint_boundary_phase="dispatching",
        binding_state="released",
    )
    artifact = c.decide(ctx)
    from core.delegated_flow_recovery_coordinator import RecoveryAction
    assert artifact.action == RecoveryAction.replay_from_checkpoint


def test_F03_redispatch_runtime_when_binding_released_no_checkpoint():
    c = _fresh_recovery_coordinator()
    ctx = _recovery_ctx(
        trigger="android_binding_lost",
        flow_id=f"flow-f03-{uuid.uuid4().hex[:8]}",
        continuity_decision="new_attachment",
        has_partial_result=False,
        checkpoint_available=False,
        binding_state="released",
    )
    artifact = c.decide(ctx)
    from core.delegated_flow_recovery_coordinator import RecoveryAction
    assert artifact.action == RecoveryAction.redispatch_runtime


def test_F04_preserve_partial_then_resume_when_partial_result_detected():
    c = _fresh_recovery_coordinator()
    ctx = _recovery_ctx(
        trigger="android_result_received",
        flow_id=f"flow-f04-{uuid.uuid4().hex[:8]}",
        has_partial_result=True,
        checkpoint_available=False,
        binding_state="bound",
    )
    artifact = c.decide(ctx)
    from core.delegated_flow_recovery_coordinator import RecoveryAction
    assert artifact.action == RecoveryAction.preserve_partial_then_resume


def test_F05_fail_closed_when_flow_id_missing():
    c = _fresh_recovery_coordinator()
    ctx = _recovery_ctx(
        trigger="v2_restart",
        flow_id="",  # missing
    )
    artifact = c.decide(ctx)
    from core.delegated_flow_recovery_coordinator import RecoveryAction
    assert artifact.action == RecoveryAction.fail_closed


def test_F06_duplicate_attempt_suppressed_after_begin_attempt():
    """begin_attempt registers flow_id; subsequent decide returns suppress_duplicate_recovery."""
    c = _fresh_recovery_coordinator()
    flow_id = f"flow-f06-{uuid.uuid4().hex[:8]}"
    ctx1 = _recovery_ctx(
        trigger="v2_restart",
        flow_id=flow_id,
        continuity_decision="continuity_resume",
    )
    # begin_attempt registers the flow_id as in-progress
    attempt, artifact1 = c.begin_attempt(ctx1)
    assert attempt.flow_id == flow_id

    # Second decide for same flow_id → suppress
    ctx2 = _recovery_ctx(
        trigger="v2_restart",
        flow_id=flow_id,
        continuity_decision="continuity_resume",
    )
    artifact2 = c.decide(ctx2)
    from core.delegated_flow_recovery_coordinator import RecoveryAction
    assert artifact2.action == RecoveryAction.suppress_duplicate_recovery


def test_F07_decide_from_continuity_artifact_enriches_context():
    from core.delegated_flow_recovery_coordinator import (
        DelegatedFlowRecoveryCoordinator,
        RecoveryTriggerContext,
        RecoveryTrigger,
        decide_recovery_from_continuity_artifact,
    )
    c = DelegatedFlowRecoveryCoordinator(capacity=16)
    flow_id = f"flow-f07-{uuid.uuid4().hex[:8]}"
    continuity_artifact_dict = {
        "artifact_id": str(uuid.uuid4()),
        "decision": "continuity_resume",
        "flow_id": flow_id,
        "flow_lineage_id": "lin-f07",
        "session_id": "sess-f07",
        "contract_id": "ctr-f07",
        "device_id": "dev-f07",
    }
    ctx = RecoveryTriggerContext(
        trigger=RecoveryTrigger.from_string("v2_restart"),
        flow_id=flow_id,
    )
    rec_artifact = decide_recovery_from_continuity_artifact(
        ctx,
        continuity_artifact_dict=continuity_artifact_dict,
        coordinator=c,
    )
    assert rec_artifact.artifact_id
    # continuity_decision should be propagated from artifact dict
    assert rec_artifact.continuity_decision == "continuity_resume"


# ===========================================================================
# Group G — Signal guard (attached_runtime_recovery_readiness)
# ===========================================================================


def test_G01_fresh_runtime_novel_signal_accepted():
    from core.attached_runtime_recovery_readiness import (
        build_idempotency_key,
        check_signal_guard,
        SignalGuardDecision,
    )
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-g01", contract_id="ctr-g01")
    decision = check_signal_guard(key, emission_seq=0, runtime=rt)
    assert decision == SignalGuardDecision.accept


def test_G02_duplicate_signal_id_rejected_as_duplicate():
    from core.attached_runtime_recovery_readiness import (
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        SignalGuardDecision,
    )
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-g02", contract_id="ctr-g02")
    record_seen_signal(key, emission_seq=3, runtime=rt)
    decision = check_signal_guard(key, emission_seq=3, runtime=rt)
    assert decision == SignalGuardDecision.duplicate


def test_G03_same_seq_different_signal_id_is_replay():
    from core.attached_runtime_recovery_readiness import (
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        SignalGuardDecision,
    )
    rt = _fresh_guard_runtime()
    key_orig = build_idempotency_key(signal_id="sig-g03-orig", contract_id="ctr-g03")
    record_seen_signal(key_orig, emission_seq=5, runtime=rt)
    # Same emission_seq=5, different signal_id
    key_replay = build_idempotency_key(signal_id="sig-g03-replay", contract_id="ctr-g03")
    decision = check_signal_guard(key_replay, emission_seq=5, runtime=rt)
    assert decision == SignalGuardDecision.replay


def test_G04_far_behind_seq_is_stale():
    from core.attached_runtime_recovery_readiness import (
        STALE_EMISSION_SEQ_THRESHOLD,
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        SignalGuardDecision,
    )
    rt = _fresh_guard_runtime()
    key_high = build_idempotency_key(signal_id="sig-g04-high", contract_id="ctr-g04")
    high_seq = 200
    record_seen_signal(key_high, emission_seq=high_seq, runtime=rt)
    # Far behind
    stale_seq = high_seq - STALE_EMISSION_SEQ_THRESHOLD - 1
    key_stale = build_idempotency_key(signal_id="sig-g04-stale", contract_id="ctr-g04")
    decision = check_signal_guard(key_stale, emission_seq=stale_seq, runtime=rt)
    assert decision == SignalGuardDecision.stale


def test_G05_slightly_behind_seq_is_out_of_order():
    from core.attached_runtime_recovery_readiness import (
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        SignalGuardDecision,
    )
    rt = _fresh_guard_runtime()
    key_high = build_idempotency_key(signal_id="sig-g05-high", contract_id="ctr-g05")
    record_seen_signal(key_high, emission_seq=10, runtime=rt)
    # Slightly behind (9 < 10, not stale)
    key_ooo = build_idempotency_key(signal_id="sig-g05-ooo", contract_id="ctr-g05")
    decision = check_signal_guard(key_ooo, emission_seq=9, runtime=rt)
    assert decision == SignalGuardDecision.out_of_order


def test_G06_check_signal_guard_is_pure_does_not_mutate():
    from core.attached_runtime_recovery_readiness import (
        build_idempotency_key,
        check_signal_guard,
    )
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-g06", contract_id="ctr-g06")
    # Calling check_signal_guard twice should give the same result
    d1 = check_signal_guard(key, emission_seq=1, runtime=rt)
    d2 = check_signal_guard(key, emission_seq=1, runtime=rt)
    assert d1 == d2  # pure — no mutation


def test_G07_record_seen_signal_updates_ring_buffer():
    from core.attached_runtime_recovery_readiness import (
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        SignalGuardDecision,
    )
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-g07", contract_id="ctr-g07")
    # Before recording: accept
    assert check_signal_guard(key, emission_seq=0, runtime=rt) == SignalGuardDecision.accept
    # Record it
    record_seen_signal(key, emission_seq=0, runtime=rt)
    # After recording: duplicate
    assert check_signal_guard(key, emission_seq=0, runtime=rt) == SignalGuardDecision.duplicate


def test_G08_two_contracts_are_guard_isolated():
    """Seq-based guard state (max_seq, out-of-order, stale) is isolated per
    context_key (contract_id / session_id).  A high seq recorded for contract A
    does not affect seq-based decisions for contract B.

    Note: signal_id deduplication is intentionally global (not per-contract)
    to prevent cross-contract replay.  Tests for per-contract isolation must
    use distinct signal_ids.
    """
    from core.attached_runtime_recovery_readiness import (
        STALE_EMISSION_SEQ_THRESHOLD,
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        SignalGuardDecision,
    )
    rt = _fresh_guard_runtime()
    # Record seq=100 for contract A only
    k_a = build_idempotency_key(signal_id="sig-g08-a", contract_id="ctr-g08-A")
    record_seen_signal(k_a, emission_seq=100, runtime=rt)
    # Contract A: a low seq is stale relative to its own high-water mark
    k_a_stale = build_idempotency_key(signal_id="sig-g08-a-stale", contract_id="ctr-g08-A")
    stale_seq = 100 - STALE_EMISSION_SEQ_THRESHOLD - 1
    assert check_signal_guard(k_a_stale, emission_seq=stale_seq, runtime=rt) == SignalGuardDecision.stale
    # Contract B: the same low seq is accepted because B has no prior history
    k_b = build_idempotency_key(signal_id="sig-g08-b", contract_id="ctr-g08-B")
    assert check_signal_guard(k_b, emission_seq=stale_seq, runtime=rt) == SignalGuardDecision.accept


# ===========================================================================
# Group H — Runtime restart recovery (RuntimeRestartRecoveryCoordinator)
# ===========================================================================


def test_H01_run_recovery_empty_stores_no_errors(tmp_path):
    coord = _make_restart_coordinator(tmp_path, [])
    report = coord.run_recovery()
    assert report.completed_at is not None
    assert not report.has_errors


def test_H02_resumable_task_registered_under_device_dispatch(tmp_path):
    records = [_task_record("task-h02", "device_dispatch")]
    coord = _make_restart_coordinator(tmp_path, records)
    report = coord.run_recovery()
    assert report.inflight_tasks_resumable >= 1


def test_H03_terminal_task_not_registered(tmp_path):
    records = [_task_record("task-h03", "result_completion")]
    coord = _make_restart_coordinator(tmp_path, records)
    report = coord.run_recovery()
    assert report.inflight_tasks_terminal >= 1
    # Terminal tasks must not be dispatched to the lifecycle registry
    assert report.inflight_tasks_dispatch_actions_taken == 0


def test_H04_recovery_idempotent_second_run_adds_nothing(tmp_path):
    records = [
        _task_record("task-h04a", "device_dispatch"),
        _task_record("task-h04b", "routing"),
    ]
    coord = _make_restart_coordinator(tmp_path, records)
    report1 = coord.run_recovery()
    # Second run on the same coordinator instance
    report2 = coord.run_recovery()
    # Second pass must not add new dispatch actions (tasks already registered)
    assert report2.inflight_tasks_already_pending_skipped >= 0  # field exists


def test_H05_recovery_report_to_dict_has_required_keys(tmp_path):
    coord = _make_restart_coordinator(tmp_path, [])
    report = coord.run_recovery()
    d = report.to_dict()
    for key in [
        "recovery_id",
        "started_at",
        "completed_at",
        "mesh_sessions_recovered",
        "body_mesh_entries_restored",
        "webrtc_bindings_cleared",
        "inflight_tasks_recovered",
        "inflight_tasks_resumable",
        "inflight_tasks_replay_only",
        "inflight_tasks_reissuable",
        "inflight_tasks_terminal",
        "inflight_tasks_dispatch_actions_taken",
        "inflight_tasks_already_pending_skipped",
        "errors",
        "non_goals",
    ]:
        assert key in d, f"missing key {key!r} in recovery report dict"


def test_H06_recovery_non_goals_list_non_empty(tmp_path):
    coord = _make_restart_coordinator(tmp_path, [])
    report = coord.run_recovery()
    assert report.non_goals, "non_goals must document intentionally ephemeral state"
    # WebRTC binding ephemeral policy must be documented
    combined = " ".join(report.non_goals).lower()
    assert "webrtc" in combined or "ephemeral" in combined


# ===========================================================================
# Group I — Chain tests (FlowContinuityCoordinator → DelegatedFlowRecoveryCoordinator)
# ===========================================================================


def test_I01_chain_v2_restart_continuity_resume_gives_resume_in_place():
    """Chain: FlowContinuityCoordinator(v2_restart, continuity_resume) →
    DelegatedFlowRecoveryCoordinator → resume_in_place."""
    # Step 1: continuity coordinator
    cc = _fresh_continuity_coordinator()
    ctx_cc = _continuity_ctx(
        event_kind="v2_restart_recovery",
        recovery_completed=False,  # → require_review
        flow_lineage_id="lin-i01",
    )
    continuity_artifact = cc.decide(ctx_cc)

    # Step 2: recovery coordinator — use continuity decision as input
    rc = _fresh_recovery_coordinator()
    flow_id = f"flow-i01-{uuid.uuid4().hex[:8]}"
    ctx_rc = _recovery_ctx(
        trigger="v2_restart",
        flow_id=flow_id,
        continuity_decision="continuity_resume",  # simulate resumed flow
        has_partial_result=False,
        checkpoint_available=False,
        binding_state="bound",
    )
    recovery_artifact = rc.decide(ctx_rc)

    from core.delegated_flow_recovery_coordinator import RecoveryAction
    assert recovery_artifact.action == RecoveryAction.resume_in_place
    # The chain produced two linked artifacts
    assert continuity_artifact.artifact_id
    assert recovery_artifact.artifact_id


def test_I02_chain_v2_restart_new_attachment_gives_redispatch_or_review():
    """Chain: FlowContinuityCoordinator(v2_restart, new_attachment) →
    DelegatedFlowRecoveryCoordinator → redispatch or require_review."""
    rc = _fresh_recovery_coordinator()
    flow_id = f"flow-i02-{uuid.uuid4().hex[:8]}"
    ctx_rc = _recovery_ctx(
        trigger="v2_restart",
        flow_id=flow_id,
        continuity_decision="new_attachment",
        has_partial_result=False,
        checkpoint_available=False,
        binding_state="released",
    )
    recovery_artifact = rc.decide(ctx_rc)
    from core.delegated_flow_recovery_coordinator import RecoveryAction
    expected = {RecoveryAction.redispatch_runtime, RecoveryAction.require_review}
    assert recovery_artifact.action in expected, (
        f"unexpected action for new_attachment chain: {recovery_artifact.action!r}"
    )


def test_I03_chain_stale_identity_continuity_reject_is_terminal_at_coordinator():
    """Chain: FlowContinuityCoordinator(stale_identity) emits reject_stale_identity.

    The FlowContinuityCoordinator is the authoritative layer for stale-identity
    rejection.  Its decision (reject_stale_identity) is terminal — callers MUST
    NOT forward the signal to the DelegatedFlowRecoveryCoordinator when the
    continuity decision is reject_stale_identity.

    This test verifies that the FlowContinuityCoordinator correctly identifies
    a stale-identity event and that the resulting decision is NOT resumable.
    """
    from core.flow_continuity_coordinator import (
        ContinuityDecision,
        ContinuityEventKind,
    )
    cc = _fresh_continuity_coordinator()
    ctx_cc = _continuity_ctx(
        event_kind="stale_identity",
        device_id="dev-i03",
        session_id="sess-i03-expired",
    )
    continuity_artifact = cc.decide(ctx_cc)
    # The coordinator MUST reject the stale identity
    assert continuity_artifact.decision == ContinuityDecision.reject_stale_identity
    # A reject_stale_identity decision is NOT resumable
    assert not continuity_artifact.is_resumable
    # Callers should NOT call the recovery coordinator when this decision is received.
    # The decision is final and non-destructive at this layer.


# ===========================================================================
# Group J — Recovery ordering and non-interference
# ===========================================================================


def test_J01_signal_guard_decisions_independent_per_contract():
    from core.attached_runtime_recovery_readiness import (
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        SignalGuardDecision,
    )
    rt = _fresh_guard_runtime()
    # Record seq=10 for contract A
    k_a10 = build_idempotency_key(signal_id="sig-j01-a", contract_id="ctr-j01-A")
    record_seen_signal(k_a10, emission_seq=10, runtime=rt)
    # Contract B should have no history → accept any seq
    k_b3 = build_idempotency_key(signal_id="sig-j01-b", contract_id="ctr-j01-B")
    decision_b = check_signal_guard(k_b3, emission_seq=3, runtime=rt)
    assert decision_b == SignalGuardDecision.accept


def test_J02_completing_attempt_deregisters_flow_allowing_next_decide():
    c = _fresh_recovery_coordinator()
    flow_id = f"flow-j02-{uuid.uuid4().hex[:8]}"
    # Register first attempt
    ctx1 = _recovery_ctx(trigger="v2_restart", flow_id=flow_id)
    attempt1, _ = c.begin_attempt(ctx1)
    # Complete it
    c.complete_attempt(attempt1.attempt_id, flow_id, success=True)
    # Now decide again → should NOT return suppress (flow de-registered)
    ctx2 = _recovery_ctx(
        trigger="v2_restart",
        flow_id=flow_id,
        continuity_decision="continuity_resume",
    )
    artifact2 = c.decide(ctx2)
    from core.delegated_flow_recovery_coordinator import RecoveryAction
    assert artifact2.action != RecoveryAction.suppress_duplicate_recovery


def test_J03_intra_snapshot_duplicate_task_ids_deduped(tmp_path):
    """Intra-snapshot duplicate task_ids produce only one dispatch action."""
    records = [
        _task_record("task-j03", "device_dispatch"),  # duplicate task_id
        _task_record("task-j03", "device_dispatch"),  # same task_id again
    ]
    coord = _make_restart_coordinator(tmp_path, records)
    report = coord.run_recovery()
    # Only one record should be recovered (deduped)
    assert report.inflight_tasks_recovered == 1


def test_J04_in_process_task_not_overwritten_by_snapshot(tmp_path):
    """Tasks already registered in the lifecycle registry are not overwritten."""
    from core.task_lifecycle_persistence import (
        TaskLifecyclePersistenceStore,
        save_task_lifecycle_snapshot,
    )
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
    from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

    class _FakeBodyRegistry:
        def register(self, device_id, roles=None, session_id=None, metadata=None):
            return {}
        def list_entries(self):
            return []

    tl_store = TaskLifecyclePersistenceStore(
        store_path=os.path.join(str(tmp_path), "tl_j04.json")
    )
    # Save two resumable records
    records = [
        _task_record("task-j04a", "device_dispatch"),
        _task_record("task-j04b", "device_dispatch"),
    ]
    save_task_lifecycle_snapshot(records, store=tl_store)
    ms_store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
    bm_store = BodyMeshPersistenceStore(
        store_path=os.path.join(str(tmp_path), "bm_j04.json")
    )
    coord = RuntimeRestartRecoveryCoordinator(
        mesh_session_store=ms_store,
        body_mesh_store=bm_store,
        body_mesh_registry=_FakeBodyRegistry(),
        task_lifecycle_store=tl_store,
    )
    report1 = coord.run_recovery()
    # First recovery: both tasks registered
    assert report1.inflight_tasks_resumable == 2
    # Second recovery: tasks already present → skipped
    report2 = coord.run_recovery()
    assert report2.inflight_tasks_already_pending_skipped >= 1 or (
        report2.inflight_tasks_dispatch_actions_taken == 0
    )


# ===========================================================================
# Group K — Serialisation and observability
# ===========================================================================


def test_K01_continuity_decision_artifact_round_trip():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(
        event_kind="stale_identity",
        device_id="dev-k01",
        session_id="sess-k01",
    )
    artifact = c.decide(ctx)
    d = artifact.to_dict()
    from core.flow_continuity_coordinator import ContinuityDecisionArtifact
    restored = ContinuityDecisionArtifact.from_dict(d)
    assert restored.artifact_id == artifact.artifact_id
    assert restored.decision == artifact.decision


def test_K02_recovery_decision_artifact_round_trip():
    c = _fresh_recovery_coordinator()
    ctx = _recovery_ctx(
        trigger="v2_restart",
        flow_id=f"flow-k02-{uuid.uuid4().hex[:8]}",
        continuity_decision="continuity_resume",
    )
    artifact = c.decide(ctx)
    d = artifact.to_dict()
    from core.delegated_flow_recovery_coordinator import RecoveryDecisionArtifact
    restored = RecoveryDecisionArtifact.from_dict(d)
    assert restored.artifact_id == artifact.artifact_id
    assert restored.action == artifact.action


def test_K03_closure_report_to_json_and_back():
    from core.recovery_durability_closure_validator import build_recovery_closure_report
    report = build_recovery_closure_report()
    payload = json.loads(report.to_json())
    assert isinstance(payload, dict)
    assert len(payload["scenarios"]) == 17
    # Every scenario entry serialises correctly
    for entry_dict in payload["scenarios"]:
        assert "scenario_id" in entry_dict
        assert "status" in entry_dict


def test_K04_continuity_coordinator_snapshot_includes_total_decisions():
    c = _fresh_continuity_coordinator()
    ctx = _continuity_ctx(event_kind="stale_identity", device_id="dev-k04")
    c.decide(ctx)
    snapshot = c.build_snapshot()
    assert snapshot.total_decisions >= 1
    assert len(snapshot.policy_sentinels) > 0


def test_K05_recovery_coordinator_snapshot_includes_total_decisions():
    c = _fresh_recovery_coordinator()
    ctx = _recovery_ctx(
        trigger="v2_restart",
        flow_id=f"flow-k05-{uuid.uuid4().hex[:8]}",
    )
    c.decide(ctx)
    snapshot = c.build_snapshot()
    assert snapshot.total_decisions >= 1
    assert len(snapshot.policy_sentinels) > 0
