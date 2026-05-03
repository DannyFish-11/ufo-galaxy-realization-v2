#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.ui_surface_authority
==========================

PR-8 — Demote legacy UI surfaces and standardize projection-only status
architecture.

**Architectural intent**
------------------------
The intended outward-facing model for system status is a **desktop status
board that consumes projection output only**.  Historical UI surfaces
(``dashboard/`` and the root ``windows_client`` legacy shell) are retired and
must not be reintroduced as architectural authorities or parallel state
sources.

This module is the authoritative registry for UI surface roles across the
Galaxy codebase.  It answers three questions:

1. **What role does a surface play?**  Is it projection-driven, a legacy UI
   surface, a host-specific legacy shell, or a compatibility-only adapter?

2. **Is a given surface the canonical outward truth?**  Only
   ``PROJECTION_DRIVEN`` surfaces are.

3. **What should consumers use instead of a legacy surface?**  Each legacy
   entry carries a ``superseded_by`` pointer to the canonical replacement.

Authority model::

    ┌──────────────────────────────────────────────────────────┐
    │  CANONICAL OUTWARD STATUS TRUTH                          │
    │  ─────────────────────────────                           │
    │  windows_client.status_board_v2                          │
    │    consumes  ──►  GET /api/v1/projection/runtime         │
    │    contract  ──►  contracts.desktop_status_projection    │
    │                   (DesktopStatusProjection)              │
    └──────────────────────────────────────────────────────────┘
                              ▲ derived-only / READ-ONLY
    ┌──────────────────────────────────────────────────────────┐
    │  CANONICAL STATUS PROJECTION SOURCE                      │
    │  ─────────────────────────────────                       │
    │  core.routes.projection  →  RuntimeProjection            │
    │  core.projection.runtime_projection                      │
    │  contracts.desktop_status_projection                     │
    └──────────────────────────────────────────────────────────┘

Retired surfaces that must NOT be reintroduced as system structure or parallel state::

    dashboard/                    →  DELETED  (former WebUI management panel)
    windows_client/main.py         →  DELETED  (former host-specific shell)
    windows_client/status_board.py →  DELETED  (former ad-hoc status board)

Usage::

    from core.ui_surface_authority import (
        UISurfaceRole,
        UISurfaceAuthorityRegistry,
        is_legacy_surface,
        is_projection_driven_surface,
        build_ui_surface_authority_summary,
        get_ui_surface_authority,
    )

    assert not is_legacy_surface("dashboard.backend.main")
    assert is_projection_driven_surface("windows_client.status_board_v2")
    summary = build_ui_surface_authority_summary()
"""

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.UISurfaceAuthority")

__all__ = [
    "UISurfaceRole",
    "UISurfaceEntry",
    "UI_SURFACE_REGISTRY",
    "UISurfaceAuthorityRegistry",
    "is_legacy_surface",
    "is_projection_driven_surface",
    "get_ui_surface_entry",
    "get_ui_surface_role",
    "build_ui_surface_authority_summary",
    "get_ui_surface_authority",
]


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------


class UISurfaceRole(str, Enum):
    """Canonical role classification for UI surfaces.

    ``PROJECTION_DRIVEN``
        The surface is the **canonical outward status interface**.  It consumes
        projection output from ``core.routes.projection`` / the
        ``DesktopStatusProjection`` contract and does **not** maintain its own
        parallel state model.  This is the only role that represents the
        authoritative outward truth for system status.

    ``LEGACY_UI``
        A legacy management UI surface.  Retained for compatibility.  Must not
        define system structure, claim status authority, or maintain a parallel
        source of truth.  Should be marked clearly as legacy in all entry-points.

    ``LEGACY_SHELL``
        A host-specific legacy shell.  Retained for compatibility.  Must not
        define the primary desktop interaction philosophy or act as the
        outward-facing status authority.

    ``COMPATIBILITY_ONLY``
        A thin adapter or bridge surface kept for third-party compatibility.
        No architectural authority whatsoever.
    """

    PROJECTION_DRIVEN = "projection_driven"
    LEGACY_UI = "legacy_ui"
    LEGACY_SHELL = "legacy_shell"
    COMPATIBILITY_ONLY = "compatibility_only"
    DELETED = "deleted"


# ---------------------------------------------------------------------------
# Entry dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class UISurfaceEntry:
    """Metadata record for a registered UI surface.

    Parameters
    ----------
    surface_path:
        Canonical dotted path (or well-known label) for the surface, e.g.
        ``"dashboard.backend.main"``, ``"windows_client.status_board_v2"``.
    role:
        :class:`UISurfaceRole` classification.
    description:
        Human-readable one-line description of the surface.
    canonical_contract:
        Dotted path to the projection contract / schema consumed by this
        surface.  ``None`` if the surface does not consume projection.
    superseded_by:
        For legacy surfaces: dotted path to the canonical replacement.
        ``None`` for ``PROJECTION_DRIVEN`` or ``COMPATIBILITY_ONLY`` surfaces.
    pr_demoted:
        PR reference that formally demoted this surface (if applicable).
    notes:
        Optional extended notes for contributors.
    """

    surface_path: str
    role: UISurfaceRole
    description: str
    canonical_contract: Optional[str] = None
    superseded_by: Optional[str] = None
    pr_demoted: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "surface_path": self.surface_path,
            "role": self.role.value,
            "description": self.description,
            "canonical_contract": self.canonical_contract,
            "superseded_by": self.superseded_by,
            "pr_demoted": self.pr_demoted,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Registry singleton
# ---------------------------------------------------------------------------


class UISurfaceAuthorityRegistry:
    """Singleton registry of all known UI surfaces and their authority roles.

    The registry is populated at module-load time and is immutable at runtime.
    """

    _instance: Optional["UISurfaceAuthorityRegistry"] = None
    _registry: Dict[str, UISurfaceEntry]

    def __new__(cls) -> "UISurfaceAuthorityRegistry":
        if cls._instance is None:
            inst = object.__new__(cls)
            inst._registry = {}
            cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------
    # Internal registration helpers
    # ------------------------------------------------------------------

    def _register(self, *entries: UISurfaceEntry) -> None:
        for entry in entries:
            self._registry[entry.surface_path] = entry

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get(self, surface_path: str) -> Optional[UISurfaceEntry]:
        """Return the :class:`UISurfaceEntry` for *surface_path*, or ``None``."""
        return self._registry.get(surface_path)

    def get_role(self, surface_path: str) -> Optional[UISurfaceRole]:
        """Return the :class:`UISurfaceRole` for *surface_path*, or ``None``."""
        entry = self._registry.get(surface_path)
        return entry.role if entry is not None else None

    def is_legacy(self, surface_path: str) -> bool:
        """Return ``True`` if *surface_path* is a legacy surface."""
        role = self.get_role(surface_path)
        return role in (UISurfaceRole.LEGACY_UI, UISurfaceRole.LEGACY_SHELL,
                        UISurfaceRole.COMPATIBILITY_ONLY)

    def is_projection_driven(self, surface_path: str) -> bool:
        """Return ``True`` if *surface_path* is the canonical projection-driven surface."""
        return self.get_role(surface_path) == UISurfaceRole.PROJECTION_DRIVEN

    def all_entries(self) -> List[UISurfaceEntry]:
        """Return all registered entries."""
        return list(self._registry.values())

    def projection_driven_surfaces(self) -> List[UISurfaceEntry]:
        """Return only the ``PROJECTION_DRIVEN`` entries."""
        return [e for e in self._registry.values()
                if e.role == UISurfaceRole.PROJECTION_DRIVEN]

    def legacy_surfaces(self) -> List[UISurfaceEntry]:
        """Return all ``LEGACY_*`` and ``COMPATIBILITY_ONLY`` entries."""
        return [e for e in self._registry.values()
                if e.role in (
                    UISurfaceRole.LEGACY_UI,
                    UISurfaceRole.LEGACY_SHELL,
                    UISurfaceRole.COMPATIBILITY_ONLY,
                )]

    def summary(self) -> Dict:
        """Return a structured summary dict (used by builders and tests)."""
        projection_count = len(self.projection_driven_surfaces())
        legacy_count = len(self.legacy_surfaces())
        return {
            "total_surfaces": len(self._registry),
            "projection_driven_count": projection_count,
            "legacy_count": legacy_count,
            "projection_is_only_outward_truth": projection_count >= 1,
            "surfaces": [e.to_dict() for e in sorted(
                self._registry.values(), key=lambda e: e.surface_path
            )],
        }


# ---------------------------------------------------------------------------
# Build and populate the registry (module-load time)
# ---------------------------------------------------------------------------

_REGISTRY = UISurfaceAuthorityRegistry()

_REGISTRY._register(
    # ------------------------------------------------------------------
    # CANONICAL — projection-driven outward status surface
    # ------------------------------------------------------------------
    UISurfaceEntry(
        surface_path="windows_client.status_board_v2",
        role=UISurfaceRole.PROJECTION_DRIVEN,
        description=(
            "Status Board V2 — the canonical read-only desktop status board. "
            "Consumes RuntimeProjection from GET /api/v1/projection/runtime "
            "and DesktopStatusProjection contract.  "
            "Projection is the sole outward truth for system status."
        ),
        canonical_contract="contracts.desktop_status_projection.DesktopStatusProjection",
        superseded_by=None,
        pr_demoted=None,
        notes=(
            "windows_client/status_board_v2/ is READ-ONLY.  "
            "It never accepts chat input, sends commands, or maintains its own "
            "parallel state model.  All authority flows from "
            "core.routes.projection → RuntimeProjection → DesktopStatusProjection."
        ),
    ),

    # ------------------------------------------------------------------
    # DELETED — dashboard/ (retired WebUI management panel)
    # ------------------------------------------------------------------
    UISurfaceEntry(
        surface_path="dashboard.backend.main",
        role=UISurfaceRole.DELETED,
        description=(
            "Galaxy Dashboard — deleted non-mainline WebUI surface.  "
            "Does not define system structure or represent the canonical "
            "outward status truth."
        ),
        canonical_contract=None,
        superseded_by="windows_client.status_board_v2",
        pr_demoted="PR-mainline-closure",
        notes=(
            "dashboard/ has been deleted as non-mainline noise. The "
            "authoritative REST/API status surfaces are core/routes/* and "
            "GET /api/v1/projection/runtime (RuntimeProjection / "
            "DesktopStatusProjection contract)."
        ),
    ),
    UISurfaceEntry(
        surface_path="dashboard",
        role=UISurfaceRole.DELETED,
        description="Galaxy Dashboard package — deleted non-mainline UI surface.",
        canonical_contract=None,
        superseded_by="windows_client.status_board_v2",
        pr_demoted="PR-mainline-closure",
        notes="dashboard/ is DELETED; do not recreate it as a status authority.",
    ),

    # ------------------------------------------------------------------
    # DELETED — windows_client/ root legacy shell/status surfaces
    # ------------------------------------------------------------------
    UISurfaceEntry(
        surface_path="windows_client.main",
        role=UISurfaceRole.DELETED,
        description=(
            "Windows Client main entry-point — deleted host-specific legacy shell."
        ),
        canonical_contract=None,
        superseded_by="windows_client.status_board_v2",
        pr_demoted="PR-mainline-closure",
        notes=(
            "windows_client/main.py is DELETED as non-mainline shell noise. "
            "Desktop status consumers must use the projection-driven "
            "windows_client.status_board_v2."
        ),
    ),
    UISurfaceEntry(
        surface_path="windows_client.status_board",
        role=UISurfaceRole.DELETED,
        description=(
            "windows_client/status_board.py — deleted ad-hoc status board."
        ),
        canonical_contract=None,
        superseded_by="windows_client.status_board_v2",
        pr_demoted="PR-mainline-closure",
        notes=(
            "status_board.py is DELETED. The canonical replacement is "
            "status_board_v2/ which consumes the RuntimeProjection contract from "
            "GET /api/v1/projection/runtime."
        ),
    ),
    UISurfaceEntry(
        surface_path="windows_client",
        role=UISurfaceRole.DELETED,
        description=(
            "windows_client/ root shell surface — retired; package remains only "
            "to host windows_client.status_board_v2 and runtime adapters."
        ),
        canonical_contract=None,
        superseded_by="windows_client.status_board_v2",
        pr_demoted="PR-mainline-closure",
        notes="The root shell authority is deleted; status_board_v2 is the canonical surface.",
    ),
)

# Public immutable view of the registry dict.
UI_SURFACE_REGISTRY: Dict[str, UISurfaceEntry] = dict(_REGISTRY._registry)


# ---------------------------------------------------------------------------
# Module-level convenience helpers
# ---------------------------------------------------------------------------


def is_legacy_surface(surface_path: str) -> bool:
    """Return ``True`` if *surface_path* is registered as a legacy surface.

    Legacy surfaces include :attr:`~UISurfaceRole.LEGACY_UI`,
    :attr:`~UISurfaceRole.LEGACY_SHELL`, and
    :attr:`~UISurfaceRole.COMPATIBILITY_ONLY`. Deleted audit records are not
    treated as live legacy surfaces.
    """
    return _REGISTRY.is_legacy(surface_path)


def is_projection_driven_surface(surface_path: str) -> bool:
    """Return ``True`` if *surface_path* is the canonical projection-driven surface."""
    return _REGISTRY.is_projection_driven(surface_path)


def get_ui_surface_entry(surface_path: str) -> Optional[UISurfaceEntry]:
    """Return the :class:`UISurfaceEntry` for *surface_path*, or ``None``."""
    return _REGISTRY.get(surface_path)


def get_ui_surface_role(surface_path: str) -> Optional[UISurfaceRole]:
    """Return the :class:`UISurfaceRole` for *surface_path*, or ``None``."""
    return _REGISTRY.get_role(surface_path)


def build_ui_surface_authority_summary() -> Dict:
    """Build a structured summary of the current UI surface authority model.

    Returns a dict suitable for embedding in diagnostics, projection metadata,
    or API responses.  The ``projection_is_only_outward_truth`` flag is ``True``
    when at least one ``PROJECTION_DRIVEN`` surface is registered.

    Example return value::

        {
          "total_surfaces": 6,
          "projection_driven_count": 1,
          "legacy_count": 0,
          "projection_is_only_outward_truth": True,
          "surfaces": [...]
        }
    """
    return _REGISTRY.summary()


def get_ui_surface_authority() -> UISurfaceAuthorityRegistry:
    """Return the singleton :class:`UISurfaceAuthorityRegistry`."""
    return _REGISTRY
