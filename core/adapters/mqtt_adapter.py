"""
core/adapters/mqtt_adapter.py — MQTT 传输适配器

Migrated from nodes/Node_41_MQTT/main.py
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.MQTT")

# 尝试导入 paho-mqtt
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    logger.warning("paho-mqtt not installed, MQTT adapter disabled")


class MQTTAdapter(TransportAdapter):
    """MQTT 传输适配器。

    Migrated from Node_41_MQTT. Provides MQTT pub/sub transport.
    """

    @property
    def transport_type(self) -> str:
        return "mqtt"

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._connected = False
        self._subscriptions: Dict[str, int] = {}
        self._broker = os.getenv("MQTT_BROKER", "localhost")
        self._port = int(os.getenv("MQTT_PORT", "1883"))
        self._username = os.getenv("MQTT_USERNAME", "")
        self._password = os.getenv("MQTT_PASSWORD", "")

        if MQTT_AVAILABLE:
            self._setup_client()

    def _setup_client(self) -> None:
        """Setup MQTT client"""
        self._client = mqtt.Client()
        if self._username:
            self._client.username_pw_set(self._username, self._password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc):
        self._connected = rc == 0
        for topic, qos in self._subscriptions.items():
            self._client.subscribe(topic, qos)

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """Publish message to MQTT topic"""
        if not MQTT_AVAILABLE or not self._connected:
            return {"success": False, "error": "MQTT not connected"}

        try:
            payload = json.dumps(message) if isinstance(message, dict) else str(message)
            result = self._client.publish(target, payload)
            return {"success": result.rc == 0, "via": "mqtt"}
        except Exception as e:
            logger.warning("MQTT publish failed: %s", e)
            return {"success": False, "error": str(e)}

    async def is_available(self, target: str) -> bool:
        return self._connected

    async def close(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
