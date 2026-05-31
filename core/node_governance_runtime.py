#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_governance_runtime.py
================================
PR-6: Node Governance Runtime Constraint — Make Governance a Real Runtime Filter.

This module is the **canonical runtime governance eligibility authority** for
node exposure and capability synchronization.  It enforces that governance
metadata (architectural class, health, lifecycle stage, deprecated/archived
semantics) is a real runtime constraint, not just documentation.

Problem addressed
-----------------
Prior to PR-6, governance concepts such as readiness, architectural classes,
lifecycle stages, and deprecated/archived semantics existed on paper but did
not reliably participate in runtime decision-making.  Nodes that should have
been excluded from canonical tool surfaces could still appear there through
fallback paths.

This module bridges:
  - :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` — health/
    architectural-class data.
  - :class:`~core.node_lifecycle_governor.NodeLifecycleGovernor` — lifecycle
    stage data (when available).

Eligibility rules
-----------------
A node is **canonically eligible** for tool-surface exposure if ALL of the
following conditions are met:

1. **Architectural class is CAPABILITY_NODE.**
   SERVICE_NODE, LEGACY_ORCHESTRATOR_NODE, EXPERIMENTAL_NODE, and
   ARCHIVED_NODE nodes are never eligible for canonical tool exposure.

2. **Node is healthy.**
   Unhealthy or offline nodes (based on heartbeat TTL and error state) are
   excluded from the canonical path.

3. **Lifecycle stage is not DEPRECATED** (when governance record available).
   A node in the DEPRECATED stage has been explicitly marked for removal;
   its capabilities must not be consumed.

4. **Lifecycle stage is not merely REGISTERED** (when governance record is
   available and readiness checking is enabled).
   A node that has only been registered but has not passed readiness checks
   represents a readiness gap and should not be exposed canonically.

Compatibility fallbacks
-----------------------
If :mod:`core.node_lifecycle_governor` is unavailable (import error), only
rules 1 and 2 (architectural class and health) are enforced.  This ensures
backward compatibility while the governor is being wired in.  The fallback
path is explicitly logged and marked as non-canonical.

Diagnostics
-----------
Every eligibility decision is recorded as a :class:`NodeGovernanceEligibilityDecision`
explaining which rules were applied and why the node was included or excluded.
Call :func:`evaluate_node_governance_eligibility` for per-node decisions and
:func:`build_governance_exclusion_report` for a bulk diagnostic snapshot.

Public API
----------
Authority sentinels::

    NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY
    NODE_GOVERNANCE_RUNTIME_CONSTRAINT_PR6_SENTINEL

Policy sentinels::

    ARCHIVED_AND_DEPRECATED_NODES_EXCLUDED_POLICY
    UNHEALTHY_NODES_EXCLUDED_FROM_CANONICAL_PATH_POLICY
    READINESS_GAP_NODES_EXCLUDED_POLICY
    GOVERNANCE_EXCLUSION_IS_DIAGNOSABLE_POLICY
    COMPATIBILITY_FALLBACK_IS_NON_CANONICAL_POLICY

Dataclasses::

    NodeGovernanceEligibilityDecision

Functions::

    evaluate_node_governance_eligibility(node_info, governor_record=None)
    get_governance_eligible_nodes(nodes, governor=None)
    build_governance_exclusion_report(nodes, governor=None)
    reset_governance_runtime_cache()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.Nodes.NodeGovernanceRuntime")

# ===========================================================================
# Authority sentinels
# ===========================================================================

NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY: str = (
    "NODE_GOVERNANCE_RUNTIME::PR6_AUTHORITY_V1: "
    "core/node_governance_runtime.py is the canonical authority for node "
    "governance runtime eligibility.  Governance metadata (architectural class, "
    "health, lifecycle stage, deprecated/archived semantics) is a real runtime "
    "constraint for canonical node tool-surface exposure.  "
    "Archived/deprecated/unhealthy/readiness-gap nodes are filtered from the "
    "canonical path.  Every exclusion decision is diagnostically observable."
)

NODE_GOVERNANCE_RUNTIME_CONSTRAINT_PR6_SENTINEL: str = (
    "NODE_GOVERNANCE_RUNTIME::PR6_SENTINEL_V1"
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

ARCHIVED_AND_DEPRECATED_NODES_EXCLUDED_POLICY: str = (
    "NODE_GOVERNANCE_RUNTIME::ARCHIVED_DEPRECATED_EXCLUDED_POLICY_V1: "
    "Nodes with architectural_class=ARCHIVED_NODE, or with a governance "
    "lifecycle_stage=DEPRECATED, are unconditionally excluded from canonical "
    "tool-surface exposure.  This is a hard runtime constraint, not a hint."
)

UNHEALTHY_NODES_EXCLUDED_FROM_CANONICAL_PATH_POLICY: str = (
    "NODE_GOVERNANCE_RUNTIME::UNHEALTHY_EXCLUDED_POLICY_V1: "
    "Nodes whose is_healthy() returns False (based on heartbeat TTL and error "
    "state) are excluded from the canonical tool-surface path.  An unhealthy "
    "node must not be offered as a callable capability to consumers."
)

READINESS_GAP_NODES_EXCLUDED_POLICY: str = (
    "NODE_GOVERNANCE_RUNTIME::READINESS_GAP_EXCLUDED_POLICY_V1: "
    "When a NodeLifecycleGovernor record is available, a node that has only "
    "reached the REGISTERED lifecycle stage (i.e. has not passed readiness "
    "checks) is considered to have a readiness gap and is excluded from the "
    "canonical tool-surface path.  This prevents prematurely exposing "
    "ungoverned or newly onboarded nodes."
)

GOVERNANCE_EXCLUSION_IS_DIAGNOSABLE_POLICY: str = (
    "NODE_GOVERNANCE_RUNTIME::DIAGNOSABLE_EXCLUSION_POLICY_V1: "
    "Every governance eligibility decision must be observable.  The "
    "NodeGovernanceEligibilityDecision dataclass carries eligible, "
    "exclusion_reasons, and diagnostic_context for each node.  Callers "
    "must log or surface these diagnostics so operators can understand "
    "why a node is or is not canonically exposed."
)

COMPATIBILITY_FALLBACK_IS_NON_CANONICAL_POLICY: str = (
    "NODE_GOVERNANCE_RUNTIME::COMPAT_FALLBACK_NON_CANONICAL_POLICY_V1: "
    "If NodeLifecycleGovernor is unavailable, the system falls back to "
    "architectural-class + health filtering only.  This fallback path is "
    "explicitly marked as non-canonical.  It must not silently override "
    "canonical governance behaviour.  Callers should log a warning when "
    "operating in fallback mode."
)

NON_CAPABILITY_NODE_EXCLUDED_FROM_CANONICAL_SURFACE_POLICY: str = (
    "NODE_GOVERNANCE_RUNTIME::NON_CAPABILITY_NODE_EXCLUDED_POLICY_V1: "
    "Only nodes with architectural_class=CAPABILITY_NODE are eligible for "
    "canonical tool-surface exposure.  SERVICE_NODE, "
    "LEGACY_ORCHESTRATOR_NODE, EXPERIMENTAL_NODE, and ARCHIVED_NODE nodes "
    "are not eligible.  This is a hard architectural governance rule."
)

# ===========================================================================
# Eligibility-reason vocabulary
# ===========================================================================

#: Returned when the node passes all governance eligibility checks.
ELIGIBLE: str = "eligible"

#: Architectural class is not CAPABILITY_NODE.
REASON_NON_CAPABILITY_CLASS: str = "non_capability_architectural_class"

#: Node is archived (architectural class = ARCHIVED_NODE).
REASON_ARCHIVED: str = "archived_node"

#: Node is not healthy (heartbeat stale or error state).
REASON_UNHEALTHY: str = "unhealthy"

#: Node lifecycle stage is DEPRECATED.
REASON_DEPRECATED: str = "deprecated_lifecycle_stage"

#: Node lifecycle stage is REGISTERED (readiness gap).
REASON_READINESS_GAP: str = "readiness_gap_lifecycle_stage"

#: Fallback mode: lifecycle governor unavailable; only arch-class + health checked.
REASON_GOVERNOR_UNAVAILABLE: str = "lifecycle_governor_unavailable_fallback"


# ===========================================================================
# Decision dataclass
# ===========================================================================


@dataclass
class NodeGovernanceEligibilityDecision:
    """Governance eligibility decision for one node.

    Attributes
    ----------
    node_id:
        The node identifier being evaluated.
    eligible:
        ``True`` when the node passes all governance eligibility checks and
        may be exposed on the canonical tool surface.
    exclusion_reasons:
        Ordered list of reason codes explaining why the node is excluded.
        Empty when ``eligible=True``.
    diagnostic_context:
        Human-readable dict with structured information about the decision.
        Always populated, regardless of eligibility.
    evaluated_at:
        Unix epoch timestamp when this decision was made.
    governor_consulted:
        Whether the :class:`~core.node_lifecycle_governor.NodeLifecycleGovernor`
        was consulted during evaluation.  ``False`` indicates fallback mode.
    """

    node_id: str
    eligible: bool
    exclusion_reasons: List[str] = field(default_factory=list)
    diagnostic_context: Dict[str, Any] = field(default_factory=dict)
    evaluated_at: float = field(default_factory=time.time)
    governor_consulted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of this decision."""
        return {
            "node_id": self.node_id,
            "eligible": self.eligible,
            "exclusion_reasons": list(self.exclusion_reasons),
            "diagnostic_context": dict(self.diagnostic_context),
            "evaluated_at": self.evaluated_at,
            "governor_consulted": self.governor_consulted,
            "authority": NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY,
        }

    def __repr__(self) -> str:
        status = "ELIGIBLE" if self.eligible else f"EXCLUDED({','.join(self.exclusion_reasons)})"
        return f"NodeGovernanceEligibilityDecision(node_id={self.node_id!r}, {status})"


# ===========================================================================
# Core evaluation function
# ===========================================================================


def evaluate_node_governance_eligibility(
    node_info: Any,
    governor_record: Optional[Any] = None,
    heartbeat_ttl: float = 60.0,
) -> NodeGovernanceEligibilityDecision:
    """Evaluate whether *node_info* is canonically eligible for tool-surface exposure.

    Parameters
    ----------
    node_info:
        A :class:`~core.nodes.node_fabric_registry.NodeInfo` instance.
    governor_record:
        An optional :class:`~core.node_lifecycle_governor.NodeGovernanceRecord`.
        When provided, lifecycle-stage rules (DEPRECATED, readiness-gap) are
        enforced.  When ``None``, only architectural-class and health rules
        apply (fallback mode).
    heartbeat_ttl:
        Heartbeat TTL in seconds.  Passed to ``node_info.is_healthy()``.

    Returns
    -------
    NodeGovernanceEligibilityDecision
        A decision record.  ``eligible=True`` means the node passes all
        governance checks.  ``eligible=False`` means at least one rule
        excluded the node; ``exclusion_reasons`` lists the applicable codes.
    """
    node_id: str = getattr(node_info, "node_id", str(node_info))
    exclusion_reasons: List[str] = []
    diagnostic: Dict[str, Any] = {
        "node_id": node_id,
        "checked_at": time.time(),
    }

    # ------------------------------------------------------------------
    # Rule 1: Architectural class must be CAPABILITY_NODE
    # ------------------------------------------------------------------
    try:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass, CAPABILITY_SYNC_ELIGIBLE  # noqa: PLC0415
        arch = getattr(node_info, "architectural_class", None)
        arch_value = arch.value if hasattr(arch, "value") else str(arch) if arch is not None else "unknown"
        diagnostic["architectural_class"] = arch_value

        if arch == NodeArchitecturalClass.ARCHIVED_NODE:
            exclusion_reasons.append(REASON_ARCHIVED)
            diagnostic["architectural_class_rule"] = "excluded: ARCHIVED_NODE"
        elif arch not in CAPABILITY_SYNC_ELIGIBLE:
            exclusion_reasons.append(REASON_NON_CAPABILITY_CLASS)
            diagnostic["architectural_class_rule"] = (
                f"excluded: {arch_value} not in CAPABILITY_SYNC_ELIGIBLE"
            )
        else:
            diagnostic["architectural_class_rule"] = "passed: CAPABILITY_NODE"
    except ImportError:
        diagnostic["architectural_class_rule"] = "skipped: NodeFabricRegistry unavailable"

    # ------------------------------------------------------------------
    # Rule 2: Node must be healthy
    # ------------------------------------------------------------------
    try:
        healthy = node_info.is_healthy(heartbeat_ttl)
    except Exception as exc:
        try:
            status = getattr(node_info, "status", None)
            healthy = str(status).lower() in {"healthy", "starting"}
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            healthy = False

    diagnostic["is_healthy"] = healthy
    if not healthy:
        exclusion_reasons.append(REASON_UNHEALTHY)
        diagnostic["health_rule"] = "excluded: node is not healthy"
    else:
        diagnostic["health_rule"] = "passed: node is healthy"

    # ------------------------------------------------------------------
    # Rules 3 & 4: Lifecycle stage (when governor record available)
    # ------------------------------------------------------------------
    # Import NodeLifecycleStage once, outside of the record-checking block, so
    # that import failures are handled explicitly and separately from record-
    # evaluation failures.
    _NodeLifecycleStage = None
    _lifecycle_stage_import_error: Optional[str] = None
    try:
        from core.node_lifecycle_governor import NodeLifecycleStage as _NodeLifecycleStage  # noqa: PLC0415
    except ImportError as _imp_err:
        _lifecycle_stage_import_error = str(_imp_err)

    governor_consulted = governor_record is not None and _NodeLifecycleStage is not None
    if governor_record is not None:
        if _NodeLifecycleStage is None:
            # Import failed: cannot enforce lifecycle rules; log and skip.
            diagnostic["lifecycle_rule"] = (
                f"skipped: NodeLifecycleStage unavailable ({_lifecycle_stage_import_error})"
            )
        else:
            try:
                stage = getattr(governor_record, "lifecycle_stage", None)
                stage_value = stage.value if hasattr(stage, "value") else str(stage)
                diagnostic["lifecycle_stage"] = stage_value

                # Rule 3: DEPRECATED stage → excluded
                if stage == _NodeLifecycleStage.DEPRECATED:
                    exclusion_reasons.append(REASON_DEPRECATED)
                    diagnostic["lifecycle_rule"] = "excluded: lifecycle_stage=DEPRECATED"

                # Rule 4: REGISTERED stage only → readiness gap
                elif stage == _NodeLifecycleStage.REGISTERED:
                    exclusion_reasons.append(REASON_READINESS_GAP)
                    diagnostic["lifecycle_rule"] = (
                        "excluded: lifecycle_stage=REGISTERED (readiness gap; "
                        "node has not passed readiness checks)"
                    )
                else:
                    diagnostic["lifecycle_rule"] = f"passed: lifecycle_stage={stage_value}"
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                diagnostic["lifecycle_rule"] = f"error evaluating lifecycle_stage: {exc}"
                governor_consulted = False
    else:
        diagnostic["lifecycle_rule"] = (
            "skipped: no governor record (fallback mode — arch class + health only)"
        )

    eligible = len(exclusion_reasons) == 0

    if not eligible:
        logger.debug(
            "Node %s excluded from canonical tool surface: reasons=%s context=%s",
            node_id,
            exclusion_reasons,
            {k: v for k, v in diagnostic.items() if k.endswith("_rule")},
        )
    else:
        logger.debug(
            "Node %s is governance-eligible for canonical tool surface",
            node_id,
        )

    return NodeGovernanceEligibilityDecision(
        node_id=node_id,
        eligible=eligible,
        exclusion_reasons=exclusion_reasons,
        diagnostic_context=diagnostic,
        governor_consulted=governor_consulted,
    )


# ===========================================================================
# Bulk helpers
# ===========================================================================


def get_governance_eligible_nodes(
    nodes: Sequence[Any],
    governor: Optional[Any] = None,
    heartbeat_ttl: float = 60.0,
) -> List[Any]:
    """Return only the governance-eligible nodes from *nodes*.

    Parameters
    ----------
    nodes:
        Sequence of :class:`~core.nodes.node_fabric_registry.NodeInfo` instances.
    governor:
        Optional :class:`~core.node_lifecycle_governor.NodeLifecycleGovernor`
        instance.  When provided, lifecycle-stage rules are enforced.
    heartbeat_ttl:
        Heartbeat TTL in seconds.

    Returns
    -------
    list
        Filtered list containing only governance-eligible nodes.
    """
    eligible: List[Any] = []
    for node in nodes:
        node_id = getattr(node, "node_id", None)
        gov_record = None
        if governor is not None and node_id is not None:
            try:
                gov_record = governor.get_record(node_id)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
        decision = evaluate_node_governance_eligibility(
            node, governor_record=gov_record, heartbeat_ttl=heartbeat_ttl
        )
        if decision.eligible:
            eligible.append(node)
    return eligible


def build_governance_exclusion_report(
    nodes: Sequence[Any],
    governor: Optional[Any] = None,
    heartbeat_ttl: float = 60.0,
) -> Dict[str, Any]:
    """Build a diagnostic report of governance eligibility for *nodes*.

    This function evaluates every node in *nodes* and returns a structured
    report grouping nodes by eligibility and exclusion reason.  Use this for
    operational diagnostics when investigating why nodes are absent from
    canonical tool surfaces.

    Parameters
    ----------
    nodes:
        Sequence of :class:`~core.nodes.node_fabric_registry.NodeInfo` instances.
    governor:
        Optional :class:`~core.node_lifecycle_governor.NodeLifecycleGovernor`.
    heartbeat_ttl:
        Heartbeat TTL in seconds.

    Returns
    -------
    dict
        Structured report with keys:
        - ``total``: total nodes evaluated.
        - ``eligible_count``: nodes that pass all governance checks.
        - ``excluded_count``: nodes excluded from the canonical path.
        - ``eligible_nodes``: list of eligible node IDs.
        - ``excluded_nodes``: list of dicts per excluded node with
          ``node_id`` and ``exclusion_reasons``.
        - ``exclusion_summary``: dict mapping each reason code to a count.
        - ``authority``: module authority sentinel.
        - ``report_at``: Unix epoch timestamp.
    """
    eligible_ids: List[str] = []
    excluded_entries: List[Dict[str, Any]] = []
    exclusion_summary: Dict[str, int] = {}

    for node in nodes:
        node_id = getattr(node, "node_id", str(node))
        gov_record = None
        if governor is not None and node_id is not None:
            try:
                gov_record = governor.get_record(node_id)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
        decision = evaluate_node_governance_eligibility(
            node, governor_record=gov_record, heartbeat_ttl=heartbeat_ttl
        )
        if decision.eligible:
            eligible_ids.append(node_id)
        else:
            excluded_entries.append(
                {
                    "node_id": node_id,
                    "exclusion_reasons": list(decision.exclusion_reasons),
                    "diagnostic_context": decision.diagnostic_context,
                    "governor_consulted": decision.governor_consulted,
                }
            )
            for reason in decision.exclusion_reasons:
                exclusion_summary[reason] = exclusion_summary.get(reason, 0) + 1

    return {
        "total": len(nodes),
        "eligible_count": len(eligible_ids),
        "excluded_count": len(excluded_entries),
        "eligible_nodes": eligible_ids,
        "excluded_nodes": excluded_entries,
        "exclusion_summary": exclusion_summary,
        "governor_consulted": governor is not None,
        "authority": NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY,
        "report_at": time.time(),
    }


# ===========================================================================
# Test-isolation helper
# ===========================================================================

def reset_governance_runtime_cache() -> None:
    """No-op reset hook for test isolation.

    Reserved for future use if caching is introduced.
    """
