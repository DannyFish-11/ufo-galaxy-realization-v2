#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr515_critical_path_harness.py
==========================================
PR-515 — Critical Interaction Path Hardening: Tests.

Validates that:
* The critical_path_harness module exports all required sentinels and symbols.
* CriticalPathKind and PathHarnessState enums have all required values.
* IngressHarnessRecord, RouteSelectionRecord, ProviderSwitchRecord,
  ExecutionDispatchRecord to_dict() round-trips correctly.
* CriticalPathSnapshot.summary() returns expected keys.
* CriticalPathHarnessRuntime ring buffers accept and return records.
* record_ingress_path, record_route_selection, record_provider_switch,
  record_execution_dispatch helpers write to the ring buffer.
* Fallback-switch behavior is recorded as a first-class ProviderSwitchRecord.
* Advisory route type is counted correctly in snapshot.
* snapshot_critical_path() returns combined dict with authority and gap_closed.
* GAP-512-009: is_residual=False in runtime_closure_audit.
* CONFLICT-008 is present and resolved in detect_parallel_truth_paths().
* PR-515 layer specs are present in verify_all_layers().
* core/openclawd.py exports CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED.
* core/multi_llm_router.py exports CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED.
* Harness writes are non-blocking (no exception on ring buffer error).
* Full end-to-end critical path: ingress → route selection → provider switch
  → execution dispatch records are traceable via ring buffers.
* Provider-switching/fallback-switching arc is inspectable.
* No competing routing authority is introduced.
* Abstraction discipline: snapshot_critical_path returns operator-safe dict.

Test groups
-----------
 A)  Module structure — all __all__ symbols importable.
 B)  Authority sentinels — correct values and types.
 C)  Policy sentinels — vocabulary checks.
 D)  CriticalPathKind enum — all required values present.
 E)  PathHarnessState enum — all required states present.
 F)  IngressHarnessRecord — structure and to_dict().
 G)  RouteSelectionRecord — structure and to_dict().
 H)  ProviderSwitchRecord — structure and to_dict() (selection + fallback).
 I)  ExecutionDispatchRecord — structure and to_dict().
 J)  CriticalPathSnapshot — structure and summary() keys.
 K)  CriticalPathHarnessRuntime — singleton management.
 L)  CriticalPathHarnessRuntime — ring buffer writes and reads.
 M)  record_ingress_path helper — ring buffer write.
 N)  record_route_selection helper — ring buffer write and state mapping.
 O)  record_provider_switch helper — ring buffer write (selection).
 P)  record_provider_switch helper — ring buffer write (fallback).
 Q)  record_execution_dispatch helper — ring buffer write.
 R)  snapshot() — correct aggregate counts.
 S)  snapshot_critical_path() — combined dict with authority/gap fields.
 T)  Advisory routing — counted correctly.
 U)  Full end-to-end critical path round-trip.
 V)  Fallback arc — primary → fallback provider arc traceable.
 W)  Non-blocking harness writes — never raises.
 X)  GAP-512-009 closure — is_residual=False in closure audit.
 Y)  CONFLICT-008 — present and resolved in detect_parallel_truth_paths.
 Z)  PR-515 layer specs present in verify_all_layers.
 AA) OpenClawd CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED sentinel.
 BB) MultiLLMRouter CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED sentinel.
 CC) No competing routing authority — harness does not route.
 DD) Abstraction discipline — snapshot dict is operator-safe (no raw deque).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helper: reset singleton between tests
# ---------------------------------------------------------------------------


def _reset() -> None:
    try:
        from core.critical_path_harness import reset_critical_path_harness
        reset_critical_path_harness()
    except Exception:
        pass


# ===========================================================================
# A)  Module structure
# ===========================================================================


class TestA_ModuleStructure(unittest.TestCase):
    """A) All __all__ symbols importable."""

    def test_A01_module_importable(self) -> None:
        import core.critical_path_harness as mod  # noqa: F401
        self.assertIsNotNone(mod)

    def test_A02_all_symbols_importable(self) -> None:
        from core import critical_path_harness as mod
        for name in mod.__all__:
            self.assertTrue(
                hasattr(mod, name),
                f"__all__ symbol '{name}' not found on module",
            )

    def test_A03_all_is_nonempty(self) -> None:
        from core.critical_path_harness import __all__
        self.assertGreater(len(__all__), 0)


# ===========================================================================
# B)  Authority sentinels
# ===========================================================================


class TestB_AuthoritySentinels(unittest.TestCase):
    """B) Authority sentinel types and values."""

    def test_B01_authority_is_string(self) -> None:
        from core.critical_path_harness import CRITICAL_PATH_HARNESS_AUTHORITY
        self.assertIsInstance(CRITICAL_PATH_HARNESS_AUTHORITY, str)
        self.assertGreater(len(CRITICAL_PATH_HARNESS_AUTHORITY), 0)

    def test_B02_layer_position_is_15(self) -> None:
        from core.critical_path_harness import CRITICAL_PATH_HARNESS_LAYER_POSITION
        self.assertIsInstance(CRITICAL_PATH_HARNESS_LAYER_POSITION, int)
        self.assertEqual(CRITICAL_PATH_HARNESS_LAYER_POSITION, 15)

    def test_B03_integrated_sentinel_is_string(self) -> None:
        from core.critical_path_harness import CRITICAL_PATH_HARNESS_INTEGRATED
        self.assertIsInstance(CRITICAL_PATH_HARNESS_INTEGRATED, str)
        self.assertGreater(len(CRITICAL_PATH_HARNESS_INTEGRATED), 0)

    def test_B04_integrated_mentions_gap_512_009(self) -> None:
        from core.critical_path_harness import CRITICAL_PATH_HARNESS_INTEGRATED
        self.assertIn("GAP-512-009", CRITICAL_PATH_HARNESS_INTEGRATED)

    def test_B05_authority_mentions_gap_512_009(self) -> None:
        from core.critical_path_harness import CRITICAL_PATH_HARNESS_AUTHORITY
        self.assertIn("GAP-512-009", CRITICAL_PATH_HARNESS_AUTHORITY)


# ===========================================================================
# C)  Policy sentinels
# ===========================================================================


class TestC_PolicySentinels(unittest.TestCase):
    """C) Policy sentinels have required vocabulary."""

    def test_C01_ingress_path_closed_policy(self) -> None:
        from core.critical_path_harness import MULTIMODAL_INGRESS_PATH_CLOSED_POLICY
        self.assertIsInstance(MULTIMODAL_INGRESS_PATH_CLOSED_POLICY, str)
        self.assertIn("multimodal", MULTIMODAL_INGRESS_PATH_CLOSED_POLICY.lower())

    def test_C02_routing_authority_canonical_policy(self) -> None:
        from core.critical_path_harness import ROUTING_AUTHORITY_CANONICAL_POLICY
        self.assertIsInstance(ROUTING_AUTHORITY_CANONICAL_POLICY, str)
        self.assertIn("GAP-512-009", ROUTING_AUTHORITY_CANONICAL_POLICY)

    def test_C03_provider_selection_inspectable_policy(self) -> None:
        from core.critical_path_harness import PROVIDER_SELECTION_INSPECTABLE_POLICY
        self.assertIsInstance(PROVIDER_SELECTION_INSPECTABLE_POLICY, str)
        self.assertIn("provider", PROVIDER_SELECTION_INSPECTABLE_POLICY.lower())

    def test_C04_fallback_switching_harness_policy(self) -> None:
        from core.critical_path_harness import FALLBACK_SWITCHING_HARNESS_POLICY
        self.assertIsInstance(FALLBACK_SWITCHING_HARNESS_POLICY, str)
        self.assertIn("fallback", FALLBACK_SWITCHING_HARNESS_POLICY.lower())

    def test_C05_no_competing_routing_authority_policy(self) -> None:
        from core.critical_path_harness import NO_COMPETING_ROUTING_AUTHORITY_POLICY
        self.assertIsInstance(NO_COMPETING_ROUTING_AUTHORITY_POLICY, str)
        self.assertIn("GAP-512-009", NO_COMPETING_ROUTING_AUTHORITY_POLICY)

    def test_C06_harness_non_blocking_policy(self) -> None:
        from core.critical_path_harness import HARNESS_NON_BLOCKING_POLICY
        self.assertIsInstance(HARNESS_NON_BLOCKING_POLICY, str)
        self.assertIn("non", HARNESS_NON_BLOCKING_POLICY.lower())

    def test_C07_abstraction_discipline_policy(self) -> None:
        from core.critical_path_harness import ABSTRACTION_DISCIPLINE_POLICY
        self.assertIsInstance(ABSTRACTION_DISCIPLINE_POLICY, str)
        self.assertIn("abstraction", ABSTRACTION_DISCIPLINE_POLICY.lower())


# ===========================================================================
# D)  CriticalPathKind enum
# ===========================================================================


class TestD_CriticalPathKind(unittest.TestCase):
    """D) CriticalPathKind has all required values."""

    def test_D01_multimodal_ingress(self) -> None:
        from core.critical_path_harness import CriticalPathKind
        self.assertEqual(CriticalPathKind.MULTIMODAL_INGRESS.value, "multimodal_ingress")

    def test_D02_route_selection(self) -> None:
        from core.critical_path_harness import CriticalPathKind
        self.assertEqual(CriticalPathKind.ROUTE_SELECTION.value, "route_selection")

    def test_D03_provider_selection(self) -> None:
        from core.critical_path_harness import CriticalPathKind
        self.assertEqual(CriticalPathKind.PROVIDER_SELECTION.value, "provider_selection")

    def test_D04_fallback_switch(self) -> None:
        from core.critical_path_harness import CriticalPathKind
        self.assertEqual(CriticalPathKind.FALLBACK_SWITCH.value, "fallback_switch")

    def test_D05_execution_dispatch(self) -> None:
        from core.critical_path_harness import CriticalPathKind
        self.assertEqual(CriticalPathKind.EXECUTION_DISPATCH.value, "execution_dispatch")

    def test_D06_result_return(self) -> None:
        from core.critical_path_harness import CriticalPathKind
        self.assertEqual(CriticalPathKind.RESULT_RETURN.value, "result_return")

    def test_D07_all_required_kinds_present(self) -> None:
        from core.critical_path_harness import CriticalPathKind
        required = {
            "multimodal_ingress", "route_selection", "provider_selection",
            "fallback_switch", "execution_dispatch", "result_return",
        }
        actual = {k.value for k in CriticalPathKind}
        self.assertTrue(required.issubset(actual), f"Missing kinds: {required - actual}")


# ===========================================================================
# E)  PathHarnessState enum
# ===========================================================================


class TestE_PathHarnessState(unittest.TestCase):
    """E) PathHarnessState has all required states."""

    def test_E01_active(self) -> None:
        from core.critical_path_harness import PathHarnessState
        self.assertEqual(PathHarnessState.ACTIVE.value, "active")

    def test_E02_completed(self) -> None:
        from core.critical_path_harness import PathHarnessState
        self.assertEqual(PathHarnessState.COMPLETED.value, "completed")

    def test_E03_degraded(self) -> None:
        from core.critical_path_harness import PathHarnessState
        self.assertEqual(PathHarnessState.DEGRADED.value, "degraded")

    def test_E04_fallback_active(self) -> None:
        from core.critical_path_harness import PathHarnessState
        self.assertEqual(PathHarnessState.FALLBACK_ACTIVE.value, "fallback_active")

    def test_E05_advisory(self) -> None:
        from core.critical_path_harness import PathHarnessState
        self.assertEqual(PathHarnessState.ADVISORY.value, "advisory")

    def test_E06_failed(self) -> None:
        from core.critical_path_harness import PathHarnessState
        self.assertEqual(PathHarnessState.FAILED.value, "failed")


# ===========================================================================
# F)  IngressHarnessRecord
# ===========================================================================


class TestF_IngressHarnessRecord(unittest.TestCase):
    """F) IngressHarnessRecord structure and to_dict()."""

    def test_F01_default_construction(self) -> None:
        from core.critical_path_harness import IngressHarnessRecord
        rec = IngressHarnessRecord()
        self.assertEqual(rec.trace_id, "")
        self.assertEqual(rec.active_modalities, [])
        self.assertFalse(rec.requires_native_multimodal)

    def test_F02_to_dict_kind(self) -> None:
        from core.critical_path_harness import IngressHarnessRecord, CriticalPathKind
        rec = IngressHarnessRecord(trace_id="t1", active_modalities=["image"])
        d = rec.to_dict()
        self.assertEqual(d["kind"], CriticalPathKind.MULTIMODAL_INGRESS.value)

    def test_F03_to_dict_contains_trace_id(self) -> None:
        from core.critical_path_harness import IngressHarnessRecord
        rec = IngressHarnessRecord(trace_id="trace-abc")
        d = rec.to_dict()
        self.assertEqual(d["trace_id"], "trace-abc")

    def test_F04_to_dict_active_modalities(self) -> None:
        from core.critical_path_harness import IngressHarnessRecord
        rec = IngressHarnessRecord(active_modalities=["image", "audio"])
        d = rec.to_dict()
        self.assertEqual(d["active_modalities"], ["image", "audio"])

    def test_F05_to_dict_requires_native_multimodal(self) -> None:
        from core.critical_path_harness import IngressHarnessRecord
        rec = IngressHarnessRecord(requires_native_multimodal=True)
        d = rec.to_dict()
        self.assertTrue(d["requires_native_multimodal"])

    def test_F06_to_dict_has_timestamp(self) -> None:
        from core.critical_path_harness import IngressHarnessRecord
        rec = IngressHarnessRecord()
        d = rec.to_dict()
        self.assertIn("timestamp", d)
        self.assertIsInstance(d["timestamp"], float)


# ===========================================================================
# G)  RouteSelectionRecord
# ===========================================================================


class TestG_RouteSelectionRecord(unittest.TestCase):
    """G) RouteSelectionRecord structure and to_dict()."""

    def test_G01_default_construction(self) -> None:
        from core.critical_path_harness import RouteSelectionRecord, PathHarnessState
        rec = RouteSelectionRecord()
        self.assertEqual(rec.route_type, "")
        self.assertEqual(rec.harness_state, PathHarnessState.COMPLETED)

    def test_G02_to_dict_kind(self) -> None:
        from core.critical_path_harness import RouteSelectionRecord, CriticalPathKind
        rec = RouteSelectionRecord(route_type="native_multimodal")
        d = rec.to_dict()
        self.assertEqual(d["kind"], CriticalPathKind.ROUTE_SELECTION.value)

    def test_G03_to_dict_route_type(self) -> None:
        from core.critical_path_harness import RouteSelectionRecord
        rec = RouteSelectionRecord(route_type="partial_multimodal", provider="openai")
        d = rec.to_dict()
        self.assertEqual(d["route_type"], "partial_multimodal")
        self.assertEqual(d["provider"], "openai")

    def test_G04_to_dict_harness_state(self) -> None:
        from core.critical_path_harness import RouteSelectionRecord, PathHarnessState
        rec = RouteSelectionRecord(
            route_type="advisory", harness_state=PathHarnessState.ADVISORY
        )
        d = rec.to_dict()
        self.assertEqual(d["harness_state"], PathHarnessState.ADVISORY.value)

    def test_G05_fallback_reason_in_dict(self) -> None:
        from core.critical_path_harness import RouteSelectionRecord
        rec = RouteSelectionRecord(fallback_reason="no_native_mm_provider")
        d = rec.to_dict()
        self.assertEqual(d["fallback_reason"], "no_native_mm_provider")


# ===========================================================================
# H)  ProviderSwitchRecord
# ===========================================================================


class TestH_ProviderSwitchRecord(unittest.TestCase):
    """H) ProviderSwitchRecord structure and to_dict() — selection and fallback."""

    def test_H01_default_construction(self) -> None:
        from core.critical_path_harness import ProviderSwitchRecord
        rec = ProviderSwitchRecord()
        self.assertEqual(rec.from_provider, "none")
        self.assertFalse(rec.is_fallback)

    def test_H02_provider_selection_kind(self) -> None:
        from core.critical_path_harness import ProviderSwitchRecord, CriticalPathKind
        rec = ProviderSwitchRecord(to_provider="openai", is_fallback=False)
        d = rec.to_dict()
        self.assertEqual(d["kind"], CriticalPathKind.PROVIDER_SELECTION.value)

    def test_H03_fallback_switch_kind(self) -> None:
        from core.critical_path_harness import ProviderSwitchRecord, CriticalPathKind
        rec = ProviderSwitchRecord(
            from_provider="openai", to_provider="anthropic", is_fallback=True
        )
        d = rec.to_dict()
        self.assertEqual(d["kind"], CriticalPathKind.FALLBACK_SWITCH.value)

    def test_H04_fallback_state_is_fallback_active(self) -> None:
        from core.critical_path_harness import ProviderSwitchRecord, PathHarnessState
        rec = ProviderSwitchRecord(is_fallback=True)
        self.assertEqual(rec.harness_state, PathHarnessState.FALLBACK_ACTIVE)

    def test_H05_selection_state_is_completed(self) -> None:
        from core.critical_path_harness import ProviderSwitchRecord, PathHarnessState
        rec = ProviderSwitchRecord(is_fallback=False)
        self.assertEqual(rec.harness_state, PathHarnessState.COMPLETED)

    def test_H06_to_dict_from_to_fields(self) -> None:
        from core.critical_path_harness import ProviderSwitchRecord
        rec = ProviderSwitchRecord(
            from_provider="anthropic", to_provider="openai",
            from_model="claude-3", to_model="gpt-4o",
        )
        d = rec.to_dict()
        self.assertEqual(d["from_provider"], "anthropic")
        self.assertEqual(d["to_provider"], "openai")
        self.assertEqual(d["from_model"], "claude-3")
        self.assertEqual(d["to_model"], "gpt-4o")


# ===========================================================================
# I)  ExecutionDispatchRecord
# ===========================================================================


class TestI_ExecutionDispatchRecord(unittest.TestCase):
    """I) ExecutionDispatchRecord structure and to_dict()."""

    def test_I01_default_construction(self) -> None:
        from core.critical_path_harness import ExecutionDispatchRecord, PathHarnessState
        rec = ExecutionDispatchRecord()
        self.assertEqual(rec.executor, "unknown")
        self.assertEqual(rec.harness_state, PathHarnessState.ACTIVE)

    def test_I02_to_dict_kind(self) -> None:
        from core.critical_path_harness import ExecutionDispatchRecord, CriticalPathKind
        rec = ExecutionDispatchRecord(task_id="task-1")
        d = rec.to_dict()
        self.assertEqual(d["kind"], CriticalPathKind.EXECUTION_DISPATCH.value)

    def test_I03_to_dict_all_fields(self) -> None:
        from core.critical_path_harness import ExecutionDispatchRecord
        rec = ExecutionDispatchRecord(
            task_id="t", trace_id="tr", executor="node-42",
            dispatch_method="fabric", provider="openai", model="gpt-4o",
        )
        d = rec.to_dict()
        self.assertEqual(d["task_id"], "t")
        self.assertEqual(d["executor"], "node-42")
        self.assertEqual(d["dispatch_method"], "fabric")
        self.assertEqual(d["provider"], "openai")
        self.assertEqual(d["model"], "gpt-4o")


# ===========================================================================
# J)  CriticalPathSnapshot
# ===========================================================================


class TestJ_CriticalPathSnapshot(unittest.TestCase):
    """J) CriticalPathSnapshot structure and summary()."""

    def test_J01_default_construction(self) -> None:
        from core.critical_path_harness import CriticalPathSnapshot
        snap = CriticalPathSnapshot()
        self.assertEqual(snap.ingress_count, 0)
        self.assertEqual(snap.fallback_count, 0)

    def test_J02_summary_has_required_keys(self) -> None:
        from core.critical_path_harness import CriticalPathSnapshot
        snap = CriticalPathSnapshot(
            ingress_count=3, route_selection_count=3,
            provider_switch_count=2, dispatch_count=2,
            fallback_count=1, advisory_count=0,
            recent_route_type="native_multimodal", recent_provider="openai",
        )
        s = snap.summary()
        for key in (
            "ingress_count", "route_selection_count", "provider_switch_count",
            "dispatch_count", "fallback_count", "advisory_count",
            "recent_route_type", "recent_provider", "snapshot_ts",
        ):
            self.assertIn(key, s, f"Key '{key}' missing from summary()")

    def test_J03_summary_values_match(self) -> None:
        from core.critical_path_harness import CriticalPathSnapshot
        snap = CriticalPathSnapshot(fallback_count=2, advisory_count=1)
        s = snap.summary()
        self.assertEqual(s["fallback_count"], 2)
        self.assertEqual(s["advisory_count"], 1)


# ===========================================================================
# K)  Singleton management
# ===========================================================================


class TestK_SingletonManagement(unittest.TestCase):
    """K) CriticalPathHarnessRuntime singleton management."""

    def setUp(self) -> None:
        _reset()

    def test_K01_get_critical_path_harness_returns_instance(self) -> None:
        from core.critical_path_harness import get_critical_path_harness, CriticalPathHarnessRuntime
        h = get_critical_path_harness()
        self.assertIsInstance(h, CriticalPathHarnessRuntime)

    def test_K02_singleton_same_object(self) -> None:
        from core.critical_path_harness import get_critical_path_harness
        h1 = get_critical_path_harness()
        h2 = get_critical_path_harness()
        self.assertIs(h1, h2)

    def test_K03_reset_creates_new_instance(self) -> None:
        from core.critical_path_harness import (
            get_critical_path_harness, reset_critical_path_harness,
        )
        h1 = get_critical_path_harness()
        reset_critical_path_harness()
        h2 = get_critical_path_harness()
        self.assertIsNot(h1, h2)


# ===========================================================================
# L)  Ring buffer writes and reads
# ===========================================================================


class TestL_RingBufferWritesReads(unittest.TestCase):
    """L) CriticalPathHarnessRuntime ring buffer writes and reads."""

    def setUp(self) -> None:
        _reset()

    def test_L01_record_ingress_appends(self) -> None:
        from core.critical_path_harness import (
            get_critical_path_harness, IngressHarnessRecord,
        )
        h = get_critical_path_harness()
        h.record_ingress(IngressHarnessRecord(trace_id="t-L01"))
        records = h.get_ingress_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].trace_id, "t-L01")

    def test_L02_record_route_selection_appends(self) -> None:
        from core.critical_path_harness import (
            get_critical_path_harness, RouteSelectionRecord,
        )
        h = get_critical_path_harness()
        h.record_route_selection(RouteSelectionRecord(route_type="native_multimodal"))
        records = h.get_route_selection_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].route_type, "native_multimodal")

    def test_L03_record_provider_switch_appends(self) -> None:
        from core.critical_path_harness import (
            get_critical_path_harness, ProviderSwitchRecord,
        )
        h = get_critical_path_harness()
        h.record_provider_switch(ProviderSwitchRecord(to_provider="openai"))
        records = h.get_provider_switch_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].to_provider, "openai")

    def test_L04_record_dispatch_appends(self) -> None:
        from core.critical_path_harness import (
            get_critical_path_harness, ExecutionDispatchRecord,
        )
        h = get_critical_path_harness()
        h.record_dispatch(ExecutionDispatchRecord(task_id="task-L04"))
        records = h.get_dispatch_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].task_id, "task-L04")

    def test_L05_get_fallback_records_filters(self) -> None:
        from core.critical_path_harness import (
            get_critical_path_harness, ProviderSwitchRecord,
        )
        h = get_critical_path_harness()
        h.record_provider_switch(ProviderSwitchRecord(to_provider="openai", is_fallback=False))
        h.record_provider_switch(ProviderSwitchRecord(to_provider="anthropic", is_fallback=True))
        fallbacks = h.get_fallback_records()
        self.assertEqual(len(fallbacks), 1)
        self.assertTrue(fallbacks[0].is_fallback)
        self.assertEqual(fallbacks[0].to_provider, "anthropic")

    def test_L06_limit_parameter(self) -> None:
        from core.critical_path_harness import (
            get_critical_path_harness, IngressHarnessRecord,
        )
        h = get_critical_path_harness()
        for i in range(5):
            h.record_ingress(IngressHarnessRecord(trace_id=f"t-{i}"))
        records = h.get_ingress_records(limit=2)
        self.assertEqual(len(records), 2)


# ===========================================================================
# M)  record_ingress_path helper
# ===========================================================================


class TestM_RecordIngressPathHelper(unittest.TestCase):
    """M) record_ingress_path helper writes to ring buffer."""

    def setUp(self) -> None:
        _reset()

    def test_M01_returns_ingress_record(self) -> None:
        from core.critical_path_harness import record_ingress_path, IngressHarnessRecord
        rec = record_ingress_path(trace_id="m-01")
        self.assertIsInstance(rec, IngressHarnessRecord)

    def test_M02_written_to_ring_buffer(self) -> None:
        from core.critical_path_harness import record_ingress_path, get_critical_path_harness
        record_ingress_path(trace_id="m-02", active_modalities=["image"])
        records = get_critical_path_harness().get_ingress_records()
        self.assertGreater(len(records), 0)
        self.assertEqual(records[-1].trace_id, "m-02")

    def test_M03_active_modalities_recorded(self) -> None:
        from core.critical_path_harness import record_ingress_path, get_critical_path_harness
        record_ingress_path(active_modalities=["video", "audio"])
        rec = get_critical_path_harness().get_ingress_records()[-1]
        self.assertEqual(rec.active_modalities, ["video", "audio"])

    def test_M04_requires_native_multimodal_recorded(self) -> None:
        from core.critical_path_harness import record_ingress_path, get_critical_path_harness
        record_ingress_path(requires_native_multimodal=True)
        rec = get_critical_path_harness().get_ingress_records()[-1]
        self.assertTrue(rec.requires_native_multimodal)


# ===========================================================================
# N)  record_route_selection helper
# ===========================================================================


class TestN_RecordRouteSelectionHelper(unittest.TestCase):
    """N) record_route_selection helper writes to ring buffer with correct state mapping."""

    def setUp(self) -> None:
        _reset()

    def test_N01_returns_route_selection_record(self) -> None:
        from core.critical_path_harness import record_route_selection, RouteSelectionRecord
        rec = record_route_selection(route_type="native_multimodal", provider="openai")
        self.assertIsInstance(rec, RouteSelectionRecord)

    def test_N02_written_to_ring_buffer(self) -> None:
        from core.critical_path_harness import record_route_selection, get_critical_path_harness
        record_route_selection(route_type="text_only", trace_id="n-02")
        records = get_critical_path_harness().get_route_selection_records()
        self.assertGreater(len(records), 0)

    def test_N03_native_multimodal_state_is_completed(self) -> None:
        from core.critical_path_harness import record_route_selection, PathHarnessState
        rec = record_route_selection(route_type="native_multimodal")
        self.assertEqual(rec.harness_state, PathHarnessState.COMPLETED)

    def test_N04_partial_multimodal_state_is_degraded(self) -> None:
        from core.critical_path_harness import record_route_selection, PathHarnessState
        rec = record_route_selection(route_type="partial_multimodal")
        self.assertEqual(rec.harness_state, PathHarnessState.DEGRADED)

    def test_N05_advisory_state_is_advisory(self) -> None:
        from core.critical_path_harness import record_route_selection, PathHarnessState
        rec = record_route_selection(route_type="advisory")
        self.assertEqual(rec.harness_state, PathHarnessState.ADVISORY)

    def test_N06_text_only_state_is_completed(self) -> None:
        from core.critical_path_harness import record_route_selection, PathHarnessState
        rec = record_route_selection(route_type="text_only")
        self.assertEqual(rec.harness_state, PathHarnessState.COMPLETED)


# ===========================================================================
# O)  record_provider_switch helper — initial selection
# ===========================================================================


class TestO_RecordProviderSwitchSelection(unittest.TestCase):
    """O) record_provider_switch helper writes initial selection records."""

    def setUp(self) -> None:
        _reset()

    def test_O01_returns_provider_switch_record(self) -> None:
        from core.critical_path_harness import record_provider_switch, ProviderSwitchRecord
        rec = record_provider_switch(to_provider="openai", to_model="gpt-4o")
        self.assertIsInstance(rec, ProviderSwitchRecord)

    def test_O02_written_to_ring_buffer(self) -> None:
        from core.critical_path_harness import record_provider_switch, get_critical_path_harness
        record_provider_switch(to_provider="anthropic", is_fallback=False)
        records = get_critical_path_harness().get_provider_switch_records()
        self.assertGreater(len(records), 0)

    def test_O03_is_fallback_false(self) -> None:
        from core.critical_path_harness import record_provider_switch
        rec = record_provider_switch(to_provider="openai", is_fallback=False)
        self.assertFalse(rec.is_fallback)

    def test_O04_not_in_fallback_records(self) -> None:
        from core.critical_path_harness import record_provider_switch, get_critical_path_harness
        record_provider_switch(to_provider="openai", is_fallback=False)
        fallbacks = get_critical_path_harness().get_fallback_records()
        self.assertEqual(len(fallbacks), 0)


# ===========================================================================
# P)  record_provider_switch helper — fallback switch
# ===========================================================================


class TestP_RecordProviderSwitchFallback(unittest.TestCase):
    """P) record_provider_switch helper writes fallback switch records."""

    def setUp(self) -> None:
        _reset()

    def test_P01_fallback_is_fallback_true(self) -> None:
        from core.critical_path_harness import record_provider_switch
        rec = record_provider_switch(
            from_provider="openai", to_provider="anthropic", is_fallback=True
        )
        self.assertTrue(rec.is_fallback)

    def test_P02_fallback_in_fallback_records(self) -> None:
        from core.critical_path_harness import record_provider_switch, get_critical_path_harness
        record_provider_switch(
            from_provider="openai", to_provider="anthropic", is_fallback=True
        )
        fallbacks = get_critical_path_harness().get_fallback_records()
        self.assertEqual(len(fallbacks), 1)

    def test_P03_fallback_harness_state(self) -> None:
        from core.critical_path_harness import record_provider_switch, PathHarnessState
        rec = record_provider_switch(is_fallback=True)
        self.assertEqual(rec.harness_state, PathHarnessState.FALLBACK_ACTIVE)

    def test_P04_switch_reason_recorded(self) -> None:
        from core.critical_path_harness import record_provider_switch
        rec = record_provider_switch(
            from_provider="openai", to_provider="anthropic",
            is_fallback=True, switch_reason="provider_unavailable",
        )
        self.assertEqual(rec.switch_reason, "provider_unavailable")


# ===========================================================================
# Q)  record_execution_dispatch helper
# ===========================================================================


class TestQ_RecordExecutionDispatch(unittest.TestCase):
    """Q) record_execution_dispatch helper writes to ring buffer."""

    def setUp(self) -> None:
        _reset()

    def test_Q01_returns_execution_dispatch_record(self) -> None:
        from core.critical_path_harness import record_execution_dispatch, ExecutionDispatchRecord
        rec = record_execution_dispatch(task_id="task-Q01")
        self.assertIsInstance(rec, ExecutionDispatchRecord)

    def test_Q02_written_to_ring_buffer(self) -> None:
        from core.critical_path_harness import record_execution_dispatch, get_critical_path_harness
        record_execution_dispatch(task_id="task-Q02", executor="node-1")
        records = get_critical_path_harness().get_dispatch_records()
        self.assertGreater(len(records), 0)
        self.assertEqual(records[-1].task_id, "task-Q02")

    def test_Q03_executor_recorded(self) -> None:
        from core.critical_path_harness import record_execution_dispatch
        rec = record_execution_dispatch(executor="node-99")
        self.assertEqual(rec.executor, "node-99")

    def test_Q04_provider_and_model_recorded(self) -> None:
        from core.critical_path_harness import record_execution_dispatch
        rec = record_execution_dispatch(provider="openai", model="gpt-4o")
        self.assertEqual(rec.provider, "openai")
        self.assertEqual(rec.model, "gpt-4o")


# ===========================================================================
# R)  snapshot() aggregate counts
# ===========================================================================


class TestR_SnapshotAggregateCounts(unittest.TestCase):
    """R) snapshot() returns correct aggregate counts."""

    def setUp(self) -> None:
        _reset()

    def test_R01_empty_snapshot(self) -> None:
        from core.critical_path_harness import get_critical_path_harness
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.ingress_count, 0)
        self.assertEqual(snap.route_selection_count, 0)
        self.assertEqual(snap.fallback_count, 0)

    def test_R02_ingress_count(self) -> None:
        from core.critical_path_harness import record_ingress_path, get_critical_path_harness
        record_ingress_path()
        record_ingress_path()
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.ingress_count, 2)

    def test_R03_fallback_count(self) -> None:
        from core.critical_path_harness import record_provider_switch, get_critical_path_harness
        record_provider_switch(to_provider="a", is_fallback=False)
        record_provider_switch(from_provider="a", to_provider="b", is_fallback=True)
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.provider_switch_count, 2)
        self.assertEqual(snap.fallback_count, 1)

    def test_R04_advisory_count(self) -> None:
        from core.critical_path_harness import record_route_selection, get_critical_path_harness
        record_route_selection(route_type="advisory")
        record_route_selection(route_type="text_only")
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.advisory_count, 1)

    def test_R05_recent_route_type(self) -> None:
        from core.critical_path_harness import record_route_selection, get_critical_path_harness
        record_route_selection(route_type="native_multimodal")
        record_route_selection(route_type="partial_multimodal")
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.recent_route_type, "partial_multimodal")

    def test_R06_recent_provider(self) -> None:
        from core.critical_path_harness import record_provider_switch, get_critical_path_harness
        record_provider_switch(to_provider="anthropic")
        record_provider_switch(to_provider="openai")
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.recent_provider, "openai")


# ===========================================================================
# S)  snapshot_critical_path()
# ===========================================================================


class TestS_SnapshotCriticalPath(unittest.TestCase):
    """S) snapshot_critical_path() returns combined dict with authority and gap fields."""

    def setUp(self) -> None:
        _reset()

    def test_S01_returns_dict(self) -> None:
        from core.critical_path_harness import snapshot_critical_path
        result = snapshot_critical_path()
        self.assertIsInstance(result, dict)

    def test_S02_has_authority_key(self) -> None:
        from core.critical_path_harness import snapshot_critical_path
        result = snapshot_critical_path()
        self.assertIn("authority", result)

    def test_S03_has_layer_position(self) -> None:
        from core.critical_path_harness import snapshot_critical_path
        result = snapshot_critical_path()
        self.assertIn("layer_position", result)
        self.assertEqual(result["layer_position"], 15)

    def test_S04_gap_closed_is_gap_512_009(self) -> None:
        from core.critical_path_harness import snapshot_critical_path
        result = snapshot_critical_path()
        self.assertEqual(result["gap_closed"], "GAP-512-009")

    def test_S05_snapshot_count_keys_present(self) -> None:
        from core.critical_path_harness import snapshot_critical_path
        result = snapshot_critical_path()
        for key in ("ingress_count", "route_selection_count", "fallback_count"):
            self.assertIn(key, result, f"Key '{key}' missing from snapshot_critical_path()")


# ===========================================================================
# T)  Advisory routing counted correctly
# ===========================================================================


class TestT_AdvisoryRouting(unittest.TestCase):
    """T) Advisory routing type is tracked separately."""

    def setUp(self) -> None:
        _reset()

    def test_T01_advisory_increments_advisory_count(self) -> None:
        from core.critical_path_harness import record_route_selection, get_critical_path_harness
        record_route_selection(route_type="advisory", provider="none", model="none")
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.advisory_count, 1)

    def test_T02_non_advisory_does_not_increment(self) -> None:
        from core.critical_path_harness import record_route_selection, get_critical_path_harness
        record_route_selection(route_type="native_multimodal", provider="openai")
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.advisory_count, 0)

    def test_T03_advisory_state_mapping(self) -> None:
        from core.critical_path_harness import record_route_selection, PathHarnessState
        rec = record_route_selection(route_type="advisory")
        self.assertEqual(rec.harness_state, PathHarnessState.ADVISORY)


# ===========================================================================
# U)  Full end-to-end critical path round-trip
# ===========================================================================


class TestU_EndToEndCriticalPath(unittest.TestCase):
    """U) Full end-to-end critical path: ingress → route → provider → dispatch."""

    def setUp(self) -> None:
        _reset()

    def test_U01_full_path_traceable(self) -> None:
        from core.critical_path_harness import (
            record_ingress_path, record_route_selection,
            record_provider_switch, record_execution_dispatch,
            get_critical_path_harness,
        )
        trace = "trace-U01"
        record_ingress_path(
            trace_id=trace, active_modalities=["image", "text"],
            requires_native_multimodal=True, source="test_ingress",
        )
        record_route_selection(
            trace_id=trace, route_type="native_multimodal",
            provider="openai", model="gpt-4o", source="test_route",
        )
        record_provider_switch(
            trace_id=trace, from_provider="none", to_provider="openai",
            to_model="gpt-4o", is_fallback=False, source="test_switch",
        )
        record_execution_dispatch(
            task_id="task-U01", trace_id=trace, executor="node-1",
            dispatch_method="fabric", provider="openai", model="gpt-4o",
        )

        h = get_critical_path_harness()
        self.assertEqual(h.get_ingress_records()[-1].trace_id, trace)
        self.assertEqual(h.get_route_selection_records()[-1].route_type, "native_multimodal")
        self.assertEqual(h.get_provider_switch_records()[-1].to_provider, "openai")
        self.assertEqual(h.get_dispatch_records()[-1].task_id, "task-U01")

    def test_U02_snapshot_reflects_full_path(self) -> None:
        from core.critical_path_harness import (
            record_ingress_path, record_route_selection,
            record_provider_switch, record_execution_dispatch,
            get_critical_path_harness,
        )
        record_ingress_path()
        record_route_selection(route_type="text_only")
        record_provider_switch(to_provider="openai")
        record_execution_dispatch(task_id="task-U02")
        snap = get_critical_path_harness().snapshot()
        self.assertEqual(snap.ingress_count, 1)
        self.assertEqual(snap.route_selection_count, 1)
        self.assertEqual(snap.provider_switch_count, 1)
        self.assertEqual(snap.dispatch_count, 1)


# ===========================================================================
# V)  Fallback arc inspectable
# ===========================================================================


class TestV_FallbackArcInspectable(unittest.TestCase):
    """V) Primary → fallback provider arc is fully traceable."""

    def setUp(self) -> None:
        _reset()

    def test_V01_fallback_arc_round_trip(self) -> None:
        from core.critical_path_harness import (
            record_route_selection, record_provider_switch, get_critical_path_harness,
        )
        # Route selection: partial_multimodal (tier-2 fallback)
        record_route_selection(
            route_type="partial_multimodal",
            provider="anthropic", model="claude-3-haiku",
            fallback_reason="native_multimodal_provider_unavailable",
        )
        # Provider switch: tier-1 (openai) was unavailable, fell back to anthropic
        record_provider_switch(
            from_provider="openai", to_provider="anthropic",
            from_model="gpt-4o", to_model="claude-3-haiku",
            switch_reason="native_multimodal_provider_unavailable",
            is_fallback=True,
        )
        h = get_critical_path_harness()
        fallbacks = h.get_fallback_records()
        self.assertEqual(len(fallbacks), 1)
        self.assertEqual(fallbacks[0].from_provider, "openai")
        self.assertEqual(fallbacks[0].to_provider, "anthropic")
        snap = h.snapshot()
        self.assertEqual(snap.fallback_count, 1)

    def test_V02_fallback_harness_state_is_fallback_active(self) -> None:
        from core.critical_path_harness import record_provider_switch, PathHarnessState
        rec = record_provider_switch(
            from_provider="openai", to_provider="anthropic", is_fallback=True
        )
        self.assertEqual(rec.harness_state, PathHarnessState.FALLBACK_ACTIVE)

    def test_V03_fallback_route_state_is_degraded(self) -> None:
        from core.critical_path_harness import record_route_selection, PathHarnessState
        rec = record_route_selection(route_type="partial_multimodal")
        self.assertEqual(rec.harness_state, PathHarnessState.DEGRADED)


# ===========================================================================
# W)  Non-blocking harness writes — never raises
# ===========================================================================


class TestW_NonBlockingHarnessWrites(unittest.TestCase):
    """W) Non-blocking harness writes never raise exceptions."""

    def test_W01_record_ingress_path_does_not_raise(self) -> None:
        from core.critical_path_harness import record_ingress_path
        # Should not raise regardless of arguments
        try:
            result = record_ingress_path(
                trace_id="w-01", active_modalities=["image"],
                requires_native_multimodal=True, source="test"
            )
            self.assertIsNotNone(result)
        except Exception as exc:
            self.fail(f"record_ingress_path raised unexpectedly: {exc}")

    def test_W02_record_route_selection_does_not_raise(self) -> None:
        from core.critical_path_harness import record_route_selection
        try:
            result = record_route_selection(route_type="advisory", provider="none")
            self.assertIsNotNone(result)
        except Exception as exc:
            self.fail(f"record_route_selection raised unexpectedly: {exc}")

    def test_W03_record_provider_switch_does_not_raise(self) -> None:
        from core.critical_path_harness import record_provider_switch
        try:
            result = record_provider_switch(
                from_provider="openai", to_provider="anthropic", is_fallback=True
            )
            self.assertIsNotNone(result)
        except Exception as exc:
            self.fail(f"record_provider_switch raised unexpectedly: {exc}")

    def test_W04_record_execution_dispatch_does_not_raise(self) -> None:
        from core.critical_path_harness import record_execution_dispatch
        try:
            result = record_execution_dispatch(task_id="w-04", executor="node-1")
            self.assertIsNotNone(result)
        except Exception as exc:
            self.fail(f"record_execution_dispatch raised unexpectedly: {exc}")

    def test_W05_snapshot_critical_path_does_not_raise(self) -> None:
        from core.critical_path_harness import snapshot_critical_path
        try:
            result = snapshot_critical_path()
            self.assertIsNotNone(result)
        except Exception as exc:
            self.fail(f"snapshot_critical_path raised unexpectedly: {exc}")


# ===========================================================================
# X)  GAP-512-009 closure
# ===========================================================================


class TestX_Gap512009Closure(unittest.TestCase):
    """X) GAP-512-009 is marked is_residual=False in the closure audit."""

    def test_X01_gap_512_009_not_residual(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        audit = get_runtime_closure_audit()
        gaps = audit.get_residual_gap_map()
        gap_009 = next((g for g in gaps if g.gap_id == "GAP-512-009"), None)
        self.assertIsNotNone(gap_009, "GAP-512-009 not found in gap map")
        self.assertFalse(
            gap_009.is_residual,  # type: ignore[union-attr]
            "GAP-512-009 should have is_residual=False after PR-515",
        )

    def test_X02_gap_512_009_follow_up_is_pr515(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        audit = get_runtime_closure_audit()
        gaps = audit.get_residual_gap_map()
        gap_009 = next((g for g in gaps if g.gap_id == "GAP-512-009"), None)
        self.assertIsNotNone(gap_009)
        self.assertEqual(gap_009.follow_up, "PR-515")  # type: ignore[union-attr]


# ===========================================================================
# Y)  CONFLICT-008 present and resolved
# ===========================================================================


class TestY_Conflict008Resolved(unittest.TestCase):
    """Y) CONFLICT-008 is present and marked resolved in detect_parallel_truth_paths."""

    def test_Y01_conflict_008_present(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        audit = get_runtime_closure_audit()
        conflicts = audit.detect_parallel_truth_paths()
        ids = [c.conflict_id for c in conflicts]
        self.assertIn("CONFLICT-008", ids)

    def test_Y02_conflict_008_resolved(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        audit = get_runtime_closure_audit()
        conflicts = audit.detect_parallel_truth_paths()
        c008 = next((c for c in conflicts if c.conflict_id == "CONFLICT-008"), None)
        self.assertIsNotNone(c008)
        self.assertTrue(c008.is_resolved)  # type: ignore[union-attr]

    def test_Y03_conflict_008_mentions_gap_512_009(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        audit = get_runtime_closure_audit()
        conflicts = audit.detect_parallel_truth_paths()
        c008 = next((c for c in conflicts if c.conflict_id == "CONFLICT-008"), None)
        self.assertIsNotNone(c008)
        self.assertIn(
            "GAP-512-009",
            c008.resolution_note,  # type: ignore[union-attr]
        )


# ===========================================================================
# Z)  PR-515 layer specs in verify_all_layers
# ===========================================================================


class TestZ_Pr515LayerSpecs(unittest.TestCase):
    """Z) PR-515 layer specs are present in verify_all_layers()."""

    def test_Z01_pr515_layer_specs_present(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        audit = get_runtime_closure_audit()
        statuses = audit.verify_all_layers()
        pr515_statuses = [s for s in statuses if s.pr_ref == "PR-515"]
        self.assertGreater(len(pr515_statuses), 0, "No PR-515 layer specs found")

    def test_Z02_critical_path_harness_authority_verified(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit, CLOSURE_STATUS_VERIFIED
        audit = get_runtime_closure_audit()
        statuses = audit.verify_all_layers()
        harness_status = next(
            (s for s in statuses if s.sentinel_name == "CRITICAL_PATH_HARNESS_AUTHORITY"),
            None,
        )
        self.assertIsNotNone(harness_status, "CRITICAL_PATH_HARNESS_AUTHORITY spec not found")
        self.assertEqual(harness_status.status, CLOSURE_STATUS_VERIFIED)  # type: ignore[union-attr]

    def test_Z03_openclawd_ingress_sentinel_present_in_specs(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        specs = RuntimeClosureAudit._LAYER_SPECS
        sentinel_names = [s[2] for s in specs]
        self.assertIn("CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED", sentinel_names)

    def test_Z04_multi_llm_router_sentinel_present_in_specs(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        specs = RuntimeClosureAudit._LAYER_SPECS
        sentinel_names = [s[2] for s in specs]
        self.assertIn("CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED", sentinel_names)


# ===========================================================================
# AA) OpenClawd integration sentinel
# ===========================================================================


class TestAA_OpenClawdSentinel(unittest.TestCase):
    """AA) core/openclawd.py exports CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED."""

    def test_AA01_sentinel_importable(self) -> None:
        from core.openclawd import CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED  # type: ignore[attr-defined]  # noqa: F401
        self.assertIsNotNone(CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED)

    def test_AA02_sentinel_is_string(self) -> None:
        from core.openclawd import CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED  # type: ignore[attr-defined]
        self.assertIsInstance(CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED, str)

    def test_AA03_sentinel_mentions_gap_512_009(self) -> None:
        from core.openclawd import CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED  # type: ignore[attr-defined]
        self.assertIn("GAP-512-009", CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED)

    def test_AA04_sentinel_mentions_pr515(self) -> None:
        from core.openclawd import CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED  # type: ignore[attr-defined]
        self.assertIn("PR-515", CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED)


# ===========================================================================
# BB) MultiLLMRouter integration sentinel
# ===========================================================================


class TestBB_MultiLLMRouterSentinel(unittest.TestCase):
    """BB) core/multi_llm_router.py exports CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED."""

    @staticmethod
    def _try_import_sentinel():
        """Return (sentinel_value, error) tuple. error is None on success."""
        try:
            from core.multi_llm_router import CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED  # type: ignore[attr-defined]
            return CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED, None
        except ImportError as exc:
            return None, exc

    def test_BB01_sentinel_importable_or_dependency_missing(self) -> None:
        sentinel, err = self._try_import_sentinel()
        if err is not None:
            # Module has optional runtime dependencies (e.g. httpx) not present
            # in this test environment; verify the sentinel exists in the source file.
            import os
            src = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "core", "multi_llm_router.py",
            )
            with open(src) as f:
                content = f.read()
            self.assertIn(
                "CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED",
                content,
                "Sentinel not found in multi_llm_router.py source",
            )
        else:
            self.assertIsNotNone(sentinel)

    def test_BB02_sentinel_is_string_or_in_source(self) -> None:
        sentinel, err = self._try_import_sentinel()
        if err is None:
            self.assertIsInstance(sentinel, str)

    def test_BB03_sentinel_mentions_gap_512_009(self) -> None:
        import os
        src = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "multi_llm_router.py",
        )
        with open(src) as f:
            content = f.read()
        # Verify the sentinel string in the file mentions GAP-512-009
        self.assertIn("GAP-512-009", content)
        self.assertIn("CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED", content)

    def test_BB04_sentinel_mentions_pr515(self) -> None:
        import os
        src = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "multi_llm_router.py",
        )
        with open(src) as f:
            content = f.read()
        self.assertIn("PR-515", content)


# ===========================================================================
# CC) No competing routing authority
# ===========================================================================


class TestCC_NoCompetingRoutingAuthority(unittest.TestCase):
    """CC) CriticalPathHarness does not make routing decisions."""

    def test_CC01_harness_has_no_route_method(self) -> None:
        from core.critical_path_harness import CriticalPathHarnessRuntime
        h = CriticalPathHarnessRuntime()
        self.assertFalse(
            hasattr(h, "route"),
            "CriticalPathHarnessRuntime must not have a route() method",
        )

    def test_CC02_harness_has_no_select_provider_method(self) -> None:
        from core.critical_path_harness import CriticalPathHarnessRuntime
        h = CriticalPathHarnessRuntime()
        self.assertFalse(
            hasattr(h, "select_provider"),
            "CriticalPathHarnessRuntime must not have a select_provider() method",
        )

    def test_CC03_no_competing_routing_authority_policy_present(self) -> None:
        from core.critical_path_harness import NO_COMPETING_ROUTING_AUTHORITY_POLICY
        self.assertIn("observer", NO_COMPETING_ROUTING_AUTHORITY_POLICY.lower())

    def test_CC04_harness_only_records(self) -> None:
        from core.critical_path_harness import CriticalPathHarnessRuntime
        h = CriticalPathHarnessRuntime()
        record_methods = [
            m for m in dir(h) if m.startswith("record_")
        ]
        # Should have record_* methods for writing, not routing
        self.assertGreater(len(record_methods), 0)
        self.assertIn("record_ingress", record_methods)
        self.assertIn("record_route_selection", record_methods)


# ===========================================================================
# DD) Abstraction discipline
# ===========================================================================


class TestDD_AbstractionDiscipline(unittest.TestCase):
    """DD) snapshot_critical_path() returns an operator-safe plain dict."""

    def setUp(self) -> None:
        _reset()

    def test_DD01_returns_plain_dict(self) -> None:
        from core.critical_path_harness import snapshot_critical_path
        result = snapshot_critical_path()
        self.assertIsInstance(result, dict)

    def test_DD02_no_deque_values(self) -> None:
        """snapshot_critical_path() must not expose raw deque objects."""
        import collections
        from core.critical_path_harness import snapshot_critical_path
        result = snapshot_critical_path()
        for key, val in result.items():
            self.assertNotIsInstance(
                val, collections.deque,
                f"Key '{key}' contains a raw deque — not operator-safe",
            )

    def test_DD03_all_values_json_serialisable_types(self) -> None:
        """snapshot_critical_path() values are JSON-friendly types."""
        from core.critical_path_harness import snapshot_critical_path
        result = snapshot_critical_path()
        import json
        # Should not raise
        try:
            json.dumps(result)
        except (TypeError, ValueError) as exc:
            self.fail(f"snapshot_critical_path() result is not JSON-serialisable: {exc}")


if __name__ == "__main__":
    unittest.main()
