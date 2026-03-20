#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_policy.policy_resolver
========================================

PR-11 (V4) — Execution Policy Schema

Derives an :class:`~core.execution_policy.ExecutionPolicy` from the
existing runtime signals already present in the Galaxy codebase.

The resolver consumes signals from **PR #262 – #265** without modifying any
of those modules:

  * ``TriStatePhase`` / ``RuntimeDomain`` — from PR-3 continuum types
  * ``AuthorityRole`` — from PR-9 orchestration authority consolidation
  * ``ReturnSummary`` — from PR-10 return intelligence formalization
  * ``ExecutorLevel`` — from PR-7 execution observability

All inputs are optional.  The resolver degrades gracefully when signals are
absent, returning progressively more conservative policies.

Resolution logic (in priority order)
--------------------------------------
1. **Return pressure override** — if return pressure (derived from
   ``ReturnSummary``) exceeds ``RETURN_PRESSURE_FORCE_OBSERVE`` threshold
   the band is clamped to ``observe_only`` regardless of other signals.

2. **Phase-primary band** — the base band is determined by
   ``TriStatePhase``:
   - ``silent``   → ``observe_only``
   - ``liminal``  → ``assistive``
   - ``manifest`` → ``bounded_execute``

3. **Domain upgrade** — ``RuntimeDomain.CROSS_DEVICE`` with a manifest phase
   upgrades the band to ``full_execute`` and enables cross-device expansion.

4. **Authority downgrade** — legacy or deprecated authority roles downgrade
   the band by one level and disable cross-device expansion.

5. **Return-pressure softening** — moderate return pressure (below the force-
   observe threshold) restricts the action budget and forces confirmation.

6. **Budget computation** — risk/action/fallback budgets are mapped from the
   final band.

Usage::

    from core.execution_policy import resolve_policy

    # Minimal call — uses only the tri-state phase
    from core.continuum.types import TriStatePhase
    policy = resolve_policy(phase=TriStatePhase.MANIFEST)

    # Full call
    from core.continuum.types import RuntimeDomain
    from core.orchestration_authority import AuthorityRole
    from core.return_intelligence import IDLE_RETURN_SUMMARY

    policy = resolve_policy(
        phase=TriStatePhase.MANIFEST,
        domain=RuntimeDomain.CROSS_DEVICE,
        authority_role=AuthorityRole.AUTHORITATIVE_ENTRYPOINT,
        return_summary=IDLE_RETURN_SUMMARY,
    )
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .policy_band import PolicyBand, BAND_ORDER, band_rank
from .execution_policy import ExecutionPolicy, DEFAULT_CONSERVATIVE_POLICY

logger = logging.getLogger("Galaxy.ExecutionPolicy.Resolver")

__all__ = ["resolve_policy", "RETURN_PRESSURE_FORCE_OBSERVE", "RETURN_PRESSURE_RESTRICT"]

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

#: Return pressure at or above this value forces the band to ``observe_only``.
RETURN_PRESSURE_FORCE_OBSERVE: float = 0.75

#: Return pressure at or above this value restricts action budget and forces
#: confirmation even in permissive bands.
RETURN_PRESSURE_RESTRICT: float = 0.40

# ---------------------------------------------------------------------------
# Budget tables
# ---------------------------------------------------------------------------

#: Maps policy band → (risk_budget, action_budget, fallback_budget)
_BAND_BUDGETS: dict[PolicyBand, tuple[float, int, int]] = {
    PolicyBand.OBSERVE_ONLY:     (0.0, 0, 0),
    PolicyBand.ASSISTIVE:        (0.1, 0, 1),
    PolicyBand.BOUNDED_EXECUTE:  (0.5, 5, 2),
    PolicyBand.FULL_EXECUTE:     (1.0, -1, 3),
}

#: Maps policy band → list of allowed executor level strings.
#: Sourced from :class:`~core.execution_observability.executor_level.ExecutorLevel`.
_BAND_EXECUTOR_LEVELS: dict[PolicyBand, list[str]] = {
    PolicyBand.OBSERVE_ONLY:    [],
    PolicyBand.ASSISTIVE:       ["orchestrator"],
    PolicyBand.BOUNDED_EXECUTE: ["system_api", "uia", "orchestrator"],
    PolicyBand.FULL_EXECUTE:    ["system_api", "uia", "gui", "vlm", "remote_executor", "orchestrator"],
}


# ---------------------------------------------------------------------------
# Return-pressure computation
# ---------------------------------------------------------------------------

def _compute_return_pressure(return_summary: Optional[Any]) -> float:
    """Derive a normalised return-pressure float [0.0, 1.0] from a summary.

    Parameters
    ----------
    return_summary:
        A :class:`~core.return_intelligence.ReturnSummary` instance, a
        compatible dict, or ``None``.

    Returns
    -------
    float
        0.0 when no return is active; increases toward 1.0 with severity.
    """
    if return_summary is None:
        return 0.0
    try:
        if isinstance(return_summary, dict):
            is_returning = bool(return_summary.get("is_returning", False))
            mode_str = str(return_summary.get("return_mode", "none"))
            decay = float(return_summary.get("decay_amount", 0.0))
        else:
            is_returning = bool(getattr(return_summary, "is_returning", False))
            mode_attr = getattr(return_summary, "return_mode", None)
            mode_str = mode_attr.value if hasattr(mode_attr, "value") else str(mode_attr or "none")
            decay = float(getattr(return_summary, "decay_amount", 0.0))

        if not is_returning:
            return 0.0

        _pressure_by_mode = {
            "none":               0.0,
            "hold":               0.05,
            "soft_decay":         0.35 + min(decay, 1.0) * 0.20,
            "step_down":          0.65,
            "return_to_formless": 0.90,
        }
        return _pressure_by_mode.get(mode_str, 0.30)
    except Exception as exc:
        logger.debug("_compute_return_pressure: error reading summary: %s", exc)
        return 0.0


# ---------------------------------------------------------------------------
# Authority-role helpers
# ---------------------------------------------------------------------------

def _is_legacy_or_deprecated_role(authority_role: Optional[Any]) -> bool:
    """Return True if *authority_role* is a legacy or deprecated role."""
    if authority_role is None:
        return False
    try:
        # Accepts either AuthorityRole enum or its string value.
        role_str = authority_role.value if hasattr(authority_role, "value") else str(authority_role)
        return role_str in ("legacy_compatibility", "deprecated")
    except Exception:
        return False


def _is_active_authoritative_role(authority_role: Optional[Any]) -> bool:
    """Return True if *authority_role* is a currently active authority."""
    if authority_role is None:
        return False
    try:
        from core.orchestration_authority import is_authoritative, AuthorityRole
        if isinstance(authority_role, AuthorityRole):
            return is_authoritative(authority_role)
        role_str = authority_role.value if hasattr(authority_role, "value") else str(authority_role)
        try:
            role_enum = AuthorityRole(role_str)
            return is_authoritative(role_enum)
        except ValueError:
            return False
    except ImportError:
        # Graceful degradation if orchestration_authority package is not available
        role_str = authority_role.value if hasattr(authority_role, "value") else str(authority_role)
        return role_str not in ("legacy_compatibility", "deprecated", "unknown")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Band downgrade helper
# ---------------------------------------------------------------------------

def _downgrade_band(band: PolicyBand, steps: int = 1) -> PolicyBand:
    """Return a band that is *steps* levels less permissive than *band*."""
    current_rank = band_rank(band)
    new_rank = max(0, current_rank - steps)
    return BAND_ORDER[new_rank]


# ---------------------------------------------------------------------------
# Primary resolver
# ---------------------------------------------------------------------------

def resolve_policy(
    *,
    phase: Optional[Any] = None,
    domain: Optional[Any] = None,
    authority_role: Optional[Any] = None,
    return_summary: Optional[Any] = None,
    retreat_tendency: Optional[float] = None,
    collapse_tendency: Optional[float] = None,
) -> ExecutionPolicy:
    """Derive an :class:`~core.execution_policy.ExecutionPolicy` from runtime signals.

    All parameters are optional.  The resolver degrades gracefully when signals
    are absent, returning progressively more conservative policies.

    Parameters
    ----------
    phase:
        :class:`~core.continuum.types.TriStatePhase` enum member or its
        string value (``"silent"`` / ``"liminal"`` / ``"manifest"``).
        When ``None`` the resolver defaults to ``observe_only`` band.
    domain:
        :class:`~core.continuum.types.RuntimeDomain` enum member or its
        string value (``"local"`` / ``"cross_device"`` / ``"transition"``).
    authority_role:
        :class:`~core.orchestration_authority.AuthorityRole` enum member or
        its string value.  Legacy/deprecated roles downgrade the band.
    return_summary:
        :class:`~core.return_intelligence.ReturnSummary` instance or a
        compatible dict.  High return pressure overrides the band.
    retreat_tendency:
        Optional float [0.0, 1.0] from :class:`~core.projection.RuntimeProjection`.
        High retreat tendency (>= 0.7) is treated as moderate return pressure.
    collapse_tendency:
        Optional float [0.0, 1.0] from :class:`~core.projection.RuntimeProjection`.
        Informational only in this PR; reserved for future enforcement.

    Returns
    -------
    ExecutionPolicy
        A fully populated, immutable policy object.  Never raises; falls
        back to :data:`~core.execution_policy.DEFAULT_CONSERVATIVE_POLICY`
        on unexpected errors.
    """
    try:
        return _resolve_policy_impl(
            phase=phase,
            domain=domain,
            authority_role=authority_role,
            return_summary=return_summary,
            retreat_tendency=retreat_tendency,
            collapse_tendency=collapse_tendency,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("resolve_policy: unexpected error, returning conservative default: %s", exc)
        return DEFAULT_CONSERVATIVE_POLICY


def _resolve_policy_impl(
    *,
    phase: Optional[Any],
    domain: Optional[Any],
    authority_role: Optional[Any],
    return_summary: Optional[Any],
    retreat_tendency: Optional[float],
    collapse_tendency: Optional[float],  # noqa: ARG001 — reserved
) -> ExecutionPolicy:
    """Internal implementation of the policy resolver."""

    # ---------------------------------------------------------------
    # 0. Normalise input strings to canonical forms
    # ---------------------------------------------------------------
    phase_str: Optional[str] = None
    if phase is not None:
        phase_str = phase.value if hasattr(phase, "value") else str(phase).lower()

    domain_str: Optional[str] = None
    if domain is not None:
        domain_str = domain.value if hasattr(domain, "value") else str(domain).lower()

    authority_str: Optional[str] = None
    if authority_role is not None:
        authority_str = (
            authority_role.value if hasattr(authority_role, "value") else str(authority_role).lower()
        )

    # ---------------------------------------------------------------
    # 1. Compute return pressure (from summary + retreat_tendency)
    # ---------------------------------------------------------------
    pressure = _compute_return_pressure(return_summary)

    # Augment with retreat_tendency if provided
    if retreat_tendency is not None:
        retreat = max(0.0, min(1.0, float(retreat_tendency)))
        if retreat >= 0.7:
            pressure = max(pressure, RETURN_PRESSURE_RESTRICT)
        elif retreat >= 0.5:
            pressure = max(pressure, 0.20)

    # ---------------------------------------------------------------
    # 2. Force observe_only when return pressure is very high
    # ---------------------------------------------------------------
    if pressure >= RETURN_PRESSURE_FORCE_OBSERVE:
        return ExecutionPolicy(
            policy_band=PolicyBand.OBSERVE_ONLY,
            risk_budget=0.0,
            action_budget=0,
            fallback_budget=0,
            allowed_executor_levels=[],
            cross_device_allowed=False,
            requires_confirmation=True,
            reason=(
                f"forced observe_only: return pressure {pressure:.2f} >= "
                f"threshold {RETURN_PRESSURE_FORCE_OBSERVE:.2f}"
            ),
            source_phase=phase_str,
            source_domain=domain_str,
            source_authority_role=authority_str,
            return_pressure=pressure,
        )

    # ---------------------------------------------------------------
    # 3. Determine base band from phase
    # ---------------------------------------------------------------
    _PHASE_TO_BASE_BAND: dict[str, PolicyBand] = {
        "silent":   PolicyBand.OBSERVE_ONLY,
        "liminal":  PolicyBand.ASSISTIVE,
        "manifest": PolicyBand.BOUNDED_EXECUTE,
    }
    band = _PHASE_TO_BASE_BAND.get(phase_str or "", PolicyBand.OBSERVE_ONLY)

    # ---------------------------------------------------------------
    # 4. Domain upgrade: cross_device + manifest → full_execute
    # ---------------------------------------------------------------
    cross_device_allowed = False
    if domain_str == "cross_device" and band is PolicyBand.BOUNDED_EXECUTE:
        band = PolicyBand.FULL_EXECUTE
        cross_device_allowed = True
    elif domain_str == "cross_device" and band is PolicyBand.FULL_EXECUTE:
        cross_device_allowed = True

    # ---------------------------------------------------------------
    # 5. Authority downgrade
    # ---------------------------------------------------------------
    if _is_legacy_or_deprecated_role(authority_role):
        band = _downgrade_band(band, steps=1)
        cross_device_allowed = False
        logger.debug(
            "resolve_policy: legacy/deprecated authority role '%s' — downgraded band to %s",
            authority_str,
            band.value,
        )

    # ---------------------------------------------------------------
    # 6. Apply moderate return pressure restrictions
    # ---------------------------------------------------------------
    requires_confirmation = False
    if pressure >= RETURN_PRESSURE_RESTRICT:
        # Restrict action budget and require confirmation
        requires_confirmation = True
        cross_device_allowed = False
        # Clamp band to bounded_execute at most
        if band is PolicyBand.FULL_EXECUTE:
            band = PolicyBand.BOUNDED_EXECUTE
            cross_device_allowed = False

    # bounded_execute always requires confirmation at band level
    if band is PolicyBand.BOUNDED_EXECUTE and not requires_confirmation:
        requires_confirmation = True

    # ---------------------------------------------------------------
    # 7. Compute budgets from final band
    # ---------------------------------------------------------------
    risk_budget, action_budget, fallback_budget = _BAND_BUDGETS[band]
    executor_levels = list(_BAND_EXECUTOR_LEVELS[band])

    # If return pressure is moderate, halve the action budget
    if pressure >= RETURN_PRESSURE_RESTRICT and action_budget > 0:
        action_budget = max(1, action_budget // 2)

    # ---------------------------------------------------------------
    # 8. Build reason string
    # ---------------------------------------------------------------
    reason_parts: list[str] = []
    if phase_str:
        reason_parts.append(f"phase={phase_str}")
    if domain_str:
        reason_parts.append(f"domain={domain_str}")
    if authority_str:
        reason_parts.append(f"authority={authority_str}")
    if pressure > 0.0:
        reason_parts.append(f"return_pressure={pressure:.2f}")
    reason = f"policy_band={band.value}: " + (", ".join(reason_parts) if reason_parts else "defaults only")

    return ExecutionPolicy(
        policy_band=band,
        risk_budget=risk_budget,
        action_budget=action_budget,
        fallback_budget=fallback_budget,
        allowed_executor_levels=executor_levels,
        cross_device_allowed=cross_device_allowed,
        requires_confirmation=requires_confirmation,
        reason=reason,
        source_phase=phase_str,
        source_domain=domain_str,
        source_authority_role=authority_str,
        return_pressure=pressure,
    )
