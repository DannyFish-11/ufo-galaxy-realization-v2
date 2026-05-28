"""
core.asr.whisper_asr — 本地语音识别（faster-whisper）
========================================================
借鉴: faster-whisper (CTranslate2加速的Whisper)
功能: 麦克风音频 → 文字

依赖:
    pip install faster-whisper

硬件要求（模型大小选择）:
    - tiny (39M)   : ~1GB VRAM, 最快, 准确率最低
    - base (74M)   : ~1GB VRAM, 较快
    - small (244M) : ~2GB VRAM, 平衡
    - medium (769M): ~5GB VRAM, 较准
    - large (1550M): ~10GB VRAM, 最准
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger("Galaxy.ASR")


class WhisperASR:
    """本地ASR引擎（faster-whisper）

    支持的模型大小（按显存需求）:
    - tiny (39M)   : ~1GB VRAM, 最快, 准确率最低
    - base (74M)   : ~1GB VRAM, 较快
    - small (244M) : ~2GB VRAM, 平衡
    - medium (769M): ~5GB VRAM, 较准
    - large (1550M): ~10GB VRAM, 最准

    自动选择策略:
    - VRAM > 8GB  → medium
    - VRAM > 4GB  → small
    - VRAM > 2GB  → base
    - 否则         → tiny

    使用示例::

        asr = WhisperASR(model_size="small")
        audio = np.random.randn(16000).astype(np.float32)
        text = asr.transcribe(audio, sample_rate=16000, language="zh")
    """

    # 默认模型缓存目录
    DEFAULT_MODEL_DIR: Optional[str] = None

    def __init__(
        self,
        model_size: Optional[str] = None,
        model_dir: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ) -> None:
        """初始化Whisper ASR引擎。

        Args:
            model_size: 模型大小 (tiny/base/small/medium/large)，None则自动选择。
            model_dir: 模型下载/缓存目录，None则使用默认路径。
            device: 计算设备 ("cuda"/"cpu")，None则自动检测。
            compute_type: 计算类型 ("float16"/"int8")，None则自动选择。
        """
        self.model = None
        self.model_size = model_size
        self.model_dir = model_dir or self.DEFAULT_MODEL_DIR
        self._device_override = device
        self._compute_type_override = compute_type
        self._load_model()

    def _load_model(self) -> None:
        """加载模型（自动选择大小和设备）"""
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError(
                "faster-whisper is not installed. "
                "Install it with: pip install faster-whisper"
            ) from exc

        if not self.model_size:
            self.model_size = self._auto_select_model()

        # compute_type: float16 (GPU) / int8 (CPU/低VRAM)
        device = self._device_override
        compute_type = self._compute_type_override

        if device is None:
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        if compute_type is None:
            compute_type = "float16" if device == "cuda" else "int8"

        # 加载模型参数
        load_kwargs = {
            "device": device,
            "compute_type": compute_type,
        }
        if self.model_dir:
            load_kwargs["download_root"] = self.model_dir
            load_kwargs["local_files_only"] = False

        self.model = WhisperModel(self.model_size, **load_kwargs)
        self._device = device
        self._compute_type = compute_type
        logger.info(
            "Whisper ASR loaded: model=%s, device=%s, compute_type=%s",
            self.model_size,
            device,
            compute_type,
        )

    def _auto_select_model(self) -> str:
        """根据硬件自动选择模型大小。

        Returns:
            最适合当前硬件的模型大小字符串。
        """
        try:
            import torch
            if torch.cuda.is_available():
                vram_mb = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
                logger.debug("Detected VRAM: %d MB", vram_mb)
                if vram_mb > 10000:
                    return "medium"
                if vram_mb > 5000:
                    return "small"
                if vram_mb > 2000:
                    return "base"
                return "tiny"
        except ImportError:
            logger.debug("torch not available for VRAM detection")
        except Exception as exc:
            logger.debug("VRAM detection failed: %s", exc)
        return "base"  # 默认: 无GPU时选base，平衡速度和精度

    def transcribe(
        self,
        audio_np: np.ndarray,
        sample_rate: int = 16000,
        language: str = "zh",
        **kwargs,
    ) -> str:
        """音频numpy数组 → 文字。

        Args:
            audio_np: 音频样本numpy数组 (float32)。
            sample_rate: 音频采样率 (Hz)，默认16000。
            language: 语言代码，默认"zh"（中文）。
            **kwargs: 传递给 model.transcribe 的额外参数。

        Returns:
            识别到的文字字符串。
        """
        if self.model is None:
            raise RuntimeError("Whisper model not loaded")

        # 确保音频是 float32 且采样率正确
        if audio_np.dtype != np.float32:
            audio_np = audio_np.astype(np.float32)

        # 标准化音频范围到 [-1, 1]（如果不在范围内）
        max_val = np.max(np.abs(audio_np))
        if max_val > 1.0:
            audio_np = audio_np / max_val

        # 默认VAD参数
        transcribe_kwargs = {
            "language": language,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }
        transcribe_kwargs.update(kwargs)

        segments, info = self.model.transcribe(audio_np, **transcribe_kwargs)
        text = " ".join([s.text for s in segments])

        logger.debug(
            "ASR result: language=%s, probability=%.2f, text='%s'",
            info.language,
            info.language_probability,
            text[:100],
        )
        return text.strip()

    @property
    def is_loaded(self) -> bool:
        """模型是否已加载。"""
        return self.model is not None

    @property
    def device(self) -> str:
        """当前使用的计算设备。"""
        return getattr(self, "_device", "unknown")

    @property
    def compute_type(self) -> str:
        """当前使用的计算类型。"""
        return getattr(self, "_compute_type", "unknown")

    def reload(self, model_size: Optional[str] = None) -> None:
        """重新加载模型（可切换大小）。

        Args:
            model_size: 新的模型大小，None则保持当前大小。
        """
        if model_size:
            self.model_size = model_size
        self.model = None
        self._load_model()

    def __repr__(self) -> str:
        return (
            f"WhisperASR(model_size={self.model_size}, "
            f"device={self.device}, compute_type={self.compute_type})"
        )
