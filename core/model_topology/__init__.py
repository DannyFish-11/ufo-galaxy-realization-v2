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

See ``docs/MODEL_TOPOLOGY_BRIDGE.md`` for the full design rationale.
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
]
