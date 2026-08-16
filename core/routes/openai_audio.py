#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/routes/openai_audio.py — OpenAI 兼容的音频端点
====================================================

仓库已经有 OpenAI 兼容的 ``/v1/chat/completions``(``Node_01_OneAPI``、
``Node_79_LocalLLM``),却没有音频那两个。而 TTS 引擎有 6 个、ASR 引擎有 2 个,
全都躺在那儿只能被内部调用。补上这两个端点,任何用 OpenAI SDK 写的脚本改一行
base_url 就能指过来::

    POST /v1/audio/speech           文字 → 音频(对齐 OpenAI TTS)
    POST /v1/audio/transcriptions   音频 → 文字(对齐 OpenAI Whisper)

设计约束
--------
1. **纯新增。** 不改任何既有行为;不挂载这个路由,系统与改造前完全一致。
2. **不另起一套引擎选择。** 说走 ``core.speech_output``(引擎链与失败降级的权威),
   听走 ``core.modality_bridge.transcribe_b64``——后者的文档把自己称作"听的收口",
   并且专门记录过绕开它的后果(语音循环直连 Whisper,导致 B 档"原生听"从未生效)。
   在这里另开一条 ASR 调用就是重犯那个错。
3. **参数按 OpenAI 的形状收,按本仓的能力答。** ``model``/``voice`` 收下并**如实
   上报实际用了什么**,而不是假装支持 OpenAI 的模型名——沉默的不匹配比明确的
   "我用的是别的"更难排查。

鉴权
----
路由本身不做鉴权;它由 ``core/api_routes.py`` 与其它路由一样挂在统一的鉴权依赖
之后。这里不自建第二套鉴权,理由与不自建第二套引擎选择相同。
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Routes.OpenAIAudio")

router = APIRouter(prefix="/v1/audio", tags=["openai-compat-audio"])

__all__ = [
    "OPENAI_AUDIO_REUSES_EXISTING_AUTHORITIES_POLICY",
    "OPENAI_AUDIO_REPORTS_WHAT_IT_ACTUALLY_USED_POLICY",
    "SpeechRequest",
    "router",
    "create_router",
]


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

OPENAI_AUDIO_REUSES_EXISTING_AUTHORITIES_POLICY: str = (
    "OPENAI_AUDIO::POLICY_1: "
    "Synthesis goes through core.speech_output (the engine-chain and demotion "
    "authority); transcription goes through core.modality_bridge.transcribe_b64 "
    "(which its own docstring calls 听的收口). This route MUST NOT select engines "
    "or call an ASR model directly — bypassing the 收口 is the documented defect "
    "that left B-tier native listening silently inactive."
)

OPENAI_AUDIO_REPORTS_WHAT_IT_ACTUALLY_USED_POLICY: str = (
    "OPENAI_AUDIO::POLICY_2: "
    "The OpenAI-shaped `model` and `voice` parameters are accepted, but the "
    "response reports the engine and voice actually used.  Silently ignoring a "
    "requested model would make a mismatch invisible; saying so makes it "
    "diagnosable."
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

_MAX_INPUT_CHARS = 4096
"""Same input ceiling OpenAI documents for its TTS endpoint."""

_SUPPORTED_RESPONSE_FORMATS = ("mp3", "wav", "opus", "aac", "flac", "pcm")


class SpeechRequest(BaseModel):
    """``POST /v1/audio/speech`` body, shaped like OpenAI's."""

    input: str = Field(..., description="要合成的文字")
    model: str = Field(default="", description="OpenAI 兼容字段;本仓按 GALAXY_TTS_ENGINE 选引擎")
    voice: str = Field(default="", description="音色;透传给引擎(如 edge 的 zh-CN-XiaoxiaoNeural)")
    response_format: str = Field(default="", description="OpenAI 兼容字段;实际格式由引擎决定并如实上报")
    speed: float = Field(default=1.0, description="OpenAI 兼容字段;当前引擎链未统一支持,收下但不静默假装生效")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/speech")
async def create_speech(req: SpeechRequest) -> Any:
    """文字 → 音频文件(对齐 ``POST /v1/audio/speech``)。

    返回音频文件本身(与 OpenAI 一致),实际使用的引擎/音色/格式放在响应头
    ``X-Galaxy-TTS-Engine`` / ``X-Galaxy-TTS-Voice`` / ``X-Galaxy-Audio-Format``,
    这样既不破坏 SDK 的二进制读取,又不让"我到底用了什么"变成黑盒。
    """
    text = (req.input or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="input 不能为空")
    if len(text) > _MAX_INPUT_CHARS:
        raise HTTPException(status_code=400, detail=f"input 超过 {_MAX_INPUT_CHARS} 字符上限")
    if req.response_format and req.response_format.lower() not in _SUPPORTED_RESPONSE_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"response_format 需为 {_SUPPORTED_RESPONSE_FORMATS} 之一",
        )

    try:
        from core.speech_output import current_engine_name, synthesize_to_file
    except Exception as exc:  # noqa: BLE001
        logger.warning("语音合成不可用: %s", exc)
        raise HTTPException(status_code=503, detail="语音合成不可用") from exc

    path = await synthesize_to_file(text, voice=(req.voice or None))
    if not path or not os.path.exists(path):
        # 503 而非 500:引擎链跑完仍出不了声是"能力当前不可用",不是请求错误。
        raise HTTPException(status_code=503, detail="TTS 引擎链不可用或合成失败")

    actual_format = os.path.splitext(path)[1].lstrip(".").lower() or "bin"
    if req.response_format and req.response_format.lower() != actual_format:
        # POLICY_2:不假装满足了请求的格式。
        logger.info(
            "TTS 实际输出 %s,与请求的 response_format=%s 不同(未做转码)",
            actual_format,
            req.response_format,
        )
    media_type = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "opus": "audio/opus",
        "flac": "audio/flac",
        "aac": "audio/aac",
    }.get(actual_format, "application/octet-stream")

    return FileResponse(
        path,
        media_type=media_type,
        filename=f"speech.{actual_format}",
        headers={
            "X-Galaxy-TTS-Engine": current_engine_name(),
            "X-Galaxy-TTS-Voice": req.voice or os.getenv("GALAXY_TTS_VOICE", ""),
            "X-Galaxy-Audio-Format": actual_format,
            "X-Galaxy-Requested-Format": req.response_format or "",
        },
    )


@router.post("/transcriptions")
async def create_transcription(
    file: UploadFile = File(..., description="音频文件(webm/wav/mp3/opus…)"),
    model: str = Form(default=""),
    language: str = Form(default="zh"),
    response_format: str = Form(default="json"),
) -> Any:
    """音频 → 文字(对齐 ``POST /v1/audio/transcriptions``)。

    走 ``modality_bridge.transcribe_b64`` 这个"听的收口":B 档原生后端在线时让全模态
    模型自己听,不行再回落 Whisper/SenseVoice。这里**不直接调 ASR**——绕开收口正是该
    模块文档记录过的那个真实缺陷。
    """
    try:
        raw = await file.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}") from exc
    if not raw:
        raise HTTPException(status_code=400, detail="上传的音频为空")

    try:
        from core.modality_bridge import transcribe_b64
    except Exception as exc:  # noqa: BLE001
        logger.warning("语音识别不可用: %s", exc)
        raise HTTPException(status_code=503, detail="语音识别不可用") from exc

    mime = file.content_type or "audio/webm"
    text = transcribe_b64(base64.b64encode(raw).decode("ascii"), mime=mime, language=language or "zh")
    if text is None:
        # None 与空串是两回事:None = 这条链路当前不可用(缺 PyAV / ASR 未就绪),
        # 空串 = 听了但没听出内容。两者混同会让排查失去方向。
        raise HTTPException(status_code=503, detail="转写链路不可用(检查 PyAV 与 ASR 依赖)")

    if (response_format or "json").lower() == "text":
        return JSONResponse(content=text, media_type="text/plain")
    payload: Dict[str, Any] = {"text": text}
    if model:
        payload["requested_model"] = model
    return payload


@router.get("/capabilities")
async def audio_capabilities() -> Dict[str, Any]:
    """本机音频能力自述:装了哪些引擎、当前会用哪个、算力是否跟得上。

    有这个端点的理由和 V1 是同一个:与其让调用方试出来,不如让它问得到。
    """
    out: Dict[str, Any] = {"tts": {}, "asr": {}}
    try:
        from core.speech_output import current_engine_name, get_tts_degraded_reason

        out["tts"]["active_engine"] = current_engine_name()
        out["tts"]["degraded_reason"] = get_tts_degraded_reason()
    except Exception as exc:  # noqa: BLE001
        out["tts"]["error"] = str(exc)
    try:
        from core.tts.compute_fit import ENGINE_COMPUTE_NEEDS, assess_engine_fit

        out["tts"]["engines"] = {name: assess_engine_fit(name).to_dict() for name in sorted(ENGINE_COMPUTE_NEEDS)}
    except Exception as exc:  # noqa: BLE001
        out["tts"]["fit_error"] = str(exc)
    try:
        from core.modality_bridge import _get_asr

        asr = _get_asr()
        out["asr"]["active_engine"] = type(asr).__name__ if asr is not None else ""
    except Exception as exc:  # noqa: BLE001
        out["asr"]["error"] = str(exc)
    out["endpoints"] = ["/v1/audio/speech", "/v1/audio/transcriptions", "/v1/audio/capabilities"]
    return out


def create_router(service_manager: Optional[Any] = None, config: Optional[Any] = None) -> APIRouter:
    """与其它 ``core/routes/*`` 一致的工厂形状(参数当前未使用,保持挂载方式统一)。"""
    return router
