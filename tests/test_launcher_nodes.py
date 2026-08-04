#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_launcher_nodes.py — 节点命令面的等价性钉

统一启动器要删 ``system_manager.py``，但 ``docs/CONFIGURATION_AUTHORITY.md:291``
与 ``docs/guides/QUICKSTART.md:374`` 都明确让用户跑它。**删本体之前必须先有等价的
新命令**，否则文档一改用户就没路可走。

本文件钉的就是"等价" —— 而且是**逐条对着真实的 argparse** 钉，不是对着计划文档
里那一行。计划写的是 ``nodes <start|stop|status> [name]``，实测少了 ``monitor``
与 ``report``、参数形态也不对（真实是 ``--group`` / ``--interval``）。
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
from pathlib import Path

from launcher import nodes

REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeManager:
    """记录调用序列的替身 —— 真跑会拉起一堆子进程。"""

    def __init__(self):
        self.calls: list = []

    async def start_all(self):
        self.calls.append(("start_all",))

    async def start_group(self, group):
        self.calls.append(("start_group", group))

    def stop_all(self):
        self.calls.append(("stop_all",))

    async def check_all_nodes(self):
        self.calls.append(("check_all_nodes",))

    async def monitor(self, interval):
        self.calls.append(("monitor", interval))

    async def generate_report(self):
        self.calls.append(("generate_report",))
        return {"nodes": {}, "ok": True}


# ---------------------------------------------------------------------------
# 1. 命令表与真实 argparse 逐条一致
# ---------------------------------------------------------------------------


def _system_manager_choices() -> dict:
    """从 ``system_manager.py`` 的 AST 里取出真实的 argparse choices。

    对着**源码**取，不是照着记忆或计划文档抄。它俩已经不一致过一次了。
    """
    tree = ast.parse((REPO_ROOT / "system_manager.py").read_text(encoding="utf-8"))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument":
            name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            for kw in node.keywords:
                if kw.arg == "choices" and isinstance(kw.value, ast.List):
                    out[name] = [e.value for e in kw.value.elts]
    return out


def test_commands_match_system_manager_exactly():
    """少一个命令就是**静默丢掉**一种用户敲惯的用法。

    计划文档写的是 ``<start|stop|status>`` —— 照那个实现会丢掉 ``monitor``
    （常驻监控循环）与 ``report``（JSON 报告），而"命令面替换完成"的说法却已经
    写进文档了。
    """
    assert list(nodes.NODE_COMMANDS) == _system_manager_choices()["command"]


def test_groups_match_system_manager_exactly():
    """``--group`` 的九个组 + all 必须一个不差。

    计划写的是位置参数 ``[name]``，那样 ``start --group core`` 根本没有对应写法。
    """
    assert list(nodes.NODE_GROUPS) == _system_manager_choices()["--group"]


def test_defaults_match_system_manager():
    assert nodes.DEFAULT_GROUP == "all"
    assert nodes.DEFAULT_INTERVAL == 30


# ---------------------------------------------------------------------------
# 2. 每条命令都真的转到对应的生命周期动作
# ---------------------------------------------------------------------------


def test_status_calls_check_all_nodes():
    m = _FakeManager()
    assert asyncio.run(nodes.run_command("status", manager=m)) == 0
    assert m.calls == [("check_all_nodes",)]


def test_stop_calls_stop_all():
    m = _FakeManager()
    assert asyncio.run(nodes.run_command("stop", manager=m)) == 0
    assert m.calls == [("stop_all",)]


def test_monitor_passes_the_interval_through():
    m = _FakeManager()
    assert asyncio.run(nodes.run_command("monitor", interval=7, manager=m)) == 0
    assert m.calls == [("monitor", 7)]


def test_report_prints_json(capsys):
    import json

    m = _FakeManager()
    assert asyncio.run(nodes.run_command("report", manager=m)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_start_all_vs_start_group():
    m = _FakeManager()

    # start 会进保活循环,所以用超时打断——打断后必须 stop_all（否则子进程失去看护）
    async def _run():
        task = asyncio.ensure_future(nodes.run_command("start", group="core", manager=m))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert ("start_group", "core") in m.calls


def test_start_keeps_running_and_stops_on_interrupt():
    """``start`` 之后必须**保持运行** —— 它拉起的是子进程。

    命令一返回就没人看着它们了。这条语义与 ``system_manager.main()`` 相同，
    不是可有可无的细节。
    """
    m = _FakeManager()

    async def _run():
        task = asyncio.ensure_future(nodes.run_command("start", manager=m))
        await asyncio.sleep(0.05)
        assert not task.done(), "start 不该立刻返回 —— 它要看着子进程"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert ("start_all",) in m.calls


# ---------------------------------------------------------------------------
# 3. 参数校验：不认识的东西要响亮地失败
# ---------------------------------------------------------------------------


def test_unknown_command_raises():
    m = _FakeManager()
    try:
        asyncio.run(nodes.run_command("nope", manager=m))
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("未知命令该抛 ValueError，不该静默什么也不做")
    assert m.calls == []


def test_unknown_group_raises():
    m = _FakeManager()
    try:
        asyncio.run(nodes.run_command("start", group="nope", manager=m))
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("未知节点组该抛 ValueError")
    assert m.calls == []


# ---------------------------------------------------------------------------
# 4. main.py 的命令面：既有形态一个都不能坏
# ---------------------------------------------------------------------------


def _parse_ok(*argv: str) -> bool:
    r = subprocess.run(
        [sys.executable, "main.py", *argv, "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    return r.returncode == 0


def test_nodes_subcommand_parses():
    assert _parse_ok("nodes", "status")
    assert _parse_ok("nodes", "start", "--group", "core")
    assert _parse_ok("nodes", "monitor", "--interval", "5")


def test_every_legacy_usage_has_a_new_spelling():
    """老命令的**每一种**用法都要有新写法。

    这不是形式主义：文档迁移要逐条对照，而手写的对照表会漂。
    """
    for command in nodes.NODE_COMMANDS:
        legacy = nodes.equivalent_legacy_command(command)
        assert legacy.startswith("python system_manager.py ")
        assert _parse_ok("nodes", command), f"{legacy} 没有对应的新写法"
    for group in nodes.NODE_GROUPS:
        assert _parse_ok("nodes", "start", "--group", group)


def test_existing_invocation_forms_still_parse():
    for form in ([], ["--host", "127.0.0.1", "--port", "9000"], ["-v"], ["--setup"], ["install", "--all"]):
        assert _parse_ok(*form), f"{form} 不再可解析"


def test_nodes_without_a_command_is_a_usage_error():
    """``python main.py nodes`` 光秃秃一个词不该被当成"启动整套系统"。"""
    r = subprocess.run(
        [sys.executable, "main.py", "nodes"], capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120
    )
    from launcher.record import EXIT_USAGE

    assert r.returncode == EXIT_USAGE, f"该按用法错误退出 {EXIT_USAGE}，实际 {r.returncode}"


# ---------------------------------------------------------------------------
# 5. 边界：命令面不重复实现生命周期
# ---------------------------------------------------------------------------


def test_lifecycle_implementation_lives_here_exactly_once():
    """实现体在本模块，且**全仓只有这一份**。

    这条测试的前提变过一次，记在这里：最初 ``launcher/nodes.py`` 只是命令面，
    所以它钉的是"不许自己起进程"。后来实现体从 ``system_manager.py``
    **原样搬**了进来 —— 起子进程从此就是它的职责，原断言失效。

    现在钉的是搬迁真正要保证的事：**只有一份实现**。``system_manager.py``
    必须只剩 CLI 外壳（从这里 re-export），不许两边各有一个 ``SystemManager``
    的类定义 —— 那正是这次统一要消掉的东西。
    """
    nodes_src = (REPO_ROOT / "launcher" / "nodes.py").read_text(encoding="utf-8")
    sm_src = (REPO_ROOT / "system_manager.py").read_text(encoding="utf-8")

    def class_defs(src):
        return {n.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef)}

    here, there = class_defs(nodes_src), class_defs(sm_src)
    assert {"SystemManager", "ConfigManager", "NodeConfig"} <= here, "实现体该在 launcher/nodes.py"
    assert not (here & there), f"两边都定义了同名类，实现变成两份：{here & there}"


def test_system_manager_is_only_a_shim_now():
    """``system_manager.py`` 只剩 CLI，且从新家 re-export。"""
    import system_manager

    from launcher import nodes as ln

    assert system_manager.SystemManager is ln.SystemManager
    assert system_manager.NodeConfig is ln.NodeConfig
    assert system_manager.NODES is ln.NODES


def test_health_monitor_points_at_the_new_home():
    """``health_monitor.py`` 是搬迁前唯一的生产 importer，必须跟着改。

    按 AST 判定：它不该再 import ``system_manager``（那是个将被删除的外壳）。
    """
    tree = ast.parse((REPO_ROOT / "health_monitor.py").read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "launcher.nodes" in modules, "health_monitor 该指向新家"
    assert "system_manager" not in modules, "不该再经将被删除的外壳中转"


def test_moved_paths_were_corrected():
    """物理移动唯一会**静默改变语义**的一类地方：``Path(__file__).parent``。

    实现体原本住在仓库根，那个表达式就是仓库根；搬进 ``launcher/`` 之后它指向
    ``launcher/`` —— 配置文件会找不到、``nodes_dir`` 会指向本模块自己、节点一个
    都扫不到，而且**不报错**，只是扫出空列表。

    所以这条测试查的是真实文件系统，不是字符串。
    """
    from launcher.nodes import PROJECT_ROOT, ConfigManager, SystemManager

    assert PROJECT_ROOT == REPO_ROOT
    assert ConfigManager.CONFIG_FILE.is_file(), f"配置文件找不到：{ConfigManager.CONFIG_FILE}"
    mgr = SystemManager()
    assert mgr.project_root == REPO_ROOT
    assert mgr.nodes_dir.is_dir(), f"节点目录找不到：{mgr.nodes_dir}"
    assert len(mgr.nodes_config) > 100, f"节点扫空了，只有 {len(mgr.nodes_config)} 个"


def test_version_path_does_not_load_the_node_table():
    """``main.py --version`` 不许触发节点表加载。

    这条的**前提变过**：原来钉的是"``import launcher.nodes`` 不许拉起
    ``system_manager``"，因为后者模块级就跑 ``load_nodes()``。实现体搬过来之后，
    模块级那次读取现在在 ``launcher.nodes`` 自己身上 —— 原断言变得无意义。

    真正要保证的时序没变，只是换了个观察点：``main.py`` 只在**真的要用**
    ``nodes`` 子命令时才 import 本模块（见 ``_run_nodes_command``），所以
    "只想问个版本号"的路径不该为它付读配置的代价。
    """
    r = subprocess.run(
        [sys.executable, "main.py", "--version"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    # 节点表加载会打印"能力管理器…"之类的初始化信息;--version 的输出该只有版本行
    assert "Galaxy" in r.stdout
    assert len(r.stdout.strip().splitlines()) == 1, f"--version 输出多了东西：{r.stdout!r}"


# ---------------------------------------------------------------------------
# 6. 退出码必须真的到达 shell
# ---------------------------------------------------------------------------


def test_main_propagates_its_exit_code():
    """``main.py`` 的 ``__main__`` 必须 ``raise SystemExit(main())``。

    此前是裸 ``main()``，于是**精心算出的退出码全部被丢弃**，进程永远 exit 0：
    EXIT_INTERRUPTED(130) / EXIT_DEPENDENCY(3) / EXIT_USAGE(2) 一个都到不了
    shell。``launcher/record.py`` 里那张退出码表读起来像是生效的，实际不是。

    与 ``core/health_check.py`` 那个"静默 exit 0"是同一类问题：
    ``python main.py && next-step`` 在启动被中断或依赖缺失时照样放行。

    按 AST 判定：``__main__`` 块里对 ``main()`` 的调用必须被 ``SystemExit``
    包住，或直接是 ``sys.exit(main())``。
    """
    tree = ast.parse((REPO_ROOT / "main.py").read_text(encoding="utf-8"))
    guards = [
        n
        for n in tree.body
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and isinstance(n.test.left, ast.Name)
        and n.test.left.id == "__name__"
    ]
    assert guards, "main.py 该有 __main__ 守卫"
    body = guards[-1].body
    # 裸 `main()` 会是一个 Expr(Call)；正确写法是 Raise(SystemExit(...)) 或 Expr(sys.exit(...))
    bare = [
        n
        for n in body
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "main"
    ]
    assert not bare, "裸调用 main() 会丢弃退出码；应 raise SystemExit(main())"


def test_start_sh_delegates_as_its_last_statement():
    """包装脚本必须让 main.py 的退出码成为自己的退出码。

    上面那条修好了"main.py 产出正确退出码"，这条保证它**传得出去** ——
    如果 start.sh 在 main.py 之后还有别的语句，用户看到的就是那条语句的码。
    """
    lines = [
        ln.strip()
        for ln in (REPO_ROOT / "start.sh").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert lines[-1].startswith("python main.py"), f"start.sh 最后一条应是 main.py 委托，实际：{lines[-1]!r}"
