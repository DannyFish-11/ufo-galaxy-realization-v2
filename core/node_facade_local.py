"""
core/node_facade_local.py
=========================
PR-GOLDEN-PATH-LOCAL: Local Node Facade — Golden Path entry point.

This module bridges the Golden Path (device_node_map → resolver → facade)
into the main invocation chain (node_invocation.py).  Unlike the HTTP-based
node_facade.py, this facade performs direct Python calls to node
fusion_entry.py modules — no HTTP overhead.

Design
------
1. node_invocation.py calls LocalNodeFacade.invoke()
2. invoke() looks up the node via DeviceNodeResolver
3. If a mapping exists, it loads the node's fusion_entry.py
4. Maps the unified action to the node's native function
5. Returns a UnifiedResponse

This is the **strangler fig** layer: old nodes continue to work via
direct fusion_entry.py loading, but new nodes go through the unified
contract. Over time, all nodes migrate to the unified path.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from core.schemas.aip_v3 import TaskResultMsg

logger = logging.getLogger("Galaxy.NodeFacadeLocal")

# Node system root
NODES_ROOT = Path(__file__).resolve().parent.parent / "nodes"

# PR-AIPV3
try:
    from core.schemas.aip_v3 import MsgType  # noqa: F401
    _AIPV3_AVAILABLE = True
except ImportError:
    _AIPV3_AVAILABLE = False

# Action → fusion_entry function name mapping for 5 key nodes
_ACTION_MAP: Dict[str, Dict[str, str]] = {
    "Node_33_ADB": {
        "adb_shell": "execute",
        "adb_screenshot": "execute",
        "adb_tap": "execute",
        "adb_swipe": "execute",
        "adb_input_text": "execute",
        "adb_keyevent": "execute",
        "execute": "execute",
    },
    "Node_38_BLE": {
        "ble_scan": "execute",
        "ble_connect": "execute",
        "ble_disconnect": "execute",
        "ble_read": "execute",
        "ble_write": "execute",
        "ble_notify": "execute",
        "execute": "execute",
    },
    "Node_41_MQTT": {
        "mqtt_publish": "execute",
        "mqtt_subscribe": "execute",
        "mqtt_unsubscribe": "execute",
        "mqtt_connect": "execute",
        "mqtt_disconnect": "execute",
        "execute": "execute",
    },
    "Node_45_DesktopAuto": {
        "ui_click": "execute",
        "ui_type": "execute",
        "ui_screenshot": "execute",
        "ui_find": "execute",
        "ui_hotkey": "execute",
        "execute": "execute",
    },
    "Node_48_Serial": {
        "serial_open": "execute",
        "serial_close": "execute",
        "serial_read": "execute",
        "serial_write": "execute",
        "serial_flush": "execute",
        "serial_list_ports": "execute",
        "execute": "execute",
    },
}

# In-memory module cache
_module_cache: Dict[str, Any] = {}


def _load_fusion_entry(node_id: str) -> Optional[Any]:
    """Load a node's fusion_entry.py module (cached)."""
    if node_id in _module_cache:
        return _module_cache[node_id]

    fusion_path = NODES_ROOT / node_id / "fusion_entry.py"
    if not fusion_path.exists():
        logger.debug("LocalFacade: fusion_entry.py not found for %s", node_id)
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            f"nodes.{node_id}.fusion_entry", str(fusion_path)
        )
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"nodes.{node_id}.fusion_entry"] = mod
        spec.loader.exec_module(mod)
        _module_cache[node_id] = mod
        return mod
    except Exception as exc:
        logger.debug("LocalFacade: failed to load %s: %s", node_id, exc)
        return None


class LocalNodeFacade:
    """Local facade that performs direct Python calls to node fusion_entry.

    This is the Golden Path entry point for node invocation.
    """

    async def invoke(
        self,
        *,
        node_id: str,
        action: str,
        params: Dict[str, Any],
        device_id: str = "",
        timeout_ms: int = 30000,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """Invoke a node action through the Golden Path.

        Steps:
        1. Look up device_node_map via DeviceNodeResolver
        2. If mapped, load the node's fusion_entry.py
        3. Map unified action to native function
        4. Execute and return UnifiedResponse format

        Returns:
            {"success": bool, "result": any, "error": str, "duration_ms": int}
        """
        started = time.time()

        # Step 1: Resolve via device_node_map
        try:
            from core.device_node_resolver import get_resolver  # noqa: PLC0415

            resolver = get_resolver()
            mapping = resolver.resolve_by_node_id(node_id)
            if mapping is None:
                # No mapping — return None to fall back to legacy path
                return {"success": False, "error": "NO_MAPPING", "fallback": True}
        except Exception as exc:
            logger.debug("LocalFacade: resolver unavailable: %s", exc)
            return {"success": False, "error": f"resolver_error:{exc}", "fallback": True}

        # Step 2: Load fusion_entry
        mapped_node_id = mapping.get("node", node_id)
        mod = _load_fusion_entry(mapped_node_id)
        if mod is None:
            return {"success": False, "error": f"cannot_load_fusion_entry:{mapped_node_id}", "fallback": True}

        # Step 3: Map action to function
        action_map = _ACTION_MAP.get(mapped_node_id, {})
        func_name = action_map.get(action, "execute")
        handler = getattr(mod, func_name, None)
        if handler is None:
            # Try generic execute
            handler = getattr(mod, "execute", None)
        if handler is None:
            return {"success": False, "error": f"no_handler_for_action:{action}", "fallback": True}

        # Step 4: Execute
        try:
            # Build call args — match what fusion_entry expects
            call_args = {
                "action": action,
                "params": params,
                "device_id": device_id,
            }
            if trace_id:
                call_args["trace_id"] = trace_id

            # Call handler
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**call_args)
            else:
                result = handler(**call_args)

            duration_ms = int((time.time() - started) * 1000)

            # Normalize result
            if isinstance(result, dict):
                return {
                    "success": result.get("success", True),
                    "result": result.get("result", result),
                    "error": result.get("error", ""),
                    "duration_ms": duration_ms,
                    "node_id": mapped_node_id,
                    "action": action,
                    "via": "golden_path_local_facade",
                }
            else:
                return {
                    "success": True,
                    "result": result,
                    "error": "",
                    "duration_ms": duration_ms,
                    "node_id": mapped_node_id,
                    "action": action,
                    "via": "golden_path_local_facade",
                }

        except Exception as exc:
            duration_ms = int((time.time() - started) * 1000)
            logger.warning(
                "LocalFacade: %s.%s failed: %s", mapped_node_id, action, exc
            )
            return {
                "success": False,
                "result": None,
                "error": f"{mapped_node_id}.{action}: {exc}",
                "duration_ms": duration_ms,
                "node_id": mapped_node_id,
                "action": action,
                "via": "golden_path_local_facade",
            }


# Singleton
_local_facade: Optional[LocalNodeFacade] = None


def get_local_node_facade() -> LocalNodeFacade:
    """Return the module-level :class:`LocalNodeFacade` singleton."""
    global _local_facade
    if _local_facade is None:
        _local_facade = LocalNodeFacade()
    return _local_facade
