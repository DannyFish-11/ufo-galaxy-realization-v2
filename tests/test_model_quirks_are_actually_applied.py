"""型号级怪癖必须真的作用到请求上，而不是只写在表里。

## 背景

2026-09-06 把 ``gpt-6-astra`` 登进目录。它有两个跟同门师兄弟不一样的地方：

* **不接受 temperature / top_p / logprobs** —— 而 ``OpenAIAdapter`` 每次都发
  ``temperature``。不处理就等于登记了一个**每次调用必炸**的选项。
* **工具调用要走 Responses API** —— 本仓只有 chat/completions 适配器，所以在
  这条路上它的工具是不工作的。

第二条比第一条更危险：参数不对会当场报错（吵，但看得见）；工具悄悄消失不会报错，
上层以为这一轮有工具可用，模型却只能空口作答，而**答案看起来是正常的**。

## 这些门钉什么

判据放在 ``core.provider_registry.MODEL_QUIRKS``（唯一权威），适配器去查它。
所以要分别钉两件事：

1. 表里写对了；
2. **表真的被执行了** —— 换掉表的内容，请求体要跟着变。只断言"现在的请求体恰好
   没有 temperature"是不够的：那种断言在适配器根本没读表、而是别处碰巧删掉了
   这个字段时，照样绿。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


class TestTheQuirkTableSaysTheRightThing:
    def test_astra_is_registered_but_is_not_the_default(self):
        """登记它，但不让它成为默认。

        ①它仍在限量放量，用户的 key 未必有权限；②$50/M 输出是 Sol 的 1.67 倍。
        默认路径不该因为"目录里多了个最强的"就变贵、变得可能 403。
        """
        from core.provider_registry import PROVIDER_REGISTRY

        openai = next(p for p in PROVIDER_REGISTRY if p["name"] == "openai")
        assert "gpt-6-astra" in openai["models"], "gpt-6-astra 已经进 OpenAI 目录了，这里应该有它"
        assert (
            openai["default_model"] != "gpt-6-astra"
        ), "把 Astra 设成默认了 —— 它仍在限量放量，而且输出单价是 Sol 的 1.67 倍。"

    def test_the_quirks_carry_their_provenance(self):
        """每条怪癖都要写清出处。没有它，过两年没人知道这条还成不成立。"""
        from core.provider_registry import MODEL_QUIRKS

        for model, quirks in MODEL_QUIRKS.items():
            assert quirks.get("why"), f"{model} 的怪癖没有写出处"

    def test_snapshot_suffixes_do_not_slip_past(self):
        """上游常在正式串后挂日期快照，精确匹配会让它悄悄绕过怪癖处理。"""
        from core.provider_registry import quirks_for

        assert quirks_for("gpt-6-astra-2026-09-01").get(
            "omit_params"
        ), "带日期快照的串没匹配到怪癖 —— 它会照常发 temperature，然后每次必炸"
        assert quirks_for("gpt-5.6-sol") == {}, "普通型号不该被误伤"


class _Captured(Exception):
    """把请求体捞出来就够了，不用真发出去。"""

    def __init__(self, body: Dict[str, Any]) -> None:
        self.body = body


def _body_for(monkeypatch, model: str, tools: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """跑一次 OpenAIAdapter.chat，把它**实际组装出来的请求体**截下来。"""
    import asyncio

    from core.multi_llm_router import OpenAIAdapter, ProviderConfig

    cfg = ProviderConfig(
        name="openai", api_key="sk-test", base_url="https://example.invalid/v1", models=[model], default_model=model
    )
    adapter = OpenAIAdapter(cfg)

    async def _boom(url, *, headers, body):  # 签名照 _post_with_retry 的真实调用点
        raise _Captured(body)

    # 拦在**真正发出去的那一步**(_post_with_retry),不是我猜的名字。
    # 上一版我 monkeypatch 了两个并不存在的方法,于是每条都走进 pytest.skip ——
    # 而 skip 的测试什么都证明不了,比没有更糟:它看着是绿的。
    monkeypatch.setattr(adapter, "_post_with_retry", _boom)

    async def _run():
        try:
            await adapter.chat([{"role": "user", "content": "hi"}], model, tools=tools)
        except _Captured as c:
            return c.body
        raise AssertionError("没有截到请求体 —— 适配器的发送路径变了,这条门要跟着改")

    return asyncio.new_event_loop().run_until_complete(_run())


class TestTheAdapterActuallyObeysTheTable:
    """**换掉表的内容，请求体要跟着变。** 只看"现在恰好没有 temperature"是不够的。"""

    def test_a_quirked_model_loses_the_params_the_table_names(self, monkeypatch):
        from core import provider_registry

        monkeypatch.setattr(
            provider_registry,
            "MODEL_QUIRKS",
            {"sentinel-model": {"omit_params": ("temperature",), "why": "测试用"}},
        )
        body = _body_for(monkeypatch, "sentinel-model")
        assert "temperature" not in body, "表里说这个型号不能带 temperature，适配器还是发了 —— 说明它根本没读表"

    def test_a_plain_model_keeps_them(self, monkeypatch):
        """反面保险：不能靠"把所有型号的 temperature 都删掉"来通过上一条。"""
        from core import provider_registry

        monkeypatch.setattr(
            provider_registry, "MODEL_QUIRKS", {"sentinel-model": {"omit_params": ("temperature",), "why": "测试用"}}
        )
        body = _body_for(monkeypatch, "some-other-model")
        assert "temperature" in body, "没有怪癖的型号也被删掉了 temperature —— 那是一刀切，不是按表办事"

    def test_tools_are_dropped_loudly_never_silently(self, monkeypatch, caplog):
        """工具在这条路上不工作的型号：丢可以，**不许不吭声**。

        静默丢掉是最坏的：上层以为有工具，模型只能空口作答，而答案看起来正常。
        """
        import logging

        from core import provider_registry

        monkeypatch.setattr(
            provider_registry,
            "MODEL_QUIRKS",
            {"sentinel-model": {"tools_broken": True, "why": "测试用出处"}},
        )
        tools = [{"type": "function", "function": {"name": "do_thing"}}]
        with caplog.at_level(logging.WARNING):
            body = _body_for(monkeypatch, "sentinel-model", tools=tools)

        assert "tools" not in body, "表里说这个型号的工具不工作，请求里还带着 tools"
        assert any(
            "工具" in r.message for r in caplog.records
        ), "工具被悄悄丢掉了 —— 上层会以为这一轮有工具可用。降级必须留痕。"
