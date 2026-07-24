"""
Node 43: MAVLink - 无人机通信协议
"""

import logging  # auto: ensure module logger is defined
logger = logging.getLogger(__name__)

import os, time
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

app = FastAPI(title="Node 43 - MAVLink", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

pymavlink = None
try:
    from pymavlink import mavutil
    pymavlink = mavutil
except ImportError:
    pass

connections = {}

class ConnectRequest(BaseModel):
    connection_string: str
    baud: int = 57600

class CommandRequest(BaseModel):
    connection_id: str
    command: str
    params: Optional[dict] = None

@app.get("/health")
async def health():
    return {"status": "healthy" if pymavlink else "degraded", "node_id": "43", "name": "MAVLink", "pymavlink_available": pymavlink is not None, "active_connections": len(connections), "timestamp": datetime.now().isoformat()}

@app.post("/connect")
async def connect(request: ConnectRequest):
    if not pymavlink:
        return {"success": False, "error": "pymavlink not installed. Run: pip install pymavlink"}
    
    try:
        def _open_connection():
            c = pymavlink.mavlink_connection(request.connection_string, baud=request.baud)
            c.wait_heartbeat(timeout=10)  # blocks up to 10s
            return c

        conn = await asyncio.to_thread(_open_connection)

        conn_id = f"mav_{len(connections)}"
        connections[conn_id] = conn
        
        return {"success": True, "connection_id": conn_id, "system_id": conn.target_system, "component_id": conn.target_component}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/disconnect")
async def disconnect(connection_id: str):
    if connection_id in connections:
        try:
            connections[connection_id].close()
            del connections[connection_id]
            return {"success": True}
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
    return {"success": False, "error": "Connection not found"}

@app.post("/arm")
async def arm(connection_id: str):
    if connection_id not in connections:
        return {"success": False, "error": "Connection not found"}
    
    try:
        conn = connections[connection_id]
        conn.arducopter_arm()
        return {"success": True, "message": "Arm command sent"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/disarm")
async def disarm(connection_id: str):
    if connection_id not in connections:
        return {"success": False, "error": "Connection not found"}
    
    try:
        conn = connections[connection_id]
        conn.arducopter_disarm()
        return {"success": True, "message": "Disarm command sent"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/takeoff")
async def takeoff(connection_id: str, altitude: float = 10.0):
    if connection_id not in connections:
        return {"success": False, "error": "Connection not found"}
    
    try:
        conn = connections[connection_id]
        conn.mav.command_long_send(conn.target_system, conn.target_component, pymavlink.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, altitude)
        return {"success": True, "message": f"Takeoff to {altitude}m commanded"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/telemetry/{connection_id}")
async def get_telemetry(connection_id: str):
    if connection_id not in connections:
        return {"success": False, "error": "Connection not found"}
    
    try:
        conn = connections[connection_id]

        def _read_telemetry():
            # Three blocking recv_match calls (up to 5s each) — run off the loop.
            position = attitude = battery = None
            m = conn.recv_match(type='GLOBAL_POSITION_INT', blocking=True, timeout=5)
            if m:
                position = {"lat": m.lat / 1e7, "lon": m.lon / 1e7, "alt": m.alt / 1000, "relative_alt": m.relative_alt / 1000}
            m = conn.recv_match(type='ATTITUDE', blocking=True, timeout=5)
            if m:
                attitude = {"roll": m.roll, "pitch": m.pitch, "yaw": m.yaw}
            m = conn.recv_match(type='SYS_STATUS', blocking=True, timeout=5)
            if m:
                battery = {"voltage": m.voltage_battery / 1000, "current": m.current_battery / 100, "remaining": m.battery_remaining}
            return position, attitude, battery

        position, attitude, battery = await asyncio.to_thread(_read_telemetry)
        return {"success": True, "position": position, "attitude": attitude, "battery": battery}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "connect": return await connect(ConnectRequest(**params))
    elif tool == "disconnect": return await disconnect(params.get("connection_id", ""))
    elif tool == "arm": return await arm(params.get("connection_id", ""))
    elif tool == "disarm": return await disarm(params.get("connection_id", ""))
    elif tool == "takeoff": return await takeoff(params.get("connection_id", ""), params.get("altitude", 10.0))
    elif tool == "telemetry": return await get_telemetry(params.get("connection_id", ""))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8043)
