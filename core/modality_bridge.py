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
    """服务层是否真的能喂原生音频。默认关（Ollama 不支持音频输入）。

    收口:统一读 core.modality_capability 的门控,不再各处各自读环境变量。
    """
    try:
        from core.modality_capability import _native_audio_serving_enabled as _gate

        return _gate()
    except Exception:  # noqa: BLE001
        return str(os.getenv("GALAXY_NATIVE_AUDIO", "")).strip().lower() in ("1", "true", "yes", "on")


def resolve_audio_in() -> str:
    """当前档位的听通路：native / asr_bridge。

    收口:委托给统一协商层 core.modality_capability.negotiate(),本函数只把三态
    映射回历史返回值(native / asr_bridge)以兼容既有调用方(ambient/voice loop)。
    unavailable(连 ASR 都没有)也归为 asr_bridge——上层 transcribe_b64 会因 ASR
    不可用返回 None,行为与旧版一致。
    """
    try:
        from core.modality_capability import negotiate

        return "native" if negotiate().audio_in.mode == "native" else "asr_bridge"
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_audio_in 回退 asr_bridge: %s", exc)
    return "asr_bridge"


def resolve_audio_out() -> str:
    """当前档位的说通路：native / tts_bridge。委托统一协商层,映射回历史返回值。"""
    try:
        from core.modality_capability import negotiate

        return "native" if negotiate().audio_out.mode == "native" else "tts_bridge"
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_audio_out 回退 tts_bridge: %s", exc)
    return "tts_bridge"


# ── 视频（看/抽帧）：连续视频 → 视觉路 ─────────────────────────────────────────
# 抽帧默认帧率(env 可覆盖)。native 连续视频送更密的帧;frames_bridge 只抽稀疏
# 静帧喂静态视觉(当前档位有视觉但无原生视频);unavailable 不抽(连静态视觉都没有)。
_VIDEO_FPS_NATIVE = float(os.getenv("GALAXY_VIDEO_FPS_NATIVE", "") or 4.0)
_VIDEO_FPS_BRIDGE = float(os.getenv("GALAXY_VIDEO_FPS_BRIDGE", "") or 1.0)


def resolve_video_in() -> str:
    """当前档位的视频通路：native / frames_bridge / unavailable。委托统一协商层。

    - native        —— GALAXY_NATIVE_VIDEO 开 + 模型原生吃连续视频
    - frames_bridge —— 有静态视觉、无原生视频 → 抽帧当静态图喂视觉(当前笔记本现实)
    - unavailable   —— 当前档位连静态视觉都没有 → 抽帧毫无意义,不该抽
    """
    try:
        from core.modality_capability import negotiate

        mode = negotiate().video_in.mode
        if mode == "native":
            return "native"
        if mode == "bridge":
            return "frames_bridge"
        return "unavailable"
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_video_in 回退 frames_bridge: %s", exc)
    return "frames_bridge"


def resolve_video_sampling(requested_fps: Optional[float] = None):
    """把 video_in 三态落成【抽帧决策】：返回 (should_sample, fps, mode)。

    上层视频抽帧循环(vision_sampler 等)据此自适配、零 per-model 分支:
      - unavailable    → (False, 0.0, mode):当前档位没有视觉,直接别抽,省算力;
      - frames_bridge  → (True, 稀疏 fps, mode):抽静帧喂静态视觉(今天真能用的);
      - native         → (True, 更密 fps, mode):模型吃连续视频,送更密的帧。
    显式 requested_fps>0 时优先尊重调用方(硬要某帧率),否则按 mode 取默认帧率。
    """
    mode = resolve_video_in()
    if mode == "unavailable":
        return (False, 0.0, mode)
    if requested_fps is not None and requested_fps > 0:
        return (True, float(requested_fps), mode)
    fps = _VIDEO_FPS_NATIVE if mode == "native" else _VIDEO_FPS_BRIDGE
    return (True, fps, mode)


# ── ASR 桥：base64 音频 → 文字 ────────────────────────────────────────────────
_asr_singleton = None
_asr_lock = threading.Lock()
_asr_failed = False  # 一旦初始化失败就不再反复尝试（缺 faster-whisper 等）


def _try_sensevoice():
    """离线中文首选:SenseVoiceSmall(非自回归,CPU 快十几倍,中文 CER<5%)。"""
    try:
        from core.asr.sensevoice_asr import SenseVoiceASR

        eng = SenseVoiceASR()
        return eng if eng.available() else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("SenseVoice ASR 不可用: %s", exc)
        return None


def _try_whisper():
    """兜底:faster-whisper。轻量优先——ambient 转写要快,tiny/base 足够抓关键词。"""
    try:
        from core.asr.whisper_asr import WhisperASR

        size = os.getenv("GALAXY_AMBIENT_ASR_SIZE", "base")
        return WhisperASR(model_size=size)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Whisper ASR 不可用: %s", exc)
        return None


def _get_asr():
    global _asr_singleton, _asr_failed
    if _asr_singleton is not None or _asr_failed:
        return _asr_singleton
    with _asr_lock:
        if _asr_singleton is None and not _asr_failed:
            # 引擎选择:GALAXY_ASR_ENGINE = auto(默认,中文 CPU 首选 SenseVoice,
            # 缺包退 Whisper) | sensevoice | whisper。装了 funasr 即自动升级到 SenseVoice。
            choice = os.getenv("GALAXY_ASR_ENGINE", "auto").strip().lower()
            if choice == "whisper":
                _asr_singleton = _try_whisper()
            elif choice == "sensevoice":
                _asr_singleton = _try_sensevoice() or _try_whisper()
            else:  # auto
                _asr_singleton = _try_sensevoice() or _try_whisper()
            if _asr_singleton is None:
                logger.debug("ASR 初始化失败,听将降级为'有声音但未转写'")
                _asr_failed = True
            else:
                logger.info("ASR 引擎: %s", type(_asr_singleton).__name__)
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

        def _collect(rframes) -> None:
            # PyAV 版本差异:resample() 可能返回单个 AudioFrame 或帧列表。统一处理。
            if rframes is None:
                return
            if not isinstance(rframes, (list, tuple)):
                rframes = [rframes]
            for rframe in rframes:
                if rframe is None:
                    continue
                arr = rframe.to_ndarray()  # shape (1, n) int16
                samples.append(arr.reshape(-1))

        for frame in container.decode(audio=0):
            _collect(resampler.resample(frame))
        # 关键:冲刷重采样器内部缓冲——否则每段音频结尾几十毫秒(可能是最后一个词)
        # 被静默丢弃,Whisper 根本看不到。
        try:
            _collect(resampler.resample(None))
        except Exception:  # noqa: BLE001 — 个别版本不支持 flush,忽略
            pass

        if not samples:
            return None
        pcm = np.concatenate(samples).astype(np.float32) / 32768.0
        return pcm
    except Exception as exc:  # noqa: BLE001
        logger.debug("音频解码失败: %s", exc)
        return None


def transcribe_b64(audio_b64: str, *, mime: str = "audio/webm", language: str = "zh") -> Optional[str]:
    """base64 音频 → 文字（听的实现）。任何环节不可用则返回 None（优雅降级）。

    收口:B 档原生后端激活时,优先让【全模态模型自己听懂】音频(而非 Whisper 转写)
    ——这是"原生听"落到消费文本的循环上的形态。server 不可达/失败则回落 Whisper,
    绝不因原生失败而丢掉这段音频。A 档(无原生后端)直接走 Whisper,行为不变。
    """
    if not audio_b64:
        return None
    try:
        from core.native_modal import get_active_backend

        be = get_active_backend()
        if be is not None:
            native_text = be.understand_audio(audio_b64, mime=mime, language=language)
            if native_text:
                return native_text
            # 原生返回空 → 回落 Whisper,不静默丢句
    except Exception as exc:  # noqa: BLE001
        logger.debug("原生听不可用,回落 Whisper: %s", exc)
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
