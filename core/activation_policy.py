"""
core/activation_policy.py
=========================
PR-DEVICE-RESOLUTION: Device Node Activation Policy

Defines four activation policies for device-node mappings and provides
decision logic for when a Node should be started.

Policies:
    always_on  — Start with core nodes, always available
    on_demand  — Start when UDM registers a matching device
    lazy       — Start on first use, then keep alive
    shared     — Lightweight shared service, start once

This module is policy-only; it does NOT start Nodes.  The actual
activation is performed by launcher/launcher_adapter.py (Stage 3).
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Optional

from core.device_node_resolver import NodeImplementation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
DEVICE_ACTIVATION_POLICY_SENTINEL = (
    "DEVICE_ACTIVATION_POLICY::NODE_STARTUP_DECISION_ENGINE"
)


# ---------------------------------------------------------------------------
# Policy enum
# ---------------------------------------------------------------------------
class ActivationPolicy(enum.Enum):
    """When should a Node be started?"""

    ALWAYS_ON = "always_on"
    """Start with the core node set at system boot.  Always available."""

    ON_DEMAND = "on_demand"
    """Start when UDM registers a device that matches this Node's mapping.
    
    Used for heavy-weight nodes (ADB, DesktopAuto) that should only run
    when a real device is present.
    """

    LAZY = "lazy"
    """Start on first capability request, then keep alive.
    
    Used for medium-weight nodes (BLE, Camera, NFC) that may be needed
    sporadically.
    """

    SHARED = "shared"
    """Lightweight shared service; start once, shared by many devices.
    
    Used for protocol gateways (MQTT) that are cheap to keep running.
    """

    def should_start_with_core(self) -> bool:
        """Should this Node be started in the core boot set?"""
        return self == ActivationPolicy.ALWAYS_ON

    def should_start_on_device_registration(self) -> bool:
        """Should this Node start when a matching device registers in UDM?"""
        return self in (ActivationPolicy.ON_DEMAND, ActivationPolicy.SHARED)

    def should_start_on_first_use(self) -> bool:
        """Should this Node start lazily on first capability request?"""
        return self == ActivationPolicy.LAZY


# ---------------------------------------------------------------------------
# Activation decision
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ActivationDecision:
    """Result of evaluating an activation policy for a Node."""

    node: str
    policy: ActivationPolicy
    should_start: bool
    reason: str


class ActivationPolicyEngine:
    """Evaluate activation policies and produce start/stop decisions.

    Usage::

        engine = ActivationPolicyEngine()
        decision = engine.evaluate(impl, trigger="device_registered")
        # ActivationDecision(node="Node_33_ADB", policy=ON_DEMAND,
        #                    should_start=True, reason="...")
    """

    # Triggers that can cause activation evaluation
    TRIGGER_BOOT = "boot"
    TRIGGER_DEVICE_REGISTERED = "device_registered"
    TRIGGER_CAPABILITY_REQUEST = "capability_request"
    TRIGGER_HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    TRIGGER_MANUAL = "manual"

    def evaluate(
        self,
        implementation: NodeImplementation,
        trigger: str,
        *,
        device_count: int = 0,
    ) -> ActivationDecision:
        """Evaluate whether a Node should start given a trigger event.

        Args:
            implementation: The NodeImplementation to evaluate.
            trigger: One of the TRIGGER_* constants.
            device_count: Number of matching devices currently registered
                         (relevant for ON_DEMAND policy).

        Returns:
            ActivationDecision with should_start=True/False.
        """
        policy = ActivationPolicy(implementation.startup)

        # -- ALWAYS_ON --
        if policy == ActivationPolicy.ALWAYS_ON:
            if trigger == self.TRIGGER_BOOT:
                return ActivationDecision(
                    node=implementation.node,
                    policy=policy,
                    should_start=True,
                    reason="ALWAYS_ON: start with core boot set",
                )
            return ActivationDecision(
                node=implementation.node,
                policy=policy,
                should_start=False,
                reason="ALWAYS_ON: already started at boot",
            )

        # -- ON_DEMAND --
        if policy == ActivationPolicy.ON_DEMAND:
            if trigger == self.TRIGGER_DEVICE_REGISTERED and device_count > 0:
                return ActivationDecision(
                    node=implementation.node,
                    policy=policy,
                    should_start=True,
                    reason=f"ON_DEMAND: {device_count} matching device(s) registered",
                )
            if trigger == self.TRIGGER_HEARTBEAT_TIMEOUT:
                return ActivationDecision(
                    node=implementation.node,
                    policy=policy,
                    should_start=False,
                    reason="ON_DEMAND: heartbeat timeout, no devices — stop",
                )
            return ActivationDecision(
                node=implementation.node,
                policy=policy,
                should_start=False,
                reason="ON_DEMAND: waiting for device registration",
            )

        # -- LAZY --
        if policy == ActivationPolicy.LAZY:
            if trigger == self.TRIGGER_CAPABILITY_REQUEST:
                return ActivationDecision(
                    node=implementation.node,
                    policy=policy,
                    should_start=True,
                    reason="LAZY: first capability request — start",
                )
            return ActivationDecision(
                node=implementation.node,
                policy=policy,
                should_start=False,
                reason="LAZY: waiting for first use",
            )

        # -- SHARED --
        if policy == ActivationPolicy.SHARED:
            if trigger in (self.TRIGGER_BOOT, self.TRIGGER_DEVICE_REGISTERED):
                return ActivationDecision(
                    node=implementation.node,
                    policy=policy,
                    should_start=True,
                    reason="SHARED: lightweight gateway — start early",
                )
            return ActivationDecision(
                node=implementation.node,
                policy=policy,
                should_start=False,
                reason="SHARED: already running",
            )

        # Unknown policy — be conservative
        logger.warning(
            "Unknown activation policy '%s' for node %s",
            implementation.startup, implementation.node,
        )
        return ActivationDecision(
            node=implementation.node,
            policy=policy,
            should_start=False,
            reason=f"Unknown policy: {implementation.startup}",
        )

    def get_core_nodes(self) -> list[str]:
        """Return node names that should start with the core boot set.

        Reads the device_node_map.yaml and returns all nodes with
        ``startup: always_on`` policy.
        """
        from core.device_node_resolver import get_resolver

        resolver = get_resolver()
        resolver._ensure_loaded()

        core_nodes: list[str] = []
        for m in resolver._mappings:
            impl = m.get("implementation", {})
            startup = impl.get("startup", "")
            if startup == ActivationPolicy.ALWAYS_ON.value:
                core_nodes.append(impl["node"])

        return core_nodes


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_engine_instance: Optional[ActivationPolicyEngine] = None


def get_engine() -> ActivationPolicyEngine:
    """Return the module-level ActivationPolicyEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ActivationPolicyEngine()
    return _engine_instance
