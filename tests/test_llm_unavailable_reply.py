"""tests/test_llm_unavailable_reply.py — 「一个都没试到」和「试了都失败」说的不是同一句话。

复测时，干净环境里第一句对话收到的是「所有 AI 服务暂时不可用（已尝试: ），请检查 API Key
配置后重试」。括号里是空的：根本没有可试的提供商，用户却看不出缺的是什么。
"""

from __future__ import annotations

import asyncio

from core.llm_unavailable_reply import NOTHING_CONFIGURED_REPLY, unavailable_reply


def test_nothing_to_try_says_what_is_missing():
    reply = unavailable_reply([])
    assert reply == NOTHING_CONFIGURED_REPLY
    assert "已尝试" not in reply
    assert "API Key" in reply and "Ollama" in reply


def test_tried_and_failed_lists_what_was_tried():
    reply = unavailable_reply(["deepseek", "openai"])
    assert "已尝试: deepseek, openai" in reply


def test_the_router_says_it_when_nothing_is_configured():
    from core.multi_llm_router import MultiLLMRouter

    router = MultiLLMRouter()
    router.providers.clear()
    router.adapters.clear()

    result = asyncio.run(router.chat([{"role": "user", "content": "hello"}], auto_failover=True))
    assert result.provider == "none"
    assert result.content == NOTHING_CONFIGURED_REPLY
