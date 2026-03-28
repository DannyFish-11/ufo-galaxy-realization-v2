"""
windows_client/status_board_v2/__init__.py
==========================================
Status Board V2 — public surface.

This package provides a **read-only** desktop status board that consumes
the :class:`~core.projection.RuntimeProjection` produced by the server and
visualises:

- Tri-state phase (silent / liminal / manifest)       → PhaseSurface
- Runtime domain (local / cross_device / transition)  → DomainSurface
- Model topology weights (top-N by weight)            → TopologySurface
- Active devices and execution stage                  → DeviceSurface
- Presence/coherence/tendency metrics                 → MetricsSurface
- Liminal spatial projection dimensions               → LiminalSurface
- Manifest stage (显现台) execution surface           → ManifestSurface
- Return intelligence summary                         → ReturnSurface

PR-10 adds the first usable adapter-driven status board surface:

- Desktop status board (adapter-driven, PR-10)        → AdapterSurface

PR-11 adds the topology / constellation layout foundation:

- Topology layout builder (PR-11)                     → build_constellation_layout
- Topology layout structures (PR-11)                  → TopologyConstellationLayout,
                                                         TopologyLayoutLayer,
                                                         TopologyLayoutNode,
                                                         TopologyLayoutRelation
- Topology enumerations (PR-11)                       → TopologyNodeKind,
                                                         TopologyRelationKind,
                                                         TopologyLayerKind

PR-12 adds the topology rendering and visual semantics polish:

- Topology constellation renderer (PR-12)             → TopologyRenderer
- Renderer authority sentinel (PR-12)                 → TOPOLOGY_RENDERER_AUTHORITY

PR-13 adds the diagnostics and inspection interaction layer:

- Topology inspector (PR-13)                          → TopologyInspector
- Inspector authority sentinel (PR-13)                → TOPOLOGY_INSPECTOR_AUTHORITY
- Node inspection detail (PR-13)                      → NodeInspectionDetail
- Relation inspection detail (PR-13)                  → RelationInspectionDetail
- Readiness inspection detail (PR-13)                 → ReadinessInspectionDetail
- Routing inspection detail (PR-13)                   → RoutingInspectionDetail
- OneAPI inspection detail (PR-13)                    → OneAPIInspectionDetail
- Inspection report (PR-13)                           → InspectionReport

PR-14 adds the observability and history layer:

- Topology history recorder (PR-14)                   → TopologyHistoryRecorder
- History authority sentinel (PR-14)                  → TOPOLOGY_HISTORY_AUTHORITY
- Change kind enumeration (PR-14)                     → TopologyChangeKind
- Readiness transition record (PR-14)                 → ReadinessTransitionRecord
- Authority change record (PR-14)                     → AuthorityChangeRecord
- Routing change record (PR-14)                       → RoutingChangeRecord
- OneAPI historical summary (PR-14)                   → OneAPIHistorySummary
- History entry (PR-14)                               → TopologyHistoryEntry
- Point-in-time snapshot (PR-14)                      → TopologySnapshot
- Bounded history buffer (PR-14)                      → TopologyHistoryBuffer

READ-ONLY GUARANTEE
-------------------
This package NEVER:
- Accepts chat input
- Sends commands to the system
- Triggers any actions

All command execution remains in::

    windows_aip_client.py → WindowsExecutionArbiter.route_command()
"""

from .app import main, run, StatusBoardV2App
from .projection_reader import ProjectionReader
from .liminal_surface import LiminalSurface
from .manifest_surface import ManifestSurface
from .return_surface import ReturnSurface
from .adapter_surface import AdapterSurface
from .topology_layout import (
    build_constellation_layout,
    TopologyConstellationLayout,
    TopologyLayoutLayer,
    TopologyLayoutNode,
    TopologyLayoutRelation,
    TopologyNodeKind,
    TopologyRelationKind,
    TopologyLayerKind,
    TOPOLOGY_LAYOUT_AUTHORITY,
)
from .topology_renderer import (
    TopologyRenderer,
    TOPOLOGY_RENDERER_AUTHORITY,
)
from .topology_inspector import (
    TopologyInspector,
    TOPOLOGY_INSPECTOR_AUTHORITY,
    NodeInspectionDetail,
    RelationInspectionDetail,
    ReadinessInspectionDetail,
    RoutingInspectionDetail,
    OneAPIInspectionDetail,
    InspectionReport,
)
from .topology_history import (
    TopologyHistoryRecorder,
    TOPOLOGY_HISTORY_AUTHORITY,
    TopologyChangeKind,
    ReadinessTransitionRecord,
    AuthorityChangeRecord,
    RoutingChangeRecord,
    OneAPIHistorySummary,
    TopologyHistoryEntry,
    TopologySnapshot,
    TopologyHistoryBuffer,
)

__all__ = [
    "main",
    "run",
    "StatusBoardV2App",
    "ProjectionReader",
    "LiminalSurface",
    "ManifestSurface",
    "ReturnSurface",
    # PR-10: first usable adapter-driven status board surface
    "AdapterSurface",
    # PR-11: topology / constellation layout foundation
    "build_constellation_layout",
    "TopologyConstellationLayout",
    "TopologyLayoutLayer",
    "TopologyLayoutNode",
    "TopologyLayoutRelation",
    "TopologyNodeKind",
    "TopologyRelationKind",
    "TopologyLayerKind",
    "TOPOLOGY_LAYOUT_AUTHORITY",
    # PR-12: topology rendering and visual semantics polish
    "TopologyRenderer",
    "TOPOLOGY_RENDERER_AUTHORITY",
    # PR-13: diagnostics and inspection interaction layer
    "TopologyInspector",
    "TOPOLOGY_INSPECTOR_AUTHORITY",
    "NodeInspectionDetail",
    "RelationInspectionDetail",
    "ReadinessInspectionDetail",
    "RoutingInspectionDetail",
    "OneAPIInspectionDetail",
    "InspectionReport",
    # PR-14: observability and history layer
    "TopologyHistoryRecorder",
    "TOPOLOGY_HISTORY_AUTHORITY",
    "TopologyChangeKind",
    "ReadinessTransitionRecord",
    "AuthorityChangeRecord",
    "RoutingChangeRecord",
    "OneAPIHistorySummary",
    "TopologyHistoryEntry",
    "TopologySnapshot",
    "TopologyHistoryBuffer",
]
