#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Agent 操作 Pydantic 模型
======================================

定义 Agent 创建、任务下发、响应、Twin 和 Swarm 相关数据模型。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentCreateSchema(BaseModel):
    """Agent 创建请求模型。

    用于创建新的 AI Agent 实例。
    """

    name: str = Field(
        ...,
        min_length=1,
        description="Agent 名称",
    )
    template: str = Field(
        default="general",
        description="Agent 模板，如 general / coder / researcher",
    )
    provider: str = Field(
        default="openai",
        description="LLM 提供商，如 openai / anthropic / deepseek",
    )
    model: str = Field(
        default="gpt-4",
        description="LLM 模型名称",
    )
    system_prompt: str = Field(
        default="",
        description="系统提示词",
    )

    model_config = {"from_attributes": True}


class AgentTaskSchema(BaseModel):
    """Agent 任务请求模型。

    向已有 Agent 提交一个任务。
    """

    agent_id: str = Field(
        ...,
        description="目标 Agent ID",
    )
    task: str = Field(
        ...,
        min_length=1,
        description="任务描述",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="任务上下文信息",
    )
    priority: str = Field(
        default="normal",
        description="优先级：low / normal / high / critical",
    )

    model_config = {"from_attributes": True}


class AgentResponseSchema(BaseModel):
    """Agent 任务响应模型。

    Agent 完成任务后的返回结构。
    """

    agent_id: str = Field(
        ...,
        description="Agent ID",
    )
    task_id: str = Field(
        default="",
        description="任务唯一标识符",
    )
    response: str = Field(
        default="",
        description="Agent 生成的响应文本",
    )
    tokens_used: int = Field(
        default=0,
        ge=0,
        description="消耗的 token 数量",
    )
    latency_ms: float = Field(
        default=0.0,
        ge=0,
        description="响应延迟（毫秒）",
    )
    success: bool = Field(
        default=True,
        description="任务是否成功完成",
    )

    model_config = {"from_attributes": True}


class TwinCreateSchema(BaseModel):
    """Twin（双子协作）创建请求模型。

    创建两个或多个 Agent 以协作方式完成任务。
    """

    task: str = Field(
        ...,
        min_length=1,
        description="协作任务描述",
    )
    strategy: str = Field(
        default="SPECIALIZED",
        description="协作策略：SPECIALIZED / COMPETITIVE / CONSENSUS",
    )
    member_count: int = Field(
        default=2,
        ge=2,
        le=10,
        description="协作成员数量",
    )
    providers: List[str] = Field(
        default_factory=list,
        description="每个成员使用的 LLM 提供商列表，为空则自动分配",
    )

    model_config = {"from_attributes": True}


class SwarmCreateSchema(BaseModel):
    """Swarm（群体智能）创建请求模型。

    创建一组 Agent 组成的 Swarm 来并行处理任务。
    """

    task: str = Field(
        ...,
        min_length=1,
        description="Swarm 任务描述",
    )
    agent_count: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Swarm 中 Agent 数量",
    )
    template: str = Field(
        default="general",
        description="Agent 模板",
    )

    model_config = {"from_attributes": True}
