"""
UFO Galaxy - Agent 蜂群 (Agent Swarm)
=====================================

N 个 Agent 并行执行，通过 asyncio.gather + Semaphore 控制并发，
支持三种策略：SAME_TASK（投票/最优）、SPLIT_TASK（分片合并）、COMPETE（竞速）。
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.AgentSwarm")


# ───────────────────── 数据模型 ─────────────────────

class SwarmStrategy(Enum):
    """蜂群执行策略"""
    SAME_TASK = "same_task"      # 所有 Agent 处理同一任务（投票/最优选）
    SPLIT_TASK = "split_task"    # 任务分片，每个 Agent 处理一片
    COMPETE = "compete"          # 竞速，第一个成功的结果获胜


@dataclass
class SwarmConfig:
    """蜂群配置"""
    swarm_size: int = 5
    strategy: SwarmStrategy = SwarmStrategy.SAME_TASK
    timeout_per_agent: float = 60.0
    max_concurrent: int = 10
    aggregation: str = "best"     # "best" | "merge" | "vote"
    provider: Optional[str] = None
    model: Optional[str] = None
    template: str = "coordinator"


@dataclass
class SwarmResult:
    """蜂群执行结果"""
    task_id: str
    strategy: SwarmStrategy
    agent_results: List[Dict] = field(default_factory=list)
    aggregated_output: Any = None
    total_latency_ms: float = 0.0
    agents_succeeded: int = 0
    agents_failed: int = 0

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "strategy": self.strategy.value,
            "agents_succeeded": self.agents_succeeded,
            "agents_failed": self.agents_failed,
            "total_latency_ms": self.total_latency_ms,
            "aggregated_output": self.aggregated_output,
        }


# ───────────────────── AgentSwarm ─────────────────────

class AgentSwarm:
    """
    Agent 蜂群 — 并行执行多个 Agent，聚合结果。

    三种策略:
    - SAME_TASK: 所有 Agent 处理同一任务，通过投票/评分选最优
    - SPLIT_TASK: 将任务分片，每个 Agent 处理一片，合并结果
    - COMPETE: 竞速模式，第一个有效结果直接返回
    """

    def __init__(self, llm_router=None, agent_factory=None,
                 capability_orchestrator=None, config: Optional[SwarmConfig] = None):
        self.llm_router = llm_router
        self.agent_factory = agent_factory
        self.capability_orchestrator = capability_orchestrator
        self.config = config or SwarmConfig()
        self._active_agents: List[str] = []
        logger.info(
            f"AgentSwarm 已初始化: size={self.config.swarm_size}, "
            f"strategy={self.config.strategy.value}"
        )

    async def execute(self, task_description: str,
                      context: Optional[Dict] = None) -> SwarmResult:
        """
        蜂群执行主入口。

        1. 创建 N 个 Agent
        2. 按策略并行执行
        3. 聚合结果
        4. 清理 Agent
        """
        task_id = f"swarm_{uuid.uuid4().hex[:8]}"
        start = time.time()
        config = self.config
        context = context or {}

        logger.info(
            f"[{task_id}] 蜂群启动: strategy={config.strategy.value}, "
            f"size={config.swarm_size}"
        )

        # 1. 创建 Agent 集合
        agents = self._create_agents(config.swarm_size)
        self._active_agents = [a.id for a in agents]

        try:
            # 2. 按策略执行
            if config.strategy == SwarmStrategy.COMPETE:
                result = await self._execute_compete(
                    task_id, agents, task_description, context
                )
            elif config.strategy == SwarmStrategy.SPLIT_TASK:
                result = await self._execute_split(
                    task_id, agents, task_description, context
                )
            else:
                result = await self._execute_same_task(
                    task_id, agents, task_description, context
                )
        except Exception as e:
            logger.error(f"[{task_id}] 蜂群执行失败: {e}")
            result = SwarmResult(
                task_id=task_id, strategy=config.strategy,
                aggregated_output=f"蜂群执行失败: {e}",
            )
        finally:
            # 3. 清理
            self._cleanup_agents()

        result.total_latency_ms = (time.time() - start) * 1000
        logger.info(
            f"[{task_id}] 蜂群完成: "
            f"成功={result.agents_succeeded}, 失败={result.agents_failed}, "
            f"耗时={result.total_latency_ms:.0f}ms"
        )
        return result

    # ─────── 策略实现 ───────

    async def _execute_same_task(self, task_id, agents, task_description, context):
        """所有 Agent 处理同一任务"""
        sem = asyncio.Semaphore(self.config.max_concurrent)

        tasks = [
            self._spawn_agent(sem, agent, {
                "description": task_description,
                "context": context,
                "agent_index": i,
            })
            for i, agent in enumerate(agents)
        ]

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        agent_results = self._collect_results(raw_results)

        aggregated = await self._aggregate(
            self.config.strategy, self.config.aggregation, agent_results
        )

        succeeded = sum(1 for r in agent_results if r.get("success"))
        return SwarmResult(
            task_id=task_id, strategy=self.config.strategy,
            agent_results=agent_results, aggregated_output=aggregated,
            agents_succeeded=succeeded,
            agents_failed=len(agent_results) - succeeded,
        )

    async def _execute_split(self, task_id, agents, task_description, context):
        """分片执行"""
        parts = await self._split_task(task_description, len(agents))
        sem = asyncio.Semaphore(self.config.max_concurrent)

        tasks = [
            self._spawn_agent(sem, agent, {
                "description": part,
                "context": {**context, "part_index": i, "total_parts": len(parts)},
                "agent_index": i,
            })
            for i, (agent, part) in enumerate(zip(agents, parts))
        ]

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        agent_results = self._collect_results(raw_results)

        aggregated = await self._aggregate(
            SwarmStrategy.SPLIT_TASK, "merge", agent_results
        )

        succeeded = sum(1 for r in agent_results if r.get("success"))
        return SwarmResult(
            task_id=task_id, strategy=SwarmStrategy.SPLIT_TASK,
            agent_results=agent_results, aggregated_output=aggregated,
            agents_succeeded=succeeded,
            agents_failed=len(agent_results) - succeeded,
        )

    async def _execute_compete(self, task_id, agents, task_description, context):
        """竞速模式 — 第一个成功结果获胜"""
        sem = asyncio.Semaphore(self.config.max_concurrent)

        tasks = [
            self._spawn_agent(sem, agent, {
                "description": task_description,
                "context": context,
                "agent_index": i,
            })
            for i, agent in enumerate(agents)
        ]

        # 用 as_completed 取第一个成功的结果
        winner = None
        completed_results = []
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                completed_results.append(result)
                if result.get("success") and winner is None:
                    winner = result
                    break
            except Exception as e:
                completed_results.append({
                    "success": False, "error": str(e)
                })

        if winner is None and completed_results:
            winner = completed_results[0]

        succeeded = sum(1 for r in completed_results if r.get("success"))
        return SwarmResult(
            task_id=task_id, strategy=SwarmStrategy.COMPETE,
            agent_results=completed_results,
            aggregated_output=winner.get("output") if winner else None,
            agents_succeeded=succeeded,
            agents_failed=len(completed_results) - succeeded,
        )

    # ─────── 核心方法 ───────

    async def _spawn_agent(self, sem: asyncio.Semaphore,
                           agent, task: Dict) -> Dict:
        """执行单个 Agent（带信号量和超时控制）"""
        async with sem:
            start = time.time()
            try:
                result = await asyncio.wait_for(
                    self._run_agent_task(agent, task),
                    timeout=self.config.timeout_per_agent,
                )
                latency = (time.time() - start) * 1000
                return {
                    "agent_id": agent.id,
                    "success": True,
                    "output": result,
                    "latency_ms": latency,
                }
            except asyncio.TimeoutError:
                return {
                    "agent_id": agent.id,
                    "success": False,
                    "error": "timeout",
                    "latency_ms": (time.time() - start) * 1000,
                }
            except Exception as e:
                return {
                    "agent_id": agent.id,
                    "success": False,
                    "error": str(e),
                    "latency_ms": (time.time() - start) * 1000,
                }

    async def _run_agent_task(self, agent, task: Dict) -> Any:
        """通过 LLM Router 执行 Agent 任务"""
        if not self.llm_router:
            return {"note": "LLM Router 未配置，降级为规则执行", "task": task["description"]}

        messages = [
            {"role": "system", "content": agent.config.system_prompt},
            {"role": "user", "content": json.dumps({
                "task": task["description"],
                "context": task.get("context", {}),
            }, ensure_ascii=False)},
        ]

        kwargs = {}
        if self.config.provider:
            kwargs["provider"] = self.config.provider
        if self.config.model:
            kwargs["model"] = self.config.model

        response = await self.llm_router.chat(
            messages=messages, task_type="agent_control", **kwargs
        )
        return response.content

    async def _aggregate(self, strategy: SwarmStrategy,
                         aggregation: str, results: List[Dict]) -> Any:
        """聚合多个 Agent 结果"""
        successful = [r for r in results if r.get("success")]
        if not successful:
            return "所有 Agent 均执行失败"

        outputs = [r.get("output", "") for r in successful]

        # 无 LLM 降级
        if not self.llm_router:
            if aggregation == "vote":
                return max(set(str(o) for o in outputs), key=lambda x: [str(o) for o in outputs].count(x))
            return outputs[0] if outputs else None

        if strategy == SwarmStrategy.SPLIT_TASK or aggregation == "merge":
            return await self._aggregate_merge(outputs)
        elif aggregation == "vote":
            return await self._aggregate_vote(outputs)
        else:  # "best"
            return await self._aggregate_best(outputs)

    async def _aggregate_best(self, outputs: List) -> Any:
        """LLM 评分选最优"""
        if len(outputs) == 1:
            return outputs[0]

        formatted = "\n\n".join(
            f"--- Agent {i+1} 结果 ---\n{o}" for i, o in enumerate(outputs)
        )
        response = await self.llm_router.chat(
            messages=[
                {"role": "system", "content": "从多个 Agent 的输出中选择最佳结果。直接输出最佳结果的内容。"},
                {"role": "user", "content": f"请从以下结果中选择最佳的：\n\n{formatted}"},
            ],
            task_type="analysis",
        )
        return response.content

    async def _aggregate_vote(self, outputs: List) -> Any:
        """LLM 投票选共识"""
        if len(outputs) == 1:
            return outputs[0]

        formatted = "\n\n".join(
            f"--- Agent {i+1} 结果 ---\n{o}" for i, o in enumerate(outputs)
        )
        response = await self.llm_router.chat(
            messages=[
                {"role": "system", "content": (
                    "多个 Agent 独立完成了同一任务。分析它们的共同结论，"
                    "输出共识结果。如果存在分歧，以多数意见为准。"
                )},
                {"role": "user", "content": f"请分析以下结果的共识：\n\n{formatted}"},
            ],
            task_type="analysis",
        )
        return response.content

    async def _aggregate_merge(self, outputs: List) -> Any:
        """合并分片结果"""
        if len(outputs) == 1:
            return outputs[0]

        formatted = "\n\n".join(
            f"--- 第 {i+1} 部分 ---\n{o}" for i, o in enumerate(outputs)
        )
        response = await self.llm_router.chat(
            messages=[
                {"role": "system", "content": (
                    "以下是一个任务被分片后各部分的执行结果。"
                    "请将它们合并为一个完整的、连贯的最终结果。"
                )},
                {"role": "user", "content": f"请合并以下分片结果：\n\n{formatted}"},
            ],
            task_type="analysis",
        )
        return response.content

    async def _split_task(self, task_description: str,
                          num_parts: int) -> List[str]:
        """将任务分解为多个子任务"""
        if not self.llm_router:
            return [task_description] * num_parts

        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": (
                        f"将给定任务分解为 {num_parts} 个可独立执行的子任务。\n"
                        "返回 JSON: {\"parts\": [\"子任务1描述\", \"子任务2描述\", ...]}"
                    )},
                    {"role": "user", "content": task_description},
                ],
                task_type="planning",
            )
            parts = result.get("parts", [])
            if len(parts) == num_parts:
                return parts
        except Exception as e:
            logger.warning(f"LLM 分片失败，降级为均匀分配: {e}")

        return [f"{task_description} (Part {i+1}/{num_parts})" for i in range(num_parts)]

    # ─────── 辅助方法 ───────

    def _create_agents(self, count: int):
        """创建 Agent 实例"""
        agents = []
        for i in range(count):
            if self.agent_factory:
                agent = self.agent_factory.create_from_template(
                    self.config.template,
                    overrides={"name": f"蜂群成员 #{i+1}"},
                )
            else:
                from core.agent_factory import TaskAgent, AgentConfig, AgentRole, AgentCapability
                agent = TaskAgent(
                    id=f"swarm_{uuid.uuid4().hex[:8]}",
                    config=AgentConfig(
                        role=AgentRole.SWARM_MEMBER,
                        name=f"蜂群成员 #{i+1}",
                        description="蜂群并行 Agent",
                        capabilities=[AgentCapability("parallel_exec", "并行执行")],
                        system_prompt="你是蜂群 Agent，独立完成分配的任务。",
                    ),
                )
            agents.append(agent)
        return agents

    def _cleanup_agents(self):
        """清理 Agent"""
        if self.agent_factory:
            for aid in self._active_agents:
                try:
                    self.agent_factory.terminate_agent(aid)
                except Exception:
                    pass
        self._active_agents.clear()

    def _collect_results(self, raw_results) -> List[Dict]:
        """收集并过滤异常结果"""
        collected = []
        for r in raw_results:
            if isinstance(r, Exception):
                collected.append({"success": False, "error": str(r)})
            elif isinstance(r, dict):
                collected.append(r)
            else:
                collected.append({"success": False, "error": f"unexpected: {r}"})
        return collected

    def get_status(self) -> Dict:
        return {
            "swarm_size": self.config.swarm_size,
            "strategy": self.config.strategy.value,
            "active_agents": len(self._active_agents),
            "max_concurrent": self.config.max_concurrent,
        }


# ───────────────────── 单例 ─────────────────────

_swarm_instance: Optional[AgentSwarm] = None


def get_agent_swarm(llm_router=None, agent_factory=None,
                    config: Optional[SwarmConfig] = None) -> AgentSwarm:
    global _swarm_instance
    if _swarm_instance is None:
        _swarm_instance = AgentSwarm(
            llm_router=llm_router,
            agent_factory=agent_factory,
            config=config,
        )
    return _swarm_instance
