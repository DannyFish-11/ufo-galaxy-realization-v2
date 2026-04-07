"""core/attached_runtime_reuse_dispatch.py
==========================================
PR package 17 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Dispatch Consumption of Attached-Runtime Reuse Bindings.

Background
----------
PR-14 established ``core.attached_runtime_reuse_binding`` as the canonical
persistent reuse-binding layer that caches the stable targeting context for an
attached Android runtime session.  PR-11 provides
``core.android_runtime_dispatch_binding`` as the per-dispatch binding identity
carrier.

Until PR-17 these two layers existed in isolation: the reuse binding was
readable but not wired into the actual delegated dispatch path.  This meant
the system had reuse bindings but could not guarantee that real delegated
dispatch would ``lookup → eligibility-gate → reuse / reject / fallback``
before creating a new dispatch binding.

This module closes that gap by providing the **canonical dispatch-path
integration** that:

1. Looks up the most recent reuse binding for the target session or device
   (via :func:`~core.attached_runtime_reuse_binding.get_reuse_binding` /
   :func:`~core.attached_runtime_reuse_binding.get_reuse_binding_by_device`).
2. Evaluates eligibility via
   :func:`~core.attached_runtime_reuse_binding.evaluate_reuse_eligibility`,
   optionally cross-checking against the live
   :class:`~core.attached_runtime_session.AttachedRuntimeSessionRecord`.
3. When **eligible**: returns the existing reuse surface so the caller can
   reuse the already-established dispatch context without creating a new
   binding.
4. When **ineligible** (detach / disconnect / disable / invalidate / bad
   posture): returns a ``rejected`` or ``no_binding`` resolution so the
   caller can create a fresh dispatch binding or take the fallback path.
5. After a new dispatch binding is established, the caller MUST call
   :func:`write_back_dispatch_binding_id` to register the new
   ``binding_id`` against the reuse binding record, keeping the cached
   ``dispatch_binding_id`` up-to-date for subsequent reuse lookups.

Public API summary
------------------
Enums::

    ReuseDispatchResolutionKind — reused / new_binding / rejected / no_binding

Dataclasses::

    ReuseDispatchResolution     — result of resolve_reuse_dispatch_surface()

Functions::

    resolve_reuse_dispatch_surface(session_id, device_id, *, ...) -> ReuseDispatchResolution
    dispatch_with_reuse_binding(session_id, device_id, attached_session,
                                handoff_contract, execution_tracker, *,
                                ...) -> ReuseDispatchResolution
    write_back_dispatch_binding_id(resolution, dispatch_binding_id, *,
                                   runtime=None) -> ReuseDispatchResolution

Ten policy sentinels documenting the canonical dispatch-consumption rules.

One PR sentinel (``ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL``).

Design principles
-----------------
- **Additive only** — does not modify any prior module.
- **Eligibility gate before dispatch** — reuse binding lookup and eligibility
  evaluation MUST precede any dispatch binding creation.
- **Write-back discipline** — every new dispatch binding MUST be registered
  against the reuse binding via :func:`write_back_dispatch_binding_id` so
  the ``dispatch_binding_id`` cache stays current.
- **Invalidation hard-stop** — a reuse binding in ``ineligible`` state caused
  by detach / disconnect / disable / invalidation MUST NOT be returned as a
  reusable surface.  The resolution kind is ``rejected``.
- **Non-destructive** — when no reuse binding exists the resolution kind is
  ``no_binding``; the caller is free to establish one via
  :func:`~core.attached_runtime_reuse_binding.establish_reuse_binding` and
  proceed to dispatch normally.

PR package numbering
--------------------
Package 17 of the post-533 dual-repo runtime unification master plan.
MAIN-repo side only.  Android-repo side changes are out of scope.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Imports from prior PR packages
# ---------------------------------------------------------------------------

from core.attached_runtime_reuse_binding import (
    AttachedRuntimeReuseBindingRecord,
    AttachedRuntimeReuseBindingRuntime,
    ReuseEligibilityStatus,
    evaluate_reuse_eligibility,
    get_reuse_binding,
    get_reuse_binding_by_device,
    register_dispatch_binding_id,
)
from core.android_runtime_dispatch_binding import (
    AndroidRuntimeDispatchBindingRecord,
    AndroidRuntimeDispatchBindingRuntime,
    resolve_dispatch_binding,
)

# PR-22: Registry gate — imported lazily so the module remains loadable when
# the session registry is unavailable (e.g. during early boot or unit tests
# that do not initialise the full runtime).
try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        RegistryEntryState as _RegistryEntryState,
        get_session_registry as _get_session_registry,
        lookup_active_session as _lookup_active_session,
    )

    _REGISTRY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False
    AttachedSessionRegistry = None  # type: ignore[assignment,misc]
    _RegistryEntryState = None  # type: ignore[assignment]
    _get_session_registry = None  # type: ignore[assignment]
    _lookup_active_session = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY: str = (
    "core.attached_runtime_reuse_dispatch::PR17::canonical-dispatch-"
    "consumption-of-attached-runtime-reuse-bindings"
)

# ---------------------------------------------------------------------------
# Policy sentinels — document canonical dispatch-consumption rules
# ---------------------------------------------------------------------------

REUSE_DISPATCH_LOOKUP_PRECEDES_DISPATCH_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_LOOKUP_PRECEDES_DISPATCH: "
    "Delegated dispatch to an attached Android runtime MUST look up the "
    "canonical reuse binding (via get_reuse_binding / get_reuse_binding_by_device) "
    "before creating a new AndroidRuntimeDispatchBindingRecord.  Skipping the "
    "lookup violates the persistent reuse contract established in PR-14."
)

REUSE_DISPATCH_ELIGIBILITY_GATE_IS_MANDATORY_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_ELIGIBILITY_GATE_IS_MANDATORY: "
    "After a reuse binding is found, evaluate_reuse_eligibility() MUST be "
    "called before accepting the binding as a valid dispatch surface.  "
    "A binding that was eligible at establishment time may have been "
    "invalidated by a detach / disconnect / disable / invalidate signal "
    "between establishment and dispatch."
)

REUSE_DISPATCH_ELIGIBLE_SURFACE_IS_REUSED_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_ELIGIBLE_SURFACE_IS_REUSED: "
    "When evaluate_reuse_eligibility() returns 'eligible', the existing "
    "attached runtime surface (session_id, device_id, dispatch context) "
    "MUST be reused as the dispatch target.  A new dispatch binding MUST "
    "NOT be created solely to replace an eligible existing binding."
)

REUSE_DISPATCH_INELIGIBLE_BINDING_IS_REJECTED_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_INELIGIBLE_BINDING_IS_REJECTED: "
    "When evaluate_reuse_eligibility() returns 'ineligible', the existing "
    "reuse binding MUST NOT be consumed as a dispatch surface.  The "
    "ReuseDispatchResolution kind MUST be 'rejected' and the caller MUST "
    "NOT send the delegated payload to the stale surface."
)

REUSE_DISPATCH_NO_BINDING_ALLOWS_NEW_DISPATCH_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_NO_BINDING_ALLOWS_NEW_DISPATCH: "
    "When no reuse binding exists for a (session_id, device_id) pair the "
    "ReuseDispatchResolution kind is 'no_binding'.  The caller is free to "
    "establish a new reuse binding and create a new dispatch binding "
    "without violating the reuse contract."
)

REUSE_DISPATCH_WRITE_BACK_IS_MANDATORY_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_WRITE_BACK_IS_MANDATORY: "
    "Every time a new AndroidRuntimeDispatchBindingRecord is created the "
    "caller MUST call write_back_dispatch_binding_id() to register the "
    "new binding_id against the reuse binding.  This keeps the cached "
    "dispatch_binding_id up-to-date for subsequent reuse lookups."
)

REUSE_DISPATCH_INVALIDATION_HARD_STOP_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_INVALIDATION_HARD_STOP: "
    "A reuse binding in 'ineligible' state caused by detach / disconnect / "
    "disable / invalidation MUST NOT be accepted as a reusable dispatch "
    "surface regardless of any caller-supplied override flags.  The "
    "invalidation hard-stop is unconditional."
)

REUSE_DISPATCH_SESSION_LOOKUP_PRECEDES_DEVICE_LOOKUP_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_SESSION_LOOKUP_PRECEDES_DEVICE_LOOKUP: "
    "When both session_id and device_id are provided, the reuse binding "
    "lookup MUST first attempt get_reuse_binding(session_id).  The "
    "device-based fallback (get_reuse_binding_by_device) is used only "
    "when session_id is empty or yields no record."
)

REUSE_DISPATCH_LIVE_SESSION_CROSS_CHECK_IS_OPTIONAL_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_LIVE_SESSION_CROSS_CHECK_IS_OPTIONAL: "
    "resolve_reuse_dispatch_surface() accepts an optional attached_session "
    "argument for live cross-checking via evaluate_reuse_eligibility().  "
    "When absent, eligibility is evaluated from the stored record state only.  "
    "Callers with access to the live session SHOULD provide it."
)

REUSE_DISPATCH_RESOLUTION_IS_IMMUTABLE_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_RESOLUTION_IS_IMMUTABLE: "
    "ReuseDispatchResolution instances are treated as immutable value "
    "objects.  write_back_dispatch_binding_id() returns a new resolution "
    "with updated fields; the caller MUST use the returned object."
)

REUSE_DISPATCH_DETACH_TRIGGERS_INELIGIBLE_RESOLUTION_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_DETACH_TRIGGERS_INELIGIBLE_RESOLUTION: "
    "Any of detach / disconnect / disable / invalidation lifecycle signals "
    "that cause invalidate_reuse_binding() to be called result in the "
    "reuse binding being ineligible.  The next resolve_reuse_dispatch_surface() "
    "call for the same session / device MUST return resolution_kind=rejected, "
    "never resolution_kind=reused."
)

# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL: str = (
    "ATTACHED_RUNTIME_REUSE_DISPATCH::package=17::post-533-main-repo::"
    "canonical-dispatch-consumption-of-attached-runtime-reuse-bindings"
)

# ---------------------------------------------------------------------------
# PR-22 registry consolidation sentinels
# ---------------------------------------------------------------------------

REUSE_DISPATCH_PR22_SENTINEL: str = (
    "ATTACHED_RUNTIME_REUSE_DISPATCH::package=22::post-533-main-repo::"
    "authoritative-registry-consolidation::registry-gates-dispatch-and-reuse"
)

REUSE_DISPATCH_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_REGISTRY_GATE_IS_AUTHORITATIVE_PR22: "
    "Both resolve_reuse_dispatch_surface() and dispatch_with_reuse_binding() MUST "
    "consult the attached runtime session registry as the first authoritative check "
    "before evaluating the reuse binding.  The registry's knowledge of session state "
    "supersedes the reuse binding's own eligibility flag for non-active sessions."
)

REUSE_DISPATCH_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REUSE_DISPATCH_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22: "
    "When the session registry contains an entry for the target session_id and that "
    "entry's state is 'replaced', 'detached', or 'invalidated', both "
    "resolve_reuse_dispatch_surface() and dispatch_with_reuse_binding() MUST return "
    "resolution_kind=rejected immediately without evaluating the reuse binding.  "
    "Absent registry entries (no matching session_id) pass through to the reuse "
    "binding evaluation step as before."
)

# ---------------------------------------------------------------------------
# PR-23 canonical takeover dispatch / delegated fallback sentinels
# ---------------------------------------------------------------------------

REUSE_DISPATCH_PR23_SENTINEL: str = (
    "ATTACHED_RUNTIME_REUSE_DISPATCH::package=23::post-533-main-repo::"
    "canonical-takeover-dispatch-and-delegated-fallback-canonicalization"
)

TAKEOVER_DISPATCH_CONSULTS_REGISTRY_FIRST_PR23_POLICY: str = (
    "REUSE_DISPATCH_POLICY::TAKEOVER_DISPATCH_CONSULTS_REGISTRY_FIRST_PR23: "
    "resolve_takeover_or_fallback_route() MUST consult the attached runtime session "
    "registry as the single first authoritative truth before evaluating the reuse "
    "binding or deciding between takeover and delegated-fallback routes.  No other "
    "session-state source may substitute for or override the registry check."
)

DELEGATED_FALLBACK_REQUIRES_INELIGIBLE_CANONICAL_PATH_PR23_POLICY: str = (
    "REUSE_DISPATCH_POLICY::DELEGATED_FALLBACK_REQUIRES_INELIGIBLE_CANONICAL_PATH_PR23: "
    "The Android delegated fallback route MUST only be selected when the canonical "
    "attached-runtime path is unavailable or ineligible.  Specifically: when the "
    "registry blocks the session (non-active), when the reuse binding is ineligible, "
    "or when no reuse binding exists.  An active, eligible attached-runtime session "
    "MUST always win the takeover dispatch decision."
)

TAKEOVER_DISPATCH_DECISION_IS_DETERMINISTIC_PR23_POLICY: str = (
    "REUSE_DISPATCH_POLICY::TAKEOVER_DISPATCH_DECISION_IS_DETERMINISTIC_PR23: "
    "The outcome of resolve_takeover_or_fallback_route() is fully determined by "
    "(1) the registry's authoritative session state and (2) the reuse binding's "
    "current eligibility.  The same inputs always produce the same TakeoverRouteOutcome. "
    "No ambient state, side-channel caches, or partial session views may influence "
    "the decision."
)

REPLACED_SESSION_CANNOT_WIN_TAKEOVER_DISPATCH_PR23_POLICY: str = (
    "REUSE_DISPATCH_POLICY::REPLACED_SESSION_CANNOT_WIN_TAKEOVER_DISPATCH_PR23: "
    "A session in 'replaced', 'invalidated', 'detached', or any other non-active "
    "registry state MUST NOT produce a TakeoverRouteOutcome of "
    "'active_attached_takeover'.  The registry gate (PR-22) catches these sessions "
    "before reuse-binding evaluation; resolve_takeover_or_fallback_route() MUST "
    "return 'delegated_fallback' for all such sessions regardless of the reuse "
    "binding's stored eligibility flag."
)

STALE_EXECUTION_CONTEXT_CANNOT_ALTER_TAKEOVER_DECISION_PR23_POLICY: str = (
    "REUSE_DISPATCH_POLICY::STALE_EXECUTION_CONTEXT_CANNOT_ALTER_TAKEOVER_DECISION_PR23: "
    "Stale or replayed execution contexts (e.g. old reuse binding ids, outdated "
    "dispatch binding ids, superseded contract ids) MUST NOT alter the takeover "
    "vs delegated-fallback routing decision.  The registry state is always the "
    "most recent truth; stale context is discarded, not promoted."
)

# ---------------------------------------------------------------------------
# ReuseDispatchResolutionKind enum
# ---------------------------------------------------------------------------


class ReuseDispatchResolutionKind(str, Enum):
    """Outcome kind for a reuse dispatch surface resolution attempt.

    reused
        A valid, eligible reuse binding was found.  The caller MUST reuse the
        attached runtime surface identified by the binding (session_id,
        device_id, dispatch context).  No new dispatch binding is required.

    new_binding
        A reuse binding existed but was ineligible **and** the caller chose
        the ``allow_new_on_ineligible=True`` path, OR
        ``dispatch_with_reuse_binding()`` created a fresh dispatch binding on
        behalf of the caller.  The new dispatch binding has been registered
        and its id written back to the reuse binding.

    rejected
        A reuse binding exists but its eligibility status is ``ineligible``
        (e.g. the session was detached, disconnected, disabled, or
        invalidated).  The caller MUST NOT send the delegated payload to the
        stale surface.

    no_binding
        No reuse binding exists for the given (session_id, device_id) pair.
        The caller is free to establish a new reuse binding and dispatch
        normally.
    """

    reused = "reused"
    new_binding = "new_binding"
    rejected = "rejected"
    no_binding = "no_binding"

    @classmethod
    def from_string(cls, value: str) -> "ReuseDispatchResolutionKind":
        """Coerce *value* to a ``ReuseDispatchResolutionKind``; unknown → ``no_binding``."""
        try:
            return cls(str(value).lower().strip())
        except ValueError:
            return cls.no_binding


# ---------------------------------------------------------------------------
# ReuseDispatchResolution dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReuseDispatchResolution:
    """Result of a :func:`resolve_reuse_dispatch_surface` call.

    Attributes
    ----------
    resolution_kind
        The outcome kind for this resolution attempt.
    session_id
        The session id used for the reuse binding lookup.
    device_id
        The device id used for the reuse binding lookup.
    reuse_binding
        The reuse binding record found (may be ineligible when kind is
        ``rejected``).  ``None`` when kind is ``no_binding``.
    dispatch_binding
        The dispatch binding record created or reused by
        :func:`dispatch_with_reuse_binding`.  ``None`` when the resolution
        was performed via :func:`resolve_reuse_dispatch_surface` (which does
        not create dispatch bindings).
    reject_reason
        Human-readable reason for rejection.  Non-empty only when
        ``resolution_kind == rejected``.
    resolved_at
        Epoch timestamp of resolution.
    resolution_id
        Auto-generated UUID for this resolution instance (for traceability).
    metadata
        Caller-supplied freeform dict forwarded through the resolution.
    """

    resolution_kind: ReuseDispatchResolutionKind
    session_id: str
    device_id: str
    reuse_binding: Optional[AttachedRuntimeReuseBindingRecord] = None
    dispatch_binding: Optional[AndroidRuntimeDispatchBindingRecord] = None
    reject_reason: str = ""
    resolved_at: float = field(default_factory=time.time)
    resolution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def is_reusable(self) -> bool:
        """Return ``True`` when the resolution kind is ``reused``."""
        return self.resolution_kind == ReuseDispatchResolutionKind.reused

    def is_rejected(self) -> bool:
        """Return ``True`` when the resolution kind is ``rejected``."""
        return self.resolution_kind == ReuseDispatchResolutionKind.rejected

    def has_no_binding(self) -> bool:
        """Return ``True`` when the resolution kind is ``no_binding``."""
        return self.resolution_kind == ReuseDispatchResolutionKind.no_binding

    def is_new_binding(self) -> bool:
        """Return ``True`` when the resolution kind is ``new_binding``."""
        return self.resolution_kind == ReuseDispatchResolutionKind.new_binding

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "resolution_kind": self.resolution_kind.value,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "reuse_binding_id": (
                self.reuse_binding.identity.reuse_binding_id
                if self.reuse_binding is not None
                else ""
            ),
            "dispatch_binding_id": (
                self.dispatch_binding.identity.binding_id
                if self.dispatch_binding is not None
                else ""
            ),
            "reject_reason": self.reject_reason,
            "resolved_at": self.resolved_at,
            "resolution_id": self.resolution_id,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _check_registry_gate(
    session_id: str,
    device_id: str,
    registry: "Optional[AttachedSessionRegistry]" = None,
) -> "Optional[str]":
    """PR-22 registry gate: return a reject reason if the session is known non-active.

    Consults the attached runtime session registry (with ``active_only=False``)
    to determine whether the target session is in a non-active state.

    Returns
    -------
    str | None
        Non-empty reject reason string when the session is known to be in
        'replaced', 'detached', or 'invalidated' state; ``None`` when the
        registry has no entry for the session (pass-through) or when the
        session is active.
    """
    if not _REGISTRY_AVAILABLE or _lookup_active_session is None:
        return None  # registry unavailable — pass through

    _registry = registry if registry is not None else _get_session_registry()

    entry = None
    if session_id:
        entry = _lookup_active_session(session_id, active_only=False, registry=_registry)

    if entry is None:
        # No registry truth — pass through per
        # REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY
        return None

    if not entry.is_active():
        state_val = entry.attachment_state.value
        return (
            f"registry gate (PR-22): session {session_id!r} is known non-active "
            f"(state={state_val!r}); dispatch/reuse/reconciliation blocked"
        )

    return None  # active — pass through


def resolve_reuse_dispatch_surface(
    session_id: str,
    device_id: str,
    *,
    attached_session: Any = None,
    reuse_runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
    registry: "Optional[AttachedSessionRegistry]" = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ReuseDispatchResolution:
    """Determine whether an eligible reuse surface exists for the given target.

    This is the canonical **pre-dispatch gate** that all delegated dispatch
    paths targeting an attached Android runtime MUST call before creating a
    new :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`.

    Lookup strategy
    ---------------
    0. **PR-22 registry gate**: consult the attached runtime session registry.
       If the registry contains an entry for *session_id* in a non-active state
       (replaced / detached / invalidated) return ``rejected`` immediately.
       Absent registry entries pass through to the reuse binding lookup.
    1. If *session_id* is non-empty, look up via
       :func:`~core.attached_runtime_reuse_binding.get_reuse_binding`.
    2. If that returns ``None`` and *device_id* is non-empty, fall back to
       :func:`~core.attached_runtime_reuse_binding.get_reuse_binding_by_device`.
    3. Evaluate eligibility via
       :func:`~core.attached_runtime_reuse_binding.evaluate_reuse_eligibility`,
       optionally cross-checking against *attached_session*.

    Resolution rules
    ----------------
    * **no_binding** — no record found for (session_id, device_id).
    * **rejected**   — a record was found but is currently ``ineligible``, or
                       the registry gate (PR-22) blocked the non-active session.
    * **reused**     — a record was found and is currently ``eligible``.

    Parameters
    ----------
    session_id
        Attached-runtime session id (PR-7).  Used as the primary lookup key.
    device_id
        Target Android device id.  Used as the fallback lookup key when
        *session_id* is absent or yields no record.
    attached_session
        Optional live
        :class:`~core.attached_runtime_session.AttachedRuntimeSessionRecord`
        for cross-checking (passed through to
        :func:`~core.attached_runtime_reuse_binding.evaluate_reuse_eligibility`).
    reuse_runtime
        Override the process-level reuse-binding ring-buffer singleton
        (test isolation).
    registry
        Optional :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
        override for the PR-22 registry gate (test isolation).  Uses the
        process singleton when ``None``.
    metadata
        Caller-supplied freeform dict forwarded into the returned resolution.

    Returns
    -------
    ReuseDispatchResolution
        Resolution with kind ``reused``, ``rejected``, or ``no_binding``.
        Never ``new_binding`` — that kind is produced only by
        :func:`dispatch_with_reuse_binding`.
    """
    _meta = metadata if metadata is not None else {}

    # --- PR-22 registry gate ---
    _gate_reason = _check_registry_gate(session_id, device_id, registry=registry)
    if _gate_reason:
        return ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.rejected,
            session_id=session_id,
            device_id=device_id,
            reuse_binding=None,
            reject_reason=_gate_reason,
            metadata=_meta,
        )

    # --- Lookup step ---
    record: Optional[AttachedRuntimeReuseBindingRecord] = None

    if session_id:
        record = get_reuse_binding(session_id, runtime=reuse_runtime)

    if record is None and device_id:
        record = get_reuse_binding_by_device(device_id, runtime=reuse_runtime)

    if record is None:
        return ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id=session_id,
            device_id=device_id,
            reuse_binding=None,
            reject_reason="",
            metadata=_meta,
        )

    # --- Eligibility gate ---
    eligibility = evaluate_reuse_eligibility(
        record,
        attached_session=attached_session,
    )

    if eligibility == ReuseEligibilityStatus.ineligible:
        _reason = (
            record.invalidation_reason.value
            if record.invalidation_reason is not None
            else "ineligible"
        )
        return ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.rejected,
            session_id=session_id,
            device_id=device_id,
            reuse_binding=record,
            reject_reason=_reason,
            metadata=_meta,
        )

    # --- Eligible: surface can be reused ---
    return ReuseDispatchResolution(
        resolution_kind=ReuseDispatchResolutionKind.reused,
        session_id=session_id,
        device_id=device_id,
        reuse_binding=record,
        reject_reason="",
        metadata=_meta,
    )


def write_back_dispatch_binding_id(
    resolution: ReuseDispatchResolution,
    dispatch_binding_id: str,
    *,
    reuse_runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> ReuseDispatchResolution:
    """Register *dispatch_binding_id* against the reuse binding in *resolution*.

    Per :data:`REUSE_DISPATCH_WRITE_BACK_IS_MANDATORY_POLICY`, every time a
    new :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
    is created the caller MUST call this function to update the reuse binding's
    cached ``dispatch_binding_id``.

    If *resolution* has no reuse binding (kind ``no_binding``) or if
    *dispatch_binding_id* is empty, the resolution is returned unchanged.

    Parameters
    ----------
    resolution
        The resolution produced by a previous
        :func:`resolve_reuse_dispatch_surface` or
        :func:`dispatch_with_reuse_binding` call.
    dispatch_binding_id
        The ``binding_id`` of the newly created
        :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`.
    reuse_runtime
        Override the process-level reuse-binding ring-buffer singleton
        (test isolation).

    Returns
    -------
    ReuseDispatchResolution
        A new resolution instance (the input is not mutated) with the updated
        ``reuse_binding`` that now carries the registered
        ``dispatch_binding_id``.
    """
    if resolution.reuse_binding is None or not dispatch_binding_id:
        return resolution

    updated_binding = register_dispatch_binding_id(
        resolution.reuse_binding,
        dispatch_binding_id,
        runtime=reuse_runtime,
    )

    return ReuseDispatchResolution(
        resolution_kind=resolution.resolution_kind,
        session_id=resolution.session_id,
        device_id=resolution.device_id,
        reuse_binding=updated_binding,
        dispatch_binding=resolution.dispatch_binding,
        reject_reason=resolution.reject_reason,
        resolved_at=resolution.resolved_at,
        resolution_id=resolution.resolution_id,
        metadata=dict(resolution.metadata),
    )


def dispatch_with_reuse_binding(
    session_id: str,
    device_id: str,
    attached_session: Any,
    handoff_contract: Any,
    execution_tracker: Any,
    *,
    android_host_role: str = "",
    capability_tier: str = "",
    binding_id: Optional[str] = None,
    reuse_runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
    dispatch_runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
    registry: "Optional[AttachedSessionRegistry]" = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ReuseDispatchResolution:
    """Full dispatch flow that consumes the reuse binding before creating a new binding.

    This is the canonical entry-point for delegated dispatch to an attached
    Android runtime that needs to honour the reuse binding contract.

    Flow
    ----
    0. **PR-22 registry gate**: consult the attached runtime session registry.
       If the registry contains an entry for *session_id* in a non-active state
       (replaced / detached / invalidated) return ``rejected`` immediately
       without evaluating the reuse binding or creating a new dispatch binding.
    1. Call :func:`resolve_reuse_dispatch_surface` to determine whether an
       eligible reuse surface already exists.

       * **reused** → return the resolution immediately without creating a
         new dispatch binding (the caller reuses the existing surface).
       * **rejected** → return the rejected resolution immediately.  The
         caller MUST NOT dispatch to the stale surface.
       * **no_binding** → proceed to step 2.

    2. (``no_binding`` path) Call
       :func:`~core.android_runtime_dispatch_binding.resolve_dispatch_binding`
       to create a new :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`.

    3. Call :func:`write_back_dispatch_binding_id` to register the new
       ``binding_id`` against the reuse binding.

    4. Return a ``new_binding`` resolution carrying both the reuse binding
       and the newly created dispatch binding.

    Parameters
    ----------
    session_id
        Attached-runtime session id (PR-7).
    device_id
        Target Android device id.
    attached_session
        Live :class:`~core.attached_runtime_session.AttachedRuntimeSessionRecord`
        (or compatible object) used for eligibility cross-checking and as
        the ``attached_session`` argument to
        :func:`~core.android_runtime_dispatch_binding.resolve_dispatch_binding`.
    handoff_contract
        :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord`
        (or compatible object) passed through to
        :func:`~core.android_runtime_dispatch_binding.resolve_dispatch_binding`.
    execution_tracker
        :class:`~core.delegated_runtime_execution_tracker.DelegatedExecutionTrackingRecord`
        (or compatible object) passed through to
        :func:`~core.android_runtime_dispatch_binding.resolve_dispatch_binding`.
    android_host_role
        Optional Android host role string override.
    capability_tier
        Optional capability tier string override.
    binding_id
        Optional explicit binding id override for the new dispatch binding.
    reuse_runtime
        Override the process-level reuse-binding ring-buffer singleton
        (test isolation).
    dispatch_runtime
        Override the process-level dispatch-binding ring-buffer singleton
        (test isolation).
    registry
        Optional :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
        override for the PR-22 registry gate (test isolation).  Uses the
        process singleton when ``None``.
    metadata
        Caller-supplied freeform dict forwarded into the returned resolution.

    Returns
    -------
    ReuseDispatchResolution
        * ``reused``      — eligible binding found; caller reuses surface.
        * ``rejected``    — binding found but ineligible, or registry gate
                           blocked the non-active session (PR-22).
        * ``new_binding`` — no prior binding; new dispatch binding created and
                           written back.
    """
    _meta = metadata if metadata is not None else {}

    # --- Step 1: resolve reuse surface (includes PR-22 registry gate) ---
    resolution = resolve_reuse_dispatch_surface(
        session_id,
        device_id,
        attached_session=attached_session,
        reuse_runtime=reuse_runtime,
        registry=registry,
        metadata=_meta,
    )

    # Terminal cases — return immediately.
    if resolution.resolution_kind in (
        ReuseDispatchResolutionKind.reused,
        ReuseDispatchResolutionKind.rejected,
    ):
        return resolution

    # --- Step 2: no_binding → create a new dispatch binding ---
    new_dispatch_binding = resolve_dispatch_binding(
        attached_session,
        handoff_contract,
        execution_tracker,
        android_host_role=android_host_role,
        capability_tier=capability_tier,
        binding_id=binding_id,
        metadata=_meta,
        runtime=dispatch_runtime,
    )

    # --- Step 3 & 4: write back and return new_binding resolution ---
    new_binding_id = new_dispatch_binding.identity.binding_id
    updated_resolution = write_back_dispatch_binding_id(
        resolution,
        new_binding_id,
        reuse_runtime=reuse_runtime,
    )

    return ReuseDispatchResolution(
        resolution_kind=ReuseDispatchResolutionKind.new_binding,
        session_id=session_id,
        device_id=device_id,
        reuse_binding=updated_resolution.reuse_binding,
        dispatch_binding=new_dispatch_binding,
        reject_reason="",
        resolved_at=resolution.resolved_at,
        resolution_id=resolution.resolution_id,
        metadata=_meta,
    )


# ---------------------------------------------------------------------------
# PR-23: Canonical takeover/fallback route decision
# ---------------------------------------------------------------------------


class TakeoverRouteOutcome(str, Enum):
    """Outcome of :func:`resolve_takeover_or_fallback_route`.

    Values
    ------
    active_attached_takeover
        The canonical attached-runtime path is active and eligible.  The
        caller MUST route the task to the attached Android runtime session
        and MUST NOT engage the Android delegated fallback path.

    delegated_fallback
        The canonical attached-runtime path is unavailable or ineligible
        (session non-active in the registry, reuse binding ineligible, or
        no reuse binding present).  The caller MUST engage the Android
        delegated fallback path.
    """

    active_attached_takeover = "active_attached_takeover"
    delegated_fallback = "delegated_fallback"

    @classmethod
    def from_string(cls, value: str) -> "TakeoverRouteOutcome":
        """Coerce *value* to a ``TakeoverRouteOutcome``; unknown → ``delegated_fallback``."""
        try:
            return cls(str(value).lower().strip())
        except ValueError:
            return cls.delegated_fallback

    def is_takeover(self) -> bool:
        """Return ``True`` when the outcome is ``active_attached_takeover``."""
        return self == TakeoverRouteOutcome.active_attached_takeover

    def is_fallback(self) -> bool:
        """Return ``True`` when the outcome is ``delegated_fallback``."""
        return self == TakeoverRouteOutcome.delegated_fallback


@dataclass
class TakeoverDispatchDecision:
    """Result of :func:`resolve_takeover_or_fallback_route`.

    Attributes
    ----------
    outcome
        Whether the attached runtime takes over or the delegated fallback
        path is selected.
    session_id
        Session id supplied by the caller.
    device_id
        Device id supplied by the caller.
    reuse_resolution
        The :class:`ReuseDispatchResolution` produced by the internal
        :func:`resolve_reuse_dispatch_surface` call, or ``None`` when the
        registry gate blocked the session before reaching reuse resolution.
    reject_reason
        Non-empty when ``outcome == delegated_fallback``, describing why the
        canonical attached-runtime path was ineligible.
    decided_at
        Epoch timestamp of the decision.
    decision_id
        Auto-generated UUID for this decision (for traceability).
    metadata
        Caller-supplied freeform dict forwarded through the decision.
    """

    outcome: TakeoverRouteOutcome
    session_id: str
    device_id: str
    reuse_resolution: Optional[ReuseDispatchResolution] = None
    reject_reason: str = ""
    decided_at: float = field(default_factory=time.time)
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_takeover(self) -> bool:
        """Return ``True`` when the attached runtime takes over."""
        return self.outcome == TakeoverRouteOutcome.active_attached_takeover

    def is_fallback(self) -> bool:
        """Return ``True`` when the delegated fallback path is selected."""
        return self.outcome == TakeoverRouteOutcome.delegated_fallback

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "outcome": self.outcome.value,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "reuse_resolution_kind": (
                self.reuse_resolution.resolution_kind.value
                if self.reuse_resolution is not None
                else None
            ),
            "reject_reason": self.reject_reason,
            "decided_at": self.decided_at,
            "decision_id": self.decision_id,
            "metadata": dict(self.metadata),
        }


def resolve_takeover_or_fallback_route(
    session_id: str,
    device_id: str,
    *,
    attached_session: Any = None,
    reuse_runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
    registry: "Optional[AttachedSessionRegistry]" = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TakeoverDispatchDecision:
    """Determine whether the attached runtime takes over or the delegated fallback is used.

    This is the **canonical PR-23 takeover/fallback routing gate**.  It makes
    the routing decision explicit and deterministic by:

    1. Consulting the attached runtime session registry as the **sole first
       authority** for session eligibility (via the PR-22 registry gate).
    2. Attempting reuse-surface resolution only when the registry does not
       block the session.
    3. Returning ``active_attached_takeover`` only when a valid, eligible
       reuse surface exists for an active session.
    4. Returning ``delegated_fallback`` for all other cases (non-active
       session, ineligible reuse binding, absent reuse binding).

    The same ``(session_id, device_id, registry_state, reuse_binding_state)``
    inputs always produce the same :class:`TakeoverRouteOutcome` — the
    decision is fully deterministic and does not drift across partial state
    sources.

    Per :data:`REPLACED_SESSION_CANNOT_WIN_TAKEOVER_DISPATCH_PR23_POLICY`,
    replaced / invalidated / detached sessions MUST NOT produce
    ``active_attached_takeover``.  The registry gate enforces this
    unconditionally.

    Parameters
    ----------
    session_id
        Attached-runtime session id.  Used as the primary registry/reuse
        lookup key.
    device_id
        Target Android device id.  Used as the fallback reuse lookup key
        when *session_id* is absent or yields no reuse binding.
    attached_session
        Optional live
        :class:`~core.attached_runtime_session.AttachedRuntimeSessionRecord`
        for eligibility cross-checking inside
        :func:`resolve_reuse_dispatch_surface`.
    reuse_runtime
        Override for the process-level reuse-binding ring-buffer singleton
        (test isolation).
    registry
        Optional
        :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
        override for the PR-22 registry gate (test isolation).
    metadata
        Caller-supplied freeform dict forwarded into the returned decision.

    Returns
    -------
    TakeoverDispatchDecision
        Decision with ``outcome=active_attached_takeover`` when an active,
        eligible attached-runtime session exists; ``outcome=delegated_fallback``
        otherwise.
    """
    _meta = metadata if metadata is not None else {}

    # ------------------------------------------------------------------ #
    # Step 1: Registry gate — the single authoritative first check.       #
    # Non-active sessions (replaced / detached / invalidated) MUST NOT    #
    # produce active_attached_takeover.                                    #
    # ------------------------------------------------------------------ #
    _gate_reason = _check_registry_gate(session_id, device_id, registry=registry)
    if _gate_reason:
        return TakeoverDispatchDecision(
            outcome=TakeoverRouteOutcome.delegated_fallback,
            session_id=session_id,
            device_id=device_id,
            reuse_resolution=None,
            reject_reason=_gate_reason,
            metadata=_meta,
        )

    # ------------------------------------------------------------------ #
    # Step 2: Reuse-surface resolution — determines attached-runtime      #
    # eligibility using the PR-17 / PR-22 reuse-dispatch gate.            #
    # ------------------------------------------------------------------ #
    resolution = resolve_reuse_dispatch_surface(
        session_id,
        device_id,
        attached_session=attached_session,
        reuse_runtime=reuse_runtime,
        registry=registry,
        metadata=_meta,
    )

    # ------------------------------------------------------------------ #
    # Step 3: Determine outcome from the reuse resolution.                #
    # Only a 'reused' resolution produces active_attached_takeover.       #
    # All other outcomes ('rejected', 'no_binding') → delegated_fallback. #
    # ------------------------------------------------------------------ #
    if resolution.resolution_kind == ReuseDispatchResolutionKind.reused:
        return TakeoverDispatchDecision(
            outcome=TakeoverRouteOutcome.active_attached_takeover,
            session_id=session_id,
            device_id=device_id,
            reuse_resolution=resolution,
            reject_reason="",
            metadata=_meta,
        )

    # Rejected or no_binding → delegated fallback.
    _fallback_reason = resolution.reject_reason or (
        f"no eligible attached-runtime reuse surface "
        f"(resolution_kind={resolution.resolution_kind.value!r})"
    )
    return TakeoverDispatchDecision(
        outcome=TakeoverRouteOutcome.delegated_fallback,
        session_id=session_id,
        device_id=device_id,
        reuse_resolution=resolution,
        reject_reason=_fallback_reason,
        metadata=_meta,
    )
