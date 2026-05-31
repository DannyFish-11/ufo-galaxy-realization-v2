"""
core/node_capability_loader.py
==============================
PR-NODE-DEVICELESS: Node Capability Loader — pure action mechanism.

Transforms the node system from "device managers" to "capability providers",
similar to MCP Servers / Skills.  Nodes no longer manage device lifecycle;
they only expose action handlers.

Architecture
------------

    Before (device-centric):
        Node_33_ADB → manages ADB connection + provides actions
        Node_38_BLE → manages BLE connection + provides actions
        Node_41_MQTT → manages MQTT connection + provides actions

    After (capability-centric):
        UDM/UCM → manages ALL device connections, heartbeats, lifecycles
        Node_33_ADB → ONLY provides [adb_shell, adb_screenshot, adb_tap]
        Node_38_BLE → ONLY provides [ble_scan, ble_connect, ble_read, ble_write]
        Node_41_MQTT → ONLY provides [mqtt_publish, mqtt_subscribe, mqtt_connect]
        Node_45_DesktopAuto → ONLY provides [click, type, screenshot]
        Node_48_Serial → ONLY provides [serial_read, serial_write, serial_connect]

    Device → UDM (lifecycle management)
      ↓
    Needs ADB action → Node_33_ADB handler
    Needs BLE action → Node_38_BLE handler

    One device can use multiple nodes.
    One node can serve multiple devices.

Usage::
    from core.node_capability_loader import get_capability_loader

    loader = get_capability_loader()
    loader.load_all_capabilities()
    handler = loader.get_handler("adb_shell")
    result = await handler(device_id="phone_01", params={"command": "ls /sdcard"})
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeCapabilityLoader")

# PR-AIPV3: AIP v3 unified message emission
try:
    from core.schemas.aip_v3 import CapabilityReportMsg  # noqa: F401
    from core.nats_bus import get_nats_bus  # noqa: F401
    _AIPV3_AVAILABLE = True
except ImportError:
    _AIPV3_AVAILABLE = False

# Node system root
NODES_ROOT = Path(__file__).resolve().parent.parent / "nodes"

# ---------------------------------------------------------------------------
# CapabilityAction — single action exposed by a node
# ---------------------------------------------------------------------------


@dataclass
class CapabilityAction:
    """A single action handler exposed by a node capability."""

    name: str
    """Action name: e.g. 'adb_shell', 'ble_scan', 'mqtt_publish'."""

    node_id: str
    """Source node: e.g. 'Node_33_ADB'."""

    handler: Callable[..., Awaitable[Any]]
    """Async handler function."""

    description: str = ""
    """Human-readable description."""

    params_schema: Dict[str, Any] = field(default_factory=dict)
    """Expected parameters schema (for validation hints)."""


# ---------------------------------------------------------------------------
# NodeCapabilityLoader
# ---------------------------------------------------------------------------


class NodeCapabilityLoader:
    """Loads node capabilities as pure action handlers.

    Nodes are treated as MCP-like capability providers.  Each node exposes
    a set of actions via its ``capability_manifest()`` function.  The loader
    discovers nodes, loads their manifests, and registers action handlers.

    Device lifecycle (connection, heartbeat, disconnection) is managed by
    UDM/UCM, NOT by nodes.
    """

    _instance: Optional["NodeCapabilityLoader"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._actions: Dict[str, CapabilityAction] = {}
        self._node_actions: Dict[str, List[str]] = {}
        self._initialized = True

    # ── Discovery ──

    def discover_nodes(self) -> List[str]:
        """Discover all node directories under ``nodes/``.

        Returns list of node IDs like ``['Node_33_ADB', 'Node_38_BLE', ...]``.
        """
        nodes = []
        if not NODES_ROOT.exists():
            return nodes
        for entry in sorted(NODES_ROOT.iterdir()):
            if entry.is_dir() and entry.name.startswith("Node_"):
                fusion_entry = entry / "fusion_entry.py"
                if fusion_entry.exists():
                    nodes.append(entry.name)
        logger.info("NodeCapabilityLoader: discovered %d nodes", len(nodes))
        return nodes

    # ── Loading ──

    async def load_node_capabilities(self, node_id: str) -> List[CapabilityAction]:
        """Load capabilities from a single node.

        Expects the node to expose ``capability_manifest()`` in its
        ``fusion_entry.py``.  If not found, falls back to extracting actions
        from the node's ``execute()`` method.

        Returns list of CapabilityAction handlers registered.
        """
        node_dir = NODES_ROOT / node_id
        fusion_path = node_dir / "fusion_entry.py"
        if not fusion_path.exists():
            logger.debug("Node %s: no fusion_entry.py", node_id)
            return []

        try:
            # Dynamic import of fusion_entry.py
            spec = importlib.util.spec_from_file_location(
                f"nodes.{node_id}.fusion_entry", str(fusion_path)
            )
            if spec is None or spec.loader is None:
                return []
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"nodes.{node_id}.fusion_entry"] = mod
            spec.loader.exec_module(mod)

            # Try capability_manifest() first
            if hasattr(mod, "capability_manifest"):
                manifest = mod.capability_manifest()
                return self._register_from_manifest(node_id, manifest, mod)

            # Fallback: extract from execute function
            if hasattr(mod, "execute"):
                return self._register_from_execute(node_id, mod)

            logger.debug("Node %s: no capability_manifest or execute found", node_id)
            return []

        except Exception as exc:
            logger.debug("Node %s: capability loading failed: %s", node_id, exc)
            return []

    def _register_from_manifest(
        self, node_id: str, manifest: Dict[str, Any], mod: Any
    ) -> List[CapabilityAction]:
        """Register actions from a capability manifest."""
        actions: List[CapabilityAction] = []
        action_list = manifest.get("actions", [])
        for action_def in action_list:
            action_name = action_def.get("name", "")
            handler_name = action_def.get("handler", action_name)
            handler = getattr(mod, handler_name, None)
            if handler is None:
                # Try the default execute as fallback
                handler = getattr(mod, "execute", None)
            if handler and action_name:
                action = CapabilityAction(
                    name=action_name,
                    node_id=node_id,
                    handler=handler,
                    description=action_def.get("description", ""),
                    params_schema=action_def.get("params", {}),
                )
                self._actions[action_name] = action
                if node_id not in self._node_actions:
                    self._node_actions[node_id] = []
                self._node_actions[node_id].append(action_name)
                actions.append(action)

        if actions:
            logger.info(
                "Node %s: registered %d actions: %s",
                node_id,
                len(actions),
                [a.name for a in actions],
            )
            self._emit_capability_report(node_id, [a.name for a in actions])
        return actions

    def _register_from_execute(self, node_id: str, mod: Any) -> List[CapabilityAction]:
        """Fallback: register a single action named after the node."""
        handler = getattr(mod, "execute", None)
        if handler is None:
            return []

        action_name = node_id.lower().replace("node_", "").replace("_", "_")
        action = CapabilityAction(
            name=action_name,
            node_id=node_id,
            handler=handler,
            description=f"Execute handler from {node_id}",
        )
        self._actions[action_name] = action
        self._node_actions[node_id] = [action_name]
        logger.info("Node %s: registered single action '%s'", node_id, action_name)
        self._emit_capability_report(node_id, [action_name])
        return [action]

    # ── Bulk operations ──

    async def load_all_capabilities(self) -> Dict[str, List[str]]:
        """Load capabilities from all discovered nodes.

        Returns mapping: ``{node_id: [action_name, ...]}``.
        """
        node_ids = self.discover_nodes()
        result: Dict[str, List[str]] = {}
        for node_id in node_ids:
            actions = await self.load_node_capabilities(node_id)
            if actions:
                result[node_id] = [a.name for a in actions]
        logger.info(
            "NodeCapabilityLoader: loaded %d actions from %d nodes",
            len(self._actions),
            len(result),
        )
        return result

    # ── Query ──

    def get_handler(self, action_name: str) -> Optional[Callable[..., Awaitable[Any]]]:
        """Get handler for an action by name.

        Returns the async handler function, or None if not found.
        """
        action = self._actions.get(action_name)
        return action.handler if action else None

    def get_action_info(self, action_name: str) -> Optional[CapabilityAction]:
        """Get full CapabilityAction metadata for an action."""
        return self._actions.get(action_name)

    def list_actions(self) -> List[str]:
        """List all registered action names."""
        return sorted(self._actions.keys())

    def list_node_actions(self, node_id: str) -> List[str]:
        """List actions provided by a specific node."""
        return list(self._node_actions.get(node_id, []))

    def has_action(self, action_name: str) -> bool:
        """Check if an action is available."""
        return action_name in self._actions

    # ── Execution ──

    async def execute(
        self,
        action_name: str,
        *,
        device_id: str = "",
        params: Optional[Dict[str, Any]] = None,
        timeout_ms: int = 30000,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """Execute an action by name.

        Args:
            action_name: Action to execute (e.g. 'adb_shell').
            device_id: Target device (managed by UDM, not the node).
            params: Action parameters.
            timeout_ms: Execution timeout.
            trace_id: Trace identifier.

        Returns:
            {"success": bool, "result": any, "error": str, "duration_ms": int}
        """
        action = self._actions.get(action_name)
        if action is None:
            return {
                "success": False,
                "error": f"Action '{action_name}' not found. Available: {self.list_actions()}",
            }

        t0 = time.time()
        try:
            # Call handler with standardized signature
            result = await asyncio.wait_for(
                action.handler(
                    device_id=device_id,
                    params=params or {},
                    trace_id=trace_id,
                ),
                timeout=timeout_ms / 1000.0,
            )
            duration_ms = int((time.time() - t0) * 1000)
            return {
                "success": True,
                "result": result,
                "error": "",
                "duration_ms": duration_ms,
                "node_id": action.node_id,
                "action": action_name,
            }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"Action '{action_name}' timed out after {timeout_ms}ms",
                "duration_ms": timeout_ms,
            }
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            duration_ms = int((time.time() - t0) * 1000)
            return {
                "success": False,
                "error": f"Action '{action_name}' failed: {exc}",
                "duration_ms": duration_ms,
            }

    # ── AIP v3 emission ──

    def _emit_capability_report(self, node_id: str, actions: List[str]) -> None:
        """Emit CAPABILITY_REPORT AIP v3 message for node capabilities."""
        if not _AIPV3_AVAILABLE:
            return
        try:
            import asyncio

            msg = CapabilityReportMsg(
                device_id=node_id,
                capabilities=actions,
                actions=actions,
            )
            nats = get_nats_bus()
            if nats.is_connected():
                asyncio.get_event_loop().create_task(nats.publish_capability_report(msg))
            else:
                logger.debug("AIPV3-NODE CAPABILITY_REPORT: %s", msg.model_dump_json(exclude_none=True))
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # ── 5-key-node capability profiles (PR-AIPV3) ──

    def get_key_node_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Return capability profiles for the 5 key device nodes.

        These profiles define the actions each node should expose in its
        ``capability_manifest()``.  Nodes that don't yet have manifests
        can use these as reference.

        Returns::

            {
                "Node_33_ADB": {
                    "description": "Android Debug Bridge actions",
                    "actions": ["adb_shell", "adb_screenshot", "adb_tap", ...],
                },
                ...
            }
        """
        return {
            "Node_33_ADB": {
                "description": "Android Debug Bridge — device control via ADB",
                "actions": [
                    {"name": "adb_shell", "description": "Execute shell command on Android device", "params": {"command": "string", "timeout_ms": "int"}},
                    {"name": "adb_screenshot", "description": "Capture device screen", "params": {"format": "string", "quality": "int"}},
                    {"name": "adb_tap", "description": "Tap screen at coordinates", "params": {"x": "int", "y": "int"}},
                    {"name": "adb_swipe", "description": "Swipe screen", "params": {"x1": "int", "y1": "int", "x2": "int", "y2": "int", "duration_ms": "int"}},
                    {"name": "adb_input_text", "description": "Type text", "params": {"text": "string"}},
                    {"name": "adb_keyevent", "description": "Send key event", "params": {"keycode": "int"}},
                ],
            },
            "Node_38_BLE": {
                "description": "Bluetooth Low Energy — scan, connect, read, write",
                "actions": [
                    {"name": "ble_scan", "description": "Scan for BLE devices", "params": {"duration_ms": "int", "service_uuid": "string"}},
                    {"name": "ble_connect", "description": "Connect to BLE device", "params": {"address": "string", "auto_discover": "bool"}},
                    {"name": "ble_disconnect", "description": "Disconnect from BLE device", "params": {"address": "string"}},
                    {"name": "ble_read", "description": "Read GATT characteristic", "params": {"address": "string", "uuid": "string"}},
                    {"name": "ble_write", "description": "Write GATT characteristic", "params": {"address": "string", "uuid": "string", "data": "bytes"}},
                    {"name": "ble_notify", "description": "Subscribe to notifications", "params": {"address": "string", "uuid": "string", "enable": "bool"}},
                ],
            },
            "Node_41_MQTT": {
                "description": "MQTT — IoT device messaging",
                "actions": [
                    {"name": "mqtt_publish", "description": "Publish MQTT message", "params": {"topic": "string", "payload": "string", "qos": "int"}},
                    {"name": "mqtt_subscribe", "description": "Subscribe to MQTT topic", "params": {"topic": "string", "qos": "int"}},
                    {"name": "mqtt_unsubscribe", "description": "Unsubscribe from topic", "params": {"topic": "string"}},
                    {"name": "mqtt_connect", "description": "Connect to MQTT broker", "params": {"host": "string", "port": "int", "client_id": "string"}},
                    {"name": "mqtt_disconnect", "description": "Disconnect from broker", "params": {}},
                ],
            },
            "Node_45_DesktopAuto": {
                "description": "Desktop Automation — UI control",
                "actions": [
                    {"name": "ui_click", "description": "Click at screen coordinates", "params": {"x": "int", "y": "int"}},
                    {"name": "ui_type", "description": "Type text", "params": {"text": "string", "interval": "float"}},
                    {"name": "ui_screenshot", "description": "Capture desktop screenshot", "params": {"region": "tuple", "format": "string"}},
                    {"name": "ui_find", "description": "Find image on screen", "params": {"image_path": "string", "confidence": "float"}},
                    {"name": "ui_hotkey", "description": "Press hotkey combination", "params": {"keys": "list"}},
                ],
            },
            "Node_48_Serial": {
                "description": "Serial/UART — hardware communication",
                "actions": [
                    {"name": "serial_open", "description": "Open serial port", "params": {"port": "string", "baudrate": "int"}},
                    {"name": "serial_close", "description": "Close serial port", "params": {"port": "string"}},
                    {"name": "serial_read", "description": "Read from serial port", "params": {"port": "string", "size": "int", "timeout_ms": "int"}},
                    {"name": "serial_write", "description": "Write to serial port", "params": {"port": "string", "data": "bytes"}},
                    {"name": "serial_flush", "description": "Flush serial buffer", "params": {"port": "string"}},
                    {"name": "serial_list_ports", "description": "List available serial ports", "params": {}},
                ],
            },
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_loader_instance: Optional[NodeCapabilityLoader] = None


def get_capability_loader() -> NodeCapabilityLoader:
    """Return the module-level :class:`NodeCapabilityLoader` singleton."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = NodeCapabilityLoader()
    return _loader_instance
