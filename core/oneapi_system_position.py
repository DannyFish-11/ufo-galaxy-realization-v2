#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/oneapi_system_position.py
================================
Sentinel and registry module formalising OneAPI's canonical system position
as a **system-level aggregator integration layer** in the Galaxy architecture.

Architecture position
---------------------
OneAPI is *not* a direct/native-multimodal top-layer provider.  It is an
external aggregator that wraps multiple upstream LLM vendors behind a single
OpenAI-compatible endpoint.  Its configuration and state have **system-wide
effect** — they feed into the provider/model source pool, routing candidate
pool, projection-facing status, and downstream status-board semantics.

Canonical position in the model supply topology::

    ┌──────────────────────────────────────────────────────────────────┐
    │  Direct / Native-Multimodal Provider Layer  (top model layer)   │
    │  OpenAI  │  Anthropic  │  Gemini  │  xAI  │  …direct vendors   │
    └──────────────────────────────────────────────────────────────────┘
                                  ▲
              primary/main model topology anchored here
                                  │
    ┌──────────────────────────────────────────────────────────────────┐
    │  OneAPI Aggregator Integration Layer  (separate lower row)      │
    │  nodes/Node_01_OneAPI — external aggregator gateway             │
    └──────────────────────────────────────────────────────────────────┘

See ``docs/ONEAPI_SYSTEM_POSITION.md`` for the full canonical definition.

Exported symbols
----------------
ONEAPI_SYSTEM_LAYER
    Sentinel string identifying OneAPI's layer in the topology.

ONEAPI_INTEGRATION_REGISTRY
    Frozen registry mapping integration-dimension keys to their canonical
    descriptions.  Used by guardrail tests to assert that all required
    system-wide effect dimensions are documented.

OneAPIIntegrationDimension
    Enum of system-wide dimensions that OneAPI configuration/state must
    influence.

build_oneapi_integration_summary()
    Builder that returns a dict snapshot of the current integration position
    (used by projection consumers and diagnostics).

get_oneapi_integration_registry() / reset_oneapi_integration_registry()
    Singleton accessor and test-reset helpers.
"""

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Dict, FrozenSet, Optional

logger = logging.getLogger("Galaxy.OneAPISystemPosition")

__all__ = [
    "ONEAPI_SYSTEM_LAYER",
    "ONEAPI_NODE_PATH",
    "ONEAPI_PROVIDER_CATEGORY_VALUE",
    "OneAPIIntegrationDimension",
    "OneAPIIntegrationEntry",
    "ONEAPI_INTEGRATION_REGISTRY",
    "OneAPIIntegrationSnapshot",
    "build_oneapi_integration_summary",
    "get_oneapi_integration_registry",
    "reset_oneapi_integration_registry",
]

# ---------------------------------------------------------------------------
# Sentinel constants
# ---------------------------------------------------------------------------

#: Sentinel identifying OneAPI's layer in the model supply topology.
#:
#: Downstream consumers (projection builders, diagnostics, guardrail tooling)
#: can compare against this value to assert that OneAPI is treated as an
#: aggregator integration layer rather than a top-layer direct provider.
ONEAPI_SYSTEM_LAYER: str = "aggregator_integration"

#: Canonical filesystem path for the OneAPI node service.
ONEAPI_NODE_PATH: str = "nodes/Node_01_OneAPI"

#: The ``ProviderCategory`` enum value string used throughout
#: ``core/model_topology/`` to classify OneAPI entries.
ONEAPI_PROVIDER_CATEGORY_VALUE: str = "oneapi"

#: Cross-reference: the canonical routing authority module.
#: OneAPI participates in routing via ``TopologyRouter``; it is *not* a
#: separate routing authority.
_ROUTING_AUTHORITY_REF: str = (
    "core.model_topology.topology_router.TopologyRouter"
)


# ---------------------------------------------------------------------------
# Integration dimensions
# ---------------------------------------------------------------------------


class OneAPIIntegrationDimension(str, Enum):
    """System-wide dimensions that OneAPI configuration/state must influence.

    Exhaustive list of the integration boundaries formalised in
    ``docs/ONEAPI_SYSTEM_POSITION.md``.  Each dimension is registered in
    :data:`ONEAPI_INTEGRATION_REGISTRY` with a canonical description.
    """

    PROVIDER_SOURCE_AVAILABILITY = "provider_source_availability"
    """OneAPI config (URL + key) must control whether the provider enters the
    candidate pool.  When not configured it must be *absent*, not merely
    disabled."""

    ROUTING_CANDIDATE_POOL = "routing_candidate_pool"
    """OneAPI must participate in the topology-router candidate graph whenever
    it is configured, with category ``ProviderCategory.ONEAPI`` and role
    ``TopologyRole.ROUTING``."""

    PROJECTION_FACING_STATUS = "projection_facing_status"
    """OneAPI availability and routing participation must surface via
    ``DesktopStatusProjection`` (``contracts/desktop_status_projection.py``)
    so that the right-side desktop status board can display it."""

    STATUS_BOARD_LOWER_ROW = "status_board_lower_row"
    """On the right-side desktop status board, OneAPI must appear as a
    *separate lower-layer row*, distinct from direct/native-multimodal
    providers.  It must not be interleaved with the top provider cluster."""

    CONFIG_HAS_GLOBAL_EFFECT = "config_has_global_effect"
    """OneAPI configuration (base URL, API key) must propagate globally —
    updating the provider registry, routing graph, and projection.  There is
    no concept of OneAPI config that applies only to a single UI surface."""


# ---------------------------------------------------------------------------
# Integration entry dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class OneAPIIntegrationEntry:
    """Metadata record for a single OneAPI integration dimension.

    Attributes
    ----------
    dimension:
        The :class:`OneAPIIntegrationDimension` this entry describes.
    description:
        Human-readable description of what this dimension means and where
        it is implemented.
    canonical_module:
        Primary module or file that implements/owns this dimension.
    canonical_doc:
        Primary documentation reference for this dimension.
    """

    dimension: OneAPIIntegrationDimension
    description: str
    canonical_module: str
    canonical_doc: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "dimension": self.dimension.value,
            "description": self.description,
            "canonical_module": self.canonical_module,
            "canonical_doc": self.canonical_doc,
        }


# ---------------------------------------------------------------------------
# Canonical integration registry
# ---------------------------------------------------------------------------

#: Frozen mapping of :class:`OneAPIIntegrationDimension` → entry.
#:
#: This registry is the machine-readable counterpart to
#: ``docs/ONEAPI_SYSTEM_POSITION.md`` section 4 ("System-Wide Effect
#: Semantics").  Guardrail tests iterate over this registry to ensure that
#: all required dimensions are documented and that the sentinel/description
#: strings are internally consistent.
ONEAPI_INTEGRATION_REGISTRY: Dict[
    OneAPIIntegrationDimension, OneAPIIntegrationEntry
] = {
    OneAPIIntegrationDimension.PROVIDER_SOURCE_AVAILABILITY: OneAPIIntegrationEntry(
        dimension=OneAPIIntegrationDimension.PROVIDER_SOURCE_AVAILABILITY,
        description=(
            "When ONEAPI_BASE_URL and ONEAPI_API_KEY are configured, the "
            "'oneapi' provider is registered in ProviderInventory with "
            "category ProviderCategory.ONEAPI.  When not configured it must "
            "be absent from the candidate pool."
        ),
        canonical_module="core.multi_llm_router.MultiLLMRouter._discover_providers",
        canonical_doc="docs/ONEAPI_SYSTEM_POSITION.md",
    ),
    OneAPIIntegrationDimension.ROUTING_CANDIDATE_POOL: OneAPIIntegrationEntry(
        dimension=OneAPIIntegrationDimension.ROUTING_CANDIDATE_POOL,
        description=(
            "ProviderCategory.ONEAPI entries participate in the "
            "TopologyRouter candidate graph with TopologyRole.ROUTING.  "
            "OneAPI is NOT a top-layer native-multimodal provider."
        ),
        canonical_module="core.model_topology.topology_router.TopologyRouter",
        canonical_doc="docs/MODEL_ROUTING_AUTHORITY.md",
    ),
    OneAPIIntegrationDimension.PROJECTION_FACING_STATUS: OneAPIIntegrationEntry(
        dimension=OneAPIIntegrationDimension.PROJECTION_FACING_STATUS,
        description=(
            "OneAPI availability and routing participation surfaces via "
            "DesktopStatusProjection.model_routing so that the right-side "
            "desktop status board can display aggregator state."
        ),
        canonical_module="contracts.desktop_status_projection.ModelRoutingProjection",
        canonical_doc="docs/ONEAPI_SYSTEM_POSITION.md",
    ),
    OneAPIIntegrationDimension.STATUS_BOARD_LOWER_ROW: OneAPIIntegrationEntry(
        dimension=OneAPIIntegrationDimension.STATUS_BOARD_LOWER_ROW,
        description=(
            "On the right-side desktop status board, OneAPI must render as a "
            "separate lower-layer row distinct from the top-layer "
            "direct/native-multimodal provider cluster."
        ),
        canonical_module="status_board_v2",
        canonical_doc="docs/DESKTOP_DISPLAY_BOUNDARIES.md",
    ),
    OneAPIIntegrationDimension.CONFIG_HAS_GLOBAL_EFFECT: OneAPIIntegrationEntry(
        dimension=OneAPIIntegrationDimension.CONFIG_HAS_GLOBAL_EFFECT,
        description=(
            "OneAPI config (ONEAPI_BASE_URL / ONEAPI_API_KEY) propagates "
            "system-wide: updates the provider registry, routing graph, and "
            "projection.  It is not a dashboard-local or node-local config."
        ),
        canonical_module="nodes.Node_01_OneAPI.main",
        canonical_doc="docs/ONEAPI_SYSTEM_POSITION.md",
    ),
}


# ---------------------------------------------------------------------------
# Integration snapshot
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=False)
class OneAPIIntegrationSnapshot:
    """Lightweight snapshot of the OneAPI integration position.

    Returned by :func:`build_oneapi_integration_summary`.

    Attributes
    ----------
    system_layer:
        Always :data:`ONEAPI_SYSTEM_LAYER` (``"aggregator_integration"``).
    node_path:
        Always :data:`ONEAPI_NODE_PATH`.
    provider_category_value:
        Always :data:`ONEAPI_PROVIDER_CATEGORY_VALUE` (``"oneapi"``).
    registered_dimensions:
        Frozenset of :class:`OneAPIIntegrationDimension` values present in the
        registry.  Tests assert this matches the full enum.
    routing_authority_ref:
        Cross-reference to the canonical routing authority module.  OneAPI
        participates in routing but does *not* own routing authority.
    """

    system_layer: str
    node_path: str
    provider_category_value: str
    registered_dimensions: FrozenSet[str]
    routing_authority_ref: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "system_layer": self.system_layer,
            "node_path": self.node_path,
            "provider_category_value": self.provider_category_value,
            "registered_dimensions": sorted(self.registered_dimensions),
            "routing_authority_ref": self.routing_authority_ref,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_oneapi_integration_summary() -> OneAPIIntegrationSnapshot:
    """Build a snapshot describing OneAPI's canonical system position.

    This is a pure builder (no side effects).  It is safe to call from
    projection compilers, diagnostics, and guardrail tests.

    Returns
    -------
    OneAPIIntegrationSnapshot
        Snapshot of the OneAPI integration position.
    """
    return OneAPIIntegrationSnapshot(
        system_layer=ONEAPI_SYSTEM_LAYER,
        node_path=ONEAPI_NODE_PATH,
        provider_category_value=ONEAPI_PROVIDER_CATEGORY_VALUE,
        registered_dimensions=frozenset(
            dim.value for dim in ONEAPI_INTEGRATION_REGISTRY
        ),
        routing_authority_ref=_ROUTING_AUTHORITY_REF,
    )


# ---------------------------------------------------------------------------
# Singleton accessor / test helpers
# ---------------------------------------------------------------------------

_REGISTRY_INSTANCE: Optional[
    Dict[OneAPIIntegrationDimension, OneAPIIntegrationEntry]
] = None


def get_oneapi_integration_registry() -> (
    Dict[OneAPIIntegrationDimension, OneAPIIntegrationEntry]
):
    """Return the singleton integration registry.

    The first call returns a reference to :data:`ONEAPI_INTEGRATION_REGISTRY`.
    Subsequent calls return the same reference.  Call
    :func:`reset_oneapi_integration_registry` between test cases if needed.
    """
    global _REGISTRY_INSTANCE
    if _REGISTRY_INSTANCE is None:
        _REGISTRY_INSTANCE = ONEAPI_INTEGRATION_REGISTRY
    return _REGISTRY_INSTANCE


def reset_oneapi_integration_registry() -> None:
    """Reset the singleton registry reference.

    Intended for use in unit tests that need a clean state.
    """
    global _REGISTRY_INSTANCE
    _REGISTRY_INSTANCE = None
