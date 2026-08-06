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

import asyncio  # auto: missing import
import logging
import time
from typing import Any, Callable, Dict, List, Optional

# RUF006: retain fire-and-forget create_task results so the event loop's weak
# reference can't let them be garbage-collected mid-execution.
_BACKGROUND_TASKS: set = set()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
UDM_REGISTRATION_HOOK_SENTINEL = "UDM_REGISTRATION_HOOK::DEVICE_RESOLUTION_EVENT_INGRESS"


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

    # -- 执行器插槽:算出来的决定要有人去执行 ---------------------------------

    def set_activation_executor(self, executor: Optional[Callable[..., Any]]) -> None:
        """登记"真的去把节点拉起来"的那个人。

        为什么是回调而不是直接 import
        ------------------------------
        决策在 ``core/``（本文件 + :mod:`core.activation_policy`），执行在
        ``launcher/``（:class:`launcher.launcher_adapter.LauncherAdapter`，它握着
        ``NodeSystemLauncher``）。``core`` 是底层，不该反过来依赖 ``launcher``
        —— 所以由 ``launcher`` 在启动时把自己注册进来。

        这条线之前**根本不存在**
        ------------------------
        这个 hook 一直被 :meth:`core.unified.device_manager._feed_resolution_plane`
        调用（设备一注册就跑），它老老实实解析出节点、评估出 ``should_start=True``、
        写进审计台账 —— **然后 return**。而 ``LauncherAdapter`` 里有能真正
        ``start_node()`` 的 ``_maybe_start_node``，却没有任何调用方。

        也就是说：会算的那个不会做，会做的那个没人叫。整套「设备插上来就把对应
        节点拉起来」的机制，两半都写好了，中间这根线是空的。

        **插槽只有一个,在 :mod:`core.node_activation_policy`。** 这里是转发。
        起初它长在本类身上,那时只有"设备注册"一个触发时机;后来 LAZY 档要在
        "首次能力请求"时也起节点,若各挂一个插槽就又成了两套并行实现 —— 那正是
        这一轮一直在修的毛病。保留本方法是因为它是这条链的自然入口,调用方不必
        知道插槽搬到哪儿去了。

        Args:
            executor: ``async (node_name, decision, device_type, transport) -> Any``；
                传 ``None`` 取消登记（测试用）。
        """
        from core.node_activation_policy import set_activation_executor

        set_activation_executor(executor)

    async def _execute_activation(
        self,
        node_name: str,
        decision: Any,
        device_type: Optional[str],
        transport: Optional[str],
    ) -> Optional[str]:
        """把决定交给执行器。**失败绝不能影响设备注册本身。**"""
        from core.node_activation_policy import get_activation_executor

        executor = get_activation_executor()
        if executor is None:
            logger.debug("[UDMHook] 没有登记激活执行器，%s 的 should_start 只记账不执行", node_name)
            return None
        try:
            return await executor(
                node_name=node_name,
                decision=decision,
                device_type=device_type,
                transport=transport,
            )
        except Exception as exc:
            # 设备已经写进 UDM 了。拉节点失败是"这台设备暂时没有对应能力"，
            # 不是"这台设备没注册上" —— 不能把前者的失败变成后者。
            logger.warning("[UDMHook] 激活 %s 失败（不影响设备注册）：%s", node_name, exc)
            return None

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
        from core.activation_policy import ActivationPolicyEngine
        from core.device_activation_registry import get_registry as get_act_registry
        from core.device_node_resolver import get_resolver

        t0 = time.perf_counter()

        # Extract fields from UnifiedDevice (duck-typed)
        device_type = self._extract(device, "device_type")
        transport = self._extract(device, "transport")
        capabilities = self._extract_list(device, "capabilities")
        device_id = self._extract(device, "device_id")

        logger.info(
            "[UDMHook] device_id=%s type=%s transport=%s caps=%s source=%s",
            device_id,
            device_type,
            transport,
            capabilities,
            source,
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
                device_id,
                device_type,
                transport,
            )
            return None

        # 决定算出来了就得有人去执行 —— 这一步之前是**空的**：hook 解析出节点、
        # 评估出 should_start=True、写进审计台账，然后直接 return，节点从来没被拉起来过。
        activated: Optional[str] = None
        if decision is not None and decision.should_start:
            activated = await self._execute_activation(
                resolved.implementation.node,
                decision,
                device_type,
                transport,
            )

        result = {
            "device_id": device_id,
            "resolved_node": resolved.implementation.node,
            "node_port": resolved.implementation.port,
            "match_type": resolved.match_type,
            "activation_policy": resolved.implementation.startup,
            # ActivationDecision 的字段是 node / policy / should_start / reason ——
            # **没有** .decision。这里原来写的是 `decision.decision`,对每一个解析
            # 成功的设备都会 AttributeError。而本方法是被 device_manager 以
            # fire-and-forget 任务调起的(create_task 之后没人 await 结果),异常
            # 从不浮出水面 —— 于是这条链对每台真实设备都是当场炸掉,而
            # record_resolution() 在它之前就已经写完了台账:**台账看起来一切正常,
            # 下游却从来没被触发过**。
            # 取值口径与 device_activation_registry 保持一致(start / skip)。
            "decision": ("start" if decision.should_start else "skip") if decision else "unknown",
            "should_start": decision.should_start if decision else False,
            "reason": decision.reason if decision else "",
            # 与 should_start 分开报:前者是"该不该起",后者是"到底起没起"。
            # 合成一个字段就再也分不清「没登记执行器」和「执行器起失败了」。
            "activated": activated,
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
            from core.state_event_bus import StateEventType, subscribe

            def _on_device_event(event_type, payload):
                _bt = asyncio.create_task(self._handle_device_event(payload))
                _BACKGROUND_TASKS.add(_bt)
                _bt.add_done_callback(_BACKGROUND_TASKS.discard)

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
    return await get_hook().on_device_registered(device, source=source, trace_id=trace_id)
