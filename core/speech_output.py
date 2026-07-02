"""
core/speech_output.py — 集中式语音输出(TTS)
=============================================

让 AI 的回复**默认朗读出来**,且不分渠道:语音对话、面板打字、自发目标……只要 handle_request
产出回复,就在这里集中朗读一次。与"听"对称——"说"也默认启用。

- **默认开**;``GALAXY_SPEAK=0`` 关闭。
- **非阻塞**:后台任务朗读,不拖慢请求返回。
- **去重**:短窗口内同一句不重复念(避免多路径重复触发双声)。
- **集中**:语音回路(VoiceLoop)不再各自 TTS,统一走这里,避免一句念两遍。
- **优雅降级**:复用 EdgeTTSEngine;缺 edge-tts / 无音频设备时静默降级,绝不抛出。
- 过长截断(念太久没意义);``GALAXY_TTS_VOICE`` 选嗓音,``GALAXY_SPEAK_MAX_CHARS`` 调长度。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("Galaxy.SpeechOutput")


def speak_enabled() -> bool:
    """默认朗读;GALAXY_SPEAK=0/false/no/off 关闭。"""
    return os.getenv("GALAXY_SPEAK", "1").strip().lower() not in ("0", "false", "no", "off")


_engine: Optional[Any] = None
_engine_failed = False
_last_text = ""
_last_ts = 0.0


def _max_chars() -> int:
    try:
        return max(80, int(os.getenv("GALAXY_SPEAK_MAX_CHARS", "600") or 600))
    except (ValueError, TypeError):
        return 600


def _get_engine() -> Optional[Any]:
    global _engine, _engine_failed
    if _engine is not None or _engine_failed:
        return _engine
    try:
        from core.tts import EdgeTTSEngine
        voice = os.getenv("GALAXY_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
        _engine = EdgeTTSEngine(voice=voice)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTS 引擎不可用(语音输出降级；装 edge-tts 可启用): %s", exc)
        _engine_failed = True
    return _engine


def speak_response(text: str, *, source: str = "") -> None:
    """默认朗读一段回复。非阻塞、去重、降级安全;永不抛出影响主流程。

    Args:
        text: 要朗读的回复文本。
        source: 请求来源("voice"/"chat"/"openclawd"/"e2e"…);自动化测试(e2e)不发声。
    """
    global _last_text, _last_ts
    if not speak_enabled():
        return
    text = (text or "").strip()
    if not text:
        return
    if source in ("e2e", "test"):  # 自动化/测试路径不发声
        return
    # 去重:3 秒内同一句不重复念(多渠道可能重复触发)。
    now = time.monotonic()
    if text == _last_text and (now - _last_ts) < 3.0:
        return
    _last_text, _last_ts = text, now

    spoken = text[: _max_chars()]
    engine = _get_engine()
    if engine is None:
        return

    async def _run() -> None:
        # 播放前后把"正在朗读"同步到桌面三态覆盖层(u_speaking)——此前 TTS 播放
        # 与覆盖层完全脱节：_speaking 只在相位事件里被动带一手且 MANIFEST 一进入
        # 就被强制置 False，而实际播放发生在那之后，覆盖层永远等不到真实信号，
        # 三态动画不随"AI 说话"运转。finally 确保异常/提前返回也一定复位。
        try:
            from core.lumiv_websocket_bridge import set_ai_speaking as _set_speaking
        except Exception:
            _set_speaking = None  # type: ignore
        if _set_speaking is not None:
            _set_speaking(True)
        try:
            await engine.synthesize_and_play(spoken)
        except Exception as exc:  # noqa: BLE001
            logger.debug("语音输出失败(降级): %s", exc)
        finally:
            if _set_speaking is not None:
                _set_speaking(False)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())  # 非阻塞:后台朗读
    except RuntimeError:
        # 无运行中的事件循环:同步兜底(尽量不长阻塞)。
        try:
            asyncio.run(_run())
        except Exception:  # noqa: BLE001
            pass
