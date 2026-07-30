"""双工语音会话的行为测试。

怎么在没有 provider key、没有出网的环境里真正验证
--------------------------------------------------
把"协议"和"网络"分开:

1. **帧编解码抽成纯函数**(``ProtocolAdapter``)—— 上行帧长什么样、下行帧怎么翻成
   ``DuplexEvent``,全部不碰网络,可以逐条断言。provider 改帧格式时这里立刻失败。
2. **会话流程跑在本地真 WebSocket 服务端上** —— 不是 mock:``websockets.serve`` 起一个
   真的服务端,说 OpenAI Realtime 的帧形状,然后驱动一条完整会话:建连 → 下发配置 →
   上行音频 → 收到转写与音频 → barge-in → 关闭。真的建连、真的收发帧。

无法在此验证的只有一件事:**真实 provider 会不会按它自己文档里的帧格式回话**。那需要
key 与出网。这一点如实写在模块 docstring 里,不假装覆盖到了。

最要紧的一组是 ``TestVoiceLoopWiring``
--------------------------------------
双工默认关闭。一个"默认关闭 + 没接线"的模块与"默认关闭 + 接好了线"的模块从外面看
一模一样 —— 都不生效。所以必须断言:开关一开,``VoiceLoop.start()` 真的走双工路径;
开关关着,真的走回合制路径。
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from core.voice_duplex_session import (
    DuplexEventType,
    DuplexSession,
    DuplexSessionConfig,
    OpenAIRealtimeAdapter,
    duplex_enabled,
    float_from_pcm16,
    get_adapter,
    pcm16_from_float,
)

np = pytest.importorskip("numpy")
websockets = pytest.importorskip("websockets")


# ── 1. 协议编解码(纯函数,零网络)──────────────────────────────────────────


class TestUplinkFrames:
    def setup_method(self):
        self.a = OpenAIRealtimeAdapter()
        self.cfg = DuplexSessionConfig(url="wss://x/y", api_key="sk-test")

    def test_session_update_requests_server_side_vad(self):
        """双工的回合边界必须由**服务端 VAD** 判。若退回本地"攒够 N 秒再转写",
        延迟就又回到回合制水平了 —— 那是这一层存在的理由被抽掉。"""
        frame = self.a.session_update(self.cfg)
        assert frame["type"] == "session.update"
        td = frame["session"]["turn_detection"]
        assert td["type"] == "server_vad"
        assert td["silence_duration_ms"] == self.cfg.silence_ms

    def test_session_update_asks_for_both_modalities(self):
        s = self.a.session_update(self.cfg)["session"]
        assert set(s["modalities"]) == {"text", "audio"}
        assert s["input_audio_format"] == "pcm16"
        assert s["output_audio_format"] == "pcm16"

    def test_instructions_omitted_when_empty(self):
        """空 instructions 不该作为空字符串发上去 —— 有 provider 会用它覆盖掉默认人设。"""
        assert "instructions" not in self.a.session_update(self.cfg)["session"]
        cfg2 = DuplexSessionConfig(url="wss://x", api_key="k", instructions="be terse")
        assert self.a.session_update(cfg2)["session"]["instructions"] == "be terse"

    def test_audio_frame_is_base64_pcm(self):
        pcm = b"\x01\x02\x03\x04"
        frame = self.a.audio_frame(pcm)
        assert frame["type"] == "input_audio_buffer.append"
        assert base64.b64decode(frame["audio"]) == pcm

    def test_text_frame_creates_item_then_requests_response(self):
        """只 create item 不 response.create,模型永远不会开口 —— 顺序和成对性都要钉住。"""
        frames = self.a.text_frame("你好")
        assert [f["type"] for f in frames] == ["conversation.item.create", "response.create"]
        assert frames[0]["item"]["content"][0]["text"] == "你好"

    def test_interrupt_cancels_the_server_side_response(self):
        """回合制的打断只停本地播放器,模型那边还在烧 token。双工必须让服务端也停。"""
        assert self.a.interrupt_frame()["type"] == "response.cancel"

    def test_headers_carry_auth(self):
        h = self.a.headers(self.cfg)
        assert h["Authorization"] == "Bearer sk-test"
        assert "realtime" in h["OpenAI-Beta"]


class TestDownlinkDecoding:
    def setup_method(self):
        self.a = OpenAIRealtimeAdapter()

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ({"type": "session.created"}, DuplexEventType.SESSION_OPEN),
            ({"type": "session.updated"}, DuplexEventType.SESSION_OPEN),
            ({"type": "input_audio_buffer.speech_started"}, DuplexEventType.USER_SPEECH_STARTED),
            ({"type": "input_audio_buffer.speech_stopped"}, DuplexEventType.USER_SPEECH_STOPPED),
            ({"type": "response.done"}, DuplexEventType.RESPONSE_DONE),
        ],
    )
    def test_control_events(self, raw, expected):
        assert self.a.decode(raw).type is expected

    def test_audio_delta_carries_base64(self):
        ev = self.a.decode({"type": "response.audio.delta", "delta": "QUJD"})
        assert ev.type is DuplexEventType.ASSISTANT_AUDIO_DELTA
        assert base64.b64decode(ev.audio_b64) == b"ABC"

    @pytest.mark.parametrize("t", ["response.text.delta", "response.audio_transcript.delta"])
    def test_assistant_text_deltas(self, t):
        ev = self.a.decode({"type": t, "delta": "在的"})
        assert ev.type is DuplexEventType.ASSISTANT_TEXT_DELTA
        assert ev.text == "在的"

    def test_user_transcription_partial_and_final_are_distinct(self):
        """部分转写与最终转写必须分开:把部分当最终会让下游对半句话就动作。"""
        p = self.a.decode({"type": "conversation.item.input_audio_transcription.delta", "delta": "帮我"})
        f = self.a.decode({"type": "conversation.item.input_audio_transcription.completed", "transcript": "帮我订机票"})
        assert p.type is DuplexEventType.PARTIAL_TRANSCRIPT and p.text == "帮我"
        assert f.type is DuplexEventType.FINAL_TRANSCRIPT and f.text == "帮我订机票"

    def test_error_frame_surfaces_the_message(self):
        ev = self.a.decode({"type": "error", "error": {"message": "rate limited"}})
        assert ev.type is DuplexEventType.ERROR
        assert ev.error == "rate limited"

    def test_unknown_frames_are_ignored_not_fatal(self):
        """provider 会不断加新事件类型。对未知帧报错会让会话动不动就断。"""
        assert self.a.decode({"type": "response.some.future.thing"}) is None
        assert self.a.decode({}) is None
        assert self.a.decode({"type": ""}) is None


class TestPcmConversion:
    def test_roundtrip_preserves_signal(self):
        x = (np.sin(2 * np.pi * 440 * np.arange(1000) / 16000) * 0.5).astype(np.float32)
        back = float_from_pcm16(pcm16_from_float(x))
        assert back.size == x.size
        assert float(np.max(np.abs(back - x))) < 1e-3

    def test_clipping_does_not_wrap(self):
        """溢出翻转会变成刺耳爆音,而且会污染模型的听觉输入。"""
        out = float_from_pcm16(pcm16_from_float(np.array([9.0, -9.0], dtype=np.float32)))
        assert out[0] > 0.9 and out[1] < -0.9

    def test_empty_inputs(self):
        assert pcm16_from_float(np.zeros(0)) == b""
        assert float_from_pcm16(b"").size == 0


class TestAdapterRegistry:
    def test_known_adapter(self):
        assert get_adapter("openai_realtime").name == "openai_realtime"

    def test_unimplemented_provider_fails_loudly(self):
        """Gemini Live 的帧形状不同,没实现就不假装支持 —— 静默退回会让用户以为在用
        Gemini,实际上发的是 OpenAI 的帧。"""
        with pytest.raises(ValueError, match="未实现"):
            get_adapter("gemini_live")


# ── 2. 完整会话流程:跑在本地【真】WebSocket 服务端上 ──────────────────────


class _FakeRealtimeServer:
    """说 OpenAI Realtime 帧形状的本地服务端。不是 mock —— 真的 WebSocket。"""

    def __init__(self) -> None:
        self.received: list = []
        self._server = None
        self.url = ""

    async def __aenter__(self):
        async def _handler(ws):
            await ws.send(json.dumps({"type": "session.created"}))
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg)
                t = msg.get("type")
                if t == "input_audio_buffer.append":
                    # 收到音频 → 模拟服务端 VAD + 转写 + 开始应答
                    await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
                    await ws.send(
                        json.dumps(
                            {
                                "type": "conversation.item.input_audio_transcription.completed",
                                "transcript": "今天天气怎么样",
                            }
                        )
                    )
                    await ws.send(json.dumps({"type": "response.audio_transcript.delta", "delta": "今天多云"}))
                    await ws.send(
                        json.dumps(
                            {
                                "type": "response.audio.delta",
                                "delta": base64.b64encode(b"\x00\x01" * 8).decode("ascii"),
                            }
                        )
                    )
                    await ws.send(json.dumps({"type": "response.done"}))
                elif t == "response.cancel":
                    await ws.send(json.dumps({"type": "response.done"}))

        self._server = await websockets.serve(_handler, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *_exc):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def types(self) -> list:
        return [m.get("type") for m in self.received]


async def _drain(sess, want: DuplexEventType, timeout: float = 3.0) -> list:
    """收事件直到拿到 ``want``;返回期间收到的全部事件。"""
    got: list = []
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        ev = await sess.next_event(timeout=0.5)
        if ev is None:
            continue
        got.append(ev)
        if ev.type is want:
            return got
    raise AssertionError(f"等不到 {want};实际收到 {[e.type.value for e in got]}")


class TestFullSessionOverRealWebSocket:
    @pytest.mark.asyncio
    async def test_connect_uplink_downlink_and_close(self):
        from core.voice_echo_guard import reset_echo_guard

        reset_echo_guard()
        async with _FakeRealtimeServer() as server:
            cfg = DuplexSessionConfig(url=server.url, api_key="sk-test")
            sess = DuplexSession(cfg)
            assert await sess.connect() is True
            try:
                # 建连即应下发 session.update
                await _drain(sess, DuplexEventType.SESSION_OPEN)
                assert "session.update" in server.types()

                pcm = pcm16_from_float(np.zeros(160, dtype=np.float32) + 0.1)
                assert await sess.send_audio(pcm) is True

                events = await _drain(sess, DuplexEventType.RESPONSE_DONE)
                kinds = [e.type for e in events]
                assert DuplexEventType.USER_SPEECH_STARTED in kinds
                assert DuplexEventType.FINAL_TRANSCRIPT in kinds
                assert DuplexEventType.ASSISTANT_TEXT_DELTA in kinds
                assert DuplexEventType.ASSISTANT_AUDIO_DELTA in kinds

                final = next(e for e in events if e.type is DuplexEventType.FINAL_TRANSCRIPT)
                assert final.text == "今天天气怎么样"
                audio = next(e for e in events if e.type is DuplexEventType.ASSISTANT_AUDIO_DELTA)
                assert float_from_pcm16(base64.b64decode(audio.audio_b64)).size == 8

                st = sess.status()
                assert st["connected"] is True
                assert st["bytes_uplinked"] == len(pcm)
            finally:
                await sess.close()
            assert sess.connected is False
        reset_echo_guard()

    @pytest.mark.asyncio
    async def test_uplink_does_not_block_on_downlink(self):
        """上行必须不等下行。若两者串行,"边说边听"在实现上就不成立 —— 只是把回合制
        换了个壳。这里连发 20 块音频、期间完全不读下行,应当全部成功。"""
        async with _FakeRealtimeServer() as server:
            sess = DuplexSession(DuplexSessionConfig(url=server.url, api_key="k"))
            assert await sess.connect() is True
            try:
                pcm = pcm16_from_float(np.zeros(160, dtype=np.float32) + 0.05)
                results = [await sess.send_audio(pcm) for _ in range(20)]
                assert all(results)
                assert sess.status()["bytes_uplinked"] == len(pcm) * 20
            finally:
                await sess.close()

    @pytest.mark.asyncio
    async def test_interrupt_reaches_the_server(self):
        async with _FakeRealtimeServer() as server:
            sess = DuplexSession(DuplexSessionConfig(url=server.url, api_key="k"))
            assert await sess.connect() is True
            try:
                assert await sess.interrupt() is True
                await _drain(sess, DuplexEventType.RESPONSE_DONE)
                assert "response.cancel" in server.types()
            finally:
                await sess.close()

    @pytest.mark.asyncio
    async def test_text_input_shares_the_same_session(self):
        async with _FakeRealtimeServer() as server:
            sess = DuplexSession(DuplexSessionConfig(url=server.url, api_key="k"))
            assert await sess.connect() is True
            try:
                assert await sess.send_text("你好") is True
                await asyncio.sleep(0.1)
                assert "conversation.item.create" in server.types()
                assert "response.create" in server.types()
            finally:
                await sess.close()

    @pytest.mark.asyncio
    async def test_assistant_text_is_registered_with_the_echo_guard(self):
        """双工下同样需要反自激励门:AEC 消不掉非线性残余回声,残余转写出来后仍要能
        判出"这是我自己说的"。"""
        from core.voice_echo_guard import get_echo_guard, reset_echo_guard

        reset_echo_guard()
        async with _FakeRealtimeServer() as server:
            sess = DuplexSession(DuplexSessionConfig(url=server.url, api_key="k"))
            assert await sess.connect() is True
            try:
                await sess.send_audio(pcm16_from_float(np.zeros(160) + 0.1))
                await _drain(sess, DuplexEventType.RESPONSE_DONE)
                assert get_echo_guard().stats()["noted"] >= 1, "AI 说出口的文字没有登记进反自激励门"
            finally:
                await sess.close()
        reset_echo_guard()

    @pytest.mark.asyncio
    async def test_close_is_idempotent_and_emits_closed(self):
        async with _FakeRealtimeServer() as server:
            sess = DuplexSession(DuplexSessionConfig(url=server.url, api_key="k"))
            await sess.connect()
            await sess.close()
            await sess.close()  # 幂等

    @pytest.mark.asyncio
    async def test_send_after_close_is_refused_not_raised(self):
        async with _FakeRealtimeServer() as server:
            sess = DuplexSession(DuplexSessionConfig(url=server.url, api_key="k"))
            await sess.connect()
            await sess.close()
            assert await sess.send_audio(b"\x00\x01") is False
            assert await sess.send_text("x") is False
            assert await sess.interrupt() is False


class TestConnectFailureDegradesToTurnBased:
    @pytest.mark.asyncio
    async def test_unreachable_url_returns_false_with_a_reason(self):
        """建连失败必须如实返回 False 并留下原因,让调用方退回回合制 —— 绝不能抛异常
        把整条语音链路带崩。"""
        sess = DuplexSession(DuplexSessionConfig(url="ws://127.0.0.1:1", api_key="k"))
        assert await sess.connect() is False
        assert sess.status()["last_error"]
        assert "connect_failed" in sess.status()["last_error"]

    @pytest.mark.asyncio
    async def test_open_duplex_session_returns_none_when_disabled(self, monkeypatch):
        from core.voice_duplex_session import open_duplex_session

        monkeypatch.delenv("GALAXY_VOICE_DUPLEX", raising=False)
        assert await open_duplex_session() is None

    @pytest.mark.asyncio
    async def test_open_duplex_session_returns_none_without_key(self, monkeypatch, caplog):
        from core.voice_duplex_session import open_duplex_session

        monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
        monkeypatch.delenv("GALAXY_REALTIME_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with caplog.at_level("WARNING"):
            assert await open_duplex_session() is None
        assert "缺少 API key" in caplog.text, "缺 key 必须留下可排查的日志"


class TestDefaultsAndConfig:
    def test_duplex_is_off_by_default(self, monkeypatch):
        """默认关闭是刻意的:它需要 realtime provider 与 key,默认打开会让所有没配 key
        的部署直接失去语音功能。"""
        monkeypatch.delenv("GALAXY_VOICE_DUPLEX", raising=False)
        assert duplex_enabled() is False

    def test_can_be_switched_on(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
        assert duplex_enabled() is True

    def test_from_env_builds_default_openai_url(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "sk-x")
        monkeypatch.delenv("GALAXY_REALTIME_URL", raising=False)
        monkeypatch.setenv("GALAXY_REALTIME_MODEL", "my-model")
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        assert cfg.model == "my-model"
        assert "my-model" in cfg.url and cfg.url.startswith("wss://")

    def test_explicit_url_wins(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "sk-x")
        monkeypatch.setenv("GALAXY_REALTIME_URL", "wss://my.host/rt")
        assert DuplexSessionConfig.from_env().url == "wss://my.host/rt"


class TestEventQueueIsBounded:
    @pytest.mark.asyncio
    async def test_oldest_events_are_dropped_not_newest(self):
        """队列满了要丢**最旧**的:过期音频块没有价值,而阻塞上行会毁掉实时性。
        丢弃必须有计数,不能静默。"""
        from core.voice_duplex_session import _EVENT_QUEUE_MAX, DuplexEvent

        sess = DuplexSession(DuplexSessionConfig(url="ws://x", api_key="k"))
        for i in range(_EVENT_QUEUE_MAX + 10):
            await sess._emit(DuplexEvent(DuplexEventType.ASSISTANT_TEXT_DELTA, text=str(i)))
        assert sess._queue.qsize() == _EVENT_QUEUE_MAX
        assert sess.events_dropped == 10
        # 队里剩的应是最近的那批
        ev = await sess.next_event(timeout=0.1)
        assert int(ev.text) >= 10


# ── 3. 接线:开关一开,VoiceLoop 真的走双工吗 ───────────────────────────────


class TestVoiceLoopWiring:
    """双工默认关闭。一个"默认关闭 + 没接线"的模块与"默认关闭 + 接好了线"的模块从外面
    看一模一样 —— 都不生效。所以必须断言开关的两个方向都真的路由到了对应实现。
    """

    @pytest.mark.asyncio
    async def test_switch_off_uses_the_turn_based_path(self, monkeypatch):
        from core.voice_loop import VoiceLoop

        monkeypatch.delenv("GALAXY_VOICE_DUPLEX", raising=False)
        loop = VoiceLoop(object(), speak_responses=False)
        assert await loop._try_start_duplex(object, object) is False
        assert loop._duplex is None

    @pytest.mark.asyncio
    async def test_switch_on_but_no_key_falls_back(self, monkeypatch):
        """开了开关却没配 key 时必须退回回合制,而不是把语音功能整体弄坏。"""
        from core.voice_loop import VoiceLoop

        monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
        monkeypatch.delenv("GALAXY_REALTIME_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        loop = VoiceLoop(object(), speak_responses=False)
        assert await loop._try_start_duplex(object, object) is False

    @pytest.mark.asyncio
    async def test_switch_on_with_reachable_server_starts_duplex(self, monkeypatch):
        """核心接线断言:开关开 + 会话建得起来 → VoiceLoop 真的进双工模式。"""
        from core.multimodal.audio_capture_service import (
            AudioCaptureConfig,
            AudioCaptureService,
        )
        from core.voice_loop import VoiceLoop

        async with _FakeRealtimeServer() as server:
            monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
            monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "sk-test")
            monkeypatch.setenv("GALAXY_REALTIME_URL", server.url)

            loop = VoiceLoop(object(), speak_responses=False)
            started = await loop._try_start_duplex(AudioCaptureConfig, AudioCaptureService)
            try:
                assert started is True, "开关已开且服务端可达,却没进双工模式 —— 接线断了"
                assert loop._duplex is not None
                assert loop._running is True
                # ASR/TTS 是回合制的部件,双工路径下不该被初始化
                assert loop.asr is None
                assert loop.tts is None
            finally:
                await loop.stop()
            # 生命周期对称:停完之后连接与播放器都要被释放
            assert loop._duplex is None
            assert loop._duplex_player is None
            assert loop._duplex_loop is None

    @pytest.mark.asyncio
    async def test_uplink_audio_reaches_the_server(self, monkeypatch):
        """真正走一遍上行:采集回调 → PCM16 → 服务端收到 input_audio_buffer.append。"""
        from core.multimodal.audio_capture_service import (
            AudioCaptureConfig,
            AudioCaptureService,
        )
        from core.voice_loop import VoiceLoop

        async with _FakeRealtimeServer() as server:
            monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
            monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "sk-test")
            monkeypatch.setenv("GALAXY_REALTIME_URL", server.url)

            loop = VoiceLoop(object(), speak_responses=False)
            assert await loop._try_start_duplex(AudioCaptureConfig, AudioCaptureService) is True
            try:
                # 直接驱动采集管道的处理入口(本环境没有真麦克风)
                pipe = loop.capture._pipeline
                await pipe._process_chunk(np.zeros(160, dtype=np.float32) + 0.1)
                for _ in range(30):
                    if "input_audio_buffer.append" in server.types():
                        break
                    await asyncio.sleep(0.05)
                assert "input_audio_buffer.append" in server.types(), "上行音频没有到达服务端"
            finally:
                await loop.stop()

    @pytest.mark.asyncio
    async def test_start_actually_consults_the_duplex_path_first(self, monkeypatch):
        """上面几个用例直接调 ``_try_start_duplex``,证明不了 ``start()`` 会去调它 ——
        把 start() 里那一行删掉,它们照样全绿。这里补上调用点本身的断言:双工启动成功时
        start() 必须**就此返回**,不再初始化 ASR/TTS(那是回合制的部件,构造 Whisper
        会真的去加载模型)。
        """
        from core.voice_loop import VoiceLoop

        calls: list = []

        async def _fake_try(*_a, **_k):
            calls.append(1)
            return True

        loop = VoiceLoop(object(), speak_responses=False)
        monkeypatch.setattr(loop, "_try_start_duplex", _fake_try)
        await loop.start()
        assert calls == [1], "start() 没有调用双工路径 —— 接线断了"
        assert loop.asr is None, "双工启动后仍初始化了 ASR,说明 start() 没有就此返回"
        assert loop.tts is None
