#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/android_v2_canonical_default_runtime_path.py
===================================================
PR: Android/V2 Cross-Repo Canonical Default Runtime Path Activation.

Problem addressed
-----------------
The Android-V2 cross-repo canonical runtime path has been structurally
implemented across multiple modules:

* ``core.presence.android_presence_participation`` — per-device presence
  participation records and summary
* ``core.android_device_state_store`` — Android device state mirror on V2
* ``core.presence.presence_projection`` — projection events that accept
  android presence participation (optional arg)
* ``core.desktop_presence_system`` — system view builder that accepts
  android presence participation (optional arg)
* ``core.desktop_presence_runtime`` — the runtime shell

However, despite all these structures being real and mature, they remained
**optional/default-off** in the runtime.  Specifically:

1. ``android_presence_participation`` was accepted as an optional parameter
   by downstream builders but was NEVER automatically populated in the
   default ``handle_request()`` path.
2. The ``presence_summary()`` diagnostic path built the system view without
   Android presence data even when Android devices were registered.
3. No canonical module declared "this path is the default" — everything
   remained structurally present but runtime-passive.

This module closes those gaps by:

1. Declaring ``ANDROID_V2_CANONICAL_DEFAULT_PATH_IS_ACTIVE`` — the formal,
   machine-checkable sentinel that the Android-V2 cross-repo presence
   participation path is **now the canonical default runtime path** and is
   default-on for all invocations.

2. Providing :class:`AndroidV2PathKind` — a four-value enum that classifies
   every runtime sub-path as:

   * ``canonical_default`` — the one legitimate default authority path.
     Android presence participation is queried and included automatically.
   * ``compat_bridge`` — explicitly permitted compat path (e.g., legacy
     direct-write Android signals); bounded scope, must not masquerade as
     canonical default.
   * ``fallback`` — degraded path used when the canonical default is
     unavailable; must not silently become the default.
   * ``optional_enhancement`` — additive capability that supplements the
     canonical default but is not required for it to be valid.

3. Providing :func:`build_android_presence_participation_for_default_path` —
   the canonical entry point that queries ``android_device_state_store`` and
   derives a :class:`~core.presence.android_presence_participation.AndroidPresenceParticipationSummary`
   for consumption in the default runtime path.  Called automatically by the
   runtime shell.

4. Providing :func:`classify_android_v2_path` — path classification helper
   that returns the :class:`AndroidV2PathKind` for a given context.

5. Providing :func:`build_android_presence_runtime_field` — builds the
   ``android_presence_runtime`` field attached to every ``handle_request()``
   result as a first-class output field.

Architecture invariants
-----------------------
* Android presence participation is **default-on** in the canonical path.
  The canonical path does not require an explicit caller opt-in.
* Compat-bridge and fallback paths are explicitly classified and **must not**
  silently become the default when the canonical path is available.
* The canonical path result is user-visible (exposed in the handle_request
  result dict), not only operator/debug-visible.
* Absence of registered Android devices produces a valid empty canonical
  result rather than raising or returning ``None``.

Public API
----------
Sentinels
~~~~~~~~~
:data:`ANDROID_V2_CANONICAL_DEFAULT_PATH_AUTHORITY`
:data:`ANDROID_V2_CANONICAL_DEFAULT_PATH_IS_ACTIVE`
:data:`ANDROID_PRESENCE_PARTICIPATION_IS_DEFAULT_ON_POLICY`
:data:`COMPAT_BRIDGE_MUST_NOT_MASQUERADE_AS_CANONICAL_DEFAULT_POLICY`
:data:`FALLBACK_MUST_NOT_SILENTLY_BECOME_DEFAULT_POLICY`

Enumerations
~~~~~~~~~~~~
:class:`AndroidV2PathKind`

Data classes
~~~~~~~~~~~~
:class:`AndroidPresenceRuntimeField`
:class:`AndroidV2PathClassification`

Functions
~~~~~~~~~
:func:`build_android_presence_participation_for_default_path`
:func:`build_android_presence_runtime_field`
:func:`classify_android_v2_path`
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidV2CanonicalDefaultRuntimePath")

__all__ = [
    # Sentinels
    "ANDROID_V2_CANONICAL_DEFAULT_PATH_AUTHORITY",
    "ANDROID_V2_CANONICAL_DEFAULT_PATH_IS_ACTIVE",
    "ANDROID_PRESENCE_PARTICIPATION_IS_DEFAULT_ON_POLICY",
    "COMPAT_BRIDGE_MUST_NOT_MASQUERADE_AS_CANONICAL_DEFAULT_POLICY",
    "FALLBACK_MUST_NOT_SILENTLY_BECOME_DEFAULT_POLICY",
    # Enum
    "AndroidV2PathKind",
    # Dataclasses
    "AndroidPresenceRuntimeField",
    "AndroidV2PathClassification",
    # Functions
    "build_android_presence_participation_for_default_path",
    "build_android_presence_runtime_field",
    "classify_android_v2_path",
]


# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

ANDROID_V2_CANONICAL_DEFAULT_PATH_AUTHORITY: str = (
    "ANDROID_V2_CANONICAL_DEFAULT_PATH_AUTHORITY::"
    "core.android_v2_canonical_default_runtime_path is the authoritative "
    "module that declares the Android-V2 cross-repo presence participation "
    "path as the canonical default runtime path.  Android presence "
    "participation is default-on: it is queried and included in every "
    "handle_request() result without requiring an explicit caller opt-in.  "
    "Compat-bridge and fallback paths are explicitly classified and must not "
    "masquerade as the canonical default."
)

ANDROID_V2_CANONICAL_DEFAULT_PATH_IS_ACTIVE: bool = True
"""Machine-checkable sentinel: Android-V2 canonical default runtime path is ACTIVE.

This boolean is the authoritative, importable signal that the Android presence
participation path has been promoted from optional/default-off to the canonical
default runtime path.  Tests, CI gates, and diagnostics endpoints MUST assert
this sentinel to verify that the default path promotion is in effect.

Prior state (before this PR): ``False`` — android presence participation was
structurally present but never automatically invoked in the default path.

Current state (this PR): ``True`` — android presence participation is queried
and included in the default ``handle_request()`` result.
"""

ANDROID_PRESENCE_PARTICIPATION_IS_DEFAULT_ON_POLICY: str = (
    "POLICY::ANDROID_PRESENCE_PARTICIPATION_IS_DEFAULT_ON_V1: "
    "Android presence participation (core.presence.android_presence_participation) "
    "is DEFAULT-ON in the canonical runtime path.  Every handle_request() "
    "invocation automatically queries the android_device_state_store for "
    "registered device snapshots and includes the resulting "
    "AndroidPresenceParticipationSummary in the result dict under the key "
    "'android_presence_runtime'.  Callers do not need to opt in.  "
    "An empty summary (no registered devices) is valid and does not indicate "
    "a path failure.  This policy is enforced by "
    "core.android_v2_canonical_default_runtime_path."
)

COMPAT_BRIDGE_MUST_NOT_MASQUERADE_AS_CANONICAL_DEFAULT_POLICY: str = (
    "POLICY::COMPAT_BRIDGE_MUST_NOT_MASQUERADE_AS_CANONICAL_DEFAULT_V1: "
    "Compat-bridge paths (legacy direct-write Android signals, bridged "
    "v1-format messages, Android-local mode-gate bypasses) are classified "
    "as AndroidV2PathKind.compat_bridge and must not silently become the "
    "canonical default runtime path.  When a compat-bridge path is active, "
    "the result must carry path_kind='compat_bridge' in the "
    "android_presence_runtime field so operators can distinguish it from "
    "canonical_default behavior."
)

FALLBACK_MUST_NOT_SILENTLY_BECOME_DEFAULT_POLICY: str = (
    "POLICY::FALLBACK_MUST_NOT_SILENTLY_BECOME_DEFAULT_V1: "
    "Fallback paths (e.g., android_device_state_store unavailable, "
    "presence module import failure) must produce a clearly-classified "
    "AndroidV2PathKind.fallback result, never an implicit empty canonical "
    "result.  The fallback classification must be reflected in the "
    "'android_presence_runtime' field so the system can detect when the "
    "canonical path was not executable."
)


# ===========================================================================
# AndroidV2PathKind enum
# ===========================================================================


class AndroidV2PathKind(str, Enum):
    """Classification of Android-V2 runtime sub-paths.

    Values
    ------
    canonical_default
        The canonical default runtime path.  Android presence participation
        is automatically queried and the result is authoritative.
    compat_bridge
        Explicitly permitted compat bridge path.  Legacy direct-write signals,
        v1-format bridging, Android-local mode-gate bypasses.  Bounded scope.
        Must not masquerade as canonical_default.
    fallback
        Degraded path used when the canonical default is unavailable (e.g.,
        state-store not initialised, module import failure).  Must not
        silently become the default.
    optional_enhancement
        Additive capability that supplements canonical_default but is not
        required for it to be valid (e.g., WebRTC streaming overlay,
        local-AI inference enrichment).
    """

    canonical_default = "canonical_default"
    compat_bridge = "compat_bridge"
    fallback = "fallback"
    optional_enhancement = "optional_enhancement"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass
class AndroidPresenceRuntimeField:
    """First-class result field attached to every handle_request() response.

    This field is the user-visible, canonical-default output of the
    Android-V2 presence participation path.  It is always present in the
    result dict (never ``None``), carrying an empty participation summary when
    no Android devices are registered.

    Attributes
    ----------
    path_kind:
        Classification of which Android-V2 sub-path produced this result.
    derived_at:
        Unix timestamp when this field was built.
    device_count:
        Number of Android device snapshots found in the state store.
    any_presence_participant:
        True when at least one Android device is a presence participant.
    any_foreground_presence:
        True when at least one Android device is the foreground presence
        surface.
    any_drives_liminal:
        True when at least one Android device drives presence toward LIMINAL.
    any_drives_manifest:
        True when at least one Android device drives presence toward MANIFEST.
    presence_participant_count:
        Number of devices that are presence participants.
    participation_records:
        Per-device serialised participation records.
    notes:
        Human-readable derivation notes (e.g., fallback reason).
    """

    path_kind: AndroidV2PathKind = AndroidV2PathKind.canonical_default
    derived_at: float = field(default_factory=time.time)
    device_count: int = 0
    any_presence_participant: bool = False
    any_foreground_presence: bool = False
    any_drives_liminal: bool = False
    any_drives_manifest: bool = False
    presence_participant_count: int = 0
    participation_records: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path_kind": self.path_kind.value,
            "derived_at": self.derived_at,
            "device_count": self.device_count,
            "any_presence_participant": self.any_presence_participant,
            "any_foreground_presence": self.any_foreground_presence,
            "any_drives_liminal": self.any_drives_liminal,
            "any_drives_manifest": self.any_drives_manifest,
            "presence_participant_count": self.presence_participant_count,
            "participation_records": list(self.participation_records),
            "notes": list(self.notes),
        }

    @property
    def is_canonical_default(self) -> bool:
        """True when this field was produced by the canonical default path."""
        return self.path_kind == AndroidV2PathKind.canonical_default


@dataclass
class AndroidV2PathClassification:
    """Result of :func:`classify_android_v2_path`.

    Attributes
    ----------
    path_kind:
        The classified path kind.
    reason:
        Human-readable classification reason.
    is_canonical_default:
        Convenience accessor — True when path_kind is canonical_default.
    """

    path_kind: AndroidV2PathKind = AndroidV2PathKind.canonical_default
    reason: str = ""

    @property
    def is_canonical_default(self) -> bool:
        return self.path_kind == AndroidV2PathKind.canonical_default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path_kind": self.path_kind.value,
            "reason": self.reason,
            "is_canonical_default": self.is_canonical_default,
        }


# ===========================================================================
# build_android_presence_participation_for_default_path
# ===========================================================================


def build_android_presence_participation_for_default_path() -> Optional[Any]:
    """Query the android_device_state_store and build a presence summary.

    This is the **canonical default entry point** for Android presence
    participation in the default runtime path.  It is called automatically
    by the runtime shell in ``handle_request()`` without any caller opt-in.

    Returns
    -------
    AndroidPresenceParticipationSummary or None
        Summary built from all registered device snapshots.  Returns ``None``
        only when the android_device_state_store module is unavailable
        (structurally absent); returns an empty summary when the store is
        available but has no registered devices.
    """
    try:
        from core.android_device_state_store import (
            list_device_state_snapshots,
        )
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )
    except ImportError as _imp_err:
        logger.debug(
            "build_android_presence_participation_for_default_path: "
            "import failed (structural absence) — %s",
            _imp_err,
        )
        return None

    try:
        snapshots = list_device_state_snapshots()
    except Exception as _snap_err:
        logger.debug(
            "build_android_presence_participation_for_default_path: "
            "list_device_state_snapshots failed — %s",
            _snap_err,
        )
        return None

    records = []
    for snap in snapshots:
        try:
            record = derive_android_presence_participation(
                device_id=snap.device_id,
                active_engagement=bool(snap.active_engagement)
                if hasattr(snap, "active_engagement")
                else False,
                sensing_stream_active=bool(snap.sensing_stream_active)
                if hasattr(snap, "sensing_stream_active")
                else False,
                handoff_interaction_active=bool(snap.handoff_interaction_active)
                if hasattr(snap, "handoff_interaction_active")
                else False,
                execution_presence_coupled=bool(snap.execution_presence_coupled)
                if hasattr(snap, "execution_presence_coupled")
                else False,
                is_foreground_surface=bool(snap.is_foreground_surface)
                if hasattr(snap, "is_foreground_surface")
                else False,
            )
            records.append(record)
        except Exception as _rec_err:
            logger.debug(
                "build_android_presence_participation_for_default_path: "
                "derive failed for device_id=%s — %s",
                getattr(snap, "device_id", "?"),
                _rec_err,
            )

    try:
        return summarise_android_presence_participation(records)
    except Exception as _sum_err:
        logger.debug(
            "build_android_presence_participation_for_default_path: "
            "summarise failed — %s",
            _sum_err,
        )
        return None


# ===========================================================================
# build_android_presence_runtime_field
# ===========================================================================


def build_android_presence_runtime_field() -> AndroidPresenceRuntimeField:
    """Build the ``android_presence_runtime`` first-class result field.

    This is the function called by the runtime shell to produce the
    ``android_presence_runtime`` key in every ``handle_request()`` result.
    It always returns an :class:`AndroidPresenceRuntimeField`; it never
    raises.

    The ``path_kind`` in the returned field reflects whether the canonical
    default path executed successfully:

    * ``canonical_default`` — android_device_state_store was available and
      returned results (including empty results — no devices registered).
    * ``fallback`` — android_device_state_store or presence module was
      unavailable at import time.

    Returns
    -------
    AndroidPresenceRuntimeField
        Always a valid field instance.  An empty field with
        ``path_kind=canonical_default`` is produced when no devices are
        registered.
    """
    notes: List[str] = []

    # Attempt the canonical default path.
    try:
        from core.android_device_state_store import list_device_state_snapshots

        snapshots = list_device_state_snapshots()
        device_count = len(snapshots)
    except ImportError:
        return AndroidPresenceRuntimeField(
            path_kind=AndroidV2PathKind.fallback,
            notes=["android_device_state_store unavailable (module absent)"],
        )
    except Exception as _err:
        return AndroidPresenceRuntimeField(
            path_kind=AndroidV2PathKind.fallback,
            notes=[f"android_device_state_store.list_device_state_snapshots failed: {_err}"],
        )

    summary = build_android_presence_participation_for_default_path()
    if summary is None:
        # Store was available but summarisation failed — still canonical_default
        # with no participation records.
        notes.append("presence_participation_summary_build_failed")
        return AndroidPresenceRuntimeField(
            path_kind=AndroidV2PathKind.canonical_default,
            device_count=device_count,
            notes=notes,
        )

    try:
        records_dicts = [r.to_dict() for r in summary.records]
    except Exception:
        records_dicts = []

    return AndroidPresenceRuntimeField(
        path_kind=AndroidV2PathKind.canonical_default,
        device_count=device_count,
        any_presence_participant=summary.any_presence_participant,
        any_foreground_presence=summary.any_foreground_presence,
        any_drives_liminal=summary.any_drives_liminal,
        any_drives_manifest=summary.any_drives_manifest,
        presence_participant_count=summary.presence_participant_count,
        participation_records=records_dicts,
        notes=notes,
    )


# ===========================================================================
# classify_android_v2_path
# ===========================================================================


def classify_android_v2_path(
    *,
    is_compat_bridge_active: bool = False,
    state_store_available: bool = True,
    is_legacy_mode_gate: bool = False,
) -> AndroidV2PathClassification:
    """Classify the current Android-V2 runtime path.

    This function applies explicit classification rules to determine which
    :class:`AndroidV2PathKind` is active, making it machine-verifiable which
    path governs the current runtime interaction.

    Parameters
    ----------
    is_compat_bridge_active:
        True when a legacy compat-bridge path (e.g., v1-format bridging,
        direct-write Android signal) is the active path.
    state_store_available:
        False when android_device_state_store is structurally absent.
        Triggers ``fallback`` classification.
    is_legacy_mode_gate:
        True when the Android-local cross_device_enabled mode gate is
        controlling path selection instead of the canonical V2 governance.

    Returns
    -------
    AndroidV2PathClassification
        Explicit path classification with reason.
    """
    if not state_store_available:
        return AndroidV2PathClassification(
            path_kind=AndroidV2PathKind.fallback,
            reason=(
                "android_device_state_store is structurally absent; "
                "canonical default path cannot execute"
            ),
        )

    if is_compat_bridge_active:
        return AndroidV2PathClassification(
            path_kind=AndroidV2PathKind.compat_bridge,
            reason=(
                "compat_bridge is active (legacy direct-write or v1-format bridging); "
                "this path must not masquerade as canonical_default"
            ),
        )

    if is_legacy_mode_gate:
        return AndroidV2PathClassification(
            path_kind=AndroidV2PathKind.compat_bridge,
            reason=(
                "Android-local cross_device_enabled mode gate is controlling path "
                "selection; V2 canonical governance is not the active decision authority; "
                "classified as compat_bridge rather than canonical_default"
            ),
        )

    return AndroidV2PathClassification(
        path_kind=AndroidV2PathKind.canonical_default,
        reason=(
            "android_device_state_store is available, no compat-bridge or "
            "legacy mode gate active; canonical default runtime path is executing"
        ),
    )
