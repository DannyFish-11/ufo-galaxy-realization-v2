"""
tests/test_continuum_guardrails.py
=====================================

Tests for PR-6 continuum performance guardrails:
- Per-tick time budget (max_tick_ms) — graceful degradation to formless
- Sampling rate (sampling_rate) — skipped ticks return cached/formless state

Test groups
-----------
A) Time budget guardrail (max_tick_ms).
B) Sampling rate guardrail (sampling_rate).
C) FeatureFlags validation — range / type constraints.
D) Integration — guardrails interact correctly with metrics.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.continuum.config import ContinuumConfig, FeatureFlags
from core.continuum.metrics import ContinuumMetrics
from core.continuum.orchestrator import ContinuumOrchestrator
from core.continuum.types import ContinuumPhase, ContinuumState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**flag_kwargs) -> ContinuumConfig:
    return ContinuumConfig(flags=FeatureFlags(**flag_kwargs))


def _orch_with_metrics(**flag_kwargs):
    """Create an orchestrator paired with a fresh ContinuumMetrics."""
    metrics = ContinuumMetrics()
    cfg = _make_cfg(**flag_kwargs)
    with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
        orch = ContinuumOrchestrator(config=cfg)
    return orch, metrics


# ---------------------------------------------------------------------------
# A) Time budget guardrail
# ---------------------------------------------------------------------------


class TestTimeBudgetGuardrail:
    def _run_with_slow_pipeline(self, max_tick_ms: float, sleep_s: float):
        """Run the orchestrator but slow down _run_pipeline with a fake delay."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(max_tick_ms=max_tick_ms)

        original_pipeline = ContinuumOrchestrator._run_pipeline

        def _slow_pipeline(self_inner, **kwargs):
            time.sleep(sleep_s)
            return original_pipeline(self_inner, **kwargs)

        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)

        with patch.object(orch, "_run_pipeline", side_effect=lambda **kw: (time.sleep(sleep_s), original_pipeline(orch, **kw))[1]):
            result = orch.run(trace_id="budget-test")

        return result, metrics

    def test_no_budget_limit_passes_through(self):
        """max_tick_ms=0 means no limit — normal result returned."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(max_tick_ms=0.0)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            result = orch.run(trace_id="no-limit")
        assert isinstance(result, ContinuumState)
        assert result.degrade_reason != "tick_budget_exceeded"

    def test_budget_exceeded_returns_degraded_formless(self):
        """When pipeline exceeds max_tick_ms, result is degraded formless."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(max_tick_ms=0.001)  # 0.001 ms — will always be exceeded

        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            result = orch.run(trace_id="budget-exceeded")

        assert result.phase == ContinuumPhase.FORMLESS
        assert result.degraded is True
        assert result.degrade_reason == "tick_budget_exceeded"

    def test_budget_exceeded_increments_metrics(self):
        """budget_exceeded counter is incremented when budget is exceeded."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(max_tick_ms=0.001)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            orch.run(trace_id="budget-metrics")

        snap = metrics.snapshot()
        assert snap["ticks_budget_exceeded"] >= 1

    def test_budget_exceeded_trace_id_preserved(self):
        """Degraded formless state still carries the caller trace_id."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(max_tick_ms=0.001)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            result = orch.run(trace_id="trace-preserved")

        assert result.trace_id == "trace-preserved"

    def test_budget_not_exceeded_normal_result(self):
        """A large budget should never trigger degradation in normal operation."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(max_tick_ms=60_000.0)  # 60 seconds
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            result = orch.run(trace_id="large-budget")

        assert result.degrade_reason != "tick_budget_exceeded"
        snap = metrics.snapshot()
        assert snap["ticks_budget_exceeded"] == 0

    def test_budget_exceeded_emits_warning_log(self, caplog):
        """Budget exceeded path emits a WARNING log entry."""
        import logging
        metrics = ContinuumMetrics()
        cfg = _make_cfg(max_tick_ms=0.001)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            with caplog.at_level(logging.WARNING, logger="Galaxy.Continuum.Orchestrator"):
                orch.run(trace_id="budget-warn")

        assert any("budget exceeded" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# B) Sampling rate guardrail
# ---------------------------------------------------------------------------


class TestSamplingRateGuardrail:
    def test_sampling_rate_one_runs_every_tick(self):
        """sampling_rate=1.0 should run every tick."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(sampling_rate=1.0)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            for _ in range(5):
                orch.run(trace_id="sample-all")

        snap = metrics.snapshot()
        assert snap["ticks_skipped"] == 0

    def test_sampling_rate_zero_skips_every_tick(self):
        """sampling_rate=0.0 should skip every tick."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(sampling_rate=0.0)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            for _ in range(5):
                orch.run(trace_id="sample-none")

        snap = metrics.snapshot()
        assert snap["ticks_skipped"] == 5

    def test_sampling_rate_zero_returns_formless_before_first_run(self):
        """Before any real tick, skipped ticks return formless default."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(sampling_rate=0.0)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            result = orch.run(trace_id="skip-first")

        assert result.phase == ContinuumPhase.FORMLESS
        assert result.presence_intensity == 0.0

    def test_sampling_rate_zero_returns_last_state_after_real_tick(self):
        """After a real tick, skipped ticks return the last cached state."""
        # Run a full tick with rate=1.0 to warm the orchestrator
        real_metrics = ContinuumMetrics()
        cfg_full = _make_cfg(sampling_rate=1.0)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=real_metrics):
            orch_full = ContinuumOrchestrator(config=cfg_full)
            first = orch_full.run(trace_id="first-real")

        # Create a separate orchestrator with rate=0.0; warm it with one real tick
        skip_metrics = ContinuumMetrics()
        cfg_zero = _make_cfg(sampling_rate=1.0)  # first tick is real
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=skip_metrics):
            orch_skip = ContinuumOrchestrator(config=cfg_zero)
            primed = orch_skip.run(trace_id="prime")

        # Now switch to rate=0.0 by creating a new orchestrator from a zero-rate config,
        # but prime its last_state by running one real tick first
        zero_metrics = ContinuumMetrics()
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=zero_metrics):
            orch_combo = ContinuumOrchestrator(config=_make_cfg(sampling_rate=1.0))
            warm_result = orch_combo.run(trace_id="warm")

            # Switch flags to 0.0 sampling via model_copy on effective config
            new_flags = orch_combo._effective_cfg.flags.model_copy(update={"sampling_rate": 0.0})
            orch_combo._effective_cfg = orch_combo._effective_cfg.model_copy(update={"flags": new_flags})

            skipped = orch_combo.run(trace_id="skipped-tick")

        # Skipped tick must return the last cached state (same phase as warm run)
        assert skipped.phase == warm_result.phase

    def test_sampling_rate_via_extra_flags(self):
        """sampling_rate can be set through extra_flags dict."""
        orch = ContinuumOrchestrator(extra_flags={"continuum_sampling_rate": 0.0})
        assert orch._effective_cfg.flags.sampling_rate == pytest.approx(0.0)

    def test_max_tick_ms_via_extra_flags(self):
        """max_tick_ms can be set through extra_flags dict."""
        orch = ContinuumOrchestrator(extra_flags={"continuum_max_tick_ms": 50.0})
        assert orch._effective_cfg.flags.max_tick_ms == pytest.approx(50.0)

    def test_sampling_skipped_increments_ticks_total(self):
        """Skipped ticks still increment ticks_total counter."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(sampling_rate=0.0)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            orch.run(trace_id="skip-total")

        snap = metrics.snapshot()
        assert snap["ticks_total"] == 1
        assert snap["ticks_skipped"] == 1

    def test_sampling_debug_log_when_skipped(self, caplog):
        """sampling_rate=0 with debug=True emits a SKIPPED log entry."""
        import logging
        metrics = ContinuumMetrics()
        cfg = _make_cfg(sampling_rate=0.0, debug=True)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            with caplog.at_level(logging.DEBUG, logger="Galaxy.Continuum.Orchestrator"):
                orch.run(trace_id="debug-skip")

        assert any("SKIPPED" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# C) FeatureFlags validation
# ---------------------------------------------------------------------------


class TestFeatureFlagsValidation:
    def test_max_tick_ms_defaults_zero(self):
        flags = FeatureFlags()
        assert flags.max_tick_ms == 0.0

    def test_sampling_rate_defaults_one(self):
        flags = FeatureFlags()
        assert flags.sampling_rate == 1.0

    def test_sampling_rate_clamped_above_one(self):
        with pytest.raises(Exception):
            FeatureFlags(sampling_rate=1.5)

    def test_sampling_rate_clamped_below_zero(self):
        with pytest.raises(Exception):
            FeatureFlags(sampling_rate=-0.1)

    def test_max_tick_ms_non_negative(self):
        with pytest.raises(Exception):
            FeatureFlags(max_tick_ms=-1.0)

    def test_flags_serialise_defaults(self):
        d = FeatureFlags().model_dump()
        assert d["max_tick_ms"] == 0.0
        assert d["sampling_rate"] == 1.0


# ---------------------------------------------------------------------------
# D) Integration — guardrails + metrics
# ---------------------------------------------------------------------------


class TestGuardrailsIntegration:
    def test_normal_tick_increments_phase_counter(self):
        metrics = ContinuumMetrics()
        cfg = _make_cfg()
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            result = orch.run(trace_id="phase-counter")

        snap = metrics.snapshot()
        phase = result.phase.value
        assert snap["phases"][phase] >= 1

    def test_budget_exceeded_does_not_cache_last_state(self):
        """When budget is exceeded the bad result must not become the sampling fallback.

        We verify observable behavior: after a budget-exceeded tick, a subsequent
        skipped tick (sampling_rate=0) must return the formless default rather than
        the degraded result (since it was never cached as a good state).
        """
        metrics = ContinuumMetrics()
        # max_tick_ms=0.001 will always be exceeded; sampling_rate stays 1.0
        cfg = _make_cfg(max_tick_ms=0.001)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            # First tick: pipeline runs but budget is exceeded → degraded formless, not cached
            exceeded = orch.run(trace_id="budget-exceeded")
        assert exceeded.degrade_reason == "tick_budget_exceeded"

        # Now switch to sampling_rate=0 to force a skip
        metrics2 = ContinuumMetrics()
        new_flags = orch._effective_cfg.flags.model_copy(update={"sampling_rate": 0.0})
        orch._effective_cfg = orch._effective_cfg.model_copy(update={"flags": new_flags})
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics2):
            skipped = orch.run(trace_id="after-exceeded")

        # The skipped tick should return formless default (nothing was cached)
        assert skipped.phase == ContinuumPhase.FORMLESS
        assert skipped.presence_intensity == 0.0
        assert skipped.degrade_reason != "tick_budget_exceeded"

    def test_multiple_ticks_accumulate_stage_latency(self):
        metrics = ContinuumMetrics()
        cfg = _make_cfg()
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            for _ in range(3):
                orch.run(trace_id="multi-tick")

        snap = metrics.snapshot()
        # At least the temporal_engine stage should have 3 observations
        assert snap["stage_latency"]["temporal_engine"]["count"] == 3

    def test_disabled_flag_no_metrics_recorded(self):
        """When continuum is fully disabled, metrics.ticks_total stays 0."""
        metrics = ContinuumMetrics()
        cfg = _make_cfg(enabled=False)
        with patch("core.continuum.orchestrator.get_continuum_metrics", return_value=metrics):
            orch = ContinuumOrchestrator(config=cfg)
            orch.run(trace_id="disabled-no-metrics")

        snap = metrics.snapshot()
        # Disabled path returns before touching metrics
        assert snap["ticks_total"] == 0
