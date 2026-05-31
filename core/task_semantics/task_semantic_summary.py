#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.task_semantics.task_semantic_summary
==========================================

PR-15 (V4) — Task Semantics & Step Classes

Defines :class:`TaskSemanticSummary` — the stable, serialisable public
summary of the semantic step classification for a task or a set of steps.

This is the **canonical read surface** for downstream consumers:
- Status Board V2 / manifest / liminal layers
- Read-only API endpoints
- Observability surfaces
- Future orchestration and recovery logic

Design rules
------------
- All fields are ``None``-safe and carry stable defaults.
- ``to_dict()`` produces a stable, JSON-serialisable dict.
- ``from_dict()`` reconstructs from a plain dict (e.g. deserialised JSON).
- The summary carries the classified steps and aggregate flags so that
  consumers can answer "does this task contain side-effectful steps?" etc.
  without iterating over individual :class:`~.step_policy.StepSemanticPolicy`
  objects.

Projection adapter
------------------
:func:`attach_semantic_summary_to_projection` adds the summary to an existing
``RuntimeProjection`` dict additively (read-only from the projection's
perspective).

:func:`get_semantic_hints` extracts a compact boolean/scalar hint dict for
quick downstream checks.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Dict, List, Optional

from .step_kind import StepKind
from .step_policy import StepSemanticPolicy

__all__ = [
    "ClassifiedStep",
    "TaskSemanticSummary",
    "EMPTY_SEMANTIC_SUMMARY",
    "attach_semantic_summary_to_projection",
    "get_semantic_hints",
]


# ---------------------------------------------------------------------------
# ClassifiedStep — per-step record
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ClassifiedStep:
    """A single classified task step with its semantic kind and policy.

    Attributes
    ----------
    step_id
        Unique identifier for the step (e.g. node_id, task sub-id).
    step_label
        Human-readable label or description.
    step_kind
        The resolved :class:`~.step_kind.StepKind`.
    policy
        The :class:`~.step_policy.StepSemanticPolicy` for this step.
    source_hint
        How the kind was resolved: ``"explicit"``, ``"tool_name"``,
        ``"description"``, ``"metadata"``, or ``"fallback"``.
    """

    step_id: str = ""
    step_label: str = ""
    step_kind: StepKind = StepKind.UNKNOWN
    policy: Optional[StepSemanticPolicy] = None
    source_hint: str = "fallback"

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain, JSON-serialisable dict."""
        return {
            "step_id": self.step_id,
            "step_label": self.step_label,
            "step_kind": self.step_kind.value
            if isinstance(self.step_kind, StepKind)
            else str(self.step_kind),
            "policy": self.policy.to_dict() if self.policy is not None else None,
            "source_hint": self.source_hint,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClassifiedStep":
        """Reconstruct from a plain dict."""
        from .step_kind import coerce_step_kind
        from .step_policy import StepSemanticPolicy

        kind = coerce_step_kind(data.get("step_kind", StepKind.UNKNOWN))
        policy_data = data.get("policy")
        policy: Optional[StepSemanticPolicy] = None
        if isinstance(policy_data, dict):
            try:
                policy = StepSemanticPolicy.from_dict(policy_data)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        return cls(
            step_id=str(data.get("step_id") or ""),
            step_label=str(data.get("step_label") or ""),
            step_kind=kind,
            policy=policy,
            source_hint=str(data.get("source_hint") or "fallback"),
        )

    def __repr__(self) -> str:
        return (
            f"<ClassifiedStep "
            f"id={self.step_id!r} "
            f"kind={self.step_kind.value} "
            f"source={self.source_hint!r}>"
        )


# ---------------------------------------------------------------------------
# TaskSemanticSummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class TaskSemanticSummary:
    """Stable, public-facing summary of semantic step classification for a task.

    Produced by the helpers in :mod:`~.step_resolver`.

    Attributes
    ----------
    task_id
        Task identifier propagated from input signals.
    trace_id
        Trace identifier propagated from input signals.
    runtime_session_id
        Runtime session identifier.
    classified_steps
        Ordered list of :class:`ClassifiedStep` records.
    has_side_effectful_steps
        True if any classified step is side-effectful.
    has_cross_device_steps
        True if any step has ``cross_device_allowed=True`` in its policy.
    has_confirmation_required_steps
        True if any step ``requires_confirmation`` in its policy.
    has_rollback_steps
        True if any step has kind :attr:`~.step_kind.StepKind.ROLLBACK`.
    primary_visible_steps
        Subset of step IDs that ``should_surface_in_manifest``.
    observability_highlight_steps
        Subset of step IDs that ``should_emit_observability_highlight``.
    unresolved_count
        Number of steps whose kind resolved to :attr:`~.step_kind.StepKind.UNKNOWN`.
    summarised_at
        Unix timestamp when the summary was created.
    """

    task_id: str = ""
    trace_id: str = ""
    runtime_session_id: str = ""
    classified_steps: List[ClassifiedStep] = dataclasses.field(
        default_factory=list
    )
    has_side_effectful_steps: bool = False
    has_cross_device_steps: bool = False
    has_confirmation_required_steps: bool = False
    has_rollback_steps: bool = False
    primary_visible_steps: List[str] = dataclasses.field(default_factory=list)
    observability_highlight_steps: List[str] = dataclasses.field(
        default_factory=list
    )
    unresolved_count: int = 0
    summarised_at: float = dataclasses.field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def total_steps(self) -> int:
        """Total number of classified steps."""
        return len(self.classified_steps)

    @property
    def is_fully_resolved(self) -> bool:
        """True if all steps have a known (non-unknown) kind."""
        return self.unresolved_count == 0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain, JSON-serialisable dict."""
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "classified_steps": [s.to_dict() for s in self.classified_steps],
            "total_steps": self.total_steps,
            "has_side_effectful_steps": self.has_side_effectful_steps,
            "has_cross_device_steps": self.has_cross_device_steps,
            "has_confirmation_required_steps": self.has_confirmation_required_steps,
            "has_rollback_steps": self.has_rollback_steps,
            "primary_visible_steps": list(self.primary_visible_steps),
            "observability_highlight_steps": list(
                self.observability_highlight_steps
            ),
            "unresolved_count": self.unresolved_count,
            "is_fully_resolved": self.is_fully_resolved,
            "summarised_at": self.summarised_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSemanticSummary":
        """Reconstruct from a plain dict."""
        steps_raw = data.get("classified_steps") or []
        classified_steps: List[ClassifiedStep] = []
        for raw in steps_raw:
            if isinstance(raw, dict):
                try:
                    classified_steps.append(ClassifiedStep.from_dict(raw))
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)

        return cls(
            task_id=str(data.get("task_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            runtime_session_id=str(data.get("runtime_session_id") or ""),
            classified_steps=classified_steps,
            has_side_effectful_steps=bool(
                data.get("has_side_effectful_steps", False)
            ),
            has_cross_device_steps=bool(data.get("has_cross_device_steps", False)),
            has_confirmation_required_steps=bool(
                data.get("has_confirmation_required_steps", False)
            ),
            has_rollback_steps=bool(data.get("has_rollback_steps", False)),
            primary_visible_steps=list(
                data.get("primary_visible_steps") or []
            ),
            observability_highlight_steps=list(
                data.get("observability_highlight_steps") or []
            ),
            unresolved_count=int(data.get("unresolved_count", 0)),
            summarised_at=float(data.get("summarised_at") or time.time()),
        )

    def __repr__(self) -> str:
        return (
            f"<TaskSemanticSummary "
            f"task={self.task_id!r} "
            f"steps={self.total_steps} "
            f"unresolved={self.unresolved_count} "
            f"side_effectful={self.has_side_effectful_steps}>"
        )


# ---------------------------------------------------------------------------
# Pre-built empty summary
# ---------------------------------------------------------------------------

EMPTY_SEMANTIC_SUMMARY: TaskSemanticSummary = TaskSemanticSummary(
    task_id="",
    trace_id="",
    runtime_session_id="",
    classified_steps=[],
    has_side_effectful_steps=False,
    has_cross_device_steps=False,
    has_confirmation_required_steps=False,
    has_rollback_steps=False,
    primary_visible_steps=[],
    observability_highlight_steps=[],
    unresolved_count=0,
)
"""Pre-built :class:`TaskSemanticSummary` representing an empty / uninitialised state.

Use as a safe default / fallback when no semantic analysis has been run.
"""


# ---------------------------------------------------------------------------
# Projection adapter
# ---------------------------------------------------------------------------


def attach_semantic_summary_to_projection(
    projection_dict: Dict[str, Any],
    summary: TaskSemanticSummary,
) -> Dict[str, Any]:
    """Attach a :class:`TaskSemanticSummary` to a ``RuntimeProjection`` dict additively.

    The summary is inserted under the key ``"task_semantics"`` alongside any
    existing projection fields.  The original dict is **not** mutated.

    Args:
        projection_dict: Existing projection dict.
        summary: The :class:`TaskSemanticSummary` to attach.

    Returns:
        A new dict with ``"task_semantics"`` added.
    """
    if not isinstance(projection_dict, dict):
        projection_dict = {}
    return {
        **projection_dict,
        "task_semantics": summary.to_dict(),
    }


def get_semantic_hints(summary: TaskSemanticSummary) -> Dict[str, Any]:
    """Extract a compact hint dict from a :class:`TaskSemanticSummary`.

    Args:
        summary: A :class:`TaskSemanticSummary` instance.

    Returns:
        A plain dict with quick-check boolean/scalar keys:

        ``total_steps``
            Total number of classified steps.
        ``unresolved_count``
            Number of steps still unresolved (kind=unknown).
        ``is_fully_resolved``
            True if all steps have a specific kind.
        ``has_side_effectful_steps``
            True if any step is side-effectful.
        ``has_cross_device_steps``
            True if any step may run cross-device.
        ``has_confirmation_required_steps``
            True if any step requires confirmation.
        ``has_rollback_steps``
            True if any step is a rollback.
        ``primary_visible_step_count``
            Number of steps visible in manifest.
        ``observability_highlight_count``
            Number of steps that emit observability highlights.
        ``task_id``
            Task identifier.
        ``trace_id``
            Trace identifier.
    """
    return {
        "total_steps": summary.total_steps,
        "unresolved_count": summary.unresolved_count,
        "is_fully_resolved": summary.is_fully_resolved,
        "has_side_effectful_steps": summary.has_side_effectful_steps,
        "has_cross_device_steps": summary.has_cross_device_steps,
        "has_confirmation_required_steps": summary.has_confirmation_required_steps,
        "has_rollback_steps": summary.has_rollback_steps,
        "primary_visible_step_count": len(summary.primary_visible_steps),
        "observability_highlight_count": len(
            summary.observability_highlight_steps
        ),
        "task_id": summary.task_id,
        "trace_id": summary.trace_id,
    }
