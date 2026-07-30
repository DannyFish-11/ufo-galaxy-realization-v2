"""反自激励门的行为测试。

被修的真实缺陷
--------------
本地语音闭环是 ``麦克风 → VAD → Whisper → VoiceLoop._on_voice_input``。AI 用 TTS
把回复从扬声器念出去,同一间屋子的麦克风必然把这段声音重新采回来,转写成文字流进
``_on_voice_input``。在那之前那里没有任何防护,于是:

1. 开头的 barge-in 逻辑把"出词"当成用户开口的证据,把 AI 自己的朗读掐断;
2. 转写出的文字继续往下走进大脑 → AI 对自己说的话作答 → 自言自语闭环。

所以本文件的重点不是"相似度函数算得对不对",而是**两个症状在真实调用路径上确实
消失了,而真正的 barge-in 没被一起杀掉**。后者是关键:简单地"朗读期间丢掉所有
音频"也能消除症状 1 和 2,但会同时废掉本仓库明确提供的"你一说话它就闭嘴"。

``TestRealCallPathOnVoiceLoop`` 就是为此存在的 —— 它走 ``VoiceLoop._on_voice_input``
本体,而不是直接调门。
"""

from __future__ import annotations

import asyncio

import pytest

REPLY = "北京今天多云,气温 22 到 30 度,空气质量良好,适合外出活动。"


@pytest.fixture
def guard():
    """每个用例一个干净的门实例(不用进程单例,避免用例间互相污染)。"""
    from core.voice_echo_guard import EchoGuard

    return EchoGuard()


# ── 判定语义 ─────────────────────────────────────────────────────────────────


class TestVerdicts:
    def test_verbatim_fragment_of_what_we_just_said_is_echo(self, guard):
        from core.voice_echo_guard import VERDICT_SELF_ECHO

        guard.note_utterance(REPLY)
        verdict, score, _ = guard.classify("北京今天多云气温22到30度")
        assert verdict == VERDICT_SELF_ECHO
        assert score >= 0.62

    def test_a_genuinely_new_request_is_the_user(self, guard):
        from core.voice_echo_guard import VERDICT_USER

        guard.note_utterance(REPLY)
        verdict, _, _ = guard.classify("帮我订一张去上海的机票")
        assert verdict == VERDICT_USER

    def test_nothing_recently_spoken_means_everything_is_the_user(self, guard):
        from core.voice_echo_guard import VERDICT_USER

        verdict, _, reason = guard.classify("北京今天多云气温22到30度")
        assert verdict == VERDICT_USER
        assert reason == "nothing_recent"

    @pytest.mark.parametrize("cmd", ["停", "别念了", "闭嘴", "等等"])
    def test_short_interrupt_commands_always_pass(self, guard, cmd):
        """打断口令又短又常见,必须永远通得过——否则用户喊"停"会被门吃掉。"""
        from core.voice_echo_guard import VERDICT_USER

        guard.note_utterance(REPLY)
        verdict, _, reason = guard.classify(cmd)
        assert verdict == VERDICT_USER
        assert reason == "too_short"

    def test_scattered_single_char_overlap_is_not_evidence(self, guard):
        """中文常用字少:一句短话的每个字几乎必然散落在长回复的某处,总重合能凑到
        很高。只看总比例会把用户真的说的话判成回声,所以还要求一段足够长的【连续】
        命中。本用例锁住这条防线。"""
        from core.voice_echo_guard import VERDICT_USER, normalize, overlap

        guard.note_utterance(REPLY)
        # 这句的每个字都在 REPLY 里,但没有任何长连续段
        probe = "今度好air"
        _containment, longest = overlap(normalize(probe), normalize(REPLY))
        assert longest < 4, "前提:这句在 REPLY 里没有长连续段"
        verdict, _, _ = guard.classify(probe)
        assert verdict == VERDICT_USER

    @pytest.mark.parametrize(
        "asr_text",
        [
            "北京今天多运气温22到30度",  # 同音字错误 云→运
            "京今天多云气温22到30",  # 首尾丢字
            "空气质量良好十分适合外出活动",  # 插入词
            "恩北京今天多云气温22到30度啊",  # 首尾填充词
        ],
    )
    def test_robust_to_realistic_asr_noise(self, guard, asr_text):
        """真实 ASR 不会逐字复现 TTS 文本。门必须容忍同音字、丢字、插词。"""
        from core.voice_echo_guard import VERDICT_SELF_ECHO

        guard.note_utterance(REPLY)
        verdict, _, _ = guard.classify(asr_text)
        assert verdict == VERDICT_SELF_ECHO


# ── 留存窗口 ─────────────────────────────────────────────────────────────────


class TestRetentionWindow:
    def test_utterance_expires_after_the_tail(self, guard, monkeypatch):
        from core.voice_echo_guard import VERDICT_SELF_ECHO, VERDICT_USER

        monkeypatch.setenv("GALAXY_VOICE_ECHO_TAIL_S", "6")
        guard.note_utterance(REPLY)
        assert guard.classify("北京今天多云气温22到30度")[0] == VERDICT_SELF_ECHO

        # 把这条记录的时间戳推回到"很久以前"
        for utt in guard._utterances:
            utt.ts -= 10_000.0
        assert guard.classify("北京今天多云气温22到30度")[0] == VERDICT_USER

    def test_long_reply_stays_live_longer_than_the_fixed_tail(self, guard, monkeypatch):
        """流式朗读整段登记、逐句播出:一段长回复登记时刻很早、播完很晚。若留存只有
        固定尾巴,它会在【还没念完时】就过期,回声照旧漏进来。故留存 = 估算朗读耗时
        + 尾巴。"""
        monkeypatch.setenv("GALAXY_VOICE_ECHO_TAIL_S", "6")
        from core.voice_echo_guard import _Utterance, tail_seconds

        short = _Utterance(norm="好的马上办", ts=0.0)
        long_ = _Utterance(norm="一" * 400, ts=0.0)
        tail = tail_seconds()
        assert short.expires_at(tail) == pytest.approx(6.0 + 1.0, abs=0.01)
        assert long_.expires_at(tail) > 80.0

    def test_utterances_are_bounded(self, guard):
        """登记来自每一句朗读,必须有上界,不能随会话时长无界增长。"""
        from core.voice_echo_guard import _MAX_UTTERANCES

        for i in range(_MAX_UTTERANCES * 3):
            guard.note_utterance(f"这是第{i}句话的内容足够长以便登记")
        assert len(guard._utterances) == _MAX_UTTERANCES


# ── 开关与降级 ───────────────────────────────────────────────────────────────


class TestDefaultsAndDegradation:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("GALAXY_VOICE_ECHO_GUARD", raising=False)
        from core.voice_echo_guard import enabled

        assert enabled() is True

    def test_can_be_switched_off(self, guard, monkeypatch):
        from core.voice_echo_guard import VERDICT_USER

        monkeypatch.setenv("GALAXY_VOICE_ECHO_GUARD", "0")
        guard.note_utterance(REPLY)
        verdict, _, reason = guard.classify("北京今天多云气温22到30度")
        assert verdict == VERDICT_USER
        assert reason == "disabled"

    def test_internal_failure_falls_open_to_user(self, guard, monkeypatch):
        """门失灵的后果必须是"助手照常听人说话",而不是"助手变聋"。"""
        import core.voice_echo_guard as m
        from core.voice_echo_guard import VERDICT_USER

        def _boom(*_a, **_k):
            raise RuntimeError("injected")

        monkeypatch.setattr(m, "normalize", _boom)
        guard.note_utterance(REPLY)
        verdict, _, reason = guard.classify("随便什么话都行")
        assert verdict == VERDICT_USER
        assert reason == "guard_error"

    def test_bad_numeric_env_falls_back_to_default(self, monkeypatch, caplog):
        monkeypatch.setenv("GALAXY_VOICE_ECHO_SIM", "not-a-number")
        from core.voice_echo_guard import similarity_threshold

        with caplog.at_level("WARNING"):
            assert similarity_threshold() == pytest.approx(0.62)
        assert "不是合法数值" in caplog.text

    def test_suppression_streak_is_visible(self, guard, caplog):
        """相似度门若误判,症状是"助手不理人"。连续压制必须升 WARNING,不能静默。"""
        from core.voice_echo_guard import _SUPPRESS_STREAK_WARN

        guard.note_utterance(REPLY)
        with caplog.at_level("WARNING"):
            for _ in range(_SUPPRESS_STREAK_WARN):
                guard.classify("北京今天多云气温22到30度")
        assert "连续压制" in caplog.text


# ── recently_spoke:给"只能按时间挡"的调用方 ────────────────────────────────


class TestRecentlySpoke:
    def test_false_before_anything_is_said(self, guard):
        assert guard.recently_spoke() is False

    def test_true_right_after_speaking(self, guard):
        guard.note_utterance(REPLY)
        assert guard.recently_spoke() is True

    def test_false_once_expired(self, guard):
        guard.note_utterance(REPLY)
        for utt in guard._utterances:
            utt.ts -= 10_000.0
        assert guard.recently_spoke() is False


# ── 真实调用路径:两个症状是否真的消失,barge-in 是否真的还活着 ─────────────


class TestRealCallPathOnVoiceLoop:
    """走 ``VoiceLoop._on_voice_input`` 本体。

    直接调门只能证明门自己算得对;只有走这条真实路径,才能证明门**接上了**,而且
    接的位置正确(必须在 barge-in 之前——接在之后的话,AI 仍会被自己的回声掐断)。
    """

    @staticmethod
    def _run(asr_text, monkeypatch):
        """返回 ``(barge_in 次数, 送进大脑的次数)``。"""
        import core.speech_output as so
        from core.voice_echo_guard import note_utterance, reset_echo_guard
        from core.voice_loop import VoiceLoop

        interrupted: list = []
        processed: list = []
        monkeypatch.setattr(so, "interrupt_speech", lambda: interrupted.append(1))
        monkeypatch.setattr(so, "is_speaking", lambda: True)  # 模拟"AI 正在朗读"

        class _FakeGalaxy:
            async def process(self, text, source=""):
                processed.append(text)
                return {"response": "ok"}

        reset_echo_guard()
        note_utterance(REPLY)  # AI 刚把 REPLY 念出去

        async def _go():
            loop = VoiceLoop(_FakeGalaxy(), speak_responses=False)
            loop._running = True
            await loop._on_voice_input(asr_text)

        asyncio.run(_go())
        reset_echo_guard()
        return len(interrupted), len(processed)

    def test_self_echo_neither_interrupts_nor_reaches_the_brain(self, monkeypatch):
        """症状 1+2 同时消失:AI 不再掐断自己,也不再对自己说的话作答。"""
        interrupted, processed = self._run("北京今天多云气温22到30度", monkeypatch)
        assert interrupted == 0, "AI 不应被自己的回声掐断朗读"
        assert processed == 0, "AI 自己说的话不应被当作用户输入送进大脑"

    def test_real_user_speech_still_barges_in_and_is_processed(self, monkeypatch):
        """关键回归防线:门不能把真正的 barge-in 一起杀掉。"""
        interrupted, processed = self._run("帮我订一张去上海的机票", monkeypatch)
        assert interrupted == 1, "用户真的开口时仍须立刻掐断朗读"
        assert processed == 1, "用户真的开口时仍须送进大脑"

    def test_bug_reproduces_when_the_guard_is_disabled(self, monkeypatch):
        """反向验证:关掉门,两个症状必须原样复现——证明这段代码是承重的,不是装饰。"""
        monkeypatch.setenv("GALAXY_VOICE_ECHO_GUARD", "0")
        interrupted, processed = self._run("北京今天多云气温22到30度", monkeypatch)
        assert interrupted == 1
        assert processed == 1


# ── 接线:发声侧真的登记了吗 ────────────────────────────────────────────────


class TestWiredIntoTheSpeakingPaths:
    def test_speak_response_registers_the_utterance(self, monkeypatch):
        """``speak_response`` 是原生 / 整段批处理 / 分句流式三条发声路径的分叉点,
        登记在这里一次就三条全覆盖。"""
        import core.speech_output as so
        from core.voice_echo_guard import get_echo_guard, reset_echo_guard

        reset_echo_guard()
        monkeypatch.setattr(so, "_maybe_speak_native", lambda *_a, **_k: True)  # 不真发声
        monkeypatch.setattr(so, "speak_enabled", lambda: True)
        so._last_text, so._last_ts = "", 0.0  # 绕开 3 秒去重
        so.speak_response("北京今天多云,气温22到30度。", source="chat")

        stats = get_echo_guard().stats()
        assert stats["noted"] == 1
        assert stats["live_utterances"] == 1
        reset_echo_guard()

    def test_incremental_speaker_registers_each_sentence(self):
        """边生成边念(/chat/stream)不经 speak_response —— 文本是逐 token 喂进来的,
        所以那条路必须自己登记,否则流式朗读的回声完全没人挡。"""
        from core.streaming_speech import _note_spoken
        from core.voice_echo_guard import get_echo_guard, reset_echo_guard

        reset_echo_guard()
        _note_spoken("这是流式朗读的一句话。")
        assert get_echo_guard().stats()["noted"] == 1
        reset_echo_guard()

    def test_ambient_gate_also_covers_non_streaming_speak_paths(self, monkeypatch):
        """``is_speaking()`` 只在流式路径上为真;整段批处理 / 原生发声下它恒为 False,
        单靠它的门是失效的。ambient 那条门必须同时看 ``recently_spoke()``。"""
        import core.ambient_attention_loop as al
        import core.speech_output as so
        from core.voice_echo_guard import note_utterance, reset_echo_guard

        reset_echo_guard()
        monkeypatch.setattr(so, "is_speaking", lambda: False)  # 模拟非流式路径
        assert al._ai_is_speaking() is False, "前提:此刻两个来源都说没在朗读"

        note_utterance(REPLY)  # 非流式路径刚念完一段
        assert al._ai_is_speaking() is True, "整段批处理/原生发声也必须被挡住"
        reset_echo_guard()
