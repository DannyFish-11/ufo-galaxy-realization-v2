"""device_client/executors — 在本机真正动手的那一层,按系统插件化。

一个插件就是一个对象,回答三个问题:

* ``platform`` / ``name``:我是谁(windows / linux / macos;具体实现名);
* ``available()``:在这台机器上能不能用,不能用的话**为什么**、**怎么补**;
* ``supported_actions()`` + ``execute(action, params)``:能做哪些动作、做一个。

``execute`` 永远不抛异常,永远返回 ``{"success": bool, ...}``;失败要带 ``error``。
主脑看到的动作清单就是 ``supported_actions()`` —— 报了做不到的动作,智能体会去调,
然后失败;所以只报真做得到的。

选择顺序:
1. 环境变量 ``GALAXY_DESKTOP_EXECUTOR``(插件名)指定的;
2. entry point 组 ``galaxy.desktop_executors`` 里登记的第三方插件(可以覆盖内置);
3. 内置:按 ``sys.platform`` 选 windows / linux / macos。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("galaxy-device-client.executors")


class DesktopExecutor:
    """执行插件的基类。子类覆盖 ``name`` / ``platform`` / ``available`` / ``supported_actions`` / ``_do``。"""

    name = "base"
    platform = "unknown"

    def available(self) -> Tuple[bool, str]:  # pragma: no cover - 抽象
        return False, "未实现"

    def supported_actions(self) -> List[str]:  # pragma: no cover - 抽象
        return []

    def _do(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - 抽象
        raise NotImplementedError

    def execute(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """做一个动作。不支持的动作如实说不支持;实现里的异常兜成错误结果,不外抛。"""
        params = dict(params or {})
        if action not in self.supported_actions():
            return {
                "success": False,
                "error": f"{self.name} 不支持动作 {action!r}",
                "supported_actions": self.supported_actions(),
            }
        try:
            out = self._do(action, params)
        except Exception as exc:  # noqa: BLE001 — 执行器崩溃不能炸断连接
            logger.warning("[%s] %s 执行异常: %s", self.name, action, exc)
            return {"success": False, "error": str(exc)}
        if not isinstance(out, dict):
            return {"success": True, "output": out}
        out.setdefault("success", True)
        return out

    def execute_agent_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """主脑委派一整段任务(``agent_execute``)。默认不支持 —— 本机没有模型。"""
        return {"success": False, "error": f"{self.name} 不接受整段任务委派,只执行单个动作"}

    def describe(self) -> Dict[str, Any]:
        ok, why = self.available()
        return {
            "executor": self.name,
            "platform": self.platform,
            "available": ok,
            "reason": why,
            "actions": self.supported_actions() if ok else [],
        }


#: 内置插件:平台 → 工厂。放在函数里 import,免得在别的系统上加载不相干的依赖。
def _builtin() -> Dict[str, Callable[[], DesktopExecutor]]:
    def windows() -> DesktopExecutor:
        from device_client.executors.windows import WindowsExecutor

        return WindowsExecutor()

    def linux() -> DesktopExecutor:
        from device_client.executors.linux_x11 import LinuxX11Executor

        return LinuxX11Executor()

    def macos() -> DesktopExecutor:
        from device_client.executors.macos import MacOSExecutor

        return MacOSExecutor()

    return {"windows": windows, "linux": linux, "macos": macos}


def _entry_point_plugins() -> Dict[str, Callable[[], DesktopExecutor]]:
    """第三方插件:``[project.entry-points."galaxy.desktop_executors"] 名字 = "包.模块:工厂"``。"""
    out: Dict[str, Callable[[], DesktopExecutor]] = {}
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="galaxy.desktop_executors"):
            out[ep.name] = ep.load
    except Exception as exc:  # noqa: BLE001 — 插件坏了不该让客户端起不来
        logger.warning("加载第三方执行插件失败: %s", exc)
    return out


def available_executors() -> Dict[str, Callable[[], DesktopExecutor]]:
    return {**_builtin(), **_entry_point_plugins()}


def select_executor(platform_name: Optional[str] = None) -> DesktopExecutor:
    """按「环境变量 → 第三方插件 → 内置」的顺序选一个执行插件。"""
    from device_client.pairing import this_platform

    registry = available_executors()
    wanted = os.environ.get("GALAXY_DESKTOP_EXECUTOR", "").strip()
    if wanted:
        if wanted not in registry:
            raise ValueError(f"GALAXY_DESKTOP_EXECUTOR={wanted!r} 不存在;可选:{sorted(registry)}")
        return registry[wanted]()
    return registry[platform_name or this_platform()]()
