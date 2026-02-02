"""
Node 37: LinuxDBus - Linux D-Bus 系统总线通信
"""
import os, subprocess
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 37 - LinuxDBus", version="3.0.0", description="Linux D-Bus System Bus Communication")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import dbus
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False

class DBusCallRequest(BaseModel):
    bus_name: str
    object_path: str
    interface: str
    method: str
    args: Optional[list] = []

@app.get("/health")
async def health():
    return {
        "status": "healthy" if DBUS_AVAILABLE else "degraded",
        "node_id": "37",
        "name": "LinuxDBus",
        "dbus_available": DBUS_AVAILABLE
    }

@app.post("/call")
async def call_method(request: DBusCallRequest):
    """调用 D-Bus 方法"""
    if not DBUS_AVAILABLE:
        raise HTTPException(status_code=503, detail="dbus-python not installed. Run: pip install dbus-python")
    
    try:
        bus = dbus.SystemBus()
        obj = bus.get_object(request.bus_name, request.object_path)
        interface = dbus.Interface(obj, request.interface)
        method = getattr(interface, request.method)
        result = method(*request.args)
        return {"success": True, "result": str(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/list_services")
async def list_services():
    """列出所有 D-Bus 服务"""
    if not DBUS_AVAILABLE:
        raise HTTPException(status_code=503, detail="dbus-python not installed")
    
    try:
        bus = dbus.SystemBus()
        services = bus.list_names()
        return {"success": True, "services": list(services)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "call": return await call_method(DBusCallRequest(**params))
    elif tool == "list_services": return await list_services()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8037)
