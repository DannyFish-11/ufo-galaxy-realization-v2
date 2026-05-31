"""
core/llm/failover.py — LLM Provider Failover Strategy
======================================================

**Batch PR-5: Multi-LLM routing decomposition**

This module extracts the failover / circuit-breaker logic from
``core.multi_llm_router`` into an explicit, testable submodule.

Authority sentinel
------------------
``LLM_FAILOVER_AUTHORITY = "core.llm.failover"``

Responsibilities
----------------
* ``ProviderCircuitBreaker`` — per-provider circuit breaker (re-exported
  from ``core.multi_llm_router`` for the package-based import path).
* ``FailoverStrategy`` — orchestrates retries across multiple providers,
  using circuit-breaker state to skip broken providers.
* ``RetryPolicy`` — configures retry counts, backoff, and jitter.

Design
------
``FailoverStrategy.execute()`` accepts an ordered list of (provider, model)
candidates and an async callable that performs the actual LLM call.  It
iterates the candidate list, skipping providers whose circuit breaker is
open, and returns on the first success.  On exhaustion it raises the last
observed exception.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from core.multi_llm_router import ProviderCircuitBreaker, ProviderStatus

logger = logging.getLogger("Galaxy.LLM.Failover")

# ── module authority sentinel ─────────────────────────────────────────────
LLM_FAILOVER_AUTHORITY: str = "core.llm.failover"
"""Sentinel: core.llm.failover is the canonical LLM failover strategy module.

Import this symbol to assert that a call site is using the decomposed
failover module rather than ad-hoc retry logic.
"""


@dataclass
class RetryPolicy:
    """Configuration for failover retry behaviour.

    Attributes
    ----------
    max_retries:
        Maximum number of provider switch attempts before giving up.
    base_delay_s:
        Base delay between retry attempts in seconds (used with
        exponential backoff).
    max_delay_s:
        Maximum delay cap in seconds.
    jitter:
        If ``True``, adds random jitter to the delay.
    """

    max_retries: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 10.0
    jitter: bool = True

    def compute_delay(self, attempt: int) -> float:
        """Return the delay for *attempt* (0-indexed) in seconds."""
        safe_exp = min(attempt, 20)  # cap exponent to prevent overflow
        delay = min(self.base_delay_s * (2 ** safe_exp), self.max_delay_s)
        if self.jitter:
            delay *= (0.5 + random.random() * 0.5)
        return delay


# ── type alias ────────────────────────────────────────────────────────────
ProviderCallable = Callable[[str, str, Any], Awaitable[Any]]
"""Async callable: (provider_name, model, request) → response."""

Candidate = Tuple[str, str]
"""(provider_name, model_name)"""


class FailoverStrategy:
    """Orchestrate retries across multiple LLM providers.

    Parameters
    ----------
    circuit_breakers:
        Dict of provider name → ``ProviderCircuitBreaker``.  Used to
        determine which providers are currently available.
    retry_policy:
        Configures retry counts and backoff.
    """

    def __init__(
        self,
        circuit_breakers: Optional[Dict[str, ProviderCircuitBreaker]] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        self._cbs: Dict[str, ProviderCircuitBreaker] = dict(circuit_breakers or {})
        self._policy = retry_policy or RetryPolicy()
        self._stats: Dict[str, int] = {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "provider_switches": 0,
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(
        self,
        candidates: List[Candidate],
        call: ProviderCallable,
        request: Any,
    ) -> Any:
        """Try each candidate in order, failing over on error.

        Parameters
        ----------
        candidates:
            Ordered list of ``(provider_name, model)`` tuples.  The first
            element is the primary provider; subsequent elements are
            fallbacks.
        call:
            Async callable that performs the actual LLM request.
            Signature: ``async def call(provider, model, request) -> response``
        request:
            The request payload passed verbatim to *call*.

        Returns
        -------
        Any:
            The first successful response.

        Raises
        ------
        Exception:
            If all candidates fail, re-raises the last exception.
        """
        last_exc: Optional[Exception] = None

        for attempt_idx, (provider, model) in enumerate(candidates):
            cb = self._cbs.get(provider)
            if cb is not None and not cb.allow_request():
                logger.debug(
                    "FailoverStrategy: circuit open for '%s', skipping", provider
                )
                self._stats["provider_switches"] += 1
                continue

            self._stats["attempts"] += 1
            try:
                if attempt_idx > 0:
                    delay = self._policy.compute_delay(attempt_idx - 1)
                    logger.debug(
                        "FailoverStrategy: retry attempt=%d provider=%s delay=%.2fs",
                        attempt_idx,
                        provider,
                        delay,
                    )
                    await asyncio.sleep(delay)

                result = await call(provider, model, request)

                if cb is not None:
                    cb.record_success()
                self._stats["successes"] += 1
                if attempt_idx > 0:
                    self._stats["provider_switches"] += 1
                return result

            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                last_exc = exc
                if cb is not None:
                    cb.record_failure()
                self._stats["failures"] += 1
                logger.warning(
                    "FailoverStrategy: provider='%s' model='%s' failed: %s",
                    provider,
                    model,
                    exc,
                )

                if attempt_idx >= self._policy.max_retries:
                    logger.error(
                        "FailoverStrategy: exhausted all %d retries", attempt_idx + 1
                    )
                    break

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("FailoverStrategy: no candidates available")

    # ------------------------------------------------------------------
    # Circuit-breaker management
    # ------------------------------------------------------------------

    def register_circuit_breaker(
        self, provider: str, cb: ProviderCircuitBreaker
    ) -> None:
        """Register (or replace) the circuit breaker for *provider*."""
        self._cbs[provider] = cb

    def get_circuit_breaker_state(self, provider: str) -> Optional[str]:
        """Return the current circuit breaker state string for *provider*."""
        cb = self._cbs.get(provider)
        if cb is None:
            return None
        return cb.state

    def get_stats(self) -> Dict[str, int]:
        """Return failover execution statistics."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset all statistics counters to zero."""
        for key in self._stats:
            self._stats[key] = 0


__all__ = [
    "LLM_FAILOVER_AUTHORITY",
    "RetryPolicy",
    "FailoverStrategy",
    "ProviderCircuitBreaker",
    "Candidate",
    "ProviderCallable",
]
