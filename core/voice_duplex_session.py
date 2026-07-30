"""core/voice_duplex_session.py —— 双工语音会话(持续上行 + 持续下行)。

这一层解决什么
--------------
现有语音链路是**回合制**的:麦克风攒够一段 → Whisper 整段转写 → 大脑生成整段回复 →
TTS 整段合成播放。每一步都要等上一步结束,所以"同一时刻边说边听"在架构上就不可能 ——
不是调参问题,是拓扑问题。

双工会话把这条链路换成**一条持续开着的连接**:音频不断往上走,音频/文字不断往下来,
两个方向互不阻塞。用户说到一半模型就能开始应答,模型说到一半用户插话也能立刻被听见。

三层的分工(与已落地的两层是叠加关系,不是替代)
------------------------------------------------
* ``acoustic_echo_canceller`` —— 信号层:把扬声器的声音从麦克风里减掉。**双工比回合制
  更需要它**:回合制下 AI 说话时麦克风的内容最终会被丢掉,双工下那些字节会实时上行进
  模型,不做 AEC 等于让模型一直听见自己在说话。
* ``voice_echo_guard`` —— 文本层:兜住 AEC 消不掉的非线性残余回声。
* 本模块 —— 传输/编排层:让"同时"这件事在拓扑上成为可能。

诚实边界
--------
* **默认关闭**(``GALAXY_VOICE_DUPLEX=0``)。它需要一个支持 realtime 的 provider 与
  对应的 key;默认打开会让所有没配 key 的部署直接失去语音功能。这是刻意的保守默认,
  不是"没接上"—— 接线在 ``VoiceLoop.start()`` 里,开关一开就走这条路(见
  ``tests/test_voice_duplex_session.py::TestVoiceLoopWiring``)。
* **真实 provider 连接在本仓库的测试环境里无法验证**(没有 key、没有出网)。可验证的是
  协议编解码(抽成纯函数)、会话状态机、以及跑在**本地真 WebSocket 服务端**上的完整
  会话流程 —— 那不是 mock,是真的建连、真的收发帧。
* 只实现了 OpenAI Realtime 的帧格式适配器。Gemini Live 的 ``bidiGenerateContent`` 帧形状
  不同,留了 ``ProtocolAdapter`` 接口但**没有**实现 —— 没实现就不假装支持。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.VoiceDuplex")

_BACKGROUND_TASKS: set = set()

#: 下行事件队列上限。满了丢**最旧**的:双工场景里过期的音频块没有价值,
#: 而阻塞上行会直接毁掉实时性。
_EVENT_QUEUE_MAX = 256


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")


def duplex_enabled() -> bool:
    """双工语音是否启用。**默认关闭** —— 它需要 realtime provider 与 key。"""
    return _flag("GALAXY_VOICE_DUPLEX", "0")


class DuplexEventType(str, Enum):
    """下行事件类型(provider 无关)。"""

    SESSION_OPEN = "session_open"
    USER_SPEECH_STARTED = "user_speech_started"  # 服务端 VAD 判定用户开口
    USER_SPEECH_STOPPED = "user_speech_stopped"
    PARTIAL_TRANSCRIPT = "partial_transcript"
    FINAL_TRANSCRIPT = "final_transcript"
    ASSISTANT_TEXT_DELTA = "assistant_text_delta"
    ASSISTANT_AUDIO_DELTA = "assistant_audio_delta"
    RESPONSE_DONE = "response_done"
    ERROR = "error"
    SESSION_CLOSED = "session_closed"


@dataclass
class DuplexEvent:
    """一条下行事件。``raw`` 保留原始帧,便于排查 provider 侧的意外字段。"""

    type: DuplexEventType
    text: str = ""
    audio_b64: str = ""
    error: str = ""
    ts: float = field(default_factory=time.time)
    raw: Optional[Dict[str, Any]] = field(default=None, repr=False)


@dataclass
class DuplexSessionConfig:
    """双工会话参数。

    ``api_key`` 刻意**不**带默认值也不从这里读环境变量 —— 由 ``from_env`` 统一负责,
    避免出现"某处忘了传 key 就静默用了空字符串去建连"。
    """

    url: str
    api_key: str
    model: str = "gpt-4o-realtime-preview"
    voice: str = "alloy"
    sample_rate: int = 16000
    instructions: str = ""
    #: 服务端 VAD 的静音判定阈值(毫秒)。双工下回合边界由服务端判,不再靠本地攒够时长。
    silence_ms: int = 500

    @classmethod
    def from_env(cls) -> Optional["DuplexSessionConfig"]:
        """从环境变量构造;缺 key 或缺 url 时返回 None 并**说明缺什么**。

        返回 None 而不是抛异常:双工默认关闭,缺配置是预期情形而非错误。但原因要能
        从日志里看到 —— 否则"开了开关却没生效"完全无从排查。
        """
        key = (os.getenv("GALAXY_REALTIME_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        url = (os.getenv("GALAXY_REALTIME_URL") or "").strip()
        model = (os.getenv("GALAXY_REALTIME_MODEL") or "gpt-4o-realtime-preview").strip()
        if not url:
            url = f"wss://api.openai.com/v1/realtime?model={model}"
        if not key:
            logger.warning(
                "双工语音已开启但缺少 API key(GALAXY_REALTIME_API_KEY 或 OPENAI_API_KEY)," "本次退回回合制语音链路。"
            )
            return None
        return cls(url=url, api_key=key, model=model)


# ── 协议适配:全部是纯函数,不碰网络,可完整单测 ────────────────────────────


class ProtocolAdapter:
    """provider 帧格式适配器。

    只有 OpenAI Realtime 一个实现。Gemini Live 的 ``bidiGenerateContent`` 帧形状不同,
    接口留在这里,但**没有实现** —— 没实现就不假装支持。
    """

    name = "abstract"

    def session_update(self, cfg: DuplexSessionConfig) -> Dict[str, Any]:
        raise NotImplementedError

    def audio_frame(self, pcm16: bytes) -> Dict[str, Any]:
        raise NotImplementedError

    def text_frame(self, text: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def interrupt_frame(self) -> Dict[str, Any]:
        raise NotImplementedError

    def decode(self, msg: Dict[str, Any]) -> Optional[DuplexEvent]:
        raise NotImplementedError

    def headers(self, cfg: DuplexSessionConfig) -> Dict[str, str]:
        raise NotImplementedError


class OpenAIRealtimeAdapter(ProtocolAdapter):
    """OpenAI Realtime(``wss://api.openai.com/v1/realtime``)的帧格式。"""

    name = "openai_realtime"

    def headers(self, cfg: DuplexSessionConfig) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {cfg.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

    def session_update(self, cfg: DuplexSessionConfig) -> Dict[str, Any]:
        session: Dict[str, Any] = {
            "modalities": ["text", "audio"],
            "voice": cfg.voice,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            # 服务端 VAD:双工下回合边界由服务端判。本地不再"攒够 3 秒再转写"——
            # 那正是回合制延迟的来源。
            "turn_detection": {
                "type": "server_vad",
                "silence_duration_ms": int(cfg.silence_ms),
            },
        }
        if cfg.instructions:
            session["instructions"] = cfg.instructions
        return {"type": "session.update", "session": session}

    def audio_frame(self, pcm16: bytes) -> Dict[str, Any]:
        return {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm16).decode("ascii"),
        }

    def text_frame(self, text: str) -> List[Dict[str, Any]]:
        return [
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            },
            {"type": "response.create"},
        ]

    def interrupt_frame(self) -> Dict[str, Any]:
        """双工下的 barge-in:让服务端**停止当前回复**,而不是本地掐断播放。

        回合制的 ``interrupt_speech()`` 只是停掉本地播放器,模型那边还在继续生成
        (token 照烧、上下文照涨)。双工下必须让服务端也停。
        """
        return {"type": "response.cancel"}

    _MAP = {
        "session.created": DuplexEventType.SESSION_OPEN,
        "session.updated": DuplexEventType.SESSION_OPEN,
        "input_audio_buffer.speech_started": DuplexEventType.USER_SPEECH_STARTED,
        "input_audio_buffer.speech_stopped": DuplexEventType.USER_SPEECH_STOPPED,
        "response.done": DuplexEventType.RESPONSE_DONE,
        "error": DuplexEventType.ERROR,
    }

    def decode(self, msg: Dict[str, Any]) -> Optional[DuplexEvent]:
        """把一帧服务端消息翻成 ``DuplexEvent``;不认识的帧返回 None(而不是报错)。

        provider 会不断加新事件类型,对未知帧报错会让会话动不动就断。未知帧只在
        debug 级别记一笔。
        """
        t = str(msg.get("type") or "")
        if not t:
            return None

        if t == "response.audio.delta":
            return DuplexEvent(DuplexEventType.ASSISTANT_AUDIO_DELTA, audio_b64=str(msg.get("delta") or ""), raw=msg)
        if t in ("response.text.delta", "response.audio_transcript.delta"):
            return DuplexEvent(DuplexEventType.ASSISTANT_TEXT_DELTA, text=str(msg.get("delta") or ""), raw=msg)
        if t == "conversation.item.input_audio_transcription.delta":
            return DuplexEvent(DuplexEventType.PARTIAL_TRANSCRIPT, text=str(msg.get("delta") or ""), raw=msg)
        if t == "conversation.item.input_audio_transcription.completed":
            return DuplexEvent(DuplexEventType.FINAL_TRANSCRIPT, text=str(msg.get("transcript") or ""), raw=msg)
        if t == "error":
            err = msg.get("error") or {}
            detail = err.get("message") if isinstance(err, dict) else str(err)
            return DuplexEvent(DuplexEventType.ERROR, error=str(detail or "unknown"), raw=msg)

        mapped = self._MAP.get(t)
        if mapped is not None:
            return DuplexEvent(mapped, raw=msg)
        logger.debug("双工会话:未识别的服务端帧类型 %s(已忽略)", t)
        return None


def get_adapter(name: str = "openai_realtime") -> ProtocolAdapter:
    if name == "openai_realtime":
        return OpenAIRealtimeAdapter()
    raise ValueError(f"未实现的双工 provider 适配器: {name}(目前只有 openai_realtime)")


# ── 会话 ─────────────────────────────────────────────────────────────────────


class DuplexSession:
    """一条持续开着的双工语音会话。

    用法::

        sess = DuplexSession(cfg)
        await sess.connect()
        await sess.send_audio(pcm16_bytes)      # 可以一直调,不阻塞下行
        async for ev in sess.events():
            ...
        await sess.close()

    上行与下行是**两个独立的协程**:下行有一个常驻读循环把帧解码后塞进队列,上行直接
    发送。这样"边说边听"在实现上才真的成立 —— 如果上行要等下行读完一帧,那还是回合制。
    """

    def __init__(self, config: DuplexSessionConfig, adapter: Optional[ProtocolAdapter] = None) -> None:
        self.config = config
        self.adapter = adapter or get_adapter()
        self._ws: Any = None
        self._reader: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_EVENT_QUEUE_MAX)
        self._connected = False
        self._closing = False
        # 观测
        self.frames_sent = 0
        self.frames_received = 0
        self.events_emitted = 0
        self.events_dropped = 0
        self.bytes_uplinked = 0
        self.last_error = ""

    # ── 生命周期 ──────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """建连并下发会话配置。返回是否成功;失败时如实记录原因,不抛出。"""
        if self._connected:
            return True
        try:
            import websockets
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"websockets_missing: {exc}"
            logger.warning("双工会话不可用(缺 websockets): %s", exc)
            return False
        try:
            self._ws = await websockets.connect(
                self.config.url,
                additional_headers=self.adapter.headers(self.config),
                max_size=16 * 1024 * 1024,
            )
            await self._send_json(self.adapter.session_update(self.config))
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"connect_failed: {exc}"
            logger.warning("双工会话建连失败,退回回合制语音: %s", exc)
            await self._hard_close()
            return False

        self._connected = True
        self._closing = False
        self._reader = asyncio.ensure_future(self._read_loop())
        _BACKGROUND_TASKS.add(self._reader)
        self._reader.add_done_callback(_BACKGROUND_TASKS.discard)
        logger.info("双工语音会话已建立(%s, model=%s)", self.adapter.name, self.config.model)
        return True

    async def close(self) -> None:
        """关闭会话。幂等、永不抛出。"""
        self._closing = True
        self._connected = False
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._hard_close()
        await self._emit(DuplexEvent(DuplexEventType.SESSION_CLOSED))

    async def _hard_close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("关闭双工连接失败(忽略): %s", exc)

    @property
    def connected(self) -> bool:
        return self._connected

    # ── 上行 ──────────────────────────────────────────────────────────────

    async def _send_json(self, payload: Dict[str, Any]) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
            self.frames_sent += 1
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"send_failed: {exc}"
            logger.debug("双工上行发送失败: %s", exc)
            return False

    async def send_audio(self, pcm16: bytes) -> bool:
        """上行一块 16-bit PCM。

        调用方**应当**送已经过 AEC 的音频:双工下这些字节会实时进模型,不做回声消除
        等于让模型一直听见自己在说话(比回合制更严重 —— 回合制下那段音频最终会被丢掉)。
        """
        if not pcm16 or not self._connected:
            return False
        ok = await self._send_json(self.adapter.audio_frame(pcm16))
        if ok:
            self.bytes_uplinked += len(pcm16)
        return ok

    async def send_text(self, text: str) -> bool:
        """上行一段文字(供面板/键盘输入与语音共用同一条会话)。"""
        if not text or not self._connected:
            return False
        ok = True
        for frame in self.adapter.text_frame(text):
            ok = await self._send_json(frame) and ok
        return ok

    async def interrupt(self) -> bool:
        """barge-in:让**服务端**停止当前回复。

        与回合制的 ``interrupt_speech()`` 有本质区别:那个只停本地播放器,模型那边还在
        继续生成(token 照烧、上下文照涨)。双工下必须让服务端也停。
        """
        if not self._connected:
            return False
        return await self._send_json(self.adapter.interrupt_frame())

    # ── 下行 ──────────────────────────────────────────────────────────────

    async def _emit(self, ev: DuplexEvent) -> None:
        """把事件塞进队列。满了丢**最旧**的 —— 过期音频块没有价值,而阻塞上行会毁掉
        实时性。丢弃有计数,不静默。"""
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self.events_dropped += 1
                self._queue.put_nowait(ev)
            except Exception:  # noqa: BLE001
                self.events_dropped += 1
                return
        self.events_emitted += 1

    async def _read_loop(self) -> None:
        """常驻下行读循环:收帧 → 解码 → 入队。与上行完全解耦。"""
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                self.frames_received += 1
                try:
                    msg = json.loads(raw)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("双工下行帧不是合法 JSON(忽略): %s", exc)
                    continue
                if not isinstance(msg, dict):
                    continue
                ev = self.adapter.decode(msg)
                if ev is None:
                    continue
                if ev.type is DuplexEventType.ERROR:
                    self.last_error = ev.error
                    logger.warning("双工会话服务端报错: %s", ev.error)
                # 把 AI 说出口的文字登记进反自激励门 —— 双工下同样需要:AEC 消不掉
                # 非线性残余回声,残余转写出来后仍要能判出"这是我自己说的"。
                if ev.type is DuplexEventType.ASSISTANT_TEXT_DELTA and ev.text:
                    self._note_spoken(ev.text)
                await self._emit(ev)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._closing:
                self.last_error = f"read_loop: {exc}"
                logger.warning("双工下行读循环异常结束: %s", exc)
        finally:
            self._connected = False

    @staticmethod
    def _note_spoken(text: str) -> None:
        try:
            from core.voice_echo_guard import note_utterance

            note_utterance(text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("双工:登记已说出口文本失败(非致命): %s", exc)

    async def events(self) -> AsyncIterator[DuplexEvent]:
        """异步迭代下行事件,直到会话关闭。"""
        while True:
            ev = await self._queue.get()
            yield ev
            if ev.type is DuplexEventType.SESSION_CLOSED:
                return

    async def next_event(self, timeout: Optional[float] = None) -> Optional[DuplexEvent]:
        """取一条事件;超时返回 None。供不想用异步迭代的调用方。"""
        try:
            if timeout is None:
                return await self._queue.get()
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    # ── 观测 ──────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "connected": self._connected,
            "adapter": self.adapter.name,
            "model": self.config.model,
            "frames_sent": self.frames_sent,
            "frames_received": self.frames_received,
            "events_emitted": self.events_emitted,
            "events_dropped": self.events_dropped,
            "bytes_uplinked": self.bytes_uplinked,
            "queue_depth": self._queue.qsize(),
            "last_error": self.last_error or None,
        }


async def open_duplex_session(
    config: Optional[DuplexSessionConfig] = None,
    adapter: Optional[ProtocolAdapter] = None,
) -> Optional[DuplexSession]:
    """按环境配置建立一条双工会话;不可用时返回 None(调用方退回回合制)。

    返回 None 的每种情形都有日志:开关没开、缺 key、建连失败 —— 否则"开了开关却没生效"
    完全无从排查。
    """
    if config is None:
        if not duplex_enabled():
            logger.debug("双工语音未启用(GALAXY_VOICE_DUPLEX 未开),走回合制链路")
            return None
        config = DuplexSessionConfig.from_env()
        if config is None:
            return None
    sess = DuplexSession(config, adapter=adapter)
    if not await sess.connect():
        return None
    return sess


def pcm16_from_float(samples: Any) -> bytes:
    """float32/float64 [-1,1] → 16-bit PCM 字节(上行格式)。

    限幅后再转,不做自动增益:溢出翻转会变成刺耳爆音,而且会污染模型的听觉输入。
    """
    import numpy as np

    arr = np.asarray(samples, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return b""
    return (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def float_from_pcm16(data: bytes) -> Any:
    """16-bit PCM 字节 → float32 [-1,1](下行播放/分析用)。"""
    import numpy as np

    if not data:
        return np.zeros(0, dtype=np.float32)
    return (np.frombuffer(data, dtype="<i2").astype(np.float32) / 32767.0).astype(np.float32)


#: 供 VoiceLoop 在双工模式下把上行音频接过去的回调类型
UplinkHook = Callable[[bytes], Any]


#: 下行播放缓冲上限(秒)。满了丢**最旧**的:过期音频没有价值,而让 play() 等待
#: 会把事件循环连带上行一起卡住。
_PLAYER_BUFFER_SEC = 2.0


class PcmPlayer:
    """下行原始 PCM 的播放器(回调驱动,``play()`` 绝不阻塞)。

    为什么不能用 ``OutputStream.write()``
    -------------------------------------
    双工下行是**连续的 PCM 流**,不是一个个音频文件,所以现有 TTS 引擎那套
    ``_play_audio(path)`` 用不上 —— 为每个 20ms 的音频块写一个临时文件再播,延迟和
    IO 开销都不可接受。

    但直接用 ``stream.write()`` 也不行:按 sounddevice 的契约它**会阻塞**到所有帧都写进
    设备缓冲为止。而 ``play()`` 是从 ``_duplex_downlink`` 里调的,跑在事件循环上 ——
    一阻塞,同一个循环上的**上行**也跟着停。那就等于用一个"实时"播放器把双工性质亲手
    毁掉:模型说话时用户的声音传不上去,退化成半双工。

    所以改成**回调驱动**:``sounddevice`` 的音频线程主动来取,``play()`` 只是往一个有界
    环形缓冲里追加,纯内存操作、不等待任何人。这也是音频输出的标准做法。

    没有 sounddevice / 没有输出设备时**如实不可用**并记一次 WARNING,不静默假装在播 ——
    "以为在说话其实一点声音都没有"是最难排查的一类症状。
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = int(sample_rate)
        self._stream: Any = None
        self._unavailable_reason = ""
        self._lock = threading.Lock()
        self._buf: Any = None  # numpy 1-D 待播样本
        self._np: Any = None
        self.blocks_played = 0
        self.blocks_dropped = 0
        self.samples_underrun = 0  # 缓冲空、只能输出静音的样本数(可听为卡顿)

    @property
    def _max_samples(self) -> int:
        return int(_PLAYER_BUFFER_SEC * self.sample_rate)

    def start(self) -> bool:
        if self._stream is not None:
            return True
        try:
            import numpy as np
            import sounddevice as sd

            self._np = np
            self._buf = np.zeros(0, dtype=np.float32)

            def _cb(outdata, frames, _time_info, status) -> None:  # noqa: ANN001
                # 音频线程:只做取数与补静音,绝不做 IO / 日志 / 加重锁
                if status:
                    pass
                with self._lock:
                    have = min(frames, self._buf.size)
                    if have:
                        outdata[:have, 0] = self._buf[:have]
                        self._buf = self._buf[have:]
                    if have < frames:
                        outdata[have:, 0] = 0.0
                        self.samples_underrun += frames - have

            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=_cb,
            )
            self._stream.start()
            logger.info("双工下行播放器已启动(回调驱动, sr=%d)", self.sample_rate)
            return True
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = str(exc)
            logger.warning("双工下行播放器不可用(模型的回复将听不到): %s", exc)
            self._stream = None
            return False

    def play(self, pcm16: bytes) -> bool:
        """把一块 PCM 追加到播放缓冲。**不阻塞**、永不抛出。"""
        if not pcm16:
            return False
        if self._stream is None or self._np is None:
            self.blocks_dropped += 1
            return False
        try:
            np = self._np
            samples = float_from_pcm16(pcm16)
            with self._lock:
                self._buf = np.concatenate((self._buf, samples))
                # 有界:生产快于消费时丢最旧的,而不是让 play() 等下去
                extra = self._buf.size - self._max_samples
                if extra > 0:
                    self._buf = self._buf[extra:]
                    self.blocks_dropped += 1
            self.blocks_played += 1
            return True
        except Exception as exc:  # noqa: BLE001
            self.blocks_dropped += 1
            logger.debug("双工下行入缓冲失败(丢弃本块): %s", exc)
            return False

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        with self._lock:
            if self._np is not None:
                self._buf = self._np.zeros(0, dtype=self._np.float32)
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("关闭双工播放器失败(忽略): %s", exc)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            buffered = int(self._buf.size) if self._buf is not None else 0
        return {
            "available": self._stream is not None,
            "unavailable_reason": self._unavailable_reason or None,
            "blocks_played": self.blocks_played,
            "blocks_dropped": self.blocks_dropped,
            "buffered_samples": buffered,
            "samples_underrun": self.samples_underrun,
        }
