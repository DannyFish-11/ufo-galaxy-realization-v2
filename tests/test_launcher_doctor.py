#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_launcher_doctor.py — 启动器**自身**体检

``launcher/doctor.py`` 检查的不是"被启动的服务健不健康"（那是另外四个面的事），
而是：**这套统一启动器自己，还是不是完整、自洽、没退化的？**

统一启动器有两类特有的退化方式，**两类都不会让任何测试自然变红**：

1. 要素悄悄丢了 —— 搬迁时漏掉一条真机故障攒出来的判据，代码照跑，只是某个边角
   场景又回到了修复前；
2. 第二份实现又长出来了 —— 有人在 ``launcher/`` 之外重写一份，漂移从头开始。

所以体检本身也得有测试：**它必须真的会红**。一个永远绿的体检比没有体检更糟，
因为它给人"检查过了"的错觉。
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from launcher import doctor
from launcher.record import EXIT_DEPENDENCY, EXIT_OK, Status

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. 体检在健康的仓库上是绿的
# ---------------------------------------------------------------------------


def test_doctor_passes_on_a_healthy_repo():
    """静态部分必须全绿。

    刻意关掉 runtime 检查：那部分取决于**跑它的机器**装没装 Ollama / 有没有外网，
    让它参与判定会把体检变成"这台机器的体检"，而不是"启动器的体检"。
    """
    report = doctor.run_doctor(include_runtime=False)
    assert report.ok, "静态体检不该有 FAILED：\n" + "\n".join(
        f"  {s.name}: {s.value} {s.hint or ''}" for s in report.failed
    )


def test_doctor_report_is_serialisable():
    """报告要能进 ``startup.json`` / ``--json``。"""
    payload = doctor.run_doctor(include_runtime=False).to_dict()
    json.dumps(payload, ensure_ascii=False, default=str)
    assert payload["counts"]["ok"] > 0


# ---------------------------------------------------------------------------
# 2. 它必须真的会红 —— 每一项都做对照实验
# ---------------------------------------------------------------------------


def test_missing_module_turns_it_red(tmp_path, monkeypatch):
    """少一个必需模块 → FAILED。"""
    monkeypatch.setattr(doctor, "REQUIRED_MODULES", doctor.REQUIRED_MODULES + ("definitely_not_here",))
    report = doctor.run_doctor(include_runtime=False)
    assert not report.ok
    assert any("模块齐全" in s.name for s in report.failed)


def test_lost_element_turns_it_red(monkeypatch):
    """要素丢了 → FAILED。

    这是整件事最大的风险：搬迁时漏掉一条判据，代码照跑，只是某个边角场景又回到
    了修复前 —— **平时看不出来**。所以必须有一条检查能看出来。
    """
    fake = dict(doctor.PRESERVED_ELEMENTS)
    fake["某个绝不存在的要素"] = {"module": "launcher.shell", "needs": "__NEVER_PRESENT_MARKER__"}
    monkeypatch.setattr(doctor, "PRESERVED_ELEMENTS", fake)
    report = doctor.run_doctor(include_runtime=False)
    assert not report.ok
    lost = next(s for s in report.failed if "要素" in s.name)
    assert "某个绝不存在的要素" in (lost.hint or "")


def test_second_implementation_turns_it_red(monkeypatch):
    """``launcher/`` 之外重新**定义**权威符号 → FAILED。

    四个启动器当初就是这么长出来的：有人在别处又写了一份，两份互不知情，然后漂。
    """
    monkeypatch.setattr(
        doctor,
        "SINGLE_IMPLEMENTATION",
        # main.py 里确实定义了 ELECTRON_DIR（刻意的：路径所有权在调用方），
        # 拿它当"假想的权威符号"就能证明这条检查真的会红。
        {"launcher.shell": ["ELECTRON_DIR"]},
    )
    report = doctor.run_doctor(include_runtime=False)
    assert not report.ok
    dup = next(s for s in report.failed if "第二份实现" in s.name)
    assert "ELECTRON_DIR" in (dup.hint or "")


def test_bare_print_on_fact_layer_turns_it_red(tmp_path, monkeypatch):
    """事实层直接 ``print`` → FAILED。

    事实层只该产出事实，打印交给 ``launcher/ui.py`` 那个唯一咽喉 —— 否则同一份
    判断又会散成"只剩一行彩色文本"，那正是这次统一要消掉的老毛病。
    """
    fake_dir = tmp_path / "launcher"
    fake_dir.mkdir()
    (fake_dir / "__init__.py").write_text("", encoding="utf-8")
    (fake_dir / "env_check.py").write_text("print('oops')\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "LAUNCHER_DIR", fake_dir)
    report = doctor.DoctorReport()
    doctor._check_no_bare_print_on_startup_path(report)
    assert report.failed and "env_check" in (report.failed[0].hint or "")


def test_layers_are_two_explicit_tables_not_an_exemption_list():
    """ "谁可以打印"必须是**两张有判据的表**，不是一个越加越长的豁免名单。

    这条的前提被我自己的设计改进作废过一次：最初实现是
    ``exempt = {"ui", "nodes"}`` —— 一个豁免集合。搬进 ``services.py`` 之后它
    也要打印（启动横幅与就绪摘要是它的职责），如果继续往集合里加，规则迟早烂成
    "谁都可以打印"。

    现在改成 ``FACT_LAYER_MODULES``（产事实，给别人渲染）与
    ``PRESENTATION_MODULES``（产界面，给人看），判据是**这个模块的产出是什么**，
    而不是"它报没报错"。
    """
    assert set(doctor.FACT_LAYER_MODULES) & set(doctor.PRESENTATION_MODULES) == set(), "两表不许有交集"
    assert "record" in doctor.FACT_LAYER_MODULES, "事实层的核心必须在表里"
    assert "ui" in doctor.PRESENTATION_MODULES, "ui 就是那个输出咽喉"
    assert "services" in doctor.PRESENTATION_MODULES, "services 拥有启动横幅"


def test_unclassified_required_module_turns_it_red(monkeypatch):
    """新加的模块没归类 → FAILED。

    没有这条，新模块会既不被查也不被豁免，悄悄地既产事实又打印，分离就白做了。
    """
    monkeypatch.setattr(doctor, "FACT_LAYER_MODULES", ("record",))
    report = doctor.DoctorReport()
    doctor._check_fact_and_presentation_are_disjoint(report)
    assert report.failed and "没归类" in (report.failed[0].value or "")


def test_bare_main_call_turns_it_red(tmp_path, monkeypatch):
    """``__main__`` 里裸调用 ``main()`` → FAILED。

    此前就是这样，退出码全被丢弃、进程永远 exit 0。
    """
    fake = tmp_path / "main.py"
    fake.write_text("def main():\n    return 3\n\n\nif __name__ == '__main__':\n    main()\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "PROJECT_ROOT", tmp_path)
    report = doctor.DoctorReport()
    doctor._check_exit_code_propagates(report)
    assert report.failed


def test_real_main_py_passes_the_exit_code_check():
    report = doctor.DoctorReport()
    doctor._check_exit_code_propagates(report)
    assert not report.failed, "main.py 又变回裸调用 main() 了"


def _retired_check(tmp_path, monkeypatch, *, main_src: str, launcher_srcs: dict | None = None):
    """在一个假仓库上跑退役检查，返回报告。"""
    (tmp_path / "main.py").write_text(main_src, encoding="utf-8")
    launcher_dir = tmp_path / "launcher"
    launcher_dir.mkdir(exist_ok=True)
    for name, src in (launcher_srcs or {}).items():
        (launcher_dir / name).write_text(src, encoding="utf-8")
    monkeypatch.setattr(doctor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(doctor, "LAUNCHER_DIR", launcher_dir)
    report = doctor.DoctorReport()
    doctor._check_retired_launchers_are_gone(report)
    return report


def test_hardcoded_path_to_a_retired_launcher_turns_it_red(tmp_path, monkeypatch):
    """``PROJECT_ROOT / "unified_launcher.py"`` → FAILED。

    这不是假想的退化，是**真实踩到的**：``main.py`` 的入口契约校验里就硬编码着
    这一句，删掉本体之后它让每一次正常启动都停在"子入口缺失"，而
    ``python main.py doctor`` 走的是另一条分支，照样全绿。
    """
    report = _retired_check(
        tmp_path,
        monkeypatch,
        main_src=(
            "from pathlib import Path\n"
            "PROJECT_ROOT = Path('.')\n"
            "def main():\n"
            "    p = PROJECT_ROOT / 'unified_launcher.py'\n"
            "    return 0 if p.exists() else 1\n"
        ),
    )
    assert report.failed, "路径拼接指向已删除的启动器，体检必须变红"
    assert "unified_launcher.py" in (report.failed[0].hint or "")


def test_import_of_a_retired_launcher_turns_it_red(tmp_path, monkeypatch):
    """``from system_manager import ...`` → FAILED。"""
    report = _retired_check(
        tmp_path,
        monkeypatch,
        main_src="def main():\n    return 0\n",
        launcher_srcs={"nodes.py": "from system_manager import NodeManager\n"},
    )
    assert report.failed
    assert "system_manager" in (report.failed[0].hint or "")


def test_retired_body_reappearing_turns_it_red(tmp_path, monkeypatch):
    """本体文件又出现在仓库根 → FAILED。"""
    (tmp_path / "install.py").write_text("# 复活了\n", encoding="utf-8")
    report = _retired_check(tmp_path, monkeypatch, main_src="def main():\n    return 0\n")
    assert report.failed
    assert "install.py 仍在仓库根" in (report.failed[0].hint or "")


def test_migration_prose_is_not_flagged(tmp_path, monkeypatch):
    """散文提到老命令 → 仍是绿的。**这条钉的是分界，不是宽松。**

    第一版按"字符串里出现文件名"判，抓到的两处都是对的：argparse 帮助文本里的
    "替代 python system_manager.py"，和 ``equivalent_legacy_command()`` 那张
    老→新对照表。把它们判红只会逼人删掉迁移说明 —— 而删掉之后，用户就再也不知道
    自己那条老命令换成什么了。危险的是名字**流进文件系统/import**，不是被提到。
    """
    report = _retired_check(
        tmp_path,
        monkeypatch,
        main_src=(
            "'''本模块替代了 unified_launcher.py。'''\n"
            "HELP = 'nodes = 节点生命周期（替代 python system_manager.py）'\n"
            "def legacy(cmd):\n"
            # ``" ".join([...])` —— 裸名字看是 join，但它是字符串拼接不是路径拼接。
            "    return ' '.join(['python', 'system_manager.py', cmd])\n"
        ),
        launcher_srcs={"nodes.py": "# launch_desktop.py 的要素已搬到这里\n"},
    )
    assert not report.failed, f"散文不该判红：{[s.hint for s in report.failed]}"


def test_os_path_join_to_a_retired_launcher_still_turns_it_red(tmp_path, monkeypatch):
    """上一条放过了 ``str.join``，但 ``os.path.join`` 必须仍然判红。

    没有这一条，"放过 join"就会被人当成"join 一律安全"，路径拼接的另一半写法
    （``os.path.join(root, "unified_launcher.py")``）就成了盲区。
    """
    report = _retired_check(
        tmp_path,
        monkeypatch,
        main_src="import os\ndef main():\n    return os.path.join('.', 'unified_launcher.py')\n",
    )
    assert report.failed, "os.path.join 指向已删除的启动器，必须判红"


def test_real_repo_has_no_live_reference_to_the_retired_launchers():
    """真仓库上的活体断言 —— 四个本体删干净，且没人还当路径/模块用。"""
    report = doctor.DoctorReport()
    doctor._check_retired_launchers_are_gone(report)
    assert not report.failed, "\n".join(s.hint or "" for s in report.failed)


def test_broken_geometry_turns_it_red(monkeypatch):
    """值列不再由常量派生 → FAILED。

    版面对齐是用户直接看得见的东西，而"某处写了字面量"是最容易发生的退化。
    """
    import core.ascii_art as art

    monkeypatch.setattr(art, "VALUE_COL", 999)
    report = doctor.DoctorReport()
    doctor._check_layout_geometry(report)
    assert report.failed and "VALUE_COL" in (report.failed[0].value or "")


# ---------------------------------------------------------------------------
# 3. 要素清单本身要有意义
# ---------------------------------------------------------------------------


def test_preserved_elements_covers_all_four_launchers():
    """清单必须覆盖四个启动器各自的要素，不能只盯着一个。"""
    modules = {spec["module"] for spec in doctor.PRESERVED_ELEMENTS.values()}
    for expected in ("launcher.shell", "launcher.env_check", "launcher.deps", "launcher.nodes"):
        assert expected in modules, f"要素清单没覆盖 {expected}"
    assert len(doctor.PRESERVED_ELEMENTS) >= 25, "要素清单太短，多半是漏登记了"


def test_every_preserved_element_points_at_a_real_module():
    """清单里的模块路径必须真实存在 —— 否则那条检查永远查不到东西。"""
    for name, spec in doctor.PRESERVED_ELEMENTS.items():
        path = REPO_ROOT / Path(*spec["module"].split(".")).with_suffix(".py")
        assert path.is_file(), f"要素「{name}」指向不存在的模块 {spec['module']}"


# ---------------------------------------------------------------------------
# 4. CLI：python main.py doctor
# ---------------------------------------------------------------------------


def _run_doctor_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "main.py", "doctor", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )


def _require_healthy_machine(r: subprocess.CompletedProcess) -> None:
    """下面几条断言的前提是「这台机器是健康的」—— 但它们**不建立**这个前提。

    体检本身把"核心依赖缺失"判为不健康并退出 EXIT_DEPENDENCY,这是**正确行为**。
    于是在一台没装齐可选/核心依赖的机器上,``test_cli_runs_and_exits_zero_when_healthy``
    会红 —— 红的不是被测代码,是这台机器不满足用例名字里那个 "when healthy"。

    实测过:本仓容器缺 7 个核心包时这几条全红;把 ollama / nats-py / huggingface-hub /
    tqdm / edge-tts / opentelemetry-sdk / uvloop 装上之后,同一份代码 26 条全绿。

    所以这里不改断言、也不放宽判据,而是**把缺失的前提显式化**:机器不健康就跳过,
    并在跳过理由里写清楚缺什么。CI 装齐依赖,这几条照常跑;本地少装几个包的人不会
    被一条与自己改动无关的红挡住,而且一眼能看出该装什么。
    """
    if r.returncode == EXIT_OK:
        return
    missing = ""
    for line in r.stdout.splitlines():
        if "核心依赖" in line and "缺" in line:
            missing = line.strip()
            break
    pytest.skip(
        "本机体检未通过，跳过「健康时」这一组断言（被测代码无关）。"
        + (f" 体检报告：{missing}" if missing else f" 退出码={r.returncode}")
    )


def test_cli_runs_and_exits_zero_when_healthy():
    r = _run_doctor_cli()
    _require_healthy_machine(r)
    assert r.returncode == EXIT_OK, r.stdout[-1500:]
    assert "启动器体检" in r.stdout


def test_cli_json_output_is_machine_readable():
    r = _run_doctor_cli("--json")
    _require_healthy_machine(r)  # 见该函数说明：不健康的机器不满足本组前提
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["steps"]


def test_cli_exits_nonzero_when_a_module_goes_missing():
    """对照实验：真的把一个模块挪走，退出码必须变成 EXIT_DEPENDENCY。

    一个永远绿的体检比没有体检更糟 —— 它给人"检查过了"的错觉。所以这条测试
    真的动文件，而不是 monkeypatch。
    """
    src = REPO_ROOT / "launcher" / "shell.py"
    bak = REPO_ROOT / "launcher" / "_shell_doctor_probe.bak"
    shutil.move(str(src), str(bak))

    # try/finally 挡不住**信号**。跑测试的 shell 一超时被 SIGTERM,子进程 pytest
    # 跟着没了,finally 一行都不执行 —— 树里留下 .bak,而 launcher/shell.py 不见了。
    # 实测发生过一次,随后的 `git add -A` 把这个状态提交了进去(git 记成一次
    # rename),一个真实模块就这么从提交里消失了。
    #
    # 三层兜底,各挡各的:
    #   finally      —— 正常路径与断言失败
    #   atexit       —— 解释器正常退出前(含 pytest 内部中断)
    #   SIGTERM/INT  —— 被外部打断(超时、Ctrl-C、CI 取消)
    # SIGKILL 谁也挡不住,由 conftest 开跑前的自愈兜住。
    def _restore(*_args):
        if bak.exists() and not src.exists():
            shutil.move(str(bak), str(src))

    atexit.register(_restore)
    _prev_handlers = {}
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            _prev_handlers[_sig] = signal.signal(_sig, lambda s, f: (_restore(), os._exit(128 + s)))
        except (ValueError, OSError):
            pass  # 非主线程注册不了信号 —— 那就靠另外两层

    try:
        r = _run_doctor_cli()
        assert r.returncode == EXIT_DEPENDENCY, f"该以 {EXIT_DEPENDENCY} 退出，实际 {r.returncode}"
        assert "✗" in r.stdout or "模块齐全" in r.stdout
    finally:
        _restore()
        for _sig, _handler in _prev_handlers.items():
            try:
                signal.signal(_sig, _handler)
            except (ValueError, OSError):
                pass
    # 恢复后必须重新变绿 —— 证明上面的红是那次挪动造成的，不是别的
    assert _run_doctor_cli().returncode == EXIT_OK


def test_degraded_does_not_change_the_exit_code():
    """降级不该让 ``doctor && deploy`` 挂掉。

    桌面壳没装好、语音包没装是**可选**能力；环境不满足、模块 import 不了才必须挂。
    本沙箱恰好就有降级项（无外网装不上 Electron 依赖），所以这条是真在跑。
    """
    report = doctor.run_doctor()
    if not report.degraded:
        import pytest

        pytest.skip("本机没有降级项，这条判据在这里无法验证")
    assert report.ok is (not report.failed)
    r = _run_doctor_cli()
    assert r.returncode == EXIT_OK


# ---------------------------------------------------------------------------
# 5. 边界
# ---------------------------------------------------------------------------


def test_doctor_reuses_the_shipping_judgements_instead_of_its_own():
    """体检必须**复用** env_check / deps / shell / nodes 的判据。

    自带一套的话，它自己就成了"第二份实现" —— 正是它要防的那件事。
    """
    src = (REPO_ROOT / "launcher" / "doctor.py").read_text(encoding="utf-8")
    for mod in ("env_check", "deps", "shell", "nodes"):
        assert f"from launcher import {mod}" in src, f"doctor 该复用 launcher.{mod}"


def test_doctor_does_not_print():
    """呈现交给调用方（``main.py doctor`` 走 ui）。"""
    import ast

    tree = ast.parse((REPO_ROOT / "launcher" / "doctor.py").read_text(encoding="utf-8"))
    prints = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
    ]
    assert not prints, f"doctor 不该自己打印（行号：{prints}）"


def test_status_vocabulary_comes_from_record():
    """状态词汇用事实层的 :class:`~launcher.record.Status`，不另发明一套。"""
    report = doctor.run_doctor(include_runtime=False)
    assert all(isinstance(s.status, Status) for s in report.steps)
