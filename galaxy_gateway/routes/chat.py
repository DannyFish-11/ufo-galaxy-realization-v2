"""
galaxy_gateway/routes/chat.py — Chat adapter surface and WebRTC routes.

This module is an **adapter surface** for the unified subject architecture.
It does NOT own subject-core authority — all chat requests are forwarded to
``DesktopPresenceRuntime.handle_request()`` which drives subject lifecycle.

Authority chain (PR-1):
    gateway /api/v1/chat  (adapter surface — no authority)
        → DesktopPresenceRuntime.handle_request(source="chat")
            → OpenClawd.process()   ← subject core

Routes:
  POST /api/v1/chat           - Chat adapter endpoint
  GET  /api/v1/webrtc/endpoint - WebRTC endpoint discovery
  WS   /ws/webrtc/{device_id} - WebRTC signaling proxy (registered in websocket.py)
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from pydantic import field_validator as _field_validator
except ImportError:  # pragma: no cover - pydantic v1 fallback
    from pydantic import validator as _field_validator  # type: ignore

from galaxy_gateway.cross_device_switch import (
    is_cross_device_enabled,
    HTTP_STATUS_CROSS_DEVICE_DISABLED,
    ERROR_CODE_CROSS_DEVICE_DISABLED,
    ERROR_MSG_CROSS_DEVICE_DISABLED,
)
from galaxy_gateway.webrtc_proxy import (
    check_node95_reachable,
    get_webrtc_endpoint_info,
)

try:
    from core.auth import require_auth as _require_auth
except ImportError:

    async def _require_auth():  # type: ignore[misc]
        return {"authenticated": True, "dev_mode": True}


logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    context: Optional[dict] = None
    # PR-3: multimodal context bundle — absent for text-only requests.
    # Passed through intact to OpenClawd.process() for multimodal fusion.
    multimodal_context: Optional[dict] = None
    # PR-1 EntryMode: caller-supplied execution mode override.
    # When absent, the mode is auto-resolved from the cross-device switch and
    # device registry.  One of: "local" | "cross_device" | "hybrid".
    entry_mode: Optional[str] = None
    # PR-5 Cross-device: explicit target device ID for this request.
    # When provided (and cross-device routing is enabled), forces cross_device
    # mode regardless of the online device count.
    target_device: Optional[str] = None
    # Source-device runtime participation posture. Kept separate from entry_mode:
    # "control_only" means the source device remains only the controller;
    # "join_runtime" means the source device is also a runtime participant.
    source_runtime_posture: Optional[str] = None

    @_field_validator("source_runtime_posture")
    @classmethod
    def _validate_source_runtime_posture(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        from core.source_runtime_posture import SourceRuntimePosture

        normalized = str(value).strip().lower()
        allowed = {posture.value for posture in SourceRuntimePosture}
        if normalized not in allowed:
            raise ValueError(
                "source_runtime_posture must be one of: " + ", ".join(sorted(allowed)) + f". Got: {normalized}"
            )
        return normalized


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _merge_parallel_result(result: dict) -> dict:
    """Promote ``parallel_result`` to the response top level when available.

    Priority:
    1. ``result`` already contains top-level ``parallel_result`` — return as-is.
    2. ``result.metadata.parallel_result`` exists (from OpenClawd sync parallel
       stream) — promote to top level.
    3. ``result`` or ``result.metadata`` contains ``group_id`` — query the
       gateway ``ParallelGroupTracker``.
    """
    if not isinstance(result, dict):
        return result

    if "parallel_result" in result:
        return result

    metadata = result.get("metadata") or {}

    # Case 2: OpenClawd sync parallel result already in metadata
    if isinstance(metadata, dict) and "parallel_result" in metadata:
        return {**result, "parallel_result": metadata["parallel_result"]}

    # Case 3: look up via group_id in gateway tracker
    group_id = None
    if isinstance(metadata, dict):
        group_id = metadata.get("parallel_group") or metadata.get("group_id")
    if not group_id:
        group_id = result.get("group_id")

    if group_id:
        try:
            from galaxy_gateway.orchestrator.parallel_tracker import get_tracker

            gs = get_tracker().get_group_status(str(group_id))
            if gs is not None:
                return {**result, "parallel_result": gs.to_dict()}
        except Exception as _err:
            logger.debug("parallel_tracker merge skipped: %s", _err)

    return result


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@router.post("/api/v1/chat")
async def chat_endpoint(
    request: ChatRequest,
    auth: dict = Depends(_require_auth),
):
    """Adapter surface — delegates to DesktopPresenceRuntime (runtime shell).

    This endpoint is an **adapter surface** in the galaxy_gateway internal
    substrate.  It does NOT own subject-core authority.  All requests are
    forwarded to ``DesktopPresenceRuntime.handle_request(source="chat")``,
    which drives the tri-state lifecycle (SILENT → LIMINAL → MANIFEST → SILENT)
    and delegates subject cognition to ``OpenClawd``.

    Response includes backward-compatible fields (reply, response, intent)
    plus ``runtime_session_id`` for end-to-end correlation.
    """
    # ── Target-device validation (additive, non-blocking) ──
    _target_device = request.target_device or None
    if _target_device:
        try:
            from core.target_device_validator import validate_target_device as _vtd

            _vr = _vtd(_target_device)
            if not _vr.valid:
                logger.warning(
                    "chat_endpoint: target_device=%s failed validation — reasons=%s",
                    _target_device,
                    _vr.reasons,
                )
        except Exception as _vtd_exc:
            logger.debug("target_device validation skipped (non-fatal): %s", _vtd_exc)

    # ── PR-5 EntryMode: resolve execution mode ──
    _entry_mode = "local"
    try:
        from core.unified.entrypoint_router import resolve_entry_mode as _resolve_em

        _entry_mode = _resolve_em(
            explicit_entry_mode=request.entry_mode or None,
            target_device=_target_device,
            source="galaxy_gateway.app",
        )
    except Exception as _em_exc:
        logger.debug("resolve_entry_mode failed (non-fatal): %s", _em_exc)

    # ── PR-1: Route through DesktopPresenceRuntime ──
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime

        runtime = get_desktop_presence_runtime()
        # Normalise context: DesktopPresenceRuntime expects Optional[List[Dict]].
        _context = [request.context] if isinstance(request.context, dict) and request.context else None
        result = await runtime.handle_request(
            message=request.message,
            source="chat",
            device_id=request.device_id,
            session_id=request.session_id or "gateway_default",
            context=_context,
            multimodal_context=request.multimodal_context,
            entry_mode=_entry_mode,
            source_runtime_posture=request.source_runtime_posture,
        )
        # Backward-compatible alias (reply = response) for legacy clients
        if isinstance(result, dict) and "reply" not in result:
            result = {**result, "reply": result.get("response", "")}
        result = _merge_parallel_result(result)
        return result
    except Exception as e:
        logger.error("DesktopPresenceRuntime chat processing failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat processing error: {e}")


# ---------------------------------------------------------------------------
# WebRTC endpoint discovery
# ---------------------------------------------------------------------------


@router.get("/api/v1/webrtc/endpoint")
async def webrtc_endpoint_info():
    """Return WebRTC signaling endpoint metadata.

    Returns HTTP 403 when cross-device routing is disabled (Round 4 switch).
    Returns HTTP 503 when Node_95 is not reachable.
    """
    if not is_cross_device_enabled():
        trace_id = str(uuid.uuid4())
        logger.warning(
            "cross_device_blocked event=webrtc_endpoint trace_id=%s reason=%s",
            trace_id,
            ERROR_CODE_CROSS_DEVICE_DISABLED,
        )
        raise HTTPException(
            status_code=HTTP_STATUS_CROSS_DEVICE_DISABLED,
            detail={
                "error": ERROR_CODE_CROSS_DEVICE_DISABLED,
                "message": ERROR_MSG_CROSS_DEVICE_DISABLED,
                "trace_id": trace_id,
            },
        )
    if not await check_node95_reachable():
        raise HTTPException(
            status_code=503,
            detail="Node_95 WebRTC Receiver is not reachable",
        )
    return get_webrtc_endpoint_info()
