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
                    ├─ LOCAL EXECUTION CHAIN   (core/local_execution_chain.py)
                    │     OpenClawd → AgentKernel → CommandRouter[LOCAL] →
                    │     local executor → LocalExecutionResult → feedback
                    └─ CROSS-DEVICE EXECUTION CHAIN  (core/cross_device_execution_chain.py)
                          OpenClawd → CommandRouter[REMOTE] → TaskEnvelope →
                          gateway → worker → ResultEnvelope → feedback

Both chains are **first-class canonical runtime chains** with documented step
ordering, authority ownership, and projection-facing summary support.  See
``docs/LOCAL_EXECUTION_CHAIN.md`` and ``docs/CROSS_DEVICE_EXECUTION_CHAIN.md``.

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

from core.desktop_presence_system import (
    DesktopPresenceStateMachine,
    build_desktop_presence_system_view,
)
from core.multimodal.perception_source_registry import STREAM_CAPABLE_SOURCE_TYPES

logger = logging.getLogger("Galaxy.Runtime")
_STREAMING_BACKBONE_CONTRACT: Optional[Dict[str, Any]] = None

DESKTOP_PRESENCE_RUNTIME_ENTRYPOINT_ROLE: str = "stage_entry"
"""Entrypoint role contract (PR-01): runtime shell stage entry, not main startup entry."""


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
                TriState.SILENT: StateEventType.PHASE_SILENT,
                TriState.LIMINAL: StateEventType.PHASE_LIMINAL,
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
                        ├─ LOCAL EXECUTION CHAIN   (core/local_execution_chain.py)
                        │     → AgentKernel → CommandRouter[LOCAL] → executor
                        └─ CROSS-DEVICE EXECUTION CHAIN  (core/cross_device_execution_chain.py)
                              → CommandRouter[REMOTE] → gateway → worker

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
        self._presence_state_machine = DesktopPresenceStateMachine()
        self._latest_presence_runtime_hint: Dict[str, Any] = {
            "presence_mode": self._presence_state_machine.mode.value,
            "previous_presence_mode": self._presence_state_machine.mode.value,
            "presence_mode_changed": False,
            "presence_transition_reason": "mode_stable",
            "presence_transition": None,
        }
        logger.info("DesktopPresenceRuntime initialised (Windows desktop runtime shell)")

        # PR-17: Shell responsibility — own and initialise the perception source
        # registry.  The registry tracks all multimodal sources (microphone,
        # local camera, WebRTC sessions, external streams) and governs primary
        # source selection, health, and diagnostics.
        from core.multimodal.perception_source_registry import PerceptionSourceRegistry

        self._source_registry: PerceptionSourceRegistry = PerceptionSourceRegistry()
        self._webrtc_session_manager: Optional[Any] = None

        # Shell responsibility: own and start the native multimodal ingress bus.
        # This provides *continuous host perception* (PerceptionFrame via
        # MultimodalIngressBus) — distinct from request-bound multimodal_context.
        # Degrades silently when enable_multimodal_ingest=false or audio/video
        # dependencies are absent; text-only deployments are unaffected.
        # See _try_start_ingest_bus() for the full startup logic.
        self._try_start_ingest_bus()
        self._try_init_webrtc_session_manager()

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
                originated the request (``"chat"``, ``"e2e"``, ``"openclawd"``,
                ``"android_vision"``, ``"vision_sampler"``).
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
        from core.session_execution_lane import get_session_execution_lane_manager
        from core.session_identity import build_canonical_session_identity

        session_identity = build_canonical_session_identity(
            session_id=session_id or "",
            user_id=user_id or "",
            device_id=device_id or "",
            runtime_session_id=rsession.runtime_session_id,
            payload=kwargs,
        )
        conversation_session_id = session_identity.conversation_session_id
        control_session_id = session_identity.control_session_id
        runtime_attachment_session_id = (
            session_identity.runtime_attachment_session_id
        )
        desktop_native_ingress_backbone: Optional[Dict[str, Any]] = None
        try:
            from core.desktop_native_multimodal_ingress_contract import (
                build_desktop_native_ingress_backbone,
            )

            desktop_native_ingress_backbone = build_desktop_native_ingress_backbone(
                message=message,
                source=source,
                multimodal_context=multimodal_context,
                context=context,
                kwargs=kwargs,
                conversation_session_id=conversation_session_id,
                control_session_id=control_session_id,
                runtime_attachment_session_id=runtime_attachment_session_id,
            )
        except Exception as _ing_err:
            logger.debug(
                "desktop-native ingress backbone build failed (non-fatal): %s",
                _ing_err,
            )

        # Block-3: _cognitive_snap will hold the StateInterpreter result and is attached
        # to the response as an additive observability field.  Declared here (before the
        # try/finally block) so it's accessible in both the success and error paths.
        _cognitive_snap: Optional[Dict[str, Any]] = None

        # PR-18: _cognitive_exec_hint holds the cognitive execution-policy hint derived
        # from live cognitive signals.  Declared before the try/finally block so it is
        # accessible in both success and error paths.  The hint is advisory only; the
        # runtime shell never enforces it as a binding directive.
        _cognitive_exec_hint: Optional[Dict[str, Any]] = None
        _dispatch_presence_runtime_hint: Dict[str, Any] = self._current_presence_runtime_hint()

        # Notify the continuous cognitive field engine that a request has arrived.
        # Best-effort — failures must never block the request path.
        try:
            from core.cognitive.cognitive_field_engine import get_cognitive_field_engine

            get_cognitive_field_engine().notify_request(
                trace_id=rsession.runtime_session_id,
            )
        except Exception as _cfe_err:
            logger.debug("cognitive_field_engine.notify_request failed (non-fatal): %s", _cfe_err)

        # PR-18: Derive the cognitive execution-policy hint from live signals.
        # This is done BEFORE dispatch so the hint can be forwarded to OpenClawd
        # as an advisory signal for execution-path and delegation biasing.
        # Best-effort — failures must never block the request path.
        _cog_hint_obj = None
        try:
            from core.cognitive.cognitive_execution_policy import (
                derive_cognitive_execution_hint,
                build_cognitive_hint_metadata,
            )

            _cog_hint_obj = derive_cognitive_execution_hint(
                trace_id=rsession.runtime_session_id,
            )
            _cognitive_exec_hint = build_cognitive_hint_metadata(
                _cog_hint_obj,
                trace_id=rsession.runtime_session_id,
            )
            logger.debug(
                "PR-18 cognitive exec hint | region=%s exec_pref=%s plan=%s budget=%.3f trace_id=%s",
                _cog_hint_obj.cognitive_region,
                _cog_hint_obj.execution_path_preference,
                _cog_hint_obj.planning_intensity,
                _cog_hint_obj.activation_budget,
                rsession.runtime_session_id,
            )
        except Exception as _ceh_err:
            logger.debug("cognitive_execution_hint derivation failed (non-fatal): %s", _ceh_err)

        # SILENT → LIMINAL: subject enters liminal phase; OpenClawd cognition begins
        rsession.advance(TriState.LIMINAL)
        stream_sensing_active = self._has_active_stream_source()
        self._update_presence_mode(
            tri_state=rsession.tristate.value,
            task_active=True,
            sensing_active=bool(multimodal_context) or stream_sensing_active,
            execution_active=False,
            user_interaction=source in {"chat", "operator"},
        )
        self._log_request_start(
            rsession,
            message,
            conversation_session_id,
            device_id,
        )

        # PR-12: Lightweight policy observation (non-blocking guardrail hint)
        # Resolves the current execution policy from tri-state/cognitive signals
        # and attaches it to the result for observability.  Never blocks the
        # request path.
        _policy_hint: Optional[Dict[str, Any]] = None
        try:
            from core.execution_policy import resolve_policy, get_policy_hints

            _policy_hint = get_policy_hints(resolve_policy(phase=rsession.tristate.value))
        except Exception as _ph_err:
            logger.debug("policy hint resolution failed (non-fatal): %s", _ph_err)

        lane_snapshot = None
        try:
            lane_manager = get_session_execution_lane_manager()
            async with lane_manager.acquire(
                conversation_session_id,
                control_session_id=control_session_id,
            ) as lane:
                # LIMINAL → MANIFEST: OpenClawd has branched; subject enters manifest
                rsession.advance(TriState.MANIFEST)
                self._update_presence_mode(
                    tri_state=rsession.tristate.value,
                    task_active=True,
                    sensing_active=bool(multimodal_context) or stream_sensing_active,
                    execution_active=True,
                    user_interaction=source in {"chat", "operator"},
                )
                _dispatch_presence_runtime_hint = self._current_presence_runtime_hint()
                _presence_mode = _dispatch_presence_runtime_hint["presence_mode"]
                _stream_runtime_status = (
                    self.realtime_streaming_backbone_summary().get("runtime_status") or {}
                )

                result = await self._dispatch(
                    rsession=rsession,
                    message=message,
                    source=source,
                    device_id=device_id,
                    session_id=conversation_session_id,
                    user_id=user_id,
                    context=context,
                    required_capabilities=required_capabilities,
                    multimodal_context=multimodal_context,
                    use_constellation=use_constellation,
                    entry_mode=entry_mode,
                    control_session_id=control_session_id,
                    runtime_attachment_session_id=runtime_attachment_session_id,
                    session_identity=session_identity,
                    # PR-18: forward the cognitive execution hint so OpenClawd can
                    # use it as an advisory signal for execution-path / delegation
                    # biasing.  Never mandatory; OpenClawd retains final authority.
                    cognitive_execution_hint=_cog_hint_obj,
                    desktop_native_ingress_backbone=desktop_native_ingress_backbone,
                    presence_mode=_presence_mode,
                    presence_runtime_hint=_dispatch_presence_runtime_hint,
                    stream_runtime_status=_stream_runtime_status,
                    is_operator_request=source == "operator",
                    **kwargs,
                )
                lane_snapshot = lane.to_dict()

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
            self._update_presence_mode(
                tri_state=rsession.tristate.value,
                task_active=False,
                sensing_active=self._has_active_stream_source(),
                execution_active=False,
                user_interaction=source in {"chat", "operator"},
                result_committed=True,
            )
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
        result["conversation_session_id"] = conversation_session_id
        result["control_session_id"] = control_session_id
        if runtime_attachment_session_id:
            result["runtime_attachment_session_id"] = runtime_attachment_session_id
        metadata = result.setdefault("metadata", {})
        metadata.setdefault("session_id", conversation_session_id)
        metadata["conversation_session_id"] = conversation_session_id
        metadata["control_session_id"] = control_session_id
        if desktop_native_ingress_backbone is not None:
            metadata["desktop_native_ingress_backbone"] = desktop_native_ingress_backbone
        metadata["presence_mode"] = _dispatch_presence_runtime_hint["presence_mode"]
        metadata["presence_runtime_hint"] = dict(_dispatch_presence_runtime_hint)
        if runtime_attachment_session_id:
            metadata["runtime_attachment_session_id"] = runtime_attachment_session_id
        if lane_snapshot is not None:
            metadata["session_execution_lane"] = lane_snapshot
        metadata.setdefault(
            "problem_execution_trace",
            {
                "trace_id": result.get("trace_id") or rsession.runtime_session_id,
                "runtime_session_id": result.get("runtime_session_id") or rsession.runtime_session_id,
                "request_id": metadata.get("request_id") or "",
                "source": source,
            },
        )
        if "execution_path_decision_basis" not in metadata and isinstance(
            result.get("execution_result"),
            dict,
        ):
            _exec_basis = result.get("execution_result", {}).get("execution_path_decision_basis")
            if isinstance(_exec_basis, dict):
                metadata["execution_path_decision_basis"] = _exec_basis
        # PR-2: stamp additive NL execution spine snapshot so chat-path and
        # task/delegation path share one problem→intent→route model.
        try:
            from core.nl_execution_spine import build_problem_execution_spine

            metadata["problem_execution_spine"] = build_problem_execution_spine(
                message=message,
                source=source,
                entry_mode=entry_mode,
                metadata=metadata,
                execution_result=result.get("execution_result"),
                intent=result.get("intent"),
            )
        except Exception as _spine_err:
            logger.warning(
                "problem_execution_spine build failed (non-fatal): source=%s entry_mode=%s trace_id=%s err=%s",
                source,
                entry_mode,
                rsession.runtime_session_id,
                _spine_err,
            )
        # Block-3: attach the continuous cognitive state snapshot (additive, optional).
        if _cognitive_snap is not None:
            result["cognitive_state"] = _cognitive_snap
        # PR-18: attach the cognitive execution hint (additive, advisory only).
        # This makes the hint visible in diagnostics / projection surfaces so
        # operators can see when cognitive-state wiring influenced execution-path
        # decisions.  The hint is never a mandatory enforcement directive.
        if _cognitive_exec_hint is not None:
            result["cognitive_execution_hint"] = _cognitive_exec_hint
        # PR-12: attach policy hint (additive, non-blocking).
        if _policy_hint is not None:
            result["policy_hint"] = _policy_hint
        # PR-9: stamp runtime shell authority metadata (additive, non-breaking).
        result.setdefault(
            "authority_metadata",
            {
                "layer_role": "runtime_shell_authority",
                "canonical_module": "core.desktop_presence_runtime",
                "canonical_class": "DesktopPresenceRuntime",
                "pr_introduced": "PR-1",
            },
        )
        # PR-10: stamp architecture diagnostics layer identifier (additive).
        result.setdefault("arch_layer_id", "runtime_shell")
        # PR-14: stamp additive introspection hints on runtime-shell result.
        result.setdefault(
            "introspection_snapshot",
            {
                "authority_role": "runtime_shell_authority",
                "entry_source": source,
                "trace_id": result.get("trace_id") or result.get("runtime_session_id"),
            },
        )
        # PR-22: assemble the desktop status projection and attach as an
        # additive, non-breaking field.  The shell combines the control-core's
        # unified_control_plan with its own source registry snapshot.
        _dsp = self.build_desktop_status_projection(
            result=result,
            tristate=rsession.tristate.value,
            runtime_session_id=rsession.runtime_session_id,
        )
        if _dsp is not None:
            result["desktop_status_projection"] = _dsp
        metadata["realtime_streaming_backbone"] = self.realtime_streaming_backbone_summary()
        # PR-5-V2: stamp ingress carrier context (additive, non-breaking).
        # Provides a single normalized carrier descriptor so all operator
        # surfaces and tests can identify which carrier path originated the
        # invocation without inspecting raw ``entrypoint_source`` strings.
        # PR-6: add invocation_id (= runtime_session_id) so the ingress stamp
        # ties each invocation back to its unique correlation ID, enabling
        # stable continuity tracing across presence→task→delegation chains.
        # Android NL chain: carrier identifies the source/carrier device; semantic_authority
        # always names V2 as the LLM semantic authority regardless of which carrier sent the
        # NL request (resolves DUAL_REPO_REAL_CHAIN_BASELINE_2026 P2 — source/carrier vs
        # semantic-authority split must be machine-verifiable).
        _android_carriers = {"android_vision", "android_goal_execution"}
        try:
            from core.android_nl_semantic_chain_contract import (
                ANDROID_PARTICIPATION_UNDER_V2_AUTHORITY_BOUNDARY as _android_authority_boundary,
                CENTER_AUTHORITY_BOUNDARY as _center_authority_boundary,
                V2_AUTHORITY as _v2_authority,
                V2_SEMANTIC_AUTHORITY as _v2_semantic_authority,
            )
        except Exception:
            _v2_semantic_authority = "v2_openclawd"
            _v2_authority = "v2_authority"
            _android_authority_boundary = "android_participation_under_v2_authority"
            _center_authority_boundary = "center_authority"
        _nl_path_type = (
            "android_cross_device_nl" if source == "android_goal_execution"
            else "android_vision_nl" if source == "android_vision"
            else "desktop_direct_nl"
        )
        _ingress_carrier_context: Dict[str, Any] = {
            "carrier": source,
            "authority_chain": "DesktopPresenceRuntime.handle_request",
            "session_id": conversation_session_id,
            "user_id": user_id or "default",
            "invocation_id": rsession.runtime_session_id,
            "control_session_id": control_session_id,
            "origin": "android" if source in _android_carriers else "center",
            "authority": _v2_authority,
            "authority_boundary": _android_authority_boundary
            if source in _android_carriers
            else _center_authority_boundary,
            # semantic_authority is always V2 — the LLM semantic reasoning chain
            # (OpenClawd + AgentKernel + MultiLLMRouter) lives here regardless of
            # which device or adapter surface originated the NL request.
            # Android-side GoalNormalizer = structural normalization only (not LLM).
            # Android-side LocalPlannerService = local task decomposition only (not LLM).
            "semantic_authority": _v2_semantic_authority,
            # nl_path_type distinguishes Android carriers from desktop-direct paths.
            "nl_path_type": _nl_path_type,
            "is_android_carrier": source in _android_carriers,
            "ingress_lineage": "canonical_ingress",
            "routing_lineage": "desktop_presence_runtime",
        }
        if source == "android_vision":
            try:
                from core.android_perception_ingress_contract import (
                    build_android_perception_ingress_context,
                )

                _ingress_carrier_context.update(
                    build_android_perception_ingress_context(
                        source=source,
                        multimodal_context=multimodal_context,
                    )
                )
            except Exception as _apc_err:
                logger.debug(
                    "android perception ingress context build failed (non-fatal): %s",
                    _apc_err,
                )
        result.setdefault("ingress_carrier_context", _ingress_carrier_context)

        # PR-UAS: Build the unified action lifecycle surface and attach it to
        # the canonical default result payload.  This is the first point in
        # the default handle_request() output path where:
        #   - Android-side result is exposed as a first-class object
        #   - blocker / confirmation / closure state is available in a unified
        #     canonical structure
        # The surface is built from existing execution_result / metadata fields
        # and does not require additional round-trips.
        try:
            from core.unified_action_lifecycle_surface import (
                ActionOrigin,
                UnifiedActionLifecycleSurface,
                build_from_dispatch,
            )

            _exec_result = result.get("execution_result") or {}
            _android_result_payload: Optional[Dict[str, Any]] = None
            _android_result_authority = ""
            _action_phase = "dispatched"
            _closure_state_str = "open"
            _blocker: Optional[Dict[str, Any]] = None
            _blocker_reason = ""
            _blocker_kind = ""
            _confirmation_needed = False

            # Detect android carrier — result may include android execution output
            if source in _android_carriers:
                _origin = ActionOrigin.android_device
                # If execution_result carries an android result or task_result,
                # surface it as a first-class android_result.
                if isinstance(_exec_result, dict) and _exec_result:
                    _android_result_payload = {
                        "source": source,
                        "execution_result": _exec_result,
                        "session_id": conversation_session_id,
                        "runtime_session_id": rsession.runtime_session_id,
                    }
                    _android_result_authority = "android_device"
                    _action_phase = "result_received"
                    _closure_state_str = "closed"
            else:
                _origin = ActionOrigin.v2_center

            # Detect blocker: look for explicit blocker or routing refusal
            if isinstance(_exec_result, dict):
                _raw_blocker = _exec_result.get("blocker") or _exec_result.get("blocked_reason")
                if _raw_blocker:
                    _blocker = {"reason": str(_raw_blocker)} if not isinstance(_raw_blocker, dict) else _raw_blocker
                    _blocker_reason = str(_raw_blocker) if not isinstance(_raw_blocker, dict) else _raw_blocker.get("reason", "")
                    _blocker_kind = "execution_blocker"
                    _action_phase = "blocked"
                _confirmation_needed = bool(
                    _exec_result.get("confirmation_needed")
                    or _exec_result.get("requires_confirmation")
                )
                if _confirmation_needed:
                    _action_phase = "confirmation_needed"

            from core.unified_action_lifecycle_surface import ActionLifecyclePhase, ClosureState

            try:
                _phase_enum = ActionLifecyclePhase(_action_phase)
            except ValueError:
                _phase_enum = ActionLifecyclePhase.dispatched

            try:
                _closure_enum = ClosureState(_closure_state_str)
            except ValueError:
                _closure_enum = ClosureState.open

            _ual_surface = UnifiedActionLifecycleSurface(
                action_id=rsession.runtime_session_id,
                session_id=conversation_session_id,
                task_id=str(metadata.get("request_id") or ""),
                device_id=device_id or "",
                phase=_phase_enum,
                origin=_origin,
                android_result=_android_result_payload,
                android_result_authority=_android_result_authority,
                blocker=_blocker,
                blocker_reason=_blocker_reason,
                blocker_kind=_blocker_kind,
                confirmation_needed=_confirmation_needed,
                closure_state=_closure_enum,
                closure_reason="execution_complete" if _closure_state_str == "closed" else "",
            )
            result["action_lifecycle_surface"] = _ual_surface.to_dict()
        except Exception as _ual_err:
            logger.debug(
                "action_lifecycle_surface build failed (non-fatal): source=%s trace_id=%s err=%s",
                source,
                rsession.runtime_session_id,
                _ual_err,
            )

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
        presence_mode: Optional[str] = None,
        presence_runtime_hint: Optional[Dict[str, Any]] = None,
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
        if source in ("chat", "openclawd", "android_vision", "vision_sampler", "operator",
                      "android_goal_execution"):
            return await self._handle_via_openclawd(
                rsession=rsession,
                message=message,
                device_id=device_id,
                session_id=session_id,
                context=context,
                required_capabilities=required_capabilities,
                multimodal_context=multimodal_context,
                entry_mode=entry_mode,
                presence_mode=presence_mode,
                presence_runtime_hint=presence_runtime_hint,
                **kwargs,
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
                control_session_id=kwargs.get("control_session_id", ""),
                runtime_attachment_session_id=kwargs.get("runtime_attachment_session_id", ""),
            )

        # Unknown source — log a warning and fall back to OpenClawd so requests
        # are never silently dropped.
        logger.warning(
            "DesktopPresenceRuntime: unknown source=%r — falling back to OpenClawd handler. " "runtime_session_id=%s",
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
            presence_mode=presence_mode,
            presence_runtime_hint=presence_runtime_hint,
            **kwargs,
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
        presence_mode: Optional[str] = None,
        presence_runtime_hint: Optional[Dict[str, Any]] = None,
        control_session_id: str = "",
        runtime_attachment_session_id: str = "",
        session_identity: Optional[Any] = None,
        desktop_native_ingress_backbone: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Invoke the subject core (OpenClawd) inside the liminal phase.

        This is the primary shell→core handoff.  The ``runtime_session_id``
        is forwarded so OpenClawd can propagate it into every stage:
        ingest → continuum → branch (local / cross-device) → manifest.
        """
        from core.openclawd import get_openclawd

        # PR-18: extract the cognitive execution hint from kwargs so it can be
        # passed to OpenClawd as a named parameter.  The hint is advisory only;
        # OpenClawd retains full execution-path authority.
        cognitive_execution_hint = kwargs.pop("cognitive_execution_hint", None)

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
            control_session_id=control_session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            session_identity=session_identity,
            desktop_native_ingress_backbone=desktop_native_ingress_backbone,
            presence_mode=presence_mode,
            presence_runtime_hint=presence_runtime_hint,
            cognitive_execution_hint=cognitive_execution_hint,
            **kwargs,
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
        control_session_id: str = "",
        runtime_attachment_session_id: str = "",
    ) -> Dict[str, Any]:
        """Delegate to the E2E pipeline with runtime_session_id propagation."""
        # Inject runtime_session_id into the context so downstream modules can
        # pick it up via the context list.
        augmented_context: List[Dict] = list(context or [])
        augmented_context.append(
            {
                "runtime_session_id": rsession.runtime_session_id,
                "trace_id": rsession.runtime_session_id,
                "control_session_id": control_session_id,
                "runtime_attachment_session_id": runtime_attachment_session_id,
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
                    "control_session_id": control_session_id,
                    "runtime_attachment_session_id": runtime_attachment_session_id,
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
                logger.warning("ConstellationRuntime failed in E2E handler, falling back to pipeline: %s", exc)

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
            logger.debug("DesktopPresenceRuntime: ingest bus startup skipped (%s)", _err)

    def _try_init_webrtc_session_manager(self) -> None:
        """Initialize WebRTC session manager when the runtime switch is enabled."""
        try:
            from core.unified_config import config as _cfg

            if not bool(_cfg.get("enable_webrtc_session_manager", False)):
                return

            from core.multimodal.webrtc_session_manager import (
                WebRTCManagerConfig,
                WebRTCSessionManager,
            )

            self._webrtc_session_manager = WebRTCSessionManager(
                WebRTCManagerConfig(runtime_session_id="runtime_shell")
            )
            logger.info("DesktopPresenceRuntime: WebRTC session manager initialized")
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime: WebRTC session manager init skipped (%s)",
                _err,
            )

    def snapshot_continuous_perception(self) -> Optional[Dict[str, Any]]:
        """PR-16: Return the latest continuous host perception snapshot.

        This is a **runtime shell responsibility** — the shell owns the
        ``MultimodalIngressBus`` and provides continuous host perception
        snapshots to the rest of the system.

        Returns the serialized :class:`~core.multimodal.perception_frame.PerceptionFrame`
        from the running singleton ingress bus, or ``None`` when the bus is
        disabled or unavailable (text-only / no-ingress deployments).

        The returned dict is safe to log and use for diagnostics.  No base64
        payloads are included.  This method never raises.
        """
        try:
            from core.multimodal.ingest_runtime import get_ingest_bus as _get_ib

            _bus = _get_ib()
            if _bus is not None:
                frame = _bus.build_frame()
                return frame.to_dict()
            return None
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.snapshot_continuous_perception failed (non-fatal): %s",
                _err,
            )
            return None

    @property
    def stream_runtime_ready(self) -> bool:
        """Return ``True`` when the WebRTC session manager has been initialised.

        This is the first-class signal that the realtime streaming backbone has
        an active stream session holder in the runtime.  Downstream control
        points (e.g. route-decision, perception assembly) read this via the
        ``stream_runtime_ready`` key in the realtime_streaming_backbone_summary.
        """
        return self._webrtc_session_manager is not None

    @property
    def source_registry(self):
        """PR-17: Return the shell-owned :class:`~core.multimodal.perception_source_registry.PerceptionSourceRegistry`.

        The registry tracks all multimodal perception sources (microphone,
        local camera, WebRTC sessions, external/remote streams) and governs
        primary source selection, health, and diagnostics.

        This is a **runtime shell responsibility** — the registry is initialised
        in ``__init__`` and must not be moved into OpenClawd.
        """
        return self._source_registry

    def snapshot_source_registry(self) -> Dict[str, Any]:
        """PR-17: Return a diagnostics-safe, JSON-serialisable snapshot of the source registry.

        The snapshot includes all registered source records with their health,
        quality, latency, and primary-selection status.  Safe to log and export
        for diagnostics and future status-board projection.  Never raises.
        """
        try:
            return self._source_registry.snapshot()
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.snapshot_source_registry failed (non-fatal): %s",
                _err,
            )
            return {"snapshot_at": time.time(), "error": str(_err), "sources": []}

    def run_source_recovery_cycle(self) -> Dict[str, Any]:
        """PR-31: Run a source recovery cycle on the shell-owned source registry.

        Delegates to :class:`~core.multimodal.source_recovery_policy.SourceRecoveryPolicy`
        to evict stale sources and re-elect primary audio/video sources when the
        current primaries have failed or degraded.

        The cycle respects flap-smoothing hysteresis: transient degradations within
        a short window do not cause chaotic primary switching.

        Returns a summary dict with cycle results (``evicted``, ``audio_reelected``,
        ``video_reelected``, ``flap_smoothed_ids``).  Never raises.
        """
        try:
            from core.multimodal.source_recovery_policy import get_source_recovery_policy

            policy = get_source_recovery_policy()
            return policy.run_recovery_cycle(self._source_registry)
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.run_source_recovery_cycle failed (non-fatal): %s",
                _err,
            )
            return {
                "evicted": [],
                "audio_reelected": False,
                "video_reelected": False,
                "flap_smoothed_ids": [],
                "error": str(_err),
            }

    def source_recovery_snapshot(self) -> Dict[str, Any]:
        """PR-31: Return a diagnostics-safe snapshot of the source recovery policy state.

        The snapshot includes recent recovery/re-election events, current primary
        source IDs, and per-category source counts (recoverable, unrecoverable,
        stale, flapping).

        Safe to log and export for diagnostics and shell-facing status projection.
        Never raises.
        """
        try:
            from core.multimodal.source_recovery_policy import (
                build_source_recovery_snapshot,
            )

            snap = build_source_recovery_snapshot(self._source_registry)
            return snap.to_dict()
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.source_recovery_snapshot failed (non-fatal): %s",
                _err,
            )
            return {"snapshot_at": time.time(), "error": str(_err)}

    def _has_active_stream_source(self) -> bool:
        """Return True when any stream-capable source is currently active."""
        try:
            for source in self._source_registry.active_sources():
                if source.source_type in STREAM_CAPABLE_SOURCE_TYPES:
                    return True
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime._has_active_stream_source failed (non-fatal): %s",
                _err,
            )
            return False
        return False

    def realtime_streaming_backbone_summary(self) -> Dict[str, Any]:
        """Return formal stream-backbone contract + current runtime state."""
        try:
            from core.realtime_streaming_backbone import (
                build_realtime_stream_runtime_status,
                build_realtime_streaming_backbone_contract,
            )
            from core.unified_config import config as _cfg

            global _STREAMING_BACKBONE_CONTRACT
            if _STREAMING_BACKBONE_CONTRACT is None:
                _STREAMING_BACKBONE_CONTRACT = build_realtime_streaming_backbone_contract()
            enable_webrtc = bool(_cfg.get("enable_webrtc_session_manager", False)) and (
                self._webrtc_session_manager is not None
            )
            source_snapshot = self.snapshot_source_registry()
            runtime_status = build_realtime_stream_runtime_status(
                source_registry_snapshot=source_snapshot,
                enable_webrtc_session_manager=enable_webrtc,
            )
            # Stamp stream_runtime_ready directly from the runtime shell — this
            # is the first-class signal that a stream manager has been
            # initialised and is available for real stream handling.
            runtime_status["stream_runtime_ready"] = self.stream_runtime_ready
            return {
                "contract": _STREAMING_BACKBONE_CONTRACT,
                "runtime_status": runtime_status,
                "source_registry_snapshot": source_snapshot,
            }
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.realtime_streaming_backbone_summary failed (non-fatal): %s",
                _err,
            )
            return {"error": str(_err)}

    def permission_safety_summary(
        self,
        *,
        result: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PR-32: Return a shell-facing permission/trust/safety summary.

        Derives an :class:`~core.multimodal.permission_safety_state.OperatorSafetySummary`
        from the canonical :class:`~core.multimodal.permission_safety_state.PermissionSafetySnapshot`
        last committed to the singleton by OpenClawd.  If the singleton
        carries no snapshot yet, falls back to building a fresh one from the
        shell-owned source registry.

        This method is the runtime shell's primary entry point for presenting
        permission and trust state to operators.  It always derives from
        canonical state and never acts as an independent truth source.

        Parameters
        ----------
        result:
            Optional OpenClawd response dict.  When provided, the embedded
            ``permission_safety_state`` is preferred over the singleton.
        trace_id:
            Optional correlation trace ID.

        Returns
        -------
        dict
            Serialisable :class:`~core.multimodal.permission_safety_state.OperatorSafetySummary`
            dict.  Never raises.
        """
        try:
            from core.multimodal.permission_safety_state import (  # noqa: PLC0415
                build_operator_safety_summary,
                build_permission_safety_snapshot,
                get_permission_safety_state,
                PermissionSafetySnapshot,
            )

            # Prefer snapshot embedded in the OpenClawd response
            snap_dict: Optional[Dict[str, Any]] = None
            if isinstance(result, dict):
                snap_dict = result.get("metadata", {}).get("permission_safety_state")

            snap: Optional[PermissionSafetySnapshot] = None
            if isinstance(snap_dict, dict):
                snap = PermissionSafetySnapshot.from_dict(snap_dict)
            else:
                # Fall back to singleton committed by OpenClawd
                snap = get_permission_safety_state().latest_snapshot

            if snap is None:
                # Final fallback: build from the shell-owned registry
                snap = build_permission_safety_snapshot(
                    source_registry_snapshot=self.snapshot_source_registry(),
                    trace_id=trace_id,
                )

            summary = build_operator_safety_summary(snap)
            return summary.to_dict()
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.permission_safety_summary failed (non-fatal): %s",
                _err,
            )
            return {"operator_message": "trust=unknown", "error": str(_err)}

    # ── PR-33: Operator Override Panel ───────────────────────────────────────

    def set_operator_override(
        self,
        override_set: "Any",  # OperatorOverrideSet (avoid hard import at module level)
        *,
        applied_by: Optional[str] = None,
        context_trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PR-33: Commit an :class:`~core.operator_override.OperatorOverrideSet` as the active override.

        This is the **shell-owned entry point** for operator-initiated override
        requests.  The override is committed to the process-wide singleton; it
        will be evaluated by OpenClawd on the next control-loop iteration.

        Parameters
        ----------
        override_set:
            The :class:`~core.operator_override.OperatorOverrideSet` to commit.
        applied_by:
            Optional identifier of the operator (for audit trail).
        context_trace_id:
            Optional correlation trace ID.

        Returns
        -------
        dict
            Summary dict with ``"override_id"``, ``"applied_domains"``,
            ``"override_reason"``, and ``"status"`` keys.  Never raises.
        """
        try:
            from core.operator_override import (  # noqa: PLC0415
                get_operator_override_state,
                build_override_summary,
            )

            state = get_operator_override_state()
            state.commit(
                override_set,
                applied_by=applied_by,
                context_trace_id=context_trace_id,
            )
            snap = state.snapshot()
            summary = build_override_summary(snap)
            return {
                "status": "committed",
                "override_id": override_set.override_id,
                **summary,
            }
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.set_operator_override failed (non-fatal): %s",
                _err,
            )
            return {"status": "error", "error": str(_err)}

    def clear_operator_override(
        self,
        *,
        applied_by: Optional[str] = None,
        context_trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PR-33: Clear the active operator override, returning to automation default.

        This is the **shell-owned entry point** for clearing a previously
        committed override.  After this call, OpenClawd's control-loop will
        resume canonical automation for all overridden domains.

        Returns
        -------
        dict
            ``{"status": "cleared"}`` on success.  Never raises.
        """
        try:
            from core.operator_override import get_operator_override_state  # noqa: PLC0415

            state = get_operator_override_state()
            state.clear(applied_by=applied_by, context_trace_id=context_trace_id)
            return {"status": "cleared"}
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.clear_operator_override failed (non-fatal): %s",
                _err,
            )
            return {"status": "error", "error": str(_err)}

    def operator_override_summary(
        self,
        *,
        result: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PR-33: Return a shell-facing summary of the active operator override state.

        Derives a human-readable summary from the canonical
        :class:`~core.operator_override.OperatorOverrideSnapshot`.  When *result*
        is provided (an OpenClawd response dict), the embedded
        ``"operator_override_state"`` snapshot is preferred; otherwise the
        process-wide singleton is queried directly.

        This method is the runtime shell's primary entry point for presenting
        override state to operators, dashboards, and diagnostics.  It derives
        from canonical state and never acts as an independent truth source.

        Parameters
        ----------
        result:
            Optional OpenClawd response dict.  When provided, the embedded
            ``operator_override_state`` snapshot is preferred.
        trace_id:
            Optional correlation trace ID.

        Returns
        -------
        dict
            Serialisable summary dict with ``"has_active_override"``,
            ``"applied_domains"``, ``"override_reason"``, and
            ``"operator_message"`` keys.  Never raises.
        """
        try:
            from core.operator_override import (  # noqa: PLC0415
                get_operator_override_state,
                build_override_summary,
                OperatorOverrideSnapshot,
            )

            snap_dict: Optional[Dict[str, Any]] = None
            if isinstance(result, dict):
                snap_dict = result.get("metadata", {}).get("operator_override_state")

            snap: Optional[OperatorOverrideSnapshot] = None
            if isinstance(snap_dict, dict):
                snap = OperatorOverrideSnapshot.from_dict(snap_dict)
            else:
                snap = get_operator_override_state().snapshot(trace_id=trace_id)

            return build_override_summary(snap)
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.operator_override_summary failed (non-fatal): %s",
                _err,
            )
            return {
                "has_active_override": False,
                "applied_domains": [],
                "override_reason": "",
                "operator_message": "override=unknown",
                "error": str(_err),
            }

    def decision_timeline_replay(
        self,
        *,
        result: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PR-34: Return a shell-facing replay of the decision timeline.

        Derives an :class:`~core.decision_timeline.ExplainabilitySnapshot` for
        shell-facing replay and diagnostics.  When *result* is provided (an
        OpenClawd response dict), the embedded ``decision_timeline_snapshot`` is
        preferred; otherwise the process-wide
        :class:`~core.decision_timeline.DecisionTimeline` singleton is queried
        directly to build a fresh snapshot.

        This method is the runtime shell's primary entry point for presenting
        decision history to operators, dashboards, and replay tools.  It
        derives from canonical state and never acts as an independent truth
        source.

        Parameters
        ----------
        result:
            Optional OpenClawd response dict.  When provided, the embedded
            ``decision_timeline_snapshot`` snapshot is preferred.
        trace_id:
            Optional correlation trace ID.

        Returns
        -------
        dict
            Serialisable :class:`~core.decision_timeline.ExplainabilitySnapshot`
            dict.  Always has ``"events"``, ``"total_events"``,
            ``"kind_counts"``, and ``"snapshot_id"`` keys.  Never raises.
        """
        try:
            from core.decision_timeline import (  # noqa: PLC0415
                build_explainability_snapshot,
                ExplainabilitySnapshot,
            )

            snap_dict: Optional[Dict[str, Any]] = None
            if isinstance(result, dict):
                snap_dict = result.get("metadata", {}).get("decision_timeline_snapshot")

            if isinstance(snap_dict, dict):
                return snap_dict

            # Fall back to live snapshot from global timeline singleton
            snap = build_explainability_snapshot(trace_id=trace_id)
            return snap.to_dict()
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.decision_timeline_replay failed (non-fatal): %s",
                _err,
            )
            return {
                "snapshot_id": "",
                "events": [],
                "total_events": 0,
                "kind_counts": {},
                "error": str(_err),
            }

    def production_baseline_summary(
        self,
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """PR-36: Return a shell-facing production baseline status summary.

        Derives a compact production baseline status summary from the most
        recent response result produced by OpenClawd.  The summary confirms
        that the unified canonical control loop is active as the production
        baseline and reports coverage of canonical primary artifacts.

        This method is **derived-only** — it reads from the canonical
        artifacts already present in *result* and never acts as an independent
        truth source.  The runtime shell exposes this for status-board and
        diagnostics rendering only.

        Parameters
        ----------
        result:
            The result dict from the most recent
            :meth:`~core.openclawd.OpenClawd.process` call (or
            :meth:`handle_request`).  The ``metadata`` sub-dict is read
            to extract canonical artifact coverage information.

        Returns
        -------
        dict
            Compact production baseline summary.  Always returns a valid dict;
            returns an error-annotated dict on failure.
        """
        try:
            from core.production_baseline import build_production_baseline_summary as _build_pbs

            metadata: Dict[str, Any] = {}
            if isinstance(result, dict):
                _meta = result.get("metadata") or {}
                if isinstance(_meta, dict):
                    metadata = _meta

            return _build_pbs(response_metadata=metadata)
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.production_baseline_summary failed (non-fatal): %s",
                _err,
            )
            return {
                "baseline_active": True,
                "error": str(_err),
            }

    def build_desktop_status_projection(
        self,
        result: Optional[Dict[str, Any]] = None,
        tristate: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-22: Build a canonical desktop status projection dict for shell-facing status board rendering.

        The runtime shell combines:
        - The unified control plan produced by OpenClawd (extracted from *result*
          metadata), which carries perception, model, execution, fallback, and
          lifecycle state owned by the control core.
        - The shell-owned source registry snapshot, which tracks available
          multimodal sources (microphone, camera, WebRTC, etc.).

        The returned dict is additive, JSON-serialisable, and safe for logging,
        status-board rendering, and diagnostics.  Never raises — returns
        ``None`` on any internal failure.

        Parameters
        ----------
        result:
            The result dict from the most recent OpenClawd.process() call.
            The ``metadata.unified_control_plan`` key is extracted when present.
        tristate:
            Current subject tri-state value (``"silent"`` / ``"liminal"`` /
            ``"manifest"``).  Pass the value from the RuntimeSession.
        runtime_session_id:
            Correlation ID for the active runtime session.

        Returns
        -------
        dict or None
            Serialisable desktop status projection dict, or ``None`` on failure.
        """
        try:
            from contracts.desktop_status_projection import (
                build_desktop_status_projection as _build_dsp,
                desktop_status_projection_summary as _dsp_summary,
            )

            # Extract unified control plan from result metadata.
            unified_control_plan: Optional[Dict[str, Any]] = None
            if isinstance(result, dict):
                _meta = result.get("metadata") or {}
                if isinstance(_meta, dict):
                    unified_control_plan = _meta.get("unified_control_plan")
                # Also accept a top-level key for convenience.
                if unified_control_plan is None:
                    unified_control_plan = result.get("unified_control_plan")

            source_registry_snapshot = self.snapshot_source_registry()

            projection = _build_dsp(
                unified_control_plan=unified_control_plan,
                source_registry_snapshot=source_registry_snapshot,
                tristate=tristate,
                runtime_session_id=runtime_session_id,
            )
            return projection.to_dict()
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.build_desktop_status_projection failed (non-fatal): %s",
                _err,
            )
            return None

    async def on_goal_execution_result(
        self,
        task_id: str,
        device_id: str,
        status: str,
        result: str,
        trace_id: str,
        *,
        group_id: Optional[str] = None,
        group_summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        """收到设备端目标执行结果时的回调 — canonical result 收口。

        由 GalaxyGateway.android_bridge._handle_goal_execution_result 调用，
        在结果持久化到 TaskMemory 之后触发。

        本方法承担以下职责：
        1. 记录结构化日志（可观测性）
        2. 将结果写入 CanonicalTaskRuntime（更新 lifecycle → COMPLETED/FAILED）
        3. 将结果注入匹配的 RuntimeSession 上下文（供 LLM 后续推理）
        4. 将结果写入 TaskMemory（canonical backflow）

        Args:
            task_id: Unique identifier for the task that completed.
            device_id: ID of the Android device that produced the result.
            status: Execution status string (e.g. ``"completed"``, ``"failed"``).
            result: Human-readable result or error summary text.
            trace_id: Correlation trace ID propagated from the original request.
            group_id: Optional group identifier when this result belongs to a
                parallel/grouped subtask batch.  Provided only on the
                group-complete notification emitted by the goal_execution handler.
            group_summary: Optional aggregated summary dict produced by
                :class:`~core.goal_result_aggregator.GoalResultAggregator` when
                the group-complete notification fires.  Contains fields such as
                ``overall_success``, ``completed_count``, ``success_count``, etc.
        """
        _status_lower = (status or "").lower().strip()
        _success = _status_lower in ("completed", "success", "done", "true")

        logger.info(
            "GoalExecutionResult received | task_id=%s device_id=%s status=%s "
            "result=%r trace_id=%s group_id=%s",
            task_id,
            device_id,
            status,
            str(result)[:100],
            trace_id,
            group_id,
        )

        # ── 1. Write to CanonicalTaskRuntime ─────────────────────────────
        try:
            from core.canonical_task import (
                get_canonical_task_runtime,
                TaskLifecycle,
                build_canonical_task,
                TaskOrigin,
            )
            ctr = get_canonical_task_runtime()
            canonical_task = ctr.get_by_task_id(task_id)
            if canonical_task is not None:
                new_lifecycle = (
                    TaskLifecycle.COMPLETED if _success else TaskLifecycle.FAILED
                )
                canonical_task.result.success = _success
                canonical_task.result.result_summary = (
                    str(result)[:400] if result else f"status={status}"
                )
                ctr.update_lifecycle(task_id, new_lifecycle)
                logger.debug(
                    "GoalExecutionResult: CanonicalTask updated | task_id=%s lifecycle=%s",
                    task_id,
                    new_lifecycle.value,
                )
            else:
                # Task not registered — create a lightweight record so the
                # result is at least visible in the observability ring-buffer.
                try:
                    new_task = build_canonical_task(
                        task_id=task_id,
                        trace_id=trace_id or task_id,
                        goal=f"[goal_execution_result] task_id={task_id}",
                        origin=TaskOrigin.DEVICE_COMMAND,
                        selected_targets=[device_id],
                    )
                    new_task.result.success = _success
                    new_task.result.result_summary = (
                        str(result)[:400] if result else f"status={status}"
                    )
                    new_lifecycle = (
                        TaskLifecycle.COMPLETED if _success else TaskLifecycle.FAILED
                    )
                    new_task.advance_lifecycle(TaskLifecycle.ADMITTED)
                    new_task.advance_lifecycle(TaskLifecycle.RUNNING)
                    new_task.advance_lifecycle(new_lifecycle)
                    ctr.register(new_task)
                    logger.debug(
                        "GoalExecutionResult: new CanonicalTask registered (result-first) | "
                        "task_id=%s lifecycle=%s",
                        task_id,
                        new_lifecycle.value,
                    )
                except Exception as _build_err:
                    logger.debug(
                        "GoalExecutionResult: build_canonical_task failed (non-fatal): %s",
                        _build_err,
                    )
        except Exception as ctr_err:
            logger.debug(
                "GoalExecutionResult: CanonicalTaskRuntime update failed (non-fatal): %s",
                ctr_err,
            )

        # ── 2. Inject result into matching RuntimeSession ────────────────
        try:
            if hasattr(self, "_active_sessions") and self._active_sessions:
                for session in self._active_sessions.values():
                    if session.runtime_session_id == trace_id:
                        # Attach result context to the session so that
                        # subsequent LLM reasoning can observe it.
                        if not hasattr(session, "goal_results"):
                            session.goal_results = {}  # type: ignore[attr-defined]
                        session.goal_results[task_id] = {  # type: ignore[attr-defined]
                            "task_id": task_id,
                            "device_id": device_id,
                            "status": status,
                            "result": result,
                            "success": _success,
                            "group_id": group_id,
                        }
                        logger.debug(
                            "GoalExecutionResult: injected into session %s | task_id=%s",
                            trace_id,
                            task_id,
                        )
                        break
        except Exception as inject_err:
            logger.debug(
                "GoalExecutionResult: session injection failed (non-fatal): %s",
                inject_err,
            )

        # ── 3. Canonical TaskMemory backflow ─────────────────────────────
        try:
            from core.openclawd_memory_backflow import store_task_result as _store_task_result_fn
            await _store_task_result_fn(
                task_id=task_id,
                device_id=device_id,
                route_mode="goal_execution",
                result={
                    "status": status,
                    "result": result,
                    "trace_id": trace_id,
                    "task_type": "goal_execution_result",
                    "group_id": group_id,
                    "group_summary": group_summary,
                },
                session_id=trace_id or None,
            )
            logger.debug(
                "GoalExecutionResult: TaskMemory canonical backflow completed | task_id=%s",
                task_id,
            )
        except Exception as mem_err:
            logger.debug(
                "GoalExecutionResult: TaskMemory backflow failed (non-fatal): %s",
                mem_err,
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

    def _update_presence_mode(
        self,
        *,
        tri_state: str,
        task_active: bool,
        sensing_active: bool,
        execution_active: bool,
        user_interaction: bool,
        result_committed: bool = False,
    ) -> Dict[str, Any]:
        transition: Optional[Dict[str, Any]] = None
        try:
            transition = self._presence_state_machine.update(
                tri_state=tri_state,
                task_active=task_active,
                sensing_active=sensing_active,
                execution_active=execution_active,
                user_interaction=user_interaction,
                result_committed=result_committed,
            )
        except Exception as exc:
            logger.debug(
                "presence state machine update failed (non-fatal): tri_state=%s task_active=%s "
                "sensing_active=%s execution_active=%s user_interaction=%s result_committed=%s "
                "err=%s (runtime continues with last known presence mode)",
                tri_state,
                task_active,
                sensing_active,
                execution_active,
                user_interaction,
                result_committed,
                exc,
            )
        self._latest_presence_runtime_hint = {
            "presence_mode": self._presence_state_machine.mode.value,
            "previous_presence_mode": (
                (transition or {}).get("from_mode")
                or self._presence_state_machine.mode.value
            ),
            "presence_mode_changed": bool(transition),
            "presence_transition_reason": self._derive_presence_transition_reason(transition),
            "presence_transition": dict(transition) if isinstance(transition, dict) else None,
        }
        return dict(self._latest_presence_runtime_hint)

    @staticmethod
    def _derive_presence_transition_reason(
        transition: Optional[Dict[str, Any]],
    ) -> str:
        if not isinstance(transition, dict):
            return "mode_stable"
        from_mode = transition.get("from_mode")
        to_mode = transition.get("to_mode")
        if from_mode == "static" and to_mode == "liminal":
            return "request_received_or_continuous_sensing"
        if from_mode == "liminal" and to_mode == "manifest":
            return "execution_path_confirmed_and_running"
        if from_mode == "manifest" and to_mode == "liminal":
            return "execution_completed_or_result_committed"
        if from_mode == "liminal" and to_mode == "static":
            return "stability_window_elapsed_without_task_or_sensing"
        return "presence_transition_applied"

    def _current_presence_runtime_hint(self) -> Dict[str, Any]:
        return dict(self._latest_presence_runtime_hint)

    # ------------------------------------------------------------------
    # PR-8 V2: Compact presence summary for operator surfaces
    # ------------------------------------------------------------------

    def presence_summary(self) -> Dict[str, Any]:
        """Return a compact, read-only summary of active presence sessions.

        This is a **shell-owned** view of the current tri-state distribution
        across all in-flight runtime sessions.  It is intended for operator
        surfaces and status boards that need to know whether the subject is
        currently at rest (``silent``), processing (``liminal``), or actively
        expressing (``manifest``).

        This method never mutates runtime session tri-state records.  It does
        mutate the internal product-level presence state machine by running one
        best-effort convergence tick using the already-observed active-session
        distribution so presence mode can settle after cooldown windows.
        Any internal failure returns an empty default dict rather than raising.

        Returns
        -------
        dict with keys:
            ``active_session_count``
                Total number of in-flight runtime sessions.
            ``tristate_distribution``
                Dict mapping each TriState value (``"silent"``,
                ``"liminal"``, ``"manifest"``) to its session count.
            ``dominant_tristate``
                The most active non-silent phase in current sessions, or
                ``"silent"`` when no request is in progress.  Follows the
                priority order: ``manifest`` > ``liminal`` > ``silent``.
        """
        try:
            sessions = list(self._active_sessions.values())
            counts: Dict[str, int] = {
                TriState.SILENT.value: 0,
                TriState.LIMINAL.value: 0,
                TriState.MANIFEST.value: 0,
            }
            for sess in sessions:
                key = sess.tristate.value
                counts[key] = counts.get(key, 0) + 1

            # Dominant tri-state: manifest > liminal > silent
            if counts.get(TriState.MANIFEST.value, 0) > 0:
                dominant = TriState.MANIFEST.value
            elif counts.get(TriState.LIMINAL.value, 0) > 0:
                dominant = TriState.LIMINAL.value
            else:
                dominant = TriState.SILENT.value

            self._update_presence_mode(
                tri_state=dominant,
                task_active=len(sessions) > 0,
                sensing_active=self._has_active_stream_source(),
                execution_active=counts.get(TriState.MANIFEST.value, 0) > 0,
                user_interaction=False,
            )
            stream_backbone = self.realtime_streaming_backbone_summary()
            presence_system = build_desktop_presence_system_view(
                state_machine_snapshot=self._presence_state_machine.snapshot(),
                dominant_tristate=dominant,
                tristate_distribution=dict(counts),
                active_session_count=len(sessions),
                stream_runtime_status=stream_backbone.get("runtime_status"),
            )

            return {
                "active_session_count": len(sessions),
                "tristate_distribution": dict(counts),
                "dominant_tristate": dominant,
                "desktop_presence_system": presence_system,
                "realtime_streaming_backbone": stream_backbone,
            }
        except Exception as _err:
            logger.debug(
                "DesktopPresenceRuntime.presence_summary failed (non-fatal): %s", _err
            )
            return {
                "active_session_count": 0,
                "tristate_distribution": {},
                "dominant_tristate": TriState.SILENT.value,
                "desktop_presence_system": build_desktop_presence_system_view(
                    state_machine_snapshot=self._presence_state_machine.snapshot(),
                    dominant_tristate=TriState.SILENT.value,
                    tristate_distribution={},
                    active_session_count=0,
                ),
                "realtime_streaming_backbone": self.realtime_streaming_backbone_summary(),
            }


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
