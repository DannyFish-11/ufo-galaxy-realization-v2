"""High-level audio capture service for the Galaxy multimodal pipeline.

Wraps :class:`AudioIngestPipeline` and :class:`MultimodalIngressBus` to
provide a single entry point for starting/stopping microphone capture with
observability, runtime event emission, and a callback interface suitable
for ASR or agent consumption.

Usage::

    service = AudioCaptureService()
    service.add_asr_callback(my_asr_handler)   # (AudioState, SignalQuality) -> None
    await service.start()
    # ... later ...
    await service.stop()

Graceful degradation
--------------------
If ``sounddevice`` is not installed, :meth:`start` returns immediately
without raising.  Downstream consumers receive ``DEVICE_UNAVAILABLE``
quality signals.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, List, Optional

import numpy as np

if TYPE_CHECKING:  # 仅类型检查:WhisperASR 实际用时在方法内懒导入(见 add_whisper_callback)
    from core.asr import WhisperASR

from .audio_features import AudioState
from .audio_ingest import AudioIngestConfig, AudioIngestPipeline
from .multimodal_events import (
    AudioQualityDegradedEvent,
    AudioStreamErrorEvent,
    AudioStreamStartedEvent,
    AudioStreamStoppedEvent,
    MultimodalEvent,
)
from .signal_quality import SignalQuality

logger = logging.getLogger(__name__)

# Latency threshold above which a quality-degraded event is emitted (ms)
_LATENCY_WARNING_MS: float = 200.0

# Default ASR buffer duration in seconds
_ASR_BUFFER_DURATION_S: float = 3.0


@dataclass
class AudioCaptureConfig:
    """Configuration for :class:`AudioCaptureService`.

    Attributes
    ----------
    sample_rate         Microphone sample rate in Hz.
    chunk_duration_ms   Target chunk duration in milliseconds.
    device              sounddevice device index (None = system default).
    latency_warning_ms  Threshold above which audio latency is flagged.
    asr_buffer_duration_s  Duration of audio to buffer before ASR (seconds).
    trace_id            Optional trace correlation ID passed to events.
    runtime_session_id  Optional runtime session ID passed to events.
    """

    sample_rate: int = 16000
    chunk_duration_ms: int = 100
    device: Optional[int] = None
    latency_warning_ms: float = _LATENCY_WARNING_MS
    asr_buffer_duration_s: float = _ASR_BUFFER_DURATION_S
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None


class AudioCaptureService:
    """High-level microphone capture service with runtime event emission.

    The service owns an :class:`AudioIngestPipeline` and acts as its primary
    consumer.  It forwards audio frames to registered ASR/agent callbacks and
    emits structured :class:`MultimodalEvent` objects for observability.

    Thread safety
    -------------
    :meth:`start` and :meth:`stop` must be called from within an asyncio
    event loop.  :meth:`add_asr_callback` and :meth:`add_event_listener` are
    safe to call before :meth:`start`.
    """

    def __init__(self, config: Optional[AudioCaptureConfig] = None) -> None:
        self.config = config or AudioCaptureConfig()
        self._pipeline = AudioIngestPipeline(
            config=AudioIngestConfig(
                sample_rate=self.config.sample_rate,
                chunk_duration_ms=self.config.chunk_duration_ms,
                device=self.config.device,
            )
        )
        self._asr_callbacks: List[Callable[[AudioState, SignalQuality], None]] = []
        self._event_listeners: List[Callable[[MultimodalEvent], None]] = []
        self._task: Optional[asyncio.Task] = None

        # Metrics
        self._chunks_processed: int = 0
        self._start_ts: Optional[float] = None
        # 语音输入链路诊断计数(供可见的一次性诊断看门狗判断"死在哪一步"):
        #   收到音频块 / 其中被 VAD 判为"说话"的块 / 成功转写出文字的次数。
        self._chunks_seen: int = 0
        self._speech_chunks: int = 0
        self._transcripts: int = 0
        self._diag_task: Optional[asyncio.Task] = None

        # Voice input callback — invoked when ASR produces text
        self.on_voice_input: Optional[Callable[[str], None]] = None

        # 主事件循环引用——ASR 转写现在跑在线程池 worker 线程里(见
        # add_whisper_callback),worker 线程没有"当前运行的事件循环"，
        # asyncio.create_task() 在那里会直接 RuntimeError。start() 里捕获，
        # _emit_voice_input 据此用 run_coroutine_threadsafe 跨线程安全调度。
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Wire internal callback to pipeline
        self._pipeline.add_callback(self._on_audio_chunk)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if sounddevice is importable on this host."""
        return self._pipeline.is_available

    def add_asr_callback(self, cb: Callable[[AudioState, SignalQuality], None]) -> None:
        """Register a callback invoked with each new :class:`AudioState`.

        Suitable for wiring directly into an ASR or agent pipeline.
        """
        self._asr_callbacks.append(cb)

    def add_event_listener(self, listener: Callable[[MultimodalEvent], None]) -> None:
        """Register a listener for :class:`MultimodalEvent` objects."""
        self._event_listeners.append(listener)

    def get_latest(self) -> tuple:
        """Return ``(AudioState | None, SignalQuality)`` for the last chunk."""
        return self._pipeline.get_latest()

    # ------------------------------------------------------------------
    # Whisper ASR integration
    # ------------------------------------------------------------------

    def add_whisper_callback(
        self,
        whisper_asr: "WhisperASR",  # type: ignore[name-defined]
        language: str = "zh",
    ) -> None:
        """Register Whisper ASR callback with automatic audio buffering.

        Buffers audio chunks and runs transcription when enough audio
        has accumulated or speech ends.

        Args:
            whisper_asr: WhisperASR instance for transcription.
            language: Language code for ASR (default "zh" for Chinese).

        Example::

            from core.asr import WhisperASR
            asr = WhisperASR(model_size="small")
            service.add_whisper_callback(asr, language="zh")
        """
        buffer: List[np.ndarray] = []
        buffer_duration: float = 0.0  # accumulated audio duration in seconds
        asr_buffer_s = self.config.asr_buffer_duration_s

        def _asr_callback(state: AudioState, quality: SignalQuality) -> None:
            nonlocal buffer, buffer_duration

            # Skip if audio quality is not usable or no samples
            if not quality.is_usable or len(state.samples) == 0:
                return

            self._chunks_seen += 1  # 诊断:确有音频块流进来(麦克风采集在工作)

            # Only buffer when speech is detected
            if state.is_speaking:
                self._speech_chunks += 1  # 诊断:VAD 判定为"说话"
                buffer.append(state.samples.copy())
                buffer_duration += len(state.samples) / state.sample_rate

            # Transcribe when buffer is full or speech ends
            if buffer_duration >= asr_buffer_s or (not state.is_speaking and buffer_duration > 0.5):
                audio_np = np.concatenate(buffer)
                buffer = []
                buffer_duration = 0.0

                # 修复(语音链路稳定性排查):whisper_asr.transcribe() 是同步、
                # CPU 密集调用(几百毫秒到数秒不等)。这个回调本身是从
                # AudioIngestPipeline._process_chunk() 的异步主循环里【同步】
                # 调用的——之前直接在这里跑 transcribe()，等于把转写工作压在
                # 和 FastAPI 服务共用的同一个事件循环线程上：每次用户说完一句
                # 话触发转写，HTTP/WS/面板轮询等所有其它并发工作都会被真实冻结
                # 相应时长，且没有任何用户可见提示。这里改成丢进线程池执行，
                # 事件循环不再被阻塞；buffer 的读取/清空仍在本次回调内同步完成，
                # 不影响后续音频块的正确累积。
                def _transcribe_in_thread(_audio=audio_np, _sr=state.sample_rate) -> None:
                    try:
                        text = whisper_asr.transcribe(_audio, sample_rate=_sr, language=language)
                        if text:
                            self._transcripts += 1  # 诊断:成功转写出文字
                            logger.info("ASR result: %s", text)
                            self._emit_voice_input(text)
                    except Exception as exc:
                        logger.warning("Whisper ASR error: %s", exc)

                try:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(None, _transcribe_in_thread)
                except RuntimeError:
                    # 理论上不会发生(本回调总是从运行中的事件循环里被同步调用)，
                    # 保守兜底：退回原来的同步调用，至少不丢失这段转写。
                    _transcribe_in_thread()

        self.add_asr_callback(_asr_callback)
        logger.info(
            "Whisper ASR callback registered (buffer=%.1fs, lang=%s)",
            asr_buffer_s,
            language,
        )

    def _emit_voice_input(self, text: str) -> None:
        """Emit a voice input event to the registered callback.

        可能从主事件循环线程调用，也可能从 ASR 线程池 worker 线程调用(见
        add_whisper_callback 的转写现在跑在 run_in_executor 里)——两种情况
        都要能正确调度 async 回调，不能假设"当前线程就是事件循环线程"。
        """
        if self.on_voice_input is None:
            return
        try:
            if asyncio.iscoroutinefunction(self.on_voice_input):
                try:
                    # 在事件循环线程里调用:直接 create_task。
                    asyncio.get_running_loop().create_task(self.on_voice_input(text))  # noqa: RUF006
                except RuntimeError:
                    # 在 worker 线程里调用(无运行中的事件循环):跨线程安全调度
                    # 到 start() 时捕获的主循环。
                    if self._loop is not None and not self._loop.is_closed():
                        asyncio.run_coroutine_threadsafe(self.on_voice_input(text), self._loop)
                    else:
                        logger.debug("Voice input callback dropped: no usable event loop")
            else:
                self.on_voice_input(text)
        except Exception as exc:
            logger.debug("Voice input callback error: %s", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start microphone capture in a background task.

        Returns immediately.  If already running, this is a no-op.
        """
        if self._task is not None and not self._task.done():
            logger.debug("AudioCaptureService already running")
            return

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        self._start_ts = time.monotonic()
        self._chunks_processed = 0
        self._chunks_seen = 0
        self._speech_chunks = 0
        self._transcripts = 0

        if not self.is_available:
            logger.warning("AudioCaptureService: sounddevice unavailable; skipping start")
            return

        self._emit_event(
            AudioStreamStartedEvent(
                trace_id=self.config.trace_id,
                runtime_session_id=self.config.runtime_session_id,
                sample_rate=self.config.sample_rate,
                chunk_duration_ms=self.config.chunk_duration_ms,
                device=self.config.device,
            )
        )
        self._task = asyncio.create_task(self._run(), name="audio_capture_service")
        self._diag_task = asyncio.create_task(self._voice_input_watchdog(), name="voice_input_watchdog")
        logger.info(
            "AudioCaptureService started (sr=%d, chunk_ms=%d)",
            self.config.sample_rate,
            self.config.chunk_duration_ms,
        )

    async def _voice_input_watchdog(self) -> None:
        """一次性【可见】诊断:启动 N 秒后按计数如实说清语音输入链路死在哪一步。

        真机排查痛点:整条链路只在 INFO/DEBUG 打日志,而用户控制台是 WARNING 级 →
        麦克风就算在工作也【看不到】,坏了更是"死得不明不白"。这里用 WARNING 级打一条
        (用户一定看得见),把黑盒变白盒:
          - 一个音频块都没收到 → 采集没打开(默认录音设备/权限/独占)。
          - 收到音频但 VAD 从未判"说话" → 麦克风增益太低/选错设备/环境太静。
          - 判过"说话"但没转写出文字 → Whisper 模型/语言问题。
          - 有转写 → 语音输入正常(如实报一次,消除"到底通没通"的疑虑)。
        GALAXY_VOICE_DIAG_S=0 可关;默认 20 秒。
        """
        try:
            delay = float(os.environ.get("GALAXY_VOICE_DIAG_S", "20") or "20")
        except (TypeError, ValueError):
            delay = 20.0
        if delay <= 0:
            return
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._transcripts > 0:
            logger.warning(
                "🎙️ 语音输入正常:%.0fs 内已转写 %d 段(收到音频块 %d、其中说话 %d)。",
                delay,
                self._transcripts,
                self._chunks_seen,
                self._speech_chunks,
            )
        elif self._chunks_seen == 0:
            logger.warning(
                "🎙️ 语音输入无效:%.0fs 内【麦克风一个音频块都没收到】——采集未打开。"
                "检查 Windows 声音设置→录制→默认麦克风(是否被禁用/拔出/被其它程序独占),"
                "或授予麦克风权限后重启。",
                delay,
            )
        elif self._speech_chunks == 0:
            logger.warning(
                "🎙️ 语音输入无效:%.0fs 内收到音频(%d 块)但【VAD 从未判定为说话】——"
                "麦克风增益极低/选错了输入设备/太安静。VAD 已自适应噪声底,若仍不触发,"
                "请在系统里调高该麦克风输入音量,或设 GALAXY_VAD_MIN_FLOOR=0.001(更灵敏)后重跑。",
                delay,
                self._chunks_seen,
            )
        else:
            logger.warning(
                "🎙️ 语音输入卡在转写:%.0fs 内检测到说话(%d 块)但【没转写出文字】——"
                "Whisper 模型/语言问题。可试 GALAXY_WHISPER_MODEL=small 提升准确度。",
                delay,
                self._speech_chunks,
            )

    async def stop(self) -> None:
        """Stop microphone capture and await the background task."""
        self._pipeline.stop()
        if self._diag_task is not None:
            self._diag_task.cancel()
            self._diag_task = None
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

        duration_s = time.monotonic() - self._start_ts if self._start_ts is not None else 0.0
        self._emit_event(
            AudioStreamStoppedEvent(
                trace_id=self.config.trace_id,
                runtime_session_id=self.config.runtime_session_id,
                reason="stopped",
                total_chunks_processed=self._chunks_processed,
                total_duration_s=duration_s,
            )
        )
        logger.info(
            "AudioCaptureService stopped (chunks=%d, duration=%.1fs)",
            self._chunks_processed,
            duration_s,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Wrap pipeline.run() and emit error events on failure."""
        try:
            await self._pipeline.run()
        except Exception as exc:
            logger.warning("AudioCaptureService pipeline error: %s", exc)
            self._emit_event(
                AudioStreamErrorEvent(
                    trace_id=self.config.trace_id,
                    runtime_session_id=self.config.runtime_session_id,
                    error=str(exc),
                    recoverable=False,
                )
            )

    def _on_audio_chunk(self, state: AudioState, quality: SignalQuality) -> None:
        """Internal callback: update metrics, check latency, forward to ASR."""
        self._chunks_processed += 1

        # Latency / quality check
        latency_ms = quality.freshness_ms or 0.0
        if latency_ms > self.config.latency_warning_ms:
            self._emit_event(
                AudioQualityDegradedEvent(
                    trace_id=self.config.trace_id,
                    runtime_session_id=self.config.runtime_session_id,
                    latency_ms=latency_ms,
                    quality_flag=quality.flag.value,
                )
            )

        # Forward to registered ASR / agent consumers
        for cb in list(self._asr_callbacks):
            try:
                cb(state, quality)
            except Exception as exc:
                logger.debug("ASR callback error: %s", exc)

    def _emit_event(self, event: MultimodalEvent) -> None:
        """Dispatch a :class:`MultimodalEvent` to all registered listeners."""
        for listener in list(self._event_listeners):
            try:
                listener(event)
            except Exception as exc:
                logger.debug("Event listener error: %s", exc)
