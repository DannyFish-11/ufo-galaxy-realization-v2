"""core/session_authority_contract.py
=======================================
PR-2: Session Authority Contract — Unified Identity and Continuity Binding
for Reconnect, Migration, Continuity, and Handoff.

Background
----------
The Galaxy V2 runtime tracks session state through several inter-related
modules:

* :mod:`core.attached_runtime_session_registry` — the ring-buffer registry of
  :class:`AttachedSessionRegistryEntry` objects; each entry carries the stable
  ``runtime_session_id`` that MUST be preserved across reconnect / re-attach.
* :mod:`core.flow_continuity_coordinator` — the unified decision entry-point
  that classifies every continuity event (attach / reconnect / re-attach /
  V2-restart-recovery / stale-identity / duplicate / partial-result) and
  returns a typed :class:`ContinuityDecisionArtifact`.
* :mod:`core.android_v2_continuity_contract` — machine-checkable joint V2 +
  Android continuity policy for the seven canonical continuity scenario classes.
* :mod:`core.canonical_session_axis` — the cross-layer, cross-repository
  session axis model that maps Android session identifiers to center-side
  canonical identifiers.
* Various reconnect / handoff / migration handlers in the transport and
  gateway layers.

The gap addressed by this module
---------------------------------
While each of the above modules is well-defined internally, there is no single
module that:

1. Declares in machine-checkable form that
   :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry` is
   the **single session authority** for the V2 runtime.
2. Documents that reconnect / migration / continuity / handoff MUST share the
   **same identity contract** — the ``runtime_session_id`` assigned at first
   attach is the stable identity anchor across all state transitions.
3. Declares that :class:`~core.flow_continuity_coordinator.FlowContinuityCoordinator`
   is the **single continuity decision entry-point** and that no path may
   bypass it to produce an independent continuity verdict.
4. Declares the **authority hierarchy** so that implementation decisions
   downstream can be guided by this contract.

This module closes that gap.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Policy-sentinel-first** — every boundary and rule is expressed as a named,
  importable, non-empty string constant for CI, conformance, and observability.
- **Accessor-providing** — lightweight helper functions expose the canonical
  authority instances so callers can use this module as the single import for
  both policy sentinels and runtime instances.
- **Fully serialisable** — :class:`SessionAuthoritySnapshot` produces a stable
  JSON-round-trippable representation of the authority contract state for audit
  and projection.
- **Graceful degradation** — accessor functions never raise; they return None
  with a warning log when the backing module is unavailable.

Authority hierarchy
-------------------
1. :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
   (``ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY``) — owns the
   ``runtime_session_id``, attachment state, invalidation, and supersession
   for every attached Android session.
2. :class:`~core.flow_continuity_coordinator.FlowContinuityCoordinator`
   (``FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY``) — produces the
   canonical continuity decision artifact for every continuity event.  Sub-
   systems MUST use this decision rather than re-deriving the classification.
3. The **shared identity contract** (``SHARED_IDENTITY_CONTRACT_POLICY``) —
   ``runtime_session_id`` is the stable identity anchor.  Reconnect /
   migration / continuity / handoff all operate on the SAME
   ``runtime_session_id``; creating a new one without superseding the old
   entry in the registry is a protocol violation.

Public API
----------
Sentinels
~~~~~~~~~
:data:`SESSION_AUTHORITY_CONTRACT_AUTHORITY`
:data:`SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL`
:data:`ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY`
:data:`FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY`
:data:`SHARED_IDENTITY_CONTRACT_POLICY`
:data:`RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY`
:data:`MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY`
:data:`HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY`
:data:`STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY`
:data:`NO_BYPASS_CONTINUITY_DECISION_POLICY`

Dataclass
~~~~~~~~~
:class:`SessionAuthoritySnapshot`

Functions
~~~~~~~~~
:func:`get_session_authority_registry` → :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry` | None
:func:`get_continuity_coordinator` → :class:`~core.flow_continuity_coordinator.FlowContinuityCoordinator` | None
:func:`build_session_authority_snapshot` → :class:`SessionAuthoritySnapshot`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

SESSION_AUTHORITY_CONTRACT_AUTHORITY: str = (
    "SESSION_AUTHORITY_CONTRACT::"
    "UNIFIED_IDENTITY_AND_CONTINUITY_BINDING_FOR_RECONNECT_MIGRATION_HANDOFF_V1"
)

SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL: str = (
    "SENTINEL::SESSION_AUTHORITY_CONTRACT_PR2: "
    "core.session_authority_contract is the canonical declaration of the "
    "single session authority (AttachedSessionRegistry) and shared identity "
    "contract binding reconnect / migration / continuity / handoff; "
    "package=PR-2::session-authority-contract::session-migration-mesh-closure"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY: str = (
    "POLICY::ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_PR2: "
    "AttachedSessionRegistry (core.attached_runtime_session_registry) is the "
    "SINGLE SESSION AUTHORITY for all attached Android / runtime sessions in "
    "the V2 runtime.  No secondary session store, shadow registry, or local "
    "state accumulator may declare itself the authority for session state.  "
    "Any component that needs to read or write session state MUST do so via "
    "the registry's public API (register_session / reconnect_session / "
    "reattach_session / detach_session / invalidate_session / lookup_active_session)."
)

FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY: str = (
    "POLICY::FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_PR2: "
    "FlowContinuityCoordinator (core.flow_continuity_coordinator) is the "
    "SINGLE CONTINUITY DECISION ENTRY-POINT.  For any continuity event "
    "(attach / reconnect / re-attach after process recreation / V2 restart "
    "recovery / stale identity / duplicate signal / partial result), the "
    "canonical classification MUST be obtained from "
    "FlowContinuityCoordinator.decide_*() and expressed as a "
    "ContinuityDecisionArtifact.  Independent classification by ad-hoc "
    "if/else logic in transport or handler layers is a protocol violation."
)

SHARED_IDENTITY_CONTRACT_POLICY: str = (
    "POLICY::SHARED_IDENTITY_CONTRACT_PR2: "
    "The 'runtime_session_id' field produced by the AttachedSessionRegistry "
    "at first attach is the STABLE IDENTITY ANCHOR across all state transitions "
    "for a given Android session.  Reconnect, migration, continuity, and "
    "handoff operations MUST carry the same runtime_session_id rather than "
    "generating new identifiers for the same logical session.  A new "
    "runtime_session_id is only valid when the old session has been explicitly "
    "superseded via register_session() (which triggers supersession of any "
    "prior active session for the device)."
)

RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY: str = (
    "POLICY::RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_PR2: "
    "When Android reconnects after a transient transport disconnect, the "
    "V2-side handler MUST call reconnect_session() on the registry.  This "
    "restores the entry to 'active' state WITHOUT generating a new "
    "runtime_session_id.  Calling register_session() for a reconnect (instead "
    "of reconnect_session()) would generate a new runtime_session_id and "
    "create a supersession event, which is incorrect for a transient reconnect."
)

MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY: str = (
    "POLICY::MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_PR2: "
    "Session migration (moving a session from one Android device to another, "
    "or reassigning a session to a different process instance) MUST use "
    "register_session() for the new device/instance (which automatically "
    "supersedes the old active session for that device) and explicitly "
    "invalidate or detach the old session via detach_session() / "
    "invalidate_session() on the registry.  Direct manipulation of registry "
    "entries without going through these helpers is a protocol violation."
)

HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY: str = (
    "POLICY::HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_PR2: "
    "Every handoff envelope dispatched to Android MUST carry a session_id that "
    "is resolvable to an active entry in the AttachedSessionRegistry at dispatch "
    "time.  Handoff responses MUST carry the same session_id so the ingress "
    "layer can correlate the response back to the originating registry entry.  "
    "Handoff responses for sessions that are no longer active in the registry "
    "(replaced / invalidated / detached) MUST be rejected non-destructively by "
    "the ingress layer."
)

STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY: str = (
    "POLICY::STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_PR2: "
    "When a session identity (session_id, runtime_session_id, contract_id) "
    "presented by Android is no longer active in the registry, the V2 runtime "
    "MUST reject the signal non-destructively: no canonical state is altered, "
    "no phantom registry entry is created, and the rejection is recorded as an "
    "audit event for observability.  The FlowContinuityCoordinator classifies "
    "this as ContinuityDecision.reject_stale_identity."
)

NO_BYPASS_CONTINUITY_DECISION_POLICY: str = (
    "POLICY::NO_BYPASS_CONTINUITY_DECISION_PR2: "
    "No transport handler, gateway handler, or sub-system component may "
    "produce a continuity classification (new_attachment / continuity_resume / "
    "reject_stale_identity / dedupe_duplicate_signal / preserve_partial_and_wait / "
    "fail_closed) independently of FlowContinuityCoordinator.  "
    "All continuity classifications MUST be obtained by calling the appropriate "
    "FlowContinuityCoordinator.decide_*() method and consulting the returned "
    "ContinuityDecisionArtifact."
)

# ---------------------------------------------------------------------------
# SessionAuthoritySnapshot dataclass
# ---------------------------------------------------------------------------


@dataclass
class SessionAuthoritySnapshot:
    """Point-in-time snapshot of the session authority contract state.

    Attributes
    ----------
    registry_available:
        True when AttachedSessionRegistry singleton is accessible.
    coordinator_available:
        True when FlowContinuityCoordinator singleton is accessible.
    active_session_count:
        Number of active sessions in the registry at snapshot time.
        -1 when the registry is unavailable.
    pending_continuity_count:
        Number of recent continuity decision artifacts in the coordinator.
        -1 when the coordinator is unavailable.
    authority_policy_count:
        Number of policy sentinels in this module's __all__.
    """

    registry_available: bool = False
    coordinator_available: bool = False
    active_session_count: int = -1
    pending_continuity_count: int = -1
    authority_policy_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "registry_available": self.registry_available,
            "coordinator_available": self.coordinator_available,
            "active_session_count": self.active_session_count,
            "pending_continuity_count": self.pending_continuity_count,
            "authority_policy_count": self.authority_policy_count,
        }


# ---------------------------------------------------------------------------
# Accessor helpers
# ---------------------------------------------------------------------------


def get_session_authority_registry():
    """Return the process-level singleton :class:`AttachedSessionRegistry`.

    Returns the canonical session authority.  Returns None on import failure.
    """
    try:
        from core.attached_runtime_session_registry import get_session_registry
        return get_session_registry()
    except Exception as exc:
        logger.warning(
            "session_authority_contract: get_session_authority_registry unavailable: %s",
            exc,
        )
        return None


def get_continuity_coordinator():
    """Return the process-level singleton :class:`FlowContinuityCoordinator`.

    Returns the canonical continuity decision authority.  Returns None on
    import failure.
    """
    try:
        from core.flow_continuity_coordinator import get_flow_continuity_coordinator
        return get_flow_continuity_coordinator()
    except Exception as exc:
        logger.warning(
            "session_authority_contract: get_continuity_coordinator unavailable: %s",
            exc,
        )
        return None


_POLICY_SENTINEL_NAMES = [
    "SESSION_AUTHORITY_CONTRACT_AUTHORITY",
    "SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL",
    "ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY",
    "FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY",
    "SHARED_IDENTITY_CONTRACT_POLICY",
    "RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY",
    "MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY",
    "HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY",
    "STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY",
    "NO_BYPASS_CONTINUITY_DECISION_POLICY",
]


def build_session_authority_snapshot() -> SessionAuthoritySnapshot:
    """Build a point-in-time snapshot of the session authority contract state.

    Returns
    -------
    SessionAuthoritySnapshot
        Never raises.
    """
    snapshot = SessionAuthoritySnapshot()

    # Count policy sentinels defined in this module (explicit list for robustness)
    snapshot.authority_policy_count = len(_POLICY_SENTINEL_NAMES)

    # Registry availability
    registry = get_session_authority_registry()
    if registry is not None:
        snapshot.registry_available = True
        try:
            active = registry.list_all_active()
            snapshot.active_session_count = len(active) if active is not None else 0
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            snapshot.active_session_count = 0

    # Coordinator availability
    coordinator = get_continuity_coordinator()
    if coordinator is not None:
        snapshot.coordinator_available = True
        try:
            recent = coordinator.list_recent(n=100)
            snapshot.pending_continuity_count = len(recent) if recent is not None else 0
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            snapshot.pending_continuity_count = 0

    return snapshot


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "SESSION_AUTHORITY_CONTRACT_AUTHORITY",
    "SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL",
    "ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY",
    "FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY",
    "SHARED_IDENTITY_CONTRACT_POLICY",
    "RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY",
    "MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY",
    "HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY",
    "STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY",
    "NO_BYPASS_CONTINUITY_DECISION_POLICY",
    # Dataclass
    "SessionAuthoritySnapshot",
    # Functions
    "get_session_authority_registry",
    "get_continuity_coordinator",
    "build_session_authority_snapshot",
]
