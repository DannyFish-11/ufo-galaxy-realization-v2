#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_gap_v2_truth_persistence_closure.py
================================================
Integration test suite verifying closure of GAP_V2_TRUTH_PERSISTENCE (P0).

Coverage groups
---------------
A  — New policy sentinels are importable and non-empty.
B  — GAP_V2_TRUTH_PERSISTENCE is marked resolved=True with a PR reference.
C  — CanonicalSessionTruthRuntime singleton auto-wires SessionTruthSnapshotStore.
D  — Session truth records written before "restart" are restored after restart.
E  — RuntimeRecoveryReport has new session_truth / continuation fields.
F  — RuntimeRecoveryReport.to_dict includes new fields.
G  — _recover_session_truth step runs without error (no snapshot → 0 restored).
H  — _recover_session_truth step restores records from a populated snapshot.
I  — Inflight lifecycle restore: RESUMABLE tasks are re-registered under
     DEVICE_DISPATCH after recovery.
J  — Inflight lifecycle restore: REPLAY_ONLY tasks are re-registered under
     ROUTING after recovery.
K  — Inflight lifecycle restore: TERMINAL_ON_INTERRUPT tasks are not
     re-registered (avoid duplicate completion).
L  — Continuation waiter reconciliation: fail_pending_dispatch added to
     CanonicalCompletionIngress and resolves futures with an exception.
M  — _reconcile_continuation_waiters resolves futures for RESUMABLE tasks
     recovered from snapshot.
N  — Continuation reconciliation is a no-op when no futures are registered.
O  — Duplicate result after restart: idempotency via durable_result_idempotency
     is not broken by recovery (re-run of store produces same hash outcome).
P  — Canonical truth continuity: records survive a simulated restart when the
     default-on snapshot store is attached.
Q  — run_recovery report includes session_truth_records_restored count.
R  — CONTINUATION_WAITER_RECONCILIATION_POLICY sentinel is non-empty string.
S  — SESSION_TRUTH_RECOVERY_POLICY sentinel is non-empty string.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_truth_record_dict(
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    merge_success: bool = True,
) -> Dict[str, Any]:
    """Return a minimal CanonicalSessionTruthRecord dict."""
    return {
        "record_id": f"cst_{uuid.uuid4().hex[:12]}",
        "session_id": session_id or str(uuid.uuid4()),
        "task_id": task_id or str(uuid.uuid4()),
        "trace_id": None,
        "source_runtime_posture": "join_runtime",
        "coordination_role": "source",
        "source_eligible": True,
        "total_units_received": 1,
        "units_after_filter": 1,
        "filtered_unit_ids": [],
        "merge_success": merge_success,
        "primary_unit_id": None,
        "truth_source": "direct",
        "reason": "test record",
        "timestamp": time.time(),
        "metadata": {},
    }


def _make_snapshot_store(tmp_dir: str, max_records: int = 100):
    from core.session_truth_snapshot import SessionTruthSnapshotStore
    path = os.path.join(tmp_dir, "stt_snap.json")
    return SessionTruthSnapshotStore(store_path=path, max_records=max_records)


def _make_task_lifecycle_store(tmp_dir: str):
    from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
    path = os.path.join(tmp_dir, "tlc_snap.json")
    return TaskLifecyclePersistenceStore(store_path=path)


def _write_lifecycle_record(store, task_id: str, owner: str = "device_dispatch") -> None:
    """Persist a minimal lifecycle record to *store*."""
    from core.task_lifecycle_persistence import TaskLifecycleSnapshotRecord
    record = {
        "task_id": task_id,
        "trace_id": None,
        "target_device_id": "dev_test",
        "tool_name": "test_tool",
        "owner": owner,
        "timeout": 30.0,
        "registered_at": time.time(),
        "metadata": {},
        "snapshot_id": str(uuid.uuid4()),
    }
    snapshot = TaskLifecycleSnapshotRecord(records=[record])
    store.save(snapshot)


# ---------------------------------------------------------------------------
# Group A — New policy sentinels
# ---------------------------------------------------------------------------


class TestGroupA_NewPolicySentinels:
    """New policy sentinels for GAP_V2_TRUTH_PERSISTENCE closure are importable."""

    def test_A01_session_truth_recovery_policy_importable(self):
        from core.runtime_restart_recovery import SESSION_TRUTH_RECOVERY_POLICY
        assert isinstance(SESSION_TRUTH_RECOVERY_POLICY, str)
        assert SESSION_TRUTH_RECOVERY_POLICY

    def test_A02_continuation_waiter_reconciliation_policy_importable(self):
        from core.runtime_restart_recovery import CONTINUATION_WAITER_RECONCILIATION_POLICY
        assert isinstance(CONTINUATION_WAITER_RECONCILIATION_POLICY, str)
        assert CONTINUATION_WAITER_RECONCILIATION_POLICY

    def test_A03_session_truth_recovery_mentions_gap(self):
        from core.runtime_restart_recovery import SESSION_TRUTH_RECOVERY_POLICY
        assert "GAP_V2_TRUTH_PERSISTENCE" in SESSION_TRUTH_RECOVERY_POLICY

    def test_A04_continuation_policy_mentions_gap(self):
        from core.runtime_restart_recovery import CONTINUATION_WAITER_RECONCILIATION_POLICY
        assert "GAP_V2_TRUTH_PERSISTENCE" in CONTINUATION_WAITER_RECONCILIATION_POLICY

    def test_A05_sentinels_in_all(self):
        import core.runtime_restart_recovery as m
        assert "SESSION_TRUTH_RECOVERY_POLICY" in m.__all__
        assert "CONTINUATION_WAITER_RECONCILIATION_POLICY" in m.__all__


# ---------------------------------------------------------------------------
# Group B — GAP_V2_TRUTH_PERSISTENCE resolved
# ---------------------------------------------------------------------------


class TestGroupB_GapResolved:
    """GAP_V2_TRUTH_PERSISTENCE is marked resolved in WORKSTREAM_GAP_REGISTRY."""

    def test_B01_gap_entry_resolved(self):
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY
        gap = next(
            (e for e in WORKSTREAM_GAP_REGISTRY if e.gap_id == "GAP_V2_TRUTH_PERSISTENCE"),
            None,
        )
        assert gap is not None, "GAP_V2_TRUTH_PERSISTENCE not found in registry"
        assert gap.resolved is True, "GAP_V2_TRUTH_PERSISTENCE must be resolved=True"

    def test_B02_gap_has_pr_reference(self):
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY
        gap = next(
            (e for e in WORKSTREAM_GAP_REGISTRY if e.gap_id == "GAP_V2_TRUTH_PERSISTENCE"),
            None,
        )
        assert gap is not None
        assert gap.resolution_pr, "GAP_V2_TRUTH_PERSISTENCE must have a resolution_pr"

    def test_B03_gap_not_in_open_p0_list(self):
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY, GapSeverity
        open_p0 = [
            e for e in WORKSTREAM_GAP_REGISTRY
            if e.severity == GapSeverity.P0 and not e.resolved
        ]
        gap_ids = [e.gap_id for e in open_p0]
        assert "GAP_V2_TRUTH_PERSISTENCE" not in gap_ids


# ---------------------------------------------------------------------------
# Group C — Default-on snapshot store wiring
# ---------------------------------------------------------------------------


class TestGroupC_DefaultOnSnapshotWiring:
    """CanonicalSessionTruthRuntime singleton auto-wires SessionTruthSnapshotStore."""

    def setup_method(self):
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

    def teardown_method(self):
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

    def test_C01_runtime_singleton_has_snapshot_store_attached(self):
        from core.canonical_session_truth import get_canonical_session_truth_runtime
        runtime = get_canonical_session_truth_runtime()
        assert runtime._snapshot_store is not None, (
            "CanonicalSessionTruthRuntime singleton must auto-wire a "
            "SessionTruthSnapshotStore on first creation."
        )

    def test_C02_snapshot_store_is_session_truth_snapshot_store(self):
        from core.canonical_session_truth import get_canonical_session_truth_runtime
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        runtime = get_canonical_session_truth_runtime()
        assert isinstance(runtime._snapshot_store, SessionTruthSnapshotStore)

    def test_C03_auto_wired_store_is_process_level_singleton(self):
        from core.canonical_session_truth import get_canonical_session_truth_runtime
        from core.session_truth_snapshot import get_session_truth_snapshot_store
        runtime = get_canonical_session_truth_runtime()
        singleton_store = get_session_truth_snapshot_store()
        assert runtime._snapshot_store is singleton_store


# ---------------------------------------------------------------------------
# Group D — Session truth records survive simulated restart
# ---------------------------------------------------------------------------


class TestGroupD_TruthSurvivesRestart:
    """Session truth records written before restart are restored after restart."""

    def test_D01_records_restored_from_snapshot_after_reset(self):
        from core.canonical_session_truth import (
            reset_canonical_session_truth_runtime,
            get_canonical_session_truth_runtime,
            CanonicalSessionTruthRecord,
        )
        from core.session_truth_snapshot import (
            reset_session_truth_snapshot_store,
            SessionTruthSnapshotStore,
            restore_session_truth_from_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            snap_path = os.path.join(tmp, "stt.json")
            store = SessionTruthSnapshotStore(store_path=snap_path)

            # "Before restart": create a runtime, wire the store, write records.
            reset_canonical_session_truth_runtime()
            reset_session_truth_snapshot_store()
            rt1 = get_canonical_session_truth_runtime()
            rt1.set_snapshot_store(store)

            session_id = str(uuid.uuid4())
            rec = CanonicalSessionTruthRecord.from_dict(
                _make_truth_record_dict(session_id=session_id)
            )
            rt1.record(rec)
            assert rt1.snapshot().total_records == 1

            # "Restart": reset the singleton.
            reset_canonical_session_truth_runtime()
            reset_session_truth_snapshot_store()

            # "After restart": new runtime, restore from snapshot.
            rt2 = get_canonical_session_truth_runtime()
            rt2.set_snapshot_store(store)
            restored = restore_session_truth_from_snapshot(runtime=rt2, store=store)

            assert restored == 1
            assert rt2.snapshot().total_records >= 1

    def test_D02_multiple_records_all_restored(self):
        from core.canonical_session_truth import (
            reset_canonical_session_truth_runtime,
            get_canonical_session_truth_runtime,
            CanonicalSessionTruthRecord,
        )
        from core.session_truth_snapshot import (
            reset_session_truth_snapshot_store,
            SessionTruthSnapshotStore,
            restore_session_truth_from_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            snap_path = os.path.join(tmp, "stt2.json")
            store = SessionTruthSnapshotStore(store_path=snap_path)

            reset_canonical_session_truth_runtime()
            reset_session_truth_snapshot_store()
            rt1 = get_canonical_session_truth_runtime()
            rt1.set_snapshot_store(store)

            n = 5
            for _ in range(n):
                rec = CanonicalSessionTruthRecord.from_dict(_make_truth_record_dict())
                rt1.record(rec)

            assert rt1.snapshot().total_records == n

            reset_canonical_session_truth_runtime()
            reset_session_truth_snapshot_store()

            rt2 = get_canonical_session_truth_runtime()
            rt2.set_snapshot_store(store)
            restored = restore_session_truth_from_snapshot(runtime=rt2, store=store)

            assert restored == n


# ---------------------------------------------------------------------------
# Group E — RuntimeRecoveryReport new fields
# ---------------------------------------------------------------------------


class TestGroupE_ReportNewFields:
    """RuntimeRecoveryReport has new session_truth_records_restored and
    continuation_waiters_reconciled fields."""

    def test_E01_session_truth_records_restored_default_zero(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        assert report.session_truth_records_restored == 0

    def test_E02_continuation_waiters_reconciled_default_zero(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        assert report.continuation_waiters_reconciled == 0

    def test_E03_fields_settable(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        report.session_truth_records_restored = 7
        report.continuation_waiters_reconciled = 3
        assert report.session_truth_records_restored == 7
        assert report.continuation_waiters_reconciled == 3


# ---------------------------------------------------------------------------
# Group F — RuntimeRecoveryReport.to_dict includes new fields
# ---------------------------------------------------------------------------


class TestGroupF_ReportToDict:
    """to_dict includes the new fields for observability."""

    def test_F01_to_dict_has_session_truth_records_restored(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        d = RuntimeRecoveryReport().to_dict()
        assert "session_truth_records_restored" in d

    def test_F02_to_dict_has_continuation_waiters_reconciled(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        d = RuntimeRecoveryReport().to_dict()
        assert "continuation_waiters_reconciled" in d

    def test_F03_to_dict_values_match_attributes(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        report.session_truth_records_restored = 4
        report.continuation_waiters_reconciled = 2
        d = report.to_dict()
        assert d["session_truth_records_restored"] == 4
        assert d["continuation_waiters_reconciled"] == 2


# ---------------------------------------------------------------------------
# Group G — _recover_session_truth with empty store
# ---------------------------------------------------------------------------


class TestGroupG_RecoverSessionTruthEmpty:
    """_recover_session_truth with no snapshot data → 0 restored, no error."""

    def test_G01_empty_snapshot_yields_zero_restored(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )
        from core.session_truth_snapshot import SessionTruthSnapshotStore

        with tempfile.TemporaryDirectory() as tmp:
            # Use an explicit empty store so the test is isolated from the global
            # singleton which may contain records from other tests.
            empty_store = SessionTruthSnapshotStore(
                store_path=os.path.join(tmp, "empty_stt.json")
            )

            coord = RuntimeRestartRecoveryCoordinator()
            report = RuntimeRecoveryReport()

            # Patch both get_session_truth_snapshot_store and
            # get_canonical_session_truth_runtime to use isolated instances.
            from core.canonical_session_truth import CanonicalSessionTruthRuntime
            isolated_runtime = CanonicalSessionTruthRuntime()
            isolated_runtime.set_snapshot_store(empty_store)

            with patch(
                "core.session_truth_snapshot.get_session_truth_snapshot_store",
                return_value=empty_store,
            ), patch(
                "core.canonical_session_truth.get_canonical_session_truth_runtime",
                return_value=isolated_runtime,
            ):
                coord._recover_session_truth(report)

        assert report.session_truth_records_restored == 0

    def test_G02_no_exception_raised_from_empty_snapshot(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        from core.canonical_session_truth import CanonicalSessionTruthRuntime

        with tempfile.TemporaryDirectory() as tmp:
            empty_store = SessionTruthSnapshotStore(
                store_path=os.path.join(tmp, "empty_stt2.json")
            )
            isolated_runtime = CanonicalSessionTruthRuntime()
            isolated_runtime.set_snapshot_store(empty_store)

            coord = RuntimeRestartRecoveryCoordinator()
            report = RuntimeRecoveryReport()
            with patch(
                "core.session_truth_snapshot.get_session_truth_snapshot_store",
                return_value=empty_store,
            ), patch(
                "core.canonical_session_truth.get_canonical_session_truth_runtime",
                return_value=isolated_runtime,
            ):
                # Must not raise
                coord._recover_session_truth(report)


# ---------------------------------------------------------------------------
# Group H — _recover_session_truth with populated snapshot
# ---------------------------------------------------------------------------


class TestGroupH_RecoverSessionTruthPopulated:
    """_recover_session_truth restores records when the snapshot contains data."""

    def test_H01_records_from_snapshot_loaded_into_runtime(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )
        from core.canonical_session_truth import (
            reset_canonical_session_truth_runtime,
            get_canonical_session_truth_runtime,
        )
        from core.session_truth_snapshot import (
            reset_session_truth_snapshot_store,
            SessionTruthSnapshotStore,
            get_session_truth_snapshot_store,
        )

        with tempfile.TemporaryDirectory() as tmp:
            snap_path = os.path.join(tmp, "stt_h.json")
            store = SessionTruthSnapshotStore(store_path=snap_path)

            # Write 3 records to the snapshot directly.
            for _ in range(3):
                store.append(_make_truth_record_dict())

            # Reset singletons so the coordinator gets a fresh runtime.
            reset_canonical_session_truth_runtime()
            reset_session_truth_snapshot_store()

            # Wire the store as the singleton.
            with patch(
                "core.session_truth_snapshot.get_session_truth_snapshot_store",
                return_value=store,
            ), patch(
                "core.canonical_session_truth.get_canonical_session_truth_runtime",
                side_effect=lambda: get_canonical_session_truth_runtime(),
            ):
                # Reset again so get_canonical_session_truth_runtime picks up the
                # patched store.
                reset_canonical_session_truth_runtime()
                rt = get_canonical_session_truth_runtime()
                rt.set_snapshot_store(store)

                coord = RuntimeRestartRecoveryCoordinator()
                report = RuntimeRecoveryReport()
                coord._recover_session_truth(report)

            assert report.session_truth_records_restored == 3

            reset_canonical_session_truth_runtime()
            reset_session_truth_snapshot_store()


# ---------------------------------------------------------------------------
# Group I — Inflight lifecycle restore: RESUMABLE tasks re-registered
# ---------------------------------------------------------------------------


class TestGroupI_InflightResumable:
    """RESUMABLE tasks are re-registered under DEVICE_DISPATCH after recovery."""

    def test_I01_resumable_task_registered_in_lifecycle_registry(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
        )

        reset_lifecycle_registry()

        with tempfile.TemporaryDirectory() as tmp:
            store = _make_task_lifecycle_store(tmp)
            task_id = f"t_{uuid.uuid4().hex[:8]}"
            # device_dispatch → RESUMABLE
            _write_lifecycle_record(store, task_id, owner="device_dispatch")

            coord = RuntimeRestartRecoveryCoordinator(task_lifecycle_store=store)
            report = RuntimeRecoveryReport()
            coord._recover_inflight_tasks(report)
            from core.task_lifecycle_persistence import restore_inflight_tasks_from_snapshot
            coord._dispatch_recovered_tasks(
                restore_inflight_tasks_from_snapshot(store=store),
                report,
            )

        registry = get_lifecycle_registry()
        assert registry.is_pending(task_id), (
            f"RESUMABLE task {task_id!r} must be registered after recovery"
        )
        reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# Group J — Inflight lifecycle restore: REPLAY_ONLY tasks
# ---------------------------------------------------------------------------


class TestGroupJ_InflightReplayOnly:
    """REPLAY_ONLY tasks are re-registered after recovery."""

    def test_J01_replay_only_task_registered(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
        )
        from core.task_lifecycle_persistence import restore_inflight_tasks_from_snapshot

        reset_lifecycle_registry()

        with tempfile.TemporaryDirectory() as tmp:
            store = _make_task_lifecycle_store(tmp)
            task_id = f"t_{uuid.uuid4().hex[:8]}"
            # routing → REPLAY_ONLY
            _write_lifecycle_record(store, task_id, owner="routing")

            coord = RuntimeRestartRecoveryCoordinator(task_lifecycle_store=store)
            report = RuntimeRecoveryReport()
            coord._recover_inflight_tasks(report)
            coord._dispatch_recovered_tasks(
                restore_inflight_tasks_from_snapshot(store=store),
                report,
            )

        registry = get_lifecycle_registry()
        assert registry.is_pending(task_id)
        reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# Group K — TERMINAL_ON_INTERRUPT tasks not re-registered
# ---------------------------------------------------------------------------


class TestGroupK_InflightTerminal:
    """TERMINAL_ON_INTERRUPT tasks are not re-registered to prevent duplicate completion."""

    def test_K01_terminal_task_not_registered(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
        )
        from core.task_lifecycle_persistence import restore_inflight_tasks_from_snapshot

        reset_lifecycle_registry()

        with tempfile.TemporaryDirectory() as tmp:
            store = _make_task_lifecycle_store(tmp)
            task_id = f"t_{uuid.uuid4().hex[:8]}"
            # result_completion → TERMINAL_ON_INTERRUPT
            _write_lifecycle_record(store, task_id, owner="result_completion")

            coord = RuntimeRestartRecoveryCoordinator(task_lifecycle_store=store)
            report = RuntimeRecoveryReport()
            coord._recover_inflight_tasks(report)
            coord._dispatch_recovered_tasks(
                restore_inflight_tasks_from_snapshot(store=store),
                report,
            )

        registry = get_lifecycle_registry()
        assert not registry.is_pending(task_id), (
            f"TERMINAL task {task_id!r} must NOT be registered after recovery"
        )
        reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# Group L — fail_pending_dispatch on CanonicalCompletionIngress
# ---------------------------------------------------------------------------


class TestGroupL_FailPendingDispatch:
    """fail_pending_dispatch resolves futures with an exception."""

    def test_L01_fail_pending_dispatch_resolves_future_with_exception(self):
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        async def _run():
            ingress = CanonicalCompletionIngress()
            fut = ingress.register_pending_dispatch("hid_1", task_id="tid_1")
            exc = RuntimeError("restart_recovery: test")
            resolved = ingress.fail_pending_dispatch("hid_1", exc)
            assert resolved is True
            with pytest.raises(RuntimeError, match="restart_recovery"):
                await fut

        asyncio.get_event_loop().run_until_complete(_run())

    def test_L02_fail_pending_dispatch_by_task_id(self):
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        async def _run():
            ingress = CanonicalCompletionIngress()
            fut = ingress.register_pending_dispatch("hid_2", task_id="tid_2")
            exc = RuntimeError("restart_recovery: test by task_id")
            resolved = ingress.fail_pending_dispatch("tid_2", exc)
            assert resolved is True
            with pytest.raises(RuntimeError):
                await fut

        asyncio.get_event_loop().run_until_complete(_run())

    def test_L03_fail_pending_dispatch_no_match_returns_false(self):
        from core.canonical_completion_ingress import CanonicalCompletionIngress
        ingress = CanonicalCompletionIngress()
        exc = RuntimeError("no such future")
        assert ingress.fail_pending_dispatch("nonexistent_key", exc) is False

    def test_L04_fail_pending_dispatch_already_resolved_returns_false(self):
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        async def _run():
            ingress = CanonicalCompletionIngress()
            fut = ingress.register_pending_dispatch("hid_3", task_id="tid_3")
            # First resolution (by result).
            ingress.complete_pending_dispatch("hid_3", {"status": "ok"})
            # Second resolution attempt should be a no-op.
            exc = RuntimeError("second resolve")
            assert ingress.fail_pending_dispatch("tid_3", exc) is False

        asyncio.get_event_loop().run_until_complete(_run())

    def test_L05_fail_pending_dispatch_module_level_shortcut_importable(self):
        from core.canonical_completion_ingress import fail_pending_dispatch
        assert callable(fail_pending_dispatch)


# ---------------------------------------------------------------------------
# Group M — _reconcile_continuation_waiters resolves futures for RESUMABLE
# ---------------------------------------------------------------------------


class TestGroupM_ReconcileContinuationWaiters:
    """_reconcile_continuation_waiters resolves futures for RESUMABLE tasks."""

    def test_M01_future_resolved_with_exception_for_resumable_task(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        async def _run():
            with tempfile.TemporaryDirectory() as tmp:
                store = _make_task_lifecycle_store(tmp)
                task_id = f"t_{uuid.uuid4().hex[:8]}"
                # device_dispatch → RESUMABLE
                _write_lifecycle_record(store, task_id, owner="device_dispatch")

                ingress = CanonicalCompletionIngress()
                fut = ingress.register_pending_dispatch(
                    f"hid_{task_id}", task_id=task_id
                )

                coord = RuntimeRestartRecoveryCoordinator(task_lifecycle_store=store)
                report = RuntimeRecoveryReport()

                # Patch get_canonical_completion_ingress to return our isolated
                # ingress instance so the reconciler operates on the futures we
                # registered above rather than the process-level singleton.
                with patch(
                    "core.canonical_completion_ingress.get_canonical_completion_ingress",
                    return_value=ingress,
                ):
                    coord._reconcile_continuation_waiters(report)

                assert report.continuation_waiters_reconciled >= 1
                # The future should be resolved with an exception.
                assert fut.done()
                with pytest.raises(RuntimeError, match="restart_recovery"):
                    fut.result()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_M02_empty_store_reconciles_zero_futures(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = _make_task_lifecycle_store(tmp)
            # No records in the store.
            coord = RuntimeRestartRecoveryCoordinator(task_lifecycle_store=store)
            report = RuntimeRecoveryReport()
            coord._reconcile_continuation_waiters(report)

        assert report.continuation_waiters_reconciled == 0


# ---------------------------------------------------------------------------
# Group N — Continuation reconciliation is no-op when no futures registered
# ---------------------------------------------------------------------------


class TestGroupN_ReconcileNoFutures:
    """When no futures are registered, reconciliation increments nothing."""

    def test_N01_no_futures_registered_zero_reconciled(self):
        from core.runtime_restart_recovery import (
            RuntimeRecoveryReport,
            RuntimeRestartRecoveryCoordinator,
        )
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        with tempfile.TemporaryDirectory() as tmp:
            store = _make_task_lifecycle_store(tmp)
            task_id = f"t_{uuid.uuid4().hex[:8]}"
            _write_lifecycle_record(store, task_id, owner="device_dispatch")

            ingress = CanonicalCompletionIngress()
            # No futures registered for this task_id.

            with patch(
                "core.canonical_completion_ingress.get_canonical_completion_ingress",
                return_value=ingress,
            ):
                coord = RuntimeRestartRecoveryCoordinator(task_lifecycle_store=store)
                report = RuntimeRecoveryReport()
                coord._reconcile_continuation_waiters(report)

        assert report.continuation_waiters_reconciled == 0


# ---------------------------------------------------------------------------
# Group O — Duplicate result after restart: idempotency not broken
# ---------------------------------------------------------------------------


class TestGroupO_DuplicateResultIdempotency:
    """Durable result idempotency is preserved after restart simulation."""

    def test_O01_idempotent_result_store_survives_reset(self):
        from core.durable_result_idempotency import DurableResultIdSet

        with tempfile.TemporaryDirectory() as tmp:
            store_path = os.path.join(tmp, "result_idem.json")
            store1 = DurableResultIdSet(store_path=store_path)

            result_id = f"r_{uuid.uuid4().hex[:8]}"

            # First add — new ID.
            added1 = store1.add(result_id)
            assert added1 is True

            # "Restart": open a new store backed by the same file.
            store2 = DurableResultIdSet(store_path=store_path)
            # Same result_id must already be present.
            added2 = store2.add(result_id)
            assert added2 is False, (
                "Re-submitting the same result_id after restart must be idempotent"
            )
            assert store2.contains(result_id) is True


# ---------------------------------------------------------------------------
# Group P — Canonical truth continuity: snapshot stores record on every append
# ---------------------------------------------------------------------------


class TestGroupP_CanonicalTruthContinuity:
    """Records written via CanonicalSessionTruthRuntime are durable by default."""

    def test_P01_record_written_to_snapshot_store_immediately(self):
        from core.canonical_session_truth import (
            reset_canonical_session_truth_runtime,
            get_canonical_session_truth_runtime,
            CanonicalSessionTruthRecord,
        )
        from core.session_truth_snapshot import (
            reset_session_truth_snapshot_store,
            SessionTruthSnapshotStore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            snap_path = os.path.join(tmp, "stt_p.json")
            store = SessionTruthSnapshotStore(store_path=snap_path)

            reset_canonical_session_truth_runtime()
            reset_session_truth_snapshot_store()

            rt = get_canonical_session_truth_runtime()
            rt.set_snapshot_store(store)

            rec = CanonicalSessionTruthRecord.from_dict(_make_truth_record_dict())
            rt.record(rec)

            # Snapshot file must exist and have 1 record.
            assert os.path.exists(snap_path)
            with open(snap_path) as fh:
                data = json.load(fh)
            assert data["count"] == 1

            reset_canonical_session_truth_runtime()
            reset_session_truth_snapshot_store()

    def test_P02_default_singleton_writes_to_snapshot_store(self):
        from core.canonical_session_truth import (
            reset_canonical_session_truth_runtime,
            get_canonical_session_truth_runtime,
            CanonicalSessionTruthRecord,
        )
        from core.session_truth_snapshot import (
            reset_session_truth_snapshot_store,
            get_session_truth_snapshot_store,
        )

        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

        rt = get_canonical_session_truth_runtime()
        store = get_session_truth_snapshot_store()
        # Both should be wired (auto-wiring).
        assert rt._snapshot_store is store

        rec = CanonicalSessionTruthRecord.from_dict(_make_truth_record_dict())
        rt.record(rec)

        records_in_store = store.load()
        assert len(records_in_store) >= 1

        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()


# ---------------------------------------------------------------------------
# Group Q — run_recovery report includes session_truth_records_restored
# ---------------------------------------------------------------------------


class TestGroupQ_RunRecoveryReport:
    """run_recovery report includes the new fields."""

    def test_Q01_run_recovery_report_has_session_truth_records_restored(self):
        from core.runtime_restart_recovery import run_startup_recovery
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store

        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

        report = run_startup_recovery()

        assert hasattr(report, "session_truth_records_restored")
        assert isinstance(report.session_truth_records_restored, int)

        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

    def test_Q02_run_recovery_report_has_continuation_waiters_reconciled(self):
        from core.runtime_restart_recovery import run_startup_recovery
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store

        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

        report = run_startup_recovery()

        assert hasattr(report, "continuation_waiters_reconciled")
        assert isinstance(report.continuation_waiters_reconciled, int)

        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

    def test_Q03_run_recovery_to_dict_has_new_keys(self):
        from core.runtime_restart_recovery import run_startup_recovery
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store

        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

        report = run_startup_recovery()
        d = report.to_dict()

        assert "session_truth_records_restored" in d
        assert "continuation_waiters_reconciled" in d

        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()


# ---------------------------------------------------------------------------
# Group R — CONTINUATION_WAITER_RECONCILIATION_POLICY sentinel
# ---------------------------------------------------------------------------


class TestGroupR_ContinuationSentinel:
    """CONTINUATION_WAITER_RECONCILIATION_POLICY is a non-empty string."""

    def test_R01_sentinel_is_str(self):
        from core.runtime_restart_recovery import CONTINUATION_WAITER_RECONCILIATION_POLICY
        assert isinstance(CONTINUATION_WAITER_RECONCILIATION_POLICY, str)

    def test_R02_sentinel_is_not_empty(self):
        from core.runtime_restart_recovery import CONTINUATION_WAITER_RECONCILIATION_POLICY
        assert len(CONTINUATION_WAITER_RECONCILIATION_POLICY) > 0

    def test_R03_sentinel_contains_policy_prefix(self):
        from core.runtime_restart_recovery import CONTINUATION_WAITER_RECONCILIATION_POLICY
        assert "POLICY::" in CONTINUATION_WAITER_RECONCILIATION_POLICY


# ---------------------------------------------------------------------------
# Group S — SESSION_TRUTH_RECOVERY_POLICY sentinel
# ---------------------------------------------------------------------------


class TestGroupS_SessionTruthRecoverySentinel:
    """SESSION_TRUTH_RECOVERY_POLICY is a non-empty string."""

    def test_S01_sentinel_is_str(self):
        from core.runtime_restart_recovery import SESSION_TRUTH_RECOVERY_POLICY
        assert isinstance(SESSION_TRUTH_RECOVERY_POLICY, str)

    def test_S02_sentinel_is_not_empty(self):
        from core.runtime_restart_recovery import SESSION_TRUTH_RECOVERY_POLICY
        assert len(SESSION_TRUTH_RECOVERY_POLICY) > 0

    def test_S03_sentinel_contains_policy_prefix(self):
        from core.runtime_restart_recovery import SESSION_TRUTH_RECOVERY_POLICY
        assert "POLICY::" in SESSION_TRUTH_RECOVERY_POLICY
