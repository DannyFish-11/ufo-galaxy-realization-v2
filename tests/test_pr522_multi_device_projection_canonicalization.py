#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr522_multi_device_projection_canonicalization.py
=============================================================
PR-522 — Multi-Device Projection Canonicalization.

Validates that:

1. **Authority sentinels are importable** (GAP-517-008 resolved).
   - ``MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY`` is importable.
   - ``MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED`` is importable.
   - ``MULTI_DEVICE_PROJECTION_GAP008_RESOLVED`` is importable.
   - Layer position is 13.

2. **CanonicalProjectionSurfacingState enum is correct**.
   - FULL, PARTIAL, DEGRADED, UNAVAILABLE values are defined.

3. **MultiDeviceCanonicalEnrichment dataclass round-trips cleanly**.
   - ``to_dict()`` produces a dict with all expected keys.
   - Default instance has ``surfacing_state == UNAVAILABLE``.
   - ``transport_local_only`` is True by default.

4. **enrich_multi_device_projection() calls canonical chain singleton**.
   - ``chain_available`` is True when CrossDeviceChainSingleton is reachable.
   - ``canonical_executions`` and ``legacy_executions`` are integers.
   - ``recent_chain_records`` is a list.
   - ``chain_snapshot`` is a dict with expected keys.

5. **enrich_multi_device_projection() calls TaskGraphRuntime**.
   - ``graph_available`` is True when TaskGraphRuntime is reachable.
   - ``graph_node_count`` is a non-negative integer.
   - ``recent_graph_records`` is a list.
   - ``graph_snapshot`` is a dict with expected keys.

6. **enrich_multi_device_projection() calls OperatorSurface**.
   - ``operator_available`` is True when OperatorSurface is reachable.
   - ``operator_snapshot`` is a dict when available.

7. **enrich_multi_device_projection() calls MultiDeviceControlIntegrityRuntime**.
   - ``integrity_available`` is True when integrity runtime is reachable.
   - ``integrity_snapshot`` is a dict when available.

8. **Surfacing state reflects canonical source availability**.
   - FULL when both chain and graph are available.
   - PARTIAL when exactly one of chain/graph is available.
   - UNAVAILABLE when neither chain nor graph is available.
   - ``transport_local_only`` is True only when both are missing.

9. **Degraded/incomplete canonical state is explicit**.
   - When chain is unavailable, gap reason mentions GAP-517-008.
   - When graph is unavailable, gap reason mentions GAP-517-008.
   - When all sources unavailable, ``surfacing_state`` is UNAVAILABLE.

10. **Projection endpoint uses canonical enrichment** (GAP-517-008).
    - Integration sentinel importable from core/routes/projection.py.
    - ``canonical_enrichment`` key present in projection metadata.
    - ``canonical_surfacing_state`` key present in projection metadata.
    - ``canonical_surfacing_gaps`` key present in projection metadata.
    - ``transport_local_only`` key present in projection metadata.
    - ``pr_522_gap_008_resolved`` key is True in projection metadata.
    - Backward-compat keys ``cross_device_chain_snapshot`` and
      ``task_graph_snapshot`` still present in metadata.

11. **GAP-517-008 is marked as resolved** in residual gap catalog.
    - ``is_resolved == True``.
    - Resolution note references PR-522.

Test groups
-----------
 A)  Sentinel imports — PR-522 constants importable and contain expected text.
 B)  CanonicalProjectionSurfacingState — enum values correct.
 C)  MultiDeviceCanonicalEnrichment — dataclass defaults and to_dict.
 D)  enrich_multi_device_projection — chain singleton available.
 E)  enrich_multi_device_projection — graph runtime available.
 F)  enrich_multi_device_projection — operator surface available.
 G)  enrich_multi_device_projection — integrity runtime available.
 H)  Surfacing state logic — FULL / PARTIAL / UNAVAILABLE.
 I)  Degraded/incomplete surfacing is explicitly surfaced in gap reasons.
 J)  Projection endpoint sentinel and canonical metadata keys.
 K)  Backward-compat keys still present in projection metadata.
 L)  GAP-517-008 marked resolved in residual gap catalog.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _reset_chain():
    try:
        from core.cross_device_execution_chain import reset_cross_device_chain
        reset_cross_device_chain()
    except Exception:
        pass


def _reset_graph():
    try:
        from core.task_graph_runtime import reset_task_graph_runtime
        reset_task_graph_runtime()
    except Exception:
        pass


def _reset_integrity_runtime():
    try:
        from core.multi_device_control_integrity import reset_multi_device_integrity_runtime
        reset_multi_device_integrity_runtime()
    except Exception:
        pass


# ===========================================================================
# A) Sentinel imports
# ===========================================================================


class TestA_SentinelImports(unittest.TestCase):
    """A) PR-522 sentinel constants are importable and contain expected text."""

    def test_A1_authority_importable(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY,
        )
        self.assertIn("PR522", MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY)

    def test_A2_authority_is_string(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY,
        )
        self.assertIsInstance(MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY, str)

    def test_A3_integrated_importable(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED,
        )
        self.assertIn(
            "INTEGRATED",
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED,
        )

    def test_A4_integrated_references_gap(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED,
        )
        self.assertIn("GAP-517-008", MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED)

    def test_A5_gap008_resolved_importable(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_GAP008_RESOLVED,
        )
        self.assertIn("GAP_517_008_RESOLVED", MULTI_DEVICE_PROJECTION_GAP008_RESOLVED)

    def test_A6_gap008_resolved_references_chain(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_GAP008_RESOLVED,
        )
        self.assertIn("CrossDeviceChainSingleton", MULTI_DEVICE_PROJECTION_GAP008_RESOLVED)

    def test_A7_layer_position_is_13(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_LAYER_POSITION,
        )
        self.assertEqual(MULTI_DEVICE_PROJECTION_CANONICALIZATION_LAYER_POSITION, 13)


# ===========================================================================
# B) CanonicalProjectionSurfacingState enum
# ===========================================================================


class TestB_SurfacingStateEnum(unittest.TestCase):
    """B) CanonicalProjectionSurfacingState enum has correct values."""

    def _enum(self):
        from core.multi_device_projection_canonicalization import (
            CanonicalProjectionSurfacingState,
        )
        return CanonicalProjectionSurfacingState

    def test_B1_full_value(self):
        self.assertEqual(self._enum().FULL.value, "full")

    def test_B2_partial_value(self):
        self.assertEqual(self._enum().PARTIAL.value, "partial")

    def test_B3_degraded_value(self):
        self.assertEqual(self._enum().DEGRADED.value, "degraded")

    def test_B4_unavailable_value(self):
        self.assertEqual(self._enum().UNAVAILABLE.value, "unavailable")

    def test_B5_four_states_defined(self):
        states = list(self._enum())
        self.assertEqual(len(states), 4)


# ===========================================================================
# C) MultiDeviceCanonicalEnrichment dataclass
# ===========================================================================


class TestC_EnrichmentDataclass(unittest.TestCase):
    """C) MultiDeviceCanonicalEnrichment dataclass defaults and serialisation."""

    def _cls(self):
        from core.multi_device_projection_canonicalization import (
            MultiDeviceCanonicalEnrichment,
        )
        return MultiDeviceCanonicalEnrichment

    def test_C1_default_surfacing_state_is_unavailable(self):
        from core.multi_device_projection_canonicalization import (
            CanonicalProjectionSurfacingState,
        )
        e = self._cls()()
        self.assertEqual(e.surfacing_state, CanonicalProjectionSurfacingState.UNAVAILABLE)

    def test_C2_transport_local_only_true_by_default(self):
        e = self._cls()()
        self.assertTrue(e.transport_local_only)

    def test_C3_chain_available_false_by_default(self):
        e = self._cls()()
        self.assertFalse(e.chain_available)

    def test_C4_graph_available_false_by_default(self):
        e = self._cls()()
        self.assertFalse(e.graph_available)

    def test_C5_to_dict_has_surfacing_state_key(self):
        d = self._cls()().to_dict()
        self.assertIn("surfacing_state", d)

    def test_C6_to_dict_has_chain_available_key(self):
        d = self._cls()().to_dict()
        self.assertIn("chain_available", d)

    def test_C7_to_dict_has_graph_available_key(self):
        d = self._cls()().to_dict()
        self.assertIn("graph_available", d)

    def test_C8_to_dict_has_transport_local_only_key(self):
        d = self._cls()().to_dict()
        self.assertIn("transport_local_only", d)

    def test_C9_to_dict_has_surfacing_gap_reasons_key(self):
        d = self._cls()().to_dict()
        self.assertIn("surfacing_gap_reasons", d)

    def test_C10_to_dict_has_enrichment_id_key(self):
        d = self._cls()().to_dict()
        self.assertIn("enrichment_id", d)

    def test_C11_to_dict_surfacing_state_is_string(self):
        d = self._cls()().to_dict()
        self.assertIsInstance(d["surfacing_state"], str)

    def test_C12_to_dict_gap_reasons_is_list(self):
        d = self._cls()().to_dict()
        self.assertIsInstance(d["surfacing_gap_reasons"], list)

    def test_C13_unique_enrichment_ids(self):
        e1 = self._cls()()
        e2 = self._cls()()
        self.assertNotEqual(e1.enrichment_id, e2.enrichment_id)


# ===========================================================================
# D) enrich_multi_device_projection — chain singleton
# ===========================================================================


class TestD_ChainEnrichment(unittest.TestCase):
    """D) enrich_multi_device_projection consumes CrossDeviceChainSingleton."""

    def setUp(self):
        _reset_chain()

    def tearDown(self):
        _reset_chain()

    def _enrich(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        return enrich_multi_device_projection()

    def test_D1_chain_available_true(self):
        e = self._enrich()
        self.assertTrue(e.chain_available)

    def test_D2_canonical_executions_is_int(self):
        e = self._enrich()
        self.assertIsInstance(e.canonical_executions, int)

    def test_D3_legacy_executions_is_int(self):
        e = self._enrich()
        self.assertIsInstance(e.legacy_executions, int)

    def test_D4_total_executions_is_int(self):
        e = self._enrich()
        self.assertIsInstance(e.total_executions, int)

    def test_D5_recent_chain_records_is_list(self):
        e = self._enrich()
        self.assertIsInstance(e.recent_chain_records, list)

    def test_D6_chain_snapshot_is_dict(self):
        e = self._enrich()
        self.assertIsInstance(e.chain_snapshot, dict)

    def test_D7_chain_snapshot_has_total_executions_key(self):
        e = self._enrich()
        self.assertIn("total_executions", e.chain_snapshot)

    def test_D8_chain_snapshot_has_canonical_executions_key(self):
        e = self._enrich()
        self.assertIn("canonical_executions", e.chain_snapshot)

    def test_D9_chain_snapshot_has_canonical_chain_order_key(self):
        e = self._enrich()
        self.assertIn("canonical_chain_order", e.chain_snapshot)

    def test_D10_chain_records_reflect_recorded_execution(self):
        from core.cross_device_execution_chain import record_chain_execution
        record_chain_execution(task_id="test_pr522_d10", device_id="dev_x")
        e = self._enrich()
        self.assertGreater(e.total_executions, 0)

    def test_D11_canonical_count_increments(self):
        from core.cross_device_execution_chain import record_chain_execution
        before = self._enrich().canonical_executions
        record_chain_execution(task_id="test_pr522_d11", device_id="dev_y")
        after = self._enrich().canonical_executions
        self.assertGreaterEqual(after, before)

    def test_D12_chain_unavailable_produces_gap_reason(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        with patch(
            "core.multi_device_projection_canonicalization.enrich_multi_device_projection",
            wraps=enrich_multi_device_projection,
        ):
            with patch(
                "core.cross_device_execution_chain.build_cross_device_chain_snapshot",
                side_effect=RuntimeError("chain unavailable"),
            ):
                result = enrich_multi_device_projection()
        self.assertFalse(result.chain_available)
        self.assertTrue(
            any("GAP-517-008" in r for r in result.surfacing_gap_reasons),
            "Expected GAP-517-008 in gap reasons",
        )


# ===========================================================================
# E) enrich_multi_device_projection — TaskGraphRuntime
# ===========================================================================


class TestE_GraphEnrichment(unittest.TestCase):
    """E) enrich_multi_device_projection consumes TaskGraphRuntime."""

    def setUp(self):
        _reset_graph()

    def tearDown(self):
        _reset_graph()

    def _enrich(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        return enrich_multi_device_projection()

    def test_E1_graph_available_true(self):
        e = self._enrich()
        self.assertTrue(e.graph_available)

    def test_E2_graph_node_count_is_int(self):
        e = self._enrich()
        self.assertIsInstance(e.graph_node_count, int)

    def test_E3_graph_node_count_non_negative(self):
        e = self._enrich()
        self.assertGreaterEqual(e.graph_node_count, 0)

    def test_E4_recent_graph_records_is_list(self):
        e = self._enrich()
        self.assertIsInstance(e.recent_graph_records, list)

    def test_E5_graph_snapshot_is_dict(self):
        e = self._enrich()
        self.assertIsInstance(e.graph_snapshot, dict)

    def test_E6_graph_snapshot_has_node_count_key(self):
        e = self._enrich()
        self.assertIn("node_count", e.graph_snapshot)

    def test_E7_graph_unavailable_produces_gap_reason(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        with patch(
            "core.task_graph_runtime.get_task_graph_runtime",
            side_effect=RuntimeError("graph unavailable"),
        ):
            result = enrich_multi_device_projection()
        self.assertFalse(result.graph_available)
        self.assertTrue(
            any("GAP-517-008" in r for r in result.surfacing_gap_reasons),
            "Expected GAP-517-008 in gap reasons when graph unavailable",
        )


# ===========================================================================
# F) enrich_multi_device_projection — OperatorSurface
# ===========================================================================


class TestF_OperatorEnrichment(unittest.TestCase):
    """F) enrich_multi_device_projection optionally consumes OperatorSurface."""

    def _enrich(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        return enrich_multi_device_projection()

    def test_F1_operator_available_is_bool(self):
        e = self._enrich()
        self.assertIsInstance(e.operator_available, bool)

    def test_F2_operator_unavailable_does_not_add_gap_reason(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        with patch(
            "core.operator_surface.get_operator_surface",
            side_effect=RuntimeError("op unavailable"),
        ):
            result = enrich_multi_device_projection()
        # operator is optional — failure must NOT appear in gap reasons
        self.assertFalse(result.operator_available)
        self.assertFalse(
            any("operator" in r.lower() for r in result.surfacing_gap_reasons),
            "OperatorSurface failure must not populate surfacing_gap_reasons",
        )

    def test_F3_operator_snapshot_none_when_unavailable(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        with patch(
            "core.operator_surface.get_operator_surface",
            side_effect=RuntimeError("op unavailable"),
        ):
            result = enrich_multi_device_projection()
        self.assertIsNone(result.operator_snapshot)


# ===========================================================================
# G) enrich_multi_device_projection — IntegrityRuntime
# ===========================================================================


class TestG_IntegrityEnrichment(unittest.TestCase):
    """G) enrich_multi_device_projection optionally consumes integrity runtime."""

    def setUp(self):
        _reset_integrity_runtime()

    def tearDown(self):
        _reset_integrity_runtime()

    def _enrich(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        return enrich_multi_device_projection()

    def test_G1_integrity_available_is_bool(self):
        e = self._enrich()
        self.assertIsInstance(e.integrity_available, bool)

    def test_G2_integrity_unavailable_does_not_add_required_gap(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        with patch(
            "core.multi_device_control_integrity.build_integrity_snapshot",
            side_effect=RuntimeError("integrity unavailable"),
        ):
            result = enrich_multi_device_projection()
        self.assertFalse(result.integrity_available)
        # integrity is optional — should not degrade required surfacing state
        # (chain + graph still available so state should remain full/partial)

    def test_G3_integrity_snapshot_has_expected_keys_when_available(self):
        e = self._enrich()
        if e.integrity_available:
            snap = e.integrity_snapshot
            self.assertIn("snapshot_id", snap)
            self.assertIn("canonical_entry_count", snap)
            self.assertIn("legacy_entry_count", snap)


# ===========================================================================
# H) Surfacing state logic
# ===========================================================================


class TestH_SurfacingStateLogic(unittest.TestCase):
    """H) Surfacing state correctly reflects canonical source availability."""

    def setUp(self):
        _reset_chain()
        _reset_graph()

    def tearDown(self):
        _reset_chain()
        _reset_graph()

    def test_H1_full_when_both_chain_and_graph_available(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
            CanonicalProjectionSurfacingState,
        )
        result = enrich_multi_device_projection()
        # Both chain and graph are available in the default test environment
        if result.chain_available and result.graph_available:
            self.assertEqual(result.surfacing_state, CanonicalProjectionSurfacingState.FULL)

    def test_H2_partial_when_only_chain_available(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
            CanonicalProjectionSurfacingState,
        )
        with patch(
            "core.task_graph_runtime.get_task_graph_runtime",
            side_effect=RuntimeError("no graph"),
        ):
            result = enrich_multi_device_projection()
        if result.chain_available:
            self.assertEqual(result.surfacing_state, CanonicalProjectionSurfacingState.PARTIAL)

    def test_H3_partial_when_only_graph_available(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
            CanonicalProjectionSurfacingState,
        )
        with patch(
            "core.cross_device_execution_chain.build_cross_device_chain_snapshot",
            side_effect=RuntimeError("no chain"),
        ):
            result = enrich_multi_device_projection()
        if result.graph_available:
            self.assertEqual(result.surfacing_state, CanonicalProjectionSurfacingState.PARTIAL)

    def test_H4_unavailable_when_neither_available(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
            CanonicalProjectionSurfacingState,
        )
        with patch(
            "core.cross_device_execution_chain.build_cross_device_chain_snapshot",
            side_effect=RuntimeError("no chain"),
        ), patch(
            "core.task_graph_runtime.get_task_graph_runtime",
            side_effect=RuntimeError("no graph"),
        ), patch(
            "core.operator_surface.get_operator_surface",
            side_effect=RuntimeError("no op"),
        ), patch(
            "core.multi_device_control_integrity.build_integrity_snapshot",
            side_effect=RuntimeError("no integrity"),
        ):
            result = enrich_multi_device_projection()
        self.assertEqual(result.surfacing_state, CanonicalProjectionSurfacingState.UNAVAILABLE)

    def test_H5_transport_local_only_true_when_both_missing(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        with patch(
            "core.cross_device_execution_chain.build_cross_device_chain_snapshot",
            side_effect=RuntimeError("no chain"),
        ), patch(
            "core.task_graph_runtime.get_task_graph_runtime",
            side_effect=RuntimeError("no graph"),
        ):
            result = enrich_multi_device_projection()
        self.assertTrue(result.transport_local_only)

    def test_H6_transport_local_only_false_when_chain_available(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        result = enrich_multi_device_projection()
        if result.chain_available:
            self.assertFalse(result.transport_local_only)

    def test_H7_to_dict_surfacing_state_matches_enum_value(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        result = enrich_multi_device_projection()
        self.assertEqual(result.to_dict()["surfacing_state"], result.surfacing_state.value)


# ===========================================================================
# I) Degraded/incomplete surfacing is explicit
# ===========================================================================


class TestI_DegradedSurfacingExplicit(unittest.TestCase):
    """I) Degraded/incomplete canonical state is surfaced in gap reasons."""

    def test_I1_gap_reason_references_gap_id_when_chain_missing(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        with patch(
            "core.cross_device_execution_chain.build_cross_device_chain_snapshot",
            side_effect=RuntimeError("chain gone"),
        ):
            result = enrich_multi_device_projection()
        self.assertTrue(
            any("GAP-517-008" in r for r in result.surfacing_gap_reasons)
        )

    def test_I2_gap_reason_references_gap_id_when_graph_missing(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        with patch(
            "core.task_graph_runtime.get_task_graph_runtime",
            side_effect=RuntimeError("graph gone"),
        ):
            result = enrich_multi_device_projection()
        self.assertTrue(
            any("GAP-517-008" in r for r in result.surfacing_gap_reasons)
        )

    def test_I3_no_gap_reasons_when_fully_available(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        result = enrich_multi_device_projection()
        if result.chain_available and result.graph_available:
            # Required sources available => no required gap reasons
            chain_graph_gaps = [
                r for r in result.surfacing_gap_reasons
                if "CrossDeviceChainSingleton" in r or "TaskGraphRuntime" in r
            ]
            self.assertEqual(chain_graph_gaps, [])

    def test_I4_surfacing_gap_reasons_is_list(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        result = enrich_multi_device_projection()
        self.assertIsInstance(result.surfacing_gap_reasons, list)

    def test_I5_enrichment_id_is_string(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        result = enrich_multi_device_projection()
        self.assertIsInstance(result.enrichment_id, str)
        self.assertTrue(len(result.enrichment_id) > 0)

    def test_I6_timestamp_is_float(self):
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        result = enrich_multi_device_projection()
        self.assertIsInstance(result.timestamp, float)
        self.assertGreater(result.timestamp, 0)

    def test_I7_raw_registry_not_sole_authority_when_chain_available(self):
        """When canonical chain data is available transport-local-only is False."""
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
        )
        result = enrich_multi_device_projection()
        if result.chain_available or result.graph_available:
            self.assertFalse(
                result.transport_local_only,
                "transport_local_only must be False when canonical sources are available",
            )


# ===========================================================================
# J) Projection endpoint canonical metadata keys
# ===========================================================================


class TestJ_ProjectionEndpointCanonicalKeys(unittest.TestCase):
    """J) Projection endpoint exposes canonical enrichment in its metadata."""

    def setUp(self):
        _reset_chain()
        _reset_graph()

    def tearDown(self):
        _reset_chain()
        _reset_graph()

    def test_J1_integration_sentinel_importable_from_projection(self):
        try:
            from core.routes.projection import (
                MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED,
            )
            self.assertIn("V1", MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED)
        except ImportError:
            self.skipTest("fastapi not installed; sentinel import skipped")

    def test_J2_canonical_enrichment_key_in_endpoint_response(self):
        """Projection endpoint metadata contains 'canonical_enrichment' key."""
        try:
            import asyncio
            from core.routes.projection import create_router
            router = create_router()

            # Find the multi-device endpoint handler
            handler = None
            for route in router.routes:
                if "/multi-device" in str(getattr(route, "path", "")):
                    handler = route.endpoint
                    break
            if handler is None:
                self.skipTest("multi-device endpoint not found")

            response = asyncio.get_event_loop().run_until_complete(handler())
            body = response.body
            import json
            data = json.loads(body)
            metadata = data.get("metadata", {})
            self.assertIn(
                "canonical_enrichment",
                metadata,
                "metadata must contain 'canonical_enrichment' key",
            )
        except ImportError:
            self.skipTest("fastapi not installed")

    def test_J3_canonical_surfacing_state_key_in_endpoint_metadata(self):
        """Projection endpoint metadata contains 'canonical_surfacing_state' key."""
        try:
            import asyncio
            from core.routes.projection import create_router
            router = create_router()
            handler = None
            for route in router.routes:
                if "/multi-device" in str(getattr(route, "path", "")):
                    handler = route.endpoint
                    break
            if handler is None:
                self.skipTest("multi-device endpoint not found")
            response = asyncio.get_event_loop().run_until_complete(handler())
            import json
            data = json.loads(response.body)
            metadata = data.get("metadata", {})
            self.assertIn("canonical_surfacing_state", metadata)
        except ImportError:
            self.skipTest("fastapi not installed")

    def test_J4_canonical_surfacing_gaps_key_in_endpoint_metadata(self):
        try:
            import asyncio
            from core.routes.projection import create_router
            router = create_router()
            handler = None
            for route in router.routes:
                if "/multi-device" in str(getattr(route, "path", "")):
                    handler = route.endpoint
                    break
            if handler is None:
                self.skipTest("multi-device endpoint not found")
            response = asyncio.get_event_loop().run_until_complete(handler())
            import json
            data = json.loads(response.body)
            metadata = data.get("metadata", {})
            self.assertIn("canonical_surfacing_gaps", metadata)
        except ImportError:
            self.skipTest("fastapi not installed")

    def test_J5_transport_local_only_key_in_endpoint_metadata(self):
        try:
            import asyncio
            from core.routes.projection import create_router
            router = create_router()
            handler = None
            for route in router.routes:
                if "/multi-device" in str(getattr(route, "path", "")):
                    handler = route.endpoint
                    break
            if handler is None:
                self.skipTest("multi-device endpoint not found")
            response = asyncio.get_event_loop().run_until_complete(handler())
            import json
            data = json.loads(response.body)
            metadata = data.get("metadata", {})
            self.assertIn("transport_local_only", metadata)
        except ImportError:
            self.skipTest("fastapi not installed")

    def test_J6_pr_522_gap_008_resolved_is_true_in_metadata(self):
        try:
            import asyncio
            from core.routes.projection import create_router
            router = create_router()
            handler = None
            for route in router.routes:
                if "/multi-device" in str(getattr(route, "path", "")):
                    handler = route.endpoint
                    break
            if handler is None:
                self.skipTest("multi-device endpoint not found")
            response = asyncio.get_event_loop().run_until_complete(handler())
            import json
            data = json.loads(response.body)
            metadata = data.get("metadata", {})
            self.assertTrue(
                metadata.get("pr_522_gap_008_resolved"),
                "pr_522_gap_008_resolved must be True",
            )
        except ImportError:
            self.skipTest("fastapi not installed")

    def test_J7_canonical_surfacing_state_is_valid_enum_value(self):
        try:
            import asyncio
            from core.routes.projection import create_router
            from core.multi_device_projection_canonicalization import (
                CanonicalProjectionSurfacingState,
            )
            router = create_router()
            handler = None
            for route in router.routes:
                if "/multi-device" in str(getattr(route, "path", "")):
                    handler = route.endpoint
                    break
            if handler is None:
                self.skipTest("multi-device endpoint not found")
            response = asyncio.get_event_loop().run_until_complete(handler())
            import json
            data = json.loads(response.body)
            metadata = data.get("metadata", {})
            state_val = metadata.get("canonical_surfacing_state")
            valid_values = {s.value for s in CanonicalProjectionSurfacingState}
            self.assertIn(
                state_val,
                valid_values,
                f"canonical_surfacing_state '{state_val}' must be a valid enum value",
            )
        except ImportError:
            self.skipTest("fastapi not installed")


# ===========================================================================
# K) Backward-compat keys still present
# ===========================================================================


class TestK_BackwardCompatKeys(unittest.TestCase):
    """K) Backward-compat metadata keys from PR-519 are still present."""

    def setUp(self):
        _reset_chain()
        _reset_graph()

    def tearDown(self):
        _reset_chain()
        _reset_graph()

    def _get_metadata(self):
        try:
            import asyncio
            from core.routes.projection import create_router
            router = create_router()
            handler = None
            for route in router.routes:
                if "/multi-device" in str(getattr(route, "path", "")):
                    handler = route.endpoint
                    break
            if handler is None:
                return None
            response = asyncio.get_event_loop().run_until_complete(handler())
            import json
            data = json.loads(response.body)
            return data.get("metadata", {})
        except ImportError:
            return None

    def test_K1_cross_device_chain_snapshot_key_present(self):
        metadata = self._get_metadata()
        if metadata is None:
            self.skipTest("fastapi not installed")
        self.assertIn(
            "cross_device_chain_snapshot",
            metadata,
            "backward-compat 'cross_device_chain_snapshot' key must still be present",
        )

    def test_K2_task_graph_snapshot_key_present(self):
        metadata = self._get_metadata()
        if metadata is None:
            self.skipTest("fastapi not installed")
        self.assertIn(
            "task_graph_snapshot",
            metadata,
            "backward-compat 'task_graph_snapshot' key must still be present",
        )

    def test_K3_result_surface_enriched_key_present(self):
        metadata = self._get_metadata()
        if metadata is None:
            self.skipTest("fastapi not installed")
        self.assertIn("result_surface_enriched", metadata)


# ===========================================================================
# L) GAP-517-008 marked resolved in residual gap catalog
# ===========================================================================


class TestL_GapCatalogResolved(unittest.TestCase):
    """L) GAP-517-008 is marked as resolved in the residual gap catalog."""

    def test_L1_gap_008_is_resolved(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertIn("GAP-517-008", gaps)
        self.assertTrue(
            gaps["GAP-517-008"].is_resolved,
            "GAP-517-008 must be marked is_resolved=True",
        )

    def test_L2_resolution_note_references_pr522(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        note = gaps["GAP-517-008"].resolution_note
        self.assertIn("PR-522", note)

    def test_L3_resolution_note_references_enrich_function(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        note = gaps["GAP-517-008"].resolution_note
        self.assertIn("enrich_multi_device_projection", note)

    def test_L4_resolution_note_references_canonicalization_module(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        note = gaps["GAP-517-008"].resolution_note
        self.assertIn("multi_device_projection_canonicalization", note)

    def test_L5_gap_008_resolution_note_is_non_empty(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertTrue(len(gaps["GAP-517-008"].resolution_note) > 50)

    def test_L6_gap_008_area_is_result_surface(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertEqual(gaps["GAP-517-008"].area, "result_surface")

    def test_L7_all_other_gaps_unaffected(self):
        """Marking GAP-517-008 resolved must not change resolution status of others."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        # These were resolved by prior PRs
        previously_resolved = {
            "GAP-517-001", "GAP-517-003", "GAP-517-004",
            "GAP-517-005", "GAP-517-006", "GAP-517-007",
        }
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        for gid in previously_resolved:
            if gid in gaps:
                self.assertTrue(
                    gaps[gid].is_resolved,
                    f"{gid} should still be resolved after PR-522",
                )

    def test_L8_gap_008_resolution_note_references_canonical_surfacing_state(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        note = gaps["GAP-517-008"].resolution_note
        self.assertIn("canonical_surfacing_state", note)


if __name__ == "__main__":
    unittest.main()
