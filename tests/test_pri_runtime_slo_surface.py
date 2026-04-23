"""
tests/test_pri_runtime_slo_surface.py — PR-I Runtime Metrics and Operational SLO Surface
===========================================================================================

Tests for ``core/operational_slo_metrics.py``:

 1.  record_dispatch_attempt / record_dispatch_success / record_dispatch_failure
 2.  dispatch_success_rate / dispatch_failure_rate — correct fractions
 3.  dispatch_failure_reason_counts — bounded by failure_reasons_max
 4.  record_route_rejection — total and per-reason counts
 5.  route_rejection_reason_counts — bounded by rejection_reasons_max
 6.  record_fallback_triggered — total and per-kind counts
 7.  fallback_kind_counts — bounded by fallback_kinds_max
 8.  record_recovery_attempt / record_recovery_resumed / record_recovery_replayed /
     record_recovery_reissued / record_recovery_failed
 9.  recovery_success_rate — correct fraction
10.  recovery_failure_reason_counts — bounded by failure_reasons_max
11.  record_startup_recovery_scan — accumulates tasks_scanned and actions_taken
12.  record_audit_persist_success / record_audit_persist_failure
13.  audit_persist_failure_rate — correct fraction
14.  snapshot() — correct JSON structure, types, and value consistency
15.  prometheus_text() — contains expected metric names
16.  prometheus_text() — valid Prometheus exposition format (HELP/TYPE for every metric)
17.  OperationalSLOMetrics.reset() — all counters return to zero
18.  Thread safety — concurrent writes do not corrupt counters
19.  get_operational_slo_metrics() — returns the same singleton across calls
20.  reset_operational_slo_metrics() — replaces singleton after reset
21.  Sentinel strings — OPERATIONAL_SLO_METRICS_IS_AUTHORITY and
     OPERATIONAL_SLO_METRICS_PR_I_SENTINEL are non-empty and distinct
22.  Bounds enforcement — reason-string dicts do not exceed their max sizes
23.  /api/v1/slo/operational endpoint — returns 200 with valid JSON schema
24.  /api/v1/slo/metrics endpoint — returns 200 with valid JSON schema (PR-G2 parity)
25.  /metrics Prometheus endpoint includes operational SLO metric names (PR-I integration)
"""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# 1–3. Dispatch recording
# ---------------------------------------------------------------------------


class TestDispatchRecording(unittest.TestCase):
    def _fresh(self, **kw):
        from core.operational_slo_metrics import OperationalSLOMetrics
        return OperationalSLOMetrics(**kw)

    def test_attempts_accumulate(self):
        m = self._fresh()
        m.record_dispatch_attempt("t1", "dev_a")
        m.record_dispatch_attempt("t2", "dev_b")
        snap = m.snapshot()
        self.assertEqual(snap["dispatch"]["attempts_total"], 2)

    def test_successes_accumulate(self):
        m = self._fresh()
        m.record_dispatch_attempt()
        m.record_dispatch_success()
        snap = m.snapshot()
        self.assertEqual(snap["dispatch"]["successes_total"], 1)

    def test_failures_accumulate_with_reason(self):
        m = self._fresh()
        m.record_dispatch_attempt()
        m.record_dispatch_failure("t1", "no_route")
        m.record_dispatch_attempt()
        m.record_dispatch_failure("t2", "no_route")
        snap = m.snapshot()
        self.assertEqual(snap["dispatch"]["failures_total"], 2)
        self.assertEqual(snap["dispatch"]["failure_reason_counts"]["no_route"], 2)

    def test_success_rate_all_success(self):
        m = self._fresh()
        for _ in range(4):
            m.record_dispatch_attempt()
            m.record_dispatch_success()
        self.assertAlmostEqual(m.dispatch_success_rate, 1.0)

    def test_failure_rate_all_failure(self):
        m = self._fresh()
        for _ in range(3):
            m.record_dispatch_attempt()
            m.record_dispatch_failure(reason="timeout")
        self.assertAlmostEqual(m.dispatch_failure_rate, 1.0)

    def test_mixed_rates(self):
        m = self._fresh()
        m.record_dispatch_attempt()
        m.record_dispatch_success()
        m.record_dispatch_attempt()
        m.record_dispatch_failure(reason="no_route")
        self.assertAlmostEqual(m.dispatch_success_rate, 0.5)
        self.assertAlmostEqual(m.dispatch_failure_rate, 0.5)

    def test_rates_zero_when_no_attempts(self):
        m = self._fresh()
        self.assertAlmostEqual(m.dispatch_success_rate, 0.0)
        self.assertAlmostEqual(m.dispatch_failure_rate, 0.0)

    def test_failure_reason_bounded(self):
        m = self._fresh(failure_reasons_max=3)
        for i in range(10):
            m.record_dispatch_failure(reason=f"reason_{i}")
        snap = m.snapshot()
        self.assertLessEqual(len(snap["dispatch"]["failure_reason_counts"]), 3)


# ---------------------------------------------------------------------------
# 4–5. Route rejection recording
# ---------------------------------------------------------------------------


class TestRouteRejection(unittest.TestCase):
    def _fresh(self, **kw):
        from core.operational_slo_metrics import OperationalSLOMetrics
        return OperationalSLOMetrics(**kw)

    def test_total_accumulates(self):
        m = self._fresh()
        m.record_route_rejection("t1", "no_capable_device")
        m.record_route_rejection("t2", "policy_reject")
        snap = m.snapshot()
        self.assertEqual(snap["route_rejection"]["rejections_total"], 2)

    def test_per_reason_counts(self):
        m = self._fresh()
        m.record_route_rejection(reason="policy_reject")
        m.record_route_rejection(reason="policy_reject")
        m.record_route_rejection(reason="no_capable_device")
        counts = m.snapshot()["route_rejection"]["rejection_reason_counts"]
        self.assertEqual(counts["policy_reject"], 2)
        self.assertEqual(counts["no_capable_device"], 1)

    def test_no_reason_does_not_add_to_counts(self):
        m = self._fresh()
        m.record_route_rejection(reason="")
        snap = m.snapshot()
        self.assertEqual(snap["route_rejection"]["rejections_total"], 1)
        self.assertEqual(snap["route_rejection"]["rejection_reason_counts"], {})

    def test_reason_bounded(self):
        m = self._fresh(rejection_reasons_max=2)
        for i in range(10):
            m.record_route_rejection(reason=f"reason_{i}")
        snap = m.snapshot()
        self.assertLessEqual(len(snap["route_rejection"]["rejection_reason_counts"]), 2)


# ---------------------------------------------------------------------------
# 6–7. Fallback recording
# ---------------------------------------------------------------------------


class TestFallbackRecording(unittest.TestCase):
    def _fresh(self, **kw):
        from core.operational_slo_metrics import OperationalSLOMetrics
        return OperationalSLOMetrics(**kw)

    def test_total_accumulates(self):
        m = self._fresh()
        m.record_fallback_triggered(fallback_kind="provider_unavailable")
        m.record_fallback_triggered(fallback_kind="router_error")
        snap = m.snapshot()
        self.assertEqual(snap["fallback"]["triggers_total"], 2)

    def test_per_kind_counts(self):
        m = self._fresh()
        m.record_fallback_triggered(fallback_kind="provider_unavailable")
        m.record_fallback_triggered(fallback_kind="provider_unavailable")
        m.record_fallback_triggered(fallback_kind="router_error")
        counts = m.snapshot()["fallback"]["fallback_kind_counts"]
        self.assertEqual(counts["provider_unavailable"], 2)
        self.assertEqual(counts["router_error"], 1)

    def test_no_kind_uses_other(self):
        m = self._fresh()
        m.record_fallback_triggered()
        snap = m.snapshot()
        self.assertEqual(snap["fallback"]["triggers_total"], 1)
        self.assertEqual(snap["fallback"]["fallback_kind_counts"]["other"], 1)

    def test_kind_bounded(self):
        m = self._fresh(fallback_kinds_max=2)
        for i in range(10):
            m.record_fallback_triggered(fallback_kind=f"kind_{i}")
        snap = m.snapshot()
        self.assertLessEqual(len(snap["fallback"]["fallback_kind_counts"]), 2)


# ---------------------------------------------------------------------------
# 8–10. Recovery recording
# ---------------------------------------------------------------------------


class TestRecoveryRecording(unittest.TestCase):
    def _fresh(self, **kw):
        from core.operational_slo_metrics import OperationalSLOMetrics
        return OperationalSLOMetrics(**kw)

    def test_attempts_accumulate(self):
        m = self._fresh()
        m.record_recovery_attempt()
        m.record_recovery_attempt()
        snap = m.snapshot()
        self.assertEqual(snap["recovery"]["attempts_total"], 2)

    def test_resumed_accumulates(self):
        m = self._fresh()
        m.record_recovery_attempt()
        m.record_recovery_resumed()
        snap = m.snapshot()
        self.assertEqual(snap["recovery"]["resumed_total"], 1)

    def test_replayed_accumulates(self):
        m = self._fresh()
        m.record_recovery_attempt()
        m.record_recovery_replayed()
        snap = m.snapshot()
        self.assertEqual(snap["recovery"]["replayed_total"], 1)

    def test_reissued_accumulates(self):
        m = self._fresh()
        m.record_recovery_attempt()
        m.record_recovery_reissued()
        snap = m.snapshot()
        self.assertEqual(snap["recovery"]["reissued_total"], 1)

    def test_failed_accumulates_with_reason(self):
        m = self._fresh()
        m.record_recovery_attempt()
        m.record_recovery_failed(reason="store_unavailable")
        snap = m.snapshot()
        self.assertEqual(snap["recovery"]["failed_total"], 1)
        self.assertEqual(snap["recovery"]["failure_reason_counts"]["store_unavailable"], 1)

    def test_success_rate_all_resumed(self):
        m = self._fresh()
        for _ in range(4):
            m.record_recovery_attempt()
            m.record_recovery_resumed()
        self.assertAlmostEqual(m.recovery_success_rate, 1.0)

    def test_success_rate_mixed(self):
        m = self._fresh()
        m.record_recovery_attempt()
        m.record_recovery_resumed()
        m.record_recovery_attempt()
        m.record_recovery_replayed()
        m.record_recovery_attempt()
        m.record_recovery_failed()
        self.assertAlmostEqual(m.recovery_success_rate, 2 / 3)

    def test_success_rate_zero_no_attempts(self):
        m = self._fresh()
        self.assertAlmostEqual(m.recovery_success_rate, 0.0)

    def test_recovery_failure_reason_bounded(self):
        m = self._fresh(failure_reasons_max=2)
        for i in range(10):
            m.record_recovery_failed(reason=f"r_{i}")
        snap = m.snapshot()
        self.assertLessEqual(len(snap["recovery"]["failure_reason_counts"]), 2)


# ---------------------------------------------------------------------------
# 11. Startup recovery scan recording
# ---------------------------------------------------------------------------


class TestStartupRecoveryScan(unittest.TestCase):
    def _fresh(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        return OperationalSLOMetrics()

    def test_starts_at_zero(self):
        m = self._fresh()
        snap = m.snapshot()
        self.assertEqual(snap["startup_recovery"]["tasks_scanned_total"], 0)
        self.assertEqual(snap["startup_recovery"]["actions_taken_total"], 0)

    def test_accumulates(self):
        m = self._fresh()
        m.record_startup_recovery_scan(tasks_scanned=10, actions_taken=7)
        snap = m.snapshot()
        self.assertEqual(snap["startup_recovery"]["tasks_scanned_total"], 10)
        self.assertEqual(snap["startup_recovery"]["actions_taken_total"], 7)

    def test_multiple_calls_accumulate(self):
        m = self._fresh()
        m.record_startup_recovery_scan(tasks_scanned=5, actions_taken=3)
        m.record_startup_recovery_scan(tasks_scanned=2, actions_taken=1)
        snap = m.snapshot()
        self.assertEqual(snap["startup_recovery"]["tasks_scanned_total"], 7)
        self.assertEqual(snap["startup_recovery"]["actions_taken_total"], 4)

    def test_negative_clamped_to_zero(self):
        m = self._fresh()
        m.record_startup_recovery_scan(tasks_scanned=-5, actions_taken=-3)
        snap = m.snapshot()
        self.assertEqual(snap["startup_recovery"]["tasks_scanned_total"], 0)
        self.assertEqual(snap["startup_recovery"]["actions_taken_total"], 0)


# ---------------------------------------------------------------------------
# 12–13. Audit persistence recording
# ---------------------------------------------------------------------------


class TestAuditPersistence(unittest.TestCase):
    def _fresh(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        return OperationalSLOMetrics()

    def test_successes_accumulate(self):
        m = self._fresh()
        m.record_audit_persist_success()
        m.record_audit_persist_success()
        snap = m.snapshot()
        self.assertEqual(snap["audit_persistence"]["persist_successes_total"], 2)

    def test_failures_accumulate_with_reason(self):
        m = self._fresh()
        m.record_audit_persist_failure(reason="io_error")
        m.record_audit_persist_failure(reason="io_error")
        snap = m.snapshot()
        self.assertEqual(snap["audit_persistence"]["persist_failures_total"], 2)
        self.assertEqual(
            snap["audit_persistence"]["persist_failure_reason_counts"]["io_error"], 2
        )

    def test_failure_rate_all_failure(self):
        m = self._fresh()
        m.record_audit_persist_failure(reason="io_error")
        self.assertAlmostEqual(m.audit_persist_failure_rate, 1.0)

    def test_failure_rate_mixed(self):
        m = self._fresh()
        m.record_audit_persist_success()
        m.record_audit_persist_success()
        m.record_audit_persist_success()
        m.record_audit_persist_failure(reason="io_error")
        self.assertAlmostEqual(m.audit_persist_failure_rate, 0.25)

    def test_failure_rate_zero_no_operations(self):
        m = self._fresh()
        self.assertAlmostEqual(m.audit_persist_failure_rate, 0.0)

    def test_failure_reason_bounded(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics(audit_failure_reasons_max=2)
        for i in range(10):
            m.record_audit_persist_failure(reason=f"reason_{i}")
        snap = m.snapshot()
        self.assertLessEqual(
            len(snap["audit_persistence"]["persist_failure_reason_counts"]), 2
        )


# ---------------------------------------------------------------------------
# 14. snapshot() structure
# ---------------------------------------------------------------------------


class TestSnapshot(unittest.TestCase):
    def _populated(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics()
        m.record_dispatch_attempt()
        m.record_dispatch_success()
        m.record_dispatch_attempt()
        m.record_dispatch_failure(reason="timeout")
        m.record_route_rejection(reason="no_capable_device")
        m.record_fallback_triggered(fallback_kind="provider_unavailable")
        m.record_recovery_attempt()
        m.record_recovery_resumed()
        m.record_recovery_attempt()
        m.record_recovery_failed(reason="store_unavailable")
        m.record_startup_recovery_scan(tasks_scanned=5, actions_taken=3)
        m.record_audit_persist_success()
        m.record_audit_persist_failure(reason="io_error")
        return m

    def test_top_level_keys(self):
        snap = self._populated().snapshot()
        for key in (
            "schema_version",
            "snapshotted_at",
            "dispatch",
            "route_rejection",
            "fallback",
            "recovery",
            "startup_recovery",
            "audit_persistence",
        ):
            self.assertIn(key, snap, f"Missing top-level key: {key}")

    def test_schema_version_is_1(self):
        snap = self._populated().snapshot()
        self.assertEqual(snap["schema_version"], 1)

    def test_dispatch_keys(self):
        snap = self._populated().snapshot()
        d = snap["dispatch"]
        for key in (
            "attempts_total",
            "successes_total",
            "failures_total",
            "success_rate",
            "failure_rate",
            "failure_reason_counts",
        ):
            self.assertIn(key, d, f"Missing dispatch key: {key}")

    def test_dispatch_values(self):
        snap = self._populated().snapshot()
        d = snap["dispatch"]
        self.assertEqual(d["attempts_total"], 2)
        self.assertEqual(d["successes_total"], 1)
        self.assertEqual(d["failures_total"], 1)
        self.assertAlmostEqual(d["success_rate"], 0.5)
        self.assertAlmostEqual(d["failure_rate"], 0.5)
        self.assertEqual(d["failure_reason_counts"]["timeout"], 1)

    def test_route_rejection_keys(self):
        snap = self._populated().snapshot()
        r = snap["route_rejection"]
        self.assertIn("rejections_total", r)
        self.assertIn("rejection_reason_counts", r)

    def test_fallback_keys(self):
        snap = self._populated().snapshot()
        fb = snap["fallback"]
        self.assertIn("triggers_total", fb)
        self.assertIn("fallback_kind_counts", fb)

    def test_recovery_keys(self):
        snap = self._populated().snapshot()
        rec = snap["recovery"]
        for key in (
            "attempts_total",
            "resumed_total",
            "replayed_total",
            "reissued_total",
            "failed_total",
            "success_rate",
            "failure_reason_counts",
        ):
            self.assertIn(key, rec, f"Missing recovery key: {key}")

    def test_startup_recovery_keys(self):
        snap = self._populated().snapshot()
        sr = snap["startup_recovery"]
        self.assertIn("tasks_scanned_total", sr)
        self.assertIn("actions_taken_total", sr)

    def test_audit_persistence_keys(self):
        snap = self._populated().snapshot()
        ap = snap["audit_persistence"]
        for key in (
            "persist_successes_total",
            "persist_failures_total",
            "persist_failure_rate",
            "persist_failure_reason_counts",
        ):
            self.assertIn(key, ap, f"Missing audit_persistence key: {key}")

    def test_empty_snapshot_all_zero(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        snap = OperationalSLOMetrics().snapshot()
        self.assertEqual(snap["dispatch"]["attempts_total"], 0)
        self.assertEqual(snap["dispatch"]["successes_total"], 0)
        self.assertEqual(snap["dispatch"]["failures_total"], 0)
        self.assertEqual(snap["route_rejection"]["rejections_total"], 0)
        self.assertEqual(snap["fallback"]["triggers_total"], 0)
        self.assertEqual(snap["recovery"]["attempts_total"], 0)
        self.assertEqual(snap["startup_recovery"]["tasks_scanned_total"], 0)
        self.assertEqual(snap["audit_persistence"]["persist_successes_total"], 0)


# ---------------------------------------------------------------------------
# 15–16. prometheus_text()
# ---------------------------------------------------------------------------


class TestPrometheusText(unittest.TestCase):
    def _populated(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics()
        m.record_dispatch_attempt()
        m.record_dispatch_success()
        m.record_fallback_triggered(fallback_kind="provider_unavailable")
        m.record_recovery_attempt()
        m.record_recovery_resumed()
        m.record_audit_persist_success()
        m.record_audit_persist_failure(reason="io_error")
        return m

    def test_contains_expected_metric_names(self):
        text = self._populated().prometheus_text()
        expected = [
            "galaxy_ops_dispatch_attempts_total",
            "galaxy_ops_dispatch_successes_total",
            "galaxy_ops_dispatch_failures_total",
            "galaxy_ops_dispatch_success_rate",
            "galaxy_ops_dispatch_failure_rate",
            "galaxy_ops_route_rejections_total",
            "galaxy_ops_fallback_triggers_total",
            "galaxy_ops_recovery_attempts_total",
            "galaxy_ops_recovery_resumed_total",
            "galaxy_ops_recovery_replayed_total",
            "galaxy_ops_recovery_reissued_total",
            "galaxy_ops_recovery_failed_total",
            "galaxy_ops_recovery_success_rate",
            "galaxy_ops_startup_recovery_tasks_scanned_total",
            "galaxy_ops_startup_recovery_actions_taken_total",
            "galaxy_ops_audit_persist_successes_total",
            "galaxy_ops_audit_persist_failures_total",
            "galaxy_ops_audit_persist_failure_rate",
        ]
        for name in expected:
            self.assertIn(name, text, f"Missing metric in prometheus_text: {name}")

    def test_valid_prometheus_format(self):
        """Every metric must have matching # HELP and # TYPE lines."""
        text = self._populated().prometheus_text()
        lines = [line for line in text.splitlines() if line.strip()]
        help_names = {line.split()[2] for line in lines if line.startswith("# HELP ")}
        type_names = {line.split()[2] for line in lines if line.startswith("# TYPE ")}
        self.assertEqual(
            help_names,
            type_names,
            "Every # HELP line must have a matching # TYPE line and vice versa",
        )

    def test_value_lines_are_numeric(self):
        """Every value line (not # HELP / # TYPE) must end with a parseable number."""
        text = self._populated().prometheus_text()
        for line in text.splitlines():
            if line.strip() and not line.startswith("#"):
                parts = line.rsplit(" ", 1)
                self.assertEqual(len(parts), 2, f"Unexpected value line format: {line!r}")
                try:
                    float(parts[1])
                except ValueError:
                    self.fail(f"Non-numeric value in line: {line!r}")

    def test_text_ends_with_newline(self):
        text = self._populated().prometheus_text()
        self.assertTrue(text.endswith("\n"), "prometheus_text() must end with a newline")


# ---------------------------------------------------------------------------
# 17. reset()
# ---------------------------------------------------------------------------


class TestReset(unittest.TestCase):
    def test_reset_clears_all_counters(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics()
        m.record_dispatch_attempt()
        m.record_dispatch_success()
        m.record_route_rejection(reason="policy_reject")
        m.record_fallback_triggered(fallback_kind="provider_unavailable")
        m.record_recovery_attempt()
        m.record_recovery_resumed()
        m.record_startup_recovery_scan(tasks_scanned=5, actions_taken=3)
        m.record_audit_persist_success()
        m.record_audit_persist_failure(reason="io_error")

        m.reset()
        snap = m.snapshot()

        self.assertEqual(snap["dispatch"]["attempts_total"], 0)
        self.assertEqual(snap["dispatch"]["successes_total"], 0)
        self.assertEqual(snap["dispatch"]["failures_total"], 0)
        self.assertEqual(snap["dispatch"]["failure_reason_counts"], {})
        self.assertEqual(snap["route_rejection"]["rejections_total"], 0)
        self.assertEqual(snap["route_rejection"]["rejection_reason_counts"], {})
        self.assertEqual(snap["fallback"]["triggers_total"], 0)
        self.assertEqual(snap["fallback"]["fallback_kind_counts"], {})
        self.assertEqual(snap["recovery"]["attempts_total"], 0)
        self.assertEqual(snap["recovery"]["resumed_total"], 0)
        self.assertEqual(snap["recovery"]["replayed_total"], 0)
        self.assertEqual(snap["recovery"]["reissued_total"], 0)
        self.assertEqual(snap["recovery"]["failed_total"], 0)
        self.assertEqual(snap["recovery"]["failure_reason_counts"], {})
        self.assertEqual(snap["startup_recovery"]["tasks_scanned_total"], 0)
        self.assertEqual(snap["startup_recovery"]["actions_taken_total"], 0)
        self.assertEqual(snap["audit_persistence"]["persist_successes_total"], 0)
        self.assertEqual(snap["audit_persistence"]["persist_failures_total"], 0)
        self.assertEqual(snap["audit_persistence"]["persist_failure_reason_counts"], {})


# ---------------------------------------------------------------------------
# 18. Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_dispatch_writes(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics()
        errors = []

        def _write(n):
            try:
                for _ in range(n):
                    m.record_dispatch_attempt()
                    m.record_dispatch_success()
                    m.record_dispatch_attempt()
                    m.record_dispatch_failure(reason="err")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(50,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        snap = m.snapshot()
        # 10 threads × 100 attempts = 1000
        self.assertEqual(snap["dispatch"]["attempts_total"], 1000)
        # 10 threads × 50 successes = 500
        self.assertEqual(snap["dispatch"]["successes_total"], 500)
        # 10 threads × 50 failures = 500
        self.assertEqual(snap["dispatch"]["failures_total"], 500)

    def test_concurrent_recovery_writes(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics()
        errors = []

        def _write():
            try:
                for _ in range(100):
                    m.record_recovery_attempt()
                    m.record_recovery_resumed()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_write) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        snap = m.snapshot()
        self.assertEqual(snap["recovery"]["attempts_total"], 1000)
        self.assertEqual(snap["recovery"]["resumed_total"], 1000)

    def test_concurrent_audit_writes(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics()
        errors = []

        def _write():
            try:
                for _ in range(50):
                    m.record_audit_persist_success()
                    m.record_audit_persist_failure(reason="err")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_write) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        snap = m.snapshot()
        self.assertEqual(snap["audit_persistence"]["persist_successes_total"], 500)
        self.assertEqual(snap["audit_persistence"]["persist_failures_total"], 500)


# ---------------------------------------------------------------------------
# 19–20. Singleton management
# ---------------------------------------------------------------------------


class TestSingleton(unittest.TestCase):
    def test_same_instance_across_calls(self):
        import core.operational_slo_metrics as _mod
        from core.operational_slo_metrics import get_operational_slo_metrics
        orig = _mod._ops_metrics
        _mod._ops_metrics = None
        try:
            a = get_operational_slo_metrics()
            b = get_operational_slo_metrics()
            self.assertIs(a, b)
        finally:
            _mod._ops_metrics = orig

    def test_reset_creates_fresh_singleton(self):
        import core.operational_slo_metrics as _mod
        from core.operational_slo_metrics import (
            get_operational_slo_metrics,
            reset_operational_slo_metrics,
        )
        orig = _mod._ops_metrics
        try:
            _mod._ops_metrics = None
            a = get_operational_slo_metrics()
            a.record_dispatch_attempt()
            reset_operational_slo_metrics()
            b = get_operational_slo_metrics()
            # After reset, singleton is None until next access; b must be a new instance
            self.assertIsNot(a, b)
            snap = b.snapshot()
            self.assertEqual(snap["dispatch"]["attempts_total"], 0)
        finally:
            _mod._ops_metrics = orig


# ---------------------------------------------------------------------------
# 21. Sentinel strings
# ---------------------------------------------------------------------------


class TestSentinels(unittest.TestCase):
    def test_authority_sentinel_present(self):
        from core.operational_slo_metrics import OPERATIONAL_SLO_METRICS_IS_AUTHORITY
        self.assertIsInstance(OPERATIONAL_SLO_METRICS_IS_AUTHORITY, str)
        self.assertGreater(len(OPERATIONAL_SLO_METRICS_IS_AUTHORITY), 0)

    def test_pr_i_sentinel_present(self):
        from core.operational_slo_metrics import OPERATIONAL_SLO_METRICS_PR_I_SENTINEL
        self.assertIsInstance(OPERATIONAL_SLO_METRICS_PR_I_SENTINEL, str)
        self.assertGreater(len(OPERATIONAL_SLO_METRICS_PR_I_SENTINEL), 0)

    def test_sentinels_are_distinct(self):
        from core.operational_slo_metrics import (
            OPERATIONAL_SLO_METRICS_IS_AUTHORITY,
            OPERATIONAL_SLO_METRICS_PR_I_SENTINEL,
        )
        self.assertNotEqual(
            OPERATIONAL_SLO_METRICS_IS_AUTHORITY,
            OPERATIONAL_SLO_METRICS_PR_I_SENTINEL,
        )

    def test_sentinels_in_all(self):
        import core.operational_slo_metrics as _mod
        self.assertIn("OPERATIONAL_SLO_METRICS_IS_AUTHORITY", _mod.__all__)
        self.assertIn("OPERATIONAL_SLO_METRICS_PR_I_SENTINEL", _mod.__all__)


# ---------------------------------------------------------------------------
# 22. Bounds enforcement
# ---------------------------------------------------------------------------


class TestBoundsEnforcement(unittest.TestCase):
    def test_rejection_reasons_not_exceeded(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics(rejection_reasons_max=5)
        for i in range(20):
            m.record_route_rejection(reason=f"r{i}")
        snap = m.snapshot()
        self.assertLessEqual(len(snap["route_rejection"]["rejection_reason_counts"]), 5)

    def test_fallback_kinds_not_exceeded(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics(fallback_kinds_max=3)
        for i in range(15):
            m.record_fallback_triggered(fallback_kind=f"kind_{i}")
        snap = m.snapshot()
        self.assertLessEqual(len(snap["fallback"]["fallback_kind_counts"]), 3)

    def test_dispatch_failure_reasons_not_exceeded(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics(failure_reasons_max=4)
        for i in range(20):
            m.record_dispatch_failure(reason=f"r{i}")
        snap = m.snapshot()
        self.assertLessEqual(len(snap["dispatch"]["failure_reason_counts"]), 4)

    def test_audit_failure_reasons_not_exceeded(self):
        from core.operational_slo_metrics import OperationalSLOMetrics
        m = OperationalSLOMetrics(audit_failure_reasons_max=3)
        for i in range(15):
            m.record_audit_persist_failure(reason=f"r{i}")
        snap = m.snapshot()
        self.assertLessEqual(
            len(snap["audit_persistence"]["persist_failure_reason_counts"]), 3
        )


# ---------------------------------------------------------------------------
# 23–25. HTTP endpoints
# ---------------------------------------------------------------------------


class TestHttpEndpoints(unittest.TestCase):
    """Test /api/v1/slo/operational, /api/v1/slo/metrics, and /metrics endpoints."""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi import FastAPI
            from fastapi.responses import PlainTextResponse
            from fastapi.testclient import TestClient

            app = FastAPI()

            from core.operational_slo_metrics import get_operational_slo_metrics
            from core.slo_metrics import get_slo_metrics

            @app.get("/api/v1/slo/operational")
            def operational_slo():
                return get_operational_slo_metrics().snapshot()

            @app.get("/api/v1/slo/metrics")
            def slo_metrics():
                return get_slo_metrics().snapshot()

            @app.get("/metrics", response_class=PlainTextResponse)
            def prometheus_all():
                parts = []
                parts.append(get_slo_metrics().prometheus_text())
                parts.append(get_operational_slo_metrics().prometheus_text())
                return PlainTextResponse(
                    content="".join(parts),
                    media_type="text/plain; version=0.0.4; charset=utf-8",
                )

            cls.client = TestClient(app)
            cls.available = True
        except ImportError:
            cls.available = False

    def _skip_if_unavailable(self):
        if not self.available:
            self.skipTest("fastapi/httpx not installed")

    # /api/v1/slo/operational
    def test_operational_endpoint_200(self):
        self._skip_if_unavailable()
        resp = self.client.get("/api/v1/slo/operational")
        self.assertEqual(resp.status_code, 200)

    def test_operational_endpoint_schema(self):
        self._skip_if_unavailable()
        data = self.client.get("/api/v1/slo/operational").json()
        for key in (
            "schema_version",
            "dispatch",
            "route_rejection",
            "fallback",
            "recovery",
            "startup_recovery",
            "audit_persistence",
        ):
            self.assertIn(key, data, f"Missing key in /api/v1/slo/operational: {key}")

    def test_operational_dispatch_sub_keys(self):
        self._skip_if_unavailable()
        data = self.client.get("/api/v1/slo/operational").json()
        d = data["dispatch"]
        for key in ("attempts_total", "successes_total", "failures_total",
                    "success_rate", "failure_rate", "failure_reason_counts"):
            self.assertIn(key, d)

    def test_operational_recovery_sub_keys(self):
        self._skip_if_unavailable()
        data = self.client.get("/api/v1/slo/operational").json()
        rec = data["recovery"]
        for key in ("attempts_total", "resumed_total", "replayed_total",
                    "reissued_total", "failed_total", "success_rate"):
            self.assertIn(key, rec)

    def test_operational_audit_sub_keys(self):
        self._skip_if_unavailable()
        data = self.client.get("/api/v1/slo/operational").json()
        ap = data["audit_persistence"]
        for key in ("persist_successes_total", "persist_failures_total",
                    "persist_failure_rate", "persist_failure_reason_counts"):
            self.assertIn(key, ap)

    # /api/v1/slo/metrics (PR-G2 parity)
    def test_slo_metrics_endpoint_200(self):
        self._skip_if_unavailable()
        resp = self.client.get("/api/v1/slo/metrics")
        self.assertEqual(resp.status_code, 200)

    def test_slo_metrics_endpoint_schema(self):
        self._skip_if_unavailable()
        data = self.client.get("/api/v1/slo/metrics").json()
        for key in ("startup", "heartbeat", "reconnect", "command_latency"):
            self.assertIn(key, data, f"Missing key in /api/v1/slo/metrics: {key}")

    # /metrics (combined Prometheus endpoint)
    def test_prometheus_endpoint_200(self):
        self._skip_if_unavailable()
        resp = self.client.get("/metrics")
        self.assertEqual(resp.status_code, 200)

    def test_prometheus_endpoint_content_type(self):
        self._skip_if_unavailable()
        resp = self.client.get("/metrics")
        self.assertIn("text/plain", resp.headers.get("content-type", ""))

    def test_prometheus_endpoint_has_slo_metric(self):
        self._skip_if_unavailable()
        text = self.client.get("/metrics").text
        self.assertIn("galaxy_slo_startup_duration_ms", text)

    def test_prometheus_endpoint_has_operational_metric(self):
        self._skip_if_unavailable()
        text = self.client.get("/metrics").text
        self.assertIn("galaxy_ops_dispatch_attempts_total", text)

    def test_prometheus_endpoint_has_recovery_metric(self):
        self._skip_if_unavailable()
        text = self.client.get("/metrics").text
        self.assertIn("galaxy_ops_recovery_attempts_total", text)

    def test_prometheus_endpoint_has_audit_metric(self):
        self._skip_if_unavailable()
        text = self.client.get("/metrics").text
        self.assertIn("galaxy_ops_audit_persist_successes_total", text)


if __name__ == "__main__":
    unittest.main()
