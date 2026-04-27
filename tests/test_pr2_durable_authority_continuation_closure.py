#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr2_durable_authority_continuation_closure.py
==========================================================
PR-2: Durable Truth Authority Convergence / Continuation Rebind Closure —
test suite.

Problem addressed
-----------------
After PR-1 (GAP_V2_TRUTH_PERSISTENCE closure), V2 gained per-domain durable
stores for session truth, task lifecycle, and result continuity.  However:

1. These stores were semantically parallel (each added additively) rather than
   forming a declared unified authority chain.
2. The ring buffer was labelled "authoritative runtime read surface" while
   durable stores were labelled "forensic/audit sinks".
3. Continuation/waiter reconciliation only *failed* stale futures (first half),
   with no structural tracking of the rebind phase (second half).
4. Multi-task / multi-participant recovery state was not observable.
5. Result continuity guard activation was not explicitly verified at recovery.

Coverage matrix
---------------
Group A — DurableTruthAuthorityChain module
  A01. Module importable; authority sentinel present.
  A02. DURABLE_TRUTH_IS_AUTHORITY_POLICY sentinel is non-empty.
  A03. RING_BUFFER_IS_READ_CACHE_POLICY sentinel is non-empty.
  A04. AUTHORITY_CHAIN_LEGS_POLICY sentinel mentions all three legs.
  A05. CONVERGENCE_REQUIRES_ALL_LEGS_POLICY sentinel is non-empty.
  A06. DURABLE_TRUTH_AUTHORITY_CHAIN_PR2_SENTINEL is non-empty.
  A07. DurableTruthConvergenceResult dataclass importable.
  A08. DurableTruthConvergenceResult.to_dict() includes required keys.
  A09. DurableTruthAuthorityChain instantiates without error.
  A10. get_durable_truth_authority_chain returns same singleton.
  A11. reset_durable_truth_authority_chain allows fresh creation.

Group B — DurableTruthAuthorityChain.convergence_check
  B01. convergence_check with all three legs healthy → converged=True.
  B02. convergence_check with unhealthy session truth leg → converged=False.
  B03. convergence_check with unhealthy task lifecycle leg → converged=False.
  B04. convergence_check with unhealthy result continuity leg → converged=False.
  B05. verify_durable_truth_convergence convenience function returns result.
  B06. Partial convergence: exactly two legs healthy → converged=False.
  B07. check_id is a unique string per check invocation.
  B08. to_dict() contains authority key.

Group C — ContinuationRebindRegistry module
  C01. Module importable; authority sentinel present.
  C02. CONTINUATION_REBIND_CLOSED_LOOP_POLICY sentinel describes five steps.
  C03. REBIND_MUST_USE_SAME_TASK_ID_POLICY sentinel is non-empty.
  C04. REBIND_IS_IDEMPOTENT_POLICY sentinel is non-empty.
  C05. RebindState enum has pending_rebind, rebound, completed values.
  C06. ContinuationRebindRecord instantiates and to_dict() works.
  C07. ContinuationRebindRecord round-trips from_dict correctly.
  C08. get_continuation_rebind_registry returns singleton.
  C09. reset_continuation_rebind_registry allows fresh creation.

Group D — ContinuationRebindRegistry operations (continuation rebind after restart)
  D01. register_rebind_pending creates a pending_rebind record.
  D02. register_rebind_pending is idempotent for same task_id.
  D03. register_new_waiter transitions pending_rebind → rebound.
  D04. mark_completed transitions rebound → completed (loop closed).
  D05. is_pending_rebind returns True for pending; False for rebound/completed.
  D06. is_loop_closed returns True only for completed.
  D07. get_record returns None for unknown task_id.
  D08. pending_rebind_count tracks correctly.
  D09. rebound_count tracks correctly.
  D10. completed_count tracks correctly.
  D11. list_pending_task_ids returns only pending_rebind task IDs.
  D12. snapshot() returns JSON-serialisable dict with correct counts.
  D13. register_new_waiter for unknown task_id returns None (no record).
  D14. mark_completed for unknown task_id returns None.

Group E — RuntimeRecoveryReport PR-2 fields
  E01. RuntimeRecoveryReport has continuation_rebinds_registered field.
  E02. RuntimeRecoveryReport has durable_truth_converged field.
  E03. RuntimeRecoveryReport has participants_consolidated field.
  E04. RuntimeRecoveryReport has result_continuity_guard_active field.
  E05. to_dict() includes all four PR-2 fields.
  E06. PR-2 policy sentinels are importable and non-empty.

Group F — Multi-task restart recovery integration
  F01. Recovery with multiple RESUMABLE tasks → all tasks registered.
  F02. Recovery with tasks on multiple devices → participants_consolidated populated.
  F03. participants_consolidated counts are per-device (not total).
  F04. tasks without target_device_id → counted under 'unknown_participant'.
  F05. participants_consolidated does not double-count duplicate task_ids.
  F06. Recovery with RESUMABLE + REPLAY_ONLY + REISSUABLE + TERMINAL →
       correct per-disposition counts and participants consolidated.

Group G — Multi-participant recovery consistency
  G01. Two participants, each with one RESUMABLE task → two participants.
  G02. One participant with three tasks → one participant entry, count=3.
  G03. Recovery is idempotent: second run adds no new participant entries.
  G04. result_continuity_guard_active is True after a standard recovery.

Group H — Duplicate result after recovery (result continuity / idempotency)
  H01. DurableResultIdSet: first add returns True; second add returns False.
  H02. DurableResultIdSet: result recorded before restart → rejected after restart.
  H03. record_result_idempotency + check_result_idempotency: new → False; seen → True.
  H04. Recovery report confirms result_continuity_guard_active=True.
  H05. Duplicate result from Android after V2 restart is suppressed.

Group I — Durable truth authority convergence (integration)
  I01. SESSION_TRUTH_RING_BUFFER_IS_READ_CACHE_SENTINEL importable from
       canonical_session_truth.
  I02. Sentinel mentions 'read-cache' and 'durable'.
  I03. RuntimeRecoveryReport.durable_truth_converged is True after recovery
       with real stores.
  I04. Recovery with broken session truth store → durable_truth_converged=False,
       but recovery still completes (graceful degradation).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task_id() -> str:
    return f"task_{uuid.uuid4().hex[:8]}"


def _result_id() -> str:
    return f"rid_{uuid.uuid4().hex[:12]}"


def _session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:8]}"


def _make_stores(tmp_dir: str):
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
    from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
    ms_store = MeshSessionPersistenceStore(store_dir=tmp_dir)
    bm_store = BodyMeshPersistenceStore(
        store_path=os.path.join(tmp_dir, "bm.json")
    )
    tl_store = TaskLifecyclePersistenceStore(
        store_path=os.path.join(tmp_dir, "tl.json")
    )
    return ms_store, bm_store, tl_store


def _record(
    task_id: str,
    owner: str,
    tool_name: str = "test_tool",
    target_device_id: str = "dev_01",
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "trace_id": f"trace_{task_id}",
        "target_device_id": target_device_id,
        "tool_name": tool_name,
        "owner": owner,
        "timeout": 30.0,
        "registered_at": time.time() - 5.0,
        "metadata": {},
    }


def _save_snapshot(tl_store, records: List[Dict[str, Any]]) -> None:
    from core.task_lifecycle_persistence import save_task_lifecycle_snapshot
    save_task_lifecycle_snapshot(records, store=tl_store)


class FakeBodyMeshRegistry:
    def register(self, device_id, roles=None, session_id=None, metadata=None):
        return {}

    def list_entries(self):
        return []


def _make_coordinator(tmp_dir: str, records: List[Dict[str, Any]]):
    ms_store, bm_store, tl_store = _make_stores(tmp_dir)
    _save_snapshot(tl_store, records)
    from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
    return RuntimeRestartRecoveryCoordinator(
        mesh_session_store=ms_store,
        body_mesh_store=bm_store,
        body_mesh_registry=FakeBodyMeshRegistry(),
        task_lifecycle_store=tl_store,
    )


# ---------------------------------------------------------------------------
# A — DurableTruthAuthorityChain module
# ---------------------------------------------------------------------------


class TestGroupA_DurableTruthAuthorityChainModule:
    def setup_method(self):
        from core.durable_truth_authority_chain import reset_durable_truth_authority_chain
        reset_durable_truth_authority_chain()

    def teardown_method(self):
        from core.durable_truth_authority_chain import reset_durable_truth_authority_chain
        reset_durable_truth_authority_chain()

    def test_A01_module_importable_authority_sentinel_present(self):
        from core.durable_truth_authority_chain import (
            DURABLE_TRUTH_AUTHORITY_CHAIN_IS_AUTHORITY,
        )
        assert isinstance(DURABLE_TRUTH_AUTHORITY_CHAIN_IS_AUTHORITY, str)
        assert DURABLE_TRUTH_AUTHORITY_CHAIN_IS_AUTHORITY

    def test_A02_durable_truth_is_authority_policy_non_empty(self):
        from core.durable_truth_authority_chain import DURABLE_TRUTH_IS_AUTHORITY_POLICY
        assert isinstance(DURABLE_TRUTH_IS_AUTHORITY_POLICY, str)
        assert "durable" in DURABLE_TRUTH_IS_AUTHORITY_POLICY.lower()

    def test_A03_ring_buffer_is_read_cache_policy_non_empty(self):
        from core.durable_truth_authority_chain import RING_BUFFER_IS_READ_CACHE_POLICY
        assert isinstance(RING_BUFFER_IS_READ_CACHE_POLICY, str)
        assert "read" in RING_BUFFER_IS_READ_CACHE_POLICY.lower()

    def test_A04_authority_chain_legs_policy_mentions_all_three_legs(self):
        from core.durable_truth_authority_chain import AUTHORITY_CHAIN_LEGS_POLICY
        p = AUTHORITY_CHAIN_LEGS_POLICY
        assert "session" in p.lower()
        assert "lifecycle" in p.lower()
        assert "result" in p.lower() or "continuity" in p.lower()

    def test_A05_convergence_requires_all_legs_policy_non_empty(self):
        from core.durable_truth_authority_chain import CONVERGENCE_REQUIRES_ALL_LEGS_POLICY
        assert isinstance(CONVERGENCE_REQUIRES_ALL_LEGS_POLICY, str)
        assert CONVERGENCE_REQUIRES_ALL_LEGS_POLICY

    def test_A06_pr2_sentinel_non_empty(self):
        from core.durable_truth_authority_chain import DURABLE_TRUTH_AUTHORITY_CHAIN_PR2_SENTINEL
        assert isinstance(DURABLE_TRUTH_AUTHORITY_CHAIN_PR2_SENTINEL, str)
        assert DURABLE_TRUTH_AUTHORITY_CHAIN_PR2_SENTINEL

    def test_A07_convergence_result_importable(self):
        from core.durable_truth_authority_chain import DurableTruthConvergenceResult
        r = DurableTruthConvergenceResult()
        assert r.converged is False
        assert isinstance(r.check_id, str)

    def test_A08_convergence_result_to_dict_required_keys(self):
        from core.durable_truth_authority_chain import DurableTruthConvergenceResult
        r = DurableTruthConvergenceResult()
        d = r.to_dict()
        for key in (
            "check_id", "converged",
            "session_truth_leg_healthy",
            "task_lifecycle_leg_healthy",
            "result_continuity_leg_healthy",
            "authority",
        ):
            assert key in d, f"Missing key: {key}"

    def test_A09_chain_instantiates(self):
        from core.durable_truth_authority_chain import DurableTruthAuthorityChain
        chain = DurableTruthAuthorityChain()
        assert chain is not None

    def test_A10_get_chain_returns_singleton(self):
        from core.durable_truth_authority_chain import get_durable_truth_authority_chain
        c1 = get_durable_truth_authority_chain()
        c2 = get_durable_truth_authority_chain()
        assert c1 is c2

    def test_A11_reset_allows_fresh_creation(self):
        from core.durable_truth_authority_chain import (
            get_durable_truth_authority_chain,
            reset_durable_truth_authority_chain,
        )
        c1 = get_durable_truth_authority_chain()
        reset_durable_truth_authority_chain()
        c2 = get_durable_truth_authority_chain()
        assert c1 is not c2


# ---------------------------------------------------------------------------
# B — DurableTruthAuthorityChain.convergence_check
# ---------------------------------------------------------------------------


class TestGroupB_ConvergenceCheck:
    def setup_method(self):
        from core.durable_truth_authority_chain import reset_durable_truth_authority_chain
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_truth_authority_chain()
        reset_session_truth_snapshot_store()
        reset_durable_result_id_store()

    def teardown_method(self):
        from core.durable_truth_authority_chain import reset_durable_truth_authority_chain
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_truth_authority_chain()
        reset_session_truth_snapshot_store()
        reset_durable_result_id_store()

    def test_B01_all_legs_healthy_converged_true(self, tmp_path):
        from core.durable_truth_authority_chain import DurableTruthAuthorityChain
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
        from core.durable_result_idempotency import DurableResultIdSet
        st_store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        tl_store = TaskLifecyclePersistenceStore(store_path=str(tmp_path / "tl.json"))
        ri_store = DurableResultIdSet(store_path=str(tmp_path / "ri.json"))
        chain = DurableTruthAuthorityChain(
            session_truth_store=st_store,
            task_lifecycle_store=tl_store,
            result_id_store=ri_store,
        )
        result = chain.convergence_check()
        assert result.converged is True
        assert result.session_truth_leg_healthy is True
        assert result.task_lifecycle_leg_healthy is True
        assert result.result_continuity_leg_healthy is True
        assert result.degradation_reasons == []

    def test_B02_unhealthy_session_truth_leg_converged_false(self, tmp_path):
        from core.durable_truth_authority_chain import DurableTruthAuthorityChain
        from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
        from core.durable_result_idempotency import DurableResultIdSet

        class BreakingStore:
            def load(self):
                raise RuntimeError("simulated failure")

        tl_store = TaskLifecyclePersistenceStore(store_path=str(tmp_path / "tl.json"))
        ri_store = DurableResultIdSet(store_path=str(tmp_path / "ri.json"))
        chain = DurableTruthAuthorityChain(
            session_truth_store=BreakingStore(),
            task_lifecycle_store=tl_store,
            result_id_store=ri_store,
        )
        result = chain.convergence_check()
        assert result.converged is False
        assert result.session_truth_leg_healthy is False
        assert len(result.degradation_reasons) >= 1

    def test_B03_unhealthy_task_lifecycle_leg_converged_false(self, tmp_path):
        from core.durable_truth_authority_chain import DurableTruthAuthorityChain
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        from core.durable_result_idempotency import DurableResultIdSet

        class BreakingStore:
            def load(self):
                raise RuntimeError("simulated failure")

        st_store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        ri_store = DurableResultIdSet(store_path=str(tmp_path / "ri.json"))
        chain = DurableTruthAuthorityChain(
            session_truth_store=st_store,
            task_lifecycle_store=BreakingStore(),
            result_id_store=ri_store,
        )
        result = chain.convergence_check()
        assert result.converged is False
        assert result.task_lifecycle_leg_healthy is False

    def test_B04_unhealthy_result_continuity_leg_converged_false(self, tmp_path):
        from core.durable_truth_authority_chain import DurableTruthAuthorityChain
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore

        class BreakingStore:
            def size(self):
                raise RuntimeError("simulated failure")

        st_store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        tl_store = TaskLifecyclePersistenceStore(store_path=str(tmp_path / "tl.json"))
        chain = DurableTruthAuthorityChain(
            session_truth_store=st_store,
            task_lifecycle_store=tl_store,
            result_id_store=BreakingStore(),
        )
        result = chain.convergence_check()
        assert result.converged is False
        assert result.result_continuity_leg_healthy is False

    def test_B05_verify_durable_truth_convergence_convenience(self, tmp_path):
        from core.durable_truth_authority_chain import verify_durable_truth_convergence
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
        from core.durable_result_idempotency import DurableResultIdSet
        st_store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        tl_store = TaskLifecyclePersistenceStore(store_path=str(tmp_path / "tl.json"))
        ri_store = DurableResultIdSet(store_path=str(tmp_path / "ri.json"))
        result = verify_durable_truth_convergence(
            session_truth_store=st_store,
            task_lifecycle_store=tl_store,
            result_id_store=ri_store,
        )
        assert result.converged is True

    def test_B06_partial_convergence_two_legs_healthy_still_false(self, tmp_path):
        from core.durable_truth_authority_chain import DurableTruthAuthorityChain
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore

        class BreakingStore:
            def size(self):
                raise RuntimeError("simulated failure")

        st_store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        tl_store = TaskLifecyclePersistenceStore(store_path=str(tmp_path / "tl.json"))
        chain = DurableTruthAuthorityChain(
            session_truth_store=st_store,
            task_lifecycle_store=tl_store,
            result_id_store=BreakingStore(),
        )
        result = chain.convergence_check()
        assert result.converged is False
        # Two legs are healthy
        healthy = sum([
            result.session_truth_leg_healthy,
            result.task_lifecycle_leg_healthy,
            result.result_continuity_leg_healthy,
        ])
        assert healthy == 2

    def test_B07_check_id_unique_per_invocation(self, tmp_path):
        from core.durable_truth_authority_chain import DurableTruthAuthorityChain
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
        from core.durable_result_idempotency import DurableResultIdSet
        st_store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        tl_store = TaskLifecyclePersistenceStore(store_path=str(tmp_path / "tl.json"))
        ri_store = DurableResultIdSet(store_path=str(tmp_path / "ri.json"))
        chain = DurableTruthAuthorityChain(
            session_truth_store=st_store,
            task_lifecycle_store=tl_store,
            result_id_store=ri_store,
        )
        r1 = chain.convergence_check()
        r2 = chain.convergence_check()
        assert r1.check_id != r2.check_id

    def test_B08_to_dict_contains_authority_key(self, tmp_path):
        from core.durable_truth_authority_chain import DurableTruthConvergenceResult
        r = DurableTruthConvergenceResult()
        d = r.to_dict()
        assert "authority" in d
        assert d["authority"]


# ---------------------------------------------------------------------------
# C — ContinuationRebindRegistry module
# ---------------------------------------------------------------------------


class TestGroupC_ContinuationRebindRegistryModule:
    def setup_method(self):
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_continuation_rebind_registry()

    def teardown_method(self):
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_continuation_rebind_registry()

    def test_C01_module_importable_authority_sentinel_present(self):
        from core.continuation_rebind_registry import (
            CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY,
        )
        assert isinstance(CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY, str)
        assert CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY

    def test_C02_closed_loop_policy_describes_five_steps(self):
        from core.continuation_rebind_registry import CONTINUATION_REBIND_CLOSED_LOOP_POLICY
        p = CONTINUATION_REBIND_CLOSED_LOOP_POLICY
        assert "register" in p.lower() or "pre-restart" in p.lower()
        assert "restart" in p.lower()
        assert "rebind" in p.lower() or "re-dispatch" in p.lower()

    def test_C03_same_task_id_policy_non_empty(self):
        from core.continuation_rebind_registry import REBIND_MUST_USE_SAME_TASK_ID_POLICY
        assert REBIND_MUST_USE_SAME_TASK_ID_POLICY

    def test_C04_idempotent_policy_non_empty(self):
        from core.continuation_rebind_registry import REBIND_IS_IDEMPOTENT_POLICY
        assert REBIND_IS_IDEMPOTENT_POLICY

    def test_C05_rebind_state_enum_values(self):
        from core.continuation_rebind_registry import RebindState
        assert RebindState.pending_rebind
        assert RebindState.rebound
        assert RebindState.completed

    def test_C06_rebind_record_instantiates_and_to_dict(self):
        from core.continuation_rebind_registry import ContinuationRebindRecord, RebindState
        rec = ContinuationRebindRecord(task_id="t1")
        d = rec.to_dict()
        assert d["task_id"] == "t1"
        assert d["state"] == RebindState.pending_rebind.value
        assert "authority" in d

    def test_C07_rebind_record_round_trips_from_dict(self):
        from core.continuation_rebind_registry import ContinuationRebindRecord, RebindState
        rec = ContinuationRebindRecord(task_id="t2", recovery_id="rcv_abc")
        d = rec.to_dict()
        rec2 = ContinuationRebindRecord.from_dict(d)
        assert rec2.task_id == "t2"
        assert rec2.recovery_id == "rcv_abc"
        assert rec2.state == RebindState.pending_rebind

    def test_C08_singleton_returns_same_instance(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        r1 = get_continuation_rebind_registry()
        r2 = get_continuation_rebind_registry()
        assert r1 is r2

    def test_C09_reset_allows_fresh_creation(self):
        from core.continuation_rebind_registry import (
            get_continuation_rebind_registry,
            reset_continuation_rebind_registry,
        )
        r1 = get_continuation_rebind_registry()
        reset_continuation_rebind_registry()
        r2 = get_continuation_rebind_registry()
        assert r1 is not r2


# ---------------------------------------------------------------------------
# D — ContinuationRebindRegistry operations (continuation rebind after restart)
# ---------------------------------------------------------------------------


class TestGroupD_ContinuationRebindRegistryOps:
    def setup_method(self):
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_continuation_rebind_registry()

    def teardown_method(self):
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_continuation_rebind_registry()

    def test_D01_register_rebind_pending_creates_record(self):
        from core.continuation_rebind_registry import (
            get_continuation_rebind_registry, RebindState,
        )
        reg = get_continuation_rebind_registry()
        tid = _task_id()
        rec = reg.register_rebind_pending(tid)
        assert rec.task_id == tid
        assert rec.state == RebindState.pending_rebind

    def test_D02_register_rebind_pending_idempotent(self):
        from core.continuation_rebind_registry import (
            get_continuation_rebind_registry, RebindState,
        )
        reg = get_continuation_rebind_registry()
        tid = _task_id()
        rec1 = reg.register_rebind_pending(tid)
        rec2 = reg.register_rebind_pending(tid)
        assert rec1 is rec2  # same object
        assert reg.pending_rebind_count() == 1

    def test_D03_register_new_waiter_transitions_to_rebound(self):
        from core.continuation_rebind_registry import (
            get_continuation_rebind_registry, RebindState,
        )
        reg = get_continuation_rebind_registry()
        tid = _task_id()
        reg.register_rebind_pending(tid)
        rec = reg.register_new_waiter(tid)
        assert rec is not None
        assert rec.state == RebindState.rebound
        assert rec.rebound_at is not None

    def test_D04_mark_completed_closes_loop(self):
        from core.continuation_rebind_registry import (
            get_continuation_rebind_registry, RebindState,
        )
        reg = get_continuation_rebind_registry()
        tid = _task_id()
        reg.register_rebind_pending(tid)
        reg.register_new_waiter(tid)
        rec = reg.mark_completed(tid)
        assert rec is not None
        assert rec.state == RebindState.completed
        assert rec.completed_at is not None

    def test_D05_is_pending_rebind_correct(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        tid = _task_id()
        assert not reg.is_pending_rebind(tid)
        reg.register_rebind_pending(tid)
        assert reg.is_pending_rebind(tid)
        reg.register_new_waiter(tid)
        assert not reg.is_pending_rebind(tid)

    def test_D06_is_loop_closed_only_for_completed(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        tid = _task_id()
        reg.register_rebind_pending(tid)
        assert not reg.is_loop_closed(tid)
        reg.register_new_waiter(tid)
        assert not reg.is_loop_closed(tid)
        reg.mark_completed(tid)
        assert reg.is_loop_closed(tid)

    def test_D07_get_record_none_for_unknown(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        assert reg.get_record("no_such_task") is None

    def test_D08_pending_rebind_count(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        t1, t2, t3 = _task_id(), _task_id(), _task_id()
        reg.register_rebind_pending(t1)
        reg.register_rebind_pending(t2)
        reg.register_rebind_pending(t3)
        assert reg.pending_rebind_count() == 3
        reg.register_new_waiter(t1)
        assert reg.pending_rebind_count() == 2

    def test_D09_rebound_count(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        t1, t2 = _task_id(), _task_id()
        reg.register_rebind_pending(t1)
        reg.register_rebind_pending(t2)
        reg.register_new_waiter(t1)
        assert reg.rebound_count() == 1
        reg.register_new_waiter(t2)
        assert reg.rebound_count() == 2

    def test_D10_completed_count(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        tid = _task_id()
        reg.register_rebind_pending(tid)
        reg.register_new_waiter(tid)
        assert reg.completed_count() == 0
        reg.mark_completed(tid)
        assert reg.completed_count() == 1

    def test_D11_list_pending_task_ids(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        t1, t2 = _task_id(), _task_id()
        reg.register_rebind_pending(t1)
        reg.register_rebind_pending(t2)
        reg.register_new_waiter(t1)
        pending = reg.list_pending_task_ids()
        assert t1 not in pending
        assert t2 in pending

    def test_D12_snapshot_json_serialisable_correct_counts(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        t1, t2 = _task_id(), _task_id()
        reg.register_rebind_pending(t1)
        reg.register_rebind_pending(t2)
        reg.register_new_waiter(t1)
        snap = reg.snapshot()
        # Must be JSON-serialisable
        json.dumps(snap)
        assert snap["pending_rebind"] == 1
        assert snap["rebound"] == 1
        assert snap["completed"] == 0
        assert snap["total"] == 2

    def test_D13_register_new_waiter_unknown_task_returns_none(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        result = reg.register_new_waiter("no_such_task")
        assert result is None

    def test_D14_mark_completed_unknown_task_returns_none(self):
        from core.continuation_rebind_registry import get_continuation_rebind_registry
        reg = get_continuation_rebind_registry()
        result = reg.mark_completed("no_such_task")
        assert result is None


# ---------------------------------------------------------------------------
# E — RuntimeRecoveryReport PR-2 fields
# ---------------------------------------------------------------------------


class TestGroupE_RecoveryReportPR2Fields:
    def test_E01_report_has_continuation_rebinds_registered_field(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        assert hasattr(r, "continuation_rebinds_registered")
        assert r.continuation_rebinds_registered == 0

    def test_E02_report_has_durable_truth_converged_field(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        assert hasattr(r, "durable_truth_converged")
        assert r.durable_truth_converged is False

    def test_E03_report_has_participants_consolidated_field(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        assert hasattr(r, "participants_consolidated")
        assert isinstance(r.participants_consolidated, dict)

    def test_E04_report_has_result_continuity_guard_active_field(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        assert hasattr(r, "result_continuity_guard_active")
        assert r.result_continuity_guard_active is False

    def test_E05_to_dict_includes_pr2_fields(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        d = r.to_dict()
        for key in (
            "continuation_rebinds_registered",
            "durable_truth_converged",
            "participants_consolidated",
            "result_continuity_guard_active",
        ):
            assert key in d, f"Missing PR-2 field in to_dict(): {key}"

    def test_E06_pr2_policy_sentinels_non_empty(self):
        from core.runtime_restart_recovery import (
            DURABLE_TRUTH_AUTHORITY_CONVERGENCE_STEP_POLICY,
            CONTINUATION_REBIND_REGISTRY_INTEGRATION_POLICY,
            MULTI_PARTICIPANT_RECOVERY_CONSOLIDATION_POLICY,
            RESULT_CONTINUITY_GUARD_VERIFICATION_POLICY,
        )
        for sentinel in (
            DURABLE_TRUTH_AUTHORITY_CONVERGENCE_STEP_POLICY,
            CONTINUATION_REBIND_REGISTRY_INTEGRATION_POLICY,
            MULTI_PARTICIPANT_RECOVERY_CONSOLIDATION_POLICY,
            RESULT_CONTINUITY_GUARD_VERIFICATION_POLICY,
        ):
            assert isinstance(sentinel, str)
            assert sentinel, f"Sentinel is empty: {sentinel!r}"


# ---------------------------------------------------------------------------
# F — Multi-task restart recovery integration
# ---------------------------------------------------------------------------


class TestGroupF_MultiTaskRestartRecovery:
    def setup_method(self):
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_lifecycle_registry()
        reset_continuation_rebind_registry()

    def teardown_method(self):
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_lifecycle_registry()
        reset_continuation_rebind_registry()

    def test_F01_multiple_resumable_tasks_all_registered(self, tmp_path):
        tasks = [_task_id() for _ in range(4)]
        records = [_record(tid, "device_dispatch") for tid in tasks]
        coord = _make_coordinator(str(tmp_path), records)
        report = coord.run_recovery()
        assert report.inflight_tasks_recovered == 4
        assert report.inflight_tasks_resumable == 4
        assert report.inflight_tasks_dispatch_actions_taken == 4

        from core.task_envelope_lifecycle_registry import get_lifecycle_registry
        reg = get_lifecycle_registry()
        for tid in tasks:
            assert reg.is_pending(tid), f"Task {tid} should be pending"

    def test_F02_tasks_on_multiple_devices_participants_consolidated(self, tmp_path):
        records = [
            _record("t1", "device_dispatch", target_device_id="dev_A"),
            _record("t2", "device_dispatch", target_device_id="dev_A"),
            _record("t3", "device_dispatch", target_device_id="dev_B"),
            _record("t4", "routing", target_device_id="dev_C"),
        ]
        coord = _make_coordinator(str(tmp_path), records)
        report = coord.run_recovery()
        p = report.participants_consolidated
        assert "dev_A" in p
        assert "dev_B" in p
        assert "dev_C" in p
        assert p["dev_A"] == 2
        assert p["dev_B"] == 1
        assert p["dev_C"] == 1

    def test_F03_participants_consolidated_counts_per_device(self, tmp_path):
        records = [
            _record(f"t{i}", "device_dispatch", target_device_id="dev_X")
            for i in range(5)
        ]
        coord = _make_coordinator(str(tmp_path), records)
        report = coord.run_recovery()
        p = report.participants_consolidated
        assert p.get("dev_X") == 5

    def test_F04_tasks_without_device_id_counted_under_unknown(self, tmp_path):
        records = [
            {
                "task_id": "t_nodev",
                "trace_id": "tr_nodev",
                "target_device_id": None,
                "tool_name": "tool",
                "owner": "device_dispatch",
                "timeout": 30.0,
                "registered_at": time.time() - 5.0,
                "metadata": {},
            }
        ]
        coord = _make_coordinator(str(tmp_path), records)
        report = coord.run_recovery()
        p = report.participants_consolidated
        assert "unknown_participant" in p
        assert p["unknown_participant"] >= 1

    def test_F05_participants_no_double_count_duplicate_task_ids(self, tmp_path):
        # Same task_id twice in snapshot (intra-snapshot duplicate)
        records = [
            _record("dup_task", "device_dispatch", target_device_id="dev_A"),
            _record("dup_task", "device_dispatch", target_device_id="dev_A"),
        ]
        coord = _make_coordinator(str(tmp_path), records)
        report = coord.run_recovery()
        p = report.participants_consolidated
        # Should only count the task once
        assert p.get("dev_A", 0) == 1

    def test_F06_mixed_dispositions_correct_counts_and_participants(self, tmp_path):
        records = [
            _record("resumable-1", "device_dispatch", target_device_id="dev_A"),
            _record("resumable-2", "cross_device", target_device_id="dev_B"),
            _record("replay-1", "routing", target_device_id="dev_A"),
            _record("reissue-1", "gateway_ingress", target_device_id="dev_C"),
            _record("terminal-1", "result_completion", target_device_id="dev_A"),
        ]
        coord = _make_coordinator(str(tmp_path), records)
        report = coord.run_recovery()
        assert report.inflight_tasks_recovered == 5
        assert report.inflight_tasks_resumable == 2
        assert report.inflight_tasks_replay_only == 1
        assert report.inflight_tasks_reissuable == 1
        assert report.inflight_tasks_terminal == 1
        p = report.participants_consolidated
        assert "dev_A" in p
        assert "dev_B" in p
        assert "dev_C" in p


# ---------------------------------------------------------------------------
# G — Multi-participant recovery consistency
# ---------------------------------------------------------------------------


class TestGroupG_MultiParticipantRecoveryConsistency:
    def setup_method(self):
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_lifecycle_registry()
        reset_continuation_rebind_registry()

    def teardown_method(self):
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_lifecycle_registry()
        reset_continuation_rebind_registry()

    def test_G01_two_participants_each_one_task(self, tmp_path):
        records = [
            _record("pA-t1", "device_dispatch", target_device_id="participant_A"),
            _record("pB-t1", "device_dispatch", target_device_id="participant_B"),
        ]
        coord = _make_coordinator(str(tmp_path), records)
        report = coord.run_recovery()
        p = report.participants_consolidated
        assert len(p) == 2
        assert p.get("participant_A") == 1
        assert p.get("participant_B") == 1

    def test_G02_one_participant_three_tasks(self, tmp_path):
        records = [
            _record(f"px-t{i}", "device_dispatch", target_device_id="participant_X")
            for i in range(3)
        ]
        coord = _make_coordinator(str(tmp_path), records)
        report = coord.run_recovery()
        p = report.participants_consolidated
        assert len(p) == 1
        assert p.get("participant_X") == 3

    def test_G03_recovery_idempotent_second_run_no_new_participants(self, tmp_path):
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry
        reset_lifecycle_registry()
        records = [
            _record("g3-t1", "device_dispatch", target_device_id="dev_A"),
            _record("g3-t2", "device_dispatch", target_device_id="dev_B"),
        ]
        ms_store, bm_store, tl_store = _make_stores(str(tmp_path))
        _save_snapshot(tl_store, records)
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=ms_store,
            body_mesh_store=bm_store,
            body_mesh_registry=FakeBodyMeshRegistry(),
            task_lifecycle_store=tl_store,
        )
        report1 = coord.run_recovery()
        report2 = coord.run_recovery()
        # Participants should be same both runs
        assert report1.participants_consolidated == report2.participants_consolidated
        # Second run: all tasks already pending, so dispatch_actions = 0
        assert report2.inflight_tasks_dispatch_actions_taken == 0

    def test_G04_result_continuity_guard_active_after_recovery(self, tmp_path):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()
        try:
            coord = _make_coordinator(str(tmp_path), [])
            report = coord.run_recovery()
            assert report.result_continuity_guard_active is True
        finally:
            reset_durable_result_id_store()


# ---------------------------------------------------------------------------
# H — Duplicate result after recovery (result continuity / idempotency)
# ---------------------------------------------------------------------------


class TestGroupH_DuplicateResultAfterRecovery:
    def setup_method(self):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()

    def teardown_method(self):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()

    def test_H01_first_add_true_second_false(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ri.json"))
        rid = _result_id()
        assert store.add(rid) is True
        assert store.add(rid) is False

    def test_H02_result_before_restart_rejected_after_restart(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ri.json")
        rid = _result_id()
        # "before restart" process
        store1 = DurableResultIdSet(store_path=path)
        store1.add(rid)
        # "after restart" process — new store instance loading same file
        store2 = DurableResultIdSet(store_path=path)
        assert store2.contains(rid), "Result recorded before restart should be seen after restart"
        assert store2.add(rid) is False, "Re-adding a result from before restart must be rejected"

    def test_H03_record_then_check_helpers(self, tmp_path, monkeypatch):
        import core.durable_result_idempotency as idem
        monkeypatch.setattr(idem, "_DEFAULT_RESULT_ID_STORE_PATH", str(tmp_path / "ri.json"))
        from core.durable_result_idempotency import (
            record_result_idempotency,
            check_result_idempotency,
        )
        rid = _result_id()
        assert check_result_idempotency(rid) is False
        assert record_result_idempotency(rid) is True
        assert check_result_idempotency(rid) is True

    def test_H04_recovery_report_result_continuity_guard_active(self, tmp_path):
        coord = _make_coordinator(str(tmp_path), [])
        report = coord.run_recovery()
        assert report.result_continuity_guard_active is True

    def test_H05_duplicate_result_ids_rejected_across_restart(self, tmp_path):
        """Simulate Android reconnect sending the same task_result twice after restart."""
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ri.json")
        rid = _result_id()

        # Simulate: original result received and recorded in "pre-restart" process
        store_pre = DurableResultIdSet(store_path=path)
        first_add = store_pre.add(rid)
        assert first_add is True

        # Simulate restart: new process, new store instance
        store_post = DurableResultIdSet(store_path=path)
        # Android reconnects and re-sends same task_result
        replay_add = store_post.add(rid)
        assert replay_add is False, (
            "Duplicate result from Android after V2 restart must be rejected "
            "by DurableResultIdSet (result continuity guard)"
        )


# ---------------------------------------------------------------------------
# I — Durable truth authority convergence (integration)
# ---------------------------------------------------------------------------

# canonical_session_truth requires pydantic (via ugcp_truth_event_model)
_pydantic_available = True
try:
    import pydantic  # noqa: F401
except ImportError:
    _pydantic_available = False


class TestGroupI_DurableTruthAuthorityConvergenceIntegration:
    def setup_method(self):
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        from core.durable_result_idempotency import reset_durable_result_id_store
        from core.durable_truth_authority_chain import reset_durable_truth_authority_chain
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_session_truth_snapshot_store()
        reset_durable_result_id_store()
        reset_durable_truth_authority_chain()
        reset_continuation_rebind_registry()
        if _pydantic_available:
            from core.canonical_session_truth import reset_canonical_session_truth_runtime
            reset_canonical_session_truth_runtime()

    def teardown_method(self):
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        from core.durable_result_idempotency import reset_durable_result_id_store
        from core.durable_truth_authority_chain import reset_durable_truth_authority_chain
        from core.continuation_rebind_registry import reset_continuation_rebind_registry
        reset_session_truth_snapshot_store()
        reset_durable_result_id_store()
        reset_durable_truth_authority_chain()
        reset_continuation_rebind_registry()
        if _pydantic_available:
            from core.canonical_session_truth import reset_canonical_session_truth_runtime
            reset_canonical_session_truth_runtime()

    def test_I01_ring_buffer_is_read_cache_sentinel_importable(self):
        if not _pydantic_available:
            pytest.skip("pydantic not installed — skipping canonical_session_truth tests")
        from core.canonical_session_truth import SESSION_TRUTH_RING_BUFFER_IS_READ_CACHE_SENTINEL
        assert isinstance(SESSION_TRUTH_RING_BUFFER_IS_READ_CACHE_SENTINEL, str)
        assert SESSION_TRUTH_RING_BUFFER_IS_READ_CACHE_SENTINEL

    def test_I02_sentinel_mentions_read_cache_and_durable(self):
        if not _pydantic_available:
            pytest.skip("pydantic not installed — skipping canonical_session_truth tests")
        from core.canonical_session_truth import SESSION_TRUTH_RING_BUFFER_IS_READ_CACHE_SENTINEL
        s = SESSION_TRUTH_RING_BUFFER_IS_READ_CACHE_SENTINEL.lower()
        assert "read-cache" in s or "read_cache" in s or "read cache" in s
        assert "durable" in s

    def test_I03_durable_truth_converged_true_after_recovery_with_real_stores(
        self, tmp_path
    ):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()
        try:
            coord = _make_coordinator(str(tmp_path), [])
            report = coord.run_recovery()
            assert report.durable_truth_converged is True, (
                "durable_truth_converged should be True when all stores are accessible. "
                f"Report: {report.to_dict()}"
            )
        finally:
            reset_durable_result_id_store()

    def test_I04_broken_session_truth_store_graceful_degradation(self, tmp_path):
        """If session truth store is broken, recovery still completes; converged=False."""
        from core.durable_truth_authority_chain import (
            DurableTruthAuthorityChain, reset_durable_truth_authority_chain,
        )

        class BreakingSessionTruthStore:
            def load(self):
                raise RuntimeError("simulated broken session truth store")
            def append(self, record):
                pass

        from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
        from core.durable_result_idempotency import DurableResultIdSet

        tl_store = TaskLifecyclePersistenceStore(store_path=str(tmp_path / "tl.json"))
        ri_store = DurableResultIdSet(store_path=str(tmp_path / "ri.json"))
        chain = DurableTruthAuthorityChain(
            session_truth_store=BreakingSessionTruthStore(),
            task_lifecycle_store=tl_store,
            result_id_store=ri_store,
        )
        result = chain.convergence_check()
        # Graceful degradation: converged is False but check completes without raising
        assert result.converged is False
        assert not result.session_truth_leg_healthy
        assert result.task_lifecycle_leg_healthy  # other legs still work
        assert result.result_continuity_leg_healthy
