"""core/node_tools.py —— 模型用节点:``nodes__list`` 查、``nodes__invoke`` 调(第 10 轮)。

为什么要有它
============
125 个节点(搜索、文件、命令行、Git、邮件、数据库、手机与电脑的键鼠、家电、打印机……)在统一执行器里都调得通了
(第 9 轮),可模型一个都看不到:规范路径上的节点工具来自 NodeFabricRegistry 登记的能力表,而启动器登记节点时能力表
是空的。所有者的决定(2026-11-01):**节点可以开放给模型;高权限、高危险的动作要交给人确认,跟之前那些一样。**

两个工具
========
* ``nodes__list``:不给参数 → 节点目录(按类别,一节点一句用途);给 ``query`` → 按名字 / 用途找;给 ``node`` → 这个节点的
  每个动作:说明、参数(名字、类型、必填)、档(只读 / 会改东西 / 危险 / 极危险)、这次调用要不要先问人;
* ``nodes__invoke``:调一个动作。

调之前(执行不猜)
================
1. 节点认不出、没登记成可运行、动作认不出或有歧义、必填参数没给 → 不执行,照实说缺什么、有哪些(不替模型猜);
2. 按 ``core/node_action_risk.py`` 打档:危险与极危险**总要问人**,「会改东西」只在谨慎档问,只读不问;
3. 问人只经 :func:`core.approval_gate.request_approval`(电脑发起的在电脑面板上批,手机 / 手表发起的在那边批;
   批一次记「同一个动作 + 同一个对象」到这段对话结束;没批就不执行)。批过的这一次,节点拨盘门认(一次调用只问一次);
4. 经统一执行器 ``invoke_node`` 执行(治理门、动作白名单照常生效)。两层任一层回失败就是失败。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeTools")

#: 一次调用给节点多久(秒)。等人批准的时间另算(在问人那一步)。
INVOKE_TIMEOUT_S = 60.0
#: 按 query 找节点时最多回几个
MAX_FOUND = 20
#: 目录里一句用途最长多少字
_PURPOSE_CHARS = 48


def _fn(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


NODES_BUILTIN_TOOLS: List[Dict[str, Any]] = [
    _fn(
        "nodes__list",
        "Find what the system's capability nodes can do (web/file/shell/git/email/database/phone & desktop control/"
        "smart home/printers/maths/media …). No arguments: the directory of nodes, one line each. 'query': nodes whose "
        "name or purpose matches. 'node': that node's actions with their parameters and risk level (safe / moderate / "
        "dangerous / critical) and whether calling it will ask the user first. Prefer a dedicated tool (devices__, "
        "home__, computer_use__, academic__, memory__ …) when one fits; use nodes for everything else.",
        {
            "query": {"type": "string", "description": "words to match against node names and purposes"},
            "node": {"type": "string", "description": "node id, e.g. 'Node_23_Time' or '23'"},
        },
        [],
    ),
    _fn(
        "nodes__invoke",
        "Run one action on a node. Call nodes__list with 'node' first and pass the action name and parameters exactly "
        "as listed. Dangerous and critical actions (running commands or code, deleting, sending messages/email, "
        "pushing code, controlling devices, reading secrets …) are put to the user for approval first; if they say no "
        "or do not answer, it is not run — tell them so instead of retrying. An unknown action, an ambiguous name or a "
        "missing required parameter is refused with the list of what the node has.",
        {
            "node": {"type": "string", "description": "node id from nodes__list"},
            "action": {"type": "string", "description": "action name from nodes__list"},
            "params": {"type": "object", "description": "the action's parameters"},
            "reason": {"type": "string", "description": "one short line: why (shown to the user when asking)"},
        },
        ["node", "action"],
    ),
]


def nodes_tools_for_agent() -> List[Dict[str, Any]]:
    return list(NODES_BUILTIN_TOOLS)


# ── 目录 ──────────────────────────────────────────────────────────────────────


def _roster() -> List[Dict[str, Any]]:
    """规范路径能调的节点(占位节点、旧编排节点不列 —— 见 core/node_declared_class.py)。"""
    from core.node_catalog import catalog_nodes
    from core.node_declared_class import why_not_callable

    return [n for n in catalog_nodes() if n.get("runnable", True) and not why_not_callable(n["dir"])]


def _line(n: Dict[str, Any]) -> str:
    """目录里的一行:``Node_23_Time — 用途 [要 key:OpenWeather]``。"""
    text = f"{n['dir']} — {str(n.get('purpose') or '')[:_PURPOSE_CHARS]}"
    connector = n.get("connector") or {}
    return f"{text} [要 {connector.get('kind', '')}:{connector['service']}]" if connector.get("service") else text


def _directory(query: str) -> Dict[str, Any]:
    rows = _roster()
    if query:
        q = query.strip().lower()
        found = [
            _line(n)
            for n in rows
            if q in n["dir"].lower()
            or q in str(n.get("purpose") or "").lower()
            or q in str(n.get("type_label", "")).lower()
        ]
        return {
            "success": True,
            "query": query,
            "nodes": found[:MAX_FOUND],
            "truncated": len(found) > MAX_FOUND,
            "next": "nodes__list with 'node' to see a node's actions",
        }
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for n in rows:
        groups.setdefault(str(n.get("type_label") or "其他"), []).append(_line(n))
    return {
        "success": True,
        "count": len(rows),
        "groups": groups,
        "next": "nodes__list with 'node' to see a node's actions",
    }


async def _describe(node: str) -> Dict[str, Any]:
    from core.node_action_risk import current_dial, needs_human
    from core.node_actions import list_actions, node_dir

    found = node_dir(node)
    if found is None:
        return {"success": False, "error": f"没有叫「{node}」的节点,先用 nodes__list 找"}
    from core.node_declared_class import why_not_callable

    if why_not_callable(found):
        return {"success": False, "node": found, "error": f"{found}:{why_not_callable(found)}"}
    try:
        actions, source = await asyncio.to_thread(list_actions, found)
    except Exception as exc:  # noqa: BLE001 — 载不进来:照实说
        return {"success": False, "node": found, "error": f"节点 {found} 载不进来:{exc}"}
    dial = current_dial()
    rows = [{**a.to_dict(), "asks_first": needs_human(a.grade.level, dial)} for a in actions]
    return {"success": True, "node": found, "source": source, "autonomy": dial, "actions": rows}


# ── 调用 ──────────────────────────────────────────────────────────────────────


def _unwrap(inv: Any) -> Dict[str, Any]:
    """统一执行器的结果 → ``{success, result|error}``:两层任一层说失败就是失败。"""
    if not inv.success:
        return {"success": False, "error": inv.error or "执行失败"}
    outer = inv.result if isinstance(inv.result, dict) else {}
    if outer.get("success") is False:
        return {"success": False, "error": str(outer.get("error") or "节点执行失败")}
    inner = outer.get("data", outer.get("result", inv.result)) if outer else inv.result
    if isinstance(inner, dict) and inner.get("success") is False:
        return {"success": False, "error": str(inner.get("error") or "节点执行失败")}
    return {"success": True, "result": inner}


def _what(found_dir: str, action: str, target: str, reason: str) -> str:
    text = f"{found_dir}.{action}" + (f"({target})" if target else "")
    return f"{text} —— {reason}" if reason else text


async def _invoke(node: str, action: str, params: Dict[str, Any], reason: str, session_id: str) -> Dict[str, Any]:
    from core.approval_gate import approval_target, interactive, label, node_key, request_approval
    from core.node_action_risk import current_dial, needs_human
    from core.node_actions import missing_params, node_dir, resolve
    from core.node_declared_class import why_not_callable

    found_dir = node_dir(node)
    if found_dir is None:
        return {"success": False, "error": f"没有叫「{node}」的节点,先用 nodes__list 找"}
    excluded = why_not_callable(found_dir)  # 占位节点、旧编排节点:不问人、不执行
    if excluded:
        return {"success": False, "node": found_dir, "error": f"{found_dir}:{excluded}。没有执行。"}
    action = str(action or "").strip()
    if not action:
        return {"success": False, "error": "nodes__invoke 需要 action(用 nodes__list 看这个节点有哪些)"}
    try:
        hit, why = await asyncio.to_thread(resolve, found_dir, action, params)
    except Exception as exc:  # noqa: BLE001 — 载不进来:不执行
        return {"success": False, "node": found_dir, "error": f"节点 {found_dir} 载不进来,没有执行:{exc}"}
    if hit is None:
        return {"success": False, "node": found_dir, "error": f"{found_dir}:{why}。没有执行。"}
    missing = missing_params(hit, params)
    if missing:
        return {
            "success": False,
            "node": found_dir,
            "action": action,
            "error": f"缺必填参数 {', '.join(missing)},没有执行",
            "params": hit.params,
        }

    risk = hit.grade.to_dict()
    target = approval_target(params)
    what = _what(found_dir, action, target, reason)
    approved_by = ""
    if needs_human(hit.grade.level, current_dial()):
        outcome = await request_approval(
            key=node_key(found_dir, action, params),
            target=target,
            what=what,
            risk=hit.grade.level,
            session_id=session_id,
            params=params,
        )
        if not outcome.approved:
            return {
                "success": False,
                "node": found_dir,
                "action": action,
                "needs_confirmation": True,
                **risk,
                "error": f"{what} 没有执行:{outcome.reason}",
            }
        approved_by = outcome.source

    from core.node_invocation import InvocationSource, invoke_node

    with interactive(), label(what):
        inv = await invoke_node(
            found_dir,
            action,
            params,
            invocation_source=InvocationSource.OPENCLAWD,
            session_id=session_id or None,
            timeout_ms=INVOKE_TIMEOUT_S * 1000,
        )
    out = {"node": found_dir, "action": action, **risk, **_unwrap(inv)}
    if approved_by:
        out["approved_by"] = approved_by
    return out


async def dispatch_nodes_tool(action: str, arguments: Dict[str, Any], *, session_id: str = "") -> Dict[str, Any]:
    """执行 ``nodes__<action>``。永不抛出:失败作为结果回给模型。"""
    args = dict(arguments or {})
    try:
        if action == "list":
            node = str(args.get("node") or "").strip()
            if node:
                return await _describe(node)
            return await asyncio.to_thread(_directory, str(args.get("query") or ""))
        if action == "invoke":
            params = args.get("params") or {}
            if not isinstance(params, dict):
                return {"success": False, "error": "params 要是一个对象(键 → 值)"}
            return await _invoke(
                str(args.get("node") or ""),
                str(args.get("action") or ""),
                params,
                str(args.get("reason") or ""),
                session_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("nodes__%s 失败: %s", action, exc)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"success": False, "error": f"未知的节点工具: nodes__{action}"}


def name_only_grade(arguments: Optional[Dict[str, Any]]) -> Optional[str]:
    """不载节点、只按名字(与参数)给的档 —— 只会比真实的档高或相等(不知道是 GET 就按会改东西算)。

    给工具超时预算用(:func:`core.approval_gate.may_wait_for_a_human`):那一步在事件循环上,不能去载节点模块。
    """
    from core.node_action_risk import grade

    args = arguments or {}
    node, action = str(args.get("node") or ""), str(args.get("action") or "")
    if not node or not action:
        return None
    params = args.get("params") if isinstance(args.get("params"), dict) else {}
    return grade(node, action, params=params).level


__all__ = ["INVOKE_TIMEOUT_S", "NODES_BUILTIN_TOOLS", "dispatch_nodes_tool", "name_only_grade", "nodes_tools_for_agent"]
