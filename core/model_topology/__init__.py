"""
core/model_topology/__init__.py
================================
Public surface of the V2 Model Topology Bridge package.

This package provides the bridge layer between the existing dashboard-era
provider/router/node concepts and the new V2 model-topology-ready schema.

Quick start::

    from core.model_topology import (
        ConfigBridge,
        LegacyLLMProviderSnapshot,
        LegacyNodeAPIEntry,
        NormalizedTopologyEntry,
        ProviderInventory,
        ProviderCategory,
        TopologyRole,
        AggregatorKind,
        AggregatorRouterHint,
    )

    bridge = ConfigBridge()
    snapshot = LegacyLLMProviderSnapshot.from_dict({
        "provider": "openai",
        "model": "gpt-5.4",
        "models": ["gpt-5.4", "gpt-4o"],
        "speed_score": 8,
        "quality_score": 9,
        "available": True,
        "multimodal": True,
    })
    entry = bridge.bridge_provider(snapshot)

See ``docs/MODEL_TOPOLOGY_BRIDGE.md`` for the bridge design rationale.
See ``docs/MODEL_SUPPLY_TOPOLOGY.md`` for the topology core design.
"""

from .config_bridge import ConfigBridge
from .legacy_dashboard_schema import (
    LegacyLLMProviderSnapshot,
    LegacyNodeAPIEntry,
    LegacyNodeAPIKeySpec,
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

# --- Topology core (PR-2) ---
from .model_node import EdgeKind, LocalityHint, ModelNode, node_from_entry
from .model_supply_graph import GraphEdge, ModelSupplyGraph
from .model_weight_field import ModelWeightField, apply_weight_fields, compute_weight_field
from .routing_policy import PolicyConfig
from .topology_router import TopologyRoutePlan, TopologyRouter

# --- Canonical model supply state (PR-18) ---
from .canonical_model_supply_state import (
    CanonicalModelSupplyState,
    NativeMultimodalCapability,
    NativeMultimodalCapabilityRegistry,
    ProviderHealthStatus,
    ProviderLocalityClass,
    ProviderSupplyRecord,
    build_canonical_model_supply_state,
    build_canonical_model_supply_state_from_router,
)

__all__ = [
    # Bridge
    "ConfigBridge",
    # Legacy schema mirrors
    "LegacyLLMProviderSnapshot",
    "LegacyNodeAPIEntry",
    "LegacyNodeAPIKeySpec",
    "LegacyProviderHealthDetail",
    "LegacyRouterSemantics",
    # Inventory
    "ProviderInventory",
    "ProviderInventoryEntry",
    # Normalized topology types
    "AggregatorKind",
    "AggregatorRouterHint",
    "AvailabilityStatus",
    "ModalityCapability",
    "ModelIdentity",
    "NormalizedTopologyEntry",
    "ProviderCategory",
    "ProviderIdentity",
    "ScoringProfile",
    "TopologyRole",
    # Topology core (PR-2)
    "EdgeKind",
    "GraphEdge",
    "LocalityHint",
    "ModelNode",
    "ModelSupplyGraph",
    "ModelWeightField",
    "PolicyConfig",
    "TopologyRoutePlan",
    "TopologyRouter",
    "apply_weight_fields",
    "compute_weight_field",
    "node_from_entry",
    # Canonical model supply state (PR-18)
    "CanonicalModelSupplyState",
    "NativeMultimodalCapability",
    "NativeMultimodalCapabilityRegistry",
    "ProviderHealthStatus",
    "ProviderLocalityClass",
    "ProviderSupplyRecord",
    "build_canonical_model_supply_state",
    "build_canonical_model_supply_state_from_router",
]
