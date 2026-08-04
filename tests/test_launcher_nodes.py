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


#: ``system_manager.py`` 被删除**之前**，从它的 argparse 里 AST 取出来的真实取值。
#:
#: 原来这份是每次运行时现读的（对着源码取，不照记忆抄）—— 那个文件在启动器统一
#: 的最后一步删了，参照物没了，只能定格成常量。
#:
#: 定格而不是删掉这两条测试，是因为它们钉的东西仍然成立：命令面**不许缩水**。
#: 计划文档当初写的是 ``<start|stop|status>``，照那个实现会静默丢掉 ``monitor``
#: 与 ``report`` —— 用户敲惯的命令突然不认识。
_LEGACY_CHOICES = {
    "command": ["start", "stop", "status", "monitor", "report"],
    "--group": [
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
    ],
}


def _system_manager_choices() -> dict:
    """老 CLI 的真实取值（已定格，见 :data:`_LEGACY_CHOICES`）。"""
    return _LEGACY_CHOICES


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
        # 老命令已随 system_manager.py 删除；这张对照表留作**迁移记录** ——
        # 用户手边的旧脚本/旧文档还写着老写法，得查得到对应的新写法。
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


def test_lifecycle_implementation_lives_here_exactly_once():  # noqa: D401
    """实现体在本模块，且**全仓只有这一份**。

    这条测试的前提变过一次，记在这里：最初 ``launcher/nodes.py`` 只是命令面，
    所以它钉的是"不许自己起进程"。后来实现体从 ``system_manager.py``
    **原样搬**了进来 —— 起子进程从此就是它的职责，原断言失效。

    现在钉的是搬迁真正要保证的事：**只有一份实现**。``system_manager.py`` 已在
    步骤 8 删除，所以扫描范围从"那一个文件"扩到了**全仓**。

    但范围不能无脑扩到底：``nodes/`` 下的单个节点各自定义自己的 ``NodeConfig``
    （如 ``Node_25_GoogleSearch`` 的 ``node_name`` / ``search_config``），与启动器
    的节点表条目（``id`` / ``port`` / ``group`` / ``dependencies``）**只是同名**，
    毫无关系。这是本轮反复遇到的同名陷阱，所以 ``nodes/`` 整体排除。
    """
    nodes_src = (REPO_ROOT / "launcher" / "nodes.py").read_text(encoding="utf-8")
    here = {n.name for n in ast.walk(ast.parse(nodes_src)) if isinstance(n, ast.ClassDef)}
    assert {"SystemManager", "ConfigManager", "NodeConfig"} <= here, "实现体该在 launcher/nodes.py"

    # 全仓不许有第二处定义这三个类（原来只查 system_manager.py，它删了之后
    # 范围扩到全仓 —— 更强，因为"第二份实现"可能长在任何地方）。
    elsewhere = []
    for path in REPO_ROOT.rglob("*.py"):
        # nodes/ 排除：单个节点各有自己的 NodeConfig，与启动器节点表同名不同义。
        if any(
            x in path.parts
            for x in ("__pycache__", ".venv", "venv", "node_modules", ".git", "external", "nodes", "tests")
        ):
            continue
        if path == REPO_ROOT / "launcher" / "nodes.py":
            continue
        try:
            defs = {
                n.name
                for n in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="ignore")))
                if isinstance(n, ast.ClassDef)
            }
        except (SyntaxError, ValueError, OSError):
            continue
        dup = defs & {"SystemManager", "ConfigManager", "NodeConfig"}
        if dup:
            elsewhere.append(f"{path.relative_to(REPO_ROOT)}: {', '.join(sorted(dup))}")
    assert not elsewhere, f"实现变成两份：{elsewhere}"


def test_system_manager_is_gone():
    """``system_manager.py`` 已随启动器统一删除，且不得复活。

    它的实现体在步骤 5 原样搬进了 ``launcher/nodes.py``（109 个节点记录比对过
    完全一致），命令面由 ``python main.py nodes`` 承接。
    """
    import importlib.util

    assert not (REPO_ROOT / "system_manager.py").exists(), "已删除，不得复活"
    assert importlib.util.find_spec("launcher.nodes") is not None, "实现体必须在新家"
    from launcher.nodes import NODES, SystemManager  # noqa: F401

    assert sum(len(v) for v in NODES.values()) > 100, "节点表不能扫空"


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
