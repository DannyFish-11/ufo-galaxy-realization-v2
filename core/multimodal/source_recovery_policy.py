"""core/multimodal/source_recovery_policy.py — Runtime Source/Session Recovery and
Primary-Source Re-election (Runtime Shell Layer)

**Unified-Subject Architecture — Runtime Shell Ownership**
------------------------------------------------------------
Source lifecycle, recovery, and primary-source election are owned by the runtime
shell (:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`).

This module provides the deterministic policy engine for:

- Assessing whether a degraded or failed source is *recoverable*
- Assessing whether a source is *stale* (no recent signal)
- Re-integrating temporarily-failed sources back to healthy state
- Evicting stale or permanently-failed sources deterministically
- Re-electing primary audio/video sources when primaries fail or degrade
- Smoothing transient flaps through hysteresis to avoid chaotic switching
- Emitting structured events for diagnostics and projection coherence

**Behavioural guarantees**

1. **Shell owns lifecycle** — this policy mutates only the shell-owned
   :class:`~core.multimodal.perception_source_registry.PerceptionSourceRegistry`.
2. **Deterministic re-election** — candidate selection uses stable rules:
   active status, health rank (HEALTHY > DEGRADED > UNKNOWN > UNAVAILABLE),
   then numeric priority (lower = higher priority).
3. **Graceful transitions** — transient flaps within a short window increment a
   hysteresis counter; primary re-election is deferred while a source is within
   its flap tolerance window.
4. **Projection consistency** — all recovery/re-election outcomes are represented
   as structured :class:`SourceRecoveryEvent` and :class:`PrimarySourceSwitchEvent`
   records on the :class:`SourceRecoverySnapshot`, keeping shell-facing status
   coherent during transitions.
5. **Canonical state** — recovery outcomes are reflected through the existing
   :class:`~core.multimodal.perception_source_registry.PerceptionSourceRegistry`
   health and primary-selection fields; no shadow state is introduced.

Usage::

    from core.multimodal.source_recovery_policy import get_source_recovery_policy

    policy = get_source_recovery_policy()
    cycle_result = policy.run_recovery_cycle(registry)

    snap = policy.snapshot(registry)
    import json; json.dumps(snap.to_dict())  # safe — no binary payloads
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default tuning constants
# ---------------------------------------------------------------------------

_DEFAULT_STALE_THRESHOLD_S: float = 30.0
"""Age (seconds, inactive) after which a non-healthy source is considered stale."""

_DEFAULT_FLAP_WINDOW_S: float = 10.0
"""Sliding window (seconds) used for flap-count tracking."""

_DEFAULT_FLAP_THRESHOLD: int = 3
"""Number of observed degradations within the flap window that constitute flapping."""

_MAX_RECENT_EVENTS: int = 50
"""Maximum number of recent events retained in memory."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SourceRecoverability(str, Enum):
    """Whether a degraded source can potentially be recovered automatically."""

    RECOVERABLE = "recoverable"
    """Source is DEGRADED and can be reintegrated when healthy again."""

    UNRECOVERABLE = "unrecoverable"
    """Source is UNAVAILABLE; manual/external action is required."""

    UNKNOWN = "unknown"
    """Recoverability cannot be determined (HEALTHY or status unknown)."""

    @classmethod
    def from_string(cls, value: str) -> "SourceRecoverability":
        """Return enum member matching *value*, or ``UNKNOWN`` on mismatch."""
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.UNKNOWN


class SourceFreshness(str, Enum):
    """Whether a source has produced a signal recently enough to be considered fresh."""

    FRESH = "fresh"
    """Source is active or was seen recently (within the staleness window)."""

    STALE = "stale"
    """Source has not been seen within the staleness window."""

    UNKNOWN = "unknown"
    """Freshness cannot be determined (no ``last_seen_at`` timestamp)."""

    @classmethod
    def from_string(cls, value: str) -> "SourceFreshness":
        """Return enum member matching *value*, or ``UNKNOWN`` on mismatch."""
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.UNKNOWN


class PrimarySourceSwitchReason(str, Enum):
    """Reason a primary audio or video source was switched."""

    PRIMARY_FAILED = "primary_failed"
    """Primary source became UNAVAILABLE (hard failure)."""

    PRIMARY_DEGRADED = "primary_degraded"
    """Primary source is DEGRADED and persistently unhealthy."""

    PRIMARY_STALE = "primary_stale"
    """Primary source exceeded the staleness threshold with no recovery."""

    PRIMARY_EVICTED = "primary_evicted"
    """Primary source was evicted from the registry."""

    NO_PRIMARY = "no_primary"
    """No primary was selected; election fills the vacancy."""

    EXPLICIT_SELECTION = "explicit_selection"
    """Caller explicitly requested a new primary."""

    NONE = "none"
    """No switch occurred or reason is not applicable."""

    @classmethod
    def from_string(cls, value: str) -> "PrimarySourceSwitchReason":
        """Return enum member matching *value*, or ``NONE`` on mismatch."""
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.NONE


class RecoveryEventKind(str, Enum):
    """Category of a source recovery, eviction, or re-election event."""

    RECOVERED = "recovered"
    """A previously-degraded source was reintegrated as healthy."""

    EVICTED = "evicted"
    """A stale or permanently-failed source was removed from the registry."""

    PRIMARY_REELECTED = "primary_reelected"
    """A new primary audio or video source was selected."""

    FLAP_SMOOTHED = "flap_smoothed"
    """A re-election or recovery was deferred due to hysteresis."""

    @classmethod
    def from_string(cls, value: str) -> "RecoveryEventKind":
        """Return enum member matching *value*, or ``RECOVERED`` on mismatch."""
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.RECOVERED


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SourceRecoveryEvent:
    """A single source recovery, eviction, or smoothing event."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_kind: RecoveryEventKind = RecoveryEventKind.RECOVERED
    source_id: str = ""
    modality: str = ""
    previous_health: str = ""
    new_health: str = ""
    reason: str = ""
    occurred_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain, JSON-safe dict."""
        return {
            "event_id": self.event_id,
            "event_kind": self.event_kind.value,
            "source_id": self.source_id,
            "modality": self.modality,
            "previous_health": self.previous_health,
            "new_health": self.new_health,
            "reason": self.reason,
            "occurred_at": self.occurred_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceRecoveryEvent":
        """Deserialise from a plain dict."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_kind=RecoveryEventKind.from_string(data.get("event_kind", "")),
            source_id=data.get("source_id", ""),
            modality=data.get("modality", ""),
            previous_health=data.get("previous_health", ""),
            new_health=data.get("new_health", ""),
            reason=data.get("reason", ""),
            occurred_at=data.get("occurred_at", time.time()),
        )


@dataclass
class PrimarySourceSwitchEvent:
    """A primary audio or video source re-election event."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    modality: str = ""
    """'audio' or 'video'."""
    previous_source_id: Optional[str] = None
    new_source_id: Optional[str] = None
    reason: PrimarySourceSwitchReason = PrimarySourceSwitchReason.NONE
    occurred_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain, JSON-safe dict."""
        return {
            "event_id": self.event_id,
            "modality": self.modality,
            "previous_source_id": self.previous_source_id,
            "new_source_id": self.new_source_id,
            "reason": self.reason.value,
            "occurred_at": self.occurred_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PrimarySourceSwitchEvent":
        """Deserialise from a plain dict."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            modality=data.get("modality", ""),
            previous_source_id=data.get("previous_source_id"),
            new_source_id=data.get("new_source_id"),
            reason=PrimarySourceSwitchReason.from_string(data.get("reason", "")),
            occurred_at=data.get("occurred_at", time.time()),
        )


@dataclass
class SourceRecoverySnapshot:
    """Snapshot of the source recovery policy state at a point in time.

    Suitable for diagnostics, shell-facing status projection, and
    canonical control artifact embedding.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    snapshot_at: float = field(default_factory=time.time)
    recent_recovery_events: List[SourceRecoveryEvent] = field(default_factory=list)
    recent_switch_events: List[PrimarySourceSwitchEvent] = field(default_factory=list)
    current_primary_audio_id: Optional[str] = None
    current_primary_video_id: Optional[str] = None
    recoverable_source_count: int = 0
    unrecoverable_source_count: int = 0
    stale_source_count: int = 0
    flap_source_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain, JSON-safe dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_at": self.snapshot_at,
            "recent_recovery_events": [
                e.to_dict() for e in self.recent_recovery_events
            ],
            "recent_switch_events": [
                e.to_dict() for e in self.recent_switch_events
            ],
            "current_primary_audio_id": self.current_primary_audio_id,
            "current_primary_video_id": self.current_primary_video_id,
            "recoverable_source_count": self.recoverable_source_count,
            "unrecoverable_source_count": self.unrecoverable_source_count,
            "stale_source_count": self.stale_source_count,
            "flap_source_count": self.flap_source_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceRecoverySnapshot":
        """Deserialise from a plain dict."""
        return cls(
            snapshot_id=data.get("snapshot_id", str(uuid.uuid4())),
            snapshot_at=data.get("snapshot_at", time.time()),
            recent_recovery_events=[
                SourceRecoveryEvent.from_dict(e)
                for e in data.get("recent_recovery_events", [])
            ],
            recent_switch_events=[
                PrimarySourceSwitchEvent.from_dict(e)
                for e in data.get("recent_switch_events", [])
            ],
            current_primary_audio_id=data.get("current_primary_audio_id"),
            current_primary_video_id=data.get("current_primary_video_id"),
            recoverable_source_count=data.get("recoverable_source_count", 0),
            unrecoverable_source_count=data.get("unrecoverable_source_count", 0),
            stale_source_count=data.get("stale_source_count", 0),
            flap_source_count=data.get("flap_source_count", 0),
        )


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------


class SourceRecoveryPolicy:
    """Runtime-shell-owned policy engine for source recovery and primary re-election.

    Parameters
    ----------
    stale_threshold_s:
        Age (seconds, while inactive) after which a non-healthy source is
        considered stale and eligible for eviction.
    flap_window_s:
        Sliding window (seconds) over which degradation events are counted for
        hysteresis purposes.
    flap_threshold:
        Number of degradation observations within *flap_window_s* that
        classify a source as flapping.  Primary re-election is deferred for
        flapping sources.
    max_recent_events:
        Maximum number of recent recovery/switch events retained in memory for
        snapshot/projection.
    """

    def __init__(
        self,
        *,
        stale_threshold_s: float = _DEFAULT_STALE_THRESHOLD_S,
        flap_window_s: float = _DEFAULT_FLAP_WINDOW_S,
        flap_threshold: int = _DEFAULT_FLAP_THRESHOLD,
        max_recent_events: int = _MAX_RECENT_EVENTS,
    ) -> None:
        self.stale_threshold_s = stale_threshold_s
        self.flap_window_s = flap_window_s
        self.flap_threshold = flap_threshold
        self.max_recent_events = max_recent_events

        # Hysteresis: source_id → list[float] of degradation observation timestamps
        self._flap_history: Dict[str, List[float]] = {}

        # Rolling event log (capped at max_recent_events each)
        self._recovery_events: List[SourceRecoveryEvent] = []
        self._switch_events: List[PrimarySourceSwitchEvent] = []

    # ------------------------------------------------------------------
    # Assessment helpers
    # ------------------------------------------------------------------

    def assess_recoverability(self, record: Any) -> SourceRecoverability:
        """Return the recoverability of a source record.

        - RECOVERABLE  → source health is DEGRADED (may recover)
        - UNRECOVERABLE → source health is UNAVAILABLE (hardware/permanent failure)
        - UNKNOWN       → any other state (HEALTHY, UNKNOWN)
        """
        from core.multimodal.perception_source_registry import SourceHealthStatus

        if record is None:
            return SourceRecoverability.UNKNOWN
        if record.health == SourceHealthStatus.DEGRADED:
            return SourceRecoverability.RECOVERABLE
        if record.health == SourceHealthStatus.UNAVAILABLE:
            return SourceRecoverability.UNRECOVERABLE
        return SourceRecoverability.UNKNOWN

    def assess_freshness(
        self,
        record: Any,
        stale_threshold_s: Optional[float] = None,
    ) -> SourceFreshness:
        """Return the freshness of a source record.

        A source is FRESH if it is currently active or its ``last_seen_at``
        timestamp is within *stale_threshold_s* seconds of now.
        """
        if record is None:
            return SourceFreshness.UNKNOWN
        if record.is_active:
            return SourceFreshness.FRESH
        if record.last_seen_at is None:
            return SourceFreshness.UNKNOWN
        threshold = (
            stale_threshold_s
            if stale_threshold_s is not None
            else self.stale_threshold_s
        )
        age = time.time() - record.last_seen_at
        return SourceFreshness.STALE if age > threshold else SourceFreshness.FRESH

    # ------------------------------------------------------------------
    # Flap / hysteresis tracking
    # ------------------------------------------------------------------

    def _record_flap(self, source_id: str) -> int:
        """Record a degradation observation for *source_id*.

        Prunes observations outside *flap_window_s* and returns the current
        flap count within the window.
        """
        now = time.time()
        history = self._flap_history.setdefault(source_id, [])
        history[:] = [t for t in history if now - t <= self.flap_window_s]
        history.append(now)
        return len(history)

    def is_flapping(self, source_id: str) -> bool:
        """Return ``True`` if *source_id* has exceeded the flap threshold.

        A source is considered flapping when it has been observed as degraded
        at least *flap_threshold* times within *flap_window_s* seconds.
        """
        now = time.time()
        history = self._flap_history.get(source_id, [])
        recent = [t for t in history if now - t <= self.flap_window_s]
        return len(recent) >= self.flap_threshold

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def attempt_recovery(self, registry: Any, source_id: str) -> bool:
        """Attempt to recover a DEGRADED source back to healthy state.

        A DEGRADED source is recovered by marking it healthy and active.
        UNAVAILABLE sources are not eligible for automatic recovery — they
        require explicit external action.

        The registry's ``mark_recovered`` method is called when available;
        otherwise the health and active fields are updated directly.

        Returns
        -------
        bool
            ``True`` if recovery was applied; ``False`` otherwise.
        """
        from core.multimodal.perception_source_registry import SourceHealthStatus

        record = registry.get(source_id)
        if record is None:
            return False

        if record.health != SourceHealthStatus.DEGRADED:
            return False

        prev_health = record.health.value

        # Prefer the registry's own mark_recovered helper when available.
        if hasattr(registry, "mark_recovered"):
            registry.mark_recovered(source_id)
        else:
            record.health = SourceHealthStatus.HEALTHY
            record.is_active = True
            record.last_seen_at = time.time()
            record.degradation_reasons.clear()

        evt = SourceRecoveryEvent(
            event_kind=RecoveryEventKind.RECOVERED,
            source_id=source_id,
            modality=record.modality.value,
            previous_health=prev_health,
            new_health=SourceHealthStatus.HEALTHY.value,
            reason="recovery_policy",
        )
        self._append_recovery_event(evt)
        logger.debug("SourceRecoveryPolicy: recovered source_id=%s", source_id)
        return True

    def evict_stale_sources(
        self,
        registry: Any,
        stale_threshold_s: Optional[float] = None,
    ) -> List[str]:
        """Remove stale non-healthy inactive sources from the registry.

        A source is evicted when **all** of the following are true:

        - It is not currently active (``is_active == False``)
        - Its ``last_seen_at`` is set and older than *stale_threshold_s*
        - Its health is not HEALTHY (stale-but-healthy sources are dormant,
          not eviction candidates)

        Returns the list of evicted ``source_id`` strings.
        """
        from core.multimodal.perception_source_registry import SourceHealthStatus

        threshold = (
            stale_threshold_s
            if stale_threshold_s is not None
            else self.stale_threshold_s
        )
        now = time.time()
        evicted: List[str] = []

        for record in list(registry.all_sources()):
            if record.is_active:
                continue
            if record.health == SourceHealthStatus.HEALTHY:
                continue
            if record.last_seen_at is None:
                continue
            age = now - record.last_seen_at
            if age <= threshold:
                continue

            source_id = record.source_id
            prev_health = record.health.value
            mod = record.modality.value

            registry.remove(source_id)

            evt = SourceRecoveryEvent(
                event_kind=RecoveryEventKind.EVICTED,
                source_id=source_id,
                modality=mod,
                previous_health=prev_health,
                new_health="removed",
                reason=f"stale_age={age:.1f}s",
            )
            self._append_recovery_event(evt)
            evicted.append(source_id)
            logger.debug(
                "SourceRecoveryPolicy: evicted stale source_id=%s age=%.1fs",
                source_id,
                age,
            )

        return evicted

    # ------------------------------------------------------------------
    # Primary source re-election
    # ------------------------------------------------------------------

    def _elect_best_candidate(self, candidates: List[Any]) -> Optional[Any]:
        """Select the best candidate from a list using deterministic stable rules.

        Election order (lower score = preferred):

        1. Active status — active (0) beats inactive (1)
        2. Health rank — HEALTHY (0) > DEGRADED (1) > UNKNOWN (2) > UNAVAILABLE (3)
        3. Numeric priority — lower value = higher priority
        """
        from core.multimodal.perception_source_registry import SourceHealthStatus

        _health_rank = {
            SourceHealthStatus.HEALTHY: 0,
            SourceHealthStatus.DEGRADED: 1,
            SourceHealthStatus.UNKNOWN: 2,
            SourceHealthStatus.UNAVAILABLE: 3,
        }

        eligible = [
            c for c in candidates if c.health != SourceHealthStatus.UNAVAILABLE
        ]
        if not eligible:
            return None

        return min(
            eligible,
            key=lambda r: (
                0 if r.is_active else 1,
                _health_rank.get(r.health, 99),
                r.priority,
            ),
        )

    def reelect_primary_audio(
        self,
        registry: Any,
        reason: PrimarySourceSwitchReason = PrimarySourceSwitchReason.PRIMARY_FAILED,
    ) -> Optional[str]:
        """Re-elect the primary audio source using deterministic candidate selection.

        Considers all audio-capable (AUDIO or MULTI modality) sources and selects
        the best one.  If no suitable candidate exists the primary is cleared.

        Returns the new primary ``source_id``, or ``None`` if no candidate.
        """
        from core.multimodal.perception_source_registry import SourceModality

        prev_primary_id = registry.primary_audio_id
        candidates = registry.sources_by_modality(SourceModality.AUDIO)
        best = self._elect_best_candidate(candidates)

        if best is None:
            registry.clear_primary_audio()
            self._append_switch_event(
                PrimarySourceSwitchEvent(
                    modality="audio",
                    previous_source_id=prev_primary_id,
                    new_source_id=None,
                    reason=reason,
                )
            )
            return None

        if best.source_id != prev_primary_id:
            registry.set_primary_audio(best.source_id)
            self._append_switch_event(
                PrimarySourceSwitchEvent(
                    modality="audio",
                    previous_source_id=prev_primary_id,
                    new_source_id=best.source_id,
                    reason=reason,
                )
            )
            logger.debug(
                "SourceRecoveryPolicy: re-elected primary audio source_id=%s "
                "(was %s) reason=%s",
                best.source_id,
                prev_primary_id,
                reason.value,
            )

        return best.source_id

    def reelect_primary_video(
        self,
        registry: Any,
        reason: PrimarySourceSwitchReason = PrimarySourceSwitchReason.PRIMARY_FAILED,
    ) -> Optional[str]:
        """Re-elect the primary video source using deterministic candidate selection.

        Considers all video-capable (VIDEO or MULTI modality) sources and selects
        the best one.  If no suitable candidate exists the primary is cleared.

        Returns the new primary ``source_id``, or ``None`` if no candidate.
        """
        from core.multimodal.perception_source_registry import SourceModality

        prev_primary_id = registry.primary_video_id
        candidates = registry.sources_by_modality(SourceModality.VIDEO)
        best = self._elect_best_candidate(candidates)

        if best is None:
            registry.clear_primary_video()
            self._append_switch_event(
                PrimarySourceSwitchEvent(
                    modality="video",
                    previous_source_id=prev_primary_id,
                    new_source_id=None,
                    reason=reason,
                )
            )
            return None

        if best.source_id != prev_primary_id:
            registry.set_primary_video(best.source_id)
            self._append_switch_event(
                PrimarySourceSwitchEvent(
                    modality="video",
                    previous_source_id=prev_primary_id,
                    new_source_id=best.source_id,
                    reason=reason,
                )
            )
            logger.debug(
                "SourceRecoveryPolicy: re-elected primary video source_id=%s "
                "(was %s) reason=%s",
                best.source_id,
                prev_primary_id,
                reason.value,
            )

        return best.source_id

    # ------------------------------------------------------------------
    # Full recovery cycle
    # ------------------------------------------------------------------

    def run_recovery_cycle(self, registry: Any) -> Dict[str, Any]:
        """Run a full source recovery cycle against *registry*.

        Steps
        -----
        1. Evict stale non-healthy inactive sources.
        2. For each remaining unhealthy primary source: check for flapping.
           - If flapping → emit ``FLAP_SMOOTHED`` event and defer re-election.
           - If not flapping → record degradation and re-elect.
        3. If no primary is selected for a modality but candidates exist,
           elect a primary (vacancy fill).

        Returns a summary dict with keys:

        ``evicted``
            List of evicted ``source_id`` strings.
        ``audio_reelected``
            ``True`` if a new primary audio source was elected.
        ``video_reelected``
            ``True`` if a new primary video source was elected.
        ``flap_smoothed_ids``
            List of ``source_id`` strings whose re-election was deferred.
        """
        from core.multimodal.perception_source_registry import (
            SourceHealthStatus,
            SourceModality,
        )

        evicted = self.evict_stale_sources(registry)
        flap_smoothed_ids: List[str] = []
        audio_reelected = False
        video_reelected = False

        # ---- check primary audio ----
        primary_audio = registry.primary_audio()
        if primary_audio is not None:
            is_unhealthy = (
                primary_audio.health
                in (SourceHealthStatus.UNAVAILABLE, SourceHealthStatus.DEGRADED)
                or not primary_audio.is_active
            )
            if is_unhealthy:
                flap_count = self._record_flap(primary_audio.source_id)
                if flap_count >= self.flap_threshold:
                    # Source is flapping — defer re-election
                    flap_smoothed_ids.append(primary_audio.source_id)
                    self._append_recovery_event(
                        SourceRecoveryEvent(
                            event_kind=RecoveryEventKind.FLAP_SMOOTHED,
                            source_id=primary_audio.source_id,
                            modality=primary_audio.modality.value,
                            previous_health=primary_audio.health.value,
                            new_health=primary_audio.health.value,
                            reason="hysteresis_audio",
                        )
                    )
                    logger.debug(
                        "SourceRecoveryPolicy: flap smoothing primary audio "
                        "source_id=%s (flap_count=%d)",
                        primary_audio.source_id,
                        flap_count,
                    )
                else:
                    reason = (
                        PrimarySourceSwitchReason.PRIMARY_FAILED
                        if primary_audio.health == SourceHealthStatus.UNAVAILABLE
                        else PrimarySourceSwitchReason.PRIMARY_DEGRADED
                    )
                    new_id = self.reelect_primary_audio(registry, reason)
                    audio_reelected = new_id != primary_audio.source_id
        elif registry.primary_audio_id is None:
            # No primary — fill vacancy if any audio candidate exists
            if registry.sources_by_modality(SourceModality.AUDIO):
                new_id = self.reelect_primary_audio(
                    registry, PrimarySourceSwitchReason.NO_PRIMARY
                )
                audio_reelected = new_id is not None

        # ---- check primary video ----
        primary_video = registry.primary_video()
        if primary_video is not None:
            is_unhealthy = (
                primary_video.health
                in (SourceHealthStatus.UNAVAILABLE, SourceHealthStatus.DEGRADED)
                or not primary_video.is_active
            )
            if is_unhealthy:
                flap_count = self._record_flap(primary_video.source_id)
                if flap_count >= self.flap_threshold:
                    flap_smoothed_ids.append(primary_video.source_id)
                    self._append_recovery_event(
                        SourceRecoveryEvent(
                            event_kind=RecoveryEventKind.FLAP_SMOOTHED,
                            source_id=primary_video.source_id,
                            modality=primary_video.modality.value,
                            previous_health=primary_video.health.value,
                            new_health=primary_video.health.value,
                            reason="hysteresis_video",
                        )
                    )
                    logger.debug(
                        "SourceRecoveryPolicy: flap smoothing primary video "
                        "source_id=%s (flap_count=%d)",
                        primary_video.source_id,
                        flap_count,
                    )
                else:
                    reason = (
                        PrimarySourceSwitchReason.PRIMARY_FAILED
                        if primary_video.health == SourceHealthStatus.UNAVAILABLE
                        else PrimarySourceSwitchReason.PRIMARY_DEGRADED
                    )
                    new_id = self.reelect_primary_video(registry, reason)
                    video_reelected = new_id != primary_video.source_id
        elif registry.primary_video_id is None:
            # No primary — fill vacancy if any video candidate exists
            if registry.sources_by_modality(SourceModality.VIDEO):
                new_id = self.reelect_primary_video(
                    registry, PrimarySourceSwitchReason.NO_PRIMARY
                )
                video_reelected = new_id is not None

        return {
            "evicted": evicted,
            "audio_reelected": audio_reelected,
            "video_reelected": video_reelected,
            "flap_smoothed_ids": flap_smoothed_ids,
        }

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, registry: Any) -> SourceRecoverySnapshot:
        """Build a :class:`SourceRecoverySnapshot` from the current policy state.

        The snapshot captures:
        - Recent recovery and switch events
        - Current primary audio/video source IDs
        - Per-category source counts (recoverable / unrecoverable / stale / flapping)
        """
        from core.multimodal.perception_source_registry import SourceHealthStatus

        now = time.time()
        recoverable_count = 0
        unrecoverable_count = 0
        stale_count = 0
        flap_count = 0

        for record in registry.all_sources():
            recov = self.assess_recoverability(record)
            if recov == SourceRecoverability.RECOVERABLE:
                recoverable_count += 1
            elif recov == SourceRecoverability.UNRECOVERABLE:
                unrecoverable_count += 1

            freshness = self.assess_freshness(record)
            if freshness == SourceFreshness.STALE:
                stale_count += 1

            if self.is_flapping(record.source_id):
                flap_count += 1

        return SourceRecoverySnapshot(
            snapshot_at=now,
            recent_recovery_events=list(self._recovery_events),
            recent_switch_events=list(self._switch_events),
            current_primary_audio_id=registry.primary_audio_id,
            current_primary_video_id=registry.primary_video_id,
            recoverable_source_count=recoverable_count,
            unrecoverable_source_count=unrecoverable_count,
            stale_source_count=stale_count,
            flap_source_count=flap_count,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_recovery_event(self, evt: SourceRecoveryEvent) -> None:
        self._recovery_events.append(evt)
        if len(self._recovery_events) > self.max_recent_events:
            self._recovery_events = self._recovery_events[-self.max_recent_events :]

    def _append_switch_event(self, evt: PrimarySourceSwitchEvent) -> None:
        self._switch_events.append(evt)
        if len(self._switch_events) > self.max_recent_events:
            self._switch_events = self._switch_events[-self.max_recent_events :]


# ---------------------------------------------------------------------------
# Module-level builders
# ---------------------------------------------------------------------------


def build_source_recovery_snapshot(
    registry: Any,
    policy: Optional[SourceRecoveryPolicy] = None,
) -> SourceRecoverySnapshot:
    """Build a :class:`SourceRecoverySnapshot` for *registry*.

    Uses the process-wide singleton policy when *policy* is not provided.
    """
    if policy is None:
        policy = get_source_recovery_policy()
    return policy.snapshot(registry)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_policy_instance: Optional[SourceRecoveryPolicy] = None


def get_source_recovery_policy() -> SourceRecoveryPolicy:
    """Return the process-wide :class:`SourceRecoveryPolicy` singleton.

    Thread-safe for read access (singleton is set once and never mutated).
    The first caller constructs the instance.
    """
    global _policy_instance
    if _policy_instance is None:
        _policy_instance = SourceRecoveryPolicy()
    return _policy_instance


def reset_source_recovery_policy() -> None:
    """Reset the process-wide singleton (primarily for testing)."""
    global _policy_instance
    _policy_instance = None
