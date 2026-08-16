#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/tts/watermark.py — 合成音频的不可听水印
==============================================

**为什么这件事值得做:** 这个系统能克隆任意音色(``indextts`` 零样本克隆,给一段
参考 wav 即可),又能控制 Android 设备。一个既能复刻别人声音、又能实际操作设备的
系统,生成完全无标记的音频是个真实的风险面——不只是合规问题。

水印用 `AudioSeal <https://github.com/facebookresearch/audioseal>`_(Meta 开源,
MIT):在波形里嵌入不可听的神经水印,能扛住压缩与转码,事后可检测。

三条设计取舍
------------
1. **可选依赖,缺了不炸。** ``audioseal`` / ``torch`` 都不随仓库分发。缺任何一个,
   合成照常出声,只是没有水印——**但会明确说出来**,不静默略过。
2. **默认只给克隆音色打。** ``cloned_only`` 是默认档:克隆音色是风险的来源,
   而给每一句系统提示音都跑一遍神经网络是不必要的开销。
3. **"没打上"必须是可观测的结果,不是沉默。** :class:`WatermarkResult` 明确区分
   "打上了" / "按策略跳过" / "想打但打不了",三者含义完全不同。把它们混成一个
   "没有水印"正是本轮改造一直在消除的那类缺陷。

严格档
------
默认情况下水印失败**不阻断合成**——对一个语音助手来说,哑掉比没水印更糟。
但需要强保证的部署可以开 ``GALAXY_TTS_WATERMARK_STRICT=1``:此时克隆音色一旦
打不上水印,合成即失败,**绝不输出无标记的克隆音频**。
"""

from __future__ import annotations

import logging
import os
import shutil
import wave
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.TTS.Watermark")

__all__ = [
    "WATERMARK_SILENT_SKIP_IS_FORBIDDEN_POLICY",
    "WATERMARK_NEVER_SILENCES_SPEECH_POLICY",
    "WATERMARK_CLONED_VOICES_ARE_THE_TARGET_POLICY",
    "MODE_OFF",
    "MODE_CLONED_ONLY",
    "MODE_ALWAYS",
    "CLONING_ENGINES",
    "get_watermark_mode",
    "strict_mode_enabled",
    "WatermarkResult",
    "should_watermark",
    "apply_watermark",
    "watermark_backend_available",
]


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

WATERMARK_SILENT_SKIP_IS_FORBIDDEN_POLICY: str = (
    "TTS_WATERMARK::POLICY_1: "
    "A WatermarkResult distinguishes applied / skipped-by-policy / wanted-but-failed. "
    "Collapsing those into a bare 'no watermark' would hide the one case that "
    "matters — the system wanted to mark cloned audio and could not."
)

WATERMARK_NEVER_SILENCES_SPEECH_POLICY: str = (
    "TTS_WATERMARK::POLICY_2: "
    "Watermarking failure never breaks synthesis in the default configuration: a "
    "voice assistant going mute is worse than unmarked audio.  Deployments needing "
    "the hard guarantee set GALAXY_TTS_WATERMARK_STRICT=1, which turns a failure on "
    "a cloned voice into a synthesis failure rather than unmarked output."
)

WATERMARK_CLONED_VOICES_ARE_THE_TARGET_POLICY: str = (
    "TTS_WATERMARK::POLICY_3: "
    "The default mode marks cloned voices only.  Cloning is where the risk lives; "
    "running a neural watermarker over every system prompt is cost without benefit."
)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

MODE_OFF: str = "off"
MODE_CLONED_ONLY: str = "cloned_only"
MODE_ALWAYS: str = "always"

_VALID_MODES = (MODE_OFF, MODE_CLONED_ONLY, MODE_ALWAYS)
_ENV_MODE = "GALAXY_TTS_WATERMARK"
_ENV_STRICT = "GALAXY_TTS_WATERMARK_STRICT"

CLONING_ENGINES = frozenset({"indextts", "IndexTTSEngine"})
"""Engines that reproduce a supplied voice.

``indextts`` is currently the only zero-shot cloning engine wired in
(``GALAXY_INDEXTTS_REF_AUDIO`` points at the voice to copy).  Both the config key
and the class name are listed so callers can pass either."""


def get_watermark_mode() -> str:
    """Resolve watermark mode; unknown values degrade to the default, not to off.

    Degrading to ``off`` would let a typo silently disable a safety feature.
    """
    raw = os.getenv(_ENV_MODE, MODE_CLONED_ONLY).strip().lower()
    if raw in _VALID_MODES:
        return raw
    logger.warning("%s=%r is not one of %s — using %r", _ENV_MODE, raw, _VALID_MODES, MODE_CLONED_ONLY)
    return MODE_CLONED_ONLY


def strict_mode_enabled() -> bool:
    """Whether a watermark failure on a cloned voice must fail the synthesis."""
    return os.getenv(_ENV_STRICT, "0").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class WatermarkResult:
    """What actually happened to this audio file.

    ``applied=False`` alone is not an answer — ``skipped_reason`` says whether the
    system chose not to mark it or wanted to and could not (POLICY_1).
    """

    applied: bool = False
    wanted: bool = False
    backend: str = ""
    skipped_reason: str = ""
    path: str = ""

    @property
    def failed_despite_wanting(self) -> bool:
        """The case that matters: we intended to mark this audio and did not."""
        return self.wanted and not self.applied

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied,
            "wanted": self.wanted,
            "backend": self.backend,
            "skipped_reason": self.skipped_reason,
            "failed_despite_wanting": self.failed_despite_wanting,
        }


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


def watermark_backend_available() -> Tuple[bool, str]:
    """Is AudioSeal usable here?  Returns ``(available, reason_when_not)``."""
    try:
        import torch  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"torch 未安装({exc.__class__.__name__})"
    try:
        import audioseal  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"audioseal 未安装({exc.__class__.__name__});pip install audioseal"
    return True, ""


def should_watermark(engine_name: str = "", *, mode: Optional[str] = None) -> bool:
    """Does policy call for watermarking audio produced by *engine_name*?"""
    resolved = mode or get_watermark_mode()
    if resolved == MODE_OFF:
        return False
    if resolved == MODE_ALWAYS:
        return True
    return bool(engine_name) and engine_name in CLONING_ENGINES


def _read_wav_mono_float(path: str):
    """Read a PCM wav into (float32 mono ndarray, sample_rate).

    Stdlib ``wave`` only — the cloning engine (indextts) writes wav, so the format
    that actually needs marking needs no extra decoder.
    """
    import numpy as np

    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        raise ValueError(f"仅支持 16-bit PCM wav(当前 {width * 8}-bit)")
    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def _write_wav_mono_float(path: str, samples, rate: int) -> None:
    import numpy as np

    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(rate))
        wf.writeframes(pcm.tobytes())


def apply_watermark(path: str, *, engine_name: str = "", mode: Optional[str] = None) -> WatermarkResult:
    """Embed an inaudible watermark into the audio at *path*, in place.

    Never raises.  Returns a :class:`WatermarkResult` that always states what
    happened — including, importantly, when marking was wanted but impossible.

    Writes via a temporary file and only replaces the original on success, so a
    failure mid-encode cannot leave a truncated audio file behind.
    """
    wanted = should_watermark(engine_name, mode=mode)
    result = WatermarkResult(wanted=wanted, path=path)
    if not wanted:
        result.skipped_reason = f"策略未要求(mode={mode or get_watermark_mode()}, engine={engine_name or '?'})"
        return result

    if not path or not os.path.exists(path):
        result.skipped_reason = "音频文件不存在"
        logger.warning("水印跳过:%s", result.skipped_reason)
        return result

    if not path.lower().endswith(".wav"):
        # Deliberately not transcoding here: pulling in a full decode/encode path
        # for a format the cloning engine does not produce would add a dependency
        # and a failure mode for no gain. Said out loud rather than skipped quietly.
        result.skipped_reason = f"当前仅对 wav 加水印(实际 {os.path.splitext(path)[1] or '未知'})"
        logger.warning("水印跳过:%s — 该音频将不带标记", result.skipped_reason)
        return result

    available, why = watermark_backend_available()
    if not available:
        result.skipped_reason = why
        logger.warning("想给克隆音色加水印但后端不可用:%s — 该音频将不带标记", why)
        return result

    tmp_path = f"{path}.wm.tmp.wav"
    try:
        import torch
        from audioseal import AudioSeal

        samples, rate = _read_wav_mono_float(path)
        if samples.size == 0:
            result.skipped_reason = "音频为空"
            return result

        model = AudioSeal.load_generator("audioseal_wm_16bits")
        tensor = torch.from_numpy(samples).unsqueeze(0).unsqueeze(0)  # (1, 1, T)
        watermarked = model(tensor, sample_rate=int(rate), alpha=1.0)
        out = watermarked.squeeze(0).squeeze(0).detach().cpu().numpy()

        _write_wav_mono_float(tmp_path, out, rate)
        shutil.move(tmp_path, path)
        result.applied = True
        result.backend = "audioseal"
        logger.info("已为克隆音色音频嵌入 AudioSeal 水印:%s", os.path.basename(path))
        return result
    except Exception as exc:  # noqa: BLE001 — 水印失败绝不能让合成整体失败(POLICY_2)
        result.skipped_reason = f"加水印失败:{exc}"
        logger.warning("想加水印但失败:%s — 该音频将不带标记", exc)
        return result
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
