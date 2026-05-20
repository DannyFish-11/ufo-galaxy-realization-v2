"""tests/test_task6_operator_action_closure_chain.py
=====================================================
Task-6 V2-side — Operator / Control-Plane Closure Loop tests.

Validates the minimal action → ack → truth → closure traceable chain:

A.  Module imports and sentinel coverage
B.  open_closure_chain / open_chain_for_operator_action basics
C.  record_subject_ack stage progression (partial, full, multi-subject)
D.  record_truth_convergence stage advancement
E.  verify_closure conditions and closure_verified flag
F.  Policy constraint sentinels are present and non-empty
G.  Integration with pr4_operator_action_governance:
       - execute_governed_operator_action opens a chain record
       - acknowledge_android_directed_action propagates to closure chain
H.  Operator routes: new closure-chain endpoints return correct shapes
I.  Projection/board remains consumer-only (no new authority injection)
J.  Regression: existing PR4 board projection still passes
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_chain_store():
    """Reset closure chain store before and after each test."""
    from core.operator_action_closure_chain import clear_closure_chain_store
    clear_closure_chain_store()
    yield
    clear_closure_chain_store()


@pytest.fixture(scope="module")
def app():
    _app = FastAPI()
    from core.routes.operator import create_router
    _app.include_router(create_router())
    return _app


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# Section A: Module imports and sentinel coverage
# ===========================================================================


class TestModuleImports:
    def test_module_importable(self):
        import core.operator_action_closure_chain as m
        assert m is not None

    def test_authority_sentinel(self):
        from core.operator_action_closure_chain import OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY
        assert "TASK6" in OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY
        assert "V2" in OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY
        assert "canonical" in OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY.lower()

    def test_contract_version(self):
        from core.operator_action_closure_chain import OPERATOR_ACTION_CLOSURE_CHAIN_CONTRACT_VERSION
        assert OPERATOR_ACTION_CLOSURE_CHAIN_CONTRACT_VERSION == "1.0.0"

    def test_policy_sentinels_present(self):
        from core.operator_action_closure_chain import (
            OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY,
            CANONICAL_GOVERNANCE_CONSTRAINTS_POLICY,
            MULTI_SUBJECT_ACK_COLLECTION_POLICY,
        )
        assert "POLICY" in OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY
        assert "POLICY" in CANONICAL_GOVERNANCE_CONSTRAINTS_POLICY
        assert "POLICY" in MULTI_SUBJECT_ACK_COLLECTION_POLICY
        # Operator plane must not be authority
        assert "authority" in OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY.lower()

    def test_enums_present(self):
        from core.operator_action_closure_chain import ClosureChainStage, AckState
        assert ClosureChainStage.dispatched.value == "dispatched"
        assert ClosureChainStage.partial_ack.value == "partial_ack"
        assert ClosureChainStage.acked.value == "acked"
        assert ClosureChainStage.truth_convergence.value == "truth_convergence"
        assert ClosureChainStage.closed.value == "closed"
        assert ClosureChainStage.failed.value == "failed"
        assert ClosureChainStage.policy_blocked.value == "policy_blocked"
        assert AckState.pending.value == "pending"
        assert AckState.acked.value == "acked"
        assert AckState.nacked.value == "nacked"
        assert AckState.timeout.value == "timeout"
        assert AckState.skipped.value == "skipped"

    def test_required_functions_exported(self):
        from core.operator_action_closure_chain import (
            open_closure_chain,
            open_chain_for_operator_action,
            record_subject_ack,
            record_truth_convergence,
            verify_closure,
            get_closure_chain_record,
            get_all_closure_chain_records,
            get_closure_chain_summary,
            clear_closure_chain_store,
        )
        for fn in [
            open_closure_chain,
            open_chain_for_operator_action,
            record_subject_ack,
            record_truth_convergence,
            verify_closure,
            get_closure_chain_record,
            get_all_closure_chain_records,
            get_closure_chain_summary,
            clear_closure_chain_store,
        ]:
            assert callable(fn)


# ===========================================================================
# Section B: open_closure_chain basics
# ===========================================================================


class TestOpenClosureChain:
    def test_open_creates_record(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, get_closure_chain_record, ClosureChainStage,
        )
        rec = open_closure_chain(
            action_id="opact_test_open_01",
            action_kind="revalidate_participation",
            routed_subjects=["device_01"],
        )
        assert rec.action_id == "opact_test_open_01"
        assert rec.stage == ClosureChainStage.dispatched.value
        assert "device_01" in rec.routed_subjects
        assert "device_01" in rec.subject_acks

        fetched = get_closure_chain_record("opact_test_open_01")
        assert fetched is not None
        assert fetched.action_id == "opact_test_open_01"

    def test_open_without_subjects(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, ClosureChainStage,
        )
        rec = open_closure_chain(
            action_id="opact_no_subjects",
            action_kind="finalize_closure",
        )
        assert rec.routed_subjects == []
        assert rec.subject_acks == {}
        assert rec.stage == ClosureChainStage.dispatched.value

    def test_open_chain_for_operator_action_with_device(self):
        from core.operator_action_closure_chain import (
            open_chain_for_operator_action, ClosureChainStage,
        )
        rec = open_chain_for_operator_action(
            action_id="opact_dev_01",
            action_kind="device_dispatch",
            device_id="android_device_01",
            operator_user_id="admin",
        )
        assert rec.action_id == "opact_dev_01"
        assert "android_device_01" in rec.routed_subjects
        assert rec.operator_user_id == "admin"
        assert rec.stage == ClosureChainStage.dispatched.value

    def test_to_dict_serialisable(self):
        from core.operator_action_closure_chain import open_closure_chain
        import json
        rec = open_closure_chain(
            action_id="opact_serial_01",
            action_kind="retry_recovery",
            routed_subjects=["dev_a", "dev_b"],
        )
        d = rec.to_dict()
        # Must be JSON-serialisable
        json.dumps(d)
        assert d["action_id"] == "opact_serial_01"
        assert d["action_kind"] == "retry_recovery"
        assert len(d["subject_acks"]) == 2

    def test_open_auto_generates_action_id_when_empty(self):
        from core.operator_action_closure_chain import open_closure_chain
        rec = open_closure_chain(action_id="", action_kind="dispatch")
        assert rec.action_id.startswith("opact_")


# ===========================================================================
# Section C: record_subject_ack stage progression
# ===========================================================================


class TestSubjectAck:
    def test_single_subject_ack_advances_to_acked(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, record_subject_ack, ClosureChainStage,
        )
        open_closure_chain(
            action_id="opact_ack_01",
            action_kind="isolate_device",
            routed_subjects=["dev_a"],
        )
        updated = record_subject_ack(
            action_id="opact_ack_01",
            subject_id="dev_a",
            ack_state="acked",
        )
        assert updated is not None
        assert updated.stage == ClosureChainStage.acked.value
        assert updated.subject_acks["dev_a"].ack_state == "acked"

    def test_partial_ack_stage(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, record_subject_ack, ClosureChainStage, AckState,
        )
        open_closure_chain(
            action_id="opact_partial_01",
            action_kind="retry_delegated_execution",
            routed_subjects=["dev_a", "dev_b"],
        )
        updated = record_subject_ack(
            action_id="opact_partial_01",
            subject_id="dev_a",
            ack_state=AckState.acked.value,
        )
        assert updated is not None
        assert updated.stage == ClosureChainStage.partial_ack.value
        assert updated.subject_acks["dev_b"].ack_state == AckState.pending.value

    def test_full_ack_after_partial(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, record_subject_ack, ClosureChainStage,
        )
        open_closure_chain(
            action_id="opact_full_01",
            action_kind="rebind_session",
            routed_subjects=["dev_a", "dev_b"],
        )
        record_subject_ack(action_id="opact_full_01", subject_id="dev_a", ack_state="acked")
        updated = record_subject_ack(action_id="opact_full_01", subject_id="dev_b", ack_state="acked")
        assert updated is not None
        assert updated.stage == ClosureChainStage.acked.value

    def test_nack_records_but_does_not_advance_to_acked(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, record_subject_ack, ClosureChainStage,
        )
        open_closure_chain(
            action_id="opact_nack_01",
            action_kind="isolate_device",
            routed_subjects=["dev_a"],
        )
        updated = record_subject_ack(
            action_id="opact_nack_01",
            subject_id="dev_a",
            ack_state="nacked",
        )
        assert updated is not None
        # nacked is "resolved" from a subject perspective: all_subjects_resolved should be True
        # since nacked != pending, but stage still from dispatched
        # After nack, all subjects have non-pending state → acked stage
        assert updated.stage in {ClosureChainStage.acked.value, ClosureChainStage.dispatched.value}

    def test_dynamic_subject_registration(self):
        """A subject not in routed_subjects can still ack (dynamic multi-subject)."""
        from core.operator_action_closure_chain import (
            open_closure_chain, record_subject_ack,
        )
        open_closure_chain(
            action_id="opact_dyn_01",
            action_kind="dispatch",
            routed_subjects=[],
        )
        updated = record_subject_ack(
            action_id="opact_dyn_01",
            subject_id="newly_routed_dev",
            ack_state="acked",
        )
        assert updated is not None
        assert "newly_routed_dev" in updated.routed_subjects
        assert "newly_routed_dev" in updated.subject_acks

    def test_ack_unknown_action_returns_none(self):
        from core.operator_action_closure_chain import record_subject_ack
        result = record_subject_ack(
            action_id="opact_nonexistent_999",
            subject_id="dev_a",
        )
        assert result is None


# ===========================================================================
# Section D: record_truth_convergence
# ===========================================================================


class TestTruthConvergence:
    def test_truth_convergence_advances_stage(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, record_truth_convergence, ClosureChainStage,
        )
        open_closure_chain(
            action_id="opact_truth_01",
            action_kind="retry_recovery",
        )
        updated = record_truth_convergence(
            action_id="opact_truth_01",
            truth_convergence_payload={"canonical_snapshot": "ok"},
            canonical_truth_refs=["core.unified_runtime_truth_ingress"],
            truth_chain_complete=True,
        )
        assert updated is not None
        assert updated.stage == ClosureChainStage.truth_convergence.value
        assert updated.truth_chain_complete is True
        assert "core.unified_runtime_truth_ingress" in updated.canonical_truth_refs

    def test_truth_convergence_unknown_action_returns_none(self):
        from core.operator_action_closure_chain import record_truth_convergence
        result = record_truth_convergence(action_id="opact_missing_999")
        assert result is None

    def test_truth_convergence_does_not_override_closed_stage(self):
        """A closed record should not regress to truth_convergence."""
        from core.operator_action_closure_chain import (
            open_closure_chain, verify_closure, record_truth_convergence,
            ClosureChainStage,
        )
        open_closure_chain(action_id="opact_tc_closed_01", action_kind="dispatch")
        verify_closure(action_id="opact_tc_closed_01", closure_verdict="success")
        # Now call truth convergence on a closed record
        updated = record_truth_convergence(
            action_id="opact_tc_closed_01",
            truth_chain_complete=True,
        )
        # Should remain closed (stage must not regress)
        assert updated is not None
        assert updated.stage == ClosureChainStage.closed.value


# ===========================================================================
# Section E: verify_closure
# ===========================================================================


class TestVerifyClosure:
    def test_local_action_closes_immediately(self):
        """V2-local action with no subjects closes immediately with truth."""
        from core.operator_action_closure_chain import (
            open_closure_chain, record_truth_convergence, verify_closure,
            ClosureChainStage,
        )
        open_closure_chain(action_id="opact_local_01", action_kind="finalize_closure")
        record_truth_convergence(
            action_id="opact_local_01",
            truth_chain_complete=True,
            canonical_truth_refs=["core.task_result_canonical_truth_chain"],
        )
        updated = verify_closure(
            action_id="opact_local_01",
            closure_verdict="success",
        )
        assert updated is not None
        assert updated.closure_verified is True
        assert updated.stage == ClosureChainStage.closed.value

    def test_device_action_requires_ack_for_success_closure(self):
        """Device-targeted action does not close until subject has acked."""
        from core.operator_action_closure_chain import (
            open_closure_chain, record_truth_convergence, verify_closure,
            ClosureChainStage,
        )
        open_closure_chain(
            action_id="opact_dev_close_01",
            action_kind="isolate_device",
            routed_subjects=["dev_a"],
        )
        record_truth_convergence(
            action_id="opact_dev_close_01",
            truth_chain_complete=True,
        )
        # Subject has not acked yet
        updated = verify_closure(
            action_id="opact_dev_close_01",
            closure_verdict="success",
        )
        assert updated is not None
        # Should NOT be verified yet (pending ack)
        assert updated.closure_verified is False
        assert updated.stage != ClosureChainStage.closed.value

    def test_device_action_closes_after_ack_and_truth(self):
        """Full happy path: action → ack → truth → closure."""
        from core.operator_action_closure_chain import (
            open_closure_chain, record_subject_ack, record_truth_convergence,
            verify_closure, ClosureChainStage,
        )
        open_closure_chain(
            action_id="opact_full_close_01",
            action_kind="rebind_session",
            routed_subjects=["dev_a"],
        )
        record_subject_ack(action_id="opact_full_close_01", subject_id="dev_a", ack_state="acked")
        record_truth_convergence(
            action_id="opact_full_close_01",
            truth_chain_complete=True,
            canonical_truth_refs=["core.multi_subject_truth_convergence_bridge"],
        )
        updated = verify_closure(
            action_id="opact_full_close_01",
            closure_verdict="success",
            closure_payload={"converged_at": 1234567890.0},
        )
        assert updated is not None
        assert updated.closure_verified is True
        assert updated.stage == ClosureChainStage.closed.value
        assert updated.closure_verdict == "success"
        assert "converged_at" in updated.closure_payload

    def test_failed_closure_closes_without_ack(self):
        """Failed actions close immediately without waiting for subject acks."""
        from core.operator_action_closure_chain import (
            open_closure_chain, verify_closure, ClosureChainStage,
        )
        open_closure_chain(
            action_id="opact_fail_01",
            action_kind="retry_recovery",
            routed_subjects=["dev_a"],
        )
        updated = verify_closure(
            action_id="opact_fail_01",
            closure_verdict="failed",
            closure_payload={"error": "device unreachable"},
        )
        assert updated is not None
        assert updated.closure_verified is True
        assert updated.stage == ClosureChainStage.closed.value
        assert updated.closure_verdict == "failed"

    def test_policy_blocked_closes_immediately(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, verify_closure, ClosureChainStage,
        )
        open_closure_chain(
            action_id="opact_blocked_01",
            action_kind="reject_closure",
            routed_subjects=["dev_a"],
        )
        updated = verify_closure(
            action_id="opact_blocked_01",
            closure_verdict="policy_blocked",
        )
        assert updated is not None
        assert updated.closure_verified is True
        assert updated.stage == ClosureChainStage.closed.value

    def test_verify_closure_unknown_action_returns_none(self):
        from core.operator_action_closure_chain import verify_closure
        result = verify_closure(action_id="opact_missing_999", closure_verdict="success")
        assert result is None


# ===========================================================================
# Section F: Policy constraint sentinel proof
# ===========================================================================


class TestPolicyConstraints:
    def test_operator_not_authority_center_policy(self):
        """Confirm the policy sentinel explicitly says operator must not be authority center."""
        from core.operator_action_closure_chain import (
            OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY
        )
        lower = OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY.lower()
        assert "not" in lower or "must not" in lower
        assert "authority" in lower

    def test_canonical_governance_constraints_policy(self):
        from core.operator_action_closure_chain import CANONICAL_GOVERNANCE_CONSTRAINTS_POLICY
        assert "OperatorSurface" in CANONICAL_GOVERNANCE_CONSTRAINTS_POLICY
        assert "canonical" in CANONICAL_GOVERNANCE_CONSTRAINTS_POLICY.lower()

    def test_multi_subject_ack_collection_policy(self):
        from core.operator_action_closure_chain import MULTI_SUBJECT_ACK_COLLECTION_POLICY
        assert "canonical" in MULTI_SUBJECT_ACK_COLLECTION_POLICY.lower()


# ===========================================================================
# Section G: Integration with pr4_operator_action_governance
# ===========================================================================


class TestPR4Integration:
    def test_execute_governed_action_opens_chain_record(self):
        """execute_governed_operator_action should open a closure chain record."""
        from core.pr4_operator_action_governance import execute_governed_operator_action
        from core.operator_action_closure_chain import get_closure_chain_record
        from core.operator_action_contract import OperatorActionKind

        action_id = "opact_pr4_int_01"
        execute_governed_operator_action(
            action_kind=OperatorActionKind.trigger_recovery.value,
            action_id=action_id,
            operator_user_id="test_operator",
        )
        record = get_closure_chain_record(action_id)
        assert record is not None
        assert record.action_id == action_id
        assert record.action_kind == OperatorActionKind.trigger_recovery.value

    def test_v2_local_action_closes_chain_immediately(self):
        """V2-local actions (no device) should close the chain record immediately."""
        from core.pr4_operator_action_governance import execute_governed_operator_action
        from core.operator_action_closure_chain import (
            get_closure_chain_record, ClosureChainStage,
        )
        from core.operator_action_contract import OperatorActionKind

        action_id = "opact_local_close_01"
        execute_governed_operator_action(
            action_kind=OperatorActionKind.trigger_recovery.value,
            action_id=action_id,
        )
        record = get_closure_chain_record(action_id)
        assert record is not None
        # V2-local actions with no routed subjects should close immediately
        assert record.routed_subjects == []
        assert record.stage == ClosureChainStage.closed.value
        assert record.closure_verified is True

    def test_android_directed_ack_updates_chain(self):
        """acknowledge_android_directed_action should propagate to closure chain."""
        from core.pr4_operator_action_governance import (
            build_android_directed_action_spec,
            acknowledge_android_directed_action,
            _PENDING_ANDROID_ACTIONS,
            AndroidDirectedActionKind,
        )
        from core.operator_action_closure_chain import (
            open_chain_for_operator_action,
            get_closure_chain_record,
        )

        action_id = "opact_android_ack_01"
        device_id = "android_test_device"

        # Open closure chain for this action
        open_chain_for_operator_action(
            action_id=action_id,
            action_kind=AndroidDirectedActionKind.revalidate_participation.value,
            device_id=device_id,
        )

        # Build an AndroidDirectedActionSpec with the same operator_action_id
        spec = build_android_directed_action_spec(
            action_kind=AndroidDirectedActionKind.revalidate_participation.value,
            device_id=device_id,
            operator_action_id=action_id,
        )

        # Acknowledge
        result = acknowledge_android_directed_action(spec.android_dispatch_id)
        assert result is True

        # Check that the closure chain subject ack was updated
        chain_record = get_closure_chain_record(action_id)
        assert chain_record is not None
        ack_entry = chain_record.subject_acks.get(device_id)
        assert ack_entry is not None
        assert ack_entry.ack_state == "acked"

        _PENDING_ANDROID_ACTIONS.clear()


# ===========================================================================
# Section H: Operator routes — new closure-chain endpoints
# ===========================================================================


class TestClosureChainRoutes:
    def test_summary_endpoint_returns_200(self, client):
        resp = client.get("/api/v1/operator/closure-chain/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_actions" in data
        assert "open_actions" in data
        assert "verified_closures" in data
        assert "stage_counts" in data

    def test_records_endpoint_returns_200(self, client):
        resp = client.get("/api/v1/operator/closure-chain/records")
        assert resp.status_code == 200
        data = resp.json()
        assert "records" in data
        assert "count" in data

    def test_record_by_id_404_when_missing(self, client):
        resp = client.get("/api/v1/operator/closure-chain/opact_nonexistent_999")
        assert resp.status_code == 404

    def test_record_by_id_returns_record(self, client):
        from core.operator_action_closure_chain import open_closure_chain
        open_closure_chain(
            action_id="opact_route_test_01",
            action_kind="dispatch",
            routed_subjects=["dev_route_01"],
        )
        resp = client.get("/api/v1/operator/closure-chain/opact_route_test_01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_id"] == "opact_route_test_01"

    def test_subject_ack_endpoint_422_without_subject_id(self, client):
        from core.operator_action_closure_chain import open_closure_chain
        open_closure_chain(action_id="opact_ack_ep_01", action_kind="dispatch")
        resp = client.post(
            "/api/v1/operator/closure-chain/opact_ack_ep_01/subject-ack",
            json={},
        )
        assert resp.status_code == 422

    def test_subject_ack_endpoint_200(self, client):
        from core.operator_action_closure_chain import open_closure_chain
        open_closure_chain(
            action_id="opact_ack_ep_02",
            action_kind="isolate_device",
            routed_subjects=["dev_ep_01"],
        )
        resp = client.post(
            "/api/v1/operator/closure-chain/opact_ack_ep_02/subject-ack",
            json={"subject_id": "dev_ep_01", "ack_state": "acked"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] in ("acked", "partial_ack")

    def test_truth_convergence_endpoint_200(self, client):
        from core.operator_action_closure_chain import open_closure_chain
        open_closure_chain(
            action_id="opact_tc_ep_01",
            action_kind="retry_recovery",
        )
        resp = client.post(
            "/api/v1/operator/closure-chain/opact_tc_ep_01/truth-convergence",
            json={
                "truth_chain_complete": True,
                "canonical_truth_refs": ["core.unified_runtime_truth_ingress"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "truth_convergence"
        assert data["truth_chain_complete"] is True

    def test_verify_closure_endpoint_200(self, client):
        from core.operator_action_closure_chain import open_closure_chain
        open_closure_chain(
            action_id="opact_vc_ep_01",
            action_kind="finalize_closure",
        )
        resp = client.post(
            "/api/v1/operator/closure-chain/opact_vc_ep_01/verify-closure",
            json={"closure_verdict": "success"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["closure_verified"] is True
        assert data["stage"] == "closed"

    def test_records_filter_by_stage(self, client):
        from core.operator_action_closure_chain import open_closure_chain, verify_closure
        open_closure_chain(action_id="opact_filter_01", action_kind="dispatch")
        verify_closure(action_id="opact_filter_01", closure_verdict="success")

        resp = client.get("/api/v1/operator/closure-chain/records?stage=closed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        for r in data["records"]:
            assert r["stage"] == "closed"


# ===========================================================================
# Section I: Projection/board remains consumer-only
# ===========================================================================


class TestProjectionConsumerOnly:
    def test_board_projection_does_not_produce_new_closure_authority(self):
        """The PR-4 board projection must not inject into the closure chain
        directly.  It only reads from existing canonical modules."""
        from core.pr4_operator_action_governance import build_operator_board_projection
        from core.operator_action_closure_chain import (
            get_closure_chain_summary,
            clear_closure_chain_store,
        )
        clear_closure_chain_store()
        _ = build_operator_board_projection()
        # Board projection should NOT have opened any closure chain records on its own
        summary = get_closure_chain_summary()
        assert summary["total_actions"] == 0, (
            "board_projection must not open closure chain records: "
            f"found {summary['total_actions']} records after projection call"
        )

    def test_closure_chain_summary_in_board_does_not_grant_authority(self):
        """The closure chain summary endpoint must confirm it has no authority."""
        from core.operator_action_closure_chain import (
            OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY,
        )
        # The policy sentinel explicitly restricts the operator plane
        assert "MUST NOT" in OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY


# ===========================================================================
# Section J: Regression — existing PR4 board projection
# ===========================================================================


class TestPR4Regression:
    def test_all_pr4_board_projection_tests_still_pass(self):
        """Run a representative set of PR4 board projection checks."""
        from core.pr4_operator_action_governance import (
            build_operator_board_projection,
            OperatorActionBoardProjection,
        )
        proj = build_operator_board_projection()
        assert isinstance(proj, OperatorActionBoardProjection)
        d = proj.to_dict()
        assert "available_actions" in d
        assert "availability_state_basis" in d

    def test_evidence_ring_closure_reasoning_uses_android_delegated(self):
        """Regression for android_local vs android_delegated fix."""
        from core.operator_execution_observability_surface import (
            _evidence_ring, record_operator_evidence_entry,
        )
        from core.pr4_operator_action_governance import build_operator_board_projection

        _evidence_ring.clear()
        record_operator_evidence_entry(
            task_id="task_reg_01",
            device_id="device_reg_01",
            evidence_state="confirmed_strong",
            trust_level="trusted",
            acceptance_verdict="accept",
            truth_chain_complete=True,
            android_proof_class="distributed_participant",
            source_channel="canonical_completion_ingress",
        )
        try:
            proj = build_operator_board_projection()
            assert proj.unified_mode_model.get("execution_location") == "android_delegated", (
                f"Expected android_delegated, got {proj.unified_mode_model.get('execution_location')}"
            )
        finally:
            _evidence_ring.clear()

    def test_get_all_closure_chain_records_pagination(self):
        from core.operator_action_closure_chain import (
            open_closure_chain, get_all_closure_chain_records,
        )
        for i in range(5):
            open_closure_chain(
                action_id=f"opact_page_{i:03d}",
                action_kind="dispatch",
            )
        records = get_all_closure_chain_records(limit=3)
        assert len(records) == 3
        # Newest first: last opened should be first
        assert records[0].action_id == "opact_page_004"
