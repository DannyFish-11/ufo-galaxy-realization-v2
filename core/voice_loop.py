"""
core.voice_loop — 语音闭环协调器
==================================
完整的语音交互闭环：
    麦克风 → ASR → Galaxy处理 → TTS → 播放

依赖:
    pip install faster-whisper edge-tts sounddevice numpy

使用方式::

    import asyncio
    from core.voice_loop import VoiceLoop

    # galaxy_client 是处理文本并返回响应的 Galaxy 客户端
    voice_loop = VoiceLoop(galaxy_client)
    await voice_loop.start()  # 开始监听麦克风
    # 用户说话 → 自动识别 → Galaxy处理 → 语音回复
    # ...
    await voice_loop.stop()   # 停止监听
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("Galaxy.VoiceLoop")


class VoiceLoop:
    """语音交互闭环协调器。

    完整的语音交互流程：
        1. 麦克风录音 (AudioCaptureService)
        2. ASR语音识别 (WhisperASR) → 文字
        3. Galaxy处理 → 文字响应
        4. TTS语音合成 (EdgeTTSEngine) → 音频
        5. 播放音频

    使用方式::

        voice_loop = VoiceLoop(galaxy_client)
        await voice_loop.start()  # 开始监听
        # 用户说话 → 自动识别 → Galaxy处理 → 语音回复
        await voice_loop.stop()
    """

    def __init__(
        self,
        galaxy_client: Any,
        model_size: Optional[str] = None,
        voice: str = "zh-CN-XiaoxiaoNeural",
        language: str = "zh",
        sample_rate: int = 16000,
        chunk_duration_ms: int = 100,
    ) -> None:
        """初始化语音闭环。

        Args:
            galaxy_client: Galaxy 客户端实例，需要实现 ``process(text, source)`` 方法。
            model_size: Whisper 模型大小 (tiny/base/small/medium/large)。
            voice: TTS 声音 ID。
            language: ASR 语言代码 (默认 "zh" 中文)。
            sample_rate: 音频采样率 (Hz)。
            chunk_duration_ms: 音频块时长 (毫秒)。
        """
        self.galaxy = galaxy_client
        self.model_size = model_size
        self.voice = voice
        self.language = language
        self.sample_rate = sample_rate
        self.chunk_duration_ms = chunk_duration_ms

        self.asr: Optional[Any] = None
        self.tts: Optional[Any] = None
        self.capture: Optional[Any] = None
        self._running: bool = False
        self._voice_input_handler: Optional[Callable[[str], asyncio.Future]] = None

    async def start(self) -> None:
        """启动语音闭环。

        初始化 ASR、TTS 和音频捕获服务，开始监听麦克风。
        """
        if self._running:
            logger.warning("VoiceLoop already running")
            return

        # Lazy imports to avoid hard dependencies at module load time
        try:
            from core.asr import WhisperASR
            from core.tts import EdgeTTSEngine
            from core.multimodal.audio_capture_service import (
                AudioCaptureService,
                AudioCaptureConfig,
            )
        except ImportError as exc:
            logger.error("VoiceLoop dependencies not available: %s", exc)
            raise

        logger.info("Starting VoiceLoop...")

        # 1. 初始化 ASR
        self.asr = WhisperASR(model_size=self.model_size)
        logger.info("ASR initialized: %s", self.asr)

        # 2. 初始化 TTS
        self.tts = EdgeTTSEngine(voice=self.voice)
        logger.info("TTS initialized: %s", self.tts)

        # 3. 初始化音频捕获服务
        capture_config = AudioCaptureConfig(
            sample_rate=self.sample_rate,
            chunk_duration_ms=self.chunk_duration_ms,
        )
        self.capture = AudioCaptureService(config=capture_config)

        # 4. 注册 ASR 回调
        self.capture.add_whisper_callback(self.asr, language=self.language)

        # 5. 注册语音输入处理回调
        self.capture.on_voice_input = self._on_voice_input

        # 6. 启动捕获
        await self.capture.start()
        self._running = True
        logger.info("VoiceLoop started — listening for voice input")

    async def _on_voice_input(self, text: str) -> None:
        """处理语音识别结果。

        流程:
            1. 发送给 Galaxy 处理
            2. TTS 合成并播放响应

        Args:
            text: ASR 识别出的文字。
        """
        if not self._running:
            return

        logger.info("Voice input: %s", text)

        try:
            # 1. 发送给 Galaxy 处理
            if asyncio.iscoroutinefunction(self.galaxy.process):
                result = await self.galaxy.process(text, source="voice")
            else:
                result = self.galaxy.process(text, source="voice")

            response = ""
            if isinstance(result, dict):
                response = result.get("response", "")
            elif isinstance(result, str):
                response = result

            if not response:
                logger.debug("Empty response from Galaxy, skipping TTS")
                return

            logger.info("Galaxy response: %s", response[:100])

            # 2. TTS 合成并播放
            if self.tts is not None:
                await self.tts.synthesize_and_play(response)
                logger.info("TTS playback completed")

        except Exception as exc:
            logger.error("Voice input processing error: %s", exc)

    async def stop(self) -> None:
        """停止语音闭环。

        停止音频捕获服务并清理资源。
        """
        self._running = False

        if self.capture is not None:
            try:
                await self.capture.stop()
            except Exception as exc:
                logger.debug("Error stopping capture: %s", exc)

        logger.info("VoiceLoop stopped")

    async def say(self, text: str) -> None:
        """直接让系统说一段话（不经过ASR）。

        Args:
            text: 要说的文字。
        """
        if self.tts is None:
            logger.warning("TTS not initialized, cannot speak")
            return

        logger.info("Saying: %s", text[:100])
        await self.tts.synthesize_and_play(text)

    async def process_once(self, audio_np, sample_rate: int = 16000) -> Dict[str, Any]:
        """处理单次音频输入（非流式）。

        适用于批量处理预录音频，而非实时麦克风输入。

        Args:
            audio_np: 音频numpy数组。
            sample_rate: 音频采样率。

        Returns:
            处理结果字典，包含 ``asr_text``、``response``、``audio_path``。
        """
        result: Dict[str, Any] = {
            "asr_text": "",
            "response": "",
            "audio_path": None,
            "success": False,
        }

        try:
            # 1. ASR
            if self.asr is None:
                from core.asr import WhisperASR
                self.asr = WhisperASR(model_size=self.model_size)

            text = self.asr.transcribe(audio_np, sample_rate=sample_rate, language=self.language)
            result["asr_text"] = text
            logger.info("ASR: %s", text)

            if not text:
                result["note"] = "No speech detected"
                return result

            # 2. Galaxy 处理
            if asyncio.iscoroutinefunction(self.galaxy.process):
                gal_result = await self.galaxy.process(text, source="voice")
            else:
                gal_result = self.galaxy.process(text, source="voice")

            response = ""
            if isinstance(gal_result, dict):
                response = gal_result.get("response", "")
            elif isinstance(gal_result, str):
                response = gal_result
            result["response"] = response

            # 3. TTS
            if response and self.tts is None:
                from core.tts import EdgeTTSEngine
                self.tts = EdgeTTSEngine(voice=self.voice)

            if response and self.tts is not None:
                audio_path = await self.tts.synthesize(response)
                result["audio_path"] = audio_path

            result["success"] = True

        except Exception as exc:
            logger.error("Process once error: %s", exc)
            result["error"] = str(exc)

        return result

    @property
    def is_running(self) -> bool:
        """语音闭环是否正在运行。"""
        return self._running

    def __repr__(self) -> str:
        return (
            f"VoiceLoop(running={self._running}, "
            f"model_size={self.model_size}, voice={self.voice}, "
            f"language={self.language})"
        )
