"""
Node 70: BambuLab - 拓竹 3D 打印机控制
"""
import os, json
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 70 - BambuLab", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

paho = None
try:
    import paho.mqtt.client as mqtt
    paho = mqtt
except ImportError:
    pass

PRINTER_IP = os.getenv("BAMBU_PRINTER_IP", "")
ACCESS_CODE = os.getenv("BAMBU_ACCESS_CODE", "")
SERIAL_NUMBER = os.getenv("BAMBU_SERIAL_NUMBER", "")

printer_status = {"connected": False, "state": "unknown"}

class PrintRequest(BaseModel):
    gcode_file: str
    plate_number: int = 1

class ControlRequest(BaseModel):
    command: str  # pause, resume, stop, home

@app.get("/health")
async def health():
    return {"status": "healthy" if paho else "degraded", "node_id": "70", "name": "BambuLab", "mqtt_available": paho is not None, "printer_configured": bool(PRINTER_IP and ACCESS_CODE), "timestamp": datetime.now().isoformat()}

def get_mqtt_client():
    if not paho:
        raise HTTPException(status_code=503, detail="paho-mqtt not installed")
    if not PRINTER_IP or not ACCESS_CODE:
        raise HTTPException(status_code=503, detail="Printer not configured. Set BAMBU_PRINTER_IP and BAMBU_ACCESS_CODE")
    
    client = paho.Client()
    client.username_pw_set("bblp", ACCESS_CODE)
    client.tls_set()
    client.tls_insecure_set(True)
    return client

@app.get("/status")
async def get_status():
    """获取打印机状态"""
    if not PRINTER_IP:
        return {"success": False, "error": "Printer not configured"}
    
    try:
        client = get_mqtt_client()
        status = {"connected": False}
        
        def on_connect(c, userdata, flags, rc):
            if rc == 0:
                status["connected"] = True
                c.subscribe(f"device/{SERIAL_NUMBER}/report")
        
        def on_message(c, userdata, msg):
            try:
                data = json.loads(msg.payload.decode())
                status.update(data)
            except (json.JSONDecodeError, ValueError):
                pass
            c.disconnect()
        
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(PRINTER_IP, 8883, 60)
        client.loop_start()
        
        import time
        time.sleep(3)
        client.loop_stop()
        
        return {"success": True, "status": status}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/print")
async def start_print(request: PrintRequest):
    """开始打印"""
    if not PRINTER_IP:
        return {"success": False, "error": "Printer not configured"}
    
    try:
        client = get_mqtt_client()
        
        command = {
            "print": {
                "command": "project_file",
                "param": f"Metadata/plate_{request.plate_number}.gcode",
                "subtask_name": request.gcode_file,
                "url": f"file:///sdcard/{request.gcode_file}",
                "timelapse": False,
                "bed_leveling": True,
                "flow_cali": True,
                "vibration_cali": True,
                "layer_inspect": False,
                "use_ams": True
            }
        }
        
        client.connect(PRINTER_IP, 8883, 60)
        client.publish(f"device/{SERIAL_NUMBER}/request", json.dumps(command))
        client.disconnect()
        
        return {"success": True, "message": f"Print job started: {request.gcode_file}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/control")
async def control_printer(request: ControlRequest):
    """控制打印机"""
    if not PRINTER_IP:
        return {"success": False, "error": "Printer not configured"}
    
    commands = {
        "pause": {"print": {"command": "pause"}},
        "resume": {"print": {"command": "resume"}},
        "stop": {"print": {"command": "stop"}},
        "home": {"print": {"command": "gcode_line", "param": "G28"}}
    }
    
    if request.command not in commands:
        raise HTTPException(status_code=400, detail=f"Unknown command: {request.command}")
    
    try:
        client = get_mqtt_client()
        client.connect(PRINTER_IP, 8883, 60)
        client.publish(f"device/{SERIAL_NUMBER}/request", json.dumps(commands[request.command]))
        client.disconnect()
        return {"success": True, "command": request.command}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/gcode")
async def send_gcode(gcode: str):
    """发送 G-code 命令"""
    if not PRINTER_IP:
        return {"success": False, "error": "Printer not configured"}
    
    try:
        client = get_mqtt_client()
        command = {"print": {"command": "gcode_line", "param": gcode}}
        client.connect(PRINTER_IP, 8883, 60)
        client.publish(f"device/{SERIAL_NUMBER}/request", json.dumps(command))
        client.disconnect()
        return {"success": True, "gcode": gcode}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "status": return await get_status()
    elif tool == "print": return await start_print(PrintRequest(**params))
    elif tool == "control": return await control_printer(ControlRequest(**params))
    elif tool == "gcode": return await send_gcode(params.get("gcode", ""))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8070)
