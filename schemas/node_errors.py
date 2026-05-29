"""
schemas/node_errors.py
======================
PR-UNIFIED-NODE-CONTRACT: Unified error codes for all device nodes.

All 130 nodes should use these error codes so that the central intelligence
can handle errors uniformly without knowing each node's dialect.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------
class NodeErrorCode(str, Enum):
    """Canonical error codes for node operations."""

    # Node lifecycle
    NODE_UNAVAILABLE = "NODE_UNAVAILABLE"
    """Node process is not running or not reachable."""

    NODE_STARTUP_FAILED = "NODE_STARTUP_FAILED"
    """Node failed to start (main.py crashed, port conflict, etc.)."""

    # Connection
    DEVICE_NOT_CONNECTED = "DEVICE_NOT_CONNECTED"
    """No device is currently connected through this node."""

    CONNECTION_FAILED = "CONNECTION_FAILED"
    """Connect attempt failed (device refused, timeout, auth error)."""

    CONNECTION_LOST = "CONNECTION_LOST"
    """Established connection dropped unexpectedly."""

    ALREADY_CONNECTED = "ALREADY_CONNECTED"
    """Connect called but a connection already exists."""

    # Action / invoke
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    """The requested action is not supported by this node."""

    INVALID_PARAMS = "INVALID_PARAMS"
    """Action parameters are missing, malformed, or out of range."""

    TIMEOUT = "TIMEOUT"
    """Operation exceeded the requested timeout_ms."""

    # Transport
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    """Underlying transport error (BLE disconnect, serial framing, etc.)."""

    PERMISSION_DENIED = "PERMISSION_DENIED"
    """Operation requires elevated privileges (root, ADB auth, etc.)."""

    # Internal
    INTERNAL_NODE_ERROR = "INTERNAL_NODE_ERROR"
    """Unclassified error inside the node process."""

    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    """Required system dependency is not installed (adb, bleak, etc.)."""

    # Health
    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"
    """Node /health endpoint returned non-200 or unhealthy body."""


# ---------------------------------------------------------------------------
# Error response model
# ---------------------------------------------------------------------------
class NodeErrorResponse(BaseModel):
    """Standard error response from any node operation.

    All nodes should return this structure when an operation fails.
    The ``detail`` field is human-readable; ``code`` is machine-readable.
    """

    success: bool = False
    code: NodeErrorCode
    detail: str
    node: Optional[str] = None
    action: Optional[str] = None
    retryable: bool = False
    retry_after_ms: Optional[int] = None
    metadata: Dict[str, Any] = {}

    @classmethod
    def from_exception(
        cls,
        code: NodeErrorCode,
        detail: str,
        *,
        node: Optional[str] = None,
        action: Optional[str] = None,
        retryable: bool = False,
        **metadata: Any,
    ) -> "NodeErrorResponse":
        """Convenience factory."""
        return cls(
            code=code,
            detail=detail,
            node=node,
            action=action,
            retryable=retryable,
            metadata=metadata,
        )

    @classmethod
    def node_unavailable(
        cls, node: str, detail: str = "Node process is not running"
    ) -> "NodeErrorResponse":
        return cls.from_exception(NodeErrorCode.NODE_UNAVAILABLE, detail, node=node)

    @classmethod
    def timeout(
        cls, action: str, timeout_ms: int, node: Optional[str] = None
    ) -> "NodeErrorResponse":
        return cls.from_exception(
            NodeErrorCode.TIMEOUT,
            f"Action '{action}' timed out after {timeout_ms}ms",
            node=node,
            action=action,
            retryable=True,
            timeout_ms=timeout_ms,
        )

    @classmethod
    def unsupported_action(
        cls, action: str, node: Optional[str] = None, supported: Optional[list] = None
    ) -> "NodeErrorResponse":
        return cls.from_exception(
            NodeErrorCode.UNSUPPORTED_ACTION,
            f"Action '{action}' is not supported by this node",
            node=node,
            action=action,
            supported_actions=supported or [],
        )
