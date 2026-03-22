#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.schemas.execution_failure — Structured Retry and Fallback Execution Policies
==================================================================================

PR-13 — Failure Domains, Retry Policies, and Fallback Execution Policies

Defines structured, serialisable objects for expressing **retry policy**
and **fallback execution policy** alongside a failure record so that
failure-handling decisions are explicit and inspectable rather than
scattered across dispatch branches.

These objects are *policy descriptors* — they describe what *should* happen
on failure.  Actual retry/fallback logic lives in the transport and dispatch
layers; these objects communicate intent and constraints.

Architectural role
------------------
::

    FailureDomain (core.failure_domains)
        ↓  classify failure kind
    FailureRecord (this module)
        ↓  carries domain + attached policies
    RetryPolicy   ← how many times, same/alternate target, mode downgrade?
    FallbackPolicy ← which fallback path is allowed?

Main concepts
-------------
:class:`RetryPolicy`
    Describes retry eligibility, limits, backoff, and targeting constraints.

:class:`FallbackPolicy`
    Describes which execution-mode or target downgrades are permitted on
    failure.

:class:`FailureRecord`
    Combines a :class:`~core.failure_domains.FailureClassification` with
    attached :class:`RetryPolicy` and :class:`FallbackPolicy` for a single
    failure event.

:func:`build_failure_record`
    Principal builder — derive a :class:`FailureRecord` from an error code
    or exception, optionally overriding the default policies.

:func:`failure_record_summary`
    Compact, JSON-safe dict suitable for embedding in metadata or
    diagnostic responses.

Relationship to other schemas
------------------------------
* :class:`~core.failure_domains.FailureDomain` — domain enum used here.
* :class:`~core.schemas.execution_lifecycle.ExecutionLifecycleState` — the
  caller may attach the ``failure_domain`` value to lifecycle summaries.
* :class:`~core.schemas.execution_plan.ExecutionPlan` — plan steps may
  carry an attached :class:`FailureRecord` when the step fails.

Backward compatibility
----------------------
All fields are optional with safe defaults.  Consumers that do not inspect
failure policy data continue to work unchanged.

Usage::

    from core.schemas.execution_failure import (
        RetryPolicy,
        FallbackPolicy,
        FailureRecord,
        build_failure_record,
        failure_record_summary,
    )

    # Quick classification from a gateway error code
    record = build_failure_record(error_code="COMMAND_TIMEOUT")
    print(record.failure_domain)          # "timeout_failure"
    print(record.retry_policy.max_attempts)  # 3
    print(record.fallback_policy.allow_remote_to_local)  # True
    print(failure_record_summary(record))
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional

from core.failure_domains import (
    FailureClassification,
    FailureDomain,
    classify_from_error_code,
    classify_from_exception,
)


__all__ = [
    "RetryPolicy",
    "FallbackPolicy",
    "FailureRecord",
    "build_failure_record",
    "build_failure_record_from_exception",
    "failure_record_summary",
    "DEFAULT_NO_RETRY_POLICY",
    "DEFAULT_TRANSIENT_RETRY_POLICY",
    "DEFAULT_NO_FALLBACK_POLICY",
    "DEFAULT_REMOTE_FALLBACK_POLICY",
]


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    """Structured retry policy for an execution failure.

    Attributes
    ----------
    is_retryable:
        Whether any retry is permitted for this failure.
    max_attempts:
        Maximum total attempts (including the first).  ``1`` means no
        retries.  Only meaningful when ``is_retryable`` is ``True``.
    backoff_base_ms:
        Base backoff interval in milliseconds between attempts.  ``0``
        means no backoff hint.
    backoff_multiplier:
        Exponential backoff multiplier applied after each failed attempt.
        ``1.0`` means constant backoff.
    same_target_only:
        When ``True``, retries must target the same device/executor as the
        original attempt.  When ``False``, alternate targets may be used.
    allow_mode_downgrade:
        When ``True``, the retry is permitted to use a lower execution mode
        (e.g. ``agent_runtime`` → ``command_only``) if the original mode
        failed.
    notes:
        Optional advisory explanation.
    """

    is_retryable: bool = False
    max_attempts: int = 1
    backoff_base_ms: int = 0
    backoff_multiplier: float = 1.0
    same_target_only: bool = True
    allow_mode_downgrade: bool = False
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "is_retryable": self.is_retryable,
            "max_attempts": self.max_attempts,
            "backoff_base_ms": self.backoff_base_ms,
            "backoff_multiplier": self.backoff_multiplier,
            "same_target_only": self.same_target_only,
            "allow_mode_downgrade": self.allow_mode_downgrade,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# FallbackPolicy
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FallbackPolicy:
    """Structured fallback execution policy for an execution failure.

    Attributes
    ----------
    allow_agent_to_command_downgrade:
        Permit downgrading from ``agent_runtime`` mode to ``command_only``
        when the original agent-runtime attempt fails due to a capability
        mismatch or transport failure.
    allow_remote_to_local:
        Permit falling back to local execution when all remote targets are
        unavailable or fail.
    allow_alternate_target:
        Permit rerouting to a different device/executor when the primary
        target is unavailable or fails.
    degraded_completion_allowed:
        For multi-device / orchestration plans: permit the plan to complete
        in a degraded state (partial success) rather than fully failing.
    fallback_mode_hint:
        Advisory hint about which execution mode to try on fallback.
        Typical values: ``"command_only"``, ``"local"``.  ``None`` means
        no specific mode is prescribed.
    notes:
        Optional advisory explanation.
    """

    allow_agent_to_command_downgrade: bool = False
    allow_remote_to_local: bool = False
    allow_alternate_target: bool = False
    degraded_completion_allowed: bool = False
    fallback_mode_hint: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "allow_agent_to_command_downgrade": self.allow_agent_to_command_downgrade,
            "allow_remote_to_local": self.allow_remote_to_local,
            "allow_alternate_target": self.allow_alternate_target,
            "degraded_completion_allowed": self.degraded_completion_allowed,
            "fallback_mode_hint": self.fallback_mode_hint,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Predefined policy constants
# ---------------------------------------------------------------------------

DEFAULT_NO_RETRY_POLICY = RetryPolicy(
    is_retryable=False,
    max_attempts=1,
    notes="Non-retryable failure.",
)

DEFAULT_TRANSIENT_RETRY_POLICY = RetryPolicy(
    is_retryable=True,
    max_attempts=3,
    backoff_base_ms=500,
    backoff_multiplier=2.0,
    same_target_only=False,
    allow_mode_downgrade=False,
    notes="Transient failure; retry with exponential backoff on alternate targets.",
)

DEFAULT_NO_FALLBACK_POLICY = FallbackPolicy(
    allow_agent_to_command_downgrade=False,
    allow_remote_to_local=False,
    allow_alternate_target=False,
    degraded_completion_allowed=False,
    notes="No fallback permitted.",
)

DEFAULT_REMOTE_FALLBACK_POLICY = FallbackPolicy(
    allow_agent_to_command_downgrade=True,
    allow_remote_to_local=True,
    allow_alternate_target=True,
    degraded_completion_allowed=True,
    notes="Full remote fallback: agent→command downgrade, remote→local, alternate target.",
)


# ---------------------------------------------------------------------------
# FailureRecord
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FailureRecord:
    """A structured record combining a failure classification with its policies.

    Attributes
    ----------
    classification:
        The :class:`~core.failure_domains.FailureClassification` describing
        the kind of failure that occurred.
    retry_policy:
        The :class:`RetryPolicy` applicable to this failure.
    fallback_policy:
        The :class:`FallbackPolicy` applicable to this failure.
    """

    classification: FailureClassification
    retry_policy: RetryPolicy
    fallback_policy: FallbackPolicy

    # -----------------------------------------------------------------------
    # Convenience accessors
    # -----------------------------------------------------------------------

    @property
    def failure_domain(self) -> str:
        """The :class:`~core.failure_domains.FailureDomain` value string."""
        return self.classification.domain.value

    @property
    def is_retryable(self) -> bool:
        """Whether any retry is permitted."""
        return self.retry_policy.is_retryable

    @property
    def downgrade_hint(self) -> Optional[str]:
        """Advisory downgrade hint from the failure classification."""
        return self.classification.downgrade_hint

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "failure_domain": self.failure_domain,
            "classification": self.classification.to_dict(),
            "retry_policy": self.retry_policy.to_dict(),
            "fallback_policy": self.fallback_policy.to_dict(),
        }


# ---------------------------------------------------------------------------
# Policy derivation helpers
# ---------------------------------------------------------------------------

def _derive_retry_policy(
    classification: FailureClassification,
) -> RetryPolicy:
    """Derive a sensible default :class:`RetryPolicy` from a classification."""
    domain = classification.domain

    if domain == FailureDomain.TIMEOUT_FAILURE:
        return RetryPolicy(
            is_retryable=True,
            max_attempts=3,
            backoff_base_ms=1000,
            backoff_multiplier=2.0,
            same_target_only=False,
            allow_mode_downgrade=False,
            notes="Timeout failures are retryable on alternate targets.",
        )
    if domain == FailureDomain.GATEWAY_TRANSPORT_FAILURE:
        return RetryPolicy(
            is_retryable=True,
            max_attempts=3,
            backoff_base_ms=500,
            backoff_multiplier=2.0,
            same_target_only=False,
            allow_mode_downgrade=False,
            notes="Transport failures are retryable on alternate targets.",
        )
    if domain == FailureDomain.REMOTE_DEVICE_UNAVAILABLE:
        return RetryPolicy(
            is_retryable=True,
            max_attempts=2,
            backoff_base_ms=200,
            backoff_multiplier=1.5,
            same_target_only=False,
            allow_mode_downgrade=False,
            notes="Device unavailable; retry on alternate target.",
        )
    if domain == FailureDomain.REMOTE_CAPABILITY_MISMATCH:
        # Same-target retry won't help; allow mode downgrade
        return RetryPolicy(
            is_retryable=True,
            max_attempts=1,
            backoff_base_ms=0,
            backoff_multiplier=1.0,
            same_target_only=False,
            allow_mode_downgrade=True,
            notes="Capability mismatch; mode downgrade or alternate target may help.",
        )
    # Non-retryable domains
    return DEFAULT_NO_RETRY_POLICY


def _derive_fallback_policy(
    classification: FailureClassification,
) -> FallbackPolicy:
    """Derive a sensible default :class:`FallbackPolicy` from a classification."""
    domain = classification.domain

    if domain == FailureDomain.REMOTE_CAPABILITY_MISMATCH:
        return FallbackPolicy(
            allow_agent_to_command_downgrade=True,
            allow_remote_to_local=False,
            allow_alternate_target=True,
            degraded_completion_allowed=False,
            fallback_mode_hint="command_only",
            notes="Capability mismatch: try command_only downgrade or alternate target.",
        )
    if domain in (
        FailureDomain.REMOTE_DEVICE_UNAVAILABLE,
        FailureDomain.GATEWAY_TRANSPORT_FAILURE,
    ):
        return FallbackPolicy(
            allow_agent_to_command_downgrade=True,
            allow_remote_to_local=True,
            allow_alternate_target=True,
            degraded_completion_allowed=False,
            fallback_mode_hint="local",
            notes="Device/transport failure: try alternate target or local fallback.",
        )
    if domain == FailureDomain.ORCHESTRATION_PARTIAL_FAILURE:
        return FallbackPolicy(
            allow_agent_to_command_downgrade=False,
            allow_remote_to_local=False,
            allow_alternate_target=False,
            degraded_completion_allowed=True,
            fallback_mode_hint=None,
            notes="Partial orchestration: degraded completion is acceptable.",
        )
    if domain == FailureDomain.TIMEOUT_FAILURE:
        return FallbackPolicy(
            allow_agent_to_command_downgrade=False,
            allow_remote_to_local=True,
            allow_alternate_target=True,
            degraded_completion_allowed=False,
            fallback_mode_hint=None,
            notes="Timeout: try alternate target or local fallback.",
        )
    # For non-recoverable domains (contract validation, local runtime, unknown)
    return DEFAULT_NO_FALLBACK_POLICY


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_failure_record(
    error_code: Optional[str] = None,
    *,
    retry_policy: Optional[RetryPolicy] = None,
    fallback_policy: Optional[FallbackPolicy] = None,
    notes: Optional[str] = None,
) -> FailureRecord:
    """Build a :class:`FailureRecord` from a gateway/substrate error code.

    Parameters
    ----------
    error_code:
        A ``GatewayErrorCode`` value string (e.g. ``"COMMAND_TIMEOUT"``),
        ``"ACL_DENIED"``, or any other error code.  ``None`` produces an
        ``unknown_failure`` classification.
    retry_policy:
        Optional override for the retry policy.  When omitted, a sensible
        default is derived from the classified failure domain.
    fallback_policy:
        Optional override for the fallback policy.  When omitted, a
        sensible default is derived from the classified failure domain.
    notes:
        Optional extra context embedded in the classification.

    Returns
    -------
    FailureRecord
    """
    classification = classify_from_error_code(error_code, notes=notes)
    effective_retry = retry_policy if retry_policy is not None else _derive_retry_policy(classification)
    effective_fallback = fallback_policy if fallback_policy is not None else _derive_fallback_policy(classification)
    return FailureRecord(
        classification=classification,
        retry_policy=effective_retry,
        fallback_policy=effective_fallback,
    )


def build_failure_record_from_exception(
    exc: Exception,
    *,
    retry_policy: Optional[RetryPolicy] = None,
    fallback_policy: Optional[FallbackPolicy] = None,
    notes: Optional[str] = None,
) -> FailureRecord:
    """Build a :class:`FailureRecord` from an exception.

    Parameters
    ----------
    exc:
        The exception that caused the failure.
    retry_policy:
        Optional override for the retry policy.
    fallback_policy:
        Optional override for the fallback policy.
    notes:
        Optional extra context.

    Returns
    -------
    FailureRecord
    """
    classification = classify_from_exception(exc, notes=notes)
    effective_retry = retry_policy if retry_policy is not None else _derive_retry_policy(classification)
    effective_fallback = fallback_policy if fallback_policy is not None else _derive_fallback_policy(classification)
    return FailureRecord(
        classification=classification,
        retry_policy=effective_retry,
        fallback_policy=effective_fallback,
    )


def failure_record_summary(
    record: Optional[FailureRecord],
) -> Dict[str, Any]:
    """Return a compact, JSON-safe summary dict for embedding in metadata.

    Parameters
    ----------
    record:
        The :class:`FailureRecord` to summarise.  Passing ``None`` returns
        a safe empty dict.

    Returns
    -------
    dict
        Keys: ``failure_domain``, ``is_retryable``, ``downgrade_hint``,
        ``retry_max_attempts``, ``fallback_allow_remote_to_local``,
        ``fallback_allow_alternate_target``.
    """
    if record is None:
        return {}
    return {
        "failure_domain": record.failure_domain,
        "is_retryable": record.is_retryable,
        "downgrade_hint": record.downgrade_hint,
        "retry_max_attempts": record.retry_policy.max_attempts,
        "fallback_allow_remote_to_local": record.fallback_policy.allow_remote_to_local,
        "fallback_allow_alternate_target": record.fallback_policy.allow_alternate_target,
        "fallback_allow_agent_to_command_downgrade": (
            record.fallback_policy.allow_agent_to_command_downgrade
        ),
    }
