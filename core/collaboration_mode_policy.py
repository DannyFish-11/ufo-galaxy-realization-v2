"""
core/collaboration_mode_policy.py — 协作模式自动选择策略
=========================================================

借鉴 Octo 六模式，按"任务结构"自动选择多 Agent 协作模式，支持手动覆盖。

模式（对应 core.agent_team.TeamStrategy / schemas TeamStrategyEnum）：
  - solo        → 单 Agent（不组队，调用方处理；本策略只在需要组队时返回团队模式）
  - critic      → 质量敏感：做/审分离（本地小模型做，开源大模型审）
  - pipeline    → 多步顺序：A→B→C 流水线交接
  - specialized → 大而可拆：子任务分解，各匹配专家（Octo 的 Split）
  - swarm       → 创意择优：同题多方案，挑最好
  - parallel    → 多视角：同题多模型并行综合（Octo 的 Roundtable 近似）

决策优先级（高 → 低）：
  1. 显式覆盖（context["collaboration_mode"] 或 GALAXY_FORCE_COLLAB_MODE）
  2. 关键词信号（质量/多步/创意/分头）
  3. 复杂度兜底

设计原则：纯函数式、零外部 IO、输入按不可信处理（用户消息），便于单测。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.CollabMode")

# 合法团队模式（与 TeamStrategy 对齐）
VALID_TEAM_MODES = {"parallel", "specialized", "swarm", "critic", "pipeline"}

# 关键词 → 模式（按优先级顺序判定，命中即返回）
# 质量敏感 → critic（做/审分离）
_CRITIC_KW = [
    "审核",
    "审查",
    "review",
    "检查",
    "校对",
    "把关",
    "质量",
    "正确性",
    "找bug",
    "找 bug",
    "查错",
    "挑错",
    "fact check",
    "事实核查",
    "合同",
    "风险",
    "安全审计",
    "code review",
    "代码审查",
    "评审",
    "复核",
]
# 多步顺序 → pipeline（流水线）
_PIPELINE_KW = [
    "先",
    "再",
    "然后",
    "接着",
    "之后",
    "step by step",
    "逐步",
    "依次",
    "流水线",
    "pipeline",
    "调研后",
    "分析再",
    "先调研",
    "再写",
    "第一步",
    "第二步",
    "workflow",
    "工作流",
    "按顺序",
]
# 创意择优 → swarm
_SWARM_KW = [
    "创意",
    "命名",
    "取名",
    "起名",
    "起几个",
    "名字",
    "标题",
    "slogan",
    "口号",
    "文案",
    "brainstorm",
    "头脑风暴",
    "多个方案",
    "几个方案",
    "想几个",
    "选一个最好",
    "活动策划",
    "视觉概念",
    "naming",
]
# 大而可拆 → specialized（分头干）
_SPLIT_KW = [
    "分别",
    "各自",
    "多个公司",
    "多家",
    "拆成",
    "分头",
    "并行处理",
    "batch",
    "批量",
    "分模块",
    "几个部分",
    "分工",
]


def _norm_mode(mode: Optional[str]) -> Optional[str]:
    """标准化模式字符串；非法返回 None。"""
    if not mode:
        return None
    m = str(mode).strip().lower()
    return m if m in VALID_TEAM_MODES else None


def select_collaboration_mode(
    message: str,
    *,
    complexity_score: float = 0.5,
    intent: Any = None,
    has_tools: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """选择团队协作模式。

    Returns:
        {"mode": <str>, "reason": <str>, "source": "override"|"keyword"|"complexity"}
    """
    context = context or {}

    # ── 1. 显式覆盖 ──────────────────────────────────────────────────────
    override = _norm_mode(context.get("collaboration_mode")) or _norm_mode(os.environ.get("GALAXY_FORCE_COLLAB_MODE"))
    if override:
        return {"mode": override, "reason": f"显式指定模式={override}", "source": "override"}

    msg = (message or "").lower()

    def _hit(keywords) -> bool:
        return any(k.lower() in msg for k in keywords)

    # ── 2. 关键词信号（质量 > 多步 > 创意 > 分头）──────────────────────────
    if _hit(_CRITIC_KW):
        return {"mode": "critic", "reason": "质量敏感关键词 → 做/审分离", "source": "keyword"}
    if _hit(_PIPELINE_KW):
        return {"mode": "pipeline", "reason": "多步顺序关键词 → 流水线", "source": "keyword"}
    if _hit(_SWARM_KW):
        return {"mode": "swarm", "reason": "创意类关键词 → 竞选择优", "source": "keyword"}
    if _hit(_SPLIT_KW):
        return {"mode": "specialized", "reason": "大而可拆关键词 → 分头专家", "source": "keyword"}

    # ── 3. 意图覆写 ──────────────────────────────────────────────────────
    intent_name = getattr(intent, "intent", "") if intent is not None else ""
    if intent_name == "workflow":
        return {"mode": "pipeline", "reason": "意图=workflow → 流水线", "source": "keyword"}
    targets = getattr(intent, "targets", []) if intent is not None else []
    if targets and len(targets) > 5:
        return {"mode": "swarm", "reason": "目标>5 → 群体", "source": "keyword"}

    # ── 4. 复杂度兜底 ────────────────────────────────────────────────────
    if complexity_score >= 0.7:
        # 高复杂度默认走 critic：用大模型审小模型，兼顾质量与成本
        return {"mode": "critic", "reason": f"高复杂度({complexity_score:.2f}) → 做/审分离", "source": "complexity"}
    if complexity_score >= 0.4:
        return {"mode": "specialized", "reason": f"中复杂度({complexity_score:.2f}) → 分头专家", "source": "complexity"}
    return {"mode": "parallel", "reason": f"低复杂度({complexity_score:.2f}) → 多视角并行", "source": "complexity"}


# Sentinel
COLLABORATION_MODE_POLICY_SENTINEL: str = (
    "COLLABORATION_MODE_POLICY_V1: core/collaboration_mode_policy.py | "
    "Octo 六模式自动选择: critic/pipeline/swarm/specialized/parallel. "
    "优先级: 显式覆盖 > 关键词 > 意图 > 复杂度. select_collaboration_mode()."
)
