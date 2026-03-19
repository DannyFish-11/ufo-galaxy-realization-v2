#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/state_event_bus.py
=======================
PR-8 — Unified State Event Bus

Provides an in-process publish/subscribe event bus for connecting phase
transitions, task lifecycle events, skill/tool invocations, executor
actions, and device state updates under a single ``trace_id`` and
``runtime_session_id``.

Design goals
------------
- **Additive** — existing code continues to work unchanged; the bus is an
  *optional* observability layer.  All integration points use best-effort
  (try/except) imports.
- **Async-safe** — subscribers may be sync *or* async callables; async
  subscribers are dispatched via ``asyncio.create_task`` when a running loop
  is present.
- **Structured** — every event carries a canonical set of fields so
  downstream consumers can build traces, dashboards, and alerts without
  parsing free-form strings.

Quick start::

    from core.state_event_bus import get_state_event_bus, StateEventType

    bus = get_state_event_bus()

    # Subscribe
    def my_listener(event):
        print(event.type, event.trace_id, event.payload)

    token = bus.subscribe(StateEventType.TASK_STARTED, my_listener)

    # Publish
    bus.publish(StateEventType.TASK_STARTED, source="my_module", payload={
        "task_id": "t-123",
        "tool_name": "list_files",
    }, trace_id="abc", runtime_session_id="sess-xyz")

    # Unsubscribe
    bus.unsubscribe(token)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union

logger = logging.getLogger("Galaxy.StateEventBus")


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class StateEventType(str, Enum):
    """Canonical event types emitted by the unified state event bus.

    Naming convention: ``<domain>.<action>``
    """

    # ── Phase / tri-state transitions ─────────────────────────────────────
    PHASE_SILENT    = "phase.silent"    # session entered SILENT state
    PHASE_LIMINAL   = "phase.liminal"   # session entered LIMINAL state
    PHASE_MANIFEST  = "phase.manifest"  # session entered MANIFEST state

    # ── Task lifecycle ─────────────────────────────────────────────────────
    TASK_STARTED    = "task.started"    # task transitioned to 'running'
    TASK_DONE       = "task.done"       # task completed successfully
    TASK_FAILED     = "task.failed"     # task failed

    # ── Skill / tool invocation ────────────────────────────────────────────
    SKILL_INVOKED   = "skill.invoked"   # skill/MCP tool call started
    SKILL_DONE      = "skill.done"      # skill/MCP tool call succeeded
    SKILL_FAILED    = "skill.failed"    # skill/MCP tool call failed

    # ── Executor / device actions ──────────────────────────────────────────
    EXECUTOR_START  = "executor.start"  # execution action started
    EXECUTOR_DONE   = "executor.done"   # execution action finished
    EXECUTOR_FAIL   = "executor.fail"   # execution action failed

    # ── Device state ───────────────────────────────────────────────────────
    DEVICE_UPDATED  = "device.updated"  # device state / capability updated

    # ── Generic / passthrough ─────────────────────────────────────────────
    GENERIC         = "generic"         # uncategorised event


# ---------------------------------------------------------------------------
# Event schema
# ---------------------------------------------------------------------------

@dataclass
class StateEvent:
    """Standard event envelope emitted on the unified state event bus.

    Attributes:
        type:               One of :class:`StateEventType` (stored as its
                            string value for easy serialisation).
        timestamp:          Unix timestamp (seconds since epoch, float).
        trace_id:           End-to-end correlation identifier.  Created if
                            not supplied.
        runtime_session_id: Runtime session identifier.  Defaults to
                            ``trace_id`` when not supplied.
        source:             Module / component that published the event.
        payload:            Arbitrary structured data specific to the event
                            type.
        event_id:           Unique identifier for this particular event
                            instance.
    """

    type: str
    source: str
    payload: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    runtime_session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if not self.runtime_session_id:
            self.runtime_session_id = self.trace_id

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain-dict representation suitable for JSON serialisation."""
        return {
            "event_id": self.event_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "source": self.source,
            "payload": self.payload,
        }


# ---------------------------------------------------------------------------
# Subscription token
# ---------------------------------------------------------------------------

@dataclass
class SubscriptionToken:
    """Opaque handle returned by :meth:`StateEventBus.subscribe`.

    Pass it back to :meth:`StateEventBus.unsubscribe` to remove the listener.
    """

    event_type: Optional[str]   # None means "wildcard" (all types)
    callback: Callable
    token_id: str = field(default_factory=lambda: uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# StateEventBus
# ---------------------------------------------------------------------------

class StateEventBus:
    """In-process publish/subscribe event bus with async-safe delivery.

    Subscribers may be registered for a specific :class:`StateEventType` or
    as *wildcard* listeners that receive every event regardless of type.

    Thread / async safety
    ~~~~~~~~~~~~~~~~~~~~~
    * :meth:`publish` can be called from any thread; it always dispatches
      synchronously to each subscriber in turn.
    * Async subscribers (``asyncio.iscoroutinefunction(cb) == True``) are
      wrapped in ``asyncio.create_task`` when a running event loop is
      available, ensuring they don't block the caller.
    * When no event loop is running the async subscriber is skipped with a
      debug log rather than raising an exception.

    Usage::

        bus = StateEventBus()
        token = bus.subscribe(StateEventType.TASK_STARTED, my_handler)
        bus.publish(StateEventType.TASK_STARTED, source="test", payload={})
        bus.unsubscribe(token)
    """

    def __init__(self) -> None:
        # type_key → list of SubscriptionToken
        self._subscribers: Dict[Optional[str], List[SubscriptionToken]] = {}
        self._all_tokens: Dict[str, SubscriptionToken] = {}

    # ── Subscribe / unsubscribe ────────────────────────────────────────────

    def subscribe(
        self,
        event_type: Optional[Union[StateEventType, str]],
        callback: Callable[[StateEvent], Any],
    ) -> SubscriptionToken:
        """Register *callback* to receive events of *event_type*.

        Args:
            event_type: The event type to listen for, or ``None`` / omitted
                        to receive *all* events (wildcard).
            callback:   A callable (sync or async) that accepts a single
                        :class:`StateEvent` argument.

        Returns:
            A :class:`SubscriptionToken` that can be passed to
            :meth:`unsubscribe`.
        """
        key: Optional[str] = (
            event_type.value if isinstance(event_type, StateEventType) else event_type
        )
        token = SubscriptionToken(event_type=key, callback=callback)
        self._subscribers.setdefault(key, []).append(token)
        self._all_tokens[token.token_id] = token
        logger.debug(
            "StateEventBus: subscribed token=%s event_type=%s",
            token.token_id, key,
        )
        return token

    def unsubscribe(self, token: SubscriptionToken) -> bool:
        """Remove a previously registered subscription.

        Args:
            token: The token returned by :meth:`subscribe`.

        Returns:
            ``True`` if the subscription was found and removed, ``False``
            otherwise.
        """
        if token.token_id not in self._all_tokens:
            return False
        bucket = self._subscribers.get(token.event_type, [])
        try:
            bucket.remove(token)
        except ValueError:
            pass
        self._all_tokens.pop(token.token_id, None)
        logger.debug(
            "StateEventBus: unsubscribed token=%s event_type=%s",
            token.token_id, token.event_type,
        )
        return True

    # ── Publish ────────────────────────────────────────────────────────────

    def publish(
        self,
        event_type: Union[StateEventType, str],
        *,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
        event: Optional[StateEvent] = None,
    ) -> StateEvent:
        """Publish an event to all matching subscribers.

        You may either supply individual fields (the common case) or pass a
        pre-constructed :class:`StateEvent` via the *event* keyword.

        Args:
            event_type:          The type of the event.
            source:              Emitting module/component name.
            payload:             Structured data specific to the event.
            trace_id:            End-to-end correlation ID (generated if
                                 omitted).
            runtime_session_id:  Runtime session ID (defaults to trace_id).
            event:               Pre-constructed :class:`StateEvent`; when
                                 supplied all other arguments are ignored.

        Returns:
            The :class:`StateEvent` that was dispatched.
        """
        if event is None:
            type_str = (
                event_type.value
                if isinstance(event_type, StateEventType)
                else str(event_type)
            )
            event = StateEvent(
                type=type_str,
                source=source,
                payload=payload or {},
                trace_id=trace_id or uuid.uuid4().hex,
                runtime_session_id=runtime_session_id or "",
            )

        self._dispatch(event)
        return event

    # Alias for callers that prefer a method name consistent with the
    # existing integration.event_bus interface.
    publish_sync = publish

    def _dispatch(self, event: StateEvent) -> None:
        """Deliver *event* to all matching subscribers (type-specific + wildcard)."""
        buckets: List[List[SubscriptionToken]] = []
        type_bucket = self._subscribers.get(event.type)
        if type_bucket:
            buckets.append(list(type_bucket))
        wildcard_bucket = self._subscribers.get(None)
        if wildcard_bucket:
            buckets.append(list(wildcard_bucket))

        for bucket in buckets:
            for token in bucket:
                try:
                    if asyncio.iscoroutinefunction(token.callback):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(token.callback(event))  # type: ignore[arg-type]
                        except RuntimeError:
                            # No running loop — skip async subscriber gracefully.
                            logger.debug(
                                "StateEventBus: async subscriber skipped (no loop) "
                                "token=%s event=%s",
                                token.token_id, event.type,
                            )
                    else:
                        token.callback(event)
                except Exception as exc:
                    logger.warning(
                        "StateEventBus: subscriber raised token=%s event=%s: %s",
                        token.token_id, event.type, exc,
                    )

    # ── Diagnostics ───────────────────────────────────────────────────────

    def subscriber_count(self, event_type: Optional[Union[StateEventType, str]] = None) -> int:
        """Return the number of subscribers for *event_type* (or total if ``None``)."""
        if event_type is None:
            return len(self._all_tokens)
        key = (
            event_type.value
            if isinstance(event_type, StateEventType)
            else event_type
        )
        return len(self._subscribers.get(key, []))

    def clear(self) -> None:
        """Remove all subscriptions (useful in tests)."""
        self._subscribers.clear()
        self._all_tokens.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_state_event_bus: Optional[StateEventBus] = None


def get_state_event_bus() -> StateEventBus:
    """Return (or lazily create) the process-wide :class:`StateEventBus` singleton."""
    global _state_event_bus
    if _state_event_bus is None:
        _state_event_bus = StateEventBus()
    return _state_event_bus


def reset_state_event_bus() -> None:
    """Reset the singleton — intended for use in tests only."""
    global _state_event_bus
    _state_event_bus = None


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def emit(
    event_type: Union[StateEventType, str],
    source: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> None:
    """Best-effort publish to the global state event bus.

    Never raises; any exception is swallowed and logged at DEBUG level so
    that callers in critical paths are not affected.

    Usage::

        from core.state_event_bus import emit, StateEventType

        emit(StateEventType.TASK_STARTED, "my_module", {
            "task_id": task.id,
        }, trace_id=trace_id, runtime_session_id=session_id)
    """
    try:
        get_state_event_bus().publish(
            event_type,
            source=source,
            payload=payload or {},
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )
    except Exception as _exc:
        logger.debug("state_event_bus.emit failed (non-fatal): %s", _exc)
