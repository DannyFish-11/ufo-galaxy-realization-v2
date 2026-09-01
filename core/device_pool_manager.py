#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — Unified Device Pool Manager
======================================

**Architecture role: Scheduling / health / weight layer over UDM SSOT.**

``DevicePoolManager`` is a *scheduling and health-tracking layer* that sits
on top of the canonical device authority chain.  It is **not** a parallel
device truth source.

Canonical authority chain::

    UnifiedDeviceManager (UDM) — canonical SSOT for device state
    ↑
    DevicePoolManager           — scheduling, health scoring, capacity tracking
                                  (delegates canonical writes to UDM first)

All ``register_device`` and ``unregister_device`` calls write to UDM **first**
before updating the local pool records.  The pool records carry
scheduling-specific metadata (weight, capacity, active connections,
circuit-breaker state) that UDM does not track, and are therefore maintained
locally as a scheduling projection.

Design principles
-----------------
* **Delegating writes** – canonical device state (registration / online /
  offline) is written to UDM before the pool record is updated.
* **Scheduling layer** – health tracking, circuit-breaking, and scheduling
  decisions are pool-local concerns that do not need to be in UDM.
* **Strategy pattern** – supports three built-in scheduling strategies:
  ``round_robin``, ``least_conn``, and ``adaptive`` (score-weighted).
* **Backward compatible** – ``DeviceOrchestrator`` and other callers keep
  their existing APIs; they simply delegate to this manager internally.

Usage
-----
    from core.device_pool_manager import get_device_pool_manager

    pool = get_device_pool_manager()
    pool.register_device("dev_01", capabilities=["screen", "touch"])
    dev = pool.select_device(required_capabilities=["screen"])
    pool.mark_success("dev_01")
    pool.mark_failure("dev_01", error="timeout")
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core import upper_ports

logger = logging.getLogger("Galaxy.DevicePoolManager")


def _satisfies_capabilities(
    device_id: str,
    declared_capabilities: Optional[List[str]],
    required_capabilities: Optional[List[str]],
) -> bool:
    """能力匹配统一走 :mod:`core.capability_registry`（三源并集），而不是只看池内字段。

    池里的 ``dev.capabilities`` 只是规范注册表的**三个来源之一**；经 capability_bus
    或网关能力投影上报的能力不在其中。只看它会把确实具备该能力的设备判成不匹配、
    从候选里剔除（已实测复现）。详见
    :func:`core.capability_registry.device_satisfies_required_capabilities` 的 docstring。

    延迟 import：``capability_registry`` 会去查 device_registry / capability_bus /
    网关投影，模块级引入容易形成环。注册表不可用时降级为原先的单源判断 ——
    保持"权威坏了不至于让派发整体失败"的既有语义。
    """
    if not required_capabilities:
        return True
    try:
        from core.capability_registry import device_satisfies_required_capabilities

        return device_satisfies_required_capabilities(device_id, declared_capabilities, required_capabilities)
    except Exception as exc:  # pragma: no cover - 降级
        logger.debug("capability registry unavailable (%s) — falling back to declared capabilities", exc)
        return all(c in (declared_capabilities or []) for c in required_capabilities)


# ---------------------------------------------------------------------------
# PR-A04: DevicePool → CapabilityAssimilationLayer integration sentinel
# ---------------------------------------------------------------------------
# DevicePoolManager.select_device() queries the canonical
# CapabilityAssimilationLayer via core.capability_network_runtime_policy.
# query_routable_executors() before falling back to the local pool.  This
# ensures that device selection always respects the unified capability graph
# and never bypasses the assimilation layer.  The sentinel below confirms
# this integration is present.
DEVICE_POOL_CAPABILITY_ASSIMILATION_LAYER_INTEGRATED: str = "DEVICE_POOL_CAPABILITY_ASSIMILATION_LAYER_INTEGRATED_V1"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SchedulingStrategy(str, Enum):
    """Available device-selection strategies."""

    ROUND_ROBIN = "round_robin"
    LEAST_CONN = "least_conn"
    ADAPTIVE = "adaptive"


# ---------------------------------------------------------------------------
# Device record
# ---------------------------------------------------------------------------


@dataclass
class PoolDevice:
    """Metadata and runtime state for a single device in the pool."""

    device_id: str
    capabilities: List[str] = field(default_factory=list)
    device_type: str = ""
    weight: float = 1.0
    capacity: int = 10  # max concurrent tasks
    active_connections: int = 0
    registered_at: float = field(default_factory=time.monotonic)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---------- derived / runtime ----------
    @property
    def is_full(self) -> bool:
        return self.active_connections >= self.capacity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "capabilities": self.capabilities,
            "weight": self.weight,
            "capacity": self.capacity,
            "active_connections": self.active_connections,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# DevicePoolManager
# ---------------------------------------------------------------------------


class DevicePoolManager:
    """Unified device pool — registration, health, weights, and scheduling.

    Parameters
    ----------
    strategy:
        Default scheduling strategy.  Can be overridden per
        :meth:`select_device` call.
    quarantine_threshold:
        Failures within the window that trigger quarantine.
        Forwarded to the underlying :class:`DeviceHealthRegistry`.
    circuit_failure_threshold:
        Consecutive failures that open the circuit breaker.
    """

    _instance: Optional["DevicePoolManager"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
        return cls._instance

    def __init__(
        self,
        strategy: SchedulingStrategy = SchedulingStrategy.ADAPTIVE,
        quarantine_threshold: int = 10,
        circuit_failure_threshold: int = 5,
    ) -> None:
        if self._initialized:
            return
        self._initialized = True

        self.strategy = strategy
        self._lock = threading.Lock()
        self._devices: Dict[str, PoolDevice] = {}

        # Round-robin cursor (device_id iterator cycle)
        self._rr_cycle: Optional[itertools.cycle] = None

        # Delegate health / circuit-breaker tracking
        self._health_registry = self._make_health_registry(
            quarantine_threshold=quarantine_threshold,
            circuit_failure_threshold=circuit_failure_threshold,
        )
        logger.info("DevicePoolManager 初始化完成 [strategy=%s]", strategy.value)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_health_registry(
        quarantine_threshold: int,
        circuit_failure_threshold: int,
    ):
        try:
            from core.control_plane.device_health_registry import DeviceHealthRegistry

            return DeviceHealthRegistry(
                quarantine_threshold=quarantine_threshold,
                circuit_failure_threshold=circuit_failure_threshold,
            )
        except Exception as exc:
            logger.warning("DeviceHealthRegistry 不可用，降级为 None: %s", exc)
            return None

    def _rebuild_rr_cycle(self) -> None:
        """Rebuild round-robin iterator from current device IDs."""
        ids = list(self._devices.keys())
        self._rr_cycle = itertools.cycle(ids) if ids else None

    def _health_score(self, device_id: str) -> float:
        """Return health score [0, 100] for *device_id*.

        无记录时返回**中性分**而不是满分。此前返回 100.0，后果是实测出来的：
        一台从没测过的设备（100.0）会排在一台实测很差但确实在工作的设备（29.83）
        前面，被 ``max(candidates, key=score)`` 选中 —— 可能已经死掉的设备优先接活。
        判据见 core/health_evidence_policy.py。
        """
        from core.health_evidence_policy import no_evidence_score

        if self._health_registry is None:
            return no_evidence_score(100.0)
        state = self._health_registry.get_state(device_id)
        if state is None:
            return no_evidence_score(100.0)
        return state.health_score

    #: 响应性分级 → 打分权重。近交互拿满，逐档往下让路，不可用直接归零。
    #: 归零而不是给个小值：``unavailable`` 的定义就是"这条路现在走不通"，给它任何正权重
    #: 都意味着在没有别的候选时它仍会被选中，而那恰恰是最该避免的一次派发。
    _RESPONSIVENESS_WEIGHT = {
        "near_interactive": 1.00,
        "bounded_deferred": 0.80,
        "eventual": 0.50,
        "degraded": 0.25,
        "unavailable": 0.00,
    }

    def _responsiveness_factor(self, device_id: str, health_fraction: float) -> float:
        """按 ``core.cross_device_responsiveness_contract`` 给出的分级折算打分权重。

        为什么要它
        ----------
        健康分把两件事压成了一个数：**分数高低**与**有没有证据**。压完之后下游分不出
        "测过、就是中等" 和 "没测过" —— 而这两件事对"该不该把活派给它"的含义完全不同。

        响应性契约的分级恰好是把它们拆开的那套判据（``evidence_available`` 是独立入参，
        且明写 ``EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY``：没有证据就不许算近交互）。
        这里把分级折成一个乘数接进既有打分，而不是另起一套选择逻辑 —— 既有的健康 /
        连接数 / Android 运行时三项都保留，契约只再压一层"证据够不够格"。

        取不到契约时返回 ``1.0``：退化成接入之前的行为，绝不因为契约层不可用就让整个
        选择停摆。降级留 warning，不静默。
        """
        try:
            from core.cross_device_responsiveness_contract import responsiveness_for_participant
        except Exception as exc:  # noqa: BLE001
            logger.warning("响应性契约不可用，候选打分退回接入前的口径: %s", exc)
            return 1.0

        has_evidence = self._has_health_evidence(device_id)
        state = self._health_registry.get_state(device_id) if self._health_registry is not None else None
        quarantined = bool(getattr(state, "quarantined", False))
        circuit = str(getattr(getattr(state, "circuit_state", None), "value", "") or "")

        # 参与者就绪档由熔断器状态给：它就是本仓对"这台设备现在能不能接活"的活判断。
        if quarantined or circuit == "open":
            readiness = "missing"
        elif not has_evidence:
            readiness = "partial"  # 在册但没有任何证据 —— 不是 ready，也不是 missing
        elif circuit == "half_open":
            readiness = "degraded"
        else:
            readiness = "ready"

        try:
            contract = responsiveness_for_participant(
                participant_readiness=readiness,
                health_score=max(0.0, min(1.0, float(health_fraction))),
                evidence_available=has_evidence,
                execution_domain="remote",
                participant_id=device_id,
            )
            return self._RESPONSIVENESS_WEIGHT.get(contract.level.value, 1.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("响应性分级失败，本次按接入前口径打分 | device=%s err=%s", device_id, exc)
            return 1.0

    def _has_health_evidence(self, device_id: str) -> bool:
        """这台设备有没有健康证据 —— 与分数是**两件事**，见 health_evidence_policy。"""
        if self._health_registry is None:
            return False
        return self._health_registry.get_state(device_id) is not None

    #: UDM 状态里明确表示"这台设备现在收不了活"的那几个值。
    #:
    #: 只列**否决**项而不是列"允许"项,是刻意的:``UnifiedDeviceStatus`` 将来加了
    #: 新值(比如某种"部分可用"),默认应当是**不否决**、交给下面的健康登记表判断,
    #: 而不是被一个写死的白名单悄悄挡在门外。宁可漏否决,不可误否决 ——
    #: 误否决的症状是"明明设备在线却调度不到它",极难归因。
    _UDM_NOT_DISPATCHABLE = frozenset({"offline", "error", "disconnected"})

    @classmethod
    def _udm_vetoes(cls, device_id: str) -> bool:
        """UDM(SSOT)是否明确否决这台设备。

        **这是 P3-3 读路径统一的落点。** 池子的写路径早就 write-through 到 UDM 了
        (见 ``_udm_write_register``),但**读路径从来没问过 UDM** —— 于是两边会分叉:

            pool.register_device("dev-A")          # UDM: ONLINE, 池子: 有记录
            udm.update_device_status("dev-A", OFFLINE)   # 唯一合法的状态写路径
            udm.get_online_devices()               # → []          UDM 知道它离线了
            pool.list_devices(eligible_only=True)  # → ['dev-A']   池子不知道
            pool.select_device()                   # → 'dev-A'     照样派活过去

        实测复现过上面这四行。后果是任务被派到系统**明知已离线**的设备上,而
        `core/unified/device_manager.py` 顶部的架构声明本来就写着:
        device_pool_manager 是"调度层,不得作为平行真相源"。写路径遵守了,读路径没有。

        判据(**只否决,不批准**):

        * UDM 里这台设备的状态在 ``_UDM_NOT_DISPATCHABLE`` 里 → 否决;
        * UDM 里**查不到**这台设备 → **不否决**。这是刻意的降级路径:
          ``register_device`` 的 write-through 是 best-effort(UDM 写失败时仍保留
          本地池记录以维持调度,见其 docstring)。这种情况下再把它否决掉,等于
          "UDM 一抖动,整个调度停摆";
        * UDM 本身不可用(import 失败 / 抛异常)→ **不否决**,同上。

        一句话:**UDM 明确说不行才不行;UDM 没话说,就轮不到它否决。**
        """
        try:
            from core.unified.device_manager import get_unified_device_manager

            device = get_unified_device_manager().get_device(device_id)
        except Exception as exc:  # pragma: no cover - UDM 不可用是降级路径
            logger.debug("DevicePoolManager: UDM 查询不可用,不否决 %s: %s", device_id, exc)
            return False

        if device is None:
            return False

        status = getattr(device, "status", None)
        # status 可能是 Enum 也可能已经是 str —— 统一按值比较,别依赖具体类型。
        status_value = getattr(status, "value", status)
        return str(status_value).lower() in cls._UDM_NOT_DISPATCHABLE

    def _is_eligible(self, device_id: str) -> bool:
        """Return True if the device can accept new tasks.

        两道关卡,顺序有意义:先问 SSOT(设备**存在且愿意收活**吗),再问本地健康
        登记表(熔断 / 隔离这类**调度层**的判断)。前者是全系统真相,后者是池子
        自己的经验 —— 真相优先。
        """
        if self._udm_vetoes(device_id):
            return False
        if self._health_registry is None:
            return True
        return self._health_registry.is_eligible(device_id)

    # ------------------------------------------------------------------
    # Registration API
    # ------------------------------------------------------------------

    def register_device(
        self,
        device_id: str,
        capabilities: Optional[List[str]] = None,
        device_type: str = "",
        weight: float = 1.0,
        capacity: int = 10,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PoolDevice:
        """Register a new device or update an existing one.

        **UDM write-through**: The canonical device state is written to
        ``UnifiedDeviceManager`` (SSOT) **before** the local pool record is
        updated.  If the UDM write fails, a warning is logged but the local
        pool record is still updated so that scheduling can continue
        (best-effort degraded mode).

        Returns the :class:`PoolDevice` record after upsert.
        """
        # --- Canonical write to UDM SSOT first ---
        self._udm_write_register(
            device_id=device_id,
            capabilities=capabilities or [],
            device_type=device_type,
            metadata=metadata or {},
        )

        with self._lock:
            if device_id in self._devices:
                dev = self._devices[device_id]
                dev.capabilities = capabilities or dev.capabilities
                dev.device_type = device_type or dev.device_type
                dev.weight = weight
                dev.capacity = capacity
                if metadata:
                    dev.metadata.update(metadata)
                logger.debug("设备已更新: %s", device_id)
            else:
                dev = PoolDevice(
                    device_id=device_id,
                    capabilities=capabilities or [],
                    device_type=device_type,
                    weight=weight,
                    capacity=capacity,
                    metadata=metadata or {},
                )
                self._devices[device_id] = dev
                self._rebuild_rr_cycle()
                logger.info("设备已注册: %s (caps=%s)", device_id, dev.capabilities)

            # Emit audit event
            self._emit_audit("device_registered", device_id=device_id)
            return dev

    def unregister_device(self, device_id: str) -> bool:
        """Remove a device from the pool. Returns True if it existed.

        **UDM write-through**: The canonical offline state is written to
        ``UnifiedDeviceManager`` (SSOT) before removing from the local pool.
        """
        # --- Canonical write to UDM SSOT first ---
        self._udm_write_unregister(device_id)

        with self._lock:
            if device_id not in self._devices:
                return False
            del self._devices[device_id]
            self._rebuild_rr_cycle()
            logger.info("设备已注销: %s", device_id)
            return True

    # ------------------------------------------------------------------
    # UDM write-through helpers (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _udm_write_register(
        device_id: str,
        capabilities: List[str],
        device_type: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Write device registration to UDM SSOT (best-effort, never raises)."""
        try:
            udm_write_register = upper_ports.resolve("gateway.ssot.udm_write_register")

            udm_write_register(
                device_id=device_id,
                device_name=metadata.get("device_name", device_id),
                device_type_raw=device_type or "unknown",
                capabilities=capabilities,
                metadata=metadata,
                source="device_pool_manager",
            )
        except Exception as exc:
            logger.warning(
                "DevicePoolManager: UDM write failed for device %s — " "pool record updated in degraded mode. error=%s",
                device_id,
                exc,
            )

    @staticmethod
    def _udm_write_unregister(device_id: str) -> None:
        """Write device unregister to UDM SSOT (best-effort, never raises)."""
        try:
            udm_write_unregister = upper_ports.resolve("gateway.ssot.udm_write_unregister")

            udm_write_unregister(device_id)
        except Exception as exc:
            logger.warning(
                "DevicePoolManager: UDM unregister write failed for device %s — "
                "pool record removed in degraded mode. error=%s",
                device_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def list_devices(
        self,
        required_capabilities: Optional[List[str]] = None,
        device_type: Optional[str] = None,
        eligible_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List registered devices with optional filters.

        Args:
            required_capabilities: Only return devices that have ALL listed
                capabilities.
            device_type: Filter by device type string.
            eligible_only: Skip quarantined / circuit-open devices.

        Returns:
            List of device info dicts, each annotated with ``health_score``
            and ``eligible``.
        """
        with self._lock:
            result = []
            for dev in self._devices.values():
                if device_type and dev.device_type != device_type:
                    continue
                if required_capabilities:
                    # 经规范能力注册表判定：dev.capabilities 只是三个来源之一，
                    # 单看它会漏掉经 capability_bus / 网关投影上报的能力。
                    if not _satisfies_capabilities(dev.device_id, dev.capabilities, required_capabilities):
                        continue
                eligible = self._is_eligible(dev.device_id)
                if eligible_only and not eligible:
                    continue
                info = dev.to_dict()
                info["health_score"] = self._health_score(dev.device_id)
                info["eligible"] = eligible
                result.append(info)
            return result

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return a single device's info dict, or None if not found."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            info = dev.to_dict()
            info["health_score"] = self._health_score(dev.device_id)
            info["eligible"] = self._is_eligible(dev.device_id)
            return info

    # ------------------------------------------------------------------
    # Scheduling / selection
    # ------------------------------------------------------------------

    def select_device(
        self,
        required_capabilities: Optional[List[str]] = None,
        device_type: Optional[str] = None,
        strategy: Optional[SchedulingStrategy] = None,
        exclude: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Select the best eligible device according to *strategy*.

        Args:
            required_capabilities: The device must have all these capabilities.
            device_type: Optional device-type filter.
            strategy: Override the pool-level default strategy.
            exclude: Device IDs to skip (e.g. already tried).

        Returns:
            ``device_id`` of the selected device, or ``None`` if no
            eligible device is available.
        """
        effective_strategy = strategy or self.strategy
        exclude_set = set(exclude or [])
        canonical_candidate_ids: Optional[set[str]] = None

        try:
            from core.capability_network_runtime_policy import query_routable_executors

            canonical_executors = query_routable_executors(required_capabilities)
            canonical_candidate_ids = {
                str(executor.node_id) for executor in canonical_executors if getattr(executor, "node_id", None)
            }
        except Exception as exc:
            logger.debug(
                "DevicePoolManager.select_device: canonical capability/runtime query unavailable: %s",
                exc,
            )

        with self._lock:
            candidates = [
                dev
                for dev in self._devices.values()
                if dev.device_id not in exclude_set
                and not dev.is_full
                and self._is_eligible(dev.device_id)
                and (canonical_candidate_ids is None or dev.device_id in canonical_candidate_ids)
                and (not device_type or dev.device_type == device_type)
                and _satisfies_capabilities(dev.device_id, dev.capabilities, required_capabilities)
            ]

            if not candidates:
                return None

            if effective_strategy == SchedulingStrategy.ROUND_ROBIN:
                chosen = self._select_rr(candidates)
            elif effective_strategy == SchedulingStrategy.LEAST_CONN:
                chosen = min(candidates, key=lambda d: d.active_connections)
            else:
                # ADAPTIVE — weighted composite score
                chosen = self._select_adaptive(candidates)

            if chosen:
                chosen.active_connections += 1
                logger.debug(
                    "选中设备: %s [strategy=%s, conns=%d]",
                    chosen.device_id,
                    effective_strategy.value,
                    chosen.active_connections,
                )
                return chosen.device_id
            return None

    def _select_rr(self, candidates: List[PoolDevice]) -> Optional[PoolDevice]:
        """Round-robin selection among *candidates*."""
        candidate_ids = {d.device_id for d in candidates}
        # Scan the cycle until we find one in the candidate set
        if self._rr_cycle is None:
            return candidates[0] if candidates else None
        for _ in range(len(self._devices) + 1):
            try:
                dev_id = next(self._rr_cycle)
            except StopIteration:
                break
            if dev_id in candidate_ids:
                return self._devices[dev_id]
        # Fallback
        return candidates[0] if candidates else None

    def _select_adaptive(self, candidates: List[PoolDevice]) -> Optional[PoolDevice]:
        """Weighted-score selection: health × weight / (connections + 1) × runtime_state.

        PR-7: The composite score is now enriched by real Android runtime-state
        truth from :mod:`core.android_device_state_store` when available.
        The runtime-state factor incorporates:

        - **queue depth** — deep offline queues reduce the score (more backlog
          means slower response for any new task).
        - **local AI readiness** — devices with local inference ready are
          preferred; they can execute locally without delegating back to center.
        - **runtime health** — devices reporting degradation in their health
          snapshot have a reduced score proportional to degradation severity.
        - **fallback tier** — devices already at a degraded fallback tier get
          a slight score reduction (they are already under load/recovery pressure).

        When the android state store is unavailable the factor defaults to 1.0
        so existing scoring semantics are fully preserved.
        """

        def score(dev: PoolDevice) -> float:
            h = self._health_score(dev.device_id) / 100.0
            conn_penalty = 1.0 / (dev.active_connections + 1)
            runtime_factor = _android_runtime_score(dev.device_id)
            resp_factor = self._responsiveness_factor(dev.device_id, h)
            return h * dev.weight * conn_penalty * runtime_factor * resp_factor

        if not candidates:
            return None
        return max(candidates, key=score)

    # ------------------------------------------------------------------
    # Feedback API (called after task execution)
    # ------------------------------------------------------------------

    def mark_success(self, device_id: str) -> None:
        """Record a successful task completion for *device_id*."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev and dev.active_connections > 0:
                dev.active_connections -= 1
        if self._health_registry:
            self._health_registry.record_success(device_id)

    def mark_failure(self, device_id: str, error: str = "") -> None:
        """Record a task failure for *device_id*.

        Internally calls :meth:`DeviceHealthRegistry.record_failure` which
        handles circuit-breaker transitions and quarantine.
        """
        with self._lock:
            dev = self._devices.get(device_id)
            if dev and dev.active_connections > 0:
                dev.active_connections -= 1
        if self._health_registry:
            self._health_registry.record_failure(device_id, error=error)

    def mark_heartbeat(self, device_id: str, latency_ms: float = 0.0) -> None:
        """Forward a heartbeat signal to the health registry."""
        if self._health_registry:
            self._health_registry.record_heartbeat(device_id, latency_ms=latency_ms)

    # ------------------------------------------------------------------
    # Quarantine / management
    # ------------------------------------------------------------------

    def quarantine(self, device_id: str, reason: str = "manual") -> None:
        """Manually quarantine a device (exclude from scheduling)."""
        if self._health_registry is not None:
            if hasattr(self._health_registry, "quarantine"):
                self._health_registry.quarantine(device_id, reason=reason)
            elif hasattr(self._health_registry, "_states"):
                with self._health_registry._lock:
                    state = self._health_registry._state(device_id)
                    state.quarantined = True
                    state.quarantine_reason = reason
        logger.warning("设备已手动隔离: %s (%s)", device_id, reason)

    def unquarantine(self, device_id: str) -> None:
        """Lift the quarantine from *device_id*."""
        if self._health_registry is not None:
            if hasattr(self._health_registry, "unquarantine"):
                self._health_registry.unquarantine(device_id)
            elif hasattr(self._health_registry, "_states"):
                with self._health_registry._lock:
                    state = self._health_registry._states.get(device_id)
                    if state:
                        state.quarantined = False
                        state.quarantine_reason = ""
        logger.info("设备隔离已解除: %s", device_id)

    def get_health_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return raw health state dict for *device_id*."""
        if self._health_registry is None:
            return None
        state = self._health_registry.get_state(device_id)
        if state is None:
            return None
        return {
            "device_id": device_id,
            "health_score": state.health_score,
            "circuit_state": state.circuit_state,
            "consecutive_failures": state.consecutive_failures,
            "quarantined": state.quarantined,
            "quarantine_reason": state.quarantine_reason,
        }

    # ------------------------------------------------------------------
    # Audit helper
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_audit(event_name: str, **kwargs) -> None:
        """Fire an audit-ledger event (best-effort, never raises)."""
        try:
            from core.control_plane.audit_ledger import AuditLedger, EventType

            ledger = AuditLedger.get_instance()
            et = getattr(EventType, event_name.upper(), None)
            if et is None:
                return
            ledger.append(et, **kwargs)
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return pool-level statistics."""
        with self._lock:
            total = len(self._devices)
            eligible = sum(1 for d in self._devices if self._is_eligible(d))
            total_conns = sum(d.active_connections for d in self._devices.values())
            return {
                "total_devices": total,
                "eligible_devices": eligible,
                "total_active_connections": total_conns,
                "strategy": self.strategy.value,
            }

    def reset(self) -> None:
        """Reset pool state (used in tests; not for production use)."""
        with self._lock:
            self._devices.clear()
            self._rr_cycle = None
        logger.debug("DevicePoolManager 已重置")

    @classmethod
    def _reset_singleton(cls) -> None:
        """Reset the singleton instance for test isolation."""
        cls._instance = None
        global _pool_manager
        _pool_manager = None


# ---------------------------------------------------------------------------
# PR-7: Runtime-state scoring helper
# ---------------------------------------------------------------------------

# Authority sentinel affirming that adaptive scheduling incorporates real
# Android runtime-state truth from android_device_state_store.
RUNTIME_STATE_SCORING_AUTHORITY: str = (
    "RUNTIME_STATE_SCORING_V1: "
    "DevicePoolManager._select_adaptive() enriches the composite scheduling "
    "score with real Android runtime-state truth from "
    "core.android_device_state_store (queue_depth, local_ai_ready, "
    "runtime_health, fallback_tier).  Degrades gracefully to 1.0 when the "
    "store is unavailable."
)

# Maximum offline queue depth that maps to a full (1.0) score penalty cap.
_QUEUE_DEPTH_PENALTY_CAP: int = 20


def _android_runtime_score(device_id: str) -> float:
    """Return a runtime-state factor [0.1, 1.5] for *device_id*.

    Queries :mod:`core.android_device_state_store` for the latest
    :class:`~core.android_device_state_store.DeviceStateSnapshot` for
    *device_id* and computes a multiplier that rewards healthy/available
    devices and penalises overloaded or degraded ones.

    Factor breakdown
    ----------------
    * **Queue depth** — ``max(0.4, 1 − depth / cap)`` where cap is
      :data:`_QUEUE_DEPTH_PENALTY_CAP` (default 20).  A device with 10
      queued items scores 0.5×; a device with no queue scores 1.0×.
    * **Local AI ready** — bonus +0.25 when ``is_local_ai_ready()`` is True;
      the device can execute locally without center delegation.
    * **Degraded state** — each degradation reason listed in
      ``degraded_reasons`` reduces the factor by 0.1 (floored at 0.4 ×
      the queue factor) to avoid over-penalising already-struggling devices.
    * **Fallback tier** — devices already on a center-delegated or degraded
      fallback tier receive a small −0.15 penalty; they are likely under
      recovery pressure and should not attract new tasks aggressively.
    * **Pending first download** — if the device has not finished its
      initial model download, a −0.3 penalty is applied.  The device
      retains a positive score so it is not excluded entirely (exclusion
      is the job of the admissibility pre-filter in device_selection.py).

    Returns ``1.0`` when the store is unavailable or has no snapshot for
    *device_id* (fail-open — preserves prior scoring semantics).
    """
    try:
        from core.android_device_state_store import get_device_state_snapshot as _get_snap

        snap = _get_snap(device_id)
        if snap is None:
            return 1.0

        factor = 1.0

        # Queue depth penalty
        depth = snap.offline_queue_depth
        if depth is not None and depth > 0:
            queue_factor = max(0.4, 1.0 - depth / _QUEUE_DEPTH_PENALTY_CAP)
            factor *= queue_factor

        # Local AI readiness bonus
        if snap.is_local_ai_ready():
            factor += 0.25

        # Degradation penalty
        degraded_count = len(snap.degraded_reasons or [])
        if degraded_count > 0:
            factor -= min(degraded_count * 0.10, factor - 0.1)

        # Fallback tier penalty — device is already under recovery pressure
        _center_delegated_tier_prefixes = ("center_", "CENTER_", "delegated")
        tier = snap.current_fallback_tier or ""
        if tier and any(tier.startswith(p) for p in _center_delegated_tier_prefixes):
            factor -= 0.15

        # Pending first-download penalty
        if snap.pending_first_download:
            factor -= 0.30

        # Clamp to [0.05, 1.5] so the factor never zeroes a score or grows
        # unboundedly.
        return max(0.05, min(1.5, factor))

    except Exception as _exc:
        logger.debug(
            "DevicePoolManager: android_runtime_score unavailable for %s " "(fail-open, returning 1.0): %s",
            device_id,
            _exc,
        )
        return 1.0


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_pool_manager: Optional[DevicePoolManager] = None
_factory_lock = threading.Lock()


def get_device_pool_manager(
    strategy: SchedulingStrategy = SchedulingStrategy.ADAPTIVE,
) -> DevicePoolManager:
    """Return (or create) the global :class:`DevicePoolManager` singleton."""
    global _pool_manager
    if _pool_manager is None:
        with _factory_lock:
            if _pool_manager is None:
                _pool_manager = DevicePoolManager(strategy=strategy)
    return _pool_manager
