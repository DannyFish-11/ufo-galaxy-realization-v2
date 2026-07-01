"""tests/test_voice_conversation_bridge.py
============================================
实时语音对话一体化闭环的行为证明(确定性 LLM stub,无需真麦克风/模型)。

被测链路(core/voice_conversation_bridge.process_voice_utterance):

    麦克风 ASR 文本
      → emit_conversation("user", …, source="voice")     ← 面板实时显示"AI 听到的"
      → DesktopPresenceRuntime.handle_request(source="voice")  ← 同一个 AI 大脑
      → emit_conversation("ai", …, source="voice", speaking=True)  ← 面板实时显示"AI 说的"
      → speak_response()（TTS，best-effort）

证明点:
  1. 面板(GalaxyPresenceBridge 已注册 WS 客户端)确实收到 user + ai 两条
     conversation 帧,source 均为 "voice",ai 帧 speaking=True。
  2. source="voice" 是运行时一等 ingress(不再落 "unknown source" 兜底)。
"""

from __future__ import annotations

import asyncio
import os

import pytest


def _inject_stub(stub) -> None:
    """把确定性 LLM stub 注入 OpenClawd + AgentKernel(复用集成测试注入方式)。"""
    from core.openclawd import get_openclawd
    from core.agent.kernel import AgentKernel
    from core.agent.intent_router import IntentRouter
    from core.agent.execution_planner import ExecutionPlanner

    clawd = get_openclawd()
    clawd._router = stub
    if clawd._kernel is None:
        clawd._kernel = AgentKernel()
    kernel = clawd._kernel
    kernel._llm_router = stub
    kernel._intent_router = IntentRouter(stub)
    kernel._planner = ExecutionPlanner(stub)


class _FakeWS:
    """最小 WS 客户端:记录收到的 JSON 帧。"""

    def __init__(self) -> None:
        self.received: list = []

    async def send_json(self, message) -> None:  # noqa: ANN001
        self.received.append(message)


@pytest.mark.asyncio
async def test_voice_utterance_emits_user_and_ai_to_panel(monkeypatch):
    """一次语音输入 → 面板收到 user + ai 两条 voice conversation 帧。"""
    monkeypatch.setenv("GALAXY_VOICE_LOOP", "1")

    from tests.integration.stubs.llm_contract_stub import LLMContractStub
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge
    from core.voice_conversation_bridge import process_voice_utterance, voice_loop_enabled

    assert voice_loop_enabled() is True

    bridge = GalaxyPresenceBridge.get_instance()
    bridge._loop = asyncio.get_running_loop()
    ws = _FakeWS()
    await bridge.register_client(ws)

    stub = LLMContractStub()
    _inject_stub(stub)

    try:
        await process_voice_utterance("今天天气怎么样", session_id="voice-test")
        await asyncio.sleep(0.1)  # 让广播 task 完成
    finally:
        await bridge.unregister_client(ws)

    conv = [m for m in ws.received if m.get("type") == "conversation"]
    roles = [m["payload"]["role"] for m in conv]
    assert "user" in roles, f"面板应收到 user(听到的)帧; got {roles}"
    assert "ai" in roles, f"面板应收到 ai(回应)帧; got {roles}"

    user_frame = next(m["payload"] for m in conv if m["payload"]["role"] == "user")
    ai_frame = next(m["payload"] for m in conv if m["payload"]["role"] == "ai")
    assert user_frame["source"] == "voice"
    assert user_frame["text"] == "今天天气怎么样"
    assert ai_frame["source"] == "voice"
    assert ai_frame["speaking"] is True
    assert ai_frame["text"], "AI 回应不应为空"

    # AI 大脑确实被调用(stub 记录调用次数)
    assert stub.call_count >= 1


@pytest.mark.asyncio
async def test_voice_is_first_class_runtime_source():
    """source='voice' 是运行时一等 ingress(不落 unknown-source 兜底)。"""
    from core.desktop_presence_runtime import get_desktop_presence_runtime

    from tests.integration.stubs.llm_contract_stub import LLMContractStub
    stub = LLMContractStub()
    _inject_stub(stub)

    res = await get_desktop_presence_runtime().handle_request(
        message="你好", source="voice", session_id="voice-src", entry_mode="local",
    )
    assert isinstance(res, dict)
    assert res.get("response"), "voice 源应产出回应"
    # tristate 生命周期应完整走完回到 silent
    assert res.get("tristate") == "silent"


def test_process_voice_utterance_noop_when_empty():
    """空文本安全 no-op,不抛。"""
    from core.voice_conversation_bridge import process_voice_utterance
    asyncio.new_event_loop().run_until_complete(process_voice_utterance("   "))
