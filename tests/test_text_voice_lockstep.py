"""文字/语音锁步:验证 IncrementalSpeaker 的逐句"开口即回调"机制。

锁步(GALAXY_TEXT_VOICE_LOCKSTEP)下,core/routes/chat.py 不再即时上屏文字,而是把
token 喂给 TTS,靠 speaker 的 on_sentence_start(每句真正开始播放时回调其文本)把
文字与语音同刻逐句露出。本测试锁死这个回调的正确性(逐句、顺序与播放一致、reset
作废、grace 有界),因为 chat.py 的锁步露出直接建立在它之上。
"""

import asyncio

import pytest

from core.streaming_speech import IncrementalSpeaker


def _mk(revealed, spoken, *, synth_fail_on=None):
    async def synth(text):
        if synth_fail_on is not None and synth_fail_on in text:
            raise RuntimeError("synth boom")
        return text  # 句柄即文本

    async def play(handle):
        spoken.append(handle)
        await asyncio.sleep(0.005)

    return IncrementalSpeaker(synth, play, on_sentence_start=lambda t: revealed.append(t))


@pytest.mark.asyncio
async def test_on_sentence_start_fires_per_played_sentence_in_order():
    revealed, spoken = [], []
    sp = _mk(revealed, spoken)
    assert sp.start()
    # 分多次喂(模拟 token 流),凑满句子才播
    for tok in ["你好呀。", "今天", "天气", "不错！", "那我们", "出发吧？"]:
        sp.feed(tok)
    sp.finish()
    await asyncio.wait_for(sp._player_task, timeout=5)
    # 每句"开口即回调"的文本,必须与实际播放的文本【逐一对应、顺序一致】
    assert revealed == spoken
    assert spoken, "应至少念出一句"
    # 露出的文本拼起来应覆盖喂入的全部可读内容(不丢句)
    joined = "".join(spoken)
    for kw in ["你好", "天气", "出发"]:
        assert kw in joined


@pytest.mark.asyncio
async def test_reset_discards_unspoken_and_callback_not_fired_for_them():
    revealed, spoken = [], []
    sp = _mk(revealed, spoken)
    assert sp.start()
    sp.feed("第一代内容会被作废。")
    sp.reset()  # 级联换档:作废未念的
    sp.feed("第二代内容才是权威。")
    sp.finish()
    await asyncio.wait_for(sp._player_task, timeout=5)
    # 被 reset 作废的那代不应作为"已开口"回调出去
    assert all("第一代" not in r for r in revealed)
    assert revealed == spoken  # 仍保持"回调==实际播放"不变量


@pytest.mark.asyncio
async def test_lockstep_drain_loop_terminates_when_player_done():
    """模拟 chat.py 锁步收尾的 drain 循环:player 结束 + 队列空 → 必然终止。"""
    revealed, spoken = [], []
    sp = _mk(revealed, spoken)
    assert sp.start()
    sp.feed("一句话就够了。")
    sp.finish()

    # 复刻 chat.py 的有界 drain
    reveal_q = revealed  # 这里 revealed 就是回调塞入的列表,充当队列语义
    loop = asyncio.get_running_loop()
    grace = loop.time() + 5.0
    idx = 0
    ptask = sp._player_task
    out = []
    while True:
        while idx < len(reveal_q):
            out.append(reveal_q[idx])
            idx += 1
        if ptask.done() and idx >= len(reveal_q):
            break
        if loop.time() >= grace:
            pytest.fail("drain 循环未在 player 结束后终止(疑似挂死)")
        await asyncio.sleep(0.02)
    assert out == spoken
