"""core/source_execution_eligibility.py
=========================================
PR-2 (post-533 dual-repo runtime host unification track):
Source Execution Eligibility — posture-aware dispatch authority.

This module is the canonical authority for determining whether the **source
device** is eligible to participate as a runtime executor based on its
declared :data:`source_runtime_posture`.

Semantics
---------
``control_only``
    The source device acts as controller/observer only.  It dispatches
    commands, monitors progress, and receives results, but contributes **no
    local execution resources** for the current task.  The source device is
    therefore **excluded from the execution pool** unless an explicit
    canonical exception is granted by the caller.

``join_runtime``
    The source device actively joins the runtime as an execution participant.
    It may receive sub-tasks, produce results, or co-execute with a target
    device.  The source device is **eligible** for local execution if it is
    otherwise available.

Design principles
-----------------
- **Additive only** — does not modify existing modules directly; callers opt
  in by importing and calling the helpers provided here.
- **Graceful degradation** — unknown or ``None`` posture values are resolved
  to ``control_only`` (the safe conservative default).
- **Policy-sentinel anchored** — every behavioral policy is documented via a
  string sentinel so audit and observability layers can reference it.

Public surface
--------------
:data:`SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY`
    Module-level authority sentinel.

:data:`CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY`
    Policy: a ``control_only`` source device must not run local execution.

:data:`JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY`
    Policy: a ``join_runtime`` source device may run local execution.

:data:`POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL`
    Integration sentinel confirming PR-2 posture-aware dispatch is active.

:class:`SourceExecutionEligibility`
    Result dataclass carrying ``eligible``, ``posture``, and ``reason``.

:func:`check_source_execution_eligibility`
    Primary API: returns a :class:`SourceExecutionEligibility` for a given
    posture hint.

:func:`is_source_eligible_for_local_execution`
    Convenience bool shorthand.
"""

from __future__ import annotations

import dataclasses
from typing import Optional

__all__ = [
    # Authority sentinels
    "SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY",
    "CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY",
    "JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY",
    "POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL",
    "POSTURE_GATED_LOCAL_EXECUTION_POLICY",
    # PR-2 coordination-role alignment sentinels
    "OBSERVER_ONLY_ROLE_BLOCKS_EXECUTION_POLICY",
    "COORDINATION_ROLE_ALIGNED_DISPATCH_SENTINEL",
    # Data types
    "SourceExecutionEligibility",
    # Functions
    "check_source_execution_eligibility",
    "is_source_eligible_for_local_execution",
    "resolve_posture_for_eligibility",
    # PR-2 coordination-role alignment
    "check_source_eligibility_with_coordination_role",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY: str = (
    "SOURCE_EXECUTION_ELIGIBILITY::POSTURE_AWARE_DISPATCH_AUTHORITY_V1: "
    "core.source_execution_eligibility is the canonical authority for "
    "posture-based source execution eligibility.  "
    "PR-2, post-533 dual-repo runtime host unification track."
)
"""Sentinel: this module owns posture-driven source execution eligibility."""

CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY: str = (
    "SOURCE_EXECUTION_ELIGIBILITY::CONTROL_ONLY_INELIGIBLE_POLICY_V1: "
    "A source device with posture='control_only' MUST NOT be included in "
    "the local execution pool.  It may only dispatch, observe, and receive "
    "results.  Local execution on the source device is gated off unless an "
    "explicit canonical exception is registered by the caller."
)
"""Policy: control_only source is excluded from local execution."""

JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY: str = (
    "SOURCE_EXECUTION_ELIGIBILITY::JOIN_RUNTIME_ELIGIBLE_POLICY_V1: "
    "A source device with posture='join_runtime' MAY participate as a "
    "local execution host if it is otherwise available.  The posture alone "
    "does not gate execution; standard availability/capability checks still "
    "apply."
)
"""Policy: join_runtime source may execute locally if otherwise eligible."""

POSTURE_GATED_LOCAL_EXECUTION_POLICY: str = (
    "SOURCE_EXECUTION_ELIGIBILITY::POSTURE_GATED_LOCAL_EXECUTION_V1: "
    "Local execution on the source device is gated by source_runtime_posture. "
    "Callers MUST query check_source_execution_eligibility() before running "
    "source-side local execution in any posture-aware dispatch path."
)
"""Policy: all posture-aware dispatch paths must query eligibility first."""

POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL: str = (
    "SOURCE_EXECUTION_ELIGIBILITY::PR2_POSTURE_AWARE_DISPATCH_INTEGRATED_V1: "
    "PR-2 post-533 posture-aware dispatch is active.  "
    "source_runtime_posture now drives source execution eligibility in "
    "core.runtime.source_dispatch_orchestrator, galaxy_gateway.device_router, "
    "and core.openclawd dispatch paths."
)
"""Integration sentinel: PR-2 posture-aware dispatch is live."""

OBSERVER_ONLY_ROLE_BLOCKS_EXECUTION_POLICY: str = (
    "SOURCE_EXECUTION_ELIGIBILITY::OBSERVER_ONLY_BLOCKS_EXECUTION_V1: "
    "A device assigned the 'observer_only' coordination role (PR-538) MUST NOT "
    "participate in local execution regardless of its declared "
    "source_runtime_posture.  The coordination role overrides posture for "
    "execution eligibility when the role is definitively observer_only."
)
"""Policy: observer_only coordination role overrides join_runtime posture."""

COORDINATION_ROLE_ALIGNED_DISPATCH_SENTINEL: str = (
    "SOURCE_EXECUTION_ELIGIBILITY::PR2_COORDINATION_ROLE_ALIGNED_DISPATCH_V1: "
    "PR-2 posture-aware dispatch is aligned with the PR-538 coordination-role "
    "model.  check_source_eligibility_with_coordination_role() combines posture "
    "and coordination role to produce a canonical eligibility outcome: "
    "observer_only blocks execution; joined_runtime_participant permits it; "
    "source_controller defers to posture; unresolved/None defers to posture."
)
"""Sentinel: coordination-role-aligned dispatch eligibility is active."""

# ---------------------------------------------------------------------------
# Canonical posture values
# ---------------------------------------------------------------------------

_CONTROL_ONLY: str = "control_only"
_JOIN_RUNTIME: str = "join_runtime"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SourceExecutionEligibility:
    """Result of a posture-based execution eligibility check.

    Attributes
    ----------
    eligible:
        ``True`` when the source device may participate in local execution;
        ``False`` when it must not.
    posture:
        The normalised posture value used to derive the eligibility result.
        Always one of ``"control_only"`` or ``"join_runtime"``.
    reason:
        Human-readable explanation of the eligibility decision.
    """

    eligible: bool
    posture: str
    reason: str

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of this eligibility result."""
        return {
            "eligible": self.eligible,
            "posture": self.posture,
            "reason": self.reason,
            "authority": SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def resolve_posture_for_eligibility(posture_hint: Optional[str]) -> str:
    """Normalise a raw posture hint to a canonical posture value.

    Parameters
    ----------
    posture_hint:
        Raw posture string, possibly ``None``, mixed-case, or unknown.

    Returns
    -------
    str
        Either ``"join_runtime"`` or ``"control_only"`` (the conservative
        safe default for any unrecognised or absent value).
    """
    if not posture_hint:
        return _CONTROL_ONLY
    normalised = str(posture_hint).strip().lower()
    if normalised == _JOIN_RUNTIME:
        return _JOIN_RUNTIME
    return _CONTROL_ONLY


def check_source_execution_eligibility(
    posture_hint: Optional[str],
) -> SourceExecutionEligibility:
    """Determine whether the source device is eligible for local execution.

    This is the **primary API** for posture-aware dispatch eligibility checks.
    It should be called by any code that is about to run local execution on
    behalf of the source device and needs to honour the posture contract
    established by PR-533 / PR-1.

    Parameters
    ----------
    posture_hint:
        The raw ``source_runtime_posture`` value from the request context.
        ``None`` or unknown values default to ``"control_only"``.

    Returns
    -------
    SourceExecutionEligibility
        Carries ``eligible``, the normalised ``posture``, and a ``reason``.

    Examples
    --------
    >>> result = check_source_execution_eligibility("control_only")
    >>> result.eligible
    False

    >>> result = check_source_execution_eligibility("join_runtime")
    >>> result.eligible
    True

    >>> result = check_source_execution_eligibility(None)  # safe default
    >>> result.eligible
    False
    """
    posture = resolve_posture_for_eligibility(posture_hint)

    if posture == _JOIN_RUNTIME:
        return SourceExecutionEligibility(
            eligible=True,
            posture=posture,
            reason=(
                "posture=join_runtime: source device may participate in "
                "local execution if otherwise available. "
                f"Policy: {JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY}"
            ),
        )

    # control_only (including all fallback cases)
    return SourceExecutionEligibility(
        eligible=False,
        posture=posture,
        reason=(
            "posture=control_only: source device is excluded from local "
            "execution pool.  It may only dispatch, observe, and receive "
            "results. "
            f"Policy: {CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY}"
        ),
    )


def is_source_eligible_for_local_execution(posture_hint: Optional[str]) -> bool:
    """Convenience shorthand — returns ``True`` when source may run locally.

    Equivalent to ``check_source_execution_eligibility(posture_hint).eligible``.

    Parameters
    ----------
    posture_hint:
        Raw ``source_runtime_posture`` value.

    Returns
    -------
    bool
        ``True`` for ``join_runtime``; ``False`` for ``control_only`` and all
        fallback / unknown values.
    """
    return check_source_execution_eligibility(posture_hint).eligible


# ---------------------------------------------------------------------------
# PR-2 coordination-role alignment — check_source_eligibility_with_coordination_role
# ---------------------------------------------------------------------------

# Canonical coordination role string values (mirrors CoordinationRole enum
# from core.multi_device_coordination_authority, kept as literals here to
# avoid a hard import cycle and keep this module self-contained).
_ROLE_OBSERVER_ONLY: str = "observer_only"
_ROLE_JOINED_RUNTIME_PARTICIPANT: str = "joined_runtime_participant"
_ROLE_SOURCE_CONTROLLER: str = "source_controller"
_ROLE_TARGET_ONLY_EXECUTOR: str = "target_only_executor"
_ROLE_UNRESOLVED: str = "unresolved"


def check_source_eligibility_with_coordination_role(
    posture_hint: Optional[str],
    coordination_role: Optional[str] = None,
) -> SourceExecutionEligibility:
    """Posture + coordination-role aware eligibility check (PR-2 alignment).

    This function extends :func:`check_source_execution_eligibility` with
    awareness of the canonical coordination roles introduced by PR-538
    (``core.multi_device_coordination_authority``).  When a coordination role
    is supplied it takes precedence over posture for certain role assignments,
    ensuring that dispatch eligibility is consistent with both the posture
    contract (PR-533 / PR-1) and the authority/role model (PR-538).

    Derivation rules (applied in priority order):

    1. **observer_only** — always ineligible regardless of posture.  The
       coordination role explicitly assigns observer-only authority; local
       execution would violate that constraint.
    2. **joined_runtime_participant** — always eligible.  This role is only
       assigned when posture is ``join_runtime``; eligibility is guaranteed by
       the role itself.
    3. **source_controller** — defers to posture (``control_only`` →
       ineligible, ``join_runtime`` → eligible).
    4. **target_only_executor** — eligible (pure execution authority; posture
       does not restrict a target-only device from running locally).
    5. **unresolved / None / unknown** — defers to posture alone (same as
       :func:`check_source_execution_eligibility`).

    Parameters
    ----------
    posture_hint:
        Raw ``source_runtime_posture`` value (may be ``None``).
    coordination_role:
        String value of the device's canonical coordination role, e.g.
        ``"observer_only"``, ``"joined_runtime_participant"``.  ``None`` or
        unrecognised values cause the function to fall back to posture alone.

    Returns
    -------
    SourceExecutionEligibility
        Carries ``eligible``, the normalised ``posture``, and a ``reason``
        that identifies which rule was applied.

    Examples
    --------
    >>> r = check_source_eligibility_with_coordination_role(
    ...     "join_runtime", "observer_only"
    ... )
    >>> r.eligible  # coordination role overrides posture
    False

    >>> r = check_source_eligibility_with_coordination_role(
    ...     "control_only", "joined_runtime_participant"
    ... )
    >>> r.eligible  # role grants eligibility
    True

    >>> r = check_source_eligibility_with_coordination_role("join_runtime", None)
    >>> r.eligible  # no role → posture alone
    True
    """
    posture = resolve_posture_for_eligibility(posture_hint)

    # Normalise the coordination_role string so we do a clean comparison.
    role: Optional[str] = (
        str(coordination_role).strip().lower() if coordination_role else None
    )

    # Rule 1: observer_only → always ineligible.
    if role == _ROLE_OBSERVER_ONLY:
        return SourceExecutionEligibility(
            eligible=False,
            posture=posture,
            reason=(
                "coordination_role=observer_only: source device has no "
                "execution authority and is excluded from local execution "
                "regardless of declared posture.  "
                f"Policy: {OBSERVER_ONLY_ROLE_BLOCKS_EXECUTION_POLICY}"
            ),
        )

    # Rule 2: joined_runtime_participant → always eligible.
    if role == _ROLE_JOINED_RUNTIME_PARTICIPANT:
        return SourceExecutionEligibility(
            eligible=True,
            posture=posture,
            reason=(
                "coordination_role=joined_runtime_participant: source device "
                "is a confirmed runtime participant and is eligible for local "
                "execution.  "
                f"Policy: {JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY}"
            ),
        )

    # Rule 3: source_controller → defer to posture.
    if role == _ROLE_SOURCE_CONTROLLER:
        base = check_source_execution_eligibility(posture_hint)
        return SourceExecutionEligibility(
            eligible=base.eligible,
            posture=base.posture,
            reason=(
                f"coordination_role=source_controller: eligibility deferred "
                f"to posture.  {base.reason}"
            ),
        )

    # Rule 4: target_only_executor → eligible (pure execution device).
    if role == _ROLE_TARGET_ONLY_EXECUTOR:
        return SourceExecutionEligibility(
            eligible=True,
            posture=posture,
            reason=(
                "coordination_role=target_only_executor: device is designated "
                "as a pure execution target and is eligible for local "
                "execution.  "
                f"Policy: {JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY}"
            ),
        )

    # Rule 5: unresolved / None / unknown → fall back to posture alone.
    return check_source_execution_eligibility(posture_hint)
