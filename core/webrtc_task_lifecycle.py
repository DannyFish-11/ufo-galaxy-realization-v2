"""core/webrtc_task_lifecycle.py
====================================
PR-6: WebRTC Task-Lifecycle Integration
========================================

**Canonical authority for integrating WebRTC/media transport state with the
Galaxy center-side task lifecycle.**

Background
----------
Prior to this module the WebRTC subsystem operated as an isolated transport
path: sessions were started by direct WebSocket connection outside the task
lifecycle, and no canonical mechanism existed to:

1. Bind a WebRTC session to a ``CanonicalTask`` at the point of task setup.
2. React to transport-state changes (reconnecting, degraded, failed) by
   advancing the task lifecycle in a principled, governed way.
3. Tear down a WebRTC session when the associated task reaches a terminal
   lifecycle state (COMPLETED, FAILED, CANCELLED).

This module closes those gaps.  It does **not** own the transport; it owns the
**integration** between transport-state signals and task-lifecycle decisions.

Design principles
-----------------
- **Task-scoped binding** — every WebRTC session that serves a task is
  represented by a :class:`WebRTCTaskBinding` record that ties the WebRTC
  session ID to the task's ``task_id`` and ``device_id``.
- **Transport state → lifecycle action** — when transport state changes the
  runtime determines the correct lifecycle action via
  :func:`classify_transport_lifecycle_action`, which is purely functional and
  testable.
- **Terminal task → session teardown** — reaching a terminal ``TaskLifecycle``
  state (COMPLETED / FAILED / CANCELLED) triggers session teardown via
  :func:`teardown_binding_on_task_terminal`.
- **Degraded continuation** — if transport degrades but remains usable
  (``WebRTCTransportState.degraded``) the task advances to
  ``TaskLifecycle.DEGRADED`` rather than FAILED, allowing the caller to
  continue with reduced quality.
- **Additive only** — does not modify any other existing module.
- **Fully serialisable** — all dataclasses expose ``to_dict()`` /
  ``from_dict()`` / ``to_json()``.

Relationship to other modules
-------------------------------
* ``core.canonical_task`` — provides ``TaskLifecycle`` and
  ``CanonicalTaskRuntime``; this module reacts to task lifecycle states and
  may advance them.
* ``core.attached_runtime_session`` — session attachment state may trigger
  transport state changes; this module treats those as input signals.
* ``core.multimodal.webrtc_session_manager`` — the ``WebRTCSessionManager``
  emits transport-state events; callers are expected to relay those events
  to :func:`apply_transport_state_to_task_lifecycle`.

Public API
----------
Sentinels::

    WEBRTC_TASK_LIFECYCLE_AUTHORITY
    WEBRTC_SESSION_MUST_BE_TASK_SCOPED_POLICY
    TRANSPORT_STATE_DRIVES_LIFECYCLE_ACTION_POLICY
    TERMINAL_TASK_TRIGGERS_SESSION_TEARDOWN_POLICY
    DEGRADED_TRANSPORT_YIELDS_DEGRADED_TASK_POLICY
    FAILED_TRANSPORT_YIELDS_FAILED_TASK_POLICY
    RECONNECTED_TRANSPORT_RESUMES_RUNNING_TASK_POLICY
    BINDING_IS_TASK_SCOPED_SINGLE_SESSION_POLICY
    TEARDOWN_IS_IDEMPOTENT_POLICY
    SESSION_BINDING_RECORD_IS_IMMUTABLE_POLICY
    WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL

Enums::

    WebRTCTransportState
    WebRTCTaskLifecycleAction

Dataclasses::

    WebRTCTaskBinding
    WebRTCTaskBindingSnapshot

Classes::

    WebRTCTaskSessionRegistry

Functions::

    bind_webrtc_session_to_task(task_id, webrtc_session_id, device_id, ...) -> WebRTCTaskBinding
    classify_transport_lifecycle_action(task_lifecycle, transport_state) -> WebRTCTaskLifecycleAction
    apply_transport_state_to_task_lifecycle(binding, transport_state, runtime=None) -> WebRTCTaskBinding
    teardown_binding_on_task_terminal(task_id, lifecycle_state, runtime=None) -> bool
    get_webrtc_task_binding(task_id) -> WebRTCTaskBinding | None
    list_active_webrtc_task_bindings() -> list[WebRTCTaskBinding]
    build_webrtc_task_binding_snapshot() -> WebRTCTaskBindingSnapshot
    get_webrtc_task_session_registry() -> WebRTCTaskSessionRegistry
    reset_webrtc_task_session_registry() -> None
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.WebRTCTaskLifecycle")

__all__ = [
    # Authority
    "WEBRTC_TASK_LIFECYCLE_AUTHORITY",
    "WEBRTC_SESSION_MUST_BE_TASK_SCOPED_POLICY",
    "TRANSPORT_STATE_DRIVES_LIFECYCLE_ACTION_POLICY",
    "TERMINAL_TASK_TRIGGERS_SESSION_TEARDOWN_POLICY",
    "DEGRADED_TRANSPORT_YIELDS_DEGRADED_TASK_POLICY",
    "FAILED_TRANSPORT_YIELDS_FAILED_TASK_POLICY",
    "RECONNECTED_TRANSPORT_RESUMES_RUNNING_TASK_POLICY",
    "BINDING_IS_TASK_SCOPED_SINGLE_SESSION_POLICY",
    "TEARDOWN_IS_IDEMPOTENT_POLICY",
    "SESSION_BINDING_RECORD_IS_IMMUTABLE_POLICY",
    "WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL",
    # Enums
    "WebRTCTransportState",
    "WebRTCTaskLifecycleAction",
    # Dataclasses
    "WebRTCTaskBinding",
    "WebRTCTaskBindingSnapshot",
    # Class
    "WebRTCTaskSessionRegistry",
    # Functions
    "bind_webrtc_session_to_task",
    "classify_transport_lifecycle_action",
    "apply_transport_state_to_task_lifecycle",
    "teardown_binding_on_task_terminal",
    "get_webrtc_task_binding",
    "list_active_webrtc_task_bindings",
    "build_webrtc_task_binding_snapshot",
    "get_webrtc_task_session_registry",
    "reset_webrtc_task_session_registry",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

WEBRTC_TASK_LIFECYCLE_AUTHORITY: str = (
    "WEBRTC_TASK_LIFECYCLE_AUTHORITY::core.webrtc_task_lifecycle is the "
    "canonical authority for integrating WebRTC/media transport state with "
    "the Galaxy center-side canonical task lifecycle (PR-6, post-533 "
    "dual-repo runtime unification)."
)

WEBRTC_SESSION_MUST_BE_TASK_SCOPED_POLICY: str = (
    "POLICY::WEBRTC_SESSION_MUST_BE_TASK_SCOPED: any WebRTC session that "
    "serves a task MUST be bound to that task via bind_webrtc_session_to_task() "
    "before the task is dispatched.  Unbound WebRTC sessions are transport-layer "
    "artifacts with no canonical lifecycle governance."
)

TRANSPORT_STATE_DRIVES_LIFECYCLE_ACTION_POLICY: str = (
    "POLICY::TRANSPORT_STATE_DRIVES_LIFECYCLE_ACTION: when the transport "
    "state of a task-bound WebRTC session changes, apply_transport_state_to_task_lifecycle() "
    "is the single canonical path for translating that change into a task "
    "lifecycle action.  No other code path may advance task lifecycle in "
    "response to transport state changes."
)

TERMINAL_TASK_TRIGGERS_SESSION_TEARDOWN_POLICY: str = (
    "POLICY::TERMINAL_TASK_TRIGGERS_SESSION_TEARDOWN: when a task reaches "
    "a terminal lifecycle state (COMPLETED, FAILED, CANCELLED), the associated "
    "WebRTC session binding MUST be torn down via teardown_binding_on_task_terminal(). "
    "Active transport connections should be closed as part of this teardown."
)

DEGRADED_TRANSPORT_YIELDS_DEGRADED_TASK_POLICY: str = (
    "POLICY::DEGRADED_TRANSPORT_YIELDS_DEGRADED_TASK: if the WebRTC transport "
    "degrades but remains usable (packet loss high, bitrate low, but frames "
    "still arriving), the associated task MUST advance to TaskLifecycle.DEGRADED "
    "rather than FAILED.  The caller may choose to continue, reshape, or "
    "explicitly fail the task based on application semantics."
)

FAILED_TRANSPORT_YIELDS_FAILED_TASK_POLICY: str = (
    "POLICY::FAILED_TRANSPORT_YIELDS_FAILED_TASK: if the WebRTC transport "
    "fails permanently (max reconnects exhausted, session error with "
    "recoverable=False), the associated task MUST advance to TaskLifecycle.FAILED "
    "with failure_domain=TRANSPORT."
)

RECONNECTED_TRANSPORT_RESUMES_RUNNING_TASK_POLICY: str = (
    "POLICY::RECONNECTED_TRANSPORT_RESUMES_RUNNING_TASK: if the WebRTC "
    "transport reconnects successfully after a transient failure, the associated "
    "task (if in DEGRADED or RUNNING state) MUST be updated to reflect that "
    "the transport is again available.  Tasks in terminal states are not affected."
)

BINDING_IS_TASK_SCOPED_SINGLE_SESSION_POLICY: str = (
    "POLICY::BINDING_IS_TASK_SCOPED_SINGLE_SESSION: each task has at most one "
    "active WebRTC task binding.  Re-binding a task replaces the previous "
    "binding record and marks the old one as superseded."
)

TEARDOWN_IS_IDEMPOTENT_POLICY: str = (
    "POLICY::TEARDOWN_IS_IDEMPOTENT: calling teardown_binding_on_task_terminal() "
    "for a task that has no active binding, or for a binding that has already "
    "been torn down, is a no-op and does not raise an error."
)

SESSION_BINDING_RECORD_IS_IMMUTABLE_POLICY: str = (
    "POLICY::SESSION_BINDING_RECORD_IS_IMMUTABLE: WebRTCTaskBinding records "
    "are immutable value objects.  Lifecycle progression is modelled by "
    "creating a new record (with the same binding_id) and registering it, "
    "not by mutating existing records in-place."
)

WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL: str = (
    "WEBRTC_TASK_LIFECYCLE_PR6::webrtc-task-lifecycle-integration-"
    "center-side-canonical-pr6-v1"
)


# ---------------------------------------------------------------------------
# PR-AIPV3-WEBRTC: AIP v3 message emission for WebRTC control plane
# ---------------------------------------------------------------------------

def _emit_aip_v3_webrtc_bind(binding: "WebRTCTaskBinding") -> None:
    """Emit WEBRTC_BIND AIP v3 message when a session is bound to a task.

    Best-effort: published via NATS if connected, otherwise logged only.
    """
    try:
        import asyncio
        from core.schemas.aip_v3 import WebRTCBindMsg  # noqa: PLC0415
        from core.nats_bus import get_nats_bus  # noqa: PLC0415

        msg = WebRTCBindMsg(
            device_id=binding.device_id,
            webrtc_session_id=binding.webrtc_session_id,
            bind_target="task",
        )
        nats = get_nats_bus()
        if nats.is_connected():
            asyncio.get_event_loop().create_task(nats.publish_webrtc_bind(msg))
        else:
            logger.debug("AIPV3-WEBRTC BIND: %s", msg.model_dump_json(exclude_none=True))
    except Exception:
        pass


def _emit_aip_v3_webrtc_transport_state(
    binding: "WebRTCTaskBinding",
    transport_state: "WebRTCTransportState",
) -> None:
    """Emit WEBRTC_TRANSPORT_STATE AIP v3 message on transport state change.

    Best-effort: published via NATS if connected, otherwise logged only.
    """
    try:
        import asyncio
        from core.schemas.aip_v3 import WebRTCTransportStateMsg  # noqa: PLC0415
        from core.nats_bus import get_nats_bus  # noqa: PLC0415

        msg = WebRTCTransportStateMsg(
            device_id=binding.device_id,
            webrtc_session_id=binding.webrtc_session_id,
            transport_state=transport_state.value if hasattr(transport_state, "value") else str(transport_state),
            previous_state=binding.transport_state.value if hasattr(binding.transport_state, "value") else str(binding.transport_state),
        )
        nats = get_nats_bus()
        if nats.is_connected():
            asyncio.get_event_loop().create_task(nats.publish_webrtc_transport_state(msg))
        else:
            logger.debug("AIPV3-WEBRTC STATE: %s", msg.model_dump_json(exclude_none=True))
    except Exception:
        pass


def _emit_aip_v3_webrtc_unbind(binding: "WebRTCTaskBinding") -> None:
    """Emit WEBRTC_UNBIND AIP v3 message when a binding is torn down.

    Best-effort: published via NATS if connected, otherwise logged only.
    """
    try:
        import asyncio
        from core.schemas.aip_v3 import WebRTCUnbindMsg  # noqa: PLC0415
        from core.nats_bus import get_nats_bus  # noqa: PLC0415

        msg = WebRTCUnbindMsg(
            device_id=binding.device_id,
            webrtc_session_id=binding.webrtc_session_id,
            reason="task_terminal",
        )
        nats = get_nats_bus()
        if nats.is_connected():
            asyncio.get_event_loop().create_task(nats.publish_webrtc_unbind(msg))
        else:
            logger.debug("AIPV3-WEBRTC UNBIND: %s", msg.model_dump_json(exclude_none=True))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY = 128

# ---------------------------------------------------------------------------
# WebRTCTransportState
# ---------------------------------------------------------------------------


class WebRTCTransportState(str, Enum):
    """Lifecycle states of a task-bound WebRTC transport connection.

    These states model the transport reality from the perspective of the
    center-side runtime.  They are derived from events emitted by
    :class:`~core.multimodal.webrtc_session_manager.WebRTCSessionManager`
    and from attachment lifecycle signals.

    connected
        The WebRTC peer connection is established and frames/data are flowing.
    reconnecting
        The connection was lost and the session manager is attempting to
        reconnect.  The task is temporarily without media input.
    degraded
        The connection is alive but quality metrics indicate degraded
        operation (high packet loss, low bitrate, stale frames).  Media
        input is still available but may be unreliable.
    failed
        The transport has permanently failed (max reconnects exhausted or
        unrecoverable error).  The task cannot proceed with media input.
    closed
        The transport was intentionally closed (e.g. as part of task
        teardown or explicit session close).
    unknown
        Transport state not yet determined or not applicable.
    """

    connected = "connected"
    reconnecting = "reconnecting"
    degraded = "degraded"
    failed = "failed"
    closed = "closed"
    unknown = "unknown"

    @classmethod
    def from_string(
        cls, value: str, default: "WebRTCTransportState" = None
    ) -> "WebRTCTransportState":
        """Parse *value* into a :class:`WebRTCTransportState`.

        Returns *default* (or ``unknown``) for unrecognised values.
        """
        try:
            return cls(value)
        except ValueError:
            return default if default is not None else cls.unknown

    @property
    def is_terminal(self) -> bool:
        """True if this transport state is terminal (no recovery possible)."""
        return self in (WebRTCTransportState.failed, WebRTCTransportState.closed)

    @property
    def is_usable(self) -> bool:
        """True if media can still flow through this transport state."""
        return self in (WebRTCTransportState.connected, WebRTCTransportState.degraded)


# ---------------------------------------------------------------------------
# WebRTCTaskLifecycleAction
# ---------------------------------------------------------------------------


class WebRTCTaskLifecycleAction(str, Enum):
    """Governance action to take on a task when WebRTC transport state changes.

    continue_running
        Transport is healthy; task should continue in its current state.
    degrade
        Transport is degraded; task should advance to TaskLifecycle.DEGRADED.
    recover
        Transport recovered after degradation or reconnect; task can resume
        normal execution (advance from DEGRADED back toward RUNNING).
    terminate_failed
        Transport has permanently failed; task must be advanced to FAILED.
    terminate_cancelled
        Transport was intentionally closed before task completion; task must
        be advanced to CANCELLED.
    no_change
        No lifecycle change required (e.g. terminal task, no bound session).
    """

    continue_running = "continue_running"
    degrade = "degrade"
    recover = "recover"
    terminate_failed = "terminate_failed"
    terminate_cancelled = "terminate_cancelled"
    no_change = "no_change"


# ---------------------------------------------------------------------------
# WebRTCTaskBinding — core record
# ---------------------------------------------------------------------------


@dataclass
class WebRTCTaskBinding:
    """Record of the binding between a canonical task and a WebRTC session.

    A binding is established when a task that requires live media input from
    an Android device is created.  It is torn down when the task reaches a
    terminal lifecycle state.

    Attributes
    ----------
    binding_id          Unique identifier for this binding record.
    task_id             Identifier of the bound :class:`~core.canonical_task.CanonicalTask`.
    webrtc_session_id   Identifier of the associated WebRTC session (from
                        :class:`~core.multimodal.webrtc_session_manager.WebRTCSessionManager`).
    device_id           Identifier of the Android device providing the media stream.
    transport_state     Current transport state (updated on each state change event).
    task_lifecycle      Most recently observed task lifecycle state.
    is_torn_down        True once teardown_binding_on_task_terminal() has been called.
    bound_at            Wall-clock timestamp when the binding was created.
    torn_down_at        Wall-clock timestamp when teardown was triggered (None if active).
    last_transition_at  Wall-clock timestamp of the last transport-state change.
    metadata            Arbitrary extra context (trace_id, session_id, etc.).
    """

    binding_id: str = field(default_factory=lambda: f"wbind_{uuid.uuid4().hex[:16]}")
    task_id: str = ""
    webrtc_session_id: str = ""
    device_id: str = ""
    transport_state: WebRTCTransportState = WebRTCTransportState.unknown
    task_lifecycle: str = "created"
    is_torn_down: bool = False
    bound_at: float = field(default_factory=time.time)
    torn_down_at: Optional[float] = None
    last_transition_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True if the binding is established and not yet torn down."""
        return not self.is_torn_down and self.transport_state not in (
            WebRTCTransportState.failed,
            WebRTCTransportState.closed,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "binding_id": self.binding_id,
            "task_id": self.task_id,
            "webrtc_session_id": self.webrtc_session_id,
            "device_id": self.device_id,
            "transport_state": self.transport_state.value
            if isinstance(self.transport_state, WebRTCTransportState)
            else str(self.transport_state),
            "task_lifecycle": self.task_lifecycle,
            "is_torn_down": self.is_torn_down,
            "bound_at": self.bound_at,
            "torn_down_at": self.torn_down_at,
            "last_transition_at": self.last_transition_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "WebRTCTaskBinding":
        """Deserialise a :class:`WebRTCTaskBinding` from *data*.

        Raises ``ValueError`` if *data* is not a dict.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"WebRTCTaskBinding.from_dict expects a dict, got {type(data).__name__!r}"
            )
        transport_state_raw = data.get("transport_state", "unknown")
        transport_state = WebRTCTransportState.from_string(
            transport_state_raw, default=WebRTCTransportState.unknown
        )
        return cls(
            binding_id=data.get("binding_id", f"wbind_{uuid.uuid4().hex[:16]}"),
            task_id=data.get("task_id", ""),
            webrtc_session_id=data.get("webrtc_session_id", ""),
            device_id=data.get("device_id", ""),
            transport_state=transport_state,
            task_lifecycle=data.get("task_lifecycle", "created"),
            is_torn_down=bool(data.get("is_torn_down", False)),
            bound_at=float(data.get("bound_at", time.time())),
            torn_down_at=data.get("torn_down_at"),
            last_transition_at=data.get("last_transition_at"),
            metadata=dict(data.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# WebRTCTaskBindingSnapshot
# ---------------------------------------------------------------------------


@dataclass
class WebRTCTaskBindingSnapshot:
    """Point-in-time snapshot of the WebRTCTaskSessionRegistry state."""

    total_bindings: int = 0
    active_bindings: int = 0
    torn_down_bindings: int = 0
    bindings_by_transport_state: Dict[str, int] = field(default_factory=dict)
    records: List[Dict[str, Any]] = field(default_factory=list)
    snapshot_id: str = field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:12]}")
    snapshotted_at: float = field(default_factory=time.time)
    policy_sentinels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_bindings": self.total_bindings,
            "active_bindings": self.active_bindings,
            "torn_down_bindings": self.torn_down_bindings,
            "bindings_by_transport_state": self.bindings_by_transport_state,
            "records": self.records,
            "snapshot_id": self.snapshot_id,
            "snapshotted_at": self.snapshotted_at,
            "policy_sentinels": self.policy_sentinels,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# WebRTCTaskSessionRegistry — singleton registry
# ---------------------------------------------------------------------------


class WebRTCTaskSessionRegistry:
    """Ring-buffer registry tracking task-to-WebRTC-session bindings.

    Provides:
    - Push and update of :class:`WebRTCTaskBinding` records.
    - Lookup by ``task_id`` (most-recent binding).
    - Listing of active (non-torn-down) bindings.
    - Snapshot for operator observability.

    This is a lightweight in-process registry.  It is not a persistence layer.
    The capacity defaults to 128 entries; the oldest entry is evicted when full.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._ring: Deque[WebRTCTaskBinding] = deque(maxlen=capacity)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def push(self, binding: WebRTCTaskBinding) -> None:
        """Append *binding* to the ring buffer."""
        self._ring.append(binding)
        logger.debug(
            "WebRTCTaskSessionRegistry.push | task_id=%s session_id=%s transport=%s",
            binding.task_id,
            binding.webrtc_session_id,
            binding.transport_state.value
            if isinstance(binding.transport_state, WebRTCTransportState)
            else binding.transport_state,
        )

    def replace_latest_for_task(self, binding: WebRTCTaskBinding) -> None:
        """Replace the most-recent binding for *binding.task_id*.

        If no prior binding exists for that task the record is appended.
        The replacement is performed in a single pass: the latest index for
        the task is found while building the updated deque.
        """
        updated: Deque[WebRTCTaskBinding] = deque(maxlen=self._capacity)
        latest_idx: Optional[int] = None
        entries = list(self._ring)
        # Find the index of the most-recent record for this task_id
        for i, rec in enumerate(entries):
            if rec.task_id == binding.task_id:
                latest_idx = i
        # Build the updated deque in a single pass, replacing only at latest_idx
        replaced = False
        for i, rec in enumerate(entries):
            if i == latest_idx and not replaced:
                updated.append(binding)
                replaced = True
            else:
                updated.append(rec)
        if not replaced:
            updated.append(binding)
        self._ring = updated

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_latest_for_task(self, task_id: str) -> Optional[WebRTCTaskBinding]:
        """Return the most-recent binding for *task_id*, or ``None``."""
        result: Optional[WebRTCTaskBinding] = None
        for rec in self._ring:
            if rec.task_id == task_id:
                result = rec
        return result

    def list_all(self) -> List[WebRTCTaskBinding]:
        """Return all bindings (oldest-first)."""
        return list(self._ring)

    def list_active(self) -> List[WebRTCTaskBinding]:
        """Return all bindings where ``is_active`` is True (most recent per task)."""
        latest: Dict[str, WebRTCTaskBinding] = {}
        for rec in self._ring:
            latest[rec.task_id] = rec
        return [r for r in latest.values() if r.is_active]

    def size(self) -> int:
        """Return the current number of entries in the ring buffer."""
        return len(self._ring)

    def capacity(self) -> int:
        """Return the ring buffer capacity."""
        return self._capacity

    def clear(self) -> None:
        """Clear the ring buffer (for testing)."""
        self._ring.clear()


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_registry_instance: Optional[WebRTCTaskSessionRegistry] = None


def get_webrtc_task_session_registry() -> WebRTCTaskSessionRegistry:
    """Return the process-global :class:`WebRTCTaskSessionRegistry` singleton."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = WebRTCTaskSessionRegistry()
    return _registry_instance


def reset_webrtc_task_session_registry() -> None:
    """Reset the singleton (for testing only)."""
    global _registry_instance
    _registry_instance = None


# ---------------------------------------------------------------------------
# Public API — binding operations
# ---------------------------------------------------------------------------


def bind_webrtc_session_to_task(
    task_id: str,
    webrtc_session_id: str,
    device_id: str,
    *,
    initial_transport_state: WebRTCTransportState = WebRTCTransportState.connected,
    task_lifecycle: str = "running",
    metadata: Optional[Dict[str, Any]] = None,
    registry: Optional[WebRTCTaskSessionRegistry] = None,
) -> WebRTCTaskBinding:
    """Create and register a binding between *task_id* and *webrtc_session_id*.

    Parameters
    ----------
    task_id
        Identifier of the :class:`~core.canonical_task.CanonicalTask`.
    webrtc_session_id
        Identifier of the WebRTC session (from
        :class:`~core.multimodal.webrtc_session_manager.WebRTCSessionManager`).
    device_id
        Android device providing the media stream.
    initial_transport_state
        Transport state at the moment of binding (default: ``connected``).
    task_lifecycle
        Current task lifecycle state string (for informational tracking).
    metadata
        Arbitrary extra context (trace_id, session_id, etc.).
    registry
        Registry instance (uses singleton if ``None``).

    Returns
    -------
    WebRTCTaskBinding
        The newly created binding record.
    """
    reg = registry or get_webrtc_task_session_registry()
    binding = WebRTCTaskBinding(
        task_id=task_id,
        webrtc_session_id=webrtc_session_id,
        device_id=device_id,
        transport_state=initial_transport_state,
        task_lifecycle=task_lifecycle,
        metadata=dict(metadata or {}),
        bound_at=time.time(),
        last_transition_at=time.time(),
    )
    reg.replace_latest_for_task(binding)
    logger.info(
        "WebRTC session bound to task | task_id=%s session_id=%s device_id=%s",
        task_id,
        webrtc_session_id,
        device_id,
    )
    # PR-AIPV3-WEBRTC: Emit WEBRTC_BIND AIP v3 message
    _emit_aip_v3_webrtc_bind(binding)
    return binding


def classify_transport_lifecycle_action(
    task_lifecycle: str,
    transport_state: "WebRTCTransportState | str",
) -> WebRTCTaskLifecycleAction:
    """Determine the lifecycle governance action for a task given a transport-state change.

    This is a **pure function** — it takes no side effects and is safe to call
    in tests or planning contexts.

    Parameters
    ----------
    task_lifecycle
        Current lifecycle state of the task (string or ``TaskLifecycle`` value).
    transport_state
        The new transport state signal.

    Returns
    -------
    WebRTCTaskLifecycleAction
        The governance action to apply.

    Decision table
    ~~~~~~~~~~~~~~
    +-----------------------+---------------------+---------------------------+
    | transport_state       | task_lifecycle      | action                    |
    +=======================+=====================+===========================+
    | connected             | any non-terminal    | continue_running          |
    +-----------------------+---------------------+---------------------------+
    | connected             | terminal            | no_change                 |
    +-----------------------+---------------------+---------------------------+
    | reconnecting          | any non-terminal    | degrade (temporarily      |
    |                       |                     | without media)            |
    +-----------------------+---------------------+---------------------------+
    | degraded              | any non-terminal    | degrade                   |
    +-----------------------+---------------------+---------------------------+
    | degraded / reconnecting| terminal           | no_change                 |
    +-----------------------+---------------------+---------------------------+
    | failed                | any non-terminal    | terminate_failed          |
    +-----------------------+---------------------+---------------------------+
    | failed                | terminal            | no_change                 |
    +-----------------------+---------------------+---------------------------+
    | closed                | any non-terminal    | terminate_cancelled       |
    +-----------------------+---------------------+---------------------------+
    | closed                | terminal            | no_change                 |
    +-----------------------+---------------------+---------------------------+
    | unknown               | any                 | no_change                 |
    +-----------------------+---------------------+---------------------------+
    """
    _TERMINAL_LIFECYCLES = {"completed", "failed", "cancelled"}

    # Normalise transport state
    if isinstance(transport_state, str):
        transport_state = WebRTCTransportState.from_string(transport_state)

    # Normalise task lifecycle
    task_lc = task_lifecycle.lower() if isinstance(task_lifecycle, str) else str(task_lifecycle)
    is_terminal = task_lc in _TERMINAL_LIFECYCLES

    if transport_state == WebRTCTransportState.unknown:
        return WebRTCTaskLifecycleAction.no_change

    if is_terminal:
        return WebRTCTaskLifecycleAction.no_change

    if transport_state == WebRTCTransportState.connected:
        # If the task was previously degraded and transport is now connected,
        # signal recovery; otherwise just continue.
        if task_lc == "degraded":
            return WebRTCTaskLifecycleAction.recover
        return WebRTCTaskLifecycleAction.continue_running

    if transport_state in (WebRTCTransportState.reconnecting, WebRTCTransportState.degraded):
        return WebRTCTaskLifecycleAction.degrade

    if transport_state == WebRTCTransportState.failed:
        return WebRTCTaskLifecycleAction.terminate_failed

    if transport_state == WebRTCTransportState.closed:
        return WebRTCTaskLifecycleAction.terminate_cancelled

    return WebRTCTaskLifecycleAction.no_change


def apply_transport_state_to_task_lifecycle(
    binding: WebRTCTaskBinding,
    transport_state: "WebRTCTransportState | str",
    *,
    runtime: Any = None,
    registry: Optional[WebRTCTaskSessionRegistry] = None,
) -> WebRTCTaskBinding:
    """Apply a transport-state change to the task lifecycle via *binding*.

    This is the **canonical path** for translating WebRTC transport-state
    events into task lifecycle changes.  It:

    1. Classifies the governance action via :func:`classify_transport_lifecycle_action`.
    2. Applies the action to the :class:`~core.canonical_task.CanonicalTask`
       via *runtime* (if provided).
    3. Updates the binding record with the new transport state.
    4. Persists the updated record to the registry.

    Parameters
    ----------
    binding
        Current binding record for the task.
    transport_state
        New transport state signal.
    runtime
        Optional :class:`~core.canonical_task.CanonicalTaskRuntime` instance.
        If provided, the task lifecycle will be advanced via
        ``runtime.update_lifecycle()``.
    registry
        Registry instance (uses singleton if ``None``).

    Returns
    -------
    WebRTCTaskBinding
        Updated binding record (original is not mutated).
    """
    from dataclasses import replace as _replace

    if isinstance(transport_state, str):
        transport_state = WebRTCTransportState.from_string(transport_state)

    action = classify_transport_lifecycle_action(binding.task_lifecycle, transport_state)
    new_task_lifecycle = binding.task_lifecycle

    # Apply action to runtime if provided
    if runtime is not None and action != WebRTCTaskLifecycleAction.no_change:
        try:
            from core.canonical_task import TaskLifecycle

            _ACTION_TO_LIFECYCLE = {
                WebRTCTaskLifecycleAction.degrade: TaskLifecycle.DEGRADED,
                WebRTCTaskLifecycleAction.terminate_failed: TaskLifecycle.FAILED,
                WebRTCTaskLifecycleAction.terminate_cancelled: TaskLifecycle.CANCELLED,
            }
            target_lc = _ACTION_TO_LIFECYCLE.get(action)
            if target_lc is not None:
                updated_task = runtime.update_lifecycle(binding.task_id, target_lc)
                if updated_task is not None:
                    new_task_lifecycle = updated_task.lifecycle.value
                    logger.info(
                        "WebRTC transport state changed task lifecycle | "
                        "task_id=%s transport=%s action=%s lifecycle=%s",
                        binding.task_id,
                        transport_state.value,
                        action.value,
                        new_task_lifecycle,
                    )
            elif action == WebRTCTaskLifecycleAction.recover:
                # Recover: attempt to advance back to RUNNING
                updated_task = runtime.update_lifecycle(
                    binding.task_id, TaskLifecycle.RUNNING
                )
                if updated_task is not None:
                    new_task_lifecycle = updated_task.lifecycle.value
                    logger.info(
                        "WebRTC transport recovered, task resumed running | "
                        "task_id=%s",
                        binding.task_id,
                    )
        except Exception as exc:
            logger.debug(
                "WebRTC task lifecycle update skipped (runtime error): %s", exc
            )

    # Build updated binding (immutable record pattern)
    updated_binding = _replace(
        binding,
        transport_state=transport_state,
        task_lifecycle=new_task_lifecycle,
        last_transition_at=time.time(),
    )

    # Persist
    reg = registry or get_webrtc_task_session_registry()
    reg.replace_latest_for_task(updated_binding)

    logger.debug(
        "apply_transport_state_to_task_lifecycle | task_id=%s transport=%s action=%s",
        binding.task_id,
        transport_state.value,
        action.value,
    )
    # PR-AIPV3-WEBRTC: Emit WEBRTC_TRANSPORT_STATE AIP v3 message
    _emit_aip_v3_webrtc_transport_state(binding, transport_state)
    return updated_binding


def teardown_binding_on_task_terminal(
    task_id: str,
    lifecycle_state: "str | Any",
    *,
    registry: Optional[WebRTCTaskSessionRegistry] = None,
) -> bool:
    """Tear down the WebRTC session binding when *task_id* reaches a terminal state.

    This function is idempotent — calling it for a task with no active binding,
    or for a binding that is already torn down, is a safe no-op.

    Parameters
    ----------
    task_id
        Identifier of the task that has reached a terminal lifecycle state.
    lifecycle_state
        The terminal lifecycle state (used for logging/metadata only).
    registry
        Registry instance (uses singleton if ``None``).

    Returns
    -------
    bool
        ``True`` if a binding was found and marked as torn down; ``False`` if
        no active binding existed (idempotent no-op path).
    """
    from dataclasses import replace as _replace

    reg = registry or get_webrtc_task_session_registry()
    binding = reg.get_latest_for_task(task_id)
    if binding is None or binding.is_torn_down:
        logger.debug(
            "teardown_binding_on_task_terminal | task_id=%s — no active binding (idempotent)",
            task_id,
        )
        return False

    lc_str = (
        lifecycle_state.value
        if hasattr(lifecycle_state, "value")
        else str(lifecycle_state)
    )
    torn_down_binding = _replace(
        binding,
        is_torn_down=True,
        torn_down_at=time.time(),
        transport_state=WebRTCTransportState.closed,
        task_lifecycle=lc_str,
        last_transition_at=time.time(),
    )
    reg.replace_latest_for_task(torn_down_binding)
    logger.info(
        "WebRTC task binding torn down | task_id=%s lifecycle=%s session_id=%s device_id=%s",
        task_id,
        lc_str,
        binding.webrtc_session_id,
        binding.device_id,
    )
    # PR-AIPV3-WEBRTC: Emit WEBRTC_UNBIND AIP v3 message
    _emit_aip_v3_webrtc_unbind(binding)
    return True


# ---------------------------------------------------------------------------
# Public API — queries
# ---------------------------------------------------------------------------


def get_webrtc_task_binding(
    task_id: str,
    *,
    registry: Optional[WebRTCTaskSessionRegistry] = None,
) -> Optional[WebRTCTaskBinding]:
    """Return the most-recent binding record for *task_id*, or ``None``."""
    reg = registry or get_webrtc_task_session_registry()
    return reg.get_latest_for_task(task_id)


def list_active_webrtc_task_bindings(
    *,
    registry: Optional[WebRTCTaskSessionRegistry] = None,
) -> List[WebRTCTaskBinding]:
    """Return all currently active (non-torn-down) bindings."""
    reg = registry or get_webrtc_task_session_registry()
    return reg.list_active()


def build_webrtc_task_binding_snapshot(
    *,
    registry: Optional[WebRTCTaskSessionRegistry] = None,
) -> WebRTCTaskBindingSnapshot:
    """Build a point-in-time snapshot of the registry state."""
    reg = registry or get_webrtc_task_session_registry()
    all_bindings = reg.list_all()
    active = [b for b in all_bindings if b.is_active]
    torn = [b for b in all_bindings if b.is_torn_down]

    by_state: Dict[str, int] = {}
    for b in all_bindings:
        state_val = (
            b.transport_state.value
            if isinstance(b.transport_state, WebRTCTransportState)
            else str(b.transport_state)
        )
        by_state[state_val] = by_state.get(state_val, 0) + 1

    return WebRTCTaskBindingSnapshot(
        total_bindings=len(all_bindings),
        active_bindings=len(active),
        torn_down_bindings=len(torn),
        bindings_by_transport_state=by_state,
        records=[b.to_dict() for b in reversed(all_bindings)],
        policy_sentinels={
            "WEBRTC_TASK_LIFECYCLE_AUTHORITY": WEBRTC_TASK_LIFECYCLE_AUTHORITY,
            "WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL": WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL,
        },
    )
