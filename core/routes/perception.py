"""
core/routes/perception.py
=========================
桌面端连续感知接收路由（摄像头 / 麦克风 / 屏幕）。

电脑端 Electron 壳用 getUserMedia 采集帧后 POST 到这里：
- POST /api/perception/desktop/frame    —— 存最新摄像头/屏幕帧（隐蔽上下文）
- POST /api/perception/desktop/audio    —— 存最新麦克风音频片段
- POST /api/perception/desktop/analyze  —— 「现在看一下」：把帧原生送模型分析
- GET  /api/perception/desktop/status   —— 存储/新鲜度诊断

frame/audio 只更新进程内 DesktopPerceptionStore，由 OpenClawd.process() 在下一次
真实请求时按 TTL 取用、作为原生多模态上下文注入（模型真正「看到」摄像头）。
analyze 则复用 Android vision 已验证的 runtime-shell 多模态路径，立即出分析。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Routes.Perception")


class DesktopFrame(BaseModel):
    image_base64: str = Field(description="Base64 编码的图像帧（建议 JPEG，≤1MB）")
    mime: str = Field(default="image/jpeg")
    source: str = Field(default="desktop_camera", description="desktop_camera / desktop_screen")
    screen: Optional[Dict[str, Any]] = None


class DesktopAudio(BaseModel):
    audio_base64: str = Field(description="Base64 编码的音频片段")
    mime: str = Field(default="audio/webm")


class DesktopAnalyze(BaseModel):
    image_base64: str = ""
    mime: str = "image/jpeg"
    prompt: str = ""
    source: str = "desktop_camera"
    session_id: str = ""


class DesktopListen(BaseModel):
    audio_base64: str = ""
    mime: str = "audio/webm"
    prompt: str = ""


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create desktop perception ingest routes."""
    router = APIRouter(prefix="/api/perception/desktop", tags=["perception"])

    @router.post("/frame")
    async def ingest_frame(frame: DesktopFrame):
        """接收最新摄像头/屏幕帧 → 存入 DesktopPerceptionStore（不立即调模型）。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store
            get_desktop_perception_store().update_frame(
                frame.image_base64, mime=frame.mime, source=frame.source, screen=frame.screen,
            )
            return {"success": True, "stored": "frame"}
        except Exception as exc:  # noqa: BLE001
            logger.debug("frame ingest failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @router.post("/audio")
    async def ingest_audio(audio: DesktopAudio):
        """接收最新麦克风音频片段 → 存入 DesktopPerceptionStore。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store
            get_desktop_perception_store().update_audio(audio.audio_base64, mime=audio.mime)
            return {"success": True, "stored": "audio"}
        except Exception as exc:  # noqa: BLE001
            logger.debug("audio ingest failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @router.get("/status")
    async def perception_status():
        """返回桌面感知存储的新鲜度/计数诊断。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store
            return {"success": True, "store": get_desktop_perception_store().status()}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    @router.post("/analyze")
    async def analyze_now(req: DesktopAnalyze):
        """「现在看一下」：把当前帧（或存储里的最新帧）原生送模型分析。

        复用 Android vision 已验证的 runtime-shell 多模态路径：构建
        MultiModalContext → DesktopPresenceRuntime.handle_request → 原生送模型。
        """
        image_b64 = req.image_base64
        mime = req.mime or "image/jpeg"
        source = req.source or "desktop_camera"
        # 未带图则取存储里的最新帧（摄像头或屏幕，取更新的那张）
        if not image_b64:
            try:
                from core.perception.desktop_perception_store import get_desktop_perception_store
                _b64, _mime, _src = get_desktop_perception_store().latest_frame_snapshot()
                if _b64:
                    image_b64, mime, source = _b64, _mime, _src
            except Exception as exc:  # noqa: BLE001
                logger.debug("store snapshot failed: %s", exc)
        if not image_b64:
            return {"success": False, "error": "no_frame_available"}

        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime
            from core.schemas.multimodal import MultiModalContext, MultiModalImage

            mm_context = MultiModalContext(
                images=[MultiModalImage(mime=mime, data=image_b64, source=source)],
                screen={"source": "desktop"},
                metadata={"source": "desktop_perception_analyze"},
            )
            runtime = get_desktop_presence_runtime()
            prompt = req.prompt or "描述一下你现在通过桌面摄像头/屏幕看到的内容。"
            session_id = req.session_id or "desktop_perception"
            result = await runtime.handle_request(
                message=prompt,
                source="desktop_vision",
                device_id=None,
                session_id=session_id,
                user_id="desktop",
                multimodal_context=mm_context,
                entry_mode="local",
            )
            return {
                "success": bool(result.get("success", True)),
                "runtime_session_id": result.get("runtime_session_id"),
                "response": result.get("response", ""),
                "multimodal_route": result.get("multimodal_route_decision", {}),
                "source": "runtime_shell_multimodal",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("desktop analyze failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @router.post("/listen")
    async def listen_now(req: DesktopListen):
        """「现在听一下」：把当前音频（或存储里的最新音频）原生送音频能力模型理解。

        复用 AudioPipeline 的原生音频通路（Gemini inline_data / OpenAI input_audio），
        返回模型对这段音频的理解/转写文本。需配置 GEMINI/GOOGLE 或 OPENAI key。
        """
        audio_b64 = req.audio_base64
        mime = req.mime or "audio/webm"
        if not audio_b64:
            try:
                from core.perception.desktop_perception_store import get_desktop_perception_store
                _store = get_desktop_perception_store()
                with _store._lock:  # noqa: SLF001 — 读快照
                    audio_b64 = _store._audio_b64 or ""
                    mime = _store._audio_mime
            except Exception as exc:  # noqa: BLE001
                logger.debug("store audio snapshot failed: %s", exc)
        if not audio_b64:
            return {"success": False, "error": "no_audio_available"}
        try:
            from core.audio_pipeline import get_audio_pipeline
            result = await get_audio_pipeline().understand(
                audio_b64, mime=mime, prompt=req.prompt or "",
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("desktop listen failed: %s", exc)
            return {"success": False, "error": str(exc)}

    return router
