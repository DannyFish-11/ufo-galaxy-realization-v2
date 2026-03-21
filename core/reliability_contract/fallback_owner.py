#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.reliability_contract.fallback_owner
==========================================

PR-19 (V4) — Reliability Contract & Delivery Semantics

Defines the :class:`FallbackOwner` enum, which classifies *which component*
is responsible for deciding and executing the fallback when a delivery path
fails or times out.

Fallback Owner Definitions
---------------------------
+---------------------+----------------------------------------------------------+
| Owner               | Meaning                                                  |
+=====================+==========================================================+
| LOCAL_FALLBACK      | A local agent or local-device runtime executes the       |
|                     | fallback (e.g. AgentBridge local_fallback path).         |
+---------------------+----------------------------------------------------------+
| TRANSPORT_FALLBACK  | The transport layer retries or falls back to an          |
|                     | alternative transport (e.g. WebSocket → HTTP fallback).  |
+---------------------+----------------------------------------------------------+
| REROUTE_OWNER       | The routing layer (CommandRouter, device_router) decides |
|                     | to reroute to a different device or executor.            |
+---------------------+----------------------------------------------------------+
| COORDINATOR         | The orchestration coordinator (TaskOrchestrator,         |
|                     | GlobalArbiter) decides the fallback — e.g. rescheduling, |
|                     | splitting, or aborting the task.                         |
+---------------------+----------------------------------------------------------+
| ABORT_OWNER         | The component that owns the abort decision.  Failure     |
|                     | propagates upward and the task is cancelled.             |
+---------------------+----------------------------------------------------------+
| CALLER              | The caller/client is responsible for deciding what to    |
|                     | do when the path fails (e.g. user-facing HITL).          |
+---------------------+----------------------------------------------------------+
| UNSPECIFIED         | Fallback ownership has not been declared.                |
+---------------------+----------------------------------------------------------+

Design notes
-------------
Fallback ownership is **advisory** — it documents who *should* own the
fallback decision.  Actual enforcement lives in AgentBridge, TaskOrchestrator,
and CommandRouter.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict

__all__ = [
    "FallbackOwner",
    "FALLBACK_OWNER_DESCRIPTIONS",
    "fallback_owner_description",
]


class FallbackOwner(str, Enum):
    """Taxonomy of fallback ownership for Galaxy runtime message paths.

    String values are stable identifiers safe for serialisation.
    """

    LOCAL_FALLBACK = "local_fallback"
    """Local agent/runtime executes fallback (AgentBridge local_fallback)."""

    TRANSPORT_FALLBACK = "transport_fallback"
    """Transport layer retries or switches to an alternative channel."""

    REROUTE_OWNER = "reroute_owner"
    """Routing layer reroutes to a different device or executor."""

    COORDINATOR = "coordinator"
    """Orchestration coordinator decides: reschedule, split, or abort."""

    ABORT_OWNER = "abort_owner"
    """Failure propagates upward; task is cancelled."""

    CALLER = "caller"
    """Caller/client decides the fallback (e.g. HITL confirmation)."""

    UNSPECIFIED = "unspecified"
    """Fallback ownership not yet declared."""


# ---------------------------------------------------------------------------
# Human-readable descriptions
# ---------------------------------------------------------------------------

FALLBACK_OWNER_DESCRIPTIONS: Dict[str, str] = {
    FallbackOwner.LOCAL_FALLBACK.value: (
        "A local agent or local-device runtime executes the fallback. "
        "Corresponds to the AgentBridge local_fallback execution path. "
        "The RECOVERY agent role takes ownership."
    ),
    FallbackOwner.TRANSPORT_FALLBACK.value: (
        "The transport layer handles the fallback, such as retrying over "
        "an alternative channel (e.g. HTTP when WebSocket is unavailable)."
    ),
    FallbackOwner.REROUTE_OWNER.value: (
        "The routing layer (CommandRouter or device_router) decides to "
        "reroute the task to a different device or executor after failure."
    ),
    FallbackOwner.COORDINATOR.value: (
        "The orchestration coordinator (TaskOrchestrator, GlobalArbiter, "
        "e2e_orchestrator) decides the fallback strategy: reschedule, "
        "split, merge, or abort."
    ),
    FallbackOwner.ABORT_OWNER.value: (
        "The failure propagates upward and the task is cancelled. "
        "The abort decision is owned by the component that initiated the task."
    ),
    FallbackOwner.CALLER.value: (
        "The caller or client is responsible for deciding the fallback. "
        "Typically applies to HITL paths or user-facing interactive flows."
    ),
    FallbackOwner.UNSPECIFIED.value: (
        "Fallback ownership has not been declared for this path."
    ),
}


def fallback_owner_description(owner: FallbackOwner) -> str:
    """Return the human-readable description for *owner*."""
    return FALLBACK_OWNER_DESCRIPTIONS.get(owner.value, "Unknown fallback owner.")
