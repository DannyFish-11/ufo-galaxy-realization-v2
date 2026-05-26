"""core/multimodal/perception_source_registry.py — Perception Source Registry (Runtime Shell Layer)

**Unified-Subject Architecture — Runtime Shell Ownership**
------------------------------------------------------------
``PerceptionSourceRegistry`` is owned by the runtime shell
(:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`).  It formally
tracks and governs all multimodal perception sources available to the shell:
microphone, local webcam/camera, WebRTC video/camera sessions, and external
or remote video stream sources.

This is a **shell-layer governance contract** — the registry answers:

- What sources currently exist?
- Which are active?
- Which are degraded or unavailable?
- Which source is the selected primary audio / video source?
- What is the quality/health/latency of each source?

**Shell / core boundary**
The registry is a runtime-shell concern.  OpenClawd (the subject core) may
consume source summaries indirectly via canonical perception state, but must
not own, mutate, or become responsible for the source registry.

Usage::

    registry = PerceptionSourceRegistry()

    # Register a microphone source
    mic_id = registry.register(
        source_type=PerceptionSourceType.MICROPHONE,
        device_id="default",
        modality=SourceModality.AUDIO,
        display_name="System Microphone",
    )
    registry.mark_active(mic_id)
    registry.set_primary_audio(mic_id)

    # Register a WebRTC source
    webrtc_id = registry.register(
        source_type=PerceptionSourceType.WEBRTC,
        transport="webrtc",
        modality=SourceModality.VIDEO,
        display_name="Remote WebRTC Camera",
    )
    registry.update_quality(webrtc_id, quality_score=0.85, latency_ms=45.0)
    registry.mark_active(webrtc_id)

    # Get a diagnostics-safe snapshot
    snapshot = registry.snapshot()
    import json; json.dumps(snapshot)  # safe — no binary payloads
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
# Enumerations
# ---------------------------------------------------------------------------


class PerceptionSourceType(str, Enum):
    """Category of a perception source."""

    MICROPHONE = "microphone"
    WEBCAM = "webcam"
    WEBRTC = "webrtc"
    REMOTE_CAMERA = "remote_camera"
    EXTERNAL_STREAM = "external_stream"


class SourceModality(str, Enum):
    """Primary sensory modality produced by a source."""

    AUDIO = "audio"
    VIDEO = "video"
    MULTI = "multi"


class SourceHealthStatus(str, Enum):
    """Health / availability summary for a source."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


STREAM_CAPABLE_SOURCE_TYPES = frozenset(
    {
        PerceptionSourceType.WEBCAM,
        PerceptionSourceType.WEBRTC,
        PerceptionSourceType.REMOTE_CAMERA,
        PerceptionSourceType.EXTERNAL_STREAM,
    }
)


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


@dataclass
class PerceptionSourceRecord:
    """Represents a single tracked perception source.

    Fields
    ------
    source_id
        Stable UUID-based identifier assigned at registration.
    source_type
        Category: microphone / webcam / webrtc / remote_camera / external_stream.
    modality
        Primary sensory modality: audio / video / multi.
    display_name
        Human-readable label for diagnostics / status board.
    device_id
        OS-level device identifier when applicable (microphone, local camera).
    transport
        Transport mechanism when applicable (e.g. "webrtc", "rtsp", "local").
    is_active
        Whether the source is currently delivering signal.
    is_primary_audio
        Whether this source is the selected primary audio source.
    is_primary_video
        Whether this source is the selected primary video source.
    priority
        Lower value = higher priority (0 is highest).  Used for source
        selection and tie-breaking.
    health
        Health / availability summary.
    degradation_reasons
        Free-text reasons for any degradation or unavailability.
    quality_score
        Normalised quality estimate [0.0–1.0] or None when unknown.
    latency_ms
        Observed transport/processing latency in milliseconds, or None.
    registered_at
        Wall-clock time when the source was first registered (time.time()).
    last_seen_at
        Wall-clock time of the most recent signal or status update.
    extra
        Arbitrary extension data for future use.
    """

    # Identity
    source_id: str
    source_type: PerceptionSourceType
    modality: SourceModality

    # Display / diagnostics
    display_name: str = ""

    # Ownership / binding context
    device_id: Optional[str] = None
    transport: Optional[str] = None

    # Liveness
    is_active: bool = False
    is_primary_audio: bool = False
    is_primary_video: bool = False

    # Selection
    priority: int = 100  # lower = higher priority

    # Health
    health: SourceHealthStatus = SourceHealthStatus.UNKNOWN
    degradation_reasons: List[str] = field(default_factory=list)

    # Quality / latency
    quality_score: Optional[float] = None
    latency_ms: Optional[float] = None

    # Timestamps
    registered_at: float = field(default_factory=time.time)
    last_seen_at: Optional[float] = None

    # Extension
    extra: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for diagnostics / JSON export.

        No binary payloads are included.
        """
        return {
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "modality": self.modality.value,
            "display_name": self.display_name,
            "device_id": self.device_id,
            "transport": self.transport,
            "is_active": self.is_active,
            "is_primary_audio": self.is_primary_audio,
            "is_primary_video": self.is_primary_video,
            "priority": self.priority,
            "health": self.health.value,
            "degradation_reasons": list(self.degradation_reasons),
            "quality_score": self.quality_score,
            "latency_ms": self.latency_ms,
            "registered_at": self.registered_at,
            "last_seen_at": self.last_seen_at,
            "extra": dict(self.extra),
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class PerceptionSourceRegistry:
    """Runtime-shell-owned registry of multimodal perception sources.

    Tracks microphone, local camera (webcam), WebRTC session, and external /
    remote video stream sources.  Supports:

    - Source registration and removal
    - Liveness / activity tracking
    - Primary audio / video source selection
    - Health and quality bookkeeping
    - Diagnostics-safe snapshot serialisation

    **Thread safety**: all mutation methods acquire a simple in-process
    lock-free design (single-threaded runtime shell).  For multi-threaded
    callers, wrap mutations in an external lock.  Snapshot is always safe
    to call from any thread (returns a copy).
    """

    def __init__(self) -> None:
        self._sources: Dict[str, PerceptionSourceRecord] = {}
        self._primary_audio_id: Optional[str] = None
        self._primary_video_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        *,
        source_type: PerceptionSourceType,
        modality: SourceModality,
        source_id: Optional[str] = None,
        display_name: str = "",
        device_id: Optional[str] = None,
        transport: Optional[str] = None,
        priority: int = 100,
        health: SourceHealthStatus = SourceHealthStatus.UNKNOWN,
    ) -> str:
        """Register a new source and return its ``source_id``.

        If *source_id* is provided and already exists, this is a no-op (the
        existing record is returned unchanged).  Pass a fresh UUID to always
        create a new record.

        Args:
            source_type: Category of the source.
            modality: Primary sensory modality.
            source_id: Optional stable ID; auto-generated when omitted.
            display_name: Human-readable label.
            device_id: OS device identifier (microphone, local camera).
            transport: Transport mechanism (webrtc, rtsp, local, …).
            priority: Selection priority; lower = higher priority.
            health: Initial health status.

        Returns:
            The ``source_id`` of the (possibly newly-created) record.
        """
        if source_id is None:
            source_id = str(uuid.uuid4())

        if source_id in self._sources:
            logger.debug(
                "PerceptionSourceRegistry.register: source_id=%s already exists — no-op",
                source_id,
            )
            return source_id

        record = PerceptionSourceRecord(
            source_id=source_id,
            source_type=source_type,
            modality=modality,
            display_name=display_name or source_type.value,
            device_id=device_id,
            transport=transport,
            priority=priority,
            health=health,
        )
        self._sources[source_id] = record
        logger.debug(
            "PerceptionSourceRegistry: registered source_id=%s type=%s modality=%s",
            source_id,
            source_type.value,
            modality.value,
        )
        return source_id

    def remove(self, source_id: str) -> bool:
        """Remove a source from the registry.

        Returns ``True`` if the source was found and removed, ``False``
        otherwise.  If the removed source was the primary audio/video source,
        the primary selection is cleared.
        """
        if source_id not in self._sources:
            return False

        self._sources.pop(source_id)

        if self._primary_audio_id == source_id:
            self._primary_audio_id = None
            logger.debug(
                "PerceptionSourceRegistry: primary audio source removed (source_id=%s)",
                source_id,
            )
        if self._primary_video_id == source_id:
            self._primary_video_id = None
            logger.debug(
                "PerceptionSourceRegistry: primary video source removed (source_id=%s)",
                source_id,
            )

        logger.debug("PerceptionSourceRegistry: removed source_id=%s", source_id)
        return True

    def get(self, source_id: str) -> Optional[PerceptionSourceRecord]:
        """Return the record for *source_id*, or ``None`` if not found."""
        return self._sources.get(source_id)

    # ------------------------------------------------------------------
    # Liveness
    # ------------------------------------------------------------------

    def mark_active(self, source_id: str) -> None:
        """Mark a source as actively delivering signal."""
        record = self._sources.get(source_id)
        if record is None:
            logger.debug(
                "PerceptionSourceRegistry.mark_active: unknown source_id=%s", source_id
            )
            return
        record.is_active = True
        record.last_seen_at = time.time()
        if record.health == SourceHealthStatus.UNKNOWN:
            record.health = SourceHealthStatus.HEALTHY

    def mark_inactive(self, source_id: str, reason: Optional[str] = None) -> None:
        """Mark a source as no longer delivering signal."""
        record = self._sources.get(source_id)
        if record is None:
            return
        record.is_active = False
        if reason:
            record.health = SourceHealthStatus.DEGRADED
            if reason not in record.degradation_reasons:
                record.degradation_reasons.append(reason)

    def mark_unavailable(
        self, source_id: str, reason: Optional[str] = None
    ) -> None:
        """Mark a source as hardware-unavailable or otherwise unusable.

        This does not remove the source from the registry — an unavailable
        placeholder is kept so diagnostics can report what was expected.
        """
        record = self._sources.get(source_id)
        if record is None:
            return
        record.is_active = False
        record.health = SourceHealthStatus.UNAVAILABLE
        if reason and reason not in record.degradation_reasons:
            record.degradation_reasons.append(reason)

    def mark_degraded(
        self, source_id: str, reason: Optional[str] = None
    ) -> None:
        """Mark a source as degraded but potentially still usable."""
        record = self._sources.get(source_id)
        if record is None:
            return
        record.health = SourceHealthStatus.DEGRADED
        if reason and reason not in record.degradation_reasons:
            record.degradation_reasons.append(reason)

    def mark_recovered(self, source_id: str) -> None:
        """Mark a previously-degraded source as healthy and active again.

        This is the recovery counterpart to :meth:`mark_degraded`.  It:

        - Sets ``health`` to :attr:`SourceHealthStatus.HEALTHY`
        - Sets ``is_active`` to ``True``
        - Clears ``degradation_reasons``
        - Updates ``last_seen_at`` to the current wall-clock time

        No-op when *source_id* is unknown or the source is already HEALTHY.
        UNAVAILABLE sources are *not* recovered by this method — they require
        explicit external action (re-registration or hardware remediation).
        """
        record = self._sources.get(source_id)
        if record is None:
            return
        if record.health == SourceHealthStatus.UNAVAILABLE:
            logger.debug(
                "PerceptionSourceRegistry.mark_recovered: source_id=%s is UNAVAILABLE"
                " — skipping auto-recovery",
                source_id,
            )
            return
        record.health = SourceHealthStatus.HEALTHY
        record.is_active = True
        record.last_seen_at = time.time()
        record.degradation_reasons.clear()
        logger.debug(
            "PerceptionSourceRegistry: source_id=%s recovered to HEALTHY", source_id
        )

    def touch(self, source_id: str) -> None:
        """Update the ``last_seen_at`` timestamp for a source."""
        record = self._sources.get(source_id)
        if record is not None:
            record.last_seen_at = time.time()

    # ------------------------------------------------------------------
    # Quality / latency
    # ------------------------------------------------------------------

    def update_quality(
        self,
        source_id: str,
        *,
        quality_score: Optional[float] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        """Update quality and/or latency metrics for a source."""
        record = self._sources.get(source_id)
        if record is None:
            return
        if quality_score is not None:
            record.quality_score = max(0.0, min(1.0, quality_score))
        if latency_ms is not None:
            record.latency_ms = latency_ms
        record.last_seen_at = time.time()

    # ------------------------------------------------------------------
    # Primary source selection
    # ------------------------------------------------------------------

    def set_primary_audio(self, source_id: str) -> bool:
        """Select *source_id* as the primary audio source.

        Clears the ``is_primary_audio`` flag from the previous primary source.

        Returns:
            ``True`` on success; ``False`` when *source_id* is unknown or
            modality is not compatible with audio.
        """
        record = self._sources.get(source_id)
        if record is None:
            logger.warning(
                "PerceptionSourceRegistry.set_primary_audio: unknown source_id=%s",
                source_id,
            )
            return False

        if record.modality not in (SourceModality.AUDIO, SourceModality.MULTI):
            logger.warning(
                "PerceptionSourceRegistry.set_primary_audio: source_id=%s has "
                "modality=%s (not audio-capable)",
                source_id,
                record.modality.value,
            )
            return False

        # Clear existing primary flag
        if self._primary_audio_id and self._primary_audio_id in self._sources:
            self._sources[self._primary_audio_id].is_primary_audio = False

        record.is_primary_audio = True
        self._primary_audio_id = source_id
        logger.debug(
            "PerceptionSourceRegistry: primary audio = source_id=%s", source_id
        )
        return True

    def set_primary_video(self, source_id: str) -> bool:
        """Select *source_id* as the primary video source.

        Clears the ``is_primary_video`` flag from the previous primary source.

        Returns:
            ``True`` on success; ``False`` when *source_id* is unknown or
            modality is not compatible with video.
        """
        record = self._sources.get(source_id)
        if record is None:
            logger.warning(
                "PerceptionSourceRegistry.set_primary_video: unknown source_id=%s",
                source_id,
            )
            return False

        if record.modality not in (SourceModality.VIDEO, SourceModality.MULTI):
            logger.warning(
                "PerceptionSourceRegistry.set_primary_video: source_id=%s has "
                "modality=%s (not video-capable)",
                source_id,
                record.modality.value,
            )
            return False

        # Clear existing primary flag
        if self._primary_video_id and self._primary_video_id in self._sources:
            self._sources[self._primary_video_id].is_primary_video = False

        record.is_primary_video = True
        self._primary_video_id = source_id
        logger.debug(
            "PerceptionSourceRegistry: primary video = source_id=%s", source_id
        )
        return True

    def clear_primary_audio(self) -> None:
        """Deselect the current primary audio source."""
        if self._primary_audio_id and self._primary_audio_id in self._sources:
            self._sources[self._primary_audio_id].is_primary_audio = False
        self._primary_audio_id = None

    def clear_primary_video(self) -> None:
        """Deselect the current primary video source."""
        if self._primary_video_id and self._primary_video_id in self._sources:
            self._sources[self._primary_video_id].is_primary_video = False
        self._primary_video_id = None

    @property
    def primary_audio_id(self) -> Optional[str]:
        """``source_id`` of the current primary audio source, or ``None``."""
        return self._primary_audio_id

    @property
    def primary_video_id(self) -> Optional[str]:
        """``source_id`` of the current primary video source, or ``None``."""
        return self._primary_video_id

    def primary_audio(self) -> Optional[PerceptionSourceRecord]:
        """Return the primary audio source record, or ``None``."""
        if self._primary_audio_id is None:
            return None
        return self._sources.get(self._primary_audio_id)

    def primary_video(self) -> Optional[PerceptionSourceRecord]:
        """Return the primary video source record, or ``None``."""
        if self._primary_video_id is None:
            return None
        return self._sources.get(self._primary_video_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_sources(self) -> List[PerceptionSourceRecord]:
        """Return all registered source records (unordered)."""
        return list(self._sources.values())

    def active_sources(self) -> List[PerceptionSourceRecord]:
        """Return records for all currently-active sources."""
        return [r for r in self._sources.values() if r.is_active]

    def sources_by_type(
        self, source_type: PerceptionSourceType
    ) -> List[PerceptionSourceRecord]:
        """Return all records with the given ``source_type``."""
        return [
            r for r in self._sources.values() if r.source_type == source_type
        ]

    def sources_by_modality(
        self, modality: SourceModality
    ) -> List[PerceptionSourceRecord]:
        """Return all records with the given ``modality`` (including MULTI)."""
        compatible = {modality, SourceModality.MULTI}
        return [r for r in self._sources.values() if r.modality in compatible]

    def degraded_sources(self) -> List[PerceptionSourceRecord]:
        """Return sources whose health is DEGRADED or UNAVAILABLE."""
        return [
            r
            for r in self._sources.values()
            if r.health
            in (SourceHealthStatus.DEGRADED, SourceHealthStatus.UNAVAILABLE)
        ]

    # ------------------------------------------------------------------
    # Snapshot / diagnostics
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a diagnostics-safe, JSON-serialisable registry snapshot.

        The snapshot includes:
        - ``sources``: list of all source records (as dicts)
        - ``primary_audio_id`` / ``primary_video_id``
        - ``active_count``, ``total_count``, ``degraded_count``
        - ``snapshot_at``: wall-clock timestamp

        No binary payloads are included.  This method never raises.
        """
        try:
            sources_list = [r.to_dict() for r in self._sources.values()]
            active_count = sum(1 for r in self._sources.values() if r.is_active)
            degraded_count = sum(
                1
                for r in self._sources.values()
                if r.health
                in (SourceHealthStatus.DEGRADED, SourceHealthStatus.UNAVAILABLE)
            )
            return {
                "snapshot_at": time.time(),
                "total_count": len(self._sources),
                "active_count": active_count,
                "degraded_count": degraded_count,
                "primary_audio_id": self._primary_audio_id,
                "primary_video_id": self._primary_video_id,
                "sources": sources_list,
            }
        except Exception as exc:  # pragma: no cover
            logger.debug(
                "PerceptionSourceRegistry.snapshot failed (non-fatal): %s", exc
            )
            return {
                "snapshot_at": time.time(),
                "error": str(exc),
                "sources": [],
            }
