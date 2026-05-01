"""
galaxy_gateway/routes/android_vlm.py
=====================================
HTTP routes for the center-side Android VLM inference service.

Routes
------
POST /api/v1/android/vlm/plan
    Perform center-side mobile UI task planning (MobileVLM equivalent).
    Android sends a screenshot + task; center returns the next action.

POST /api/v1/android/vlm/ground
    Perform center-side UI element grounding (SeeClick equivalent).
    Android sends a screenshot + query; center returns bounding box.

GET /api/v1/android/vlm/status
    Returns the VLM service status: available providers, inference mode.

GET /api/v1/android/vlm/model_checksums
    Returns the canonical SHA-256 checksums for Android model assets.
    Android uses these to verify downloaded files from Hugging Face.

These routes eliminate the need for llama.cpp / NCNN to be bundled
in the Android APK when ``android.inference_mode`` is set to ``"center"``
or ``"hybrid"``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/android/vlm", tags=["android-vlm"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class PlanRequest(BaseModel):
    """Request body for the /plan endpoint."""
    image_base64: str = Field(description="Base64-encoded PNG or JPEG screenshot.")
    task: str = Field(description="Natural language task description.")
    device_id: Optional[str] = Field(default="", description="Android device identifier.")
    screen_width: Optional[int] = Field(default=0, description="Screen width in pixels.")
    screen_height: Optional[int] = Field(default=0, description="Screen height in pixels.")


class GroundRequest(BaseModel):
    """Request body for the /ground endpoint."""
    image_base64: str = Field(description="Base64-encoded PNG or JPEG screenshot.")
    query: str = Field(description="Natural language description of the target UI element.")
    device_id: Optional[str] = Field(default="", description="Android device identifier.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/plan")
async def android_vlm_plan(req: PlanRequest) -> Dict[str, Any]:
    """
    Center-side mobile UI task planning (MobileVLM equivalent).

    Android sends a screenshot and task description; the V2 center performs
    multimodal inference and returns the next atomic action to take.

    This endpoint replaces the Android-local ``LocalPlannerService`` that
    requires llama.cpp to be bundled in the APK.
    """
    from galaxy_gateway.android_vlm_service import get_android_vlm_service
    service = get_android_vlm_service()
    result = await service.plan(
        image_base64=req.image_base64,
        task=req.task,
        device_id=req.device_id or "",
        screen_width=req.screen_width or 0,
        screen_height=req.screen_height or 0,
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "VLM plan failed"))
    return result


@router.post("/ground")
async def android_vlm_ground(req: GroundRequest) -> Dict[str, Any]:
    """
    Center-side UI element grounding (SeeClick equivalent).

    Android sends a screenshot and a natural language query; the V2 center
    performs multimodal inference and returns the bounding box of the target
    UI element.

    This endpoint replaces the Android-local ``LocalGroundingService`` that
    requires NCNN to be bundled in the APK.
    """
    from galaxy_gateway.android_vlm_service import get_android_vlm_service
    service = get_android_vlm_service()
    result = await service.ground(
        image_base64=req.image_base64,
        query=req.query,
        device_id=req.device_id or "",
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "VLM ground failed"))
    return result


@router.get("/status")
async def android_vlm_status() -> Dict[str, Any]:
    """
    Return the VLM service status including available multimodal providers
    and the configured Android inference mode.
    """
    from galaxy_gateway.android_vlm_service import get_android_vlm_service

    service = get_android_vlm_service()
    router_instance = service._get_router()

    multimodal_providers: list = []
    if router_instance is not None:
        try:
            providers = getattr(router_instance, "_providers", {})
            for pid, cfg in providers.items():
                if getattr(cfg, "multimodal", False):
                    multimodal_providers.append(pid)
        except Exception:
            pass

    inference_mode = "center"
    try:
        from core.config_service import get_config_service
        inference_mode = get_config_service().get_network_url("android_gateway_url") or "center"
        cfg = get_config_service()._store.read_config()
        inference_mode = cfg.get("android", {}).get("inference_mode", "center")
    except Exception:
        pass

    return {
        "service": "AndroidVLMService",
        "available": router_instance is not None,
        "multimodal_providers": multimodal_providers,
        "inference_mode": inference_mode,
        "endpoints": {
            "plan":  "/api/v1/android/vlm/plan",
            "ground": "/api/v1/android/vlm/ground",
        },
    }


@router.get("/model_checksums")
async def android_model_checksums() -> Dict[str, Any]:
    """
    Return the canonical SHA-256 checksums for Android model assets.

    Android uses these values to verify downloaded model files from
    Hugging Face, replacing the null checksums previously recorded in
    ``ModelAssetManager.kt``.

    An empty ``sha256`` string means the checksum has not yet been populated
    by the deployment operator.  In that case verification should be skipped
    and the operator should update the checksum registry.
    """
    from galaxy_gateway.android_vlm_service import ANDROID_MODEL_CHECKSUMS
    return {
        "checksums": ANDROID_MODEL_CHECKSUMS,
        "note": (
            "When android.inference_mode='center', model files are optional on "
            "the Android device — the V2 center performs all VLM inference. "
            "Populate the sha256 fields before production deployment."
        ),
    }
