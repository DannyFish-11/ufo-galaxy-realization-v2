"""core/execution/readiness_gate.py
=====================================
ExecutionReadinessGate — canonical pre-execution readiness decision layer.

PR-23: Execution Readiness Gate

This module provides the **single authoritative gate** that answers the
pre-execution question:

  - Is the system ready to execute?
  - If not, why not?
  - If yes, does it still require confirmation?
  - Which policy band / readiness reason explains the result?

It composes existing mechanisms instead of replacing them:
  - :func:`~core.execution_policy.resolve_policy` for policy-band evaluation
  - :class:`~core.policy.hitl_policy.HITLPolicy` for HITL gate evaluation
  - :class:`~core.execution.intent_profile.ExecutionIntentProfile` (PR-22)
    for structured intent signals
  - Tri-state / runtime-domain signals from ``state_continuum`` dicts

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — :meth:`ReadinessResult.to_dict` and
  :meth:`ReadinessResult.to_json` produce stable, round-trippable output.
- **Graceful defaults** — all inputs are optional; the gate degrades
  conservatively when signals are unavailable.
- **Composition, not duplication** — delegates policy, HITL, and domain
  checks to the existing modules; never re-implements their logic.

Usage::

    from core.execution.readiness_gate import (
        evaluate_readiness,
        ExecutionReadinessGate,
    )

    result = evaluate_readiness(
        intent_profile=profile,
        state_continuum=continuum_dict,
    )

    if result.ready:
        if result.requires_confirmation:
            # surface confirmation UI
            ...
        else:
            # proceed to execute
            ...
    else:
        # blocked — inspect result.blocked_by / result.reason
        ...

See ``docs/EXECUTION_READINESS_GATE.md`` for the full specification.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Execution.ReadinessGate")


# ---------------------------------------------------------------------------
# ReadinessStatus — canonical status vocabulary
# ---------------------------------------------------------------------------


class ReadinessStatus(str, Enum):
    """Canonical readiness status values.

    These are the only possible top-level answers from the gate.
    """

    READY = "ready"
    """Execution is permitted and no confirmation is required."""

    CONFIRM_REQUIRED = "confirm_required"
    """Execution is permitted but requires human confirmation first."""

    BLOCKED = "blocked"
    """Execution is currently blocked; inspect ``blocked_by`` and ``reason``."""

    OBSERVE_ONLY = "observe_only"
    """The action level or policy band restricts to observe/advisory output only.
    No side-effectful execution is allowed."""


# ---------------------------------------------------------------------------
# BlockedBy — structured block-cause vocabulary
# ---------------------------------------------------------------------------


class BlockedBy(str, Enum):
    """Structured reason codes for a blocked or restricted readiness result.

    Multiple causes may apply; the gate records the *primary* blocking cause
    in :attr:`ReadinessResult.blocked_by` and additional context in
    :attr:`ReadinessResult.notes`.
    """

    POLICY = "policy"
    """Blocked by execution policy (policy_band / band guardrails)."""

    HITL = "hitl"
    """Blocked or gated by the Human-in-the-Loop policy."""

    RUNTIME_PHASE = "runtime_phase"
    """Blocked because the current tri-state phase does not permit execution."""

    DOMAIN = "domain"
    """Blocked due to incompatible runtime domain (e.g. cross-device disallowed)."""

    MISSING_TARGET = "missing_target"
    """Blocked because no valid execution target was resolved."""

    MISSING_INTENT = "missing_intent"
    """Blocked because no execution intent profile is available."""

    ACTION_LEVEL = "action_level"
    """Blocked because the action level (observe / hint) does not permit execution."""

    CONFIRMATION_REQUIRED = "confirmation_required"
    """Not blocked outright; confirmation is required before proceeding."""

    NONE = "none"
    """Not blocked — execution is permitted (possibly with confirmation)."""


# ---------------------------------------------------------------------------
# ReadinessResult — canonical readiness contract
# ---------------------------------------------------------------------------


class ReadinessResult(BaseModel):
    """Canonical, serialisable readiness decision object.

    Produced by :class:`ExecutionReadinessGate` or the module-level
    :func:`evaluate_readiness` helper.

    Fields
    ------
    ready
        ``True`` when execution is permitted (may still require confirmation).
        ``False`` when execution is blocked.
    status
        Top-level :class:`ReadinessStatus` (``ready``, ``confirm_required``,
        ``blocked``, or ``observe_only``).
    reason
        Human-readable explanation of the readiness decision.
    requires_confirmation
        ``True`` when execution is permitted but a human confirmation step
        must be completed first.
    policy_band
        Normalised policy-band string from the execution-policy resolver
        (``"observe_only"`` / ``"assistive"`` / ``"bounded_execute"`` /
        ``"full_execute"``).  ``None`` when the resolver was unavailable.
    blocked_by
        Primary block-cause code (:class:`BlockedBy` value string).
        ``"none"`` when not blocked.
    runtime_session_id
        Active runtime/OpenClawd session ID.  ``None`` when unavailable.
    intent_id
        ID of the :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        that was evaluated.  ``None`` when no intent profile was available.
    action_level
        Action level from the intent profile
        (``"observe"`` / ``"hint"`` / ``"assist"`` / ``"execute"``).
    runtime_domain
        Runtime domain string (``"local"`` / ``"cross_device"`` / ``"transition"``).
        ``None`` when unavailable.
    notes
        Optional list of additional context strings.  May contain secondary
        block causes, policy resolver diagnostics, or debug hints.
    """

    ready: bool = Field(
        default=False,
        description="True when execution is permitted (may still require confirmation).",
    )
    status: str = Field(
        default=ReadinessStatus.BLOCKED.value,
        description="Top-level readiness status (ready / confirm_required / blocked / observe_only).",
    )
    reason: str = Field(
        default="",
        description="Human-readable explanation of the readiness decision.",
    )
    requires_confirmation: bool = Field(
        default=False,
        description="True when execution requires a human confirmation step before proceeding.",
    )
    policy_band: Optional[str] = Field(
        default=None,
        description="Policy band from the execution-policy resolver.",
    )
    blocked_by: str = Field(
        default=BlockedBy.NONE.value,
        description="Primary block-cause code (none when not blocked).",
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Active runtime/OpenClawd session ID.",
    )
    intent_id: Optional[str] = Field(
        default=None,
        description="ID of the ExecutionIntentProfile that was evaluated.",
    )
    action_level: str = Field(
        default="observe",
        description="Action level from the intent profile.",
    )
    runtime_domain: Optional[str] = Field(
        default=None,
        description="Runtime domain (local / cross_device / transition).",
    )
    notes: List[str] = Field(
        default_factory=list,
        description="Optional additional context strings.",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    def governance_summary(self) -> Dict[str, Any]:
        """Return a compact, projection-safe governance summary.

        Suitable for inclusion in runtime governance surfaces or projection
        assembly without bloating the full schema.
        """
        return {
            "ready": self.ready,
            "status": self.status,
            "requires_confirmation": self.requires_confirmation,
            "policy_band": self.policy_band,
            "blocked_by": self.blocked_by,
            "action_level": self.action_level,
            "intent_id": self.intent_id,
        }


# ---------------------------------------------------------------------------
# ExecutionReadinessGate
# ---------------------------------------------------------------------------


class ExecutionReadinessGate:
    """Canonical pre-execution readiness gate.

    Composes the execution-policy resolver, HITL policy, and intent-profile
    signals into a single :class:`ReadinessResult`.

    Parameters
    ----------
    policy_resolver_fn :
        Optional callable overriding the default
        :func:`~core.execution_policy.resolve_policy`.  Primarily for testing.
    hitl_policy_fn :
        Optional callable returning a :class:`~core.policy.hitl_policy.HITLPolicy`
        instance.  Overrides :func:`~core.policy.hitl_policy.get_hitl_policy`.
        Primarily for testing.
    """

    def __init__(
        self,
        *,
        policy_resolver_fn: Optional[Any] = None,
        hitl_policy_fn: Optional[Any] = None,
    ) -> None:
        self._policy_resolver_fn = policy_resolver_fn
        self._hitl_policy_fn = hitl_policy_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        intent_profile: Optional[Any] = None,
        *,
        state_continuum: Optional[Dict[str, Any]] = None,
        action_level: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
        require_target: bool = False,
        target_ref: Optional[str] = None,
        runtime_domain: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ReadinessResult:
        """Evaluate execution readiness.

        Accepts an optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        and/or a ``state_continuum`` dict.  When both are provided the intent
        profile takes precedence for structured fields; the continuum dict is
        used to extract policy signals (phase, domain, return pressure) via the
        resolver.

        Parameters
        ----------
        intent_profile :
            :class:`~core.execution.intent_profile.ExecutionIntentProfile`
            built by PR-22 machinery.  ``None`` is safe — signals degrade
            gracefully.
        state_continuum :
            Serialised ``ContinuumState`` dict.  Used to feed the
            execution-policy resolver.  ``None`` is safe.
        action_level :
            Explicit override for ``action_level``.  When provided this takes
            precedence over the value in *intent_profile*.
        runtime_session_id :
            Explicit session-ID override.  When ``None`` the value is taken
            from *intent_profile* when available.
        require_target :
            When ``True`` the gate treats a missing ``target_ref`` as a block
            condition.  Defaults to ``False`` (non-execute action levels do not
            require a target).
        target_ref :
            Explicit target-ref override.  When ``None`` the value is taken
            from *intent_profile*.
        runtime_domain :
            Explicit domain override.  When ``None`` the value is taken from
            *intent_profile* or *state_continuum*.
        notes :
            Optional context note attached to the result.

        Returns
        -------
        ReadinessResult
            Always returns a valid result; never raises.
        """
        try:
            return self._evaluate_impl(
                intent_profile=intent_profile,
                state_continuum=state_continuum,
                action_level=action_level,
                runtime_session_id=runtime_session_id,
                require_target=require_target,
                target_ref=target_ref,
                runtime_domain=runtime_domain,
                notes=notes,
            )
        except Exception as exc:
            logger.warning("ExecutionReadinessGate.evaluate failed (safe fallback): %s", exc)
            return _make_blocked_result(
                reason=f"readiness_gate_internal_error: {exc}",
                blocked_by=BlockedBy.POLICY,
                notes=[str(exc)] + ([notes] if notes else []),
            )

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _evaluate_impl(
        self,
        intent_profile: Optional[Any],
        *,
        state_continuum: Optional[Dict[str, Any]],
        action_level: Optional[str],
        runtime_session_id: Optional[str],
        require_target: bool,
        target_ref: Optional[str],
        runtime_domain: Optional[str],
        notes: Optional[str],
    ) -> ReadinessResult:
        extra_notes: List[str] = []
        if notes:
            extra_notes.append(notes)

        # ----------------------------------------------------------------
        # 1. Extract signals from intent_profile (PR-22)
        # ----------------------------------------------------------------
        _action_level, _target_ref, _session_id, _domain, _intent_id = (
            _extract_intent_signals(intent_profile)
        )

        # Explicit overrides take precedence
        eff_action_level: str = action_level or _action_level or "observe"
        eff_target_ref: Optional[str] = target_ref or _target_ref
        eff_session_id: Optional[str] = runtime_session_id or _session_id
        eff_intent_id: Optional[str] = _intent_id

        # ----------------------------------------------------------------
        # 2. Extract domain from state_continuum (fallback)
        # ----------------------------------------------------------------
        eff_domain: Optional[str] = runtime_domain or _domain
        if eff_domain is None and state_continuum:
            eff_domain = _extract_domain_from_continuum(state_continuum)

        # ----------------------------------------------------------------
        # 3. Missing intent guard — must precede action_level check so that
        #    "no profile + no explicit action_level" → missing_intent rather
        #    than observe_only (which would mask the true cause).
        # ----------------------------------------------------------------
        if intent_profile is None and action_level is None:
            extra_notes.append("no intent_profile and no explicit action_level")
            return _make_blocked_result(
                reason="no execution intent available",
                blocked_by=BlockedBy.MISSING_INTENT,
                session_id=eff_session_id,
                intent_id=eff_intent_id,
                action_level=eff_action_level,
                domain=eff_domain,
                notes=extra_notes,
            )

        # ----------------------------------------------------------------
        # 4. Check action_level — observe/hint → observe_only
        # ----------------------------------------------------------------
        if eff_action_level in ("observe", "hint"):
            return ReadinessResult(
                ready=False,
                status=ReadinessStatus.OBSERVE_ONLY.value,
                reason=(
                    f"action_level='{eff_action_level}' does not permit "
                    "side-effectful execution"
                ),
                requires_confirmation=False,
                blocked_by=BlockedBy.ACTION_LEVEL.value,
                policy_band=None,
                runtime_session_id=eff_session_id,
                intent_id=eff_intent_id,
                action_level=eff_action_level,
                runtime_domain=eff_domain,
                notes=extra_notes,
            )

        # ----------------------------------------------------------------
        # 5. Missing target guard (optional — only when require_target=True)
        # ----------------------------------------------------------------
        if require_target and not eff_target_ref:
            return _make_blocked_result(
                reason="execution target is required but was not resolved",
                blocked_by=BlockedBy.MISSING_TARGET,
                session_id=eff_session_id,
                intent_id=eff_intent_id,
                action_level=eff_action_level,
                domain=eff_domain,
                notes=extra_notes,
            )

        # ----------------------------------------------------------------
        # 6. Resolve execution policy
        # ----------------------------------------------------------------
        policy = self._resolve_policy(state_continuum, extra_notes)
        policy_band_str: Optional[str] = (
            policy.policy_band.value if policy is not None else None
        )

        # ----------------------------------------------------------------
        # 7. Policy-band gate
        # ----------------------------------------------------------------
        if policy is not None:
            from core.execution_policy.policy_band import band_allows_execution  # noqa: PLC0415
            if not band_allows_execution(policy.policy_band):
                return ReadinessResult(
                    ready=False,
                    status=ReadinessStatus.BLOCKED.value,
                    reason=(
                        f"execution blocked by policy band '{policy.policy_band.value}': "
                        + policy.reason
                    ),
                    requires_confirmation=False,
                    policy_band=policy_band_str,
                    blocked_by=BlockedBy.POLICY.value,
                    runtime_session_id=eff_session_id,
                    intent_id=eff_intent_id,
                    action_level=eff_action_level,
                    runtime_domain=eff_domain,
                    notes=extra_notes,
                )

        # ----------------------------------------------------------------
        # 8. HITL gate
        # ----------------------------------------------------------------
        hitl_result = self._evaluate_hitl(
            action=eff_action_level,
            context={
                "target_ref": eff_target_ref,
                "intent_id": eff_intent_id,
                "policy_band": policy_band_str,
                "runtime_domain": eff_domain,
            },
            session_id=eff_session_id,
        )
        if hitl_result.get("blocked"):
            return ReadinessResult(
                ready=False,
                status=ReadinessStatus.BLOCKED.value,
                reason=hitl_result.get("reason", "blocked by HITL policy"),
                requires_confirmation=False,
                policy_band=policy_band_str,
                blocked_by=BlockedBy.HITL.value,
                runtime_session_id=eff_session_id,
                intent_id=eff_intent_id,
                action_level=eff_action_level,
                runtime_domain=eff_domain,
                notes=extra_notes,
            )

        # ----------------------------------------------------------------
        # 9. Confirmation gate — policy requires_confirmation or HITL pending
        # ----------------------------------------------------------------
        requires_confirmation = bool(
            (policy is not None and policy.requires_confirmation)
            or hitl_result.get("requires_confirmation", False)
        )

        if requires_confirmation:
            confirm_notes = list(extra_notes)
            if policy is not None and policy.requires_confirmation:
                confirm_notes.append(f"policy.requires_confirmation=True (band={policy_band_str})")
            if hitl_result.get("requires_confirmation"):
                confirm_notes.append("hitl.requires_confirmation=True")
            return ReadinessResult(
                ready=True,
                status=ReadinessStatus.CONFIRM_REQUIRED.value,
                reason="execution permitted but requires human confirmation",
                requires_confirmation=True,
                policy_band=policy_band_str,
                blocked_by=BlockedBy.CONFIRMATION_REQUIRED.value,
                runtime_session_id=eff_session_id,
                intent_id=eff_intent_id,
                action_level=eff_action_level,
                runtime_domain=eff_domain,
                notes=confirm_notes,
            )

        # ----------------------------------------------------------------
        # 10. Ready — all gates passed
        # ----------------------------------------------------------------
        return ReadinessResult(
            ready=True,
            status=ReadinessStatus.READY.value,
            reason="execution is ready; all readiness gates passed",
            requires_confirmation=False,
            policy_band=policy_band_str,
            blocked_by=BlockedBy.NONE.value,
            runtime_session_id=eff_session_id,
            intent_id=eff_intent_id,
            action_level=eff_action_level,
            runtime_domain=eff_domain,
            notes=extra_notes,
        )

    # ------------------------------------------------------------------
    # Policy resolution (composed, not duplicated)
    # ------------------------------------------------------------------

    def _resolve_policy(
        self,
        state_continuum: Optional[Dict[str, Any]],
        notes: List[str],
    ) -> Optional[Any]:
        """Delegate to the execution-policy resolver.  Returns ``None`` on error."""
        try:
            if self._policy_resolver_fn is not None:
                return self._policy_resolver_fn(state_continuum)
            from core.execution_policy import resolve_policy  # noqa: PLC0415
            if state_continuum:
                phase = state_continuum.get("phase") or state_continuum.get("tri_state_phase")
                domain = state_continuum.get("runtime_domain")
                return resolve_policy(phase=phase, domain=domain)
            return resolve_policy()
        except Exception as exc:
            logger.debug("ReadinessGate: policy resolver unavailable — %s", exc)
            notes.append(f"policy_resolver_unavailable: {exc}")
            return None

    # ------------------------------------------------------------------
    # HITL evaluation (composed, not duplicated)
    # ------------------------------------------------------------------

    def _evaluate_hitl(
        self,
        action: str,
        context: Dict[str, Any],
        session_id: Optional[str],
    ) -> Dict[str, Any]:
        """Delegate to the HITL policy gate.  Returns safe defaults on error."""
        try:
            if self._hitl_policy_fn is not None:
                hitl_policy = self._hitl_policy_fn()
            else:
                from core.policy.hitl_policy import get_hitl_policy  # noqa: PLC0415
                hitl_policy = get_hitl_policy()

            from core.policy.hitl_policy import HITLMode, HITLDecisionOutcome  # noqa: PLC0415
            decision = hitl_policy.evaluate(
                action=action,
                context=context,
                session_id=session_id,
            )

            # Explicit rejection → blocked outright
            if decision.outcome is HITLDecisionOutcome.REJECTED:
                return {
                    "blocked": True,
                    "requires_confirmation": False,
                    "reason": f"HITL rejected action '{action}': {decision.reason}",
                }

            # MANUAL mode → always surface confirmation requirement so that
            # callers are aware a human review step is expected.
            if hitl_policy.mode is HITLMode.MANUAL:
                return {
                    "blocked": False,
                    "requires_confirmation": True,
                    "reason": "HITL mode=manual requires human confirmation",
                }

            # SEMI mode + bounded_execute band → recommend confirmation for
            # high-risk or constrained-budget execution paths.
            if (
                hitl_policy.mode is HITLMode.SEMI
                and context.get("policy_band") == "bounded_execute"
            ):
                return {
                    "blocked": False,
                    "requires_confirmation": True,
                    "reason": "HITL mode=semi + bounded_execute band requires confirmation",
                }

            return {
                "blocked": False,
                "requires_confirmation": False,
                "reason": "hitl_approved",
            }
        except Exception as exc:
            logger.debug("ReadinessGate: HITL unavailable — %s", exc)
            return {
                "blocked": False,
                "requires_confirmation": False,
                "reason": "hitl_unavailable",
            }


# ---------------------------------------------------------------------------
# Module-level convenience function (preferred public API)
# ---------------------------------------------------------------------------

_default_gate: Optional[ExecutionReadinessGate] = None


def evaluate_readiness(
    intent_profile: Optional[Any] = None,
    *,
    state_continuum: Optional[Dict[str, Any]] = None,
    action_level: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    require_target: bool = False,
    target_ref: Optional[str] = None,
    runtime_domain: Optional[str] = None,
    notes: Optional[str] = None,
) -> ReadinessResult:
    """Evaluate execution readiness using the process-level gate singleton.

    This is the **preferred entry-point** for callers that want a quick
    readiness check without managing a gate instance.

    Parameters
    ----------
    intent_profile :
        Optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        from PR-22.
    state_continuum :
        Serialised ``ContinuumState`` dict.
    action_level :
        Explicit action-level override.
    runtime_session_id :
        Explicit session-ID override.
    require_target :
        When ``True`` the gate blocks when no target is resolved.
    target_ref :
        Explicit target-ref override.
    runtime_domain :
        Explicit domain override.
    notes :
        Optional context note.

    Returns
    -------
    ReadinessResult
        Always returns a valid result; never raises.
    """
    global _default_gate
    if _default_gate is None:
        _default_gate = ExecutionReadinessGate()
    return _default_gate.evaluate(
        intent_profile,
        state_continuum=state_continuum,
        action_level=action_level,
        runtime_session_id=runtime_session_id,
        require_target=require_target,
        target_ref=target_ref,
        runtime_domain=runtime_domain,
        notes=notes,
    )


def reset_readiness_gate() -> None:
    """Reset the process-level gate singleton (intended for tests only)."""
    global _default_gate
    _default_gate = None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_intent_signals(
    intent_profile: Optional[Any],
) -> tuple:
    """Extract key signals from an intent profile.

    Returns (action_level, target_ref, session_id, domain, intent_id).
    All values may be None or default strings.
    """
    if intent_profile is None:
        return ("observe", None, None, None, None)
    try:
        return (
            getattr(intent_profile, "action_level", "observe") or "observe",
            getattr(intent_profile, "target_ref", None),
            getattr(intent_profile, "runtime_session_id", None),
            getattr(intent_profile, "runtime_domain", None),
            getattr(intent_profile, "intent_id", None),
        )
    except Exception:
        return ("observe", None, None, None, None)


def _extract_domain_from_continuum(state_continuum: Dict[str, Any]) -> Optional[str]:
    """Extract runtime_domain from a continuum dict."""
    try:
        domain = state_continuum.get("runtime_domain")
        return str(domain) if domain else None
    except Exception:
        return None


def _make_blocked_result(
    reason: str,
    blocked_by: BlockedBy,
    *,
    session_id: Optional[str] = None,
    intent_id: Optional[str] = None,
    action_level: str = "observe",
    domain: Optional[str] = None,
    notes: Optional[List[str]] = None,
) -> ReadinessResult:
    """Construct a blocked :class:`ReadinessResult`."""
    return ReadinessResult(
        ready=False,
        status=ReadinessStatus.BLOCKED.value,
        reason=reason,
        requires_confirmation=False,
        policy_band=None,
        blocked_by=blocked_by.value,
        runtime_session_id=session_id,
        intent_id=intent_id,
        action_level=action_level,
        runtime_domain=domain,
        notes=notes or [],
    )
