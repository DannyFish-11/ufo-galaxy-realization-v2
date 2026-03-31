"""
core/commands/registry.py — Command Handler Registry
=====================================================

**Batch PR-5: Command routing decomposition**

This module provides the ``CommandRegistry`` class, which tracks registered
command handlers by command name.  Handlers are registered with an optional
set of required capabilities so the registry can perform capability-aware
lookups.

Authority sentinel
------------------
``COMMAND_REGISTRY_AUTHORITY = "core.commands.registry"``

Design
------
The registry is intentionally thin:

* It stores a mapping from command name → handler callable.
* It provides lookup by exact name.
* It does NOT perform dispatch — that is the responsibility of
  ``core.commands.dispatcher.CommandDispatcher``.
* It does NOT perform validation — that is the responsibility of
  ``core.commands.validators``.

Usage::

    from core.commands.registry import CommandRegistry

    registry = CommandRegistry()

    @registry.register("screenshot")
    async def handle_screenshot(context, params):
        ...

    handler = registry.get("screenshot")
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.Commands.Registry")

# ── module authority sentinel ─────────────────────────────────────────────
COMMAND_REGISTRY_AUTHORITY: str = "core.commands.registry"
"""Sentinel: core.commands.registry is the canonical command handler registry.

Import this symbol to assert that a call site is using the decomposed
registry module rather than ad-hoc handler lookup logic.
"""


class CommandRegistry:
    """Registry that maps command names to their handler callables.

    Parameters
    ----------
    name:
        Optional human-readable label for this registry (used in log
        messages and introspection).
    """

    def __init__(self, name: str = "default") -> None:
        self._name = name
        self._handlers: Dict[str, Callable[..., Any]] = {}
        self._capabilities: Dict[str, List[str]] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        command: str,
        required_capabilities: Optional[List[str]] = None,
        **metadata: Any,
    ) -> Callable:
        """Decorator that registers *func* as the handler for *command*.

        Parameters
        ----------
        command:
            The command name to register (case-sensitive).
        required_capabilities:
            Optional list of device capabilities required before this
            handler can be invoked (e.g. ``["screen", "touch"]``).
        **metadata:
            Arbitrary metadata stored alongside the registration.
        """
        def _decorator(func: Callable) -> Callable:
            if command in self._handlers:
                logger.warning(
                    "CommandRegistry[%s]: overwriting existing handler for '%s'",
                    self._name,
                    command,
                )
            self._handlers[command] = func
            self._capabilities[command] = list(required_capabilities or [])
            self._metadata[command] = dict(metadata)
            logger.debug(
                "CommandRegistry[%s]: registered handler for '%s' (caps=%s)",
                self._name,
                command,
                self._capabilities[command],
            )
            return func

        return _decorator

    def register_handler(
        self,
        command: str,
        handler: Callable[..., Any],
        required_capabilities: Optional[List[str]] = None,
        **metadata: Any,
    ) -> None:
        """Programmatic registration (non-decorator form)."""
        self.register(command, required_capabilities, **metadata)(handler)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, command: str) -> Optional[Callable[..., Any]]:
        """Return the handler for *command*, or ``None`` if not found."""
        return self._handlers.get(command)

    def get_required_capabilities(self, command: str) -> List[str]:
        """Return the capability list for *command* (empty list if unregistered)."""
        return list(self._capabilities.get(command, []))

    def get_metadata(self, command: str) -> Dict[str, Any]:
        """Return metadata dict for *command* (empty dict if unregistered)."""
        return dict(self._metadata.get(command, {}))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_commands(self) -> List[str]:
        """Return a sorted list of all registered command names."""
        return sorted(self._handlers.keys())

    def has(self, command: str) -> bool:
        """Return ``True`` if *command* is registered."""
        return command in self._handlers

    def unregister(self, command: str) -> bool:
        """Remove *command* from the registry.  Returns ``True`` if found."""
        if command in self._handlers:
            del self._handlers[command]
            self._capabilities.pop(command, None)
            self._metadata.pop(command, None)
            logger.debug(
                "CommandRegistry[%s]: unregistered handler for '%s'",
                self._name,
                command,
            )
            return True
        return False

    def __len__(self) -> int:
        return len(self._handlers)

    def __repr__(self) -> str:
        return (
            f"CommandRegistry(name={self._name!r}, "
            f"commands={self.list_commands()!r})"
        )


# ── module-level default registry (shared singleton) ─────────────────────
_DEFAULT_REGISTRY: Optional[CommandRegistry] = None


def get_command_registry() -> CommandRegistry:
    """Return the module-level default ``CommandRegistry`` singleton."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = CommandRegistry(name="global")
    return _DEFAULT_REGISTRY


__all__ = [
    "COMMAND_REGISTRY_AUTHORITY",
    "CommandRegistry",
    "get_command_registry",
]
