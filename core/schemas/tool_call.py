#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Tool Call & ReAct Loop Pydantic Models
=====================================================

定义 ReAct 循环中工具调用的结构化记录，用于：
- OpenClawd._react_loop 的 traceability
- Agent 执行日志
- Dashboard 展示
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolLayer(str, Enum):
    """工具所在层级"""
    MCP = "mcp"          # MCP Server 工具 → mcp__<server>__<tool>
    MCP_GW = "mcp_gw"   # MCP Gateway 自建工具 → mcp__gateway__<tool>
    SKILL = "skill"      # Skill 技能 → skill__<id>
    NODE = "node"        # Node 节点 → node__<id>__<action>


class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class ToolCallRecord(BaseModel):
    """单次工具调用记录"""

    tool_name: str = Field(..., description="完整工具名: mcp__server__tool / skill__id / node__id__action")
    layer: ToolLayer = Field(..., description="工具层级")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="调用参数")
    result: Any = Field(default=None, description="返回结果 (截断至 2000 字)")
    status: ToolCallStatus = Field(default=ToolCallStatus.SUCCESS)
    error: Optional[str] = Field(default=None, description="错误信息")
    latency_ms: float = Field(default=0.0, ge=0)
    iteration: int = Field(default=0, ge=0, description="所在 ReAct 迭代序号 (0-based)")

    model_config = {"from_attributes": True}

    @classmethod
    def classify_layer(cls, tool_name: str) -> ToolLayer:
        """根据工具名前缀判断层级"""
        if tool_name.startswith("mcp__gateway__"):
            return ToolLayer.MCP_GW
        elif tool_name.startswith("mcp__"):
            return ToolLayer.MCP
        elif tool_name.startswith("skill__"):
            return ToolLayer.SKILL
        elif tool_name.startswith("node__"):
            return ToolLayer.NODE
        return ToolLayer.MCP  # fallback


class ReactLoopResult(BaseModel):
    """ReAct 循环完整结果 — OpenClawd._react_loop 的返回契约"""

    response: str = Field(default="", description="最终 LLM 回复")
    tool_calls_log: List[ToolCallRecord] = Field(
        default_factory=list,
        description="按时序排列的所有工具调用记录",
    )
    iterations: int = Field(default=1, ge=1, description="实际迭代次数")
    provider: str = Field(default="", description="使用的 LLM provider")
    model: str = Field(default="", description="使用的模型")
    total_tokens: int = Field(default=0, ge=0)
    total_latency_ms: float = Field(default=0.0, ge=0)
    complexity_score: float = Field(default=0.5, ge=0, le=1)
    hit_max_iterations: bool = Field(default=False, description="是否触达最大迭代限制")

    model_config = {"from_attributes": True}

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls_log)

    @property
    def layers_used(self) -> List[str]:
        """返回本次循环涉及的工具层级"""
        return list(set(tc.layer.value for tc in self.tool_calls_log))
