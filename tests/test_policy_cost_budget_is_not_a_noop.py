"""策略层的成本预算此前是**结构性空转**:判定恒为真。

被修的 bug
----------
``core/unified/llm_router.py`` 里成本这条链原先是::

    def _estimate_cost_per_1k(self, provider, task_type_str):
        budget = rule.get("cost_budget") or {}
        return float(budget.get("max_cost_per_1k_tokens", 0.0))   # ← 返回的是【上限】

    cost_per_1k = self._estimate_cost_per_1k(provider_name, task_type_str)
    if not _check_cost_budget(cost_per_1k, task_type_str, self._policy):   # 上限 <= 上限
        logger.warning("LLM cost budget exceeded ...")

``_estimate_cost_per_1k`` **完全忽略 provider 参数**,返回的就是本任务 ``cost_budget``
的上限;``_check_cost_budget`` 拿它跟同一个上限比,于是恒等于 ``x <= x`` → 恒真。

两个后果:

* 那句超预算告警**不可达**,``cost_budget`` 在整个 YAML 里是装饰性的;
* 记进遥测的 ``cost_usd`` 是 ``tokens/1000 × 上限``,同一任务下每家一模一样 ——
  免费的 ollama 和 0.015/1k 的 anthropic 在 reasoning 下都被记成 0.15。

为什么单元测试没抓到
--------------------
``tests/test_pr6_block6.py`` **单测过** ``_check_cost_budget``:用手挑的 0.10 / 0.20 对
0.15 的上限,断言 True / False。函数是对的,测试也是对的 —— 错的是**接线**。这类
"单元绿、集成空"的 bug 只能靠端到端断言抓,所以本文件里的断言都从调用方那一侧发起。

判定这是 bug 而非"故意留空"
----------------------------
1. 真实单价一直就在同一个仓库里:``core.multi_llm_router.PROVIDER_REGISTRY`` 每家都有
   ``cost_in`` / ``cost_out``,经 ``ProviderConfig.cost_per_1k_input/output`` 暴露,统一层
   通过 ``self._backend.providers`` 就能拿到(``get_status()`` 早就这么访问了)。不是缺数据;
2. ``_estimate_cost_per_1k`` 签名里**带着 ``provider`` 参数却一次没用** —— 意图很明确,
   实现没跟上;
3. 策略 YAML 对 ``global_slo.max_cost_per_1k_tokens`` 的注释写着"超过此值触发降级",
   而在此之前没有任何东西会降级。

顺带补上的降级
--------------
既然 YAML 明写"触发降级",就按 SLO 降级那一套**完全相同**的做法补上:超预算的提供商往后
排(``affordable + pricey``),**只重排不删除**。贵的那家仍然可用,真到只剩它照样会被调用
—— 这一点由下面的 membership 断言守住。单价未知的一律不罚:openrouter 这类聚合器单价写 0
是因为真实成本随所选底层模型浮动,把"查不到"当成"超预算"会错杀。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.unified.llm_router import (
    RoutingTelemetry,
    _check_cost_budget,
    _cost_ceiling,
    _resolve_provider_order,
    reset_routing_telemetry,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def policy() -> dict:
    return yaml.safe_load((REPO_ROOT / "config/llm_routing_policy.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def rates() -> dict:
    from core.multi_llm_router import PROVIDER_REGISTRY

    return {s["name"]: float(s.get("cost_out", 0.0)) for s in PROVIDER_REGISTRY}


@pytest.fixture
def telemetry() -> RoutingTelemetry:
    reset_routing_telemetry()
    return RoutingTelemetry()


class TestTheOldWiringWasAlwaysTrue:
    """先证明这个 bug 真的存在过 —— 否则下面的断言只说明"新的是对的"。"""

    def test_old_estimate_fed_the_ceiling_into_its_own_check(self, policy):
        def old_estimate(provider: str, task_type: str) -> float:
            rule = policy.get("task_routing", {}).get(task_type, {})
            budget = rule.get("cost_budget") or {}
            return float(budget.get("max_cost_per_1k_tokens", 0.0))

        # 每个任务类型 × 每家提供商,旧接线都判"在预算内"。
        for task in policy["task_routing"]:
            for provider in ("ollama", "deepseek", "anthropic", "openai"):
                assert _check_cost_budget(old_estimate(provider, task), task, policy) is True

    def test_old_estimate_gave_every_provider_the_same_cost(self, policy):
        """免费的 ollama 与最贵的一家被记成一样贵 —— 遥测里的成本是编的。"""

        def old_estimate(provider: str, task_type: str) -> float:
            rule = policy.get("task_routing", {}).get(task_type, {})
            return float((rule.get("cost_budget") or {}).get("max_cost_per_1k_tokens", 0.0))

        got = {p: old_estimate(p, "reasoning") for p in ("ollama", "deepseek", "anthropic")}
        assert len(set(got.values())) == 1, "旧实现居然区分了各家?那本次改动的前提就错了"
        assert got["ollama"] == got["anthropic"] == 0.15


class TestEstimateNowReturnsRealPerProviderPrices:
    def test_prices_differ_across_providers(self, rates):
        """最基本的一条:各家单价必须不同,否则"按真实单价"是句空话。"""
        assert len(set(rates.values())) > 3, f"registry 单价没有区分度: {rates}"

    def test_free_local_and_expensive_cloud_are_not_equal(self, rates):
        assert rates["deepseek"] < rates["anthropic"], "便宜的反而比贵的贵?单价读错了"

    def test_estimate_ignores_task_type_and_follows_provider(self, rates):
        """单价是**提供商**的属性,跟任务类型无关 —— 原实现刚好搞反了。"""
        from core.unified.llm_router import UnifiedLLMRouter

        r = object.__new__(UnifiedLLMRouter)
        r._backend = _FakeBackend(rates)
        for task in ("reasoning", "fast_response", "coding"):
            assert r._estimate_cost_per_1k("deepseek", task) == rates["deepseek"]
            assert r._estimate_cost_per_1k("anthropic", task) == rates["anthropic"]

    def test_unknown_provider_returns_none_not_zero(self, rates):
        """``None`` 而不是 0.0:0 会被误读成"这家免费",预算判定又变成恒真。"""
        from core.unified.llm_router import UnifiedLLMRouter

        r = object.__new__(UnifiedLLMRouter)
        r._backend = _FakeBackend(rates)
        assert r._estimate_cost_per_1k("no_such_provider", "general") is None

    def test_missing_backend_degrades_quietly(self):
        from core.unified.llm_router import UnifiedLLMRouter

        r = object.__new__(UnifiedLLMRouter)
        r._backend = None
        assert r._provider_rates() == {}
        assert r._estimate_cost_per_1k("openai", "general") is None


class TestCostCheckCanNowActuallyFail:
    """判定必须真的会返回 False,否则改了半天还是恒真。"""

    def test_over_budget_is_rejected(self, policy, rates):
        # fast_response 上限 0.01,openai 输出单价 0.015 → 必须判超预算。
        assert _cost_ceiling("fast_response", policy) == pytest.approx(0.01)
        assert rates["openai"] > 0.01
        assert _check_cost_budget(rates["openai"], "fast_response", policy) is False

    def test_within_budget_is_accepted(self, policy, rates):
        assert _check_cost_budget(rates["deepseek"], "fast_response", policy) is True

    def test_free_provider_always_passes(self, policy):
        for task in policy["task_routing"]:
            assert _check_cost_budget(0.0, task, policy) is True


class TestCostDegradationReordersButNeverDrops:
    """降级的核心安全性质:只重排,不删除。"""

    def test_membership_is_preserved_for_every_task(self, policy, telemetry, rates):
        for task in policy["task_routing"]:
            before, _ = _resolve_provider_order(task, policy, telemetry, None, None)
            after, _ = _resolve_provider_order(task, policy, telemetry, None, rates)
            assert set(before) == set(after), f"{task}: 成本降级把 provider 弄丢了 —— 只许重排"
            assert len(before) == len(after), f"{task}: 长度变了,可能有重复或丢失"

    def test_the_expensive_ones_really_move_back(self, policy, telemetry, rates):
        """fast_response 上限 0.01,超出的必须在 **priorities 这一层里**被排到最后。

        2026-09-04 改判据 —— 原来这里写的是"openai/anthropic 都是 0.015,必须被排到
        后面",并对**整个返回列表**断言"所有便宜的都在所有贵的前面"。那个断言只在
        价格表凑巧的时候成立:

        · 返回的列表是两层拼起来的 —— ``priorities``(成本降级作用的那一层)在前,
          ``fallback_chain`` 在后。fallback 按定义就该排在所有 priorities 之后,
          不管它便宜不便宜,那是"前面全挂了才轮到你"的意思,不是排序失灵。
        · 当时 anthropic 是 0.015、跟 openai 一样超上限,两家都落在"贵"那一组、
          又都在尾部,跨层的断言才**碰巧**为真。
        · 之后 Claude Sonnet 5 的真实输出价是 $10/M(= 0.010),不超 0.01 上限,
          于是它成了"便宜的",却仍然因为身处 fallback 层而排在最后 —— 跨层断言
          当场失效。失效的是断言的前提,不是被测的行为。

        所以改成在**降级真正作用的那一层**上判,并补一条更硬的:openai 必须真的
        动过位置。只判"贵的在后面"是不够的 —— 如果它本来就在最后,不做任何降级
        也能过。
        """
        ceiling = _cost_ceiling("fast_response", policy)
        priorities = list(policy["task_routing"]["fast_response"]["priorities"])

        before, _ = _resolve_provider_order("fast_response", policy, telemetry, None, None)
        after, _ = _resolve_provider_order("fast_response", policy, telemetry, None, rates)

        in_tier = [p for p in after if p in priorities]
        pricey = [p for p in in_tier if rates.get(p, 0.0) > ceiling]
        assert pricey, "priorities 这一层里没有任何一家超出 fast_response 的上限?那这条测试失去意义"

        cheap_positions = [i for i, p in enumerate(in_tier) if p not in pricey]
        pricey_positions = [i for i, p in enumerate(in_tier) if p in pricey]
        assert max(cheap_positions) < min(pricey_positions), f"贵的没有被排到 priorities 层的最后: {in_tier}"

        # 反向保险:贵的那些必须真的**移动过**,而不是本来就在末尾。
        for p in pricey:
            assert before.index(p) < after.index(p), (
                f"{p} 超出上限却没有被往后挪(降级前 {before.index(p)} → 降级后 {after.index(p)})"
                f" —— 只判「贵的在后面」会让「本来就在后面」也蒙混过关。"
            )

    def test_order_changes_at_all(self, policy, telemetry, rates):
        """反向保险:如果传 rates 与不传毫无差别,说明这条路根本没接上。"""
        diffs = 0
        for task in policy["task_routing"]:
            before, _ = _resolve_provider_order(task, policy, telemetry, None, None)
            after, _ = _resolve_provider_order(task, policy, telemetry, None, rates)
            if before != after:
                diffs += 1
        assert diffs >= 1, "成本降级对任何任务类型都没有影响 —— 没接上"

    def test_unknown_price_is_never_penalised(self, policy, telemetry):
        """单价查不到 ≠ 超预算。聚合器 openrouter 单价写 0 正是这种情况。"""
        partial = {"openai": 99.0}  # 只知道 openai 巨贵,其余全未知
        after, _ = _resolve_provider_order("general", policy, telemetry, None, partial)
        assert after[-1] == "openai", f"只有已知超预算的那家该被降级: {after}"
        assert after[0] == "ollama", "未知单价的本地主脑被误罚了"

    def test_no_rates_means_no_degradation(self, policy, telemetry):
        for task in policy["task_routing"]:
            a, _ = _resolve_provider_order(task, policy, telemetry, None, None)
            b, _ = _resolve_provider_order(task, policy, telemetry, None, {})
            assert a == b, f"{task}: 空单价表不应改变任何顺序"

    def test_local_first_survives_cost_degradation(self, policy, telemetry, rates):
        """本地主脑打头是仓库明文设计,成本降级不能把它顶掉(它免费,本就不该被罚)。"""
        for task in policy["task_routing"]:
            after, _ = _resolve_provider_order(task, policy, telemetry, None, rates)
            assert after[0] == "ollama", f"{task}: 成本降级破了 LOCAL-FIRST: {after[:3]}"

    def test_preferred_provider_is_exempt_from_cost_degradation(self, policy, telemetry, rates):
        """显式指定的 provider 豁免成本降级 —— 它必须仍然排第一。

        openai 的单价 0.015 超出 fast_response 的 0.01 上限,若不豁免就会被挪到队尾,
        点名要 openai 的调用方却拿到别家。预算是**默认**偏好,显式指定是覆盖。

        我最初没做这个豁免,而是写了一条"openai 不在最后一位"的断言 —— 它当时是绿的,
        但绿的原因是 anthropic 也超预算、排在它后面,跟"豁免"毫无关系。这种"因为别的
        原因而通过"的断言比没有断言更坏,所以改成直接断言首位。
        """
        after, _ = _resolve_provider_order("fast_response", policy, telemetry, "openai", rates)
        assert after[0] == "openai", f"显式指定的 provider 被成本降级挪走了: {after}"

    def test_slo_degradation_still_applies_to_the_preferred_provider(self, policy, rates):
        """不对称的另一半:SLO 降级**不**豁免显式指定。

        依据不同 —— SLO 降级的理由是"这家实测正在坏",那是覆盖显式选择的正当理由;
        成本只是默认偏好。这条把这个取舍钉住,免得日后被"统一一下"抹平。
        """
        reset_routing_telemetry()
        tel = RoutingTelemetry()
        for _ in range(5):  # 超过 is_slo_violated 的 3 次样本门槛
            tel.record("openai", success=False, latency_ms=999_999.0)
        after, _ = _resolve_provider_order("fast_response", policy, tel, "openai", rates)
        assert after[0] != "openai", f"实测正在坏的 provider 仍被排在首位: {after[:3]}"
        assert "openai" in after, "SLO 降级也只许重排,不许删除"


class TestCeilingResolution:
    def test_task_ceiling_wins_over_global(self, policy):
        assert _cost_ceiling("fast_response", policy) == pytest.approx(0.01)
        assert _cost_ceiling("reasoning", policy) == pytest.approx(0.15)

    def test_unknown_task_falls_back_to_global(self, policy):
        expected = policy["global_slo"]["max_cost_per_1k_tokens"]
        assert _cost_ceiling("no_such_task", policy) == pytest.approx(expected)

    def test_empty_policy_means_no_ceiling(self):
        assert _cost_ceiling("anything", {}) == float("inf")

    def test_no_ceiling_disables_degradation(self, telemetry, rates):
        """无上限时不能因为"查得到单价"就乱排。"""
        bare = {"task_routing": {"t": {"priorities": ["openai", "deepseek"]}}}
        after, _ = _resolve_provider_order("t", bare, telemetry, None, rates)
        assert after[:2] == ["openai", "deepseek"], f"无上限却发生了降级: {after}"


class TestRequireToolsConstraintIsNoLongerDead:
    """``constraints.require_tools`` 此前**全仓库零读取**。

    它在策略 YAML 的"字段说明"里明写着是可选约束之一,``agent_control`` 也确实设了
    ``require_tools: true``,但没有任何代码读它。

    今天还没被违反:registry 里唯一 ``supports_tools=False`` 的是 perplexity,而它不在
    agent_control 的 priorities 里。所以这是**潜在**缺口而非现行故障 —— 记在这里是因为
    它离故障只有一次 YAML 编辑的距离(perplexity 是搜索型 provider,往 agent 任务里加它
    很自然),而策略里那句 require_tools 全程无声。
    """

    def test_the_field_is_actually_declared_in_the_policy(self, policy):
        """前提:确实有任务类型要求工具。否则这一整组测试是在空气上跑。"""
        requiring = [t for t, r in policy["task_routing"].items() if (r.get("constraints") or {}).get("require_tools")]
        assert requiring == ["agent_control"], f"要求工具的任务类型变了: {requiring}"

    def test_registry_has_at_least_one_tool_incapable_provider(self):
        """前提:有不支持工具的 provider,否则这条约束永远无从体现。"""
        from core.multi_llm_router import PROVIDER_REGISTRY

        incapable = [s["name"] for s in PROVIDER_REGISTRY if (s.get("extra") or {}).get("supports_tools") is False]
        assert incapable, "registry 里已经没有不支持工具的 provider 了"

    def test_tool_incapable_provider_is_demoted_when_required(self, policy, telemetry):
        caps = {"ollama": True, "anthropic": True, "openai": True, "deepseek": True, "perplexity": False}
        p = dict(policy)
        p["task_routing"] = dict(policy["task_routing"])
        rule = dict(p["task_routing"]["agent_control"])
        # 把不支持工具的那家硬塞进 agent_control —— 也就是"下一次 YAML 编辑"的样子
        rule["priorities"] = ["ollama", "perplexity", "anthropic"]
        p["task_routing"]["agent_control"] = rule

        after, _ = _resolve_provider_order("agent_control", p, telemetry, None, None, caps)
        assert after.index("perplexity") > after.index("anthropic"), f"不支持工具的没被降级: {after}"
        assert "perplexity" in after, "只许重排,不许删除 —— 真到只剩它,仍应被尝试"

    def test_no_demotion_when_the_task_does_not_require_tools(self, policy, telemetry):
        caps = {"perplexity": False}
        before, _ = _resolve_provider_order("analysis", policy, telemetry, None, None, None)
        after, _ = _resolve_provider_order("analysis", policy, telemetry, None, None, caps)
        assert before == after, "analysis 的 require_tools 是 false,不该发生任何重排"

    def test_unknown_capability_is_treated_as_capable(self, policy, telemetry):
        """查不到就放行:registry 的 supports_tools 默认为 True,反过来会误伤一大片。"""
        before, _ = _resolve_provider_order("agent_control", policy, telemetry, None, None, None)
        after, _ = _resolve_provider_order("agent_control", policy, telemetry, None, None, {"nobody": False})
        assert before == after

    def test_todays_policy_has_no_actual_violation(self, policy, telemetry):
        """如实记录现状:当前配置下这条约束不改变任何顺序。

        这条测试的价值在于**将来它会变红** —— 一旦有人把不支持工具的 provider 加进
        agent_control,这里就会提示"现在这条约束真的生效了,请确认是有意的"。
        """
        from core.multi_llm_router import PROVIDER_REGISTRY

        caps = {s["name"]: (s.get("extra") or {}).get("supports_tools", True) for s in PROVIDER_REGISTRY}
        before, _ = _resolve_provider_order("agent_control", policy, telemetry, None, None, None)
        after, _ = _resolve_provider_order("agent_control", policy, telemetry, None, None, caps)
        assert before == after, (
            "agent_control 里出现了不支持工具的 provider,约束开始生效 —— "
            f"若是有意的请更新本测试说明。顺序: {before} → {after}"
        )

    def test_capability_map_is_read_from_the_backend(self):
        from core.unified.llm_router import UnifiedLLMRouter

        r = object.__new__(UnifiedLLMRouter)
        r._backend = _FakeBackend({"a": 0.001, "b": 0.002}, tools={"a": True, "b": False})
        assert r._tool_capable() == {"a": True, "b": False}

    def test_capability_map_empty_without_backend(self):
        from core.unified.llm_router import UnifiedLLMRouter

        r = object.__new__(UnifiedLLMRouter)
        r._backend = None
        assert r._tool_capable() == {}


class TestEveryPolicyFieldIsNowEitherUsedOrKnown:
    """把"策略层每个字段的去向"这件事本身钉住。

    这次排查的起因就是"YAML 里写了一堆东西,但哪些真的生效?"。答案当时是:priorities /
    fallback_chain / slo 生效,cost_budget 空转,constraints 零读取。修完之后除了
    ``version`` 都生效了 —— 把这个结论写成测试,下次加字段时才不会又悄悄多一个装饰品。
    """

    #: 已知**不驱动任何行为**的字段,以及为什么可以这样。
    KNOWN_INERT = {"version"}

    def test_all_top_level_fields_are_accounted_for(self, policy):
        import inspect

        from core.unified import llm_router as unified

        src = inspect.getsource(unified)
        unaccounted = [k for k in policy if k not in self.KNOWN_INERT and f'"{k}"' not in src]
        assert not unaccounted, f"策略顶层字段 {unaccounted} 在统一层里没有任何读取点 —— 装饰品"

    def test_all_rule_level_fields_are_accounted_for(self, policy):
        import inspect

        from core.unified import llm_router as unified

        src = inspect.getsource(unified)
        fields = set()
        for rule in policy["task_routing"].values():
            fields |= set(rule)
        unaccounted = sorted(f for f in fields if f'"{f}"' not in src)
        assert not unaccounted, f"任务规则字段 {unaccounted} 没有任何读取点 —— 装饰品"

    def test_the_nested_budget_and_slo_keys_are_read(self, policy):
        import inspect

        from core.unified import llm_router as unified

        src = inspect.getsource(unified)
        for key in ("max_cost_per_1k_tokens", "max_latency_ms", "min_success_rate", "require_tools"):
            assert key in src, f"{key} 在统一层没有读取点"


class _FakeBackend:
    """只提供 ``providers`` 映射,模拟 MultiLLMRouter 的那一面。"""

    def __init__(self, rates: dict, tools: dict | None = None):
        tools = tools or {}
        self.providers = {name: _FakeCfg(rate, tools.get(name, True)) for name, rate in rates.items()}


class _FakeCfg:
    def __init__(self, rate: float, supports_tools: bool = True):
        self.cost_per_1k_output = rate
        self.cost_per_1k_input = rate / 2.0
        self.supports_tools = supports_tools
