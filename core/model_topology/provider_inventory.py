"""
core/model_topology/provider_inventory.py
==========================================
ProviderInventory – a typed, queryable collection of NormalizedTopologyEntry
objects produced by the ConfigBridge.

Design goals
------------
- Act as the *single source of truth* for the current provider/model supply
  after bridge normalization.
- Provide lookups by provider_id, by category, by role hint, and by
  availability/multimodal flags.
- Be serialisable to a plain dict for transport (status board, future
  projection layers).
- Remain independent of the dashboard frontend and FastAPI routes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional

from .topology_types import (
    AggregatorRouterHint,
    NormalizedTopologyEntry,
    ProviderCategory,
    TopologyRole,
)

logger = logging.getLogger("Galaxy.ModelTopology.ProviderInventory")


# ---------------------------------------------------------------------------
# ProviderInventoryEntry – thin wrapper that can carry an optional health
# snapshot alongside the normalized topology entry.
# ---------------------------------------------------------------------------


@dataclass
class ProviderInventoryEntry:
    """One slot in the inventory: a normalized topology entry plus an optional
    live health snapshot (populated later by the routing telemetry layer).

    PR-4 adds config-authority-driven fields:

    config_enabled
        Set by the unified config authority (``runtime/config.json``
        ``providers.<id>.enabled``).  When ``False`` the provider must not
        appear in the routing candidate pool regardless of key presence.

    config_has_key
        ``True`` when the required secret(s) for this provider are present
        according to the unified config authority (env-var or
        ``runtime/secrets.env``).

    config_source
        Informational: records which authority layer produced these flags.
        Expected values: ``"config_authority"`` (set by
        ``inventory_from_config``), ``"env"`` (legacy env-probing path),
        ``"unknown"`` (not yet determined).

    is_candidate_eligible
        Derived: ``True`` only when ``config_enabled`` **and**
        ``config_has_key`` are both ``True``.  Routing candidate-pool
        formation uses this flag as the primary gate.
    """
    entry: NormalizedTopologyEntry
    health_status: str = "unknown"   # "healthy" | "degraded" | "down" | "unknown"
    latency_avg_ms: float = 0.0
    error_rate: float = 0.0
    # PR-4: config-authority-driven participation flags
    config_enabled: bool = True
    config_has_key: bool = True
    config_source: str = "unknown"

    @property
    def provider_id(self) -> str:
        return self.entry.provider.provider_id

    @property
    def model_id(self) -> str:
        return self.entry.model.model_id

    @property
    def is_candidate_eligible(self) -> bool:
        """True when this provider may participate in routing candidate pool."""
        return self.config_enabled and self.config_has_key

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "display_name": self.entry.provider.display_name,
            "model_id": self.model_id,
            "alternative_models": self.entry.model.alternatives,
            "category": self.entry.category.value,
            "role_hints": [r.value for r in self.entry.role_hints],
            "available": self.entry.is_available,
            "missing_env_key": self.entry.availability.missing_env_key,
            "all_env_keys": self.entry.availability.all_env_keys,
            "native_multimodal": self.entry.is_multimodal_native,
            "supports_vision": self.entry.modality.supports_vision,
            "speed_score": self.entry.scoring.speed_score,
            "quality_score": self.entry.scoring.quality_score,
            "composite_score": self.entry.scoring.composite_score,
            "health_status": self.health_status,
            "latency_avg_ms": self.latency_avg_ms,
            "error_rate": self.error_rate,
            # PR-4 config-authority fields
            "config_enabled": self.config_enabled,
            "config_has_key": self.config_has_key,
            "config_source": self.config_source,
            "is_candidate_eligible": self.is_candidate_eligible,
        }


# ---------------------------------------------------------------------------
# ProviderInventory
# ---------------------------------------------------------------------------


class ProviderInventory:
    """Queryable collection of ProviderInventoryEntry objects.

    Typical lifecycle::

        bridge = ConfigBridge()
        inventory = bridge.build_inventory(snapshots)
        # … later …
        multimodal = inventory.multimodal_entries()
        available  = inventory.available_entries()
    """

    def __init__(
        self,
        entries: Optional[Iterable[ProviderInventoryEntry]] = None,
        aggregator_hints: Optional[List[AggregatorRouterHint]] = None,
    ) -> None:
        self._entries: Dict[str, ProviderInventoryEntry] = {}
        self.aggregator_hints: List[AggregatorRouterHint] = list(aggregator_hints or [])
        for e in (entries or []):
            self.add(e)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, inv_entry: ProviderInventoryEntry) -> None:
        pid = inv_entry.provider_id
        if pid in self._entries:
            logger.warning(
                "ProviderInventory: duplicate provider_id '%s'; overwriting.", pid
            )
        self._entries[pid] = inv_entry

    # ------------------------------------------------------------------
    # Basic lookups
    # ------------------------------------------------------------------

    def get(self, provider_id: str) -> Optional[ProviderInventoryEntry]:
        return self._entries.get(provider_id)

    def all_entries(self) -> List[ProviderInventoryEntry]:
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[ProviderInventoryEntry]:
        return iter(self._entries.values())

    def __contains__(self, provider_id: str) -> bool:
        return provider_id in self._entries

    # ------------------------------------------------------------------
    # Filtered views
    # ------------------------------------------------------------------

    def available_entries(self) -> List[ProviderInventoryEntry]:
        """Entries where the required API key is present (env-probing path)."""
        return [e for e in self._entries.values() if e.entry.is_available]

    def unavailable_entries(self) -> List[ProviderInventoryEntry]:
        return [e for e in self._entries.values() if not e.entry.is_available]

    # ------------------------------------------------------------------
    # PR-4: Config-authority-driven candidate pool views
    # ------------------------------------------------------------------

    def candidate_pool_entries(self) -> List[ProviderInventoryEntry]:
        """Entries eligible to participate in routing candidate-pool selection.

        A provider is eligible when **both** of the following hold:

        - ``config_enabled`` is ``True`` (the provider is enabled in the
          unified config authority)
        - ``config_has_key`` is ``True`` (required secret(s) are present
          according to the config authority)

        Disabled providers and providers missing required secrets do **not**
        appear in the candidate pool regardless of their env-probing
        availability status.

        This is the primary gate used by routing candidate-pool formation
        (PR-4).  Downstream routing (``TopologyRouter``) consumes this view
        instead of the raw ``available_entries()`` list when the config
        authority has been applied.
        """
        return [e for e in self._entries.values() if e.is_candidate_eligible]

    def enabled_entries(self) -> List[ProviderInventoryEntry]:
        """Entries whose provider is enabled in the unified config authority.

        Note: enabled does **not** imply the key is present.  For the routing
        candidate pool use :meth:`candidate_pool_entries` instead.
        """
        return [e for e in self._entries.values() if e.config_enabled]

    def disabled_entries(self) -> List[ProviderInventoryEntry]:
        """Entries whose provider is explicitly disabled in the config authority."""
        return [e for e in self._entries.values() if not e.config_enabled]

    def unconfigured_entries(self) -> List[ProviderInventoryEntry]:
        """Entries that are enabled in config but are missing required secrets.

        These providers are enabled by operator intent but cannot participate
        in the routing candidate pool until the required key is supplied.
        They may appear in diagnostic / inventory views as *enabled but
        unconfigured*.
        """
        return [
            e for e in self._entries.values()
            if e.config_enabled and not e.config_has_key
        ]

    def multimodal_entries(self) -> List[ProviderInventoryEntry]:
        """Entries whose provider natively supports multimodal input."""
        return [e for e in self._entries.values() if e.entry.is_multimodal_native]

    def by_category(self, category: ProviderCategory) -> List[ProviderInventoryEntry]:
        return [e for e in self._entries.values() if e.entry.category == category]

    def by_role(self, role: TopologyRole) -> List[ProviderInventoryEntry]:
        return [
            e for e in self._entries.values()
            if role in e.entry.role_hints
        ]

    def top_by_quality(self, n: int = 5, available_only: bool = True) -> List[ProviderInventoryEntry]:
        pool = self.available_entries() if available_only else self.all_entries()
        return sorted(pool, key=lambda e: e.entry.scoring.quality_score, reverse=True)[:n]

    def top_by_speed(self, n: int = 5, available_only: bool = True) -> List[ProviderInventoryEntry]:
        pool = self.available_entries() if available_only else self.all_entries()
        return sorted(pool, key=lambda e: e.entry.scoring.speed_score, reverse=True)[:n]

    def top_by_composite(self, n: int = 5, available_only: bool = True) -> List[ProviderInventoryEntry]:
        pool = self.available_entries() if available_only else self.all_entries()
        return sorted(pool, key=lambda e: e.entry.scoring.composite_score, reverse=True)[:n]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise the full inventory to a plain dict suitable for JSON
        transport or status-board projection.
        """
        return {
            "entries": {pid: e.to_dict() for pid, e in self._entries.items()},
            "aggregator_hints": [
                {
                    "kind": h.kind.value,
                    "label": h.label,
                    "candidate_provider_ids": h.candidate_provider_ids,
                    "notes": h.notes,
                }
                for h in self.aggregator_hints
            ],
            "stats": {
                "total": len(self._entries),
                "available": len(self.available_entries()),
                "multimodal": len(self.multimodal_entries()),
                # PR-4: config-authority-driven stats
                "candidate_eligible": len(self.candidate_pool_entries()),
                "enabled": len(self.enabled_entries()),
                "disabled": len(self.disabled_entries()),
                "unconfigured": len(self.unconfigured_entries()),
                "categories": {
                    cat.value: len(self.by_category(cat))
                    for cat in ProviderCategory
                },
            },
        }

    def __repr__(self) -> str:
        return (
            f"<ProviderInventory total={len(self)} "
            f"available={len(self.available_entries())} "
            f"candidate_eligible={len(self.candidate_pool_entries())} "
            f"multimodal={len(self.multimodal_entries())}>"
        )
