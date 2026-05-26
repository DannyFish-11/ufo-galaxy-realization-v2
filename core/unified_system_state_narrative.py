"""
core/unified_system_state_narrative.py
========================================
Focused Convergence Pass — Unified System-State Narrative

Purpose
-------
Organises existing canonical runtime truth into a single, coherent 7-dimension
narrative so that users and operators can understand:

  1. Whether the system is currently operable and why.
  2. What the main current operating structure is.
  3. What task execution state looks like right now.
  4. Which devices are dispatchable and why (or why not).
  5. What autonomy / participation tier each device is at and on what evidence.
  6. What topology / allocation relations are active.
  7. What recovery / degradation / blockage conditions exist.

Design rules
------------
- **Read-only projections only** — this module never writes state.
- **Single truth** — reads from existing canonical singletons; does NOT
  introduce a new truth store.
- **Source-annotated** — every dimension carries ``source``,
  ``is_canonical_truth``, and ``evidence_basis`` fields so operators can
  trace each value back to its authoritative substrate.
- **Graceful degradation** — individual source failures leave that dimension
  at a safe default rather than failing the whole narrative.
- **Explainability** — each dimension includes a human-readable ``explanation``
  summarising *why* the system is in that state.

Public API
----------
Authority sentinels::

    UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY
    UNIFIED_SYSTEM_STATE_NARRATIVE_VERSION

Dataclasses::

    NarrativeDimension       — single dimension result
    SystemStateNarrative     — the full 7-dimension narrative

Functions::

    build_system_state_narrative() -> SystemStateNarrative
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.UnifiedSystemStateNarrative")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY: str = (
    "UNIFIED_SYSTEM_STATE_NARRATIVE_V1: "
    "core.unified_system_state_narrative organises existing canonical runtime "
    "truth into a coherent 7-dimension narrative.  It reads exclusively from "
    "existing canonical singletons and does NOT introduce a new truth store.  "
    "Every dimension is source-annotated so operators can trace values to their "
    "authoritative substrate."
)

UNIFIED_SYSTEM_STATE_NARRATIVE_VERSION: str = "1.0"

# ---------------------------------------------------------------------------
# Operability state constants
# ---------------------------------------------------------------------------

OPERABILITY_OPERABLE: str = "operable"
OPERABILITY_BLOCKED: str = "blocked"
OPERABILITY_DEGRADED: str = "degraded"
OPERABILITY_UNKNOWN: str = "unknown"

ALL_KNOWN_OPERABILITY_STATES: frozenset = frozenset({
    OPERABILITY_OPERABLE,
    OPERABILITY_BLOCKED,
    OPERABILITY_DEGRADED,
    OPERABILITY_UNKNOWN,
    "error",
    "unavailable",
    "no_active_degradation",
})

# ---------------------------------------------------------------------------
# Autonomy tier classification constants
# ---------------------------------------------------------------------------

_STRONG_AUTONOMY_TIERS: frozenset = frozenset({
    "semi_autonomous", "distributed_participant", "strong",
})
_LIMITED_AUTONOMY_TIERS: frozenset = frozenset({
    "observable", "participant", "limited",
})

# ---------------------------------------------------------------------------
# Dimension names (stable constants for downstream consumers)
# ---------------------------------------------------------------------------

DIM_OVERALL_RUNTIME_STATE: str = "overall_runtime_state"
DIM_OPERATING_STRUCTURE: str = "operating_structure"
DIM_TASK_EXECUTION_STATE: str = "task_execution_state"
DIM_DEVICE_DISPATCH_SUPPORT_STATE: str = "device_dispatch_support_state"
DIM_AUTONOMY_PARTICIPATION_STATE: str = "autonomy_participation_state"
DIM_TOPOLOGY_ALLOCATION_RELATIONS: str = "topology_allocation_relations"
DIM_RECOVERY_DEGRADATION_BLOCKAGE: str = "recovery_degradation_blockage"

ALL_NARRATIVE_DIMENSIONS: tuple = (
    DIM_OVERALL_RUNTIME_STATE,
    DIM_OPERATING_STRUCTURE,
    DIM_TASK_EXECUTION_STATE,
    DIM_DEVICE_DISPATCH_SUPPORT_STATE,
    DIM_AUTONOMY_PARTICIPATION_STATE,
    DIM_TOPOLOGY_ALLOCATION_RELATIONS,
    DIM_RECOVERY_DEGRADATION_BLOCKAGE,
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NarrativeDimension:
    """Result for one of the 7 narrative dimensions.

    Attributes
    ----------
    dimension:
        One of the ``DIM_*`` constants defined in this module.
    state:
        Current state value for this dimension (e.g. ``"operable"``,
        ``"blocked"``, ``"degraded"``).
    source:
        Fully qualified module path or authority string for the canonical
        source that produced the ``state`` value.
    is_canonical_truth:
        ``True`` when ``state`` is sourced from a canonical runtime substrate;
        ``False`` when it is a fallback / projection / derived value.
    explanation:
        Human-readable sentence explaining *why* the dimension is in the
        current state — not just what the state is.
    evidence_basis:
        Key evidence items or metric values that determined the state.
    traceability:
        Detailed trace (ordered list of reasoning steps or signal names)
        showing how the state was reached.
    source_authority:
        Optional authority sentinel string from the source module if available.
    compiled_at:
        Unix timestamp when this dimension was compiled.
    """

    dimension: str
    state: str
    source: str
    is_canonical_truth: bool
    explanation: str
    evidence_basis: Dict[str, Any] = field(default_factory=dict)
    traceability: List[str] = field(default_factory=list)
    source_authority: Optional[str] = None
    compiled_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "state": self.state,
            "source": self.source,
            "is_canonical_truth": self.is_canonical_truth,
            "explanation": self.explanation,
            "evidence_basis": dict(self.evidence_basis),
            "traceability": list(self.traceability),
            "source_authority": self.source_authority,
            "compiled_at": self.compiled_at,
        }


@dataclass
class SystemStateNarrative:
    """The full 7-dimension coherent system-state narrative.

    Built from existing canonical runtime truth.  Each dimension is
    independently sourced and source-annotated.

    Attributes
    ----------
    narrative_id:
        Unique ID for this narrative instance.
    compiled_at:
        Unix timestamp when the narrative was assembled.
    authority:
        Authority sentinel identifying this module as the builder.
    version:
        Schema version string.
    dimensions:
        Mapping from dimension name → :class:`NarrativeDimension`.
    is_fully_sourced:
        ``True`` when all 7 dimensions were successfully sourced from
        canonical substrates.
    unsourced_dimensions:
        List of dimension names that fell back to defaults.
    overall_operability:
        Top-level operability verdict derived from
        :attr:`~NarrativeDimension.state` of
        :data:`DIM_OVERALL_RUNTIME_STATE`.
    overall_explanation:
        A single consolidated explanation sentence describing the most
        important current system-state condition.
    """

    narrative_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    compiled_at: float = field(default_factory=time.time)
    authority: str = UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY
    version: str = UNIFIED_SYSTEM_STATE_NARRATIVE_VERSION
    dimensions: Dict[str, NarrativeDimension] = field(default_factory=dict)
    is_fully_sourced: bool = False
    unsourced_dimensions: List[str] = field(default_factory=list)
    overall_operability: str = "unknown"
    overall_explanation: str = ""

    def get_dimension(self, name: str) -> Optional[NarrativeDimension]:
        """Return a dimension by name, or ``None`` if absent."""
        return self.dimensions.get(name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "narrative_id": self.narrative_id,
            "compiled_at": self.compiled_at,
            "authority": self.authority,
            "version": self.version,
            "overall_operability": self.overall_operability,
            "overall_explanation": self.overall_explanation,
            "is_fully_sourced": self.is_fully_sourced,
            "unsourced_dimensions": list(self.unsourced_dimensions),
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
        }


# ---------------------------------------------------------------------------
# Internal helpers — dimension builders
# ---------------------------------------------------------------------------


def _safe(fn: Any, default: Any) -> Any:
    """Call *fn()* and return its result; return *default* on any exception."""
    try:
        return fn()
    except Exception as exc:
        logger.debug("narrative safe call failed: %s", exc)
        return default


def _get_record_status(record: Any) -> str:
    """Extract and normalise the status string from an allocation record.

    Works with both dataclass instances (attribute access) and plain dicts
    (key access).

    Returns
    -------
    str
        The lowercased status string, or ``""`` when the record has no status.
    """
    if isinstance(record, dict):
        return str(record.get("status") or "").lower()
    return str(getattr(record, "status", "") or "").lower()


def _get_record_value(record: Any, key: str) -> Any:
    """Extract a value from an allocation record regardless of its type."""
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def _build_overall_runtime_state() -> NarrativeDimension:
    """Dimension 1: Is the system currently operable and why?"""
    state = "unknown"
    explanation = "Runtime readiness matrix unavailable."
    evidence: Dict[str, Any] = {}
    trace: List[str] = ["readiness_matrix_query"]
    source_authority: Optional[str] = None
    is_canonical = False

    try:
        from core.runtime_readiness_matrix import ReadinessMatrix, ReadinessVerdict
        matrix = ReadinessMatrix()
        verdict = matrix.evaluate()
        verdict_str = verdict.verdict if hasattr(verdict, "verdict") else str(verdict)
        blocked = getattr(verdict, "blocked_dimensions", []) or []
        degraded = getattr(verdict, "degraded_dimensions", []) or []
        notes = getattr(verdict, "notes", []) or []

        ready_value = ReadinessVerdict.READY.value if hasattr(ReadinessVerdict, "READY") else "READY"
        if verdict_str == ready_value:
            state = "operable"
            explanation = "All readiness dimensions are satisfied; the system is currently operable."
        elif verdict_str in ("BLOCKED", "blocked"):
            state = "blocked"
            blocked_str = ", ".join(blocked) if blocked else "unspecified"
            explanation = (
                f"System is blocked by readiness dimension(s): {blocked_str}. "
                f"All blocking conditions must be resolved before task execution can proceed."
            )
        elif verdict_str in ("DEGRADED", "degraded"):
            state = "degraded"
            degraded_str = ", ".join(degraded) if degraded else "unspecified"
            explanation = (
                f"System is degraded in dimension(s): {degraded_str}. "
                f"Task execution may proceed with reduced capability or reliability."
            )
        else:
            state = verdict_str.lower() if verdict_str else "unknown"
            explanation = f"Readiness verdict: {verdict_str}. Notes: {notes}"

        evidence = {
            "verdict": verdict_str,
            "blocked_dimensions": blocked,
            "degraded_dimensions": degraded,
            "notes": list(notes),
        }
        trace = [
            "core.runtime_readiness_matrix.ReadinessMatrix.evaluate()",
            f"verdict={verdict_str}",
            *[f"blocked:{d}" for d in blocked],
            *[f"degraded:{d}" for d in degraded],
        ]
        is_canonical = True
    except Exception as exc:
        logger.debug("overall_runtime_state: readiness matrix failed: %s", exc)
        trace.append(f"readiness_matrix_failed:{exc}")

    # Supplement with outward truth surfacing_complete if available
    try:
        from core.outward_runtime_truth import compile_outward_truth
        outward = compile_outward_truth()
        evidence["surfacing_complete"] = outward.surfacing_complete
        evidence["unavailable_source_count"] = outward.unavailable_source_count
        if not outward.surfacing_complete and state == "operable":
            state = "degraded"
            explanation += (
                f" However, {outward.unavailable_source_count} canonical source(s) "
                f"were unavailable during truth compilation, indicating partial degradation."
            )
        trace.append(
            f"outward_truth_surfacing_complete={outward.surfacing_complete}"
        )
        is_canonical = True
    except Exception as exc:
        logger.debug("overall_runtime_state: outward truth unavailable: %s", exc)
        trace.append(f"outward_truth_failed:{exc}")

    return NarrativeDimension(
        dimension=DIM_OVERALL_RUNTIME_STATE,
        state=state,
        source="core.runtime_readiness_matrix.ReadinessMatrix + core.outward_runtime_truth.compile_outward_truth",
        is_canonical_truth=is_canonical,
        explanation=explanation,
        evidence_basis=evidence,
        traceability=trace,
        source_authority=(
            "RUNTIME_READINESS_MATRIX_AUTHORITY + OUTWARD_RUNTIME_TRUTH_AUTHORITY"
        ),
    )


def _build_operating_structure() -> NarrativeDimension:
    """Dimension 2: What is the main current operating structure?"""
    state = "unknown"
    explanation = "Node fabric registry unavailable."
    evidence: Dict[str, Any] = {}
    trace: List[str] = ["node_fabric_registry_query"]
    is_canonical = False

    try:
        from core.nodes.node_fabric_registry import (
            CANONICAL_RUNTIME_NODE_REGISTRY_AUTHORITY,
            get_node_fabric_registry,
        )
        fab = get_node_fabric_registry()
        nodes = fab.list_nodes()
        node_count = len(nodes)

        # Node role breakdown
        role_counts: Dict[str, int] = {}
        for n in nodes:
            role = (
                getattr(n, "role", None)
                or (n.get("role") if isinstance(n, dict) else None)
                or "unknown"
            )
            role_counts[str(role)] = role_counts.get(str(role), 0) + 1

        state = f"active:{node_count}_nodes"
        explanation = (
            f"NodeFabricRegistry reports {node_count} registered node(s). "
            f"Role distribution: {role_counts}. "
            f"The NodeFabricRegistry is the canonical source for node/worker/service-endpoint ontology."
        )
        evidence = {
            "canonical_node_count": node_count,
            "role_distribution": role_counts,
            "registry": "core.nodes.node_fabric_registry.NodeFabricRegistry",
            "legacy_registry_is_runtime_authority": False,
        }
        trace = [
            "core.nodes.node_fabric_registry.get_node_fabric_registry()",
            f"node_count={node_count}",
            *[f"role_{k}={v}" for k, v in role_counts.items()],
        ]
        is_canonical = True
        source_authority_val: Optional[str] = CANONICAL_RUNTIME_NODE_REGISTRY_AUTHORITY
    except Exception as exc:
        logger.debug("operating_structure: node fabric registry failed: %s", exc)
        trace.append(f"node_fabric_registry_failed:{exc}")
        source_authority_val = None

    # Supplement with topology info if available
    try:
        from core.network_topology_runtime import get_network_topology_runtime
        topo = get_network_topology_runtime()
        topo_nodes = topo.node_count() if hasattr(topo, "node_count") else len(
            getattr(topo, "_nodes", {}) or {}
        )
        topo_edges = topo.edge_count() if hasattr(topo, "edge_count") else len(
            getattr(topo, "_edges", []) or []
        )
        evidence["topology_node_count"] = topo_nodes
        evidence["topology_edge_count"] = topo_edges
        evidence[
            "topology_note"
        ] = "Topology is a runtime projection of node relations, not an independent truth store."
        trace.append(f"topology_nodes={topo_nodes},edges={topo_edges}")
        is_canonical = True
    except Exception as exc:
        logger.debug("operating_structure: topology unavailable: %s", exc)
        trace.append(f"topology_failed:{exc}")

    return NarrativeDimension(
        dimension=DIM_OPERATING_STRUCTURE,
        state=state,
        source="core.nodes.node_fabric_registry.NodeFabricRegistry + core.network_topology_runtime",
        is_canonical_truth=is_canonical,
        explanation=explanation,
        evidence_basis=evidence,
        traceability=trace,
        source_authority=source_authority_val,  # type: ignore[arg-type]
    )


def _build_task_execution_state() -> NarrativeDimension:
    """Dimension 3: What is the current task execution state?"""
    state = "unknown"
    explanation = "Canonical task runtime unavailable."
    evidence: Dict[str, Any] = {}
    trace: List[str] = ["canonical_task_runtime_query"]
    is_canonical = False

    try:
        from core.canonical_task import get_canonical_task_runtime
        runtime = get_canonical_task_runtime()
        active_records = runtime.list_allocation_records(limit=256)
        active_count = len(active_records)

        # Classify records by state using the shared helper
        pending = [r for r in active_records if _get_record_status(r) in ("pending", "waiting", "queued")]
        executing = [r for r in active_records if _get_record_status(r) in ("executing", "running", "active", "in_progress")]
        completed = [r for r in active_records if _get_record_status(r) in ("completed", "success", "closed", "terminal")]
        failed = [r for r in active_records if _get_record_status(r) in ("failed", "error", "rejected", "blocked")]

        if active_count == 0:
            state = "idle"
            explanation = (
                "No active allocation records in CanonicalTaskRuntime. "
                "The system is idle with no pending or executing tasks."
            )
        elif executing:
            state = f"executing:{len(executing)}_tasks"
            explanation = (
                f"CanonicalTaskRuntime reports {len(executing)} actively executing task(s) "
                f"and {len(pending)} pending, {len(completed)} recently completed, "
                f"{len(failed)} failed allocation records."
            )
        elif pending:
            state = f"pending:{len(pending)}_tasks"
            explanation = (
                f"CanonicalTaskRuntime reports {len(pending)} pending task(s). "
                f"Tasks are queued but none are actively executing."
            )
        else:
            state = f"records:{active_count}"
            explanation = (
                f"CanonicalTaskRuntime has {active_count} allocation record(s) "
                f"in mixed states."
            )

        evidence = {
            "total_allocation_records": active_count,
            "pending_count": len(pending),
            "executing_count": len(executing),
            "completed_count": len(completed),
            "failed_count": len(failed),
            "source": "core.canonical_task.CanonicalTaskRuntime",
        }
        trace = [
            "core.canonical_task.get_canonical_task_runtime()",
            "list_allocation_records(limit=256)",
            f"total={active_count}",
            f"executing={len(executing)}",
            f"pending={len(pending)}",
            f"failed={len(failed)}",
        ]
        is_canonical = True
    except Exception as exc:
        logger.debug("task_execution_state: canonical task runtime failed: %s", exc)
        trace.append(f"canonical_task_runtime_failed:{exc}")

    return NarrativeDimension(
        dimension=DIM_TASK_EXECUTION_STATE,
        state=state,
        source="core.canonical_task.CanonicalTaskRuntime",
        is_canonical_truth=is_canonical,
        explanation=explanation,
        evidence_basis=evidence,
        traceability=trace,
        source_authority="CANONICAL_TASK_RUNTIME_AUTHORITY",
    )


def _build_device_dispatch_support_state() -> NarrativeDimension:
    """Dimension 4: Which devices are dispatchable and why (or why not)?"""
    state = "unknown"
    explanation = "Device dispatch readiness surface unavailable."
    evidence: Dict[str, Any] = {}
    trace: List[str] = ["device_dispatch_readiness_surface_query"]
    is_canonical = False

    try:
        from core.device_dispatch_readiness_surface import (
            DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY,
            get_dispatch_readiness_panel,
        )
        panel = get_dispatch_readiness_panel()
        devices = panel.get("devices") or []
        summary = panel.get("summary") or {}

        ready_count = int(summary.get("dispatch_ready_count", 0) or 0)
        total_count = len(devices)
        blocked_count = total_count - ready_count

        if total_count == 0:
            state = "no_devices"
            explanation = (
                "No devices are known to the dispatch readiness surface. "
                "The system has no dispatchable device registered."
            )
        elif ready_count == total_count:
            state = f"all_ready:{ready_count}_devices"
            explanation = (
                f"All {ready_count} device(s) pass dispatch readiness gates. "
                f"Each device has satisfied registration, capability, and operational-support requirements."
            )
        elif ready_count > 0:
            state = f"partial_ready:{ready_count}_of_{total_count}"
            explanation = (
                f"{ready_count} of {total_count} device(s) are dispatch-ready; "
                f"{blocked_count} are blocked. See evidence_basis.device_blockers for per-device reasons."
            )
        else:
            state = f"none_ready:{total_count}_blocked"
            explanation = (
                f"None of the {total_count} known device(s) pass dispatch readiness. "
                f"See evidence_basis.device_blockers for per-device blocker reasons."
            )

        # Collect per-device blocker summaries for traceability
        device_blockers = []
        for d in devices:
            did = d.get("device_id", "unknown")
            is_ready = bool(d.get("dispatch_ready", False))
            blockers = d.get("blockers") or d.get("blocking_reasons") or []
            device_blockers.append({
                "device_id": did,
                "dispatch_ready": is_ready,
                "blockers": blockers,
            })

        evidence = {
            "total_devices": total_count,
            "dispatch_ready_count": ready_count,
            "blocked_count": blocked_count,
            "summary": dict(summary),
            "device_blockers": device_blockers,
        }
        trace = [
            "core.device_dispatch_readiness_surface.get_dispatch_readiness_panel()",
            f"total_devices={total_count}",
            f"dispatch_ready={ready_count}",
            f"blocked={blocked_count}",
        ]
        for d in device_blockers:
            if not d["dispatch_ready"]:
                trace.append(
                    f"device:{d['device_id']} blocked by: {d['blockers']}"
                )
        is_canonical = True

        return NarrativeDimension(
            dimension=DIM_DEVICE_DISPATCH_SUPPORT_STATE,
            state=state,
            source="core.device_dispatch_readiness_surface.get_dispatch_readiness_panel",
            is_canonical_truth=is_canonical,
            explanation=explanation,
            evidence_basis=evidence,
            traceability=trace,
            source_authority=DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY,
        )
    except Exception as exc:
        logger.debug("device_dispatch_support_state: failed: %s", exc)
        trace.append(f"dispatch_readiness_surface_failed:{exc}")

    # Fallback: try device_operational_support for at least static tier info
    try:
        from core.device_operational_support import (
            DEVICE_OPERATIONAL_SUPPORT_AUTHORITY,
            NEAR_PEER_OPERATIONAL_TYPES,
            OBSERVABLE_BUT_NON_OPERATIONAL_TYPES,
        )
        evidence["near_peer_operational_types"] = sorted(NEAR_PEER_OPERATIONAL_TYPES)
        evidence["observable_only_types"] = sorted(OBSERVABLE_BUT_NON_OPERATIONAL_TYPES)
        evidence[
            "support_note"
        ] = "Static device support classification — runtime dispatch readiness unavailable."
        state = "support_classification_only"
        explanation = (
            "Runtime dispatch readiness surface is unavailable; falling back to static "
            f"device support classification. Near-peer operational types: "
            f"{sorted(NEAR_PEER_OPERATIONAL_TYPES)}."
        )
        trace.append("fallback:core.device_operational_support static classification")
        is_canonical = False

        return NarrativeDimension(
            dimension=DIM_DEVICE_DISPATCH_SUPPORT_STATE,
            state=state,
            source="core.device_operational_support (static fallback)",
            is_canonical_truth=is_canonical,
            explanation=explanation,
            evidence_basis=evidence,
            traceability=trace,
            source_authority=DEVICE_OPERATIONAL_SUPPORT_AUTHORITY,
        )
    except Exception as exc2:
        logger.debug("device_dispatch_support_state: fallback also failed: %s", exc2)
        trace.append(f"static_classification_failed:{exc2}")

    return NarrativeDimension(
        dimension=DIM_DEVICE_DISPATCH_SUPPORT_STATE,
        state="unavailable",
        source="unavailable",
        is_canonical_truth=False,
        explanation=(
            "Both the dispatch readiness surface and static device support classification "
            "are unavailable. Device dispatch state cannot be determined."
        ),
        evidence_basis={},
        traceability=trace,
    )


def _build_autonomy_participation_state() -> NarrativeDimension:
    """Dimension 5: What autonomy/participation tier and evidence?"""
    state = "unknown"
    explanation = "Android participation and autonomy evidence unavailable."
    evidence: Dict[str, Any] = {}
    trace: List[str] = ["android_participation_query"]
    is_canonical = False

    try:
        from core.android_network_participation import (
            ANDROID_NETWORK_PARTICIPATION_AUTHORITY,
            AndroidParticipationTier,
            get_participation_state_for_device,
        )
        from core.android_device_state_store import list_device_state_snapshots
        snaps = list_device_state_snapshots()
        device_results = []
        for snap in snaps:
            did = snap.device_id
            try:
                part_state = get_participation_state_for_device(did)
                tier = (
                    part_state.tier.value
                    if hasattr(part_state, "tier") and hasattr(part_state.tier, "value")
                    else str(getattr(part_state, "tier", "unknown"))
                )
                reasons = getattr(part_state, "blocking_reasons", []) or []
                notes = getattr(part_state, "tier_derivation_notes", []) or []
                device_results.append({
                    "device_id": did,
                    "tier": tier,
                    "blocking_reasons": list(reasons),
                    "tier_derivation_notes": list(notes),
                })
            except Exception as inner:
                device_results.append({"device_id": did, "tier": "unknown", "error": str(inner)})

        total = len(device_results)
        strong = [d for d in device_results if d.get("tier") in _STRONG_AUTONOMY_TIERS]
        limited = [d for d in device_results if d.get("tier") in _LIMITED_AUTONOMY_TIERS]

        if total == 0:
            state = "no_android_devices"
            explanation = (
                "No Android devices have active state snapshots. "
                "Autonomy/participation tier cannot be determined without active device sessions."
            )
        elif strong:
            state = f"strong_participation:{len(strong)}_devices"
            explanation = (
                f"{len(strong)} device(s) at strong autonomy/participation tiers "
                f"({len(limited)} limited, {total - len(strong) - len(limited)} unknown). "
                f"Stronger tiers require cross-repo execution evidence, not just posture."
            )
        else:
            state = f"limited_participation:{total}_devices"
            explanation = (
                f"{total} device(s) at limited/observable participation tiers. "
                f"Strong autonomy classes require cross-repo runtime evidence including "
                f"accepted execution, result return, and closure integration."
            )

        evidence = {
            "total_device_snapshots": total,
            "strong_participation_count": len(strong),
            "limited_participation_count": len(limited),
            "device_participation": device_results,
        }
        trace = [
            "core.android_device_state_store.list_device_state_snapshots()",
            "core.android_network_participation.get_participation_state_for_device(device_id)",
            f"total_devices={total}",
            f"strong={len(strong)}",
            f"limited={len(limited)}",
        ]
        is_canonical = True

        return NarrativeDimension(
            dimension=DIM_AUTONOMY_PARTICIPATION_STATE,
            state=state,
            source=(
                "core.android_network_participation.get_participation_state_for_device"
                " + core.android_device_state_store"
            ),
            is_canonical_truth=is_canonical,
            explanation=explanation,
            evidence_basis=evidence,
            traceability=trace,
            source_authority=ANDROID_NETWORK_PARTICIPATION_AUTHORITY,
        )
    except Exception as exc:
        logger.debug("autonomy_participation_state: failed: %s", exc)
        trace.append(f"android_participation_failed:{exc}")

    # Fallback: device_autonomy_evidence (best-effort)
    try:
        from core.device_autonomy_evidence import (
            DEVICE_AUTONOMY_EVIDENCE_AUTHORITY,
            build_device_autonomy_summary,
        )
        summary = build_device_autonomy_summary()
        state = summary.get("overall_class", "unknown")
        explanation = summary.get("explanation", "Device autonomy evidence summary.")
        evidence = dict(summary)
        trace.append("fallback:core.device_autonomy_evidence.build_device_autonomy_summary()")
        is_canonical = True

        return NarrativeDimension(
            dimension=DIM_AUTONOMY_PARTICIPATION_STATE,
            state=state,
            source="core.device_autonomy_evidence.build_device_autonomy_summary",
            is_canonical_truth=is_canonical,
            explanation=explanation,
            evidence_basis=evidence,
            traceability=trace,
            source_authority=DEVICE_AUTONOMY_EVIDENCE_AUTHORITY,
        )
    except Exception as exc2:
        logger.debug("autonomy_participation_state: fallback failed: %s", exc2)
        trace.append(f"autonomy_evidence_failed:{exc2}")

    return NarrativeDimension(
        dimension=DIM_AUTONOMY_PARTICIPATION_STATE,
        state="unavailable",
        source="unavailable",
        is_canonical_truth=False,
        explanation=(
            "Android participation and device autonomy evidence modules are unavailable. "
            "Autonomy tier cannot be determined."
        ),
        evidence_basis={},
        traceability=trace,
    )


def _build_topology_allocation_relations() -> NarrativeDimension:
    """Dimension 6: What topology/allocation relations are active?"""
    state = "unknown"
    explanation = "Topology and allocation substrates unavailable."
    evidence: Dict[str, Any] = {}
    trace: List[str] = ["topology_allocation_query"]
    is_canonical = False

    # Allocation records from canonical task runtime
    try:
        from core.canonical_task import get_canonical_task_runtime
        runtime = get_canonical_task_runtime()
        alloc_records = runtime.list_allocation_records(limit=256)

        accepted = [
            r for r in alloc_records
            if str(_get_record_value(r, "accepted_allocation") or "").lower() == "accepted"
        ]
        active_executors: Dict[str, int] = {}
        for r in accepted:
            exec_loc = (
                _get_record_value(r, "execution_location")
                or _get_record_value(r, "selected_executor")
            )
            if exec_loc:
                active_executors[str(exec_loc)] = active_executors.get(str(exec_loc), 0) + 1

        evidence["allocation_records_total"] = len(alloc_records)
        evidence["accepted_allocation_count"] = len(accepted)
        evidence["active_executors"] = dict(active_executors)
        evidence[
            "allocation_source"
        ] = "core.canonical_task.CanonicalTaskRuntime.list_allocation_records"
        trace.append(
            f"canonical_task_runtime: {len(alloc_records)} records, {len(accepted)} accepted"
        )
        is_canonical = True
    except Exception as exc:
        logger.debug("topology_allocation_relations: canonical task runtime failed: %s", exc)
        trace.append(f"canonical_task_runtime_failed:{exc}")

    # Topology from NetworkTopologyRuntime
    try:
        from core.network_topology_runtime import get_network_topology_runtime
        topo = get_network_topology_runtime()
        topo_nodes = topo.node_count() if hasattr(topo, "node_count") else len(
            getattr(topo, "_nodes", {}) or {}
        )
        topo_edges = topo.edge_count() if hasattr(topo, "edge_count") else len(
            getattr(topo, "_edges", []) or []
        )
        evidence["topology_node_count"] = topo_nodes
        evidence["topology_edge_count"] = topo_edges
        evidence[
            "topology_projection_note"
        ] = (
            "Topology is a runtime projection of node/device relations. "
            "Relation strength depends on underlying state quality."
        )
        trace.append(f"network_topology: {topo_nodes} nodes, {topo_edges} edges")
        is_canonical = True
    except Exception as exc:
        logger.debug("topology_allocation_relations: topology failed: %s", exc)
        trace.append(f"topology_failed:{exc}")

    # Build state and explanation from collected evidence
    topo_n = evidence.get("topology_node_count", 0)
    alloc_total = evidence.get("allocation_records_total", 0)
    accepted_total = evidence.get("accepted_allocation_count", 0)
    exec_map = evidence.get("active_executors", {})

    if topo_n > 0 or alloc_total > 0:
        state = f"topology:{topo_n}_nodes,allocations:{accepted_total}_accepted"
        explanation = (
            f"Topology has {topo_n} node(s) and {evidence.get('topology_edge_count', 0)} edge(s). "
            f"Allocation system has {alloc_total} record(s) total, {accepted_total} accepted. "
            f"Active executor assignments: {exec_map}. "
            f"Note: topology is a runtime projection — relations reflect runtime state, not durable structure."
        )
    else:
        state = "no_topology_or_allocation_data"
        explanation = (
            "No topology nodes or allocation records found. "
            "The system has no active topology relations or task allocations."
        )

    return NarrativeDimension(
        dimension=DIM_TOPOLOGY_ALLOCATION_RELATIONS,
        state=state,
        source="core.canonical_task.CanonicalTaskRuntime + core.network_topology_runtime",
        is_canonical_truth=is_canonical,
        explanation=explanation,
        evidence_basis=evidence,
        traceability=trace,
        source_authority="CANONICAL_TASK_RUNTIME_AUTHORITY + NETWORK_TOPOLOGY_RUNTIME_AUTHORITY",
    )


def _build_recovery_degradation_blockage() -> NarrativeDimension:
    """Dimension 7: What recovery/degradation/blockage conditions exist?"""
    state = "unknown"
    explanation = "Recovery and degradation state surfaces unavailable."
    evidence: Dict[str, Any] = {}
    trace: List[str] = ["recovery_degradation_query"]
    is_canonical = False

    # Runtime readiness matrix — blocked/degraded dimensions
    try:
        from core.runtime_readiness_matrix import ReadinessMatrix, ReadinessVerdict
        matrix = ReadinessMatrix()
        verdict = matrix.evaluate()
        verdict_str = verdict.verdict if hasattr(verdict, "verdict") else str(verdict)
        blocked = getattr(verdict, "blocked_dimensions", []) or []
        degraded = getattr(verdict, "degraded_dimensions", []) or []

        evidence["readiness_verdict"] = verdict_str
        evidence["blocked_dimensions"] = list(blocked)
        evidence["degraded_dimensions"] = list(degraded)
        trace.append(
            f"readiness_matrix: verdict={verdict_str}, blocked={blocked}, degraded={degraded}"
        )
        is_canonical = True
    except Exception as exc:
        logger.debug("recovery_degradation: readiness matrix failed: %s", exc)
        trace.append(f"readiness_matrix_failed:{exc}")

    # Delegated flow recovery
    try:
        from core.delegated_flow_recovery_coordinator import (
            get_recovery_coordinator,
        )
        coord = get_recovery_coordinator()
        recovery_state = coord.get_recovery_state() if hasattr(coord, "get_recovery_state") else {}
        if recovery_state:
            evidence["delegated_flow_recovery"] = dict(recovery_state)
            trace.append(f"delegated_flow_recovery: {recovery_state}")
    except Exception as exc:
        logger.debug("recovery_degradation: delegated flow recovery failed: %s", exc)
        trace.append(f"delegated_flow_recovery_failed:{exc}")

    # Android continuity recovery router
    try:
        from core.android_continuity_recovery_state_router import (
            get_recovery_state_router,
        )
        router = get_recovery_state_router()
        android_recovery = (
            router.get_current_recovery_state()
            if hasattr(router, "get_current_recovery_state")
            else {}
        )
        if android_recovery:
            evidence["android_recovery_state"] = dict(android_recovery)
            trace.append(f"android_recovery_state: {android_recovery}")
    except Exception as exc:
        logger.debug("recovery_degradation: android recovery router failed: %s", exc)
        trace.append(f"android_recovery_failed:{exc}")

    # Runtime restart recovery
    try:
        from core.runtime_restart_recovery import get_recovery_surface
        recovery_surface = get_recovery_surface()
        restart_state = recovery_surface.get_restart_state() if hasattr(recovery_surface, "get_restart_state") else {}
        if restart_state:
            evidence["restart_recovery_state"] = dict(restart_state)
            is_validated = bool(restart_state.get("revalidated", False))
            if not is_validated:
                evidence["restart_recovery_note"] = (
                    "Restored state is present but has not been revalidated — "
                    "it must not be treated as live canonical truth until revalidation passes."
                )
            trace.append(f"restart_recovery: revalidated={is_validated}")
    except Exception as exc:
        logger.debug("recovery_degradation: runtime restart recovery failed: %s", exc)
        trace.append(f"runtime_restart_recovery_failed:{exc}")

    # Build summary state
    blocked_dims = evidence.get("blocked_dimensions", [])
    degraded_dims = evidence.get("degraded_dimensions", [])
    readiness = evidence.get("readiness_verdict", "unknown")

    if blocked_dims:
        state = f"blocked_dimensions:{','.join(blocked_dims)}"
        explanation = (
            f"The system has blocked readiness dimension(s): {blocked_dims}. "
            f"These conditions prevent normal task execution. "
            f"Degraded dimensions: {degraded_dims}."
        )
    elif degraded_dims:
        state = f"degraded_dimensions:{','.join(degraded_dims)}"
        explanation = (
            f"The system has degraded readiness dimension(s): {degraded_dims}. "
            f"Task execution may proceed with reduced reliability."
        )
    elif readiness in ("READY", "operable") or (not blocked_dims and not degraded_dims and is_canonical):
        state = "no_active_degradation"
        explanation = (
            "No active blocking or degraded readiness dimensions detected. "
            "Recovery surfaces report nominal state."
        )
    else:
        state = "recovery_degradation_state_unavailable"
        explanation = (
            "Recovery and degradation signals could not be fully queried. "
            "System state is partially known."
        )

    return NarrativeDimension(
        dimension=DIM_RECOVERY_DEGRADATION_BLOCKAGE,
        state=state,
        source=(
            "core.runtime_readiness_matrix + core.delegated_flow_recovery_coordinator"
            " + core.android_continuity_recovery_state_router + core.runtime_restart_recovery"
        ),
        is_canonical_truth=is_canonical,
        explanation=explanation,
        evidence_basis=evidence,
        traceability=trace,
        source_authority="RUNTIME_READINESS_MATRIX_AUTHORITY",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_DIMENSION_BUILDERS = {
    DIM_OVERALL_RUNTIME_STATE: _build_overall_runtime_state,
    DIM_OPERATING_STRUCTURE: _build_operating_structure,
    DIM_TASK_EXECUTION_STATE: _build_task_execution_state,
    DIM_DEVICE_DISPATCH_SUPPORT_STATE: _build_device_dispatch_support_state,
    DIM_AUTONOMY_PARTICIPATION_STATE: _build_autonomy_participation_state,
    DIM_TOPOLOGY_ALLOCATION_RELATIONS: _build_topology_allocation_relations,
    DIM_RECOVERY_DEGRADATION_BLOCKAGE: _build_recovery_degradation_blockage,
}


def build_system_state_narrative() -> SystemStateNarrative:
    """Build and return the current :class:`SystemStateNarrative`.

    Queries each of the 7 dimension builders independently so that a failure
    in one dimension never prevents others from being populated.

    Returns
    -------
    SystemStateNarrative
        The fully assembled (or gracefully degraded) narrative.
    """
    narrative = SystemStateNarrative()
    unsourced: List[str] = []

    for dim_name, builder in _DIMENSION_BUILDERS.items():
        try:
            dim = builder()
            narrative.dimensions[dim_name] = dim
            if not dim.is_canonical_truth:
                unsourced.append(dim_name)
        except Exception as exc:
            logger.debug("build_system_state_narrative: dimension '%s' failed: %s", dim_name, exc)
            unsourced.append(dim_name)
            narrative.dimensions[dim_name] = NarrativeDimension(
                dimension=dim_name,
                state="error",
                source="unavailable",
                is_canonical_truth=False,
                explanation=f"Dimension builder failed: {exc}",
                evidence_basis={"error": str(exc)},
                traceability=[f"builder_exception:{exc}"],
            )

    narrative.unsourced_dimensions = unsourced
    narrative.is_fully_sourced = len(unsourced) == 0

    # Derive overall operability from dimension 1
    overall_dim = narrative.dimensions.get(DIM_OVERALL_RUNTIME_STATE)
    if overall_dim:
        state_val = overall_dim.state.lower()
        if state_val.startswith("operable"):
            narrative.overall_operability = "operable"
        elif state_val.startswith("blocked"):
            narrative.overall_operability = "blocked"
        elif state_val.startswith("degraded"):
            narrative.overall_operability = "degraded"
        else:
            narrative.overall_operability = state_val

    # Build consolidated explanation
    parts: List[str] = []
    if overall_dim:
        parts.append(overall_dim.explanation)
    recovery_dim = narrative.dimensions.get(DIM_RECOVERY_DEGRADATION_BLOCKAGE)
    if recovery_dim and recovery_dim.state not in ("no_active_degradation", "unknown", "error", "unavailable"):
        parts.append(recovery_dim.explanation)
    dispatch_dim = narrative.dimensions.get(DIM_DEVICE_DISPATCH_SUPPORT_STATE)
    if dispatch_dim and "none_ready" in dispatch_dim.state:
        parts.append(dispatch_dim.explanation)
    narrative.overall_explanation = " | ".join(parts) if parts else "System state narrative compiled."

    return narrative
