#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/concurrent_mutation_conflict_contract.py
=============================================
PR-13: Multi-Writer / Concurrent Mutation / Conflict Semantics Contract.

Background
----------
The Galaxy V2 system already possesses substantial mutation, state-update,
result/evidence ingestion, recovery, and reconciliation infrastructure:
runtime truth / readiness / governance / acceptance surfaces, multiple
participant execution paths, retry / replay / deferred write / post-hoc
reconciliation semantics, and multi-device operation.  This demonstrates
that the system is not fully single-writer and is not completely oblivious
to concurrent mutation.

However, before this module the system had no formal operational contract
that distinguished *a write that succeeded without contention* from *a write
whose concurrent-mutation semantics have been formally validated*.  The
practical risk was silent optimism: "the last result was written
successfully" could be — and was — silently treated as "the system has
formally guaranteed concurrent-mutation consistency and conflict semantics".

Specifically, the following distinctions were absent:

* **conflict_free_authoritative** — the write was performed by a confirmed
  single writer with no concurrent mutations; the result is authoritative
  without any merge or reconciliation.
* **deterministically_merged** — two or more concurrent mutations produced
  a conflict; the conflict was resolved by a deterministic, idempotent merge
  function applied to all writers; the merged result is authoritative.
* **last_writer_won_non_authoritative** — a conflict occurred and was
  "resolved" by last-writer-wins; no deterministic merge was applied; the
  surviving write is NOT authoritative concurrent-mutation semantics — it is
  a non-authoritative fallback.
* **reconciliation_required** — a conflict or mutation ambiguity has been
  detected; reconciliation has been initiated but has not yet completed;
  the mutation state is partial and MUST NOT be promoted to any authoritative
  class.
* **conflict_unresolved** — a conflict is acknowledged but no resolution
  strategy (merge, last-writer-wins, or reconciliation) has been applied or
  completed; the mutation state is in an explicitly unresolved state.

Without these distinctions, ``runtime truth`` / ``acceptance`` /
``readiness`` / ``governance`` surfaces cannot distinguish "the final state
happened to land somewhere" from "the final state was reached through a
formally sound concurrent-mutation process".

This module closes that gap by establishing the **Concurrent Mutation /
Conflict Semantics Contract** — a formal classification contract that:

1. Defines five mutually exclusive and exhaustive
   :class:`MutationConflictClass` values.
2. Specifies precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient or ambiguous
   evidence always produces the lowest defensible class rather than the
   optimistic one.
4. Prohibits treating last-writer-wins, reconciliation initiation, or a
   successful write-landing as equivalent to conflict-free authoritative
   or deterministically merged.
5. Provides a :class:`MutationConflictVerdict` dataclass consumable by
   runtime truth / acceptance / readiness / governance pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  CONCURRENT MUTATION / CONFLICT SEMANTICS CONTRACT (this module,   │
    │  PR-13)                                                             │
    │                                                                     │
    │  Five mutation conflict classes (ordered by semantic strength):    │
    │    1. conflict_free_authoritative     (highest — single writer,    │
    │       no concurrent mutations detected, write is authoritative)    │
    │    2. deterministically_merged        (concurrent mutation but      │
    │       all conflicts resolved by deterministic, idempotent merge;   │
    │       merged result is authoritative)                               │
    │    3. last_writer_won_non_authoritative  (conflict "resolved" by   │
    │       last-writer-wins; NOT authoritative; concurrent semantics    │
    │       are NOT formally guaranteed)                                  │
    │    4. reconciliation_required         (conflict or ambiguity        │
    │       detected; reconciliation initiated but not yet complete;     │
    │       MUST NOT be promoted to any authoritative class)             │
    │    5. conflict_unresolved             (lowest — conflict or        │
    │       mutation ambiguity exists; no resolution applied or          │
    │       completed; fail-conservative default)                        │
    │                                                                     │
    │  Evidence dimensions evaluated:                                    │
    │    • single_writer_confirmed      — only one writer was active     │
    │    • no_concurrent_mutations      — no concurrent mutations        │
    │    • write_order_deterministic    — write ordering is deterministic│
    │    • replay_safe                  — replay/retry is idempotent     │
    │    • deterministic_merge_applied  — deterministic merge was used   │
    │    • merge_function_idempotent    — merge fn is idempotent         │
    │    • all_conflicts_resolved       — all conflicts resolved         │
    │    • last_writer_wins_applied     — last-writer-wins was used      │
    │    • concurrent_writers_detected  — multiple concurrent writers    │
    │    • duplicate_write_detected     — duplicate write detected       │
    │    • out_of_order_write_detected  — out-of-order write detected    │
    │    • reconciliation_initiated     — reconciliation started         │
    │    • reconciliation_complete      — reconciliation complete        │
    │    • conflict_acknowledged        — a conflict was acknowledged    │
    │    • conflict_resolution_absent   — no resolution applied          │
    │    • mutation_uncertainty         — mutation state is uncertain    │
    │    • explicit_conflict_unresolved — explicitly flagged unresolved  │
    │                                                                     │
    │  Downgrade semantics:                                              │
    │    • explicit_conflict_unresolved → ALWAYS conflict_unresolved    │
    │    • conflict_acknowledged AND conflict_resolution_absent →        │
    │      ALWAYS conflict_unresolved                                    │
    │    • last_writer_wins_applied → NEVER conflict_free_authoritative │
    │      or deterministically_merged; at most                          │
    │      last_writer_won_non_authoritative                             │
    │    • reconciliation_initiated AND NOT reconciliation_complete →   │
    │      ALWAYS reconciliation_required                                │
    │    • concurrent_writers_detected or duplicate_write_detected or   │
    │      out_of_order_write_detected → NEVER conflict_free_authoritative│
    │      unless all_conflicts_resolved AND write_order_deterministic  │
    │      (can be elevated to deterministically_merged)                │
    │    • mutation_uncertainty → NEVER conflict_free_authoritative      │
    │    • no positive evidence → conflict_unresolved (fail-conservative)│
    │                                                                     │
    │  Produces:                                                         │
    │    • MutationConflictVerdict  (structured output)                  │
    │                                                                     │
    │  Consumed by:                                                      │
    │    • system_final_acceptance_verdict                               │
    │      (concurrent_mutation_conflict dimension)                      │
    │    • runtime truth / acceptance / readiness / governance surfaces  │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class (``conflict_unresolved``) rather than the optimistic one.
3. **No optimistic promotion** — last-writer-wins, reconciliation initiation,
   and a successful write-landing are explicitly excluded from being promoted
   to ``conflict_free_authoritative`` or ``deterministically_merged``.
4. **Taxonomy boundary enforcement** — "last write succeeded" does NOT imply
   "conflict-free authoritative"; "reconciliation started" does NOT imply
   "conflicts resolved"; "merge ran" does NOT imply "merge was deterministic
   and idempotent".
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Critical boundary: what counts as conflict_free_authoritative vs what does not
-------------------------------------------------------------------------------
- **Last-writer-wins** — does NOT constitute conflict_free_authoritative or
  deterministically_merged; it is at best last_writer_won_non_authoritative.
- **Reconciliation in progress** — does NOT constitute any authoritative
  class; reconciliation_required MUST be assigned until reconciliation is
  complete.
- **Duplicate write** — does NOT constitute conflict_free_authoritative
  unless the write is confirmed idempotent / replay-safe and write ordering
  is deterministic; otherwise the class MUST be downgraded.
- **Out-of-order write** — does NOT constitute conflict_free_authoritative
  unless write ordering has been confirmed deterministic and all conflicts
  are resolved.
- **No evidence** — cannot be treated as conflict_free_authoritative; the
  absence of mutation semantics confirmation is the conservative default
  (conflict_unresolved).

Public API
----------
Authority sentinels::

    CONCURRENT_MUTATION_CONFLICT_CONTRACT_AUTHORITY
    CONCURRENT_MUTATION_CONFLICT_CONTRACT_PR13_SENTINEL

Policy sentinels::

    MUTATION_CONFLICT_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY
    LAST_WRITER_WINS_MUST_NOT_CLAIM_AUTHORITATIVE_POLICY
    RECONCILIATION_INCOMPLETE_BLOCKS_AUTHORITATIVE_MUTATION_POLICY
    DUPLICATE_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY
    OUT_OF_ORDER_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY
    MUTATION_ABSENCE_DEFAULTS_TO_CONFLICT_UNRESOLVED_POLICY
    WRITE_SUCCESS_MUST_NOT_IMPLY_CONCURRENT_SEMANTICS_POLICY

Enumerations::

    MutationConflictClass
    WriterConcurrencyMode

Data classes::

    MutationConflictEvidence
    MutationConflictVerdict

Functions::

    classify_mutation_conflict(evidence) -> MutationConflictVerdict
    build_mutation_conflict_verdict(evidence) -> MutationConflictVerdict
    build_baseline_mutation_conflict_verdict() -> MutationConflictVerdict
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ConcurrentMutationConflictContract")

__all__ = [
    # Authority sentinels
    "CONCURRENT_MUTATION_CONFLICT_CONTRACT_AUTHORITY",
    "CONCURRENT_MUTATION_CONFLICT_CONTRACT_PR13_SENTINEL",
    # Policy sentinels
    "MUTATION_CONFLICT_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY",
    "LAST_WRITER_WINS_MUST_NOT_CLAIM_AUTHORITATIVE_POLICY",
    "RECONCILIATION_INCOMPLETE_BLOCKS_AUTHORITATIVE_MUTATION_POLICY",
    "DUPLICATE_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY",
    "OUT_OF_ORDER_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY",
    "MUTATION_ABSENCE_DEFAULTS_TO_CONFLICT_UNRESOLVED_POLICY",
    "WRITE_SUCCESS_MUST_NOT_IMPLY_CONCURRENT_SEMANTICS_POLICY",
    # Enumerations
    "MutationConflictClass",
    "WriterConcurrencyMode",
    # Data classes
    "MutationConflictEvidence",
    "MutationConflictVerdict",
    # Functions
    "classify_mutation_conflict",
    "build_mutation_conflict_verdict",
    "build_baseline_mutation_conflict_verdict",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CONCURRENT_MUTATION_CONFLICT_CONTRACT_AUTHORITY: str = (
    "CONCURRENT_MUTATION_CONFLICT_CONTRACT_AUTHORITY::"
    "core.concurrent_mutation_conflict_contract::PR13::"
    "multi-writer-concurrent-mutation-conflict-taxonomy::"
    "formal-mutation-conflict-contract-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical authority for multi-writer /
concurrent mutation / conflict semantics classification in Galaxy V2.

Import this sentinel to assert that a release gate, governance surface,
acceptance evaluator, or runtime truth layer is consuming a formal mutation
conflict classification rather than an implicit "write succeeded" flag."""

CONCURRENT_MUTATION_CONFLICT_CONTRACT_PR13_SENTINEL: str = (
    "CONCURRENT_MUTATION_CONFLICT_CONTRACT_PR13_SENTINEL::"
    "package=PR13::profile=concurrent-mutation-conflict-contract-v1::"
    "module=core.concurrent_mutation_conflict_contract"
)
"""Package sentinel for PR-13 concurrent mutation / conflict contract."""

MUTATION_CONFLICT_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY: str = (
    "POLICY::MUTATION_CONFLICT_TAXONOMY_IS_FIRST_CLASS_DIMENSION_V1: "
    "Multi-writer / concurrent mutation / conflict semantics MUST be treated "
    "as a first-class operational dimension by truth surfaces, readiness gates, "
    "acceptance evaluators, and governance pipelines.  Surfaces MUST NOT "
    "conflate 'the last write landed successfully' (write-success) with "
    "'concurrent mutation semantics are formally sound and authoritative' "
    "(conflict-free authoritative or deterministically merged).  Every "
    "mutation verdict MUST include a MutationConflictVerdict that identifies "
    "the applicable class.  "
    "See: MutationConflictClass taxonomy in "
    "core.concurrent_mutation_conflict_contract (PR-13)."
)
"""Policy: concurrent mutation conflict taxonomy is a first-class dimension."""

LAST_WRITER_WINS_MUST_NOT_CLAIM_AUTHORITATIVE_POLICY: str = (
    "POLICY::LAST_WRITER_WINS_MUST_NOT_CLAIM_AUTHORITATIVE_V1: "
    "When the mutation outcome was produced by last-writer-wins (the last "
    "write timestamp determined the surviving value without a deterministic "
    "merge function), the mutation class MUST NOT be set to "
    "conflict_free_authoritative or deterministically_merged.  "
    "Last-writer-wins is a non-authoritative fallback; it MUST be classified "
    "as last_writer_won_non_authoritative at best.  'The last write survived' "
    "is not the same as 'concurrent mutation semantics are formally sound'.  "
    "See: MutationConflictClass.last_writer_won_non_authoritative in "
    "core.concurrent_mutation_conflict_contract (PR-13)."
)
"""Policy: last-writer-wins must not produce an authoritative classification."""

RECONCILIATION_INCOMPLETE_BLOCKS_AUTHORITATIVE_MUTATION_POLICY: str = (
    "POLICY::RECONCILIATION_INCOMPLETE_BLOCKS_AUTHORITATIVE_MUTATION_V1: "
    "When reconciliation has been initiated but has not yet completed, the "
    "mutation class MUST be at most reconciliation_required.  An incomplete "
    "reconciliation means the mutation state is partial; the class MUST NOT "
    "be promoted to conflict_free_authoritative, deterministically_merged, or "
    "last_writer_won_non_authoritative.  Reconciliation initiation does not "
    "constitute conflict resolution.  "
    "See: MutationConflictClass.reconciliation_required in "
    "core.concurrent_mutation_conflict_contract (PR-13)."
)
"""Policy: incomplete reconciliation blocks any authoritative mutation class."""

DUPLICATE_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY: str = (
    "POLICY::DUPLICATE_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_V1: "
    "When a duplicate write has been detected (the same mutation was applied "
    "more than once, e.g. due to retry, replay, or at-least-once delivery), "
    "the mutation class MUST NOT be set to conflict_free_authoritative unless "
    "the write operation is confirmed replay-safe (idempotent) AND write "
    "ordering is confirmed deterministic.  A duplicate write without these "
    "guarantees is at best a mutation ambiguity and MUST be classified "
    "conservatively.  "
    "See: duplicate_write_detected and replay_safe flags in "
    "classify_mutation_conflict() (PR-13)."
)
"""Policy: duplicate writes must not produce conflict_free_authoritative."""

OUT_OF_ORDER_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY: str = (
    "POLICY::OUT_OF_ORDER_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_V1: "
    "When an out-of-order write has been detected (a mutation arrived with a "
    "sequence or timestamp inconsistent with the expected order), the mutation "
    "class MUST NOT be set to conflict_free_authoritative unless write ordering "
    "is confirmed deterministic and all resulting conflicts have been resolved.  "
    "Out-of-order writes without deterministic ordering and conflict resolution "
    "MUST be classified conservatively.  "
    "See: out_of_order_write_detected and write_order_deterministic flags in "
    "classify_mutation_conflict() (PR-13)."
)
"""Policy: out-of-order writes must not produce conflict_free_authoritative."""

MUTATION_ABSENCE_DEFAULTS_TO_CONFLICT_UNRESOLVED_POLICY: str = (
    "POLICY::MUTATION_ABSENCE_DEFAULTS_TO_CONFLICT_UNRESOLVED_V1: "
    "When no positive mutation conflict evidence is present — no confirmation "
    "that the write was single-writer, no deterministic merge, no "
    "reconciliation completion — the mutation class MUST default to "
    "conflict_unresolved.  The absence of mutation semantics evidence is NOT "
    "a signal of conflict_free_authoritative; it is a signal of unknown or "
    "worst-case mutation state.  Silence is not concurrency safety.  "
    "See: MutationConflictClass.conflict_unresolved in "
    "core.concurrent_mutation_conflict_contract (PR-13)."
)
"""Policy: absence of mutation evidence defaults to conflict_unresolved."""

WRITE_SUCCESS_MUST_NOT_IMPLY_CONCURRENT_SEMANTICS_POLICY: str = (
    "POLICY::WRITE_SUCCESS_MUST_NOT_IMPLY_CONCURRENT_SEMANTICS_V1: "
    "A write operation completing successfully (the state was persisted, the "
    "record was updated, or the artifact was committed) MUST NOT be interpreted "
    "as evidence that concurrent mutation semantics are formally sound.  Write "
    "success is a necessary but not sufficient condition for any authoritative "
    "concurrent mutation classification.  The system MUST NOT auto-promote a "
    "successful write to conflict_free_authoritative or deterministically_merged "
    "without explicit evidence of single-writer operation or deterministic merge "
    "application.  "
    "See: MutationConflictClass taxonomy in "
    "core.concurrent_mutation_conflict_contract (PR-13)."
)
"""Policy: write success must not imply authoritative concurrent semantics."""


# ---------------------------------------------------------------------------
# MutationConflictClass
# ---------------------------------------------------------------------------


class MutationConflictClass(str, Enum):
    """Five-class mutation conflict taxonomy for concurrent mutation semantics.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.

    Ordering (from strongest to weakest semantic guarantee):
      conflict_free_authoritative > deterministically_merged >
      last_writer_won_non_authoritative > reconciliation_required >
      conflict_unresolved
    """

    conflict_free_authoritative = "conflict_free_authoritative"
    """A single writer was confirmed active; no concurrent mutations were
    detected; the write result is authoritative without any merge or
    reconciliation.  This is the only class that represents genuinely
    sound single-writer concurrent-mutation semantics.

    Requirements (all must hold):
    - single_writer_confirmed = True
    - no_concurrent_mutations = True
    - write_order_deterministic = True
    - replay_safe = True (writes are idempotent / replay-safe)
    - last_writer_wins_applied = False
    - concurrent_writers_detected = False
    - duplicate_write_detected = False (OR replay_safe = True)
    - out_of_order_write_detected = False (OR write_order_deterministic = True)
    - reconciliation_initiated = False OR reconciliation_complete = True
    - conflict_acknowledged = False
    - conflict_resolution_absent = False
    - mutation_uncertainty = False
    - explicit_conflict_unresolved = False
    """

    deterministically_merged = "deterministically_merged"
    """Two or more concurrent mutations produced a conflict that was resolved
    by a deterministic, idempotent merge function applied to all writers.
    The merged result is authoritative.  This is NOT conflict_free because
    concurrent writes occurred; but the resolution is formally sound.

    Requirements (all must hold):
    - deterministic_merge_applied = True
    - merge_function_idempotent = True
    - all_conflicts_resolved = True
    - last_writer_wins_applied = False
    - reconciliation_initiated = False OR reconciliation_complete = True
    - conflict_acknowledged = False OR (deterministic_merge_applied = True
      AND all_conflicts_resolved = True)
    - explicit_conflict_unresolved = False
    """

    last_writer_won_non_authoritative = "last_writer_won_non_authoritative"
    """A conflict occurred and was "resolved" by last-writer-wins (the most
    recent write timestamp determined the surviving value).  No deterministic
    merge was applied.  The surviving write is present but its concurrent-
    mutation semantics are NOT formally guaranteed.  Consumers MUST NOT treat
    this as equivalent to conflict_free_authoritative.

    Requirements:
    - last_writer_wins_applied = True
    - reconciliation_initiated = False (no pending reconciliation)
    - explicit_conflict_unresolved = False
    """

    reconciliation_required = "reconciliation_required"
    """A conflict or mutation ambiguity has been detected and reconciliation
    has been initiated but has not yet completed.  The mutation state is
    partial and MUST NOT be promoted to any authoritative class until
    reconciliation is complete.

    Requirements:
    - reconciliation_initiated = True
    - reconciliation_complete = False
    - explicit_conflict_unresolved = False
    """

    conflict_unresolved = "conflict_unresolved"
    """A conflict exists (or the mutation state is ambiguous) and no
    resolution strategy (merge, last-writer-wins, or reconciliation) has
    been applied or completed.  This is the fail-conservative default when
    evidence of sound mutation semantics is absent.

    Requirements (any of):
    - explicit_conflict_unresolved = True
    - conflict_acknowledged = True AND conflict_resolution_absent = True
    - No positive mutation evidence at all (fail-conservative default)
    """


# Numeric rank for comparison (lower = worse)
_CLASS_RANK: Dict[str, int] = {
    MutationConflictClass.conflict_unresolved.value: 0,
    MutationConflictClass.reconciliation_required.value: 1,
    MutationConflictClass.last_writer_won_non_authoritative.value: 2,
    MutationConflictClass.deterministically_merged.value: 3,
    MutationConflictClass.conflict_free_authoritative.value: 4,
}


def _worse_or_equal(a: MutationConflictClass, b: MutationConflictClass) -> bool:
    """Return True if class *a* is worse than or equal to class *b*."""
    return _CLASS_RANK[a.value] <= _CLASS_RANK[b.value]


# ---------------------------------------------------------------------------
# WriterConcurrencyMode
# ---------------------------------------------------------------------------


class WriterConcurrencyMode(str, Enum):
    """Describes the concurrency mode observed during the mutation.

    Used to provide additional context in the MutationConflictVerdict.
    """

    single_writer = "single_writer"
    """Only one writer was active during the mutation.  No concurrency."""

    serialised = "serialised"
    """Multiple potential writers exist but writes are serialised (e.g.
    through a lock, queue, or leader-election); effective single-writer."""

    concurrent_detected = "concurrent_detected"
    """Multiple concurrent writers were active simultaneously; conflict
    resolution is required."""

    replay_or_retry = "replay_or_retry"
    """Write arrived via retry, replay, or at-least-once delivery; the
    effective writer count may be > 1 due to resubmission."""

    out_of_order = "out_of_order"
    """Writes arrived out of the expected order; ordering guarantees are
    absent and must be resolved before an authoritative class can be
    assigned."""

    unknown = "unknown"
    """Concurrency mode is unknown.  Must be treated conservatively."""


# ---------------------------------------------------------------------------
# MutationConflictEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MutationConflictEvidence:
    """Structured evidence input for the mutation conflict classifier.

    All fields have safe (fail-conservative) defaults so that an absent
    signal does not silently produce an optimistic classification.

    Attributes
    ----------
    single_writer_confirmed:
        True only when it has been positively confirmed that only one writer
        was active during the mutation window.  Defaults to False.
    no_concurrent_mutations:
        True only when it has been confirmed that no concurrent mutations
        occurred on the same logical state / artifact / record.  Defaults to
        False (conservative).
    write_order_deterministic:
        True when write ordering is confirmed deterministic (e.g. through
        a sequence number, vector clock, or leader-election coordination).
        Defaults to False (conservative).
    replay_safe:
        True when the write operation is confirmed idempotent / replay-safe
        (applying the same write multiple times yields the same result).
        Defaults to False (conservative).
    deterministic_merge_applied:
        True when a deterministic merge function was explicitly applied to
        resolve concurrent writes.  Defaults to False.
    merge_function_idempotent:
        True when the applied merge function is confirmed idempotent
        (applying it multiple times yields the same result).  Defaults to
        False.  MUST be False if deterministic_merge_applied is False.
    all_conflicts_resolved:
        True when every detected conflict has been resolved (either by
        deterministic merge or by another explicit resolution strategy).
        Defaults to False (conservative).
    last_writer_wins_applied:
        True when last-writer-wins was used as the conflict resolution
        strategy.  Defaults to False.  When True, ALWAYS prevents
        conflict_free_authoritative and deterministically_merged.
    concurrent_writers_detected:
        True when multiple concurrent writers were detected on the same
        logical state.  Defaults to False.  When True, prevents
        conflict_free_authoritative unless all_conflicts_resolved and
        write_order_deterministic are both True.
    duplicate_write_detected:
        True when a duplicate write was detected (the same mutation applied
        more than once).  Defaults to False.  When True, prevents
        conflict_free_authoritative unless replay_safe is True.
    out_of_order_write_detected:
        True when an out-of-order write was detected.  Defaults to False.
        When True, prevents conflict_free_authoritative unless
        write_order_deterministic is True.
    reconciliation_initiated:
        True when reconciliation has been started to address a conflict or
        mutation ambiguity.  Defaults to False.
    reconciliation_complete:
        True when reconciliation has completed successfully.  Defaults to
        False.  MUST NOT be True if reconciliation_initiated is False.
    conflict_acknowledged:
        True when a conflict has been explicitly acknowledged (logged,
        recorded, or signalled).  Defaults to False.  When True together
        with conflict_resolution_absent=True, ALWAYS produces
        conflict_unresolved.
    conflict_resolution_absent:
        True when no conflict resolution strategy has been applied despite
        a conflict being present.  Defaults to False.  When True together
        with conflict_acknowledged=True, ALWAYS produces conflict_unresolved.
    mutation_uncertainty:
        True when the mutation state is uncertain (signals are absent,
        contradictory, or incomplete).  Defaults to False.  When True,
        prevents conflict_free_authoritative.
    explicit_conflict_unresolved:
        True when the mutation has been explicitly flagged as unresolved.
        Defaults to False.  When True, ALWAYS produces conflict_unresolved
        regardless of other fields.
    concurrency_mode:
        The observed writer concurrency mode for contextual reporting.
        Defaults to WriterConcurrencyMode.unknown (conservative).
    participant_id:
        Optional participant or surface identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    extra_context:
        Optional dict of additional context signals.  Not used in
        classification logic but included in the verdict for auditability.
    """

    single_writer_confirmed: bool = False
    no_concurrent_mutations: bool = False
    write_order_deterministic: bool = False
    replay_safe: bool = False
    deterministic_merge_applied: bool = False
    merge_function_idempotent: bool = False
    all_conflicts_resolved: bool = False
    last_writer_wins_applied: bool = False
    concurrent_writers_detected: bool = False
    duplicate_write_detected: bool = False
    out_of_order_write_detected: bool = False
    reconciliation_initiated: bool = False
    reconciliation_complete: bool = False
    conflict_acknowledged: bool = False
    conflict_resolution_absent: bool = False
    mutation_uncertainty: bool = False
    explicit_conflict_unresolved: bool = False
    concurrency_mode: WriterConcurrencyMode = WriterConcurrencyMode.unknown
    participant_id: Optional[str] = None
    trace_id: Optional[str] = None
    extra_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "single_writer_confirmed": self.single_writer_confirmed,
            "no_concurrent_mutations": self.no_concurrent_mutations,
            "write_order_deterministic": self.write_order_deterministic,
            "replay_safe": self.replay_safe,
            "deterministic_merge_applied": self.deterministic_merge_applied,
            "merge_function_idempotent": self.merge_function_idempotent,
            "all_conflicts_resolved": self.all_conflicts_resolved,
            "last_writer_wins_applied": self.last_writer_wins_applied,
            "concurrent_writers_detected": self.concurrent_writers_detected,
            "duplicate_write_detected": self.duplicate_write_detected,
            "out_of_order_write_detected": self.out_of_order_write_detected,
            "reconciliation_initiated": self.reconciliation_initiated,
            "reconciliation_complete": self.reconciliation_complete,
            "conflict_acknowledged": self.conflict_acknowledged,
            "conflict_resolution_absent": self.conflict_resolution_absent,
            "mutation_uncertainty": self.mutation_uncertainty,
            "explicit_conflict_unresolved": self.explicit_conflict_unresolved,
            "concurrency_mode": self.concurrency_mode.value,
            "participant_id": self.participant_id,
            "trace_id": self.trace_id,
            "extra_context": dict(self.extra_context),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MutationConflictEvidence":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        mode_raw = data.get("concurrency_mode", "unknown")
        try:
            concurrency_mode = WriterConcurrencyMode(mode_raw)
        except ValueError:
            concurrency_mode = WriterConcurrencyMode.unknown
        return cls(
            single_writer_confirmed=bool(
                data.get("single_writer_confirmed", False)
            ),
            no_concurrent_mutations=bool(
                data.get("no_concurrent_mutations", False)
            ),
            write_order_deterministic=bool(
                data.get("write_order_deterministic", False)
            ),
            replay_safe=bool(data.get("replay_safe", False)),
            deterministic_merge_applied=bool(
                data.get("deterministic_merge_applied", False)
            ),
            merge_function_idempotent=bool(
                data.get("merge_function_idempotent", False)
            ),
            all_conflicts_resolved=bool(
                data.get("all_conflicts_resolved", False)
            ),
            last_writer_wins_applied=bool(
                data.get("last_writer_wins_applied", False)
            ),
            concurrent_writers_detected=bool(
                data.get("concurrent_writers_detected", False)
            ),
            duplicate_write_detected=bool(
                data.get("duplicate_write_detected", False)
            ),
            out_of_order_write_detected=bool(
                data.get("out_of_order_write_detected", False)
            ),
            reconciliation_initiated=bool(
                data.get("reconciliation_initiated", False)
            ),
            reconciliation_complete=bool(
                data.get("reconciliation_complete", False)
            ),
            conflict_acknowledged=bool(
                data.get("conflict_acknowledged", False)
            ),
            conflict_resolution_absent=bool(
                data.get("conflict_resolution_absent", False)
            ),
            mutation_uncertainty=bool(data.get("mutation_uncertainty", False)),
            explicit_conflict_unresolved=bool(
                data.get("explicit_conflict_unresolved", False)
            ),
            concurrency_mode=concurrency_mode,
            participant_id=data.get("participant_id"),
            trace_id=data.get("trace_id"),
            extra_context=dict(data.get("extra_context", {})),
        )


# ---------------------------------------------------------------------------
# MutationConflictVerdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MutationConflictVerdict:
    """Formal mutation conflict verdict for a system surface.

    Produced by :func:`classify_mutation_conflict`.

    Attributes
    ----------
    mutation_class:
        The classified :class:`MutationConflictClass` for this context.
    rationale:
        Human-readable explanation of why this class was assigned.  Always
        non-empty.
    downgrade_reasons:
        List of specific reasons that caused the class to be downgraded from
        an optimistic baseline.  Empty when no downgrade occurred.
    is_conflict_free_authoritative:
        True only for ``conflict_free_authoritative`` class.  MUST NOT be
        set for any other class.
    is_deterministically_merged:
        True for ``deterministically_merged``.  Indicates a conflict was
        resolved via a deterministic merge.
    is_last_writer_won:
        True for ``last_writer_won_non_authoritative``.  Indicates a
        last-writer-wins fallback was applied; not authoritative.
    is_reconciliation_required:
        True for ``reconciliation_required``.  Indicates reconciliation
        was initiated but not yet complete.
    is_conflict_unresolved:
        True for ``conflict_unresolved``.  Indicates no sound resolution
        has been applied.
    participant_id:
        Identifier of the surface or participant this verdict applies to.
    evidence_present:
        Whether any positive mutation conflict evidence was available
        during classification.
    classified_at:
        Unix timestamp (float) when this verdict was produced.
    verdict_id:
        Unique identifier for this verdict instance.
    trace_id:
        Optional distributed-trace identifier.
    """

    mutation_class: MutationConflictClass
    rationale: str
    downgrade_reasons: List[str] = field(default_factory=list)
    is_conflict_free_authoritative: bool = False
    is_deterministically_merged: bool = False
    is_last_writer_won: bool = False
    is_reconciliation_required: bool = False
    is_conflict_unresolved: bool = False
    participant_id: Optional[str] = None
    evidence_present: bool = False
    classified_at: float = field(default_factory=time.time)
    verdict_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "mutation_class": self.mutation_class.value,
            "rationale": self.rationale,
            "downgrade_reasons": list(self.downgrade_reasons),
            "is_conflict_free_authoritative": self.is_conflict_free_authoritative,
            "is_deterministically_merged": self.is_deterministically_merged,
            "is_last_writer_won": self.is_last_writer_won,
            "is_reconciliation_required": self.is_reconciliation_required,
            "is_conflict_unresolved": self.is_conflict_unresolved,
            "participant_id": self.participant_id,
            "evidence_present": self.evidence_present,
            "classified_at": self.classified_at,
            "verdict_id": self.verdict_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MutationConflictVerdict":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        class_raw = data.get("mutation_class", "conflict_unresolved")
        try:
            m_class = MutationConflictClass(class_raw)
        except ValueError:
            m_class = MutationConflictClass.conflict_unresolved
        return cls(
            mutation_class=m_class,
            rationale=data.get("rationale", ""),
            downgrade_reasons=list(data.get("downgrade_reasons", [])),
            is_conflict_free_authoritative=bool(
                data.get("is_conflict_free_authoritative", False)
            ),
            is_deterministically_merged=bool(
                data.get("is_deterministically_merged", False)
            ),
            is_last_writer_won=bool(data.get("is_last_writer_won", False)),
            is_reconciliation_required=bool(
                data.get("is_reconciliation_required", False)
            ),
            is_conflict_unresolved=bool(data.get("is_conflict_unresolved", False)),
            participant_id=data.get("participant_id"),
            evidence_present=bool(data.get("evidence_present", False)),
            classified_at=float(data.get("classified_at", time.time())),
            verdict_id=data.get("verdict_id", uuid.uuid4().hex[:12]),
            trace_id=data.get("trace_id"),
        )


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------


def _classify(evidence: MutationConflictEvidence) -> MutationConflictVerdict:
    """Internal classification implementation.

    Priority order:
    1. explicit_conflict_unresolved=True → conflict_unresolved (always)
    2. conflict_acknowledged=True AND conflict_resolution_absent=True
       → conflict_unresolved (always)
    3. reconciliation_initiated=True AND reconciliation_complete=False
       → reconciliation_required
    4. last_writer_wins_applied=True → last_writer_won_non_authoritative
    5. deterministic_merge_applied=True AND merge_function_idempotent=True
       AND all_conflicts_resolved=True → deterministically_merged
    6. All conflict-free conditions met → conflict_free_authoritative
    7. All other cases → conflict_unresolved (fail-conservative)
    """
    downgrade_reasons: List[str] = []

    # Determine whether any positive evidence exists
    positive_signals = [
        evidence.single_writer_confirmed,
        evidence.no_concurrent_mutations,
        evidence.write_order_deterministic,
        evidence.replay_safe,
        evidence.deterministic_merge_applied,
        evidence.merge_function_idempotent,
        evidence.all_conflicts_resolved,
    ]
    negative_signals = [
        evidence.last_writer_wins_applied,
        evidence.concurrent_writers_detected,
        evidence.duplicate_write_detected,
        evidence.out_of_order_write_detected,
        evidence.reconciliation_initiated,
        evidence.conflict_acknowledged,
        evidence.conflict_resolution_absent,
        evidence.mutation_uncertainty,
        evidence.explicit_conflict_unresolved,
    ]
    evidence_present = any(positive_signals) or any(negative_signals)

    # Rule 1: explicit_conflict_unresolved always wins
    if evidence.explicit_conflict_unresolved:
        return MutationConflictVerdict(
            mutation_class=MutationConflictClass.conflict_unresolved,
            rationale=(
                "explicit_conflict_unresolved=True: mutation has been "
                "explicitly flagged as unresolved.  No authoritative "
                "concurrent-mutation semantics can be claimed."
            ),
            downgrade_reasons=["explicit_conflict_unresolved=True"],
            is_conflict_unresolved=True,
            participant_id=evidence.participant_id,
            evidence_present=evidence_present,
            trace_id=evidence.trace_id,
        )

    # Rule 2: acknowledged conflict with no resolution applied
    if evidence.conflict_acknowledged and evidence.conflict_resolution_absent:
        downgrade_reasons.append(
            "conflict_acknowledged=True AND conflict_resolution_absent=True: "
            "a conflict is known but no resolution strategy has been applied."
        )
        return MutationConflictVerdict(
            mutation_class=MutationConflictClass.conflict_unresolved,
            rationale=(
                "conflict_acknowledged=True AND conflict_resolution_absent=True: "
                "a conflict exists but has not been resolved.  The mutation "
                "state is explicitly unresolved."
            ),
            downgrade_reasons=downgrade_reasons,
            is_conflict_unresolved=True,
            participant_id=evidence.participant_id,
            evidence_present=evidence_present,
            trace_id=evidence.trace_id,
        )

    # Rule 3: reconciliation initiated but not complete
    if evidence.reconciliation_initiated and not evidence.reconciliation_complete:
        downgrade_reasons.append(
            "reconciliation_initiated=True AND reconciliation_complete=False: "
            "reconciliation has been started but is not yet complete; "
            "mutation state is partial."
        )
        return MutationConflictVerdict(
            mutation_class=MutationConflictClass.reconciliation_required,
            rationale=(
                "reconciliation_initiated=True AND reconciliation_complete=False: "
                "reconciliation is in progress.  The mutation class MUST NOT "
                "be promoted to any authoritative class until reconciliation "
                "completes."
            ),
            downgrade_reasons=downgrade_reasons,
            is_reconciliation_required=True,
            participant_id=evidence.participant_id,
            evidence_present=evidence_present,
            trace_id=evidence.trace_id,
        )

    # Rule 4: last-writer-wins → non-authoritative
    if evidence.last_writer_wins_applied:
        downgrade_reasons.append(
            "last_writer_wins_applied=True: last-writer-wins was used as "
            "conflict resolution; this is a non-authoritative fallback."
        )
        return MutationConflictVerdict(
            mutation_class=MutationConflictClass.last_writer_won_non_authoritative,
            rationale=(
                "last_writer_wins_applied=True: a conflict was resolved by "
                "last-writer-wins.  The surviving write is present but "
                "concurrent-mutation semantics are NOT formally guaranteed.  "
                "This is NOT conflict_free_authoritative or "
                "deterministically_merged."
            ),
            downgrade_reasons=downgrade_reasons,
            is_last_writer_won=True,
            participant_id=evidence.participant_id,
            evidence_present=evidence_present,
            trace_id=evidence.trace_id,
        )

    # Rule 5: deterministic merge
    if (
        evidence.deterministic_merge_applied
        and evidence.merge_function_idempotent
        and evidence.all_conflicts_resolved
    ):
        return MutationConflictVerdict(
            mutation_class=MutationConflictClass.deterministically_merged,
            rationale=(
                "deterministic_merge_applied=True, merge_function_idempotent=True, "
                "all_conflicts_resolved=True: concurrent mutations were resolved "
                "by a deterministic idempotent merge.  The merged result is "
                "authoritative."
            ),
            downgrade_reasons=[],
            is_deterministically_merged=True,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # Collect downgrade reasons for Rule 6 check
    if evidence.concurrent_writers_detected:
        downgrade_reasons.append(
            "concurrent_writers_detected=True: multiple concurrent writers "
            "were active; single-writer cannot be claimed."
        )
    if evidence.duplicate_write_detected and not evidence.replay_safe:
        downgrade_reasons.append(
            "duplicate_write_detected=True AND replay_safe=False: a duplicate "
            "write was detected without idempotency confirmation."
        )
    if evidence.out_of_order_write_detected and not evidence.write_order_deterministic:
        downgrade_reasons.append(
            "out_of_order_write_detected=True AND write_order_deterministic=False: "
            "an out-of-order write was detected without deterministic ordering."
        )
    if evidence.mutation_uncertainty:
        downgrade_reasons.append(
            "mutation_uncertainty=True: mutation state is uncertain."
        )

    # Rule 6: all conflict-free conditions met → conflict_free_authoritative
    dup_ok = not evidence.duplicate_write_detected or evidence.replay_safe
    oor_ok = not evidence.out_of_order_write_detected or evidence.write_order_deterministic
    recon_ok = (
        not evidence.reconciliation_initiated
        or evidence.reconciliation_complete
    )
    all_conflict_free = (
        evidence.single_writer_confirmed
        and evidence.no_concurrent_mutations
        and evidence.write_order_deterministic
        and evidence.replay_safe
        and not evidence.last_writer_wins_applied
        and not evidence.concurrent_writers_detected
        and dup_ok
        and oor_ok
        and recon_ok
        and not evidence.conflict_acknowledged
        and not evidence.mutation_uncertainty
        and not evidence.explicit_conflict_unresolved
    )

    if all_conflict_free and not downgrade_reasons:
        return MutationConflictVerdict(
            mutation_class=MutationConflictClass.conflict_free_authoritative,
            rationale=(
                "All conflict-free conditions met: single writer confirmed, "
                "no concurrent mutations, write order is deterministic, writes "
                "are replay-safe, no last-writer-wins applied, no conflicts "
                "acknowledged, no mutation uncertainty."
            ),
            downgrade_reasons=[],
            is_conflict_free_authoritative=True,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # Rule 7: all other cases → conflict_unresolved (fail-conservative)
    if not downgrade_reasons:
        downgrade_reasons.append(
            "No positive mutation conflict evidence is present (fail-conservative "
            "default)."
        )
    return MutationConflictVerdict(
        mutation_class=MutationConflictClass.conflict_unresolved,
        rationale=(
            "Insufficient evidence to classify as any authoritative concurrent "
            "mutation class.  Defaulting to conflict_unresolved "
            "(fail-conservative baseline)."
        ),
        downgrade_reasons=downgrade_reasons,
        is_conflict_unresolved=True,
        participant_id=evidence.participant_id,
        evidence_present=evidence_present,
        trace_id=evidence.trace_id,
    )


def classify_mutation_conflict(
    evidence: MutationConflictEvidence,
) -> MutationConflictVerdict:
    """Classify the concurrent mutation / conflict class for a mutation surface.

    This is the canonical entry point for multi-writer / concurrent mutation /
    conflict semantics classification.  It applies the fail-conservative
    downgrade rules defined in the module docstring and enforced by the
    policy sentinels.

    Classification logic (evaluated in priority order):
    1. ``explicit_conflict_unresolved=True`` → **conflict_unresolved** (always)
    2. ``conflict_acknowledged=True`` AND ``conflict_resolution_absent=True``
       → **conflict_unresolved** (always)
    3. ``reconciliation_initiated=True`` AND ``reconciliation_complete=False``
       → **reconciliation_required**
    4. ``last_writer_wins_applied=True`` → **last_writer_won_non_authoritative**
    5. ``deterministic_merge_applied=True`` AND ``merge_function_idempotent=True``
       AND ``all_conflicts_resolved=True`` → **deterministically_merged**
    6. All single-writer conflict-free conditions met
       → **conflict_free_authoritative**
    7. All other cases → **conflict_unresolved** (fail-conservative)

    Parameters
    ----------
    evidence:
        A :class:`MutationConflictEvidence` instance populated with the
        mutation conflict signals for the surface being evaluated.

    Returns
    -------
    MutationConflictVerdict
        Formal verdict with mutation class, rationale, downgrade reasons,
        boolean flag accessors, and metadata.
    """
    verdict = _classify(evidence)
    logger.debug(
        "classify_mutation_conflict → %s reasons=%d participant=%r",
        verdict.mutation_class.value,
        len(verdict.downgrade_reasons),
        evidence.participant_id,
    )
    return verdict


def build_mutation_conflict_verdict(
    evidence: MutationConflictEvidence,
) -> MutationConflictVerdict:
    """Build a :class:`MutationConflictVerdict` from the given evidence.

    This is a convenience alias for :func:`classify_mutation_conflict`.
    Useful in contexts that prefer the ``build_*_verdict`` naming convention
    used by other contract modules.
    """
    return classify_mutation_conflict(evidence)


def build_baseline_mutation_conflict_verdict() -> MutationConflictVerdict:
    """Build a conservative baseline (zero-evidence) verdict.

    Returns a :class:`MutationConflictVerdict` with all evidence fields at
    their conservative defaults (all False).  The result MUST be
    ``conflict_unresolved`` — this confirms the fail-conservative contract
    is correctly enforced.

    This function is used by acceptance / readiness / governance probes to
    verify that the contract module is available and correctly wired without
    requiring live mutation evidence.
    """
    return classify_mutation_conflict(MutationConflictEvidence())
