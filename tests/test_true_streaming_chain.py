"""tests/test_true_streaming_chain.py
=====================================
真流式链路(token 边生成边到)的回归防护,覆盖五层:

  1. core.llm_stream.TokenStream — 增量通道语义(feed/reset/回调异常不反噬)
     与 contextvars 请求级隔离(use_stream/current_stream)。
  2. streaming_speech.extract_speakable_prefix — 增量句界(非 ASCII 标点即界、
     ASCII 句点须后随空白、不足 min_chars 续攒)。
  3. streaming_speech.IncrementalSpeaker — 边生成边念:句成即播、finish 冲尾、
     reset 作废未播、interrupt 即刻闭嘴、on_speaking 起止同步。
  4. 适配器真流式 — OllamaAdapter NDJSON / OpenAIAdapter SSE:增量喂 sink、
     全文与 token 数组装正确、工具调用增量按 index 组装且【不】泄漏进 sink。
  5. 编排层 reset 语义 — chat_cascade 换档作废草稿;openclawd._react_loop 把
     请求上下文里的 sink 传给路由层、工具轮后作废过场话。
  6. /api/v1/chat/stream — 真增量帧逐帧转发 + reset 帧 + done 对账全文;
     零增量时退回逐字假流式(行为兜底)。

全部用注入的假引擎/假 HTTP 客户端,离线可跑。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 1. TokenStream + contextvars
# ---------------------------------------------------------------------------

class TestTokenStream:
    def test_feed_and_reset_counters(self):
        from core.llm_stream import TokenStream
        got, resets = [], []
        s = TokenStream(on_delta=got.append, on_reset=lambda: resets.append(1))
        s.feed("你好")
        s.feed("")          # 空串跳过
        s.feed("世界")
        assert got == ["你好", "世界"]
        assert s.chars == 4 and s.total_chars == 4
        s.reset()
        assert s.chars == 0 and s.total_chars == 4 and s.resets == 1
        assert len(resets) == 1
        s.feed("again")
        assert s.chars == 5

    def test_callback_exception_never_propagates(self):
        from core.llm_stream import TokenStream

        def _boom(_):
            raise RuntimeError("boom")

        s = TokenStream(on_delta=_boom, on_reset=None)
        s.feed("x")   # 不抛
        s.reset()     # on_reset None 也不抛
        assert s.total_chars == 1

    def test_use_stream_context_isolation(self):
        from core.llm_stream import TokenStream, current_stream, use_stream
        assert current_stream() is None
        sink = TokenStream(on_delta=lambda t: None)
        with use_stream(sink):
            assert current_stream() is sink
            with use_stream(None):
                assert current_stream() is None
            assert current_stream() is sink
        assert current_stream() is None

    @pytest.mark.asyncio
    async def test_context_propagates_into_awaited_chain(self):
        """消费端挂 sink → 深层 await 链里的生成点能取到(同一任务上下文)。"""
        from core.llm_stream import TokenStream, current_stream, use_stream

        async def _deep():
            await asyncio.sleep(0)
            return current_stream()

        sink = TokenStream(on_delta=lambda t: None)

        async def _run():
            with use_stream(sink):
                return await _deep()

        got = await asyncio.get_running_loop().create_task(_run())
        assert got is sink
        assert current_stream() is None  # 任务外不可见


# ---------------------------------------------------------------------------
# 2. extract_speakable_prefix
# ---------------------------------------------------------------------------

class TestExtractSpeakablePrefix:
    def test_cjk_boundary_immediate(self):
        from core.streaming_speech import extract_speakable_prefix
        chunks, rest = extract_speakable_prefix("今天天气不错。明天呢")
        assert chunks == ["今天天气不错。"]
        assert rest == "明天呢"

    def test_ascii_period_at_tail_is_held(self):
        """句点在缓冲末尾时下一字符未知(可能是 3.14),必须继续等。"""
        from core.streaming_speech import extract_speakable_prefix
        chunks, rest = extract_speakable_prefix("The value is 3.")
        assert chunks == []
        assert rest == "The value is 3."

    def test_ascii_period_followed_by_space_is_boundary(self):
        from core.streaming_speech import extract_speakable_prefix
        chunks, rest = extract_speakable_prefix("It works fine. And then")
        assert chunks == ["It works fine."]
        assert rest == " And then"

    def test_short_prefix_keeps_accumulating(self):
        from core.streaming_speech import extract_speakable_prefix
        chunks, rest = extract_speakable_prefix("好。", min_chars=6)
        assert chunks == []
        assert rest == "好。"

    def test_no_boundary_returns_everything_as_remainder(self):
        from core.streaming_speech import extract_speakable_prefix
        chunks, rest = extract_speakable_prefix("还没说完呢")
        assert chunks == [] and rest == "还没说完呢"


# ---------------------------------------------------------------------------
# 3. IncrementalSpeaker
# ---------------------------------------------------------------------------

def _mk_speaker(played, discarded=None, speaking_events=None, min_chars=1):
    from core.streaming_speech import IncrementalSpeaker

    async def _synth(text):
        await asyncio.sleep(0)
        return f"mp3:{text}"

    async def _play(handle):
        await asyncio.sleep(0.01)
        played.append(handle)

    async def _stop():
        pass

    return IncrementalSpeaker(
        _synth, _play, stop=_stop,
        on_speaking=(speaking_events.append if speaking_events is not None else None),
        discard=(discarded.append if discarded is not None else None),
        min_chars=min_chars,
    )


class TestIncrementalSpeaker:
    @pytest.mark.asyncio
    async def test_sentences_play_in_order_and_finish_flushes_tail(self):
        played, speaking = [], []
        sp = _mk_speaker(played, speaking_events=speaking)
        assert sp.start()
        sp.feed("第一句话。第二")
        sp.feed("句话！尾巴没有标点")
        sp.finish()
        await asyncio.wait_for(sp._player_task, timeout=5)
        assert played == ["mp3:第一句话。", "mp3:第二句话！", "mp3:尾巴没有标点"]
        assert sp.spoke_anything and sp.chunks_spoken == 3
        # on_speaking: 起(True)止(False)各至少一次,末次必为 False
        assert True in speaking and speaking[-1] is False

    @pytest.mark.asyncio
    async def test_reset_discards_unplayed(self):
        played = []
        sp = _mk_speaker(played)
        assert sp.start()
        sp.feed("作废的草稿一。作废的草稿二。")
        sp.reset()  # 换档:队列作废
        sp.feed("最终答案。")
        sp.finish()
        await asyncio.wait_for(sp._player_task, timeout=5)
        # 竞态窗口:reset 前第一句可能已开播(与真实 barge-in 语义一致,stop 掐断),
        # 但 reset 之后旧代内容绝不再新增;最终答案一定在,且是最后一句。
        assert played[-1] == "mp3:最终答案。"
        assert "mp3:作废的草稿二。" not in played

    @pytest.mark.asyncio
    async def test_interrupt_stops_and_rejects_further_feed(self):
        played = []
        sp = _mk_speaker(played)
        assert sp.start()
        sp.feed("第一句。")
        await sp.interrupt()
        sp.feed("打断之后不该念这句。")
        sp.finish()
        await asyncio.wait_for(sp._player_task, timeout=5)
        assert "mp3:打断之后不该念这句。" not in played

    @pytest.mark.asyncio
    async def test_no_running_loop_start_returns_false(self):
        played = []
        sp = _mk_speaker(played)

        def _sync_start():
            return sp.start()

        # start() 在无运行循环的线程里应返回 False(调用方降级),不抛。
        ok = await asyncio.to_thread(_sync_start)
        assert ok is False


# ---------------------------------------------------------------------------
# 4. 适配器真流式
# ---------------------------------------------------------------------------

class _FakeStreamResp:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for ln in self._lines:
            await asyncio.sleep(0)
            yield ln


class _FakeStreamCM:
    def __init__(self, lines):
        self._resp = _FakeStreamResp(lines)

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    def __init__(self, lines):
        self._lines = lines
        self.is_closed = False

    def stream(self, *a, **k):
        return _FakeStreamCM(self._lines)


def _mk_sink(collected, resets=None):
    from core.llm_stream import TokenStream
    return TokenStream(
        on_delta=collected.append,
        on_reset=(lambda: resets.append(1)) if resets is not None else None,
    )


class TestOllamaStreaming:
    @pytest.mark.asyncio
    async def test_ndjson_deltas_feed_sink_and_final_counts(self):
        from core.multi_llm_router import OllamaAdapter, ProviderConfig

        cfg = ProviderConfig(name="ollama", api_key="",
                             base_url="http://localhost:11434", models=["m"],
                             default_model="m")
        ad = OllamaAdapter(cfg)
        lines = [
            json.dumps({"message": {"content": "你"}, "done": False}),
            json.dumps({"message": {"content": "好"}, "done": False}),
            "",  # 空行容忍
            json.dumps({"message": {"content": ""}, "done": True,
                        "prompt_eval_count": 7, "eval_count": 2}),
        ]
        ad._client = _FakeClient(lines)
        got = []
        sink = _mk_sink(got)
        resp = await ad.chat([{"role": "user", "content": "hi"}], "m", stream=sink)
        assert got == ["你", "好"]
        assert resp.content == "你好"
        assert resp.input_tokens == 7 and resp.output_tokens == 2
        assert resp.provider == "ollama"


class TestOpenAIStreaming:
    def test_merge_tool_call_delta_assembles_fragments(self):
        from core.multi_llm_router import OpenAIAdapter
        acc = {}
        OpenAIAdapter._merge_tool_call_delta(acc, {
            "index": 0, "id": "call_1", "type": "function",
            "function": {"name": "get_weather", "arguments": "{\"ci"},
        })
        OpenAIAdapter._merge_tool_call_delta(acc, {
            "index": 0, "function": {"arguments": "ty\": \"北京\"}"},
        })
        assert acc[0]["id"] == "call_1"
        assert acc[0]["function"]["name"] == "get_weather"
        assert json.loads(acc[0]["function"]["arguments"]) == {"city": "北京"}

    @pytest.mark.asyncio
    async def test_sse_content_streams_and_tool_calls_never_leak_to_sink(self):
        from core.multi_llm_router import OpenAIAdapter, ProviderConfig

        cfg = ProviderConfig(name="deepseek", api_key="k",
                             base_url="https://api.deepseek.com/v1",
                             models=["m"], default_model="m")
        ad = OpenAIAdapter(cfg)
        lines = [
            'data: ' + json.dumps({"choices": [{"delta": {"content": "答"}}]}),
            'data: ' + json.dumps({"choices": [{"delta": {"content": "案"}}]}),
            'data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": "c1",
                "function": {"name": "t", "arguments": "{}"},
            }]}}]}),
            'data: ' + json.dumps({"choices": [], "usage": {
                "prompt_tokens": 5, "completion_tokens": 2}}),
            'data: [DONE]',
        ]
        ad._client = _FakeClient(lines)
        got = []
        sink = _mk_sink(got)
        resp = await ad.chat([{"role": "user", "content": "hi"}], "m", stream=sink)
        assert got == ["答", "案"]          # 工具调用片段绝不进 sink
        assert resp.content == "答案"
        assert resp.tool_calls and resp.tool_calls[0]["function"]["name"] == "t"
        assert resp.input_tokens == 5 and resp.output_tokens == 2


# ---------------------------------------------------------------------------
# 5. 编排层 reset 语义
# ---------------------------------------------------------------------------

class _StageAdapter:
    """假适配器:流出指定文本并返回该文本的 LLMResponse。"""

    def __init__(self, name, text):
        self._name = name
        self._text = text

    async def chat(self, messages, model, tools=None, temperature=0.7,
                   max_tokens=4096, **kwargs):
        from core.multi_llm_router import LLMResponse
        sink = kwargs.get("stream")
        if sink is not None:
            sink.feed(self._text)
        return LLMResponse(content=self._text, provider=self._name, model=model,
                           input_tokens=1, output_tokens=len(self._text),
                           latency_ms=1.0)


class TestCascadeResetSemantics:
    @pytest.mark.asyncio
    async def test_escalation_resets_streamed_draft(self):
        from core.multi_llm_router import MultiLLMRouter, TaskType

        r = MultiLLMRouter.__new__(MultiLLMRouter)
        r.providers = {}
        r.call_history = []
        r.adapters = {
            "cheap": _StageAdapter("cheap", "短"),
            "strong": _StageAdapter("strong", "这是一个足够长的合格答案。"),
        }
        r._capability_floor_for_complexity = lambda c: 0
        r._cost_ordered_ladder = lambda *a, **k: [("cheap", "m1"), ("strong", "m2")]
        r._record_call = lambda *a, **k: None

        got, resets = [], []
        sink = _mk_sink(got, resets)
        resp = await r.chat_cascade(
            [{"role": "user", "content": "q"}], TaskType.GENERAL,
            judge=lambda resp_: len(resp_.content) > 5,
            complexity=0.1, stream=sink,
        )
        assert resp.provider == "strong"
        assert len(resets) == 1                      # 换档前作废了便宜档草稿
        assert got == ["短", "这是一个足够长的合格答案。"]  # 两代内容都流过

    @pytest.mark.asyncio
    async def test_react_loop_passes_context_sink_and_resets_between_rounds(self):
        """_react_loop 从请求上下文取 sink → 传给 chat_with_tools;
        工具轮流出过内容则作废,最终答案轮直通。"""
        from core.llm_stream import TokenStream, use_stream
        from core.multi_llm_router import LLMResponse
        from core.openclawd import OpenClawd

        calls = []

        class _FakeRouter:
            async def chat_with_tools(self, messages, tools=None, task_type=None,
                                      max_tokens=4096, **kwargs):
                sink = kwargs.get("stream")
                calls.append(sink)
                if len(calls) == 1:
                    if sink is not None:
                        sink.feed("我查一下…")  # 过场话
                    return LLMResponse(
                        content="", provider="p", model="m",
                        input_tokens=1, output_tokens=1, latency_ms=1.0,
                        tool_calls=[{"id": "c1", "type": "function",
                                     "function": {"name": "t", "arguments": "{}"}}],
                    )
                if sink is not None:
                    sink.feed("最终答案。")
                return LLMResponse(content="最终答案。", provider="p", model="m",
                                   input_tokens=1, output_tokens=1, latency_ms=1.0)

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._get_router = lambda: _FakeRouter()

        async def _fake_dispatch(name, args):
            return {"success": True, "result": "ok"}

        clawd._dispatch_tool_call = _fake_dispatch

        got, resets = [], []
        sink = TokenStream(on_delta=got.append, on_reset=lambda: resets.append(1))

        async def _run():
            with use_stream(sink):
                return await clawd._react_loop(
                    [{"role": "user", "content": "q"}],
                    tools=[{"type": "function", "function": {"name": "t"}}],
                )

        result = await _run()
        assert result["response"] == "最终答案。"
        assert calls == [sink, sink]        # 两轮都拿到了上下文里的 sink
        assert len(resets) == 1             # 工具轮过场话被作废了一次
        assert got == ["我查一下…", "最终答案。"]


# ---------------------------------------------------------------------------
# 6. /api/v1/chat/stream 真流式表面
# ---------------------------------------------------------------------------

def _collect_frames(resp_iter):
    frames = []
    for line in resp_iter:
        if line and line.startswith("data: "):
            frames.append(json.loads(line[6:]))
    return frames


def _mk_app():
    from fastapi import FastAPI
    import core.routes.chat as chat_mod
    app = FastAPI()
    app.include_router(chat_mod.create_router(service_manager=None, config=None))
    return app


class TestChatStreamTrueStreaming:
    def test_true_deltas_forwarded_and_done_reconciles(self, monkeypatch):
        """runtime 边生成边 feed → SSE 真增量帧;done.response 为权威全文。"""
        monkeypatch.setenv("GALAXY_SPEAK", "0")  # 测试环境不发声
        from fastapi.testclient import TestClient
        import core.desktop_presence_runtime as dpr

        class _StreamingRuntime:
            async def handle_request(self, *a, **k):
                from core.llm_stream import current_stream
                sink = current_stream()
                assert sink is not None, "chat_stream 必须在请求上下文里挂 sink"
                sink.feed("你")
                await asyncio.sleep(0)
                sink.feed("好。")
                return {"success": True, "response": "你好。", "intent": "chat",
                        "metadata": {"session_id": "s1", "model": "m1"}}

        with patch.object(dpr, "get_desktop_presence_runtime",
                          lambda: _StreamingRuntime()):
            client = TestClient(_mk_app())
            with client.stream("POST", "/api/v1/chat/stream",
                               json={"message": "hi", "session_id": "s1"}) as r:
                frames = _collect_frames(r.iter_lines())

        deltas = [f["text"] for f in frames if f["type"] == "delta"]
        assert deltas == ["你", "好。"], f"应为真增量逐帧转发; got {deltas}"
        done = next(f for f in frames if f["type"] == "done")
        assert done["response"] == "你好。" and done["success"] is True
        phases = [f["phase"] for f in frames if f["type"] == "phase"]
        assert phases[0] == "liminal" and "manifest" in phases and phases[-1] == "silent"

    def test_reset_frame_emitted_on_sink_reset(self, monkeypatch):
        monkeypatch.setenv("GALAXY_SPEAK", "0")
        from fastapi.testclient import TestClient
        import core.desktop_presence_runtime as dpr

        class _ResettingRuntime:
            async def handle_request(self, *a, **k):
                from core.llm_stream import current_stream
                sink = current_stream()
                sink.feed("便宜档草稿")
                sink.reset()
                sink.feed("升级后的答案。")
                return {"success": True, "response": "升级后的答案。",
                        "intent": "chat", "metadata": {"session_id": "s"}}

        with patch.object(dpr, "get_desktop_presence_runtime",
                          lambda: _ResettingRuntime()):
            client = TestClient(_mk_app())
            with client.stream("POST", "/api/v1/chat/stream",
                               json={"message": "hi"}) as r:
                frames = _collect_frames(r.iter_lines())

        types = [f["type"] for f in frames]
        assert "reset" in types, f"作废草稿应发 reset 帧; got {types}"
        i_reset = types.index("reset")
        after = [f["text"] for f in frames[i_reset:] if f["type"] == "delta"]
        assert after == ["升级后的答案。"]

    def test_zero_delta_falls_back_to_chunked_pseudo_stream(self, monkeypatch):
        """一个增量都没流出(非流式适配器)→ 退回逐字假流式,前端观感不变。"""
        monkeypatch.setenv("GALAXY_SPEAK", "0")
        from fastapi.testclient import TestClient
        import core.desktop_presence_runtime as dpr

        class _AtomicRuntime:
            async def handle_request(self, *a, **k):
                return {"success": True, "response": "整段一次到的答案",
                        "intent": "chat", "metadata": {"session_id": "s"}}

        with patch.object(dpr, "get_desktop_presence_runtime",
                          lambda: _AtomicRuntime()):
            client = TestClient(_mk_app())
            with client.stream("POST", "/api/v1/chat/stream",
                               json={"message": "hi"}) as r:
                frames = _collect_frames(r.iter_lines())

        deltas = [f["text"] for f in frames if f["type"] == "delta"]
        assert "".join(deltas) == "整段一次到的答案"
        assert len(deltas) > 1, "假流式兜底应逐字分帧"
        done = next(f for f in frames if f["type"] == "done")
        assert done["response"] == "整段一次到的答案"


# ---------------------------------------------------------------------------
# 7. 防双读:增量朗读接管后,集中式 speak_response 必须闭嘴
# ---------------------------------------------------------------------------

class TestNoDoubleSpeak:
    @pytest.mark.asyncio
    async def test_suppress_final_speak_in_context(self, monkeypatch):
        import core.speech_output as so

        spoken = []

        class _FakeEngine:
            async def synthesize_and_play(self, text):
                spoken.append(text)

        monkeypatch.setattr(so, "_get_engine", lambda: _FakeEngine())
        monkeypatch.setattr(so, "speak_enabled", lambda: True)
        monkeypatch.setattr(so, "_last_text", "")
        monkeypatch.setattr(so, "_last_ts", 0.0)
        monkeypatch.setenv("GALAXY_TTS_STREAMING", "0")

        async def _request_like():
            so.suppress_final_speak_in_context()
            so.speak_response("这句不该被念", source="chat")

        await asyncio.get_running_loop().create_task(_request_like())
        await asyncio.sleep(0.05)
        assert spoken == [], "增量朗读接管的请求里,集中式朗读必须被抑制"

        # 抑制只作用于那条请求上下文:新任务不受影响。
        async def _normal_request():
            so.speak_response("这句正常念", source="voice")

        await asyncio.get_running_loop().create_task(_normal_request())
        await asyncio.sleep(0.05)
        assert spoken == ["这句正常念"]
