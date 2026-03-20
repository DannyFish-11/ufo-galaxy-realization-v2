#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/entrypoint_router.py
===================================
PR-1 (Block-1) — Unified Entrypoint Router

Acts as the **first-hop** for all ingress requests before they reach
OpenClawd or any other handler.  This module:

1. Stamps every request with routing metadata:
   - ``entry_path``: ``"canonical"`` | ``"legacy"``
   - ``via_legacy_adapter``: ``True`` when routed through a legacy adapter
   - ``trace_id``: globally unique end-to-end correlation ID
   - ``routed_at``: Unix timestamp when routing occurred

2. Provides a single ``route_request(...)`` coroutine used by
   ``core/routes/chat.py``, ``core/openclawd.py``, and any adapter.

3. Delegates actual processing to the provided ``handler`` callable,
   which should ultimately call ``OpenClawd.process()`` or
   ``DesktopPresenceRuntime.handle_request()``.

Design goals
------------
- **Additive** — existing code paths are unaffected; this module is called
  *before* existing logic, not instead of it.
- **No circular imports** — only stdlib is used at module level.  Heavy
  imports (OpenClawd, bus) happen lazily inside the method.
- **Observable** — emits a ``StateEventBus`` event so canonical vs legacy
  path usage can be monitored.

Usage (canonical path)::

    from core.unified.entrypoint_router import get_entrypoint_router

    router = get_entrypoint_router()
    result = await router.route_request(
        message="open chrome",
        source="chat",
        handler=my_handler,
        device_id="dev-001",
        session_id="sess-abc",
    )

Usage (legacy adapter path)::

    router = get_entrypoint_router()
    result = await router.route_request(
        message=msg,
        source="legacy_connection_manager",
        handler=my_handler,
        via_legacy_adapter=True,
    )
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("Galaxy.Unified.EntrypointRouter")


# ---------------------------------------------------------------------------
# EntrypointRouter
# ---------------------------------------------------------------------------


class EntrypointRouter:
    """First-hop request router that stamps metadata and delegates to a handler.

    This class is a **thin wrapper** — it does not implement business logic.
    Its sole responsibilities are:

    - Assign a ``trace_id`` if one is not already present.
    - Determine ``entry_path`` (``canonical`` or ``legacy``).
    - Emit an observability event on the StateEventBus (best-effort).
    - Call the provided ``handler`` and return its result unchanged.
    """

    def __init__(self) -> None:
        self._request_count: int = 0
        self._legacy_count: int = 0
        self._canonical_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route_request(
        self,
        *,
        message: str,
        source: str,
        handler: Callable[..., Awaitable[Dict[str, Any]]],
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[Any] = None,
        required_capabilities: Optional[Any] = None,
        multimodal_context: Optional[Any] = None,
        runtime_session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        via_legacy_adapter: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Route an ingress request through the canonical first-hop.

        Parameters
        ----------
        message:
            User/system message text.
        source:
            Human-readable identifier of the caller (e.g. ``"chat"``,
            ``"legacy_connection_manager"``, ``"android_ws"``).
        handler:
            Async callable that performs the actual processing.  It receives
            all keyword arguments that this method accepts (minus ``handler``
            itself) plus the generated ``trace_id``.  Must return a ``dict``.
        device_id:
            Optional device identifier.
        session_id:
            Optional session identifier.
        context:
            Optional conversation context list.
        required_capabilities:
            Optional list of required device capabilities.
        multimodal_context:
            Optional multimodal context bundle.
        runtime_session_id:
            Optional runtime session ID from DesktopPresenceRuntime.
        trace_id:
            If provided, used as-is; otherwise a new UUID is generated.
        via_legacy_adapter:
            ``True`` when called from a legacy adapter.  Sets
            ``entry_path="legacy"`` in the routing metadata.
        extra:
            Arbitrary extra key/value pairs forwarded to the handler.

        Returns
        -------
        dict
            The result dict returned by ``handler``, augmented with a
            ``_routing`` key containing the routing metadata.
        """
        self._request_count += 1

        effective_trace_id = trace_id or runtime_session_id or uuid.uuid4().hex
        entry_path = "legacy" if via_legacy_adapter else "canonical"

        if via_legacy_adapter:
            self._legacy_count += 1
        else:
            self._canonical_count += 1

        routing_meta: Dict[str, Any] = {
            "entry_path": entry_path,
            "via_legacy_adapter": via_legacy_adapter,
            "trace_id": effective_trace_id,
            "source": source,
            "routed_at": time.time(),
        }

        logger.debug(
            "EntrypointRouter.route_request | entry_path=%s via_legacy=%s "
            "source=%s trace_id=%s",
            entry_path,
            via_legacy_adapter,
            source,
            effective_trace_id,
        )

        # Best-effort observability event
        self._emit_routing_event(routing_meta)

        # Build kwargs for the handler
        handler_kwargs: Dict[str, Any] = {
            "message": message,
            "source": source,
            "device_id": device_id,
            "session_id": session_id,
            "context": context,
            "required_capabilities": required_capabilities,
            "multimodal_context": multimodal_context,
            "runtime_session_id": effective_trace_id,
            "trace_id": effective_trace_id,
            "via_legacy_adapter": via_legacy_adapter,
        }
        if extra:
            handler_kwargs.update(extra)

        result = await handler(**handler_kwargs)

        # Augment result with routing metadata (non-breaking: added under _routing key)
        if isinstance(result, dict):
            result.setdefault("_routing", routing_meta)

        return result

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        """Return routing statistics (total, canonical, legacy counts)."""
        return {
            "total": self._request_count,
            "canonical": self._canonical_count,
            "legacy": self._legacy_count,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_routing_event(self, routing_meta: Dict[str, Any]) -> None:
        """Best-effort emission on StateEventBus (never raises)."""
        try:
            from core.state_event_bus import emit as _seb_emit, StateEventType

            # Use TASK_STARTED as a generic ingress event type; the payload
            # carries the full routing metadata for differentiation.
            _seb_emit(
                StateEventType.TASK_STARTED,
                source="entrypoint_router",
                payload={
                    "event_kind": "request_routed",
                    **routing_meta,
                },
                trace_id=routing_meta.get("trace_id", ""),
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_entrypoint_router_instance: Optional[EntrypointRouter] = None


def get_entrypoint_router() -> EntrypointRouter:
    """Return the process-level singleton EntrypointRouter."""
    global _entrypoint_router_instance
    if _entrypoint_router_instance is None:
        _entrypoint_router_instance = EntrypointRouter()
    return _entrypoint_router_instance


def reset_entrypoint_router() -> None:
    """Reset the singleton (for testing only)."""
    global _entrypoint_router_instance
    _entrypoint_router_instance = None


# ---------------------------------------------------------------------------
# Entry-mode resolution (PR-1 EntryMode unification)
# ---------------------------------------------------------------------------

def resolve_entry_mode(
    explicit_entry_mode: Optional[str] = None,
    *,
    target_device: Optional[str] = None,
    trace_id: str = "",
    source: str = "",
) -> str:
    """Resolve the ``entry_mode`` for a request and emit an observability event.

    Resolution rules (applied in order):

    1. If *explicit_entry_mode* is provided by the caller, use it as-is.
    2. Else, if cross-device routing is **enabled** *and* either:

       - *target_device* is explicitly specified in the request, **or**
       - more than one device is currently registered/available (>=2),

       return ``"cross_device"``.
    3. Else return ``"local"``.

    The result is always emitted as a :data:`StateEventType.ENTRY_MODE_RESOLVED`
    event on the state event bus (best-effort, never raises).  When
    ``"cross_device"`` is selected automatically, an additional INFO-level
    structured log entry is written that includes *device_count* and *trace_id*
    so operators can correlate the selection decision.

    Args:
        explicit_entry_mode: Optional caller-supplied override.  When not
            ``None`` (and not an empty string) it is returned unchanged.
        target_device: Optional explicit target device ID from the request.
            When provided (and cross-device is enabled), forces
            ``"cross_device"`` mode regardless of the online device count.
        trace_id: End-to-end correlation ID for the current request.
        source: Human-readable label for the calling module (for observability).

    Returns:
        One of ``"local"``, ``"cross_device"``, or the caller-supplied value.
    """
    resolved: str
    resolution_source: str
    _device_count: int = 0

    if explicit_entry_mode:
        resolved = explicit_entry_mode
        resolution_source = "caller_explicit"
    else:
        # Determine mode from cross-device switch + device registry / target
        _cross_device_on = False
        try:
            from galaxy_gateway.cross_device_switch import is_cross_device_enabled
            _cross_device_on = is_cross_device_enabled()
        except Exception:
            pass

        if _cross_device_on:
            try:
                from core.unified.device_manager import get_unified_device_manager
                _device_count = get_unified_device_manager().get_online_count()
            except Exception:
                pass

        _explicit_target = bool(target_device and target_device.strip())
        _has_multiple_devices = _device_count >= 2

        if _cross_device_on and (_explicit_target or _has_multiple_devices):
            resolved = "cross_device"
            if _explicit_target:
                resolution_source = "auto_target_device"
            else:
                resolution_source = "auto_cross_device"
            # Structured INFO log for observability
            logger.info(
                "cross_device_mode_selected source=%s trace_id=%s "
                "device_count=%d target_device=%s resolution_source=%s",
                source or "entrypoint_router",
                trace_id,
                _device_count,
                target_device or "",
                resolution_source,
            )
        else:
            resolved = "local"
            resolution_source = "auto_local"

    # Best-effort observability event
    try:
        from core.state_event_bus import emit as _seb_emit, StateEventType
        _seb_emit(
            StateEventType.ENTRY_MODE_RESOLVED,
            source=source or "entrypoint_router",
            payload={
                "entry_mode": resolved,
                "resolution_source": resolution_source,
                "device_count": _device_count,
                "target_device": target_device or "",
                "trace_id": trace_id,
            },
            trace_id=trace_id,
        )
    except Exception:
        pass

    return resolved


__all__ = [
    "EntrypointRouter",
    "get_entrypoint_router",
    "reset_entrypoint_router",
    "resolve_entry_mode",
]
