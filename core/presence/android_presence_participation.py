#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/presence/android_presence_participation.py
================================================
Android Presence Participation / Projection Model
--------------------------------------------------

This module establishes the **canonical dual-repo presence participation
model** for Android devices: a runtime-consumable structure that interprets
Android device states as *presence participation* rather than ordinary device
metadata or execution-node status.

Design
------
There are two fundamentally distinct ways an Android device can relate to the
subject's existence:

1. **Execution participant** — the Android device is a runtime node that
   accepts and runs tasks delegated from V2.  This is what
   ``AndroidNetworkParticipationTier`` and the cross-device execution chain
   already model.

2. **Presence participant** — the Android device contributes to the *subject's
   existence posture*: the way the subject is present, perceptible, and
   expressing itself across the dual-repo surface.  This is *not* derivable
   from execution readiness alone.

``AndroidPresenceParticipationMode`` names the three canonical participation
levels; ``AndroidPresenceParticipationRecord`` is the runtime-consumable
canonical structure that carries one device's presence participation state;
``derive_android_presence_participation`` produces that record from the
signals already available in V2 and on Android devices.

When an Android device reaches ``PRESENCE_PARTICIPANT`` or
``FOREGROUND_PRESENCE`` mode the V2 presence layer **must** change its
behaviour — presence mode selection, projection intensity, and foreground
payload composition all differ when Android presence participation is active.

Key distinctions from prior work
---------------------------------
- ``AndroidNetworkParticipationTier`` → execution/network layer (unchanged).
- ``AndroidPresenceSignals`` in ``desktop_existence_surface`` → aggregate
  device-count signals used for existence-verdict calculation (unchanged).
- **This module** → per-device canonical *presence participation* semantics,
  the first structure that explicitly distinguishes Android-as-presence-face
  from Android-as-execution-node.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Presence.AndroidParticipation")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

ANDROID_PRESENCE_PARTICIPATION_AUTHORITY: str = (
    "ANDROID_PRESENCE_PARTICIPATION_AUTHORITY::"
    "core.presence.android_presence_participation is the canonical source "
    "for interpreting Android device states as subject presence participation. "
    "Do not substitute execution/network tier for presence participation."
)

# ---------------------------------------------------------------------------
# AndroidPresenceParticipationMode
# ---------------------------------------------------------------------------


class AndroidPresenceParticipationMode(str, Enum):
    """Canonical participation mode for an Android device in the presence layer.

    This enum is the primary discriminator between Android-as-execution-node
    and Android-as-presence-participant.  It is intentionally separate from
    ``AndroidNetworkParticipationTier`` (execution/network) and from ordinary
    device-online/offline status.

    Values
    ------
    EXECUTION_ONLY:
        The Android device is reachable and may execute tasks, but it is *not*
        contributing to the subject's presence posture.  Presence-related
        behaviour is unaffected by this device.
    PRESENCE_PARTICIPANT:
        The Android device is actively contributing to the subject's existence
        expression — through sensing participation, active engagement, or
        handoff/interaction state.  The V2 presence state machine **must**
        account for this device when computing presence mode.
    FOREGROUND_PRESENCE:
        The Android device is the foreground presence surface for the subject
        right now — the subject's manifest presence is primarily expressed
        through this device.  Presence projection intensity to this device
        is elevated to FULL.
    """

    EXECUTION_ONLY = "execution_only"
    PRESENCE_PARTICIPANT = "presence_participant"
    FOREGROUND_PRESENCE = "foreground_presence"


# ---------------------------------------------------------------------------
# AndroidPresenceParticipationRecord
# ---------------------------------------------------------------------------


@dataclass
class AndroidPresenceParticipationRecord:
    """Canonical presence participation record for a single Android device.

    This is the **runtime-consumable** structure that carries one Android
    device's presence participation state.  It is the first structure in the
    V2 codebase that explicitly distinguishes Android-as-presence-participant
    from Android-as-execution-node.

    Attributes
    ----------
    device_id:
        Android device identifier.
    participation_mode:
        The canonical participation mode (see :class:`AndroidPresenceParticipationMode`).
    active_engagement:
        The device is in an active user-interaction / foreground engagement
        state on the Android side.  Drives presence toward LIMINAL or MANIFEST.
    sensing_stream_active:
        The device is actively contributing sensing / perception streams
        (camera, microphone, screen OCR, etc.) to the subject's cognitive
        pipeline.  Drives presence toward LIMINAL.
    handoff_interaction_active:
        The device is in a handoff or cross-device interaction state — the
        subject is transitioning between the Android surface and other
        presence surfaces.  Drives presence toward LIMINAL.
    execution_presence_coupled:
        The device is executing a task *and* that execution is
        presence-coupled — meaning the execution result will be expressed on
        the device's own presence surface (not just silently delegated).
        Drives presence toward MANIFEST.
    is_foreground_surface:
        The device is the primary foreground surface for the subject right now.
        Sets participation_mode to FOREGROUND_PRESENCE when combined with
        active_engagement or execution_presence_coupled.
    derived_at:
        Unix epoch when this record was derived.
    _source:
        Module that produced this record.
    """

    device_id: str = ""
    participation_mode: AndroidPresenceParticipationMode = AndroidPresenceParticipationMode.EXECUTION_ONLY
    active_engagement: bool = False
    sensing_stream_active: bool = False
    handoff_interaction_active: bool = False
    execution_presence_coupled: bool = False
    is_foreground_surface: bool = False
    derived_at: float = field(default_factory=time.time)
    _source: str = "core.presence.android_presence_participation"

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def is_presence_participant(self) -> bool:
        """True when this device contributes to subject presence semantics."""
        return self.participation_mode in (
            AndroidPresenceParticipationMode.PRESENCE_PARTICIPANT,
            AndroidPresenceParticipationMode.FOREGROUND_PRESENCE,
        )

    @property
    def drives_liminal(self) -> bool:
        """True when this device's state should push presence toward LIMINAL."""
        return (
            self.is_presence_participant
            and (
                self.active_engagement
                or self.sensing_stream_active
                or self.handoff_interaction_active
            )
        )

    @property
    def drives_manifest(self) -> bool:
        """True when this device's state should push presence toward MANIFEST."""
        return self.is_presence_participant and self.execution_presence_coupled

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "participation_mode": self.participation_mode.value,
            "active_engagement": self.active_engagement,
            "sensing_stream_active": self.sensing_stream_active,
            "handoff_interaction_active": self.handoff_interaction_active,
            "execution_presence_coupled": self.execution_presence_coupled,
            "is_foreground_surface": self.is_foreground_surface,
            "is_presence_participant": self.is_presence_participant,
            "drives_liminal": self.drives_liminal,
            "drives_manifest": self.drives_manifest,
            "derived_at": self.derived_at,
            "_source": self._source,
        }


# ---------------------------------------------------------------------------
# AndroidPresenceParticipationSummary
# ---------------------------------------------------------------------------


@dataclass
class AndroidPresenceParticipationSummary:
    """Aggregated presence participation summary across all Android devices.

    This is the object consumed by the V2 presence state machine and the
    PresenceDirector.  It collapses per-device records into the signals
    needed for presence-mode decisions.

    Attributes
    ----------
    records:
        Per-device participation records.
    any_presence_participant:
        True when at least one Android device is a presence participant.
    any_foreground_presence:
        True when at least one Android device is the foreground presence surface.
    any_drives_liminal:
        True when at least one Android device drives presence toward LIMINAL.
    any_drives_manifest:
        True when at least one Android device drives presence toward MANIFEST.
    presence_participant_count:
        Number of devices that are presence participants.
    """

    records: List[AndroidPresenceParticipationRecord] = field(default_factory=list)
    any_presence_participant: bool = False
    any_foreground_presence: bool = False
    any_drives_liminal: bool = False
    any_drives_manifest: bool = False
    presence_participant_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "any_presence_participant": self.any_presence_participant,
            "any_foreground_presence": self.any_foreground_presence,
            "any_drives_liminal": self.any_drives_liminal,
            "any_drives_manifest": self.any_drives_manifest,
            "presence_participant_count": self.presence_participant_count,
            "records": [r.to_dict() for r in self.records],
        }


# ---------------------------------------------------------------------------
# derive_android_presence_participation
# ---------------------------------------------------------------------------


def derive_android_presence_participation(
    device_id: str,
    *,
    active_engagement: bool = False,
    sensing_stream_active: bool = False,
    handoff_interaction_active: bool = False,
    execution_presence_coupled: bool = False,
    is_foreground_surface: bool = False,
    execution_only_override: bool = False,
) -> AndroidPresenceParticipationRecord:
    """Derive a canonical presence participation record for one Android device.

    This function is the boundary at which Android device state stops being
    device metadata and begins being interpreted as subject presence
    participation.

    The presence participation mode is derived as follows:

    - ``EXECUTION_ONLY`` when ``execution_only_override`` is True, or when
      none of the presence-signal flags are set.
    - ``FOREGROUND_PRESENCE`` when ``is_foreground_surface`` is True and at
      least one of ``active_engagement`` or ``execution_presence_coupled`` is
      True.
    - ``PRESENCE_PARTICIPANT`` otherwise (at least one presence-signal flag
      is set but not foreground).

    Parameters
    ----------
    device_id:
        Android device identifier.
    active_engagement:
        Device is in active user-interaction / foreground-engagement state.
    sensing_stream_active:
        Device is contributing sensing/perception streams to the cognitive
        pipeline.
    handoff_interaction_active:
        Device is in a handoff or cross-device interaction state.
    execution_presence_coupled:
        Device is executing a presence-coupled task (result expressed on its
        own presence surface).
    is_foreground_surface:
        Device is the current foreground presence surface.
    execution_only_override:
        Force ``EXECUTION_ONLY`` mode regardless of other flags (use when the
        caller has determined that Android is only an execution node for this
        interaction).

    Returns
    -------
    AndroidPresenceParticipationRecord
        Canonical presence participation record.
    """
    any_presence_signal = (
        active_engagement
        or sensing_stream_active
        or handoff_interaction_active
        or execution_presence_coupled
        or is_foreground_surface
    )

    if execution_only_override or not any_presence_signal:
        mode = AndroidPresenceParticipationMode.EXECUTION_ONLY
    elif is_foreground_surface and (active_engagement or execution_presence_coupled):
        mode = AndroidPresenceParticipationMode.FOREGROUND_PRESENCE
    else:
        mode = AndroidPresenceParticipationMode.PRESENCE_PARTICIPANT

    return AndroidPresenceParticipationRecord(
        device_id=device_id,
        participation_mode=mode,
        active_engagement=active_engagement,
        sensing_stream_active=sensing_stream_active,
        handoff_interaction_active=handoff_interaction_active,
        execution_presence_coupled=execution_presence_coupled,
        is_foreground_surface=is_foreground_surface,
    )


def summarise_android_presence_participation(
    records: List[AndroidPresenceParticipationRecord],
) -> AndroidPresenceParticipationSummary:
    """Aggregate per-device records into a presence-layer summary.

    Parameters
    ----------
    records:
        List of per-device :class:`AndroidPresenceParticipationRecord` values.

    Returns
    -------
    AndroidPresenceParticipationSummary
        Aggregated summary used by the V2 presence state machine and director.
    """
    any_presence_participant = any(r.is_presence_participant for r in records)
    any_foreground_presence = any(
        r.participation_mode == AndroidPresenceParticipationMode.FOREGROUND_PRESENCE
        for r in records
    )
    any_drives_liminal = any(r.drives_liminal for r in records)
    any_drives_manifest = any(r.drives_manifest for r in records)
    presence_participant_count = sum(1 for r in records if r.is_presence_participant)

    return AndroidPresenceParticipationSummary(
        records=list(records),
        any_presence_participant=any_presence_participant,
        any_foreground_presence=any_foreground_presence,
        any_drives_liminal=any_drives_liminal,
        any_drives_manifest=any_drives_manifest,
        presence_participant_count=presence_participant_count,
    )
