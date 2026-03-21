#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_formation.formation_summary
==========================================

PR-17 (V4) — Device Formation & Multi-Device Group Model

Provides :class:`FormationSummary` — a compact, public-safe, JSON-serialisable
summary of a :class:`~.formation_group.DeviceFormationGroup` and its
associated :class:`~.formation_policy.FormationPolicy`.

Also provides helper functions:

* :func:`build_formation_summary` — build summary from group + policy.
* :func:`attach_formation_to_projection` — attach formation to a projection
  dict additively (following the PR-13/PR-14/PR-15 pattern).
* :func:`get_formation_hints` — return compact scalar hints for downstream
  checks.
* :func:`resolve_formation_summary` — one-call convenience helper that runs
  the resolver and builds the summary.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from .formation_group import DeviceFormationGroup, EMPTY_FORMATION_GROUP
from .formation_policy import BarrierPosture, FormationPolicy, DEFAULT_LOCAL_FORMATION_POLICY
from .formation_resolver import resolve_formation

__all__ = [
    "FormationSummary",
    "IDLE_FORMATION_SUMMARY",
    "build_formation_summary",
    "attach_formation_to_projection",
    "get_formation_hints",
    "resolve_formation_summary",
]


# ---------------------------------------------------------------------------
# FormationSummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FormationSummary:
    """Compact, public-safe summary of a device formation group.

    This is the preferred type for API responses, projection payloads, and log
    records.  It flattens the most important fields from
    :class:`~.formation_group.DeviceFormationGroup` and
    :class:`~.formation_policy.FormationPolicy` into a single serialisable
    object.

    Attributes
    ----------
    formation_id:
        Stable unique identifier for the formation.
    task_id:
        Task identifier (if available).
    trace_id:
        Distributed-trace identifier (if available).
    is_multi_device:
        ``True`` if more than one device participates.
    member_count:
        Total number of members in the formation.
    source_device_id:
        Device that originated the request.
    primary_execution_device_id:
        Device primarily responsible for execution.
    merge_owner_device_id:
        Device responsible for merging results.
    barrier_posture:
        String value of the barrier/completion posture.
    multi_device_required:
        ``True`` if the policy requires at least two devices.
    merge_confirmation_required:
        ``True`` if the policy requires merge confirmation.
    fallback_available:
        ``True`` if at least one FALLBACK member is present.
    formation_reason:
        Human-readable reason the formation was assembled.
    runtime_domain_intent:
        Runtime domain that triggered formation assembly.
    all_member_device_ids:
        List of all participating device IDs.
    fallback_device_ids:
        List of FALLBACK member device IDs.
    support_device_ids:
        List of SUPPORT member device IDs.
    observer_device_ids:
        List of OBSERVER member device IDs.
    relay_device_ids:
        List of RELAY member device IDs.
    policy_reason:
        Human-readable reason the policy was derived.
    schema_version:
        Schema version integer.
    """

    formation_id: str = "empty"
    task_id: Optional[str] = None
    trace_id: Optional[str] = None
    is_multi_device: bool = False
    member_count: int = 0
    source_device_id: Optional[str] = None
    primary_execution_device_id: Optional[str] = None
    merge_owner_device_id: Optional[str] = None
    barrier_posture: str = BarrierPosture.WAIT_PRIMARY.value
    multi_device_required: bool = False
    merge_confirmation_required: bool = False
    fallback_available: bool = False
    formation_reason: str = "no active formation"
    runtime_domain_intent: str = "local"
    all_member_device_ids: List[str] = dataclasses.field(default_factory=list)
    fallback_device_ids: List[str] = dataclasses.field(default_factory=list)
    support_device_ids: List[str] = dataclasses.field(default_factory=list)
    observer_device_ids: List[str] = dataclasses.field(default_factory=list)
    relay_device_ids: List[str] = dataclasses.field(default_factory=list)
    policy_reason: str = "default"
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "formation_id": self.formation_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "is_multi_device": self.is_multi_device,
            "member_count": self.member_count,
            "source_device_id": self.source_device_id,
            "primary_execution_device_id": self.primary_execution_device_id,
            "merge_owner_device_id": self.merge_owner_device_id,
            "barrier_posture": self.barrier_posture,
            "multi_device_required": self.multi_device_required,
            "merge_confirmation_required": self.merge_confirmation_required,
            "fallback_available": self.fallback_available,
            "formation_reason": self.formation_reason,
            "runtime_domain_intent": self.runtime_domain_intent,
            "all_member_device_ids": list(self.all_member_device_ids),
            "fallback_device_ids": list(self.fallback_device_ids),
            "support_device_ids": list(self.support_device_ids),
            "observer_device_ids": list(self.observer_device_ids),
            "relay_device_ids": list(self.relay_device_ids),
            "policy_reason": self.policy_reason,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_formation_summary(
    group: DeviceFormationGroup,
    policy: FormationPolicy,
) -> FormationSummary:
    """Build a :class:`FormationSummary` from a group and policy pair.

    Parameters
    ----------
    group:
        The :class:`~.formation_group.DeviceFormationGroup` to summarise.
    policy:
        The :class:`~.formation_policy.FormationPolicy` associated with the
        group.

    Returns
    -------
    FormationSummary
        A compact, public-safe summary.
    """
    from .formation_role import FormationRole

    fallback_available = any(
        m.role == FormationRole.FALLBACK for m in group.members
    )

    return FormationSummary(
        formation_id=group.formation_id,
        task_id=group.task_id,
        trace_id=group.trace_id,
        is_multi_device=group.is_multi_device,
        member_count=group.member_count,
        source_device_id=group.source_device_id,
        primary_execution_device_id=group.primary_execution_device_id,
        merge_owner_device_id=group.effective_merge_owner_device_id,
        barrier_posture=group.barrier_posture,
        multi_device_required=policy.multi_device_required,
        merge_confirmation_required=policy.merge_confirmation_required,
        fallback_available=fallback_available,
        formation_reason=group.formation_reason,
        runtime_domain_intent=group.runtime_domain_intent,
        all_member_device_ids=group.all_member_device_ids,
        fallback_device_ids=group.fallback_device_ids,
        support_device_ids=group.support_device_ids,
        observer_device_ids=group.observer_device_ids,
        relay_device_ids=group.relay_device_ids,
        policy_reason=policy.policy_reason,
        schema_version=group.schema_version,
    )


# ---------------------------------------------------------------------------
# Projection attachment
# ---------------------------------------------------------------------------


def attach_formation_to_projection(
    projection_dict: Dict[str, Any],
    summary: FormationSummary,
) -> Dict[str, Any]:
    """Attach a :class:`FormationSummary` to a projection dict additively.

    Follows the same additive pattern used by PR-13
    (:func:`~core.cross_device_policy.attach_cross_device_to_projection`) and
    PR-14 (:func:`~core.distributed_execution.attach_merge_summary_to_projection`).

    The original ``projection_dict`` is not mutated — a new dict is returned
    with the ``"device_formation"`` key added.

    Parameters
    ----------
    projection_dict:
        The projection dict to enrich.  Must be a ``dict``; non-dict values
        are silently treated as an empty dict.
    summary:
        The :class:`FormationSummary` to attach.

    Returns
    -------
    dict
        A new dict containing all original keys plus ``"device_formation"``.
    """
    if not isinstance(projection_dict, dict):
        projection_dict = {}

    result = dict(projection_dict)
    result["device_formation"] = summary.to_dict()
    return result


# ---------------------------------------------------------------------------
# Hints helper
# ---------------------------------------------------------------------------


def get_formation_hints(summary: FormationSummary) -> Dict[str, Any]:
    """Return compact scalar hints for quick downstream checks.

    Parameters
    ----------
    summary:
        A :class:`FormationSummary` to extract hints from.

    Returns
    -------
    dict
        A small dict with boolean and scalar fields suitable for conditional
        checks without inspecting the full summary.
    """
    return {
        "is_multi_device": summary.is_multi_device,
        "member_count": summary.member_count,
        "fallback_available": summary.fallback_available,
        "multi_device_required": summary.multi_device_required,
        "merge_confirmation_required": summary.merge_confirmation_required,
        "has_primary": summary.primary_execution_device_id is not None,
        "has_source": summary.source_device_id is not None,
        "has_merge_owner": summary.merge_owner_device_id is not None,
        "barrier_posture": summary.barrier_posture,
        "runtime_domain_intent": summary.runtime_domain_intent,
    }


# ---------------------------------------------------------------------------
# One-call convenience helper
# ---------------------------------------------------------------------------


def resolve_formation_summary(
    **kwargs: Any,
) -> FormationSummary:
    """Resolve a formation and return a :class:`FormationSummary` in one call.

    Accepts the same keyword arguments as :func:`~.formation_resolver.resolve_formation`.
    Always returns a valid :class:`FormationSummary` — never raises.

    Returns
    -------
    FormationSummary
        A compact summary of the resolved formation.
    """
    try:
        group, policy = resolve_formation(**kwargs)
        return build_formation_summary(group, policy)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger("Galaxy.DeviceFormation.Summary").warning(
            "resolve_formation_summary failed, returning idle summary: %s", exc
        )
        return IDLE_FORMATION_SUMMARY


# ---------------------------------------------------------------------------
# Pre-built idle sentinel
# ---------------------------------------------------------------------------

#: Pre-built idle summary for use when no active formation context is present.
IDLE_FORMATION_SUMMARY = FormationSummary(
    formation_id="empty",
    task_id=None,
    trace_id=None,
    is_multi_device=False,
    member_count=0,
    source_device_id=None,
    primary_execution_device_id=None,
    merge_owner_device_id=None,
    barrier_posture=BarrierPosture.WAIT_PRIMARY.value,
    multi_device_required=False,
    merge_confirmation_required=False,
    fallback_available=False,
    formation_reason="no active formation",
    runtime_domain_intent="local",
    all_member_device_ids=[],
    fallback_device_ids=[],
    support_device_ids=[],
    observer_device_ids=[],
    relay_device_ids=[],
    policy_reason="idle default",
    schema_version=1,
)
