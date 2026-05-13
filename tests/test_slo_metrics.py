"""
tests/test_slo_metrics.py — PR-G2 SLO Metrics
================================================

Tests for ``core/slo_metrics.py``:

1.  SLOMetrics.record_startup()          — sets duration_ms, ignores subsequent calls.
2.  SLOMetrics.record_heartbeat()        — updates totals and rolling window.
3.  SLOMetrics.heartbeat_loss_rate       — correct fraction over rolling window.
4.  SLOMetrics.heartbeat_loss_rate       — returns 0.0 with no data.
5.  SLOMetrics.record_reconnect()        — increments counter.
6.  SLOMetrics.record_command_latency()  — samples accumulated.
7.  SLOMetrics.command_latency_p50/p95  — correct percentiles.
8.  SLOMetrics.command_latency_p50/p95  — return NaN when empty.
9.  SLOMetrics.snapshot()               — correct JSON structure and types.
10. SLOMetrics.prometheus_text()         — contains expected metric names.
11. SLOMetrics.prometheus_text()         — valid exposition format (HELP/TYPE lines).
12. Rolling window eviction              — old samples are discarded when window full.
13. Thread safety                        — concurrent writes don't corrupt counters.
14. get_slo_metrics()                    — returns the same singleton across calls.
15. /metrics endpoint                    — returns 200 with text/plain content-type.
16. /api/v1/slo/metrics endpoint         — returns 200 with valid JSON schema.
"""

from __future__ import annotations

import math
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. record_startup
# ---------------------------------------------------------------------------

class TestRecordStartup(unittest.TestCase):
    def _fresh(self):
        from core.slo_metrics import SLOMetrics
        return SLOMetrics()

    def test_records_first_call(self):
        m = self._fresh()
        m.record_startup(1234.5)
        self.assertAlmostEqual(m.startup_duration_ms, 1234.5)

    def test_ignores_subsequent_calls(self):
        m = self._fresh()
        m.record_startup(100.0)
        m.record_startup(9999.0)
        self.assertAlmostEqual(m.startup_duration_ms, 100.0)

    def test_initial_value_is_none(self):
        m = self._fresh()
        self.assertIsNone(m.startup_duration_ms)

    def test_negative_clamped_to_zero(self):
        m = self._fresh()
        m.record_startup(-50.0)
        self.assertGreaterEqual(m.startup_duration_ms, 0.0)


# ---------------------------------------------------------------------------
# 2–4. record_heartbeat / heartbeat_loss_rate
# ---------------------------------------------------------------------------

class TestHeartbeat(unittest.TestCase):
    def _fresh(self):
        from core.slo_metrics import SLOMetrics
        return SLOMetrics(heartbeat_window=10)

    def test_all_success(self):
        m = self._fresh()
        for _ in range(5):
            m.record_heartbeat(True)
        self.assertAlmostEqual(m.heartbeat_loss_rate, 0.0)

    def test_all_failure(self):
        m = self._fresh()
        for _ in range(5):
            m.record_heartbeat(False)
        self.assertAlmostEqual(m.heartbeat_loss_rate, 1.0)

    def test_mixed(self):
        m = self._fresh()
        m.record_heartbeat(True)
        m.record_heartbeat(True)
        m.record_heartbeat(False)
        # 1 failure / 3 total
        self.assertAlmostEqual(m.heartbeat_loss_rate, 1 / 3)

    def test_no_data_returns_zero(self):
        m = self._fresh()
        self.assertAlmostEqual(m.heartbeat_loss_rate, 0.0)

    def test_cumulative_counters(self):
        m = self._fresh()
        for _ in range(4):
            m.record_heartbeat(True)
        m.record_heartbeat(False)
        snap = m.snapshot()
        self.assertEqual(snap["heartbeat"]["total"], 5)
        self.assertEqual(snap["heartbeat"]["failures"], 1)

    def test_rolling_window_evicts_old(self):
        """Window of 10; fill with failures then successes — rate must drop."""
        m = self._fresh()
        for _ in range(5):
            m.record_heartbeat(False)
        for _ in range(5):
            m.record_heartbeat(True)
        # window is 10; all 10 fit — 5 fail / 10 total
        self.assertAlmostEqual(m.heartbeat_loss_rate, 0.5)

        # Now add 10 more successes; old failures evicted (window=10)
        for _ in range(10):
            m.record_heartbeat(True)
        self.assertAlmostEqual(m.heartbeat_loss_rate, 0.0)


# ---------------------------------------------------------------------------
# 5. record_reconnect
# ---------------------------------------------------------------------------

class TestReconnect(unittest.TestCase):
    def _fresh(self):
        from core.slo_metrics import SLOMetrics
        return SLOMetrics()

    def test_starts_at_zero(self):
        m = self._fresh()
        self.assertEqual(m.reconnect_total, 0)

    def test_increments(self):
        m = self._fresh()
        m.record_reconnect("node_01")
        m.record_reconnect()
        self.assertEqual(m.reconnect_total, 2)


# ---------------------------------------------------------------------------
# 6–8. record_command_latency / percentiles
# ---------------------------------------------------------------------------

class TestCommandLatency(unittest.TestCase):
    def _fresh(self, window=100):
        from core.slo_metrics import SLOMetrics
        return SLOMetrics(latency_window=window)

    def test_no_samples_nan(self):
        m = self._fresh()
        self.assertTrue(math.isnan(m.command_latency_p50))
        self.assertTrue(math.isnan(m.command_latency_p95))

    def test_single_sample(self):
        m = self._fresh()
        m.record_command_latency(42.0)
        self.assertAlmostEqual(m.command_latency_p50, 42.0)
        self.assertAlmostEqual(m.command_latency_p95, 42.0)

    def test_percentiles_ordered(self):
        m = self._fresh()
        for v in range(1, 101):
            m.record_command_latency(float(v))
        # p50 ≈ 50, p95 ≈ 95
        self.assertLessEqual(m.command_latency_p50, m.command_latency_p95)
        self.assertGreater(m.command_latency_p50, 0)

    def test_rolling_window_evicts(self):
        m = self._fresh(window=5)
        for v in range(1, 6):
            m.record_command_latency(float(v))
        snap = m.snapshot()
        self.assertEqual(snap["command_latency"]["sample_count"], 5)
        # Add 5 more large values; small ones evicted
        for v in range(1000, 1005):
            m.record_command_latency(float(v))
        self.assertGreater(m.command_latency_p50, 100)


# ---------------------------------------------------------------------------
# 9. snapshot()
# ---------------------------------------------------------------------------

class TestSnapshot(unittest.TestCase):
    def test_snapshot_structure(self):
        from core.slo_metrics import SLOMetrics
        m = SLOMetrics()
        m.record_startup(500.0)
        m.record_heartbeat(True)
        m.record_heartbeat(False)
        m.record_reconnect()
        m.record_command_latency(100.0)
        m.record_command_latency(200.0)

        snap = m.snapshot()

        # Verify top-level keys
        self.assertIn("startup", snap)
        self.assertIn("heartbeat", snap)
        self.assertIn("reconnect", snap)
        self.assertIn("command_latency", snap)
        self.assertIn("control_loop", snap)

        # startup
        self.assertAlmostEqual(snap["startup"]["duration_ms"], 500.0)
        self.assertIsNotNone(snap["startup"]["recorded_at"])

        # heartbeat
        self.assertEqual(snap["heartbeat"]["total"], 2)
        self.assertEqual(snap["heartbeat"]["failures"], 1)
        self.assertAlmostEqual(snap["heartbeat"]["loss_rate"], 0.5)

        # reconnect
        self.assertEqual(snap["reconnect"]["attempts_total"], 1)

        # command_latency
        self.assertEqual(snap["command_latency"]["sample_count"], 2)
        self.assertIsNotNone(snap["command_latency"]["p50_ms"])
        self.assertIsNotNone(snap["command_latency"]["p95_ms"])
        self.assertIn("projection_stale_snapshot_rate", snap["control_loop"])

    def test_snapshot_null_when_no_data(self):
        from core.slo_metrics import SLOMetrics
        m = SLOMetrics()
        snap = m.snapshot()
        self.assertIsNone(snap["startup"]["duration_ms"])
        self.assertIsNone(snap["command_latency"]["p50_ms"])
        self.assertIsNone(snap["command_latency"]["p95_ms"])


# ---------------------------------------------------------------------------
# 10–11. prometheus_text()
# ---------------------------------------------------------------------------

class TestPrometheusText(unittest.TestCase):
    def _populated(self):
        from core.slo_metrics import SLOMetrics
        m = SLOMetrics()
        m.record_startup(1000.0)
        for _ in range(3):
            m.record_heartbeat(True)
        m.record_heartbeat(False)
        m.record_reconnect()
        m.record_command_latency(50.0)
        m.record_command_latency(150.0)
        return m

    def test_contains_expected_metric_names(self):
        text = self._populated().prometheus_text()
        expected = [
            "galaxy_slo_startup_duration_ms",
            "galaxy_slo_heartbeat_total",
            "galaxy_slo_heartbeat_failure_total",
            "galaxy_slo_heartbeat_loss_rate",
            "galaxy_slo_reconnect_attempts_total",
            "galaxy_slo_command_latency_p50_ms",
            "galaxy_slo_command_latency_p95_ms",
            "galaxy_slo_command_latency_sample_count",
            "galaxy_slo_projection_stale_snapshot_rate",
            "galaxy_slo_projection_window_samples_total",
        ]
        for name in expected:
            self.assertIn(name, text, f"Missing metric: {name}")

    def test_valid_prometheus_format(self):
        """Every metric must have a # HELP and # TYPE line."""
        text = self._populated().prometheus_text()
        lines = [l for l in text.splitlines() if l.strip()]
        help_names = {l.split()[2] for l in lines if l.startswith("# HELP ")}
        type_names = {l.split()[2] for l in lines if l.startswith("# TYPE ")}
        # Every HELP line should have a matching TYPE line
        self.assertEqual(help_names, type_names)

    def test_startup_value_present(self):
        text = self._populated().prometheus_text()
        # Check that the startup value line is present and has a numeric value
        for line in text.splitlines():
            if line.startswith("galaxy_slo_startup_duration_ms "):
                value_str = line.split()[-1]
                self.assertNotEqual(value_str, "")
                float(value_str)  # must be parseable
                break
        else:
            self.fail("galaxy_slo_startup_duration_ms value line not found")


# ---------------------------------------------------------------------------
# 12. Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety(unittest.TestCase):
    def test_concurrent_heartbeat_writes(self):
        from core.slo_metrics import SLOMetrics
        m = SLOMetrics()
        errors = []

        def _write(n):
            try:
                for _ in range(n):
                    m.record_heartbeat(True)
                    m.record_heartbeat(False)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write, args=(100,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        # 10 threads × 200 (100 true + 100 false) = 2000 total
        snap = m.snapshot()
        self.assertEqual(snap["heartbeat"]["total"], 2000)
        self.assertEqual(snap["heartbeat"]["failures"], 1000)

    def test_concurrent_latency_writes(self):
        from core.slo_metrics import SLOMetrics
        m = SLOMetrics(latency_window=10000)
        errors = []

        def _write():
            try:
                for i in range(200):
                    m.record_command_latency(float(i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        # p50/p95 should be computable without error
        p50 = m.command_latency_p50
        p95 = m.command_latency_p95
        self.assertFalse(math.isnan(p50))
        self.assertFalse(math.isnan(p95))


# ---------------------------------------------------------------------------
# 13. get_slo_metrics() singleton
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):
    def test_same_instance(self):
        from core.slo_metrics import get_slo_metrics, _slo_lock
        import core.slo_metrics as _mod
        # Reset singleton for isolation
        orig = _mod._slo_metrics
        _mod._slo_metrics = None
        try:
            a = get_slo_metrics()
            b = get_slo_metrics()
            self.assertIs(a, b)
        finally:
            _mod._slo_metrics = orig


# ---------------------------------------------------------------------------
# 14–15. HTTP endpoints (FastAPI TestClient)
# ---------------------------------------------------------------------------

class TestHttpEndpoints(unittest.TestCase):
    """Test the /metrics and /api/v1/slo/metrics endpoints via TestClient."""

    @classmethod
    def setUpClass(cls):
        """Build a minimal FastAPI app that only mounts the SLO endpoints."""
        try:
            from fastapi import FastAPI
            from fastapi.responses import PlainTextResponse
            from fastapi.testclient import TestClient

            app = FastAPI()

            from core.slo_metrics import get_slo_metrics

            @app.get("/metrics", response_class=PlainTextResponse)
            def metrics():
                return PlainTextResponse(
                    content=get_slo_metrics().prometheus_text(),
                    media_type="text/plain; version=0.0.4; charset=utf-8",
                )

            @app.get("/api/v1/slo/metrics")
            def slo_json():
                return get_slo_metrics().snapshot()

            cls.client = TestClient(app)
            cls.available = True
        except ImportError:
            cls.available = False

    def _skip_if_unavailable(self):
        if not self.available:
            self.skipTest("fastapi/httpx not installed")

    def test_prometheus_endpoint_200(self):
        self._skip_if_unavailable()
        resp = self.client.get("/metrics")
        self.assertEqual(resp.status_code, 200)

    def test_prometheus_endpoint_content_type(self):
        self._skip_if_unavailable()
        resp = self.client.get("/metrics")
        self.assertIn("text/plain", resp.headers.get("content-type", ""))

    def test_prometheus_endpoint_has_metric_name(self):
        self._skip_if_unavailable()
        resp = self.client.get("/metrics")
        self.assertIn("galaxy_slo_startup_duration_ms", resp.text)

    def test_json_endpoint_200(self):
        self._skip_if_unavailable()
        resp = self.client.get("/api/v1/slo/metrics")
        self.assertEqual(resp.status_code, 200)

    def test_json_endpoint_schema(self):
        self._skip_if_unavailable()
        resp = self.client.get("/api/v1/slo/metrics")
        data = resp.json()
        for key in ("startup", "heartbeat", "reconnect", "command_latency"):
            self.assertIn(key, data, f"Missing top-level key: {key}")

        hb = data["heartbeat"]
        self.assertIn("total", hb)
        self.assertIn("failures", hb)
        self.assertIn("loss_rate", hb)

        cl = data["command_latency"]
        self.assertIn("sample_count", cl)
        self.assertIn("p50_ms", cl)
        self.assertIn("p95_ms", cl)


if __name__ == "__main__":
    unittest.main()
