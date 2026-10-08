"""偏好表没列、但已配好可用的厂商，要进失败转移链 —— 而不是只在「别的全不可用」时被任选一个碰到。

被修的问题
----------
面板上「我的模型服务」写着「通了才让它参与选路」。实际上用户端点（``source_type="user"``）与 OneAPI
聚合网关不可能出现在 ``TASK_ROUTING_PREFERENCES`` 里，于是智能路由里它们是「不存在」的：只有当所有列出来的
厂商都不可用，兜底那条「任选一个可用」才会碰到它们，而且不排序、没有备选。

同一类漏配之前出现过一次（agnes / moonshot / openrouter 注册了却没进任何偏好表、从未被自动选中）。

规则（见 ``core/routing_tail.py``）
---------------------------------
1. 列出来的照旧，本修复不碰它们的顺序；
2. 没列、已注册、可用的接在它们**后面**（失败转移的后几档）；
3. 有意不自动参与选路的（智谱编码套餐）不进这一档，只在「没有任何别的可用」时垫底。
"""

from __future__ import annotations

import pytest

from core.llm_types import ProviderConfig, ProviderStatus, TaskType
from core.multi_llm_router import TASK_ROUTING_PREFERENCES, MultiLLMRouter


def _cfg(name: str, *, source_type: str = "api", model: str = "m-1", down: bool = False) -> ProviderConfig:
    cfg = ProviderConfig(
        name=name,
        api_key="k",
        base_url="https://x.example/v1",
        models=[model],
        default_model=model,
        source_type=source_type,
    )
    if down:
        cfg.status = ProviderStatus.DOWN
        cfg.down_since = 9e12  # 远在未来：冷却期没过，保持不可用
    return cfg


@pytest.fixture()
def router():
    r = MultiLLMRouter()
    r.providers.clear()
    r.adapters.clear()
    return r


def _put(router, *cfgs):
    for c in cfgs:
        router.providers[c.name] = c


class TestUnlistedJoinTheFailoverChain:
    def test_user_endpoint_follows_the_listed_vendors(self, router):
        _put(router, _cfg("deepseek"), _cfg("my-gw", source_type="user"))
        d = router.route(TaskType.GENERAL)
        assert d.provider == "deepseek"
        assert [a.split(":")[0] for a in d.alternatives] == ["my-gw"]

    def test_user_endpoint_is_used_when_every_listed_vendor_is_down(self, router):
        _put(router, _cfg("deepseek", down=True), _cfg("my-gw", source_type="user", model="gw-model"))
        d = router.route(TaskType.GENERAL)
        assert d.provider == "my-gw"
        assert d.model == "gw-model"

    def test_oneapi_gateway_is_a_candidate_too(self, router):
        _put(router, _cfg("anthropic"), _cfg("oneapi", source_type="oneapi"))
        d = router.route(TaskType.REASONING)
        assert d.provider == "anthropic"
        assert "oneapi" in [a.split(":")[0] for a in d.alternatives]

    def test_a_listed_vendor_missing_from_this_task_still_joins_as_backup(self, router):
        """groq 不在 REASONING 的偏好表里；有 deepseek 在时它不抢位，但 deepseek 失败后它是备选。"""
        assert "groq" not in TASK_ROUTING_PREFERENCES[TaskType.REASONING]
        _put(router, _cfg("deepseek"), _cfg("groq"))
        d = router.route(TaskType.REASONING)
        assert d.provider == "deepseek"
        assert "groq" in [a.split(":")[0] for a in d.alternatives]

    def test_only_an_unlisted_vendor_configured_still_answers_and_lists_the_rest(self, router):
        _put(router, _cfg("groq"), _cfg("my-gw", source_type="user"))
        d = router.route(TaskType.REASONING)
        assert d.provider in {"groq", "my-gw"}
        rest = {"groq", "my-gw"} - {d.provider}
        assert {a.split(":")[0] for a in d.alternatives} == rest

    def test_listed_order_is_untouched(self, router):
        """本修复只加后档，不动已列厂商的排序。"""
        _put(router, _cfg("anthropic"), _cfg("openai"), _cfg("my-gw", source_type="user"))
        d = router.route(TaskType.REASONING)
        chain = [d.provider] + [a.split(":")[0] for a in d.alternatives]
        assert chain.index("my-gw") == len(chain) - 1


class TestOptInStaysOptIn:
    def test_coding_plan_is_not_a_backup_for_ordinary_tasks(self, router):
        _put(router, _cfg("deepseek"), _cfg("zhipu_coding"))
        d = router.route(TaskType.GENERAL)
        assert d.provider == "deepseek"
        assert "zhipu_coding" not in [a.split(":")[0] for a in d.alternatives]

    def test_coding_plan_still_answers_when_it_is_the_only_one(self, router):
        """保持原先「任选一个可用」的兜底语义 —— 只是不再提前混进正常备选。"""
        _put(router, _cfg("zhipu_coding"))
        d = router.route(TaskType.CODING)
        assert d.provider == "zhipu_coding"

    def test_nothing_available_is_still_the_explicit_none(self, router):
        d = router.route(TaskType.GENERAL)
        assert d.provider == "none"
