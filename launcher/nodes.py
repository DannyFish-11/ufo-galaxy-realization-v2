"""launcher/nodes.py — 节点生命周期的**命令面**

它解决什么
----------
``docs/CONFIGURATION_AUTHORITY.md`` 与 ``docs/guides/QUICKSTART.md`` 都明确让用户
跑 ``python system_manager.py``。而统一启动器的目标是"所有启动器收敛到
``main.py`` 一个入口，各自真实有效的要素保留、本体删掉" —— 那么**删本体之前，
必须先有等价的新命令**，否则文档一改用户就没路可走。

本模块就是那条新路：``python main.py nodes <command>``。

计划里写的替换命令是**不完整的**（订正记录）
------------------------------------------------
``docs/LAUNCHER_UNIFICATION_PLAN.md`` 的命令面表写的是::

    python system_manager.py  →  python main.py nodes <start|stop|status> [name]

对着 ``system_manager.main()`` 的真实 CLI 核过之后，这条有两处不对：

1. **少了两个命令**：真实的是 ``start | stop | status | monitor | report``。
   照着计划实现会**静默丢掉** ``monitor``（常驻监控循环）与 ``report``
   （JSON 报告）—— 用户敲惯的命令突然不认识，而"命令面替换完成"的说法却已经
   写进文档。
2. **参数形态错了**：真实的是 ``--group``（九个节点组 + ``all``）与
   ``--interval``，不是位置参数 ``[name]``。按 ``[name]`` 实现的话，
   ``python system_manager.py start --group core`` 这种用法直接没有对应写法。

所以这里按**实际存在的**表面等价迁移，而不是按计划里那一行。

为什么现在只搬命令面、不搬实现
------------------------------
``system_manager.py`` 有 676 行，且 ``health_monitor.py:50`` 有一条**真实的生产
import**（``from system_manager import SystemManager, NODES, NodeConfig``）。
把实现体和这条 import 一起动，是两件互相独立、各自都会出错的事。

这一步只保证"新命令能用、老命令的每种用法都有对应写法"，实现仍委托现有
``SystemManager``。实现体的搬迁与 ``system_manager.py`` 的删除留到步骤 8 ——
到那时新命令已经在文档里挂了一阵，出问题也有回退余地。

刻意的边界
----------
与 :mod:`launcher.env_check` / :mod:`launcher.deps` 同：本模块不自己实现节点
生命周期，也不重复一份节点表。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional, Sequence

#: ``system_manager.main()`` 实际接受的命令。**照抄**，不是重新设计 ——
#: 少一个就是静默丢掉一种用户敲惯的用法。
NODE_COMMANDS: Sequence[str] = ("start", "stop", "status", "monitor", "report")

#: ``--group`` 的取值。同样照抄。
NODE_GROUPS: Sequence[str] = (
    "core",
    "tools",
    "physical",
    "intelligence",
    "monitoring",
    "advanced",
    "orchestration",
    "multimodal",
    "academic",
    "all",
)

DEFAULT_GROUP = "all"
DEFAULT_INTERVAL = 30


def _load_manager() -> Any:
    """惰性取 ``SystemManager``。

    惰性是必须的：``import system_manager`` 会在模块顶层执行
    ``NODES = ConfigManager.load_nodes()`` —— 读配置文件。启动路径上
    ``main.py`` 的参数解析阶段不该为一个**没被调用**的子命令付这个代价。
    """
    from system_manager import SystemManager

    return SystemManager()


async def run_command(
    command: str,
    *,
    group: str = DEFAULT_GROUP,
    interval: int = DEFAULT_INTERVAL,
    manager: Optional[Any] = None,
) -> int:
    """执行一条节点生命周期命令，返回进程退出码。

    行为与 ``python system_manager.py <command>`` **逐条对应**，包括
    ``start`` 之后保持运行、``Ctrl+C`` 时停全部这条语义 —— 那不是可有可无的
    细节：``start`` 拉起的是子进程，命令一返回它们就会失去看护。

    Args:
        command:  :data:`NODE_COMMANDS` 之一。
        group:    :data:`NODE_GROUPS` 之一（仅 ``start`` 用）。
        interval: 监控间隔秒数（仅 ``monitor`` 用）。
        manager:  注入点，仅测试用；生产路径永远走 :func:`_load_manager`。
    """
    if command not in NODE_COMMANDS:
        raise ValueError(f"未知命令 {command!r}；可用：{', '.join(NODE_COMMANDS)}")
    if group not in NODE_GROUPS:
        raise ValueError(f"未知节点组 {group!r}；可用：{', '.join(NODE_GROUPS)}")

    mgr = manager if manager is not None else _load_manager()

    if command == "start":
        if group == DEFAULT_GROUP:
            await mgr.start_all()
        else:
            await mgr.start_group(group)
        # 保持运行 —— 与 system_manager.main() 同。拉起的是子进程，这里一返回
        # 就没人看着它们了。
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            mgr.stop_all()
        return 0

    if command == "stop":
        mgr.stop_all()
        return 0

    if command == "status":
        await mgr.check_all_nodes()
        return 0

    if command == "monitor":
        await mgr.monitor(interval)
        return 0

    # report
    report = await mgr.generate_report()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


def equivalent_legacy_command(command: str, *, group: str = DEFAULT_GROUP, interval: int = DEFAULT_INTERVAL) -> str:
    """给出这条新命令对应的**老**命令写法。

    存在的意义不是好看：文档迁移时要逐条对照，而"对照表"如果是手写的就会漂。
    这个函数让"每种老用法都有新写法"成为**可测**的（见
    ``tests/test_launcher_nodes.py``）。
    """
    parts: List[str] = ["python", "system_manager.py", command]
    if command == "start" and group != DEFAULT_GROUP:
        parts += ["--group", group]
    if command == "monitor" and interval != DEFAULT_INTERVAL:
        parts += ["--interval", str(interval)]
    return " ".join(parts)


__all__ = [
    "NODE_COMMANDS",
    "NODE_GROUPS",
    "DEFAULT_GROUP",
    "DEFAULT_INTERVAL",
    "run_command",
    "equivalent_legacy_command",
]
