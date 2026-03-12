"""
core/policy_loader.py
======================
全局权限策略加载器 (P1)

从 data/permissions_policy.json 读取权限策略，并注入到 Agent 执行上下文中。

用法示例：
    from core.policy_loader import get_policy, get_agent_permissions

    # 获取某 Agent 的有效权限（先查覆盖，再查全局默认）
    perms = get_agent_permissions("agent_001")
"""

import json
import os
from typing import Any, Dict, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_POLICY_FILE = os.path.join(_PROJECT_ROOT, "data", "permissions_policy.json")

_DEFAULT_POLICY: Dict[str, Any] = {
    "global": {
        "filesystem": False,
        "terminal": False,
        "network": True,
        "browser": False,
    },
    "agent_overrides": {},
}


def get_policy() -> Dict[str, Any]:
    """加载完整权限策略，文件不存在时返回内置默认值。"""
    if os.path.exists(_POLICY_FILE):
        try:
            with open(_POLICY_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return _DEFAULT_POLICY.copy()


def get_global_permissions() -> Dict[str, bool]:
    """返回全局默认权限字典 {filesystem, terminal, network, browser}。"""
    policy = get_policy()
    defaults: Dict[str, bool] = {
        "filesystem": False,
        "terminal": False,
        "network": True,
        "browser": False,
    }
    for k, v in policy.get("global", {}).items():
        if k in defaults and isinstance(v, bool):
            defaults[k] = v
    return defaults


def get_agent_permissions(agent_id: str) -> Dict[str, bool]:
    """
    返回指定 Agent 的有效权限。

    优先级: agent_overrides[agent_id] > global > 内置默认
    """
    policy = get_policy()
    base = get_global_permissions()
    overrides: Optional[Dict] = policy.get("agent_overrides", {}).get(agent_id)
    if overrides and isinstance(overrides, dict):
        for k, v in overrides.items():
            if k in base and isinstance(v, bool):
                base[k] = v
    return base


def inject_policy_into_context(context: Dict[str, Any], agent_id: Optional[str] = None) -> Dict[str, Any]:
    """
    将权限策略注入执行上下文字典（就地修改并返回）。

    context["permissions"] 将被设置为该 Agent 的有效权限映射。
    """
    perms = get_agent_permissions(agent_id or "") if agent_id else get_global_permissions()
    context["permissions"] = perms
    return context
