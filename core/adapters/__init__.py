"""
core/adapters/ — AIP v3 传输适配器集合（物理传输层）

注意: NATS 不在这里，NATS 是任务分发层，和 AIP Transport 并列。

Migrated from nodes/:
- Node_41_MQTT → MQTTAdapter
- Node_38_BLE → BLEAdapter
- Node_48_Serial → SerialAdapter
- Node_37_LinuxDBus → DBusAdapter
- Node_42_CANbus → CANBusAdapter
"""

from core.adapters.websocket_adapter import WebSocketAdapter
from core.adapters.mqtt_adapter import MQTTAdapter
from core.adapters.ble_adapter import BLEAdapter
from core.adapters.serial_adapter import SerialAdapter
from core.adapters.dbus_adapter import DBusAdapter
from core.adapters.canbus_adapter import CANBusAdapter

__all__ = [
    "WebSocketAdapter",
    "MQTTAdapter",
    "BLEAdapter",
    "SerialAdapter",
    "DBusAdapter",
    "CANBusAdapter",
]
