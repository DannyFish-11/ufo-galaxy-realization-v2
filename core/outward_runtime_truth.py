#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/outward_runtime_truth.py
==============================
PR-531: Outward Runtime Truth — Unify Outward Runtime Truth and Eliminate
Multi-Source Ambiguity.

This module is the **outward runtime truth governance layer** for the Galaxy
canonical runtime architecture.  It provides a single compilation point for
all downstream-facing runtime state, ensuring that projection/status/operator
surfaces are driven primarily by canonical runtime truth rather than stitched
legacy or fallback views.

Problem addressed
-----------------
After PRs #506–#530 the internal canonical pipeline is well-governed.
However, outward-facing surfaces (status endpoints, desktop projections,
operator dashboards) may still reflect *multiple partial truths* assembled
from different sources rather than a single canonical runtime truth.  Downstream
consumers (desktop UI, operator CLI, monitoring integrations) therefore need to
infer or stitch state from multiple sources.

This module establishes:

1. **A single outward truth compilation point** — :func:`compile_outward_truth`
   gathers all canonical runtime source snapshots into one
   :class:`OutwardRuntimeTruthSnapshot` that outward surfaces must prefer.

2. **Secondary / fallback signal classification** — legacy and compat sources
   are explicitly classified as secondary so they cannot accidentally become
   primary truth for downstream consumers.

3. **Drift prevention sentinels** — machine-checkable sentinels document the
   governance invariants so tests can verify compliance.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  OUTWARD SURFACES — projection, status, operator, desktop        │
    │  /api/v1/projection/runtime-truth  ·  desktop_status_board       │
    │  operator snapshot  ·  desktop topology                          │
    └────────────────────────────┬─────────────────────────────────────┘
                                 │  READS COMPILED OUTWARD TRUTH ONLY
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  OUTWARD RUNTIME TRUTH LAYER  (this module, Layer 15)           │
    │                                                                  │
    │  compile_outward_truth() — single compilation function          │
    │  OutwardRuntimeTruthSnapshot — stable output dataclass          │
    │  TruthSignalClass.PRIMARY / SECONDARY / LEGACY_COMPAT           │
    │                                                                  │
    │  Drift-prevention sentinels:                                    │
    │    NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY                  │
    │    NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY                          │
    │    OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY            │
    └────────────────────────────┬─────────────────────────────────────┘
                                 │  READS CANONICAL LAYERS
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  CANONICAL RUNTIME LAYERS (Layers 6–14)                         │
    │  RuntimeTruthCompiler · AuthorityConflictElimination            │
    │  OperatorSurface · ProjectionSurfaceBridge                      │
    │  TaskGraphRuntime · NetworkTopologyRuntime                      │
    │  CapabilityAssimilation · ReplayFoundation                      │
    └──────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1. **Single compilation point.**  All outward surfaces MUST source from
   :func:`compile_outward_truth` rather than independently assembling
   subsystem state.
   Governed by :data:`OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY`.

2. **Secondary signals are explicitly classified.**  Legacy / fallback /
   compat sources are classified as :attr:`TruthSignalClass.SECONDARY` or
   :attr:`TruthSignalClass.LEGACY_COMPAT` so they can never silently become
   primary truth.
   Governed by :data:`NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY`.

3. **No parallel outward assembly.**  Outward surfaces must not maintain
   independent state stores that produce equivalent payloads from different
   sources.
   Governed by :data:`NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY`.

Public API
----------
Authority sentinels::

    OUTWARD_RUNTIME_TRUTH_AUTHORITY
    OUTWARD_RUNTIME_TRUTH_LAYER_POSITION

Policy sentinels (drift prevention)::

    NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY
    NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY
    OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY

Enums::

    TruthSignalClass

Dataclasses::

    TruthSourceRecord
    OutwardRuntimeTruthSnapshot

Runtime class::

    OutwardRuntimeTruthRuntime
    get_outward_runtime_truth_runtime()
    reset_outward_runtime_truth_runtime()

Helpers::

    compile_outward_truth() -> OutwardRuntimeTruthSnapshot
    classify_signal(source_name, is_canonical) -> TruthSignalClass
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.OutwardRuntimeTruth")

# ===========================================================================
# Authority sentinels
# ===========================================================================

#: Identifies this module as the outward runtime truth governance layer.
OUTWARD_RUNTIME_TRUTH_AUTHORITY: str = (
    "OUTWARD_RUNTIME_TRUTH::PR531_OUTWARD_TRUTH_AUTHORITY_V1: "
    "core/outward_runtime_truth.py is the canonical governance layer for all "
    "downstream-facing runtime state.  Layer 15.  "
    "All outward surfaces MUST read from compile_outward_truth()."
)

#: Numeric layer position in the Galaxy runtime stack.
OUTWARD_RUNTIME_TRUTH_LAYER_POSITION: int = 15

# ---------------------------------------------------------------------------
# Drift-prevention policy sentinels
# ---------------------------------------------------------------------------

NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY: str = (
    "NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_V1: "
    "Legacy, fallback, and compat sources are explicitly classified as "
    "TruthSignalClass.SECONDARY or LEGACY_COMPAT and MUST NOT be surfaced as "
    "primary runtime truth to downstream consumers.  Violating this policy "
    "causes downstream consumers to receive inconsistent state."
)

NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY: str = (
    "NO_PARALLEL_OUTWARD_ASSEMBLY_V1: "
    "Outward surfaces (status endpoints, desktop projection, operator dashboard) "
    "MUST NOT maintain independent state stores that produce equivalent payloads "
    "from different source combinations.  All outward assembly must flow through "
    "compile_outward_truth()."
)

OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY: str = (
    "OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_V1: "
    "All outward-facing surfaces MUST prefer OutwardRuntimeTruthSnapshot as "
    "their primary data source.  Legacy/fallback paths may remain as "
    "compatibility scaffolding but must be explicitly marked secondary."
)

# ===========================================================================
# Enums
# ===========================================================================


class TruthSignalClass(str, Enum):
    """Classification of a runtime truth signal's authority tier."""

    PRIMARY = "primary"
    """Signal is sourced from a canonical runtime layer and is authoritative."""

    SECONDARY = "secondary"
    """Signal is sourced from a fallback/partial path; must not override primary."""

    LEGACY_COMPAT = "legacy_compat"
    """Signal is sourced from a legacy/compat layer retained for backward
    compatibility; must not be presented as current truth."""

    UNAVAILABLE = "unavailable"
    """Signal source was queried but returned no data; not a primary/secondary signal."""


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class TruthSourceRecord:
    """Record describing the contribution of one canonical source to a snapshot."""

    source_name: str
    """Identifying name for this truth source (e.g. ``'RuntimeTruthCompiler'``)."""

    signal_class: TruthSignalClass
    """Whether this source is PRIMARY, SECONDARY, LEGACY_COMPAT, or UNAVAILABLE."""

    data: Optional[Dict[str, Any]] = None
    """Data returned by this source, or ``None`` if unavailable."""

    error: Optional[str] = None
    """Error message if this source failed to respond."""

    latency_ms: float = 0.0
    """Round-trip latency in milliseconds to query this source."""


@dataclass
class OutwardRuntimeTruthSnapshot:
    """Compiled snapshot of all outward-facing runtime state.

    This is the **single stable object** that outward surfaces (status
    endpoints, desktop projection, operator dashboard) should source from.
    It collects signals from all canonical runtime layers, classifies them
    by authority tier, and exposes the compiled primary truth together with
    explicit metadata about secondary/legacy signals.
    """

    snapshot_id: str
    """Unique identifier for this snapshot (UUIDv4)."""

    compiled_at: float
    """Unix epoch timestamp when this snapshot was compiled."""

    authority: str = OUTWARD_RUNTIME_TRUTH_AUTHORITY

    # Primary signals (from canonical layers)
    runtime_truth_compiler: Optional[Dict[str, Any]] = None
    """RuntimeTruthCompiler snapshot — tri-state lifecycle, topology, system."""

    operator_snapshot: Optional[Dict[str, Any]] = None
    """OperatorSurface snapshot — task/route/executor/lineage inspection."""

    projection_bridge_augmentation: Optional[Dict[str, Any]] = None
    """ProjectionSurfaceBridge augmentation fields."""

    authority_conflict_summary: Optional[Dict[str, Any]] = None
    """AuthorityConflictElimination snapshot — boundary compliance."""

    durable_mesh_session_facet: Optional[Dict[str, Any]] = None
    """Durable mesh session facet — recoverable session count, session IDs, and
    lifecycle summary surfaced from :class:`~core.mesh.mesh_session_persistence.MeshSessionPersistenceStore`.

    This facet is the outward truth integration point for the durable mesh
    session runtime foundation (PR-1).  Downstream projection surfaces and
    recovery monitors should prefer this field over independently querying
    the persistence store.
    """

    # Aggregated source records
    source_records: List[TruthSourceRecord] = field(default_factory=list)

    # Computed summary
    primary_source_count: int = 0
    secondary_source_count: int = 0
    legacy_compat_source_count: int = 0
    unavailable_source_count: int = 0

    surfacing_complete: bool = False
    """True when all canonical primary sources responded without error."""

    surfacing_notes: List[str] = field(default_factory=list)
    """Human-readable notes about degraded/partial sourcing."""

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict suitable for JSON endpoints."""
        return {
            "snapshot_id": self.snapshot_id,
            "compiled_at": self.compiled_at,
            "authority": self.authority,
            "layer_position": OUTWARD_RUNTIME_TRUTH_LAYER_POSITION,
            "surfacing_complete": self.surfacing_complete,
            "primary_source_count": self.primary_source_count,
            "secondary_source_count": self.secondary_source_count,
            "legacy_compat_source_count": self.legacy_compat_source_count,
            "unavailable_source_count": self.unavailable_source_count,
            "surfacing_notes": self.surfacing_notes,
            "runtime_truth_compiler": self.runtime_truth_compiler,
            "operator_snapshot": self.operator_snapshot,
            "projection_bridge_augmentation": self.projection_bridge_augmentation,
            "authority_conflict_summary": self.authority_conflict_summary,
            "durable_mesh_session_facet": self.durable_mesh_session_facet,
            "sources": [
                {
                    "source_name": r.source_name,
                    "signal_class": r.signal_class.value,
                    "latency_ms": round(r.latency_ms, 2),
                    "error": r.error,
                    "has_data": r.data is not None,
                }
                for r in self.source_records
            ],
        }


# ===========================================================================
# Runtime class
# ===========================================================================

_RING_SIZE = 64


class OutwardRuntimeTruthRuntime:
    """Singleton runtime that maintains a ring buffer of compiled snapshots.

    Snapshots are compiled on demand by :func:`compile_outward_truth` and
    stored here for observability / replay purposes.
    """

    _instance: Optional["OutwardRuntimeTruthRuntime"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._ring: Deque[OutwardRuntimeTruthSnapshot] = deque(maxlen=_RING_SIZE)
        self._compile_count: int = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Singleton helpers
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "OutwardRuntimeTruthRuntime":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — for testing only."""
        with cls._lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def record_snapshot(self, snapshot: OutwardRuntimeTruthSnapshot) -> None:
        """Add *snapshot* to the ring buffer."""
        with self._lock:
            self._ring.append(snapshot)
            self._compile_count += 1

    def latest_snapshot(self) -> Optional[OutwardRuntimeTruthSnapshot]:
        """Return the most recently compiled snapshot, or ``None``."""
        with self._lock:
            return self._ring[-1] if self._ring else None

    def snapshot_list(self) -> List[OutwardRuntimeTruthSnapshot]:
        """Return all buffered snapshots (oldest first)."""
        with self._lock:
            return list(self._ring)

    @property
    def compile_count(self) -> int:
        """Total number of snapshots compiled since this runtime was created."""
        return self._compile_count


# ===========================================================================
# Module-level helpers
# ===========================================================================


def get_outward_runtime_truth_runtime() -> OutwardRuntimeTruthRuntime:
    """Return the process-level singleton :class:`OutwardRuntimeTruthRuntime`."""
    return OutwardRuntimeTruthRuntime.get_instance()


def reset_outward_runtime_truth_runtime() -> None:
    """Reset the singleton — **for testing only**."""
    OutwardRuntimeTruthRuntime.reset()


def classify_signal(source_name: str, is_canonical: bool) -> TruthSignalClass:
    """Classify a runtime truth signal.

    Parameters
    ----------
    source_name:
        Identifier for the signal source (used for logging).
    is_canonical:
        ``True`` if the source is a canonical runtime layer;
        ``False`` if it is a fallback / compat path.

    Returns
    -------
    TruthSignalClass
        :attr:`TruthSignalClass.PRIMARY` for canonical sources,
        :attr:`TruthSignalClass.LEGACY_COMPAT` for fallback/compat sources.
    """
    if is_canonical:
        return TruthSignalClass.PRIMARY
    logger.debug(
        "classify_signal: source '%s' classified as LEGACY_COMPAT", source_name
    )
    return TruthSignalClass.LEGACY_COMPAT


def compile_outward_truth() -> OutwardRuntimeTruthSnapshot:
    """Compile and return the current :class:`OutwardRuntimeTruthSnapshot`.

    This is the **single canonical compilation point** for all outward-facing
    runtime state.  It queries each canonical runtime source in dependency
    order, classifies the resulting signals, assembles the snapshot, and
    records it in the :class:`OutwardRuntimeTruthRuntime` ring buffer.

    All canonical queries are *read-only* and *soft-fail*: if a source is
    unavailable the snapshot is produced with ``surfacing_complete=False``
    and an explanatory note rather than raising.

    Returns
    -------
    OutwardRuntimeTruthSnapshot
        The compiled snapshot.  Downstream surfaces should prefer this object
        over independently sourcing subsystem state.
    """
    t_start = time.monotonic()
    snapshot_id = str(uuid.uuid4())
    records: List[TruthSourceRecord] = []
    notes: List[str] = []

    rtc_data: Optional[Dict[str, Any]] = None
    op_data: Optional[Dict[str, Any]] = None
    bridge_data: Optional[Dict[str, Any]] = None
    ace_data: Optional[Dict[str, Any]] = None

    # ── 1. RuntimeTruthCompiler ──────────────────────────────────────────
    t0 = time.monotonic()
    try:
        from core.projection.runtime_truth_compiler import compile_runtime_truth

        rtc = compile_runtime_truth()
        rtc_data = {
            "compiler_authority": getattr(rtc, "compiler_authority", None),
            "compiled_at": getattr(rtc, "compiled_at", None),
            "continuum": getattr(rtc, "continuum", None),
            "topology": getattr(rtc, "topology", None),
            "oneapi": getattr(rtc, "oneapi", None),
            "system_resource": getattr(rtc, "system_resource", None),
        }
        records.append(TruthSourceRecord(
            source_name="RuntimeTruthCompiler",
            signal_class=TruthSignalClass.PRIMARY,
            data=rtc_data,
            latency_ms=(time.monotonic() - t0) * 1000,
        ))
    except Exception as exc:
        notes.append(f"RuntimeTruthCompiler unavailable: {exc}")
        records.append(TruthSourceRecord(
            source_name="RuntimeTruthCompiler",
            signal_class=TruthSignalClass.UNAVAILABLE,
            error=str(exc),
            latency_ms=(time.monotonic() - t0) * 1000,
        ))

    # ── 2. OperatorSurface ───────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        from core.operator_surface import get_operator_surface

        op = get_operator_surface()
        op_snap = op.operator_snapshot()
        op_data = {
            "authority": getattr(op_snap, "authority", None),
            "active_task_count": getattr(op_snap, "active_task_count", 0),
            "recent_failure_count": getattr(op_snap, "recent_failure_count", 0),
            "reachable_executor_count": getattr(op_snap, "reachable_executor_count", 0),
        }
        records.append(TruthSourceRecord(
            source_name="OperatorSurface",
            signal_class=TruthSignalClass.PRIMARY,
            data=op_data,
            latency_ms=(time.monotonic() - t0) * 1000,
        ))
    except Exception as exc:
        notes.append(f"OperatorSurface unavailable: {exc}")
        records.append(TruthSourceRecord(
            source_name="OperatorSurface",
            signal_class=TruthSignalClass.UNAVAILABLE,
            error=str(exc),
            latency_ms=(time.monotonic() - t0) * 1000,
        ))

    # ── 3. ProjectionSurfaceBridge ───────────────────────────────────────
    t0 = time.monotonic()
    try:
        from core.projection_surface_bridge import get_runtime_augmentation

        aug = get_runtime_augmentation()
        bridge_data = {
            "active_task_count": getattr(aug, "active_task_count", 0),
            "executor_count": getattr(aug, "executor_count", 0),
            "network_reachable_node_count": getattr(
                aug, "network_reachable_node_count", 0
            ),
        }
        records.append(TruthSourceRecord(
            source_name="ProjectionSurfaceBridge",
            signal_class=TruthSignalClass.PRIMARY,
            data=bridge_data,
            latency_ms=(time.monotonic() - t0) * 1000,
        ))
    except Exception as exc:
        notes.append(f"ProjectionSurfaceBridge unavailable: {exc}")
        records.append(TruthSourceRecord(
            source_name="ProjectionSurfaceBridge",
            signal_class=TruthSignalClass.UNAVAILABLE,
            error=str(exc),
            latency_ms=(time.monotonic() - t0) * 1000,
        ))

    # ── 4. AuthorityConflictElimination ──────────────────────────────────
    t0 = time.monotonic()
    try:
        from core.authority_conflict_elimination import build_authority_elimination_snapshot

        ace_snap = build_authority_elimination_snapshot()
        ace_data = {
            "authority": getattr(ace_snap, "authority", None),
            "resolution_count": getattr(ace_snap, "resolution_count", 0),
            "violation_count": getattr(ace_snap, "violation_count", 0),
        }
        records.append(TruthSourceRecord(
            source_name="AuthorityConflictElimination",
            signal_class=TruthSignalClass.PRIMARY,
            data=ace_data,
            latency_ms=(time.monotonic() - t0) * 1000,
        ))
    except Exception as exc:
        notes.append(f"AuthorityConflictElimination unavailable: {exc}")
        records.append(TruthSourceRecord(
            source_name="AuthorityConflictElimination",
            signal_class=TruthSignalClass.UNAVAILABLE,
            error=str(exc),
            latency_ms=(time.monotonic() - t0) * 1000,
        ))

    # ── 5. DurableMeshSessionFacet ───────────────────────────────────────
    # PR-1: Durable mesh session runtime foundation.
    # Surface recoverable session state through the outward truth path so
    # downstream projection and recovery monitors have a single authoritative
    # read point rather than independently querying the persistence store.
    t0 = time.monotonic()
    mesh_session_data: Optional[Dict[str, Any]] = None
    try:
        from core.mesh.mesh_session_persistence import (
            recover_mesh_sessions,
            list_recoverable_sessions,
        )

        recoverable_records = recover_mesh_sessions()
        recoverable_ids = [r.session_id for r in recoverable_records]
        mesh_session_data = {
            "recoverable_session_count": len(recoverable_ids),
            "recoverable_session_ids": recoverable_ids,
            "status_breakdown": {
                r.session_id: r.overall_status for r in recoverable_records
            },
            "authority": (
                "DURABLE_MESH_SESSION_FACET::PR1_OUTWARD_TRUTH_INTEGRATION: "
                "Recoverable session state sourced from "
                "core/mesh/mesh_session_persistence.py."
            ),
        }
        records.append(TruthSourceRecord(
            source_name="DurableMeshSessionFacet",
            signal_class=TruthSignalClass.PRIMARY,
            data=mesh_session_data,
            latency_ms=(time.monotonic() - t0) * 1000,
        ))
    except Exception as exc:
        notes.append(f"DurableMeshSessionFacet unavailable: {exc}")
        records.append(TruthSourceRecord(
            source_name="DurableMeshSessionFacet",
            signal_class=TruthSignalClass.UNAVAILABLE,
            error=str(exc),
            latency_ms=(time.monotonic() - t0) * 1000,
        ))

    # ── Aggregate counts ─────────────────────────────────────────────────
    primary = sum(1 for r in records if r.signal_class == TruthSignalClass.PRIMARY)
    secondary = sum(1 for r in records if r.signal_class == TruthSignalClass.SECONDARY)
    legacy = sum(1 for r in records if r.signal_class == TruthSignalClass.LEGACY_COMPAT)
    unavailable = sum(1 for r in records if r.signal_class == TruthSignalClass.UNAVAILABLE)

    snapshot = OutwardRuntimeTruthSnapshot(
        snapshot_id=snapshot_id,
        compiled_at=time.time(),
        runtime_truth_compiler=rtc_data,
        operator_snapshot=op_data,
        projection_bridge_augmentation=bridge_data,
        authority_conflict_summary=ace_data,
        durable_mesh_session_facet=mesh_session_data,
        source_records=records,
        primary_source_count=primary,
        secondary_source_count=secondary,
        legacy_compat_source_count=legacy,
        unavailable_source_count=unavailable,
        surfacing_complete=(unavailable == 0),
        surfacing_notes=notes,
    )

    get_outward_runtime_truth_runtime().record_snapshot(snapshot)

    total_ms = (time.monotonic() - t_start) * 1000
    logger.debug(
        "compile_outward_truth: compiled in %.1f ms — %d primary, %d unavailable",
        total_ms,
        primary,
        unavailable,
    )
    return snapshot
