"""tests/test_streaming_speech.py
====================================

分句流式朗读 + barge-in 打断的逻辑（不触真实 edge-tts / 音频设备）。

覆盖：
  - split_into_speakable_chunks：句界切分、短碎片合并、空白折叠、边界。
  - StreamingSpeaker：按序逐句播放、预取下一句与当前句并发、interrupt() 掐断后
    不再播放后续、on_speaking 起止回调、合成/播放异常不致命。

说明：默认 min_chars=6，即"内容不足 6 字的碎片并入邻句"以避免像"好。""是。"
这类独块造成播放频繁启停。因此多块用例统一采用内容 ≥6 字的真实句子。
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from core.streaming_speech import StreamingSpeaker, split_into_speakable_chunks


class TestSplitChunks:
    def test_splits_on_chinese_punctuation(self):
        chunks = split_into_speakable_chunks("今天天气真不错呀。我们出去走走散步吧！你说好不好呢？")
        assert len(chunks) == 3
        assert chunks[0].endswith("。") and chunks[1].endswith("！") and chunks[2].endswith("？")

    def test_splits_on_english_punctuation_and_newline(self):
        chunks = split_into_speakable_chunks(
            "This is the first sentence. Here comes the second one!\nAnd a third line here."
        )
        assert len(chunks) == 3

    def test_merges_tiny_fragments(self):
        # "好。" 内容仅 1 字 → 并入下一句，不单独成块
        chunks = split_into_speakable_chunks("好。我这就帮你查一下最近的错误日志。")
        assert len(chunks) == 1
        assert "好" in chunks[0] and "日志" in chunks[0]

    def test_trailing_text_without_punctuation_kept(self):
        chunks = split_into_speakable_chunks("这是一句完整的话结束了。然后还有没加标点的一截尾巴内容")
        assert len(chunks) == 2
        assert "尾巴" in chunks[-1]

    def test_empty_and_whitespace(self):
        assert split_into_speakable_chunks("") == []
        assert split_into_speakable_chunks("   \n  ") == []

    def test_single_long_sentence_no_punct(self):
        chunks = split_into_speakable_chunks("一句没有任何标点的长句子应当整体作为一块返回")
        assert chunks == ["一句没有任何标点的长句子应当整体作为一块返回"]


class _Recorder:
    """记录合成/播放顺序的可注入桩。"""

    def __init__(self, play_delay: float = 0.0):
        self.synthed: List[str] = []
        self.played: List[str] = []
        self.stopped = 0
        self.speaking_events: List[bool] = []
        self._play_delay = play_delay

    async def synth(self, text: str) -> str:
        self.synthed.append(text)
        return f"handle::{text}"

    async def play(self, handle: str) -> None:
        if self._play_delay:
            await asyncio.sleep(self._play_delay)
        self.played.append(handle)

    async def stop(self) -> None:
        self.stopped += 1

    def on_speaking(self, on: bool) -> None:
        self.speaking_events.append(on)


_THREE = "这是第一句话内容。这是第二句话内容。这是第三句话内容。"


class TestStreamingSpeaker:
    def test_speaks_all_chunks_in_order(self):
        rec = _Recorder()
        sp = StreamingSpeaker(rec.synth, rec.play, stop=rec.stop, on_speaking=rec.on_speaking)
        asyncio.run(sp.speak(_THREE))
        assert rec.played == [
            "handle::这是第一句话内容。",
            "handle::这是第二句话内容。",
            "handle::这是第三句话内容。",
        ]
        assert sp.chunks_spoken == 3
        assert rec.speaking_events[0] is True and rec.speaking_events[-1] is False

    def test_prefetch_synth_overlaps_play(self):
        # 播放有延迟时，下一句合成应与当前句播放并发（合成顺序完整、先于播放推进）。
        rec = _Recorder(play_delay=0.02)
        sp = StreamingSpeaker(rec.synth, rec.play, stop=rec.stop)
        asyncio.run(sp.speak(_THREE))
        assert rec.synthed == ["这是第一句话内容。", "这是第二句话内容。", "这是第三句话内容。"]
        assert len(rec.played) == 3

    def test_interrupt_stops_further_playback(self):
        five = "".join(f"这是第{i}句要念的话。" for i in "一二三四五")
        rec = _Recorder(play_delay=0.05)

        async def run():
            sp = StreamingSpeaker(rec.synth, rec.play, stop=rec.stop, on_speaking=rec.on_speaking)
            task = asyncio.ensure_future(sp.speak(five))
            await asyncio.sleep(0.06)  # 让第一句播起来
            await sp.interrupt()
            await task
            return sp

        sp = asyncio.run(run())
        assert rec.stopped >= 1  # 掐断了当前播放
        assert len(rec.played) < 5  # 没把五句全播完
        assert rec.speaking_events[-1] is False

    def test_empty_text_is_noop(self):
        rec = _Recorder()
        sp = StreamingSpeaker(rec.synth, rec.play)
        asyncio.run(sp.speak(""))
        assert rec.played == [] and rec.synthed == []

    def test_interrupt_discards_unplayed_synthesized_handles(self):
        # 打断时,已合成但没播的句柄必须被 discard 清理(否则临时 mp3 泄漏)。
        five = "".join(f"这是第{i}句要念的话。" for i in "一二三四五")
        rec = _Recorder(play_delay=0.05)
        discarded: List[str] = []

        async def run():
            sp = StreamingSpeaker(
                rec.synth,
                rec.play,
                stop=rec.stop,
                discard=lambda h: discarded.append(h),
            )
            task = asyncio.ensure_future(sp.speak(five))
            await asyncio.sleep(0.06)
            await sp.interrupt()
            await task

        asyncio.run(run())
        # 合成过的句柄里,凡是没被播放的,都应出现在 discarded 中(不泄漏)。
        synth_handles = {f"handle::{c}" for c in rec.synthed}
        played = set(rec.played)
        leaked = synth_handles - played - set(discarded)
        assert not leaked, f"这些已合成句柄既没播也没清理(泄漏): {leaked}"

    def test_synth_failure_skips_chunk_not_fatal(self):
        rec = _Recorder()

        async def flaky_synth(text: str) -> str:
            rec.synthed.append(text)
            if "坏" in text:
                raise RuntimeError("synth boom")
            return f"handle::{text}"

        sp = StreamingSpeaker(flaky_synth, rec.play)
        asyncio.run(sp.speak("这是完好的句子。这是坏掉的句子。这是另一句好的话。"))
        assert "handle::这是完好的句子。" in rec.played
        assert "handle::这是另一句好的话。" in rec.played
        assert all("坏" not in p for p in rec.played)

    def test_play_failure_skips_not_fatal(self):
        rec = _Recorder()

        async def flaky_play(handle: str) -> None:
            if "炸" in handle:
                raise RuntimeError("play boom")
            rec.played.append(handle)

        sp = StreamingSpeaker(rec.synth, flaky_play)
        asyncio.run(sp.speak("这是正常的句子。这是要炸的句子。这也是正常的话。"))
        assert "handle::这是正常的句子。" in rec.played and "handle::这也是正常的话。" in rec.played

    def test_speaking_flag_tracks_state(self):
        rec = _Recorder()
        sp = StreamingSpeaker(rec.synth, rec.play)
        assert sp.speaking is False
        asyncio.run(sp.speak("这是一句完整的话。"))
        assert sp.speaking is False  # 播完复位
