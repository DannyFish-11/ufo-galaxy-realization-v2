"""core/tool_call_validator.py — 工具调用参数校验(Gecko 借鉴 · 阶段一)
========================================================================

借鉴 ICML'26 Gecko(camel-ai)的 Argument Validator 思路:LLM 生成的工具调用在
**真正派发之前**先过两层校验,错误在"模拟"里死,不在真实世界死:

  1. **规则层**(零 LLM 成本,微秒级):工具是否存在、必填字段、参数类型、
     enum/format 等 schema 约束——直接用 ``_collect_tools()`` 已产出的
     OpenAI function schema 做 jsonschema 校验。
  2. **语义层**(可选,一次便宜档 LLM 调用):schema 写不进去的约束
     (如"要 ticker 不要公司名")。默认只在阈限态预演(liminal_rehearsal)
     中启用,真实 ReAct 主路径不为它加延迟。

校验失败**不派发**,而是把结构化错误作为 tool 消息回喂给模型——模型在下一轮
自行修正参数(Gecko 的反馈-修正循环,嵌进现有 ReAct,零额外轮次成本)。

与既有防线的关系:能力门 + V3 槽权威管的是【设备/执行体级】准入,本模块管的
是【工具参数级】合法性——互补,不重叠。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ToolCallValidator")

# 只读工具判定(Gecko hybrid adaptation 的边界):只读工具在预演中直通真实系统
# (信息一致性),写状态工具走模拟(安全可控)。按【动作语义前缀/关键词】分类;
# 判不准时保守视为"写状态"(宁可多模拟,不可漏真实副作用)。
_READONLY_MARKERS = (
    "get",
    "list",
    "read",
    "search",
    "query",
    "recall",
    "status",
    "fetch",
    "show",
    "describe",
    "lookup",
    "find",
    "check",
    "info",
    "stat",
    "peek",
    "watch",
    "view",
    "count",
    "ping",
    "health",
)

# 高风险动作关键词——与 command_router._HIGH_RISK_COMMANDS(HITL 审批门)同一
# 语义家族;此处独立维护一份工具级超集,避免依赖私有属性。
_HIGH_RISK_MARKERS = (
    "delete",
    "remove",
    "rm",
    "format",
    "wipe",
    "purge",
    "shutdown",
    "reboot",
    "factory_reset",
    "kill",
    "drop",
    "truncate",
    "uninstall",
    "pay",
    "payment",
    "transfer",
    "send",
    "publish",
    "post",
    "cancel",
    "overwrite",
    "reset",
)


def _action_of(tool_name: str) -> str:
    """取工具名的动作段:node__X__action / mcp__srv__tool / device__act → 末段。"""
    return (tool_name or "").rsplit("__", 1)[-1].lower()


def is_read_only_tool(tool_name: str) -> bool:
    """只读工具(预演中可直通真实执行)。判不准 → False(保守当写状态)。"""
    action = _action_of(tool_name)
    return any(action.startswith(m) or f"_{m}" in action for m in _READONLY_MARKERS)


def is_high_risk_tool(tool_name: str) -> bool:
    """高风险工具(触发语义校验/HITL 语义家族)。"""
    action = _action_of(tool_name)
    return any(m in action for m in _HIGH_RISK_MARKERS)


@dataclass
class ToolCallValidation:
    """一次工具调用的校验结论(结构化,可直接回喂模型)。"""

    valid: bool
    tool_name: str
    errors: List[str] = field(default_factory=list)

    def feedback_text(self) -> str:
        """给模型看的自纠反馈(工具消息体)。"""
        if self.valid:
            return "参数校验通过。"
        lines = "\n".join(f"- {e}" for e in self.errors)
        return (
            f"[参数校验失败·未执行] 工具 {self.tool_name} 的调用参数不合法,"
            f"本次调用没有被执行。问题:\n{lines}\n"
            f"请修正参数后重新调用,或改用其它合适的工具。"
        )


def _find_schema(tool_name: str, tools: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    for t in tools or []:
        fn = t.get("function") if isinstance(t, dict) else None
        if isinstance(fn, dict) and fn.get("name") == tool_name:
            return fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {}
    return None


def validate_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    tools: Optional[List[Dict[str, Any]]],
) -> ToolCallValidation:
    """规则层校验:工具存在性 + jsonschema(必填/类型/enum/format)。

    找不到 schema(工具不在本轮提供的名单里)→ 判失败并列出问题;
    jsonschema 库缺失或 schema 本身畸形 → 放行(校验器绝不误杀主流程)。
    """
    params_schema = _find_schema(tool_name, tools)
    if params_schema is None:
        return ToolCallValidation(
            valid=False,
            tool_name=tool_name,
            errors=[f"工具 {tool_name!r} 不在本轮可用工具名单中(可能拼错了名字)"],
        )
    if not params_schema:
        return ToolCallValidation(valid=True, tool_name=tool_name)
    try:
        import jsonschema
    except Exception:  # noqa: BLE001 — 校验器缺依赖不阻塞主流程
        return ToolCallValidation(valid=True, tool_name=tool_name)
    try:
        validator_cls = jsonschema.validators.validator_for(params_schema)
        validator = validator_cls(params_schema)
        errors = [
            # json path 定位 + 原因,模型能直接看懂改哪里
            f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(args or {}), key=str)
        ]
    except Exception as exc:  # noqa: BLE001 — schema 畸形不当作调用方的错
        logger.debug("工具 %s 的 schema 无法用于校验(放行): %s", tool_name, exc)
        return ToolCallValidation(valid=True, tool_name=tool_name)
    if errors:
        return ToolCallValidation(valid=False, tool_name=tool_name, errors=errors[:8])
    return ToolCallValidation(valid=True, tool_name=tool_name)


async def semantic_check(
    tool_name: str,
    args: Dict[str, Any],
    task_context: str,
    *,
    router: Any = None,
) -> ToolCallValidation:
    """语义层校验(一次便宜档 LLM 调用):参数格式合法但语义是否合适。

    仅在预演/高风险路径调用;任何失败(路由不可用/解析失败)都放行——
    语义层是增强,不是闸门。
    """
    try:
        if router is None:
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()
        prompt = (
            "你是工具调用参数审查员。判断下面的参数在语义上是否适合该工具与任务,"
            '只回 JSON: {"ok": true} 或 {"ok": false, "reason": "..."}\n'
            f"任务: {task_context[:400]}\n工具: {tool_name}\n参数: {args}"
        )
        resp = await router.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=120,
        )
        import json as _json

        text = (getattr(resp, "content", "") or "").strip()
        start, end = text.find("{"), text.rfind("}")
        verdict = _json.loads(text[start : end + 1]) if start >= 0 <= end else {"ok": True}
        if verdict.get("ok", True):
            return ToolCallValidation(valid=True, tool_name=tool_name)
        return ToolCallValidation(
            valid=False,
            tool_name=tool_name,
            errors=[f"语义不合适: {str(verdict.get('reason', ''))[:200]}"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("语义校验不可用(放行): %s", exc)
        return ToolCallValidation(valid=True, tool_name=tool_name)
