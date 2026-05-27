#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/presence/presence_projection.py
======================================
Block-4 (PR-4) — Cross-Device Presence Projection Engine

Projects a unified cognitive state across all devices in the Body Mesh,
with **intensity** modulated by each device's role:

- :attr:`~core.mesh.body_mesh_registry.DeviceRole.PRESENCE` devices receive
  *full* projection intensity.
- :attr:`~core.mesh.body_mesh_registry.DeviceRole.ACTION` devices receive
  *medium* intensity (enough to synchronise action context).
- :attr:`~core.mesh.body_mesh_registry.DeviceRole.PERCEPTION` devices receive
  *low* intensity (acknowledgement only).
- Devices with no role receive *minimal* intensity.

Design
------
- Additive — does not modify existing state management.
- Integrates with :class:`~core.state_event_bus.StateEventBus` for
  ``presence.projected`` events.
- Singleton via :func:`get_presence_projection` / :func:`reset_presence_projection`.

Quick start::

    from core.presence.presence_projection import get_presence_projection

    proj = get_presence_projection()
    events = proj.project(
        cognitive_state={"intensity": 0.8, "phase": "manifest"},
        session_id="sess-abc",
    )
    for e in events:
        print(e.device_id, e.intensity)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Presence.Projection")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProjectionIntensity(float, Enum):
    """Normalised projection intensity by device role."""

    FULL     = 1.0   # PRESENCE role devices
    MEDIUM   = 0.6   # ACTION role devices
    LOW      = 0.3   # PERCEPTION role devices
    MINIMAL  = 0.1   # No-role / unknown devices


# Role → intensity mapping
_ROLE_INTENSITY: Dict[str, ProjectionIntensity] = {
    "presence":   ProjectionIntensity.FULL,
    "action":     ProjectionIntensity.MEDIUM,
    "perception": ProjectionIntensity.LOW,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProjectionEvent:
    """A single presence-projection event targeting one device.

    Attributes
    ----------
    projection_id:
        Unique identifier for this projection event.
    device_id:
        Target device.
    session_id:
        Cognitive session being projected.
    trace_id:
        Distributed trace identifier.
    cognitive_state:
        Snapshot of the cognitive state being projected.
    intensity:
        Projection intensity for this device (0.0–1.0).
    roles:
        Device roles that determined the intensity.
    projected_at:
        Unix timestamp.
    android_presence_participation_mode:
        When the target device is an Android device with canonical presence
        participation, this field carries its participation mode string
        (``"presence_participant"`` or ``"foreground_presence"``).
        ``None`` for desktop/non-Android devices or Android devices in
        ``"execution_only"`` mode.  The presence of a non-None value in this
        field proves that Android presence participation — not just execution
        metadata — reached the projection layer.
    """

    projection_id: str = field(default_factory=lambda: f"proj_{uuid.uuid4().hex[:12]}")
    device_id: str = ""
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    cognitive_state: Dict[str, Any] = field(default_factory=dict)
    intensity: float = ProjectionIntensity.MINIMAL
    roles: List[str] = field(default_factory=list)
    projected_at: float = field(default_factory=time.time)
    android_presence_participation_mode: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "cognitive_state": self.cognitive_state,
            "intensity": self.intensity,
            "roles": self.roles,
            "projected_at": self.projected_at,
            "android_presence_participation_mode": self.android_presence_participation_mode,
        }


# ---------------------------------------------------------------------------
# PresenceProjection
# ---------------------------------------------------------------------------


class PresenceProjection:
    """Projects cognitive state across all Body Mesh devices.

    Methods
    -------
    project(cognitive_state, session_id, trace_id) -> List[ProjectionEvent]
        Project *cognitive_state* to all relevant devices and emit events.
    project_to_device(device_id, cognitive_state, intensity, ...) -> ProjectionEvent
        Project to a single named device.
    last_events(n) -> List[ProjectionEvent]
        Return the most recent *n* projection events (audit trail).
    """

    def __init__(self) -> None:
        self._recent: List[ProjectionEvent] = []
        self._lock = threading.Lock()
        self._max_recent = 200

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def project(
        self,
        cognitive_state: Dict[str, Any],
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        android_presence_participation: Optional[Any] = None,
    ) -> List[ProjectionEvent]:
        """Project *cognitive_state* to all devices registered in the Body Mesh.

        For each registered device the method:
        1. Looks up device roles from :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry`.
        2. Determines projection intensity by the highest-priority role.
        3. When ``android_presence_participation`` is supplied and a device is
           an Android presence participant, upgrades its intensity to at least
           ``MEDIUM`` and stamps the :attr:`~ProjectionEvent.android_presence_participation_mode`
           field.  This is the first path where Android presence participation —
           distinct from execution-node status — reaches projection output.
        4. Creates a :class:`ProjectionEvent` and emits it on the
           :class:`~core.state_event_bus.StateEventBus`.

        Args:
            cognitive_state:  Arbitrary dict with the current cognitive state
                              (e.g. ``{"phase": "manifest", "intensity": 0.9}``).
            session_id:       Optional session scope.  When given, only devices
                              in this session are targeted.
            trace_id:         Optional trace identifier.
            android_presence_participation:
                              Optional :class:`~core.presence.android_presence_participation.AndroidPresenceParticipationSummary`
                              (or any object with a ``records`` iterable of
                              :class:`~core.presence.android_presence_participation.AndroidPresenceParticipationRecord`).
                              When provided, Android devices that are presence
                              participants receive elevated intensity and a
                              stamped participation mode on their
                              :class:`ProjectionEvent`.

        Returns:
            List of :class:`ProjectionEvent` objects — one per targeted device.
        """
        events: List[ProjectionEvent] = []

        # Build a lookup: device_id → participation_mode for Android participants.
        _android_participant_map: Dict[str, str] = {}
        if android_presence_participation is not None:
            try:
                for rec in android_presence_participation.records:
                    if rec.is_presence_participant:
                        _android_participant_map[rec.device_id] = rec.participation_mode.value
            except AttributeError:
                pass

        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            registry = get_body_mesh_registry()
            if session_id:
                entries = registry.get_by_session(session_id)
                if not entries:
                    entries = registry.list_entries()
            else:
                entries = registry.list_entries()
        except Exception as exc:
            logger.warning("PresenceProjection.project: cannot access BodyMeshRegistry — %s", exc)
            entries = []

        for entry in entries:
            roles = [r.value if hasattr(r, "value") else str(r) for r in entry.roles]
            intensity = self._determine_intensity(roles)

            # Elevate intensity for Android presence participants.
            android_pm: Optional[str] = _android_participant_map.get(entry.device_id)
            if android_pm is not None:
                # foreground_presence → FULL intensity; presence_participant → at least MEDIUM.
                from core.presence.android_presence_participation import (
                    AndroidPresenceParticipationMode,
                )
                if android_pm == AndroidPresenceParticipationMode.FOREGROUND_PRESENCE.value:
                    intensity = max(intensity, float(ProjectionIntensity.FULL))
                else:
                    intensity = max(intensity, float(ProjectionIntensity.MEDIUM))

            evt = self.project_to_device(
                device_id=entry.device_id,
                cognitive_state=cognitive_state,
                intensity=intensity,
                roles=roles,
                session_id=session_id,
                trace_id=trace_id,
                android_presence_participation_mode=android_pm,
            )
            events.append(evt)

        logger.debug(
            "PresenceProjection.project: projected to %d devices session=%s android_participants=%d",
            len(events),
            session_id,
            len(_android_participant_map),
        )
        return events

    def project_to_device(
        self,
        device_id: str,
        cognitive_state: Dict[str, Any],
        intensity: float = ProjectionIntensity.MINIMAL,
        roles: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        android_presence_participation_mode: Optional[str] = None,
    ) -> ProjectionEvent:
        """Project to a single device and emit a state bus event.

        Args:
            device_id:        Target device.
            cognitive_state:  Cognitive state snapshot.
            intensity:        Projection intensity.
            roles:            Device roles (for observability).
            session_id:       Session scope.
            trace_id:         Trace identifier.
            android_presence_participation_mode:
                              When this device is an Android presence
                              participant, the participation mode string
                              (``"presence_participant"`` or
                              ``"foreground_presence"``); ``None`` otherwise.

        Returns:
            The :class:`ProjectionEvent` that was emitted.
        """
        evt = ProjectionEvent(
            device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
            cognitive_state=dict(cognitive_state),
            intensity=float(intensity),
            roles=list(roles or []),
            android_presence_participation_mode=android_presence_participation_mode,
        )

        with self._lock:
            self._recent.append(evt)
            if len(self._recent) > self._max_recent:
                self._recent = self._recent[-self._max_recent:]

        self._emit_event(evt)
        return evt

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def last_events(self, n: int = 20) -> List[ProjectionEvent]:
        """Return the most recent *n* projection events."""
        with self._lock:
            return list(self._recent[-n:])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_intensity(roles: List[str]) -> float:
        """Return the highest applicable intensity for the given role list."""
        best = float(ProjectionIntensity.MINIMAL)
        for role in roles:
            intensity = float(_ROLE_INTENSITY.get(role.lower(), ProjectionIntensity.MINIMAL))
            if intensity > best:
                best = intensity
        return best

    @staticmethod
    def _emit_event(evt: ProjectionEvent) -> None:
        """Best-effort emission on the StateEventBus."""
        try:
            from core.state_event_bus import get_state_event_bus, StateEventType
            bus = get_state_event_bus()
            event_type = StateEventType.PRESENCE_PROJECTED
            bus.publish(
                event_type,
                source="presence_projection",
                payload=evt.to_dict(),
                trace_id=evt.trace_id,
                runtime_session_id=evt.session_id,
            )
        except Exception as exc:
            logger.debug("PresenceProjection._emit_event: state bus unavailable — %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_projection: Optional[PresenceProjection] = None
_projection_lock = threading.Lock()


def get_presence_projection() -> PresenceProjection:
    """Return (or lazily create) the process-level :class:`PresenceProjection`."""
    global _projection
    with _projection_lock:
        if _projection is None:
            _projection = PresenceProjection()
    return _projection


def reset_presence_projection() -> None:
    """Reset the singleton (intended for tests only)."""
    global _projection
    with _projection_lock:
        _projection = None
