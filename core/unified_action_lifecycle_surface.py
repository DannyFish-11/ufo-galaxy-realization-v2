"""core/unified_action_lifecycle_surface.py
=============================================
PR-UAS: Unified Action Lifecycle Surface for dual-repo (V2 + Android).

Establishes a single, runtime-consumable canonical surface that covers the
complete action lifecycle across both V2 and the Android device runtime:

  dispatch → acceptance → execution → result → blocker →
  confirmation_needed → closure

Prior to this module, Android-side execution results were processed by
individual gateway handlers (handoff_v2_result, task_lifecycle, etc.) and
absorbed into V2 canonical state independently.  This meant:

- Android result existed at the *ingress* level but not as a first-class
  object in any unified foreground surface.
- blocker / confirmation_needed / closure status was scattered across
  handlers, operator truth, and projection layers.
- No single structure captured the full cross-repo action lifecycle in a
  form that the default response composition path could consume.

This module closes that gap by providing:

1. :class:`ActionLifecyclePhase` — canonical phase enum covering every
   named step of the dual-repo action lifecycle.

2. :class:`ActionOrigin` — identifies whether an action originated from
   the V2 center, an Android device, or a cross-repo handoff.

3. :class:`UnifiedActionLifecycleSurface` — canonical runtime surface
   dataclass.  Fields:

   - Standard identity: ``action_id``, ``session_id``, ``task_id``,
     ``handoff_id``, ``device_id``.
   - Phase: ``phase`` (:class:`ActionLifecyclePhase`).
   - Origin: ``origin`` (:class:`ActionOrigin`).
   - Acceptance: ``accepted`` (bool), ``acceptance_tag``.
   - Execution: ``execution_state`` (string progress token).
   - **Android-side result as first-class object**: ``android_result``
     (dict or None) — set when an Android execution result has been
     received and is authoritative; ``android_result_authority`` marks it
     as the canonical execution outcome, not a secondary interpretation.
   - Blocker convergence: ``blocker`` (dict or None), ``blocker_reason``,
     ``blocker_kind``.
   - Confirmation convergence: ``confirmation_needed`` (bool),
     ``confirmation_context`` (dict or None).
   - Closure: ``closure_state`` (``open`` / ``handoff_pending`` /
     ``closed``), ``closure_reason``.
   - Cross-repo lifecycle mapping: ``cross_repo_lifecycle_map`` — dict
     that maps Android gateway events (acceptance, handoff_ack,
     handoff_result, reconciliation_signal) to their canonical lifecycle
     phase names.
   - Surface metadata: ``surface_version``, ``surface_origin_module``.

4. :func:`build_from_dispatch` — create a surface entry when an action is
   dispatched (phase = ``dispatched``).

5. :func:`build_from_handoff_response` — build/update a surface from a
   :class:`~core.android_handoff_v2_response_ingress.HandoffV2ResponseOutcome`;
   makes the Android-side result a first-class object.

6. :func:`build_from_normalizer_outcome` — build/update a surface from an
   :class:`~core.android_result_normalizer.AndroidResultNormalizerOutcome`.

7. :func:`apply_blocker` — converge a blocker into the surface.

8. :func:`apply_confirmation` — converge a confirmation_needed signal.

9. :func:`close_surface` — mark the surface as closed with a reason.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Runtime-consumable** — the surface is a plain dataclass with a
  ``to_dict()`` method; it can be serialised and embedded in any gateway
  ACK response or default response composition result.
- **Android result is a first-class object** — ``android_result`` is a
  named top-level field; it is never nested inside a V2 post-processing
  wrapper.
- **Single canonical blocker / confirmation surface** — ``blocker`` and
  ``confirmation_needed`` live on the surface itself, not in scattered
  handler-local dicts.
- **Cross-repo lifecycle mapping is explicit** — ``cross_repo_lifecycle_map``
  names each Android gateway event and its lifecycle phase equivalent so
  tooling and tests can assert on cross-repo coverage without parsing
  free-form text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

UNIFIED_ACTION_LIFECYCLE_SURFACE_SENTINEL: str = (
    "UNIFIED_ACTION_LIFECYCLE_SURFACE::core.unified_action_lifecycle_surface::"
    "pr-uas::dual-repo-action-result-blocker-confirmation-surface::"
    "android-result-first-class::blocker-confirmation-convergence"
)


# ---------------------------------------------------------------------------
# Canonical cross-repo lifecycle map
# ---------------------------------------------------------------------------

#: Maps Android gateway event names to their canonical lifecycle phase names.
#: This mapping is the authoritative cross-repo lifecycle mapping; any code
#: that needs to know which Android event corresponds to which V2 lifecycle
#: phase should import this dict rather than re-deriving the mapping.
CROSS_REPO_LIFECYCLE_MAP: Dict[str, str] = {
    # Android dispatches a handoff to V2; V2 side marks action as dispatched.
    "handoff_dispatch": "dispatched",
    # Android ACKs receipt of the handoff — execution is about to start.
    "handoff_ack": "accepted",
    # Android sends an in-progress status / delegated execution signal.
    "delegated_execution_signal": "executing",
    # Android sends a successful execution result.
    "handoff_result": "result_received",
    # Android sends a goal execution result (business result type).
    "goal_execution_result": "result_received",
    # Android task result (task-level business result).
    "task_result": "result_received",
    # Android sends a failure result.
    "handoff_failure": "result_received",
    # Android sends an acceptance report (explicit acceptance evidence).
    "acceptance_report": "accepted",
    # Android sends a reconciliation signal — forces V2-side truth reconcile.
    "reconciliation_signal": "closed",
    # Android sends a takeover response — handoff is returned to V2.
    "takeover_response": "closed",
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ActionLifecyclePhase(str, Enum):
    """Canonical phases of the dual-repo action lifecycle."""

    unknown = "unknown"
    dispatched = "dispatched"
    accepted = "accepted"
    executing = "executing"
    result_received = "result_received"
    blocked = "blocked"
    confirmation_needed = "confirmation_needed"
    closed = "closed"


class ActionOrigin(str, Enum):
    """Origin of an action in the dual-repo system."""

    unknown = "unknown"
    v2_center = "v2_center"
    android_device = "android_device"
    cross_repo = "cross_repo"


class ClosureState(str, Enum):
    """Closure state of an action lifecycle entry."""

    open = "open"
    handoff_pending = "handoff_pending"
    closed = "closed"


# ---------------------------------------------------------------------------
# Surface dataclass
# ---------------------------------------------------------------------------


@dataclass
class UnifiedActionLifecycleSurface:
    """Canonical runtime surface for a single dual-repo action lifecycle entry.

    All fields beyond ``action_id`` are optional so the surface can be
    constructed incrementally (e.g., ``dispatched`` phase has no result yet).

    The surface is designed to be embedded in:
    - Gateway ACK responses returned to the Android runtime.
    - Default ``DesktopPresenceRuntime.handle_request()`` result composition.
    - Any canonical runtime output payload.

    It is intentionally **not** a projection or operator-only artefact: it
    lives in the foreground response path.
    """

    # --- Identity ---
    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    task_id: str = ""
    handoff_id: str = ""
    device_id: str = ""

    # --- Phase / Origin ---
    phase: ActionLifecyclePhase = ActionLifecyclePhase.unknown
    origin: ActionOrigin = ActionOrigin.unknown

    # --- Acceptance ---
    accepted: bool = False
    acceptance_tag: str = ""

    # --- Execution state ---
    execution_state: str = ""

    # --- Android-side result as first-class object ---
    #: Raw execution result payload from the Android device.  This field makes
    #: Android-side result a first-class object in the unified surface rather
    #: than a secondary value absorbed into V2 post-processing.
    android_result: Optional[Dict[str, Any]] = None
    #: Marks the authority of ``android_result``.  When non-empty the Android
    #: device is the authoritative execution reporter for this action; V2 is
    #: the canonical *ingress* and *routing* authority, not the result author.
    android_result_authority: str = ""

    # --- Blocker convergence ---
    #: Canonical blocker payload.  When non-None, this action is blocked.
    blocker: Optional[Dict[str, Any]] = None
    blocker_reason: str = ""
    blocker_kind: str = ""

    # --- Confirmation convergence ---
    confirmation_needed: bool = False
    confirmation_context: Optional[Dict[str, Any]] = None

    # --- Closure ---
    closure_state: ClosureState = ClosureState.open
    closure_reason: str = ""

    # --- Cross-repo lifecycle mapping ---
    #: Maps the Android gateway event that drove the last phase transition to
    #: its canonical phase name.  Populated by ``build_from_handoff_response``
    #: and ``build_from_normalizer_outcome`` so the surface carries its own
    #: provenance.
    cross_repo_lifecycle_map: Dict[str, str] = field(
        default_factory=lambda: dict(CROSS_REPO_LIFECYCLE_MAP)
    )
    #: The specific Android message type that produced the current phase.
    last_android_event: str = ""

    # --- Surface metadata ---
    surface_version: str = "1.0"
    surface_origin_module: str = "core.unified_action_lifecycle_surface"

    # ------------------------------------------------------------------ #
    # Public helpers                                                       #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the surface to a plain dict for embedding in payloads."""
        return {
            "action_id": self.action_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "handoff_id": self.handoff_id,
            "device_id": self.device_id,
            "phase": self.phase.value,
            "origin": self.origin.value,
            "accepted": self.accepted,
            "acceptance_tag": self.acceptance_tag,
            "execution_state": self.execution_state,
            "android_result": self.android_result,
            "android_result_authority": self.android_result_authority,
            "blocker": self.blocker,
            "blocker_reason": self.blocker_reason,
            "blocker_kind": self.blocker_kind,
            "confirmation_needed": self.confirmation_needed,
            "confirmation_context": self.confirmation_context,
            "closure_state": self.closure_state.value,
            "closure_reason": self.closure_reason,
            "cross_repo_lifecycle_map": self.cross_repo_lifecycle_map,
            "last_android_event": self.last_android_event,
            "surface_version": self.surface_version,
            "surface_origin_module": self.surface_origin_module,
        }

    def is_android_result_first_class(self) -> bool:
        """Return True iff an Android-side result has been set as first-class."""
        return self.android_result is not None and bool(self.android_result_authority)

    def has_blocker(self) -> bool:
        """Return True iff a canonical blocker is present."""
        return self.blocker is not None or bool(self.blocker_reason)

    def is_closed(self) -> bool:
        """Return True iff the surface has been closed."""
        return self.closure_state == ClosureState.closed


# ---------------------------------------------------------------------------
# Factory / builder functions
# ---------------------------------------------------------------------------


def build_from_dispatch(
    *,
    action_id: str = "",
    session_id: str = "",
    task_id: str = "",
    handoff_id: str = "",
    device_id: str = "",
    origin: ActionOrigin = ActionOrigin.v2_center,
) -> UnifiedActionLifecycleSurface:
    """Create a surface entry when an action is initially dispatched.

    Sets phase to ``dispatched`` and closure_state to ``open``.
    """
    return UnifiedActionLifecycleSurface(
        action_id=action_id or str(uuid.uuid4()),
        session_id=session_id,
        task_id=task_id,
        handoff_id=handoff_id,
        device_id=device_id,
        phase=ActionLifecyclePhase.dispatched,
        origin=origin,
        closure_state=ClosureState.open,
    )


def build_from_handoff_response(
    outcome: Any,
    *,
    action_id: str = "",
    session_id: str = "",
) -> UnifiedActionLifecycleSurface:
    """Build a surface entry from a HandoffV2ResponseOutcome.

    This function makes the Android-side execution result a first-class
    object: ``android_result`` is populated from the response payload and
    ``android_result_authority`` is set to ``"android_device"`` so callers
    can distinguish Android-reported results from V2-computed results.

    Parameters
    ----------
    outcome:
        A :class:`~core.android_handoff_v2_response_ingress.HandoffV2ResponseOutcome`
        instance.  Accepts any duck-typed object with ``.envelope``,
        ``.was_correlated``, and ``.callback_invoked`` attributes.
    action_id:
        Optional stable action ID.  Defaults to a new UUID.
    session_id:
        Optional session ID override.
    """
    env = getattr(outcome, "envelope", None)
    if env is None:
        return UnifiedActionLifecycleSurface(
            action_id=action_id or str(uuid.uuid4()),
            session_id=session_id,
            phase=ActionLifecyclePhase.unknown,
            origin=ActionOrigin.android_device,
        )

    _raw_response_kind = getattr(env, "response_kind", None)
    response_kind_val = "unknown"
    if _raw_response_kind is not None:
        # Normalise pydantic/enum value to string
        if hasattr(_raw_response_kind, "value"):
            response_kind_val = str(_raw_response_kind.value)
        else:
            response_kind_val = str(_raw_response_kind)

    # Map android response_kind to cross-repo lifecycle phase
    _msg_type_for_mapping = {
        "ack": "handoff_ack",
        "result": "handoff_result",
        "failure": "handoff_failure",
    }.get(response_kind_val, response_kind_val)
    phase_name = CROSS_REPO_LIFECYCLE_MAP.get(_msg_type_for_mapping, "unknown")
    try:
        phase = ActionLifecyclePhase(phase_name)
    except ValueError:
        phase = ActionLifecyclePhase.unknown

    is_terminal = bool(getattr(env, "is_terminal", False))
    was_correlated = bool(getattr(outcome, "was_correlated", False))

    # Acceptance: handoff_ack → accepted
    accepted = response_kind_val == "ack" and was_correlated
    acceptance_tag = "android_handoff_ack" if accepted else ""

    # Android-side result payload — first-class object
    android_result: Optional[Dict[str, Any]] = None
    android_result_authority = ""
    if response_kind_val in {"result", "failure"} and was_correlated:
        raw_payload = getattr(env, "payload", None) or {}
        android_result = {
            "response_kind": response_kind_val,
            "handoff_id": str(getattr(env, "handoff_id", "") or ""),
            "task_id": str(getattr(env, "task_id", "") or ""),
            "device_id": str(getattr(env, "device_id", "") or ""),
            "payload": raw_payload if isinstance(raw_payload, dict) else {},
            "is_terminal": is_terminal,
            "callback_invoked": bool(getattr(outcome, "callback_invoked", False)),
        }
        android_result_authority = "android_device"

    # Closure
    if is_terminal:
        closure_state = ClosureState.closed
        closure_reason = f"android_handoff_{response_kind_val}"
    elif accepted:
        closure_state = ClosureState.handoff_pending
        closure_reason = "android_ack_received"
    else:
        closure_state = ClosureState.open
        closure_reason = ""

    return UnifiedActionLifecycleSurface(
        action_id=action_id or str(uuid.uuid4()),
        session_id=session_id or str(getattr(env, "session_id", "") or ""),
        task_id=str(getattr(env, "task_id", "") or ""),
        handoff_id=str(getattr(env, "handoff_id", "") or ""),
        device_id=str(getattr(env, "device_id", "") or ""),
        phase=phase,
        origin=ActionOrigin.android_device,
        accepted=accepted,
        acceptance_tag=acceptance_tag,
        execution_state="terminal" if is_terminal else "in_progress" if accepted else "unknown",
        android_result=android_result,
        android_result_authority=android_result_authority,
        closure_state=closure_state,
        closure_reason=closure_reason,
        last_android_event=_msg_type_for_mapping,
    )


def build_from_normalizer_outcome(
    outcome: Any,
    *,
    action_id: str = "",
    session_id: str = "",
    device_id: str = "",
) -> UnifiedActionLifecycleSurface:
    """Build a surface entry from an AndroidResultNormalizerOutcome.

    Handles all three normalizer routing paths: participant_truth,
    signal_reconcile, and handoff_response.

    Parameters
    ----------
    outcome:
        An :class:`~core.android_result_normalizer.AndroidResultNormalizerOutcome`.
    action_id:
        Optional stable action ID.
    session_id:
        Optional session ID override.
    device_id:
        Optional device ID.
    """
    msg_type = str(getattr(outcome, "message_type", "") or "")
    was_normalized = bool(getattr(outcome, "was_normalized", False))
    was_deduplicated = bool(getattr(outcome, "was_deduplicated", False))
    source_message_id = str(getattr(outcome, "source_message_id", "") or "")
    committed_identity = str(getattr(outcome, "committed_terminal_identity", "") or "")

    # Derive phase from message type using canonical map
    phase_name = CROSS_REPO_LIFECYCLE_MAP.get(msg_type, "unknown")
    try:
        phase = ActionLifecyclePhase(phase_name)
    except ValueError:
        phase = ActionLifecyclePhase.unknown

    # If dedup hit, treat as closed
    if was_deduplicated:
        phase = ActionLifecyclePhase.closed

    # Android-side result: populate from handoff_response_outcome if present
    handoff_resp_outcome = getattr(outcome, "handoff_response_outcome", None)
    android_result: Optional[Dict[str, Any]] = None
    android_result_authority = ""

    if handoff_resp_outcome is not None and was_normalized:
        env = getattr(handoff_resp_outcome, "envelope", None)
        if env is not None:
            _raw_rk = getattr(env, "response_kind", None)
            if _raw_rk is not None:
                response_kind_val = str(_raw_rk.value) if hasattr(_raw_rk, "value") else str(_raw_rk)
            else:
                response_kind_val = "unknown"
            if response_kind_val in {"result", "failure"}:
                android_result = {
                    "response_kind": response_kind_val,
                    "handoff_id": str(getattr(env, "handoff_id", "") or ""),
                    "task_id": str(getattr(env, "task_id", "") or ""),
                    "device_id": str(getattr(env, "device_id", "") or ""),
                    "payload": getattr(env, "payload", {}) or {},
                    "message_type": msg_type,
                    "committed_terminal_identity": committed_identity,
                }
                android_result_authority = "android_device"

    # Participant truth outcome — use as result if business result type
    pt_outcome = getattr(outcome, "participant_truth_outcome", None)
    if android_result is None and pt_outcome is not None and was_normalized:
        if msg_type in {"task_result", "goal_execution_result"}:
            android_result = {
                "message_type": msg_type,
                "source_message_id": source_message_id,
                "committed_terminal_identity": committed_identity,
                "participant_truth_ingested": True,
            }
            android_result_authority = "android_device"

    # Closure
    if phase == ActionLifecyclePhase.closed or was_deduplicated:
        closure_state = ClosureState.closed
        closure_reason = "android_terminal_normalizer" if not was_deduplicated else "dedup_already_committed"
    elif phase == ActionLifecyclePhase.result_received:
        closure_state = ClosureState.closed
        closure_reason = f"android_{msg_type}_result_received"
    else:
        closure_state = ClosureState.open
        closure_reason = ""

    return UnifiedActionLifecycleSurface(
        action_id=action_id or str(uuid.uuid4()),
        session_id=session_id,
        task_id="",
        handoff_id="",
        device_id=device_id,
        phase=phase,
        origin=ActionOrigin.android_device,
        android_result=android_result,
        android_result_authority=android_result_authority,
        closure_state=closure_state,
        closure_reason=closure_reason,
        last_android_event=msg_type,
    )


def apply_blocker(
    surface: UnifiedActionLifecycleSurface,
    *,
    blocker: Dict[str, Any],
    blocker_reason: str = "",
    blocker_kind: str = "",
) -> UnifiedActionLifecycleSurface:
    """Converge a blocker into the surface, advancing phase to ``blocked``.

    Returns the mutated surface (in-place modification for ergonomics).
    """
    surface.blocker = blocker
    surface.blocker_reason = blocker_reason or blocker.get("reason", "")
    surface.blocker_kind = blocker_kind or blocker.get("kind", "")
    surface.phase = ActionLifecyclePhase.blocked
    return surface


def apply_confirmation(
    surface: UnifiedActionLifecycleSurface,
    *,
    confirmation_context: Optional[Dict[str, Any]] = None,
    reason: str = "",
) -> UnifiedActionLifecycleSurface:
    """Mark the surface as needing operator/user confirmation.

    Advances phase to ``confirmation_needed`` and sets
    ``confirmation_needed=True``.

    Returns the mutated surface.
    """
    surface.confirmation_needed = True
    surface.confirmation_context = confirmation_context or {"reason": reason}
    surface.phase = ActionLifecyclePhase.confirmation_needed
    return surface


def close_surface(
    surface: UnifiedActionLifecycleSurface,
    *,
    reason: str = "",
) -> UnifiedActionLifecycleSurface:
    """Mark the surface as closed.

    Returns the mutated surface.
    """
    surface.closure_state = ClosureState.closed
    surface.closure_reason = reason or "explicit_close"
    surface.phase = ActionLifecyclePhase.closed
    return surface


def derive_visible_action(surface: UnifiedActionLifecycleSurface) -> Dict[str, Any]:
    """Derive a lightweight foreground-facing action payload from the surface."""
    phase = surface.phase.value
    if surface.phase == ActionLifecyclePhase.blocked:
        status_feedback = "blocked"
    elif surface.phase == ActionLifecyclePhase.confirmation_needed:
        status_feedback = "confirmation_required"
    elif surface.phase == ActionLifecyclePhase.accepted:
        status_feedback = "accepted"
    elif surface.phase in {ActionLifecyclePhase.result_received, ActionLifecyclePhase.closed}:
        status_feedback = "result_received"
    elif surface.phase == ActionLifecyclePhase.executing:
        status_feedback = "executing"
    else:
        status_feedback = "dispatched"

    return {
        "action_id": surface.action_id,
        "phase": phase,
        "origin": surface.origin.value,
        "accepted": surface.accepted,
        "blocker": surface.blocker,
        "blocker_reason": surface.blocker_reason,
        "confirmation_needed": surface.confirmation_needed,
        "closure_state": surface.closure_state.value,
        "status_feedback": status_feedback,
    }


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "UNIFIED_ACTION_LIFECYCLE_SURFACE_SENTINEL",
    "CROSS_REPO_LIFECYCLE_MAP",
    "ActionLifecyclePhase",
    "ActionOrigin",
    "ClosureState",
    "UnifiedActionLifecycleSurface",
    "build_from_dispatch",
    "build_from_handoff_response",
    "build_from_normalizer_outcome",
    "apply_blocker",
    "apply_confirmation",
    "close_surface",
    "derive_visible_action",
]
