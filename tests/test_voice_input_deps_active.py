"""tests/test_voice_input_deps_active.py
=========================================
麦克风"对它说话没反应"的回归防护。

根因:桌面语音输入闭环 core/voice_loop.py 用 sounddevice 采集 + faster-whisper 转写。
而 faster-whisper 曾被注释出默认 requirements → WhisperASR import 失败 →
start_voice_interaction() 返回 False → 常开监听循环从不启动 → 说话毫无反应。

"语音闭环三件套"(麦克风 sounddevice / ASR faster-whisper / TTS edge-tts)必须【同为
默认装机依赖】,三缺一都会让语音交互静默失效。本测试锁死三者在 requirements.txt 里
均为激活(未注释)状态,防止再次因少装一个而整条哑掉。
"""

from __future__ import annotations

import pathlib

_REQ = pathlib.Path(__file__).resolve().parents[1] / "requirements.txt"


def _active_packages() -> set:
    names = set()
    for raw in _REQ.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # 取包名(去掉版本/注释/extras)
        token = line.split("#", 1)[0].strip()
        for sep in ("==", ">=", "<=", "~=", ">", "<", "[", ";", " "):
            if sep in token:
                token = token.split(sep, 1)[0]
        if token:
            names.add(token.lower())
    return names


def test_voice_loop_dependencies_are_active():
    active = _active_packages()
    for pkg in ("sounddevice", "edge-tts", "faster-whisper"):
        assert pkg in active, (
            f"语音闭环依赖 {pkg} 未在 requirements.txt 激活 —— 三缺一会让"
            f"麦克风/语音交互静默失效(对它说话没反应)。当前激活集: {sorted(active)}"
        )
