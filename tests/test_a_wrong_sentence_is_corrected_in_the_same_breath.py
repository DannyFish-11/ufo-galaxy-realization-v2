"""说错了,在同一段话里就改过来 —— 总体设计三期(docs/GROUNDED_AGENT_DESIGN.md §3.3)。

* **已说出口、还在生成**:核对线驳倒一句,就请这一次生成在下一个句界收住(适配器每流出一段前后各看一眼;
  半句话不收,迟迟不出句界的最多再放 ``STOP_GRACE_CHARS`` 个字),
  把「第 N 句与某事实不符」当一条观察喂回去,让模型接着说 —— 它自己先更正一句再往下。同一个气泡,
  已流出的字不作废;念的那一路随之念出更正。
* **生成已经结束才核出来**:念完之前补一句口头更正(每轮最多两处;打断过生成、让它自己更正了的不重复)。
* **别的设备发起的**(手表 / 手机只显示一段字):拿到的是改过的文字。
"""

from __future__ import annotations

import asyncio
import json

import pytest

import core.live_check as lc
from core.llm_stream import TokenStream, use_stream

# ── 适配器看得见「停下」 ───────────────────────────────────────────────────


class _Resp:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for ln in self._lines:
            await asyncio.sleep(0)
            yield ln


class _CM:
    def __init__(self, lines):
        self._resp = _Resp(lines)

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _Client:
    def __init__(self, lines):
        self._lines = lines
        self.is_closed = False

    def stream(self, *a, **k):
        return _CM(self._lines)


@pytest.mark.asyncio
async def test_the_local_model_stops_generating_when_asked():
    from core.multi_llm_router import OllamaAdapter, ProviderConfig

    ad = OllamaAdapter(
        ProviderConfig(name="ollama", api_key="", base_url="http://localhost:11434", models=["m"], default_model="m")
    )
    ad._client = _Client(
        [json.dumps({"message": {"content": c}, "done": False}) for c in ("灯已经打开了。", "还要", "调亮度吗")]
    )
    got = []
    sink = TokenStream(on_delta=got.append)

    def on_delta(text):
        got.append(text)
        if text == "灯已经打开了。":
            sink.request_stop("[核对] 不对")

    sink._on_delta = on_delta
    resp = await ad.chat([{"role": "user", "content": "开灯"}], "m", stream=sink)
    assert got == ["灯已经打开了。"], "收到「停下」之后不该再往外吐字"
    assert resp.content == "灯已经打开了。"


# ── 整条:核对线驳倒一句 → 收住 → 带着更正接着说 ─────────────────────────────


@pytest.mark.asyncio
async def test_a_refuted_claim_mid_answer_is_corrected_in_the_same_answer():
    from core.multi_llm_router import LLMResponse
    from core.openclawd import OpenClawd

    calls = []

    def _resp(content, tool_calls=None):
        return LLMResponse(
            content=content,
            provider="p",
            model="m",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1.0,
            tool_calls=tool_calls,
        )

    class _Router:
        async def chat_with_tools(self, messages, tools=None, task_type=None, max_tokens=4096, **kwargs):
            sink = kwargs.get("stream")
            calls.append([dict(m) for m in messages])
            if len(calls) == 1:  # 先去开灯
                return _resp(
                    "", [{"id": "c1", "type": "function", "function": {"name": "home__control", "arguments": "{}"}}]
                )
            if len(calls) == 2:  # 开灯失败了,它却说开好了
                said = []
                for piece in ("灯已经打开了。", "还要", "帮你调亮度吗？"):
                    sink.feed(piece)
                    said.append(piece)
                    await asyncio.sleep(0.05)  # 核对线在这段时间里核完
                    if sink.stop_requested:
                        break
                return _resp("".join(said))
            sink.feed("更正一下：开灯没有成功，需要你在面板上批准。")
            return _resp("更正一下：开灯没有成功，需要你在面板上批准。")

    clawd = OpenClawd.__new__(OpenClawd)
    clawd._get_router = lambda: _Router()

    async def _dispatch(name, args):
        return {"success": False, "error": "approval_denied: 开灯 没有执行:你在面板上拒绝了"}

    clawd._dispatch_tool_call = _dispatch
    frames = []
    ledger, sink = lc.stream_ledger(frames.append)
    with use_stream(sink), lc.use_turn(ledger):
        result = await clawd._react_loop(
            [{"role": "user", "content": "开灯"}], tools=[{"type": "function", "function": {"name": "home__control"}}]
        )

    assert len(calls) == 3, "驳倒之后应当再生成一次(接着说)"
    note = calls[2][-1]
    assert note["role"] == "user" and note["content"].startswith("[核对]") and "灯已经打开了。" in note["content"]
    assert calls[2][-2] == {"role": "assistant", "content": "灯已经打开了。"}
    assert result["response"] == "灯已经打开了。更正一下：开灯没有成功，需要你在面板上批准。"
    deltas = [p for k, p in frames if k == "delta"]
    assert deltas == ["灯已经打开了。", "更正一下：开灯没有成功，需要你在面板上批准。"], "已流出的字不作废,接着往下流"
    assert not [k for k, _ in frames if k == "reset"]
    revise = [p for k, p in frames if k == "revise"]
    assert revise and revise[0]["original"] == "灯已经打开了。"


def test_a_tool_round_reset_drops_the_saved_prefix():
    sink = TokenStream(on_delta=lambda t: None)
    sink.request_stop("[核对] x")
    assert lc.take_correction(sink, "半句。") is not None and sink.prefix == "半句。"
    sink.reset()
    assert sink.prefix == "" and not sink.stop_requested
    assert lc.full_answer(sink, "新的回答。") == "新的回答。"


def test_only_one_interruption_per_turn():
    async def run():
        ledger, sink = lc.stream_ledger(lambda f: None)
        ledger.note("x__write", False, "boom")
        ledger.feed("已经保存好了。")
        await asyncio.sleep(0.05)
        first = sink.stop_note
        lc.take_correction(sink, "已经保存好了。")
        ledger.feed("文件也已经删除了。")
        await asyncio.sleep(0.05)
        return first, sink.stop_requested, ledger

    first, again, ledger = asyncio.run(run())
    assert first.startswith("[核对]") and again is False, "一轮最多打断一次"
    assert ledger.late_spoken_corrections() == ["更正一下：刚才说的那件事其实没有做成。"], "没打断的那一句收尾时口头补"


# ── 生成结束才核出来:念完之前补一句 ─────────────────────────────────────


class _Speaker:
    def __init__(self):
        self.fed = []
        self.finished = False

    def feed(self, text):
        self.fed.append(text)

    def finish(self):
        self.finished = True


def test_a_late_correction_is_said_before_the_voice_finishes():
    async def run():
        ledger = lc.TurnLedger()
        ledger.note("home__control", False, "超时")
        with lc.use_turn(ledger):
            await lc.settle_current("灯已经打开了。")
        speaker = _Speaker()
        lc.finish_speaking(speaker, ledger)
        return speaker

    speaker = asyncio.run(run())
    assert speaker.fed == ["更正一下：刚才说的那件事其实没有做成。"] and speaker.finished


def test_at_most_two_spoken_corrections_per_turn():
    ledger = lc.TurnLedger()
    ledger._revisions = {i: lc.Revision(i, f"第{i}句做好了。", lc.REFUTED, "x", "turn_ledger") for i in range(4)}
    assert len(ledger.late_spoken_corrections()) == 2


# ── 别的设备发起的:拿到改过的文字 ───────────────────────────────────────


def test_a_watch_gets_the_corrected_text_and_the_panel_keeps_the_original():
    async def run(desktop):
        ledger = lc.TurnLedger()
        ledger.note("home__control", False, "没批准")
        result = {"response": "灯已经打开了。"}
        with lc.use_turn(ledger):
            await lc.attach_revisions(result, desktop=desktop)
        return result

    watch = asyncio.run(run(False))
    assert "（更正：" in watch["response"] and watch["response_original"] == "灯已经打开了。"
    panel = asyncio.run(run(True))
    assert panel["response"] == "灯已经打开了。" and "response_original" not in panel


# ── Agent 工厂那条工具循环也记账 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_agent_tool_loop_records_what_really_happened():
    """第 8 轮真跑:任务路径(Agent 工厂建 Agent 去做)调了 tuning__set 且失败,核对线却说「这一轮没有执行任何操作」——
    那条循环(core/agent/react_loop.py)从没往这一轮的账里记过。"""
    from core.agent.react_loop import run_react_tool_loop
    from core.multi_llm_router import LLMResponse

    replies = [
        LLMResponse(
            content="",
            provider="p",
            model="m",
            tool_calls=[{"id": "c1", "function": {"name": "tuning__set", "arguments": "{}"}}],
        ),
        LLMResponse(content="已经帮你设置好了。", provider="p", model="m"),
    ]

    async def llm_call(messages, tools=None):
        return replies.pop(0)

    async def dispatch(name, args):
        return {"success": False, "error": "这个参数不存在"}

    ledger = lc.TurnLedger()
    with lc.use_turn(ledger):
        await run_react_tool_loop(
            messages=[{"role": "user", "content": "调一下"}],
            llm_call=llm_call,
            dispatch_tool=dispatch,
            max_iterations=4,
        )
        (rev,) = await lc.settle_current("已经帮你设置好了。")
    assert ledger.outcomes() == [lc.ToolOutcome("tuning__set", False, "这个参数不存在")]
    assert rev.verdict == lc.REFUTED


# ── 收住在句界上(第 12 轮真跑:每段一出就停,更正接在半句话后面 ——「要我更正一下」) ────────────


def _openai_adapter(pieces):
    from core.multi_llm_router import OpenAIAdapter, ProviderConfig

    ad = OpenAIAdapter(ProviderConfig(name="p", api_key="k", base_url="http://x/v1", models=["m"], default_model="m"))
    lines = [
        "data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": c}}]}, ensure_ascii=False) for c in pieces
    ]
    ad._client = _Client(lines + ["data: [DONE]"])
    return ad


async def _stream(ad, pieces_to_stop_after, sink_factory=TokenStream):
    got = []
    sink = sink_factory(on_delta=got.append)

    def on_delta(text):
        got.append(text)
        if text == pieces_to_stop_after:
            sink.request_stop("[核对] 不对")

    sink._on_delta = on_delta
    resp = await ad.chat([{"role": "user", "content": "x"}], "m", stream=sink)
    return got, resp


@pytest.mark.asyncio
async def test_a_refutation_mid_sentence_waits_for_the_end_of_that_sentence():
    """核出来时正说到半句:说完这句再收,不留「要我」这种半截话给更正接上。"""
    pieces = ["小米手表现在离线，", "连不上它。", "要我", "再试", "试吗？", "还有别的。"]
    got, resp = await _stream(_openai_adapter(pieces), "要我")
    assert "".join(got) == "小米手表现在离线，连不上它。要我再试试吗？"
    assert resp.content == "小米手表现在离线，连不上它。要我再试试吗？"


@pytest.mark.asyncio
async def test_a_refutation_at_a_sentence_end_lets_nothing_more_out():
    """核出来时已经停在句界上:下一段不再流出(那一段是新句子的开头)。"""
    pieces = ["小米手表现在离线，", "连不上它。", "要我", "再试试吗？"]
    got, resp = await _stream(_openai_adapter(pieces), "连不上它。")
    assert got == ["小米手表现在离线，", "连不上它。"] and resp.content == "小米手表现在离线，连不上它。"


@pytest.mark.asyncio
async def test_a_model_that_never_ends_the_sentence_is_still_stopped():
    from core.llm_stream import STOP_GRACE_CHARS

    pieces = ["灯开好了。", "然后"] + ["很长" for _ in range(STOP_GRACE_CHARS)]
    got, _ = await _stream(_openai_adapter(pieces), "然后")
    assert len("".join(got)) <= len("灯开好了。然后") + STOP_GRACE_CHARS + 2, "迟迟不出句界也不会一直说下去"


def test_a_closing_quote_after_the_full_stop_still_counts_as_a_sentence_end():
    sink = TokenStream(on_delta=lambda t: None)
    sink.feed("他说「开好了。」")
    assert sink.at_boundary
    sink.feed("然后")
    assert not sink.at_boundary
    sink.request_stop("[核对] x")
    assert not sink.ready_to_stop()
    sink.feed("呢？")
    assert sink.ready_to_stop()


def test_a_reset_starts_at_a_sentence_boundary():
    sink = TokenStream(on_delta=lambda t: None, on_reset=lambda: None)
    sink.feed("半句")
    sink.reset()
    assert sink.at_boundary and not sink.ready_to_stop()


def test_the_check_line_cuts_sentences_where_the_stream_stops():
    from core.llm_stream import SENTENCE_END

    assert lc._SENT_END is SENTENCE_END
