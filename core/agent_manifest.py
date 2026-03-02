"""
AgentManifest — 可序列化的 Agent 部署包
=======================================

这是 Matrix OS Phase 1 的核心数据结构。

AgentManifest 是一个 Agent 的完整"灵魂"打包:
- 身份信息 (ID, 名称, 角色)
- 系统提示词 (决定 Agent 如何思考)
- 工具声明 (Agent 可以调用哪些能力)
- 任务队列 (Agent 需要执行的任务)
- 执行配置 (ReAct 最大轮次, 超时等)

Manifest 可以:
1. 序列化为 JSON → 通过 WebSocket 传输到端侧
2. 端侧反序列化 → 在 LocalAgentRuntime 中复活执行
3. 作为 Agent 迁移的最小单元
"""

import json
import time
import uuid
import hashlib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class ManifestVersion(str, Enum):
    V1 = "1.0"


class ExecutionMode(str, Enum):
    """执行模式"""
    REACT = "react"          # ReAct Loop (Thought → Action → Observation)
    SEQUENTIAL = "sequential"  # 顺序执行预定义动作列表
    AUTONOMOUS = "autonomous"  # 完全自主 (自行发现工具 + 决策)


class AgentPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ToolDeclaration:
    """工具声明 — Agent 被授权使用的工具"""
    name: str                          # 工具名 (e.g. "click", "screenshot", "open_app")
    description: str                   # 工具功能描述
    parameters: Dict[str, Any] = field(default_factory=dict)   # JSON Schema
    required_capability: str = ""      # 需要的设备能力 (e.g. "ui_automation")

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TaskItem:
    """任务项 — Agent 需要执行的具体任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    instruction: str = ""              # 自然语言指令
    action: str = ""                   # 具体动作 (可选, 用于 SEQUENTIAL 模式)
    params: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5                  # 1-10, 越高越优先
    depends_on: List[str] = field(default_factory=list)  # 依赖的任务 ID

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class AgentManifest:
    """
    Agent 部署清单 — 可序列化的 Agent 完整状态

    这是 Agent 在设备间迁移的最小传输单元。
    端侧收到 Manifest 后可以完全独立运行 Agent,
    无需再次请求服务端。
    """

    # ── 身份信息 ──
    manifest_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = "unnamed_agent"
    agent_role: str = "executor"       # coordinator / executor / analyst / planner
    description: str = ""

    # ── 思考引擎 ──
    system_prompt: str = ""            # Agent 的 "灵魂" — 决定它如何思考和行动
    execution_mode: str = "react"      # react / sequential / autonomous

    # ── 工具声明 ──
    tools: List[Dict] = field(default_factory=list)  # List[ToolDeclaration.to_dict()]

    # ── 任务队列 ──
    tasks: List[Dict] = field(default_factory=list)   # List[TaskItem.to_dict()]

    # ── 执行配置 ──
    max_react_turns: int = 10          # ReAct 最大推理轮次
    timeout_seconds: int = 300         # 总超时
    retry_on_error: bool = True        # 出错时是否重试
    max_retries: int = 2

    # ── 上下文 ──
    context: Dict[str, Any] = field(default_factory=dict)  # 任意附加上下文
    parent_manifest_id: Optional[str] = None  # 父 Manifest ID (用于分裂追踪)
    source_device: str = ""            # 来源设备 ID
    target_device: str = ""            # 目标设备 ID

    # ── 元数据 ──
    version: str = ManifestVersion.V1.value
    created_at: float = field(default_factory=time.time)
    priority: str = AgentPriority.NORMAL.value
    ttl_seconds: int = 3600            # 存活时间

    # ── MCP 工具发现 ──
    discover_local_tools: bool = True  # 是否在端侧自动发现 MCP 工具
    mcp_endpoint: str = ""             # 如果指定, 从此端点加载工具 Schema

    # ================================================================
    # 序列化 / 反序列化
    # ================================================================

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "manifest_id": self.manifest_id,
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "execution_mode": self.execution_mode,
            "tools": self.tools,
            "tasks": self.tasks,
            "max_react_turns": self.max_react_turns,
            "timeout_seconds": self.timeout_seconds,
            "retry_on_error": self.retry_on_error,
            "max_retries": self.max_retries,
            "context": self.context,
            "parent_manifest_id": self.parent_manifest_id,
            "source_device": self.source_device,
            "target_device": self.target_device,
            "version": self.version,
            "created_at": self.created_at,
            "priority": self.priority,
            "ttl_seconds": self.ttl_seconds,
            "discover_local_tools": self.discover_local_tools,
            "mcp_endpoint": self.mcp_endpoint,
        }

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def checksum(self) -> str:
        """计算 Manifest 校验和 (用于传输完整性验证)"""
        content = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentManifest":
        """从字典反序列化"""
        return cls(
            manifest_id=data.get("manifest_id", str(uuid.uuid4())),
            agent_name=data.get("agent_name", "unnamed_agent"),
            agent_role=data.get("agent_role", "executor"),
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            execution_mode=data.get("execution_mode", "react"),
            tools=data.get("tools", []),
            tasks=data.get("tasks", []),
            max_react_turns=data.get("max_react_turns", 10),
            timeout_seconds=data.get("timeout_seconds", 300),
            retry_on_error=data.get("retry_on_error", True),
            max_retries=data.get("max_retries", 2),
            context=data.get("context", {}),
            parent_manifest_id=data.get("parent_manifest_id"),
            source_device=data.get("source_device", ""),
            target_device=data.get("target_device", ""),
            version=data.get("version", ManifestVersion.V1.value),
            created_at=data.get("created_at", time.time()),
            priority=data.get("priority", AgentPriority.NORMAL.value),
            ttl_seconds=data.get("ttl_seconds", 3600),
            discover_local_tools=data.get("discover_local_tools", True),
            mcp_endpoint=data.get("mcp_endpoint", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AgentManifest":
        """从 JSON 字符串反序列化"""
        return cls.from_dict(json.loads(json_str))

    # ================================================================
    # 便捷工厂方法
    # ================================================================

    @classmethod
    def create_device_control_agent(
        cls,
        target_device: str,
        instruction: str,
        source_device: str = "server",
        tools: List[ToolDeclaration] = None,
    ) -> "AgentManifest":
        """快速创建设备控制 Agent"""
        default_tools = tools or [
            ToolDeclaration("open_app", "Open an application", {"app_name": {"type": "string"}}),
            ToolDeclaration("click", "Click at coordinates", {"x": {"type": "integer"}, "y": {"type": "integer"}}),
            ToolDeclaration("swipe", "Swipe gesture", {"x1": {"type": "integer"}, "y1": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}}),
            ToolDeclaration("type_text", "Type text", {"text": {"type": "string"}}),
            ToolDeclaration("screenshot", "Capture screenshot"),
            ToolDeclaration("key_event", "Send key event", {"key": {"type": "string"}}),
            ToolDeclaration("shell", "Execute shell command", {"command": {"type": "string"}}, "shell_access"),
        ]

        return cls(
            agent_name=f"device_control_{target_device}",
            agent_role="executor",
            description=f"Control device {target_device}: {instruction}",
            system_prompt=(
                f"You are a device control agent deployed on device '{target_device}'.\n"
                f"Your task: {instruction}\n\n"
                "RULES:\n"
                "1. Use the available tools to accomplish the task.\n"
                "2. After each action, observe the result before deciding next step.\n"
                "3. If a tool fails, try an alternative approach.\n"
                "4. Report completion status clearly.\n"
                "5. NEVER perform destructive actions without confirmation.\n"
            ),
            execution_mode=ExecutionMode.REACT.value,
            tools=[t.to_dict() for t in default_tools],
            tasks=[TaskItem(instruction=instruction).to_dict()],
            source_device=source_device,
            target_device=target_device,
            discover_local_tools=True,
            priority=AgentPriority.NORMAL.value,
        )

    @classmethod
    def create_multi_step_agent(
        cls,
        agent_name: str,
        steps: List[Dict[str, Any]],
        target_device: str = "",
    ) -> "AgentManifest":
        """创建多步骤顺序执行 Agent"""
        tasks = [
            TaskItem(
                instruction=step.get("instruction", ""),
                action=step.get("action", ""),
                params=step.get("params", {}),
                priority=step.get("priority", 5),
            ).to_dict()
            for step in steps
        ]

        return cls(
            agent_name=agent_name,
            agent_role="executor",
            description=f"Multi-step agent with {len(steps)} steps",
            system_prompt="Execute the following steps in order. Report each step's result.",
            execution_mode=ExecutionMode.SEQUENTIAL.value,
            tasks=tasks,
            target_device=target_device,
        )
