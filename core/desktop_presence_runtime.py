"""
core.desktop_presence_runtime — Unified Control-Plane Runtime
=============================================================

This module provides the single control-plane runtime for the Galaxy system.
All high-level request entrypoints (chat, OpenClawd, E2E) are routed through
:class:`DesktopPresenceRuntime`, which owns the canonical **tri-state
progression**:

    silent  →  liminal  →  manifest  →  silent

Responsibilities
----------------
- Accept requests from chat / OpenClawd / E2E entrypoints via :meth:`handle_request`.
- Emit a single ``runtime_session_id`` that is propagated through the entire
  request lifecycle and is present in every downstream log entry.
- Drive tri-state transitions and enforce that no entrypoint can skip the
  progression.
- Provide observability hooks (log entries) at each state transition and at
  the start/end of every handled request.
- Delegate actual LLM / agent / pipeline work to existing modules
  (OpenClawd, ConstellationRuntime, EndToEndPipeline) so that external
  behavior is preserved.

Tri-state mapping
-----------------
- ``SILENT``   — system is idle / background monitoring; no active request.
- ``LIMINAL``  — request received; intent evaluation and routing in progress.
- ``MANIFEST`` — active execution: LLM call, tool dispatch, device commands.
  After execution completes the session transitions back to ``SILENT``.

Usage::

    from core.desktop_presence_runtime import get_desktop_presence_runtime

    runtime = get_desktop_presence_runtime()
    result = await runtime.handle_request(
        message="打开微信",
        source="chat",
        device_id="pc_01",
        session_id=None,
    )
    # result["runtime_session_id"] is propagated all the way through.
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Runtime")


# ---------------------------------------------------------------------------
# Tri-state definition
# ---------------------------------------------------------------------------


class TriState(str, Enum):
    """Canonical tri-state progression for the Galaxy system.

    - ``SILENT``   — idle; no active high-level request.
    - ``LIMINAL``  — request received; evaluation / routing in progress.
    - ``MANIFEST`` — active execution; producing output or controlling devices.
    """

    SILENT = "silent"
    LIMINAL = "liminal"
    MANIFEST = "manifest"


# ---------------------------------------------------------------------------
# RuntimeSession — per-request lifecycle holder
# ---------------------------------------------------------------------------


class RuntimeSession:
    """Holds the lifecycle state of a single top-level request.

    Each call to :meth:`DesktopPresenceRuntime.handle_request` creates one
    ``RuntimeSession``.  The session is ephemeral and is discarded once the
    request completes.

    Attributes:
        runtime_session_id: Unique identifier for this runtime session.  Used
            as the stable correlation ID across all downstream log entries.
        trace_id: Alias for ``runtime_session_id``; kept for compatibility with
            existing trace propagation patterns.
        source: Entrypoint that originated the request.  One of ``"chat"``,
            ``"e2e"``, or ``"openclawd"``.
        tristate: Current tri-state phase of this session.
        created_at: Unix timestamp when the session was created.
        transitions: Ordered list of ``(TriState, timestamp)`` tuples recording
            every state transition.
    """

    def __init__(self, source: str) -> None:
        self.runtime_session_id: str = uuid.uuid4().hex
        self.trace_id: str = self.runtime_session_id
        self.source: str = source
        self.tristate: TriState = TriState.SILENT
        self.created_at: float = time.monotonic()
        self.transitions: List[tuple] = []

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def advance(self, new_state: TriState) -> None:
        """Advance the session to a new tri-state phase and record the event."""
        old_state = self.tristate
        self.tristate = new_state
        ts = time.monotonic()
        self.transitions.append((new_state, ts))
        logger.debug(
            "Runtime tristate transition | runtime_session_id=%s source=%s %s→%s",
            self.runtime_session_id,
            self.source,
            old_state.value,
            new_state.value,
        )
        # PR-8: emit phase transition on the unified state event bus.
        try:
            from core.state_event_bus import emit as _seb_emit, StateEventType
            _phase_map = {
                TriState.SILENT:   StateEventType.PHASE_SILENT,
                TriState.LIMINAL:  StateEventType.PHASE_LIMINAL,
                TriState.MANIFEST: StateEventType.PHASE_MANIFEST,
            }
            et = _phase_map.get(new_state)
            if et is not None:
                _seb_emit(
                    et,
                    source="desktop_presence_runtime",
                    payload={
                        "from_phase": old_state.value,
                        "to_phase": new_state.value,
                        "request_source": self.source,
                    },
                    trace_id=self.trace_id,
                    runtime_session_id=self.runtime_session_id,
                )
        except Exception:
            pass

    def elapsed_ms(self) -> float:
        """Return elapsed milliseconds since session creation."""
        return (time.monotonic() - self.created_at) * 1_000


# ---------------------------------------------------------------------------
# DesktopPresenceRuntime
# ---------------------------------------------------------------------------


class DesktopPresenceRuntime:
    """Single control-plane runtime — routes all high-level requests through
    the unified tri-state lifecycle.

    This class is the **sole authoritative entrypoint** for all high-level
    requests in the Galaxy system.  It enforces tri-state progression
    (silent → liminal → manifest → silent) for every request regardless of
    which UI or integration surface originated it.

    Instantiation is inexpensive; all heavy modules are loaded lazily.
    Use :func:`get_desktop_presence_runtime` to obtain the singleton.

    Notes
    -----
    Thread-safety: :meth:`handle_request` is an ``async`` coroutine and is
    safe to call concurrently.  The session dict uses plain Python dict
    operations; add an ``asyncio.Lock`` if strict ordering is required.
    """

    def __init__(self) -> None:
        # Active sessions keyed by runtime_session_id.
        # Sessions are removed upon completion to avoid unbounded growth.
        self._active_sessions: Dict[str, RuntimeSession] = {}
        logger.info("DesktopPresenceRuntime initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_request(
        self,
        message: str,
        *,
        source: str = "chat",
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: str = "default",
        context: Optional[List[Dict]] = None,
        required_capabilities: Optional[List[str]] = None,
        multimodal_context: Optional[Any] = None,
        use_constellation: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Handle a top-level request through the unified tri-state lifecycle.

        This is the **single** method that all entrypoints (chat route,
        OpenClawd, E2E orchestrator) must call.  It:

        1. Creates a :class:`RuntimeSession` with a unique ``runtime_session_id``.
        2. Advances the session through ``SILENT → LIMINAL → MANIFEST``.
        3. Delegates execution to the appropriate internal handler based on
           *source*.
        4. Advances back to ``SILENT`` after execution.
        5. Returns the handler result, augmented with ``runtime_session_id`` and
           ``tristate`` observability fields.

        Args:
            message: Natural-language request text.
            source: Originating entrypoint; one of ``"chat"``, ``"e2e"``,
                ``"openclawd"``.  Used for observability tagging only —
                does not change the routing logic.
            device_id: Optional source-device identifier.
            session_id: Optional external session identifier.  When ``None``
                a new session ID is derived from ``runtime_session_id``.
            user_id: User identifier for cross-device session correlation.
            context: Conversation history list.
            required_capabilities: Scheduler capability hints.
            multimodal_context: Multi-modal payload bundle (PR-1).
            use_constellation: When *True* (default) prefer
                ConstellationRuntime for ``source="e2e"`` requests.
            **kwargs: Additional keyword arguments forwarded to the underlying
                handler.

        Returns:
            A dict with at minimum::

                {
                    "success": bool,
                    "response": str,   # or "reply" for e2e paths
                    "runtime_session_id": str,
                    "trace_id": str,
                    "tristate": str,   # final phase ("silent")
                    "entrypoint_source": str,
                }
        """
        rsession = self._create_session(source)

        # SILENT → LIMINAL: request received, starting evaluation
        rsession.advance(TriState.LIMINAL)
        self._log_request_start(rsession, message, session_id, device_id)

        try:
            # LIMINAL → MANIFEST: active execution
            rsession.advance(TriState.MANIFEST)

            result = await self._dispatch(
                rsession=rsession,
                message=message,
                source=source,
                device_id=device_id,
                session_id=session_id or f"session_{rsession.runtime_session_id[:12]}",
                user_id=user_id,
                context=context,
                required_capabilities=required_capabilities,
                multimodal_context=multimodal_context,
                use_constellation=use_constellation,
                **kwargs,
            )

        except Exception as exc:
            logger.error(
                "DesktopPresenceRuntime._dispatch error | runtime_session_id=%s source=%s: %s",
                rsession.runtime_session_id,
                source,
                exc,
                exc_info=True,
            )
            result = {
                "success": False,
                "response": f"Runtime error: {exc}",
                "error": str(exc),
            }
        finally:
            # MANIFEST → SILENT: execution complete (even on error)
            rsession.advance(TriState.SILENT)
            self._log_request_end(rsession)
            self._active_sessions.pop(rsession.runtime_session_id, None)

        # Augment result with runtime observability fields
        result.setdefault("runtime_session_id", rsession.runtime_session_id)
        result.setdefault("trace_id", rsession.runtime_session_id)
        result["tristate"] = rsession.tristate.value
        result["entrypoint_source"] = source
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_session(self, source: str) -> RuntimeSession:
        """Create and register a new RuntimeSession."""
        session = RuntimeSession(source=source)
        self._active_sessions[session.runtime_session_id] = session
        return session

    async def _dispatch(
        self,
        rsession: RuntimeSession,
        message: str,
        source: str,
        device_id: Optional[str],
        session_id: str,
        user_id: str,
        context: Optional[List[Dict]],
        required_capabilities: Optional[List[str]],
        multimodal_context: Optional[Any],
        use_constellation: bool,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Route to the correct underlying handler based on *source*.

        All handlers receive ``runtime_session_id`` so they can propagate it
        to sub-systems (continuum orchestrator, audit ledger, task logger).

        Guardrail: every code path must go through this method.  If a new
        source is added, it must be explicitly listed here; unknown sources
        are routed to the OpenClawd handler with a warning log so that
        requests are never silently dropped.
        """
        if source in ("chat", "openclawd"):
            return await self._handle_via_openclawd(
                rsession=rsession,
                message=message,
                device_id=device_id,
                session_id=session_id,
                context=context,
                required_capabilities=required_capabilities,
                multimodal_context=multimodal_context,
            )

        if source == "e2e":
            return await self._handle_via_e2e(
                rsession=rsession,
                message=message,
                device_id=device_id,
                session_id=session_id,
                user_id=user_id,
                context=context,
                use_constellation=use_constellation,
            )

        # Unknown source — log a warning and fall back to OpenClawd so requests
        # are never silently dropped.
        logger.warning(
            "DesktopPresenceRuntime: unknown source=%r — falling back to OpenClawd handler. "
            "runtime_session_id=%s",
            source,
            rsession.runtime_session_id,
        )
        return await self._handle_via_openclawd(
            rsession=rsession,
            message=message,
            device_id=device_id,
            session_id=session_id,
            context=context,
            required_capabilities=required_capabilities,
            multimodal_context=multimodal_context,
        )

    # ------------------------------------------------------------------
    # Source-specific handlers
    # ------------------------------------------------------------------

    async def _handle_via_openclawd(
        self,
        rsession: RuntimeSession,
        message: str,
        device_id: Optional[str],
        session_id: str,
        context: Optional[List[Dict]],
        required_capabilities: Optional[List[str]],
        multimodal_context: Optional[Any],
    ) -> Dict[str, Any]:
        """Delegate to OpenClawd.process() with runtime_session_id propagation."""
        from core.openclawd import get_openclawd

        clawd = get_openclawd()
        result = await clawd.process(
            message=message,
            device_id=device_id,
            session_id=session_id,
            context=context,
            required_capabilities=required_capabilities,
            multimodal_context=multimodal_context,
            runtime_session_id=rsession.runtime_session_id,
        )
        # Normalise the result to always contain "response" (OpenClawd uses it)
        result.setdefault("response", result.get("reply", ""))
        return result

    async def _handle_via_e2e(
        self,
        rsession: RuntimeSession,
        message: str,
        device_id: Optional[str],
        session_id: str,
        user_id: str,
        context: Optional[List[Dict]],
        use_constellation: bool,
    ) -> Dict[str, Any]:
        """Delegate to the E2E pipeline with runtime_session_id propagation."""
        # Inject runtime_session_id into the context so downstream modules can
        # pick it up via the context list.
        augmented_context: List[Dict] = list(context or [])
        augmented_context.append(
            {
                "runtime_session_id": rsession.runtime_session_id,
                "trace_id": rsession.runtime_session_id,
            }
        )

        # Primary path: ConstellationRuntime
        if use_constellation:
            try:
                from core.constellation_runtime import get_constellation_runtime

                constellation = get_constellation_runtime()
                ctx_dict: Dict[str, Any] = {
                    "user_id": user_id,
                    "runtime_session_id": rsession.runtime_session_id,
                    "trace_id": rsession.runtime_session_id,
                }
                result = await constellation.run(
                    task_description=message,
                    device_id=device_id or "",
                    session_id=session_id,
                    user_id=user_id,
                    context=ctx_dict,
                )
                result.setdefault("response", result.get("reply", ""))
                return result
            except Exception as exc:
                logger.warning(
                    "ConstellationRuntime failed in E2E handler, falling back to pipeline: %s", exc
                )

        # Fallback: EndToEndPipeline
        from core.e2e_pipeline import get_pipeline

        pipeline = get_pipeline()
        result = await pipeline.execute(
            message=message,
            user_id=user_id,
            source_device_id=device_id or "",
            session_id=session_id,
            context=augmented_context,
        )
        result.setdefault("response", result.get("reply", ""))
        return result

    # ------------------------------------------------------------------
    # Observability helpers
    # ------------------------------------------------------------------

    def _log_request_start(
        self,
        rsession: RuntimeSession,
        message: str,
        session_id: Optional[str],
        device_id: Optional[str],
    ) -> None:
        """Emit a structured log entry at the start of every request."""
        logger.info(
            "Runtime request START | runtime_session_id=%s source=%s tristate=%s "
            "session_id=%s device_id=%s message=%r",
            rsession.runtime_session_id,
            rsession.source,
            rsession.tristate.value,
            session_id,
            device_id,
            message[:80],
        )

    def _log_request_end(self, rsession: RuntimeSession) -> None:
        """Emit a structured log entry at the end of every request."""
        logger.info(
            "Runtime request END | runtime_session_id=%s source=%s tristate=%s elapsed_ms=%.1f",
            rsession.runtime_session_id,
            rsession.source,
            rsession.tristate.value,
            rsession.elapsed_ms(),
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_runtime_instance: Optional[DesktopPresenceRuntime] = None


def get_desktop_presence_runtime() -> DesktopPresenceRuntime:
    """Return the process-wide :class:`DesktopPresenceRuntime` singleton.

    Thread-safe for read access (singleton is set once and never mutated).
    The first caller constructs the instance.
    """
    global _runtime_instance
    if _runtime_instance is None:
        _runtime_instance = DesktopPresenceRuntime()
    return _runtime_instance
