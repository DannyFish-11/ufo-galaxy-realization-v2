#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/conversation_continuity_truth.py
======================================
PR-CCT (post-533 continuity-truth track):
Conversation Continuity Truth Contract — formal taxonomy and structured
verdict surface for **conversation continuity** after crash / restart /
process death / partial recovery.

Problem addressed
-----------------
The Galaxy V2 runtime already has substantial state persistence, task
continuity, and recovery machinery.  After a crash or restart, the system
can observe:

* Conversation / session history still visible in the persistence store
* Task continuity reports showing some tasks ``recoverable`` or ``resumed``
* Session records re-hydrated from durable state

However none of these observations individually — or in combination —
constitute an authoritative claim that **conversation continuity** has been
restored.  Without a formal contract, recovery code and acceptance logic
tend to treat "history visible" or "state in registry" as sufficient grounds
for optimistically declaring that conversation continuity is active.

This module closes that gap by defining:

1. :class:`ConversationContinuityStatus` — five-tier taxonomy.
2. :class:`ConversationContinuityEvidence` — the evidence bundle evaluated
   by the contract.
3. :class:`ConversationContinuityVerdict` — per-session structured verdict.
4. :class:`ConversationContinuityTruthContract` — evaluation logic that
   converts evidence into a verdict, enforcing downgrade semantics.
5. :func:`build_conversation_continuity_verdict` — convenience builder.
6. :func:`evaluate_session_continuity_after_restart` — high-level helper
   that probes existing V2 modules and produces a verdict.

Critical invariants
-------------------
* **History visible ≠ conversation continuity restored.**
* **Task continuity ≠ conversation continuity.**
* **State restoration ≠ conversation continuity.**
* **Rebind not completed → MUST NOT claim authoritative continuity.**
* **Evidence absent → MUST NOT optimistically upgrade verdict.**

Taxonomy
--------
``authoritative_continuity_restored``
    All required evidence is present: session identity is stable, history
    is accessible, conversation context is consistent, AND the runtime
    rebind has been completed.  No interruption gap exists.

``partial_continuity``
    Some evidence is present (e.g. history accessible, partial task
    continuity) but not all conditions for authoritative continuity are
    met.  Conversation may be usable but cannot be declared fully
    restored.

``history_only_restored``
    Session history is visible / accessible but the live conversation
    runtime context has not been rebound.  The user can read past
    conversation turns but the active session is not reconnected.

``state_restored_rebind_required``
    Conversation state (session record, history) has been restored to the
    persistence layer, but the runtime rebind step has not been completed.
    A new bind operation is required before authoritative continuity can
    be claimed.

``continuity_lost``
    No viable path to restore conversation continuity exists.  Session
    identity is gone, history is inaccessible, or the process death was
    unrecoverable.  A new conversation must be started.

Downgrade semantics
-------------------
The contract evaluates evidence in descending priority order.  Each
negative evidence signal triggers a downgrade; upgrades are **never**
performed when evidence is absent or ambiguous.

::

    authoritative_continuity_restored  ← requires ALL positive signals
           ↓ (history present, no live rebind)
    history_only_restored
           ↓ (state present, rebind incomplete)
    state_restored_rebind_required
           ↓ (evidence partial / ambiguous)
    partial_continuity
           ↓ (evidence absent / irrecoverable)
    continuity_lost

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  CONVERSATION CONTINUITY TRUTH CONTRACT  (this module — PR-CCT)    │
    │                                                                     │
    │  Five-tier taxonomy:                                               │
    │    1. authoritative_continuity_restored                            │
    │    2. partial_continuity                                           │
    │    3. history_only_restored                                        │
    │    4. state_restored_rebind_required                               │
    │    5. continuity_lost                                              │
    │                                                                     │
    │  Evidence dimensions evaluated:                                    │
    │    • session_identity_stable    — stable session_id across restart │
    │    • history_accessible         — history readable from store      │
    │    • context_consistent         — conversation context intact      │
    │    • live_rebind_completed      — runtime session rebound          │
    │    • task_continuity_confirmed  — in-flight task continuity ok     │
    │                                                                     │
    │  Policy sentinels enforcing downgrade semantics (no optimistic     │
    │  upgrade when evidence is absent or ambiguous).                    │
    │                                                                     │
    │  Probes (read-only / fail-graceful):                               │
    │    • core.session_manager                                          │
    │    • core.continuation_rebind_registry                             │
    │    • core.inflight_task_continuity_contract                        │
    │    • core.canonical_session_truth                                  │
    │                                                                     │
    │  Produces:                                                         │
    │    • ConversationContinuityVerdict (per-session structured verdict)│
    │    • ConversationContinuityTruthReport (aggregated surface)        │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Fail-conservative** — missing or unobservable evidence yields the
   most conservative (lower) verdict tier, never the optimistic one.
3. **Honest deferral** — deferred boundaries are explicitly marked; they
   are never silently closed.
4. **No conflation** — task continuity, history visibility, session
   persistence, and runtime rebinding are kept distinct; no single
   observation is sufficient to claim authoritative conversation
   continuity.
5. **Projection-only** — this module reads from existing modules; it
   never mutates their state.

Public API
----------
Sentinels::

    CONVERSATION_CONTINUITY_TRUTH_AUTHORITY
    CONVERSATION_CONTINUITY_TRUTH_PR_CCT_SENTINEL
    HISTORY_VISIBLE_IS_NOT_CONVERSATION_CONTINUITY_POLICY
    TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY
    STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY
    REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY_POLICY
    EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT_POLICY

Enumerations::

    ConversationContinuityStatus

Dataclasses::

    ConversationContinuityEvidence
    ConversationContinuityVerdict
    ConversationContinuityTruthReport

Classes::

    ConversationContinuityTruthContract

Functions::

    build_conversation_continuity_verdict(
        evidence: ConversationContinuityEvidence,
    ) -> ConversationContinuityVerdict

    evaluate_session_continuity_after_restart(
        session_id: str | None = None,
    ) -> ConversationContinuityTruthReport

    get_conversation_continuity_truth_report() -> ConversationContinuityTruthReport
    reset_conversation_continuity_truth_report() -> None  (testing only)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ConversationContinuityTruth")

__all__ = [
    # Sentinels
    "CONVERSATION_CONTINUITY_TRUTH_AUTHORITY",
    "CONVERSATION_CONTINUITY_TRUTH_PR_CCT_SENTINEL",
    "HISTORY_VISIBLE_IS_NOT_CONVERSATION_CONTINUITY_POLICY",
    "TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY",
    "STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY",
    "REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY_POLICY",
    "EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT_POLICY",
    # Enumerations
    "ConversationContinuityStatus",
    # Dataclasses
    "ConversationContinuityEvidence",
    "ConversationContinuityVerdict",
    "ConversationContinuityTruthReport",
    # Classes
    "ConversationContinuityTruthContract",
    # Functions
    "build_conversation_continuity_verdict",
    "evaluate_session_continuity_after_restart",
    "get_conversation_continuity_truth_report",
    "reset_conversation_continuity_truth_report",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CONVERSATION_CONTINUITY_TRUTH_AUTHORITY: str = (
    "CONVERSATION_CONTINUITY_TRUTH_AUTHORITY::"
    "core.conversation_continuity_truth is the canonical judgment layer "
    "for conversation continuity after crash / restart / process death / "
    "partial recovery (PR-CCT).  It converts structured evidence into "
    "five-tier ConversationContinuityStatus verdicts and a structured "
    "ConversationContinuityTruthReport consumable by recovery, readiness, "
    "and acceptance pipelines."
)

CONVERSATION_CONTINUITY_TRUTH_PR_CCT_SENTINEL: str = (
    "CONVERSATION_CONTINUITY_TRUTH_PR_CCT::"
    "package=PR-CCT "
    "track=conversation-continuity-truth-after-crash-restart "
    "module=core.conversation_continuity_truth "
    "title=conversation-continuity-truth-contract-after-crash-restart"
)

HISTORY_VISIBLE_IS_NOT_CONVERSATION_CONTINUITY_POLICY: str = (
    "POLICY::HISTORY_VISIBLE_IS_NOT_CONVERSATION_CONTINUITY_PR_CCT: "
    "The presence of readable conversation history in the persistence store "
    "after restart is *history restoration*, not *conversation continuity "
    "restoration*.  A session classified as having authoritative continuity "
    "restored REQUIRES BOTH history accessibility AND a completed live "
    "runtime rebind.  Callers MUST NOT treat 'history visible' as "
    "'conversation continuity restored'.  The history_only_restored tier "
    "exists precisely for this case.  (PR-CCT)"
)

TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY: str = (
    "POLICY::TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_PR_CCT: "
    "In-flight task continuity (TaskContinuityStatus from "
    "core.inflight_task_continuity_contract) is a distinct dimension from "
    "conversation continuity.  A session may have all in-flight tasks "
    "classified as 'resumed' or 'recoverable' while the conversation "
    "context is in 'history_only_restored' or 'state_restored_rebind_required' "
    "state.  Conversely, conversation continuity may be restored while some "
    "tasks are interrupted.  These two dimensions MUST NOT be conflated.  "
    "task_continuity_confirmed in ConversationContinuityEvidence is a "
    "contributing signal, not a sufficient condition.  (PR-CCT)"
)

STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY: str = (
    "POLICY::STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_PR_CCT: "
    "Restoring session state records (session_id, history entries, "
    "metadata) from a durable persistence store after restart is "
    "*state restoration*, not *conversation continuity restoration*.  "
    "Conversation continuity additionally requires that the live runtime "
    "session context has been rebound (live_rebind_completed=True) and "
    "that the conversation context is consistent (context_consistent=True).  "
    "State restored without rebind MUST be classified as "
    "state_restored_rebind_required, not authoritative_continuity_restored.  "
    "(PR-CCT)"
)

REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY_POLICY: str = (
    "POLICY::REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY_PR_CCT: "
    "live_rebind_completed=False is an unconditional downgrade trigger.  "
    "No combination of other positive evidence signals is sufficient to "
    "claim authoritative_continuity_restored when the runtime rebind has "
    "not been completed.  A session without live rebind MUST be classified "
    "as history_only_restored (if history is accessible) or "
    "state_restored_rebind_required (if state is present) or "
    "continuity_lost (if neither).  (PR-CCT)"
)

EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT_POLICY: str = (
    "POLICY::EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT_PR_CCT: "
    "When an evidence dimension cannot be observed (module unavailable, "
    "probe failure, field absent) it MUST be treated as the absence of "
    "that evidence, which triggers the corresponding downgrade.  Missing "
    "evidence MUST NOT be treated as positive evidence.  The "
    "ConversationContinuityTruthContract enforces this by using "
    "Optional[bool] for all evidence flags and treating None as False "
    "for downgrade purposes.  (PR-CCT)"
)

PROCESS_DEATH_REQUIRES_FULL_REBIND_POLICY: str = (
    "POLICY::PROCESS_DEATH_REQUIRES_FULL_REBIND_PR_CCT: "
    "After a process death (as opposed to a graceful restart), the "
    "in-memory runtime session state is irrecoverably lost.  Even if "
    "session records are restored from durable store, the conversation "
    "runtime rebind MUST be completed before authoritative continuity "
    "can be claimed.  A verdict of state_restored_rebind_required is the "
    "minimum correct classification after process death where state is "
    "present; continuity_lost is correct where state is absent.  (PR-CCT)"
)

PARTIAL_RECOVERY_MUST_NOT_CLAIM_FULL_CONTINUITY_POLICY: str = (
    "POLICY::PARTIAL_RECOVERY_MUST_NOT_CLAIM_FULL_CONTINUITY_PR_CCT: "
    "When recovery is partial (some sessions restored, some lost; or some "
    "evidence dimensions present but not all), the verdict MUST be "
    "partial_continuity at best.  The is_partial_recovery flag in "
    "ConversationContinuityEvidence triggers a ceiling on the verdict "
    "that prevents upgrading to authoritative_continuity_restored.  "
    "(PR-CCT)"
)


# ---------------------------------------------------------------------------
# ConversationContinuityStatus
# ---------------------------------------------------------------------------


class ConversationContinuityStatus(str, Enum):
    """Five-tier taxonomy for conversation continuity after crash / restart.

    Values
    ------
    authoritative_continuity_restored
        All required evidence is present: session identity is stable,
        history is accessible, conversation context is consistent, AND
        the live runtime rebind has been completed.  The system can
        formally declare that conversation continuity is authoritatively
        restored.  No interruption gap exists in the conversation thread.

    partial_continuity
        Some evidence is present but not all conditions for authoritative
        continuity are met.  Conversation may be partially usable but
        cannot be declared fully restored.  Typical cause: some history
        accessible, some context lost, or task continuity partial.

    history_only_restored
        Session history is visible and accessible, but the live
        conversation runtime context has not been rebound.  The user can
        read past conversation turns but the active session is not
        reconnected to the runtime.  Rebind required before the session
        can be used interactively.

    state_restored_rebind_required
        Conversation state (session record, history) has been restored to
        the persistence layer, but the runtime rebind step has not been
        completed.  A new bind operation is required before authoritative
        continuity can be claimed.  Distinct from history_only_restored:
        this tier applies when *state* is present but *history
        accessibility* may also be incomplete.

    continuity_lost
        No viable path to restore conversation continuity exists.  Session
        identity is gone, history is inaccessible, or the process death
        was unrecoverable.  A new conversation must be started.
    """

    authoritative_continuity_restored = "authoritative_continuity_restored"
    partial_continuity = "partial_continuity"
    history_only_restored = "history_only_restored"
    state_restored_rebind_required = "state_restored_rebind_required"
    continuity_lost = "continuity_lost"

    @property
    def is_authoritative(self) -> bool:
        """True only for authoritative_continuity_restored."""
        return self == ConversationContinuityStatus.authoritative_continuity_restored

    @property
    def is_usable(self) -> bool:
        """True when the session can be used (authoritative or partial)."""
        return self in (
            ConversationContinuityStatus.authoritative_continuity_restored,
            ConversationContinuityStatus.partial_continuity,
        )

    @property
    def requires_rebind(self) -> bool:
        """True when a rebind operation is required before use."""
        return self in (
            ConversationContinuityStatus.history_only_restored,
            ConversationContinuityStatus.state_restored_rebind_required,
        )

    @property
    def is_lost(self) -> bool:
        """True when continuity is irrecoverably lost."""
        return self == ConversationContinuityStatus.continuity_lost


# ---------------------------------------------------------------------------
# ConversationContinuityEvidence
# ---------------------------------------------------------------------------


@dataclass
class ConversationContinuityEvidence:
    """Evidence bundle evaluated by the continuity truth contract.

    Attributes
    ----------
    session_id
        The session identifier being evaluated.  If None the verdict
        is scoped to an anonymous or system-level assessment.
    session_identity_stable
        True when the session_id has been confirmed as stable across
        the restart boundary (same id is present in both the durable
        store and the runtime context).  None = unobserved.
    history_accessible
        True when conversation history turns are readable from the
        persistence store for this session.  None = unobserved.
    context_consistent
        True when the conversation context (metadata, device bindings,
        LLM context window references) is consistent and not corrupted.
        None = unobserved.
    live_rebind_completed
        True when the runtime session rebind has been explicitly
        completed — i.e. the session has been reattached to an active
        runtime context after the restart.  None = unobserved or not
        yet executed.
    task_continuity_confirmed
        True when associated in-flight tasks have been evaluated by
        InFlightTaskContinuityContract and at least one task is
        classified as ``resumed`` (no continuity gap).  None = no
        tasks or unobserved.  This is a *contributing* signal only;
        it is not sufficient alone to claim conversation continuity.
    is_post_crash
        True when the evidence was gathered after a crash (uncontrolled
        process termination) rather than a graceful restart.  Influences
        the downgrade ceiling.
    is_partial_recovery
        True when recovery was partial — some sessions or state elements
        were restored but the recovery was not complete.  Prevents
        upgrading to authoritative_continuity_restored.
    recovery_strategy
        Human-readable description of the recovery strategy used (e.g.
        "durable_store_restore", "in_memory_snapshot", "no_recovery").
    supporting_modules
        List of V2 module paths that provided supporting evidence.
    evidence_timestamp
        Unix timestamp when this evidence bundle was assembled.
    notes
        Freeform notes for debugging or audit purposes.
    """

    session_id: Optional[str] = None
    session_identity_stable: Optional[bool] = None
    history_accessible: Optional[bool] = None
    context_consistent: Optional[bool] = None
    live_rebind_completed: Optional[bool] = None
    task_continuity_confirmed: Optional[bool] = None
    is_post_crash: bool = False
    is_partial_recovery: bool = False
    recovery_strategy: str = ""
    supporting_modules: List[str] = field(default_factory=list)
    evidence_timestamp: float = field(default_factory=time.time)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_identity_stable": self.session_identity_stable,
            "history_accessible": self.history_accessible,
            "context_consistent": self.context_consistent,
            "live_rebind_completed": self.live_rebind_completed,
            "task_continuity_confirmed": self.task_continuity_confirmed,
            "is_post_crash": self.is_post_crash,
            "is_partial_recovery": self.is_partial_recovery,
            "recovery_strategy": self.recovery_strategy,
            "supporting_modules": list(self.supporting_modules),
            "evidence_timestamp": self.evidence_timestamp,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# ConversationContinuityVerdict
# ---------------------------------------------------------------------------


@dataclass
class ConversationContinuityVerdict:
    """Structured verdict for a single session's conversation continuity.

    Attributes
    ----------
    verdict_id
        Unique identifier for this verdict instance.
    session_id
        Session identifier this verdict applies to.
    status
        Five-tier continuity status.
    rationale
        Human-readable explanation of why this verdict was reached.
    downgrade_reasons
        Ordered list of downgrade triggers applied (most significant
        first).
    policy_references
        Policy sentinel names that governed the evaluation.
    evidence_summary
        Summary of the evidence that was evaluated.
    evidence
        Full evidence bundle used for this verdict.
    evaluated_at
        Unix timestamp when the verdict was produced.
    """

    verdict_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    status: ConversationContinuityStatus = ConversationContinuityStatus.continuity_lost
    rationale: str = ""
    downgrade_reasons: List[str] = field(default_factory=list)
    policy_references: List[str] = field(default_factory=list)
    evidence_summary: str = ""
    evidence: Optional[ConversationContinuityEvidence] = None
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict_id": self.verdict_id,
            "session_id": self.session_id,
            "status": self.status.value,
            "is_authoritative": self.status.is_authoritative,
            "is_usable": self.status.is_usable,
            "requires_rebind": self.status.requires_rebind,
            "is_lost": self.status.is_lost,
            "rationale": self.rationale,
            "downgrade_reasons": list(self.downgrade_reasons),
            "policy_references": list(self.policy_references),
            "evidence_summary": self.evidence_summary,
            "evidence": self.evidence.to_dict() if self.evidence is not None else {},
            "evaluated_at": self.evaluated_at,
        }


# ---------------------------------------------------------------------------
# ConversationContinuityTruthReport
# ---------------------------------------------------------------------------


@dataclass
class ConversationContinuityTruthReport:
    """Aggregated conversation continuity truth surface report.

    Attributes
    ----------
    report_id
        Unique identifier for this report.
    verdicts
        List of per-session verdicts evaluated.
    authoritative_count
        Number of sessions with authoritative_continuity_restored status.
    partial_count
        Number of sessions with partial_continuity status.
    history_only_count
        Number of sessions with history_only_restored status.
    rebind_required_count
        Number of sessions with state_restored_rebind_required status.
    lost_count
        Number of sessions with continuity_lost status.
    has_any_authoritative
        True when at least one session has authoritative continuity.
    has_any_lost
        True when at least one session has continuity_lost.
    authority_sentinel
        Policy authority sentinel for this report.
    generated_at
        Unix timestamp when this report was generated.
    notes
        Freeform notes for audit / debugging.
    """

    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    verdicts: List[ConversationContinuityVerdict] = field(default_factory=list)
    authoritative_count: int = 0
    partial_count: int = 0
    history_only_count: int = 0
    rebind_required_count: int = 0
    lost_count: int = 0
    has_any_authoritative: bool = False
    has_any_lost: bool = False
    authority_sentinel: str = CONVERSATION_CONTINUITY_TRUTH_AUTHORITY
    generated_at: float = field(default_factory=time.time)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "authoritative_count": self.authoritative_count,
            "partial_count": self.partial_count,
            "history_only_count": self.history_only_count,
            "rebind_required_count": self.rebind_required_count,
            "lost_count": self.lost_count,
            "has_any_authoritative": self.has_any_authoritative,
            "has_any_lost": self.has_any_lost,
            "authority_sentinel": self.authority_sentinel,
            "generated_at": self.generated_at,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# ConversationContinuityTruthContract
# ---------------------------------------------------------------------------


class ConversationContinuityTruthContract:
    """Evaluates conversation continuity evidence and produces a formal verdict.

    This class is the single authoritative source for the distinction between:
    * *state restoration* and *conversation continuity restoration*
    * *history visibility* and *active conversation continuity*
    * *task continuity* and *conversation continuity*
    * *session persistence* and *runtime rebind completeness*

    Downgrade rules (applied in order, first match wins)
    ----------------------------------------------------
    1. Evidence bundle is None or completely absent
       → ``continuity_lost``
    2. ``is_post_crash=True`` AND ``live_rebind_completed`` is not True
       → ceiling: at most ``state_restored_rebind_required``
    3. ``is_partial_recovery=True``
       → ceiling: at most ``partial_continuity``
    4. ``session_identity_stable`` is not True
       → ``continuity_lost`` (cannot establish any continuity without
         stable identity)
    5. ``live_rebind_completed`` is not True
       → ``history_only_restored`` if ``history_accessible=True``, else
         ``state_restored_rebind_required`` if any state present, else
         ``continuity_lost``
    6. ``history_accessible`` is not True
       → ``state_restored_rebind_required`` (identity and rebind present
         but history inaccessible)
    7. ``context_consistent`` is not True
       → ``partial_continuity`` (most dimensions ok but context gaps)
    8. All required dimensions positive
       → ``authoritative_continuity_restored``
    """

    def evaluate(
        self,
        evidence: ConversationContinuityEvidence,
    ) -> ConversationContinuityVerdict:
        """Evaluate evidence and return a formal continuity verdict.

        Parameters
        ----------
        evidence
            The :class:`ConversationContinuityEvidence` bundle to evaluate.

        Returns
        -------
        ConversationContinuityVerdict
            Structured verdict with status, rationale, and downgrade reasons.
        """
        downgrade_reasons: List[str] = []
        policy_refs: List[str] = []

        def _v(
            status: ConversationContinuityStatus,
            rationale: str,
        ) -> ConversationContinuityVerdict:
            return ConversationContinuityVerdict(
                session_id=evidence.session_id,
                status=status,
                rationale=rationale,
                downgrade_reasons=list(downgrade_reasons),
                policy_references=list(policy_refs),
                evidence_summary=_build_evidence_summary(evidence),
                evidence=evidence,
            )

        # ----------------------------------------------------------------
        # Rule 1: No identity — continuity_lost
        # ----------------------------------------------------------------
        if not evidence.session_identity_stable:
            downgrade_reasons.append(
                "session_identity_stable=False/None — no stable session identity"
            )
            policy_refs.append("EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT_POLICY")
            policy_refs.append("STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY")
            return _v(
                ConversationContinuityStatus.continuity_lost,
                "No stable session identity: cannot establish any conversation "
                "continuity after restart/crash.",
            )

        # ----------------------------------------------------------------
        # Rule 2: Post-crash ceiling — rebind not completed
        # ----------------------------------------------------------------
        if evidence.is_post_crash and not evidence.live_rebind_completed:
            downgrade_reasons.append(
                "is_post_crash=True and live_rebind_completed=False/None — "
                "process death requires full rebind"
            )
            policy_refs.append("PROCESS_DEATH_REQUIRES_FULL_REBIND_POLICY")
            policy_refs.append("REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY_POLICY")
            if evidence.history_accessible:
                return _v(
                    ConversationContinuityStatus.history_only_restored,
                    "Process death detected; history is accessible but live rebind "
                    "has not been completed.  Classified as history_only_restored.",
                )
            return _v(
                ConversationContinuityStatus.state_restored_rebind_required,
                "Process death detected; state may be present but rebind has not "
                "been completed and history accessibility is not confirmed.  "
                "Classified as state_restored_rebind_required.",
            )

        # ----------------------------------------------------------------
        # Rule 3: Partial recovery ceiling
        # ----------------------------------------------------------------
        if evidence.is_partial_recovery:
            downgrade_reasons.append(
                "is_partial_recovery=True — partial recovery prevents "
                "authoritative_continuity_restored verdict"
            )
            policy_refs.append("PARTIAL_RECOVERY_MUST_NOT_CLAIM_FULL_CONTINUITY_POLICY")
            # Fall through to produce best-possible verdict ≤ partial_continuity

        # ----------------------------------------------------------------
        # Rule 4: Live rebind not completed
        # ----------------------------------------------------------------
        if not evidence.live_rebind_completed:
            downgrade_reasons.append(
                "live_rebind_completed=False/None — runtime rebind not completed"
            )
            policy_refs.append("REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY_POLICY")
            if evidence.history_accessible:
                return _v(
                    ConversationContinuityStatus.history_only_restored,
                    "Session identity is stable and history is accessible, but "
                    "live runtime rebind has not been completed.  Classified as "
                    "history_only_restored.",
                )
            return _v(
                ConversationContinuityStatus.state_restored_rebind_required,
                "Session identity is stable but live rebind has not been completed "
                "and history accessibility is not confirmed.  Classified as "
                "state_restored_rebind_required.",
            )

        # ----------------------------------------------------------------
        # Rule 5: History not accessible (rebind is done but history missing)
        # ----------------------------------------------------------------
        if not evidence.history_accessible:
            downgrade_reasons.append(
                "history_accessible=False/None — history not accessible after rebind"
            )
            policy_refs.append("HISTORY_VISIBLE_IS_NOT_CONVERSATION_CONTINUITY_POLICY")
            return _v(
                ConversationContinuityStatus.state_restored_rebind_required,
                "Session identity is stable and rebind was attempted, but history "
                "is not accessible.  Classified as state_restored_rebind_required.",
            )

        # ----------------------------------------------------------------
        # Rule 6: Context not consistent — partial_continuity
        # ----------------------------------------------------------------
        if not evidence.context_consistent:
            downgrade_reasons.append(
                "context_consistent=False/None — conversation context has gaps"
            )
            policy_refs.append("STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY")
            if evidence.is_partial_recovery:
                return _v(
                    ConversationContinuityStatus.partial_continuity,
                    "Session identity stable, rebind completed, history accessible, "
                    "but context is not consistent and recovery was partial.  "
                    "Classified as partial_continuity.",
                )
            return _v(
                ConversationContinuityStatus.partial_continuity,
                "Session identity stable, rebind completed, history accessible, "
                "but conversation context is not fully consistent.  "
                "Classified as partial_continuity.",
            )

        # ----------------------------------------------------------------
        # Rule 7: Partial recovery ceiling (all other signals positive)
        # ----------------------------------------------------------------
        if evidence.is_partial_recovery:
            return _v(
                ConversationContinuityStatus.partial_continuity,
                "All primary evidence signals are positive but recovery was "
                "partial.  Ceiling prevents authoritative_continuity_restored.  "
                "Classified as partial_continuity.",
            )

        # ----------------------------------------------------------------
        # Rule 8: All required dimensions positive — authoritative
        # ----------------------------------------------------------------
        policy_refs.append("CONVERSATION_CONTINUITY_TRUTH_AUTHORITY")
        return _v(
            ConversationContinuityStatus.authoritative_continuity_restored,
            "All required evidence dimensions are positive: session identity "
            "stable, live rebind completed, history accessible, context "
            "consistent.  Conversation continuity is authoritatively restored.",
        )


def _build_evidence_summary(evidence: ConversationContinuityEvidence) -> str:
    """Build a compact evidence summary string."""
    flags = {
        "identity": evidence.session_identity_stable,
        "history": evidence.history_accessible,
        "context": evidence.context_consistent,
        "rebind": evidence.live_rebind_completed,
        "task_cont": evidence.task_continuity_confirmed,
        "post_crash": evidence.is_post_crash,
        "partial_rec": evidence.is_partial_recovery,
    }
    parts = [f"{k}={v}" for k, v in flags.items()]
    return "evidence: " + ", ".join(parts)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def build_conversation_continuity_verdict(
    evidence: ConversationContinuityEvidence,
) -> ConversationContinuityVerdict:
    """Evaluate evidence and return a :class:`ConversationContinuityVerdict`.

    This is the primary public API for single-session evaluation.

    Parameters
    ----------
    evidence
        The :class:`ConversationContinuityEvidence` to evaluate.

    Returns
    -------
    ConversationContinuityVerdict
        Formal verdict with status, rationale, and downgrade reasons.
    """
    return ConversationContinuityTruthContract().evaluate(evidence)


# ---------------------------------------------------------------------------
# Probe-based evaluation (reads from existing V2 modules)
# ---------------------------------------------------------------------------


def evaluate_session_continuity_after_restart(
    session_id: Optional[str] = None,
) -> ConversationContinuityTruthReport:
    """Probe existing V2 modules and produce a continuity truth report.

    This function assembles a :class:`ConversationContinuityEvidence` bundle
    by probing the current process-level state of:

    * ``core.session_manager`` — session identity and history
    * ``core.continuation_rebind_registry`` — rebind completion status
    * ``core.inflight_task_continuity_contract`` — task continuity evidence
    * ``core.canonical_session_truth`` — session truth snapshot

    All probes are read-only and fail-graceful.  Missing or unavailable
    modules result in the corresponding evidence field being left as ``None``
    (unobserved), which triggers the appropriate downgrade per
    ``EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT_POLICY``.

    Parameters
    ----------
    session_id
        Optional session identifier to evaluate.  When None, probes
        aggregate across all available sessions (or produces a single
        system-level verdict if no session enumeration is available).

    Returns
    -------
    ConversationContinuityTruthReport
        Aggregated report with per-session verdicts and summary counts.
    """
    verdicts: List[ConversationContinuityVerdict] = []
    supporting_modules: List[str] = []

    # ----------------------------------------------------------------
    # Probe 1: session_manager — session identity and history
    # ----------------------------------------------------------------
    session_identity_stable: Optional[bool] = None
    history_accessible: Optional[bool] = None
    session_ids_to_evaluate: List[Optional[str]] = [session_id]

    try:
        from core.session_manager import SessionManager  # type: ignore[import]
        sm = SessionManager()
        supporting_modules.append("core.session_manager")

        if session_id is not None:
            sess = sm.get_session(session_id) if hasattr(sm, "get_session") else None
            if sess is not None:
                session_identity_stable = True
                hist = sm.get_history(session_id) if hasattr(sm, "get_history") else None
                history_accessible = bool(hist)
            else:
                session_identity_stable = False
                history_accessible = False
        else:
            # Enumerate all known sessions via public API
            all_session_summaries = (
                sm.list_sessions()
                if hasattr(sm, "list_sessions")
                else []
            )
            if all_session_summaries:
                session_ids_to_evaluate = [
                    s.get("id") or s.get("session_id")
                    for s in all_session_summaries
                    if isinstance(s, dict)
                ]
                # Filter out None values
                session_ids_to_evaluate = [
                    sid for sid in session_ids_to_evaluate if sid is not None
                ] or [None]
            else:
                session_ids_to_evaluate = [None]
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ConversationContinuityTruth: session_manager probe failed: %s", exc
        )

    # ----------------------------------------------------------------
    # Probe 2: continuation_rebind_registry — rebind completion
    # ----------------------------------------------------------------
    live_rebind_completed: Optional[bool] = None
    try:
        from core.continuation_rebind_registry import (  # type: ignore[import]
            get_continuation_rebind_registry,
            RebindState,
        )
        registry = get_continuation_rebind_registry()
        supporting_modules.append("core.continuation_rebind_registry")

        if session_id is not None and hasattr(registry, "get"):
            record = registry.get(session_id)
            if record is not None:
                state_val = getattr(record, "state", None)
                if state_val is not None:
                    live_rebind_completed = (
                        str(state_val) in ("RebindState.completed", "completed")
                        or state_val == RebindState.completed
                    )
        elif hasattr(registry, "snapshot"):
            # Use public snapshot() method to check completed count
            snap = registry.snapshot()
            completed_count = snap.get("completed", 0) if isinstance(snap, dict) else 0
            live_rebind_completed = completed_count > 0
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ConversationContinuityTruth: continuation_rebind_registry probe failed: %s",
            exc,
        )

    # ----------------------------------------------------------------
    # Probe 3: inflight_task_continuity_contract — task continuity
    # ----------------------------------------------------------------
    task_continuity_confirmed: Optional[bool] = None
    try:
        from core.inflight_task_continuity_contract import (  # type: ignore[import]
            build_continuity_report,
            TaskContinuityStatus,
        )
        task_report = build_continuity_report([])
        supporting_modules.append("core.inflight_task_continuity_contract")
        # task_continuity_confirmed = True only if there are resumed tasks;
        # zero tasks or only recoverable tasks is NOT task continuity confirmed.
        task_continuity_confirmed = (
            task_report.continuity_restored_count > 0
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ConversationContinuityTruth: inflight_task_continuity probe failed: %s", exc
        )

    # ----------------------------------------------------------------
    # Probe 4: canonical_session_truth — context consistency
    # ----------------------------------------------------------------
    context_consistent: Optional[bool] = None
    try:
        from core.canonical_session_truth import (  # type: ignore[import]
            get_canonical_session_truth,
        )
        cst = get_canonical_session_truth()
        supporting_modules.append("core.canonical_session_truth")
        if hasattr(cst, "is_consistent"):
            context_consistent = bool(cst.is_consistent)
        elif hasattr(cst, "to_dict"):
            d = cst.to_dict()
            context_consistent = bool(d.get("is_consistent", False))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "ConversationContinuityTruth: canonical_session_truth probe failed: %s", exc
        )

    # ----------------------------------------------------------------
    # Evaluate each session
    # ----------------------------------------------------------------
    contract = ConversationContinuityTruthContract()
    for sid in session_ids_to_evaluate:
        ev = ConversationContinuityEvidence(
            session_id=sid,
            session_identity_stable=session_identity_stable,
            history_accessible=history_accessible,
            context_consistent=context_consistent,
            live_rebind_completed=live_rebind_completed,
            task_continuity_confirmed=task_continuity_confirmed,
            is_post_crash=False,  # cannot determine at probe level without explicit signal
            is_partial_recovery=False,
            recovery_strategy="probe_based",
            supporting_modules=list(supporting_modules),
        )
        verdict = contract.evaluate(ev)
        verdicts.append(verdict)

    # ----------------------------------------------------------------
    # Aggregate
    # ----------------------------------------------------------------
    authoritative_count = sum(
        1 for v in verdicts
        if v.status == ConversationContinuityStatus.authoritative_continuity_restored
    )
    partial_count = sum(
        1 for v in verdicts
        if v.status == ConversationContinuityStatus.partial_continuity
    )
    history_only_count = sum(
        1 for v in verdicts
        if v.status == ConversationContinuityStatus.history_only_restored
    )
    rebind_required_count = sum(
        1 for v in verdicts
        if v.status == ConversationContinuityStatus.state_restored_rebind_required
    )
    lost_count = sum(
        1 for v in verdicts
        if v.status == ConversationContinuityStatus.continuity_lost
    )

    return ConversationContinuityTruthReport(
        verdicts=verdicts,
        authoritative_count=authoritative_count,
        partial_count=partial_count,
        history_only_count=history_only_count,
        rebind_required_count=rebind_required_count,
        lost_count=lost_count,
        has_any_authoritative=authoritative_count > 0,
        has_any_lost=lost_count > 0,
        notes=(
            "Probed: " + ", ".join(supporting_modules)
            if supporting_modules
            else "No V2 modules available; all evidence unobserved."
        ),
    )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_report_lock = threading.Lock()
_cached_report: Optional[ConversationContinuityTruthReport] = None


def get_conversation_continuity_truth_report(
    session_id: Optional[str] = None,
) -> ConversationContinuityTruthReport:
    """Return a cached :class:`ConversationContinuityTruthReport`.

    The cache is invalidated by :func:`reset_conversation_continuity_truth_report`.
    Use :func:`evaluate_session_continuity_after_restart` directly when a
    fresh report is required (e.g. in CI or after a restart event).

    Parameters
    ----------
    session_id
        Optional session identifier; passed to the underlying evaluator
        if the cache is cold.
    """
    global _cached_report
    with _report_lock:
        if _cached_report is None:
            _cached_report = evaluate_session_continuity_after_restart(
                session_id=session_id
            )
        return _cached_report


def reset_conversation_continuity_truth_report() -> None:
    """Reset the cached report (for testing and post-restart use).

    Call this function after a restart event to ensure the next call to
    :func:`get_conversation_continuity_truth_report` performs a fresh
    evaluation rather than returning the pre-restart cache.
    """
    global _cached_report
    with _report_lock:
        _cached_report = None
