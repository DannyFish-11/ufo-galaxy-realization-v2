#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_local_routing_resolves_by_slot.py

钉住：**本地这一侧要能分清"哪个模型"；云端那一侧一个字不动。**

本地侧原来的样子
================
``MultiLLMRouter.select_brain_for_role`` 命中 ``prefer_local`` 之后是这样的：

.. code-block:: python

    for local in ("ollama", "hf_local"):
        if _avail(local):
            model = self.select_model_by_complexity(local, eff_task, eff_complexity)

而 ``select_model_by_complexity`` 对本地 provider **一律早退回 default_model**
（这是刻意的：本地通常只装了所选那一个 tag，按复杂度换挡会 404 到没装的 tag）。

两条加起来的效果是：**本地侧根本没有"哪个模型"这个概念** —— 取第一个可用的
provider，用它的默认模型。配了两个本地模型（感知位 + 推理位）之后，两个角色会
解析到同一个 default_model，``ROLE_BRAIN_HINTS`` 里的角色区分在本地这边落不了地。

云端侧一个字不动
================
``ROLE_BRAIN_HINTS`` 里 critic / reviewer / reasoner / coordinator / planner /
analyst 是 ``prefer_local: False`` 的**常驻归属** —— 审核、推理、协调本来就派给
云端，与本地装不装得下无关（该模块原话：「本地做，云端审；不让云端强模型抢走
executor」）。它不是"本地不够用才降级"的兜底档。这些角色压根走不到槽位那一步，
本文件也照此断言。
"""

from __future__ import annotations

import pytest

import core.model_catalog as mc
from core.model_catalog import SLOT_PERCEPTION, SLOT_REASONING
from core.multi_llm_router import ROLE_BRAIN_HINTS, MultiLLMRouter, ProviderConfig, TaskType

PERCEPTION = "openbmb/minicpm-o4.5"
REASONING = "qwen3.6:35b-a3b"


def _local_cfg(name: str, models, default) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        api_key="",
        base_url="http://127.0.0.1:1/v1",
        models=list(models),
        default_model=default,
        source_type="local",
    )


def _cloud_cfg(name: str, models) -> ProviderConfig:
    """一家云端 provider —— 只为把"有云端可选"这个条件摆出来，不会真的被调。"""
    return ProviderConfig(
        name=name,
        api_key="k",
        base_url="https://example.invalid/v1",
        models=list(models),
        default_model=models[0],
        source_type="api",
    )


class _Adapter:
    """占位适配器 —— 路由只检查它不是 None，不会真的调它。"""


@pytest.fixture
def router():
    """空壳路由器：绕开 __init__ 的真实 provider 发现，自己摆桌面。"""
    r = MultiLLMRouter.__new__(MultiLLMRouter)
    r.providers = {}
    r.adapters = {}
    return r


@pytest.fixture
def two_local_models(router):
    """C 档的真实形状。

    感知位 MiniCPM-o 是 Ollama 能直接 pull 的 tag（``source="local"``），所以它在
    ``ollama`` 上；推理位是本地 GGUF（``source="llama_cpp"``，专家卸载只在这条路
    上可用），由核显/独显那台 OpenAI 兼容服务托管。

    这个摆法同时是**判别点**：旧路径取 ``("ollama","hf_local")`` 里第一个可用的、
    用它的 default_model —— 于是它答的是**感知位**。新旧两条路在这张桌面上给出
    不同答案，测试才有区分力。若把两个模型对调，两条路会碰巧同答，测试就退化成
    「怎么写都通过」。
    """
    router.providers["ollama"] = _local_cfg("ollama", [PERCEPTION], PERCEPTION)
    router.adapters["ollama"] = _Adapter()
    router.providers["local_openai"] = _local_cfg("local_openai", [REASONING], REASONING)
    router.adapters["local_openai"] = _Adapter()
    return router


class TestTwoModelsAreToldApart:
    def test_the_two_slots_resolve_to_different_models(self, two_local_models, monkeypatch):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        r = two_local_models
        perception = r._local_by_slot(SLOT_PERCEPTION, role="probe", task=TaskType.GENERAL)
        reasoning = r._local_by_slot(SLOT_REASONING, role="probe", task=TaskType.GENERAL)
        assert perception is not None and reasoning is not None
        assert perception.model == PERCEPTION
        assert reasoning.model == REASONING
        assert perception.provider != reasoning.provider, "两个槽位落到了同一个 provider —— 没分开"

    def test_dispatch_roles_land_on_the_reasoning_slot(self, two_local_models, monkeypatch):
        """派活角色干的是文本/工具的活 → 推理位，不该被派给常驻感知位。

        ``coder`` / ``writer`` **不在这个名单里了**：它们已改成产出角色（按能力选，
        不按位置选），不再"硬优先本地"。它们落到本地时仍然该落在推理位上 ——
        那由下面 :meth:`test_output_roles_also_land_on_the_reasoning_slot` 单独钉。
        """
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        for role in ("executor", "worker", "researcher"):
            assert ROLE_BRAIN_HINTS[role]["prefer_local"] is True, "前提变了：这条测试假设它们硬优先本地"
            decision = two_local_models.select_brain_for_role(role)
            assert decision.model == REASONING, f"角色 {role} 被派给了 {decision.model}"

    def test_output_roles_also_land_on_the_reasoning_slot(self, two_local_models, monkeypatch):
        """产出角色落到本地时，同样该落在推理位上。

        它们走的是另一条路（质量优先，而非硬优先本地），但"两个本地槽位分得开"
        这件事对它们一样成立 —— 一个只有本地 provider 的桌面上，写代码不该被派给
        那个负责看/听的感知位。

        这条与上面那条覆盖的是**不同的代码路径**，不是重复：上面走
        ``_local_by_slot`` 的硬优先分支，这条走质量优先回落。
        """
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        for role in ("coder", "writer"):
            assert ROLE_BRAIN_HINTS[role]["prefer_local"] is False, "前提变了：它们该是产出角色"
            decision = two_local_models.select_brain_for_role(role)
            assert decision.model == REASONING, f"角色 {role} 被派给了 {decision.model}"

    def test_old_path_would_have_sent_agent_work_to_the_perception_slot(self, two_local_models, monkeypatch):
        """反向确认修复确实改变了行为，而不是碰巧本来就对。

        旧路径取 ``("ollama","hf_local")`` 里第一个可用的、用它的 default_model ——
        在这张桌面上那是**感知位**。也就是说 executor 这些干文本活的角色，会被派
        给那个负责看/听的常驻模型，而真正该干这活的推理位一次都轮不到。
        """
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        r = two_local_models

        old_style = None
        for local in ("ollama", "hf_local"):
            if local in r.providers:
                old_style = r.providers[local].default_model
                break
        assert old_style == PERCEPTION, "构造的桌面没能复现旧路径的错法，这条测试就失去意义了"

        assert r.select_brain_for_role("executor").model == REASONING
        assert r.select_brain_for_role("executor").model != old_style


class TestOneModelBehavesExactlyAsBefore:
    def test_single_tier_resolves_both_slots_to_the_main_brain(self, router, monkeypatch):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "A")
        monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b")
        router.providers["ollama"] = _local_cfg("ollama", ["gemma4:12b"], "gemma4:12b")
        router.adapters["ollama"] = _Adapter()

        perception = router._local_by_slot(SLOT_PERCEPTION, role="probe", task=TaskType.GENERAL)
        reasoning = router._local_by_slot(SLOT_REASONING, role="probe", task=TaskType.GENERAL)
        assert perception.model == reasoning.model == "gemma4:12b"
        assert perception.provider == reasoning.provider == "ollama"

    def test_single_tier_follows_the_chosen_brain_not_the_first_candidate(self, monkeypatch):
        """A 档三个候选里选了 12b，按角色问就必须答 12b，不能答候选表里的第一个。"""
        monkeypatch.setenv("GALAXY_MODEL_TIER", "A")
        monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b")
        assert mc.model_for_role(SLOT_REASONING) == "gemma4:12b"
        monkeypatch.setenv("OLLAMA_MODEL", "gemma4:e4b")
        assert mc.model_for_role(SLOT_REASONING) == "gemma4:e4b"


class TestCloudSideIsUntouched:
    def test_heavy_roles_are_still_cloud_bound(self):
        """这几个角色是常驻归属云端的，不是"本地装不下才上云"。"""
        for role in ("critic", "reviewer", "reasoner", "coordinator", "planner", "analyst"):
            assert ROLE_BRAIN_HINTS[role]["prefer_local"] is False, f"{role} 的云端归属被改动了"

    def test_heavy_role_never_reaches_the_slot_resolver_when_cloud_exists(self, two_local_models, monkeypatch):
        """有云端时，把关角色不该被引到本地槽位上去。

        原来这条不带云端 provider 就断言"永远不会调到槽位解析"。那个前提已经变了：
        把关角色现在是 ``prefer_remote``（常驻云端），而一个云端都没配时**会**回落
        本地 —— 纯本地方案必须能跑。回落之后落在推理位而不是感知位，是对的，
        不是"云端那一侧被动了"。所以这条改成在**它真正描述的那个条件下**断言。
        """
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        two_local_models.providers["anthropic"] = _cloud_cfg("anthropic", ["claude-sonnet-5"])
        two_local_models.adapters["anthropic"] = _Adapter()
        called = []
        orig = two_local_models._local_by_slot
        two_local_models._local_by_slot = lambda *a, **k: called.append(a) or orig(*a, **k)
        decision = two_local_models.select_brain_for_role("critic")
        assert called == [], "重角色走进了本地槽位解析 —— 云端把关那一侧被动了"
        assert decision.provider == "anthropic", "把关角色没落到云端"

    def test_heavy_role_falls_back_to_the_reasoning_slot_when_local_only(self, two_local_models, monkeypatch):
        """纯本地方案：把关角色回落本地时，同样落在推理位而不是感知位。

        回落本身是对的（一个云端都没配也必须能跑）；落错槽位就不对了 ——
        那是这个文件从头到尾在防的那个缺陷。
        """
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        assert two_local_models.select_brain_for_role("critic").model == REASONING


class TestFallbacksDoNotSilentlyMisroute:
    def test_slot_model_with_no_local_host_falls_back_instead_of_swapping(self, router, monkeypatch):
        """槽位指定的模型没人托管时交回原路径，**不能**默默改派给另一个本地模型。

        默默改派正是"配了两个模型却全落到一个上"的形状 —— 功能看着在，
        实际另一位从没被用过。
        """
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        # 只有感知位在线，推理位那台没起。
        router.providers["local_openai"] = _local_cfg("local_openai", [PERCEPTION], PERCEPTION)
        router.adapters["local_openai"] = _Adapter()
        assert router._local_by_slot(SLOT_REASONING, role="probe", task=TaskType.GENERAL) is None

    def test_catalog_failure_falls_back_quietly(self, two_local_models, monkeypatch):
        monkeypatch.setattr(mc, "model_for_role", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert two_local_models._local_by_slot(SLOT_REASONING, role="probe", task=TaskType.GENERAL) is None

    def test_root_prefix_matching_still_works(self, router, monkeypatch):
        """Ollama 的 tag 带后缀(gemma4:12b-instruct)时也要认得出是同一个模型。"""
        monkeypatch.setenv("GALAXY_MODEL_TIER", "A")
        monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b")
        router.providers["ollama"] = _local_cfg("ollama", ["gemma4:12b-instruct"], "gemma4:12b-instruct")
        router.adapters["ollama"] = _Adapter()
        assert router._provider_serving("gemma4:12b") == ("ollama", "gemma4:12b-instruct")

    def test_unhosted_tag_reports_no_provider(self, two_local_models):
        assert two_local_models._provider_serving("nobody/hosts-this") is None

    def test_a_differently_named_service_needs_an_explicit_declaration(self, router, monkeypatch):
        """OpenVINO / llama.cpp server 按自己那套命名报模型 id,与目录 tag 对不上。

        这里**不猜**:只有起服务的人知道自己装的是什么。没声明就报"没人托管"
        (交回原路径),声明了才认领 —— 且调用时报服务自己那个 id,不是目录 tag,
        否则一律 404。
        """
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        monkeypatch.delenv("GALAXY_LOCAL_OPENAI_SERVES", raising=False)
        router.providers["local_openai"] = _local_cfg(
            "local_openai", ["MiniCPM-o-4_5-int4-ov"], "MiniCPM-o-4_5-int4-ov"
        )
        router.adapters["local_openai"] = _Adapter()

        assert router._provider_serving(PERCEPTION) is None, "名字对不上却认领了 —— 那是在猜"

        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_SERVES", PERCEPTION)
        assert router._provider_serving(PERCEPTION) == ("local_openai", "MiniCPM-o-4_5-int4-ov")

    def test_declaration_only_claims_the_tag_it_names(self, router, monkeypatch):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_SERVES", PERCEPTION)
        router.providers["local_openai"] = _local_cfg(
            "local_openai", ["MiniCPM-o-4_5-int4-ov"], "MiniCPM-o-4_5-int4-ov"
        )
        router.adapters["local_openai"] = _Adapter()
        assert router._provider_serving(REASONING) is None, "声明的是感知位,却把推理位也认领了"


class TestAnUnstaffedSlotIsLoud:
    """真实路径实测发现的：交回原路径这件事本身必须响亮。

    实跑 C 档、只起了感知位那台服务时看到的：

    .. code-block:: text

        executor -> local_openai:MiniCPM-o-4_5-int4-ov
                    角色[executor] 轻角色(无本地→fit) → fit-based: ...

    ``_local_by_slot`` 尽职地返回了 None（没有静默改派），可下游按可用性
    fit-based 又把活派给了**感知位** —— 最终结果和静默改派一模一样，而唯一的
    痕迹是一行 debug。用户看到的是"两个模型都配好了、系统也在跑"，实际推理位
    从没上过岗。所以这里必须 WARNING，且要说清怎么查。
    """

    def test_unhosted_slot_warns_with_actionable_text(self, router, monkeypatch, caplog):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        router.providers["ollama"] = _local_cfg("ollama", [PERCEPTION], PERCEPTION)
        router.adapters["ollama"] = _Adapter()  # 只有感知位在线

        with caplog.at_level("WARNING"):
            assert router._local_by_slot(SLOT_REASONING, role="executor", task=TaskType.GENERAL) is None

        msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert msgs, "推理位没上岗却一声不吭 —— 只有 debug 等于没说"
        text = "\n".join(msgs)
        assert REASONING in text, "没说清是哪一位没上岗"
        assert "GALAXY_LOCAL_OPENAI_SERVES" in text, "没给出可操作的排查方向"

    def test_it_warns_once_per_slot_not_every_route(self, router, monkeypatch, caplog):
        """这条路径每次路由都会走到 —— 喊满屏等于没喊。"""
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        router.providers["ollama"] = _local_cfg("ollama", [PERCEPTION], PERCEPTION)
        router.adapters["ollama"] = _Adapter()

        with caplog.at_level("WARNING"):
            for _ in range(5):
                router._local_by_slot(SLOT_REASONING, role="executor", task=TaskType.GENERAL)

        warns = [r for r in caplog.records if r.levelname == "WARNING" and REASONING in r.getMessage()]
        assert len(warns) == 1, f"同一个槽位喊了 {len(warns)} 次"

    def test_a_staffed_slot_says_nothing(self, two_local_models, monkeypatch, caplog):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        with caplog.at_level("WARNING"):
            assert two_local_models._local_by_slot(SLOT_REASONING, role="executor", task=TaskType.GENERAL) is not None
        assert [r for r in caplog.records if r.levelname == "WARNING"] == []
