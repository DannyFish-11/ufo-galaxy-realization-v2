"""
HybridExecutionArbiter — 混合执行仲裁器
========================================

Phase 3 Matrix OS 核心组件。

三级降级执行链:
  Level 1: A2A (Agent-to-Agent) — 通过 API/MCP 直接调用目标应用/服务
  Level 2: GUI Automation      — 通过 UI 自动化 (点击/滑动/输入) 操控界面
  Level 3: VLM (Vision-Language Model) — 截图 + VLM 理解 + 坐标推理

每个执行请求按顺序尝试三级:
  - A2A 成功 → 直接返回结果 (最快, 最准)
  - A2A 失败 → 降级到 GUI (通过 accessibility/adb)
  - GUI 失败 → 降级到 VLM (截图 + 视觉理解 + 盲操作)

策略选择器:
  - 根据目标应用的能力声明决定首选执行级别
  - 如果已知某应用有 A2A API, 直接跳到 L1
  - 如果已知某应用只有 GUI, 跳过 L1
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Galaxy.HybridExecutor")


class ExecutionLevel(str, Enum):
    A2A = "a2a"          # Agent-to-Agent (API/MCP direct call)
    GUI = "gui"          # GUI Automation (accessibility, ADB)
    VLM = "vlm"          # Vision-Language Model (screenshot + reasoning)


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"    # 低级别成功
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class ExecutionAttempt:
    """单次执行尝试记录"""
    level: ExecutionLevel
    status: ExecutionStatus
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    latency_ms: float = 0


@dataclass
class HybridResult:
    """混合执行最终结果"""
    request_id: str
    success: bool
    final_level: ExecutionLevel
    result: Dict[str, Any] = field(default_factory=dict)
    attempts: List[Dict] = field(default_factory=list)
    total_latency_ms: float = 0

    def to_dict(self) -> Dict:
        return {
            "request_id": self.request_id,
            "success": self.success,
            "final_level": self.final_level.value,
            "result": self.result,
            "attempts": self.attempts,
            "total_latency_ms": self.total_latency_ms,
        }


# ============================================================================
# 能力注册表 — 记录每个应用/服务支持的执行级别
# ============================================================================

@dataclass
class AppCapability:
    """应用能力声明"""
    app_id: str                          # 包名或服务标识
    a2a_endpoint: str = ""               # A2A API 端点 (空=不支持)
    a2a_actions: List[str] = field(default_factory=list)  # 支持的 A2A 动作
    gui_supported: bool = True           # 是否支持 GUI 自动化
    vlm_supported: bool = True           # 是否支持 VLM (几乎所有应用都支持)
    preferred_level: Optional[ExecutionLevel] = None  # 强制首选级别


class CapabilityRegistry:
    """应用能力注册表"""

    def __init__(self):
        self._apps: Dict[str, AppCapability] = {}
        self._register_defaults()

    def _register_defaults(self):
        """注册默认应用能力"""
        defaults = [
            AppCapability("com.tencent.mm", gui_supported=True,
                          a2a_actions=["send_message"],
                          a2a_endpoint=""),  # 微信: 暂无公开 A2A
            AppCapability("com.android.settings", gui_supported=True),
            AppCapability("com.android.chrome",
                          a2a_actions=["open_url", "search"],
                          a2a_endpoint="intent://"),
            AppCapability("system_shell",
                          a2a_endpoint="adb",
                          a2a_actions=["execute"],
                          preferred_level=ExecutionLevel.A2A),
            AppCapability("file_manager",
                          a2a_endpoint="filesystem",
                          a2a_actions=["read", "write", "list", "delete"],
                          preferred_level=ExecutionLevel.A2A),
        ]
        for cap in defaults:
            self._apps[cap.app_id] = cap

    def register(self, cap: AppCapability):
        self._apps[cap.app_id] = cap

    def get(self, app_id: str) -> Optional[AppCapability]:
        return self._apps.get(app_id)

    def get_preferred_levels(self, app_id: str) -> List[ExecutionLevel]:
        """根据应用能力返回执行级别优先序列"""
        cap = self._apps.get(app_id)
        if not cap:
            return [ExecutionLevel.A2A, ExecutionLevel.GUI, ExecutionLevel.VLM]

        if cap.preferred_level:
            levels = [cap.preferred_level]
            for lv in [ExecutionLevel.A2A, ExecutionLevel.GUI, ExecutionLevel.VLM]:
                if lv != cap.preferred_level:
                    levels.append(lv)
            return levels

        levels = []
        if cap.a2a_endpoint or cap.a2a_actions:
            levels.append(ExecutionLevel.A2A)
        if cap.gui_supported:
            levels.append(ExecutionLevel.GUI)
        if cap.vlm_supported:
            levels.append(ExecutionLevel.VLM)
        return levels or [ExecutionLevel.GUI, ExecutionLevel.VLM]

    def list_apps(self) -> List[Dict]:
        return [
            {"app_id": cap.app_id, "a2a": bool(cap.a2a_endpoint),
             "gui": cap.gui_supported, "vlm": cap.vlm_supported}
            for cap in self._apps.values()
        ]


# ============================================================================
# 执行器接口
# ============================================================================

# A2A 执行器: (app_id, action, params, device_id) -> result_dict
A2AExecutor = Callable[[str, str, Dict, str], Awaitable[Dict[str, Any]]]

# GUI 执行器: (device_id, action, params) -> result_dict
GUIExecutor = Callable[[str, str, Dict], Awaitable[Dict[str, Any]]]

# VLM 执行器: (device_id, instruction, screenshot_b64) -> result_dict
VLMExecutor = Callable[[str, str, Optional[str]], Awaitable[Dict[str, Any]]]

# 截图器: (device_id) -> base64_string
ScreenshotGetter = Callable[[str], Awaitable[str]]


class HybridExecutionArbiter:
    """
    混合执行仲裁器

    核心逻辑:
    1. 接收执行请求 (device_id, app_id, action, params)
    2. 查询能力注册表获取执行级别序列
    3. 按序尝试: A2A → GUI → VLM
    4. 返回最终结果 (包含所有尝试记录)
    """

    def __init__(
        self,
        a2a_executor: A2AExecutor = None,
        gui_executor: GUIExecutor = None,
        vlm_executor: VLMExecutor = None,
        screenshot_getter: ScreenshotGetter = None,
    ):
        self._a2a = a2a_executor
        self._gui = gui_executor
        self._vlm = vlm_executor
        self._screenshot = screenshot_getter
        self.registry = CapabilityRegistry()
        self._execution_history: List[Dict] = []
        self._stats = {
            "total": 0,
            "a2a_success": 0,
            "gui_success": 0,
            "vlm_success": 0,
            "all_failed": 0,
        }

    def set_executors(
        self,
        a2a: A2AExecutor = None,
        gui: GUIExecutor = None,
        vlm: VLMExecutor = None,
        screenshot: ScreenshotGetter = None,
    ):
        if a2a:
            self._a2a = a2a
        if gui:
            self._gui = gui
        if vlm:
            self._vlm = vlm
        if screenshot:
            self._screenshot = screenshot

    async def execute(
        self,
        device_id: str,
        app_id: str,
        action: str,
        params: Dict[str, Any] = None,
        instruction: str = "",
        force_level: ExecutionLevel = None,
    ) -> HybridResult:
        """
        混合执行入口

        Args:
            device_id: 目标设备 ID
            app_id: 目标应用标识
            action: 要执行的动作
            params: 动作参数
            instruction: 自然语言指令 (VLM 模式使用)
            force_level: 强制使用指定级别 (跳过降级)
        """
        params = params or {}
        request_id = str(uuid.uuid4())[:12]
        start = time.time()
        self._stats["total"] += 1

        # 确定执行级别序列
        if force_level:
            levels = [force_level]
        else:
            levels = self.registry.get_preferred_levels(app_id)

        attempts = []

        for level in levels:
            attempt = await self._try_level(
                level, device_id, app_id, action, params, instruction
            )
            attempts.append(attempt)

            if attempt.status == ExecutionStatus.SUCCESS:
                self._stats[f"{level.value}_success"] += 1
                result = HybridResult(
                    request_id=request_id,
                    success=True,
                    final_level=level,
                    result=attempt.result,
                    attempts=[self._attempt_to_dict(a) for a in attempts],
                    total_latency_ms=(time.time() - start) * 1000,
                )
                self._record(result)
                return result

            logger.info(
                f"Level {level.value} failed for {app_id}.{action}: "
                f"{attempt.error}. Trying next level..."
            )

        # 所有级别都失败
        self._stats["all_failed"] += 1
        result = HybridResult(
            request_id=request_id,
            success=False,
            final_level=levels[-1] if levels else ExecutionLevel.A2A,
            result={"error": "All execution levels failed"},
            attempts=[self._attempt_to_dict(a) for a in attempts],
            total_latency_ms=(time.time() - start) * 1000,
        )
        self._record(result)
        return result

    async def _try_level(
        self,
        level: ExecutionLevel,
        device_id: str,
        app_id: str,
        action: str,
        params: Dict,
        instruction: str,
    ) -> ExecutionAttempt:
        """尝试单个执行级别"""
        start = time.time()

        try:
            if level == ExecutionLevel.A2A:
                return await self._try_a2a(device_id, app_id, action, params, start)
            elif level == ExecutionLevel.GUI:
                return await self._try_gui(device_id, action, params, start)
            elif level == ExecutionLevel.VLM:
                return await self._try_vlm(device_id, instruction or f"{action} {json.dumps(params)}", start)
            else:
                return ExecutionAttempt(
                    level=level,
                    status=ExecutionStatus.FAILED,
                    error=f"Unknown level: {level}",
                )
        except Exception as e:
            return ExecutionAttempt(
                level=level,
                status=ExecutionStatus.FAILED,
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def _try_a2a(
        self, device_id: str, app_id: str, action: str, params: Dict, start: float
    ) -> ExecutionAttempt:
        """Level 1: A2A 直接调用"""
        if not self._a2a:
            return ExecutionAttempt(
                level=ExecutionLevel.A2A,
                status=ExecutionStatus.SKIPPED,
                error="No A2A executor configured",
                latency_ms=(time.time() - start) * 1000,
            )

        result = await self._a2a(app_id, action, params, device_id)

        if result.get("success", False) or result.get("status") == "success":
            return ExecutionAttempt(
                level=ExecutionLevel.A2A,
                status=ExecutionStatus.SUCCESS,
                result=result,
                latency_ms=(time.time() - start) * 1000,
            )
        return ExecutionAttempt(
            level=ExecutionLevel.A2A,
            status=ExecutionStatus.FAILED,
            error=result.get("error", "A2A call returned non-success"),
            result=result,
            latency_ms=(time.time() - start) * 1000,
        )

    async def _try_gui(
        self, device_id: str, action: str, params: Dict, start: float
    ) -> ExecutionAttempt:
        """Level 2: GUI 自动化"""
        if not self._gui:
            return ExecutionAttempt(
                level=ExecutionLevel.GUI,
                status=ExecutionStatus.SKIPPED,
                error="No GUI executor configured",
                latency_ms=(time.time() - start) * 1000,
            )

        result = await self._gui(device_id, action, params)

        if result.get("success", False) or result.get("status") == "success":
            return ExecutionAttempt(
                level=ExecutionLevel.GUI,
                status=ExecutionStatus.SUCCESS,
                result=result,
                latency_ms=(time.time() - start) * 1000,
            )
        return ExecutionAttempt(
            level=ExecutionLevel.GUI,
            status=ExecutionStatus.FAILED,
            error=result.get("error", "GUI automation failed"),
            result=result,
            latency_ms=(time.time() - start) * 1000,
        )

    async def _try_vlm(
        self, device_id: str, instruction: str, start: float
    ) -> ExecutionAttempt:
        """Level 3: VLM 视觉理解执行"""
        if not self._vlm:
            return ExecutionAttempt(
                level=ExecutionLevel.VLM,
                status=ExecutionStatus.SKIPPED,
                error="No VLM executor configured",
                latency_ms=(time.time() - start) * 1000,
            )

        # 获取截图
        screenshot_b64 = None
        if self._screenshot:
            try:
                screenshot_b64 = await self._screenshot(device_id)
            except Exception as e:
                logger.warning(f"Screenshot failed: {e}")

        result = await self._vlm(device_id, instruction, screenshot_b64)

        if result.get("success", False) or result.get("status") == "success":
            return ExecutionAttempt(
                level=ExecutionLevel.VLM,
                status=ExecutionStatus.SUCCESS,
                result=result,
                latency_ms=(time.time() - start) * 1000,
            )
        return ExecutionAttempt(
            level=ExecutionLevel.VLM,
            status=ExecutionStatus.FAILED,
            error=result.get("error", "VLM execution failed"),
            result=result,
            latency_ms=(time.time() - start) * 1000,
        )

    # ================================================================
    # 辅助
    # ================================================================

    @staticmethod
    def _attempt_to_dict(attempt: ExecutionAttempt) -> Dict:
        return {
            "level": attempt.level.value,
            "status": attempt.status.value,
            "result": attempt.result,
            "error": attempt.error,
            "latency_ms": attempt.latency_ms,
        }

    def _record(self, result: HybridResult):
        self._execution_history.append(result.to_dict())
        if len(self._execution_history) > 200:
            self._execution_history = self._execution_history[-200:]

    def get_stats(self) -> Dict:
        return {**self._stats, "registry_apps": len(self.registry._apps)}

    def get_history(self, limit: int = 50) -> List[Dict]:
        return self._execution_history[-limit:]


# ============================================================================
# 单例
# ============================================================================

_arbiter_instance: Optional[HybridExecutionArbiter] = None


def get_hybrid_arbiter() -> HybridExecutionArbiter:
    global _arbiter_instance
    if _arbiter_instance is None:
        _arbiter_instance = HybridExecutionArbiter()
    return _arbiter_instance
