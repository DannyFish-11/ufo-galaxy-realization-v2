"""core/shell_script_policy.py — `/script` 那条路的判定(纯函数)

为什么单独有这一条
------------------
``Node_122_Shell`` 有两个执行入口,而安全检查只装在一个上:

    execute / execute_background → _is_command_safe  ✅
    execute_script               → 什么都没有         ❌

实测确认过:``execute_script`` 里一次 ``_is_command_safe`` 都没调。于是上一轮为
PowerShell 建的那一整套(cmdlet 白名单、元字符拒绝)有个平行绕过口 ——
``{"interpreter": "powershell", "script": "<任意内容>"}`` 一行都不经过它们。

脚本和单条命令不是一回事
------------------------
把 ``_is_command_safe(shell_mode=True)`` 逐行套到脚本正文上,结果是几乎所有真实脚本
都被拒(管道、``&&``、重定向在脚本里是正常写法)。一个没法用的端点会被绕过去用别的方式,
那比装不上更糟。所以这里换一套形状。

**静态判定一段任意脚本安不安全,是做不到的。** 这句话必须写在这儿,因为下面这两层
很容易被读成"已经安全了":

  1. **解释器白名单**(主防线)—— ``interpreter`` 是 ``create_subprocess_exec`` 的
     argv[0],由调用方直接给。不限制它,这个端点就是"执行任意可执行文件"。
  2. **正文黑名单扫描**(第二道)—— 只能抓已知坏字面量。抓不到的远比抓得到的多。

真正兜底的是第三层:**人确认**。

PowerShell 不在解释器白名单里
-----------------------------
``powershell`` / ``pwsh`` / ``cmd`` 被**刻意排除**。把 PowerShell 当脚本解释器,
等于把任意 PowerShell 从 stdin 灌进去 —— 上一轮 cmdlet 白名单挡住的每一条,
都能从这条路原样进来。这和当初拒绝把 ``powershell`` 加进 argv[0] 白名单是同一个
论证(通用解释器 = 万能钥匙),只是换了个入口;论证不该只在一个入口成立。

需要在 Windows 上跑 PowerShell,走 ``/execute`` —— 那条路上 cmdlet 白名单是生效的。
"""

from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

logger = logging.getLogger("Galaxy.ShellScriptPolicy")

__all__ = [
    "DEFAULT_ALLOWED_INTERPRETERS",
    "ScriptVerdict",
    "allowed_interpreters",
    "interpreter_name",
    "evaluate_script",
]

#: 允许作为脚本解释器的程序名(按 basename 比较,去掉 ``.exe``)。
#:
#: **刻意不含 powershell / pwsh / cmd** —— 见模块 docstring。
#: 也不含 ``sudo`` / ``env`` / ``xargs`` 这类"能把别的程序拉起来"的转发器:
#: 允许它们等于允许它们能启动的一切。
DEFAULT_ALLOWED_INTERPRETERS = frozenset(
    {
        "bash",
        "sh",
        "zsh",
        "dash",
        "python",
        "python3",
        "node",
    }
)

#: 解释器白名单的追加项(逗号分隔)。和 ``GALAXY_SHELL_ALLOWED_COMMANDS`` 同一约定:
#: 默认保守,要放开得显式写出来。
ENV_EXTRA_INTERPRETERS = "GALAXY_SCRIPT_ALLOWED_INTERPRETERS"


@dataclass(frozen=True)
class ScriptVerdict:
    """一次 ``/script`` 调用的判定结果。冻结,防事后篡改。"""

    allowed: bool
    reason: str = ""
    interpreter: str = ""
    #: 命中的黑名单字面量(便于排障说清楚是被哪条拦的)。
    matched_pattern: str = ""
    #: **恒为 True**。理由见 :func:`evaluate_script`。
    needs_human: bool = True

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "interpreter": self.interpreter,
            "matched_pattern": self.matched_pattern,
            "needs_human": self.needs_human,
        }


def allowed_interpreters() -> frozenset:
    extra = os.getenv(ENV_EXTRA_INTERPRETERS, "")
    if not extra.strip():
        return DEFAULT_ALLOWED_INTERPRETERS
    added = {i.strip().lower() for i in extra.split(",") if i.strip()}
    return DEFAULT_ALLOWED_INTERPRETERS | added


def interpreter_name(interpreter: str) -> str:
    """``/usr/bin/python3`` → ``python3``;``C:\\WINDOWS\\powershell.exe`` → ``powershell``。

    取 basename 是为了让 ``/bin/../bin/powershell`` 这种写法不能绕过按程序名的限制。
    ``posix=False`` 的理由和 ``_executable_name`` 一样:POSIX 模式会把 Windows 路径里的
    反斜杠当转义符吃掉。
    """
    raw = (interpreter or "").strip()
    if not raw:
        return ""
    try:
        tokens = shlex.split(raw, posix=False)
        first = tokens[0] if tokens else ""
    except ValueError:
        first = raw.split()[0] if raw.split() else ""
    first = first.strip("\"'")
    # 同时按两种分隔符取 basename —— 跨平台路径都可能出现
    for sep in ("/", "\\"):
        if sep in first:
            first = first.rsplit(sep, 1)[-1]
    name = first.lower()
    if name.endswith(".exe"):
        name = name[: -len(".exe")]
    return name


def evaluate_script(
    interpreter: str,
    script: str,
    *,
    blocked_patterns: Optional[Sequence[str]] = None,
    allowlist_enabled: bool = True,
) -> ScriptVerdict:
    """判定一次 ``/script`` 调用。

    ``needs_human`` **恒为 True**,不看自治档位 —— 和 PowerShell 那条是同一个理由:
    一段任意脚本正文没法被静态判定,机器给不出"这段安全"的结论。给不出结论的时候
    该问人,而不是默认放行。调用方必须真的去问(上一轮的教训:这个字段光有值、没人读,
    等于第四层不存在)。

    ``blocked_patterns`` 由调用方注入(``Node_122`` 传它自己的 ``BLOCKED_COMMANDS``)——
    **本模块不自己再造一份黑名单**,那必然和节点那份漂移。
    """
    name = interpreter_name(interpreter)
    if not name:
        return ScriptVerdict(allowed=False, reason="解释器为空:无从判定要执行什么")

    if allowlist_enabled:
        allowed = allowed_interpreters()
        if name not in allowed:
            return ScriptVerdict(
                allowed=False,
                interpreter=name,
                reason=(
                    f"解释器 {name!r} 不在白名单里"
                    f"(设 {ENV_EXTRA_INTERPRETERS} 可追加;"
                    f"powershell/pwsh/cmd 是刻意排除的,走 /execute)"
                ),
            )

    hit = _first_blocked(script, blocked_patterns or ())
    if hit:
        return ScriptVerdict(
            allowed=False,
            interpreter=name,
            matched_pattern=hit,
            reason=f"脚本正文命中黑名单 {hit!r}",
        )

    return ScriptVerdict(allowed=True, interpreter=name, reason="解释器在白名单内,正文未命中黑名单")


def _first_blocked(script: str, patterns: Iterable[str]) -> str:
    """正文里第一条命中的黑名单字面量。

    和 ``_is_command_safe`` 一样先归一化空白 —— 否则 ``rm  -rf /``(双空格)
    和 ``rm\\t-rf /`` 都能绕过 ``rm -rf /`` 这条。逐行做而不是整篇拼成一行:
    整篇归一化会把跨行的两条无关命令粘成一条,凭空造出不存在的匹配。
    """
    lines: List[str] = [" ".join(ln.lower().split()) for ln in (script or "").splitlines()]
    for pattern in patterns:
        norm = " ".join(str(pattern).lower().split())
        if not norm:
            continue
        if any(norm in ln for ln in lines):
            return str(pattern)
    return ""
