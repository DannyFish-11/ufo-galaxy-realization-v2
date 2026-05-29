"""
launcher/launcher_adapter.py
============================
PR-DEVICE-RESOLUTION: Unified Node Launcher Adapter

Bridge between the Device Resolution & Activation Plane and the
NodeSystemLauncher.  This adapter is the ONLY component that translates
resolution decisions into concrete node-start actions.

Design principles:
    - ONLY speaks Unified Node Contract (via facade layer)
    - NEVER calls node dialect endpoints directly
    - Feature-flag controlled (observe_only / dry_run / allowlist / full)
    - Integrates resolver + policy + registry into one closed loop
    - Structured logging for every decision

Feature modes (set via LAUNCHER_ADAPTER_MODE env var):
    observe_only  — Records decisions, never starts nodes (DEFAULT)
    dry_run       — Simulates full flow, logs what WOULD happen
    allowlist     — Only starts nodes in LAUNCHER_ADAPTER_ALLOWLIST
    full          — Full autonomous activation (USE WITH CARE)

Usage::

    from launcher.launcher_adapter import LauncherAdapter

    adapter = LauncherAdapter(node_launcher)
    await adapter.start()  # resolves mappings, records to registry

    # After UDM device registration:
    result = await adapter.on_device_registered(device)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
LAUNCHER_ADAPTER_SENTINEL = (
    "LAUNCHER_ADAPTER::UNIFIED_NODE_CONTRACT_LAUNCH_BRIDGE"
)


# ---------------------------------------------------------------------------
# Feature mode
# ---------------------------------------------------------------------------
class AdapterMode(str, Enum):
    """Feature-flag controlled execution mode."""

    OBSERVE_ONLY = "observe_only"
    """Default: records all decisions, never starts any node."""

    DRY_RUN = "dry_run"
    """Simulates the full flow and logs what WOULD happen."""

    ALLOWLIST = "allowlist"
    """Only starts nodes listed in LAUNCHER_ADAPTER_ALLOWLIST env var."""

    FULL = "full"
    """Full autonomous activation.  USE WITH CARE — test in dry_run first."""


# ---------------------------------------------------------------------------
# LauncherAdapter
# ---------------------------------------------------------------------------
class LauncherAdapter:
    """Unified launcher adapter — the Golden Path execution bridge.

    Connects the Device Resolution & Activation Plane to the
    NodeSystemLauncher via the Unified Node Contract facade layer.

    Args:
        node_launcher: The NodeSystemLauncher instance from unified_launcher.py.
        mode: Execution mode (defaults to env LAUNCHER_ADAPTER_MODE or observe_only).
    """

    def __init__(
        self,
        node_launcher: Any,
        mode: Optional[AdapterMode] = None,
    ) -> None:
        self.node_launcher = node_launcher
        self.mode = mode or self._detect_mode()
        self.allowlist: Set[str] = self._load_allowlist()
        self._started_nodes: Set[str] = set()
        self._shutdown = False

        logger.info(
            "[LauncherAdapter] initialised mode=%s allowlist=%s",
            self.mode.value,
            sorted(self.allowlist) if self.allowlist else "(none)",
        )

    # -- mode detection ------------------------------------------------------

    @staticmethod
    def _detect_mode() -> AdapterMode:
        raw = os.environ.get("LAUNCHER_ADAPTER_MODE", "observe_only").lower().strip()
        try:
            return AdapterMode(raw)
        except ValueError:
            logger.warning("Invalid LAUNCHER_ADAPTER_MODE='%s', using observe_only", raw)
            return AdapterMode.OBSERVE_ONLY

    @staticmethod
    def _load_allowlist() -> Set[str]:
        raw = os.environ.get("LAUNCHER_ADAPTER_ALLOWLIST", "")
        if not raw:
            return set()
        return {n.strip() for n in raw.split(",") if n.strip()}

    # -- public API ----------------------------------------------------------

    async def start(self) -> Dict[str, Any]:
        """Run at system boot: resolve all core-node mappings and record.

        This is called by unified_launcher.py during startup.
        It resolves every mapping in device_node_map.yaml that points to
        a core boot node, evaluates policy, and records the decision.
        Depending on mode, it may also trigger node starts.
        """
        from core.device_activation_registry import get_registry as get_act_registry
        from core.device_node_resolver import DeviceNodeResolver
        from core.activation_policy import ActivationPolicyEngine

        t0 = time.perf_counter()
        registry = get_act_registry()
        resolver = DeviceNodeResolver()
        resolver._ensure_loaded()
        engine = ActivationPolicyEngine()

        results: Dict[str, Any] = {"resolved": 0, "started": 0, "skipped": 0, "mode": self.mode.value}

        # Find all mappings for nodes in the core boot set
        core_nodes: Set[str] = set()
        if hasattr(self.node_launcher, "get_core_nodes"):
            core_nodes = set(self.node_launcher.get_core_nodes())

        for mapping in resolver._mappings:
            impl = mapping.get("implementation", {})
            node_name = impl.get("node", "")

            # Only process mappings for nodes that will actually start
            if node_name not in core_nodes:
                continue

            match = mapping.get("match", {})
            device_type = match.get("device_type")
            transport = match.get("transport")
            capabilities = match.get("capabilities", [])

            # Resolve (we already know the mapping, but run through resolver for audit)
            resolved = resolver.resolve(
                device_type=device_type,
                transport=transport,
                capabilities=capabilities if not device_type and not transport else None,
            )

            if resolved is None:
                results["skipped"] += 1
                continue

            # Evaluate policy
            decision = engine.evaluate(
                resolved.implementation,
                ActivationPolicyEngine.TRIGGER_BOOT,
            )

            # Record to registry (always, regardless of mode)
            duration_ms = (time.perf_counter() - t0) * 1000
            registry.record_resolution(
                device_type=device_type,
                transport=transport,
                capabilities=capabilities if not device_type and not transport else None,
                result=resolved,
                decision=decision,
                source_event="boot",
                source_module="launcher_adapter.start",
                duration_ms=duration_ms,
            )

            results["resolved"] += 1

            # Act based on mode
            if decision.should_start:
                act_result = await self._maybe_start_node(
                    node_name=resolved.implementation.node,
                    device_type=device_type,
                    transport=transport,
                    decision=decision,
                )
                if act_result:
                    results["started"] += 1

        total_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "[LauncherAdapter.start] resolved=%d started=%d skipped=%d mode=%s in %.1fms",
            results["resolved"], results["started"], results["skipped"],
            self.mode.value, total_ms,
        )
        return results

    async def on_device_registered(self, device: Any) -> Optional[Dict[str, Any]]:
        """Handle a device registered in UDM.

        Called by udm_registration_hook.py when a new device appears.
        Flow: resolve → evaluate → (maybe) start node → record.

        Returns:
            Dict with resolution result, or None if unresolved.
        """
        from core.device_node_resolver import get_resolver
        from core.activation_policy import ActivationPolicyEngine
        from core.device_activation_registry import get_registry as get_act_registry

        t0 = time.perf_counter()

        # Extract device fields (duck-typed)
        device_type = self._extract(device, "device_type")
        transport = self._extract(device, "transport")
        capabilities = self._extract_list(device, "capabilities")
        device_id = self._extract(device, "device_id")

        # Resolve
        resolver = get_resolver()
        resolved = resolver.resolve(
            device_type=device_type,
            transport=transport,
            capabilities=capabilities,
        )

        if resolved is None:
            logger.info(
                "[LauncherAdapter] device_id=%s UNRESOLVED — no mapping",
                device_id,
            )
            return None

        # Evaluate policy
        engine = ActivationPolicyEngine()
        decision = engine.evaluate(
            resolved.implementation,
            ActivationPolicyEngine.TRIGGER_DEVICE_REGISTERED,
            device_count=1,
        )

        # Record
        registry = get_act_registry()
        duration_ms = (time.perf_counter() - t0) * 1000
        registry.record_resolution(
            device_type=device_type,
            transport=transport,
            capabilities=capabilities,
            device_id=device_id,
            result=resolved,
            decision=decision,
            source_event="device_registered",
            source_module="launcher_adapter.on_device_registered",
            duration_ms=duration_ms,
        )

        # Act
        act_result = None
        if decision.should_start:
            act_result = await self._maybe_start_node(
                node_name=resolved.implementation.node,
                device_type=device_type,
                transport=transport,
                decision=decision,
            )

        result = {
            "device_id": device_id,
            "resolved_node": resolved.implementation.node,
            "node_port": resolved.implementation.port,
            "activation_policy": resolved.implementation.startup,
            "decision": decision.decision if decision else "unknown",
            "should_start": decision.should_start if decision else False,
            "reason": decision.reason if decision else "",
            "started": act_result is not None,
            "mode": self.mode.value,
            "duration_ms": round(duration_ms, 2),
        }

        logger.info(
            "[LauncherAdapter] device_id=%s → %s:%d | %s | mode=%s",
            device_id, result["resolved_node"], result["node_port"],
            result["decision"], self.mode.value,
        )
        return result

    async def shutdown(self) -> None:
        """Graceful shutdown — stop any nodes started by this adapter."""
        self._shutdown = True
        for node_name in list(self._started_nodes):
            try:
                if hasattr(self.node_launcher, "stop_node"):
                    await self.node_launcher.stop_node(node_name)
                    logger.info("[LauncherAdapter] Stopped %s", node_name)
            except Exception as exc:
                logger.warning("[LauncherAdapter] Failed to stop %s: %s", node_name, exc)
        self._started_nodes.clear()

    # -- internal action -----------------------------------------------------

    async def _maybe_start_node(
        self,
        *,
        node_name: str,
        device_type: Optional[str],
        transport: Optional[str],
        decision: Any,
    ) -> Optional[str]:
        """Maybe start a node based on current mode.

        Returns:
            node_name if started (or simulated), None if blocked.
        """
        # Mode: observe_only — never start
        if self.mode == AdapterMode.OBSERVE_ONLY:
            logger.debug(
                "[LauncherAdapter] OBSERVE_ONLY: would start %s (%s)",
                node_name, decision.reason,
            )
            return None

        # Mode: dry_run — log what would happen
        if self.mode == AdapterMode.DRY_RUN:
            logger.info(
                "[LauncherAdapter] DRY_RUN: would start %s | policy=%s | reason=%s",
                node_name, decision.policy.value if decision else "?", decision.reason,
            )
            return node_name  # Return as if started, but don't actually start

        # Mode: allowlist — check whitelist
        if self.mode == AdapterMode.ALLOWLIST:
            if node_name not in self.allowlist:
                logger.info(
                    "[LauncherAdapter] ALLOWLIST: blocked %s (not in allowlist)",
                    node_name,
                )
                return None

        # Mode: full — proceed to start
        # Check if already started
        if node_name in self._started_nodes:
            logger.debug("[LauncherAdapter] %s already started", node_name)
            return node_name

        # Actually start the node
        try:
            success = await self.node_launcher.start_node(node_name)
            if success:
                self._started_nodes.add(node_name)
                logger.info("[LauncherAdapter] STARTED %s", node_name)
                return node_name
            else:
                logger.warning("[LauncherAdapter] FAILED to start %s", node_name)
                return None
        except Exception as exc:
            logger.error("[LauncherAdapter] EXCEPTION starting %s: %s", node_name, exc)
            return None

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _extract(device: Any, key: str) -> Optional[str]:
        if hasattr(device, key):
            val = getattr(device, key)
            return str(val) if val is not None else None
        if isinstance(device, dict):
            val = device.get(key)
            return str(val) if val is not None else None
        return None

    @staticmethod
    def _extract_list(device: Any, key: str) -> List[str]:
        if hasattr(device, key):
            val = getattr(device, key)
            if isinstance(val, (list, tuple, set)):
                return [str(v) for v in val]
        if isinstance(device, dict):
            val = device.get(key)
            if isinstance(val, (list, tuple, set)):
                return [str(v) for v in val]
        return []
