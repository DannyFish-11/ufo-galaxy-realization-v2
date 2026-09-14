"""core/windows_powershell_policy.py — PowerShell 的 cmdlet 级白名单
=====================================================================

为什么不能直接把 powershell 加进 argv[0] 白名单
------------------------------------------------
``Node_122_Shell`` 的白名单按 **argv[0]**(程序名)授权,这对 ``git`` / ``ls`` 这类
程序是有效的:程序本身决定了它能做什么。

但 ``powershell -Command <任意字符串>`` 不是这样 —— 它是一个**通用解释器**。
把 ``powershell`` 加进 argv[0] 白名单,等于给了一把万能钥匙:白名单外的每一个程序
都能通过 ``powershell -Command "rm -rf ..."`` 被调起来,那道白名单当场失效。

所以 PowerShell 必须在**更细的一层**授权:允许的不是"powershell 这个程序",
而是"powershell 后面跟的那个 cmdlet"。

沙箱在这里不适用
----------------
``core/execution_isolation.py`` 是真沙箱,但它盖的是 ``SafeExecutor`` —— 模型生成的
代码跑在容器里。桌面自动化在**结构上**不可能被容器盖住:PowerShell 一旦跑进容器,
它就碰不到这台机器的桌面了,而那正是它存在的理由。

能隔离就说明操作不了你的电脑;能操作你的电脑就说明没被隔离。两件事不能同时成立。
所以这里的安全性来自**门禁**,不来自沙箱:白名单 + 元字符拒绝 + 参数不拼串 +
人确认,四层都是与的关系。

默认白名单的取舍
----------------
默认只给**只读**的 cmdlet(Get-* 这一类)。写操作、进程控制、服务控制、注册表、
文件删除一律不在默认集合里 —— 需要它们的场景应当显式通过
``GALAXY_PS_ALLOWED_CMDLETS`` 授权,而不是默认可用。

这个取舍和 Node_122 的默认集合刻意不含 rm / mv / dd / sudo 是同一条原则。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Sequence

__all__ = [
    "POWERSHELL_EXECUTABLES",
    "DEFAULT_ALLOWED_CMDLETS",
    "SHELL_METACHARACTERS",
    "PowerShellVerdict",
    "is_powershell",
    "allowed_cmdlets",
    "evaluate",
]

#: 会被当成 PowerShell 解释器的程序名(小写、已去掉路径与 .exe)。
POWERSHELL_EXECUTABLES: FrozenSet[str] = frozenset({"powershell", "pwsh", "powershell_ise"})

#: 默认允许的 cmdlet。**只读**。
#:
#: 刻意不含:Remove-* / Set-* / New-* / Start-* / Stop-* / Invoke-* /
#: Restart-* / Clear-* / Out-File / Add-Content —— 这些要么改状态,要么
#: (Invoke-Expression / Invoke-Command)本身就是另一把万能钥匙。
DEFAULT_ALLOWED_CMDLETS: FrozenSet[str] = frozenset(
    {
        "get-process",
        "get-service",
        "get-childitem",
        "get-content",
        "get-location",
        "get-date",
        "get-host",
        "get-command",
        "get-help",
        "get-module",
        "get-computerinfo",
        "get-hotfix",
        "get-eventlog",
        "get-wmiobject",
        "get-ciminstance",
        "get-netadapter",
        "get-netipaddress",
        "get-volume",
        "get-disk",
        "test-path",
        "test-connection",
        "measure-object",
        "select-object",
        "where-object",
        "sort-object",
        "format-list",
        "format-table",
    }
)

#: 出现其中任何一个就拒绝。
#:
#: 为什么白名单之外还要这一道:``Get-Process; Remove-Item C:\\``。前半截是允许的
#: cmdlet,后半截不是 —— 只看第一个词的白名单会放行整条。分号、管道、``&``、
#: ``$(...)``、反引号、重定向,每一个都能在一个被允许的 cmdlet 后面接上任意东西。
SHELL_METACHARACTERS: FrozenSet[str] = frozenset({";", "|", "&", "`", "$(", "${", ">", "<", "\n", "\r", "&&", "||"})

_CMDLET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-[A-Za-z][A-Za-z0-9]*$")


@dataclass(frozen=True)
class PowerShellVerdict:
    """一次 PowerShell 调用的判定。冻结:判定不该在执行途中被改写。"""

    allowed: bool
    reason: str
    cmdlet: str = ""
    #: **永远为 True**。见 :func:`evaluate` 的说明 —— 这不是一个可以按档位放松的位。
    needs_human: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "cmdlet": self.cmdlet,
            "needs_human": self.needs_human,
        }


def is_powershell(executable: str) -> bool:
    """这个程序名是不是 PowerShell 解释器。输入应当已经过 basename 与 .exe 剥离。"""
    name = (executable or "").strip().lower()
    if name.endswith(".exe"):
        name = name[: -len(".exe")]
    return name in POWERSHELL_EXECUTABLES


def allowed_cmdlets() -> FrozenSet[str]:
    """当前允许的 cmdlet 集合。``GALAXY_PS_ALLOWED_CMDLETS`` 逗号分隔,**追加**到默认集合。"""
    extra = os.getenv("GALAXY_PS_ALLOWED_CMDLETS", "")
    if not extra.strip():
        return DEFAULT_ALLOWED_CMDLETS
    added = {c.strip().lower() for c in extra.split(",") if c.strip()}
    return DEFAULT_ALLOWED_CMDLETS | frozenset(added)


def _first_cmdlet(tokens: Sequence[str]) -> str:
    """取 ``-Command`` / ``-c`` 之后的第一个 token —— 那才是真正要跑的 cmdlet。"""
    for i, tok in enumerate(tokens):
        if tok.lower() in ("-command", "-c", "/command"):
            return tokens[i + 1].strip().strip("'\"") if i + 1 < len(tokens) else ""
    return ""


def evaluate(argv: Optional[Sequence[str]]) -> PowerShellVerdict:
    """判定这次 PowerShell 调用放不放行。纯函数。

    ``needs_human`` 恒为 True,**不看自治档位**。``core.autonomy_policy`` 的
    ``AUTONOMOUS`` 档会跳过逐步审批,那对点击、输入是合理的;对一个通用解释器不是。
    一次不走运的命令生成,和一次点错按钮,代价差着数量级。

    fail-closed:参数为空、不是 PowerShell、拿不到 cmdlet、cmdlet 形状不对、
    出现元字符 —— 一律不放行,并说明是哪一条。
    """
    tokens: List[str] = [str(t) for t in (argv or []) if str(t).strip()]
    if not tokens:
        return PowerShellVerdict(False, "空命令")

    if not is_powershell(re.split(r"[\\/]", tokens[0])[-1]):
        return PowerShellVerdict(False, f"argv[0] 不是 PowerShell 解释器: {tokens[0]!r}")

    rest = " ".join(tokens[1:])
    for meta in SHELL_METACHARACTERS:
        if meta in rest:
            return PowerShellVerdict(
                False,
                f"命令里出现元字符 {meta!r} —— 被允许的 cmdlet 后面能接任意东西,白名单会被绕过",
            )

    cmdlet = _first_cmdlet(tokens[1:])
    if not cmdlet:
        return PowerShellVerdict(False, "没有 -Command,或它后面没有 cmdlet —— 拿不到要授权的对象")

    if not _CMDLET_RE.match(cmdlet):
        # 形如 "C:\\x.ps1" 或 "iex" 的东西不是 Verb-Noun,拿不准一律拒。
        return PowerShellVerdict(False, f"{cmdlet!r} 不是 Verb-Noun 形状的 cmdlet", cmdlet=cmdlet)

    if cmdlet.lower() not in allowed_cmdlets():
        return PowerShellVerdict(
            False,
            f"cmdlet {cmdlet!r} 不在白名单里(设 GALAXY_PS_ALLOWED_CMDLETS 可授权)",
            cmdlet=cmdlet,
        )

    return PowerShellVerdict(True, f"cmdlet {cmdlet!r} 在白名单里;仍需人确认", cmdlet=cmdlet)
