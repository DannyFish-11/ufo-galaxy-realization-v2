"""
core.tts.edge_tts_engine — 语音合成（edge-tts）
====================================================
免费的微软Edge TTS服务，支持中文和多种声音。

依赖:
    pip install edge-tts

支持的中文声音:
    - zh-CN-XiaoxiaoNeural  (女声，温柔)
    - zh-CN-XiaohanNeural   (女声，冷静)
    - zh-CN-YunxiNeural     (男声，年轻)
    - zh-CN-YunjianNeural   (男声，新闻)
    - zh-CN-XiaoyiNeural    (童声)
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger("Galaxy.TTS")


class EdgeTTSEngine:
    """Edge TTS 语音合成引擎。

    基于微软Edge浏览器的免费TTS服务，无需API密钥。

    支持的中文声音:
    - zh-CN-XiaoxiaoNeural  (女声，温柔)
    - zh-CN-XiaohanNeural   (女声，冷静)
    - zh-CN-YunxiNeural     (男声，年轻)
    - zh-CN-YunjianNeural   (男声，新闻)
    - zh-CN-XiaoyiNeural    (童声)

    使用示例::

        import asyncio
        tts = EdgeTTSEngine(voice="zh-CN-XiaoxiaoNeural")
        mp3_path = await tts.synthesize("你好，Galaxy！")
        # 播放
        await tts.synthesize_and_play("你好，Galaxy！")
    """

    # 中文声音列表
    CHINESE_VOICES = [
        "zh-CN-XiaoxiaoNeural",   # 女声，温柔
        "zh-CN-XiaohanNeural",    # 女声，冷静
        "zh-CN-YunxiNeural",      # 男声，年轻
        "zh-CN-YunjianNeural",    # 男声，新闻
        "zh-CN-XiaoyiNeural",     # 童声
    ]

    # 语速选项
    RATE_SLOW = "-25%"
    RATE_NORMAL = "+0%"
    RATE_FAST = "+25%"

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        proxy: Optional[str] = None,
    ) -> None:
        """初始化Edge TTS引擎。

        Args:
            voice: 声音ID，默认中文女声 XiaoxiaoNeural。
            rate: 语速调整 (如 "+0%", "-25%", "+25%")。
            volume: 音量调整 (如 "+0%", "-25%", "+25%")。
            proxy: 代理服务器地址 (如 "http://127.0.0.1:7890")。
        """
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.proxy = proxy
        self._play_lock = asyncio.Lock()

    async def synthesize(
        self,
        text: str,
        output_path: Optional[str] = None,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
    ) -> str:
        """文字 → 语音文件路径。

        Args:
            text: 要合成的文字。
            output_path: 输出MP3文件路径，None则创建临时文件。
            voice: 临时覆盖声音ID。
            rate: 临时覆盖语速。

        Returns:
            生成的MP3文件绝对路径。
        """
        try:
            import edge_tts
        except ImportError as exc:
            raise ImportError(
                "edge-tts is not installed. "
                "Install it with: pip install edge-tts"
            ) from exc

        if not output_path:
            # M3 fixed: use NamedTemporaryFile with delete=False for explicit cleanup
            _tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            _tmp.close()
            output_path = _tmp.name

        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        use_voice = voice or self.voice
        use_rate = rate or self.rate

        communicate = edge_tts.Communicate(
            text,
            use_voice,
            rate=use_rate,
            volume=self.volume,
            proxy=self.proxy,
        )
        await communicate.save(output_path)
        logger.debug("TTS synthesized: '%s...' → %s", text[:50], output_path)
        return output_path

    async def synthesize_and_play(
        self,
        text: str,
        output_path: Optional[str] = None,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        cleanup: bool = True,
    ) -> str:
        """文字 → 合成 → 播放。

        Args:
            text: 要合成的文字。
            output_path: 输出MP3文件路径，None则创建临时文件。
            voice: 临时覆盖声音ID。
            rate: 临时覆盖语速。
            cleanup: 播放后是否删除临时文件。

        Returns:
            生成的MP3文件路径。
        """
        mp3_path = await self.synthesize(text, output_path, voice, rate)
        await self._play_audio(mp3_path)

        if cleanup and (output_path is None):
            try:
                os.remove(mp3_path)
                logger.debug("Cleaned up temporary audio file: %s", mp3_path)
            except OSError as exc:
                logger.debug("Failed to cleanup temp file: %s", exc)

        return mp3_path

    async def _play_audio(self, mp3_path: str) -> None:
        """播放音频文件（跨平台）。

        支持 Windows / macOS / Linux。
        Linux需要安装 mpg123 或 ffplay。

        Args:
            mp3_path: MP3文件路径。
        """
        system = platform.system()
        play_cmd: List[str] = []

        if system == "Windows":
            # Windows: 使用 PowerShell 播放
            play_cmd = [
                "powershell",
                "-c",
                f"Add-Type -AssemblyName presentationCore; "
                f"$player = New-Object System.Windows.Media.MediaPlayer; "
                f"$player.Open('{mp3_path}'); "
                f"$player.Play(); "
                f"Start-Sleep -Milliseconds 500; "
                f"while ($player.Position -lt $player.NaturalDuration.TimeSpan) "
                f"{{ Start-Sleep -Milliseconds 100 }}; "
                f"$player.Stop()",
            ]
        elif system == "Darwin":  # macOS
            play_cmd = ["afplay", mp3_path]
        else:  # Linux
            # 优先尝试 mpg123，然后是 ffplay，最后是 aplay
            if self._command_exists("mpg123"):
                play_cmd = ["mpg123", "-q", mp3_path]
            elif self._command_exists("ffplay"):
                play_cmd = [
                    "ffplay",
                    "-nodisp",
                    "-nostats",
                    "-hide_banner",
                    "-autoexit",
                    mp3_path,
                ]
            elif self._command_exists("aplay"):
                # 需要先把MP3转成WAV
                if self._command_exists("ffmpeg"):
                    wav_path = mp3_path.replace(".mp3", "_temp.wav")
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", mp3_path, wav_path],
                        capture_output=True,
                        check=True,
                    )
                    play_cmd = ["aplay", "-q", wav_path]
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass
                else:
                    logger.warning(
                        "No audio player found. Install mpg123 or ffmpeg."
                    )
                    return
            else:
                logger.warning(
                    "No audio player found on Linux. "
                    "Install mpg123: sudo apt-get install mpg123"
                )
                return

        if play_cmd:
            logger.debug("Playing audio with: %s", " ".join(play_cmd[:2]))
            proc = await asyncio.create_subprocess_exec(
                *play_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(
                    "Audio playback failed (code=%d): %s",
                    proc.returncode,
                    stderr.decode("utf-8", errors="replace")[:200],
                )

    def _command_exists(self, cmd: str) -> bool:
        """检查系统命令是否可用。

        Args:
            cmd: 命令名称。

        Returns:
            命令是否可用。
        """
        try:
            subprocess.run(
                [cmd, "--version"],
                capture_output=True,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @classmethod
    async def list_voices(cls, language: Optional[str] = None) -> List[dict]:
        """列出可用的TTS声音。

        Args:
            language: 语言过滤 (如 "zh-CN")，None则返回所有。

        Returns:
            声音信息列表。
        """
        import edge_tts
        voices_manager = await edge_tts.VoicesManager.create()
        voices = voices_manager.voices
        if language:
            voices = [v for v in voices if v.get("Locale", "").startswith(language)]
        return voices

    @classmethod
    def get_chinese_voices(cls) -> List[str]:
        """获取支持的中文声音列表。

        Returns:
            中文声音ID列表。
        """
        return cls.CHINESE_VOICES.copy()

    def set_voice(self, voice: str) -> None:
        """设置默认声音。

        Args:
            voice: 声音ID。
        """
        self.voice = voice
        logger.debug("TTS voice set to: %s", voice)

    def set_rate(self, rate: str) -> None:
        """设置语速。

        Args:
            rate: 语速调整 (如 "+0%", "-25%", "+25%")。
        """
        self.rate = rate
        logger.debug("TTS rate set to: %s", rate)

    def __repr__(self) -> str:
        return (
            f"EdgeTTSEngine(voice={self.voice}, "
            f"rate={self.rate}, volume={self.volume})"
        )
