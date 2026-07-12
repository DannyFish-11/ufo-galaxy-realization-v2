"""core.tts.sapi_engine — Windows 系统自带语音合成(SAPI)兜底引擎
==================================================================

**为什么存在:** 默认的 edge-tts 走微软云端服务,在部分网络环境(代理/封锁/离线)
下【合成必然失败】——而且失败发生在运行期,引擎选择阶段看不出来。真机表现就是
"回复文字出来了,一句话都不说"。本引擎用 Windows 自带的 System.Speech(SAPI),
**零 pip 依赖、完全离线**,任何一台 Windows 都能出声(中文系统自带 Huihui 等中文
嗓音),作为 speech_output 引擎链的最后兜底。

实现:PowerShell 子进程调 System.Speech.Synthesis.SpeechSynthesizer,文本经
stdin 传入(避免引号转义地狱),SetOutputToWaveFile 落成 wav;播放/打断复用
EdgeTTSEngine 的跨平台播放器(继承)。非 Windows 平台 available() 恒 False。
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import subprocess
import tempfile
from typing import Optional

from .edge_tts_engine import EdgeTTSEngine

logger = logging.getLogger("Galaxy.TTS.Sapi")

# PowerShell 脚本:stdin(UTF-8) 读文本 → 优先选中文嗓音 → 合成到 wav。
_PS_SYNTH = (
    "[Console]::InputEncoding=[System.Text.Encoding]::UTF8; "
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$v = $s.GetInstalledVoices() | Where-Object "
    "{ $_.VoiceInfo.Culture.Name -like 'zh*' } | Select-Object -First 1; "
    "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
    "$s.SetOutputToWaveFile($env:GALAXY_SAPI_OUT); "
    "$s.Speak([Console]::In.ReadToEnd()); "
    "$s.Dispose()"
)


class SapiTTSEngine(EdgeTTSEngine):
    """Windows SAPI 离线合成引擎(播放/打断继承 EdgeTTSEngine 的跨平台实现)。

    只覆写【合成】:文字 → 本地 SAPI → wav 文件;``synthesize_and_play`` 继承
    自父类(其内部调 ``self.synthesize`` → 走到这里的覆写),无需重复实现。
    """

    def available(self) -> bool:
        """仅 Windows 可用(System.Speech 是 .NET/Windows 组件)。"""
        return platform.system() == "Windows"

    async def synthesize(
        self,
        text: str,
        output_path: Optional[str] = None,
        voice: Optional[str] = None,   # SAPI 自动选中文嗓音;参数保留接口兼容
        rate: Optional[str] = None,
    ) -> str:
        if not self.available():
            raise RuntimeError("SAPI TTS 仅支持 Windows")
        _tmp_created = False
        if not output_path:
            _tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            _tmp.close()
            output_path = _tmp.name
            _tmp_created = True
        output_path = os.path.abspath(output_path)

        env = {**os.environ, "GALAXY_SAPI_OUT": output_path}
        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SYNTH,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=env,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(text.encode("utf-8")), timeout=30.0,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    "SAPI 合成失败(code=%s): %s" % (
                        proc.returncode,
                        (stderr or b"").decode("utf-8", errors="replace")[:200],
                    )
                )
            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError("SAPI 合成产物为空")
        except Exception:
            if _tmp_created:
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            raise
        logger.debug("SAPI synthesized: '%s...' → %s", text[:30], output_path)
        return output_path
