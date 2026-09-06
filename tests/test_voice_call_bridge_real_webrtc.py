"""设备 WebRTC 音频 ↔ 双工语音会话:跑在**真 aiortc** 上的回环验证。

为什么不是 mock
---------------
这条链路上会出错的地方几乎全在"真的传一遍"才暴露:重采样把音调弄错、出站轨不按
时间产帧导致对端听到加速播放、帧的 ``pts`` / ``time_base`` 不对导致轨被判为无效、
打断时缓冲没清干净所以 AI 又硬说完半句。把 ``RTCPeerConnection`` mock 掉,以上每一
条都会被"测试通过"盖住。

所以这里建两个**真的** ``RTCPeerConnection``,做真的 offer/answer 协商,音频真的经
Opus 编码、经 ICE 通道传输、再解码回来。假的只有 provider 那一端(没有 key、没有出网,
无法连真的 OpenAI Realtime / Gemini Live)——而那一端的协议编解码有它自己的测试。
"""

from __future__ import annotations

import asyncio
import base64
import math
import struct
from typing import Any, AsyncIterator, List, Optional

import pytest

from core.voice_call_bridge import (
    FRAME_MS,
    OUTBOUND_RATE,
    VoiceCall,
    VoiceCallRegistry,
    webrtc_available,
)

pytestmark = pytest.mark.skipif(
    webrtc_available() is not None,
    reason=f"WebRTC 依赖不可用: {webrtc_available()}",
)

PROVIDER_RATE = 16000


# ---------------------------------------------------------------------------
# 替身:只替 provider 那一端
# ---------------------------------------------------------------------------


class _Cfg:
    sample_rate = PROVIDER_RATE


class FakeDuplexSession:
    """一条假的 provider 会话。记录收到的上行,按脚本吐下行事件。"""

    def __init__(self, script: Optional[List[Any]] = None) -> None:
        self.config = _Cfg()
        self.sent_audio: List[bytes] = []
        self.interrupted = 0
        self.closed = False
        self._script = list(script or [])
        self._queue: asyncio.Queue = asyncio.Queue()
        for ev in self._script:
            self._queue.put_nowait(ev)

    async def send_audio(self, pcm16: bytes) -> bool:
        self.sent_audio.append(pcm16)
        return True

    async def interrupt(self) -> bool:
        self.interrupted += 1
        return True

    async def close(self) -> None:
        self.closed = True

    async def events(self) -> AsyncIterator[Any]:
        while True:
            ev = await self._queue.get()
            if ev is None:
                return
            yield ev

    def push(self, ev: Any) -> None:
        self._queue.put_nowait(ev)


class Ev:
    """一条下行事件,字段与 DuplexEvent 同型。"""

    def __init__(self, type_: str, text: str = "", audio_b64: str = "", error: str = "") -> None:
        self.type = type_
        self.text = text
        self.audio_b64 = audio_b64
        self.error = error


def tone_pcm16(rate: int, ms: int, freq: int = 440, amp: int = 12000) -> bytes:
    """一段正弦音。用音调而不是随机数:重采样出错时音调会变,肉眼看频谱就能发现。"""
    n = int(rate * ms / 1000)
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))


# ---------------------------------------------------------------------------
# 1. 出站轨:按时间产帧,不是有多少给多少
# ---------------------------------------------------------------------------


async def test_downlink_track_emits_correctly_shaped_frames():
    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess)
    track = call.downlink_track

    await track.push_pcm16(tone_pcm16(OUTBOUND_RATE, 100))
    frame = await track.recv()

    assert frame.sample_rate == OUTBOUND_RATE
    assert frame.samples == int(OUTBOUND_RATE * FRAME_MS / 1000)
    assert frame.format.name == "s16"
    assert frame.time_base.denominator == OUTBOUND_RATE, "time_base 不对,对端会算错时间轴"


async def test_downlink_track_paces_itself_instead_of_dumping():
    """缓冲里有一整秒也只能一帧一帧按时给,否则对端听到的是加速播放。"""
    call = VoiceCall("watch_01", FakeDuplexSession())
    await call.downlink_track.push_pcm16(tone_pcm16(OUTBOUND_RATE, 1000))

    start = asyncio.get_running_loop().time()
    for _ in range(5):
        await call.downlink_track.recv()
    elapsed = asyncio.get_running_loop().time() - start

    # 5 帧 × 20ms = 100ms；第一帧不等待，所以下界取 3 帧的时长。
    assert elapsed >= FRAME_MS * 3 / 1000, f"出站轨没有按时间节流(用了 {elapsed*1000:.0f}ms)"


async def test_downlink_track_emits_silence_rather_than_stalling():
    """缓冲空时必须给静音帧。断流会让对端的抖动缓冲以为链路坏了。"""
    call = VoiceCall("watch_01", FakeDuplexSession())
    frame = await asyncio.wait_for(call.downlink_track.recv(), timeout=1.0)
    assert bytes(frame.planes[0])[:64] == b"\x00" * 64


async def test_downlink_buffer_drops_oldest_when_full():
    """过期音频没有价值;阻塞写入会把上行一起卡住。所以满了丢最旧的。"""
    call = VoiceCall("watch_01", FakeDuplexSession())
    track = call.downlink_track
    await track.push_pcm16(tone_pcm16(OUTBOUND_RATE, 4000))  # 远超 1.5s 上限
    assert track.dropped_bytes > 0


# ---------------------------------------------------------------------------
# 2. 重采样
# ---------------------------------------------------------------------------


async def test_upsample_to_track_rate_preserves_duration():
    """16k → 48k 之后时长必须不变。变了就是变速播放。"""
    call = VoiceCall("watch_01", FakeDuplexSession())
    src = tone_pcm16(PROVIDER_RATE, 100)
    out = call._upsample_for_track(src)
    src_ms = len(src) / 2 / PROVIDER_RATE * 1000
    out_ms = len(out) / 2 / OUTBOUND_RATE * 1000
    assert abs(out_ms - src_ms) < 2, f"时长从 {src_ms:.0f}ms 变成了 {out_ms:.0f}ms"


async def test_upsample_is_identity_when_rates_match():
    sess = FakeDuplexSession()
    sess.config.sample_rate = OUTBOUND_RATE
    call = VoiceCall("watch_01", sess)
    src = tone_pcm16(OUTBOUND_RATE, 20)
    assert call._upsample_for_track(src) == src


# ---------------------------------------------------------------------------
# 3. 端到端:两个真 RTCPeerConnection
# ---------------------------------------------------------------------------


async def _connect(pc_a: Any, pc_b: Any) -> None:
    """真的做一次 offer/answer 协商。"""
    offer = await pc_a.createOffer()
    await pc_a.setLocalDescription(offer)
    await pc_b.setRemoteDescription(pc_a.localDescription)
    answer = await pc_b.createAnswer()
    await pc_b.setLocalDescription(answer)
    await pc_a.setRemoteDescription(pc_b.localDescription)


async def test_device_audio_really_reaches_the_provider():
    """设备说话 → 经真 WebRTC → 落到 session.send_audio()。

    这是整件事的核心断言:音频真的走完了编码、ICE 传输、解码、重采样这一整条路。
    """
    import av
    from aiortc import RTCPeerConnection
    from aiortc.mediastreams import MediaStreamTrack

    class DeviceMic(MediaStreamTrack):
        """假装是手表麦克风的一条轨:持续产 440Hz 正弦。"""

        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._pts = 0
            self.rate = 48000
            self.spf = int(self.rate * FRAME_MS / 1000)

        async def recv(self) -> Any:
            import fractions

            await asyncio.sleep(FRAME_MS / 1000)
            frame = av.AudioFrame(format="s16", layout="mono", samples=self.spf)
            frame.planes[0].update(tone_pcm16(self.rate, FRAME_MS))
            frame.sample_rate = self.rate
            frame.pts = self._pts
            frame.time_base = fractions.Fraction(1, self.rate)
            self._pts += self.spf
            return frame

    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess)

    device = RTCPeerConnection()  # 手表侧
    gateway = RTCPeerConnection()  # 网关侧
    got_track: asyncio.Future = asyncio.get_running_loop().create_future()

    @gateway.on("track")
    def on_track(track: Any) -> None:
        if track.kind == "audio" and not got_track.done():
            got_track.set_result(track)

    device.addTrack(DeviceMic())
    try:
        await _connect(device, gateway)
        track = await asyncio.wait_for(got_track, timeout=10.0)
        call.attach_uplink(track)

        # 等真的有音频流过来
        for _ in range(100):
            if len(sess.sent_audio) >= 3:
                break
            await asyncio.sleep(0.05)

        assert len(sess.sent_audio) >= 3, f"上行没到 provider(只收到 {len(sess.sent_audio)} 块)"
        total = sum(len(c) for c in sess.sent_audio)
        assert total > 0
        # 重采样后必须是 provider 要的采样率对应的 PCM16(偶数字节)
        assert all(len(c) % 2 == 0 for c in sess.sent_audio)
        assert not all(c == b"\x00" * len(c) for c in sess.sent_audio), "收到的全是静音,重采样把信号丢了"
    finally:
        await call.close()
        await device.close()
        await gateway.close()


async def test_provider_audio_really_reaches_the_device():
    """AI 说话 → 出站轨 → 经真 WebRTC → 手表侧收到可解码的音频帧。"""
    from aiortc import RTCPeerConnection

    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess)

    gateway = RTCPeerConnection()
    device = RTCPeerConnection()
    got: asyncio.Future = asyncio.get_running_loop().create_future()

    @device.on("track")
    def on_track(track: Any) -> None:
        if track.kind == "audio" and not got.done():
            got.set_result(track)

    gateway.addTrack(call.downlink_track)
    call.start_downlink()

    try:
        await _connect(gateway, device)
        inbound = await asyncio.wait_for(got, timeout=10.0)

        # provider 吐一段音频
        pcm = tone_pcm16(PROVIDER_RATE, 200)
        sess.push(Ev("assistant_audio_delta", audio_b64=base64.b64encode(pcm).decode()))

        frames = [await asyncio.wait_for(inbound.recv(), timeout=5.0) for _ in range(6)]
        assert len(frames) == 6
        assert all(f.sample_rate > 0 for f in frames)
        assert any(
            bytes(f.planes[0]) != b"\x00" * len(bytes(f.planes[0])) for f in frames
        ), "手表侧只收到静音 —— AI 的声音没能穿过 WebRTC"
        assert sess.sent_audio == [], "下行不该反向污染上行"
    finally:
        await call.close()
        await gateway.close()
        await device.close()


# ---------------------------------------------------------------------------
# 4. 事件、打断、收尾
# ---------------------------------------------------------------------------


async def test_events_are_forwarded_verbatim():
    """事件名直接用 DuplexEventType 的值,不重新命名 —— 中间翻译一层就会漂。"""
    seen: List[tuple] = []

    async def sink(event: str, text: str, error: str) -> None:
        seen.append((event, text, error))

    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess, send_event=sink)
    call.start_downlink()

    sess.push(Ev("partial_transcript", text="今天天"))
    sess.push(Ev("final_transcript", text="今天天气怎么样"))
    sess.push(Ev("assistant_text_delta", text="我看看"))
    sess.push(Ev("response_done"))

    for _ in range(60):
        if len(seen) >= 4:
            break
        await asyncio.sleep(0.02)
    await call.close()

    assert [e for e, _, _ in seen] == [
        "partial_transcript",
        "final_transcript",
        "assistant_text_delta",
        "response_done",
    ]
    assert seen[1][1] == "今天天气怎么样"


async def test_audio_delta_does_not_leak_into_text_events():
    """音频块不该也当成一条文字事件发出去 —— 每 20ms 一条会把控制通道淹掉。"""
    seen: List[str] = []

    async def sink(event: str, text: str, error: str) -> None:
        seen.append(event)

    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess, send_event=sink)
    call.start_downlink()
    sess.push(Ev("assistant_audio_delta", audio_b64=base64.b64encode(tone_pcm16(PROVIDER_RATE, 20)).decode()))
    sess.push(Ev("response_done"))

    for _ in range(60):
        if "response_done" in seen:
            break
        await asyncio.sleep(0.02)
    await call.close()
    assert "assistant_audio_delta" not in seen


async def test_user_speech_clears_pending_audio():
    """用户开口时必须清掉已缓冲的 AI 音频,否则 AI 会硬说完半句才停。"""
    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess)
    call.start_downlink()

    sess.push(Ev("assistant_audio_delta", audio_b64=base64.b64encode(tone_pcm16(PROVIDER_RATE, 800)).decode()))
    for _ in range(60):
        if call.stats.downlink_chunks >= 1:
            break
        await asyncio.sleep(0.02)

    sess.push(Ev("user_speech_started"))
    for _ in range(60):
        if call.stats.events.get("user_speech_started"):
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)

    frame = await call.downlink_track.recv()
    assert bytes(frame.planes[0]) == b"\x00" * len(bytes(frame.planes[0])), "打断后缓冲没清干净"
    await call.close()


async def test_interrupt_stops_the_server_and_clears_the_buffer():
    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess)
    await call.downlink_track.push_pcm16(tone_pcm16(OUTBOUND_RATE, 500))
    await call.interrupt("user_tap")
    assert sess.interrupted == 1, "没有让服务端停口"
    frame = await call.downlink_track.recv()
    assert bytes(frame.planes[0]) == b"\x00" * len(bytes(frame.planes[0]))
    await call.close()


async def test_close_always_closes_the_provider_session():
    """漏关一次就是那头挂着一条会话继续计费,而且没有任何报错提示。"""
    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess)
    call.start_downlink()
    await call.close()
    assert sess.closed is True
    assert call.closed is True


async def test_close_is_idempotent_and_never_raises():
    sess = FakeDuplexSession()
    call = VoiceCall("watch_01", sess)
    await call.close()
    await call.close()
    assert sess.closed is True


async def test_close_still_closes_session_when_it_raises():
    class Grumpy(FakeDuplexSession):
        async def close(self) -> None:
            self.closed = True
            raise RuntimeError("provider 那头炸了")

    call = VoiceCall("watch_01", Grumpy())
    await call.close()  # 不许抛
    assert call.closed is True


# ---------------------------------------------------------------------------
# 5. 一台设备一通电话
# ---------------------------------------------------------------------------


async def test_second_call_supersedes_the_first():
    """连点两次不能开出两条 provider 会话 —— 两倍计费,且都对着同一个麦克风。"""
    reg = VoiceCallRegistry()
    s1, s2 = FakeDuplexSession(), FakeDuplexSession()
    c1, c2 = VoiceCall("watch_01", s1), VoiceCall("watch_01", s2)

    await reg.put(c1)
    old = await reg.put(c2)

    assert old is c1
    assert s1.closed is True, "旧通话没被挂断"
    assert s2.closed is False
    assert reg.active_count() == 1
    await reg.end_all()


async def test_registry_end_reports_whether_there_was_a_call():
    reg = VoiceCallRegistry()
    assert await reg.end("nobody") is False
    sess = FakeDuplexSession()
    await reg.put(VoiceCall("watch_01", sess))
    assert await reg.end("watch_01") is True
    assert sess.closed is True


async def test_end_all_closes_every_call():
    reg = VoiceCallRegistry()
    sessions = [FakeDuplexSession() for _ in range(3)]
    for i, s in enumerate(sessions):
        await reg.put(VoiceCall(f"watch_{i}", s))
    assert await reg.end_all() == 3
    assert all(s.closed for s in sessions)
    assert reg.active_count() == 0


# ---------------------------------------------------------------------------
# 6. 依赖缺失时如实说明,不假装接通
# ---------------------------------------------------------------------------


def test_missing_dependency_returns_a_readable_reason(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "aiortc":
            raise ImportError("No module named 'aiortc'", name="aiortc")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    reason = webrtc_available()
    assert reason and "aiortc" in reason, "依赖缺失时必须说清是缺什么,而不是只给一个 False"
