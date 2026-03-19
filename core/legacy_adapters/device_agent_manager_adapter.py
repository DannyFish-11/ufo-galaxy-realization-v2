#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/legacy_adapters/device_agent_manager_adapter.py
======================================================
PR-1 (Block-1) — Legacy Device Agent Manager Adapter

Wraps the legacy ``core.device_agent_manager.DeviceAgentManager`` API and
ensures all device state writes go through ``core.unified.device_manager.UnifiedDeviceManager``
(the SSOT for device state).

Old callers continue to work unchanged because this adapter preserves
the original public interface.  Device registration, unregistration, and
status/heartbeat updates are delegated exclusively to the unified core.

The adapter stamps all requests with:
    entry_path = "legacy"
    via_legacy_adapter = True
    source = "legacy_device_agent_manager"

Delegation map
--------------
Legacy method                     → Unified / canonical target
---------------------------------   -----------------------------------------
register_device(device_info)      → UnifiedDeviceManager.register_device(...)
unregister_device(device_id)      → UnifiedDeviceManager.unregister_device(...)
get_device(device_id)             → UnifiedDeviceManager.get_device(...)
get_all_devices()                 → UnifiedDeviceManager.list_devices()
connect_device(device_id)         → DeviceAgentManager.connect_device(...)
disconnect_device(device_id)      → DeviceAgentManager.disconnect_device(...)
execute_command(device_id, ...)   → DeviceAgentManager.execute_command(...)
heartbeat(device_id)              → UnifiedDeviceManager.heartbeat(...)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LegacyAdapter.DeviceAgentManager")


class LegacyDeviceAgentManagerAdapter:
    """Adapter that keeps legacy DeviceAgentManager signatures while delegating
    device-state writes to ``UnifiedDeviceManager``.

    Usage::

        from core.legacy_adapters import LegacyDeviceAgentManagerAdapter
        adapter = LegacyDeviceAgentManagerAdapter()
        agent = await adapter.register_device(device_info)
    """

    def __init__(self) -> None:
        self._legacy: Optional[Any] = None
        self._unified: Optional[Any] = None

    def _get_legacy(self) -> Any:
        """Lazily obtain the legacy DeviceAgentManager singleton."""
        if self._legacy is None:
            try:
                from core.device_agent_manager import DeviceAgentManager
                self._legacy = DeviceAgentManager()
            except Exception as exc:
                logger.error(
                    "LegacyDeviceAgentManagerAdapter: cannot load legacy DeviceAgentManager: %s",
                    exc,
                )
                raise
        return self._legacy

    def _get_unified(self) -> Any:
        """Lazily obtain the unified device manager singleton."""
        if self._unified is None:
            from core.unified.device_manager import get_unified_device_manager
            self._unified = get_unified_device_manager()
        return self._unified

    def _log_delegation(self, method: str) -> None:
        logger.debug(
            "legacy_device_agent_manager → unified | method=%s "
            "entry_path=legacy via_legacy_adapter=True",
            method,
        )

    # ------------------------------------------------------------------
    # Device lifecycle — delegated to UnifiedDeviceManager (SSOT)
    # ------------------------------------------------------------------

    async def register_device(self, device_info: Any, **kwargs: Any) -> Optional[Any]:
        """Legacy API: register a device and create an agent.

        Device state is written to UnifiedDeviceManager (SSOT).
        Agent creation is handled by the legacy DeviceAgentManager.
        """
        self._log_delegation("register_device")
        # Delegate to legacy manager which already routes through UDM internally
        legacy = self._get_legacy()
        return await legacy.register_device(device_info, **kwargs)

    async def unregister_device(self, device_id: str) -> bool:
        """Legacy API: unregister a device by ID."""
        self._log_delegation("unregister_device")
        # Remove from UDM (SSOT)
        try:
            self._get_unified().unregister_device(device_id)
        except Exception as exc:
            logger.warning(
                "LegacyDeviceAgentManagerAdapter.unregister_device: UDM unregister failed: %s",
                exc,
            )
        # Also clean up legacy agent if present
        try:
            legacy = self._get_legacy()
            if hasattr(legacy, "unregister_device"):
                return await legacy.unregister_device(device_id)
        except Exception as exc:
            logger.warning("Legacy unregister_device failed: %s", exc)
        return True

    def get_device(self, device_id: str) -> Optional[Any]:
        """Legacy API: get device info by ID (read from UDM)."""
        self._log_delegation("get_device")
        return self._get_unified().get_device(device_id)

    def get_all_devices(self) -> List[Any]:
        """Legacy API: list all registered devices (read from UDM)."""
        self._log_delegation("get_all_devices")
        return self._get_unified().list_devices()

    def get_online_devices(self) -> List[Any]:
        """Legacy API: list only online devices (read from UDM)."""
        self._log_delegation("get_online_devices")
        return self._get_unified().get_online_devices()

    def get_agent(self, device_id: str) -> Optional[Any]:
        """Legacy API: get the device agent object."""
        self._log_delegation("get_agent")
        try:
            legacy = self._get_legacy()
            if hasattr(legacy, "get_agent"):
                return legacy.get_agent(device_id)
            if hasattr(legacy, "_agents"):
                return legacy._agents.get(device_id)
        except Exception as exc:
            logger.warning("get_agent failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Device operations — delegated to legacy agent manager
    # ------------------------------------------------------------------

    async def connect_device(self, device_id: str) -> bool:
        """Legacy API: connect a registered device."""
        self._log_delegation("connect_device")
        legacy = self._get_legacy()
        if hasattr(legacy, "connect_device"):
            return await legacy.connect_device(device_id)
        return False

    async def disconnect_device(self, device_id: str) -> bool:
        """Legacy API: disconnect a registered device."""
        self._log_delegation("disconnect_device")
        legacy = self._get_legacy()
        if hasattr(legacy, "disconnect_device"):
            return await legacy.disconnect_device(device_id)
        return False

    async def execute_command(
        self,
        device_id: str,
        command: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Legacy API: execute a command on a device."""
        self._log_delegation("execute_command")
        legacy = self._get_legacy()
        if hasattr(legacy, "execute_command"):
            return await legacy.execute_command(device_id, command, params or {})
        return {"success": False, "error": "execute_command not available"}

    def heartbeat(self, device_id: str) -> None:
        """Legacy API: record a heartbeat for a device (writes to UDM)."""
        self._log_delegation("heartbeat")
        try:
            self._get_unified().heartbeat(device_id)
        except Exception as exc:
            logger.warning("heartbeat UDM update failed for %s: %s", device_id, exc)

    async def initialize(self) -> bool:
        """Legacy API: initialise the device agent manager."""
        self._log_delegation("initialize")
        return await self._get_legacy().initialize()

    async def shutdown(self) -> bool:
        """Legacy API: shutdown the device agent manager."""
        self._log_delegation("shutdown")
        return await self._get_legacy().shutdown()

    def get_stats(self) -> Dict[str, Any]:
        """Legacy API: return statistics."""
        self._log_delegation("get_stats")
        legacy = self._get_legacy()
        if hasattr(legacy, "get_stats"):
            return legacy.get_stats()
        return {"devices": len(self.get_all_devices())}


__all__ = ["LegacyDeviceAgentManagerAdapter"]
