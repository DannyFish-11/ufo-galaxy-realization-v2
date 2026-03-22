"""
core.desktop_presence_runtime — Windows Desktop Runtime Shell
=============================================================

**Unified-Subject Architecture**
---------------------------------
``DesktopPresenceRuntime`` and ``OpenClawd`` are **not** two parallel subjects.
They are two layers of the *same* subject:

- ``DesktopPresenceRuntime`` — the **runtime shell** (the "clothing" / outer
  presence layer).  It is the Windows desktop presentation shell that wraps
  and hosts the subject on a Windows PC.  Think of it as the garment the
  subject wears when running on a desktop: it owns the session, drives the
  canonical tri-state lifecycle, owns native multimodal ingress, and exposes
  the subject as a desktop presence.
- ``OpenClawd``             — the **subject core** (cognition + execution
  nucleus).  It operates entirely *inside* the liminal phase; the runtime
  shell never bypasses it.

Together they form one subject::

    DesktopPresenceRuntime (outer shell / Windows clothing)
        └─ owns: session, tri-state lifecycle, native multimodal ingress
        └─ invokes OpenClawd inside liminal
              └─ OpenClawd: ingest → continuum → branch → manifest
                    ├─ local execution loop (Windows / System API)
                    └─ cross-device execution loop (gateway expansion)

**Canonical Tri-State Lifecycle** (carried by this shell)
----------------------------------------------------------
::

    silent  →  liminal  →  manifest  →  silent

- ``SILENT``   — subject at rest; native multimodal ingress continues.
- ``LIMINAL``  — request received; OpenClawd cognition/execution in progress.
- ``MANIFEST`` — subject actively producing output / controlling devices.
  Returns to ``SILENT`` after execution.

This is the *subject lifecycle*.  It is distinct from:
- The continuum posture (``tri_state_phase`` + ``runtime_domain``) — an
  internal state-protocol detail owned by OpenClawd.
- The UI shell states (``DORMANT`` / ``ISLAND`` / ``SIDESHEET`` /
  ``FULLAGENT``) — desktop clothing expansion modes that live in
  ``system_integration/`` and describe *how the shell is rendered*, not
  *what the subject is doing*.

**Responsibilities of this shell**
-----------------------------------
- Own the ``runtime_session_id`` that is the stable correlation ID for the
  entire request lifecycle across all downstream modules.
- Drive tri-state transitions; no adapter/launcher can skip the progression.
- Own native multimodal ingress (``MultimodalIngressBus``) — continuous
  host perception via ``PerceptionFrame``.  This is *distinct* from
  ``multimodal_context`` (request-bound payload fusion handled by
  ``MultimodalBus.ingest`` inside OpenClawd).
- Invoke ``OpenClawd.process()`` inside liminal with the
  ``runtime_session_id`` so the core can propagate it into every stage.
- Record observability hooks (log entries) at each state transition.
- Degrade gracefully: all non-essential modules (ingest bus, policy hints,
  cognitive field engine) are loaded lazily and fail silently.

**What this shell is NOT**
---------------------------
- Not a parallel subject alongside OpenClawd.
- Not a primary entrypoint in the sense of business logic — it is the *outer
  presence layer* that adapter surfaces (chat route, gateway, launcher scripts)
  call into.  Those adapter surfaces are themselves demoted from subject-core
  authority; they are launchers / protocol adapters only.

Usage::

    from core.desktop_presence_runtime import get_desktop_presence_runtime

    runtime = get_desktop_presence_runtime()
    result = await runtime.handle_request(
        message="打开微信",
        source="chat",       # observability tag only; does not change routing
        device_id="pc_01",
        session_id=None,
    )
    # result["runtime_session_id"] is propagated through every downstream layer.
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
    """Canonical subject lifecycle tri-state, carried by :class:`DesktopPresenceRuntime`.

    This is the **subject lifecycle** — describing the subject's existential
    state as a whole — not a UI state and not the internal continuum posture.

    - ``SILENT``   — subject at rest; native multimodal host ingress continues
                     in the background; no active cognition request.
    - ``LIMINAL``  — subject in transition; OpenClawd cognition and execution
                     branching are in progress inside this phase.
    - ``MANIFEST`` — subject actively expressing: producing output, controlling
                     devices, or expanding into a cross-device loop.
                     Transitions back to ``SILENT`` upon completion.

    Do **not** confuse with:
    - ``tri_state_phase`` in the OpenClawd continuum (internal state protocol).
    - ``DORMANT`` / ``ISLAND`` / ``SIDESHEET`` / ``FULLAGENT`` (desktop UI
      shell expansion modes; these describe the *clothing*, not the lifecycle).
    """

    SILENT = "silent"
    LIMINAL = "liminal"
    MANIFEST = "manifest"


# ---------------------------------------------------------------------------
# RuntimeSession — per-request lifecycle holder
# ---------------------------------------------------------------------------


class RuntimeSession:
    """Holds the lifecycle state of a single top-level request within the runtime shell.

    Each call to :meth:`DesktopPresenceRuntime.handle_request` creates one
    ``RuntimeSession``.  The session is ephemeral and is discarded once the
    request completes.

    The ``runtime_session_id`` is the **canonical correlation ID** for the
    entire request lifecycle — it is propagated into OpenClawd, the continuum
    orchestrator, the decision executor, the audit ledger, and every log entry
    so that the full subject cycle for one request can be reconstructed from
    logs.

    Attributes:
        runtime_session_id: Unique identifier for this runtime session.  Used
            as the stable correlation ID across all downstream log entries.
        trace_id: Alias for ``runtime_session_id``; kept for compatibility with
            existing trace propagation patterns.
        source: Observability tag indicating which adapter surface originated
            the request.  One of ``"chat"``, ``"e2e"``, or ``"openclawd"``.
            This is a **tag only** — it does not change routing logic; all
            adapter surfaces are demoted from subject-core authority and funnelled
            through this shell identically.
        tristate: Current tri-state phase of this session (subject lifecycle).
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
    """Windows Desktop Runtime Shell — the outer presence layer of the unified subject.

    **Role in the unified subject**

    ``DesktopPresenceRuntime`` is the **outer shell** (the "clothing") that
    presents the subject on a Windows desktop.  It wraps ``OpenClawd`` (the
    subject core) and is NOT a parallel subject.  Together they form one
    coherent entity:

    .. code-block:: text

        DesktopPresenceRuntime   ← outer shell / Windows clothing
            └─ TriState lifecycle owner (silent → liminal → manifest)
            └─ native multimodal ingress owner (MultimodalIngressBus)
            └─ runtime_session_id generator & propagator
            └─ invokes OpenClawd during the LIMINAL phase
                  └─ OpenClawd (subject core): ingest → continuum → branch
                        ├─ local execution loop (Windows / System API)
                        └─ cross-device execution loop (gateway)

    **Canonical Lifecycle**

    This class is the *sole* driver of the tri-state subject lifecycle::

        SILENT → LIMINAL → MANIFEST → SILENT

    Every adapter surface (chat route, gateway, launcher script) must call
    :meth:`handle_request` to enter this lifecycle.  No adapter surface has
    subject-core authority; they are protocol adapters / launchers only.

    **Three distinct state systems — do not conflate**

    1. **Tri-state lifecycle** (this class) — ``silent`` / ``liminal`` /
       ``manifest``.  The subject's existential state.
    2. **Continuum posture** (``OpenClawd`` / ``ContinuumOrchestrator``) —
       ``tri_state_phase`` + ``runtime_domain``.  Internal state protocol
       inside the core.
    3. **UI shell states** (``system_integration/``) — ``DORMANT`` /
       ``ISLAND`` / ``SIDESHEET`` / ``FULLAGENT``.  Desktop clothing
       expansion modes that describe *how the shell is rendered*.

    **Native multimodal ingress vs request-bound multimodal context**

    - ``MultimodalIngressBus`` (started by :meth:`_try_start_ingest_bus` in
      ``__init__``) — *continuous host perception*: audio / video / system
      signals fed into ``PerceptionFrame`` objects.  Owned by this shell.
    - ``multimodal_context`` parameter on :meth:`handle_request` — *request-
      bound* multimodal payload; fused inside ``OpenClawd`` via
      ``MultimodalBus.ingest``.  A per-request attachment, not a stream.

    Instantiation is inexpensive; all heavy modules are loaded lazily.
    Use :func:`get_desktop_presence_runtime` to obtain the singleton.
    """

    def __init__(self) -> None:
        # Active sessions keyed by runtime_session_id.
        # Sessions are removed upon completion to avoid unbounded growth.
        self._active_sessions: Dict[str, RuntimeSession] = {}
        logger.info("DesktopPresenceRuntime initialised (Windows desktop runtime shell)")

        # Shell responsibility: own and start the native multimodal ingress bus.
        # This provides *continuous host perception* (PerceptionFrame via
        # MultimodalIngressBus) — distinct from request-bound multimodal_context.
        # Degrades silently when enable_multimodal_ingest=false or audio/video
        # dependencies are absent; text-only deployments are unaffected.
        # See _try_start_ingest_bus() for the full startup logic.
        self._try_start_ingest_bus()

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
        entry_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Drive the full subject lifecycle for one top-level request.

        This is the **single** method that all adapter surfaces (chat route,
        OpenClawd direct callers, E2E orchestrator) must call.  Adapter
        surfaces have no subject-core authority; they are launchers / protocol
        adapters that hand off to this shell.

        **Shell → Liminal → Core → Manifest → Silent**

        1. Creates a :class:`RuntimeSession` with a unique ``runtime_session_id``
           that will be propagated through OpenClawd, the continuum orchestrator,
           the decision executor, the audit ledger, and every log entry.
        2. ``SILENT → LIMINAL``: request received; subject enters the liminal
           phase.  OpenClawd cognition begins here.
        3. ``LIMINAL → MANIFEST``: OpenClawd has produced an intent and
           execution path; the subject enters manifest.
        4. Delegates execution to the appropriate internal handler; ``OpenClawd``
           is invoked for all ``source`` values (``"chat"``, ``"openclawd"``,
           ``"e2e"`` uses the E2E path which may also call OpenClawd internally).
        5. ``MANIFEST → SILENT``: execution complete; subject returns to rest.
        6. Returns the result augmented with ``runtime_session_id``, ``tristate``,
           and ``entrypoint_source`` observability fields.

        Args:
            message: Natural-language request text.
            source: **Observability tag only** — indicates which adapter surface
                originated the request (``"chat"``, ``"e2e"``, ``"openclawd"``).
                This does NOT confer subject-core authority to the caller; all
                sources enter the same shell → liminal → manifest → silent path.
            device_id: Optional source-device identifier.
            session_id: Optional external session identifier.  When ``None``
                a new session ID is derived from ``runtime_session_id``.
            user_id: User identifier for cross-device session correlation.
            context: Conversation history list.
            required_capabilities: Scheduler capability hints.
            multimodal_context: Request-bound multi-modal payload bundle.
                Fused inside OpenClawd via ``MultimodalBus.ingest``.  Distinct
                from the continuous ``MultimodalIngressBus`` host perception stream.
            use_constellation: When *True* (default) prefer
                ConstellationRuntime for ``source="e2e"`` requests.
            entry_mode: Pre-resolved execution mode (``"local"`` |
                ``"cross_device"`` | ``"hybrid"``).  Forwarded to OpenClawd
                without modification so the correct liminal branch is taken.
            **kwargs: Additional keyword arguments forwarded to the underlying
                handler.

        Returns:
            A dict with at minimum::

                {
                    "success": bool,
                    "response": str,
                    "runtime_session_id": str,  # correlation ID for all logs
                    "trace_id": str,
                    "tristate": str,            # final phase ("silent")
                    "entrypoint_source": str,   # observability tag
                }
        """
        rsession = self._create_session(source)

        # Block-3: _cognitive_snap will hold the StateInterpreter result and is attached
        # to the response as an additive observability field.  Declared here (before the
        # try/finally block) so it's accessible in both the success and error paths.
        _cognitive_snap: Optional[Dict[str, Any]] = None

        # Notify the continuous cognitive field engine that a request has arrived.
        # Best-effort — failures must never block the request path.
        try:
            from core.cognitive.cognitive_field_engine import get_cognitive_field_engine
            get_cognitive_field_engine().notify_request(
                trace_id=rsession.runtime_session_id,
            )
        except Exception as _cfe_err:
            logger.debug("cognitive_field_engine.notify_request failed (non-fatal): %s", _cfe_err)

        # SILENT → LIMINAL: subject enters liminal phase; OpenClawd cognition begins
        rsession.advance(TriState.LIMINAL)
        self._log_request_start(rsession, message, session_id, device_id)

        # PR-12: Lightweight policy observation (non-blocking guardrail hint)
        # Resolves the current execution policy from tri-state/cognitive signals
        # and attaches it to the result for observability.  Never blocks the
        # request path.
        _policy_hint: Optional[Dict[str, Any]] = None
        try:
            from core.execution_policy import resolve_policy, get_policy_hints
            _policy_hint = get_policy_hints(
                resolve_policy(phase=rsession.tristate.value)
            )
        except Exception as _ph_err:
            logger.debug("policy hint resolution failed (non-fatal): %s", _ph_err)

        try:
            # LIMINAL → MANIFEST: OpenClawd has branched; subject enters manifest
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
                entry_mode=entry_mode,
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
            # MANIFEST → SILENT: subject returns to rest (even on error)
            rsession.advance(TriState.SILENT)
            self._log_request_end(rsession)
            self._active_sessions.pop(rsession.runtime_session_id, None)

            # Block-3: Notify decay controller that execution completed so the
            # cognitive field begins its manifest→liminal→passive reabsorption.
            try:
                from core.cognitive.cognitive_field_engine import get_cognitive_field_engine
                get_cognitive_field_engine().notify_task_complete(
                    trace_id=rsession.runtime_session_id,
                )
            except Exception as _decay_err:
                logger.debug("cognitive decay trigger failed (non-fatal): %s", _decay_err)

            # Block-3: Derive the interpreted tri-state from the continuous field.
            # This is additive — the existing ``rsession.tristate`` is unchanged.
            try:
                from core.cognitive.state_interpreter import get_state_interpreter
                _interp = get_state_interpreter().interpret()
                _cognitive_snap = _interp.to_dict()
            except Exception as _interp_err:
                logger.debug("state_interpreter.interpret failed (non-fatal): %s", _interp_err)

        # Augment result with runtime observability fields
        result.setdefault("runtime_session_id", rsession.runtime_session_id)
        result.setdefault("trace_id", rsession.runtime_session_id)
        result["tristate"] = rsession.tristate.value
        result["entrypoint_source"] = source
        # Block-3: attach the continuous cognitive state snapshot (additive, optional).
        if _cognitive_snap is not None:
            result["cognitive_state"] = _cognitive_snap
        # PR-12: attach policy hint (additive, non-blocking).
        if _policy_hint is not None:
            result["policy_hint"] = _policy_hint
        # PR-9: stamp runtime shell authority metadata (additive, non-breaking).
        result.setdefault("authority_metadata", {
            "layer_role": "runtime_shell_authority",
            "canonical_module": "core.desktop_presence_runtime",
            "canonical_class": "DesktopPresenceRuntime",
            "pr_introduced": "PR-1",
        })
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
        entry_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Route to the correct underlying handler.

        All handlers receive ``runtime_session_id`` so they can propagate it
        into the OpenClawd core, continuum orchestrator, audit ledger, and
        task logger.

        The ``source`` parameter is an observability tag only.  It does not
        confer subject-core authority.  All adapter surfaces (chat, e2e, direct
        openclawd callers) are funnelled through this shell equivalently; none
        can bypass the tri-state lifecycle.

        Unknown sources fall back to OpenClawd with a warning so requests are
        never silently dropped.
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
                entry_mode=entry_mode,
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
            entry_mode=entry_mode,
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
        entry_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Invoke the subject core (OpenClawd) inside the liminal phase.

        This is the primary shell→core handoff.  The ``runtime_session_id``
        is forwarded so OpenClawd can propagate it into every stage:
        ingest → continuum → branch (local / cross-device) → manifest.
        """
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
            entry_mode=entry_mode,
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

    def _try_start_ingest_bus(self) -> None:
        """Start the native multimodal host perception bus (shell ownership).

        The ``MultimodalIngressBus`` provides *continuous host perception* —
        a ``PerceptionFrame`` stream of audio / video / system signals from
        the Windows desktop environment.  This is a runtime-shell
        responsibility: the shell owns the local sensory layer of the subject.

        This is distinct from ``multimodal_context``, which is a per-request
        payload bundle fused inside OpenClawd via ``MultimodalBus.ingest``.

        Gracefully degrades: when ``enable_multimodal_ingest`` is ``False``
        (default) or when audio/video dependencies are absent, no exception
        is raised and no pipeline is started.
        """
        try:
            from core.multimodal.ingest_runtime import start_ingest_bus
            started = start_ingest_bus(runtime_session_id=None)
            if started:
                logger.info("DesktopPresenceRuntime: multimodal ingest bus started")
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime: ingest bus startup skipped (%s)", _err
            )

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
