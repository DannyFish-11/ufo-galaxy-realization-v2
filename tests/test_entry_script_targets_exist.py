"""入口脚本引用的目标必须真实存在。

为什么要这道门
--------------
一次全仓核对抓出三处"引用了不存在的文件"，全都是**用户会踩到、而所有测试
都测不到**的那种：

* ``install_windows.ps1`` / ``install_taskscheduler.ps1`` 把开机自启的快捷方式
  指向仓库根的 ``galaxy_daemon.py`` —— 该文件在 ``daemon/`` 下。装完了守护
  进程起不来，报错是"找不到文件"，离真正原因很远。
* ``package.json`` 的 ``health`` 指向 ``scripts/health_check.py`` —— 不存在
  （真正的健康检查是 ``scripts/health_check.sh`` / ``.ps1``）。``npm run health``
  必崩。

这类 bug 的共同点：**它们活在测试跑不到的地方**（安装脚本、npm scripts、
计划任务），只有真机装一次才会发现。所以把"目标是否存在"这件事做成静态门。

刻意的边界
----------
只检查**结构性引用**（脚本要执行的文件、npm script 的目标），不检查注释和
文档里提到的路径 —— 后者提到已删除的东西往往是**有意的历史记录**
（见 ``entrypoint_role_contract.py`` 里 dashboard.backend.main 那条）。
把两者混为一谈会让这道门变成噪音源，噪音源最后都会被加豁免直到失效。
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# 1. package.json 的每个 script 目标
# ---------------------------------------------------------------------------


def _npm_script_targets() -> list[tuple[str, str, str]]:
    """返回 (script 名, 类型, 目标)。跳过 ``python -c`` 这种内联代码。"""
    data = json.loads((_ROOT / "package.json").read_text(encoding="utf-8"))
    out: list[tuple[str, str, str]] = []
    for name, cmd in data.get("scripts", {}).items():
        if re.search(r"python\s+-c\s", cmd):
            continue  # 内联代码，没有文件目标
        m = re.search(r"python\s+-m\s+([\w.]+)", cmd)
        if m:
            out.append((name, "module", m.group(1)))
            continue
        m = re.search(r"(?:python3?\s+|bash\s+|-File\s+)([\w./\\-]+\.(?:py|sh|ps1|bat))", cmd)
        if m:
            out.append((name, "file", m.group(1)))
    return out


@pytest.mark.parametrize("name,kind,target", _npm_script_targets(), ids=lambda v: str(v))
def test_npm_script_target_exists(name: str, kind: str, target: str) -> None:
    if kind == "module":
        import importlib.util

        assert importlib.util.find_spec(target) is not None, f"npm script {name!r} 指向不存在的模块 {target}"
    else:
        assert (_ROOT / target).is_file(), f"npm script {name!r} 指向不存在的文件 {target}"


def test_npm_scripts_were_actually_scanned() -> None:
    """自证：上面那条参数化不得因为解析不出目标而退化成零用例。"""
    assert len(_npm_script_targets()) >= 8, "解析出的 npm script 目标太少，正则大概率坏了"


# ---------------------------------------------------------------------------
# 2. 安装 / 计划任务脚本里要执行的 .py
# ---------------------------------------------------------------------------

#: 会去执行 python 文件的脚本。只列这些 —— 它们是"装完就跑"的路径，
#: 错了用户直接受影响，而 CI 里没有任何作业会真的执行它们。
_ENTRY_SCRIPTS = [
    "install_windows.ps1",
    "install_taskscheduler.ps1",
    "install.sh",
    "start.sh",
    "start.bat",
]


def _executed_py_refs(text: str) -> set[str]:
    """抽出脚本里**要执行**的 .py 路径，跳过注释/回显。

    只认两种形态：
      * ``python[3] <path>.py`` / ``-Execute ... -Argument "<path>.py"``
      * ``$ProjectRoot\\<path>.py`` 这类拼出来的实参
    """
    refs: set[str] = set()
    for m in re.finditer(r"\$ProjectRoot[\\/]([\w\\/.-]+\.py)", text):
        refs.add(m.group(1).replace("\\", "/"))
    for line in text.split("\n"):
        stripped = line.strip()
        # 回显/注释行不算结构性引用（Write-Host "python x.py" 只是给人看的提示）
        if stripped.startswith(("#", "::", "REM", "//")) or "Write-Host" in line or "echo " in line:
            continue
        for m in re.finditer(r'python3?\s+["\']?([\w\\/.-]+\.py)', line):
            refs.add(m.group(1).replace("\\", "/"))
    return refs


@pytest.mark.parametrize("script", _ENTRY_SCRIPTS)
def test_entry_script_python_targets_exist(script: str) -> None:
    p = _ROOT / script
    if not p.is_file():
        pytest.fail(f"入口脚本 {script} 不存在 —— 这本身就是问题（它被 README/安装流程引用）")
    missing = [r for r in _executed_py_refs(p.read_text(encoding="utf-8")) if not (_ROOT / r).is_file()]
    assert not missing, (
        f"{script} 要执行的这些 .py 不存在：{missing}。"
        f"这类错误只有真机装一次才会暴露，CI 里没有作业会执行安装脚本。"
    )


def test_the_guard_can_see_the_pattern_it_forbids() -> None:
    """自证：判据必须真能认出违规形态，否则这道门会恒真通过。"""
    bad = _executed_py_refs('$Shortcut.Arguments = "`"$ProjectRoot\\galaxy_daemon.py`""')
    assert "galaxy_daemon.py" in bad, "判据认不出 $ProjectRoot 拼路径的形态"
    assert not (
        _ROOT / "galaxy_daemon.py"
    ).is_file(), "仓库根出现了 galaxy_daemon.py —— 上面那条自证就失去意义了，请改用别的样例"
    ok = _executed_py_refs('# python nonexistent_example.py\nWrite-Host "python other.py"')
    assert not ok, f"注释与回显被误判为结构性引用：{ok}"
