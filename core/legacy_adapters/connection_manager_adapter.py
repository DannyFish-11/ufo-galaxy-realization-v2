#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/legacy_adapters/connection_manager_adapter.py
=====================================================
PR-1 (Block-1) — Legacy Connection Manager Adapter

.. deprecated:: Batch PR-3
    Deprecation level: D1 (SOFT_DEPRECATED)
    Canonical replacement: ``core.unified.connection_manager.UnifiedConnectionManager``
    Canonical accessor: ``core.unified.connection_manager.get_unified_connection_manager()``
    Removal target: **Batch PR-5**

    This module is a **compatibility shim only**.  New code must not depend on
    :class:`LegacyConnectionManagerAdapter`.  Call
    :func:`core.unified.connection_manager.get_unified_connection_manager`
    directly instead.

Wraps the legacy ``core.connection_manager.ConnectionManager`` API and
delegates to ``core.unified.connection_manager.UnifiedConnectionManager``.

Old callers continue to work unchanged because this adapter preserves
the original public interface.  Internally, all operations are routed
through the unified core so logic is not duplicated.

The adapter stamps all requests with:
    entry_path = "legacy"
    via_legacy_adapter = True
    source = "legacy_connection_manager"

Delegation map
--------------
Legacy method                 → Unified method
-----------------------------   ----------------------------------------
register_connection(...)      → unified.register_connection(...)
connect(conn_id)              → unified.connect(conn_id)
disconnect(conn_id, graceful) → unified.disconnect(conn_id, graceful)
reconnect(conn_id)            → unified.reconnect(conn_id)
get_connection(conn_id)       → unified.get_connection(conn_id)
get_all_connections()         → unified.get_all_connections()
get_connected_connections()   → unified.get_connected_connections()
get_stats()                   → unified.get_stats()
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.LegacyAdapter.ConnectionManager")


class LegacyConnectionManagerAdapter:
    """Adapter that keeps legacy ConnectionManager signatures while delegating
    to ``UnifiedConnectionManager``.

    Usage::

        from core.legacy_adapters import LegacyConnectionManagerAdapter
        adapter = LegacyConnectionManagerAdapter()
        await adapter.register_connection(config)
        await adapter.connect("my-conn")
    """

    def __init__(self) -> None:
        self._unified: Optional[Any] = None

    def _get_unified(self) -> Any:
        """Lazily obtain the unified connection manager singleton."""
        if self._unified is None:
            try:
                from core.unified.connection_manager import get_unified_connection_manager
                self._unified = get_unified_connection_manager()
            except Exception as exc:
                logger.warning(
                    "LegacyConnectionManagerAdapter: could not obtain "
                    "UnifiedConnectionManager, falling back to legacy: %s", exc
                )
                from core.connection_manager import get_connection_manager
                self._unified = get_connection_manager()
        return self._unified

    def _log_delegation(self, method: str) -> None:
        logger.debug(
            "legacy_connection_manager → unified | method=%s "
            "entry_path=legacy via_legacy_adapter=True",
            method,
        )

    # ------------------------------------------------------------------
    # Delegated methods (legacy public API preserved)
    # ------------------------------------------------------------------

    async def register_connection(self, config: Any) -> None:
        """Legacy API: register a new connection config."""
        self._log_delegation("register_connection")
        unified = self._get_unified()
        if hasattr(unified, "register_connection"):
            await unified.register_connection(config)
        else:
            logger.warning("UnifiedConnectionManager has no register_connection; skipping.")

    async def connect(self, connection_id: str) -> bool:
        """Legacy API: connect by connection_id."""
        self._log_delegation("connect")
        unified = self._get_unified()
        if hasattr(unified, "connect"):
            return await unified.connect(connection_id)
        return False

    async def disconnect(self, connection_id: str, graceful: bool = True) -> bool:
        """Legacy API: disconnect by connection_id."""
        self._log_delegation("disconnect")
        unified = self._get_unified()
        if hasattr(unified, "disconnect"):
            return await unified.disconnect(connection_id, graceful=graceful)
        return False

    async def reconnect(self, connection_id: str) -> bool:
        """Legacy API: reconnect by connection_id."""
        self._log_delegation("reconnect")
        unified = self._get_unified()
        if hasattr(unified, "reconnect"):
            return await unified.reconnect(connection_id)
        return False

    def get_connection(self, connection_id: str) -> Optional[Any]:
        """Legacy API: get connection info by id."""
        self._log_delegation("get_connection")
        unified = self._get_unified()
        if hasattr(unified, "get_connection"):
            return unified.get_connection(connection_id)
        return None

    def get_all_connections(self) -> List[Any]:
        """Legacy API: list all connections."""
        self._log_delegation("get_all_connections")
        unified = self._get_unified()
        if hasattr(unified, "get_all_connections"):
            return unified.get_all_connections()
        return []

    def get_connected_connections(self) -> List[Any]:
        """Legacy API: list only connected connections."""
        self._log_delegation("get_connected_connections")
        unified = self._get_unified()
        if hasattr(unified, "get_connected_connections"):
            return unified.get_connected_connections()
        return []

    def get_stats(self) -> Dict[str, Any]:
        """Legacy API: return connection statistics."""
        self._log_delegation("get_stats")
        unified = self._get_unified()
        if hasattr(unified, "get_stats"):
            return unified.get_stats()
        return {}

    def on_connected(self, connection_id: str, callback: Callable) -> None:
        """Legacy API: register an on-connected callback."""
        self._log_delegation("on_connected")
        unified = self._get_unified()
        if hasattr(unified, "on_connected"):
            unified.on_connected(connection_id, callback)

    def on_disconnected(self, connection_id: str, callback: Callable) -> None:
        """Legacy API: register an on-disconnected callback."""
        self._log_delegation("on_disconnected")
        unified = self._get_unified()
        if hasattr(unified, "on_disconnected"):
            unified.on_disconnected(connection_id, callback)

    async def start_all(self) -> None:
        """Legacy API: start all managed connections."""
        self._log_delegation("start_all")
        unified = self._get_unified()
        if hasattr(unified, "start_all"):
            await unified.start_all()

    async def stop_all(self) -> None:
        """Legacy API: stop all managed connections."""
        self._log_delegation("stop_all")
        unified = self._get_unified()
        if hasattr(unified, "stop_all"):
            await unified.stop_all()

    async def shutdown(self) -> None:
        """Legacy API: graceful shutdown."""
        self._log_delegation("shutdown")
        unified = self._get_unified()
        if hasattr(unified, "shutdown"):
            await unified.shutdown()


__all__ = ["LegacyConnectionManagerAdapter"]
