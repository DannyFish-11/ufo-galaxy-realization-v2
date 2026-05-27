"""core/subject_facing_foreground.py
=====================================
PR-SFF: Subject-Facing Foreground — primary organizing object for the default
user-visible response.

This module introduces :class:`SubjectFacingForeground`: the canonical
subject-facing foreground object that makes the subject's lifecycle state
(presence, action, result, blocker, confirmation) the **primary organizing
structure** of the default user-visible response.

Prior to this module, the default user-facing response was organized around:

- ``response`` — a scattered text string produced by the runtime/LLM
- ``visible_action_surface`` — a supplementary struct built from runtime fields
- ``problem_execution_spine`` — a control-plane diagnostic object always
  exposed to users regardless of whether they needed it

None of these objects is organized around the *subject itself*.  The user saw
the runtime's output, not the subject's state.

``SubjectFacingForeground`` reorganizes the default foreground around the
subject lifecycle::

    subject_state (presence mode)
        ↓
    action_phase  (what lifecycle phase the subject is in)
        ↓
    [current_action | blocker | confirmation | result]
        ↓
    foreground_status  (primary human-facing status string)

Key design differences from ``visible_action_surface``
------------------------------------------------------
- ``visible_action_surface`` is a *runtime field collection*:
  it gathers present runtime fields into a dict.
- ``SubjectFacingForeground`` is a *subject lifecycle object*:
  it is organized around what the subject IS, IS DOING, is BLOCKED by,
  is COMPLETING, and needs CONFIRMED — not around which runtime fields
  happen to exist.
- ``blocker`` and ``confirmation`` are **primary foreground events** here,
  not optional metadata attachments.
- ``foreground_status`` is derived from the subject lifecycle, not from
  runtime text output.
- ``is_subject_primary = True`` signals to consumers that this object —
  not scattered response fields — is the canonical foreground primary object.

This module is **additive only** and does not modify any existing module
directly.  :func:`build_subject_facing_foreground` is called from
``core/routes/chat.py`` after the existing
``_apply_hidden_visible_boundary()`` pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

SUBJECT_FACING_FOREGROUND_SENTINEL: str = (
    "SUBJECT_FACING_FOREGROUND::core.subject_facing_foreground::"
    "pr-sff::subject-lifecycle-primary-foreground::"
    "presence-action-result-blocker-confirmation-organized"
)

# ---------------------------------------------------------------------------
# Foreground event type constants
# ---------------------------------------------------------------------------

#: Subject is actively performing an action (executing / dispatched / accepted).
FOREGROUND_EVENT_ACTIVE = "active"
#: Subject is blocked and cannot proceed without external resolution.
FOREGROUND_EVENT_BLOCKED = "blocked"
#: Subject is waiting for user/operator confirmation before proceeding.
FOREGROUND_EVENT_CONFIRMING = "confirming"
#: Subject completed an action successfully.
FOREGROUND_EVENT_COMPLETED = "completed"
#: Subject is present and ready (no active action).
FOREGROUND_EVENT_READY = "ready"
#: Subject is in a lifecycle transition (e.g. liminal → manifest).
FOREGROUND_EVENT_TRANSITIONING = "transitioning"


# ---------------------------------------------------------------------------
# SubjectFacingForeground dataclass
# ---------------------------------------------------------------------------


@dataclass
class SubjectFacingForeground:
    """Primary organizing object for the default user-visible foreground.

    This is the canonical subject-facing foreground.  It organizes everything
    the user sees around the subject's lifecycle state, not around the
    runtime's internal output.

    Attributes
    ----------
    subject_state:
        Current presence mode of the subject (e.g. ``"liminal"``,
        ``"manifest"``, ``"silent"``).  This is the primary
        existence/readiness signal for the user.
    action_phase:
        Canonical action lifecycle phase name (from
        :class:`~core.unified_action_lifecycle_surface.ActionLifecyclePhase`).
        Tells the user which lifecycle stage the subject is in.
    foreground_event:
        The primary foreground event type (one of the ``FOREGROUND_EVENT_*``
        constants defined in this module).  This is the single most-reduced
        statement of what the subject is doing right now.
    foreground_status:
        Human-facing primary status string derived from the subject lifecycle.
        Unlike the raw ``response`` text, this is **derived from structured
        lifecycle state**, not from runtime text output.
    current_action:
        Concise description of the action the subject is currently performing
        or last performed.  Empty string when not applicable.
    result:
        Subject's action result state: ``"completed"``, ``"failed"``, or
        empty string when no result is available yet.
    result_summary:
        Brief human-facing result description.  Empty when not completed.
    blocker:
        Blocker payload dict when the subject is blocked.  ``None`` otherwise.
        When present, this is a **primary foreground event**, not a metadata
        attachment.
    blocker_reason:
        Human-facing blocker reason string.  Empty when not blocked.
    confirmation:
        Confirmation context dict when user confirmation is required.
        ``None`` otherwise.  When present, this is a **primary foreground
        event**.
    confirmation_reason:
        Human-facing description of why confirmation is needed.  Empty when
        confirmation is not needed.
    is_subject_primary:
        Always ``True``.  Signals to consumers that this object — not
        scattered runtime response fields — is the canonical foreground
        primary object.  Consumers should prefer the subject lifecycle fields
        over scattered ``response`` text or raw metadata fields.
    foreground_version:
        Schema version for forward-compat checking.  Currently ``"1.0"``.
    """

    # --- Subject existence / presence ---
    subject_state: str = "unknown"

    # --- Action lifecycle ---
    action_phase: str = "unknown"
    foreground_event: str = FOREGROUND_EVENT_READY

    # --- Primary human-facing status (lifecycle-derived, not runtime text) ---
    foreground_status: str = ""

    # --- Current action expression ---
    current_action: str = ""

    # --- Result ---
    result: str = ""
    result_summary: str = ""

    # --- Blocker — primary foreground event when present ---
    blocker: Optional[Dict[str, Any]] = None
    blocker_reason: str = ""

    # --- Confirmation — primary foreground event when present ---
    confirmation: Optional[Dict[str, Any]] = None
    confirmation_reason: str = ""

    # --- Subject primary signal ---
    is_subject_primary: bool = True

    # --- Schema versioning ---
    foreground_version: str = "1.0"

    # ------------------------------------------------------------------ #
    # Public helpers                                                       #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for embedding in response payloads."""
        return {
            "subject_state": self.subject_state,
            "action_phase": self.action_phase,
            "foreground_event": self.foreground_event,
            "foreground_status": self.foreground_status,
            "current_action": self.current_action,
            "result": self.result,
            "result_summary": self.result_summary,
            "blocker": self.blocker,
            "blocker_reason": self.blocker_reason,
            "confirmation": self.confirmation,
            "confirmation_reason": self.confirmation_reason,
            "is_subject_primary": self.is_subject_primary,
            "foreground_version": self.foreground_version,
        }

    def is_blocked(self) -> bool:
        """Return True iff a blocker is the primary foreground event."""
        return bool(self.blocker or self.blocker_reason)

    def needs_confirmation(self) -> bool:
        """Return True iff user confirmation is the primary foreground event."""
        return self.confirmation is not None or bool(self.confirmation_reason)

    def is_completed(self) -> bool:
        """Return True iff subject has completed an action."""
        return self.result == "completed"


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def build_subject_facing_foreground(
    *,
    visible_action_surface: Dict[str, Any],
    action_lifecycle_surface: Optional[Dict[str, Any]] = None,
    foreground_response: str = "",
) -> SubjectFacingForeground:
    """Build a :class:`SubjectFacingForeground` from the canonical surface dicts.

    This is the canonical factory.  It **reorganizes** existing structured
    information around the subject lifecycle without adding new computation or
    round-trips.  It consumes:

    - ``visible_action_surface`` — produced by
      ``_apply_hidden_visible_boundary()`` in ``core/routes/chat.py``
    - ``action_lifecycle_surface`` — produced by
      :class:`~core.unified_action_lifecycle_surface.UnifiedActionLifecycleSurface`
      in ``core/desktop_presence_runtime.py``

    The result is a :class:`SubjectFacingForeground` where blocker and
    confirmation are **primary events** (they drive ``foreground_event`` and
    ``foreground_status`` before any other consideration), and where
    ``foreground_status`` is lifecycle-derived rather than runtime-text-derived.

    Parameters
    ----------
    visible_action_surface:
        The ``visible_action_surface`` dict already produced by the boundary
        pass.  Must be a dict; pass ``{}`` if unavailable.
    action_lifecycle_surface:
        The ``action_lifecycle_surface`` dict from
        ``DesktopPresenceRuntime.handle_request()`` result.  Optional.
    foreground_response:
        The foreground response string already determined by the boundary
        function.  Used as last-resort fallback for ``foreground_status``.
    """
    lifecycle = action_lifecycle_surface or {}

    # ── 1. Subject state (presence mode) ───────────────────────────────────
    subject_state = (
        str(visible_action_surface.get("current_presence_mode", "")).strip()
        or "unknown"
    )

    # ── 2. Action phase ─────────────────────────────────────────────────────
    action_phase = (
        str(
            visible_action_surface.get("lifecycle_phase", "")
            or lifecycle.get("phase", "")
        ).strip()
        or "unknown"
    )

    # ── 3. Blocker (primary event — evaluated before action/result) ─────────
    blocker_reason = str(
        visible_action_surface.get("blocker_summary", "")
        or lifecycle.get("blocker_reason", "")
    ).strip()
    blocker_dict: Optional[Dict[str, Any]] = visible_action_surface.get(
        "blocker"
    ) or lifecycle.get("blocker")
    if blocker_dict is not None and not isinstance(blocker_dict, dict):
        blocker_dict = {"raw": str(blocker_dict)}
    if blocker_reason and blocker_dict is None:
        blocker_dict = {"reason": blocker_reason}

    # ── 4. Confirmation (primary event — evaluated before action/result) ────
    confirmation_needed = bool(visible_action_surface.get("confirmation_needed", False))
    confirmation_dict: Optional[Dict[str, Any]] = lifecycle.get("confirmation_context")
    if confirmation_dict is not None and not isinstance(confirmation_dict, dict):
        confirmation_dict = {"raw": str(confirmation_dict)}
    confirmation_reason = ""
    if confirmation_needed and confirmation_dict is None:
        confirmation_dict = {}
        confirmation_reason = "user_confirmation_required"

    # ── 5. Current action expression ────────────────────────────────────────
    current_action = str(
        visible_action_surface.get("action_trace_summary", "")
        or visible_action_surface.get("lifecycle_status_feedback", "")
    ).strip()

    # ── 6. Result ───────────────────────────────────────────────────────────
    action_state = str(visible_action_surface.get("current_action_state", "")).strip()
    if action_state == "completed":
        result = "completed"
        result_summary = str(
            visible_action_surface.get("result_artifacts_summary", "")
            or visible_action_surface.get("lightweight_status_feedback", "")
        ).strip()
    elif action_state == "failed":
        result = "failed"
        result_summary = str(
            visible_action_surface.get("lightweight_status_feedback", "")
        ).strip()
    else:
        result = ""
        result_summary = ""

    # ── 7. Foreground event (single most-reduced subject state expression) ──
    # Blocker and confirmation take priority — they are blocking lifecycle
    # events that require immediate user attention.
    if blocker_reason or blocker_dict:
        foreground_event = FOREGROUND_EVENT_BLOCKED
    elif confirmation_needed:
        foreground_event = FOREGROUND_EVENT_CONFIRMING
    elif action_state == "completed":
        foreground_event = FOREGROUND_EVENT_COMPLETED
    elif action_state in {"executing", "accepted"}:
        foreground_event = FOREGROUND_EVENT_ACTIVE
    elif subject_state in {"liminal", "manifest"}:
        foreground_event = FOREGROUND_EVENT_TRANSITIONING
    else:
        foreground_event = FOREGROUND_EVENT_READY

    # ── 8. Foreground status (lifecycle-derived, not runtime text) ──────────
    # Derived from subject lifecycle state — not from the raw runtime text
    # response.  This is the structural difference from scattered response text.
    if blocker_reason:
        foreground_status = f"blocked: {blocker_reason}"
    elif confirmation_needed:
        foreground_status = "awaiting_confirmation"
    elif result == "completed":
        foreground_status = "completed"
    elif result == "failed":
        foreground_status = "failed"
    elif action_state == "executing":
        foreground_status = "executing"
    elif action_state == "accepted":
        foreground_status = "accepted"
    elif subject_state in {"liminal", "manifest"}:
        foreground_status = subject_state
    else:
        # Last-resort fallback — use foreground_response only when the
        # lifecycle does not yield a structured status.
        foreground_status = foreground_response or "ready"

    return SubjectFacingForeground(
        subject_state=subject_state,
        action_phase=action_phase,
        foreground_event=foreground_event,
        foreground_status=foreground_status,
        current_action=current_action,
        result=result,
        result_summary=result_summary,
        blocker=blocker_dict,
        blocker_reason=blocker_reason,
        confirmation=confirmation_dict,
        confirmation_reason=confirmation_reason,
        is_subject_primary=True,
        foreground_version="1.0",
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "SUBJECT_FACING_FOREGROUND_SENTINEL",
    "FOREGROUND_EVENT_ACTIVE",
    "FOREGROUND_EVENT_BLOCKED",
    "FOREGROUND_EVENT_CONFIRMING",
    "FOREGROUND_EVENT_COMPLETED",
    "FOREGROUND_EVENT_READY",
    "FOREGROUND_EVENT_TRANSITIONING",
    "SubjectFacingForeground",
    "build_subject_facing_foreground",
]
