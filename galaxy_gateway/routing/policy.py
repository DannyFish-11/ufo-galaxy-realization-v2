"""galaxy_gateway/routing/policy.py — Routing policy / command analysis.

This module owns the decision of *what* a command is asking for and *which
category* of device should handle it.  It is intentionally separate from
device *selection* (which specific device to pick) and *dispatch* (how to
send the task).

Responsibilities
----------------
- Parse a natural-language command into a structured analysis dict.
- Identify the target device type, task type, and required actions.
- Detect whether cross-device coordination is needed.

The ``analyze_command`` function is extracted from
``DeviceRouter._analyze_command``; its output schema is unchanged so that
``device_selection.select_devices`` and the routing chain continue to work
without modification.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

ROUTING_POLICY_AUTHORITY = "galaxy_gateway.routing.policy"
"""Sentinel string identifying this module as the routing-policy authority."""


# ---------------------------------------------------------------------------
# Task-type labels (mirrored from DeviceRouter.TaskType for import convenience)
# ---------------------------------------------------------------------------

_TASK_UI_AUTOMATION = "ui_automation"
_TASK_APP_CONTROL = "app_control"
_TASK_SYSTEM_CONTROL = "system_control"
_TASK_QUERY = "query"
_TASK_COMPOUND = "compound"
_TASK_CROSS_DEVICE = "cross_device"


# ---------------------------------------------------------------------------
# Command analysis
# ---------------------------------------------------------------------------


def analyze_command(command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Analyse *command* and return a routing-policy analysis dict.

    This function is the extracted implementation of
    ``DeviceRouter._analyze_command``.  It uses lightweight keyword matching
    to determine:

    - The target ``DeviceType`` (Android, Windows, iOS, or UNKNOWN).
    - The ``task_type`` (UI automation, app control, system control, query, …).
    - The list of primary ``actions`` extracted from the command.
    - Whether ``requires_cross_device`` coordination is needed.

    Additional fields present in *context* (e.g. ``exec_mode``,
    ``required_capabilities``, ``device_id``) are passed through unchanged
    so that downstream routing steps can consume them.

    Args:
        command: Natural-language command string.
        context: Optional caller-supplied context dict.  Fields from *context*
                 that are relevant to routing are merged into the returned dict.

    Returns:
        Analysis dict with at least the following keys:

        ``command``
            The original command string.
        ``target_device_type``
            A :class:`~core.device_types.DeviceType` enum value.
        ``task_type``
            One of the ``_TASK_*`` string constants.
        ``actions``
            List of action keyword strings.
        ``requires_cross_device``
            ``True`` when cross-device coordination is needed.
    """
    from core.device_types import DeviceType  # lazy import — avoids circular deps

    ctx = context or {}

    analysis: Dict[str, Any] = {
        "command": command,
        "target_device_type": DeviceType.UNKNOWN,
        "task_type": _TASK_UI_AUTOMATION,
        "actions": [],
        "requires_cross_device": False,
        # Pass through caller-supplied routing hints
        "exec_mode": ctx.get("exec_mode", ""),
        "required_capabilities": ctx.get("required_capabilities", []),
        "task_role": ctx.get("task_role"),
    }

    command_lower = command.lower()

    # ── Target device type ───────────────────────────────────────────────────
    if any(kw in command_lower for kw in ["手机", "android", "移动端", "app"]):
        analysis["target_device_type"] = DeviceType.ANDROID
    elif any(kw in command_lower for kw in ["电脑", "pc", "windows", "桌面"]):
        analysis["target_device_type"] = DeviceType.WINDOWS
    elif any(kw in command_lower for kw in ["平板", "ipad", "tablet"]):
        analysis["target_device_type"] = DeviceType.IOS

    # ── Task type and actions ────────────────────────────────────────────────
    if any(kw in command_lower for kw in ["打开", "启动", "运行"]):
        analysis["task_type"] = _TASK_APP_CONTROL
        analysis["actions"].append("open")
    elif any(kw in command_lower for kw in ["点击", "按", "选择"]):
        analysis["task_type"] = _TASK_UI_AUTOMATION
        analysis["actions"].append("click")
    elif any(kw in command_lower for kw in ["输入", "填写", "写入"]):
        analysis["task_type"] = _TASK_UI_AUTOMATION
        analysis["actions"].append("input")
    elif any(kw in command_lower for kw in ["查询", "查看", "显示"]):
        analysis["task_type"] = _TASK_QUERY
        analysis["actions"].append("query")
    elif any(kw in command_lower for kw in ["音量", "亮度", "wifi", "蓝牙"]):
        analysis["task_type"] = _TASK_SYSTEM_CONTROL

    # ── Cross-device coordination ────────────────────────────────────────────
    if any(kw in command_lower for kw in ["复制到", "发送到", "传输到", "同步"]):
        analysis["requires_cross_device"] = True

    return analysis
