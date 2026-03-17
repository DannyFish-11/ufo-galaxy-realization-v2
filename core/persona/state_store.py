"""
Galaxy — PersonaState Store (PR-3)
=====================================

:class:`StateStore` maintains an in-memory :class:`PersonaState` per
``session_id``.  All mutations are performed through :meth:`update_state`
which delegates to :class:`~core.persona.emotion_engine.EmotionEngine` and
then emits a ``PERSONA_STATE_UPDATED`` event on the Galaxy EventBus.

Design notes
------------
* **Thread-safe reads/writes**: the store uses a plain ``dict`` protected by
  nothing more than the GIL.  Full async locking is unnecessary here because
  persona updates are low-frequency and the GIL makes dict assignment atomic.
* **No persistence**: state is lost when the process restarts.  A future PR
  may back this with Redis or SQLite.
* **Default baseline**: callers that provide an unknown ``session_id`` receive
  a freshly constructed :class:`PersonaState` with calm/neutral defaults.

Usage::

    from core.persona.state_store import get_state_store

    store = get_state_store()
    state = store.get_state("sess_abc")
    updated, delta = store.update_state(
        "sess_abc",
        message="这个脚本跑崩了",
        interaction_mode="control_console",
        task_success=False,
    )
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from core.schemas.persona_state import PersonaState
from core.persona.emotion_engine import EmotionEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store_instance: Optional["StateStore"] = None


def get_state_store() -> "StateStore":
    """Return the process-wide :class:`StateStore` singleton."""
    global _store_instance
    if _store_instance is None:
        _store_instance = StateStore()
    return _store_instance


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------

class StateStore:
    """In-memory persona state store, keyed by ``session_id``.

    Public API:

    * :meth:`get_state` — retrieve (or auto-create) state for a session.
    * :meth:`update_state` — compute delta → apply → emit event → return.
    * :meth:`reset_state` — reset a session back to baseline (useful in tests).
    """

    def __init__(self) -> None:
        self._states: Dict[str, PersonaState] = {}
        self._engine = EmotionEngine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self, session_id: str) -> PersonaState:
        """Return the :class:`PersonaState` for *session_id*.

        If the session is unknown a new baseline state is created, stored,
        and returned.  The fallback session ``"__global__"`` is *always*
        available and acts as the default for callers that do not track
        sessions.
        """
        if not session_id:
            session_id = "__global__"
        if session_id not in self._states:
            self._states[session_id] = PersonaState.default_baseline(session_id)
        return self._states[session_id]

    def update_state(
        self,
        session_id: str,
        *,
        message: str = "",
        interaction_mode: Optional[str] = None,
        task_success: Optional[bool] = None,
        task_result_summary: Optional[str] = None,
    ) -> Tuple[PersonaState, Dict[str, Any]]:
        """Compute a delta, apply it to the stored state, emit an event.

        Args:
            session_id:           Session to update.
            message:              Raw user message (for sentiment heuristics).
            interaction_mode:     Current interaction mode string value.
            task_success:         ``True`` / ``False`` / ``None`` for task outcome.
            task_result_summary:  Optional task result summary text.

        Returns:
            ``(updated_state, delta)`` where *delta* is the raw numeric
            increment dict produced by :class:`EmotionEngine`.
        """
        if not session_id:
            session_id = "__global__"

        state = self.get_state(session_id)
        delta = self._engine.compute_delta(
            message=message,
            interaction_mode=interaction_mode,
            task_success=task_success,
            task_result_summary=task_result_summary,
        )
        self._engine.apply_delta(state, delta)

        self._emit_event(session_id=session_id, delta=delta, state=state)
        return state, delta

    def reset_state(self, session_id: str) -> PersonaState:
        """Reset *session_id* back to the calm/neutral baseline and return it."""
        if not session_id:
            session_id = "__global__"
        self._states[session_id] = PersonaState.default_baseline(session_id)
        return self._states[session_id]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_event(
        self,
        session_id: str,
        delta: Dict[str, Any],
        state: PersonaState,
    ) -> None:
        """Emit ``PERSONA_STATE_UPDATED`` on the Galaxy EventBus (best-effort)."""
        try:
            from integration.event_bus import EventType, UIGalaxyEvent
            from integration.event_bus import event_bus as _event_bus

            _event_bus.publish(
                UIGalaxyEvent(
                    event_type=EventType.PERSONA_STATE_UPDATED,
                    source="persona_state_store",
                    data={
                        "session_id": session_id,
                        "delta": {k: v for k, v in delta.items() if not k.startswith("_")},
                        "state": state.to_dict(),
                    },
                )
            )
        except Exception as exc:
            logger.debug("StateStore._emit_event failed: %s", exc)


__all__ = ["StateStore", "get_state_store"]
