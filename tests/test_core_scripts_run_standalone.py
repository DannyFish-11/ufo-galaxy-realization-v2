"""``core/`` 里带 ``__main__`` 守卫的模块,被**当脚本直接跑**时也得立得住。

这条补的是一次真实事故:把 ``core/`` 的上行依赖改走 ``core/upper_ports`` 时,给
``core/release_blocking_gate.py`` 加了一句模块级的 ``from core import upper_ports``。
单测和 import 全绿,但 CI 上那道 ``[BLOCKING]`` 闸挂了 ——

    python core/release_blocking_gate.py
    ModuleNotFoundError: No module named 'core'

原因很朴素:``python core/x.py`` 会把 ``core/`` 放进 ``sys.path[0]``,**仓库根不在
里面**。之前那些上行依赖都写在函数体里,延迟到调用时才执行,所以从没在导入期
暴露过这件事。

怎么测:只跑模块体,不跑 ``__main__``
------------------------------------
第一版是直接 ``subprocess`` 跑 ``python core/x.py``。它抓住了目标缺陷,但也**真的
执行了每个模块的 __main__**,于是在 CI 上炸了另一处:``core/microsoft_ufo_integration``
的 ``__main__`` 会去初始化 UI 自动化,在无头 runner 上 ``KeyError: 'DISPLAY'``。
本机没炸只是因为本机没装 pyautogui —— 纯属侥幸。

拿测试去跑任意程序的 ``__main__`` 本身就是错的:它们会起服务、连设备、阻塞。
而事故发生在**导入期**,所以只需要复现导入期:

    sys.path[0] = <仓库>/core        # 复刻 `python core/x.py` 的 sys.path 布局
    runpy.run_path(模块, run_name="…")  # 跑模块体,run_name 不是 __main__ → 跳过守卫

验证过这个探针两头都成立:撤掉引导它报 ``ModuleNotFoundError``,装上引导它退出 0,
而 ``microsoft_ufo_integration`` 在它下面安静通过(不再触发 UI 初始化)。

**完整执行**只留给 CI 真的当脚本跑的那几个 —— 从 workflow 里扫出来,不写死。
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# 复刻 `python core/x.py` 的 sys.path 布局,然后只执行模块体。
_PROBE = (
    "import os, runpy, sys; "
    "sys.path[0] = os.path.abspath({dirname!r}); "
    "runpy.run_path({path!r}, run_name='__standalone_probe__')"
)


def _ci_like_env() -> dict[str, str]:
    """CI 那种环境:**没有** ``PYTHONPATH``。

    这是本文件最要紧的一处。``tests/conftest.py`` 里有一句::

        os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT))

    它给 pytest 进程设了 ``PYTHONPATH``,而 ``subprocess`` **会继承**。于是在 pytest
    里起的子进程,``from core import ...`` 总能找到 —— 哪怕被测模块自己根本立不住。

    第一版就栽在这儿:把修复撤掉之后它**照样绿**。一条"撤掉修复也不红"的回归测试
    等于没有。CI 里那道闸是普通 workflow step,环境里没有这个变量。
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
    return [
        str(path.relative_to(REPO))
        for path in sorted((REPO / "core").rglob("*.py"))
        if "__pycache__" not in path.parts and _has_main_guard(path)
    ]


def _modules_ci_runs_as_scripts() -> list[str]:
    """从 workflow 里扫出 CI 真的用 ``python core/x.py`` 跑的模块。

    不写死名单:哪天有人在 workflow 里加一条 ``python core/新东西.py``,
    它自动进入"必须完整跑通"这一档。
    """
    pattern = re.compile(r"python\s+(core/[\w/]+\.py)")
    found: set[str] = set()
    for workflow in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        found.update(pattern.findall(workflow.read_text(encoding="utf-8", errors="replace")))
    return sorted(f for f in found if (REPO / f).exists())


ALL_EXECUTABLE = _executable_core_modules()
CI_RUNS = _modules_ci_runs_as_scripts()


def test_discovery_actually_found_something():
    """自动发现不能悄悄退化成空集合 —— 那样下面的用例会全部"通过"。"""
    assert ALL_EXECUTABLE, "core/ 里一个带 __main__ 守卫的模块都没找到,发现逻辑坏了"
    assert CI_RUNS, "workflow 里一条 `python core/*.py` 都没扫到,扫描逻辑坏了"


@pytest.mark.parametrize("module_path", ALL_EXECUTABLE)
@pytest.mark.timeout(180)
def test_module_body_loads_when_run_as_a_script(module_path):
    """按脚本的 ``sys.path`` 布局跑模块体 —— 导入期不许缺东西。

    只跑模块体、不跑 ``__main__``:事故发生在导入期,而执行 ``__main__`` 会起服务、
    连设备。见模块 docstring。
    """
    code = _PROBE.format(dirname=str((REPO / module_path).parent), path=module_path)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        env=_ci_like_env(),
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert "ModuleNotFoundError" not in result.stderr, (
        f"{module_path} 当脚本跑时缺模块 —— 多半是模块级写了 `from core import ...`,"
        f"而 `python core/x.py` 的 sys.path[0] 是 core/ 不是仓库根:\n{result.stderr[-1500:]}"
    )
    assert result.returncode == 0, f"{module_path} 模块体执行失败(退出码 {result.returncode})\n{result.stderr[-1500:]}"


@pytest.mark.parametrize("module_path", CI_RUNS)
@pytest.mark.timeout(300)
def test_modules_ci_executes_run_all_the_way_through(module_path):
    """CI 真的当脚本跑的那几个,要**完整跑完并退出 0**。

    这一档才是原事故的现场:``python core/release_blocking_gate.py``。
    """
    result = subprocess.run(
        [sys.executable, module_path],
        cwd=REPO,
        env=_ci_like_env(),
        capture_output=True,
        text=True,
        timeout=280,
    )
    assert result.returncode == 0, f"{module_path} 直接执行退出码 {result.returncode}\n{result.stderr[-2000:]}"


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


def test_the_probe_would_catch_a_missing_bootstrap(tmp_path):
    """自检之二:证明这个探针**确实**抓得住那类缺陷。

    临时造一个"模块级 import core、且没有引导"的文件,探针必须报
    ``ModuleNotFoundError``。没有这条,探针哪天退化成"什么都不执行"也没人知道。
    """
    victim = REPO / "core" / "_probe_victim_tmp.py"
    victim.write_text("from core import upper_ports  # noqa: F401\n", encoding="utf-8")
    try:
        code = _PROBE.format(dirname=str(REPO / "core"), path=f"core/{victim.name}")
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO,
            env=_ci_like_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
        assert "ModuleNotFoundError" in result.stderr, f"探针没抓住:\n{result.stderr[-800:]}"
    finally:
        victim.unlink(missing_ok=True)
