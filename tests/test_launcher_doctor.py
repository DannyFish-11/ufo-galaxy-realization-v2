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

import json
import shutil
import subprocess
import sys
from pathlib import Path

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


def test_ui_and_nodes_are_exempt_from_the_print_rule():
    """``ui`` 是那个咽喉本身；``nodes`` 搬来的实现体自带面向运维的彩色输出。

    自证：豁免名单不是"把所有报错的都塞进去"，而是有理由的两个。
    """
    import inspect

    src = inspect.getsource(doctor._check_no_bare_print_on_startup_path)
    assert 'exempt = {"ui", "nodes"}' in src, "豁免名单变了，理由要跟着更新"


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


def test_cli_runs_and_exits_zero_when_healthy():
    r = _run_doctor_cli()
    assert r.returncode == EXIT_OK, r.stdout[-1500:]
    assert "启动器体检" in r.stdout


def test_cli_json_output_is_machine_readable():
    r = _run_doctor_cli("--json")
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
    try:
        r = _run_doctor_cli()
        assert r.returncode == EXIT_DEPENDENCY, f"该以 {EXIT_DEPENDENCY} 退出，实际 {r.returncode}"
        assert "✗" in r.stdout or "模块齐全" in r.stdout
    finally:
        shutil.move(str(bak), str(src))
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
