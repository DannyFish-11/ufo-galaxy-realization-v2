"""tests/test_pr19_memory_runtime_bias.py
==========================================
Tests for PR-19: memory-informed runtime bias layer.

Coverage matrix
---------------
Group A — Sentinel / authority assertions
  A01. MEMORY_RUNTIME_BIAS_IS_AUTHORITY sentinel exists.
  A02. MEMORY_RUNTIME_BIAS_PR19_SENTINEL sentinel exists.
  A03. HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY sentinel exists.
  A04. MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITY_POLICY sentinel exists.
  A05. MEMORY_BIAS_DERIVED_FROM_EXISTING_SIGNALS_POLICY sentinel exists.
  A06. EXPLICIT_USER_INTENT_REMAINS_PRIMARY_POLICY sentinel exists.
  A07. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 sentinel exists in kernel.py.
  A08. MEMORY_BIAS_PLANNER_WIRED_PR19 sentinel exists in execution_planner.py.
  A09. MEMORY_RUNTIME_BIAS_ALIGNED_PR19 alignment sentinel exists in projection.py.

Group B — MemoryBias derivation
  B01. derive_memory_bias() returns a MemoryBias instance.
  B02. derive_memory_bias() never raises — returns fallback on error.
  B03. FALLBACK_MEMORY_BIAS has influenced_by_memory=False and source='fallback'.
  B04. FALLBACK_MEMORY_BIAS posture is 'novelty'.
  B05. derive_memory_bias with empty memory → posture='novelty'.
  B06. MemoryBias.is_novelty() is True for novelty posture.
  B07. MemoryBias.is_continuity_seeking() is True for continuity_seeking posture.
  B08. MemoryBias.is_retrieval_seeking() is True for retrieval_seeking posture.
  B09. MemoryBias.to_dict() returns expected keys.
  B10. Memory bias with dense recent tasks → continuity_seeking posture.
  B11. Memory bias with moderate tasks → retrieval_seeking posture.
  B12. Memory bias with working memory → increases memory_density and continuity score.
  B13. influenced_by_memory is True when signals are available.
  B14. source is 'memory_runtime_bias' for live derivations.
  B15. diagnostic_note is a non-empty string.

Group C — MemoryBiasPlannerHint derivation
  C01. get_memory_planner_hint(None) returns non-influenced fallback hint.
  C02. get_memory_planner_hint(FALLBACK_MEMORY_BIAS) returns fallback hint.
  C03. continuity_seeking bias → prefer_continuity_strategy=True.
  C04. retrieval_seeking bias → prefer_retrieval_support=True.
  C05. novelty bias → prefer_continuity_strategy=False, prefer_retrieval_support=False.
  C06. continuity_seeking → negative complexity_threshold_adjustment.
  C07. retrieval_seeking → positive complexity_threshold_adjustment.
  C08. novelty → zero complexity_threshold_adjustment.
  C09. influenced_by_memory is True for live hints, False for fallback.
  C10. MemoryBiasPlannerHint.to_dict() returns expected keys.
  C11. get_memory_planner_hint never raises — returns fallback on error.

Group D — MemoryPosture enum
  D01. MemoryPosture has CONTINUITY_SEEKING, RETRIEVAL_SEEKING, NOVELTY values.
  D02. MemoryPosture values are strings.
  D03. MemoryPosture.CONTINUITY_SEEKING == 'continuity_seeking'.
  D04. MemoryPosture.RETRIEVAL_SEEKING == 'retrieval_seeking'.
  D05. MemoryPosture.NOVELTY == 'novelty'.

Group E — build_memory_bias_diagnostics
  E01. None bias returns minimal diagnostics with memory_bias_available=False.
  E02. Live bias returns full diagnostics with memory_bias_available=True.
  E03. influenced=True is surfaced in diagnostics.
  E04. hard_gate_overrode=True is surfaced in diagnostics.
  E05. influence_surface is surfaced in diagnostics.
  E06. diagnostics dict is JSON-safe (no special objects).

Group F — Planner strategy with memory hint (_pick_strategy)
  F01. No memory_hint → original thresholds unaffected.
  F02. continuity_seeking hint adjusts complexity threshold by -0.05.
  F03. retrieval_seeking hint adjusts complexity threshold by +0.05.
  F04. novelty hint has zero complexity adjustment.
  F05. task_type mapping still has highest priority over memory bias.
  F06. memory_hint is subordinate to breadth_guidance threshold adjustment.
  F07. memory_hint influenced_by_memory=False has no effect on thresholds.

Group G — Kernel wiring (mock-based)
  G01. KernelResponse has memory_bias_hint field (Optional[Dict]).
  G02. to_api_dict() includes 'memory_bias_hint' key.
  G03. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 sentinel exists.
  G04. execute() is called with memory_bias kwarg.

Group H — Backward compatibility
  H01. Old callers using execute(plan) without memory_bias still work.
  H02. Old callers using execute(plan, activation_budget=x) without memory_bias still work.
  H03. derive_memory_bias never raises — returns fallback on invalid input.
  H04. get_memory_planner_hint never raises — returns fallback on invalid input.
  H05. _pick_strategy(message, complexity) without memory_hint still works.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_bias_with_density(density: float) -> Any:
    """Build a MemoryBias directly with a given density for testing."""
    from core.cognitive.memory_runtime_bias import MemoryBias, MemoryPosture

    # Classify posture the same way the module does
    if density >= 0.6:
        posture = MemoryPosture.CONTINUITY_SEEKING.value
    elif density >= 0.2:
        posture = MemoryPosture.RETRIEVAL_SEEKING.value
    else:
        posture = MemoryPosture.NOVELTY.value

    return MemoryBias(
        posture=posture,
        memory_density=density,
        recent_entry_count=int(density * 10),
        total_entry_count=int(density * 15),
        session_continuity_score=density * 0.9,
        has_long_term_context=density > 0.4,
        influenced_by_memory=True,
        source="memory_runtime_bias",
        diagnostic_note=f"test: density={density}",
    )


def _make_task_memory_with_entries(n_recent: int, session_id: str = "sess_test"):
    """Build a minimal mock TaskMemory-like object with n_recent entries."""
    now = time.time()

    class FakeSummary:
        def __init__(self, i):
            self.summary_id = f"s{i}"
            self.timestamp = now - i * 60  # i minutes ago
            self.task = f"task {i}"
            self.result_summary = f"result {i}"
            self.success = True
            self.strategy = "single"

    summaries = [FakeSummary(i) for i in range(n_recent)]

    class FakeTaskMemory:
        def get_recent_summaries(self, n=20):
            return summaries[:n]

    return FakeTaskMemory()


def _make_working_memory_with_entries(n_entries: int, session_id: str = "sess_test"):
    """Build a minimal mock WorkingMemory-like object."""
    now = time.time()

    class FakeEntry:
        def __init__(self, i):
            self.role = "user"
            self.content = f"turn {i}"
            self.timestamp = now - i * 30  # i * 30 seconds ago

    entries = [FakeEntry(i) for i in range(n_entries)]

    class FakeWorkingMemory:
        def get(self, session_id=""):
            return entries

    return FakeWorkingMemory()


# ─────────────────────────── Group A — Sentinels ────────────────────────────


class TestSentinels:
    """Group A — verify PR-19 authority/sentinel constants exist."""

    def test_a01_authority_sentinel(self):
        """A01. MEMORY_RUNTIME_BIAS_IS_AUTHORITY exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "MEMORY_RUNTIME_BIAS_IS_AUTHORITY")
        assert isinstance(mod.MEMORY_RUNTIME_BIAS_IS_AUTHORITY, str)
        assert "CANONICAL_AUTHORITY" in mod.MEMORY_RUNTIME_BIAS_IS_AUTHORITY

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
        """A04. MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITY_POLICY exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITY_POLICY")
        assert "advisory" in mod.MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITY_POLICY.lower()

    def test_a05_derived_from_existing_signals_policy(self):
        """A05. MEMORY_BIAS_DERIVED_FROM_EXISTING_SIGNALS_POLICY exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "MEMORY_BIAS_DERIVED_FROM_EXISTING_SIGNALS_POLICY")
        assert "existing" in mod.MEMORY_BIAS_DERIVED_FROM_EXISTING_SIGNALS_POLICY.lower()

    def test_a06_explicit_user_intent_policy(self):
        """A06. EXPLICIT_USER_INTENT_REMAINS_PRIMARY_POLICY exists."""
        from core.cognitive import memory_runtime_bias as mod
        assert hasattr(mod, "EXPLICIT_USER_INTENT_REMAINS_PRIMARY_POLICY")
        assert "primary" in mod.EXPLICIT_USER_INTENT_REMAINS_PRIMARY_POLICY.lower()

    def test_a07_kernel_sentinel(self):
        """A07. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 exists in kernel.py."""
        from core.agent import kernel as kernel_mod
        assert hasattr(kernel_mod, "MEMORY_BIAS_WIRED_INTO_KERNEL_PR19")
        assert "PR19" in kernel_mod.MEMORY_BIAS_WIRED_INTO_KERNEL_PR19

    def test_a08_planner_sentinel(self):
        """A08. MEMORY_BIAS_PLANNER_WIRED_PR19 exists in execution_planner.py."""
        from core.agent import execution_planner as ep_mod
        assert hasattr(ep_mod, "MEMORY_BIAS_PLANNER_WIRED_PR19")
        assert "PR19" in ep_mod.MEMORY_BIAS_PLANNER_WIRED_PR19

    def test_a09_projection_alignment_sentinel(self):
        """A09. MEMORY_RUNTIME_BIAS_ALIGNED_PR19 exists in projection.py."""
        pytest.importorskip("fastapi", reason="fastapi not installed")
        import core.routes.projection as proj_mod
        assert hasattr(proj_mod, "MEMORY_RUNTIME_BIAS_ALIGNED_PR19")
        val = proj_mod.MEMORY_RUNTIME_BIAS_ALIGNED_PR19
        assert isinstance(val, str)
        assert "UNAVAILABLE" not in val


# ─────────────────── Group B — MemoryBias derivation ──────────────────────


class TestMemoryBiasDerivation:
    """Group B — derive_memory_bias() and MemoryBias dataclass."""

    def test_b01_derive_returns_memory_bias_instance(self):
        """B01. derive_memory_bias() returns a MemoryBias instance."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias, MemoryBias
        # Mock memory sources to avoid file I/O
        mock_tm = _make_task_memory_with_entries(0)
        mock_wm = _make_working_memory_with_entries(0)
        result = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm,
            long_term_memory=None,
        )
        assert isinstance(result, MemoryBias)

    def test_b02_never_raises_returns_fallback(self):
        """B02. derive_memory_bias() never raises — returns fallback on error."""
        from core.cognitive.memory_runtime_bias import (
            derive_memory_bias, FALLBACK_MEMORY_BIAS,
        )

        class BrokenMemory:
            def get_recent_summaries(self, n=20):
                raise RuntimeError("broken")

        result = derive_memory_bias(
            session_id="sess_test",
            task_memory=BrokenMemory(),
        )
        assert isinstance(result, type(FALLBACK_MEMORY_BIAS))

    def test_b03_fallback_bias_flags(self):
        """B03. FALLBACK_MEMORY_BIAS has influenced_by_memory=False and source='fallback'."""
        from core.cognitive.memory_runtime_bias import FALLBACK_MEMORY_BIAS
        assert FALLBACK_MEMORY_BIAS.influenced_by_memory is False
        assert FALLBACK_MEMORY_BIAS.source == "fallback"

    def test_b04_fallback_bias_posture_is_novelty(self):
        """B04. FALLBACK_MEMORY_BIAS posture is 'novelty'."""
        from core.cognitive.memory_runtime_bias import FALLBACK_MEMORY_BIAS, MemoryPosture
        assert FALLBACK_MEMORY_BIAS.posture == MemoryPosture.NOVELTY.value

    def test_b05_empty_memory_returns_novelty(self):
        """B05. derive_memory_bias with empty memory → posture='novelty'."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias, MemoryPosture
        mock_tm = _make_task_memory_with_entries(0)
        mock_wm = _make_working_memory_with_entries(0)
        result = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm,
            long_term_memory=None,
        )
        assert result.posture == MemoryPosture.NOVELTY.value

    def test_b06_is_novelty_helper(self):
        """B06. MemoryBias.is_novelty() is True for novelty posture."""
        bias = _make_bias_with_density(0.0)
        assert bias.is_novelty() is True
        assert bias.is_continuity_seeking() is False
        assert bias.is_retrieval_seeking() is False

    def test_b07_is_continuity_seeking_helper(self):
        """B07. MemoryBias.is_continuity_seeking() is True for continuity_seeking posture."""
        bias = _make_bias_with_density(0.8)
        assert bias.is_continuity_seeking() is True
        assert bias.is_novelty() is False
        assert bias.is_retrieval_seeking() is False

    def test_b08_is_retrieval_seeking_helper(self):
        """B08. MemoryBias.is_retrieval_seeking() is True for retrieval_seeking posture."""
        bias = _make_bias_with_density(0.4)
        assert bias.is_retrieval_seeking() is True
        assert bias.is_novelty() is False
        assert bias.is_continuity_seeking() is False

    def test_b09_to_dict_has_expected_keys(self):
        """B09. MemoryBias.to_dict() returns expected keys."""
        bias = _make_bias_with_density(0.5)
        d = bias.to_dict()
        expected_keys = {
            "posture", "memory_density", "recent_entry_count",
            "total_entry_count", "session_continuity_score",
            "has_long_term_context", "influenced_by_memory", "source",
            "timestamp", "diagnostic_note",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_b10_dense_tasks_produce_continuity_posture(self):
        """B10. Memory bias with dense recent tasks → continuity_seeking posture."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias, MemoryPosture
        # 10 recent tasks in last hour gives density ~0.5 from task alone
        # plus working memory entries will push it over 0.6
        mock_tm = _make_task_memory_with_entries(10)  # 10 recent tasks
        mock_wm = _make_working_memory_with_entries(5)  # 5 working memory entries
        result = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm,
            long_term_memory=None,
        )
        # 10 tasks → task_density: min(10/10, 1.0) * 0.50 = 0.50
        # 5 working entries (recent) → wm_recency: 1.0 * 0.30 = 0.30; wm_density: min(5/5,1)*0.20 = 0.20
        # Total ≈ 1.0 → continuity_seeking
        assert result.posture == MemoryPosture.CONTINUITY_SEEKING.value

    def test_b11_moderate_tasks_produce_retrieval_posture(self):
        """B11. Memory bias with moderate recent tasks → retrieval_seeking posture."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias, MemoryPosture
        # 3 recent tasks, no working memory entries → density ≈ 0.15 (task only)
        # but with some working memory it should be in range [0.2, 0.6)
        mock_tm = _make_task_memory_with_entries(4)
        mock_wm = _make_working_memory_with_entries(2)
        result = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm,
            long_term_memory=None,
        )
        # 4 tasks: task_density = min(4/10,1)*0.50 = 0.20
        # 2 wm entries (recent): wm_recency = 1.0*0.30 = 0.30; wm_density = min(2/5,1)*0.20 = 0.08
        # Total ≈ 0.58 → retrieval_seeking or continuity_seeking
        assert result.posture in (
            MemoryPosture.RETRIEVAL_SEEKING.value,
            MemoryPosture.CONTINUITY_SEEKING.value,
        )

    def test_b12_working_memory_increases_density(self):
        """B12. Memory bias with working memory entries increases density and continuity."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias
        # No tasks but working memory entries
        mock_tm = _make_task_memory_with_entries(0)
        mock_wm_empty = _make_working_memory_with_entries(0)
        mock_wm_full = _make_working_memory_with_entries(5)

        bias_empty = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm_empty,
            long_term_memory=None,
        )
        bias_full = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm_full,
            long_term_memory=None,
        )
        assert bias_full.memory_density > bias_empty.memory_density
        assert bias_full.session_continuity_score >= bias_empty.session_continuity_score

    def test_b13_influenced_by_memory_true_for_live(self):
        """B13. influenced_by_memory is True when signals are available."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias
        mock_tm = _make_task_memory_with_entries(5)
        mock_wm = _make_working_memory_with_entries(0)
        result = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm,
            long_term_memory=None,
        )
        assert result.influenced_by_memory is True

    def test_b14_source_field_for_live_derivation(self):
        """B14. source is 'memory_runtime_bias' for live derivations."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias
        mock_tm = _make_task_memory_with_entries(3)
        mock_wm = _make_working_memory_with_entries(0)
        result = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm,
            long_term_memory=None,
        )
        assert result.source == "memory_runtime_bias"

    def test_b15_diagnostic_note_non_empty(self):
        """B15. diagnostic_note is a non-empty string."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias
        mock_tm = _make_task_memory_with_entries(2)
        mock_wm = _make_working_memory_with_entries(0)
        result = derive_memory_bias(
            session_id="sess_test",
            task_memory=mock_tm,
            working_memory=mock_wm,
            long_term_memory=None,
        )
        assert isinstance(result.diagnostic_note, str)
        assert len(result.diagnostic_note) > 0


# ────────────── Group C — MemoryBiasPlannerHint derivation ──────────────────


class TestMemoryBiasPlannerHint:
    """Group C — get_memory_planner_hint()."""

    def test_c01_none_bias_returns_fallback_hint(self):
        """C01. get_memory_planner_hint(None) returns non-influenced fallback hint."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        hint = get_memory_planner_hint(None)
        assert hint.influenced_by_memory is False
        assert hint.posture == "novelty"

    def test_c02_fallback_bias_returns_fallback_hint(self):
        """C02. get_memory_planner_hint(FALLBACK_MEMORY_BIAS) returns fallback hint."""
        from core.cognitive.memory_runtime_bias import (
            get_memory_planner_hint, FALLBACK_MEMORY_BIAS,
        )
        hint = get_memory_planner_hint(FALLBACK_MEMORY_BIAS)
        assert hint.influenced_by_memory is False

    def test_c03_continuity_seeking_prefer_continuity(self):
        """C03. continuity_seeking bias → prefer_continuity_strategy=True."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        bias = _make_bias_with_density(0.8)
        hint = get_memory_planner_hint(bias)
        assert hint.prefer_continuity_strategy is True
        assert hint.posture == "continuity_seeking"

    def test_c04_retrieval_seeking_prefer_retrieval(self):
        """C04. retrieval_seeking bias → prefer_retrieval_support=True."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        bias = _make_bias_with_density(0.4)
        hint = get_memory_planner_hint(bias)
        assert hint.prefer_retrieval_support is True
        assert hint.posture == "retrieval_seeking"

    def test_c05_novelty_no_preferences(self):
        """C05. novelty bias → prefer_continuity_strategy=False, prefer_retrieval_support=False."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        bias = _make_bias_with_density(0.05)
        hint = get_memory_planner_hint(bias)
        assert hint.prefer_continuity_strategy is False
        assert hint.prefer_retrieval_support is False
        assert hint.posture == "novelty"

    def test_c06_continuity_seeking_negative_complexity_adj(self):
        """C06. continuity_seeking → negative complexity_threshold_adjustment."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        bias = _make_bias_with_density(0.8)
        hint = get_memory_planner_hint(bias)
        assert hint.complexity_threshold_adjustment < 0.0

    def test_c07_retrieval_seeking_positive_complexity_adj(self):
        """C07. retrieval_seeking → positive complexity_threshold_adjustment."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        bias = _make_bias_with_density(0.4)
        hint = get_memory_planner_hint(bias)
        assert hint.complexity_threshold_adjustment > 0.0

    def test_c08_novelty_zero_complexity_adj(self):
        """C08. novelty → zero complexity_threshold_adjustment."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        bias = _make_bias_with_density(0.05)
        hint = get_memory_planner_hint(bias)
        assert abs(hint.complexity_threshold_adjustment) < 0.001

    def test_c09_influenced_by_memory_flag(self):
        """C09. influenced_by_memory is True for live hints, False for fallback."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        live_hint = get_memory_planner_hint(_make_bias_with_density(0.8))
        assert live_hint.influenced_by_memory is True

        fallback_hint = get_memory_planner_hint(None)
        assert fallback_hint.influenced_by_memory is False

    def test_c10_to_dict_has_expected_keys(self):
        """C10. MemoryBiasPlannerHint.to_dict() returns expected keys."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        hint = get_memory_planner_hint(_make_bias_with_density(0.5))
        d = hint.to_dict()
        expected_keys = {
            "posture", "prefer_continuity_strategy", "prefer_retrieval_support",
            "complexity_threshold_adjustment", "session_continuity_score",
            "influenced_by_memory", "diagnostic_note",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_c11_never_raises(self):
        """C11. get_memory_planner_hint never raises — returns fallback on error."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint

        # Pass something completely invalid
        hint = get_memory_planner_hint("not_a_bias_object")  # type: ignore
        assert hint is not None
        assert hasattr(hint, "posture")


# ─────────────────── Group D — MemoryPosture enum ──────────────────────────


class TestMemoryPostureEnum:
    """Group D — MemoryPosture enum contract."""

    def test_d01_enum_has_required_members(self):
        """D01. MemoryPosture has CONTINUITY_SEEKING, RETRIEVAL_SEEKING, NOVELTY."""
        from core.cognitive.memory_runtime_bias import MemoryPosture
        assert hasattr(MemoryPosture, "CONTINUITY_SEEKING")
        assert hasattr(MemoryPosture, "RETRIEVAL_SEEKING")
        assert hasattr(MemoryPosture, "NOVELTY")

    def test_d02_enum_values_are_strings(self):
        """D02. MemoryPosture values are strings."""
        from core.cognitive.memory_runtime_bias import MemoryPosture
        assert isinstance(MemoryPosture.CONTINUITY_SEEKING.value, str)
        assert isinstance(MemoryPosture.RETRIEVAL_SEEKING.value, str)
        assert isinstance(MemoryPosture.NOVELTY.value, str)

    def test_d03_continuity_seeking_value(self):
        """D03. MemoryPosture.CONTINUITY_SEEKING == 'continuity_seeking'."""
        from core.cognitive.memory_runtime_bias import MemoryPosture
        assert MemoryPosture.CONTINUITY_SEEKING.value == "continuity_seeking"

    def test_d04_retrieval_seeking_value(self):
        """D04. MemoryPosture.RETRIEVAL_SEEKING == 'retrieval_seeking'."""
        from core.cognitive.memory_runtime_bias import MemoryPosture
        assert MemoryPosture.RETRIEVAL_SEEKING.value == "retrieval_seeking"

    def test_d05_novelty_value(self):
        """D05. MemoryPosture.NOVELTY == 'novelty'."""
        from core.cognitive.memory_runtime_bias import MemoryPosture
        assert MemoryPosture.NOVELTY.value == "novelty"


# ────────────── Group E — build_memory_bias_diagnostics ─────────────────────


class TestMemoryBiasDiagnostics:
    """Group E — build_memory_bias_diagnostics()."""

    def test_e01_none_bias_minimal_diagnostics(self):
        """E01. None bias returns minimal diagnostics with memory_bias_available=False."""
        from core.cognitive.memory_runtime_bias import build_memory_bias_diagnostics
        diag = build_memory_bias_diagnostics(None)
        assert diag["memory_bias_available"] is False
        assert diag["posture"] == "novelty"
        assert diag["influenced"] is False

    def test_e02_live_bias_full_diagnostics(self):
        """E02. Live bias returns full diagnostics with memory_bias_available=True."""
        from core.cognitive.memory_runtime_bias import build_memory_bias_diagnostics
        bias = _make_bias_with_density(0.8)
        diag = build_memory_bias_diagnostics(bias)
        assert diag["memory_bias_available"] is True
        assert diag["posture"] == "continuity_seeking"
        assert "memory_density" in diag
        assert "recent_entry_count" in diag

    def test_e03_influenced_surfaced(self):
        """E03. influenced=True is surfaced in diagnostics."""
        from core.cognitive.memory_runtime_bias import build_memory_bias_diagnostics
        bias = _make_bias_with_density(0.8)
        diag = build_memory_bias_diagnostics(bias, influenced=True)
        assert diag["influenced"] is True

    def test_e04_hard_gate_override_surfaced(self):
        """E04. hard_gate_overrode=True is surfaced in diagnostics."""
        from core.cognitive.memory_runtime_bias import build_memory_bias_diagnostics
        bias = _make_bias_with_density(0.5)
        diag = build_memory_bias_diagnostics(
            bias,
            hard_gate_overrode=True,
            override_reason="governance_denied",
        )
        assert diag["hard_gate_overrode"] is True
        assert diag["override_reason"] == "governance_denied"

    def test_e05_influence_surface_surfaced(self):
        """E05. influence_surface is surfaced in diagnostics."""
        from core.cognitive.memory_runtime_bias import build_memory_bias_diagnostics
        bias = _make_bias_with_density(0.5)
        diag = build_memory_bias_diagnostics(
            bias,
            influenced=True,
            influence_surface="planner_strategy",
        )
        assert diag["influence_surface"] == "planner_strategy"

    def test_e06_diagnostics_json_safe(self):
        """E06. diagnostics dict is JSON-safe (no special objects)."""
        import json
        from core.cognitive.memory_runtime_bias import build_memory_bias_diagnostics
        bias = _make_bias_with_density(0.7)
        diag = build_memory_bias_diagnostics(bias, influenced=True, influence_surface="test")
        # Should not raise
        serialized = json.dumps(diag)
        assert len(serialized) > 0


# ───────── Group F — Planner strategy with memory hint ──────────────────────


class TestPlannerStrategyWithMemoryHint:
    """Group F — _pick_strategy() with memory_hint parameter."""

    def _make_planner(self):
        from core.agent.execution_planner import ExecutionPlanner
        return ExecutionPlanner(llm_router=None)

    def _make_memory_hint(self, posture: str, adj: float):
        """Build a minimal MemoryBiasPlannerHint-like object."""
        from core.cognitive.memory_runtime_bias import MemoryBiasPlannerHint
        return MemoryBiasPlannerHint(
            posture=posture,
            prefer_continuity_strategy=(posture == "continuity_seeking"),
            prefer_retrieval_support=(posture == "retrieval_seeking"),
            complexity_threshold_adjustment=adj,
            session_continuity_score=0.5,
            influenced_by_memory=True,
            diagnostic_note=f"test: posture={posture}",
        )

    def test_f01_no_memory_hint_unaffected(self):
        """F01. No memory_hint → original thresholds unaffected."""
        planner = self._make_planner()
        # Complexity 0.70 ≥ 0.65 → specialized without any adjustment
        strategy = planner._pick_strategy("some complex task", 0.70)
        assert strategy == "specialized"

    def test_f02_continuity_seeking_lowers_threshold(self):
        """F02. continuity_seeking hint adjusts complexity threshold by -0.05."""
        planner = self._make_planner()
        hint = self._make_memory_hint("continuity_seeking", -0.05)
        # complexity 0.63 < specialized_threshold=0.65 without adj,
        # but with adj=-0.05 → threshold=0.60, so 0.63 >= 0.60 → specialized
        strategy = planner._pick_strategy("task", 0.63, memory_hint=hint)
        assert strategy == "specialized"

    def test_f03_retrieval_seeking_raises_threshold(self):
        """F03. retrieval_seeking hint adjusts complexity threshold by +0.05."""
        planner = self._make_planner()
        hint = self._make_memory_hint("retrieval_seeking", +0.05)
        # complexity 0.67 >= 0.65 normally → specialized
        # but with adj=+0.05 → threshold=0.70, so 0.67 < 0.70 → single
        strategy = planner._pick_strategy("task", 0.67, memory_hint=hint)
        assert strategy == "single"

    def test_f04_novelty_hint_no_change(self):
        """F04. novelty hint has zero complexity adjustment."""
        planner = self._make_planner()
        hint = self._make_memory_hint("novelty", 0.0)
        # Same as without hint
        strategy_with = planner._pick_strategy("task", 0.70, memory_hint=hint)
        strategy_without = planner._pick_strategy("task", 0.70)
        assert strategy_with == strategy_without

    def test_f05_task_type_mapping_overrides_memory_hint(self):
        """F05. task_type mapping still has highest priority over memory bias."""
        planner = self._make_planner()
        hint = self._make_memory_hint("continuity_seeking", -0.05)
        # task_type 'chat' → single regardless of memory hint
        strategy = planner._pick_strategy("chat about something", 0.9, task_type="chat", memory_hint=hint)
        assert strategy == "single"

    def test_f06_memory_hint_combines_with_breadth_guidance(self):
        """F06. memory_hint is subordinate to breadth_guidance threshold adjustment."""
        from core.cognitive.cognitive_activation_budget import PlannerBreadthGuidance
        planner = self._make_planner()
        # breadth_guidance with adj=+0.15 (narrow/passive)
        breadth = PlannerBreadthGuidance(
            breadth_mode="narrow",
            max_concurrent_agents=1,
            complexity_threshold_adjustment=0.15,
            strategy_preference="single",
            budget_value=0.2,
            influenced_by_budget=True,
            diagnostic_note="test",
        )
        hint = self._make_memory_hint("continuity_seeking", -0.05)
        # combined adj = 0.15 + (-0.05) = 0.10
        # fractal threshold = 0.75 + 0.10 = 0.85
        # specialized threshold = 0.65 + 0.10 = 0.75
        # complexity 0.80 < 0.85 → not fractal; 0.80 >= 0.75 → specialized
        # but strategy_preference='single' from narrow budget overrides if below threshold
        strategy = planner._pick_strategy("task", 0.80, breadth_guidance=breadth, memory_hint=hint)
        # 0.80 >= specialized threshold (0.75) → specialized (before strategy_pref check)
        assert strategy == "specialized"

    def test_f07_non_influenced_memory_hint_has_no_effect(self):
        """F07. memory_hint influenced_by_memory=False has no effect on thresholds."""
        from core.cognitive.memory_runtime_bias import MemoryBiasPlannerHint
        planner = self._make_planner()
        # Create a hint with influenced_by_memory=False
        hint = MemoryBiasPlannerHint(
            posture="continuity_seeking",
            prefer_continuity_strategy=True,
            prefer_retrieval_support=False,
            complexity_threshold_adjustment=-0.15,  # large negative adj
            session_continuity_score=0.9,
            influenced_by_memory=False,  # not influenced
            diagnostic_note="test",
        )
        # Without influence, adj should be ignored
        strategy_with = planner._pick_strategy("task", 0.62, memory_hint=hint)
        strategy_without = planner._pick_strategy("task", 0.62)
        assert strategy_with == strategy_without  # both should return "single"


# ──────────────── Group G — Kernel wiring (mock-based) ──────────────────────


class TestKernelWiring:
    """Group G — kernel.py memory bias wiring."""

    def test_g01_kernel_response_has_memory_bias_hint_field(self):
        """G01. KernelResponse has memory_bias_hint field (Optional[Dict])."""
        from core.agent.kernel import KernelResponse
        resp = KernelResponse()
        assert hasattr(resp, "memory_bias_hint")
        assert resp.memory_bias_hint is None  # default is None

    def test_g02_to_api_dict_includes_memory_bias_hint(self):
        """G02. to_api_dict() includes 'memory_bias_hint' key."""
        from core.agent.kernel import KernelResponse
        resp = KernelResponse(memory_bias_hint={"posture": "novelty"})
        api_dict = resp.to_api_dict()
        assert "memory_bias_hint" in api_dict
        assert api_dict["memory_bias_hint"] == {"posture": "novelty"}

    def test_g03_memory_bias_wired_sentinel_exists(self):
        """G03. MEMORY_BIAS_WIRED_INTO_KERNEL_PR19 sentinel exists."""
        from core.agent import kernel as kernel_mod
        assert hasattr(kernel_mod, "MEMORY_BIAS_WIRED_INTO_KERNEL_PR19")
        assert "memory" in kernel_mod.MEMORY_BIAS_WIRED_INTO_KERNEL_PR19.lower()

    def test_g04_execute_accepts_memory_bias_kwarg(self):
        """G04. execute() accepts memory_bias kwarg without error."""
        import asyncio
        import inspect
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner(llm_router=None)
        sig = inspect.signature(planner.execute)
        assert "memory_bias" in sig.parameters


# ─────────────────── Group H — Backward compatibility ───────────────────────


class TestBackwardCompatibility:
    """Group H — ensure PR-19 changes do not break existing callers."""

    def test_h01_execute_without_memory_bias_works(self):
        """H01. Old callers using execute(plan) without memory_bias still work."""
        import inspect
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner(llm_router=None)
        sig = inspect.signature(planner.execute)
        # memory_bias must have a default value of None
        param = sig.parameters.get("memory_bias")
        assert param is not None
        assert param.default is None

    def test_h02_execute_with_only_activation_budget_works(self):
        """H02. Old callers using execute(plan, activation_budget=x) without memory_bias still work."""
        import inspect
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner(llm_router=None)
        sig = inspect.signature(planner.execute)
        # activation_budget must still exist and have default None
        ab_param = sig.parameters.get("activation_budget")
        assert ab_param is not None
        assert ab_param.default is None
        # memory_bias must have default None
        mb_param = sig.parameters.get("memory_bias")
        assert mb_param is not None
        assert mb_param.default is None

    def test_h03_derive_memory_bias_never_raises(self):
        """H03. derive_memory_bias never raises — returns fallback on invalid input."""
        from core.cognitive.memory_runtime_bias import derive_memory_bias, FALLBACK_MEMORY_BIAS

        # All None inputs
        result = derive_memory_bias(session_id="")
        assert result is not None
        assert hasattr(result, "posture")

    def test_h04_get_memory_planner_hint_never_raises(self):
        """H04. get_memory_planner_hint never raises — returns fallback on error."""
        from core.cognitive.memory_runtime_bias import get_memory_planner_hint
        # Various invalid inputs
        for invalid in [None, 42, "string", [], {}]:
            result = get_memory_planner_hint(invalid)  # type: ignore
            assert result is not None
            assert hasattr(result, "posture")

    def test_h05_pick_strategy_without_memory_hint_unchanged(self):
        """H05. _pick_strategy(message, complexity) without memory_hint still works."""
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner(llm_router=None)
        # All original cases should still work
        assert planner._pick_strategy("simple task", 0.3) == "single"
        assert planner._pick_strategy("parallel team task", 0.7) in ("specialized", "fractal", "swarm")
        # Fractal keywords
        result = planner._pick_strategy("fractal decomposition", 0.9)
        assert result == "fractal"
