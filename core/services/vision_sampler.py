#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — Vision Sampler Service
=================================

Server-side service that pulls frames from Node_95 WebRTC Receiver at a
configurable frame rate, feeds them into the runtime shell as multi-modal
context, and optionally routes any returned action command via command_router.

Usage example::

    from core.services.vision_sampler import run_sampling_session

    result = await run_sampling_session(
        device_id="dev_abc",
        fps=1,
        duration=10,
        prompt="Describe what you see and suggest the next action.",
    )

Environment variables:
    NODE_95_URL  — Base URL of Node_95 WebRTC Receiver.
                   Defaults to ``http://localhost:8095``.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.VisionSampler")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_NODE_95_URL = "http://localhost:8095"
_DEFAULT_PROMPT = (
    "Observe the current screen or camera view.  "
    "Describe what you see and, if an action is needed, specify it clearly."
)
# Minimum frames-per-second guard to avoid zero/negative interval arithmetic.
_MIN_FPS: float = 0.01
# Accepted URL schemes for NODE_95_URL to prevent SSRF via the env var.
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _node_95_url() -> str:
    """Return the Node_95 base URL from the environment, with fallback.

    Only ``http://`` and ``https://`` schemes are permitted to prevent
    accidental SSRF via the ``NODE_95_URL`` environment variable.
    """
    raw = os.environ.get("NODE_95_URL", _DEFAULT_NODE_95_URL).rstrip("/")
    try:
        from urllib.parse import urlparse
        scheme = urlparse(raw).scheme.lower()
    except Exception:
        scheme = ""
    if scheme not in _ALLOWED_SCHEMES:
        logger.warning(
            "VisionSampler: NODE_95_URL scheme '%s' is not allowed; "
            "falling back to default URL.",
            scheme,
        )
        return _DEFAULT_NODE_95_URL
    return raw


# ---------------------------------------------------------------------------
# Frame fetching
# ---------------------------------------------------------------------------

async def _fetch_frame(
    session: Any,  # aiohttp.ClientSession
    device_id: str,
    node_url: str,
) -> Optional[bytes]:
    """Fetch a single JPEG frame from Node_95.

    Returns raw JPEG bytes on success, or ``None`` if the request fails.
    """
    url = f"{node_url}/frame/{device_id}"
    try:
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                return await resp.read()
            logger.warning(
                "VisionSampler: frame fetch returned HTTP %d for device=%s",
                resp.status,
                device_id,
            )
            return None
    except Exception as exc:
        logger.warning(
            "VisionSampler: failed to fetch frame from %s — %s",
            url,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_sampling_session(
    device_id: str,
    fps: float = 1.0,
    duration: float = 10.0,
    prompt: Optional[str] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a vision sampling session and return a structured result.

    The function pulls frames from Node_95 at *fps* frames per second for
    *duration* seconds, packages them as base64-encoded images into a
    :class:`~core.schemas.multimodal.MultiModalContext`, calls
    ``DesktopPresenceRuntime.handle_request()`` so the canonical runtime shell
    owns the ingress, and — if the response carries an ``action`` payload —
    wraps it in a :class:`~core.schemas.task_envelope.TaskEnvelope` and routes
    it via ``command_router.route_envelope``.

    Args:
        device_id: The target device identifier used to fetch frames.
        fps:       Frames per second to sample (default 1.0).  Values above
                   the Node_95 capture rate are silently clamped by the
                   upstream receiver.
        duration:  Total sampling window in seconds (default 10.0).
        prompt:    Optional instruction passed to the runtime shell.  Falls back to a
                    built-in observe-and-suggest prompt when omitted.
        mode:      Optional mode hint forwarded downstream (e.g.
                    ``"observe"``, ``"control"``).

    Returns:
        A dict with the following keys::

            {
                "success": bool,
                "frames_sampled": int,
                "openclawd_response": dict | None,
                "command_result": dict | None,
            }
    """
    effective_prompt = prompt or _DEFAULT_PROMPT
    node_url = _node_95_url()
    interval = max(1.0 / max(fps, _MIN_FPS), 0.0)

    frames_sampled = 0
    images: List[Any] = []  # List[MultiModalImage]

    # ── Import schemas lazily to avoid circular imports at module load time ──
    try:
        from core.schemas.multimodal import MultiModalImage, MultiModalContext
    except ImportError as exc:
        logger.error("VisionSampler: cannot import multimodal schemas — %s", exc)
        return {
            "success": False,
            "frames_sampled": 0,
            "openclawd_response": None,
            "command_result": None,
            "error": f"Schema import failed: {exc}",
        }

    # ── Collect frames ───────────────────────────────────────────────────────
    try:
        import aiohttp  # type: ignore

        t_end = time.monotonic() + duration
        async with aiohttp.ClientSession() as session:
            while time.monotonic() < t_end:
                frame_start = time.monotonic()
                raw = await _fetch_frame(session, device_id, node_url)
                if raw:
                    b64 = base64.b64encode(raw).decode("utf-8")
                    images.append(
                        MultiModalImage(
                            mime="image/jpeg",
                            data=b64,
                            source="node_95_webrtc",
                        )
                    )
                    frames_sampled += 1
                    logger.debug(
                        "VisionSampler: captured frame %d (device=%s)",
                        frames_sampled,
                        device_id,
                    )
                elapsed = time.monotonic() - frame_start
                sleep_for = max(0.0, interval - elapsed)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

    except ImportError:
        logger.warning(
            "VisionSampler: aiohttp not available — attempting fallback with urllib"
        )
        # ── urllib fallback for environments without aiohttp ─────────────────
        import urllib.request

        t_end = time.monotonic() + duration
        loop = asyncio.get_running_loop()
        while time.monotonic() < t_end:
            frame_start = time.monotonic()
            url = f"{node_url}/frame/{device_id}"
            try:
                raw = await loop.run_in_executor(
                    None, lambda u=url: urllib.request.urlopen(u, timeout=5).read()  # noqa: S310 – URL validated by _node_95_url()
                )
                b64 = base64.b64encode(raw).decode("utf-8")
                images.append(
                    MultiModalImage(
                        mime="image/jpeg",
                        data=b64,
                        source="node_95_webrtc",
                    )
                )
                frames_sampled += 1
            except Exception as exc:
                logger.warning("VisionSampler: urllib frame fetch failed — %s", exc)
            elapsed = time.monotonic() - frame_start
            sleep_for = max(0.0, interval - elapsed)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    except Exception as exc:
        logger.error("VisionSampler: frame collection error — %s", exc)
        return {
            "success": False,
            "frames_sampled": frames_sampled,
            "openclawd_response": None,
            "command_result": None,
            "error": str(exc),
        }

    if frames_sampled == 0:
        logger.warning(
            "VisionSampler: no frames captured for device=%s — Node_95 may be unreachable",
            device_id,
        )
        return {
            "success": False,
            "frames_sampled": 0,
            "openclawd_response": None,
            "command_result": None,
            "error": "No frames captured; Node_95 may be unreachable.",
        }

    # ── Build MultiModalContext ──────────────────────────────────────────────
    mm_context = MultiModalContext(images=images)

    # ── Call runtime shell ───────────────────────────────────────────────────
    runtime_response: Optional[Dict[str, Any]] = None
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime

        runtime = get_desktop_presence_runtime()
        # Derive a stable session_id for this sampling run so the carrier can
        # be correlated through the authority chain.
        _session_id = f"vision_sampler_{device_id}"
        runtime_response = await runtime.handle_request(
            message=effective_prompt,
            source="vision_sampler",
            device_id=device_id,
            session_id=_session_id,
            user_id=device_id or "vision_sampler",
            multimodal_context=mm_context,
            entry_mode="local",
            mode=mode,
        )
        logger.info(
            "VisionSampler: runtime shell processed %d frame(s) for device=%s",
            frames_sampled,
            device_id,
        )
    except Exception as exc:
        logger.error("VisionSampler: runtime shell request failed — %s", exc)
        return {
            "success": False,
            "frames_sampled": frames_sampled,
            # Backward-compat alias retained for callers still reading the
            # historical field name from the pre-runtime-shell path.
            "openclawd_response": None,
            "runtime_response": None,
            "command_result": None,
            "error": f"Runtime shell error: {exc}",
        }

    # ── Route action command if present ─────────────────────────────────────
    command_result: Optional[Dict[str, Any]] = None
    action = None
    if runtime_response:
        action = (
            runtime_response.get("action")
            or runtime_response.get("metadata", {}).get("action")
        )

    if action and isinstance(action, dict):
        action_device = action.get("device_id") or device_id
        action_command = action.get("command", "")
        action_params = action.get("params") or action.get("payload") or {}

        if action_command:
            try:
                from core.command_router import get_command_router
                from core.schemas.task_envelope import TaskEnvelope

                cmd_router = get_command_router()
                task_id = f"vision_task_{uuid.uuid4().hex[:12]}"
                # PR-1: wrap action command in TaskEnvelope and use route_envelope
                envelope = TaskEnvelope(
                    task_id=task_id,
                    source="vision_sampler",
                    targets=[action_device],
                    tool_name=action_command,
                    args=action_params,
                    metadata={
                        "command_id": f"vision_cmd_{uuid.uuid4().hex[:12]}",
                        "device_id": action_device,
                    },
                )
                command_result = await cmd_router.route_envelope(envelope)
                logger.info(
                    "VisionSampler: routed command=%s to device=%s (success=%s)",
                    action_command,
                    action_device,
                    command_result.get("success"),
                )
            except Exception as exc:
                logger.error(
                    "VisionSampler: route_envelope failed — %s", exc
                )
                command_result = {"success": False, "error": str(exc)}

    return {
        "success": True,
        "frames_sampled": frames_sampled,
        # Backward-compat alias retained for callers still reading the
        # historical field name from the pre-runtime-shell path.
        "openclawd_response": runtime_response,
        "runtime_response": runtime_response,
        "command_result": command_result,
        "streaming_role": "derived_snapshot_bridge_from_continuous_stream",
        "stream_source_authority": "NODE_95_URL",
    }
