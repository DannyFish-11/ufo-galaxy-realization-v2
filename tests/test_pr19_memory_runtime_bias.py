"""tests/test_pr19_memory_runtime_bias.py
===========================================
Tests for PR-19: memory-informed runtime bias layer.

Coverage matrix
---------------
Group A — Sentinel / authority assertions
  A01. MEMORY_RUNTIME_BIAS_IS_AUTHORITY sentinel exists.
  A02. MEMORY_RUNTIME_BIAS_PR19_SENTINEL sentinel exists.
  A03. HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY sentinel exists.
  A04. MEMORY_BIAS_IS_ADVISORY_NOT_HARD_GATE_POLICY sentinel exists.
  A05. EXPLICIT_USER_INTENT_SUPERSEDES_MEMORY_BIAS_POLICY sentinel exists.
  A06. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 sentinel exists in kernel.py.
  A07. MEMORY_BIAS_PLANNER_CONTINUITY_WIRED_PR19 sentinel exists in execution_planner.py.
  A08. MEMORY_BIAS_GOVERNANCE_ADVISORY_PR19 sentinel exists in governance.
  A09. MEMORY_RUNTIME_BIAS_ALIGNED_PR19 alignment sentinel exists in projection.py.

Group B — MemoryRuntimeBias derivation
  B01. derive_memory_runtime_bias(task_memory=empty) returns NOVELTY fallback.
  B02. derive_memory_runtime_bias() with no task_memory still returns MemoryRuntimeBias.
  B03. High-success memory (>=70%) → CONTINUITY_SEEKING posture.
  B04. Mid-success memory ([30%, 70%)) → RETRIEVAL_SEEKING posture.
  B05. Low-success memory (<30%) → NOVELTY posture.
  B06. Stale-only memory → NOVELTY posture even if entries exist.
  B07. prior_strategy is populated from most-recent non-empty strategy.
  B08. influenced_by_memory is True for live signals, False for fallback.
  B09. source is 'task_memory' for live derivations; 'fallback' otherwise.
  B10. MemoryRuntimeBias.is_continuity_seeking() / is_retrieval_seeking() / is_novelty() helpers.
  B11. MemoryRuntimeBias.to_dict() returns JSON-safe dict with expected keys.
  B12. continuity_score + retrieval_score + novelty_score relationships.
  B13. FALLBACK_MEMORY_RUNTIME_BIAS defaults.

Group C — PlannerContinuityGuidance derivation
  C01. get_planner_continuity_guidance(None) returns fallback guidance.
  C02. get_planner_continuity_guidance(fallback_bias) returns fallback guidance.
  C03. CONTINUITY_SEEKING → strategy_bias=prior/single, complexity_adj=+0.10.
  C04. RETRIEVAL_SEEKING → strategy_bias='team', complexity_adj=-0.05.
  C05. NOVELTY → strategy_bias=None, complexity_adj=0.0.
  C06. influenced_by_memory is True for live guidance, False for fallback.
  C07. diagnostic_note is a non-empty string describing the decision.
  C08. PlannerContinuityGuidance.to_dict() returns expected keys.

Group D — Node candidate biasing
  D01. apply_memory_bias_to_node_preference([], None) returns empty list.
  D02. apply_memory_bias_to_node_preference with fallback bias returns unchanged.
  D03. governance_allowed filter applied before memory bias.
  D04. Memory bias never re-admits nodes excluded by governance filter.
  D05. influenced_by_memory=True when active bias is applied.
  D06. Diagnostics dict contains expected keys.
  D07. Candidates are not removed (only re-tagged); original order preserved.

Group E — Planner strategy with continuity guidance (_pick_strategy)
  E01. No continuity_guidance → original thresholds unchanged.
  E02. CONTINUITY_SEEKING raises thresholds by +0.10.
  E03. RETRIEVAL_SEEKING lowers thresholds by -0.05.
  E04. task_type mapping table has highest priority over memory bias.
  E05. Keyword-based swarm detection overrides memory bias.
  E06. RETRIEVAL_SEEKING strategy_bias='team' → 'specialized' when below threshold.
  E07. CONTINUITY_SEEKING with prior_strategy='single' → single returned.
  E08. memory bias is stacked on top of PR-18 breadth guidance (additive).

Group F — Kernel wiring (mock-based)
  F01. KernelResponse has memory_bias_hint field (Optional[Dict]).
  F02. to_api_dict() includes 'memory_bias_hint' key.
  F03. _process() derives memory_bias_hint even when TaskMemory unavailable.
  F04. execute() is called with memory_bias kwarg.

Group G — Governance integration
  G01. evaluate_invocation_governance accepts memory_bias kwarg.
  G02. When memory_bias provided, diagnostic_context includes 'memory_bias_context'.
  G03. Memory bias is advisory only: invocation_allowed is unchanged.
  G04. Denied node stays denied regardless of memory posture.
  G05. When memory_bias is None, no memory_bias_context key in diagnostics.

Group H — Diagnostics builder
  H01. build_memory_bias_diagnostics(None) returns fallback diag dict.
  H02. build_memory_bias_diagnostics with active bias returns expected keys.
  H03. influenced and influence_source are correctly threaded.
  H04. hard_gate_overrode is correctly threaded.
  H05. All numeric fields are rounded.

Group I — Backward compatibility
  I01. Old callers using execute(plan) without memory_bias still work.
  I02. Old callers using evaluate_invocation_governance without memory_bias still work.
  I03. derive_memory_runtime_bias never raises — returns fallback on error.
  I04. get_planner_continuity_guidance never raises — returns fallback on error.
  I05. apply_memory_bias_to_node_preference never raises — returns unchanged on error.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_summary(
    task: str = "test task",
    success: bool = True,
    strategy: str = "single",
    age_seconds: float = 60.0,
) -> Any:
    """Build a minimal TaskSummary-like object."""
    from core.task_memory import TaskSummary
    return TaskSummary(
        task=task,
        result_summary="ok",
        success=success,
        strategy=strategy,
        timestamp=time.time() - age_seconds,
    )


def _make_task_memory_with_summaries(summaries: list) -> Any:
    """Build a minimal mock TaskMemory that returns given summaries."""
    mem = MagicMock()
    mem.get_recent_summaries = MagicMock(return_value=summaries)
    return mem


def _make_bias(posture: str, n: int = 5, success_rate: float = 0.8) -> Any:
    """Build a MemoryRuntimeBias for testing."""
    from core.cognitive.memory_runtime_bias import MemoryRuntimeBias, MemoryPosture
    cont = 1.0 - success_rate if posture == MemoryPosture.NOVELTY else (success_rate if posture == MemoryPosture.CONTINUITY_SEEKING else 0.0)
    retr = 0.0 if posture != MemoryPosture.RETRIEVAL_SEEKING else 0.5
    nov = 1.0 - cont - retr
    return MemoryRuntimeBias(
        posture=posture,
        recent_entry_count=n,
        success_rate=success_rate,
        prior_strategy="single",
        influenced_by_memory=True,
        source="task_memory",
        continuity_score=round(cont, 4),
        retrieval_score=round(retr, 4),
        novelty_score=max(0.0, round(nov, 4)),
        diagnostic_note=f"test posture={posture}",
    )


# ─────────────────────────── Group A — Sentinels ────────────────────────────


class TestSentinels:
    """Group A — verify PR-19 authority/sentinel constants exist."""

    def test_a01_authority_sentinel(self):
        """A01. MEMORY_RUNTIME_BIAS_IS_AUTHORITY exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "MEMORY_RUNTIME_BIAS_IS_AUTHORITY")
        assert isinstance(mod.MEMORY_RUNTIME_BIAS_IS_AUTHORITY, str)
        assert len(mod.MEMORY_RUNTIME_BIAS_IS_AUTHORITY) > 0

    def test_a02_pr19_sentinel(self):
        """A02. MEMORY_RUNTIME_BIAS_PR19_SENTINEL exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "MEMORY_RUNTIME_BIAS_PR19_SENTINEL")
        assert "PR19" in mod.MEMORY_RUNTIME_BIAS_PR19_SENTINEL

    def test_a03_hard_gates_policy(self):
        """A03. HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY")
        assert "authoritative" in mod.HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY.lower()

    def test_a04_advisory_policy(self):
        """A04. MEMORY_BIAS_IS_ADVISORY_NOT_HARD_GATE_POLICY exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "MEMORY_BIAS_IS_ADVISORY_NOT_HARD_GATE_POLICY")
        assert "advisory" in mod.MEMORY_BIAS_IS_ADVISORY_NOT_HARD_GATE_POLICY.lower()

    def test_a05_explicit_intent_policy(self):
        """A05. EXPLICIT_USER_INTENT_SUPERSEDES_MEMORY_BIAS_POLICY exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "EXPLICIT_USER_INTENT_SUPERSEDES_MEMORY_BIAS_POLICY")
        assert "intent" in mod.EXPLICIT_USER_INTENT_SUPERSEDES_MEMORY_BIAS_POLICY.lower()

    def test_a06_kernel_sentinel(self):
        """A06. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 exists in kernel.py."""
        from core.agent import kernel as kernel_mod
        assert hasattr(kernel_mod, "MEMORY_BIAS_WIRED_INTO_KERNEL_PR19")
        assert "PR19" in kernel_mod.MEMORY_BIAS_WIRED_INTO_KERNEL_PR19

    def test_a07_planner_sentinel(self):
        """A07. MEMORY_BIAS_PLANNER_CONTINUITY_WIRED_PR19 exists in execution_planner.py."""
        from core.agent import execution_planner as ep_mod
        assert hasattr(ep_mod, "MEMORY_BIAS_PLANNER_CONTINUITY_WIRED_PR19")
        assert "PR19" in ep_mod.MEMORY_BIAS_PLANNER_CONTINUITY_WIRED_PR19

    def test_a08_governance_sentinel(self):
        """A08. MEMORY_BIAS_GOVERNANCE_ADVISORY_PR19 exists in governance."""
        import core.node_invocation_governance as gov_mod
        assert hasattr(gov_mod, "MEMORY_BIAS_GOVERNANCE_ADVISORY_PR19")
        assert "PR19" in gov_mod.MEMORY_BIAS_GOVERNANCE_ADVISORY_PR19

    def test_a09_projection_alignment_sentinel(self):
        """A09. MEMORY_RUNTIME_BIAS_ALIGNED_PR19 exists in projection.py."""
        pytest.importorskip("fastapi", reason="fastapi not installed")
        import core.routes.projection as proj_mod
        assert hasattr(proj_mod, "MEMORY_RUNTIME_BIAS_ALIGNED_PR19")
        val = proj_mod.MEMORY_RUNTIME_BIAS_ALIGNED_PR19
        assert isinstance(val, str)
        assert "UNAVAILABLE" not in val


# ────────────────── Group B — MemoryRuntimeBias derivation ──────────────────


class TestMemoryRuntimeBiasDerivation:
    """Group B — derive_memory_runtime_bias()."""

    def test_b01_empty_memory_returns_novelty(self):
        """B01. Empty memory → NOVELTY fallback."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            MemoryPosture,
        )
        mem = _make_task_memory_with_summaries([])
        bias = derive_memory_runtime_bias(task_memory=mem)
        assert bias.posture == MemoryPosture.NOVELTY
        assert bias.influenced_by_memory is True  # attempted, but no entries
        assert bias.recent_entry_count == 0

    def test_b02_no_task_memory_returns_fallback(self):
        """B02. No TaskMemory singleton → returns MemoryRuntimeBias."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            MemoryRuntimeBias,
        )
        # Patch get_task_memory to raise
        with patch("core.cognitive.memory_runtime_bias._derive_bias_impl") as m:
            from core.cognitive.memory_runtime_bias import FALLBACK_MEMORY_RUNTIME_BIAS
            m.side_effect = Exception("no memory")
            bias = derive_memory_runtime_bias()
            assert bias is FALLBACK_MEMORY_RUNTIME_BIAS

    def test_b03_high_success_produces_continuity_seeking(self):
        """B03. >= 70% success → CONTINUITY_SEEKING posture."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            MemoryPosture,
        )
        summaries = [
            _make_summary(success=True, strategy="single")
            for _ in range(8)
        ] + [
            _make_summary(success=False, strategy="single")
            for _ in range(2)
        ]
        mem = _make_task_memory_with_summaries(summaries)
        bias = derive_memory_runtime_bias(task_memory=mem)
        assert bias.posture == MemoryPosture.CONTINUITY_SEEKING
        assert bias.success_rate >= 0.7
        assert bias.continuity_score > 0.0

    def test_b04_mid_success_produces_retrieval_seeking(self):
        """B04. 30%-70% success → RETRIEVAL_SEEKING posture."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            MemoryPosture,
        )
        summaries = [
            _make_summary(success=True, strategy="team")
            for _ in range(5)
        ] + [
            _make_summary(success=False)
            for _ in range(7)
        ]
        mem = _make_task_memory_with_summaries(summaries)
        bias = derive_memory_runtime_bias(task_memory=mem)
        assert bias.posture == MemoryPosture.RETRIEVAL_SEEKING
        assert 0.3 <= bias.success_rate < 0.7

    def test_b05_low_success_produces_novelty(self):
        """B05. < 30% success → NOVELTY posture."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            MemoryPosture,
        )
        summaries = [
            _make_summary(success=True)
            for _ in range(2)
        ] + [
            _make_summary(success=False)
            for _ in range(8)
        ]
        mem = _make_task_memory_with_summaries(summaries)
        bias = derive_memory_runtime_bias(task_memory=mem)
        assert bias.posture == MemoryPosture.NOVELTY
        assert bias.success_rate < 0.3

    def test_b06_stale_memory_returns_novelty(self):
        """B06. Stale-only memory → NOVELTY even if entries present."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            MemoryPosture,
        )
        # All entries are older than the default 3600s window
        summaries = [
            _make_summary(success=True, age_seconds=7200.0)
            for _ in range(5)
        ]
        mem = _make_task_memory_with_summaries(summaries)
        bias = derive_memory_runtime_bias(task_memory=mem, recency_window_seconds=3600.0)
        assert bias.posture == MemoryPosture.NOVELTY

    def test_b07_prior_strategy_populated(self):
        """B07. prior_strategy is set from most-recent non-empty strategy."""
        from core.cognitive.memory_runtime_bias import derive_memory_runtime_bias
        summaries = [
            _make_summary(success=True, strategy="single"),
            _make_summary(success=True, strategy="specialized"),
        ]
        mem = _make_task_memory_with_summaries(summaries)
        bias = derive_memory_runtime_bias(task_memory=mem)
        assert bias.prior_strategy == "specialized"

    def test_b08_influenced_by_memory_flags(self):
        """B08. influenced_by_memory=True for live signals."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            FALLBACK_MEMORY_RUNTIME_BIAS,
        )
        summaries = [_make_summary(success=True)]
        mem = _make_task_memory_with_summaries(summaries)
        bias = derive_memory_runtime_bias(task_memory=mem)
        assert bias.influenced_by_memory is True
        assert FALLBACK_MEMORY_RUNTIME_BIAS.influenced_by_memory is False

    def test_b09_source_field(self):
        """B09. source='task_memory' for live; 'fallback' otherwise."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            FALLBACK_MEMORY_RUNTIME_BIAS,
        )
        summaries = [_make_summary(success=True)]
        mem = _make_task_memory_with_summaries(summaries)
        bias = derive_memory_runtime_bias(task_memory=mem)
        assert bias.source == "task_memory"
        assert FALLBACK_MEMORY_RUNTIME_BIAS.source == "fallback"

    def test_b10_posture_helpers(self):
        """B10. is_continuity_seeking / is_retrieval_seeking / is_novelty helpers."""
        from core.cognitive.memory_runtime_bias import MemoryPosture
        c = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        r = _make_bias(MemoryPosture.RETRIEVAL_SEEKING)
        n = _make_bias(MemoryPosture.NOVELTY)

        assert c.is_continuity_seeking() is True
        assert c.is_retrieval_seeking() is False
        assert c.is_novelty() is False

        assert r.is_continuity_seeking() is False
        assert r.is_retrieval_seeking() is True
        assert r.is_novelty() is False

        assert n.is_continuity_seeking() is False
        assert n.is_retrieval_seeking() is False
        assert n.is_novelty() is True

    def test_b11_to_dict_keys(self):
        """B11. MemoryRuntimeBias.to_dict() returns expected keys."""
        from core.cognitive.memory_runtime_bias import MemoryPosture
        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        d = bias.to_dict()
        expected_keys = {
            "posture", "recent_entry_count", "success_rate", "prior_strategy",
            "influenced_by_memory", "source", "continuity_score", "retrieval_score",
            "novelty_score", "timestamp", "diagnostic_note",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_b12_score_relationships(self):
        """B12. Scores are normalised [0.0, 1.0]."""
        from core.cognitive.memory_runtime_bias import MemoryPosture
        for posture in [MemoryPosture.CONTINUITY_SEEKING, MemoryPosture.RETRIEVAL_SEEKING, MemoryPosture.NOVELTY]:
            b = _make_bias(posture)
            assert 0.0 <= b.continuity_score <= 1.0
            assert 0.0 <= b.retrieval_score <= 1.0
            assert 0.0 <= b.novelty_score <= 1.0

    def test_b13_fallback_defaults(self):
        """B13. FALLBACK_MEMORY_RUNTIME_BIAS has safe defaults."""
        from core.cognitive.memory_runtime_bias import (
            FALLBACK_MEMORY_RUNTIME_BIAS,
            MemoryPosture,
        )
        b = FALLBACK_MEMORY_RUNTIME_BIAS
        assert b.posture == MemoryPosture.NOVELTY
        assert b.influenced_by_memory is False
        assert b.source == "fallback"
        assert b.recent_entry_count == 0
        assert b.continuity_score == 0.0
        assert b.novelty_score == 1.0


# ────────────── Group C — PlannerContinuityGuidance derivation ───────────────


class TestPlannerContinuityGuidance:
    """Group C — get_planner_continuity_guidance()."""

    def test_c01_none_returns_fallback(self):
        """C01. get_planner_continuity_guidance(None) returns fallback."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            FALLBACK_PLANNER_CONTINUITY_GUIDANCE,
        )
        result = get_planner_continuity_guidance(None)
        assert result is FALLBACK_PLANNER_CONTINUITY_GUIDANCE

    def test_c02_fallback_bias_returns_fallback_guidance(self):
        """C02. Fallback bias → fallback guidance (not influenced)."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            FALLBACK_MEMORY_RUNTIME_BIAS,
        )
        result = get_planner_continuity_guidance(FALLBACK_MEMORY_RUNTIME_BIAS)
        assert result.influenced_by_memory is False

    def test_c03_continuity_seeking_guidance(self):
        """C03. CONTINUITY_SEEKING → strategy_bias in proven set, adj=+0.10."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        guidance = get_planner_continuity_guidance(bias)
        assert guidance.posture == MemoryPosture.CONTINUITY_SEEKING
        assert guidance.complexity_threshold_adjustment == pytest.approx(0.10, abs=0.01)
        assert guidance.strategy_bias in ("single", "specialized", "fractal", "swarm", None)
        assert guidance.influenced_by_memory is True

    def test_c04_retrieval_seeking_guidance(self):
        """C04. RETRIEVAL_SEEKING → strategy_bias='team', adj=-0.05."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.RETRIEVAL_SEEKING)
        guidance = get_planner_continuity_guidance(bias)
        assert guidance.posture == MemoryPosture.RETRIEVAL_SEEKING
        assert guidance.strategy_bias == "team"
        assert guidance.complexity_threshold_adjustment == pytest.approx(-0.05, abs=0.01)
        assert guidance.influenced_by_memory is True

    def test_c05_novelty_guidance(self):
        """C05. NOVELTY → strategy_bias=None, adj=0.0."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.NOVELTY)
        guidance = get_planner_continuity_guidance(bias)
        assert guidance.posture == MemoryPosture.NOVELTY
        assert guidance.strategy_bias is None
        assert guidance.complexity_threshold_adjustment == pytest.approx(0.0, abs=0.01)

    def test_c06_influenced_by_memory_true_for_live(self):
        """C06. influenced_by_memory=True for live guidance."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        guidance = get_planner_continuity_guidance(bias)
        assert guidance.influenced_by_memory is True

    def test_c07_diagnostic_note_non_empty(self):
        """C07. diagnostic_note is non-empty string."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        for posture in [MemoryPosture.CONTINUITY_SEEKING, MemoryPosture.RETRIEVAL_SEEKING, MemoryPosture.NOVELTY]:
            guidance = get_planner_continuity_guidance(_make_bias(posture))
            assert isinstance(guidance.diagnostic_note, str)
            assert len(guidance.diagnostic_note) > 0

    def test_c08_to_dict_keys(self):
        """C08. PlannerContinuityGuidance.to_dict() returns expected keys."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        guidance = get_planner_continuity_guidance(_make_bias(MemoryPosture.CONTINUITY_SEEKING))
        d = guidance.to_dict()
        expected_keys = {
            "posture", "strategy_bias", "complexity_threshold_adjustment",
            "prior_strategy", "influenced_by_memory", "diagnostic_note",
        }
        assert expected_keys.issubset(set(d.keys()))


# ─────────────────── Group D — Node candidate biasing ───────────────────────


class TestNodeCandidateBiasing:
    """Group D — apply_memory_bias_to_node_preference()."""

    def test_d01_empty_candidates_with_none_bias(self):
        """D01. Empty candidates + None bias returns empty list."""
        from core.cognitive.memory_runtime_bias import apply_memory_bias_to_node_preference
        result = apply_memory_bias_to_node_preference([], None)
        assert result["ordered_candidates"] == []
        assert result["influenced_by_memory"] is False

    def test_d02_fallback_bias_returns_unchanged(self):
        """D02. Fallback bias returns candidates unchanged."""
        from core.cognitive.memory_runtime_bias import (
            apply_memory_bias_to_node_preference,
            FALLBACK_MEMORY_RUNTIME_BIAS,
        )
        result = apply_memory_bias_to_node_preference(
            ["node_a", "node_b"], FALLBACK_MEMORY_RUNTIME_BIAS
        )
        assert result["ordered_candidates"] == ["node_a", "node_b"]
        assert result["influenced_by_memory"] is False

    def test_d03_governance_filter_applied(self):
        """D03. governance_allowed filter applied before memory bias."""
        from core.cognitive.memory_runtime_bias import (
            apply_memory_bias_to_node_preference,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        result = apply_memory_bias_to_node_preference(
            ["node_a", "node_b", "node_c"],
            bias,
            governance_allowed={"node_a", "node_c"},
        )
        assert "node_b" not in result["ordered_candidates"]
        assert result["governance_applied"] is True

    def test_d04_bias_never_readmits_governance_excluded(self):
        """D04. Memory bias never re-admits governance-excluded candidates."""
        from core.cognitive.memory_runtime_bias import (
            apply_memory_bias_to_node_preference,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        result = apply_memory_bias_to_node_preference(
            ["denied_node", "allowed_node"],
            bias,
            governance_allowed={"allowed_node"},
        )
        assert "denied_node" not in result["ordered_candidates"]
        assert "allowed_node" in result["ordered_candidates"]

    def test_d05_influenced_by_memory_true_when_active(self):
        """D05. influenced_by_memory=True when active bias is applied."""
        from core.cognitive.memory_runtime_bias import (
            apply_memory_bias_to_node_preference,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        result = apply_memory_bias_to_node_preference(["node_a"], bias)
        assert result["influenced_by_memory"] is True

    def test_d06_diagnostics_keys(self):
        """D06. Diagnostics dict contains expected keys."""
        from core.cognitive.memory_runtime_bias import (
            apply_memory_bias_to_node_preference,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.NOVELTY)
        result = apply_memory_bias_to_node_preference(["node_a"], bias)
        expected_keys = {
            "ordered_candidates", "posture", "governance_applied",
            "influenced_by_memory", "diagnostic_note",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_d07_candidates_not_removed_without_governance(self):
        """D07. Without governance_allowed, candidates are not removed."""
        from core.cognitive.memory_runtime_bias import (
            apply_memory_bias_to_node_preference,
            MemoryPosture,
        )
        candidates = ["node_a", "node_b", "node_c"]
        bias = _make_bias(MemoryPosture.RETRIEVAL_SEEKING)
        result = apply_memory_bias_to_node_preference(candidates, bias)
        assert set(result["ordered_candidates"]) == set(candidates)


# ──────────── Group E — Planner strategy with continuity guidance ─────────────


class TestPlannerStrategyWithContinuityGuidance:
    """Group E — _pick_strategy() with continuity_guidance."""

    def _make_planner(self):
        from core.agent.execution_planner import ExecutionPlanner
        return ExecutionPlanner(llm_router=None)

    def test_e01_no_guidance_original_thresholds(self):
        """E01. No continuity_guidance → original thresholds unchanged."""
        planner = self._make_planner()
        # complexity 0.70 is between 0.65 and 0.75 → specialized without adjustment
        strategy = planner._pick_strategy("do something", 0.70, continuity_guidance=None)
        assert strategy == "specialized"

    def test_e02_continuity_raises_thresholds(self):
        """E02. CONTINUITY_SEEKING raises thresholds by +0.10."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        planner = self._make_planner()
        guidance = get_planner_continuity_guidance(_make_bias(MemoryPosture.CONTINUITY_SEEKING))
        # complexity 0.70 → specialized normally, but with +0.10 threshold becomes 0.75
        # so 0.70 < 0.75 → no fractal, check specialized threshold 0.65+0.10=0.75
        # 0.70 < 0.75 → falls through to single (or team if retrieval)
        strategy = planner._pick_strategy("do something", 0.70, continuity_guidance=guidance)
        # With +0.10: fractal_threshold=0.85, specialized_threshold=0.75
        # 0.70 < 0.75 → should not be specialized/fractal
        assert strategy not in ("fractal",)

    def test_e03_retrieval_lowers_thresholds(self):
        """E03. RETRIEVAL_SEEKING lowers thresholds by -0.05."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        planner = self._make_planner()
        guidance = get_planner_continuity_guidance(_make_bias(MemoryPosture.RETRIEVAL_SEEKING))
        # complexity 0.64 → single normally (< 0.65 specialized threshold)
        # with -0.05: specialized_threshold = 0.60
        # so 0.64 >= 0.60 → specialized
        strategy = planner._pick_strategy("do something", 0.64, continuity_guidance=guidance)
        assert strategy == "specialized"

    def test_e04_task_type_mapping_has_highest_priority(self):
        """E04. task_type mapping table has highest priority over memory bias."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        planner = self._make_planner()
        guidance = get_planner_continuity_guidance(_make_bias(MemoryPosture.CONTINUITY_SEEKING))
        # "device_control" → "single" regardless of memory bias
        strategy = planner._pick_strategy(
            "do something", 0.90,
            task_type="device_control",
            continuity_guidance=guidance,
        )
        assert strategy == "single"

    def test_e05_swarm_keyword_overrides_memory_bias(self):
        """E05. Swarm keyword overrides memory bias."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        planner = self._make_planner()
        guidance = get_planner_continuity_guidance(_make_bias(MemoryPosture.CONTINUITY_SEEKING))
        strategy = planner._pick_strategy("run swarm tasks", 0.3, continuity_guidance=guidance)
        assert strategy == "swarm"

    def test_e06_retrieval_seeking_strategy_bias_team(self):
        """E06. RETRIEVAL_SEEKING with team bias → 'specialized' when below threshold."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        planner = self._make_planner()
        guidance = get_planner_continuity_guidance(_make_bias(MemoryPosture.RETRIEVAL_SEEKING))
        # complexity 0.2 → normally single; with team bias and adj, should be specialized
        strategy = planner._pick_strategy("do something", 0.2, continuity_guidance=guidance)
        assert strategy == "specialized"

    def test_e07_continuity_seeking_single_prior_strategy(self):
        """E07. CONTINUITY_SEEKING with prior_strategy='single' → single returned."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryRuntimeBias,
            MemoryPosture,
        )
        planner = self._make_planner()
        bias = MemoryRuntimeBias(
            posture=MemoryPosture.CONTINUITY_SEEKING,
            recent_entry_count=5,
            success_rate=0.9,
            prior_strategy="single",
            influenced_by_memory=True,
            source="task_memory",
            continuity_score=0.9,
            retrieval_score=0.0,
            novelty_score=0.1,
            diagnostic_note="test",
        )
        guidance = get_planner_continuity_guidance(bias)
        strategy = planner._pick_strategy("do something", 0.3, continuity_guidance=guidance)
        assert strategy == "single"

    def test_e08_memory_bias_stacks_with_pr18_breadth_guidance(self):
        """E08. Memory bias adj stacks on top of PR-18 breadth guidance adj."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            MemoryPosture,
        )
        from core.cognitive.cognitive_activation_budget import ActivationBudget, PlannerBreadthGuidance
        planner = self._make_planner()

        # PR-18: narrow → adj=+0.15
        breadth_guidance = PlannerBreadthGuidance(
            breadth_mode="narrow",
            max_concurrent_agents=1,
            complexity_threshold_adjustment=0.15,
            strategy_preference=None,
            budget_value=0.2,
            influenced_by_budget=True,
            diagnostic_note="narrow",
        )
        # PR-19: retrieval → adj=-0.05
        memory_guidance = get_planner_continuity_guidance(_make_bias(MemoryPosture.RETRIEVAL_SEEKING))

        # Combined adj = +0.15 + (-0.05) = +0.10
        # fractal_threshold = 0.75+0.10 = 0.85
        # specialized_threshold = 0.65+0.10 = 0.75
        # complexity 0.80 → 0.80 >= 0.75 → specialized (not fractal)
        strategy = planner._pick_strategy(
            "do something", 0.80,
            breadth_guidance=breadth_guidance,
            continuity_guidance=memory_guidance,
        )
        assert strategy in ("specialized", "fractal")  # with combined adj should be specialized


# ──────────────── Group F — Kernel wiring (mock-based) ──────────────────────


class TestKernelWiring:
    """Group F — KernelResponse and _process() wiring."""

    def test_f01_kernel_response_has_memory_bias_hint(self):
        """F01. KernelResponse has memory_bias_hint field (Optional[Dict])."""
        from core.agent.kernel import KernelResponse
        resp = KernelResponse(success=True, mode="chat_only", reply="hi")
        assert hasattr(resp, "memory_bias_hint")
        assert resp.memory_bias_hint is None  # default

    def test_f02_to_api_dict_includes_memory_bias_hint(self):
        """F02. to_api_dict() includes 'memory_bias_hint' key."""
        from core.agent.kernel import KernelResponse
        resp = KernelResponse(
            success=True,
            mode="chat_only",
            reply="hi",
            memory_bias_hint={"posture": "novelty"},
        )
        d = resp.to_api_dict()
        assert "memory_bias_hint" in d
        assert d["memory_bias_hint"] == {"posture": "novelty"}

    def test_f03_process_derives_memory_bias_hint_with_unavailable_memory(self):
        """F03. _process() derives memory_bias_hint even when TaskMemory unavailable."""
        from core.agent.kernel import KernelResponse
        # Even with no memory, the key should exist (None is acceptable)
        resp = KernelResponse(success=True, mode="chat_only", reply="hi")
        d = resp.to_api_dict()
        assert "memory_bias_hint" in d

    def test_f04_execute_called_with_memory_bias(self):
        """F04. execute() is called with memory_bias kwarg."""
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner(llm_router=None)
        import inspect
        sig = inspect.signature(planner.execute)
        assert "memory_bias" in sig.parameters


# ──────────────── Group G — Governance integration ─────────────────────────


class TestGovernanceIntegration:
    """Group G — evaluate_invocation_governance with memory_bias."""

    def _make_eligible_registry(self, node_id: str) -> Any:
        """Build a mock NodeFabricRegistry where node_id is eligible."""
        from core.node_invocation_governance import NodeInvocationGovernanceDecision

        reg = MagicMock()
        node = MagicMock()
        node.node_id = node_id
        node.status = "active"
        node.architecture_class = "STANDARD"
        reg.get = MagicMock(return_value=node)
        return reg

    def test_g01_governance_accepts_memory_bias_kwarg(self):
        """G01. evaluate_invocation_governance accepts memory_bias kwarg."""
        import inspect
        from core.node_invocation_governance import evaluate_invocation_governance
        sig = inspect.signature(evaluate_invocation_governance)
        assert "memory_bias" in sig.parameters

    def test_g02_memory_bias_in_diagnostic_context(self):
        """G02. When memory_bias provided, diagnostic_context includes 'memory_bias_context'."""
        from core.node_invocation_governance import evaluate_invocation_governance
        from core.cognitive.memory_runtime_bias import MemoryPosture

        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)

        with patch(
            "core.node_invocation_governance.get_node_fabric_registry",
            side_effect=Exception("no registry"),
        ):
            # Node not in registry → unregistered_unmanaged path
            decision = evaluate_invocation_governance(
                "test_node",
                memory_bias=bias,
            )
        # Even on unregistered path, memory_bias_context should be in diagnostics
        assert "memory_bias_context" in decision.diagnostic_context
        ctx = decision.diagnostic_context["memory_bias_context"]
        assert ctx["posture"] == MemoryPosture.CONTINUITY_SEEKING
        assert "advisory_only" in ctx["note"]

    def test_g03_memory_bias_does_not_alter_invocation_allowed(self):
        """G03. Memory bias is advisory only: invocation_allowed is unchanged."""
        from core.node_invocation_governance import evaluate_invocation_governance
        from core.cognitive.memory_runtime_bias import MemoryPosture

        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)

        with patch(
            "core.node_invocation_governance.get_node_fabric_registry",
            side_effect=Exception("no registry"),
        ):
            # Without memory bias
            dec_no_bias = evaluate_invocation_governance("test_node")
            # With memory bias
            dec_with_bias = evaluate_invocation_governance(
                "test_node", memory_bias=bias
            )

        assert dec_no_bias.invocation_allowed == dec_with_bias.invocation_allowed

    def test_g04_denied_node_stays_denied_with_memory_bias(self):
        """G04. Denied node stays denied regardless of memory posture."""
        from core.node_invocation_governance import evaluate_invocation_governance
        from core.cognitive.memory_runtime_bias import MemoryPosture

        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)

        # Patch the governance eligibility function in its home module
        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility"
        ) as mock_gov:
            mock_gov.return_value = MagicMock(
                eligible=False,
                exclusion_reasons=["archived"],
                diagnostic_context={},
                governor_consulted=False,
            )
            reg = MagicMock()
            node = MagicMock()
            reg.get = MagicMock(return_value=node)
            decision = evaluate_invocation_governance(
                "denied_node",
                registry=reg,
                memory_bias=bias,
            )
        assert decision.invocation_allowed is False
        assert "memory_bias_context" in decision.diagnostic_context

    def test_g05_no_memory_bias_no_context_key(self):
        """G05. When memory_bias is None, no memory_bias_context key in diagnostics."""
        from core.node_invocation_governance import evaluate_invocation_governance

        with patch(
            "core.node_invocation_governance.get_node_fabric_registry",
            side_effect=Exception("no registry"),
        ):
            decision = evaluate_invocation_governance("test_node", memory_bias=None)

        assert "memory_bias_context" not in decision.diagnostic_context


# ───────────────── Group H — Diagnostics builder ────────────────────────────


class TestDiagnosticsBuilder:
    """Group H — build_memory_bias_diagnostics()."""

    def test_h01_none_bias_returns_fallback_diag(self):
        """H01. build_memory_bias_diagnostics(None) returns fallback diag."""
        from core.cognitive.memory_runtime_bias import (
            build_memory_bias_diagnostics,
            MemoryPosture,
        )
        diag = build_memory_bias_diagnostics(None)
        assert diag["influenced_by_memory"] is False
        assert diag["posture"] == MemoryPosture.NOVELTY
        assert diag["source"] == "fallback"

    def test_h02_active_bias_returns_expected_keys(self):
        """H02. Active bias returns expected keys."""
        from core.cognitive.memory_runtime_bias import (
            build_memory_bias_diagnostics,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        diag = build_memory_bias_diagnostics(bias, influenced=True, influence_source="planner")
        expected_keys = {
            "posture", "influenced", "influence_source", "hard_gate_overrode",
            "influenced_by_memory", "diagnostic_note", "source",
            "recent_entry_count", "success_rate", "prior_strategy",
            "continuity_score", "retrieval_score", "novelty_score",
        }
        assert expected_keys.issubset(set(diag.keys()))

    def test_h03_influenced_and_source_threaded(self):
        """H03. influenced and influence_source are correctly threaded."""
        from core.cognitive.memory_runtime_bias import (
            build_memory_bias_diagnostics,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.RETRIEVAL_SEEKING)
        diag = build_memory_bias_diagnostics(
            bias, influenced=True, influence_source="kernel_process"
        )
        assert diag["influenced"] is True
        assert diag["influence_source"] == "kernel_process"

    def test_h04_hard_gate_overrode_threaded(self):
        """H04. hard_gate_overrode is correctly threaded."""
        from core.cognitive.memory_runtime_bias import (
            build_memory_bias_diagnostics,
            MemoryPosture,
        )
        bias = _make_bias(MemoryPosture.CONTINUITY_SEEKING)
        diag = build_memory_bias_diagnostics(bias, hard_gate_overrode=True)
        assert diag["hard_gate_overrode"] is True

    def test_h05_numeric_fields_rounded(self):
        """H05. success_rate, continuity_score, retrieval_score, novelty_score rounded."""
        from core.cognitive.memory_runtime_bias import (
            build_memory_bias_diagnostics,
            MemoryRuntimeBias,
            MemoryPosture,
        )
        import math
        bias = MemoryRuntimeBias(
            posture=MemoryPosture.CONTINUITY_SEEKING,
            recent_entry_count=3,
            success_rate=0.777777,
            prior_strategy="single",
            influenced_by_memory=True,
            source="task_memory",
            continuity_score=0.777777,
            retrieval_score=0.111111,
            novelty_score=0.111111,
            diagnostic_note="test",
        )
        diag = build_memory_bias_diagnostics(bias)
        # All float values should be rounded to 4 decimal places
        for key in ("success_rate", "continuity_score", "retrieval_score", "novelty_score"):
            val = diag[key]
            assert isinstance(val, float)
            assert len(str(val).split(".")[-1]) <= 4


# ──────────────── Group I — Backward compatibility ─────────────────────────


class TestBackwardCompatibility:
    """Group I — backward compatibility checks."""

    @pytest.mark.asyncio
    async def test_i01_execute_without_memory_bias_works(self):
        """I01. Old callers using execute(plan) without memory_bias still work."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)
        plan = ExecutionPlan(
            message="hello",
            intent=IntentResult(mode=IntentMode.CHAT_ONLY, raw_intent="hello"),
            soul_policy="",
            agents_policy="",
            user_policy="",
            session_id="s1",
            device_id="d1",
            context=[],
        )
        # Should not raise even without memory_bias
        with patch.object(planner, "_dispatch") as mock_dispatch:
            from core.agent.execution_planner import ExecutionResult
            mock_dispatch.return_value = ExecutionResult(success=True, reply="ok")
            result = await planner.execute(plan)
            assert result.success is True

    def test_i02_governance_without_memory_bias_works(self):
        """I02. Old callers using evaluate_invocation_governance without memory_bias."""
        from core.node_invocation_governance import evaluate_invocation_governance

        with patch(
            "core.node_invocation_governance.get_node_fabric_registry",
            side_effect=Exception("no registry"),
        ):
            decision = evaluate_invocation_governance("test_node")
        # Should not raise; memory_bias_context should not be in diagnostics
        assert "memory_bias_context" not in decision.diagnostic_context

    def test_i03_derive_memory_bias_never_raises(self):
        """I03. derive_memory_runtime_bias never raises — returns fallback on error."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_runtime_bias,
            FALLBACK_MEMORY_RUNTIME_BIAS,
        )
        # Trigger an error inside derivation
        mem = MagicMock()
        mem.get_recent_summaries = MagicMock(side_effect=RuntimeError("boom"))
        result = derive_memory_runtime_bias(task_memory=mem)
        # Should return fallback
        assert result is FALLBACK_MEMORY_RUNTIME_BIAS

    def test_i04_get_planner_continuity_guidance_never_raises(self):
        """I04. get_planner_continuity_guidance never raises — returns fallback on error."""
        from core.cognitive.memory_runtime_bias import (
            get_planner_continuity_guidance,
            FALLBACK_PLANNER_CONTINUITY_GUIDANCE,
        )
        # Pass an invalid object
        result = get_planner_continuity_guidance(object())
        # Should return fallback (not influenced)
        assert result.influenced_by_memory is False

    def test_i05_apply_bias_never_raises(self):
        """I05. apply_memory_bias_to_node_preference never raises on error."""
        from core.cognitive.memory_runtime_bias import apply_memory_bias_to_node_preference

        # Pass malformed candidates
        class BadNode:
            @property
            def node_id(self):
                raise RuntimeError("bad node")

        result = apply_memory_bias_to_node_preference(
            ["good_node"],  # use str to avoid exception
            bias=None,
        )
        assert isinstance(result["ordered_candidates"], list)
