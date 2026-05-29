"""
nodes/common/node_facade.py
===========================
PR-UNIFIED-NODE-CONTRACT: Facade / adapter layer for 5 key device nodes.

Translates the Unified Node Contract v1 (POST /invoke) to each node's
current dialect endpoints.  No existing node code is modified; this facade
acts as an anti-corruption layer.

Covered nodes:
    Node_33_ADB        → /execute, /devices
    Node_38_BLE        → /connect, /disconnect, /scan, /read, /write
    Node_41_MQTT       → /connect, /disconnect, /publish, /subscribe
    Node_45_DesktopAuto → /click, /type, /hotkey, /move, /scroll
    Node_48_Serial     → /connect, /disconnect, /send, /read

The facade runs as a thin FastAPI service (or can be mounted as a router)
that exposes the unified contract on the northbound and calls the actual
node's localhost endpoints on the southbound.

Usage (standalone service)::

    from nodes.common.node_facade import create_facade_app
    app = create_facade_app()  # mounts all 5 node facades
    uvicorn.run(app, port=8100)

Usage (integrated)::

    from nodes.common.node_facade import ADBFacade, BLEFacade
    router = APIRouter()
    ADBFacade(router, base_url="http://localhost:8033")
    BLEFacade(router, base_url="http://localhost:8038")
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException

from schemas.node_contract import (
    ConnectRequest,
    DisconnectRequest,
    InvokeRequest,
    NodeActionRouter,
    NodeMetadata,
    NodeStatus,
    UnifiedResponse,
)
from schemas.node_errors import NodeErrorCode, NodeErrorResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base facade class
# ---------------------------------------------------------------------------
class NodeFacadeBase:
    """Base class for node facades.  Handles HTTP client lifecycle."""

    def __init__(self, node_name: str, base_url: str, router: APIRouter) -> None:
        self.node_name = node_name
        self.base_url = base_url.rstrip("/")
        self.router = router
        self._client: Optional[httpx.AsyncClient] = None
        self._router = NodeActionRouter(node_name)

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _post(self, path: str, json: Optional[Dict] = None) -> Dict[str, Any]:
        """POST to the underlying node."""
        try:
            resp = await self.client.post(f"{self.base_url}{path}", json=json)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("%s POST %s failed: %s", self.node_name, path, exc)
            raise
        except httpx.RequestError as exc:
            logger.warning("%s POST %s unreachable: %s", self.node_name, path, exc)
            raise

    async def _get(self, path: str) -> Dict[str, Any]:
        """GET from the underlying node."""
        try:
            resp = await self.client.get(f"{self.base_url}{path}")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("%s GET %s failed: %s", self.node_name, path, exc)
            raise
        except httpx.RequestError as exc:
            logger.warning("%s GET %s unreachable: %s", self.node_name, path, exc)
            raise

    def _ok(self, data: Optional[Dict] = None) -> UnifiedResponse:
        return UnifiedResponse(success=True, data=data or {}, node=self.node_name)

    def _err(self, code: NodeErrorCode, detail: str, **kw: Any) -> UnifiedResponse:
        return UnifiedResponse(
            success=False,
            data={
                "error": NodeErrorResponse.from_exception(
                    code, detail, node=self.node_name, **kw
                ).model_dump()
            },
            node=self.node_name,
        )


# ---------------------------------------------------------------------------
# Node_33_ADB Facade
# ---------------------------------------------------------------------------
class ADBFacade(NodeFacadeBase):
    """Facade for Node_33_ADB.

    Dialect mapping:
        /invoke {action:"execute"}  → POST /execute
        /invoke {action:"devices"}  → GET  /devices
        /invoke {action:"shell"}    → POST /execute {command:"shell ..."}
        /invoke {action:"install"}  → POST /execute {command:"install ..."}
    """

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8033") -> None:
        super().__init__("Node_33_ADB", base_url, router)
        self._router.register("execute", self._handle_execute)
        self._router.register("devices", self._handle_devices)
        self._router.register("shell", self._handle_shell)
        self._router.register("install", self._handle_install)
        self._router.register("screenshot", self._handle_screenshot)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name,
                transport="adb",
                capabilities=["GUI_READ", "GUI_WRITE", "INPUT_TOUCH", "GUI_SCREENSHOT"],
                actions=self._router.supported_actions(),
                description="Android Debug Bridge facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            try:
                st = await self._get("/health")
                return self._ok({"health": st})
            except Exception as exc:
                return self._err(NodeErrorCode.NODE_UNAVAILABLE, str(exc))

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            # ADB doesn't have a separate connect; device selection is via params
            return self._ok({"message": "ADB uses device serial in params"})

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            return self._ok({"message": "Disconnect via ADB kill-server if needed"})

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_execute(self, params: Dict, timeout_ms: int) -> Dict:
        command = params.get("command", "")
        result = await self._post("/execute", {"command": command})
        return result

    async def _handle_devices(self, params: Dict, timeout_ms: int) -> Dict:
        result = await self._get("/devices")
        return result

    async def _handle_shell(self, params: Dict, timeout_ms: int) -> Dict:
        cmd = params.get("command", "")
        result = await self._post("/execute", {"command": f"shell {cmd}"})
        return result

    async def _handle_install(self, params: Dict, timeout_ms: int) -> Dict:
        apk_path = params.get("apk_path", "")
        result = await self._post("/execute", {"command": f"install {apk_path}"})
        return result

    async def _handle_screenshot(self, params: Dict, timeout_ms: int) -> Dict:
        result = await self._post("/execute", {"command": "shell screencap -p /sdcard/screen.png"})
        return {"screenshot_path": "/sdcard/screen.png", "raw": result}


# ---------------------------------------------------------------------------
# Node_38_BLE Facade
# ---------------------------------------------------------------------------
class BLEFacade(NodeFacadeBase):
    """Facade for Node_38_BLE.

    Dialect mapping:
        /invoke {action:"connect"}    → POST /connect
        /invoke {action:"disconnect"} → POST /disconnect
        /invoke {action:"scan"}       → POST /scan
        /invoke {action:"read"}       → POST /read
        /invoke {action:"write"}      → POST /write
    """

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8038") -> None:
        super().__init__("Node_38_BLE", base_url, router)
        self._router.register("connect", self._handle_connect)
        self._router.register("disconnect", self._handle_disconnect)
        self._router.register("scan", self._handle_scan)
        self._router.register("read", self._handle_read)
        self._router.register("write", self._handle_write)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name,
                transport="ble",
                capabilities=["COMM_BLUETOOTH", "SENSOR_MOTION"],
                actions=self._router.supported_actions(),
                description="Bluetooth LE facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            try:
                st = await self._get("/status")
                return self._ok(st)
            except Exception as exc:
                return self._err(NodeErrorCode.NODE_UNAVAILABLE, str(exc))

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            try:
                result = await self._post("/connect", {"address": req.target, **req.params})
                return self._ok(result)
            except Exception as exc:
                return self._err(NodeErrorCode.CONNECTION_FAILED, str(exc))

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            try:
                result = await self._post("/disconnect", {})
                return self._ok(result)
            except Exception as exc:
                return self._err(NodeErrorCode.TRANSPORT_ERROR, str(exc))

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_connect(self, params: Dict, timeout_ms: int) -> Dict:
        address = params.get("address", "")
        return await self._post("/connect", {"address": address})

    async def _handle_disconnect(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/disconnect", {})

    async def _handle_scan(self, params: Dict, timeout_ms: int) -> Dict:
        duration = params.get("duration", 10)
        return await self._post("/scan", {"duration": duration})

    async def _handle_read(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/read", params)

    async def _handle_write(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/write", params)


# ---------------------------------------------------------------------------
# Node_41_MQTT Facade
# ---------------------------------------------------------------------------
class MQTTFacade(NodeFacadeBase):
    """Facade for Node_41_MQTT.

    Dialect mapping:
        /invoke {action:"connect"}     → POST /connect
        /invoke {action:"disconnect"}  → POST /disconnect
        /invoke {action:"publish"}     → POST /publish
        /invoke {action:"subscribe"}   → POST /subscribe
    """

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8041") -> None:
        super().__init__("Node_41_MQTT", base_url, router)
        self._router.register("connect", self._handle_connect)
        self._router.register("disconnect", self._handle_disconnect)
        self._router.register("publish", self._handle_publish)
        self._router.register("subscribe", self._handle_subscribe)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name,
                transport="mqtt",
                capabilities=["COMM_MQTT"],
                actions=self._router.supported_actions(),
                description="MQTT broker facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            try:
                st = await self._get("/health")
                return self._ok(st)
            except Exception as exc:
                return self._err(NodeErrorCode.NODE_UNAVAILABLE, str(exc))

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            try:
                result = await self._post("/connect", {"broker": req.target, **req.params})
                return self._ok(result)
            except Exception as exc:
                return self._err(NodeErrorCode.CONNECTION_FAILED, str(exc))

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            try:
                result = await self._post("/disconnect", {})
                return self._ok(result)
            except Exception as exc:
                return self._err(NodeErrorCode.TRANSPORT_ERROR, str(exc))

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_connect(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/connect", params)

    async def _handle_disconnect(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/disconnect", {})

    async def _handle_publish(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/publish", params)

    async def _handle_subscribe(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/subscribe", params)


# ---------------------------------------------------------------------------
# Node_45_DesktopAuto Facade
# ---------------------------------------------------------------------------
class DesktopAutoFacade(NodeFacadeBase):
    """Facade for Node_45_DesktopAuto.

    Dialect mapping:
        /invoke {action:"click"}     → POST /click
        /invoke {action:"type"}      → POST /type
        /invoke {action:"hotkey"}    → POST /hotkey
        /invoke {action:"move"}      → POST /move
        /invoke {action:"scroll"}    → POST /scroll
        /invoke {action:"screenshot"}→ POST /screenshot (via GET /health proxy)
    """

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8045") -> None:
        super().__init__("Node_45_DesktopAuto", base_url, router)
        self._router.register("click", self._handle_click)
        self._router.register("double_click", self._handle_double_click)
        self._router.register("type", self._handle_type)
        self._router.register("hotkey", self._handle_hotkey)
        self._router.register("move", self._handle_move)
        self._router.register("scroll", self._handle_scroll)
        self._router.register("press", self._handle_press)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name,
                transport="uiauto",
                capabilities=["GUI_READ", "GUI_WRITE", "INPUT_KEYBOARD", "INPUT_MOUSE"],
                actions=self._router.supported_actions(),
                description="Desktop UI automation facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            try:
                st = await self._get("/health")
                return self._ok(st)
            except Exception as exc:
                return self._err(NodeErrorCode.NODE_UNAVAILABLE, str(exc))

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            # DesktopAuto doesn't have explicit connect
            return self._ok({"message": "DesktopAuto is always connected to local desktop"})

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            return self._ok({"message": "No-op for DesktopAuto"})

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_click(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/click", params)

    async def _handle_double_click(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/double_click", params)

    async def _handle_type(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/type", params)

    async def _handle_hotkey(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/hotkey", params)

    async def _handle_move(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/move", params)

    async def _handle_scroll(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/scroll", params)

    async def _handle_press(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/press", params)


# ---------------------------------------------------------------------------
# Node_48_Serial Facade
# ---------------------------------------------------------------------------
class SerialFacade(NodeFacadeBase):
    """Facade for Node_48_Serial.

    Dialect mapping:
        /invoke {action:"connect"}    → POST /connect
        /invoke {action:"disconnect"} → POST /disconnect
        /invoke {action:"send"}       → POST /send
        /invoke {action:"read"}       → POST /read
    """

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8049") -> None:
        super().__init__("Node_48_Serial", base_url, router)
        self._router.register("connect", self._handle_connect)
        self._router.register("disconnect", self._handle_disconnect)
        self._router.register("send", self._handle_send)
        self._router.register("read", self._handle_read)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name,
                transport="serial",
                capabilities=["COMM_SERIAL"],
                actions=self._router.supported_actions(),
                description="Serial/UART facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            try:
                st = await self._get("/status")
                return self._ok(st)
            except Exception as exc:
                return self._err(NodeErrorCode.NODE_UNAVAILABLE, str(exc))

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            try:
                result = await self._post("/connect", {"port": req.target, **req.params})
                return self._ok(result)
            except Exception as exc:
                return self._err(NodeErrorCode.CONNECTION_FAILED, str(exc))

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            try:
                result = await self._post("/disconnect", {})
                return self._ok(result)
            except Exception as exc:
                return self._err(NodeErrorCode.TRANSPORT_ERROR, str(exc))

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_connect(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/connect", params)

    async def _handle_disconnect(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/disconnect", {})

    async def _handle_send(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/send", params)

    async def _handle_read(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/read", params)


# ---------------------------------------------------------------------------
# Node_34_Scrcpy Facade
# ---------------------------------------------------------------------------
class ScrcpyFacade(NodeFacadeBase):
    """Facade for Node_34_Scrcpy (Android screen mirroring).

    Dialect mapping:
        /invoke {action:"screenshot"}  → POST /screenshot
        /invoke {action:"tap"}         → POST /tap
        /invoke {action:"swipe"}       → POST /swipe
        /invoke {action:"input_text"}  → POST /input_text
        /invoke {action:"key_event"}   → POST /key_event
    """

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8034") -> None:
        super().__init__("Node_34_Scrcpy", base_url, router)
        self._router.register("screenshot", self._handle_screenshot)
        self._router.register("tap", self._handle_tap)
        self._router.register("swipe", self._handle_swipe)
        self._router.register("input_text", self._handle_input_text)
        self._router.register("key_event", self._handle_key_event)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name, transport="scrcpy",
                capabilities=["GUI_READ", "GUI_STREAM", "INPUT_TOUCH"],
                actions=self._router.supported_actions(),
                description="Scrcpy Android screen mirroring facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            try:
                st = await self._get("/devices")
                return self._ok(st)
            except Exception as exc:
                return self._err(NodeErrorCode.NODE_UNAVAILABLE, str(exc))

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            return self._ok({"message": "Scrcpy auto-connects on first use"})

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            return self._ok({"message": "Scrcpy disconnects on process exit"})

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_screenshot(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/screenshot", params)

    async def _handle_tap(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/tap", params)

    async def _handle_swipe(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/swipe", params)

    async def _handle_input_text(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/input_text", params)

    async def _handle_key_event(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/key_event", params)


# ---------------------------------------------------------------------------
# Node_42_CANbus Facade
# ---------------------------------------------------------------------------
class CANbusFacade(NodeFacadeBase):
    """Facade for Node_42_CANbus (automotive/industrial CAN bus)."""

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8042") -> None:
        super().__init__("Node_42_CANbus", base_url, router)
        self._router.register("connect", self._handle_connect)
        self._router.register("disconnect", self._handle_disconnect)
        self._router.register("send_frame", self._handle_send_frame)
        self._router.register("read_frame", self._handle_read_frame)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name, transport="can",
                capabilities=["COMM_CAN"],
                actions=self._router.supported_actions(),
                description="CAN bus automotive/industrial facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            return self._ok({"status": "CAN skeleton — full implementation pending"})

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            return self._ok({"message": "CAN connect via interface parameter"})

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            return self._ok({})

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_connect(self, params: Dict, timeout_ms: int) -> Dict:
        return {"interface": params.get("interface", "vcan0"), "bitrate": params.get("bitrate", 500000)}

    async def _handle_disconnect(self, params: Dict, timeout_ms: int) -> Dict:
        return {}

    async def _handle_send_frame(self, params: Dict, timeout_ms: int) -> Dict:
        return {"arbitration_id": params.get("arbitration_id"), "data": params.get("data")}

    async def _handle_read_frame(self, params: Dict, timeout_ms: int) -> Dict:
        return {"timeout": params.get("timeout", 1.0)}


# ---------------------------------------------------------------------------
# Node_44_NFC Facade
# ---------------------------------------------------------------------------
class NFCFacade(NodeFacadeBase):
    """Facade for Node_44_NFC (Near Field Communication)."""

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8044") -> None:
        super().__init__("Node_44_NFC", base_url, router)
        self._router.register("read_tag", self._handle_read_tag)
        self._router.register("write_tag", self._handle_write_tag)
        self._router.register("scan", self._handle_scan)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name, transport="nfc",
                capabilities=["COMM_NFC"],
                actions=self._router.supported_actions(),
                description="NFC near-field communication facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            return self._ok({"status": "NFC skeleton — full implementation pending"})

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            return self._ok({"message": "NFC auto-detects on scan"})

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            return self._ok({})

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_read_tag(self, params: Dict, timeout_ms: int) -> Dict:
        return {"uid": params.get("uid"), "data": "placeholder"}

    async def _handle_write_tag(self, params: Dict, timeout_ms: int) -> Dict:
        return {"uid": params.get("uid"), "written": params.get("data")}

    async def _handle_scan(self, params: Dict, timeout_ms: int) -> Dict:
        return {"duration": params.get("duration", 5.0)}


# ---------------------------------------------------------------------------
# Node_46_Camera Facade
# ---------------------------------------------------------------------------
class CameraFacade(NodeFacadeBase):
    """Facade for Node_46_Camera."""

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8046") -> None:
        super().__init__("Node_46_Camera", base_url, router)
        self._router.register("capture", self._handle_capture)
        self._router.register("record_start", self._handle_record_start)
        self._router.register("record_stop", self._handle_record_stop)
        self._router.register("get_frame", self._handle_get_frame)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name, transport="camera",
                capabilities=["SENSOR_CAMERA", "GUI_STREAM"],
                actions=self._router.supported_actions(),
                description="Camera capture and streaming facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            try:
                st = await self._get("/status")
                return self._ok(st)
            except Exception as exc:
                return self._err(NodeErrorCode.NODE_UNAVAILABLE, str(exc))

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            return self._ok({"device_index": req.params.get("device_index", 0)})

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            return self._ok({})

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_capture(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/capture", params)

    async def _handle_record_start(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/record/start", params)

    async def _handle_record_stop(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/record/stop", {})

    async def _handle_get_frame(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._get("/stream/frame")


# ---------------------------------------------------------------------------
# Node_47_Audio Facade
# ---------------------------------------------------------------------------
class AudioFacade(NodeFacadeBase):
    """Facade for Node_47_Audio (microphone + playback)."""

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8047") -> None:
        super().__init__("Node_47_Audio", base_url, router)
        self._router.register("record_start", self._handle_record_start)
        self._router.register("record_stop", self._handle_record_stop)
        self._router.register("play", self._handle_play)
        self._router.register("play_stop", self._handle_play_stop)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name, transport="audio",
                capabilities=["SENSOR_MIC", "INPUT_VOICE"],
                actions=self._router.supported_actions(),
                description="Audio recording and playback facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            try:
                st = await self._get("/status")
                return self._ok(st)
            except Exception as exc:
                return self._err(NodeErrorCode.NODE_UNAVAILABLE, str(exc))

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            return self._ok({"device": req.params.get("device", "default")})

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            return self._ok({})

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_record_start(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/record/start", params)

    async def _handle_record_stop(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/record/stop", {})

    async def _handle_play(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/play", params)

    async def _handle_play_stop(self, params: Dict, timeout_ms: int) -> Dict:
        return await self._post("/play/stop", {})


# ---------------------------------------------------------------------------
# Node_49_OctoPrint Facade
# ---------------------------------------------------------------------------
class OctoPrintFacade(NodeFacadeBase):
    """Facade for Node_49_OctoPrint (3D printer REST API)."""

    def __init__(self, router: APIRouter, base_url: str = "http://localhost:8050") -> None:
        super().__init__("Node_49_OctoPrint", base_url, router)
        self._router.register("get_status", self._handle_get_status)
        self._router.register("start_print", self._handle_start_print)
        self._router.register("cancel_print", self._handle_cancel_print)
        self._router.register("home_axes", self._handle_home_axes)
        self._router.register("jog", self._handle_jog)
        self._mount_routes()

    def _mount_routes(self) -> None:
        @self.router.get("/metadata")
        async def metadata() -> NodeMetadata:
            return NodeMetadata(
                node_name=self.node_name, transport="http",
                capabilities=["GUI_READ", "GUI_WRITE"],
                actions=self._router.supported_actions(),
                description="OctoPrint 3D printer facade",
            )

        @self.router.get("/status")
        async def status() -> UnifiedResponse:
            return self._ok({"status": "OctoPrint skeleton — full implementation pending"})

        @self.router.post("/connect")
        async def connect(req: ConnectRequest) -> UnifiedResponse:
            return self._ok({"octoprint_url": req.target or "http://localhost:5000"})

        @self.router.post("/disconnect")
        async def disconnect(req: DisconnectRequest) -> UnifiedResponse:
            return self._ok({})

        @self.router.post("/invoke")
        async def invoke(req: InvokeRequest) -> UnifiedResponse:
            return await self._router.handle(req)

    async def _handle_get_status(self, params: Dict, timeout_ms: int) -> Dict:
        return {"state": "Operational", "temps": {}}

    async def _handle_start_print(self, params: Dict, timeout_ms: int) -> Dict:
        return {"file": params.get("file"), "started": True}

    async def _handle_cancel_print(self, params: Dict, timeout_ms: int) -> Dict:
        return {"cancelled": True}

    async def _handle_home_axes(self, params: Dict, timeout_ms: int) -> Dict:
        return {"axes": params.get("axes", ["x", "y", "z"])}

    async def _handle_jog(self, params: Dict, timeout_ms: int) -> Dict:
        return {"x": params.get("x", 0), "y": params.get("y", 0), "z": params.get("z", 0)}


# ---------------------------------------------------------------------------
# Factory: mount all facades into a single router
# ---------------------------------------------------------------------------
_FACADE_CLASSES = [
    ("adb", ADBFacade, "http://localhost:8033"),
    ("ble", BLEFacade, "http://localhost:8038"),
    ("mqtt", MQTTFacade, "http://localhost:8041"),
    ("desktop", DesktopAutoFacade, "http://localhost:8045"),
    ("serial", SerialFacade, "http://localhost:8049"),
    ("scrcpy", ScrcpyFacade, "http://localhost:8034"),
    ("canbus", CANbusFacade, "http://localhost:8042"),
    ("nfc", NFCFacade, "http://localhost:8044"),
    ("camera", CameraFacade, "http://localhost:8046"),
    ("audio", AudioFacade, "http://localhost:8047"),
    ("octoprint", OctoPrintFacade, "http://localhost:8050"),
]


def mount_all_facades(prefix: str = "/facade") -> APIRouter:
    """Create a router with all 11 node facades mounted.

    Usage::

        from fastapi import FastAPI
        from nodes.common.node_facade import mount_all_facades

        app = FastAPI()
        app.include_router(mount_all_facades(), prefix="/facade")

    Endpoints:
        /facade/adb/..., /facade/ble/..., /facade/mqtt/...
        /facade/desktop/..., /facade/serial/..., /facade/scrcpy/...
        /facade/canbus/..., /facade/nfc/..., /facade/camera/...
        /facade/audio/..., /facade/octoprint/...
    """
    router = APIRouter()
    for name, cls, base_url in _FACADE_CLASSES:
        sub = APIRouter(prefix=f"{prefix}/{name}")
        cls(sub, base_url)
        router.include_router(sub)

    logger.info("Mounted %d node facades under %s", len(_FACADE_CLASSES), prefix)
    return router


def create_facade_app() -> "FastAPI":
    """Create a standalone FastAPI app with all facades."""
    from fastapi import FastAPI

    app = FastAPI(title="Galaxy Unified Node Facade", version="1.1.0")
    app.include_router(mount_all_facades())

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {
            "status": "ok",
            "facades": [name for name, _, _ in _FACADE_CLASSES],
            "count": len(_FACADE_CLASSES),
        }

    return app
