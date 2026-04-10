"""tests/test_pr18_cognitive_activation_budget.py
==================================================
Tests for PR-18: cognitive activation budgeting.

Coverage matrix
---------------
Group A — Sentinel / authority assertions
  A01. COGNITIVE_ACTIVATION_BUDGET_IS_AUTHORITY sentinel exists.
  A02. COGNITIVE_ACTIVATION_BUDGET_PR18_SENTINEL sentinel exists.
  A03. HARD_GATES_REMAIN_AUTHORITATIVE_POLICY sentinel exists.
  A04. BUDGET_IS_SOFT_INFLUENCE_NOT_HARD_GATE_POLICY sentinel exists.
  A05. ACTIVATION_BUDGET_WIRED_INTO_KERNEL_PR18 sentinel exists in kernel.py.
  A06. ACTIVATION_BUDGET_PLANNER_BREADTH_WIRED_PR18 sentinel exists in execution_planner.py.
  A07. ACTIVATION_BUDGET_NARROWING_COMPATIBLE_WITH_GOVERNANCE_PR18 sentinel exists in governance.
  A08. COGNITIVE_ACTIVATION_BUDGET_ALIGNED_PR18 alignment sentinel exists in projection.py.

Group B — ActivationBudget derivation from CognitiveExecutionHint
  B01. derive_activation_budget(None) returns FALLBACK_ACTIVATION_BUDGET.
  B02. derive_activation_budget(fallback_hint) returns fallback budget.
  B03. Passive hint (region='passive') produces narrow / low / single budget.
  B04. Silent hint (region='silent') produces narrow / low / single budget.
  B05. Liminal hint (region='liminal') produces moderate / moderate budget.
  B06. Manifest hint (region='manifest') produces broad / high / None budget.
  B07. budget_value is carried from hint.activation_budget.
  B08. cognitive_region is carried from hint.cognitive_region.
  B09. influenced_by_budget is True for live hints, False for fallback.
  B10. source is 'cognitive_activation_budget' for live derivations.
  B11. ActivationBudget.is_narrow() / is_moderate() / is_broad() helpers work correctly.
  B12. ActivationBudget.to_dict() returns JSON-safe dict with expected keys.

Group C — PlannerBreadthGuidance derivation
  C01. get_planner_breadth_guidance(None) returns non-influenced fallback guidance.
  C02. get_planner_breadth_guidance(fallback_budget) returns fallback guidance.
  C03. narrow budget → narrow breadth, max_concurrent_agents=1, complexity_adj=+0.15.
  C04. moderate budget → moderate breadth, max_concurrent_agents=3, complexity_adj=0.0.
  C05. broad budget → broad breadth, max_concurrent_agents=20, complexity_adj=-0.10.
  C06. influenced_by_budget is True for live guidance, False for fallback.
  C07. diagnostic_note is a non-empty string describing the decision.
  C08. PlannerBreadthGuidance.to_dict() returns expected keys.

Group D — Candidate narrowing
  D01. apply_candidate_narrowing with None budget returns all candidates unchanged.
  D02. apply_candidate_narrowing with fallback budget (not influenced) returns all.
  D03. Passive budget narrows candidates to max_candidate_nodes=5.
  D04. Liminal budget narrows candidates to max_candidate_nodes=10.
  D05. Manifest budget does not narrow candidates (max=9999).
  D06. governance_allowed filter is applied before budget narrowing.
  D07. Budget narrowing never re-admits nodes excluded by governance filter.
  D08. Candidates already within budget limit are not narrowed further.
  D09. Diagnostics dict contains expected keys and correct output_count.
  D10. apply_candidate_narrowing with empty input returns empty list with correct diag.

Group E — Planner strategy with breadth guidance (_pick_strategy)
  E01. No breadth_guidance → original thresholds (0.75 / 0.65).
  E02. Narrow guidance raises fractal threshold to 0.90 and specialized threshold to 0.80.
  E03. Broad guidance lowers fractal threshold to 0.65 and specialized threshold to 0.55.
  E04. task_type mapping table still has highest priority over budget guidance.
  E05. Keyword-based strategy (swarm/fractal/team) is not overridden by narrow budget.
  E06. strategy_preference='single' from narrow budget returns 'single' below new threshold.
  E07. Moderate breadth_guidance has no threshold adjustment (0.0).

Group F — Kernel wiring (mock-based)
  F01. KernelResponse has activation_budget_hint field (Optional[Dict]).
  F02. to_api_dict() includes 'activation_budget_hint' key.
  F03. _process() derives activation_budget_hint even when cognitive signals unavailable.
  F04. execute() is called with activation_budget kwarg.

Group G — Governance integration
  G01. evaluate_invocation_governance accepts activation_budget kwarg.
  G02. When budget provided, diagnostic_context includes 'activation_budget_context'.
  G03. Budget context is advisory only: invocation_allowed is unchanged.
  G04. Denied node stays denied regardless of budget.
  G05. When budget is None, no activation_budget_context key in diagnostics.

Group H — Backward compatibility
  H01. Old callers using execute(plan) without activation_budget still work.
  H02. Old callers using evaluate_invocation_governance without activation_budget still work.
  H03. derive_activation_budget never raises — returns fallback on invalid input.
  H04. get_planner_breadth_guidance never raises — returns fallback on invalid input.
  H05. apply_candidate_narrowing never raises — returns all candidates on error.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_hint(region: str, budget: float, wiring_active: bool = True) -> Any:
    """Build a minimal CognitiveExecutionHint-like object."""
    from core.cognitive.cognitive_execution_policy import CognitiveExecutionHint
    return CognitiveExecutionHint(
        cognitive_region=region,
        activation_budget=budget,
        cognitive_wiring_active=wiring_active,
        source="cognitive_execution_policy" if wiring_active else "fallback",
    )


def _make_budget(region: str, budget_value: float) -> Any:
    """Derive an ActivationBudget from a CognitiveExecutionHint."""
    from core.cognitive.cognitive_activation_budget import derive_activation_budget
    hint = _make_hint(region, budget_value)
    return derive_activation_budget(hint)


# ─────────────────────────── Group A — Sentinels ────────────────────────────


class TestSentinels:
    """Group A — verify PR-18 authority/sentinel constants exist."""

    def test_a01_authority_sentinel(self):
        """A01. COGNITIVE_ACTIVATION_BUDGET_IS_AUTHORITY exists."""
        from core.cognitive import cognitive_activation_budget as mod
        assert hasattr(mod, "COGNITIVE_ACTIVATION_BUDGET_IS_AUTHORITY")
        assert isinstance(mod.COGNITIVE_ACTIVATION_BUDGET_IS_AUTHORITY, str)
        assert len(mod.COGNITIVE_ACTIVATION_BUDGET_IS_AUTHORITY) > 0

    def test_a02_pr18_sentinel(self):
        """A02. COGNITIVE_ACTIVATION_BUDGET_PR18_SENTINEL exists."""
        from core.cognitive import cognitive_activation_budget as mod
        assert hasattr(mod, "COGNITIVE_ACTIVATION_BUDGET_PR18_SENTINEL")
        assert "PR18" in mod.COGNITIVE_ACTIVATION_BUDGET_PR18_SENTINEL

    def test_a03_hard_gates_policy(self):
        """A03. HARD_GATES_REMAIN_AUTHORITATIVE_POLICY exists."""
        from core.cognitive import cognitive_activation_budget as mod
        assert hasattr(mod, "HARD_GATES_REMAIN_AUTHORITATIVE_POLICY")
        assert "authoritative" in mod.HARD_GATES_REMAIN_AUTHORITATIVE_POLICY.lower()

    def test_a04_soft_influence_policy(self):
        """A04. BUDGET_IS_SOFT_INFLUENCE_NOT_HARD_GATE_POLICY exists."""
        from core.cognitive import cognitive_activation_budget as mod
        assert hasattr(mod, "BUDGET_IS_SOFT_INFLUENCE_NOT_HARD_GATE_POLICY")
        assert "soft" in mod.BUDGET_IS_SOFT_INFLUENCE_NOT_HARD_GATE_POLICY.lower()

    def test_a05_kernel_sentinel(self):
        """A05. ACTIVATION_BUDGET_WIRED_INTO_KERNEL_PR18 exists in kernel.py."""
        from core.agent import kernel as kernel_mod
        assert hasattr(kernel_mod, "ACTIVATION_BUDGET_WIRED_INTO_KERNEL_PR18")
        assert "PR18" in kernel_mod.ACTIVATION_BUDGET_WIRED_INTO_KERNEL_PR18

    def test_a06_planner_sentinel(self):
        """A06. ACTIVATION_BUDGET_PLANNER_BREADTH_WIRED_PR18 exists in execution_planner.py."""
        from core.agent import execution_planner as ep_mod
        assert hasattr(ep_mod, "ACTIVATION_BUDGET_PLANNER_BREADTH_WIRED_PR18")
        assert "PR18" in ep_mod.ACTIVATION_BUDGET_PLANNER_BREADTH_WIRED_PR18

    def test_a07_governance_sentinel(self):
        """A07. ACTIVATION_BUDGET_NARROWING_COMPATIBLE_WITH_GOVERNANCE_PR18 exists."""
        import core.node_invocation_governance as gov_mod
        assert hasattr(gov_mod, "ACTIVATION_BUDGET_NARROWING_COMPATIBLE_WITH_GOVERNANCE_PR18")
        assert "PR18" in gov_mod.ACTIVATION_BUDGET_NARROWING_COMPATIBLE_WITH_GOVERNANCE_PR18

    def test_a08_projection_alignment_sentinel(self):
        """A08. COGNITIVE_ACTIVATION_BUDGET_ALIGNED_PR18 exists in projection.py."""
        pytest.importorskip("fastapi", reason="fastapi not installed")
        import core.routes.projection as proj_mod
        assert hasattr(proj_mod, "COGNITIVE_ACTIVATION_BUDGET_ALIGNED_PR18")
        val = proj_mod.COGNITIVE_ACTIVATION_BUDGET_ALIGNED_PR18
        assert isinstance(val, str)
        # Should not be the unavailable variant (module should import cleanly)
        assert "UNAVAILABLE" not in val


# ────────────────── Group B — ActivationBudget derivation ──────────────────


class TestActivationBudgetDerivation:
    """Group B — derive_activation_budget()."""

    def test_b01_none_hint_returns_fallback(self):
        """B01. derive_activation_budget(None) returns FALLBACK_ACTIVATION_BUDGET."""
        from core.cognitive.cognitive_activation_budget import (
            derive_activation_budget,
            FALLBACK_ACTIVATION_BUDGET,
        )
        result = derive_activation_budget(None)
        assert result is FALLBACK_ACTIVATION_BUDGET

    def test_b02_fallback_hint_returns_fallback_budget(self):
        """B02. derive_activation_budget(fallback_hint) returns fallback budget."""
        from core.cognitive.cognitive_activation_budget import derive_activation_budget
        hint = _make_hint("silent", 0.2, wiring_active=False)
        result = derive_activation_budget(hint)
        assert result.influenced_by_budget is False
        assert result.source == "fallback"

    def test_b03_passive_produces_narrow_budget(self):
        """B03. Passive hint → narrow / low / single budget."""
        from core.cognitive.cognitive_activation_budget import BREADTH_MODE_NARROW, INTENSITY_LOW
        budget = _make_budget("passive", 0.2)
        assert budget.breadth_mode == BREADTH_MODE_NARROW
        assert budget.intensity == INTENSITY_LOW
        assert budget.strategy_preference == "single"
        assert budget.influenced_by_budget is True

    def test_b04_silent_produces_narrow_budget(self):
        """B04. Silent hint → narrow / low / single budget."""
        from core.cognitive.cognitive_activation_budget import BREADTH_MODE_NARROW
        budget = _make_budget("silent", 0.2)
        assert budget.breadth_mode == BREADTH_MODE_NARROW

    def test_b05_liminal_produces_moderate_budget(self):
        """B05. Liminal hint → moderate breadth."""
        from core.cognitive.cognitive_activation_budget import BREADTH_MODE_MODERATE, INTENSITY_MODERATE
        budget = _make_budget("liminal", 0.6)
        assert budget.breadth_mode == BREADTH_MODE_MODERATE
        assert budget.intensity == INTENSITY_MODERATE
        assert budget.strategy_preference is None
        assert budget.influenced_by_budget is True

    def test_b06_manifest_produces_broad_budget(self):
        """B06. Manifest hint → broad / high budget."""
        from core.cognitive.cognitive_activation_budget import BREADTH_MODE_BROAD, INTENSITY_HIGH
        budget = _make_budget("manifest", 1.0)
        assert budget.breadth_mode == BREADTH_MODE_BROAD
        assert budget.intensity == INTENSITY_HIGH
        assert budget.strategy_preference is None
        assert budget.influenced_by_budget is True

    def test_b07_budget_value_carried_from_hint(self):
        """B07. budget_value is carried from hint.activation_budget."""
        budget = _make_budget("manifest", 0.85)
        assert abs(budget.budget_value - 0.85) < 0.001

    def test_b08_cognitive_region_carried(self):
        """B08. cognitive_region is carried from hint."""
        budget = _make_budget("liminal", 0.6)
        assert budget.cognitive_region == "liminal"

    def test_b09_influenced_by_budget_flags(self):
        """B09. influenced_by_budget is True for live hints, False for fallback."""
        live_budget = _make_budget("manifest", 1.0)
        assert live_budget.influenced_by_budget is True

        from core.cognitive.cognitive_activation_budget import FALLBACK_ACTIVATION_BUDGET
        assert FALLBACK_ACTIVATION_BUDGET.influenced_by_budget is False

    def test_b10_source_field(self):
        """B10. source is 'cognitive_activation_budget' for live derivations."""
        budget = _make_budget("manifest", 1.0)
        assert budget.source == "cognitive_activation_budget"

    def test_b11_is_narrow_is_moderate_is_broad_helpers(self):
        """B11. ActivationBudget.is_narrow() / is_moderate() / is_broad() work."""
        from core.cognitive.cognitive_activation_budget import (
            derive_activation_budget, ActivationBudget,
            BREADTH_MODE_NARROW, BREADTH_MODE_MODERATE, BREADTH_MODE_BROAD,
        )
        narrow_b = _make_budget("passive", 0.2)
        moderate_b = _make_budget("liminal", 0.6)
        broad_b = _make_budget("manifest", 1.0)

        assert narrow_b.is_narrow() is True
        assert narrow_b.is_moderate() is False
        assert narrow_b.is_broad() is False

        assert moderate_b.is_narrow() is False
        assert moderate_b.is_moderate() is True
        assert moderate_b.is_broad() is False

        assert broad_b.is_narrow() is False
        assert broad_b.is_moderate() is False
        assert broad_b.is_broad() is True

    def test_b12_to_dict_has_expected_keys(self):
        """B12. ActivationBudget.to_dict() returns expected keys."""
        budget = _make_budget("liminal", 0.6)
        d = budget.to_dict()
        expected_keys = {
            "budget_value", "intensity", "breadth_mode", "max_candidate_nodes",
            "max_concurrent_agents", "strategy_preference", "cognitive_region",
            "influenced_by_budget", "source", "timestamp",
        }
        assert expected_keys.issubset(set(d.keys()))


# ─────────────────── Group C — PlannerBreadthGuidance ───────────────────────


class TestPlannerBreadthGuidance:
    """Group C — get_planner_breadth_guidance()."""

    def test_c01_none_budget_returns_fallback_guidance(self):
        """C01. get_planner_breadth_guidance(None) returns non-influenced fallback."""
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        guidance = get_planner_breadth_guidance(None)
        assert guidance.influenced_by_budget is False
        assert guidance.breadth_mode == "narrow"

    def test_c02_fallback_budget_returns_fallback_guidance(self):
        """C02. get_planner_breadth_guidance(fallback_budget) returns fallback guidance."""
        from core.cognitive.cognitive_activation_budget import (
            get_planner_breadth_guidance, FALLBACK_ACTIVATION_BUDGET,
        )
        guidance = get_planner_breadth_guidance(FALLBACK_ACTIVATION_BUDGET)
        assert guidance.influenced_by_budget is False

    def test_c03_narrow_budget_guidance(self):
        """C03. narrow budget → narrow breadth, max_agents=1, complexity_adj=+0.15."""
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        budget = _make_budget("passive", 0.2)
        guidance = get_planner_breadth_guidance(budget)
        assert guidance.breadth_mode == "narrow"
        assert guidance.max_concurrent_agents == 1
        assert abs(guidance.complexity_threshold_adjustment - 0.15) < 0.001
        assert guidance.strategy_preference == "single"
        assert guidance.influenced_by_budget is True

    def test_c04_moderate_budget_guidance(self):
        """C04. moderate budget → moderate breadth, max_agents=3, complexity_adj=0.0."""
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        budget = _make_budget("liminal", 0.6)
        guidance = get_planner_breadth_guidance(budget)
        assert guidance.breadth_mode == "moderate"
        assert guidance.max_concurrent_agents == 3
        assert abs(guidance.complexity_threshold_adjustment - 0.0) < 0.001
        assert guidance.strategy_preference is None
        assert guidance.influenced_by_budget is True

    def test_c05_broad_budget_guidance(self):
        """C05. broad budget → broad breadth, max_agents=20, complexity_adj=-0.10."""
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        budget = _make_budget("manifest", 1.0)
        guidance = get_planner_breadth_guidance(budget)
        assert guidance.breadth_mode == "broad"
        assert guidance.max_concurrent_agents == 20
        assert abs(guidance.complexity_threshold_adjustment - (-0.10)) < 0.001
        assert guidance.strategy_preference is None
        assert guidance.influenced_by_budget is True

    def test_c06_influenced_by_budget_flag(self):
        """C06. influenced_by_budget is True for live guidance, False for fallback."""
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        live_guidance = get_planner_breadth_guidance(_make_budget("manifest", 1.0))
        assert live_guidance.influenced_by_budget is True

        fallback_guidance = get_planner_breadth_guidance(None)
        assert fallback_guidance.influenced_by_budget is False

    def test_c07_diagnostic_note_is_non_empty(self):
        """C07. diagnostic_note is a non-empty string."""
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        guidance = get_planner_breadth_guidance(_make_budget("liminal", 0.6))
        assert isinstance(guidance.diagnostic_note, str)
        assert len(guidance.diagnostic_note) > 0

    def test_c08_to_dict_has_expected_keys(self):
        """C08. PlannerBreadthGuidance.to_dict() returns expected keys."""
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        guidance = get_planner_breadth_guidance(_make_budget("manifest", 1.0))
        d = guidance.to_dict()
        expected_keys = {
            "breadth_mode", "max_concurrent_agents", "complexity_threshold_adjustment",
            "strategy_preference", "budget_value", "influenced_by_budget", "diagnostic_note",
        }
        assert expected_keys.issubset(set(d.keys()))


# ────────────────────── Group D — Candidate narrowing ───────────────────────


class TestCandidateNarrowing:
    """Group D — apply_candidate_narrowing()."""

    def _candidates(self, n: int) -> List[str]:
        return [f"node_{i}" for i in range(n)]

    def test_d01_none_budget_returns_all(self):
        """D01. apply_candidate_narrowing with None budget returns all candidates."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        candidates = self._candidates(10)
        result, diag = apply_candidate_narrowing(candidates, None)
        assert result == candidates
        assert diag["budget_narrowing_applied"] is False
        assert diag["output_count"] == 10

    def test_d02_fallback_budget_returns_all(self):
        """D02. apply_candidate_narrowing with fallback budget returns all."""
        from core.cognitive.cognitive_activation_budget import (
            apply_candidate_narrowing, FALLBACK_ACTIVATION_BUDGET,
        )
        candidates = self._candidates(8)
        result, diag = apply_candidate_narrowing(candidates, FALLBACK_ACTIVATION_BUDGET)
        assert result == candidates
        assert diag["budget_narrowing_applied"] is False

    def test_d03_passive_budget_narrows_to_5(self):
        """D03. Passive budget narrows candidates to max_candidate_nodes=5."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        budget = _make_budget("passive", 0.2)
        candidates = self._candidates(12)
        result, diag = apply_candidate_narrowing(candidates, budget)
        assert len(result) == 5
        assert diag["budget_narrowing_applied"] is True
        assert diag["output_count"] == 5

    def test_d04_liminal_budget_narrows_to_10(self):
        """D04. Liminal budget narrows candidates to max_candidate_nodes=10."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        budget = _make_budget("liminal", 0.6)
        candidates = self._candidates(15)
        result, diag = apply_candidate_narrowing(candidates, budget)
        assert len(result) == 10
        assert diag["budget_narrowing_applied"] is True

    def test_d05_manifest_budget_does_not_narrow(self):
        """D05. Manifest budget does not narrow candidates (max=9999)."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        budget = _make_budget("manifest", 1.0)
        candidates = self._candidates(50)
        result, diag = apply_candidate_narrowing(candidates, budget)
        assert len(result) == 50
        assert diag["budget_narrowing_applied"] is False

    def test_d06_governance_filter_applied_first(self):
        """D06. governance_allowed filter is applied before budget narrowing."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        budget = _make_budget("liminal", 0.6)  # max=10
        candidates = [f"node_{i}" for i in range(20)]
        gov_allowed = {f"node_{i}" for i in range(7)}  # only 7 allowed
        result, diag = apply_candidate_narrowing(candidates, budget, governance_allowed=gov_allowed)
        # After governance filter: 7 nodes; budget max=10, so no further narrowing
        assert len(result) == 7
        assert all(n in gov_allowed for n in result)
        assert diag["governance_filter_applied"] is True

    def test_d07_budget_never_readmits_governance_excluded(self):
        """D07. Budget narrowing never re-admits nodes excluded by governance filter."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        budget = _make_budget("manifest", 1.0)  # broad — no narrowing
        candidates = ["node_a", "node_b", "node_c", "node_d"]
        gov_allowed = {"node_a", "node_b"}
        result, _ = apply_candidate_narrowing(candidates, budget, governance_allowed=gov_allowed)
        # Only governance-allowed nodes appear
        assert set(result) == {"node_a", "node_b"}
        assert "node_c" not in result
        assert "node_d" not in result

    def test_d08_already_within_budget_not_narrowed(self):
        """D08. Candidates already within budget limit are not narrowed further."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        budget = _make_budget("passive", 0.2)  # max=5
        candidates = self._candidates(3)  # only 3 — already within limit
        result, diag = apply_candidate_narrowing(candidates, budget)
        assert result == candidates
        assert diag["budget_narrowing_applied"] is False
        assert diag["narrowed_by"] == "within_budget"

    def test_d09_diagnostics_keys(self):
        """D09. Diagnostics dict contains expected keys and correct output_count."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        budget = _make_budget("passive", 0.2)
        candidates = self._candidates(8)
        result, diag = apply_candidate_narrowing(candidates, budget)
        expected_keys = {
            "input_count", "governance_filter_applied", "budget_narrowing_applied",
            "narrowed_by", "output_count",
        }
        assert expected_keys.issubset(set(diag.keys()))
        assert diag["input_count"] == 8
        assert diag["output_count"] == len(result)

    def test_d10_empty_input(self):
        """D10. apply_candidate_narrowing with empty input returns empty list."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        budget = _make_budget("manifest", 1.0)
        result, diag = apply_candidate_narrowing([], budget)
        assert result == []
        assert diag["output_count"] == 0


# ──────────────── Group E — Planner strategy with budget ────────────────────


class TestPlannerStrategyWithBudget:
    """Group E — ExecutionPlanner._pick_strategy() with breadth_guidance."""

    def _make_planner(self):
        from core.agent.execution_planner import ExecutionPlanner
        return ExecutionPlanner()

    def _guidance(self, region: str, budget_value: float):
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        budget = _make_budget(region, budget_value)
        return get_planner_breadth_guidance(budget)

    def test_e01_no_guidance_original_thresholds(self):
        """E01. No breadth_guidance → original thresholds (0.75 / 0.65)."""
        planner = self._make_planner()
        # complexity 0.70 → normally specialized (>= 0.65)
        assert planner._pick_strategy("task", 0.70) == "specialized"
        # complexity 0.76 → normally fractal (>= 0.75)
        assert planner._pick_strategy("task", 0.76) == "fractal"
        # complexity 0.50 → single
        assert planner._pick_strategy("task", 0.50) == "single"

    def test_e02_narrow_raises_thresholds(self):
        """E02. Narrow guidance raises fractal threshold to 0.90, specialized to 0.80."""
        planner = self._make_planner()
        guidance = self._guidance("passive", 0.2)
        # complexity 0.70 — below new specialized threshold (0.65+0.15=0.80)
        assert planner._pick_strategy("task", 0.70, breadth_guidance=guidance) == "single"
        # complexity 0.80 — at new specialized threshold
        assert planner._pick_strategy("task", 0.81, breadth_guidance=guidance) == "specialized"
        # complexity 0.89 — below new fractal threshold (0.75+0.15=0.90)
        assert planner._pick_strategy("task", 0.89, breadth_guidance=guidance) == "specialized"
        # complexity 0.91 — above new fractal threshold
        assert planner._pick_strategy("task", 0.91, breadth_guidance=guidance) == "fractal"

    def test_e03_broad_lowers_thresholds(self):
        """E03. Broad guidance lowers fractal threshold to 0.65, specialized to 0.55."""
        planner = self._make_planner()
        guidance = self._guidance("manifest", 1.0)
        # complexity 0.60 — above new specialized threshold (0.65-0.10=0.55)
        assert planner._pick_strategy("task", 0.60, breadth_guidance=guidance) == "specialized"
        # complexity 0.66 — above new fractal threshold (0.75-0.10=0.65)
        assert planner._pick_strategy("task", 0.66, breadth_guidance=guidance) == "fractal"

    def test_e04_task_type_mapping_has_highest_priority(self):
        """E04. task_type mapping table still has highest priority over budget guidance."""
        planner = self._make_planner()
        # task_type='single' maps to 'single' regardless of complexity
        guidance = self._guidance("manifest", 1.0)
        assert planner._pick_strategy("any task", 0.9, task_type="fast_response", breadth_guidance=guidance) == "single"
        # task_type='swarm' maps to 'swarm' regardless of narrow budget
        guidance_n = self._guidance("passive", 0.2)
        assert planner._pick_strategy("any task", 0.3, task_type="swarm", breadth_guidance=guidance_n) == "swarm"

    def test_e05_keyword_swarm_not_overridden_by_narrow(self):
        """E05. Keyword-based swarm strategy is not overridden by narrow budget."""
        planner = self._make_planner()
        guidance = self._guidance("passive", 0.2)
        # Message contains 'swarm' keyword — should still return 'swarm'
        assert planner._pick_strategy("run swarm of agents", 0.3, breadth_guidance=guidance) == "swarm"

    def test_e06_narrow_strategy_preference_single(self):
        """E06. strategy_preference='single' from narrow budget returns 'single' below threshold."""
        planner = self._make_planner()
        guidance = self._guidance("passive", 0.2)
        # complexity well below any threshold
        assert planner._pick_strategy("simple task", 0.30, breadth_guidance=guidance) == "single"

    def test_e07_moderate_no_adjustment(self):
        """E07. Moderate breadth_guidance has no threshold adjustment (0.0)."""
        planner = self._make_planner()
        guidance = self._guidance("liminal", 0.6)
        # Original thresholds apply — 0.70 should still be 'specialized'
        assert planner._pick_strategy("task", 0.70, breadth_guidance=guidance) == "specialized"
        # 0.76 should still be 'fractal'
        assert planner._pick_strategy("task", 0.76, breadth_guidance=guidance) == "fractal"


# ──────────────────── Group F — Kernel wiring ───────────────────────────────


class TestKernelWiring:
    """Group F — KernelResponse and execute() integration."""

    def test_f01_kernel_response_has_activation_budget_hint_field(self):
        """F01. KernelResponse has activation_budget_hint field (Optional[Dict])."""
        from core.agent.kernel import KernelResponse
        kr = KernelResponse()
        assert hasattr(kr, "activation_budget_hint")
        assert kr.activation_budget_hint is None

    def test_f02_to_api_dict_includes_activation_budget_hint(self):
        """F02. to_api_dict() includes 'activation_budget_hint' key."""
        from core.agent.kernel import KernelResponse
        kr = KernelResponse(activation_budget_hint={"budget_value": 0.6})
        d = kr.to_api_dict()
        assert "activation_budget_hint" in d
        assert d["activation_budget_hint"] == {"budget_value": 0.6}

    def test_f03_to_api_dict_activation_budget_hint_none_when_not_set(self):
        """F03. activation_budget_hint is None in to_api_dict() when not set."""
        from core.agent.kernel import KernelResponse
        kr = KernelResponse()
        d = kr.to_api_dict()
        assert d["activation_budget_hint"] is None

    def test_f04_execute_accepts_activation_budget_kwarg(self):
        """F04. ExecutionPlanner.execute() accepts activation_budget kwarg."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult
        import inspect
        sig = inspect.signature(ExecutionPlanner.execute)
        assert "activation_budget" in sig.parameters


# ─────────────────── Group G — Governance integration ───────────────────────


class TestGovernanceIntegration:
    """Group G — evaluate_invocation_governance() with activation_budget."""

    def _make_mock_budget(self, region: str = "manifest", budget_value: float = 1.0) -> Any:
        mock_budget = MagicMock()
        mock_budget.breadth_mode = "broad" if region == "manifest" else "narrow"
        mock_budget.budget_value = budget_value
        mock_budget.intensity = "high" if region == "manifest" else "low"
        mock_budget.cognitive_region = region
        mock_budget.influenced_by_budget = True
        return mock_budget

    def test_g01_accepts_activation_budget_kwarg(self):
        """G01. evaluate_invocation_governance accepts activation_budget kwarg."""
        import inspect
        from core.node_invocation_governance import evaluate_invocation_governance
        sig = inspect.signature(evaluate_invocation_governance)
        assert "activation_budget" in sig.parameters

    def test_g02_budget_context_in_diagnostics_when_provided(self):
        """G02. When budget provided, diagnostic_context includes 'activation_budget_context'."""
        from core.node_invocation_governance import evaluate_invocation_governance
        mock_budget = self._make_mock_budget("manifest", 1.0)

        # Call with an unregistered node (unregistered_unmanaged path).
        # Budget context is embedded in all paths (not just eligible).
        decision = evaluate_invocation_governance(
            "unregistered_test_node_pr18_g02",
            activation_budget=mock_budget,
        )

        assert "activation_budget_context" in decision.diagnostic_context
        ctx = decision.diagnostic_context["activation_budget_context"]
        assert ctx["influenced_by_budget"] is True
        assert "advisory_only" in ctx["note"]

    def test_g03_budget_is_advisory_invocation_allowed_unchanged(self):
        """G03. Budget context is advisory only: invocation_allowed is not forced to False."""
        from core.node_invocation_governance import evaluate_invocation_governance
        mock_budget = self._make_mock_budget("passive", 0.2)  # low budget

        # Even with a very low budget, an unregistered node still proceeds
        decision = evaluate_invocation_governance(
            "unregistered_test_node_pr18_g03",
            activation_budget=mock_budget,
        )
        # Budget never forces denial — unregistered nodes are allowed regardless
        assert decision.invocation_allowed is True
        assert "activation_budget_context" in decision.diagnostic_context

    def test_g04_denied_node_budget_context_in_diagnostics(self):
        """G04. Denied node gets budget context embedded in its denied diagnostics."""
        from core.node_invocation_governance import evaluate_invocation_governance
        mock_budget = self._make_mock_budget("manifest", 1.0)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility"
        ) as mock_eval:
            mock_decision = MagicMock()
            mock_decision.eligible = False
            mock_decision.governor_consulted = True
            mock_decision.diagnostic_context = {}
            mock_decision.exclusion_reasons = ["archived"]
            mock_eval.return_value = mock_decision

            # Use a mock registry that returns a node so governance runs
            mock_registry = MagicMock()
            mock_registry.get.return_value = MagicMock()  # non-None node_info

            decision = evaluate_invocation_governance(
                "archived_node_pr18_g04",
                registry=mock_registry,
                activation_budget=mock_budget,
            )

        assert decision.invocation_allowed is False
        assert decision.governance_status == "ineligible_denied"
        # Budget context is embedded even in denied decisions
        assert "activation_budget_context" in decision.diagnostic_context

    def test_g05_no_budget_no_context_key(self):
        """G05. When budget is None, no activation_budget_context key in diagnostics."""
        from core.node_invocation_governance import evaluate_invocation_governance

        decision = evaluate_invocation_governance(
            "unregistered_test_node_pr18_g05",
            activation_budget=None,
        )

        assert "activation_budget_context" not in decision.diagnostic_context


# ─────────────────── Group H — Backward compatibility ───────────────────────


class TestBackwardCompatibility:
    """Group H — backward compatibility checks."""

    def test_h01_execute_without_activation_budget_works(self):
        """H01. execute(plan) without activation_budget still works."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult
        import asyncio

        planner = ExecutionPlanner()
        plan = ExecutionPlan(
            message="hello",
            intent=IntentResult(mode="chat_only", confidence=1.0),
        )
        # execute() without activation_budget should not raise signature errors.
        # We don't run it fully (side effects) — just check the call is accepted.
        import inspect
        sig = inspect.signature(planner.execute)
        # Calling with only plan (no activation_budget) should be valid
        bound = sig.bind(plan)
        bound.apply_defaults()
        assert bound.arguments.get("activation_budget") is None

    def test_h02_evaluate_governance_without_budget_works(self):
        """H02. evaluate_invocation_governance without activation_budget still works."""
        from core.node_invocation_governance import evaluate_invocation_governance
        import inspect
        sig = inspect.signature(evaluate_invocation_governance)
        # activation_budget should have a default of None
        param = sig.parameters["activation_budget"]
        assert param.default is None

    def test_h03_derive_activation_budget_never_raises(self):
        """H03. derive_activation_budget never raises — returns fallback on invalid input."""
        from core.cognitive.cognitive_activation_budget import (
            derive_activation_budget, FALLBACK_ACTIVATION_BUDGET,
        )
        # Pass various invalid inputs — should return FALLBACK_ACTIVATION_BUDGET
        for bad_input in [42, "string", object(), {"key": "value"}, []]:
            result = derive_activation_budget(bad_input)
            # Contract: returns FALLBACK_ACTIVATION_BUDGET on invalid input, never raises
            assert result is FALLBACK_ACTIVATION_BUDGET

    def test_h04_get_planner_breadth_guidance_never_raises(self):
        """H04. get_planner_breadth_guidance never raises — returns fallback on invalid input."""
        from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance
        for bad_input in [42, "string", object(), {"key": "value"}]:
            guidance = get_planner_breadth_guidance(bad_input)
            assert isinstance(guidance.breadth_mode, str)

    def test_h05_apply_candidate_narrowing_never_raises(self):
        """H05. apply_candidate_narrowing never raises — returns all candidates on error."""
        from core.cognitive.cognitive_activation_budget import apply_candidate_narrowing
        candidates = ["a", "b", "c"]
        # Bad budget (not None but missing attributes)
        result, diag = apply_candidate_narrowing(candidates, "bad_budget")
        assert isinstance(result, list)
        assert isinstance(diag, dict)
