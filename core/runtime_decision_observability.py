#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.runtime_decision_observability
=====================================

PR-20 — Unified Runtime Decision Observability

Canonical **runtime decision observability** layer that consolidates the
explanation of how the canonical system reached key runtime decisions across:

- execution-path selection
- model/provider selection
- node activation readiness
- invocation denials
- cognitive execution hints
- memory-derived policy influence
- activation-budget influence
- task-semantic influence across text and multimodal flows
- planner/execution-posture influence on downstream candidate selection

Background
----------
PR-17 through PR-19 established real runtime decision influences operating in
or near the canonical path:

- PR-17: task-semantic model routing (task hint → text-only and multimodal paths)
- PR-18: cognitive activation budgeting (budget intensity → planner breadth)
- PR-19: memory-informed runtime bias (continuity/retrieval/novelty → planner posture)

Each influence layer was independently wired and provided per-module
diagnostics.  Without a unified observability surface those fragments are
difficult to reason about in combination.  This module consolidates them
into a single coherent explanation surface.

Design principles
-----------------
- **Reflects real decisions**: every field in a
  :class:`RuntimeDecisionExplanation` maps to an actual canonical decision
  point, not to a synthetic simulation.
- **Authority hierarchy preserved**: hard gates (governance, lifecycle denial,
  activation-context readiness) remain primary.  Soft influences (memory,
  cognitive posture, activation budget, task semantics) are represented as
  influence layers with explicit ``influence_class`` labels.
- **Non-duplicating**: this module assembles existing diagnostics from
  PR-17/18/19 authority modules — it does not re-compute them.
- **Aligned terminology**: ``InfluenceClass`` enum values are stable string
  identifiers used consistently across routing, cognition, node activation,
  memory, task semantics, and execution posture surfaces.

Influence classification
------------------------
+----------------------------+----------------------------------------------+
| InfluenceClass             | Meaning                                      |
+============================+==============================================+
| ``hard_gate``              | Governance / lifecycle denial — primary      |
|                            | authority.  When present, outcome is final.  |
+----------------------------+----------------------------------------------+
| ``soft_hint``              | Advisory execution-path preference.          |
+----------------------------+----------------------------------------------+
| ``policy_bias``            | Policy-derived direction (posture, strategy).|
+----------------------------+----------------------------------------------+
| ``topology_influence``     | Topology / context shape influenced the      |
|                            | candidate set or execution domain.           |
+----------------------------+----------------------------------------------+
| ``memory_influence``       | Memory-derived continuity/retrieval/novelty  |
|                            | posture biased execution strategy.           |
+----------------------------+----------------------------------------------+
| ``task_semantic_influence``| Task-type classification influenced model /  |
|                            | provider or planner strategy selection.      |
+----------------------------+----------------------------------------------+
| ``execution_posture``      | Planner execution-posture (breadth,          |
|                            | intensity, cognitive region) propagated into |
|                            | downstream decision surfaces.                |
+----------------------------+----------------------------------------------+

Authority sentinels
-------------------
RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY
    Asserts this module is the canonical unified runtime decision
    observability authority for PR-20.

RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL
    Machine-checkable sentinel confirming PR-20 observability is present.

Usage::

    from core.runtime_decision_observability import (
        build_runtime_decision_explanation,
        build_runtime_decision_diagnostics,
        RuntimeDecisionExplanation,
    )

    explanation = build_runtime_decision_explanation(
        execution_path="agent_execute",
        model_selected="gpt-4o",
        provider_selected="openai",
        task_hint="creative_generation",
        activation_budget_hint=budget_dict,
        memory_bias_hint=bias_dict,
        governance_decision=gov_dict,
        cognitive_hint_dict=cog_dict,
    )
    diagnostics = build_runtime_decision_diagnostics(explanation)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.RuntimeDecisionObservability")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY: str = (
    "RUNTIME_DECISION_OBSERVABILITY::CANONICAL_AUTHORITY: "
    "core.runtime_decision_observability is the canonical unified runtime "
    "decision observability layer for PR-20.  It consolidates explanations "
    "across execution-path selection, model/provider selection, node activation "
    "readiness, invocation denials, cognitive execution hints, memory-derived "
    "policy influence, activation-budget influence, task-semantic influence, and "
    "planner/execution-posture influence into a single coherent diagnostics surface."
)

RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL: str = (
    "RUNTIME_DECISION_OBSERVABILITY::PR20_SENTINEL: "
    "Unified runtime decision observability (PR-20) is present and active.  "
    "RuntimeDecisionExplanation consolidates PR-17 task-semantic, PR-18 "
    "activation-budget, PR-19 memory-bias, governance, and cognitive-posture "
    "influence layers into a single, canonical diagnostics surface."
)

# Policy sentinels
HARD_GATES_ARE_PRIMARY_AUTHORITY_POLICY: str = (
    "RUNTIME_DECISION_OBSERVABILITY::POLICY_1: "
    "Hard gates (governance denial, lifecycle denial, activation-context "
    "readiness) are ALWAYS the primary authority.  When a hard gate is present "
    "in RuntimeDecisionExplanation.hard_gates, the outcome is final.  Soft "
    "influence layers annotated as 'soft_hint', 'policy_bias', 'memory_influence', "
    "'task_semantic_influence', or 'execution_posture' are subordinate."
)

OBSERVABILITY_REFLECTS_REAL_DECISIONS_POLICY: str = (
    "RUNTIME_DECISION_OBSERVABILITY::POLICY_2: "
    "Every field in RuntimeDecisionExplanation maps to an actual canonical "
    "decision point.  This module MUST NOT invent explanations for decisions "
    "that were not actually made.  An influence layer is only included when the "
    "underlying authority module confirmed the influence was active."
)

INFLUENCE_LAYERS_ARE_NON_AUTHORITATIVE_POLICY: str = (
    "RUNTIME_DECISION_OBSERVABILITY::POLICY_3: "
    "Soft influence layers (memory_influence, task_semantic_influence, "
    "execution_posture, policy_bias) are advisory.  Their presence in a "
    "RuntimeDecisionExplanation MUST NOT be interpreted as a hard gate.  "
    "Operators may observe that an influence was active without it implying "
    "that it was the sole or binding cause of the outcome."
)

DIAGNOSTICS_SURFACE_IS_CANONICAL_NOT_PARALLEL_POLICY: str = (
    "RUNTIME_DECISION_OBSERVABILITY::POLICY_4: "
    "RuntimeDecisionExplanation assembles existing diagnostics from PR-17/18/19 "
    "authority modules.  It does not re-compute, duplicate, or replace canonical "
    "decision logic.  The observability surface remains downstream of real "
    "runtime authorities."
)

# ---------------------------------------------------------------------------
# InfluenceClass enum
# ---------------------------------------------------------------------------


class InfluenceClass(str, Enum):
    """Classification of an influence layer within a runtime decision.

    String values are stable identifiers for serialisation and logging.
    """

    HARD_GATE = "hard_gate"
    """Governance / lifecycle denial — primary authority.  When present, outcome is final."""

    SOFT_HINT = "soft_hint"
    """Advisory execution-path preference."""

    POLICY_BIAS = "policy_bias"
    """Policy-derived direction (posture, strategy, domain)."""

    TOPOLOGY_INFLUENCE = "topology_influence"
    """Topology / context shape influenced the candidate set or execution domain."""

    MEMORY_INFLUENCE = "memory_influence"
    """Memory-derived continuity/retrieval/novelty posture biased execution strategy."""

    TASK_SEMANTIC_INFLUENCE = "task_semantic_influence"
    """Task-type classification influenced model/provider or planner strategy selection."""

    EXECUTION_POSTURE = "execution_posture"
    """Planner execution-posture (breadth, intensity, cognitive region) propagated into downstream."""


# ---------------------------------------------------------------------------
# RuntimeDecisionRecord
# ---------------------------------------------------------------------------


@dataclass
class RuntimeDecisionRecord:
    """A single influence layer's contribution to a runtime decision.

    Each record captures one identifiable factor that was active during the
    decision, its classification, the authority that produced it, and any
    available detail.

    Attributes
    ----------
    layer_name:
        Short, stable identifier for the influence layer
        (e.g. ``"memory_bias"``, ``"task_semantic"``, ``"activation_budget"``).
    influence_class:
        :class:`InfluenceClass` value describing how this factor influenced
        the decision.
    active:
        ``True`` when this influence was confirmed active by the underlying
        authority module.  ``False`` when it was present but had no confirmed
        effect.
    authority_module:
        Python module path of the authority that produced this record.
    summary:
        Human-readable sentence describing what the layer did.
    detail:
        Freeform dict with supplemental diagnostics from the authority module.
    """

    layer_name: str
    influence_class: InfluenceClass
    active: bool
    authority_module: str = ""
    summary: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_name": self.layer_name,
            "influence_class": self.influence_class.value,
            "active": self.active,
            "authority_module": self.authority_module,
            "summary": self.summary,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RuntimeDecisionRecord":
        ic = d.get("influence_class", InfluenceClass.SOFT_HINT.value)
        try:
            ic_val = InfluenceClass(ic)
        except ValueError:
            ic_val = InfluenceClass.SOFT_HINT
        return cls(
            layer_name=d.get("layer_name", ""),
            influence_class=ic_val,
            active=bool(d.get("active", False)),
            authority_module=d.get("authority_module", ""),
            summary=d.get("summary", ""),
            detail=dict(d.get("detail") or {}),
        )


# ---------------------------------------------------------------------------
# RuntimeDecisionExplanation
# ---------------------------------------------------------------------------


@dataclass
class RuntimeDecisionExplanation:
    """Unified explanation of how the canonical runtime reached a key decision.

    Attributes
    ----------
    execution_path:
        The execution path that was selected (e.g. ``"agent_execute"``,
        ``"fallback_chat"``, ``"multimodal_route"``).
    model_selected:
        Model identifier that was selected for this request, if applicable.
    provider_selected:
        Provider identifier that was selected, if applicable.
    model_selection_reason:
        Human-readable reason why this model/provider was selected.
    task_hint:
        Task-semantic hint that was active during this decision, derived via
        PR-17 classify_task().
    task_semantic_influenced_routing:
        ``True`` when the task hint actually changed the routing decision
        (e.g. moved away from GENERAL fallback to a task-specific route).
    task_semantic_influenced_planner:
        ``True`` when the task hint influenced planner strategy selection.
    hard_gates:
        List of :class:`RuntimeDecisionRecord` entries with
        ``influence_class=HARD_GATE``.  When non-empty, one or more hard
        authority gates were active.
    soft_influences:
        List of :class:`RuntimeDecisionRecord` entries for soft influence
        layers (soft hints, policy biases, memory, task semantics, execution
        posture, topology).
    node_allowed:
        ``True`` when the governance gate allowed node activation/invocation.
        ``None`` when governance was not consulted.
    node_denial_reasons:
        Ordered list of reasons why the node was denied (empty when allowed).
    activation_budget_active:
        ``True`` when activation budget influence was confirmed active.
    activation_budget_mode:
        Breadth mode from the budget layer (``"narrow"`` / ``"moderate"`` /
        ``"broad"``), or ``None``.
    memory_bias_posture:
        Memory posture that was active (``"continuity"`` / ``"retrieval"`` /
        ``"novelty"``), or ``None``.
    memory_influenced_planner:
        ``True`` when memory bias confirmed it influenced planner strategy.
    cognitive_region:
        Cognitive region from the execution policy layer (``"PASSIVE"`` /
        ``"LIMINAL"`` / ``"MANIFEST"``), or ``None``.
    execution_path_preference:
        Execution-path preference from the cognitive execution hint (e.g.
        ``"direct"`` / ``"planning"`` / ``"deferred"``), or ``None``.
    execution_path_preference_binding:
        Explicit authority qualifier for ``execution_path_preference``.
        ``"advisory_only_non_binding"`` means this preference is surfaced as
        a soft signal and does not directly override canonical routing.
    execution_path_preference_authority:
        Stable label describing the authority class for execution-path
        preference (``"soft_hint_non_binding"``).
    planner_strategy:
        Execution strategy chosen by the planner (e.g. ``"single_agent"`` /
        ``"team_specialized"`` / ``"team_swarm"`` / ``"fractal"``), or ``None``.
    source_authority:
        Python module path of the authority that produced this explanation.
    assembled_at:
        Timestamp when the explanation was assembled.
    """

    execution_path: str = ""
    model_selected: Optional[str] = None
    provider_selected: Optional[str] = None
    model_selection_reason: Optional[str] = None
    task_hint: Optional[str] = None
    task_semantic_influenced_routing: bool = False
    task_semantic_influenced_planner: bool = False
    hard_gates: List[RuntimeDecisionRecord] = field(default_factory=list)
    soft_influences: List[RuntimeDecisionRecord] = field(default_factory=list)
    node_allowed: Optional[bool] = None
    node_denial_reasons: List[str] = field(default_factory=list)
    activation_budget_active: bool = False
    activation_budget_mode: Optional[str] = None
    memory_bias_posture: Optional[str] = None
    memory_influenced_planner: bool = False
    cognitive_region: Optional[str] = None
    execution_path_preference: Optional[str] = None
    execution_path_preference_binding: str = "advisory_only_non_binding"
    execution_path_preference_authority: str = "soft_hint_non_binding"
    planner_strategy: Optional[str] = None
    source_authority: str = "core.runtime_decision_observability"
    assembled_at: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    @property
    def has_hard_gate(self) -> bool:
        """True when at least one active hard gate is present."""
        return any(r.active for r in self.hard_gates)

    @property
    def active_influence_count(self) -> int:
        """Number of confirmed-active soft influence layers."""
        return sum(1 for r in self.soft_influences if r.active)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_path": self.execution_path,
            "model_selected": self.model_selected,
            "provider_selected": self.provider_selected,
            "model_selection_reason": self.model_selection_reason,
            "task_hint": self.task_hint,
            "task_semantic_influenced_routing": self.task_semantic_influenced_routing,
            "task_semantic_influenced_planner": self.task_semantic_influenced_planner,
            "hard_gates": [r.to_dict() for r in self.hard_gates],
            "soft_influences": [r.to_dict() for r in self.soft_influences],
            "node_allowed": self.node_allowed,
            "node_denial_reasons": list(self.node_denial_reasons),
            "activation_budget_active": self.activation_budget_active,
            "activation_budget_mode": self.activation_budget_mode,
            "memory_bias_posture": self.memory_bias_posture,
            "memory_influenced_planner": self.memory_influenced_planner,
            "cognitive_region": self.cognitive_region,
            "execution_path_preference": self.execution_path_preference,
            "execution_path_preference_binding": self.execution_path_preference_binding,
            "execution_path_preference_authority": self.execution_path_preference_authority,
            "planner_strategy": self.planner_strategy,
            "source_authority": self.source_authority,
            "assembled_at": self.assembled_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RuntimeDecisionExplanation":
        hard_gates = [
            RuntimeDecisionRecord.from_dict(r)
            for r in (d.get("hard_gates") or [])
        ]
        soft_influences = [
            RuntimeDecisionRecord.from_dict(r)
            for r in (d.get("soft_influences") or [])
        ]
        return cls(
            execution_path=d.get("execution_path", ""),
            model_selected=d.get("model_selected"),
            provider_selected=d.get("provider_selected"),
            model_selection_reason=d.get("model_selection_reason"),
            task_hint=d.get("task_hint"),
            task_semantic_influenced_routing=bool(d.get("task_semantic_influenced_routing", False)),
            task_semantic_influenced_planner=bool(d.get("task_semantic_influenced_planner", False)),
            hard_gates=hard_gates,
            soft_influences=soft_influences,
            node_allowed=d.get("node_allowed"),
            node_denial_reasons=list(d.get("node_denial_reasons") or []),
            activation_budget_active=bool(d.get("activation_budget_active", False)),
            activation_budget_mode=d.get("activation_budget_mode"),
            memory_bias_posture=d.get("memory_bias_posture"),
            memory_influenced_planner=bool(d.get("memory_influenced_planner", False)),
            cognitive_region=d.get("cognitive_region"),
            execution_path_preference=d.get("execution_path_preference"),
            execution_path_preference_binding=d.get(
                "execution_path_preference_binding", "advisory_only_non_binding"
            ),
            execution_path_preference_authority=d.get(
                "execution_path_preference_authority", "soft_hint_non_binding"
            ),
            planner_strategy=d.get("planner_strategy"),
            source_authority=d.get("source_authority", "core.runtime_decision_observability"),
            assembled_at=float(d.get("assembled_at", 0.0)),
        )


# ---------------------------------------------------------------------------
# Empty / fallback sentinel
# ---------------------------------------------------------------------------

EMPTY_RUNTIME_DECISION_EXPLANATION: RuntimeDecisionExplanation = RuntimeDecisionExplanation(
    execution_path="unknown",
    source_authority="core.runtime_decision_observability.EMPTY_SENTINEL",
)
"""Sentinel returned when no decision explanation can be assembled."""


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------


def build_runtime_decision_explanation(
    *,
    execution_path: str = "",
    model_selected: Optional[str] = None,
    provider_selected: Optional[str] = None,
    model_selection_reason: Optional[str] = None,
    task_hint: Optional[str] = None,
    task_semantic_influenced_routing: bool = False,
    task_semantic_influenced_planner: bool = False,
    activation_budget_hint: Optional[Dict[str, Any]] = None,
    memory_bias_hint: Optional[Dict[str, Any]] = None,
    governance_decision: Optional[Dict[str, Any]] = None,
    cognitive_hint_dict: Optional[Dict[str, Any]] = None,
    planner_strategy: Optional[str] = None,
    extra_records: Optional[List[RuntimeDecisionRecord]] = None,
) -> RuntimeDecisionExplanation:
    """Build a :class:`RuntimeDecisionExplanation` from canonical runtime signals.

    This function assembles an explanation from already-computed diagnostic
    dicts produced by:

    - PR-17 task-semantic routing (``task_hint``, ``task_semantic_influenced_*``)
    - PR-18 activation-budget layer (``activation_budget_hint``)
    - PR-19 memory-bias layer (``memory_bias_hint``)
    - PR-11 invocation governance (``governance_decision``)
    - PR-18 cognitive execution policy (``cognitive_hint_dict``)

    All parameters are optional.  The function degrades gracefully to a
    minimal explanation when signals are absent.

    Parameters
    ----------
    execution_path:
        The execution path that was selected.
    model_selected:
        Model identifier selected for this request.
    provider_selected:
        Provider identifier selected.
    model_selection_reason:
        Human-readable reason for model/provider selection.
    task_hint:
        Task-semantic hint active during the decision (PR-17).
    task_semantic_influenced_routing:
        Whether the task hint changed the routing decision away from the
        GENERAL/fallback default.
    task_semantic_influenced_planner:
        Whether the task hint influenced planner strategy selection.
    activation_budget_hint:
        Diagnostics dict from ``build_budget_diagnostics()`` (PR-18).
    memory_bias_hint:
        Diagnostics dict from ``build_memory_bias_diagnostics()`` (PR-19).
    governance_decision:
        Dict representation of a governance decision (PR-11), typically
        from ``build_invocation_denial_diagnostics()`` or
        ``NodeInvocationGovernanceDecision.to_dict()``.
    cognitive_hint_dict:
        Diagnostics dict from the cognitive execution-policy layer (PR-18).
    planner_strategy:
        Execution strategy chosen by the planner.
    extra_records:
        Additional :class:`RuntimeDecisionRecord` entries to append to
        ``soft_influences``.

    Returns
    -------
    RuntimeDecisionExplanation
        Populated explanation.  Never raises; degrades gracefully to
        :data:`EMPTY_RUNTIME_DECISION_EXPLANATION` on any error.
    """
    try:
        return _build_explanation_impl(
            execution_path=execution_path,
            model_selected=model_selected,
            provider_selected=provider_selected,
            model_selection_reason=model_selection_reason,
            task_hint=task_hint,
            task_semantic_influenced_routing=task_semantic_influenced_routing,
            task_semantic_influenced_planner=task_semantic_influenced_planner,
            activation_budget_hint=activation_budget_hint,
            memory_bias_hint=memory_bias_hint,
            governance_decision=governance_decision,
            cognitive_hint_dict=cognitive_hint_dict,
            planner_strategy=planner_strategy,
            extra_records=extra_records or [],
        )
    except Exception as exc:
        logger.debug("build_runtime_decision_explanation failed (returning empty): %s", exc)
        return EMPTY_RUNTIME_DECISION_EXPLANATION


def _build_explanation_impl(
    *,
    execution_path: str,
    model_selected: Optional[str],
    provider_selected: Optional[str],
    model_selection_reason: Optional[str],
    task_hint: Optional[str],
    task_semantic_influenced_routing: bool,
    task_semantic_influenced_planner: bool,
    activation_budget_hint: Optional[Dict[str, Any]],
    memory_bias_hint: Optional[Dict[str, Any]],
    governance_decision: Optional[Dict[str, Any]],
    cognitive_hint_dict: Optional[Dict[str, Any]],
    planner_strategy: Optional[str],
    extra_records: List[RuntimeDecisionRecord],
) -> RuntimeDecisionExplanation:
    hard_gates: List[RuntimeDecisionRecord] = []
    soft_influences: List[RuntimeDecisionRecord] = []

    # ------------------------------------------------------------------
    # 1. Governance / hard-gate layer (PR-11)
    # ------------------------------------------------------------------
    node_allowed: Optional[bool] = None
    node_denial_reasons: List[str] = []

    if governance_decision is not None:
        _eligible = governance_decision.get("eligible", governance_decision.get("allowed", True))
        _denial = governance_decision.get("denial_reasons") or governance_decision.get("exclusion_reasons") or []
        node_allowed = bool(_eligible)
        node_denial_reasons = list(_denial)
        _gov_active = not node_allowed
        hard_gates.append(RuntimeDecisionRecord(
            layer_name="invocation_governance",
            influence_class=InfluenceClass.HARD_GATE,
            active=_gov_active,
            authority_module="core.node_invocation_governance",
            summary=(
                f"Governance gate: node {'allowed' if node_allowed else 'denied'}"
                + (f" — {'; '.join(node_denial_reasons[:2])}" if node_denial_reasons else "")
            ),
            detail=dict(governance_decision),
        ))

    # ------------------------------------------------------------------
    # 2. Activation-budget influence layer (PR-18)
    # ------------------------------------------------------------------
    activation_budget_active = False
    activation_budget_mode: Optional[str] = None

    if activation_budget_hint is not None:
        _budg_influenced = bool(activation_budget_hint.get("influenced_runtime_decision", False))
        activation_budget_active = _budg_influenced
        activation_budget_mode = activation_budget_hint.get("breadth_mode")
        soft_influences.append(RuntimeDecisionRecord(
            layer_name="activation_budget",
            influence_class=InfluenceClass.EXECUTION_POSTURE,
            active=_budg_influenced,
            authority_module="core.cognitive.cognitive_activation_budget",
            summary=(
                f"Activation budget: breadth_mode={activation_budget_mode or 'unknown'}, "
                f"influenced={_budg_influenced}"
            ),
            detail=dict(activation_budget_hint),
        ))

    # ------------------------------------------------------------------
    # 3. Memory-bias influence layer (PR-19)
    # ------------------------------------------------------------------
    memory_bias_posture: Optional[str] = None
    memory_influenced_planner = False

    if memory_bias_hint is not None:
        _mem_posture = memory_bias_hint.get("posture")
        _mem_influenced = bool(memory_bias_hint.get("influenced_runtime_decision", False))
        memory_bias_posture = _mem_posture
        memory_influenced_planner = _mem_influenced
        soft_influences.append(RuntimeDecisionRecord(
            layer_name="memory_bias",
            influence_class=InfluenceClass.MEMORY_INFLUENCE,
            active=_mem_influenced,
            authority_module="core.cognitive.memory_bias_layer",
            summary=(
                f"Memory bias: posture={_mem_posture or 'unknown'}, "
                f"influenced={_mem_influenced}"
            ),
            detail=dict(memory_bias_hint),
        ))

    # ------------------------------------------------------------------
    # 4. Cognitive execution-hint / execution-posture layer (PR-18)
    # ------------------------------------------------------------------
    cognitive_region: Optional[str] = None
    execution_path_preference: Optional[str] = None

    if cognitive_hint_dict is not None:
        cognitive_region = cognitive_hint_dict.get("cognitive_region")
        execution_path_preference = cognitive_hint_dict.get("execution_path_preference")
        _cog_active = cognitive_region is not None
        soft_influences.append(RuntimeDecisionRecord(
            layer_name="cognitive_execution_policy",
            influence_class=InfluenceClass.SOFT_HINT,
            active=_cog_active,
            authority_module="core.cognitive.cognitive_execution_policy",
            summary=(
                f"Cognitive posture: region={cognitive_region or 'unknown'}, "
                f"path_pref={execution_path_preference or 'unknown'}"
            ),
            detail=dict(cognitive_hint_dict),
        ))

    # ------------------------------------------------------------------
    # 5. Task-semantic influence layer (PR-17)
    # ------------------------------------------------------------------
    if task_hint:
        soft_influences.append(RuntimeDecisionRecord(
            layer_name="task_semantic",
            influence_class=InfluenceClass.TASK_SEMANTIC_INFLUENCE,
            active=(task_semantic_influenced_routing or task_semantic_influenced_planner),
            authority_module="core.agent.kernel",
            summary=(
                f"Task semantic hint={task_hint!r}; "
                f"influenced_routing={task_semantic_influenced_routing}, "
                f"influenced_planner={task_semantic_influenced_planner}"
            ),
            detail={
                "task_hint": task_hint,
                "influenced_routing": task_semantic_influenced_routing,
                "influenced_planner": task_semantic_influenced_planner,
            },
        ))

    # ------------------------------------------------------------------
    # 6. Planner execution-posture layer
    # ------------------------------------------------------------------
    if planner_strategy is not None:
        _posture_active = bool(planner_strategy)
        # Track whether any soft layer drove the planner away from the default
        _driven_by_budget = activation_budget_active
        _driven_by_memory = memory_influenced_planner
        _driven_by_task = task_semantic_influenced_planner
        soft_influences.append(RuntimeDecisionRecord(
            layer_name="planner_strategy",
            influence_class=InfluenceClass.EXECUTION_POSTURE,
            active=_posture_active,
            authority_module="core.agent.execution_planner",
            summary=(
                f"Planner strategy={planner_strategy!r}; "
                f"driven_by: budget={_driven_by_budget}, memory={_driven_by_memory}, "
                f"task_semantic={_driven_by_task}"
            ),
            detail={
                "strategy": planner_strategy,
                "driven_by_activation_budget": _driven_by_budget,
                "driven_by_memory_bias": _driven_by_memory,
                "driven_by_task_semantic": _driven_by_task,
            },
        ))

    # ------------------------------------------------------------------
    # 7. Append caller-provided extra records
    # ------------------------------------------------------------------
    for rec in extra_records:
        if rec.influence_class == InfluenceClass.HARD_GATE:
            hard_gates.append(rec)
        else:
            soft_influences.append(rec)

    return RuntimeDecisionExplanation(
        execution_path=execution_path,
        model_selected=model_selected,
        provider_selected=provider_selected,
        model_selection_reason=model_selection_reason,
        task_hint=task_hint,
        task_semantic_influenced_routing=task_semantic_influenced_routing,
        task_semantic_influenced_planner=task_semantic_influenced_planner,
        hard_gates=hard_gates,
        soft_influences=soft_influences,
        node_allowed=node_allowed,
        node_denial_reasons=node_denial_reasons,
        activation_budget_active=activation_budget_active,
        activation_budget_mode=activation_budget_mode,
        memory_bias_posture=memory_bias_posture,
        memory_influenced_planner=memory_influenced_planner,
        cognitive_region=cognitive_region,
        execution_path_preference=execution_path_preference,
        execution_path_preference_binding="advisory_only_non_binding",
        execution_path_preference_authority="soft_hint_non_binding",
        planner_strategy=planner_strategy,
    )


# ---------------------------------------------------------------------------
# Diagnostics assembler
# ---------------------------------------------------------------------------


def build_runtime_decision_diagnostics(
    explanation: Optional[RuntimeDecisionExplanation],
    *,
    include_detail: bool = False,
) -> Dict[str, Any]:
    """Assemble a compact diagnostics dict from a :class:`RuntimeDecisionExplanation`.

    Always returns a valid dict.  Never raises.

    Parameters
    ----------
    explanation:
        The explanation to convert.  When ``None`` or not a
        :class:`RuntimeDecisionExplanation`, returns a minimal fallback dict.
    include_detail:
        When ``True``, each influence record's ``detail`` dict is included in
        the output.  Defaults to ``False`` to keep the diagnostics surface compact.

    Returns
    -------
    dict
        Compact, JSON-safe diagnostics dict with the following guaranteed keys:

        - ``execution_path``
        - ``model_selected``
        - ``provider_selected``
        - ``model_selection_reason``
        - ``task_hint``
        - ``task_semantic_influenced_routing``
        - ``task_semantic_influenced_planner``
        - ``has_hard_gate``
        - ``hard_gate_count``
        - ``node_allowed``
        - ``node_denial_reasons``
        - ``activation_budget_active``
        - ``activation_budget_mode``
        - ``memory_bias_posture``
        - ``memory_influenced_planner``
        - ``cognitive_region``
        - ``execution_path_preference``
        - ``execution_path_preference_binding``
        - ``execution_path_preference_authority``
        - ``planner_strategy``
        - ``active_soft_influence_count``
        - ``influence_layers``
        - ``assembled_at``
        - ``observability_authority``
    """
    try:
        if explanation is None or not isinstance(explanation, RuntimeDecisionExplanation):
            return _minimal_diagnostics_fallback()

        all_records: List[Dict[str, Any]] = []
        for rec in (explanation.hard_gates + explanation.soft_influences):
            entry: Dict[str, Any] = {
                "layer_name": rec.layer_name,
                "influence_class": rec.influence_class.value,
                "active": rec.active,
                "authority_module": rec.authority_module,
                "summary": rec.summary,
            }
            if include_detail:
                entry["detail"] = rec.detail
            all_records.append(entry)

        return {
            "execution_path": explanation.execution_path,
            "model_selected": explanation.model_selected,
            "provider_selected": explanation.provider_selected,
            "model_selection_reason": explanation.model_selection_reason,
            "task_hint": explanation.task_hint,
            "task_semantic_influenced_routing": explanation.task_semantic_influenced_routing,
            "task_semantic_influenced_planner": explanation.task_semantic_influenced_planner,
            "has_hard_gate": explanation.has_hard_gate,
            "hard_gate_count": len(explanation.hard_gates),
            "node_allowed": explanation.node_allowed,
            "node_denial_reasons": list(explanation.node_denial_reasons),
            "activation_budget_active": explanation.activation_budget_active,
            "activation_budget_mode": explanation.activation_budget_mode,
            "memory_bias_posture": explanation.memory_bias_posture,
            "memory_influenced_planner": explanation.memory_influenced_planner,
            "cognitive_region": explanation.cognitive_region,
            "execution_path_preference": explanation.execution_path_preference,
            "execution_path_preference_binding": "advisory_only_non_binding",
            "execution_path_preference_authority": "soft_hint_non_binding",
            "planner_strategy": explanation.planner_strategy,
            "active_soft_influence_count": explanation.active_influence_count,
            "influence_layers": all_records,
            "decision_scope": {
                "hard_authority": {
                    "governance_or_readiness_gate_active": explanation.has_hard_gate,
                    "node_allowed": explanation.node_allowed,
                },
                "soft_influence": {
                    "task_semantic": bool(
                        explanation.task_semantic_influenced_routing
                        or explanation.task_semantic_influenced_planner
                    ),
                    "activation_budget": explanation.activation_budget_active,
                    "memory_bias": explanation.memory_influenced_planner,
                    "cognitive_hint": bool(explanation.execution_path_preference),
                    "planner_strategy_observed": bool(explanation.planner_strategy),
                },
                "routing_metadata_fields": [
                    "execution_path",
                    "model_selected",
                    "provider_selected",
                    "model_selection_reason",
                ],
                "metadata_only_fields": [
                    "assembled_at",
                    "observability_authority",
                ],
            },
            "assembled_at": explanation.assembled_at,
            "observability_authority": RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY,
        }
    except Exception as exc:
        logger.debug("build_runtime_decision_diagnostics failed (returning minimal): %s", exc)
        return _minimal_diagnostics_fallback()


def _minimal_diagnostics_fallback() -> Dict[str, Any]:
    return {
        "execution_path": "unknown",
        "model_selected": None,
        "provider_selected": None,
        "model_selection_reason": None,
        "task_hint": None,
        "task_semantic_influenced_routing": False,
        "task_semantic_influenced_planner": False,
        "has_hard_gate": False,
        "hard_gate_count": 0,
        "node_allowed": None,
        "node_denial_reasons": [],
        "activation_budget_active": False,
        "activation_budget_mode": None,
        "memory_bias_posture": None,
        "memory_influenced_planner": False,
        "cognitive_region": None,
        "execution_path_preference": None,
        "execution_path_preference_binding": "advisory_only_non_binding",
        "execution_path_preference_authority": "soft_hint_non_binding",
        "planner_strategy": None,
        "active_soft_influence_count": 0,
        "influence_layers": [],
        "decision_scope": {
            "hard_authority": {
                "governance_or_readiness_gate_active": False,
                "node_allowed": None,
            },
            "soft_influence": {
                "task_semantic": False,
                "activation_budget": False,
                "memory_bias": False,
                "cognitive_hint": False,
                "planner_strategy_observed": False,
            },
            "routing_metadata_fields": [
                "execution_path",
                "model_selected",
                "provider_selected",
                "model_selection_reason",
            ],
            "metadata_only_fields": [
                "assembled_at",
                "observability_authority",
            ],
        },
        "assembled_at": time.time(),
        "observability_authority": RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY,
    }


# ---------------------------------------------------------------------------
# Convenience: enrich multimodal route dict with observability context
# ---------------------------------------------------------------------------


def enrich_multimodal_route_with_observability(
    route_dict: Dict[str, Any],
    *,
    task_hint: Optional[str] = None,
    task_semantic_influenced: bool = False,
) -> Dict[str, Any]:
    """Enrich a multimodal route dict with task-semantic observability fields.

    Called by ``OpenClawd._select_multimodal_route()`` to attach PR-20
    observability context to the route result dict.

    Parameters
    ----------
    route_dict:
        The route result dict to enrich (mutated in-place and returned).
    task_hint:
        Task-semantic hint that was active during routing (PR-17).
    task_semantic_influenced:
        ``True`` when the task hint changed the routing outcome away from
        the GENERAL fallback default.

    Returns
    -------
    dict
        The enriched route dict (same object, with additional keys).
    """
    try:
        route_dict["pr20_task_hint"] = task_hint
        route_dict["pr20_task_semantic_influenced_routing"] = task_semantic_influenced
        route_dict["pr20_observability_source"] = RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL
    except Exception as exc:
        logger.debug("enrich_multimodal_route_with_observability failed (swallowed): %s", exc)
    return route_dict


# ---------------------------------------------------------------------------
# Convenience: enrich governance decision dict with observability context
# ---------------------------------------------------------------------------


def enrich_governance_decision_with_observability(
    decision_dict: Dict[str, Any],
    *,
    activation_budget_hint: Optional[Dict[str, Any]] = None,
    memory_bias_hint: Optional[Dict[str, Any]] = None,
    task_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Enrich a governance decision dict with PR-20 observability context.

    Called by ``evaluate_invocation_governance()`` to embed a compact
    PR-20 observability summary in the governance diagnostic dict.

    Parameters
    ----------
    decision_dict:
        The governance diagnostic dict to enrich (mutated in-place and returned).
    activation_budget_hint:
        Budget diagnostics dict from PR-18 (optional).
    memory_bias_hint:
        Memory bias diagnostics dict from PR-19 (optional).
    task_hint:
        Task-semantic hint active at governance time (PR-17, optional).

    Returns
    -------
    dict
        The enriched dict (same object, with additional keys under
        ``pr20_observability_context``).
    """
    try:
        obs: Dict[str, Any] = {
            "task_hint": task_hint,
            "activation_budget_mode": (
                (activation_budget_hint or {}).get("breadth_mode")
            ),
            "memory_bias_posture": (
                (memory_bias_hint or {}).get("posture")
            ),
            "observability_pr20_active": True,
            "observability_authority": RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL,
        }
        decision_dict["pr20_observability_context"] = obs
    except Exception as exc:
        logger.debug("enrich_governance_decision_with_observability failed (swallowed): %s", exc)
    return decision_dict
