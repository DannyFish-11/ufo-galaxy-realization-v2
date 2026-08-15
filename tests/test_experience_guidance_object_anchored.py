"""tests/test_experience_guidance_object_anchored.py
=====================================================
Tests for object-anchored experience guidance.

背景
----
被取代的实现 ``ExecutionPlanner._experience_strategy_adjust`` 做的是:
把结构化事实(策略/成败)拼成中文散文写进统一记忆层 → 向量相似度召回至多 8 段
文本 → 正则 ``策略[X] ... 结果[成功|失败]`` 抠回结构 → 算"成功率" →
**无条件覆写** ``_pick_strategy()`` 已经从受治理输入产出的策略。

三处硬伤:
  1. 算出来的不是成功率——分母是相似度采样的 8 条,不是真实执行总数。
  2. 无类型过滤——共享无类型文本命名空间,任何写入方写出同样括号格式即污染。
  3. 格式串一改,正则匹配不上只是 continue,学习静默停止、不报错。

现改为读 ``TaskSummary`` 的类型化字段(``strategy: str`` / ``success: bool``),
作用域由 BM25 词法排序提供,并降级为 ``_pick_strategy()`` 的**建议输入**,
服从 ``MEMORY_BIAS_LAYER::POLICY_4``(记忆派生影响优先级最低)。

Coverage matrix
---------------
Group A — Sentinel / policy assertions
  A01. EXPERIENCE_GUIDANCE_IS_AUTHORITY sentinel exists.
  A02. EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_POLICY sentinel exists.
  A03. EXPERIENCE_GUIDANCE_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY sentinel exists.
  A04. EXPERIENCE_GUIDANCE_NEVER_OVERRIDES_EXPLICIT_SIGNALS_POLICY sentinel exists.
  A05. EXPERIENCE_GUIDANCE_PATTERN_MINER_BOUNDARY documents the PatternMiner overlap.
  A06. EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_WIRED sentinel exists in execution_planner.

Group B — Mode resolution
  B01. Default mode is "on" (historical behaviour was active by default).
  B02. GALAXY_EXPERIENCE_GUIDANCE=shadow → MODE_SHADOW.
  B03. GALAXY_EXPERIENCE_GUIDANCE=off → MODE_OFF.
  B04. Legacy GALAXY_EXPERIENCE_STRATEGY=0 forces MODE_OFF (back-compat).
  B05. Unrecognised value degrades to MODE_ON without raising.

Group C — StrategyStat
  C01. rate is successes/total.
  C02. rate is 0.0 (not ZeroDivisionError) when total==0.
  C03. qualifies() honours min_samples.
  C04. to_dict() is JSON-safe with expected keys.

Group D — Derivation
  D01. Clear winner with enough samples → candidate populated, influenced=True.
  D02. Below min_samples → no candidate.
  D03. Advantage below margin → no candidate.
  D04. Cold start (current has no samples) + candidate above floor → candidate.
  D05. Cold start + candidate below floor → no candidate (the old code switched here).
  D06. Current strategy already best → no candidate.
  D07. Empty record set → neutral guidance.
  D08. Records without a strategy field → neutral guidance.
  D09. MODE_SHADOW populates candidate but influenced_by_experience stays False.
  D10. MODE_OFF → neutral, memory never consulted.
  D11. A raising memory backend degrades to neutral instead of propagating.
  D12. Ties resolve deterministically regardless of record order.
  D13. Exact counts are used — the denominator is the real population.
  D14. to_dict() is JSON-safe.

Group E — _pick_strategy integration (priority)
  E01. experience_guidance=None leaves selection byte-identical (regression).
  E02. Guidance redirects an implicitly-reached strategy.
  E03. Guidance never overrides task_type mapping.
  E04. Guidance never overrides an explicit keyword match.
  E05. Guidance never overrides budget strategy preference.
  E06. Guidance never overrides memory continuity preference.
  E07. influenced_by_experience=False is ignored even with a candidate.
  E08. Candidate equal to base is a no-op.

Group F — Regression guards
  F01. The superseded method name is gone from execution_planner.
  F02. The 策略[...]结果[...] regex is gone from the decision path.
  F03. The decision path no longer imports core.memory for strategy selection.
  F04. experience_guidance flag is registered in flags.py.
"""

from __future__ import annotations

import inspect
import json

import pytest

from core.cognitive.experience_guidance import (
    MODE_OFF,
    MODE_ON,
    MODE_SHADOW,
    ExperienceGuidance,
    StrategyStat,
    derive_experience_guidance,
    get_experience_guidance_mode,
)
from core.task_memory import TaskSummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeTaskMemory:
    """Minimal stand-in exposing the two TaskMemory methods used for scoping."""

    def __init__(self, records):
        self._records = list(records)
        self.retrieve_calls = 0
        self.recent_calls = 0

    def retrieve_similar(self, query, k=5, min_score=0.3):
        self.retrieve_calls += 1
        return list(self._records)

    def get_recent_summaries(self, n=5, task_type=None):
        self.recent_calls += 1
        return list(self._records)


class BoomTaskMemory:
    """A memory backend that fails on every access."""

    def retrieve_similar(self, *a, **k):
        raise RuntimeError("backend down")

    def get_recent_summaries(self, *a, **k):
        raise RuntimeError("backend down")


def rec(strategy: str, success: bool, task: str = "部署服务到生产环境") -> TaskSummary:
    return TaskSummary(task=task, strategy=strategy, success=success)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts from the documented default mode."""
    monkeypatch.delenv("GALAXY_EXPERIENCE_GUIDANCE", raising=False)
    monkeypatch.delenv("GALAXY_EXPERIENCE_STRATEGY", raising=False)


# ---------------------------------------------------------------------------
# Group A — Sentinels
# ---------------------------------------------------------------------------


class TestGroupASentinels:
    def test_a01_authority_sentinel(self):
        from core.cognitive.experience_guidance import EXPERIENCE_GUIDANCE_IS_AUTHORITY

        assert "AUTHORITY" in EXPERIENCE_GUIDANCE_IS_AUTHORITY
        assert "strategy-success statistics" in EXPERIENCE_GUIDANCE_IS_AUTHORITY

    def test_a02_object_anchored_policy(self):
        from core.cognitive.experience_guidance import EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_POLICY

        assert "POLICY_1" in EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_POLICY
        assert "typed TaskSummary fields" in EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_POLICY
        assert "forbidden" in EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_POLICY.lower()

    def test_a03_advisory_policy(self):
        from core.cognitive.experience_guidance import (
            EXPERIENCE_GUIDANCE_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY,
        )

        assert "POLICY_2" in EXPERIENCE_GUIDANCE_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY
        assert "advisory" in EXPERIENCE_GUIDANCE_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY.lower()

    def test_a04_never_overrides_policy(self):
        from core.cognitive.experience_guidance import (
            EXPERIENCE_GUIDANCE_NEVER_OVERRIDES_EXPLICIT_SIGNALS_POLICY,
        )

        text = EXPERIENCE_GUIDANCE_NEVER_OVERRIDES_EXPLICIT_SIGNALS_POLICY
        assert "POLICY_3" in text
        # Must explicitly inherit the PR-19 lowest-priority doctrine.
        assert "MEMORY_BIAS_LAYER::POLICY_4" in text

    def test_a05_pattern_miner_boundary_is_documented(self):
        """The overlap with PatternMiner must be stated, not silently ignored."""
        from core.cognitive.experience_guidance import EXPERIENCE_GUIDANCE_PATTERN_MINER_BOUNDARY

        text = EXPERIENCE_GUIDANCE_PATTERN_MINER_BOUNDARY
        assert "PatternMiner" in text
        assert "ExperienceGuidance" in text
        # It must not claim to be the single source of strategy statistics.
        assert "neither" in text.lower()

    def test_a06_planner_wired_sentinel(self):
        from core.agent.execution_planner import EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_WIRED

        text = EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_WIRED
        assert "OBJECT_ANCHORED_WIRED" in text
        assert "never a post-hoc" in text


# ---------------------------------------------------------------------------
# Group B — Mode resolution
# ---------------------------------------------------------------------------


class TestGroupBModes:
    def test_b01_default_is_on(self):
        assert get_experience_guidance_mode() == MODE_ON

    def test_b02_shadow(self, monkeypatch):
        monkeypatch.setenv("GALAXY_EXPERIENCE_GUIDANCE", "shadow")
        assert get_experience_guidance_mode() == MODE_SHADOW

    def test_b03_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_EXPERIENCE_GUIDANCE", "off")
        assert get_experience_guidance_mode() == MODE_OFF

    @pytest.mark.parametrize("value", ["0", "false", "no", "off"])
    def test_b04_legacy_kill_switch_forces_off(self, monkeypatch, value):
        """Historical opt-out contract must keep working."""
        monkeypatch.setenv("GALAXY_EXPERIENCE_STRATEGY", value)
        monkeypatch.setenv("GALAXY_EXPERIENCE_GUIDANCE", "on")
        assert get_experience_guidance_mode() == MODE_OFF

    def test_b05_unknown_value_degrades_to_on(self, monkeypatch):
        """A typo in an env var must never break strategy selection."""
        monkeypatch.setenv("GALAXY_EXPERIENCE_GUIDANCE", "enabled-ish")
        assert get_experience_guidance_mode() == MODE_ON


# ---------------------------------------------------------------------------
# Group C — StrategyStat
# ---------------------------------------------------------------------------


class TestGroupCStrategyStat:
    def test_c01_rate(self):
        assert StrategyStat("s", successes=3, total=4).rate == 0.75

    def test_c02_rate_no_samples_is_zero(self):
        assert StrategyStat("s", successes=0, total=0).rate == 0.0

    def test_c03_qualifies(self):
        stat = StrategyStat("s", successes=5, total=5)
        assert stat.qualifies(5) is True
        assert stat.qualifies(6) is False

    def test_c04_to_dict_json_safe(self):
        payload = StrategyStat("s", successes=1, total=2).to_dict()
        assert set(payload) == {"strategy", "successes", "total", "rate"}
        json.dumps(payload)


# ---------------------------------------------------------------------------
# Group D — Derivation
# ---------------------------------------------------------------------------


class TestGroupDDerivation:
    def test_d01_clear_winner(self):
        mem = FakeTaskMemory([rec("swarm", True)] * 6 + [rec("single", False)] * 6)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_strategy == "swarm"
        assert g.candidate_rate == 1.0
        assert g.candidate_n == 6
        assert g.current_strategy == "single"
        assert g.current_n == 6
        assert g.influenced_by_experience is True

    def test_d02_below_min_samples(self):
        mem = FakeTaskMemory([rec("swarm", True)] * 3 + [rec("single", False)] * 3)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_strategy == ""
        assert g.influenced_by_experience is False
        assert "min_samples" in g.diagnostic_note

    def test_d03_advantage_below_margin(self):
        # swarm .60 vs single .50 — a 0.10 gap, below the 0.34 margin.
        mem = FakeTaskMemory(
            [rec("swarm", True)] * 6
            + [rec("swarm", False)] * 4
            + [rec("single", True)] * 5
            + [rec("single", False)] * 5
        )
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_strategy == ""
        assert g.influenced_by_experience is False

    def test_d04_cold_start_above_floor(self):
        mem = FakeTaskMemory([rec("swarm", True)] * 6)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_strategy == "swarm"
        assert g.influenced_by_experience is True
        assert "cold-start floor" in g.diagnostic_note

    def test_d05_cold_start_below_floor(self):
        """The superseded implementation switched here — any qualifying
        candidate won when the current strategy had no samples, so a 50%
        strategy could take over. The floor closes that."""
        mem = FakeTaskMemory([rec("swarm", True)] * 3 + [rec("swarm", False)] * 3)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_strategy == ""
        assert g.influenced_by_experience is False
        assert "below cold-start floor" in g.diagnostic_note

    def test_d06_current_already_best(self):
        mem = FakeTaskMemory([rec("single", True)] * 6 + [rec("swarm", False)] * 6)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_strategy == ""
        assert "already the best" in g.diagnostic_note

    def test_d07_empty_records(self):
        g = derive_experience_guidance("部署服务", "single", memory=FakeTaskMemory([]))
        assert g.influenced_by_experience is False
        assert g.scope_size == 0

    def test_d08_records_without_strategy(self):
        mem = FakeTaskMemory([rec("", True)] * 6)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_strategy == ""
        assert "strategy field" in g.diagnostic_note
        # Diagnostics must distinguish "no history" from "history, none usable".
        assert g.scope_size == 6

    def test_d08b_thin_scope_without_task_type_does_not_widen(self):
        """A thin lexical scope must NOT be padded with unrelated recent tasks.

        Widening to "recent tasks of any kind" answers a different question
        ("which strategy has worked lately") and reports it as a conclusion
        about *this* task — the exact defect this module removes.
        """

        class ThinThenFat:
            def __init__(self):
                self.recent_calls = 0

            def retrieve_similar(self, query, k=5, min_score=0.3):
                return [rec("swarm", True)] * 2  # below min_samples

            def get_recent_summaries(self, n=5, task_type=None):
                self.recent_calls += 1
                return [rec("swarm", True)] * 50

        mem = ThinThenFat()
        g = derive_experience_guidance("全新的任务", "single", memory=mem)  # no task_type
        assert mem.recent_calls == 0, "untyped scope must not widen"
        assert g.influenced_by_experience is False
        assert g.scope_size == 2

    def test_d08c_thin_scope_with_task_type_widens_to_that_type(self):
        """With a task_type, widening targets a real, nameable population."""

        class ThinThenTyped:
            def __init__(self):
                self.seen_task_type = None

            def retrieve_similar(self, query, k=5, min_score=0.3):
                return []

            def get_recent_summaries(self, n=5, task_type=None):
                self.seen_task_type = task_type
                # Distinct objects: the merge dedupes on summary_id, so repeating
                # one instance would collapse to a single record.
                return [rec("swarm", True) for _ in range(8)]

        mem = ThinThenTyped()
        g = derive_experience_guidance("全新的任务", "single", task_type="batch", memory=mem)
        assert mem.seen_task_type == "batch"
        assert g.candidate_strategy == "swarm"
        assert "task_type=batch" in g.diagnostic_note

    def test_d08d_scope_label_travels_with_the_reason(self):
        """A rate is meaningless without the population it was computed over."""
        mem = FakeTaskMemory([rec("swarm", True)] * 6 + [rec("single", False)] * 6)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.diagnostic_note.startswith("[scope=similar]")

    def test_d09_shadow_computes_but_does_not_influence(self, monkeypatch):
        monkeypatch.setenv("GALAXY_EXPERIENCE_GUIDANCE", "shadow")
        mem = FakeTaskMemory([rec("swarm", True)] * 6 + [rec("single", False)] * 6)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_strategy == "swarm"  # computed
        assert g.influenced_by_experience is False  # but inert
        assert g.mode == MODE_SHADOW

    def test_d10_off_never_touches_memory(self, monkeypatch):
        monkeypatch.setenv("GALAXY_EXPERIENCE_GUIDANCE", "off")
        mem = FakeTaskMemory([rec("swarm", True)] * 6)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.influenced_by_experience is False
        assert mem.retrieve_calls == 0
        assert mem.recent_calls == 0

    def test_d11_failing_backend_degrades_to_neutral(self):
        g = derive_experience_guidance("部署服务", "single", memory=BoomTaskMemory())
        assert g.influenced_by_experience is False
        assert g.candidate_strategy == ""

    def test_d12_ties_are_order_independent(self):
        records = [rec("aaa", True)] * 6 + [rec("zzz", True)] * 6 + [rec("single", False)] * 6
        forward = derive_experience_guidance("部署服务", "single", memory=FakeTaskMemory(records))
        reverse = derive_experience_guidance("部署服务", "single", memory=FakeTaskMemory(list(reversed(records))))
        assert forward.candidate_strategy == reverse.candidate_strategy

    def test_d13_denominator_is_the_real_population(self):
        """The point of the change: counts are exact, not a similarity sample."""
        mem = FakeTaskMemory([rec("swarm", True)] * 9 + [rec("swarm", False)] * 1)
        g = derive_experience_guidance("部署服务", "single", memory=mem)
        assert g.candidate_n == 10
        assert g.candidate_rate == pytest.approx(0.9)

    def test_d14_to_dict_json_safe(self):
        mem = FakeTaskMemory([rec("swarm", True)] * 6 + [rec("single", False)] * 6)
        payload = derive_experience_guidance("部署服务", "single", memory=mem).to_dict()
        json.dumps(payload)
        assert payload["candidate_strategy"] == "swarm"
        assert isinstance(payload["stats"], list)


# ---------------------------------------------------------------------------
# Group E — _pick_strategy integration
# ---------------------------------------------------------------------------


def _guidance(candidate: str, influenced: bool = True) -> ExperienceGuidance:
    return ExperienceGuidance(
        candidate_strategy=candidate,
        candidate_rate=0.95,
        candidate_n=10,
        influenced_by_experience=influenced,
        mode=MODE_ON,
        diagnostic_note="test",
    )


class _StubBreadth:
    influenced_by_budget = True
    complexity_threshold_adjustment = 0.0
    strategy_preference = "single"
    breadth_mode = "narrow"


class _StubMemoryContinuity:
    influenced_by_memory = True
    complexity_threshold_adjustment = 0.0
    prefer_single_agent = True
    posture = "continuity"


@pytest.fixture
def planner():
    from core.agent.execution_planner import ExecutionPlanner

    return ExecutionPlanner()


class TestGroupEPickStrategy:
    def test_e01_none_guidance_is_unchanged(self, planner):
        """Regression: absent guidance must reproduce historical selection."""
        assert planner._pick_strategy("do task", 0.50) == "single"
        assert planner._pick_strategy("do task", 0.70) == "specialized"
        assert planner._pick_strategy("do task", 0.80) == "fractal"

    @pytest.mark.parametrize(
        "message",
        ["普通任务", "递归深度拆解", "团队分工", "批量处理", "递归 团队", ""],
    )
    @pytest.mark.parametrize("complexity", [0.0, 0.30, 0.64, 0.65, 0.74, 0.75, 0.90])
    def test_e01b_inert_guidance_matches_no_guidance(self, planner, message, complexity):
        """An inert guidance must be indistinguishable from passing nothing.

        Guards the integration seam rather than the cascade itself: whatever
        _pick_strategy decides without guidance, it must decide identically when
        handed a guidance that declares no influence.
        """
        inert = ExperienceGuidance(candidate_strategy="swarm", influenced_by_experience=False, mode=MODE_ON)
        assert planner._pick_strategy(message, complexity) == planner._pick_strategy(
            message, complexity, experience_guidance=inert
        )

    def test_e02_redirects_implicit_choice(self, planner):
        # 0.50 reaches "single" implicitly (no keyword, no mapping).
        result = planner._pick_strategy("do task", 0.50, experience_guidance=_guidance("specialized"))
        assert result == "specialized"

    def test_e03_never_overrides_task_type_mapping(self, planner):
        result = planner._pick_strategy(
            "any task", 0.9, task_type="fast_response", experience_guidance=_guidance("swarm")
        )
        assert result == "single"  # mapping wins

    def test_e04_never_overrides_explicit_keyword(self, planner):
        # "递归" is an explicit fractal keyword at low complexity.
        result = planner._pick_strategy("递归深度拆解任务", 0.30, experience_guidance=_guidance("single"))
        assert result == "fractal"

    def test_e04b_never_overrides_swarm_keyword(self, planner):
        result = planner._pick_strategy("批量处理大量任务", 0.30, experience_guidance=_guidance("single"))
        assert result == "swarm"

    def test_e04c_keyword_wins_even_when_threshold_also_fires(self, planner):
        """A keyword that agrees with a crossed threshold is still explicit.

        Regression: an earlier draft marked the decision "implicit" whenever the
        complexity threshold branch matched first, so a high-complexity message
        that *also* carried an explicit fractal keyword could be redirected away
        from fractal by statistics — exactly what POLICY_3 forbids.
        """
        result = planner._pick_strategy("递归深度拆解任务", 0.90, experience_guidance=_guidance("single"))
        assert result == "fractal"

    def test_e04d_specialized_keyword_wins_when_threshold_also_fires(self, planner):
        result = planner._pick_strategy("团队分工处理", 0.70, experience_guidance=_guidance("single"))
        assert result == "specialized"

    def test_e05_never_overrides_budget_preference(self, planner):
        result = planner._pick_strategy(
            "do task",
            0.30,
            breadth_guidance=_StubBreadth(),
            experience_guidance=_guidance("swarm"),
        )
        assert result == "single"

    def test_e06_never_overrides_memory_continuity(self, planner):
        result = planner._pick_strategy(
            "do task",
            0.30,
            memory_guidance=_StubMemoryContinuity(),
            experience_guidance=_guidance("swarm"),
        )
        assert result == "single"

    def test_e07_uninfluenced_guidance_is_ignored(self, planner):
        result = planner._pick_strategy("do task", 0.50, experience_guidance=_guidance("swarm", influenced=False))
        assert result == "single"

    def test_e08_candidate_equal_to_base_is_noop(self, planner):
        result = planner._pick_strategy("do task", 0.50, experience_guidance=_guidance("single"))
        assert result == "single"


# ---------------------------------------------------------------------------
# Group F — Regression guards
# ---------------------------------------------------------------------------


class TestGroupFRegressionGuards:
    def test_f01_superseded_method_is_gone(self):
        from core.agent.execution_planner import ExecutionPlanner

        assert not hasattr(ExecutionPlanner, "_experience_strategy_adjust")
        assert hasattr(ExecutionPlanner, "_derive_experience_guidance")

    def test_f02_prose_regex_is_gone_from_decision_path(self):
        """The 策略[X]...结果[Y] regex must not come back."""
        import core.agent.execution_planner as mod

        src = inspect.getsource(mod)
        assert "策略\\[" not in src
        assert "结果\\[" not in src

    def test_f03_strategy_selection_does_not_recall_prose(self):
        """_derive_experience_guidance must not reach into core.memory."""
        from core.agent.execution_planner import ExecutionPlanner

        src = inspect.getsource(ExecutionPlanner._derive_experience_guidance)
        assert "get_unified_memory" not in src
        assert "recall" not in src
        assert "experience_guidance" in src

    def test_f04_flag_is_registered(self):
        from flags import get_flag

        flag = get_flag("experience_guidance")
        assert flag is not None
        assert flag.env_var == "GALAXY_EXPERIENCE_GUIDANCE"
        assert flag.default == "on"
        assert flag.cleanup_condition
        assert flag.rollout_plan
