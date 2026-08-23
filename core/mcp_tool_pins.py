"""core/mcp_tool_pins.py — MCP 服务器的工具清单变了没有
========================================================

问题:客户端从服务器继承信任,却从不复验
--------------------------------------
MCP 的工具描述是**直接进模型上下文**的文本。它由服务器给,而服务器随时可以改。
公开记录在案的攻击形状:

- **工具投毒** —— 描述里藏着给模型看的指令,模型调这个工具时以宿主权限执行;
- **rug-pull** —— 先上线一个干净的服务器,等被信任之后再推一次更新把描述换掉,
  而宿主重新拉取工具清单时**不会再问任何人**;
- **工具影子** —— 一个服务器的描述去改写另一个服务器的工具行为。

三者共同的结构性成因是同一个:**宿主从服务器继承信任,却不持续验证**。

``core.mcp_loader._refresh_tools`` 正是这个形状 —— 每次刷新直接整表替换::

    server.tools = [MCPTool.from_dict(t) for t in response.result.get("tools", [])]

这道闸做什么
------------
给每台服务器的**整份工具清单**算一个指纹(名字 + 描述 + 入参 schema,三样都算,
因为三样都进上下文),钉住;下次清单变了就按档位处理。

关于"第一次见到就信"(TOFU)
---------------------------
``core.weights_admission`` 里我写死了"钉子必须是人显式做的动作",因为那边有
可对照的外部事实(模型仓库、发布方)。**这里不一样**:MCP 的工具清单是运行时从
服务器动态发现的,没有任何带外清单可以对照 —— 要么第一次见到就记下来,要么这道闸
根本没法起步。

所以这里用 TOFU,并且**把这个弱点显式记进钉子里**(``tofu: true``),报告里分开
计数。它挡得住"后来被改了",挡不住"一开始就是坏的" —— 这句话必须写在这儿,而不是
让人从"已钉住 N 个"里自己推。

档位
----
``enforce``(默认)配 TOFU 是**能用的**:第一次照记不拦,只有"变了"才拦。
``warn`` 只记不拦;``off`` 完全不生效。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

logger = logging.getLogger("Galaxy.MCPToolPins")

#: 档位。默认 ``enforce`` —— 配合 TOFU,它只拦"变了",不拦"第一次见到"。
PIN_MODES: Tuple[str, ...] = ("enforce", "warn", "off")

#: 钉子落在这里。与 ``core.weights_admission`` 同一处置:**路径不做 env 覆盖**。
_PIN_FILE = Path("runtime") / "mcp_tool_pins.json"


@dataclass(frozen=True)
class PinVerdict:
    """一台服务器这次刷新的判定。"""

    #: ``first_seen`` / ``unchanged`` / ``changed`` / ``skipped``(闸关着)
    status: str = "first_seen"
    server: str = ""
    fingerprint: str = ""
    previous: str = ""
    mode: str = "enforce"
    #: 变更明细,给人看的:哪些工具加了/没了/描述被改了。
    changes: Tuple[str, ...] = ()
    reason: str = ""

    @property
    def accepted(self) -> bool:
        """这份工具清单能不能用。只有 ``changed`` 且 ``enforce`` 时为假。"""
        return not (self.status == "changed" and self.mode == "enforce")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "server": self.server,
            "fingerprint": self.fingerprint,
            "previous": self.previous,
            "mode": self.mode,
            "changes": list(self.changes),
            "reason": self.reason,
            "accepted": self.accepted,
        }


def pin_mode() -> str:
    """取值非法时按 ``enforce``(不因为拼错就把闸降级)。"""
    raw = (os.environ.get("GALAXY_MCP_PIN_MODE", "enforce") or "enforce").strip().lower()
    return raw if raw in PIN_MODES else "enforce"


# ══════════════════════════════════════════════════════════════════════════
# 指纹
# ══════════════════════════════════════════════════════════════════════════


def _tool_tuple(tool: Any) -> Tuple[str, str, str]:
    """从一个工具对象取出**会进上下文的那三样**。

    入参 schema 也算进去:藏在 schema 的 ``description`` 字段里的指令,和藏在
    工具描述里的一样会被模型读到。只指纹名字是挡不住投毒的。
    """
    name = str(getattr(tool, "name", "") or (tool.get("name", "") if isinstance(tool, dict) else ""))
    desc = str(getattr(tool, "description", "") or (tool.get("description", "") if isinstance(tool, dict) else ""))
    raw_schema = getattr(tool, "inputSchema", None)
    if raw_schema is None and isinstance(tool, dict):
        raw_schema = tool.get("inputSchema")
    try:
        schema = json.dumps(raw_schema or {}, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        schema = repr(raw_schema)
    return name, desc, schema


def fingerprint(tools: Iterable[Any]) -> str:
    """整份工具清单的指纹。空清单也有确定的指纹 —— 它与"没探到"不是一回事。"""
    digest = hashlib.sha256()
    for name, desc, schema in sorted(_tool_tuple(t) for t in tools):
        digest.update(name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(desc.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(schema.encode("utf-8"))
        digest.update(b"\x01")
    return digest.hexdigest()


def _describe_changes(old: Dict[str, Tuple[str, str]], tools: Iterable[Any]) -> Tuple[str, ...]:
    """人能看懂的变更明细。没有明细时返回空 —— 不编。"""
    current = {name: (desc, schema) for name, desc, schema in (_tool_tuple(t) for t in tools)}
    out: List[str] = []
    for name in sorted(set(old) | set(current)):
        if name not in current:
            out.append(f"工具消失: {name}")
        elif name not in old:
            out.append(f"新增工具: {name}")
        else:
            if old[name][0] != current[name][0]:
                out.append(f"描述被改: {name}")
            if old[name][1] != current[name][1]:
                out.append(f"入参 schema 被改: {name}")
    return tuple(out)


# ══════════════════════════════════════════════════════════════════════════
# 钉子存取
# ══════════════════════════════════════════════════════════════════════════


def _load() -> Dict[str, Dict[str, Any]]:
    try:
        with open(_PIN_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:  # noqa: BLE001
        logger.warning("MCP 钉子读不出来,按没有钉子处理: %s", exc)
        return {}


def _save(pins: Dict[str, Dict[str, Any]]) -> bool:
    try:
        _PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_PIN_FILE, "w", encoding="utf-8") as handle:
            json.dump(pins, handle, ensure_ascii=False, indent=2, sort_keys=True)
        return True
    except OSError as exc:  # noqa: BLE001
        logger.warning("MCP 钉子写不进去: %s", exc)
        return False


def pinned(server: str) -> str:
    """这台服务器登记过的指纹;没登记过为空串。"""
    return str(_load().get(server, {}).get("fingerprint", ""))


def approve(server: str, tools: Iterable[Any], *, tofu: bool = False) -> bool:
    """把当前清单钉住(或重新钉住)。

    ``tofu=True`` 表示这是"第一次见到就记下"的钉子,**弱点会被记进文件**,
    好让报告能把它和人确认过的钉子分开算。
    """
    tool_list = list(tools)
    pins = _load()
    pins[server] = {
        "fingerprint": fingerprint(tool_list),
        "tools": {name: [desc, schema] for name, desc, schema in (_tool_tuple(t) for t in tool_list)},
        "tofu": bool(tofu),
        "at": time.time(),
    }
    return _save(pins)


# ══════════════════════════════════════════════════════════════════════════
# 判据
# ══════════════════════════════════════════════════════════════════════════


def check(server: str, tools: Iterable[Any]) -> PinVerdict:
    """这台服务器这次刷新的工具清单能不能用。**唯一判据处**,不抛异常。"""
    mode = pin_mode()
    tool_list = list(tools)

    if mode == "off":
        return PinVerdict(status="skipped", server=server, mode=mode, reason="MCP 钉子闸已关(off)")

    current = fingerprint(tool_list)
    record = _load().get(server, {})
    previous = str(record.get("fingerprint", ""))

    if not previous:
        # TOFU:第一次见到就记下。挡不住"一开始就是坏的",见模块头。
        approve(server, tool_list, tofu=True)
        return PinVerdict(
            status="first_seen",
            server=server,
            fingerprint=current,
            mode=mode,
            reason=f"{server} 第一次见到,已按 TOFU 记下({len(tool_list)} 个工具)",
        )

    if current == previous:
        return PinVerdict(
            status="unchanged",
            server=server,
            fingerprint=current,
            previous=previous,
            mode=mode,
            reason="工具清单与登记的一致",
        )

    old_tools = {
        str(k): (str(v[0]), str(v[1]))
        for k, v in (record.get("tools") or {}).items()
        if isinstance(v, (list, tuple)) and len(v) == 2
    }
    changes = _describe_changes(old_tools, tool_list)
    verdict = PinVerdict(
        status="changed",
        server=server,
        fingerprint=current,
        previous=previous,
        mode=mode,
        changes=changes,
        reason=(
            f"{server} 的工具清单变了 —— 这正是 rug-pull 的形状。"
            + ("变更: " + "; ".join(changes) if changes else "变更明细算不出来")
            + ("(已拦下,确认无误后重新钉住)" if mode == "enforce" else "(warn 档只记不拦)")
        ),
    )
    logger.warning("MCP 工具清单变更: %s", verdict.reason)
    return verdict


def pins_report() -> Dict[str, Any]:
    """只读诊断:钉了哪些服务器,其中多少是 TOFU(即"没人确认过")。"""
    pins = _load()
    tofu = [name for name, rec in pins.items() if rec.get("tofu")]
    return {
        "mode": pin_mode(),
        "enforcing": pin_mode() == "enforce",
        "pinned_servers": len(pins),
        # 这一位是这份报告的要害:TOFU 的钉子只挡"后来被改了",
        # 挡不住"一开始就是坏的"。混在总数里报会让人高估这道闸。
        "trust_on_first_use": len(tofu),
        "human_confirmed": len(pins) - len(tofu),
        "servers": sorted(pins.keys()),
    }
