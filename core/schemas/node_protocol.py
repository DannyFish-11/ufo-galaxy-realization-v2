"""
节点-网关统一标准协议 (Node Protocol)
=======================================

定义所有节点与 Agent/Gateway 通信的标准请求/响应格式，
以及节点向 Agent 系统注册工具的标准 ToolDefinition。

设计原则:
  - 向后兼容: 旧格式节点响应自动适配为 NodeResponse
  - 统一工具注册: 多来源统一为 ToolDefinition
  - Agent 友好: ToolDefinition 直接映射 LLM function calling 格式
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NodeRequest(BaseModel):
    """标准节点请求

    所有 Agent/Gateway → Node 的调用应使用此格式。
    """
    action: str = Field(..., description="执行动作名称")
    params: Dict[str, Any] = Field(default_factory=dict, description="动作参数")
    request_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:12],
        description="请求唯一 ID，用于跟踪和关联响应",
    )
    timeout: float = Field(default=30.0, description="请求超时(秒)")
    caller: str = Field(
        default="gateway",
        description="调用者标识: gateway / agent / scheduler / node",
    )


class NodeResponse(BaseModel):
    """标准节点响应

    所有 Node → Agent/Gateway 的返回应使用此格式。
    对于旧格式节点，由 unified_node_gateway 适配层自动包装。
    """
    success: bool = Field(..., description="是否执行成功")
    data: Optional[Any] = Field(default=None, description="成功时的返回数据")
    error: Optional[str] = Field(default=None, description="失败时的错误信息")
    error_code: Optional[str] = Field(
        default=None,
        description="标准错误码: TIMEOUT / NOT_FOUND / INTERNAL / UNAVAILABLE / INVALID_PARAMS",
    )
    request_id: str = Field(default="", description="回传请求 ID")
    node_id: str = Field(default="", description="响应节点 ID")
    latency_ms: float = Field(default=0.0, description="执行耗时(毫秒)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

    @classmethod
    def from_raw(cls, node_id: str, raw: Any, request_id: str = "",
                 latency_ms: float = 0.0) -> "NodeResponse":
        """从旧格式节点原始响应自动适配为标准 NodeResponse

        支持的旧格式:
          - {"success": True/False, "data": ..., "error": ...}
          - {"success": True/False, "result": ...}
          - 裸数据（字符串/字典/列表等）→ 包装为 {success: True, data: raw}
        """
        if isinstance(raw, dict):
            return cls(
                success=raw.get("success", True),
                data=raw.get("data", raw.get("result", raw)),
                error=raw.get("error"),
                error_code=raw.get("error_code"),
                request_id=request_id,
                node_id=node_id,
                latency_ms=latency_ms,
                metadata=raw.get("metadata", {}),
            )
        # 裸数据
        return cls(
            success=True,
            data=raw,
            request_id=request_id,
            node_id=node_id,
            latency_ms=latency_ms,
        )


class NodeHealthResponse(BaseModel):
    """标准健康检查响应"""
    status: str = Field(..., description="healthy / degraded / unhealthy")
    node_id: str = Field(default="", description="节点 ID")
    version: str = Field(default="1.0.0", description="节点版本")
    capabilities: List[str] = Field(default_factory=list, description="节点能力列表")
    uptime_seconds: float = Field(default=0.0, description="运行时间(秒)")
    load: float = Field(default=0.0, description="负载 0.0-1.0")

    @classmethod
    def from_raw(cls, node_id: str, raw: Any) -> "NodeHealthResponse":
        """从旧格式健康响应适配"""
        if isinstance(raw, dict):
            status = raw.get("status", "healthy")
            if isinstance(status, bool):
                status = "healthy" if status else "unhealthy"
            return cls(
                status=status,
                node_id=node_id,
                version=raw.get("version", "1.0.0"),
                capabilities=raw.get("capabilities", []),
                uptime_seconds=raw.get("uptime_seconds", raw.get("uptime", 0.0)),
                load=raw.get("load", 0.0),
            )
        return cls(status="healthy" if raw else "unhealthy", node_id=node_id)


class ToolDefinition(BaseModel):
    """标准工具定义 — 供 Agent/Scheduler 的 LLM function calling 使用

    统一 4 种工具来源:
      - nodes/*/config.json
      - nodes/*/main.py docstring (自动推断)
      - MCP 工具 (mcp_loader)
      - OpenClawd._CORE_NODE_ACTIONS (硬编码)
    """
    name: str = Field(..., description="唯一工具名: call_Node_XX_action")
    description: str = Field(..., description="自然语言描述（供 LLM 理解）")
    node_id: str = Field(default="", description="所属节点 ID")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="参数 JSON Schema 格式",
    )
    returns: Dict[str, Any] = Field(
        default_factory=dict,
        description="返回值 JSON Schema 格式",
    )
    version: str = Field(default="1.0.0", description="语义版本号")
    category: str = Field(default="general", description="工具分类")
    requires_device: bool = Field(
        default=False,
        description="是否需要设备上下文（device_id）",
    )
    source: str = Field(
        default="config",
        description="来源: config / docstring / mcp / hardcoded",
    )

    def to_openai_tool(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "执行动作"},
                        "params": {"type": "object", "description": "动作参数"},
                    },
                },
            },
        }
