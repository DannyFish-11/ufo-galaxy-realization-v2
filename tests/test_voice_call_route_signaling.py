"""通话信令跑在**真** ``handle_message`` 上的验证。

为什么不直接 new 一个 VoiceCallRoute 来测
--------------------------------------
直接测 ``VoiceCallRoute`` 只能证明"这个类自己是对的",证明不了网关真的会把消息交给
它。而这条路上最容易出的错恰恰在交接处:消息在 ``event.kind`` 分派链里被归成
``unknown``、掉进末尾的错误分支,设备收到一条 error,通话永远接不通 —— 类本身完全正常。

所以这里的入口一律是 ``galaxy_gateway.websocket_handler.handle_message``,走真的
``parse_message_strict`` → 真的归一化 → 真的分派。假的只有两头:设备那头的
WebSocket(换成一个记录回包的替身)和 provider 那头的双工会话(没有 key、没有出网)。
中间那段 WebRTC 是**真的** —— 真的 SDP 协商、真的 Opus、真的 ICE 传输。
"""

from __future__ import annotations

import asyncio
import fractions
import json
import math
import struct
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from core.voice_call_bridge import FRAME_MS, get_call_registry, webrtc_available
from core.voice_duplex_session import DuplexEvent, DuplexEventType
from galaxy_gateway.voice_call_route import (
    DEVICE_ORIGINATED,
    VOICE_CALL_TYPES,
    VoiceCallRoute,
    active_route_count,
    close_voice_route,
)
from galaxy_gateway.websocket_handler import handle_message, handle_websocket

PROVIDER_RATE = 16000
_needs_webrtc = pytest.mark.skipif(
    webrtc_available() is not None,
    reason=f"WebRTC 依赖不可用: {webrtc_available()}",
)


# ---------------------------------------------------------------------------
# 替身
# ---------------------------------------------------------------------------


class _Cfg:
    sample_rate = PROVIDER_RATE
    provider = "openai_realtime"


class FakeDuplexSession:
    def __init__(self) -> None:
        self.config = _Cfg()
        self.sent_audio: List[bytes] = []
        self.interrupted = 0
        self.closed = False
        self._queue: asyncio.Queue = asyncio.Queue()

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


class FakeWebSocket:
    """只记录回包。信令的全部可观测行为都在这里。"""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    async def send_json(self, payload: Dict[str, Any]) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:  # pragma: no cover - 未走到
        pass

    def frames(self, type_: str) -> List[Dict[str, Any]]:
        return [f for f in self.sent if f.get("type") == type_]

    def last(self, type_: str) -> Optional[Dict[str, Any]]:
        got = self.frames(type_)
        return got[-1] if got else None


def tone_pcm16(rate: int, ms: int, freq: int = 440, amp: int = 12000) -> bytes:
    n = int(rate * ms / 1000)
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))


def wire(type_: str, device_id: str = "watch_01", **payload: Any) -> Dict[str, Any]:
    """一条 AIP v3 线上消息。刻意手写而不是用构造器 —— 手表发来的就是这个形状。"""
    return {"version": "3.0", "type": type_, "device_id": device_id, "payload": dict(payload)}


def make_device_mic() -> Any:
    import av
    from aiortc.mediastreams import MediaStreamTrack

    class DeviceMic(MediaStreamTrack):
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._pts = 0
            self.rate = 48000
            self.spf = int(self.rate * FRAME_MS / 1000)

        async def recv(self) -> Any:
            await asyncio.sleep(FRAME_MS / 1000)
            frame = av.AudioFrame(format="s16", layout="mono", samples=self.spf)
            frame.planes[0].update(tone_pcm16(self.rate, FRAME_MS))
            frame.sample_rate = self.rate
            frame.pts = self._pts
            frame.time_base = fractions.Fraction(1, self.rate)
            self._pts += self.spf
            return frame

    return DeviceMic()


@pytest.fixture
def fake_session(monkeypatch: Any) -> FakeDuplexSession:
    """把 provider 那一端换成替身,其余全走真的。"""
    import core.voice_duplex_session as vds

    sess = FakeDuplexSession()

    async def _open(config: Any = None, adapter: Any = None) -> Any:
        return sess

    monkeypatch.setattr(vds.DuplexSessionConfig, "from_env", classmethod(lambda cls, **kw: _Cfg()))
    monkeypatch.setattr(vds, "open_duplex_session", _open)
    return sess


@pytest.fixture(autouse=True)
async def _clean_registry() -> AsyncIterator[None]:
    """每个用例前后都清干净:通话是全局注册表里的资源,漏一个下个用例就被它污染。"""
    await get_call_registry().end_all(reason="test_setup")
    yield
    await get_call_registry().end_all(reason="test_teardown")


# ---------------------------------------------------------------------------
# 1. 协议接线:这六条真的被网关认领了吗
# ---------------------------------------------------------------------------


async def test_declared_types_all_exist_in_the_protocol_ssot():
    """本模块认领的每一条都必须在网关协议权威里。

    少一条的后果不是报错,是 ``parse_message_strict`` 直接拒收 —— 手表拨号毫无反应。
    """
    from galaxy_gateway.protocol.aip_v3 import MessageType

    known = {m.value for m in MessageType}
    missing = VOICE_CALL_TYPES - known
    assert not missing, f"这些类型网关协议里没有: {missing}"
    assert DEVICE_ORIGINATED <= VOICE_CALL_TYPES


async def test_voice_kinds_are_registered_and_classified_as_transport():
    """没登记的话,分派前那条日志会把每一帧通话信令报成 kind=unknown。

    通话本身照样能通(拦截在分派链之前),但线上排障时看到的是一片 unknown —— 这正是
    ACK / PING 当初补登记要解决的同一个坑。
    """
    from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass, classify_ingress_kind
    from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind

    for t in VOICE_CALL_TYPES:
        assert IngressEventKind.normalise(t) == t, f"{t} 未登记为 IngressEventKind"
        assert classify_ingress_kind(t) == IngressMessageClass.TRANSPORT


async def test_real_dispatch_hands_voice_messages_to_the_route(monkeypatch: Any):
    """真 handle_message 收到 voice_call_start 时,走的是通话分支而不是错误分支。"""
    seen: List[str] = []

    async def _spy(self: Any, msg_type: str, payload: Dict[str, Any]) -> None:
        seen.append(msg_type)

    monkeypatch.setattr(VoiceCallRoute, "handle", _spy)
    ws = FakeWebSocket()
    for t in sorted(DEVICE_ORIGINATED):
        await handle_message("conn_dispatch", wire(t), ws)
    await close_voice_route("conn_dispatch")

    assert seen == sorted(DEVICE_ORIGINATED)
    assert ws.frames("error") == [], "通话信令不该掉进未知消息的错误分支"


# ---------------------------------------------------------------------------
# 2. 拒绝路径:被拒时必须说清是为什么
# ---------------------------------------------------------------------------


async def test_reject_when_no_provider_says_so(monkeypatch: Any):
    """没有 provider 时如实拒绝。

    只回一个不带原因的 voice_call_end,设备只能显示"通话失败" —— 而没装 aiortc、
    没配 key、SDP 谈崩三种情况的处置完全不同。
    """
    import core.voice_duplex_session as vds

    monkeypatch.setattr(vds.DuplexSessionConfig, "from_env", classmethod(lambda cls, **kw: None))
    monkeypatch.setattr("core.voice_call_bridge.webrtc_available", lambda: None)

    ws = FakeWebSocket()
    await handle_message("conn_np", wire("voice_call_start", sdp="v=0\r\n"), ws)

    end = ws.last("voice_call_end")
    assert end is not None and ws.last("voice_call_accepted") is None
    assert "provider" in end["reason"] or "后端" in end["reason"], end["reason"]
    await close_voice_route("conn_np")


async def test_reject_when_webrtc_missing_names_the_dependency(monkeypatch: Any):
    monkeypatch.setattr("core.voice_call_bridge.webrtc_available", lambda: "未安装 aiortc")
    ws = FakeWebSocket()
    await handle_message("conn_nw", wire("voice_call_start", sdp="v=0\r\n"), ws)

    end = ws.last("voice_call_end")
    assert end is not None and end["reason"] == "未安装 aiortc"
    await close_voice_route("conn_nw")


async def test_reject_when_sdp_missing(monkeypatch: Any, fake_session: FakeDuplexSession):
    monkeypatch.setattr("core.voice_call_bridge.webrtc_available", lambda: None)
    ws = FakeWebSocket()
    await handle_message("conn_nosdp", wire("voice_call_start"), ws)

    end = ws.last("voice_call_end")
    assert end is not None and "SDP" in end["reason"]
    assert not fake_session.closed, "还没开会话就不该有会话被关"
    await close_voice_route("conn_nosdp")


async def test_kill_switch_rejects_and_says_which_switch(monkeypatch: Any):
    """运维一键停通话时,拒绝理由要点名是哪个开关,否则没人知道该改什么。"""
    monkeypatch.setenv("GALAXY_VOICE_CALL", "0")
    ws = FakeWebSocket()
    await handle_message("conn_off", wire("voice_call_start", sdp="v=0\r\n"), ws)

    end = ws.last("voice_call_end")
    assert end is not None and "GALAXY_VOICE_CALL" in end["reason"]
    await close_voice_route("conn_off")


async def test_downlink_messages_from_the_device_are_refused(monkeypatch: Any):
    """voice_call_accepted / voice_event 是网关下行的。设备发上来说明方向搞反了。"""
    called: List[str] = []
    monkeypatch.setattr(
        VoiceCallRoute, "_start", lambda self, payload: called.append("start")  # type: ignore[assignment]
    )
    ws = FakeWebSocket()
    for t in ("voice_call_accepted", "voice_event"):
        await handle_message("conn_rev", wire(t, call_id="c1"), ws)

    assert called == [], "反方向的消息不该触发建立通话"
    assert ws.sent == [], "也不该有任何回包"
    await close_voice_route("conn_rev")


# ---------------------------------------------------------------------------
# 3. 真 WebRTC:整条路跑通
# ---------------------------------------------------------------------------


async def _negotiate(ws: FakeWebSocket, device: Any, conn_id: str, device_id: str = "watch_01") -> Dict[str, Any]:
    """手表侧发真 offer,经真 handle_message 拿回真 answer,并装上。"""
    from aiortc import RTCSessionDescription

    offer = await device.createOffer()
    await device.setLocalDescription(offer)
    await handle_message(conn_id, wire("voice_call_start", device_id, sdp=device.localDescription.sdp), ws)

    accepted = ws.last("voice_call_accepted")
    assert accepted is not None, f"没拿到 answer,回包是: {ws.sent}"
    await device.setRemoteDescription(RTCSessionDescription(sdp=accepted["sdp"], type="answer"))
    return accepted


@_needs_webrtc
async def test_watch_audio_really_reaches_the_provider_through_the_gateway(
    monkeypatch: Any, fake_session: FakeDuplexSession
):
    """核心断言:手表说话 → 真 SDP 协商 → 真 Opus/ICE → 落到 session.send_audio()。

    整条路只有两头是假的。中间的编码、传输、解码、重采样全是真跑的。
    """
    from aiortc import RTCPeerConnection

    ws = FakeWebSocket()
    device = RTCPeerConnection()
    device.addTrack(make_device_mic())
    try:
        accepted = await _negotiate(ws, device, "conn_up")
        assert accepted["call_id"], "接通必须带 call_id,否则后续 ICE/打断无处可寻"

        for _ in range(100):
            if fake_session.sent_audio:
                break
            await asyncio.sleep(0.1)

        assert fake_session.sent_audio, "手表音频没有到达 provider"
        heard = b"".join(fake_session.sent_audio)
        assert len(heard) > 0
        assert any(b != 0 for b in heard), "到达的全是静音 —— 等于没通"
    finally:
        await close_voice_route("conn_up")
        await device.close()


@_needs_webrtc
async def test_ai_audio_really_reaches_the_watch_through_the_gateway(monkeypatch: Any, fake_session: FakeDuplexSession):
    """反方向:provider 吐音频 → 出站轨 → 真 WebRTC → 手表侧解出非静音。"""
    import base64

    from aiortc import RTCPeerConnection

    ws = FakeWebSocket()
    device = RTCPeerConnection()
    device.addTransceiver("audio", direction="recvonly")
    got: asyncio.Future = asyncio.get_running_loop().create_future()

    @device.on("track")
    def _on_track(track: Any) -> None:
        if track.kind == "audio" and not got.done():
            got.set_result(track)

    try:
        await _negotiate(ws, device, "conn_down")
        track = await asyncio.wait_for(got, timeout=10.0)

        async def _keep_speaking() -> None:
            while True:
                fake_session.push(
                    DuplexEvent(
                        type=DuplexEventType.ASSISTANT_AUDIO_DELTA,
                        audio_b64=base64.b64encode(tone_pcm16(PROVIDER_RATE, 200)).decode(),
                    )
                )
                await asyncio.sleep(0.1)

        speaker = asyncio.create_task(_keep_speaking())
        try:
            loud = False
            for _ in range(120):
                frame = await asyncio.wait_for(track.recv(), timeout=5.0)
                if any(b != 0 for b in bytes(frame.planes[0])):
                    loud = True
                    break
            assert loud, "手表侧只收到静音 —— AI 的声音没走通"
        finally:
            speaker.cancel()
    finally:
        await close_voice_route("conn_down")
        await device.close()


@_needs_webrtc
async def test_session_events_are_pushed_to_the_watch(monkeypatch: Any, fake_session: FakeDuplexSession):
    """AI 的文字/状态要回推给手表 —— 这是"通话之外还能传上下文"那一半。"""
    from aiortc import RTCPeerConnection

    ws = FakeWebSocket()
    device = RTCPeerConnection()
    device.addTransceiver("audio", direction="recvonly")
    try:
        accepted = await _negotiate(ws, device, "conn_ev")
        fake_session.push(DuplexEvent(type=DuplexEventType.FINAL_TRANSCRIPT, text="你说的是:明天下午三点"))

        for _ in range(50):
            if ws.frames("voice_event"):
                break
            await asyncio.sleep(0.1)

        ev = ws.last("voice_event")
        assert ev is not None, "会话事件没有回推到设备"
        assert ev["call_id"] == accepted["call_id"]
        assert ev["text"] == "你说的是:明天下午三点"
        assert ev["event"] == DuplexEventType.FINAL_TRANSCRIPT.value
    finally:
        await close_voice_route("conn_ev")
        await device.close()


@_needs_webrtc
async def test_interrupt_from_the_watch_reaches_the_session(monkeypatch: Any, fake_session: FakeDuplexSession):
    """插话:手表一开口,AI 必须立刻闭嘴,而且已经缓冲的话也得丢掉。"""
    from aiortc import RTCPeerConnection

    ws = FakeWebSocket()
    device = RTCPeerConnection()
    device.addTransceiver("audio", direction="recvonly")
    try:
        await _negotiate(ws, device, "conn_int")
        call = get_call_registry().get("watch_01")
        assert call is not None
        await call.downlink_track.push_pcm16(tone_pcm16(48000, 500))

        await handle_message("conn_int", wire("voice_interrupt", reason="user_speech"), ws)

        assert fake_session.interrupted == 1, "打断没有传到 provider"
        assert call.downlink_track.buffered_bytes == 0, "缓冲没清干净,AI 会硬说完半句"
    finally:
        await close_voice_route("conn_int")
        await device.close()


# ---------------------------------------------------------------------------
# 4. 收尾:漏一次就是一条持续计费的会话
# ---------------------------------------------------------------------------


@_needs_webrtc
async def test_connection_teardown_ends_the_call(monkeypatch: Any, fake_session: FakeDuplexSession):
    """手表进隧道断线 → provider 那头的会话必须跟着关。

    漏掉这一步不会报任何错:通话看起来"结束"了,而 provider 侧的会话还挂着计费。
    """
    from aiortc import RTCPeerConnection

    ws = FakeWebSocket()
    device = RTCPeerConnection()
    device.addTransceiver("audio", direction="recvonly")
    try:
        await _negotiate(ws, device, "conn_tear")
        assert get_call_registry().active_count() == 1
        assert active_route_count() >= 1

        had = await close_voice_route("conn_tear")

        assert had is True
        assert fake_session.closed is True, "provider 会话没关 —— 这是一条在计费的泄漏"
        assert get_call_registry().active_count() == 0
    finally:
        await device.close()


@_needs_webrtc
async def test_device_hangup_closes_everything(monkeypatch: Any, fake_session: FakeDuplexSession):
    from aiortc import RTCPeerConnection

    ws = FakeWebSocket()
    device = RTCPeerConnection()
    device.addTransceiver("audio", direction="recvonly")
    try:
        await _negotiate(ws, device, "conn_bye")
        await handle_message("conn_bye", wire("voice_call_end", reason="user_hangup"), ws)

        assert fake_session.closed is True
        assert get_call_registry().active_count() == 0
    finally:
        await close_voice_route("conn_bye")
        await device.close()


async def test_hangup_is_idempotent_and_never_raises():
    """挂断跑在连接清理路径上 —— 它自己出错不能反过来把清理弄崩。"""
    route = VoiceCallRoute("watch_x", None)
    await route.hangup()
    await route.hangup(reason="again")
    assert route.in_call is False
    assert await close_voice_route("never_existed") is False


async def test_ice_before_call_and_bad_candidate_are_survivable(monkeypatch: Any):
    """单个候选加不进去不该毁掉整通电话:ICE 本来就是多候选择优。"""
    ws = FakeWebSocket()
    await handle_message("conn_ice", wire("voice_ice", candidate="candidate:garbage"), ws)
    await handle_message("conn_ice", wire("voice_ice", candidate=""), ws)
    assert ws.sent == [], "还没建立通话时的 ICE 不该产生任何回包"
    await close_voice_route("conn_ice")


@_needs_webrtc
async def test_real_connection_loop_ends_the_call_on_disconnect(monkeypatch: Any, fake_session: FakeDuplexSession):
    """跑真 ``handle_websocket``:手表断线后 provider 会话必须关掉。

    上一个用例直接调 ``close_voice_route``,只证明了那个函数是对的;证明不了连接循环
    真的会调它。把收尾漏在 ``finally`` 之外不会报任何错 —— 通话看起来结束了,而
    provider 侧的会话还挂着计费。所以这里从真的连接循环进,让它真的断给我看。
    """
    from aiortc import RTCPeerConnection
    from fastapi import WebSocketDisconnect

    device = RTCPeerConnection()
    device.addTransceiver("audio", direction="recvonly")
    offer = await device.createOffer()
    await device.setLocalDescription(offer)

    frames = [json.dumps(wire("voice_call_start", sdp=device.localDescription.sdp))]

    class LoopWebSocket(FakeWebSocket):
        async def accept(self) -> None:
            pass

        async def receive_text(self) -> str:
            if frames:
                return frames.pop(0)
            raise WebSocketDisconnect(code=1006)

    ws = LoopWebSocket()
    try:
        await handle_websocket(ws, "conn_loop")

        assert ws.last("voice_call_accepted") is not None, f"通话没接通,回包是 {ws.sent}"
        assert fake_session.closed is True, "断线后 provider 会话没关 —— 这是一条在计费的泄漏"
        assert get_call_registry().active_count() == 0
        assert active_route_count() == 0, "连接级路由表没清干净"
    finally:
        await close_voice_route("conn_loop")
        await device.close()
