"""
core.desktop_existence_surface — Canonical Assistant-Like Existence Surface
============================================================================

PR-2: Desktop Existence Surface / Assistant Presence Unification

**Purpose**

The Galaxy dual-repo system contains multiple real state families related to
lifecycle, presence, shell-clothing, continuous-background cognition, and
Android carrier signals.  These families existed independently with no shared
coherent external projection.  This module unifies them into one
*canonical existence surface* for the unified subject.

**State families unified here (all grounded in current merged code)**

1. **Subject lifecycle tri-state** — ``TriState`` (SILENT / LIMINAL / MANIFEST)
   owned by :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`.
   Read via :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.presence_summary`.

2. **UI shell / clothing state** — ``SystemState`` (DORMANT / ISLAND /
   SIDESHEET / FULLAGENT) owned by
   :class:`~system_integration.state_machine_ui_integration.SystemStateMachine`.
   Read via :attr:`~system_integration.state_machine_ui_integration.SystemStateMachine.current_state`.

3. **Continuum posture** — ``tri_state_phase`` + ``runtime_domain`` owned by
   ``ContinuumOrchestrator`` inside :class:`~core.openclawd.OpenClawd`.
   Read via :func:`~core.projection.build_runtime_projection` (same source
   path used by :mod:`~core.routes.projection`).

4. **Continuous cognitive field** — ``activation``, ``intent_strength``,
   ``manifest_pressure``, ``stability`` owned by
   :class:`~core.cognitive.cognitive_field_engine.CognitiveFieldEngine` /
   :class:`~core.cognitive.continuous_state.CognitiveState`.
   Read via ``get_cognitive_state().snapshot()``.

5. **Android presence signals** — ``DeviceStateSnapshot`` inventory from
   :mod:`~core.android_device_state_store`.
   Read via ``list_device_state_snapshots()`` + ``get_device_ecosystem_summary()``.

**What this module is NOT**

- It is NOT a second presence system.  :class:`DesktopExistenceSurfaceBuilder`
  reads from existing canonical singletons; it never writes state.
- It does NOT introduce new state machines or enums.  The
  :class:`ExistenceProjection` is a *derived, read-only* verdict computed
  from the above families — not a new authoritative state.
- It does NOT invent unsupported assistant modes.  Every field in
  :class:`DesktopExistenceSurface` is directly traceable to a source singleton.

**Integration with PR-1**

:func:`build_desktop_existence_surface` is called by
:mod:`~core.unified_panel_aggregation` (PR-1) so the existence surface is
included as a sub-section of the unified panel payload.
:mod:`~core.routes.existence` exposes a dedicated read-only endpoint:
``GET /api/v1/existence/surface``.

Public API
----------
Authority sentinels::

    DESKTOP_EXISTENCE_SURFACE_AUTHORITY
    EXISTENCE_SURFACE_SCHEMA_VERSION

Dataclasses::

    SubjectLifecycleSnapshot    — state family 1: TriState / runtime lifecycle
    ShellClothingSnapshot       — state family 2: SystemState / UI clothing
    ContinuumPostureSnapshot    — state family 3: tri_state_phase / runtime_domain
    CognitiveFieldSnapshot      — state family 4: continuous cognitive field
    AndroidPresenceSignals      — state family 5: Android carrier presence
    ExistenceProjection         — derived verdict (read-only, not a new state)
    DesktopExistenceSurface     — unified canonical existence surface

Class::

    DesktopExistenceSurfaceBuilder  — builds DesktopExistenceSurface from singletons

Helpers::

    build_desktop_existence_surface() -> DesktopExistenceSurface
    get_desktop_existence_surface_builder() -> DesktopExistenceSurfaceBuilder
    reset_desktop_existence_surface_builder() -> None   # testing only
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DesktopExistenceSurface")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

DESKTOP_EXISTENCE_SURFACE_AUTHORITY: str = (
    "DESKTOP_EXISTENCE_SURFACE_V1: "
    "core.desktop_existence_surface is the canonical unified existence surface "
    "for the Galaxy assistant.  It derives a single coherent assistant-like "
    "existence projection from five real state families present in merged code: "
    "(1) subject lifecycle tri-state (DesktopPresenceRuntime), "
    "(2) UI shell clothing state (SystemStateMachine/SystemState), "
    "(3) continuum posture (ContinuumOrchestrator tri_state_phase/runtime_domain), "
    "(4) continuous cognitive field (CognitiveFieldEngine/CognitiveState), "
    "(5) Android presence signals (android_device_state_store).  "
    "This module reads from existing canonical singletons and NEVER introduces "
    "a second presence system or writes state."
)

EXISTENCE_SURFACE_SCHEMA_VERSION: str = "1.0"

# ---------------------------------------------------------------------------
# State-family snapshot dataclasses
# ---------------------------------------------------------------------------
# Each snapshot carries a ``_source`` field naming the canonical module it
# was read from.  This makes provenance machine-verifiable.
# ---------------------------------------------------------------------------


@dataclass
class SubjectLifecycleSnapshot:
    """Snapshot of the subject lifecycle tri-state (state family 1).

    Source: :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`
    via :meth:`presence_summary`.

    Values of ``dominant_tristate`` are the canonical TriState string values:
    ``"silent"`` / ``"liminal"`` / ``"manifest"``.
    """

    dominant_tristate: str = "silent"
    active_session_count: int = 0
    tristate_distribution: Dict[str, int] = field(default_factory=dict)
    _source: str = "desktop_presence_runtime"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dominant_tristate": self.dominant_tristate,
            "active_session_count": self.active_session_count,
            "tristate_distribution": dict(self.tristate_distribution),
            "_source": self._source,
        }


@dataclass
class ShellClothingSnapshot:
    """Snapshot of the UI shell / clothing state (state family 2).

    Source: :class:`~system_integration.state_machine_ui_integration.SystemStateMachine`
    via :attr:`current_state`.

    Values of ``shell_state`` are the canonical SystemState string values:
    ``"dormant"`` / ``"island"`` / ``"sidesheet"`` / ``"fullagent"``.

    This state describes *how the desktop clothing is rendered*, not the
    subject's lifecycle.
    """

    shell_state: str = "dormant"
    _source: str = "state_machine_ui_integration"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shell_state": self.shell_state,
            "_source": self._source,
        }


@dataclass
class ContinuumPostureSnapshot:
    """Snapshot of the OpenClawd continuum posture (state family 3).

    Source: :func:`~core.projection.build_runtime_projection` (same path
    used by :mod:`~core.routes.projection` and
    :mod:`~core.unified_panel_aggregation`).

    ``tri_state_phase`` and ``runtime_domain`` are the internal state-protocol
    detail owned by ``ContinuumOrchestrator`` — they are distinct from both
    the subject lifecycle tri-state and the UI shell state.
    """

    tri_state_phase: str = ""
    runtime_domain: Optional[str] = None
    presence_intensity: float = 0.0
    coherence: float = 0.0
    _source: str = "continuum_orchestrator"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tri_state_phase": self.tri_state_phase,
            "runtime_domain": self.runtime_domain,
            "presence_intensity": self.presence_intensity,
            "coherence": self.coherence,
            "_source": self._source,
        }


@dataclass
class CognitiveFieldSnapshot:
    """Snapshot of the continuous cognitive field (state family 4).

    Source: :class:`~core.cognitive.cognitive_field_engine.CognitiveFieldEngine`
    + :class:`~core.cognitive.continuous_state.CognitiveState`.

    The cognitive field represents the subject's sustained background presence
    even when no active request is in flight.  ``manifest_pressure`` is the
    accumulated signal driving toward the manifest phase.  ``is_running``
    indicates whether the background tick loop is active.
    """

    activation: float = 0.0
    intent_strength: float = 0.0
    manifest_pressure: float = 0.0
    stability: float = 0.0
    is_running: bool = False
    tick_count: int = 0
    _source: str = "cognitive_field_engine"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activation": self.activation,
            "intent_strength": self.intent_strength,
            "manifest_pressure": self.manifest_pressure,
            "stability": self.stability,
            "is_running": self.is_running,
            "tick_count": self.tick_count,
            "_source": self._source,
        }


@dataclass
class AndroidPresenceSignals:
    """Android-originated presence signals that participate in existence (state family 5).

    Source: :mod:`~core.android_device_state_store` via
    ``list_device_state_snapshots()`` and ``get_device_ecosystem_summary()``.

    These signals reflect the carrier/runtime side of assistant presence on
    Android devices.  ``local_loop_ready_count`` is the number of devices
    whose full local loop (plan/ground/act) is ready — a direct indicator
    that an Android-side execution surface is live.
    """

    total_devices_with_snapshot: int = 0
    local_loop_ready_count: int = 0
    model_ready_count: int = 0
    active_runtime_type_distribution: Dict[str, int] = field(default_factory=dict)
    _source: str = "android_device_state_store"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_devices_with_snapshot": self.total_devices_with_snapshot,
            "local_loop_ready_count": self.local_loop_ready_count,
            "model_ready_count": self.model_ready_count,
            "active_runtime_type_distribution": dict(self.active_runtime_type_distribution),
            "_source": self._source,
        }


# ---------------------------------------------------------------------------
# Derived existence projection
# ---------------------------------------------------------------------------


@dataclass
class ExistenceProjection:
    """Derived, read-only assistant presence verdict computed from all state families.

    **This is NOT a new state system.**  ``presence_verdict`` is a
    *derived projection* — a read-only summary of what the five real state
    families jointly say about the assistant's current existence on the
    desktop.  It does not add new authority or write any state.

    ``presence_verdict`` values
    ---------------------------
    ``"expressing"``
        The subject is in the MANIFEST tri-state phase — actively producing
        output, controlling devices, or expanding into a cross-device loop.
        Evidence: ``dominant_tristate == "manifest"`` from family 1,
        or ``shell_state`` is ``"fullagent"`` from family 2.

    ``"active"``
        The subject is in the LIMINAL tri-state phase (cognition/execution
        in progress), or the shell is expanded into SIDESHEET mode, or
        manifest_pressure is elevated, or continuum posture is non-idle.
        Evidence: ``dominant_tristate == "liminal"`` from family 1,
        ``shell_state`` in ``{"sidesheet"}`` from family 2,
        ``manifest_pressure > 0.4`` from family 4.

    ``"background"``
        The cognitive field engine is running its continuous background tick
        loop (sustained background presence), or Android devices have live
        local loops, or the shell is in ISLAND mode.
        Evidence: ``is_running == True`` from family 4,
        ``local_loop_ready_count > 0`` from family 5,
        ``shell_state == "island"`` from family 2.

    ``"dormant"``
        All families are at rest: subject is SILENT, shell is DORMANT,
        cognitive field is low, no Android loops active.

    ``contributing_families``
        List of family names that contributed non-default signals to the
        verdict.  Machine-verifiable provenance.
    """

    presence_verdict: str = "dormant"
    contributing_families: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "presence_verdict": self.presence_verdict,
            "contributing_families": list(self.contributing_families),
            "evidence": dict(self.evidence),
        }


# ---------------------------------------------------------------------------
# DesktopExistenceSurface — the unified canonical surface
# ---------------------------------------------------------------------------


@dataclass
class DesktopExistenceSurface:
    """Single canonical assistant-like existence surface.

    Combines the five real state families present in merged code into one
    coherent, serialisable existence model.  Downstream consumers (status
    boards, Android app, operator panels, unified panel endpoint) read from
    this surface instead of fanning out across the individual state families.

    Attributes
    ----------
    surface_id:
        Unique identifier for this surface snapshot instance.
    generated_at:
        Unix timestamp when this surface was built.
    schema_version:
        Schema version string (``"1.0"``).
    subject_lifecycle:
        State family 1 — TriState subject lifecycle snapshot.
    shell_clothing:
        State family 2 — SystemState UI shell clothing snapshot.
    continuum_posture:
        State family 3 — OpenClawd continuum posture snapshot.
    cognitive_field:
        State family 4 — CognitiveFieldEngine field snapshot.
    android_signals:
        State family 5 — Android device presence signals.
    existence_projection:
        Derived read-only verdict combining all five families.
    _source:
        Authority sentinel.
    """

    surface_id: str = field(
        default_factory=lambda: f"exist_{uuid.uuid4().hex[:12]}"
    )
    generated_at: float = field(default_factory=time.time)
    schema_version: str = EXISTENCE_SURFACE_SCHEMA_VERSION

    subject_lifecycle: SubjectLifecycleSnapshot = field(
        default_factory=SubjectLifecycleSnapshot
    )
    shell_clothing: ShellClothingSnapshot = field(
        default_factory=ShellClothingSnapshot
    )
    continuum_posture: ContinuumPostureSnapshot = field(
        default_factory=ContinuumPostureSnapshot
    )
    cognitive_field: CognitiveFieldSnapshot = field(
        default_factory=CognitiveFieldSnapshot
    )
    android_signals: AndroidPresenceSignals = field(
        default_factory=AndroidPresenceSignals
    )
    existence_projection: ExistenceProjection = field(
        default_factory=ExistenceProjection
    )
    _source: str = DESKTOP_EXISTENCE_SURFACE_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "surface_id": self.surface_id,
            "generated_at": self.generated_at,
            "schema_version": self.schema_version,
            "subject_lifecycle": self.subject_lifecycle.to_dict(),
            "shell_clothing": self.shell_clothing.to_dict(),
            "continuum_posture": self.continuum_posture.to_dict(),
            "cognitive_field": self.cognitive_field.to_dict(),
            "android_signals": self.android_signals.to_dict(),
            "existence_projection": self.existence_projection.to_dict(),
            "_source": self._source,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class DesktopExistenceSurfaceBuilder:
    """Builds :class:`DesktopExistenceSurface` from canonical singleton sources.

    This class is **read-only** — it never mutates any singleton state.  All
    five source reads are best-effort: a failure in any individual source
    yields a default empty snapshot for that family rather than raising, so
    the surface is always returnable.

    All five state family reads are recorded in the ``contributing_families``
    list of :class:`ExistenceProjection` when their values are non-default,
    ensuring machine-verifiable provenance.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> DesktopExistenceSurface:
        """Build and return a :class:`DesktopExistenceSurface` snapshot.

        Each call reads from singletons at the moment of the call.  The
        result is a point-in-time immutable snapshot.  Each family read is
        independently guarded so a failure in one source never prevents the
        other families from contributing to the surface.
        """
        with self._lock:
            try:
                fam1 = self._read_subject_lifecycle()
            except Exception as exc:
                logger.debug("build: subject_lifecycle read failed (non-fatal): %s", exc)
                fam1 = SubjectLifecycleSnapshot()

            try:
                fam2 = self._read_shell_clothing()
            except Exception as exc:
                logger.debug("build: shell_clothing read failed (non-fatal): %s", exc)
                fam2 = ShellClothingSnapshot()

            try:
                fam3 = self._read_continuum_posture()
            except Exception as exc:
                logger.debug("build: continuum_posture read failed (non-fatal): %s", exc)
                fam3 = ContinuumPostureSnapshot()

            try:
                fam4 = self._read_cognitive_field()
            except Exception as exc:
                logger.debug("build: cognitive_field read failed (non-fatal): %s", exc)
                fam4 = CognitiveFieldSnapshot()

            try:
                fam5 = self._read_android_signals()
            except Exception as exc:
                logger.debug("build: android_signals read failed (non-fatal): %s", exc)
                fam5 = AndroidPresenceSignals()

            proj = self._derive_existence_projection(fam1, fam2, fam3, fam4, fam5)

            return DesktopExistenceSurface(
                subject_lifecycle=fam1,
                shell_clothing=fam2,
                continuum_posture=fam3,
                cognitive_field=fam4,
                android_signals=fam5,
                existence_projection=proj,
            )

    # ------------------------------------------------------------------
    # Family 1 — Subject lifecycle tri-state
    # ------------------------------------------------------------------

    def _read_subject_lifecycle(self) -> SubjectLifecycleSnapshot:
        """Read TriState presence_summary from DesktopPresenceRuntime."""
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime

            runtime = get_desktop_presence_runtime()
            summary = runtime.presence_summary
            return SubjectLifecycleSnapshot(
                dominant_tristate=summary.get("dominant_tristate", "silent"),
                active_session_count=summary.get("active_session_count", 0),
                tristate_distribution=dict(
                    summary.get("tristate_distribution", {})
                ),
            )
        except Exception as exc:
            logger.debug(
                "DesktopExistenceSurfaceBuilder: subject_lifecycle read failed "
                "(non-fatal): %s",
                exc,
            )
            return SubjectLifecycleSnapshot()

    # ------------------------------------------------------------------
    # Family 2 — UI shell / clothing state
    # ------------------------------------------------------------------

    def _read_shell_clothing(self) -> ShellClothingSnapshot:
        """Read SystemState from SystemStateMachine singleton."""
        try:
            from system_integration.state_machine_ui_integration import (
                SystemStateMachine,
            )

            sm = SystemStateMachine()
            state_val = sm.current_state.value
            return ShellClothingSnapshot(shell_state=state_val)
        except Exception as exc:
            logger.debug(
                "DesktopExistenceSurfaceBuilder: shell_clothing read failed "
                "(non-fatal): %s",
                exc,
            )
            return ShellClothingSnapshot()

    # ------------------------------------------------------------------
    # Family 3 — Continuum posture
    # ------------------------------------------------------------------

    def _read_continuum_posture(self) -> ContinuumPostureSnapshot:
        """Read tri_state_phase / runtime_domain via build_runtime_projection."""
        try:
            from core.projection import build_runtime_projection

            proj = build_runtime_projection()
            return ContinuumPostureSnapshot(
                tri_state_phase=proj.get("tri_state_phase", ""),
                runtime_domain=proj.get("runtime_domain"),
                presence_intensity=float(proj.get("presence_intensity", 0.0)),
                coherence=float(proj.get("coherence", 0.0)),
            )
        except Exception as exc:
            logger.debug(
                "DesktopExistenceSurfaceBuilder: continuum_posture read failed "
                "(non-fatal): %s",
                exc,
            )
            return ContinuumPostureSnapshot()

    # ------------------------------------------------------------------
    # Family 4 — Continuous cognitive field
    # ------------------------------------------------------------------

    def _read_cognitive_field(self) -> CognitiveFieldSnapshot:
        """Read CognitiveState snapshot and CognitiveFieldEngine status."""
        try:
            from core.cognitive.continuous_state import get_cognitive_state
            from core.cognitive.cognitive_field_engine import get_cognitive_field_engine

            snap = get_cognitive_state().snapshot()
            engine = get_cognitive_field_engine()
            return CognitiveFieldSnapshot(
                activation=float(snap.get("activation", 0.0)),
                intent_strength=float(snap.get("intent_strength", 0.0)),
                manifest_pressure=float(snap.get("manifest_pressure", 0.0)),
                stability=float(snap.get("stability", 0.0)),
                is_running=engine.is_running,
                tick_count=int(engine.tick_count),
            )
        except Exception as exc:
            logger.debug(
                "DesktopExistenceSurfaceBuilder: cognitive_field read failed "
                "(non-fatal): %s",
                exc,
            )
            return CognitiveFieldSnapshot()

    # ------------------------------------------------------------------
    # Family 5 — Android presence signals
    # ------------------------------------------------------------------

    def _read_android_signals(self) -> AndroidPresenceSignals:
        """Read DeviceStateSnapshot inventory from android_device_state_store."""
        try:
            from core.android_device_state_store import list_device_state_snapshots

            snapshots = list_device_state_snapshots()
            total = len(snapshots)
            local_loop_ready = sum(
                1 for s in snapshots if getattr(s, "local_loop_ready", False)
            )
            model_ready = sum(
                1 for s in snapshots if getattr(s, "model_ready", False)
            )
            runtime_dist: Dict[str, int] = {}
            for s in snapshots:
                rt = getattr(s, "active_runtime_type", None) or "unknown"
                runtime_dist[rt] = runtime_dist.get(rt, 0) + 1

            return AndroidPresenceSignals(
                total_devices_with_snapshot=total,
                local_loop_ready_count=local_loop_ready,
                model_ready_count=model_ready,
                active_runtime_type_distribution=runtime_dist,
            )
        except Exception as exc:
            logger.debug(
                "DesktopExistenceSurfaceBuilder: android_signals read failed "
                "(non-fatal): %s",
                exc,
            )
            return AndroidPresenceSignals()

    # ------------------------------------------------------------------
    # Projection derivation — read-only, not a new state machine
    # ------------------------------------------------------------------

    def _derive_existence_projection(
        self,
        fam1: SubjectLifecycleSnapshot,
        fam2: ShellClothingSnapshot,
        fam3: ContinuumPostureSnapshot,
        fam4: CognitiveFieldSnapshot,
        fam5: AndroidPresenceSignals,
    ) -> ExistenceProjection:
        """Derive the presence verdict from all five state families.

        This method is **pure** (no side effects) and produces a read-only
        verdict.  The priority order is:
        expressing > active > background > dormant.
        """
        contributing: List[str] = []
        evidence: Dict[str, Any] = {}

        # ── Collect non-default signals ─────────────────────────────────

        # Family 1 — subject lifecycle
        if fam1.dominant_tristate != "silent" or fam1.active_session_count > 0:
            contributing.append("subject_lifecycle")
            evidence["dominant_tristate"] = fam1.dominant_tristate
            evidence["active_session_count"] = fam1.active_session_count

        # Family 2 — shell clothing
        if fam2.shell_state != "dormant":
            contributing.append("shell_clothing")
            evidence["shell_state"] = fam2.shell_state

        # Family 3 — continuum posture
        if fam3.tri_state_phase or fam3.presence_intensity > 0.0:
            contributing.append("continuum_posture")
            evidence["tri_state_phase"] = fam3.tri_state_phase
            evidence["presence_intensity"] = fam3.presence_intensity

        # Family 4 — cognitive field
        if fam4.is_running or fam4.manifest_pressure > 0.0 or fam4.tick_count > 0:
            contributing.append("cognitive_field")
            evidence["manifest_pressure"] = fam4.manifest_pressure
            evidence["activation"] = fam4.activation
            evidence["is_running"] = fam4.is_running

        # Family 5 — android signals
        if fam5.total_devices_with_snapshot > 0:
            contributing.append("android_signals")
            evidence["android_total_devices"] = fam5.total_devices_with_snapshot
            evidence["android_local_loop_ready"] = fam5.local_loop_ready_count

        # ── Derive verdict (priority: expressing > active > background > dormant) ─

        # expressing: subject actively producing output / controlling devices
        is_expressing = (
            fam1.dominant_tristate == "manifest"
            or fam2.shell_state == "fullagent"
        )

        # active: cognition/execution in progress or shell expanded
        is_active_continuum_phase = bool(
            fam3.tri_state_phase and fam3.tri_state_phase not in ("", "passive")
        )
        is_active = (
            fam1.dominant_tristate == "liminal"
            or fam2.shell_state == "sidesheet"
            or fam4.manifest_pressure > 0.4
            or is_active_continuum_phase
        )

        # background: sustained background presence without active request
        is_background = (
            fam4.is_running
            or fam5.local_loop_ready_count > 0
            or fam2.shell_state == "island"
            or fam4.tick_count > 0
        )

        if is_expressing:
            verdict = "expressing"
        elif is_active:
            verdict = "active"
        elif is_background:
            verdict = "background"
        else:
            verdict = "dormant"

        return ExistenceProjection(
            presence_verdict=verdict,
            contributing_families=contributing,
            evidence=evidence,
        )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_builder_instance: Optional[DesktopExistenceSurfaceBuilder] = None
_builder_lock = threading.Lock()


def get_desktop_existence_surface_builder() -> DesktopExistenceSurfaceBuilder:
    """Return the process-wide :class:`DesktopExistenceSurfaceBuilder` singleton."""
    global _builder_instance
    with _builder_lock:
        if _builder_instance is None:
            _builder_instance = DesktopExistenceSurfaceBuilder()
    return _builder_instance


def reset_desktop_existence_surface_builder() -> None:
    """Reset the singleton — for testing only."""
    global _builder_instance
    with _builder_lock:
        _builder_instance = None


def build_desktop_existence_surface() -> DesktopExistenceSurface:
    """Build and return a :class:`DesktopExistenceSurface` snapshot.

    Convenience wrapper over
    :meth:`DesktopExistenceSurfaceBuilder.build` using the process-wide
    singleton builder.
    """
    return get_desktop_existence_surface_builder().build()
