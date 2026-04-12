#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.repo_layout_registry
==========================

PR-8 (repo-layout) — Repository Layout Organisation.

**Architectural intent**
------------------------
This module is the authoritative registry for repository directory
classification across the Galaxy codebase.  It answers four questions:

1. **What zone does a directory belong to?**  Active runtime, active desktop
   status surface, legacy surface, or infrastructure/transitional?

2. **Is a given directory on the active runtime path?**  Only
   ``ACTIVE_RUNTIME`` and ``ACTIVE_DESKTOP_STATUS`` directories are.

3. **Is a given directory a legacy or transitional artifact?**  Legacy
   directories must not be extended with new runtime logic.

4. **Where should new code go?**  Each legacy/transitional entry carries a
   ``canonical_replacement`` pointer to the active equivalent.

Layout zones::

    ACTIVE_RUNTIME
    ├── core/              — canonical runtime, authority model, multimodal engine
    ├── launcher/          — authoritative startup modules
    ├── nodes/             — active node system (130+ canonical nodes)
    ├── contracts/         — canonical data contracts
    ├── galaxy_gateway/    — active gateway / cross-device routing substrate
    ├── desktop_projection/— liminal-space / manifest-stage tri-state engine
    └── worker/            — background task worker pool

    ACTIVE_DESKTOP_STATUS
    └── windows_client/status_board_v2/ — canonical operator-facing desktop
                                          runtime surface (projection-driven;
                                          consumes GET /api/v1/projection/runtime;
                                          bounded exposed authority)

    ACTIVE_DESKTOP_SHELL
    └── windows_client/autonomy/ — Windows automation / input simulation layer

    LEGACY_SURFACE
    └── dashboard/         — legacy WebUI management panel (LEGACY_UI, PR-8)

    LEGACY_SHELL
    └── windows_client/    — host-specific legacy shell (PR-3 retired,
                             active sub-dirs preserved above)

    TRANSITIONAL
    └── enhancements/      — enhancement overlays; clients/ hard-disabled (PR-3)

    INFRASTRUCTURE
    ├── docs/              — documentation
    ├── tests/             — test suite
    ├── scripts/           — operational scripts
    ├── deployment/        — Kubernetes / nginx / Docker assets
    ├── config/            — runtime configuration files
    ├── data/              — persistent data directory
    └── static/            — static web assets

Authority model::

    ┌──────────────────────────────────────────────────────────────┐
    │  CANONICAL OUTWARD STATUS TRUTH                              │
    │  ─────────────────────────────                               │
    │  windows_client/status_board_v2/   (ACTIVE_DESKTOP_STATUS)  │
    │    consumes  ──►  GET /api/v1/projection/runtime             │
    │    contract  ──►  contracts.desktop_status_projection        │
    └──────────────────────────────────────────────────────────────┘
              ▲ projection-derived downstream runtime surface
    ┌──────────────────────────────────────────────────────────────┐
    │  CANONICAL RUNTIME SOURCE OF TRUTH                           │
    │  ─────────────────────────────────                           │
    │  core/   ──►   DesktopPresenceRuntime (tri-state lifecycle)  │
    │  core/   ──►   OpenClawd (AI authority)                      │
    │  core/   ──►   PerceptionSourceRegistry                      │
    └──────────────────────────────────────────────────────────────┘

Usage::

    from core.repo_layout_registry import (
        DirectoryRole,
        LayoutZone,
        RepoLayoutEntry,
        RepoLayoutRegistry,
        is_active_runtime_directory,
        is_legacy_directory,
        get_layout_zone,
        build_repo_layout_summary,
        get_repo_layout_registry,
    )

    assert is_active_runtime_directory("core")
    assert is_active_runtime_directory("launcher")
    assert is_legacy_directory("dashboard")
    summary = build_repo_layout_summary()
    assert summary["active_count"] >= 5
"""

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.RepoLayoutRegistry")

__all__ = [
    "DirectoryRole",
    "LayoutZone",
    "RepoLayoutEntry",
    "RepoLayoutRegistry",
    "REPO_LAYOUT_REGISTRY",
    "is_active_runtime_directory",
    "is_legacy_directory",
    "is_active_desktop_status_directory",
    "get_layout_zone",
    "get_repo_layout_entry",
    "build_repo_layout_summary",
    "get_repo_layout_registry",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DirectoryRole(str, Enum):
    """Classification role for a repository directory.

    ``ACTIVE_RUNTIME``
        Core active runtime code, authority model, execution engine.
        New functionality goes here.

    ``ACTIVE_DESKTOP_STATUS``
        Active, canonical desktop status surface.
        Consumes projection output; operator-facing with bounded exposed
        authority relative to canonical runtime truth.

    ``ACTIVE_DESKTOP_SHELL``
        Active Windows automation / input simulation layer.
        Not the authority for system state; drives OS-level interaction.

    ``LEGACY_SURFACE``
        Retained for compatibility only; must not define system structure
        or maintain a parallel source of truth.  Marked LEGACY.

    ``LEGACY_SHELL``
        Host-specific legacy shell; retired from the active runtime surface.
        Active sub-directories (status_board_v2/, autonomy/) are preserved
        under their own ACTIVE_* roles.

    ``TRANSITIONAL``
        Enhancement overlays or adapter directories that are being phased out.
        Some sub-paths may be hard-disabled (e.g. enhancements/clients/).

    ``INFRASTRUCTURE``
        Operational, documentation, testing, or deployment support directories.
        Not part of the active runtime code path.
    """

    ACTIVE_RUNTIME = "active_runtime"
    ACTIVE_DESKTOP_STATUS = "active_desktop_status"
    ACTIVE_DESKTOP_SHELL = "active_desktop_shell"
    LEGACY_SURFACE = "legacy_surface"
    LEGACY_SHELL = "legacy_shell"
    TRANSITIONAL = "transitional"
    INFRASTRUCTURE = "infrastructure"


class LayoutZone(str, Enum):
    """High-level zone grouping for repository directories.

    ``CORE_RUNTIME``
        Active authoritative runtime code (core/, launcher/, nodes/, etc.).

    ``DESKTOP_STATUS``
        Active desktop status / tri-state surface directories.

    ``LEGACY``
        Retired or demoted directories still present for compatibility.

    ``INFRASTRUCTURE``
        Docs, tests, scripts, deployment, config, data.
    """

    CORE_RUNTIME = "core_runtime"
    DESKTOP_STATUS = "desktop_status"
    LEGACY = "legacy"
    INFRASTRUCTURE = "infrastructure"


# ---------------------------------------------------------------------------
# RepoLayoutEntry dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RepoLayoutEntry:
    """Metadata record for a single repository directory.

    Attributes
    ----------
    path:
        Relative path from the repository root (e.g. ``"core"``).
    role:
        :class:`DirectoryRole` classification for this directory.
    zone:
        :class:`LayoutZone` high-level zone grouping.
    description:
        Short human-readable description of the directory's purpose.
    canonical_replacement:
        For legacy/transitional entries: the canonical active replacement path.
        ``None`` for active or infrastructure entries.
    pr_classified:
        PR identifier that established this classification.
    notes:
        Extended notes (migration guidance, scope limits, etc.).
    """

    path: str
    role: DirectoryRole
    zone: LayoutZone
    description: str
    canonical_replacement: Optional[str] = None
    pr_classified: str = "PR-8-layout"
    notes: str = ""

    def is_active(self) -> bool:
        """Return ``True`` if this directory is on the active runtime path."""
        return self.role in (
            DirectoryRole.ACTIVE_RUNTIME,
            DirectoryRole.ACTIVE_DESKTOP_STATUS,
            DirectoryRole.ACTIVE_DESKTOP_SHELL,
        )

    def is_legacy(self) -> bool:
        """Return ``True`` if this directory is a legacy or transitional asset."""
        return self.role in (
            DirectoryRole.LEGACY_SURFACE,
            DirectoryRole.LEGACY_SHELL,
            DirectoryRole.TRANSITIONAL,
        )

    def to_dict(self) -> Dict:
        """Return a JSON-serialisable dict representation."""
        return {
            "path": self.path,
            "role": self.role.value,
            "zone": self.zone.value,
            "description": self.description,
            "canonical_replacement": self.canonical_replacement,
            "pr_classified": self.pr_classified,
            "notes": self.notes,
            "is_active": self.is_active(),
            "is_legacy": self.is_legacy(),
        }


# ---------------------------------------------------------------------------
# RepoLayoutRegistry
# ---------------------------------------------------------------------------


class RepoLayoutRegistry:
    """Singleton registry of repository directory layout classifications.

    Maintains a mapping of relative directory paths to :class:`RepoLayoutEntry`
    records.  Provides query helpers and summary builders.
    """

    def __init__(self) -> None:
        self._registry: Dict[str, RepoLayoutEntry] = {}

    def _register(self, entry: RepoLayoutEntry) -> None:
        self._registry[entry.path] = entry

    def get(self, path: str) -> Optional[RepoLayoutEntry]:
        """Return the :class:`RepoLayoutEntry` for *path*, or ``None``."""
        return self._registry.get(path)

    def get_role(self, path: str) -> Optional[DirectoryRole]:
        """Return the :class:`DirectoryRole` for *path*, or ``None``."""
        entry = self._registry.get(path)
        return entry.role if entry is not None else None

    def get_zone(self, path: str) -> Optional[LayoutZone]:
        """Return the :class:`LayoutZone` for *path*, or ``None``."""
        entry = self._registry.get(path)
        return entry.zone if entry is not None else None

    def is_active(self, path: str) -> bool:
        """Return ``True`` if *path* is classified as an active runtime directory."""
        entry = self._registry.get(path)
        return entry is not None and entry.is_active()

    def is_legacy(self, path: str) -> bool:
        """Return ``True`` if *path* is classified as a legacy or transitional directory."""
        entry = self._registry.get(path)
        return entry is not None and entry.is_legacy()

    def active_entries(self) -> List[RepoLayoutEntry]:
        """Return all active (runtime + desktop status) entries."""
        return [e for e in self._registry.values() if e.is_active()]

    def legacy_entries(self) -> List[RepoLayoutEntry]:
        """Return all legacy/transitional entries."""
        return [e for e in self._registry.values() if e.is_legacy()]

    def entries_by_zone(self, zone: LayoutZone) -> List[RepoLayoutEntry]:
        """Return all entries belonging to *zone*."""
        return [e for e in self._registry.values() if e.zone == zone]

    def summary(self) -> Dict:
        """Return a structured summary of the layout registry.

        Example::

            {
              "total_directories": 18,
              "active_count": 9,
              "legacy_count": 4,
              "infrastructure_count": 5,
              "core_runtime_count": 7,
              "desktop_status_count": 2,
              "directories": [...]
            }
        """
        all_entries = list(self._registry.values())
        active = [e for e in all_entries if e.is_active()]
        legacy = [e for e in all_entries if e.is_legacy()]
        infra = [e for e in all_entries if e.role == DirectoryRole.INFRASTRUCTURE]
        core_rt = [e for e in all_entries if e.zone == LayoutZone.CORE_RUNTIME]
        desktop_status = [e for e in all_entries if e.zone == LayoutZone.DESKTOP_STATUS]
        return {
            "total_directories": len(all_entries),
            "active_count": len(active),
            "legacy_count": len(legacy),
            "infrastructure_count": len(infra),
            "core_runtime_count": len(core_rt),
            "desktop_status_count": len(desktop_status),
            "directories": [e.to_dict() for e in all_entries],
        }


# ---------------------------------------------------------------------------
# Registry population
# ---------------------------------------------------------------------------

_REGISTRY = RepoLayoutRegistry()


# ── Active Runtime ─────────────────────────────────────────────────────────

_REGISTRY._register(
    RepoLayoutEntry(
        path="core",
        role=DirectoryRole.ACTIVE_RUNTIME,
        zone=LayoutZone.CORE_RUNTIME,
        description=(
            "Canonical runtime authority — OpenClawd AI authority, "
            "DesktopPresenceRuntime tri-state lifecycle, perception pipeline, "
            "multi-LLM router, cross-device chain, and all canonical singletons."
        ),
        pr_classified="PR-8-layout",
        notes=(
            "core/ is the single authoritative source of truth for runtime "
            "state, execution decisions, and architecture governance.  "
            "All new canonical functionality goes here."
        ),
    )
)

_REGISTRY._register(
    RepoLayoutEntry(
        path="launcher",
        role=DirectoryRole.ACTIVE_RUNTIME,
        zone=LayoutZone.CORE_RUNTIME,
        description=(
            "Authoritative startup modules (PR-5 refactor): bootstrap, "
            "service_manager, core_services, node_startup, health_checks, "
            "shutdown, config_manager, dependency_resolver."
        ),
        pr_classified="PR-8-layout",
        notes=(
            "launcher/ is the canonical startup responsibility holder.  "
            "unified_launcher.py orchestrates it.  Do not add startup logic "
            "to root-level scripts; add it here instead."
        ),
    )
)

_REGISTRY._register(
    RepoLayoutEntry(
        path="nodes",
        role=DirectoryRole.ACTIVE_RUNTIME,
        zone=LayoutZone.CORE_RUNTIME,
        description=(
            "Active node system — 130+ canonical nodes (Node_00 through "
            "Node_130), classified and unified in PR-6/PR-7.  Orchestrated "
            "nodes are in node_dependencies.json."
        ),
        pr_classified="PR-8-layout",
        notes=(
            "nodes/ contains all canonical node implementations.  "
            "Reserved nodes (28–32) and Node_130 stub have startup_policy=skip.  "
            "See docs/NODE_ACTIVE_MANIFEST.md and node_dependencies.json."
        ),
    )
)

_REGISTRY._register(
    RepoLayoutEntry(
        path="contracts",
        role=DirectoryRole.ACTIVE_RUNTIME,
        zone=LayoutZone.CORE_RUNTIME,
        description=(
            "Canonical data contracts — DesktopStatusProjection, "
            "MultiDeviceRuntimeProjection, and proto definitions."
        ),
        pr_classified="PR-8-layout",
        notes=(
            "contracts/ defines the authoritative wire contracts consumed by "
            "the active status board and cross-device projection layer.  "
            "Do not duplicate these contracts in legacy surfaces."
        ),
    )
)

_REGISTRY._register(
    RepoLayoutEntry(
        path="galaxy_gateway",
        role=DirectoryRole.ACTIVE_RUNTIME,
        zone=LayoutZone.CORE_RUNTIME,
        description=(
            "Active gateway / cross-device routing substrate — AIP v3 "
            "protocol, device router, NATS adapter, WebSocket handler."
        ),
        pr_classified="PR-8-layout",
        notes=(
            "galaxy_gateway/ is the active execution substrate (PR-7).  "
            "It is not the final routing authority; OpenClawd in core/ holds "
            "that role.  aip_protocol_v2.py within it is a deprecated stub."
        ),
    )
)

_REGISTRY._register(
    RepoLayoutEntry(
        path="desktop_projection",
        role=DirectoryRole.ACTIVE_RUNTIME,
        zone=LayoutZone.CORE_RUNTIME,
        description=(
            "Tri-state liminal-space / manifest-stage projection engine "
            "(silent → liminal → manifest state transitions)."
        ),
        pr_classified="PR-8-layout",
        notes=(
            "desktop_projection/ provides the stage-transition animator, "
            "manifest-stage controller, and state-space mapper that drive "
            "the active tri-state desktop lifecycle."
        ),
    )
)

_REGISTRY._register(
    RepoLayoutEntry(
        path="worker",
        role=DirectoryRole.ACTIVE_RUNTIME,
        zone=LayoutZone.CORE_RUNTIME,
        description="Background task worker pool for async job execution.",
        pr_classified="PR-8-layout",
        notes="worker/ provides the active async execution worker tier.",
    )
)

# ── Active Desktop Status Surface ─────────────────────────────────────────

_REGISTRY._register(
    RepoLayoutEntry(
        path="windows_client/status_board_v2",
        role=DirectoryRole.ACTIVE_DESKTOP_STATUS,
        zone=LayoutZone.DESKTOP_STATUS,
        description=(
            "Canonical operator-facing desktop status runtime surface (PR-8).  "
            "Consumes GET /api/v1/projection/runtime "
            "(contract: contracts.desktop_status_projection.DesktopStatusProjection).  "
            "Tri-state phase surfaces: silent / liminal / manifest."
        ),
        pr_classified="PR-8-layout",
        notes=(
            "status_board_v2/ is the ONLY canonical outward-facing status "
            "runtime surface.  It is projection-driven with bounded exposed "
            "authority.  "
            "Do NOT extend legacy status_board.py; extend this instead."
        ),
    )
)

_REGISTRY._register(
    RepoLayoutEntry(
        path="windows_client/autonomy",
        role=DirectoryRole.ACTIVE_DESKTOP_SHELL,
        zone=LayoutZone.DESKTOP_STATUS,
        description=(
            "Active Windows automation and input-simulation layer "
            "(UI automation, comtypes bootstrap, input simulator)."
        ),
        pr_classified="PR-8-layout",
        notes=(
            "windows_client/autonomy/ is the active OS-interaction layer.  "
            "It does not maintain system state; it drives UI actions only."
        ),
    )
)

# ── Legacy Surfaces ────────────────────────────────────────────────────────

_REGISTRY._register(
    RepoLayoutEntry(
        path="dashboard",
        role=DirectoryRole.LEGACY_SURFACE,
        zone=LayoutZone.LEGACY,
        description=(
            "Legacy WebUI management panel (PR-8 demoted, PR-4 isolated).  "
            "dashboard/backend/main.py — legacy management convenience routes.  "
            "dashboard/frontend/ — non-primary static assets."
        ),
        canonical_replacement="core/api_routes.py",
        pr_classified="PR-8",
        notes=(
            "dashboard/ is retained for transition-period compatibility only.  "
            "It must not define system structure, claim status authority, "
            "or maintain a parallel source of truth.  "
            "See dashboard/LEGACY_SURFACE.md."
        ),
    )
)

_REGISTRY._register(
    RepoLayoutEntry(
        path="windows_client",
        role=DirectoryRole.LEGACY_SHELL,
        zone=LayoutZone.LEGACY,
        description=(
            "Host-specific legacy shell (PR-3 retired, PR-8 demoted).  "
            "Active sub-directories preserved: status_board_v2/ and autonomy/.  "
            "Root-level modules (client.py, ui_sidebar.py, desktop_automation.py, "
            "windows_mcp_server.py, main.py, key_listener.py, "
            "windows_client_integrated.py) are hard-disabled stubs."
        ),
        canonical_replacement="windows_client/status_board_v2",
        pr_classified="PR-3",
        notes=(
            "windows_client/ as a whole is a HOST-SPECIFIC LEGACY SHELL.  "
            "Only windows_client/status_board_v2/ and windows_client/autonomy/ "
            "are active.  Hard-disabled modules raise RuntimeError on import.  "
            "See windows_client/__init__.py and core/ui_surface_authority.py."
        ),
    )
)

# ── Transitional Directories ───────────────────────────────────────────────

_REGISTRY._register(
    RepoLayoutEntry(
        path="enhancements",
        role=DirectoryRole.TRANSITIONAL,
        zone=LayoutZone.LEGACY,
        description=(
            "Enhancement overlays — bridges, execution adapters, "
            "perception modules, and clients.  "
            "enhancements/clients/windows_client/ is hard-disabled (PR-3).  "
            "Other sub-modules are evaluated individually."
        ),
        canonical_replacement="core",
        pr_classified="PR-8-layout",
        notes=(
            "enhancements/ is a transitional directory.  "
            "enhancements/clients/windows_client/run_ui.py is hard-disabled "
            "(raises DeprecationWarning; targeted the retired legacy client).  "
            "New enhancement logic should be integrated directly into core/.  "
            "See enhancements/LEGACY_TRANSITION.md."
        ),
    )
)

# ── Infrastructure Directories ─────────────────────────────────────────────

for _infra_path, _infra_desc in (
    ("docs", "Documentation — architecture, API, operational, migration guides."),
    ("tests", "Test suite — unit, integration, conformance, chaos tests."),
    ("scripts", "Operational scripts — audits, health checks, dep pinning."),
    ("deployment", "Deployment assets — Kubernetes, nginx, Docker configurations."),
    ("config", "Runtime configuration files and Grafana dashboards."),
    ("data", "Persistent data directory."),
    ("static", "Static web assets served by the API layer."),
    ("systemd", "systemd unit files for Linux service management."),
    ("agent", "Agent configuration or runtime agent assets."),
    ("android_client", "Android client implementation."),
    ("cli", "Command-line interface entrypoints."),
    ("daemon", "Background daemon process assets."),
    ("external", "External integrations (AgentCPM, Microsoft UFO, channels)."),
    ("fusion", "Data fusion utilities."),
    ("hardware", "Hardware interface layer."),
    ("installer", "Installation packaging assets."),
    ("integration", "Integration test fixtures and wiring."),
    ("knowledge_db", "Knowledge database assets."),
    ("mcp_bridge", "MCP (Model Context Protocol) bridge."),
    ("path", "Path configuration and resolution utilities."),
    ("skills", "Skill packages (SKILL.md format)."),
    ("system_integration", "System integration layer."),
    ("tools", "Developer tooling."),
    ("examples", "Usage examples and sample configurations."),
):
    _REGISTRY._register(
        RepoLayoutEntry(
            path=_infra_path,
            role=DirectoryRole.INFRASTRUCTURE,
            zone=LayoutZone.INFRASTRUCTURE,
            description=_infra_desc,
            pr_classified="PR-8-layout",
        )
    )


# Public immutable view.
REPO_LAYOUT_REGISTRY: Dict[str, RepoLayoutEntry] = dict(_REGISTRY._registry)


# ---------------------------------------------------------------------------
# Module-level convenience helpers
# ---------------------------------------------------------------------------


def is_active_runtime_directory(path: str) -> bool:
    """Return ``True`` if *path* is an active runtime or desktop status directory."""
    return _REGISTRY.is_active(path)


def is_legacy_directory(path: str) -> bool:
    """Return ``True`` if *path* is a legacy or transitional directory."""
    return _REGISTRY.is_legacy(path)


def is_active_desktop_status_directory(path: str) -> bool:
    """Return ``True`` if *path* is the canonical active desktop status surface."""
    entry = _REGISTRY.get(path)
    return entry is not None and entry.role == DirectoryRole.ACTIVE_DESKTOP_STATUS


def get_layout_zone(path: str) -> Optional[LayoutZone]:
    """Return the :class:`LayoutZone` for *path*, or ``None`` if not registered."""
    return _REGISTRY.get_zone(path)


def get_repo_layout_entry(path: str) -> Optional[RepoLayoutEntry]:
    """Return the :class:`RepoLayoutEntry` for *path*, or ``None``."""
    return _REGISTRY.get(path)


def build_repo_layout_summary() -> Dict:
    """Build a structured summary of the repository layout registry.

    Returns a dict suitable for embedding in diagnostics or API responses.

    Example return value::

        {
          "total_directories": 18,
          "active_count": 9,
          "legacy_count": 4,
          "infrastructure_count": 5,
          "core_runtime_count": 7,
          "desktop_status_count": 2,
          "directories": [...]
        }
    """
    return _REGISTRY.summary()


def get_repo_layout_registry() -> RepoLayoutRegistry:
    """Return the singleton :class:`RepoLayoutRegistry`."""
    return _REGISTRY
