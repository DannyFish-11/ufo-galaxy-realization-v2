"""tests/test_pr19_memory_decision_bias.py
============================================
Tests for PR-19: memory-informed runtime bias layer.

Coverage matrix
---------------
Group A — Sentinel / authority assertions
  A01. MEMORY_DECISION_BIAS_IS_AUTHORITY sentinel exists.
  A02. MEMORY_DECISION_BIAS_PR19_SENTINEL sentinel exists.
  A03. HARD_GATES_UNAFFECTED_BY_MEMORY_BIAS_POLICY sentinel exists.
  A04. MEMORY_BIAS_IS_ADVISORY_ONLY_POLICY sentinel exists.
  A05. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 sentinel exists in kernel.py.
  A06. MEMORY_BIAS_PLANNER_CONTINUITY_WIRED_PR19 sentinel exists in execution_planner.py.
  A07. MEMORY_DECISION_BIAS_ALIGNED_PR19 alignment sentinel exists in projection.py.

Group B — MemoryBias derivation from TaskMemory
  B01. derive_memory_bias(None) with no singleton → returns FALLBACK_MEMORY_BIAS.
  B02. derive_memory_bias with empty task memory → novelty posture.
  B03. derive_memory_bias with 1 summary (below min) → novelty posture.
  B04. derive_memory_bias with high-success history → continuity_seeking posture.
  B05. derive_memory_bias with low-success history → retrieval_seeking posture.
  B06. derive_memory_bias with moderate-success history → novelty posture.
  B07. derive_memory_bias with high diversity → novelty posture.
  B08. derive_memory_bias with high diversity + low success → retrieval_seeking.
  B09. influenced=True for live derivations, False for fallback.
  B10. source is 'task_memory' for live derivations.
  B11. MemoryBias.is_continuity_seeking() / is_retrieval_seeking() / is_novelty() helpers.
  B12. MemoryBias.to_dict() returns JSON-safe dict with expected keys.

Group C — PlannerContinuityGuidance derivation
  C01. get_planner_continuity_guidance(None) → fresh fallback, not influenced.
  C02. get_planner_continuity_guidance(fallback_bias) → fresh, not influenced.
  C03. continuity_seeking → continuity style, prefer_prior_context=True.
  C04. retrieval_seeking → retrieval style, prefer_recall_support=True.
  C05. novelty → fresh style, prefer_prior_context=False, prefer_recall_support=False.
  C06. influenced_by_memory is True for live guidance, False for fallback.
  C07. diagnostic_note is a non-empty string.
  C08. PlannerContinuityGuidance.to_dict() returns expected keys.

Group D — Planner strategy with continuity guidance (_pick_strategy)
  D01. No continuity_guidance → original strategy unchanged.
  D02. continuity_seeking bias near threshold → biases toward 'specialized'.
  D03. novelty bias → no additional bias (returns 'single' as normal).
  D04. budget guidance "single" takes priority over continuity_seeking bias.
  D05. task_type mapping table priority over memory bias.
  D06. retrieval_seeking near threshold → biases toward 'specialized'.
  D07. Memory bias does not affect fractal/swarm paths.

Group E — Diagnostics
  E01. build_memory_bias_diagnostics(None) returns valid dict with None posture.
  E02. build_memory_bias_diagnostics(bias) includes expected keys.
  E03. influenced=True is reflected in diagnostics.
  E04. hard_gate_overrode=True is reflected in diagnostics.
  E05. influence_surface is included in diagnostics.
  E06. FALLBACK_MEMORY_BIAS produces correct diagnostic dict.

Group F — Kernel wiring (mock-based)
  F01. KernelResponse has memory_bias_hint field (Optional[Dict]).
  F02. to_api_dict() includes 'memory_bias_hint' key.
  F03. execute() is called with memory_bias kwarg.

Group G — Backward compatibility
  G01. Old callers using execute(plan) without memory_bias still work.
  G02. Old callers using execute(plan, activation_budget=...) without memory_bias work.
  G03. derive_memory_bias never raises — returns fallback on invalid input.
  G04. get_planner_continuity_guidance never raises — returns fallback on error.
  G05. _pick_strategy without continuity_guidance works unchanged (regression).

Group H — Posture constants
  H01. MEMORY_POSTURE_CONTINUITY is 'continuity_seeking'.
  H02. MEMORY_POSTURE_RETRIEVAL is 'retrieval_seeking'.
  H03. MEMORY_POSTURE_NOVELTY is 'novelty'.
  H04. FALLBACK_MEMORY_BIAS has novelty posture and influenced=False.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_task_summary(success: bool = True, task_type: str = "") -> Any:
    """Build a minimal TaskSummary-like object."""
    obj = MagicMock()
    obj.success = success
    obj.task_type = task_type
    return obj


def _make_task_memory(summaries: List[Any]) -> Any:
    """Build a minimal TaskMemory-like object."""
    mem = MagicMock()
    mem.get_recent_summaries.return_value = summaries
    return mem


# ─────────────────────────────────────────────────────────────────────────────
# Group A — Sentinels
# ─────────────────────────────────────────────────────────────────────────────


class TestSentinels:
    """Group A — verify PR-19 authority/sentinel constants exist."""

    def test_a01_authority_sentinel(self):
        """A01. MEMORY_DECISION_BIAS_IS_AUTHORITY exists."""
        from core.cognitive import memory_decision_bias as mod
        assert hasattr(mod, "MEMORY_DECISION_BIAS_IS_AUTHORITY")
        assert isinstance(mod.MEMORY_DECISION_BIAS_IS_AUTHORITY, str)
        assert len(mod.MEMORY_DECISION_BIAS_IS_AUTHORITY) > 0

    def test_a02_pr19_sentinel(self):
        """A02. MEMORY_DECISION_BIAS_PR19_SENTINEL exists."""
        from core.cognitive import memory_decision_bias as mod
        assert hasattr(mod, "MEMORY_DECISION_BIAS_PR19_SENTINEL")
        assert "PR19" in mod.MEMORY_DECISION_BIAS_PR19_SENTINEL

    def test_a03_hard_gates_policy(self):
        """A03. HARD_GATES_UNAFFECTED_BY_MEMORY_BIAS_POLICY exists."""
        from core.cognitive import memory_decision_bias as mod
        assert hasattr(mod, "HARD_GATES_UNAFFECTED_BY_MEMORY_BIAS_POLICY")
        assert "authoritative" in mod.HARD_GATES_UNAFFECTED_BY_MEMORY_BIAS_POLICY.lower()

    def test_a04_advisory_only_policy(self):
        """A04. MEMORY_BIAS_IS_ADVISORY_ONLY_POLICY exists."""
        from core.cognitive import memory_decision_bias as mod
        assert hasattr(mod, "MEMORY_BIAS_IS_ADVISORY_ONLY_POLICY")
        assert "advisory" in mod.MEMORY_BIAS_IS_ADVISORY_ONLY_POLICY.lower()

    def test_a05_kernel_sentinel(self):
        """A05. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 exists in kernel.py."""
        from core.agent import kernel as kernel_mod
        assert hasattr(kernel_mod, "MEMORY_BIAS_WIRED_INTO_KERNEL_PR19")
        assert "PR19" in kernel_mod.MEMORY_BIAS_WIRED_INTO_KERNEL_PR19

    def test_a06_planner_sentinel(self):
        """A06. MEMORY_BIAS_PLANNER_CONTINUITY_WIRED_PR19 exists in execution_planner.py."""
        from core.agent import execution_planner as ep_mod
        assert hasattr(ep_mod, "MEMORY_BIAS_PLANNER_CONTINUITY_WIRED_PR19")
        assert "PR19" in ep_mod.MEMORY_BIAS_PLANNER_CONTINUITY_WIRED_PR19

    def test_a07_projection_alignment_sentinel(self):
        """A07. MEMORY_DECISION_BIAS_ALIGNED_PR19 exists in projection.py."""
        pytest.importorskip("fastapi", reason="fastapi not installed")
        import core.routes.projection as proj_mod
        assert hasattr(proj_mod, "MEMORY_DECISION_BIAS_ALIGNED_PR19")
        val = proj_mod.MEMORY_DECISION_BIAS_ALIGNED_PR19
        assert isinstance(val, str)
        assert "UNAVAILABLE" not in val


# ─────────────────────────────────────────────────────────────────────────────
# Group B — MemoryBias derivation
# ─────────────────────────────────────────────────────────────────────────────


class TestMemoryBiasDerivation:
    """Group B — derive_memory_bias()."""

    def test_b01_none_memory_no_singleton_returns_fallback(self):
        """B01. derive_memory_bias(None) with no singleton → returns FALLBACK_MEMORY_BIAS."""
        from core.cognitive.memory_decision_bias import derive_memory_bias, FALLBACK_MEMORY_BIAS
        with patch("core.cognitive.memory_decision_bias._derive_bias_impl") as mock_impl:
            mock_impl.side_effect = Exception("no singleton")
            result = derive_memory_bias(None)
            assert result is FALLBACK_MEMORY_BIAS

    def test_b02_empty_memory_returns_novelty(self):
        """B02. derive_memory_bias with empty task memory → novelty posture."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            MEMORY_POSTURE_NOVELTY,
        )
        mem = _make_task_memory([])
        result = derive_memory_bias(mem)
        assert result.memory_posture == MEMORY_POSTURE_NOVELTY
        assert result.recent_task_count == 0
        assert result.influenced is True
        assert result.source == "task_memory"

    def test_b03_single_summary_below_min_returns_novelty(self):
        """B03. derive_memory_bias with 1 summary (below min=2) → novelty posture."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            MEMORY_POSTURE_NOVELTY,
        )
        mem = _make_task_memory([_make_task_summary(success=True)])
        result = derive_memory_bias(mem)
        assert result.memory_posture == MEMORY_POSTURE_NOVELTY
        assert result.recent_task_count == 1

    def test_b04_high_success_returns_continuity_seeking(self):
        """B04. High-success history → continuity_seeking posture."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            MEMORY_POSTURE_CONTINUITY,
        )
        # 4/5 success → 80% success rate, same task_type → low diversity
        summaries = [
            _make_task_summary(success=True, task_type="analysis"),
            _make_task_summary(success=True, task_type="analysis"),
            _make_task_summary(success=True, task_type="analysis"),
            _make_task_summary(success=True, task_type="analysis"),
            _make_task_summary(success=False, task_type="analysis"),
        ]
        mem = _make_task_memory(summaries)
        result = derive_memory_bias(mem)
        assert result.memory_posture == MEMORY_POSTURE_CONTINUITY
        assert result.continuity_score > 0.5
        assert result.influenced is True

    def test_b05_low_success_returns_retrieval_seeking(self):
        """B05. Low-success history → retrieval_seeking posture."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            MEMORY_POSTURE_RETRIEVAL,
        )
        # 1/5 success → 20% success rate
        summaries = [
            _make_task_summary(success=True, task_type="search"),
            _make_task_summary(success=False, task_type="search"),
            _make_task_summary(success=False, task_type="search"),
            _make_task_summary(success=False, task_type="search"),
            _make_task_summary(success=False, task_type="search"),
        ]
        mem = _make_task_memory(summaries)
        result = derive_memory_bias(mem)
        assert result.memory_posture == MEMORY_POSTURE_RETRIEVAL
        assert result.retrieval_relevance > 0.5
        assert result.influenced is True

    def test_b06_moderate_success_returns_novelty(self):
        """B06. Moderate success (60%) → novelty posture."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            MEMORY_POSTURE_NOVELTY,
        )
        # 3/5 success → 60% success rate (between 45% and 70%)
        summaries = [
            _make_task_summary(success=True, task_type="coding"),
            _make_task_summary(success=True, task_type="coding"),
            _make_task_summary(success=True, task_type="coding"),
            _make_task_summary(success=False, task_type="coding"),
            _make_task_summary(success=False, task_type="coding"),
        ]
        mem = _make_task_memory(summaries)
        result = derive_memory_bias(mem)
        assert result.memory_posture == MEMORY_POSTURE_NOVELTY

    def test_b07_high_diversity_returns_novelty(self):
        """B07. High diversity (>= 4 distinct task types) → novelty posture."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            MEMORY_POSTURE_NOVELTY,
        )
        # 5 distinct task types, high success
        summaries = [
            _make_task_summary(success=True, task_type="analysis"),
            _make_task_summary(success=True, task_type="coding"),
            _make_task_summary(success=True, task_type="search"),
            _make_task_summary(success=True, task_type="planning"),
            _make_task_summary(success=True, task_type="translation"),
        ]
        mem = _make_task_memory(summaries)
        result = derive_memory_bias(mem)
        assert result.memory_posture == MEMORY_POSTURE_NOVELTY

    def test_b08_high_diversity_low_success_returns_retrieval(self):
        """B08. High diversity + low success → retrieval_seeking posture."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            MEMORY_POSTURE_RETRIEVAL,
        )
        # 5 distinct task types, low success
        summaries = [
            _make_task_summary(success=False, task_type="analysis"),
            _make_task_summary(success=False, task_type="coding"),
            _make_task_summary(success=False, task_type="search"),
            _make_task_summary(success=True, task_type="planning"),
            _make_task_summary(success=False, task_type="translation"),
        ]
        mem = _make_task_memory(summaries)
        result = derive_memory_bias(mem)
        assert result.memory_posture == MEMORY_POSTURE_RETRIEVAL

    def test_b09_influenced_true_for_live_false_for_fallback(self):
        """B09. influenced=True for live derivations, False for fallback."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            FALLBACK_MEMORY_BIAS,
        )
        # Live derivation
        mem = _make_task_memory([
            _make_task_summary(success=True, task_type="x"),
            _make_task_summary(success=True, task_type="x"),
            _make_task_summary(success=True, task_type="x"),
        ])
        result = derive_memory_bias(mem)
        assert result.influenced is True
        # Fallback
        assert FALLBACK_MEMORY_BIAS.influenced is False

    def test_b10_source_is_task_memory_for_live(self):
        """B10. source is 'task_memory' for live derivations."""
        from core.cognitive.memory_decision_bias import derive_memory_bias
        mem = _make_task_memory([
            _make_task_summary(success=True, task_type="a"),
            _make_task_summary(success=True, task_type="a"),
        ])
        result = derive_memory_bias(mem)
        assert result.source == "task_memory"

    def test_b11_posture_helpers(self):
        """B11. is_continuity_seeking() / is_retrieval_seeking() / is_novelty() work."""
        from core.cognitive.memory_decision_bias import (
            MemoryBias,
            MEMORY_POSTURE_CONTINUITY,
            MEMORY_POSTURE_RETRIEVAL,
            MEMORY_POSTURE_NOVELTY,
        )
        c = MemoryBias(memory_posture=MEMORY_POSTURE_CONTINUITY)
        assert c.is_continuity_seeking() is True
        assert c.is_retrieval_seeking() is False
        assert c.is_novelty() is False

        r = MemoryBias(memory_posture=MEMORY_POSTURE_RETRIEVAL)
        assert r.is_continuity_seeking() is False
        assert r.is_retrieval_seeking() is True
        assert r.is_novelty() is False

        n = MemoryBias(memory_posture=MEMORY_POSTURE_NOVELTY)
        assert n.is_continuity_seeking() is False
        assert n.is_retrieval_seeking() is False
        assert n.is_novelty() is True

    def test_b12_to_dict_returns_expected_keys(self):
        """B12. MemoryBias.to_dict() returns JSON-safe dict with expected keys."""
        from core.cognitive.memory_decision_bias import MemoryBias, MEMORY_POSTURE_NOVELTY
        bias = MemoryBias()
        d = bias.to_dict()
        expected_keys = {
            "memory_posture",
            "continuity_score",
            "retrieval_relevance",
            "novelty_score",
            "recent_task_count",
            "recent_success_rate",
            "influenced",
            "source",
            "diagnostic_note",
            "timestamp",
        }
        assert expected_keys.issubset(d.keys())
        assert d["memory_posture"] == MEMORY_POSTURE_NOVELTY


# ─────────────────────────────────────────────────────────────────────────────
# Group C — PlannerContinuityGuidance derivation
# ─────────────────────────────────────────────────────────────────────────────


class TestPlannerContinuityGuidance:
    """Group C — get_planner_continuity_guidance()."""

    def test_c01_none_returns_fresh_fallback(self):
        """C01. get_planner_continuity_guidance(None) → fresh, not influenced."""
        from core.cognitive.memory_decision_bias import get_planner_continuity_guidance
        guidance = get_planner_continuity_guidance(None)
        assert guidance.continuity_style == "fresh"
        assert guidance.influenced_by_memory is False
        assert guidance.prefer_prior_context is False
        assert guidance.prefer_recall_support is False

    def test_c02_fallback_bias_returns_fresh(self):
        """C02. get_planner_continuity_guidance(fallback_bias) → fresh, not influenced."""
        from core.cognitive.memory_decision_bias import (
            get_planner_continuity_guidance,
            FALLBACK_MEMORY_BIAS,
        )
        guidance = get_planner_continuity_guidance(FALLBACK_MEMORY_BIAS)
        assert guidance.influenced_by_memory is False
        assert guidance.continuity_style == "fresh"

    def test_c03_continuity_seeking_guidance(self):
        """C03. continuity_seeking → continuity style, prefer_prior_context=True."""
        from core.cognitive.memory_decision_bias import (
            get_planner_continuity_guidance,
            MemoryBias,
            MEMORY_POSTURE_CONTINUITY,
        )
        bias = MemoryBias(
            memory_posture=MEMORY_POSTURE_CONTINUITY,
            continuity_score=0.85,
            influenced=True,
            source="task_memory",
        )
        guidance = get_planner_continuity_guidance(bias)
        assert guidance.continuity_style == "continuity"
        assert guidance.prefer_prior_context is True
        assert guidance.prefer_recall_support is False
        assert guidance.influenced_by_memory is True

    def test_c04_retrieval_seeking_guidance(self):
        """C04. retrieval_seeking → retrieval style, prefer_recall_support=True."""
        from core.cognitive.memory_decision_bias import (
            get_planner_continuity_guidance,
            MemoryBias,
            MEMORY_POSTURE_RETRIEVAL,
        )
        bias = MemoryBias(
            memory_posture=MEMORY_POSTURE_RETRIEVAL,
            retrieval_relevance=0.75,
            influenced=True,
            source="task_memory",
        )
        guidance = get_planner_continuity_guidance(bias)
        assert guidance.continuity_style == "retrieval"
        assert guidance.prefer_recall_support is True
        assert guidance.prefer_prior_context is False
        assert guidance.influenced_by_memory is True

    def test_c05_novelty_guidance(self):
        """C05. novelty → fresh style, no prior context or recall preference."""
        from core.cognitive.memory_decision_bias import (
            get_planner_continuity_guidance,
            MemoryBias,
            MEMORY_POSTURE_NOVELTY,
        )
        bias = MemoryBias(
            memory_posture=MEMORY_POSTURE_NOVELTY,
            novelty_score=0.9,
            influenced=True,
            source="task_memory",
        )
        guidance = get_planner_continuity_guidance(bias)
        assert guidance.continuity_style == "fresh"
        assert guidance.prefer_prior_context is False
        assert guidance.prefer_recall_support is False
        assert guidance.influenced_by_memory is True

    def test_c06_influenced_by_memory_false_for_fallback(self):
        """C06. influenced_by_memory is False for fallback/unavailable."""
        from core.cognitive.memory_decision_bias import (
            get_planner_continuity_guidance,
            FALLBACK_MEMORY_BIAS,
        )
        guidance = get_planner_continuity_guidance(FALLBACK_MEMORY_BIAS)
        assert guidance.influenced_by_memory is False

    def test_c07_diagnostic_note_nonempty(self):
        """C07. diagnostic_note is a non-empty string."""
        from core.cognitive.memory_decision_bias import (
            get_planner_continuity_guidance,
            MemoryBias,
            MEMORY_POSTURE_CONTINUITY,
        )
        bias = MemoryBias(
            memory_posture=MEMORY_POSTURE_CONTINUITY,
            influenced=True,
            source="task_memory",
        )
        guidance = get_planner_continuity_guidance(bias)
        assert isinstance(guidance.diagnostic_note, str)
        assert len(guidance.diagnostic_note) > 0

    def test_c08_to_dict_returns_expected_keys(self):
        """C08. PlannerContinuityGuidance.to_dict() returns expected keys."""
        from core.cognitive.memory_decision_bias import (
            get_planner_continuity_guidance,
            FALLBACK_MEMORY_BIAS,
        )
        guidance = get_planner_continuity_guidance(FALLBACK_MEMORY_BIAS)
        d = guidance.to_dict()
        expected_keys = {
            "continuity_style",
            "prefer_prior_context",
            "prefer_recall_support",
            "memory_posture",
            "continuity_score",
            "influenced_by_memory",
            "diagnostic_note",
        }
        assert expected_keys.issubset(d.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Group D — Planner strategy with continuity guidance
# ─────────────────────────────────────────────────────────────────────────────


class TestPlannerStrategyWithContinuityGuidance:
    """Group D — _pick_strategy() with PR-19 continuity_guidance."""

    def _make_planner(self):
        from core.agent.execution_planner import ExecutionPlanner
        return ExecutionPlanner()

    def _make_continuity_guidance(
        self,
        continuity_style: str,
        prefer_prior_context: bool = False,
        prefer_recall_support: bool = False,
        influenced: bool = True,
    ):
        from core.cognitive.memory_decision_bias import PlannerContinuityGuidance
        return PlannerContinuityGuidance(
            continuity_style=continuity_style,
            prefer_prior_context=prefer_prior_context,
            prefer_recall_support=prefer_recall_support,
            influenced_by_memory=influenced,
        )

    def test_d01_no_guidance_original_strategy_unchanged(self):
        """D01. No continuity_guidance → original strategy unchanged."""
        planner = self._make_planner()
        # Complexity 0.3 → single (below both thresholds)
        strategy = planner._pick_strategy("hello world", 0.3, continuity_guidance=None)
        assert strategy == "single"

    def test_d02_continuity_seeking_near_threshold_biases_specialized(self):
        """D02. continuity_seeking near threshold biases toward 'specialized'."""
        planner = self._make_planner()
        guidance = self._make_continuity_guidance(
            "continuity",
            prefer_prior_context=True,
            influenced=True,
        )
        # Complexity 0.58 — below specialized_threshold=0.65, but within 0.10 margin
        strategy = planner._pick_strategy(
            "analyze this dataset",
            0.58,
            continuity_guidance=guidance,
        )
        assert strategy == "specialized"

    def test_d03_novelty_bias_no_change(self):
        """D03. novelty bias → no additional bias (returns 'single' as normal)."""
        planner = self._make_planner()
        guidance = self._make_continuity_guidance(
            "fresh",
            prefer_prior_context=False,
            prefer_recall_support=False,
            influenced=True,
        )
        # Complexity 0.3 → single
        strategy = planner._pick_strategy("hello world", 0.3, continuity_guidance=guidance)
        assert strategy == "single"

    def test_d04_budget_single_takes_priority_over_continuity_bias(self):
        """D04. budget guidance 'single' takes priority over continuity_seeking bias."""
        planner = self._make_planner()
        continuity_guidance = self._make_continuity_guidance(
            "continuity",
            prefer_prior_context=True,
            influenced=True,
        )
        # Build a narrow breadth_guidance that wants 'single'
        from core.cognitive.cognitive_activation_budget import PlannerBreadthGuidance
        breadth_guidance = PlannerBreadthGuidance(
            breadth_mode="narrow",
            strategy_preference="single",
            influenced_by_budget=True,
            complexity_threshold_adjustment=0.15,
        )
        # Complexity 0.58 — near threshold; continuity bias wants 'specialized',
        # but budget says 'single'
        strategy = planner._pick_strategy(
            "analyze this dataset",
            0.58,
            breadth_guidance=breadth_guidance,
            continuity_guidance=continuity_guidance,
        )
        assert strategy == "single"

    def test_d05_task_type_mapping_takes_priority_over_memory_bias(self):
        """D05. task_type mapping table priority over memory bias."""
        planner = self._make_planner()
        guidance = self._make_continuity_guidance(
            "continuity",
            prefer_prior_context=True,
            influenced=True,
        )
        # task_type='coding' → 'single' (from TASK_TYPE_STRATEGY_MAP)
        strategy = planner._pick_strategy(
            "write a function",
            0.6,
            task_type="coding",
            continuity_guidance=guidance,
        )
        assert strategy == "single"

    def test_d06_retrieval_seeking_near_threshold_biases_specialized(self):
        """D06. retrieval_seeking near threshold biases toward 'specialized'."""
        planner = self._make_planner()
        guidance = self._make_continuity_guidance(
            "retrieval",
            prefer_recall_support=True,
            influenced=True,
        )
        # Complexity 0.60 — near threshold
        strategy = planner._pick_strategy(
            "recall what we discussed before",
            0.60,
            continuity_guidance=guidance,
        )
        assert strategy == "specialized"

    def test_d07_memory_bias_does_not_affect_fractal(self):
        """D07. Memory bias does not affect fractal path (complexity > 0.75)."""
        planner = self._make_planner()
        guidance = self._make_continuity_guidance(
            "fresh",  # novelty bias, no preference
            influenced=True,
        )
        # Complexity 0.85 → fractal regardless of memory bias
        strategy = planner._pick_strategy(
            "complex multi-layer task",
            0.85,
            continuity_guidance=guidance,
        )
        assert strategy == "fractal"


# ─────────────────────────────────────────────────────────────────────────────
# Group E — Diagnostics
# ─────────────────────────────────────────────────────────────────────────────


class TestDiagnostics:
    """Group E — build_memory_bias_diagnostics()."""

    def test_e01_none_bias_returns_valid_dict(self):
        """E01. build_memory_bias_diagnostics(None) returns valid dict with None posture."""
        from core.cognitive.memory_decision_bias import build_memory_bias_diagnostics
        d = build_memory_bias_diagnostics(None)
        assert isinstance(d, dict)
        assert d["memory_posture"] is None
        assert d["influenced"] is False

    def test_e02_bias_dict_has_expected_keys(self):
        """E02. build_memory_bias_diagnostics(bias) includes expected keys."""
        from core.cognitive.memory_decision_bias import (
            build_memory_bias_diagnostics,
            MemoryBias,
        )
        bias = MemoryBias()
        d = build_memory_bias_diagnostics(bias)
        expected_keys = {
            "memory_posture",
            "continuity_score",
            "retrieval_relevance",
            "novelty_score",
            "recent_task_count",
            "influenced",
            "influence_surface",
            "hard_gate_overrode",
            "source",
            "diagnostic_note",
        }
        assert expected_keys.issubset(d.keys())

    def test_e03_influenced_true_reflected(self):
        """E03. influenced=True is reflected in diagnostics."""
        from core.cognitive.memory_decision_bias import (
            build_memory_bias_diagnostics,
            MemoryBias,
        )
        bias = MemoryBias()
        d = build_memory_bias_diagnostics(bias, influenced=True, influence_surface="planner_strategy")
        assert d["influenced"] is True
        assert d["influence_surface"] == "planner_strategy"

    def test_e04_hard_gate_overrode_reflected(self):
        """E04. hard_gate_overrode=True is reflected in diagnostics."""
        from core.cognitive.memory_decision_bias import (
            build_memory_bias_diagnostics,
            MemoryBias,
        )
        bias = MemoryBias()
        d = build_memory_bias_diagnostics(bias, hard_gate_overrode=True)
        assert d["hard_gate_overrode"] is True

    def test_e05_influence_surface_in_diagnostics(self):
        """E05. influence_surface is included in diagnostics."""
        from core.cognitive.memory_decision_bias import (
            build_memory_bias_diagnostics,
            MemoryBias,
        )
        bias = MemoryBias()
        d = build_memory_bias_diagnostics(bias, influence_surface="node_candidate_selection")
        assert d["influence_surface"] == "node_candidate_selection"

    def test_e06_fallback_bias_diagnostics(self):
        """E06. FALLBACK_MEMORY_BIAS produces correct diagnostic dict."""
        from core.cognitive.memory_decision_bias import (
            build_memory_bias_diagnostics,
            FALLBACK_MEMORY_BIAS,
            MEMORY_POSTURE_NOVELTY,
        )
        d = build_memory_bias_diagnostics(FALLBACK_MEMORY_BIAS)
        assert d["memory_posture"] == MEMORY_POSTURE_NOVELTY
        assert d["influenced"] is False
        assert d["source"] == "fallback"


# ─────────────────────────────────────────────────────────────────────────────
# Group F — Kernel wiring (mock-based)
# ─────────────────────────────────────────────────────────────────────────────


class TestKernelWiring:
    """Group F — KernelResponse wiring for PR-19."""

    def test_f01_kernel_response_has_memory_bias_hint_field(self):
        """F01. KernelResponse has memory_bias_hint field (Optional[Dict])."""
        from core.agent.kernel import KernelResponse
        resp = KernelResponse()
        assert hasattr(resp, "memory_bias_hint")
        assert resp.memory_bias_hint is None

    def test_f02_to_api_dict_includes_memory_bias_hint(self):
        """F02. to_api_dict() includes 'memory_bias_hint' key."""
        from core.agent.kernel import KernelResponse
        resp = KernelResponse(memory_bias_hint={"memory_posture": "novelty"})
        d = resp.to_api_dict()
        assert "memory_bias_hint" in d
        assert d["memory_bias_hint"] == {"memory_posture": "novelty"}

    def test_f03_execute_accepts_memory_bias_kwarg(self):
        """F03. execute() can be called with memory_bias kwarg without error."""
        from core.agent.execution_planner import ExecutionPlanner
        import inspect
        sig = inspect.signature(ExecutionPlanner.execute)
        assert "memory_bias" in sig.parameters


# ─────────────────────────────────────────────────────────────────────────────
# Group G — Backward compatibility
# ─────────────────────────────────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Group G — backward compatibility checks."""

    def test_g01_execute_without_memory_bias_works(self):
        """G01. Old callers using execute(plan) without memory_bias still work."""
        from core.agent.execution_planner import ExecutionPlanner
        import inspect
        sig = inspect.signature(ExecutionPlanner.execute)
        # memory_bias should have a default value of None
        assert sig.parameters["memory_bias"].default is None

    def test_g02_execute_with_activation_budget_only_works(self):
        """G02. Old callers using execute(plan, activation_budget=...) without memory_bias work."""
        from core.agent.execution_planner import ExecutionPlanner
        import inspect
        sig = inspect.signature(ExecutionPlanner.execute)
        # Both parameters have defaults
        assert sig.parameters["activation_budget"].default is None
        assert sig.parameters["memory_bias"].default is None

    def test_g03_derive_memory_bias_never_raises(self):
        """G03. derive_memory_bias never raises — returns fallback on invalid input."""
        from core.cognitive.memory_decision_bias import (
            derive_memory_bias,
            FALLBACK_MEMORY_BIAS,
        )
        # Pass something that will cause errors
        result = derive_memory_bias("not_a_memory_object")
        # Should return fallback, not raise
        assert result is not None
        assert hasattr(result, "memory_posture")

    def test_g04_get_planner_continuity_guidance_never_raises(self):
        """G04. get_planner_continuity_guidance never raises on error input."""
        from core.cognitive.memory_decision_bias import get_planner_continuity_guidance
        # Pass something weird
        result = get_planner_continuity_guidance("not_a_bias")
        assert result is not None
        assert hasattr(result, "continuity_style")

    def test_g05_pick_strategy_without_continuity_guidance_unchanged(self):
        """G05. _pick_strategy without continuity_guidance works unchanged (regression)."""
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner()
        # Same tests that should work pre-PR19
        assert planner._pick_strategy("hello", 0.3) == "single"
        assert planner._pick_strategy("large swarm task", 0.3) == "swarm"
        assert planner._pick_strategy("complex deep task", 0.85) == "fractal"


# ─────────────────────────────────────────────────────────────────────────────
# Group H — Posture constants
# ─────────────────────────────────────────────────────────────────────────────


class TestPostureConstants:
    """Group H — memory posture constants and FALLBACK_MEMORY_BIAS."""

    def test_h01_continuity_constant(self):
        """H01. MEMORY_POSTURE_CONTINUITY is 'continuity_seeking'."""
        from core.cognitive.memory_decision_bias import MEMORY_POSTURE_CONTINUITY
        assert MEMORY_POSTURE_CONTINUITY == "continuity_seeking"

    def test_h02_retrieval_constant(self):
        """H02. MEMORY_POSTURE_RETRIEVAL is 'retrieval_seeking'."""
        from core.cognitive.memory_decision_bias import MEMORY_POSTURE_RETRIEVAL
        assert MEMORY_POSTURE_RETRIEVAL == "retrieval_seeking"

    def test_h03_novelty_constant(self):
        """H03. MEMORY_POSTURE_NOVELTY is 'novelty'."""
        from core.cognitive.memory_decision_bias import MEMORY_POSTURE_NOVELTY
        assert MEMORY_POSTURE_NOVELTY == "novelty"

    def test_h04_fallback_bias_is_novelty_not_influenced(self):
        """H04. FALLBACK_MEMORY_BIAS has novelty posture and influenced=False."""
        from core.cognitive.memory_decision_bias import (
            FALLBACK_MEMORY_BIAS,
            MEMORY_POSTURE_NOVELTY,
        )
        assert FALLBACK_MEMORY_BIAS.memory_posture == MEMORY_POSTURE_NOVELTY
        assert FALLBACK_MEMORY_BIAS.influenced is False
        assert FALLBACK_MEMORY_BIAS.source == "fallback"
        assert FALLBACK_MEMORY_BIAS.recent_task_count == 0
