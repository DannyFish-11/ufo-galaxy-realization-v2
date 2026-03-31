"""
core/commands — Command Routing Subpackage
==========================================

**Batch PR-5: Command routing decomposition**

This package decomposes the command routing layer into explicit, testable
submodules while preserving the public API of ``core.command_router``.

Submodule responsibilities
--------------------------
router.py
    Facade and authority sentinel for ``CommandRouter``.  Public factory
    function :func:`get_command_router` lives here.

registry.py
    ``CommandRegistry`` — tracks registered command handlers by name.

dispatcher.py
    ``CommandDispatcher`` — low-level dispatch helpers: envelope creation,
    target iteration, result aggregation.

context.py
    ``CommandContext`` — per-request execution context (trace_id, source,
    metadata).

middleware.py
    ``CommandMiddleware`` ABC — before/after hooks for cross-cutting concerns
    (logging, auth, rate-limiting).

validators/
    ``CommandValidator`` base class and built-in validators (envelope
    completeness, ACL, risk classification).

handlers/
    ``CommandHandler`` base class and handler registration helpers.

Backward compatibility
----------------------
All public symbols from ``core.command_router`` are re-exported here so that
existing import paths continue to work without modification.

    from core.commands import CommandRouter, CommandRequest, get_command_router

Authority sentinel
------------------
``COMMAND_ROUTING_PACKAGE_AUTHORITY = "core.commands"``
"""
from __future__ import annotations

# ── package authority sentinel ────────────────────────────────────────────
COMMAND_ROUTING_PACKAGE_AUTHORITY: str = "core.commands"
"""Sentinel: core.commands is the canonical command routing package.

Import to assert that a call site is using the decomposed command routing
package rather than reaching directly into core.command_router internals.
"""

# ── backward-compat re-exports from canonical implementation ─────────────
from core.command_router import (  # noqa: F401
    CommandRouter,
    CommandRequest,
    CommandResult,
    CommandStatus,
    CommandMode,
    TargetResult,
    GatewayError,
    GatewayErrorCode,
    validate_command_envelope,
    get_command_router,
    COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
)

__all__ = [
    # package sentinel
    "COMMAND_ROUTING_PACKAGE_AUTHORITY",
    # router class + factory
    "CommandRouter",
    "get_command_router",
    # data models
    "CommandRequest",
    "CommandResult",
    "CommandStatus",
    "CommandMode",
    "TargetResult",
    # errors + validation
    "GatewayError",
    "GatewayErrorCode",
    "validate_command_envelope",
    # authority sentinels
    "COMMAND_ROUTER_ORCHESTRATION_AUTHORITY",
]
