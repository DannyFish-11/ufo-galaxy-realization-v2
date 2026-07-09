"""core/asr/sensevoice_asr.py — 离线中文语音识别（SenseVoiceSmall / FunASR）
================================================================================

A 档(无卡/离线)的"听"首选。SenseVoiceSmall 是非自回归模型:一次前向出结果,
CPU 上比 Whisper 快十几倍;中文 CER<5%,onnx 量化版仅 ~242MB,还支持中/英/粤/日/韩。
相较仓库原有的 faster-whisper(自回归、偏英文),它才是 CPU 中文场景的对的工具。

接口与 :class:`core.asr.whisper_asr.WhisperASR` 对齐(``transcribe(audio_np,
sample_rate, language) -> str`` + ``is_loaded``),因此能被 ``modality_bridge._get_asr``
直接当作 Whisper 的替代/首选。

真机需要::

    pip install funasr        # 阿里达摩院语音工具包
    # 首次使用自动下载 SenseVoiceSmall(可用 GALAXY_HF_ENDPOINT / 国内镜像加速)

缺包/加载失败时**优雅降级**(available()=False,transcribe 返回 ""),绝不抛出——
选择器据此自动回退到 Whisper。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger("Galaxy.ASR.SenseVoice")

# SenseVoice 识别输出里夹带的富文本标记(<|zh|><|NEUTRAL|><|Speech|>…),清洗掉只留正文。
_RICH_TAG = re.compile(r"<\|[^|]*\|>")


class SenseVoiceASR:
    """离线 SenseVoiceSmall ASR。接口对齐 WhisperASR(transcribe/is_loaded)。"""

    def __init__(
        self,
        model: Optional[str] = None,
        device: Optional[str] = None,
    ) -> None:
        # 模型 id:默认 modelscope 的 iic/SenseVoiceSmall;可用 GALAXY_SENSEVOICE_MODEL 覆盖
        # (如 HF 的 FunAudioLLM/SenseVoiceSmall)。
        self.model_name = model or os.getenv(
            "GALAXY_SENSEVOICE_MODEL", "iic/SenseVoiceSmall"
        )
        self._device_override = device
        self.model = None
        self._load_failed = False
        self._device = "cpu"
        self._load_model()

    def _load_model(self) -> None:
        try:
            from funasr import AutoModel  # 延迟 import:仅装了 funasr 才可用
        except Exception as exc:  # noqa: BLE001
            logger.info("SenseVoice 不可用(需 pip install funasr): %s", exc)
            self._load_failed = True
            return

        device = self._device_override
        if device is None:
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:  # noqa: BLE001
                device = "cpu"

        # 国内镜像:HF_ENDPOINT 未设时默认 hf-mirror.com(与 whisper_asr 一致)。
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = os.environ.get(
                "GALAXY_HF_ENDPOINT", "https://hf-mirror.com"
            )

        try:
            self.model = AutoModel(
                model=self.model_name,
                device=device,
                disable_update=True,  # 别每次联网检查更新,离线可用
            )
            self._device = device
            logger.info("SenseVoice ASR loaded: model=%s device=%s", self.model_name, device)
        except Exception as exc:  # noqa: BLE001
            logger.info("SenseVoice 加载失败(降级为 Whisper): %s", exc)
            self._load_failed = True

    def available(self) -> bool:
        return self.model is not None and not self._load_failed

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def transcribe(
        self,
        audio_np,
        sample_rate: int = 16000,
        language: str = "zh",
        **kwargs,
    ) -> str:
        """音频 numpy(float32, 16kHz 单声道) → 文字;不可用/失败返回 ""(优雅降级)。"""
        if self.model is None:
            return ""
        # SenseVoice 语种:auto/zh/en/yue/ja/ko;非法值一律 auto(它自己判语种)。
        lang = language if language in ("auto", "zh", "en", "yue", "ja", "ko") else "auto"
        try:
            res = self.model.generate(
                input=audio_np,
                cache={},
                language=lang,
                use_itn=True,  # 逆文本正则化:数字/标点更规整
            )
            raw = res[0]["text"] if res else ""
            return self._clean(raw).strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("SenseVoice 转写失败: %s", exc)
            return ""

    @staticmethod
    def _clean(text: str) -> str:
        """去掉 SenseVoice 的富文本标记,返回纯正文。优先用官方后处理。"""
        if not text:
            return ""
        try:
            from funasr.utils.postprocess_utils import rich_transcription_postprocess
            return rich_transcription_postprocess(text)
        except Exception:  # noqa: BLE001 — 官方后处理不可用时退回正则清洗
            return _RICH_TAG.sub("", text)

    def __repr__(self) -> str:
        return f"SenseVoiceASR(model={self.model_name}, device={self._device})"
