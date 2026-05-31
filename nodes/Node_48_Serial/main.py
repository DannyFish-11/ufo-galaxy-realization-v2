"""
Node 48: Serial - Serial Port Communication
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
    PORT = get_node_port("Node_48_Serial")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8048"))

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    serial = None
    SERIAL_AVAILABLE = False

try:
    import serial_asyncio
    ASYNCIO_AVAILABLE = True
except ImportError:
    serial_asyncio = None
    ASYNCIO_AVAILABLE = False

app = FastAPI(title="Node 48 - Serial", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Active connections: conn_id -> serial.Serial
connections: Dict[str, Any] = {}

class ConnectRequest(BaseModel):
    port: str
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    timeout: float = 1.0
    conn_id: Optional[str] = None

class DisconnectRequest(BaseModel):
    conn_id: str

class SendRequest(BaseModel):
    conn_id: str
    data: str
    encoding: str = "utf-8"  # "utf-8" or "hex"

class ReadRequest(BaseModel):
    conn_id: str
    max_bytes: int = 256
    timeout: float = 1.0
    encoding: str = "utf-8"

@app.get("/health")
async def health():
    return {
        "status": "healthy" if SERIAL_AVAILABLE else "degraded",
        "node_id": "48",
        "name": "Serial",
        "pyserial_available": SERIAL_AVAILABLE,
        "degraded": not SERIAL_AVAILABLE,
        "degraded_reason": None if SERIAL_AVAILABLE else "pyserial not installed",
        "active_connections": len(connections),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "48",
        "name": "Serial",
        "pyserial_available": SERIAL_AVAILABLE,
        "active_connections": list(connections.keys()),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/ports")
async def list_ports():
    if not SERIAL_AVAILABLE:
        return {"success": False, "error": "pyserial not installed. Run: pip install pyserial"}
    try:
        ports = []
        for p in serial.tools.list_ports.comports():
            ports.append({
                "device": p.device,
                "name": p.name,
                "description": p.description,
                "hwid": p.hwid,
                "manufacturer": p.manufacturer,
                "product": p.product,
                "vid": p.vid,
                "pid": p.pid
            })
        return {"success": True, "ports": ports, "count": len(ports)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/connect")
async def connect(request: ConnectRequest):
    if not SERIAL_AVAILABLE:
        return {"success": False, "error": "pyserial not installed. Run: pip install pyserial"}
    try:
        conn_id = request.conn_id or request.port
        if conn_id in connections:
            return {"success": True, "conn_id": conn_id, "message": "Already connected"}
        ser = serial.Serial(
            port=request.port,
            baudrate=request.baudrate,
            bytesize=request.bytesize,
            parity=request.parity,
            stopbits=request.stopbits,
            timeout=request.timeout
        )
        connections[conn_id] = ser
        return {"success": True, "conn_id": conn_id, "port": request.port, "baudrate": request.baudrate}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/disconnect")
async def disconnect(request: DisconnectRequest):
    if request.conn_id not in connections:
        return {"success": False, "error": f"Connection '{request.conn_id}' not found"}
    try:
        connections[request.conn_id].close()
        del connections[request.conn_id]
        return {"success": True, "conn_id": request.conn_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/send")
async def send_data(request: SendRequest):
    if not SERIAL_AVAILABLE:
        return {"success": False, "error": "pyserial not installed. Run: pip install pyserial"}
    if request.conn_id not in connections:
        return {"success": False, "error": f"Connection '{request.conn_id}' not found"}
    try:
        ser = connections[request.conn_id]
        if request.encoding == "hex":
            data = bytes.fromhex(request.data)
        else:
            data = request.data.encode(request.encoding)
        bytes_written = ser.write(data)
        return {"success": True, "bytes_written": bytes_written}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/read")
async def read_data(request: ReadRequest):
    if not SERIAL_AVAILABLE:
        return {"success": False, "error": "pyserial not installed. Run: pip install pyserial"}
    if request.conn_id not in connections:
        return {"success": False, "error": f"Connection '{request.conn_id}' not found"}
    try:
        ser = connections[request.conn_id]
        old_timeout = ser.timeout
        ser.timeout = request.timeout
        data = ser.read(request.max_bytes)
        ser.timeout = old_timeout
        if request.encoding == "hex":
            return {"success": True, "data": data.hex(), "bytes_read": len(data)}
        else:
            return {"success": True, "data": data.decode(request.encoding, errors="replace"), "bytes_read": len(data)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/connections")
async def list_connections():
    result = []
    for conn_id, ser in connections.items():
        result.append({
            "conn_id": conn_id,
            "port": ser.port if SERIAL_AVAILABLE else "N/A",
            "baudrate": ser.baudrate if SERIAL_AVAILABLE else 0,
            "is_open": ser.is_open if SERIAL_AVAILABLE else False
        })
    return {"success": True, "connections": result, "count": len(result)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
