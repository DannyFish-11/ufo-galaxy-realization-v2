"""
LLM 驱动的自主规划器 (Autonomous Planner)
==========================================

根据分解的子任务生成可执行的计划。

两种模式：
1. LLM 模式 - 大模型理解上下文并生成智能计划
2. 规则模式 - 基于资源匹配的简单规划
"""

import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

from .goal_decomposer import SubTask, DecompositionResult

logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """资源类型"""
    NODE = "node"
    DEVICE = "device"
    API = "api"
    TOOL = "tool"
    AGENT = "agent"


@dataclass
class Resource:
    """资源"""
    id: str
    type: ResourceType
    name: str
    capabilities: List[str]
    availability: float  # 0-1
    metadata: Dict = field(default_factory=dict)


@dataclass
class Action:
    """动作"""
    id: str
    subtask_id: str
    node_id: Optional[str]
    device_id: Optional[str]
    command: str
    parameters: Dict
    expected_duration: int
    fallback_actions: List['Action'] = field(default_factory=list)
    preconditions: List[str] = field(default_factory=list)
    postconditions: List[str] = field(default_factory=list)


@dataclass
class Plan:
    """计划"""
    goal_description: str
    actions: List[Action]
    execution_order: List[str]  # Action IDs
    total_estimated_duration: int
    required_resources: List[Resource]
    contingency_plans: Dict[str, List[Action]]  # 应急计划
    strategy: str = ""  # 规划策略说明
    parallel_groups: List[List[str]] = field(default_factory=list)  # 可并行的动作组


class AutonomousPlanner:
    """
    LLM 驱动的自主规划器

    优先使用 LLM 生成智能计划（考虑上下文、风险、最优路径），
    LLM 不可用时降级到基于规则的规划。
    """

    def __init__(self, available_resources: Optional[List[Resource]] = None,
                 llm_router=None):
        self.available_resources = available_resources or []
        self.llm_router = llm_router
        self._mode = "llm" if llm_router else "rule"
        logger.info(
            f"AutonomousPlanner 已初始化 (模式: {self._mode}, "
            f"资源: {len(self.available_resources)} 个)"
        )

    async def create_plan_async(self, decomposition: DecompositionResult) -> Plan:
        """异步创建计划（优先使用 LLM）"""
        logger.info(f"开始为目标创建计划: {decomposition.goal.description}")

        if self.llm_router:
            try:
                return await self._plan_with_llm(decomposition)
            except Exception as e:
                logger.warning(f"LLM 规划失败: {e}，降级到规则规划")

        return self.create_plan(decomposition)

    async def _plan_with_llm(self, decomposition: DecompositionResult) -> Plan:
        """用 LLM 生成计划"""
        prompt = self._build_planning_prompt(decomposition)

        result = await self.llm_router.chat_json(
            messages=[
                {"role": "system", "content": (
                    "你是一个执行计划专家。根据子任务列表和可用资源，"
                    "生成最优的执行计划。\n"
                    "考虑：资源利用率、并行执行机会、风险缓解、应急方案。\n"
                    "返回严格的 JSON 格式。"
                )},
                {"role": "user", "content": prompt},
            ],
            task_type="planning",
        )

        # 解析 LLM 响应
        actions = []
        for i, act_data in enumerate(result.get("actions", [])):
            fallbacks = []
            for fb_data in act_data.get("fallback_actions", []):
                fallbacks.append(Action(
                    id=fb_data.get("id", f"fb_{i}"),
                    subtask_id=act_data.get("subtask_id", f"st_{i}"),
                    node_id=fb_data.get("node_id"),
                    device_id=fb_data.get("device_id"),
                    command=fb_data.get("command", ""),
                    parameters=fb_data.get("parameters", {}),
                    expected_duration=fb_data.get("expected_duration", 30),
                ))

            actions.append(Action(
                id=act_data.get("id", f"action_{i}"),
                subtask_id=act_data.get("subtask_id", f"st_{i}"),
                node_id=act_data.get("node_id"),
                device_id=act_data.get("device_id"),
                command=act_data.get("command", ""),
                parameters=act_data.get("parameters", {}),
                expected_duration=act_data.get("expected_duration", 60),
                fallback_actions=fallbacks,
                preconditions=act_data.get("preconditions", []),
                postconditions=act_data.get("postconditions", []),
            ))

        execution_order = result.get("execution_order", [a.id for a in actions])
        parallel_groups = result.get("parallel_groups", [])
        strategy = result.get("strategy", "LLM 智能规划")

        # 构建应急计划
        contingency = {}
        for act in actions:
            if act.fallback_actions:
                contingency[act.id] = act.fallback_actions

        return Plan(
            goal_description=decomposition.goal.description,
            actions=actions,
            execution_order=execution_order,
            total_estimated_duration=sum(a.expected_duration for a in actions),
            required_resources=self._identify_required_resources(actions),
            contingency_plans=contingency,
            strategy=strategy,
            parallel_groups=parallel_groups,
        )

    def _build_planning_prompt(self, decomposition: DecompositionResult) -> str:
        subtasks_str = json.dumps([
            {
                "id": st.id,
                "type": st.type.value,
                "description": st.description,
                "dependencies": st.dependencies,
                "required_capabilities": st.required_capabilities,
                "estimated_duration": st.estimated_duration,
                "priority": st.priority,
            }
            for st in decomposition.subtasks
        ], ensure_ascii=False, indent=2)

        resources_str = json.dumps([
            {
                "id": r.id,
                "type": r.type.value,
                "name": r.name,
                "capabilities": r.capabilities,
                "availability": r.availability,
            }
            for r in self.available_resources
        ], ensure_ascii=False, indent=2)

        return f"""请为以下子任务创建最优执行计划。

目标: {decomposition.goal.description}

子任务列表:
{subtasks_str}

可用资源:
{resources_str}

请返回 JSON:
{{
    "strategy": "规划策略说明",
    "actions": [
        {{
            "id": "action_0",
            "subtask_id": "st_0",
            "node_id": "资源ID或null",
            "device_id": "设备ID或null",
            "command": "要执行的命令",
            "parameters": {{}},
            "expected_duration": 60,
            "preconditions": ["前置条件"],
            "postconditions": ["完成后的状态"],
            "fallback_actions": [
                {{
                    "id": "fb_0",
                    "command": "备用命令",
                    "parameters": {{}},
                    "expected_duration": 30
                }}
            ]
        }}
    ],
    "execution_order": ["action_0", "action_1"],
    "parallel_groups": [["action_0", "action_1"]],
    "risk_assessment": "风险评估"
}}

要求：
1. 为每个子任务分配最合适的资源
2. 尽可能并行执行无依赖的任务
3. 为关键动作提供备用方案
4. 考虑资源可用性和负载均衡"""

    # ─────── 规则模式（降级）─────────

    def create_plan(self, decomposition: DecompositionResult) -> Plan:
        """创建计划（规则模式）"""
        logger.info(f"创建计划 (规则模式): {decomposition.goal.description}")

        actions = []
        for subtask in decomposition.subtasks:
            action = self._create_action_for_subtask(subtask)
            if action:
                actions.append(action)
            else:
                logger.warning(f"无法为子任务创建动作: {subtask.id}")

        execution_order = self._determine_action_order(actions, decomposition.execution_order)
        required_resources = self._identify_required_resources(actions)
        contingency_plans = self._generate_contingency_plans(actions)

        return Plan(
            goal_description=decomposition.goal.description,
            actions=actions,
            execution_order=execution_order,
            total_estimated_duration=decomposition.estimated_total_duration,
            required_resources=required_resources,
            contingency_plans=contingency_plans,
            strategy="基于规则的资源匹配规划",
        )

    def _create_action_for_subtask(self, subtask: SubTask) -> Optional[Action]:
        """为子任务创建动作"""
        matching_resources = self._find_matching_resources(subtask.required_capabilities)

        if not matching_resources:
            # 没有精确匹配，尝试部分匹配
            matching_resources = self._find_partial_matching_resources(
                subtask.required_capabilities
            )

        best_resource = None
        if matching_resources:
            best_resource = max(matching_resources, key=lambda r: r.availability)

        command, parameters = self._generate_command(subtask, best_resource)

        return Action(
            id=f"action_{subtask.id}",
            subtask_id=subtask.id,
            node_id=best_resource.id if best_resource and best_resource.type == ResourceType.NODE else None,
            device_id=best_resource.id if best_resource and best_resource.type == ResourceType.DEVICE else None,
            command=command,
            parameters=parameters,
            expected_duration=subtask.estimated_duration,
            fallback_actions=[],
        )

    def _find_matching_resources(self, required_capabilities: List[str]) -> List[Resource]:
        """查找完全匹配的资源"""
        return [
            r for r in self.available_resources
            if all(cap in r.capabilities for cap in required_capabilities)
        ]

    def _find_partial_matching_resources(self, required_capabilities: List[str]) -> List[Resource]:
        """查找部分匹配的资源"""
        result = []
        for r in self.available_resources:
            overlap = sum(1 for cap in required_capabilities if cap in r.capabilities)
            if overlap > 0:
                result.append(r)
        return result

    def _generate_command(self, subtask: SubTask, resource: Optional[Resource]) -> tuple:
        """生成命令"""
        command_map = {
            "search": ("web_search", {"query": subtask.description}),
            "read": ("read_content", {"source": subtask.description}),
            "write": ("generate_content", {"prompt": subtask.description}),
            "execute": ("execute_task", {"task": subtask.description}),
            "analyze": ("analyze_data", {"data": subtask.description}),
            "synthesize": ("synthesize_info", {"sources": subtask.description}),
            "control_device": ("device_control", {"action": subtask.description}),
            "communicate": ("send_message", {"message": subtask.description}),
            "plan": ("create_plan", {"goal": subtask.description}),
            "validate": ("validate_result", {"target": subtask.description}),
        }

        command, params = command_map.get(subtask.type.value, ("execute_task", {}))
        params["subtask_id"] = subtask.id
        params["description"] = subtask.description
        if resource:
            params["resource_id"] = resource.id

        return command, params

    def _determine_action_order(self, actions: List[Action],
                                subtask_order: List[str]) -> List[str]:
        action_map = {a.subtask_id: a.id for a in actions}
        return [action_map[sid] for sid in subtask_order if sid in action_map]

    def _identify_required_resources(self, actions: List[Action]) -> List[Resource]:
        resource_ids = set()
        required = []
        for action in actions:
            for rid in [action.node_id, action.device_id]:
                if rid and rid not in resource_ids:
                    resource_ids.add(rid)
                    for res in self.available_resources:
                        if res.id == rid:
                            required.append(res)
                            break
        return required

    def _generate_contingency_plans(self, actions: List[Action]) -> Dict[str, List[Action]]:
        return {}

    def update_plan(self, plan: Plan, feedback: Dict) -> Plan:
        """根据反馈更新计划"""
        logger.info(f"根据反馈更新计划: {feedback}")

        if 'failed_action_id' in feedback:
            failed_id = feedback['failed_action_id']
            if failed_id in plan.contingency_plans:
                fallbacks = plan.contingency_plans[failed_id]
                # 替换失败的动作
                for i, action in enumerate(plan.actions):
                    if action.id == failed_id and fallbacks:
                        plan.actions[i] = fallbacks[0]
                        logger.info(f"使用应急方案替换: {failed_id}")
                        break

        return plan


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    from .goal_decomposer import GoalDecomposer, Goal

    resources = [
        Resource(id="node_13", type=ResourceType.NODE, name="Web Node",
                 capabilities=['web_search', 'information_retrieval'], availability=1.0),
        Resource(id="node_12", type=ResourceType.NODE, name="File Node",
                 capabilities=['read_content', 'generate_content', 'text_understanding', 'summarization'],
                 availability=1.0),
        Resource(id="node_50", type=ResourceType.NODE, name="AI Node",
                 capabilities=['text_generation', 'analysis', 'synthesize_info', 'data_analysis'],
                 availability=0.9),
    ]

    decomposer = GoalDecomposer()
    goal = Goal(description="了解量子计算的最新进展")
    decomposition = decomposer.decompose(goal)

    planner = AutonomousPlanner(available_resources=resources)
    plan = planner.create_plan(decomposition)

    print(f"\n执行计划:")
    print(f"  目标: {plan.goal_description}")
    print(f"  策略: {plan.strategy}")
    print(f"  动作数量: {len(plan.actions)}")
    print(f"  执行顺序: {' -> '.join(plan.execution_order)}")
    print(f"\n动作详情:")
    for action in plan.actions:
        print(f"  - {action.id}: {action.command}")
        print(f"    节点: {action.node_id or 'N/A'}")
        print(f"    参数: {action.parameters}")
