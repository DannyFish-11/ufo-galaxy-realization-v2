#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.reliability_contract.timeout_owner
==========================================

PR-19 (V4) — Reliability Contract & Delivery Semantics

Defines the :class:`TimeoutOwner` enum, which classifies *which component*
is responsible for enforcing the timeout on a given message path.

Timeout Owner Definitions
--------------------------
+-------------------+----------------------------------------------------------+
| Owner             | Meaning                                                  |
+===================+==========================================================+
| TRANSPORT         | The transport layer (WebSocket, NATS, HTTP) enforces     |
|                   | connection/message-level timeouts.                       |
+-------------------+----------------------------------------------------------+
| ROUTER            | The routing layer (CommandRouter, device_router) holds   |
|                   | the dispatch timeout.                                    |
+-------------------+----------------------------------------------------------+
| RUNTIME           | The runtime bridge (AgentBridge, local_agent_runtime)    |
|                   | enforces handoff/execution timeouts.                     |
+-------------------+----------------------------------------------------------+
| COORDINATOR       | The orchestration coordinator (TaskOrchestrator,         |
|                   | GlobalArbiter, e2e_orchestrator) holds the end-to-end    |
|                   | task timeout.                                            |
+-------------------+----------------------------------------------------------+
| CALLER            | The caller/client is responsible for enforcing its own   |
|                   | timeout (e.g. a HITL wait or an async API consumer).     |
+-------------------+----------------------------------------------------------+
| UNSPECIFIED       | Timeout ownership has not been declared.  Treat as       |
|                   | best-effort (no timeout guarantee).                      |
+-------------------+----------------------------------------------------------+

Design notes
-------------
Timeout ownership is **advisory** — it documents who *should* enforce the
timeout, not who *does*.  The distinction matters because some paths may not
yet have explicit timeout enforcement; this annotation makes the gap visible.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict

__all__ = [
    "TimeoutOwner",
    "TIMEOUT_OWNER_DESCRIPTIONS",
    "timeout_owner_description",
]


class TimeoutOwner(str, Enum):
    """Taxonomy of timeout ownership for Galaxy runtime message paths.

    String values are stable identifiers safe for serialisation.
    """

    TRANSPORT = "transport"
    """Transport layer (WebSocket, NATS, HTTP) enforces timeout."""

    ROUTER = "router"
    """Routing layer (CommandRouter, device_router) holds dispatch timeout."""

    RUNTIME = "runtime"
    """Runtime bridge (AgentBridge, local_agent_runtime) enforces handoff/exec timeout."""

    COORDINATOR = "coordinator"
    """Orchestration coordinator (TaskOrchestrator, GlobalArbiter) holds end-to-end timeout."""

    CALLER = "caller"
    """Caller/client enforces its own timeout."""

    UNSPECIFIED = "unspecified"
    """Timeout ownership not yet declared.  Treat as best-effort."""


# ---------------------------------------------------------------------------
# Human-readable descriptions
# ---------------------------------------------------------------------------

TIMEOUT_OWNER_DESCRIPTIONS: Dict[str, str] = {
    TimeoutOwner.TRANSPORT.value: (
        "The transport layer (WebSocket, NATS, HTTP) is responsible for "
        "enforcing connection-level and message-level timeouts. Examples: "
        "WebSocket ping/pong timeout, NATS consumer ack timeout."
    ),
    TimeoutOwner.ROUTER.value: (
        "The routing layer is responsible for enforcing dispatch timeouts. "
        "CommandRouter and device_router may apply deadline propagation."
    ),
    TimeoutOwner.RUNTIME.value: (
        "The runtime bridge (AgentBridge / local_agent_runtime) enforces "
        "handoff and execution timeouts. HandoffPolicy.handoff_timeout_hint_ms "
        "is the advisory source."
    ),
    TimeoutOwner.COORDINATOR.value: (
        "The orchestration coordinator (TaskOrchestrator, GlobalArbiter, "
        "e2e_orchestrator) holds the end-to-end task deadline. This is the "
        "highest-level timeout in the execution lifecycle."
    ),
    TimeoutOwner.CALLER.value: (
        "The caller or API client is responsible for enforcing its own "
        "timeout. The Galaxy runtime does not guarantee a timeout for this path."
    ),
    TimeoutOwner.UNSPECIFIED.value: (
        "Timeout ownership has not been declared for this path. "
        "Treat as best-effort — no timeout guarantee."
    ),
}


def timeout_owner_description(owner: TimeoutOwner) -> str:
    """Return the human-readable description for *owner*."""
    return TIMEOUT_OWNER_DESCRIPTIONS.get(owner.value, "Unknown timeout owner.")
