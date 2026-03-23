#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/cross_device_execution_chain.py — Canonical Cross-Device Execution Chain (PR-7)

**Unified-Subject Architecture — Canonical Cross-Device Execution Chain**
--------------------------------------------------------------------------
This module establishes the **single canonical cross-device execution chain** for
the Galaxy runtime and provides the vocabulary for tracking, auditing, and
projecting its state.

Canonical Chain
---------------
::

    OpenClawd (routing authority)
        └─ CommandRouter (sole router for cross-device tasks)
              └─ TaskEnvelope / CommandEnvelope (serialisable task contract)
                    └─ Gateway substrate (execution plumbing only)
                          └─ Worker / Device / Node (executors only)
                                └─ ResultEnvelope (normalised result)
                                      └─ OpenClawd feedback
                                            └─ Projection / Audit / Memory backflow

Architecture ownership rules
-----------------------------
- **OpenClawd** owns routing authority — it is the sole decision-maker for
  whether a request goes cross-device and which chain step handles it.
- **CommandRouter** is the *sole router* for cross-device tasks.  No other
  module should perform independent cross-device dispatch.
- **Gateway substrate** is execution plumbing only.  It does not make planning
  or routing decisions.
- **Workers / Devices / Nodes** are executors only.  They receive
  ``TaskEnvelope`` / ``CommandEnvelope`` instructions; they do not plan.
- **ResultEnvelope** is the canonical result container.  All cross-device
  results must be normalised into a ``ResultEnvelope`` before being merged back
  into OpenClawd.
- **Memory backflow**, **projection**, and **audit** are all triggered by
  OpenClawd after it receives the ``ResultEnvelope`` — they are downstream
  consumers, not independent authorities.

Legacy paths
------------
Any code path that:
- allows the gateway to make routing decisions (``galaxy_gateway.orchestrator.*``),
- dispatches to a worker/device outside ``CommandRouter.route_envelope``, or
- returns results without normalising them into a ``ResultEnvelope``

is a **legacy compatibility path** and is formally demoted by this PR.  See
:mod:`core.orchestration_authority.legacy_paths` for the registry.

Public API
----------
:class:`CanonicalChainStep`
    Enum of the steps in the canonical cross-device execution chain.

:class:`ResultEnvelope`
    Normalised, serialisable result container for cross-device task results.

:class:`ChainExecutionRecord`
    Serialisable record of a single cross-device chain execution (one request
    through the canonical chain).

:class:`CrossDeviceChainSnapshot`
    Serialisable snapshot of the global chain singleton state.

:func:`build_result_envelope`
    Construct a :class:`ResultEnvelope` from a raw result dict.

:func:`build_chain_execution_record`
    Construct a :class:`ChainExecutionRecord` from execution signals.

:func:`record_chain_execution`
    Append a :class:`ChainExecutionRecord` to the global chain singleton and
    return the record.

:func:`build_cross_device_chain_snapshot`
    Build a :class:`CrossDeviceChainSnapshot` from the global singleton.

:func:`get_cross_device_chain`
    Return the global :class:`CrossDeviceChainSingleton`.

:func:`reset_cross_device_chain`
    Reset the global singleton (for testing).
"""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CrossDeviceExecutionChain")

__all__ = [
    "CanonicalChainStep",
    "CHAIN_STEP_AUTHORITIES",
    "ResultEnvelope",
    "ChainExecutionRecord",
    "CrossDeviceChainSnapshot",
    "build_result_envelope",
    "build_chain_execution_record",
    "record_chain_execution",
    "build_cross_device_chain_snapshot",
    "get_cross_device_chain",
    "reset_cross_device_chain",
]


# ---------------------------------------------------------------------------
# CanonicalChainStep
# ---------------------------------------------------------------------------


class CanonicalChainStep(str, Enum):
    """Ordered steps of the canonical cross-device execution chain.

    Each value corresponds to a distinct layer in the chain.  The chain must
    always be traversed in this order; skipping steps or reversing order
    indicates a legacy or non-canonical path.

    ``openclawd_dispatch``
        OpenClawd makes the routing authority decision and initiates dispatch.
        This is the *only* allowed entry-point for cross-device requests.

    ``command_router``
        CommandRouter receives the request and performs envelope construction,
        ACL enforcement, circuit-breaker, and transport selection.  This is the
        *sole* router for cross-device tasks.

    ``task_envelope``
        The request is serialised into a ``TaskEnvelope`` or
        ``CommandEnvelope``.  No planning decisions occur here — the envelope
        carries the intent forward.

    ``gateway_substrate``
        The Galaxy Gateway plumbing transports the envelope to the target
        device / node.  The gateway is *execution substrate only* and must not
        make routing decisions.

    ``worker_executor``
        The target worker / device / node executes the command.  Executors are
        instruction followers only; they do not plan.

    ``result_envelope``
        The raw execution result is normalised into a :class:`ResultEnvelope`
        for canonical backflow.

    ``openclawd_feedback``
        OpenClawd receives the ``ResultEnvelope``, updates its internal state,
        and triggers downstream consumers (projection, audit, memory backflow).
    """

    openclawd_dispatch = "openclawd_dispatch"
    command_router = "command_router"
    task_envelope = "task_envelope"
    gateway_substrate = "gateway_substrate"
    worker_executor = "worker_executor"
    result_envelope = "result_envelope"
    openclawd_feedback = "openclawd_feedback"


#: Mapping from each chain step to the module/class that owns authority at that step.
#: Used by diagnostics and contributor tooling to verify layer compliance.
CHAIN_STEP_AUTHORITIES: Dict[CanonicalChainStep, str] = {
    CanonicalChainStep.openclawd_dispatch: "core.openclawd.OpenClawd",
    CanonicalChainStep.command_router: "core.command_router.CommandRouter",
    CanonicalChainStep.task_envelope: "core.schemas.task_envelope.TaskEnvelope",
    CanonicalChainStep.gateway_substrate: "galaxy_gateway (substrate only)",
    CanonicalChainStep.worker_executor: "worker/device/node (executor only)",
    CanonicalChainStep.result_envelope: "core.cross_device_execution_chain.ResultEnvelope",
    CanonicalChainStep.openclawd_feedback: "core.openclawd.OpenClawd",
}

#: Ordered list of steps in the canonical execution chain.
CANONICAL_CHAIN_ORDER: List[CanonicalChainStep] = [
    CanonicalChainStep.openclawd_dispatch,
    CanonicalChainStep.command_router,
    CanonicalChainStep.task_envelope,
    CanonicalChainStep.gateway_substrate,
    CanonicalChainStep.worker_executor,
    CanonicalChainStep.result_envelope,
    CanonicalChainStep.openclawd_feedback,
]


# ---------------------------------------------------------------------------
# ResultEnvelope
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResultEnvelope:
    """Normalised, serialisable result container for cross-device task results.

    All cross-device execution results **must** be normalised into a
    ``ResultEnvelope`` before being merged back into OpenClawd.  This ensures:

    - Result backflow is consistent and tied to OpenClawd's metadata.
    - Projection, audit, and memory backflow receive a predictable structure.
    - Legacy paths that return raw dicts without normalisation are detectable.

    Attributes
    ----------
    result_id:
        Unique identifier for this result (UUID4 by default).
    task_id:
        The task ID from the originating ``TaskEnvelope`` / ``CommandEnvelope``.
    device_id:
        The device that executed the task.
    chain_step:
        The chain step that produced this result (normally
        :attr:`CanonicalChainStep.result_envelope`).
    success:
        Whether the execution was considered successful.
    status:
        Raw status string from the executing device/worker.
    payload:
        The raw result payload from the executing device/worker.
    error:
        Error message if ``success`` is False.
    trace_id:
        Optional trace ID for distributed tracing.
    session_id:
        Optional session ID for session affinity.
    route_mode:
        The route mode used (e.g. ``"cross_device"``, ``"hybrid"``).
    openclawd_merged:
        Whether this result has been merged into OpenClawd feedback.
        Set to True by :func:`record_chain_execution` when the
        ``openclawd_feedback`` step is recorded.
    projected:
        Whether this result has been forwarded to the projection layer.
    audited:
        Whether this result has been forwarded to the audit layer.
    memory_backflow_stored:
        Whether this result has been written to memory backflow.
    timestamp:
        UNIX timestamp of result creation.
    extra:
        Additional metadata from the executing device/worker.
    """

    result_id: str = dataclasses.field(
        default_factory=lambda: str(uuid.uuid4())
    )
    task_id: str = ""
    device_id: str = ""
    chain_step: CanonicalChainStep = CanonicalChainStep.result_envelope
    success: bool = False
    status: str = "unknown"
    payload: Dict[str, Any] = dataclasses.field(default_factory=dict)
    error: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    route_mode: str = "cross_device"
    openclawd_merged: bool = False
    projected: bool = False
    audited: bool = False
    memory_backflow_stored: bool = False
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "task_id": self.task_id,
            "device_id": self.device_id,
            "chain_step": self.chain_step.value,
            "success": self.success,
            "status": self.status,
            "payload": self.payload,
            "error": self.error,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "route_mode": self.route_mode,
            "openclawd_merged": self.openclawd_merged,
            "projected": self.projected,
            "audited": self.audited,
            "memory_backflow_stored": self.memory_backflow_stored,
            "timestamp": self.timestamp,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResultEnvelope":
        chain_step_raw = data.get("chain_step", CanonicalChainStep.result_envelope.value)
        try:
            chain_step = CanonicalChainStep(chain_step_raw)
        except ValueError:
            chain_step = CanonicalChainStep.result_envelope
        return cls(
            result_id=data.get("result_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            device_id=data.get("device_id", ""),
            chain_step=chain_step,
            success=bool(data.get("success", False)),
            status=data.get("status", "unknown"),
            payload=dict(data.get("payload") or {}),
            error=data.get("error"),
            trace_id=data.get("trace_id"),
            session_id=data.get("session_id"),
            route_mode=data.get("route_mode", "cross_device"),
            openclawd_merged=bool(data.get("openclawd_merged", False)),
            projected=bool(data.get("projected", False)),
            audited=bool(data.get("audited", False)),
            memory_backflow_stored=bool(data.get("memory_backflow_stored", False)),
            timestamp=float(data.get("timestamp", time.time())),
            extra=dict(data.get("extra") or {}),
        )


# ---------------------------------------------------------------------------
# ChainExecutionRecord
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ChainExecutionRecord:
    """Serialisable record of a single cross-device chain execution.

    One record is produced per request that travels through the canonical
    cross-device execution chain.  Records are appended to the global
    :class:`CrossDeviceChainSingleton` by :func:`record_chain_execution`.

    Attributes
    ----------
    record_id:
        Unique identifier for this record (UUID4 by default).
    task_id:
        The task ID from the originating envelope.
    trace_id:
        Optional trace ID for distributed tracing.
    device_id:
        The target device/worker/node.
    route_mode:
        Route mode (e.g. ``"cross_device"``, ``"command_only"``,
        ``"agent_runtime"``).
    steps_completed:
        Ordered list of :class:`CanonicalChainStep` values that were actually
        traversed for this execution.
    is_canonical:
        True if the execution traversed all canonical steps in order.
    legacy_path_used:
        Name of the legacy path used, if any.  None for canonical executions.
    result_envelope:
        The :class:`ResultEnvelope` produced at the end of the chain, if any.
    dispatched_at:
        UNIX timestamp when OpenClawd dispatched the request.
    completed_at:
        UNIX timestamp when the result was merged into OpenClawd, or None.
    extra:
        Additional metadata (authority_role, session_id, etc.).
    """

    record_id: str = dataclasses.field(
        default_factory=lambda: str(uuid.uuid4())
    )
    task_id: str = ""
    trace_id: Optional[str] = None
    device_id: str = ""
    route_mode: str = "cross_device"
    steps_completed: List[CanonicalChainStep] = dataclasses.field(
        default_factory=list
    )
    is_canonical: bool = False
    legacy_path_used: Optional[str] = None
    result_envelope: Optional[ResultEnvelope] = None
    dispatched_at: float = dataclasses.field(default_factory=time.time)
    completed_at: Optional[float] = None
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "device_id": self.device_id,
            "route_mode": self.route_mode,
            "steps_completed": [s.value for s in self.steps_completed],
            "is_canonical": self.is_canonical,
            "legacy_path_used": self.legacy_path_used,
            "result_envelope": (
                self.result_envelope.to_dict()
                if self.result_envelope is not None
                else None
            ),
            "dispatched_at": self.dispatched_at,
            "completed_at": self.completed_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChainExecutionRecord":
        steps_raw = data.get("steps_completed") or []
        steps: List[CanonicalChainStep] = []
        for s in steps_raw:
            try:
                steps.append(CanonicalChainStep(s))
            except ValueError:
                pass
        re_raw = data.get("result_envelope")
        re = ResultEnvelope.from_dict(re_raw) if isinstance(re_raw, dict) else None
        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            trace_id=data.get("trace_id"),
            device_id=data.get("device_id", ""),
            route_mode=data.get("route_mode", "cross_device"),
            steps_completed=steps,
            is_canonical=bool(data.get("is_canonical", False)),
            legacy_path_used=data.get("legacy_path_used"),
            result_envelope=re,
            dispatched_at=float(data.get("dispatched_at", time.time())),
            completed_at=data.get("completed_at"),
            extra=dict(data.get("extra") or {}),
        )


# ---------------------------------------------------------------------------
# CrossDeviceChainSnapshot
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CrossDeviceChainSnapshot:
    """Serialisable snapshot of the global cross-device chain singleton state.

    Consumed by projection, audit, and diagnostics layers.

    Attributes
    ----------
    snapshot_id:
        Unique identifier for this snapshot (UUID4 by default).
    total_executions:
        Total number of chain executions recorded in the current session.
    canonical_executions:
        Number of executions that used the full canonical chain.
    legacy_executions:
        Number of executions that used a legacy/non-canonical path.
    recent_records:
        The most recent :class:`ChainExecutionRecord` entries (up to
        ``max_recent`` as configured on the singleton).
    chain_authority_map:
        Copy of :data:`CHAIN_STEP_AUTHORITIES` for consumer reference.
    canonical_chain_order:
        Ordered list of canonical step values for consumer reference.
    timestamp:
        UNIX timestamp when this snapshot was produced.
    """

    snapshot_id: str = dataclasses.field(
        default_factory=lambda: str(uuid.uuid4())
    )
    total_executions: int = 0
    canonical_executions: int = 0
    legacy_executions: int = 0
    recent_records: List[ChainExecutionRecord] = dataclasses.field(
        default_factory=list
    )
    chain_authority_map: Dict[str, str] = dataclasses.field(
        default_factory=dict
    )
    canonical_chain_order: List[str] = dataclasses.field(default_factory=list)
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "total_executions": self.total_executions,
            "canonical_executions": self.canonical_executions,
            "legacy_executions": self.legacy_executions,
            "recent_records": [r.to_dict() for r in self.recent_records],
            "chain_authority_map": self.chain_authority_map,
            "canonical_chain_order": self.canonical_chain_order,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# CrossDeviceChainSingleton
# ---------------------------------------------------------------------------

_MAX_RECORDS = 200


class CrossDeviceChainSingleton:
    """Global singleton tracking cross-device chain executions.

    Maintains a bounded in-memory log of :class:`ChainExecutionRecord` entries.
    Accessed via :func:`get_cross_device_chain`.
    """

    def __init__(self, max_records: int = _MAX_RECORDS) -> None:
        self._records: List[ChainExecutionRecord] = []
        self._max_records = max_records
        self._total = 0
        self._canonical = 0
        self._legacy = 0

    def append(self, record: ChainExecutionRecord) -> None:
        """Append a :class:`ChainExecutionRecord` to the log."""
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records :]
        self._total += 1
        if record.is_canonical:
            self._canonical += 1
        else:
            self._legacy += 1

    def snapshot(self, max_recent: int = 20) -> CrossDeviceChainSnapshot:
        """Build and return a :class:`CrossDeviceChainSnapshot`."""
        return CrossDeviceChainSnapshot(
            total_executions=self._total,
            canonical_executions=self._canonical,
            legacy_executions=self._legacy,
            recent_records=list(self._records[-max_recent:]),
            chain_authority_map={
                step.value: authority
                for step, authority in CHAIN_STEP_AUTHORITIES.items()
            },
            canonical_chain_order=[s.value for s in CANONICAL_CHAIN_ORDER],
        )

    def clear(self) -> None:
        """Clear all records and reset counters (for testing)."""
        self._records = []
        self._total = 0
        self._canonical = 0
        self._legacy = 0


_CHAIN_SINGLETON: Optional[CrossDeviceChainSingleton] = None


def get_cross_device_chain() -> CrossDeviceChainSingleton:
    """Return the global :class:`CrossDeviceChainSingleton`, creating it if needed."""
    global _CHAIN_SINGLETON
    if _CHAIN_SINGLETON is None:
        _CHAIN_SINGLETON = CrossDeviceChainSingleton()
    return _CHAIN_SINGLETON


def reset_cross_device_chain() -> None:
    """Reset the global singleton to a fresh state (for testing only)."""
    global _CHAIN_SINGLETON
    _CHAIN_SINGLETON = CrossDeviceChainSingleton()


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def build_result_envelope(
    raw_result: Dict[str, Any],
    *,
    task_id: str = "",
    device_id: str = "",
    route_mode: str = "cross_device",
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> ResultEnvelope:
    """Construct a :class:`ResultEnvelope` from a raw cross-device result dict.

    This is the canonical way to normalise a raw execution result before
    merging it back into OpenClawd.

    Parameters
    ----------
    raw_result:
        The raw result dict returned by a worker / device / gateway.
    task_id:
        The originating task ID.
    device_id:
        The executing device ID.
    route_mode:
        The route mode used (e.g. ``"cross_device"``).
    trace_id:
        Optional trace ID for distributed tracing.
    session_id:
        Optional session ID.
    """
    status = raw_result.get("status", "unknown")
    if isinstance(status, bool):
        success = status
    else:
        success = str(status).lower() in ("success", "completed", "done", "ok")

    if not success and not isinstance(status, bool):
        success = bool(raw_result.get("success", False))

    error: Optional[str] = raw_result.get("error") or raw_result.get("error_message")

    # Extract payload — prefer explicit 'result' or 'data' sub-dicts,
    # falling back to the entire raw_result minus large/redundant fields.
    payload_raw = raw_result.get("result") or raw_result.get("data")
    if isinstance(payload_raw, dict):
        payload = payload_raw
    else:
        payload = {
            k: v
            for k, v in raw_result.items()
            if k not in ("image_base64", "screenshot_base64", "raw_bytes")
        }

    return ResultEnvelope(
        task_id=task_id or raw_result.get("task_id", ""),
        device_id=device_id or raw_result.get("device_id", ""),
        chain_step=CanonicalChainStep.result_envelope,
        success=success,
        status=str(status),
        payload=payload,
        error=error,
        trace_id=trace_id or raw_result.get("trace_id"),
        session_id=session_id or raw_result.get("session_id"),
        route_mode=route_mode,
        extra={
            k: v
            for k, v in raw_result.items()
            if k not in ("status", "success", "result", "data", "error",
                         "error_message", "task_id", "device_id",
                         "trace_id", "session_id", "image_base64",
                         "screenshot_base64", "raw_bytes")
        },
    )


def build_chain_execution_record(
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
    device_id: str = "",
    route_mode: str = "cross_device",
    steps_completed: Optional[List[CanonicalChainStep]] = None,
    legacy_path_used: Optional[str] = None,
    result_envelope: Optional[ResultEnvelope] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> ChainExecutionRecord:
    """Construct a :class:`ChainExecutionRecord` from execution signals.

    Parameters
    ----------
    task_id:
        The originating task ID.
    trace_id:
        Optional trace ID.
    device_id:
        The executing device ID.
    route_mode:
        The route mode used.
    steps_completed:
        Ordered list of :class:`CanonicalChainStep` values actually traversed.
        Defaults to the full canonical chain if not provided and no
        ``legacy_path_used`` is given.
    legacy_path_used:
        If a non-canonical / legacy path was used, its name.  Setting this
        implies ``is_canonical=False``.
    result_envelope:
        The :class:`ResultEnvelope` produced by this execution.
    extra:
        Additional metadata.
    """
    completed_at = time.time() if result_envelope is not None else None

    if steps_completed is None:
        if legacy_path_used:
            steps_completed = []
        else:
            steps_completed = list(CANONICAL_CHAIN_ORDER)

    is_canonical = (
        legacy_path_used is None
        and steps_completed == list(CANONICAL_CHAIN_ORDER)
    )

    return ChainExecutionRecord(
        task_id=task_id,
        trace_id=trace_id,
        device_id=device_id,
        route_mode=route_mode,
        steps_completed=steps_completed,
        is_canonical=is_canonical,
        legacy_path_used=legacy_path_used,
        result_envelope=result_envelope,
        completed_at=completed_at,
        extra=extra or {},
    )


def record_chain_execution(
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
    device_id: str = "",
    route_mode: str = "cross_device",
    steps_completed: Optional[List[CanonicalChainStep]] = None,
    legacy_path_used: Optional[str] = None,
    result_envelope: Optional[ResultEnvelope] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> ChainExecutionRecord:
    """Build a :class:`ChainExecutionRecord`, append it to the global singleton,
    and return the record.

    This is the primary way to record that a cross-device task has completed
    the canonical chain.  Callers should invoke this in the
    ``openclawd_feedback`` step, after the ``ResultEnvelope`` has been produced
    and merged back into OpenClawd.
    """
    record = build_chain_execution_record(
        task_id=task_id,
        trace_id=trace_id,
        device_id=device_id,
        route_mode=route_mode,
        steps_completed=steps_completed,
        legacy_path_used=legacy_path_used,
        result_envelope=result_envelope,
        extra=extra or {},
    )

    # Mark the result envelope as OpenClawd-merged when recording the full chain.
    if record.is_canonical and record.result_envelope is not None:
        record.result_envelope.openclawd_merged = True

    get_cross_device_chain().append(record)

    logger.debug(
        "chain_execution_record: task_id=%s device_id=%s is_canonical=%s "
        "legacy_path=%s route_mode=%s",
        task_id,
        device_id,
        record.is_canonical,
        legacy_path_used or "none",
        route_mode,
    )

    if not record.is_canonical and legacy_path_used:
        logger.warning(
            "LEGACY CHAIN PATH | task_id=%s device_id=%s legacy_path=%s | "
            "Use OpenClawd → CommandRouter → TaskEnvelope → Gateway substrate → "
            "Worker/Device/Node → ResultEnvelope → OpenClawd feedback instead.",
            task_id,
            device_id,
            legacy_path_used,
        )

    return record


def build_cross_device_chain_snapshot(
    max_recent: int = 20,
) -> CrossDeviceChainSnapshot:
    """Build a :class:`CrossDeviceChainSnapshot` from the global singleton.

    Suitable for embedding in OpenClawd response metadata, projection payloads,
    and audit logs.
    """
    return get_cross_device_chain().snapshot(max_recent=max_recent)
