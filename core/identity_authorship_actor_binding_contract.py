#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/identity_authorship_actor_binding_contract.py
====================================================
PR: Identity / Authorship / Actor-Binding Semantics Contract.

Background
----------
The Galaxy V2 system already possesses substantial actor and identity
awareness across its surfaces: participant lifecycle truth, task execution
identity, evidence/result ingestion, review/finalization paths, delegation
transfers, and source attribution all carry some form of actor or identity
information.  This demonstrates that the system is not oblivious to who is
doing what.

However, before this module the system had no formal contract that
distinguished *having an actor field* from *identity authoritatively bound*.
The practical risk was silent optimism: a system that merely recorded a
participant ID, source label, or author string could classify — or report
itself — as having "formally verified identity and authorship semantics"
merely because the field was non-empty.

Specifically, the following distinctions were absent:

* **identity_authoritatively_bound** — the actor/participant identity has
  been positively verified through an authoritative channel; binding is
  confirmed, not merely asserted.
* **authorship_verified** — the claimed authorship of an artifact, result,
  or action has been verified through a validation process beyond mere
  assertion; the author claim is substantiated.
* **asserted_but_unverified** — an actor, author, or source has been
  claimed or recorded but the claim has not been subjected to any
  independent verification process.  The claim may be correct, but it is
  not confirmed.
* **delegated_or_proxy_actor** — the action, result, or artifact was
  produced under a delegation or proxy arrangement; the recorded actor is
  not the primary originator but an intermediary, delegate, or proxy.
  This is NOT the same as direct verified authorship.
* **identity_or_provenance_uncertain** — the identity, authorship, or
  provenance is unknown, missing, ambiguous, or has been explicitly flagged
  as uncertain.  This is the fail-conservative default.

Without these distinctions, ``runtime truth`` / ``acceptance`` /
``readiness`` / ``governance`` surfaces cannot tell the difference between:
- "we stored a participant_id field" and "participant identity is formally
  bound and verified",
- "author string is present" and "authorship has been verified",
- "delegation transfer occurred" and "primary actor identity is confirmed".

This module closes that gap by establishing the **Identity / Authorship /
Actor-Binding Semantics Contract** — a formal classification contract that:

1. Defines five mutually exclusive and exhaustive
   :class:`IdentityBindingClass` values.
2. Specifies precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient, ambiguous,
   or unverified evidence always produces the lowest defensible class
   rather than the optimistic one.
4. Prohibits treating actor-field presence, assertion, delegation, or
   proxy binding as equivalent to authoritative identity binding.
5. Provides an :class:`IdentityBindingVerdict` dataclass consumable by
   runtime truth / acceptance / readiness / governance pipelines.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  IDENTITY / AUTHORSHIP / ACTOR-BINDING CONTRACT  (this module)      │
    │                                                                      │
    │  Five identity binding classes (strictly ordered by binding          │
    │  confidence / authority):                                            │
    │    1. identity_authoritatively_bound  (highest — actor/participant  │
    │       identity verified through authoritative channel; binding       │
    │       confirmed, not merely asserted; primary actor is the          │
    │       verified origin)                                               │
    │    2. authorship_verified             (authorship of an artifact,   │
    │       result, or action has been validated beyond mere assertion;   │
    │       author claim is substantiated by independent verification)    │
    │    3. asserted_but_unverified         (actor, author, or source     │
    │       has been claimed or recorded; no independent verification     │
    │       has been performed; claim may be correct but is unconfirmed) │
    │    4. delegated_or_proxy_actor        (action/artifact produced     │
    │       under delegation or proxy; recorded actor is not the primary │
    │       originator; NOT equivalent to direct verified authorship)     │
    │    5. identity_or_provenance_uncertain (lowest — identity,         │
    │       authorship, or provenance is unknown, missing, ambiguous,    │
    │       or explicitly flagged uncertain; fail-conservative default)  │
    │                                                                      │
    │  Evidence dimensions evaluated:                                     │
    │    • actor_field_present        — an actor/participant field exists │
    │    • identity_verified_by_authority — verified by auth. channel    │
    │    • authorship_validated       — authorship independently checked │
    │    • binding_confirmed          — binding was positively confirmed │
    │    • is_delegation_or_proxy     — delegation/proxy arrangement     │
    │    • delegation_explicitly_documented — delegation is formal       │
    │    • assertion_only             — claim with no verification       │
    │    • provenance_missing_or_ambiguous — no clear provenance         │
    │    • identity_explicitly_uncertain  — flagged as uncertain         │
    │    • multiple_authority_sources_agree — ≥2 auth. sources agree    │
    │                                                                      │
    │  Downgrade semantics:                                               │
    │    • identity_explicitly_uncertain → ALWAYS                         │
    │      identity_or_provenance_uncertain                               │
    │    • provenance_missing_or_ambiguous → NEVER                        │
    │      identity_authoritatively_bound or authorship_verified          │
    │    • is_delegation_or_proxy → NEVER identity_authoritatively_bound │
    │      or authorship_verified (direct); at most delegated_or_proxy   │
    │    • assertion_only (no verification) → NEVER                       │
    │      identity_authoritatively_bound or authorship_verified          │
    │    • actor_field_present alone → NEVER authoritatively_bound        │
    │    • no positive evidence → identity_or_provenance_uncertain         │
    │      (fail-conservative)                                             │
    │                                                                      │
    │  Produces:                                                          │
    │    • IdentityBindingVerdict  (structured output)                    │
    │                                                                      │
    │  Consumed by:                                                       │
    │    • system_final_acceptance_verdict                                │
    │      (identity_authorship_binding dimension)                        │
    │    • runtime truth / acceptance / readiness / governance surfaces  │
    └──────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class (``identity_or_provenance_uncertain``) rather than
   the optimistic one.
3. **No optimistic promotion** — actor field presence, assertion, delegation,
   and proxy binding are explicitly excluded from being promoted to
   ``identity_authoritatively_bound`` or ``authorship_verified``.
4. **Taxonomy boundary enforcement** — "actor field is non-empty" does NOT
   imply "identity authoritatively bound"; "delegation occurred" does NOT
   imply "authorship verified"; "source string present" does NOT imply
   "provenance is confirmed".
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Critical boundary: what counts as authoritative binding vs what does not
------------------------------------------------------------------------
- **Actor field presence** — does NOT constitute authoritative identity
  binding.  The field existing (even with a non-empty value) does not mean
  the identity claim has been subjected to any verification process.
- **Bare assertion** — does NOT constitute authorship_verified.  An author
  string in a record is an assertion, not a verified claim.
- **Delegation / proxy** — does NOT constitute identity_authoritatively_bound
  or direct authorship_verified.  A delegate or proxy may legitimately act
  on behalf of a principal, but the recorded actor identity is that of the
  delegate/proxy, not the primary originator.  This MUST be captured as
  ``delegated_or_proxy_actor`` rather than masked as authoritative binding.
- **Source attribution without validation** — does NOT constitute
  provenance confirmation.  A ``source`` field in a result or evidence
  object is metadata; it becomes provenance only when validated by an
  authoritative process.
- **No evidence** — cannot be treated as any class above
  ``identity_or_provenance_uncertain``; the absence of identity confirmation
  is the conservative default.

Public API
----------
Authority sentinels::

    IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY
    IDENTITY_AUTHORSHIP_BINDING_CONTRACT_SENTINEL

Policy sentinels::

    IDENTITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY
    ACTOR_FIELD_PRESENCE_IS_NOT_AUTHORITATIVE_BINDING_POLICY
    ASSERTION_MUST_NOT_CLAIM_AUTHORSHIP_VERIFIED_POLICY
    DELEGATION_MUST_NOT_CLAIM_DIRECT_AUTHORSHIP_POLICY
    PROVENANCE_ABSENCE_DEFAULTS_TO_UNCERTAIN_POLICY

Enumerations::

    IdentityBindingClass
    IdentityBindingSignalStrength

Data classes::

    IdentityBindingEvidence
    IdentityBindingVerdict

Functions::

    classify_identity_binding(evidence) -> IdentityBindingVerdict
    build_identity_binding_verdict(evidence) -> IdentityBindingVerdict
    build_baseline_identity_binding_verdict() -> IdentityBindingVerdict
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.IdentityAuthorshipActorBindingContract")

__all__ = [
    # Authority sentinels
    "IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY",
    "IDENTITY_AUTHORSHIP_BINDING_CONTRACT_SENTINEL",
    # Policy sentinels
    "IDENTITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY",
    "ACTOR_FIELD_PRESENCE_IS_NOT_AUTHORITATIVE_BINDING_POLICY",
    "ASSERTION_MUST_NOT_CLAIM_AUTHORSHIP_VERIFIED_POLICY",
    "DELEGATION_MUST_NOT_CLAIM_DIRECT_AUTHORSHIP_POLICY",
    "PROVENANCE_ABSENCE_DEFAULTS_TO_UNCERTAIN_POLICY",
    # Enumerations
    "IdentityBindingClass",
    "IdentityBindingSignalStrength",
    # Data classes
    "IdentityBindingEvidence",
    "IdentityBindingVerdict",
    # Functions
    "classify_identity_binding",
    "build_identity_binding_verdict",
    "build_baseline_identity_binding_verdict",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY: str = (
    "IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY::"
    "core.identity_authorship_actor_binding_contract::"
    "identity-authorship-actor-binding-taxonomy::"
    "formal-identity-truth-contract-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical authority for identity /
authorship / actor-binding semantics classification in Galaxy V2.

Import this sentinel to assert that a release gate, governance surface,
acceptance evaluator, or runtime truth layer is consuming a formal
identity binding classification rather than an implicit "has actor field"
flag."""

IDENTITY_AUTHORSHIP_BINDING_CONTRACT_SENTINEL: str = (
    "IDENTITY_AUTHORSHIP_BINDING_CONTRACT_SENTINEL::"
    "profile=identity-authorship-actor-binding-contract-v1::"
    "module=core.identity_authorship_actor_binding_contract"
)
"""Package sentinel for the identity / authorship / actor-binding contract."""

IDENTITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY: str = (
    "POLICY::IDENTITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_V1: "
    "Identity / authorship / actor-binding semantics MUST be treated as a "
    "first-class operational dimension by truth surfaces, readiness gates, "
    "acceptance evaluators, and governance pipelines.  Surfaces MUST NOT "
    "conflate 'actor field is present' (field existence) with 'identity is "
    "authoritatively bound' (verified binding).  Every identity-sensitive "
    "verdict MUST include an IdentityBindingVerdict that identifies the "
    "applicable class.  "
    "See: IdentityBindingClass taxonomy in "
    "core.identity_authorship_actor_binding_contract."
)
"""Policy: identity taxonomy is a first-class operational dimension."""

ACTOR_FIELD_PRESENCE_IS_NOT_AUTHORITATIVE_BINDING_POLICY: str = (
    "POLICY::ACTOR_FIELD_PRESENCE_IS_NOT_AUTHORITATIVE_BINDING_V1: "
    "The mere presence of an actor, participant, author, or source field — "
    "even if non-empty — MUST NOT be used as evidence of authoritative "
    "identity binding.  Field presence is an assertion; binding is a "
    "verified state.  Surfaces MUST NOT auto-promote 'actor_field_present=True' "
    "to identity_authoritatively_bound without independent verification "
    "evidence (identity_verified_by_authority=True and "
    "binding_confirmed=True).  "
    "See: classify_identity_binding() downgrade rules in "
    "core.identity_authorship_actor_binding_contract."
)
"""Policy: actor/source field presence must not produce authoritative binding."""

ASSERTION_MUST_NOT_CLAIM_AUTHORSHIP_VERIFIED_POLICY: str = (
    "POLICY::ASSERTION_MUST_NOT_CLAIM_AUTHORSHIP_VERIFIED_V1: "
    "When an actor, author, or source has been asserted (claimed or recorded) "
    "but has NOT been subjected to independent verification, the identity "
    "binding class MUST NOT be set to authorship_verified or higher.  An "
    "asserted identity is at most asserted_but_unverified.  'The field says "
    "author=X' is not the same as 'authorship of X has been verified'.  "
    "See: IdentityBindingClass.asserted_but_unverified in "
    "core.identity_authorship_actor_binding_contract."
)
"""Policy: bare assertion must not produce authorship_verified or higher."""

DELEGATION_MUST_NOT_CLAIM_DIRECT_AUTHORSHIP_POLICY: str = (
    "POLICY::DELEGATION_MUST_NOT_CLAIM_DIRECT_AUTHORSHIP_V1: "
    "When an action, result, or artifact was produced under a delegation or "
    "proxy arrangement, the identity binding class MUST NOT be set to "
    "identity_authoritatively_bound or authorship_verified (direct).  A "
    "delegated or proxy actor is producing the artifact on behalf of a "
    "principal; the recorded actor is the delegate/proxy, not the primary "
    "originator.  This MUST be classified as delegated_or_proxy_actor, not "
    "masked as direct verified authorship.  "
    "See: IdentityBindingClass.delegated_or_proxy_actor in "
    "core.identity_authorship_actor_binding_contract."
)
"""Policy: delegation/proxy must not produce identity_authoritatively_bound or
authorship_verified (direct)."""

PROVENANCE_ABSENCE_DEFAULTS_TO_UNCERTAIN_POLICY: str = (
    "POLICY::PROVENANCE_ABSENCE_DEFAULTS_TO_UNCERTAIN_V1: "
    "When no positive identity evidence is present — no verification by an "
    "authoritative channel, no confirmed binding, no validated authorship — "
    "the identity binding class MUST default to "
    "identity_or_provenance_uncertain.  The absence of identity evidence is "
    "NOT a signal of verified identity; it is a signal of unknown or "
    "unconfirmed identity state.  Silence is not authoritative binding.  "
    "See: IdentityBindingClass.identity_or_provenance_uncertain in "
    "core.identity_authorship_actor_binding_contract."
)
"""Policy: absence of identity evidence defaults to uncertain (fail-conservative)."""


# ---------------------------------------------------------------------------
# IdentityBindingClass
# ---------------------------------------------------------------------------


class IdentityBindingClass(str, Enum):
    """Five-class identity / authorship / actor-binding taxonomy.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.

    Ordering (from highest to lowest binding confidence):
      identity_authoritatively_bound > authorship_verified >
      asserted_but_unverified > delegated_or_proxy_actor >
      identity_or_provenance_uncertain
    """

    identity_authoritatively_bound = "identity_authoritatively_bound"
    """Actor/participant identity has been positively verified through an
    authoritative channel; binding is confirmed, not merely asserted.  The
    primary actor is the verified origin of the action, artifact, or claim.

    Requirements (all must hold):
    - identity_verified_by_authority = True
    - binding_confirmed = True
    - assertion_only = False
    - is_delegation_or_proxy = False
    - provenance_missing_or_ambiguous = False
    - identity_explicitly_uncertain = False
    """

    authorship_verified = "authorship_verified"
    """Authorship of an artifact, result, or action has been validated beyond
    mere assertion; the author claim is substantiated by independent
    verification (but not full authoritative channel binding as above).

    Requirements (all must hold):
    - authorship_validated = True
    - assertion_only = False
    - is_delegation_or_proxy = False
    - provenance_missing_or_ambiguous = False
    - identity_explicitly_uncertain = False
    - identity_verified_by_authority may be False (distinguishes from
      identity_authoritatively_bound)
    """

    asserted_but_unverified = "asserted_but_unverified"
    """An actor, author, or source has been claimed or recorded but the claim
    has not been subjected to any independent verification process.  The
    claim may be correct, but it is not confirmed.  This class requires at
    minimum that a non-empty actor/author/source assertion is present.

    Requirements:
    - actor_field_present = True  (some actor assertion exists)
    - identity_verified_by_authority = False  (no auth. verification)
    - authorship_validated = False  (no authorship validation)
    - is_delegation_or_proxy = False  (not a delegation)
    - identity_explicitly_uncertain = False  (not explicitly uncertain)
    """

    delegated_or_proxy_actor = "delegated_or_proxy_actor"
    """The action, result, or artifact was produced under a delegation or
    proxy arrangement.  The recorded actor is not the primary originator but
    an intermediary, delegate, or proxy.  This is NOT equivalent to direct
    verified authorship.  Delegation may be legitimate and documented, but
    it is a distinct binding class from direct verified identity.

    Requirements:
    - is_delegation_or_proxy = True
    - identity_explicitly_uncertain = False
    """

    identity_or_provenance_uncertain = "identity_or_provenance_uncertain"
    """Identity, authorship, or provenance is unknown, missing, ambiguous, or
    has been explicitly flagged as uncertain.  This is the fail-conservative
    default when no positive identity evidence is present.

    Requirements (any of):
    - identity_explicitly_uncertain = True
    - provenance_missing_or_ambiguous = True
    - No actor_field_present (no assertion at all)
    - No positive evidence for any higher class
    """


# Numeric rank for comparison (lower = worse)
_CLASS_RANK: Dict[str, int] = {
    IdentityBindingClass.identity_or_provenance_uncertain.value: 0,
    IdentityBindingClass.delegated_or_proxy_actor.value: 1,
    IdentityBindingClass.asserted_but_unverified.value: 2,
    IdentityBindingClass.authorship_verified.value: 3,
    IdentityBindingClass.identity_authoritatively_bound.value: 4,
}


def _worse_or_equal(a: IdentityBindingClass, b: IdentityBindingClass) -> bool:
    """Return True if class *a* is worse than or equal to class *b*."""
    return _CLASS_RANK[a.value] <= _CLASS_RANK[b.value]


# ---------------------------------------------------------------------------
# IdentityBindingSignalStrength
# ---------------------------------------------------------------------------


class IdentityBindingSignalStrength(str, Enum):
    """Describes the overall strength of the identity binding signal.

    Used to provide additional context in the IdentityBindingVerdict.
    """

    authoritative = "authoritative"
    """Identity binding is backed by an authoritative verification channel
    with confirmed binding.  The strongest possible signal."""

    validated = "validated"
    """Authorship or identity has been validated by an independent process,
    but not through a full authoritative channel."""

    asserted = "asserted"
    """Identity or authorship has been claimed/recorded but not verified.
    The signal is present but unconfirmed."""

    delegated = "delegated"
    """Identity binding is through a delegation or proxy chain.  The actor
    recorded is an intermediary, not the primary originator."""

    absent_or_uncertain = "absent_or_uncertain"
    """No usable identity signal, or the signal is explicitly uncertain or
    ambiguous.  The fail-conservative baseline."""


# ---------------------------------------------------------------------------
# IdentityBindingEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityBindingEvidence:
    """Structured evidence input for the identity binding classifier.

    All fields have safe (fail-conservative) defaults so that an absent
    signal does not silently produce an optimistic classification.

    Attributes
    ----------
    actor_field_present : bool
        True when an actor, participant, author, or source field is present
        and non-empty.  This is a *necessary but not sufficient* condition
        for any class above ``identity_or_provenance_uncertain``.  Presence
        alone MUST NOT produce ``identity_authoritatively_bound`` or
        ``authorship_verified``.

    identity_verified_by_authority : bool
        True when the actor/participant identity has been verified through
        an authoritative channel (e.g. identity provider, auth service,
        signed credential).  Required for
        ``identity_authoritatively_bound``.

    authorship_validated : bool
        True when the authorship of an artifact, result, or action has been
        independently validated (e.g. signature check, cross-reference
        verification, review confirmation).  Required for
        ``authorship_verified``.

    binding_confirmed : bool
        True when the identity binding has been positively confirmed as
        active and current (not just historical or cached).  Required for
        ``identity_authoritatively_bound``.

    is_delegation_or_proxy : bool
        True when the action, result, or artifact was produced under a
        delegation or proxy arrangement.  When True, the maximum class is
        ``delegated_or_proxy_actor`` (not ``identity_authoritatively_bound``
        or ``authorship_verified``).

    delegation_explicitly_documented : bool
        True when the delegation or proxy arrangement is formally documented
        (i.e. the delegation is structured and traceable).  Only meaningful
        when ``is_delegation_or_proxy=True``.

    assertion_only : bool
        True when the identity/authorship claim is a bare assertion with no
        verification.  When True, the maximum class is
        ``asserted_but_unverified``.

    provenance_missing_or_ambiguous : bool
        True when the provenance of the actor, author, or source is missing,
        incomplete, or ambiguous.  When True, the class MUST NOT be
        ``identity_authoritatively_bound`` or ``authorship_verified``.

    identity_explicitly_uncertain : bool
        True when the identity or provenance has been explicitly flagged as
        uncertain, unknown, or unreliable.  When True, the class MUST be
        ``identity_or_provenance_uncertain`` regardless of other signals.

    multiple_authority_sources_agree : bool
        True when two or more independent authoritative sources agree on the
        identity binding.  Provides additional confidence for
        ``identity_authoritatively_bound``.
    """

    actor_field_present: bool = False
    identity_verified_by_authority: bool = False
    authorship_validated: bool = False
    binding_confirmed: bool = False
    is_delegation_or_proxy: bool = False
    delegation_explicitly_documented: bool = False
    assertion_only: bool = False
    provenance_missing_or_ambiguous: bool = False
    identity_explicitly_uncertain: bool = False
    multiple_authority_sources_agree: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "actor_field_present": self.actor_field_present,
            "identity_verified_by_authority": self.identity_verified_by_authority,
            "authorship_validated": self.authorship_validated,
            "binding_confirmed": self.binding_confirmed,
            "is_delegation_or_proxy": self.is_delegation_or_proxy,
            "delegation_explicitly_documented": (
                self.delegation_explicitly_documented
            ),
            "assertion_only": self.assertion_only,
            "provenance_missing_or_ambiguous": self.provenance_missing_or_ambiguous,
            "identity_explicitly_uncertain": self.identity_explicitly_uncertain,
            "multiple_authority_sources_agree": (
                self.multiple_authority_sources_agree
            ),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdentityBindingEvidence":
        """Deserialise from a plain dictionary."""
        return cls(
            actor_field_present=bool(data.get("actor_field_present", False)),
            identity_verified_by_authority=bool(
                data.get("identity_verified_by_authority", False)
            ),
            authorship_validated=bool(data.get("authorship_validated", False)),
            binding_confirmed=bool(data.get("binding_confirmed", False)),
            is_delegation_or_proxy=bool(
                data.get("is_delegation_or_proxy", False)
            ),
            delegation_explicitly_documented=bool(
                data.get("delegation_explicitly_documented", False)
            ),
            assertion_only=bool(data.get("assertion_only", False)),
            provenance_missing_or_ambiguous=bool(
                data.get("provenance_missing_or_ambiguous", False)
            ),
            identity_explicitly_uncertain=bool(
                data.get("identity_explicitly_uncertain", False)
            ),
            multiple_authority_sources_agree=bool(
                data.get("multiple_authority_sources_agree", False)
            ),
        )


# ---------------------------------------------------------------------------
# IdentityBindingVerdict
# ---------------------------------------------------------------------------


@dataclass
class IdentityBindingVerdict:
    """Structured identity / authorship / actor-binding verdict.

    This is the canonical output of :func:`classify_identity_binding` and
    :func:`build_identity_binding_verdict`.  It is designed to be consumed
    by truth / acceptance / readiness / governance pipelines.

    Attributes
    ----------
    verdict_id : str
        Unique identifier for this verdict instance.
    generated_at : float
        Unix timestamp of verdict generation.
    taxonomy_sentinel : str
        Copy of :data:`IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY`.
    binding_class : IdentityBindingClass
        The formal :class:`IdentityBindingClass` verdict.
    signal_strength : IdentityBindingSignalStrength
        Derived signal strength label.
    reason : str
        Human-readable explanation of the verdict and the classification
        rule that applied.
    downgrade_reasons : List[str]
        If the verdict was downgraded from a higher class, these explain why.
        Empty list when no downgrade occurred.
    evidence : IdentityBindingEvidence
        The input evidence that produced this verdict.  Included for
        auditability.
    is_authoritatively_bound : bool
        Convenience flag — True only for
        ``identity_authoritatively_bound``.
    is_authorship_verified : bool
        Convenience flag — True only for ``authorship_verified``.
    is_asserted_unverified : bool
        Convenience flag — True only for ``asserted_but_unverified``.
    is_delegated_or_proxy : bool
        Convenience flag — True only for ``delegated_or_proxy_actor``.
    is_uncertain : bool
        Convenience flag — True only for
        ``identity_or_provenance_uncertain``.
    """

    verdict_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: float = field(default_factory=time.time)
    taxonomy_sentinel: str = field(
        default=IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY
    )
    binding_class: IdentityBindingClass = field(
        default=IdentityBindingClass.identity_or_provenance_uncertain
    )
    signal_strength: IdentityBindingSignalStrength = field(
        default=IdentityBindingSignalStrength.absent_or_uncertain
    )
    reason: str = ""
    downgrade_reasons: List[str] = field(default_factory=list)
    evidence: IdentityBindingEvidence = field(
        default_factory=IdentityBindingEvidence
    )
    is_authoritatively_bound: bool = False
    is_authorship_verified: bool = False
    is_asserted_unverified: bool = False
    is_delegated_or_proxy: bool = False
    is_uncertain: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "verdict_id": self.verdict_id,
            "generated_at": self.generated_at,
            "taxonomy_sentinel": self.taxonomy_sentinel,
            "binding_class": self.binding_class.value,
            "signal_strength": self.signal_strength.value,
            "reason": self.reason,
            "downgrade_reasons": list(self.downgrade_reasons),
            "evidence": self.evidence.to_dict(),
            "is_authoritatively_bound": self.is_authoritatively_bound,
            "is_authorship_verified": self.is_authorship_verified,
            "is_asserted_unverified": self.is_asserted_unverified,
            "is_delegated_or_proxy": self.is_delegated_or_proxy,
            "is_uncertain": self.is_uncertain,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdentityBindingVerdict":
        """Deserialise from a plain dictionary (best-effort)."""
        binding_class_raw = data.get(
            "binding_class",
            IdentityBindingClass.identity_or_provenance_uncertain.value,
        )
        try:
            binding_class = IdentityBindingClass(binding_class_raw)
        except ValueError:
            binding_class = IdentityBindingClass.identity_or_provenance_uncertain

        signal_strength_raw = data.get(
            "signal_strength",
            IdentityBindingSignalStrength.absent_or_uncertain.value,
        )
        try:
            signal_strength = IdentityBindingSignalStrength(signal_strength_raw)
        except ValueError:
            signal_strength = IdentityBindingSignalStrength.absent_or_uncertain

        evidence_raw = data.get("evidence", {})
        evidence = (
            IdentityBindingEvidence.from_dict(evidence_raw)
            if isinstance(evidence_raw, dict)
            else IdentityBindingEvidence()
        )

        return cls(
            verdict_id=str(data.get("verdict_id", str(uuid.uuid4()))),
            generated_at=float(data.get("generated_at", time.time())),
            taxonomy_sentinel=str(
                data.get(
                    "taxonomy_sentinel",
                    IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY,
                )
            ),
            binding_class=binding_class,
            signal_strength=signal_strength,
            reason=str(data.get("reason", "")),
            downgrade_reasons=list(data.get("downgrade_reasons", [])),
            evidence=evidence,
            is_authoritatively_bound=bool(
                data.get("is_authoritatively_bound", False)
            ),
            is_authorship_verified=bool(
                data.get("is_authorship_verified", False)
            ),
            is_asserted_unverified=bool(
                data.get("is_asserted_unverified", False)
            ),
            is_delegated_or_proxy=bool(data.get("is_delegated_or_proxy", False)),
            is_uncertain=bool(data.get("is_uncertain", True)),
        )


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------


def _build_verdict(
    binding_class: IdentityBindingClass,
    signal_strength: IdentityBindingSignalStrength,
    reason: str,
    downgrade_reasons: List[str],
    evidence: IdentityBindingEvidence,
) -> IdentityBindingVerdict:
    """Construct a fully-populated :class:`IdentityBindingVerdict`."""
    return IdentityBindingVerdict(
        binding_class=binding_class,
        signal_strength=signal_strength,
        reason=reason,
        downgrade_reasons=downgrade_reasons,
        evidence=evidence,
        is_authoritatively_bound=(
            binding_class
            == IdentityBindingClass.identity_authoritatively_bound
        ),
        is_authorship_verified=(
            binding_class == IdentityBindingClass.authorship_verified
        ),
        is_asserted_unverified=(
            binding_class == IdentityBindingClass.asserted_but_unverified
        ),
        is_delegated_or_proxy=(
            binding_class == IdentityBindingClass.delegated_or_proxy_actor
        ),
        is_uncertain=(
            binding_class
            == IdentityBindingClass.identity_or_provenance_uncertain
        ),
    )


def classify_identity_binding(
    evidence: IdentityBindingEvidence,
) -> IdentityBindingVerdict:
    """Classify the identity / authorship / actor-binding state from evidence.

    Applies the formal taxonomy rules and downgrade semantics defined in
    this module.  Always fail-conservative: insufficient or ambiguous
    evidence yields ``identity_or_provenance_uncertain`` rather than an
    optimistic classification.

    Parameters
    ----------
    evidence:
        The :class:`IdentityBindingEvidence` to evaluate.

    Returns
    -------
    IdentityBindingVerdict
        Structured verdict with the classified :class:`IdentityBindingClass`,
        downgrade reasons, and evidence summary.
    """
    downgrade_reasons: List[str] = []

    # ------------------------------------------------------------------
    # Rule 1: identity_explicitly_uncertain → ALWAYS uncertain
    # This is the hardest downgrade: explicit uncertainty signal beats
    # all other evidence.
    # ------------------------------------------------------------------
    if evidence.identity_explicitly_uncertain:
        downgrade_reasons.append(
            "identity_explicitly_uncertain=True: identity or provenance "
            "has been explicitly flagged as uncertain; all higher classes "
            "are prohibited regardless of other evidence."
        )
        return _build_verdict(
            IdentityBindingClass.identity_or_provenance_uncertain,
            IdentityBindingSignalStrength.absent_or_uncertain,
            "Identity explicitly uncertain: identity or provenance has been "
            "explicitly flagged as uncertain.  No higher class is defensible.",
            downgrade_reasons,
            evidence,
        )

    # ------------------------------------------------------------------
    # Rule 2: provenance_missing_or_ambiguous → at most
    #         asserted_but_unverified (prevents authorship_verified and
    #         identity_authoritatively_bound)
    # ------------------------------------------------------------------
    provenance_blocks_verified = evidence.provenance_missing_or_ambiguous
    if provenance_blocks_verified:
        downgrade_reasons.append(
            "provenance_missing_or_ambiguous=True: provenance is not "
            "established; identity_authoritatively_bound and "
            "authorship_verified are prohibited."
        )

    # ------------------------------------------------------------------
    # Rule 3: No actor field and no delegation → uncertain by default
    # ------------------------------------------------------------------
    if (
        not evidence.actor_field_present
        and not evidence.is_delegation_or_proxy
        and not evidence.identity_verified_by_authority
        and not evidence.authorship_validated
    ):
        if not downgrade_reasons:
            downgrade_reasons.append(
                "No actor_field_present, no delegation, no authority "
                "verification, no authorship validation: no positive identity "
                "evidence present."
            )
        return _build_verdict(
            IdentityBindingClass.identity_or_provenance_uncertain,
            IdentityBindingSignalStrength.absent_or_uncertain,
            "No positive identity evidence present.  Fail-conservative "
            "default: identity_or_provenance_uncertain.",
            downgrade_reasons,
            evidence,
        )

    # ------------------------------------------------------------------
    # Rule 4: identity_authoritatively_bound — requires ALL of:
    #   - identity_verified_by_authority = True
    #   - binding_confirmed = True
    #   - assertion_only = False
    #   - is_delegation_or_proxy = False
    #   - provenance_missing_or_ambiguous = False
    #   - identity_explicitly_uncertain = False (already handled above)
    # ------------------------------------------------------------------
    if (
        evidence.identity_verified_by_authority
        and evidence.binding_confirmed
        and not evidence.assertion_only
        and not evidence.is_delegation_or_proxy
        and not evidence.provenance_missing_or_ambiguous
    ):
        reason = (
            "Identity authoritatively bound: identity has been verified "
            "by an authoritative channel and binding has been confirmed; "
            "no delegation, no bare assertion, no provenance ambiguity."
        )
        if evidence.multiple_authority_sources_agree:
            reason += (
                "  Multiple authority sources agree, providing additional "
                "confidence."
            )
        return _build_verdict(
            IdentityBindingClass.identity_authoritatively_bound,
            IdentityBindingSignalStrength.authoritative,
            reason,
            downgrade_reasons,
            evidence,
        )

    # Track what prevented identity_authoritatively_bound
    if evidence.identity_verified_by_authority or evidence.binding_confirmed:
        if evidence.assertion_only:
            downgrade_reasons.append(
                "assertion_only=True: bare assertion prevents "
                "identity_authoritatively_bound."
            )
        if evidence.is_delegation_or_proxy:
            downgrade_reasons.append(
                "is_delegation_or_proxy=True: delegation/proxy prevents "
                "identity_authoritatively_bound."
            )
        if not evidence.binding_confirmed:
            downgrade_reasons.append(
                "binding_confirmed=False: binding not confirmed; "
                "identity_authoritatively_bound requires confirmed binding."
            )
        if not evidence.identity_verified_by_authority:
            downgrade_reasons.append(
                "identity_verified_by_authority=False: no authority "
                "verification; identity_authoritatively_bound requires "
                "authoritative channel verification."
            )

    # ------------------------------------------------------------------
    # Rule 5: authorship_verified — requires ALL of:
    #   - authorship_validated = True
    #   - assertion_only = False
    #   - is_delegation_or_proxy = False
    #   - provenance_missing_or_ambiguous = False
    #   - identity_explicitly_uncertain = False (already handled)
    # ------------------------------------------------------------------
    if (
        evidence.authorship_validated
        and not evidence.assertion_only
        and not evidence.is_delegation_or_proxy
        and not evidence.provenance_missing_or_ambiguous
    ):
        return _build_verdict(
            IdentityBindingClass.authorship_verified,
            IdentityBindingSignalStrength.validated,
            "Authorship verified: authorship has been independently "
            "validated; no delegation, no bare assertion, no provenance "
            "ambiguity.",
            downgrade_reasons,
            evidence,
        )

    if evidence.authorship_validated:
        if evidence.assertion_only:
            downgrade_reasons.append(
                "assertion_only=True: bare assertion prevents "
                "authorship_verified."
            )
        if evidence.is_delegation_or_proxy:
            downgrade_reasons.append(
                "is_delegation_or_proxy=True: delegation/proxy prevents "
                "authorship_verified."
            )

    # ------------------------------------------------------------------
    # Rule 6: delegated_or_proxy_actor — requires:
    #   - is_delegation_or_proxy = True
    #   - identity_explicitly_uncertain = False (already handled)
    # ------------------------------------------------------------------
    if evidence.is_delegation_or_proxy:
        doc_note = (
            "  Delegation is formally documented."
            if evidence.delegation_explicitly_documented
            else "  Delegation is present but not formally documented."
        )
        return _build_verdict(
            IdentityBindingClass.delegated_or_proxy_actor,
            IdentityBindingSignalStrength.delegated,
            "Delegated or proxy actor: the action/artifact was produced "
            "under a delegation or proxy arrangement; the recorded actor is "
            "not the primary originator.  This is NOT equivalent to direct "
            "verified authorship." + doc_note,
            downgrade_reasons,
            evidence,
        )

    # ------------------------------------------------------------------
    # Rule 7: asserted_but_unverified — requires:
    #   - actor_field_present = True
    #   - (not identity_verified_by_authority)
    #   - (not authorship_validated)
    #   - (not is_delegation_or_proxy)
    #   - identity_explicitly_uncertain = False (already handled)
    #
    # At this point we know:
    #   - not identity_authoritatively_bound (Rule 4 didn't apply)
    #   - not authorship_verified (Rule 5 didn't apply)
    #   - not delegated_or_proxy_actor (Rule 6 didn't apply)
    #   - not identity_explicitly_uncertain (Rule 1 didn't apply)
    #   - actor_field_present = True OR some positive signal exists
    # ------------------------------------------------------------------
    if evidence.actor_field_present:
        if evidence.assertion_only:
            reason = (
                "Asserted but unverified: actor/author/source has been "
                "claimed (assertion_only=True) with no independent "
                "verification.  Claim is present but unconfirmed."
            )
        else:
            reason = (
                "Asserted but unverified: actor/author/source field is "
                "present but no authoritative verification or authorship "
                "validation has been performed.  Claim is present but "
                "unconfirmed."
            )
        if evidence.provenance_missing_or_ambiguous:
            reason += (
                "  Provenance is also missing or ambiguous, which further "
                "limits confidence in the assertion."
            )
        return _build_verdict(
            IdentityBindingClass.asserted_but_unverified,
            IdentityBindingSignalStrength.asserted,
            reason,
            downgrade_reasons,
            evidence,
        )

    # ------------------------------------------------------------------
    # Rule 8: fallback — identity_or_provenance_uncertain
    # ------------------------------------------------------------------
    if not downgrade_reasons:
        downgrade_reasons.append(
            "No positive identity evidence or assertion meets the minimum "
            "threshold for any higher class."
        )
    return _build_verdict(
        IdentityBindingClass.identity_or_provenance_uncertain,
        IdentityBindingSignalStrength.absent_or_uncertain,
        "Identity or provenance uncertain: no positive evidence meets the "
        "threshold for any higher identity binding class.",
        downgrade_reasons,
        evidence,
    )


def build_identity_binding_verdict(
    evidence: Optional[IdentityBindingEvidence] = None,
) -> IdentityBindingVerdict:
    """Build an :class:`IdentityBindingVerdict` from *evidence*.

    This is the canonical classification entry-point for acceptance /
    governance / runtime truth / readiness consumers.

    Parameters
    ----------
    evidence:
        The :class:`IdentityBindingEvidence` to evaluate.  When ``None``
        (or not provided), a zero-evidence instance is used, which yields
        ``identity_or_provenance_uncertain`` per the fail-conservative
        policy.

    Returns
    -------
    IdentityBindingVerdict
        Structured verdict with the classified :class:`IdentityBindingClass`,
        downgrade reasons, and evidence summary.
    """
    if evidence is None:
        evidence = IdentityBindingEvidence()
    return classify_identity_binding(evidence)


def build_baseline_identity_binding_verdict() -> IdentityBindingVerdict:
    """Build a zero-evidence baseline verdict.

    This helper is used by acceptance and governance probes to confirm that
    the contract is wired and produces a conservative verdict
    (``identity_or_provenance_uncertain``) when no identity evidence is
    present.

    Returns
    -------
    IdentityBindingVerdict
        Baseline verdict with ``identity_or_provenance_uncertain`` class.
    """
    return build_identity_binding_verdict(evidence=None)
