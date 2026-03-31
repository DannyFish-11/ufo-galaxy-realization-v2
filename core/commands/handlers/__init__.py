"""
core/commands/handlers — Command Handler Subpackage
====================================================

**Batch PR-5: Command routing decomposition**

This sub-package provides the ``CommandHandler`` abstract base class and
helpers for building structured command handlers in the Galaxy runtime.

Authority sentinel
------------------
``COMMAND_HANDLER_AUTHORITY = "core.commands.handlers"``

Design
------
``CommandHandler`` is a callable ABC.  Each concrete handler corresponds to
one command name and is responsible for:

1. Receiving a ``CommandContext`` and ``params`` dict.
2. Performing the command action (usually delegated to a device adapter).
3. Returning a result dict compatible with ``TargetResult.result``.

Handlers are registered via ``CommandRegistry``:

    from core.commands.registry import get_command_registry
    from core.commands.handlers import CommandHandler

    class ScreenshotHandler(CommandHandler):
        command_name = "screenshot"

        async def execute(self, context, params):
            ...
            return {"image_url": "..."}

    registry = get_command_registry()
    registry.register_handler("screenshot", ScreenshotHandler())
"""
from __future__ import annotations

import abc
import logging
from typing import Any, Dict, Optional

from core.commands.context import CommandContext

logger = logging.getLogger("Galaxy.Commands.Handlers")

# ── sub-package authority sentinel ────────────────────────────────────────
COMMAND_HANDLER_AUTHORITY: str = "core.commands.handlers"
"""Sentinel: core.commands.handlers is the canonical command handler module.

Import this symbol to assert that a call site is using the decomposed
handler sub-package.
"""


class CommandHandler(abc.ABC):
    """Abstract base class for a command handler.

    Concrete subclasses must:
    1. Set the class attribute ``command_name``.
    2. Implement :meth:`execute`.

    Handlers are stateless; they must not store per-request state as
    instance attributes.
    """

    #: The command name this handler is responsible for.
    command_name: str = ""

    @abc.abstractmethod
    async def execute(
        self,
        context: CommandContext,
        params: Dict[str, Any],
    ) -> Any:
        """Execute the command and return the result.

        Parameters
        ----------
        context:
            Immutable per-request execution context (trace_id, source, …).
        params:
            Command parameters forwarded from the ``CommandRequest``.

        Returns
        -------
        Any:
            A JSON-serializable result object.  Typically a dict.

        Raises
        ------
        Exception:
            Any exception raised here will be caught by the dispatcher and
            stored as a failure result for the target.
        """

    async def __call__(
        self,
        context: CommandContext,
        params: Dict[str, Any],
    ) -> Any:
        """Make handlers callable (forwards to :meth:`execute`)."""
        return await self.execute(context, params)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(command_name={self.command_name!r})"


class NoopHandler(CommandHandler):
    """No-op handler that returns an empty result dict.

    Useful as a placeholder during development or in tests.
    """

    command_name = "__noop__"

    async def execute(
        self,
        context: CommandContext,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        logger.debug(
            "NoopHandler.execute | trace=%s command=%s",
            context.trace_id,
            context.command,
        )
        return {"noop": True, "command": context.command}


__all__ = [
    "COMMAND_HANDLER_AUTHORITY",
    "CommandHandler",
    "NoopHandler",
]
