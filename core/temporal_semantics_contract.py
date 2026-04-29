#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/temporal_semantics_contract.py
=====================================
PR-14: Time Semantics / Freshness / Staleness / Deadline Truth Contract.

Background
----------
The Galaxy V2 system already possesses substantial temporal infrastructure:
timestamps on evidence, lifecycle, telemetry, and result surfaces; timeout
and retry/replay windows; heartbeat presence monitoring; age-based
invalidation; delayed ingestion paths; and clock-based decision gates.
This demonstrates that the system is not temporally oblivious.

However, before this module the system had no formal contract that
distinguished *having a timestamp* from *temporal truth being authoritative,
fresh, or meaningfully classified*.  The practical risk was silent optimism:
the presence of any recent timestamp, heartbeat signal, or ingestion event
could be interpreted — or programmatically misclassified — as evidence that
the system's temporal state is healthy, fresh, and authoritative.

Specifically, the following distinctions were absent:

* **timely_authoritative** vs **fresh_with_bounded_lag** — is the data
  delivered within the authoritative time window with verified clock
  integrity and no deadline miss, or is the data recent but sourced with
  a measured, bounded lag that prevents a fully-authoritative temporal
  claim?
* **stale_but_usable** — the data exceeds the freshness window but is
  within the staleness tolerance bound; still usable for non-real-time
  decisions but NOT current.
* **deadline_missed_or_timed_out** — a formal deadline was set and has
  been exceeded, OR the ingestion/heartbeat window timed out; no
  valid temporal claim can be made from the available data.
* **temporally_unreliable** — clock uncertainty is unacceptably high,
  heartbeat is absent, timestamp is missing or contradictory, or the
  operator has explicitly declared temporal integrity unavailable.

Without these distinctions, ``runtime truth`` / ``acceptance`` /
``readiness`` / ``governance`` surfaces cannot distinguish "we have a
timestamp" from "we have authoritative, timely temporal evidence".

This module closes that gap by establishing the **Temporal Semantics
Contract** — a formal classification contract that:

1. Defines five mutually exclusive and exhaustive
   :class:`TemporalClass` values.
2. Specifies precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: stale, lagged, deadline-
   missed, or clock-uncertain evidence always produces the lowest
   defensible class rather than the optimistic one.
4. Prohibits treating timestamp presence, recent heartbeat receipt, or
   delayed ingestion as equivalent to timely authoritative temporal truth.
5. Provides a :class:`TemporalVerdict` dataclass consumable by runtime
   truth / acceptance / readiness / governance pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  TEMPORAL SEMANTICS CONTRACT  (this module — PR-14)                 │
    │                                                                     │
    │  Five temporal classes (strictly ordered by temporal authority):   │
    │    1. timely_authoritative      (highest — data delivered within   │
    │       the authoritative time window, clock integrity verified,     │
    │       no deadline miss, no significant lag, no heartbeat absence,  │
    │       and no clock uncertainty)                                    │
    │    2. fresh_with_bounded_lag    (data is recent, within the        │
    │       freshness window, and the lag is measured and bounded, but   │
    │       at least one authoritative condition is absent: delivery     │
    │       exceeded the tight authoritative window, clock uncertainty   │
    │       is present but within tolerance, or heartbeat was received   │
    │       with a non-trivial delay)                                    │
    │    3. stale_but_usable          (data exceeds the freshness window │
    │       but is within the staleness tolerance bound; lag is known    │
    │       and bounded; data is usable for non-real-time or post-hoc   │
    │       decisions but NOT current; deadline has not yet been missed) │
    │    4. deadline_missed_or_timed_out  (a formal deadline was set and │
    │       has been exceeded, OR the ingestion/heartbeat window timed   │
    │       out; data is expired for any authoritative temporal claim;   │
    │       replay/retry windows may be open but current data is gone)  │
    │    5. temporally_unreliable     (lowest — clock uncertainty is     │
    │       unacceptably high, heartbeat is absent, timestamp is         │
    │       missing or contradictory, or operator has explicitly marked  │
    │       temporal integrity unavailable; default fail-conservative    │
    │       baseline when no positive temporal evidence)                 │
    │                                                                     │
    │  Evidence dimensions evaluated:                                    │
    │    • timestamp_present         — a timestamp exists for the event  │
    │    • timestamp_authoritative   — timestamp is sourced from an      │
    │      authoritative clock (NTP-synced, trusted source)             │
    │    • within_authoritative_window — data arrived within the tight   │
    │      authoritative delivery window (e.g. ≤T_auth)                │
    │    • within_freshness_window   — data age is ≤ freshness_window   │
    │      (broader than authoritative window)                          │
    │    • within_staleness_tolerance — data age is ≤ staleness bound;  │
    │      stale but not yet expired                                     │
    │    • deadline_set              — a formal deadline was declared    │
    │    • deadline_met              — deadline was set AND met          │
    │    • heartbeat_present         — at least one heartbeat was        │
    │      received in the expected window                               │
    │    • heartbeat_within_window   — heartbeat arrived within the      │
    │      expected heartbeat interval                                   │
    │    • lag_measured              — the delivery lag is measured      │
    │      and bounded (even if large)                                   │
    │    • lag_within_bound          — the measured lag is within the    │
    │      operator-specified lag tolerance                              │
    │    • clock_uncertainty_acceptable — clock skew / drift is within  │
    │      acceptable bounds for a temporal truth claim                 │
    │    • explicit_temporally_unreliable — operator or system has       │
    │      explicitly declared temporal integrity unavailable            │
    │                                                                     │
    │  Downgrade semantics:                                              │
    │    • no timestamp at all → ALWAYS temporally_unreliable            │
    │    • timestamp present but not authoritative →                     │
    │      NEVER timely_authoritative or fresh_with_bounded_lag          │
    │    • deadline set and missed → ALWAYS deadline_missed_or_timed_out │
    │    • heartbeat absent when required →                              │
    │      NEVER timely_authoritative                                    │
    │    • clock uncertainty unacceptable → NEVER timely_authoritative  │
    │    • lag present but unmeasured →                                  │
    │      NEVER fresh_with_bounded_lag or higher                        │
    │    • explicit_temporally_unreliable → ALWAYS temporally_unreliable │
    │                                                                     │
    │  Produces:                                                         │
    │    • TemporalVerdict  (structured output)                          │
    │                                                                     │
    │  Consumed by:                                                      │
    │    • system_final_acceptance_verdict (temporal_semantics dimension)│
    │    • runtime truth / acceptance / readiness / governance surfaces  │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous temporal evidence yields
   the lowest defensible class (``temporally_unreliable``) rather than
   the optimistic one.
3. **No optimistic promotion** — timestamp presence, recent heartbeat
   receipt, delayed ingestion, and non-authoritative clock sources are
   explicitly excluded from being promoted to ``timely_authoritative``.
4. **Taxonomy boundary enforcement** — timestamp presence, authoritative
   timing, lag bounds, deadline compliance, heartbeat health, and clock
   integrity are treated as *separate* evidence dimensions.  Presence of
   any one does not imply the others.
5. **Projection-only** — this module evaluates evidence fed to it; it
   never mutates external state.

Critical boundaries
-------------------
- **Timestamp present** — does NOT constitute timely_authoritative; the
  timestamp may exist but be sourced from an untrusted clock, arrived
  with unknown lag, or be older than any freshness window.
- **Heartbeat received** — does NOT constitute timely_authoritative if
  the heartbeat arrived outside the expected window or if clock
  uncertainty is unacceptable.
- **Delayed ingestion** — data arrived via deferred / replay / batch
  path; even if the timestamp is "recent", the delivery path is not
  timely authoritative.
- **Lag measured** — knowing the lag exists is not the same as the lag
  being within the authoritative window.
- **Deadline not yet missed** — does NOT imply timely_authoritative;
  the data must still pass all freshness and lag conditions.

Public API
----------
Authority sentinels::

    TEMPORAL_SEMANTICS_CONTRACT_AUTHORITY
    TEMPORAL_SEMANTICS_CONTRACT_PR14_SENTINEL

Policy sentinels::

    TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_POLICY
    LAG_UNMEASURED_BLOCKS_FRESH_BOUNDED_LAG_POLICY
    DEADLINE_MISS_FORCES_TIMED_OUT_CLASS_POLICY
    HEARTBEAT_ABSENT_BLOCKS_TIMELY_AUTHORITATIVE_POLICY
    CLOCK_UNCERTAINTY_BLOCKS_TIMELY_AUTHORITATIVE_POLICY
    TEMPORAL_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY
    EXPLICIT_UNRELIABLE_ALWAYS_FORCES_LOWEST_CLASS_POLICY

Enumerations::

    TemporalClass

Data classes::

    TemporalEvidence
    TemporalVerdict

Functions::

    classify_temporal_semantics(evidence) -> TemporalVerdict
    build_temporal_verdict(evidence) -> TemporalVerdict
    build_baseline_temporal_verdict() -> TemporalVerdict
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TemporalSemanticsContract")

__all__ = [
    # Authority sentinels
    "TEMPORAL_SEMANTICS_CONTRACT_AUTHORITY",
    "TEMPORAL_SEMANTICS_CONTRACT_PR14_SENTINEL",
    # Policy sentinels
    "TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_POLICY",
    "LAG_UNMEASURED_BLOCKS_FRESH_BOUNDED_LAG_POLICY",
    "DEADLINE_MISS_FORCES_TIMED_OUT_CLASS_POLICY",
    "HEARTBEAT_ABSENT_BLOCKS_TIMELY_AUTHORITATIVE_POLICY",
    "CLOCK_UNCERTAINTY_BLOCKS_TIMELY_AUTHORITATIVE_POLICY",
    "TEMPORAL_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY",
    "EXPLICIT_UNRELIABLE_ALWAYS_FORCES_LOWEST_CLASS_POLICY",
    # Enumerations
    "TemporalClass",
    # Data classes
    "TemporalEvidence",
    "TemporalVerdict",
    # Functions
    "classify_temporal_semantics",
    "build_temporal_verdict",
    "build_baseline_temporal_verdict",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

TEMPORAL_SEMANTICS_CONTRACT_AUTHORITY: str = (
    "TEMPORAL_SEMANTICS_CONTRACT_AUTHORITY::"
    "core.temporal_semantics_contract::PR14::"
    "temporal-semantics-freshness-staleness-deadline-taxonomy::"
    "formal-temporal-contract-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical authority for temporal semantics
classification in Galaxy V2.

Import this sentinel to assert that a release gate, governance surface,
acceptance evaluator, or runtime truth layer is consuming a formal temporal
classification rather than an implicit "timestamp present" flag."""

TEMPORAL_SEMANTICS_CONTRACT_PR14_SENTINEL: str = (
    "TEMPORAL_SEMANTICS_CONTRACT_PR14_SENTINEL::"
    "package=PR14::profile=temporal-semantics-contract-v1::"
    "module=core.temporal_semantics_contract"
)
"""Package sentinel for PR-14 temporal semantics contract."""

TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_POLICY: str = (
    "POLICY::TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_V1: "
    "The existence of a timestamp, a recently-received heartbeat, or any "
    "time-related signal does NOT constitute timely authoritative temporal "
    "truth.  The timestamp must be sourced from an authoritative clock, "
    "the data must have arrived within the authoritative delivery window, "
    "lag must be within tolerance, and no deadline may have been missed.  "
    "Surfaces MUST NOT report 'temporally authoritative' merely because a "
    "timestamp field is populated or a recent signal was observed.  "
    "See: TemporalClass taxonomy in "
    "core.temporal_semantics_contract (PR-14)."
)
"""Policy: timestamp presence alone does not constitute temporal authority."""

LAG_UNMEASURED_BLOCKS_FRESH_BOUNDED_LAG_POLICY: str = (
    "POLICY::LAG_UNMEASURED_BLOCKS_FRESH_BOUNDED_LAG_V1: "
    "fresh_with_bounded_lag requires that the delivery lag is BOTH measured "
    "(lag_measured=True) AND within the operator-specified lag tolerance "
    "(lag_within_bound=True).  When lag is unknown or unmeasured "
    "(lag_measured=False), the class MUST NOT be promoted to "
    "fresh_with_bounded_lag; it MUST remain at stale_but_usable or lower.  "
    "An unmeasured lag implies unbounded delay which cannot support a fresh "
    "temporal claim.  "
    "See: TemporalClass.fresh_with_bounded_lag in "
    "core.temporal_semantics_contract (PR-14)."
)
"""Policy: unmeasured lag must not be promoted to fresh_with_bounded_lag."""

DEADLINE_MISS_FORCES_TIMED_OUT_CLASS_POLICY: str = (
    "POLICY::DEADLINE_MISS_FORCES_TIMED_OUT_CLASS_V1: "
    "When a formal deadline has been declared (deadline_set=True) and that "
    "deadline has been missed (deadline_met=False), the temporal class MUST "
    "be deadline_missed_or_timed_out regardless of other conditions.  "
    "A deadline miss cannot be overridden by freshness, lag bounds, or "
    "heartbeat presence.  Similarly, when a heartbeat or ingestion window "
    "has timed out and no valid data remains, the class MUST be "
    "deadline_missed_or_timed_out.  "
    "See: TemporalClass.deadline_missed_or_timed_out in "
    "core.temporal_semantics_contract (PR-14)."
)
"""Policy: deadline miss forces deadline_missed_or_timed_out class."""

HEARTBEAT_ABSENT_BLOCKS_TIMELY_AUTHORITATIVE_POLICY: str = (
    "POLICY::HEARTBEAT_ABSENT_BLOCKS_TIMELY_AUTHORITATIVE_V1: "
    "When the evidence context requires heartbeat presence "
    "(heartbeat_required=True) and the heartbeat is absent "
    "(heartbeat_present=False), the temporal class MUST NOT be "
    "timely_authoritative.  A missing required heartbeat indicates that "
    "the source may be unresponsive, partitioned, or in an error state.  "
    "The class MUST be downgraded to fresh_with_bounded_lag at most, and "
    "further to temporally_unreliable if no other positive evidence exists.  "
    "See: TemporalClass.timely_authoritative requirements in "
    "core.temporal_semantics_contract (PR-14)."
)
"""Policy: absent required heartbeat blocks timely_authoritative class."""

CLOCK_UNCERTAINTY_BLOCKS_TIMELY_AUTHORITATIVE_POLICY: str = (
    "POLICY::CLOCK_UNCERTAINTY_BLOCKS_TIMELY_AUTHORITATIVE_V1: "
    "When clock uncertainty is unacceptable (clock_uncertainty_acceptable=False), "
    "the temporal class MUST NOT be timely_authoritative.  High clock skew "
    "or drift renders any 'timely' claim meaningless: the system cannot "
    "verify that the reported delivery time is actually within the "
    "authoritative window.  The class MUST be downgraded to at most "
    "fresh_with_bounded_lag if freshness and lag conditions hold, or further "
    "downgraded if they do not.  "
    "See: TemporalClass.timely_authoritative requirements in "
    "core.temporal_semantics_contract (PR-14)."
)
"""Policy: unacceptable clock uncertainty blocks timely_authoritative class."""

TEMPORAL_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY: str = (
    "POLICY::TEMPORAL_ABSENCE_DEFAULTS_TO_UNRELIABLE_V1: "
    "When no timestamp is present (timestamp_present=False) or no positive "
    "temporal evidence exists at all, the temporal class MUST default to "
    "temporally_unreliable.  The absence of temporal evidence is NOT a "
    "signal of temporal health; it is a signal of unknown / worst-case "
    "temporal state.  Silence is not timeliness.  "
    "See: TemporalClass.temporally_unreliable in "
    "core.temporal_semantics_contract (PR-14)."
)
"""Policy: absence of temporal evidence defaults to temporally_unreliable."""

EXPLICIT_UNRELIABLE_ALWAYS_FORCES_LOWEST_CLASS_POLICY: str = (
    "POLICY::EXPLICIT_UNRELIABLE_ALWAYS_FORCES_LOWEST_CLASS_V1: "
    "When the operator or system has explicitly declared temporal integrity "
    "unavailable (explicit_temporally_unreliable=True), the class MUST be "
    "temporally_unreliable regardless of any other evidence.  An explicit "
    "unreliability declaration cannot be overridden by timestamps, "
    "heartbeats, or freshness signals.  "
    "See: TemporalClass.temporally_unreliable in "
    "core.temporal_semantics_contract (PR-14)."
)
"""Policy: explicit temporal unreliability always forces the lowest class."""


# ---------------------------------------------------------------------------
# TemporalClass
# ---------------------------------------------------------------------------


class TemporalClass(str, Enum):
    """Five-class taxonomy for time semantics / freshness / staleness /
    deadline truth.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.

    Ordering (from most authoritative to least):
      timely_authoritative > fresh_with_bounded_lag > stale_but_usable >
      deadline_missed_or_timed_out > temporally_unreliable
    """

    timely_authoritative = "timely_authoritative"
    """Data is delivered within the authoritative time window, the clock
    source is verified as authoritative, the lag is within tolerance, no
    deadline has been missed, heartbeat (if required) is present and within
    window, and clock uncertainty is acceptable.  This is the only class
    that represents genuine timely, authoritative temporal truth.

    Requirements (ALL must hold):
    - timestamp_present = True
    - timestamp_authoritative = True  (authoritative clock source)
    - within_authoritative_window = True  (arrived within tight window)
    - within_freshness_window = True
    - clock_uncertainty_acceptable = True
    - lag_measured = True
    - lag_within_bound = True
    - deadline_set = False  OR  (deadline_set = True AND deadline_met = True)
    - heartbeat_present = True  OR  heartbeat_required = False
    - heartbeat_within_window = True  OR  heartbeat_required = False
    - explicit_temporally_unreliable = False

    NOT satisfied when:
    - timestamp_present = False (no timestamp at all)
    - timestamp_authoritative = False (non-authoritative clock)
    - within_authoritative_window = False (arrived late)
    - clock_uncertainty_acceptable = False (clock drift/skew too high)
    - heartbeat_present = False AND heartbeat_required = True
    - deadline_set = True AND deadline_met = False
    - explicit_temporally_unreliable = True
    """

    fresh_with_bounded_lag = "fresh_with_bounded_lag"
    """Data is recent and within the freshness window.  The lag is measured
    and within the operator-specified lag tolerance bound.  However, at
    least one condition for timely_authoritative is absent: the data did
    not arrive within the tight authoritative window, or clock uncertainty
    is present (but within tolerable bounds), or heartbeat was received
    with a non-trivial delay, or the timestamp clock source is not
    authoritative.  The data is timely in a broad sense but NOT
    timely_authoritative.

    Requirements:
    - timestamp_present = True
    - within_freshness_window = True  (data age ≤ freshness window)
    - lag_measured = True
    - lag_within_bound = True
    - deadline_set = False  OR  (deadline_set = True AND deadline_met = True)
    - explicit_temporally_unreliable = False
    - NOT all timely_authoritative conditions satisfied
      (i.e., at least one of: within_authoritative_window = False,
      timestamp_authoritative = False, clock_uncertainty_acceptable = False,
      heartbeat_within_window = False while heartbeat_required = True)

    NOT satisfied when:
    - timestamp_present = False
    - within_freshness_window = False (data is stale)
    - lag_measured = False (lag is unknown — cannot bound it)
    - lag_within_bound = False (lag exceeds tolerance)
    - deadline_set = True AND deadline_met = False
    - explicit_temporally_unreliable = True
    """

    stale_but_usable = "stale_but_usable"
    """Data exceeds the freshness window but is within the staleness
    tolerance bound.  The lag is known and bounded.  The data is valid
    for non-real-time or post-hoc analysis but NOT current.  No deadline
    has been missed yet.  The data may be used where "good enough old
    data" is acceptable, but cannot support any timely or fresh claim.

    Requirements:
    - timestamp_present = True
    - within_freshness_window = False  (data is stale)
    - within_staleness_tolerance = True  (stale but within tolerance)
    - lag_measured = True
    - deadline_set = False  OR  (deadline_set = True AND deadline_met = True)
    - explicit_temporally_unreliable = False

    NOT satisfied when:
    - timestamp_present = False
    - within_staleness_tolerance = False (data has exceeded even stale bounds)
    - deadline_set = True AND deadline_met = False (→ deadline_missed_or_timed_out)
    - explicit_temporally_unreliable = True
    """

    deadline_missed_or_timed_out = "deadline_missed_or_timed_out"
    """A formal deadline was declared and has been exceeded, OR the
    ingestion / heartbeat / delivery window has timed out.  The data is
    expired for any authoritative temporal claim.  Replay or retry windows
    may be open, but the current data cannot be treated as temporally
    valid.  This class is also assigned when the data exceeds even the
    staleness tolerance bound (implicitly expired).

    Requirements (any of):
    - deadline_set = True AND deadline_met = False
    - within_staleness_tolerance = False AND timestamp_present = True
      (data exists but is beyond all tolerance bounds)

    NOT satisfied when:
    - No deadline was set AND data is within staleness tolerance
    - explicit_temporally_unreliable = True
      (→ ALWAYS temporally_unreliable instead)
    """

    temporally_unreliable = "temporally_unreliable"
    """The lowest class.  Assigned when:
    - timestamp_present = False  (no timestamp at all), OR
    - explicit_temporally_unreliable = True  (operator declared unreliable), OR
    - clock_uncertainty_acceptable = False AND no other positive evidence
      is sufficient to make any temporal claim, OR
    - heartbeat is absent AND required AND no bounded-lag data exists, OR
    - any other condition prevents a defensible temporal class from
      being assigned.

    This is the default fail-conservative baseline when no positive temporal
    evidence is available.

    Requirements (any of):
    - timestamp_present = False
    - explicit_temporally_unreliable = True
    - No sufficient combination of other dimensions to assign any higher class

    Invariant: this class MUST be the default when all evidence dimensions
    are at their conservative (False) defaults.
    """

    @classmethod
    def from_string(cls, value: str) -> "TemporalClass":
        """Return the member matching *value*, defaulting to
        ``temporally_unreliable`` on unknown input."""
        if not isinstance(value, str):
            return cls.temporally_unreliable
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.temporally_unreliable

    @classmethod
    def rank(cls, member: "TemporalClass") -> int:
        """Return a numeric rank (higher = more authoritative).

        Ordering:
          temporally_unreliable          = 0
          deadline_missed_or_timed_out   = 1
          stale_but_usable               = 2
          fresh_with_bounded_lag         = 3
          timely_authoritative           = 4
        """
        _ranks = {
            cls.temporally_unreliable: 0,
            cls.deadline_missed_or_timed_out: 1,
            cls.stale_but_usable: 2,
            cls.fresh_with_bounded_lag: 3,
            cls.timely_authoritative: 4,
        }
        return _ranks.get(member, 0)


# ---------------------------------------------------------------------------
# TemporalEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporalEvidence:
    """Evidence dimensions fed to :func:`classify_temporal_semantics`.

    All boolean fields default to False (conservative).  Callers MUST
    only set a field to True when they have genuine, verified evidence for
    that condition.

    Attributes
    ----------
    timestamp_present:
        True when a timestamp exists for the event or data item.
        Defaults to False (conservative).
    timestamp_authoritative:
        True when the timestamp is sourced from an authoritative,
        trusted clock (e.g. NTP-synced, GPS-disciplined).  Requires
        timestamp_present = True to be meaningful.  Defaults to False.
    within_authoritative_window:
        True when the data arrived within the tight authoritative
        delivery window (e.g. ≤T_auth for real-time delivery).
        Defaults to False (conservative).
    within_freshness_window:
        True when the data age is within the operator-specified
        freshness window (broader than the authoritative window).
        Defaults to False (conservative).
    within_staleness_tolerance:
        True when the data is stale (outside freshness window) but
        still within the operator-specified staleness tolerance bound.
        Defaults to False (conservative).
    deadline_set:
        True when a formal temporal deadline has been declared for
        this data or operation.  Defaults to False.
    deadline_met:
        True when deadline_set = True AND the deadline has been met.
        Meaningless when deadline_set = False.  Defaults to False.
    heartbeat_required:
        True when the evidence context requires that a heartbeat be
        present to support a timely claim.  Defaults to False.
    heartbeat_present:
        True when at least one heartbeat was received in the expected
        monitoring window.  Defaults to False (conservative).
    heartbeat_within_window:
        True when the heartbeat arrived within the expected heartbeat
        interval (not just present but on-time).  Defaults to False.
    lag_measured:
        True when the delivery lag is measured and bounded (even if
        the lag is large).  Defaults to False (conservative).
    lag_within_bound:
        True when the measured lag is within the operator-specified
        lag tolerance.  Meaningless when lag_measured = False.
        Defaults to False (conservative).
    clock_uncertainty_acceptable:
        True when clock skew / drift is within acceptable bounds
        for a temporal truth claim.  Defaults to False (conservative).
    explicit_temporally_unreliable:
        True when the operator or system has explicitly declared that
        temporal integrity is unavailable (e.g. known clock failure,
        timestamp corruption, deliberate time isolation).  When True,
        ALWAYS forces temporally_unreliable regardless of other fields.
        Defaults to False.
    participant_id:
        Optional identifier of the participant or surface being
        evaluated.  Used for traceability in verdicts.
    trace_id:
        Optional trace / correlation identifier.  Propagated into
        the verdict for log correlation.
    """

    timestamp_present: bool = False
    timestamp_authoritative: bool = False
    within_authoritative_window: bool = False
    within_freshness_window: bool = False
    within_staleness_tolerance: bool = False
    deadline_set: bool = False
    deadline_met: bool = False
    heartbeat_required: bool = False
    heartbeat_present: bool = False
    heartbeat_within_window: bool = False
    lag_measured: bool = False
    lag_within_bound: bool = False
    clock_uncertainty_acceptable: bool = False
    explicit_temporally_unreliable: bool = False
    participant_id: Optional[str] = None
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "timestamp_present": self.timestamp_present,
            "timestamp_authoritative": self.timestamp_authoritative,
            "within_authoritative_window": self.within_authoritative_window,
            "within_freshness_window": self.within_freshness_window,
            "within_staleness_tolerance": self.within_staleness_tolerance,
            "deadline_set": self.deadline_set,
            "deadline_met": self.deadline_met,
            "heartbeat_required": self.heartbeat_required,
            "heartbeat_present": self.heartbeat_present,
            "heartbeat_within_window": self.heartbeat_within_window,
            "lag_measured": self.lag_measured,
            "lag_within_bound": self.lag_within_bound,
            "clock_uncertainty_acceptable": self.clock_uncertainty_acceptable,
            "explicit_temporally_unreliable": self.explicit_temporally_unreliable,
            "participant_id": self.participant_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalEvidence":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            timestamp_present=bool(data.get("timestamp_present", False)),
            timestamp_authoritative=bool(data.get("timestamp_authoritative", False)),
            within_authoritative_window=bool(
                data.get("within_authoritative_window", False)
            ),
            within_freshness_window=bool(data.get("within_freshness_window", False)),
            within_staleness_tolerance=bool(
                data.get("within_staleness_tolerance", False)
            ),
            deadline_set=bool(data.get("deadline_set", False)),
            deadline_met=bool(data.get("deadline_met", False)),
            heartbeat_required=bool(data.get("heartbeat_required", False)),
            heartbeat_present=bool(data.get("heartbeat_present", False)),
            heartbeat_within_window=bool(data.get("heartbeat_within_window", False)),
            lag_measured=bool(data.get("lag_measured", False)),
            lag_within_bound=bool(data.get("lag_within_bound", False)),
            clock_uncertainty_acceptable=bool(
                data.get("clock_uncertainty_acceptable", False)
            ),
            explicit_temporally_unreliable=bool(
                data.get("explicit_temporally_unreliable", False)
            ),
            participant_id=data.get("participant_id"),
            trace_id=data.get("trace_id"),
        )


# ---------------------------------------------------------------------------
# TemporalVerdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporalVerdict:
    """Formal temporal semantics verdict for a system surface.

    Produced by :func:`classify_temporal_semantics`.

    Attributes
    ----------
    temporal_class:
        The classified :class:`TemporalClass` for this context.
    rationale:
        Human-readable explanation of why this class was assigned.
        Always non-empty.
    downgrade_reasons:
        List of specific reasons that caused the class to be downgraded
        from an optimistic baseline.  Empty when no downgrade occurred.
    is_timely_authoritative:
        True only for ``timely_authoritative`` class.  MUST NOT be set
        for any other class.
    is_fresh:
        True for ``timely_authoritative`` and ``fresh_with_bounded_lag``.
        Indicates data is within the freshness window.
    is_stale_but_usable:
        True for ``stale_but_usable``.  Indicates data is stale but
        within staleness tolerance.
    is_deadline_missed:
        True for ``deadline_missed_or_timed_out``.  Indicates a deadline
        was set and missed, or the delivery window timed out.
    is_temporally_unreliable:
        True for ``temporally_unreliable``.  Indicates temporal truth
        cannot be established.
    participant_id:
        Propagated from the evidence.
    evidence_present:
        True when at least a timestamp was present in the evidence.
    trace_id:
        Propagated from the evidence for log correlation.
    verdict_id:
        Auto-generated UUID for this verdict instance.
    evaluated_at:
        Unix timestamp (float) when the verdict was produced.
    """

    temporal_class: TemporalClass
    rationale: str
    downgrade_reasons: List[str]
    is_timely_authoritative: bool
    is_fresh: bool
    is_stale_but_usable: bool
    is_deadline_missed: bool
    is_temporally_unreliable: bool
    participant_id: Optional[str] = None
    evidence_present: bool = False
    trace_id: Optional[str] = None
    verdict_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    evaluated_at: float = field(default_factory=time.time)

    # Invariant checks -------------------------------------------------

    def __post_init__(self) -> None:
        # Exactly one of the five class flags must be True
        active_flags = sum([
            self.is_timely_authoritative,
            self.is_fresh and not self.is_timely_authoritative,
            self.is_stale_but_usable,
            self.is_deadline_missed,
            self.is_temporally_unreliable,
        ])
        # Allow (is_fresh=True, is_timely_authoritative=True) as a special case
        # Both flags are True for timely_authoritative, but exactly one
        # "primary" flag should be true.
        primary_flags = sum([
            self.is_timely_authoritative,
            self.is_stale_but_usable,
            self.is_deadline_missed,
            self.is_temporally_unreliable,
            # fresh-only (not timely_authoritative)
            (self.is_fresh and not self.is_timely_authoritative),
        ])
        if primary_flags < 1:
            raise ValueError(
                "TemporalVerdict: at least one class flag must be True."
            )

        # timely_authoritative must also set is_fresh
        if self.is_timely_authoritative and not self.is_fresh:
            raise ValueError(
                "TemporalVerdict: is_timely_authoritative=True requires "
                "is_fresh=True."
            )

        # is_temporally_unreliable blocks all other positive flags
        if self.is_temporally_unreliable and (
            self.is_timely_authoritative
            or self.is_fresh
            or self.is_stale_but_usable
            or self.is_deadline_missed
        ):
            raise ValueError(
                "TemporalVerdict: is_temporally_unreliable=True must not "
                "be combined with any positive temporal flag."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "temporal_class": self.temporal_class.value,
            "rationale": self.rationale,
            "downgrade_reasons": list(self.downgrade_reasons),
            "is_timely_authoritative": self.is_timely_authoritative,
            "is_fresh": self.is_fresh,
            "is_stale_but_usable": self.is_stale_but_usable,
            "is_deadline_missed": self.is_deadline_missed,
            "is_temporally_unreliable": self.is_temporally_unreliable,
            "participant_id": self.participant_id,
            "evidence_present": self.evidence_present,
            "trace_id": self.trace_id,
            "verdict_id": self.verdict_id,
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalVerdict":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        class_raw = data.get("temporal_class", "temporally_unreliable")
        try:
            t_class = TemporalClass(class_raw)
        except ValueError:
            t_class = TemporalClass.temporally_unreliable
        return cls(
            temporal_class=t_class,
            rationale=data.get("rationale", ""),
            downgrade_reasons=list(data.get("downgrade_reasons", [])),
            is_timely_authoritative=bool(data.get("is_timely_authoritative", False)),
            is_fresh=bool(data.get("is_fresh", False)),
            is_stale_but_usable=bool(data.get("is_stale_but_usable", False)),
            is_deadline_missed=bool(data.get("is_deadline_missed", False)),
            is_temporally_unreliable=bool(data.get("is_temporally_unreliable", False)),
            participant_id=data.get("participant_id"),
            evidence_present=bool(data.get("evidence_present", False)),
            trace_id=data.get("trace_id"),
            verdict_id=data.get("verdict_id", str(uuid.uuid4())),
            evaluated_at=float(data.get("evaluated_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------


def _classify(evidence: TemporalEvidence) -> TemporalVerdict:
    """Internal classification logic (separated for testability)."""
    downgrade_reasons: List[str] = []

    # ------------------------------------------------------------------
    # Rule 0 (highest priority): explicit_temporally_unreliable
    # ------------------------------------------------------------------
    if evidence.explicit_temporally_unreliable:
        return TemporalVerdict(
            temporal_class=TemporalClass.temporally_unreliable,
            rationale=(
                "Temporal integrity has been explicitly declared unavailable "
                "(explicit_temporally_unreliable=True).  "
                "EXPLICIT_UNRELIABLE_ALWAYS_FORCES_LOWEST_CLASS_POLICY "
                "mandates temporally_unreliable regardless of any other "
                "evidence.  No temporal claim can be made."
            ),
            downgrade_reasons=[
                "explicit_temporally_unreliable=True overrides all other "
                "evidence dimensions"
            ],
            is_timely_authoritative=False,
            is_fresh=False,
            is_stale_but_usable=False,
            is_deadline_missed=False,
            is_temporally_unreliable=True,
            participant_id=evidence.participant_id,
            evidence_present=evidence.timestamp_present,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 1: no timestamp → always temporally_unreliable
    # ------------------------------------------------------------------
    if not evidence.timestamp_present:
        return TemporalVerdict(
            temporal_class=TemporalClass.temporally_unreliable,
            rationale=(
                "No timestamp is present (timestamp_present=False).  "
                "TEMPORAL_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY mandates "
                "temporally_unreliable when no timestamp exists.  "
                "Timestamp presence is the minimum requirement for any "
                "temporal classification above temporally_unreliable."
            ),
            downgrade_reasons=[
                "timestamp_present=False — no temporal anchor exists"
            ],
            is_timely_authoritative=False,
            is_fresh=False,
            is_stale_but_usable=False,
            is_deadline_missed=False,
            is_temporally_unreliable=True,
            participant_id=evidence.participant_id,
            evidence_present=False,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 2: deadline missed → always deadline_missed_or_timed_out
    # (unless explicit_temporally_unreliable, already handled above)
    # ------------------------------------------------------------------
    if evidence.deadline_set and not evidence.deadline_met:
        downgrade_reasons.append(
            "deadline_set=True AND deadline_met=False — formal deadline "
            "has been missed"
        )
        return TemporalVerdict(
            temporal_class=TemporalClass.deadline_missed_or_timed_out,
            rationale=(
                "A formal deadline was declared and has not been met "
                "(deadline_set=True, deadline_met=False).  "
                "DEADLINE_MISS_FORCES_TIMED_OUT_CLASS_POLICY mandates "
                "deadline_missed_or_timed_out; this cannot be overridden "
                "by freshness, lag bounds, or heartbeat signals."
            ),
            downgrade_reasons=downgrade_reasons,
            is_timely_authoritative=False,
            is_fresh=False,
            is_stale_but_usable=False,
            is_deadline_missed=True,
            is_temporally_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 3: data exceeds staleness tolerance (implicitly expired)
    # ------------------------------------------------------------------
    if (
        not evidence.within_freshness_window
        and not evidence.within_staleness_tolerance
    ):
        downgrade_reasons.append(
            "within_freshness_window=False AND within_staleness_tolerance=False "
            "— data has exceeded all temporal tolerance bounds"
        )
        return TemporalVerdict(
            temporal_class=TemporalClass.deadline_missed_or_timed_out,
            rationale=(
                "Data exceeds both the freshness window and the staleness "
                "tolerance bound (within_freshness_window=False, "
                "within_staleness_tolerance=False).  The data is implicitly "
                "expired and no temporal claim above "
                "deadline_missed_or_timed_out is defensible."
            ),
            downgrade_reasons=downgrade_reasons,
            is_timely_authoritative=False,
            is_fresh=False,
            is_stale_but_usable=False,
            is_deadline_missed=True,
            is_temporally_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 4: timely_authoritative — all conditions must hold
    # ------------------------------------------------------------------
    timely_auth_blockers: List[str] = []

    if not evidence.timestamp_authoritative:
        timely_auth_blockers.append(
            "timestamp_authoritative=False — clock source is not authoritative"
        )
    if not evidence.within_authoritative_window:
        timely_auth_blockers.append(
            "within_authoritative_window=False — data did not arrive within "
            "the tight authoritative delivery window"
        )
    if not evidence.within_freshness_window:
        timely_auth_blockers.append(
            "within_freshness_window=False — data is not within freshness window"
        )
    if not evidence.clock_uncertainty_acceptable:
        timely_auth_blockers.append(
            "clock_uncertainty_acceptable=False — clock skew/drift is "
            "unacceptable for a timely_authoritative claim"
        )
    if not evidence.lag_measured:
        timely_auth_blockers.append(
            "lag_measured=False — delivery lag is unknown, cannot confirm "
            "it is within authoritative bounds"
        )
    if evidence.lag_measured and not evidence.lag_within_bound:
        timely_auth_blockers.append(
            "lag_within_bound=False — measured lag exceeds tolerance"
        )
    if evidence.heartbeat_required and not evidence.heartbeat_present:
        timely_auth_blockers.append(
            "heartbeat_required=True AND heartbeat_present=False — required "
            "heartbeat is absent; HEARTBEAT_ABSENT_BLOCKS_TIMELY_AUTHORITATIVE_POLICY"
        )
    if evidence.heartbeat_required and evidence.heartbeat_present and not evidence.heartbeat_within_window:
        timely_auth_blockers.append(
            "heartbeat_required=True AND heartbeat_within_window=False — "
            "heartbeat present but arrived outside the expected window"
        )

    if not timely_auth_blockers:
        # All conditions satisfied → timely_authoritative
        return TemporalVerdict(
            temporal_class=TemporalClass.timely_authoritative,
            rationale=(
                "All timely_authoritative conditions are satisfied: "
                "timestamp present and authoritative, data arrived within "
                "the authoritative delivery window, freshness window met, "
                "lag measured and within bound, clock uncertainty acceptable, "
                "and heartbeat conditions met.  "
                "This is the only class representing genuine timely "
                "authoritative temporal truth."
            ),
            downgrade_reasons=[],
            is_timely_authoritative=True,
            is_fresh=True,
            is_stale_but_usable=False,
            is_deadline_missed=False,
            is_temporally_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    downgrade_reasons.extend(timely_auth_blockers)

    # ------------------------------------------------------------------
    # Rule 5: fresh_with_bounded_lag
    # Requires: timestamp_present, within_freshness_window,
    #           lag_measured, lag_within_bound, no deadline miss
    # ------------------------------------------------------------------
    fresh_lag_blockers: List[str] = []
    if not evidence.within_freshness_window:
        fresh_lag_blockers.append(
            "within_freshness_window=False — data is stale, cannot be "
            "fresh_with_bounded_lag"
        )
    if not evidence.lag_measured:
        fresh_lag_blockers.append(
            "lag_measured=False — lag is unknown; "
            "LAG_UNMEASURED_BLOCKS_FRESH_BOUNDED_LAG_POLICY prevents "
            "fresh_with_bounded_lag"
        )
    if evidence.lag_measured and not evidence.lag_within_bound:
        fresh_lag_blockers.append(
            "lag_within_bound=False — measured lag exceeds the operator "
            "tolerance; cannot claim fresh_with_bounded_lag"
        )

    if not fresh_lag_blockers:
        # Freshness window met, lag measured and within bound
        return TemporalVerdict(
            temporal_class=TemporalClass.fresh_with_bounded_lag,
            rationale=(
                "Data is within the freshness window with a measured lag "
                "within the operator tolerance.  However, at least one "
                "timely_authoritative condition is absent: "
                + "; ".join(timely_auth_blockers)
                + ".  Classification is fresh_with_bounded_lag: timely "
                "in a broad sense but NOT timely_authoritative."
            ),
            downgrade_reasons=downgrade_reasons,
            is_timely_authoritative=False,
            is_fresh=True,
            is_stale_but_usable=False,
            is_deadline_missed=False,
            is_temporally_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    downgrade_reasons.extend(
        r for r in fresh_lag_blockers if r not in downgrade_reasons
    )

    # ------------------------------------------------------------------
    # Rule 6: stale_but_usable
    # Requires: timestamp_present, within_staleness_tolerance,
    #           lag_measured (lag known even if not within bound),
    #           no deadline miss
    # ------------------------------------------------------------------
    if evidence.within_staleness_tolerance and evidence.lag_measured:
        return TemporalVerdict(
            temporal_class=TemporalClass.stale_but_usable,
            rationale=(
                "Data is stale (outside the freshness window) but within "
                "the staleness tolerance bound, and the lag is measured.  "
                "Data is usable for non-real-time or post-hoc decisions "
                "but NOT current.  Downgrade reasons: "
                + "; ".join(downgrade_reasons)
                + "."
            ),
            downgrade_reasons=downgrade_reasons,
            is_timely_authoritative=False,
            is_fresh=False,
            is_stale_but_usable=True,
            is_deadline_missed=False,
            is_temporally_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 7: temporally_unreliable (catch-all / fallback)
    # ------------------------------------------------------------------
    # At this point we have a timestamp but cannot classify above
    # temporally_unreliable: freshness window is missed, lag is unknown or
    # out of bounds, AND staleness tolerance conditions aren't met.

    if not downgrade_reasons:
        downgrade_reasons.append(
            "Insufficient positive temporal evidence to assign any class "
            "above temporally_unreliable"
        )

    return TemporalVerdict(
        temporal_class=TemporalClass.temporally_unreliable,
        rationale=(
            "Insufficient temporal evidence to assign a defensible class "
            "above temporally_unreliable.  A timestamp is present but "
            "freshness, lag, staleness, heartbeat, or clock conditions "
            "prevent any higher classification.  Downgrade reasons: "
            + "; ".join(downgrade_reasons)
            + "."
        ),
        downgrade_reasons=downgrade_reasons,
        is_timely_authoritative=False,
        is_fresh=False,
        is_stale_but_usable=False,
        is_deadline_missed=False,
        is_temporally_unreliable=True,
        participant_id=evidence.participant_id,
        evidence_present=True,
        trace_id=evidence.trace_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_temporal_semantics(evidence: TemporalEvidence) -> TemporalVerdict:
    """Classify temporal semantics from the provided evidence.

    Parameters
    ----------
    evidence:
        :class:`TemporalEvidence` instance with all observed dimensions.

    Returns
    -------
    TemporalVerdict
        Formal temporal verdict with class, rationale, and downgrade reasons.

    Notes
    -----
    This function is pure (no side effects) and always returns a verdict.
    It never raises — all exceptions are caught and result in a
    ``temporally_unreliable`` verdict with the exception as the rationale.
    """
    try:
        return _classify(evidence)
    except Exception as exc:  # pragma: no cover
        logger.exception(
            "classify_temporal_semantics: unexpected error — "
            "defaulting to temporally_unreliable"
        )
        return TemporalVerdict(
            temporal_class=TemporalClass.temporally_unreliable,
            rationale=(
                f"classify_temporal_semantics raised an unexpected exception: "
                f"{exc!r}.  Defaulting to temporally_unreliable."
            ),
            downgrade_reasons=[f"Internal exception: {exc!r}"],
            is_timely_authoritative=False,
            is_fresh=False,
            is_stale_but_usable=False,
            is_deadline_missed=False,
            is_temporally_unreliable=True,
            evidence_present=False,
        )


def build_temporal_verdict(evidence: TemporalEvidence) -> TemporalVerdict:
    """Alias for :func:`classify_temporal_semantics`.

    Provided for API symmetry with other contract modules.
    """
    return classify_temporal_semantics(evidence)


def build_baseline_temporal_verdict() -> TemporalVerdict:
    """Return a baseline temporal verdict with all evidence at conservative
    defaults.

    The baseline verdict MUST be ``temporally_unreliable`` — when no
    evidence is provided, the system cannot claim any temporal authority,
    freshness, or usability.

    Returns
    -------
    TemporalVerdict
        A ``temporally_unreliable`` verdict representing the
        zero-evidence / fail-conservative baseline.
    """
    return classify_temporal_semantics(TemporalEvidence())
