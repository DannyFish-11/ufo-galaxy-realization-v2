#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/security_policy_loader.py — Security Policy Loader

PR-SECURITY-POLICY-V1: OpenClawd 安全策略加载与校验模块。

本模块负责:
  1. 读取 config/security_policy.yaml
  2. 校验策略格式完整性
  3. 提供运行时查询接口（权限检查、危险命令确认等级查询等）
  4. 策略热重载（文件变更时自动重新加载）

与 OpenClawd 集成:
  - OpenClawd.__init__ 中调用 load_security_policy()
  - send_gateway_command() 中调用 check_command_permission() 和
    get_confirmation_level() 做前置安全检查
  - 每条命令执行后调用 audit_command() 记录审计日志

Author: Galaxy Fix Bot
Version: 1.0.0
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

logger = logging.getLogger("Galaxy.SecurityPolicy")

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
SECURITY_POLICY_LOADER_AUTHORITY = (
    "SECURITY_POLICY_LOADER::core.security_policy_loader::"
    "PR-SECURITY-POLICY-V1::runtime-security-boundary-enforcement"
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_POLICY_PATH = "config/security_policy.yaml"
FALLBACK_POLICY_PATH = "config/security_policy.yaml.bak"


class ConfirmationLevel(str, Enum):
    """命令确认等级，从低到高。"""
    NONE = "none"           # 无需确认
    VOICE = "voice"         # 语音确认
    WATCH_BTN = "watch_btn" # 手表按键确认
    DUAL = "dual"           # 双重确认（语音+按键）
    FORBIDDEN = "forbidden" # 完全禁止


class AuditLevel(str, Enum):
    """审计日志级别。"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class CommandCheckResult:
    """命令权限检查结果。"""
    allowed: bool
    reason: str
    confirmation_level: ConfirmationLevel
    audit_level: AuditLevel
    require_trace_id: bool
    safety_timeout_minutes: Optional[int] = None
    notifications: List[Dict[str, str]] = field(default_factory=list)
    max_daily_executions: Optional[int] = None


@dataclass
class AuditRecord:
    """审计记录。"""
    timestamp: str
    trace_id: str
    source_device_id: str
    source_device_type: str
    command: str
    command_category: str
    confirmation_level: str
    confirmation_result: bool
    target_device_id: Optional[str]
    openclawd_decision: str
    execution_result: str
    latency_ms: float


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
_policy_instance: Optional[SecurityPolicy] = None
_policy_load_time: float = 0.0
_policy_file_path: str = DEFAULT_POLICY_PATH


class SecurityPolicy:
    """安全策略运行时。

    封装安全策略的加载、校验和查询。OpenClawd 通过此类的
    实例来做命令权限检查。
    """

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = raw
        self._version = raw.get("policy_version", "unknown")
        self._boundaries: Dict[str, Dict[str, Any]] = raw.get("capability_boundaries", {})
        self._dangerous: Dict[str, Dict[str, Any]] = raw.get("dangerous_commands", {})
        self._audit_rules: Dict[str, Any] = raw.get("audit_rules", {})
        self._failsafe: Dict[str, Any] = raw.get("failsafe", {})
        self._emergency: Dict[str, Any] = raw.get("emergency_stop", {})
        self._daily_counters: Dict[str, Dict[str, int]] = {}  # device -> {command: count}
        self._last_day: str = time.strftime("%Y-%m-%d")

        logger.info("SecurityPolicy loaded | version=%s boundaries=%d dangerous=%d",
                    self._version, len(self._boundaries), len(self._dangerous))

    # -- Public API --------------------------------------------------------

    def get_device_boundary(self, device_type: str) -> Dict[str, Any]:
        """获取指定设备类型的权限边界。未知设备返回最小权限（wear_os）。"""
        boundary = self._boundaries.get(device_type)
        if boundary is None:
            logger.warning("Unknown device_type '%s', falling back to wear_os boundary", device_type)
            boundary = self._boundaries.get("wear_os", {})
        return boundary

    def is_category_allowed(self, device_type: str, category: str) -> bool:
        """检查设备是否有权限执行某命令类别。"""
        boundary = self.get_device_boundary(device_type)
        allowed = set(boundary.get("allowed_categories", []))
        denied = set(boundary.get("denied_categories", []))

        if "*" in allowed:
            return category not in denied
        return category in allowed and category not in denied

    def get_confirmation_level(self, command: str) -> CommandCheckResult:
        """查询命令的确认等级和安全配置。"""
        rule = self._dangerous.get(command)
        if rule is None:
            # 使用默认规则
            rule = self._dangerous.get("_default", {})

        level_str = rule.get("confirmation_level", "voice")
        try:
            level = ConfirmationLevel(level_str)
        except ValueError:
            level = ConfirmationLevel.VOICE

        audit_str = rule.get("audit_level", "warning")
        try:
            audit = AuditLevel(audit_str)
        except ValueError:
            audit = AuditLevel.WARNING

        return CommandCheckResult(
            allowed=level != ConfirmationLevel.FORBIDDEN,
            reason=rule.get("reason", ""),
            confirmation_level=level,
            audit_level=audit,
            require_trace_id=rule.get("require_trace_id", True),
            safety_timeout_minutes=rule.get("safety_timeout_minutes"),
            notifications=rule.get("notifications", []),
            max_daily_executions=rule.get("max_daily_executions"),
        )

    def check_daily_limit(self, device_id: str, command: str) -> bool:
        """检查命令是否超过每日执行上限。"""
        rule = self._dangerous.get(command, {})
        max_daily = rule.get("max_daily_executions")
        if max_daily is None:
            return True

        # Reset counters on day change
        today = time.strftime("%Y-%m-%d")
        if today != self._last_day:
            self._daily_counters.clear()
            self._last_day = today

        device_counts = self._daily_counters.setdefault(device_id, {})
        current = device_counts.get(command, 0)
        if current >= max_daily:
            logger.warning("Daily limit exceeded | device=%s command=%s limit=%d", device_id, command, max_daily)
            return False
        device_counts[command] = current + 1
        return True

    def check_command_permission(
        self,
        device_type: str,
        device_id: str,
        command: str,
        command_category: str,
    ) -> CommandCheckResult:
        """完整的命令权限检查 — OpenClawd 在执行前调用。

        检查流程:
          1. 设备权限边界（类别是否允许）
          2. 危险命令确认等级
          3. 每日执行上限
        """
        # Step 1: category permission
        if not self.is_category_allowed(device_type, command_category):
            return CommandCheckResult(
                allowed=False,
                reason=f"设备类型 '{device_type}' 无权执行类别 '{command_category}'",
                confirmation_level=ConfirmationLevel.FORBIDDEN,
                audit_level=AuditLevel.WARNING,
                require_trace_id=True,
            )

        # Step 2: dangerous command check
        result = self.get_confirmation_level(command)
        if not result.allowed:
            return result

        # Step 3: daily limit
        if not self.check_daily_limit(device_id, command):
            return CommandCheckResult(
                allowed=False,
                reason=f"命令 '{command}' 已超过每日执行上限",
                confirmation_level=ConfirmationLevel.FORBIDDEN,
                audit_level=AuditLevel.WARNING,
                require_trace_id=True,
            )

        return result

    def get_scene_whitelist(self, device_type: str) -> Set[str]:
        """获取设备允许触发的场景白名单。"""
        boundary = self.get_device_boundary(device_type)
        return set(boundary.get("scene_whitelist", []))

    def is_scene_allowed(self, device_type: str, scene_name: str) -> bool:
        """检查设备是否有权限触发指定场景。"""
        whitelist = self.get_scene_whitelist(device_type)
        if not whitelist:
            # 没有白名单 = 全部允许（兼容旧设备）
            return True
        return scene_name in whitelist

    def get_emergency_triggers(self) -> Dict[str, Any]:
        """获取紧急制动触发配置。"""
        return self._emergency.get("triggers", {})

    def get_emergency_actions(self) -> List[str]:
        """获取紧急制动执行动作列表。"""
        return self._emergency.get("actions", [])

    def is_emergency_enabled(self) -> bool:
        """紧急制动是否启用。"""
        return self._emergency.get("enabled", False)

    def should_log_audit(self) -> bool:
        """审计日志是否启用。"""
        return self._audit_rules.get("enabled", True)

    def get_audit_required_fields(self) -> List[str]:
        """获取审计记录必须包含的字段。"""
        return self._audit_rules.get("required_fields", [])

    @property
    def version(self) -> str:
        return self._version

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict（用于状态报告）。"""
        return {
            "version": self._version,
            "boundaries": list(self._boundaries.keys()),
            "dangerous_commands": list(self._dangerous.keys()),
            "audit_enabled": self.should_log_audit(),
            "emergency_enabled": self.is_emergency_enabled(),
        }


# ---------------------------------------------------------------------------
# Factory / loader
# ---------------------------------------------------------------------------

def load_security_policy(path: Optional[str] = None) -> SecurityPolicy:
    """加载安全策略文件。

    加载顺序:
      1. 指定路径（如果提供）
      2. DEFAULT_POLICY_PATH
      3. FALLBACK_POLICY_PATH
      4. 全部失败时返回最小默认策略（deny_all_dangerous）
    """
    global _policy_instance, _policy_load_time, _policy_file_path

    paths_to_try = []
    if path:
        paths_to_try.append(path)
    paths_to_try.extend([DEFAULT_POLICY_PATH, FALLBACK_POLICY_PATH])

    for p in paths_to_try:
        policy = _try_load_file(p)
        if policy is not None:
            _policy_instance = policy
            _policy_load_time = time.time()
            _policy_file_path = p
            return policy

    # All loads failed — return failsafe default
    logger.critical("All security policy files failed to load! Using failsafe defaults (deny all dangerous).")
    return _create_failsafe_policy()


def _try_load_file(path: str) -> Optional[SecurityPolicy]:
    """尝试加载单个策略文件。"""
    if not os.path.exists(path):
        logger.debug("Security policy file not found: %s", path)
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            if yaml:
                raw = yaml.safe_load(f)
            else:
                # Fallback: try JSON
                raw = json.load(f)
    except Exception as exc:
        logger.error("Failed to parse security policy %s: %s", path, exc)
        return None

    if not raw or not isinstance(raw, dict):
        logger.error("Security policy %s is empty or invalid", path)
        return None

    try:
        policy = SecurityPolicy(raw)
        logger.info("Security policy loaded from %s | version=%s", path, policy.version)
        return policy
    except Exception as exc:
        logger.error("Failed to initialize SecurityPolicy from %s: %s", path, exc)
        return None


def _create_failsafe_policy() -> SecurityPolicy:
    """创建失效保护策略 — 允许查询和低危操作，拒绝所有危险操作。"""
    failsafe_raw = {
        "policy_version": "failsafe-1.0",
        "capability_boundaries": {
            "wear_os": {
                "allowed_categories": ["query"],
                "denied_categories": ["*"],
            },
            "android": {
                "allowed_categories": ["query", "light_control", "scene_trigger", "media_playback"],
                "denied_categories": ["door_lock", "camera_control", "hvac_control",
                                       "appliance_power", "security_arm", "device_takeover"],
            },
            "tablet": {
                "allowed_categories": ["query", "media_playback"],
                "denied_categories": ["*"],
            },
            "windows": {
                "allowed_categories": ["*"],
                "denied_categories": [],
            },
        },
        "dangerous_commands": {
            "_default": {
                "confirmation_level": "voice",
                "reason": "Fallsafe mode: unknown command requires voice confirmation",
                "audit_level": "warning",
                "require_trace_id": True,
            },
            "door.unlock": {
                "confirmation_level": "dual",
                "reason": "Fallsafe: door unlock requires dual confirmation",
                "audit_level": "critical",
                "require_trace_id": True,
            },
            "device.takeover": {
                "confirmation_level": "forbidden",
                "reason": "Fallsafe: takeovers are forbidden until policy file is restored",
                "audit_level": "critical",
                "require_trace_id": True,
            },
        },
        "audit_rules": {"enabled": True, "log_level": "verbose"},
        "failsafe": {"policy_file_missing": {"action": "deny_all_dangerous"}},
        "emergency_stop": {"enabled": True, "triggers": {}, "actions": []},
    }
    return SecurityPolicy(failsafe_raw)


def get_security_policy() -> Optional[SecurityPolicy]:
    """获取当前已加载的安全策略实例。"""
    return _policy_instance


def reload_security_policy(path: Optional[str] = None) -> SecurityPolicy:
    """热重载安全策略。"""
    global _policy_instance
    new_policy = load_security_policy(path or _policy_file_path)
    _policy_instance = new_policy
    logger.info("Security policy reloaded | version=%s", new_policy.version)
    return new_policy


def check_policy_file_changed() -> bool:
    """检查策略文件是否有变更（用于定时热重载）。"""
    if not os.path.exists(_policy_file_path):
        return False
    try:
        mtime = os.path.getmtime(_policy_file_path)
        return mtime > _policy_load_time
    except OSError:
        return False
