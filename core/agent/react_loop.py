"""
core/agent/react_loop.py
========================
统一的 ReAct 工具调用循环（native function-calling 风格）。

背景：此前 ReAct 循环在三处各写了一遍且参数不一致——
  - ``core/agent_factory.py``        单 Agent，max 8
  - ``core/agent_team.py``           团队成员，max 6
  - ``core/local_agent_runtime.py``  Manifest 本地，max 10（不同 schema/范式）

前两处是同构的 OpenAI 风格 tool-calling 循环，本模块把它们的循环主体抽成
``run_react_tool_loop()``：调用方通过回调提供「如何调 LLM」「如何派发工具」
「如何记录工具结果」「（可选）如何反思」，循环负责迭代、消息装配、环路检测、
反思回灌与终止。``local_agent_runtime`` 因 schema 不同（injected 回调 + 逐步
状态上报）不并入本函数，但与三处共享 :class:`ReactConfig` 与环路检测。

所有上限/预算/反思/环路检测均集中在 :class:`ReactConfig`，可经环境变量覆盖。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.Agent.ReactLoop")


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass
class ReactConfig:
    """ReAct 循环的集中配置（单一可调来源，环境变量可覆盖）。"""

    # 各上下文的迭代上限（替代散落的 8 / 6 / 10 魔数）
    single_agent_max_iterations: int = 8
    team_member_max_iterations: int = 6
    manifest_max_turns: int = 10

    # 反思自检（Reflexion 式）
    reflection_enabled: bool = True
    max_reflection_rounds: int = 1

    # 环路检测：连续重复相同 tool-call 签名达到该次数即提前终止
    # （0 表示关闭）。避免模型在同一工具/参数上空转耗尽预算。
    loop_detection_window: int = 2

    @classmethod
    def from_env(cls) -> "ReactConfig":
        return cls(
            single_agent_max_iterations=_env_int("GALAXY_AGENT_MAX_ITERATIONS", 8),
            team_member_max_iterations=_env_int("GALAXY_TEAM_MAX_ITERATIONS", 6),
            manifest_max_turns=_env_int("GALAXY_MANIFEST_MAX_TURNS", 10),
            reflection_enabled=_env_bool("GALAXY_AGENT_REFLECTION", True),
            max_reflection_rounds=_env_int("GALAXY_AGENT_MAX_REFLECTION", 1),
            loop_detection_window=_env_int("GALAXY_AGENT_LOOP_WINDOW", 2),
        )


def tool_call_signature(tool_calls: List[Dict[str, Any]]) -> str:
    """为一轮 tool_calls 生成稳定签名，用于环路检测。

    采用工具名 + 原始参数串（OpenAI 风格 ``function.name`` / ``function.arguments``）。
    """
    parts: List[str] = []
    for tc in tool_calls or []:
        func = tc.get("function", {}) if isinstance(tc, dict) else {}
        parts.append(f"{func.get('name', '')}:{func.get('arguments', '')}")
    return "|".join(parts)


def is_repeating(history: List[str], window: int) -> bool:
    """最近 ``window`` 次 tool-call 签名是否全部相同（且非空）。"""
    if window <= 0 or len(history) < window:
        return False
    recent = history[-window:]
    return all(s and s == recent[0] for s in recent)


@dataclass
class ToolLoopResult:
    final_response: Any  # 最后一次 LLM 响应对象（调用方据此取 content/provider）
    iterations: int  # 实际 LLM 调用轮数
    reflection_rounds: int  # 反思触发轮数
    stop_reason: str  # "final" | "max_iterations" | "loop_detected"


async def run_react_tool_loop(
    *,
    messages: List[Dict[str, Any]],
    llm_call: Callable[[List[Dict[str, Any]]], Awaitable[Any]],
    dispatch_tool: Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]],
    max_iterations: int,
    on_tool_result: Optional[Callable[[str, Dict[str, Any], Dict[str, Any], int], None]] = None,
    reflect: Optional[Callable[[str], Awaitable[Optional[Dict[str, Any]]]]] = None,
    max_reflection_rounds: int = 0,
    loop_detection_window: int = 2,
) -> ToolLoopResult:
    """统一的 native function-calling ReAct 循环（供同构的两处复用）。

    Args:
        messages: 对话消息列表（原地追加 assistant/tool 轮次）。
        llm_call: ``async (messages) -> resp``；调用方在闭包内处理 tools/provider/
            model/熔断器/token 计数等差异。resp 需有 ``.tool_calls`` 与 ``.content``。
        dispatch_tool: ``async (name, args) -> dict``；调用方在闭包内处理单工具
            超时等差异；约定返回 ``{"success","result"/"error",...}``。
        on_tool_result: 可选副作用回调（记录 ToolCallRecord / 累计 token 等）。
        reflect: 可选反思回调 ``async (final_content) -> {"sufficient","critique"} | None``；
            返回 None 即放行（反思绝不阻断交付）。
        max_reflection_rounds: 反思最多触发轮数（消耗同一 max_iterations 预算）。
        loop_detection_window: 连续相同 tool-call 签名达此次数即终止（0 关闭）。
    """
    resp: Any = None
    iteration = 0
    reflection_rounds = 0
    sig_history: List[str] = []

    while iteration < max_iterations:
        resp = await llm_call(messages)
        iteration += 1

        tool_calls = getattr(resp, "tool_calls", None)
        if not tool_calls:
            # 候选最终答案 —— 反思自检（有界；任何 None/异常都放行）
            if reflect is not None and reflection_rounds < max_reflection_rounds and iteration < max_iterations:
                content = getattr(resp, "content", "") or ""
                try:
                    verdict = await reflect(content)
                except Exception as exc:  # noqa: BLE001 — 反思失败必须放行
                    logger.debug("reflect callback failed (released): %s", exc)
                    verdict = None
                if verdict and not verdict.get("sufficient", True):
                    reflection_rounds += 1
                    critique = verdict.get("critique", "") or "结果可能不完整，请补全并复核后再给出最终答案。"
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"[自检] 上述回答存在不足：{critique}\n请据此修正或补全，然后给出最终结果。",
                        }
                    )
                    continue
            return ToolLoopResult(resp, iteration, reflection_rounds, "final")

        # 环路检测：模型在相同工具+参数上空转 → 提前终止，避免耗尽预算
        sig_history.append(tool_call_signature(tool_calls))
        if is_repeating(sig_history, loop_detection_window):
            logger.info(
                "ReAct loop-detection triggered (window=%d) — stopping early at iter=%d",
                loop_detection_window,
                iteration,
            )
            return ToolLoopResult(resp, iteration, reflection_rounds, "loop_detected")

        # 装配 assistant(tool_calls) 轮
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": resp.content or ""}
        assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # 逐个执行工具
        for tc in tool_calls:
            tc_func = tc.get("function", {})
            tc_name = tc_func.get("name", "")
            tc_id = tc.get("id", f"call_{tc_name}")
            import json as _json

            try:
                tc_args = _json.loads(tc_func.get("arguments", "{}"))
            except (ValueError, TypeError):
                tc_args = {}

            result = await dispatch_tool(tc_name, tc_args)
            if on_tool_result is not None:
                try:
                    on_tool_result(tc_name, tc_args, result, iteration - 1)
                except Exception as exc:  # noqa: BLE001 — 记录副作用不应中断循环
                    logger.debug("on_tool_result hook failed: %s", exc)

            result_str = str(result.get("result", result.get("error", "")))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_str[:4000],
                }
            )

    return ToolLoopResult(resp, iteration, reflection_rounds, "max_iterations")
