"""
core.desktop_existence_surface — Canonical Assistant-Like Existence Surface
============================================================================

PR-2: Desktop Existence Surface / Assistant Presence Unification
PR-8 (V2): Unified Carrier Execution Surface — R8 closure

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

**PR-8 V2: Unified Carrier Execution Surface (R8 closure)**

The R8 gap identified in the joint system review was:
"Desktop/tablet carrier semantics not unified with Android carrier into a
single manifestation framework at the code layer."

This PR closes that gap by introducing:

- :class:`CarrierSurfaceEntry` — a uniform, per-carrier semantic unit that
  represents a single execution-surface carrier (desktop *or* Android) at the
  same projection level.  Both carrier types share the fields
  ``carrier_type``, ``carrier_id``, ``execution_surface_state``,
  ``is_execution_ready``, and ``carrier_semantic_role``.

- :class:`UnifiedCarrierSurface` — the aggregate surface that collects all
  active carriers (one desktop entry + one entry per Android device snapshot)
  and derives ``dominant_carrier_type``, ``active_carrier_count``, and
  ``execution_ready_carrier_count`` from them.

This unified carrier surface is added as a new field
``unified_carrier_surface`` on :class:`DesktopExistenceSurface` (schema
version "1.1") and is populated by
:class:`DesktopExistenceSurfaceBuilder` reading from existing canonical
singletons — no new state authority is introduced.

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
    PR8_UNIFIED_CARRIER_SURFACE_SENTINEL

Carrier type constants::

    CARRIER_TYPE_DESKTOP
    CARRIER_TYPE_ANDROID

Dataclasses::

    SubjectLifecycleSnapshot    — state family 1: TriState / runtime lifecycle
    ShellClothingSnapshot       — state family 2: SystemState / UI clothing
    ContinuumPostureSnapshot    — state family 3: tri_state_phase / runtime_domain
    CognitiveFieldSnapshot      — state family 4: continuous cognitive field
    AndroidPresenceSignals      — state family 5: Android carrier presence
    CarrierSurfaceEntry         — PR-8: single carrier at unified semantic level
    UnifiedCarrierSurface       — PR-8: all carriers at same projection layer
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
    "PR-8 V2 extends this with a UnifiedCarrierSurface (CarrierSurfaceEntry per carrier) "
    "that projects desktop and Android carriers at the same semantic level, closing R8.  "
    "This module reads from existing canonical singletons and NEVER introduces "
    "a second presence system or writes state."
)

#: PR-8 V2 sentinel — confirms that the UnifiedCarrierSurface (CarrierSurfaceEntry list)
#: is present in this module, closing the R8 gap of desktop/Android carrier semantic
#: divergence.  Both carrier types are now projected at the same semantic layer via
#: CarrierSurfaceEntry / UnifiedCarrierSurface.
PR8_UNIFIED_CARRIER_SURFACE_SENTINEL: str = (
    "PR8_V2::UNIFIED_CARRIER_SURFACE_V1: "
    "core.desktop_existence_surface.UnifiedCarrierSurface projects desktop and Android "
    "carriers at the same semantic level via CarrierSurfaceEntry.  "
    "Closes R8: desktop carrier and Android carrier are now unified in a single "
    "code-layer manifestation framework (schema_version 1.1)."
)

#: Carrier type constant for the desktop/tablet carrier.
CARRIER_TYPE_DESKTOP: str = "desktop"

#: Carrier type constant for Android device carriers.
CARRIER_TYPE_ANDROID: str = "android"

EXISTENCE_SURFACE_SCHEMA_VERSION: str = "1.1"

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
# PR-8 V2 — Unified Carrier Execution Surface (R8 closure)
# ---------------------------------------------------------------------------


@dataclass
class CarrierSurfaceEntry:
    """A single carrier execution surface entry at a unified semantic level.

    PR-8 V2 / R8 closure: both desktop and Android carriers are represented
    as :class:`CarrierSurfaceEntry` instances, eliminating the asymmetry where
    Android devices were only represented as aggregate counts while the desktop
    carrier was represented through richer subject-lifecycle and shell-clothing
    families.  Every carrier now carries the same semantic fields, making
    desktop and Android carriers structurally equivalent at the projection
    layer.

    Attributes
    ----------
    carrier_type:
        ``"desktop"`` or ``"android"``.  Use :data:`CARRIER_TYPE_DESKTOP` /
        :data:`CARRIER_TYPE_ANDROID` constants.
    carrier_id:
        Unique identifier for this carrier.  ``"desktop"`` for the local
        desktop/tablet surface; the ``device_id`` string for Android devices.
    execution_surface_state:
        Canonical execution-surface state for this carrier:

        - ``"active"`` — carrier is currently running an execution loop
          (manifest tri-state or local loop ready + model ready on Android).
        - ``"ready"`` — carrier can accept execution (liminal tri-state or
          model ready on Android) but no active loop is running.
        - ``"idle"`` — carrier is present and reachable but not execution-ready.
        - ``"unavailable"`` — carrier has no execution surface or is offline.

    is_execution_ready:
        ``True`` when the carrier can accept an execution request right now.
    carrier_semantic_role:
        ``"primary"`` for the desktop carrier (V2-local governance surface);
        ``"delegated"`` for Android carriers (runtime-node / delegated
        execution surfaces).
    _source:
        Module that produced this entry.
    """

    carrier_type: str = CARRIER_TYPE_DESKTOP
    carrier_id: str = "desktop"
    execution_surface_state: str = "unavailable"
    is_execution_ready: bool = False
    carrier_semantic_role: str = "primary"
    _source: str = "desktop_existence_surface"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "carrier_type": self.carrier_type,
            "carrier_id": self.carrier_id,
            "execution_surface_state": self.execution_surface_state,
            "is_execution_ready": self.is_execution_ready,
            "carrier_semantic_role": self.carrier_semantic_role,
            "_source": self._source,
        }


@dataclass
class UnifiedCarrierSurface:
    """Unified execution surface across all active carriers.

    PR-8 V2 / R8 closure: collects :class:`CarrierSurfaceEntry` instances for
    *all* carriers — one desktop entry and one entry per Android device
    snapshot — so downstream consumers have a single, uniform carrier
    projection without having to reconstruct it from heterogeneous sources.

    ``dominant_carrier_type`` names the carrier type (``"desktop"`` or
    ``"android"``) of the first carrier in ``active`` state; if none are
    active, the first ``ready`` carrier type; ``"none"`` when no carrier is
    ready.

    This object is read-only and derived; it does not introduce new state
    authority.

    Attributes
    ----------
    carriers:
        All carrier surface entries (desktop first, Android entries in
        insertion order).
    dominant_carrier_type:
        Carrier type of the currently dominant execution surface.
    active_carrier_count:
        Count of carriers whose ``execution_surface_state`` is ``"active"``.
    execution_ready_carrier_count:
        Count of carriers where ``is_execution_ready`` is ``True``.
    _source:
        Module that produced this surface.
    """

    carriers: List[CarrierSurfaceEntry] = field(default_factory=list)
    dominant_carrier_type: str = "none"
    active_carrier_count: int = 0
    execution_ready_carrier_count: int = 0
    _source: str = "desktop_existence_surface"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "carriers": [c.to_dict() for c in self.carriers],
            "dominant_carrier_type": self.dominant_carrier_type,
            "active_carrier_count": self.active_carrier_count,
            "execution_ready_carrier_count": self.execution_ready_carrier_count,
            "_source": self._source,
        }


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
        Schema version string (``"1.1"``).
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
    unified_carrier_surface:
        PR-8 V2 — Unified carrier execution surface projecting desktop and
        Android carriers at the same semantic level.  Closes R8.
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
    unified_carrier_surface: UnifiedCarrierSurface = field(
        default_factory=UnifiedCarrierSurface
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
            "unified_carrier_surface": self.unified_carrier_surface.to_dict(),
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

            try:
                carrier_surface = self._build_unified_carrier_surface(fam1, fam2)
            except Exception as exc:
                logger.debug("build: unified_carrier_surface failed (non-fatal): %s", exc)
                carrier_surface = UnifiedCarrierSurface()

            proj = self._derive_existence_projection(fam1, fam2, fam3, fam4, fam5, carrier_surface)

            return DesktopExistenceSurface(
                subject_lifecycle=fam1,
                shell_clothing=fam2,
                continuum_posture=fam3,
                cognitive_field=fam4,
                android_signals=fam5,
                unified_carrier_surface=carrier_surface,
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
    # PR-8 V2 — Unified carrier surface (R8 closure)
    # ------------------------------------------------------------------

    def _build_unified_carrier_surface(
        self,
        fam1: SubjectLifecycleSnapshot,
        fam2: ShellClothingSnapshot,
    ) -> UnifiedCarrierSurface:
        """Build the unified carrier execution surface.

        Reads per-device Android snapshots from
        :func:`~core.android_device_state_store.list_device_state_snapshots`
        and combines them with the desktop carrier context derived from
        ``fam1`` (subject lifecycle) and ``fam2`` (shell clothing) so that
        desktop and Android carriers are represented at the same semantic
        level.

        This method is **read-only** — it never writes state.  Failures in
        the Android snapshot read produce an Android-less surface (desktop
        entry only) rather than raising.
        """
        carriers: List[CarrierSurfaceEntry] = []

        # ── Desktop carrier entry ──────────────────────────────────────
        if fam1.dominant_tristate == "manifest" or fam2.shell_state == "fullagent":
            desktop_exec_state = "active"
            desktop_ready = True
        elif fam1.dominant_tristate == "liminal" or fam2.shell_state in (
            "sidesheet",
            "island",
        ):
            desktop_exec_state = "ready"
            desktop_ready = True
        elif fam1.active_session_count > 0 or fam2.shell_state != "dormant":
            desktop_exec_state = "idle"
            desktop_ready = False
        else:
            desktop_exec_state = "unavailable"
            desktop_ready = False

        carriers.append(
            CarrierSurfaceEntry(
                carrier_type=CARRIER_TYPE_DESKTOP,
                carrier_id="desktop",
                execution_surface_state=desktop_exec_state,
                is_execution_ready=desktop_ready,
                carrier_semantic_role="primary",
            )
        )

        # ── Android carrier entries (one per device snapshot) ──────────
        try:
            from core.android_device_state_store import list_device_state_snapshots

            for snap in list_device_state_snapshots():
                device_id: str = getattr(snap, "device_id", "android") or "android"
                local_loop = bool(getattr(snap, "local_loop_ready", False))
                model_rdy = bool(getattr(snap, "model_ready", False))

                if local_loop and model_rdy:
                    android_exec_state = "active"
                    android_ready = True
                elif model_rdy:
                    android_exec_state = "ready"
                    android_ready = True
                elif local_loop:
                    android_exec_state = "idle"
                    android_ready = False
                else:
                    android_exec_state = "unavailable"
                    android_ready = False

                carriers.append(
                    CarrierSurfaceEntry(
                        carrier_type=CARRIER_TYPE_ANDROID,
                        carrier_id=device_id,
                        execution_surface_state=android_exec_state,
                        is_execution_ready=android_ready,
                        carrier_semantic_role="delegated",
                    )
                )
        except Exception as exc:
            logger.debug(
                "DesktopExistenceSurfaceBuilder: android carrier read failed "
                "(non-fatal — desktop carrier still present): %s",
                exc,
            )

        # ── Derived summary fields ─────────────────────────────────────
        active_count = sum(
            1 for c in carriers if c.execution_surface_state == "active"
        )
        ready_count = sum(1 for c in carriers if c.is_execution_ready)

        dominant: str = "none"
        for c in carriers:
            if c.execution_surface_state == "active":
                dominant = c.carrier_type
                break
        if dominant == "none":
            for c in carriers:
                if c.is_execution_ready:
                    dominant = c.carrier_type
                    break

        return UnifiedCarrierSurface(
            carriers=carriers,
            dominant_carrier_type=dominant,
            active_carrier_count=active_count,
            execution_ready_carrier_count=ready_count,
        )

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
        carrier_surface: Optional[UnifiedCarrierSurface] = None,
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

        # PR-8 V2 — unified carrier context
        if carrier_surface is not None and carrier_surface.carriers:
            evidence["carrier_active_count"] = carrier_surface.active_carrier_count
            evidence["carrier_ready_count"] = carrier_surface.execution_ready_carrier_count
            evidence["dominant_carrier_type"] = carrier_surface.dominant_carrier_type

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
