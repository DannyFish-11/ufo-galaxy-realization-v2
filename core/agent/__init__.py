"""
Galaxy - Unified Agent Kernel Package
======================================

核心模块:
  kernel            — 统一智能体内核，唯一决策入口
  intent_router     — 意图分类: chat_only / task_execute / hybrid
  policy_loader     — 策略加载器 (SOUL / AGENTS / USER)
  execution_planner — 任务执行计划生成器
  capability_registry — MCP / Skill / Gateway 统一能力注册表

使用方式:
    from core.agent.kernel import AgentKernel, get_kernel
    kernel = get_kernel()
    result = await kernel.process(message="...", session_id="...")
"""

from .kernel import AgentKernel, get_kernel, KernelResponse
from .intent_router import IntentRouter, IntentMode, RouterDecision
from .policy_loader import PolicyLoader, PolicySet
from .capability_registry import CapabilityRegistry, get_capability_registry
from .execution_planner import ExecutionPlanner, ExecutionPlan

__all__ = [
    "AgentKernel",
    "get_kernel",
    "KernelResponse",
    "IntentRouter",
    "IntentMode",
    "RouterDecision",
    "PolicyLoader",
    "PolicySet",
    "CapabilityRegistry",
    "get_capability_registry",
    "ExecutionPlanner",
    "ExecutionPlan",
]
