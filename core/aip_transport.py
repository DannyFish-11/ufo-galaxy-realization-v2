"""
core/aip_transport.py — AIP v3 统一传输层
==========================================

所有消息（Mesh协同、NATS任务、设备控制）统一通过此类发送。
适配你的真实 AIP v3 协议 (core/schemas/aip_v3.py)。

对齐点:
- AIPMessage 基类无 transport/source/target 字段
- 用 device_id 标识设备
- aip_version 标记协议版本
- transport 字段在发送时由 AIPTransport 自动注入

支持的传输适配器:
- tailscale_p2p: Tailscale WireGuard P2P（同 tailnet 设备优先，~5ms）
- websocket: WebSocket 点对点（全局兜底路径）
- mqtt: MQTT 发布/订阅
- tcp: TCP 直连（P2P）
- udp: UDP 报文
- ble: Bluetooth LE
- serial: 串口通信

架构:
    Mesh/NATS/App ──► AIPTransport.send()
                          │
                    ┌─────┴─────┐
                    ▼           ▼
              适配器注册表    自动选择/默认fallback
                    │
            transport → adapter
                    │
            ┌───┬───┼───┬───┬───┐
            ▼   ▼   ▼   ▼   ▼   ▼
           WS MQTT TCP UDP BLE SERIAL
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.AIPTransport")

# ───────────────────── 需求感知选路(按消息实际需要,而非一律静态优先级) ─────────────────────
# 小而频、丢一两条无妨的控制/心跳类:低延迟优先,UDP 可以上位。
_LOSS_TOLERANT_TYPES = frozenset(
    {
        "heartbeat",
        "heartbeat_ack",
        "ack",
        "state_event",
        "coord_sync",
    }
)
# 必达的执行/生命周期类:只走有连接语义的可靠传输,UDP 不做候选。
_RELIABLE_TYPES = frozenset(
    {
        "task_assign",
        "task_submit",
        "task_result",
        "task_cancel",
        "cancel_result",
        "goal_execution",
        "goal_result",
        "goal_execution_result",
        "parallel_subtask",
        "device_register",
        "device_unregister",
        "capability_report",
        "capability_query",
        "takeover_request",
        "takeover_response",
        "operator_action_request",
        "operator_action_result",
        "delegated_execution_signal",
        "reconciliation_signal",
        "command_result",
    }
)
# 大载荷阈值:超过后窄带传输(BLE/串口/UDP/CAN/DBus)不做候选(MTU/速率不现实)。
_NARROWBAND = frozenset({"ble", "serial", "udp", "canbus", "dbus"})


def _bulk_threshold_bytes() -> int:
    try:
        return int(os.environ.get("GALAXY_TRANSPORT_BULK_BYTES", "65536") or "65536")
    except ValueError:
        return 65536


class TransportAdapter(ABC):
    """传输适配器抽象基类。所有传输协议必须实现此接口。"""

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """传输类型: websocket, mqtt, tcp, udp, ble, serial"""

    @abstractmethod
    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """发送 AIP v3 消息。返回 {"success": bool, "via": str, ...}"""

    @abstractmethod
    async def is_available(self, target: str) -> bool:
        """目标是否可通过此传输到达。"""

    async def broadcast(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """广播消息（可选实现，默认逐个发送给已知目标）。"""
        return {"success": True, "via": self.transport_type, "broadcast": "not_implemented"}

    async def close(self) -> None:
        """清理资源。"""
        pass


class AIPTransport:
    """AIP v3 统一传输管理器。

    设计原则:
    1. 与 core.schemas.aip_v3 协议对齐 — AIPMessage 无 transport 字段，发送时注入
    2. 自动传输选择 — 根据目标设备可用性和网络状况自动选择最优传输
    3. Mesh/NATS 保持独立 — 不并入 transport，但可通过 AIPTransport 发送消息
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, TransportAdapter] = {}
        self._default_transport: str = "websocket"
        # 传输优先级（用于自动选择）
        # PR-28: tailscale_p2p 排在首位 — 同 tailnet 设备直接走 WireGuard
        self._transport_priority = [
            "tailscale_p2p",  # Tailscale WireGuard P2P（最低延迟）
            "tcp",  # LAN TCP 直连
            "websocket",  # WebSocket 兜底
            "mqtt",  # MQTT 广播/订阅
            "udp",  # UDP 报文
            "ble",  # 蓝牙 LE
            "serial",  # 串口
        ]
        # 链路历史:(transport, target) → 尝试/成功/EWMA 延迟。由 _send_with_fallback
        # 的真实发送结果喂入,反哺后续候选排序(表现差的链路下沉,好的上浮)。
        self._link_stats: Dict[Tuple[str, str], Dict[str, float]] = {}

    # -- 需求感知选路 --------------------------------------------------------

    @staticmethod
    def _message_needs(msg_dict: Dict[str, Any]) -> Dict[str, Any]:
        """从消息本身推导传输需求:必达/容损、载荷大小、优先级。选路"根据实际需要来"
        的依据就是这三样,而不是无论什么消息都按同一张静态优先级表。"""
        mtype = str(msg_dict.get("type", "") or "")
        try:
            size = len(json.dumps(msg_dict, default=str, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            size = 0
        return {
            "reliable": mtype in _RELIABLE_TYPES,
            "loss_tolerant": mtype in _LOSS_TOLERANT_TYPES,
            "bulk": size >= _bulk_threshold_bytes(),
            "priority": str(msg_dict.get("priority", "") or "normal"),
            "size": size,
        }

    def _record_attempt(self, ttype: str, target: str, ok: bool, latency_ms: float) -> None:
        """记一次真实发送结果进链路统计。全程防御,绝不影响发送主流程。"""
        try:
            key = (ttype, target)
            s = self._link_stats.setdefault(key, {"attempts": 0.0, "successes": 0.0, "ewma_latency_ms": 0.0})
            s["attempts"] += 1
            if ok:
                s["successes"] += 1
                prev = s["ewma_latency_ms"]
                s["ewma_latency_ms"] = latency_ms if prev <= 0 else (0.7 * prev + 0.3 * latency_ms)
            if len(self._link_stats) > 2048:  # 有界,防长期运行膨胀
                self._link_stats.pop(next(iter(self._link_stats)))
        except Exception:  # noqa: BLE001
            pass

    def _link_score(self, ttype: str, target: str) -> Optional[float]:
        """链路得分 = 成功率 − 延迟惩罚;样本 <3 返回 None(不评,保持静态位置)。"""
        s = self._link_stats.get((ttype, target))
        if not s or s["attempts"] < 3:
            return None
        success_rate = s["successes"] / s["attempts"]
        lat_pen = min(1.0, (s["ewma_latency_ms"] or 0.0) / 2000.0) * 0.2
        return success_rate - lat_pen

    def _candidate_order(self, target: str, needs: Optional[Dict[str, Any]] = None) -> List[str]:
        """按【消息实际需要】过滤 + 按【链路历史】重排候选传输。

        - bulk 大载荷:剔除窄带(BLE/串口/UDP/CAN/DBus);
        - 必达消息:剔除 UDP;
        - 容损小控制消息:UDP 上提(低开销,丢一条无妨);
        - critical/high 优先级:剔除已知很差(得分<0.34)的链路,除非没得剩;
        - 历史重排:有分按分降序,无分保持静态相对位置(冷启动 = 完全静态,零行为变化);
          GALAXY_TRANSPORT_ADAPTIVE=false 时只做需求过滤、不做历史重排。
        """
        order = list(self._transport_priority)
        if needs:
            if needs.get("bulk"):
                filtered = [t for t in order if t not in _NARROWBAND]
                order = filtered or order  # 全被剔光则放弃过滤,宁可窄带兜底
            elif needs.get("reliable"):
                order = [t for t in order if t != "udp"] or order
            elif needs.get("loss_tolerant") and "udp" in order:
                order.remove("udp")
                idx = order.index("tcp") + 1 if "tcp" in order else 1
                order.insert(idx, "udp")
            if needs.get("priority") in ("critical", "high"):

                def _known_bad(t: str) -> bool:
                    sc = self._link_score(t, target)
                    return sc is not None and sc < 0.34

                kept = [t for t in order if not _known_bad(t)]
                if kept:
                    order = kept
        if os.environ.get("GALAXY_TRANSPORT_ADAPTIVE", "true").lower() == "false":
            return order

        def _key(pair: Tuple[int, str]) -> Tuple[float, int]:
            i, t = pair
            sc = self._link_score(t, target)
            return (-(0.5 if sc is None else sc), i)  # 无分按 0.5 基线,稳定保持静态位

        return [t for _, t in sorted(enumerate(order), key=_key)]

    def transport_stats(self) -> List[Dict[str, Any]]:
        """可观测:导出链路统计(供面板/诊断查看选路反哺依据)。"""
        out: List[Dict[str, Any]] = []
        for (ttype, target), s in self._link_stats.items():
            n = s["attempts"] or 1
            out.append(
                {
                    "transport": ttype,
                    "target": target,
                    "attempts": int(s["attempts"]),
                    "success_rate": round(s["successes"] / n, 4),
                    "ewma_latency_ms": round(s["ewma_latency_ms"], 1),
                    "score": self._link_score(ttype, target),
                }
            )
        out.sort(key=lambda d: (-(d["score"] if d["score"] is not None else 0.5)))
        return out

    # -- 注册管理 ----------------------------------------------------------

    def register_adapter(self, adapter: TransportAdapter) -> None:
        self._adapters[adapter.transport_type] = adapter
        logger.info("Transport adapter registered: %s", adapter.transport_type)

    def unregister_adapter(self, transport_type: str) -> None:
        adapter = self._adapters.pop(transport_type, None)
        if adapter:
            logger.info("Transport adapter unregistered: %s", transport_type)

    def get_adapter(self, transport_type: str) -> Optional[TransportAdapter]:
        return self._adapters.get(transport_type)

    def list_adapters(self) -> List[str]:
        return list(self._adapters.keys())

    # -- 核心发送接口 ------------------------------------------------------

    async def send(
        self,
        message: Any,
        target: str,
        transport: Optional[str] = None,
    ) -> Dict[str, Any]:
        """统一发送入口。

        Args:
            message: AIP v3 消息 — AIPMessage 对象或 dict
            target: 目标 device_id
            transport: 强制指定传输类型（None=自动选择）

        自动处理:
        - 将 AIPMessage 转 dict
        - 自动注入 transport 字段（对齐 AIP v3 协议）
        - transport=None 时按优先级自动选择可用传输
        """
        # 1. 统一转 dict
        msg_dict = self._to_dict(message)

        # 2. 需求感知:从消息本身推导传输需求(必达/容损/大载荷/优先级)
        needs = self._message_needs(msg_dict)

        # 3. 确定传输类型
        ttype = transport or msg_dict.get("_transport", self._default_transport)
        msg_dict["_transport"] = ttype  # 内部标记（不出现在 AIP v3 协议中）

        # 4. 自动选择：如果指定传输不可用，按【需求过滤+历史重排】后的候选 fallback
        adapter = await self._select_adapter(target, preferred=ttype, needs=needs)
        if adapter is None:
            return {
                "success": False,
                "error": f"No transport available for target '{target}'",
            }

        ttype = adapter.transport_type

        # 5. 发送 + PR-28 fallback 链：一个传输失败自动试下一个(结果记入链路统计)
        return await self._send_with_fallback(msg_dict, target, adapter, ttype, needs=needs)

    async def broadcast(
        self,
        message: Any,
        targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """广播消息到多个目标。

        遍历所有可用适配器发送，不依赖 NATS。
        如果提供 targets，逐个发送到目标设备。
        如果没有 targets，调用各适配器的 broadcast 方法。
        """
        msg_dict = self._to_dict(message)
        results = {}

        if targets:
            # 逐个发送到指定目标
            for target in targets:
                result = await self.send(msg_dict, target)
                results[target] = result
        else:
            # 调用每个适配器的广播
            for ttype, adapter in self._adapters.items():
                try:
                    result = await adapter.broadcast(msg_dict)
                    results[ttype] = result
                except Exception as e:
                    logger.warning("Broadcast via '%s' failed: %s", ttype, e)
                    results[ttype] = {"success": False, "error": str(e)}

        return {"success": True, "results": results}

    # -- 自动传输选择 ------------------------------------------------------

    async def probe_best_transport(self, target: str) -> Optional[str]:
        """探测到目标设备的最佳传输。

        按优先级顺序检查各传输的可用性，返回第一个可用的。
        """
        for ttype in self._transport_priority:
            adapter = self._adapters.get(ttype)
            if adapter and await adapter.is_available(target):
                return ttype
        return None

    async def _select_adapter(
        self,
        target: str,
        preferred: str,
        needs: Optional[Dict[str, Any]] = None,
    ) -> Optional[TransportAdapter]:
        """选择最佳适配器。

        1. "auto" 模式：按优先级自动探测
        2. 优先使用 caller 指定的传输
        3. 如果不可用，按优先级 fallback
        4. 如果都不通，返回默认传输适配器

        PR-28: 当 TailscaleP2PAdapter 注册且目标在同 tailnet 时，
        自动提升 tailscale_p2p 为首选，绕过 WebSocket 网关。
        """
        # PR-28: "auto" 模式 — 用 NetworkTopologyRuntime 评估最佳路径
        if preferred == "auto":
            recommended_transport = await self._assess_via_topology(target)
            if recommended_transport and recommended_transport != "auto":
                adapter = self._adapters.get(recommended_transport)
                if adapter and await adapter.is_available(target):
                    logger.debug(
                        "Auto-selected '%s' for target '%s' (via topology)",
                        recommended_transport,
                        target,
                    )
                    return adapter
            # Topology 无法推荐或推荐的不通 — 按【需求过滤+历史重排】后的候选逐个探测
            for ttype in self._candidate_order(target, needs):
                adapter = self._adapters.get(ttype)
                if adapter and await adapter.is_available(target):
                    logger.debug("Auto-selected '%s' for target '%s'", ttype, target)
                    return adapter
            # 没有可用的，fallback 到默认
            default = self._adapters.get(self._default_transport)
            if default:
                return default
            return None

        # PR-28: 指定模式下也做拓扑检查 — 同 tailnet 强制走 P2P
        if preferred not in ("tailscale_p2p",):
            ts_adapter = self._adapters.get("tailscale_p2p")
            if ts_adapter is not None and await ts_adapter.is_available(target):
                logger.debug(
                    "Tailscale P2P available for '%s', overriding preferred '%s'",
                    target,
                    preferred,
                )
                return ts_adapter

        # 尝试首选
        adapter = self._adapters.get(preferred)
        if adapter and await adapter.is_available(target):
            return adapter

        # 按【需求过滤+历史重排】后的候选 fallback
        for ttype in self._candidate_order(target, needs):
            if ttype == preferred:
                continue
            adapter = self._adapters.get(ttype)
            if adapter and await adapter.is_available(target):
                logger.debug("Fallback: '%s' → '%s' for target '%s'", preferred, ttype, target)
                return adapter

        # 最后尝试默认
        default = self._adapters.get(self._default_transport)
        if default:
            logger.debug("Force default '%s' for target '%s'", self._default_transport, target)
            return default

        return None

    async def _assess_via_topology(self, target: str) -> str:
        """Use NetworkTopologyRuntime to assess best path. Returns transport type."""
        try:
            from core.network_topology_runtime import get_network_topology_runtime

            topo = get_network_topology_runtime()
            # Need a source device ID — use my position
            source = topo._my_device_id or "server"
            assessment = topo.assess_path(source, target)
            return assessment.recommended_transport
        except Exception:
            return "auto"

    # -- PR-28: Fallback chain -----------------------------------------------

    async def _send_with_fallback(
        self,
        msg_dict: Dict[str, Any],
        target: str,
        first_adapter: TransportAdapter,
        first_ttype: str,
        needs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send with automatic fallback chain.

        If the first adapter fails, try the next one — 候选链按消息需求过滤 + 链路
        历史重排(不再是一张静态表)。Every attempt's outcome (success/latency) is
        recorded into link stats to feed future ordering.
        """
        attempted: List[str] = []
        errors: List[str] = []

        adapters_to_try = [first_adapter]
        # 需求过滤 + 历史重排后的候选(caller 显式指定的 first_adapter 始终保留在首位)
        for ttype in self._candidate_order(target, needs):
            adapter = self._adapters.get(ttype)
            if adapter and adapter not in adapters_to_try:
                adapters_to_try.append(adapter)

        for adapter in adapters_to_try:
            ttype = adapter.transport_type
            attempted.append(ttype)
            t0 = time.monotonic()
            try:
                result = await adapter.send(msg_dict, target)
                latency_ms = (time.monotonic() - t0) * 1000
                result["_transport_used"] = ttype
                if result.get("success"):
                    self._record_attempt(ttype, target, True, latency_ms)
                    if len(attempted) > 1:
                        logger.info(
                            "PR-28 fallback success: %s → %s for %s (tried: %s)",
                            first_ttype,
                            ttype,
                            target,
                            attempted,
                        )
                    return result
                # Adapter returned success=False — record reason and try next
                self._record_attempt(ttype, target, False, latency_ms)
                errors.append(f"{ttype}: {result.get('error', 'unknown')}")
            except Exception as exc:
                self._record_attempt(ttype, target, False, (time.monotonic() - t0) * 1000)
                errors.append(f"{ttype}: {exc}")
                continue

        # All failed
        logger.warning(
            "PR-28 all transports failed for %s: %s",
            target,
            errors,
        )
        return {
            "success": False,
            "error": f"All transports failed (tried: {attempted}): {' | '.join(errors)}",
            "_attempted": attempted,
        }

    # -- 内部工具 ----------------------------------------------------------

    def _to_dict(self, message: Any) -> Dict[str, Any]:
        """将各种消息格式统一转为 dict。

        支持: AIPMessage (Pydantic), dict, str (JSON)
        """
        if isinstance(message, dict):
            return dict(message)  # 复制避免修改原对象
        if hasattr(message, "model_dump"):
            # Pydantic v2
            return message.model_dump()
        if hasattr(message, "dict"):
            # Pydantic v1
            return message.dict()
        if isinstance(message, str):
            import json

            return json.loads(message)
        raise ValueError(f"Unsupported message type: {type(message)}")

    async def close_all(self) -> None:
        for adapter in self._adapters.values():
            try:
                await adapter.close()
            except Exception as e:
                logger.debug("Error closing adapter '%s': %s", adapter.transport_type, e)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_transport_instance: Optional[AIPTransport] = None


def get_aip_transport() -> AIPTransport:
    global _transport_instance
    if _transport_instance is None:
        _transport_instance = AIPTransport()
    return _transport_instance


def register_transport_adapter(adapter: TransportAdapter) -> None:
    get_aip_transport().register_adapter(adapter)
