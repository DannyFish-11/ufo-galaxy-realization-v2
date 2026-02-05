"""
Node 41: MQTT - MQTT消息队列节点
==================================
提供MQTT连接、发布订阅、消息管理功能
"""
import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 尝试导入paho-mqtt
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

app = FastAPI(title="Node 41 - MQTT", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# MQTT配置
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

class MQTTMessage(BaseModel):
    topic: str
    payload: Any
    qos: int = 0
    retain: bool = False

class MQTTSubscribeRequest(BaseModel):
    topic: str
    qos: int = 0

class MQTTManager:
    def __init__(self):
        self.client = None
        self.connected = False
        self.subscriptions: Dict[str, int] = {}
        self.messages: List[Dict] = []
        self.message_handlers: Dict[str, List[Callable]] = {}
        self._setup_client()

    def _setup_client(self):
        """设置MQTT客户端"""
        if not MQTT_AVAILABLE:
            return

        self.client = mqtt.Client()
        if MQTT_USERNAME:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc):
        """连接回调"""
        self.connected = rc == 0
        # 重新订阅
        for topic, qos in self.subscriptions.items():
            self.client.subscribe(topic, qos)

    def _on_message(self, client, userdata, msg):
        """消息回调"""
        message = {
            "topic": msg.topic,
            "payload": msg.payload.decode(),
            "qos": msg.qos,
            "retain": msg.retain,
            "timestamp": datetime.now().isoformat()
        }
        self.messages.append(message)

        # 限制消息数量
        if len(self.messages) > 1000:
            self.messages = self.messages[-1000:]

        # 调用处理器
        for topic, handlers in self.message_handlers.items():
            if mqtt.topic_matches_sub(topic, msg.topic):
                for handler in handlers:
                    handler(message)

    def _on_disconnect(self, client, userdata, rc):
        """断开回调"""
        self.connected = False

    def connect(self, broker: str = None, port: int = None) -> bool:
        """连接MQTT代理"""
        if not MQTT_AVAILABLE:
            raise RuntimeError("paho-mqtt not installed")

        broker = broker or MQTT_BROKER
        port = port or MQTT_PORT

        try:
            self.client.connect(broker, port)
            self.client.loop_start()
            return True
        except Exception as e:
            raise RuntimeError(f"MQTT connection failed: {e}")

    def disconnect(self):
        """断开连接"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False

    def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False):
        """发布消息"""
        if not self.connected:
            raise RuntimeError("MQTT not connected")

        if isinstance(payload, dict):
            payload = json.dumps(payload)

        result = self.client.publish(topic, payload, qos, retain)
        return {"success": result.rc == 0, "mid": result.mid}

    def subscribe(self, topic: str, qos: int = 0):
        """订阅主题"""
        if not self.connected:
            raise RuntimeError("MQTT not connected")

        result = self.client.subscribe(topic, qos)
        self.subscriptions[topic] = qos
        return {"success": result[0] == 0}

    def unsubscribe(self, topic: str):
        """取消订阅"""
        if not self.connected:
            raise RuntimeError("MQTT not connected")

        result = self.client.unsubscribe(topic)
        if topic in self.subscriptions:
            del self.subscriptions[topic]
        return {"success": result[0] == 0}

    def get_messages(self, topic: str = None, limit: int = 100) -> List[Dict]:
        """获取消息"""
        messages = self.messages
        if topic:
            messages = [m for m in messages if mqtt.topic_matches_sub(topic, m["topic"])]
        return messages[-limit:]

# 全局MQTT管理器
mqtt_manager = MQTTManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "41",
        "name": "MQTT",
        "mqtt_available": MQTT_AVAILABLE,
        "connected": mqtt_manager.connected,
        "broker": MQTT_BROKER,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/connect")
async def connect_mqtt(broker: str = None, port: int = None):
    """连接MQTT代理"""
    if not MQTT_AVAILABLE:
        raise HTTPException(status_code=503, detail="paho-mqtt not installed")

    try:
        success = mqtt_manager.connect(broker, port)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/disconnect")
async def disconnect_mqtt():
    """断开连接"""
    try:
        mqtt_manager.disconnect()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/publish")
async def publish_message(request: MQTTMessage):
    """发布消息"""
    try:
        result = mqtt_manager.publish(
            topic=request.topic,
            payload=request.payload,
            qos=request.qos,
            retain=request.retain
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/subscribe")
async def subscribe_topic(request: MQTTSubscribeRequest):
    """订阅主题"""
    try:
        result = mqtt_manager.subscribe(request.topic, request.qos)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/unsubscribe")
async def unsubscribe_topic(topic: str):
    """取消订阅"""
    try:
        result = mqtt_manager.unsubscribe(topic)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/messages")
async def get_messages(topic: str = None, limit: int = 100):
    """获取消息"""
    try:
        messages = mqtt_manager.get_messages(topic, limit)
        return {"messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8041)
