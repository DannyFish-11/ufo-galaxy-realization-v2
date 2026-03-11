"""
core/agent — 统一智能体内核包

提供"对话/执行一体化"的统一智能体主干：
  kernel           — 统一入口：接收自然语言 → 判定意图 → 注入策略 → 执行/对话
  intent_router    — 聊天 vs 任务执行 判定
  policy_loader    — 加载 SOUL / AGENTS / USER 策略文件
  execution_planner— 基于意图组装执行计划（Agent / Team / Swarm）
  capability_registry — 统一注册 MCP / Skills / Gateway 能力
"""

from .kernel import AgentKernel, KernelResponse, get_kernel, handle_message

__all__ = [
    "AgentKernel",
    "KernelResponse",
    "get_kernel",
    "handle_message",
]
