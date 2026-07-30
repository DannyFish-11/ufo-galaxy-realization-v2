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
        """未实现的 provider 必须显式抛错,不能静默退回某个默认实现 —— 那会让用户
        以为在用 A、实际发的是 B 的帧。

        (这条原先拿 ``gemini_live`` 当"未实现"的例子;它现在已经实现了,故换成一个
        真正未实现的名字。)
        """
        with pytest.raises(ValueError, match="未实现"):
            get_adapter("anthropic_realtime")


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


# ── 4. 下行播放器:绝不阻塞事件循环 ────────────────────────────────────────


class TestPcmPlayerNeverBlocks:
    """为什么单独立一组:``OutputStream.write()`` 按 sounddevice 的契约**会阻塞**到帧写完
    为止,而 ``play()`` 是从 ``_duplex_downlink`` 里调的、跑在事件循环上 —— 一阻塞,同一个
    循环上的**上行**也跟着停,等于用一个"实时"播放器把双工性质亲手毁掉,退化成半双工。
    所以实现改成回调驱动:``play()`` 只往有界缓冲追加,纯内存操作。
    """

    def test_play_is_pure_buffer_append_no_blocking_write(self):
        """实现里不该出现 ``stream.write(``。这是白盒断言,但它守的是一条从外面测不出来
        的性质(本环境没有音频设备,阻塞与否无法直接观测)。"""
        import inspect

        from core.voice_duplex_session import PcmPlayer

        src = inspect.getsource(PcmPlayer)
        # 只看真正的调用形式,不看 docstring 里对 stream.write() 的说明性提及
        assert "self._stream.write(" not in src, "播放器又用回了阻塞式 write —— 会卡住事件循环"
        assert "callback=_cb" in src, "播放器应是回调驱动"

    def test_play_without_a_device_counts_drops_and_returns_false(self):
        from core.voice_duplex_session import PcmPlayer

        p = PcmPlayer(sample_rate=16000)
        assert p.start() is False  # 本环境没有 sounddevice
        assert p.play(b"\x00\x01" * 100) is False
        st = p.status()
        assert st["available"] is False
        assert st["unavailable_reason"]
        assert st["blocks_dropped"] == 1

    def test_empty_block_is_a_noop(self):
        from core.voice_duplex_session import PcmPlayer

        p = PcmPlayer()
        assert p.play(b"") is False
        assert p.status()["blocks_dropped"] == 0

    def test_stop_is_safe_without_start(self):
        from core.voice_duplex_session import PcmPlayer

        PcmPlayer().stop()

    def test_buffer_is_bounded_and_drops_oldest(self, monkeypatch):
        """生产快于消费时必须丢**最旧**的,而不是让 play() 等下去。用一个假 stream 绕过
        "本环境没有音频设备",单独检验缓冲策略。"""
        from core.voice_duplex_session import _PLAYER_BUFFER_SEC, PcmPlayer

        p = PcmPlayer(sample_rate=16000)
        p._stream = object()  # 假装设备可用
        p._np = np
        p._buf = np.zeros(0, dtype=np.float32)

        one_sec = pcm16_from_float(np.zeros(16000, dtype=np.float32) + 0.1)
        for _ in range(int(_PLAYER_BUFFER_SEC) + 3):
            assert p.play(one_sec) is True
        assert p.status()["buffered_samples"] <= int(_PLAYER_BUFFER_SEC * 16000)
        assert p.status()["blocks_dropped"] > 0, "超上限时应有丢弃计数,不能静默"


class TestUnexpectedDisconnectIsNotSilent:
    """服务端**正常**关闭连接时,``async for`` 会安静地结束、不抛异常。若那里什么都不做,
    后果完全静默:上行 ``send_audio`` 从此每次返回 False(没人看返回值),用户的声音再也
    传不上去;而下行消费方还在 await 一个永远不会再有事件的队列上,任务就此挂死。
    症状是"助手突然不理人了",日志里一点线索都没有。
    """

    @staticmethod
    async def _session_that_gets_closed():
        async def handler(ws):
            await ws.send(json.dumps({"type": "session.created"}))
            await asyncio.sleep(0.05)
            await ws.close()  # 服务端正常关闭

        server = await websockets.serve(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        sess = DuplexSession(DuplexSessionConfig(url=f"ws://127.0.0.1:{port}", api_key="k"))
        assert await sess.connect() is True
        return sess, server

    @pytest.mark.asyncio
    async def test_consumer_is_released_instead_of_hanging(self):
        sess, server = await self._session_that_gets_closed()
        seen: list = []

        async def _consume():
            async for ev in sess.events():
                seen.append(ev.type)

        task = asyncio.ensure_future(_consume())
        try:
            # 不补发 SESSION_CLOSED 的话这里会超时 —— 消费方挂死
            await asyncio.wait_for(task, timeout=3.0)
        except asyncio.TimeoutError:
            task.cancel()
            raise AssertionError("下行消费方挂死:断连后没有收到 SESSION_CLOSED")
        finally:
            server.close()
            await server.wait_closed()
        assert DuplexEventType.SESSION_CLOSED in seen

    @pytest.mark.asyncio
    async def test_disconnect_is_logged_and_recorded(self, caplog):
        sess, server = await self._session_that_gets_closed()
        try:
            with caplog.at_level("WARNING"):
                for _ in range(30):
                    if not sess.connected:
                        break
                    await asyncio.sleep(0.05)
            assert sess.connected is False
            assert sess.status()["last_error"], "断连必须留下可排查的痕迹"
            assert "已断开" in caplog.text, "断连必须升 WARNING,不能静默"
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_uplink_after_disconnect_reports_failure(self):
        sess, server = await self._session_that_gets_closed()
        try:
            for _ in range(30):
                if not sess.connected:
                    break
                await asyncio.sleep(0.05)
            assert await sess.send_audio(b"\x00\x01") is False
        finally:
            server.close()
            await server.wait_closed()


# ── 5. ducking(压低音量继续说)────────────────────────────────────────────


class TestDucking:
    """把 PR #1541 里"ducking 做不到"那句话纠正过来。

    那句话对**旧的文件式 TTS 路径**成立(edge-tts 的 volume 是合成时参数,``_play_audio``
    只是播一个文件,``stop()`` 只能整段掐断)。但双工路径的 ``PcmPlayer`` 是本仓库自己写的
    回调驱动缓冲 —— 音频线程来取数时乘一个增益即可,压音完全做得到。结论下得过宽了。

    压音的价值不只是"温和":它是**非承诺性**的。服务端 VAD 只能告诉你"有人在出声",
    分不出抢话与积极倾听;先压低、等最终转写到了再决定,比一听见声音就取消整个回复正确。
    """

    def _player(self):
        """带假 stream 的播放器(本环境无音频设备),驱动**真正的** ``_fill``。"""
        from core.voice_duplex_session import PcmPlayer

        p = PcmPlayer(sample_rate=16000)
        p._stream = object()
        p._np = np
        p._buf = np.zeros(0, dtype=np.float32)
        return p

    def _render(self, player, blocks, block=160, duck_at=None, unduck_at=None):
        out = []
        for i in range(blocks):
            if duck_at is not None and i == duck_at:
                player.duck()
            if unduck_at is not None and i == unduck_at:
                player.unduck()
            buf = np.zeros((block, 1), dtype=np.float32)
            player._fill(buf, block)
            out.append(buf[:, 0].copy())
        return np.concatenate(out)

    def test_duck_lowers_the_volume(self):
        from core.voice_duplex_session import duck_gain

        p = self._player()
        p.play(pcm16_from_float(np.ones(16000, dtype=np.float32)))
        sig = self._render(p, 40, duck_at=5)
        tail = sig[25 * 160 :]  # 爬坡早已结束
        assert abs(float(np.abs(tail).mean()) - duck_gain()) < 0.02

    def test_unduck_restores_full_volume(self):
        p = self._player()
        p.play(pcm16_from_float(np.ones(16000, dtype=np.float32)))
        sig = self._render(p, 60, duck_at=5, unduck_at=30)
        tail = sig[50 * 160 :]
        assert abs(float(np.abs(tail).mean()) - 1.0) < 0.02

    def test_gain_change_is_ramped_not_stepped(self):
        """幅度突变在听感上就是"啪"的一声爆音。瞬切时最大单样本跳变约 0.75;
        50ms 爬坡下应当小两个数量级。"""
        p = self._player()
        p.play(pcm16_from_float(np.ones(16000, dtype=np.float32)))
        sig = self._render(p, 60, duck_at=10, unduck_at=40)
        assert float(np.abs(np.diff(sig)).max()) < 0.02

    def test_ramp_completes_within_the_configured_time(self):
        from core.voice_duplex_session import _DUCK_RAMP_MS, duck_gain

        p = self._player()
        p.play(pcm16_from_float(np.ones(16000, dtype=np.float32)))
        # 爬坡时长内应基本到位(留一格余量)
        blocks = int(_DUCK_RAMP_MS / 10.0) + 2
        sig = self._render(p, blocks, duck_at=0)
        assert abs(float(np.abs(sig[-160:]).mean()) - duck_gain()) < 0.05

    def test_ramp_is_spread_across_blocks_not_finished_in_one(self):
        """这一条才真正钉住**跨块**的爬坡上限 —— 上面那条"跳变要小"只测到了块【内】的
        线性插值:把跨块上限去掉后,一块之内 linspace 依然会把 1.0 平滑插到 0.25,
        单样本跳变仍然很小,用例照样通过。反向验证时(拆掉上限、64 例全绿)才暴露出来。

        真正的判据是**爬坡有没有花够时间**:50ms 爬坡 + 10ms 的块 = 一块最多走 20%,
        所以一块之后增益应当还在 0.8 附近,远没到 0.25。
        """
        p = self._player()
        p.play(pcm16_from_float(np.ones(16000, dtype=np.float32)))
        p.duck()
        buf = np.zeros((160, 1), dtype=np.float32)
        p._fill(buf, 160)  # 只走一块(10ms)
        gain = p.status()["gain"]
        assert gain > 0.5, f"一块(10ms)之后增益已降到 {gain} —— 跨块爬坡上限没生效,爬坡过快"

    def test_status_exposes_ducking_state(self):
        """压音是"听得见但不明显"的行为 —— 不摊出来就无从判断到底压了没有、是否忘了恢复。"""
        p = self._player()
        assert p.status()["ducked"] is False
        p.duck()
        st = p.status()
        assert st["ducked"] is True and st["target_gain"] < 1.0 and st["duck_events"] == 1
        p.unduck()
        assert p.status()["ducked"] is False

    def test_duck_is_idempotent_in_counting(self):
        p = self._player()
        p.duck()
        p.duck()
        assert p.status()["duck_events"] == 1, "重复压音不该重复计数"

    def test_defaults(self, monkeypatch):
        from core.voice_duplex_session import duck_gain, ducking_enabled

        monkeypatch.delenv("GALAXY_VOICE_DUCKING", raising=False)
        monkeypatch.delenv("GALAXY_VOICE_DUCK_GAIN", raising=False)
        assert ducking_enabled() is True
        assert duck_gain() == pytest.approx(0.25)

    def test_bad_gain_falls_back(self, monkeypatch, caplog):
        from core.voice_duplex_session import duck_gain

        monkeypatch.setenv("GALAXY_VOICE_DUCK_GAIN", "loud")
        with caplog.at_level("WARNING"):
            assert duck_gain() == pytest.approx(0.25)
        assert "不是合法数值" in caplog.text

    def test_gain_is_clamped(self, monkeypatch):
        from core.voice_duplex_session import duck_gain

        monkeypatch.setenv("GALAXY_VOICE_DUCK_GAIN", "5")
        assert duck_gain() == 1.0
        monkeypatch.setenv("GALAXY_VOICE_DUCK_GAIN", "-1")
        assert duck_gain() == 0.0


class TestDuplexBargeInUsesTheClassifier:
    """双工路径此前对**任何** ``USER_SPEECH_STARTED`` 都直接 ``response.cancel`` ——
    等于把回合制那边刚修好的毛病又犯了一遍:用户"嗯"一声也会把整个回复取消掉。

    服务端 VAD 只知道"有人在出声",分不出抢话与积极倾听 —— 那是 ``classify_barge_in``
    的活。改成两段式:开口先压音(非承诺),最终转写到了再决定继续还是取消。
    """

    @staticmethod
    def _loop_with_fakes():
        from core.voice_loop import VoiceLoop

        loop = VoiceLoop(object(), speak_responses=False)

        class _FakePlayer:
            def __init__(self):
                self.ducked_calls = 0
                self.unducked_calls = 0

            def duck(self):
                self.ducked_calls += 1

            def unduck(self):
                self.unducked_calls += 1

        class _FakeSession:
            def __init__(self, events):
                self._events = events
                self.interrupts = 0

            async def interrupt(self):
                self.interrupts += 1

            async def events(self):
                for e in self._events:
                    yield e

        loop._duplex_player = _FakePlayer()
        return loop, _FakePlayer, _FakeSession

    def _run(self, transcript):
        from core.voice_duplex_session import DuplexEvent, DuplexEventType

        loop, _FP, _FS = self._loop_with_fakes()
        session = _FS(
            [
                DuplexEvent(DuplexEventType.USER_SPEECH_STARTED),
                DuplexEvent(DuplexEventType.FINAL_TRANSCRIPT, text=transcript),
                DuplexEvent(DuplexEventType.SESSION_CLOSED),
            ]
        )
        asyncio.run(loop._duplex_downlink(session, DuplexEventType))
        return loop._duplex_player, session

    def test_speech_start_ducks_instead_of_cancelling(self):
        player, session = self._run("嗯")
        assert player.ducked_calls == 1, "用户开口应先压音"
        assert session.interrupts == 0, "光是出声还不该取消模型回复"

    def test_backchannel_resumes_full_volume_and_never_cancels(self):
        player, session = self._run("嗯")
        assert session.interrupts == 0
        assert player.unducked_calls >= 1, "判定为应答后应恢复音量"

    def test_real_interruption_cancels_on_the_server(self):
        player, session = self._run("不是这个我要另一个")
        assert session.interrupts == 1, "真打断必须让服务端停止生成"

    def test_falls_back_to_cancel_when_ducking_is_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_VOICE_DUCKING", "0")
        player, session = self._run("嗯")
        assert player.ducked_calls == 0
        assert session.interrupts == 1, "关掉 ducking 应退回原来的「开口即取消」"


# ── 6. Gemini Live 适配器 ──────────────────────────────────────────────────


class TestGeminiLiveFrames:
    """补上第二个 provider,双工层不再只绑一家。

    两家不只是字段名不同,是**结构不同**:配置帧的位置与时机(setup 必须是连接后第一帧)、
    音频上行的载体(realtimeInput.mediaChunks,采样率写在 mimeType 里)、下行 parts 的
    **混合数组**(同一个 parts 里既可能是音频也可能是文本)、回合边界的表达
    (turnComplete/interrupted 标志而非独立事件)、鉴权方式(key 在 URL query,没有
    Authorization 头)。所以是两份实现,不是参数化的一份。
    """

    def setup_method(self):
        from core.voice_duplex_session import GeminiLiveAdapter

        self.a = GeminiLiveAdapter()
        self.cfg = DuplexSessionConfig(
            url="wss://x", api_key="k", model="gemini-2.0-flash-exp", voice="Puck", provider="gemini_live"
        )

    def test_setup_frame_shape(self):
        f = self.a.session_update(self.cfg)
        assert "setup" in f, "Gemini 的配置帧叫 setup,不是 session.update"
        assert f["setup"]["model"].startswith("models/"), "model 必须带 models/ 前缀"
        assert f["setup"]["generationConfig"]["responseModalities"] == ["AUDIO"]

    def test_model_prefix_not_doubled(self):
        cfg = DuplexSessionConfig(url="w", api_key="k", model="models/gemini-x", provider="gemini_live")
        assert self.a.session_update(cfg)["setup"]["model"] == "models/gemini-x"

    def test_audio_frame_carries_rate_in_mimetype(self):
        """采样率写在 mimeType 里 —— Gemini 没有像 OpenAI 那样在 session 里统一声明格式。"""
        f = self.a.audio_frame(b"\x01\x02")
        chunk = f["realtimeInput"]["mediaChunks"][0]
        assert "rate=16000" in chunk["mimeType"]
        assert base64.b64decode(chunk["data"]) == b"\x01\x02"

    def test_text_frame_is_a_single_turn_complete(self):
        """Gemini 一帧即可(turnComplete 就等于"说完了该你了"),
        不需要 OpenAI 那种 create item + response.create 两步。"""
        frames = self.a.text_frame("你好")
        assert len(frames) == 1
        assert frames[0]["clientContent"]["turnComplete"] is True

    def test_interrupt_is_an_empty_completed_turn(self):
        """Gemini 没有显式 cancel 帧,靠新的用户输入打断 —— 机制不同,不能照抄
        OpenAI 的 response.cancel。"""
        f = self.a.interrupt_frame()
        assert f["clientContent"]["turns"] == []
        assert f["clientContent"]["turnComplete"] is True

    def test_no_auth_header(self):
        """Gemini 的 key 在 URL query 里。若照抄 OpenAI 加 Authorization 头,握手会被拒。"""
        assert self.a.headers(self.cfg) == {}

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ({"setupComplete": {}}, DuplexEventType.SESSION_OPEN),
            ({"serverContent": {"turnComplete": True}}, DuplexEventType.RESPONSE_DONE),
            ({"serverContent": {"interrupted": True}}, DuplexEventType.USER_SPEECH_STARTED),
            ({"error": {"message": "quota"}}, DuplexEventType.ERROR),
        ],
    )
    def test_control_frames(self, raw, expected):
        assert self.a.decode(raw).type is expected

    def test_audio_part_decoded(self):
        ev = self.a.decode(
            {"serverContent": {"modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm", "data": "QUJD"}}]}}}
        )
        assert ev.type is DuplexEventType.ASSISTANT_AUDIO_DELTA
        assert base64.b64decode(ev.audio_b64) == b"ABC"

    def test_text_part_decoded(self):
        ev = self.a.decode({"serverContent": {"modelTurn": {"parts": [{"text": "你好"}]}}})
        assert ev.type is DuplexEventType.ASSISTANT_TEXT_DELTA and ev.text == "你好"

    def test_mixed_parts_prefer_audio(self):
        """parts 是混合数组。音频要优先 —— 它才是必须立刻播出去的那个。"""
        ev = self.a.decode(
            {"serverContent": {"modelTurn": {"parts": [{"text": "旁白"}, {"inlineData": {"data": "QUJD"}}]}}}
        )
        assert ev.type is DuplexEventType.ASSISTANT_AUDIO_DELTA

    def test_input_transcription_becomes_final_transcript(self):
        ev = self.a.decode({"serverContent": {"inputTranscription": {"text": "帮我订机票"}}})
        assert ev.type is DuplexEventType.FINAL_TRANSCRIPT and ev.text == "帮我订机票"

    def test_unknown_frames_ignored(self):
        assert self.a.decode({"weird": 1}) is None
        assert self.a.decode({"serverContent": {}}) is None


class TestProviderSelection:
    def test_both_adapters_registered(self):
        assert get_adapter("openai_realtime").name == "openai_realtime"
        assert get_adapter("gemini_live").name == "gemini_live"

    def test_unknown_provider_still_fails_loudly(self):
        """静默退回默认实现会让用户以为在用 A、实际发的是 B 的帧。"""
        with pytest.raises(ValueError, match="未实现"):
            get_adapter("anthropic_realtime")

    def test_session_picks_adapter_from_config(self):
        """写死默认适配器会让 GALAXY_REALTIME_PROVIDER 形同虚设。"""
        cfg = DuplexSessionConfig(url="wss://x", api_key="k", provider="gemini_live")
        assert DuplexSession(cfg).adapter.name == "gemini_live"

    def test_from_env_builds_gemini_config(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "gemini_live")
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "gk")
        monkeypatch.delenv("GALAXY_REALTIME_URL", raising=False)
        monkeypatch.delenv("GALAXY_REALTIME_MODEL", raising=False)
        monkeypatch.delenv("GALAXY_REALTIME_VOICE", raising=False)
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        assert cfg.provider == "gemini_live"
        assert "BidiGenerateContent" in cfg.url and "key=gk" in cfg.url
        assert cfg.model.startswith("gemini-")
        assert cfg.voice == "Puck"

    def test_from_env_gemini_missing_key_names_the_right_vars(self, monkeypatch, caplog):
        monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "gemini_live")
        for v in ("GALAXY_REALTIME_API_KEY", "GOOGLE_API_KEY", "GALAXY_REALTIME_URL"):
            monkeypatch.delenv(v, raising=False)
        with caplog.at_level("WARNING"):
            assert DuplexSessionConfig.from_env() is None
        assert "GOOGLE_API_KEY" in caplog.text, "缺 key 的提示要点名该 provider 的变量"


class _FakeGeminiServer:
    """说 Gemini Live 帧形状的本地服务端。与 OpenAI 那个同一套方法,不是 mock。"""

    def __init__(self) -> None:
        self.received: list = []
        self._server = None
        self.url = ""

    async def __aenter__(self):
        async def _handler(ws):
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg)
                if "setup" in msg:
                    await ws.send(json.dumps({"setupComplete": {}}))
                elif "realtimeInput" in msg:
                    await ws.send(json.dumps({"serverContent": {"inputTranscription": {"text": "今天天气怎么样"}}}))
                    await ws.send(
                        json.dumps(
                            {
                                "serverContent": {
                                    "modelTurn": {
                                        "parts": [{"inlineData": {"data": base64.b64encode(b"\x00\x01" * 8).decode()}}]
                                    }
                                }
                            }
                        )
                    )
                    await ws.send(json.dumps({"serverContent": {"turnComplete": True}}))

        self._server = await websockets.serve(_handler, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *_exc):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def keys(self) -> list:
        return [k for m in self.received for k in m]


class TestGeminiFullSessionOverRealWebSocket:
    @pytest.mark.asyncio
    async def test_end_to_end(self):
        async with _FakeGeminiServer() as server:
            cfg = DuplexSessionConfig(url=server.url, api_key="k", provider="gemini_live")
            sess = DuplexSession(cfg)
            assert await sess.connect() is True
            try:
                await _drain(sess, DuplexEventType.SESSION_OPEN)
                assert "setup" in server.keys(), "建连后第一帧必须是 setup"

                await sess.send_audio(pcm16_from_float(np.zeros(160, dtype=np.float32) + 0.1))
                events = await _drain(sess, DuplexEventType.RESPONSE_DONE)
                kinds = [e.type for e in events]
                assert DuplexEventType.FINAL_TRANSCRIPT in kinds
                assert DuplexEventType.ASSISTANT_AUDIO_DELTA in kinds
                assert "realtimeInput" in server.keys()
            finally:
                await sess.close()
