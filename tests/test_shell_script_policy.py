"""`/script` 那条路的判定,以及「人确认」那一层真的接上了没有。

## 这个文件存在的理由

上一轮我把 PowerShell 的门禁描述成四层:argv[0] 分流 → cmdlet 白名单 → 元字符拒绝
→ 人确认。**第四层当时不存在** —— `needs_human` 只是 `PowerShellVerdict` 上的一个
字段,全仓没有任何地方读它。同一轮里还漏了 `execute_script`:它一次
`_is_command_safe` 都不调,于是前三层也有个平行绕过口。

两处都不会有任何症状:命令照常执行,日志里什么都没有。所以这里用测试钉住。
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

# uvicorn 只在节点的 __main__ 里用来起服务,和判定逻辑无关。
sys.modules.setdefault("uvicorn", types.ModuleType("uvicorn"))

from core.shell_script_policy import (  # noqa: E402
    DEFAULT_ALLOWED_INTERPRETERS,
    evaluate_script,
    interpreter_name,
)


# ── 解释器白名单 ─────────────────────────────────────────────────────────────
def test_powershell_is_not_a_script_interpreter():
    """把 PowerShell 当脚本解释器,等于把任意 PowerShell 从 stdin 灌进去。

    上一轮拒绝把 `powershell` 加进 argv[0] 白名单的论证是"通用解释器 = 万能钥匙"。
    那个论证在这个入口同样成立 —— 只在一个入口成立的安全论证不成立。
    """
    for name in ("powershell", "pwsh", "cmd"):
        assert name not in DEFAULT_ALLOWED_INTERPRETERS
        assert not evaluate_script(name, "whatever").allowed


def test_a_path_cannot_be_used_to_smuggle_a_banned_interpreter():
    """按 basename 比较,所以 `/usr/bin/../bin/pwsh` 不能绕过。"""
    assert not evaluate_script("/usr/bin/../bin/pwsh", "x").allowed
    assert not evaluate_script(r"C:\WINDOWS\System32\powershell.exe", "x").allowed


def test_interpreter_name_strips_paths_and_exe_on_both_platforms():
    assert interpreter_name("/usr/bin/python3") == "python3"
    assert interpreter_name(r"C:\Python\python.exe") == "python"
    assert interpreter_name('"/usr/bin/bash"') == "bash"
    assert interpreter_name("") == ""


def test_an_allowlisted_interpreter_passes():
    v = evaluate_script("/usr/bin/python3", "print(1)")
    assert v.allowed and v.interpreter == "python3"


def test_the_allowlist_can_be_extended_but_is_not_open_by_default(monkeypatch):
    assert not evaluate_script("perl", "x").allowed
    monkeypatch.setenv("GALAXY_SCRIPT_ALLOWED_INTERPRETERS", "perl")
    assert evaluate_script("perl", "x").allowed


def test_turning_the_allowlist_off_matches_the_node_wide_switch():
    """和 `GALAXY_SHELL_ALLOWLIST_MODE=off` 对齐:关掉之后退回纯黑名单。"""
    assert evaluate_script("powershell", "x", allowlist_enabled=False).allowed


# ── 正文黑名单 ───────────────────────────────────────────────────────────────
def test_the_body_is_scanned_against_the_nodes_own_blocklist():
    v = evaluate_script("bash", "echo hi\nrm  -rf /\n", blocked_patterns=["rm -rf /"])
    assert not v.allowed and v.matched_pattern == "rm -rf /"


def test_whitespace_variants_do_not_slip_past_the_blocklist():
    """`rm  -rf /`(双空格)、`rm\\t-rf /` 都要被同一条规则抓住。"""
    for body in ("rm  -rf /", "rm\t-rf /", "  rm   -rf   /  "):
        assert not evaluate_script("bash", body, blocked_patterns=["rm -rf /"]).allowed


def test_the_blocklist_is_applied_per_line_not_to_the_whole_blob():
    """逐行匹配,不把整篇拼成一行 —— 否则跨行的两条无关命令会被粘成一条假匹配。"""
    body = "echo rm\necho -rf /\n"
    assert evaluate_script("bash", body, blocked_patterns=["rm -rf /"]).allowed


def test_the_policy_does_not_carry_its_own_copy_of_the_blocklist():
    """黑名单由调用方注入。本模块再造一份必然和节点那份漂移。"""
    assert evaluate_script("bash", "rm -rf /").allowed, "不传 blocked_patterns 时不该凭空拦截"


# ── 判不了的东西必须问人 ─────────────────────────────────────────────────────
def test_every_verdict_demands_a_human():
    """静态判定一段任意脚本安不安全做不到,所以 needs_human 恒为 True。"""
    assert evaluate_script("bash", "echo hi").needs_human is True
    assert evaluate_script("powershell", "x").needs_human is True


# ── 接线:节点真的会用上面这些 ────────────────────────────────────────────────
@pytest.fixture
def node():
    import nodes.Node_122_Shell.main as n122

    return n122


def test_execute_script_actually_consults_the_policy(node, monkeypatch):
    """此前这里一道检查都没有 —— 实测 `_is_command_safe` 被调用 0 次。"""
    monkeypatch.setenv("GALAXY_SHELL_UNATTENDED", "1")  # 把人确认那层挪开,单看判定
    r = asyncio.run(node.shell_service.execute_script(node.ScriptRequest(script="x", interpreter="powershell")))
    assert r["success"] is False
    assert "Script blocked" in r["error"]


def test_a_script_needs_a_human_even_with_a_clean_interpreter_and_body(node, monkeypatch):
    """解释器和正文都干净,仍然要问人 —— 判定管不了"这一次这么用对不对"。"""
    monkeypatch.delenv("GALAXY_SHELL_UNATTENDED", raising=False)
    monkeypatch.setattr(node, "_human_approved", _never_approve)
    r = asyncio.run(node.shell_service.execute_script(node.ScriptRequest(script="print(1)", interpreter="python3")))
    assert r["success"] is False and "human approval" in r["error"]


def test_powershell_now_really_reaches_the_human_layer(node, monkeypatch):
    """`needs_human` 上一轮只是个字段。这条钉住它真的被读了。"""
    monkeypatch.delenv("GALAXY_SHELL_UNATTENDED", raising=False)
    asked = []

    async def _record(title, summary):
        asked.append((title, summary))
        return False

    monkeypatch.setattr(node, "_human_approved", _record)
    r = asyncio.run(node.shell_service.execute(node.ExecuteRequest(command="powershell -Command Get-Process")))
    assert asked, "PowerShell 调用没有触发人确认 —— 第四层又不存在了"
    assert r["success"] is False and "human approval" in r["error"]


def test_an_ordinary_command_is_not_dragged_into_the_human_loop(node, monkeypatch):
    """门禁只挡该挡的。把每条 `git status` 都弹给人,结果是这道闸被整个关掉。"""
    monkeypatch.delenv("GALAXY_SHELL_UNATTENDED", raising=False)
    asked = []

    async def _record(title, summary):
        asked.append(title)
        return False

    monkeypatch.setattr(node, "_human_approved", _record)
    assert asyncio.run(node.shell_service._needs_human_for("git status")) is False
    assert not asked


def test_no_reachable_device_denies_quickly_instead_of_burning_the_timeout(node, monkeypatch):
    """没人可问时立刻拒绝,不把超时等满。

    实测过:等满是 60 秒。无头部署每条命令卡一分钟会被当成节点坏了,
    然后有人去把这道闸关掉 —— 一个让人想绕过的门禁等于没有门禁。
    """
    monkeypatch.delenv("GALAXY_SHELL_UNATTENDED", raising=False)

    async def _no_devices():
        return []

    import core.interaction.pending_decision_registry as reg

    monkeypatch.setattr(reg, "_discover_target_devices", _no_devices)

    loop_took = asyncio.run(_timed(node._human_approved("t", "s")))
    assert loop_took[0] is False
    assert loop_took[1] < 5.0, f"没人可问却等了 {loop_took[1]:.1f}s"


def test_the_unattended_escape_hatch_is_explicit_and_loud(node, monkeypatch):
    """无头放行必须是显式设置的,不能是默认。"""
    monkeypatch.delenv("GALAXY_SHELL_UNATTENDED", raising=False)

    async def _no_devices():
        return []

    import core.interaction.pending_decision_registry as reg

    monkeypatch.setattr(reg, "_discover_target_devices", _no_devices)
    assert asyncio.run(node._human_approved("t", "s")) is False

    monkeypatch.setenv("GALAXY_SHELL_UNATTENDED", "1")
    assert asyncio.run(node._human_approved("t", "s")) is True


async def _never_approve(title, summary):
    return False


async def _timed(coro):
    loop = asyncio.get_running_loop()
    t = loop.time()
    out = await coro
    return out, loop.time() - t
