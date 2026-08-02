"""
Node_122_Shell 命令准入策略测试（B3）
====================================

审查发现：该节点原本只有 ``BLOCKED_COMMANDS`` 黑名单，且是**子串匹配** ——

    if blocked.lower() in command_lower

于是 ``rm -rf /`` 拦得住，而 ``rm  -rf /``（双空格）、``rm\\t-rf /`` 拦不住。
黑名单的攻击面由"作者想到了多少种写法"决定，不由策略决定。

修复引入**可执行文件白名单**作为主防线（黑名单降为第二道），本文件把两者的
契约钉住：

* 白名单：只有 ``argv[0]`` 落在允许集合内才放行；``/bin/rm`` 不能靠绝对路径绕过。
* 黑名单：归一化空白后再匹配，堵掉上面那个双空格绕过。
* 两者是**与**的关系：白名单内的程序（如 ``python``）仍要过黑名单与元字符检查。
* 可配置：``GALAXY_SHELL_ALLOWED_COMMANDS`` 追加，``GALAXY_SHELL_ALLOWLIST_MODE=off`` 关闭。
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

NODE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def shell_mod():
    """按文件路径加载节点的 main.py，避免与仓库根 main.py 抢 ``main`` 这个名字。

    （顶层模块名劫持正是 tests/test_no_test_hijacks_top_level_module.py 守的问题，
    这里从一开始就用唯一模块名，不往 sys.modules 里塞 "main"。）
    """
    if str(NODE_DIR) not in sys.path:
        sys.path.insert(0, str(NODE_DIR))
    spec = importlib.util.spec_from_file_location("node122_shell_main", NODE_DIR / "main.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Node_122_Shell/main.py 无法加载（缺依赖）: {exc}")
    return module


@pytest.fixture
def executor(shell_mod):
    for name in ("ShellService", "ShellExecutor"):
        cls = getattr(shell_mod, name, None)
        if cls is not None:
            return cls()
    pytest.skip("未找到 ShellService/ShellExecutor")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GALAXY_SHELL_ALLOWED_COMMANDS", raising=False)
    monkeypatch.delenv("GALAXY_SHELL_ALLOWLIST_MODE", raising=False)


# ── 可执行名解析 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "command,expected",
    [
        ("git status", "git"),
        ("/usr/bin/git log --oneline", "git"),
        ("/bin/rm -rf /", "rm"),                       # 绝对路径不能绕过
        ("python3 -c 'print(1)'", "python3"),
        (r"C:\Python\python.exe script.py", "python"),  # .exe 后缀去掉
        ("", ""),
    ],
)
def test_executable_name_extraction(shell_mod, command, expected):
    assert shell_mod._executable_name(command) == expected


# ── 白名单主防线 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", ["git status", "ls -la", "python3 --version", "pytest -q"])
def test_allowlisted_commands_pass(executor, command):
    assert executor._is_command_safe(command, shell_mode=False) is True


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ./build",       # rm 刻意不在默认白名单里
        "mkfs.ext4 /dev/sda",
        "sudo systemctl stop x",
        "chown root:root /etc",
        "some-random-binary --flag",
    ],
)
def test_non_allowlisted_commands_blocked(executor, command):
    assert executor._is_command_safe(command, shell_mode=False) is False


def test_absolute_path_cannot_bypass_allowlist(executor):
    """``/bin/rm`` 与 ``rm`` 必须同等对待 —— 这正是取 basename 的理由。"""
    assert executor._is_command_safe("/bin/rm -rf /tmp/x", shell_mode=False) is False


# ── 黑名单：修掉空白绕过 ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm  -rf /",        # 双空格 —— 修复前可绕过
        "rm\t-rf /",        # 制表符 —— 修复前可绕过
        "rm   -rf   /",
    ],
)
def test_whitespace_variants_of_blocked_command_are_all_blocked(executor, command):
    assert executor._is_command_safe(command, shell_mode=False) is False


def test_blocklist_still_applies_to_allowlisted_executables(executor, monkeypatch):
    """白名单与黑名单是**与**的关系：授权了 rm 也仍然拦 ``rm -rf /``。"""
    monkeypatch.setenv("GALAXY_SHELL_ALLOWED_COMMANDS", "rm")
    assert executor._is_command_safe("rm ./tmpfile", shell_mode=False) is True
    assert executor._is_command_safe("rm -rf /", shell_mode=False) is False


# ── Shell 元字符（既有行为，确认未被回归） ───────────────────────────────────

@pytest.mark.parametrize("command", ["git status && rm -rf /", "git log | sh", "git log; whoami", "git log `id`"])
def test_shell_metacharacters_blocked_in_shell_mode(executor, command):
    assert executor._is_command_safe(command, shell_mode=True) is False


def test_metacharacters_allowed_when_not_shell_mode(executor):
    """非 shell 模式下 argv 不经 shell 解释，元字符只是普通字符。"""
    assert executor._is_command_safe("git commit -m 'a && b'", shell_mode=False) is True


# ── 可配置性 ────────────────────────────────────────────────────────────────

def test_extra_allowed_commands_env_extends_allowlist(executor, monkeypatch):
    assert executor._is_command_safe("some-random-binary", shell_mode=False) is False
    monkeypatch.setenv("GALAXY_SHELL_ALLOWED_COMMANDS", "some-random-binary, another-one")
    assert executor._is_command_safe("some-random-binary", shell_mode=False) is True
    assert executor._is_command_safe("another-one --x", shell_mode=False) is True


def test_allowlist_can_be_disabled_for_legacy_behaviour(executor, monkeypatch):
    """关掉白名单后退回纯黑名单（旧行为），但黑名单本身仍然生效。"""
    monkeypatch.setenv("GALAXY_SHELL_ALLOWLIST_MODE", "off")
    assert executor._is_command_safe("some-random-binary", shell_mode=False) is True
    assert executor._is_command_safe("rm -rf /", shell_mode=False) is False


def test_empty_command_is_rejected(executor):
    assert executor._is_command_safe("", shell_mode=False) is False
    assert executor._is_command_safe("   ", shell_mode=False) is False
