#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/hybrid_execution_policy.py
=================================
PR-5: Explicit Hybrid Execution Policy

Background
----------
Prior to this module the ``HybridExecutionArbiter`` (``core/hybrid_executor.py``)
implemented only **sequential degradation** — A2A → GUI → VLM — without any
explicit concept of *mode*.  Every execution was treated the same way regardless
of context, and there was no machine-checkable distinction between:

* "This is intentionally a degrade chain" (expected fallback)
* "This is a staged hybrid" (first A2A for data retrieval, then GUI for display)
* "This is a parallel race" (A2A and GUI both launched; first success wins)

This module closes the gap by introducing:

1. :class:`HybridExecutionMode` — explicit enum of all supported execution modes.
2. :class:`HybridExecutionPolicy` — context-aware policy engine that evaluates
   a request's characteristics and returns a :class:`HybridExecutionDecision`
   declaring the selected mode and the reason it was chosen.
3. :class:`HybridExecutionDecision` — immutable, serialisable record of what
   mode was selected and why, enabling reviewable test assertions.

Design principles
-----------------
- **Additive only** — does not modify ``core.hybrid_executor``.
- **No executor logic** — this module is policy-only; it does not execute tasks.
  It is consumed by :class:`~core.hybrid_executor.HybridExecutionArbiter` to
  get the correct mode for each request.
- **Fully serialisable** — ``HybridExecutionDecision.to_dict()`` and
  ``from_dict()`` support audit/replay.
- **Testable** — all policy decisions are deterministic given the same context;
  no hidden side-effects.

Modes
-----
:attr:`HybridExecutionMode.sequential_degrade`
    The classic A2A → GUI → VLM fallback chain.  Each level is tried
    sequentially; later levels are only reached if earlier ones fail.
    This is the **existing** behaviour, now made explicit and named.

:attr:`HybridExecutionMode.parallel_race`
    A2A and GUI are launched **concurrently**; the first success is
    returned and the other is cancelled.  Use when minimising latency is
    more important than resource efficiency.

:attr:`HybridExecutionMode.staged_hybrid`
    Two stages run in sequence with explicit stage boundaries:
    Stage 1 (data retrieval / API call) and Stage 2 (UI action / display).
    Neither stage degrades into the other — if Stage 1 fails, the whole
    request fails rather than silently falling through to Stage 2.

:attr:`HybridExecutionMode.local_preferred`
    Prefer the local execution path (on-device A2A or GUI).  If the local
    path fails, fall back to a remote path (VLM reasoning via a remote
    model).  Useful when data privacy or latency makes local preferable.

:attr:`HybridExecutionMode.remote_preferred`
    Prefer a remote execution path first (e.g. cloud API or VLM).  If the
    remote path fails or is unavailable, fall back to local GUI/A2A.

Sentinels
---------
:data:`HYBRID_EXECUTION_POLICY_IS_AUTHORITY`
    Affirms this module is the canonical policy engine for hybrid execution
    mode selection.
:data:`SEQUENTIAL_DEGRADE_IS_EXPLICIT_POLICY`
    Affirms that the existing degrade-chain is now an *explicit* mode
    (``sequential_degrade``) rather than the implicit-only behaviour.
:data:`PARALLEL_RACE_IS_REAL_HYBRID_POLICY`
    Affirms that ``parallel_race`` represents *true* hybrid execution —
    multiple paths running concurrently — as opposed to sequential fallback.
:data:`DECISION_IS_SERIALISABLE_POLICY`
    Affirms that every :class:`HybridExecutionDecision` can be round-tripped
    through ``to_dict()`` / ``from_dict()`` for auditing and test assertions.
:data:`HYBRID_EXECUTION_POLICY_PR5_SENTINEL`
    Monotonic sentinel string for PR-5 feature identification.

Public API
----------
Enums::

    HybridExecutionMode

Classes::

    HybridExecutionDecision
    HybridExecutionPolicy

Functions::

    evaluate_hybrid_execution_mode(context) -> HybridExecutionDecision
    get_hybrid_execution_policy() -> HybridExecutionPolicy
    reset_hybrid_execution_policy() -> None
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.HybridExecutionPolicy")

__all__ = [
    # Sentinels
    "HYBRID_EXECUTION_POLICY_IS_AUTHORITY",
    "SEQUENTIAL_DEGRADE_IS_EXPLICIT_POLICY",
    "PARALLEL_RACE_IS_REAL_HYBRID_POLICY",
    "DECISION_IS_SERIALISABLE_POLICY",
    "HYBRID_EXECUTION_POLICY_PR5_SENTINEL",
    # Enums
    "HybridExecutionMode",
    # Classes
    "HybridExecutionDecision",
    "HybridExecutionPolicy",
    # Functions
    "evaluate_hybrid_execution_mode",
    "get_hybrid_execution_policy",
    "reset_hybrid_execution_policy",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

HYBRID_EXECUTION_POLICY_IS_AUTHORITY: str = (
    "HYBRID_EXECUTION_POLICY_IS_AUTHORITY: "
    "core/hybrid_execution_policy.py is the canonical policy engine for "
    "selecting hybrid execution modes in the Galaxy runtime (PR-5)."
)

SEQUENTIAL_DEGRADE_IS_EXPLICIT_POLICY: str = (
    "POLICY::SEQUENTIAL_DEGRADE_IS_EXPLICIT: the classic A2A→GUI→VLM "
    "degrade chain is now an explicit named mode (HybridExecutionMode."
    "sequential_degrade) rather than implicit-only behaviour.  All paths "
    "through HybridExecutionArbiter MUST declare their mode via "
    "HybridExecutionPolicy before execution."
)

PARALLEL_RACE_IS_REAL_HYBRID_POLICY: str = (
    "POLICY::PARALLEL_RACE_IS_REAL_HYBRID: HybridExecutionMode.parallel_race "
    "represents true hybrid execution where multiple execution paths run "
    "concurrently and the first success is returned.  This is NOT a degrade "
    "chain; it is a genuine multi-path concurrent execution."
)

DECISION_IS_SERIALISABLE_POLICY: str = (
    "POLICY::DECISION_IS_SERIALISABLE: every HybridExecutionDecision MUST "
    "be round-trippable through to_dict() / from_dict() to enable auditing, "
    "replay, and test assertions."
)

HYBRID_EXECUTION_POLICY_PR5_SENTINEL: str = (
    "HYBRID_EXECUTION_POLICY_PR5::hybrid-execution-policy-explicit-modes-pr5-v1"
)


# ---------------------------------------------------------------------------
# HybridExecutionMode
# ---------------------------------------------------------------------------


class HybridExecutionMode(str, Enum):
    """Explicit modes of hybrid execution supported by the Galaxy runtime.

    Attributes
    ----------
    sequential_degrade
        Classic A2A → GUI → VLM degrade chain.  Each level is tried
        sequentially; later levels are only attempted if earlier ones fail.
        This names the **existing** HybridExecutionArbiter behaviour explicitly.
    parallel_race
        A2A and GUI are launched **concurrently**.  The first to succeed
        wins; the other is cancelled.  True hybrid execution: multiple paths
        compete for the result.
    staged_hybrid
        Two explicit stages run in sequence with hard boundaries.  Stage 1
        performs data retrieval / API interaction (A2A); Stage 2 performs UI
        presentation / action (GUI).  Neither stage silently degrades into
        the other.
    local_preferred
        Prefer on-device local execution (A2A or GUI on the local device).
        Fall back to remote VLM reasoning only if local fails.
    remote_preferred
        Prefer remote execution first (cloud API or remote VLM).  Fall back
        to local GUI/A2A if remote is unavailable or fails.
    """

    sequential_degrade = "sequential_degrade"
    parallel_race = "parallel_race"
    staged_hybrid = "staged_hybrid"
    local_preferred = "local_preferred"
    remote_preferred = "remote_preferred"

    @classmethod
    def from_string(
        cls, value: str, default: Optional["HybridExecutionMode"] = None
    ) -> "HybridExecutionMode":
        """Parse *value* into a :class:`HybridExecutionMode`.

        Returns *default* (or ``sequential_degrade``) for unrecognised values.
        """
        try:
            return cls(value)
        except ValueError:
            return default if default is not None else cls.sequential_degrade

    @property
    def is_concurrent(self) -> bool:
        """True if this mode launches multiple execution paths concurrently."""
        return self == HybridExecutionMode.parallel_race

    @property
    def is_degrade_chain(self) -> bool:
        """True if this mode follows a sequential fallback / degradation chain."""
        return self in (
            HybridExecutionMode.sequential_degrade,
            HybridExecutionMode.local_preferred,
            HybridExecutionMode.remote_preferred,
        )


# ---------------------------------------------------------------------------
# HybridExecutionDecision
# ---------------------------------------------------------------------------


@dataclass
class HybridExecutionDecision:
    """Immutable record of a hybrid execution mode selection.

    Attributes
    ----------
    decision_id
        Unique identifier for this decision record.
    mode
        The :class:`HybridExecutionMode` that was selected.
    reason
        Human-readable explanation of why this mode was selected.
    context_snapshot
        Snapshot of the context dict that drove the selection (for auditing).
    confidence
        0.0–1.0 confidence score for this selection.  1.0 = exact match to
        a rule; 0.5 = heuristic; 0.0 = default/fallback.
    decided_at
        Wall-clock timestamp when the decision was made.
    policy_version
        Semantic version of the policy that produced this decision.
    """

    mode: HybridExecutionMode
    reason: str
    decision_id: str = field(default_factory=lambda: f"hdec_{uuid.uuid4().hex[:12]}")
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    decided_at: float = field(default_factory=time.time)
    policy_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "decision_id": self.decision_id,
            "mode": self.mode.value if isinstance(self.mode, HybridExecutionMode) else str(self.mode),
            "reason": self.reason,
            "context_snapshot": self.context_snapshot,
            "confidence": self.confidence,
            "decided_at": self.decided_at,
            "policy_version": self.policy_version,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "HybridExecutionDecision":
        """Deserialise from *data*.

        Raises ``ValueError`` if *data* is not a dict.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"HybridExecutionDecision.from_dict expects a dict, got "
                f"{type(data).__name__!r}"
            )
        return cls(
            decision_id=data.get("decision_id", f"hdec_{uuid.uuid4().hex[:12]}"),
            mode=HybridExecutionMode.from_string(data.get("mode", "sequential_degrade")),
            reason=data.get("reason", ""),
            context_snapshot=dict(data.get("context_snapshot") or {}),
            confidence=float(data.get("confidence", 1.0)),
            decided_at=float(data.get("decided_at", time.time())),
            policy_version=data.get("policy_version", "1.0"),
        )


# ---------------------------------------------------------------------------
# HybridExecutionPolicy — the rule engine
# ---------------------------------------------------------------------------


class HybridExecutionPolicy:
    """Context-aware policy engine for hybrid execution mode selection.

    The policy evaluates a context dict and returns a
    :class:`HybridExecutionDecision` declaring the appropriate
    :class:`HybridExecutionMode`.

    Context fields
    --------------
    ``app_id`` (str)
        Target application identifier.
    ``action`` (str)
        The action to execute (e.g. ``"send_message"``, ``"open_url"``).
    ``device_id`` (str)
        Target device identifier.
    ``has_a2a`` (bool)
        True if an A2A endpoint is available for this app/action.
    ``has_gui`` (bool)
        True if GUI automation is available for this device.
    ``has_vlm`` (bool)
        True if a VLM executor is configured.
    ``latency_sensitive`` (bool)
        True if the caller requires minimum latency (favours parallel_race).
    ``staged_actions`` (list[str])
        When provided and non-empty, indicates the request has multiple
        discrete stages (favours staged_hybrid).
    ``prefer_local`` (bool)
        True if the caller explicitly prefers local execution paths.
    ``prefer_remote`` (bool)
        True if the caller explicitly prefers remote execution paths.
    ``force_mode`` (str)
        When non-empty, bypass all heuristics and return this mode.

    Rules (in priority order)
    -------------------------
    1. ``force_mode`` set → return exactly that mode.
    2. ``staged_actions`` non-empty → ``staged_hybrid``.
    3. ``latency_sensitive`` AND ``has_a2a`` AND ``has_gui`` → ``parallel_race``.
    4. ``prefer_local`` → ``local_preferred``.
    5. ``prefer_remote`` → ``remote_preferred``.
    6. Default → ``sequential_degrade``.
    """

    VERSION: str = "1.0"

    def evaluate(self, context: Dict[str, Any]) -> HybridExecutionDecision:
        """Evaluate *context* and return a :class:`HybridExecutionDecision`.

        Parameters
        ----------
        context:
            Dict of execution context fields (see class docstring for keys).

        Returns
        -------
        :class:`HybridExecutionDecision`
            Immutable record of the selected mode and the reason.
        """
        ctx = context or {}
        # Sanitise snapshot — strip any non-serialisable values for safety
        snapshot = {k: v for k, v in ctx.items() if isinstance(v, (str, int, float, bool, list, type(None)))}

        # ----------------------------------------------------------------
        # Rule 1: caller-forced mode
        # ----------------------------------------------------------------
        force_mode_raw = ctx.get("force_mode", "")
        if force_mode_raw:
            mode = HybridExecutionMode.from_string(str(force_mode_raw))
            return HybridExecutionDecision(
                mode=mode,
                reason=f"Explicit force_mode={force_mode_raw!r} supplied by caller.",
                context_snapshot=snapshot,
                confidence=1.0,
                policy_version=self.VERSION,
            )

        # ----------------------------------------------------------------
        # Rule 2: staged actions → staged_hybrid
        # ----------------------------------------------------------------
        staged_actions: List[str] = ctx.get("staged_actions") or []
        if staged_actions:
            return HybridExecutionDecision(
                mode=HybridExecutionMode.staged_hybrid,
                reason=(
                    f"Request has {len(staged_actions)} explicit stage(s) "
                    f"({staged_actions!r}); selecting staged_hybrid to enforce "
                    "hard stage boundaries without silent level degradation."
                ),
                context_snapshot=snapshot,
                confidence=0.95,
                policy_version=self.VERSION,
            )

        # ----------------------------------------------------------------
        # Rule 3: latency-sensitive + A2A + GUI → parallel_race (true hybrid)
        # ----------------------------------------------------------------
        latency_sensitive = bool(ctx.get("latency_sensitive", False))
        has_a2a = bool(ctx.get("has_a2a", False))
        has_gui = bool(ctx.get("has_gui", False))
        if latency_sensitive and has_a2a and has_gui:
            return HybridExecutionDecision(
                mode=HybridExecutionMode.parallel_race,
                reason=(
                    "latency_sensitive=True with both A2A and GUI available; "
                    "parallel_race selected to minimise end-to-end latency by "
                    "launching both paths concurrently (true hybrid execution)."
                ),
                context_snapshot=snapshot,
                confidence=0.9,
                policy_version=self.VERSION,
            )

        # ----------------------------------------------------------------
        # Rule 4: explicit local preference
        # ----------------------------------------------------------------
        prefer_local = bool(ctx.get("prefer_local", False))
        if prefer_local:
            return HybridExecutionDecision(
                mode=HybridExecutionMode.local_preferred,
                reason=(
                    "prefer_local=True; local execution path takes priority "
                    "with remote VLM as fallback."
                ),
                context_snapshot=snapshot,
                confidence=0.85,
                policy_version=self.VERSION,
            )

        # ----------------------------------------------------------------
        # Rule 5: explicit remote preference
        # ----------------------------------------------------------------
        prefer_remote = bool(ctx.get("prefer_remote", False))
        if prefer_remote:
            return HybridExecutionDecision(
                mode=HybridExecutionMode.remote_preferred,
                reason=(
                    "prefer_remote=True; remote execution path takes priority "
                    "with local GUI/A2A as fallback."
                ),
                context_snapshot=snapshot,
                confidence=0.85,
                policy_version=self.VERSION,
            )

        # ----------------------------------------------------------------
        # Rule 6: default — sequential_degrade (existing HybridExecutionArbiter
        #   behaviour, now made explicit)
        # ----------------------------------------------------------------
        return HybridExecutionDecision(
            mode=HybridExecutionMode.sequential_degrade,
            reason=(
                "No specific rule matched; defaulting to sequential_degrade "
                "(A2A → GUI → VLM fallback chain).  This is the canonical "
                "degrade-chain behaviour of HybridExecutionArbiter, now "
                "declared explicitly."
            ),
            context_snapshot=snapshot,
            confidence=0.5,
            policy_version=self.VERSION,
        )

    def describe_mode(self, mode: HybridExecutionMode) -> str:
        """Return a human-readable description of *mode*."""
        descriptions = {
            HybridExecutionMode.sequential_degrade: (
                "Sequential degradation chain: A2A → GUI → VLM.  Each level "
                "is tried in sequence; later levels only if earlier ones fail."
            ),
            HybridExecutionMode.parallel_race: (
                "Parallel race: A2A and GUI launched concurrently; first "
                "success returned, other cancelled.  True hybrid execution."
            ),
            HybridExecutionMode.staged_hybrid: (
                "Staged hybrid: Stage 1 (A2A data retrieval) then Stage 2 "
                "(GUI presentation).  Hard boundaries; no silent degradation."
            ),
            HybridExecutionMode.local_preferred: (
                "Local-preferred: try local A2A/GUI first; fall back to "
                "remote VLM only on failure."
            ),
            HybridExecutionMode.remote_preferred: (
                "Remote-preferred: try remote API/VLM first; fall back to "
                "local GUI/A2A on failure."
            ),
        }
        return descriptions.get(mode, f"Unknown mode: {mode!r}")


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_policy_instance: Optional[HybridExecutionPolicy] = None


def get_hybrid_execution_policy() -> HybridExecutionPolicy:
    """Return the process-level :class:`HybridExecutionPolicy` singleton."""
    global _policy_instance
    if _policy_instance is None:
        _policy_instance = HybridExecutionPolicy()
    return _policy_instance


def reset_hybrid_execution_policy() -> None:
    """Reset the singleton (for testing)."""
    global _policy_instance
    _policy_instance = None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def evaluate_hybrid_execution_mode(
    context: Dict[str, Any],
    policy: Optional[HybridExecutionPolicy] = None,
) -> HybridExecutionDecision:
    """Evaluate *context* and return a :class:`HybridExecutionDecision`.

    Parameters
    ----------
    context:
        Execution context dict (see :class:`HybridExecutionPolicy` for fields).
    policy:
        Optional policy instance to use.  Defaults to the process-level
        singleton returned by :func:`get_hybrid_execution_policy`.

    Returns
    -------
    :class:`HybridExecutionDecision`
    """
    p = policy or get_hybrid_execution_policy()
    return p.evaluate(context)
