"""
Node 38: BLE - Bluetooth Low Energy
"""
import os
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_38_BLE")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8038"))

try:
    from bleak import BleakScanner, BleakClient
    BLEAK_AVAILABLE = True
except ImportError:
    BleakScanner = None
    BleakClient = None
    BLEAK_AVAILABLE = False

app = FastAPI(title="Node 38 - BLE", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Active connections
connections: Dict[str, Any] = {}
notification_callbacks: Dict[str, Dict[str, List[Any]]] = {}

class ScanRequest(BaseModel):
    timeout: float = 5.0

class ConnectRequest(BaseModel):
    address: str
    timeout: float = 10.0

class DisconnectRequest(BaseModel):
    address: str

class ReadRequest(BaseModel):
    address: str
    characteristic_uuid: str

class WriteRequest(BaseModel):
    address: str
    characteristic_uuid: str
    data: str  # hex string
    response: bool = True

class NotifyRequest(BaseModel):
    address: str
    characteristic_uuid: str

@app.get("/health")
async def health():
    return {
        "status": "healthy" if BLEAK_AVAILABLE else "degraded",
        "node_id": "38",
        "name": "BLE",
        "bleak_available": BLEAK_AVAILABLE,
        "degraded": not BLEAK_AVAILABLE,
        "degraded_reason": None if BLEAK_AVAILABLE else "bleak not installed",
        "active_connections": len(connections),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "38",
        "name": "BLE",
        "bleak_available": BLEAK_AVAILABLE,
        "connected_devices": list(connections.keys()),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/scan")
async def scan(request: ScanRequest):
    if not BLEAK_AVAILABLE:
        return {"success": False, "error": "bleak not installed. Run: pip install bleak"}
    try:
        devices = await BleakScanner.discover(timeout=request.timeout)
        return {
            "success": True,
            "devices": [
                {"address": d.address, "name": d.name or "Unknown", "rssi": d.rssi}
                for d in devices
            ],
            "count": len(devices)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/connect")
async def connect(request: ConnectRequest):
    if not BLEAK_AVAILABLE:
        return {"success": False, "error": "bleak not installed. Run: pip install bleak"}
    try:
        if request.address in connections:
            return {"success": True, "address": request.address, "message": "Already connected"}
        client = BleakClient(request.address, timeout=request.timeout)
        await client.connect()
        connections[request.address] = client
        return {"success": True, "address": request.address, "connected": client.is_connected}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/disconnect")
async def disconnect(request: DisconnectRequest):
    if not BLEAK_AVAILABLE:
        return {"success": False, "error": "bleak not installed. Run: pip install bleak"}
    if request.address not in connections:
        return {"success": False, "error": f"Not connected to {request.address}"}
    try:
        await connections[request.address].disconnect()
        del connections[request.address]
        return {"success": True, "address": request.address}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/services/{address}")
async def list_services(address: str):
    if not BLEAK_AVAILABLE:
        return {"success": False, "error": "bleak not installed. Run: pip install bleak"}
    if address not in connections:
        return {"success": False, "error": f"Not connected to {address}"}
    try:
        client = connections[address]
        services = []
        for service in client.services:
            chars = []
            for char in service.characteristics:
                chars.append({
                    "uuid": str(char.uuid),
                    "properties": list(char.properties),
                    "descriptors": [str(d.uuid) for d in char.descriptors]
                })
            services.append({"uuid": str(service.uuid), "description": service.description, "characteristics": chars})
        return {"success": True, "address": address, "services": services}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/read")
async def read_characteristic(request: ReadRequest):
    if not BLEAK_AVAILABLE:
        return {"success": False, "error": "bleak not installed. Run: pip install bleak"}
    if request.address not in connections:
        return {"success": False, "error": f"Not connected to {request.address}"}
    try:
        client = connections[request.address]
        data = await client.read_gatt_char(request.characteristic_uuid)
        return {"success": True, "address": request.address, "uuid": request.characteristic_uuid, "data": data.hex(), "bytes": list(data)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/write")
async def write_characteristic(request: WriteRequest):
    if not BLEAK_AVAILABLE:
        return {"success": False, "error": "bleak not installed. Run: pip install bleak"}
    if request.address not in connections:
        return {"success": False, "error": f"Not connected to {request.address}"}
    try:
        client = connections[request.address]
        data = bytes.fromhex(request.data)
        await client.write_gatt_char(request.characteristic_uuid, data, response=request.response)
        return {"success": True, "address": request.address, "uuid": request.characteristic_uuid}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/notify/subscribe")
async def subscribe_notifications(request: NotifyRequest):
    if not BLEAK_AVAILABLE:
        return {"success": False, "error": "bleak not installed. Run: pip install bleak"}
    if request.address not in connections:
        return {"success": False, "error": f"Not connected to {request.address}"}
    try:
        client = connections[request.address]
        received = []
        if request.address not in notification_callbacks:
            notification_callbacks[request.address] = {}

        def handler(sender, data):
            received.append({"sender": str(sender), "data": data.hex(), "timestamp": datetime.now().isoformat()})

        notification_callbacks[request.address][request.characteristic_uuid] = received
        await client.start_notify(request.characteristic_uuid, handler)
        return {"success": True, "address": request.address, "uuid": request.characteristic_uuid, "message": "Notification subscription started"}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
