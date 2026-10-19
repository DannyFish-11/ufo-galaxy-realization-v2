"""
Galaxy - Vision Routes
============================

Routes:
  POST /api/v1/vision/understand  - 融合视觉理解 (OCR + GUI)
  POST /api/v1/vision/ocr         - 独立 OCR 接口
  POST /api/v1/vision/observe     - 视觉采样会话 (Node_95 → OpenClawd → command_router)
"""

import base64
import binascii
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.routes._models import OCRRequest, VisionRequest

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


#: OCRRequest.mode → 适配器上的方法。原先调的 DeepSeekOCR2Adapter.process_image 不存在,这个接口从来只回失败。
_OCR_MODES = {
    "free_ocr": "extract_text",
    "markdown": "document_to_markdown",
    "tables": "extract_tables",
    "handwriting": "recognize_handwriting",
    "ui": "analyze_ui",
}


async def _deepseek_ocr(image_data: bytes, mode: str) -> dict:
    from nodes.Node_15_OCR.core.deepseek_ocr_adapter import DeepSeekOCRAdapter

    adapter = DeepSeekOCRAdapter()
    try:
        if not await adapter.initialize():
            return {"error": "DeepSeek OCR 2 没配:NOVITA_API_KEY / DEEPSEEK_OCR_API_KEY 或本机 DEEPSEEK_OCR2_LOCAL_URL"}
        method = getattr(adapter, _OCR_MODES.get(mode, "extract_text"))
        return await method(base64.b64encode(image_data).decode("ascii"))
    finally:
        await adapter.close()


def _decode_image(image_base64: str) -> bytes:
    """图是调用方给的：不是合法的 base64 就是调用方的错（400），不是这边崩了（原先两个接口都回 500）。"""
    try:
        return base64.b64decode(image_base64)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="image_base64 不是合法的 base64")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create vision routes router."""
    router = APIRouter()

    @router.post("/api/v1/vision/understand")
    async def vision_understand(req: VisionRequest):
        """融合视觉理解：支持图片、视频流及复合指令"""
        try:
            if req.video_chunk:
                if not req.image_base64:
                    return JSONResponse(
                        {
                            "success": True,
                            "mode": "video_stream",
                            "session_id": req.session_id,
                            "message": "Video chunk received",
                        }
                    )

            if not req.image_base64:
                raise HTTPException(status_code=400, detail="Image or video chunk required")

            _decode_image(req.image_base64)  # 先确认是张图,坏数据在这里就报

            # understand() 是协程,原先丢进线程池跑、返回的是没 await 的协程对象 —— 序列化时炸成 500,
            # 这个接口从来没成功过;退路调的 DeepSeekOCR2Adapter / process_image 也都不存在。
            # 管线自己按登记表逐档降级(DeepSeek OCR 2 就是其中一档),这里不再另起一条。
            from core.vision_pipeline import get_vision_pipeline

            result = await get_vision_pipeline().understand(
                image_base64=req.image_base64, mode=req.mode, task_context=req.instruction
            )
            if result.success:
                return JSONResponse({"success": True, "engine": result.engine_used, "result": result.to_dict()})

            return JSONResponse(
                {
                    "success": False,
                    "engine": "none",
                    "error": result.error or "无可用的视觉理解引擎",
                    "result": {
                        "raw_text": "",
                        "text_blocks": [],
                        "ui_elements": [],
                        "scene_description": "视觉引擎不可用",
                        "suggested_actions": [],
                    },
                }
            )

        except HTTPException:
            raise  # 上面那两个 400 原先被这里接住、改写成 500(「500: 400: Image or video chunk required」)
        except Exception as e:
            logger.error(f"视觉理解失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vision/ocr")
    async def vision_ocr(req: OCRRequest):
        """独立 OCR 接口"""
        image_data = _decode_image(req.image_base64)
        try:
            try:
                result = await _deepseek_ocr(image_data, req.mode)
            except Exception as e:  # 详情只进服务端日志,不把异常原文回给调用方
                logger.warning("DeepSeek OCR 2 调用失败: %s", e)
                result = {"error": "OCR 调用失败(详情见服务端日志)"}
            if result.get("error"):
                return JSONResponse({"success": False, "error": result["error"], "text": "", "blocks": []})
            return JSONResponse(
                {
                    "success": True,
                    "engine": "deepseek_ocr2",
                    "text": result.get("text", ""),
                    "blocks": result.get("blocks", []),
                    "confidence": result.get("confidence", 0.0),
                }
            )

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
