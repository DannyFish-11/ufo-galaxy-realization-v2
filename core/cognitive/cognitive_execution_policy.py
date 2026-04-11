#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cognitive.cognitive_execution_policy
==========================================

PR-18 — Cognitive Execution-Policy Wiring

Canonical cognitive execution-policy mapping layer.  Derives bounded
execution-policy hints from **already-live** runtime cognition signals and
makes those hints available to the canonical execution-policy path in
:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime` and
:class:`~core.openclawd.OpenClawd`.

Design principles
-----------------
- **Consumes, does not re-compute**: All cognitive signals are read from the
  existing :class:`~core.cognitive.continuous_state.CognitiveState`,
  :class:`~core.cognitive.state_interpreter.StateInterpreter`, and
  :class:`~core.continuum.types.ContinuumState` instances.  This module
  never starts a second cognitive pipeline.
- **Hints, not commands**: The produced :class:`CognitiveExecutionHint` is a
  bounded, policy-oriented *hint* -- it biases execution preferences rather
  than replacing core authority figures
  (``DesktopPresenceRuntime``, ``OpenClawd``, ``AgentKernel``).
- **Additive**: All consumers fall back gracefully when hints are unavailable.

Cognitive region to execution-hint mapping
------------------------------------------
PASSIVE   -> execution_path_pref=deferred, planning_intensity=minimal,
             activation_budget=0.2, delegation_bias=prefer_deferred
LIMINAL   -> execution_path_pref=planning, planning_intensity=heavy,
             activation_budget=0.6, delegation_bias=prefer_planning
MANIFEST  -> execution_path_pref=direct, planning_intensity=standard,
             activation_budget=1.0, delegation_bias=prefer_local

Authority sentinels
-------------------
COGNITIVE_EXECUTION_POLICY_IS_AUTHORITY
    Asserts this module is the canonical cognitive execution-policy mapping
    authority.  Imported by projection.py to register the PR-18 alignment.

COGNITIVE_EXECUTION_POLICY_PR18_SENTINEL
    Machine-checkable sentinel confirming PR-18 cognitive wiring is present.

Usage::

    from core.cognitive.cognitive_execution_policy import (
        derive_cognitive_execution_hint,
        CognitiveExecutionHint,
    )

    hint = derive_cognitive_execution_hint()
    print(hint.execution_path_preference)  # "direct" | "planning" | "deferred"
    print(hint.activation_budget)          # float 0.0-1.0
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Cognitive.ExecutionPolicy")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

COGNITIVE_EXECUTION_POLICY_IS_AUTHORITY: str = (
    "COGNITIVE_EXECUTION_POLICY::CANONICAL_AUTHORITY: "
    "core.cognitive.cognitive_execution_policy is the canonical cognitive "
    "execution-policy mapping layer (PR-18).  It derives bounded execution "
    "hints from live cognitive signals without replacing DesktopPresenceRuntime, "
    "OpenClawd, or AgentKernel."
)

COGNITIVE_EXECUTION_POLICY_PR18_SENTINEL: str = (
    "COGNITIVE_EXECUTION_POLICY::PR18_SENTINEL: "
    "Cognitive execution-policy wiring (PR-18) is present and active.  "
    "CognitiveRegion signals from StateInterpreter and ContinuumOrchestrator "
    "are now mapped to bounded execution-policy hints and fed into the "
    "canonical runtime dispatch flow."
)

# Policy sentinels
COGNITIVE_STATE_DRIVES_EXECUTION_HINT_POLICY: str = (
    "COGNITIVE_EXECUTION_POLICY::POLICY_1: "
    "CognitiveRegion (PASSIVE/LIMINAL/MANIFEST) is the primary driver of the "
    "cognitive execution hint.  Continuum signals refine the hint but do not "
    "override the region-level classification."
)

COGNITIVE_HINT_IS_ADVISORY_NOT_MANDATORY_POLICY: str = (
    "COGNITIVE_EXECUTION_POLICY::POLICY_2: "
    "CognitiveExecutionHint is advisory only.  Consumers MUST handle the case "
    "where no hint is available and fall back to their own defaults.  The hint "
    "never replaces DesktopPresenceRuntime or OpenClawd authority."
)

COGNITIVE_HINT_CONSUMES_EXISTING_SIGNALS_POLICY: str = (
    "COGNITIVE_EXECUTION_POLICY::POLICY_3: "
    "derive_cognitive_execution_hint() reads from the process-wide "
    "CognitiveState and StateInterpreter singletons.  It does NOT start a new "
    "cognitive pipeline or a second ContinuumOrchestrator tick."
)

ACTIVATION_BUDGET_IS_NORMALIZED_POLICY: str = (
    "COGNITIVE_EXECUTION_POLICY::POLICY_4: "
    "activation_budget is a normalized float in [0.0, 1.0].  It represents "
    "the cognitive intensity budget available for node activation.  It is "
    "distinct from NodeActivationContext eligibility (PR-14 node track)."
)


# ---------------------------------------------------------------------------
# Enums / constants
# ---------------------------------------------------------------------------

# execution_path_preference values
EXEC_PATH_PREF_DIRECT: str = "direct"
EXEC_PATH_PREF_PLANNING: str = "planning"
EXEC_PATH_PREF_DEFERRED: str = "deferred"

# delegation_bias values
DELEGATION_BIAS_PREFER_LOCAL: str = "prefer_local"
DELEGATION_BIAS_PREFER_PLANNING: str = "prefer_planning"
DELEGATION_BIAS_PREFER_DEFERRED: str = "prefer_deferred"

# planning_intensity values
PLANNING_INTENSITY_STANDARD: str = "standard"
PLANNING_INTENSITY_HEAVY: str = "heavy"
PLANNING_INTENSITY_MINIMAL: str = "minimal"


# ---------------------------------------------------------------------------
# CognitiveExecutionHint dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CognitiveExecutionHint:
    """Bounded, advisory execution-policy hint derived from live cognitive state.

    This dataclass is the canonical output of
    :func:`derive_cognitive_execution_hint`.  All fields have safe defaults;
    consumers must never assume a field is non-None.

    Attributes
    ----------
    cognitive_region:
        The :class:`~core.cognitive.state_interpreter.CognitiveRegion` string
        value that produced this hint (``"silent"`` / ``"liminal"`` /
        ``"manifest"``).
    execution_path_preference:
        Preferred execution path bias derived from cognitive region:

        - ``"direct"``    — manifest state; prefer lower-latency, direct
                            execution on the local device.
        - ``"planning"``  — liminal state; prefer heavier planning / intent
                            resolution before committing.
        - ``"deferred"``  — passive state; prefer deferred / lower-cost
                            execution.  Avoid triggering side-effectful
                            actions until the system becomes more active.
    delegation_bias:
        Delegation preference hint:

        - ``"prefer_local"``     — manifest; execute locally first.
        - ``"prefer_planning"``  — liminal; spend time planning.
        - ``"prefer_deferred"``  — passive; defer or return early.
    planning_intensity:
        Suggested planning intensity:

        - ``"standard"`` — manifest; normal planning depth.
        - ``"heavy"``    — liminal; expand planning breadth and depth.
        - ``"minimal"``  — passive; minimal planning overhead.
    activation_budget:
        Normalised float [0.0, 1.0] indicating the cognitive intensity
        budget available for node activation.  1.0 = full budget; 0.0 =
        no activation budget (passive/silent state).

        This is **distinct** from NodeActivationContext eligibility
        (PR-14 node track).  It is a *hint* for budget awareness, not an
        eligibility gate.
    manifest_score:
        Continuous manifest score [0.0, 1.0] from the cognitive field engine.
        Useful for fine-grained policy tuning beyond the discrete regions.
    arousal:
        Cognitive arousal / activation level [0.0, 1.0] from the live state.
    uncertainty:
        Current epistemic uncertainty [0.0, 1.0].  High uncertainty may
        suggest more conservative execution.
    cognitive_wiring_active:
        Always ``True`` when returned by :func:`derive_cognitive_execution_hint`.
        Consumers can check this field to confirm the hint was produced by
        the cognitive wiring layer (as opposed to a fallback).
    source:
        ``"cognitive_execution_policy"`` when derived from live signals;
        ``"fallback"`` when the signals were unavailable.
    timestamp:
        Unix epoch at hint derivation time.
    """

    cognitive_region: str = "silent"
    execution_path_preference: str = EXEC_PATH_PREF_DEFERRED
    delegation_bias: str = DELEGATION_BIAS_PREFER_DEFERRED
    planning_intensity: str = PLANNING_INTENSITY_MINIMAL
    activation_budget: float = 0.2
    manifest_score: float = 0.0
    arousal: float = 0.0
    uncertainty: float = 0.5
    cognitive_wiring_active: bool = True
    source: str = "cognitive_execution_policy"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation of this hint."""
        return {
            "cognitive_region": self.cognitive_region,
            "execution_path_preference": self.execution_path_preference,
            "delegation_bias": self.delegation_bias,
            "planning_intensity": self.planning_intensity,
            "activation_budget": round(self.activation_budget, 4),
            "manifest_score": round(self.manifest_score, 4),
            "arousal": round(self.arousal, 4),
            "uncertainty": round(self.uncertainty, 4),
            "cognitive_wiring_active": self.cognitive_wiring_active,
            "source": self.source,
            "timestamp": self.timestamp,
        }

    def is_manifest(self) -> bool:
        """Return True when the cognitive region is manifest."""
        return self.cognitive_region == "manifest"

    def is_liminal(self) -> bool:
        """Return True when the cognitive region is liminal."""
        return self.cognitive_region == "liminal"

    def is_passive(self) -> bool:
        """Return True when the cognitive region is passive / silent."""
        return self.cognitive_region in ("silent", "passive")


# ---------------------------------------------------------------------------
# Fallback hint (safe default when signals are unavailable)
# ---------------------------------------------------------------------------

FALLBACK_COGNITIVE_HINT: CognitiveExecutionHint = CognitiveExecutionHint(
    cognitive_region="silent",
    execution_path_preference=EXEC_PATH_PREF_DEFERRED,
    delegation_bias=DELEGATION_BIAS_PREFER_DEFERRED,
    planning_intensity=PLANNING_INTENSITY_MINIMAL,
    activation_budget=0.2,
    manifest_score=0.0,
    arousal=0.0,
    uncertainty=0.5,
    cognitive_wiring_active=False,
    source="fallback",
)


# ---------------------------------------------------------------------------
# Region-to-hint mapping tables
# ---------------------------------------------------------------------------

# Maps CognitiveRegion string value -> (exec_path_pref, delegation_bias, planning_intensity)
_REGION_HINT_MAP: Dict[str, tuple] = {
    "silent":   (EXEC_PATH_PREF_DEFERRED,  DELEGATION_BIAS_PREFER_DEFERRED,  PLANNING_INTENSITY_MINIMAL),
    "passive":  (EXEC_PATH_PREF_DEFERRED,  DELEGATION_BIAS_PREFER_DEFERRED,  PLANNING_INTENSITY_MINIMAL),
    "liminal":  (EXEC_PATH_PREF_PLANNING,  DELEGATION_BIAS_PREFER_PLANNING,  PLANNING_INTENSITY_HEAVY),
    "manifest": (EXEC_PATH_PREF_DIRECT,    DELEGATION_BIAS_PREFER_LOCAL,     PLANNING_INTENSITY_STANDARD),
}

# Maps CognitiveRegion string value -> base activation_budget
_REGION_ACTIVATION_BUDGET: Dict[str, float] = {
    "silent":   0.2,
    "passive":  0.2,
    "liminal":  0.6,
    "manifest": 1.0,
}


# ---------------------------------------------------------------------------
# Core derivation function
# ---------------------------------------------------------------------------


def derive_cognitive_execution_hint(
    *,
    cognitive_state: Optional[Any] = None,
    continuum_state: Optional[Any] = None,
    trace_id: Optional[str] = None,
) -> CognitiveExecutionHint:
    """Derive a :class:`CognitiveExecutionHint` from live cognitive signals.

    This function **reads** from the already-live
    :class:`~core.cognitive.continuous_state.CognitiveState` and
    :class:`~core.cognitive.state_interpreter.StateInterpreter` singletons.
    It does not start a new cognitive pipeline.

    Parameters
    ----------
    cognitive_state:
        Optional :class:`~core.cognitive.continuous_state.CognitiveState`
        override.  When ``None``, the process-wide singleton is used.
    continuum_state:
        Optional :class:`~core.continuum.types.ContinuumState` snapshot for
        additional signal enrichment (presence_intensity, coherence,
        action_level).  When ``None``, a best-effort attempt is made to
        obtain the last known continuum state; if unavailable the base
        region mapping is used without refinement.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    CognitiveExecutionHint
        A bounded, advisory hint derived from live cognitive signals.
        Never raises — returns :data:`FALLBACK_COGNITIVE_HINT` on any error.
    """
    try:
        return _derive_hint_impl(
            cognitive_state=cognitive_state,
            continuum_state=continuum_state,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.debug(
            "derive_cognitive_execution_hint: error deriving hint (trace_id=%s): %s — returning fallback",
            trace_id,
            exc,
        )
        return FALLBACK_COGNITIVE_HINT


def _derive_hint_impl(
    *,
    cognitive_state: Optional[Any],
    continuum_state: Optional[Any],
    trace_id: Optional[str],
) -> CognitiveExecutionHint:
    """Internal implementation of hint derivation."""

    # ------------------------------------------------------------------
    # 1. Obtain the interpreted cognitive region from StateInterpreter
    # ------------------------------------------------------------------
    from core.cognitive.state_interpreter import get_state_interpreter

    interp = get_state_interpreter()
    interpreted: Any = interp.interpret(state=cognitive_state)

    region_str: str = interpreted.region.value  # e.g. "silent" / "liminal" / "manifest"
    manifest_score: float = float(interpreted.score)
    arousal: float = float(interpreted.activation)
    uncertainty: float = float(interpreted.uncertainty)

    # ------------------------------------------------------------------
    # 2. Base hint from region mapping table
    # ------------------------------------------------------------------
    exec_path_pref, delegation_bias, planning_intensity = _REGION_HINT_MAP.get(
        region_str, _REGION_HINT_MAP["silent"]
    )
    base_budget: float = _REGION_ACTIVATION_BUDGET.get(region_str, 0.2)

    # ------------------------------------------------------------------
    # 3. Refine activation_budget using continuum signals (if available)
    # ------------------------------------------------------------------
    activation_budget = base_budget
    _continuum_refined = False

    if continuum_state is not None:
        activation_budget = _refine_budget_from_continuum(
            base_budget=base_budget,
            continuum_state=continuum_state,
            region_str=region_str,
        )
        _continuum_refined = True
    else:
        # Best-effort: try to obtain continuum signals from the manifest_score
        # and arousal already extracted above.
        activation_budget = _refine_budget_from_field(
            base_budget=base_budget,
            manifest_score=manifest_score,
            arousal=arousal,
            uncertainty=uncertainty,
        )

    logger.debug(
        "CognitiveExecutionPolicy: region=%s score=%.3f arousal=%.3f "
        "unc=%.3f budget=%.3f exec_pref=%s continuum_refined=%s trace_id=%s",
        region_str,
        manifest_score,
        arousal,
        uncertainty,
        activation_budget,
        exec_path_pref,
        _continuum_refined,
        trace_id,
    )

    return CognitiveExecutionHint(
        cognitive_region=region_str,
        execution_path_preference=exec_path_pref,
        delegation_bias=delegation_bias,
        planning_intensity=planning_intensity,
        activation_budget=round(activation_budget, 4),
        manifest_score=round(manifest_score, 4),
        arousal=round(arousal, 4),
        uncertainty=round(uncertainty, 4),
        cognitive_wiring_active=True,
        source="cognitive_execution_policy",
    )


# ---------------------------------------------------------------------------
# Refinement helpers
# ---------------------------------------------------------------------------


def _refine_budget_from_continuum(
    *,
    base_budget: float,
    continuum_state: Any,
    region_str: str,
) -> float:
    """Refine activation_budget using ContinuumState signals.

    Reads ``presence_intensity``, ``coherence``, and ``decision.action_level``
    from the continuum state.  These signals are blended with the base
    region budget to produce a continuous, smooth budget value.
    """
    try:
        presence_intensity = float(getattr(continuum_state, "presence_intensity", base_budget))
        coherence = float(getattr(continuum_state, "coherence", 0.5))

        # action_level hint from decision gate (observe/hint/assist/act)
        action_level_boost = 0.0
        decision = getattr(continuum_state, "decision", None)
        if decision is not None:
            al = getattr(decision, "action_level", None)
            al_str = al.value if hasattr(al, "value") else str(al or "")
            if al_str == "act":
                action_level_boost = 0.15
            elif al_str == "assist":
                action_level_boost = 0.08

        # Blend: 60% presence_intensity + 40% base_budget + coherence bonus
        blended = (presence_intensity * 0.6 + base_budget * 0.4)
        # Coherence above 0.7 provides a small boost; below 0.3 slightly restricts.
        coherence_adj = (coherence - 0.5) * 0.1
        refined = min(1.0, max(0.0, blended + coherence_adj + action_level_boost))
        return refined
    except Exception as exc:
        logger.debug("_refine_budget_from_continuum: error: %s", exc)
        return base_budget


def _refine_budget_from_field(
    *,
    base_budget: float,
    manifest_score: float,
    arousal: float,
    uncertainty: float,
) -> float:
    """Refine activation_budget using the cognitive field values directly.

    This is the fallback when no ContinuumState is available.  Blends the
    manifest_score and arousal to produce a budget close to the base.
    """
    try:
        blended = (manifest_score * 0.5 + arousal * 0.3 + base_budget * 0.2)
        # High uncertainty slightly restricts.
        unc_adj = -(uncertainty - 0.5) * 0.10
        refined = min(1.0, max(0.0, blended + unc_adj))
        return refined
    except Exception as exc:
        logger.debug("_refine_budget_from_field: error: %s", exc)
        return base_budget


# ---------------------------------------------------------------------------
# Convenience: build hint dict for embedding in response metadata
# ---------------------------------------------------------------------------


def build_cognitive_hint_metadata(
    hint: Optional[CognitiveExecutionHint],
    *,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a metadata-safe dict from a :class:`CognitiveExecutionHint`.

    Returns a minimal, JSON-safe dict suitable for embedding in response
    metadata, projection payloads, or observability logs.

    Parameters
    ----------
    hint:
        A :class:`CognitiveExecutionHint` or ``None``.
    trace_id:
        Optional correlation ID added to the dict.

    Returns
    -------
    dict
        Always returns a dict; never raises.
    """
    try:
        if hint is None:
            return {
                "cognitive_wiring_active": False,
                "source": "unavailable",
                "hint_authority": "advisory_only",
                "execution_path_preference_binding": "advisory_only_non_binding",
                "influences_execution_path_routing": False,
            }
        d = hint.to_dict()
        d.setdefault("hint_authority", "advisory_only")
        d.setdefault("execution_path_preference_binding", "advisory_only_non_binding")
        d.setdefault("influences_execution_path_routing", False)
        if trace_id:
            d["trace_id"] = trace_id
        return d
    except Exception as exc:
        logger.debug("build_cognitive_hint_metadata: error: %s", exc)
        return {"cognitive_wiring_active": False, "source": "error", "error": str(exc)}
