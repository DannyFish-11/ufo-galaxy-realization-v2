#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Agent 操作 Pydantic 模型
======================================

定义 Agent 创建、任务下发、响应、Team/Twin/Swarm 和
异构团队清单（TeamManifest）相关数据模型。
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ───────── Agent CRUD ─────────

class AgentCreateSchema(BaseModel):
    """Agent 创建请求"""

    name: str = Field(..., min_length=1, description="Agent 名称")
    template: str = Field(
        default="general",
        description="Agent 模板: coordinator / code_executor / data_analyst / research / device_controller / planner",
    )
    provider: str = Field(default="openai", description="LLM 提供商")
    model: str = Field(default="gpt-4", description="LLM 模型名称")
    system_prompt: str = Field(default="", description="系统提示词")

    model_config = {"from_attributes": True}


class AgentTaskSchema(BaseModel):
    """向已有 Agent 提交任务"""

    agent_id: str = Field(..., description="目标 Agent ID")
    task: str = Field(..., min_length=1, description="任务描述")
    context: Dict[str, Any] = Field(default_factory=dict, description="任务上下文")
    priority: str = Field(default="normal", description="优先级: low / normal / high / critical")

    model_config = {"from_attributes": True}


class AgentResponseSchema(BaseModel):
    """Agent 任务响应"""

    agent_id: str = Field(..., description="Agent ID")
    task_id: str = Field(default="", description="任务唯一标识符")
    response: str = Field(default="", description="Agent 生成的响应文本")
    tokens_used: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
    success: bool = Field(default=True)
    tool_calls_log: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="ReAct 循环中工具调用记录",
    )

    model_config = {"from_attributes": True}


# ───────── Team Manifest (异构团队清单) ─────────

class TeamStrategyEnum(str, Enum):
    """团队协作策略"""
    PARALLEL = "parallel"       # Perplexity 风格 — 同一任务多 LLM 并行
    SPECIALIZED = "specialized" # 特种部队 — 子任务分解，各匹配最优 Agent+LLM
    SWARM = "swarm"             # 群体智能 — 批量同类 Agent 投票/合并


class TeamMemberSchema(BaseModel):
    """团队成员描述"""

    agent_id: str = Field(default="", description="Agent ID (执行时填充)")
    agent_name: str = Field(..., description="Agent 名称")
    provider: str = Field(..., description="LLM provider")
    model: str = Field(..., description="模型 ID")
    role_in_team: str = Field(..., description="团队内角色: leader / executor / reviewer / synthesizer")
    template: str = Field(default="research", description="Agent 模板")
    subtask: str = Field(default="", description="分配的子任务 (SPECIALIZED 策略时填充)")

    model_config = {"from_attributes": True}

    @classmethod
    def from_dataclass(cls, dc) -> "TeamMemberSchema":
        """从 agent_team.TeamMember dataclass 转换"""
        return cls(
            agent_id=dc.agent_id,
            agent_name=dc.agent_name,
            provider=dc.provider,
            model=dc.model,
            role_in_team=dc.role_in_team,
            template=dc.template,
        )


class TeamManifestSchema(BaseModel):
    """异构团队清单 — 描述一个完整 Agent Team 的组成

    由 OpenClawd 在任务分析后生成，传给 AgentTeam 执行。
    """

    team_id: str = Field(default="", description="团队 ID (空字符串时由引擎生成)")
    strategy: TeamStrategyEnum = Field(
        default=TeamStrategyEnum.SPECIALIZED,
        description="协作策略",
    )
    task: str = Field(..., min_length=1, description="原始任务描述")
    members: List[TeamMemberSchema] = Field(
        ..., min_length=1,
        description="团队成员列表 (至少 1 人)",
    )
    complexity_score: float = Field(
        default=0.5, ge=0, le=1,
        description="任务复杂度评分 — 影响团队规模和模型等级",
    )
    max_iterations: int = Field(
        default=8, ge=1, le=20,
        description="每个成员的 ReAct 循环最大迭代次数",
    )
    synthesis_provider: Optional[str] = Field(
        default=None,
        description="综合结果时使用的 LLM provider (默认用路由器选择)",
    )

    model_config = {"from_attributes": True}


class TeamMemberResultSchema(BaseModel):
    """单个成员执行结果"""

    member: TeamMemberSchema
    result: str = Field(default="")
    latency_ms: float = Field(default=0.0, ge=0)
    tokens: int = Field(default=0, ge=0)
    success: bool = Field(default=True)
    error: Optional[str] = Field(default=None)
    tool_calls_log: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="该成员的工具调用记录",
    )

    model_config = {"from_attributes": True}

    @classmethod
    def from_dataclass(cls, dc) -> "TeamMemberResultSchema":
        """从 agent_team.MemberResult dataclass 转换"""
        return cls(
            member=TeamMemberSchema.from_dataclass(dc.member),
            result=dc.result,
            latency_ms=dc.latency_ms,
            tokens=dc.tokens,
            success=dc.success,
            error=dc.error,
        )


class TeamResultSchema(BaseModel):
    """团队整体执行结果"""

    team_id: str = Field(...)
    strategy: str = Field(...)
    task: str = Field(...)
    member_results: List[TeamMemberResultSchema] = Field(default_factory=list)
    synthesized: str = Field(default="", description="综合后的最终回答")
    total_latency_ms: float = Field(default=0.0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    member_count: int = Field(default=0, ge=0)

    model_config = {"from_attributes": True}

    @classmethod
    def from_dataclass(cls, dc) -> "TeamResultSchema":
        """从 agent_team.TeamResult dataclass 转换"""
        return cls(
            team_id=dc.team_id,
            strategy=dc.strategy,
            task=dc.task,
            member_results=[TeamMemberResultSchema.from_dataclass(mr) for mr in dc.member_results],
            synthesized=dc.synthesized,
            total_latency_ms=dc.total_latency_ms,
            total_tokens=dc.total_tokens,
            member_count=len(dc.member_results),
        )


# ───────── Twin / Swarm (保持兼容) ─────────

class TwinCreateSchema(BaseModel):
    """Twin（双子协作）创建请求"""

    task: str = Field(..., min_length=1, description="协作任务描述")
    strategy: str = Field(default="SPECIALIZED", description="协作策略: SPECIALIZED / COMPETITIVE / CONSENSUS")
    member_count: int = Field(default=2, ge=2, le=10)
    providers: List[str] = Field(default_factory=list, description="每个成员的 LLM 提供商，为空则自动分配")

    model_config = {"from_attributes": True}


class SwarmCreateSchema(BaseModel):
    """Swarm（群体智能）创建请求"""

    task: str = Field(..., min_length=1, description="Swarm 任务描述")
    agent_count: int = Field(default=3, ge=1, le=50)
    template: str = Field(default="general", description="Agent 模板")

    model_config = {"from_attributes": True}
