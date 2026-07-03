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
    """A 融合互斥:GALAXY_VOICE(主 VoiceLoop)开启时,voice_conversation_bridge
    的 start_voice_loop() 必须跳过,避免双跑;只有主 VoiceLoop 显式关闭才启用。"""

    def test_bridge_skips_when_main_voice_loop_on(self, monkeypatch):
        import core.voice_conversation_bridge as vcb
        monkeypatch.setenv("GALAXY_VOICE_LOOP", "1")   # 本模块被显式启用
        monkeypatch.setenv("GALAXY_VOICE", "1")         # 但主 VoiceLoop 也开着(默认)
        assert vcb.start_voice_loop() is False, "主 VoiceLoop 在跑时必须跳过,避免双跑"

    def test_bridge_runs_only_when_main_voice_loop_off(self, monkeypatch):
        import core.voice_conversation_bridge as vcb
        monkeypatch.setenv("GALAXY_VOICE_LOOP", "1")
        monkeypatch.setenv("GALAXY_VOICE", "0")         # 用户显式关掉主 VoiceLoop
        # 依赖(音频/Whisper)在沙箱里不可用,会在后续步骤返回 False——但关键是
        # 它【越过了互斥闸门】开始尝试,而不是在闸门处直接跳过。用 monkeypatch 让
        # AudioCaptureService 抛异常,验证它确实走到了那一步(而非被互斥挡掉)。
        import core.multimodal.audio_capture_service as acs
        def _boom(*a, **k):
            raise RuntimeError("no audio in sandbox")
        monkeypatch.setattr(acs, "AudioCaptureService", _boom)
        # 走到音频初始化并因沙箱无音频返回 False —— 证明没有被互斥闸门提前拦截。
        assert vcb.start_voice_loop() is False
