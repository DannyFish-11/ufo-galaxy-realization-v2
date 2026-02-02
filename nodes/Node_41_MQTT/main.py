"""
Node 41: MQTT - 物联网消息队列
"""
import os, json
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 41 - MQTT", version="3.0.0", description="MQTT IoT Message Broker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

class MQTTPublishRequest(BaseModel):
    broker: str
    port: int = 1883
    topic: str
    payload: str
    qos: int = 0
    retain: bool = False
    username: Optional[str] = None
    password: Optional[str] = None

@app.get("/health")
async def health():
    return {
        "status": "healthy" if MQTT_AVAILABLE else "degraded",
        "node_id": "41",
        "name": "MQTT",
        "paho_mqtt_available": MQTT_AVAILABLE
    }

@app.post("/publish")
async def publish_message(request: MQTTPublishRequest):
    """发布 MQTT 消息"""
    if not MQTT_AVAILABLE:
        raise HTTPException(status_code=503, detail="paho-mqtt not installed. Run: pip install paho-mqtt")
    
    try:
        client = mqtt.Client()
        if request.username and request.password:
            client.username_pw_set(request.username, request.password)
        
        client.connect(request.broker, request.port, 60)
        result = client.publish(request.topic, request.payload, qos=request.qos, retain=request.retain)
        client.disconnect()
        
        return {
            "success": result.rc == 0,
            "message_id": result.mid,
            "topic": request.topic
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "publish": return await publish_message(MQTTPublishRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8041)
