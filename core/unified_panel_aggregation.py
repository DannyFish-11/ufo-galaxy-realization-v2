"""
core/unified_panel_aggregation.py
===================================
PR-1: Unified Runtime Surface & Panel Aggregation

Implements the single canonical unified panel/runtime aggregation surface for
the dual-repo (ufo-galaxy-realization-v2 + ufo-galaxy-android) system.

Architecture role
-----------------
This module consolidates the fragmented panel/operator-state sources into one
typed, serialisable payload and exposes a single build entry-point so
downstream consumers no longer need to fan out across multiple endpoints.

State families aggregated
-------------------------
1. **Operator/control-plane projection** — from
   :class:`~core.operator_surface.OperatorSurface` (task counts, device
   presence, topology, capability providers, active flow count).

2. **Shell/presence manifestation** — from
   :class:`~core.operator_surface.OperatorSnapshot`
   (``desktop_shell_state``, ``presence_tristate``, ``manifestation_summary``).

3. **Android runtime/ecosystem** — from
   :mod:`~core.android_device_state_store`
   (``get_device_ecosystem_summary()``).  The count-level summary plus a
   per-device execution-phase digest built from
   ``list_device_state_snapshots()``.

4. **Continuum/flow execution state** — from
   :func:`~core.projection.build_runtime_projection` via
   :mod:`~core.continuum.types.ContinuumState`
   (``tri_state_phase``, ``runtime_domain``, ``presence_intensity``,
   ``coherence``).

5. **Execution readiness** — from
   :mod:`~core.runtime_readiness_matrix`
   (``readiness_verdict``, ``blocked_dimensions``).

6. **Active surface spec** — from
   :class:`~core.generative_ui.surface_selector.SurfaceSelector`
   (the ``SurfaceSpec`` for the current or default interaction mode).

Design invariants
-----------------
- **Read-only projections only** — no state is mutated.
- **Single truth** — this module does NOT introduce a second truth store.  It
  reads from existing canonical singletons and composes them into one view.
- **Graceful degradation** — individual source failures yield empty/default
  sub-sections rather than raising.
- **Source-annotated** — every sub-section carries a ``_source`` key so
  downstream consumers can verify provenance.
- **Extends, not duplicates** — ``OperatorSnapshot`` remains the authority for
  its own state families.  This module only *composes* it with the additional
  runtime/projection/Android families.

Public API
----------
Authority sentinels::

    UNIFIED_PANEL_AGGREGATION_AUTHORITY
    PANEL_STATE_SCHEMA_VERSION

Dataclass::

    UnifiedPanelPayload      — the typed unified panel/runtime model

Class::

    UnifiedPanelAggregationService  — builds UnifiedPanelPayload from sources

Helpers::

    build_unified_panel_payload() -> UnifiedPanelPayload
    get_unified_panel_aggregation_service() -> UnifiedPanelAggregationService
    reset_unified_panel_aggregation_service() -> None   # testing only
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.UnifiedPanelAggregation")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

UNIFIED_PANEL_AGGREGATION_AUTHORITY: str = (
    "UNIFIED_PANEL_AGGREGATION_V1: "
    "core.unified_panel_aggregation is the canonical aggregation surface for "
    "the unified dual-repo runtime/panel state.  All panel clients MUST read "
    "from this module rather than fanning out across separate operator, "
    "projection, and Android-ecosystem endpoints.  This module reads from "
    "existing canonical singletons — it does NOT introduce a second truth store."
)

PANEL_STATE_SCHEMA_VERSION: str = "1.0"

# ---------------------------------------------------------------------------
# UnifiedPanelPayload
# ---------------------------------------------------------------------------


@dataclass
class UnifiedPanelPayload:
    """Typed unified panel/runtime payload model.

    Aggregates all canonical state families required by panel clients into one
    serialisable object.  Built exclusively from real canonical source
    singletons — no assumed or fabricated state.

    Fields
    ------
    payload_id
        Unique ID for this snapshot instance (for deduplication / caching).
    generated_at
        Unix epoch timestamp at which the payload was built.
    schema_version
        Schema version string for forward-compatibility checks.

    Operator/control-plane section
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    active_task_count
        Count of currently active tasks from CanonicalTaskRuntime.
    active_flow_count
        Count of active delegated flows from DelegatedFlowEntityRuntime.
    online_device_count
        Count of online topology nodes from NetworkTopologyRuntime.
    capability_provider_count
        Total capability providers in CapabilityAssimilationLayer.
    online_provider_count
        Online capability providers.
    topology_node_count / topology_edge_count
        Topology graph size metrics.

    Shell/presence section
    ~~~~~~~~~~~~~~~~~~~~~~
    desktop_shell_state
        Current UI shell expansion mode (dormant/island/sidesheet/fullagent).
        Empty string when SystemStateMachine is unavailable.
    presence_tristate
        Dominant subject tri-state (silent/liminal/manifest).
    manifestation_summary
        Combined shell+presence derived view.

    Continuum/flow execution section
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    tri_state_phase
        Current continuum phase from ContinuumState.
    runtime_domain
        Execution domain (local/cross_device/transition/None).
    presence_intensity
        EMA-smoothed presence strength [0, 1].
    coherence
        Degree to which sensed signals form a coherent intent [0, 1].

    Android runtime/ecosystem section
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    android_ecosystem
        Count-level summary from android_device_state_store
        (total_devices_with_snapshot, local_ai_ready_count, etc.).
    android_device_execution_digest
        Per-device execution-phase digest built from DeviceStateSnapshot list.
        Summarises readiness and model availability per connected Android device.

    Execution readiness section
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~
    readiness_verdict
        Overall readiness verdict (READY/BLOCKED/DEGRADED/UNKNOWN).
    blocked_dimensions
        List of dimension names that are currently BLOCKED or UNKNOWN.

    Active surface section
    ~~~~~~~~~~~~~~~~~~~~~~
    active_surface_spec
        SurfaceSpec dict for the current interaction mode.  Contains
        surface_type, title, layout_hints, fallback_surface.

    Existence surface section (PR-2)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    existence_surface
        Dict representation of the :class:`~core.desktop_existence_surface.DesktopExistenceSurface`
        built by :mod:`~core.desktop_existence_surface`.  Contains all five
        real state-family snapshots (subject_lifecycle, shell_clothing,
        continuum_posture, cognitive_field, android_signals) plus the derived
        ``existence_projection`` verdict.  Empty dict when the existence
        surface module is unavailable.

    Last operator action section (PR-3)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    last_operator_action
        Compact summary of the most recent
        :class:`~core.operator_action_contract.OperatorActionResult` executed
        in this process lifetime.  Keys: ``action_id``, ``action_kind``,
        ``accepted``, ``runtime_session_id``, ``operator_entry_mode``,
        ``generated_at``.  Empty dict when no operator action has been
        executed or the operator action module is unavailable.

    Provenance
    ~~~~~~~~~~
    _source
        Authority annotation identifying this module as the builder.
    """

    payload_id: str = field(default_factory=lambda: f"panel_{uuid.uuid4().hex[:12]}")
    generated_at: float = field(default_factory=time.time)
    schema_version: str = PANEL_STATE_SCHEMA_VERSION

    # ── Operator/control-plane projection ─────────────────────────────────
    active_task_count: int = 0
    active_flow_count: int = 0
    online_device_count: int = 0
    capability_provider_count: int = 0
    online_provider_count: int = 0
    topology_node_count: int = 0
    topology_edge_count: int = 0

    # ── Shell/presence manifestation ──────────────────────────────────────
    desktop_shell_state: str = ""
    presence_tristate: str = ""
    manifestation_summary: Dict[str, Any] = field(default_factory=dict)

    # ── Continuum/flow execution state ────────────────────────────────────
    tri_state_phase: str = ""
    runtime_domain: Optional[str] = None
    presence_intensity: float = 0.0
    coherence: float = 0.0

    # ── Android runtime/ecosystem ─────────────────────────────────────────
    android_ecosystem: Dict[str, Any] = field(default_factory=dict)
    android_device_execution_digest: List[Dict[str, Any]] = field(default_factory=list)

    # ── Execution readiness ───────────────────────────────────────────────
    readiness_verdict: str = "UNKNOWN"
    blocked_dimensions: List[str] = field(default_factory=list)

    # ── Active surface spec ───────────────────────────────────────────────
    active_surface_spec: Dict[str, Any] = field(default_factory=dict)

    # ── Existence surface (PR-2) ──────────────────────────────────────────
    existence_surface: Dict[str, Any] = field(default_factory=dict)

    # ── Last operator action outcome (PR-3) ───────────────────────────────
    # When an operator-panel action has been executed, this field carries a
    # compact summary of the most recent OperatorActionResult so that the
    # unified panel surface stays coherent with control-plane activity.
    # Empty dict when no operator action has been executed in this process
    # lifetime or the operator action module is unavailable.
    last_operator_action: Dict[str, Any] = field(default_factory=dict)

    # ── Execution result feedback (PR-4) ──────────────────────────────────
    # Carries the compact projection of the most recent
    # ExecutionRoundtripRecord from core.canonical_roundtrip.  This closes
    # the action→execution→result→state-feedback loop so that the unified
    # panel surface reflects real execution outcomes rather than only
    # indicating that an action was "accepted".
    #
    # Keys: roundtrip_id, action_id, action_kind, trace_id, execution_phase,
    #       execution_success, android_terminal_phase, android_device_id,
    #       android_flow_id, feedback_projected_at, _source.
    # Empty dict when no execution roundtrip has completed in this process
    # lifetime or the canonical_roundtrip module is unavailable.
    last_execution_result: Dict[str, Any] = field(default_factory=dict)

    # ── Android mode gate state (PR-mode-gate) ───────────────────────────
    # Authoritative per-device mode / readiness summary from
    # core.android_mode_gate_policy.  Carries the unified verdict for the
    # three Android gates (crossDeviceEnabled, goalExecutionEnabled,
    # parallelExecutionEnabled) and the current device mode
    # (local / cross_device / unknown) for every device with an active
    # session.  Empty dict when the mode gate policy module is unavailable.
    #
    # Keys: devices (list of AndroidModeReadinessVerdict dicts),
    #       cross_device_ready_count, dispatch_eligible_count,
    #       takeover_eligible_count, total_devices, _source.
    android_mode_gate_state: Dict[str, Any] = field(default_factory=dict)
    governance_state: Dict[str, Any] = field(default_factory=dict)

    # ── Provenance ────────────────────────────────────────────────────────
    _source: str = UNIFIED_PANEL_AGGREGATION_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "payload_id": self.payload_id,
            "generated_at": self.generated_at,
            "schema_version": self.schema_version,
            # operator/control-plane
            "active_task_count": self.active_task_count,
            "active_flow_count": self.active_flow_count,
            "online_device_count": self.online_device_count,
            "capability_provider_count": self.capability_provider_count,
            "online_provider_count": self.online_provider_count,
            "topology_node_count": self.topology_node_count,
            "topology_edge_count": self.topology_edge_count,
            # shell/presence
            "desktop_shell_state": self.desktop_shell_state,
            "presence_tristate": self.presence_tristate,
            "manifestation_summary": dict(self.manifestation_summary),
            # continuum/flow execution
            "tri_state_phase": self.tri_state_phase,
            "runtime_domain": self.runtime_domain,
            "presence_intensity": self.presence_intensity,
            "coherence": self.coherence,
            # android
            "android_ecosystem": dict(self.android_ecosystem),
            "android_device_execution_digest": list(self.android_device_execution_digest),
            # readiness
            "readiness_verdict": self.readiness_verdict,
            "blocked_dimensions": list(self.blocked_dimensions),
            # surface spec
            "active_surface_spec": dict(self.active_surface_spec),
            # existence surface (PR-2)
            "existence_surface": dict(self.existence_surface),
            # last operator action (PR-3)
            "last_operator_action": dict(self.last_operator_action),
            # execution result feedback (PR-4)
            "last_execution_result": dict(self.last_execution_result),
            # android mode gate state (PR-mode-gate)
            "android_mode_gate_state": dict(self.android_mode_gate_state),
            # unified governance semantics
            "governance_state": dict(self.governance_state),
            # provenance
            "_source": self._source,
        }


# ---------------------------------------------------------------------------
# UnifiedPanelAggregationService
# ---------------------------------------------------------------------------


class UnifiedPanelAggregationService:
    """Canonical aggregation service that builds :class:`UnifiedPanelPayload`.

    Reads exclusively from existing canonical singletons — no new truth stores
    are introduced.  Each source section is gathered in a separate try/except
    block so that partial failures degrade gracefully without blocking the
    entire payload.

    Source modules consumed
    -----------------------
    - ``core.operator_surface`` → ``OperatorSurface.operator_snapshot()``
    - ``core.android_device_state_store`` → ``get_device_ecosystem_summary()``,
      ``list_device_state_snapshots()``
    - ``core.projection`` + ``core.continuum`` →
      ``build_runtime_projection()`` over live ``ContinuumState``
    - ``core.runtime_readiness_matrix`` → ``ReadinessMatrix``
    - ``core.generative_ui.surface_selector`` → ``SurfaceSelector``
    """

    def __init__(self) -> None:
        self._service_id: str = f"upas_{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------
    # Main entry-point
    # ------------------------------------------------------------------

    def build_payload(self, *, mode: str = "chat") -> UnifiedPanelPayload:
        """Build and return the current :class:`UnifiedPanelPayload`.

        Args:
            mode: Interaction mode forwarded to :class:`SurfaceSelector` to
                  determine ``active_surface_spec``.  Defaults to ``"chat"``.

        Returns:
            A fully populated :class:`UnifiedPanelPayload`.  Individual source
            failures leave the corresponding section at its default empty value.
        """
        payload = UnifiedPanelPayload()

        # Each fill step is independently guarded so a failure in one source
        # never prevents other sources from contributing to the payload.

        # 1. Operator snapshot — control-plane + shell/presence families
        try:
            self._fill_from_operator_snapshot(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: operator snapshot fill failed: %s", exc)

        # 2. Android ecosystem + execution digest
        try:
            self._fill_from_android_store(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: android store fill failed: %s", exc)

        # 3. Continuum/flow execution projection
        try:
            self._fill_from_runtime_projection(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: runtime projection fill failed: %s", exc)

        # 4. Execution readiness verdict
        try:
            self._fill_from_readiness_matrix(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: readiness matrix fill failed: %s", exc)

        # 5. Active surface spec
        try:
            self._fill_active_surface_spec(payload, mode=mode)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: surface spec fill failed: %s", exc)

        # 6. Existence surface (PR-2) — unified assistant-like existence projection
        try:
            self._fill_from_existence_surface(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: existence surface fill failed: %s", exc)

        # 7. Last operator action outcome (PR-3) — control-plane result integration
        try:
            self._fill_from_last_operator_action(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: last operator action fill failed: %s", exc)

        # 8. Execution result feedback (PR-4) — closed-loop roundtrip projection
        try:
            self._fill_from_execution_roundtrip(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: execution roundtrip fill failed: %s", exc)

        # 9. Android mode gate state — unified cross-device gate readiness
        try:
            self._fill_from_android_mode_gate_policy(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: android mode gate state fill failed: %s", exc)

        # 10. Unified governance semantics (V2 authority vs Android autonomy)
        try:
            self._fill_from_unified_governance_semantics(payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("build_payload: governance semantics fill failed: %s", exc)

        return payload

    # ------------------------------------------------------------------
    # Source fill methods (each isolated so one failure does not cascade)
    # ------------------------------------------------------------------

    def _fill_from_operator_snapshot(self, payload: UnifiedPanelPayload) -> None:
        """Fill operator/control-plane and shell/presence fields from OperatorSnapshot."""
        try:
            from core.operator_surface import get_operator_surface
            snap = get_operator_surface().operator_snapshot()

            payload.active_task_count = snap.active_task_count
            payload.active_flow_count = snap.active_flow_count
            payload.online_device_count = snap.online_device_count
            payload.capability_provider_count = snap.capability_provider_count
            payload.online_provider_count = snap.online_provider_count
            payload.topology_node_count = snap.topology_node_count
            payload.topology_edge_count = snap.topology_edge_count
            payload.desktop_shell_state = snap.desktop_shell_state
            payload.presence_tristate = snap.presence_tristate
            payload.manifestation_summary = dict(snap.manifestation_summary)
        except Exception as exc:
            logger.debug("build_payload: operator snapshot unavailable: %s", exc)

    def _fill_from_android_store(self, payload: UnifiedPanelPayload) -> None:
        """Fill Android ecosystem + per-device execution digest fields."""
        try:
            from core.android_device_state_store import (
                get_device_ecosystem_summary,
                list_device_state_snapshots,
            )
            from core.operator_surface import ANDROID_ECOSYSTEM_SNAPSHOT_KEYS

            eco = get_device_ecosystem_summary()
            # Apply the same whitelist used by OperatorSnapshot to maintain
            # consistency with the existing canonical surface.
            payload.android_ecosystem = {
                k: v for k, v in eco.items() if k in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
            }

            # Build per-device execution-phase digest from raw snapshots.
            # This is a lightweight summary — full per-device detail stays
            # in GET /api/v1/operator/devices/ecosystem.
            snapshots = list_device_state_snapshots()
            digest: List[Dict[str, Any]] = []
            for snap in snapshots:
                try:
                    readiness_fn = getattr(snap, "readiness_summary", None)
                    readiness = readiness_fn() if callable(readiness_fn) else {}
                    local_ai_fn = getattr(snap, "is_local_ai_ready", None)
                    digest.append({
                        "device_id": snap.device_id,
                        "absorbed_at": snap.absorbed_at,
                        "model_ready": snap.model_ready,
                        "accessibility_ready": snap.accessibility_ready,
                        "local_ai_ready": local_ai_fn() if callable(local_ai_fn) else False,
                        "mobilevlm_present": getattr(snap, "mobilevlm_present", False),
                        "seeclick_present": getattr(snap, "seeclick_present", False),
                        "dispatch_capability_status": {
                            "authoritative_scoring_fields": {
                                "model_ready": getattr(snap, "model_ready", None),
                                "accessibility_ready": getattr(snap, "accessibility_ready", None),
                                "local_loop_ready": getattr(snap, "local_loop_ready", None),
                                "warmup_result": getattr(snap, "warmup_result", None),
                                "current_fallback_tier": getattr(snap, "current_fallback_tier", None),
                            },
                            "capability_presence_only_fields": {
                                "mobilevlm_present": getattr(snap, "mobilevlm_present", None),
                                "mobilevlm_checksum_ok": getattr(snap, "mobilevlm_checksum_ok", None),
                                "seeclick_present": getattr(snap, "seeclick_present", None),
                            },
                            "authority_note": (
                                "runtime-truth fields above drive dispatch scoring; "
                                "capability_presence_only_fields are observability-only"
                            ),
                        },
                        "readiness": readiness,
                        "_source": "android_device_state_store",
                    })
                except Exception as inner_exc:
                    logger.debug("build_payload: device digest entry error: %s", inner_exc)
            payload.android_device_execution_digest = digest

        except Exception as exc:
            logger.debug("build_payload: android store unavailable: %s", exc)

    def _fill_from_runtime_projection(self, payload: UnifiedPanelPayload) -> None:
        """Fill continuum/flow execution fields from RuntimeProjection."""
        try:
            from core.projection import build_runtime_projection
            from core.continuum.types import ContinuumState, ContinuumPhase  # noqa: F401
        except Exception as exc:
            logger.debug("build_payload: projection imports unavailable: %s", exc)
            return

        try:
            # Obtain the live ContinuumState from the canonical runtime source.
            # This mirrors _get_continuum_state_with_source() in projection.py.
            continuum_state: Optional[Any] = None
            try:
                from core.desktop_presence_runtime import get_desktop_presence_runtime
                dpr = get_desktop_presence_runtime()
                cs = getattr(dpr, "_continuum_state", None) or getattr(dpr, "continuum_state", None)
                if cs is None:
                    # Fall back to ContinuumState factory if runtime doesn't
                    # expose it directly.
                    cs = _get_continuum_state_fallback()
                continuum_state = cs
            except Exception:
                continuum_state = _get_continuum_state_fallback()

            if continuum_state is None:
                return

            projection = build_runtime_projection(
                continuum_state=continuum_state,
                timestamp=time.time(),
            )
            # tri_state_phase may be enum or string depending on version
            tsp = getattr(projection, "tri_state_phase", None)
            if tsp is not None:
                payload.tri_state_phase = tsp.value if hasattr(tsp, "value") else str(tsp)
            rd = getattr(projection, "runtime_domain", None)
            if rd is not None:
                payload.runtime_domain = rd.value if hasattr(rd, "value") else str(rd)
            payload.presence_intensity = float(getattr(projection, "presence_intensity", 0.0) or 0)
            payload.coherence = float(getattr(projection, "coherence", 0.0) or 0)
        except Exception as exc:
            logger.debug("build_payload: runtime projection unavailable: %s", exc)

    def _fill_from_readiness_matrix(self, payload: UnifiedPanelPayload) -> None:
        """Fill execution readiness fields from ReadinessMatrix."""
        try:
            from core.runtime_readiness_matrix import get_readiness_matrix
            matrix = get_readiness_matrix()
            d = matrix.to_dict()
            # Normalise to uppercase for consistency with the READY/BLOCKED/
            # DEGRADED/UNKNOWN vocabulary.
            payload.readiness_verdict = str(d.get("verdict", "UNKNOWN")).upper()
            blocked = d.get("blocked_dimensions") or d.get("blocked", [])
            payload.blocked_dimensions = list(blocked)
        except Exception as exc:
            logger.debug("build_payload: readiness matrix unavailable: %s", exc)

    def _fill_active_surface_spec(
        self, payload: UnifiedPanelPayload, *, mode: str = "chat"
    ) -> None:
        """Fill active_surface_spec from SurfaceSelector."""
        try:
            from core.generative_ui.surface_selector import SurfaceSelector
            selector = SurfaceSelector()
            spec = selector.select_surface(mode=mode)
            payload.active_surface_spec = spec.to_dict()
        except Exception as exc:
            logger.debug("build_payload: surface selector unavailable: %s", exc)

    def _fill_from_existence_surface(self, payload: UnifiedPanelPayload) -> None:
        """Fill existence_surface from DesktopExistenceSurfaceBuilder (PR-2).

        Adds the unified assistant-like existence surface to the panel payload
        so that consumers of GET /api/v1/panel/unified also receive the
        coherent existence projection without a second request.
        """
        try:
            from core.desktop_existence_surface import build_desktop_existence_surface

            surface = build_desktop_existence_surface()
            payload.existence_surface = surface.to_dict()
        except Exception as exc:
            logger.debug("build_payload: existence surface unavailable: %s", exc)

    def _fill_from_last_operator_action(self, payload: UnifiedPanelPayload) -> None:
        """Fill last_operator_action from the operator action result store (PR-3).

        Reads the most recent :class:`~core.operator_action_contract.OperatorActionResult`
        persisted in the process-level ``_LAST_OPERATOR_ACTION_RESULT`` store
        (maintained by the operator route handlers).  This ensures that the
        unified panel payload reflects the most recent operator control-plane
        activity without requiring a separate request.
        """
        try:
            result = get_last_operator_action_result()
            if result is not None:
                payload.last_operator_action = {
                    "action_id": result.action_id,
                    "action_kind": result.action_kind,
                    "accepted": result.accepted,
                    "runtime_session_id": result.runtime_session_id,
                    "operator_entry_mode": result.operator_entry_mode,
                    "generated_at": result.generated_at,
                    "_source": "operator_action_contract",
                }
        except Exception as exc:
            logger.debug("build_payload: last operator action unavailable: %s", exc)

    def _fill_from_execution_roundtrip(self, payload: UnifiedPanelPayload) -> None:
        """Fill last_execution_result from the canonical roundtrip store (PR-4).

        Reads the most recent :class:`~core.canonical_roundtrip.ExecutionRoundtripRecord`
        from the process-level roundtrip store and projects a compact summary
        into the panel payload.  This closes the action→execution→result→state-
        feedback roundtrip so that operator/panel/existence consumers observe
        real outcome-driven state changes rather than only "action accepted".

        Both V2-local execution results (from DesktopPresenceRuntime) and
        Android terminal execution events (from android_device_state_store) are
        eligible to populate this field.
        """
        try:
            from core.canonical_roundtrip import get_last_execution_roundtrip

            record = get_last_execution_roundtrip()
            if record is not None:
                payload.last_execution_result = record.compact_dict()
        except Exception as exc:
            logger.debug("build_payload: execution roundtrip unavailable: %s", exc)

    def _fill_from_android_mode_gate_policy(self, payload: UnifiedPanelPayload) -> None:
        """Fill android_mode_gate_state from the unified mode gate policy (PR-mode-gate).

        Aggregates per-device cross-device readiness into the panel payload so
        that operator surfaces can observe whether each connected Android device
        is in local or cross_device mode, and whether it passes the unified gate
        policy for dispatch / takeover eligibility.

        All devices with an active session in AttachedRuntimeSessionRegistry are
        evaluated.  Evaluation is lightweight (no I/O, reads from in-process
        singletons) so the per-device cost is acceptable for the typical small
        count of connected devices.  If the device count grows large, consider
        applying a sampling or caching layer upstream.
        """
        try:
            from core.android_mode_gate_policy import build_cross_device_readiness_panel_dict
            payload.android_mode_gate_state = build_cross_device_readiness_panel_dict()
        except Exception as exc:
            logger.debug("build_payload: android mode gate policy unavailable: %s", exc)

    def _fill_from_unified_governance_semantics(self, payload: UnifiedPanelPayload) -> None:
        """Fill governance_state from unified governance semantics contract."""
        try:
            from core.unified_governance_semantics import build_unified_governance_state

            payload.governance_state = build_unified_governance_state()
        except Exception as exc:
            logger.debug("build_payload: unified governance semantics unavailable: %s", exc)


# ---------------------------------------------------------------------------
# Process-level operator action result store (PR-3)
# ---------------------------------------------------------------------------
# A lightweight in-process store so the unified panel payload can reflect
# the most recent operator control-plane action without requiring the routes
# module to publish results to a separate service.
#
# This store is written by record_last_operator_action_result() (called by
# the operator route handlers) and read by _fill_from_last_operator_action().
# It is intentionally NOT a full persistence layer — a process restart clears
# it.  For durable audit evidence, see the audit_store chain.

_LAST_OPERATOR_ACTION_RESULT: Optional[Any] = None
_OPERATOR_ACTION_RESULT_LOCK = threading.Lock()


def record_last_operator_action_result(result: Any) -> None:
    """Store the most recent :class:`~core.operator_action_contract.OperatorActionResult`.

    Called by operator route handlers after each action execution so the
    unified panel payload can surface the last operator activity.

    Args:
        result: An :class:`~core.operator_action_contract.OperatorActionResult`
                instance.
    """
    global _LAST_OPERATOR_ACTION_RESULT
    with _OPERATOR_ACTION_RESULT_LOCK:
        _LAST_OPERATOR_ACTION_RESULT = result


def get_last_operator_action_result() -> Optional[Any]:
    """Return the most recent operator action result, or None."""
    return _LAST_OPERATOR_ACTION_RESULT


def reset_last_operator_action_result() -> None:
    """Reset the stored result — for testing only."""
    global _LAST_OPERATOR_ACTION_RESULT
    with _OPERATOR_ACTION_RESULT_LOCK:
        _LAST_OPERATOR_ACTION_RESULT = None


# ---------------------------------------------------------------------------
# Continuum state fallback helper
# ---------------------------------------------------------------------------


def _get_continuum_state_fallback() -> Optional[Any]:
    """Return a live or synthetic ContinuumState for projection.

    Mirrors the approach used in core/routes/projection.py without importing
    that private helper directly.
    """
    try:
        from core.continuum.types import ContinuumState, ContinuumPhase

        # Attempt to obtain a live ContinuumState from the cognitive field engine.
        try:
            from core.cognitive_field_engine import get_cognitive_field_engine
            cfe = get_cognitive_field_engine()
            cs = getattr(cfe, "continuum_state", None) or getattr(cfe, "_state", None)
            if cs is not None and isinstance(cs, ContinuumState):
                return cs
        except Exception:
            pass

        # Construct a minimal silent-phase fallback so downstream consumers
        # always receive a valid (though empty) projection.
        return ContinuumState(phase=ContinuumPhase.SILENT)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Module-level convenience helpers
# ---------------------------------------------------------------------------


def build_unified_panel_payload(*, mode: str = "chat") -> UnifiedPanelPayload:
    """Build and return the current :class:`UnifiedPanelPayload`.

    This is the single canonical entry-point for panel clients.  It delegates
    to the process-level :class:`UnifiedPanelAggregationService` singleton.

    Args:
        mode: Interaction mode for the ``active_surface_spec`` field.
              Defaults to ``"chat"``.

    Returns:
        A fully populated :class:`UnifiedPanelPayload`.
    """
    return get_unified_panel_aggregation_service().build_payload(mode=mode)


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_service_instance: Optional[UnifiedPanelAggregationService] = None
_service_lock = threading.Lock()


def get_unified_panel_aggregation_service() -> UnifiedPanelAggregationService:
    """Return the process-level singleton :class:`UnifiedPanelAggregationService`."""
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = UnifiedPanelAggregationService()
    return _service_instance


def reset_unified_panel_aggregation_service() -> None:
    """Reset the singleton — for testing only."""
    global _service_instance
    with _service_lock:
        _service_instance = None
