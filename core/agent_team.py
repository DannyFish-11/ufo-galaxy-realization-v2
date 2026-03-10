"""
Agent Team 协作引擎
===================

三种团队策略:
1. PARALLEL (Perplexity 风格) — 同一任务分发给 N 个不同 LLM，综合回答
2. SPECIALIZED (特种部队分工) — LLM 分解子任务，每个匹配最优 Agent+LLM
3. SWARM (群体智能) — 批量同类 Agent 并行执行，投票/合并

孪生模型集成:
- 每个 Team 成员自动创建数字孪生（默认 LOOSE 耦合）
- 支持随时解耦/耦合切换：TIGHT → LOOSE → DECOUPLED → SHADOW
- 执行时同步更新孪生状态快照 + 偏差检测

复用:
- core.agent_factory (AgentFactory, TaskAgent, AGENT_TEMPLATES, AgentMessageBus)
- core.multi_llm_router (MultiLLMRouter, TaskType, RoutingDecision)
- enhancements.agent_factory.twin_model (TwinModelManager, CouplingMode)
"""

import asyncio
import json
import logging
import time
import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Galaxy.AgentTeam")

# 孪生模型管理器（可选依赖）
try:
    from enhancements.agent_factory.twin_model import (
        TwinModelManager, CouplingMode as TwinCouplingMode, TwinState
    )
    TWIN_AVAILABLE = True
except ImportError:
    TWIN_AVAILABLE = False
    TwinModelManager = None
    TwinCouplingMode = None
    TwinState = None


# ───────────────────── 数据模型 ─────────────────────

class TeamStrategy(Enum):
    PARALLEL = "parallel"
    SPECIALIZED = "specialized"
    SWARM = "swarm"


class TeamStatus(Enum):
    IDLE = "idle"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class TeamMember:
    """团队成员"""
    agent_id: str
    agent_name: str
    provider: str
    model: str
    role_in_team: str
    template: str = ""

    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "role_in_team": self.role_in_team,
            "template": self.template,
        }


@dataclass
class MemberResult:
    """单个成员的执行结果"""
    member: TeamMember
    result: str
    latency_ms: float = 0.0
    tokens: int = 0
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "member": self.member.to_dict(),
            "result": self.result,
            "latency_ms": self.latency_ms,
            "tokens": self.tokens,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class TeamResult:
    """团队执行结果"""
    team_id: str
    strategy: str
    task: str
    member_results: List[MemberResult]
    synthesized: str
    total_latency_ms: float = 0.0
    total_tokens: int = 0

    def to_dict(self) -> Dict:
        return {
            "team_id": self.team_id,
            "strategy": self.strategy,
            "task": self.task,
            "member_results": [mr.to_dict() for mr in self.member_results],
            "synthesized": self.synthesized,
            "total_latency_ms": self.total_latency_ms,
            "total_tokens": self.total_tokens,
            "member_count": len(self.member_results),
        }


# ───── 任务类型 → Agent 模板 映射 ─────

TASK_TYPE_TO_TEMPLATE = {
    "reasoning": "coordinator",
    "coding": "code_executor",
    "analysis": "data_analyst",
    "planning": "planner",
    "research": "research",
    "agent_control": "device_controller",
    "creative": "research",
    "fast_response": "research",
    "general": "research",
}


# ───────────────────── AgentTeam ─────────────────────

class AgentTeam:
    """一个 Agent 团队实例

    支持孪生模型：每个成员可以有数字孪生体，
    通过 couple/decouple 随时切换耦合模式。
    """

    def __init__(self, team_id: str, strategy: TeamStrategy,
                 members: List[TeamMember],
                 agent_factory, llm_router,
                 twin_manager=None):
        self.team_id = team_id
        self.strategy = strategy
        self.members = members
        self.status = TeamStatus.IDLE
        self._factory = agent_factory
        self._router = llm_router
        self._results: Optional[TeamResult] = None
        # 工具能力 (由 OpenClawd 注入)
        self._tools: List[Dict] = []
        self._dispatch_fn = None  # async (tool_name, args) -> dict
        # 孪生模型
        self._twin_manager = twin_manager
        # agent_id → twin_id 映射
        self._member_twins: Dict[str, str] = {}

    def set_tools(self, tools: List[Dict], dispatch_fn=None):
        """注入工具列表和分发函数，使团队成员获得 ReAct 工具调用能力"""
        self._tools = tools
        self._dispatch_fn = dispatch_fn

    async def init_twins(self, coupling_mode: str = "loose"):
        """为所有团队成员创建数字孪生体

        Args:
            coupling_mode: "tight" | "loose" | "decoupled" | "shadow"
        """
        if not self._twin_manager or not TWIN_AVAILABLE:
            logger.debug("TwinModelManager 不可用，跳过孪生创建")
            return

        mode = TwinCouplingMode(coupling_mode)
        for member in self.members:
            if member.agent_id in self._member_twins:
                continue
            initial_snapshot = {
                "agent_id": member.agent_id,
                "provider": member.provider,
                "model": member.model,
                "role": member.role_in_team,
                "team_id": self.team_id,
                "status": "idle",
                "task_count": 0,
                "last_result": None,
            }
            twin = await self._twin_manager.create_twin(
                source_id=member.agent_id,
                name=f"twin_{member.agent_name}",
                coupling_mode=mode,
                initial_snapshot=initial_snapshot,
            )
            self._member_twins[member.agent_id] = twin.twin_id
            logger.info(f"成员 {member.agent_name} 创建孪生: {twin.twin_id} (模式: {coupling_mode})")

    async def couple_member(self, agent_id: str, mode: str = "loose"):
        """切换成员的耦合模式"""
        if not self._twin_manager or not TWIN_AVAILABLE:
            return
        twin_id = self._member_twins.get(agent_id)
        if twin_id:
            self._twin_manager.couple(twin_id, TwinCouplingMode(mode))

    async def decouple_member(self, agent_id: str):
        """解耦成员"""
        if not self._twin_manager or not TWIN_AVAILABLE:
            return
        twin_id = self._member_twins.get(agent_id)
        if twin_id:
            self._twin_manager.decouple(twin_id)

    def get_twin_status(self) -> List[Dict]:
        """获取所有成员的孪生状态"""
        if not self._twin_manager or not TWIN_AVAILABLE:
            return []
        statuses = []
        for member in self.members:
            twin_id = self._member_twins.get(member.agent_id)
            if twin_id:
                twin = self._twin_manager.get_twin(twin_id)
                if twin:
                    statuses.append({
                        "agent_id": member.agent_id,
                        "agent_name": member.agent_name,
                        "twin_id": twin.twin_id,
                        "state": twin.state.value,
                        "coupling_mode": twin.coupling_mode.value,
                        "divergence": twin.current_divergence,
                        "sync_count": twin.sync_count,
                    })
        return statuses

    async def _update_member_twin(self, agent_id: str, snapshot_update: Dict):
        """执行后更新成员孪生体的状态快照"""
        if not self._twin_manager or not TWIN_AVAILABLE:
            return
        twin_id = self._member_twins.get(agent_id)
        if twin_id:
            twin = self._twin_manager.get_twin(twin_id)
            if twin:
                merged = {**twin.snapshot, **snapshot_update}
                await self._twin_manager.update_snapshot(twin_id, merged)

    def to_dict(self) -> Dict:
        result = {
            "team_id": self.team_id,
            "strategy": self.strategy.value,
            "status": self.status.value,
            "member_count": len(self.members),
            "members": [m.to_dict() for m in self.members],
        }
        # 附加孪生状态
        twin_status = self.get_twin_status()
        if twin_status:
            result["twin_status"] = twin_status
        return result

    async def execute(self, task: str, context: Optional[Dict] = None) -> TeamResult:
        """根据策略执行团队任务

        执行过程中自动更新每个成员的孪生体状态快照。
        """
        self.status = TeamStatus.EXECUTING
        t0 = time.monotonic()

        # 初始化孪生体（如果尚未创建）
        if self._twin_manager and not self._member_twins:
            await self.init_twins()

        try:
            if self.strategy == TeamStrategy.PARALLEL:
                result = await self._execute_parallel(task, context)
            elif self.strategy == TeamStrategy.SPECIALIZED:
                result = await self._execute_specialized(task, context)
            elif self.strategy == TeamStrategy.SWARM:
                result = await self._execute_swarm(task, context)
            else:
                raise ValueError(f"未知策略: {self.strategy}")

            result.total_latency_ms = (time.monotonic() - t0) * 1000
            result.total_tokens = sum(mr.tokens for mr in result.member_results)
            self.status = TeamStatus.COMPLETED
            self._results = result

            # 更新所有成员孪生体
            for mr in result.member_results:
                await self._update_member_twin(mr.member.agent_id, {
                    "status": "completed" if mr.success else "error",
                    "last_task": task[:100],
                    "last_result": mr.result[:200] if mr.result else None,
                    "last_latency_ms": mr.latency_ms,
                    "task_count": 1,  # will be merged with existing
                    "success": mr.success,
                })

            return result

        except Exception as e:
            self.status = TeamStatus.ERROR
            logger.error(f"Team {self.team_id} 执行失败: {e}")
            return TeamResult(
                team_id=self.team_id,
                strategy=self.strategy.value,
                task=task,
                member_results=[],
                synthesized=f"团队执行失败: {str(e)}",
                total_latency_ms=(time.monotonic() - t0) * 1000,
            )

    # ─────── 成员 ReAct 执行 (带工具) ───────

    async def _call_member_with_tools(
        self, member: TeamMember, messages: List[Dict], max_iterations: int = 6,
    ) -> MemberResult:
        """带 ReAct 工具调用的成员执行 — 有工具走循环，无工具走直连"""
        t0 = time.monotonic()
        total_tokens = 0

        try:
            if self._tools and self._dispatch_fn:
                # ReAct 循环
                resp = None
                for _ in range(max_iterations):
                    resp = await self._router.chat(
                        messages=messages,
                        tools=self._tools,
                        provider=member.provider,
                        model=member.model,
                        max_tokens=2048,
                    )
                    total_tokens += resp.input_tokens + resp.output_tokens

                    if not resp.tool_calls:
                        break

                    # 追加 assistant tool_calls
                    assistant_msg = {"role": "assistant", "content": resp.content or ""}
                    if resp.tool_calls:
                        assistant_msg["tool_calls"] = resp.tool_calls
                    messages.append(assistant_msg)

                    # 执行每个 tool_call
                    for tc in resp.tool_calls:
                        tc_func = tc.get("function", {})
                        tc_name = tc_func.get("name", "")
                        tc_id = tc.get("id", f"call_{tc_name}")
                        try:
                            tc_args = json.loads(tc_func.get("arguments", "{}"))
                        except (ValueError, TypeError):
                            tc_args = {}

                        result = await self._dispatch_fn(tc_name, tc_args)
                        result_str = str(result.get("result", result.get("error", "")))
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": result_str[:4000],
                        })

                return MemberResult(
                    member=member,
                    result=resp.content if resp else "",
                    latency_ms=(time.monotonic() - t0) * 1000,
                    tokens=total_tokens,
                )
            else:
                # 无工具 — 直接调用
                response = await self._router.chat(
                    messages=messages,
                    provider=member.provider,
                    model=member.model,
                    max_tokens=2048,
                )
                return MemberResult(
                    member=member,
                    result=response.content,
                    latency_ms=(time.monotonic() - t0) * 1000,
                    tokens=response.input_tokens + response.output_tokens,
                )
        except Exception as e:
            return MemberResult(
                member=member,
                result="",
                latency_ms=(time.monotonic() - t0) * 1000,
                success=False,
                error=str(e),
            )

    # ─────── 策略 1: PARALLEL (Perplexity 风格) ───────

    async def _execute_parallel(self, task: str, context: Optional[Dict]) -> TeamResult:
        """每个成员用不同 LLM 独立回答同一任务，最后综合"""

        async def _call_member(member: TeamMember) -> MemberResult:
            messages = [
                {"role": "system", "content": f"你是 {member.agent_name}，擅长 {member.role_in_team}。请独立分析并回答。"},
                {"role": "user", "content": task},
            ]
            if context:
                messages[0]["content"] += f"\n\n上下文:\n{json.dumps(context, ensure_ascii=False)}"
            return await self._call_member_with_tools(member, messages)

        # 并行调用所有成员
        member_results = await asyncio.gather(
            *[_call_member(m) for m in self.members]
        )
        member_results = list(member_results)

        # 综合所有结果
        synthesized = await self._synthesize_results(
            task, member_results, "综合以上各方回答，给出最全面准确的回答。"
        )

        return TeamResult(
            team_id=self.team_id,
            strategy="parallel",
            task=task,
            member_results=member_results,
            synthesized=synthesized,
        )

    # ─────── 策略 2: SPECIALIZED (特种部队分工) ───────

    async def _execute_specialized(self, task: str, context: Optional[Dict]) -> TeamResult:
        """LLM 分解子任务 → 每个子任务匹配最优 Agent+LLM → 并行执行 → 综合"""

        # Step 1: 用 LLM 分解任务
        subtasks = await self._decompose_task(task, context)

        if not subtasks:
            # 分解失败，退回 parallel
            return await self._execute_parallel(task, context)

        # Step 2: 为每个子任务分配最优成员
        assignments = []
        available_members = list(self.members)

        for st in subtasks:
            # 分类子任务
            task_type = self._router.classify_task(
                [{"role": "user", "content": st["description"]}]
            )
            # 选最优提供商
            try:
                decision = self._router.route(task_type)
            except RuntimeError:
                decision = None

            # 匹配成员
            member = None
            if decision:
                for m in available_members:
                    if m.provider == decision.provider:
                        member = m
                        break
            if member is None and available_members:
                member = available_members[0]

            if member:
                assignments.append((st, member))

        # Step 3: 并行执行 (带工具)
        async def _exec_subtask(subtask: Dict, member: TeamMember) -> MemberResult:
            messages = [
                {"role": "system", "content": f"你是 {member.agent_name}。你的任务是: {subtask['title']}"},
                {"role": "user", "content": subtask["description"]},
            ]
            result = await self._call_member_with_tools(member, messages)
            # 前缀子任务标题
            if result.success and result.result:
                result.result = f"[{subtask['title']}]\n{result.result}"
            else:
                result.result = f"[{subtask['title']}] 失败"
            return result

        member_results = await asyncio.gather(
            *[_exec_subtask(st, m) for st, m in assignments]
        )
        member_results = list(member_results)

        # Step 4: 综合
        synthesized = await self._synthesize_results(
            task, member_results, "整合以上各专家团队的子任务结果，给出完整的综合回答。"
        )

        return TeamResult(
            team_id=self.team_id,
            strategy="specialized",
            task=task,
            member_results=member_results,
            synthesized=synthesized,
        )

    # ─────── 策略 3: SWARM (群体智能) ───────

    async def _execute_swarm(self, task: str, context: Optional[Dict]) -> TeamResult:
        """批量 Agent 并行执行同一任务，多数投票或综合合并"""

        async def _call_member(member: TeamMember) -> MemberResult:
            messages = [
                {"role": "system", "content": f"你是 {member.agent_name}。请独立思考并给出你的回答。"},
                {"role": "user", "content": task},
            ]
            return await self._call_member_with_tools(member, messages)

        member_results = list(await asyncio.gather(
            *[_call_member(m) for m in self.members]
        ))

        # 综合合并
        synthesized = await self._synthesize_results(
            task, member_results, "以上是多个独立 Agent 的回答。综合所有观点，给出最佳回答。如有分歧，指出不同观点。"
        )

        return TeamResult(
            team_id=self.team_id,
            strategy="swarm",
            task=task,
            member_results=member_results,
            synthesized=synthesized,
        )

    # ─────── 辅助方法 ───────

    async def _decompose_task(self, task: str, context: Optional[Dict]) -> List[Dict]:
        """用 LLM 分解任务为子任务列表"""
        try:
            prompt = f"""将以下任务分解为 2-5 个独立的子任务。

任务: {task}

以 JSON 数组格式返回，每个子任务包含 "title" 和 "description" 字段。
例: [{{"title": "数据收集", "description": "..."}}, {{"title": "分析", "description": "..."}}]

只返回 JSON，不要其他内容。"""

            response = await self._router.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type="planning",
                max_tokens=1024,
                temperature=0.3,
            )

            # 提取 JSON
            text = response.content.strip()
            # 尝试从 markdown 代码块提取
            if "```" in text:
                import re
                match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
                if match:
                    text = match.group(1).strip()

            subtasks = json.loads(text)
            if isinstance(subtasks, list) and len(subtasks) >= 2:
                return subtasks
        except Exception as e:
            logger.warning(f"任务分解失败: {e}")
        return []

    async def _synthesize_results(self, task: str,
                                   member_results: List[MemberResult],
                                   instruction: str) -> str:
        """用 coordinator LLM 综合所有成员结果"""
        successful = [mr for mr in member_results if mr.success and mr.result]
        if not successful:
            return "所有成员执行失败，无法综合结果。"

        if len(successful) == 1:
            return successful[0].result

        results_text = "\n\n".join(
            f"--- {mr.member.agent_name} ({mr.member.provider}:{mr.member.model}) ---\n{mr.result}"
            for mr in successful
        )

        try:
            response = await self._router.chat(
                messages=[
                    {"role": "system", "content": "你是一个综合分析专家。"},
                    {"role": "user", "content": f"原始任务: {task}\n\n各方回答:\n{results_text}\n\n{instruction}"},
                ],
                task_type="reasoning",
                max_tokens=4096,
            )
            return response.content
        except Exception as e:
            # 综合失败，拼接所有结果
            logger.warning(f"综合结果失败: {e}，返回拼接结果")
            return results_text


# ───────────────────── TeamManager ─────────────────────

class TeamManager:
    """管理所有 Agent Team 的生命周期

    支持孪生模型：创建 Team 时自动为成员建立数字孪生，
    可通过 API 随时切换 TIGHT/LOOSE/DECOUPLED/SHADOW 模式。
    """

    def __init__(self, agent_factory=None, llm_router=None, twin_manager=None):
        self._factory = agent_factory
        self._router = llm_router
        self._twin_manager = twin_manager
        self.teams: Dict[str, AgentTeam] = {}
        logger.info(f"TeamManager 已初始化 (twin={TWIN_AVAILABLE and twin_manager is not None})")

    async def create_team(self, strategy: str, task_hint: str = "",
                          complexity_score: float = 0.5) -> AgentTeam:
        """创建一个 Agent 团队"""
        try:
            strat = TeamStrategy(strategy)
        except ValueError:
            raise ValueError(f"未知策略: {strategy}，可选: {[s.value for s in TeamStrategy]}")

        team_id = f"team_{uuid.uuid4().hex[:12]}"

        # 根据策略和可用提供商创建成员 (使用复杂度选模型)
        members = self._create_members(strat, task_hint, complexity_score)

        team = AgentTeam(
            team_id=team_id,
            strategy=strat,
            members=members,
            agent_factory=self._factory,
            llm_router=self._router,
            twin_manager=self._twin_manager,
        )

        self.teams[team_id] = team
        logger.info(f"Team {team_id} 已创建，策略={strategy}，成员数={len(members)}")
        return team

    def _create_members(self, strategy: TeamStrategy, task_hint: str,
                        complexity_score: float = 0.5) -> List[TeamMember]:
        """根据策略创建团队成员 (按复杂度选模型)"""
        members = []

        if not self._router or not self._router.providers:
            return [TeamMember(
                agent_id=f"agent_{uuid.uuid4().hex[:8]}",
                agent_name="默认 Agent",
                provider="none",
                model="none",
                role_in_team="worker",
            )]

        providers = list(self._router.providers.items())

        # 预计算任务类型 (用于复杂度选模型)
        _task_type = None
        if task_hint:
            _task_type = self._router.classify_task(
                [{"role": "user", "content": task_hint}]
            )

        def _pick_model(prov_name: str, prov_cfg) -> str:
            """按复杂度选模型，fallback 到 default_model"""
            if _task_type and hasattr(self._router, "select_model_by_complexity"):
                try:
                    return self._router.select_model_by_complexity(
                        prov_name, _task_type, complexity_score,
                    )
                except Exception:
                    pass
            return prov_cfg.default_model

        if strategy == TeamStrategy.PARALLEL:
            # 每个可用提供商一个成员
            for prov_name, prov_cfg in providers:
                if self._router.adapters.get(prov_name) is None:
                    continue
                agent_id = f"agent_{uuid.uuid4().hex[:8]}"
                # 用 factory 创建 Agent（如果可用）
                if self._factory:
                    try:
                        agent = self._factory.create_from_template("research")
                        agent_id = agent.id
                    except Exception:
                        pass

                members.append(TeamMember(
                    agent_id=agent_id,
                    agent_name=f"研究员-{prov_name}",
                    provider=prov_name,
                    model=_pick_model(prov_name, prov_cfg),
                    role_in_team="researcher",
                    template="research",
                ))

        elif strategy == TeamStrategy.SPECIALIZED:
            # 创建不同角色的成员，分配到不同提供商
            roles = [
                ("analyst", "data_analyst", "分析专家"),
                ("coder", "code_executor", "编码专家"),
                ("planner", "planner", "规划专家"),
                ("researcher", "research", "研究专家"),
            ]
            for i, (role, template, name) in enumerate(roles):
                prov_name, prov_cfg = providers[i % len(providers)]
                agent_id = f"agent_{uuid.uuid4().hex[:8]}"
                if self._factory:
                    try:
                        agent = self._factory.create_from_template(template)
                        agent_id = agent.id
                    except Exception:
                        pass

                members.append(TeamMember(
                    agent_id=agent_id,
                    agent_name=name,
                    provider=prov_name,
                    model=_pick_model(prov_name, prov_cfg),
                    role_in_team=role,
                    template=template,
                ))

            # 加一个 coordinator
            prov_name, prov_cfg = providers[0]
            agent_id = f"agent_{uuid.uuid4().hex[:8]}"
            if self._factory:
                try:
                    agent = self._factory.create_from_template("coordinator")
                    agent_id = agent.id
                except Exception:
                    pass
            members.append(TeamMember(
                agent_id=agent_id,
                agent_name="总协调",
                provider=prov_name,
                model=_pick_model(prov_name, prov_cfg),
                role_in_team="coordinator",
                template="coordinator",
            ))

        elif strategy == TeamStrategy.SWARM:
            # 批量创建同类 Agent，分布到不同提供商
            swarm_size = min(5, max(3, len(providers) * 2))
            for i in range(swarm_size):
                prov_name, prov_cfg = providers[i % len(providers)]
                agent_id = f"agent_{uuid.uuid4().hex[:8]}"
                if self._factory:
                    try:
                        agent = self._factory.create_from_template("research")
                        agent_id = agent.id
                    except Exception:
                        pass
                members.append(TeamMember(
                    agent_id=agent_id,
                    agent_name=f"Swarm-{i+1}",
                    provider=prov_name,
                    model=_pick_model(prov_name, prov_cfg),
                    role_in_team=f"swarm_worker_{i+1}",
                    template="research",
                ))

        return members

    async def execute_team(self, team_id: str, task: str,
                           context: Optional[Dict] = None) -> TeamResult:
        """执行团队任务"""
        team = self.teams.get(team_id)
        if not team:
            raise ValueError(f"Team {team_id} 不存在")
        return await team.execute(task, context)

    async def execute_team_task(
        self,
        task: str,
        strategy,
        member_count: int = 3,
        providers: Optional[List[str]] = None,
        context: Optional[Dict] = None,
    ) -> Dict:
        """一站式接口 — 创建团队 → 执行 → 解散 → 返回结果

        供 routes/ai.py 端点调用，封装完整的团队生命周期。

        Args:
            task: 任务描述
            strategy: TeamStrategy 枚举或字符串
            member_count: 期望成员数
            providers: 限定使用的 LLM 提供商列表
            context: 额外上下文
        """
        # 策略标准化
        strat_value = strategy.value if hasattr(strategy, "value") else str(strategy)

        team = await self.create_team(strategy=strat_value, task_hint=task)

        # 按请求过滤/截取成员
        if providers:
            team.members = [m for m in team.members if m.provider in providers]
            if not team.members:
                # 所有成员都被过滤掉 → 用原始成员
                team = await self.create_team(strategy=strat_value, task_hint=task)

        if member_count and len(team.members) > member_count:
            team.members = team.members[:member_count]

        try:
            team_result = await team.execute(task, context)
            return team_result.to_dict()
        finally:
            self.disband_team(team.team_id)

    def list_teams(self) -> List[Dict]:
        """列出所有团队"""
        return [team.to_dict() for team in self.teams.values()]

    def get_team(self, team_id: str) -> Optional[AgentTeam]:
        return self.teams.get(team_id)

    def disband_team(self, team_id: str) -> bool:
        """解散团队（同时清理成员孪生体）"""
        team = self.teams.pop(team_id, None)
        if team:
            # 清理孪生体
            if team._twin_manager and TWIN_AVAILABLE:
                for agent_id, twin_id in team._member_twins.items():
                    try:
                        asyncio.get_event_loop().create_task(
                            team._twin_manager.delete_twin(twin_id)
                        )
                    except RuntimeError:
                        # 没有事件循环时直接跳过
                        pass
                team._member_twins.clear()

            # 清理 factory 中的 agent
            if self._factory:
                for member in team.members:
                    agent = self._factory.agents.pop(member.agent_id, None)
                    if agent:
                        self._factory.message_bus.unregister(member.agent_id)
            logger.info(f"Team {team_id} 已解散（含孪生清理）")
            return True
        return False
