#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/conversation_continuity_truth.py
======================================
PR-12 (post-533 dual-repo runtime-unification track):
Conversation Continuity Truth — formal taxonomy and contract for determining
authoritative conversation continuity after crash / restart / process death /
partial recovery.

Problem addressed
-----------------
After a crash, restart, or process death the Galaxy V2 runtime can restore
*state* (session records re-hydrated, task history visible, partial results
present).  However, previously the system had no formal contract that
distinguished:

* **State restored** (session records are visible, history can be read)
  from **Conversation continuity restored** (the user can genuinely rely on
  the *same* conversation thread being active and authoritative).
* **Task continuity** (a task's execution state was preserved)
  from **Conversation continuity** (the conversation layer itself is
  authoritative and the client binding is current).
* **History visibility** (past messages can be read from a durable store)
  from **Session rebinding** (the active conversation session has been
  authoritatively re-established with a live client).

This mismatch means the system could optimistically report "conversation
continuity restored" merely because:
- A session record survived in the database, OR
- Task history was replayed, OR
- A partial recovery produced some visible state.

None of those conditions alone justify claiming authoritative conversation
continuity.

This module closes that gap by defining a formal **Conversation Continuity
Truth** taxonomy and contract that:

1. Establishes five mutually exclusive and exhaustive
   :class:`ConversationContinuityClass` verdicts.
2. Defines precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient evidence always
   yields the lowest applicable class rather than the optimistic one.
4. Prohibits promoting ``history_only_restored`` or ``partial_continuity``
   to ``authoritative_continuity_restored`` without explicit rebinding and
   session confirmation evidence.
5. Provides a :class:`ConversationContinuityVerdict` dataclass that is
   consumable by recovery / readiness / acceptance pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  CONVERSATION CONTINUITY TRUTH  (this module — PR-12)              │
    │                                                                     │
    │  Five continuity classes (strictly ordered):                       │
    │    1. authoritative_continuity_restored  (highest — requires all)  │
    │    2. partial_continuity                                            │
    │    3. history_only_restored                                         │
    │    4. state_restored_rebind_required                                │
    │    5. continuity_lost                   (lowest — default)         │
    │                                                                     │
    │  Evidence dimensions evaluated:                                    │
    │    • session_confirmed   — live session re-established with client  │
    │    • history_visible     — conversation history readable from store │
    │    • state_present       — session/task state present in registry  │
    │    • rebind_completed    — active client rebinding confirmed        │
    │    • task_continuity_ok  — in-flight task continuity present        │
    │                                                                     │
    │  Downgrade semantics (crash / restart / process death):            │
    │    • Any missing required evidence → downgrade to lower class      │
    │    • history_visible alone → history_only_restored (never higher)  │
    │    • state_present + no rebind → state_restored_rebind_required    │
    │    • No evidence → continuity_lost                                 │
    │                                                                     │
    │  Produces:                                                         │
    │    • ConversationContinuityVerdict  (structured output)            │
    │                                                                     │
    │  Consumed by:                                                      │
    │    • system_final_acceptance_verdict (conversation_continuity dim) │
    │    • recovery / readiness / acceptance pipelines                   │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class rather than the optimistic one.
3. **No optimistic promotion** — ``history_only_restored``, ``partial_continuity``,
   and ``state_restored_rebind_required`` MUST NOT be upgraded to
   ``authoritative_continuity_restored`` without explicit session and rebind
   confirmation evidence.
4. **Taxonomy boundary enforcement** — task continuity, history visibility,
   and state persistence are treated as *separate* evidence dimensions from
   conversation continuity.  Presence of any one does not imply the others.
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Public API
----------
Sentinels::

    CONVERSATION_CONTINUITY_TRUTH_AUTHORITY
    CONVERSATION_CONTINUITY_TRUTH_PR12_SENTINEL
    HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY
    STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY
    TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY
    AUTHORITATIVE_CONTINUITY_REQUIRES_REBIND_AND_SESSION_POLICY
    PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_POLICY
    PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY
    EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY

Enumerations::

    ConversationContinuityClass

Dataclasses::

    ConversationContinuityEvidence
    ConversationContinuityVerdict

Classes::

    ConversationContinuityContract

Functions::

    build_conversation_continuity_verdict(
        evidence,
    ) -> ConversationContinuityVerdict
"""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ConversationContinuityTruth")

__all__ = [
    # Sentinels
    "CONVERSATION_CONTINUITY_TRUTH_AUTHORITY",
    "CONVERSATION_CONTINUITY_TRUTH_PR12_SENTINEL",
    "HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY",
    "STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY",
    "TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY",
    "AUTHORITATIVE_CONTINUITY_REQUIRES_REBIND_AND_SESSION_POLICY",
    "PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_POLICY",
    "PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY",
    "EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY",
    # Enumerations
    "ConversationContinuityClass",
    # Dataclasses
    "ConversationContinuityEvidence",
    "ConversationContinuityVerdict",
    # Classes
    "ConversationContinuityContract",
    # Functions
    "build_conversation_continuity_verdict",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CONVERSATION_CONTINUITY_TRUTH_AUTHORITY: str = (
    "CONVERSATION_CONTINUITY_TRUTH_AUTHORITY::"
    "core.conversation_continuity_truth is the canonical authority for "
    "conversation continuity classification after crash / restart / process "
    "death / partial recovery (PR-12).  It converts structured evidence "
    "(session_confirmed, history_visible, state_present, rebind_completed, "
    "task_continuity_ok) into a formal ConversationContinuityClass verdict "
    "consumable by recovery, readiness, and acceptance pipelines.  "
    "post-533 dual-repo runtime-unification track."
)

CONVERSATION_CONTINUITY_TRUTH_PR12_SENTINEL: str = (
    "CONVERSATION_CONTINUITY_TRUTH_PR12_SENTINEL::"
    "package=PR-12 "
    "track=conversation-continuity-truth-formalization "
    "module=core.conversation_continuity_truth "
    "title=crash-restart-conversation-continuity-truth-contract"
)

HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY: str = (
    "POLICY::HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_PR12: "
    "The ability to read conversation history from a durable store after a "
    "restart is NOT equivalent to conversation continuity being restored.  "
    "history_visible means past messages can be retrieved; it does NOT mean "
    "the conversation session is live, the client binding is current, or the "
    "user can continue the same conversation thread authoritatively.  "
    "Systems MUST NOT upgrade a history_only_restored verdict to "
    "authoritative_continuity_restored on the basis of history visibility "
    "alone.  (PR-12)"
)

STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY: str = (
    "POLICY::STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_PR12: "
    "Session state being present in the registry (records visible, persisted "
    "snapshots loadable) is NOT equivalent to conversation continuity.  "
    "state_present means the state survived the restart; it does NOT mean "
    "the active conversation is live, the client has re-bound, or that the "
    "session is authoritative for future turns.  A state_present verdict "
    "without confirmed rebinding MUST be classified at most as "
    "state_restored_rebind_required.  (PR-12)"
)

TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY: str = (
    "POLICY::TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_PR12: "
    "In-flight task continuity being preserved (a task's execution state "
    "survived recovery) is NOT the same as conversation continuity being "
    "restored.  A recovered task's execution thread does not imply that the "
    "conversation session itself is live, the client is rebound, or that the "
    "user can continue the same turn sequence.  task_continuity_ok is one "
    "supporting evidence dimension but is insufficient alone for any class "
    "higher than partial_continuity.  (PR-12)"
)

AUTHORITATIVE_CONTINUITY_REQUIRES_REBIND_AND_SESSION_POLICY: str = (
    "POLICY::AUTHORITATIVE_CONTINUITY_REQUIRES_REBIND_AND_SESSION_PR12: "
    "ConversationContinuityClass.authoritative_continuity_restored requires "
    "ALL of the following to be true: (1) session_confirmed — the live "
    "conversation session has been explicitly re-established; (2) "
    "rebind_completed — the active client has been re-bound to the session; "
    "(3) history_visible — conversation history is readable; and (4) "
    "state_present — session state is present in the registry.  Absence of "
    "any one of these MUST prevent the verdict from reaching "
    "authoritative_continuity_restored.  (PR-12)"
)

PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_POLICY: str = (
    "POLICY::PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_PR12: "
    "When recovery is only partial — meaning some evidence dimensions are "
    "present but not all required for authoritative continuity — the verdict "
    "MUST be downgraded.  If session_confirmed or rebind_completed is absent "
    "but history and state are present, the maximum achievable class is "
    "partial_continuity.  If only history_visible is present (state and "
    "rebind absent), the verdict is history_only_restored.  If only "
    "state_present is true with no rebind, the verdict is "
    "state_restored_rebind_required.  Downstream consumers MUST respect these "
    "downgrade semantics and MUST NOT re-upgrade a partial verdict.  (PR-12)"
)

PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY: str = (
    "POLICY::PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_PR12: "
    "After a process death event, ALL previously established client bindings "
    "and live session references are considered invalidated.  Recovery may "
    "restore state records and history, but conversation continuity MUST "
    "remain at state_restored_rebind_required or lower until an explicit "
    "rebind has been confirmed by a live session establishment signal.  "
    "Surviving state records do NOT carry over the prior binding.  (PR-12)"
)

EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY: str = (
    "POLICY::EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_PR12: "
    "When a required evidence dimension is absent (not observed, not "
    "confirmed, or not determinable) the verdict MUST be degraded to the "
    "lowest class supported by the available evidence.  It is PROHIBITED to "
    "assume that an unobserved dimension is 'likely present' or 'probably ok'.  "
    "Unknown or absent evidence MUST be treated as not-present for verdict "
    "computation purposes.  (PR-12)"
)


# ---------------------------------------------------------------------------
# ConversationContinuityClass
# ---------------------------------------------------------------------------


class ConversationContinuityClass(str, Enum):
    """Canonical conversation continuity classification after restart / crash.

    Values are strictly ordered from highest (most continuity assured) to
    lowest (no continuity).  Downgrade semantics apply: insufficient evidence
    always yields the lowest class that honest evidence supports.

    Values
    ------
    authoritative_continuity_restored
        Full authoritative conversation continuity has been restored.
        Requires ALL of: session_confirmed, rebind_completed,
        history_visible, state_present.  The user can rely on the same
        conversation thread continuing without interruption from the
        client's perspective.

    partial_continuity
        Some continuity dimensions are present but not all.  At minimum
        history is visible and state is present, but either
        session_confirmed or rebind_completed is absent.  The conversation
        can be partially resumed but authoritative continuity cannot be
        guaranteed.

    history_only_restored
        Only conversation history is readable from the durable store.
        State may or may not be present; no active session or client
        rebinding has occurred.  The user can read history but cannot
        continue the conversation without starting a new session.

    state_restored_rebind_required
        Session/task state is present in the registry but no client
        rebinding has been completed.  The conversation cannot resume
        until an explicit rebind is performed.  This is the correct
        class after a process death or restart where state survived but
        the client connection was lost.

    continuity_lost
        No conversation continuity.  History may or may not be accessible;
        state may or may not be present; but no recovery path has
        established even partial continuity.  A new conversation session
        is required.  This is the conservative default when evidence is
        absent or indeterminate.
    """

    authoritative_continuity_restored = "authoritative_continuity_restored"
    partial_continuity = "partial_continuity"
    history_only_restored = "history_only_restored"
    state_restored_rebind_required = "state_restored_rebind_required"
    continuity_lost = "continuity_lost"

    # ------------------------------------------------------------------
    # Ordering helpers
    # ------------------------------------------------------------------

    @property
    def rank(self) -> int:
        """Numeric rank (higher = more continuity).  Used for comparisons."""
        return _CONTINUITY_CLASS_RANK[self.value]

    def is_at_least(self, other: "ConversationContinuityClass") -> bool:
        """True when this class has equal or higher continuity than *other*."""
        return self.rank >= other.rank

    @property
    def is_authoritative(self) -> bool:
        """True only for ``authoritative_continuity_restored``."""
        return self == ConversationContinuityClass.authoritative_continuity_restored

    @property
    def requires_rebind(self) -> bool:
        """True when the current class implies client rebinding is still needed."""
        return self in (
            ConversationContinuityClass.state_restored_rebind_required,
            ConversationContinuityClass.continuity_lost,
        )

    @property
    def is_terminal_loss(self) -> bool:
        """True when continuity is definitively lost and cannot be inferred."""
        return self == ConversationContinuityClass.continuity_lost

    @classmethod
    def from_string(cls, value: str) -> "ConversationContinuityClass":
        """Return the matching member, defaulting to ``continuity_lost``."""
        if not isinstance(value, str):
            return cls.continuity_lost
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.continuity_lost


# Class-level rank mapping (defined outside the class to avoid forward-ref issues)
_CONTINUITY_CLASS_RANK: Dict[str, int] = {
    ConversationContinuityClass.continuity_lost.value: 0,
    ConversationContinuityClass.state_restored_rebind_required.value: 1,
    ConversationContinuityClass.history_only_restored.value: 2,
    ConversationContinuityClass.partial_continuity.value: 3,
    ConversationContinuityClass.authoritative_continuity_restored.value: 4,
}


# ---------------------------------------------------------------------------
# ConversationContinuityEvidence
# ---------------------------------------------------------------------------


@dataclass
class ConversationContinuityEvidence:
    """Structured input evidence for conversation continuity evaluation.

    Each boolean dimension represents an independently-observed evidence
    signal.  Absent or indeterminate signals MUST be left as ``False``
    (never assumed True).

    Attributes
    ----------
    session_confirmed
        A live conversation session has been explicitly re-established
        with the authoritative session manager after the restart/recovery.
        This is the strongest continuity signal.  A session record existing
        in a database does NOT satisfy this; the session must be actively
        confirmed as current.
    history_visible
        Conversation history is readable from the durable store.  This
        means past messages can be retrieved but does NOT imply the session
        is live or the client is rebound.
    state_present
        Session and/or task state is present in the runtime registry.
        This means state records survived the restart but does NOT imply
        the conversation can be continued without further action.
    rebind_completed
        An active client connection has been re-bound to the session after
        the restart.  This requires an explicit re-attachment signal from
        the client, not just the presence of a prior session record.
    task_continuity_ok
        In-flight task execution state was preserved by the recovery
        process.  This is a supporting dimension; it alone does NOT imply
        conversation continuity.
    process_death_observed
        A clean process death (SIGKILL, OOM, hard crash) was observed.
        When True, all prior bindings are treated as invalidated per
        PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY.
    partial_recovery_only
        Recovery was known to be only partial (e.g. some state missing,
        some evidence unavailable).  When True, the verdict is capped at
        ``partial_continuity`` even if other evidence would permit higher.
    conversation_session_id
        Optional: the conversation session identifier being evaluated.
    evaluated_context
        Optional: free-form description of the recovery context for audit.
    """

    session_confirmed: bool = False
    history_visible: bool = False
    state_present: bool = False
    rebind_completed: bool = False
    task_continuity_ok: bool = False
    process_death_observed: bool = False
    partial_recovery_only: bool = False
    conversation_session_id: str = ""
    evaluated_context: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "session_confirmed": self.session_confirmed,
            "history_visible": self.history_visible,
            "state_present": self.state_present,
            "rebind_completed": self.rebind_completed,
            "task_continuity_ok": self.task_continuity_ok,
            "process_death_observed": self.process_death_observed,
            "partial_recovery_only": self.partial_recovery_only,
            "conversation_session_id": self.conversation_session_id,
            "evaluated_context": self.evaluated_context,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConversationContinuityEvidence":
        """Reconstruct from a serialised dict."""
        return cls(
            session_confirmed=bool(d.get("session_confirmed", False)),
            history_visible=bool(d.get("history_visible", False)),
            state_present=bool(d.get("state_present", False)),
            rebind_completed=bool(d.get("rebind_completed", False)),
            task_continuity_ok=bool(d.get("task_continuity_ok", False)),
            process_death_observed=bool(d.get("process_death_observed", False)),
            partial_recovery_only=bool(d.get("partial_recovery_only", False)),
            conversation_session_id=str(d.get("conversation_session_id", "")),
            evaluated_context=str(d.get("evaluated_context", "")),
        )


# ---------------------------------------------------------------------------
# ConversationContinuityVerdict
# ---------------------------------------------------------------------------


@dataclass
class ConversationContinuityVerdict:
    """Structured conversation continuity verdict.

    This is the canonical output of :class:`ConversationContinuityContract`
    and :func:`build_conversation_continuity_verdict`.  It is designed to be
    consumed by recovery, readiness, acceptance, and governance pipelines.

    Attributes
    ----------
    verdict_id
        Unique identifier for this verdict instance.
    generated_at
        Unix timestamp of verdict generation.
    continuity_class
        The formal :class:`ConversationContinuityClass` verdict.
    conversation_session_id
        The session identifier this verdict applies to (may be empty).
    session_confirmed
        Evidence dimension: live session re-established.
    history_visible
        Evidence dimension: history readable from durable store.
    state_present
        Evidence dimension: state present in registry.
    rebind_completed
        Evidence dimension: active client rebinding confirmed.
    task_continuity_ok
        Evidence dimension: in-flight task continuity preserved.
    process_death_observed
        Whether a process death event was observed.
    partial_recovery_only
        Whether recovery was known to be only partial.
    reason
        Human-readable explanation of the verdict.
    policy_references
        List of policy sentinel names that governed this verdict.
    continuity_sentinel
        Copy of the module-level authority sentinel.
    """

    verdict_id: str = field(
        default_factory=lambda: f"ccv_{uuid.uuid4().hex[:12]}"
    )
    generated_at: float = field(default_factory=time.time)
    continuity_class: ConversationContinuityClass = (
        ConversationContinuityClass.continuity_lost
    )
    conversation_session_id: str = ""
    session_confirmed: bool = False
    history_visible: bool = False
    state_present: bool = False
    rebind_completed: bool = False
    task_continuity_ok: bool = False
    process_death_observed: bool = False
    partial_recovery_only: bool = False
    reason: str = ""
    policy_references: List[str] = field(default_factory=list)
    continuity_sentinel: str = CONVERSATION_CONTINUITY_TRUTH_AUTHORITY

    @property
    def is_authoritative(self) -> bool:
        """True only when full authoritative continuity has been confirmed."""
        return self.continuity_class.is_authoritative

    @property
    def requires_rebind(self) -> bool:
        """True when the verdict implies client rebinding is still required."""
        return self.continuity_class.requires_rebind

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "verdict_id": self.verdict_id,
            "generated_at": self.generated_at,
            "continuity_class": self.continuity_class.value,
            "conversation_session_id": self.conversation_session_id,
            "session_confirmed": self.session_confirmed,
            "history_visible": self.history_visible,
            "state_present": self.state_present,
            "rebind_completed": self.rebind_completed,
            "task_continuity_ok": self.task_continuity_ok,
            "process_death_observed": self.process_death_observed,
            "partial_recovery_only": self.partial_recovery_only,
            "reason": self.reason,
            "policy_references": list(self.policy_references),
            "continuity_sentinel": self.continuity_sentinel,
            "is_authoritative": self.is_authoritative,
            "requires_rebind": self.requires_rebind,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConversationContinuityVerdict":
        """Reconstruct from a serialised dict."""
        raw_class = d.get("continuity_class", "continuity_lost")
        try:
            cc = ConversationContinuityClass(raw_class)
        except ValueError:
            cc = ConversationContinuityClass.continuity_lost
        return cls(
            verdict_id=str(d.get("verdict_id", "")),
            generated_at=float(d.get("generated_at", 0.0)),
            continuity_class=cc,
            conversation_session_id=str(d.get("conversation_session_id", "")),
            session_confirmed=bool(d.get("session_confirmed", False)),
            history_visible=bool(d.get("history_visible", False)),
            state_present=bool(d.get("state_present", False)),
            rebind_completed=bool(d.get("rebind_completed", False)),
            task_continuity_ok=bool(d.get("task_continuity_ok", False)),
            process_death_observed=bool(d.get("process_death_observed", False)),
            partial_recovery_only=bool(d.get("partial_recovery_only", False)),
            reason=str(d.get("reason", "")),
            policy_references=list(d.get("policy_references", [])),
            continuity_sentinel=str(
                d.get("continuity_sentinel", CONVERSATION_CONTINUITY_TRUTH_AUTHORITY)
            ),
        )


# ---------------------------------------------------------------------------
# ConversationContinuityContract
# ---------------------------------------------------------------------------


class ConversationContinuityContract:
    """Evaluates conversation continuity after crash / restart / process death.

    Converts a :class:`ConversationContinuityEvidence` object into a formal
    :class:`ConversationContinuityVerdict` using strict downgrade semantics.

    Classification rules (applied in strict descending order)
    ----------------------------------------------------------
    1. **authoritative_continuity_restored** — requires ALL of:
       session_confirmed=True, rebind_completed=True, history_visible=True,
       state_present=True, AND neither process_death_observed nor
       partial_recovery_only is True.

    2. **partial_continuity** — requires: history_visible=True AND
       state_present=True AND at least one of (session_confirmed,
       rebind_completed, task_continuity_ok) is True, but NOT all
       authoritative requirements met (or partial_recovery_only=True).

    3. **history_only_restored** — requires: history_visible=True AND
       state_present=False AND rebind_completed=False.

    4. **state_restored_rebind_required** — requires: state_present=True
       AND rebind_completed=False (regardless of history_visible), including
       when process_death_observed=True.

    5. **continuity_lost** — when none of the above conditions are satisfied
       (default / conservative fallback).

    Downgrade overrides
    -------------------
    - ``process_death_observed=True`` prevents ``authoritative_continuity_restored``
      and caps the verdict at ``partial_continuity`` at best (if other evidence
      present), else ``state_restored_rebind_required`` or ``continuity_lost``.
    - ``partial_recovery_only=True`` prevents ``authoritative_continuity_restored``
      and caps at ``partial_continuity`` at best.
    """

    def evaluate(
        self, evidence: ConversationContinuityEvidence
    ) -> ConversationContinuityVerdict:
        """Evaluate evidence and produce a structured continuity verdict.

        Parameters
        ----------
        evidence
            :class:`ConversationContinuityEvidence` instance describing what
            recovery evidence is present.

        Returns
        -------
        ConversationContinuityVerdict
        """
        verdict = ConversationContinuityVerdict(
            conversation_session_id=evidence.conversation_session_id,
            session_confirmed=evidence.session_confirmed,
            history_visible=evidence.history_visible,
            state_present=evidence.state_present,
            rebind_completed=evidence.rebind_completed,
            task_continuity_ok=evidence.task_continuity_ok,
            process_death_observed=evidence.process_death_observed,
            partial_recovery_only=evidence.partial_recovery_only,
        )

        cc, reason, policies = self._classify(evidence)
        verdict.continuity_class = cc
        verdict.reason = reason
        verdict.policy_references = policies

        logger.debug(
            "ConversationContinuityContract.evaluate: "
            "session_id=%r class=%s reason=%r",
            evidence.conversation_session_id,
            cc.value,
            reason,
        )
        return verdict

    # ------------------------------------------------------------------
    # Internal classification logic
    # ------------------------------------------------------------------

    def _classify(
        self, e: ConversationContinuityEvidence
    ) -> "tuple[ConversationContinuityClass, str, List[str]]":
        """Apply classification rules and return (class, reason, policies)."""
        policies: List[str] = []

        # ------------------------------------------------------------------
        # Rule 1: authoritative_continuity_restored
        # Requires: all four core dimensions confirmed AND no downgrade flags.
        # ------------------------------------------------------------------
        if (
            e.session_confirmed
            and e.rebind_completed
            and e.history_visible
            and e.state_present
            and not e.process_death_observed
            and not e.partial_recovery_only
        ):
            policies.append(
                "AUTHORITATIVE_CONTINUITY_REQUIRES_REBIND_AND_SESSION_POLICY"
            )
            return (
                ConversationContinuityClass.authoritative_continuity_restored,
                (
                    "All four required evidence dimensions are confirmed "
                    "(session_confirmed, rebind_completed, history_visible, "
                    "state_present) with no downgrade flags.  "
                    "Authoritative conversation continuity restored."
                ),
                policies,
            )

        # ------------------------------------------------------------------
        # Downgrade override: process_death_observed or partial_recovery_only
        # blocks authoritative continuity even if all dimensions appear present.
        # ------------------------------------------------------------------
        if (
            e.session_confirmed
            and e.rebind_completed
            and e.history_visible
            and e.state_present
            and (e.process_death_observed or e.partial_recovery_only)
        ):
            policies.append("PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY")
            policies.append("PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_POLICY")
            downgrade_reason = "process_death_observed" if e.process_death_observed else "partial_recovery_only"
            return (
                ConversationContinuityClass.partial_continuity,
                (
                    f"All four evidence dimensions present but {downgrade_reason!r} "
                    "forces downgrade from authoritative_continuity_restored to "
                    "partial_continuity.  Prior bindings are considered invalidated "
                    "and must be re-confirmed before full authoritative status."
                ),
                policies,
            )

        # ------------------------------------------------------------------
        # Rule 2: partial_continuity
        # Requires: history_visible AND state_present AND at least one of
        # (session_confirmed, rebind_completed, task_continuity_ok).
        # ------------------------------------------------------------------
        if (
            e.history_visible
            and e.state_present
            and (e.session_confirmed or e.rebind_completed or e.task_continuity_ok)
        ):
            policies.append("PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_POLICY")
            missing = []
            if not e.session_confirmed:
                missing.append("session_confirmed")
            if not e.rebind_completed:
                missing.append("rebind_completed")
            return (
                ConversationContinuityClass.partial_continuity,
                (
                    "history_visible and state_present are confirmed, and at least "
                    "one supporting dimension is present, but full authoritative "
                    f"continuity is not achievable.  Missing: {missing!r}.  "
                    "Partial continuity only."
                ),
                policies,
            )

        # ------------------------------------------------------------------
        # Rule 3: history_only_restored
        # Requires: history_visible AND state not present AND no rebind.
        # ------------------------------------------------------------------
        if e.history_visible and not e.state_present and not e.rebind_completed:
            policies.append("HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY")
            return (
                ConversationContinuityClass.history_only_restored,
                (
                    "history_visible is True but state_present=False and "
                    "rebind_completed=False.  Conversation history can be read "
                    "but the conversation cannot be continued without a new "
                    "session.  History visibility alone does NOT constitute "
                    "conversation continuity."
                ),
                policies,
            )

        # ------------------------------------------------------------------
        # Rule 4: state_restored_rebind_required
        # Requires: state_present AND NOT rebind_completed.
        # (Covers process_death + state survived but client not rebound.)
        # ------------------------------------------------------------------
        if e.state_present and not e.rebind_completed:
            policies.append("STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY")
            if e.process_death_observed:
                policies.append("PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY")
            return (
                ConversationContinuityClass.state_restored_rebind_required,
                (
                    "state_present=True but rebind_completed=False.  "
                    "Session state survived the restart but an explicit client "
                    "rebinding is required before the conversation can resume.  "
                    "State presence alone does NOT constitute conversation continuity."
                    + (
                        "  process_death_observed=True: all prior bindings are "
                        "invalidated."
                        if e.process_death_observed
                        else ""
                    )
                ),
                policies,
            )

        # ------------------------------------------------------------------
        # Rule 5 (default): continuity_lost
        # ------------------------------------------------------------------
        policies.append("EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY")
        absent_dims = [
            dim
            for dim, val in [
                ("session_confirmed", e.session_confirmed),
                ("history_visible", e.history_visible),
                ("state_present", e.state_present),
                ("rebind_completed", e.rebind_completed),
            ]
            if not val
        ]
        return (
            ConversationContinuityClass.continuity_lost,
            (
                "Insufficient evidence to establish any level of conversation "
                f"continuity.  Absent dimensions: {absent_dims!r}.  "
                "Conversation continuity is lost; a new session is required."
            ),
            policies,
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def build_conversation_continuity_verdict(
    evidence: ConversationContinuityEvidence,
) -> ConversationContinuityVerdict:
    """Evaluate conversation continuity evidence and return a formal verdict.

    This is the canonical entry point for callers that want a
    :class:`ConversationContinuityVerdict` without directly instantiating
    :class:`ConversationContinuityContract`.

    Parameters
    ----------
    evidence
        :class:`ConversationContinuityEvidence` describing what recovery
        evidence is present for the conversation session being evaluated.

    Returns
    -------
    ConversationContinuityVerdict
        Structured verdict with class, reason, and policy references.
    """
    contract = ConversationContinuityContract()
    return contract.evaluate(evidence)
