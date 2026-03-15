"""
Galaxy - Vision Routes
============================

Routes:
  POST /api/v1/vision/understand  - 融合视觉理解 (OCR + GUI)
  POST /api/v1/vision/ocr         - 独立 OCR 接口
  POST /api/v1/vision/observe     - 视觉采样会话 (Node_95 → OpenClawd → command_router)
"""

import asyncio
import base64
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.routes._models import VisionRequest, OCRRequest

logger = logging.getLogger("Galaxy.API")


# ---------------------------------------------------------------------------
# Request model for the observe endpoint
# ---------------------------------------------------------------------------

class ObserveRequest(BaseModel):
    """Request body for POST /api/v1/vision/observe."""

    device_id: str = Field(description="Target device ID used to pull frames from Node_95.")
    fps: float = Field(default=1.0, ge=0.01, le=30.0, description="Frames per second to sample.")
    duration: float = Field(default=10.0, ge=1.0, le=300.0, description="Sampling window in seconds.")
    prompt: Optional[str] = Field(default=None, description="Instruction forwarded to OpenClawd.")
    mode: Optional[str] = Field(default=None, description="Optional mode hint for OpenClawd.")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create vision routes router."""
    router = APIRouter()

    @router.post("/api/v1/vision/understand")
    async def vision_understand(req: VisionRequest):
        """融合视觉理解：支持图片、视频流及复合指令"""
        try:
            if req.video_chunk:
                if not req.image_base64:
                    return JSONResponse({
                        "success": True,
                        "mode": "video_stream",
                        "session_id": req.session_id,
                        "message": "Video chunk received"
                    })

            if not req.image_base64:
                raise HTTPException(status_code=400, detail="Image or video chunk required")

            image_data = base64.b64decode(req.image_base64)

            try:
                from core.vision_pipeline import VisionPipeline
                pipeline = VisionPipeline()
                result = await asyncio.get_running_loop().run_in_executor(
                    None, pipeline.understand, image_data, req.mode, req.instruction
                )
                return JSONResponse({
                    "success": True,
                    "engine": "vision_pipeline",
                    "result": result
                })
            except ImportError:
                pass

            try:
                from nodes.Node_15_OCR.core.deepseek_ocr_adapter import DeepSeekOCR2Adapter
                adapter = DeepSeekOCR2Adapter()
                result = await asyncio.get_running_loop().run_in_executor(
                    None, adapter.process_image, image_data, req.mode
                )
                return JSONResponse({
                    "success": True,
                    "engine": "deepseek_ocr2",
                    "result": result
                })
            except Exception as e:
                logger.warning(f"DeepSeek OCR 2 调用失败: {e}")

            return JSONResponse({
                "success": False,
                "engine": "none",
                "error": "无可用的视觉理解引擎",
                "result": {
                    "raw_text": "",
                    "text_blocks": [],
                    "ui_elements": [],
                    "scene_description": "视觉引擎不可用",
                    "suggested_actions": []
                }
            })

        except Exception as e:
            logger.error(f"视觉理解失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vision/ocr")
    async def vision_ocr(req: OCRRequest):
        """独立 OCR 接口"""
        try:
            image_data = base64.b64decode(req.image_base64)

            try:
                from nodes.Node_15_OCR.core.deepseek_ocr_adapter import DeepSeekOCR2Adapter
                adapter = DeepSeekOCR2Adapter()
                result = await asyncio.get_running_loop().run_in_executor(
                    None, adapter.process_image, image_data, req.mode
                )
                return JSONResponse({
                    "success": True,
                    "engine": "deepseek_ocr2",
                    "text": result.get("text", ""),
                    "blocks": result.get("blocks", []),
                    "confidence": result.get("confidence", 0.0)
                })
            except Exception as e:
                logger.warning(f"DeepSeek OCR 2 调用失败: {e}")
                return JSONResponse({
                    "success": False,
                    "error": str(e),
                    "text": "",
                    "blocks": []
                })

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vision/observe")
    async def vision_observe(req: ObserveRequest):
        """Trigger a vision sampling session.

        Pulls frames from Node_95 WebRTC Receiver at *fps* frames/s for
        *duration* seconds, packages them into a MultiModalContext, calls
        OpenClawd, and — when the response contains an action — routes it via
        command_router.

        Returns a JSON object with keys:
          - success (bool)
          - frames_sampled (int)
          - openclawd_response (dict | null)
          - command_result (dict | null)
        """
        try:
            from core.services.vision_sampler import run_sampling_session

            result = await run_sampling_session(
                device_id=req.device_id,
                fps=req.fps,
                duration=req.duration,
                prompt=req.prompt,
                mode=req.mode,
            )
            if result.get("success"):
                status_code = 200
            elif "unreachable" in (result.get("error") or "").lower() or result.get("frames_sampled", 0) == 0:
                status_code = 503  # Node_95 unreachable / no frames captured
            else:
                status_code = 500
            return JSONResponse(result, status_code=status_code)
        except Exception as e:
            logger.error("vision_observe error: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    return router
