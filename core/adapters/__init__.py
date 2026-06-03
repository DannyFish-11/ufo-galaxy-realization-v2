"""
core/adapters/ — AIP v3 传输适配器集合

Migrated from nodes/:
- Node_41_MQTT → MQTTAdapter
- Node_38_BLE → BLEAdapter
- Node_48_Serial → SerialAdapter
"""

from core.adapters.websocket_adapter import WebSocketAdapter
from core.adapters.nats_adapter import NATSAdapter
from core.adapters.mqtt_adapter import MQTTAdapter
from core.adapters.ble_adapter import BLEAdapter
from core.adapters.serial_adapter import SerialAdapter

__all__ = [
    "WebSocketAdapter",
    "NATSAdapter",
    "MQTTAdapter",
    "BLEAdapter",
    "SerialAdapter",
]
