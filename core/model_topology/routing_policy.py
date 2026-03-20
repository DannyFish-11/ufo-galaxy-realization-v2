"""
core/model_topology/routing_policy.py
========================================
Routing policy rules that map (TriStatePhase, RuntimeDomain) to
node-selection preferences.

The policy layer is intentionally *simple and deterministic*.  It does not
perform probabilistic sampling or ML-based ranking; it produces a ranked
preference list from the model supply graph by applying weight fields and
enforcing the following hard rules:

  1. Native multimodal has highest base priority (always anchors primary slot).
  2. SILENT:   emphasize multimodal + perception; minimize execution roles.
  3. LIMINAL:  increase reasoning + routing aggregators; keep multimodal anchor.
  4. MANIFEST: increase execution roles; allow cross-device specialists when
               RuntimeDomain.CROSS_DEVICE.

All ordering is deterministic: ties are broken by node_id lexicographic order.

No UI semantics; no dashboard imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.continuum.types import RuntimeDomain, TriStatePhase

from .model_node import ModelNode
from .model_supply_graph import ModelSupplyGraph
from .model_weight_field import ModelWeightField, apply_weight_fields
from .topology_types import TopologyRole

logger = logging.getLogger("Galaxy.ModelTopology.RoutingPolicy")


# ---------------------------------------------------------------------------
# PolicyConfig — static configuration for the policy engine
# ---------------------------------------------------------------------------


@dataclass
class PolicyConfig:
    """Tuneable parameters for the routing policy.

    ``max_support_models``   — maximum number of support models included
                               in the route plan.
    ``require_multimodal_primary`` — if True (default) the primary model
                               MUST be native multimodal in silent/liminal.
    ``allow_unavailable_fallback`` — if True, consider unavailable nodes as
                               last-resort fallbacks.
    """

    max_support_models: int = 3
    require_multimodal_primary: bool = True
    allow_unavailable_fallback: bool = False


_DEFAULT_POLICY_CONFIG = PolicyConfig()


# ---------------------------------------------------------------------------
# PhasePolicy — the high-level selection strategy per phase
# ---------------------------------------------------------------------------


def _select_primary_node(
    graph: ModelSupplyGraph,
    phase: TriStatePhase,
    domain: RuntimeDomain,
    config: PolicyConfig,
) -> Optional[Tuple[ModelNode, ModelWeightField]]:
    """Select the primary model node for the given phase/domain.

    Rules (in priority order):
    1. In SILENT or LIMINAL: must be native multimodal (if
       ``config.require_multimodal_primary`` is True and any MM node exists).
    2. In MANIFEST + CROSS_DEVICE: cross-device specialists are eligible as
       primary (but multimodal core still preferred if available).
    3. Otherwise: highest combined_weight available node.
    """
    available = graph.available_nodes()
    if not available:
        if config.allow_unavailable_fallback:
            available = sorted(
                graph.all_nodes(), key=lambda n: (-n.base_weight, n.node_id)
            )
        else:
            return None

    weighted_available = apply_weight_fields(available, phase, domain)

    if phase in (TriStatePhase.SILENT, TriStatePhase.LIMINAL):
        if config.require_multimodal_primary:
            mm_pairs = [
                (n, wf) for n, wf in weighted_available if n.is_multimodal_native
            ]
            if mm_pairs:
                return mm_pairs[0]

    # For MANIFEST or when no MM node found:
    return weighted_available[0] if weighted_available else None


def _select_support_nodes(
    graph: ModelSupplyGraph,
    phase: TriStatePhase,
    domain: RuntimeDomain,
    primary_node_id: str,
    config: PolicyConfig,
) -> List[Tuple[ModelNode, ModelWeightField]]:
    """Select support model nodes (excluding the primary)."""
    available = graph.available_nodes()
    candidates = [n for n in available if n.node_id != primary_node_id]

    weighted = apply_weight_fields(candidates, phase, domain)

    # In MANIFEST + CROSS_DEVICE: include cross-device specialists explicitly
    if phase == TriStatePhase.MANIFEST and domain == RuntimeDomain.CROSS_DEVICE:
        cd_nodes = {n.node_id for n in graph.cross_device_capable_nodes()}
        # Ensure cross-device nodes appear in the support list if not already
        extra = [
            (n, wf)
            for n, wf in weighted
            if n.node_id in cd_nodes
        ]
        rest = [(n, wf) for n, wf in weighted if n.node_id not in cd_nodes]
        weighted = extra + rest

    return weighted[: config.max_support_models]


# ---------------------------------------------------------------------------
# Route reason builder
# ---------------------------------------------------------------------------


def _build_route_reason(
    phase: TriStatePhase,
    domain: RuntimeDomain,
    primary: Optional[ModelNode],
    support_count: int,
) -> str:
    if primary is None:
        return f"no_available_node phase={phase.value} domain={domain.value}"

    mm = "multimodal_anchor" if primary.is_multimodal_native else "non_multimodal"
    return (
        f"phase={phase.value} domain={domain.value} "
        f"primary={primary.node_id} primary_role={primary.topology_role.value} "
        f"primary_type={mm} support_count={support_count}"
    )
