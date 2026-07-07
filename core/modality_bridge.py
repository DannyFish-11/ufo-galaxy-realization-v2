"""core/modality_bridge.py — 能力驱动的多模态 IO 桥接（听 / 说）
================================================================

把 core.model_catalog 的"有效 IO"落到实处：上层（ambient loop / voice loop）
不再写死"某模型能不能听/说"，而是问本模块——**当前档位**该走原生还是桥接。

  听 (audio_in):
    native      —— 当前档位有模型原生理解音频，且服务层确实能把音频喂进去
    asr_bridge  —— 否则用 faster-whisper 把音频转文字，再当文本喂给模型

  说 (audio_out):
    native      —— 当前档位有模型原生合成语音
    tts_bridge  —— 否则用 edge-tts 合成

服务层现实
----------
即便模型本身支持音频（如 MiniCPM-o），Ollama 的 /api/chat 目前并没有标准的
音频输入字段（只有 images）。因此"原生听"是否真能生效，还取决于**服务路径**是否
把音频管道接通。用 ``GALAXY_NATIVE_AUDIO`` 显式门控：默认关（Ollama 路径走 ASR 桥，
这是笔记本上真正能用的），将来上了真正的全模态服务（vLLM-Omni / MiniCPM-o server）
再打开。这样"能力声明"（catalog）与"服务现实"（本门控）解耦，不自欺。
"""
from __future__ import annotations

import base64
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("Galaxy.ModalityBridge")


def _native_audio_serving_enabled() -> bool:
    """服务层是否真的能喂原生音频。默认关（Ollama 不支持音频输入）。"""
    return str(os.getenv("GALAXY_NATIVE_AUDIO", "")).strip().lower() in ("1", "true", "yes", "on")


def resolve_audio_in() -> str:
    """当前档位的听通路：native / asr_bridge。"""
    try:
        from core.model_catalog import active_effective_io
        io = active_effective_io()
        if io.audio_in == "native" and _native_audio_serving_enabled():
            return "native"
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_audio_in 回退 asr_bridge: %s", exc)
    return "asr_bridge"


def resolve_audio_out() -> str:
    """当前档位的说通路：native / tts_bridge。"""
    try:
        from core.model_catalog import active_effective_io
        io = active_effective_io()
        if io.audio_out == "native" and _native_audio_serving_enabled():
            return "native"
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_audio_out 回退 tts_bridge: %s", exc)
    return "tts_bridge"


# ── ASR 桥：base64 音频 → 文字 ────────────────────────────────────────────────
_asr_singleton = None
_asr_lock = threading.Lock()
_asr_failed = False  # 一旦初始化失败就不再反复尝试（缺 faster-whisper 等）


def _get_asr():
    global _asr_singleton, _asr_failed
    if _asr_singleton is not None or _asr_failed:
        return _asr_singleton
    with _asr_lock:
        if _asr_singleton is None and not _asr_failed:
            try:
                from core.asr.whisper_asr import WhisperASR
                # 轻量优先：ambient 转写要快，tiny/base 足够抓关键词判断是否介入。
                size = os.getenv("GALAXY_AMBIENT_ASR_SIZE", "base")
                _asr_singleton = WhisperASR(model_size=size)
            except Exception as exc:  # noqa: BLE001
                logger.debug("ASR 初始化失败,听将降级为'有声音但未转写': %s", exc)
                _asr_failed = True
    return _asr_singleton


def _decode_audio_to_pcm(audio_bytes: bytes):
    """任意容器(webm/opus/wav…)的音频字节 → float32 单声道 16kHz numpy 数组。

    用 PyAV 解码+重采样；失败返回 None。
    """
    try:
        import io
        import av
        import numpy as np

        container = av.open(io.BytesIO(audio_bytes))
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
        samples = []
        for frame in container.decode(audio=0):
            for rframe in resampler.resample(frame):
                arr = rframe.to_ndarray()  # shape (1, n) int16
                samples.append(arr.reshape(-1))
        if not samples:
            return None
        pcm = np.concatenate(samples).astype(np.float32) / 32768.0
        return pcm
    except Exception as exc:  # noqa: BLE001
        logger.debug("音频解码失败: %s", exc)
        return None


def transcribe_b64(audio_b64: str, *, mime: str = "audio/webm", language: str = "zh") -> Optional[str]:
    """base64 音频 → 文字（听的桥接实现）。任何环节不可用则返回 None（优雅降级）。"""
    if not audio_b64:
        return None
    asr = _get_asr()
    if asr is None:
        return None
    try:
        raw = base64.b64decode(audio_b64)
    except Exception:  # noqa: BLE001
        return None
    pcm = _decode_audio_to_pcm(raw)
    if pcm is None or len(pcm) == 0:
        return None
    try:
        text = asr.transcribe(pcm, sample_rate=16000, language=language)
        return (text or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("转写失败: %s", exc)
        return None
