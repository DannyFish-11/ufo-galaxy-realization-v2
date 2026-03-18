"""
tests/test_continuum_observability.py
======================================

Tests for PR-6 continuum observability features:
- Structured logging (debug_continuum / flags.debug)
- Per-component feature flags
- ContinuumMetrics counters and latency tracking

Test groups
-----------
A) ContinuumMetrics — counters and latency tracking.
B) Structured logging — debug flag emits expected log records.
C) Per-component feature flags — each flag disables its stage gracefully.
D) Extra-flags pass-through from config dict into FeatureFlags.
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from unittest.mock import patch

import pytest

from core.continuum.config import ContinuumConfig, FeatureFlags, DEFAULT_CONTINUUM_CONFIG
from core.continuum.metrics import ContinuumMetrics, get_continuum_metrics
from core.continuum.orchestrator import ContinuumOrchestrator
from core.continuum.types import (
    ActionLevel,
    ContinuumPhase,
    ContinuumState,
    DecisionState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**flag_kwargs) -> ContinuumConfig:
    return ContinuumConfig(flags=FeatureFlags(**flag_kwargs))


# ---------------------------------------------------------------------------
# A) ContinuumMetrics — basic counter / latency API
# ---------------------------------------------------------------------------


class TestContinuumMetrics:
    def setup_method(self):
        self.m = ContinuumMetrics()

    def test_initial_snapshot_zeros(self):
        snap = self.m.snapshot()
        assert snap["ticks_total"] == 0
        assert snap["ticks_degraded"] == 0
        assert snap["ticks_skipped"] == 0
        assert snap["ticks_budget_exceeded"] == 0
        for phase in ("formless", "liminal", "manifest", "receding"):
            assert snap["phases"][phase] == 0

    def test_record_tick_increments_total(self):
        self.m.record_tick(phase="liminal", elapsed_ms=10.0)
        snap = self.m.snapshot()
        assert snap["ticks_total"] == 1
        assert snap["phases"]["liminal"] == 1

    def test_record_tick_degraded(self):
        self.m.record_tick(phase="formless", elapsed_ms=5.0, degraded=True)
        snap = self.m.snapshot()
        assert snap["ticks_degraded"] == 1

    def test_record_tick_skipped_does_not_count_phase(self):
        self.m.record_tick(phase="liminal", elapsed_ms=0.0, skipped=True)
        snap = self.m.snapshot()
        assert snap["ticks_total"] == 1
        assert snap["ticks_skipped"] == 1
        # Skipped ticks don't update phase counters
        assert snap["phases"]["liminal"] == 0

    def test_record_tick_budget_exceeded(self):
        self.m.record_tick(phase="formless", elapsed_ms=200.0, degraded=True, budget_exceeded=True)
        snap = self.m.snapshot()
        assert snap["ticks_budget_exceeded"] == 1

    def test_record_stage_latency(self):
        self.m.record_stage("human_field", 3.5)
        snap = self.m.snapshot()
        assert snap["stage_latency"]["human_field"]["count"] == 1
        assert snap["stage_latency"]["human_field"]["sum_ms"] == pytest.approx(3.5, abs=0.01)

    def test_record_stage_skipped_not_counted(self):
        self.m.record_stage("decision_gate", 10.0, skipped=True)
        snap = self.m.snapshot()
        assert snap["stage_latency"]["decision_gate"]["count"] == 0

    def test_record_stage_unknown_name_does_not_raise(self):
        # Unknown stage names should be silently ignored
        self.m.record_stage("nonexistent_stage", 5.0)

    def test_latency_avg_computed(self):
        self.m.record_tick(phase="formless", elapsed_ms=10.0)
        self.m.record_tick(phase="formless", elapsed_ms=20.0)
        snap = self.m.snapshot()
        assert snap["tick_latency"]["avg_ms"] == pytest.approx(15.0, abs=0.1)

    def test_reset_zeros_all(self):
        self.m.record_tick(phase="manifest", elapsed_ms=50.0)
        self.m.reset()
        snap = self.m.snapshot()
        assert snap["ticks_total"] == 0
        assert snap["tick_latency"]["count"] == 0

    def test_get_continuum_metrics_singleton(self):
        m1 = get_continuum_metrics()
        m2 = get_continuum_metrics()
        assert m1 is m2


# ---------------------------------------------------------------------------
# B) Structured logging — debug flag
# ---------------------------------------------------------------------------


class TestStructuredLogging:
    def setup_method(self):
        # Use a fresh metrics instance per test to avoid cross-contamination
        self._metrics_patch = patch(
            "core.continuum.orchestrator.get_continuum_metrics",
            return_value=ContinuumMetrics(),
        )
        self._metrics_patch.start()

    def teardown_method(self):
        self._metrics_patch.stop()

    def test_debug_flag_emits_tick_log(self, caplog):
        cfg = _make_cfg(debug=True)
        orch = ContinuumOrchestrator(config=cfg)
        with caplog.at_level(logging.DEBUG, logger="Galaxy.Continuum.Orchestrator"):
            orch.run(trace_id="log-test-1")
        tick_records = [r for r in caplog.records if "Continuum tick" in r.message]
        assert len(tick_records) >= 1

    def test_debug_flag_off_no_tick_log(self, caplog):
        cfg = _make_cfg(debug=False)
        orch = ContinuumOrchestrator(config=cfg)
        with caplog.at_level(logging.DEBUG, logger="Galaxy.Continuum.Orchestrator"):
            orch.run(trace_id="log-test-2")
        tick_records = [r for r in caplog.records if "Continuum tick |" in r.message]
        assert len(tick_records) == 0

    def test_debug_tick_log_contains_trace_id(self, caplog):
        cfg = _make_cfg(debug=True)
        orch = ContinuumOrchestrator(config=cfg)
        with caplog.at_level(logging.DEBUG, logger="Galaxy.Continuum.Orchestrator"):
            orch.run(trace_id="unique-trace-xyz")
        assert any("unique-trace-xyz" in r.message for r in caplog.records)

    def test_debug_stage_logs_emitted(self, caplog):
        cfg = _make_cfg(debug=True)
        orch = ContinuumOrchestrator(config=cfg)
        with caplog.at_level(logging.DEBUG, logger="Galaxy.Continuum.Orchestrator"):
            orch.run(trace_id="stage-log-test")
        stage_msgs = [r.message for r in caplog.records if "Continuum stage" in r.message]
        # We expect at least the perception and human_field stage logs
        assert len(stage_msgs) >= 2

    def test_disabled_continuum_emits_no_logs(self, caplog):
        cfg = _make_cfg(enabled=False, debug=True)
        orch = ContinuumOrchestrator(config=cfg)
        with caplog.at_level(logging.DEBUG, logger="Galaxy.Continuum.Orchestrator"):
            result = orch.run(trace_id="disabled-log")
        assert result.phase == ContinuumPhase.FORMLESS
        assert len(caplog.records) == 0


# ---------------------------------------------------------------------------
# C) Per-component feature flags
# ---------------------------------------------------------------------------


class TestPerComponentFlags:
    def setup_method(self):
        self._metrics_patch = patch(
            "core.continuum.orchestrator.get_continuum_metrics",
            return_value=ContinuumMetrics(),
        )
        self._metrics_patch.start()

    def teardown_method(self):
        self._metrics_patch.stop()

    def test_enable_perception_false_still_returns_state(self):
        cfg = _make_cfg(enable_perception=False)
        orch = ContinuumOrchestrator(config=cfg)
        result = orch.run(trace_id="no-perception")
        assert isinstance(result, ContinuumState)
        assert result.phase in ContinuumPhase.__members__.values()

    def test_enable_human_field_false_returns_state(self):
        cfg = _make_cfg(enable_human_field=False)
        orch = ContinuumOrchestrator(config=cfg)
        result = orch.run(trace_id="no-human-field")
        assert isinstance(result, ContinuumState)

    def test_enable_liminal_field_false_returns_state(self):
        cfg = _make_cfg(enable_liminal_field=False)
        orch = ContinuumOrchestrator(config=cfg)
        result = orch.run(trace_id="no-liminal")
        assert isinstance(result, ContinuumState)
        assert not result.degraded

    def test_enable_decision_gate_false_action_is_observe(self):
        cfg = _make_cfg(enable_decision_gate=False)
        orch = ContinuumOrchestrator(config=cfg)
        result = orch.run(trace_id="no-decision-gate")
        assert result.decision.action_level == ActionLevel.OBSERVE

    def test_all_components_disabled_returns_valid_state(self):
        cfg = _make_cfg(
            enable_perception=False,
            enable_human_field=False,
            enable_liminal_field=False,
            enable_decision_gate=False,
        )
        orch = ContinuumOrchestrator(config=cfg)
        result = orch.run(trace_id="all-disabled")
        assert isinstance(result, ContinuumState)
        assert result.decision.action_level == ActionLevel.OBSERVE

    def test_all_flags_default_true(self):
        flags = FeatureFlags()
        assert flags.enable_perception is True
        assert flags.enable_human_field is True
        assert flags.enable_liminal_field is True
        assert flags.enable_decision_gate is True

    def test_all_flags_serialise_to_dict(self):
        flags = FeatureFlags(
            enable_perception=False,
            enable_human_field=False,
            enable_liminal_field=False,
            enable_decision_gate=False,
        )
        d = flags.model_dump()
        assert d["enable_perception"] is False
        assert d["enable_human_field"] is False
        assert d["enable_liminal_field"] is False
        assert d["enable_decision_gate"] is False


# ---------------------------------------------------------------------------
# D) Extra-flags pass-through from config dict
# ---------------------------------------------------------------------------


class TestExtraFlagsPassThrough:
    def setup_method(self):
        self._metrics_patch = patch(
            "core.continuum.orchestrator.get_continuum_metrics",
            return_value=ContinuumMetrics(),
        )
        self._metrics_patch.start()

    def teardown_method(self):
        self._metrics_patch.stop()

    def test_enable_perception_via_extra_flags(self):
        orch = ContinuumOrchestrator(extra_flags={"enable_perception": False})
        assert orch._effective_cfg.flags.enable_perception is False

    def test_enable_human_field_via_extra_flags(self):
        orch = ContinuumOrchestrator(extra_flags={"enable_human_field": False})
        assert orch._effective_cfg.flags.enable_human_field is False

    def test_enable_liminal_field_via_extra_flags(self):
        orch = ContinuumOrchestrator(extra_flags={"enable_liminal_field": False})
        assert orch._effective_cfg.flags.enable_liminal_field is False

    def test_enable_decision_gate_via_extra_flags(self):
        orch = ContinuumOrchestrator(extra_flags={"enable_decision_gate": False})
        assert orch._effective_cfg.flags.enable_decision_gate is False

    def test_enable_continuum_via_extra_flags_still_works(self):
        orch = ContinuumOrchestrator(extra_flags={"enable_continuum": False})
        result = orch.run(trace_id="extra-disabled")
        assert result.phase == ContinuumPhase.FORMLESS

    def test_unknown_extra_flags_ignored(self):
        # Should not raise
        orch = ContinuumOrchestrator(extra_flags={"totally_unknown_key": 999})
        result = orch.run(trace_id="unknown-flags")
        assert isinstance(result, ContinuumState)

    def test_metrics_record_tick_after_run(self):
        metrics = ContinuumMetrics()
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator()
            orch.run(trace_id="metrics-test")
        snap = metrics.snapshot()
        assert snap["ticks_total"] == 1
