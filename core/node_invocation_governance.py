#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_invocation_governance.py
====================================
PR-11: Enforce Governance Eligibility at Invocation Time.

This module is the **canonical authority** for governance eligibility checks
at *invocation time* — i.e. the gate that runs inside
:class:`~core.node_invocation.UnifiedNodeExecutor` before any node is loaded
or executed.

Background
----------
PR-6 (:mod:`core.node_governance_runtime`) introduced runtime governance as a
real filter at *capability/tool-surface exposure* time: archived, deprecated,
unhealthy, and readiness-gap nodes are excluded from what callers can *see*.

However, a node hidden from capability surfaces could still be *directly invoked*
by a caller that already knew the ``node_id``, because the unified executor
(:func:`~core.node_invocation.invoke_node`) did not consult governance before
executing.  PR-11 closes this gap.

Design
------
When :meth:`~core.node_invocation.UnifiedNodeExecutor.execute` receives an
invocation envelope it now performs the following gate **before** loading or
executing the node:

1. Look up the node in :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`.
2. If the node **is registered**, call
   :func:`~core.node_governance_runtime.evaluate_node_governance_eligibility`
   on the registry record.  If the decision is ``eligible=False``, deny the
   invocation and return a structured :class:`~core.node_invocation.NodeInvocationResult`
   with ``success=False`` and an ``eligibility_denial`` diagnostic payload.
3. If the node is **not registered** in the fabric registry, execution proceeds
   under a "unregistered/unmanaged node" warning — this preserves backward
   compatibility for nodes loaded directly from the filesystem that have not yet
   been enrolled in the managed registry.  The result carries a diagnostic
   ``governance_status=unregistered_unmanaged`` tag.
4. If the invocation envelope carries
   ``governance_override=NodeInvocationGovernanceOverride.COMPAT_INTERNAL``,
   the governance gate is bypassed entirely.  This path is explicitly auditable
   via structured log output and the ``execution_source`` field in the result.
   It MUST NOT be used by any canonical callsite.

Sentinels
---------
All sentinel constants are machine-checkable strings exported for use by
external verifiers (e.g. ``core/routes/projection.py``)::

    NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY
    NODE_INVOCATION_GOVERNANCE_PR11_SENTINEL
    GOVERNANCE_GATE_ENFORCED_AT_INVOCATION_TIME_POLICY
    INELIGIBLE_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY
    INVOCATION_DENIAL_CARRIES_STRUCTURED_DIAGNOSTICS_POLICY
    OVERRIDE_PATH_IS_EXPLICIT_AUDITABLE_NON_CANONICAL_POLICY
    UNREGISTERED_NODES_PROCEED_WITH_UNMANAGED_WARNING_POLICY

Public API
----------
Enums::

    NodeInvocationGovernanceOverride

Dataclass::

    NodeInvocationGovernanceDecision

Functions::

    evaluate_invocation_governance(node_id, *, registry=None, governor=None, heartbeat_ttl=60.0)
    build_invocation_denial_diagnostics(decision)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeInvocation.Governance")

# Module-level optional import for NodeFabricRegistry singleton access.
# Imported here so that tests can patch `core.node_invocation_governance.get_node_fabric_registry`.
try:
    from core.nodes.node_fabric_registry import get_node_fabric_registry  # noqa: F401
except ImportError:
    get_node_fabric_registry = None  # type: ignore[assignment]

# ===========================================================================
# Authority sentinels
# ===========================================================================

NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY: str = (
    "NODE_INVOCATION_GOVERNANCE::PR11_AUTHORITY_V1: "
    "core/node_invocation_governance.py is the canonical authority for "
    "governance eligibility enforcement at node *invocation* time.  "
    "UnifiedNodeExecutor.execute() MUST consult this module before loading "
    "or executing any node.  Governance-ineligible nodes (archived, "
    "deprecated, unhealthy, readiness-gap) are denied canonical invocation "
    "with a structured diagnostic payload.  The only permitted bypass is the "
    "explicitly-scoped COMPAT_INTERNAL override path, which is non-canonical "
    "and fully auditable."
)

NODE_INVOCATION_GOVERNANCE_PR11_SENTINEL: str = (
    "NODE_INVOCATION_GOVERNANCE::PR11_SENTINEL_V1"
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

GOVERNANCE_GATE_ENFORCED_AT_INVOCATION_TIME_POLICY: str = (
    "NODE_INVOCATION_GOVERNANCE::GATE_AT_INVOCATION_POLICY_V1: "
    "Governance eligibility is enforced at invocation time, not only at "
    "capability/tool-surface exposure time.  UnifiedNodeExecutor.execute() "
    "consults NodeFabricRegistry and evaluate_node_governance_eligibility() "
    "before loading or running any node on the canonical path."
)

INELIGIBLE_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY: str = (
    "NODE_INVOCATION_GOVERNANCE::INELIGIBLE_NOT_INVOCABLE_POLICY_V1: "
    "A node that is governance-ineligible (archived, deprecated, unhealthy, "
    "or readiness-gap) cannot be executed through canonical node invocation "
    "paths, even if the caller supplies a known node_id directly.  "
    "Canonical invocation denial is enforced identically to canonical "
    "exposure exclusion."
)

INVOCATION_DENIAL_CARRIES_STRUCTURED_DIAGNOSTICS_POLICY: str = (
    "NODE_INVOCATION_GOVERNANCE::DENIAL_DIAGNOSTICS_POLICY_V1: "
    "When canonical invocation is denied due to governance ineligibility, "
    "the returned NodeInvocationResult carries a structured diagnostic payload "
    "under the 'eligibility_denial' key.  The payload includes node_id, "
    "exclusion_reasons, diagnostic_context, and governor_consulted so that "
    "callers and operators can understand exactly why execution was refused."
)

OVERRIDE_PATH_IS_EXPLICIT_AUDITABLE_NON_CANONICAL_POLICY: str = (
    "NODE_INVOCATION_GOVERNANCE::OVERRIDE_AUDITABLE_POLICY_V1: "
    "The only permitted bypass of the invocation-time governance gate is "
    "NodeInvocationGovernanceOverride.COMPAT_INTERNAL.  This path is "
    "explicitly logged at WARNING level, reflected in the result's "
    "execution_source field, and MUST NOT be used by canonical callsites.  "
    "It exists solely for tightly-scoped internal compatibility transitions."
)

UNREGISTERED_NODES_PROCEED_WITH_UNMANAGED_WARNING_POLICY: str = (
    "NODE_INVOCATION_GOVERNANCE::UNREGISTERED_UNMANAGED_POLICY_V1: "
    "Nodes that are not enrolled in NodeFabricRegistry cannot have their "
    "governance eligibility evaluated.  Such nodes are allowed to proceed "
    "under a WARNING-level log message and are tagged with "
    "governance_status=unregistered_unmanaged in the invocation result.  "
    "This preserves backward compatibility for filesystem-only nodes that "
    "have not yet been enrolled in managed runtime governance."
)


# ===========================================================================
# Override enum
# ===========================================================================

class NodeInvocationGovernanceOverride(str, Enum):
    """Controls whether the invocation-time governance gate is bypassed.

    Attributes
    ----------
    NONE:
        No override — the canonical governance gate runs normally.
    COMPAT_INTERNAL:
        Bypass the governance gate for tightly-scoped internal/compatibility
        purposes.  This path is auditable: it is logged at WARNING level and
        reflected in ``execution_source``.  MUST NOT be used by canonical
        callsites.
    """

    NONE = "none"
    COMPAT_INTERNAL = "compat_internal"


# ===========================================================================
# Decision dataclass
# ===========================================================================

@dataclass
class NodeInvocationGovernanceDecision:
    """Result of an invocation-time governance eligibility check.

    Attributes
    ----------
    node_id:
        The node identifier being evaluated.
    invocation_allowed:
        ``True`` when the node may proceed to execution on the canonical path.
    denial_reasons:
        Ordered list of reason codes explaining why invocation is denied.
        Empty when ``invocation_allowed=True``.
    diagnostic_context:
        Structured human-readable dict with decision details.
    governance_status:
        High-level classification:
        - ``"eligible"`` — node is governance-eligible, invocation allowed.
        - ``"ineligible_denied"`` — node is governance-ineligible, invocation denied.
        - ``"unregistered_unmanaged"`` — node not in registry, proceeds with warning.
        - ``"override_compat_internal"`` — override path; governance gate bypassed.
    registry_consulted:
        Whether NodeFabricRegistry was consulted during the check.
    governor_consulted:
        Whether NodeLifecycleGovernor was consulted during the check.
    evaluated_at:
        Unix epoch timestamp when this decision was made.
    """

    node_id: str
    invocation_allowed: bool
    denial_reasons: List[str] = field(default_factory=list)
    diagnostic_context: Dict[str, Any] = field(default_factory=dict)
    governance_status: str = "eligible"
    registry_consulted: bool = False
    governor_consulted: bool = False
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for logging and result payloads."""
        return {
            "node_id": self.node_id,
            "invocation_allowed": self.invocation_allowed,
            "denial_reasons": list(self.denial_reasons),
            "diagnostic_context": dict(self.diagnostic_context),
            "governance_status": self.governance_status,
            "registry_consulted": self.registry_consulted,
            "governor_consulted": self.governor_consulted,
            "evaluated_at": self.evaluated_at,
            "authority": NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY,
        }


# ===========================================================================
# Core gate function
# ===========================================================================

def evaluate_invocation_governance(
    node_id: str,
    *,
    registry: Optional[Any] = None,
    governor: Optional[Any] = None,
    heartbeat_ttl: float = 60.0,
    override: NodeInvocationGovernanceOverride = NodeInvocationGovernanceOverride.NONE,
) -> NodeInvocationGovernanceDecision:
    """Evaluate whether *node_id* may be invoked on the canonical path.

    Parameters
    ----------
    node_id:
        The node identifier to check.
    registry:
        An optional :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
        instance.  When ``None``, the module-level singleton is retrieved via
        :func:`~core.nodes.node_fabric_registry.get_node_fabric_registry`.
    governor:
        An optional :class:`~core.node_lifecycle_governor.NodeLifecycleGovernor`
        instance.  When ``None``, only architectural-class and health rules
        apply (fallback mode as per PR-6 compatibility semantics).
    heartbeat_ttl:
        Heartbeat TTL in seconds forwarded to
        :func:`~core.node_governance_runtime.evaluate_node_governance_eligibility`.
    override:
        When :attr:`NodeInvocationGovernanceOverride.COMPAT_INTERNAL`, the gate
        is bypassed entirely and an auditable override decision is returned.

    Returns
    -------
    NodeInvocationGovernanceDecision
        Decision record.  ``invocation_allowed=True`` means the node may
        proceed to canonical execution.
    """
    # ------------------------------------------------------------------
    # Override path: compat/internal bypass
    # ------------------------------------------------------------------
    if override == NodeInvocationGovernanceOverride.COMPAT_INTERNAL:
        logger.warning(
            "governance gate bypassed via COMPAT_INTERNAL override | node_id=%s",
            node_id,
        )
        return NodeInvocationGovernanceDecision(
            node_id=node_id,
            invocation_allowed=True,
            denial_reasons=[],
            diagnostic_context={
                "node_id": node_id,
                "override": override.value,
                "checked_at": time.time(),
                "note": (
                    "Governance gate bypassed via COMPAT_INTERNAL override.  "
                    "This path is non-canonical and auditable."
                ),
            },
            governance_status="override_compat_internal",
            registry_consulted=False,
            governor_consulted=False,
        )

    # ------------------------------------------------------------------
    # Resolve NodeFabricRegistry
    # ------------------------------------------------------------------
    resolved_registry = registry
    if resolved_registry is None:
        try:
            # Use module-level get_node_fabric_registry (patchable in tests)
            _get_reg = get_node_fabric_registry
            if _get_reg is None:
                # Module-level import failed; try inline
                from core.nodes.node_fabric_registry import get_node_fabric_registry as _get_reg  # noqa: PLC0415
            resolved_registry = _get_reg()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "governance gate: could not resolve NodeFabricRegistry for node_id=%s: %s",
                node_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Look up node in registry
    # ------------------------------------------------------------------
    node_info = None
    registry_consulted = False
    if resolved_registry is not None:
        try:
            node_info = resolved_registry.get(node_id)
            registry_consulted = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "governance gate: registry lookup failed for node_id=%s: %s",
                node_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Unregistered / unmanaged node — allow with warning
    # ------------------------------------------------------------------
    if node_info is None:
        logger.warning(
            "governance gate: node_id=%s is not registered in NodeFabricRegistry; "
            "proceeding as unregistered/unmanaged (governance not enforced)",
            node_id,
        )
        return NodeInvocationGovernanceDecision(
            node_id=node_id,
            invocation_allowed=True,
            denial_reasons=[],
            diagnostic_context={
                "node_id": node_id,
                "registry_consulted": registry_consulted,
                "checked_at": time.time(),
                "note": (
                    "Node not found in NodeFabricRegistry.  Proceeding as "
                    "unregistered/unmanaged.  Governance eligibility not enforced."
                ),
            },
            governance_status="unregistered_unmanaged",
            registry_consulted=registry_consulted,
            governor_consulted=False,
        )

    # ------------------------------------------------------------------
    # Resolve governor record if governor is provided
    # ------------------------------------------------------------------
    governor_record = None
    if governor is not None:
        try:
            governor_record = governor.get_record(node_id)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Evaluate governance eligibility via PR-6 function
    # ------------------------------------------------------------------
    try:
        from core.node_governance_runtime import evaluate_node_governance_eligibility  # noqa: PLC0415
        eligibility = evaluate_node_governance_eligibility(
            node_info,
            governor_record=governor_record,
            heartbeat_ttl=heartbeat_ttl,
        )
    except Exception as exc:  # noqa: BLE001
        # If governance evaluation itself fails, allow execution with a
        # warning rather than silently blocking everything.
        logger.warning(
            "governance gate: eligibility evaluation failed for node_id=%s: %s; "
            "allowing invocation in degraded mode",
            node_id,
            exc,
        )
        return NodeInvocationGovernanceDecision(
            node_id=node_id,
            invocation_allowed=True,
            denial_reasons=[],
            diagnostic_context={
                "node_id": node_id,
                "evaluation_error": str(exc),
                "checked_at": time.time(),
                "note": "Governance evaluation failed; proceeding in degraded mode.",
            },
            governance_status="evaluation_error_degraded",
            registry_consulted=registry_consulted,
            governor_consulted=False,
        )

    # ------------------------------------------------------------------
    # Apply eligibility decision
    # ------------------------------------------------------------------
    if eligibility.eligible:
        logger.debug(
            "governance gate: ALLOWED | node_id=%s governor_consulted=%s",
            node_id,
            eligibility.governor_consulted,
        )
        return NodeInvocationGovernanceDecision(
            node_id=node_id,
            invocation_allowed=True,
            denial_reasons=[],
            diagnostic_context=dict(eligibility.diagnostic_context),
            governance_status="eligible",
            registry_consulted=registry_consulted,
            governor_consulted=eligibility.governor_consulted,
        )
    else:
        logger.warning(
            "governance gate: DENIED | node_id=%s reasons=%s",
            node_id,
            eligibility.exclusion_reasons,
        )
        return NodeInvocationGovernanceDecision(
            node_id=node_id,
            invocation_allowed=False,
            denial_reasons=list(eligibility.exclusion_reasons),
            diagnostic_context=dict(eligibility.diagnostic_context),
            governance_status="ineligible_denied",
            registry_consulted=registry_consulted,
            governor_consulted=eligibility.governor_consulted,
        )


# ===========================================================================
# Denial diagnostics helper
# ===========================================================================

def build_invocation_denial_diagnostics(
    decision: NodeInvocationGovernanceDecision,
) -> Dict[str, Any]:
    """Build a structured denial diagnostic payload from a governance decision.

    This payload is embedded in the ``NodeInvocationResult.result`` field
    (under the key ``eligibility_denial``) when invocation is denied, so
    that callers receive actionable, machine-readable information about
    why execution was refused.

    Parameters
    ----------
    decision:
        A :class:`NodeInvocationGovernanceDecision` with
        ``invocation_allowed=False``.

    Returns
    -------
    dict
        Structured denial payload with keys:
        - ``node_id``
        - ``denial_reasons`` — list of exclusion reason codes
        - ``governance_status`` — e.g. ``"ineligible_denied"``
        - ``diagnostic_context`` — per-rule detail from eligibility check
        - ``registry_consulted``
        - ``governor_consulted``
        - ``denied_at``
        - ``sentinel`` — PR-11 authority sentinel
    """
    return {
        "node_id": decision.node_id,
        "denial_reasons": list(decision.denial_reasons),
        "governance_status": decision.governance_status,
        "diagnostic_context": dict(decision.diagnostic_context),
        "registry_consulted": decision.registry_consulted,
        "governor_consulted": decision.governor_consulted,
        "denied_at": time.time(),
        "sentinel": NODE_INVOCATION_GOVERNANCE_PR11_SENTINEL,
    }
