"""
Node 48: Serial - 串口通信
"""
import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 48 - Serial", version="3.0.0", description="Serial Port Communication")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

class SerialSendRequest(BaseModel):
    port: str
    baudrate: int = 9600
    data: str
    timeout: int = 1

class SerialReadRequest(BaseModel):
    port: str
    baudrate: int = 9600
    size: int = 1024
    timeout: int = 1

@app.get("/health")
async def health():
    return {
        "status": "healthy" if SERIAL_AVAILABLE else "degraded",
        "node_id": "48",
        "name": "Serial",
        "pyserial_available": SERIAL_AVAILABLE
    }

@app.post("/send")
async def send_data(request: SerialSendRequest):
    """发送串口数据"""
    if not SERIAL_AVAILABLE:
        raise HTTPException(status_code=503, detail="pyserial not installed. Run: pip install pyserial")
    
    try:
        ser = serial.Serial(request.port, request.baudrate, timeout=request.timeout)
        bytes_written = ser.write(request.data.encode())
        ser.close()
        return {"success": True, "bytes_written": bytes_written}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/read")
async def read_data(request: SerialReadRequest):
    """读取串口数据"""
    if not SERIAL_AVAILABLE:
        raise HTTPException(status_code=503, detail="pyserial not installed")
    
    try:
        ser = serial.Serial(request.port, request.baudrate, timeout=request.timeout)
        data = ser.read(request.size)
        ser.close()
        return {"success": True, "data": data.decode(errors='ignore')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ports")
async def list_ports():
    """列出可用串口"""
    if not SERIAL_AVAILABLE:
        raise HTTPException(status_code=503, detail="pyserial not installed")
    
    try:
        ports = serial.tools.list_ports.comports()
        return {
            "success": True,
            "ports": [{"device": p.device, "description": p.description} for p in ports]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "send": return await send_data(SerialSendRequest(**params))
    elif tool == "read": return await read_data(SerialReadRequest(**params))
    elif tool == "ports": return await list_ports()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8048)
