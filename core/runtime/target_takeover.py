"""core/runtime/target_takeover.py
====================================
Target Runtime Local Takeover Path — PR-34.

This module implements the **canonical target-side execution path** that
allows a target device's local runtime to:

1. Accept and normalise an incoming handoff envelope (PR-31 or legacy
   ``HandoffContract``).
2. Resolve or create a local session context (session adoption helpers).
3. Execute locally using existing execution facilities
   (``OpenClawd._run_execution()``-style path).
4. Return a structured :class:`~contracts.local_takeover_result.LocalTakeoverResult`.

This is the first real target-side execution step of the runtime-device-mesh
phase (PR-34).  It is **minimal and additive**: it reuses the existing execution
infrastructure, does not redesign the runtime API surface, and degrades
gracefully when upstream context is unavailable.

Public surface
--------------
Handler class:
    :class:`TargetTakeoverHandler` — stateless handler; call
    :meth:`~TargetTakeoverHandler.handle` with any envelope/dict payload.

Session adoption helpers:
    :func:`adopt_handoff_session` — maps an envelope into a
    :class:`~contracts.local_takeover_result.LocalTakeoverSessionContext`.

    :func:`resolve_or_create_runtime_session` — returns an existing session ID
    or mints a fresh one.

    :func:`build_local_takeover_context` — assembles the state-continuum dict
    suitable for ``_run_execution``.

Envelope normalisation:
    :func:`normalize_handoff_envelope` — accepts a
    :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`, a legacy
    ``HandoffContract``, or a raw ``dict`` and always returns a
    :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`.

Top-level entry point:
    :func:`execute_local_takeover` — end-to-end convenience function.

Design principles
-----------------
- **Additive only** — no changes to openclawd.py, agent_bridge.py, or any
  existing module.
- **Reuses execution path** — calls ``OpenClawd._run_execution()`` (or
  degrades gracefully when OpenClawd is unavailable).
- **Graceful degradation** — every function returns a valid result even when
  inputs are partial, None, or raise.
- **Tolerant of legacy payloads** — :func:`normalize_handoff_envelope` adapts
  legacy ``HandoffContract`` objects and raw dicts to v2 envelopes.
- **No persistence / streaming** — in-scope for future PRs only.
- **No Mesh Session Coordinator** — out of scope for PR-34.

Usage::

    from core.runtime.target_takeover import execute_local_takeover
    from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

    envelope = build_handoff_envelope_v2(
        trace_id="trace_abc",
        task={"tool_name": "screenshot", "args": {}},
        session_id="sess_001",
        target_device_id="tablet_002",
    )
    result = execute_local_takeover(envelope)
    payload = result.to_dict()

Or use the handler class directly::

    from core.runtime.target_takeover import TargetTakeoverHandler

    handler = TargetTakeoverHandler()
    result = handler.handle(envelope_or_dict)

See ``docs/TARGET_RUNTIME_LOCAL_TAKEOVER.md`` for the full specification.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Envelope normalisation
# ---------------------------------------------------------------------------


def normalize_handoff_envelope(
    payload: Any,
) -> Any:
    """Normalise *payload* to a :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`.

    Accepts any of:
    - A :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` instance
      (returned unchanged).
    - A legacy ``HandoffContract`` dataclass/object (converted via
      :func:`~contracts.handoff_envelope_v2.from_legacy_handoff_contract`).
    - A plain ``dict`` (wrapped via
      :func:`~contracts.handoff_envelope_v2.build_handoff_envelope_v2`).
    - ``None`` (returns an empty envelope with a generated ``trace_id``).

    This function never raises.  On unexpected input it returns a minimal
    valid envelope.

    Parameters
    ----------
    payload:
        Incoming handoff payload of any recognised type.

    Returns
    -------
    HandoffEnvelopeV2
    """
    try:
        from contracts.handoff_envelope_v2 import (
            HandoffEnvelopeV2,
            from_legacy_handoff_contract,
            build_handoff_envelope_v2,
        )

        if payload is None:
            return build_handoff_envelope_v2(
                trace_id=str(uuid.uuid4()),
                task={},
            )

        if isinstance(payload, HandoffEnvelopeV2):
            return payload

        # Raw dict — treat as keyword bag
        if isinstance(payload, dict):
            trace_id = payload.get("trace_id") or str(uuid.uuid4())
            task = payload.get("task") or {}
            return build_handoff_envelope_v2(
                trace_id=trace_id,
                task=task,
                task_id=payload.get("task_id"),
                session_id=payload.get("session_id"),
                source_device_id=payload.get("source_device_id"),
                target_device_id=payload.get("target_device_id"),
                source_runtime_id=payload.get("source_runtime_id"),
                target_runtime_id=payload.get("target_runtime_id"),
                agent_id=payload.get("agent_id"),
                agent_type=payload.get("agent_type"),
                agent_role=payload.get("agent_role"),
                metadata=payload.get("metadata"),
            )

        # Assume legacy HandoffContract duck-type
        return from_legacy_handoff_contract(payload)

    except Exception as exc:  # noqa: BLE001
        logger.debug("normalize_handoff_envelope: normalisation failed: %s", exc)
        try:
            from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
            return build_handoff_envelope_v2(
                trace_id=str(uuid.uuid4()),
                task={},
            )
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# Session adoption helpers
# ---------------------------------------------------------------------------


def adopt_handoff_session(
    envelope: Any,
    *,
    existing_runtime_session_id: Optional[str] = None,
) -> Any:
    """Map an incoming handoff envelope into a local session context.

    Extracts ``trace_id``, ``task_id``, and ``session_id`` from *envelope*
    and wraps them in a
    :class:`~contracts.local_takeover_result.LocalTakeoverSessionContext`.

    When an existing ``runtime_session_id`` is provided the session is marked
    as *adopted* (``adopted=True``); otherwise a new session ID is generated
    and ``adopted`` is set to ``False``.

    Optionally attaches mesh session ID when a PR-33
    :class:`~contracts.mesh_session.MeshSession` context is available.

    This function never raises.

    Parameters
    ----------
    envelope:
        A :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` or
        any duck-typed object with ``trace_id``, ``task_id``, ``session_id``
        attributes.
    existing_runtime_session_id:
        When provided, marks the session as *adopted* and uses this value
        as ``runtime_session_id``.

    Returns
    -------
    LocalTakeoverSessionContext
    """
    try:
        from contracts.local_takeover_result import LocalTakeoverSessionContext

        _trace_id: Optional[str] = None
        _task_id: Optional[str] = None
        _session_id: Optional[str] = None
        _mesh_session_id: Optional[str] = None

        if envelope is not None:
            _trace_id = getattr(envelope, "trace_id", None) or None
            _task_id = getattr(envelope, "task_id", None) or None
            _session_id = getattr(envelope, "session_id", None) or None

        # Attempt to attach a mesh session ID from PR-33 context
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            _registry = get_body_mesh_registry()
            _mesh_sess = _registry.get_mesh_session(mesh_id="default_mesh")
            if _mesh_sess is not None:
                _mesh_session_id = _mesh_sess.session_id or None
        except Exception:  # noqa: BLE001
            pass

        _adopted = existing_runtime_session_id is not None
        _runtime_session_id = existing_runtime_session_id or str(uuid.uuid4())
        if not _session_id:
            _session_id = str(uuid.uuid4())

        return LocalTakeoverSessionContext(
            session_id=_session_id,
            runtime_session_id=_runtime_session_id,
            task_id=_task_id,
            trace_id=_trace_id,
            adopted=_adopted,
            mesh_session_id=_mesh_session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("adopt_handoff_session: failed: %s", exc)
        try:
            from contracts.local_takeover_result import LocalTakeoverSessionContext
            return LocalTakeoverSessionContext(
                session_id=str(uuid.uuid4()),
                adopted=False,
            )
        except Exception:  # noqa: BLE001
            return None


def resolve_or_create_runtime_session(
    envelope: Any,
    *,
    existing_runtime_session_id: Optional[str] = None,
) -> str:
    """Return an existing runtime session ID or mint a fresh one.

    When *existing_runtime_session_id* is provided it is returned as-is.
    Otherwise a fresh UUID4 session ID is generated.

    When the envelope carries a ``session_id`` and no existing session is
    supplied, the envelope's session ID is preferred over a randomly generated
    one, to preserve continuity across the handoff.

    Parameters
    ----------
    envelope:
        Handoff envelope with optional ``session_id`` attribute.
    existing_runtime_session_id:
        Existing runtime session ID to reuse.

    Returns
    -------
    str
        Session ID to use for this local execution.
    """
    if existing_runtime_session_id:
        return existing_runtime_session_id

    try:
        _env_session = getattr(envelope, "session_id", None)
        if _env_session:
            return str(_env_session)
    except Exception:  # noqa: BLE001
        pass

    return str(uuid.uuid4())


def build_local_takeover_context(
    envelope: Any,
    *,
    session_context: Any = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the state-continuum dict used by the local execution path.

    Produces a dict shaped like the ``state_continuum`` parameter expected by
    ``OpenClawd._run_execution()``.  It extracts task, session, and trace
    information from *envelope* and wraps it with minimal metadata suitable
    for local execution.

    This function never raises; on error it returns a minimal safe dict.

    Parameters
    ----------
    envelope:
        Normalised :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`.
    session_context:
        :class:`~contracts.local_takeover_result.LocalTakeoverSessionContext`
        resolved by :func:`adopt_handoff_session`.
    extra_metadata:
        Arbitrary extra metadata to merge into the ``"metadata"`` key.

    Returns
    -------
    dict
        State-continuum dict ready for ``_run_execution``.
    """
    try:
        _task: Dict[str, Any] = {}
        _session_dict: Dict[str, Any] = {}
        _trace_id: Optional[str] = None
        _task_id: Optional[str] = None

        if envelope is not None:
            _trace_id = getattr(envelope, "trace_id", None)
            _task_id = getattr(envelope, "task_id", None)

            # Extract task spec
            _task_spec = getattr(envelope, "task_spec", None)
            if _task_spec is not None:
                if hasattr(_task_spec, "model_dump"):
                    _task = _task_spec.model_dump(mode="json")
                elif hasattr(_task_spec, "__dict__"):
                    _task = dict(_task_spec.__dict__)
                else:
                    _raw = getattr(_task_spec, "raw_task", None)
                    if isinstance(_raw, dict):
                        _task = _raw
            elif hasattr(envelope, "task") and isinstance(getattr(envelope, "task", None), dict):
                _task = getattr(envelope, "task", {})

            # Extract session context
            _sess_ctx = getattr(envelope, "session_context", None)
            if _sess_ctx is not None:
                if hasattr(_sess_ctx, "model_dump"):
                    _session_dict = _sess_ctx.model_dump(mode="json")
                elif isinstance(_sess_ctx, dict):
                    _session_dict = _sess_ctx
            elif hasattr(envelope, "session") and isinstance(getattr(envelope, "session", None), dict):
                _session_dict = getattr(envelope, "session", {})

        # Merge session context from adoption
        _sc_id: Optional[str] = None
        _rt_sess_id: Optional[str] = None
        if session_context is not None:
            _sc_id = getattr(session_context, "session_id", None)
            _rt_sess_id = getattr(session_context, "runtime_session_id", None)
            if _sc_id:
                _session_dict["session_id"] = _sc_id

        _metadata: Dict[str, Any] = {
            "source": "target_takeover",
            "trace_id": _trace_id,
            "task_id": _task_id,
            "runtime_session_id": _rt_sess_id,
            "force_local_execution": True,
        }
        if extra_metadata:
            _metadata.update(extra_metadata)

        return {
            "task": _task,
            "session": _session_dict,
            "trace_id": _trace_id,
            "task_id": _task_id,
            "metadata": _metadata,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("build_local_takeover_context: failed: %s", exc)
        return {
            "task": {},
            "session": {},
            "trace_id": None,
            "task_id": None,
            "metadata": {
                "source": "target_takeover",
                "error": str(exc),
                "force_local_execution": True,
            },
        }


# ---------------------------------------------------------------------------
# Core takeover execution
# ---------------------------------------------------------------------------


def _run_local_execution(
    state_continuum: Dict[str, Any],
    *,
    entry_mode: str = "local",
) -> Dict[str, Any]:
    """Invoke local execution via OpenClawd._run_execution().

    Attempts to acquire the OpenClawd singleton and call ``_run_execution``.
    Degrades gracefully when OpenClawd is unavailable (e.g. in test
    environments) — returns a minimal skipped result dict.

    Parameters
    ----------
    state_continuum:
        State-continuum dict assembled by :func:`build_local_takeover_context`.
    entry_mode:
        Execution mode string; defaults to ``"local"`` for takeover flows.

    Returns
    -------
    dict
        Execution result dict (always returned, never raises).
    """
    try:
        # Prefer singleton accessor if available
        _openclawd_instance = None
        try:
            from core.openclawd import OpenClawd
            # Attempt to get singleton or create minimal instance
            if hasattr(OpenClawd, "get_instance"):
                _openclawd_instance = OpenClawd.get_instance()
            elif hasattr(OpenClawd, "_instance"):
                _openclawd_instance = OpenClawd._instance
        except Exception:  # noqa: BLE001
            pass

        if _openclawd_instance is not None and hasattr(_openclawd_instance, "_run_execution"):
            return _openclawd_instance._run_execution(
                state_continuum,
                entry_mode=entry_mode,
            )

        # Fallback: no OpenClawd instance available
        logger.debug(
            "_run_local_execution: OpenClawd instance unavailable; "
            "returning skipped result"
        )
        return {
            "action_taken": "none",
            "success": False,
            "skipped_reason": "executor_unavailable:no_openclawd_instance",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("_run_local_execution: execution raised: %s", exc)
        return {
            "action_taken": "error",
            "success": False,
            "skipped_reason": f"internal_error:{exc}",
        }


def _try_governance_snapshot() -> Optional[Dict[str, Any]]:
    """Attempt to capture the current RuntimeGovernanceSnapshot (PR-27).

    Returns the serialised snapshot dict or ``None`` on any failure.
    """
    try:
        from core.runtime_governance.snapshot import assemble_runtime_governance_snapshot
        snap = assemble_runtime_governance_snapshot()
        if snap is not None:
            if hasattr(snap, "to_dict"):
                return snap.to_dict()
            if isinstance(snap, dict):
                return snap
    except Exception:  # noqa: BLE001
        pass
    return None


def _try_policy_alignment() -> Optional[Dict[str, Any]]:
    """Attempt to capture the current ExecutionPolicyAlignmentSurface (PR-28).

    Returns the serialised alignment dict or ``None`` on any failure.
    """
    try:
        from core.routes.projection import _assemble_policy_alignment  # type: ignore[attr-defined]
        return _assemble_policy_alignment()
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# TargetTakeoverHandler — stateless handler class
# ---------------------------------------------------------------------------


class TargetTakeoverHandler:
    """Stateless handler that executes the target-side local takeover path.

    Usage::

        handler = TargetTakeoverHandler()
        result = handler.handle(envelope)
        payload = result.to_dict()

    The handler is safe to instantiate multiple times and to call from multiple
    threads (it holds no mutable state).
    """

    def handle(
        self,
        payload: Any,
        *,
        existing_runtime_session_id: Optional[str] = None,
        entry_mode: str = "local",
        capture_governance: bool = True,
        capture_policy_alignment: bool = True,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute the full target-side local takeover path.

        Steps:
        1. Validate / normalise *payload* to a HandoffEnvelopeV2.
        2. Check takeover policy (``allow_local_takeover``).
        3. Adopt / create a local session context.
        4. Build state-continuum context.
        5. Run local execution.
        6. Optionally capture governance snapshot / policy alignment.
        7. Return a :class:`~contracts.local_takeover_result.LocalTakeoverResult`.

        This method never raises.

        Parameters
        ----------
        payload:
            Incoming handoff payload (HandoffEnvelopeV2, legacy
            HandoffContract, dict, or None).
        existing_runtime_session_id:
            Existing runtime session ID to reuse (``None`` = create new).
        entry_mode:
            Execution mode string forwarded to the executor.
        capture_governance:
            When ``True``, attempt to capture RuntimeGovernanceSnapshot.
        capture_policy_alignment:
            When ``True``, attempt to capture policy alignment surface.
        extra_metadata:
            Arbitrary extra metadata for the state-continuum.

        Returns
        -------
        LocalTakeoverResult
        """
        from contracts.local_takeover_result import (
            LocalTakeoverResult,
            LocalTakeoverStatus,
            from_execution_output,
            failure_result,
        )

        envelope = None
        try:
            # Step 1 — normalise envelope
            envelope = normalize_handoff_envelope(payload)

            _trace_id: Optional[str] = getattr(envelope, "trace_id", None) if envelope else None
            _task_id: Optional[str] = getattr(envelope, "task_id", None) if envelope else None

            # Step 2 — check takeover policy
            if envelope is not None:
                _policy = getattr(envelope, "takeover_policy", None)
                if _policy is not None:
                    _allow = getattr(_policy, "allow_local_takeover", True)
                    if _allow is False:
                        logger.debug(
                            "TargetTakeoverHandler.handle: takeover disallowed by policy | "
                            "trace_id=%s",
                            _trace_id,
                        )
                        return failure_result(
                            trace_id=_trace_id,
                            task_id=_task_id,
                            reason="takeover_disallowed_by_policy",
                            status=LocalTakeoverStatus.rejected,
                        )

            # Step 3 — adopt / create session context
            session_ctx = adopt_handoff_session(
                envelope,
                existing_runtime_session_id=existing_runtime_session_id,
            )
            _session_id = getattr(session_ctx, "session_id", None) if session_ctx else None
            _rt_session_id = getattr(session_ctx, "runtime_session_id", None) if session_ctx else None

            logger.debug(
                "TargetTakeoverHandler.handle: session adopted | "
                "trace_id=%s session_id=%s adopted=%s",
                _trace_id,
                _session_id,
                getattr(session_ctx, "adopted", False) if session_ctx else False,
            )

            # Step 4 — build state-continuum context
            state_continuum = build_local_takeover_context(
                envelope,
                session_context=session_ctx,
                extra_metadata=extra_metadata,
            )

            # Step 5 — run local execution
            exec_output = _run_local_execution(
                state_continuum,
                entry_mode=entry_mode,
            )

            # Step 6 — optionally capture governance / policy alignment
            _governance: Optional[Dict[str, Any]] = None
            _alignment: Optional[Dict[str, Any]] = None
            if capture_governance:
                _governance = _try_governance_snapshot()
            if capture_policy_alignment:
                _alignment = _try_policy_alignment()

            # Step 7 — build result
            return from_execution_output(
                trace_id=_trace_id,
                execution_output=exec_output,
                session_id=_session_id,
                runtime_session_id=_rt_session_id,
                task_id=_task_id,
                session_context=session_ctx,
                governance_snapshot=_governance,
                policy_alignment=_alignment,
                metadata={
                    "source_device_id": getattr(envelope, "source_device_id", None) if envelope else None,
                    "target_device_id": getattr(envelope, "target_device_id", None) if envelope else None,
                    "entry_mode": entry_mode,
                },
            )

        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "TargetTakeoverHandler.handle: unhandled exception: %s", exc
            )
            _trace_id2: Optional[str] = None
            _task_id2: Optional[str] = None
            try:
                if envelope is not None:
                    _trace_id2 = getattr(envelope, "trace_id", None)
                    _task_id2 = getattr(envelope, "task_id", None)
            except Exception:  # noqa: BLE001
                pass
            return failure_result(
                trace_id=_trace_id2,
                task_id=_task_id2,
                reason=f"internal_error:{exc}",
                errors=[str(exc)],
            )


# ---------------------------------------------------------------------------
# Top-level convenience entry point
# ---------------------------------------------------------------------------


def execute_local_takeover(
    payload: Any,
    *,
    existing_runtime_session_id: Optional[str] = None,
    entry_mode: str = "local",
    capture_governance: bool = True,
    capture_policy_alignment: bool = True,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Execute the full target-side local takeover path.

    This is the top-level convenience entry point for PR-34.  It instantiates
    a :class:`TargetTakeoverHandler` and delegates to its
    :meth:`~TargetTakeoverHandler.handle` method.

    Parameters
    ----------
    payload:
        Incoming handoff payload (HandoffEnvelopeV2, legacy HandoffContract,
        dict, or None).
    existing_runtime_session_id:
        Existing runtime session ID to reuse (``None`` = create new).
    entry_mode:
        Execution mode string forwarded to the executor.
    capture_governance:
        When ``True``, attempt to capture RuntimeGovernanceSnapshot.
    capture_policy_alignment:
        When ``True``, attempt to capture policy alignment surface.
    extra_metadata:
        Arbitrary extra metadata for the state-continuum.

    Returns
    -------
    LocalTakeoverResult
        Always returned, never raises.
    """
    handler = TargetTakeoverHandler()
    return handler.handle(
        payload,
        existing_runtime_session_id=existing_runtime_session_id,
        entry_mode=entry_mode,
        capture_governance=capture_governance,
        capture_policy_alignment=capture_policy_alignment,
        extra_metadata=extra_metadata,
    )
