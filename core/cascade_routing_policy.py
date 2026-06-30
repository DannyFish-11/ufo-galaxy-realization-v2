"""
core.cascade_routing_policy — 大小模型协作级联路由策略
=========================================================

实现设计目标：
  大小模型配合 — 简单任务用小/快模型，复杂任务用大/强模型
  本地原生多模态优先 — Ollama/HF local 始终是第一候选
  各种 API 多级兜底 — 根据复杂度选择合适的 API 层

路由层次（配合现有 MultiLLMRouter.TASK_ROUTING_PREFERENCES）：

  SIMPLE  → TaskType.FAST_RESPONSE   → API fallback: deepseek/groq/gemini-flash  (小模型)
  MEDIUM  → TaskType.GENERAL         → API fallback: openai/anthropic/deepseek     (中模型)
  COMPLEX → TaskType.REASONING/etc.  → API fallback: anthropic/openai/deepseek-r1  (大模型)

TaskType 映射利用现有 TASK_ROUTING_PREFERENCES 表，无需改动路由器内部逻辑。
OpenClawd 只需把分类结果传给 _react_loop(task_type=...) 即可触发正确的 API 优先级。

Agent 路由：
  SIMPLE  → single agent, FAST_RESPONSE model tier
  MEDIUM  → single agent, GENERAL model tier
  COMPLEX → team task (existing cv.weighted_score >= 0.6 logic unchanged)
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.CascadeRouting")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskComplexity(str, Enum):
    SIMPLE = "simple"    # 快速问答, 简单对话, 翻译
    MEDIUM = "medium"    # 代码辅助, 摘要, 结构化任务
    COMPLEX = "complex"  # 多步推理, 长上下文, Agent 编排


# TaskType 字符串 → 对应 MultiLLMRouter 中 TaskType 枚举值
# 使用字符串避免直接依赖枚举，兼容降级场景
COMPLEXITY_TO_TASK_TYPE: Dict[TaskComplexity, str] = {
    TaskComplexity.SIMPLE:  "fast_response",   # FAST_RESPONSE → deepseek/groq/gemini-flash
    TaskComplexity.MEDIUM:  "general",          # GENERAL → openai/anthropic/deepseek
    TaskComplexity.COMPLEX: "reasoning",        # REASONING → anthropic/openai/deepseek-r1
}

# 任务关键词 → 强制 task_type 覆盖（忽略复杂度）
KEYWORD_TASK_TYPE_MAP: List[Tuple[List[str], str]] = [
    (["写代码", "生成代码", "code", "写个函数", "debug", "fix bug", "implement",
      "python ", "javascript", "typescript", "```python", "def ", "class "], "coding"),
    (["分析", "analyze", "analysis", "深入分析", "详细分析", "evaluate", "compare",
      "对比", "评估", "数据分析"], "analysis"),
    (["规划", "plan", "计划", "roadmap", "步骤", "schedule", "strategy", "策略"], "planning"),
    (["创作", "写作", "creative", "故事", "story", "poem", "诗", "小说", "script"], "creative"),
    (["推理", "reasoning", "逻辑", "logic", "证明", "prove", "math", "数学",
      "why does", "explain why", "为什么"], "reasoning"),
    (["agent", "tool", "工具", "orchestrate", "协调", "多步", "multi-step",
      "workflow", "任务链"], "agent_control"),
]

# 简单任务关键词（降低复杂度分数）
_SIMPLE_SIGNALS: List[str] = [
    "什么是", "what is", "how to", "怎么", "hello", "你好", "hi", "help",
    "translate", "翻译", "list", "列出", "yes or no", "是否", "简单",
    "quick", "brief", "简要", "一句话", "define", "定义",
]

# 复杂任务关键词（提升复杂度分数）
_COMPLEX_SIGNALS: List[str] = [
    "分析", "analyze", "design", "设计", "implement", "实现", "debug", "调试",
    "architecture", "架构", "optimize", "优化", "explain in detail", "详细解释",
    "comprehensive", "全面", "step by step", "一步步", "compared to", "对比",
    "research", "研究", "generate", "build", "创建", "系统", "system",
    "integrate", "集成", "end to end", "端到端", "多个", "several steps",
]


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def classify_task_complexity(
    message: str,
    *,
    has_tools: bool = False,
    is_agent_task: bool = False,
    history_len: int = 0,
    task_type_hint: Optional[str] = None,
) -> TaskComplexity:
    """
    Classify task complexity based on message content and context signals.

    Returns TaskComplexity.SIMPLE / MEDIUM / COMPLEX.
    Inputs should be treated as untrusted (user messages); no eval/exec.
    """
    # Agent tasks with tools are always complex
    if is_agent_task and has_tools:
        return TaskComplexity.COMPLEX

    msg_lower = message.lower()
    msg_len = len(message)
    score = 0

    # --- Length signals ---
    if msg_len > 1200:
        score += 3
    elif msg_len > 500:
        score += 2
    elif msg_len > 200:
        score += 1
    elif msg_len < 80:
        score -= 1

    # --- Keyword signals ---
    for kw in _COMPLEX_SIGNALS:
        if kw in msg_lower:
            score += 1

    for kw in _SIMPLE_SIGNALS:
        if kw in msg_lower:
            score -= 1

    # --- Context signals ---
    if has_tools:
        score += 1
    if is_agent_task:
        score += 2
    if history_len > 8:
        score += 1

    # --- Task type override (strong signal) ---
    if task_type_hint in ("reasoning", "agent_control", "planning", "analysis"):
        score += 2
    elif task_type_hint == "fast_response":
        score -= 2

    # --- Decision ---
    if score >= 4:
        return TaskComplexity.COMPLEX
    elif score >= 1:
        return TaskComplexity.MEDIUM
    else:
        return TaskComplexity.SIMPLE


def infer_task_type(message: str, complexity: TaskComplexity) -> str:
    """
    Infer the best TaskType string for routing, combining keyword detection
    and complexity-based mapping.

    Priority: keyword match > complexity-based default.
    """
    msg_lower = message.lower()

    for keywords, task_type in KEYWORD_TASK_TYPE_MAP:
        if any(kw in msg_lower for kw in keywords):
            return task_type

    return COMPLEXITY_TO_TASK_TYPE[complexity]


# ---------------------------------------------------------------------------
# CascadeRoutingPolicy — singleton
# ---------------------------------------------------------------------------

class CascadeRoutingPolicy:
    """
    Stateless policy object. Call get_routing_hint() per request.

    Returns a routing hint dict consumed by OpenClawd to:
      1. Select the TaskType passed to _react_loop / chat_with_tools
      2. Calibrate complexity_score for within-provider model size selection
      3. Annotate response metadata (panel visibility)
    """

    def get_routing_hint(
        self,
        message: str,
        *,
        has_tools: bool = False,
        is_agent_task: bool = False,
        history_len: int = 0,
        task_type_hint: Optional[str] = None,
    ) -> Dict:
        """
        Returns:
          complexity      : str ("simple" | "medium" | "complex")
          task_type       : str  → pass to chat_with_tools(task_type=...)
          complexity_score: float 0.0-1.0 → pass to router for model-size selection
          model_tier_label: str  ("小模型" | "中模型" | "大模型") for panel display
        """
        complexity = classify_task_complexity(
            message,
            has_tools=has_tools,
            is_agent_task=is_agent_task,
            history_len=history_len,
            task_type_hint=task_type_hint,
        )
        task_type = infer_task_type(message, complexity)

        # Map complexity → complexity_score for select_model_by_complexity()
        # SIMPLE: 0.2 (light model), MEDIUM: 0.5 (balanced), COMPLEX: 0.85 (heavy model)
        score_map = {
            TaskComplexity.SIMPLE:  0.2,
            TaskComplexity.MEDIUM:  0.5,
            TaskComplexity.COMPLEX: 0.85,
        }
        tier_label = {
            TaskComplexity.SIMPLE:  "小模型/快速",
            TaskComplexity.MEDIUM:  "中模型/均衡",
            TaskComplexity.COMPLEX: "大模型/强推理",
        }

        hint = {
            "complexity": complexity.value,
            "task_type": task_type,
            "complexity_score": score_map[complexity],
            "model_tier_label": tier_label[complexity],
        }
        logger.debug(
            "CascadeRouting: complexity=%s task_type=%s score=%.2f",
            complexity.value, task_type, score_map[complexity],
        )
        return hint


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_policy: Optional[CascadeRoutingPolicy] = None


def get_cascade_policy() -> CascadeRoutingPolicy:
    global _policy
    if _policy is None:
        _policy = CascadeRoutingPolicy()
    return _policy


# Sentinel for grep / code navigation
CASCADE_ROUTING_POLICY_SENTINEL: str = (
    "CASCADE_ROUTING_POLICY_V1: core/cascade_routing_policy.py | "
    "大小模型协作: SIMPLE→fast_response(小), MEDIUM→general(中), COMPLEX→reasoning(大). "
    "Keyword-first task type detection, complexity_score calibrates within-provider model size. "
    "Integrates with MultiLLMRouter.TASK_ROUTING_PREFERENCES and select_model_by_complexity()."
)
