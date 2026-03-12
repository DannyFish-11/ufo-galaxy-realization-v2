"""
Node 37: LinuxDBus - D-Bus IPC Service
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_37_LinuxDBus")
except Exception:
    PORT = int(os.getenv("PORT", "8037"))

try:
    import dbus
    DBUS_AVAILABLE = True
except ImportError:
    dbus = None
    DBUS_AVAILABLE = False

app = FastAPI(title="Node 37 - LinuxDBus", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class DBusCallRequest(BaseModel):
    bus_type: str = "session"  # "session" or "system"
    service: str
    object_path: str
    interface: str
    method: str
    args: Optional[List[Any]] = None

class DBusIntrospectRequest(BaseModel):
    bus_type: str = "session"
    service: str
    object_path: str

class DBusSignalRequest(BaseModel):
    bus_type: str = "session"
    object_path: str
    interface: str
    signal_name: str
    args: Optional[List[Any]] = None

def get_bus(bus_type: str):
    if not DBUS_AVAILABLE:
        raise RuntimeError("dbus-python not installed. Run: pip install dbus-python")
    if bus_type == "system":
        return dbus.SystemBus()
    return dbus.SessionBus()

@app.get("/health")
async def health():
    return {
        "status": "healthy" if DBUS_AVAILABLE else "degraded",
        "node_id": "37",
        "name": "LinuxDBus",
        "dbus_available": DBUS_AVAILABLE,
        "degraded": not DBUS_AVAILABLE,
        "degraded_reason": None if DBUS_AVAILABLE else "dbus-python not installed",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "37",
        "name": "LinuxDBus",
        "dbus_available": DBUS_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/call")
async def call_method(request: DBusCallRequest):
    if not DBUS_AVAILABLE:
        return {"success": False, "error": "dbus-python not installed. Run: pip install dbus-python"}
    try:
        bus = get_bus(request.bus_type)
        obj = bus.get_object(request.service, request.object_path)
        iface = dbus.Interface(obj, request.interface)
        method = getattr(iface, request.method)
        args = request.args or []
        result = method(*args)
        return {"success": True, "result": str(result)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/introspect")
async def introspect(service: str, object_path: str, bus_type: str = "session"):
    if not DBUS_AVAILABLE:
        return {"success": False, "error": "dbus-python not installed. Run: pip install dbus-python"}
    try:
        bus = get_bus(bus_type)
        obj = bus.get_object(service, object_path)
        iface = dbus.Interface(obj, "org.freedesktop.DBus.Introspectable")
        xml = iface.Introspect()
        return {"success": True, "xml": str(xml)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/signal")
async def emit_signal(request: DBusSignalRequest):
    if not DBUS_AVAILABLE:
        return {"success": False, "error": "dbus-python not installed. Run: pip install dbus-python"}
    try:
        # Signals require a running main loop and registered service with a service name
        # Return guidance instead of attempting a partial implementation
        return {
            "success": False,
            "error": "Signal emission requires a registered D-Bus service with a running main loop. Use /call for method invocation."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/list_names")
async def list_names(bus_type: str = "session"):
    if not DBUS_AVAILABLE:
        return {"success": False, "error": "dbus-python not installed. Run: pip install dbus-python"}
    try:
        bus = get_bus(bus_type)
        obj = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
        iface = dbus.Interface(obj, "org.freedesktop.DBus")
        names = list(iface.ListNames())
        return {"success": True, "names": names, "count": len(names)}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
