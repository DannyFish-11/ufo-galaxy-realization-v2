"""core/tts/piper_engine.py — 离线本地 TTS（Piper）
====================================================

A 档(无卡/断网)的"说"兜底:Piper 是纯 CPU、实时、离线的神经 TTS(树莓派都能跑),
不依赖网络(区别于 edge-tts 要连微软)。接口与 EdgeTTSEngine 对齐,能直接被
speech_output / StreamingSpeaker 复用。

真机需要:``pip install piper-tts`` + 一个中文语音模型(.onnx + .onnx.json)。
模型路径由 ``GALAXY_PIPER_MODEL`` 指定,或放在 ``models/piper/`` 下自动发现。
缺包/缺模型时**优雅降级**(synthesize 返回 None,speak 静默跳过),绝不抛出。
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import tempfile
from typing import List, Optional

logger = logging.getLogger("Galaxy.TTS.Piper")


def _discover_model() -> Optional[str]:
    """找一个 piper 语音模型(.onnx)。优先 GALAXY_PIPER_MODEL,否则 models/piper/。"""
    env = os.getenv("GALAXY_PIPER_MODEL", "").strip()
    if env and os.path.exists(env):
        return env
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for pat in ("models/piper/*zh*.onnx", "models/piper/*.onnx", "models/*.onnx"):
        hits = sorted(glob.glob(os.path.join(root, pat)))
        if hits:
            return hits[0]
    return None


class PiperTTSEngine:
    """离线 Piper TTS。接口对齐 EdgeTTSEngine(synthesize/_play_audio/stop)。"""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or _discover_model()
        self._voice = None
        self._active_proc = None
        self._load_failed = False

    def available(self) -> bool:
        return self.model_path is not None and not self._load_failed

    def _ensure_voice(self):
        if self._voice is not None or self._load_failed:
            return self._voice
        if not self.model_path:
            self._load_failed = True
            return None
        try:
            from piper import PiperVoice  # 延迟 import:仅装了 piper-tts 才可用

            self._voice = PiperVoice.load(self.model_path)
        except Exception as exc:  # noqa: BLE001
            logger.info("Piper 不可用(需 pip install piper-tts + 语音模型): %s", exc)
            self._load_failed = True
        return self._voice

    async def synthesize(self, text: str, voice: Optional[str] = None) -> Optional[str]:
        """文本 → wav 临时文件路径;不可用返回 None(优雅降级)。"""
        text = (text or "").strip()
        if not text:
            return None
        v = self._ensure_voice()
        if v is None:
            return None

        def _synth() -> Optional[str]:
            import wave

            try:
                fd, path = tempfile.mkstemp(suffix=".wav", prefix="galaxy_piper_")
                os.close(fd)
                with wave.open(path, "wb") as wf:
                    v.synthesize(text, wf)
                return path
            except Exception as exc:  # noqa: BLE001
                logger.debug("Piper 合成失败: %s", exc)
                return None

        return await asyncio.to_thread(_synth)

    async def _play_audio(self, wav_path: str) -> None:
        """播放 wav。Linux: aplay/ffplay/paplay;macOS: afplay;Windows: PowerShell。"""
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
            logger.debug("Piper 播放失败: %s", exc)
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
