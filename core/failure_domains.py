#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.failure_domains — Canonical Failure Domain Taxonomy
=========================================================

PR-13 — Failure Domains, Retry Policies, and Fallback Execution Policies

Defines the **canonical failure-domain vocabulary** for the Galaxy runtime.
Every execution path — local, remote ``command_only``, remote
``agent_runtime``, and multi-device orchestration — can express what *kind*
of failure occurred using the stable :class:`FailureDomain` enum defined
here.

This module is intentionally small and import-safe.  It carries no heavy
dependencies so it can be imported early in any dispatch or resolver path
without causing circular imports.

Failure Domain Semantics
------------------------
+-------------------------------+---------------------------------------------+
| Domain                        | Meaning                                     |
+===============================+=============================================+
| ``local_runtime_failure``     | The local execution path raised an error or |
|                               | returned a failure result.                  |
+-------------------------------+---------------------------------------------+
| ``remote_capability_mismatch``| The target device's profile does not        |
|                               | support the required execution mode or the  |
|                               | required capability set.                    |
+-------------------------------+---------------------------------------------+
| ``remote_device_unavailable`` | The target device is not registered, is     |
|                               | offline, or cannot be reached.              |
+-------------------------------+---------------------------------------------+
| ``gateway_transport_failure`` | The transport layer (gateway/NATS/WebSocket)|
|                               | experienced a connection error, disconnect, |
|                               | or delivery failure.                        |
+-------------------------------+---------------------------------------------+
| ``substrate_dispatch_failure``| The execution substrate (CommandRouter) was |
|                               | unable to dispatch the envelope — e.g.      |
|                               | invalid envelope, ACL denial, internal      |
|                               | routing error.                              |
+-------------------------------+---------------------------------------------+
| ``orchestration_partial_failure``| A multi-device plan partially succeeded.  |
|                               | At least one member failed; the aggregate   |
|                               | result is degraded or partially succeeded.  |
+-------------------------------+---------------------------------------------+
| ``contract_validation_failure``| Schema validation, ACL enforcement, or      |
|                               | HITL denial rejected the execution attempt. |
+-------------------------------+---------------------------------------------+
| ``timeout_failure``           | The operation did not complete within its   |
|                               | permitted time window.                      |
+-------------------------------+---------------------------------------------+
| ``unknown_failure``           | Catch-all for failures that cannot be       |
|                               | classified into a known domain.             |
+-------------------------------+---------------------------------------------+

Usage::

    from core.failure_domains import (
        FailureDomain,
        FailureClassification,
        classify_from_error_code,
        is_retryable_by_domain,
    )

    classification = classify_from_error_code("COMMAND_TIMEOUT")
    assert classification.domain == FailureDomain.TIMEOUT_FAILURE
    assert classification.is_retryable

    domain = FailureDomain.REMOTE_DEVICE_UNAVAILABLE
    print(is_retryable_by_domain(domain))  # True
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Dict, Optional


__all__ = [
    "FailureDomain",
    "FailureClassification",
    "classify_from_error_code",
    "classify_from_exception",
    "is_retryable_by_domain",
    "downgrade_hint_for_domain",
    "DOMAIN_DESCRIPTIONS",
]


# ---------------------------------------------------------------------------
# FailureDomain
# ---------------------------------------------------------------------------


class FailureDomain(str, Enum):
    """Canonical failure domain vocabulary.

    Values are stable, lowercase, underscore-delimited strings safe for
    serialisation, logging, and API responses.
    """

    LOCAL_RUNTIME_FAILURE = "local_runtime_failure"
    REMOTE_CAPABILITY_MISMATCH = "remote_capability_mismatch"
    REMOTE_DEVICE_UNAVAILABLE = "remote_device_unavailable"
    GATEWAY_TRANSPORT_FAILURE = "gateway_transport_failure"
    SUBSTRATE_DISPATCH_FAILURE = "substrate_dispatch_failure"
    ORCHESTRATION_PARTIAL_FAILURE = "orchestration_partial_failure"
    CONTRACT_VALIDATION_FAILURE = "contract_validation_failure"
    TIMEOUT_FAILURE = "timeout_failure"
    UNKNOWN_FAILURE = "unknown_failure"


# ---------------------------------------------------------------------------
# Human-readable descriptions
# ---------------------------------------------------------------------------

DOMAIN_DESCRIPTIONS: Dict[FailureDomain, str] = {
    FailureDomain.LOCAL_RUNTIME_FAILURE: (
        "Local execution raised an error or returned a failure result."
    ),
    FailureDomain.REMOTE_CAPABILITY_MISMATCH: (
        "Target device profile does not support the required execution mode or capability."
    ),
    FailureDomain.REMOTE_DEVICE_UNAVAILABLE: (
        "Target device is not registered, offline, or unreachable."
    ),
    FailureDomain.GATEWAY_TRANSPORT_FAILURE: (
        "Transport layer experienced a connection error, disconnect, or delivery failure."
    ),
    FailureDomain.SUBSTRATE_DISPATCH_FAILURE: (
        "Execution substrate was unable to dispatch the envelope "
        "(invalid envelope, ACL denial, routing error)."
    ),
    FailureDomain.ORCHESTRATION_PARTIAL_FAILURE: (
        "Multi-device orchestration partially succeeded; at least one member failed."
    ),
    FailureDomain.CONTRACT_VALIDATION_FAILURE: (
        "Schema validation, ACL enforcement, or HITL denial rejected the execution attempt."
    ),
    FailureDomain.TIMEOUT_FAILURE: (
        "Operation did not complete within the permitted time window."
    ),
    FailureDomain.UNKNOWN_FAILURE: (
        "Failure cannot be classified into a known domain."
    ),
}


# ---------------------------------------------------------------------------
# Retry eligibility by domain
# ---------------------------------------------------------------------------

#: Domains where a retry attempt may succeed (transient failures).
_RETRYABLE_DOMAINS: frozenset[FailureDomain] = frozenset(
    {
        FailureDomain.REMOTE_DEVICE_UNAVAILABLE,
        FailureDomain.GATEWAY_TRANSPORT_FAILURE,
        FailureDomain.TIMEOUT_FAILURE,
    }
)

#: Domains where retry on a *different target* may help even if
#: same-target retry would not.
_RETRYABLE_ON_ALTERNATE_TARGET: frozenset[FailureDomain] = frozenset(
    {
        FailureDomain.REMOTE_CAPABILITY_MISMATCH,
        FailureDomain.REMOTE_DEVICE_UNAVAILABLE,
        FailureDomain.GATEWAY_TRANSPORT_FAILURE,
        FailureDomain.TIMEOUT_FAILURE,
    }
)


def is_retryable_by_domain(
    domain: FailureDomain,
    *,
    allow_alternate_target: bool = False,
) -> bool:
    """Return ``True`` when a failure in *domain* is eligible for retry.

    Parameters
    ----------
    domain:
        The :class:`FailureDomain` to check.
    allow_alternate_target:
        When ``True``, also return ``True`` for domains where retry on a
        *different* target is viable even if same-target retry is not.

    Returns
    -------
    bool
    """
    if domain in _RETRYABLE_DOMAINS:
        return True
    if allow_alternate_target and domain in _RETRYABLE_ON_ALTERNATE_TARGET:
        return True
    return False


# ---------------------------------------------------------------------------
# Downgrade hints by domain
# ---------------------------------------------------------------------------

def downgrade_hint_for_domain(domain: FailureDomain) -> Optional[str]:
    """Return a canonical downgrade hint string for *domain*, or ``None``.

    The hint is advisory — it tells the fallback policy what kind of
    execution mode downgrade may be worth attempting.

    Possible return values:
    * ``"agent_runtime_to_command_only"``
    * ``"remote_to_local"``
    * ``None`` — no specific downgrade hint; caller decides.
    """
    _hints: Dict[FailureDomain, str] = {
        FailureDomain.REMOTE_CAPABILITY_MISMATCH: "agent_runtime_to_command_only",
        FailureDomain.REMOTE_DEVICE_UNAVAILABLE: "remote_to_local",
        FailureDomain.GATEWAY_TRANSPORT_FAILURE: "remote_to_local",
    }
    return _hints.get(domain)


# ---------------------------------------------------------------------------
# FailureClassification
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FailureClassification:
    """The result of classifying a failure event into a :class:`FailureDomain`.

    Attributes
    ----------
    domain:
        The canonical :class:`FailureDomain` for this failure.
    is_retryable:
        Whether a retry attempt (same or alternate target) is worth trying.
    is_retryable_same_target:
        Whether retry on the *same* target is appropriate (a subset of
        retryable failures).
    downgrade_hint:
        Advisory hint about a mode downgrade that may succeed where the
        original attempt failed.  ``None`` means no downgrade is suggested.
    source_error_code:
        The raw error code or exception class name that produced this
        classification.  ``None`` when not derived from a known code.
    notes:
        Optional free-form explanation of how the classification was made.
    """

    domain: FailureDomain
    is_retryable: bool
    is_retryable_same_target: bool
    downgrade_hint: Optional[str]
    source_error_code: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "domain": self.domain.value,
            "is_retryable": self.is_retryable,
            "is_retryable_same_target": self.is_retryable_same_target,
            "downgrade_hint": self.downgrade_hint,
            "source_error_code": self.source_error_code,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

# Mapping from GatewayErrorCode string values to failure domains
_GATEWAY_ERROR_CODE_MAP: Dict[str, FailureDomain] = {
    "INVALID_ENVELOPE": FailureDomain.SUBSTRATE_DISPATCH_FAILURE,
    "DEVICE_NOT_FOUND": FailureDomain.REMOTE_DEVICE_UNAVAILABLE,
    "DEVICE_OFFLINE": FailureDomain.REMOTE_DEVICE_UNAVAILABLE,
    "COMMAND_TIMEOUT": FailureDomain.TIMEOUT_FAILURE,
    "DISCONNECT": FailureDomain.GATEWAY_TRANSPORT_FAILURE,
    "EXECUTOR_ERROR": FailureDomain.GATEWAY_TRANSPORT_FAILURE,
    "INTERNAL_ERROR": FailureDomain.SUBSTRATE_DISPATCH_FAILURE,
    "HITL_TIMEOUT": FailureDomain.TIMEOUT_FAILURE,
    "HITL_DENIED": FailureDomain.CONTRACT_VALIDATION_FAILURE,
    "ACL_DENIED": FailureDomain.CONTRACT_VALIDATION_FAILURE,
    # Timeout sentinel used in some paths
    "timeout": FailureDomain.TIMEOUT_FAILURE,
}


def classify_from_error_code(
    error_code: Optional[str],
    *,
    notes: Optional[str] = None,
) -> FailureClassification:
    """Derive a :class:`FailureClassification` from a gateway/substrate error code.

    Parameters
    ----------
    error_code:
        A ``GatewayErrorCode`` value string (e.g. ``"COMMAND_TIMEOUT"``),
        an ``"ACL_DENIED"`` sentinel, or any other error code string.
        ``None`` is handled gracefully and maps to
        :attr:`FailureDomain.UNKNOWN_FAILURE`.
    notes:
        Optional extra context to embed in the classification.

    Returns
    -------
    FailureClassification
    """
    if error_code is None:
        domain = FailureDomain.UNKNOWN_FAILURE
    else:
        domain = _GATEWAY_ERROR_CODE_MAP.get(
            str(error_code).upper() if error_code else "",
            _GATEWAY_ERROR_CODE_MAP.get(str(error_code), FailureDomain.UNKNOWN_FAILURE),
        )

    return FailureClassification(
        domain=domain,
        is_retryable=is_retryable_by_domain(domain, allow_alternate_target=True),
        is_retryable_same_target=is_retryable_by_domain(domain, allow_alternate_target=False),
        downgrade_hint=downgrade_hint_for_domain(domain),
        source_error_code=str(error_code) if error_code is not None else None,
        notes=notes,
    )


def classify_from_exception(
    exc: Exception,
    *,
    notes: Optional[str] = None,
) -> FailureClassification:
    """Derive a :class:`FailureClassification` from an exception instance.

    Inspects common exception types and their messages to select the most
    appropriate failure domain.  Falls back to
    :attr:`FailureDomain.LOCAL_RUNTIME_FAILURE` for unrecognised exceptions.

    Parameters
    ----------
    exc:
        The exception that caused the failure.
    notes:
        Optional extra context.

    Returns
    -------
    FailureClassification
    """
    exc_name = type(exc).__name__
    exc_str = str(exc).lower()

    if "timeout" in exc_name.lower() or "timeout" in exc_str or "timed out" in exc_str:
        domain = FailureDomain.TIMEOUT_FAILURE
    elif "connect" in exc_str or "disconnect" in exc_str or "network" in exc_str:
        domain = FailureDomain.GATEWAY_TRANSPORT_FAILURE
    elif "unavailable" in exc_str or "offline" in exc_str or "not found" in exc_str:
        domain = FailureDomain.REMOTE_DEVICE_UNAVAILABLE
    elif "capability" in exc_str or "mismatch" in exc_str or "not supported" in exc_str:
        domain = FailureDomain.REMOTE_CAPABILITY_MISMATCH
    elif "validation" in exc_str or "acl" in exc_str or "denied" in exc_str:
        domain = FailureDomain.CONTRACT_VALIDATION_FAILURE
    else:
        domain = FailureDomain.LOCAL_RUNTIME_FAILURE

    return FailureClassification(
        domain=domain,
        is_retryable=is_retryable_by_domain(domain, allow_alternate_target=True),
        is_retryable_same_target=is_retryable_by_domain(domain, allow_alternate_target=False),
        downgrade_hint=downgrade_hint_for_domain(domain),
        source_error_code=exc_name,
        notes=notes,
    )
