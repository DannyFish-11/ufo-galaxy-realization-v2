#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/presence/presence_director.py
=====================================
Block-4 (PR-4) — Presence Director

Orchestrates cross-device presence projection by coordinating:

1. :class:`~core.presence.presence_projection.PresenceProjection` — projects
   cognitive state to individual devices.
2. :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` — provides device
   role information.
3. :class:`~core.policy.hitl_policy.HITLPolicy` — optionally gates
   liminal→manifest transitions.

The Director is the **single entry point** for presence-related actions.
External callers (e.g. ``desktop_presence_runtime``, ``openclawd``) should
call :meth:`PresenceDirector.on_phase_transition` rather than pushing
directly to the projection engine.

Observability
-------------
Every :meth:`on_phase_transition` call emits a ``presence.director.transition``
event on the :class:`~core.state_event_bus.StateEventBus` with full trace fields.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Presence.Director")


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class DirectorConfig:
    """Configuration for the :class:`PresenceDirector`.

    Attributes
    ----------
    project_on_manifest:
        Trigger a presence projection whenever the session enters the
        MANIFEST phase.  Default: ``True``.
    project_on_liminal:
        Trigger a presence projection whenever the session enters the
        LIMINAL phase.  Default: ``False``.
    hitl_on_manifest:
        Apply HITL policy gate before projecting into MANIFEST phase.
        Default: ``False`` (gate is opt-in).
    """

    project_on_manifest: bool = True
    project_on_liminal: bool = False
    hitl_on_manifest: bool = False


# ---------------------------------------------------------------------------
# PresenceDirector
# ---------------------------------------------------------------------------


class PresenceDirector:
    """Orchestrates presence projection across the Body Mesh.

    Parameters
    ----------
    config:
        Director configuration.  Defaults to :class:`DirectorConfig()`.
    """

    def __init__(self, config: Optional[DirectorConfig] = None) -> None:
        self._config = config or DirectorConfig()
        self._lock = threading.Lock()
        self._trace_log: List[Dict[str, Any]] = []
        self._max_trace = 100

    # ------------------------------------------------------------------
    # Phase transition hook
    # ------------------------------------------------------------------

    def on_phase_transition(
        self,
        from_phase: str,
        to_phase: str,
        cognitive_state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        android_presence_participation: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """React to a cognitive phase transition.

        Depending on configuration, projects presence and/or gates the
        transition through HITL policy.

        Args:
            from_phase:      Previous phase name (e.g. ``"liminal"``).
            to_phase:        New phase name (e.g. ``"manifest"``).
            cognitive_state: Current cognitive state snapshot.
            session_id:      Session scope.
            trace_id:        Distributed trace identifier.
            android_presence_participation:
                             Optional :class:`~core.presence.android_presence_participation.AndroidPresenceParticipationSummary`.
                             When provided, Android devices that are presence
                             participants receive elevated projection intensity
                             and their participation mode is stamped on the
                             resulting :class:`~core.presence.presence_projection.ProjectionEvent`.

        Returns:
            Dict with keys:
              - ``projected``: ``True`` if a projection was triggered.
              - ``hitl_required``: ``True`` if HITL gate was triggered.
              - ``hitl_approved``: HITL decision outcome (or ``None``).
              - ``projection_events``: list of projection event dicts.
              - ``android_presence_participant_count``: number of Android
                presence participants in this transition (0 when not supplied).
        """
        state = dict(cognitive_state or {})
        state.setdefault("from_phase", from_phase)
        state.setdefault("to_phase", to_phase)

        # Embed android presence participation summary into the cognitive state
        # so it travels with the projection payload.
        _android_participant_count = 0
        if android_presence_participation is not None:
            try:
                _android_participant_count = int(
                    android_presence_participation.presence_participant_count
                )
                state["android_presence_participant_count"] = _android_participant_count
                state["android_any_drives_liminal"] = bool(
                    android_presence_participation.any_drives_liminal
                )
                state["android_any_drives_manifest"] = bool(
                    android_presence_participation.any_drives_manifest
                )
            except AttributeError:
                pass

        result: Dict[str, Any] = {
            "projected": False,
            "hitl_required": False,
            "hitl_approved": None,
            "projection_events": [],
            "android_presence_participant_count": _android_participant_count,
        }

        # ── HITL gate (manifest only, if enabled) ─────────────────────────
        if to_phase.lower() == "manifest" and self._config.hitl_on_manifest:
            hitl_result = self._apply_hitl(
                action="manifest_projection",
                context=state,
                session_id=session_id,
                trace_id=trace_id,
            )
            result["hitl_required"] = True
            result["hitl_approved"] = hitl_result.get("approved", True)
            if not hitl_result.get("approved", True):
                logger.info(
                    "PresenceDirector: HITL blocked manifest projection "
                    "session=%s trace=%s",
                    session_id,
                    trace_id,
                )
                self._record_trace(from_phase, to_phase, result, session_id, trace_id)
                self._emit_director_event(from_phase, to_phase, result, session_id, trace_id)
                return result

        # ── Projection ────────────────────────────────────────────────────
        should_project = (
            (to_phase.lower() == "manifest" and self._config.project_on_manifest)
            or (to_phase.lower() == "liminal" and self._config.project_on_liminal)
        )

        if should_project:
            events = self._project(
                state,
                session_id=session_id,
                trace_id=trace_id,
                android_presence_participation=android_presence_participation,
            )
            result["projected"] = True
            result["projection_events"] = [e.to_dict() for e in events]

        self._record_trace(from_phase, to_phase, result, session_id, trace_id)
        self._emit_director_event(from_phase, to_phase, result, session_id, trace_id)
        return result

    # ------------------------------------------------------------------
    # Presence refresh
    # ------------------------------------------------------------------

    def refresh_presence(
        self,
        cognitive_state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        android_presence_participation: Optional[Any] = None,
    ) -> List[Any]:
        """Unconditionally project *cognitive_state* to all mesh devices.

        Use this for periodic presence refreshes outside of phase transitions.

        Args:
            android_presence_participation:
                Optional :class:`~core.presence.android_presence_participation.AndroidPresenceParticipationSummary`.
                Android presence participants receive elevated intensity.

        Returns:
            List of :class:`~core.presence.presence_projection.ProjectionEvent`
            objects.
        """
        return self._project(
            cognitive_state or {},
            session_id=session_id,
            trace_id=trace_id,
            android_presence_participation=android_presence_participation,
        )

    # ------------------------------------------------------------------
    # Trace / observability
    # ------------------------------------------------------------------

    def get_trace_log(self, n: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent *n* director trace entries."""
        with self._lock:
            return list(self._trace_log[-n:])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _project(
        self,
        cognitive_state: Dict[str, Any],
        session_id: Optional[str],
        trace_id: Optional[str],
        android_presence_participation: Optional[Any] = None,
    ) -> List[Any]:
        """Delegate to :class:`~core.presence.presence_projection.PresenceProjection`."""
        try:
            from core.presence.presence_projection import get_presence_projection
            proj = get_presence_projection()
            return proj.project(
                cognitive_state=cognitive_state,
                session_id=session_id,
                trace_id=trace_id,
                android_presence_participation=android_presence_participation,
            )
        except Exception as exc:
            logger.warning("PresenceDirector._project: projection failed — %s", exc)
            return []

    def _apply_hitl(
        self,
        action: str,
        context: Dict[str, Any],
        session_id: Optional[str],
        trace_id: Optional[str],
    ) -> Dict[str, Any]:
        """Delegate to :class:`~core.policy.hitl_policy.HITLPolicy`."""
        try:
            from core.policy.hitl_policy import get_hitl_policy
            policy = get_hitl_policy()
            decision = policy.evaluate(
                action=action,
                context=context,
                session_id=session_id,
                trace_id=trace_id,
            )
            return {"approved": decision.approved, "reason": decision.reason}
        except Exception as exc:
            logger.debug("PresenceDirector._apply_hitl: HITL unavailable — %s", exc)
            return {"approved": True, "reason": "hitl_unavailable"}

    def _record_trace(
        self,
        from_phase: str,
        to_phase: str,
        result: Dict[str, Any],
        session_id: Optional[str],
        trace_id: Optional[str],
    ) -> None:
        entry = {
            "from_phase": from_phase,
            "to_phase": to_phase,
            "result": dict(result),
            "session_id": session_id,
            "trace_id": trace_id,
            "ts": time.time(),
        }
        with self._lock:
            self._trace_log.append(entry)
            if len(self._trace_log) > self._max_trace:
                self._trace_log = self._trace_log[-self._max_trace:]

    @staticmethod
    def _emit_director_event(
        from_phase: str,
        to_phase: str,
        result: Dict[str, Any],
        session_id: Optional[str],
        trace_id: Optional[str],
    ) -> None:
        """Best-effort emission on the StateEventBus."""
        try:
            from core.state_event_bus import get_state_event_bus, StateEventType
            bus = get_state_event_bus()
            event_type = StateEventType.PRESENCE_PROJECTED
            bus.publish(
                event_type,
                source="presence_director",
                payload={
                    "event": "presence.director.transition",
                    "from_phase": from_phase,
                    "to_phase": to_phase,
                    "projected": result.get("projected"),
                    "hitl_required": result.get("hitl_required"),
                    "hitl_approved": result.get("hitl_approved"),
                },
                trace_id=trace_id,
                runtime_session_id=session_id,
            )
        except Exception as exc:
            logger.debug("PresenceDirector._emit_director_event: bus unavailable — %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_director: Optional[PresenceDirector] = None
_director_lock = threading.Lock()


def get_presence_director() -> PresenceDirector:
    """Return (or lazily create) the process-level :class:`PresenceDirector`."""
    global _director
    with _director_lock:
        if _director is None:
            _director = PresenceDirector()
    return _director


def reset_presence_director() -> None:
    """Reset the singleton (intended for tests only)."""
    global _director
    with _director_lock:
        _director = None
