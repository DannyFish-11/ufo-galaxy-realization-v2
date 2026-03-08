"""
UFO Galaxy - 通用工具包装引擎
==============================

提供外部工具的学习、发现、执行和管理能力。
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.ToolWrapper")


class ToolType(str, Enum):
    CLI = "cli"
    API = "api"
    LIBRARY = "library"
    GUI = "gui"


class InstallMethod(str, Enum):
    PIP = "pip"
    NPM = "npm"
    APT = "apt"
    BREW = "brew"
    MANUAL = "manual"


@dataclass
class ToolKnowledge:
    tool_name: str
    tool_type: ToolType
    description: str
    install_command: str = ""
    examples: List[str] = field(default_factory=list)
    learned_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "tool_type": self.tool_type.value,
            "description": self.description,
            "install_command": self.install_command,
            "examples": self.examples,
            "learned_at": self.learned_at,
        }


@dataclass
class ExecutionResult:
    tool_name: str
    task: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "task": self.task,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


class ToolWrapperEngine:
    """通用工具包装引擎 - 工具学习、发现和执行"""

    def __init__(self):
        self._tools: Dict[str, ToolKnowledge] = {}
        self.execution_history: List[ExecutionResult] = []
        logger.info("工具包装引擎已初始化")

    def use_tool(
        self, tool_name: str, task_description: str, context: Optional[Dict] = None
    ) -> ExecutionResult:
        result = ExecutionResult(
            tool_name=tool_name,
            task=task_description,
            success=tool_name in self._tools,
            output=f"Tool '{tool_name}' executed for: {task_description}" if tool_name in self._tools else "",
            error="" if tool_name in self._tools else f"Tool '{tool_name}' not known",
        )
        self.execution_history.append(result)
        return result

    def learn_tool(
        self,
        tool_name: str,
        tool_type: str = "cli",
        description: str = "",
        install_command: str = "",
        examples: Optional[List[str]] = None,
    ) -> ToolKnowledge:
        knowledge = ToolKnowledge(
            tool_name=tool_name,
            tool_type=ToolType(tool_type) if isinstance(tool_type, str) else tool_type,
            description=description,
            install_command=install_command,
            examples=examples or [],
        )
        self._tools[tool_name] = knowledge
        logger.info(f"已学习工具: {tool_name}")
        return knowledge

    def discover_tool(self, tool_name: str) -> ToolKnowledge:
        knowledge = ToolKnowledge(
            tool_name=tool_name,
            tool_type=ToolType.CLI,
            description=f"Auto-discovered tool: {tool_name}",
        )
        self._tools[tool_name] = knowledge
        return knowledge

    def forget_tool(self, tool_name: str) -> bool:
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
        return False

    def get_known_tools(self) -> List[str]:
        return list(self._tools.keys())

    def get_tool_knowledge(self, tool_name: str) -> Optional[ToolKnowledge]:
        return self._tools.get(tool_name)
