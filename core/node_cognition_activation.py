#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_cognition_activation.py
====================================
PR-14 (node track): Cognition-Oriented Node Activation Layer.

This module is the **canonical authority** for the cognition-oriented node
activation layer that sits *above* raw tool/capability invocation and
*beneath* full planner or memory orchestration.

Background
----------
PR-5 through PR-13 (node track) established the canonical runtime foundation:

- Canonical runtime registry (:mod:`core.nodes.node_fabric_registry`)
- Unified invocation executor (:mod:`core.node_invocation`)
- Governance eligibility at capability exposure time
  (:mod:`core.node_governance_runtime`)
- Governance eligibility at invocation time
  (:mod:`core.node_invocation_governance`)
- Discovery and health wiring
  (:mod:`core.node_discovery_startup_health_closure`)
- Explicit boundary classification of all node surfaces
  (:mod:`core.node_final_boundary_enforcement`)

That foundation treats nodes primarily as *callable capability providers*
that are exposed externally as tools.  This is the correct substrate layer,
but it does not yet support the cognition-oriented model that the system is
converging toward.

Purpose of this module
-----------------------
A cognition-oriented architecture needs more than raw callable nodes.  It
needs a layer that can represent:

- **when** a node is *eligible* for cognitive participation (as opposed to
  merely being governance-eligible for raw invocation)
- **when** a node is *selected* for a planning, acting, sensing, or memory
  role in the current session/task context
- **how** node activation relates to task/session context
- **how** node execution fits into a higher-level orchestration or
  state-transition model

This module introduces that activation layer.  It is intentionally thin:
it does not replace the unified executor, does not re-implement governance,
and does not attempt to build a complete state-machine runtime.  Instead it
provides the formal vocabulary, transition model, and policy contracts that
higher-level orchestration layers (planners, cognitive modes, attention
routers) can use to interact with nodes as *cognitive participants* rather
than as bare callable tools.

Design
------
1. :class:`NodeActivationState` — the canonical set of activation states
   a node can occupy in a cognition-oriented context.
2. :class:`NodeCognitionRole` — the cognitive role assigned to an activated
   node within a task or session context (planning, acting, sensing, memory,
   coordination).
3. :class:`NodeActivationContext` — the activation record for a single
   node within a particular session/task.  Carries state, role, activation
   reason, and references to the canonical runtime authority.
4. :func:`evaluate_activation_eligibility` — policy-aware check that
   determines whether a node may enter the ``SELECTED`` state for a given
   cognitive context.  Builds on top of governance eligibility and adds
   cognition-specific rules.
5. :func:`transition_activation_state` — validates and applies a
   state transition against the canonical transition table.
6. :func:`build_activation_context_snapshot` — assembles a
   :class:`NodeActivationContextSnapshot` summarising all active contexts
   for observability and dashboard surfaces.
7. :class:`NodeActivationPolicy` — container for policy-aware activation
   rules that higher-level orchestration layers can configure without
   modifying the runtime or invocation layers.

Non-goals
---------
- Does NOT replace :mod:`core.node_invocation` or
  :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`.
- Does NOT implement a full state-machine runtime.
- Does NOT implement planner, memory, or orchestration logic.
- Does NOT change governance eligibility rules.

Sentinels
---------
All sentinel constants are machine-checkable strings exported for use by
external verifiers (e.g. ``core/routes/projection.py``)::

    NODE_COGNITION_ACTIVATION_IS_AUTHORITY
    NODE_COGNITION_ACTIVATION_PR14_SENTINEL

Policy sentinels::

    ACTIVATION_LAYER_SITS_ABOVE_INVOCATION_SUBSTRATE_POLICY
    ACTIVATION_ELIGIBILITY_REQUIRES_GOVERNANCE_CLEARANCE_POLICY
    ACTIVATION_STATE_TRANSITIONS_ARE_VALIDATED_POLICY
    COGNITION_ROLE_IS_ASSIGNED_AT_ACTIVATION_NOT_REGISTRATION_POLICY
    ORCHESTRATION_MUST_USE_ACTIVATION_LAYER_NOT_BARE_INVOCATION_POLICY

Public API
----------
Enums::

    NodeActivationState
    NodeCognitionRole
    ActivationTransitionReason
    ActivationEligibilityOutcome

Dataclasses::

    NodeActivationContext
    NodeActivationEligibilityDecision
    NodeActivationTransitionResult
    NodeActivationContextSnapshot
    NodeActivationPolicy

Functions::

    evaluate_activation_eligibility(node_id, role, *, registry=None, governor=None,
                                    policy=None) -> NodeActivationEligibilityDecision
    transition_activation_state(context, target_state, reason, *,
                                policy=None) -> NodeActivationTransitionResult
    build_activation_context_snapshot(contexts, *,
                                      policy=None) -> NodeActivationContextSnapshot
    get_activation_summary(contexts, *, policy=None) -> dict
    build_default_activation_policy() -> NodeActivationPolicy
"""

from __future__ import annotations

import copy
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.Nodes.CognitionActivation")

# Module-level optional import for NodeFabricRegistry singleton access.
# Imported here so that tests can patch
# `core.node_cognition_activation.get_node_fabric_registry`.
try:
    from core.nodes.node_fabric_registry import get_node_fabric_registry  # noqa: F401
except ImportError:
    get_node_fabric_registry = None  # type: ignore[assignment]

# ===========================================================================
# Authority sentinels
# ===========================================================================

NODE_COGNITION_ACTIVATION_IS_AUTHORITY: str = (
    "NODE_COGNITION_ACTIVATION::PR14_AUTHORITY_V1: "
    "core/node_cognition_activation.py is the canonical authority for the "
    "cognition-oriented node activation layer.  It defines activation states, "
    "transitions, roles, eligibility rules, and policy contracts that sit "
    "above raw tool/capability invocation without replacing the unified "
    "executor or canonical runtime registry."
)

NODE_COGNITION_ACTIVATION_PR14_SENTINEL: str = (
    "NODE_COGNITION_ACTIVATION::PR14_SENTINEL_V1"
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

ACTIVATION_LAYER_SITS_ABOVE_INVOCATION_SUBSTRATE_POLICY: str = (
    "NODE_COGNITION_ACTIVATION::ABOVE_SUBSTRATE_POLICY_V1: "
    "The cognition-oriented activation layer sits above raw node invocation "
    "(core.node_invocation / UnifiedNodeExecutor) and above capability/tool "
    "exposure (core.node_governance_runtime).  It does not replace either "
    "substrate.  Higher-level orchestration that needs to activate nodes in a "
    "cognitive context MUST use this layer rather than directly constructing "
    "NodeInvocationEnvelopes."
)

ACTIVATION_ELIGIBILITY_REQUIRES_GOVERNANCE_CLEARANCE_POLICY: str = (
    "NODE_COGNITION_ACTIVATION::GOVERNANCE_CLEARANCE_POLICY_V1: "
    "A node may only enter the SELECTED activation state if it is also "
    "governance-eligible at the invocation level (i.e. not archived, "
    "deprecated, unhealthy, or readiness-gap).  Activation eligibility "
    "evaluation calls evaluate_node_governance_eligibility() as a prerequisite "
    "gate before applying any cognition-specific activation policy."
)

ACTIVATION_STATE_TRANSITIONS_ARE_VALIDATED_POLICY: str = (
    "NODE_COGNITION_ACTIVATION::VALIDATED_TRANSITIONS_POLICY_V1: "
    "All activation-state transitions are validated against the canonical "
    "transition table defined in VALID_ACTIVATION_TRANSITIONS.  Illegal "
    "transitions (e.g. RETIRED -> SELECTED, BLOCKED -> ACTIVE) are rejected "
    "with a structured NodeActivationTransitionResult carrying "
    "transition_allowed=False and an explicit rejection_reason."
)

COGNITION_ROLE_IS_ASSIGNED_AT_ACTIVATION_NOT_REGISTRATION_POLICY: str = (
    "NODE_COGNITION_ACTIVATION::ROLE_AT_ACTIVATION_POLICY_V1: "
    "A node's cognitive role (PLANNING, ACTING, SENSING, MEMORY, "
    "COORDINATION, OBSERVER) is assigned at activation time in a specific "
    "task/session context.  It is NOT a static property of the node's "
    "registration record.  The same node may serve different cognitive roles "
    "in different task contexts."
)

ORCHESTRATION_MUST_USE_ACTIVATION_LAYER_NOT_BARE_INVOCATION_POLICY: str = (
    "NODE_COGNITION_ACTIVATION::ORCHESTRATION_PATH_POLICY_V1: "
    "Higher-level orchestration and planning layers that interact with nodes "
    "in a cognition-aware context MUST go through the activation layer "
    "(evaluate_activation_eligibility + transition_activation_state) rather "
    "than directly constructing NodeInvocationEnvelopes.  Direct bare "
    "invocation bypasses activation-state tracking, role assignment, and "
    "policy-aware selection and must not be used from orchestration paths."
)

# ===========================================================================
# NodeActivationState enum
# ===========================================================================


class NodeActivationState(str, Enum):
    """Canonical set of activation states for a node in a cognitive context.

    Attributes
    ----------
    CANDIDATE:
        The node has been identified as a potential participant but has not
        yet been evaluated for eligibility.  This is the entry state.
    ELIGIBLE:
        The node has passed governance + activation eligibility checks and
        may be selected for a cognitive role.  It is not yet active.
    SELECTED:
        The node has been chosen for a specific cognitive role in the current
        task/session context.  Execution has not yet begun.
    ACTIVE:
        The node is currently executing or participating in the cognitive
        context (e.g. contributing to planning, sensing, memory retrieval).
    SUSPENDED:
        The node was previously ACTIVE but has been temporarily paused by
        the orchestration layer.  It may be resumed.
    BLOCKED:
        The node cannot proceed due to a dependency, resource, or policy
        constraint.  It may become ELIGIBLE again when the constraint lifts.
    RETIRED:
        The node has completed its role in the current cognitive context.
        This is a terminal state for a given context; the node itself remains
        in the registry.
    EXCLUDED:
        The node failed eligibility or was explicitly excluded by policy.
        It will not participate in the current cognitive context.
    """

    CANDIDATE = "candidate"
    ELIGIBLE = "eligible"
    SELECTED = "selected"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"
    RETIRED = "retired"
    EXCLUDED = "excluded"


# ===========================================================================
# NodeCognitionRole enum
# ===========================================================================


class NodeCognitionRole(str, Enum):
    """Cognitive role assigned to an activated node within a task context.

    Attributes
    ----------
    PLANNING:
        The node contributes to goal decomposition, plan generation, or
        strategy selection.
    ACTING:
        The node executes actions, produces outputs, or drives state changes.
    SENSING:
        The node gathers, transforms, or enriches perception inputs.
    MEMORY:
        The node reads from or writes to memory/context surfaces.
    COORDINATION:
        The node manages dependencies, sequencing, or inter-node messaging.
    OBSERVER:
        The node passively monitors the context without producing primary
        outputs.  Used for logging, tracing, and meta-cognition.
    UNASSIGNED:
        Role has not yet been determined.  Nodes in CANDIDATE or ELIGIBLE
        states typically carry this role.
    """

    PLANNING = "planning"
    ACTING = "acting"
    SENSING = "sensing"
    MEMORY = "memory"
    COORDINATION = "coordination"
    OBSERVER = "observer"
    UNASSIGNED = "unassigned"


# ===========================================================================
# ActivationTransitionReason enum
# ===========================================================================


class ActivationTransitionReason(str, Enum):
    """Semantic reason codes for activation-state transitions.

    Used to provide machine-readable rationale in
    :class:`NodeActivationTransitionResult` and audit traces.
    """

    ELIGIBILITY_PASSED = "eligibility_passed"
    GOVERNANCE_CLEARED = "governance_cleared"
    ROLE_ASSIGNED = "role_assigned"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    ORCHESTRATOR_SUSPENDED = "orchestrator_suspended"
    ORCHESTRATOR_RESUMED = "orchestrator_resumed"
    DEPENDENCY_BLOCKED = "dependency_blocked"
    CONSTRAINT_LIFTED = "constraint_lifted"
    CONTEXT_RETIRED = "context_retired"
    POLICY_EXCLUDED = "policy_excluded"
    GOVERNANCE_FAILED = "governance_failed"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    EXPLICIT_ORCHESTRATOR_RETIRE = "explicit_orchestrator_retire"


# ===========================================================================
# ActivationEligibilityOutcome enum
# ===========================================================================


class ActivationEligibilityOutcome(str, Enum):
    """Result codes for :func:`evaluate_activation_eligibility`."""

    ELIGIBLE = "eligible"
    GOVERNANCE_INELIGIBLE = "governance_ineligible"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    ROLE_CONFLICT = "role_conflict"
    POLICY_EXCLUDED = "policy_excluded"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    UNREGISTERED_NODE = "unregistered_node"


# ===========================================================================
# Canonical transition table
# ===========================================================================

#: Legal state transitions (from_state -> set_of_valid_to_states).
VALID_ACTIVATION_TRANSITIONS: Dict[NodeActivationState, Set[NodeActivationState]] = {
    NodeActivationState.CANDIDATE: {
        NodeActivationState.ELIGIBLE,
        NodeActivationState.EXCLUDED,
    },
    NodeActivationState.ELIGIBLE: {
        NodeActivationState.SELECTED,
        NodeActivationState.BLOCKED,
        NodeActivationState.EXCLUDED,
    },
    NodeActivationState.SELECTED: {
        NodeActivationState.ACTIVE,
        NodeActivationState.BLOCKED,
        NodeActivationState.EXCLUDED,
        NodeActivationState.RETIRED,
    },
    NodeActivationState.ACTIVE: {
        NodeActivationState.SUSPENDED,
        NodeActivationState.RETIRED,
        NodeActivationState.BLOCKED,
    },
    NodeActivationState.SUSPENDED: {
        NodeActivationState.ACTIVE,
        NodeActivationState.RETIRED,
        NodeActivationState.EXCLUDED,
    },
    NodeActivationState.BLOCKED: {
        NodeActivationState.ELIGIBLE,
        NodeActivationState.EXCLUDED,
        NodeActivationState.RETIRED,
    },
    # Terminal states — no valid outgoing transitions within a context.
    NodeActivationState.RETIRED: set(),
    NodeActivationState.EXCLUDED: set(),
}

# ===========================================================================
# NodeActivationContext dataclass
# ===========================================================================


@dataclass
class NodeActivationContext:
    """Activation record for a single node within a task/session context.

    This is the primary data object produced and consumed by the activation
    layer.  It records the node's current activation state and cognitive
    role, plus enough context to trace back to the canonical runtime registry
    and invocation authority.

    Attributes
    ----------
    node_id:
        Identifier of the node in :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`.
    session_id:
        Identifier of the session or task context in which this activation
        record is live.
    activation_id:
        Unique identifier for this specific activation record.  Generated
        automatically if not provided.
    state:
        Current :class:`NodeActivationState` of this node in the context.
    role:
        :class:`NodeCognitionRole` assigned to this node.  UNASSIGNED until
        the node reaches SELECTED state.
    activation_reason:
        Human-readable string explaining why this activation record was
        created.
    last_transition_reason:
        :class:`ActivationTransitionReason` code for the most recent
        state transition.
    governance_cleared:
        ``True`` if the node has passed the governance eligibility gate
        (which is a prerequisite for ELIGIBLE state).
    eligible_at:
        Unix timestamp when the node first reached ELIGIBLE state, or
        ``None`` if it has not.
    selected_at:
        Unix timestamp when the node was SELECTED, or ``None``.
    activated_at:
        Unix timestamp when the node became ACTIVE, or ``None``.
    retired_at:
        Unix timestamp when the node entered RETIRED state, or ``None``.
    diagnostic_context:
        Freeform dict for diagnostic metadata (e.g. exclusion reasons,
        policy notes, governance decision details).
    """

    node_id: str
    session_id: str
    activation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: NodeActivationState = NodeActivationState.CANDIDATE
    role: NodeCognitionRole = NodeCognitionRole.UNASSIGNED
    activation_reason: str = ""
    last_transition_reason: Optional[ActivationTransitionReason] = None
    governance_cleared: bool = False
    eligible_at: Optional[float] = None
    selected_at: Optional[float] = None
    activated_at: Optional[float] = None
    retired_at: Optional[float] = None
    diagnostic_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of this context."""
        return {
            "node_id": self.node_id,
            "session_id": self.session_id,
            "activation_id": self.activation_id,
            "state": self.state.value,
            "role": self.role.value,
            "activation_reason": self.activation_reason,
            "last_transition_reason": (
                self.last_transition_reason.value
                if self.last_transition_reason is not None
                else None
            ),
            "governance_cleared": self.governance_cleared,
            "eligible_at": self.eligible_at,
            "selected_at": self.selected_at,
            "activated_at": self.activated_at,
            "retired_at": self.retired_at,
            "diagnostic_context": self.diagnostic_context,
        }

    @property
    def is_terminal(self) -> bool:
        """``True`` when the context is in a terminal state (RETIRED or EXCLUDED)."""
        return self.state in (NodeActivationState.RETIRED, NodeActivationState.EXCLUDED)

    @property
    def is_participating(self) -> bool:
        """``True`` when the node is actively contributing (SELECTED or ACTIVE)."""
        return self.state in (NodeActivationState.SELECTED, NodeActivationState.ACTIVE)


# ===========================================================================
# NodeActivationEligibilityDecision dataclass
# ===========================================================================


@dataclass
class NodeActivationEligibilityDecision:
    """Result of :func:`evaluate_activation_eligibility`.

    Attributes
    ----------
    node_id:
        The node identifier that was evaluated.
    outcome:
        :class:`ActivationEligibilityOutcome` describing the result.
    eligible:
        ``True`` when the node may enter SELECTED activation state.
    denial_reasons:
        Ordered list of reason strings (non-empty only when ``eligible`` is
        ``False``).
    governance_decision_summary:
        Summary dict from the governance eligibility evaluation, or ``None``
        if governance could not be evaluated.
    policy_notes:
        List of policy-level notes that informed this decision.
    diagnostic_context:
        Freeform dict for additional diagnostic metadata.
    """

    node_id: str
    outcome: ActivationEligibilityOutcome
    eligible: bool
    denial_reasons: List[str] = field(default_factory=list)
    governance_decision_summary: Optional[Dict[str, Any]] = None
    policy_notes: List[str] = field(default_factory=list)
    diagnostic_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "outcome": self.outcome.value,
            "eligible": self.eligible,
            "denial_reasons": self.denial_reasons,
            "governance_decision_summary": self.governance_decision_summary,
            "policy_notes": self.policy_notes,
            "diagnostic_context": self.diagnostic_context,
        }


# ===========================================================================
# NodeActivationTransitionResult dataclass
# ===========================================================================


@dataclass
class NodeActivationTransitionResult:
    """Result of :func:`transition_activation_state`.

    Attributes
    ----------
    node_id:
        The node identifier.
    from_state:
        The state the context was in before the attempted transition.
    to_state:
        The target state that was requested.
    transition_allowed:
        ``True`` when the transition was valid and has been applied.
    rejection_reason:
        Non-empty string explaining why the transition was rejected, when
        ``transition_allowed`` is ``False``.
    applied_reason:
        :class:`ActivationTransitionReason` code provided by the caller.
    updated_context:
        The updated :class:`NodeActivationContext` when the transition was
        allowed, or the original context when rejected.
    diagnostic_context:
        Freeform dict for additional diagnostic metadata.
    """

    node_id: str
    from_state: NodeActivationState
    to_state: NodeActivationState
    transition_allowed: bool
    rejection_reason: str = ""
    applied_reason: Optional[ActivationTransitionReason] = None
    updated_context: Optional[NodeActivationContext] = None
    diagnostic_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "transition_allowed": self.transition_allowed,
            "rejection_reason": self.rejection_reason,
            "applied_reason": (
                self.applied_reason.value if self.applied_reason is not None else None
            ),
            "updated_context": (
                self.updated_context.to_dict() if self.updated_context is not None else None
            ),
            "diagnostic_context": self.diagnostic_context,
        }


# ===========================================================================
# NodeActivationContextSnapshot dataclass
# ===========================================================================


@dataclass
class NodeActivationContextSnapshot:
    """Snapshot of all activation contexts for a session or system-wide view.

    Attributes
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    session_id:
        Session or task context this snapshot covers, or ``"system"`` for a
        system-wide view.
    total_contexts:
        Total number of contexts in this snapshot.
    candidate_count:
        Nodes in CANDIDATE state.
    eligible_count:
        Nodes in ELIGIBLE state.
    selected_count:
        Nodes in SELECTED state.
    active_count:
        Nodes in ACTIVE state (currently executing/participating).
    suspended_count:
        Nodes in SUSPENDED state.
    blocked_count:
        Nodes in BLOCKED state.
    retired_count:
        Nodes in RETIRED state.
    excluded_count:
        Nodes in EXCLUDED state.
    contexts:
        The full list of :class:`NodeActivationContext` objects in this
        snapshot.
    snapshot_at:
        Unix timestamp when the snapshot was assembled.
    authority:
        Reference to :data:`NODE_COGNITION_ACTIVATION_IS_AUTHORITY`.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = "system"
    total_contexts: int = 0
    candidate_count: int = 0
    eligible_count: int = 0
    selected_count: int = 0
    active_count: int = 0
    suspended_count: int = 0
    blocked_count: int = 0
    retired_count: int = 0
    excluded_count: int = 0
    contexts: List[NodeActivationContext] = field(default_factory=list)
    snapshot_at: float = field(default_factory=time.time)
    authority: str = field(default=NODE_COGNITION_ACTIVATION_IS_AUTHORITY)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "total_contexts": self.total_contexts,
            "candidate_count": self.candidate_count,
            "eligible_count": self.eligible_count,
            "selected_count": self.selected_count,
            "active_count": self.active_count,
            "suspended_count": self.suspended_count,
            "blocked_count": self.blocked_count,
            "retired_count": self.retired_count,
            "excluded_count": self.excluded_count,
            "contexts": [c.to_dict() for c in self.contexts],
            "snapshot_at": self.snapshot_at,
            "authority": self.authority,
        }


# ===========================================================================
# NodeActivationPolicy dataclass
# ===========================================================================


@dataclass
class NodeActivationPolicy:
    """Container for policy-aware activation rules.

    Higher-level orchestration layers can configure this object and pass it
    to :func:`evaluate_activation_eligibility`,
    :func:`transition_activation_state`, and
    :func:`build_activation_context_snapshot` to apply context-specific
    policy without modifying the runtime or invocation layers.

    Attributes
    ----------
    max_active_per_role:
        Maximum number of simultaneously ACTIVE nodes per
        :class:`NodeCognitionRole`.  ``None`` means no limit.
    require_governance_clearance:
        When ``True`` (the default), activation eligibility evaluation will
        consult the governance runtime before returning ELIGIBLE.  Setting
        this to ``False`` is for testing and internal-only contexts only.
    excluded_node_ids:
        Explicit set of node identifiers that are excluded from cognition
        activation regardless of governance state.
    allowed_roles_for_unregistered:
        Roles that an unregistered (non-fabric-enrolled) node may still be
        given.  Empty set means unregistered nodes are excluded from all
        roles by default.
    policy_label:
        Human-readable label for this policy instance (used in diagnostics).
    """

    max_active_per_role: Optional[Dict[str, int]] = None
    require_governance_clearance: bool = True
    excluded_node_ids: Set[str] = field(default_factory=set)
    allowed_roles_for_unregistered: Set[NodeCognitionRole] = field(default_factory=set)
    policy_label: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_active_per_role": self.max_active_per_role,
            "require_governance_clearance": self.require_governance_clearance,
            "excluded_node_ids": list(self.excluded_node_ids),
            "allowed_roles_for_unregistered": [
                r.value for r in self.allowed_roles_for_unregistered
            ],
            "policy_label": self.policy_label,
        }


# ===========================================================================
# Public functions
# ===========================================================================


def build_default_activation_policy() -> NodeActivationPolicy:
    """Return the canonical default :class:`NodeActivationPolicy`.

    The defaults are:
    - No per-role active-node cap (``max_active_per_role=None``)
    - Governance clearance required (``require_governance_clearance=True``)
    - No excluded nodes
    - No unregistered-node role allowances
    """
    return NodeActivationPolicy(
        max_active_per_role=None,
        require_governance_clearance=True,
        excluded_node_ids=set(),
        allowed_roles_for_unregistered=set(),
        policy_label="default",
    )


def evaluate_activation_eligibility(
    node_id: str,
    role: NodeCognitionRole,
    *,
    registry: Any = None,
    governor: Any = None,
    policy: Optional[NodeActivationPolicy] = None,
    active_contexts: Optional[List[NodeActivationContext]] = None,
) -> NodeActivationEligibilityDecision:
    """Evaluate whether *node_id* is eligible to be activated for *role*.

    This is a policy-aware check that:

    1. Checks that *node_id* is not in the policy's ``excluded_node_ids``.
    2. Resolves :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
       (or uses the supplied *registry* stub) to check if the node is enrolled.
    3. If ``policy.require_governance_clearance`` is True, consults
       :func:`~core.node_governance_runtime.evaluate_node_governance_eligibility`
       on the registry record.
    4. Checks per-role capacity caps from *policy*.
    5. Returns a :class:`NodeActivationEligibilityDecision` with all findings.

    Parameters
    ----------
    node_id:
        The node identifier to evaluate.
    role:
        The :class:`NodeCognitionRole` the caller wants to activate the node
        for.
    registry:
        Optional :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
        instance.  If ``None``, the function attempts to resolve the singleton
        via :func:`~core.nodes.node_fabric_registry.get_node_fabric_registry`.
    governor:
        Optional :class:`~core.node_lifecycle_governor.NodeLifecycleGovernor`
        instance passed through to governance evaluation.
    policy:
        Optional :class:`NodeActivationPolicy`.  Defaults to
        :func:`build_default_activation_policy`.
    active_contexts:
        Optional list of currently active :class:`NodeActivationContext` objects
        used to check per-role capacity caps.

    Returns
    -------
    NodeActivationEligibilityDecision
    """
    if policy is None:
        policy = build_default_activation_policy()
    if active_contexts is None:
        active_contexts = []

    denial_reasons: List[str] = []
    policy_notes: List[str] = []
    governance_decision_summary: Optional[Dict[str, Any]] = None

    # -----------------------------------------------------------------------
    # 1. Policy-level exclusion check
    # -----------------------------------------------------------------------
    if node_id in policy.excluded_node_ids:
        denial_reasons.append(f"node_id '{node_id}' is in policy.excluded_node_ids")
        policy_notes.append(
            f"policy_label={policy.policy_label!r}: node explicitly excluded"
        )
        return NodeActivationEligibilityDecision(
            node_id=node_id,
            outcome=ActivationEligibilityOutcome.POLICY_EXCLUDED,
            eligible=False,
            denial_reasons=denial_reasons,
            governance_decision_summary=None,
            policy_notes=policy_notes,
            diagnostic_context={"policy_label": policy.policy_label},
        )

    # -----------------------------------------------------------------------
    # 2. Resolve registry
    # -----------------------------------------------------------------------
    resolved_registry = _resolve_registry(registry)
    registry_available = resolved_registry is not None

    # -----------------------------------------------------------------------
    # 3. Node registration check
    # -----------------------------------------------------------------------
    node_record: Any = None
    if registry_available:
        try:
            node_record = _get_node_record(resolved_registry, node_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "evaluate_activation_eligibility: error fetching node record for "
                "node_id=%s: %s",
                node_id,
                exc,
            )
            node_record = None

    is_registered = node_record is not None

    if not is_registered:
        # Unregistered nodes may be allowed for specific roles by policy.
        if role not in policy.allowed_roles_for_unregistered:
            denial_reasons.append(
                f"node_id '{node_id}' is not enrolled in NodeFabricRegistry and "
                f"role '{role.value}' is not in policy.allowed_roles_for_unregistered"
            )
            outcome = (
                ActivationEligibilityOutcome.REGISTRY_UNAVAILABLE
                if not registry_available
                else ActivationEligibilityOutcome.UNREGISTERED_NODE
            )
            return NodeActivationEligibilityDecision(
                node_id=node_id,
                outcome=outcome,
                eligible=False,
                denial_reasons=denial_reasons,
                governance_decision_summary=None,
                policy_notes=policy_notes,
                diagnostic_context={
                    "registry_available": registry_available,
                    "is_registered": False,
                },
            )
        else:
            policy_notes.append(
                f"node_id '{node_id}' is unregistered but role '{role.value}' "
                "is permitted by policy.allowed_roles_for_unregistered"
            )

    # -----------------------------------------------------------------------
    # 4. Governance clearance (only for registered nodes)
    # -----------------------------------------------------------------------
    if policy.require_governance_clearance and is_registered and node_record is not None:
        gov_decision = _evaluate_governance(node_record, governor=governor)
        if gov_decision is not None:
            governance_decision_summary = {
                "node_id": getattr(gov_decision, "node_id", node_id),
                "eligible": getattr(gov_decision, "eligible", None),
                "exclusion_reasons": getattr(gov_decision, "exclusion_reasons", []),
                "governor_consulted": getattr(gov_decision, "governor_consulted", False),
            }
            if not getattr(gov_decision, "eligible", True):
                denial_reasons.append(
                    "node is governance-ineligible: "
                    + ", ".join(
                        str(r) for r in getattr(gov_decision, "exclusion_reasons", [])
                    )
                )
                return NodeActivationEligibilityDecision(
                    node_id=node_id,
                    outcome=ActivationEligibilityOutcome.GOVERNANCE_INELIGIBLE,
                    eligible=False,
                    denial_reasons=denial_reasons,
                    governance_decision_summary=governance_decision_summary,
                    policy_notes=policy_notes,
                    diagnostic_context={},
                )
        elif policy.require_governance_clearance:
            policy_notes.append(
                "governance evaluation unavailable; proceeding without clearance check"
            )

    # -----------------------------------------------------------------------
    # 5. Per-role capacity check
    # -----------------------------------------------------------------------
    if policy.max_active_per_role is not None:
        cap = policy.max_active_per_role.get(role.value)
        if cap is not None:
            current_active_for_role = sum(
                1
                for ctx in active_contexts
                if ctx.role == role and ctx.state == NodeActivationState.ACTIVE
            )
            if current_active_for_role >= cap:
                denial_reasons.append(
                    f"role '{role.value}' capacity cap ({cap}) reached; "
                    f"currently active: {current_active_for_role}"
                )
                policy_notes.append(
                    f"policy_label={policy.policy_label!r}: "
                    f"max_active_per_role[{role.value!r}]={cap}"
                )
                return NodeActivationEligibilityDecision(
                    node_id=node_id,
                    outcome=ActivationEligibilityOutcome.CAPACITY_EXCEEDED,
                    eligible=False,
                    denial_reasons=denial_reasons,
                    governance_decision_summary=governance_decision_summary,
                    policy_notes=policy_notes,
                    diagnostic_context={
                        "current_active_for_role": current_active_for_role,
                        "cap": cap,
                    },
                )

    # -----------------------------------------------------------------------
    # 6. Eligible
    # -----------------------------------------------------------------------
    policy_notes.append(
        f"node_id '{node_id}' passed all activation eligibility checks for "
        f"role '{role.value}'"
    )
    return NodeActivationEligibilityDecision(
        node_id=node_id,
        outcome=ActivationEligibilityOutcome.ELIGIBLE,
        eligible=True,
        denial_reasons=[],
        governance_decision_summary=governance_decision_summary,
        policy_notes=policy_notes,
        diagnostic_context={
            "registry_available": registry_available,
            "is_registered": is_registered,
        },
    )


def transition_activation_state(
    context: NodeActivationContext,
    target_state: NodeActivationState,
    reason: ActivationTransitionReason,
    *,
    policy: Optional[NodeActivationPolicy] = None,
) -> NodeActivationTransitionResult:
    """Validate and apply an activation-state transition.

    Checks *target_state* against :data:`VALID_ACTIVATION_TRANSITIONS` for
    the context's current state.  If the transition is valid, a new
    :class:`NodeActivationContext` is returned with the updated state and
    timestamps.  If the transition is invalid, the original context is
    returned unchanged along with a rejection reason.

    Parameters
    ----------
    context:
        The current :class:`NodeActivationContext`.
    target_state:
        The desired :class:`NodeActivationState` to transition to.
    reason:
        :class:`ActivationTransitionReason` code for this transition.
    policy:
        Optional :class:`NodeActivationPolicy`.  Currently used only for
        audit/diagnostics.

    Returns
    -------
    NodeActivationTransitionResult
    """
    from_state = context.state
    valid_targets = VALID_ACTIVATION_TRANSITIONS.get(from_state, set())

    if target_state not in valid_targets:
        return NodeActivationTransitionResult(
            node_id=context.node_id,
            from_state=from_state,
            to_state=target_state,
            transition_allowed=False,
            rejection_reason=(
                f"transition {from_state.value!r} -> {target_state.value!r} "
                "is not in VALID_ACTIVATION_TRANSITIONS"
            ),
            applied_reason=reason,
            updated_context=context,
            diagnostic_context={
                "valid_targets": [s.value for s in valid_targets],
                "policy_label": policy.policy_label if policy is not None else "none",
            },
        )

    # Build an updated copy of the context.
    updated = copy.copy(context)
    updated.diagnostic_context = dict(context.diagnostic_context)
    updated.state = target_state
    updated.last_transition_reason = reason
    now = time.time()

    if target_state == NodeActivationState.ELIGIBLE and updated.eligible_at is None:
        updated.eligible_at = now
        updated.governance_cleared = True
    elif target_state == NodeActivationState.SELECTED and updated.selected_at is None:
        updated.selected_at = now
    elif target_state == NodeActivationState.ACTIVE and updated.activated_at is None:
        updated.activated_at = now
    elif target_state == NodeActivationState.RETIRED and updated.retired_at is None:
        updated.retired_at = now

    logger.debug(
        "activation state transition: node_id=%s session_id=%s %s -> %s reason=%s",
        context.node_id,
        context.session_id,
        from_state.value,
        target_state.value,
        reason.value,
    )

    return NodeActivationTransitionResult(
        node_id=context.node_id,
        from_state=from_state,
        to_state=target_state,
        transition_allowed=True,
        rejection_reason="",
        applied_reason=reason,
        updated_context=updated,
        diagnostic_context={
            "policy_label": policy.policy_label if policy is not None else "none",
        },
    )


def build_activation_context_snapshot(
    contexts: List[NodeActivationContext],
    *,
    session_id: str = "system",
    policy: Optional[NodeActivationPolicy] = None,
) -> NodeActivationContextSnapshot:
    """Assemble a :class:`NodeActivationContextSnapshot` from a list of contexts.

    Parameters
    ----------
    contexts:
        List of :class:`NodeActivationContext` objects to summarise.
    session_id:
        The session or task context label for this snapshot.
    policy:
        Optional :class:`NodeActivationPolicy` (used only for metadata).

    Returns
    -------
    NodeActivationContextSnapshot
    """
    counts: Dict[NodeActivationState, int] = {s: 0 for s in NodeActivationState}
    for ctx in contexts:
        counts[ctx.state] = counts.get(ctx.state, 0) + 1

    return NodeActivationContextSnapshot(
        session_id=session_id,
        total_contexts=len(contexts),
        candidate_count=counts[NodeActivationState.CANDIDATE],
        eligible_count=counts[NodeActivationState.ELIGIBLE],
        selected_count=counts[NodeActivationState.SELECTED],
        active_count=counts[NodeActivationState.ACTIVE],
        suspended_count=counts[NodeActivationState.SUSPENDED],
        blocked_count=counts[NodeActivationState.BLOCKED],
        retired_count=counts[NodeActivationState.RETIRED],
        excluded_count=counts[NodeActivationState.EXCLUDED],
        contexts=list(contexts),
    )


def get_activation_summary(
    contexts: List[NodeActivationContext],
    *,
    policy: Optional[NodeActivationPolicy] = None,
) -> Dict[str, Any]:
    """Return a compact summary dict for dashboard and diagnostic surfaces.

    Parameters
    ----------
    contexts:
        List of :class:`NodeActivationContext` objects.
    policy:
        Optional :class:`NodeActivationPolicy`.

    Returns
    -------
    dict
        Keys: ``total_contexts``, ``active_count``, ``selected_count``,
        ``eligible_count``, ``candidate_count``, ``suspended_count``,
        ``blocked_count``, ``retired_count``, ``excluded_count``,
        ``participating_count``, ``authority``.
    """
    snapshot = build_activation_context_snapshot(contexts, policy=policy)
    return {
        "total_contexts": snapshot.total_contexts,
        "active_count": snapshot.active_count,
        "selected_count": snapshot.selected_count,
        "eligible_count": snapshot.eligible_count,
        "candidate_count": snapshot.candidate_count,
        "suspended_count": snapshot.suspended_count,
        "blocked_count": snapshot.blocked_count,
        "retired_count": snapshot.retired_count,
        "excluded_count": snapshot.excluded_count,
        "participating_count": snapshot.selected_count + snapshot.active_count,
        "authority": NODE_COGNITION_ACTIVATION_IS_AUTHORITY,
    }


# ===========================================================================
# Private helpers
# ===========================================================================


def _resolve_registry(registry: Any) -> Any:
    """Resolve NodeFabricRegistry from supplied value or singleton."""
    if registry is not None:
        return registry
    try:
        _get_reg = get_node_fabric_registry
        if _get_reg is None:
            from core.nodes.node_fabric_registry import (  # noqa: PLC0415
                get_node_fabric_registry as _get_reg,
            )
        if callable(_get_reg):
            return _get_reg()
    except Exception as exc:  # noqa: BLE001
        logger.debug("_resolve_registry: could not resolve NodeFabricRegistry: %s", exc)
    return None


def _get_node_record(registry: Any, node_id: str) -> Any:
    """Retrieve a node record from the registry by node_id.

    Returns ``None`` when the node is not found.
    """
    try:
        # NodeFabricRegistry exposes get_node(node_id) -> Optional[NodeRecord]
        if hasattr(registry, "get_node"):
            return registry.get_node(node_id)
        # Fallback: try list_nodes() and find by node_id
        if hasattr(registry, "list_nodes"):
            for record in registry.list_nodes():
                if getattr(record, "node_id", None) == node_id:
                    return record
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "_get_node_record: error fetching node_id=%s from registry: %s",
            node_id,
            exc,
        )
    return None


def _evaluate_governance(node_record: Any, governor: Any = None) -> Any:
    """Evaluate governance eligibility for a registered node record.

    Returns the :class:`~core.node_governance_runtime.NodeGovernanceEligibilityDecision`
    or ``None`` when the governance module is unavailable.
    """
    try:
        from core.node_governance_runtime import (  # noqa: PLC0415
            evaluate_node_governance_eligibility,
        )

        return evaluate_node_governance_eligibility(
            node_record, governor_record=governor
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("_evaluate_governance: governance evaluation unavailable: %s", exc)
    return None
