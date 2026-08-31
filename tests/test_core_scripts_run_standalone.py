"""``core/`` 里带 ``__main__`` 守卫的模块,必须**直接执行**也能跑起来。

这条是补一次真实事故:把 ``core/`` 的上行依赖改走 ``core/upper_ports`` 时,给
``core/release_blocking_gate.py`` 加了一句模块级的 ``from core import upper_ports``。
单测和 import 全绿,但 CI 上那道 ``[BLOCKING]`` 闸挂了 ——

    python core/release_blocking_gate.py
    ModuleNotFoundError: No module named 'core'

原因很朴素:``python core/x.py`` 会把 ``core/`` 放进 ``sys.path[0]``,**仓库根不在
里面**,于是 ``from core import ...`` 找不到。之前那些上行依赖都写在函数体里,
延迟到调用时才执行,所以从没在导入期暴露过这件事。

教训不是"别加模块级导入",而是"**这类模块有两种跑法,测试只覆盖了一种**"。
所以这里按 ``__main__`` 守卫自动发现,不写死名单 —— 以后谁再给 ``core/`` 加一个
可执行模块,自动被这条盖住。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# 直接执行会产生副作用(起服务、连设备)因而不能在测试里跑的模块,连同理由。
# 名单要小;能跑的一律跑。
_SIDE_EFFECTING: dict[str, str] = {
    "core/device_status_api.py": "__main__ 里 uvicorn.run(...) 会真的起 HTTP 服务并阻塞",
}


def _ci_like_env() -> dict[str, str]:
    """CI 那种环境:**没有** ``PYTHONPATH``。

    这条是本文件最要紧的一处,单拎出来说明。``tests/conftest.py`` 里有一句::

        os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT))

    它给 pytest 进程设了 ``PYTHONPATH``,而 ``subprocess`` **会继承**。于是在 pytest
    里起的子进程,``from core import ...`` 总能找到 —— 哪怕被测模块自己根本立不住。

    第一版这条测试就栽在这儿:把修复撤掉之后它**照样绿**,而同一条命令在 pytest
    之外跑是 ``ModuleNotFoundError``。一条"撤掉修复也不红"的回归测试等于没有。

    CI 里那道闸是普通的 workflow step(``python core/release_blocking_gate.py``),
    环境里没有 ``PYTHONPATH``。所以这里必须把它摘掉,才是在测真实那条路。
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _has_main_guard(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in test.comparators)
        ):
            return True
    return False


def _executable_core_modules() -> list[str]:
    found = []
    for path in sorted((REPO / "core").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if _has_main_guard(path):
            found.append(str(path.relative_to(REPO)))
    return found


ALL_EXECUTABLE = _executable_core_modules()
RUNNABLE = [m for m in ALL_EXECUTABLE if m not in _SIDE_EFFECTING]


def test_discovery_actually_found_something():
    """自动发现不能悄悄退化成空集合 —— 那样下面的用例会全部"通过"。"""
    assert ALL_EXECUTABLE, "core/ 里一个带 __main__ 守卫的模块都没找到,发现逻辑坏了"


@pytest.mark.parametrize("module_path", RUNNABLE)
@pytest.mark.timeout(180)
def test_runs_as_a_bare_script(module_path):
    """``python core/x.py`` —— CI 里就是这么调的,所以这一种必须能跑。"""
    result = subprocess.run(
        [sys.executable, module_path],
        cwd=REPO,
        env=_ci_like_env(),
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert "ModuleNotFoundError" not in result.stderr, (
        f"{module_path} 直接执行时缺模块 —— 多半是模块级写了 `from core import ...`,"
        f"而 `python core/x.py` 的 sys.path[0] 是 core/ 不是仓库根:\n{result.stderr[-1500:]}"
    )
    assert result.returncode == 0, f"{module_path} 直接执行退出码 {result.returncode}\n{result.stderr[-1500:]}"


@pytest.mark.parametrize("module_path", RUNNABLE)
@pytest.mark.timeout(180)
def test_runs_as_a_module(module_path):
    """``python -m core.x`` —— 另一种跑法,两种都得成立。"""
    dotted = module_path[:-3].replace("/", ".")
    result = subprocess.run(
        [sys.executable, "-m", dotted],
        cwd=REPO,
        env=_ci_like_env(),
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert result.returncode == 0, f"python -m {dotted} 退出码 {result.returncode}\n{result.stderr[-1500:]}"


@pytest.mark.parametrize("module_path", sorted(_SIDE_EFFECTING))
def test_side_effecting_modules_still_import_cleanly(module_path):
    """跑不了的那几个,至少要保证**导入期**不缺模块。

    事故就发生在导入期(``from core import upper_ports`` 在模块顶层),所以这一条
    盖得住同一类问题;盖不住的只是 ``__main__`` 体内的错误。豁免名单里的模块也
    因此不是完全没人看。
    """
    dotted = module_path[:-3].replace("/", ".")
    result = subprocess.run(
        [sys.executable, "-c", f"import {dotted}"],
        cwd=REPO,
        env=_ci_like_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"import {dotted} 失败\n{result.stderr[-1500:]}"


@pytest.mark.parametrize("module_path", sorted(_SIDE_EFFECTING))
def test_exemptions_have_not_rotted(module_path):
    """豁免名单里的文件必须还存在、还带 ``__main__`` 守卫。"""
    assert (REPO / module_path).exists(), f"{module_path} 已不存在,请从 _SIDE_EFFECTING 里删掉"
    assert module_path in ALL_EXECUTABLE, f"{module_path} 已没有 __main__ 守卫,请从 _SIDE_EFFECTING 里删掉"


def test_the_harness_really_strips_pythonpath():
    """自检:上面那套净化必须真的把 ``PYTHONPATH`` 摘掉了。

    没有这条,``_ci_like_env`` 哪天被改坏(或 conftest 换个变量名注入),上面所有用例
    会重新变成"永远绿",而且没人会发现 —— 那正是第一版翻的车。
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import os,sys; print(repr(os.environ.get('PYTHONPATH')), file=sys.stderr)"],
        cwd=REPO,
        env=_ci_like_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert probe.stderr.strip() == "None", f"子进程仍然带着 PYTHONPATH: {probe.stderr.strip()}"
