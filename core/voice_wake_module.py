"""
core/voice_wake_module.py
=========================
PR-VOICE-WAKE: Local Voice Wake-Word Detection.

Install dependencies (optional — system works without them):
    pip install pvporcupine webrtcvad faster-whisper pyaudio

Graceful degradation: if any dependency is missing, the module
silently skips and the system continues without voice wake.

Detects the wake word "Galaxy" locally and triggers tri-state transition
from SILENT → LIMINAL.

Design principles:
  - Pure Python — no heavy ML dependencies.
  - Uses webrtcvad + simple energy threshold as fallback.
  - If porcupine/snowboy is available, uses them for accurate detection.
  - If not, uses VAD + keyword spotting via faster-whisper.
  - Fire-and-forget: detection never blocks the main loop.

Usage::
    from core.voice_wake_module import get_voice_wake

    wake = get_voice_wake()
    wake.start(callback=on_wake_word)
    # ... runs in background thread ...
    wake.stop()
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("Galaxy.VoiceWake")

# Optional wake-word engine
try:
    import pvporcupine  # type: ignore[import-untyped]

    _PORCUPINE_AVAILABLE = True
except ImportError:
    _PORCUPINE_AVAILABLE = False

try:
    import numpy as np

    from core.multimodal.vad import VADConfig, VoiceActivityDetector

    _VAD_AVAILABLE = True
except ImportError:
    _VAD_AVAILABLE = False

try:
    import pyaudio  # type: ignore[import-untyped]

    _PYAUDIO_AVAILABLE = True
except ImportError:
    _PYAUDIO_AVAILABLE = False

# Optional: use faster-whisper for wake-word spotting
try:
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False


class VoiceWakeModule:
    """Local voice wake-word detector.

    Detects "Galaxy" wake word and triggers callback.
    Falls back to energy-based VAD + whisper transcription if no
    dedicated wake-word engine is available.
    """

    WAKE_WORD = "galaxy"
    CHUNK_DURATION_MS = 30  # 30ms audio chunks
    BUFFER_MAX_MS = 3000  # 缓冲上限；同时也是「连续有声」强制转写的门限
    SAMPLE_RATE = 16000
    FRAME_LENGTH = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[], None]] = None
        self._porcupine: Optional[Any] = None
        self._vad: Optional[Any] = None
        self._audio: Optional[Any] = None
        self._stream: Optional[Any] = None
        self._whisper_model: Optional[Any] = None

    # ── Engine detection ──

    def _init_porcupine(self) -> bool:
        """Initialize Porcupine wake-word engine if available."""
        if not _PORCUPINE_AVAILABLE:
            return False
        try:
            # Try to find the keyword file for "Galaxy"
            keyword_paths = pvporcupine.KEYWORD_PATHS
            if "galaxy" in keyword_paths:
                self._porcupine = pvporcupine.create(
                    keyword_paths=[keyword_paths["galaxy"]],
                    sensitivities=[0.7],
                )
                logger.info("VoiceWake: Porcupine engine initialized for 'Galaxy'")
                return True
        except Exception as exc:
            logger.debug("VoiceWake: Porcupine init failed: %s", exc)
        return False

    def _init_vad(self) -> bool:
        """初始化 VAD —— 与采集管线**同一个判据**（``core/multimodal/vad.py``）。

        原来这里是 ``webrtcvad.Vad(2)`` 独断，也就是采集侧明确记录为
        「一启用就一直判定有人在说话」成因的那条旧行为：webrtcvad 是频谱分类器，
        宽带稳态噪声（风扇/空调）在它眼里跟摩擦音、清音很像，它照判有声。

        后果在这条链上比在采集侧更硬：见 :meth:`_detect_loop`，识别唤醒词的
        ``_process_buffer`` 只在"说话结束"那一拍被调用。VAD 恒判有声 ⇒ 那一拍
        永远不来 ⇒ **叫它永远没反应**。实测（桩替掉 VAD，60 秒）:恒真时
        ``_process_buffer`` 被调用 0 次，正常起落时 2 次。

        改用 ``VoiceActivityDetector`` 一并解决三件事:
        * 取"频谱有声 ∩ 能量超自适应门限"的交集，稳态噪声不再恒判有声;
        * ``GALAXY_VAD_*`` 一套环境变量对两条链同时生效（原来这里写死 2，
          ``VADConfig`` 的文档还写着"与 voice_wake_module 保持一致"—— 靠人对齐）;
        * webrtcvad 缺包时能量法仍然可用，原来会直接把 VAD 整个关掉。

        帧长按本模块真实投喂节奏给 30ms（``CHUNK_DURATION_MS``），不是
        ``VADConfig`` 面向采集管线的默认 100ms —— 否则滚动窗口会被算长 3 倍多。
        """
        if not _VAD_AVAILABLE:
            return False
        try:
            cfg = dataclasses.replace(VADConfig.from_env(), frame_duration_ms=self.CHUNK_DURATION_MS)
            self._vad = VoiceActivityDetector(config=cfg, sample_rate=self.SAMPLE_RATE)
            return True
        except Exception as exc:
            logger.debug("VoiceWake: VAD init failed: %s", exc)
        return False

    def _is_speech(self, data: bytes) -> bool:
        """一帧 int16 PCM 是否有人在说话（交给统一判据）。"""
        pcm = np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0
        return bool(self._vad.process_frame(pcm).is_speaking)

    def _init_audio(self) -> bool:
        """Initialize PyAudio."""
        if not _PYAUDIO_AVAILABLE:
            return False
        try:
            self._audio = pyaudio.PyAudio()
            self._stream = self._audio.open(
                rate=self.SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.FRAME_LENGTH,
            )
            return True
        except Exception as exc:
            logger.debug("VoiceWake: PyAudio init failed: %s", exc)
        return False

    def _init_whisper(self) -> bool:
        """Initialize faster-whisper for keyword spotting fallback."""
        if not _WHISPER_AVAILABLE:
            return False
        try:
            # Use tiny model for fast detection
            self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            logger.info("VoiceWake: Whisper fallback initialized")
            return True
        except Exception as exc:
            logger.debug("VoiceWake: Whisper init failed: %s", exc)
        return False

    # ── Detection loop ──

    def _detect_loop(self) -> None:
        """Main detection loop — runs in background thread."""
        audio_buffer: bytes = b""
        buffer_max_ms = self.BUFFER_MAX_MS
        # 16-bit 单声道：每毫秒 SAMPLE_RATE/1000 个样本 × 2 字节
        flush_bytes = self.SAMPLE_RATE * 2 * buffer_max_ms // 1000
        speech_detected = False

        logger.info("VoiceWake: detection loop started (wake_word='%s')", self.WAKE_WORD)

        while self._running:
            try:
                if self._stream is None:
                    time.sleep(0.1)
                    continue

                # Read audio chunk
                data = self._stream.read(self.FRAME_LENGTH, exception_on_overflow=False)

                # Strategy 1: Porcupine (most accurate)
                if self._porcupine is not None:
                    keyword_index = self._porcupine.process(data)
                    if keyword_index >= 0:
                        logger.info("VoiceWake: Porcupine detected 'Galaxy'")
                        self._trigger()
                        continue

                # Strategy 2: VAD + buffer + whisper keyword spotting
                if self._vad is not None:
                    is_speech = self._is_speech(data)
                    if is_speech:
                        speech_detected = True
                        audio_buffer += data
                    elif speech_detected and len(audio_buffer) > 0:
                        # Speech ended — process buffer
                        if len(audio_buffer) > self.SAMPLE_RATE * 0.5:  # at least 0.5s
                            self._process_buffer(audio_buffer)
                        audio_buffer = b""
                        speech_detected = False

                    # 兜底：VAD 判据坏掉时，唤醒也不许彻底哑掉。
                    #
                    # 上面识别唤醒词的唯一时机是「说话结束」那一拍。只要 VAD 持续
                    # 判有声，那一拍就永远不来 —— 缓冲被原来的截断逻辑一直滚着，
                    # _process_buffer 一次都不会被调用（实测 60 秒 0 次，正常起落
                    # 同样时长是 2 次）。判据本身已经换成与采集管线同源的那套，但
                    # 一条链的可用性不该完全押在另一条链的判据不出错上：连续有声
                    # 攒满 BUFFER_MAX_MS 就强制转写一次。真人连着说这么久也确实
                    # 该出一次结果，所以这既是兜底也是正常路径。
                    #
                    # 这一支同时取代了原来的「Prevent buffer overflow」截断
                    # （攒满就丢掉、只留最后 1 秒）：那段在这里已经不可达，而且
                    # 它做的事恰恰是把唤醒词悄悄扔掉。
                    if speech_detected and len(audio_buffer) >= flush_bytes:
                        self._process_buffer(audio_buffer)
                        audio_buffer = b""
                        speech_detected = False

            except Exception as exc:
                logger.debug("VoiceWake: detection loop error: %s", exc)
                time.sleep(0.1)

        logger.info("VoiceWake: detection loop stopped")

    def _process_buffer(self, audio_buffer: bytes) -> None:
        """Process audio buffer for wake word detection."""
        if self._whisper_model is None:
            return
        try:
            # Save buffer to temp file for whisper
            import tempfile

            import numpy as np

            # Convert bytes to numpy array
            np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                import wave

                with wave.open(f.name, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.SAMPLE_RATE)
                    wf.writeframes(audio_buffer)
                temp_path = f.name

            # Transcribe
            segments, _ = self._whisper_model.transcribe(temp_path, language="en", beam_size=1)
            text = " ".join([s.text for s in segments]).lower().strip()

            # Check for wake word
            if self.WAKE_WORD in text:
                logger.info("VoiceWake: Whisper spotted 'Galaxy' in: %s", text)
                self._trigger()

            # Cleanup
            Path(temp_path).unlink(missing_ok=True)

        except Exception as exc:
            logger.debug("VoiceWake: buffer processing error: %s", exc)

    def _trigger(self) -> None:
        """Fire the wake-word callback."""
        if self._callback is not None:
            try:
                self._callback()
            except Exception as exc:
                logger.warning("VoiceWake: callback error: %s", exc)

    # ── Public API ──

    def is_available(self) -> bool:
        """Check if any detection engine is available."""
        return _PYAUDIO_AVAILABLE and (_PORCUPINE_AVAILABLE or _VAD_AVAILABLE or _WHISPER_AVAILABLE)

    def start(self, callback: Callable[[], None]) -> bool:
        """Start wake-word detection in background thread.

        Args:
            callback: Called when wake word is detected.

        Returns:
            True if started successfully, False if no engine available.
        """
        if self._running:
            return True

        self._callback = callback

        # Initialize engines
        if not self._init_audio():
            logger.warning("VoiceWake: PyAudio unavailable — cannot start")
            return False

        self._init_porcupine()
        if self._porcupine is None:
            self._init_vad()
            self._init_whisper()

        if self._porcupine is None and self._vad is None:
            logger.warning("VoiceWake: no detection engine available")
            return False

        self._running = True
        self._thread = threading.Thread(target=self._detect_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop wake-word detection."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        # Cleanup resources
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
            self._stream = None

        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
            self._audio = None

        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
            self._porcupine = None

        logger.info("VoiceWake: stopped")

    def get_status(self) -> Dict[str, Any]:
        """Return current status."""
        return {
            "running": self._running,
            "porcupine": self._porcupine is not None,
            "vad": self._vad is not None,
            "whisper": self._whisper_model is not None,
            "audio": self._stream is not None,
            "wake_word": self.WAKE_WORD,
        }


# Singleton
_voice_wake: Optional[VoiceWakeModule] = None


def get_voice_wake() -> VoiceWakeModule:
    """Return the module-level :class:`VoiceWakeModule` singleton."""
    global _voice_wake
    if _voice_wake is None:
        _voice_wake = VoiceWakeModule()
    return _voice_wake
