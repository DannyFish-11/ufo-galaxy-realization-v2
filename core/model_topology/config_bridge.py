"""
core/model_topology/config_bridge.py
======================================
ConfigBridge – translates dashboard-era provider/router/node-API concepts
into the normalized ``NormalizedTopologyEntry`` objects used by the V2 model
topology layer.

WHAT THIS DOES
--------------
1. Accepts ``LegacyLLMProviderSnapshot`` objects (mirroring the existing
   ``/api/v1/llm/providers`` JSON) and produces ``NormalizedTopologyEntry``.
2. Accepts ``LegacyNodeAPIEntry`` objects and produces supplementary
   ``NormalizedTopologyEntry`` objects for node-backed providers.
3. Assembles a ``ProviderInventory`` from a batch of snapshots.
4. Extracts ``AggregatorRouterHint`` objects that represent the logical
   IntentRouter / ExecutionPlanner / AgentFactory / Multi-LLM-Router roles
   described in ``dashboard/README.md``.

WHAT THIS DOES NOT DO
---------------------
- It does NOT import or depend on the dashboard FastAPI app.
- It does NOT render any UI.
- It does NOT modify any existing routing/LLM manager code.

DESIGN
------
ConfigBridge is a pure translation layer.  All methods are stateless with
respect to live runtime state; they work only on the snapshot types defined
in ``legacy_dashboard_schema.py``.

Later V2 PRs will consume the ``ProviderInventory`` produced here and feed it
into the topology core / routing policy / projection surface.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Sequence

from .legacy_dashboard_schema import (
    LegacyLLMProviderSnapshot,
    LegacyNodeAPIEntry,
    LegacyProviderHealthDetail,
    LegacyRouterSemantics,
)
from .provider_inventory import ProviderInventory, ProviderInventoryEntry
from .topology_types import (
    AggregatorKind,
    AggregatorRouterHint,
    AvailabilityStatus,
    ModalityCapability,
    ModelIdentity,
    NormalizedTopologyEntry,
    ProviderCategory,
    ProviderIdentity,
    ScoringProfile,
    TopologyRole,
)

logger = logging.getLogger("Galaxy.ModelTopology.ConfigBridge")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Maps dashboard-era node categories to ProviderCategory enum values.
_NODE_CATEGORY_MAP: Dict[str, ProviderCategory] = {
    "llm": ProviderCategory.ONEAPI,
    "local_llm": ProviderCategory.LOCAL,
    "vision": ProviderCategory.NODE_BACKED,
    "code": ProviderCategory.NODE_BACKED,
    "translation": ProviderCategory.TOOLS,
    "data": ProviderCategory.TOOLS,
    "search": ProviderCategory.TOOLS,
    "hardware": ProviderCategory.TOOLS,
    "media": ProviderCategory.TOOLS,
}

# Role hints automatically assigned to native-multimodal providers.
_MULTIMODAL_ROLE_HINTS: List[TopologyRole] = [
    TopologyRole.MULTIMODAL_CORE,
    TopologyRole.GENERAL,
]

# Role hints for fast (speed_score >= 9) providers.
_FAST_ROLE_HINTS: List[TopologyRole] = [
    TopologyRole.EXECUTION,
]

# Role hints for high-quality (quality_score >= 10) providers.
_QUALITY_ROLE_HINTS: List[TopologyRole] = [
    TopologyRole.REASONING,
]

# Role hints for local providers.
_LOCAL_ROLE_HINTS: List[TopologyRole] = [
    TopologyRole.EXECUTION,
    TopologyRole.MEMORY,
]


def _derive_role_hints(
    entry: LegacyLLMProviderSnapshot,
    category: ProviderCategory,
) -> List[TopologyRole]:
    """Derive topology role hints from dashboard-era attributes.

    Rules (additive, no single role assigned twice):
    - native multimodal → MULTIMODAL_CORE + GENERAL
    - quality_score >= 10 → REASONING (overrides GENERAL if already multimodal)
    - speed_score >= 9   → EXECUTION
    - LOCAL category     → EXECUTION + MEMORY
    - ONEAPI category    → ROUTING (it acts as an aggregator)
    """
    hints: List[TopologyRole] = []
    seen = set()

    def _add(role: TopologyRole) -> None:
        if role not in seen:
            hints.append(role)
            seen.add(role)

    if entry.multimodal:
        for r in _MULTIMODAL_ROLE_HINTS:
            _add(r)

    if entry.quality_score >= 10:
        for r in _QUALITY_ROLE_HINTS:
            _add(r)

    if entry.speed_score >= 9:
        for r in _FAST_ROLE_HINTS:
            _add(r)

    if category == ProviderCategory.LOCAL:
        for r in _LOCAL_ROLE_HINTS:
            _add(r)

    if category == ProviderCategory.ONEAPI:
        _add(TopologyRole.ROUTING)

    if not hints:
        _add(TopologyRole.GENERAL)

    return hints


# ---------------------------------------------------------------------------
# ConfigBridge
# ---------------------------------------------------------------------------


class ConfigBridge:
    """Translates dashboard-era provider/node snapshots into the normalized
    topology layer used by V2 core modules.

    Usage::

        bridge = ConfigBridge()
        snapshots = [LegacyLLMProviderSnapshot.from_dict(d) for d in raw_list]
        inventory = bridge.build_inventory(snapshots)
    """

    # ------------------------------------------------------------------
    # Single-entry translation
    # ------------------------------------------------------------------

    def bridge_provider(
        self,
        snapshot: LegacyLLMProviderSnapshot,
        health: Optional[LegacyProviderHealthDetail] = None,
    ) -> NormalizedTopologyEntry:
        """Translate one ``LegacyLLMProviderSnapshot`` → ``NormalizedTopologyEntry``.

        Preserves: provider identity, model identity, multimodal flag, speed
        and quality scores, availability and env-key requirements, and derives
        topology role hints.

        Args:
            snapshot: Dashboard-era provider snapshot.
            health:   Optional runtime health detail (used only to annotate
                      ``supports_vision`` when the health snapshot contradicts
                      the static multimodal flag).
        """
        provider_id = snapshot.provider

        # Provider identity
        provider = ProviderIdentity(
            provider_id=provider_id,
            display_name=provider_id.capitalize(),
        )

        # Model identity
        alternatives = [m for m in snapshot.models if m != snapshot.model]
        model = ModelIdentity(
            model_id=snapshot.model or f"{provider_id}-default",
            provider_id=provider_id,
            alternatives=alternatives,
        )

        # Modality: start from static multimodal flag, refine with health
        supports_vision = snapshot.multimodal
        if health and health.supports_vision:
            supports_vision = True
        modality = ModalityCapability(
            native_multimodal=snapshot.multimodal,
            supports_vision=supports_vision,
            supports_audio=False,
            supports_video=False,
        )

        # Scoring: clamp to [1, 10]
        speed = max(1, min(10, snapshot.speed_score))
        quality = max(1, min(10, snapshot.quality_score))
        scoring = ScoringProfile(speed_score=speed, quality_score=quality)

        # Availability
        availability = AvailabilityStatus.from_dashboard_entry(
            available=snapshot.available,
            missing_env_key=snapshot.missing_env_key,
            env_keys=snapshot.env_keys or (
                [snapshot.missing_env_key] if snapshot.missing_env_key else []
            ),
        )

        # Category: direct unless the snapshot carries a hint
        category = ProviderCategory.DIRECT

        # Role hints
        role_hints = _derive_role_hints(snapshot, category)

        return NormalizedTopologyEntry(
            provider=provider,
            model=model,
            modality=modality,
            scoring=scoring,
            availability=availability,
            category=category,
            role_hints=role_hints,
            raw_metadata=snapshot.to_dict(),
        )

    def bridge_node_api(
        self,
        node_entry: LegacyNodeAPIEntry,
    ) -> NormalizedTopologyEntry:
        """Translate one ``LegacyNodeAPIEntry`` → ``NormalizedTopologyEntry``.

        Node-API entries describe Galaxy node services (OCR, OneAPI, local LLM,
        etc.) that are not traditional LLM providers.  The bridge maps them
        into the topology so downstream routing can treat them as addressable
        supply slots.
        """
        node_id = node_entry.node_id
        provider_id = f"node_{node_id}"

        provider = ProviderIdentity(
            provider_id=provider_id,
            display_name=node_entry.name,
        )

        model = ModelIdentity(
            model_id=f"{provider_id}/default",
            provider_id=provider_id,
            alternatives=[],
        )

        # Multimodal is implied for vision-category nodes
        is_vision = "vision" in node_entry.category.lower()
        modality = ModalityCapability(
            native_multimodal=is_vision,
            supports_vision=is_vision,
            supports_audio=False,
            supports_video=False,
        )

        scoring = ScoringProfile(speed_score=7, quality_score=7)

        availability = AvailabilityStatus(
            available=node_entry.all_configured,
            missing_env_key=(
                node_entry.keys[0].env_var
                if node_entry.keys and not node_entry.all_configured
                else None
            ),
            all_env_keys=[k.env_var for k in node_entry.keys],
        )

        category = _NODE_CATEGORY_MAP.get(node_entry.category, ProviderCategory.TOOLS)

        # Role hints
        role_hints: List[TopologyRole] = []
        if category == ProviderCategory.LOCAL:
            role_hints = [TopologyRole.EXECUTION, TopologyRole.MEMORY]
        elif category == ProviderCategory.ONEAPI:
            role_hints = [TopologyRole.ROUTING]
        elif is_vision:
            role_hints = [TopologyRole.MULTIMODAL_CORE]
        else:
            role_hints = [TopologyRole.GENERAL]

        return NormalizedTopologyEntry(
            provider=provider,
            model=model,
            modality=modality,
            scoring=scoring,
            availability=availability,
            category=category,
            role_hints=role_hints,
            raw_metadata={
                "node_id": node_id,
                "name": node_entry.name,
                "category": node_entry.category,
                "all_configured": node_entry.all_configured,
            },
        )

    # ------------------------------------------------------------------
    # Inventory builder
    # ------------------------------------------------------------------

    def build_inventory(
        self,
        provider_snapshots: Sequence[LegacyLLMProviderSnapshot],
        node_entries: Optional[Sequence[LegacyNodeAPIEntry]] = None,
        health_map: Optional[Dict[str, LegacyProviderHealthDetail]] = None,
        router_semantics: Optional[LegacyRouterSemantics] = None,
    ) -> ProviderInventory:
        """Build a full ``ProviderInventory`` from dashboard-era input.

        Args:
            provider_snapshots: LLM provider snapshots (required).
            node_entries:       Node-API entries (optional, augments inventory).
            health_map:         provider_id → health detail (optional).
            router_semantics:   Dashboard router role descriptor (optional,
                                used to generate aggregator hints).

        Returns:
            A populated ``ProviderInventory`` ready for V2 topology consumers.
        """
        health_map = health_map or {}
        entries: List[ProviderInventoryEntry] = []

        for snap in provider_snapshots:
            health = health_map.get(snap.provider)
            try:
                top_entry = self.bridge_provider(snap, health=health)
            except Exception as exc:
                logger.warning(
                    "ConfigBridge: skipping provider '%s' due to error: %s",
                    snap.provider, exc,
                )
                continue

            inv_entry = ProviderInventoryEntry(entry=top_entry)
            if health:
                inv_entry.health_status = health.status
                inv_entry.latency_avg_ms = health.latency_avg_ms
                inv_entry.error_rate = health.error_rate
            entries.append(inv_entry)

        for node_entry in (node_entries or []):
            try:
                top_entry = self.bridge_node_api(node_entry)
            except Exception as exc:
                logger.warning(
                    "ConfigBridge: skipping node '%s' due to error: %s",
                    node_entry.node_id, exc,
                )
                continue
            entries.append(ProviderInventoryEntry(entry=top_entry))

        # Aggregator hints
        agg_hints = self.extract_aggregator_hints(
            entries=[e.entry for e in entries],
            router_semantics=router_semantics,
        )

        inventory = ProviderInventory(entries=entries, aggregator_hints=agg_hints)
        logger.info(
            "ConfigBridge: inventory built – %s",
            inventory,
        )
        return inventory

    # ------------------------------------------------------------------
    # Aggregator / router semantic hint extraction
    # ------------------------------------------------------------------

    def extract_aggregator_hints(
        self,
        entries: Iterable[NormalizedTopologyEntry],
        router_semantics: Optional[LegacyRouterSemantics] = None,
    ) -> List[AggregatorRouterHint]:
        """Extract aggregator / router semantic hints from a set of topology
        entries (and an optional ``LegacyRouterSemantics`` descriptor).

        The hints are derived from:
        1. Role hints already present on each entry (primary source).
        2. Explicit provider lists in ``router_semantics`` (if provided).

        These hints are *not* wired into runtime routing in this PR; they give
        the topology core PR a stable, representable contract to build on.
        """
        entries_list = list(entries)

        # Build per-kind candidate lists from role hints
        kind_candidates: Dict[AggregatorKind, List[str]] = {k: [] for k in AggregatorKind}

        for e in entries_list:
            pid = e.provider.provider_id
            if TopologyRole.MULTIMODAL_CORE in e.role_hints:
                kind_candidates[AggregatorKind.MULTIMODAL_CORE_AGGREGATOR].append(pid)
            if TopologyRole.REASONING in e.role_hints:
                kind_candidates[AggregatorKind.REASONING_AGGREGATOR].append(pid)
            if TopologyRole.EXECUTION in e.role_hints:
                kind_candidates[AggregatorKind.EXECUTION_AGGREGATOR].append(pid)
            if TopologyRole.MEMORY in e.role_hints:
                kind_candidates[AggregatorKind.MEMORY_AGGREGATOR].append(pid)
            if TopologyRole.ROUTING in e.role_hints:
                kind_candidates[AggregatorKind.ROUTE_ARBITER].append(pid)
            if TopologyRole.CROSS_DEVICE in e.role_hints:
                kind_candidates[AggregatorKind.CROSS_DEVICE_AGGREGATOR].append(pid)

        # Merge explicit router_semantics overrides (union)
        if router_semantics:
            for pid in router_semantics.multi_llm_router_providers:
                if pid not in kind_candidates[AggregatorKind.ROUTE_ARBITER]:
                    kind_candidates[AggregatorKind.ROUTE_ARBITER].append(pid)
            for pid in router_semantics.agent_factory_providers:
                if pid not in kind_candidates[AggregatorKind.EXECUTION_AGGREGATOR]:
                    kind_candidates[AggregatorKind.EXECUTION_AGGREGATOR].append(pid)
            for pid in router_semantics.memory_providers:
                if pid not in kind_candidates[AggregatorKind.MEMORY_AGGREGATOR]:
                    kind_candidates[AggregatorKind.MEMORY_AGGREGATOR].append(pid)
            for pid in router_semantics.cross_device_providers:
                if pid not in kind_candidates[AggregatorKind.CROSS_DEVICE_AGGREGATOR]:
                    kind_candidates[AggregatorKind.CROSS_DEVICE_AGGREGATOR].append(pid)

        _LABELS = {
            AggregatorKind.MULTIMODAL_CORE_AGGREGATOR: "Multimodal Core Aggregator",
            AggregatorKind.REASONING_AGGREGATOR: "Reasoning Aggregator",
            AggregatorKind.EXECUTION_AGGREGATOR: "Execution Aggregator",
            AggregatorKind.MEMORY_AGGREGATOR: "Memory Aggregator",
            AggregatorKind.ROUTE_ARBITER: "Route Arbiter",
            AggregatorKind.CROSS_DEVICE_AGGREGATOR: "Cross-Device Aggregator",
        }

        hints = [
            AggregatorRouterHint(
                kind=kind,
                label=_LABELS[kind],
                candidate_provider_ids=candidates,
                notes=(
                    "Derived from legacy dashboard IntentRouter/ExecutionPlanner/AgentFactory "
                    "semantics and topology role hints."
                ),
            )
            for kind, candidates in kind_candidates.items()
        ]
        return hints
