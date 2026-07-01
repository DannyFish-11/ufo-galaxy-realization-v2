"""
core/voice_conversation_bridge.py — 实时语音对话闭环（一体化）
=================================================================

把已有的语音零件串成端到端闭环，并与面板"实时上下文"一体：

    麦克风 → AudioCaptureService → Whisper ASR 转写
        → emit_conversation("user", …, source="voice")   ← 面板实时显示"听到的"
        → DesktopPresenceRuntime.handle_request()          ← 喂给同一个 AI 大脑
        → emit_conversation("ai", …, speaking=True)        ← 面板实时显示"AI 说的"
        → speak_response()（TTS 朗读）

设计：
  - 复用 core.lumiv_websocket_bridge.emit_conversation（与在场共用 WS 通道），
    所以语音对话与打字对话在面板上是同一条实时上下文流。
  - 默认关闭；仅当 GALAXY_VOICE_LOOP=1 且真实麦克风/模型可用时启用（需真机验证）。
  - 全程容错，任何一环失败都不影响其余通路。
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("Galaxy.VoiceBridge")

_VOICE_SESSION = "voice-desktop"


def voice_loop_enabled() -> bool:
    return os.environ.get("GALAXY_VOICE_LOOP", "").strip().lower() in ("1", "true", "yes", "on")


async def process_voice_utterance(text: str, session_id: str = _VOICE_SESSION) -> None:
    """一次语音输入的完整闭环：面板显示 → AI 回应 → 面板显示 + 朗读。容错。"""
    text = (text or "").strip()
    if not text:
        return

    try:
        from core.lumiv_websocket_bridge import emit_conversation
    except Exception:  # noqa: BLE001
        emit_conversation = None  # type: ignore

    # 1) 听到的 → 面板实时上下文
    if emit_conversation is not None:
        emit_conversation("user", text, source="voice", turn_id=session_id)

    # 2) 喂给同一个 AI 大脑
    reply = ""
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        res = await get_desktop_presence_runtime().handle_request(
            message=text, source="voice", session_id=session_id, entry_mode="local",
        )
        reply = (res.get("response") or "") if isinstance(res, dict) else str(res or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice→AI 处理失败: %s", exc)
        return

    reply = (reply or "").strip()
    if not reply:
        return

    # 3) AI 回应 → 面板实时上下文（标记朗读态）+ TTS 朗读
    if emit_conversation is not None:
        emit_conversation("ai", reply, source="voice", speaking=True, turn_id=session_id)
    try:
        from core.speech_output import speak_enabled, speak_response
        if speak_enabled():
            speak_response(reply, source="voice")
    except Exception as exc:  # noqa: BLE001
        logger.debug("TTS 朗读跳过: %s", exc)


def _on_voice_input(text: str) -> None:
    """AudioCaptureService.on_voice_input 的同步回调（音频线程）→ 调度异步闭环。"""
    try:
        asyncio.run(process_voice_utterance(text))
    except RuntimeError:
        # 罕见：当前线程已有运行 loop → 调度为 task
        try:
            asyncio.get_running_loop().create_task(process_voice_utterance(text))
        except Exception as exc:  # noqa: BLE001
            logger.debug("voice input 调度失败: %s", exc)


def attach_voice_loop(audio_capture_service) -> bool:
    """把闭环挂到 AudioCaptureService.on_voice_input。返回是否已挂上。"""
    if not voice_loop_enabled():
        return False
    try:
        audio_capture_service.on_voice_input = _on_voice_input
        logger.info("实时语音对话闭环已挂载（ASR→AI→TTS + 面板一体化）")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("attach_voice_loop 失败: %s", exc)
        return False


def start_voice_loop() -> bool:
    """(gated) 惰性构建 AudioCaptureService + Whisper 并启动语音闭环。

    仅当 GALAXY_VOICE_LOOP=1 时执行；任何依赖缺失/无麦克风都安全返回 False，
    绝不阻塞或破坏桌面运行时启动。需在真机上验证。
    """
    if not voice_loop_enabled():
        return False
    try:
        from core.multimodal.audio_capture_service import AudioCaptureService
        svc = AudioCaptureService()
    except Exception as exc:  # noqa: BLE001
        logger.info("语音闭环未启动（音频采集不可用）: %s", exc)
        return False
    try:
        from core.asr import WhisperASR
        svc.add_whisper_callback(WhisperASR(model_size="small"), language="zh")
    except Exception as exc:  # noqa: BLE001
        logger.info("语音闭环未启动（Whisper 不可用）: %s", exc)
        return False
    if not attach_voice_loop(svc):
        return False
    try:
        # start() 需在事件循环内；有运行 loop 就调度，否则交给调用方。
        loop = asyncio.get_running_loop()
        loop.create_task(svc.start())
    except RuntimeError:
        logger.info("语音闭环已挂载，等待事件循环启动采集")
    return True


# Sentinel
VOICE_CONVERSATION_BRIDGE_SENTINEL: str = (
    "VOICE_CONVERSATION_BRIDGE_V1: core/voice_conversation_bridge.py | "
    "ASR→emit_conversation(user)→handle_request→emit_conversation(ai)+TTS. "
    "Gated by GALAXY_VOICE_LOOP=1. 与面板实时上下文共用 WS 通道，一体化。"
)
