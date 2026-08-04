#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_launcher_deps.py — 依赖引导共享层的判据钉

``launcher/deps.py`` 把四份依赖引导（``main.py`` Phase 2 / ``install.py`` /
``install.sh`` / ``install_windows.ps1``，外加 ``launch_desktop`` Phase 1）真正
共用的东西合成一份：镜像轮换、重试、诚实上报，以及"这个项目需要什么"的单一清单。

合并的每一条都是行为决定，逐条钉在这里 —— 尤其是那些**看起来该改、其实不能改**
的地方（见 ``test_probe_uses_real_import_not_find_spec``）。
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from launcher import deps

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. pip 源候选：四份里只有一份有三个、一份有一个、两份一个都没有
# ---------------------------------------------------------------------------


def test_default_candidates_try_default_index_first():
    """默认源排第一 —— 尊重用户已配置的 pip.conf / 企业内网源。

    反过来（镜像优先）会让境外用户平白绕道国内镜像。
    """
    c = deps.pip_index_candidates()
    assert c[0] is None, "第一个候选必须是默认源"
    assert len(c) >= 3, "国内镜像回退至少两个（清华 / 阿里云），抗单点"


def test_galaxy_pip_index_override(monkeypatch):
    """``GALAXY_PIP_INDEX`` 沿用 install.sh 已有的约定，不另发明开关。"""
    monkeypatch.setenv("GALAXY_PIP_INDEX", "https://my.corp/simple")
    assert deps.pip_index_candidates() == ["https://my.corp/simple"]


def test_galaxy_pip_index_default_keyword(monkeypatch):
    monkeypatch.setenv("GALAXY_PIP_INDEX", "default")
    assert deps.pip_index_candidates() == [None]


def test_pip_install_rotates_through_candidates(monkeypatch):
    """默认源失败必须继续轮换，而不是就此认输。

    这是 ``install.py`` / ``install_windows.ps1`` 完全没有的一层：它们只打一枪，
    国内网络下基本必失败，且不会提示"换个源"。
    """
    seen = []

    class _R:
        def __init__(self, rc):
            self.returncode = rc
            self.stderr = "boom"
            self.stdout = ""

    def _run(cmd, **kw):
        seen.append(cmd)
        # 只有最后一个候选（阿里云）成功
        return _R(0 if "aliyun" in " ".join(cmd) else 1)

    monkeypatch.setattr(deps.subprocess, "run", _run)
    result = deps.pip_install(["somepkg"])
    assert result.ok is True
    assert result.attempts == 3, f"该轮换三个候选，实际 {result.attempts}"
    assert "aliyun" in (result.index_used or "")


def test_pip_install_reports_failure_honestly(monkeypatch):
    """全部候选失败就是失败，不吞。"""

    class _R:
        returncode = 1
        stderr = "ERROR: could not find a version"
        stdout = ""

    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: _R())
    result = deps.pip_install(["nope"], stream=False)
    assert result.ok is False
    assert result.attempts == len(deps.pip_index_candidates())
    assert "could not find" in result.stderr_tail


def test_pip_install_adds_trusted_host(monkeypatch):
    """用镜像源时要带 ``--trusted-host``。

    ``install.sh`` 有这一条，``main.py`` 原来没有 —— 某些企业网下镜像证书链
    不受信任时会卡死在这一步。合并取更强的那个。
    """
    seen = []

    class _R:
        returncode = 1
        stderr = ""
        stdout = ""

    monkeypatch.setattr(deps.subprocess, "run", lambda cmd, **k: (seen.append(cmd), _R())[1])
    deps.pip_install(["x"], stream=False)
    mirror_cmds = [c for c in seen if "-i" in c]
    assert mirror_cmds, "应当有用到镜像源的尝试"
    for cmd in mirror_cmds:
        assert "--trusted-host" in cmd, f"用镜像源却没带 --trusted-host: {cmd}"


def test_pip_install_targets_current_interpreter(monkeypatch):
    """必须是 ``sys.executable -m pip``，不是 PATH 上那个 pip。"""
    seen = []

    class _R:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr(deps.subprocess, "run", lambda cmd, **k: (seen.append(cmd), _R())[1])
    deps.pip_install(["x"])
    assert seen[0][:4] == [sys.executable, "-m", "pip", "install"]


def test_pip_install_empty_list_is_skip_not_success(monkeypatch):
    """没东西要装 → 标成"跳过"，不冒充"装成功"。"""
    called = []
    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: called.append(1))
    r = deps.pip_install([])
    assert r.ok is True and r.skipped_reason, "空清单该带跳过原因"
    assert not called, "空清单不该真去调 pip"


def test_pip_install_timeout_is_reported_not_raised(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pip", timeout=900)

    monkeypatch.setattr(deps.subprocess, "run", _boom)
    r = deps.pip_install(["x"], timeout=900)
    assert r.ok is False
    assert "超时" in r.stderr_tail


# ---------------------------------------------------------------------------
# 2. 探测：必须是真 import，不能"优化"成 find_spec
# ---------------------------------------------------------------------------


def test_probe_uses_real_import_not_find_spec():
    """``probe_missing`` 必须真的 import，不能用 ``importlib.util.find_spec``。

    这条看着像在钉一个实现细节，其实钉的是一个**已经修过一次的 bug**：
    ``sounddevice`` 的顶层 import 会一并加载 PortAudio 原生库，所以 import
    失败也能兜住"PortAudio 缺失"。换成 find_spec，"装了 sounddevice 但系统没
    PortAudio"的机器会被判成语音依赖齐全、横幅打 ✓，而麦克风根本打不开。

    按 AST 判定,注释里提到 find_spec 不算。
    """
    src = (REPO_ROOT / "launcher" / "deps.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "probe_missing")
    calls = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
    }
    assert "__import__" in calls, "probe_missing 必须真 import"
    assert "find_spec" not in calls, "不能用 find_spec —— 见本测试 docstring 的 PortAudio 反例"


def test_probe_detects_import_time_failure(monkeypatch):
    """能找到模块文件、但 import 时报错 → 仍算缺失。

    这就是 PortAudio 那类场景的可执行复现。
    """
    import types

    broken = types.ModuleType("galaxy_probe_broken")
    sys.modules.pop("galaxy_probe_broken", None)

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _fake_import(name, *a, **k):
        if name == "galaxy_probe_broken":
            raise OSError("PortAudio library not found")
        return real_import(name, *a, **k)

    monkeypatch.setitem(
        __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__, "__import__", _fake_import
    )
    assert deps.probe_missing({"galaxy_probe_broken": "galaxy-probe-broken"}) == ["galaxy-probe-broken"]
    del broken


def test_probe_finds_nothing_missing_for_installed_modules():
    assert deps.probe_missing({"json": "json", "os": "os"}) == []


def test_probe_reports_pip_name_not_module_name():
    """报出来的要是 **pip 名**（用户拿它去装），不是 import 名。"""
    missing = deps.probe_missing({"definitely_not_a_real_module_xyz": "some-pip-name"})
    assert missing == ["some-pip-name"]


# ---------------------------------------------------------------------------
# 3. 单一清单：启动期核心 / 语音
# ---------------------------------------------------------------------------


def test_core_modules_map_import_name_to_pip_name():
    """几个 import 名 ≠ pip 名的，必须映射对，否则装的是错的包。"""
    assert deps.CORE_MODULES["nats"] == "nats-py"
    assert deps.CORE_MODULES["edge_tts"] == "edge-tts"
    assert deps.CORE_MODULES["huggingface_hub"] == "huggingface-hub"
    assert deps.CORE_MODULES["opentelemetry.sdk"] == "opentelemetry-sdk"


def test_platform_core_modules_picks_the_right_event_loop(monkeypatch):
    monkeypatch.setattr(deps.os, "name", "nt")
    assert "winloop" in deps.platform_core_modules()
    assert "uvloop" not in deps.platform_core_modules()
    monkeypatch.setattr(deps.os, "name", "posix")
    assert "uvloop" in deps.platform_core_modules()
    assert "winloop" not in deps.platform_core_modules()


def test_voice_modules_include_sounddevice():
    """``sounddevice`` 曾从这份清单里漏掉。

    后果很具体：麦克风采集打不开，横幅却报"语音依赖 ✓"，把排查引到别处。
    """
    assert "sounddevice" in deps.VOICE_MODULES


def test_voice_is_not_part_of_core():
    """语音**不进**核心清单 —— 启动期不自动装它是刻意的决定。

    pip 装 faster-whisper 要拉几百 MB，卡住就把首启拖死；而语音只是可选的
    麦克风路径，缺了远程/文字路径照常可用。
    """
    assert not (set(deps.VOICE_MODULES) & set(deps.CORE_MODULES))


def test_main_py_no_longer_defines_its_own_module_list():
    """``main.py`` 不许再内嵌一份清单 —— 那正是四份漂移的来源。"""
    src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert '"nats": "nats-py"' not in src, "main.py 又内嵌了一份核心模块清单"
    assert '"pvporcupine": "pvporcupine"' not in src, "main.py 又内嵌了一份语音清单"


def test_main_py_no_longer_defines_its_own_pip_mirrors():
    src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert "_PIP_INDEX_CANDIDATES" not in src, "main.py 又内嵌了一份镜像候选表"


# ---------------------------------------------------------------------------
# 4. requirements 分层：跳过 ≠ 成功
# ---------------------------------------------------------------------------


def test_requirement_tiers_point_at_real_files():
    """三档都要真有对应文件，否则分层是纸面上的。"""
    for tier, rel in deps.REQUIREMENT_TIERS.items():
        assert (REPO_ROOT / rel).is_file(), f"{tier} 档指向的 {rel} 不存在"


def test_missing_requirements_file_is_skip_not_success(tmp_path, monkeypatch):
    """文件不存在 → ok=True 但带 skipped_reason。

    原 ``install.py`` 两种情况都返回 True，于是一个打错名字的档位会被报成
    "安装成功"。
    """
    called = []
    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: called.append(1))
    r = deps.install_requirements("core", root=tmp_path)
    assert r.ok is True
    assert r.skipped_reason, "跳过必须说明原因，不能与真装成功混为一谈"
    assert not called, "文件不存在就不该去调 pip"


def test_unknown_tier_is_an_error_not_a_skip():
    r = deps.install_requirements("nonexistent-tier")
    assert r.ok is False
    assert "未知档位" in r.stderr_tail


# ---------------------------------------------------------------------------
# 5. npm / electron 镜像
# ---------------------------------------------------------------------------


def test_npm_install_rotates_electron_mirrors(monkeypatch, tmp_path):
    seen = []

    class _R:
        def __init__(self, rc):
            self.returncode = rc

    def _run(cmd, **kw):
        seen.append(kw.get("env", {}).get("ELECTRON_MIRROR", ""))
        return _R(0 if len(seen) == 3 else 1)

    monkeypatch.setattr(deps.subprocess, "run", _run)
    r = deps.npm_install(tmp_path, npm_path="/usr/bin/npm")
    assert r.ok is True
    assert r.attempts == 3
    assert seen[0].startswith("https://npmmirror.com"), "第一候选该是国内镜像"
    assert seen[-1] == "", "最后一候选该回退官方源"


def test_npm_install_uses_absolute_path(monkeypatch, tmp_path):
    """Windows 上 npm 是 npm.cmd，CreateProcess 不套用 PATHEXT。"""
    seen = []

    class _R:
        returncode = 0

    monkeypatch.setattr(deps.subprocess, "run", lambda cmd, **k: (seen.append(cmd), _R())[1])
    deps.npm_install(tmp_path, npm_path=r"C:\nodejs\npm.cmd")
    assert seen[0][0] == r"C:\nodejs\npm.cmd"


def test_npm_install_without_npm_fails_clearly(monkeypatch, tmp_path):
    import shutil as _sh

    monkeypatch.setattr(_sh, "which", lambda n: None)
    r = deps.npm_install(tmp_path)
    assert r.ok is False
    assert "npm" in r.stderr_tail


def test_npm_flags_carry_weak_network_hardening():
    joined = " ".join(deps.NPM_NET_FLAGS)
    assert "--fetch-retries" in joined
    assert "--fetch-timeout" in joined


# ---------------------------------------------------------------------------
# 6. 边界：事实层不打印
# ---------------------------------------------------------------------------


def test_deps_module_never_prints():
    """安装过程要流式输出，但那是**子进程**在打，本模块自己不 print。

    打印一律经 ``launcher/ui.py``。按 AST 判定，文档里提到 print 不算。
    """
    tree = ast.parse((REPO_ROOT / "launcher" / "deps.py").read_text(encoding="utf-8"))
    prints = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
    ]
    assert not prints, f"deps 不该自己打印（行号：{prints}）"


def test_install_py_delegates_instead_of_reimplementing():
    """``install.py`` 不许再自己写一份 pip 调用。"""
    src = (REPO_ROOT / "install.py").read_text(encoding="utf-8")
    assert "from launcher import deps" in src
    assert '"-m", "pip"' not in src, "install.py 又自己拼 pip 命令了"
    assert "subprocess" not in ast.dump(ast.parse(src)), "install.py 不该再自己起子进程装东西"
