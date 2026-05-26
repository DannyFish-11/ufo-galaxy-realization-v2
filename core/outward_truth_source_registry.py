"""
core/outward_truth_source_registry.py
========================================
Focused Convergence Pass — Outward Truth-Source Registry

Purpose
-------
Provides a machine-readable registry that maps every key outward surface
field (in the unified panel, operator surface, and runtime snapshots) to its
authoritative canonical source.

This registry exists to:
1. Make the provenance of every key outward state value traceable.
2. Prevent silent drift where a surface value is produced by a weaker
   substrate without any annotation.
3. Allow operator tools and diagnostic surfaces to show users *why* a value
   is what it is — not just what it is.

Design rules
------------
- **Read-only** — the registry is static + augmented at import time.
- **Declarative** — each entry describes the source; it does not perform
  any computation.
- **Non-authoritative** — this module does NOT produce or store runtime truth;
  it only describes where truth comes from.
- **Extensible** — new entries can be appended without breaking existing ones.

Public API
----------
Authority sentinels::

    OUTWARD_TRUTH_SOURCE_REGISTRY_AUTHORITY

Dataclass::

    TruthSourceEntry     — one registry entry

Functions::

    get_registry() -> Dict[str, TruthSourceEntry]
    get_entry(field_key: str) -> Optional[TruthSourceEntry]
    assert_source_for_field(field_key: str, claimed_source: str) -> None
    build_registry_snapshot() -> Dict[str, Any]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

OUTWARD_TRUTH_SOURCE_REGISTRY_AUTHORITY: str = (
    "OUTWARD_TRUTH_SOURCE_REGISTRY_V1: "
    "core.outward_truth_source_registry is the canonical declarative registry "
    "that maps every key outward surface field to its authoritative truth source. "
    "It does NOT produce runtime truth — it describes provenance."
)

# ---------------------------------------------------------------------------
# Source kind constants (mirrors authority_source_fingerprint where applicable)
# ---------------------------------------------------------------------------

SK_CANONICAL_TRUTH = "canonical_truth"
SK_COMPILED_OUTWARD_TRUTH = "compiled_outward_truth"
SK_RUNTIME_VISIBLE_STATE = "runtime_visible_state"
SK_OPERATOR_DERIVED_SURFACE = "operator_derived_surface"
SK_DIAGNOSTICS_VISIBLE_STATE = "diagnostics_visible_state"
SK_STATIC_DECLARATION = "static_declaration"
SK_EVIDENCE_PROJECTION = "evidence_projection"

# ---------------------------------------------------------------------------
# TruthSourceEntry dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TruthSourceEntry:
    """Describes the authoritative source for one key outward surface field.

    Attributes
    ----------
    field_key:
        Dot-separated key path identifying the field (e.g.
        ``"panel.readiness_verdict"``).
    surface_path:
        API or module path where this field appears
        (e.g. ``"/api/v1/panel/unified"``).
    source_module:
        Canonical module path that produces this field's value
        (e.g. ``"core.runtime_readiness_matrix.ReadinessMatrix"``).
    source_authority:
        Optional authority sentinel constant string from the source module.
    source_kind:
        One of the ``SK_*`` constants indicating the authority tier.
    is_canonical_truth:
        ``True`` when this field is sourced from a canonical runtime substrate.
    is_durable:
        ``True`` when the source persists across restarts.
    is_projection:
        ``True`` when the value is derived/projected rather than directly stored.
    requires_revalidation_after_restart:
        ``True`` when a restored value must be revalidated before it can be
        treated as live canonical truth.
    evidence_chain:
        Ordered tuple of module/step names that feed into this field's value.
    explanation:
        Human-readable sentence explaining what this field means and why it
        comes from this source.
    """

    field_key: str
    surface_path: str
    source_module: str
    source_authority: Optional[str]
    source_kind: str
    is_canonical_truth: bool
    is_durable: bool = False
    is_projection: bool = False
    requires_revalidation_after_restart: bool = False
    evidence_chain: Tuple[str, ...] = field(default_factory=tuple)
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_key": self.field_key,
            "surface_path": self.surface_path,
            "source_module": self.source_module,
            "source_authority": self.source_authority,
            "source_kind": self.source_kind,
            "is_canonical_truth": self.is_canonical_truth,
            "is_durable": self.is_durable,
            "is_projection": self.is_projection,
            "requires_revalidation_after_restart": self.requires_revalidation_after_restart,
            "evidence_chain": list(self.evidence_chain),
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------------
# Registry declaration
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, TruthSourceEntry] = {
    # ------------------------------------------------------------------
    # Allocation truth
    # ------------------------------------------------------------------
    "allocation.records": TruthSourceEntry(
        field_key="allocation.records",
        surface_path="core.canonical_task.CanonicalTaskRuntime",
        source_module="core.canonical_task.CanonicalTaskRuntime",
        source_authority="CANONICAL_TASK_RUNTIME_AUTHORITY",
        source_kind=SK_CANONICAL_TRUTH,
        is_canonical_truth=True,
        is_durable=True,
        is_projection=False,
        requires_revalidation_after_restart=True,
        evidence_chain=(
            "core.canonical_task.CanonicalTaskRuntime.list_allocation_records",
        ),
        explanation=(
            "Task allocation ownership is tracked by CanonicalTaskRuntime. "
            "Accepted allocations are durable but must be revalidated after restart "
            "before being treated as live execution truth."
        ),
    ),
    "allocation.executor_assignment": TruthSourceEntry(
        field_key="allocation.executor_assignment",
        surface_path="core.canonical_task.CanonicalTaskRuntime",
        source_module="core.canonical_task.CanonicalTaskRuntime",
        source_authority="CANONICAL_TASK_RUNTIME_AUTHORITY",
        source_kind=SK_CANONICAL_TRUTH,
        is_canonical_truth=True,
        is_durable=True,
        is_projection=False,
        requires_revalidation_after_restart=True,
        evidence_chain=(
            "core.canonical_task.CanonicalTaskRuntime.list_allocation_records",
            "AllocationRecord.selected_executor",
            "AllocationRecord.execution_location",
        ),
        explanation=(
            "Which executor a task is allocated to is determined by "
            "AllocationRecord.selected_executor / execution_location in "
            "CanonicalTaskRuntime. Executor assignments that survive restart "
            "must be revalidated before dispatch."
        ),
    ),
    # ------------------------------------------------------------------
    # Autonomy truth
    # ------------------------------------------------------------------
    "autonomy.device_class": TruthSourceEntry(
        field_key="autonomy.device_class",
        surface_path="core.device_autonomy_evidence",
        source_module="core.device_autonomy_evidence.build_device_autonomy_classification",
        source_authority="DEVICE_AUTONOMY_EVIDENCE_AUTHORITY",
        source_kind=SK_EVIDENCE_PROJECTION,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=True,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.android_device_state_store.list_device_state_snapshots",
            "core.android_network_participation.get_participation_state_for_device",
            "core.canonical_cross_repo_evidence_pipeline.build_canonical_cross_repo_evidence_report",
            "core.delegated_runtime_execution_tracker.build_execution_tracking_snapshot",
        ),
        explanation=(
            "Device autonomy class is a projection derived from cross-repo "
            "execution evidence (accepted execution, result return, closure). "
            "Registration posture alone never promotes autonomy class. "
            "Strong classes require runtime-proven cross-repo evidence."
        ),
    ),
    "autonomy.promotion_evidence": TruthSourceEntry(
        field_key="autonomy.promotion_evidence",
        surface_path="core.device_autonomy_evidence",
        source_module="core.canonical_cross_repo_evidence_pipeline.build_canonical_cross_repo_evidence_report",
        source_authority="CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY",
        source_kind=SK_EVIDENCE_PROJECTION,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=True,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.canonical_cross_repo_evidence_pipeline",
            "core.android_acceptance_evidence_store",
            "core.delegated_runtime_execution_tracker",
        ),
        explanation=(
            "Autonomy promotion evidence is produced by the canonical cross-repo "
            "evidence pipeline. Evidence items include: accepted execution proof, "
            "actual execution proof, result return proof, closure-integration proof, "
            "continuity-over-time proof, stable runtime-host proof."
        ),
    ),
    # ------------------------------------------------------------------
    # Device support truth
    # ------------------------------------------------------------------
    "device_support.operational_tier": TruthSourceEntry(
        field_key="device_support.operational_tier",
        surface_path="core.device_operational_support",
        source_module="core.device_operational_support.classify_device_operational_support",
        source_authority="DEVICE_OPERATIONAL_SUPPORT_AUTHORITY",
        source_kind=SK_STATIC_DECLARATION,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=False,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.device_types.DeviceType",
            "core.device_operational_support.NEAR_PEER_OPERATIONAL_TYPES",
        ),
        explanation=(
            "Device operational support tier is a static classification. "
            "Only declared near-peer operational types (Android, Windows) are "
            "dispatch/control-capable. Other declared types are observable-only "
            "or non-operational regardless of registration posture."
        ),
    ),
    "device_support.dispatch_readiness": TruthSourceEntry(
        field_key="device_support.dispatch_readiness",
        surface_path="core.device_dispatch_readiness_surface",
        source_module="core.device_dispatch_readiness_surface.get_dispatch_readiness_panel",
        source_authority="DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY",
        source_kind=SK_RUNTIME_VISIBLE_STATE,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=False,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.unified_dispatch_readiness_gate.evaluate_dispatch_readiness",
            "galaxy_gateway.android.handlers.registration.get_all_devices_with_registration_gaps",
            "core.android_device_state_store",
        ),
        explanation=(
            "Per-device dispatch readiness is evaluated at runtime by the "
            "unified dispatch readiness gate. Blockers include registration gaps, "
            "missing device state snapshots, operational support failures, and "
            "gating policy decisions. All blocking reasons are structured fields, "
            "not just a boolean."
        ),
    ),
    # ------------------------------------------------------------------
    # Topology truth
    # ------------------------------------------------------------------
    "topology.node_relations": TruthSourceEntry(
        field_key="topology.node_relations",
        surface_path="core.network_topology_runtime",
        source_module="core.network_topology_runtime.NetworkTopologyRuntime",
        source_authority=None,
        source_kind=SK_RUNTIME_VISIBLE_STATE,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=True,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.network_topology_runtime.NetworkTopologyRuntime",
            "core.nodes.node_fabric_registry.NodeFabricRegistry",
        ),
        explanation=(
            "Topology node/edge relations are a runtime projection of the live "
            "node fabric registry state. They are NOT a durable structure. "
            "Topology relations reflect current registration/attachment state "
            "and may change as nodes join or leave. Strong vs best-effort relation "
            "strength depends on whether both endpoint nodes are confirmed active."
        ),
    ),
    "topology.galaxy_tree": TruthSourceEntry(
        field_key="topology.galaxy_tree",
        surface_path="core.unified_panel_aggregation / grounded_runtime_topology",
        source_module="core.unified_panel_aggregation.UnifiedPanelAggregationService._fill_grounded_runtime_topology",
        source_authority=None,
        source_kind=SK_COMPILED_OUTWARD_TRUTH,
        is_canonical_truth=False,
        is_durable=False,
        is_projection=True,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.network_topology_runtime",
            "core.nodes.node_fabric_registry",
            "core.canonical_task.CanonicalTaskRuntime",
        ),
        explanation=(
            "The galaxy tree / grounded runtime topology field in the unified panel "
            "is a compiled outward projection that assembles node, device, and "
            "allocation relations into a coherent view. It is a projection of "
            "canonical sources — not itself a canonical truth store."
        ),
    ),
    # ------------------------------------------------------------------
    # Dispatch readiness / degradation truth
    # ------------------------------------------------------------------
    "readiness.verdict": TruthSourceEntry(
        field_key="readiness.verdict",
        surface_path="core.runtime_readiness_matrix",
        source_module="core.runtime_readiness_matrix.ReadinessMatrix.evaluate",
        source_authority=None,
        source_kind=SK_CANONICAL_TRUTH,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=False,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.runtime_readiness_matrix.ReadinessMatrix",
        ),
        explanation=(
            "The readiness verdict (READY/BLOCKED/DEGRADED/UNKNOWN) is produced "
            "by ReadinessMatrix by evaluating all registered readiness dimensions. "
            "Blocked dimensions are the canonical source of truth for why the system "
            "cannot execute tasks."
        ),
    ),
    # ------------------------------------------------------------------
    # Android participation / snapshot / execution truth
    # ------------------------------------------------------------------
    "android.participation_tier": TruthSourceEntry(
        field_key="android.participation_tier",
        surface_path="core.android_network_participation",
        source_module="core.android_network_participation.get_participation_state_for_device",
        source_authority="ANDROID_NETWORK_PARTICIPATION_AUTHORITY",
        source_kind=SK_EVIDENCE_PROJECTION,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=True,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.android_device_state_store.get_device_state_snapshot",
            "core.android_runtime_host.build_android_runtime_host_identity",
            "core.canonical_cross_repo_evidence_pipeline",
        ),
        explanation=(
            "Android participation tier (observable/participant/semi_autonomous) is "
            "projected from Android device state, runtime host identity, and "
            "cross-repo evidence. It is not a registration posture — it reflects "
            "runtime-evidenced participation level."
        ),
    ),
    "android.device_snapshot": TruthSourceEntry(
        field_key="android.device_snapshot",
        surface_path="core.android_device_state_store",
        source_module="core.android_device_state_store.get_device_state_snapshot",
        source_authority=None,
        source_kind=SK_RUNTIME_VISIBLE_STATE,
        is_canonical_truth=True,
        is_durable=True,
        is_projection=False,
        requires_revalidation_after_restart=True,
        evidence_chain=(
            "core.android_device_state_store.DeviceStateStore",
        ),
        explanation=(
            "Android device state snapshots are the authoritative record of "
            "per-device model readiness, accessibility state, and runtime mode. "
            "Snapshots are durable but must be revalidated after host restart "
            "before being treated as live execution truth."
        ),
    ),
    "android.execution_phase": TruthSourceEntry(
        field_key="android.execution_phase",
        surface_path="core.delegated_runtime_execution_tracker",
        source_module="core.delegated_runtime_execution_tracker.build_execution_tracking_snapshot",
        source_authority=None,
        source_kind=SK_CANONICAL_TRUTH,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=False,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.delegated_runtime_execution_tracker.DelegatedRuntimeExecutionTracker",
        ),
        explanation=(
            "Android execution phase tracking is produced by "
            "DelegatedRuntimeExecutionTracker. It tracks accepted handoff, "
            "actual execution, result return, and canonical closure. "
            "This is the authoritative source for Android-side execution evidence."
        ),
    ),
    # ------------------------------------------------------------------
    # Durable / recoverable runtime truth
    # ------------------------------------------------------------------
    "recovery.delegated_flow_state": TruthSourceEntry(
        field_key="recovery.delegated_flow_state",
        surface_path="core.delegated_flow_persistence",
        source_module="core.delegated_flow_persistence.DelegatedFlowPersistence",
        source_authority=None,
        source_kind=SK_CANONICAL_TRUTH,
        is_canonical_truth=True,
        is_durable=True,
        is_projection=False,
        requires_revalidation_after_restart=True,
        evidence_chain=(
            "core.delegated_flow_persistence.DelegatedFlowPersistence",
            "core.delegated_flow_recovery_coordinator",
        ),
        explanation=(
            "Delegated flow state is durably persisted. After restart, "
            "restored flow state is historical/unrevalidated until the "
            "recovery coordinator performs revalidation. Stale or "
            "unrevalidated state must not be treated as live truth."
        ),
    ),
    "recovery.android_continuity": TruthSourceEntry(
        field_key="recovery.android_continuity",
        surface_path="core.android_continuity_recovery_state_router",
        source_module="core.android_continuity_recovery_state_router",
        source_authority=None,
        source_kind=SK_RUNTIME_VISIBLE_STATE,
        is_canonical_truth=True,
        is_durable=False,
        is_projection=False,
        requires_revalidation_after_restart=True,
        evidence_chain=(
            "core.android_continuity_recovery_state_router.get_recovery_state_router",
        ),
        explanation=(
            "Android continuity recovery state tracks whether the Android session "
            "is in a live, recovering, or degraded state. Recovery is partial when "
            "only some persisted artifacts are available; coherent recovery requires "
            "the Android host to reconfirm session state."
        ),
    ),
    # ------------------------------------------------------------------
    # Operator-visible runtime state
    # ------------------------------------------------------------------
    "operator.snapshot": TruthSourceEntry(
        field_key="operator.snapshot",
        surface_path="/api/v1/operator/snapshot",
        source_module="core.operator_surface.OperatorSurface.operator_snapshot",
        source_authority="OPERATOR_SURFACE_AUTHORITY",
        source_kind=SK_OPERATOR_DERIVED_SURFACE,
        is_canonical_truth=False,
        is_durable=False,
        is_projection=True,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.canonical_task.CanonicalTaskRuntime",
            "core.network_topology_runtime",
            "core.capability_assimilation",
            "core.android_device_state_store",
        ),
        explanation=(
            "The operator snapshot is a compiled projection over multiple canonical "
            "runtime sources. It is NOT a canonical truth source itself — it reads "
            "from canonical sources and projects them into an operator-friendly view. "
            "The underlying canonical sources are listed in evidence_chain."
        ),
    ),
    "operator.panel_unified": TruthSourceEntry(
        field_key="operator.panel_unified",
        surface_path="/api/v1/panel/unified",
        source_module="core.unified_panel_aggregation.UnifiedPanelAggregationService.build_payload",
        source_authority="UNIFIED_PANEL_AGGREGATION_AUTHORITY",
        source_kind=SK_COMPILED_OUTWARD_TRUTH,
        is_canonical_truth=False,
        is_durable=False,
        is_projection=True,
        requires_revalidation_after_restart=False,
        evidence_chain=(
            "core.outward_runtime_truth.compile_outward_truth",
            "core.operator_surface.OperatorSurface.operator_snapshot",
            "core.android_device_state_store.get_device_ecosystem_summary",
            "core.projection.build_runtime_projection",
            "core.runtime_readiness_matrix.ReadinessMatrix",
        ),
        explanation=(
            "The unified panel payload is a compiled outward projection. "
            "It reads from existing canonical singletons and does NOT introduce "
            "a new truth store. The primary source path is compile_outward_truth(); "
            "all other sources are secondary or fallback."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_registry() -> Dict[str, TruthSourceEntry]:
    """Return the full truth source registry (field_key → entry)."""
    return dict(_REGISTRY)


def get_entry(field_key: str) -> Optional[TruthSourceEntry]:
    """Return the registry entry for *field_key*, or ``None`` if not found."""
    return _REGISTRY.get(field_key)


def assert_source_for_field(field_key: str, claimed_source: str) -> None:
    """Assert that *field_key* is registered as coming from *claimed_source*.

    Raises
    ------
    KeyError:
        When *field_key* is not in the registry.
    AssertionError:
        When the registry entry's ``source_module`` does not match
        *claimed_source*.
    """
    entry = _REGISTRY[field_key]
    assert claimed_source in entry.source_module or claimed_source in (entry.source_authority or ""), (
        f"Field '{field_key}': claimed source '{claimed_source}' does not match "
        f"registered source '{entry.source_module}' (authority: {entry.source_authority!r})"
    )


def build_registry_snapshot() -> Dict[str, Any]:
    """Return a full JSON-serialisable snapshot of the registry for operator surfaces."""
    return {
        "authority": OUTWARD_TRUTH_SOURCE_REGISTRY_AUTHORITY,
        "entry_count": len(_REGISTRY),
        "entries": {k: v.to_dict() for k, v in _REGISTRY.items()},
    }
