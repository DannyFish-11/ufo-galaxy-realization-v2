"""
UFO Galaxy - 任务编排数据契约（Pydantic V2）
==============================================

定义 Orchestrator 的输入/输出数据模型，用于：
  - MasterBrain → Orchestrator 的任务下发
  - Orchestrator 内部的 DAG 表示
  - Orchestrator → AgentKernel 的子任务分发
  - 编排结果的统一返回

所有跨层调用必须使用这些模型，禁止 dict 裸奔。
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SubTaskStatus(str, Enum):
    """子任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class OrchestrationStatus(str, Enum):
    """编排整体状态"""
    PLANNING = "planning"
    EXECUTING = "executing"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class SubTask(BaseModel):
    """子任务 — DAG 中的一个节点。

    由 LLM 分解生成，包含任务描述、依赖关系和执行参数。
    """

    task_id: str = Field(
        default_factory=lambda: f"sub_{uuid.uuid4().hex[:8]}",
        description="子任务唯一 ID",
    )
    name: str = Field(..., min_length=1, description="子任务名称")
    description: str = Field(default="", description="子任务详细描述")
    depends_on: List[str] = Field(
        default_factory=list,
        description="依赖的子任务 ID 列表（这些任务完成后才能开始）",
    )
    device_type: str = Field(
        default="",
        description="目标设备类型（可选，空字符串表示不限）",
    )
    device_id: str = Field(
        default="",
        description="目标设备 ID（可选，空字符串表示自动选择）",
    )
    action: str = Field(
        default="",
        description="动作类型：execute / query / control / analyze",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="子任务参数",
    )
    timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description="子任务超时秒数",
    )
    # ── 运行时字段（执行后填充） ──
    status: SubTaskStatus = Field(
        default=SubTaskStatus.PENDING,
        description="子任务状态",
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="子任务执行结果",
    )
    error: str = Field(default="", description="错误信息（如果失败）")
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class TaskDecomposition(BaseModel):
    """任务分解结果 — LLM 输出的结构化分解。"""

    goal: str = Field(..., description="原始任务目标")
    subtasks: List[SubTask] = Field(
        default_factory=list,
        description="分解后的子任务列表",
    )
    reasoning: str = Field(
        default="",
        description="LLM 的分解推理过程",
    )


class OrchestrationRequest(BaseModel):
    """编排请求 — 从 MasterBrain 或 API 层发起。"""

    request_id: str = Field(
        default_factory=lambda: f"orch_{uuid.uuid4().hex[:12]}",
        description="编排请求唯一 ID",
    )
    task_description: str = Field(..., min_length=1, description="任务自然语言描述")
    user_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="用户上下文（会话信息、设备信息等）",
    )
    session_id: str = Field(default="", description="会话 ID")
    device_id: str = Field(default="", description="来源设备 ID")
    priority: str = Field(default="normal", description="优先级")
    timeout_seconds: float = Field(
        default=300.0,
        ge=10.0,
        le=3600.0,
        description="整体编排超时秒数",
    )


class OrchestrationResult(BaseModel):
    """编排结果 — 完整的编排执行报告。"""

    request_id: str = Field(..., description="对应的编排请求 ID")
    status: OrchestrationStatus = Field(
        default=OrchestrationStatus.PLANNING,
        description="编排状态",
    )
    goal: str = Field(default="", description="任务目标")
    subtasks: List[SubTask] = Field(
        default_factory=list,
        description="所有子任务及其执行结果",
    )
    summary: str = Field(default="", description="执行摘要")
    total_subtasks: int = Field(default=0, ge=0)
    completed_subtasks: int = Field(default=0, ge=0)
    failed_subtasks: int = Field(default=0, ge=0)
    total_time_ms: float = Field(default=0.0, ge=0)
    error: str = Field(default="", description="顶层错误（如果有）")
