#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/legacy_dispatch_registry.py — PR-A: Legacy Dispatch Registry
==================================================================

**Legacy Dispatch Registry — Classification & Observability**
--------------------------------------------------------------
Provides a formal registry for all legacy dispatch paths that bypass or
pre-date the canonical execution spine:

    CanonicalTask → TaskEnvelope → CommandRouter.route_envelope()

Every shortcut that dispatches outside this spine MUST be registered here
with an explicit classification.  This makes the demotion status observable
and verifiable in tests and operator tooling.

Classifications
---------------
- ``compat-only`` — kept for backward-compatibility with older callers.
  MUST NOT be extended.  May be removed in a future PR.
- ``deprecated`` — will be removed in an upcoming PR.  Callers should
  migrate to the canonical spine immediately.
- ``facade-only`` — demoted to a thin wrapper / planner helper.  The
  module no longer performs independent system-level dispatch.

Architecture invariants
-----------------------
1.  All entries in this registry represent paths that MUST NOT become
    parallel dispatch authorities.
2.  Any module adding a new dispatch shortcut MUST register it here.
3.  The registry is observable via :func:`get_legacy_dispatch_registry`
    and :func:`snapshot_registry`.
4.  Tests MUST assert that specific known legacy paths are registered and
    correctly classified.

Public API
----------
Authority sentinels::

    LEGACY_DISPATCH_REGISTRY_AUTHORITY
    LEGACY_DISPATCH_REGISTRY_POLICY

Enumerations::

    LegacyDispatchClassification

Dataclasses::

    LegacyDispatchEntry
    LegacyRegistrySnapshot

Classes::

    LegacyDispatchRegistry

Helpers::

    register_legacy_dispatch(module, classification, reason)
    get_legacy_dispatch_registry() -> LegacyDispatchRegistry
    snapshot_registry() -> LegacyRegistrySnapshot
    reset_registry()   # testing only
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LegacyDispatchRegistry")

__all__ = [
    # Authority
    "LEGACY_DISPATCH_REGISTRY_AUTHORITY",
    "LEGACY_DISPATCH_REGISTRY_POLICY",
    # Enum
    "LegacyDispatchClassification",
    # Dataclasses
    "LegacyDispatchEntry",
    "LegacyRegistrySnapshot",
    # Class
    "LegacyDispatchRegistry",
    # Helpers
    "register_legacy_dispatch",
    "get_legacy_dispatch_registry",
    "snapshot_registry",
    "reset_registry",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

LEGACY_DISPATCH_REGISTRY_AUTHORITY: str = "LEGACY_DISPATCH_REGISTRY_V1"
"""Sentinel: identifies this module as the legacy dispatch registry authority."""

LEGACY_DISPATCH_REGISTRY_POLICY: str = (
    "ALL legacy dispatch paths that bypass CanonicalTask→TaskEnvelope→"
    "CommandRouter.route_envelope() MUST be registered here with an explicit "
    "classification (compat-only/deprecated/facade-only)."
)
"""Policy: all legacy dispatch shortcuts must be formally registered."""


# ---------------------------------------------------------------------------
# Classification enum
# ---------------------------------------------------------------------------

class LegacyDispatchClassification(str, Enum):
    """Classification of a legacy dispatch entry.

    :attr:`COMPAT_ONLY`   — preserved for backward compatibility only.
    :attr:`DEPRECATED`    — deprecated, scheduled for removal.
    :attr:`FACADE_ONLY`   — module demoted to facade/planner helper; no
                            independent dispatch authority.
    """

    COMPAT_ONLY = "compat-only"
    DEPRECATED = "deprecated"
    FACADE_ONLY = "facade-only"


# ---------------------------------------------------------------------------
# Registry entry dataclass
# ---------------------------------------------------------------------------

@dataclass
class LegacyDispatchEntry:
    """A single entry in the legacy dispatch registry."""

    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    module: str = ""
    """Python module path (e.g. 'fusion.unified_orchestrator')."""

    classification: LegacyDispatchClassification = LegacyDispatchClassification.DEPRECATED
    """Formal demotion classification."""

    reason: str = ""
    """Human-readable explanation of why this path is legacy."""

    registered_at: float = field(default_factory=time.time)
    """Unix timestamp when this entry was registered."""

    pr_origin: str = ""
    """PR that introduced the demotion (e.g. 'PR-3', 'PR-A')."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "module": self.module,
            "classification": (
                self.classification.value
                if isinstance(self.classification, LegacyDispatchClassification)
                else str(self.classification)
            ),
            "reason": self.reason,
            "registered_at": self.registered_at,
            "pr_origin": self.pr_origin,
        }


# ---------------------------------------------------------------------------
# Registry snapshot
# ---------------------------------------------------------------------------

@dataclass
class LegacyRegistrySnapshot:
    """Point-in-time snapshot of the legacy dispatch registry."""

    total_entries: int = 0
    entries_by_classification: Dict[str, int] = field(default_factory=dict)
    entries: List[Dict[str, Any]] = field(default_factory=list)
    snapshot_ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_entries": self.total_entries,
            "entries_by_classification": self.entries_by_classification,
            "entries": self.entries,
            "snapshot_ts": self.snapshot_ts,
        }


# ---------------------------------------------------------------------------
# LegacyDispatchRegistry class
# ---------------------------------------------------------------------------

class LegacyDispatchRegistry:
    """Singleton registry of all legacy dispatch paths.

    Usage::

        registry = get_legacy_dispatch_registry()
        registry.register(
            module="fusion.unified_orchestrator",
            classification=LegacyDispatchClassification.FACADE_ONLY,
            reason="Demoted to planner facade in PR-3; no dispatch authority.",
            pr_origin="PR-3",
        )
        snap = registry.snapshot()
        print(snap.total_entries)
    """

    def __init__(self) -> None:
        self._entries: Dict[str, LegacyDispatchEntry] = {}
        """Keyed by module path for O(1) lookup and idempotent registration."""

    def register(
        self,
        module: str,
        classification: LegacyDispatchClassification,
        reason: str = "",
        pr_origin: str = "",
    ) -> LegacyDispatchEntry:
        """Register or update a legacy dispatch entry.

        Subsequent calls with the same *module* update the classification
        and reason (idempotent upsert).

        Parameters
        ----------
        module:
            Python module path.
        classification:
            :class:`LegacyDispatchClassification` value.
        reason:
            Human-readable demotion reason.
        pr_origin:
            PR that introduced the demotion.

        Returns
        -------
        LegacyDispatchEntry
        """
        if not module:
            raise ValueError("module must be a non-empty string")
        entry = LegacyDispatchEntry(
            module=module,
            classification=classification,
            reason=reason,
            pr_origin=pr_origin,
        )
        self._entries[module] = entry
        logger.debug(
            "LegacyDispatchRegistry.register | module=%s classification=%s",
            module, classification.value if isinstance(classification, LegacyDispatchClassification) else classification,
        )
        return entry

    def get(self, module: str) -> Optional[LegacyDispatchEntry]:
        """Return the entry for *module*, or ``None`` if not registered."""
        return self._entries.get(module)

    def is_registered(self, module: str) -> bool:
        """Return ``True`` when *module* is registered as a legacy path."""
        return module in self._entries

    def get_by_classification(
        self, classification: LegacyDispatchClassification
    ) -> List[LegacyDispatchEntry]:
        """Return all entries with the given *classification*."""
        return [
            e for e in self._entries.values()
            if e.classification == classification
        ]

    def all_entries(self) -> List[LegacyDispatchEntry]:
        """Return all registered entries."""
        return list(self._entries.values())

    def snapshot(self) -> LegacyRegistrySnapshot:
        """Return a point-in-time snapshot of the registry."""
        by_class: Dict[str, int] = {}
        for entry in self._entries.values():
            cls_val = (
                entry.classification.value
                if isinstance(entry.classification, LegacyDispatchClassification)
                else str(entry.classification)
            )
            by_class[cls_val] = by_class.get(cls_val, 0) + 1
        return LegacyRegistrySnapshot(
            total_entries=len(self._entries),
            entries_by_classification=by_class,
            entries=[e.to_dict() for e in self._entries.values()],
        )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_registry_instance: Optional[LegacyDispatchRegistry] = None


def get_legacy_dispatch_registry() -> LegacyDispatchRegistry:
    """Return the process-global :class:`LegacyDispatchRegistry` singleton."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = LegacyDispatchRegistry()
        _bootstrap_known_entries(_registry_instance)
    return _registry_instance


def reset_registry() -> None:
    """Reset the singleton (for testing only)."""
    global _registry_instance
    _registry_instance = None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def register_legacy_dispatch(
    module: str,
    classification: LegacyDispatchClassification,
    reason: str = "",
    pr_origin: str = "",
) -> LegacyDispatchEntry:
    """Register a legacy dispatch path with the global registry.

    Convenience wrapper around ``get_legacy_dispatch_registry().register()``.

    Parameters
    ----------
    module:
        Python module path (e.g. 'fusion.unified_orchestrator').
    classification:
        :class:`LegacyDispatchClassification` value.
    reason:
        Human-readable demotion reason.
    pr_origin:
        PR that formalized the demotion.

    Returns
    -------
    LegacyDispatchEntry
    """
    return get_legacy_dispatch_registry().register(
        module=module,
        classification=classification,
        reason=reason,
        pr_origin=pr_origin,
    )


def snapshot_registry() -> LegacyRegistrySnapshot:
    """Return a snapshot of the global legacy dispatch registry."""
    return get_legacy_dispatch_registry().snapshot()


# ---------------------------------------------------------------------------
# Bootstrap: pre-register all known legacy dispatch paths
# ---------------------------------------------------------------------------

def _bootstrap_known_entries(registry: LegacyDispatchRegistry) -> None:
    """Pre-populate the registry with all known legacy dispatch paths.

    This ensures the registry is always coherent even before individual
    modules have self-registered.
    """
    _C = LegacyDispatchClassification

    # ── PR-3 demotions ──────────────────────────────────────────────────
    registry.register(
        module="core.e2e_orchestrator",
        classification=_C.FACADE_ONLY,
        reason="Convenience facade over canonical chain; no independent dispatch authority.",
        pr_origin="PR-3",
    )
    registry.register(
        module="core.device_orchestrator",
        classification=_C.FACADE_ONLY,
        reason="Demoted to FACADE_AUTHORITY in PR-3; routes through CommandRouter.",
        pr_origin="PR-3",
    )
    registry.register(
        module="galaxy_gateway.orchestrator.galaxy_orchestrator",
        classification=_C.FACADE_ONLY,
        reason="Demoted to FACADE_AUTHORITY in PR-3; graph contributor in PR-6.",
        pr_origin="PR-3",
    )
    registry.register(
        module="fusion.unified_orchestrator",
        classification=_C.FACADE_ONLY,
        reason="Deprecated module; demoted to FACADE_AUTHORITY in PR-3; graph contributor in PR-6.",
        pr_origin="PR-3",
    )

    # ── PR-3 side-path modules ──────────────────────────────────────────
    registry.register(
        module="core.local_execution_chain",
        classification=_C.COMPAT_ONLY,
        reason="Audit/projection helper for local path; no dispatch authority.",
        pr_origin="PR-3",
    )
    registry.register(
        module="core.cross_device_execution_chain",
        classification=_C.COMPAT_ONLY,
        reason="Audit/projection helper for cross-device path; no dispatch authority.",
        pr_origin="PR-3",
    )
    registry.register(
        module="core.hybrid_executor",
        classification=_C.COMPAT_ONLY,
        reason="Fallback-level execution helper; no top-level dispatch authority.",
        pr_origin="PR-3",
    )
    registry.register(
        module="core.remote_execution_mode_resolver",
        classification=_C.COMPAT_ONLY,
        reason="Mode-resolution helper for CommandRouter; not a dispatch authority.",
        pr_origin="PR-3",
    )
    registry.register(
        module="galaxy_gateway.agent_bridge",
        classification=_C.COMPAT_ONLY,
        reason="Runtime handoff adapter; normalizes to execution spine.",
        pr_origin="PR-3",
    )
    registry.register(
        module="galaxy_gateway.task_router",
        classification=_C.DEPRECATED,
        reason="Legacy compatibility surface; all new paths use CommandRouter.",
        pr_origin="PR-3",
    )
    registry.register(
        module="galaxy_gateway.cross_device_coordinator",
        classification=_C.COMPAT_ONLY,
        reason="Internal cross-device substrate called by DeviceRouter; not a primary entry.",
        pr_origin="PR-3",
    )

    # ── PR-A demotions ──────────────────────────────────────────────────
    registry.register(
        module="core.repo_coordinator",
        classification=_C.FACADE_ONLY,
        reason="Legacy/management facade; demoted in PR-S4.",
        pr_origin="PR-A",
    )
    registry.register(
        module="core.execution_spine",
        classification=_C.COMPAT_ONLY,
        reason=(
            "PR-3 ingress normalizer; CanonicalTask adapter is the preferred "
            "entry point; this module remains for scheduler/bridge ingress normalization."
        ),
        pr_origin="PR-A",
    )
