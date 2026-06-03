"""
core/adapters/canbus_adapter.py — CAN Bus 传输适配器

Migrated from nodes/Node_42_CANbus/
Controller Area Network transport for vehicle/industrial devices.
"""

import logging
import os
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.CANBus")

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    can = None
    CAN_AVAILABLE = False
    logger.warning("python-can not installed, CAN bus adapter disabled")


class CANBusAdapter(TransportAdapter):
    """CAN Bus 传输适配器。

    Migrated from Node_42_CANbus. Provides CAN bus frame transmission.
    """

    @property
    def transport_type(self) -> str:
        return "canbus"

    def __init__(self) -> None:
        self._buses: Dict[str, Any] = {}
        self._interface = os.getenv("CAN_INTERFACE", "socketcan")
        self._channel = os.getenv("CAN_CHANNEL", "can0")
        self._bitrate = int(os.getenv("CAN_BITRATE", "500000"))

    def _get_bus(self, channel: str) -> Any:
        if channel not in self._buses:
            if not CAN_AVAILABLE:
                return None
            try:
                self._buses[channel] = can.Bus(
                    interface=self._interface,
                    channel=channel,
                    bitrate=self._bitrate,
                )
            except Exception as e:
                logger.warning("CAN bus init failed for %s: %s", channel, e)
                return None
        return self._buses.get(channel)

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """Send CAN frame.

        target: channel name, e.g., "can0"
        message: {"arbitration_id": int, "data": str(hex), ...}
        """
        if not CAN_AVAILABLE:
            return {"success": False, "error": "python-can not installed"}

        try:
            bus = self._get_bus(target)
            if bus is None:
                return {"success": False, "error": f"CAN bus {target} not available"}

            arb_id = message.get("arbitration_id", 0)
            data_hex = message.get("data", "")
            data = bytes.fromhex(data_hex) if data_hex else b""
            is_extended = message.get("is_extended_id", False)

            frame = can.Message(
                arbitration_id=arb_id,
                data=data,
                is_extended_id=is_extended,
            )
            bus.send(frame)
            return {"success": True, "via": "canbus"}
        except Exception as e:
            logger.warning("CAN send failed: %s", e)
            return {"success": False, "error": str(e)}

    async def is_available(self, target: str) -> bool:
        return self._get_bus(target) is not None

    async def close(self) -> None:
        for bus in self._buses.values():
            try:
                bus.shutdown()
            except Exception:
                pass
        self._buses.clear()
