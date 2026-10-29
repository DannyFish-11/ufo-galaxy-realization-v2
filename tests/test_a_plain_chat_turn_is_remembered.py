"""纯聊天的一轮也进会话(第 8 轮真跑发现)。

内核按意图分流:``chat_only`` 在分流处直接返回,而「记录会话」那一步在执行路的末尾 —— 纯聊天从来不记。
真跑:``你好呀`` 之后 ``GET /api/v1/sessions/<id>/history`` 是空的;面板重开看不到这段对话,
下一轮交给模型的上下文里也没有上一句。执行路(``task_execute``)的会话一直是有的。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _fresh_kernel():
    from core.agent import kernel as kernel_mod

    kernel_mod._kernel = None
    kernel_mod.AgentKernel._instance = None
    return kernel_mod.get_kernel()


@pytest.mark.asyncio
@pytest.mark.parametrize("success, recorded", [(True, True), (False, False)])
async def test_a_chat_turn_goes_into_the_session(success, recorded):
    from core.agent.intent_router import IntentMode
    from core.agent.kernel import KernelResponse

    kernel = _fresh_kernel()
    seen = []

    async def fake_handle_chat(message, session_id, context, user_policy, task_hint="", **kwargs):
        reply = "你好,我在。" if success else "LLM 服务未配置,请在 Dashboard 中设置 API Key。"
        return KernelResponse(success=success, mode=IntentMode.CHAT_ONLY, reply=reply)

    async def fake_record(session_id, user_msg, assistant_msg, **kwargs):
        seen.append((session_id, user_msg, assistant_msg))

    with (
        patch.object(kernel, "_handle_chat", side_effect=fake_handle_chat),
        patch.object(kernel, "_record_session", side_effect=fake_record),
    ):
        result = await kernel.handle_message("你好呀", session_id="chat-remembered")

    assert result.mode == IntentMode.CHAT_ONLY
    if recorded:
        assert seen == [("chat-remembered", "你好呀", "你好,我在。")]
    else:
        assert seen == [], "没成的那一轮(服务未配置)不是它说的话,不记进会话"
