#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canonical_execution_chain.py — Canonical Execution Chain Authority Declaration
====================================================================================

**Purpose**
-----------
This module declares the **single canonical execution authority chain** for the
Galaxy runtime.  It does NOT introduce new routing logic; it provides the
cross-cutting declarations that let all subsystems refer to one coherent
authority hierarchy.

Canonical execution chain::

    HTTP / WS request
        │  ← CHAIN_STAGE: ROUTE_INGRESS
        ▼
    core/routes/* (adapter / validator surface only — no orchestration authority)
        │  ← CHAIN_STAGE: ROUTE_ADAPTER
        ▼
    core/openclawd.py  ← OPENCLAWD_SUBJECT_AUTHORITY
        │   Subject/execution core.  Owns: intent resolution, execution-path
        │   branching (local / cross_device / hybrid / none), liminal lifecycle.
        │  ← CHAIN_STAGE: OPENCLAWD_SUBJECT
        ▼
    core/command_router.py  ← COMMAND_ROUTER_ORCHESTRATION_AUTHORITY
        │   Canonical command orchestration authority.  Owns: ACL enforcement,
        │   HITL gate, lifecycle state transitions, retry / circuit-breaker,
        │   trace propagation, TaskEnvelope plumbing.
        │  ← CHAIN_STAGE: COMMAND_ROUTER_ORCHESTRATION
        ▼
    galaxy_gateway/device_router.py  ← DEVICE_ROUTER_DISPATCH_AUTHORITY
        │   Canonical device dispatch authority.  Owns: WebSocket session
        │   management, live transport routing, connection-level retry.
        │  ← CHAIN_STAGE: DEVICE_ROUTER_DISPATCH
        ▼
    Device / transport execution
        │  ← CHAIN_STAGE: DEVICE_EXECUTION

Side-path modules (adapters / facades — NOT parallel authorities)
-----------------------------------------------------------------
The following modules remain as **compatibility adapters or internal
helpers**.  They MUST NOT be treated as parallel top-level authorities:

- ``core/e2e_orchestrator.py``           — convenience facade over the chain
- ``core/local_execution_chain.py``      — audit/projection helper for local path
- ``core/cross_device_execution_chain.py`` — audit/projection helper for cross-device path
- ``core/hybrid_executor.py``            — fallback-level execution helper
- ``core/remote_execution_mode_resolver.py`` — mode-resolution helper for CommandRouter
- ``core/repo_coordinator.py``           — legacy/management facade (demoted, PR-S4)
- ``galaxy_gateway/agent_bridge.py``     — runtime handoff adapter (Round 5)
- ``galaxy_gateway/task_router.py``      — legacy compatibility surface (PR-S6)
- ``galaxy_gateway/cross_device_coordinator.py`` — internal cross-device substrate
  called by DeviceRouter, not a primary entry

Authority invariants
--------------------
1. Every request entering through a route surface MUST be forwarded to
   ``OpenClawd`` (via ``DesktopPresenceRuntime`` or directly) as the
   subject/execution authority.
2. OpenClawd MUST use ``CommandRouter.route_envelope()`` for all device-bound
   command dispatch (cross-device branch).
3. CommandRouter MUST delegate device transport to ``DeviceRouter`` —
   it MUST NOT own WebSocket connections or transport state directly.
4. DeviceRouter is the sole component that holds active WebSocket/transport
   session handles.
5. Side-path modules invoked outside the canonical chain MUST be classified
   as ``"compat"`` or ``"legacy"`` in :mod:`core.mainline_convergence`.

Usage::

    from core.canonical_execution_chain import (
        CANONICAL_CHAIN_AUTHORITY,
        OPENCLAWD_SUBJECT_AUTHORITY,
        COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
        DEVICE_ROUTER_DISPATCH_AUTHORITY,
        CanonicalChainStage,
        CHAIN_STAGE_AUTHORITY,
        build_chain_context,
    )
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CanonicalExecutionChain")

# ---------------------------------------------------------------------------
# Module-level authority sentinels
# ---------------------------------------------------------------------------

CANONICAL_CHAIN_AUTHORITY: str = "core.canonical_execution_chain"
"""Sentinel: identifies this module as the canonical chain authority
declaration.  Import this symbol to assert that a call site is operating
within the declared canonical execution chain."""

OPENCLAWD_SUBJECT_AUTHORITY: str = "core.openclawd.OpenClawd"
"""Sentinel: ``OpenClawd`` is the subject/execution core and top-level
orchestration authority.  All requests MUST pass through OpenClawd before
reaching CommandRouter or DeviceRouter."""

COMMAND_ROUTER_ORCHESTRATION_AUTHORITY: str = "core.command_router.CommandRouter"
"""Sentinel: ``CommandRouter`` is the canonical command orchestration
authority.  It owns ACL enforcement, HITL gating, lifecycle transitions,
retry / circuit-breaker, and TaskEnvelope propagation.  It MUST be the
single orchestration decision-maker after OpenClawd accepts a request."""

DEVICE_ROUTER_DISPATCH_AUTHORITY: str = "galaxy_gateway.device_router.DeviceRouter"
"""Sentinel: ``DeviceRouter`` is the canonical device dispatch authority.
It owns WebSocket/transport session handles and all device-level routing.
CommandRouter MUST delegate transport to DeviceRouter; no other module
should own live device connections."""

ROUTE_ADAPTER_ROLE: str = "route_adapter"
"""Role label for route-layer modules.  Route modules are **adapter surfaces**
only — they validate and translate HTTP/WS requests into canonical chain calls.
They MUST NOT contain orchestration or dispatch logic."""

SIDE_PATH_FACADE_ROLE: str = "side_path_facade"
"""Role label for side-path modules that have been demoted to compatibility
facades/adapters.  These modules may remain but MUST NOT act as parallel
top-level authorities."""


# ---------------------------------------------------------------------------
# Canonical chain stages
# ---------------------------------------------------------------------------

class CanonicalChainStage(str, Enum):
    """Ordered stages of the canonical execution chain.

    These labels are used for structured logging, tracing, and observability.
    Every significant hop in the canonical path maps to exactly one stage.
    """

    ROUTE_INGRESS = "route_ingress"
    """External request arrives at the route adapter layer."""

    ROUTE_ADAPTER = "route_adapter"
    """Route module validates / translates the request (no orchestration)."""

    OPENCLAWD_SUBJECT = "openclawd_subject"
    """OpenClawd acts as subject/execution core — intent resolution and
    execution-path branching."""

    COMMAND_ROUTER_ORCHESTRATION = "command_router_orchestration"
    """CommandRouter performs orchestration: ACL, HITL, lifecycle, retry,
    TaskEnvelope construction."""

    DEVICE_ROUTER_DISPATCH = "device_router_dispatch"
    """DeviceRouter dispatches to the target device via transport."""

    DEVICE_EXECUTION = "device_execution"
    """Target device / transport executes the command."""

    RESPONSE_RETURN = "response_return"
    """Result propagates back through the chain to the caller."""


# Map each canonical stage to the owning authority sentinel.
CHAIN_STAGE_AUTHORITY: Dict[CanonicalChainStage, str] = {
    CanonicalChainStage.ROUTE_INGRESS:               ROUTE_ADAPTER_ROLE,
    CanonicalChainStage.ROUTE_ADAPTER:               ROUTE_ADAPTER_ROLE,
    CanonicalChainStage.OPENCLAWD_SUBJECT:           OPENCLAWD_SUBJECT_AUTHORITY,
    CanonicalChainStage.COMMAND_ROUTER_ORCHESTRATION: COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
    CanonicalChainStage.DEVICE_ROUTER_DISPATCH:      DEVICE_ROUTER_DISPATCH_AUTHORITY,
    CanonicalChainStage.DEVICE_EXECUTION:            DEVICE_ROUTER_DISPATCH_AUTHORITY,
    CanonicalChainStage.RESPONSE_RETURN:             OPENCLAWD_SUBJECT_AUTHORITY,
}

# Ordered list of canonical stages (route → device).
CANONICAL_STAGE_ORDER: tuple = (
    CanonicalChainStage.ROUTE_INGRESS,
    CanonicalChainStage.ROUTE_ADAPTER,
    CanonicalChainStage.OPENCLAWD_SUBJECT,
    CanonicalChainStage.COMMAND_ROUTER_ORCHESTRATION,
    CanonicalChainStage.DEVICE_ROUTER_DISPATCH,
    CanonicalChainStage.DEVICE_EXECUTION,
    CanonicalChainStage.RESPONSE_RETURN,
)


# ---------------------------------------------------------------------------
# Side-path module registry
# ---------------------------------------------------------------------------

#: Modules that have been demoted to adapter / facade / helper status.
#: They MUST NOT act as parallel top-level dispatch authorities.
SIDE_PATH_MODULE_REGISTRY: Dict[str, str] = {
    "core.e2e_orchestrator": SIDE_PATH_FACADE_ROLE,
    "core.local_execution_chain": "audit_helper",
    "core.cross_device_execution_chain": "audit_helper",
    "core.hybrid_executor": "fallback_execution_helper",
    "core.remote_execution_mode_resolver": "mode_resolution_helper",
    "core.repo_coordinator": "legacy_management_facade",
    "galaxy_gateway.agent_bridge": "runtime_handoff_adapter",
    "galaxy_gateway.task_router": "legacy_compat_surface",
    "galaxy_gateway.cross_device_coordinator": "internal_cross_device_substrate",
}


# ---------------------------------------------------------------------------
# Chain execution context
# ---------------------------------------------------------------------------

@dataclass
class ChainExecutionContext:
    """Portable context object carried through the canonical execution chain.

    Components that participate in the canonical chain should accept or
    produce a :class:`ChainExecutionContext` to ensure trace identifiers,
    authority declarations, and stage labels travel end-to-end without
    being dropped.

    This dataclass intentionally uses only stdlib types so it can be
    imported from any module without circular dependency risk.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    trace_id: str = field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:12]}")
    """Distributed trace identifier — generated at ROUTE_INGRESS and
    propagated unchanged through every hop."""

    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:16]}")
    """Unique task identifier for this request."""

    session_id: str = ""
    """Session scope — ties multiple requests to one user interaction."""

    device_id: str = ""
    """Target device identifier (empty = local / unrouted)."""

    # ── Stage tracking ───────────────────────────────────────────────────────
    current_stage: str = CanonicalChainStage.ROUTE_INGRESS.value
    """Most recently reached canonical chain stage."""

    stages_visited: List[str] = field(default_factory=list)
    """Ordered list of canonical stage values visited so far."""

    # ── Authority ────────────────────────────────────────────────────────────
    current_authority: str = ROUTE_ADAPTER_ROLE
    """Authority sentinel of the component currently handling the request."""

    # ── Timestamps ──────────────────────────────────────────────────────────
    ingress_ts: float = field(default_factory=time.time)
    """Unix timestamp when the request entered the chain."""

    last_stage_ts: float = field(default_factory=time.time)
    """Unix timestamp of the most recent stage transition."""

    # ── Extra metadata ───────────────────────────────────────────────────────
    extra: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata forwarded from ingress (e.g. source, entry_mode)."""

    def advance_stage(self, stage: CanonicalChainStage) -> "ChainExecutionContext":
        """Record a stage transition and update authority.

        Returns ``self`` for chaining.
        """
        self.current_stage = stage.value
        self.current_authority = CHAIN_STAGE_AUTHORITY.get(stage, "unknown")
        if stage.value not in self.stages_visited:
            self.stages_visited.append(stage.value)
        self.last_stage_ts = time.time()
        logger.debug(
            "CanonicalChain.advance_stage | trace_id=%s stage=%s authority=%s",
            self.trace_id, stage.value, self.current_authority,
        )
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "current_stage": self.current_stage,
            "current_authority": self.current_authority,
            "stages_visited": list(self.stages_visited),
            "ingress_ts": self.ingress_ts,
            "last_stage_ts": self.last_stage_ts,
            "extra": self.extra,
        }


def build_chain_context(
    *,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: str = "",
    device_id: str = "",
    source: str = "",
    entry_mode: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> ChainExecutionContext:
    """Construct a :class:`ChainExecutionContext` at chain entry.

    This should be called at the route-layer boundary (ROUTE_INGRESS) so
    that a consistent context object travels through the entire chain.

    Args:
        trace_id:   Existing trace identifier; a new UUID is generated when
                    ``None``.
        task_id:    Existing task identifier; a new UUID is generated when
                    ``None``.
        session_id: Optional session scope.
        device_id:  Optional target device.
        source:     Human-readable label of the calling surface (e.g.
                    ``"chat"``, ``"command"``).
        entry_mode: Execution mode resolved at route layer (``"local"`` /
                    ``"cross_device"``).
        extra:      Arbitrary additional context.

    Returns:
        A :class:`ChainExecutionContext` pre-stamped at the
        ``ROUTE_INGRESS`` stage.
    """
    ctx = ChainExecutionContext(
        trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
        task_id=task_id or f"task_{uuid.uuid4().hex[:16]}",
        session_id=session_id,
        device_id=device_id,
        extra={
            "source": source,
            "entry_mode": entry_mode,
            **(extra or {}),
        },
    )
    ctx.advance_stage(CanonicalChainStage.ROUTE_INGRESS)
    return ctx


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------

def is_canonical_module(module_name: str) -> bool:
    """Return ``True`` when *module_name* is one of the three canonical
    authority components (OpenClawd, CommandRouter, DeviceRouter)."""
    return module_name in (
        OPENCLAWD_SUBJECT_AUTHORITY,
        COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
        DEVICE_ROUTER_DISPATCH_AUTHORITY,
    )


def get_side_path_role(module_name: str) -> Optional[str]:
    """Return the demoted role for a side-path module, or ``None`` if the
    module is not in the side-path registry."""
    return SIDE_PATH_MODULE_REGISTRY.get(module_name)


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "CANONICAL_CHAIN_AUTHORITY",
    "OPENCLAWD_SUBJECT_AUTHORITY",
    "COMMAND_ROUTER_ORCHESTRATION_AUTHORITY",
    "DEVICE_ROUTER_DISPATCH_AUTHORITY",
    "ROUTE_ADAPTER_ROLE",
    "SIDE_PATH_FACADE_ROLE",
    # Enums / mappings
    "CanonicalChainStage",
    "CHAIN_STAGE_AUTHORITY",
    "CANONICAL_STAGE_ORDER",
    "SIDE_PATH_MODULE_REGISTRY",
    # Dataclasses / functions
    "ChainExecutionContext",
    "build_chain_context",
    "is_canonical_module",
    "get_side_path_role",
]
