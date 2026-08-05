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

_HF_REPO = "fastrtc/kokoro-onnx"  # kokoro-onnx 官方发布件的 HF 镜像(可走国内 HF_ENDPOINT)
_MODEL_FILE_DEFAULT = "kokoro-v1.0.onnx"
_VOICES_FILE = "voices-v1.0.bin"

_fetch_lock = threading.Lock()
_fetch_started = False


def _model_dir() -> Path:
    # `or` 而非 get 的默认参数:这两把键已登记进面板,用户把输入框清空存回来就是
    # ``GALAXY_KOKORO_DIR=``(空串,不是未设)。get 的默认值对空串不生效 —— 那样会
    # 拿到 Path("") / 文件名 ""，模型永远找不到。与 core/hf_endpoint.py 同一写法。
    return Path(os.environ.get("GALAXY_KOKORO_DIR", "").strip() or "models/kokoro")


def _model_file() -> str:
    return os.environ.get("GALAXY_KOKORO_MODEL", "").strip() or _MODEL_FILE_DEFAULT


def model_files_present() -> bool:
    d = _model_dir()
    return (d / _model_file()).exists() and (d / _VOICES_FILE).exists()


def kick_background_fetch() -> None:
    """后台线程拉取模型文件(幂等,至多一次;GALAXY_KOKORO_AUTOFETCH=0 关闭)。"""
    global _fetch_started
    if os.environ.get("GALAXY_KOKORO_AUTOFETCH", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return
    with _fetch_lock:
        if _fetch_started or model_files_present():
            return
        _fetch_started = True

    def _fetch() -> None:
        # 下载源可靠化(所有者 Windows 真机日志):hf-mirror.com 不可达时,
        # hf_hub_download 会对每个文件 HEAD 3s 超时 × 指数重试 5 次,与
        # faster-whisper 叠加把控制台刷屏。先做 ≤2s 的源健康探测(进程级缓存,
        # 全不可达负缓存 5 分钟),不通就本次跳过预取、允许下次(源恢复后)再试
        # ——模型缺失走懒加载降级,绝不阻塞启动刷屏。
        try:
            from core.hf_endpoint import pick_endpoint

            _ep_ok = bool(pick_endpoint())
        except Exception:  # 探测模块不可用 → 保守按可达处理(沿用旧行为)
            _ep_ok = True
        if not _ep_ok:
            global _fetch_started
            with _fetch_lock:
                _fetch_started = False  # 幂等标记回滚:源恢复后 available() 可再触发
            logger.warning(
                "Kokoro 模型拉取失败(HF 下载源不可达,本次跳过预取、不做多轮重试刷屏):"
                "网络恢复后自动再试;或手动下载 %s 与 %s 放到 %s"
                "(HF 镜像可设 HF_ENDPOINT=https://hf-mirror.com,来源仓库 %s)",
                _model_file(),
                _VOICES_FILE,
                _model_dir(),
                _HF_REPO,
            )
            return
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
            # 真机排查发现:此前只 INFO 级(默认 WARNING 控制台看不到),用户只会
            # 看到"语音降级为系统音"的笼统提示,不知道离线引擎为什么没准备好。
            # 提到 WARNING,并给出可操作的具体路径/文件名/镜像,呼应
            # speech_output._note_engine_choice() 的"手动预置模型"指引。
            logger.warning(
                "Kokoro 模型拉取失败(下次启动再试): %s ——网络受限时可手动下载 %s 与 %s"
                " 放到 %s(HF 镜像可设 HF_ENDPOINT=https://hf-mirror.com,来源仓库 %s)",
                exc,
                _model_file(),
                _VOICES_FILE,
                _model_dir(),
                _HF_REPO,
            )

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
        rate: Optional[str] = None,  # 接口兼容;Kokoro 用 speed 概念,此处不映射
    ) -> str:
        def _run() -> str:
            kokoro = self._ensure_loaded()
            use_voice = voice or self._pick_voice(text)
            # 留空 = 按文本自动判定(中文 cmn / 其余 en-us)。面板上这一项的默认就是
            # 空串,所以空必须走自动分支而不是原样传下去(lang="" 会让 kokoro 报错)。
            lang = os.environ.get("GALAXY_KOKORO_LANG", "").strip() or ("cmn" if _has_cjk(text) else "en-us")
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
