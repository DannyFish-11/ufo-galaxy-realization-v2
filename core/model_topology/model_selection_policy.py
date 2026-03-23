#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/model_topology/model_selection_policy.py
=============================================
Explicit Model Selection Policy Engine for OpenClawd.

**Unified-Control Architecture — Model Selection Policy (PR-25)**
-----------------------------------------------------------------
``ModelSelectionPolicyEngine`` is the canonical, explicit policy layer that
OpenClawd invokes to derive a model-selection decision from canonical supply
state and per-request perception/policy inputs.  It answers — in a single,
structured, and diagnosable output — questions such as:

* When should one model be selected over another?
* How should native multimodal capability be weighted against cost, latency,
  quality, and availability?
* How should support / auxiliary models be considered?
* How should fallback candidates be ranked?
* How should partial multimodal support compare with full multimodal support?

Architecture
------------

.. code-block:: text

    CanonicalModelSupplyState (PR-18)   ← supply truth (not duplicated here)
         │
    ModelSelectionPolicy                ← per-request policy inputs & constraints
         │
    ModelSelectionPolicyEngine.evaluate()
         │
    ModelSelectionDecision              ← structured, explainable selection output
         │
    OpenClawd                           ← final authority; embeds decision in
         │                                 UnifiedControlPlan (PR-19)
    UnifiedControlPlan["model_selection_decision"]

Design goals
------------
- Make model selection an **explicit, canonical policy concern** inside the
  control core, not an emergent effect of scattered heuristics.
- **OpenClawd remains final authority**: the engine is invoked by the control
  core and its result is embedded in the canonical control artifact.
- **Native multimodal is a first-class policy dimension**: it is not a side
  flag or incidental preference but a top-priority selection criterion.
- **Policy output is explainable**: :class:`ModelSelectionDecision` carries
  structured :class:`SelectionReason` records, not just final provider names.
- **Do not duplicate supply truth**: the engine reads
  :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`
  dicts rather than re-implementing capability logic.
- **Backward compatible**: text-only and legacy paths continue to work;
  selection degrades gracefully when supply state is unavailable.

Ranking algorithm
-----------------
The engine evaluates each available provider against the policy and assigns a
numeric score.  Higher score = higher preference.  Scoring tiers (in descending
priority):

1. **Native multimodal match** (if required_modalities is non-empty and
   ``prefer_native_multimodal=True``): +40 pts if the provider is natively
   multimodal and required modalities overlap with provider capabilities.
2. **Partial multimodal match** (``allow_partial_multimodal=True``): +20 pts
   when the provider supports at least one required modality but not all.
3. **Health bonus**: HEALTHY → +10 pts, DEGRADED → +2 pts, DOWN → disqualified.
4. **Locality match**: +5 pts when ``preferred_locality`` matches provider
   locality class.
5. **Cost tier**: ``low`` prefers providers with lower cost_per_1k_input;
   ``high`` prefers providers with higher cost (proxy for quality).
   ±3 pts relative adjustment within the ranked set.
6. **Latency budget**: providers with ``latency_avg_ms > latency_budget_ms``
   (when specified) are penalised −5 pts.
7. **Auxiliary eligibility**: support-model candidates receive a +2 pts
   auxiliary bonus so they are ranked before non-support fallbacks.

The **winning provider** is the highest-scoring candidate that is not DOWN.
If multiple providers tie, the one that appears first in ``available_provider_ids``
(deterministic order from the supply state) wins.

Fallback chain
--------------
All evaluated providers are sorted by score.  The fallback chain is the
ordered list of provider IDs after the winner, from best to worst.

Usage::

    from core.model_topology.model_selection_policy import (
        ModelSelectionPolicy,
        ModelSelectionPolicyEngine,
        ModelSelectionDecision,
    )

    policy = ModelSelectionPolicy(
        required_modalities=["image"],
        prefer_native_multimodal=True,
        allow_partial_multimodal=True,
        latency_budget_ms=3000,
        cost_tier="low",
    )
    engine = ModelSelectionPolicyEngine()
    decision = engine.evaluate(policy, canonical_supply_dict)
    print(decision.to_dict())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ModelTopology.ModelSelectionPolicy")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SelectionDimension(str, Enum):
    """Policy dimensions evaluated by the engine for each provider.

    Each dimension corresponds to one scoring criterion.  A
    :class:`SelectionReason` references the dimensions that influenced the
    final decision.
    """

    #: Native multimodal capability matched the required modalities.
    NATIVE_MULTIMODAL_MATCH = "native_multimodal_match"
    #: Partial multimodal capability (subset of required modalities supported).
    PARTIAL_MULTIMODAL_MATCH = "partial_multimodal_match"
    #: No multimodal capability; text-only provider selected.
    TEXT_ONLY_FALLBACK = "text_only_fallback"
    #: Provider health status influenced the decision.
    HEALTH_STATUS = "health_status"
    #: Provider locality class matched the policy preference.
    LOCALITY_MATCH = "locality_match"
    #: Cost tier influenced the provider ranking.
    COST_TIER = "cost_tier"
    #: Latency budget influenced the provider ranking.
    LATENCY_BUDGET = "latency_budget"
    #: Provider is a support/auxiliary model candidate.
    AUXILIARY_ELIGIBLE = "auxiliary_eligible"
    #: Provider was the only available option.
    ONLY_AVAILABLE = "only_available"
    #: No provider was available; fallback to advisory/no-op.
    NO_PROVIDER_AVAILABLE = "no_provider_available"
    #: Policy input was missing or invalid; selection degraded.
    SUPPLY_UNAVAILABLE = "supply_unavailable"


class SelectionReasonCode(str, Enum):
    """Machine-readable reason code attached to a :class:`SelectionReason`.

    Stable string values safe for serialisation and programmatic consumption.
    """

    #: Provider selected because it has the best native multimodal capability.
    NATIVE_MULTIMODAL_PREFERRED = "native_multimodal_preferred"
    #: Provider selected because it has partial multimodal support (best available).
    PARTIAL_MULTIMODAL_BEST_AVAILABLE = "partial_multimodal_best_available"
    #: Provider selected via text-only path (no multimodal requirement).
    TEXT_ONLY_SELECTED = "text_only_selected"
    #: Provider health was the tie-breaking dimension.
    HEALTH_TIEBREAK = "health_tiebreak"
    #: Provider locality matched the preferred deployment target.
    LOCALITY_PREFERRED = "locality_preferred"
    #: Provider selected due to cost-tier policy alignment.
    COST_ALIGNED = "cost_aligned"
    #: Provider penalised or demoted due to latency exceeding budget.
    LATENCY_OVER_BUDGET = "latency_over_budget"
    #: Provider is the only available option (no ranking applied).
    SOLE_CANDIDATE = "sole_candidate"
    #: All providers unavailable; advisory/no-op result returned.
    NO_CANDIDATES = "no_candidates"
    #: Canonical supply state was unavailable; degraded to no-selection.
    SUPPLY_STATE_UNAVAILABLE = "supply_state_unavailable"
    #: Provider is a designated support/auxiliary model candidate.
    AUXILIARY_CANDIDATE = "auxiliary_candidate"
    #: Fallback provider selected because preferred provider was unavailable.
    FALLBACK_SELECTED = "fallback_selected"


# ---------------------------------------------------------------------------
# SelectionReason — one structured reason entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionReason:
    """One structured reason entry in a :class:`ModelSelectionDecision`.

    Attributes
    ----------
    code:
        Machine-readable :class:`SelectionReasonCode` value.
    dimension:
        The :class:`SelectionDimension` that this reason belongs to.
    detail:
        Human-readable explanation (e.g. ``"native multimodal: image+video"``).
    score_contribution:
        Numeric score contributed by this reason to the provider's total score.
        ``0.0`` when the reason is informational only.
    """

    code: str  # SelectionReasonCode value
    dimension: str  # SelectionDimension value
    detail: str = ""
    score_contribution: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "dimension": self.dimension,
            "detail": self.detail,
            "score_contribution": self.score_contribution,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SelectionReason":
        return cls(
            code=str(d.get("code") or ""),
            dimension=str(d.get("dimension") or ""),
            detail=str(d.get("detail") or ""),
            score_contribution=float(d.get("score_contribution") or 0.0),
        )


# ---------------------------------------------------------------------------
# ModelSelectionPolicy — per-request policy inputs
# ---------------------------------------------------------------------------


@dataclass
class ModelSelectionPolicy:
    """Per-request model selection policy inputs and constraints.

    This structure carries the **inputs** that the caller (OpenClawd) provides
    to the :class:`ModelSelectionPolicyEngine`.  It does not carry supply
    state — that is read from
    :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`.

    All fields are optional and default to permissive / unspecified values so
    that legacy text-only requests work without any configuration.

    Attributes
    ----------
    required_modalities:
        List of modality labels that the selected model must support
        (e.g. ``["image"]``, ``["audio", "video_frame"]``).
        Empty list means text-only request — native multimodal not required.
    prefer_native_multimodal:
        When ``True`` and ``required_modalities`` is non-empty, the engine
        strongly prefers providers with native multimodal API support over
        text-capable (partial / summary-based) alternatives.
        Defaults to ``True`` (native multimodal is a first-class preference).
    allow_partial_multimodal:
        When ``True``, providers that support a subset of ``required_modalities``
        are acceptable (with lower score than full native multimodal).
        When ``False``, only full native multimodal providers qualify for
        multimodal requests; partial providers are treated as text-only.
        Defaults to ``True``.
    latency_budget_ms:
        Maximum acceptable provider average latency in milliseconds.  Providers
        that exceed this value are penalised in scoring but not disqualified
        (degraded gracefully to fallback).  ``None`` means no latency constraint.
    cost_tier:
        Cost preference: ``"low"`` prefers lower-cost providers; ``"high"``
        prefers higher-cost (premium quality) providers; ``"medium"`` or
        ``None`` is neutral.
    quality_tier:
        Quality preference hint: ``"standard"`` or ``"premium"``.  Currently
        used as a tiebreak signal when cost_tier is ``None``.  ``None`` is
        neutral.
    preferred_locality:
        Preferred deployment locality: ``"local"`` prefers locally-hosted
        providers; ``"cloud"`` prefers cloud/remote providers; ``"any"``
        (or ``None``) is neutral.
    allow_auxiliary_models:
        When ``True``, the engine considers support/auxiliary model candidates
        as valid selections for certain task types.  Defaults to ``True``.
    trace_id:
        Optional correlation ID for logging/diagnostics.
    """

    required_modalities: List[str] = field(default_factory=list)
    prefer_native_multimodal: bool = True
    allow_partial_multimodal: bool = True
    latency_budget_ms: Optional[float] = None
    cost_tier: Optional[str] = None          # "low" | "medium" | "high" | None
    quality_tier: Optional[str] = None       # "standard" | "premium" | None
    preferred_locality: Optional[str] = None  # "local" | "cloud" | "hybrid" | "any" | None
    allow_auxiliary_models: bool = True
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_modalities": list(self.required_modalities),
            "prefer_native_multimodal": self.prefer_native_multimodal,
            "allow_partial_multimodal": self.allow_partial_multimodal,
            "latency_budget_ms": self.latency_budget_ms,
            "cost_tier": self.cost_tier,
            "quality_tier": self.quality_tier,
            "preferred_locality": self.preferred_locality,
            "allow_auxiliary_models": self.allow_auxiliary_models,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelSelectionPolicy":
        return cls(
            required_modalities=list(d.get("required_modalities") or []),
            prefer_native_multimodal=bool(d.get("prefer_native_multimodal", True)),
            allow_partial_multimodal=bool(d.get("allow_partial_multimodal", True)),
            latency_budget_ms=(
                float(d["latency_budget_ms"])
                if d.get("latency_budget_ms") is not None
                else None
            ),
            cost_tier=d.get("cost_tier"),
            quality_tier=d.get("quality_tier"),
            preferred_locality=d.get("preferred_locality"),
            allow_auxiliary_models=bool(d.get("allow_auxiliary_models", True)),
            trace_id=d.get("trace_id"),
        )

    @classmethod
    def text_only(cls, trace_id: Optional[str] = None) -> "ModelSelectionPolicy":
        """Convenience constructor for a text-only (no multimodal) policy."""
        return cls(required_modalities=[], trace_id=trace_id)

    @classmethod
    def native_multimodal_preferred(
        cls,
        required_modalities: List[str],
        trace_id: Optional[str] = None,
        **kwargs: Any,
    ) -> "ModelSelectionPolicy":
        """Convenience constructor that sets native multimodal as first priority."""
        return cls(
            required_modalities=required_modalities,
            prefer_native_multimodal=True,
            allow_partial_multimodal=True,
            trace_id=trace_id,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# ModelSelectionDecision — structured output of the policy engine
# ---------------------------------------------------------------------------


@dataclass
class ModelSelectionDecision:
    """Structured, explainable model selection decision produced by the engine.

    This is the canonical output of :class:`ModelSelectionPolicyEngine`.  It
    carries not only the winning provider/model but also:

    * structured :class:`SelectionReason` records for every dimension that
      influenced the decision
    * an ordered fallback chain of alternative providers
    * a compact decision summary suitable for diagnostics and projection

    **OpenClawd embeds this record in the** :class:`~core.schemas.unified_control_plan.UnifiedControlPlan`
    via the ``model_selection_decision`` field.

    Attributes
    ----------
    chosen_provider_id:
        The canonical provider identifier selected by the engine.
        ``None`` when no provider was available.
    chosen_model_id:
        The canonical model identifier selected (default model of the provider).
        ``None`` when no provider was available.
    is_native_multimodal:
        ``True`` when the selected provider/model has native multimodal API
        support and a multimodal modality was required.
    is_partial_multimodal:
        ``True`` when the selected provider supports some (but not all) of the
        required modalities via native API.
    selection_reasons:
        Ordered list of :class:`SelectionReason` records explaining the
        decision.  The most significant reason is first.
    fallback_chain:
        Ordered list of provider IDs that are valid fallback alternatives,
        from most preferred to least preferred.  Excludes the winning provider.
    considered_providers:
        All provider IDs that were evaluated (available + unavailable).
    policy_snapshot:
        Serialisable snapshot of the :class:`ModelSelectionPolicy` that was
        applied, for auditability.
    decision_summary:
        Human-readable one-line summary of the decision (auto-derived).
    score_breakdown:
        Dict mapping provider_id to numeric score for diagnostics.
    """

    chosen_provider_id: Optional[str] = None
    chosen_model_id: Optional[str] = None
    is_native_multimodal: bool = False
    is_partial_multimodal: bool = False

    selection_reasons: List[SelectionReason] = field(default_factory=list)
    fallback_chain: List[str] = field(default_factory=list)
    considered_providers: List[str] = field(default_factory=list)

    policy_snapshot: Optional[Dict[str, Any]] = None
    decision_summary: Optional[str] = None
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.decision_summary:
            self.decision_summary = self._derive_summary()

    def _derive_summary(self) -> str:
        if self.chosen_provider_id is None:
            return "no_selection: no available provider"
        mm_flag = ""
        if self.is_native_multimodal:
            mm_flag = " [native-multimodal]"
        elif self.is_partial_multimodal:
            mm_flag = " [partial-multimodal]"
        primary_reason = (
            self.selection_reasons[0].code
            if self.selection_reasons
            else "unspecified"
        )
        return (
            f"selected={self.chosen_provider_id}/{self.chosen_model_id}{mm_flag} "
            f"reason={primary_reason} "
            f"fallbacks={len(self.fallback_chain)}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a fully serialisable dict representation."""
        return {
            "chosen_provider_id": self.chosen_provider_id,
            "chosen_model_id": self.chosen_model_id,
            "is_native_multimodal": self.is_native_multimodal,
            "is_partial_multimodal": self.is_partial_multimodal,
            "selection_reasons": [r.to_dict() for r in self.selection_reasons],
            "fallback_chain": list(self.fallback_chain),
            "considered_providers": list(self.considered_providers),
            "policy_snapshot": self.policy_snapshot,
            "decision_summary": self.decision_summary,
            "score_breakdown": dict(self.score_breakdown),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelSelectionDecision":
        """Reconstruct from a serialised dict; unknown keys degrade gracefully."""
        reasons_raw = d.get("selection_reasons") or []
        reasons = [
            SelectionReason.from_dict(r) if isinstance(r, dict) else r
            for r in reasons_raw
        ]
        obj = cls(
            chosen_provider_id=d.get("chosen_provider_id"),
            chosen_model_id=d.get("chosen_model_id"),
            is_native_multimodal=bool(d.get("is_native_multimodal", False)),
            is_partial_multimodal=bool(d.get("is_partial_multimodal", False)),
            selection_reasons=reasons,
            fallback_chain=list(d.get("fallback_chain") or []),
            considered_providers=list(d.get("considered_providers") or []),
            policy_snapshot=d.get("policy_snapshot"),
            decision_summary=d.get("decision_summary"),
            score_breakdown=dict(d.get("score_breakdown") or {}),
        )
        return obj

    @classmethod
    def unavailable(
        cls,
        policy: Optional["ModelSelectionPolicy"] = None,
        detail: str = "supply_state_unavailable",
    ) -> "ModelSelectionDecision":
        """Factory: produce a no-selection decision when supply state is missing."""
        reason = SelectionReason(
            code=SelectionReasonCode.SUPPLY_STATE_UNAVAILABLE.value,
            dimension=SelectionDimension.SUPPLY_UNAVAILABLE.value,
            detail=detail,
        )
        obj = cls(
            chosen_provider_id=None,
            chosen_model_id=None,
            selection_reasons=[reason],
            policy_snapshot=policy.to_dict() if policy is not None else None,
            decision_summary=f"no_selection: {detail}",
        )
        return obj


# ---------------------------------------------------------------------------
# Internal scoring helpers
# ---------------------------------------------------------------------------


_HEALTH_SCORE: Dict[str, float] = {
    "healthy": 10.0,
    "degraded": 2.0,
    "down": -9999.0,  # effectively disqualifies
    "unknown": 1.0,
}

_LOCALITY_SCORE: Dict[str, Dict[str, float]] = {
    "local": {"local": 5.0, "hybrid": 2.0, "cloud": 0.0, "unknown": 0.0},
    "cloud": {"cloud": 5.0, "hybrid": 2.0, "local": 0.0, "unknown": 0.0},
    "hybrid": {"hybrid": 5.0, "local": 2.0, "cloud": 2.0, "unknown": 0.0},
}


def _score_provider(
    provider_id: str,
    record: Dict[str, Any],
    policy: ModelSelectionPolicy,
    cap: Optional[Dict[str, Any]],
) -> tuple[float, List[SelectionReason]]:
    """Compute a numeric score and reasons list for one provider record.

    Parameters
    ----------
    provider_id:
        Canonical provider identifier.
    record:
        ``ProviderSupplyRecord.to_dict()``-style dict from the supply state.
    policy:
        The active :class:`ModelSelectionPolicy`.
    cap:
        ``NativeMultimodalCapability.to_dict()``-style capability dict for this
        provider, or ``None`` when capability info is absent.

    Returns
    -------
    (score, reasons)
    """
    score: float = 0.0
    reasons: List[SelectionReason] = []

    # ── Health ────────────────────────────────────────────────────────────────
    health_str = str(record.get("health_status") or "unknown").lower()
    h_score = _HEALTH_SCORE.get(health_str, 1.0)
    score += h_score
    reasons.append(SelectionReason(
        code=SelectionReasonCode.HEALTH_TIEBREAK.value,
        dimension=SelectionDimension.HEALTH_STATUS.value,
        detail=f"health={health_str}",
        score_contribution=h_score,
    ))

    # ── Multimodal capability ─────────────────────────────────────────────────
    req = policy.required_modalities
    cap_modalities: List[str] = list(cap.get("active_modalities") or []) if cap else []
    is_native = bool(cap.get("is_natively_multimodal", False)) if cap else False

    if req:
        overlap = [m for m in req if m in cap_modalities]
        full_match = len(overlap) == len(req)
        partial_match = bool(overlap) and not full_match

        if is_native and full_match and policy.prefer_native_multimodal:
            mm_score = 40.0
            reasons.append(SelectionReason(
                code=SelectionReasonCode.NATIVE_MULTIMODAL_PREFERRED.value,
                dimension=SelectionDimension.NATIVE_MULTIMODAL_MATCH.value,
                detail=f"native_multimodal: required={req} supported={cap_modalities}",
                score_contribution=mm_score,
            ))
            score += mm_score
        elif is_native and partial_match and policy.allow_partial_multimodal:
            mm_score = 20.0
            reasons.append(SelectionReason(
                code=SelectionReasonCode.PARTIAL_MULTIMODAL_BEST_AVAILABLE.value,
                dimension=SelectionDimension.PARTIAL_MULTIMODAL_MATCH.value,
                detail=(
                    f"partial_multimodal: required={req} "
                    f"matched={overlap} not_matched={[m for m in req if m not in overlap]}"
                ),
                score_contribution=mm_score,
            ))
            score += mm_score
        else:
            # Text-only provider for a multimodal request
            reasons.append(SelectionReason(
                code=SelectionReasonCode.TEXT_ONLY_SELECTED.value,
                dimension=SelectionDimension.TEXT_ONLY_FALLBACK.value,
                detail=f"no_native_multimodal: required={req} provider_caps={cap_modalities}",
                score_contribution=0.0,
            ))
    else:
        # Text-only request
        reasons.append(SelectionReason(
            code=SelectionReasonCode.TEXT_ONLY_SELECTED.value,
            dimension=SelectionDimension.TEXT_ONLY_FALLBACK.value,
            detail="text_only_request",
            score_contribution=0.0,
        ))

    # ── Locality ──────────────────────────────────────────────────────────────
    pref_loc = (policy.preferred_locality or "any").lower()
    if pref_loc not in ("any", "", "none"):
        provider_loc = str(record.get("locality_class") or "unknown").lower()
        locality_bonus = _LOCALITY_SCORE.get(pref_loc, {}).get(provider_loc, 0.0)
        if locality_bonus:
            score += locality_bonus
            reasons.append(SelectionReason(
                code=SelectionReasonCode.LOCALITY_PREFERRED.value,
                dimension=SelectionDimension.LOCALITY_MATCH.value,
                detail=f"locality: preferred={pref_loc} actual={provider_loc}",
                score_contribution=locality_bonus,
            ))

    # ── Latency budget ────────────────────────────────────────────────────────
    if policy.latency_budget_ms is not None:
        avg_latency = float(record.get("latency_avg_ms") or 0.0)
        if avg_latency > 0 and avg_latency > policy.latency_budget_ms:
            penalty = -5.0
            score += penalty
            reasons.append(SelectionReason(
                code=SelectionReasonCode.LATENCY_OVER_BUDGET.value,
                dimension=SelectionDimension.LATENCY_BUDGET.value,
                detail=(
                    f"latency={avg_latency:.0f}ms > budget={policy.latency_budget_ms:.0f}ms"
                ),
                score_contribution=penalty,
            ))

    # ── Cost tier ─────────────────────────────────────────────────────────────
    # Cost tier adjustment is applied in post-processing (relative ranking),
    # recorded here as informational reason only.
    if policy.cost_tier in ("low", "high"):
        cost_input = float(record.get("cost_per_1k_input") or 0.0)
        reasons.append(SelectionReason(
            code=SelectionReasonCode.COST_ALIGNED.value,
            dimension=SelectionDimension.COST_TIER.value,
            detail=f"cost_tier={policy.cost_tier} cost_per_1k={cost_input:.6f}",
            score_contribution=0.0,  # adjusted below in engine
        ))

    # ── Auxiliary eligibility ─────────────────────────────────────────────────
    if record.get("is_support_model_candidate") and policy.allow_auxiliary_models:
        aux_score = 2.0
        score += aux_score
        reasons.append(SelectionReason(
            code=SelectionReasonCode.AUXILIARY_CANDIDATE.value,
            dimension=SelectionDimension.AUXILIARY_ELIGIBLE.value,
            detail="support_model_candidate",
            score_contribution=aux_score,
        ))

    return score, reasons


# ---------------------------------------------------------------------------
# ModelSelectionPolicyEngine
# ---------------------------------------------------------------------------


class ModelSelectionPolicyEngine:
    """Explicit policy engine that derives model-selection decisions.

    OpenClawd invokes :meth:`evaluate` once per request (or per decision point)
    to produce a :class:`ModelSelectionDecision` from the canonical supply
    state and the per-request :class:`ModelSelectionPolicy`.

    The engine **never modifies** the supply state or the router; it is a
    read-only evaluator.

    Usage::

        engine = ModelSelectionPolicyEngine()
        decision = engine.evaluate(policy, canonical_supply_dict)
    """

    # ── Public API ───────────────────────────────────────────────────────────

    def evaluate(
        self,
        policy: ModelSelectionPolicy,
        canonical_supply: Optional[Dict[str, Any]],
    ) -> ModelSelectionDecision:
        """Evaluate *policy* against *canonical_supply* and return a decision.

        Parameters
        ----------
        policy:
            Per-request :class:`ModelSelectionPolicy` carrying the selection
            constraints and preferences.
        canonical_supply:
            Serialised
            :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`
            dict (as produced by ``CanonicalModelSupplyState.to_dict()``).
            May be ``None`` or empty — the engine degrades gracefully.

        Returns
        -------
        ModelSelectionDecision
            A fully populated, explainable decision.  Never raises.
        """
        try:
            return self._evaluate_inner(policy, canonical_supply)
        except Exception as _err:
            logger.warning(
                "ModelSelectionPolicyEngine.evaluate failed (degraded): %s", _err
            )
            return ModelSelectionDecision.unavailable(
                policy=policy,
                detail=f"engine_error={_err}",
            )

    # ── Internal implementation ──────────────────────────────────────────────

    def _evaluate_inner(
        self,
        policy: ModelSelectionPolicy,
        canonical_supply: Optional[Dict[str, Any]],
    ) -> ModelSelectionDecision:
        """Core evaluation logic (may raise; wrapped by :meth:`evaluate`)."""
        policy_snapshot = policy.to_dict()

        # ── Guard: no supply state ────────────────────────────────────────────
        if not canonical_supply:
            logger.debug(
                "ModelSelectionPolicyEngine: supply_state unavailable; "
                "returning no-selection decision"
            )
            return ModelSelectionDecision.unavailable(
                policy=policy,
                detail="supply_state_unavailable",
            )

        providers: Dict[str, Any] = canonical_supply.get("providers") or {}
        available_ids: List[str] = list(
            canonical_supply.get("available_provider_ids") or []
        )
        capability_registry: Dict[str, Any] = (
            canonical_supply.get("multimodal_registry") or {}
        )
        # Support/fallback hints from supply state
        fallback_candidates: List[str] = list(
            canonical_supply.get("fallback_candidates") or []
        )
        support_candidates: List[str] = list(
            canonical_supply.get("support_model_candidates") or []
        )

        all_provider_ids = list(providers.keys())
        considered = all_provider_ids

        # ── Guard: no available providers ─────────────────────────────────────
        if not available_ids:
            reason = SelectionReason(
                code=SelectionReasonCode.NO_CANDIDATES.value,
                dimension=SelectionDimension.NO_PROVIDER_AVAILABLE.value,
                detail=f"available=0 total={len(all_provider_ids)}",
            )
            return ModelSelectionDecision(
                chosen_provider_id=None,
                chosen_model_id=None,
                selection_reasons=[reason],
                fallback_chain=[],
                considered_providers=considered,
                policy_snapshot=policy_snapshot,
                decision_summary="no_selection: no available providers",
            )

        # ── Score each available provider ─────────────────────────────────────
        scored: List[tuple[float, int, str, List[SelectionReason]]] = []
        # ^^ (score, tiebreak_index, provider_id, reasons)

        for tiebreak_idx, pid in enumerate(available_ids):
            record = providers.get(pid) or {}
            # Capability info may be embedded in the record or in a separate registry
            cap: Optional[Dict[str, Any]] = (
                record.get("capability")
                or (capability_registry.get("capabilities") or {}).get(pid)
            )
            raw_score, reasons = _score_provider(pid, record, policy, cap)
            scored.append((raw_score, tiebreak_idx, pid, reasons))

        # ── Cost tier relative adjustment ─────────────────────────────────────
        # Apply relative cost adjustment after initial scoring.
        if policy.cost_tier in ("low", "high"):
            costs = []
            for (sc, ti, pid, _) in scored:
                rec = providers.get(pid) or {}
                costs.append(float(rec.get("cost_per_1k_input") or 0.0))
            # Avoid division by zero; only adjust when cost data is present
            if any(c > 0 for c in costs):
                min_c = min(c for c in costs if c > 0) if any(c > 0 for c in costs) else 0
                max_c = max(costs)
                rng = max_c - min_c if max_c > min_c else 1.0
                adjusted: List[tuple[float, int, str, List[SelectionReason]]] = []
                for (sc, ti, pid, reasons), cost in zip(scored, costs):
                    adj = 0.0
                    if rng > 0:
                        norm = (cost - min_c) / rng  # 0 = cheapest, 1 = most expensive
                        if policy.cost_tier == "low":
                            adj = (1.0 - norm) * 3.0
                        else:  # "high" / premium
                            adj = norm * 3.0
                    # Update the cost reason score_contribution
                    new_reasons = []
                    for r in reasons:
                        if r.dimension == SelectionDimension.COST_TIER.value:
                            r = SelectionReason(
                                code=r.code,
                                dimension=r.dimension,
                                detail=r.detail,
                                score_contribution=adj,
                            )
                        new_reasons.append(r)
                    adjusted.append((sc + adj, ti, pid, new_reasons))
                scored = adjusted

        # ── Sort: descending score, ascending tiebreak index ─────────────────
        scored.sort(key=lambda x: (-x[0], x[1]))

        winner_score, _, winner_id, winner_reasons = scored[0]
        winner_record = providers.get(winner_id) or {}
        winner_cap: Optional[Dict[str, Any]] = (
            winner_record.get("capability")
            or (capability_registry.get("capabilities") or {}).get(winner_id)
        )

        # ── Determine multimodal flags for winner ────────────────────────────
        is_native_mm = False
        is_partial_mm = False
        req = policy.required_modalities
        if req and winner_cap:
            cap_mods = list(winner_cap.get("active_modalities") or [])
            overlap = [m for m in req if m in cap_mods]
            is_native_cap = bool(winner_cap.get("is_natively_multimodal", False))
            if is_native_cap and len(overlap) == len(req):
                is_native_mm = True
            elif is_native_cap and overlap:
                is_partial_mm = True

        # ── Add sole-candidate reason when only one option ───────────────────
        if len(available_ids) == 1:
            winner_reasons.append(SelectionReason(
                code=SelectionReasonCode.SOLE_CANDIDATE.value,
                dimension=SelectionDimension.ONLY_AVAILABLE.value,
                detail="only_available_provider",
            ))

        # ── Add fallback reason when winner is not the primary supply hint ────
        primary_hint = canonical_supply.get("primary_provider_id")
        if (
            primary_hint
            and winner_id != primary_hint
            and len(scored) > 1
        ):
            winner_reasons.append(SelectionReason(
                code=SelectionReasonCode.FALLBACK_SELECTED.value,
                dimension=SelectionDimension.ONLY_AVAILABLE.value,
                detail=(
                    f"policy_winner={winner_id} supply_primary_hint={primary_hint}"
                ),
            ))

        # ── Build fallback chain from remaining scored candidates ─────────────
        fallback_chain: List[str] = [pid for (_, _, pid, _) in scored[1:]]

        # ── Chosen model ID ───────────────────────────────────────────────────
        chosen_model = winner_record.get("default_model") or winner_id

        logger.debug(
            "ModelSelectionPolicyEngine: winner=%s model=%s score=%.1f "
            "is_native_mm=%s fallbacks=%d trace=%s",
            winner_id,
            chosen_model,
            winner_score,
            is_native_mm,
            len(fallback_chain),
            policy.trace_id or "",
        )

        # ── Build score breakdown for diagnostics ────────────────────────────
        score_breakdown = {pid: sc for (sc, _, pid, _) in scored}

        return ModelSelectionDecision(
            chosen_provider_id=winner_id,
            chosen_model_id=chosen_model,
            is_native_multimodal=is_native_mm,
            is_partial_multimodal=is_partial_mm,
            selection_reasons=winner_reasons,
            fallback_chain=fallback_chain,
            considered_providers=considered,
            policy_snapshot=policy_snapshot,
            score_breakdown=score_breakdown,
        )


# ---------------------------------------------------------------------------
# Convenience builder
# ---------------------------------------------------------------------------


def build_model_selection_policy_from_perception(
    canonical_perception: Optional[Dict[str, Any]],
    *,
    latency_budget_ms: Optional[float] = None,
    cost_tier: Optional[str] = None,
    quality_tier: Optional[str] = None,
    preferred_locality: Optional[str] = None,
    allow_auxiliary_models: bool = True,
    trace_id: Optional[str] = None,
) -> ModelSelectionPolicy:
    """Build a :class:`ModelSelectionPolicy` from a canonical perception dict.

    Convenience bridge that reads ``requires_native_multimodal`` and
    ``active_modalities`` from the perception state to construct the policy
    without duplicating the modality logic in the caller.

    Parameters
    ----------
    canonical_perception:
        Serialised
        :class:`~core.perception.canonical_perception_state.CanonicalPerceptionState`
        dict (may be ``None`` for text-only requests).

    Returns
    -------
    ModelSelectionPolicy
    """
    if not canonical_perception:
        return ModelSelectionPolicy.text_only(trace_id=trace_id)

    active_modalities: List[str] = list(
        canonical_perception.get("active_modalities") or []
    )
    requires_native = bool(
        canonical_perception.get("requires_native_multimodal", False)
    )

    if not active_modalities and not requires_native:
        return ModelSelectionPolicy(
            required_modalities=[],
            prefer_native_multimodal=True,
            latency_budget_ms=latency_budget_ms,
            cost_tier=cost_tier,
            quality_tier=quality_tier,
            preferred_locality=preferred_locality,
            allow_auxiliary_models=allow_auxiliary_models,
            trace_id=trace_id,
        )

    return ModelSelectionPolicy(
        required_modalities=active_modalities,
        prefer_native_multimodal=requires_native or True,
        allow_partial_multimodal=True,
        latency_budget_ms=latency_budget_ms,
        cost_tier=cost_tier,
        quality_tier=quality_tier,
        preferred_locality=preferred_locality,
        allow_auxiliary_models=allow_auxiliary_models,
        trace_id=trace_id,
    )
