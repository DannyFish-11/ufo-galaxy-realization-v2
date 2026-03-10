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

try:
    from core.monitoring import CircuitBreaker
except ImportError:
    CircuitBreaker = None

logger = logging.getLogger("Galaxy.AgentFactory")


# ───────────────────── Agent 消息通信 ─────────────────────

@dataclass
class AgentMessage:
    """Agent 间通信消息"""
    id: str
    sender_id: str
    receiver_id: str
    msg_type: str  # task_assign, task_result, heartbeat, status_query, status_response
    payload: Dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ack: bool = False  # 已确认


class AgentMessageBus:
    """
    Agent 消息总线 —— 基于内存队列的发布/订阅通信系统。

    每个 Agent 拥有独立的消息队列，支持:
    - 点对点消息发送（send）
    - 带超时的接收（receive）
    - 广播消息（broadcast）
    - 请求-回复模式（request / reply）
    """

    MAX_QUEUE_SIZE = 1000  # 每个 Agent 队列的最大消息数

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._pending_acks: Dict[str, asyncio.Event] = {}
        logger.info("AgentMessageBus 初始化")

    def register(self, agent_id: str):
        """为 Agent 注册一个消息队列"""
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)

    def unregister(self, agent_id: str):
        if agent_id in self._queues:
            del self._queues[agent_id]

    async def send(self, msg: AgentMessage) -> bool:
        """发送消息到目标 Agent 的队列"""
        q = self._queues.get(msg.receiver_id)
        if q is None:
            logger.warning(f"目标 Agent {msg.receiver_id} 不存在")
            return False
        await q.put(msg)
        return True

    async def receive(self, agent_id: str, timeout: float = 5.0) -> Optional[AgentMessage]:
        """从队列中接收消息，带超时"""
        q = self._queues.get(agent_id)
        if q is None:
            return None
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def broadcast(self, sender_id: str, msg_type: str, payload: Dict):
        """向所有已注册 Agent 广播消息"""
        for agent_id in list(self._queues.keys()):
            if agent_id == sender_id:
                continue
            msg = AgentMessage(
                id=f"msg_{uuid.uuid4().hex[:12]}",
                sender_id=sender_id,
                receiver_id=agent_id,
                msg_type=msg_type,
                payload=payload,
            )
            await self.send(msg)

    async def request(self, msg: AgentMessage, timeout: float = 10.0) -> Optional[AgentMessage]:
        """请求-回复模式：发送请求并等待回复"""
        reply_event = asyncio.Event()
        self._pending_acks[msg.id] = reply_event
        await self.send(msg)
        try:
            await asyncio.wait_for(reply_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"请求超时: {msg.id}")
            self._pending_acks.pop(msg.id, None)
            return None
        self._pending_acks.pop(msg.id, None)
        # 从接收方队列中取回复（按 convention 回复 msg_type = 'reply_{original_id}'）
        return await self.receive(msg.sender_id, timeout=1.0)

    def notify_ack(self, original_msg_id: str):
        """通知请求方消息已被处理"""
        ev = self._pending_acks.get(original_msg_id)
        if ev:
            ev.set()


# 全局消息总线单例
_message_bus: Optional["AgentMessageBus"] = None


def get_message_bus() -> AgentMessageBus:
    global _message_bus
    if _message_bus is None:
        _message_bus = AgentMessageBus()
    return _message_bus


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

    # 生产可用性配置
    MAX_AGENTS = 500              # 最大 Agent 数
    CLEANUP_INTERVAL = 60         # TTL 清理间隔（秒）
    MAX_CREATES_PER_MINUTE = 50   # 每分钟最大创建数
    STATE_FILE = "data/agent_state.json"

    def __init__(self, llm_router=None):
        self.llm_router = llm_router
        self.agents: Dict[str, TaskAgent] = {}
        self.agent_tree: Dict[str, List[str]] = {}  # parent_id → [child_ids]
        self._task_handlers: Dict[str, Callable] = {}
        self.message_bus = get_message_bus()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._creation_timestamps: List[float] = []  # 速率限制追踪
        # LLM 调用熔断器
        self._llm_circuit_breaker = (
            CircuitBreaker(name="agent_llm", failure_threshold=5, recovery_timeout=30.0)
            if CircuitBreaker else None
        )
        self._load_state()
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
                # 通过消息总线向子 Agent 分发任务
                for child in children:
                    for task_item in child.task_queue:
                        task_msg = AgentMessage(
                            id=f"msg_{uuid.uuid4().hex[:12]}",
                            sender_id=agent.id,
                            receiver_id=child.id,
                            msg_type="task_assign",
                            payload=task_item,
                        )
                        await self.message_bus.send(task_msg)
                # 子 Agent 并行执行（带总超时保护）
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(
                            *[self._run_agent(c.id) for c in children],
                            return_exceptions=True,
                        ),
                        timeout=self.TASK_TIMEOUT_SECONDS * 2,
                    )
                except asyncio.TimeoutError:
                    logger.error(f"子 Agent 并行执行整体超时 ({self.TASK_TIMEOUT_SECONDS * 2}s)")
                    for child in children:
                        child.state = AgentState.ERROR
                    agent.state = AgentState.ERROR
                    return {
                        "strategy": "split_and_parallel",
                        "error": f"Parallel execution timed out after {self.TASK_TIMEOUT_SECONDS * 2}s",
                        "children": [c.id for c in children],
                    }
                # 收集执行结果，区分成功和失败
                child_results = []
                success_count = 0
                fail_count = 0
                for i, child in enumerate(children):
                    r = results[i]
                    if isinstance(r, BaseException):
                        result_payload = {"error": str(r), "error_type": type(r).__name__}
                        fail_count += 1
                        agent.metrics["tasks_failed"] += 1
                        logger.warning(f"子 Agent {child.id} 执行失败: {r}")
                    else:
                        result_payload = r if isinstance(r, dict) else {"result": r}
                        success_count += 1
                    child_results.append(result_payload)
                    # 发送结果消息给父 Agent
                    result_msg = AgentMessage(
                        id=f"msg_{uuid.uuid4().hex[:12]}",
                        sender_id=child.id,
                        receiver_id=agent.id,
                        msg_type="task_result",
                        payload=result_payload if isinstance(result_payload, dict) else {},
                    )
                    await self.message_bus.send(result_msg)

                # 如果所有子 Agent 都失败，回退到父 Agent 串行执行
                if fail_count == len(children) and agent.task_queue:
                    logger.warning(
                        f"所有子 Agent 均失败，回退到父 Agent {agent_id} 串行执行"
                    )
                    agent.state = AgentState.WORKING
                    fallback_result = await self._run_agent(agent_id)
                    return {
                        "strategy": "split_fallback_serial",
                        "children_failed": [c.id for c in children],
                        "fallback_result": fallback_result,
                    }

                agent.state = AgentState.IDLE
                return {
                    "strategy": "split_and_parallel",
                    "children": [c.id for c in children],
                    "success_count": success_count,
                    "fail_count": fail_count,
                    "results": child_results,
                }

        # 直接执行
        result = await self._run_agent(agent_id)
        return result

    TASK_TIMEOUT_SECONDS = 300  # 单个任务超时（秒）

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
                result = await asyncio.wait_for(
                    self._execute_single_task(agent, task),
                    timeout=self.TASK_TIMEOUT_SECONDS,
                )

                latency = (time.monotonic() - t0) * 1000
                result["latency_ms"] = latency
                agent.metrics["tasks_completed"] += 1
                agent.metrics["total_latency_ms"] += latency
                agent.completed_tasks.append(result)
                results.append(result)

                if result.get("simulated"):
                    logger.warning(
                        f"Agent {agent_id} task was SIMULATED (no LLM): "
                        f"{task.get('description', str(task)[:80])}"
                    )

            except asyncio.TimeoutError:
                latency = (time.monotonic() - t0) * 1000
                agent.metrics["tasks_failed"] += 1
                results.append({
                    "task": task,
                    "error": f"Task timed out after {self.TASK_TIMEOUT_SECONDS}s",
                    "error_type": "TimeoutError",
                    "latency_ms": latency,
                })
                logger.error(
                    f"Agent {agent_id} task timed out after {self.TASK_TIMEOUT_SECONDS}s: "
                    f"{task.get('description', str(task)[:80])}"
                )

            except Exception as e:
                agent.metrics["tasks_failed"] += 1
                results.append({"task": task, "error": str(e)})

        agent.state = AgentState.IDLE
        agent.last_active = time.time()
        any_simulated = any(r.get("simulated") for r in results)
        return {
            "agent_id": agent_id,
            "results": results,
            "status": "simulated" if any_simulated else "completed",
        }

    async def _execute_single_task(self, agent: TaskAgent, task: Dict) -> Dict:
        """执行单个任务 — 带 ReAct 工具调用循环

        流程:
          1. 构建 messages（system_prompt + task）
          2. 收集可用工具（MCP/Skill/Node 三层）
          3. 调用 LLM（带 tools）→ 如果有 tool_calls → 执行 → 追加结果 → 继续
          4. 无 tool_calls 时返回最终文本
        """
        if self.llm_router:
            messages = [
                {"role": "system", "content": agent.config.system_prompt},
                {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
            ]

            # 收集可用工具
            tools = []
            try:
                from core.openclawd import get_openclawd
                clawd = get_openclawd()
                tools = clawd._collect_tools()
            except Exception as e:
                logger.debug(f"Agent 工具收集失败（降级为无工具模式）: {e}")

            # ReAct 循环（使用结构化 ToolCallRecord）
            import time as _time
            from core.schemas.tool_call import ToolCallRecord, ToolCallStatus

            tool_records: list = []
            max_react_iterations = 8

            for iteration in range(max_react_iterations):
                async def _llm_call():
                    return await self.llm_router.chat(
                        messages=messages,
                        tools=tools if tools else None,
                        task_type="agent_control",
                    )

                if self._llm_circuit_breaker:
                    resp = await self._llm_circuit_breaker.execute(_llm_call)
                else:
                    resp = await _llm_call()

                if not resp.tool_calls:
                    return {
                        "task": task,
                        "output": resp.content,
                        "provider": resp.provider,
                        "tool_calls": [r.model_dump() for r in tool_records],
                        "iterations": iteration + 1,
                    }

                # 处理 tool_calls
                assistant_msg = {"role": "assistant", "content": resp.content or ""}
                if resp.tool_calls:
                    assistant_msg["tool_calls"] = resp.tool_calls
                messages.append(assistant_msg)

                for tc in resp.tool_calls:
                    tc_func = tc.get("function", {})
                    tc_name = tc_func.get("name", "")
                    tc_id = tc.get("id", f"call_{tc_name}")

                    try:
                        tc_args = json.loads(tc_func.get("arguments", "{}"))
                    except (ValueError, TypeError):
                        tc_args = {}

                    logger.info(f"Agent {agent.id} 调用工具: {tc_name}")

                    t0 = _time.time()
                    try:
                        result = await clawd._dispatch_tool_call(tc_name, tc_args)
                    except Exception:
                        result = {"success": False, "error": f"工具 {tc_name} 不可用"}
                    elapsed_ms = (_time.time() - t0) * 1000

                    layer = ToolCallRecord.classify_layer(tc_name)
                    status = ToolCallStatus.SUCCESS if result.get("success", True) else ToolCallStatus.ERROR
                    result_str = str(result.get("result", result.get("error", "")))
                    tool_records.append(ToolCallRecord(
                        tool_name=tc_name,
                        layer=layer,
                        arguments=tc_args,
                        result=result_str[:2000],
                        status=status,
                        error=result.get("error") if not result.get("success", True) else None,
                        latency_ms=round(elapsed_ms, 1),
                        iteration=iteration,
                    ))

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_str[:4000],
                    })

            # 达到最大迭代次数
            return {
                "task": task,
                "output": resp.content if resp else "Agent 达到最大迭代次数",
                "provider": resp.provider if resp else "",
                "tool_calls": [r.model_dump() for r in tool_records],
                "iterations": max_react_iterations,
            }

        else:
            # 无 LLM，模拟执行
            return {
                "task": task,
                "output": f"Agent {agent.config.name} 已处理任务（无 LLM 模式）",
                "simulated": True,
                "status": "simulated",
            }

    # ─────── 内部工具 ─────────

    def _check_rate_limit(self):
        """检查 Agent 创建速率限制"""
        now = time.time()
        # 清理 1 分钟前的记录
        self._creation_timestamps = [t for t in self._creation_timestamps if now - t < 60]
        if len(self._creation_timestamps) >= self.MAX_CREATES_PER_MINUTE:
            raise RuntimeError(
                f"Agent 创建速率超限: {len(self._creation_timestamps)}/{self.MAX_CREATES_PER_MINUTE} per minute"
            )
        if len(self.agents) >= self.MAX_AGENTS:
            raise RuntimeError(f"Agent 数量超限: {len(self.agents)}/{self.MAX_AGENTS}")

    def _register_agent(self, agent: TaskAgent):
        self._check_rate_limit()
        self.agents[agent.id] = agent
        self.message_bus.register(agent.id)
        self._creation_timestamps.append(time.time())
        if agent.parent_id:
            if agent.parent_id not in self.agent_tree:
                self.agent_tree[agent.parent_id] = []
            self.agent_tree[agent.parent_id].append(agent.id)
        self._persist_state()

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
        self.message_bus.unregister(agent_id)
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
            self.message_bus.unregister(aid)
            del self.agents[aid]
            # 从 agent_tree 中清理
            for parent_id in list(self.agent_tree.keys()):
                if aid in self.agent_tree[parent_id]:
                    self.agent_tree[parent_id].remove(aid)
        if expired:
            logger.info(f"清理了 {len(expired)} 个过期 Agent")
            self._persist_state()

    # ─────── 生命周期管理 ─────────

    async def start_cleanup_loop(self):
        """启动定期清理任务"""
        if self._cleanup_task is not None:
            return

        async def _loop():
            while True:
                await asyncio.sleep(self.CLEANUP_INTERVAL)
                try:
                    self.cleanup_expired()
                except Exception as e:
                    logger.error(f"Agent 清理循环异常: {e}")

        self._cleanup_task = asyncio.create_task(_loop())
        logger.info(f"Agent TTL 清理循环已启动 (间隔 {self.CLEANUP_INTERVAL}s)")

    async def stop_cleanup_loop(self):
        """停止清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Agent TTL 清理循环已停止")

    # ─────── 状态持久化 ─────────

    def _persist_state(self):
        """持久化 Agent 状态到磁盘"""
        import os as _os
        state_dir = _os.path.dirname(self.STATE_FILE)
        if state_dir:
            _os.makedirs(state_dir, exist_ok=True)
        try:
            state = {
                "agents": {},
                "agent_tree": self.agent_tree,
                "timestamp": time.time(),
            }
            for aid, agent in self.agents.items():
                if agent.state in (AgentState.TERMINATED, AgentState.COMPLETED):
                    continue  # 不持久化已终止的 Agent
                state["agents"][aid] = {
                    "id": agent.id,
                    "config": {
                        "role": agent.config.role.value,
                        "name": agent.config.name,
                        "description": agent.config.description,
                        "system_prompt": agent.config.system_prompt,
                        "max_subtasks": agent.config.max_subtasks,
                        "max_depth": agent.config.max_depth,
                        "split_threshold": agent.config.split_threshold,
                        "ttl": agent.config.ttl,
                    },
                    "state": agent.state.value,
                    "parent_id": agent.parent_id,
                    "children_ids": agent.children_ids,
                    "creation_mode": agent.creation_mode.value,
                    "depth": agent.depth,
                    "created_at": agent.created_at,
                    "last_active": agent.last_active,
                    "metrics": agent.metrics,
                }
            with open(self.STATE_FILE, "w") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Agent 状态持久化失败: {e}")

    def _load_state(self):
        """从磁盘恢复 Agent 状态"""
        import os as _os
        if not _os.path.exists(self.STATE_FILE):
            return
        try:
            with open(self.STATE_FILE) as f:
                state = json.load(f)

            self.agent_tree = state.get("agent_tree", {})
            loaded = 0
            for aid, adata in state.get("agents", {}).items():
                cfg_data = adata.get("config", {})
                try:
                    role = AgentRole(cfg_data.get("role", "executor"))
                except ValueError:
                    role = AgentRole.EXECUTOR

                config = AgentConfig(
                    role=role,
                    name=cfg_data.get("name", "restored_agent"),
                    description=cfg_data.get("description", ""),
                    capabilities=[],
                    system_prompt=cfg_data.get("system_prompt", ""),
                    max_subtasks=cfg_data.get("max_subtasks", 5),
                    max_depth=cfg_data.get("max_depth", 3),
                    split_threshold=cfg_data.get("split_threshold", 3),
                    ttl=cfg_data.get("ttl", 3600),
                )

                try:
                    agent_state = AgentState(adata.get("state", "idle"))
                except ValueError:
                    agent_state = AgentState.IDLE

                try:
                    creation_mode = CreationMode(adata.get("creation_mode", "template"))
                except ValueError:
                    creation_mode = CreationMode.TEMPLATE

                agent = TaskAgent(
                    id=aid,
                    config=config,
                    state=agent_state,
                    parent_id=adata.get("parent_id"),
                    children_ids=adata.get("children_ids", []),
                    creation_mode=creation_mode,
                    depth=adata.get("depth", 0),
                    created_at=adata.get("created_at", time.time()),
                    last_active=adata.get("last_active", time.time()),
                    metrics=adata.get("metrics", {}),
                )
                self.agents[aid] = agent
                self.message_bus.register(aid)
                loaded += 1

            if loaded:
                logger.info(f"从磁盘恢复了 {loaded} 个 Agent")
        except Exception as e:
            logger.warning(f"Agent 状态恢复失败: {e}")

    # ─────── 分形任务 ─────────

    async def create_fractal_task(
        self, task_description: str, context: Optional[Dict] = None
    ) -> Dict:
        """
        通过 FractalExecutor 执行分形递归任务分解。

        适用于复杂多步骤任务 — FractalAgent 会自动评估复杂度，
        递归分解子任务，并行执行后合并结果。
        """
        from core.fractal_agent import get_fractal_executor

        executor = get_fractal_executor(
            llm_router=self.llm_router,
            agent_factory=self,
        )
        result = await executor.run(task_description, context)

        return {
            "success": result.success,
            "reply": result.summary if hasattr(result, "summary") else str(result),
            "data": {
                "total_agents": result.total_agents if hasattr(result, "total_agents") else 0,
                "latency_ms": result.latency_ms if hasattr(result, "latency_ms") else 0,
                "mode": "fractal",
            },
        }

    # ─────── 统一模板注册表 ─────────

    def register_template(self, name: str, config: AgentConfig):
        """动态注册新的 Agent 模板（运行时扩展）"""
        AGENT_TEMPLATES[name] = config
        logger.info(f"模板注册: {name} ({config.role.value})")

    def list_templates(self) -> List[Dict]:
        """列出所有可用模板（含内置 + 动态注册）"""
        result = []
        for name, cfg in AGENT_TEMPLATES.items():
            result.append({
                "name": name,
                "role": cfg.role.value,
                "description": cfg.description,
                "capabilities": [c.name for c in cfg.capabilities],
                "max_subtasks": cfg.max_subtasks,
                "max_depth": cfg.max_depth,
            })
        return result

    def create_unified(
        self,
        agent_type: str,
        task_description: str = "",
        template_name: str = "",
        device_id: str = "",
        device_type: str = "",
        context: Optional[Dict] = None,
    ) -> Dict:
        """
        统一创建接口 — 支持所有 Agent 类型:
        - "task"    → create_from_template / create_from_llm
        - "device"  → DeviceAgentManager.create_agent
        - "twin"    → DigitalTwinEngine.create_twin
        - "fractal" → create_fractal_task (async, 返回占位)

        Returns: {"agent_id": ..., "type": ..., "status": ...}
        """
        if agent_type == "task":
            if template_name and template_name in AGENT_TEMPLATES:
                agent = self.create_from_template(template_name)
            else:
                template = self._match_template(task_description or "coordinator")
                agent = self.create_from_template(template)
            return {
                "agent_id": agent.id,
                "type": "task",
                "role": agent.config.role.value,
                "name": agent.config.name,
                "status": agent.state.value,
            }

        elif agent_type == "device":
            try:
                from core.device_agent_manager import DeviceAgentManager
                manager = DeviceAgentManager()
                # DeviceAgentManager.register_device is async and requires DeviceInfo
                # For sync unified creation, return a placeholder with info
                return {
                    "agent_id": device_id or f"dev_{uuid.uuid4().hex[:8]}",
                    "type": "device",
                    "device_type": device_type or "generic",
                    "status": "ready",
                    "note": "Use POST /api/v1/devices/register for full device registration",
                }
            except Exception as e:
                return {"agent_id": None, "type": "device", "error": str(e)}

        elif agent_type == "twin":
            try:
                from core.digital_twin_engine import get_digital_twin_engine
                engine = get_digital_twin_engine()
                twin = engine.create_twin(
                    device_id=device_id or f"virtual_{uuid.uuid4().hex[:8]}",
                    device_type=device_type or "generic",
                    initial_state=context,
                )
                return {
                    "agent_id": twin.twin_id,
                    "type": "twin",
                    "device_id": twin.device_id,
                    "status": twin.status.value,
                }
            except Exception as e:
                return {"agent_id": None, "type": "twin", "error": str(e)}

        elif agent_type == "fractal":
            return {
                "agent_id": f"fractal_pending_{uuid.uuid4().hex[:8]}",
                "type": "fractal",
                "status": "use create_fractal_task() for async execution",
            }

        else:
            raise ValueError(f"未知 Agent 类型: {agent_type}，可用: task, device, twin, fractal")

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
            "templates": list(AGENT_TEMPLATES.keys()),
            "agent_tree": self.get_agent_tree(),
        }


# ───────────────────── 单例 ─────────────────────

_factory_instance: Optional[AgentFactory] = None


def get_agent_factory(llm_router=None) -> AgentFactory:
    global _factory_instance
    if _factory_instance is None:
        _factory_instance = AgentFactory(llm_router)
    return _factory_instance


# 兼容别名 (main 分支使用)
get_agent_factory_instance = get_agent_factory
