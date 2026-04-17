#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr1_mesh_session_durable_foundation.py
===================================================
Tests for the PR-1 Durable Mesh Session Runtime Foundation.

Coverage:
  # contracts/mesh_session.py — lifecycle extensions
  1.  SUSPENDED status is present in MeshSessionStatus.
  2.  RESTORING status is present in MeshSessionStatus.
  3.  MESH_SESSION_TERMINAL_STATUSES contains completed/cancelled/failed.
  4.  MESH_SESSION_RESTORABLE_STATUSES contains suspended.
  5.  MESH_SESSION_VALID_TRANSITIONS is a dict with expected source keys.
  6.  MESH_SESSION_LIFECYCLE_IS_EXPLICIT sentinel is an importable string.
  7.  is_valid_lifecycle_transition: PENDING→ACTIVE is valid.
  8.  is_valid_lifecycle_transition: ACTIVE→SUSPENDED is valid.
  9.  is_valid_lifecycle_transition: SUSPENDED→RESTORING is valid.
  10. is_valid_lifecycle_transition: RESTORING→ACTIVE is valid.
  11. is_valid_lifecycle_transition: ACTIVE→COMPLETED is valid.
  12. is_valid_lifecycle_transition: COMPLETED→ACTIVE is invalid.
  13. is_valid_lifecycle_transition: ACTIVE→PENDING is invalid.
  14. _map_session_status handles "suspended" and "restoring" correctly.
  15. MeshSession can be constructed with SUSPENDED status.
  16. MeshSession to_dict/from_dict round-trips SUSPENDED and RESTORING.

  # core/mesh/mesh_session_lifecycle.py
  17. Module sentinels are importable strings.
  18. MeshSessionLifecycleRecord construction and to_dict.
  19. MeshSessionLifecycleCoordinator.create_session registers record.
  20. create_session with no session_id returns None.
  21. activate_session: PENDING → ACTIVE.
  22. activate_session: invalid source status returns None.
  23. suspend_session: ACTIVE → SUSPENDED.
  24. suspend_session: invalid source returns None.
  25. restore_session: SUSPENDED → ACTIVE (via durable store).
  26. restore_session: no durable state returns None.
  27. restore_session: terminal snapshot is not restored.
  28. terminate_session: ACTIVE → COMPLETED + mark_terminal.
  29. terminate_session: ACTIVE → CANCELLED.
  30. terminate_session: ACTIVE → FAILED.
  31. terminate_session: invalid outcome defaults to failed.
  32. get_record returns in-memory record.
  33. list_active_session_ids returns only active sessions.
  34. summary() returns expected keys.
  35. get_lifecycle_coordinator returns singleton.
  36. reset_lifecycle_coordinator clears singleton.
  37. Module-level create_durable_session function.
  38. Module-level activate_durable_session function.
  39. Module-level suspend_durable_session function.
  40. Module-level restore_durable_session function.
  41. Module-level terminate_durable_session function.
  42. core.mesh __init__ exports lifecycle symbols.

  # core/outward_runtime_truth.py — durable_mesh_session_facet
  43. OutwardRuntimeTruthSnapshot has durable_mesh_session_facet field.
  44. to_dict() includes durable_mesh_session_facet key.
  45. compile_outward_truth includes DurableMeshSessionFacet source record.
  46. durable_mesh_session_facet is populated when persistence store has sessions.
"""

from __future__ import annotations

import tempfile
from typing import Any, Dict, Optional

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _make_store(tmp_dir: Optional[str] = None):
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    return MeshSessionPersistenceStore(store_dir=tmp_dir or tempfile.mkdtemp())


def _make_coordinator(store=None):
    from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator
    return MeshSessionLifecycleCoordinator(store=store)


def _make_session_dict(session_id: str = "sess-001", status: str = "pending") -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "status": status,
        "source_device_id": "phone_001",
        "primary_device_id": "tablet_002",
    }


# ===========================================================================
# 1–16: contracts/mesh_session.py lifecycle extensions
# ===========================================================================


class TestMeshSessionStatusExtensions:
    """Tests for new lifecycle states added in PR-1."""

    def test_suspended_status_exists(self):
        from contracts.mesh_session import MeshSessionStatus
        assert MeshSessionStatus.SUSPENDED.value == "suspended"

    def test_restoring_status_exists(self):
        from contracts.mesh_session import MeshSessionStatus
        assert MeshSessionStatus.RESTORING.value == "restoring"

    def test_terminal_statuses_sentinel(self):
        from contracts.mesh_session import MESH_SESSION_TERMINAL_STATUSES, MeshSessionStatus
        assert MeshSessionStatus.COMPLETED in MESH_SESSION_TERMINAL_STATUSES
        assert MeshSessionStatus.CANCELLED in MESH_SESSION_TERMINAL_STATUSES
        assert MeshSessionStatus.FAILED in MESH_SESSION_TERMINAL_STATUSES
        assert MeshSessionStatus.SUSPENDED not in MESH_SESSION_TERMINAL_STATUSES
        assert MeshSessionStatus.ACTIVE not in MESH_SESSION_TERMINAL_STATUSES

    def test_restorable_statuses_sentinel(self):
        from contracts.mesh_session import MESH_SESSION_RESTORABLE_STATUSES, MeshSessionStatus
        assert MeshSessionStatus.SUSPENDED in MESH_SESSION_RESTORABLE_STATUSES
        assert MeshSessionStatus.ACTIVE not in MESH_SESSION_RESTORABLE_STATUSES

    def test_valid_transitions_is_dict(self):
        from contracts.mesh_session import MESH_SESSION_VALID_TRANSITIONS, MeshSessionStatus
        assert isinstance(MESH_SESSION_VALID_TRANSITIONS, dict)
        # All canonical source states present
        for status in (
            MeshSessionStatus.PENDING,
            MeshSessionStatus.ACTIVE,
            MeshSessionStatus.MERGING,
            MeshSessionStatus.SUSPENDED,
            MeshSessionStatus.RESTORING,
        ):
            assert status in MESH_SESSION_VALID_TRANSITIONS

    def test_lifecycle_is_explicit_sentinel(self):
        from contracts.mesh_session import MESH_SESSION_LIFECYCLE_IS_EXPLICIT
        assert isinstance(MESH_SESSION_LIFECYCLE_IS_EXPLICIT, str)
        assert "MESH_SESSION_LIFECYCLE_IS_EXPLICIT" in MESH_SESSION_LIFECYCLE_IS_EXPLICIT
        assert "PR-1" in MESH_SESSION_LIFECYCLE_IS_EXPLICIT

    def test_valid_transition_pending_to_active(self):
        from contracts.mesh_session import MeshSessionStatus, is_valid_lifecycle_transition
        assert is_valid_lifecycle_transition(
            MeshSessionStatus.PENDING, MeshSessionStatus.ACTIVE
        ) is True

    def test_valid_transition_active_to_suspended(self):
        from contracts.mesh_session import MeshSessionStatus, is_valid_lifecycle_transition
        assert is_valid_lifecycle_transition(
            MeshSessionStatus.ACTIVE, MeshSessionStatus.SUSPENDED
        ) is True

    def test_valid_transition_suspended_to_restoring(self):
        from contracts.mesh_session import MeshSessionStatus, is_valid_lifecycle_transition
        assert is_valid_lifecycle_transition(
            MeshSessionStatus.SUSPENDED, MeshSessionStatus.RESTORING
        ) is True

    def test_valid_transition_restoring_to_active(self):
        from contracts.mesh_session import MeshSessionStatus, is_valid_lifecycle_transition
        assert is_valid_lifecycle_transition(
            MeshSessionStatus.RESTORING, MeshSessionStatus.ACTIVE
        ) is True

    def test_valid_transition_active_to_completed(self):
        from contracts.mesh_session import MeshSessionStatus, is_valid_lifecycle_transition
        assert is_valid_lifecycle_transition(
            MeshSessionStatus.ACTIVE, MeshSessionStatus.COMPLETED
        ) is True

    def test_invalid_transition_completed_to_active(self):
        from contracts.mesh_session import MeshSessionStatus, is_valid_lifecycle_transition
        assert is_valid_lifecycle_transition(
            MeshSessionStatus.COMPLETED, MeshSessionStatus.ACTIVE
        ) is False

    def test_invalid_transition_active_to_pending(self):
        from contracts.mesh_session import MeshSessionStatus, is_valid_lifecycle_transition
        assert is_valid_lifecycle_transition(
            MeshSessionStatus.ACTIVE, MeshSessionStatus.PENDING
        ) is False

    def test_map_session_status_suspended(self):
        from contracts.mesh_session import _map_session_status, MeshSessionStatus
        assert _map_session_status("suspended") is MeshSessionStatus.SUSPENDED

    def test_map_session_status_restoring(self):
        from contracts.mesh_session import _map_session_status, MeshSessionStatus
        assert _map_session_status("restoring") is MeshSessionStatus.RESTORING

    def test_mesh_session_with_suspended_status(self):
        from contracts.mesh_session import MeshSession, MeshSessionStatus
        session = MeshSession(
            session_id="sess-susp",
            status=MeshSessionStatus.SUSPENDED,
            source_device_id="dev_a",
        )
        assert session.status == MeshSessionStatus.SUSPENDED

    def test_mesh_session_round_trip_suspended_restoring(self):
        from contracts.mesh_session import MeshSession, MeshSessionStatus
        for status in (MeshSessionStatus.SUSPENDED, MeshSessionStatus.RESTORING):
            session = MeshSession(
                session_id=f"sess-{status.value}",
                status=status,
            )
            d = session.to_dict()
            assert d["status"] == status.value
            restored = MeshSession.from_dict(d)
            assert restored.status == status


# ===========================================================================
# 17–42: core/mesh/mesh_session_lifecycle.py
# ===========================================================================


class TestLifecycleSentinels:
    def test_coordinator_authority_sentinel(self):
        from core.mesh.mesh_session_lifecycle import (
            MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY,
        )
        assert isinstance(MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY, str)
        assert "MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY" in (
            MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY
        )

    def test_mutations_persisted_sentinel(self):
        from core.mesh.mesh_session_lifecycle import LIFECYCLE_MUTATIONS_ARE_PERSISTED_POLICY
        assert isinstance(LIFECYCLE_MUTATIONS_ARE_PERSISTED_POLICY, str)

    def test_restore_requires_durable_state_sentinel(self):
        from core.mesh.mesh_session_lifecycle import RESTORE_REQUIRES_DURABLE_STATE_POLICY
        assert isinstance(RESTORE_REQUIRES_DURABLE_STATE_POLICY, str)


class TestMeshSessionLifecycleRecord:
    def test_construction(self):
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleRecord
        rec = MeshSessionLifecycleRecord(
            session_id="s1",
            status="pending",
            session_dict={"foo": "bar"},
        )
        assert rec.session_id == "s1"
        assert rec.status == "pending"
        assert rec.restore_count == 0

    def test_to_dict_keys(self):
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleRecord
        rec = MeshSessionLifecycleRecord(session_id="s1", status="active")
        d = rec.to_dict()
        for key in ("session_id", "status", "created_at", "updated_at", "restore_count", "metadata"):
            assert key in d


class TestMeshSessionLifecycleCoordinator:
    def test_create_session_registers_record(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        session = _make_session_dict("sess-create")
        rec = coord.create_session(session)
        assert rec is not None
        assert rec.session_id == "sess-create"
        assert rec.status == "pending"

    def test_create_session_no_session_id_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        rec = coord.create_session({"session_id": "", "status": "pending"})
        assert rec is None

    def test_activate_session_pending_to_active(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-act"))
        rec = coord.activate_session("sess-act")
        assert rec is not None
        assert rec.status == "active"

    def test_activate_session_invalid_source_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-act-bad"))
        first = coord.activate_session("sess-act-bad")
        assert first is not None
        assert first.status == "active"
        # Already active — activating again should fail (active not in valid_sources)
        rec = coord.activate_session("sess-act-bad")
        assert rec is None

    def test_suspend_session_active_to_suspended(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-susp"))
        coord.activate_session("sess-susp")
        rec = coord.suspend_session("sess-susp", reason="test suspend")
        assert rec is not None
        assert rec.status == "suspended"
        assert rec.metadata.get("suspend_reason") == "test suspend"

    def test_suspend_session_invalid_source_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-susp-bad"))
        # Suspend from pending (invalid)
        rec = coord.suspend_session("sess-susp-bad")
        assert rec is None

    def test_restore_session_from_suspended(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-restore"))
        coord.activate_session("sess-restore")
        coord.suspend_session("sess-restore")
        rec = coord.restore_session("sess-restore")
        assert rec is not None
        assert rec.status == "active"
        assert rec.restore_count >= 1

    def test_restore_session_no_durable_state_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        # No session ever created — nothing in store
        rec = coord.restore_session("nonexistent-sess")
        assert rec is None

    def test_restore_session_terminal_snapshot_not_restored(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-term-restore"))
        coord.activate_session("sess-term-restore")
        coord.terminate_session("sess-term-restore", outcome="completed")
        # Attempt restore after terminal
        rec = coord.restore_session("sess-term-restore")
        assert rec is None

    def test_terminate_completed(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-done"))
        coord.activate_session("sess-done")
        rec = coord.terminate_session("sess-done", outcome="completed")
        assert rec is not None
        assert rec.status == "completed"
        # Verify persistence also marked terminal
        snap = store.load("sess-done")
        assert snap is not None
        assert snap.is_terminal()

    def test_terminate_cancelled(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-cancel"))
        coord.activate_session("sess-cancel")
        rec = coord.terminate_session("sess-cancel", outcome="cancelled")
        assert rec is not None
        assert rec.status == "cancelled"

    def test_terminate_failed(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-fail"))
        coord.activate_session("sess-fail")
        rec = coord.terminate_session("sess-fail", outcome="failed")
        assert rec is not None
        assert rec.status == "failed"

    def test_terminate_invalid_outcome_defaults_to_failed(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-inv"))
        coord.activate_session("sess-inv")
        rec = coord.terminate_session("sess-inv", outcome="nonsense_value")
        assert rec is not None
        assert rec.status == "failed"

    def test_get_record_returns_in_memory_record(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-get"))
        rec = coord.get_record("sess-get")
        assert rec is not None
        assert rec.session_id == "sess-get"

    def test_get_record_unknown_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        # A known session exists, but a different ID returns None
        coord.create_session(_make_session_dict("known-sess"))
        assert coord.get_record("no-such-session") is None

    def test_list_active_session_ids(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("sess-a"))
        coord.create_session(_make_session_dict("sess-b"))
        coord.activate_session("sess-a")
        active = coord.list_active_session_ids()
        assert "sess-a" in active
        assert "sess-b" not in active

    def test_summary_keys(self, tmp_path):
        store = _make_store(str(tmp_path))
        coord = _make_coordinator(store=store)
        coord.create_session(_make_session_dict("s1"))
        summary = coord.summary()
        assert "in_memory_session_count" in summary
        assert "status_breakdown" in summary
        assert "authority" in summary

    def test_get_lifecycle_coordinator_singleton(self, tmp_path):
        from core.mesh.mesh_session_lifecycle import (
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
            MeshSessionLifecycleCoordinator,
        )
        reset_lifecycle_coordinator()
        c1 = get_lifecycle_coordinator()
        c2 = get_lifecycle_coordinator()
        assert c1 is c2
        assert isinstance(c1, MeshSessionLifecycleCoordinator)
        reset_lifecycle_coordinator()

    def test_reset_lifecycle_coordinator(self):
        from core.mesh.mesh_session_lifecycle import (
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )
        reset_lifecycle_coordinator()
        c1 = get_lifecycle_coordinator()
        reset_lifecycle_coordinator()
        c2 = get_lifecycle_coordinator()
        assert c1 is not c2
        reset_lifecycle_coordinator()


class TestModuleLevelLifecycleFunctions:
    def test_create_durable_session(self, tmp_path):
        from core.mesh.mesh_session_lifecycle import (
            create_durable_session,
            MeshSessionLifecycleCoordinator,
        )
        store = _make_store(str(tmp_path))
        coord = MeshSessionLifecycleCoordinator(store=store)
        rec = create_durable_session(
            _make_session_dict("fn-create"), coordinator=coord
        )
        assert rec is not None
        assert rec.session_id == "fn-create"

    def test_activate_durable_session(self, tmp_path):
        from core.mesh.mesh_session_lifecycle import (
            create_durable_session,
            activate_durable_session,
            MeshSessionLifecycleCoordinator,
        )
        store = _make_store(str(tmp_path))
        coord = MeshSessionLifecycleCoordinator(store=store)
        create_durable_session(_make_session_dict("fn-act"), coordinator=coord)
        rec = activate_durable_session("fn-act", coordinator=coord)
        assert rec is not None
        assert rec.status == "active"

    def test_suspend_durable_session(self, tmp_path):
        from core.mesh.mesh_session_lifecycle import (
            create_durable_session,
            activate_durable_session,
            suspend_durable_session,
            MeshSessionLifecycleCoordinator,
        )
        store = _make_store(str(tmp_path))
        coord = MeshSessionLifecycleCoordinator(store=store)
        create_durable_session(_make_session_dict("fn-susp"), coordinator=coord)
        activate_durable_session("fn-susp", coordinator=coord)
        rec = suspend_durable_session("fn-susp", reason="fn test", coordinator=coord)
        assert rec is not None
        assert rec.status == "suspended"

    def test_restore_durable_session(self, tmp_path):
        from core.mesh.mesh_session_lifecycle import (
            create_durable_session,
            activate_durable_session,
            suspend_durable_session,
            restore_durable_session,
            MeshSessionLifecycleCoordinator,
        )
        store = _make_store(str(tmp_path))
        coord = MeshSessionLifecycleCoordinator(store=store)
        create_durable_session(_make_session_dict("fn-restore"), coordinator=coord)
        activate_durable_session("fn-restore", coordinator=coord)
        suspend_durable_session("fn-restore", coordinator=coord)
        rec = restore_durable_session("fn-restore", coordinator=coord)
        assert rec is not None
        assert rec.status == "active"

    def test_terminate_durable_session(self, tmp_path):
        from core.mesh.mesh_session_lifecycle import (
            create_durable_session,
            activate_durable_session,
            terminate_durable_session,
            MeshSessionLifecycleCoordinator,
        )
        store = _make_store(str(tmp_path))
        coord = MeshSessionLifecycleCoordinator(store=store)
        create_durable_session(_make_session_dict("fn-term"), coordinator=coord)
        activate_durable_session("fn-term", coordinator=coord)
        rec = terminate_durable_session("fn-term", outcome="completed", coordinator=coord)
        assert rec is not None
        assert rec.status == "completed"

    def test_core_mesh_init_exports_lifecycle_symbols(self):
        import core.mesh as cm
        assert hasattr(cm, "MeshSessionLifecycleRecord")
        assert hasattr(cm, "MeshSessionLifecycleCoordinator")
        assert hasattr(cm, "get_lifecycle_coordinator")
        assert hasattr(cm, "reset_lifecycle_coordinator")
        assert hasattr(cm, "create_durable_session")
        assert hasattr(cm, "activate_durable_session")
        assert hasattr(cm, "suspend_durable_session")
        assert hasattr(cm, "restore_durable_session")
        assert hasattr(cm, "terminate_durable_session")
        assert hasattr(cm, "MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY")
        assert hasattr(cm, "LIFECYCLE_MUTATIONS_ARE_PERSISTED_POLICY")
        assert hasattr(cm, "RESTORE_REQUIRES_DURABLE_STATE_POLICY")


# ===========================================================================
# 43–46: core/outward_runtime_truth.py — durable_mesh_session_facet
# ===========================================================================


class TestOutwardRuntimeTruthDurableFacet:
    def test_snapshot_has_durable_mesh_session_facet_field(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        import dataclasses
        fields = {f.name for f in dataclasses.fields(OutwardRuntimeTruthSnapshot)}
        assert "durable_mesh_session_facet" in fields

    def test_to_dict_includes_durable_mesh_session_facet_key(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        snap = OutwardRuntimeTruthSnapshot(
            snapshot_id="test-snap",
            compiled_at=0.0,
            durable_mesh_session_facet={"recoverable_session_count": 0},
        )
        d = snap.to_dict()
        assert "durable_mesh_session_facet" in d
        assert d["durable_mesh_session_facet"]["recoverable_session_count"] == 0

    def test_to_dict_durable_mesh_session_facet_none_by_default(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        snap = OutwardRuntimeTruthSnapshot(
            snapshot_id="test-snap-none",
            compiled_at=0.0,
        )
        d = snap.to_dict()
        assert "durable_mesh_session_facet" in d
        assert d["durable_mesh_session_facet"] is None

    def test_compile_outward_truth_includes_durable_mesh_session_source(self):
        from core.outward_runtime_truth import (
            compile_outward_truth,
            reset_outward_runtime_truth_runtime,
        )
        reset_outward_runtime_truth_runtime()
        snap = compile_outward_truth()
        source_names = {r.source_name for r in snap.source_records}
        assert "DurableMeshSessionFacet" in source_names

    def test_durable_mesh_session_facet_populated_with_store_sessions(
        self, tmp_path
    ):
        """When the store has non-terminal sessions, they appear in the facet."""
        from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
        from core.outward_runtime_truth import (
            compile_outward_truth,
            reset_outward_runtime_truth_runtime,
        )
        import unittest.mock as mock

        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        store.save({
            "session_id": "facet-test-sess",
            "coordinator_id": "coord-xyz",
            "overall_status": "coordinating",
        })

        reset_outward_runtime_truth_runtime()

        # Patch recover_mesh_sessions to return our test store's records
        recoverable = store.list_recoverable()
        with mock.patch(
            "core.mesh.mesh_session_persistence.recover_mesh_sessions",
            return_value=recoverable,
        ):
            snap = compile_outward_truth()

        assert snap.durable_mesh_session_facet is not None
        assert snap.durable_mesh_session_facet["recoverable_session_count"] >= 1
        assert "facet-test-sess" in snap.durable_mesh_session_facet.get(
            "recoverable_session_ids", []
        )
