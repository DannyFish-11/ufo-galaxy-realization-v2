#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_utilization_observability.py
=============================================
PR-531: Capability Utilization Observability — Practical Observability
Foundations for Capability and Node Utilization.

This module establishes **practical observability foundations** for tracking
which capabilities/nodes are actually used, how often they fail, and what
operational value they provide.  This is not a full analytics platform; the
goal is to create actionable observability that supports future governance
and promotion decisions.

Problem addressed
-----------------
After PRs #506–#530 the capability/node execution pipeline is well-governed
internally.  However, there is insufficient visibility into:

- Which capabilities/nodes are actually called in production.
- Which tool calls fail most often (and with what failure domain).
- Which capabilities are called rarely and may be candidates for demotion.
- Which capabilities are called frequently and may be candidates for promotion
  from OPTIONAL/EXPERIMENTAL to ACTIVE.

This module provides:

1. **CapabilityCallRecord** — lightweight record of a single capability/node
   invocation: tool name, caller, latency, success/failure, failure domain.

2. **UtilizationReport** — aggregated per-capability metrics: call count,
   success rate, failure count, average latency, last-call timestamp.

3. **CapabilityUtilizationObservability** — singleton that maintains a ring
   buffer of call records and computes utilization reports on demand.

4. **record_capability_call() / record_failure()** — lightweight hooks that
   existing dispatch paths can call to feed the observability layer without
   coupling to a full analytics stack.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  GOVERNANCE / PROMOTION DECISION LAYER                          │
    │  node_lifecycle_governor  ·  operator_surface                   │
    └────────────────────────────┬─────────────────────────────────────┘
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  CAPABILITY UTILIZATION OBSERVABILITY  (this module, Layer 15)  │
    │                                                                  │
    │  record_capability_call() — hook called by dispatch paths       │
    │  record_failure() — hook called on tool/node failure            │
    │  get_utilization_report() → UtilizationReport per capability    │
    │  get_all_utilization_reports() → full utilization summary       │
    └──────────────────────────────────────────────────────────────────┘

Public API
----------
Authority sentinels::

    CAPABILITY_UTILIZATION_OBSERVABILITY_AUTHORITY
    CAPABILITY_UTILIZATION_OBSERVABILITY_LAYER_POSITION
    CAPABILITY_UTILIZATION_FOUNDATIONS_ESTABLISHED

Policy sentinels::

    OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY
    UTILIZATION_DATA_IS_ADVISORY_POLICY

Dataclasses::

    CapabilityCallRecord
    UtilizationReport
    UtilizationSummary

Class::

    CapabilityUtilizationObservability
    get_capability_utilization_observability()
    reset_capability_utilization_observability()

Helpers::

    record_capability_call(tool_name, ...) -> None
    record_failure(tool_name, ...) -> None
    get_utilization_report(tool_name) -> Optional[UtilizationReport]
    get_all_utilization_reports() -> UtilizationSummary
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.CapabilityUtilizationObservability")

# ===========================================================================
# Authority sentinels
# ===========================================================================

CAPABILITY_UTILIZATION_OBSERVABILITY_AUTHORITY: str = (
    "CAPABILITY_UTILIZATION_OBSERVABILITY::PR531_UTILIZATION_OBSERVABILITY_V1: "
    "core/capability_utilization_observability.py establishes practical "
    "observability foundations for capability and node utilization.  Layer 15.  "
    "This module provides call-record tracking and utilization reports for "
    "governance and promotion decisions."
)

CAPABILITY_UTILIZATION_OBSERVABILITY_LAYER_POSITION: int = 15

CAPABILITY_UTILIZATION_FOUNDATIONS_ESTABLISHED: str = (
    "CAPABILITY_UTILIZATION_FOUNDATIONS_V1: "
    "CapabilityUtilizationObservability is the canonical observability entry "
    "point for capability/node utilization.  Call record_capability_call() "
    "from dispatch paths to feed observability data."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY: str = (
    "OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_V1: "
    "All calls to record_capability_call() and record_failure() are "
    "fire-and-forget.  They MUST NOT raise exceptions or block the dispatch "
    "path.  Observability failures are logged at DEBUG level only."
)

UTILIZATION_DATA_IS_ADVISORY_POLICY: str = (
    "UTILIZATION_DATA_IS_ADVISORY_V1: "
    "Utilization reports are advisory data for governance and promotion "
    "decisions.  They do not constitute runtime truth and must not be used "
    "to gate or block dispatch paths."
)

# ===========================================================================
# Dataclasses
# ===========================================================================

_DEFAULT_RING_SIZE = 1024


@dataclass
class CapabilityCallRecord:
    """A single capability/node invocation record."""

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    """Canonical tool/capability name (e.g. ``'node::Node_001::schedule'``)."""

    caller: str = ""
    """Calling context identifier (e.g. ``'OpenClawd'``, ``'CanonicalDispatcher'``)."""

    success: bool = True
    """Whether the call completed successfully."""

    failure_domain: Optional[str] = None
    """Failure domain if ``success=False`` (e.g. ``'NODE_UNAVAILABLE'``)."""

    latency_ms: float = 0.0
    """Call latency in milliseconds."""

    called_at: float = field(default_factory=time.time)

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UtilizationReport:
    """Aggregated utilization metrics for a single capability/node."""

    tool_name: str
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0

    first_call_at: Optional[float] = None
    last_call_at: Optional[float] = None

    failure_domains: Dict[str, int] = field(default_factory=dict)
    """Count of failures per failure domain."""

    @property
    def success_rate(self) -> float:
        """Success rate as a fraction [0.0 – 1.0]."""
        if self.total_calls == 0:
            return 0.0
        return self.success_count / self.total_calls

    @property
    def failure_rate(self) -> float:
        """Failure rate as a fraction [0.0 – 1.0]."""
        return 1.0 - self.success_rate

    @property
    def average_latency_ms(self) -> float:
        """Average call latency in milliseconds."""
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "average_latency_ms": round(self.average_latency_ms, 2),
            "first_call_at": self.first_call_at,
            "last_call_at": self.last_call_at,
            "failure_domains": self.failure_domains,
        }


@dataclass
class UtilizationSummary:
    """Full utilization summary across all tracked capabilities."""

    authority: str = CAPABILITY_UTILIZATION_OBSERVABILITY_AUTHORITY
    summary_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    compiled_at: float = field(default_factory=time.time)

    total_tracked_capabilities: int = 0
    total_calls_recorded: int = 0
    total_failures_recorded: int = 0

    reports: List[UtilizationReport] = field(default_factory=list)

    most_called: Optional[str] = None
    most_failing: Optional[str] = None
    least_called: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "summary_id": self.summary_id,
            "compiled_at": self.compiled_at,
            "total_tracked_capabilities": self.total_tracked_capabilities,
            "total_calls_recorded": self.total_calls_recorded,
            "total_failures_recorded": self.total_failures_recorded,
            "most_called": self.most_called,
            "most_failing": self.most_failing,
            "least_called": self.least_called,
            "reports": [r.to_dict() for r in self.reports],
        }


# ===========================================================================
# Singleton
# ===========================================================================


class CapabilityUtilizationObservability:
    """Process-level singleton for capability/node utilization observability.

    Maintains a fixed-size ring buffer of :class:`CapabilityCallRecord` objects
    and computes :class:`UtilizationReport` aggregates on demand.

    All write operations are thread-safe and non-blocking.  Read operations
    acquire a shared lock briefly to produce a consistent snapshot.
    """

    _instance: Optional["CapabilityUtilizationObservability"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self, ring_size: int = _DEFAULT_RING_SIZE) -> None:
        self._ring: Deque[CapabilityCallRecord] = deque(maxlen=ring_size)
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "CapabilityUtilizationObservability":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — **for testing only**."""
        with cls._class_lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def record_call(
        self,
        tool_name: str,
        *,
        caller: str = "",
        success: bool = True,
        failure_domain: Optional[str] = None,
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a capability invocation.

        This method is fire-and-forget per
        :data:`OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY`.  It will not
        raise even if internal state is corrupted.
        """
        try:
            rec = CapabilityCallRecord(
                tool_name=tool_name,
                caller=caller,
                success=success,
                failure_domain=failure_domain,
                latency_ms=latency_ms,
                metadata=metadata or {},
            )
            with self._lock:
                self._ring.append(rec)
        except Exception as exc:
            logger.debug("record_call: suppressed error: %s", exc)

    def record_failure(
        self,
        tool_name: str,
        *,
        caller: str = "",
        failure_domain: str = "UNKNOWN",
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a capability failure.

        Convenience wrapper around :meth:`record_call` with ``success=False``.
        """
        self.record_call(
            tool_name,
            caller=caller,
            success=False,
            failure_domain=failure_domain,
            latency_ms=latency_ms,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def get_utilization_report(self, tool_name: str) -> Optional[UtilizationReport]:
        """Return a :class:`UtilizationReport` for *tool_name*, or ``None``."""
        with self._lock:
            records = [r for r in self._ring if r.tool_name == tool_name]
        if not records:
            return None
        return self._build_report(tool_name, records)

    def get_all_utilization_reports(self) -> UtilizationSummary:
        """Return a :class:`UtilizationSummary` across all tracked capabilities."""
        with self._lock:
            all_records = list(self._ring)

        # Group by tool_name
        by_tool: Dict[str, List[CapabilityCallRecord]] = defaultdict(list)
        for rec in all_records:
            by_tool[rec.tool_name].append(rec)

        reports = [
            self._build_report(tool_name, recs)
            for tool_name, recs in by_tool.items()
        ]
        reports.sort(key=lambda r: r.total_calls, reverse=True)

        total_calls = sum(r.total_calls for r in reports)
        total_failures = sum(r.failure_count for r in reports)

        most_called = reports[0].tool_name if reports else None
        most_failing = (
            max(reports, key=lambda r: r.failure_count).tool_name
            if any(r.failure_count > 0 for r in reports)
            else None
        )
        least_called = reports[-1].tool_name if reports else None

        return UtilizationSummary(
            total_tracked_capabilities=len(reports),
            total_calls_recorded=total_calls,
            total_failures_recorded=total_failures,
            reports=reports,
            most_called=most_called,
            most_failing=most_failing,
            least_called=least_called,
        )

    def list_records(self) -> List[CapabilityCallRecord]:
        """Return a snapshot copy of all buffered call records."""
        with self._lock:
            return list(self._ring)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_report(
        tool_name: str, records: List[CapabilityCallRecord]
    ) -> UtilizationReport:
        report = UtilizationReport(tool_name=tool_name)
        failure_domains: Dict[str, int] = defaultdict(int)
        for rec in records:
            report.total_calls += 1
            if rec.success:
                report.success_count += 1
            else:
                report.failure_count += 1
                if rec.failure_domain:
                    failure_domains[rec.failure_domain] += 1
            report.total_latency_ms += rec.latency_ms
            if report.first_call_at is None or rec.called_at < report.first_call_at:
                report.first_call_at = rec.called_at
            if report.last_call_at is None or rec.called_at > report.last_call_at:
                report.last_call_at = rec.called_at
        report.failure_domains = dict(failure_domains)
        return report


# ===========================================================================
# Module-level helpers
# ===========================================================================


def get_capability_utilization_observability() -> CapabilityUtilizationObservability:
    """Return the process-level singleton."""
    return CapabilityUtilizationObservability.get_instance()


def reset_capability_utilization_observability() -> None:
    """Reset the singleton — **for testing only**."""
    CapabilityUtilizationObservability.reset()


def record_capability_call(
    tool_name: str,
    *,
    caller: str = "",
    success: bool = True,
    failure_domain: Optional[str] = None,
    latency_ms: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a capability invocation in the observability ring buffer.

    This is the **primary write hook** for dispatch paths.  It is
    fire-and-forget per :data:`OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY`.

    Parameters
    ----------
    tool_name:
        Canonical tool/capability name.
    caller:
        Calling context identifier.
    success:
        Whether the invocation succeeded.
    failure_domain:
        Failure domain if ``success=False``.
    latency_ms:
        Call latency in milliseconds.
    metadata:
        Optional additional metadata (not indexed; stored for replay only).
    """
    try:
        get_capability_utilization_observability().record_call(
            tool_name,
            caller=caller,
            success=success,
            failure_domain=failure_domain,
            latency_ms=latency_ms,
            metadata=metadata,
        )
    except Exception as exc:
        logger.debug("record_capability_call: suppressed error: %s", exc)


def record_failure(
    tool_name: str,
    *,
    caller: str = "",
    failure_domain: str = "UNKNOWN",
    latency_ms: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a capability failure.

    Convenience wrapper for :func:`record_capability_call` with
    ``success=False``.
    """
    record_capability_call(
        tool_name,
        caller=caller,
        success=False,
        failure_domain=failure_domain,
        latency_ms=latency_ms,
        metadata=metadata,
    )


def get_utilization_report(tool_name: str) -> Optional[UtilizationReport]:
    """Return a utilization report for *tool_name*, or ``None`` if no calls recorded."""
    return get_capability_utilization_observability().get_utilization_report(tool_name)


def get_all_utilization_reports() -> UtilizationSummary:
    """Return a full utilization summary across all tracked capabilities."""
    return get_capability_utilization_observability().get_all_utilization_reports()
