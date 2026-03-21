#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.reliability_contract.retry_policy
=========================================

PR-19 (V4) — Reliability Contract & Delivery Semantics

Defines :class:`RetryPolicy` — a serialisable policy describing the retry
contract for a message path.

This module does **not** implement retry logic.  Actual retry behaviour lives
in the transport and runtime layers.  :class:`RetryPolicy` describes the
*contract* — what retry semantics are defined, who owns them, and what the
advisory limits are.

Design notes
-------------
- All numeric fields have safe sentinel defaults so policies can be
  constructed with partial metadata.
- ``owner`` is a free-form string matching the pattern used in
  :class:`~core.reliability_contract.timeout_owner.TimeoutOwner` /
  :class:`~core.reliability_contract.fallback_owner.FallbackOwner`.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional

__all__ = [
    "RetryPolicy",
    "NO_RETRY_POLICY",
    "TRANSPORT_RETRY_POLICY",
    "RUNTIME_RETRY_POLICY",
    "COORDINATOR_RETRY_POLICY",
]


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    """Serialisable policy describing the retry contract for a message path.

    Attributes
    ----------
    max_attempts:
        Maximum total delivery attempts (including the first attempt).
        ``1`` means no retries.  ``0`` means retry behaviour is not defined.
    backoff_base_ms:
        Base backoff interval in milliseconds between attempts.
        ``0`` means no backoff hint.
    backoff_multiplier:
        Exponential backoff multiplier applied to *backoff_base_ms* after
        each failed attempt.  ``1.0`` means constant (no exponential growth).
    owner:
        Component responsible for executing retries, e.g. ``"transport"``,
        ``"runtime"``, ``"coordinator"``.  Matches
        :class:`~core.reliability_contract.timeout_owner.TimeoutOwner` values
        where applicable.
    retry_on_timeout:
        Whether a timeout (no ack within hint window) triggers a retry.
    retry_on_error:
        Whether a transport/runtime error triggers a retry.
    notes:
        Optional clarification.
    schema_version:
        Schema version integer.
    """

    max_attempts: int = 1
    backoff_base_ms: int = 0
    backoff_multiplier: float = 1.0
    owner: str = "unspecified"
    retry_on_timeout: bool = False
    retry_on_error: bool = False
    notes: Optional[str] = None
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def has_retries(self) -> bool:
        """Return ``True`` if this policy defines more than one attempt."""
        return self.max_attempts > 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "max_attempts": self.max_attempts,
            "backoff_base_ms": self.backoff_base_ms,
            "backoff_multiplier": self.backoff_multiplier,
            "owner": self.owner,
            "retry_on_timeout": self.retry_on_timeout,
            "retry_on_error": self.retry_on_error,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryPolicy":
        """Reconstruct from a serialised dict.  Unknown fields are silently defaulted."""
        return cls(
            max_attempts=int(data.get("max_attempts", 1)),
            backoff_base_ms=int(data.get("backoff_base_ms", 0)),
            backoff_multiplier=float(data.get("backoff_multiplier", 1.0)),
            owner=str(data.get("owner", "unspecified")),
            retry_on_timeout=bool(data.get("retry_on_timeout", False)),
            retry_on_error=bool(data.get("retry_on_error", False)),
            notes=data.get("notes"),
            schema_version=int(data.get("schema_version", 1)),
        )


# ---------------------------------------------------------------------------
# Pre-built policy sentinels
# ---------------------------------------------------------------------------

#: No retries — fire-and-forget / best-effort paths.
NO_RETRY_POLICY = RetryPolicy(
    max_attempts=1,
    backoff_base_ms=0,
    backoff_multiplier=1.0,
    owner="none",
    retry_on_timeout=False,
    retry_on_error=False,
    notes="No retry defined; single attempt only.",
    schema_version=1,
)

#: Transport-owned retry — up to 3 attempts with 500 ms base backoff.
TRANSPORT_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    backoff_base_ms=500,
    backoff_multiplier=2.0,
    owner="transport",
    retry_on_timeout=True,
    retry_on_error=True,
    notes="Transport-layer retry; exponential backoff, 3 attempts max.",
    schema_version=1,
)

#: Runtime-owned retry — up to 2 attempts for runtime handoff / bridge paths.
RUNTIME_RETRY_POLICY = RetryPolicy(
    max_attempts=2,
    backoff_base_ms=1_000,
    backoff_multiplier=1.0,
    owner="runtime",
    retry_on_timeout=True,
    retry_on_error=False,
    notes="Runtime-layer retry; fixed backoff, 2 attempts, timeout-triggered only.",
    schema_version=1,
)

#: Coordinator-owned retry — up to 3 attempts for orchestration paths.
COORDINATOR_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    backoff_base_ms=2_000,
    backoff_multiplier=1.5,
    owner="coordinator",
    retry_on_timeout=True,
    retry_on_error=True,
    notes="Coordinator-owned retry with exponential backoff; 3 attempts max.",
    schema_version=1,
)
