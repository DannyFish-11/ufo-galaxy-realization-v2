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


def test_nothing_configured_is_a_state_said_once_not_an_error_per_call(monkeypatch, caplog):
    """真跑:一条对话消息路由七八次,原先每次都记 ERROR「没有可用的 LLM 提供商」+「所有提供商调用失败: []」,
    两分钟几十条,还上控制台。「一个都没配」是一种状态:每 10 分钟提醒一次(WARNING),其余 debug。"""
    import logging

    import core.llm_unavailable_reply as m

    monkeypatch.setattr(m, "_last_noted", [0.0])
    with caplog.at_level(logging.DEBUG, logger=m.logger.name):
        for _ in range(8):
            assert m.unavailable_reply([]) == m.NOTHING_CONFIGURED_REPLY
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(loud) == 1 and loud[0].levelno == logging.WARNING, [r.getMessage() for r in loud]


def test_providers_that_were_tried_and_failed_are_still_an_error(caplog):
    import logging

    import core.llm_unavailable_reply as m

    with caplog.at_level(logging.ERROR, logger=m.logger.name):
        m.unavailable_reply(["deepseek"])
    assert any(r.levelno == logging.ERROR and "deepseek" in r.getMessage() for r in caplog.records)


def test_the_router_notes_the_state_instead_of_logging_an_error():
    import inspect

    import core.multi_llm_router as r

    src = inspect.getsource(r)
    assert 'logger.error("没有可用的 LLM 提供商")' not in src
    assert "note_nothing_configured()" in src
