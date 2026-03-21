#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.task_semantics
====================

PR-15 (V4) — Task Semantics & Step Classes

A focused, additive package that formalises **semantic step meaning** on top
of the existing ``TaskGraph``, ``TaskEnvelope``, orchestration, and policy
layers.

This package answers, for any given task step:
  - What kind of step is this? (:class:`StepKind`)
  - Is the step side-effectful?
  - Can it run cross-device?
  - Is failure skippable, or must it halt the task?
  - Should it be visible / prominent in manifest / projection surfaces?
  - Should an observability highlight be emitted for this step?
  - What recovery posture is recommended when this step fails?

Source signals consumed (read-only, not modified)
--------------------------------------------------
* :class:`~core.schemas.task_envelope.TaskEnvelope` ``tool_name`` and metadata
* :class:`~core.task_graph.TaskGraph` node descriptions and metadata
* :class:`~core.distributed_execution.MergeSummary` recovery hints (PR-14)
* :class:`~core.execution_policy.ExecutionPolicy` band and gate flags (PR-11)
* :class:`~core.cross_device_policy.RoutingPolicy` assignment hints (PR-13)

Public API
----------
StepKind
    Stable enum of semantic step classifications: ``perceive``, ``analyze``,
    ``decide``, ``execute``, ``confirm``, ``notify``, ``rollback``,
    ``observe_remote``, ``unknown``.

STEP_KIND_ORDER
    Ordered list from least to most side-effectful.

SIDE_EFFECTFUL_KINDS
    Frozenset of kinds considered side-effectful by default.

READONLY_KINDS
    Frozenset of read-only kinds.

step_kind_description(kind) → str
    Human-readable description.

is_side_effectful_kind(kind) → bool
    True if the kind is side-effectful.

is_readonly_kind(kind) → bool
    True if the kind is read-only.

coerce_step_kind(value) → StepKind
    Coerce any value to a :class:`StepKind`.

StepSemanticPolicy
    Immutable, serialisable semantic policy dataclass.  Fields:
    ``step_kind``, ``side_effectful``, ``requires_confirmation``,
    ``cross_device_allowed``, ``failure_skippable``,
    ``should_surface_in_manifest``, ``should_emit_observability_highlight``,
    ``preferred_recovery_posture``, ``policy_reason``.

DEFAULT_SAFE_STEP_POLICY
    Pre-built safe-default policy for read-only steps.

DEFAULT_EXECUTE_STEP_POLICY
    Pre-built default policy for execution steps.

build_policy_for_kind(kind, …) → StepSemanticPolicy
    Build a policy with defaults derived from the given kind.

ClassifiedStep
    Immutable per-step record: ``step_id``, ``step_label``, ``step_kind``,
    ``policy``, ``source_hint``.

TaskSemanticSummary
    Immutable, serialisable summary of classified steps for a task.

EMPTY_SEMANTIC_SUMMARY
    Pre-built empty/uninitialised summary.

attach_semantic_summary_to_projection(projection_dict, summary) → dict
    Attach summary to a ``RuntimeProjection`` dict additively.

get_semantic_hints(summary) → dict
    Compact boolean/scalar hints for downstream consumers.

resolve_step_kind(…) → (StepKind, source_hint)
    Infer step kind from available metadata.

resolve_step_policy(…) → StepSemanticPolicy
    Infer step policy from available metadata.

classify_task_node(node, …) → ClassifiedStep
    Classify a single ``TaskNode``-like object.

classify_task_envelope(envelope, …) → ClassifiedStep
    Classify a :class:`~core.schemas.task_envelope.TaskEnvelope`.

build_semantic_summary_from_graph(graph, …) → TaskSemanticSummary
    Build summary from a :class:`~core.task_graph.TaskGraph`.

build_semantic_summary_from_envelopes(envelopes, …) → TaskSemanticSummary
    Build summary from a list of task envelopes.

build_semantic_summary_from_dicts(step_dicts, …) → TaskSemanticSummary
    Build summary from a list of plain step dicts.

What this package does NOT do
------------------------------
- It does **not** replace or modify ``TaskGraph``, ``TaskEnvelope``,
  ``ConstellationRuntime``, ``DesktopPresenceRuntime``, or any existing
  orchestrator.
- It does **not** add a competing orchestrator.
- It does **not** enforce step-level policy (that is left to future PRs).
- All paths are additive and read-only from the perspective of existing
  execution layers.

See Also
--------
docs/TASK_SEMANTICS_AND_STEP_CLASSES.md — design document for this package.
core/execution_policy/ — PR-11 execution policy schema (upstream signal).
core/cross_device_policy/ — PR-13 cross-device routing policy (upstream signal).
core/distributed_execution/ — PR-14 merge & recovery (upstream signal).
core/task_graph.py — existing DAG engine (not modified).
"""

from __future__ import annotations

from .step_kind import (
    StepKind,
    STEP_KIND_ORDER,
    SIDE_EFFECTFUL_KINDS,
    READONLY_KINDS,
    step_kind_description,
    is_side_effectful_kind,
    is_readonly_kind,
    coerce_step_kind,
)
from .step_policy import (
    StepSemanticPolicy,
    DEFAULT_SAFE_STEP_POLICY,
    DEFAULT_EXECUTE_STEP_POLICY,
    build_policy_for_kind,
)
from .task_semantic_summary import (
    ClassifiedStep,
    TaskSemanticSummary,
    EMPTY_SEMANTIC_SUMMARY,
    attach_semantic_summary_to_projection,
    get_semantic_hints,
)
from .step_resolver import (
    resolve_step_kind,
    resolve_step_policy,
    classify_task_node,
    classify_task_envelope,
    build_semantic_summary_from_graph,
    build_semantic_summary_from_envelopes,
    build_semantic_summary_from_dicts,
)

__all__ = [
    # Step kind enum and helpers
    "StepKind",
    "STEP_KIND_ORDER",
    "SIDE_EFFECTFUL_KINDS",
    "READONLY_KINDS",
    "step_kind_description",
    "is_side_effectful_kind",
    "is_readonly_kind",
    "coerce_step_kind",
    # Step policy dataclass and factories
    "StepSemanticPolicy",
    "DEFAULT_SAFE_STEP_POLICY",
    "DEFAULT_EXECUTE_STEP_POLICY",
    "build_policy_for_kind",
    # Summary types and adapters
    "ClassifiedStep",
    "TaskSemanticSummary",
    "EMPTY_SEMANTIC_SUMMARY",
    "attach_semantic_summary_to_projection",
    "get_semantic_hints",
    # Resolver helpers
    "resolve_step_kind",
    "resolve_step_policy",
    "classify_task_node",
    "classify_task_envelope",
    "build_semantic_summary_from_graph",
    "build_semantic_summary_from_envelopes",
    "build_semantic_summary_from_dicts",
]
