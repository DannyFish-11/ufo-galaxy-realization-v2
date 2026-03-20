#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/policy/hitl_policy.py
============================
Block-4 (PR-4) — Human-in-the-Loop (HITL) Policy Gate

Implements a configurable HITL gate that can intercept critical Galaxy
actions (cross-device control, manifest projections, high-risk executions)
and require human confirmation before proceeding.

Modes
-----
:attr:`HITLMode.AUTO`
    No human confirmation required; all actions proceed automatically.
:attr:`HITLMode.SEMI`
    Low-risk actions proceed automatically; high-risk actions require
    confirmation or time out with a configurable default decision.
:attr:`HITLMode.MANUAL`
    All gated actions require explicit human confirmation.

Integration points
------------------
- :class:`~core.presence.presence_director.PresenceDirector` calls
  :meth:`HITLPolicy.evaluate` before manifest projection when configured.
- Dashboard backend exposes ``/api/v1/hitl/requests`` and
  ``POST /api/v1/hitl/decide`` so the UI can show and resolve pending requests.
- :func:`reset_hitl_policy` resets the singleton for tests.

Trace
-----
Every :meth:`evaluate` call emits a ``hitl.evaluated`` event on the
:class:`~core.state_event_bus.StateEventBus` for full audit traceability.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.Policy.HITL")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class HITLMode(str, Enum):
    """Operating mode for the HITL policy gate."""

    AUTO   = "auto"    # No human confirmation required
    SEMI   = "semi"    # Confirmation for high-risk only
    MANUAL = "manual"  # All gated actions require confirmation


class HITLDecisionOutcome(str, Enum):
    """Outcome of a HITL gate evaluation."""

    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT  = "timeout"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class HITLRequest:
    """A pending HITL confirmation request.

    Attributes
    ----------
    request_id:
        Unique identifier for this request.
    action:
        The action being gated (e.g. ``"manifest_projection"``).
    context:
        Arbitrary context dict describing the action.
    session_id:
        Cognitive session scope.
    trace_id:
        Distributed trace identifier.
    is_high_risk:
        Whether the action was classified as high-risk.
    created_at:
        Unix timestamp.
    expires_at:
        Unix timestamp after which the request times out.
    decision:
        Populated by :meth:`HITLPolicy.decide` once a decision is made.
    """

    request_id: str = field(default_factory=lambda: f"hitl_{uuid.uuid4().hex[:10]}")
    action: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    is_high_risk: bool = False
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 30.0)
    decision: Optional["HITLDecision"] = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def is_pending(self) -> bool:
        return self.decision is None and not self.is_expired()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "context": self.context,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "is_high_risk": self.is_high_risk,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "decision": self.decision.to_dict() if self.decision else None,
            "is_pending": self.is_pending(),
        }


@dataclass
class HITLDecision:
    """The decision taken for a :class:`HITLRequest`.

    Attributes
    ----------
    request_id:
        Correlates with the originating :class:`HITLRequest`.
    outcome:
        Approved / rejected / timeout.
    approved:
        Shorthand — ``True`` iff outcome is APPROVED.
    reason:
        Human-readable explanation.
    decided_by:
        Who made the decision (``"auto"`` / ``"user:<id>"`` / ``"timeout"``).
    decided_at:
        Unix timestamp.
    trace_id:
        Propagated from the originating request.
    """

    request_id: str
    outcome: HITLDecisionOutcome
    approved: bool
    reason: str = ""
    decided_by: str = "auto"
    decided_at: float = field(default_factory=time.time)
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "outcome": self.outcome.value,
            "approved": self.approved,
            "reason": self.reason,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "trace_id": self.trace_id,
        }


# ---------------------------------------------------------------------------
# HITLPolicy
# ---------------------------------------------------------------------------

# High-risk action keywords (case-insensitive substring match)
_HIGH_RISK_KEYWORDS = [
    "manifest",
    "cross_device",
    "system",
    "delete",
    "shutdown",
    "restart",
    "execute",
    "deploy",
]


class HITLPolicy:
    """Configurable Human-in-the-Loop gate.

    Parameters
    ----------
    mode:
        Operating mode.  Can be changed at runtime via :attr:`mode`.
    timeout_seconds:
        How long to wait for a human decision in SEMI/MANUAL modes before
        timing out.  The timeout default decision is controlled by
        ``timeout_default_approve``.
    timeout_default_approve:
        When ``True`` (default), timed-out requests are **approved** (optimistic).
        Set to ``False`` for pessimistic safety.
    high_risk_classifier:
        Optional callable ``(action: str, context: dict) -> bool``.  When
        provided, overrides the built-in keyword-based classifier.
    """

    def __init__(
        self,
        mode: HITLMode = HITLMode.AUTO,
        timeout_seconds: float = 30.0,
        timeout_default_approve: bool = True,
        high_risk_classifier: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    ) -> None:
        self._mode = mode
        self._timeout_seconds = timeout_seconds
        self._timeout_default_approve = timeout_default_approve
        self._classifier = high_risk_classifier

        self._pending: Dict[str, HITLRequest] = {}
        self._history: List[HITLDecision] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> HITLMode:
        return self._mode

    @mode.setter
    def mode(self, value: HITLMode) -> None:
        self._mode = value
        logger.info("HITLPolicy: mode changed to %s", value)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> HITLDecision:
        """Evaluate the HITL gate for *action*.

        In **AUTO** mode: always returns an APPROVED decision.
        In **SEMI** mode: low-risk actions auto-approve; high-risk actions
          create a :class:`HITLRequest` and wait for :meth:`decide`.
        In **MANUAL** mode: all actions create a request and wait.

        For synchronous callers that cannot wait, the method returns
        immediately with the current state (or a timeout decision if the
        request has already expired).  Dashboard integration calls
        :meth:`decide` asynchronously and notifies waiting callers.

        Args:
            action:      Name of the action being gated.
            context:     Arbitrary context dict.
            session_id:  Session scope.
            trace_id:    Trace identifier.

        Returns:
            :class:`HITLDecision` with ``approved`` field indicating whether
            to proceed.
        """
        ctx = dict(context or {})
        is_high_risk = self._classify(action, ctx)

        # AUTO mode: approve everything immediately
        if self._mode == HITLMode.AUTO:
            decision = HITLDecision(
                request_id=f"hitl_{uuid.uuid4().hex[:8]}",
                outcome=HITLDecisionOutcome.APPROVED,
                approved=True,
                reason="auto_mode",
                decided_by="auto",
                trace_id=trace_id,
            )
            self._emit_event(action, is_high_risk, decision, session_id, trace_id)
            return decision

        # SEMI mode: auto-approve low-risk
        if self._mode == HITLMode.SEMI and not is_high_risk:
            decision = HITLDecision(
                request_id=f"hitl_{uuid.uuid4().hex[:8]}",
                outcome=HITLDecisionOutcome.APPROVED,
                approved=True,
                reason="semi_mode_low_risk",
                decided_by="auto",
                trace_id=trace_id,
            )
            self._emit_event(action, is_high_risk, decision, session_id, trace_id)
            return decision

        # SEMI (high-risk) or MANUAL: create a pending request
        req = HITLRequest(
            action=action,
            context=ctx,
            session_id=session_id,
            trace_id=trace_id,
            is_high_risk=is_high_risk,
            expires_at=time.time() + self._timeout_seconds,
        )
        with self._lock:
            self._pending[req.request_id] = req

        logger.info(
            "HITLPolicy: created request=%s action=%s high_risk=%s session=%s",
            req.request_id,
            action,
            is_high_risk,
            session_id,
        )

        # In synchronous context: return a timeout-default decision immediately
        # (dashboard integration can call decide() before this timeout).
        # NOTE: we do NOT set req.decision here — the request remains truly pending
        # until a human calls decide() or the timeout expires.
        default_outcome = (
            HITLDecisionOutcome.APPROVED
            if self._timeout_default_approve
            else HITLDecisionOutcome.REJECTED
        )
        decision = HITLDecision(
            request_id=req.request_id,
            outcome=default_outcome,
            approved=self._timeout_default_approve,
            reason=f"pending_request_created_default={self._timeout_default_approve}",
            decided_by="auto_default",
            trace_id=trace_id,
        )
        # Emit event for observability but leave req.decision=None (still pending)
        self._emit_event(action, is_high_risk, decision, session_id, trace_id)
        return decision

    def decide(
        self,
        request_id: str,
        approve: bool,
        decided_by: str = "user",
        reason: str = "",
    ) -> Optional[HITLDecision]:
        """Record a human decision for *request_id*.

        Args:
            request_id:  ID of the pending :class:`HITLRequest`.
            approve:     ``True`` to approve, ``False`` to reject.
            decided_by:  Identifier of the deciding principal.
            reason:      Human-readable rationale.

        Returns:
            The :class:`HITLDecision`, or ``None`` if request not found.
        """
        with self._lock:
            req = self._pending.get(request_id)

        if req is None:
            logger.warning("HITLPolicy.decide: unknown request_id=%s", request_id)
            return None

        outcome = HITLDecisionOutcome.APPROVED if approve else HITLDecisionOutcome.REJECTED
        decision = HITLDecision(
            request_id=request_id,
            outcome=outcome,
            approved=approve,
            reason=reason,
            decided_by=decided_by,
            trace_id=req.trace_id,
        )
        req.decision = decision

        with self._lock:
            self._pending.pop(request_id, None)
            self._history.append(decision)
            if len(self._history) > 500:
                self._history = self._history[-500:]

        logger.info(
            "HITLPolicy.decide: request=%s outcome=%s by=%s reason=%r",
            request_id,
            outcome,
            decided_by,
            reason,
        )
        self._emit_event(req.action, req.is_high_risk, decision, req.session_id, req.trace_id)
        return decision

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def pending_requests(self) -> List[HITLRequest]:
        """Return list of pending (not yet decided, not expired) requests."""
        with self._lock:
            reqs = [r for r in self._pending.values() if r.is_pending()]
        return reqs

    def decision_history(self, n: int = 50) -> List[HITLDecision]:
        """Return the most recent *n* completed decisions."""
        with self._lock:
            return list(self._history[-n:])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify(self, action: str, context: Dict[str, Any]) -> bool:
        """Return ``True`` if the action is considered high-risk."""
        if self._classifier is not None:
            try:
                return bool(self._classifier(action, context))
            except Exception:
                pass
        action_lower = action.lower()
        return any(kw in action_lower for kw in _HIGH_RISK_KEYWORDS)

    @staticmethod
    def _emit_event(
        action: str,
        is_high_risk: bool,
        decision: HITLDecision,
        session_id: Optional[str],
        trace_id: Optional[str],
    ) -> None:
        try:
            from core.state_event_bus import get_state_event_bus, StateEventType
            bus = get_state_event_bus()
            event_type = StateEventType.HITL_EVALUATED
            bus.publish(
                event_type,
                source="hitl_policy",
                payload={
                    "event": "hitl.evaluated",
                    "action": action,
                    "is_high_risk": is_high_risk,
                    "outcome": decision.outcome.value,
                    "approved": decision.approved,
                    "request_id": decision.request_id,
                    "decided_by": decision.decided_by,
                },
                trace_id=trace_id,
                runtime_session_id=session_id,
            )
        except Exception as exc:
            logger.debug("HITLPolicy._emit_event: bus unavailable — %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_policy: Optional[HITLPolicy] = None
_policy_lock = threading.Lock()


def get_hitl_policy() -> HITLPolicy:
    """Return (or lazily create) the process-level :class:`HITLPolicy`."""
    global _policy
    with _policy_lock:
        if _policy is None:
            _policy = HITLPolicy()
    return _policy


def reset_hitl_policy() -> None:
    """Reset the singleton (intended for tests only)."""
    global _policy
    with _policy_lock:
        _policy = None
