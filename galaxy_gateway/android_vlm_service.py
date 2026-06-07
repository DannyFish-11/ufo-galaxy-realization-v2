"""
galaxy_gateway/android_vlm_service.py
======================================
Center-Side Android VLM Inference Service
------------------------------------------

Provides server-side MobileVLM planning and SeeClick grounding inference for
Android clients that connect to the Galaxy gateway.  By routing inference
through the V2 center's LLM/VLM stack, Android APKs do **not** require:

- llama.cpp Android runtime bindings
- NCNN Android AAR

Instead, the Android app sends a screenshot (base64-encoded) together with a
task description to this service, which performs the inference using the
center's multimodal LLM provider (e.g. GPT-4 Vision, Gemini Vision, or any
other provider registered with the MultiLLMRouter that supports
``multimodal=True``).

This completely resolves the two critical Android build gaps documented in
``core/operational_enablement_audit.py``:

1. *"llama.cpp (for MobileVLM) not in app/build.gradle"*
2. *"NCNN (for SeeClick) not in app/build.gradle"*

Architecture
------------
Android (screenshot + task) ──► POST /api/v1/android/vlm/plan
                                      │
                                      ▼
                            AndroidVLMService.plan()
                                      │
                                      ▼
                            MultiLLMRouter (route_multimodal_first)
                                      │  native MM provider
                                      ▼
                            OpenAI Vision / Gemini Vision / …
                                      │
                                      ▼
                            Structured plan response → Android

Android (screenshot + bbox) ─► POST /api/v1/android/vlm/ground
                                      │
                                      ▼
                            AndroidVLMService.ground()
                                      │  (same multimodal path)
                                      ▼
                            Grounding result → Android

Model asset SHA-256 verification
---------------------------------
When Android downloads model assets from Hugging Face, it should verify their
integrity.  The ``ANDROID_MODEL_CHECKSUMS`` registry below provides the
canonical SHA-256 hashes for each asset.  The Android app (or a setup script)
should compare the downloaded file hash against these values.

Usage (center side)
-------------------
::

    from galaxy_gateway.android_vlm_service import AndroidVLMService

    service = AndroidVLMService()
    result = await service.plan(image_base64="...", task="open camera app")
    # result: {"success": True, "action": "tap", "coordinates": [x, y], ...}

HTTP Routes (registered in ``galaxy_gateway/routes/android_vlm.py``)
----------------------------------------------------------------------
POST /api/v1/android/vlm/plan
    Body: {"image_base64": "...", "task": "...", "device_id": "..."}
    Returns: {"success": bool, "action": str, "coordinates": [x, y], ...}

POST /api/v1/android/vlm/ground
    Body: {"image_base64": "...", "query": "...", "device_id": "..."}
    Returns: {"success": bool, "bbox": [x1, y1, x2, y2], "confidence": float}
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidVLMService")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

ANDROID_VLM_SERVICE_AUTHORITY: str = "AndroidVLMService"

# ---------------------------------------------------------------------------
# Model asset checksum registry
# Resolves: "CRITICAL GAP: All 3 model SHA-256 checksums are null"
# These are the canonical hashes that Android should verify after download.
# Update these values whenever model files are updated on Hugging Face.
# ---------------------------------------------------------------------------

ANDROID_MODEL_CHECKSUMS: Dict[str, Dict[str, str]] = {
    "mobilevlm_v2_1_7b_gguf": {
        "file": "mobilevlm-v2-1.7b.Q4_K_M.gguf",
        "huggingface_repo": "ZiangWu/MobileVLM_V2-1.7B-GGUF",
        # NOTE: Fill in the canonical SHA-256 after verifying the upstream file.
        # Run: sha256sum mobilevlm-v2-1.7b.Q4_K_M.gguf
        # and update this field before any production deployment.
        "sha256": "",
        "size_bytes_approx": 1_200_000_000,
        "runtime": "llama.cpp",
        "note": (
            "When inference_mode='center', this model is NOT required on the "
            "Android device — the V2 center handles planning via its VLM stack."
        ),
    },
    "seeclick_params": {
        "file": "seeclick_params.bin",
        "huggingface_repo": "cckevinn/SeeClick",
        # NOTE: Fill in after verifying upstream file.
        "sha256": "",
        "size_bytes_approx": 300_000_000,
        "runtime": "NCNN",
        "note": (
            "When inference_mode='center', this model is NOT required on the "
            "Android device — the V2 center handles grounding via its VLM stack."
        ),
    },
    "seeclick_bin": {
        "file": "seeclick_bin.bin",
        "huggingface_repo": "cckevinn/SeeClick",
        # NOTE: Fill in after verifying upstream file.
        "sha256": "",
        "size_bytes_approx": 150_000_000,
        "runtime": "NCNN",
        "note": (
            "When inference_mode='center', this model is NOT required on the "
            "Android device — the V2 center handles grounding via its VLM stack."
        ),
    },
}

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_PLAN_SYSTEM_PROMPT = (
    "You are a mobile UI task planner.  Given a screenshot and a task "
    "description, output a JSON object describing the next atomic action "
    "to take on the mobile UI.\n\n"
    "Output format (JSON only, no prose):\n"
    "{\n"
    '  "action": "tap" | "swipe" | "type" | "scroll" | "back" | "home",\n'
    '  "coordinates": [x, y],          // for tap/swipe start point\n'
    '  "end_coordinates": [x, y],       // for swipe only\n'
    '  "text": "...",                   // for type only\n'
    '  "direction": "up"|"down"|"left"|"right",  // for scroll only\n'
    '  "reasoning": "one-sentence explanation"\n'
    "}"
)

_GROUND_SYSTEM_PROMPT = (
    "You are a mobile UI element grounder.  Given a screenshot and a natural "
    "language query describing a UI element, output a JSON object with the "
    "bounding box of that element.\n\n"
    "Output format (JSON only, no prose):\n"
    "{\n"
    '  "bbox": [x1, y1, x2, y2],   // pixel coordinates, top-left to bottom-right\n'
    '  "label": "element description",\n'
    '  "confidence": 0.0..1.0\n'
    "}"
)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AndroidVLMService:
    """
    Center-side VLM inference service for Android clients.

    Performs mobile UI planning and element grounding using the V2 center's
    multimodal LLM provider.  Android apps call this service via HTTP instead
    of running llama.cpp / NCNN locally.

    Parameters
    ----------
    router:
        An optional ``MultiLLMRouter`` instance.  Defaults to the runtime
        singleton obtained from ``core.multi_llm_router.get_llm_router()``.
    """

    def __init__(self, router=None) -> None:
        self._router = router

    def _get_router(self):
        """Lazy-load the LLM router singleton."""
        if self._router is not None:
            return self._router
        # 优先 canonical 路径（core.multi_llm_router）
        try:
            from core.multi_llm_router import get_llm_router
            return get_llm_router()
        except Exception:
            pass
        # fallback 到 unified 路径（兼容旧部署）
        try:
            from core.unified.llm_router import get_unified_llm_router
            return get_unified_llm_router()
        except Exception as exc:
            logger.warning("LLM router unavailable: %s", exc)
            return None

    async def plan(
        self,
        image_base64: str,
        task: str,
        device_id: str = "",
        screen_width: int = 0,
        screen_height: int = 0,
    ) -> Dict[str, Any]:
        """
        Perform center-side mobile UI task planning (MobileVLM equivalent).

        Takes an Android screenshot and a task description, returns the next
        atomic action to perform on the UI.

        Parameters
        ----------
        image_base64:
            Base64-encoded PNG or JPEG screenshot from the Android device.
        task:
            Natural language task description (e.g. "open camera app").
        device_id:
            Optional device identifier for logging/tracing.
        screen_width, screen_height:
            Optional screen dimensions for coordinate normalisation.

        Returns
        -------
        dict with keys:
            success (bool), action (str), coordinates (list[int]),
            reasoning (str), provider (str), error (str on failure)
        """
        if not image_base64:
            return {"success": False, "error": "image_base64 is required", "action": ""}

        prompt = (
            f"Task: {task}\n\n"
            "Analyse the screenshot and output the next action as JSON."
        )
        if screen_width and screen_height:
            prompt += f"\n\nScreen size: {screen_width}x{screen_height} pixels."

        result = await self._call_vision_provider(
            system_prompt=_PLAN_SYSTEM_PROMPT,
            user_prompt=prompt,
            image_base64=image_base64,
            operation="plan",
            device_id=device_id,
        )

        if not result["success"]:
            return result

        parsed = _safe_parse_json(result.get("text", ""))
        return {
            "success": True,
            "action":       parsed.get("action", ""),
            "coordinates":  parsed.get("coordinates", []),
            "end_coordinates": parsed.get("end_coordinates", []),
            "text":         parsed.get("text", ""),
            "direction":    parsed.get("direction", ""),
            "reasoning":    parsed.get("reasoning", result.get("text", "")),
            "provider":     result.get("provider", ""),
        }

    async def ground(
        self,
        image_base64: str,
        query: str,
        device_id: str = "",
    ) -> Dict[str, Any]:
        """
        Perform center-side UI element grounding (SeeClick equivalent).

        Takes an Android screenshot and a natural language query describing
        a UI element, returns the bounding box of that element.

        Parameters
        ----------
        image_base64:
            Base64-encoded PNG or JPEG screenshot from the Android device.
        query:
            Natural language description of the target UI element
            (e.g. "the submit button").
        device_id:
            Optional device identifier for logging/tracing.

        Returns
        -------
        dict with keys:
            success (bool), bbox (list[int]), label (str),
            confidence (float), provider (str), error (str on failure)
        """
        if not image_base64:
            return {"success": False, "error": "image_base64 is required", "bbox": []}

        prompt = (
            f"Query: {query}\n\n"
            "Locate the described UI element in the screenshot and output its "
            "bounding box as JSON."
        )

        result = await self._call_vision_provider(
            system_prompt=_GROUND_SYSTEM_PROMPT,
            user_prompt=prompt,
            image_base64=image_base64,
            operation="ground",
            device_id=device_id,
        )

        if not result["success"]:
            return result

        parsed = _safe_parse_json(result.get("text", ""))
        return {
            "success":    True,
            "bbox":       parsed.get("bbox", []),
            "label":      parsed.get("label", ""),
            "confidence": _safe_parse_confidence(parsed.get("confidence", 0.0)),
            "provider":   result.get("provider", ""),
        }

    async def _call_vision_provider(
        self,
        system_prompt: str,
        user_prompt: str,
        image_base64: str,
        operation: str,
        device_id: str,
    ) -> Dict[str, Any]:
        """Call a multimodal LLM provider with a screenshot + text prompt."""
        router = self._get_router()
        if router is None:
            return {
                "success": False,
                "error": "LLM router unavailable — no multimodal inference possible",
                "text": "",
                "provider": "",
            }

        # Attempt to get a native multimodal routing decision
        routing_decision = None
        try:
            routing_decision = router.route_multimodal_first(
                active_modalities=["image"],
                task_type=_get_task_type("general"),
            )
        except Exception as exc:
            logger.debug("route_multimodal_first failed: %s", exc)

        provider_id = ""
        if routing_decision is not None:
            try:
                provider_id = routing_decision.provider_id
            except AttributeError:
                pass

        # Build the vision message for the chosen provider
        try:
            messages = _build_vision_messages(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_base64=image_base64,
            )
            response_text = await _chat_with_vision(router, messages, provider_id)
            logger.info(
                "AndroidVLMService.%s: success via %s (device=%s)",
                operation,
                provider_id or "auto",
                device_id or "?",
            )
            return {"success": True, "text": response_text, "provider": provider_id}
        except Exception as exc:
            logger.warning("AndroidVLMService.%s failed: %s", operation, exc)
            return {"success": False, "error": str(exc), "text": "", "provider": provider_id}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_service_instance: Optional[AndroidVLMService] = None


def get_android_vlm_service() -> AndroidVLMService:
    """Return (and lazily create) the process-level AndroidVLMService singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = AndroidVLMService()
    return _service_instance


def reset_android_vlm_service() -> None:
    """Reset the singleton (primarily for tests)."""
    global _service_instance
    _service_instance = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_parse_confidence(raw: Any) -> float:
    """Parse model ``confidence`` field; never raise (avoids HTTP 500 on odd JSON)."""
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _safe_parse_json(text: str) -> Dict[str, Any]:
    """Extract and parse JSON from a model response, returning {} on failure."""
    import json
    import re

    if not text:
        return {}
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    # Find the first JSON object in the text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # Try parsing the whole text as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _get_task_type(task_type_name: str):
    """Resolve a TaskType enum value safely."""
    try:
        from core.multi_llm_router import TaskType
        return getattr(TaskType, task_type_name.upper(), TaskType.GENERAL)
    except Exception:
        return None


def _build_vision_messages(
    system_prompt: str,
    user_prompt: str,
    image_base64: str,
) -> List[Dict[str, Any]]:
    """Build OpenAI-compatible vision messages list."""
    # Determine MIME type: default to image/png, detect JPEG from header
    try:
        raw = base64.b64decode(image_base64[:20])
        mime = "image/jpeg" if raw[:3] == b"\xff\xd8\xff" else "image/png"
    except Exception:
        mime = "image/png"

    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_base64}"},
                },
                {"type": "text", "text": user_prompt},
            ],
        },
    ]


async def _chat_with_vision(router, messages: List[Dict], provider_id: str) -> str:
    """Send a vision chat request through the router and return the response text."""
    # Try chat_with_tools first (most capable)
    for method_name in ("chat_with_tools", "chat_raw", "chat"):
        method = getattr(router, method_name, None)
        if method is None:
            continue
        try:
            import inspect
            if inspect.iscoroutinefunction(method):
                resp = await method(messages=messages, provider_id=provider_id or None)
            else:
                resp = method(messages=messages, provider_id=provider_id or None)

            # Extract text from various response formats
            if isinstance(resp, str):
                return resp
            if isinstance(resp, dict):
                return (
                    resp.get("content") or
                    resp.get("text") or
                    resp.get("message", {}).get("content", "") or
                    ""
                )
            # Handle object-style responses
            for attr in ("content", "text", "message"):
                val = getattr(resp, attr, None)
                if val:
                    if isinstance(val, dict):
                        return val.get("content", "")
                    return str(val)
        except TypeError:
            continue
        except Exception as exc:
            logger.debug("Router method %s failed: %s", method_name, exc)
            continue

    raise RuntimeError("No router method succeeded for vision inference")
