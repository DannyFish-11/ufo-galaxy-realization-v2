#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.task_semantics.step_resolver
===================================

PR-15 (V4) — Task Semantics & Step Classes

Provides **resolver helpers** that infer or attach semantic step kinds from
existing runtime structures.

Resolver inputs (all optional, degrade gracefully)
---------------------------------------------------
- :class:`~core.schemas.task_envelope.TaskEnvelope` metadata / ``tool_name``
- :class:`~core.task_graph.TaskNode` / ``TaskGraph`` node descriptions and
  metadata
- :class:`~core.distributed_execution.MergeSummary` recovery hints (PR-14)
- :class:`~core.execution_policy.ExecutionPolicy` cross-device / confirmation
  hints (PR-11)
- :class:`~core.cross_device_policy.RoutingPolicy` assignment hints (PR-13)
- Plain ``dict`` metadata from arbitrary task payloads

Resolution strategy (applied in order, first match wins)
----------------------------------------------------------
1. Explicit ``"step_kind"`` key in node/envelope metadata dict.
2. ``tool_name`` keyword mapping (e.g. ``"screenshot"`` → ``perceive``).
3. Description keyword scan (e.g. description contains ``"rollback"``).
4. Cross-device context from routing policy → ``observe_remote``.
5. Execution policy context (``observe_only`` band → ``perceive``/``analyze``).
6. Fallback to :attr:`~.step_kind.StepKind.UNKNOWN`.

Design
------
All public functions are **pure** (no side effects, no global state mutation).
They accept optional inputs and degrade gracefully when inputs are absent or
of unexpected types.

Public API
----------
resolve_step_kind(…) → (StepKind, str)
    Infer a :class:`~.step_kind.StepKind` from available metadata.
    Returns the kind and a ``source_hint`` string.

resolve_step_policy(…) → StepSemanticPolicy
    Infer a :class:`~.step_policy.StepSemanticPolicy` from available metadata.

classify_task_node(…) → ClassifiedStep
    Classify a single ``TaskNode``-like dict into a :class:`~.task_semantic_summary.ClassifiedStep`.

classify_task_envelope(…) → ClassifiedStep
    Classify a :class:`~core.schemas.task_envelope.TaskEnvelope` into a
    :class:`~.task_semantic_summary.ClassifiedStep`.

build_semantic_summary_from_graph(graph, …) → TaskSemanticSummary
    Build a :class:`~.task_semantic_summary.TaskSemanticSummary` from a
    :class:`~core.task_graph.TaskGraph`.

build_semantic_summary_from_envelopes(envelopes, …) → TaskSemanticSummary
    Build a :class:`~.task_semantic_summary.TaskSemanticSummary` from a list
    of :class:`~core.schemas.task_envelope.TaskEnvelope` objects.

build_semantic_summary_from_dicts(step_dicts, …) → TaskSemanticSummary
    Build a :class:`~.task_semantic_summary.TaskSemanticSummary` from a list
    of plain dicts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .step_kind import StepKind, coerce_step_kind
from .step_policy import StepSemanticPolicy, build_policy_for_kind
from .task_semantic_summary import (
    ClassifiedStep,
    TaskSemanticSummary,
    EMPTY_SEMANTIC_SUMMARY,
)

logger = logging.getLogger("Galaxy.TaskSemantics.Resolver")

__all__ = [
    "resolve_step_kind",
    "resolve_step_policy",
    "classify_task_node",
    "classify_task_envelope",
    "build_semantic_summary_from_graph",
    "build_semantic_summary_from_envelopes",
    "build_semantic_summary_from_dicts",
]


# ---------------------------------------------------------------------------
# Internal: tool-name keyword mapping
# ---------------------------------------------------------------------------

_TOOL_NAME_MAP: Dict[str, StepKind] = {
    # Perception / observation
    "screenshot": StepKind.PERCEIVE,
    "capture_screen": StepKind.PERCEIVE,
    "read_screen": StepKind.PERCEIVE,
    "get_screen": StepKind.PERCEIVE,
    "read_file": StepKind.PERCEIVE,
    "read_clipboard": StepKind.PERCEIVE,
    "sensor_read": StepKind.PERCEIVE,
    "poll": StepKind.PERCEIVE,
    "fetch": StepKind.PERCEIVE,
    "list_files": StepKind.PERCEIVE,
    "get_status": StepKind.PERCEIVE,
    "observe": StepKind.PERCEIVE,
    # Remote observation
    "observe_remote": StepKind.OBSERVE_REMOTE,
    "remote_screenshot": StepKind.OBSERVE_REMOTE,
    "remote_poll": StepKind.OBSERVE_REMOTE,
    # Analysis
    "analyze": StepKind.ANALYZE,
    "analyse": StepKind.ANALYZE,
    "ocr": StepKind.ANALYZE,
    "parse": StepKind.ANALYZE,
    "detect": StepKind.ANALYZE,
    "classify": StepKind.ANALYZE,
    "extract": StepKind.ANALYZE,
    "summarize": StepKind.ANALYZE,
    "summarise": StepKind.ANALYZE,
    "process": StepKind.ANALYZE,
    # Decision
    "decide": StepKind.DECIDE,
    "plan": StepKind.DECIDE,
    "select": StepKind.DECIDE,
    "choose": StepKind.DECIDE,
    "route": StepKind.DECIDE,
    # Execution / action
    "click": StepKind.EXECUTE,
    "type": StepKind.EXECUTE,
    "key": StepKind.EXECUTE,
    "keypress": StepKind.EXECUTE,
    "execute": StepKind.EXECUTE,
    "run": StepKind.EXECUTE,
    "write_file": StepKind.EXECUTE,
    "delete_file": StepKind.EXECUTE,
    "move_file": StepKind.EXECUTE,
    "api_call": StepKind.EXECUTE,
    "post": StepKind.EXECUTE,
    "send": StepKind.EXECUTE,
    "submit": StepKind.EXECUTE,
    "invoke": StepKind.EXECUTE,
    "shell": StepKind.EXECUTE,
    "cmd": StepKind.EXECUTE,
    "control": StepKind.EXECUTE,
    # Confirmation
    "confirm": StepKind.CONFIRM,
    "approve": StepKind.CONFIRM,
    "wait_for_confirmation": StepKind.CONFIRM,
    "gate": StepKind.CONFIRM,
    # Notification
    "notify": StepKind.NOTIFY,
    "alert": StepKind.NOTIFY,
    "push": StepKind.NOTIFY,
    "webhook": StepKind.NOTIFY,
    "broadcast": StepKind.NOTIFY,
    # Rollback / undo
    "rollback": StepKind.ROLLBACK,
    "undo": StepKind.ROLLBACK,
    "revert": StepKind.ROLLBACK,
    "compensate": StepKind.ROLLBACK,
    "restore": StepKind.ROLLBACK,
}

# Description keywords (scanned in order; first match wins)
_DESCRIPTION_KEYWORDS: List[Tuple[str, StepKind]] = [
    ("rollback", StepKind.ROLLBACK),
    ("undo", StepKind.ROLLBACK),
    ("revert", StepKind.ROLLBACK),
    ("compensat", StepKind.ROLLBACK),
    ("confirm", StepKind.CONFIRM),
    ("approve", StepKind.CONFIRM),
    ("notify", StepKind.NOTIFY),
    ("alert", StepKind.NOTIFY),
    ("observe remote", StepKind.OBSERVE_REMOTE),
    ("remote observation", StepKind.OBSERVE_REMOTE),
    ("screenshot", StepKind.PERCEIVE),
    ("capture screen", StepKind.PERCEIVE),
    ("take screenshot", StepKind.PERCEIVE),
    ("read screen", StepKind.PERCEIVE),
    ("perceive", StepKind.PERCEIVE),
    ("sense", StepKind.PERCEIVE),
    ("detect", StepKind.ANALYZE),
    ("analyz", StepKind.ANALYZE),
    ("analys", StepKind.ANALYZE),
    ("classify", StepKind.ANALYZE),
    ("extract", StepKind.ANALYZE),
    ("parse", StepKind.ANALYZE),
    ("ocr", StepKind.ANALYZE),
    ("decide", StepKind.DECIDE),
    ("plan", StepKind.DECIDE),
    ("select action", StepKind.DECIDE),
    ("choose", StepKind.DECIDE),
    ("click", StepKind.EXECUTE),
    ("type", StepKind.EXECUTE),
    ("write", StepKind.EXECUTE),
    ("execute", StepKind.EXECUTE),
    ("run command", StepKind.EXECUTE),
    ("invoke", StepKind.EXECUTE),
    ("perform", StepKind.EXECUTE),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_to_str(value: Any) -> str:
    """Safely coerce any value to a lowercase stripped string.

    Returns an empty string for ``None`` and for strings that are empty or
    whitespace-only after stripping.  This normalisation is intentional: callers
    treat an empty string as "no value provided" and fall through to the next
    resolution step.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().lower()
    if hasattr(value, "value"):
        return str(value.value).strip().lower()
    return str(value).strip().lower()


def _resolve_from_metadata(meta: Any) -> Optional[StepKind]:
    """Try to extract an explicit ``step_kind`` key from metadata dict."""
    if not isinstance(meta, dict):
        return None
    raw = meta.get("step_kind")
    if raw is None:
        return None
    kind = coerce_step_kind(raw)
    return kind if kind != StepKind.UNKNOWN else None


def _resolve_from_tool_name(tool_name: Any) -> Optional[StepKind]:
    """Map a ``tool_name`` to a :class:`~.step_kind.StepKind`."""
    name = _coerce_to_str(tool_name)
    if not name:
        return None
    # Exact match first
    if name in _TOOL_NAME_MAP:
        return _TOOL_NAME_MAP[name]
    # Prefix / substring match
    for key, kind in _TOOL_NAME_MAP.items():
        if name.startswith(key) or key in name:
            return kind
    return None


def _resolve_from_description(description: Any) -> Optional[StepKind]:
    """Scan a description string for semantic keywords."""
    desc = _coerce_to_str(description)
    if not desc:
        return None
    for keyword, kind in _DESCRIPTION_KEYWORDS:
        if keyword in desc:
            return kind
    return None


def _resolve_from_cross_device_context(
    routing_policy: Any,
) -> Optional[StepKind]:
    """If a routing policy indicates cross-device remote observation, return OBSERVE_REMOTE."""
    if routing_policy is None:
        return None
    # Accept RoutingPolicy objects or dicts
    posture: str = ""
    if hasattr(routing_policy, "posture"):
        posture = _coerce_to_str(routing_policy.posture)
    elif isinstance(routing_policy, dict):
        posture = _coerce_to_str(routing_policy.get("posture", ""))
    if posture == "mirrored_observation":
        return StepKind.OBSERVE_REMOTE
    return None


def _resolve_from_execution_policy(
    execution_policy: Any,
) -> Optional[StepKind]:
    """Map observe_only band to PERCEIVE as a conservative hint."""
    if execution_policy is None:
        return None
    band: str = ""
    if hasattr(execution_policy, "policy_band"):
        band = _coerce_to_str(execution_policy.policy_band)
    elif isinstance(execution_policy, dict):
        band = _coerce_to_str(execution_policy.get("policy_band", ""))
    if band == "observe_only":
        return StepKind.PERCEIVE
    return None


# ---------------------------------------------------------------------------
# Public: resolve_step_kind
# ---------------------------------------------------------------------------


def resolve_step_kind(
    *,
    tool_name: Any = None,
    description: Any = None,
    metadata: Any = None,
    routing_policy: Any = None,
    execution_policy: Any = None,
) -> Tuple[StepKind, str]:
    """Infer a :class:`~.step_kind.StepKind` from available metadata.

    Resolution order (first match wins):
    1. Explicit ``"step_kind"`` key in *metadata* dict.
    2. ``tool_name`` keyword mapping.
    3. ``description`` keyword scan.
    4. Cross-device routing context (``mirrored_observation`` → ``observe_remote``).
    5. Execution policy band (``observe_only`` → ``perceive``).
    6. Fallback → :attr:`~.step_kind.StepKind.UNKNOWN`.

    Args:
        tool_name: Tool/skill/command name (string or object with ``.value``).
        description: Human-readable step description.
        metadata: Dict of extra metadata; may contain an explicit
                  ``"step_kind"`` key.
        routing_policy: Optional :class:`~core.cross_device_policy.RoutingPolicy`
                        or compatible dict.
        execution_policy: Optional :class:`~core.execution_policy.ExecutionPolicy`
                          or compatible dict.

    Returns:
        A ``(StepKind, source_hint)`` tuple where ``source_hint`` is one of
        ``"explicit"``, ``"tool_name"``, ``"description"``,
        ``"routing_policy"``, ``"execution_policy"``, or ``"fallback"``.
    """
    # 1. Explicit metadata key
    kind = _resolve_from_metadata(metadata)
    if kind is not None:
        return kind, "explicit"

    # 2. Tool name
    kind = _resolve_from_tool_name(tool_name)
    if kind is not None:
        return kind, "tool_name"

    # 3. Description
    kind = _resolve_from_description(description)
    if kind is not None:
        return kind, "description"

    # 4. Cross-device routing context
    kind = _resolve_from_cross_device_context(routing_policy)
    if kind is not None:
        return kind, "routing_policy"

    # 5. Execution policy band
    kind = _resolve_from_execution_policy(execution_policy)
    if kind is not None:
        return kind, "execution_policy"

    return StepKind.UNKNOWN, "fallback"


# ---------------------------------------------------------------------------
# Public: resolve_step_policy
# ---------------------------------------------------------------------------


def resolve_step_policy(
    *,
    tool_name: Any = None,
    description: Any = None,
    metadata: Any = None,
    routing_policy: Any = None,
    execution_policy: Any = None,
) -> StepSemanticPolicy:
    """Infer a :class:`~.step_policy.StepSemanticPolicy` from available metadata.

    Calls :func:`resolve_step_kind` to determine the kind, then delegates
    to :func:`~.step_policy.build_policy_for_kind` for trait defaults.

    Cross-device and confirmation overrides are applied when available from
    upstream execution/routing policy signals.

    Args:
        tool_name: Tool/skill/command name.
        description: Human-readable step description.
        metadata: Dict of extra metadata.
        routing_policy: Optional routing policy (PR-13).
        execution_policy: Optional execution policy (PR-11).

    Returns:
        A :class:`~.step_policy.StepSemanticPolicy`.
    """
    kind, source_hint = resolve_step_kind(
        tool_name=tool_name,
        description=description,
        metadata=metadata,
        routing_policy=routing_policy,
        execution_policy=execution_policy,
    )

    # Derive cross_device override from upstream signals
    cross_device_allowed: Optional[bool] = None
    if routing_policy is not None:
        if hasattr(routing_policy, "is_cross_device"):
            cross_device_allowed = bool(routing_policy.is_cross_device)
        elif isinstance(routing_policy, dict):
            cross_device_allowed = bool(routing_policy.get("is_cross_device", False))

    if execution_policy is not None and cross_device_allowed is None:
        if hasattr(execution_policy, "cross_device_allowed"):
            cross_device_allowed = bool(execution_policy.cross_device_allowed)
        elif isinstance(execution_policy, dict):
            cross_device_allowed = bool(
                execution_policy.get("cross_device_allowed", False)
            )

    # Derive requires_confirmation override
    requires_confirmation: Optional[bool] = None
    if execution_policy is not None:
        if hasattr(execution_policy, "requires_confirmation"):
            requires_confirmation = bool(execution_policy.requires_confirmation)
        elif isinstance(execution_policy, dict):
            requires_confirmation = bool(
                execution_policy.get("requires_confirmation", False)
            )

    return build_policy_for_kind(
        kind,
        policy_reason=f"resolved from source_hint={source_hint!r}",
        cross_device_allowed=cross_device_allowed,
        requires_confirmation=requires_confirmation,
    )


# ---------------------------------------------------------------------------
# Public: classify_task_node
# ---------------------------------------------------------------------------


def classify_task_node(
    node: Any,
    *,
    routing_policy: Any = None,
    execution_policy: Any = None,
) -> ClassifiedStep:
    """Classify a single ``TaskNode``-like object or dict into a :class:`~.task_semantic_summary.ClassifiedStep`.

    Accepts:
    - :class:`~core.task_graph.TaskNode` dataclass instances
    - Plain dicts with ``node_id``/``description``/``metadata`` keys

    Args:
        node: The task node to classify.
        routing_policy: Optional routing policy for cross-device context.
        execution_policy: Optional execution policy for band context.

    Returns:
        A :class:`~.task_semantic_summary.ClassifiedStep`.
    """
    if node is None:
        return ClassifiedStep(
            step_id="",
            step_label="",
            step_kind=StepKind.UNKNOWN,
            policy=build_policy_for_kind(StepKind.UNKNOWN),
            source_hint="fallback",
        )

    # Extract fields from node (dataclass or dict)
    if isinstance(node, dict):
        node_id = str(node.get("node_id") or node.get("id") or "")
        description = node.get("description") or node.get("label") or ""
        metadata = node.get("metadata") or {}
        tool_name = node.get("tool_name") or metadata.get("tool_name") or ""
    else:
        node_id = str(getattr(node, "node_id", "") or "")
        description = getattr(node, "description", "") or ""
        metadata = getattr(node, "metadata", {}) or {}
        tool_name = getattr(node, "tool_name", "") or metadata.get("tool_name", "")

    kind, source_hint = resolve_step_kind(
        tool_name=tool_name,
        description=description,
        metadata=metadata,
        routing_policy=routing_policy,
        execution_policy=execution_policy,
    )
    policy = build_policy_for_kind(
        kind,
        policy_reason=f"classified from task_node source_hint={source_hint!r}",
    )
    return ClassifiedStep(
        step_id=node_id,
        step_label=str(description)[:200],
        step_kind=kind,
        policy=policy,
        source_hint=source_hint,
    )


# ---------------------------------------------------------------------------
# Public: classify_task_envelope
# ---------------------------------------------------------------------------


def classify_task_envelope(
    envelope: Any,
    *,
    routing_policy: Any = None,
    execution_policy: Any = None,
) -> ClassifiedStep:
    """Classify a :class:`~core.schemas.task_envelope.TaskEnvelope` into a :class:`~.task_semantic_summary.ClassifiedStep`.

    Accepts TaskEnvelope objects (Pydantic) or plain dicts.

    Args:
        envelope: The task envelope to classify.
        routing_policy: Optional routing policy for cross-device context.
        execution_policy: Optional execution policy for band context.

    Returns:
        A :class:`~.task_semantic_summary.ClassifiedStep`.
    """
    if envelope is None:
        return ClassifiedStep(
            step_id="",
            step_label="",
            step_kind=StepKind.UNKNOWN,
            policy=build_policy_for_kind(StepKind.UNKNOWN),
            source_hint="fallback",
        )

    if isinstance(envelope, dict):
        task_id = str(envelope.get("task_id") or "")
        tool_name = envelope.get("tool_name") or ""
        metadata = envelope.get("metadata") or {}
        description = metadata.get("description") or envelope.get("description") or tool_name
    else:
        task_id = str(getattr(envelope, "task_id", "") or "")
        tool_name = getattr(envelope, "tool_name", "") or ""
        metadata = getattr(envelope, "metadata", {}) or {}
        description = metadata.get("description") or tool_name

    kind, source_hint = resolve_step_kind(
        tool_name=tool_name,
        description=description,
        metadata=metadata,
        routing_policy=routing_policy,
        execution_policy=execution_policy,
    )
    policy = build_policy_for_kind(
        kind,
        policy_reason=f"classified from task_envelope source_hint={source_hint!r}",
    )
    return ClassifiedStep(
        step_id=task_id,
        step_label=str(description)[:200],
        step_kind=kind,
        policy=policy,
        source_hint=source_hint,
    )


# ---------------------------------------------------------------------------
# Internal: aggregate summary from classified steps
# ---------------------------------------------------------------------------


def _build_summary_from_steps(
    steps: List[ClassifiedStep],
    *,
    task_id: str = "",
    trace_id: str = "",
    runtime_session_id: str = "",
) -> TaskSemanticSummary:
    """Build a :class:`~.task_semantic_summary.TaskSemanticSummary` from a list of :class:`~.task_semantic_summary.ClassifiedStep` objects."""
    has_side_effectful = False
    has_cross_device = False
    has_confirmation_required = False
    has_rollback = False
    primary_visible: List[str] = []
    obs_highlight: List[str] = []
    unresolved = 0

    for step in steps:
        if step.step_kind == StepKind.UNKNOWN:
            unresolved += 1
        if step.step_kind == StepKind.ROLLBACK:
            has_rollback = True

        policy = step.policy
        if policy is not None:
            if policy.side_effectful:
                has_side_effectful = True
            if policy.cross_device_allowed:
                has_cross_device = True
            if policy.requires_confirmation:
                has_confirmation_required = True
            if policy.should_surface_in_manifest and step.step_id:
                primary_visible.append(step.step_id)
            if policy.should_emit_observability_highlight and step.step_id:
                obs_highlight.append(step.step_id)

    return TaskSemanticSummary(
        task_id=task_id,
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        classified_steps=steps,
        has_side_effectful_steps=has_side_effectful,
        has_cross_device_steps=has_cross_device,
        has_confirmation_required_steps=has_confirmation_required,
        has_rollback_steps=has_rollback,
        primary_visible_steps=primary_visible,
        observability_highlight_steps=obs_highlight,
        unresolved_count=unresolved,
    )


# ---------------------------------------------------------------------------
# Public: build_semantic_summary_from_graph
# ---------------------------------------------------------------------------


def build_semantic_summary_from_graph(
    graph: Any,
    *,
    routing_policy: Any = None,
    execution_policy: Any = None,
) -> TaskSemanticSummary:
    """Build a :class:`~.task_semantic_summary.TaskSemanticSummary` from a :class:`~core.task_graph.TaskGraph`.

    Iterates over the graph's nodes and classifies each one.  Degrades
    gracefully when the graph is ``None`` or has no accessible nodes.

    Args:
        graph: A :class:`~core.task_graph.TaskGraph` instance (or ``None``).
        routing_policy: Optional routing policy for cross-device context.
        execution_policy: Optional execution policy for band context.

    Returns:
        A :class:`~.task_semantic_summary.TaskSemanticSummary`.
    """
    if graph is None:
        return EMPTY_SEMANTIC_SUMMARY

    # Extract nodes from TaskGraph._nodes dict or list
    task_id = str(getattr(graph, "graph_id", "") or "")
    trace_id = str(getattr(graph, "trace_id", "") or "")
    runtime_session_id = str(getattr(graph, "runtime_session_id", "") or "")

    nodes_raw = getattr(graph, "_nodes", None)
    if nodes_raw is None:
        nodes_raw = getattr(graph, "nodes", {})

    steps: List[ClassifiedStep] = []
    if isinstance(nodes_raw, dict):
        for node in nodes_raw.values():
            steps.append(
                classify_task_node(
                    node,
                    routing_policy=routing_policy,
                    execution_policy=execution_policy,
                )
            )
    elif isinstance(nodes_raw, (list, tuple)):
        for node in nodes_raw:
            steps.append(
                classify_task_node(
                    node,
                    routing_policy=routing_policy,
                    execution_policy=execution_policy,
                )
            )

    return _build_summary_from_steps(
        steps,
        task_id=task_id,
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
    )


# ---------------------------------------------------------------------------
# Public: build_semantic_summary_from_envelopes
# ---------------------------------------------------------------------------


def build_semantic_summary_from_envelopes(
    envelopes: List[Any],
    *,
    task_id: str = "",
    trace_id: str = "",
    routing_policy: Any = None,
    execution_policy: Any = None,
) -> TaskSemanticSummary:
    """Build a :class:`~.task_semantic_summary.TaskSemanticSummary` from a list of task envelopes.

    Args:
        envelopes: List of :class:`~core.schemas.task_envelope.TaskEnvelope`
                   objects or dicts.
        task_id: Optional task identifier.
        trace_id: Optional trace identifier.
        routing_policy: Optional routing policy.
        execution_policy: Optional execution policy.

    Returns:
        A :class:`~.task_semantic_summary.TaskSemanticSummary`.
    """
    if not envelopes:
        return EMPTY_SEMANTIC_SUMMARY

    steps: List[ClassifiedStep] = []
    inferred_task_id = task_id
    inferred_trace_id = trace_id

    for env in envelopes:
        if env is None:
            continue
        step = classify_task_envelope(
            env,
            routing_policy=routing_policy,
            execution_policy=execution_policy,
        )
        steps.append(step)
        # Propagate IDs from first envelope if not supplied
        if not inferred_task_id:
            if isinstance(env, dict):
                inferred_task_id = str(env.get("task_id") or "")
            else:
                inferred_task_id = str(getattr(env, "task_id", "") or "")
        if not inferred_trace_id:
            if isinstance(env, dict):
                inferred_trace_id = str(env.get("trace_id") or "")
            else:
                inferred_trace_id = str(getattr(env, "trace_id", "") or "")

    return _build_summary_from_steps(
        steps,
        task_id=inferred_task_id,
        trace_id=inferred_trace_id,
    )


# ---------------------------------------------------------------------------
# Public: build_semantic_summary_from_dicts
# ---------------------------------------------------------------------------


def build_semantic_summary_from_dicts(
    step_dicts: List[Any],
    *,
    task_id: str = "",
    trace_id: str = "",
    routing_policy: Any = None,
    execution_policy: Any = None,
) -> TaskSemanticSummary:
    """Build a :class:`~.task_semantic_summary.TaskSemanticSummary` from a list of plain dicts.

    Each dict may contain any combination of:
    ``node_id`` / ``id``, ``description`` / ``label``, ``tool_name``,
    ``metadata``, ``step_kind``.

    Args:
        step_dicts: List of plain dict step descriptors.
        task_id: Optional task identifier.
        trace_id: Optional trace identifier.
        routing_policy: Optional routing policy.
        execution_policy: Optional execution policy.

    Returns:
        A :class:`~.task_semantic_summary.TaskSemanticSummary`.
    """
    if not step_dicts:
        return EMPTY_SEMANTIC_SUMMARY

    steps: List[ClassifiedStep] = []
    for item in step_dicts:
        if item is None:
            continue
        if not isinstance(item, dict):
            # Attempt to treat it as a node-like object
            steps.append(
                classify_task_node(
                    item,
                    routing_policy=routing_policy,
                    execution_policy=execution_policy,
                )
            )
            continue
        steps.append(
            classify_task_node(
                item,
                routing_policy=routing_policy,
                execution_policy=execution_policy,
            )
        )

    return _build_summary_from_steps(
        steps,
        task_id=task_id,
        trace_id=trace_id,
    )
