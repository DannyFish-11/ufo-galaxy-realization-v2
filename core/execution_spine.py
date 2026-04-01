#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/execution_spine.py — PR-3: Execution Spine Integration
=============================================================

**Canonical Execution Spine — Unified Ingress Adapter**
---------------------------------------------------------
This module is the **single authority** for funnelling all execution
ingress paths (scheduler tool calls, android bridge dispatches, legacy
orchestrator invocations) into the canonical execution spine:

.. code-block:: text

    scheduler / bridge / legacy orchestrator
              │
              ▼
    ExecutionIngressAdapter.route_via_spine()
              │
              ▼  (builds / normalizes TaskEnvelope)
    CommandRouter.route_envelope()
              │
              ▼  (canonical chain from here)
    Gateway substrate → Worker/Device/Node
              │
              ▼
    ResultEnvelope → OpenClawd feedback

Architecture position
---------------------
- **OpenClawd** is the execution decision authority.
- **CommandRouter** is the *sole* cross-device execution router.
- **ExecutionIngressAdapter** (this module) is the *ingress normalizer*:
  it converts heterogeneous upstream frames into ``TaskEnvelope`` and
  enters ``CommandRouter.route_envelope``.  It has no independent
  dispatch authority.

Design invariants
-----------------
1.  **Additive-only** — this module never modifies existing callers.
    Legacy modules that do not adopt it continue to work unchanged.
2.  **Single spine** — all paths that adopt this adapter converge on
    ``CommandRouter.route_envelope`` as the terminal dispatch entry.
3.  **Observability** — every normalized ingress is recorded in a
    ring-buffer for operator visibility / debugging.
4.  **Graceful degradation** — all optional imports are wrapped in
    try/except; this module never raises on import.

Public API
----------
Authority sentinels::

    EXECUTION_SPINE_AUTHORITY
    EXECUTION_SPINE_INGRESS_POLICY

Enums::

    ExecutionIngressSource

Dataclasses::

    IngressRecord

Helpers::

    normalize_ingress_to_envelope(payload, *, source) -> TaskEnvelope
    route_via_spine(payload, *, source, router) -> Dict
    record_legacy_ingress(source, payload, *, reason) -> IngressRecord
    get_ingress_log() -> List[IngressRecord]
    reset_ingress_log()          (testing only)
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.ExecutionSpine")

__all__ = [
    # Authority
    "EXECUTION_SPINE_AUTHORITY",
    "EXECUTION_SPINE_INGRESS_POLICY",
    # Enum
    "ExecutionIngressSource",
    # Dataclass
    "IngressRecord",
    # Helpers
    "normalize_ingress_to_envelope",
    "route_via_spine",
    "record_legacy_ingress",
    "get_ingress_log",
    "reset_ingress_log",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Identifies this module as the canonical execution spine ingress authority.
#: PR-3: Execution Spine Integration.
EXECUTION_SPINE_AUTHORITY: str = "EXECUTION_SPINE_V1"

#: Policy: all cross-device execution MUST enter CommandRouter.route_envelope.
#: Scheduler / bridge / orchestrator paths are normalised here before dispatch.
EXECUTION_SPINE_INGRESS_POLICY: str = (
    "REQUIRED: all execution ingress normalized to TaskEnvelope before "
    "entering CommandRouter.route_envelope; no parallel dispatch authority."
)


# ---------------------------------------------------------------------------
# Ingress source classification
# ---------------------------------------------------------------------------

class ExecutionIngressSource(str, Enum):
    """Classifies the origin of an execution ingress frame."""

    SCHEDULER = "scheduler"
    """Core scheduler tool call (send_to_device / relay_to_device / mesh_send)."""

    BRIDGE = "bridge"
    """Android bridge dispatch (goal_execution / task_submit)."""

    GALAXY_ORCHESTRATOR = "galaxy_orchestrator"
    """Legacy GalaxyOrchestrator.execute_task() path."""

    DEVICE_ORCHESTRATOR = "device_orchestrator"
    """Legacy DeviceOrchestrator.send_command() path."""

    UNIFIED_ORCHESTRATOR = "unified_orchestrator"
    """Legacy UnifiedOrchestrator path (already deprecated)."""

    CANONICAL = "canonical"
    """Already a valid TaskEnvelope — no normalization needed."""

    UNKNOWN = "unknown"
    """Source unknown / not yet classified."""


# ---------------------------------------------------------------------------
# Ingress record (observability ring-buffer entry)
# ---------------------------------------------------------------------------

@dataclass
class IngressRecord:
    """A single entry in the execution spine ingress log.

    Stored in a bounded ring-buffer (max 256 entries) for operator
    observability.  The log is accessible via :func:`get_ingress_log`.
    """

    record_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: ExecutionIngressSource = ExecutionIngressSource.UNKNOWN
    task_id: str = ""
    trace_id: str = ""
    tool_name: str = ""
    targets: List[str] = field(default_factory=list)
    was_normalized: bool = False
    """True when the payload required normalization (non-canonical input)."""
    legacy_reason: str = ""
    """Human-readable description of why this path is considered legacy."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source": self.source.value if isinstance(self.source, ExecutionIngressSource) else str(self.source),
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "tool_name": self.tool_name,
            "targets": self.targets,
            "was_normalized": self.was_normalized,
            "legacy_reason": self.legacy_reason,
        }


# ---------------------------------------------------------------------------
# Global ingress ring-buffer (max 256 entries)
# ---------------------------------------------------------------------------

_INGRESS_LOG_MAX: int = 256
_ingress_log: Deque[IngressRecord] = deque(maxlen=_INGRESS_LOG_MAX)


def get_ingress_log() -> List[IngressRecord]:
    """Return a snapshot of the execution spine ingress log (most recent last)."""
    return list(_ingress_log)


def reset_ingress_log() -> None:
    """Clear the ingress log (intended for use in tests only)."""
    _ingress_log.clear()


def _append_ingress_record(record: IngressRecord) -> None:
    _ingress_log.append(record)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _new_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:16]}"


def _new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:12]}"


@dataclass
class _FallbackEnvelope:
    """Minimal envelope substitute for environments where pydantic is absent.

    Provides the same attribute interface as ``TaskEnvelope`` so that
    downstream code can access ``task_id``, ``trace_id``, ``tool_name``,
    ``targets``, ``args``, ``source``, and ``metadata`` without error.
    """

    task_id: str = field(default_factory=_new_task_id)
    trace_id: str = field(default_factory=_new_trace_id)
    source: str = ""
    targets: List[str] = field(default_factory=list)
    tool_name: str = "unknown"
    args: Dict[str, Any] = field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    @property
    def target(self) -> str:
        return self.targets[0] if self.targets else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source": self.source,
            "targets": self.targets,
            "tool_name": self.tool_name,
            "args": self.args,
            "metadata": self.metadata or {},
        }


def normalize_ingress_to_envelope(
    payload: Any,
    *,
    source: ExecutionIngressSource = ExecutionIngressSource.UNKNOWN,
) -> Any:
    """Normalize an arbitrary execution ingress payload into a ``TaskEnvelope``.

    If *payload* is already a ``TaskEnvelope`` the fast path is taken and it
    is returned unchanged.

    Otherwise the function delegates to
    :func:`core.message_interop.normalize_to_task_envelope` (PR-2) so that
    the same correlation-field stamping logic applies to all ingress paths.

    Parameters
    ----------
    payload:
        Arbitrary execution frame — a dict, a ``TaskEnvelope``, or any object
        that exposes a ``to_dict()`` method.
    source:
        Origin classification for observability / audit.

    Returns
    -------
    TaskEnvelope
        A fully populated ``TaskEnvelope`` ready for
        ``CommandRouter.route_envelope``.
    """
    # ── Fast path: already a TaskEnvelope ──────────────────────────────────
    try:
        from core.schemas.task_envelope import TaskEnvelope as _TE
        if isinstance(payload, _TE):
            return payload
    except Exception:
        pass

    # ── Delegate to PR-2 message interop layer ─────────────────────────────
    try:
        from core.message_interop import normalize_to_task_envelope as _norm
        envelope = _norm(payload, source=source.value if isinstance(source, ExecutionIngressSource) else str(source))
        return envelope
    except Exception as exc:
        logger.debug("normalize_ingress_to_envelope: message_interop unavailable (%s); building fallback", exc)

    # ── Fallback: build a minimal envelope from dict keys ──────────────────
    raw: Dict[str, Any] = {}
    if isinstance(payload, dict):
        raw = payload
    elif hasattr(payload, "to_dict"):
        try:
            raw = payload.to_dict()
        except Exception:
            pass

    task_id = str(raw.get("task_id") or _new_task_id())
    trace_id = str(raw.get("trace_id") or _new_trace_id())
    tool_name = str(
        raw.get("tool_name")
        or raw.get("task_type")
        or raw.get("action")
        or raw.get("command")
        or "unknown"
    )
    targets_raw = list(raw.get("targets") or [])
    if not targets_raw:
        td = raw.get("target_device_id") or raw.get("device_id") or raw.get("target_device")
        if td:
            targets_raw = [str(td)]
    src_val = source.value if isinstance(source, ExecutionIngressSource) else str(source)

    try:
        from core.schemas.task_envelope import TaskEnvelope as _TE
        return _TE(
            task_id=task_id,
            trace_id=trace_id,
            source=src_val,
            targets=targets_raw,
            tool_name=tool_name,
            args=raw.get("args") or raw.get("payload") or raw.get("params") or {},
            metadata={"ingress_source": src_val},
        )
    except Exception:
        # pydantic / TaskEnvelope unavailable — return lightweight fallback
        return _FallbackEnvelope(
            task_id=task_id,
            trace_id=trace_id,
            source=src_val,
            targets=targets_raw,
            tool_name=tool_name,
            args=raw.get("args") or raw.get("payload") or raw.get("params") or {},
            metadata={"ingress_source": src_val},
        )


# ---------------------------------------------------------------------------
# Main spine entry — normalize + route
# ---------------------------------------------------------------------------

async def route_via_spine(
    payload: Any,
    *,
    source: ExecutionIngressSource = ExecutionIngressSource.UNKNOWN,
    router: Any = None,
) -> Dict[str, Any]:
    """Normalize *payload* and route it through ``CommandRouter.route_envelope``.

    This is the **canonical ingress function** for all non-canonical execution
    paths.  After calling this function the request is on the spine:

    .. code-block:: text

        route_via_spine()
            → normalize_ingress_to_envelope()
            → CommandRouter.route_envelope()
            → DeviceRouter → device / worker

    Parameters
    ----------
    payload:
        Execution frame from scheduler / bridge / orchestrator.
    source:
        Origin classification for observability.
    router:
        Optional pre-resolved ``CommandRouter`` instance.  When omitted the
        global singleton is obtained via :func:`core.command_router.get_command_router`.

    Returns
    -------
    dict
        Raw result dict from ``CommandRouter.route_envelope``.
    """
    # 1. Normalise to TaskEnvelope
    try:
        envelope = normalize_ingress_to_envelope(payload, source=source)
    except Exception as exc:
        return {
            "success": False,
            "error": f"execution_spine: normalization failed: {exc}",
            "source": source.value if isinstance(source, ExecutionIngressSource) else str(source),
        }

    # 2. Record ingress for observability
    try:
        from core.schemas.task_envelope import TaskEnvelope as _TE
        is_canonical = isinstance(payload, _TE)
    except Exception:
        is_canonical = False

    rec = IngressRecord(
        source=source,
        task_id=getattr(envelope, "task_id", ""),
        trace_id=getattr(envelope, "trace_id", ""),
        tool_name=getattr(envelope, "tool_name", ""),
        targets=list(getattr(envelope, "targets", []) or []),
        was_normalized=not is_canonical,
        legacy_reason="" if is_canonical else f"ingress from {source.value if isinstance(source, ExecutionIngressSource) else source}",
    )
    _append_ingress_record(rec)

    # 3. Obtain router if not supplied
    if router is None:
        try:
            from core.command_router import get_command_router
            router = get_command_router()
        except Exception as exc:
            return {
                "success": False,
                "error": f"execution_spine: CommandRouter unavailable: {exc}",
                "task_id": getattr(envelope, "task_id", ""),
                "trace_id": getattr(envelope, "trace_id", ""),
                "source": source.value if isinstance(source, ExecutionIngressSource) else str(source),
            }

    # 4. Enter canonical spine via CommandRouter.route_envelope
    try:
        return await router.route_envelope(envelope)
    except Exception as exc:
        return {
            "success": False,
            "error": f"execution_spine: route_envelope failed: {exc}",
            "task_id": getattr(envelope, "task_id", ""),
            "trace_id": getattr(envelope, "trace_id", ""),
            "source": source.value if isinstance(source, ExecutionIngressSource) else str(source),
        }


# ---------------------------------------------------------------------------
# Legacy ingress recorder (for non-spine paths that can't yet be migrated)
# ---------------------------------------------------------------------------

def record_legacy_ingress(
    source: ExecutionIngressSource,
    payload: Any,
    *,
    reason: str = "",
) -> IngressRecord:
    """Record a legacy ingress event without routing through the spine.

    Use this when a legacy path *cannot yet* be migrated to
    :func:`route_via_spine` but should still be surfaced in the ingress
    log for observability purposes.

    Parameters
    ----------
    source:
        Origin classification.
    payload:
        Raw payload (dict or object with ``to_dict()``).
    reason:
        Human-readable explanation of why this path is legacy.

    Returns
    -------
    IngressRecord
        The newly appended record.
    """
    raw: Dict[str, Any] = {}
    if isinstance(payload, dict):
        raw = payload
    elif hasattr(payload, "to_dict"):
        try:
            raw = payload.to_dict()
        except Exception:
            pass

    rec = IngressRecord(
        source=source,
        task_id=raw.get("task_id", ""),
        trace_id=raw.get("trace_id", ""),
        tool_name=(
            raw.get("tool_name")
            or raw.get("task_type")
            or raw.get("action")
            or raw.get("command")
            or ""
        ),
        targets=list(raw.get("targets") or []),
        was_normalized=True,
        legacy_reason=reason or f"legacy ingress from {source.value if isinstance(source, ExecutionIngressSource) else source}",
    )
    _append_ingress_record(rec)
    return rec
