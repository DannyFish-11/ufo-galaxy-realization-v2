"""开闭源按【模型】判定 + 选脑打分接上实测表现。

被修的两个问题
--------------
**一、同一个 provider,排序时算开源、打分时算非开源。**

``meta`` 和 ``openrouter`` 在 ``OPEN_SOURCE_PROVIDERS`` / ``PROPRIETARY_PROVIDERS``
**两个集合都没登记**,而两处消费点对"未登记"的处理正好相反:

* ``reorder_open_source_first()`` —— ``p not in PROPRIETARY_PROVIDERS`` → 未登记算开源;
* ``_score()`` —— ``if name in OPEN_SOURCE_PROVIDERS: score += 0.15`` → 未登记拿不到加分。

而且 provider 粒度本身就表达不了现实:``moonshot`` 同时供 ``kimi-k2.*``(开放权重)和
``moonshot-v1-*``(闭源),却被整家登记成开源 —— 闭源那个型号一直在白拿开源加分。
所有者的判断是「它开源和闭源的都有,按照它那个模型区分开来就行了」。

**二、选脑打分完全没接实测表现。**

仓库里有一套写得很完整的 L3 bandit(UCB1:成功率 − 延迟/成本/啰嗦惩罚 + 探索项,
未试过乐观初始化,冷启动退回原序),但它**全仓只被调用一处** —— ``route()``。
agent 团队选脑走的是另一条路(``agent_team`` → ``select_brain_for_role`` →
``select_brain_for_task`` → ``_score``),那条路只吃手工维护的
``PROVIDER_QUALITY_TIER``,拿不到任何真实反馈。所有者原话:「这玩意不应该交给智能
路由自己选吗」。接上之后手写档位退化为冷启动先验,有实测数据时由实测修正。
"""

from __future__ import annotations

import pytest

from core.model_openness import (
    OPENNESS_CLOSED,
    OPENNESS_MIXED,
    OPENNESS_OPEN,
    OPENNESS_UNKNOWN,
    audit_registry,
    is_open_weight,
    provider_openness,
    treat_as_open_source,
)


class TestModelLevelVerdicts:
    @pytest.mark.parametrize(
        "model",
        [
            "Llama-4-Maverick-17B-128E-Instruct-FP8",
            "Llama-4-Scout-17B-16E-Instruct-FP8",
            "llama-3.3-70b-versatile",
            "deepseek-v4-pro",
            "deepseek-reasoner",
            "qwen3.7-max",
            "glm-5.1",
            "kimi-k2.6",
            "mistral-large-3",
            "MiniMax-M3",
            "gemma4:e2b",
            "minicpm-o4.5",
            "step-3.7-flash",
            "mimo-v2.5-pro",
        ],
    )
    def test_open_weight_models(self, model):
        assert is_open_weight(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-5.6",
            "gpt-4o",
            "o3-mini",
            "claude-opus-4-8-20250529",
            "claude-sonnet-5",
            "gemini-3.5-pro",
            "grok-4.5",
            "sonar-pro",
            "sonar-deep-research",
            "moonshot-v1-128k",
        ],
    )
    def test_closed_weight_models(self, model):
        assert is_open_weight(model) is False

    @pytest.mark.parametrize("model", ["agnes-2.5-flash", "openrouter/auto", "", "   ", "某个没听过的型号"])
    def test_undecidable_returns_none_not_false(self, model):
        """判不出来必须是 None,**不能**是 False。

        None 的语义是"本模块无法判定,请回落到既有 provider 级登记";若返回 False,
        调用方会当成"闭源",于是静默改掉别人明确写过的分类(``agnes`` 就在
        ``OPEN_SOURCE_PROVIDERS`` 里)。这两者绝不能混。
        """
        assert is_open_weight(model) is None

    def test_none_and_non_str_are_safe(self):
        assert is_open_weight(None) is None  # type: ignore[arg-type]
        assert is_open_weight(123) is None  # type: ignore[arg-type]

    def test_aggregator_namespace_prefix_is_stripped(self):
        """聚合器把型号写成 ``上游/型号``。只看整串会全落"未知",取最后一段才判得出。"""
        assert is_open_weight("meta-llama/llama-3.3-70b") is True
        assert is_open_weight("deepseek/deepseek-chat") is True
        assert is_open_weight("openai/gpt-4o") is False

    def test_closed_pattern_wins_over_open_for_same_vendor(self):
        """同厂两种权重状态:kimi-* 开放、moonshot-v1-* 闭源,不能互相吃掉。"""
        assert is_open_weight("kimi-k2.5") is True
        assert is_open_weight("moonshot-v1-128k") is False


class TestProviderOpenness:
    def test_all_open(self):
        assert provider_openness(["deepseek-v4-pro", "deepseek-chat"]) == OPENNESS_OPEN

    def test_all_closed(self):
        assert provider_openness(["gpt-5.6", "gpt-4o"]) == OPENNESS_CLOSED

    def test_mixed_is_the_whole_point(self):
        """provider 粒度表达不了的那种情形 —— 正是要按模型判的理由。"""
        assert provider_openness(["kimi-k2.6", "moonshot-v1-128k"]) == OPENNESS_MIXED

    def test_unknown_when_nothing_decidable(self):
        assert provider_openness(["agnes-2.5-flash"]) == OPENNESS_UNKNOWN

    def test_empty_is_unknown_not_crash(self):
        assert provider_openness([]) == OPENNESS_UNKNOWN
        assert provider_openness(None) == OPENNESS_UNKNOWN  # type: ignore[arg-type]


class TestTreatAsOpenSourceResolutionOrder:
    OPEN = frozenset({"deepseek", "agnes", "moonshot"})
    PROP = frozenset({"openai", "anthropic"})

    def _call(self, provider, model):
        return treat_as_open_source(provider, model, open_source_providers=self.OPEN, proprietary_providers=self.PROP)

    def test_model_verdict_beats_provider_registration(self):
        """模型级优先 —— 这正是所有者要的"按模型区分"。

        ``moonshot`` 整家登记为开源,但 ``moonshot-v1-128k`` 是闭源型号,必须判非开源。
        这是本次改动里唯一一处**行为变化**:该型号不再白拿 +0.15。
        """
        assert self._call("moonshot", "moonshot-v1-128k") is False
        assert self._call("moonshot", "kimi-k2.6") is True

    def test_falls_back_to_provider_when_model_undecidable(self):
        """``agnes-*`` 判不出来 → 沿用 agnes 既有的开源登记,不擅自改判。"""
        assert self._call("agnes", "agnes-2.5-flash") is True

    def test_falls_back_to_proprietary_registration(self):
        assert self._call("openai", "某个没见过的型号") is False

    def test_unregistered_provider_with_undecidable_model_defaults_to_open(self):
        """与 reorder_open_source_first() 的成文约定一致:未知按开源处理。

        原先 ``_score()`` 对这种情况是**不给**加分的,两处因此矛盾 —— 这条钉住修复。
        """
        assert self._call("openrouter", "openrouter/auto") is True

    def test_unregistered_provider_with_open_model(self):
        """meta 的实际情形:两个集合都没登记,但型号是 Llama-4 → 按模型判为开源。"""
        assert self._call("meta", "Llama-4-Maverick-17B-128E-Instruct-FP8") is True


class TestAgainstTheRealRegistry:
    """拿仓库真实的 PROVIDER_REGISTRY 跑,确认没有意外改动既有分类。"""

    @staticmethod
    def _audit():
        from core.multi_llm_router import PROVIDER_REGISTRY

        return audit_registry({s["name"]: s.get("models") or [] for s in PROVIDER_REGISTRY})

    def test_previously_declared_providers_keep_their_classification(self):
        """核心安全性断言:凡是原先明确登记过的,判定结果必须与登记一致。

        本模块的目的是补上"未登记"的那几个,**不是**重新裁决已登记的。任何一处不一致
        都意味着我在静默改别人写过的决定。
        """
        from core.multi_llm_router import OPEN_SOURCE_PROVIDERS, PROPRIETARY_PROVIDERS

        audit = self._audit()
        conflicts = []
        for provider, info in audit.items():
            verdict = info["openness"]
            if verdict in (OPENNESS_UNKNOWN, OPENNESS_MIXED):
                continue  # 判不出来 → 回落;mixed → 本就该按模型分,不该有整家结论
            if provider in OPEN_SOURCE_PROVIDERS and verdict != OPENNESS_OPEN:
                conflicts.append(f"{provider}: 登记为开源但按模型判是 {verdict}")
            if provider in PROPRIETARY_PROVIDERS and verdict != OPENNESS_CLOSED:
                conflicts.append(f"{provider}: 登记为专有但按模型判是 {verdict}")
        assert not conflicts, f"按模型判定与既有登记冲突(会静默改掉既有决定): {conflicts}"

    def test_meta_resolves_to_open_by_its_models(self):
        assert self._audit()["meta"]["openness"] == OPENNESS_OPEN

    def test_moonshot_is_detected_as_mixed(self):
        """真实数据里确实存在 provider 粒度表达不了的一家 —— 证明这个改动不是空谈。"""
        assert self._audit()["moonshot"]["openness"] == OPENNESS_MIXED

    def test_agnes_stays_undecidable_so_its_registration_is_respected(self):
        assert self._audit()["agnes"]["openness"] == OPENNESS_UNKNOWN

    def test_no_previously_classified_provider_became_undecidable(self):
        """反向的安全网:如果哪家原先能判、现在整家判不出来了,说明模式表退化了。"""
        audit = self._audit()
        core_four = ("openai", "anthropic", "deepseek", "qwen")
        for p in core_four:
            assert audit[p]["openness"] != OPENNESS_UNKNOWN, f"{p} 整家判不出来了"


class TestObservedPerformanceReachesBrainSelection:
    """``_score()`` 必须真的读 bandit 统计 —— 只加代码不等于接上了。"""

    def test_score_consults_the_bandit(self):
        """白盒:确认 ``select_brain_for_task`` 里真的调了 ``_bandit_score``。

        用源码断言而不是行为断言的理由:要构造"实测数据改变了选择结果"的行为用例,
        得先把 provider 注册齐、再灌一批 call_history。这里先钉住"这段代码在"这个
        最容易被后人删掉的点;真行为由本文件末尾的
        ``TestObservedSignalActuallyChangesTheWinner`` 覆盖(造两个静态条件完全平手的
        provider,只让历史成功率不同,断言赢家跟着变、且跟着历史翻转)。
        """
        import inspect

        from core.multi_llm_router import MultiLLMRouter

        src = inspect.getsource(MultiLLMRouter.select_brain_for_task)
        assert "_bandit_score" in src, "选脑打分没有读 bandit —— 实测表现没接进来"
        # 取历史统计走 _bandit_stats(它内部才调 _provider_stats)。第一版这里断言的是
        # _provider_stats,把"抄了一遍回退逻辑"那个写法钉死了 —— 后来把重复逻辑提成
        # _bandit_stats 时这条就炸了。炸得对:它确实在承重。改断言到正确的那一层。
        assert "_bandit_stats" in src, "选脑打分没有取历史统计"

    def test_score_uses_per_model_openness_not_provider_set(self):
        """必须比对**去掉注释后**的源码。

        第一版直接在整份源码里搜 ``name in OPEN_SOURCE_PROVIDERS``,被自己的说明注释
        绊倒了 —— 那段注释里正引用着这行旧代码来解释改动理由。白盒断言搜的是"代码里
        还有没有这个写法",不是"文本里有没有出现过这串字"。
        """
        import inspect
        import re as _re

        from core.multi_llm_router import MultiLLMRouter

        raw = inspect.getsource(MultiLLMRouter.select_brain_for_task)
        code = _re.sub(r"#.*$", "", raw, flags=_re.M)
        assert "_treat_as_open_source" in code, "打分仍按 provider 猜开源,没有按模型判"
        assert "name in OPEN_SOURCE_PROVIDERS" not in code, "旧的 provider 粒度判定还在"

    def test_untried_provider_does_not_hijack_selection(self):
        """``_bandit_score`` 对没试过的返回 +inf。若直接加进分数,一个从未试过的
        provider 会压过一切、抢走整个 agent 的活。必须被排除。"""
        import inspect

        from core.multi_llm_router import MultiLLMRouter

        src = inspect.getsource(MultiLLMRouter.select_brain_for_task)
        assert 'b != float("inf")' in src, "没有排除未试过的 provider(+inf)"

    def test_observed_weight_is_configurable_and_defaults_to_one(self, monkeypatch):
        """权重要能关掉 —— 出问题时得有回退开关。"""
        import inspect

        from core.multi_llm_router import MultiLLMRouter

        src = inspect.getsource(MultiLLMRouter.select_brain_for_task)
        assert "GALAXY_ROUTE_OBSERVED_WEIGHT" in src
        assert '"1.0"' in src, "默认权重不是 1.0"


class TestReorderStaysCoarseOnPurpose:
    """预排序刻意保持 provider 粗粒度 —— 别让后人"顺手改成"按模型判而弄出新矛盾。"""

    def test_reorder_is_still_provider_level(self):
        import inspect

        from core.multi_llm_router import reorder_open_source_first

        src = inspect.getsource(reorder_open_source_first)
        assert "PROPRIETARY_PROVIDERS" in src

    def test_docstring_explains_why_it_is_not_per_model(self):
        """这条防的是"没写理由 → 下一个人以为是漏改 → 改出不一致"。"""
        from core.multi_llm_router import reorder_open_source_first

        doc = reorder_open_source_first.__doc__ or ""
        assert "预排序" in doc and "select_model_by_complexity" in doc

    def test_both_paths_agree_on_unregistered_providers(self):
        """两处对未登记 provider 的结论必须一致,否则又回到"排序算开源、打分算非开源"。"""
        from core.multi_llm_router import (
            OPEN_SOURCE_PROVIDERS,
            PROPRIETARY_PROVIDERS,
            reorder_open_source_first,
        )

        unregistered = "某个未登记的家"
        assert unregistered not in OPEN_SOURCE_PROVIDERS
        assert unregistered not in PROPRIETARY_PROVIDERS
        # 排序侧:未登记的排在专有之前(即被当成开源)
        ordered = reorder_open_source_first([unregistered, "openai"])
        assert ordered.index(unregistered) < ordered.index("openai")
        # 打分侧:同样按开源处理
        assert (
            treat_as_open_source(
                unregistered,
                "判不出来的型号",
                open_source_providers=frozenset(OPEN_SOURCE_PROVIDERS),
                proprietary_providers=frozenset(PROPRIETARY_PROVIDERS),
            )
            is True
        )


class TestObservedSignalActuallyChangesTheWinner:
    """真行为:同样的候选,只因历史表现不同,选出的脑就不同。

    上面那组白盒断言只能证明"这段代码在",证明不了"它真的起作用"。这一组构造两个
    静态先验完全相同的 provider(同 quality tier、同成本、同延迟),只让 call_history
    里的成功率不同,断言赢家跟着变 —— 这才是"交给智能路由自己选"的可验证形式。
    """

    @staticmethod
    def _router(history):
        """造一个只有两个候选的 router,绕开真实的 provider 发现(要网络/密钥)。"""
        from core.multi_llm_router import (
            MultiLLMRouter,
            ProviderCircuitBreaker,
            ProviderConfig,
            TaskType,
        )

        r = MultiLLMRouter.__new__(MultiLLMRouter)
        r.providers = {}
        r.adapters = {}
        r.circuit_breakers = {}
        # 两家静态条件【完全一致】:同 tier(都不在 QUALITY_TIER 表里→都兜底 2)、
        # 同成本、同延迟、模型都判不出开闭源(→都回落到未登记→都算开源)。
        # 于是静态打分必然平手,唯一的区别只剩历史表现。
        for name in ("alpha_vendor", "beta_vendor"):
            cfg = ProviderConfig(
                name=name,
                api_key="k",
                base_url="http://localhost",
                models=[f"{name}-x1"],
                default_model=f"{name}-x1",
            )
            cfg.cost_per_1k_output = 0.001
            cfg.latency_avg_ms = 100.0
            r.providers[name] = cfg
            r.adapters[name] = object()
            r.circuit_breakers[name] = ProviderCircuitBreaker(name)
        r.call_history = list(history)
        return r, TaskType

    @staticmethod
    def _hist(provider, *, calls, successes, task="general"):
        return [
            {
                "provider": provider,
                "task_type": task,
                "success": i < successes,
                "latency_ms": 100.0,
                "cost": 0.001,
                "tokens_out": 100,
            }
            for i in range(calls)
        ]

    def test_static_priors_are_a_genuine_tie_without_history(self):
        """判别前提:没有历史时两家必须真的平手。

        若静态条件本就不平,下面那条"赢家跟着历史变"就没有判别力 —— 可能只是静态
        差异在起作用。这条先把前提钉死。
        """
        from core.multi_llm_router import PROVIDER_QUALITY_TIER

        assert "alpha_vendor" not in PROVIDER_QUALITY_TIER
        assert "beta_vendor" not in PROVIDER_QUALITY_TIER
        assert is_open_weight("alpha_vendor-x1") is None
        assert is_open_weight("beta_vendor-x1") is None

    def test_better_observed_success_rate_wins(self):
        r, TaskType = self._router(
            self._hist("alpha_vendor", calls=20, successes=4)  # 20% 成功
            + self._hist("beta_vendor", calls=20, successes=19)  # 95% 成功
        )
        d = r.select_brain_for_task(TaskType.GENERAL, complexity_score=0.6)
        assert d.provider == "beta_vendor", f"实测表现没起作用,选了 {d.provider}({d.reason})"

    def test_the_winner_flips_when_history_flips(self):
        """把历史反过来,赢家必须跟着反 —— 排除"恰好总选 beta"这种假通过。"""
        r, TaskType = self._router(
            self._hist("alpha_vendor", calls=20, successes=19) + self._hist("beta_vendor", calls=20, successes=4)
        )
        d = r.select_brain_for_task(TaskType.GENERAL, complexity_score=0.6)
        assert d.provider == "alpha_vendor", f"赢家没跟着历史翻转,选了 {d.provider}"

    def test_observed_weight_zero_restores_the_tie(self):
        """反向验证:把权重调 0,实测信号必须失效、退回静态平手(稳定排序取第一个)。

        证明那一项确实是承重的 —— 而不是赢家由别的因素决定、我只是恰好看到想看的结果。
        """
        import os

        r, TaskType = self._router(
            self._hist("alpha_vendor", calls=20, successes=4) + self._hist("beta_vendor", calls=20, successes=19)
        )
        os.environ["GALAXY_ROUTE_OBSERVED_WEIGHT"] = "0"
        try:
            d = r.select_brain_for_task(TaskType.GENERAL, complexity_score=0.6)
        finally:
            os.environ.pop("GALAXY_ROUTE_OBSERVED_WEIGHT", None)
        assert d.provider == "alpha_vendor", "权重归零后实测信号仍在影响结果,说明它没被真正关掉"

    def test_too_few_samples_falls_back_to_static(self):
        """样本不足(< 5)时不该让噪声决定选择 —— 与 _bandit_reorder 的 min_samples 同口径。"""
        r, TaskType = self._router(self._hist("beta_vendor", calls=2, successes=2))
        d = r.select_brain_for_task(TaskType.GENERAL, complexity_score=0.6)
        assert d.provider == "alpha_vendor", "样本不足时不应被少量历史带偏"


class TestBanditSampleFloorIsNotDuplicated:
    """样本阈值只能有一处 —— 否则"重排认为够、打分认为不够"会分裂。

    接实测表现时我把 ``_bandit_reorder`` 的两级回退**抄了一遍**,还把 5 写成字面量,
    而那边是 ``min_samples`` 参数。这组钉住去重后的形态。
    """

    def test_threshold_lives_in_one_place(self):
        from core.multi_llm_router import MultiLLMRouter

        assert MultiLLMRouter.BANDIT_MIN_SAMPLES == 5

    def test_no_hardcoded_five_in_either_consumer(self):
        """反向验证:两处都不许再出现裸的 5 当阈值。"""
        import inspect
        import re as _re

        from core.multi_llm_router import MultiLLMRouter

        for fn in (MultiLLMRouter.select_brain_for_task, MultiLLMRouter._bandit_reorder):
            code = _re.sub(r"#.*$", "", inspect.getsource(fn), flags=_re.M)
            assert not _re.search(r"<\s*5\b|>=\s*5\b", code), f"{fn.__name__} 里还有硬编码的样本阈值 5"

    def test_both_consumers_go_through_the_shared_helper(self):
        import inspect

        from core.multi_llm_router import MultiLLMRouter

        for fn in (MultiLLMRouter.select_brain_for_task, MultiLLMRouter._bandit_reorder):
            assert "_bandit_stats" in inspect.getsource(fn), f"{fn.__name__} 没走共享的统计取数"

    def test_helper_returns_zero_total_when_samples_insufficient(self):
        from core.multi_llm_router import MultiLLMRouter, TaskType

        r = MultiLLMRouter.__new__(MultiLLMRouter)
        r.call_history = [
            {"provider": "x", "task_type": "general", "success": True, "latency_ms": 1, "cost": 0, "tokens_out": 1}
        ]
        stats, total = r._bandit_stats(TaskType.GENERAL)
        assert (stats, total) == ({}, 0), "样本不足时必须返回 ({}, 0),让调用方退回静态行为"

    def test_helper_returns_stats_when_samples_sufficient(self):
        from core.multi_llm_router import MultiLLMRouter, TaskType

        r = MultiLLMRouter.__new__(MultiLLMRouter)
        r.call_history = [
            {"provider": "x", "task_type": "general", "success": True, "latency_ms": 1, "cost": 0, "tokens_out": 1}
            for _ in range(5)
        ]
        stats, total = r._bandit_stats(TaskType.GENERAL)
        assert total == 5 and "x" in stats

    def test_reorder_still_falls_back_to_original_order(self):
        """去重不能改掉 _bandit_reorder 原有的冷启动语义:样本不足原样返回。"""
        from core.multi_llm_router import MultiLLMRouter, TaskType

        r = MultiLLMRouter.__new__(MultiLLMRouter)
        r.call_history = []
        cands = ["a", "b", "c"]
        assert r._bandit_reorder(list(cands), TaskType.GENERAL) == cands


class TestDeadCostPolicyRemoved:
    """``route_with_cost_policy()`` 已删除,并且不该被重新加回来。

    删除依据(当时逐条查证过):

    1. **全仓零外部引用** —— 没有测试、文档或治理哨兵提及它;
    2. **成本策略已由统一层真实承担** —— ``config/llm_routing_policy.yaml`` 按任务类型
       配 ``cost_budget.max_cost_per_1k_tokens``,``_check_cost_budget()`` 在
       ``core/unified/llm_router.py:788`` 被真实调用,经 ``openclawd.py:1263`` 进入;
    3. **它的打分是 ``select_brain_for_task()`` 的较弱重复** —— 没有质量档、没有实测
       表现、没有按模型判开闭源。

    我一度打算"把它接上"。查清第 2 点后反过来了:接上等于造出**第二套互相竞争的成本
    策略**,正是本轮合并 7 份重复助手要消除的那类漂移。
    """

    def test_the_method_is_gone(self):
        from core.multi_llm_router import MultiLLMRouter

        assert not hasattr(MultiLLMRouter, "route_with_cost_policy")

    def test_the_unified_layer_really_owns_cost_policy(self):
        """删除的前提必须成立:统一层的成本策略是真的在跑,不是另一处死代码。

        没有这条,上面那个删除就只是"删了个我说没用的东西"。
        """
        import inspect

        from core.unified import llm_router as unified

        assert hasattr(unified, "_check_cost_budget"), "统一层没有成本预算检查 —— 删除前提不成立"
        # 必须有真实调用点,而不只是定义
        src = inspect.getsource(unified)
        assert src.count("_check_cost_budget(") >= 2, "_check_cost_budget 只有定义没有调用"

    def test_the_policy_file_exists_and_defines_cost_budgets(self):
        from pathlib import Path

        policy = Path(__file__).resolve().parent.parent / "config/llm_routing_policy.yaml"
        assert policy.exists(), "策略文件不存在 —— 删除前提不成立"
        text = policy.read_text(encoding="utf-8")
        assert "cost_budget" in text and "max_cost_per_1k_tokens" in text

    def test_removal_is_documented_in_place(self):
        """删掉的地方要留下"为什么删"—— 否则后人看到统一层之外没有成本策略会又加一个。"""
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "core/multi_llm_router.py").read_text(encoding="utf-8")
        assert "route_with_cost_policy() 已删除" in src
        assert "llm_routing_policy.yaml" in src, "没写清成本策略现在归谁"
