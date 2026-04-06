"""core/attached_runtime_reuse_dispatch.py
==========================================
PR package 17 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Dispatch Consumption of Attached-Runtime Reuse Bindings.

This module is the **canonical authority** for integrating the persistent
attached-runtime reuse binding layer (PR-14) into the real delegated dispatch
path on the MAIN repo side.

Background
----------
PR-14 established ``core.attached_runtime_reuse_binding`` with a full data
model, eligibility rules, and ring-buffer persistence.  PR-11 established
``core.android_runtime_dispatch_binding`` for per-dispatch binding identity.
While both layers are complete, the real delegated dispatch path has not yet
been wired to *consume* the reuse binding before dispatching — meaning
``establish_reuse_binding`` / ``evaluate_reuse_eligibility`` / etc. are
available but not guaranteed to be called on every actual dispatch.

This module closes the gap by providing a canonical "reuse-aware dispatch"
path that:

1. Performs a reuse binding lookup (``get_reuse_binding`` or
   ``get_reuse_binding_by_device``) before any dispatch decision.
2. Evaluates eligibility via ``evaluate_reuse_eligibility`` using the live
   attached session (if provided) or the persisted binding record.
3. When the binding is **eligible**: reuses the existing attached runtime
   surface — consuming stable targeting context (session_id, device_id,
   posture, role, tier) from the binding without re-deriving it — and creates
   a fresh ``AndroidRuntimeDispatchBindingRecord`` for the new dispatch.
4. When the binding is **ineligible** (invalidated by detach / disconnect /
   disable / lifecycle signal) or absent: returns a ``rejected`` or
   ``new_binding`` decision so the caller can take the appropriate fallback
   action (create a new session, re-establish the binding, or fail gracefully).
5. After every successfully created ``AndroidRuntimeDispatchBindingRecord``,
   writes the new ``binding_id`` back to the reuse binding record via
   ``register_dispatch_binding_id`` so the reuse binding always carries the
   latest dispatch anchor.
6. Guarantees that invalidated reuse bindings are never consumed: the
   ``evaluate_reuse_eligibility`` gate is unconditionally traversed before
   any dispatch work proceeds.

Public API summary
------------------
Enums::

    DispatchReuseDecision  — reuse / new_binding / rejected

Dataclasses::

    ReuseSurfaceResolution  — output of the lookup + eligibility evaluation step
    ReuseDispatchOutcome    — output of the full reuse-aware dispatch step

Functions::

    resolve_reuse_surface(session_id, device_id, *, ...) -> ReuseSurfaceResolution
    execute_reuse_dispatch(session_id, device_id, *, ...)  -> ReuseDispatchOutcome

Ten policy sentinels documenting canonical dispatch consumption rules.

One PR sentinel (``ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL``).

Design principles
-----------------
- **Additive only** — does not modify any prior module.
- **Reuse before dispatch** — lookup + eligibility evaluation MUST precede
  any dispatch binding creation.
- **Single write-back path** — ``register_dispatch_binding_id`` is called
  exactly once per successful dispatch binding, inside this module.
- **Invalidated bindings are never consumed** — the eligibility gate is
  unconditional; an ineligible record always produces a ``rejected`` decision.
- **Fallback-friendly** — callers that receive ``new_binding`` or ``rejected``
  can decide their own recovery strategy without this module mandating one.
- **Runtime-injectable** — all ring-buffer singletons can be overridden for
  test isolation.

PR package numbering
--------------------
Package 17 of the post-533 dual-repo runtime unification master plan.
MAIN-repo side only.
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
    ReuseInvalidationReason,
    evaluate_reuse_eligibility,
    get_reuse_binding,
    get_reuse_binding_by_device,
    register_dispatch_binding_id,
)
from core.android_runtime_dispatch_binding import (
    AndroidRuntimeDispatchBindingRecord,
    AndroidRuntimeDispatchBindingRuntime,
    AndroidRuntimeBindingState,
    create_android_dispatch_binding,
)

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY: str = (
    "core.attached_runtime_reuse_dispatch::PR17::canonical-dispatch-"
    "consumption-of-attached-runtime-reuse-bindings"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

REUSE_DISPATCH_LOOKUP_BEFORE_DISPATCH_POLICY: str = (
    "POLICY::REUSE_DISPATCH_LOOKUP_BEFORE_DISPATCH: the canonical delegated "
    "dispatch path for attached Android runtimes MUST perform a reuse binding "
    "lookup (get_reuse_binding or get_reuse_binding_by_device) before any "
    "dispatch binding creation or WebSocket send.  Skipping the lookup is a "
    "policy violation that breaks the reuse guarantee."
)

REUSE_DISPATCH_ELIGIBILITY_GATE_IS_UNCONDITIONAL_POLICY: str = (
    "POLICY::REUSE_DISPATCH_ELIGIBILITY_GATE_IS_UNCONDITIONAL: "
    "evaluate_reuse_eligibility() MUST be called for every candidate reuse "
    "binding, regardless of whether the binding was recently established or "
    "previously used for a successful dispatch.  The gate is unconditional "
    "because lifecycle signals (detach / disconnect / disable / invalidate) "
    "can arrive between dispatches."
)

REUSE_DISPATCH_ELIGIBLE_REUSES_SURFACE_POLICY: str = (
    "POLICY::REUSE_DISPATCH_ELIGIBLE_REUSES_SURFACE: when the reuse binding "
    "is eligible the dispatch path MUST consume the stable targeting identity "
    "(session_id, device_id, source_runtime_posture, coordination_role, "
    "android_host_role, capability_tier) from the reuse binding record rather "
    "than re-deriving it from the attached session or scheduling records."
)

REUSE_DISPATCH_INELIGIBLE_DOES_NOT_DISPATCH_POLICY: str = (
    "POLICY::REUSE_DISPATCH_INELIGIBLE_DOES_NOT_DISPATCH: when the reuse "
    "binding is ineligible (e.g. invalidated by detach / disconnect / disable "
    "/ invalidate) the canonical dispatch path MUST NOT create a dispatch "
    "binding or send work to the invalidated surface.  The caller receives a "
    "'rejected' decision and is responsible for recovery."
)

REUSE_DISPATCH_WRITE_BACK_DISPATCH_BINDING_ID_POLICY: str = (
    "POLICY::REUSE_DISPATCH_WRITE_BACK_DISPATCH_BINDING_ID: after every "
    "successfully created AndroidRuntimeDispatchBindingRecord, the dispatch "
    "path MUST call register_dispatch_binding_id() to write the new "
    "binding_id back to the reuse binding.  This ensures the reuse binding "
    "always carries the latest dispatch anchor for recovery / reuse tracking."
)

REUSE_DISPATCH_FALLBACK_ON_MISSING_BINDING_POLICY: str = (
    "POLICY::REUSE_DISPATCH_FALLBACK_ON_MISSING_BINDING: when no reuse "
    "binding exists for the requested session_id / device_id the dispatch "
    "path returns a 'new_binding' decision.  Callers that require reuse MUST "
    "establish a reuse binding (via establish_reuse_binding) before retrying. "
    "Callers that can proceed without reuse may create a bare dispatch binding."
)

REUSE_DISPATCH_INVALIDATED_BINDING_NOT_CONSUMED_POLICY: str = (
    "POLICY::REUSE_DISPATCH_INVALIDATED_BINDING_NOT_CONSUMED: invalidated "
    "reuse bindings (reuse_eligibility_status == ineligible) MUST never be "
    "used as dispatch targets.  The eligibility gate produces a 'rejected' "
    "decision for any ineligible binding, and the dispatch binding creation "
    "step is skipped entirely."
)

REUSE_DISPATCH_SESSION_LOOKUP_PRIORITY_POLICY: str = (
    "POLICY::REUSE_DISPATCH_SESSION_LOOKUP_PRIORITY: when both session_id "
    "and device_id are provided, the lookup first tries get_reuse_binding "
    "by session_id.  If no record is found, a fallback lookup is performed "
    "by device_id via get_reuse_binding_by_device.  This ensures the most "
    "precise match (session-scoped) takes priority over device-scoped."
)

REUSE_DISPATCH_DISPATCH_BINDING_USES_REUSE_IDENTITY_POLICY: str = (
    "POLICY::REUSE_DISPATCH_DISPATCH_BINDING_USES_REUSE_IDENTITY: the "
    "AndroidRuntimeDispatchBindingRecord created during reuse dispatch MUST "
    "carry the session_id, device_id, source_runtime_posture, "
    "coordination_role, android_host_role, and capability_tier from the "
    "reuse binding record — not from the caller's raw inputs — to preserve "
    "stable targeting identity across multiple dispatches."
)

REUSE_DISPATCH_OUTCOME_IS_INSPECTABLE_POLICY: str = (
    "POLICY::REUSE_DISPATCH_OUTCOME_IS_INSPECTABLE: ReuseDispatchOutcome "
    "MUST carry sufficient information for callers to observe the decision "
    "(was_reused, decision, rejection_reason), the binding records involved "
    "(reuse_binding, dispatch_binding, updated_reuse_binding), and the final "
    "targeting identity (session_id, device_id) that was used."
)

REUSE_DISPATCH_REATTACH_ESTABLISHES_NEW_SURFACE_POLICY: str = (
    "POLICY::REUSE_DISPATCH_REATTACH_ESTABLISHES_NEW_SURFACE: after a "
    "session is detached / disconnected / disabled, the reuse binding is "
    "invalidated.  To resume delegated dispatch the caller MUST establish a "
    "fresh reuse binding (via establish_reuse_binding) for the new session "
    "before calling execute_reuse_dispatch.  This module does not implicitly "
    "re-establish bindings."
)

ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL: str = (
    "ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL::package=17 "
    "canonical-attached-runtime-reuse-dispatch-post-533-main-repo-pr17-v1"
)

_ALL_POLICY_SENTINELS = (
    ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY,
    REUSE_DISPATCH_LOOKUP_BEFORE_DISPATCH_POLICY,
    REUSE_DISPATCH_ELIGIBILITY_GATE_IS_UNCONDITIONAL_POLICY,
    REUSE_DISPATCH_ELIGIBLE_REUSES_SURFACE_POLICY,
    REUSE_DISPATCH_INELIGIBLE_DOES_NOT_DISPATCH_POLICY,
    REUSE_DISPATCH_WRITE_BACK_DISPATCH_BINDING_ID_POLICY,
    REUSE_DISPATCH_FALLBACK_ON_MISSING_BINDING_POLICY,
    REUSE_DISPATCH_INVALIDATED_BINDING_NOT_CONSUMED_POLICY,
    REUSE_DISPATCH_SESSION_LOOKUP_PRIORITY_POLICY,
    REUSE_DISPATCH_DISPATCH_BINDING_USES_REUSE_IDENTITY_POLICY,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_TIER_UNKNOWN: str = "unknown"


# ---------------------------------------------------------------------------
# DispatchReuseDecision
# ---------------------------------------------------------------------------


class DispatchReuseDecision(str, Enum):
    """Canonical dispatch reuse decision after lookup and eligibility evaluation.

    reuse
        A reuse binding was found and evaluated as eligible.  The dispatch path
        should consume the binding's targeting context and create a fresh
        :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
        anchored to the same session / device surface.

    new_binding
        No reuse binding exists for the requested session_id / device_id.  The
        caller must establish a new reuse binding (via
        ``establish_reuse_binding``) and retry, or create a bare dispatch
        binding without reuse guarantees.

    rejected
        A reuse binding was found but is ineligible (e.g. invalidated by a
        detach / disconnect / disable / invalidate lifecycle signal).  The
        caller must not dispatch to this surface; recovery requires
        re-establishing the session and a fresh reuse binding.
    """

    reuse = "reuse"
    new_binding = "new_binding"
    rejected = "rejected"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "DispatchReuseDecision" = None,
    ) -> "DispatchReuseDecision":
        """Return the enum member matching *value*, or *default* / ``rejected``."""
        if default is None:
            default = cls.rejected
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default


# ---------------------------------------------------------------------------
# ReuseSurfaceResolution
# ---------------------------------------------------------------------------


@dataclass
class ReuseSurfaceResolution:
    """Output of :func:`resolve_reuse_surface` — the lookup + eligibility step.

    Attributes
    ----------
    decision
        The :class:`DispatchReuseDecision` resulting from the lookup and
        eligibility evaluation.
    reuse_binding
        The binding record that was found, if any.  ``None`` when
        ``decision`` is ``new_binding``.
    rejection_reason
        Human-readable string describing why dispatch was blocked.  Empty
        when ``decision`` is ``reuse``.
    applied_policy
        The policy sentinel string that caused the block, or empty string.
    session_id
        The session id that was evaluated.
    device_id
        The device id that was evaluated.
    resolved_at
        Unix timestamp when the resolution was produced.
    """

    decision: DispatchReuseDecision = DispatchReuseDecision.rejected
    reuse_binding: Optional[AttachedRuntimeReuseBindingRecord] = None
    rejection_reason: str = ""
    applied_policy: str = ""
    session_id: str = ""
    device_id: str = ""
    resolved_at: float = field(default_factory=time.time)

    def is_reuse(self) -> bool:
        """Return True iff the decision is ``reuse``."""
        return self.decision == DispatchReuseDecision.reuse

    def is_rejected(self) -> bool:
        """Return True iff the decision is ``rejected``."""
        return self.decision == DispatchReuseDecision.rejected

    def is_new_binding(self) -> bool:
        """Return True iff the decision is ``new_binding``."""
        return self.decision == DispatchReuseDecision.new_binding

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "decision": self.decision.value,
            "reuse_binding_id": (
                self.reuse_binding.identity.reuse_binding_id
                if self.reuse_binding is not None
                else None
            ),
            "rejection_reason": self.rejection_reason,
            "applied_policy": self.applied_policy,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "resolved_at": self.resolved_at,
        }


# ---------------------------------------------------------------------------
# ReuseDispatchOutcome
# ---------------------------------------------------------------------------


@dataclass
class ReuseDispatchOutcome:
    """Output of :func:`execute_reuse_dispatch` — the full reuse-aware dispatch.

    Attributes
    ----------
    decision
        The :class:`DispatchReuseDecision` that governed this dispatch.
    reuse_binding
        The reuse binding that was consumed (eligible case) or evaluated
        (rejected case).  ``None`` when ``decision`` is ``new_binding``.
    dispatch_binding
        The :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
        created for this dispatch.  ``None`` when ``decision`` is ``rejected``
        or ``new_binding``.
    updated_reuse_binding
        The updated reuse binding record after ``dispatch_binding_id`` was
        written back via ``register_dispatch_binding_id``.  ``None`` when no
        dispatch binding was created (rejected / new_binding cases) or when
        the write-back was skipped because the binding is ineligible.
    was_reused
        ``True`` iff the dispatch successfully consumed an eligible reuse
        binding and created a dispatch binding anchored to the same session /
        device surface.
    rejection_reason
        Human-readable string describing why dispatch was blocked.  Empty
        when ``was_reused`` is True.
    session_id
        The session id used for dispatch (from the reuse binding when
        ``was_reused`` is True, otherwise the caller's input).
    device_id
        The device id used for dispatch.
    dispatched_at
        Unix timestamp when this outcome was produced.
    """

    decision: DispatchReuseDecision = DispatchReuseDecision.rejected
    reuse_binding: Optional[AttachedRuntimeReuseBindingRecord] = None
    dispatch_binding: Optional[AndroidRuntimeDispatchBindingRecord] = None
    updated_reuse_binding: Optional[AttachedRuntimeReuseBindingRecord] = None
    was_reused: bool = False
    rejection_reason: str = ""
    session_id: str = ""
    device_id: str = ""
    dispatched_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "decision": self.decision.value,
            "was_reused": self.was_reused,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "reuse_binding_id": (
                self.reuse_binding.identity.reuse_binding_id
                if self.reuse_binding is not None
                else None
            ),
            "dispatch_binding_id": (
                self.dispatch_binding.identity.binding_id
                if self.dispatch_binding is not None
                else None
            ),
            "updated_dispatch_binding_id": (
                self.updated_reuse_binding.dispatch_binding_id
                if self.updated_reuse_binding is not None
                else None
            ),
            "rejection_reason": self.rejection_reason,
            "dispatched_at": self.dispatched_at,
        }


# ---------------------------------------------------------------------------
# Public API — resolve_reuse_surface
# ---------------------------------------------------------------------------


def resolve_reuse_surface(
    session_id: str,
    device_id: str = "",
    *,
    attached_session: Any = None,
    reuse_runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> ReuseSurfaceResolution:
    """Look up and evaluate a reuse binding for *session_id* (or *device_id*).

    This is the canonical "before-dispatch" step.  It performs:

    1. A reuse binding lookup by ``session_id`` via :func:`get_reuse_binding`.
       If no record is found and ``device_id`` is provided, a fallback lookup
       via :func:`get_reuse_binding_by_device` is attempted
       (:data:`REUSE_DISPATCH_SESSION_LOOKUP_PRIORITY_POLICY`).

    2. An unconditional eligibility evaluation via
       :func:`evaluate_reuse_eligibility`
       (:data:`REUSE_DISPATCH_ELIGIBILITY_GATE_IS_UNCONDITIONAL_POLICY`).

    Parameters
    ----------
    session_id
        Attached-runtime session id (PR-7).  Primary lookup key.
    device_id
        Target Android device id.  Used as fallback lookup key when
        ``session_id`` yields no result.
    attached_session
        Optional live attached session object.  When provided it is forwarded
        to :func:`evaluate_reuse_eligibility` for richer eligibility decisions
        (e.g. cross-checking the live attachment state).  The object must
        expose ``attachment_state`` and ``source_runtime_posture`` attributes.
    reuse_runtime
        Override the process-level ring-buffer singleton (test isolation).

    Returns
    -------
    ReuseSurfaceResolution
        A :class:`ReuseSurfaceResolution` with the lookup outcome and
        eligibility decision.
    """
    sid = (session_id or "").strip()
    did = (device_id or "").strip()

    # Step 1 — lookup by session_id (primary), then by device_id (fallback).
    record: Optional[AttachedRuntimeReuseBindingRecord] = None
    if sid:
        record = get_reuse_binding(sid, runtime=reuse_runtime)
    if record is None and did:
        record = get_reuse_binding_by_device(did, runtime=reuse_runtime)

    if record is None:
        return ReuseSurfaceResolution(
            decision=DispatchReuseDecision.new_binding,
            reuse_binding=None,
            rejection_reason=(
                "No reuse binding found for session_id="
                + repr(sid)
                + " device_id="
                + repr(did)
            ),
            applied_policy=REUSE_DISPATCH_FALLBACK_ON_MISSING_BINDING_POLICY,
            session_id=sid,
            device_id=did,
        )

    # Step 2 — unconditional eligibility evaluation.
    eligibility = evaluate_reuse_eligibility(record, attached_session=attached_session)

    if eligibility == ReuseEligibilityStatus.eligible:
        return ReuseSurfaceResolution(
            decision=DispatchReuseDecision.reuse,
            reuse_binding=record,
            rejection_reason="",
            applied_policy="",
            session_id=record.identity.session_id,
            device_id=record.identity.device_id,
        )

    # Ineligible — determine a useful rejection message.
    reason = record.invalidation_reason
    rejection_msg = (
        f"Reuse binding ineligible: invalidation_reason={reason.value} "
        f"reuse_binding_id={record.identity.reuse_binding_id}"
    )
    return ReuseSurfaceResolution(
        decision=DispatchReuseDecision.rejected,
        reuse_binding=record,
        rejection_reason=rejection_msg,
        applied_policy=REUSE_DISPATCH_INELIGIBLE_DOES_NOT_DISPATCH_POLICY,
        session_id=record.identity.session_id,
        device_id=record.identity.device_id,
    )


# ---------------------------------------------------------------------------
# Public API — execute_reuse_dispatch
# ---------------------------------------------------------------------------


def execute_reuse_dispatch(
    session_id: str,
    device_id: str = "",
    *,
    contract_id: str = "",
    tracker_id: str = "",
    trace_id: Optional[str] = None,
    coordination_role: str = "",
    android_host_role: str = "",
    capability_tier: str = "",
    source_runtime_posture: str = _POSTURE_JOIN_RUNTIME,
    attached_session: Any = None,
    reuse_runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
    dispatch_runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> ReuseDispatchOutcome:
    """Execute the canonical reuse-binding-aware delegated dispatch path.

    This function is the **authoritative integration point** between the
    persistent reuse binding layer (PR-14) and the dispatch binding layer
    (PR-11).  It enforces the full sequence mandated by PR-17:

    1. Call :func:`resolve_reuse_surface` to perform the lookup and
       eligibility evaluation before any dispatch work
       (:data:`REUSE_DISPATCH_LOOKUP_BEFORE_DISPATCH_POLICY`).

    2. If the decision is ``reuse``: extract stable targeting context from the
       reuse binding record (:data:`REUSE_DISPATCH_ELIGIBLE_REUSES_SURFACE_POLICY`)
       and create a new
       :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
       via :func:`~core.android_runtime_dispatch_binding.create_android_dispatch_binding`
       (:data:`REUSE_DISPATCH_DISPATCH_BINDING_USES_REUSE_IDENTITY_POLICY`).

    3. After creating a dispatch binding, call
       :func:`~core.attached_runtime_reuse_binding.register_dispatch_binding_id`
       to write the new ``binding_id`` back to the reuse binding
       (:data:`REUSE_DISPATCH_WRITE_BACK_DISPATCH_BINDING_ID_POLICY`).

    4. If the decision is ``rejected`` (ineligible binding): return the
       outcome without creating a dispatch binding
       (:data:`REUSE_DISPATCH_INELIGIBLE_DOES_NOT_DISPATCH_POLICY`).

    5. If the decision is ``new_binding`` (no binding found): return the
       outcome so the caller can establish a binding and retry.

    Parameters
    ----------
    session_id
        Attached-runtime session id (PR-7).  Primary lookup key.
    device_id
        Target Android device id.  Fallback lookup key and used in dispatch
        binding creation when the reuse binding does not override it.
    contract_id
        Handoff contract id (PR-9) to embed in the dispatch binding.
    tracker_id
        Execution tracking record id (PR-10) to embed in the dispatch binding.
    trace_id
        Distributed trace id.  Auto-generated if not provided.
    coordination_role
        Coordination role override.  When the reuse binding is consumed its
        ``coordination_role`` field takes precedence over this parameter.
    android_host_role
        Android host role override.  Overridden by the reuse binding value
        when the binding is consumed.
    capability_tier
        Capability tier override.  Overridden by the reuse binding value when
        the binding is consumed.
    source_runtime_posture
        Source posture override.  Overridden by the reuse binding value when
        the binding is consumed.
    attached_session
        Optional live attached session object forwarded to
        :func:`evaluate_reuse_eligibility`.
    reuse_runtime
        Override the reuse binding ring-buffer singleton (test isolation).
    dispatch_runtime
        Override the dispatch binding ring-buffer singleton (test isolation).

    Returns
    -------
    ReuseDispatchOutcome
        A :class:`ReuseDispatchOutcome` describing the decision made, the
        binding records involved, and the targeting identity used.
    """
    _trace_id = trace_id or str(uuid.uuid4())

    # Step 1 — resolve the reuse surface (lookup + eligibility gate).
    resolution = resolve_reuse_surface(
        session_id,
        device_id,
        attached_session=attached_session,
        reuse_runtime=reuse_runtime,
    )

    # Step 2a — no binding found: caller must establish one before retrying.
    if resolution.decision == DispatchReuseDecision.new_binding:
        return ReuseDispatchOutcome(
            decision=DispatchReuseDecision.new_binding,
            reuse_binding=None,
            dispatch_binding=None,
            updated_reuse_binding=None,
            was_reused=False,
            rejection_reason=resolution.rejection_reason,
            session_id=resolution.session_id or (session_id or "").strip(),
            device_id=resolution.device_id or (device_id or "").strip(),
        )

    # Step 2b — binding found but ineligible: do NOT dispatch.
    if resolution.decision == DispatchReuseDecision.rejected:
        return ReuseDispatchOutcome(
            decision=DispatchReuseDecision.rejected,
            reuse_binding=resolution.reuse_binding,
            dispatch_binding=None,
            updated_reuse_binding=None,
            was_reused=False,
            rejection_reason=resolution.rejection_reason,
            session_id=resolution.session_id,
            device_id=resolution.device_id,
        )

    # Step 3 — binding is eligible: consume stable targeting identity.
    binding = resolution.reuse_binding
    _session_id = binding.identity.session_id
    _device_id = binding.identity.device_id
    _posture = binding.source_runtime_posture or _POSTURE_JOIN_RUNTIME
    _role = binding.coordination_role or coordination_role or ""
    _android_role = binding.android_host_role or android_host_role or ""
    _tier = binding.capability_tier or capability_tier or _TIER_UNKNOWN

    # Step 4 — create a new dispatch binding anchored to the reuse surface.
    dispatch_rec = create_android_dispatch_binding(
        session_id=_session_id,
        device_id=_device_id,
        source_runtime_posture=_posture,
        coordination_role=_role,
        android_host_role=_android_role,
        capability_tier=_tier,
        contract_id=contract_id or "",
        tracker_id=tracker_id or "",
        trace_id=_trace_id,
        runtime=dispatch_runtime,
    )

    # Step 5 — write the new dispatch_binding_id back to the reuse binding.
    _binding_id = dispatch_rec.identity.binding_id
    updated_reuse = register_dispatch_binding_id(
        binding,
        _binding_id,
        runtime=reuse_runtime,
    )

    return ReuseDispatchOutcome(
        decision=DispatchReuseDecision.reuse,
        reuse_binding=binding,
        dispatch_binding=dispatch_rec,
        updated_reuse_binding=updated_reuse,
        was_reused=True,
        rejection_reason="",
        session_id=_session_id,
        device_id=_device_id,
    )
