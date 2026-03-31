"""
core/commands/router.py — Command Router Facade
================================================

**Batch PR-5: Command routing decomposition**

This module is the canonical facade entry point for the command routing
layer.  It re-exports the ``CommandRouter`` class and the public factory
function :func:`get_command_router` from the canonical implementation in
``core.command_router``.

Authority sentinel
------------------
``COMMAND_ROUTER_AUTHORITY = "core.commands.router"``

All downstream code should import from ``core.commands.router`` (or the
package root ``core.commands``) rather than reaching directly into
``core.command_router``.

Migration path
--------------
The canonical implementation currently lives in ``core.command_router``
(a single large module).  This facade allows call sites to adopt the
package-based import path incrementally; once the implementation is fully
decomposed the canonical path will remain ``core.commands.router``.
"""
from __future__ import annotations

# ── module authority sentinel ─────────────────────────────────────────────
COMMAND_ROUTER_AUTHORITY: str = "core.commands.router"
"""Sentinel: core.commands.router is the canonical command router facade.

Import this symbol to declare that a call site is using the canonical
command routing entry point.
"""

# ── re-export from canonical implementation ───────────────────────────────
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
    "COMMAND_ROUTER_AUTHORITY",
    "CommandRouter",
    "CommandRequest",
    "CommandResult",
    "CommandStatus",
    "CommandMode",
    "TargetResult",
    "GatewayError",
    "GatewayErrorCode",
    "validate_command_envelope",
    "get_command_router",
    "COMMAND_ROUTER_ORCHESTRATION_AUTHORITY",
]
