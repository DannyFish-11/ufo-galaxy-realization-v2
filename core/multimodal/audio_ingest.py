"""Microphone capture pipeline with VAD and lightweight audio state features.

Runs in local/server contexts where *sounddevice* is available.
Degrades gracefully when the device is missing or permission is denied —
the pipeline returns immediately without raising, leaving the rest of the
system unaffected.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional

import numpy as np

from .audio_features import AudioState, extract_audio_features
from .signal_quality import SignalQuality
from .vad import VADConfig, VoiceActivityDetector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional sounddevice import
# ---------------------------------------------------------------------------
_SOUNDDEVICE_AVAILABLE = False
try:
    import sounddevice as _sd  # noqa: F401

    _SOUNDDEVICE_AVAILABLE = True
except Exception as exc:
    logger.debug("Suppressed: %s", exc)


def _resolve_input_device(sd, configured, sample_rate: int, channels: int):
    """选一个【真的能以目标参数打开】的输入设备,专治"默认录音设备被改/被拔/被独占
    → 之前能录、现在 device=None 直接打不开"这一最常见的麦克风失灵根因。

    顺序:显式 configured → 系统默认(None)→ 枚举里所有有输入通道的设备;每个候选
    用 sd.check_input_settings 实测能否以目标 sr/通道打开,第一个通过的即采用。全都
    不通过 → 返回 configured(维持原行为,让下面的 InputStream 抛错并打完整诊断)。
    仅在默认设备确实打不开时才改选别的,不打扰正常情形。
    """

    def _ok(dev) -> bool:
        try:
            sd.check_input_settings(device=dev, samplerate=sample_rate, channels=channels, dtype="float32")
            return True
        except Exception:
            return False

    candidates: List = [configured] if configured is not None else [None]  # 先试显式/系统默认
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0 and idx not in candidates:
                candidates.append(idx)
    except Exception:
        pass
    for dev in candidates:
        if _ok(dev):
            return dev
    return configured


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class AudioIngestConfig:
    """Configuration for the microphone ingest pipeline."""

    sample_rate: int = 16000  # Hz
    channels: int = 1
    chunk_duration_ms: int = 100  # Target chunk size (~10 Hz update rate)
    device: Optional[int] = None  # None → use system default microphone
    vad_config: Optional[VADConfig] = None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class AudioIngestPipeline:
    """Microphone capture pipeline with VAD and lightweight audio state.

    Usage::

        pipeline = AudioIngestPipeline()
        pipeline.add_callback(my_handler)
        await pipeline.run()          # blocks until stop() is called

    Or as an async generator::

        async for state, quality in pipeline.stream():
            ...
    """

    def __init__(self, config: Optional[AudioIngestConfig] = None) -> None:
        self.config = config or AudioIngestConfig()
        self._vad = VoiceActivityDetector(
            config=self.config.vad_config,
            sample_rate=self.config.sample_rate,
        )
        self._running = False
        self._quality: SignalQuality = SignalQuality.missing("Not started")
        self._latest_state: Optional[AudioState] = None
        self._callbacks: List[Callable[[AudioState, SignalQuality], None]] = []
        self._last_update_ts: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if sounddevice is importable on this host."""
        return _SOUNDDEVICE_AVAILABLE

    def add_callback(self, cb: Callable[[AudioState, SignalQuality], None]) -> None:
        """Register a callback invoked with each new AudioState."""
        self._callbacks.append(cb)

    def get_latest(self) -> tuple:
        """Return (AudioState | None, SignalQuality) for the most recent frame."""
        return self._latest_state, self._quality

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the microphone ingest loop.

        Returns immediately (without raising) when:
        - sounddevice is not installed
        - microphone permission is denied
        - the device is not found
        """
        if not _SOUNDDEVICE_AVAILABLE:
            self._quality = SignalQuality.device_unavailable()
            logger.warning("sounddevice is not available; audio ingest disabled")
            return

        import sounddevice as sd  # deferred to avoid import-time failure

        # 默认录音设备可能被改/被拔/被独占 → device=None 直接打不开(经典"之前能录现在
        # 不行")。这里先挑一个实测能打开的输入设备,默认可用就原样用,不可用才回退。
        _device = _resolve_input_device(sd, self.config.device, self.config.sample_rate, self.config.channels)
        if _device != self.config.device:
            logger.warning(
                "默认录音设备不可用,已回退到输入设备 index=%s(原 device=%s)。"
                "如非预期,Windows 声音设置→录制里确认默认麦克风。",
                _device,
                self.config.device,
            )

        chunk_size = max(
            1,
            int(self.config.sample_rate * self.config.chunk_duration_ms / 1000),
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # capture() must be called from within a running asyncio event loop.
            # Without one, the sounddevice callback cannot enqueue audio chunks
            # safely, so we exit early rather than silently misbehaving.
            logger.warning(
                "AudioIngestPipeline.capture() called with no running event loop — "
                "audio capture cannot start.  Call capture() from an async context."
            )
            self._quality = SignalQuality.device_unavailable()
            return
        queue: asyncio.Queue = asyncio.Queue(maxsize=30)

        def _safe_put(chunk_: np.ndarray) -> None:
            # 在事件循环内执行:满了就丢帧。之前直接调度 queue.put_nowait,
            # QueueFull 在回调执行时抛进事件循环,每帧刷一条
            # "Exception in callback Queue.put_nowait" 错误日志。
            try:
                queue.put_nowait(chunk_)
            except asyncio.QueueFull:
                pass  # drop frame rather than block

        def _sd_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            if status:
                logger.debug("sounddevice status: %s", status)
            chunk = indata[:, 0].copy() if indata.ndim > 1 else indata.flatten().copy()
            try:
                loop.call_soon_threadsafe(_safe_put, chunk)
            except RuntimeError:
                pass  # loop closed during shutdown — drop

        self._running = True
        self._quality = SignalQuality.ok()

        try:
            with sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype="float32",
                blocksize=chunk_size,
                device=_device,
                callback=_sd_callback,
            ):
                logger.info(
                    "Audio ingest started (sr=%d, chunk_ms=%d)",
                    self.config.sample_rate,
                    self.config.chunk_duration_ms,
                )
                while self._running:
                    try:
                        chunk = await asyncio.wait_for(queue.get(), timeout=1.0)
                        await self._process_chunk(chunk)
                    except asyncio.TimeoutError:
                        pass

        except PermissionError:
            self._quality = SignalQuality.permission_denied()
            logger.warning("Microphone permission denied")
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            self._quality = SignalQuality.degraded(str(exc))
            # 真机常见:PortAudio "Unanticipated host error [PaErrorCode -9999]" +
            # "MME error 1" —— Windows MME 后端打不开默认录音设备的经典组合，
            # 通常是驱动/独占模式占用问题，与本仓库代码无关，此环境也无法复现。
            # 之前只打一行原始异常文本，排查时两眼一抹黑。这里在同一次失败里
            # 顺手枚举一次可用设备/host API，把诊断信息打进同一条日志——下次
            # 真机复现时，日志本身就能看出"到底有没有可用设备、默认设备是谁"，
            # 而不必再靠猜。绝不影响主流程(仅诊断，任何异常都吞掉)。
            _diag = ""
            try:
                devices = sd.query_devices()
                hostapis = sd.query_hostapis()
                default_in = sd.default.device[0] if hasattr(sd.default, "device") else None
                _diag = (
                    f" | 诊断:默认输入设备索引={default_in}，"
                    f"可用设备数={len(devices)}，"
                    f"host API={[h.get('name') for h in hostapis]}"
                )
            except Exception:
                _diag = " | 诊断:枚举设备本身也失败(可能压根没有录音设备)"
            logger.warning(
                "Audio ingest error: %s%s —— 常见于 Windows MME 后端打不开默认"
                "录音设备(驱动/独占模式占用);不影响其它功能，语音走独立的 "
                "Whisper 采集路径。可尝试:Windows 声音设置 → 录制 → 默认设备 "
                '→ 属性 → 高级 → 取消勾选"允许应用程序独占控制"。',
                exc,
                _diag,
            )
        finally:
            self._running = False
            logger.info("Audio ingest stopped")

    async def _process_chunk(self, chunk: np.ndarray) -> None:
        """Update VAD + features and invoke registered callbacks."""
        now = time.monotonic()
        vad_state = self._vad.process_frame(chunk)
        state = extract_audio_features(chunk, vad_state, self._last_update_ts, self.config.sample_rate)
        self._last_update_ts = now
        self._latest_state = state
        self._quality = SignalQuality.ok(freshness_ms=(time.monotonic() - now) * 1000.0)
        for cb in list(self._callbacks):
            try:
                cb(state, self._quality)
            except Exception as exc:
                logger.debug("Audio callback error: %s", exc)

    # ------------------------------------------------------------------
    # Async generator interface
    # ------------------------------------------------------------------

    async def stream(self) -> AsyncIterator:
        """Yield (AudioState, SignalQuality) tuples as they arrive."""
        states: asyncio.Queue = asyncio.Queue(maxsize=50)

        def _enqueue(state: AudioState, quality: SignalQuality) -> None:
            try:
                states.put_nowait((state, quality))
            except asyncio.QueueFull:
                pass

        self.add_callback(_enqueue)
        task = asyncio.create_task(self.run())
        try:
            while not task.done() or not states.empty():
                try:
                    yield await asyncio.wait_for(states.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if task.done():
                        break
        finally:
            self.stop()
            await task
