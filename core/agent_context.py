"""
UFO Galaxy - Agent 上下文管理
============================

基于 Vercel 研究：被动上下文比主动调用更可靠。

功能：
1. 自动加载 AGENTS.md 作为上下文
2. 每轮对话自动提供系统知识
3. 消除 Agent 决策负担

使用方法：
    from core.agent_context import get_agent_context
    
    context = get_agent_context()
    # context 包含 AGENTS.md 的内容
"""

import os
from pathlib import Path
from typing import Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# AGENTS.md 路径
AGENTS_MD_PATH = PROJECT_ROOT / "AGENTS.md"

# 缓存
_cached_context: Optional[str] = None


def get_agent_context() -> str:
    """
    获取 Agent 上下文
    
    返回 AGENTS.md 的内容，作为每轮对话的上下文
    """
    global _cached_context
    
    if _cached_context is not None:
        return _cached_context
    
    if AGENTS_MD_PATH.exists():
        with open(AGENTS_MD_PATH, "r", encoding="utf-8") as f:
            _cached_context = f.read()
        return _cached_context
    
    return ""


def get_system_prompt() -> str:
    """
    获取系统提示词
    
    包含 AGENTS.md 内容，用于初始化对话
    """
    context = get_agent_context()
    
    return f"""你是 UFO Galaxy 的 AI 助手。

以下是系统的知识索引，请参考这些信息来回答问题和执行任务：

{context}

---
请根据以上信息来理解系统架构和执行操作。"""


def refresh_context():
    """刷新上下文缓存"""
    global _cached_context
    _cached_context = None
    return get_agent_context()


def get_context_size() -> int:
    """获取上下文大小（字节）"""
    return len(get_agent_context())


# 导出
__all__ = [
    "get_agent_context",
    "get_system_prompt",
    "refresh_context",
    "get_context_size",
]
