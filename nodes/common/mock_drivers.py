"""节点的模拟驱动：只有明确要（``USE_MOCK_DRIVERS=true``，启动器原样传给每个节点）才模拟。

全面排查第 7 轮：几个节点在缺东西时「模拟执行」并回 ``success: True`` ——

- ADB（Node_33）没连手机 / 没装 adb：点屏、滑动、输入都回成功，智能体以为手机上已经点了；
- OctoPrint（Node_49）没配 Key：开始打印、调温度都回成功；
- GitHubFlow（Node_106）没配 ``GITHUB_TOKEN``：回一个 ``github.com/mock/repo/pull/1`` 的「新 PR」；配了 Token 却没配
  生成模型的 Key：把一段写死的「✅ 代码审查通过……建议合并」**当评论发到真的 PR 上**。

没有任何调用方读 ``mock`` 那一位，看的都是 ``success``。现在缺东西就照实失败、说缺什么；要模拟（测试 / 演示）就显式打开。
"""

from __future__ import annotations

import os
from typing import Any, Dict

__all__ = ["NotConfigured", "mock_drivers_enabled", "unavailable"]


class NotConfigured(RuntimeError):
    """缺一样东西（Key / 设备 / 命令），这一步没有执行。"""


def mock_drivers_enabled() -> bool:
    return os.getenv("USE_MOCK_DRIVERS", "").strip().lower() in ("1", "true", "yes", "on")


def unavailable(action: str, why: str) -> Dict[str, Any]:
    """没执行的那一步，照实这么回。"""
    return {"action": action, "success": False, "mock": False, "error": why}
