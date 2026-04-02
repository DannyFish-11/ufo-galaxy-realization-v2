#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr519_cross_device_result_surface_closure.py
=========================================================
PR-519 — Cross-Device Result Surface Closure: Tests.

Validates:

A) CROSS_DEVICE_RESULT_SURFACE_AUTHORITY sentinel
   A1. CROSS_DEVICE_RESULT_SURFACE_AUTHORITY is importable.
   A2. CROSS_DEVICE_RESULT_SURFACE_INTEGRATED is importable.
   A3. CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED is importable.
   A4. CROSS_DEVICE_RESULT_SURFACE_LAYER_POSITION is 12.

B) surface_cross_device_result — ResultEnvelope production
   B1. surface_cross_device_result returns a ResultSurfaceRecord.
   B2. result_envelope_produced is True when raw_result is a success dict.
   B3. result_envelope is success=True for {"success": True} input.
   B4. result_envelope is success=False for {"success": False, "error": ...} input.
   B5. task_id propagated from raw_result when not explicitly provided.

C) surface_cross_device_result — ChainExecutionRecord produced
   C1. ChainExecutionRecord is appended to CrossDeviceChainSingleton.
   C2. Chain record carries correct task_id, device_id, route_mode.
   C3. Legacy path is recorded when legacy_path_used is set.
   C4. Chain snapshot reflects the recorded execution.

D) surface_cross_device_result — TaskGraphRuntime update
   D1. task_graph_updated is True after a successful surface call.
   D2. TaskGraphRuntime contains a node for the surfaced task.
   D3. Node reaches COMPLETED state for success result.
   D4. Node reaches FAILED state for failure result.

E) surface_cross_device_result — ReplayFoundation update
   E1. replay_foundation_updated is True after a successful surface call.
   E2. ReplayFoundation ring buffer contains a TASK_COMPLETED event.
   E3. ReplayFoundation ring buffer contains a TASK_FAILED event for failure.

F) surface_cross_device_result — ResultSurfaceRecord classification
   F1. ResultSurfaceKind is CANONICAL_FULL when all surfaces updated.
   F2. surface_gap_reasons list is empty on fully canonical surface.
   F3. ResultSurfaceRecord.is_canonically_surfaced is True on full surface.

G) CrossDeviceCoordinator wiring (GAP-517-007)
   G1. CROSS_DEVICE_RESULT_SURFACE_INTEGRATED sentinel importable from coordinator.
   G2. execute_cross_device_task calls surface_cross_device_result (spy/mock).
   G3. Failure path also calls surface_cross_device_result.

H) DeviceRouter wiring (GAP-517-007)
   H1. CROSS_DEVICE_RESULT_SURFACE_INTEGRATED sentinel importable from device_router.
   H2. route_task result path calls surface_cross_device_result.

I) GAP-517-007 resolved in gap catalog
   I1. GAP-517-007 is_resolved == True.
   I2. Resolution note is non-empty and mentions PR-519.
   I3. GAP-517-008 is still in the catalog with partial resolution note.

J) Projection enrichment (GAP-517-008 partial)
   J1. Projection metadata keys cross_device_chain_snapshot / task_graph_snapshot
       are populated in the metadata when chain data is available.
   J2. result_surface_enriched flag is True.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import unittest
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# A) Authority sentinels
# ===========================================================================

class TestA_AuthoritySentinels(unittest.TestCase):
    """A) Authority sentinels are importable."""

    def test_A1_authority_importable(self):
        from core.cross_device_result_surface import CROSS_DEVICE_RESULT_SURFACE_AUTHORITY
        self.assertIn("PR519", CROSS_DEVICE_RESULT_SURFACE_AUTHORITY)

    def test_A2_integrated_importable(self):
        from core.cross_device_result_surface import CROSS_DEVICE_RESULT_SURFACE_INTEGRATED
        self.assertIn("INTEGRATED", CROSS_DEVICE_RESULT_SURFACE_INTEGRATED)

    def test_A3_gap007_resolved_importable(self):
        from core.cross_device_result_surface import CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED
        self.assertIn("GAP_517_007_RESOLVED", CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED)

    def test_A4_layer_position(self):
        from core.cross_device_result_surface import CROSS_DEVICE_RESULT_SURFACE_LAYER_POSITION
        self.assertEqual(CROSS_DEVICE_RESULT_SURFACE_LAYER_POSITION, 12)


# ===========================================================================
# B) ResultEnvelope production
# ===========================================================================

class TestB_ResultEnvelopeProduction(unittest.TestCase):
    """B) surface_cross_device_result produces a ResultEnvelope."""

    def _call(self, raw_result, **kwargs):
        from core.cross_device_result_surface import surface_cross_device_result
        return surface_cross_device_result(raw_result, **kwargs)

    def test_B1_returns_result_surface_record(self):
        from core.multi_device_control_integrity import ResultSurfaceRecord
        sr = self._call({"success": True}, task_id=str(uuid.uuid4()), device_id="dev-1")
        self.assertIsInstance(sr, ResultSurfaceRecord)

    def test_B2_envelope_produced_for_success(self):
        sr = self._call({"success": True}, task_id=str(uuid.uuid4()))
        self.assertTrue(sr.result_envelope_produced)

    def test_B3_envelope_success_true(self):
        from core.cross_device_execution_chain import get_cross_device_chain
        _tid = str(uuid.uuid4())
        self._call({"success": True, "result": {"data": "ok"}}, task_id=_tid, device_id="dev-2")
        snap = get_cross_device_chain().snapshot()
        records = [r for r in snap.recent_records if r.task_id == _tid]
        self.assertGreater(len(records), 0, "No chain record found for task")
        self.assertIsNotNone(records[-1].result_envelope)
        self.assertTrue(records[-1].result_envelope.success)

    def test_B4_envelope_success_false_for_failure(self):
        from core.cross_device_execution_chain import get_cross_device_chain
        _tid = str(uuid.uuid4())
        self._call({"success": False, "error": "device offline"}, task_id=_tid)
        snap = get_cross_device_chain().snapshot()
        records = [r for r in snap.recent_records if r.task_id == _tid]
        self.assertGreater(len(records), 0)
        self.assertIsNotNone(records[-1].result_envelope)
        self.assertFalse(records[-1].result_envelope.success)

    def test_B5_task_id_from_raw_result(self):
        from core.cross_device_execution_chain import get_cross_device_chain
        _tid = str(uuid.uuid4())
        self._call({"success": True, "task_id": _tid})  # no explicit task_id kwarg
        snap = get_cross_device_chain().snapshot()
        records = [r for r in snap.recent_records if r.task_id == _tid]
        self.assertGreater(len(records), 0)


# ===========================================================================
# C) ChainExecutionRecord
# ===========================================================================

class TestC_ChainExecutionRecord(unittest.TestCase):
    """C) ChainExecutionRecord is produced and appended to the chain singleton."""

    def _call(self, raw_result, **kwargs):
        from core.cross_device_result_surface import surface_cross_device_result
        return surface_cross_device_result(raw_result, **kwargs)

    def test_C1_record_appended(self):
        from core.cross_device_execution_chain import get_cross_device_chain
        _tid = str(uuid.uuid4())
        before = get_cross_device_chain().snapshot().total_executions
        self._call({"success": True}, task_id=_tid)
        after = get_cross_device_chain().snapshot().total_executions
        self.assertGreater(after, before)

    def test_C2_record_fields(self):
        from core.cross_device_execution_chain import get_cross_device_chain
        _tid = str(uuid.uuid4())
        self._call({"success": True}, task_id=_tid, device_id="dev-99",
                   route_mode="multi_device")
        snap = get_cross_device_chain().snapshot()
        records = [r for r in snap.recent_records if r.task_id == _tid]
        self.assertGreater(len(records), 0)
        r = records[-1]
        self.assertEqual(r.device_id, "dev-99")
        self.assertEqual(r.route_mode, "multi_device")

    def test_C3_legacy_path_recorded(self):
        from core.cross_device_execution_chain import get_cross_device_chain
        _tid = str(uuid.uuid4())
        self._call({"success": True}, task_id=_tid,
                   legacy_path_used="cross_device_coordinator.legacy")
        snap = get_cross_device_chain().snapshot()
        records = [r for r in snap.recent_records if r.task_id == _tid]
        self.assertGreater(len(records), 0)
        self.assertEqual(records[-1].legacy_path_used,
                         "cross_device_coordinator.legacy")
        self.assertFalse(records[-1].is_canonical)

    def test_C4_chain_snapshot_reflects_execution(self):
        from core.cross_device_execution_chain import (
            get_cross_device_chain,
            build_cross_device_chain_snapshot,
        )
        _tid = str(uuid.uuid4())
        self._call({"success": True}, task_id=_tid)
        snap = build_cross_device_chain_snapshot()
        self.assertGreater(snap.total_executions, 0)


# ===========================================================================
# D) TaskGraphRuntime update
# ===========================================================================

class TestD_TaskGraphRuntimeUpdate(unittest.TestCase):
    """D) TaskGraphRuntime is updated by surface_cross_device_result."""

    def _call(self, raw_result, **kwargs):
        from core.cross_device_result_surface import surface_cross_device_result
        return surface_cross_device_result(raw_result, **kwargs)

    def test_D1_task_graph_updated_flag(self):
        _tid = str(uuid.uuid4())
        sr = self._call({"success": True}, task_id=_tid)
        self.assertTrue(sr.task_graph_updated)

    def test_D2_tgr_has_node(self):
        from core.task_graph_runtime import get_task_graph_runtime
        _tid = str(uuid.uuid4())
        self._call({"success": True}, task_id=_tid, device_id="dev-tgr-1")
        tgr = get_task_graph_runtime()
        self.assertIsNotNone(tgr.get_node_by_task_id(_tid))

    def test_D3_completed_state_for_success(self):
        from core.task_graph_runtime import get_task_graph_runtime, GraphNodeState
        _tid = str(uuid.uuid4())
        self._call({"success": True}, task_id=_tid)
        node = get_task_graph_runtime().get_node_by_task_id(_tid)
        self.assertIsNotNone(node)
        self.assertEqual(node.state, GraphNodeState.COMPLETED)

    def test_D4_failed_state_for_failure(self):
        from core.task_graph_runtime import get_task_graph_runtime, GraphNodeState
        _tid = str(uuid.uuid4())
        self._call({"success": False, "error": "timeout"}, task_id=_tid)
        node = get_task_graph_runtime().get_node_by_task_id(_tid)
        self.assertIsNotNone(node)
        self.assertEqual(node.state, GraphNodeState.FAILED)


# ===========================================================================
# E) ReplayFoundation update
# ===========================================================================

class TestE_ReplayFoundationUpdate(unittest.TestCase):
    """E) ReplayFoundation receives runtime events."""

    def _call(self, raw_result, **kwargs):
        from core.cross_device_result_surface import surface_cross_device_result
        return surface_cross_device_result(raw_result, **kwargs)

    def test_E1_replay_updated_flag(self):
        _tid = str(uuid.uuid4())
        sr = self._call({"success": True}, task_id=_tid)
        self.assertTrue(sr.replay_foundation_updated)

    def test_E2_task_completed_event_in_buffer(self):
        from core.replay_foundation import get_replay_foundation, ReplayEventKind
        _tid = str(uuid.uuid4())
        self._call({"success": True}, task_id=_tid, trace_id="tr-e2")
        rf = get_replay_foundation()
        snap = rf.snapshot()
        events = [
            e for e in snap.recent_runtime_events
            if e.get("task_id") == _tid
            and e.get("kind") == ReplayEventKind.TASK_COMPLETED
        ]
        self.assertGreater(len(events), 0, "No TASK_COMPLETED event found")

    def test_E3_task_failed_event_in_buffer(self):
        from core.replay_foundation import get_replay_foundation, ReplayEventKind
        _tid = str(uuid.uuid4())
        self._call({"success": False, "error": "device unreachable"}, task_id=_tid)
        rf = get_replay_foundation()
        snap = rf.snapshot()
        events = [
            e for e in snap.recent_runtime_events
            if e.get("task_id") == _tid
            and e.get("kind") == ReplayEventKind.TASK_FAILED
        ]
        self.assertGreater(len(events), 0, "No TASK_FAILED event found")


# ===========================================================================
# F) ResultSurfaceRecord classification
# ===========================================================================

class TestF_ResultSurfaceClassification(unittest.TestCase):
    """F) ResultSurfaceRecord is classified correctly."""

    def _call(self, raw_result, **kwargs):
        from core.cross_device_result_surface import surface_cross_device_result
        return surface_cross_device_result(raw_result, **kwargs)

    def test_F1_canonical_full_when_all_surfaces_updated(self):
        from core.multi_device_control_integrity import ResultSurfaceKind
        _tid = str(uuid.uuid4())
        sr = self._call({"success": True}, task_id=_tid)
        # result_envelope + task_graph + replay all updated → CANONICAL_FULL
        self.assertEqual(sr.surface_kind, ResultSurfaceKind.CANONICAL_FULL)

    def test_F2_no_gap_reasons_on_full_surface(self):
        _tid = str(uuid.uuid4())
        sr = self._call({"success": True}, task_id=_tid)
        self.assertEqual(sr.surface_gap_reasons, [])

    def test_F3_is_canonically_surfaced_true(self):
        _tid = str(uuid.uuid4())
        sr = self._call({"success": True}, task_id=_tid)
        self.assertTrue(sr.is_canonically_surfaced)


# ===========================================================================
# G) CrossDeviceCoordinator wiring
# ===========================================================================

class TestG_CoordinatorWiring(unittest.TestCase):
    """G) CrossDeviceCoordinator is wired to surface_cross_device_result."""

    def test_G1_sentinel_importable_from_coordinator(self):
        from galaxy_gateway.cross_device_coordinator import (
            CROSS_DEVICE_RESULT_SURFACE_INTEGRATED,
        )
        self.assertIn("INTEGRATED", CROSS_DEVICE_RESULT_SURFACE_INTEGRATED)

    def test_G2_execute_calls_surface(self):
        """execute_cross_device_task calls surface_cross_device_result."""
        with patch(
            "galaxy_gateway.cross_device_coordinator.surface_cross_device_result"
        ) as mock_surface:
            from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
            coord = CrossDeviceCoordinator()
            coord._analyze_cross_device_task = MagicMock(return_value="generic")
            coord._execute_generic_cross_device_task = AsyncMock(
                return_value={"success": True, "data": "done"}
            )
            _run(coord.execute_cross_device_task(
                "test command",
                {"task_id": "t-g2"},
                _substrate_caller="test",
            ))
            mock_surface.assert_called_once()

    def test_G3_failure_path_calls_surface(self):
        """Failure path in execute_cross_device_task also calls surface."""
        with patch(
            "galaxy_gateway.cross_device_coordinator.surface_cross_device_result"
        ) as mock_surface:
            from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
            coord = CrossDeviceCoordinator()
            coord._analyze_cross_device_task = MagicMock(return_value="generic")
            coord._execute_generic_cross_device_task = AsyncMock(
                side_effect=RuntimeError("device offline")
            )
            result = _run(coord.execute_cross_device_task(
                "test command",
                {"task_id": "t-g3"},
                _substrate_caller="test",
            ))
            self.assertFalse(result.get("success"))
            mock_surface.assert_called_once()


# ===========================================================================
# H) DeviceRouter wiring
# ===========================================================================

class TestH_DeviceRouterWiring(unittest.TestCase):
    """H) DeviceRouter is wired to surface_cross_device_result."""

    def test_H1_sentinel_importable_from_device_router(self):
        from galaxy_gateway.device_router import CROSS_DEVICE_RESULT_SURFACE_INTEGRATED
        self.assertIn("INTEGRATED", CROSS_DEVICE_RESULT_SURFACE_INTEGRATED)

    def test_H2_route_task_calls_surface_after_dispatch(self):
        """route_task calls surface_cross_device_result after dispatch."""
        with patch(
            "galaxy_gateway.device_router.surface_cross_device_result"
        ) as mock_surface:
            from galaxy_gateway.device_router import DeviceRouter

            router = DeviceRouter()
            _fake_device = MagicMock()
            _fake_device.device_id = "phone-001"
            router._analyze_command = AsyncMock(return_value={
                "requires_cross_device": False,
                "exec_mode": "both",
                "task_type": "command",
            })
            router._select_devices = MagicMock(return_value=[_fake_device])
            router._create_task = MagicMock(return_value={"task_id": "t-h2"})
            router.dispatch_task = AsyncMock(
                return_value={"success": True, "result": "done"}
            )

            result = _run(router.route_task("test command", {"task_id": "t-h2"}))
            self.assertTrue(result.get("success"))
            mock_surface.assert_called_once()


# ===========================================================================
# I) GAP-517-007 resolved in gap catalog
# ===========================================================================

class TestI_GapCatalog(unittest.TestCase):
    """I) GAP-517-007 is resolved in the integrity gap catalog."""

    def _get_gap(self, gap_id: str):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        for g in get_residual_integrity_gaps():
            if g.gap_id == gap_id:
                return g
        return None

    def test_I1_gap007_resolved(self):
        g = self._get_gap("GAP-517-007")
        self.assertIsNotNone(g, "GAP-517-007 not found in catalog")
        self.assertTrue(g.is_resolved, "GAP-517-007 should be resolved")

    def test_I2_gap007_resolution_note_mentions_pr519(self):
        g = self._get_gap("GAP-517-007")
        self.assertIsNotNone(g)
        self.assertIn("PR-519", g.resolution_note)

    def test_I3_gap008_still_present_with_partial_note(self):
        g = self._get_gap("GAP-517-008")
        self.assertIsNotNone(g, "GAP-517-008 not found in catalog")
        # partial resolution note mentions PR-519
        self.assertIn("PR-519", g.resolution_note)

    def test_I4_gap007_severity_high(self):
        g = self._get_gap("GAP-517-007")
        self.assertIsNotNone(g)
        self.assertEqual(g.severity, "HIGH")


# ===========================================================================
# J) Projection enrichment (GAP-517-008 partial)
# ===========================================================================

class TestJ_ProjectionEnrichment(unittest.TestCase):
    """J) multi-device projection includes chain and task-graph snapshots."""

    def test_J1_metadata_contains_chain_and_tgr_snapshots(self):
        """build_multi_device_runtime_projection metadata enriched when called
        with chain_snapshot and task_graph_snapshot."""
        from contracts.multi_device_runtime_projection import (
            build_multi_device_runtime_projection,
        )
        # Simulate how the projection endpoint now calls build with metadata
        proj = build_multi_device_runtime_projection(
            metadata={
                "cross_device_chain_snapshot": {
                    "total_executions": 5,
                    "canonical_executions": 3,
                },
                "task_graph_snapshot": {"total_nodes": 2, "recent_records": []},
                "result_surface_enriched": True,
                "pr_519_gap_008_partial": True,
            }
        )
        meta = proj.metadata
        self.assertIn("cross_device_chain_snapshot", meta)
        self.assertIn("task_graph_snapshot", meta)
        self.assertTrue(meta.get("result_surface_enriched"))

    def test_J2_result_surface_enriched_flag(self):
        from contracts.multi_device_runtime_projection import (
            build_multi_device_runtime_projection,
        )
        proj = build_multi_device_runtime_projection(
            metadata={"result_surface_enriched": True}
        )
        self.assertTrue(proj.metadata.get("result_surface_enriched"))


if __name__ == "__main__":
    unittest.main()
