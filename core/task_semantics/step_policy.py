#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.task_semantics.step_policy
================================

PR-15 (V4) — Task Semantics & Step Classes

Defines :class:`StepSemanticPolicy` — the stable, immutable, serialisable
policy object that describes the *semantic traits* of a single task step.

:class:`StepSemanticPolicy` answers:
  - Is the step side-effectful?
  - Can it run cross-device?
  - Is failure skippable, or must the whole task halt?
  - Should this step be visible / prominent in manifest/projection surfaces?
  - Should an observability highlight be emitted for this step?
  - What recovery posture is recommended when this step fails?

Design rules
------------
- All fields are ``None``-safe or carry stable defaults.
- ``to_dict()`` produces a stable, JSON-serialisable dict.
- ``from_dict()`` reconstructs from a plain dict (e.g. deserialised JSON).
- The policy does NOT replace or modify any execution engine; it is a
  descriptor that orchestration/recovery/projection layers may consume.

Relation to upstream packages
------------------------------
- :class:`~core.execution_policy.ExecutionPolicy` (PR-11) describes **task-level**
  execution permission bands.  :class:`StepSemanticPolicy` describes the
  **step-level** semantic traits *within* a task.
- :class:`~core.distributed_execution.RecoveryPosture` (PR-14) is reused as
  the type for ``preferred_recovery_posture``.
- :class:`~.step_kind.StepKind` must be resolved before constructing a policy;
  use :func:`~.step_resolver.resolve_step_kind` or pass an explicit kind.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional

from .step_kind import StepKind, is_side_effectful_kind, coerce_step_kind

__all__ = [
    "StepSemanticPolicy",
    "DEFAULT_SAFE_STEP_POLICY",
    "DEFAULT_EXECUTE_STEP_POLICY",
    "build_policy_for_kind",
]


# ---------------------------------------------------------------------------
# StepSemanticPolicy dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class StepSemanticPolicy:
    """Semantic policy traits for a single task step.

    Attributes
    ----------
    step_kind
        The :class:`~.step_kind.StepKind` this policy applies to.
    side_effectful
        Whether the step modifies external state (files, UI, APIs, etc.).
        Defaults to ``True`` when ``step_kind`` is in
        :data:`~.step_kind.SIDE_EFFECTFUL_KINDS`.
    requires_confirmation
        Whether the step must wait for explicit user/system confirmation
        before it can proceed.
    cross_device_allowed
        Whether the step may be dispatched to a non-local device.
    failure_skippable
        Whether the task can continue when this step fails.
        ``False`` (halt) is the conservative default.
    should_surface_in_manifest
        Whether the step should be visible in manifest/projection surfaces.
    should_emit_observability_highlight
        Whether an observability highlight event should be emitted when
        this step starts or completes.
    preferred_recovery_posture
        Optional string hint for the preferred
        :class:`~core.distributed_execution.RecoveryPosture` when this
        step fails.  ``None`` means no preference expressed (caller may
        apply global task recovery logic).
    policy_reason
        Human-readable note explaining why these traits were assigned.
    """

    step_kind: StepKind = StepKind.UNKNOWN
    side_effectful: bool = True
    requires_confirmation: bool = False
    cross_device_allowed: bool = False
    failure_skippable: bool = False
    should_surface_in_manifest: bool = True
    should_emit_observability_highlight: bool = False
    preferred_recovery_posture: Optional[str] = None
    policy_reason: str = ""

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain, JSON-serialisable dict.

        Enum values are converted to their string ``.value``.
        """
        return {
            "step_kind": self.step_kind.value
            if isinstance(self.step_kind, StepKind)
            else str(self.step_kind),
            "side_effectful": self.side_effectful,
            "requires_confirmation": self.requires_confirmation,
            "cross_device_allowed": self.cross_device_allowed,
            "failure_skippable": self.failure_skippable,
            "should_surface_in_manifest": self.should_surface_in_manifest,
            "should_emit_observability_highlight": self.should_emit_observability_highlight,
            "preferred_recovery_posture": self.preferred_recovery_posture,
            "policy_reason": self.policy_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepSemanticPolicy":
        """Reconstruct from a plain dict (e.g. deserialised from JSON).

        Degrades gracefully when fields are absent.
        """
        kind = coerce_step_kind(data.get("step_kind", StepKind.UNKNOWN))
        return cls(
            step_kind=kind,
            side_effectful=bool(
                data.get("side_effectful", is_side_effectful_kind(kind))
            ),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            cross_device_allowed=bool(data.get("cross_device_allowed", False)),
            failure_skippable=bool(data.get("failure_skippable", False)),
            should_surface_in_manifest=bool(
                data.get("should_surface_in_manifest", True)
            ),
            should_emit_observability_highlight=bool(
                data.get("should_emit_observability_highlight", False)
            ),
            preferred_recovery_posture=data.get("preferred_recovery_posture") or None,
            policy_reason=str(data.get("policy_reason") or ""),
        )

    def __repr__(self) -> str:
        return (
            f"<StepSemanticPolicy "
            f"kind={self.step_kind.value} "
            f"side_effectful={self.side_effectful} "
            f"cross_device={self.cross_device_allowed} "
            f"skippable={self.failure_skippable}>"
        )


# ---------------------------------------------------------------------------
# Pre-built default policies
# ---------------------------------------------------------------------------

DEFAULT_SAFE_STEP_POLICY: StepSemanticPolicy = StepSemanticPolicy(
    step_kind=StepKind.PERCEIVE,
    side_effectful=False,
    requires_confirmation=False,
    cross_device_allowed=False,
    failure_skippable=True,
    should_surface_in_manifest=False,
    should_emit_observability_highlight=False,
    preferred_recovery_posture=None,
    policy_reason="default safe/read-only policy for perceive steps",
)
"""Conservative safe-default policy for read-only steps."""

DEFAULT_EXECUTE_STEP_POLICY: StepSemanticPolicy = StepSemanticPolicy(
    step_kind=StepKind.EXECUTE,
    side_effectful=True,
    requires_confirmation=False,
    cross_device_allowed=False,
    failure_skippable=False,
    should_surface_in_manifest=True,
    should_emit_observability_highlight=True,
    preferred_recovery_posture="retry_same_device",
    policy_reason="default policy for execute steps",
)
"""Default policy for execution steps — side-effectful, non-skippable."""


# ---------------------------------------------------------------------------
# Factory: build a sensible default policy for a given StepKind
# ---------------------------------------------------------------------------

_KIND_DEFAULTS: Dict[str, Dict[str, Any]] = {
    StepKind.PERCEIVE.value: dict(
        side_effectful=False,
        requires_confirmation=False,
        cross_device_allowed=False,
        failure_skippable=True,
        should_surface_in_manifest=False,
        should_emit_observability_highlight=False,
        preferred_recovery_posture=None,
        policy_reason="inferred from perceive step kind",
    ),
    StepKind.ANALYZE.value: dict(
        side_effectful=False,
        requires_confirmation=False,
        cross_device_allowed=False,
        failure_skippable=True,
        should_surface_in_manifest=False,
        should_emit_observability_highlight=False,
        preferred_recovery_posture=None,
        policy_reason="inferred from analyze step kind",
    ),
    StepKind.DECIDE.value: dict(
        side_effectful=False,
        requires_confirmation=False,
        cross_device_allowed=False,
        failure_skippable=False,
        should_surface_in_manifest=True,
        should_emit_observability_highlight=False,
        preferred_recovery_posture=None,
        policy_reason="inferred from decide step kind",
    ),
    StepKind.EXECUTE.value: dict(
        side_effectful=True,
        requires_confirmation=False,
        cross_device_allowed=False,
        failure_skippable=False,
        should_surface_in_manifest=True,
        should_emit_observability_highlight=True,
        preferred_recovery_posture="retry_same_device",
        policy_reason="inferred from execute step kind",
    ),
    StepKind.CONFIRM.value: dict(
        side_effectful=False,
        requires_confirmation=True,
        cross_device_allowed=False,
        failure_skippable=False,
        should_surface_in_manifest=True,
        should_emit_observability_highlight=True,
        preferred_recovery_posture="require_confirmation",
        policy_reason="inferred from confirm step kind",
    ),
    StepKind.NOTIFY.value: dict(
        side_effectful=True,
        requires_confirmation=False,
        cross_device_allowed=True,
        failure_skippable=True,
        should_surface_in_manifest=False,
        should_emit_observability_highlight=False,
        preferred_recovery_posture="skip_optional_branch",
        policy_reason="inferred from notify step kind",
    ),
    StepKind.ROLLBACK.value: dict(
        side_effectful=True,
        requires_confirmation=False,
        cross_device_allowed=False,
        failure_skippable=False,
        should_surface_in_manifest=True,
        should_emit_observability_highlight=True,
        preferred_recovery_posture="abort_task",
        policy_reason="inferred from rollback step kind",
    ),
    StepKind.OBSERVE_REMOTE.value: dict(
        side_effectful=False,
        requires_confirmation=False,
        cross_device_allowed=True,
        failure_skippable=True,
        should_surface_in_manifest=False,
        should_emit_observability_highlight=False,
        preferred_recovery_posture=None,
        policy_reason="inferred from observe_remote step kind",
    ),
    StepKind.UNKNOWN.value: dict(
        side_effectful=True,
        requires_confirmation=False,
        cross_device_allowed=False,
        failure_skippable=False,
        should_surface_in_manifest=True,
        should_emit_observability_highlight=False,
        preferred_recovery_posture="retry_same_device",
        policy_reason="conservative default for unknown step kind",
    ),
}


def build_policy_for_kind(
    kind: object,
    *,
    policy_reason: Optional[str] = None,
    cross_device_allowed: Optional[bool] = None,
    failure_skippable: Optional[bool] = None,
    requires_confirmation: Optional[bool] = None,
) -> StepSemanticPolicy:
    """Build a :class:`StepSemanticPolicy` with defaults derived from *kind*.

    All keyword arguments are optional overrides; when supplied they take
    precedence over the kind's built-in defaults.

    Args:
        kind:
            A :class:`~.step_kind.StepKind` value or a string that will be
            coerced via :func:`~.step_kind.coerce_step_kind`.
        policy_reason:
            Optional override for the ``policy_reason`` field.
        cross_device_allowed:
            Optional override for ``cross_device_allowed``.
        failure_skippable:
            Optional override for ``failure_skippable``.
        requires_confirmation:
            Optional override for ``requires_confirmation``.

    Returns:
        A new :class:`StepSemanticPolicy` with appropriate defaults.
    """
    coerced = coerce_step_kind(kind)
    defaults = dict(_KIND_DEFAULTS.get(coerced.value, _KIND_DEFAULTS[StepKind.UNKNOWN.value]))

    if policy_reason is not None:
        defaults["policy_reason"] = policy_reason
    if cross_device_allowed is not None:
        defaults["cross_device_allowed"] = cross_device_allowed
    if failure_skippable is not None:
        defaults["failure_skippable"] = failure_skippable
    if requires_confirmation is not None:
        defaults["requires_confirmation"] = requires_confirmation

    return StepSemanticPolicy(step_kind=coerced, **defaults)
