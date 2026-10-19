"""一个模型都没配时,日志说的是「没有模型」,不是「JSON 解析失败」「schema 校验失败」。

``MultiLLMRouter.chat`` 调不通时不抛异常,回一条给人看的降级说明(``provider="none"``)。原先 ``chat_json`` 拿这句话
去 ``json.loads``,记一条「chat_json 解析失败」;Agent 工厂再记「LLM 生成的 Agent 配置未通过 schema 校验」,
任务分解记「LLM 返回非法 JSON」—— 真跑里每次生成 Agent 三条 WARNING,原因全说错了。
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

from core.llm_types import LLMResponse
from core.llm_unavailable_reply import NOTHING_CONFIGURED_REPLY

NONE = LLMResponse(content=NOTHING_CONFIGURED_REPLY, provider="none", model="none")


def _chat_json_when_nothing_answers():
    from core.multi_llm_router import MultiLLMRouter

    router = MultiLLMRouter()

    async def run():
        with patch.object(router, "chat", new_callable=AsyncMock, return_value=NONE):
            return await router.chat_json([{"role": "user", "content": "x"}])

    return asyncio.run(run())


def test_chat_json_says_unavailable_without_parsing_the_apology(caplog):
    with caplog.at_level(logging.WARNING):
        result = _chat_json_when_nothing_answers()
    assert result == {"error": NOTHING_CONFIGURED_REPLY, "unavailable": True}
    assert not [r for r in caplog.records if "解析失败" in r.getMessage()]


def test_agent_factory_uses_a_template_and_does_not_blame_the_schema(caplog):
    from core.agent_factory import AgentFactory

    router = AsyncMock()
    router.chat_json.return_value = {"error": NOTHING_CONFIGURED_REPLY, "unavailable": True}
    factory = AgentFactory(llm_router=router)
    with caplog.at_level(logging.WARNING):
        agent = asyncio.run(factory.create_from_llm("整理一下桌面上的文件"))
    assert agent is not None
    assert not [r for r in caplog.records if "schema" in r.getMessage().lower()]
