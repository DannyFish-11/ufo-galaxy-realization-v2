"""core/orchestration/state.py — Session memory and continuum state management.

PR-7: State management submodule extracted from the OpenClawd god object.
Provides ``SessionMemoryManager`` for per-session conversation history and
``ContinuumStateAdapter`` for interfacing with the ContinuumOrchestrator.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Orchestration.State")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

STATE_MANAGER_AUTHORITY = "STATE_MANAGER_AUTHORITY"

# ---------------------------------------------------------------------------
# SessionMemoryManager
# ---------------------------------------------------------------------------


class SessionMemoryManager:
    """Manages per-session conversation history for OpenClawd sessions."""

    STATE_MANAGER_AUTHORITY = STATE_MANAGER_AUTHORITY

    _MAX_HISTORY_BUFFER: int = 40
    _ROLLING_WINDOW_SIZE: int = 20

    def __init__(self) -> None:
        self._session_memory: Dict[str, List[Dict]] = {}

    async def record_turn(self, session_id: str, role: str, content: str) -> None:
        """Append a conversation turn to *session_id*'s history."""
        if session_id not in self._session_memory:
            self._session_memory[session_id] = []
        self._session_memory[session_id].append({"role": role, "content": content})
        # Keep a rolling window to bound memory growth
        if len(self._session_memory[session_id]) > self._MAX_HISTORY_BUFFER:
            self._session_memory[session_id] = (
                self._session_memory[session_id][-self._ROLLING_WINDOW_SIZE :]
            )

    async def clear_session(self, session_id: str) -> None:
        """Remove all history for *session_id*."""
        self._session_memory.pop(session_id, None)

    def get_history(self, session_id: str, max_turns: int = 20) -> List[Dict]:
        """Return the most recent *max_turns* turns for *session_id*."""
        history = self._session_memory.get(session_id, [])
        return history[-max_turns:] if len(history) > max_turns else list(history)

    def list_sessions(self) -> List[Dict]:
        """Return a summary list of all active sessions."""
        return [
            {"session_id": sid, "turn_count": len(turns)}
            for sid, turns in self._session_memory.items()
        ]


# ---------------------------------------------------------------------------
# ContinuumStateAdapter
# ---------------------------------------------------------------------------


class ContinuumStateAdapter:
    """Adapter that bridges OpenClawd with the ContinuumOrchestrator."""

    STATE_MANAGER_AUTHORITY = STATE_MANAGER_AUTHORITY

    @staticmethod
    def get_orchestrator(openclawd_instance: Any) -> Optional[Any]:
        """Return (and lazily initialise) the ContinuumOrchestrator on *openclawd_instance*."""
        if getattr(openclawd_instance, "_continuum_orchestrator", None) is None:
            try:
                from core.continuum_orchestrator import ContinuumOrchestrator
                openclawd_instance._continuum_orchestrator = ContinuumOrchestrator()
            except Exception as exc:
                logger.warning("ContinuumOrchestrator unavailable: %s", exc)
                return None
        return openclawd_instance._continuum_orchestrator

    @staticmethod
    async def run_continuum(
        orchestrator: Any,
        trace_id: str,
        multimodal_context: Optional[Dict] = None,
        runtime_session_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Delegate continuum execution to *orchestrator*.

        Returns the ``state_continuum`` dict or ``None`` on failure.
        """
        if orchestrator is None:
            return None
        try:
            return await orchestrator.run(
                trace_id=trace_id,
                multimodal_context=multimodal_context,
                runtime_session_id=runtime_session_id,
            )
        except Exception as exc:
            logger.warning("ContinuumStateAdapter.run_continuum failed: %s", exc)
            return None
