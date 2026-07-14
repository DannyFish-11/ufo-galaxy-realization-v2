"""tests/test_voice_loop_panel_push.py
========================================
A 融合(语音通路统一)的回归防护。

背景:系统里有两条语音闭环——
- core.voice_loop.VoiceLoop:GALAXY_VOICE=1 默认【开启】,由 unified_launcher
  拉起,真正驱动三态与朗读。
- core.voice_conversation_bridge:GALAXY_VOICE_LOOP=1 默认【关闭】。

面板"实时上下文"的语音显示,靠 core.lumiv_websocket_bridge.emit_conversation
推送。此前【只有默认关闭的那条】调用 emit_conversation,默认开启的 VoiceLoop
从不推送——于是在用户真机的默认配置下,面板的语音实时显示永远是空的。

修复:在默认活跃的 VoiceLoop._on_voice_input 里补上对 emit_conversation 的
调用(用户语音转写 + AI 语音回复各一次)。本测试验证这两次推送确实发生、
角色/来源正确,防止回退。
"""

from __future__ import annotations

import pytest

from core.voice_loop import VoiceLoop


class _FakeGalaxy:
    async def process(self, text, source="voice"):  # noqa: ANN001
        return {"response": f"回应:{text}"}


@pytest.mark.asyncio
async def test_voice_loop_pushes_user_and_ai_turns_to_panel(monkeypatch):
    pushed = []

    def _fake_emit(role, text, *, final=True, speaking=False, source="text", turn_id=""):  # noqa: ANN001
        pushed.append({"role": role, "text": text, "source": source})

    # 拦截真实的 bridge 推送,只观察调用。
    import core.lumiv_websocket_bridge as bridge

    monkeypatch.setattr(bridge, "emit_conversation", _fake_emit)

    loop = VoiceLoop(_FakeGalaxy(), speak_responses=False)
    loop._running = True  # 跳过真实麦克风/音频初始化,直接驱动处理回调

    await loop._on_voice_input("今天天气怎么样")

    # 用户语音转写 + AI 回复,两条都应推给面板,来源都是 voice。
    assert len(pushed) == 2, f"应推送用户+AI 两条,实际: {pushed}"
    assert pushed[0] == {"role": "user", "text": "今天天气怎么样", "source": "voice"}
    assert pushed[1]["role"] == "ai"
    assert pushed[1]["text"] == "回应:今天天气怎么样"
    assert pushed[1]["source"] == "voice"


@pytest.mark.asyncio
async def test_empty_response_still_pushes_user_turn(monkeypatch):
    """AI 回复为空时,用户那句仍应已推送(用户说了话,面板就该显示)。"""
    pushed = []

    def _fake_emit(role, text, *, final=True, speaking=False, source="text", turn_id=""):  # noqa: ANN001
        pushed.append(role)

    import core.lumiv_websocket_bridge as bridge

    monkeypatch.setattr(bridge, "emit_conversation", _fake_emit)

    class _EmptyGalaxy:
        async def process(self, text, source="voice"):  # noqa: ANN001
            return {"response": ""}

    loop = VoiceLoop(_EmptyGalaxy(), speak_responses=False)
    loop._running = True
    await loop._on_voice_input("在吗")

    assert pushed == ["user"], f"空回复时只应推用户那句,实际: {pushed}"


@pytest.mark.asyncio
async def test_emit_failure_does_not_break_voice_processing(monkeypatch):
    """面板推送失败绝不能影响语音主流程(容错)。"""

    def _boom(*a, **k):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("bridge down")

    import core.lumiv_websocket_bridge as bridge

    monkeypatch.setattr(bridge, "emit_conversation", _boom)

    loop = VoiceLoop(_FakeGalaxy(), speak_responses=False)
    loop._running = True
    # 不应抛出。
    await loop._on_voice_input("测试容错")


class TestSingleVoiceLoopExclusion:
    """A 融合互斥的终局(死代码清理):voice_conversation_bridge 是 voice_loop 的
    被架空旧版(自认子集,默认关闭,仅测试引用),已整体删除——互斥从"运行时闸门"
    升级为"结构性不存在"。唯一语音回路 = core.voice_loop。"""

    def test_legacy_bridge_module_removed(self):
        import importlib.util

        assert (
            importlib.util.find_spec("core.voice_conversation_bridge") is None
        ), "voice_conversation_bridge 已删除(voice_loop 是唯一语音回路),不应复活"
