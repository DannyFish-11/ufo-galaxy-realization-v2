"""角色派活：产出按能力选，把关换脑子看，派活就近。

改了什么
========
原来只有两类：轻角色**硬**优先本地、重角色"质量优先"。两处都有问题：

1. ``coder`` / ``writer`` 被归进轻角色 —— 产出质量直接是交付物本身，
   "就近"不是它该优化的东西。
2. 本地的能力档写死成 1（``PROVIDER_QUALITY_TIER`` 里三行 ``"ollama": 1``，
   注释是"本地轻量(无 GPU 笔电主脑)"）。C 档推理位是 35B-A3B、D 档是 9B 稠密，
   一律判 1 档的后果是**走质量优先必然输给任何云端** —— 于是"优先强模型"这句话
   在本地放着 35B 时也只会把活派到云端。

两处一起改，"不管本地云端都优先强模型"才成立。

改的过程中撞出来的第三件事（C 组）
==================================
本地按实际装的东西算成 3 档之后，``critic`` / ``reviewer`` 立刻**全落回本地** ——
因为质量打平时本地零成本 + 开源加分会赢。那等于同一个脑子既做又审，
把仓库明写的「本地做、云端审」当场作废。所以把关角色补了显式的 ``prefer_remote``。

覆盖矩阵
========
A. 本地能力档由推理位上真正选中的型号决定
B. 产出角色按能力选：本地强则留、本地弱则出
C. 把关角色常驻云端 —— 即便本地也是 3 档
D. 纯本地方案照跑：没有云端时一切回落本地
E. 派活角色不受影响：始终本地硬优先
"""

from __future__ import annotations

import pytest

import core.model_catalog as mc
from core.multi_llm_router import ROLE_BRAIN_HINTS, MultiLLMRouter, ProviderConfig, is_local_provider

LOCAL_ROLES = ("executor", "worker", "researcher")
OUTPUT_ROLES = ("coder", "writer")
GATEKEEPER_ROLES = ("critic", "reviewer", "reasoner", "coordinator", "planner", "analyst")


@pytest.fixture(autouse=True)
def _isolated_tier_state(tmp_path, monkeypatch):
    """把档位状态隔到临时目录 —— **不碰工作区里那份真文件**。

    ``save_tier()`` 会写 ``runtime/model_state.json``（真文件，全会话共享）。
    只在 teardown 里"存旧值再写回"是不够的：中途崩了、或断言失败提前退出，
    残留就留在盘上，后面所有读档位的用例都会跟着错，而症状指不到这里。
    本轮开发时正是这么栽过一次 —— 一个临时脚本把档位落成 C，
    ``test_clone_to_running_dual_brain`` 与 ``test_reasoning_slot_stays_resident``
    一起变红，看起来像路由改动的回归，其实一行代码都没关系。
    """
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(mc, "_STATE_FILE", tmp_path / "model_state.json", raising=False)
    yield


def _router(*, with_cloud: bool) -> MultiLLMRouter:
    """只装 provider 表的最小路由器 —— 不触网、不加载任何模型。"""
    r = MultiLLMRouter.__new__(MultiLLMRouter)
    r.providers, r.adapters = {}, {}

    def add(name: str, source_type: str, models: list) -> None:
        cfg = ProviderConfig(
            name=name,
            api_key="k" if source_type == "api" else "",
            base_url="http://x/v1",
            models=models,
            default_model=models[0],
            source_type=source_type,
        )
        cfg.status = "healthy"
        r.providers[name] = cfg
        r.adapters[name] = object()

    add("ollama", "local", ["local-tag"])
    if with_cloud:
        add("anthropic", "api", ["claude-sonnet-5"])
        add("openai", "api", ["gpt-5.6"])
    return r


def _side(r: MultiLLMRouter, role: str) -> str:
    d = r.select_brain_for_role(role, complexity_score=0.5)
    return "local" if is_local_provider(d.provider, r.providers.get(d.provider)) else "cloud"


# ---------------------------------------------------------------------------
# A. 本地能力档按实际装的东西算
# ---------------------------------------------------------------------------


class TestGroupALocalTierIsDerived:
    @pytest.mark.parametrize("tier,expected", [("A", 1), ("B", 2), ("D", 2), ("C", 3)])
    def test_a01_tier_follows_the_reasoning_slot(self, tier: str, expected: int) -> None:
        """阈值按目录里真实存在的型号定：35B(18 GB)→3，9B/12B→2，e2b/e4b→1。"""
        assert mc.local_reasoning_quality_tier(tier) == expected

    def test_a02_same_provider_different_answer(self) -> None:
        """同一个 provider 名字，装什么就判什么 —— 这正是"不写死"的意思。"""
        from core.multi_llm_router import _provider_quality_tier

        mc.save_tier("A")
        weak = _provider_quality_tier("ollama")
        mc.save_tier("C")
        strong = _provider_quality_tier("ollama")
        assert (weak, strong) == (1, 3)

    def test_a03_explicit_env_override_still_wins(self, monkeypatch) -> None:
        """人比推断更权威。"""
        from core.multi_llm_router import _provider_quality_tier

        mc.save_tier("C")
        monkeypatch.setenv("GALAXY_QUALITY_TIER_OLLAMA", "1")
        assert _provider_quality_tier("ollama") == 1

    def test_a04_cloud_tiers_untouched(self) -> None:
        from core.multi_llm_router import _provider_quality_tier

        assert _provider_quality_tier("anthropic") == 3
        assert _provider_quality_tier("groq") == 2

    def test_a05_unknown_tier_is_conservative(self) -> None:
        """不知道就别高估 —— 高估会把活派给一个可能带不动的本地模型。"""
        assert mc.local_reasoning_quality_tier("ZZZ") == 1


# ---------------------------------------------------------------------------
# B. 产出角色按能力选
# ---------------------------------------------------------------------------


class TestGroupBOutputRolesFollowCapability:
    @pytest.mark.parametrize("role", OUTPUT_ROLES)
    def test_b01_weak_local_sends_it_out(self, role: str) -> None:
        mc.save_tier("A")
        assert _side(_router(with_cloud=True), role) == "cloud"

    @pytest.mark.parametrize("role", OUTPUT_ROLES)
    def test_b02_strong_local_keeps_it(self, role: str) -> None:
        """**这一条是整改的目的。** 本地放着 35B 还把写代码派到云端，是在浪费它。"""
        mc.save_tier("C")
        assert _side(_router(with_cloud=True), role) == "local"

    @pytest.mark.parametrize("role", OUTPUT_ROLES)
    def test_b03_output_roles_are_no_longer_hard_local(self, role: str) -> None:
        """防回归：它们要是又被归回"硬优先本地"，B01 会静默变成本地也算过。"""
        assert ROLE_BRAIN_HINTS[role]["prefer_local"] is False

    @pytest.mark.parametrize("role", OUTPUT_ROLES)
    def test_b04_output_roles_are_not_pinned_remote_either(self, role: str) -> None:
        """按能力选 = 两边都不钉死。钉在云端就成了另一种写死。"""
        assert ROLE_BRAIN_HINTS[role].get("prefer_remote", False) is False


# ---------------------------------------------------------------------------
# C. 把关角色换一个脑子看
# ---------------------------------------------------------------------------


class TestGroupCGatekeepersStayRemote:
    @pytest.mark.parametrize("role", GATEKEEPER_ROLES)
    def test_c01_gatekeepers_go_cloud_even_when_local_is_tier_3(self, role: str) -> None:
        """**这一条钉的是本次改动撞出来的回归。**

        本地按实际装的东西算成 3 档之后，质量打平时本地零成本 + 开源加分会赢，
        于是 critic/reviewer 全落回本地 —— 同一个脑子既做又审，
        「本地做、云端审」当场作废。
        """
        mc.save_tier("C")
        assert _side(_router(with_cloud=True), role) == "cloud"

    @pytest.mark.parametrize("role", GATEKEEPER_ROLES)
    def test_c02_declared_explicitly_not_inferred(self, role: str) -> None:
        """它必须是**写下来的**意图。只写 prefer_local=False 等于"走质量优先"，
        而质量优先在本地够强时会把审核也交给本地 —— 那正是 C01 抓到的洞。"""
        assert ROLE_BRAIN_HINTS[role].get("prefer_remote", False) is True

    def test_c03_the_doer_and_the_reviewer_are_different_sides(self) -> None:
        """分工本身：同一份配置下，做的和审的不在同一侧。"""
        mc.save_tier("C")
        r = _router(with_cloud=True)
        assert _side(r, "coder") == "local"
        assert _side(r, "reviewer") == "cloud"


# ---------------------------------------------------------------------------
# D. 纯本地方案照跑
# ---------------------------------------------------------------------------


class TestGroupDLocalOnlyStillWorks:
    @pytest.mark.parametrize("role", OUTPUT_ROLES + GATEKEEPER_ROLES + LOCAL_ROLES)
    def test_d01_everything_falls_back_to_local(self, role: str) -> None:
        """``prefer_remote`` 是偏好不是硬性要求 —— 一个云端都没配时必须照跑。"""
        mc.save_tier("C")
        assert _side(_router(with_cloud=False), role) == "local"

    def test_d02_narrowing_to_empty_does_not_silently_reopen(self) -> None:
        """``only_providers`` 收窄到空时交回 none，由调用方决定怎么回落。

        在那里自作主张放开，等于把"只在云端选"变成一句没有效力的话。
        """
        from core.multi_llm_router import TaskType

        r = _router(with_cloud=False)
        d = r.select_brain_for_task(TaskType.REASONING, only_providers=["anthropic"])
        assert d.provider == "none"


# ---------------------------------------------------------------------------
# E. 派活角色不受影响
# ---------------------------------------------------------------------------


class TestGroupEDispatchRolesUnchanged:
    @pytest.mark.parametrize("role", LOCAL_ROLES)
    @pytest.mark.parametrize("tier", ["A", "C"])
    def test_e01_always_local(self, role: str, tier: str) -> None:
        """设计意图原话：「本地做，云端审；不让云端强模型抢走 executor」。"""
        mc.save_tier(tier)
        assert _side(_router(with_cloud=True), role) == "local"

    @pytest.mark.parametrize("role", LOCAL_ROLES)
    def test_e02_still_declared_hard_local(self, role: str) -> None:
        assert ROLE_BRAIN_HINTS[role]["prefer_local"] is True
