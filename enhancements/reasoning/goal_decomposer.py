"""
LLM 驱动的目标分解器 (Goal Decomposer)
========================================

将高层次目标分解为可执行的子任务。

两种工作模式：
1. LLM 模式（优先）- 用大模型理解目标语义并智能分解
2. 规则模式（降级）- 基于关键词和模板的分解（无 LLM 时自动降级）
"""

import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class GoalType(Enum):
    """目标类型"""
    INFORMATION_GATHERING = "information_gathering"
    TASK_EXECUTION = "task_execution"
    PROBLEM_SOLVING = "problem_solving"
    CREATION = "creation"
    AUTOMATION = "automation"
    MULTI_DEVICE = "multi_device"
    ANALYSIS = "analysis"


class SubTaskType(Enum):
    """子任务类型"""
    SEARCH = "search"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ANALYZE = "analyze"
    SYNTHESIZE = "synthesize"
    CONTROL_DEVICE = "control_device"
    COMMUNICATE = "communicate"
    PLAN = "plan"
    VALIDATE = "validate"


@dataclass
class SubTask:
    """子任务"""
    id: str
    type: SubTaskType
    description: str
    dependencies: List[str]  # 依赖的子任务 ID
    required_capabilities: List[str]
    estimated_duration: int  # 秒
    priority: int  # 1-10, 10 最高
    metadata: Dict = field(default_factory=dict)
    assignee_hint: str = ""  # 建议的执行者


@dataclass
class Goal:
    """目标"""
    description: str
    type: GoalType = GoalType.TASK_EXECUTION
    constraints: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    deadline: Optional[int] = None  # Unix timestamp
    context: Dict = field(default_factory=dict)


@dataclass
class DecompositionResult:
    """分解结果"""
    goal: Goal
    subtasks: List[SubTask]
    execution_order: List[str]  # 子任务 ID 的执行顺序
    estimated_total_duration: int
    decomposition_strategy: str = ""  # 分解策略说明
    parallelizable_groups: List[List[str]] = field(default_factory=list)  # 可并行的子任务组


class GoalDecomposer:
    """
    LLM 驱动的目标分解器

    优先使用 LLM 进行语义理解和智能分解，
    LLM 不可用时降级到基于规则的分解。
    """

    def __init__(self, llm_router=None):
        self.llm_router = llm_router
        self._mode = "llm" if llm_router else "rule"
        logger.info(f"GoalDecomposer 已初始化 (模式: {self._mode})")

    async def decompose_async(self, goal: Goal) -> DecompositionResult:
        """异步分解目标（优先使用 LLM）"""
        logger.info(f"开始分解目标: {goal.description}")

        if self.llm_router:
            try:
                return await self._decompose_with_llm(goal)
            except Exception as e:
                logger.warning(f"LLM 分解失败: {e}，降级到规则分解")

        return self.decompose(goal)

    async def _decompose_with_llm(self, goal: Goal) -> DecompositionResult:
        """用 LLM 分解目标"""
        prompt = self._build_decomposition_prompt(goal)

        result = await self.llm_router.chat_json(
            messages=[
                {"role": "system", "content": (
                    "你是一个任务分解专家。将用户的高层目标分解为具体可执行的子任务。\n"
                    "考虑任务之间的依赖关系、所需能力和执行顺序。\n"
                    "返回严格的 JSON 格式。"
                )},
                {"role": "user", "content": prompt},
            ],
            task_type="planning",
        )

        # 解析 LLM 响应
        subtasks = []
        for i, st_data in enumerate(result.get("subtasks", [])):
            try:
                st_type = SubTaskType(st_data.get("type", "execute"))
            except ValueError:
                st_type = SubTaskType.EXECUTE

            subtasks.append(SubTask(
                id=st_data.get("id", f"st_{i}"),
                type=st_type,
                description=st_data.get("description", ""),
                dependencies=st_data.get("dependencies", []),
                required_capabilities=st_data.get("required_capabilities", []),
                estimated_duration=st_data.get("estimated_duration", 60),
                priority=st_data.get("priority", 5),
                metadata=st_data.get("metadata", {}),
                assignee_hint=st_data.get("assignee_hint", ""),
            ))

        # 确定执行顺序
        execution_order = self._determine_execution_order(subtasks)

        # 识别可并行组
        parallel_groups = self._identify_parallel_groups(subtasks)

        goal_type_str = result.get("goal_type", "task_execution")
        try:
            goal.type = GoalType(goal_type_str)
        except ValueError:
            pass

        return DecompositionResult(
            goal=goal,
            subtasks=subtasks,
            execution_order=execution_order,
            estimated_total_duration=sum(st.estimated_duration for st in subtasks),
            decomposition_strategy=result.get("strategy", "LLM 智能分解"),
            parallelizable_groups=parallel_groups,
        )

    def _build_decomposition_prompt(self, goal: Goal) -> str:
        constraints_str = "\n".join(f"  - {c}" for c in goal.constraints) if goal.constraints else "无"
        criteria_str = "\n".join(f"  - {c}" for c in goal.success_criteria) if goal.success_criteria else "无"
        context_str = json.dumps(goal.context, ensure_ascii=False, indent=2) if goal.context else "无"

        return f"""请将以下目标分解为具体可执行的子任务。

目标: {goal.description}
约束条件:
{constraints_str}
成功标准:
{criteria_str}
上下文:
{context_str}

请返回 JSON:
{{
    "goal_type": "information_gathering|task_execution|problem_solving|creation|automation|multi_device|analysis",
    "strategy": "分解策略的简要说明",
    "subtasks": [
        {{
            "id": "st_0",
            "type": "search|read|write|execute|analyze|synthesize|control_device|communicate|plan|validate",
            "description": "具体描述",
            "dependencies": [],
            "required_capabilities": ["capability_1"],
            "estimated_duration": 60,
            "priority": 10,
            "assignee_hint": "建议由谁执行 (agent类型)",
            "metadata": {{}}
        }}
    ]
}}

要求：
1. 子任务要足够具体，每个子任务可以独立执行
2. 正确标注依赖关系（哪些任务必须先完成）
3. 可以并行的任务不要添加不必要的依赖
4. 合理估算每个子任务的执行时间（秒）
5. 优先级 1-10，10 最高"""

    def _identify_parallel_groups(self, subtasks: List[SubTask]) -> List[List[str]]:
        """识别可以并行执行的子任务组"""
        groups = []
        used = set()

        # 找出没有依赖或依赖相同的子任务
        dep_map = {st.id: tuple(sorted(st.dependencies)) for st in subtasks}

        # 按依赖分组
        dep_groups: Dict[tuple, List[str]] = {}
        for st in subtasks:
            key = tuple(sorted(st.dependencies))
            if key not in dep_groups:
                dep_groups[key] = []
            dep_groups[key].append(st.id)

        for deps, task_ids in dep_groups.items():
            if len(task_ids) > 1:
                groups.append(task_ids)

        return groups

    # ─────── 规则模式（降级）─────────

    def decompose(self, goal: Goal) -> DecompositionResult:
        """同步分解目标（规则模式）"""
        goal_type = self._identify_goal_type(goal)
        goal.type = goal_type
        logger.info(f"目标类型: {goal_type.value}")

        subtasks = self._generate_subtasks(goal, goal_type)
        execution_order = self._determine_execution_order(subtasks)
        total_duration = sum(st.estimated_duration for st in subtasks)

        return DecompositionResult(
            goal=goal,
            subtasks=subtasks,
            execution_order=execution_order,
            estimated_total_duration=total_duration,
            decomposition_strategy="基于规则的分解",
        )

    def _identify_goal_type(self, goal: Goal) -> GoalType:
        """识别目标类型"""
        description_lower = goal.description.lower()

        if any(kw in description_lower for kw in ['查找', '搜索', '了解', 'find', 'search', 'learn']):
            return GoalType.INFORMATION_GATHERING
        if any(kw in description_lower for kw in ['创建', '生成', '设计', 'create', 'generate', 'design']):
            return GoalType.CREATION
        if any(kw in description_lower for kw in ['解决', '修复', '调试', 'solve', 'fix', 'debug']):
            return GoalType.PROBLEM_SOLVING
        if any(kw in description_lower for kw in ['自动化', '定时', 'automate', 'schedule']):
            return GoalType.AUTOMATION
        if any(kw in description_lower for kw in ['分析', '评估', 'analyze', 'evaluate']):
            return GoalType.ANALYSIS
        if any(kw in description_lower for kw in ['设备', '无人机', '打印', 'device', 'drone']):
            return GoalType.MULTI_DEVICE

        return GoalType.TASK_EXECUTION

    def _generate_subtasks(self, goal: Goal, goal_type: GoalType) -> List[SubTask]:
        """生成子任务（规则模式）"""
        generators = {
            GoalType.INFORMATION_GATHERING: self._gen_information_subtasks,
            GoalType.CREATION: self._gen_creation_subtasks,
            GoalType.PROBLEM_SOLVING: self._gen_problem_solving_subtasks,
            GoalType.AUTOMATION: self._gen_automation_subtasks,
            GoalType.ANALYSIS: self._gen_analysis_subtasks,
        }
        generator = generators.get(goal_type, self._gen_generic_subtasks)
        return generator(goal)

    def _gen_information_subtasks(self, goal: Goal) -> List[SubTask]:
        return [
            SubTask(id="st_0", type=SubTaskType.SEARCH,
                    description=f"搜索相关信息: {goal.description}",
                    dependencies=[], required_capabilities=['web_search', 'information_retrieval'],
                    estimated_duration=30, priority=10),
            SubTask(id="st_1", type=SubTaskType.READ,
                    description="阅读和理解搜索结果",
                    dependencies=["st_0"], required_capabilities=['text_understanding'],
                    estimated_duration=60, priority=9),
            SubTask(id="st_2", type=SubTaskType.SYNTHESIZE,
                    description="综合信息并生成报告",
                    dependencies=["st_1"], required_capabilities=['text_generation', 'analysis'],
                    estimated_duration=45, priority=8),
        ]

    def _gen_creation_subtasks(self, goal: Goal) -> List[SubTask]:
        return [
            SubTask(id="st_0", type=SubTaskType.ANALYZE,
                    description=f"分析创作需求: {goal.description}",
                    dependencies=[], required_capabilities=['requirement_analysis'],
                    estimated_duration=30, priority=10),
            SubTask(id="st_1", type=SubTaskType.WRITE,
                    description="生成初稿",
                    dependencies=["st_0"], required_capabilities=['content_generation'],
                    estimated_duration=120, priority=9),
            SubTask(id="st_2", type=SubTaskType.VALIDATE,
                    description="评估和优化",
                    dependencies=["st_1"], required_capabilities=['quality_assessment'],
                    estimated_duration=60, priority=8),
        ]

    def _gen_problem_solving_subtasks(self, goal: Goal) -> List[SubTask]:
        return [
            SubTask(id="st_0", type=SubTaskType.ANALYZE,
                    description=f"分析问题: {goal.description}",
                    dependencies=[], required_capabilities=['problem_analysis'],
                    estimated_duration=45, priority=10),
            SubTask(id="st_1", type=SubTaskType.SEARCH,
                    description="搜索解决方案",
                    dependencies=["st_0"], required_capabilities=['web_search'],
                    estimated_duration=30, priority=9),
            SubTask(id="st_2", type=SubTaskType.EXECUTE,
                    description="执行解决方案",
                    dependencies=["st_1"], required_capabilities=['task_execution'],
                    estimated_duration=90, priority=8),
            SubTask(id="st_3", type=SubTaskType.VALIDATE,
                    description="验证解决方案",
                    dependencies=["st_2"], required_capabilities=['testing'],
                    estimated_duration=30, priority=7),
        ]

    def _gen_automation_subtasks(self, goal: Goal) -> List[SubTask]:
        return [
            SubTask(id="st_0", type=SubTaskType.ANALYZE,
                    description=f"分析自动化需求: {goal.description}",
                    dependencies=[], required_capabilities=['workflow_analysis'],
                    estimated_duration=30, priority=10),
            SubTask(id="st_1", type=SubTaskType.WRITE,
                    description="编写自动化脚本",
                    dependencies=["st_0"], required_capabilities=['code_generation'],
                    estimated_duration=120, priority=9),
            SubTask(id="st_2", type=SubTaskType.EXECUTE,
                    description="测试自动化脚本",
                    dependencies=["st_1"], required_capabilities=['testing'],
                    estimated_duration=60, priority=8),
            SubTask(id="st_3", type=SubTaskType.EXECUTE,
                    description="部署自动化任务",
                    dependencies=["st_2"], required_capabilities=['deployment'],
                    estimated_duration=30, priority=7),
        ]

    def _gen_analysis_subtasks(self, goal: Goal) -> List[SubTask]:
        return [
            SubTask(id="st_0", type=SubTaskType.SEARCH,
                    description=f"收集数据: {goal.description}",
                    dependencies=[], required_capabilities=['data_collection'],
                    estimated_duration=45, priority=10),
            SubTask(id="st_1", type=SubTaskType.ANALYZE,
                    description="数据分析和统计",
                    dependencies=["st_0"], required_capabilities=['data_analysis', 'statistics'],
                    estimated_duration=90, priority=9),
            SubTask(id="st_2", type=SubTaskType.SYNTHESIZE,
                    description="生成分析报告",
                    dependencies=["st_1"], required_capabilities=['report_generation'],
                    estimated_duration=60, priority=8),
        ]

    def _gen_generic_subtasks(self, goal: Goal) -> List[SubTask]:
        return [
            SubTask(id="st_0", type=SubTaskType.ANALYZE,
                    description=f"分析任务: {goal.description}",
                    dependencies=[], required_capabilities=['text_understanding'],
                    estimated_duration=30, priority=10),
            SubTask(id="st_1", type=SubTaskType.EXECUTE,
                    description="执行任务",
                    dependencies=["st_0"], required_capabilities=['task_execution'],
                    estimated_duration=90, priority=9),
        ]

    def _determine_execution_order(self, subtasks: List[SubTask]) -> List[str]:
        """拓扑排序确定执行顺序"""
        dep_graph = {st.id: st.dependencies for st in subtasks}
        order = []
        visited = set()

        def visit(task_id: str):
            if task_id in visited:
                return
            visited.add(task_id)
            for dep in dep_graph.get(task_id, []):
                visit(dep)
            order.append(task_id)

        for task in subtasks:
            visit(task.id)

        return order


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    decomposer = GoalDecomposer()

    goal = Goal(
        description="了解量子计算的最新进展",
        constraints=["使用可信来源", "时间限制 10 分钟"],
        success_criteria=["获得至少 3 个关键发现"],
    )

    result = decomposer.decompose(goal)

    print(f"\n目标分解结果:")
    print(f"  目标: {result.goal.description}")
    print(f"  策略: {result.decomposition_strategy}")
    print(f"  子任务数量: {len(result.subtasks)}")
    print(f"  执行顺序: {' -> '.join(result.execution_order)}")
    print(f"  预计时长: {result.estimated_total_duration} 秒")
    print(f"\n子任务详情:")
    for st in result.subtasks:
        print(f"  - {st.id}: {st.description}")
        print(f"    依赖: {st.dependencies or '无'}")
        print(f"    能力: {', '.join(st.required_capabilities)}")
