"""
core/llm/supply_authority.py — Canonical LLM Model Supply Authority
====================================================================

**L2: Canonicalize model supply truth, provider ordering, and fallback legality**

This module is the **single canonical LLM supply authority** for the Galaxy
system.  It sits between the L1 routing authority and the provider execution
layer, and is responsible for:

- Determining whether a canonical route intent (from :class:`LLMRouteDecision`)
  can be satisfied by the currently available provider supply.
- Enforcing explicit, consistent provider ordering rather than allowing
  scattered integrations to define implicit ordering.
- Authorising or rejecting fallback / substitution with an explicit legality
  classification rather than allowing ad-hoc provider-specific shortcuts.
- Making it always clear which model/provider was *requested*, which was
  *supplied*, and *why* any fallback was legal.

Architecture
------------

.. code-block:: text

    LLMRouteDecision           ← L1 canonical route intent
        │  (produced by LLMRouteAuthority.resolve())
        ▼
    LLMSupplyAuthority.resolve_supply(decision, supply_state)
        │  ← L2 canonical supply resolution
        │  1. Validate the canonical provider order from supply_state.
        │  2. Check whether the intended provider/model is available.
        │  3. If unavailable, determine whether a fallback is LEGAL
        │     under the active FallbackLegality policy.
        │  4. Emit a SupplyResolutionResult that makes the full trace
        │     explicit and auditable.
        ▼
    SupplyResolutionResult {
        requested_provider, requested_model,        ← what the router asked for
        supplied_provider, supplied_model,           ← what supply actually gives
        fallback_legality,                           ← legal basis (or NONE)
        ordering_basis,                              ← how providers were ordered
        is_satisfied,                                ← whether supply can proceed
        resolution_trace,                            ← ordered audit list
        authority,                                   ← LLM_SUPPLY_AUTHORITY sentinel
    }
        │
        ▼
    Provider execution layer (MultiLLMRouter)

Authority sentinel
------------------
``LLM_SUPPLY_AUTHORITY = "core.llm.supply_authority.LLMSupplyAuthority"``

Import this sentinel to assert that a downstream layer is consuming the
canonical supply result rather than a provider-specific or ad-hoc supply path.

Fallback legality contract
--------------------------
Fallback is ONLY permitted under one of the following explicit legal bases:

- :attr:`FallbackLegality.PRIMARY_UNAVAILABLE` — the primary provider API key
  is missing or the provider health status is DOWN.
- :attr:`FallbackLegality.PRIMARY_DEGRADED` — the primary provider is DEGRADED
  (circuit breaker open / elevated error rate) and the policy allows degraded
  fallback.
- :attr:`FallbackLegality.CAPABILITY_MISMATCH` — the primary provider lacks a
  required capability (e.g. tool use, multimodal) and a capable fallback is
  available.
- :attr:`FallbackLegality.EXPLICIT_CALLER_PREFERENCE` — the caller held
  ``preferred_provider`` which is unavailable; routing authority already
  consented to fall through.

Any fallback that cannot be classified under one of these bases is rejected;
:attr:`SupplyResolutionResult.is_satisfied` is ``False`` and the reason is
recorded in :attr:`SupplyResolutionResult.resolution_trace`.

Provider ordering contract
--------------------------
Provider ordering is derived from the **canonical supply state snapshot** passed
to :meth:`LLMSupplyAuthority.resolve_supply`.  The ordering is never inferred
ad-hoc inside a provider-specific integration.

Ordering priority (highest first):

1. Provider explicitly named in the ``LLMRouteDecision`` (the canonical route
   intent from L1).
2. Available providers in the canonical ``fallback_candidates`` list of the
   supply state.
3. Any remaining available providers not in the above lists.

Providers with health status DOWN are always excluded from the ordering.

Design principles
-----------------
- **Supply truth is canonical and separated from route intent.**  Route intent
  belongs to L1; supply truth belongs to L2.
- **Provider ordering is explicit and consistent.**  The ordering algorithm is
  defined once here, not scattered across provider integrations.
- **Fallback is policy-governed.**  Every fallback emits an explicit
  :class:`FallbackLegality` value.
- **Provider-specific code must not act as a hidden supply authority.**
  Necessary provider-specific adaptations are confined to the execution layer
  and do not alter supply truth.
- **The resolution trace makes the full supply decision auditable.**

Usage::

    from core.llm.supply_authority import (
        LLM_SUPPLY_AUTHORITY,
        LLMSupplyAuthority,
        FallbackLegality,
        SupplyResolutionResult,
        get_llm_supply_authority,
    )
    from core.llm.route_authority import LLMRouteDecision, LLMRouteRequest

    supply_auth = get_llm_supply_authority()

    # Resolve supply against a canonical model supply state snapshot
    result = supply_auth.resolve_supply(route_decision, supply_snapshot)

    if not result.is_satisfied:
        # No legal supply path — log and handle gracefully
        ...
    elif result.fallback_legality != FallbackLegality.NONE:
        # Fallback was taken; the legality is explicit
        ...
    else:
        # Primary supply satisfied
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LLM.SupplyAuthority")

# ---------------------------------------------------------------------------
# Module authority sentinel
# ---------------------------------------------------------------------------

#: Identifies this module as the **single canonical LLM supply authority**.
#:
#: Import this sentinel to assert that a downstream call site is consuming a
#: supply decision originating from the canonical supply authority rather than
#: a scattered provider-specific or ad-hoc supply path.
#:
#: See ``docs/MODEL_ROUTING_AUTHORITY.md`` §10 for the full supply policy.
LLM_SUPPLY_AUTHORITY: str = "core.llm.supply_authority.LLMSupplyAuthority"


# ---------------------------------------------------------------------------
# FallbackLegality — explicit legal basis for any fallback / substitution
# ---------------------------------------------------------------------------


class FallbackLegality(str, Enum):
    """Explicit, canonical legal basis for a provider fallback or substitution.

    Every fallback taken by the supply authority must be classified under one
    of these values.  ``NONE`` indicates that no fallback was needed (the
    primary route intent was satisfied directly).

    Attributes
    ----------
    NONE:
        No fallback was taken; the primary provider/model was supplied as
        intended by the canonical routing decision.
    PRIMARY_UNAVAILABLE:
        The primary provider is unavailable (API key absent, health status
        DOWN, or no models registered).  A fallback to the next available
        provider in the canonical ordering was authorised.
    PRIMARY_DEGRADED:
        The primary provider is degraded (elevated error rate, circuit breaker
        open).  Fallback to a healthy provider was authorised under the
        active degraded-fallback policy.
    CAPABILITY_MISMATCH:
        The primary provider lacks a required capability (e.g. tool-use,
        native multimodal).  A capable fallback was authorised.
    EXPLICIT_CALLER_PREFERENCE:
        The caller expressed a ``preferred_provider`` that is unavailable.
        The routing authority already consented to fall through; this value
        marks the supply-layer acknowledgement of that consent.
    NO_SUPPLY_AVAILABLE:
        No provider was available under any legal fallback path.  Supply is
        unsatisfied; ``SupplyResolutionResult.is_satisfied`` will be
        ``False``.
    """

    NONE = "none"
    PRIMARY_UNAVAILABLE = "primary_unavailable"
    PRIMARY_DEGRADED = "primary_degraded"
    CAPABILITY_MISMATCH = "capability_mismatch"
    EXPLICIT_CALLER_PREFERENCE = "explicit_caller_preference"
    NO_SUPPLY_AVAILABLE = "no_supply_available"


# ---------------------------------------------------------------------------
# ProviderOrderingPolicy — explicit, canonical ordering rules
# ---------------------------------------------------------------------------


@dataclass
class ProviderOrderingPolicy:
    """Explicit canonical policy governing provider ordering for supply resolution.

    This object makes provider ordering rules first-class and auditable.  It
    is consulted by :class:`LLMSupplyAuthority` during supply resolution and
    is embedded in :class:`SupplyResolutionResult` so consumers can see which
    ordering basis was applied.

    Attributes
    ----------
    allow_degraded_fallback:
        When ``True``, DEGRADED providers are eligible as fallbacks after all
        HEALTHY providers have been tried.  When ``False``, DEGRADED providers
        are skipped.  Defaults to ``True``.
    max_fallback_depth:
        Maximum number of fallback providers to try before declaring supply
        unsatisfied.  ``0`` means no fallback is permitted (only the primary
        will be tried).  Defaults to ``5``.
    prefer_canonical_fallback_list:
        When ``True`` (default), the :attr:`~CanonicalModelSupplyState.fallback_candidates`
        list from the supply snapshot is used as the authoritative fallback
        ordering.  When ``False``, available providers are ordered by
        health status (HEALTHY first) then by their position in the supply
        snapshot's ``available_provider_ids`` list.
    required_capabilities:
        Optional list of required capability strings (e.g. ``["tool_use"]``,
        ``["image"]``).  Providers that do not declare the required
        capabilities are skipped; if none match, ``CAPABILITY_MISMATCH``
        fallback applies.
    """

    allow_degraded_fallback: bool = True
    max_fallback_depth: int = 5
    prefer_canonical_fallback_list: bool = True
    required_capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow_degraded_fallback": self.allow_degraded_fallback,
            "max_fallback_depth": self.max_fallback_depth,
            "prefer_canonical_fallback_list": self.prefer_canonical_fallback_list,
            "required_capabilities": list(self.required_capabilities),
        }


# ---------------------------------------------------------------------------
# SupplyResolutionStep — one step in the supply resolution trace
# ---------------------------------------------------------------------------


@dataclass
class SupplyResolutionStep:
    """A single step in the supply resolution trace.

    Records the outcome of attempting to satisfy supply from one provider.

    Attributes
    ----------
    provider:
        Provider identifier attempted at this step.
    model:
        Model identifier associated with this provider at this step.
    selected:
        ``True`` if this step represents the final supply selection.
    skipped:
        ``True`` if this provider was skipped.
    skip_reason:
        Human-readable reason for skipping (only set when ``skipped=True``).
    fallback_legality:
        The legal basis under which this provider was tried as a fallback
        (``FallbackLegality.NONE`` for the primary attempt).
    """

    provider: str
    model: str
    selected: bool = False
    skipped: bool = False
    skip_reason: str = ""
    fallback_legality: FallbackLegality = FallbackLegality.NONE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "selected": self.selected,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "fallback_legality": self.fallback_legality.value,
        }


# ---------------------------------------------------------------------------
# SupplyResolutionResult — canonical output of supply authority
# ---------------------------------------------------------------------------


@dataclass
class SupplyResolutionResult:
    """Canonical output of a supply resolution decision.

    Makes it always clear which provider/model was *requested* (route intent),
    which was *supplied* (actual supply), and *why* any fallback was legal.

    Attributes
    ----------
    requested_provider:
        Provider requested by the canonical routing decision (L1 intent).
    requested_model:
        Model requested by the canonical routing decision (L1 intent).
    supplied_provider:
        Provider that will actually satisfy this request (after fallback, if
        any).  ``None`` when supply is unsatisfied.
    supplied_model:
        Model that will actually satisfy this request.  ``None`` when supply
        is unsatisfied.
    fallback_legality:
        Legal basis for any fallback taken.  ``FallbackLegality.NONE``
        when the primary was satisfied directly.
    ordering_basis:
        Human-readable description of how providers were ordered for this
        resolution (for diagnostics / audit).
    is_satisfied:
        ``True`` when a legal supply path was found (either primary or a
        legal fallback).  ``False`` when no provider could be supplied.
    resolution_trace:
        Ordered list of :class:`SupplyResolutionStep` records — the full
        audit trail of which providers were tried and why.
    authority:
        Always :data:`LLM_SUPPLY_AUTHORITY` — identifies this result as
        originating from the canonical supply authority.
    policy:
        The :class:`ProviderOrderingPolicy` that was active during resolution.
    """

    requested_provider: str
    requested_model: str
    supplied_provider: Optional[str] = None
    supplied_model: Optional[str] = None
    fallback_legality: FallbackLegality = FallbackLegality.NONE
    ordering_basis: str = ""
    is_satisfied: bool = False
    resolution_trace: List[SupplyResolutionStep] = field(default_factory=list)
    authority: str = LLM_SUPPLY_AUTHORITY
    policy: Optional[ProviderOrderingPolicy] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable representation of the supply resolution."""
        return {
            "requested_provider": self.requested_provider,
            "requested_model": self.requested_model,
            "supplied_provider": self.supplied_provider,
            "supplied_model": self.supplied_model,
            "fallback_legality": self.fallback_legality.value,
            "ordering_basis": self.ordering_basis,
            "is_satisfied": self.is_satisfied,
            "resolution_trace": [step.to_dict() for step in self.resolution_trace],
            "authority": self.authority,
            "policy": self.policy.to_dict() if self.policy else None,
        }


# ---------------------------------------------------------------------------
# LLMSupplyAuthority — canonical supply resolution class
# ---------------------------------------------------------------------------


class LLMSupplyAuthority:
    """Single canonical authority for LLM model supply resolution.

    Sits between the L1 :class:`~core.llm.route_authority.LLMRouteAuthority`
    (which determines *route intent*) and the provider execution layer (which
    performs *execution*).

    Responsibilities
    ----------------
    * :meth:`resolve_supply` — take an :class:`~core.llm.route_authority.LLMRouteDecision`
      and a canonical supply snapshot, and determine the legal supply path.
    * Enforce explicit, consistent provider ordering.
    * Enforce explicit fallback legality.
    * Emit a :class:`SupplyResolutionResult` that makes the full trace auditable.

    Provider-specific code must not perform supply resolution independently.
    Emergency / shortcut paths inside providers are not permitted to override
    the canonical supply decision produced by this class.

    Parameters
    ----------
    policy:
        Active :class:`ProviderOrderingPolicy`.  Defaults to the standard
        policy when not provided.
    """

    def __init__(self, policy: Optional[ProviderOrderingPolicy] = None) -> None:
        self._policy = policy or ProviderOrderingPolicy()

    @property
    def policy(self) -> ProviderOrderingPolicy:
        """The active provider ordering and fallback legality policy."""
        return self._policy

    # ------------------------------------------------------------------
    # Primary supply resolution gate
    # ------------------------------------------------------------------

    def resolve_supply(
        self,
        route_decision: Any,  # LLMRouteDecision
        supply_state: Any,  # CanonicalModelSupplyState or dict
    ) -> SupplyResolutionResult:
        """Resolve a canonical route decision against available provider supply.

        This is the **single gate** through which supply decisions must pass.
        It enforces:

        1. Explicit provider ordering based on the canonical supply state.
        2. Explicit fallback legality — fallback only under a legal basis.
        3. A complete, auditable resolution trace.

        Parameters
        ----------
        route_decision:
            The :class:`~core.llm.route_authority.LLMRouteDecision` produced
            by the canonical L1 routing authority.  Must carry
            ``provider`` and ``model`` fields.
        supply_state:
            The canonical supply snapshot.  Accepts either a
            :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`
            object or its ``to_dict()`` serialisation.

        Returns
        -------
        SupplyResolutionResult:
            Full supply resolution with authority sentinel, trace, and
            explicit fallback legality.
        """
        requested_provider = getattr(route_decision, "provider", None) or ""
        requested_model = getattr(route_decision, "model", None) or ""

        result = SupplyResolutionResult(
            requested_provider=requested_provider,
            requested_model=requested_model,
            authority=LLM_SUPPLY_AUTHORITY,
            policy=self._policy,
        )

        # Normalise supply_state to a dict representation
        supply_dict = self._normalise_supply_state(supply_state)
        provider_records = supply_dict.get("providers", {})

        # Build the canonical ordered provider list
        ordered_candidates = self._build_ordered_candidates(
            requested_provider=requested_provider,
            supply_dict=supply_dict,
            provider_records=provider_records,
        )

        result.ordering_basis = self._describe_ordering_basis(
            requested_provider, supply_dict
        )

        # Walk the ordered candidate list; try primary then fallbacks
        self._walk_candidates(
            ordered_candidates=ordered_candidates,
            requested_provider=requested_provider,
            requested_model=requested_model,
            provider_records=provider_records,
            result=result,
        )

        logger.debug(
            "LLMSupplyAuthority.resolve_supply: requested=%s/%s → supplied=%s/%s "
            "fallback=%s satisfied=%s",
            requested_provider,
            requested_model,
            result.supplied_provider,
            result.supplied_model,
            result.fallback_legality.value,
            result.is_satisfied,
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_supply_state(supply_state: Any) -> Dict[str, Any]:
        """Return the supply state as a plain dict."""
        if supply_state is None:
            return {}
        if isinstance(supply_state, dict):
            return supply_state
        # CanonicalModelSupplyState or similar object with to_dict()
        if hasattr(supply_state, "to_dict"):
            return supply_state.to_dict()  # type: ignore[return-value]
        # Attempt attribute access for known fields
        providers_raw = getattr(supply_state, "providers", {})
        # CanonicalModelSupplyState stores providers as {id: ProviderSupplyRecord}
        # Normalise to serialisable dict
        providers_dict: Dict[str, Any] = {}
        if isinstance(providers_raw, dict):
            for pid, rec in providers_raw.items():
                if hasattr(rec, "to_dict"):
                    providers_dict[pid] = rec.to_dict()
                elif isinstance(rec, dict):
                    providers_dict[pid] = rec
                else:
                    providers_dict[pid] = {"provider_id": pid}
        return {
            "providers": providers_dict,
            "available_provider_ids": list(
                getattr(supply_state, "available_provider_ids", [])
            ),
            "unavailable_provider_ids": list(
                getattr(supply_state, "unavailable_provider_ids", [])
            ),
            "fallback_candidates": list(
                getattr(supply_state, "fallback_candidates", [])
            ),
            "primary_provider_id": getattr(supply_state, "primary_provider_id", None),
        }

    def _build_ordered_candidates(
        self,
        requested_provider: str,
        supply_dict: Dict[str, Any],
        provider_records: Dict[str, Any],
    ) -> List[str]:
        """Return the canonical ordered list of provider IDs for resolution.

        Priority (highest first):
        1. The provider explicitly named in the route decision.
        2. The canonical fallback_candidates list from the supply state
           (when prefer_canonical_fallback_list is True).
        3. Remaining available providers not already in the list.
        """
        seen: set = set()
        ordered: List[str] = []

        def _add(pid: str) -> None:
            if pid and pid not in seen:
                seen.add(pid)
                ordered.append(pid)

        # 1. Requested provider first (canonical route intent)
        if requested_provider:
            _add(requested_provider)

        # 2. Canonical fallback list from supply state
        if self._policy.prefer_canonical_fallback_list:
            for pid in supply_dict.get("fallback_candidates", []):
                _add(pid)

        # 3. Remaining available providers
        for pid in supply_dict.get("available_provider_ids", []):
            _add(pid)

        # 4. Any providers from the records that are not DOWN (final safety net)
        for pid, rec in provider_records.items():
            health = str(
                rec.get("health_status", "unknown") if isinstance(rec, dict)
                else getattr(rec, "health_status", "unknown")
            ).lower()
            if health not in ("down", "unavailable"):
                _add(pid)

        return ordered

    @staticmethod
    def _describe_ordering_basis(
        requested_provider: str,
        supply_dict: Dict[str, Any],
    ) -> str:
        """Return a human-readable description of the ordering basis."""
        parts: List[str] = []
        if requested_provider:
            parts.append(f"route_intent={requested_provider}")
        fallback_list = supply_dict.get("fallback_candidates", [])
        if fallback_list:
            parts.append(f"canonical_fallback_list={fallback_list}")
        available = supply_dict.get("available_provider_ids", [])
        if available:
            parts.append(f"available_ids={available}")
        return "; ".join(parts) if parts else "no_supply_data"

    def _walk_candidates(
        self,
        ordered_candidates: List[str],
        requested_provider: str,
        requested_model: str,
        provider_records: Dict[str, Any],
        result: SupplyResolutionResult,
    ) -> None:
        """Walk the ordered candidate list and populate *result* in-place."""
        fallback_depth = 0

        for idx, pid in enumerate(ordered_candidates):
            is_primary = pid == requested_provider
            rec = provider_records.get(pid)

            # If the provider is not registered in the supply records at all,
            # it cannot be canonically supplied — skip it.
            if rec is None:
                skip_reason = "not_in_supply_records"
                legality = (
                    FallbackLegality.PRIMARY_UNAVAILABLE
                    if is_primary
                    else FallbackLegality.NO_SUPPLY_AVAILABLE
                )
                result.resolution_trace.append(
                    SupplyResolutionStep(
                        provider=pid,
                        model="",
                        skipped=True,
                        skip_reason=skip_reason,
                        fallback_legality=legality,
                    )
                )
                continue

            # Determine provider health
            health = self._get_health(rec)
            model = self._get_model(pid, rec, requested_model if is_primary else "")

            if health == "down":
                skip_reason = "provider_down"
                legality = (
                    FallbackLegality.PRIMARY_UNAVAILABLE
                    if is_primary
                    else FallbackLegality.NO_SUPPLY_AVAILABLE
                )
                result.resolution_trace.append(
                    SupplyResolutionStep(
                        provider=pid,
                        model=model,
                        skipped=True,
                        skip_reason=skip_reason,
                        fallback_legality=legality,
                    )
                )
                continue

            # Check capability requirements
            if self._policy.required_capabilities:
                if not self._provider_has_capabilities(rec):
                    result.resolution_trace.append(
                        SupplyResolutionStep(
                            provider=pid,
                            model=model,
                            skipped=True,
                            skip_reason="capability_mismatch",
                            fallback_legality=FallbackLegality.CAPABILITY_MISMATCH,
                        )
                    )
                    continue

            # Determine the fallback legality for this step
            if is_primary:
                # This is the primary attempt — determine if healthy
                if health == "degraded" and not self._policy.allow_degraded_fallback:
                    result.resolution_trace.append(
                        SupplyResolutionStep(
                            provider=pid,
                            model=model,
                            skipped=True,
                            skip_reason="primary_degraded_fallback_disabled",
                            fallback_legality=FallbackLegality.PRIMARY_DEGRADED,
                        )
                    )
                    continue
                # Primary is available (healthy or degraded with policy consent)
                step_legality = FallbackLegality.NONE
            else:
                # This is a fallback attempt — check fallback depth
                if fallback_depth >= self._policy.max_fallback_depth:
                    result.resolution_trace.append(
                        SupplyResolutionStep(
                            provider=pid,
                            model=model,
                            skipped=True,
                            skip_reason="max_fallback_depth_reached",
                            fallback_legality=FallbackLegality.NO_SUPPLY_AVAILABLE,
                        )
                    )
                    continue

                fallback_depth += 1

                # Determine legal basis for fallback
                step_legality = self._determine_fallback_legality(
                    requested_provider=requested_provider,
                    primary_rec=provider_records.get(requested_provider),
                    result=result,
                )
                if health == "degraded" and not self._policy.allow_degraded_fallback:
                    result.resolution_trace.append(
                        SupplyResolutionStep(
                            provider=pid,
                            model=model,
                            skipped=True,
                            skip_reason="degraded_fallback_disabled",
                            fallback_legality=FallbackLegality.NO_SUPPLY_AVAILABLE,
                        )
                    )
                    continue

            # This provider is selected
            result.resolution_trace.append(
                SupplyResolutionStep(
                    provider=pid,
                    model=model,
                    selected=True,
                    fallback_legality=step_legality,
                )
            )
            result.supplied_provider = pid
            result.supplied_model = model
            result.fallback_legality = step_legality
            result.is_satisfied = True
            return

        # Exhausted all candidates without satisfaction
        result.fallback_legality = FallbackLegality.NO_SUPPLY_AVAILABLE
        result.is_satisfied = False

    @staticmethod
    def _get_health(rec: Any) -> str:
        """Normalise provider health to a lowercase string."""
        if rec is None:
            return "unknown"
        health_raw = (
            rec.get("health_status", "unknown")
            if isinstance(rec, dict)
            else getattr(rec, "health_status", "unknown")
        )
        if hasattr(health_raw, "value"):
            return health_raw.value.lower()
        return str(health_raw).lower()

    @staticmethod
    def _get_model(pid: str, rec: Any, preferred_model: str) -> str:
        """Return the model to use for *pid* from the supply record."""
        if preferred_model:
            return preferred_model
        if rec is None:
            return ""
        if isinstance(rec, dict):
            return rec.get("default_model", "") or ""
        return getattr(rec, "default_model", "") or ""

    def _provider_has_capabilities(self, rec: Any) -> bool:
        """Return ``True`` if the provider satisfies all required capabilities."""
        if not self._policy.required_capabilities:
            return True
        if rec is None:
            return False
        cap = (
            rec.get("capability") if isinstance(rec, dict)
            else getattr(rec, "capability", None)
        )
        if cap is None:
            # No capability record — can't verify; reject if capabilities required
            return False
        # Check tool_use
        if "tool_use" in self._policy.required_capabilities:
            supports_tools = (
                cap.get("supports_tools", False) if isinstance(cap, dict)
                else getattr(cap, "supports_tools", False)
            )
            if not supports_tools:
                return False
        # Check image/multimodal
        multimodal_caps = {"image", "audio", "video", "multimodal"}
        required_mm = set(self._policy.required_capabilities) & multimodal_caps
        if required_mm:
            is_mm = (
                cap.get("is_natively_multimodal", False) if isinstance(cap, dict)
                else getattr(cap, "is_natively_multimodal", False)
            )
            if not is_mm:
                return False
        return True

    @staticmethod
    def _determine_fallback_legality(
        requested_provider: str,
        primary_rec: Any,
        result: SupplyResolutionResult,
    ) -> FallbackLegality:
        """Return the legal basis for a fallback.

        Evaluates the primary provider record to classify the reason a
        fallback is being attempted.
        """
        if not requested_provider:
            # No specific provider was requested; any available is fine
            return FallbackLegality.NONE

        # Check whether the primary was ever tried and skipped
        primary_steps = [
            s for s in result.resolution_trace if s.provider == requested_provider
        ]
        if primary_steps:
            for step in primary_steps:
                if step.skipped:
                    skip_r = step.skip_reason
                    if "down" in skip_r or "unavailable" in skip_r:
                        return FallbackLegality.PRIMARY_UNAVAILABLE
                    if "degraded" in skip_r:
                        return FallbackLegality.PRIMARY_DEGRADED
                    if "capability" in skip_r:
                        return FallbackLegality.CAPABILITY_MISMATCH

        # Primary wasn't in the trace yet — evaluate health directly
        if primary_rec is None:
            return FallbackLegality.PRIMARY_UNAVAILABLE

        health = LLMSupplyAuthority._get_health(primary_rec)
        if health in ("down", "unavailable"):
            return FallbackLegality.PRIMARY_UNAVAILABLE
        if health == "degraded":
            return FallbackLegality.PRIMARY_DEGRADED

        return FallbackLegality.PRIMARY_UNAVAILABLE


# ---------------------------------------------------------------------------
# Module-level singleton and factory
# ---------------------------------------------------------------------------

_supply_authority_instance: Optional[LLMSupplyAuthority] = None


def get_llm_supply_authority(
    policy: Optional[ProviderOrderingPolicy] = None,
) -> LLMSupplyAuthority:
    """Return the module-level :class:`LLMSupplyAuthority` singleton.

    This is the canonical factory function for the L2 supply authority.

    Parameters
    ----------
    policy:
        Optional :class:`ProviderOrderingPolicy` to use when creating a new
        instance.  Ignored when the singleton already exists.

    Returns
    -------
    LLMSupplyAuthority:
        The canonical L2 supply authority instance.
    """
    global _supply_authority_instance
    if _supply_authority_instance is None:
        _supply_authority_instance = LLMSupplyAuthority(policy=policy)
    return _supply_authority_instance


def refresh_llm_supply_authority(
    policy: Optional[ProviderOrderingPolicy] = None,
) -> LLMSupplyAuthority:
    """Reset and re-create the :class:`LLMSupplyAuthority` singleton.

    Intended for use in test teardown or when the provider configuration has
    changed and the authority should be re-initialised with a fresh policy.

    Parameters
    ----------
    policy:
        Optional :class:`ProviderOrderingPolicy` for the new instance.

    Returns
    -------
    LLMSupplyAuthority:
        A freshly created :class:`LLMSupplyAuthority` instance.
    """
    global _supply_authority_instance
    _supply_authority_instance = LLMSupplyAuthority(policy=policy)
    return _supply_authority_instance


__all__ = [
    # authority sentinel
    "LLM_SUPPLY_AUTHORITY",
    # enums and policy
    "FallbackLegality",
    "ProviderOrderingPolicy",
    # result types
    "SupplyResolutionStep",
    "SupplyResolutionResult",
    # authority class and factories
    "LLMSupplyAuthority",
    "get_llm_supply_authority",
    "refresh_llm_supply_authority",
]
