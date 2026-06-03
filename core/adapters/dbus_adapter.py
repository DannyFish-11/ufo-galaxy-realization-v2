"""
core/adapters/dbus_adapter.py — D-Bus 传输适配器

Migrated from nodes/Node_37_LinuxDBus/
Linux D-Bus IPC (Inter-Process Communication) transport.
"""

import logging
import os
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.DBus")

try:
    import dbus
    DBUS_AVAILABLE = True
except ImportError:
    dbus = None
    DBUS_AVAILABLE = False
    logger.warning("dbus-python not installed, D-Bus adapter disabled")


class DBusAdapter(TransportAdapter):
    """D-Bus 传输适配器。

    Migrated from Node_37_LinuxDBus. Provides Linux D-Bus IPC transport.
    """

    @property
    def transport_type(self) -> str:
        return "dbus"

    def __init__(self) -> None:
        self._session_bus = None
        self._system_bus = None
        if DBUS_AVAILABLE:
            try:
                self._session_bus = dbus.SessionBus()
                self._system_bus = dbus.SystemBus()
            except Exception as e:
                logger.warning("D-Bus bus init failed: %s", e)

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """Call D-Bus method on target service.

        target format: "bus_type:service:object_path:interface:method"
        e.g., "session:org.freedesktop.Notifications:/org/freedesktop/Notifications:org.freedesktop.Notifications:Notify"
        """
        if not DBUS_AVAILABLE:
            return {"success": False, "error": "dbus-python not installed"}

        try:
            parts = target.split(":")
            if len(parts) != 5:
                return {"success": False, "error": f"Invalid D-Bus target format: {target}"}

            bus_type, service, obj_path, interface, method = parts
            bus = self._system_bus if bus_type == "system" else self._session_bus
            if bus is None:
                return {"success": False, "error": f"{bus_type} bus not available"}

            proxy = bus.get_object(service, obj_path)
            iface = dbus.Interface(proxy, interface)
            args = message.get("args", [])
            result = getattr(iface, method)(*args)

            return {"success": True, "via": "dbus", "result": str(result)}
        except Exception as e:
            logger.warning("D-Bus call failed: %s", e)
            return {"success": False, "error": str(e)}

    async def is_available(self, target: str) -> bool:
        if not DBUS_AVAILABLE:
            return False
        try:
            parts = target.split(":")
            if len(parts) < 2:
                return False
            bus_type = parts[0]
            bus = self._system_bus if bus_type == "system" else self._session_bus
            return bus is not None
        except Exception:
            return False

    async def close(self) -> None:
        pass
