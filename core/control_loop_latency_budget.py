#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.control_loop_latency_budget — Control-Loop Latency Budgets (PR-30)

**Unified-Subject Architecture — Latency Budget Awareness**
------------------------------------------------------------
This module introduces explicit latency-budget awareness and related
throttling/coalescing/fast-path strategies for the control loop, covering:

- **Ingest cadence controls** — rate-limit multimodal ingestion calls so that
  continuous perception updates do not overwhelm the control loop.
- **Control-plan recompute throttling / coalescing** — prevent unnecessary
  rebuilding of the unified control plan during rapid source or state churn.
- **Projection refresh budgeting** — reduce shell-facing update churn without
  sacrificing coherence.
- **Provider-selection latency budgeting** — cap provider-selection overhead and
  short-circuit when the perceived state has not changed.
- **Text-only fast paths** — when a request clearly does not require multimodal
  handling, skip the full multimodal stack to reduce overhead.
- **Structured latency accounting** — optional, serialisable latency-budget
  summary that can feed observability without coupling tightly to a dashboard.

Architecture
------------

Authority boundaries are preserved:

- The **runtime shell** (``DesktopPresenceRuntime``) remains the authority for
  source/session facts and shell-facing status projection.
- **OpenClawd core** remains the authority for routing and execution decisions.
  This module merely makes the *cadence* of those decisions more efficient.
- **Projection/diagnostics layers** consume the resulting
  :class:`LatencyBudgetSummary` without inventing their own budget semantics.

Public structures
-----------------
:class:`IngestCadencePolicy`
    Policy vocabulary for ingest-cadence decisions.

:class:`RecomputePolicy`
    Policy vocabulary for control-plan recompute decisions.

:class:`ProjectionRefreshPolicy`
    Policy vocabulary for projection-refresh decisions.

:class:`ModalityFastPathKind`
    Classification of whether a fast path applies to the current request.

:class:`IngestCadenceWindow`
    Stateful sliding window for ingest cadence control.

:class:`RecomputeWindow`
    Stateful sliding window for control-plan recompute throttling.

:class:`ProjectionRefreshWindow`
    Stateful sliding window for projection refresh budgeting.

:class:`ProviderSelectionBudget`
    Per-request latency budget for provider selection.

:class:`TextOnlyFastPathAssessment`
    Result of fast-path eligibility assessment for a single request.

:class:`LatencyBudgetSummary`
    Point-in-time, JSON-serialisable summary of all budget decisions for a
    single control-loop iteration.

:class:`ControlLoopLatencyBudget`
    Top-level stateful coordinator that owns all sub-windows and fast-path
    logic.  Designed for singleton use via
    :func:`get_control_loop_latency_budget`.

Public helpers
--------------
:func:`assess_text_only_fast_path`
    Assess whether a request is text-only and eligible for a lightweight path.

:func:`build_latency_budget_summary`
    Compose a :class:`LatencyBudgetSummary` from per-request budget decisions.

:func:`get_control_loop_latency_budget`
    Return the global :class:`ControlLoopLatencyBudget` singleton.

:func:`reset_latency_budget`
    Reset the global singleton (primarily for tests).

Serialisation
-------------
All public dataclasses expose ``to_dict()`` / ``from_dict()`` round-trip
methods.  All stored values are plain Python primitives (str, int, float,
bool, list, dict) so that ``json.dumps(obj.to_dict())`` always succeeds.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Policy Enums
# ---------------------------------------------------------------------------


class IngestCadencePolicy(str, Enum):
    """Ingest cadence policy applied to a multimodal ingestion call.

    Values are lowercase strings safe for serialisation and policy analysis.
    """

    ALLOWED = "allowed"
    """The ingest call is within the cadence budget and proceeds normally."""

    THROTTLED = "throttled"
    """Too many ingest calls in the current window; this call is deferred or
    coalesced with the next scheduled ingest cycle."""

    SKIPPED_TEXT_ONLY = "skipped_text_only"
    """No multimodal context is present; ingest is skipped on the fast path."""

    UNKNOWN = "unknown"
    """Cannot determine policy — safe default; ingest proceeds normally."""

    @classmethod
    def from_string(cls, value: str) -> "IngestCadencePolicy":
        """Return the enum member matching *value* or :attr:`UNKNOWN`."""
        _v = (value or "").strip().lower()
        for member in cls:
            if member.value == _v:
                return member
        return cls.UNKNOWN


class RecomputePolicy(str, Enum):
    """Policy applied to a control-plan recompute decision."""

    FULL = "full"
    """Full recomputation proceeds — perception or model-supply state has
    changed beyond the coalescing threshold."""

    COALESCED = "coalesced"
    """Recomputation is coalesced — a recent recompute is still fresh; the
    previous canonical control plan is reused without modification."""

    DEFERRED = "deferred"
    """Recomputation is deferred — rapid churn is detected; recompute is
    scheduled at the end of the churn window."""

    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "RecomputePolicy":
        _v = (value or "").strip().lower()
        for member in cls:
            if member.value == _v:
                return member
        return cls.UNKNOWN


class ProjectionRefreshPolicy(str, Enum):
    """Policy applied to a shell-facing projection refresh decision."""

    IMMEDIATE = "immediate"
    """Refresh proceeds immediately — budget allows it."""

    COALESCED = "coalesced"
    """Refresh is coalesced with the next scheduled update window to reduce
    churn without losing coherence."""

    SUPPRESSED = "suppressed"
    """Refresh is suppressed — state has not changed since the last update;
    emitting would produce a duplicate."""

    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "ProjectionRefreshPolicy":
        _v = (value or "").strip().lower()
        for member in cls:
            if member.value == _v:
                return member
        return cls.UNKNOWN


class ModalityFastPathKind(str, Enum):
    """Classification of whether a text-only fast path applies."""

    TEXT_ONLY = "text_only"
    """Request is text-only; multimodal stack overhead can be avoided."""

    MULTIMODAL_REQUIRED = "multimodal_required"
    """Request requires multimodal handling; full stack applies."""

    AMBIGUOUS = "ambiguous"
    """Cannot determine modality from available context; full stack is
    used conservatively."""

    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "ModalityFastPathKind":
        _v = (value or "").strip().lower()
        for member in cls:
            if member.value == _v:
                return member
        return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IngestCadenceWindow:
    """Sliding window state for ingest cadence control.

    Tracks the number of ingest calls within a rolling time window and
    determines whether a new call should be allowed, throttled, or skipped.
    """

    window_seconds: float = 1.0
    """Width of the rolling cadence window in seconds."""

    max_calls_per_window: int = 5
    """Maximum ingest calls allowed within *window_seconds*."""

    call_timestamps: List[float] = field(default_factory=list)
    """Monotonic timestamps of recent ingest calls (internal state)."""

    total_allowed: int = 0
    total_throttled: int = 0
    total_skipped_text_only: int = 0

    def record(self, allowed: bool, text_only: bool = False) -> None:
        """Record one ingest decision into the window state."""
        now = time.monotonic()
        # Prune stale entries
        cutoff = now - self.window_seconds
        self.call_timestamps = [t for t in self.call_timestamps if t >= cutoff]
        if text_only:
            self.total_skipped_text_only += 1
        elif allowed:
            self.call_timestamps.append(now)
            self.total_allowed += 1
        else:
            self.total_throttled += 1

    def should_allow(self) -> bool:
        """Return True if the next ingest call is within budget."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        active = [t for t in self.call_timestamps if t >= cutoff]
        return len(active) < self.max_calls_per_window

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_seconds": self.window_seconds,
            "max_calls_per_window": self.max_calls_per_window,
            "total_allowed": self.total_allowed,
            "total_throttled": self.total_throttled,
            "total_skipped_text_only": self.total_skipped_text_only,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IngestCadenceWindow":
        return cls(
            window_seconds=float(d.get("window_seconds", 1.0)),
            max_calls_per_window=int(d.get("max_calls_per_window", 5)),
            total_allowed=int(d.get("total_allowed", 0)),
            total_throttled=int(d.get("total_throttled", 0)),
            total_skipped_text_only=int(d.get("total_skipped_text_only", 0)),
        )


@dataclass
class RecomputeWindow:
    """Sliding window state for control-plan recompute throttling / coalescing.

    Prevents full control-plan rebuilds during rapid source or state churn by
    coalescing requests that arrive within a minimum inter-recompute interval.
    """

    min_interval_seconds: float = 0.05
    """Minimum time between full recomputes in seconds (50 ms default)."""

    churn_window_seconds: float = 0.2
    """If more than *churn_threshold_calls* recompute requests arrive within
    this window, recompute is deferred until the window drains."""

    churn_threshold_calls: int = 10
    """Number of recompute requests within *churn_window_seconds* that
    triggers deferral."""

    _last_recompute_ts: float = field(default=0.0, repr=False)
    _recent_request_ts: List[float] = field(default_factory=list, repr=False)

    total_full: int = 0
    total_coalesced: int = 0
    total_deferred: int = 0

    def decide(self) -> RecomputePolicy:
        """Return the recompute policy that should apply right now."""
        now = time.monotonic()
        cutoff = now - self.churn_window_seconds
        self._recent_request_ts = [t for t in self._recent_request_ts if t >= cutoff]
        self._recent_request_ts.append(now)

        # Churn detection: too many requests in the churn window → defer
        if len(self._recent_request_ts) > self.churn_threshold_calls:
            self.total_deferred += 1
            return RecomputePolicy.DEFERRED

        # Freshness gate: last recompute was very recent → coalesce
        if (now - self._last_recompute_ts) < self.min_interval_seconds:
            self.total_coalesced += 1
            return RecomputePolicy.COALESCED

        # Full recompute is warranted
        self._last_recompute_ts = now
        self.total_full += 1
        return RecomputePolicy.FULL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_interval_seconds": self.min_interval_seconds,
            "churn_window_seconds": self.churn_window_seconds,
            "churn_threshold_calls": self.churn_threshold_calls,
            "total_full": self.total_full,
            "total_coalesced": self.total_coalesced,
            "total_deferred": self.total_deferred,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RecomputeWindow":
        return cls(
            min_interval_seconds=float(d.get("min_interval_seconds", 0.05)),
            churn_window_seconds=float(d.get("churn_window_seconds", 0.2)),
            churn_threshold_calls=int(d.get("churn_threshold_calls", 10)),
            total_full=int(d.get("total_full", 0)),
            total_coalesced=int(d.get("total_coalesced", 0)),
            total_deferred=int(d.get("total_deferred", 0)),
        )


@dataclass
class ProjectionRefreshWindow:
    """Sliding window state for projection / status refresh budgeting.

    Coalesces shell-facing updates to avoid excessive churn while preserving
    coherence: a refresh is only suppressed when state is genuinely unchanged.
    """

    min_interval_seconds: float = 0.1
    """Minimum time between projection refreshes in seconds (100 ms default)."""

    _last_refresh_ts: float = field(default=0.0, repr=False)
    _last_state_fingerprint: Optional[str] = field(default=None, repr=False)

    total_immediate: int = 0
    total_coalesced: int = 0
    total_suppressed: int = 0

    def decide(self, state_fingerprint: Optional[str] = None) -> ProjectionRefreshPolicy:
        """Return the refresh policy for a new projection update.

        Parameters
        ----------
        state_fingerprint:
            A short string uniquely identifying the current state (e.g. a hash
            of the projection payload).  If identical to the last seen
            fingerprint *and* within the minimum interval, the refresh is
            suppressed.
        """
        now = time.monotonic()
        elapsed = now - self._last_refresh_ts

        # Suppress: within interval AND state unchanged
        if (
            elapsed < self.min_interval_seconds
            and state_fingerprint is not None
            and state_fingerprint == self._last_state_fingerprint
        ):
            self.total_suppressed += 1
            return ProjectionRefreshPolicy.SUPPRESSED

        # Coalesce: within minimum interval but state has changed
        if elapsed < self.min_interval_seconds:
            self.total_coalesced += 1
            return ProjectionRefreshPolicy.COALESCED

        # Immediate: enough time has passed
        self._last_refresh_ts = now
        self._last_state_fingerprint = state_fingerprint
        self.total_immediate += 1
        return ProjectionRefreshPolicy.IMMEDIATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_interval_seconds": self.min_interval_seconds,
            "total_immediate": self.total_immediate,
            "total_coalesced": self.total_coalesced,
            "total_suppressed": self.total_suppressed,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProjectionRefreshWindow":
        return cls(
            min_interval_seconds=float(d.get("min_interval_seconds", 0.1)),
            total_immediate=int(d.get("total_immediate", 0)),
            total_coalesced=int(d.get("total_coalesced", 0)),
            total_suppressed=int(d.get("total_suppressed", 0)),
        )


@dataclass
class ProviderSelectionBudget:
    """Per-request latency budget record for provider/model selection.

    Captures the measured overhead of the provider-selection step and flags
    whether it exceeded the configured budget ceiling.
    """

    budget_ms: float = 20.0
    """Maximum acceptable provider-selection latency in milliseconds."""

    measured_ms: float = 0.0
    """Actual measured provider-selection latency for this request."""

    exceeded: bool = False
    """True when *measured_ms* > *budget_ms*."""

    route_type: str = "unknown"
    """The route tier that was selected (e.g. ``native_multimodal``,
    ``text_only``, ``advisory``)."""

    fast_path_applied: bool = False
    """True when the text-only fast path was applied, skipping full
    provider-selection logic."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget_ms": self.budget_ms,
            "measured_ms": self.measured_ms,
            "exceeded": self.exceeded,
            "route_type": self.route_type,
            "fast_path_applied": self.fast_path_applied,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProviderSelectionBudget":
        return cls(
            budget_ms=float(d.get("budget_ms", 20.0)),
            measured_ms=float(d.get("measured_ms", 0.0)),
            exceeded=bool(d.get("exceeded", False)),
            route_type=str(d.get("route_type", "unknown")),
            fast_path_applied=bool(d.get("fast_path_applied", False)),
        )


@dataclass
class TextOnlyFastPathAssessment:
    """Result of fast-path eligibility assessment for a single request.

    A request qualifies for the text-only fast path when it carries no
    multimodal context, the canonical perception state contains no active
    non-text modalities, and no source-registry entry signals active
    audio/video capture.
    """

    fast_path_kind: ModalityFastPathKind = ModalityFastPathKind.UNKNOWN
    """Classification of this request's fast-path status."""

    is_text_only: bool = False
    """Shorthand: True iff *fast_path_kind* is :attr:`ModalityFastPathKind.TEXT_ONLY`."""

    reason: str = ""
    """Human-readable explanation of the classification."""

    active_modalities: List[str] = field(default_factory=list)
    """Non-text modalities detected in the canonical perception state, if any."""

    has_multimodal_context: bool = False
    """True when an explicit multimodal context payload was supplied."""

    assessment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique ID for this assessment (for tracing)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fast_path_kind": self.fast_path_kind.value,
            "is_text_only": self.is_text_only,
            "reason": self.reason,
            "active_modalities": list(self.active_modalities),
            "has_multimodal_context": self.has_multimodal_context,
            "assessment_id": self.assessment_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TextOnlyFastPathAssessment":
        return cls(
            fast_path_kind=ModalityFastPathKind.from_string(d.get("fast_path_kind", "unknown")),
            is_text_only=bool(d.get("is_text_only", False)),
            reason=str(d.get("reason", "")),
            active_modalities=list(d.get("active_modalities", [])),
            has_multimodal_context=bool(d.get("has_multimodal_context", False)),
            assessment_id=str(d.get("assessment_id", str(uuid.uuid4()))),
        )


@dataclass
class LatencyBudgetSummary:
    """Point-in-time, JSON-serialisable summary of all latency-budget decisions
    for a single control-loop iteration.

    This is the primary artifact consumed by projection and observability layers.
    It captures all budget decisions without coupling to a dashboard
    implementation: consumers may log it, forward it to a metrics endpoint, or
    embed it in the response metadata.
    """

    summary_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this summary (UUID4)."""

    timestamp: float = field(default_factory=time.time)
    """Wall-clock timestamp when this summary was built (Unix seconds)."""

    trace_id: str = ""
    """Trace ID of the originating control-loop request."""

    runtime_session_id: str = ""
    """Runtime session ID of the originating request, if available."""

    # ── Ingest cadence ───────────────────────────────────────────────────────
    ingest_cadence_policy: str = IngestCadencePolicy.UNKNOWN.value
    """Applied ingest cadence policy for this iteration."""

    # ── Recompute throttling ─────────────────────────────────────────────────
    recompute_policy: str = RecomputePolicy.UNKNOWN.value
    """Applied control-plan recompute policy for this iteration."""

    # ── Projection refresh ───────────────────────────────────────────────────
    projection_refresh_policy: str = ProjectionRefreshPolicy.UNKNOWN.value
    """Applied projection refresh policy for this iteration."""

    # ── Provider selection latency ───────────────────────────────────────────
    provider_selection_budget: Optional[Dict[str, Any]] = None
    """Serialised :class:`ProviderSelectionBudget` for this iteration."""

    # ── Text-only fast path ──────────────────────────────────────────────────
    text_only_fast_path: Optional[Dict[str, Any]] = None
    """Serialised :class:`TextOnlyFastPathAssessment` for this iteration."""

    # ── Aggregate window stats (snapshot) ───────────────────────────────────
    ingest_window_stats: Optional[Dict[str, Any]] = None
    """Snapshot of :class:`IngestCadenceWindow` counters."""

    recompute_window_stats: Optional[Dict[str, Any]] = None
    """Snapshot of :class:`RecomputeWindow` counters."""

    projection_window_stats: Optional[Dict[str, Any]] = None
    """Snapshot of :class:`ProjectionRefreshWindow` counters."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "ingest_cadence_policy": self.ingest_cadence_policy,
            "recompute_policy": self.recompute_policy,
            "projection_refresh_policy": self.projection_refresh_policy,
            "provider_selection_budget": self.provider_selection_budget,
            "text_only_fast_path": self.text_only_fast_path,
            "ingest_window_stats": self.ingest_window_stats,
            "recompute_window_stats": self.recompute_window_stats,
            "projection_window_stats": self.projection_window_stats,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LatencyBudgetSummary":
        return cls(
            summary_id=str(d.get("summary_id", str(uuid.uuid4()))),
            timestamp=float(d.get("timestamp", time.time())),
            trace_id=str(d.get("trace_id", "")),
            runtime_session_id=str(d.get("runtime_session_id", "")),
            ingest_cadence_policy=str(d.get("ingest_cadence_policy", IngestCadencePolicy.UNKNOWN.value)),
            recompute_policy=str(d.get("recompute_policy", RecomputePolicy.UNKNOWN.value)),
            projection_refresh_policy=str(d.get("projection_refresh_policy", ProjectionRefreshPolicy.UNKNOWN.value)),
            provider_selection_budget=d.get("provider_selection_budget"),
            text_only_fast_path=d.get("text_only_fast_path"),
            ingest_window_stats=d.get("ingest_window_stats"),
            recompute_window_stats=d.get("recompute_window_stats"),
            projection_window_stats=d.get("projection_window_stats"),
        )


# ---------------------------------------------------------------------------
# ControlLoopLatencyBudget — stateful singleton coordinator
# ---------------------------------------------------------------------------


class ControlLoopLatencyBudget:
    """Top-level stateful coordinator for all control-loop latency budgets.

    Owns :class:`IngestCadenceWindow`, :class:`RecomputeWindow`, and
    :class:`ProjectionRefreshWindow` and applies them per iteration.

    Designed for singleton use via :func:`get_control_loop_latency_budget`.
    All public methods are thread-safe.
    """

    def __init__(
        self,
        *,
        ingest_window_seconds: float = 1.0,
        ingest_max_calls: int = 5,
        recompute_min_interval_seconds: float = 0.05,
        recompute_churn_window_seconds: float = 0.2,
        recompute_churn_threshold: int = 10,
        projection_min_interval_seconds: float = 0.1,
        provider_selection_budget_ms: float = 20.0,
    ) -> None:
        self._lock = threading.Lock()
        self._ingest = IngestCadenceWindow(
            window_seconds=ingest_window_seconds,
            max_calls_per_window=ingest_max_calls,
        )
        self._recompute = RecomputeWindow(
            min_interval_seconds=recompute_min_interval_seconds,
            churn_window_seconds=recompute_churn_window_seconds,
            churn_threshold_calls=recompute_churn_threshold,
        )
        self._projection = ProjectionRefreshWindow(
            min_interval_seconds=projection_min_interval_seconds,
        )
        self._provider_budget_ms = provider_selection_budget_ms

    # ── Public API ────────────────────────────────────────────────────────────

    def decide_ingest_cadence(
        self,
        *,
        has_multimodal_context: bool,
        is_text_only: bool = False,
    ) -> IngestCadencePolicy:
        """Decide whether an ingest call is within budget.

        Parameters
        ----------
        has_multimodal_context:
            True when an explicit multimodal payload was supplied.
        is_text_only:
            True when the request has been assessed as text-only; ingest is
            skipped on the fast path.
        """
        with self._lock:
            if is_text_only or not has_multimodal_context:
                self._ingest.record(allowed=False, text_only=True)
                return IngestCadencePolicy.SKIPPED_TEXT_ONLY

            if self._ingest.should_allow():
                self._ingest.record(allowed=True)
                return IngestCadencePolicy.ALLOWED

            self._ingest.record(allowed=False, text_only=False)
            return IngestCadencePolicy.THROTTLED

    def decide_recompute(self) -> RecomputePolicy:
        """Decide whether a full control-plan recompute should proceed."""
        with self._lock:
            return self._recompute.decide()

    def decide_projection_refresh(
        self,
        state_fingerprint: Optional[str] = None,
    ) -> ProjectionRefreshPolicy:
        """Decide whether a projection refresh should proceed immediately.

        Parameters
        ----------
        state_fingerprint:
            Optional short string identifying the current projection state.
            Pass the same value across calls to enable suppression of
            duplicate refreshes.
        """
        with self._lock:
            return self._projection.decide(state_fingerprint=state_fingerprint)

    def record_provider_selection(
        self,
        measured_ms: float,
        route_type: str = "unknown",
        fast_path_applied: bool = False,
    ) -> ProviderSelectionBudget:
        """Record a provider-selection latency measurement.

        Returns a :class:`ProviderSelectionBudget` capturing whether the
        budget was exceeded.
        """
        with self._lock:
            return ProviderSelectionBudget(
                budget_ms=self._provider_budget_ms,
                measured_ms=measured_ms,
                exceeded=measured_ms > self._provider_budget_ms,
                route_type=route_type,
                fast_path_applied=fast_path_applied,
            )

    def snapshot_ingest_stats(self) -> Dict[str, Any]:
        with self._lock:
            return self._ingest.to_dict()

    def snapshot_recompute_stats(self) -> Dict[str, Any]:
        with self._lock:
            return self._recompute.to_dict()

    def snapshot_projection_stats(self) -> Dict[str, Any]:
        with self._lock:
            return self._projection.to_dict()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def assess_text_only_fast_path(
    multimodal_context: Any,
    canonical_perception: Optional[Dict[str, Any]],
    source_registry_snapshot: Optional[Dict[str, Any]] = None,
) -> TextOnlyFastPathAssessment:
    """Assess whether a request is text-only and eligible for a lightweight path.

    Parameters
    ----------
    multimodal_context:
        The raw multimodal context payload supplied to the control loop.
        ``None`` signals no multimodal content.
    canonical_perception:
        The canonical perception state dict (from PR-16).  Used to detect
        active non-text modalities.
    source_registry_snapshot:
        Optional source-registry snapshot (from PR-17).  Currently reserved
        for future fine-grained modality presence checks.

    Returns
    -------
    TextOnlyFastPathAssessment
        Always returns a valid assessment; never raises.
    """
    try:
        has_mm_context = multimodal_context is not None

        # Extract active modalities from canonical perception
        active_modalities: List[str] = []
        if canonical_perception:
            raw = canonical_perception.get("active_modalities") or []
            if isinstance(raw, (list, tuple)):
                active_modalities = [str(m) for m in raw if str(m).lower() != "text"]

        requires_native_mm = bool(
            canonical_perception.get("requires_native_multimodal", False)
            if canonical_perception
            else False
        )

        if not has_mm_context and not active_modalities and not requires_native_mm:
            return TextOnlyFastPathAssessment(
                fast_path_kind=ModalityFastPathKind.TEXT_ONLY,
                is_text_only=True,
                reason="no_multimodal_context_no_active_modalities",
                active_modalities=[],
                has_multimodal_context=False,
            )

        if has_mm_context or active_modalities or requires_native_mm:
            return TextOnlyFastPathAssessment(
                fast_path_kind=ModalityFastPathKind.MULTIMODAL_REQUIRED,
                is_text_only=False,
                reason="multimodal_context_or_active_modalities_detected",
                active_modalities=active_modalities,
                has_multimodal_context=has_mm_context,
            )

        return TextOnlyFastPathAssessment(
            fast_path_kind=ModalityFastPathKind.AMBIGUOUS,
            is_text_only=False,
            reason="ambiguous_modality_state",
            active_modalities=active_modalities,
            has_multimodal_context=has_mm_context,
        )
    except Exception:
        return TextOnlyFastPathAssessment(
            fast_path_kind=ModalityFastPathKind.UNKNOWN,
            is_text_only=False,
            reason="assessment_error",
        )


def build_latency_budget_summary(
    *,
    trace_id: str = "",
    runtime_session_id: str = "",
    ingest_cadence_policy: IngestCadencePolicy = IngestCadencePolicy.UNKNOWN,
    recompute_policy: RecomputePolicy = RecomputePolicy.UNKNOWN,
    projection_refresh_policy: ProjectionRefreshPolicy = ProjectionRefreshPolicy.UNKNOWN,
    provider_selection_budget: Optional[ProviderSelectionBudget] = None,
    text_only_fast_path: Optional[TextOnlyFastPathAssessment] = None,
    ingest_window_stats: Optional[Dict[str, Any]] = None,
    recompute_window_stats: Optional[Dict[str, Any]] = None,
    projection_window_stats: Optional[Dict[str, Any]] = None,
) -> LatencyBudgetSummary:
    """Compose a :class:`LatencyBudgetSummary` from per-request budget decisions.

    All parameters are optional; safe defaults are used for any missing value
    so that the summary is always well-formed and JSON-serialisable.

    Returns
    -------
    LatencyBudgetSummary
        Always returns a valid summary; never raises.
    """
    try:
        return LatencyBudgetSummary(
            trace_id=trace_id or "",
            runtime_session_id=runtime_session_id or "",
            ingest_cadence_policy=ingest_cadence_policy.value,
            recompute_policy=recompute_policy.value,
            projection_refresh_policy=projection_refresh_policy.value,
            provider_selection_budget=(
                provider_selection_budget.to_dict()
                if provider_selection_budget is not None
                else None
            ),
            text_only_fast_path=(
                text_only_fast_path.to_dict()
                if text_only_fast_path is not None
                else None
            ),
            ingest_window_stats=ingest_window_stats,
            recompute_window_stats=recompute_window_stats,
            projection_window_stats=projection_window_stats,
        )
    except Exception:
        return LatencyBudgetSummary(
            trace_id=trace_id or "",
            runtime_session_id=runtime_session_id or "",
        )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_budget_singleton: Optional[ControlLoopLatencyBudget] = None
_budget_lock = threading.Lock()


def get_control_loop_latency_budget() -> ControlLoopLatencyBudget:
    """Return the global :class:`ControlLoopLatencyBudget` singleton."""
    global _budget_singleton
    if _budget_singleton is None:
        with _budget_lock:
            if _budget_singleton is None:
                _budget_singleton = ControlLoopLatencyBudget()
    return _budget_singleton


def reset_latency_budget() -> None:
    """Reset the global singleton (primarily for tests)."""
    global _budget_singleton
    with _budget_lock:
        _budget_singleton = None
