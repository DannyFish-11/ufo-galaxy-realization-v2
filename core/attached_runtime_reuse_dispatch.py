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


def resolve_reuse_dispatch_surface(
    session_id: str,
    device_id: str,
    *,
    attached_session: Any = None,
    reuse_runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ReuseDispatchResolution:
    """Determine whether an eligible reuse surface exists for the given target.

    This is the canonical **pre-dispatch gate** that all delegated dispatch
    paths targeting an attached Android runtime MUST call before creating a
    new :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`.

    Lookup strategy
    ---------------
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
    * **rejected**   — a record was found but is currently ``ineligible``.
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
    metadata: Optional[Dict[str, Any]] = None,
) -> ReuseDispatchResolution:
    """Full dispatch flow that consumes the reuse binding before creating a new binding.

    This is the canonical entry-point for delegated dispatch to an attached
    Android runtime that needs to honour the reuse binding contract.

    Flow
    ----
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
    metadata
        Caller-supplied freeform dict forwarded into the returned resolution.

    Returns
    -------
    ReuseDispatchResolution
        * ``reused``      — eligible binding found; caller reuses surface.
        * ``rejected``    — binding found but ineligible; caller MUST NOT dispatch.
        * ``new_binding`` — no prior binding; new dispatch binding created and
                           written back.
    """
    _meta = metadata if metadata is not None else {}

    # --- Step 1: resolve reuse surface ---
    resolution = resolve_reuse_dispatch_surface(
        session_id,
        device_id,
        attached_session=attached_session,
        reuse_runtime=reuse_runtime,
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
