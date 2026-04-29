#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/human_intervention_taxonomy.py
=====================================
PR-08: Human Intervention Taxonomy — formal system-level classification
of human escalation, operator takeover, and manual intervention semantics.

Problem addressed
-----------------
The Galaxy V2 system already supports human-in-the-loop (HITL) flows,
operator override surfaces, and manual recovery paths.  However, before
this module the boundary between *system autonomous closure* and *human-
assisted closure* was not formally modelled.  This created a silent
optimism risk: a task or decision that was only completed because a human
intervened could be reported as if the system had reached autonomous
operational closure on its own.

Specifically, the following distinctions were absent:

* **autonomous_closure** vs **operator_assisted_closure** — was the
  closure reached without any human action, or did an operator step in to
  complete it?
* **human_confirmed_system_incomplete** — a human confirmed a result, but
  the system alone could not have produced a complete result.
* **manual_override** — a human explicitly overrode the system's decision
  or action rather than confirming it.
* **escalation_required** — the system was unable to produce a result and
  escalated to a human without the human yet responding.

Without these distinctions, ``acceptance`` / ``governance`` / ``runtime
truth`` surfaces cannot distinguish "the system closed autonomously" from
"the system only appears closed because a human filled the gap".

This module closes that gap by establishing the **Human Intervention
Taxonomy** — a formal classification contract that:

1. Defines five mutually exclusive and exhaustive
   :class:`HumanInterventionClass` values.
2. Specifies precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient evidence or
   any detected human involvement always produces the lowest defensible
   class rather than the optimistic one.
4. Prohibits treating human confirmation, manual patch-up, operator
   takeover, or escalation as equivalent to autonomous system closure.
5. Provides a :class:`HumanInterventionVerdict` dataclass consumable by
   acceptance / governance / runtime truth / readiness pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  HUMAN INTERVENTION TAXONOMY  (this module — PR-08)                 │
    │                                                                     │
    │  Five intervention classes (strictly ordered by autonomy):         │
    │    1. autonomous_closure             (highest — no human action)   │
    │    2. operator_assisted_closure      (human helped; system drove)  │
    │    3. human_confirmed_system_incomplete  (human confirmed a result  │
    │       the system alone could not complete)                         │
    │    4. manual_override                (human overrode system)       │
    │    5. escalation_required            (lowest — system escalated;   │
    │       human has not yet responded)                                 │
    │                                                                     │
    │  Evidence dimensions evaluated:                                    │
    │    • operator_action_observed      — any operator action detected  │
    │    • manual_override_observed      — human overrode system decision│
    │    • human_confirmation_observed   — human confirmed a result      │
    │    • system_incomplete_without_human — system could not complete   │
    │      task without human involvement                                │
    │    • escalation_triggered          — system explicitly escalated   │
    │    • escalation_resolved           — escalation was resolved by    │
    │      human response                                                │
    │    • autonomous_evidence_present   — explicit evidence of system   │
    │      self-closure without human                                    │
    │                                                                     │
    │  Downgrade semantics:                                              │
    │    • manual_override_observed → NEVER autonomous_closure or        │
    │      operator_assisted_closure                                     │
    │    • escalation_triggered and not resolved → ALWAYS                │
    │      escalation_required                                           │
    │    • human_confirmation_observed + system_incomplete_without_human │
    │      → NEVER autonomous_closure or operator_assisted_closure       │
    │    • operator_action_observed → NEVER autonomous_closure           │
    │    • no evidence → escalation_required (fail-conservative)         │
    │                                                                     │
    │  Produces:                                                         │
    │    • HumanInterventionVerdict  (structured output)                 │
    │                                                                     │
    │  Consumed by:                                                      │
    │    • system_final_acceptance_verdict (human_intervention dimension) │
    │    • acceptance / governance / runtime truth / readiness surfaces  │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class (``escalation_required``) rather than the optimistic one.
3. **No optimistic promotion** — operator action, human confirmation, and
   escalation are explicitly excluded from being promoted to
   ``autonomous_closure``.
4. **Taxonomy boundary enforcement** — human confirmation does NOT imply
   system completeness; operator assistance does NOT imply autonomy;
   manual override does NOT imply normal system operation.
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Critical boundary: what counts as autonomous closure vs what does not
----------------------------------------------------------------------
- **Operator action observed** — does NOT constitute autonomous closure;
  an operator stepped into the operational path.
- **Human confirmation** — does NOT constitute autonomous closure; even
  if the system produced a partial result, confirmation indicates a human
  was required to validate or complete the flow.
- **Escalation triggered** — does NOT constitute any form of closure until
  the escalation is explicitly resolved.
- **Manual override** — must never be classified as normal system operation;
  the human explicitly replaced the system's decision.
- **No evidence** — cannot be treated as autonomous closure; absence of
  intervention evidence alone is insufficient without positive
  ``autonomous_evidence_present``.

Public API
----------
Sentinels::

    HUMAN_INTERVENTION_TAXONOMY_AUTHORITY
    HUMAN_INTERVENTION_TAXONOMY_PR08_SENTINEL
    AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_POLICY
    OPERATOR_ASSISTED_IS_NOT_AUTONOMOUS_CLOSURE_POLICY
    HUMAN_CONFIRMATION_DOES_NOT_IMPLY_SYSTEM_COMPLETE_POLICY
    MANUAL_OVERRIDE_MUST_NOT_BE_OPTIMISTICALLY_RECLASSIFIED_POLICY
    ESCALATION_REQUIRED_BLOCKS_CLOSURE_VERDICT_POLICY
    EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_POLICY

Enumerations::

    HumanInterventionClass

Data classes::

    HumanInterventionEvidence
    HumanInterventionVerdict

Functions::

    build_human_intervention_verdict(evidence) -> HumanInterventionVerdict
    classify_autonomy_level(evidence) -> HumanInterventionClass
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.HumanInterventionTaxonomy")

__all__ = [
    # Sentinels
    "HUMAN_INTERVENTION_TAXONOMY_AUTHORITY",
    "HUMAN_INTERVENTION_TAXONOMY_PR08_SENTINEL",
    "AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_POLICY",
    "OPERATOR_ASSISTED_IS_NOT_AUTONOMOUS_CLOSURE_POLICY",
    "HUMAN_CONFIRMATION_DOES_NOT_IMPLY_SYSTEM_COMPLETE_POLICY",
    "MANUAL_OVERRIDE_MUST_NOT_BE_OPTIMISTICALLY_RECLASSIFIED_POLICY",
    "ESCALATION_REQUIRED_BLOCKS_CLOSURE_VERDICT_POLICY",
    "EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_POLICY",
    # Enumerations
    "HumanInterventionClass",
    # Data classes
    "HumanInterventionEvidence",
    "HumanInterventionVerdict",
    # Functions
    "build_human_intervention_verdict",
    "classify_autonomy_level",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

HUMAN_INTERVENTION_TAXONOMY_AUTHORITY: str = (
    "HUMAN_INTERVENTION_TAXONOMY_AUTHORITY::"
    "core.human_intervention_taxonomy::PR08::"
    "human-escalation-operator-takeover-manual-intervention-taxonomy::"
    "single-authoritative-semantic-boundary-definition"
)
"""Sentinel: this module is the canonical taxonomy authority for the V2
human intervention / operator takeover / manual escalation surface.  Import
this sentinel to assert that downstream surfaces are aligned with the unified
human intervention taxonomy rather than maintaining ad-hoc term definitions.
In particular: presence of human intervention MUST NOT be treated as evidence
that the system reached autonomous operational closure."""

HUMAN_INTERVENTION_TAXONOMY_PR08_SENTINEL: str = (
    "HUMAN_INTERVENTION_TAXONOMY_PR08_SENTINEL::"
    "package=PR08::profile=human-intervention-taxonomy-v1::"
    "module=core.human_intervention_taxonomy"
)
"""Package sentinel for PR-08 human intervention taxonomy."""

AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_POLICY: str = (
    "POLICY::AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_V1: "
    "A closure verdict of autonomous_closure REQUIRES that no operator "
    "action, human confirmation, manual override, or escalation was "
    "observed in the operational path.  Autonomous closure means the "
    "system drove the decision, execution, and completion entirely on its "
    "own without human involvement.  "
    "autonomous_evidence_present MUST be True for this class.  "
    "Any detected human action MUST prevent autonomous_closure.  "
    "See: HumanInterventionClass.autonomous_closure."
)
"""Policy: autonomous_closure requires complete absence of human action."""

OPERATOR_ASSISTED_IS_NOT_AUTONOMOUS_CLOSURE_POLICY: str = (
    "POLICY::OPERATOR_ASSISTED_IS_NOT_AUTONOMOUS_CLOSURE_V1: "
    "operator_assisted_closure MUST NOT be reported as or promoted to "
    "autonomous_closure.  Operator assistance means a human entered the "
    "operational path to help complete the task, even if the system "
    "initiated and drove the primary flow.  "
    "Systems and governance surfaces that consume closure verdicts MUST "
    "distinguish between operator-assisted and autonomous outcomes.  "
    "Reporting 'fully_autonomous' or 'system_self_closed' when an operator "
    "assisted is a contract violation.  "
    "See: HumanInterventionClass.operator_assisted_closure."
)
"""Policy: operator-assisted closure is not equivalent to autonomous closure."""

HUMAN_CONFIRMATION_DOES_NOT_IMPLY_SYSTEM_COMPLETE_POLICY: str = (
    "POLICY::HUMAN_CONFIRMATION_DOES_NOT_IMPLY_SYSTEM_COMPLETE_V1: "
    "When a human confirmed a result AND the system alone could not have "
    "produced a complete result (system_incomplete_without_human=True), "
    "the closure class MUST be human_confirmed_system_incomplete.  "
    "Human confirmation of a partial or incomplete system output does NOT "
    "elevate the closure verdict to operator_assisted_closure or "
    "autonomous_closure.  "
    "See: HumanInterventionClass.human_confirmed_system_incomplete."
)
"""Policy: human confirmation + system incompleteness → human_confirmed_system_incomplete."""

MANUAL_OVERRIDE_MUST_NOT_BE_OPTIMISTICALLY_RECLASSIFIED_POLICY: str = (
    "POLICY::MANUAL_OVERRIDE_MUST_NOT_BE_OPTIMISTICALLY_RECLASSIFIED_V1: "
    "When a human manually overrode the system's decision or action "
    "(manual_override_observed=True), the closure class MUST be "
    "manual_override.  A manual override MUST NOT be reclassified as "
    "operator_assisted_closure, human_confirmed_system_incomplete, or "
    "autonomous_closure.  Manual override means the system's output was "
    "actively replaced by a human decision; the system did not close the "
    "task — the human did.  "
    "See: HumanInterventionClass.manual_override."
)
"""Policy: manual override must always yield manual_override class."""

ESCALATION_REQUIRED_BLOCKS_CLOSURE_VERDICT_POLICY: str = (
    "POLICY::ESCALATION_REQUIRED_BLOCKS_CLOSURE_VERDICT_V1: "
    "When an escalation has been triggered but not yet resolved "
    "(escalation_triggered=True AND escalation_resolved=False), the "
    "closure class MUST be escalation_required.  An open escalation "
    "means the system was unable to produce a result and is waiting for "
    "human action.  This state MUST block any positive closure verdict.  "
    "Closing a task as 'autonomous' or 'operator-assisted' while an "
    "escalation is still open is a contract violation.  "
    "See: HumanInterventionClass.escalation_required."
)
"""Policy: open escalation always yields escalation_required."""

EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_POLICY: str = (
    "POLICY::EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_V1: "
    "When no evidence is present — no operator action, no human "
    "confirmation, no manual override, no escalation signal, and no "
    "autonomous_evidence_present — the taxonomy MUST default to "
    "escalation_required rather than autonomous_closure.  "
    "Absence of intervention evidence alone is NOT positive evidence of "
    "autonomous closure.  Autonomous closure requires explicit positive "
    "evidence (autonomous_evidence_present=True) combined with absence of "
    "all human-action signals.  "
    "See: classify_autonomy_level() and build_human_intervention_verdict()."
)
"""Policy: no evidence defaults to escalation_required (fail-conservative)."""


# ---------------------------------------------------------------------------
# HumanInterventionClass
# ---------------------------------------------------------------------------


class HumanInterventionClass(str, Enum):
    """Five-value canonical taxonomy for classifying the autonomy level of
    an operational closure, decision, or task completion.

    Values are strictly ordered from highest autonomy (``autonomous_closure``)
    to lowest (``escalation_required``).  Downgrade semantics ensure that
    insufficient evidence or any detected human involvement yields the lowest
    defensible class.

    Values
    ------
    autonomous_closure
        The system reached closure entirely on its own without any human
        action.  No operator action, human confirmation, manual override,
        or escalation was observed.  ``autonomous_evidence_present`` MUST
        be True.  This is the only class that represents genuine system
        self-closure.

    operator_assisted_closure
        The system initiated and drove the primary flow, but an operator
        stepped in to help complete, confirm, or advance the task.  The
        operator action was assistive (not overriding).  The system could
        have theoretically completed the task but the operator participated.
        ``operator_action_observed`` is True; ``manual_override_observed``
        is False; ``system_incomplete_without_human`` is False.

    human_confirmed_system_incomplete
        A human confirmed a result, but the system alone could not have
        produced a complete result.  The system's output was partial or
        incomplete; human involvement was necessary to reach any closure.
        ``human_confirmation_observed`` is True AND
        ``system_incomplete_without_human`` is True.  MUST NOT be promoted
        to autonomous_closure or operator_assisted_closure.

    manual_override
        A human explicitly overrode the system's decision or action.  The
        system produced (or attempted to produce) a result, but the human
        replaced it.  The system did not close the task autonomously.
        ``manual_override_observed`` is True.

    escalation_required
        The system was unable to produce a result and escalated to a human,
        but the escalation has not yet been resolved.  No closure has been
        reached at all.  ``escalation_triggered`` is True and
        ``escalation_resolved`` is False, OR no evidence is available
        (fail-conservative default).
    """

    autonomous_closure = "autonomous_closure"
    operator_assisted_closure = "operator_assisted_closure"
    human_confirmed_system_incomplete = "human_confirmed_system_incomplete"
    manual_override = "manual_override"
    escalation_required = "escalation_required"

    @classmethod
    def from_string(cls, value: str) -> "HumanInterventionClass":
        """Return the member matching *value*, defaulting to
        ``escalation_required`` (fail-conservative)."""
        if not isinstance(value, str):
            return cls.escalation_required
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.escalation_required

    # Ordering helpers

    @property
    def rank(self) -> int:
        """Return the autonomy rank (higher = more autonomous).

        autonomous_closure=4, operator_assisted_closure=3,
        human_confirmed_system_incomplete=2, manual_override=1,
        escalation_required=0.
        """
        return _INTERVENTION_CLASS_RANK.get(self.value, 0)

    def is_at_least(self, other: "HumanInterventionClass") -> bool:
        """Return True when ``self`` has rank >= ``other``."""
        return self.rank >= other.rank

    @property
    def is_autonomous(self) -> bool:
        """Return True only when this is ``autonomous_closure``."""
        return self == HumanInterventionClass.autonomous_closure

    @property
    def involves_human_action(self) -> bool:
        """Return True when a human took some action in the closure path."""
        return self in (
            HumanInterventionClass.operator_assisted_closure,
            HumanInterventionClass.human_confirmed_system_incomplete,
            HumanInterventionClass.manual_override,
            HumanInterventionClass.escalation_required,
        )

    @property
    def is_positive_closure(self) -> bool:
        """Return True when any form of closure was reached (resolved or not).

        ``escalation_required`` is NOT a positive closure — it means no
        closure has been reached yet.  All other classes indicate some form
        of closure (autonomous or human-assisted) has occurred.
        """
        return self != HumanInterventionClass.escalation_required


# Rank table defined outside the class to avoid class-level forward-reference issues.
_INTERVENTION_CLASS_RANK: Dict[str, int] = {
    HumanInterventionClass.escalation_required.value: 0,
    HumanInterventionClass.manual_override.value: 1,
    HumanInterventionClass.human_confirmed_system_incomplete.value: 2,
    HumanInterventionClass.operator_assisted_closure.value: 3,
    HumanInterventionClass.autonomous_closure.value: 4,
}


# ---------------------------------------------------------------------------
# HumanInterventionEvidence
# ---------------------------------------------------------------------------


@dataclass
class HumanInterventionEvidence:
    """Structured evidence dimensions used to classify human intervention.

    All fields default to their conservative value so that a zero-evidence
    instance correctly yields ``escalation_required`` rather than an
    optimistic class.

    Fields
    ------
    operator_action_observed
        True when any operator action was detected in the operational path
        (e.g. operator acknowledged, advanced, or supplemented a task).
        Does NOT include manual override (see ``manual_override_observed``).

    manual_override_observed
        True when a human explicitly replaced or overrode the system's
        decision, action, or output.  This is the strongest form of human
        intervention.  MUST produce ``manual_override`` class regardless
        of other evidence.

    human_confirmation_observed
        True when a human confirmed, validated, or approved a result or
        decision produced by the system.  On its own, confirmation suggests
        operator assistance.  Combined with ``system_incomplete_without_human``
        it yields ``human_confirmed_system_incomplete``.

    system_incomplete_without_human
        True when the system alone could NOT have produced a complete result
        for this task/decision.  Human involvement was necessary, not merely
        assistive.

    escalation_triggered
        True when the system explicitly triggered an escalation to a human
        because it could not proceed autonomously.

    escalation_resolved
        True when an active escalation has been resolved by human response.
        Only meaningful when ``escalation_triggered`` is also True.

    autonomous_evidence_present
        True when there is explicit positive evidence that the system closed
        the task/decision entirely without human involvement.  Absence of
        this flag alone is NOT sufficient to assume autonomous closure.

    context
        Optional free-form context dict for audit/trace purposes.
    """

    operator_action_observed: bool = False
    manual_override_observed: bool = False
    human_confirmation_observed: bool = False
    system_incomplete_without_human: bool = False
    escalation_triggered: bool = False
    escalation_resolved: bool = False
    autonomous_evidence_present: bool = False
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "operator_action_observed": self.operator_action_observed,
            "manual_override_observed": self.manual_override_observed,
            "human_confirmation_observed": self.human_confirmation_observed,
            "system_incomplete_without_human": self.system_incomplete_without_human,
            "escalation_triggered": self.escalation_triggered,
            "escalation_resolved": self.escalation_resolved,
            "autonomous_evidence_present": self.autonomous_evidence_present,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HumanInterventionEvidence":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            operator_action_observed=bool(
                data.get("operator_action_observed", False)
            ),
            manual_override_observed=bool(
                data.get("manual_override_observed", False)
            ),
            human_confirmation_observed=bool(
                data.get("human_confirmation_observed", False)
            ),
            system_incomplete_without_human=bool(
                data.get("system_incomplete_without_human", False)
            ),
            escalation_triggered=bool(data.get("escalation_triggered", False)),
            escalation_resolved=bool(data.get("escalation_resolved", False)),
            autonomous_evidence_present=bool(
                data.get("autonomous_evidence_present", False)
            ),
            context=dict(data.get("context", {})),
        )


# ---------------------------------------------------------------------------
# HumanInterventionVerdict
# ---------------------------------------------------------------------------


@dataclass
class HumanInterventionVerdict:
    """Structured verdict produced by :func:`build_human_intervention_verdict`.

    Fields
    ------
    intervention_class
        The canonical :class:`HumanInterventionClass` for this evaluation.
    is_autonomous
        Convenience flag: True only when
        ``intervention_class == autonomous_closure``.
    involves_human_action
        True when a human took some action in the closure path.
    is_positive_closure
        True when any closure was reached (autonomous or human-assisted).
        False for ``escalation_required`` (no closure reached).
    downgrade_reasons
        List of human-readable strings explaining why the verdict was
        downgraded from ``autonomous_closure``.  Empty when autonomous.
    evidence_summary
        Human-readable summary of the evidence evaluated.
    evaluated_evidence
        The :class:`HumanInterventionEvidence` instance used.
    verdict_id
        Stable UUID for this verdict instance.
    evaluated_at
        Unix timestamp of evaluation.
    """

    intervention_class: HumanInterventionClass = (
        HumanInterventionClass.escalation_required
    )
    is_autonomous: bool = False
    involves_human_action: bool = True
    is_positive_closure: bool = False
    downgrade_reasons: List[str] = field(default_factory=list)
    evidence_summary: str = ""
    evaluated_evidence: Optional[HumanInterventionEvidence] = None
    verdict_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "intervention_class": self.intervention_class.value,
            "is_autonomous": self.is_autonomous,
            "involves_human_action": self.involves_human_action,
            "is_positive_closure": self.is_positive_closure,
            "downgrade_reasons": list(self.downgrade_reasons),
            "evidence_summary": self.evidence_summary,
            "evaluated_evidence": (
                self.evaluated_evidence.to_dict()
                if self.evaluated_evidence is not None
                else None
            ),
            "verdict_id": self.verdict_id,
            "evaluated_at": self.evaluated_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HumanInterventionVerdict":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        evidence_data = data.get("evaluated_evidence")
        evidence = (
            HumanInterventionEvidence.from_dict(evidence_data)
            if evidence_data is not None
            else None
        )
        intervention_class = HumanInterventionClass.from_string(
            data.get("intervention_class", "")
        )
        return cls(
            intervention_class=intervention_class,
            is_autonomous=bool(data.get("is_autonomous", False)),
            involves_human_action=bool(data.get("involves_human_action", True)),
            is_positive_closure=bool(data.get("is_positive_closure", False)),
            downgrade_reasons=list(data.get("downgrade_reasons", [])),
            evidence_summary=data.get("evidence_summary", ""),
            evaluated_evidence=evidence,
            verdict_id=data.get("verdict_id", uuid.uuid4().hex[:12]),
            evaluated_at=data.get("evaluated_at", time.time()),
        )


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------


def classify_autonomy_level(
    evidence: HumanInterventionEvidence,
) -> HumanInterventionClass:
    """Classify the autonomy level from *evidence* using strict downgrade semantics.

    Downgrade priority (highest to lowest, applied in order):

    1. ``manual_override_observed`` → ``manual_override``
    2. ``escalation_triggered`` and not ``escalation_resolved``
       → ``escalation_required``
    3. ``human_confirmation_observed`` and ``system_incomplete_without_human``
       → ``human_confirmed_system_incomplete``
    4. ``operator_action_observed`` OR (``human_confirmation_observed`` and
       NOT ``system_incomplete_without_human``)
       → ``operator_assisted_closure``
    5. ``autonomous_evidence_present`` and no human-action signals
       → ``autonomous_closure``
    6. No evidence at all → ``escalation_required`` (fail-conservative)

    Parameters
    ----------
    evidence:
        The :class:`HumanInterventionEvidence` instance to evaluate.

    Returns
    -------
    HumanInterventionClass
        The conservatively classified intervention class.
    """
    # Priority 1: manual override — strongest signal; always dominates
    if evidence.manual_override_observed:
        return HumanInterventionClass.manual_override

    # Priority 2: open escalation — system could not proceed on its own
    if evidence.escalation_triggered and not evidence.escalation_resolved:
        return HumanInterventionClass.escalation_required

    # Priority 3: human confirmed but system was incomplete without human
    if evidence.human_confirmation_observed and evidence.system_incomplete_without_human:
        return HumanInterventionClass.human_confirmed_system_incomplete

    # Priority 4: operator assisted (action or confirmation without incompleteness)
    if evidence.operator_action_observed or evidence.human_confirmation_observed:
        return HumanInterventionClass.operator_assisted_closure

    # Priority 5: autonomous closure — requires explicit positive evidence
    # AND absence of all human-action signals (already checked above)
    if evidence.autonomous_evidence_present:
        return HumanInterventionClass.autonomous_closure

    # Priority 6: no evidence → fail-conservative default
    return HumanInterventionClass.escalation_required


def _build_downgrade_reasons(
    evidence: HumanInterventionEvidence,
    result_class: HumanInterventionClass,
) -> List[str]:
    """Produce a list of human-readable downgrade reasons for *result_class*."""
    if result_class == HumanInterventionClass.autonomous_closure:
        return []

    reasons: List[str] = []

    if evidence.manual_override_observed:
        reasons.append(
            "manual_override_observed=True: human explicitly replaced system "
            "decision/action — MANUAL_OVERRIDE_MUST_NOT_BE_OPTIMISTICALLY_"
            "RECLASSIFIED_POLICY applied."
        )

    if evidence.escalation_triggered and not evidence.escalation_resolved:
        reasons.append(
            "escalation_triggered=True, escalation_resolved=False: system "
            "escalated to human but escalation is unresolved — "
            "ESCALATION_REQUIRED_BLOCKS_CLOSURE_VERDICT_POLICY applied."
        )

    if evidence.human_confirmation_observed and evidence.system_incomplete_without_human:
        reasons.append(
            "human_confirmation_observed=True + system_incomplete_without_human=True: "
            "human confirmed a result the system alone could not complete — "
            "HUMAN_CONFIRMATION_DOES_NOT_IMPLY_SYSTEM_COMPLETE_POLICY applied."
        )

    if evidence.operator_action_observed:
        reasons.append(
            "operator_action_observed=True: operator entered the operational "
            "path — OPERATOR_ASSISTED_IS_NOT_AUTONOMOUS_CLOSURE_POLICY applied."
        )

    if evidence.human_confirmation_observed and not evidence.system_incomplete_without_human:
        reasons.append(
            "human_confirmation_observed=True: human confirmed the result — "
            "AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_POLICY applied."
        )

    if not evidence.autonomous_evidence_present and not reasons:
        reasons.append(
            "autonomous_evidence_present=False and no other signals present: "
            "no positive evidence of autonomous closure — "
            "EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_POLICY applied."
        )

    return reasons


def _build_evidence_summary(
    evidence: HumanInterventionEvidence,
    result_class: HumanInterventionClass,
) -> str:
    """Build a human-readable summary string for the verdict."""
    flags: List[str] = []
    if evidence.autonomous_evidence_present:
        flags.append("autonomous_evidence")
    if evidence.operator_action_observed:
        flags.append("operator_action")
    if evidence.manual_override_observed:
        flags.append("manual_override")
    if evidence.human_confirmation_observed:
        flags.append("human_confirmation")
    if evidence.system_incomplete_without_human:
        flags.append("system_incomplete_without_human")
    if evidence.escalation_triggered:
        status = "resolved" if evidence.escalation_resolved else "open"
        flags.append(f"escalation_triggered({status})")

    flags_str = ", ".join(flags) if flags else "no_signals"
    return (
        f"HumanInterventionTaxonomy: class={result_class.value}; "
        f"evidence=[{flags_str}]; "
        f"is_autonomous={result_class.is_autonomous}; "
        f"is_positive_closure={result_class.is_positive_closure}."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_human_intervention_verdict(
    evidence: Optional[HumanInterventionEvidence] = None,
) -> HumanInterventionVerdict:
    """Build a :class:`HumanInterventionVerdict` from *evidence*.

    This is the canonical classification entry-point for
    acceptance / governance / runtime truth / readiness consumers.

    Parameters
    ----------
    evidence:
        The :class:`HumanInterventionEvidence` to evaluate.  When ``None``
        (or not provided), a zero-evidence instance is used, which yields
        ``escalation_required`` per the fail-conservative policy.

    Returns
    -------
    HumanInterventionVerdict
        Structured verdict with the classified :class:`HumanInterventionClass`,
        downgrade reasons, and evidence summary.
    """
    if evidence is None:
        evidence = HumanInterventionEvidence()

    result_class = classify_autonomy_level(evidence)
    downgrade_reasons = _build_downgrade_reasons(evidence, result_class)
    evidence_summary = _build_evidence_summary(evidence, result_class)

    verdict = HumanInterventionVerdict(
        intervention_class=result_class,
        is_autonomous=result_class.is_autonomous,
        involves_human_action=result_class.involves_human_action,
        is_positive_closure=result_class.is_positive_closure,
        downgrade_reasons=downgrade_reasons,
        evidence_summary=evidence_summary,
        evaluated_evidence=evidence,
    )

    logger.debug(
        "build_human_intervention_verdict: class=%s is_autonomous=%s",
        result_class.value,
        result_class.is_autonomous,
    )

    return verdict
