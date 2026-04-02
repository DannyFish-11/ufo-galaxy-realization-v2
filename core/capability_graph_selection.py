#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_graph_selection.py
=====================================
PR-D: Capability + Network Runtime Convergence — Capability Selection Plane.

Promotes the ``CapabilityAssimilationLayer`` from a passive registry into an
active **capability selection plane** that planner, router, and policy modules
can query to discover, score, and select capability providers / executors.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  CAPABILITY SELECTION PLANE  (this module, Layer 10-selection)      │
    │                                                                      │
    │  Consumes:                                                           │
    │    • CapabilityAssimilationLayer   (live capability descriptors)     │
    │    • ExecutionProfile              (participant kind, priority)      │
    │    • AssimilationPresenceState     (online / degraded / offline)     │
    │                                                                      │
    │  Exposes:                                                            │
    │    • discover_providers(capabilities)  → List[AssimilationRecord]   │
    │    • select_best_provider(task_caps)   → Optional[AssimilationRecord]│
    │    • select_fallback_providers(…)      → List[AssimilationRecord]   │
    │    • explain_selection(record)         → SelectionExplanation        │
    └──────────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **Read-only consumer of CapabilityAssimilationLayer.**
    This module MUST NOT write to the assimilation layer.
2.  **No direct topology access.**
    Transport path scoring is delegated to :mod:`core.capability_network_bridge`.
3.  **All selection decisions are observable.**
    Every discovery / selection call is recorded in a 256-entry ring buffer.

Public API
----------
Authority sentinels:
    CAPABILITY_GRAPH_SELECTION_AUTHORITY
    CAPABILITY_SELECTION_PLANE_LAYER_POSITION
    CAPABILITY_SELECTION_POLICY

Dataclasses:
    CapabilityFitScore
    SelectionExplanation
    SelectionRecord

Functions:
    discover_providers(capabilities, *, kind_filter, require_online)
        -> List[AssimilationRecord]
    score_provider(record, required_capabilities)
        -> CapabilityFitScore
    select_best_provider(required_capabilities, *, kind_filter)
        -> Optional[AssimilationRecord]
    select_fallback_providers(required_capabilities, *, exclude_ids, kind_filter)
        -> List[AssimilationRecord]
    explain_selection(record, required_capabilities)
        -> SelectionExplanation
    get_selection_log()
        -> Deque[SelectionRecord]
    reset_selection_log()
        -> None  # for testing
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.CapabilityGraphSelection")

__all__ = [
    # Authority sentinels
    "CAPABILITY_GRAPH_SELECTION_AUTHORITY",
    "CAPABILITY_SELECTION_PLANE_LAYER_POSITION",
    "CAPABILITY_SELECTION_POLICY",
    # Dataclasses
    "CapabilityFitScore",
    "SelectionExplanation",
    "SelectionRecord",
    # Functions
    "discover_providers",
    "score_provider",
    "select_best_provider",
    "select_fallback_providers",
    "explain_selection",
    "get_selection_log",
    "reset_selection_log",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

CAPABILITY_GRAPH_SELECTION_AUTHORITY: str = (
    "core.capability_graph_selection"
    " — canonical capability selection plane (PR-D)"
)
"""Sentinel: this module is the canonical capability selection plane.

Import this sentinel to assert that a call site queries capability candidates
through the selection plane rather than reading raw assimilation records.
"""

CAPABILITY_SELECTION_PLANE_LAYER_POSITION: int = 10
"""Layer position in the canonical control-plane stack.

Layer 10 sits above the capability assimilation layer (Layer 7) and is
consumed by planner / policy / router at layer 11+.
"""

CAPABILITY_SELECTION_POLICY: str = (
    "CAPABILITY_SELECTION_PLANE_V1: planner/router/policy MUST query "
    "capability candidates via core.capability_graph_selection rather than "
    "reading raw AssimilationRecord collections directly."
)
"""Policy sentinel: governs consumer access to capability candidates.

All planner / router / policy code that needs to select an executor or provider
MUST use the functions in this module rather than calling
``CapabilityAssimilationLayer.list_records()`` directly.
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RING_BUFFER_SIZE: int = 256

# Priority order for NodeParticipantKind — higher = preferred in tie-breaks.
# Kinds not listed get priority 0.
_KIND_PRIORITY: Dict[str, int] = {
    "capability_provider": 10,
    "worker": 9,
    "specialist": 8,
    "device": 7,
    "mcp_provider": 7,
    "skill": 7,
    "fabric_participant": 2,
    "legacy_facade": 1,
    "unknown": 0,
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CapabilityFitScore:
    """Numeric fit score for a single capability provider against a task.

    Attributes:
        node_id:            Provider node identifier.
        required_matched:   Number of required capabilities matched.
        required_total:     Total number of required capabilities.
        coverage_ratio:     ``required_matched / required_total`` (0.0–1.0).
        kind_priority:      Score contribution from :attr:`NodeParticipantKind`.
        is_online:          Whether the provider is currently online.
        total_score:        Composite score used for ranking.
        matched_caps:       Capability names that were matched.
        missing_caps:       Required capabilities that were not found.
    """

    node_id: str
    required_matched: int
    required_total: int
    coverage_ratio: float
    kind_priority: int
    is_online: bool
    total_score: float
    matched_caps: List[str] = field(default_factory=list)
    missing_caps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "required_matched": self.required_matched,
            "required_total": self.required_total,
            "coverage_ratio": self.coverage_ratio,
            "kind_priority": self.kind_priority,
            "is_online": self.is_online,
            "total_score": self.total_score,
            "matched_caps": list(self.matched_caps),
            "missing_caps": list(self.missing_caps),
        }


@dataclass
class SelectionExplanation:
    """Human-readable explanation for a capability selection decision.

    Attributes:
        node_id:             Selected provider node identifier.
        participant_kind:    Provider kind string.
        fit_score:           Detailed fit score.
        reason:              Short reason sentence.
        alternatives_count:  How many other providers were considered.
        alternatives_ids:    Top alternative node IDs (up to 3).
        selected_at:         Monotonic timestamp.
    """

    node_id: str
    participant_kind: str
    fit_score: CapabilityFitScore
    reason: str
    alternatives_count: int = 0
    alternatives_ids: List[str] = field(default_factory=list)
    selected_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "participant_kind": self.participant_kind,
            "fit_score": self.fit_score.to_dict(),
            "reason": self.reason,
            "alternatives_count": self.alternatives_count,
            "alternatives_ids": list(self.alternatives_ids),
            "selected_at": self.selected_at,
        }


@dataclass
class SelectionRecord:
    """Observability record for one selection event (ring-buffer entry).

    Attributes:
        record_id:            Monotonically increasing record ID.
        operation:            ``"discover"`` | ``"select_best"`` | ``"fallback"`` | ``"explain"``.
        required_capabilities: Capabilities that were searched for.
        result_ids:           Node IDs returned / selected.
        candidate_count:      Total candidates evaluated.
        timestamp:            Monotonic timestamp.
        notes:                Optional diagnostic notes.
    """

    record_id: int
    operation: str
    required_capabilities: List[str]
    result_ids: List[str]
    candidate_count: int
    timestamp: float = field(default_factory=time.monotonic)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "operation": self.operation,
            "required_capabilities": list(self.required_capabilities),
            "result_ids": list(self.result_ids),
            "candidate_count": self.candidate_count,
            "timestamp": self.timestamp,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Module-level ring buffer
# ---------------------------------------------------------------------------

_selection_log: Deque[SelectionRecord] = deque(maxlen=_RING_BUFFER_SIZE)
_record_counter: int = 0


def _next_record_id() -> int:
    global _record_counter
    _record_counter += 1
    return _record_counter


def _emit_record(
    operation: str,
    required_caps: List[str],
    result_ids: List[str],
    candidate_count: int,
    notes: Optional[List[str]] = None,
) -> None:
    rec = SelectionRecord(
        record_id=_next_record_id(),
        operation=operation,
        required_capabilities=list(required_caps),
        result_ids=list(result_ids),
        candidate_count=candidate_count,
        notes=list(notes or []),
    )
    _selection_log.append(rec)


# ---------------------------------------------------------------------------
# Core selection functions
# ---------------------------------------------------------------------------


def discover_providers(
    capabilities: Optional[List[str]] = None,
    *,
    kind_filter: Optional[List[str]] = None,
    require_online: bool = True,
) -> List[Any]:
    """Discover all capability providers that match the requested capabilities.

    Args:
        capabilities:  Required capability names.  If *None* or empty, all
                       providers are returned (subject to ``require_online``).
        kind_filter:   Optional list of :class:`NodeParticipantKind` *values*
                       (strings) to restrict results to.  E.g.
                       ``["device", "mcp_provider"]``.
        require_online: If *True* (default), only ONLINE providers are returned.

    Returns:
        List of :class:`~core.capability_assimilation.AssimilationRecord`
        objects that match the criteria, ordered by descending fit score.
    """
    try:
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            AssimilationPresenceState,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("capability_graph_selection: assimilation layer unavailable — %s", exc)
        _emit_record("discover", list(capabilities or []), [], 0, [str(exc)])
        return []

    layer = get_capability_assimilation_layer()
    all_records = layer.list_records()

    required: List[str] = list(capabilities or [])
    kind_set: Optional[Set[str]] = set(kind_filter) if kind_filter else None

    candidates = []
    for rec in all_records:
        # Presence filter
        if require_online:
            state = rec.fabric_presence.presence_state
            if isinstance(state, str):
                if state not in (
                    AssimilationPresenceState.ONLINE.value,
                    AssimilationPresenceState.DEGRADED.value,
                ):
                    continue
            else:
                if state not in (
                    AssimilationPresenceState.ONLINE,
                    AssimilationPresenceState.DEGRADED,
                ):
                    continue

        # Kind filter
        if kind_set is not None:
            kind_val = rec.execution_profile.participant_kind
            kind_str = kind_val.value if hasattr(kind_val, "value") else str(kind_val)
            if kind_str not in kind_set:
                continue

        candidates.append(rec)

    # Score and sort
    scored = [(score_provider(r, required), r) for r in candidates]
    scored.sort(key=lambda x: x[0].total_score, reverse=True)
    results = [r for _, r in scored]

    _emit_record(
        "discover",
        required,
        [r.node_id for r in results],
        len(candidates),
    )
    return results


def score_provider(
    record: Any,
    required_capabilities: Optional[List[str]] = None,
) -> "CapabilityFitScore":
    """Compute a :class:`CapabilityFitScore` for *record* against *required_capabilities*.

    Args:
        record:                The :class:`~core.capability_assimilation.AssimilationRecord`
                               to score.
        required_capabilities: List of capability names the task needs.

    Returns:
        A populated :class:`CapabilityFitScore`.
    """
    try:
        from core.capability_assimilation import AssimilationPresenceState
    except Exception:  # pragma: no cover
        AssimilationPresenceState = None  # type: ignore[assignment]

    required: List[str] = list(required_capabilities or [])
    provider_caps: Set[str] = set(record.capability_descriptor.capabilities or [])

    matched = [c for c in required if c in provider_caps]
    missing = [c for c in required if c not in provider_caps]
    total = len(required)
    coverage = len(matched) / total if total > 0 else 1.0

    kind_val = record.execution_profile.participant_kind
    kind_str = kind_val.value if hasattr(kind_val, "value") else str(kind_val)
    kind_prio = _KIND_PRIORITY.get(kind_str, 0)

    state = record.fabric_presence.presence_state
    if AssimilationPresenceState is not None:
        online = state in (
            AssimilationPresenceState.ONLINE,
            AssimilationPresenceState.ONLINE.value,
        )
    else:
        online = str(state) in ("online", "AssimilationPresenceState.ONLINE")

    # Composite score: coverage is most important, then kind priority, then
    # a small degraded-state penalty.
    degraded_penalty = 0.1 if not online else 0.0
    total_score = (coverage * 10.0) + (kind_prio * 0.5) - degraded_penalty

    return CapabilityFitScore(
        node_id=record.node_id,
        required_matched=len(matched),
        required_total=total,
        coverage_ratio=coverage,
        kind_priority=kind_prio,
        is_online=online,
        total_score=total_score,
        matched_caps=matched,
        missing_caps=missing,
    )


def select_best_provider(
    required_capabilities: Optional[List[str]] = None,
    *,
    kind_filter: Optional[List[str]] = None,
) -> Optional[Any]:
    """Select the single best capability provider for the given required capabilities.

    Args:
        required_capabilities: Capability names the task requires.
        kind_filter:           Optional participant kind restriction.

    Returns:
        The :class:`~core.capability_assimilation.AssimilationRecord` with the
        highest :class:`CapabilityFitScore`, or *None* if no suitable provider
        is available.
    """
    candidates = discover_providers(
        capabilities=required_capabilities,
        kind_filter=kind_filter,
        require_online=True,
    )

    result_id = candidates[0].node_id if candidates else None
    _emit_record(
        "select_best",
        list(required_capabilities or []),
        [result_id] if result_id else [],
        len(candidates),
    )
    return candidates[0] if candidates else None


def select_fallback_providers(
    required_capabilities: Optional[List[str]] = None,
    *,
    exclude_ids: Optional[List[str]] = None,
    kind_filter: Optional[List[str]] = None,
    max_results: int = 3,
) -> List[Any]:
    """Return ordered fallback providers, excluding the primary candidates.

    Used when the primary provider is unavailable or has returned a failure.
    Also includes DEGRADED providers as candidates of last resort.

    Args:
        required_capabilities: Capability names the task requires.
        exclude_ids:           Node IDs to exclude (e.g. the already-failed
                               primary provider).
        kind_filter:           Optional participant kind restriction.
        max_results:           Maximum fallback candidates to return.

    Returns:
        Ordered list of fallback :class:`~core.capability_assimilation.AssimilationRecord`
        objects (best fit first), up to *max_results*.
    """
    excluded: Set[str] = set(exclude_ids or [])

    # Include degraded providers as fallback by relaxing require_online=True
    try:
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            AssimilationPresenceState,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("capability_graph_selection: assimilation layer unavailable — %s", exc)
        _emit_record("fallback", list(required_capabilities or []), [], 0, [str(exc)])
        return []

    layer = get_capability_assimilation_layer()
    all_records = layer.list_records()
    required: List[str] = list(required_capabilities or [])
    kind_set: Optional[Set[str]] = set(kind_filter) if kind_filter else None

    candidates = []
    for rec in all_records:
        if rec.node_id in excluded:
            continue

        state = rec.fabric_presence.presence_state
        state_str = state.value if hasattr(state, "value") else str(state)
        # Accept online or degraded
        if state_str not in ("online", "degraded"):
            continue

        if kind_set is not None:
            kind_val = rec.execution_profile.participant_kind
            kind_str = kind_val.value if hasattr(kind_val, "value") else str(kind_val)
            if kind_str not in kind_set:
                continue

        candidates.append(rec)

    scored = [(score_provider(r, required), r) for r in candidates]
    scored.sort(key=lambda x: x[0].total_score, reverse=True)
    results = [r for _, r in scored[:max_results]]

    _emit_record(
        "fallback",
        required,
        [r.node_id for r in results],
        len(candidates),
        [f"excluded={sorted(excluded)}"],
    )
    return results


def explain_selection(
    record: Any,
    required_capabilities: Optional[List[str]] = None,
    *,
    alternatives: Optional[List[Any]] = None,
) -> SelectionExplanation:
    """Produce a human-readable explanation for why *record* was selected.

    Args:
        record:                The selected :class:`~core.capability_assimilation.AssimilationRecord`.
        required_capabilities: Capability names the task required.
        alternatives:          Other candidate records that were not chosen.

    Returns:
        A :class:`SelectionExplanation` describing the selection decision.
    """
    fit = score_provider(record, required_capabilities)

    kind_val = record.execution_profile.participant_kind
    kind_str = kind_val.value if hasattr(kind_val, "value") else str(kind_val)

    if fit.required_total == 0:
        reason = (
            f"Provider '{record.node_id}' selected as {kind_str}: "
            "no specific capabilities required; selected as best available."
        )
    elif fit.coverage_ratio >= 1.0:
        reason = (
            f"Provider '{record.node_id}' selected as {kind_str}: "
            f"full capability match ({fit.required_matched}/{fit.required_total} capabilities: "
            f"{', '.join(fit.matched_caps)})."
        )
    elif fit.coverage_ratio > 0:
        reason = (
            f"Provider '{record.node_id}' selected as {kind_str}: "
            f"partial capability match ({fit.required_matched}/{fit.required_total}; "
            f"matched: {', '.join(fit.matched_caps)}; "
            f"missing: {', '.join(fit.missing_caps)})."
        )
    else:
        reason = (
            f"Provider '{record.node_id}' selected as {kind_str}: "
            "no capability match — selected as only available provider."
        )

    alts = list(alternatives or [])
    alt_ids = [a.node_id for a in alts[:3]]

    expl = SelectionExplanation(
        node_id=record.node_id,
        participant_kind=kind_str,
        fit_score=fit,
        reason=reason,
        alternatives_count=len(alts),
        alternatives_ids=alt_ids,
    )

    _emit_record(
        "explain",
        list(required_capabilities or []),
        [record.node_id],
        1 + len(alts),
    )
    return expl


# ---------------------------------------------------------------------------
# Ring buffer access
# ---------------------------------------------------------------------------


def get_selection_log() -> Deque[SelectionRecord]:
    """Return the 256-entry selection observability ring buffer (read-only view)."""
    return _selection_log


def reset_selection_log() -> None:
    """Clear the selection log (for testing)."""
    global _record_counter
    _selection_log.clear()
    _record_counter = 0
