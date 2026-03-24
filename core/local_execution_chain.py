#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/local_execution_chain.py — Canonical Local Execution Chain (PR-4)

**Unified-Subject Architecture — Canonical Local Execution Chain**
------------------------------------------------------------------
This module establishes the **canonical local execution chain** for the
Galaxy runtime.  It is the symmetric counterpart of
:mod:`core.cross_device_execution_chain` and provides vocabulary for
tracking, auditing, and projecting local execution state.

The two execution chains under the unified subject runtime:

.. code-block:: text

    DesktopPresenceRuntime (outer shell / Windows clothing)
        └─ unified subject runtime
              ├─ LOCAL EXECUTION CHAIN      ← this module
              └─ CROSS-DEVICE EXECUTION CHAIN  (core/cross_device_execution_chain.py)

Canonical Chain
---------------
::

    OpenClawd (routing authority)
        └─ AgentKernel (planning/cognition only — not final authority)
              └─ CommandRouter.route_envelope() [LOCAL_MANIFESTATION]
                    └─ Local executor / capability / skill / MCP tool
                          └─ LocalExecutionResult (normalised result)
                                └─ OpenClawd feedback
                                      └─ Projection / Audit / Memory backflow

Architecture ownership rules
-----------------------------
- **OpenClawd** owns routing authority — it is the sole decision-maker for
  whether a request executes locally.
- **AgentKernel** is the *planning / cognition layer* only.  It does not
  hold final execution authority.
- **CommandRouter** is the canonical router for local tasks when called
  with ``LOCAL_MANIFESTATION`` mode.  No other module should dispatch to
  local executors independently.
- **Local executors** (Windows API adapters, capability modules, skill
  packages, MCP tools) are executors only; they receive instructions and
  do not make routing or planning decisions.
- **LocalExecutionResult** is the canonical result container.  All local
  execution results should be normalised into a :class:`LocalExecutionResult`
  before being fed back to OpenClawd.
- **Projection** and **memory backflow** are downstream consumers triggered
  by OpenClawd after it receives the ``LocalExecutionResult`` — they are not
  independent authorities.

Local vs cross-device
---------------------
Both chains share the same authority structure at the top (OpenClawd decides,
CommandRouter routes) and the same feedback path (normalised result →
OpenClawd → projection/backflow).  The distinction is:

- **Local chain** — execution stays on the Windows desktop.  Result flows
  back *synchronously* via ``CommandRouter.route_envelope()``'s return value.
- **Cross-device chain** — execution delegates to a remote node.  Result
  flows back asynchronously via a ``ResultEnvelope`` through the gateway
  substrate and the canonical 7-step cross-device chain.

Canonical step count: **6** (vs 7 for cross-device; the gateway/task-envelope
steps are absent because execution is local).

Public API
----------
:class:`LocalChainStep`
    Enum of the steps in the canonical local execution chain.

:class:`LocalExecutionResult`
    Normalised, serialisable result container for local task results.

:class:`LocalExecutionRecord`
    Serialisable record of a single local chain execution.

:class:`LocalChainSnapshot`
    Serialisable snapshot of the global chain singleton state.

:func:`build_local_execution_result`
    Construct a :class:`LocalExecutionResult` from a raw result dict.

:func:`build_local_execution_record`
    Construct a :class:`LocalExecutionRecord` from execution signals.

:func:`record_local_execution`
    Append a :class:`LocalExecutionRecord` to the global singleton and
    return the record.

:func:`build_local_chain_snapshot`
    Build a :class:`LocalChainSnapshot` from the global singleton.

:func:`get_local_execution_chain`
    Return the global :class:`LocalExecutionChainSingleton`.

:func:`reset_local_execution_chain`
    Reset the global singleton (for testing).
"""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LocalExecutionChain")

__all__ = [
    "LocalChainStep",
    "LOCAL_CHAIN_STEP_AUTHORITIES",
    "LOCAL_CHAIN_ORDER",
    "LocalExecutionResult",
    "LocalExecutionRecord",
    "LocalChainSnapshot",
    "LocalExecutionChainSingleton",
    "build_local_execution_result",
    "build_local_execution_record",
    "record_local_execution",
    "build_local_chain_snapshot",
    "get_local_execution_chain",
    "reset_local_execution_chain",
]


# ---------------------------------------------------------------------------
# LocalChainStep
# ---------------------------------------------------------------------------


class LocalChainStep(str, Enum):
    """Ordered steps of the canonical local execution chain.

    Each step corresponds to a distinct authority boundary in the local
    execution path.  See :data:`LOCAL_CHAIN_ORDER` for the canonical ordering
    and :data:`LOCAL_CHAIN_STEP_AUTHORITIES` for the owning module at each
    step.

    .. code-block:: text

        openclawd_dispatch
            → agent_kernel_plan
                → command_router_local
                    → local_executor
                        → result_capture
                            → openclawd_feedback
    """

    openclawd_dispatch = "openclawd_dispatch"
    """OpenClawd receives the request and decides local execution is appropriate.
    Authority: ``core.openclawd`` (subject_decision_authority)."""

    agent_kernel_plan = "agent_kernel_plan"
    """AgentKernel produces a plan / intent via the LLM continuum loop.
    Authority: ``core.agent.kernel`` (cognition_planning_layer).
    NOTE: AgentKernel is a *planning layer only* — it does not hold final
    execution authority."""

    command_router_local = "command_router_local"
    """CommandRouter.route_envelope() is called with LOCAL_MANIFESTATION mode.
    Authority: ``core.command_router`` (execution_substrate).
    This is the canonical routing step for all local execution."""

    local_executor = "local_executor"
    """The resolved local executor (Windows API adapter, capability module,
    skill package, or MCP tool) performs the action on the local device.
    Authority: capability/skill/MCP module (executor_only)."""

    result_capture = "result_capture"
    """The raw executor result is normalised into a :class:`LocalExecutionResult`.
    Authority: ``core.local_execution_chain`` (result_normaliser)."""

    openclawd_feedback = "openclawd_feedback"
    """OpenClawd receives the normalised result, applies memory backflow,
    and emits projection updates.
    Authority: ``core.openclawd`` (subject_decision_authority)."""


#: Mapping from each chain step to the module/class that owns authority at
#: that step.  Used by diagnostics and contributor tooling to verify layer
#: compliance.
LOCAL_CHAIN_STEP_AUTHORITIES: Dict[LocalChainStep, str] = {
    LocalChainStep.openclawd_dispatch: "core.openclawd",
    LocalChainStep.agent_kernel_plan: "core.agent.kernel",
    LocalChainStep.command_router_local: "core.command_router",
    LocalChainStep.local_executor: "capability/skill/mcp_module",
    LocalChainStep.result_capture: "core.local_execution_chain",
    LocalChainStep.openclawd_feedback: "core.openclawd",
}

#: Ordered list of steps in the canonical local execution chain.
#: Any execution that skips or reorders these steps is non-canonical.
LOCAL_CHAIN_ORDER: List[LocalChainStep] = [
    LocalChainStep.openclawd_dispatch,
    LocalChainStep.agent_kernel_plan,
    LocalChainStep.command_router_local,
    LocalChainStep.local_executor,
    LocalChainStep.result_capture,
    LocalChainStep.openclawd_feedback,
]


# ---------------------------------------------------------------------------
# LocalExecutionResult
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LocalExecutionResult:
    """Normalised, serialisable result container for a local task execution.

    All local execution results should be normalised into a
    :class:`LocalExecutionResult` at the ``result_capture`` step before
    being passed back to OpenClawd.  This is the local-execution analogue of
    :class:`core.cross_device_execution_chain.ResultEnvelope`.

    Attributes
    ----------
    task_id:
        The originating task / request identifier.
    chain_step:
        The chain step at which this result was produced (always
        :attr:`LocalChainStep.result_capture`).
    success:
        Whether the local execution succeeded.
    status:
        Raw status string from the executor (e.g. ``"completed"``,
        ``"failed"``, ``"skipped"``).
    payload:
        Normalised result payload — a plain ``dict`` with the semantically
        meaningful result data.  Large blobs (screenshots, binary data) are
        excluded.
    error:
        Error message if execution failed, otherwise ``None``.
    executor_module:
        Dotted module path of the executor that ran the task (for audit).
    session_id:
        Optional runtime session ID propagated from
        :class:`core.desktop_presence_runtime.RuntimeSession`.
    result_id:
        Auto-generated unique ID for this result record.
    timestamp:
        Unix timestamp when the result was captured.
    extra:
        Additional metadata that does not fit the standard fields.
    openclawd_merged:
        Set to ``True`` by :func:`record_local_execution` when the record
        has been acknowledged by OpenClawd feedback.
    """

    task_id: str = ""
    chain_step: LocalChainStep = LocalChainStep.result_capture
    success: bool = False
    status: str = "unknown"
    payload: Dict[str, Any] = dataclasses.field(default_factory=dict)
    error: Optional[str] = None
    executor_module: str = ""
    session_id: Optional[str] = None
    result_id: str = dataclasses.field(
        default_factory=lambda: uuid.uuid4().hex,
    )
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)
    openclawd_merged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "task_id": self.task_id,
            "chain_step": self.chain_step.value,
            "success": self.success,
            "status": self.status,
            "payload": self.payload,
            "error": self.error,
            "executor_module": self.executor_module,
            "session_id": self.session_id,
            "result_id": self.result_id,
            "timestamp": self.timestamp,
            "extra": self.extra,
            "openclawd_merged": self.openclawd_merged,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalExecutionResult":
        """Reconstruct a :class:`LocalExecutionResult` from a dict."""
        step_val = data.get("chain_step", LocalChainStep.result_capture.value)
        try:
            step = LocalChainStep(step_val)
        except ValueError:
            step = LocalChainStep.result_capture
        return cls(
            task_id=data.get("task_id", ""),
            chain_step=step,
            success=bool(data.get("success", False)),
            status=str(data.get("status", "unknown")),
            payload=data.get("payload") or {},
            error=data.get("error"),
            executor_module=data.get("executor_module", ""),
            session_id=data.get("session_id"),
            result_id=data.get("result_id", uuid.uuid4().hex),
            timestamp=float(data.get("timestamp", time.time())),
            extra=data.get("extra") or {},
            openclawd_merged=bool(data.get("openclawd_merged", False)),
        )


# ---------------------------------------------------------------------------
# LocalExecutionRecord
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LocalExecutionRecord:
    """Serialisable record of a single local chain execution.

    One :class:`LocalExecutionRecord` is created per top-level request that
    travels the local execution chain.  Records are appended to the global
    :class:`LocalExecutionChainSingleton` by :func:`record_local_execution`.

    Attributes
    ----------
    task_id:
        The originating task identifier.
    session_id:
        Optional runtime session ID.
    executor_module:
        Dotted module path of the executor that ran the task.
    steps_completed:
        Ordered list of :class:`LocalChainStep` values actually traversed.
    is_canonical:
        ``True`` when :attr:`steps_completed` exactly matches
        :data:`LOCAL_CHAIN_ORDER` and no legacy path was used.
    legacy_path_used:
        Non-``None`` when execution used a non-canonical / legacy path.
    result:
        The :class:`LocalExecutionResult` produced by this execution.
    record_id:
        Auto-generated unique ID for this record.
    dispatched_at:
        Unix timestamp when the record was created.
    completed_at:
        Unix timestamp when execution completed (``None`` if not yet done).
    extra:
        Additional metadata.
    """

    task_id: str = ""
    session_id: Optional[str] = None
    executor_module: str = ""
    steps_completed: List[LocalChainStep] = dataclasses.field(
        default_factory=list,
    )
    is_canonical: bool = False
    legacy_path_used: Optional[str] = None
    result: Optional[LocalExecutionResult] = None
    record_id: str = dataclasses.field(
        default_factory=lambda: uuid.uuid4().hex,
    )
    dispatched_at: float = dataclasses.field(default_factory=time.time)
    completed_at: Optional[float] = None
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "executor_module": self.executor_module,
            "steps_completed": [s.value for s in self.steps_completed],
            "is_canonical": self.is_canonical,
            "legacy_path_used": self.legacy_path_used,
            "result": self.result.to_dict() if self.result is not None else None,
            "record_id": self.record_id,
            "dispatched_at": self.dispatched_at,
            "completed_at": self.completed_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalExecutionRecord":
        """Reconstruct a :class:`LocalExecutionRecord` from a dict."""
        raw_steps = data.get("steps_completed") or []
        steps: List[LocalChainStep] = []
        for sv in raw_steps:
            try:
                steps.append(LocalChainStep(sv))
            except ValueError:
                pass
        result_data = data.get("result")
        result = (
            LocalExecutionResult.from_dict(result_data)
            if isinstance(result_data, dict)
            else None
        )
        return cls(
            task_id=data.get("task_id", ""),
            session_id=data.get("session_id"),
            executor_module=data.get("executor_module", ""),
            steps_completed=steps,
            is_canonical=bool(data.get("is_canonical", False)),
            legacy_path_used=data.get("legacy_path_used"),
            result=result,
            record_id=data.get("record_id", uuid.uuid4().hex),
            dispatched_at=float(data.get("dispatched_at", time.time())),
            completed_at=data.get("completed_at"),
            extra=data.get("extra") or {},
        )


# ---------------------------------------------------------------------------
# LocalChainSnapshot
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LocalChainSnapshot:
    """Serialisable snapshot of the global :class:`LocalExecutionChainSingleton`.

    Suitable for embedding in OpenClawd response metadata, projection payloads,
    and audit logs.  This is the local-chain analogue of
    :class:`core.cross_device_execution_chain.CrossDeviceChainSnapshot`.

    Attributes
    ----------
    total_executions:
        Total number of local executions recorded since last reset.
    canonical_executions:
        Number of executions that followed the full canonical chain.
    legacy_executions:
        Number of executions that used a legacy / non-canonical path.
    recent_records:
        The most recent :class:`LocalExecutionRecord` entries (up to
        ``max_recent``).
    chain_authority_map:
        Snapshot of :data:`LOCAL_CHAIN_STEP_AUTHORITIES` as a plain dict.
    canonical_chain_order:
        Snapshot of :data:`LOCAL_CHAIN_ORDER` as a list of step value strings.
    snapshot_id:
        Auto-generated unique ID for this snapshot.
    timestamp:
        Unix timestamp when this snapshot was built.
    """

    total_executions: int = 0
    canonical_executions: int = 0
    legacy_executions: int = 0
    recent_records: List[LocalExecutionRecord] = dataclasses.field(
        default_factory=list,
    )
    chain_authority_map: Dict[str, str] = dataclasses.field(
        default_factory=dict,
    )
    canonical_chain_order: List[str] = dataclasses.field(default_factory=list)
    snapshot_id: str = dataclasses.field(
        default_factory=lambda: uuid.uuid4().hex,
    )
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "total_executions": self.total_executions,
            "canonical_executions": self.canonical_executions,
            "legacy_executions": self.legacy_executions,
            "recent_records": [r.to_dict() for r in self.recent_records],
            "chain_authority_map": self.chain_authority_map,
            "canonical_chain_order": self.canonical_chain_order,
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# LocalExecutionChainSingleton
# ---------------------------------------------------------------------------

_MAX_RECORDS = 200


class LocalExecutionChainSingleton:
    """Bounded in-memory audit log for local execution chain records.

    Maintains a bounded in-memory log of :class:`LocalExecutionRecord`
    entries.  Provides snapshot access suitable for projection/status
    surfaces.  This is the local-chain analogue of
    :class:`core.cross_device_execution_chain.CrossDeviceChainSingleton`.
    """

    def __init__(self, max_records: int = _MAX_RECORDS) -> None:
        self._records: List[LocalExecutionRecord] = []
        self._max_records = max_records
        self._total = 0
        self._canonical = 0
        self._legacy = 0

    def append(self, record: LocalExecutionRecord) -> None:
        """Append a :class:`LocalExecutionRecord` to the log."""
        self._records.append(record)
        self._total += 1
        if record.is_canonical:
            self._canonical += 1
        elif record.legacy_path_used:
            self._legacy += 1
        # Trim to bounded size (FIFO).
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records :]

    def snapshot(self, max_recent: int = 20) -> LocalChainSnapshot:
        """Build and return a :class:`LocalChainSnapshot`."""
        recent = self._records[-max_recent:] if self._records else []
        return LocalChainSnapshot(
            total_executions=self._total,
            canonical_executions=self._canonical,
            legacy_executions=self._legacy,
            recent_records=list(recent),
            chain_authority_map={
                step.value: authority
                for step, authority in LOCAL_CHAIN_STEP_AUTHORITIES.items()
            },
            canonical_chain_order=[s.value for s in LOCAL_CHAIN_ORDER],
        )

    def clear(self) -> None:
        """Clear all records and reset counters (for testing)."""
        self._records = []
        self._total = 0
        self._canonical = 0
        self._legacy = 0


_CHAIN_SINGLETON: Optional[LocalExecutionChainSingleton] = None


def get_local_execution_chain() -> LocalExecutionChainSingleton:
    """Return the global :class:`LocalExecutionChainSingleton`, creating it if needed."""
    global _CHAIN_SINGLETON
    if _CHAIN_SINGLETON is None:
        _CHAIN_SINGLETON = LocalExecutionChainSingleton()
    return _CHAIN_SINGLETON


def reset_local_execution_chain() -> None:
    """Reset the global singleton to a fresh state (for testing only)."""
    global _CHAIN_SINGLETON
    _CHAIN_SINGLETON = LocalExecutionChainSingleton()


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def build_local_execution_result(
    raw_result: Dict[str, Any],
    *,
    task_id: str = "",
    executor_module: str = "",
    session_id: Optional[str] = None,
) -> LocalExecutionResult:
    """Construct a :class:`LocalExecutionResult` from a raw local executor dict.

    This is the canonical way to normalise a raw local execution result before
    passing it back to OpenClawd.

    Parameters
    ----------
    raw_result:
        The raw result dict returned by a local executor / capability module.
    task_id:
        The originating task ID.
    executor_module:
        Dotted module path of the executor (for audit).
    session_id:
        Optional runtime session ID.
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

    return LocalExecutionResult(
        task_id=task_id or raw_result.get("task_id", ""),
        chain_step=LocalChainStep.result_capture,
        success=success,
        status=str(status),
        payload=payload,
        error=error,
        executor_module=executor_module or raw_result.get("executor_module", ""),
        session_id=session_id or raw_result.get("session_id"),
        extra={
            k: v
            for k, v in raw_result.items()
            if k not in (
                "status",
                "success",
                "result",
                "data",
                "error",
                "error_message",
                "task_id",
                "executor_module",
                "session_id",
                "image_base64",
                "screenshot_base64",
                "raw_bytes",
            )
        },
    )


def build_local_execution_record(
    *,
    task_id: str = "",
    session_id: Optional[str] = None,
    executor_module: str = "",
    steps_completed: Optional[List[LocalChainStep]] = None,
    legacy_path_used: Optional[str] = None,
    result: Optional[LocalExecutionResult] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> LocalExecutionRecord:
    """Construct a :class:`LocalExecutionRecord` from execution signals.

    Parameters
    ----------
    task_id:
        The originating task ID.
    session_id:
        Optional runtime session ID.
    executor_module:
        Dotted module path of the executor.
    steps_completed:
        Ordered list of :class:`LocalChainStep` values actually traversed.
        Defaults to the full canonical chain if not provided and no
        ``legacy_path_used`` is given.
    legacy_path_used:
        If a non-canonical / legacy path was used, its name.  Setting this
        implies ``is_canonical=False``.
    result:
        The :class:`LocalExecutionResult` produced by this execution.
    extra:
        Additional metadata.
    """
    completed_at = time.time() if result is not None else None

    if steps_completed is None:
        if legacy_path_used:
            steps_completed = []
        else:
            steps_completed = list(LOCAL_CHAIN_ORDER)

    is_canonical = (
        legacy_path_used is None
        and steps_completed == list(LOCAL_CHAIN_ORDER)
    )

    return LocalExecutionRecord(
        task_id=task_id,
        session_id=session_id,
        executor_module=executor_module,
        steps_completed=steps_completed,
        is_canonical=is_canonical,
        legacy_path_used=legacy_path_used,
        result=result,
        completed_at=completed_at,
        extra=extra or {},
    )


def record_local_execution(
    *,
    task_id: str = "",
    session_id: Optional[str] = None,
    executor_module: str = "",
    steps_completed: Optional[List[LocalChainStep]] = None,
    legacy_path_used: Optional[str] = None,
    result: Optional[LocalExecutionResult] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> LocalExecutionRecord:
    """Build a :class:`LocalExecutionRecord`, append it to the global singleton,
    and return the record.

    This is the primary way to record that a local task has completed the
    canonical chain.  Callers should invoke this in the
    ``openclawd_feedback`` step, after the :class:`LocalExecutionResult` has
    been produced and merged back into OpenClawd.
    """
    record = build_local_execution_record(
        task_id=task_id,
        session_id=session_id,
        executor_module=executor_module,
        steps_completed=steps_completed,
        legacy_path_used=legacy_path_used,
        result=result,
        extra=extra or {},
    )

    # Mark the result as OpenClawd-merged when recording the full chain.
    if record.is_canonical and record.result is not None:
        record.result.openclawd_merged = True

    get_local_execution_chain().append(record)

    logger.debug(
        "local_execution_record: task_id=%s executor=%s is_canonical=%s "
        "legacy_path=%s",
        task_id,
        executor_module,
        record.is_canonical,
        legacy_path_used or "none",
    )

    if not record.is_canonical and legacy_path_used:
        logger.warning(
            "LEGACY LOCAL CHAIN PATH | task_id=%s executor=%s legacy_path=%s | "
            "Use OpenClawd → AgentKernel → CommandRouter[LOCAL_MANIFESTATION] → "
            "local executor → LocalExecutionResult → OpenClawd feedback instead.",
            task_id,
            executor_module,
            legacy_path_used,
        )

    return record


def build_local_chain_snapshot(
    max_recent: int = 20,
) -> LocalChainSnapshot:
    """Build a :class:`LocalChainSnapshot` from the global singleton.

    Suitable for embedding in OpenClawd response metadata, projection payloads,
    and audit logs.
    """
    return get_local_execution_chain().snapshot(max_recent=max_recent)
