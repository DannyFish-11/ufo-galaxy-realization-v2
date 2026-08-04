#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_launcher_env_check.py — 环境检查合并后的判据钉

``launcher/env_check.py`` 把两份互不知情的 Phase 0（``main.py`` 与
``launch_desktop.py``）合成一份。合并**不是取并集**，是逐行取更强的那个判据；
取谁不取谁是行为决定，所以每一条都在这里钉住，而不是留在注释里。

这个文件重点不在"覆盖率"，在于：**如果有人把某一行悄悄换回弱的那版，
必须有一条测试当场变红。**
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from launcher import env_check
from launcher.env_check import MIN_PYTHON, EnvReport, check_environment
from launcher.record import Column, Status

REPO_ROOT = Path(__file__).resolve().parent.parent


def _report(**overrides) -> EnvReport:
    """造一份"全绿"的报告，再按需覆盖 —— 让每条测试只表达它关心的那一维。"""
    base = dict(
        python_version="3.11.9",
        python_ok=True,
        python_executable="/usr/bin/python3",
        pip_ok=True,
        pip_version="24.0",
        env_exists=True,
        env_size_bytes=2048,
        api_keys_configured=2,
        npm_installed=True,
        npm_version="10.9.0",
        npm_path="/usr/bin/npm",
        node_installed=True,
        node_version="v22.0.0",
        electron_deps_ok=True,
        electron_probe="intact",
        ollama_installed=True,
        ollama_running=True,
        ollama_models=["qwen3:8b"],
    )
    base.update(overrides)
    return EnvReport(**base)


# ---------------------------------------------------------------------------
# 1. pip —— 取 launch_desktop 的判据（问当前解释器，不问 PATH）
# ---------------------------------------------------------------------------


def test_pip_probe_asks_the_running_interpreter_not_path(monkeypatch):
    """PATH 上完全没有 ``pip`` 时，``pip_ok`` 仍应为 True。

    这是两份判据里差别最实际的一处：``which("pip")`` 找到的可能是**另一个
    解释器**的 pip（venv 没激活、系统 pip 排在前面），它在不在都不代表
    **当前**解释器装得上包。对照实验：把 ``shutil.which`` 打成永远找不到，
    真判据不受影响。
    """
    monkeypatch.setattr(env_check.shutil, "which", lambda name: None)
    pip_ok, version = env_check._probe_pip()
    assert pip_ok is True, "pip 探测不该依赖 PATH 上有没有 pip 可执行文件"
    assert version, "应当解析出版本号"


def test_pip_probe_reports_failure_when_module_missing(monkeypatch):
    """自证：上面那条不是"永远返回 True"。"""

    class _Fail:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(env_check.subprocess, "run", lambda *a, **k: _Fail())
    assert env_check._probe_pip() == (False, "")


def test_pip_probe_command_targets_sys_executable(monkeypatch):
    """钉住命令形状本身：必须是 ``[sys.executable, "-m", "pip", ...]``。"""
    seen = {}

    class _R:
        returncode = 0
        stdout = "pip 24.0 from /x (python 3.11)"

    def _run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _R()

    monkeypatch.setattr(env_check.subprocess, "run", _run)
    env_check._probe_pip()
    assert seen["cmd"][:4] == [sys.executable, "-m", "pip", "--version"]


# ---------------------------------------------------------------------------
# 2. API Key —— 取 main.py 的判据（.env + runtime/secrets.env，过占位符）
# ---------------------------------------------------------------------------


def test_api_key_probe_counts_panel_saved_secrets(monkeypatch, tmp_path):
    """密钥只存在 ``runtime/secrets.env`` 里时也必须数得到。

    这是 ``launch_desktop`` 那份的真 bug：密钥经面板保存后被收敛进
    ``runtime/secrets.env``，**不再明文留在 .env**，而它只读 ``os.environ``，
    于是在密钥已正确保存的情况下永远报"未配置"。
    """
    monkeypatch.setattr(env_check, "ENV_FILE", tmp_path / "nonexistent.env")

    class _Store:
        def read_secrets(self):
            return {"OPENAI_API_KEY": "sk-real-value", "ANTHROPIC_API_KEY": "sk-ant-real"}

    monkeypatch.setitem(sys.modules, "core.config_store", type(sys)("core.config_store"))
    sys.modules["core.config_store"].get_config_store = lambda: _Store()

    assert env_check._probe_api_keys() == 2


def test_api_key_probe_rejects_placeholders(monkeypatch, tmp_path):
    """``.env`` 里没换掉的模板值不算已配置。"""
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_API_KEY=your_openai_api_key_here\n"
        "# COMMENTED_API_KEY=sk-xxx\n"
        "DEEPSEEK_API_KEY=sk-genuine\n"
        "NOT_A_SECRET=hello\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(env_check, "ENV_FILE", env)
    monkeypatch.setitem(sys.modules, "core.config_store", type(sys)("core.config_store"))
    sys.modules["core.config_store"].get_config_store = lambda: type("S", (), {"read_secrets": lambda s: {}})()

    # 只有 DEEPSEEK_API_KEY 算数：占位符被过滤、注释行被跳过、非密钥键不计
    assert env_check._probe_api_keys() == 1


def test_api_key_probe_does_not_double_count(monkeypatch, tmp_path):
    """同一个键在 .env 与 secrets.env 都出现时只算一个。"""
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-from-env\n", encoding="utf-8")
    monkeypatch.setattr(env_check, "ENV_FILE", env)
    monkeypatch.setitem(sys.modules, "core.config_store", type(sys)("core.config_store"))
    sys.modules["core.config_store"].get_config_store = lambda: type(
        "S", (), {"read_secrets": lambda s: {"OPENAI_API_KEY": "sk-from-store"}}
    )()
    assert env_check._probe_api_keys() == 1


def test_api_key_probe_never_exposes_values(monkeypatch, tmp_path):
    """探测结果只有**计数**，不含任何键值。

    ``EnvReport`` 里这一项就是个 ``int``，结构上没有地方放得下值 ——
    这条测试是把"结构上放不下"这件事显式钉住。
    """
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-super-secret-value\n", encoding="utf-8")
    monkeypatch.setattr(env_check, "ENV_FILE", env)
    monkeypatch.setitem(sys.modules, "core.config_store", type(sys)("core.config_store"))
    sys.modules["core.config_store"].get_config_store = lambda: type("S", (), {"read_secrets": lambda s: {}})()

    rep = _report(api_keys_configured=env_check._probe_api_keys())
    blob = repr(rep.to_status_dict()) + repr([s.to_dict() for s in rep.to_steps()])
    assert "sk-super-secret-value" not in blob


# ---------------------------------------------------------------------------
# 3. Electron —— 取 main.py 的判据（完整性，不是目录存在）
# ---------------------------------------------------------------------------


def test_electron_probe_detects_partial_install(monkeypatch, tmp_path):
    """``node_modules`` 在、但包残缺 → 必须判 False 且标 ``partial``。

    只看目录存在会漏掉 ``npm install`` 中途断掉的情况（``electron.cmd`` 存根
    在、``electron/cli.js`` 没了），那时会跳过安装、直接拉起 electron 然后崩。
    """
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(env_check, "ELECTRON_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "core.electron_launch_guard", type(sys)("core.electron_launch_guard"))
    sys.modules["core.electron_launch_guard"].electron_package_intact = lambda p: False

    ok, probe = env_check._probe_electron(npm_ok=True)
    assert ok is False
    assert probe == "partial", "残缺安装必须与「根本没装」区分开"


def test_electron_probe_missing_vs_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(env_check, "ELECTRON_DIR", tmp_path)  # 空目录，无 node_modules
    monkeypatch.setitem(sys.modules, "core.electron_launch_guard", type(sys)("core.electron_launch_guard"))
    sys.modules["core.electron_launch_guard"].electron_package_intact = lambda p: False
    assert env_check._probe_electron(npm_ok=True) == (False, "missing")


def test_electron_probe_marks_its_own_fallback(monkeypatch, tmp_path):
    """完整性检查不可用时退化看目录，但必须**如实标记**结论没那么硬。"""
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(env_check, "ELECTRON_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "core.electron_launch_guard", None)  # import 会炸
    ok, probe = env_check._probe_electron(npm_ok=True)
    assert ok is True
    assert probe == "fallback-dir-exists"


# ---------------------------------------------------------------------------
# 4. npm —— 取 main.py 的判据（绝对路径，Windows npm.cmd / PATHEXT）
# ---------------------------------------------------------------------------


def test_npm_probe_invokes_absolute_path_not_bare_name(monkeypatch):
    """必须用 ``which`` 出来的绝对路径调用。

    Windows 上 npm 实际是 ``npm.cmd``，``CreateProcess`` 不套用 ``PATHEXT`` ——
    传裸 ``"npm"`` 必抛 ``FileNotFoundError``，被 except 吞掉后打出一个没有
    版本号的 "✓ npm"。真机日志里"Node.js 有版本、npm 没版本"就是这个指纹。
    """
    seen = {}
    monkeypatch.setattr(env_check.shutil, "which", lambda n: r"C:\Program Files\nodejs\npm.cmd")

    class _R:
        returncode = 0
        stdout = "10.9.0\n"

    def _run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _R()

    monkeypatch.setattr(env_check.subprocess, "run", _run)
    ok, version, path = env_check._probe_npm()
    assert ok and version == "10.9.0"
    assert seen["cmd"][0] == r"C:\Program Files\nodejs\npm.cmd", "不能传裸 'npm'"
    assert path == r"C:\Program Files\nodejs\npm.cmd"


# ---------------------------------------------------------------------------
# 5. Ollama —— 取 launch_desktop 的判据（装没装 + 在不在跑 + 有哪些模型）
# ---------------------------------------------------------------------------


def test_ollama_probe_separates_installed_from_running(monkeypatch):
    """ ""「装了但没起来」和「没装」是完全不同的处境，不能都报成「未安装」。"""
    monkeypatch.setattr(env_check.shutil, "which", lambda n: "/usr/bin/ollama")

    class _R:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(env_check.subprocess, "run", lambda *a, **k: _R())
    installed, running, models = env_check._probe_ollama()
    assert (installed, running, models) == (True, False, [])


def test_ollama_probe_parses_model_list_and_skips_header(monkeypatch):
    monkeypatch.setattr(env_check.shutil, "which", lambda n: "/usr/bin/ollama")

    class _R:
        returncode = 0
        stdout = "NAME            ID       SIZE\nqwen3:8b        abc      5GB\nllama3:8b       def      4GB\n"

    monkeypatch.setattr(env_check.subprocess, "run", lambda *a, **k: _R())
    installed, running, models = env_check._probe_ollama()
    assert installed and running
    assert models == ["qwen3:8b", "llama3:8b"], "表头 NAME 不能被当成模型名"


# ---------------------------------------------------------------------------
# 6. Python 版本门 —— 取 launch_desktop 的判据（main.py 原本没有）
# ---------------------------------------------------------------------------


def test_python_floor_exists():
    assert MIN_PYTHON == (3, 10), "版本下限取自 launch_desktop 的 >= 3.10"


def test_python_floor_failure_short_circuits(monkeypatch):
    """版本不达标时提前返回，不再往下探测。

    理由：后面的探测要 import ``core.*``，在旧版本上可能因语法写法直接炸，
    那种崩溃会盖掉"你的 Python 太老了"这个唯一有用的信息。
    """
    monkeypatch.setattr(env_check, "_probe_python", lambda: ("3.9.18", False, "/usr/bin/python3.9"))
    called = []
    monkeypatch.setattr(env_check, "_probe_pip", lambda: called.append("pip") or (True, "1"))

    rep = check_environment()
    assert rep.python_ok is False
    assert rep.ready is False
    assert called == [], "版本门没过就不该继续探测"


def test_python_floor_failure_yields_actionable_step():
    steps = _report(python_ok=False, python_version="3.9.18").to_steps()
    py = next(s for s in steps if s.name == "Python")
    assert py.status is Status.FAILED
    assert py.hint and "3.10" in py.hint


# ---------------------------------------------------------------------------
# 7. ready 判据 —— .env 缺失不阻止启动
# ---------------------------------------------------------------------------


def test_ready_requires_python_pip_npm():
    assert _report().ready is True
    assert _report(python_ok=False).ready is False
    assert _report(pip_ok=False).ready is False
    assert _report(npm_installed=False).ready is False


def test_missing_env_file_does_not_block_startup():
    """``.env`` 不存在只降级，不拦启动。

    取 ``launch_desktop`` 的判断而非 ``main.py`` 的，理由是实证的：
    ``main.py`` 自己的 Phase 2 就有"``.env`` 不存在则从 ``.env.example``
    复制一份"的自愈。把一个**下一步就会自动补上**的东西算进"不能启动"，
    只会让启动在可以自愈的情况下白白终止。
    """
    rep = _report(env_exists=False, env_size_bytes=0)
    assert rep.ready is True
    step = next(s for s in rep.to_steps() if s.name == ".env 配置文件")
    assert step.status is Status.DEGRADED
    assert step.hint, "降级项要给出它会被怎么补上"


def test_missing_ollama_does_not_block_startup():
    """没有本地大脑仍可启动（走 API 主脑），只降级。"""
    assert _report(ollama_installed=False, ollama_running=False, ollama_models=[]).ready is True


# ---------------------------------------------------------------------------
# 8. 对两个老调用方的兼容：键必须是并集
# ---------------------------------------------------------------------------

#: ``main.py:phase2_ensure_deps`` 实际读的键（逐个 grep 出来的，不是猜的）。
_MAIN_PY_KEYS = {"pip_ok", "env_exists", "npm_installed", "electron_deps_ok", "ollama_installed"}
#: ``launch_desktop`` 侧实际读的键。
_LAUNCH_DESKTOP_KEYS = {
    "python_ok",
    "pip_ok",
    "env_exists",
    "has_api_key",
    "ollama_installed",
    "ollama_running",
    "model_available",
    "npm_installed",
    "electron_deps_ok",
    "ready",
}


def test_status_dict_covers_both_callers():
    """少给任何一个键，对应调用点就会静默走进 ``.get()`` 的 None 分支。

    那比报错更难查 —— 静默的 falsy 会让"自愈"以为该修，或者让"已就绪"以为
    没就绪，两个方向都错得无声无息。
    """
    keys = set(_report().to_status_dict())
    missing_main = _MAIN_PY_KEYS - keys
    missing_desktop = _LAUNCH_DESKTOP_KEYS - keys
    assert not missing_main, f"main.py 侧会读不到：{missing_main}"
    assert not missing_desktop, f"launch_desktop 侧会读不到：{missing_desktop}"


def test_status_dict_is_mutable_for_self_heal():
    """两侧都会在自愈成功后回写（如装完 npm 后置 True），这个行为必须保住。"""
    d = _report(npm_installed=False).to_status_dict()
    d["npm_installed"] = True
    assert d["npm_installed"] is True


# ---------------------------------------------------------------------------
# 9. 边界：事实层不打印
# ---------------------------------------------------------------------------


def test_env_check_module_never_prints():
    """本模块只产事实。打印一律经 ``launcher/ui.py`` 那个唯一咽喉。

    按 AST 判定而不是搜 ``"print("`` —— 后者会被文档里提到 print 的句子骗到。
    """
    tree = ast.parse((REPO_ROOT / "launcher" / "env_check.py").read_text(encoding="utf-8"))
    prints = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
    ]
    assert not prints, f"env_check 不该自己打印（行号：{prints}）"


def test_all_steps_are_env_column():
    assert all(s.column is Column.ENV for s in _report().to_steps())


def test_no_fabricated_hints_on_healthy_steps():
    """全绿时不许挂修复建议 —— ``hint`` 只在真降级/失败时才有意义。"""
    for s in _report().to_steps():
        if s.status is Status.OK:
            assert s.hint is None, f"{s.name} 正常却带了建议：{s.hint}"


# ---------------------------------------------------------------------------
# 10. 真机冒烟：真的跑一遍，别只测 mock
# ---------------------------------------------------------------------------


def test_check_environment_runs_for_real():
    """整套在本机真跑一次：不抛异常、字段类型对、Python 一定是 OK 的。

    没有这条，上面全部基于 monkeypatch 的测试可能整体建立在一个跑不起来的
    函数上。
    """
    rep = check_environment()
    assert isinstance(rep, EnvReport)
    assert rep.python_ok is True, "测试自己就跑在受支持的 Python 上"
    assert rep.python_version.count(".") == 2
    assert isinstance(rep.to_status_dict(), dict)
    steps = rep.to_steps()
    assert steps and all(isinstance(s.status, Status) for s in steps)
