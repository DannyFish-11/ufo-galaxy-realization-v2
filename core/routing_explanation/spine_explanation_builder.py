#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.routing_explanation.spine_explanation_builder
====================================================

PR-H — Live Routing Explanation & Decision-Causality Wiring

Provides :class:`SpineDecisionCollector` and :func:`build_spine_explanation`
to capture live routing decision signals emitted by
``CommandRouter.route_envelope()`` and assemble them into a fully structured
:class:`~.route_explanation.RouteExplanation` whose content is derived from
the actual live dispatch path rather than from projection defaults.

Architecture role
-----------------
This module sits at the boundary between the canonical routing spine and the
routing explanation layer.  It is deliberately kept read-only with respect to
routing — it *observes* and *records* decisions, never *makes* them.

Collected signal categories
----------------------------
* **Posture gate** — session-truth posture eligibility result (Gate A)
* **Admissibility gate** — per-target admissibility verdicts (Gate B)
* **Capability graph** — confirmed / unconfirmed targets from the capability
  network runtime policy layer
* **Path branch** — which dispatch branch was chosen and why
  (cross_device / parallel_fanout / worker / local)
* **Policy engine** — ``apply_target_selection_policy()`` decision recorded
  as a decision-basis entry
* **Result outcome** — success/failure, error code, failure domain

Integration point
-----------------
``CommandRouter.route_envelope()`` creates a :class:`SpineDecisionCollector`
at the start of the method, feeds signals from each gate section, then calls
:func:`build_spine_explanation` once dispatch is complete to get the live
:class:`~.route_explanation.RouteExplanation`.  The explanation is attached
to the result dict under ``"routing_explanation"`` and passed to
``ReplayFoundation.record_route_decision()``.

Design rules
------------
* Never raises — all public methods are exception-safe.
* Never writes routing state — strictly observational.
* Structured and JSON-serialisable output — suitable for operator review and
  postmortem analysis.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .decision_basis import (
    DecisionFactor,
    make_decision_basis,
    basis_from_availability,
    basis_from_capability,
    basis_from_policy_posture,
    DecisionBasis,
)
from .route_explanation import (
    RejectedCandidate,
    RouteExplanation,
    build_route_explanation,
    EMPTY_ROUTE_EXPLANATION,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SpineDecisionCollector",
    "build_spine_explanation",
    "LIVE_ROUTING_EXPLANATION_WIRED",
]

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------

LIVE_ROUTING_EXPLANATION_WIRED: str = (
    "COMMAND_ROUTER::LIVE_ROUTING_EXPLANATION_V1: "
    "CommandRouter.route_envelope() now generates a live RouteExplanation "
    "via SpineDecisionCollector at core.routing_explanation.spine_explanation_builder. "
    "Explanation is attached to results under 'routing_explanation' and passed "
    "to ReplayFoundation.record_route_decision() as structured evidence."
)
"""Sentinel importable to assert that live routing explanation is wired into
``CommandRouter.route_envelope()``."""


# ---------------------------------------------------------------------------
# SpineDecisionCollector
# ---------------------------------------------------------------------------


class SpineDecisionCollector:
    """Accumulate live routing decision signals during ``route_envelope()``.

    Create one instance per dispatch call at the start of
    ``route_envelope()``, feed signals via the ``record_*`` methods as each
    gate executes, then call :func:`build_spine_explanation` with the
    collector to get the assembled :class:`~.route_explanation.RouteExplanation`.

    All ``record_*`` methods are exception-safe: they silently ignore errors so
    that a collector failure never propagates into the dispatch path.
    """

    def __init__(
        self,
        task_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        self.task_id: Optional[str] = task_id
        self.trace_id: Optional[str] = trace_id

        # Posture gate
        self._posture_applied: bool = False
        self._posture_value: Optional[str] = None
        self._posture_eligible: Optional[bool] = None

        # Admissibility gate
        self._adm_applied: bool = False
        self._adm_validated: List[str] = []
        self._adm_excluded: List[str] = []

        # Capability graph
        self._cap_applied: bool = False
        self._cap_confirmed: List[str] = []
        self._cap_unconfirmed: List[str] = []
        self._cap_required: Optional[List[str]] = None

        # Path branch
        self._branch_kind: Optional[str] = None  # "cross_device"|"fanout"|"worker"|"local"
        self._branch_reason: str = ""

        # Policy engine
        self._policy_kind: Optional[str] = None
        self._policy_reason: Optional[str] = None
        self._policy_band: Optional[str] = None
        self._policy_posture: str = "undecided"
        self._policy_candidates: List[str] = []

        # Outcome
        self._success: Optional[bool] = None
        self._error_code: Optional[str] = None
        self._failure_domain: Optional[str] = None
        self._fallback_triggered: bool = False
        self._fallback_reason: Optional[str] = None

        # Selected primary target (resolved after all gates)
        self._selected_target: Optional[str] = None
        self._original_targets: List[str] = []

    # ------------------------------------------------------------------
    # Feed methods
    # ------------------------------------------------------------------

    def record_initial_targets(self, targets: List[str]) -> None:
        """Record the initial targets before any gate processing."""
        try:
            self._original_targets = list(targets)
            if targets:
                self._selected_target = targets[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("SpineDecisionCollector.record_initial_targets skipped: %s", exc)

    def record_posture_gate(
        self,
        posture: str,
        eligible: bool,
        *,
        reason: str = "",
    ) -> None:
        """Record the Gate A (posture-aware session-truth) result."""
        try:
            self._posture_applied = True
            self._posture_value = posture
            self._posture_eligible = eligible
            if not self._policy_posture or self._policy_posture == "undecided":
                self._policy_posture = posture
            if reason:
                self._policy_reason = reason
        except Exception as exc:  # noqa: BLE001
            logger.debug("SpineDecisionCollector.record_posture_gate skipped: %s", exc)

    def record_admissibility(
        self,
        validated: List[str],
        excluded: List[str],
    ) -> None:
        """Record Gate B (admissibility chain) results."""
        try:
            self._adm_applied = True
            self._adm_validated = list(validated)
            self._adm_excluded = list(excluded)
            if validated:
                self._selected_target = validated[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("SpineDecisionCollector.record_admissibility skipped: %s", exc)

    def record_capability_check(
        self,
        confirmed: List[str],
        unconfirmed: List[str],
        required_caps: Optional[List[str]] = None,
    ) -> None:
        """Record capability-graph enforcement results."""
        try:
            self._cap_applied = True
            self._cap_confirmed = list(confirmed)
            self._cap_unconfirmed = list(unconfirmed)
            self._cap_required = list(required_caps) if required_caps else None
            if confirmed:
                self._selected_target = confirmed[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("SpineDecisionCollector.record_capability_check skipped: %s", exc)

    def record_path_branch(
        self,
        branch_kind: str,
        reason: str = "",
    ) -> None:
        """Record which dispatch branch was chosen.

        Args:
            branch_kind: One of ``"cross_device"``, ``"fanout"``,
                ``"worker"``, ``"local"``.
            reason: Human-readable reason for the branch choice.
        """
        try:
            self._branch_kind = branch_kind
            self._branch_reason = reason
        except Exception as exc:  # noqa: BLE001
            logger.debug("SpineDecisionCollector.record_path_branch skipped: %s", exc)

    def record_policy_engine_decision(
        self,
        policy_kind: Optional[str],
        decision_reason: Optional[str],
        policy_band: Optional[str] = None,
        policy_posture: Optional[str] = None,
        candidates: Optional[List[str]] = None,
    ) -> None:
        """Record the execution-target policy engine decision."""
        try:
            self._policy_kind = policy_kind
            self._policy_reason = decision_reason
            if policy_band:
                self._policy_band = policy_band
            if policy_posture and (not self._policy_posture or self._policy_posture == "undecided"):
                self._policy_posture = policy_posture
            if candidates:
                self._policy_candidates = list(candidates)
        except Exception as exc:  # noqa: BLE001
            logger.debug("SpineDecisionCollector.record_policy_engine_decision skipped: %s", exc)

    def record_result(
        self,
        success: bool,
        error_code: Optional[str] = None,
        failure_domain: Optional[str] = None,
        selected_target: Optional[str] = None,
    ) -> None:
        """Record the dispatch outcome."""
        try:
            self._success = success
            self._error_code = error_code
            self._failure_domain = failure_domain
            if selected_target:
                self._selected_target = selected_target
        except Exception as exc:  # noqa: BLE001
            logger.debug("SpineDecisionCollector.record_result skipped: %s", exc)

    def record_fallback(
        self,
        triggered: bool,
        reason: Optional[str] = None,
    ) -> None:
        """Record whether fallback was triggered and why."""
        try:
            self._fallback_triggered = triggered
            self._fallback_reason = reason
        except Exception as exc:  # noqa: BLE001
            logger.debug("SpineDecisionCollector.record_fallback skipped: %s", exc)

    # ------------------------------------------------------------------
    # Public read-only properties for external access
    # ------------------------------------------------------------------

    @property
    def branch_kind(self) -> Optional[str]:
        """The dispatch branch chosen (``"cross_device"``, ``"fanout"``,
        ``"worker"``, or ``"local"``). ``None`` if not yet recorded."""
        return self._branch_kind

    @property
    def adm_validated(self) -> List[str]:
        """Targets that passed the admissibility gate."""
        return list(self._adm_validated)

    @property
    def adm_excluded(self) -> List[str]:
        """Targets that were excluded by the admissibility gate."""
        return list(self._adm_excluded)

    @property
    def cap_confirmed(self) -> List[str]:
        """Targets confirmed in the capability graph."""
        return list(self._cap_confirmed)

    @property
    def fallback_triggered(self) -> bool:
        """Whether a fallback path was triggered during this dispatch."""
        return self._fallback_triggered


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_spine_explanation(
    collector: SpineDecisionCollector,
    *,
    owner_component: str = "command_router.route_envelope",
) -> RouteExplanation:
    """Assemble a live :class:`~.route_explanation.RouteExplanation` from
    signals accumulated in *collector*.

    This function reads only from the collector — it never calls into
    routing modules or modifies any routing state.

    Args:
        collector:       Populated :class:`SpineDecisionCollector` instance.
        owner_component: Component label for traceability (default:
                         ``"command_router.route_envelope"``).

    Returns:
        A frozen :class:`~.route_explanation.RouteExplanation`.  Never raises.
    """
    try:
        return _build_impl(collector, owner_component)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "build_spine_explanation: explanation assembly failed — "
            "returning EMPTY_ROUTE_EXPLANATION (task_id=%s): %s",
            collector.task_id,
            exc,
        )
        return EMPTY_ROUTE_EXPLANATION


def _build_impl(
    c: SpineDecisionCollector,
    owner_component: str,
) -> RouteExplanation:
    bases: List[DecisionBasis] = []
    rejected: List[RejectedCandidate] = []

    # ------------------------------------------------------------------
    # 1. Path branch — why this dispatch path was selected
    # ------------------------------------------------------------------
    branch = c._branch_kind or "local"
    branch_desc = _branch_description(branch, c._branch_reason)
    bases.append(
        make_decision_basis(
            factor=DecisionFactor.POLICY,
            signal_value=branch,
            description=branch_desc,
            accepted=True,
            weight=0.30,
        )
    )

    # ------------------------------------------------------------------
    # 2. Posture gate — session-truth eligibility
    # ------------------------------------------------------------------
    if c._posture_applied and c._posture_value is not None:
        eligible = c._posture_eligible if c._posture_eligible is not None else True
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.POLICY,
                signal_value=c._posture_value,
                description=(
                    f"Session-truth posture '{c._posture_value}': "
                    f"source eligible={eligible} for this dispatch path"
                ),
                accepted=eligible,
                weight=0.15,
            )
        )

    # ------------------------------------------------------------------
    # 3. Admissibility gate — per-target readiness / participation checks
    # ------------------------------------------------------------------
    if c._adm_applied:
        if c._adm_validated:
            bases.append(
                make_decision_basis(
                    factor=DecisionFactor.AVAILABILITY,
                    signal_value=c._adm_validated,
                    description=(
                        f"Admissibility gate: {len(c._adm_validated)} target(s) "
                        f"passed readiness/participation checks: {c._adm_validated}"
                    ),
                    accepted=True,
                    weight=0.20,
                )
            )
        for excl_id in c._adm_excluded:
            rejected.append(
                RejectedCandidate(
                    candidate_id=excl_id,
                    rejection_reason=(
                        "Failed admissibility gate: readiness or participation "
                        "check returned not-ready"
                    ),
                    was_available=False,
                )
            )
        if c._adm_excluded and not c._adm_validated:
            # All targets failed — note graceful degradation
            bases.append(
                make_decision_basis(
                    factor=DecisionFactor.AVAILABILITY,
                    signal_value=False,
                    description=(
                        f"All {len(c._adm_excluded)} target(s) failed admissibility; "
                        "proceeding with original targets (graceful degradation)"
                    ),
                    accepted=False,
                    weight=0.15,
                )
            )

    # ------------------------------------------------------------------
    # 4. Capability graph — confirmed / unconfirmed targets
    # ------------------------------------------------------------------
    if c._cap_applied:
        caps_desc = (
            f"required_capabilities={c._cap_required}" if c._cap_required else "no capabilities filter"
        )
        if c._cap_confirmed:
            bases.append(
                make_decision_basis(
                    factor=DecisionFactor.CAPABILITY,
                    signal_value=c._cap_confirmed,
                    description=(
                        f"Capability graph confirmed {len(c._cap_confirmed)} target(s) "
                        f"({caps_desc}): {c._cap_confirmed}"
                    ),
                    accepted=True,
                    weight=0.15,
                )
            )
        for uncf_id in c._cap_unconfirmed:
            rejected.append(
                RejectedCandidate(
                    candidate_id=uncf_id,
                    rejection_reason=(
                        f"Not confirmed in capability graph for {caps_desc}; "
                        "filtered to capability-confirmed targets"
                    ),
                    capability_match=False,
                )
            )

    # ------------------------------------------------------------------
    # 5. Policy engine — execution-target selection policy
    # ------------------------------------------------------------------
    if c._policy_kind is not None:
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.POLICY,
                signal_value=c._policy_kind,
                description=(
                    f"Execution-target policy engine: policy_kind='{c._policy_kind}'"
                    + (
                        f", reason='{c._policy_reason}'"
                        if c._policy_reason
                        else ""
                    )
                ),
                accepted=True,
                weight=0.10,
            )
        )

    # ------------------------------------------------------------------
    # 6. Fallback
    # ------------------------------------------------------------------
    fallback_plan: Optional[str] = None
    if c._fallback_triggered:
        fallback_plan = c._fallback_reason or "fallback path engaged"
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.FALLBACK,
                signal_value=True,
                description=fallback_plan,
                accepted=True,
                weight=0.05,
            )
        )

    # ------------------------------------------------------------------
    # 7. Outcome — success/failure
    # ------------------------------------------------------------------
    if c._success is not None and not c._success:
        _err = c._error_code or "unknown_error"
        _domain = c._failure_domain or ""
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.AVAILABILITY,
                signal_value=False,
                description=(
                    f"Dispatch outcome: failed (error_code={_err!r}"
                    + (f", domain={_domain!r}" if _domain else "")
                    + ")"
                ),
                accepted=False,
                weight=0.05,
            )
        )

    # ------------------------------------------------------------------
    # Resolve policy metadata
    # ------------------------------------------------------------------
    posture = c._policy_posture or "undecided"
    # Infer cross-device posture from branch kind when no explicit posture
    # gate was applied — this ensures is_cross_device is correctly computed
    # in the downstream RoutingExplanationSummary.
    if posture == "undecided" and c._branch_kind == "cross_device":
        posture = "remote_required"
    policy_reason = c._policy_reason or _default_policy_reason(branch)
    policy_band = c._policy_band

    return build_route_explanation(
        selected_target=c._selected_target,
        decision_bases=bases,
        rejected_candidates=rejected,
        policy_posture=posture,
        policy_reason=policy_reason,
        policy_band=policy_band,
        fallback_plan=fallback_plan,
        owner_agent=None,
        owner_component=owner_component,
        task_id=c.task_id,
        trace_id=c.trace_id,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _branch_description(branch: str, reason: str) -> str:
    """Return a human-readable description for a dispatch branch choice."""
    labels: Dict[str, str] = {
        "cross_device": (
            "Route selected cross-device dispatch path "
            "(envelope has cross_device=true or executor_target_type=android_device/node_service)"
        ),
        "fanout": (
            "Route selected parallel fanout dispatch path "
            "(envelope has parallel_fanout=true)"
        ),
        "worker": (
            "Route selected worker/MasterBrain dispatch path "
            "(executor_target_type=go_worker)"
        ),
        "local": (
            "Route selected local execution path "
            "(no cross-device, fanout, or worker signals)"
        ),
    }
    base = labels.get(branch, f"Route selected dispatch path: '{branch}'")
    return (base + f"; {reason}") if reason else base


def _default_policy_reason(branch: str) -> str:
    """Return a default policy reason string for a branch when no engine reason is available."""
    reasons: Dict[str, str] = {
        "cross_device": "cross-device metadata or explicit executor_target_type directed cross-device dispatch",
        "fanout": "parallel_fanout metadata directed multi-target fanout dispatch",
        "worker": "explicit executor_target_type=go_worker directed worker dispatch",
        "local": "no cross-device, fanout, or worker signals — local execution selected",
    }
    return reasons.get(branch, "routing decision recorded by canonical spine")
