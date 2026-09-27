"""Windows 执行插件:交给 ``WindowsExecutionArbiter``(系统 API → UIA → GUI → 视觉模型)。

执行本体仍在 ``windows_client/windows_aip_client.py`` 的 ``_execute_command`` /
``_execute_agent_task`` —— 那是 Windows 唯一的执行入口,既有契约与用例都钉在那里。
这里只是把它接进插件接口;调用时才去模块上取,测试对那两个函数的替换照样生效。
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Tuple

from device_client.executors import DesktopExecutor


class WindowsExecutor(DesktopExecutor):
    name = "windows-arbiter"
    platform = "windows"

    def available(self) -> Tuple[bool, str]:
        if not sys.platform.startswith("win"):
            return False, "只在 Windows 上可用"
        return True, ""

    def supported_actions(self) -> List[str]:
        from windows_client import windows_aip_client as wac

        return list(wac.WINDOWS_SUPPORTED_ACTIONS)

    def _do(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from windows_client import windows_aip_client as wac

        return wac._execute_command(action, params)

    def execute_agent_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from windows_client import windows_aip_client as wac

        return wac._execute_agent_task(payload)
