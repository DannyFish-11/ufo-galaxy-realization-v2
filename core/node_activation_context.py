#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_activation_context.py
==================================
PR-15 (node track): Canonical Node Activation Context Layer.

This module is the **canonical authority** for node activation-context
evaluation — runtime readiness classification that enriches canonical
invocation governance with policy-aware readiness semantics.

Background
----------
PR-5 through PR-14 (node track) established the canonical runtime foundation:

- Canonical runtime registry (:mod:`core.nodes.node_fabric_registry`)
- Governance eligibility at invocation time
  (:mod:`core.node_invocation_governance`)
- Cognition-oriented activation above the substrate
  (:mod:`core.node_cognition_activation`)

The invocation governance path (PR-11) enforces lifecycle/health/class rules
at execution time.  However, it does not yet account for a node's
**activation context** — whether the node is intrinsically always ready,
whether it requires topology connectivity, whether it must be explicitly
requested, or whether it is administratively dormant.

Purpose of this module
-----------------------
This module introduces the **activation-context layer**: a set of runtime
readiness classifications attached to nodes that are evaluated *inside*
:func:`~core.node_invocation_governance.evaluate_invocation_governance`.

The activation-context check is an **enrichment of the existing canonical
invocation-governance path**, not a new parallel gate or competing authority.

Design
------
1. :class:`NodeActivationPolicyKind` — runtime readiness policy for a node:
   - ``ALWAYS_ACTIVE`` — node is unconditionally ready for canonical invocation.
   - ``TOPOLOGY_CONDITIONAL`` — node readiness depends on optional topology
     connectivity; if the topology runtime indicates the node is unreachable,
     the node is blocked.
   - ``DEMAND_ACTIVATED`` — node requires an explicit demand/request context to
     be considered ready; not ready for ambient invocations.
   - ``DORMANT`` — node is administratively dormant and cannot be canonically
     invoked regardless of governance state.

2. :class:`NodeActivationReadinessDecision` — structured result of a single
   activation-context evaluation.  Carries the policy kind, readiness outcome,
   denial reason (if any), and diagnostic context.

3. :func:`evaluate_node_activation_context` — canonical evaluation function
   called from within ``evaluate_invocation_governance()``.  Respects the
   policy kind and applies optional topology/connectivity context only where
   explicitly allowed (``TOPOLOGY_CONDITIONAL`` nodes).

4. :func:`get_activation_policy_kind_for_node` — helper that extracts the
   activation policy kind from a ``NodeInfo`` record's metadata or returns the
   default (``ALWAYS_ACTIVE``).

Non-goals
---------
- Does NOT replace :mod:`core.node_invocation_governance` as the canonical
  pre-invocation gate.
- Does NOT make :mod:`core.network_topology_runtime` the authority for node
  existence or governance.
- Does NOT re-implement lifecycle/health/architectural-class checks (those
  remain in :mod:`core.node_governance_runtime`).
- Does NOT conflate node activation readiness with the existing
  ``CognitiveState.activation`` arousal signal.
- Does NOT introduce a new parallel node-governance authority.

Sentinels
---------
All sentinel constants are machine-checkable strings exported for use by
external verifiers (e.g. ``core/routes/projection.py``)::

    NODE_ACTIVATION_CONTEXT_IS_AUTHORITY
    NODE_ACTIVATION_CONTEXT_PR15_SENTINEL

Policy sentinels::

    ACTIVATION_CONTEXT_ENRICHES_INVOCATION_GOVERNANCE_POLICY
    DORMANT_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY
    TOPOLOGY_CONDITIONAL_REQUIRES_CONNECTIVITY_POLICY
    DEMAND_ACTIVATED_REQUIRES_EXPLICIT_REQUEST_POLICY
    ACTIVATION_POLICY_CLASSIFICATION_IS_RUNTIME_METADATA_POLICY

Public API
----------
Enums::

    NodeActivationPolicyKind

Dataclass::

    NodeActivationReadinessDecision

Functions::

    evaluate_node_activation_context(node_id, policy_kind, *,
                                     demand_context=None,
                                     topology_runtime=None)
        -> NodeActivationReadinessDecision
    get_activation_policy_kind_for_node(node_info) -> NodeActivationPolicyKind
    build_activation_context_denial_diagnostics(decision) -> dict
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeActivation.Context")

# ===========================================================================
# Authority sentinels
# ===========================================================================

NODE_ACTIVATION_CONTEXT_IS_AUTHORITY: str = (
    "NODE_ACTIVATION_CONTEXT::PR15_AUTHORITY_V1: "
    "core/node_activation_context.py is the canonical authority for node "
    "activation-context evaluation.  It enriches the canonical invocation-"
    "governance path (evaluate_invocation_governance) with runtime readiness "
    "semantics (ALWAYS_ACTIVE / TOPOLOGY_CONDITIONAL / DEMAND_ACTIVATED / "
    "DORMANT) without introducing a new parallel governance authority.  "
    "NodeFabricRegistry remains the canonical source of node existence and "
    "base eligibility.  NetworkTopologyRuntime may supply optional connectivity "
    "context only for TOPOLOGY_CONDITIONAL nodes."
)

NODE_ACTIVATION_CONTEXT_PR15_SENTINEL: str = (
    "NODE_ACTIVATION_CONTEXT::PR15_SENTINEL_V1"
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

ACTIVATION_CONTEXT_ENRICHES_INVOCATION_GOVERNANCE_POLICY: str = (
    "NODE_ACTIVATION_CONTEXT::ENRICHES_GOVERNANCE_POLICY_V1: "
    "Activation-context evaluation is invoked from *within* "
    "evaluate_invocation_governance(), not through a new parallel gate.  "
    "It enriches the canonical pre-invocation decision with readiness "
    "semantics after lifecycle/health/governance eligibility has been "
    "confirmed.  A governance-allowed node may still be denied by the "
    "activation-context layer if its policy is DORMANT or "
    "TOPOLOGY_CONDITIONAL and connectivity is unavailable."
)

DORMANT_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY: str = (
    "NODE_ACTIVATION_CONTEXT::DORMANT_NOT_INVOCABLE_POLICY_V1: "
    "A node with activation policy DORMANT cannot be canonically invoked, "
    "even if its lifecycle/governance state is otherwise eligible.  "
    "DORMANT is an explicit administrative classification indicating the node "
    "is not ready for runtime use regardless of health or registration status."
)

TOPOLOGY_CONDITIONAL_REQUIRES_CONNECTIVITY_POLICY: str = (
    "NODE_ACTIVATION_CONTEXT::TOPOLOGY_CONDITIONAL_POLICY_V1: "
    "A node classified as TOPOLOGY_CONDITIONAL may be denied invocation when "
    "optional topology/connectivity context indicates the node is unreachable.  "
    "Topology influence is scoped exclusively to TOPOLOGY_CONDITIONAL nodes.  "
    "NetworkTopologyRuntime is consulted as an optional secondary input; it is "
    "NOT the canonical authority for node existence or governance eligibility."
)

DEMAND_ACTIVATED_REQUIRES_EXPLICIT_REQUEST_POLICY: str = (
    "NODE_ACTIVATION_CONTEXT::DEMAND_ACTIVATED_POLICY_V1: "
    "A node classified as DEMAND_ACTIVATED is not ready for ambient or "
    "opportunistic invocations.  It requires an explicit demand context "
    "(demand_context parameter) supplied by the caller.  Without an explicit "
    "demand context, DEMAND_ACTIVATED nodes are treated as not ready and "
    "invocation is denied with an activation-context denial."
)

ACTIVATION_POLICY_CLASSIFICATION_IS_RUNTIME_METADATA_POLICY: str = (
    "NODE_ACTIVATION_CONTEXT::POLICY_METADATA_POLICY_V1: "
    "NodeActivationPolicyKind is runtime metadata stored in NodeInfo.metadata "
    "under the key 'activation_policy' or in the NodeInfo.activation_policy "
    "field.  It does not affect governance eligibility rules (lifecycle/health/"
    "architectural class) and is evaluated as a secondary enrichment layer.  "
    "The default policy for nodes that do not declare an activation policy is "
    "ALWAYS_ACTIVE."
)


# ===========================================================================
# NodeActivationPolicyKind enum
# ===========================================================================


class NodeActivationPolicyKind(str, Enum):
    """Runtime readiness classification for a node.

    This enum classifies a node's activation policy — how it should be
    treated with respect to runtime invocation readiness.  It is evaluated
    inside the canonical invocation-governance gate as a secondary
    enrichment layer, *after* lifecycle/health/governance eligibility has
    been confirmed.

    Attributes
    ----------
    ALWAYS_ACTIVE:
        The node is unconditionally ready for canonical invocation (subject
        only to lifecycle/governance eligibility).  This is the default
        classification for nodes that do not declare an explicit policy.
    TOPOLOGY_CONDITIONAL:
        The node's readiness depends on optional topology connectivity.
        If the optional NetworkTopologyRuntime input indicates the node
        (or a dependency node) is unreachable, invocation is denied.
        Topology influence is scoped exclusively to this classification.
    DEMAND_ACTIVATED:
        The node requires an explicit demand context to be considered ready.
        Ambient or opportunistic invocations are denied unless the caller
        explicitly supplies a demand context token.
    DORMANT:
        The node is administratively dormant.  It cannot be canonically
        invoked regardless of lifecycle or governance eligibility.  Dormant
        nodes silently return an activation-context denial without appearing
        ready through the normal invocation path.
    """

    ALWAYS_ACTIVE = "always_active"
    TOPOLOGY_CONDITIONAL = "topology_conditional"
    DEMAND_ACTIVATED = "demand_activated"
    DORMANT = "dormant"


# ===========================================================================
# NodeActivationReadinessDecision dataclass
# ===========================================================================


@dataclass
class NodeActivationReadinessDecision:
    """Result of a single activation-context readiness evaluation.

    Attributes
    ----------
    node_id:
        The node identifier being evaluated.
    policy_kind:
        The :class:`NodeActivationPolicyKind` that was applied.
    ready:
        ``True`` when the node is considered activation-context-ready.
        ``False`` means the node is blocked by its activation policy.
    denial_reason:
        Short denial code when ``ready=False``.  Empty when ``ready=True``.
        Possible values:
        - ``"dormant"`` — node is DORMANT.
        - ``"topology_unreachable"`` — TOPOLOGY_CONDITIONAL node is unreachable.
        - ``"demand_context_missing"`` — DEMAND_ACTIVATED node without context.
    diagnostic_context:
        Structured dict with human-readable decision details for diagnostics
        and operator-facing surfaces.
    topology_consulted:
        Whether NetworkTopologyRuntime was consulted during this evaluation.
    demand_context_present:
        Whether a demand context was supplied by the caller.
    evaluated_at:
        Unix epoch timestamp when this decision was made.
    """

    node_id: str
    policy_kind: NodeActivationPolicyKind
    ready: bool
    denial_reason: str = ""
    diagnostic_context: Dict[str, Any] = field(default_factory=dict)
    topology_consulted: bool = False
    demand_context_present: bool = False
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for logging and result payloads."""
        return {
            "node_id": self.node_id,
            "policy_kind": self.policy_kind.value,
            "ready": self.ready,
            "denial_reason": self.denial_reason,
            "diagnostic_context": dict(self.diagnostic_context),
            "topology_consulted": self.topology_consulted,
            "demand_context_present": self.demand_context_present,
            "evaluated_at": self.evaluated_at,
            "authority": NODE_ACTIVATION_CONTEXT_IS_AUTHORITY,
        }


# ===========================================================================
# Core evaluation function
# ===========================================================================


def evaluate_node_activation_context(
    node_id: str,
    policy_kind: NodeActivationPolicyKind,
    *,
    demand_context: Optional[str] = None,
    topology_runtime: Optional[Any] = None,
) -> NodeActivationReadinessDecision:
    """Evaluate activation-context readiness for *node_id* under *policy_kind*.

    This function is called from within
    :func:`~core.node_invocation_governance.evaluate_invocation_governance`
    as a secondary enrichment layer *after* lifecycle/health/governance
    eligibility has been confirmed.  It enforces the activation-policy
    readiness semantics but does **not** re-check governance rules.

    Parameters
    ----------
    node_id:
        The node identifier to evaluate.
    policy_kind:
        The :class:`NodeActivationPolicyKind` for this node.  Typically
        retrieved via :func:`get_activation_policy_kind_for_node`.
    demand_context:
        An optional demand context token.  Required for ``DEMAND_ACTIVATED``
        nodes; ignored for all other policy kinds.
    topology_runtime:
        An optional :class:`~core.network_topology_runtime.NetworkTopologyRuntime`
        instance.  Consulted *only* for ``TOPOLOGY_CONDITIONAL`` nodes to
        determine whether the node (or its topology entry) is reachable.
        Has no effect on any other policy kind.

    Returns
    -------
    NodeActivationReadinessDecision
        Decision record.  ``ready=True`` means the activation-context check
        passes and the node may proceed.  ``ready=False`` means the node is
        blocked by its activation policy.
    """
    topology_consulted = False
    demand_context_present = demand_context is not None and len(demand_context) > 0

    # ------------------------------------------------------------------
    # ALWAYS_ACTIVE — unconditionally ready
    # ------------------------------------------------------------------
    if policy_kind == NodeActivationPolicyKind.ALWAYS_ACTIVE:
        logger.debug(
            "activation context: READY (always_active) | node_id=%s", node_id
        )
        return NodeActivationReadinessDecision(
            node_id=node_id,
            policy_kind=policy_kind,
            ready=True,
            denial_reason="",
            diagnostic_context={
                "node_id": node_id,
                "policy_kind": policy_kind.value,
                "note": "Node is ALWAYS_ACTIVE; activation context unconditionally ready.",
            },
            topology_consulted=False,
            demand_context_present=demand_context_present,
        )

    # ------------------------------------------------------------------
    # DORMANT — blocked regardless of governance state
    # ------------------------------------------------------------------
    if policy_kind == NodeActivationPolicyKind.DORMANT:
        logger.warning(
            "activation context: BLOCKED (dormant) | node_id=%s", node_id
        )
        return NodeActivationReadinessDecision(
            node_id=node_id,
            policy_kind=policy_kind,
            ready=False,
            denial_reason="dormant",
            diagnostic_context={
                "node_id": node_id,
                "policy_kind": policy_kind.value,
                "note": (
                    "Node has DORMANT activation policy.  It cannot be "
                    "canonically invoked regardless of governance eligibility.  "
                    "Set the activation_policy to ALWAYS_ACTIVE or "
                    "DEMAND_ACTIVATED to enable invocation."
                ),
            },
            topology_consulted=False,
            demand_context_present=demand_context_present,
        )

    # ------------------------------------------------------------------
    # DEMAND_ACTIVATED — requires explicit demand context
    # ------------------------------------------------------------------
    if policy_kind == NodeActivationPolicyKind.DEMAND_ACTIVATED:
        if not demand_context_present:
            logger.warning(
                "activation context: BLOCKED (demand_context_missing) | node_id=%s",
                node_id,
            )
            return NodeActivationReadinessDecision(
                node_id=node_id,
                policy_kind=policy_kind,
                ready=False,
                denial_reason="demand_context_missing",
                diagnostic_context={
                    "node_id": node_id,
                    "policy_kind": policy_kind.value,
                    "note": (
                        "Node has DEMAND_ACTIVATED activation policy.  "
                        "No demand context was supplied by the caller.  "
                        "Provide a non-empty demand_context to activate."
                    ),
                },
                topology_consulted=False,
                demand_context_present=False,
            )
        logger.debug(
            "activation context: READY (demand_activated, context present) | node_id=%s",
            node_id,
        )
        return NodeActivationReadinessDecision(
            node_id=node_id,
            policy_kind=policy_kind,
            ready=True,
            denial_reason="",
            diagnostic_context={
                "node_id": node_id,
                "policy_kind": policy_kind.value,
                "note": "DEMAND_ACTIVATED node with explicit demand context; ready.",
            },
            topology_consulted=False,
            demand_context_present=True,
        )

    # ------------------------------------------------------------------
    # TOPOLOGY_CONDITIONAL — check optional topology connectivity
    # ------------------------------------------------------------------
    if policy_kind == NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL:
        topo_node = None
        topology_consulted = False

        if topology_runtime is not None:
            try:
                topo_node = topology_runtime.get_node(node_id)
                topology_consulted = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "activation context: topology lookup failed for node_id=%s: %s; "
                    "treating as reachable (degraded mode)",
                    node_id,
                    exc,
                )

        if topology_runtime is not None and topology_consulted:
            # Topology was available — check reachability
            if topo_node is None:
                # Node not in topology graph — treat as unreachable
                logger.warning(
                    "activation context: BLOCKED (topology_unreachable, not in topology) | node_id=%s",
                    node_id,
                )
                return NodeActivationReadinessDecision(
                    node_id=node_id,
                    policy_kind=policy_kind,
                    ready=False,
                    denial_reason="topology_unreachable",
                    diagnostic_context={
                        "node_id": node_id,
                        "policy_kind": policy_kind.value,
                        "topology_consulted": True,
                        "note": (
                            "Node has TOPOLOGY_CONDITIONAL activation policy but "
                            "is not present in the NetworkTopologyRuntime graph.  "
                            "Invocation blocked until topology connectivity is established."
                        ),
                    },
                    topology_consulted=True,
                    demand_context_present=demand_context_present,
                )
            # Check the topology node's connection state
            try:
                from core.network_topology_runtime import TopologyConnectionState  # noqa: PLC0415
                state = getattr(topo_node, "state", None)
                unreachable_states = {
                    TopologyConnectionState.UNAVAILABLE,
                }
                if state in unreachable_states:
                    logger.warning(
                        "activation context: BLOCKED (topology_unreachable, state=%s) | node_id=%s",
                        state,
                        node_id,
                    )
                    return NodeActivationReadinessDecision(
                        node_id=node_id,
                        policy_kind=policy_kind,
                        ready=False,
                        denial_reason="topology_unreachable",
                        diagnostic_context={
                            "node_id": node_id,
                            "policy_kind": policy_kind.value,
                            "topology_consulted": True,
                            "topology_node_state": state.value if hasattr(state, "value") else str(state),
                            "note": (
                                "Node has TOPOLOGY_CONDITIONAL activation policy and "
                                "NetworkTopologyRuntime reports the node as UNAVAILABLE.  "
                                "Invocation blocked until connectivity is restored."
                            ),
                        },
                        topology_consulted=True,
                        demand_context_present=demand_context_present,
                    )
            except ImportError:
                # NetworkTopologyRuntime unavailable; treat as reachable
                pass

            logger.debug(
                "activation context: READY (topology_conditional, reachable) | node_id=%s",
                node_id,
            )
            return NodeActivationReadinessDecision(
                node_id=node_id,
                policy_kind=policy_kind,
                ready=True,
                denial_reason="",
                diagnostic_context={
                    "node_id": node_id,
                    "policy_kind": policy_kind.value,
                    "topology_consulted": True,
                    "note": "TOPOLOGY_CONDITIONAL node confirmed reachable via NetworkTopologyRuntime.",
                },
                topology_consulted=True,
                demand_context_present=demand_context_present,
            )
        else:
            # No topology runtime available — allow with note (graceful degradation)
            logger.debug(
                "activation context: READY (topology_conditional, no topology runtime) | node_id=%s",
                node_id,
            )
            return NodeActivationReadinessDecision(
                node_id=node_id,
                policy_kind=policy_kind,
                ready=True,
                denial_reason="",
                diagnostic_context={
                    "node_id": node_id,
                    "policy_kind": policy_kind.value,
                    "topology_consulted": False,
                    "note": (
                        "Node has TOPOLOGY_CONDITIONAL activation policy but no "
                        "NetworkTopologyRuntime was supplied.  Proceeding as ready "
                        "in degraded mode (topology connectivity not verified)."
                    ),
                },
                topology_consulted=False,
                demand_context_present=demand_context_present,
            )

    # ------------------------------------------------------------------
    # Fallback — unknown policy kind, allow with warning
    # ------------------------------------------------------------------
    logger.warning(
        "activation context: unknown policy_kind=%s for node_id=%s; allowing",
        policy_kind,
        node_id,
    )
    return NodeActivationReadinessDecision(
        node_id=node_id,
        policy_kind=policy_kind,
        ready=True,
        denial_reason="",
        diagnostic_context={
            "node_id": node_id,
            "policy_kind": str(policy_kind),
            "note": "Unknown activation policy kind; proceeding as ready.",
        },
        topology_consulted=False,
        demand_context_present=demand_context_present,
    )


# ===========================================================================
# Helper: extract activation policy kind from NodeInfo
# ===========================================================================


def get_activation_policy_kind_for_node(node_info: Any) -> NodeActivationPolicyKind:
    """Extract the :class:`NodeActivationPolicyKind` from a ``NodeInfo`` record.

    Reads ``node_info.activation_policy`` (the dedicated field added to
    :class:`~core.nodes.node_fabric_registry.NodeInfo`) first, then falls back
    to ``node_info.metadata.get("activation_policy")``.  If neither is set,
    returns :attr:`NodeActivationPolicyKind.ALWAYS_ACTIVE` as the safe default.

    Parameters
    ----------
    node_info:
        A :class:`~core.nodes.node_fabric_registry.NodeInfo`-like object with
        optional ``activation_policy`` field or ``metadata`` dict.

    Returns
    -------
    NodeActivationPolicyKind
        The resolved activation policy kind, defaulting to ``ALWAYS_ACTIVE``.
    """
    # Try the dedicated NodeInfo field first
    raw_policy: Optional[str] = None
    try:
        field_val = getattr(node_info, "activation_policy", None)
        if field_val is not None:
            raw_policy = str(field_val)
    except Exception as exc:
        logger.debug("Suppressed: %s", exc)

    # Fall back to metadata dict
    if raw_policy is None:
        try:
            metadata = getattr(node_info, "metadata", {}) or {}
            raw_policy = metadata.get("activation_policy")
            if raw_policy is not None:
                raw_policy = str(raw_policy)
        except Exception as exc:
            logger.debug("Suppressed: %s", exc)

    if raw_policy is None:
        return NodeActivationPolicyKind.ALWAYS_ACTIVE

    # Try to coerce to enum
    try:
        return NodeActivationPolicyKind(raw_policy)
    except ValueError:
        logger.warning(
            "get_activation_policy_kind_for_node: unrecognised activation_policy=%r; "
            "defaulting to ALWAYS_ACTIVE",
            raw_policy,
        )
        return NodeActivationPolicyKind.ALWAYS_ACTIVE


# ===========================================================================
# Diagnostics helper
# ===========================================================================


def build_activation_context_denial_diagnostics(
    decision: NodeActivationReadinessDecision,
) -> Dict[str, Any]:
    """Build a structured denial diagnostic payload from a readiness decision.

    This payload is embedded in the ``NodeInvocationGovernanceDecision``
    ``diagnostic_context`` when invocation is denied by the activation-context
    layer, so that callers and operators can understand exactly why execution
    was refused at the activation-context level versus the governance level.

    Parameters
    ----------
    decision:
        A :class:`NodeActivationReadinessDecision` with ``ready=False``.

    Returns
    -------
    dict
        Structured denial payload with keys:
        - ``node_id``
        - ``denial_reason`` — short code (dormant / topology_unreachable /
          demand_context_missing)
        - ``policy_kind`` — the classification that produced the denial
        - ``diagnostic_context`` — per-decision detail
        - ``topology_consulted``
        - ``demand_context_present``
        - ``denied_at``
        - ``sentinel``
    """
    return {
        "node_id": decision.node_id,
        "denial_reason": decision.denial_reason,
        "policy_kind": decision.policy_kind.value,
        "diagnostic_context": dict(decision.diagnostic_context),
        "topology_consulted": decision.topology_consulted,
        "demand_context_present": decision.demand_context_present,
        "denied_at": time.time(),
        "sentinel": NODE_ACTIVATION_CONTEXT_PR15_SENTINEL,
    }
