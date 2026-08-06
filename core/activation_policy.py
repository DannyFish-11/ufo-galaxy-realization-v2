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
DEVICE_ACTIVATION_POLICY_SENTINEL = "DEVICE_ACTIVATION_POLICY::NODE_STARTUP_DECISION_ENGINE"


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
            implementation.startup,
            implementation.node,
        )
        return ActivationDecision(
            node=implementation.node,
            policy=policy,
            should_start=False,
            reason=f"Unknown policy: {implementation.startup}",
        )

    def get_core_nodes(self) -> list[str]:
        """Return node names that should start with the core boot set.

        这里原来只扫 ``registry/device_node_map.yaml`` 找 ``startup: always_on``
        —— 而那张表里**一条 always_on 都没有**（它记的是设备型节点，全是
        on_demand / lazy / shared）。于是这个方法**恒返回空表**，一直如此，
        不报错也没人发现。

        改为走 :func:`core.node_activation_policy.resolve_activation_policy`：
        它对磁盘上全部 125 个节点定档，判定顺序是「设备表 > skip > core 组 >
        默认 lazy」，设备表仍然优先，所以原来的语义是它的子集。

        惰性 import 是为了避开循环：``node_activation_policy`` 在模块级 import
        本模块的 :class:`ActivationPolicy`。
        """
        try:
            from core.node_activation_policy import activation_policy_coverage
        except Exception as exc:  # pragma: no cover - 退化路径
            logger.warning("节点激活档位表不可用(%s)——核心启动集按空处理", exc)
            return []

        return sorted(
            name
            for name, info in activation_policy_coverage().items()
            if info["policy"] == ActivationPolicy.ALWAYS_ON.value
        )


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
