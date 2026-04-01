#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr2_result_correlation_chain.py
==========================================
PR-2 — Canonical Message Interop: Result Correlation Tests.

Validates that:
 1.  extract_correlation returns CorrelationFields instance.
 2.  extract_correlation with task_id in payload preserves task_id.
 3.  extract_correlation with trace_id in payload preserves trace_id.
 4.  extract_correlation with session_id in payload preserves session_id.
 5.  extract_correlation with no task_id generates non-empty task_id.
 6.  extract_correlation with no trace_id generates non-empty trace_id.
 7.  extract_correlation session_id is None when absent.
 8.  extract_correlation reads trace_id from context sub-dict.
 9.  extract_correlation reads session_id from context sub-dict.
10.  extract_correlation reads task_id from 'request_id' alias.
11.  extract_correlation with non-dict returns valid CorrelationFields.
12.  normalize_to_result_envelope with task_id kwarg preserves task_id.
13.  normalize_to_result_envelope with trace_id kwarg preserves trace_id.
14.  normalize_to_result_envelope with success=True result is success.
15.  normalize_to_result_envelope with 'status': 'ok' result is success.
16.  normalize_to_result_envelope with 'error' result is not success.
17.  normalize_to_result_envelope result has non-empty task_id.
18.  normalize_to_result_envelope result has non-empty trace_id.
19.  normalize_to_result_envelope device_id kwarg is reflected in envelope.
20.  normalize_to_result_envelope extracts task_id from raw when kwarg absent.
21.  ResultEnvelope.task_id can be traced back to originating TaskEnvelope.task_id.
22.  extract_correlation two calls with same dict return same task_id.
23.  normalize_to_task_envelope → extract_correlation round-trip preserves IDs.
24.  normalize_to_result_envelope route_mode propagated.
25.  CorrelationFields to_dict session_id is None when session absent.
"""

from __future__ import annotations

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExtractCorrelation(unittest.TestCase):
    """Tests 1–11: extract_correlation behaviour."""

    def _extract(self, payload):
        from core.message_interop import extract_correlation
        return extract_correlation(payload)

    def test_01_returns_correlation_fields_instance(self):
        from core.message_interop import CorrelationFields
        cf = self._extract({"task_id": "t1", "trace_id": "tr1"})
        self.assertIsInstance(cf, CorrelationFields)

    def test_02_preserves_task_id(self):
        cf = self._extract({"task_id": "task_preserve_me"})
        self.assertEqual(cf.task_id, "task_preserve_me")

    def test_03_preserves_trace_id(self):
        cf = self._extract({"trace_id": "trace_preserve_me"})
        self.assertEqual(cf.trace_id, "trace_preserve_me")

    def test_04_preserves_session_id(self):
        cf = self._extract({"session_id": "sess_preserve"})
        self.assertEqual(cf.session_id, "sess_preserve")

    def test_05_generates_task_id_when_absent(self):
        cf = self._extract({})
        self.assertTrue(len(cf.task_id) > 0)

    def test_06_generates_trace_id_when_absent(self):
        cf = self._extract({})
        self.assertTrue(len(cf.trace_id) > 0)

    def test_07_session_id_none_when_absent(self):
        cf = self._extract({})
        self.assertIsNone(cf.session_id)

    def test_08_reads_trace_id_from_context_subdict(self):
        cf = self._extract({"context": {"trace_id": "trace_from_ctx"}})
        self.assertEqual(cf.trace_id, "trace_from_ctx")

    def test_09_reads_session_id_from_context_subdict(self):
        cf = self._extract({"context": {"session_id": "sess_from_ctx"}})
        self.assertEqual(cf.session_id, "sess_from_ctx")

    def test_10_reads_task_id_from_request_id_alias(self):
        cf = self._extract({"request_id": "req_alias_123"})
        self.assertEqual(cf.task_id, "req_alias_123")

    def test_11_non_dict_returns_valid_correlation_fields(self):
        cf = self._extract("not_a_dict")  # type: ignore[arg-type]
        self.assertTrue(len(cf.task_id) > 0)
        self.assertTrue(len(cf.trace_id) > 0)


class TestNormalizeToResultEnvelope(unittest.TestCase):
    """Tests 12–20, 24: normalize_to_result_envelope behaviour."""

    def _normalize_result(self, raw, **kwargs):
        from core.message_interop import normalize_to_result_envelope
        return normalize_to_result_envelope(raw, **kwargs)

    def test_12_preserves_task_id_kwarg(self):
        env = self._normalize_result({}, task_id="task_kwarg_001", trace_id="tr_001")
        self.assertEqual(env.task_id, "task_kwarg_001")

    def test_13_preserves_trace_id_kwarg(self):
        env = self._normalize_result({}, task_id="t1", trace_id="trace_kwarg_002")
        self.assertEqual(env.trace_id, "trace_kwarg_002")

    def test_14_success_true_when_result_has_success_flag(self):
        env = self._normalize_result({"success": True, "status": "done"}, task_id="t1", trace_id="tr1")
        self.assertTrue(env.success)

    def test_15_success_true_when_status_ok(self):
        env = self._normalize_result({"status": "ok"}, task_id="t1", trace_id="tr1")
        self.assertTrue(env.success)

    def test_16_not_success_when_error_present(self):
        env = self._normalize_result(
            {"status": "error", "error": "something went wrong"},
            task_id="t1", trace_id="tr1",
        )
        # 'error' status should not be mapped to success
        self.assertFalse(env.success)
        # Error message should be preserved in the envelope
        self.assertIsNotNone(env.error)
        self.assertIn("something went wrong", env.error)

    def test_17_result_has_non_empty_task_id(self):
        env = self._normalize_result({"status": "ok"}, trace_id="tr1")
        self.assertTrue(len(env.task_id) > 0)

    def test_18_result_has_non_empty_trace_id(self):
        env = self._normalize_result({"status": "ok"}, task_id="t1")
        self.assertTrue(len(env.trace_id) > 0)

    def test_19_device_id_reflected_in_envelope(self):
        env = self._normalize_result({}, task_id="t1", trace_id="tr1", device_id="dev_test")
        self.assertEqual(env.device_id, "dev_test")

    def test_20_extracts_task_id_from_raw_when_kwarg_absent(self):
        env = self._normalize_result({"task_id": "task_from_raw", "status": "ok"}, trace_id="tr1")
        self.assertEqual(env.task_id, "task_from_raw")

    def test_24_route_mode_propagated(self):
        env = self._normalize_result({}, task_id="t1", trace_id="tr1", route_mode="hybrid")
        self.assertEqual(env.route_mode, "hybrid")


class TestEndToEndCorrelation(unittest.TestCase):
    """Tests 21–23, 25: End-to-end correlation chain."""

    def test_21_result_task_id_traceable_to_envelope(self):
        """ResultEnvelope.task_id matches originating TaskEnvelope.task_id."""
        from core.message_interop import normalize_to_task_envelope, normalize_to_result_envelope

        task_payload = {
            "task_id": "e2e_task_001",
            "trace_id": "e2e_trace_001",
            "task_type": "screenshot",
            "target_device_id": "dev_e2e",
        }
        envelope = normalize_to_task_envelope(task_payload, source="test")

        raw_result = {
            "status": "success",
            "device_id": "dev_e2e",
            "data": {"screenshot": "base64..."},
        }
        result = normalize_to_result_envelope(
            raw_result,
            task_id=envelope.task_id,
            trace_id=envelope.trace_id,
            device_id=envelope.target,
        )
        self.assertEqual(result.task_id, envelope.task_id)
        self.assertEqual(result.trace_id, envelope.trace_id)

    def test_22_extract_correlation_deterministic_same_dict(self):
        """Two extract_correlation calls on same dict return same task_id."""
        from core.message_interop import extract_correlation
        d = {"task_id": "deterministic_001", "trace_id": "tr_det"}
        cf1 = extract_correlation(d)
        cf2 = extract_correlation(d)
        self.assertEqual(cf1.task_id, cf2.task_id)
        self.assertEqual(cf1.trace_id, cf2.trace_id)

    def test_23_round_trip_preserves_ids(self):
        """normalize_to_task_envelope → extract_correlation round-trip."""
        from core.message_interop import normalize_to_task_envelope, extract_correlation

        task_payload = {
            "task_id": "round_trip_001",
            "trace_id": "rt_trace_001",
            "session_id": "sess_rt",
            "task_type": "open_app",
        }
        envelope = normalize_to_task_envelope(task_payload, source="test")

        # Simulate: envelope gets converted to dict and then passed through another
        # system that extracts correlation fields.
        envelope_as_dict = {
            "task_id": envelope.task_id,
            "trace_id": envelope.trace_id,
            "session_id": envelope.session_id,
        }
        corr = extract_correlation(envelope_as_dict)
        self.assertEqual(corr.task_id, "round_trip_001")
        self.assertEqual(corr.trace_id, "rt_trace_001")
        self.assertEqual(corr.session_id, "sess_rt")

    def test_25_correlation_to_dict_session_none_when_absent(self):
        from core.message_interop import CorrelationFields
        cf = CorrelationFields(task_id="t1", trace_id="tr1")
        d = cf.to_dict()
        self.assertIsNone(d["session_id"])


if __name__ == "__main__":
    unittest.main()
