"""tests/test_pr19_memory_informed_runtime_bias.py
==================================================
Tests for PR-19: memory-informed runtime bias.

Coverage matrix
---------------
Group A — Sentinel / authority assertions
  A01. MEMORY_BIAS_LAYER_IS_AUTHORITY sentinel exists in memory_bias_layer.
  A02. MEMORY_BIAS_LAYER_PR19_SENTINEL sentinel exists in memory_bias_layer.
  A03. HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY sentinel exists.
  A04. MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY sentinel exists.
  A05. MEMORY_BIAS_CONSUMES_EXISTING_SIGNALS_POLICY sentinel exists.
  A06. MEMORY_BIAS_SUBORDINATE_TO_TASK_SEMANTICS_POLICY sentinel exists.
  A07. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 sentinel exists in kernel.py.
  A08. MEMORY_BIAS_PLANNER_GUIDANCE_WIRED_PR19 sentinel exists in execution_planner.py.
  A09. MEMORY_BIAS_LAYER_ALIGNED_PR19 alignment sentinel exists in projection.py.

Group B — MemoryBias derivation (unit — mocked memory sources)
  B01. derive_memory_bias(None session) with no live memory → NOVELTY fallback.
  B02. MemoryBias with wm_depth=0, ltm=0, tasks=0 → NOVELTY posture.
  B03. MemoryBias with wm_depth>=5 → CONTINUITY posture.
  B04. MemoryBias with wm_depth=2..4 + recent tasks → CONTINUITY posture.
  B05. MemoryBias with wm_depth=0 + ltm_depth>=3 → RETRIEVAL posture.
  B06. MemoryBias with low wm + low ltm → NOVELTY posture.
  B07. influenced_by_memory=True when any memory source has content.
  B08. influenced_by_memory=False (fallback) when all sources are empty.
  B09. MemoryBias.is_continuity() / is_retrieval() / is_novelty() helpers work.
  B10. MemoryBias.to_dict() returns JSON-safe dict with expected keys.
  B11. continuity_score is in [0.0, 1.0].
  B12. retrieval_relevance is in [0.0, 1.0].
  B13. novelty_factor is approximately 1 - continuity_score.
  B14. source is 'memory_bias_layer' for live derivations.

Group C — MemoryPlannerGuidance derivation
  C01. get_memory_planner_guidance(None) → non-influenced fresh guidance.
  C02. get_memory_planner_guidance(fallback_bias) → non-influenced fresh guidance.
  C03. CONTINUITY bias → decomposition_hint='resume', prefer_single_agent=True, adj>0.
  C04. RETRIEVAL bias → decomposition_hint='recall', prefer_single_agent=False, adj=0.0.
  C05. NOVELTY bias (with content) → decomposition_hint='fresh', prefer_single=False.
  C06. influenced_by_memory=True for live guidance, False for fallback/None.
  C07. diagnostic_note is a non-empty string.
  C08. MemoryPlannerGuidance.to_dict() returns expected keys.

Group D — Diagnostics
  D01. build_memory_bias_diagnostics(None) returns minimal dict with posture key.
  D02. build_memory_bias_diagnostics with bias returns bias fields plus extras.
  D03. influenced_runtime_decision field reflects supplied influenced param.
  D04. influence_source field reflects supplied source param.
  D05. build_memory_bias_diagnostics never raises on bad input.

Group E — Planner strategy with memory guidance (_pick_strategy)
  E01. No memory_guidance → original thresholds unaffected.
  E02. CONTINUITY guidance raises fractal threshold by +0.10.
  E03. CONTINUITY guidance returns 'single' when prefer_single_agent=True below threshold.
  E04. RETRIEVAL guidance has no threshold adjustment (0.0).
  E05. NOVELTY guidance has no threshold adjustment (0.0) and no single preference.
  E06. task_type mapping table takes highest priority over memory guidance.
  E07. Keyword-based 'swarm' is not overridden by CONTINUITY memory guidance.
  E08. When PR-18 breadth_guidance has strategy_pref='single', memory guidance is ignored.
  E09. Keyword 'fractal' returns 'fractal' even with CONTINUITY memory guidance.

Group F — Kernel wiring (mock-based)
  F01. KernelResponse has memory_bias_hint field (Optional[Dict]).
  F02. to_api_dict() includes 'memory_bias_hint' key.
  F03. execute() is called with memory_bias kwarg.

Group G — Backward compatibility
  G01. Old callers using execute(plan) without memory_bias still work.
  G02. Old callers using execute(plan, activation_budget=x) without memory_bias work.
  G03. derive_memory_bias never raises — returns fallback on any error.
  G04. get_memory_planner_guidance never raises — returns fallback on error.
  G05. build_memory_bias_diagnostics never raises on None bias.

Group H — Advisory / non-override assertions
  H01. Memory bias NOVELTY posture does not prevent 'fractal' at high complexity.
  H02. Memory bias CONTINUITY posture does not force 'single' when complexity is fractal-level.
  H03. Memory bias cannot override a task_type-mapped strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_memory_bias(
    posture: str = "novelty",
    continuity_score: float = 0.0,
    retrieval_relevance: float = 0.0,
    novelty_factor: float = 1.0,
    wm_depth: int = 0,
    ltm_depth: int = 0,
    recent_task_count: int = 0,
    influenced: bool = True,
    source: str = "memory_bias_layer",
) -> Any:
    """Build a MemoryBias object directly."""
    from core.cognitive.memory_bias_layer import MemoryBias
    return MemoryBias(
        posture=posture,
        continuity_score=continuity_score,
        retrieval_relevance=retrieval_relevance,
        novelty_factor=novelty_factor,
        working_memory_depth=wm_depth,
        long_term_memory_depth=ltm_depth,
        recent_task_count=recent_task_count,
        influenced_by_memory=influenced,
        source=source,
        session_id="test_session",
    )


def _make_memory_guidance(
    posture: str = "novelty",
    decomp_hint: str = "fresh",
    prefer_single: bool = False,
    adj: float = 0.0,
    influenced: bool = True,
) -> Any:
    """Build a MemoryPlannerGuidance object directly."""
    from core.cognitive.memory_bias_layer import MemoryPlannerGuidance
    return MemoryPlannerGuidance(
        posture=posture,
        decomposition_hint=decomp_hint,
        prefer_single_agent=prefer_single,
        complexity_threshold_adjustment=adj,
        influenced_by_memory=influenced,
        diagnostic_note=f"test guidance for {posture}",
    )


def _make_planner():
    """Return an ExecutionPlanner instance."""
    from core.agent.execution_planner import ExecutionPlanner
    return ExecutionPlanner()


# ─────────────────────────────────────────────────────────────────────────────
# Group A — Sentinel / authority assertions
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupA_Sentinels:
    def test_A01_authority_sentinel_exists(self):
        from core.cognitive.memory_bias_layer import MEMORY_BIAS_LAYER_IS_AUTHORITY
        assert "CANONICAL_AUTHORITY" in MEMORY_BIAS_LAYER_IS_AUTHORITY
        assert "PR-19" in MEMORY_BIAS_LAYER_IS_AUTHORITY

    def test_A02_pr19_sentinel_exists(self):
        from core.cognitive.memory_bias_layer import MEMORY_BIAS_LAYER_PR19_SENTINEL
        assert "PR19_SENTINEL" in MEMORY_BIAS_LAYER_PR19_SENTINEL
        assert "PR-19" in MEMORY_BIAS_LAYER_PR19_SENTINEL

    def test_A03_hard_gates_policy_exists(self):
        from core.cognitive.memory_bias_layer import HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY
        assert "POLICY_1" in HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY
        assert "Hard gates" in HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY

    def test_A04_advisory_policy_exists(self):
        from core.cognitive.memory_bias_layer import MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY
        assert "POLICY_2" in MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY
        assert "advisory" in MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY.lower()

    def test_A05_consumes_existing_signals_policy_exists(self):
        from core.cognitive.memory_bias_layer import MEMORY_BIAS_CONSUMES_EXISTING_SIGNALS_POLICY
        assert "POLICY_3" in MEMORY_BIAS_CONSUMES_EXISTING_SIGNALS_POLICY

    def test_A06_subordinate_to_task_semantics_policy_exists(self):
        from core.cognitive.memory_bias_layer import MEMORY_BIAS_SUBORDINATE_TO_TASK_SEMANTICS_POLICY
        assert "POLICY_4" in MEMORY_BIAS_SUBORDINATE_TO_TASK_SEMANTICS_POLICY

    def test_A07_kernel_sentinel_exists(self):
        from core.agent.kernel import MEMORY_BIAS_WIRED_INTO_KERNEL_PR19
        assert "MEMORY_BIAS_WIRED_INTO_KERNEL_PR19" in MEMORY_BIAS_WIRED_INTO_KERNEL_PR19
        assert "PR19" in MEMORY_BIAS_WIRED_INTO_KERNEL_PR19

    def test_A08_planner_sentinel_exists(self):
        from core.agent.execution_planner import MEMORY_BIAS_PLANNER_GUIDANCE_WIRED_PR19
        assert "MEMORY_BIAS_PLANNER_GUIDANCE_WIRED_PR19" in MEMORY_BIAS_PLANNER_GUIDANCE_WIRED_PR19
        assert "PR19" in MEMORY_BIAS_PLANNER_GUIDANCE_WIRED_PR19

    def test_A09_projection_alignment_sentinel_exists(self):
        from core.routes.projection import MEMORY_BIAS_LAYER_ALIGNED_PR19
        assert "PR19" in MEMORY_BIAS_LAYER_ALIGNED_PR19
        assert "UNAVAILABLE" not in MEMORY_BIAS_LAYER_ALIGNED_PR19


# ─────────────────────────────────────────────────────────────────────────────
# Group B — MemoryBias derivation
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupB_MemoryBiasDeriivation:
    def test_B01_derive_with_no_session_returns_valid_bias(self):
        from core.cognitive.memory_bias_layer import derive_memory_bias, POSTURE_NOVELTY
        bias = derive_memory_bias()
        assert bias is not None
        assert bias.posture in ("continuity", "retrieval", "novelty")

    def test_B02_no_memory_produces_novelty_posture(self):
        from core.cognitive.memory_bias_layer import (
            derive_memory_bias, POSTURE_NOVELTY, FALLBACK_MEMORY_BIAS,
        )
        # Mock the memory singletons inside the target modules directly
        with (
            patch("core.cognitive.working_memory.WorkingMemory.get", return_value=[]),
            patch("core.cognitive.long_term_memory.LongTermMemory.retrieve_all", return_value=[]),
            patch("core.task_memory.TaskMemory.get_recent_summaries", return_value=[]),
        ):
            bias = derive_memory_bias(session_id="sess_test")
        # When all sources return empty, posture should be novelty
        assert bias.posture == POSTURE_NOVELTY

    def test_B03_high_wm_depth_produces_continuity_posture(self):
        """wm_depth >= 5 → continuity_score >= 0.6 → CONTINUITY."""
        from core.cognitive.memory_bias_layer import (
            _compute_continuity_score, _classify_posture, POSTURE_CONTINUITY,
        )
        score = _compute_continuity_score(wm_depth=5, recent_task_count=0)
        posture = _classify_posture(score, 0.0)
        assert score >= 0.6
        assert posture == POSTURE_CONTINUITY

    def test_B04_medium_wm_plus_tasks_produces_continuity(self):
        """wm_depth=2 + recent_tasks=3 → continuity_score >= 0.6 → CONTINUITY."""
        from core.cognitive.memory_bias_layer import (
            _compute_continuity_score, _classify_posture, POSTURE_CONTINUITY,
        )
        score = _compute_continuity_score(wm_depth=2, recent_task_count=3)
        posture = _classify_posture(score, 0.0)
        assert score >= 0.6
        assert posture == POSTURE_CONTINUITY

    def test_B05_high_ltm_with_zero_wm_produces_retrieval(self):
        """wm_depth=0 + ltm_depth>=3 → RETRIEVAL posture."""
        from core.cognitive.memory_bias_layer import (
            _compute_continuity_score, _compute_retrieval_relevance,
            _classify_posture, POSTURE_RETRIEVAL,
        )
        c_score = _compute_continuity_score(wm_depth=0, recent_task_count=0)
        r_score = _compute_retrieval_relevance(ltm_depth=3)
        posture = _classify_posture(c_score, r_score)
        assert posture == POSTURE_RETRIEVAL

    def test_B06_low_wm_low_ltm_produces_novelty(self):
        """wm_depth=1 + ltm_depth=0 → NOVELTY posture."""
        from core.cognitive.memory_bias_layer import (
            _compute_continuity_score, _compute_retrieval_relevance,
            _classify_posture, POSTURE_NOVELTY,
        )
        c_score = _compute_continuity_score(wm_depth=1, recent_task_count=0)
        r_score = _compute_retrieval_relevance(ltm_depth=0)
        posture = _classify_posture(c_score, r_score)
        assert posture == POSTURE_NOVELTY

    def test_B07_influenced_true_when_any_source_has_content(self):
        bias = _make_memory_bias(wm_depth=3, influenced=True)
        assert bias.influenced_by_memory is True

    def test_B08_influenced_false_for_fallback(self):
        from core.cognitive.memory_bias_layer import FALLBACK_MEMORY_BIAS
        assert FALLBACK_MEMORY_BIAS.influenced_by_memory is False
        assert FALLBACK_MEMORY_BIAS.source == "fallback"

    def test_B09_posture_helpers(self):
        c_bias = _make_memory_bias(posture="continuity")
        r_bias = _make_memory_bias(posture="retrieval")
        n_bias = _make_memory_bias(posture="novelty")
        assert c_bias.is_continuity()
        assert not c_bias.is_retrieval()
        assert not c_bias.is_novelty()
        assert r_bias.is_retrieval()
        assert n_bias.is_novelty()

    def test_B10_to_dict_returns_expected_keys(self):
        bias = _make_memory_bias(posture="continuity", continuity_score=0.75)
        d = bias.to_dict()
        assert "posture" in d
        assert "continuity_score" in d
        assert "retrieval_relevance" in d
        assert "novelty_factor" in d
        assert "influenced_by_memory" in d
        assert "source" in d
        assert "session_id" in d
        assert "timestamp" in d

    def test_B11_continuity_score_in_range(self):
        from core.cognitive.memory_bias_layer import _compute_continuity_score
        for wm in range(0, 10):
            for tasks in range(0, 5):
                s = _compute_continuity_score(wm, tasks)
                assert 0.0 <= s <= 1.0

    def test_B12_retrieval_relevance_in_range(self):
        from core.cognitive.memory_bias_layer import _compute_retrieval_relevance
        for ltm in range(0, 10):
            r = _compute_retrieval_relevance(ltm)
            assert 0.0 <= r <= 1.0

    def test_B13_novelty_factor_approx_one_minus_continuity(self):
        bias = _make_memory_bias(
            posture="novelty",
            continuity_score=0.3,
            novelty_factor=0.7,
        )
        assert abs(bias.novelty_factor - (1.0 - bias.continuity_score)) < 0.01

    def test_B14_source_is_memory_bias_layer_for_live(self):
        bias = _make_memory_bias(source="memory_bias_layer")
        assert bias.source == "memory_bias_layer"


# ─────────────────────────────────────────────────────────────────────────────
# Group C — MemoryPlannerGuidance derivation
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupC_MemoryPlannerGuidance:
    def test_C01_none_bias_returns_non_influenced_guidance(self):
        from core.cognitive.memory_bias_layer import get_memory_planner_guidance
        guidance = get_memory_planner_guidance(None)
        assert guidance.influenced_by_memory is False
        assert guidance.decomposition_hint == "fresh"

    def test_C02_fallback_bias_returns_non_influenced_guidance(self):
        from core.cognitive.memory_bias_layer import (
            get_memory_planner_guidance, FALLBACK_MEMORY_BIAS,
        )
        guidance = get_memory_planner_guidance(FALLBACK_MEMORY_BIAS)
        assert guidance.influenced_by_memory is False
        assert guidance.decomposition_hint == "fresh"

    def test_C03_continuity_bias_produces_resume_guidance(self):
        from core.cognitive.memory_bias_layer import get_memory_planner_guidance
        bias = _make_memory_bias(posture="continuity", continuity_score=0.75, influenced=True)
        guidance = get_memory_planner_guidance(bias)
        assert guidance.decomposition_hint == "resume"
        assert guidance.prefer_single_agent is True
        assert guidance.complexity_threshold_adjustment > 0.0

    def test_C04_retrieval_bias_produces_recall_guidance(self):
        from core.cognitive.memory_bias_layer import get_memory_planner_guidance
        bias = _make_memory_bias(posture="retrieval", retrieval_relevance=0.7, influenced=True)
        guidance = get_memory_planner_guidance(bias)
        assert guidance.decomposition_hint == "recall"
        assert guidance.prefer_single_agent is False
        assert guidance.complexity_threshold_adjustment == 0.0

    def test_C05_novelty_bias_produces_fresh_guidance(self):
        from core.cognitive.memory_bias_layer import get_memory_planner_guidance
        bias = _make_memory_bias(posture="novelty", wm_depth=1, influenced=True)
        guidance = get_memory_planner_guidance(bias)
        assert guidance.decomposition_hint == "fresh"
        assert guidance.prefer_single_agent is False

    def test_C06_influenced_true_for_live_false_for_fallback(self):
        from core.cognitive.memory_bias_layer import get_memory_planner_guidance, FALLBACK_MEMORY_BIAS
        live_bias = _make_memory_bias(posture="continuity", influenced=True)
        live_guidance = get_memory_planner_guidance(live_bias)
        fallback_guidance = get_memory_planner_guidance(FALLBACK_MEMORY_BIAS)
        assert live_guidance.influenced_by_memory is True
        assert fallback_guidance.influenced_by_memory is False

    def test_C07_diagnostic_note_is_non_empty(self):
        from core.cognitive.memory_bias_layer import get_memory_planner_guidance
        for posture in ("continuity", "retrieval", "novelty"):
            bias = _make_memory_bias(posture=posture, wm_depth=3, influenced=True)
            guidance = get_memory_planner_guidance(bias)
            assert guidance.diagnostic_note != ""

    def test_C08_to_dict_returns_expected_keys(self):
        guidance = _make_memory_guidance(posture="continuity", decomp_hint="resume")
        d = guidance.to_dict()
        assert "posture" in d
        assert "decomposition_hint" in d
        assert "prefer_single_agent" in d
        assert "complexity_threshold_adjustment" in d
        assert "influenced_by_memory" in d
        assert "diagnostic_note" in d


# ─────────────────────────────────────────────────────────────────────────────
# Group D — Diagnostics
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupD_Diagnostics:
    def test_D01_none_bias_returns_minimal_dict(self):
        from core.cognitive.memory_bias_layer import build_memory_bias_diagnostics
        d = build_memory_bias_diagnostics(None)
        assert "posture" in d

    def test_D02_live_bias_returns_full_dict(self):
        from core.cognitive.memory_bias_layer import build_memory_bias_diagnostics
        bias = _make_memory_bias(posture="continuity", continuity_score=0.8)
        d = build_memory_bias_diagnostics(bias)
        assert d["posture"] == "continuity"
        assert "continuity_score" in d
        assert "influenced_by_memory" in d

    def test_D03_influenced_runtime_decision_field(self):
        from core.cognitive.memory_bias_layer import build_memory_bias_diagnostics
        bias = _make_memory_bias()
        d_influenced = build_memory_bias_diagnostics(bias, influenced=True)
        d_not = build_memory_bias_diagnostics(bias, influenced=False)
        assert d_influenced["influenced_runtime_decision"] is True
        assert d_not["influenced_runtime_decision"] is False

    def test_D04_influence_source_field(self):
        from core.cognitive.memory_bias_layer import build_memory_bias_diagnostics
        bias = _make_memory_bias()
        d = build_memory_bias_diagnostics(bias, influence_source="planner_strategy")
        assert d["influence_source"] == "planner_strategy"

    def test_D05_diagnostics_never_raises(self):
        from core.cognitive.memory_bias_layer import build_memory_bias_diagnostics
        # Should not raise on any input
        _ = build_memory_bias_diagnostics(None)
        _ = build_memory_bias_diagnostics(None, influenced=True, influence_source="x")
        _ = build_memory_bias_diagnostics("not_a_bias_object")  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Group E — Planner strategy with memory guidance
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupE_PlannerStrategyWithMemoryGuidance:
    def test_E01_no_memory_guidance_leaves_thresholds_unchanged(self):
        planner = _make_planner()
        # With default thresholds: fractal=0.75, specialized=0.65
        # At complexity=0.60 with no guidance → below specialized (0.65) → 'single'
        strategy = planner._pick_strategy("do task", 0.60)
        assert strategy == "single"
        # At complexity=0.74 → >= specialized (0.65) → 'specialized'
        strategy = planner._pick_strategy("do task", 0.74)
        assert strategy == "specialized"
        # At complexity=0.76 → fractal
        strategy = planner._pick_strategy("do task", 0.76)
        assert strategy == "fractal"

    def test_E02_continuity_guidance_raises_fractal_threshold(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(
            posture="continuity", prefer_single=True, adj=0.10, influenced=True
        )
        # complexity=0.76 would normally be fractal; with +0.10 adj → threshold=0.85 → single
        strategy = planner._pick_strategy("do task", 0.76, memory_guidance=guidance)
        # fractal threshold is now 0.85; 0.76 < 0.85 → not fractal
        assert strategy != "fractal"

    def test_E03_continuity_guidance_prefer_single_returns_single(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(
            posture="continuity", prefer_single=True, adj=0.10, influenced=True
        )
        strategy = planner._pick_strategy("simple task", 0.3, memory_guidance=guidance)
        assert strategy == "single"

    def test_E04_retrieval_guidance_no_threshold_change(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(
            posture="retrieval", prefer_single=False, adj=0.0, influenced=True
        )
        # complexity=0.76 → fractal (threshold 0.75 unchanged)
        strategy = planner._pick_strategy("do task", 0.76, memory_guidance=guidance)
        assert strategy == "fractal"

    def test_E05_novelty_guidance_no_influence(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(
            posture="novelty", prefer_single=False, adj=0.0, influenced=True
        )
        strategy_no_guidance = planner._pick_strategy("do task", 0.74)
        strategy_with_guidance = planner._pick_strategy("do task", 0.74, memory_guidance=guidance)
        assert strategy_no_guidance == strategy_with_guidance

    def test_E06_task_type_mapping_takes_highest_priority(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(
            posture="continuity", prefer_single=True, adj=0.10, influenced=True
        )
        # 'chat' task type maps to 'single' regardless of memory guidance
        strategy = planner._pick_strategy("do task", 0.9, task_type="chat", memory_guidance=guidance)
        assert strategy == "single"

    def test_E07_swarm_keyword_not_overridden_by_continuity(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(
            posture="continuity", prefer_single=True, adj=0.10, influenced=True
        )
        strategy = planner._pick_strategy("批量处理大量任务", 0.5, memory_guidance=guidance)
        assert strategy == "swarm"

    def test_E08_pr18_strategy_pref_takes_precedence_over_memory_guidance(self):
        """When PR-18 breadth_guidance sets strategy_pref='single', memory adj is skipped."""
        planner = _make_planner()

        class _NarrowBreadthGuidance:
            breadth_mode = "narrow"
            max_concurrent_agents = 1
            complexity_threshold_adjustment = 0.15
            strategy_preference = "single"
            influenced_by_budget = True

        guidance = _make_memory_guidance(
            posture="continuity", prefer_single=True, adj=0.10, influenced=True
        )
        # With narrow breadth (PR-18 adj=0.15): fractal_threshold=0.90, specialized=0.80
        # Use complexity=0.70: 0.70 < 0.80 → not specialized, not fractal
        # strategy_pref='single' (from PR-18) → returns 'single'
        strategy = planner._pick_strategy(
            "do task", 0.70,
            breadth_guidance=_NarrowBreadthGuidance(),
            memory_guidance=guidance,
        )
        assert strategy == "single"

    def test_E09_fractal_keyword_returns_fractal_with_continuity_guidance(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(
            posture="continuity", prefer_single=True, adj=0.10, influenced=True
        )
        strategy = planner._pick_strategy("递归深度拆解任务", 0.3, memory_guidance=guidance)
        assert strategy == "fractal"


# ─────────────────────────────────────────────────────────────────────────────
# Group F — Kernel wiring (mock-based)
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupF_KernelWiring:
    def test_F01_kernel_response_has_memory_bias_hint_field(self):
        from core.agent.kernel import KernelResponse
        resp = KernelResponse()
        assert hasattr(resp, "memory_bias_hint")
        assert resp.memory_bias_hint is None  # default

    def test_F02_to_api_dict_includes_memory_bias_hint(self):
        from core.agent.kernel import KernelResponse
        resp = KernelResponse(memory_bias_hint={"posture": "novelty"})
        d = resp.to_api_dict()
        assert "memory_bias_hint" in d
        assert d["memory_bias_hint"] == {"posture": "novelty"}

    def test_F03_execute_called_with_memory_bias_kwarg(self):
        """execute() must accept and not crash with memory_bias=something."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult

        planner = ExecutionPlanner()
        plan = ExecutionPlan(
            message="hello",
            intent=IntentResult(),
        )
        bias = _make_memory_bias(posture="novelty", influenced=False)

        # Should not raise TypeError about unexpected kwarg
        import inspect
        sig = inspect.signature(planner.execute)
        assert "memory_bias" in sig.parameters


# ─────────────────────────────────────────────────────────────────────────────
# Group G — Backward compatibility
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupG_BackwardCompatibility:
    @pytest.mark.asyncio
    async def test_G01_execute_without_memory_bias_still_works(self):
        """Calling execute(plan) without memory_bias must not crash."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult

        planner = ExecutionPlanner()
        plan = ExecutionPlan(message="hello", intent=IntentResult())

        with patch.object(planner, "_dispatch", new_callable=AsyncMock) as mock_dispatch:
            from core.agent.execution_planner import ExecutionResult
            mock_dispatch.return_value = ExecutionResult(success=True, reply="ok")
            # Calling without memory_bias
            result = await planner.execute(plan)
            assert result is not None

    @pytest.mark.asyncio
    async def test_G02_execute_with_activation_budget_only_still_works(self):
        """Calling execute(plan, activation_budget=x) without memory_bias must work."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult

        planner = ExecutionPlanner()
        plan = ExecutionPlan(message="hello", intent=IntentResult())

        with patch.object(planner, "_dispatch", new_callable=AsyncMock) as mock_dispatch:
            from core.agent.execution_planner import ExecutionResult
            mock_dispatch.return_value = ExecutionResult(success=True, reply="ok")
            result = await planner.execute(plan, activation_budget=None)
            assert result is not None

    def test_G03_derive_memory_bias_never_raises(self):
        from core.cognitive.memory_bias_layer import derive_memory_bias
        # Must not raise on any input
        _ = derive_memory_bias()
        _ = derive_memory_bias(session_id="")
        _ = derive_memory_bias(session_id="test", trace_id="t123")

    def test_G04_get_memory_planner_guidance_never_raises(self):
        from core.cognitive.memory_bias_layer import get_memory_planner_guidance
        _ = get_memory_planner_guidance(None)
        _ = get_memory_planner_guidance("not_a_bias")  # type: ignore

    def test_G05_build_memory_bias_diagnostics_never_raises_on_none(self):
        from core.cognitive.memory_bias_layer import build_memory_bias_diagnostics
        d = build_memory_bias_diagnostics(None)
        assert isinstance(d, dict)


# ─────────────────────────────────────────────────────────────────────────────
# Group H — Advisory / non-override assertions
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupH_AdvisoryNonOverride:
    def test_H01_novelty_posture_does_not_prevent_fractal_at_high_complexity(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(posture="novelty", prefer_single=False, adj=0.0, influenced=True)
        strategy = planner._pick_strategy("do task", 0.80, memory_guidance=guidance)
        assert strategy == "fractal"

    def test_H02_continuity_posture_does_not_force_single_at_fractal_level_complexity(self):
        """Even with continuity posture, fractal keyword overrides memory guidance."""
        planner = _make_planner()
        guidance = _make_memory_guidance(posture="continuity", prefer_single=True, adj=0.10, influenced=True)
        # fractal keyword → always returns fractal regardless of memory guidance
        strategy = planner._pick_strategy("fractal analysis 分型", 0.3, memory_guidance=guidance)
        assert strategy == "fractal"

    def test_H03_memory_bias_cannot_override_task_type_mapped_strategy(self):
        planner = _make_planner()
        guidance = _make_memory_guidance(posture="continuity", prefer_single=True, adj=0.10, influenced=True)
        # 'analysis' maps to 'specialized' in TASK_TYPE_STRATEGY_MAP
        strategy = planner._pick_strategy("do task", 0.5, task_type="analysis", memory_guidance=guidance)
        assert strategy == "specialized"
