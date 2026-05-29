"""
core/udm_registration_hook.py
=============================
PR-DEVICE-RESOLUTION: UDM Device Registration Hook

Listens for device registration events and feeds them into the
Device Resolution & Activation Plane.

Two entry points:
    1. **Explicit call**: ``on_device_registered()`` — called directly by
       gateway handlers after UDM.write().
    2. **Event-driven**: ``listen()`` — subscribes to state_event_bus
       ``DEVICE_UPDATED`` events (future, not active yet).

This module is Stage 2 of the Device Resolution pipeline:
    registry/device_node_map.yaml → resolver → policy → THIS HOOK

The hook itself is observe-only; it records decisions but does NOT
start nodes.  Node starting is Stage 3 (launcher_adapter.py).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
UDM_REGISTRATION_HOOK_SENTINEL = (
    "UDM_REGISTRATION_HOOK::DEVICE_RESOLUTION_EVENT_INGRESS"
)


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------
class UDMRegistrationHook:
    """Hook into UDM device registration for resolution & activation tracing.

    Usage (explicit call from gateway handlers)::

        from core.udm_registration_hook import get_hook
        from core.unified.models import UnifiedDevice

        hook = get_hook()
        await hook.on_device_registered(device)

    Usage (event-driven, future)::

        hook = get_hook()
        await hook.listen()  # subscribes to state_event_bus
    """

    def __init__(self) -> None:
        self._listening = False

    # -- Stage 2: explicit call (current) ------------------------------------

    async def on_device_registered(
        self,
        device: Any,  # UnifiedDevice or dict-like
        *,
        source: str = "unknown",
        trace_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Process a newly registered device through the resolution plane.

        Called by gateway handlers (Android, BLE, MQTT, etc.) after the
        device has been written to UDM.  This is the **primary entry point**
        for Stage 2.

        Flow:
            1. Extract device_type / transport / capabilities from device
            2. Call DeviceNodeResolver.resolve()
            3. Call ActivationPolicyEngine.evaluate()
            4. Record everything to DeviceActivationRegistry
            5. Return the decision (for upstream inspection)

        Args:
            device: A UnifiedDevice instance or dict with keys:
                    device_type, transport, capabilities, device_id
            source: Which gateway handler triggered this (e.g. "android").
            trace_id: End-to-end correlation ID.

        Returns:
            Dict with resolution + decision, or None if resolution failed.
        """
        from core.device_activation_registry import get_registry as get_act_registry
        from core.device_node_resolver import get_resolver
        from core.activation_policy import ActivationPolicyEngine

        t0 = time.perf_counter()

        # Extract fields from UnifiedDevice (duck-typed)
        device_type = self._extract(device, "device_type")
        transport = self._extract(device, "transport")
        capabilities = self._extract_list(device, "capabilities")
        device_id = self._extract(device, "device_id")

        logger.info(
            "[UDMHook] device_id=%s type=%s transport=%s caps=%s source=%s",
            device_id, device_type, transport, capabilities, source,
        )

        # Resolve to Node
        resolver = get_resolver()
        resolved = resolver.resolve(
            device_type=device_type,
            transport=transport,
            capabilities=capabilities,
        )

        # Evaluate activation policy
        decision = None
        if resolved:
            engine = ActivationPolicyEngine()
            decision = engine.evaluate(
                resolved.implementation,
                ActivationPolicyEngine.TRIGGER_DEVICE_REGISTERED,
                device_count=1,
            )

        # Record to registry (observe-only)
        registry = get_act_registry()
        duration_ms = (time.perf_counter() - t0) * 1000

        registry.record_resolution(
            device_type=device_type,
            transport=transport,
            capabilities=capabilities,
            device_id=device_id,
            result=resolved,
            decision=decision,
            trace_id=trace_id,
            source_event="device_registered",
            source_module=f"udm_registration_hook.{source}",
            duration_ms=duration_ms,
        )

        if resolved is None:
            logger.info(
                "[UDMHook] device_id=%s UNRESOLVED — no mapping for type=%s transport=%s",
                device_id, device_type, transport,
            )
            return None

        result = {
            "device_id": device_id,
            "resolved_node": resolved.implementation.node,
            "node_port": resolved.implementation.port,
            "match_type": resolved.match_type,
            "activation_policy": resolved.implementation.startup,
            "decision": decision.decision if decision else "unknown",
            "should_start": decision.should_start if decision else False,
            "reason": decision.reason if decision else "",
            "duration_ms": round(duration_ms, 2),
        }

        logger.info(
            "[UDMHook] device_id=%s → %s:%d | %s | %s",
            device_id,
            result["resolved_node"],
            result["node_port"],
            result["decision"],
            result["reason"][:60],
        )

        return result

    # -- Stage 2b: event-driven (future) -------------------------------------

    async def listen(self) -> None:
        """Subscribe to state_event_bus DEVICE_UPDATED events.

        This is a **future entry point**.  Not active yet because:
        - UDM.register_device() does not emit StateEventBus events today
        - When it does, this method will auto-feed the resolution pipeline
        """
        if self._listening:
            return

        try:
            from core.state_event_bus import subscribe, StateEventType

            def _on_device_event(event_type, payload):
                asyncio.create_task(self._handle_device_event(payload))

            subscribe(StateEventType.DEVICE_UPDATED, _on_device_event)
            self._listening = True
            logger.info("[UDMHook] Listening for DEVICE_UPDATED events")
        except Exception as exc:
            logger.debug("[UDMHook] Event listening not available: %s", exc)

    async def _handle_device_event(self, payload: Dict[str, Any]) -> None:
        """Handle a DEVICE_UPDATED event from the state event bus."""
        device_data = payload.get("device", {})
        if not device_data:
            return
        await self.on_device_registered(
            device_data,
            source=payload.get("source", "event_bus"),
            trace_id=payload.get("trace_id"),
        )

    # -- internal helpers ----------------------------------------------------

    @staticmethod
    def _extract(device: Any, key: str) -> Optional[str]:
        """Safely extract a string field from UnifiedDevice or dict."""
        if hasattr(device, key):
            val = getattr(device, key)
            return str(val) if val is not None else None
        if isinstance(device, dict):
            val = device.get(key)
            return str(val) if val is not None else None
        return None

    @staticmethod
    def _extract_list(device: Any, key: str) -> List[str]:
        """Safely extract a list field from UnifiedDevice or dict."""
        if hasattr(device, key):
            val = getattr(device, key)
            if isinstance(val, (list, tuple, set)):
                return [str(v) for v in val]
        if isinstance(device, dict):
            val = device.get(key)
            if isinstance(val, (list, tuple, set)):
                return [str(v) for v in val]
        return []


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_hook_instance: Optional[UDMRegistrationHook] = None


def get_hook() -> UDMRegistrationHook:
    """Return the module-level UDMRegistrationHook singleton."""
    global _hook_instance
    if _hook_instance is None:
        _hook_instance = UDMRegistrationHook()
    return _hook_instance


# Convenience: direct function call
async def on_device_registered(
    device: Any,
    *,
    source: str = "unknown",
    trace_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Convenience: process device using the module singleton."""
    return await get_hook().on_device_registered(
        device, source=source, trace_id=trace_id
    )
