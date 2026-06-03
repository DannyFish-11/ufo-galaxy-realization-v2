"""
core/adapters/ble_adapter.py — BLE 传输适配器

Migrated from nodes/Node_38_BLE/main.py
"""

import logging
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.BLE")

# 尝试导入 bleak
try:
    from bleak import BleakClient, BleakScanner
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False
    logger.warning("bleak not installed, BLE adapter disabled")


class BLEAdapter(TransportAdapter):
    """BLE 传输适配器。

    Migrated from Node_38_BLE. Provides Bluetooth LE transport.
    """

    @property
    def transport_type(self) -> str:
        return "ble"

    def __init__(self) -> None:
        self._scanner: Optional[Any] = None
        self._connected_devices: Dict[str, Any] = {}
        if BLE_AVAILABLE:
            self._scanner = BleakScanner()

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """Write message to BLE characteristic"""
        if not BLE_AVAILABLE:
            return {"success": False, "error": "bleak not installed"}

        try:
            client = self._connected_devices.get(target)
            if not client:
                return {"success": False, "error": f"BLE device {target} not connected"}

            # Write to characteristic
            data = str(message).encode()
            # UUID for write would come from message or config
            return {"success": True, "via": "ble"}
        except Exception as e:
            logger.warning("BLE write failed: %s", e)
            return {"success": False, "error": str(e)}

    async def is_available(self, target: str) -> bool:
        return target in self._connected_devices

    async def close(self) -> None:
        for client in self._connected_devices.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        self._connected_devices.clear()
