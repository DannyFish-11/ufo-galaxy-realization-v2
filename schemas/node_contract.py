"""
schemas/node_contract.py
========================
PR-UNIFIED-NODE-CONTRACT: Unified Node Contract v1

Defines the standard north-bound interface that all device nodes expose.
The central intelligence and launcher_adapter.py only speak this contract;
per-node dialects are translated by the facade layer.

Standard endpoints:
    GET  /health     — liveness probe
    GET  /metadata   — node identity, capabilities, version
    GET  /status     — connection state, active devices, stats
    POST /connect    — connect to a device
    POST /disconnect — disconnect from a device
    POST /invoke     — unified action invocation

All responses use the UnifiedResponse envelope so callers can rely on
a consistent shape regardless of the underlying node.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from schemas.node_errors import NodeErrorCode, NodeErrorResponse


# ---------------------------------------------------------------------------
# Request / response envelopes
# ---------------------------------------------------------------------------
class UnifiedResponse(BaseModel):
    """Every successful node response is wrapped in this envelope."""

    success: bool = True
    data: Optional[Dict[str, Any]] = None
    node: Optional[str] = None
    duration_ms: Optional[float] = None


class InvokeRequest(BaseModel):
    """POST /invoke — unified action invocation.

    All node-specific operations (click, publish, write, execute, scan, …)
    are normalized through this single endpoint.
    """

    action: str = Field(..., description="Action name, e.g. 'click', 'publish', 'write'")
    params: Dict[str, Any] = Field(default_factory=dict, description="Action-specific parameters")
    timeout_ms: int = Field(default=10_000, ge=100, le=300_000, description="Timeout in milliseconds")
    correlation_id: Optional[str] = Field(default=None, description="End-to-end correlation ID")


class ConnectRequest(BaseModel):
    """POST /connect — connect to a target device."""

    target: str = Field(..., description="Device identifier (IP, MAC, serial port, etc.)")
    params: Dict[str, Any] = Field(default_factory=dict, description="Transport-specific parameters")
    timeout_ms: int = Field(default=10_000, ge=100, le=60_000)


class DisconnectRequest(BaseModel):
    """POST /disconnect — disconnect from a device."""

    target: Optional[str] = Field(default=None, description="Specific device to disconnect; None = all")
    force: bool = Field(default=False, description="Force disconnect even if operations are pending")


# ---------------------------------------------------------------------------
# Metadata / status models
# ---------------------------------------------------------------------------
class NodeMetadata(BaseModel):
    """GET /metadata — node identity and capability declaration."""

    node_name: str
    version: str = "1.0.0"
    transport: str = Field(..., description="Primary transport: adb, ble, mqtt, serial, uiauto, ...")
    capabilities: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list, description="Actions supported by /invoke")
    description: str = ""
    uptime_seconds: float = 0.0


class ConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class DeviceStatus(BaseModel):
    """Status of a single connected device."""

    device_id: str
    connection_status: ConnectionStatus
    device_type: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NodeStatus(BaseModel):
    """GET /status — full node state."""

    node_name: str
    process_running: bool = True
    connections: List[DeviceStatus] = Field(default_factory=list)
    active_device_count: int = 0
    stats: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Facade router (used by node_facade.py)
# ---------------------------------------------------------------------------
class NodeActionRouter:
    """Routes unified ``/invoke`` actions to node-specific handlers.

    Each node facade creates an instance and registers its actions::

        router = NodeActionRouter("Node_38_BLE")
        router.register("connect", _handle_connect)
        router.register("disconnect", _handle_disconnect)
        router.register("scan", _handle_scan)
        router.register("read", _handle_read)
        router.register("write", _handle_write)

    Then in the facade's ``/invoke`` handler::

        @app.post("/invoke")
        async def invoke(req: InvokeRequest):
            return await router.handle(req)
    """

    def __init__(self, node_name: str) -> None:
        self.node_name = node_name
        self._handlers: Dict[str, Any] = {}

    def register(self, action: str, handler: Any) -> None:
        """Register a handler for an action name."""
        self._handlers[action] = handler

    def supported_actions(self) -> List[str]:
        """Return the list of registered actions."""
        return sorted(self._handlers.keys())

    async def handle(self, request: InvokeRequest) -> UnifiedResponse:
        """Route an InvokeRequest to the registered handler."""
        import time
        t0 = time.perf_counter()

        handler = self._handlers.get(request.action)
        if handler is None:
            from schemas.node_errors import NodeErrorResponse
            err = NodeErrorResponse.unsupported_action(
                action=request.action,
                node=self.node_name,
                supported=self.supported_actions(),
            )
            # Return as a "successful" response containing an error
            # so the envelope shape is always consistent
            return UnifiedResponse(
                success=False,
                data={"error": err.model_dump()},
                node=self.node_name,
            )

        try:
            result = await handler(request.params, timeout_ms=request.timeout_ms)
            return UnifiedResponse(
                success=True,
                data=result if isinstance(result, dict) else {"result": result},
                node=self.node_name,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except TimeoutError:
            from schemas.node_errors import NodeErrorResponse
            err = NodeErrorResponse.timeout(
                action=request.action, timeout_ms=request.timeout_ms, node=self.node_name
            )
            return UnifiedResponse(
                success=False,
                data={"error": err.model_dump()},
                node=self.node_name,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            from schemas.node_errors import NodeErrorResponse, NodeErrorCode
            err = NodeErrorResponse.from_exception(
                NodeErrorCode.INTERNAL_NODE_ERROR,
                str(exc),
                node=self.node_name,
                action=request.action,
            )
            return UnifiedResponse(
                success=False,
                data={"error": err.model_dump()},
                node=self.node_name,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
