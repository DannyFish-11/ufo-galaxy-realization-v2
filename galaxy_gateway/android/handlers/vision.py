"""
galaxy_gateway/android/handlers/vision.py

Handles vision_request messages from Android devices.

The handler creates a canonical MultiModalContext from the incoming screenshot
and routes it through the runtime shell.  This ensures that Android visual
inputs enter the same DesktopPresenceRuntime → OpenClawd authority chain as
other request surfaces, while still using the native multimodal fusion path.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_vision_request(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理视觉请求：Android 上传截图 → 多模态管道分析 → task_assign 回推

    Routes the Android screenshot through the canonical runtime-shell pipeline:
    1. Wraps the screenshot in a ``MultiModalContext`` (canonical schema).
    2. Delegates to ``DesktopPresenceRuntime.handle_request()`` so the
       runtime shell remains the single ingress authority and OpenClawd still
       receives the multimodal payload through its native fusion path.
    3. Falls back to the legacy ``VisionPipeline`` if OpenClawd is unavailable.
    """
    device_id = message.get("device_id")
    task_id = message.get("task_id") or message.get("message_id") or str(uuid.uuid4())
    image_base64 = message.get("image_base64", "")
    mode = message.get("mode", "full")
    task_context = message.get("task_context", "")
    participation = message.get("participation", "one_shot_request_bound")

    logger.info("Vision request from %s: task_id=%s, mode=%s", device_id, task_id, mode)

    if not image_base64:
        return MessageBuilder.error(
            device_id or "unknown",
            "VISION_NO_IMAGE",
            "image_base64 is required for vision_request",
        )

    # ── Primary path: route through the runtime shell multimodal pipeline ───
    vision_payload: Dict[str, Any] = {}
    try:
        vision_payload = await _process_via_runtime_shell(
            image_base64=image_base64,
            task_context=task_context,
            mode=mode,
            device_id=device_id or "",
            task_id=task_id,
            participation=participation,
        )
    except Exception as exc:
        logger.warning(
            "runtime-shell multimodal path unavailable (%s), falling back to VisionPipeline",
            exc,
        )
        vision_payload = await _process_via_vision_pipeline(
            image_base64=image_base64,
            mode=mode,
            task_context=task_context,
        )

    # ── Push result back to Android ─────────────────────────────────────────
    response = MessageBuilder.vision_result(
        device_id=device_id or "unknown",
        task_id=task_id,
        result=vision_payload,
    )

    try:
        if websocket is not None:
            # PR-AIP-UNIFIED: Route through AIPTransport
            from core.aip_transport import get_aip_transport
            _msg = {
                **response,
                "_transport": "auto",
                "version": "3.0",
            }
            try:
                await get_aip_transport().send(_msg, device_id or "unknown")
            except Exception:
                await websocket.send_json(response)
    except Exception as e:
        logger.warning("Failed to push vision_result to %s: %s", device_id, e)

    return response


async def _process_via_runtime_shell(
    image_base64: str,
    task_context: str,
    mode: str,
    device_id: str,
    task_id: str = "",
    participation: str = "one_shot_request_bound",
) -> Dict[str, Any]:
    """Route the vision request through the runtime shell multimodal path."""
    from core.android_perception_ingress_contract import (
        build_android_perception_payload_contract,
    )
    from core.desktop_presence_runtime import get_desktop_presence_runtime
    from core.schemas.multimodal import MultiModalContext, MultiModalImage

    runtime = get_desktop_presence_runtime()

    # Build canonical multimodal context from the Android screenshot
    mm_context = MultiModalContext(
        images=[
            MultiModalImage(
                mime="image/png",
                data=image_base64,
                source=f"android_screen:{device_id}" if device_id else "android_screen",
            )
        ],
        screen={"mode": mode, "source": "android"},
        metadata={
            "device_id": device_id,
            "mode": mode,
            "android_perception_contract": build_android_perception_payload_contract(
                device_id=device_id,
                mode=mode,
                task_id=task_id,
                participation=participation,
            ),
            "android_perception_participation": participation,
        },
    )

    # Derive a stable session_id for this vision request so the carrier can
    # be correlated with the same authority-chain session across calls.
    _session_id = task_id or f"android_vision_{device_id}"

    prompt = task_context or "Analyse this Android screen and describe what you see."
    result = await runtime.handle_request(
        message=prompt,
        source="android_vision",
        device_id=device_id or None,
        session_id=_session_id,
        user_id=device_id or "android",
        multimodal_context=mm_context,
        entry_mode="local",
        mode=mode,
    )

    return {
        "success": bool(result.get("success", True)),
        "runtime_session_id": result.get("runtime_session_id"),
        "analysis": {
            "response":         result.get("response", ""),
            "execution_path":   result.get("execution_path", ""),
            "runtime_domain":   result.get("runtime_domain", ""),
            "multimodal_route": result.get("multimodal_route_decision", {}),
        },
        "source": "runtime_shell_multimodal",
    }


async def _process_via_vision_pipeline(
    image_base64: str,
    mode: str,
    task_context: str,
) -> Dict[str, Any]:
    """Legacy fallback: call VisionPipeline directly."""
    try:
        from core.vision_pipeline import VisionPipeline
        pipeline = VisionPipeline()
        vision_result = await pipeline.understand(
            image_base64=image_base64,
            mode=mode,
            task_context=task_context,
        )
        analysis = vision_result.to_dict() if hasattr(vision_result, "to_dict") else {
            k: v for k, v in vars(vision_result).items() if not k.startswith("_")
        }
        return {
            "success": vision_result.success,
            "runtime_session_id": None,
            "analysis": analysis,
            "source": "vision_pipeline",
        }
    except Exception as e:
        logger.warning("VisionPipeline unavailable: %s", e)
        return {
            "success": False,
            "runtime_session_id": None,
            "error": str(e),
            "source": "vision_pipeline",
        }
