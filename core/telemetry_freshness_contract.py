#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/telemetry_freshness_contract.py
======================================
PR-15: Real-Time Observability / Telemetry Freshness Semantics Contract.

Background
----------
The Galaxy V2 system already possesses substantial observability / telemetry
infrastructure: runtime truth surfaces, readiness / acceptance / governance
surfaces, streaming and polling evidence paths, participant lifecycle signals,
Android evaluator artifacts, delegated runtime audit events, and signal
ingestion pipelines.  This demonstrates that the system is not opaque to
observers.

However, before this module the system had no formal contract that
distinguished *having telemetry* from *telemetry being sufficiently fresh,
complete, and authoritative*.  The practical risk was silent optimism: the
presence of any logs, signals, or metrics could be interpreted — or
programmatically misclassified — as evidence that the system's current state
is being observed in real-time, completely, and reliably.

Specifically, the following distinctions were absent:

* **realtime_authoritative** vs **fresh_not_realtime** — is the observation
  path delivering data in strict real-time with confirmed delivery and
  authority, or is the data recent but not sourced from a confirmed
  real-time channel?
* **delayed_observable** — telemetry is present but arrives with a known or
  measured delay; the data is valid but NOT current.
* **partially_observable** — only a subset of the required telemetry channels
  are active; system state cannot be fully observed from available data.
* **telemetry_unreliable** — channels are present but evidence of lossy
  delivery, sampling gaps, or unresolvable contradictions prevents any
  reliable observability claim.

Without these distinctions, ``runtime truth`` / ``acceptance`` /
``readiness`` / ``governance`` surfaces cannot distinguish "we have some
signal" from "we are observing the system reliably and in real-time".

This module closes that gap by establishing the **Telemetry Freshness
Contract** — a formal classification contract that:

1. Defines five mutually exclusive and exhaustive
   :class:`TelemetryFreshnessClass` values.
2. Specifies precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient, stale, partial,
   or unreliable telemetry always produces the lowest defensible class rather
   than the optimistic one.
4. Prohibits treating signal presence, polling receipt, or delayed ingestion
   as equivalent to real-time authoritative observability.
5. Provides a :class:`TelemetryFreshnessVerdict` dataclass consumable by
   runtime truth / acceptance / readiness / governance pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  TELEMETRY FRESHNESS CONTRACT  (this module — PR-15)                │
    │                                                                     │
    │  Five freshness classes (strictly ordered by observability):        │
    │    1. realtime_authoritative       (highest — channel confirmed     │
    │       real-time, all required channels active, freshness within     │
    │       authoritative window, no delivery gaps or sampling losses)    │
    │    2. fresh_not_realtime           (data is recent and within       │
    │       freshness window but sourced from a non-real-time path:       │
    │       polling, batch, near-realtime streaming with lag; NOT the     │
    │       same as realtime_authoritative)                               │
    │    3. delayed_observable           (telemetry present but with a    │
    │       known or measured delay exceeding the freshness window;       │
    │       data is valid for post-hoc analysis but NOT current)          │
    │    4. partially_observable         (a subset of required channels   │
    │       is active; system state is incompletely covered; cannot       │
    │       claim any full observability class)                           │
    │    5. telemetry_unreliable         (lowest — channels present but   │
    │       lossy delivery, unresolvable contradictions, or sampling      │
    │       gaps prevent any reliable observability claim; default        │
    │       fail-conservative baseline when no positive evidence)         │
    │                                                                     │
    │  Evidence dimensions evaluated:                                     │
    │    • realtime_channel_confirmed   — at least one channel is         │
    │      confirmed to deliver data in real-time with known latency      │
    │      bounds                                                         │
    │    • all_required_channels_active — every required telemetry        │
    │      channel is reporting (no channel is missing or silent)         │
    │    • freshness_within_window      — most recent telemetry sample    │
    │      is within the operator-specified freshness window              │
    │    • delivery_path_authoritative  — data is sourced from a path     │
    │      that has been explicitly designated authoritative (not a       │
    │      fallback, shadow, or mirror path)                              │
    │    • no_delivery_gaps             — no known delivery interruptions │
    │      or sequence gaps in the observation window                     │
    │    • no_sampling_loss             — sampling rate is sufficient;    │
    │      no evidence of dropped samples or resolution loss              │
    │    • evidence_lag_known           — the delay between event         │
    │      occurrence and telemetry receipt is measured and bounded       │
    │    • post_hoc_evidence_only       — all available evidence is       │
    │      post-hoc (arrived after the fact); no live channel exists      │
    │    • explicit_unreliable          — operator or system has          │
    │      explicitly declared the telemetry channel unreliable           │
    │                                                                     │
    │  Downgrade semantics:                                               │
    │    • explicit_unreliable → ALWAYS telemetry_unreliable              │
    │    • post_hoc_evidence_only → NEVER realtime_authoritative or       │
    │      fresh_not_realtime (at most delayed_observable)                │
    │    • not all required channels active → NEVER realtime_authoritative│
    │      (at most partially_observable)                                 │
    │    • delivery_path not authoritative → NEVER realtime_authoritative │
    │    • freshness outside window → NEVER realtime_authoritative or     │
    │      fresh_not_realtime (at most delayed_observable)                │
    │    • delivery gaps present → downgrade from realtime_authoritative  │
    │    • sampling loss present → downgrade from realtime_authoritative  │
    │    • no positive telemetry evidence → telemetry_unreliable          │
    │      (fail-conservative default)                                    │
    │                                                                     │
    │  Produces:                                                          │
    │    • TelemetryFreshnessVerdict  (structured output)                 │
    │                                                                     │
    │  Consumed by:                                                       │
    │    • system_final_acceptance_verdict (telemetry_freshness           │
    │      dimension)                                                     │
    │    • runtime truth / acceptance / readiness / governance surfaces   │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class (``telemetry_unreliable``) rather than the optimistic one.
3. **No optimistic promotion** — signal presence, polling receipt, delayed
   ingestion, and post-hoc evidence return are explicitly excluded from being
   promoted to ``realtime_authoritative``.
4. **Taxonomy boundary enforcement** — "can see some telemetry" does NOT imply
   "is observing in real-time and authoritatively"; "data arrived" does NOT
   imply "data is current or from a confirmed real-time channel"; "channels
   exist" does NOT imply "all required channels are active and gap-free".
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Critical boundary: what counts as realtime_authoritative vs what does not
--------------------------------------------------------------------------
- **Signal presence alone** — does NOT constitute realtime_authoritative;
  a log entry, a metric sample, or an event receipt proves only that
  *something* was observed at *some point*, not that observation is
  real-time, complete, or authoritative.
- **Polling / batch receipt** — does NOT constitute realtime_authoritative;
  polling paths introduce inherent latency between event occurrence and
  observation.
- **Post-hoc evidence return** — does NOT retroactively elevate the
  freshness class to realtime_authoritative for the window in which the
  system was unobserved.
- **Partial channel availability** — does NOT constitute
  realtime_authoritative or fresh_not_realtime; if required channels are
  missing, the system state cannot be fully observed.
- **No evidence** — cannot be treated as realtime_authoritative; absence of
  confirmed channels, freshness evidence, and delivery confirmation is the
  conservative default (telemetry_unreliable).

Public API
----------
Authority sentinels::

    TELEMETRY_FRESHNESS_CONTRACT_AUTHORITY
    TELEMETRY_FRESHNESS_CONTRACT_PR15_SENTINEL

Policy sentinels::

    FRESHNESS_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY
    SIGNAL_PRESENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY
    POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY
    PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_POLICY
    STALE_TELEMETRY_MUST_DOWNGRADE_CLASS_POLICY
    DELIVERY_GAP_MUST_DOWNGRADE_FROM_REALTIME_POLICY
    TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY

Enumerations::

    TelemetryFreshnessClass
    ObservationPathKind

Data classes::

    TelemetryFreshnessEvidence
    TelemetryFreshnessVerdict

Functions::

    classify_telemetry_freshness(evidence) -> TelemetryFreshnessVerdict
    build_telemetry_freshness_verdict(evidence) -> TelemetryFreshnessVerdict
    build_baseline_telemetry_freshness_verdict() -> TelemetryFreshnessVerdict
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TelemetryFreshnessContract")

__all__ = [
    # Authority sentinels
    "TELEMETRY_FRESHNESS_CONTRACT_AUTHORITY",
    "TELEMETRY_FRESHNESS_CONTRACT_PR15_SENTINEL",
    # Policy sentinels
    "FRESHNESS_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY",
    "SIGNAL_PRESENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY",
    "POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY",
    "PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_POLICY",
    "STALE_TELEMETRY_MUST_DOWNGRADE_CLASS_POLICY",
    "DELIVERY_GAP_MUST_DOWNGRADE_FROM_REALTIME_POLICY",
    "TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY",
    # Enumerations
    "TelemetryFreshnessClass",
    "ObservationPathKind",
    # Data classes
    "TelemetryFreshnessEvidence",
    "TelemetryFreshnessVerdict",
    # Functions
    "classify_telemetry_freshness",
    "build_telemetry_freshness_verdict",
    "build_baseline_telemetry_freshness_verdict",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

TELEMETRY_FRESHNESS_CONTRACT_AUTHORITY: str = (
    "TELEMETRY_FRESHNESS_CONTRACT_AUTHORITY::"
    "core.telemetry_freshness_contract::PR15::"
    "realtime-observability-telemetry-freshness-taxonomy::"
    "formal-telemetry-freshness-contract-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical authority for telemetry freshness /
real-time observability classification in Galaxy V2.

Import this sentinel to assert that a release gate, governance surface,
acceptance evaluator, or runtime truth layer is consuming a formal
telemetry freshness classification rather than an implicit signal-presence
flag."""

TELEMETRY_FRESHNESS_CONTRACT_PR15_SENTINEL: str = (
    "TELEMETRY_FRESHNESS_CONTRACT_PR15_SENTINEL::"
    "package=PR15::profile=telemetry-freshness-contract-v1::"
    "module=core.telemetry_freshness_contract"
)
"""Package sentinel for PR-15 telemetry freshness contract."""

FRESHNESS_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY: str = (
    "POLICY::FRESHNESS_TAXONOMY_IS_FIRST_CLASS_DIMENSION_V1: "
    "Real-time observability / telemetry freshness MUST be treated as a "
    "first-class operational dimension by truth surfaces, readiness gates, "
    "acceptance evaluators, and governance pipelines.  Surfaces MUST NOT "
    "conflate 'some telemetry is visible' (signal presence) with 'the system "
    "is being observed in real-time, completely, and authoritatively'.  "
    "Every observability verdict MUST include a TelemetryFreshnessVerdict "
    "that identifies the applicable freshness class.  "
    "See: TelemetryFreshnessClass taxonomy in "
    "core.telemetry_freshness_contract (PR-15)."
)
"""Policy: telemetry freshness is a first-class observability dimension."""

SIGNAL_PRESENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY: str = (
    "POLICY::SIGNAL_PRESENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_V1: "
    "The mere presence of a log entry, metric sample, event receipt, or any "
    "other telemetry signal MUST NOT be used to claim realtime_authoritative "
    "observability.  Signal presence proves only that something was observed "
    "at some point; it does not prove that observation is real-time, "
    "complete, gap-free, or from a confirmed authoritative delivery path.  "
    "Only a confirmed real-time channel with fresh data, all required "
    "channels active, no delivery gaps, and an authoritative delivery path "
    "qualifies as realtime_authoritative.  "
    "See: TelemetryFreshnessClass.realtime_authoritative in "
    "core.telemetry_freshness_contract (PR-15)."
)
"""Policy: signal presence alone must not produce realtime_authoritative."""

POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY: str = (
    "POLICY::POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_V1: "
    "When all available evidence has arrived post-hoc (after the fact, via "
    "deferred ingestion, replay, or delayed return), the freshness class "
    "MUST NOT be set to realtime_authoritative or fresh_not_realtime.  "
    "Post-hoc evidence by definition describes a past state and cannot "
    "establish that the system was being observed in real-time during the "
    "window in question.  At best the class is delayed_observable.  "
    "'Evidence arrived eventually' is not the same as 'we were observing "
    "in real-time'.  "
    "See: TelemetryFreshnessClass.delayed_observable in "
    "core.telemetry_freshness_contract (PR-15)."
)
"""Policy: post-hoc evidence must not produce realtime_authoritative."""

PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_POLICY: str = (
    "POLICY::PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_V1: "
    "When not all required telemetry channels are active (some channels are "
    "missing or silent), the freshness class MUST be at most "
    "partially_observable.  Partial channel availability means system state "
    "cannot be fully observed even if the active channels are delivering "
    "data in real-time.  The class MUST NOT be promoted to "
    "realtime_authoritative or fresh_not_realtime when coverage is "
    "incomplete.  "
    "See: TelemetryFreshnessClass.partially_observable in "
    "core.telemetry_freshness_contract (PR-15)."
)
"""Policy: incomplete channel coverage blocks realtime_authoritative."""

STALE_TELEMETRY_MUST_DOWNGRADE_CLASS_POLICY: str = (
    "POLICY::STALE_TELEMETRY_MUST_DOWNGRADE_CLASS_V1: "
    "When the most recent telemetry sample exceeds the operator-specified "
    "freshness window, the freshness class MUST be downgraded.  Stale "
    "telemetry implies the current system state is not actively being "
    "observed; it MUST NOT be used to maintain a realtime_authoritative or "
    "fresh_not_realtime classification.  A surface with only stale samples "
    "is at most delayed_observable.  "
    "See: freshness_within_window flag in classify_telemetry_freshness() "
    "(PR-15)."
)
"""Policy: stale telemetry must downgrade the freshness class."""

DELIVERY_GAP_MUST_DOWNGRADE_FROM_REALTIME_POLICY: str = (
    "POLICY::DELIVERY_GAP_MUST_DOWNGRADE_FROM_REALTIME_V1: "
    "When delivery gaps, sequence holes, or sampling losses are detected in "
    "the observation window, the freshness class MUST be downgraded from "
    "realtime_authoritative.  Gaps in delivery mean the observation record "
    "is not continuous; the system state during the gap period was not "
    "observed in real-time.  A delivery gap MUST produce at most "
    "fresh_not_realtime (if data is still within the freshness window) or "
    "partially_observable / delayed_observable (if coverage is also "
    "incomplete or stale).  "
    "See: no_delivery_gaps and no_sampling_loss flags in "
    "classify_telemetry_freshness() (PR-15)."
)
"""Policy: delivery gaps and sampling loss must downgrade from realtime."""

TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY: str = (
    "POLICY::TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_V1: "
    "When no positive telemetry evidence is present — no confirmed channels, "
    "no freshness evidence, no delivery path confirmation — the freshness "
    "class MUST default to telemetry_unreliable.  The absence of telemetry "
    "evidence is NOT a signal of realtime_authoritative observability; it is "
    "a signal of unknown or worst-case observability state.  Silence is not "
    "real-time visibility.  "
    "See: TelemetryFreshnessClass.telemetry_unreliable in "
    "core.telemetry_freshness_contract (PR-15)."
)
"""Policy: absence of telemetry evidence defaults to unreliable (fail-conservative)."""


# ---------------------------------------------------------------------------
# TelemetryFreshnessClass
# ---------------------------------------------------------------------------


class TelemetryFreshnessClass(str, Enum):
    """Five-class telemetry freshness taxonomy for real-time observability
    semantics.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.

    Ordering (from most observable to least):
      realtime_authoritative > fresh_not_realtime >
      delayed_observable > partially_observable > telemetry_unreliable
    """

    realtime_authoritative = "realtime_authoritative"
    """System state is being observed in real-time via a confirmed authoritative
    channel.  All required channels are active, freshness is within the
    authoritative window, delivery has no gaps, and the path is explicitly
    designated authoritative.  This is the only class that represents genuine
    real-time operational visibility.

    Requirements (all must hold):
    - realtime_channel_confirmed = True
    - all_required_channels_active = True
    - freshness_within_window = True
    - delivery_path_authoritative = True
    - no_delivery_gaps = True
    - no_sampling_loss = True
    - post_hoc_evidence_only = False
    - explicit_unreliable = False
    """

    fresh_not_realtime = "fresh_not_realtime"
    """Data is recent and within the freshness window, but is sourced from a
    non-real-time path (polling, batch ingestion, near-realtime streaming
    with bounded lag, or a non-authoritative mirror).  The data is timely but
    NOT real-time authoritative.

    Requirements:
    - freshness_within_window = True
    - all_required_channels_active = True
    - post_hoc_evidence_only = False
    - explicit_unreliable = False
    - realtime_channel_confirmed = False OR delivery_path_authoritative = False
      OR no_delivery_gaps = False OR no_sampling_loss = False
      (i.e., at least one realtime_authoritative condition is missing)
    """

    delayed_observable = "delayed_observable"
    """Telemetry is present but arrives with a known or measured delay that
    exceeds the freshness window.  The data is valid for post-hoc analysis
    and historical review but does NOT represent current real-time state.
    Post-hoc evidence also maps to this class.

    Requirements:
    - Some telemetry evidence present (channels exist, samples available)
    - freshness_within_window = False OR post_hoc_evidence_only = True
    - all_required_channels_active = True OR
      evidence_lag_known = True (delay is measured and bounded)
    - explicit_unreliable = False
    """

    partially_observable = "partially_observable"
    """Only a subset of required telemetry channels are active.  System state
    cannot be fully observed from the available data.  This class applies
    regardless of the freshness of the active channels — incomplete coverage
    prevents any full observability claim.

    Requirements:
    - all_required_channels_active = False (at least one required channel
      is missing or silent)
    - Some positive telemetry evidence exists on active channels
    - explicit_unreliable = False
    """

    telemetry_unreliable = "telemetry_unreliable"
    """Lowest class — channels may be nominally present but lossy delivery,
    unresolvable contradictions, sampling gaps, or the complete absence of
    positive telemetry evidence prevent any reliable observability claim.
    This is the fail-conservative default when no positive evidence is
    present, or when the operator / system has explicitly declared the
    telemetry unreliable.

    Requirements (any of):
    - explicit_unreliable = True
    - No positive telemetry evidence at all (fail-conservative default)
    - Delivery gaps + sampling loss + stale data + partial channels
      (combination that prevents any classification above unreliable)
    """


# Numeric rank for comparison (lower = worse)
_CLASS_RANK: Dict[str, int] = {
    TelemetryFreshnessClass.telemetry_unreliable.value: 0,
    TelemetryFreshnessClass.partially_observable.value: 1,
    TelemetryFreshnessClass.delayed_observable.value: 2,
    TelemetryFreshnessClass.fresh_not_realtime.value: 3,
    TelemetryFreshnessClass.realtime_authoritative.value: 4,
}


def _worse_or_equal(
    a: TelemetryFreshnessClass, b: TelemetryFreshnessClass
) -> bool:
    """Return True if class *a* is worse than or equal to class *b*."""
    return _CLASS_RANK[a.value] <= _CLASS_RANK[b.value]


# ---------------------------------------------------------------------------
# ObservationPathKind
# ---------------------------------------------------------------------------


class ObservationPathKind(str, Enum):
    """Describes the delivery path via which telemetry is received.

    Used to distinguish realtime_authoritative from fresh_not_realtime.
    """

    realtime_push = "realtime_push"
    """Data is delivered via a confirmed real-time push channel with known
    latency bounds.  The only path kind that can contribute to
    realtime_authoritative (subject to all other conditions being met)."""

    polling = "polling"
    """Data is retrieved by periodic polling.  Inherently introduces
    observation lag between event occurrence and detection.  Polling paths
    cannot produce realtime_authoritative."""

    streaming_with_lag = "streaming_with_lag"
    """Data arrives via a streaming channel but with a bounded, non-zero
    lag (e.g., a message queue with processing delay).  May produce
    fresh_not_realtime when data is within the freshness window."""

    batch_ingestion = "batch_ingestion"
    """Data arrives in batches.  Cannot produce realtime_authoritative
    or fresh_not_realtime unless the batch interval is within the
    freshness window."""

    post_hoc_replay = "post_hoc_replay"
    """Data arrived after the fact via replay or deferred ingestion.
    Cannot produce realtime_authoritative or fresh_not_realtime.
    At most delayed_observable."""

    unknown = "unknown"
    """Delivery path is unknown.  Must be treated conservatively — cannot
    claim realtime_authoritative from an unknown path."""


# ---------------------------------------------------------------------------
# TelemetryFreshnessEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TelemetryFreshnessEvidence:
    """Structured evidence input for the telemetry freshness classifier.

    All fields have safe (fail-conservative) defaults so that an absent
    signal does not silently produce an optimistic classification.

    Attributes
    ----------
    realtime_channel_confirmed:
        True only when at least one telemetry channel has been confirmed
        to deliver data in real-time with known latency bounds.  Defaults
        to False (conservative).
    all_required_channels_active:
        True when every required telemetry channel is reporting and no
        required channel is missing or silent.  Defaults to False
        (conservative).
    freshness_within_window:
        True only when the most recent telemetry sample is within the
        operator-specified freshness window.  Defaults to False
        (conservative).
    delivery_path_authoritative:
        True when the delivery path has been explicitly designated
        authoritative (not a fallback, shadow, or mirror path).  Defaults
        to False (conservative).
    no_delivery_gaps:
        True when no delivery interruptions or sequence gaps have been
        detected in the observation window.  Defaults to False
        (conservative).
    no_sampling_loss:
        True when the sampling rate is sufficient and no evidence of
        dropped samples or resolution loss exists.  Defaults to False
        (conservative).
    evidence_lag_known:
        True when the delay between event occurrence and telemetry receipt
        is measured and bounded (even if that delay is large).  Defaults
        to False (conservative).
    post_hoc_evidence_only:
        True when ALL available evidence has arrived post-hoc (via
        deferred ingestion, replay, or delayed return) and no live channel
        exists.  This flag explicitly marks that no real-time observation
        occurred.  Defaults to False (conservative).
    explicit_unreliable:
        True when the operator or system has explicitly declared the
        telemetry channel(s) unreliable (e.g., known data loss, channel
        failure, contradictory readings).  Defaults to False.  When True,
        ALWAYS produces telemetry_unreliable regardless of other fields.
    observation_path_kind:
        The kind of delivery path via which telemetry is received.
        Defaults to ObservationPathKind.unknown (conservative).
    participant_id:
        Optional participant or surface identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    extra_context:
        Optional dict of additional context signals.  Not used in
        classification logic but included in the verdict for auditability.
    """

    realtime_channel_confirmed: bool = False
    all_required_channels_active: bool = False
    freshness_within_window: bool = False
    delivery_path_authoritative: bool = False
    no_delivery_gaps: bool = False
    no_sampling_loss: bool = False
    evidence_lag_known: bool = False
    post_hoc_evidence_only: bool = False
    explicit_unreliable: bool = False
    observation_path_kind: ObservationPathKind = ObservationPathKind.unknown
    participant_id: Optional[str] = None
    trace_id: Optional[str] = None
    extra_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "realtime_channel_confirmed": self.realtime_channel_confirmed,
            "all_required_channels_active": self.all_required_channels_active,
            "freshness_within_window": self.freshness_within_window,
            "delivery_path_authoritative": self.delivery_path_authoritative,
            "no_delivery_gaps": self.no_delivery_gaps,
            "no_sampling_loss": self.no_sampling_loss,
            "evidence_lag_known": self.evidence_lag_known,
            "post_hoc_evidence_only": self.post_hoc_evidence_only,
            "explicit_unreliable": self.explicit_unreliable,
            "observation_path_kind": self.observation_path_kind.value,
            "participant_id": self.participant_id,
            "trace_id": self.trace_id,
            "extra_context": dict(self.extra_context),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TelemetryFreshnessEvidence":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        path_raw = data.get("observation_path_kind", "unknown")
        try:
            path_kind = ObservationPathKind(path_raw)
        except ValueError:
            path_kind = ObservationPathKind.unknown
        return cls(
            realtime_channel_confirmed=bool(
                data.get("realtime_channel_confirmed", False)
            ),
            all_required_channels_active=bool(
                data.get("all_required_channels_active", False)
            ),
            freshness_within_window=bool(
                data.get("freshness_within_window", False)
            ),
            delivery_path_authoritative=bool(
                data.get("delivery_path_authoritative", False)
            ),
            no_delivery_gaps=bool(data.get("no_delivery_gaps", False)),
            no_sampling_loss=bool(data.get("no_sampling_loss", False)),
            evidence_lag_known=bool(data.get("evidence_lag_known", False)),
            post_hoc_evidence_only=bool(
                data.get("post_hoc_evidence_only", False)
            ),
            explicit_unreliable=bool(data.get("explicit_unreliable", False)),
            observation_path_kind=path_kind,
            participant_id=data.get("participant_id"),
            trace_id=data.get("trace_id"),
            extra_context=dict(data.get("extra_context", {})),
        )


# ---------------------------------------------------------------------------
# TelemetryFreshnessVerdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TelemetryFreshnessVerdict:
    """Formal telemetry freshness verdict for a system surface.

    Produced by :func:`classify_telemetry_freshness`.

    Attributes
    ----------
    freshness_class:
        The classified :class:`TelemetryFreshnessClass` for this context.
    rationale:
        Human-readable explanation of why this class was assigned.  Always
        non-empty.
    downgrade_reasons:
        List of specific reasons that caused the class to be downgraded from
        an optimistic baseline.  Empty when no downgrade occurred.
    is_realtime_authoritative:
        True only for ``realtime_authoritative`` class.  MUST NOT be set
        for any other class.
    is_fresh:
        True for ``realtime_authoritative`` and ``fresh_not_realtime``.
        Indicates data is within the freshness window.
    is_delayed:
        True for ``delayed_observable``.  Indicates data is valid but not
        current.
    is_partial:
        True for ``partially_observable``.  Indicates incomplete channel
        coverage.
    is_unreliable:
        True for ``telemetry_unreliable``.  Indicates no reliable
        observability claim can be made.
    participant_id:
        Identifier of the surface or participant this verdict applies to.
    evidence_present:
        Whether any positive telemetry evidence was available during
        classification.
    classified_at:
        Unix timestamp (float) when this verdict was produced.
    verdict_id:
        Unique identifier for this verdict instance.
    trace_id:
        Optional distributed-trace identifier.
    """

    freshness_class: TelemetryFreshnessClass
    rationale: str
    downgrade_reasons: List[str] = field(default_factory=list)
    is_realtime_authoritative: bool = False
    is_fresh: bool = False
    is_delayed: bool = False
    is_partial: bool = False
    is_unreliable: bool = False
    participant_id: Optional[str] = None
    evidence_present: bool = False
    classified_at: float = field(default_factory=time.time)
    verdict_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "freshness_class": self.freshness_class.value,
            "rationale": self.rationale,
            "downgrade_reasons": list(self.downgrade_reasons),
            "is_realtime_authoritative": self.is_realtime_authoritative,
            "is_fresh": self.is_fresh,
            "is_delayed": self.is_delayed,
            "is_partial": self.is_partial,
            "is_unreliable": self.is_unreliable,
            "participant_id": self.participant_id,
            "evidence_present": self.evidence_present,
            "classified_at": self.classified_at,
            "verdict_id": self.verdict_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any]
    ) -> "TelemetryFreshnessVerdict":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        class_raw = data.get("freshness_class", "telemetry_unreliable")
        try:
            f_class = TelemetryFreshnessClass(class_raw)
        except ValueError:
            f_class = TelemetryFreshnessClass.telemetry_unreliable
        return cls(
            freshness_class=f_class,
            rationale=data.get("rationale", ""),
            downgrade_reasons=list(data.get("downgrade_reasons", [])),
            is_realtime_authoritative=bool(
                data.get("is_realtime_authoritative", False)
            ),
            is_fresh=bool(data.get("is_fresh", False)),
            is_delayed=bool(data.get("is_delayed", False)),
            is_partial=bool(data.get("is_partial", False)),
            is_unreliable=bool(data.get("is_unreliable", False)),
            participant_id=data.get("participant_id"),
            evidence_present=bool(data.get("evidence_present", False)),
            classified_at=float(data.get("classified_at", time.time())),
            verdict_id=data.get("verdict_id", uuid.uuid4().hex[:12]),
            trace_id=data.get("trace_id"),
        )


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------


def classify_telemetry_freshness(
    evidence: TelemetryFreshnessEvidence,
) -> TelemetryFreshnessVerdict:
    """Classify the telemetry freshness class for a system surface.

    This is the canonical entry point for telemetry freshness /
    real-time observability classification.  It applies the fail-conservative
    downgrade rules defined in the module docstring and enforced by the
    policy sentinels.

    Classification logic (evaluated in priority order):
    1. ``explicit_unreliable=True`` → **telemetry_unreliable** (always)
    2. All six realtime conditions met (realtime_channel_confirmed,
       all_required_channels_active, freshness_within_window,
       delivery_path_authoritative, no_delivery_gaps, no_sampling_loss)
       AND NOT post_hoc_evidence_only → **realtime_authoritative**
    3. ``freshness_within_window=True`` AND
       ``all_required_channels_active=True`` AND NOT
       ``post_hoc_evidence_only`` → **fresh_not_realtime**
    4. ``post_hoc_evidence_only=True`` OR
       (evidence present AND freshness outside window AND
       ``all_required_channels_active=True``) → **delayed_observable**
    5. Some positive evidence AND NOT ``all_required_channels_active``
       → **partially_observable**
    6. All other cases → **telemetry_unreliable** (fail-conservative)

    Parameters
    ----------
    evidence:
        :class:`TelemetryFreshnessEvidence` describing the telemetry
        channel state.

    Returns
    -------
    TelemetryFreshnessVerdict
        Immutable verdict recording the class, rationale, and any downgrade
        reasons.  Never raises; returns ``telemetry_unreliable`` on
        unexpected input.
    """
    try:
        return _classify(evidence)
    except Exception as exc:
        logger.warning(
            "classify_telemetry_freshness raised unexpectedly: %r — "
            "defaulting to telemetry_unreliable",
            exc,
        )
        return TelemetryFreshnessVerdict(
            freshness_class=TelemetryFreshnessClass.telemetry_unreliable,
            rationale=(
                f"Classification raised an unexpected exception ({exc!r}); "
                "defaulting to telemetry_unreliable per fail-conservative policy."
            ),
            downgrade_reasons=[f"exception: {exc!r}"],
            is_realtime_authoritative=False,
            is_fresh=False,
            is_delayed=False,
            is_partial=False,
            is_unreliable=True,
            evidence_present=False,
        )


def _classify(
    evidence: TelemetryFreshnessEvidence,
) -> TelemetryFreshnessVerdict:
    """Internal classification logic (separated for testability)."""
    downgrade_reasons: List[str] = []

    # ------------------------------------------------------------------
    # Rule 1: explicit_unreliable always wins
    # ------------------------------------------------------------------
    if evidence.explicit_unreliable:
        return TelemetryFreshnessVerdict(
            freshness_class=TelemetryFreshnessClass.telemetry_unreliable,
            rationale=(
                "Telemetry has been explicitly declared unreliable.  "
                "TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY and "
                "explicit_unreliable=True override all other signals."
            ),
            downgrade_reasons=["explicit_unreliable=True"],
            is_realtime_authoritative=False,
            is_fresh=False,
            is_delayed=False,
            is_partial=False,
            is_unreliable=True,
            participant_id=evidence.participant_id,
            evidence_present=False,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 2: realtime_authoritative — requires ALL six conditions AND
    #         no post-hoc-only evidence
    # ------------------------------------------------------------------
    if (
        evidence.realtime_channel_confirmed
        and evidence.all_required_channels_active
        and evidence.freshness_within_window
        and evidence.delivery_path_authoritative
        and evidence.no_delivery_gaps
        and evidence.no_sampling_loss
        and not evidence.post_hoc_evidence_only
    ):
        return TelemetryFreshnessVerdict(
            freshness_class=TelemetryFreshnessClass.realtime_authoritative,
            rationale=(
                "All six realtime_authoritative conditions are met: "
                "realtime channel confirmed, all required channels active, "
                "freshness within window, delivery path authoritative, "
                "no delivery gaps, no sampling loss.  "
                "Real-time authoritative observability is formally confirmed."
            ),
            downgrade_reasons=[],
            is_realtime_authoritative=True,
            is_fresh=True,
            is_delayed=False,
            is_partial=False,
            is_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Collect downgrade reasons for non-realtime states
    # ------------------------------------------------------------------
    if not evidence.realtime_channel_confirmed:
        downgrade_reasons.append(
            "realtime_channel_confirmed=False: "
            "SIGNAL_PRESENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY applied."
        )
    if not evidence.delivery_path_authoritative:
        downgrade_reasons.append(
            "delivery_path_authoritative=False: delivery path is not confirmed "
            "as authoritative."
        )
    if not evidence.no_delivery_gaps:
        downgrade_reasons.append(
            "no_delivery_gaps=False: "
            "DELIVERY_GAP_MUST_DOWNGRADE_FROM_REALTIME_POLICY applied."
        )
    if not evidence.no_sampling_loss:
        downgrade_reasons.append(
            "no_sampling_loss=False: sampling loss detected; "
            "DELIVERY_GAP_MUST_DOWNGRADE_FROM_REALTIME_POLICY applied."
        )
    if evidence.post_hoc_evidence_only:
        downgrade_reasons.append(
            "post_hoc_evidence_only=True: "
            "POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY applied."
        )
    if not evidence.freshness_within_window:
        downgrade_reasons.append(
            "freshness_within_window=False: "
            "STALE_TELEMETRY_MUST_DOWNGRADE_CLASS_POLICY applied."
        )
    if not evidence.all_required_channels_active:
        downgrade_reasons.append(
            "all_required_channels_active=False: "
            "PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_POLICY applied."
        )

    # ------------------------------------------------------------------
    # Rule 3: fresh_not_realtime — data is within freshness window, all
    #         channels active, not post-hoc, but missing ≥1 realtime
    #         condition (already excluded from realtime_authoritative above)
    # ------------------------------------------------------------------
    if (
        evidence.freshness_within_window
        and evidence.all_required_channels_active
        and not evidence.post_hoc_evidence_only
    ):
        return TelemetryFreshnessVerdict(
            freshness_class=TelemetryFreshnessClass.fresh_not_realtime,
            rationale=(
                "Data is within the freshness window and all required channels "
                "are active, but at least one realtime_authoritative condition "
                "is not met (realtime channel not confirmed, path not "
                "authoritative, delivery gaps, or sampling loss).  "
                "Classification is fresh_not_realtime: timely but not "
                "real-time authoritative."
            ),
            downgrade_reasons=downgrade_reasons,
            is_realtime_authoritative=False,
            is_fresh=True,
            is_delayed=False,
            is_partial=False,
            is_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 4: post-hoc evidence only → delayed_observable
    #         OR stale but all channels active and lag is known
    # ------------------------------------------------------------------
    _any_evidence = any([
        evidence.realtime_channel_confirmed,
        evidence.all_required_channels_active,
        evidence.freshness_within_window,
        evidence.evidence_lag_known,
        evidence.post_hoc_evidence_only,
    ])

    if evidence.post_hoc_evidence_only and _any_evidence:
        return TelemetryFreshnessVerdict(
            freshness_class=TelemetryFreshnessClass.delayed_observable,
            rationale=(
                "All available evidence is post-hoc (arrived after the fact "
                "via deferred ingestion, replay, or delayed return).  No "
                "live real-time channel exists.  "
                "POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY "
                "prevents classification as realtime_authoritative or "
                "fresh_not_realtime.  Classification is delayed_observable: "
                "valid for post-hoc analysis but does NOT represent current "
                "real-time state."
            ),
            downgrade_reasons=downgrade_reasons,
            is_realtime_authoritative=False,
            is_fresh=False,
            is_delayed=True,
            is_partial=False,
            is_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    if (
        not evidence.freshness_within_window
        and evidence.all_required_channels_active
        and evidence.evidence_lag_known
        and _any_evidence
    ):
        return TelemetryFreshnessVerdict(
            freshness_class=TelemetryFreshnessClass.delayed_observable,
            rationale=(
                "All required channels are active and the evidence lag is "
                "measured and bounded, but the most recent sample exceeds "
                "the freshness window.  Data is valid for post-hoc analysis "
                "but does NOT represent current real-time state.  "
                "STALE_TELEMETRY_MUST_DOWNGRADE_CLASS_POLICY applied.  "
                "Classification is delayed_observable."
            ),
            downgrade_reasons=downgrade_reasons,
            is_realtime_authoritative=False,
            is_fresh=False,
            is_delayed=True,
            is_partial=False,
            is_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 5: partially_observable — some channels active but not all
    # ------------------------------------------------------------------
    _some_active_evidence = any([
        evidence.realtime_channel_confirmed,
        evidence.freshness_within_window,
        evidence.evidence_lag_known,
    ])

    if not evidence.all_required_channels_active and _some_active_evidence:
        return TelemetryFreshnessVerdict(
            freshness_class=TelemetryFreshnessClass.partially_observable,
            rationale=(
                "At least one required telemetry channel is missing or silent.  "
                "System state cannot be fully observed from available data.  "
                "PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_POLICY prevents "
                "promotion to realtime_authoritative or fresh_not_realtime.  "
                "Classification is partially_observable: incomplete coverage."
            ),
            downgrade_reasons=downgrade_reasons,
            is_realtime_authoritative=False,
            is_fresh=False,
            is_delayed=False,
            is_partial=True,
            is_unreliable=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 6: fail-conservative default → telemetry_unreliable
    # ------------------------------------------------------------------
    if not downgrade_reasons:
        downgrade_reasons.append(
            "No positive telemetry evidence; "
            "TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY applied."
        )
    return TelemetryFreshnessVerdict(
        freshness_class=TelemetryFreshnessClass.telemetry_unreliable,
        rationale=(
            "No sufficient combination of channel confirmation, freshness, "
            "delivery path authority, or coverage evidence was present.  "
            "Defaulting to telemetry_unreliable per fail-conservative policy.  "
            "TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY applied."
        ),
        downgrade_reasons=downgrade_reasons,
        is_realtime_authoritative=False,
        is_fresh=False,
        is_delayed=False,
        is_partial=False,
        is_unreliable=True,
        participant_id=evidence.participant_id,
        evidence_present=_any_evidence,
        trace_id=evidence.trace_id,
    )


# ---------------------------------------------------------------------------
# Public convenience wrappers
# ---------------------------------------------------------------------------


def build_telemetry_freshness_verdict(
    evidence: TelemetryFreshnessEvidence,
) -> TelemetryFreshnessVerdict:
    """Convenience wrapper around :func:`classify_telemetry_freshness`.

    Equivalent to calling ``classify_telemetry_freshness(evidence)`` directly.
    Provided for naming symmetry with other taxonomy modules in the system.
    """
    return classify_telemetry_freshness(evidence)


def build_baseline_telemetry_freshness_verdict() -> TelemetryFreshnessVerdict:
    """Return the baseline (zero-evidence) telemetry freshness verdict.

    This is the honest starting state for a process instance that has not
    yet received any telemetry or observability evidence.  The verdict will
    be ``telemetry_unreliable`` with an appropriate rationale.

    Used by the acceptance evaluator to confirm the contract is wired and
    conservatively defaults rather than optimistically assuming real-time
    authoritative observability.
    """
    evidence = TelemetryFreshnessEvidence()
    return classify_telemetry_freshness(evidence)
