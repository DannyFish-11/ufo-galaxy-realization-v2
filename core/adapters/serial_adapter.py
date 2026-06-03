"""
core/adapters/serial_adapter.py — Serial 传输适配器

Migrated from nodes/Node_48_Serial/main.py
"""

import logging
import os
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.Serial")

# 尝试导入 pyserial
try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    logger.warning("pyserial not installed, Serial adapter disabled")


class SerialAdapter(TransportAdapter):
    """Serial 传输适配器。

    Migrated from Node_48_Serial. Provides serial port transport.
    """

    @property
    def transport_type(self) -> str:
        return "serial"

    def __init__(self) -> None:
        self._ports: Dict[str, Any] = {}
        self._default_baudrate = int(os.getenv("SERIAL_BAUDRATE", "9600"))

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """Write message to serial port"""
        if not SERIAL_AVAILABLE:
            return {"success": False, "error": "pyserial not installed"}

        try:
            port = self._ports.get(target)
            if not port:
                port = serial.Serial(target, self._default_baudrate, timeout=1)
                self._ports[target] = port

            data = str(message).encode()
            port.write(data)
            return {"success": True, "via": "serial"}
        except Exception as e:
            logger.warning("Serial write to %s failed: %s", target, e)
            return {"success": False, "error": str(e)}

    async def is_available(self, target: str) -> bool:
        return target in self._ports

    async def close(self) -> None:
        for port in self._ports.values():
            try:
                port.close()
            except Exception:
                pass
        self._ports.clear()
