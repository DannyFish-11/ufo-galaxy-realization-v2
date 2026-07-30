"""barge-in 分类("应答"与"真打断")的行为测试。

被修的问题
----------
原先的 barge-in 是"ASR 一出词就掐断朗读"。但人在听别人说话时会一直出声
——"嗯""对""好""哦" —— 那是**积极倾听**,不是要抢话。全当打断的结果是 AI 每讲两句就
被"嗯"一声掐断,对话根本进行不下去。这是"边说边听"体验里最刺眼、也是纯政策层就能修的
一处。

两个方向都要守住
----------------
这个改动有**两种**失败方式,而且第二种更危险:

1. 应答被当成打断 → AI 老被"嗯"打断(改动前的现状);
2. **真打断被当成应答 → 用户想插话却被无视**。这个更糟:用户会以为助手坏了,而且会
   反复大声重复。

所以分类刻意保守:含任何实义内容一律判打断,只有**完全由**语义空的应答词组成、且足够短
的才算应答。``TestRealInterruptionsAlwaysWin`` 就是为第二种失败方式立的防线。
"""

from __future__ import annotations

import asyncio

import pytest

from core.voice_dialog_policy import (
    BARGE_IN_BACKCHANNEL,
    BARGE_IN_INTERRUPT,
    backchannel_tolerance_enabled,
    get_dialog_policy,
    normalize_for_backchannel,
    reset_dialog_policy,
)


@pytest.fixture(autouse=True)
def _fresh_policy():
    reset_dialog_policy()
    yield
    reset_dialog_policy()


# ── 分类语义 ─────────────────────────────────────────────────────────────────


class TestBackchannelsAreRecognised:
    @pytest.mark.parametrize(
        "text",
        [
            "嗯",
            "嗯嗯",
            "哦",
            "噢",
            "唔",
            "对",
            "对对",
            "是",
            "是的",
            "好",
            "好的",
            "行",
            "可以",
            "明白",
            "懂了",
            "知道了",
            "了解",
            "没错",
        ],
    )
    def test_chinese_backchannels(self, text):
        assert get_dialog_policy().classify_barge_in(text) == BARGE_IN_BACKCHANNEL

    @pytest.mark.parametrize("text", ["ok", "OK", "okay", "yeah", "yep", "yes", "right", "sure", "got it", "I see"])
    def test_english_backchannels(self, text):
        assert get_dialog_policy().classify_barge_in(text) == BARGE_IN_BACKCHANNEL

    @pytest.mark.parametrize("text", ["嗯,对", "嗯嗯好的", "哦,明白", "对对对"])
    def test_stacked_backchannels(self, text):
        """连着说几声应答词仍是应答。"""
        assert get_dialog_policy().classify_barge_in(text) == BARGE_IN_BACKCHANNEL

    def test_punctuation_is_ignored(self):
        """ASR 的标点极不稳定,不能参与判断。"""
        assert normalize_for_backchannel("嗯……,") == "嗯"
        assert get_dialog_policy().classify_barge_in("嗯……,") == BARGE_IN_BACKCHANNEL


class TestRealInterruptionsAlwaysWin:
    """最重要的一组:真打断被当成应答的话,用户想插话却被无视 —— 那比"老被嗯打断"更糟。"""

    @pytest.mark.parametrize("text", ["停", "别说了", "别念了", "闭嘴", "打住", "stop", "shut up"])
    def test_stop_commands_are_never_backchannels(self, text):
        assert get_dialog_policy().classify_barge_in(text) == BARGE_IN_INTERRUPT

    @pytest.mark.parametrize("text", ["等一下", "等等", "让我想想"])
    def test_hold_commands_are_never_backchannels(self, text):
        assert get_dialog_policy().classify_barge_in(text) == BARGE_IN_INTERRUPT

    @pytest.mark.parametrize(
        "text",
        [
            "不是这个",
            "帮我订一张去上海的机票",
            "那明天呢",
            "嗯这个不对",  # 以应答词开头,但带实义内容
            "好的那你帮我查一下天气",  # 同上
            "对了还有一件事",
        ],
    )
    def test_anything_with_real_content_is_an_interruption(self, text):
        assert get_dialog_policy().classify_barge_in(text) == BARGE_IN_INTERRUPT

    def test_empty_text_is_an_interruption(self):
        """判不了就按打断处理 —— 宁可多打断一次,也不要吃掉用户真的要说的话。"""
        assert get_dialog_policy().classify_barge_in("") == BARGE_IN_INTERRUPT
        assert get_dialog_policy().classify_barge_in("   ") == BARGE_IN_INTERRUPT

    def test_long_text_is_an_interruption_even_if_words_look_like_backchannels(self):
        from core.voice_dialog_policy import _MAX_BACKCHANNEL_CHARS

        long_text = "好" * (_MAX_BACKCHANNEL_CHARS + 1)
        assert get_dialog_policy().classify_barge_in(long_text) == BARGE_IN_INTERRUPT


class TestToggle:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("GALAXY_VOICE_BACKCHANNEL_TOLERANCE", raising=False)
        assert backchannel_tolerance_enabled() is True

    def test_can_be_switched_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_BACKCHANNEL_TOLERANCE", "0")
        assert backchannel_tolerance_enabled() is False


# ── 真实调用路径 ─────────────────────────────────────────────────────────────


class TestRealCallPathOnVoiceLoop:
    """走 ``VoiceLoop._on_voice_input`` 本体 —— 只测分类函数证明不了它接上了。"""

    @staticmethod
    def _run(text, monkeypatch, *, speaking=True):
        """返回 ``(barge_in 次数, 送进大脑的次数)``。"""
        import core.speech_output as so
        from core.voice_echo_guard import reset_echo_guard
        from core.voice_loop import VoiceLoop

        interrupted: list = []
        processed: list = []
        monkeypatch.setattr(so, "interrupt_speech", lambda: interrupted.append(1))
        monkeypatch.setattr(so, "is_speaking", lambda: speaking)

        class _FakeGalaxy:
            async def process(self, text, source=""):
                processed.append(text)
                return {"response": "ok"}

        reset_echo_guard()

        async def _go():
            loop = VoiceLoop(_FakeGalaxy(), speak_responses=False)
            loop._running = True
            await loop._on_voice_input(text)

        asyncio.run(_go())
        reset_echo_guard()
        return len(interrupted), len(processed)

    @pytest.mark.parametrize("text", ["嗯", "好的", "对对"])
    def test_backchannel_keeps_the_ai_talking(self, monkeypatch, text):
        """既不掐断朗读,也不把这声"嗯"当成一个用户回合 —— 后者会让 AI 对一句语义空的
        应答另起一段回复。"""
        interrupted, processed = self._run(text, monkeypatch)
        assert interrupted == 0, "应答不该掐断朗读"
        assert processed == 0, "应答不该被当成用户回合送进大脑"

    @pytest.mark.parametrize("text", ["停", "不是这个我要另一个", "帮我订一张去上海的机票"])
    def test_real_interruption_still_stops_playback(self, monkeypatch, text):
        interrupted, processed = self._run(text, monkeypatch)
        assert interrupted == 1
        assert processed == 1

    def test_backchannel_when_ai_is_not_speaking_is_a_normal_turn(self, monkeypatch):
        """AI 没在说话时,"嗯"是一个(弱)用户回合,不是应答 —— 比如 AI 刚问完
        "要我继续吗?"、已经念完,用户答"嗯"。此时必须照常处理。"""
        interrupted, processed = self._run("嗯", monkeypatch, speaking=False)
        assert interrupted == 0
        assert processed == 1, "AI 没在朗读时,应答词应作为正常回合处理"

    def test_disabling_tolerance_restores_the_old_interrupt_everything_behaviour(self, monkeypatch):
        """反向验证:关掉开关,"嗯"应恢复为打断 —— 证明这段代码是承重的。"""
        monkeypatch.setenv("GALAXY_VOICE_BACKCHANNEL_TOLERANCE", "0")
        interrupted, processed = self._run("嗯", monkeypatch)
        assert interrupted == 1
        assert processed == 1
