"""
Galaxy - Execution Planner
============================

根据意图路由结果和用户消息，生成结构化执行计划。

ExecutionPlan 包含:
  steps      — 有序执行步骤列表（每步包含工具/Agent/输入）
  agent_mode — single / team / swarm
  tools      — 本次执行所需工具列表
  rationale  — 规划依据（日志/调试用）

规划流程:
  1. 从 CapabilityRegistry 查询可用工具
  2. 如果 LLM 可用，让 LLM 生成结构化计划（JSON）
  3. 如果 LLM 不可用，根据意图标签使用规则生成简单计划
  4. 计划校验：确保每个步骤包含必要字段
"""

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Agent.ExecutionPlanner")


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class PlanStep:
    """单个执行步骤"""
    step_id: str
    description: str
    tool_name: Optional[str]           # 调用的工具名（capability_registry 中的 name）
    tool_params: Dict[str, Any]        # 工具参数
    agent_role: Optional[str] = None   # 负责此步骤的 Agent 角色（多 Agent 时）
    depends_on: List[str] = field(default_factory=list)  # 依赖的前置步骤 ID
    status: str = "pending"            # pending / running / done / failed
    output: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
            "agent_role": self.agent_role,
            "depends_on": self.depends_on,
            "status": self.status,
            "output": self.output,
            "error": self.error,
        }


@dataclass
class ExecutionPlan:
    """完整执行计划"""
    plan_id: str
    intent_label: str
    agent_mode: str                    # single / team / swarm
    steps: List[PlanStep]
    required_tools: List[str]
    rationale: str
    created_at: float = field(default_factory=time.time)
    system_prompt: str = ""            # 执行时使用的系统提示（含 SOUL）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "intent_label": self.intent_label,
            "agent_mode": self.agent_mode,
            "steps": [s.to_dict() for s in self.steps],
            "required_tools": self.required_tools,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }

    def mark_step_running(self, step_id: str) -> None:
        for s in self.steps:
            if s.step_id == step_id:
                s.status = "running"
                s.started_at = time.time()
                return

    def mark_step_done(self, step_id: str, output: Any = None) -> None:
        for s in self.steps:
            if s.step_id == step_id:
                s.status = "done"
                s.output = output
                s.completed_at = time.time()
                return

    def mark_step_failed(self, step_id: str, error: str) -> None:
        for s in self.steps:
            if s.step_id == step_id:
                s.status = "failed"
                s.error = error
                s.completed_at = time.time()
                return

    def all_done(self) -> bool:
        return all(s.status in ("done", "failed") for s in self.steps)

    def summary(self) -> Dict[str, Any]:
        done = sum(1 for s in self.steps if s.status == "done")
        failed = sum(1 for s in self.steps if s.status == "failed")
        return {
            "total": len(self.steps),
            "done": done,
            "failed": failed,
            "pending": len(self.steps) - done - failed,
        }


# ============================================================================
# ExecutionPlanner
# ============================================================================

class ExecutionPlanner:
    """
    任务执行计划生成器。

    plan() 是主入口，接受用户消息 + 意图标签 + 系统提示，
    返回 ExecutionPlan。
    """

    def __init__(self, llm_router=None, capability_registry=None):
        self._llm_router = llm_router
        self._registry = capability_registry
        logger.info(
            "ExecutionPlanner 初始化 (llm=%s, registry=%s)",
            llm_router is not None,
            capability_registry is not None,
        )

    def set_llm_router(self, llm_router) -> None:
        self._llm_router = llm_router

    def set_capability_registry(self, registry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def plan(
        self,
        message: str,
        intent_label: str,
        system_prompt: str,
        context: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutionPlan:
        """
        生成执行计划。

        Args:
            message:      用户消息
            intent_label: 意图标签（来自 IntentRouter）
            system_prompt: 执行使用的系统提示（已含 SOUL + AGENTS）
            context:      历史对话上下文（可选）

        Returns:
            ExecutionPlan
        """
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        available_tools = self._get_available_tools_summary()

        # 优先使用 LLM 生成计划
        if self._llm_router is not None:
            try:
                return await self._llm_plan(
                    plan_id, message, intent_label, system_prompt,
                    available_tools, context or [],
                )
            except Exception as e:
                logger.warning("LLM 计划生成失败，回退到规则计划: %s", e)

        # 规则兜底
        return self._rule_plan(plan_id, message, intent_label, available_tools)

    # ------------------------------------------------------------------
    # LLM 计划生成
    # ------------------------------------------------------------------

    async def _llm_plan(
        self,
        plan_id: str,
        message: str,
        intent_label: str,
        system_prompt: str,
        available_tools: List[Dict[str, str]],
        context: List[Dict[str, Any]],
    ) -> ExecutionPlan:
        """让 LLM 生成 JSON 格式执行计划"""

        tools_desc = "\n".join(
            f"  - {t['name']}: {t['description']}" for t in available_tools[:30]
        )

        planner_prompt = (
            f"{system_prompt}\n\n"
            "---\n\n"
            "# 任务规划指令\n\n"
            "你需要将用户请求拆解为有序执行步骤。\n"
            "只输出以下 JSON 格式，不加任何额外说明:\n\n"
            "{\n"
            '  "agent_mode": "single|team|swarm",\n'
            '  "rationale": "规划依据简述",\n'
            '  "steps": [\n'
            "    {\n"
            '      "step_id": "step_1",\n'
            '      "description": "步骤描述",\n'
            '      "tool_name": "工具名或null",\n'
            '      "tool_params": {},\n'
            '      "depends_on": []\n'
            "    }\n"
            "  ],\n"
            '  "required_tools": ["工具名列表"]\n'
            "}\n\n"
            f"可用工具:\n{tools_desc}\n\n"
            "规则:\n"
            "- agent_mode: 单任务用 single，多并行子任务用 team，复杂协作用 swarm\n"
            "- tool_name: 从可用工具中选择，无合适工具时填 null\n"
            "- depends_on: 填写前置步骤的 step_id 列表\n"
            "- 步骤数量适当，不超过 8 步\n"
        )

        messages = [{"role": "system", "content": planner_prompt}]
        for ctx in context[-4:]:
            messages.append(ctx)
        messages.append({"role": "user", "content": f"请为以下请求生成执行计划:\n{message}"})

        response = await self._llm_router.chat_completion(
            messages=messages,
            task_type="PLANNING",
        )
        raw = response.choices[0].message.content or ""

        # 提取 JSON（处理 LLM 在 JSON 前后添加说明文字的情况）
        def _extract_json(text: str) -> dict:
            text = text.strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"LLM 未返回有效 JSON: {text[:300]}")

        data = _extract_json(raw)

        steps = []
        for i, s in enumerate(data.get("steps", [])):
            step_id = s.get("step_id", f"step_{i+1}")
            steps.append(PlanStep(
                step_id=step_id,
                description=s.get("description", ""),
                tool_name=s.get("tool_name") or None,
                tool_params=s.get("tool_params") or {},
                depends_on=s.get("depends_on") or [],
            ))

        if not steps:
            steps = [PlanStep(
                step_id="step_1",
                description=f"执行用户请求: {message[:100]}",
                tool_name=None,
                tool_params={"message": message},
            )]

        return ExecutionPlan(
            plan_id=plan_id,
            intent_label=intent_label,
            agent_mode=data.get("agent_mode", "single"),
            steps=steps,
            required_tools=data.get("required_tools") or [],
            rationale=data.get("rationale", "LLM 生成计划"),
            system_prompt=system_prompt,
        )

    # ------------------------------------------------------------------
    # 规则计划生成（LLM 不可用时兜底）
    # ------------------------------------------------------------------

    def _rule_plan(
        self,
        plan_id: str,
        message: str,
        intent_label: str,
        available_tools: List[Dict[str, str]],
    ) -> ExecutionPlan:
        """根据意图标签生成简单规则计划"""

        _label_to_tool = {
            "device_control": "node_adb_device",
            "file_operation": "node_filesystem",
            "code": "node_code_execute",
            "search": "node_web_search",
            "task_manage": None,
        }

        tool_name = _label_to_tool.get(intent_label)
        # 确认工具已注册
        if tool_name and self._registry and not self._registry.has_tool(tool_name):
            tool_name = None

        steps = [
            PlanStep(
                step_id="step_1",
                description=f"执行 {intent_label} 类型任务: {message[:80]}",
                tool_name=tool_name,
                tool_params={"message": message},
            )
        ]
        if tool_name is None:
            steps.append(PlanStep(
                step_id="step_2",
                description="汇总结果并回复用户",
                tool_name=None,
                tool_params={"message": message},
                depends_on=["step_1"],
            ))

        return ExecutionPlan(
            plan_id=plan_id,
            intent_label=intent_label,
            agent_mode="single",
            steps=steps,
            required_tools=[tool_name] if tool_name else [],
            rationale=f"规则计划（label={intent_label}, llm_unavailable=True）",
        )

    # ------------------------------------------------------------------
    # 工具摘要
    # ------------------------------------------------------------------

    def _get_available_tools_summary(self) -> List[Dict[str, str]]:
        """从 capability_registry 获取可用工具摘要（名称+描述）"""
        if self._registry is None:
            return []
        tools = self._registry.list_tools(available_only=True)
        return [{"name": t["name"], "description": t["description"]} for t in tools]
