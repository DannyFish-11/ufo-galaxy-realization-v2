"""
core/commands/middleware.py — Command Middleware
================================================

**Batch PR-5: Command routing decomposition**

This module defines the ``CommandMiddleware`` abstract base class, which
provides before/after hooks for cross-cutting concerns in the command
execution lifecycle (logging, authentication, rate-limiting, audit trail).

Authority sentinel
------------------
``COMMAND_MIDDLEWARE_AUTHORITY = "core.commands.middleware"``

Design
------
Middleware implementations follow the chain-of-responsibility pattern.
Each middleware receives the ``CommandContext`` and the *next* callable in
the chain.  It may:

1. Inspect / mutate the context before forwarding (pre-hook).
2. Call ``await next_handler(context)`` to continue the chain.
3. Inspect / mutate the result after returning (post-hook).
4. Short-circuit by raising an exception or returning a synthetic result.

Built-in middleware
-------------------
``LoggingMiddleware``
    Logs command entry/exit with trace_id, command, and latency.

``NoopMiddleware``
    Pass-through no-op (useful for testing).

Usage::

    from core.commands.middleware import LoggingMiddleware, NoopMiddleware

    chain = LoggingMiddleware(NoopMiddleware())
    result = await chain.process(ctx, handler)
"""
from __future__ import annotations

import abc
import logging
import time
from typing import Any, Awaitable, Callable

from core.commands.context import CommandContext

logger = logging.getLogger("Galaxy.Commands.Middleware")

# ── module authority sentinel ─────────────────────────────────────────────
COMMAND_MIDDLEWARE_AUTHORITY: str = "core.commands.middleware"
"""Sentinel: core.commands.middleware is the canonical command middleware module.

Import this symbol to assert that a call site is using the decomposed
middleware module.
"""

# ── type alias ────────────────────────────────────────────────────────────
NextHandler = Callable[[CommandContext], Awaitable[Any]]


class CommandMiddleware(abc.ABC):
    """Abstract base class for command execution middleware.

    Subclasses must implement :meth:`process`.

    Parameters
    ----------
    next_middleware:
        The next middleware in the chain.  May be ``None`` if this is the
        terminal middleware.
    """

    def __init__(self, next_middleware: "CommandMiddleware | None" = None) -> None:
        self._next = next_middleware

    @abc.abstractmethod
    async def process(
        self,
        context: CommandContext,
        handler: NextHandler,
    ) -> Any:
        """Process the command in *context*.

        Parameters
        ----------
        context:
            Immutable per-request execution context.
        handler:
            The terminal handler coroutine that performs actual execution.
            Middleware should call ``await handler(context)`` to forward.

        Returns
        -------
        Any:
            The result of the command execution (typically a
            ``CommandResult`` or a dict).
        """

    async def _call_next(
        self,
        context: CommandContext,
        handler: NextHandler,
    ) -> Any:
        """Convenience: call the next middleware or the handler directly."""
        if self._next is not None:
            return await self._next.process(context, handler)
        return await handler(context)


class LoggingMiddleware(CommandMiddleware):
    """Middleware that logs command entry/exit with latency."""

    async def process(self, context: CommandContext, handler: NextHandler) -> Any:
        start = time.monotonic()
        logger.info(
            "Command START | trace=%s cmd=%s source=%s",
            context.trace_id,
            context.command,
            context.source,
        )
        try:
            result = await self._call_next(context, handler)
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.info(
                "Command END   | trace=%s cmd=%s latency=%.1fms",
                context.trace_id,
                context.command,
                elapsed_ms,
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error(
                "Command ERROR | trace=%s cmd=%s latency=%.1fms error=%s",
                context.trace_id,
                context.command,
                elapsed_ms,
                exc,
            )
            raise


class NoopMiddleware(CommandMiddleware):
    """Pass-through middleware (useful for testing and as chain terminator)."""

    async def process(self, context: CommandContext, handler: NextHandler) -> Any:
        return await self._call_next(context, handler)


__all__ = [
    "COMMAND_MIDDLEWARE_AUTHORITY",
    "CommandMiddleware",
    "LoggingMiddleware",
    "NoopMiddleware",
    "NextHandler",
]
