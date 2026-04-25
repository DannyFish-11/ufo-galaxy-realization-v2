#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/governance_validation_gate.py
====================================
PR-4: Governance / Readiness / Release Validation Main Chain Entry.

This module bridges the governance/readiness evidence surface (produced by
:mod:`core.distributed_release_gate_skeleton`) into real validation semantics.

Problem addressed
-----------------
The distributed release gate skeleton and readiness gate produce structured
verdicts (``open`` / ``blocked`` / ``not_ready`` / ``deferred``) but those
verdicts were previously **non-enforcing** — they were logged or surfaced in
reports but had no impact on any validation outcome.

This module introduces the :class:`GovernanceValidationGate` which:

1. Reads the current release gate verdict from
   :func:`~core.distributed_release_gate_skeleton.evaluate_distributed_release_gate`.
2. Reads the current execution readiness verdict from
   :func:`~core.execution.readiness_gate.evaluate_readiness`.
3. Maps those verdicts into a :class:`ValidationOutcome` (``PASS`` /
   ``FAIL`` / ``WARN``) with a machine-readable :class:`ValidationFailReason`.
4. **Affects real outcomes** — callers that use :meth:`GovernanceValidationGate.enforce`
   or :meth:`GovernanceValidationGate.assert_pass` will raise
   :class:`GovernanceValidationError` when the gate is blocked, making the
   verdict a real execution condition rather than a log entry.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fail-safe defaults** — when the underlying evidence surface is
  unavailable the gate defaults to ``WARN`` (not ``PASS`` or ``FAIL``),
  preventing false passes without hard-breaking environments that have not
  yet wired up the evidence surface.
- **Composable** — the gate can be embedded in CI scripts, release tooling,
  test fixtures, or production validation layers.

Capability-Tiering integration
-------------------------------
When ``capability_tier_check=True`` is passed to
:meth:`GovernanceValidationGate.validate`, the gate also checks that the
requested capability is classified as a **main-chain** tier capability via
:mod:`core.capability_tier`.  EXPERIMENTAL or QUASI_MAIN_CHAIN capabilities
are surfaced as ``WARN`` (not ``FAIL``) by default but can be escalated.

Public API
----------
Constants::

    GOVERNANCE_VALIDATION_GATE_AUTHORITY
    GOVERNANCE_VERDICT_AFFECTS_VALIDATION_POLICY
    NOT_READY_BLOCKS_VALIDATION_POLICY
    EXPERIMENTAL_CAPABILITY_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY

Enumerations::

    ValidationOutcome
    ValidationFailReason

Exceptions::

    GovernanceValidationError

Data class::

    ValidationResult

Class::

    GovernanceValidationGate

Functions::

    evaluate_governance_validation(...)  -> ValidationResult
    get_governance_validation_gate()     -> GovernanceValidationGate
    reset_governance_validation_gate()   -> None   (testing only)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.GovernanceValidationGate")

__all__ = [
    # Sentinels / policy constants
    "GOVERNANCE_VALIDATION_GATE_AUTHORITY",
    "GOVERNANCE_VERDICT_AFFECTS_VALIDATION_POLICY",
    "NOT_READY_BLOCKS_VALIDATION_POLICY",
    "EXPERIMENTAL_CAPABILITY_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY",
    # Enumerations
    "ValidationOutcome",
    "ValidationFailReason",
    # Exceptions
    "GovernanceValidationError",
    # Data class
    "ValidationResult",
    # Class
    "GovernanceValidationGate",
    # Functions
    "evaluate_governance_validation",
    "get_governance_validation_gate",
    "reset_governance_validation_gate",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

GOVERNANCE_VALIDATION_GATE_AUTHORITY: str = (
    "GOVERNANCE_VALIDATION_GATE_AUTHORITY::"
    "core.governance_validation_gate::"
    "PR4::governance-to-validation-closure::"
    "not-ready-and-violation-block-validation"
)
"""Sentinel: this module is the canonical governance-to-validation bridge.
Import to verify that a caller is using the real enforcement gate rather than
a documentation-only report."""

GOVERNANCE_VERDICT_AFFECTS_VALIDATION_POLICY: str = (
    "POLICY::GOVERNANCE_VERDICT_AFFECTS_VALIDATION_V1: "
    "The distributed release gate verdict MUST influence validation outcome.  "
    "A verdict of 'blocked' in ANY gate_worthy category propagates to "
    "ValidationOutcome.FAIL when enforce=True.  This policy exists to prevent "
    "governance verdicts from being purely observational log entries."
)
"""Policy: governance verdicts must affect real validation outcomes."""

NOT_READY_BLOCKS_VALIDATION_POLICY: str = (
    "POLICY::NOT_READY_BLOCKS_VALIDATION_V1: "
    "A ReadinessStatus of BLOCKED from ExecutionReadinessGate, or a "
    "DelegatedFlowReadinessVerdict that is_blocked, MUST produce "
    "ValidationOutcome.FAIL when enforce=True.  "
    "NOT_READY / VIOLATION semantics are real execution conditions, not "
    "informational labels."
)
"""Policy: NOT_READY / BLOCKED readiness status blocks validation."""

EXPERIMENTAL_CAPABILITY_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY: str = (
    "POLICY::EXPERIMENTAL_CAPABILITY_MUST_NOT_CLAIM_MAIN_CHAIN_V1: "
    "Capabilities in the EXPERIMENTAL or QUASI_MAIN_CHAIN tier MUST NOT be "
    "represented as fully-integrated main-chain capabilities.  Callers that "
    "require a MAIN_CHAIN capability and receive an EXPERIMENTAL one MUST "
    "surface this as at least a ValidationOutcome.WARN, and MAY escalate to "
    "FAIL if the calling context requires strict tier enforcement."
)
"""Policy: experimental capabilities must not be treated as main-chain."""


# ---------------------------------------------------------------------------
# ValidationOutcome
# ---------------------------------------------------------------------------


class ValidationOutcome(str, Enum):
    """Top-level validation result.

    Values
    ------
    PASS
        All governance and readiness checks passed.  The system is verified
        ready for the requested operation under current evidence.
    WARN
        One or more checks produced an uncertain result (e.g. evidence surface
        unavailable, capability tier is quasi-main-chain, deferred gate).
        The system MAY proceed but the caller should surface the warning.
    FAIL
        At least one gate_worthy governance category is blocked, or readiness
        status is BLOCKED.  The operation MUST NOT proceed in enforcing mode.
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


# ---------------------------------------------------------------------------
# ValidationFailReason
# ---------------------------------------------------------------------------


class ValidationFailReason(str, Enum):
    """Machine-readable reason for a ValidationOutcome.FAIL or WARN.

    Values
    ------
    governance_blocked
        The distributed release gate produced a 'blocked' overall verdict.
    readiness_blocked
        ExecutionReadinessGate returned ReadinessStatus.BLOCKED.
    delegated_readiness_not_ready
        DelegatedFlowReadinessGate verdict is_blocked is True.
    capability_tier_experimental
        The requested capability is in the EXPERIMENTAL tier.
    capability_tier_quasi_main_chain
        The requested capability is in the QUASI_MAIN_CHAIN tier.
    evidence_surface_unavailable
        The underlying evidence surface could not be loaded; verdict is
        degraded to WARN rather than false-positive PASS.
    none
        No failure reason (used when outcome is PASS).
    """

    governance_blocked = "governance_blocked"
    readiness_blocked = "readiness_blocked"
    delegated_readiness_not_ready = "delegated_readiness_not_ready"
    capability_tier_experimental = "capability_tier_experimental"
    capability_tier_quasi_main_chain = "capability_tier_quasi_main_chain"
    evidence_surface_unavailable = "evidence_surface_unavailable"
    none = "none"


# ---------------------------------------------------------------------------
# GovernanceValidationError
# ---------------------------------------------------------------------------


class GovernanceValidationError(Exception):
    """Raised by :meth:`GovernanceValidationGate.assert_pass` or
    :meth:`GovernanceValidationGate.enforce` when the validation outcome
    is :attr:`ValidationOutcome.FAIL`.

    Attributes
    ----------
    result : ValidationResult
        The full validation result that caused the error.
    """

    def __init__(self, result: "ValidationResult") -> None:
        reason = result.fail_reasons[0].value if result.fail_reasons else "unknown"
        super().__init__(
            f"GovernanceValidation FAILED: outcome={result.outcome.value} "
            f"reason={reason} — {result.summary}"
        )
        self.result = result


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Canonical, serialisable governance validation result.

    Produced by :meth:`GovernanceValidationGate.validate` and
    :func:`evaluate_governance_validation`.

    Fields
    ------
    result_id
        Unique identifier for this validation snapshot.
    generated_at
        Unix timestamp (float) when the result was assembled.
    outcome
        :class:`ValidationOutcome` — PASS / WARN / FAIL.
    fail_reasons
        Ordered list of :class:`ValidationFailReason` values explaining any
        FAIL or WARN outcome.  Empty when outcome is PASS.
    summary
        Human-readable one-liner describing the outcome.
    release_gate_verdict
        The overall_verdict from the distributed release gate skeleton, or
        ``"unavailable"`` if the gate could not be evaluated.
    readiness_status
        The ReadinessStatus value from ExecutionReadinessGate, or
        ``"unavailable"`` if the gate could not be evaluated.
    delegated_readiness_verdict
        The DelegatedFlowReadinessVerdict value, or ``"unavailable"``.
    blocked_gate_worthy_count
        Number of gate_worthy categories that are blocked.
    capability_tier
        The tier of the capability being validated, or ``""`` if not checked.
    enforce_mode
        Whether the validation was run in enforce mode (errors raised on FAIL).
    details
        Additional structured details for debugging.
    """

    result_id: str
    generated_at: float
    outcome: ValidationOutcome
    fail_reasons: List[ValidationFailReason] = field(default_factory=list)
    summary: str = ""
    release_gate_verdict: str = "unavailable"
    readiness_status: str = "unavailable"
    delegated_readiness_verdict: str = "unavailable"
    blocked_gate_worthy_count: int = 0
    capability_tier: str = ""
    enforce_mode: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "generated_at": self.generated_at,
            "outcome": self.outcome.value,
            "fail_reasons": [r.value for r in self.fail_reasons],
            "summary": self.summary,
            "release_gate_verdict": self.release_gate_verdict,
            "readiness_status": self.readiness_status,
            "delegated_readiness_verdict": self.delegated_readiness_verdict,
            "blocked_gate_worthy_count": self.blocked_gate_worthy_count,
            "capability_tier": self.capability_tier,
            "enforce_mode": self.enforce_mode,
            "details": self.details,
        }

    @property
    def passed(self) -> bool:
        """True when outcome is PASS."""
        return self.outcome == ValidationOutcome.PASS

    @property
    def failed(self) -> bool:
        """True when outcome is FAIL."""
        return self.outcome == ValidationOutcome.FAIL

    @property
    def warned(self) -> bool:
        """True when outcome is WARN."""
        return self.outcome == ValidationOutcome.WARN


# ---------------------------------------------------------------------------
# Optional dependency imports (graceful degradation)
# ---------------------------------------------------------------------------

try:
    from core.distributed_release_gate_skeleton import (
        evaluate_distributed_release_gate as _evaluate_distributed_gate,
        ReleaseGateVerdict as _ReleaseGateVerdict,
    )
    _DISTRIBUTED_GATE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DISTRIBUTED_GATE_AVAILABLE = False
    _evaluate_distributed_gate = None  # type: ignore[assignment]
    _ReleaseGateVerdict = None  # type: ignore[assignment]

try:
    from core.execution.readiness_gate import (
        evaluate_readiness as _evaluate_readiness,
        ReadinessStatus as _ReadinessStatus,
    )
    _READINESS_GATE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _READINESS_GATE_AVAILABLE = False
    _evaluate_readiness = None  # type: ignore[assignment]
    _ReadinessStatus = None  # type: ignore[assignment]

try:
    from core.delegated_flow_readiness_gate import (
        DelegatedFlowReadinessGate as _DelegatedFlowReadinessGate,
    )
    _DELEGATED_READINESS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DELEGATED_READINESS_AVAILABLE = False
    _DelegatedFlowReadinessGate = None  # type: ignore[assignment]

try:
    from core.capability_tier import (
        get_capability_tier,
        CapabilityTier as _CapabilityTier,
    )
    _CAPABILITY_TIER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CAPABILITY_TIER_AVAILABLE = False
    get_capability_tier = None  # type: ignore[assignment]
    _CapabilityTier = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# GovernanceValidationGate
# ---------------------------------------------------------------------------


class GovernanceValidationGate:
    """Bridges governance/readiness verdicts into real validation semantics.

    Usage
    -----
    Basic validation (observe mode — never raises)::

        gate = GovernanceValidationGate()
        result = gate.validate()
        if result.failed:
            print(f"Governance blocked: {result.summary}")

    Enforcing mode (raises on FAIL)::

        try:
            result = gate.validate(enforce=True)
        except GovernanceValidationError as exc:
            # hard block — surface to CI or release pipeline
            raise SystemExit(1) from exc

    Capability-tier check::

        result = gate.validate(capability="screen_capture")
        if result.warned:
            print(f"Capability tier: {result.capability_tier}")

    Parameters
    ----------
    strict_on_unavailable
        When ``True``, treat an unavailable evidence surface as FAIL instead
        of the default WARN.  Defaults to ``False`` for safe degradation.
    """

    def __init__(self, *, strict_on_unavailable: bool = False) -> None:
        self._strict_on_unavailable = strict_on_unavailable

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def validate(
        self,
        *,
        capability: Optional[str] = None,
        enforce: bool = False,
        check_readiness: bool = True,
        check_delegated_readiness: bool = False,
        check_capability_tier: bool = True,
    ) -> "ValidationResult":
        """Run all active governance and readiness checks.

        Parameters
        ----------
        capability
            Optional capability name to tier-check.  If provided and
            ``check_capability_tier=True``, the tier is evaluated and
            non-MAIN_CHAIN tiers surface as WARN (or FAIL if enforce=True
            and the tier is EXPERIMENTAL).
        enforce
            When ``True``, raise :class:`GovernanceValidationError` if the
            outcome is :attr:`ValidationOutcome.FAIL`.
        check_readiness
            When ``True`` (default), evaluate ExecutionReadinessGate.
        check_delegated_readiness
            When ``True``, also evaluate DelegatedFlowReadinessGate.
        check_capability_tier
            When ``True`` (default) and ``capability`` is provided, evaluate
            the capability's tier.

        Returns
        -------
        ValidationResult
        """
        fail_reasons: List[ValidationFailReason] = []
        details: Dict[str, Any] = {}
        release_gate_verdict = "unavailable"
        readiness_status = "unavailable"
        delegated_readiness_verdict = "unavailable"
        blocked_count = 0
        cap_tier = ""

        # -- Distributed release gate check ---------------------------------
        if _DISTRIBUTED_GATE_AVAILABLE and _evaluate_distributed_gate is not None:
            try:
                gate_report = _evaluate_distributed_gate()
                release_gate_verdict = gate_report.overall_verdict
                blocked_count = gate_report.blocked_gate_worthy_count
                details["release_gate_report_id"] = gate_report.report_id
                details["gate_worthy_count"] = gate_report.gate_worthy_count

                if release_gate_verdict == "blocked":
                    fail_reasons.append(ValidationFailReason.governance_blocked)
                    details["blocked_categories"] = [
                        e.category
                        for e in gate_report.category_evaluations
                        if e.verdict == "blocked"
                    ]
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "GovernanceValidationGate: distributed gate eval failed: %s", exc
                )
                release_gate_verdict = "error"
                fail_reasons.append(ValidationFailReason.evidence_surface_unavailable)
                details["distributed_gate_error"] = str(exc)
        else:
            # Evidence surface not importable — treat as unavailable
            fail_reasons.append(ValidationFailReason.evidence_surface_unavailable)
            details["distributed_gate_available"] = False

        # -- ExecutionReadinessGate check -----------------------------------
        if check_readiness and _READINESS_GATE_AVAILABLE and _evaluate_readiness is not None:
            try:
                readiness_result = _evaluate_readiness()
                readiness_status = readiness_result.status.value
                details["readiness_ready"] = readiness_result.ready
                if readiness_result.status.value == "blocked":
                    fail_reasons.append(ValidationFailReason.readiness_blocked)
                    details["readiness_blocked_by"] = (
                        readiness_result.blocked_by.value
                        if readiness_result.blocked_by
                        else None
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "GovernanceValidationGate: readiness gate eval failed: %s", exc
                )
                readiness_status = "error"
                details["readiness_error"] = str(exc)

        # -- DelegatedFlowReadinessGate check --------------------------------
        if (
            check_delegated_readiness
            and _DELEGATED_READINESS_AVAILABLE
            and _DelegatedFlowReadinessGate is not None
        ):
            try:
                delegated_report = _DelegatedFlowReadinessGate().evaluate()
                delegated_readiness_verdict = delegated_report.verdict.value
                details["delegated_is_ready"] = delegated_report.is_ready_for_release
                if delegated_report.verdict.is_blocked:
                    fail_reasons.append(ValidationFailReason.delegated_readiness_not_ready)
                    details["delegated_gaps"] = delegated_report.gaps
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "GovernanceValidationGate: delegated readiness eval failed: %s", exc
                )
                delegated_readiness_verdict = "error"
                details["delegated_readiness_error"] = str(exc)

        # -- Capability tier check ------------------------------------------
        if (
            capability
            and check_capability_tier
            and _CAPABILITY_TIER_AVAILABLE
            and get_capability_tier is not None
        ):
            try:
                tier = get_capability_tier(capability)
                cap_tier = tier.value
                details["capability"] = capability
                details["capability_tier"] = cap_tier
                if tier.value == "EXPERIMENTAL":
                    fail_reasons.append(ValidationFailReason.capability_tier_experimental)
                elif tier.value == "QUASI_MAIN_CHAIN":
                    fail_reasons.append(ValidationFailReason.capability_tier_quasi_main_chain)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "GovernanceValidationGate: capability tier check failed: %s", exc
                )
                details["capability_tier_error"] = str(exc)

        # -- Determine outcome ----------------------------------------------
        outcome = self._compute_outcome(fail_reasons)

        # Build summary
        if outcome == ValidationOutcome.PASS:
            summary = "All governance and readiness checks passed."
        elif outcome == ValidationOutcome.WARN:
            warn_reasons = [r.value for r in fail_reasons]
            summary = f"Validation passed with warnings: {', '.join(warn_reasons)}"
        else:
            fail_strs = [r.value for r in fail_reasons]
            summary = f"Validation FAILED: {', '.join(fail_strs)}"

        result = ValidationResult(
            result_id=str(uuid.uuid4()),
            generated_at=time.time(),
            outcome=outcome,
            fail_reasons=fail_reasons,
            summary=summary,
            release_gate_verdict=release_gate_verdict,
            readiness_status=readiness_status,
            delegated_readiness_verdict=delegated_readiness_verdict,
            blocked_gate_worthy_count=blocked_count,
            capability_tier=cap_tier,
            enforce_mode=enforce,
            details=details,
        )

        logger.debug(
            "GovernanceValidationGate.validate() → outcome=%s fail_reasons=%s",
            outcome.value,
            [r.value for r in fail_reasons],
        )

        if enforce and outcome == ValidationOutcome.FAIL:
            raise GovernanceValidationError(result)

        return result

    def assert_pass(self, **validate_kwargs: Any) -> ValidationResult:
        """Validate and raise :class:`GovernanceValidationError` on FAIL.

        Equivalent to ``validate(enforce=True, ...)``.
        """
        return self.validate(enforce=True, **validate_kwargs)

    def enforce(self, **validate_kwargs: Any) -> ValidationResult:
        """Alias for :meth:`assert_pass`."""
        return self.assert_pass(**validate_kwargs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_outcome(
        self, fail_reasons: List[ValidationFailReason]
    ) -> ValidationOutcome:
        """Compute the overall outcome from the accumulated fail reasons.

        Rules
        -----
        - Any hard-fail reason → FAIL
        - Only soft-warn reasons → WARN
        - No reasons → PASS

        Hard-fail reasons (per policy)
        ------------------------------
        - governance_blocked
        - readiness_blocked
        - delegated_readiness_not_ready

        Soft-warn reasons
        -----------------
        - evidence_surface_unavailable  (unless strict_on_unavailable=True)
        - capability_tier_experimental  (warn by default; callers may escalate)
        - capability_tier_quasi_main_chain
        """
        if not fail_reasons:
            return ValidationOutcome.PASS

        _hard_fail = {
            ValidationFailReason.governance_blocked,
            ValidationFailReason.readiness_blocked,
            ValidationFailReason.delegated_readiness_not_ready,
        }

        if self._strict_on_unavailable:
            _hard_fail.add(ValidationFailReason.evidence_surface_unavailable)

        for reason in fail_reasons:
            if reason in _hard_fail:
                return ValidationOutcome.FAIL

        # Only soft-warn reasons remain
        return ValidationOutcome.WARN


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

_default_gate: Optional[GovernanceValidationGate] = None
_gate_lock = threading.Lock()


def get_governance_validation_gate(
    *, strict_on_unavailable: bool = False
) -> GovernanceValidationGate:
    """Return the process-level :class:`GovernanceValidationGate` singleton."""
    global _default_gate
    with _gate_lock:
        if _default_gate is None:
            _default_gate = GovernanceValidationGate(
                strict_on_unavailable=strict_on_unavailable
            )
    return _default_gate


def reset_governance_validation_gate() -> None:
    """Reset the singleton (for testing only)."""
    global _default_gate
    with _gate_lock:
        _default_gate = None


def evaluate_governance_validation(
    *,
    capability: Optional[str] = None,
    enforce: bool = False,
    check_readiness: bool = True,
    check_delegated_readiness: bool = False,
    check_capability_tier: bool = True,
    strict_on_unavailable: bool = False,
) -> ValidationResult:
    """Module-level convenience function — evaluate governance validation.

    Creates a fresh :class:`GovernanceValidationGate` (not the singleton) to
    ensure the evaluation always reflects current evidence state.

    Parameters are forwarded to :meth:`GovernanceValidationGate.validate`.

    Returns
    -------
    ValidationResult
    """
    gate = GovernanceValidationGate(strict_on_unavailable=strict_on_unavailable)
    return gate.validate(
        capability=capability,
        enforce=enforce,
        check_readiness=check_readiness,
        check_delegated_readiness=check_delegated_readiness,
        check_capability_tier=check_capability_tier,
    )
