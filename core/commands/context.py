"""
core/commands/context.py — Command Execution Context
=====================================================

**Batch PR-5: Command routing decomposition**

This module defines ``CommandContext``, a per-request value object that
carries cross-cutting concerns through the command execution lifecycle:
trace identity, source information, and request-scoped metadata.

Authority sentinel
------------------
``COMMAND_CONTEXT_AUTHORITY = "core.commands.context"``

Design
------
``CommandContext`` is immutable once created.  It is passed through the
middleware chain and into handlers.  Handlers must not mutate it; instead
they should derive a new context with ``context.with_metadata(**extra)``
if they need to propagate additional state.

The context deliberately does NOT hold a reference to the router or
dispatcher — those are injection concerns handled at the call site.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# ── module authority sentinel ─────────────────────────────────────────────
COMMAND_CONTEXT_AUTHORITY: str = "core.commands.context"
"""Sentinel: core.commands.context is the canonical command context module.

Import this symbol to assert that a call site is using the decomposed
context module rather than ad-hoc dict-based context passing.
"""


@dataclass(frozen=True)
class CommandContext:
    """Immutable per-request execution context.

    Parameters
    ----------
    trace_id:
        Globally unique trace identifier for end-to-end observability.
        Auto-generated if not provided.
    request_id:
        Identifier of the ``CommandRequest`` this context belongs to.
    source:
        String identifying the caller (e.g. ``"api"``, ``"scheduler"``,
        ``"ai"``).
    user_id:
        Authenticated user identifier, if applicable.
    device_id:
        Primary target device identifier, if the context is scoped to a
        single device dispatch.
    command:
        The command name being executed.
    created_at:
        Unix timestamp at context creation time.
    metadata:
        Arbitrary immutable metadata dict for cross-cutting annotations.
    """

    trace_id: str = field(default_factory=lambda: f"trc_{uuid.uuid4().hex[:16]}")
    request_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    source: str = ""
    user_id: Optional[str] = None
    device_id: Optional[str] = None
    command: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def with_metadata(self, **extra: Any) -> "CommandContext":
        """Return a new ``CommandContext`` with *extra* merged into metadata."""
        import dataclasses
        merged = {**self.metadata, **extra}
        return dataclasses.replace(self, metadata=merged)

    def with_device(self, device_id: str) -> "CommandContext":
        """Return a new ``CommandContext`` scoped to *device_id*."""
        import dataclasses
        return dataclasses.replace(self, device_id=device_id)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize context to a JSON-serializable dict."""
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "source": self.source,
            "user_id": self.user_id,
            "device_id": self.device_id,
            "command": self.command,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_request(cls, request: Any) -> "CommandContext":
        """Build a ``CommandContext`` from a ``CommandRequest``-like object."""
        metadata = dict(getattr(request, "metadata", None) or {})
        trace_id = metadata.pop("trace_id", None) or f"trc_{uuid.uuid4().hex[:16]}"
        return cls(
            trace_id=trace_id,
            request_id=getattr(request, "request_id", f"req_{uuid.uuid4().hex[:12]}"),
            source=getattr(request, "source", ""),
            user_id=metadata.pop("user_id", None),
            device_id=None,
            command=getattr(request, "command", ""),
            created_at=getattr(request, "created_at", time.time()),
            metadata=metadata,
        )


__all__ = [
    "COMMAND_CONTEXT_AUTHORITY",
    "CommandContext",
]
