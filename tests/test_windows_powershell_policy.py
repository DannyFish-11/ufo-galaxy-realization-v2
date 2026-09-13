"""PowerShell 的白名单必须在 cmdlet 那一层,不能在 argv[0] 那一层。

`Node_122_Shell` 的白名单按**程序名**授权 —— 对 `git` / `ls` 有效,因为程序本身
决定了它能做什么。但 `powershell -Command <任意字符串>` 是**通用解释器**:
把它加进 argv[0] 白名单,等于给了一把万能钥匙,白名单外的每个程序都能被它调起来。

这组测试钉的就是这件事,以及"允许的 cmdlet 后面不许再接别的东西"。
"""

from __future__ import annotations

import pytest

from core.windows_powershell_policy import (
    DEFAULT_ALLOWED_CMDLETS,
    PowerShellVerdict,
    allowed_cmdlets,
    evaluate,
    is_powershell,
)


# ── 识别解释器 ────────────────────────────────────────────────────────────────
def test_recognises_the_three_interpreter_names():
    for name in ("powershell", "pwsh", "PowerShell.exe", "PWSH.EXE", "powershell_ise"):
        assert is_powershell(name) is True, name


def test_a_normal_program_is_not_powershell():
    for name in ("git", "python", "cmd", "bash"):
        assert is_powershell(name) is False, name


def test_non_powershell_argv0_is_refused_here():
    # 本模块只管 PowerShell。别的程序由 Node_122 的 argv[0] 白名单管。
    v = evaluate(["git", "-Command", "Get-Process"])
    assert v.allowed is False and "不是 PowerShell" in v.reason


# ── 白名单在 cmdlet 层 ────────────────────────────────────────────────────────
def test_an_allowlisted_cmdlet_passes():
    v = evaluate(["powershell", "-NoProfile", "-Command", "Get-Process"])
    assert v.allowed is True and v.cmdlet == "Get-Process"


def test_a_write_cmdlet_is_not_in_the_default_allowlist():
    """默认只给只读。写操作要显式授权,和 Node_122 默认不含 rm/mv/dd 同一条原则。"""
    for cmdlet in ("Remove-Item", "Stop-Process", "Set-ItemProperty", "New-Item", "Start-Process"):
        v = evaluate(["powershell", "-Command", cmdlet])
        assert v.allowed is False, cmdlet
        assert "白名单" in v.reason


def test_invoke_expression_is_not_allowed():
    """Invoke-Expression / Invoke-Command 本身就是另一把万能钥匙。"""
    for cmdlet in ("Invoke-Expression", "Invoke-Command"):
        assert evaluate(["powershell", "-Command", cmdlet]).allowed is False, cmdlet


def test_the_allowlist_is_extendable_by_env(monkeypatch):
    assert evaluate(["powershell", "-Command", "Stop-Service"]).allowed is False
    monkeypatch.setenv("GALAXY_PS_ALLOWED_CMDLETS", "Stop-Service")
    assert "stop-service" in allowed_cmdlets()
    assert evaluate(["powershell", "-Command", "Stop-Service"]).allowed is True


def test_env_extension_adds_it_never_replaces_the_default(monkeypatch):
    monkeypatch.setenv("GALAXY_PS_ALLOWED_CMDLETS", "Stop-Service")
    assert DEFAULT_ALLOWED_CMDLETS <= allowed_cmdlets(), "环境变量不该把默认集合挤掉"


# ── 元字符:允许的 cmdlet 后面不许再接东西 ─────────────────────────────────────
@pytest.mark.parametrize(
    "payload",
    [
        "Get-Process; Remove-Item C:\\",
        "Get-Process | Stop-Process",
        "Get-Process && shutdown",
        "Get-Process `n whoami",
        "Get-Date $(whoami)",
        "Get-Content x > y",
    ],
)
def test_a_metacharacter_after_an_allowed_cmdlet_is_refused(payload):
    """`Get-Process; Remove-Item C:\\` —— 前半截允许,后半截不允许。

    只看第一个词的白名单会放行整条。这一道就是为这个存在的。
    """
    v = evaluate(["powershell", "-Command", payload])
    assert v.allowed is False
    assert "元字符" in v.reason


def test_metacharacters_anywhere_in_argv_are_caught_not_just_in_command():
    v = evaluate(["powershell", "-EncodedCommand", "x;y", "-Command", "Get-Process"])
    assert v.allowed is False and "元字符" in v.reason


# ── fail-closed ───────────────────────────────────────────────────────────────
def test_empty_is_refused():
    for argv in (None, [], ["", "  "]):
        assert evaluate(argv).allowed is False


def test_no_command_flag_means_no_object_to_authorise():
    v = evaluate(["powershell", "-NoProfile"])
    assert v.allowed is False and "拿不到要授权的对象" in v.reason


def test_a_script_path_is_not_a_cmdlet():
    # C:\x.ps1 不是 Verb-Noun,拿不准一律拒。
    v = evaluate(["powershell", "-Command", "C:\\x.ps1"])
    assert v.allowed is False


def test_an_alias_is_not_a_cmdlet():
    # iex 是 Invoke-Expression 的别名 —— 形状不对,拒。
    assert evaluate(["powershell", "-Command", "iex"]).allowed is False


# ── 人确认这一位不许被档位关掉 ────────────────────────────────────────────────
def test_needs_human_is_always_true_even_when_allowed():
    """autonomy_policy 的 AUTONOMOUS 档会跳过逐步审批。

    那对点击、输入是合理的;对一个通用解释器不是 —— 一次不走运的命令生成,
    和一次点错按钮,代价差着数量级。所以这一位不看档位。
    """
    v = evaluate(["powershell", "-Command", "Get-Process"])
    assert v.allowed is True and v.needs_human is True


def test_needs_human_is_true_on_refusal_too():
    assert evaluate(["powershell", "-Command", "Remove-Item"]).needs_human is True


def test_verdict_is_frozen():
    v = evaluate(["powershell", "-Command", "Get-Process"])
    with pytest.raises(Exception):
        v.allowed = False  # type: ignore[misc]


def test_verdict_dict_carries_the_reason():
    d = evaluate(["powershell", "-Command", "Remove-Item"]).to_dict()
    assert d["allowed"] is False and d["reason"] and d["needs_human"] is True


# ── 接线:Node_122 真的调了这套策略 ───────────────────────────────────────────
def _node122_src() -> str:
    import pathlib

    for cand in (pathlib.Path("."), pathlib.Path("..")):
        f = cand / "nodes" / "Node_122_Shell" / "main.py"
        if f.is_file():
            return f.read_text(encoding="utf-8")
    raise AssertionError("找不到 Node_122_Shell/main.py —— 这里刻意不跳过")


def test_node122_routes_powershell_to_the_cmdlet_policy():
    """策略再对,没人调也是永远不生效。"""
    src = _node122_src()
    assert "_is_powershell_invocation(exe)" in src, "Node_122 的白名单没有把 PowerShell 分流出去"
    assert "core.windows_powershell_policy" in src, "没有引用这套策略"


def test_powershell_is_not_in_node122_argv0_allowlist():
    """`powershell` 绝不能进 argv[0] 白名单 —— 那是万能钥匙。"""
    src = _node122_src()
    import re

    block = src[src.index("_DEFAULT_ALLOWED_COMMANDS") : src.index("def _allowlist_enabled")]
    names = set(re.findall(r'"([a-z0-9_.-]+)"', block))
    for banned in ("powershell", "pwsh", "cmd", "sh", "bash", "zsh"):
        assert banned not in names, f"{banned} 进了 argv[0] 白名单 —— 白名单当场失效"


def test_the_policy_falls_closed_when_unavailable():
    """策略模块读不到时拒绝执行,而不是放行。"""
    src = _node122_src()
    seg = src[src.index("def _powershell_allowed") : src.index("def _executable_name")]
    assert "return False" in seg, "策略不可用时没有 fail-closed"


def test_node122_declares_its_actions_now():
    """最需要动作白名单的那个节点,此前一个声明都没有 → legacy 放行。"""
    import json
    import pathlib

    for cand in (pathlib.Path("."), pathlib.Path("..")):
        f = cand / "config" / "node_catalog.json"
        if f.is_file():
            d = json.loads(f.read_text(encoding="utf-8"))
            break
    else:
        raise AssertionError("找不到 config/node_catalog.json")
    node = next(n for n in d["nodes"] if n.get("num") == 122)
    actions = set(node.get("permissions", {}).get("actions", []))
    assert actions, "Node_122 仍然没有权限声明 —— fail-closed 的闸对它不生效"
    assert "execute" in actions and "kill" in actions
    # 没声明的动作必须被拒
    from core.node_action_permissions import evaluate_action_permission, reset_cache

    reset_cache()
    assert evaluate_action_permission("Node_122_Shell", "format_disk").allowed is False
