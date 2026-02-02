"""
Node 38: BLE - 蓝牙低功耗通信
"""
import os, asyncio
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 38 - BLE", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

bleak = None
try:
    from bleak import BleakScanner, BleakClient
    bleak = True
except ImportError:
    pass

devices = {}

class ConnectRequest(BaseModel):
    address: str
    timeout: float = 10.0

class ReadWriteRequest(BaseModel):
    address: str
    characteristic: str
    value: Optional[str] = None

@app.get("/health")
async def health():
    return {"status": "healthy" if bleak else "degraded", "node_id": "38", "name": "BLE", "bleak_available": bleak is not None, "timestamp": datetime.now().isoformat()}

@app.get("/scan")
async def scan_devices(timeout: float = 5.0):
    if not bleak:
        return {"success": False, "error": "bleak not installed. Run: pip install bleak"}
    
    try:
        from bleak import BleakScanner
        discovered = await BleakScanner.discover(timeout=timeout)
        results = [{"name": d.name or "Unknown", "address": d.address, "rssi": d.rssi} for d in discovered]
        return {"success": True, "devices": results, "count": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/connect")
async def connect_device(request: ConnectRequest):
    if not bleak:
        return {"success": False, "error": "bleak not installed"}
    
    try:
        from bleak import BleakClient
        client = BleakClient(request.address)
        await asyncio.wait_for(client.connect(), timeout=request.timeout)
        
        if client.is_connected:
            devices[request.address] = client
            services = []
            for service in client.services:
                chars = [{"uuid": c.uuid, "properties": c.properties} for c in service.characteristics]
                services.append({"uuid": service.uuid, "characteristics": chars})
            return {"success": True, "address": request.address, "services": services}
        return {"success": False, "error": "Failed to connect"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/disconnect")
async def disconnect_device(address: str):
    if address in devices:
        try:
            await devices[address].disconnect()
            del devices[address]
            return {"success": True, "address": address}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "Device not connected"}

@app.post("/read")
async def read_characteristic(request: ReadWriteRequest):
    if not bleak:
        return {"success": False, "error": "bleak not installed"}
    
    if request.address not in devices:
        return {"success": False, "error": "Device not connected"}
    
    try:
        client = devices[request.address]
        value = await client.read_gatt_char(request.characteristic)
        return {"success": True, "value": value.hex(), "raw": list(value)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/write")
async def write_characteristic(request: ReadWriteRequest):
    if not bleak:
        return {"success": False, "error": "bleak not installed"}
    
    if request.address not in devices:
        return {"success": False, "error": "Device not connected"}
    
    if not request.value:
        return {"success": False, "error": "No value provided"}
    
    try:
        client = devices[request.address]
        data = bytes.fromhex(request.value)
        await client.write_gatt_char(request.characteristic, data)
        return {"success": True, "written": request.value}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "scan": return await scan_devices(params.get("timeout", 5.0))
    elif tool == "connect": return await connect_device(ConnectRequest(**params))
    elif tool == "disconnect": return await disconnect_device(params.get("address", ""))
    elif tool == "read": return await read_characteristic(ReadWriteRequest(**params))
    elif tool == "write": return await write_characteristic(ReadWriteRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8038)
