#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_launcher_shell.py — 桌面壳诊断与七级自愈阶梯

``launcher/shell.py`` 把 ``unified_launcher.start_electron()`` 里那段 160 行内联
自愈流程重排成"可单独查询的事实 + 可逐级审计的阶梯"。**判据一条没改**，改的是
组织方式。

这个文件要保证的是两件此前做不到的事：

1. **不启动就能诊断**（``diagnose()`` 零副作用）；
2. **哪一级救活的、卡在第几级，事后答得上来**（``HealReport``）。

以及那条最容易被"顺手优化"掉的东西：**阶梯顺序**。清残留目录必须在任何
``npm install`` 之前 —— 顺序一换，"不完整→重装→ENOTEMPTY→仍不完整"的死循环
就回来了。
"""

from __future__ import annotations

from pathlib import Path

from launcher import shell

REPO_ROOT = Path(__file__).resolve().parent.parent


class _Proc:
    def __init__(self, rc=0, stderr="", stdout=""):
        self.returncode = rc
        self.stderr = stderr
        self.stdout = stdout


def _mk_electron(tmp_path: Path, *, node_modules=False, staging=0) -> Path:
    root = tmp_path / "electron"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    if node_modules:
        nm = root / "node_modules"
        nm.mkdir()
        (nm / ".bin").mkdir()
        for i in range(staging):
            (nm / f".somepkg-abc{i}def").mkdir()
    return root


# ---------------------------------------------------------------------------
# 1. 诊断：零副作用
# ---------------------------------------------------------------------------


def test_diagnose_has_no_side_effects(tmp_path, monkeypatch):
    """诊断不许动现场。

    这条不是洁癖：残留暂存目录是**第 3 级自愈**要处理的东西。如果诊断顺手把它们
    清了，那"我这台机器有没有 ENOTEMPTY 风险"这个问题就再也查不出来了 ——
    跑一次诊断就把证据抹掉。
    """
    root = _mk_electron(tmp_path, node_modules=True, staging=3)
    before = sorted(p.name for p in (root / "node_modules").iterdir())

    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    health = shell.diagnose(root)

    after = sorted(p.name for p in (root / "node_modules").iterdir())
    assert before == after, "诊断改动了 node_modules"
    assert health.staging_dirs == 3, "残留目录该被**看见**（但不清）"


def test_diagnose_reports_missing_node_modules(tmp_path, monkeypatch):
    root = _mk_electron(tmp_path)
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    h = shell.diagnose(root)
    assert h.electron_dir_exists and not h.node_modules_exists
    assert h.needs_install and not h.ready
    assert h.blocked is None, "缺依赖是可以自愈的，不算硬阻塞"


def test_no_npm_is_a_hard_block(tmp_path, monkeypatch):
    """npm 不在 PATH → 自愈装不了任何东西，必须如实说这是硬阻塞。

    与"缺依赖"区分开：后者能救，前者不能。混为一谈会让自愈白跑一轮再失败。
    """
    root = _mk_electron(tmp_path)
    monkeypatch.setattr(shell.shutil, "which", lambda n: None)
    h = shell.diagnose(root)
    assert h.blocked and "npm" in h.blocked


def test_missing_electron_dir_is_a_hard_block(tmp_path, monkeypatch):
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    h = shell.diagnose(tmp_path / "nope")
    assert h.blocked and "electron/" in h.blocked


def test_diagnose_runs_for_real_on_this_machine():
    """真机跑一次：不抛异常、字段类型对。

    没有这条，上面全部基于 tmp_path 的测试可能整体建立在一个跑不起来的函数上。
    """
    h = shell.diagnose()
    assert isinstance(h.to_dict(), dict)
    assert isinstance(h.ready, bool)


# ---------------------------------------------------------------------------
# 2. 阶梯顺序 —— 最容易被"顺手优化"掉的东西
# ---------------------------------------------------------------------------


def test_staging_purge_happens_before_any_install(tmp_path, monkeypatch):
    """清残留目录**必须**在第一次 ``npm install`` 之前。

    顺序一换，死循环就回来了："检测到不完整 → 重装 → ENOTEMPTY（暂存名已存在
    且非空）→ 仍不完整 → 重装…"，桌面覆盖层永远起不来。

    这条测试记录调用序列来钉顺序，而不是读代码 —— 读代码钉不住"运行时谁先谁后"。
    """
    root = _mk_electron(tmp_path, node_modules=True, staging=2)
    order = []

    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    monkeypatch.setitem(
        __import__("sys").modules, "core.electron_launch_guard", _guard_stub(order, intact_after_install=True)
    )
    guard = __import__("sys").modules["core.electron_launch_guard"]
    monkeypatch.setattr(
        shell.subprocess,
        "run",
        lambda *a, **k: (order.append("npm_install"), guard._state.__setitem__("installed", 1), _Proc(0))[2],
    )

    report = shell.self_heal(electron_dir=root)
    assert "purge" in order, "第 3 级没跑"
    assert order.index("purge") < order.index("npm_install"), f"顺序错了：{order}"
    assert report.ok


def _guard_stub(order, *, intact_after_install=True, stale_error=False, repair_ok=True):
    """替身 guard 模块。真跑会碰真实的 npm/electron。"""
    import sys as _sys
    import types

    m = types.ModuleType("core.electron_launch_guard")
    state = {"installed": 0}

    def purge(nm):
        order.append("purge")
        return 2

    def intact(d):
        return intact_after_install and state["installed"] > 0

    def stale(out):
        return stale_error

    def repair(d):
        order.append("repair")
        return repair_ok

    m.purge_npm_staging_dirs = purge
    m.electron_package_intact = intact
    m.is_npm_stale_dir_error = stale
    m.repair_electron_binary = repair
    m.electron_binary_fix_hint = lambda d="electron": "hint"
    m.already_running = lambda: False
    m._NPM_STAGING_RE = __import__("re").compile(r"^\.[^/\\]+-[A-Za-z0-9_]{6,}$")
    m._NPM_KEEP_DOTTED = frozenset({".bin"})
    m._state = state
    _sys.modules.pop("core.electron_launch_guard", None)
    return m


# ---------------------------------------------------------------------------
# 3. 每一级都可审计
# ---------------------------------------------------------------------------


def test_lock_held_short_circuits_at_level_zero(tmp_path, monkeypatch):
    """别的启动路径已经起过壳 → 0 级直接复用，不重复拉起。

    此前 4 条启动路径里只有 1 条写 ``.electron.pid``，其余 3 条互不知情。
    """
    root = _mk_electron(tmp_path)
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    monkeypatch.setattr(
        shell,
        "diagnose",
        lambda d=None: shell.ShellHealth(
            electron_dir_exists=True,
            npm_path="/usr/bin/npm",
            node_modules_exists=False,
            package_intact=False,
            local_binary=None,
            staging_dirs=0,
            lock_held=True,
            tauri_binary=None,
        ),
    )
    ran = []
    monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: ran.append(1))
    report = shell.self_heal(electron_dir=root)
    assert report.ok and report.healed_at == 0
    assert not ran, "锁有效时不该跑任何安装"


def test_hard_block_is_reported_not_retried(tmp_path, monkeypatch):
    root = _mk_electron(tmp_path)
    monkeypatch.setattr(shell.shutil, "which", lambda n: None)
    ran = []
    monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: ran.append(1))
    report = shell.self_heal(electron_dir=root)
    assert report.ok is False
    assert not ran, "硬阻塞下不该白跑一轮安装"
    assert any("硬阻塞" in s.detail for s in report.steps)


def test_network_failure_triggers_mirror_retry(tmp_path, monkeypatch):
    """官方源网络失败 → 换 npmmirror，而不是直接放弃桌面壳。"""
    root = _mk_electron(tmp_path)
    order = []
    calls = []
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    monkeypatch.setitem(__import__("sys").modules, "core.electron_launch_guard", _guard_stub(order))

    def _run(cmd, **k):
        calls.append(cmd)
        if len(calls) == 1:
            return _Proc(1, stderr="npm error ECONNRESET fetch failed")
        order.append("npm_install")
        return _Proc(0)

    monkeypatch.setattr(shell.subprocess, "run", _run)
    report = shell.self_heal(electron_dir=root)
    assert any(shell.NPM_MIRROR_REGISTRY in " ".join(c) for c in calls), "没换镜像重试"
    lvl4 = next(s for s in report.steps if s.level == 4)
    assert lvl4.applied and lvl4.ok


def test_non_network_failure_does_not_switch_mirror(tmp_path, monkeypatch):
    """自证：不是什么失败都换源 —— 换源对本地文件系统问题毫无用处。"""
    root = _mk_electron(tmp_path)
    order = []
    calls = []
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    monkeypatch.setitem(__import__("sys").modules, "core.electron_launch_guard", _guard_stub(order))
    monkeypatch.setattr(shell.subprocess, "run", lambda cmd, **k: (calls.append(cmd), _Proc(1, stderr="EACCES"))[1])
    report = shell.self_heal(electron_dir=root)
    assert not any(shell.NPM_MIRROR_REGISTRY in " ".join(c) for c in calls)
    lvl4 = next(s for s in report.steps if s.level == 4)
    assert not lvl4.applied
    assert "不像网络问题" in lvl4.detail
    assert report.ok is False


def test_stale_dir_error_triggers_full_rebuild(tmp_path, monkeypatch):
    """仍被残留目录挡住 → 整体重建 ``node_modules``。

    换镜像绕不过本地文件系统；``node_modules`` 完全可由 ``package.json`` 重建，
    删除无损。
    """
    root = _mk_electron(tmp_path, node_modules=True)
    order = []
    calls = []
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    monkeypatch.setitem(__import__("sys").modules, "core.electron_launch_guard", _guard_stub(order, stale_error=True))

    def _run(cmd, **k):
        calls.append(cmd)
        return _Proc(1, stderr="ENOTEMPTY") if len(calls) == 1 else _Proc(0)

    monkeypatch.setattr(shell.subprocess, "run", _run)
    rm = []
    monkeypatch.setattr(shell.shutil, "rmtree", lambda p, **k: rm.append(p))
    report = shell.self_heal(electron_dir=root)
    assert rm, "没有重建 node_modules"
    lvl5 = next(s for s in report.steps if s.level == 5)
    assert lvl5.applied and lvl5.ok


def test_binary_repair_runs_when_install_leaves_package_incomplete(tmp_path, monkeypatch):
    """装完仍不完整 → 单独补运行时二进制。

    根因：electron 包目录已存在时 npm install 会**跳过 postinstall**，不会补下
    ``dist/electron.exe`` —— 光重跑 install 永远修不好。
    """
    root = _mk_electron(tmp_path, node_modules=True)
    order = []
    guard = _guard_stub(order, intact_after_install=False, repair_ok=True)
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    monkeypatch.setitem(__import__("sys").modules, "core.electron_launch_guard", guard)
    monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: _Proc(0))
    report = shell.self_heal(electron_dir=root)
    assert "repair" in order, "第 6 级没跑"
    lvl6 = next(s for s in report.steps if s.level == 6)
    assert lvl6.applied


def test_report_says_which_level_healed_it(tmp_path, monkeypatch):
    """``healed_at`` 就是本模块存在的理由之一。

    此前"修好了是哪一步修的"只能靠翻散落的 logger.warning 猜。
    """
    root = _mk_electron(tmp_path)
    order = []
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    stub = _guard_stub(order)
    monkeypatch.setitem(__import__("sys").modules, "core.electron_launch_guard", stub)

    def _fake_install(*a, **k):
        # 假装真装了：建出 node_modules。
        # 少这一步 report.ok 会是 False —— 而那是**对的**：self_heal 不信各级的
        # 自我汇报，它重新 diagnose 一次再下结论。这里补上是为了让替身像真的。
        order.append("npm_install")
        (root / "node_modules").mkdir(exist_ok=True)
        stub._state["installed"] = 1
        return _Proc(0)

    monkeypatch.setattr(shell.subprocess, "run", _fake_install)
    report = shell.self_heal(electron_dir=root)
    assert report.ok
    assert report.healed_at == 1, f"该由第 1 级（首次安装）救活，实际 {report.healed_at}"
    assert report.to_dict()["steps"], "过程必须可序列化（要进 startup.json）"


def test_all_seven_levels_appear_even_when_install_fails(tmp_path, monkeypatch):
    """安装失败早退时，**每一级仍要在报告里出现**。

    否则第 6 级凭空消失，读报告的人分不清"跑了没用"和"根本没跑到" ——
    而这两者的下一步完全不同。

    真机复现过这个形态：本沙箱没有外网，L1/L4 都真跑并真失败，L5 判定"不是残留
    目录问题"跳过，L6 此前直接不出现。
    """
    root = _mk_electron(tmp_path)
    order = []
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    monkeypatch.setitem(__import__("sys").modules, "core.electron_launch_guard", _guard_stub(order))
    monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: _Proc(1, stderr="ECONNRESET"))
    report = shell.self_heal(electron_dir=root)
    assert report.ok is False
    levels = sorted({s.level for s in report.steps})
    assert levels == [0, 1, 3, 4, 5, 6], f"有级别没留痕：{levels}"
    for s in report.steps:
        assert s.applied or s.detail, f"第 {s.level} 级没跑却没说原因"


def test_every_ladder_level_is_recorded_even_when_skipped(tmp_path, monkeypatch):
    """没跑的级别也要留痕并写明原因 —— 否则"为什么没试第 5 级"答不上来。"""
    root = _mk_electron(tmp_path)
    order = []
    monkeypatch.setattr(shell.shutil, "which", lambda n: "/usr/bin/npm")
    monkeypatch.setitem(__import__("sys").modules, "core.electron_launch_guard", _guard_stub(order))
    monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: _Proc(0))
    report = shell.self_heal(electron_dir=root)
    for s in report.steps:
        if not s.applied:
            assert s.detail, f"第 {s.level} 级没跑却没说原因"


# ---------------------------------------------------------------------------
# 4. 渲染降级：与安装自愈正交的三档
# ---------------------------------------------------------------------------


def test_render_degradation_has_three_rungs():
    """默认硬件加速 → 软件渲染 → 不透明 basic 小窗。

    第三档保留功能、只丢透明特效，而不是彻底放弃桌面壳 —— 它是给"无独显
    Windows 上透明分层窗口本身出问题"准备的。
    """
    assert shell.render_env() == {}
    assert shell.render_env(force_software=True) == {"GALAXY_ELECTRON_GPU": "0"}
    basic = shell.render_env(basic_window=True)
    assert basic["GALAXY_ELECTRON_GPU"] == "0", "basic 档必须也关 GPU"
    assert basic["GALAXY_ELECTRON_BASIC"] == "1"


# ---------------------------------------------------------------------------
# 5. 双壳选择
# ---------------------------------------------------------------------------


def _health(**kw):
    base = dict(
        electron_dir_exists=True,
        npm_path="/usr/bin/npm",
        node_modules_exists=True,
        package_intact=True,
        local_binary="/x/electron",
        staging_dirs=0,
        lock_held=False,
        tauri_binary=None,
    )
    base.update(kw)
    return shell.ShellHealth(**base)


def test_tauri_preferred_when_binary_present(monkeypatch):
    monkeypatch.delenv("GALAXY_DESKTOP_SHELL", raising=False)
    assert shell.preferred_shell(_health(tauri_binary="/x/galaxy-shell")) == "tauri"


def test_falls_back_to_electron_without_tauri(monkeypatch):
    monkeypatch.delenv("GALAXY_DESKTOP_SHELL", raising=False)
    assert shell.preferred_shell(_health()) == "electron"


def test_env_var_forces_electron(monkeypatch):
    """``GALAXY_DESKTOP_SHELL=electron`` 强制回退 —— 这个开关原样保留。"""
    monkeypatch.setenv("GALAXY_DESKTOP_SHELL", "electron")
    assert shell.preferred_shell(_health(tauri_binary="/x/galaxy-shell")) == "electron"


def test_no_shell_at_all():
    assert shell.preferred_shell(_health(electron_dir_exists=False, tauri_binary=None)) == "none"


# ---------------------------------------------------------------------------
# 6. 边界
# ---------------------------------------------------------------------------


def test_shell_module_never_prints():
    import ast

    tree = ast.parse((REPO_ROOT / "launcher" / "shell.py").read_text(encoding="utf-8"))
    prints = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
    ]
    assert not prints, f"shell 不该自己打印（行号：{prints}）"


def test_primitives_are_delegated_not_reimplemented():
    """锁 / 完整性 / 暂存目录 / 二进制修复都该委托 ``core.electron_launch_guard``。

    那是它们的家。这里复制一份就等于又造了一处会漂的判据。
    """
    src = (REPO_ROOT / "launcher" / "shell.py").read_text(encoding="utf-8")
    for prim in (
        "electron_package_intact",
        "purge_npm_staging_dirs",
        "is_npm_stale_dir_error",
        "repair_electron_binary",
        "already_running",
    ):
        assert f"import {prim}" in src or f"{prim}," in src, f"{prim} 该从 guard 导入"


def test_helper_scripts_still_reference_the_lock():
    """``.electron.pid`` 这把锁是四条启动路径共享的，不能只有本模块认它。"""
    from core.electron_launch_guard import lock_path

    assert lock_path().endswith(".electron.pid")
