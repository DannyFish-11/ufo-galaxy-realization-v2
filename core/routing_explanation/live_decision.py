#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.routing_explanation.live_decision
=========================================

PR-H — Live Routing Explanation & Decision-Causality Wiring

Provides :class:`LiveRoutingDecisionBuilder`, a lightweight per-call collector
that gathers routing signals *during* a live ``CommandRouter.route_envelope``
invocation and assembles a :class:`~.route_explanation.RouteExplanation` that
reflects actual decision causality — not projection defaults or placeholder
summaries.

Design rules
------------
- One builder instance per ``route_envelope`` call (never a singleton).
- All ``record_*`` methods are safe to call even when the underlying data is
  absent — they degrade gracefully by recording no basis rather than raising.
- :meth:`build` always returns a valid :class:`RouteExplanation` (falling back
  to :data:`~.route_explanation.EMPTY_ROUTE_EXPLANATION` on error).
- This module is write-only at call time: it does NOT read from or modify any
  routing state; it only observes signals passed to it.

Integration points in ``CommandRouter.route_envelope``
------------------------------------------------------
1. :meth:`record_posture_gate` — after the session-truth posture eligibility
   check (Gate A).
2. :meth:`record_admissibility_gate` — after the per-target admissibility check
   (Gate B), once validated and excluded sets are known.
3. :meth:`record_capability_enforcement` — after the capability-graph
   enforcement step.
4. :meth:`record_route_path_selection` — once the dispatch branch is resolved
   (cross-device, worker, local, or parallel-fanout).
5. :meth:`record_result_outcome` — after the dispatch result is available, to
   capture fallback or failure causes.
6. :meth:`build` — called last to produce the final :class:`RouteExplanation`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .decision_basis import (
    DecisionBasis,
    DecisionFactor,
    make_decision_basis,
    basis_from_availability,
    basis_from_capability,
    basis_from_health_score,
    basis_from_policy_posture,
)
from .route_explanation import (
    RejectedCandidate,
    RouteExplanation,
    build_route_explanation,
    EMPTY_ROUTE_EXPLANATION,
)
from .explanation_summary import (
    RoutingExplanationSummary,
    build_explanation_summary,
    IDLE_EXPLANATION_SUMMARY,
)

__all__ = [
    "LiveRoutingDecisionBuilder",
    "live_explanation_to_record_str",
]


# ---------------------------------------------------------------------------
# Route-path labels
# ---------------------------------------------------------------------------

ROUTE_PATH_CROSS_DEVICE = "cross_device"
ROUTE_PATH_WORKER = "go_worker"
ROUTE_PATH_LOCAL = "local"
ROUTE_PATH_PARALLEL_FANOUT = "parallel_fanout"

_ROUTE_PATH_REASONS: Dict[str, str] = {
    ROUTE_PATH_CROSS_DEVICE: (
        "Explicit executor_target_type or metadata cross_device=true directed "
        "dispatch to the cross-device substrate (DeviceRouter)."
    ),
    ROUTE_PATH_WORKER: (
        "Explicit executor_target_type=go_worker directed dispatch to the "
        "MasterBrain worker domain."
    ),
    ROUTE_PATH_LOCAL: (
        "No cross-device or worker hint present; task dispatched via the local "
        "execution runtime."
    ),
    ROUTE_PATH_PARALLEL_FANOUT: (
        "metadata parallel_fanout=true directed dispatch to the canonical "
        "parallel fan-out path (multiple concurrent sub-envelopes)."
    ),
}


# ---------------------------------------------------------------------------
# LiveRoutingDecisionBuilder
# ---------------------------------------------------------------------------


class LiveRoutingDecisionBuilder:
    """Collect live routing signals and produce a :class:`RouteExplanation`.

    Usage::

        builder = LiveRoutingDecisionBuilder(task_id=..., trace_id=...)
        # ... routing proceeds ...
        builder.record_posture_gate(posture="local_preferred", eligible=True)
        builder.record_admissibility_gate(
            validated=["device-1"],
            excluded=[("device-2", ["not-ready"])],
        )
        builder.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="device-1")
        explanation = builder.build()

    All ``record_*`` methods are idempotent-safe: calling them with empty /
    ``None`` inputs is a no-op and never raises.
    """

    def __init__(
        self,
        task_id: str = "",
        trace_id: str = "",
    ) -> None:
        self._task_id = task_id
        self._trace_id = trace_id
        self._decision_bases: List[DecisionBasis] = []
        self._rejected_candidates: List[RejectedCandidate] = []
        self._selected_target: Optional[str] = None
        self._policy_posture: str = "undecided"
        self._policy_reason: str = ""
        self._policy_band: Optional[str] = None
        self._fallback_plan: Optional[str] = None
        self._route_path: Optional[str] = None

    # ------------------------------------------------------------------
    # Signal recorders
    # ------------------------------------------------------------------

    def record_posture_gate(
        self,
        posture: str,
        eligible: bool,
        *,
        reason: str = "",
    ) -> None:
        """Record the session-truth / posture eligibility gate result.

        Args:
            posture:  Posture string (e.g. ``"local_preferred"``).
            eligible: Whether the source is eligible to execute on this path.
            reason:   Optional human-readable elaboration.
        """
        if not posture:
            return
        self._policy_posture = posture
        desc_suffix = reason or (
            "source is eligible for local execution"
            if eligible
            else "control-only source flagged on non-cross-device path"
        )
        basis = make_decision_basis(
            factor=DecisionFactor.POLICY,
            signal_value=posture,
            description=f"Posture gate: '{posture}' — {desc_suffix}",
            accepted=eligible,
            weight=0.20,
        )
        self._decision_bases.append(basis)

    def record_admissibility_gate(
        self,
        validated: List[str],
        excluded: List[tuple],  # list of (device_id, reasons_list)
    ) -> None:
        """Record the per-target admissibility (readiness/capability) gate.

        Args:
            validated: Device IDs that passed the admissibility check.
            excluded:  Pairs of ``(device_id, reasons)`` for rejected devices.
        """
        if validated:
            basis = make_decision_basis(
                factor=DecisionFactor.AVAILABILITY,
                signal_value=validated,
                description=(
                    f"{len(validated)} target(s) passed admissibility check: "
                    f"{validated}"
                ),
                accepted=True,
                weight=0.15,
            )
            self._decision_bases.append(basis)

        for dev_id, reasons in (excluded or []):
            reason_str = ", ".join(str(r) for r in (reasons or [])) or "failed admissibility check"
            self._rejected_candidates.append(
                RejectedCandidate(
                    candidate_id=str(dev_id),
                    rejection_reason=reason_str,
                    was_available=False,
                )
            )
            basis_rej = make_decision_basis(
                factor=DecisionFactor.AVAILABILITY,
                signal_value=False,
                description=(
                    f"Target '{dev_id}' excluded by admissibility gate: {reason_str}"
                ),
                accepted=False,
                weight=0.15,
            )
            self._decision_bases.append(basis_rej)

    def record_capability_enforcement(
        self,
        confirmed: List[str],
        unconfirmed: List[str],
        required_caps: Optional[List[str]] = None,
    ) -> None:
        """Record capability-graph enforcement results.

        Args:
            confirmed:     Device IDs confirmed in the capability graph.
            unconfirmed:   Device IDs NOT found in the capability graph.
            required_caps: Capability constraints that were checked.
        """
        cap_str = f"caps={required_caps}" if required_caps else "no capability filter"
        if confirmed:
            basis = make_decision_basis(
                factor=DecisionFactor.CAPABILITY,
                signal_value=confirmed,
                description=(
                    f"{len(confirmed)} target(s) confirmed in capability graph "
                    f"({cap_str}): {confirmed}"
                ),
                accepted=True,
                weight=0.15,
            )
            self._decision_bases.append(basis)

        for dev_id in unconfirmed or []:
            self._rejected_candidates.append(
                RejectedCandidate(
                    candidate_id=str(dev_id),
                    rejection_reason=(
                        f"not confirmed in capability graph for {cap_str}"
                    ),
                    capability_match=False,
                )
            )
            basis_rej = make_decision_basis(
                factor=DecisionFactor.CAPABILITY,
                signal_value=False,
                description=(
                    f"Target '{dev_id}' not confirmed in capability graph "
                    f"({cap_str})"
                ),
                accepted=False,
                weight=0.15,
            )
            self._decision_bases.append(basis_rej)

    def record_route_path_selection(
        self,
        path: str,
        selected_target: Optional[str] = None,
        *,
        reason: str = "",
    ) -> None:
        """Record which routing path branch was selected and why.

        Args:
            path:             Route path label (use ``ROUTE_PATH_*`` constants).
            selected_target:  Primary target device ID or route label, if known.
            reason:           Optional explicit reason overriding the default.
        """
        if path:
            self._route_path = path
        if selected_target:
            self._selected_target = selected_target

        desc = reason or _ROUTE_PATH_REASONS.get(path, f"route path: {path}")
        basis = make_decision_basis(
            factor=DecisionFactor.POLICY,
            signal_value=path,
            description=desc,
            accepted=True,
            weight=0.30,
        )
        self._decision_bases.append(basis)

    def record_policy_band(self, band: str) -> None:
        """Record the execution-policy band active at dispatch time.

        Args:
            band: Policy band string (e.g. ``"bounded_execute"``).
        """
        if not band:
            return
        self._policy_band = band
        basis = make_decision_basis(
            factor=DecisionFactor.EXECUTION_BUDGET,
            signal_value=band,
            description=f"Execution policy band: '{band}'",
            accepted=True,
            weight=0.10,
        )
        self._decision_bases.append(basis)

    def record_fallback(
        self,
        fallback_device_ids: List[str],
        *,
        reason: str = "",
    ) -> None:
        """Record that a fallback path was engaged.

        Args:
            fallback_device_ids: Device IDs available as fallback.
            reason:              Optional description of why fallback was triggered.
        """
        if fallback_device_ids:
            self._fallback_plan = (
                reason
                or f"Fallback device(s) available: {', '.join(fallback_device_ids)}"
            )
        elif reason:
            self._fallback_plan = reason

        if self._fallback_plan:
            basis = make_decision_basis(
                factor=DecisionFactor.FALLBACK,
                signal_value=True,
                description=self._fallback_plan,
                accepted=True,
                weight=0.05,
            )
            self._decision_bases.append(basis)

    def record_result_outcome(
        self,
        success: bool,
        error_code: str = "",
        via: str = "",
    ) -> None:
        """Record the final dispatch outcome.

        Args:
            success:    Whether dispatch succeeded.
            error_code: Error code string if dispatch failed.
            via:        The ``via`` field from the result (transit label).
        """
        if not success and error_code:
            basis = make_decision_basis(
                factor=DecisionFactor.AVAILABILITY,
                signal_value=False,
                description=(
                    f"Dispatch failed: error_code='{error_code}'"
                    + (f" via='{via}'" if via else "")
                ),
                accepted=False,
                weight=0.10,
            )
            self._decision_bases.append(basis)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> RouteExplanation:
        """Assemble and return the :class:`RouteExplanation`.

        Uses the signals recorded via the ``record_*`` methods.  Returns
        :data:`~.route_explanation.EMPTY_ROUTE_EXPLANATION` if assembly fails.
        """
        policy_reason = self._policy_reason or _derive_policy_reason(
            self._route_path,
            self._policy_posture,
        )
        return build_route_explanation(
            selected_target=self._selected_target,
            decision_bases=list(self._decision_bases),
            rejected_candidates=list(self._rejected_candidates),
            policy_posture=self._policy_posture,
            policy_reason=policy_reason,
            policy_band=self._policy_band,
            fallback_plan=self._fallback_plan,
            owner_agent=None,
            owner_component="CommandRouter.route_envelope",
            task_id=self._task_id or None,
            trace_id=self._trace_id or None,
        )

    def build_summary(self) -> RoutingExplanationSummary:
        """Build and return the :class:`RoutingExplanationSummary`.

        Convenience wrapper around :meth:`build` →
        :func:`~.explanation_summary.build_explanation_summary`.
        """
        try:
            return build_explanation_summary(self.build())
        except Exception:
            return IDLE_EXPLANATION_SUMMARY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_policy_reason(
    route_path: Optional[str],
    policy_posture: str,
) -> str:
    """Derive a human-readable policy reason from path and posture signals."""
    if route_path and route_path in _ROUTE_PATH_REASONS:
        base = _ROUTE_PATH_REASONS[route_path]
    else:
        base = "routing decision made by CommandRouter.route_envelope"
    if policy_posture and policy_posture != "undecided":
        return f"{base}  Posture: '{policy_posture}'."
    return base


def live_explanation_to_record_str(explanation: RouteExplanation) -> str:
    """Serialise a :class:`RouteExplanation` to a JSON string suitable for
    storage in :attr:`~core.replay_foundation.RouteDecisionRecord.route_explanation`.

    Falls back to a minimal placeholder string on serialisation failure.
    """
    try:
        return json.dumps(explanation.to_dict(), ensure_ascii=False)
    except Exception:
        return (
            f"live_routing_explanation: "
            f"selected={explanation.selected_target!r} "
            f"path={explanation.policy_posture!r} "
            f"bases={len(explanation.decision_bases)} "
            f"rejected={len(explanation.rejected_candidates)}"
        )
