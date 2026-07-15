"""tests/test_tts_speaking_overlay_sync.py
============================================
桌面三态覆盖层"说话中"动画的回归防护。

现象:用户反馈桌面覆盖层的三态动画不随 AI 实际说话/朗读运转。

根因:``GalaxyPresenceBridge._speaking`` 此前只在相位事件(``phase.liminal``/
``intent.update``)里被动带一手,且 ``_on_phase_manifest`` 一进入 MANIFEST 就
把它强制置 False;而 ``core.speech_output.speak_response()`` 真正播放 TTS
音频发生在文本生成完毕之后(MANIFEST 快结束/已回 SILENT),从未调用过任何
方法去通知 bridge——覆盖层前端(electron/renderer/app.js)虽然正确消费了
``payload.speaking`` 并映射到 ``u_speaking`` 着色器 uniform,但后端从未在
真实播放期间把它置 True,导致"说话动画"永远不会随实际朗读触发。

修复:``speak_response()`` 在调用 ``engine.synthesize_and_play()`` 前后,
通过 ``core.lumiv_websocket_bridge.set_ai_speaking()`` 把 True/False 同步
给 bridge,bridge 立即广播(不等下一次 ambient tick)。
"""

from __future__ import annotations

import asyncio
import time

import pytest


async def _wait_until(cond, timeout: float = 3.0) -> bool:
    """轮询等待条件成立(替代固定 sleep——CI 负载抖动下墙钟假设必翻车)。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.01)
    return cond()


class _FakeWS:
    def __init__(self) -> None:
        self.received: list = []

    async def send_json(self, message) -> None:  # noqa: ANN001
        self.received.append(message)


def _speaking_sequence(frames: list) -> list:
    """从 state_event 帧里抽取 speaking 值序列(压缩连续重复)。"""
    seq = []
    for m in frames:
        if m.get("type") != "state_event":
            continue
        v = m["payload"]["speaking"]
        if not seq or seq[-1] != v:
            seq.append(v)
    return seq


@pytest.mark.asyncio
async def test_speak_response_toggles_overlay_speaking_during_playback(monkeypatch):
    """TTS 播放期间 speaking=True,播放结束后立即回 False,且都广播给覆盖层。"""
    import core.speech_output as so
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge

    bridge = GalaxyPresenceBridge.get_instance()
    bridge._loop = asyncio.get_running_loop()
    ws = _FakeWS()
    await bridge.register_client(ws)

    monkeypatch.setattr(so, "_last_text", "")
    monkeypatch.setattr(so, "_last_ts", 0.0)

    played = {"active": False, "saw_active": False}

    class _FakeEngine:
        async def synthesize_and_play(self, text):  # noqa: ANN001
            played["active"] = True
            await asyncio.sleep(0.15)
            played["saw_active"] = True
            played["active"] = False

    try:
        monkeypatch.setattr(so, "_get_engine", lambda: _FakeEngine())
        monkeypatch.setattr(so, "speak_enabled", lambda: True)
        # 本测试钉的是【整段批处理】路径的 set_ai_speaking 前后同步
        # (_FakeEngine 只实现 synthesize_and_play)。分句流式成为默认后,
        # 不关掉流式会走 StreamingSpeaker → 假引擎缺 synthesize/_play_audio
        # → 零句播出,断言恒失败。流式路径的 on_speaking 同步由
        # StreamingSpeaker 自身的测试覆盖。
        monkeypatch.setenv("GALAXY_TTS_STREAMING", "0")

        so.speak_response("今天天气不错", source="voice")
        assert await _wait_until(lambda: played["active"]), "播放应在期限内开始"
        assert await _wait_until(lambda: played["saw_active"] and not played["active"]), "播放应在期限内彻底结束"
        # 结束后的 speaking=False 广播帧也可能晚于引擎返回一拍,等它落地
        assert await _wait_until(
            lambda: (lambda s: True in s and s[-1] is False)(_speaking_sequence(ws.received))
        ), f"覆盖层应先后收到 speaking=True/False; got {_speaking_sequence(ws.received)}"
    finally:
        await bridge.unregister_client(ws)

    seq = _speaking_sequence(ws.received)
    assert True in seq, f"覆盖层应收到过 speaking=True 的广播帧; got {seq}"
    assert seq[-1] is False, f"播放结束后应最终回 speaking=False; got {seq}"


def test_set_ai_speaking_never_raises():
    """set_ai_speaking 对无客户端/无事件循环等边界情况永不抛出。"""
    from core.lumiv_websocket_bridge import set_ai_speaking

    set_ai_speaking(True)
    set_ai_speaking(False)


def test_speaking_broadcast_snapshots_value_no_lost_true_pulse():
    """竞态回归:set_ai_speaking(True) 的广播帧必须携带【调用时快照值】。

    根因:广播是 fire-and-forget 任务,_build_message 原读 live self._speaking;
    True→播放→False 两次快速切换下,若 True 广播任务被事件循环饿过后面的
    _speaking=False,它会读到 False → True 脉冲丢失(说话动画偶发不起 + CI flaky)。
    本测试强制复现该顺序,断言快照修复后 True 帧仍为 True。
    """
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge

    b = GalaxyPresenceBridge.get_instance()
    _saved = b._speaking  # bridge 是单例:测完必须还原,否则污染后续测试
    try:
        b._speaking = True
        frame_true = b._build_message(speaking_override=True)
        # 模拟后到的 set_ai_speaking(False) 抢先把 live 态翻了
        b._speaking = False
        frame_live = b._build_message()

        assert frame_true["payload"]["speaking"] is True, "快照未生效:True 脉冲会被丢!"
        assert frame_live["payload"]["speaking"] is False
        # 说话深度地板也应随快照抬起(说话时维持可见在场深度)
        assert frame_true["payload"]["depth_factor"] >= 0.5
        # 默认(无 override)沿用 live,其它调用点行为不变
        b._speaking = True
        assert b._build_message()["payload"]["speaking"] is True
    finally:
        b._speaking = _saved
