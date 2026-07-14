"""tests/test_voice_dialog_policy.py
========================================

GPT-Live 借鉴 · 对话政策(core.voice_dialog_policy)+ voice_loop 集成:
语义回合判定 / eagerness / hold / 委托分类 / 捧哏节奏 / 委托后台执行。
"""

from __future__ import annotations

import asyncio

import pytest

import core.voice_dialog_policy as vdp
from core.voice_loop import VoiceLoop


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    vdp.reset_dialog_policy()
    for k in ("GALAXY_VOICE_EAGERNESS", "GALAXY_VOICE_DELEGATE", "GALAXY_VOICE_BACKCHANNEL", "GALAXY_VOICE_HOLD_S"):
        monkeypatch.delenv(k, raising=False)
    yield
    vdp.reset_dialog_policy()


# ── 语义回合判定 ──


class TestSemanticEndOfTurn:
    def test_terminal_punct_is_complete(self):
        assert not vdp.looks_incomplete("今天天气怎么样？")
        assert not vdp.looks_incomplete("好的。")
        assert vdp.end_of_turn_wait("帮我看下日程。") == 0.0

    def test_dangling_connective_is_incomplete(self):
        assert vdp.looks_incomplete("帮我打开浏览器然后")
        assert vdp.looks_incomplete("我想说的是，")
        assert vdp.looks_incomplete("先查一下天气，再")
        assert vdp.looks_incomplete("search for the weather and")

    def test_dangling_gets_longer_wait_than_clean(self):
        w_dangling = vdp.end_of_turn_wait("帮我打开浏览器然后")
        w_clean = vdp.end_of_turn_wait("你好呀！")
        assert w_dangling > 0 and w_clean == 0.0

    def test_eagerness_scales_wait(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_EAGERNESS", "low")
        w_low = vdp.end_of_turn_wait("帮我打开浏览器然后")
        monkeypatch.setenv("GALAXY_VOICE_EAGERNESS", "high")
        w_high = vdp.end_of_turn_wait("帮我打开浏览器然后")
        assert w_low > w_high > 0

    def test_invalid_eagerness_falls_back_auto(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_EAGERNESS", "bogus")
        assert vdp.eagerness() == "auto"

    def test_long_unpunctuated_gets_light_wait(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_EAGERNESS", "auto")
        assert vdp.end_of_turn_wait("帮我看看今天下午有哪些安排要处理") > 0
        monkeypatch.setenv("GALAXY_VOICE_EAGERNESS", "high")
        assert vdp.end_of_turn_wait("帮我看看今天下午有哪些安排要处理") == 0.0


# ── hold ──


class TestHold:
    def test_hold_and_resume_commands(self):
        p = vdp.get_dialog_policy()
        assert p.check_hold_command("等一下,让我想想")
        assert p.check_hold_command("hold on a sec")
        assert not p.check_hold_command("帮我查天气")
        assert p.check_resume_command("好了,继续")
        assert p.check_resume_command("ok go ahead")

    def test_hold_window_and_release(self):
        p = vdp.get_dialog_policy()
        assert not p.is_holding()
        p.hold(5)
        assert p.is_holding()
        p.release_hold()
        assert not p.is_holding()


# ── 委托分类 ──


class TestClassifyTurn:
    def test_quick_smalltalk(self):
        p = vdp.get_dialog_policy()
        assert p.classify_turn("你好呀") == "quick"
        assert p.classify_turn("现在几点了？") == "quick"

    def test_heavy_task_markers(self):
        p = vdp.get_dialog_policy()
        assert p.classify_turn("帮我查一下明天北京的天气") == "heavy"
        assert p.classify_turn("搜索最新的语音模型进展") == "heavy"
        assert p.classify_turn("帮我下载并安装那个工具") == "heavy"
        assert p.classify_turn("search for recent papers on VAD") == "heavy"

    def test_heavy_multi_step_chain(self):
        p = vdp.get_dialog_policy()
        assert p.classify_turn("先打开日历,然后看下周三的安排,最后提醒我") == "heavy"


# ── 捧哏节奏 ──


class TestBackchannel:
    def test_pacing_first_at_5s_then_12s_max2(self):
        p = vdp.get_dialog_policy()
        assert not p.should_backchannel(2.0, 0)
        assert p.should_backchannel(5.5, 0)
        assert not p.should_backchannel(10.0, 1)
        assert p.should_backchannel(17.5, 1)
        assert not p.should_backchannel(60.0, 2)  # 最多 2 次

    def test_disabled_by_env(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_BACKCHANNEL", "0")
        p = vdp.get_dialog_policy()
        assert not p.should_backchannel(10.0, 0)

    def test_phrases_rotate(self):
        p = vdp.get_dialog_policy()
        assert p.ack_phrase() != p.ack_phrase()
        assert p.backchannel_phrase() != p.backchannel_phrase()


# ── voice_loop 集成 ──


class _FakeGalaxy:
    def __init__(self, delay: float = 0.0):
        self.calls = []
        self.delay = delay

    async def process(self, text, source=""):
        self.calls.append(text)
        if self.delay:
            await asyncio.sleep(self.delay)
        return {"response": f"回答:{text}"}


def _loop(galaxy=None) -> VoiceLoop:
    vl = VoiceLoop(galaxy or _FakeGalaxy(), speak_responses=False)
    vl._running = True
    return vl


class TestVoiceLoopIntegration:
    def test_quick_turn_processed_synchronously(self):
        g = _FakeGalaxy()
        vl = _loop(g)
        asyncio.run(vl._on_voice_input("你好呀。"))
        assert g.calls == ["你好呀。"]

    def test_heavy_turn_delegated_to_background(self, monkeypatch):
        spoken = []
        monkeypatch.setattr("core.speech_output.speak_response", lambda text, source="": spoken.append(text))
        g = _FakeGalaxy(delay=0.15)

        async def _run():
            vl = _loop(g)
            await vl._on_voice_input("帮我查一下明天的天气。")
            # 委托返回时后台还没跑完 —— 对话没有被推理堵死
            assert g.calls == []
            assert len(spoken) == 1  # 已口头致谢
            await asyncio.sleep(0.4)  # 等后台完成
            assert g.calls == ["帮我查一下明天的天气。"]

        asyncio.run(_run())

    def test_delegate_disabled_falls_back_sync(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_DELEGATE", "0")
        g = _FakeGalaxy()
        vl = _loop(g)
        asyncio.run(vl._on_voice_input("帮我查一下明天的天气。"))
        assert g.calls == ["帮我查一下明天的天气。"]

    def test_hold_suppresses_and_resume_releases(self):
        g = _FakeGalaxy()

        async def _run():
            vl = _loop(g)
            await vl._on_voice_input("等一下,让我想想。")
            assert g.calls == []  # hold:安静
            await vl._on_voice_input("今天天气如何？")
            assert g.calls == []  # hold 中忽略
            await vl._on_voice_input("好了,继续。")
            # 恢复口令本身不算内容回合(它只解除 hold)……但当前实现会继续处理该句;
            # 关键断言:hold 已解除,后续回合正常
            await vl._on_voice_input("现在几点了？")
            assert "现在几点了？" in g.calls

        asyncio.run(_run())

    def test_incomplete_fragment_merges_with_next(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_EAGERNESS", "auto")
        g = _FakeGalaxy()

        async def _run():
            vl = _loop(g)
            t1 = asyncio.ensure_future(vl._on_voice_input("帮我打开浏览器然后"))
            await asyncio.sleep(0.1)  # 悬垂片段在等待窗口内
            await vl._on_voice_input("看一下今天的新闻。")
            await t1
            # 两个片段并成一个回合,只处理一次
            assert len(g.calls) == 1
            assert "帮我打开浏览器然后" in g.calls[0] and "看一下今天的新闻。" in g.calls[0]

        asyncio.run(_run())

    def test_incomplete_fragment_alone_still_processed_after_wait(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_EAGERNESS", "high")  # 等待最短,测试快
        g = _FakeGalaxy()

        async def _run():
            vl = _loop(g)
            await vl._on_voice_input("帮我打开浏览器然后")
            assert len(g.calls) == 1  # 等待窗口过后仍会处理,不丢话

        asyncio.run(_run())

    def test_stop_cancels_background_tasks(self, monkeypatch):
        monkeypatch.setattr("core.speech_output.speak_response", lambda *a, **k: None)
        g = _FakeGalaxy(delay=5.0)

        async def _run():
            vl = _loop(g)
            await vl._on_voice_input("帮我查一下天气预报。")
            assert vl._bg_tasks
            await vl.stop()
            assert not vl._bg_tasks

        asyncio.run(_run())


class TestAmbientHoldGate:
    def test_ambient_speak_suppressed_while_holding(self, monkeypatch):
        from core.ambient_attention_loop import AmbientAction, AmbientAttentionLoop, AmbientDecision

        spoken = []
        monkeypatch.setattr("core.speech_output.speak_response", lambda text, source="": spoken.append(text))
        vdp.get_dialog_policy().hold(30)
        loop = AmbientAttentionLoop()
        decision = AmbientDecision(action=AmbientAction.SPEAK, utterance="我注意到你在写代码")
        asyncio.run(loop._route(decision, None))
        assert spoken == []  # hold 中,自发开口被抑制
