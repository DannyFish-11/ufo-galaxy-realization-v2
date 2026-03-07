"""
分形 Agent 系统 (Fractal Agent System)
=======================================

核心思想：每个 Agent 既是一个独立的执行单元，也是一个可以递归分解的系统。
Agent 接收任务 → 判断是否需要分解 → 如果需要则创建子 Agent → 子 Agent 递归执行 → 汇总结果。

分形特征：
- 自相似性：每个层级的 Agent 都有相同的 "接收-分解-执行-汇总" 结构
- 自组织：Agent 根据任务复杂度自动决定分解策略
- 尺度不变：从单个 Agent 到整个集群，运作逻辑一致
"""

import asyncio
import json
import logging
import time
import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Galaxy.FractalAgent")


# ───────────────────── 数据模型 ─────────────────────

class Complexity(Enum):
    """任务复杂度"""
    ATOMIC = "atomic"        # 原子任务，不可分解
    SIMPLE = "simple"        # 简单，2-3 步
    MODERATE = "moderate"    # 中等，需要分解
    COMPLEX = "complex"      # 复杂，需要多层分解
    EPIC = "epic"            # 史诗级，需要大规模协作


@dataclass
class FractalTask:
    """分形任务"""
    id: str
    description: str
    context: Dict = field(default_factory=dict)
    complexity: Complexity = Complexity.ATOMIC
    parent_task_id: Optional[str] = None
    subtask_ids: List[str] = field(default_factory=list)
    result: Optional[Any] = None
    error: Optional[str] = None
    depth: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class FractalResult:
    """分形执行结果"""
    task_id: str
    success: bool
    output: Any
    depth: int
    subtask_results: List['FractalResult'] = field(default_factory=list)
    agent_id: str = ""
    latency_ms: float = 0
    decomposition_used: bool = False


# ───────────────────── 分形 Agent ─────────────────────

class FractalAgent:
    """
    分形 Agent

    核心执行循环：
    1. 接收任务
    2. 评估复杂度 (用 LLM 或规则)
    3. 如果是原子任务 → 直接执行
    4. 如果是复杂任务 → 分解为子任务 → 创建子 Agent → 并行执行 → 汇总结果
    5. 递归，直到所有子任务都是原子任务
    """

    MAX_DEPTH = 4
    MAX_SUBTASKS = 6

    def __init__(self, agent_id: str = None, llm_router=None,
                 agent_factory=None, depth: int = 0,
                 role: str = "general", parent_id: str = None):
        self.id = agent_id or f"fractal_{uuid.uuid4().hex[:8]}"
        self.llm_router = llm_router
        self.agent_factory = agent_factory
        self.depth = depth
        self.role = role
        self.parent_id = parent_id
        self.children: Dict[str, 'FractalAgent'] = {}
        self.tasks_executed: int = 0
        self.total_latency: float = 0

    async def execute(self, task: FractalTask) -> FractalResult:
        """
        分形执行入口

        自动判断任务复杂度，决定是直接执行还是递归分解。
        """
        t0 = time.monotonic()
        task.depth = self.depth

        logger.info(
            f"{'  ' * self.depth}[深度{self.depth}] Agent {self.id} 接收任务: "
            f"{task.description[:60]}..."
        )

        # 1. 评估复杂度
        complexity = await self._assess_complexity(task)
        task.complexity = complexity
        logger.info(f"{'  ' * self.depth}  复杂度: {complexity.value}")

        # 2. 根据复杂度决定执行策略
        if complexity == Complexity.ATOMIC or self.depth >= self.MAX_DEPTH:
            # 原子执行
            result = await self._execute_atomic(task)
        else:
            # 递归分解
            result = await self._execute_recursive(task)

        result.latency_ms = (time.monotonic() - t0) * 1000
        result.agent_id = self.id
        self.tasks_executed += 1
        self.total_latency += result.latency_ms

        logger.info(
            f"{'  ' * self.depth}[深度{self.depth}] Agent {self.id} 完成 | "
            f"{'成功' if result.success else '失败'} | {result.latency_ms:.0f}ms"
        )
        return result

    # ─────── 复杂度评估 ─────────

    async def _assess_complexity(self, task: FractalTask) -> Complexity:
        """评估任务复杂度"""
        if self.llm_router:
            return await self._assess_with_llm(task)
        return self._assess_with_rules(task)

    async def _assess_with_llm(self, task: FractalTask) -> Complexity:
        """用 LLM 评估复杂度"""
        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": (
                        "你是一个任务复杂度评估器。评估给定任务的复杂度。\n"
                        "返回 JSON: {\"complexity\": \"atomic|simple|moderate|complex|epic\", "
                        "\"reason\": \"原因\", \"estimated_subtasks\": 数字}"
                    )},
                    {"role": "user", "content": (
                        f"任务: {task.description}\n"
                        f"上下文: {json.dumps(task.context, ensure_ascii=False)}\n"
                        f"当前递归深度: {self.depth}/{self.MAX_DEPTH}"
                    )},
                ],
                task_type="reasoning",
            )
            return Complexity(result.get("complexity", "atomic"))
        except Exception as e:
            logger.warning(f"LLM 复杂度评估失败: {e}，使用规则评估")
            return self._assess_with_rules(task)

    def _assess_with_rules(self, task: FractalTask) -> Complexity:
        """基于规则评估复杂度"""
        desc = task.description.lower()
        word_count = len(desc.split())

        # 关键词检测
        complex_indicators = [
            "并且", "同时", "首先", "然后", "最后", "以及", "还需要",
            "and", "then", "also", "first", "second", "finally",
            "多个", "所有", "每个", "批量",
        ]
        indicator_count = sum(1 for kw in complex_indicators if kw in desc)

        # 已经在较深层了，倾向于标记为原子
        if self.depth >= self.MAX_DEPTH - 1:
            return Complexity.ATOMIC

        if indicator_count >= 4 or word_count > 100:
            return Complexity.COMPLEX
        elif indicator_count >= 2 or word_count > 50:
            return Complexity.MODERATE
        elif indicator_count >= 1 or word_count > 20:
            return Complexity.SIMPLE
        else:
            return Complexity.ATOMIC

    # ─────── 原子执行 ─────────

    async def _execute_atomic(self, task: FractalTask) -> FractalResult:
        """直接执行原子任务"""
        try:
            if self.llm_router:
                resp = await self.llm_router.chat(
                    messages=[
                        {"role": "system", "content": (
                            f"你是一个任务执行 Agent（角色: {self.role}）。\n"
                            "直接执行给定的任务并返回结果。"
                        )},
                        {"role": "user", "content": (
                            f"执行任务: {task.description}\n"
                            f"上下文: {json.dumps(task.context, ensure_ascii=False)}"
                        )},
                    ],
                    task_type="agent_control",
                )
                output = resp.content
            else:
                # 模拟执行
                output = f"[模拟] Agent {self.id} 已执行: {task.description}"

            task.result = output
            return FractalResult(
                task_id=task.id, success=True, output=output,
                depth=self.depth, decomposition_used=False,
            )
        except Exception as e:
            task.error = str(e)
            return FractalResult(
                task_id=task.id, success=False, output=str(e),
                depth=self.depth, decomposition_used=False,
            )

    # ─────── 递归分解执行 ─────────

    async def _execute_recursive(self, task: FractalTask) -> FractalResult:
        """递归分解并执行"""

        # 1. 分解任务
        subtasks = await self._decompose(task)
        if not subtasks:
            # 分解失败，降级为原子执行
            return await self._execute_atomic(task)

        task.subtask_ids = [st.id for st in subtasks]

        logger.info(
            f"{'  ' * self.depth}  分解为 {len(subtasks)} 个子任务: "
            f"{[st.description[:30] for st in subtasks]}"
        )

        # 2. 为每个子任务创建子 Agent
        child_agents = []
        for i, subtask in enumerate(subtasks):
            child = FractalAgent(
                llm_router=self.llm_router,
                agent_factory=self.agent_factory,
                depth=self.depth + 1,
                role=self._choose_role_for_subtask(subtask),
                parent_id=self.id,
            )
            self.children[child.id] = child
            child_agents.append((child, subtask))

        # 3. 并行执行所有子 Agent
        sub_results = await asyncio.gather(
            *[child.execute(subtask) for child, subtask in child_agents],
            return_exceptions=True,
        )

        # 4. 汇总结果
        collected_results = []
        all_success = True
        for r in sub_results:
            if isinstance(r, Exception):
                collected_results.append(
                    FractalResult(task_id="error", success=False,
                                  output=str(r), depth=self.depth + 1)
                )
                all_success = False
            else:
                collected_results.append(r)
                if not r.success:
                    all_success = False

        # 5. 合成最终结果
        synthesis = await self._synthesize(task, collected_results)

        return FractalResult(
            task_id=task.id,
            success=all_success,
            output=synthesis,
            depth=self.depth,
            subtask_results=collected_results,
            decomposition_used=True,
        )

    async def _decompose(self, task: FractalTask) -> List[FractalTask]:
        """将任务分解为子任务"""
        if self.llm_router:
            return await self._decompose_with_llm(task)
        return self._decompose_with_rules(task)

    async def _decompose_with_llm(self, task: FractalTask) -> List[FractalTask]:
        """用 LLM 分解任务"""
        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": (
                        "你是一个任务分解专家。将复杂任务分解为可独立执行的子任务。\n"
                        f"最多分解为 {self.MAX_SUBTASKS} 个子任务。\n"
                        "每个子任务应该足够具体，可以独立执行。\n\n"
                        "返回 JSON: {\"subtasks\": [{\"description\": \"子任务描述\", "
                        "\"role\": \"执行角色\", \"context\": {}}]}"
                    )},
                    {"role": "user", "content": (
                        f"请分解以下任务:\n{task.description}\n\n"
                        f"上下文: {json.dumps(task.context, ensure_ascii=False)}"
                    )},
                ],
                task_type="planning",
            )

            subtasks = []
            for i, st_data in enumerate(result.get("subtasks", [])[:self.MAX_SUBTASKS]):
                subtasks.append(FractalTask(
                    id=f"{task.id}_sub{i}",
                    description=st_data.get("description", ""),
                    context={**task.context, **st_data.get("context", {})},
                    parent_task_id=task.id,
                ))
            return subtasks

        except Exception as e:
            logger.warning(f"LLM 分解失败: {e}")
            return self._decompose_with_rules(task)

    def _decompose_with_rules(self, task: FractalTask) -> List[FractalTask]:
        """基于规则分解任务"""
        desc = task.description

        # 按连接词分割
        separators = ["并且", "同时", "然后", "以及", "还需要",
                       " and ", " then ", " also "]
        parts = [desc]
        for sep in separators:
            new_parts = []
            for part in parts:
                new_parts.extend(part.split(sep))
            parts = new_parts

        parts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]

        if len(parts) <= 1:
            # 无法分解
            return []

        subtasks = []
        for i, part in enumerate(parts[:self.MAX_SUBTASKS]):
            subtasks.append(FractalTask(
                id=f"{task.id}_sub{i}",
                description=part,
                context=task.context,
                parent_task_id=task.id,
            ))
        return subtasks

    def _choose_role_for_subtask(self, subtask: FractalTask) -> str:
        """为子任务选择角色"""
        desc = subtask.description.lower()
        if any(kw in desc for kw in ["分析", "数据", "统计", "analyze"]):
            return "analyst"
        if any(kw in desc for kw in ["代码", "编程", "code", "开发"]):
            return "coder"
        if any(kw in desc for kw in ["搜索", "查找", "调研", "search"]):
            return "researcher"
        if any(kw in desc for kw in ["控制", "设备", "执行", "device"]):
            return "controller"
        return "executor"

    async def _synthesize(self, task: FractalTask,
                          sub_results: List[FractalResult]) -> str:
        """合成子任务结果"""
        if self.llm_router:
            try:
                # 收集所有子结果
                result_texts = []
                for r in sub_results:
                    status = "成功" if r.success else "失败"
                    output = r.output if isinstance(r.output, str) else json.dumps(r.output, ensure_ascii=False)
                    result_texts.append(f"[{status}] {output[:500]}")

                resp = await self.llm_router.chat(
                    messages=[
                        {"role": "system", "content": (
                            "你是一个结果合成专家。将多个子任务的结果合成为一个完整的回答。"
                        )},
                        {"role": "user", "content": (
                            f"原始任务: {task.description}\n\n"
                            f"子任务结果:\n" + "\n".join(result_texts)
                        )},
                    ],
                    task_type="analysis",
                )
                return resp.content
            except Exception as e:
                logger.warning(f"LLM 合成失败: {e}")

        # 降级：简单拼接
        outputs = [
            r.output if isinstance(r.output, str) else str(r.output)
            for r in sub_results if r.success
        ]
        return "\n---\n".join(outputs)

    # ─────── 状态查询 ─────────

    def get_tree(self) -> Dict:
        """获取分形树结构"""
        node = {
            "id": self.id,
            "role": self.role,
            "depth": self.depth,
            "tasks_executed": self.tasks_executed,
            "children": {},
        }
        for child_id, child in self.children.items():
            node["children"][child_id] = child.get_tree()
        return node

    def count_agents(self) -> int:
        """统计 Agent 总数（包括子 Agent）"""
        return 1 + sum(c.count_agents() for c in self.children.values())


# ───────────────────── 分形执行器（顶层入口）─────────────────────

class FractalExecutor:
    """
    分形执行器 - 系统级入口

    接收用户任务，创建根 FractalAgent，启动分形执行流程。
    """

    def __init__(self, llm_router=None, agent_factory=None):
        self.llm_router = llm_router
        self.agent_factory = agent_factory
        self.executions: Dict[str, Dict] = {}

    async def run(self, task_description: str,
                  context: Optional[Dict] = None) -> FractalResult:
        """
        执行分形任务

        Args:
            task_description: 任务描述
            context: 上下文信息
        """
        task = FractalTask(
            id=f"task_{uuid.uuid4().hex[:8]}",
            description=task_description,
            context=context or {},
        )

        root_agent = FractalAgent(
            llm_router=self.llm_router,
            agent_factory=self.agent_factory,
            depth=0,
            role="coordinator",
        )

        logger.info(f"开始分形执行: {task_description[:60]}...")

        result = await root_agent.execute(task)

        self.executions[task.id] = {
            "task": task_description,
            "result": result,
            "agent_tree": root_agent.get_tree(),
            "total_agents": root_agent.count_agents(),
            "timestamp": time.time(),
        }

        logger.info(
            f"分形执行完成 | 总 Agent 数: {root_agent.count_agents()} | "
            f"成功: {result.success} | {result.latency_ms:.0f}ms"
        )
        return result

    def get_status(self) -> Dict:
        return {
            "total_executions": len(self.executions),
            "recent": [
                {
                    "task": v["task"][:50],
                    "total_agents": v["total_agents"],
                    "success": v["result"].success,
                }
                for v in list(self.executions.values())[-10:]
            ],
        }


# ───────────────────── 单例 ─────────────────────

_executor_instance: Optional[FractalExecutor] = None


def get_fractal_executor(llm_router=None, agent_factory=None) -> FractalExecutor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = FractalExecutor(llm_router, agent_factory)
    return _executor_instance
