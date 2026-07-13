"""core/liminal_rehearsal.py — 阈限态预演(Gecko 借鉴 · 阶段二/三)
====================================================================

借鉴 ICML'26 Gecko(camel-ai)的状态化模拟环境思想,落进本系统三态架构的
**阈限态(LIMINAL)**语义:智能体在真正落手(MANIFEST)之前,先在一个
可反馈、可重试、可维护状态的沙盘里推演工具调用计划——这正是阈限态最初的
设计意图(推演空间),此前只做了意图分类,没有做计划预演。

组件对应(Gecko → 本模块):

  - Argument Validator      → core.tool_call_validator(规则层+语义层)
  - Response Generator      → :meth:`ShadowToolSimulator.simulate_call`
                              (LLM 按 schema+影子状态生成模拟响应)
  - Task State Estimator    → :class:`ShadowState`(纯内存影子状态,
                              每次重试从同一初始快照开始——失败尝试绝不
                              污染后续,更绝不触碰真实世界)
  - Task Feedback Generator → :meth:`LiminalRehearsal._judge`(任务级完成度
                              判断,未完成给出原因反馈进下一轮)
  - Hybrid Adaptation       → 只读工具直通真实派发(信息一致性),写状态
                              工具一律模拟(安全);风险分层复用既有
                              tool_call_validator 的只读/高风险判定,与
                              HITL 审批门同一语义家族。

产出:预演成功的轨迹作为 in-context 指导注入真实 ReAct(GATS 思路),
让真实执行"按剧本走,遇偏差再自调"。

可打断(阶段三):预演跑在请求任务里,面板 barge-in/超时取消即
asyncio.CancelledError,预演立即终止且零真实副作用;每步经 StateEventBus
的 skill.invoked 事件推到面板(payload.kind="rehearsal", simulated=True),
推演过程可见。

成本闸门:GALAXY_LIMINAL_REHEARSAL = 0(关) | 1(凡有工具即预演) |
auto(默认:复杂度 ≥ GALAXY_REHEARSAL_COMPLEXITY_FLOOR 且有工具才预演)。
预演的模拟器/裁判走路由级联便宜档,不占本地 CPU 主脑。
"""
from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LiminalRehearsal")


def rehearsal_mode() -> str:
    return os.environ.get("GALAXY_LIMINAL_REHEARSAL", "auto").strip().lower()


def _complexity_floor() -> float:
    try:
        return float(os.environ.get("GALAXY_REHEARSAL_COMPLEXITY_FLOOR", "0.55"))
    except (TypeError, ValueError):
        return 0.55


def should_rehearse(complexity: float, tools: Optional[List[Dict[str, Any]]]) -> bool:
    """预演触发判定:关/强制/auto(复杂度门槛 + 有工具可调)。"""
    mode = rehearsal_mode()
    if mode in ("0", "false", "no", "off"):
        return False
    if not tools:
        return False
    if mode in ("1", "true", "yes", "on", "always"):
        return True
    return complexity >= _complexity_floor()


def _emit_rehearsal_event(step: str, payload: Dict[str, Any]) -> None:
    """预演过程可见化:经既有 skill.invoked 事件族上面板(面板推送允许清单
    含 "skill." 族)。payload 恒带 kind="rehearsal" + simulated=True,消费方
    可与真实工具调用区分——语义即"(模拟)工具调用活动"。"""
    try:
        from core.state_event_bus import emit as _emit, StateEventType
        _emit(
            StateEventType.SKILL_INVOKED,
            source="liminal_rehearsal",
            payload={"kind": "rehearsal", "simulated": True, "step": step, **payload},
        )
    except Exception as exc:  # noqa: BLE001 — 可见化失败绝不影响预演
        logger.debug("预演事件发布失败(忽略): %s", exc)


@dataclass
class ShadowState:
    """影子任务状态:纯内存、可快照重置——失败尝试不污染后续,不碰真实世界。"""
    facts: Dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self.facts)

    def restore(self, snap: Dict[str, Any]) -> None:
        self.facts = copy.deepcopy(snap)

    def apply_delta(self, delta: Optional[Dict[str, Any]]) -> None:
        if isinstance(delta, dict):
            self.facts.update(delta)

    def render(self, max_chars: int = 1200) -> str:
        try:
            return json.dumps(self.facts, ensure_ascii=False)[:max_chars]
        except Exception:  # noqa: BLE001
            return str(self.facts)[:max_chars]


class ShadowToolSimulator:
    """模拟派发器(hybrid):只读直通真实派发,写状态由 LLM 按 schema+影子状态
    生成模拟响应并给出状态增量。"""

    def __init__(self, real_dispatch, router: Any, state: ShadowState,
                 tools: Optional[List[Dict[str, Any]]] = None) -> None:
        self._real_dispatch = real_dispatch  # async (name, args) -> dict
        self._router = router
        self.state = state
        self._tools = tools or []

    def _schema_of(self, tool_name: str) -> Dict[str, Any]:
        for t in self._tools:
            fn = t.get("function") if isinstance(t, dict) else None
            if isinstance(fn, dict) and fn.get("name") == tool_name:
                return fn
        return {"name": tool_name}

    async def simulate_call(self, tool_name: str, args: Dict[str, Any],
                            task: str) -> Dict[str, Any]:
        from core.tool_call_validator import is_read_only_tool

        if is_read_only_tool(tool_name) and self._real_dispatch is not None:
            # Hybrid:只读工具直通真实系统,消除"隐藏数据库"带来的模拟偏差。
            try:
                result = await self._real_dispatch(tool_name, args)
                return {"simulated": False, "result": result}
            except Exception as exc:  # noqa: BLE001 — 真实只读失败按失败回喂
                return {"simulated": False,
                        "result": {"success": False, "error": str(exc)[:300]}}

        # 写状态工具:LLM 生成 schema 一致、且与影子状态连贯的模拟响应。
        prompt = (
            "你是工具执行模拟器。根据工具定义、调用参数、任务与当前任务状态,"
            "生成这次调用【最可能的】返回结果,并给出它对任务状态的增量。\n"
            "只回 JSON: {\"response\": <模拟返回,尽量贴合工具真实返回形状>, "
            "\"state_delta\": {<状态键值增量,没有就 {}>}}\n"
            f"任务: {task[:400]}\n"
            f"工具定义: {json.dumps(self._schema_of(tool_name), ensure_ascii=False)[:800]}\n"
            f"调用参数: {json.dumps(args, ensure_ascii=False)[:600]}\n"
            f"当前任务状态: {self.state.render()}"
        )
        try:
            resp = await self._router.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=500,
            )
            text = (getattr(resp, "content", "") or "").strip()
            start, end = text.find("{"), text.rfind("}")
            data = json.loads(text[start:end + 1]) if start >= 0 <= end else {}
        except Exception as exc:  # noqa: BLE001 — 模拟失败给出通用成功壳
            logger.debug("模拟响应生成失败(用通用壳): %s", exc)
            data = {}
        sim_result = data.get("response", {"success": True, "simulated_note": "ok"})
        self.state.apply_delta(data.get("state_delta"))
        return {"simulated": True, "result": sim_result}


@dataclass
class RehearsalOutcome:
    success: bool
    attempts: int
    trajectory: List[Dict[str, Any]] = field(default_factory=list)  # 成功轨迹
    feedback_history: List[str] = field(default_factory=list)
    final_state: Dict[str, Any] = field(default_factory=dict)

    def guidance_text(self, max_chars: int = 2000) -> str:
        """成功轨迹 → 真实执行的 in-context 指导(GATS)。"""
        if not self.success or not self.trajectory:
            return ""
        lines = []
        for i, step in enumerate(self.trajectory, 1):
            lines.append(
                f"{i}. {step['tool']}({json.dumps(step['args'], ensure_ascii=False)[:200]})"
                f" → {json.dumps(step.get('result', ''), ensure_ascii=False)[:150]}"
            )
        body = "\n".join(lines)
        return (
            "[阈限态预演·成功轨迹] 以下计划已在模拟环境中验证可完成任务,"
            "请按此顺序执行;若真实返回与预演不符,再自行调整:\n" + body
        )[:max_chars]


class LiminalRehearsal:
    """预演循环:影子 ReAct → 校验/模拟/状态更新 → 任务级裁判 → 反馈重试。"""

    def __init__(self, router: Any, real_dispatch=None,
                 tools: Optional[List[Dict[str, Any]]] = None,
                 max_attempts: int = 2, max_steps: int = 6) -> None:
        self._router = router
        self._real_dispatch = real_dispatch
        self._tools = tools or []
        self._max_attempts = max(1, max_attempts)
        self._max_steps = max(1, max_steps)

    async def _judge(self, task: str, trajectory: List[Dict[str, Any]],
                     state: ShadowState) -> Dict[str, Any]:
        """任务级反馈(不是单次调用报错,而是"目标完成了吗、差什么")。"""
        prompt = (
            "你是任务完成度裁判。根据任务目标、已执行的(模拟)工具调用轨迹和"
            "当前任务状态,判断任务是否已经完成。只回 JSON: "
            "{\"complete\": true} 或 {\"complete\": false, \"feedback\": \"还差什么/哪里不对\"}\n"
            f"任务: {task[:400]}\n"
            f"轨迹: {json.dumps(trajectory, ensure_ascii=False)[:1500]}\n"
            f"任务状态: {state.render()}"
        )
        try:
            resp = await self._router.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=200,
            )
            text = (getattr(resp, "content", "") or "").strip()
            start, end = text.find("{"), text.rfind("}")
            return json.loads(text[start:end + 1]) if start >= 0 <= end else {"complete": False, "feedback": "裁判输出不可解析"}
        except Exception as exc:  # noqa: BLE001 — 裁判失败视为未完成(保守)
            return {"complete": False, "feedback": f"裁判不可用: {exc}"[:200]}

    async def rehearse(self, task: str) -> RehearsalOutcome:
        from core.tool_call_validator import (
            is_high_risk_tool,
            semantic_check,
            validate_tool_call,
        )

        state = ShadowState()
        initial_snap = state.snapshot()
        outcome = RehearsalOutcome(success=False, attempts=0)

        for attempt in range(1, self._max_attempts + 1):
            outcome.attempts = attempt
            state.restore(initial_snap)  # 失败尝试不污染后续:同一初始快照
            sim = ShadowToolSimulator(self._real_dispatch, self._router, state, self._tools)
            trajectory: List[Dict[str, Any]] = []
            _emit_rehearsal_event("attempt_start", {"attempt": attempt, "task": task[:120]})

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": (
                    "你正在【模拟环境】中预演工具调用计划(不会产生真实副作用)。"
                    "逐步调用工具完成任务;完成后不再调用工具,直接说明结果。"
                )},
                {"role": "user", "content": task},
            ]
            for fb in outcome.feedback_history[-2:]:
                messages.append({"role": "system",
                                 "content": f"[上一轮预演反馈] {fb[:400]}"})

            for _step in range(self._max_steps):
                resp = await self._router.chat_with_tools(
                    messages=messages, tools=self._tools, max_tokens=1024,
                )
                if not getattr(resp, "tool_calls", None):
                    break  # 模型认为完成 → 交给裁判
                messages.append({
                    "role": "assistant",
                    "content": resp.content or "",
                    "tool_calls": resp.tool_calls,
                })
                for tc in resp.tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    tc_id = tc.get("id", f"sim_{name}")
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except (ValueError, TypeError):
                        args = {}

                    check = validate_tool_call(name, args, self._tools)
                    if check.valid and is_high_risk_tool(name):
                        check = await semantic_check(name, args, task, router=self._router)
                    if not check.valid:
                        messages.append({"role": "tool", "tool_call_id": tc_id,
                                         "content": check.feedback_text()[:1500]})
                        _emit_rehearsal_event("validation_reject",
                                              {"attempt": attempt, "tool": name})
                        continue

                    sim_out = await sim.simulate_call(name, args, task)
                    trajectory.append({
                        "tool": name, "args": args,
                        "result": sim_out.get("result"),
                        "simulated": sim_out.get("simulated", True),
                    })
                    _emit_rehearsal_event("tool_simulated", {
                        "attempt": attempt, "tool": name,
                        "simulated": sim_out.get("simulated", True),
                    })
                    messages.append({
                        "role": "tool", "tool_call_id": tc_id,
                        "content": json.dumps(sim_out.get("result"),
                                              ensure_ascii=False)[:2000],
                    })

            verdict = await self._judge(task, trajectory, state)
            if verdict.get("complete"):
                outcome.success = True
                outcome.trajectory = trajectory
                outcome.final_state = state.snapshot()
                _emit_rehearsal_event("attempt_success",
                                      {"attempt": attempt, "steps": len(trajectory)})
                return outcome
            fb = str(verdict.get("feedback", ""))[:400]
            outcome.feedback_history.append(fb)
            _emit_rehearsal_event("attempt_failed",
                                  {"attempt": attempt, "feedback": fb[:200]})
            logger.info("预演第 %d 轮未完成: %s", attempt, fb[:160])

        return outcome
