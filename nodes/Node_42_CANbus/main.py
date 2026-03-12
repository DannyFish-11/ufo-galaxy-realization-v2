"""
Node 42: CANbus - CAN Bus Communication
"""
import os
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_42_CANbus")
except Exception:
    PORT = int(os.getenv("PORT", "8042"))

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    can = None
    CAN_AVAILABLE = False

app = FastAPI(title="Node 42 - CANbus", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# State
bus_instance = None
filters: List[Dict] = []
received_frames: deque = deque(maxlen=500)

class ConnectRequest(BaseModel):
    interface: str = "socketcan"
    channel: str = "can0"
    bitrate: int = 500000

class SendRequest(BaseModel):
    arbitration_id: int
    data: str  # hex string e.g. "DEADBEEF"
    is_extended_id: bool = False
    is_remote_frame: bool = False

class FilterRequest(BaseModel):
    filters: List[Dict[str, Any]]  # [{"can_id": 0x100, "can_mask": 0x7FF, "extended": False}]

@app.get("/health")
async def health():
    return {
        "status": "healthy" if CAN_AVAILABLE else "degraded",
        "node_id": "42",
        "name": "CANbus",
        "can_available": CAN_AVAILABLE,
        "degraded": not CAN_AVAILABLE,
        "degraded_reason": None if CAN_AVAILABLE else "python-can not installed",
        "connected": bus_instance is not None,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "42",
        "name": "CANbus",
        "can_available": CAN_AVAILABLE,
        "connected": bus_instance is not None,
        "pending_frames": len(received_frames),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/connect")
async def connect(request: ConnectRequest):
    global bus_instance
    if not CAN_AVAILABLE:
        return {"success": False, "error": "python-can not installed. Run: pip install python-can"}
    try:
        if bus_instance is not None:
            bus_instance.shutdown()
        bus_instance = can.interface.Bus(
            channel=request.channel,
            interface=request.interface,
            bitrate=request.bitrate
        )
        return {"success": True, "interface": request.interface, "channel": request.channel, "bitrate": request.bitrate}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/disconnect")
async def disconnect():
    global bus_instance
    if bus_instance is None:
        return {"success": False, "error": "Not connected"}
    try:
        bus_instance.shutdown()
        bus_instance = None
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/send")
async def send_frame(request: SendRequest):
    if not CAN_AVAILABLE:
        return {"success": False, "error": "python-can not installed. Run: pip install python-can"}
    if bus_instance is None:
        return {"success": False, "error": "Not connected. Call /connect first."}
    try:
        data = bytes.fromhex(request.data)
        msg = can.Message(
            arbitration_id=request.arbitration_id,
            data=data,
            is_extended_id=request.is_extended_id,
            is_remote_frame=request.is_remote_frame
        )
        bus_instance.send(msg)
        return {"success": True, "arbitration_id": request.arbitration_id, "data": request.data}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/receive")
async def receive_frames(limit: int = 10):
    if not CAN_AVAILABLE:
        return {"success": False, "error": "python-can not installed. Run: pip install python-can"}
    if bus_instance is None:
        return {"success": False, "error": "Not connected. Call /connect first."}
    try:
        frames = []
        for _ in range(min(limit, 50)):
            msg = bus_instance.recv(timeout=0.1)
            if msg is None:
                break
            frames.append({
                "arbitration_id": msg.arbitration_id,
                "data": msg.data.hex(),
                "is_extended_id": msg.is_extended_id,
                "is_remote_frame": msg.is_remote_frame,
                "timestamp": msg.timestamp
            })
        return {"success": True, "frames": frames, "count": len(frames)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/filters")
async def get_filters():
    return {"success": True, "filters": filters}

@app.post("/filters")
async def set_filters(request: FilterRequest):
    global filters
    if not CAN_AVAILABLE:
        return {"success": False, "error": "python-can not installed. Run: pip install python-can"}
    if bus_instance is None:
        return {"success": False, "error": "Not connected. Call /connect first."}
    try:
        filters = request.filters
        bus_instance.set_filters(filters)
        return {"success": True, "filters": filters}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
