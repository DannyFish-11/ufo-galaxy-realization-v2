"""
数字孪生引擎 (Digital Twin Engine)
====================================

真正的虚实耦合系统，实现：
- 耦合模式 (Coupled): 实时同步物理设备状态到数字孪生
- 解耦模式 (Decoupled): 纯虚拟推演，不影响物理设备
- 混合模式 (Hybrid): 读取真实状态，但操作先在虚拟侧验证
- 状态漂移检测：检测虚实之间的状态偏差
- 预测性模拟：用历史数据预测未来状态
"""

import asyncio
import logging
import time
import uuid
import math
import json
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger("UFO-Galaxy.DigitalTwin")


# ───────────────────── 数据模型 ─────────────────────

class CouplingMode(Enum):
    """耦合模式"""
    COUPLED = "coupled"        # 实时同步
    DECOUPLED = "decoupled"    # 纯虚拟
    HYBRID = "hybrid"          # 混合模式


class SyncDirection(Enum):
    """同步方向"""
    PHYSICAL_TO_DIGITAL = "p2d"  # 物理 → 数字
    DIGITAL_TO_PHYSICAL = "d2p"  # 数字 → 物理（下发指令）
    BIDIRECTIONAL = "bi"         # 双向同步


class TwinStatus(Enum):
    """孪生体状态"""
    SYNCED = "synced"          # 同步正常
    DRIFTED = "drifted"        # 状态漂移
    OFFLINE = "offline"        # 物理设备离线
    SIMULATING = "simulating"  # 纯模拟中
    ERROR = "error"


@dataclass
class PhysicalState:
    """物理设备状态"""
    device_id: str
    properties: Dict[str, Any]  # 设备属性 (位置、温度、电量等)
    timestamp: float = field(default_factory=time.time)
    source: str = "sensor"     # sensor / manual / estimated


@dataclass
class DigitalState:
    """数字孪生状态"""
    twin_id: str
    device_id: str
    properties: Dict[str, Any]
    predicted_properties: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0    # 状态置信度 (0-1)


@dataclass
class DriftReport:
    """状态漂移报告"""
    twin_id: str
    drifted_properties: Dict[str, Dict]  # property → {physical, digital, delta}
    max_drift: float           # 最大漂移值
    timestamp: float = field(default_factory=time.time)
    severity: str = "low"      # low / medium / high / critical


@dataclass
class SimulationResult:
    """模拟结果"""
    twin_id: str
    action: str
    predicted_state: Dict[str, Any]
    success_probability: float
    risks: List[str] = field(default_factory=list)
    side_effects: List[str] = field(default_factory=list)
    duration_estimate_ms: float = 0
    timestamp: float = field(default_factory=time.time)


# ───────────────────── 数字孪生体 ─────────────────────

class DigitalTwin:
    """
    单个设备的数字孪生体

    维护设备的虚拟副本，支持：
    - 状态同步
    - 状态预测
    - 操作模拟
    - 漂移检测
    """

    def __init__(self, device_id: str, device_type: str,
                 initial_state: Optional[Dict] = None,
                 drift_threshold: float = 0.1):
        self.twin_id = f"twin_{device_id}_{uuid.uuid4().hex[:6]}"
        self.device_id = device_id
        self.device_type = device_type
        self.coupling_mode = CouplingMode.DECOUPLED
        self.status = TwinStatus.SIMULATING

        # 状态
        self.digital_state = DigitalState(
            twin_id=self.twin_id,
            device_id=device_id,
            properties=initial_state or {},
        )
        self.physical_state: Optional[PhysicalState] = None

        # 历史记录
        self.state_history: deque = deque(maxlen=500)
        self.drift_history: List[DriftReport] = []
        self.simulation_log: List[SimulationResult] = []

        # 配置
        self.drift_threshold = drift_threshold  # 漂移告警阈值
        self.sync_interval: float = 1.0  # 同步间隔（秒）
        self._sync_task: Optional[asyncio.Task] = None

        # 物理设备回调
        self._state_fetcher: Optional[Callable[[], Awaitable[Dict]]] = None
        self._command_sender: Optional[Callable[[str, Dict], Awaitable[Dict]]] = None

        # 物理模型（用于预测）
        self._physics_models: Dict[str, Callable] = {}

        logger.info(f"数字孪生创建: {self.twin_id} → 设备 {device_id} ({device_type})")

    # ─────── 耦合控制 ─────────

    async def couple(self,
                     state_fetcher: Callable[[], Awaitable[Dict]],
                     command_sender: Optional[Callable[[str, Dict], Awaitable[Dict]]] = None,
                     mode: CouplingMode = CouplingMode.COUPLED,
                     sync_interval: float = 1.0):
        """
        耦合到物理设备

        Args:
            state_fetcher: 异步函数，返回物理设备当前状态
            command_sender: 异步函数，向物理设备发送命令
            mode: 耦合模式
            sync_interval: 同步间隔（秒）
        """
        self._state_fetcher = state_fetcher
        self._command_sender = command_sender
        self.coupling_mode = mode
        self.sync_interval = sync_interval

        # 首次同步
        await self._sync_from_physical()

        # 启动持续同步（仅耦合模式）
        if mode in (CouplingMode.COUPLED, CouplingMode.HYBRID):
            self._start_sync_loop()

        self.status = TwinStatus.SYNCED
        logger.info(f"孪生体 {self.twin_id} 已耦合到物理设备 (模式: {mode.value})")

    async def decouple(self):
        """
        解耦：断开与物理设备的连接，保留最后状态继续运行
        """
        self._stop_sync_loop()
        self.coupling_mode = CouplingMode.DECOUPLED
        self.status = TwinStatus.SIMULATING
        # 保留当前数字状态用于离线模拟
        logger.info(f"孪生体 {self.twin_id} 已解耦，进入纯模拟模式")

    def switch_mode(self, new_mode: CouplingMode):
        """切换耦合模式"""
        old_mode = self.coupling_mode
        self.coupling_mode = new_mode

        if new_mode == CouplingMode.DECOUPLED:
            self._stop_sync_loop()
            self.status = TwinStatus.SIMULATING
        elif new_mode in (CouplingMode.COUPLED, CouplingMode.HYBRID):
            if self._state_fetcher:
                self._start_sync_loop()
                self.status = TwinStatus.SYNCED

        logger.info(f"孪生体 {self.twin_id} 模式切换: {old_mode.value} → {new_mode.value}")

    # ─────── 状态同步 ─────────

    async def _sync_from_physical(self):
        """从物理设备拉取状态"""
        if not self._state_fetcher:
            return

        try:
            physical_props = await self._state_fetcher()
            self.physical_state = PhysicalState(
                device_id=self.device_id,
                properties=physical_props,
            )

            if self.coupling_mode == CouplingMode.COUPLED:
                # 完全同步：物理状态覆盖数字状态
                self.digital_state.properties = {**physical_props}
                self.digital_state.timestamp = time.time()
                self.digital_state.confidence = 1.0
            elif self.coupling_mode == CouplingMode.HYBRID:
                # 混合同步：更新数字状态但保留预测值
                self.digital_state.predicted_properties = self.digital_state.properties.copy()
                self.digital_state.properties = {**physical_props}
                self.digital_state.timestamp = time.time()

            # 记录历史
            self.state_history.append({
                "physical": physical_props,
                "digital": self.digital_state.properties.copy(),
                "timestamp": time.time(),
            })

            self.status = TwinStatus.SYNCED

        except Exception as e:
            logger.warning(f"同步失败 [{self.twin_id}]: {e}")
            self.status = TwinStatus.OFFLINE
            self.digital_state.confidence *= 0.9  # 降低置信度

    async def push_to_physical(self, command: str, params: Dict) -> Dict:
        """
        从数字侧向物理设备推送命令

        在 HYBRID 模式下，先模拟验证再执行
        """
        if self.coupling_mode == CouplingMode.DECOUPLED:
            # 解耦模式：只在虚拟侧执行
            sim_result = await self.simulate_action(command, params)
            return {"mode": "simulated", "result": sim_result.__dict__}

        if self.coupling_mode == CouplingMode.HYBRID:
            # 混合模式：先模拟验证
            sim = await self.simulate_action(command, params)
            if sim.success_probability < 0.5:
                return {
                    "mode": "blocked",
                    "reason": f"模拟成功率过低: {sim.success_probability:.1%}",
                    "risks": sim.risks,
                }

        # 执行
        if not self._command_sender:
            return {"mode": "error", "reason": "未配置命令发送器"}

        try:
            result = await self._command_sender(command, params)
            # 执行后同步状态
            await self._sync_from_physical()
            return {"mode": "executed", "result": result}
        except Exception as e:
            self.status = TwinStatus.ERROR
            return {"mode": "error", "reason": str(e)}

    def _start_sync_loop(self):
        """启动同步循环"""
        self._stop_sync_loop()
        self._sync_task = asyncio.ensure_future(self._sync_loop())

    def _stop_sync_loop(self):
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            self._sync_task = None

    async def _sync_loop(self):
        """持续同步循环"""
        while True:
            try:
                await asyncio.sleep(self.sync_interval)
                await self._sync_from_physical()

                # 检测漂移
                drift = self.detect_drift()
                if drift and drift.severity in ("high", "critical"):
                    logger.warning(
                        f"[漂移告警] {self.twin_id}: 最大漂移 {drift.max_drift:.4f}, "
                        f"严重性: {drift.severity}"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"同步循环错误 [{self.twin_id}]: {e}")
                await asyncio.sleep(5)

    # ─────── 漂移检测 ─────────

    def detect_drift(self) -> Optional[DriftReport]:
        """检测物理状态与数字状态之间的漂移"""
        if not self.physical_state:
            return None

        drifted = {}
        max_drift = 0.0

        for key, digital_val in self.digital_state.properties.items():
            physical_val = self.physical_state.properties.get(key)
            if physical_val is None:
                continue

            # 计算漂移
            delta = self._compute_delta(digital_val, physical_val)
            if delta is not None and abs(delta) > self.drift_threshold:
                drifted[key] = {
                    "physical": physical_val,
                    "digital": digital_val,
                    "delta": delta,
                }
                max_drift = max(max_drift, abs(delta))

        if not drifted:
            return None

        severity = "low"
        if max_drift > self.drift_threshold * 5:
            severity = "critical"
        elif max_drift > self.drift_threshold * 3:
            severity = "high"
        elif max_drift > self.drift_threshold * 1.5:
            severity = "medium"

        report = DriftReport(
            twin_id=self.twin_id,
            drifted_properties=drifted,
            max_drift=max_drift,
            severity=severity,
        )
        self.drift_history.append(report)
        if severity in ("high", "critical"):
            self.status = TwinStatus.DRIFTED
        return report

    @staticmethod
    def _compute_delta(a: Any, b: Any) -> Optional[float]:
        """计算两个值之间的差异"""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(a - b)
        if isinstance(a, str) and isinstance(b, str):
            return 0.0 if a == b else 1.0
        if isinstance(a, bool) and isinstance(b, bool):
            return 0.0 if a == b else 1.0
        return None

    # ─────── 模拟预测 ─────────

    def register_physics_model(self, action: str,
                               model: Callable[[Dict, Dict], Dict]):
        """注册物理模型用于预测"""
        self._physics_models[action] = model

    async def simulate_action(self, action: str, params: Dict) -> SimulationResult:
        """
        模拟一个操作的结果

        如果有物理模型，使用物理模型预测
        否则使用基于历史的统计预测
        """
        current_state = self.digital_state.properties.copy()
        risks = []
        side_effects = []

        # 使用物理模型
        if action in self._physics_models:
            try:
                predicted = self._physics_models[action](current_state, params)
                success_prob = predicted.pop("_success_probability", 0.9)
                risks = predicted.pop("_risks", [])
                side_effects = predicted.pop("_side_effects", [])
            except Exception as e:
                predicted = current_state
                success_prob = 0.5
                risks.append(f"物理模型异常: {e}")
        else:
            # 统计预测
            predicted = current_state.copy()
            success_prob = self._estimate_success_probability(action)

        # 安全检查
        safety = self._safety_check(action, params, predicted)
        risks.extend(safety.get("risks", []))
        if not safety.get("safe", True):
            success_prob *= 0.3

        result = SimulationResult(
            twin_id=self.twin_id,
            action=action,
            predicted_state=predicted,
            success_probability=success_prob,
            risks=risks,
            side_effects=side_effects,
        )
        self.simulation_log.append(result)
        return result

    def _estimate_success_probability(self, action: str) -> float:
        """基于历史估算成功概率"""
        # 从模拟日志中找相同操作的历史
        similar = [s for s in self.simulation_log if s.action == action]
        if similar:
            avg_prob = sum(s.success_probability for s in similar) / len(similar)
            return avg_prob
        return 0.8  # 默认

    def _safety_check(self, action: str, params: Dict,
                      predicted_state: Dict) -> Dict:
        """安全检查"""
        risks = []
        safe = True

        # 通用安全规则
        if "battery" in predicted_state:
            if predicted_state["battery"] < 10:
                risks.append("电量过低 (<10%)")
                safe = False

        if "temperature" in predicted_state:
            temp = predicted_state["temperature"]
            if temp > 80:
                risks.append(f"温度过高 ({temp}°C)")
                safe = False

        if "altitude" in predicted_state and self.device_type == "drone":
            alt = predicted_state["altitude"]
            if alt > 120:
                risks.append(f"超出法定飞行高度 ({alt}m)")

        return {"safe": safe, "risks": risks}

    async def predict_future_state(self, steps: int = 5,
                                   interval: float = 1.0) -> List[Dict]:
        """基于历史趋势预测未来状态"""
        if len(self.state_history) < 3:
            return [self.digital_state.properties.copy()] * steps

        predictions = []
        current = self.digital_state.properties.copy()

        # 计算每个数值属性的变化趋势
        trends = self._compute_trends()

        for step in range(steps):
            predicted = current.copy()
            for key, trend in trends.items():
                if key in predicted and isinstance(predicted[key], (int, float)):
                    predicted[key] = predicted[key] + trend * (step + 1)
            predictions.append(predicted)

        return predictions

    def _compute_trends(self) -> Dict[str, float]:
        """计算属性变化趋势（简单线性回归）"""
        trends = {}
        history = list(self.state_history)
        if len(history) < 2:
            return trends

        # 取最近的 N 个状态
        recent = history[-min(20, len(history)):]
        first_state = recent[0].get("digital", {})
        last_state = recent[-1].get("digital", {})

        n = len(recent)
        for key in first_state:
            first_val = first_state.get(key)
            last_val = last_state.get(key)
            if isinstance(first_val, (int, float)) and isinstance(last_val, (int, float)):
                trends[key] = (last_val - first_val) / max(n, 1)

        return trends

    # ─────── 状态查询 ─────────

    def get_state(self) -> Dict:
        return {
            "twin_id": self.twin_id,
            "device_id": self.device_id,
            "device_type": self.device_type,
            "coupling_mode": self.coupling_mode.value,
            "status": self.status.value,
            "digital_state": self.digital_state.properties,
            "physical_state": self.physical_state.properties if self.physical_state else None,
            "confidence": self.digital_state.confidence,
            "history_length": len(self.state_history),
            "drift_count": len(self.drift_history),
        }


# ───────────────────── 孪生管理器 ─────────────────────

class DigitalTwinEngine:
    """
    数字孪生引擎

    管理所有设备的数字孪生体，提供：
    - 批量创建和管理孪生体
    - 全局状态视图
    - 场景模拟（同时在多个孪生体上运行）
    """

    def __init__(self):
        self.twins: Dict[str, DigitalTwin] = {}
        self._by_device: Dict[str, str] = {}  # device_id → twin_id
        logger.info("数字孪生引擎已初始化")

    def create_twin(self, device_id: str, device_type: str,
                    initial_state: Optional[Dict] = None,
                    drift_threshold: float = 0.1) -> DigitalTwin:
        """创建数字孪生体"""
        twin = DigitalTwin(
            device_id=device_id,
            device_type=device_type,
            initial_state=initial_state,
            drift_threshold=drift_threshold,
        )
        self.twins[twin.twin_id] = twin
        self._by_device[device_id] = twin.twin_id
        return twin

    def get_twin(self, twin_id: str) -> Optional[DigitalTwin]:
        return self.twins.get(twin_id)

    def get_twin_by_device(self, device_id: str) -> Optional[DigitalTwin]:
        twin_id = self._by_device.get(device_id)
        return self.twins.get(twin_id) if twin_id else None

    async def couple_all(self, state_fetcher_factory: Callable[[str], Callable],
                         mode: CouplingMode = CouplingMode.COUPLED):
        """批量耦合所有孪生体"""
        for twin in self.twins.values():
            fetcher = state_fetcher_factory(twin.device_id)
            await twin.couple(fetcher, mode=mode)

    async def decouple_all(self):
        """批量解耦"""
        for twin in self.twins.values():
            await twin.decouple()

    async def simulate_scenario(self, actions: List[Dict]) -> List[SimulationResult]:
        """
        场景模拟：在多个孪生体上同时模拟一组操作

        Args:
            actions: [{"device_id": ..., "action": ..., "params": {...}}]
        """
        results = []
        for action_spec in actions:
            device_id = action_spec["device_id"]
            twin = self.get_twin_by_device(device_id)
            if not twin:
                results.append(SimulationResult(
                    twin_id="unknown", action=action_spec.get("action", ""),
                    predicted_state={}, success_probability=0,
                    risks=[f"设备 {device_id} 没有对应的数字孪生体"],
                ))
                continue

            result = await twin.simulate_action(
                action_spec["action"],
                action_spec.get("params", {}),
            )
            results.append(result)

        return results

    def get_global_state(self) -> Dict:
        """获取全局孪生状态"""
        return {
            "total_twins": len(self.twins),
            "by_status": self._count_by_status(),
            "by_coupling": self._count_by_coupling(),
            "twins": {
                tid: twin.get_state()
                for tid, twin in self.twins.items()
            },
        }

    def _count_by_status(self) -> Dict[str, int]:
        counts = {}
        for t in self.twins.values():
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        return counts

    def _count_by_coupling(self) -> Dict[str, int]:
        counts = {}
        for t in self.twins.values():
            counts[t.coupling_mode.value] = counts.get(t.coupling_mode.value, 0) + 1
        return counts

    async def shutdown(self):
        """关闭引擎，停止所有同步"""
        for twin in self.twins.values():
            twin._stop_sync_loop()
        logger.info("数字孪生引擎已关闭")


# ───────────────── 预置物理模型 ──────────────────

def drone_flight_model(state: Dict, params: Dict) -> Dict:
    """无人机飞行物理模型"""
    predicted = state.copy()
    target_alt = params.get("altitude", state.get("altitude", 0))
    target_lat = params.get("latitude", state.get("latitude", 0))
    target_lon = params.get("longitude", state.get("longitude", 0))
    speed = params.get("speed", 5.0)  # m/s

    # 位置更新
    predicted["altitude"] = target_alt
    predicted["latitude"] = target_lat
    predicted["longitude"] = target_lon

    # 电量消耗估算
    distance = math.sqrt(
        (target_lat - state.get("latitude", 0)) ** 2 +
        (target_lon - state.get("longitude", 0)) ** 2
    ) * 111000  # 度 → 米（粗略）
    alt_delta = abs(target_alt - state.get("altitude", 0))
    battery_drain = (distance / 1000 + alt_delta / 100) * 2  # 粗略消耗模型
    predicted["battery"] = max(0, state.get("battery", 100) - battery_drain)

    # 风险
    risks = []
    if predicted["battery"] < 15:
        risks.append("电量不足以返航")
    if target_alt > 120:
        risks.append("超出法定飞行高度")

    predicted["_success_probability"] = 0.95 if predicted["battery"] > 20 else 0.4
    predicted["_risks"] = risks
    predicted["_side_effects"] = [f"电量从 {state.get('battery', 100):.0f}% 降至 {predicted['battery']:.0f}%"]
    return predicted


def printer_3d_model(state: Dict, params: Dict) -> Dict:
    """3D 打印机物理模型"""
    predicted = state.copy()
    file_size_mb = params.get("file_size_mb", 10)
    material = params.get("material", "PLA")

    # 打印时间估算
    print_time_min = file_size_mb * 12  # 粗略
    predicted["printing"] = True
    predicted["progress"] = 0
    predicted["estimated_time_min"] = print_time_min

    # 耗材消耗
    filament_used_g = file_size_mb * 5
    predicted["filament_remaining_g"] = max(
        0, state.get("filament_remaining_g", 1000) - filament_used_g
    )

    risks = []
    if predicted["filament_remaining_g"] < filament_used_g:
        risks.append("耗材不足")

    nozzle_temp = state.get("nozzle_temp", 200)
    if material == "ABS" and nozzle_temp < 230:
        risks.append("喷嘴温度过低，ABS 需要 230°C+")

    predicted["_success_probability"] = 0.9 if not risks else 0.5
    predicted["_risks"] = risks
    predicted["_side_effects"] = [f"预计耗时 {print_time_min} 分钟"]
    return predicted


# ───────────────────── 单例 ─────────────────────

_engine_instance: Optional[DigitalTwinEngine] = None


def get_digital_twin_engine() -> DigitalTwinEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = DigitalTwinEngine()
    return _engine_instance
