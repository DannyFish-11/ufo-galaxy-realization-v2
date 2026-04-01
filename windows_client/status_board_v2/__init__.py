"""
windows_client/status_board_v2/__init__.py
==========================================
Status Board V2 — public surface.

This package provides a desktop status board that consumes the
:class:`~core.projection.RuntimeProjection` produced by the server and
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

PR-15 upgrades the board to the canonical desktop control surface:

- Config control surface (PR-15)                      → ConfigControlSurface
- Control authority sentinel (PR-15)                  → STATUS_BOARD_CONFIG_CONTROL_AUTHORITY
- Allowed control operations (PR-15)                  → ControlOperation
- Control feedback dataclass (PR-15)                  → ControlApplyResult
- Full pipeline regression tests (PR-15)              → tests/test_pr15_e2e_hardening.py
- Control surface tests (PR-15)                       → tests/test_pr15_status_board_config_control.py
- Architecture reference doc (PR-15)                  → docs/DESKTOP_PIPELINE_ARCHITECTURE.md
- All PR-9 through PR-14 exports verified present
  and re-exportable from this package __all__ (PR-15)

CONTROL SURFACE — PR-15
-----------------------
As of PR-15 this package includes a bounded configuration entry path:

    ConfigControlSurface.apply_toggle(provider, enabled)
    ConfigControlSurface.apply_routing_policy(mode)

All writes go through ``core.config_service.ConfigService`` (canonical
authority) and are persisted to ``runtime/config.json``.  Runtime hot-reload
is triggered via ``core.config_hot_reload.HotReloadConfigManager`` where the
manager is already initialised; otherwise the change takes effect on the next
process startup.  Every apply action returns an explicit ``ControlApplyResult``
feedback object.

Accepted operations remain intentionally narrow — provider enable/disable
toggles and routing policy selection only.

DESIGN INVARIANTS
-----------------
This package NEVER:
- Sends chat input or task commands  (read-only with respect to command execution)
- Bypasses the canonical configuration authority
- Leaks secret values into feedback or log output
- Accepts freeform configuration schema changes

All task execution remains in::

    windows_aip_client.py → WindowsExecutionArbiter.route_command()
"""

from .app import main, run, StatusBoardV2App
from .projection_reader import ProjectionReader
from .config_control import (
    ConfigControlSurface,
    STATUS_BOARD_CONFIG_CONTROL_AUTHORITY,
    ControlOperation,
    ControlApplyResult,
)
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
    # PR-15: canonical configuration control surface
    "ConfigControlSurface",
    "STATUS_BOARD_CONFIG_CONTROL_AUTHORITY",
    "ControlOperation",
    "ControlApplyResult",
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
