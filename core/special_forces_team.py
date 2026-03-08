"""
UFO Galaxy - 特种部队 Agent 团队 (Special Forces Team)
======================================================

异构多模型团队：每个成员使用不同的 LLM 模型，根据专长分工。
Claude 负责推理，DeepSeek 负责编码，GPT-4o 负责创意，Groq 负责快速侦察。
成员通过 AgentMessageBus 协调，由 LEAD 统一指挥。
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.SpecialForces")


# ───────────────────── 数据模型 ─────────────────────

class TeamRole(Enum):
    """团队角色"""
    STRATEGIST = "strategist"    # 策略分析（强推理模型）
    CODER = "coder"              # 代码生成（代码模型）
    CREATIVE = "creative"        # 创意写作（创意模型）
    ANALYST = "analyst"          # 数据分析
    SCOUT = "scout"              # 快速侦察（快速模型）
    LEAD = "lead"                # 团队指挥


class CoordinationMode(Enum):
    """协调模式"""
    SEQUENTIAL = "sequential"    # 顺序执行，输出链式传递
    PARALLEL = "parallel"        # 并行执行
    PIPELINE = "pipeline"        # 流水线模式


@dataclass
class TeamMember:
    """团队成员"""
    member_id: str
    role: TeamRole
    agent: Any  # TaskAgent
    provider: str
    model: str
    specialties: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "member_id": self.member_id,
            "role": self.role.value,
            "provider": self.provider,
            "model": self.model,
            "specialties": self.specialties,
        }


@dataclass
class TeamConfig:
    """团队配置"""
    composition: Optional[Dict] = None  # role -> {"provider", "model", "template"}
    coordination_mode: CoordinationMode = CoordinationMode.PARALLEL
    max_rounds: int = 3
    timeout_per_member: float = 90.0


@dataclass
class TeamResult:
    """团队执行结果"""
    task_id: str
    member_contributions: Dict[str, Dict] = field(default_factory=dict)
    final_output: Any = None
    coordination_rounds: int = 0
    total_latency_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "members": len(self.member_contributions),
            "coordination_rounds": self.coordination_rounds,
            "total_latency_ms": self.total_latency_ms,
            "final_output": self.final_output,
        }


# ───────────────────── 默认团队组成 ─────────────────────

DEFAULT_TEAM_COMPOSITION: Dict[TeamRole, Dict] = {
    TeamRole.STRATEGIST: {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "template": "planner",
        "specialties": ["推理", "策略", "风险评估"],
    },
    TeamRole.CODER: {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "template": "code_executor",
        "specialties": ["代码生成", "调试", "架构"],
    },
    TeamRole.CREATIVE: {
        "provider": "openai",
        "model": "gpt-4o",
        "template": "research",
        "specialties": ["创意写作", "文案", "设计建议"],
    },
    TeamRole.ANALYST: {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "template": "data_analyst",
        "specialties": ["数据分析", "统计", "可视化"],
    },
    TeamRole.SCOUT: {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "template": "research",
        "specialties": ["快速搜索", "信息收集", "摘要"],
    },
    TeamRole.LEAD: {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "template": "coordinator",
        "specialties": ["团队协调", "任务分配", "结果综合"],
    },
}


# ───────────────────── SpecialForcesTeam ─────────────────────

class SpecialForcesTeam:
    """
    特种部队 Agent 团队 — 每个成员使用不同 LLM 模型。

    工作流程:
    1. LEAD 分析任务，决定需要哪些角色
    2. 按 coordination_mode 执行任务
    3. LEAD 综合所有成员结果为最终输出
    """

    def __init__(self, llm_router=None, agent_factory=None,
                 config: Optional[TeamConfig] = None):
        self.llm_router = llm_router
        self.agent_factory = agent_factory
        self.config = config or TeamConfig()
        self._composition = self.config.composition or DEFAULT_TEAM_COMPOSITION
        self._members: List[TeamMember] = []
        logger.info(
            f"SpecialForcesTeam 已初始化: "
            f"mode={self.config.coordination_mode.value}"
        )

    async def execute(self, task_description: str,
                      context: Optional[Dict] = None) -> TeamResult:
        """
        团队执行主入口。

        1. 组建团队（LEAD 分析任务选角色）
        2. 分配子任务
        3. 按协调模式执行
        4. LEAD 综合结果
        """
        task_id = f"team_{uuid.uuid4().hex[:8]}"
        start = time.time()
        context = context or {}

        logger.info(f"[{task_id}] 特种部队启动")

        try:
            # 1. 组建团队
            members = await self.assemble(task_description)
            if not members:
                return TeamResult(
                    task_id=task_id,
                    final_output="无法组建团队：没有可用的提供商",
                    total_latency_ms=(time.time() - start) * 1000,
                )

            # 2. LEAD 分配任务
            lead = self._get_lead(members)
            assignments = await self._assign_tasks(lead, task_description, members, context)

            # 3. 执行
            contributions = await self._execute_assignments(
                members, assignments, context
            )

            # 4. LEAD 综合
            final = await self._synthesize(lead, task_description, contributions)

            result = TeamResult(
                task_id=task_id,
                member_contributions=contributions,
                final_output=final,
                coordination_rounds=1,
                total_latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            logger.error(f"[{task_id}] 团队执行失败: {e}")
            result = TeamResult(
                task_id=task_id,
                final_output=f"团队执行失败: {e}",
                total_latency_ms=(time.time() - start) * 1000,
            )
        finally:
            self._cleanup()

        logger.info(
            f"[{task_id}] 特种部队完成: "
            f"{len(result.member_contributions)} 成员参与, "
            f"耗时={result.total_latency_ms:.0f}ms"
        )
        return result

    async def assemble(self, task_description: str) -> List[TeamMember]:
        """根据任务分析组建团队"""
        # 确定需要的角色
        needed_roles = await self._decide_roles(task_description)

        members = []
        for role in needed_roles:
            comp = self._composition.get(role)
            if not comp:
                continue

            # 检查 provider 是否可用
            provider = comp["provider"]
            if self.llm_router and hasattr(self.llm_router, 'providers'):
                if provider not in self.llm_router.providers:
                    # 降级到其他可用 provider
                    available = [
                        p for p in self.llm_router.providers
                        if self.llm_router.providers[p].status.value != "down"
                    ]
                    if available:
                        provider = available[0]
                        model = self.llm_router.providers[provider].default_model
                    else:
                        logger.warning(f"角色 {role.value} 无可用 provider，跳过")
                        continue
                else:
                    model = comp["model"]
            else:
                model = comp["model"]

            # 创建 Agent
            template = comp.get("template", "research")
            if self.agent_factory:
                agent = self.agent_factory.create_from_template(
                    template,
                    overrides={"name": f"特种部队-{role.value}"},
                )
            else:
                from core.agent_factory import TaskAgent, AgentConfig, AgentRole, AgentCapability
                agent = TaskAgent(
                    id=f"sf_{uuid.uuid4().hex[:8]}",
                    config=AgentConfig(
                        role=AgentRole.SPECIALIST,
                        name=f"特种部队-{role.value}",
                        description=f"特种部队 {role.value} 成员",
                        capabilities=[AgentCapability("specialized_execution", role.value)],
                        system_prompt=f"你是特种部队 {role.value}，完成分配的任务。",
                    ),
                )

            member = TeamMember(
                member_id=f"member_{role.value}_{uuid.uuid4().hex[:6]}",
                role=role,
                agent=agent,
                provider=provider,
                model=model,
                specialties=comp.get("specialties", []),
            )
            members.append(member)

        self._members = members
        logger.info(
            f"团队组建完成: {[m.role.value for m in members]}"
        )
        return members

    async def _decide_roles(self, task_description: str) -> List[TeamRole]:
        """决定任务需要哪些角色"""
        # LEAD 总是需要
        base_roles = [TeamRole.LEAD]

        if not self.llm_router:
            # 无 LLM 时基于关键词选角色
            return base_roles + self._decide_roles_by_rules(task_description)

        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": (
                        "分析任务需要哪些团队角色。可选角色：\n"
                        "- strategist: 策略分析和推理\n"
                        "- coder: 代码生成和开发\n"
                        "- creative: 创意和内容生成\n"
                        "- analyst: 数据分析\n"
                        "- scout: 快速信息收集\n\n"
                        "返回 JSON: {\"roles\": [\"role1\", \"role2\"]}"
                    )},
                    {"role": "user", "content": task_description},
                ],
                task_type="planning",
            )
            role_names = result.get("roles", [])
            roles = []
            role_map = {r.value: r for r in TeamRole}
            for name in role_names:
                if name in role_map and name != "lead":
                    roles.append(role_map[name])
            return base_roles + (roles if roles else [TeamRole.STRATEGIST])
        except Exception as e:
            logger.warning(f"LLM 角色决策失败，降级: {e}")
            return base_roles + self._decide_roles_by_rules(task_description)

    def _decide_roles_by_rules(self, task: str) -> List[TeamRole]:
        """基于规则的角色决策"""
        roles = []
        task_lower = task.lower()
        if any(w in task_lower for w in ["代码", "编程", "code", "实现", "函数", "bug"]):
            roles.append(TeamRole.CODER)
        if any(w in task_lower for w in ["分析", "数据", "统计", "analysis"]):
            roles.append(TeamRole.ANALYST)
        if any(w in task_lower for w in ["创意", "设计", "写作", "creative", "内容"]):
            roles.append(TeamRole.CREATIVE)
        if any(w in task_lower for w in ["搜索", "调研", "research", "信息"]):
            roles.append(TeamRole.SCOUT)
        if any(w in task_lower for w in ["策略", "计划", "方案", "strategy"]):
            roles.append(TeamRole.STRATEGIST)
        return roles if roles else [TeamRole.STRATEGIST]

    async def _assign_tasks(self, lead: Optional[TeamMember],
                            task_description: str,
                            members: List[TeamMember],
                            context: Dict) -> Dict[str, str]:
        """LEAD 为每个成员分配子任务"""
        if not self.llm_router or not lead:
            return {m.member_id: task_description for m in members if m.role != TeamRole.LEAD}

        member_desc = "\n".join(
            f"- {m.role.value} ({m.provider}/{m.model}): {', '.join(m.specialties)}"
            for m in members if m.role != TeamRole.LEAD
        )

        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": (
                        "你是团队指挥官。根据每个成员的专长分配子任务。\n"
                        f"团队成员:\n{member_desc}\n\n"
                        "返回 JSON: {\"assignments\": {\"角色名\": \"该成员的具体子任务\"}}"
                    )},
                    {"role": "user", "content": task_description},
                ],
                provider=lead.provider,
                model=lead.model,
                task_type="planning",
            )
            raw = result.get("assignments", {})
            # 将角色名映射到 member_id
            assignments = {}
            for m in members:
                if m.role == TeamRole.LEAD:
                    continue
                sub = raw.get(m.role.value, task_description)
                assignments[m.member_id] = sub
            return assignments
        except Exception as e:
            logger.warning(f"任务分配失败，各成员执行完整任务: {e}")
            return {m.member_id: task_description for m in members if m.role != TeamRole.LEAD}

    async def _execute_assignments(self, members: List[TeamMember],
                                   assignments: Dict[str, str],
                                   context: Dict) -> Dict[str, Dict]:
        """按协调模式执行分配的任务"""
        working_members = [m for m in members if m.member_id in assignments]

        if self.config.coordination_mode == CoordinationMode.SEQUENTIAL:
            return await self._execute_sequential(working_members, assignments, context)
        elif self.config.coordination_mode == CoordinationMode.PIPELINE:
            return await self._execute_pipeline(working_members, assignments, context)
        else:
            return await self._execute_parallel(working_members, assignments, context)

    async def _execute_parallel(self, members, assignments, context):
        """并行执行"""
        tasks = [
            self._execute_member_task(m, assignments[m.member_id], context)
            for m in members
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        contributions = {}
        for m, r in zip(members, raw):
            if isinstance(r, Exception):
                contributions[m.member_id] = {
                    "role": m.role.value, "success": False, "error": str(r)
                }
            else:
                contributions[m.member_id] = r
        return contributions

    async def _execute_sequential(self, members, assignments, context):
        """顺序执行，前一个输出作为后一个的上下文"""
        contributions = {}
        accumulated_context = dict(context)

        for m in members:
            result = await self._execute_member_task(
                m, assignments[m.member_id], accumulated_context
            )
            contributions[m.member_id] = result
            if result.get("success"):
                accumulated_context[f"{m.role.value}_output"] = result.get("output", "")

        return contributions

    async def _execute_pipeline(self, members, assignments, context):
        """流水线模式 — 每个成员的输出是下一个的输入"""
        contributions = {}
        pipe_input = context.get("initial_input", "")

        for m in members:
            task_with_input = (
                f"{assignments[m.member_id]}\n\n"
                f"前置输入:\n{pipe_input}" if pipe_input else assignments[m.member_id]
            )
            result = await self._execute_member_task(m, task_with_input, context)
            contributions[m.member_id] = result
            if result.get("success"):
                pipe_input = result.get("output", "")

        return contributions

    async def _execute_member_task(self, member: TeamMember,
                                   task: str, context: Dict) -> Dict:
        """执行单个成员任务 — 强制使用该成员的 provider/model"""
        start = time.time()

        if not self.llm_router:
            return {
                "role": member.role.value,
                "success": True,
                "output": f"[{member.role.value}] 降级执行: {task[:200]}",
                "latency_ms": 0,
            }

        try:
            messages = [
                {"role": "system", "content": (
                    f"你是特种部队的 {member.role.value}，专长: {', '.join(member.specialties)}。\n"
                    f"完成以下分配给你的任务。"
                )},
                {"role": "user", "content": task},
            ]

            response = await asyncio.wait_for(
                self.llm_router.chat(
                    messages=messages,
                    provider=member.provider,
                    model=member.model,
                    task_type="agent_control",
                    auto_failover=True,
                ),
                timeout=self.config.timeout_per_member,
            )

            return {
                "role": member.role.value,
                "success": True,
                "output": response.content,
                "provider": response.provider,
                "model": response.model,
                "latency_ms": (time.time() - start) * 1000,
            }
        except asyncio.TimeoutError:
            return {
                "role": member.role.value,
                "success": False,
                "error": "timeout",
                "latency_ms": (time.time() - start) * 1000,
            }
        except Exception as e:
            return {
                "role": member.role.value,
                "success": False,
                "error": str(e),
                "latency_ms": (time.time() - start) * 1000,
            }

    async def _synthesize(self, lead: Optional[TeamMember],
                          task_description: str,
                          contributions: Dict[str, Dict]) -> Any:
        """LEAD 综合所有成员结果"""
        successful = {k: v for k, v in contributions.items() if v.get("success")}
        if not successful:
            return "所有团队成员执行失败"

        if not self.llm_router or not lead:
            return "\n\n".join(
                f"[{v['role']}] {v.get('output', '')}"
                for v in successful.values()
            )

        formatted = "\n\n".join(
            f"--- {v['role']} ({v.get('provider', '?')}) ---\n{v.get('output', '')}"
            for v in successful.values()
        )

        response = await self.llm_router.chat(
            messages=[
                {"role": "system", "content": (
                    "你是特种部队指挥官。综合团队所有成员的输出，"
                    "形成一个完整、连贯的最终结果。"
                )},
                {"role": "user", "content": (
                    f"原始任务: {task_description}\n\n"
                    f"团队成员输出:\n{formatted}\n\n"
                    "请综合以上输出，给出最终结果。"
                )},
            ],
            provider=lead.provider,
            model=lead.model,
            task_type="analysis",
        )
        return response.content

    def _get_lead(self, members: List[TeamMember]) -> Optional[TeamMember]:
        """获取 LEAD 成员"""
        for m in members:
            if m.role == TeamRole.LEAD:
                return m
        return members[0] if members else None

    def _cleanup(self):
        """清理团队 Agent"""
        if self.agent_factory:
            for m in self._members:
                try:
                    self.agent_factory.terminate_agent(m.agent.id)
                except Exception:
                    pass
        self._members.clear()

    def get_status(self) -> Dict:
        return {
            "coordination_mode": self.config.coordination_mode.value,
            "active_members": len(self._members),
            "composition_roles": [r.value for r in self._composition],
        }


# ───────────────────── 单例 ─────────────────────

_team_instance: Optional[SpecialForcesTeam] = None


def get_special_forces_team(llm_router=None, agent_factory=None,
                            config: Optional[TeamConfig] = None) -> SpecialForcesTeam:
    global _team_instance
    if _team_instance is None:
        _team_instance = SpecialForcesTeam(
            llm_router=llm_router,
            agent_factory=agent_factory,
            config=config,
        )
    return _team_instance
