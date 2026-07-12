"""core.tts.kokoro_engine — Kokoro-82M 离线高质量语音合成
============================================================

**定位:** edge-tts(云端)不可达时的**首选离线引擎**——82M 参数、Apache 2.0、
纯 CPU 快于实时、支持中文嗓音;音质远好于 Windows SAPI 机器人音。引擎链:
``edge → melo → piper → kokoro → sapi``。

依赖: pip install kokoro-onnx (requirements.txt 已含);模型文件两枚:
  - kokoro-v1.0.onnx  (~310MB, GALAXY_KOKORO_MODEL 可换 int8 版)
  - voices-v1.0.bin   (~27MB 音色向量包)
存放于 models/kokoro/(GALAXY_KOKORO_DIR 可改)。缺文件时 available()=False,
并(默认)自动踢一个后台线程经 huggingface_hub 拉取(支持 HF_ENDPOINT 镜像,
GALAXY_KOKORO_AUTOFETCH=0 关闭);下载完成后下次引擎选择/进程重启即生效。

合成是 CPU 密集(onnxruntime),放 asyncio.to_thread,不占事件循环。播放/打断
继承 EdgeTTSEngine 跨平台实现。任何运行期失败都由 speech_output 的降级链
兜底(→ sapi),绝不让语音整段静默。
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Optional

from .edge_tts_engine import EdgeTTSEngine

logger = logging.getLogger("Galaxy.TTS.Kokoro")

_HF_REPO = "fastrtc/kokoro-onnx"   # kokoro-onnx 官方发布件的 HF 镜像(可走国内 HF_ENDPOINT)
_MODEL_FILE_DEFAULT = "kokoro-v1.0.onnx"
_VOICES_FILE = "voices-v1.0.bin"

_fetch_lock = threading.Lock()
_fetch_started = False


def _model_dir() -> Path:
    return Path(os.environ.get("GALAXY_KOKORO_DIR", "models/kokoro"))


def _model_file() -> str:
    return os.environ.get("GALAXY_KOKORO_MODEL", _MODEL_FILE_DEFAULT)


def model_files_present() -> bool:
    d = _model_dir()
    return (d / _model_file()).exists() and (d / _VOICES_FILE).exists()


def kick_background_fetch() -> None:
    """后台线程拉取模型文件(幂等,至多一次;GALAXY_KOKORO_AUTOFETCH=0 关闭)。"""
    global _fetch_started
    if os.environ.get("GALAXY_KOKORO_AUTOFETCH", "1").strip().lower() in (
        "0", "false", "no", "off",
    ):
        return
    with _fetch_lock:
        if _fetch_started or model_files_present():
            return
        _fetch_started = True

    def _fetch() -> None:
        try:
            from huggingface_hub import hf_hub_download
            d = _model_dir()
            d.mkdir(parents=True, exist_ok=True)
            for fname in (_model_file(), _VOICES_FILE):
                if (d / fname).exists():
                    continue
                logger.info("Kokoro 模型文件后台拉取中: %s", fname)
                got = hf_hub_download(repo_id=_HF_REPO, filename=fname)
                # 落到目标目录(hf 缓存 → 稳定路径,拷贝而非软链,便于用户迁移)
                import shutil
                shutil.copyfile(got, d / fname)
            logger.info("Kokoro 模型就绪(%s)——下次语音引擎选择/重启后启用", _model_dir())
        except Exception as exc:  # noqa: BLE001
            logger.info("Kokoro 模型拉取失败(下次启动再试): %s", exc)

    threading.Thread(target=_fetch, name="kokoro-fetch", daemon=True).start()


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


class KokoroTTSEngine(EdgeTTSEngine):
    """Kokoro-82M ONNX 离线合成引擎(播放/打断继承 EdgeTTSEngine)。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._kokoro: Optional[Any] = None
        self._voices: Optional[list] = None

    def available(self) -> bool:
        """包可导入且模型文件就位才可用;缺文件时顺手踢一次后台拉取。"""
        try:
            import kokoro_onnx  # noqa: F401
        except Exception:
            return False
        if not model_files_present():
            kick_background_fetch()
            return False
        return True

    def _ensure_loaded(self) -> Any:
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            d = _model_dir()
            self._kokoro = Kokoro(str(d / _model_file()), str(d / _VOICES_FILE))
            try:
                self._voices = sorted(self._kokoro.get_voices())
            except Exception:  # noqa: BLE001
                self._voices = []
            logger.info("Kokoro 引擎已加载(%d 个音色)", len(self._voices or []))
        return self._kokoro

    def _pick_voice(self, text: str) -> str:
        env_voice = os.environ.get("GALAXY_KOKORO_VOICE", "").strip()
        voices = self._voices or []
        if env_voice and (not voices or env_voice in voices):
            return env_voice
        prefixes = ("zf_", "zm_") if _has_cjk(text) else ("af_", "am_", "bf_", "bm_")
        for p in prefixes:
            for v in voices:
                if v.startswith(p):
                    return v
        return voices[0] if voices else "af_sarah"

    async def synthesize(
        self,
        text: str,
        output_path: Optional[str] = None,
        voice: Optional[str] = None,
        rate: Optional[str] = None,   # 接口兼容;Kokoro 用 speed 概念,此处不映射
    ) -> str:
        def _run() -> str:
            kokoro = self._ensure_loaded()
            use_voice = voice or self._pick_voice(text)
            lang = os.environ.get(
                "GALAXY_KOKORO_LANG", "cmn" if _has_cjk(text) else "en-us",
            )
            samples, sample_rate = kokoro.create(text, voice=use_voice, lang=lang)
            path = output_path
            if not path:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                path = tmp.name
            import numpy as np
            pcm = np.clip(samples, -1.0, 1.0)
            pcm16 = (pcm * 32767.0).astype("<i2")
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(int(sample_rate))
                wf.writeframes(pcm16.tobytes())
            return path

        # onnxruntime 推理是 CPU 密集同步调用,放线程,绝不占事件循环。
        path = await asyncio.to_thread(_run)
        logger.debug("Kokoro synthesized: '%s...' → %s", text[:30], path)
        return path
