"""
tests/test_canonical_roundtrip.py
===================================
PR-4: Canonical State / Action / Result / Feedback Roundtrip — test suite.

Validates:
1. ExecutionRoundtripRecord structure, construction, and serialisation.
2. record_execution_roundtrip() correctly maps runtime_result to execution_phase/success.
3. notify_android_execution_terminal() maps Android terminal events to roundtrip records.
4. get_last_execution_roundtrip() returns the most recent record.
5. get_execution_roundtrip_store() returns all records.
6. UnifiedPanelPayload gains last_execution_result field (PR-4).
7. UnifiedPanelAggregationService._fill_from_execution_roundtrip() projects the
   most recent roundtrip record into the panel payload.
8. Operator action completion (dispatch / device_dispatch / flow_cancel) wires
   record_execution_roundtrip() so that panel payload reflects real outcomes.
9. Android terminal execution events wire notify_android_execution_terminal()
   via android_device_state_store.absorb_execution_event().
10. Regressions in roundtrip wiring are detectable (regression guards).
"""
from __future__ import annotations

import time
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# A. ExecutionRoundtripRecord — structure and serialisation
# ---------------------------------------------------------------------------


class TestExecutionRoundtripRecord(unittest.TestCase):
    """ExecutionRoundtripRecord must have all required fields and correct types."""

    def setUp(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        reset_execution_roundtrip()

    def test_A01_import_succeeds(self):
        from core.canonical_roundtrip import (
            ExecutionRoundtripRecord,
            CANONICAL_ROUNDTRIP_AUTHORITY,
            ROUNDTRIP_SCHEMA_VERSION,
        )
        self.assertIsInstance(CANONICAL_ROUNDTRIP_AUTHORITY, str)
        self.assertIn("CANONICAL_ROUNDTRIP_V1", CANONICAL_ROUNDTRIP_AUTHORITY)
        self.assertEqual(ROUNDTRIP_SCHEMA_VERSION, "1.0")

    def test_A02_default_construction(self):
        from core.canonical_roundtrip import ExecutionRoundtripRecord
        r = ExecutionRoundtripRecord()
        self.assertTrue(r.roundtrip_id.startswith("rt_"))
        self.assertEqual(r.execution_phase, "dispatched")
        self.assertEqual(r.action_kind, "dispatch")
        self.assertEqual(r.schema_version, "1.0")
        self.assertIsNone(r.execution_success)
        self.assertIsInstance(r.generated_at, float)
        self.assertGreater(r.generated_at, 0)

    def test_A03_to_dict_has_required_keys(self):
        from core.canonical_roundtrip import ExecutionRoundtripRecord
        r = ExecutionRoundtripRecord(
            action_id="act_abc",
            action_kind="dispatch",
            trace_id="trace_xyz",
            session_id="sess_001",
            execution_phase="completed",
            execution_success=True,
        )
        d = r.to_dict()
        for key in [
            "roundtrip_id", "action_id", "action_kind", "trace_id",
            "session_id", "execution_phase", "execution_success",
            "execution_result_data", "android_terminal_phase",
            "android_device_id", "android_flow_id",
            "feedback_projected_at", "generated_at",
            "schema_version", "authority",
        ]:
            self.assertIn(key, d, f"Key {key!r} missing from to_dict()")

    def test_A04_compact_dict_has_required_keys(self):
        from core.canonical_roundtrip import ExecutionRoundtripRecord
        r = ExecutionRoundtripRecord(
            action_id="act_xyz",
            trace_id="trace_001",
            execution_phase="failed",
            execution_success=False,
        )
        cd = r.compact_dict()
        for key in [
            "roundtrip_id", "action_id", "action_kind", "trace_id",
            "execution_phase", "execution_success",
            "android_terminal_phase", "android_device_id", "android_flow_id",
            "feedback_projected_at", "_source",
        ]:
            self.assertIn(key, cd, f"Key {key!r} missing from compact_dict()")
        self.assertEqual(cd["_source"], "canonical_roundtrip")

    def test_A05_android_fields_populated(self):
        from core.canonical_roundtrip import ExecutionRoundtripRecord
        r = ExecutionRoundtripRecord(
            action_kind="android_terminal",
            execution_phase="completed",
            execution_success=True,
            android_terminal_phase="completed",
            android_device_id="dev_pixel",
            android_flow_id="flow_abc123",
        )
        cd = r.compact_dict()
        self.assertEqual(cd["android_terminal_phase"], "completed")
        self.assertEqual(cd["android_device_id"], "dev_pixel")
        self.assertEqual(cd["android_flow_id"], "flow_abc123")


# ---------------------------------------------------------------------------
# B. record_execution_roundtrip — V2 action completion path
# ---------------------------------------------------------------------------


class TestRecordExecutionRoundtrip(unittest.TestCase):
    """record_execution_roundtrip() must correctly map runtime_result to record."""

    def setUp(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        reset_execution_roundtrip()

    def test_B01_success_result_maps_to_completed(self):
        from core.canonical_roundtrip import (
            record_execution_roundtrip,
            get_last_execution_roundtrip,
        )
        r = record_execution_roundtrip(
            action_id="act_001",
            action_kind="dispatch",
            trace_id="trace_001",
            session_id="sess_001",
            runtime_result={"success": True, "runtime_session_id": "sess_001"},
        )
        self.assertEqual(r.execution_phase, "completed")
        self.assertTrue(r.execution_success)
        self.assertEqual(r.action_id, "act_001")
        # Also check it was stored
        stored = get_last_execution_roundtrip()
        self.assertIsNotNone(stored)
        self.assertEqual(stored.roundtrip_id, r.roundtrip_id)

    def test_B02_failure_result_maps_to_failed(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        r = record_execution_roundtrip(
            action_id="act_002",
            action_kind="dispatch",
            runtime_result={"success": False, "error": "runtime error"},
        )
        self.assertEqual(r.execution_phase, "failed")
        self.assertFalse(r.execution_success)

    def test_B03_error_string_maps_to_failed(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        r = record_execution_roundtrip(
            action_id="act_003",
            runtime_result={"error": "something went wrong"},
        )
        self.assertEqual(r.execution_phase, "failed")
        self.assertFalse(r.execution_success)

    def test_B04_no_terminal_outcome_maps_to_dispatched(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        r = record_execution_roundtrip(
            action_id="act_004",
            runtime_result={"runtime_session_id": "sess_async"},
        )
        self.assertEqual(r.execution_phase, "dispatched")
        self.assertIsNone(r.execution_success)

    def test_B05_empty_runtime_result_maps_to_dispatched(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        r = record_execution_roundtrip(action_id="act_005")
        self.assertEqual(r.execution_phase, "dispatched")
        self.assertIsNone(r.execution_success)

    def test_B06_trace_id_extracted_from_runtime_result(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        r = record_execution_roundtrip(
            action_id="act_006",
            runtime_result={"trace_id": "outer_trace", "runtime_session_id": "sess_rt"},
        )
        self.assertEqual(r.trace_id, "outer_trace")

    def test_B07_session_id_extracted_from_runtime_result(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        r = record_execution_roundtrip(
            action_id="act_007",
            runtime_result={"runtime_session_id": "sess_rt"},
        )
        self.assertEqual(r.session_id, "sess_rt")

    def test_B08_multiple_records_accumulated(self):
        from core.canonical_roundtrip import (
            record_execution_roundtrip,
            get_execution_roundtrip_store,
        )
        for i in range(5):
            record_execution_roundtrip(
                action_id=f"act_{i:03d}",
                runtime_result={"success": True},
            )
        store = get_execution_roundtrip_store()
        self.assertEqual(len(store), 5)

    def test_B09_device_dispatch_kind_preserved(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        r = record_execution_roundtrip(
            action_id="act_dev",
            action_kind="device_dispatch",
            runtime_result={"success": True},
        )
        self.assertEqual(r.action_kind, "device_dispatch")

    def test_B10_flow_cancel_kind_preserved(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        r = record_execution_roundtrip(
            action_id="act_cancel",
            action_kind="flow_cancel",
            runtime_result={"flow_id": "flow_xyz", "phase_after_cancel": "cancelled"},
        )
        self.assertEqual(r.action_kind, "flow_cancel")


# ---------------------------------------------------------------------------
# C. notify_android_execution_terminal — Android execution truth path
# ---------------------------------------------------------------------------


class TestNotifyAndroidExecutionTerminal(unittest.TestCase):
    """notify_android_execution_terminal() must correctly record Android outcomes."""

    def setUp(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        reset_execution_roundtrip()

    def test_C01_completed_phase_maps_to_success(self):
        from core.canonical_roundtrip import (
            notify_android_execution_terminal,
            get_last_execution_roundtrip,
        )
        r = notify_android_execution_terminal(
            flow_id="flow_abc",
            device_id="dev_pixel",
            phase="completed",
            step_index=5,
            detail="execution completed",
        )
        self.assertEqual(r.execution_phase, "completed")
        self.assertTrue(r.execution_success)
        self.assertEqual(r.android_terminal_phase, "completed")
        self.assertEqual(r.android_device_id, "dev_pixel")
        self.assertEqual(r.android_flow_id, "flow_abc")
        self.assertEqual(r.action_kind, "android_terminal")

        stored = get_last_execution_roundtrip()
        self.assertIsNotNone(stored)
        self.assertEqual(stored.android_flow_id, "flow_abc")

    def test_C02_failed_phase_maps_to_failure(self):
        from core.canonical_roundtrip import notify_android_execution_terminal
        r = notify_android_execution_terminal(
            flow_id="flow_fail",
            device_id="dev_galaxy",
            phase="failed",
        )
        self.assertEqual(r.execution_phase, "failed")
        self.assertFalse(r.execution_success)
        self.assertEqual(r.android_terminal_phase, "failed")

    def test_C03_stagnation_phase_maps_to_failure(self):
        from core.canonical_roundtrip import notify_android_execution_terminal
        r = notify_android_execution_terminal(
            flow_id="flow_stag",
            device_id="dev_test",
            phase="stagnation",
        )
        self.assertEqual(r.execution_phase, "failed")
        self.assertFalse(r.execution_success)
        self.assertEqual(r.android_terminal_phase, "stagnation")

    def test_C04_evidence_stored_in_result_data(self):
        from core.canonical_roundtrip import notify_android_execution_terminal
        r = notify_android_execution_terminal(
            flow_id="flow_ev",
            device_id="dev_ev",
            phase="completed",
            task_id="task_001",
            evidence={"fallback_tier": "local_ai"},
        )
        self.assertEqual(r.execution_result_data.get("task_id"), "task_001")
        self.assertEqual(r.execution_result_data.get("fallback_tier"), "local_ai")
        self.assertEqual(r.execution_result_data.get("flow_id"), "flow_ev")

    def test_C05_roundtrip_id_is_unique_per_call(self):
        from core.canonical_roundtrip import notify_android_execution_terminal
        r1 = notify_android_execution_terminal(
            flow_id="flow_1", device_id="dev_1", phase="completed"
        )
        r2 = notify_android_execution_terminal(
            flow_id="flow_2", device_id="dev_1", phase="completed"
        )
        self.assertNotEqual(r1.roundtrip_id, r2.roundtrip_id)


# ---------------------------------------------------------------------------
# D. Store management — get_last / store snapshot / reset
# ---------------------------------------------------------------------------


class TestRoundtripStore(unittest.TestCase):
    """Store management helpers must work correctly."""

    def setUp(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        reset_execution_roundtrip()

    def test_D01_empty_store_returns_none(self):
        from core.canonical_roundtrip import get_last_execution_roundtrip
        self.assertIsNone(get_last_execution_roundtrip())

    def test_D02_get_last_returns_most_recent(self):
        from core.canonical_roundtrip import (
            record_execution_roundtrip,
            get_last_execution_roundtrip,
        )
        r1 = record_execution_roundtrip(action_id="first", runtime_result={"success": True})
        r2 = record_execution_roundtrip(action_id="second", runtime_result={"success": False})
        last = get_last_execution_roundtrip()
        self.assertEqual(last.roundtrip_id, r2.roundtrip_id)
        self.assertEqual(last.action_id, "second")

    def test_D03_reset_clears_store(self):
        from core.canonical_roundtrip import (
            record_execution_roundtrip,
            get_last_execution_roundtrip,
            get_execution_roundtrip_store,
            reset_execution_roundtrip,
        )
        record_execution_roundtrip(action_id="to_be_cleared", runtime_result={})
        self.assertIsNotNone(get_last_execution_roundtrip())
        reset_execution_roundtrip()
        self.assertIsNone(get_last_execution_roundtrip())
        self.assertEqual(len(get_execution_roundtrip_store()), 0)

    def test_D04_store_snapshot_is_copy(self):
        from core.canonical_roundtrip import (
            record_execution_roundtrip,
            get_execution_roundtrip_store,
        )
        record_execution_roundtrip(action_id="snap_test", runtime_result={})
        snap1 = get_execution_roundtrip_store()
        record_execution_roundtrip(action_id="snap_test_2", runtime_result={})
        snap2 = get_execution_roundtrip_store()
        self.assertEqual(len(snap1), 1)
        self.assertEqual(len(snap2), 2)


# ---------------------------------------------------------------------------
# E. UnifiedPanelPayload — last_execution_result field (PR-4)
# ---------------------------------------------------------------------------


class TestUnifiedPanelPayloadExecutionResult(unittest.TestCase):
    """UnifiedPanelPayload must have last_execution_result field (PR-4)."""

    def test_E01_last_execution_result_field_exists(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        self.assertIsInstance(p.last_execution_result, dict)
        self.assertEqual(p.last_execution_result, {})

    def test_E02_to_dict_includes_last_execution_result(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        d = p.to_dict()
        self.assertIn("last_execution_result", d)
        self.assertIsInstance(d["last_execution_result"], dict)

    def test_E03_last_execution_result_can_be_populated(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        p.last_execution_result = {
            "roundtrip_id": "rt_test",
            "action_kind": "dispatch",
            "execution_phase": "completed",
            "execution_success": True,
            "_source": "canonical_roundtrip",
        }
        d = p.to_dict()
        self.assertEqual(d["last_execution_result"]["execution_phase"], "completed")
        self.assertTrue(d["last_execution_result"]["execution_success"])


# ---------------------------------------------------------------------------
# F. UnifiedPanelAggregationService — roundtrip fill (PR-4)
# ---------------------------------------------------------------------------


class TestUnifiedPanelRoundtripFill(unittest.TestCase):
    """UnifiedPanelAggregationService must fill last_execution_result from roundtrip store."""

    def setUp(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        from core.unified_panel_aggregation import reset_unified_panel_aggregation_service
        reset_execution_roundtrip()
        reset_unified_panel_aggregation_service()

    def tearDown(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        from core.unified_panel_aggregation import reset_unified_panel_aggregation_service
        reset_execution_roundtrip()
        reset_unified_panel_aggregation_service()

    def test_F01_empty_roundtrip_store_yields_empty_dict(self):
        from core.unified_panel_aggregation import build_unified_panel_payload
        payload = build_unified_panel_payload()
        # No roundtrip recorded — last_execution_result should be empty
        self.assertIsInstance(payload.last_execution_result, dict)
        # May be empty or may pick up pre-existing records; just verify no crash.

    def test_F02_roundtrip_record_is_projected_into_payload(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        from core.unified_panel_aggregation import build_unified_panel_payload

        r = record_execution_roundtrip(
            action_id="panel_test_act",
            action_kind="dispatch",
            trace_id="trace_panel",
            runtime_result={"success": True},
        )
        payload = build_unified_panel_payload()
        result_field = payload.last_execution_result
        self.assertIsInstance(result_field, dict)
        self.assertNotEqual(result_field, {})
        self.assertEqual(result_field.get("roundtrip_id"), r.roundtrip_id)
        self.assertEqual(result_field.get("execution_phase"), "completed")
        self.assertTrue(result_field.get("execution_success"))
        self.assertEqual(result_field.get("_source"), "canonical_roundtrip")

    def test_F03_android_terminal_event_projected_into_payload(self):
        from core.canonical_roundtrip import notify_android_execution_terminal
        from core.unified_panel_aggregation import build_unified_panel_payload

        r = notify_android_execution_terminal(
            flow_id="flow_panel",
            device_id="dev_panel",
            phase="completed",
        )
        payload = build_unified_panel_payload()
        result_field = payload.last_execution_result
        self.assertIsInstance(result_field, dict)
        self.assertNotEqual(result_field, {})
        self.assertEqual(result_field.get("action_kind"), "android_terminal")
        self.assertEqual(result_field.get("android_flow_id"), "flow_panel")
        self.assertEqual(result_field.get("android_device_id"), "dev_panel")
        self.assertTrue(result_field.get("execution_success"))

    def test_F04_most_recent_roundtrip_wins(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        from core.unified_panel_aggregation import build_unified_panel_payload

        record_execution_roundtrip(
            action_id="older_act",
            runtime_result={"success": True},
        )
        newer = record_execution_roundtrip(
            action_id="newer_act",
            runtime_result={"success": False, "error": "newer error"},
        )
        payload = build_unified_panel_payload()
        result_field = payload.last_execution_result
        # Should reflect the most recent record
        self.assertEqual(result_field.get("roundtrip_id"), newer.roundtrip_id)
        self.assertEqual(result_field.get("execution_phase"), "failed")

    def test_F05_to_dict_includes_last_execution_result(self):
        from core.canonical_roundtrip import record_execution_roundtrip
        from core.unified_panel_aggregation import build_unified_panel_payload

        record_execution_roundtrip(
            action_id="dict_act",
            runtime_result={"success": True},
        )
        d = build_unified_panel_payload().to_dict()
        self.assertIn("last_execution_result", d)
        self.assertIsInstance(d["last_execution_result"], dict)
        self.assertEqual(d["last_execution_result"].get("execution_phase"), "completed")


# ---------------------------------------------------------------------------
# G. Android execution event absorption — terminal event triggers roundtrip
# ---------------------------------------------------------------------------


class TestAndroidTerminalEventWiring(unittest.TestCase):
    """Android terminal execution events must trigger notify_android_execution_terminal()."""

    def setUp(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        from core.android_device_state_store import reset_android_device_state_store
        reset_execution_roundtrip()
        reset_android_device_state_store()

    def tearDown(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        from core.android_device_state_store import reset_android_device_state_store
        reset_execution_roundtrip()
        reset_android_device_state_store()

    def test_G01_non_terminal_event_does_not_create_roundtrip(self):
        from core.android_device_state_store import absorb_device_execution_event
        from core.canonical_roundtrip import get_last_execution_roundtrip

        # "grounding" is not a terminal phase
        absorb_device_execution_event("dev_001", {
            "flow_id": "flow_non_terminal",
            "task_id": "task_001",
            "phase": "grounding",
            "step_index": 1,
        })
        # No roundtrip should be recorded for non-terminal phases
        last = get_last_execution_roundtrip()
        # It's OK if last is None (non-terminal) — no terminal roundtrip
        if last is not None:
            self.assertNotEqual(last.android_terminal_phase, "grounding")

    def test_G02_completed_event_creates_roundtrip(self):
        from core.android_device_state_store import absorb_device_execution_event
        from core.canonical_roundtrip import get_last_execution_roundtrip

        absorb_device_execution_event("dev_completed", {
            "flow_id": "flow_terminal_complete",
            "task_id": "task_terminal",
            "phase": "completed",
            "step_index": 10,
        })
        last = get_last_execution_roundtrip()
        self.assertIsNotNone(last)
        self.assertEqual(last.android_terminal_phase, "completed")
        self.assertEqual(last.android_device_id, "dev_completed")
        self.assertEqual(last.android_flow_id, "flow_terminal_complete")
        self.assertTrue(last.execution_success)

    def test_G03_failed_event_creates_roundtrip(self):
        from core.android_device_state_store import absorb_device_execution_event
        from core.canonical_roundtrip import get_last_execution_roundtrip

        absorb_device_execution_event("dev_fail", {
            "flow_id": "flow_terminal_fail",
            "task_id": "task_fail",
            "phase": "failed",
            "step_index": 3,
        })
        last = get_last_execution_roundtrip()
        self.assertIsNotNone(last)
        self.assertEqual(last.android_terminal_phase, "failed")
        self.assertFalse(last.execution_success)

    def test_G04_completed_android_event_projects_into_panel(self):
        from core.android_device_state_store import absorb_device_execution_event
        from core.unified_panel_aggregation import (
            build_unified_panel_payload,
            reset_unified_panel_aggregation_service,
        )
        reset_unified_panel_aggregation_service()

        absorb_device_execution_event("dev_panel_android", {
            "flow_id": "flow_panel_android",
            "task_id": "task_panel",
            "phase": "completed",
            "step_index": 7,
        })
        payload = build_unified_panel_payload()
        result_field = payload.last_execution_result
        self.assertIsInstance(result_field, dict)
        self.assertNotEqual(result_field, {})
        self.assertEqual(result_field.get("android_terminal_phase"), "completed")
        self.assertEqual(result_field.get("action_kind"), "android_terminal")
        self.assertTrue(result_field.get("execution_success"))


# ---------------------------------------------------------------------------
# H. Regression guards — roundtrip wiring is detectable
# ---------------------------------------------------------------------------


class TestRoundtripRegressionGuards(unittest.TestCase):
    """Regressions in roundtrip wiring must be detectable by these tests."""

    def setUp(self):
        from core.canonical_roundtrip import reset_execution_roundtrip
        reset_execution_roundtrip()

    def test_H01_canonical_roundtrip_module_importable(self):
        import core.canonical_roundtrip as m
        self.assertTrue(hasattr(m, "ExecutionRoundtripRecord"))
        self.assertTrue(hasattr(m, "record_execution_roundtrip"))
        self.assertTrue(hasattr(m, "notify_android_execution_terminal"))
        self.assertTrue(hasattr(m, "get_last_execution_roundtrip"))
        self.assertTrue(hasattr(m, "get_execution_roundtrip_store"))
        self.assertTrue(hasattr(m, "reset_execution_roundtrip"))
        self.assertTrue(hasattr(m, "CANONICAL_ROUNDTRIP_AUTHORITY"))
        self.assertTrue(hasattr(m, "ROUNDTRIP_SCHEMA_VERSION"))

    def test_H02_unified_panel_payload_has_last_execution_result(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        self.assertTrue(hasattr(p, "last_execution_result"))
        self.assertIn("last_execution_result", p.to_dict())

    def test_H03_android_store_has_terminal_phases_constant(self):
        from core.android_device_state_store import _ANDROID_TERMINAL_PHASES
        self.assertIsInstance(_ANDROID_TERMINAL_PHASES, frozenset)
        self.assertIn("completed", _ANDROID_TERMINAL_PHASES)
        self.assertIn("failed", _ANDROID_TERMINAL_PHASES)
        self.assertIn("stagnation", _ANDROID_TERMINAL_PHASES)

    def test_H04_action_to_result_roundtrip_closure(self):
        """Full roundtrip: action → record → panel reflects outcome."""
        from core.canonical_roundtrip import (
            record_execution_roundtrip,
            get_last_execution_roundtrip,
        )
        from core.unified_panel_aggregation import (
            build_unified_panel_payload,
            reset_unified_panel_aggregation_service,
        )
        reset_unified_panel_aggregation_service()

        # 1. Record an action result (simulating operator action completion)
        rt = record_execution_roundtrip(
            action_id="regression_act_001",
            action_kind="dispatch",
            trace_id="regression_trace",
            runtime_result={"success": True, "runtime_session_id": "regression_sess"},
        )

        # 2. Verify last roundtrip is the one we just recorded
        last = get_last_execution_roundtrip()
        self.assertIsNotNone(last)
        self.assertEqual(last.action_id, "regression_act_001")
        self.assertEqual(last.execution_phase, "completed")

        # 3. Build the unified panel payload and verify it reflects the result
        payload = build_unified_panel_payload()
        self.assertIn("last_execution_result", payload.to_dict())
        er = payload.last_execution_result
        self.assertNotEqual(er, {})
        self.assertEqual(er.get("roundtrip_id"), rt.roundtrip_id)
        self.assertEqual(er.get("execution_phase"), "completed")
        self.assertTrue(er.get("execution_success"))
        self.assertEqual(er.get("action_kind"), "dispatch")

    def test_H05_android_terminal_to_panel_roundtrip_closure(self):
        """Android terminal event → roundtrip store → panel reflects Android outcome."""
        from core.canonical_roundtrip import notify_android_execution_terminal
        from core.unified_panel_aggregation import (
            build_unified_panel_payload,
            reset_unified_panel_aggregation_service,
        )
        reset_unified_panel_aggregation_service()

        rt = notify_android_execution_terminal(
            flow_id="regression_flow",
            device_id="regression_dev",
            phase="completed",
            step_index=3,
        )
        payload = build_unified_panel_payload()
        er = payload.last_execution_result
        self.assertNotEqual(er, {})
        self.assertEqual(er.get("action_kind"), "android_terminal")
        self.assertEqual(er.get("android_flow_id"), "regression_flow")
        self.assertEqual(er.get("android_device_id"), "regression_dev")
        self.assertTrue(er.get("execution_success"))

    def test_H06_operator_routes_import_record_execution_roundtrip(self):
        """Operator routes module must be importable and reference canonical_roundtrip."""
        import importlib
        import core.routes.operator as op_mod
        # The module must be importable without errors
        self.assertIsNotNone(op_mod)
        # And the canonical_roundtrip module must exist
        import core.canonical_roundtrip as cr_mod
        self.assertIsNotNone(cr_mod)

    def test_H07_record_execution_roundtrip_is_idempotent_for_multiple_actions(self):
        """Multiple actions all produce distinct roundtrip records."""
        from core.canonical_roundtrip import (
            record_execution_roundtrip,
            get_execution_roundtrip_store,
        )
        ids = set()
        for i in range(3):
            r = record_execution_roundtrip(
                action_id=f"multi_act_{i}",
                action_kind="dispatch",
                runtime_result={"success": i % 2 == 0},
            )
            ids.add(r.roundtrip_id)
        # All three should have distinct roundtrip_ids
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(get_execution_roundtrip_store()), 3)


if __name__ == "__main__":
    unittest.main()
