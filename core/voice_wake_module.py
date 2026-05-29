"""
core/voice_wake_module.py
=========================
PR-VOICE-WAKE: Local Voice Wake-Word Detection.

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

import asyncio
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
    import webrtcvad  # type: ignore[import-untyped]
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
        """Initialize WebRTC VAD as fallback."""
        if not _VAD_AVAILABLE:
            return False
        try:
            self._vad = webrtcvad.Vad(2)  # aggressiveness 0-3
            return True
        except Exception as exc:
            logger.debug("VoiceWake: VAD init failed: %s", exc)
        return False

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
        buffer_max_ms = 3000  # 3 seconds max buffer
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
                    is_speech = self._vad.is_speech(data, self.SAMPLE_RATE)
                    if is_speech:
                        speech_detected = True
                        audio_buffer += data
                    elif speech_detected and len(audio_buffer) > 0:
                        # Speech ended — process buffer
                        if len(audio_buffer) > self.SAMPLE_RATE * 0.5:  # at least 0.5s
                            self._process_buffer(audio_buffer)
                        audio_buffer = b""
                        speech_detected = False

                    # Prevent buffer overflow
                    if len(audio_buffer) > self.SAMPLE_RATE * 2 * buffer_max_ms // 1000:
                        audio_buffer = audio_buffer[-self.SAMPLE_RATE:]  # keep last 1s

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
            audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0

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
            except Exception:
                pass
            self._stream = None

        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None

        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception:
                pass
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
