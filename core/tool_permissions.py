"""
工具调用权限控制与安全强约束 (Phase 9)
==========================================

智能体可以操控 Windows 电脑（截屏、点击、输入、文件操作），
如果没有权限管控，等于给 LLM 幻觉留了直通系统的后门。

本模块提供：
  1. 工具风险四级分类（SAFE/MODERATE/DANGEROUS/CRITICAL）
  2. 工具名 glob 匹配策略
  3. 频率限制（每分钟调用上限）
  4. 敏感操作用户确认机制
  5. 审计日志记录

设计原则：
  - SAFE/MODERATE 级默认放行，不影响正常体验
  - DANGEROUS/CRITICAL 级需要确认或受频率限制
  - 所有检查结果通过 AuditLogger 记录
  - 可通过 config 扩展策略，不硬编码
"""

import fnmatch
import logging
import time
from collections import defaultdict
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.ToolPermissions")


# ============================================================================
# 数据模型
# ============================================================================

class ToolRiskLevel(str, Enum):
    """工具风险等级"""
    SAFE = "safe"              # 只读/查询类：screenshot, get_screen_state, search
    MODERATE = "moderate"      # 输入类：click, type, scroll, find_and_click
    DANGEROUS = "dangerous"    # 系统级：press_keys(hotkey), file_delete, process_stop
    CRITICAL = "critical"      # 破坏性：system_command, file_write(/system/*), 批量操作


class ToolPermissionPolicy(BaseModel):
    """工具权限策略"""
    tool_pattern: str = Field(..., description="工具名匹配模式（glob），如 'mcp__*__screenshot'")
    risk_level: ToolRiskLevel = Field(default=ToolRiskLevel.MODERATE)
    requires_confirmation: bool = Field(default=False, description="是否需要用户二次确认")
    max_calls_per_minute: int = Field(default=60, ge=1, description="每分钟最大调用次数")


class PermissionCheckResult(BaseModel):
    """权限检查结果"""
    allowed: bool = True
    requires_confirmation: bool = False
    risk_level: str = "safe"
    reason: str = ""
    tool_name: str = ""


# ============================================================================
# 默认策略
# ============================================================================

DEFAULT_POLICIES: List[ToolPermissionPolicy] = [
    # SAFE: 只读/查询
    ToolPermissionPolicy(tool_pattern="mcp__*__screenshot", risk_level=ToolRiskLevel.SAFE),
    ToolPermissionPolicy(tool_pattern="mcp__*__get_screen_state", risk_level=ToolRiskLevel.SAFE),
    ToolPermissionPolicy(tool_pattern="node__*__search", risk_level=ToolRiskLevel.SAFE),
    ToolPermissionPolicy(tool_pattern="node__*__list", risk_level=ToolRiskLevel.SAFE),
    ToolPermissionPolicy(tool_pattern="node__*__read", risk_level=ToolRiskLevel.SAFE),
    ToolPermissionPolicy(tool_pattern="node__*__status", risk_level=ToolRiskLevel.SAFE),
    ToolPermissionPolicy(tool_pattern="node__*__info", risk_level=ToolRiskLevel.SAFE),

    # MODERATE: 输入操作
    ToolPermissionPolicy(tool_pattern="mcp__*__click", risk_level=ToolRiskLevel.MODERATE),
    ToolPermissionPolicy(tool_pattern="mcp__*__type", risk_level=ToolRiskLevel.MODERATE),
    ToolPermissionPolicy(tool_pattern="mcp__*__scroll", risk_level=ToolRiskLevel.MODERATE),
    ToolPermissionPolicy(tool_pattern="mcp__*__find_and_click", risk_level=ToolRiskLevel.MODERATE),
    ToolPermissionPolicy(tool_pattern="mcp__*__find_and_type", risk_level=ToolRiskLevel.MODERATE),
    ToolPermissionPolicy(tool_pattern="node__*__write", risk_level=ToolRiskLevel.MODERATE),

    # DANGEROUS: 系统级，需确认
    ToolPermissionPolicy(
        tool_pattern="mcp__*__press_key",
        risk_level=ToolRiskLevel.DANGEROUS,
        requires_confirmation=False,  # 单键一般安全
        max_calls_per_minute=30,
    ),
    ToolPermissionPolicy(
        tool_pattern="mcp__*__press_keys",
        risk_level=ToolRiskLevel.DANGEROUS,
        requires_confirmation=True,
        max_calls_per_minute=10,
    ),
    ToolPermissionPolicy(
        tool_pattern="node__*__delete",
        risk_level=ToolRiskLevel.DANGEROUS,
        requires_confirmation=True,
        max_calls_per_minute=5,
    ),
    ToolPermissionPolicy(
        tool_pattern="node__*__file_delete",
        risk_level=ToolRiskLevel.DANGEROUS,
        requires_confirmation=True,
        max_calls_per_minute=5,
    ),

    # CRITICAL: 破坏性，严格限制
    ToolPermissionPolicy(
        tool_pattern="node__*__system_command",
        risk_level=ToolRiskLevel.CRITICAL,
        requires_confirmation=True,
        max_calls_per_minute=3,
    ),
    ToolPermissionPolicy(
        tool_pattern="node__*__execute",
        risk_level=ToolRiskLevel.CRITICAL,
        requires_confirmation=True,
        max_calls_per_minute=5,
    ),
]


# ============================================================================
# 权限检查器
# ============================================================================

class ToolPermissionChecker:
    """工具调用权限检查器

    - 根据工具名匹配策略，返回风险等级和是否需要确认
    - 维护每分钟调用计数器，超限则拒绝
    - 未匹配任何策略的工具默认为 MODERATE（放行但记录）
    """

    def __init__(self, policies: Optional[List[ToolPermissionPolicy]] = None):
        self._policies = policies or list(DEFAULT_POLICIES)
        # 频率计数: {tool_pattern: [(timestamp, count), ...]}
        self._call_counts: Dict[str, List[float]] = defaultdict(list)

    def check(
        self,
        tool_name: str,
        session_id: str = "",
        device_id: str = "",
    ) -> PermissionCheckResult:
        """检查工具调用权限

        Args:
            tool_name: 工具名，如 "mcp__windows-local__press_keys"
            session_id: 会话 ID
            device_id: 设备 ID

        Returns:
            PermissionCheckResult
        """
        # 查找匹配的策略（取最严格的）
        matched_policy = self._find_policy(tool_name)

        if matched_policy is None:
            # 未匹配 → 默认 MODERATE，放行但记录
            logger.debug(f"工具 {tool_name} 未匹配任何策略，默认 MODERATE")
            return PermissionCheckResult(
                allowed=True,
                risk_level=ToolRiskLevel.MODERATE.value,
                tool_name=tool_name,
            )

        # 频率检查
        if not self._check_rate_limit(matched_policy):
            logger.warning(
                f"工具 {tool_name} 超过频率限制 "
                f"({matched_policy.max_calls_per_minute}/min)"
            )
            return PermissionCheckResult(
                allowed=False,
                risk_level=matched_policy.risk_level.value,
                reason=f"超过频率限制 ({matched_policy.max_calls_per_minute}/min)",
                tool_name=tool_name,
            )

        # 记录本次调用
        self._record_call(matched_policy.tool_pattern)

        # 审计日志
        if matched_policy.risk_level in (ToolRiskLevel.DANGEROUS, ToolRiskLevel.CRITICAL):
            logger.info(
                f"[AUDIT] 工具调用: {tool_name} | 风险: {matched_policy.risk_level.value} "
                f"| 确认: {matched_policy.requires_confirmation} "
                f"| session: {session_id} | device: {device_id}"
            )

        return PermissionCheckResult(
            allowed=True,
            requires_confirmation=matched_policy.requires_confirmation,
            risk_level=matched_policy.risk_level.value,
            tool_name=tool_name,
        )

    def _find_policy(self, tool_name: str) -> Optional[ToolPermissionPolicy]:
        """查找匹配的策略（精确匹配优先，再 glob 匹配）"""
        best: Optional[ToolPermissionPolicy] = None
        for policy in self._policies:
            if fnmatch.fnmatch(tool_name, policy.tool_pattern):
                if best is None:
                    best = policy
                elif _risk_order(policy.risk_level) > _risk_order(best.risk_level):
                    best = policy  # 取最严格的
        return best

    def _check_rate_limit(self, policy: ToolPermissionPolicy) -> bool:
        """检查是否超过频率限制"""
        now = time.time()
        window = 60.0  # 1 分钟窗口
        key = policy.tool_pattern

        # 清理过期记录
        self._call_counts[key] = [
            t for t in self._call_counts[key] if now - t < window
        ]

        return len(self._call_counts[key]) < policy.max_calls_per_minute

    def _record_call(self, pattern: str):
        """记录一次工具调用"""
        self._call_counts[pattern].append(time.time())

    def add_policy(self, policy: ToolPermissionPolicy):
        """动态添加策略"""
        self._policies.append(policy)

    def reset_counters(self):
        """重置频率计数器"""
        self._call_counts.clear()


def _risk_order(level: ToolRiskLevel) -> int:
    """风险等级排序（越高越严格）"""
    return {
        ToolRiskLevel.SAFE: 0,
        ToolRiskLevel.MODERATE: 1,
        ToolRiskLevel.DANGEROUS: 2,
        ToolRiskLevel.CRITICAL: 3,
    }.get(level, 1)


# ============================================================================
# 设备能力白名单校验
# ============================================================================

DEVICE_CAPABILITY_WHITELIST: Dict[str, List[str]] = {
    "windows_desktop": [
        "get_screen_state", "click", "type", "press_key", "press_keys",
        "scroll", "find_and_click", "find_and_type", "screenshot",
        "execute_script", "send_notification", "display_media",
        "visual_action", "ui_automation",
    ],
    "windows_laptop": [
        "get_screen_state", "click", "type", "press_key", "press_keys",
        "scroll", "find_and_click", "find_and_type", "screenshot",
        "execute_script", "send_notification", "display_media",
        "visual_action", "ui_automation",
    ],
    "android_phone": [
        "tap", "swipe", "input_text", "screenshot", "install_app",
        "uninstall_app", "launch_app", "press_key", "shell",
        "get_ui_tree", "find_element",
    ],
    "android_tablet": [
        "tap", "swipe", "input_text", "screenshot", "install_app",
        "uninstall_app", "launch_app", "press_key", "shell",
        "get_ui_tree", "find_element",
    ],
}


def validate_device_capabilities(
    device_type: str, reported_capabilities: List[str]
) -> List[str]:
    """服务端校验设备声明的能力，过滤非法声明

    Args:
        device_type: 设备类型，如 "windows_desktop"
        reported_capabilities: 客户端自报的能力列表

    Returns:
        校验后的合法能力列表
    """
    whitelist = DEVICE_CAPABILITY_WHITELIST.get(device_type)
    if whitelist is None:
        # 未知设备类型 → 保守策略，只允许 screenshot 和查询类
        logger.warning(f"未知设备类型 {device_type}，仅允许只读能力")
        safe_defaults = {"screenshot", "get_screen_state", "get_ui_tree", "status"}
        return [cap for cap in reported_capabilities if cap in safe_defaults]

    validated = [cap for cap in reported_capabilities if cap in whitelist]
    filtered = set(reported_capabilities) - set(validated)
    if filtered:
        logger.warning(
            f"设备 {device_type} 声明了非法能力，已过滤: {filtered}"
        )
    return validated


# ============================================================================
# 全局单例
# ============================================================================

_checker_instance: Optional[ToolPermissionChecker] = None


def get_tool_permission_checker() -> ToolPermissionChecker:
    """获取全局权限检查器单例"""
    global _checker_instance
    if _checker_instance is None:
        _checker_instance = ToolPermissionChecker()
    return _checker_instance
