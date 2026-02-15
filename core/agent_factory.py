"""
动态 Agent 工厂 (Dynamic Agent Factory)
========================================

三种 Agent 创建模式：
1. 模板创建 - 从预定义模板实例化
2. LLM 生成 - 大模型根据任务描述自动生成 Agent 配置
3. 分裂繁殖 - 现有 Agent 根据负载自动分裂为多个子 Agent
"""

import asyncio
import json
import logging
import time
import uuid
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Galaxy.AgentFactory")


# ───────────────────── 数据模型 ─────────────────────

class AgentRole(Enum):
    """Agent 角色"""
    COORDINATOR = "coordinator"      # 协调者 - 分配任务给子 Agent
    EXECUTOR = "executor"            # 执行者 - 执行具体任务
    ANALYST = "analyst"              # 分析者 - 分析数据和信息
    PLANNER = "planner"              # 规划者 - 制定计划
    MONITOR = "monitor"              # 监控者 - 监控执行过程
    COMMUNICATOR = "communicator"    # 通信者 - 处理外部通信
    SPECIALIST = "specialist"        # 专家 - 特定领域专家


class AgentState(Enum):
    """Agent 状态"""
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"       # 等待子任务完成
    SPLITTING = "splitting"   # 正在分裂
    COMPLETED = "completed"
    ERROR = "error"
    TERMINATED = "terminated"


class CreationMode(Enum):
    """创建模式"""
    TEMPLATE = "template"
    LLM_GENERATED = "llm_generated"
    SPLIT = "split"


@dataclass
class AgentCapability:
    """Agent 能力"""
    name: str
    description: str
    strength: float = 1.0  # 0-1 能力强度


@dataclass
class AgentConfig:
    """Agent 配置"""
    role: AgentRole
    name: str
    description: str
    capabilities: List[AgentCapability]
    system_prompt: str
    max_subtasks: int = 5
    max_depth: int = 3        # 最大递归深度
    split_threshold: int = 3  # 积压任务超过此数触发分裂
    ttl: int = 3600           # 生存时间（秒）
    metadata: Dict = field(default_factory=dict)


@dataclass
class TaskAgent:
    """运行时 Agent 实例"""
    id: str
    config: AgentConfig
    state: AgentState = AgentState.IDLE
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    creation_mode: CreationMode = CreationMode.TEMPLATE
    depth: int = 0            # 当前递归深度
    task_queue: List[Dict] = field(default_factory=list)
    completed_tasks: List[Dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    metrics: Dict = field(default_factory=lambda: {
        "tasks_completed": 0,
        "tasks_failed": 0,
        "total_latency_ms": 0,
        "splits": 0,
    })

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "role": self.config.role.value,
            "name": self.config.name,
            "state": self.state.value,
            "parent_id": self.parent_id,
            "children": self.children_ids,
            "depth": self.depth,
            "queue_length": len(self.task_queue),
            "completed": len(self.completed_tasks),
            "creation_mode": self.creation_mode.value,
            "metrics": self.metrics,
        }


# ───────────────────── 模板库 ─────────────────────

AGENT_TEMPLATES: Dict[str, AgentConfig] = {
    "coordinator": AgentConfig(
        role=AgentRole.COORDINATOR,
        name="协调 Agent",
        description="负责接收复杂任务，分解为子任务并分配给子 Agent",
        capabilities=[
            AgentCapability("task_decomposition", "将复杂任务分解为子任务"),
            AgentCapability("agent_management", "创建和管理子 Agent"),
            AgentCapability("result_aggregation", "汇总子 Agent 结果"),
        ],
        system_prompt=(
            "你是一个协调 Agent。你的职责是：\n"
            "1. 接收用户的复杂任务\n"
            "2. 将任务分解为可独立执行的子任务\n"
            "3. 为每个子任务分配合适的执行 Agent\n"
            "4. 监控执行进度并汇总结果\n\n"
            "返回 JSON 格式的任务分解方案。"
        ),
        max_subtasks=10,
        max_depth=3,
    ),
    "data_analyst": AgentConfig(
        role=AgentRole.ANALYST,
        name="数据分析 Agent",
        description="专门处理数据分析、统计和可视化任务",
        capabilities=[
            AgentCapability("data_analysis", "数据清洗和分析"),
            AgentCapability("statistics", "统计计算"),
            AgentCapability("summarization", "数据摘要"),
        ],
        system_prompt=(
            "你是一个数据分析 Agent。分析给定的数据并提供洞察。\n"
            "输出格式为 JSON: {\"analysis\": ..., \"insights\": [...], \"recommendations\": [...]}"
        ),
    ),
    "code_executor": AgentConfig(
        role=AgentRole.EXECUTOR,
        name="代码执行 Agent",
        description="负责生成和执行代码",
        capabilities=[
            AgentCapability("code_generation", "生成 Python/JS 代码"),
            AgentCapability("code_review", "代码审查"),
            AgentCapability("testing", "测试代码"),
        ],
        system_prompt=(
            "你是一个代码执行 Agent。根据需求生成代码并执行。\n"
            "返回 JSON: {\"code\": ..., \"language\": ..., \"explanation\": ...}"
        ),
    ),
    "research": AgentConfig(
        role=AgentRole.ANALYST,
        name="调研 Agent",
        description="负责信息收集和研究",
        capabilities=[
            AgentCapability("web_search", "网络搜索"),
            AgentCapability("information_extraction", "信息提取"),
            AgentCapability("fact_checking", "事实核查"),
        ],
        system_prompt=(
            "你是一个调研 Agent。负责收集和整理信息。\n"
            "返回 JSON: {\"findings\": [...], \"sources\": [...], \"summary\": ...}"
        ),
    ),
    "device_controller": AgentConfig(
        role=AgentRole.EXECUTOR,
        name="设备控制 Agent",
        description="负责与物理设备交互",
        capabilities=[
            AgentCapability("device_control", "控制设备"),
            AgentCapability("status_monitoring", "监控设备状态"),
            AgentCapability("safety_check", "安全检查"),
        ],
        system_prompt=(
            "你是一个设备控制 Agent。负责安全地控制物理设备。\n"
            "在执行任何操作前，先进行安全检查。\n"
            "返回 JSON: {\"action\": ..., \"device\": ..., \"safety_check\": ..., \"result\": ...}"
        ),
    ),
    "planner": AgentConfig(
        role=AgentRole.PLANNER,
        name="规划 Agent",
        description="负责制定执行计划和策略",
        capabilities=[
            AgentCapability("strategic_planning", "制定策略"),
            AgentCapability("risk_assessment", "风险评估"),
            AgentCapability("resource_allocation", "资源分配"),
        ],
        system_prompt=(
            "你是一个规划 Agent。根据目标制定详细的执行计划。\n"
            "返回 JSON: {\"plan\": {\"steps\": [...], \"resources\": [...], \"risks\": [...]}}"
        ),
    ),
}


# ───────────────────── Agent 工厂 ─────────────────────

class AgentFactory:
    """
    动态 Agent 工厂

    三种创建模式：
    1. create_from_template() - 从预定义模板实例化
    2. create_from_llm() - LLM 根据任务描述动态生成 Agent 配置
    3. split_agent() - 现有 Agent 根据负载分裂为多个子 Agent
    """

    def __init__(self, llm_router=None):
        self.llm_router = llm_router
        self.agents: Dict[str, TaskAgent] = {}
        self.agent_tree: Dict[str, List[str]] = {}  # parent_id → [child_ids]
        self._task_handlers: Dict[str, Callable] = {}
        logger.info("AgentFactory 已初始化")

    # ─────── 模式 1: 模板创建 ─────────

    def create_from_template(
        self, template_name: str,
        parent_id: Optional[str] = None,
        overrides: Optional[Dict] = None,
    ) -> TaskAgent:
        """从模板创建 Agent"""
        if template_name not in AGENT_TEMPLATES:
            available = list(AGENT_TEMPLATES.keys())
            raise ValueError(f"未知模板: {template_name}，可用: {available}")

        config = AGENT_TEMPLATES[template_name]

        # 应用覆盖
        if overrides:
            if "name" in overrides:
                config = AgentConfig(**{**config.__dict__, "name": overrides["name"]})
            if "system_prompt" in overrides:
                config = AgentConfig(**{**config.__dict__, "system_prompt": overrides["system_prompt"]})

        agent = TaskAgent(
            id=f"agent_{uuid.uuid4().hex[:12]}",
            config=config,
            parent_id=parent_id,
            creation_mode=CreationMode.TEMPLATE,
            depth=self._get_depth(parent_id),
        )

        self._register_agent(agent)
        logger.info(f"[模板创建] {agent.config.name} ({agent.id}) 从模板 '{template_name}'")
        return agent

    # ─────── 模式 2: LLM 生成 ─────────

    async def create_from_llm(
        self, task_description: str,
        parent_id: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> TaskAgent:
        """LLM 根据任务描述动态生成 Agent 配置"""
        if not self.llm_router:
            raise RuntimeError("LLM Router 未配置，无法使用 LLM 生成模式")

        prompt = self._build_agent_generation_prompt(task_description, context)

        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": "你是一个 Agent 配置生成器。根据任务描述生成最优的 Agent 配置。"},
                    {"role": "user", "content": prompt},
                ],
                task_type="planning",
            )

            # 从 LLM 响应构建 AgentConfig
            role_str = result.get("role", "executor")
            try:
                role = AgentRole(role_str)
            except ValueError:
                role = AgentRole.EXECUTOR

            capabilities = [
                AgentCapability(
                    name=cap.get("name", "unknown"),
                    description=cap.get("description", ""),
                    strength=cap.get("strength", 0.8),
                )
                for cap in result.get("capabilities", [])
            ]

            config = AgentConfig(
                role=role,
                name=result.get("name", f"动态Agent-{task_description[:20]}"),
                description=result.get("description", task_description),
                capabilities=capabilities,
                system_prompt=result.get("system_prompt", f"你是一个专门处理以下任务的 Agent: {task_description}"),
                max_subtasks=result.get("max_subtasks", 5),
                max_depth=result.get("max_depth", 2),
                metadata={"generated_from": task_description, "llm_config": result},
            )

            agent = TaskAgent(
                id=f"agent_{uuid.uuid4().hex[:12]}",
                config=config,
                parent_id=parent_id,
                creation_mode=CreationMode.LLM_GENERATED,
                depth=self._get_depth(parent_id),
            )

            self._register_agent(agent)
            logger.info(f"[LLM 生成] {agent.config.name} ({agent.id}) 用于: {task_description[:50]}")
            return agent

        except Exception as e:
            logger.warning(f"LLM 生成 Agent 失败: {e}，回退到模板创建")
            # 回退到最匹配的模板
            template = self._match_template(task_description)
            return self.create_from_template(template, parent_id)

    def _build_agent_generation_prompt(self, task_description: str,
                                       context: Optional[Dict] = None) -> str:
        ctx_str = json.dumps(context, ensure_ascii=False, indent=2) if context else "无"
        return f"""根据以下任务描述，生成一个最优的 Agent 配置。

任务描述: {task_description}
上下文信息: {ctx_str}

请返回 JSON 格式:
{{
    "role": "coordinator|executor|analyst|planner|monitor|communicator|specialist",
    "name": "Agent 名称",
    "description": "Agent 描述",
    "capabilities": [
        {{"name": "能力名", "description": "能力描述", "strength": 0.0-1.0}}
    ],
    "system_prompt": "Agent 的系统提示词",
    "max_subtasks": 5,
    "max_depth": 2,
    "suggested_sub_agents": [
        {{"template": "模板名或描述", "reason": "为什么需要这个子 Agent"}}
    ]
}}"""

    def _match_template(self, task_description: str) -> str:
        """匹配最相关的模板"""
        desc = task_description.lower()
        if any(kw in desc for kw in ["分析", "数据", "统计", "analyze"]):
            return "data_analyst"
        if any(kw in desc for kw in ["代码", "编程", "code", "执行"]):
            return "code_executor"
        if any(kw in desc for kw in ["搜索", "调研", "research", "查找"]):
            return "research"
        if any(kw in desc for kw in ["设备", "控制", "device", "硬件"]):
            return "device_controller"
        if any(kw in desc for kw in ["计划", "规划", "plan", "策略"]):
            return "planner"
        return "coordinator"

    # ─────── 模式 3: 分裂繁殖 ─────────

    async def split_agent(self, agent_id: str,
                          num_children: int = 2) -> List[TaskAgent]:
        """
        将一个 Agent 分裂为多个子 Agent

        触发条件：Agent 的任务队列超过 split_threshold
        分裂策略：
        - 协调者 → 多个执行者
        - 执行者 → 按能力分割
        """
        parent = self.agents.get(agent_id)
        if not parent:
            raise ValueError(f"Agent 不存在: {agent_id}")

        if parent.depth >= parent.config.max_depth:
            logger.warning(f"Agent {agent_id} 已达最大深度 {parent.config.max_depth}，无法继续分裂")
            return []

        parent.state = AgentState.SPLITTING
        parent.metrics["splits"] += 1
        children = []

        # 按任务队列分割
        tasks_per_child = max(1, len(parent.task_queue) // num_children)

        for i in range(num_children):
            # 子 Agent 继承父代的部分能力
            child_capabilities = self._distribute_capabilities(
                parent.config.capabilities, i, num_children
            )

            child_config = AgentConfig(
                role=AgentRole.EXECUTOR,
                name=f"{parent.config.name}-子代{i+1}",
                description=f"从 {parent.config.name} 分裂的子 Agent ({i+1}/{num_children})",
                capabilities=child_capabilities,
                system_prompt=parent.config.system_prompt,
                max_subtasks=parent.config.max_subtasks,
                max_depth=parent.config.max_depth,
                split_threshold=parent.config.split_threshold,
                ttl=parent.config.ttl // 2,  # 子代 TTL 减半
            )

            child = TaskAgent(
                id=f"agent_{uuid.uuid4().hex[:12]}",
                config=child_config,
                parent_id=agent_id,
                creation_mode=CreationMode.SPLIT,
                depth=parent.depth + 1,
            )

            # 分配任务
            start = i * tasks_per_child
            end = start + tasks_per_child if i < num_children - 1 else len(parent.task_queue)
            child.task_queue = parent.task_queue[start:end]

            self._register_agent(child)
            children.append(child)
            parent.children_ids.append(child.id)

        # 清空父代任务队列（已分配给子代）
        parent.task_queue = []
        parent.state = AgentState.WAITING

        logger.info(
            f"[分裂繁殖] {parent.config.name} ({agent_id}) → "
            f"{num_children} 个子 Agent: {[c.id for c in children]}"
        )
        return children

    def _distribute_capabilities(self, capabilities: List[AgentCapability],
                                 index: int, total: int) -> List[AgentCapability]:
        """分配能力给子 Agent（每个子代获得所有能力，但强度分化）"""
        result = []
        for cap in capabilities:
            # 子代在不同能力上有不同的强度分化
            variation = 0.8 + (0.4 * ((index + hash(cap.name)) % total) / total)
            result.append(AgentCapability(
                name=cap.name,
                description=cap.description,
                strength=min(1.0, cap.strength * variation),
            ))
        return result

    # ─────── Agent 执行 ─────────

    async def execute_agent_task(self, agent_id: str, task: Dict) -> Dict:
        """
        让 Agent 执行一个任务

        如果 Agent 有 LLM Router，使用 LLM 推理
        如果积压过多，触发分裂
        """
        agent = self.agents.get(agent_id)
        if not agent:
            raise ValueError(f"Agent 不存在: {agent_id}")

        agent.task_queue.append(task)
        agent.state = AgentState.WORKING
        agent.last_active = time.time()

        # 检查是否需要分裂
        if len(agent.task_queue) > agent.config.split_threshold and \
           agent.depth < agent.config.max_depth:
            children = await self.split_agent(agent_id)
            if children:
                # 子 Agent 并行执行
                results = await asyncio.gather(
                    *[self._run_agent(c.id) for c in children],
                    return_exceptions=True,
                )
                agent.state = AgentState.IDLE
                return {
                    "strategy": "split_and_parallel",
                    "children": [c.id for c in children],
                    "results": [
                        r if not isinstance(r, Exception) else {"error": str(r)}
                        for r in results
                    ],
                }

        # 直接执行
        result = await self._run_agent(agent_id)
        return result

    async def _run_agent(self, agent_id: str) -> Dict:
        """执行 Agent 的当前任务队列"""
        agent = self.agents.get(agent_id)
        if not agent or not agent.task_queue:
            return {"status": "no_tasks"}

        agent.state = AgentState.WORKING
        results = []

        while agent.task_queue:
            task = agent.task_queue.pop(0)
            t0 = time.monotonic()

            try:
                if self.llm_router:
                    # 用 LLM 执行
                    messages = [
                        {"role": "system", "content": agent.config.system_prompt},
                        {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
                    ]
                    resp = await self.llm_router.chat(
                        messages=messages,
                        task_type="agent_control",
                    )
                    result = {"task": task, "output": resp.content, "provider": resp.provider}
                else:
                    # 无 LLM，模拟执行
                    result = {
                        "task": task,
                        "output": f"Agent {agent.config.name} 已处理任务（无 LLM 模式）",
                        "simulated": True,
                    }

                latency = (time.monotonic() - t0) * 1000
                result["latency_ms"] = latency
                agent.metrics["tasks_completed"] += 1
                agent.metrics["total_latency_ms"] += latency
                agent.completed_tasks.append(result)
                results.append(result)

            except Exception as e:
                agent.metrics["tasks_failed"] += 1
                results.append({"task": task, "error": str(e)})

        agent.state = AgentState.IDLE
        agent.last_active = time.time()
        return {"agent_id": agent_id, "results": results}

    # ─────── 内部工具 ─────────

    def _register_agent(self, agent: TaskAgent):
        self.agents[agent.id] = agent
        if agent.parent_id:
            if agent.parent_id not in self.agent_tree:
                self.agent_tree[agent.parent_id] = []
            self.agent_tree[agent.parent_id].append(agent.id)

    def _get_depth(self, parent_id: Optional[str]) -> int:
        if parent_id and parent_id in self.agents:
            return self.agents[parent_id].depth + 1
        return 0

    # ─────── 查询和管理 ─────────

    def get_agent(self, agent_id: str) -> Optional[TaskAgent]:
        return self.agents.get(agent_id)

    def get_all_agents(self) -> Dict[str, Dict]:
        return {aid: a.to_dict() for aid, a in self.agents.items()}

    def get_agent_tree(self) -> Dict:
        """获取 Agent 层级树"""
        roots = [a for a in self.agents.values() if a.parent_id is None]
        return {
            "total_agents": len(self.agents),
            "max_depth": max((a.depth for a in self.agents.values()), default=0),
            "roots": [self._build_tree_node(r.id) for r in roots],
        }

    def _build_tree_node(self, agent_id: str) -> Dict:
        agent = self.agents[agent_id]
        node = agent.to_dict()
        children_ids = self.agent_tree.get(agent_id, [])
        if children_ids:
            node["children_detail"] = [
                self._build_tree_node(cid)
                for cid in children_ids if cid in self.agents
            ]
        return node

    def terminate_agent(self, agent_id: str, recursive: bool = True):
        """终止 Agent"""
        agent = self.agents.get(agent_id)
        if not agent:
            return

        if recursive:
            for child_id in list(agent.children_ids):
                self.terminate_agent(child_id, recursive=True)

        agent.state = AgentState.TERMINATED
        logger.info(f"Agent 已终止: {agent.config.name} ({agent_id})")

    def cleanup_expired(self):
        """清理过期 Agent"""
        now = time.time()
        expired = [
            aid for aid, a in self.agents.items()
            if a.state in (AgentState.COMPLETED, AgentState.TERMINATED, AgentState.IDLE)
            and now - a.created_at > a.config.ttl
        ]
        for aid in expired:
            del self.agents[aid]
        if expired:
            logger.info(f"清理了 {len(expired)} 个过期 Agent")

    def get_status(self) -> Dict:
        by_state = {}
        by_mode = {}
        for a in self.agents.values():
            by_state[a.state.value] = by_state.get(a.state.value, 0) + 1
            by_mode[a.creation_mode.value] = by_mode.get(a.creation_mode.value, 0) + 1

        return {
            "total_agents": len(self.agents),
            "by_state": by_state,
            "by_creation_mode": by_mode,
            "agent_tree": self.get_agent_tree(),
        }


# ───────────────────── 单例 ─────────────────────

_factory_instance: Optional[AgentFactory] = None


def get_agent_factory(llm_router=None) -> AgentFactory:
    global _factory_instance
    if _factory_instance is None:
        _factory_instance = AgentFactory(llm_router)
    return _factory_instance
