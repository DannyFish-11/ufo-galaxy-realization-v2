"""core/tts/melo_engine.py — 离线中英混读 TTS（MeloTTS）
========================================================

A 档(无卡/离线)"说"的音质档:MeloTTS 是 VITS 系,CPU 秒级合成,中英混读自然流畅
(像"我看了 Avengers Endgame"这种夹杂句发音也不生硬)。相较 Piper(纯 onnx、更轻但更糙),
它中文自然度明显更好;相较 edge-tts,它完全离线、数据不出设备。

接口与 :class:`core.tts.piper_engine.PiperTTSEngine` / EdgeTTSEngine 对齐
(``synthesize -> wav 路径`` / ``_play_audio`` / ``synthesize_and_play`` / ``stop``),
可被 ``speech_output`` / StreamingSpeaker 直接复用。

真机需要::

    pip install melotts            # myshell-ai/MeloTTS(MIT)
    python -m unidic download      # 日文/分词依赖(中英可跳过,视安装而定)
    # 首次 TTS(language=...) 自动下载对应语言模型(可用 GALAXY_HF_ENDPOINT 加速)

缺包/加载失败一律**优雅降级**(available()=False,synthesize 返回 None),绝不抛出。
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import List, Optional

logger = logging.getLogger("Galaxy.TTS.Melo")


class MeloTTSEngine:
    """离线 MeloTTS。接口对齐 PiperTTSEngine(synthesize/_play_audio/stop)。"""

    def __init__(
        self,
        language: Optional[str] = None,
        speaker: Optional[str] = None,
        speed: Optional[float] = None,
        device: Optional[str] = None,
    ) -> None:
        # 语言:ZH_MIX_EN(中英混读,默认) / ZH / EN / JP / KR / ES / FR。
        self.language = language or os.getenv("GALAXY_MELO_LANG", "ZH_MIX_EN")
        # 说话人 key(留空取该语言首个音色);speed 建议 0.8~1.2(见踩坑:调太快中文糊)。
        self.speaker = speaker or os.getenv("GALAXY_MELO_SPEAKER", "")
        try:
            self.speed = float(os.getenv("GALAXY_MELO_SPEED", str(speed or 1.0)))
        except (ValueError, TypeError):
            self.speed = 1.0
        self.device = device or os.getenv("GALAXY_MELO_DEVICE", "auto")
        self._model = None
        self._spk_id = None
        self._load_failed = False
        self._active_proc = None

    def available(self) -> bool:
        """装了 melo 包即认为可用(模型按需下载/加载,失败再降级)。"""
        if self._load_failed:
            return False
        try:
            import importlib.util

            return importlib.util.find_spec("melo") is not None
        except Exception:  # noqa: BLE001
            return False

    def _ensure_model(self):
        if self._model is not None or self._load_failed:
            return self._model
        try:
            from melo.api import TTS  # 延迟 import:仅装了 melotts 才可用

            dev = self.device
            if dev == "auto":
                try:
                    import torch

                    dev = "cuda" if torch.cuda.is_available() else "cpu"
                except Exception:  # noqa: BLE001
                    dev = "cpu"
            if not os.environ.get("HF_ENDPOINT"):
                os.environ["HF_ENDPOINT"] = os.environ.get("GALAXY_HF_ENDPOINT", "https://hf-mirror.com")
            self._model = TTS(language=self.language, device=dev)
            spk = self._model.hps.data.spk2id  # {说话人名: id}
            if self.speaker and self.speaker in spk:
                self._spk_id = spk[self.speaker]
            else:
                self._spk_id = list(spk.values())[0]
            logger.info("MeloTTS loaded: lang=%s device=%s spk=%s", self.language, dev, self._spk_id)
        except Exception as exc:  # noqa: BLE001
            logger.info("MeloTTS 不可用(需 pip install melotts + 模型): %s", exc)
            self._load_failed = True
        return self._model

    async def synthesize(self, text: str, voice: Optional[str] = None) -> Optional[str]:
        """文本 → wav 临时文件路径;不可用返回 None(优雅降级)。"""
        text = (text or "").strip()
        if not text:
            return None
        m = self._ensure_model()
        if m is None:
            return None

        def _synth() -> Optional[str]:
            try:
                fd, path = tempfile.mkstemp(suffix=".wav", prefix="galaxy_melo_")
                os.close(fd)
                m.tts_to_file(text, self._spk_id, path, speed=self.speed)
                return path
            except Exception as exc:  # noqa: BLE001
                logger.debug("MeloTTS 合成失败: %s", exc)
                return None

        return await asyncio.to_thread(_synth)

    async def _play_audio(self, wav_path: str) -> None:
        """播放 wav。Linux: aplay/paplay/ffplay;macOS: afplay;Windows: PowerShell。"""
        import sys

        if not wav_path or not os.path.exists(wav_path):
            return
        play_cmd: List[str] = []
        if sys.platform == "darwin":
            play_cmd = ["afplay", wav_path]
        elif sys.platform == "win32":
            play_cmd = ["powershell", "-c", f"(New-Object Media.SoundPlayer '{wav_path}').PlaySync();"]
        else:
            for cand in (
                ["aplay", "-q", wav_path],
                ["paplay", wav_path],
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", wav_path],
            ):
                if self._command_exists(cand[0]):
                    play_cmd = cand
                    break
        if not play_cmd:
            logger.debug("无可用 wav 播放器(装 alsa-utils/ffmpeg),跳过")
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                *play_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            self._active_proc = proc
            await proc.wait()
        except Exception as exc:  # noqa: BLE001
            logger.debug("MeloTTS 播放失败: %s", exc)
        finally:
            self._active_proc = None

    async def synthesize_and_play(self, text: str, voice: Optional[str] = None) -> None:
        path = await self.synthesize(text, voice)
        if path:
            try:
                await self._play_audio(path)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

    async def stop(self) -> None:
        """barge-in:掐断当前播放。"""
        proc = self._active_proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _command_exists(cmd: str) -> bool:
        import shutil

        return shutil.which(cmd) is not None
