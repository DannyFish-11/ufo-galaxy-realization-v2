"""core/voice_call_bridge.py —— 设备 WebRTC 音频 ↔ 双工语音会话的桥。

这一层解决什么
--------------
:mod:`core.voice_duplex_session` 已经能和 provider 维持一条持续的双工语音会话,但它
今天只服务**本机麦克风**:音频来自 ``audio_capture_service`` + ``sounddevice``,下行
由绑死本机扬声器的 ``PcmPlayer`` 播出。设备(手表/手机)侧没有任何上行音频的入口 ——
AIP 协议里原本连一个音频消息类型都没有。

本模块补的就是中间那一段:把设备的 **WebRTC 音频轨**接到 ``DuplexSession`` 的
``send_audio()``,再把 ``events()`` 里的下行音频喂回一条**出站** WebRTC 轨。
``PcmPlayer`` 在这条路上完全不出现 —— 手表的声音不该从服务器的扬声器里出来。

为什么媒体走 WebRTC 而不是 AIP WebSocket
----------------------------------------
AIP WebSocket 建立在 TCP 上。丢一个包,它后面的所有数据都被堵住(队头阻塞),而重传
回来的是**过期音频** —— 实时语音里迟到的音频没有价值,只会把延迟越堆越高。WebRTC
走 UDP:丢了就丢了,配合抖动缓冲与丢包补偿,听感上只是一瞬轻微失真。

手表恰恰是这件事上最差的设备:天线小、贴在手腕上、跟着人移动,最容易落在弱信号下;
而独立流量(LTE)场景网络更不可控。所以媒体面必须是 WebRTC,信令与文字事件才留在 AIP。

诚实边界
--------
* ``aiortc`` 是**可选依赖**(``requirements.txt`` 里注释着)。没装时本模块的导入不会
  炸,但 :func:`webrtc_available` 返回 False,通话请求会被如实拒绝并说明原因 ——
  绝不静默假装接通。
* 真 provider 连接在本仓测试环境里无法验证(没有 key、没有出网)。可验证的是重采样、
  轨道编解码、会话生命周期,以及**跑在真 aiortc 上的端到端回环**:两个真的
  ``RTCPeerConnection`` 对接,音频真的编码、传输、解码。那不是 mock。
"""

from __future__ import annotations

import asyncio
import base64
import fractions
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("Galaxy.VoiceCallBridge")

#: 出站轨每帧的时长(毫秒)。20ms 是 WebRTC/Opus 的事实标准分包长度:再短包头开销占比
#: 陡增,再长则每丢一个包造成的空洞更明显。
FRAME_MS = 20

#: 出站轨的采样率。48kHz 是 WebRTC 的原生采样率,选它可以让出站方向**完全不重采样**
#: (provider 给什么我们只做一次上采样),少一次转换就少一处失真与延迟。
OUTBOUND_RATE = 48000

#: 下行缓冲上限(秒)。满了丢**最旧**的:过期音频没有价值,而阻塞写入会把整个事件
#: 循环连带上行一起卡住。
_DOWNLINK_BUFFER_SEC = 1.5


def webrtc_available() -> Optional[str]:
    """WebRTC 依赖是否就绪。就绪返回 None,否则返回**人能看懂的原因**。

    返回原因而不是布尔:"通话建不起来"如果只留一个 False,排查时无从下手 ——
    是没装 aiortc,还是装了但 PyAV 坏了,处置完全不同。
    """
    try:
        import aiortc  # noqa: F401
        import av  # noqa: F401
    except ImportError as exc:
        return f"WebRTC 依赖未安装({exc.name});安装 aiortc 后重启网关"
    return None


# ---------------------------------------------------------------------------
# 重采样
# ---------------------------------------------------------------------------


class _Resampler:
    """入站 48kHz 立体声 → provider 要的单声道 PCM16。

    独立成类而不是写在泵里:重采样是这条链路上唯一会**改变样本**的一步,出问题时
    (音调不对、变速、爆音)需要能单独喂已知输入去比对输出。
    """

    def __init__(self, target_rate: int) -> None:
        from av.audio.resampler import AudioResampler

        self.target_rate = int(target_rate)
        self._r = AudioResampler(format="s16", layout="mono", rate=self.target_rate)

    def to_pcm16(self, frame: Any) -> bytes:
        """一个 ``av.AudioFrame`` → 裸 PCM16 字节。"""
        out = bytearray()
        for resampled in self._r.resample(frame):
            out += bytes(resampled.planes[0])
        return bytes(out)


# ---------------------------------------------------------------------------
# 出站轨:把 provider 的下行音频变成 WebRTC 音频轨
# ---------------------------------------------------------------------------


def _make_downlink_track_class() -> type:
    """延迟构造出站轨类型。

    ``MediaStreamTrack`` 只有 import 了 aiortc 才存在,而本模块必须在没装 aiortc 时
    也能被导入(否则整个网关起不来)。所以基类在函数里才解析。
    """
    from aiortc.mediastreams import MediaStreamTrack

    class DownlinkAudioTrack(MediaStreamTrack):
        """一条出站音频轨,声音来自 ``DuplexSession`` 的下行事件。

        为什么要自己按时间产帧
        ----------------------
        aiortc 会尽可能快地调用 ``recv()``。如果缓冲里没数据就一直等,轨会停;如果有
        多少给多少,就会瞬间把几秒钟的音频塞进去,对端听到的是加速播放。所以这里按
        **墙钟节拍**产帧:到点了就给一帧,缓冲空就给一帧静音。

        静音而不是阻塞,是因为 WebRTC 的音频轨一旦断流,对端的抖动缓冲会认为链路出了
        问题;持续的静音帧则是完全正常的"对方没说话"。
        """

        kind = "audio"

        def __init__(self, sample_rate: int = OUTBOUND_RATE) -> None:
            super().__init__()
            self.sample_rate = int(sample_rate)
            self.samples_per_frame = int(self.sample_rate * FRAME_MS / 1000)
            self._buf = bytearray()
            self._lock = asyncio.Lock()
            self._pts = 0
            self._start: Optional[float] = None
            self._max_bytes = int(self.sample_rate * 2 * _DOWNLINK_BUFFER_SEC)
            self.dropped_bytes = 0

        async def push_pcm16(self, pcm: bytes) -> None:
            """追加一段 PCM16(单声道,本轨采样率)。缓冲满则丢最旧的。"""
            if not pcm:
                return
            async with self._lock:
                self._buf += pcm
                excess = len(self._buf) - self._max_bytes
                if excess > 0:
                    del self._buf[:excess]
                    self.dropped_bytes += excess
                    logger.warning("下行缓冲溢出,丢弃最旧 %d 字节(累计 %d)", excess, self.dropped_bytes)

        async def clear(self) -> None:
            """清空未播出的下行音频 —— barge-in 时用。

            打断的语义是"立刻闭嘴"。只让服务端停止生成是不够的:缓冲里还排着好几百
            毫秒已经生成好的音频,不清掉的话用户会听见 AI 又硬说完半句才停。
            """
            async with self._lock:
                self._buf.clear()

        async def recv(self) -> Any:
            import av

            if self._start is None:
                self._start = time.monotonic()

            # 按墙钟节拍等到这一帧该出的时刻。
            target = self._start + (self._pts / self.sample_rate)
            delay = target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

            need = self.samples_per_frame * 2  # s16 单声道
            async with self._lock:
                if len(self._buf) >= need:
                    chunk = bytes(self._buf[:need])
                    del self._buf[:need]
                else:
                    chunk = bytes(self._buf) + b"\x00" * (need - len(self._buf))
                    self._buf.clear()

            frame = av.AudioFrame(format="s16", layout="mono", samples=self.samples_per_frame)
            frame.planes[0].update(chunk)
            frame.sample_rate = self.sample_rate
            frame.pts = self._pts
            frame.time_base = fractions.Fraction(1, self.sample_rate)
            self._pts += self.samples_per_frame
            return frame

    return DownlinkAudioTrack


# ---------------------------------------------------------------------------
# 一通电话
# ---------------------------------------------------------------------------


@dataclass
class VoiceCallStats:
    """一通电话的可观测量。排查"听不见/说不出"时,这几个数就是第一手判据。"""

    uplink_frames: int = 0
    uplink_bytes: int = 0
    downlink_chunks: int = 0
    downlink_bytes: int = 0
    events: Dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def note_event(self, name: str) -> None:
        self.events[name] = self.events.get(name, 0) + 1


class VoiceCall:
    """一通设备语音通话的完整生命周期。

    职责边界刻意收窄:本类只负责**把音频接起来、把事件转出去**。它不碰信令传输
    (那是网关路由的事)、不碰 provider 协议(那是 ``DuplexSession`` 的事)。
    """

    def __init__(
        self,
        device_id: str,
        session: Any,
        *,
        call_id: str = "",
        send_event: Optional[Callable[[str, str, str], Any]] = None,
    ) -> None:
        self.device_id = device_id
        self.call_id = call_id or f"call_{uuid.uuid4().hex[:10]}"
        self.session = session
        self.stats = VoiceCallStats()
        self._send_event = send_event
        self._uplink_task: Optional[asyncio.Task] = None
        self._downlink_task: Optional[asyncio.Task] = None
        self._closed = False
        rate = int(getattr(getattr(session, "config", None), "sample_rate", 16000) or 16000)
        self._resampler = _Resampler(rate)
        self.downlink_track = _make_downlink_track_class()()

    # ── 上行 ────────────────────────────────────────────────────────────

    def attach_uplink(self, track: Any) -> None:
        """接上设备的入站音频轨,开始把它泵进 provider。"""
        if self._uplink_task is not None:
            logger.warning("call=%s 重复接入上行轨,忽略", self.call_id)
            return
        self._uplink_task = asyncio.create_task(self._pump_uplink(track))

    async def _pump_uplink(self, track: Any) -> None:
        from aiortc.mediastreams import MediaStreamError

        try:
            while not self._closed:
                frame = await track.recv()
                pcm = self._resampler.to_pcm16(frame)
                if not pcm:
                    continue
                self.stats.uplink_frames += 1
                self.stats.uplink_bytes += len(pcm)
                await self.session.send_audio(pcm)
        except MediaStreamError:
            # 对端停止发送 —— 正常挂断路径,不是错误。
            logger.info("call=%s 上行轨结束", self.call_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("call=%s 上行泵异常: %s", self.call_id, exc)

    # ── 下行 ────────────────────────────────────────────────────────────

    def start_downlink(self) -> None:
        """开始把会话事件转成音频帧与 AIP 事件。"""
        if self._downlink_task is None:
            self._downlink_task = asyncio.create_task(self._pump_downlink())

    async def _pump_downlink(self) -> None:
        try:
            async for ev in self.session.events():
                if self._closed:
                    break
                name = getattr(ev.type, "value", str(ev.type))
                self.stats.note_event(name)

                if name == "assistant_audio_delta" and ev.audio_b64:
                    pcm = base64.b64decode(ev.audio_b64)
                    self.stats.downlink_chunks += 1
                    self.stats.downlink_bytes += len(pcm)
                    await self.downlink_track.push_pcm16(self._upsample_for_track(pcm))
                    continue

                # 用户开口 → 立刻清掉还没播出的 AI 音频。
                # 只让服务端停止生成不够:缓冲里排着的几百毫秒会让 AI 硬说完半句。
                if name == "user_speech_started":
                    await self.downlink_track.clear()

                await self._emit(name, getattr(ev, "text", "") or "", getattr(ev, "error", "") or "")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("call=%s 下行泵异常: %s", self.call_id, exc)
            await self._emit("error", "", str(exc))

    def _upsample_for_track(self, pcm: bytes) -> bytes:
        """provider 采样率 → 出站轨采样率(48k)。整数倍时做零阶保持,否则线性插值。

        不引入 numpy:这条路径在网关进程里每 20ms 跑一次,而 numpy 在本仓是可选依赖 ——
        为一次上采样把它变成必需,不划算。
        """
        src = self._resampler.target_rate
        dst = self.downlink_track.sample_rate
        if src == dst or not pcm:
            return pcm
        import array

        samples = array.array("h")
        samples.frombytes(pcm[: len(pcm) // 2 * 2])
        ratio = dst / src
        out = array.array("h", bytes(int(len(samples) * ratio) * 2))
        n_out = len(out)
        for i in range(n_out):
            pos = i / ratio
            lo = int(pos)
            if lo + 1 < len(samples):
                frac = pos - lo
                out[i] = int(samples[lo] * (1.0 - frac) + samples[lo + 1] * frac)
            elif samples:
                out[i] = samples[min(lo, len(samples) - 1)]
        return out.tobytes()

    async def _emit(self, event: str, text: str, error: str) -> None:
        if self._send_event is None:
            return
        try:
            result = self._send_event(event, text, error)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            logger.debug("call=%s 事件回调失败(不影响通话): %s", self.call_id, exc)

    # ── 打断与收尾 ──────────────────────────────────────────────────────

    async def interrupt(self, reason: str = "user_speech") -> None:
        """barge-in:让服务端停口,并清掉本地还没播出的音频。"""
        await self.downlink_track.clear()
        try:
            await self.session.interrupt()
        except Exception as exc:  # noqa: BLE001
            logger.warning("call=%s 打断失败: %s", self.call_id, exc)
        logger.info("call=%s 已打断(%s)", self.call_id, reason)

    async def close(self, reason: str = "user_hangup") -> None:
        """挂断。幂等、永不抛出。

        **必须关掉 provider 会话**:设备掉线、进程被杀、Wi-Fi 切换都会走到这里,漏关
        一次就是那头挂着一条会话继续计费,而且没有任何报错提示。
        """
        if self._closed:
            return
        self._closed = True
        for task in (self._uplink_task, self._downlink_task):
            if task is not None and not task.done():
                task.cancel()
        try:
            await self.session.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("call=%s 关闭会话失败: %s", self.call_id, exc)
        try:
            self.downlink_track.stop()
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "call=%s 已挂断(%s) 上行 %d 帧/%d 字节,下行 %d 块/%d 字节,事件 %s",
            self.call_id,
            reason,
            self.stats.uplink_frames,
            self.stats.uplink_bytes,
            self.stats.downlink_chunks,
            self.stats.downlink_bytes,
            self.stats.events,
        )

    @property
    def closed(self) -> bool:
        return self._closed


# ---------------------------------------------------------------------------
# 通话注册表:一台设备一通电话
# ---------------------------------------------------------------------------


class VoiceCallRegistry:
    """进程内的在通电话表。

    一台设备同时只允许一通:手表上不存在"多方通话"这个交互,而允许多通的直接后果是
    用户连点两次就开了两条 provider 会话 —— 两倍计费,且两条都在对着同一个麦克风。
    """

    def __init__(self) -> None:
        self._calls: Dict[str, VoiceCall] = {}
        self._lock = asyncio.Lock()

    async def put(self, call: VoiceCall) -> Optional[VoiceCall]:
        """登记一通电话;若该设备已有在通的,**先挂掉旧的**并返回它。"""
        async with self._lock:
            old = self._calls.get(call.device_id)
            self._calls[call.device_id] = call
        if old is not None:
            logger.info("device=%s 已有在通电话 %s,先挂断", call.device_id, old.call_id)
            await old.close(reason="superseded")
        return old

    def get(self, device_id: str) -> Optional[VoiceCall]:
        return self._calls.get(device_id)

    async def end(self, device_id: str, reason: str = "user_hangup") -> bool:
        """挂断某设备的电话。没有在通的返回 False。"""
        async with self._lock:
            call = self._calls.pop(device_id, None)
        if call is None:
            return False
        await call.close(reason=reason)
        return True

    async def end_all(self, reason: str = "shutdown") -> int:
        async with self._lock:
            calls = list(self._calls.values())
            self._calls.clear()
        for c in calls:
            await c.close(reason=reason)
        return len(calls)

    def active_count(self) -> int:
        return len(self._calls)


_registry: Optional[VoiceCallRegistry] = None


def get_call_registry() -> VoiceCallRegistry:
    global _registry
    if _registry is None:
        _registry = VoiceCallRegistry()
    return _registry
