"""
core/adapters — AIP v3 传输适配器集合

适配器列表:
- websocket_adapter: WebSocket 点对点
- mqtt_adapter:      MQTT 发布/订阅
- tcp_adapter:       TCP P2P 直连
- udp_adapter:       UDP 报文/广播
- ble_adapter:       Bluetooth LE GATT
- serial_adapter:    串口通信
- dbus_adapter:      Linux D-Bus
- canbus_adapter:    CAN Bus

注册 (lifecycle.py):
    transport = get_aip_transport()
    transport.register_adapter(WebSocketAdapter(...))
    transport.register_adapter(MQTTAdapter(...))
    ...
"""

from core.adapters.websocket_adapter import WebSocketAdapter
from core.adapters.mqtt_adapter import MQTTAdapter
from core.adapters.tcp_adapter import TCPAdapter
from core.adapters.udp_adapter import UDPAdapter
from core.adapters.ble_adapter import BLEAdapter
from core.adapters.serial_adapter import SerialAdapter
from core.adapters.dbus_adapter import DBusAdapter
from core.adapters.canbus_adapter import CANBusAdapter

__all__ = [
    "WebSocketAdapter",
    "MQTTAdapter",
    "TCPAdapter",
    "UDPAdapter",
    "BLEAdapter",
    "SerialAdapter",
    "DBusAdapter",
    "CANBusAdapter",
]
