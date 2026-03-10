#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Routing Pydantic Models
======================================

Defines schemas for the intelligent routing layer:
- 5-dimension complexity scoring
- Model tier selection (LIGHT / MEDIUM / HEAVY / EXPERT)
- Provider health & circuit-breaker state
- Router response with full traceability
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ───────── 枚举 ─────────

class ModelTier(str, Enum):
    """模型等级 — 按复杂度区间选择"""
    LIGHT = "light"       # complexity 0.0 - 0.3
    MEDIUM = "medium"     # complexity 0.3 - 0.6
    HEAVY = "heavy"       # complexity 0.6 - 0.8
    EXPERT = "expert"     # complexity 0.8 - 1.0


class CircuitBreakerState(str, Enum):
    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断（请求阻断）
    HALF_OPEN = "half_open" # 探测恢复中


# ───────── 复杂度评估 ─────────

class ComplexityVector(BaseModel):
    """5 维复杂度向量 — 路由决策的核心依据"""

    context_length: float = Field(
        default=0.0, ge=0, le=1,
        description="上下文长度维度 (weight=0.15)，估算 token / 8000",
    )
    logic_depth: float = Field(
        default=0.0, ge=0, le=1,
        description="逻辑深度维度 (weight=0.25)，递归/条件/推导关键词命中",
    )
    domain_expertise: float = Field(
        default=0.0, ge=0, le=1,
        description="领域专业度 (weight=0.20)，编程/数学/专业术语命中",
    )
    precision_requirement: float = Field(
        default=0.0, ge=0, le=1,
        description="精度要求 (weight=0.20)，bug修复/严格验证关键词命中",
    )
    tool_needs: float = Field(
        default=0.0, ge=0, le=1,
        description="工具需求 (weight=0.20)，文件/搜索/执行关键词 + 是否有可用工具",
    )

    @property
    def weighted_score(self) -> float:
        return round(min(1.0, (
            0.15 * self.context_length
            + 0.25 * self.logic_depth
            + 0.20 * self.domain_expertise
            + 0.20 * self.precision_requirement
            + 0.20 * self.tool_needs
        )), 3)

    @property
    def tier(self) -> ModelTier:
        s = self.weighted_score
        if s < 0.3:
            return ModelTier.LIGHT
        elif s < 0.6:
            return ModelTier.MEDIUM
        elif s < 0.8:
            return ModelTier.HEAVY
        return ModelTier.EXPERT

    model_config = {"from_attributes": True}


# ───────── 路由请求 / 响应 ─────────

class RoutingRequestSchema(BaseModel):
    """路由请求 — 携带消息 + 可选 hint + 复杂度评分"""

    message: str = Field(
        ..., min_length=1,
        description="用户消息或 prompt",
    )
    task_type: str = Field(
        default="auto",
        description="任务分类 hint: auto / reasoning / coding / creative / analysis / planning / general",
    )
    preferred_provider: Optional[str] = Field(
        default=None,
        description="优选 LLM provider (openai / anthropic / deepseek 等)，健康时优先使用",
    )
    complexity_score: Optional[float] = Field(
        default=None, ge=0, le=1,
        description="预计算的复杂度分数 (0-1)，为 None 时由路由器自动计算",
    )
    tools: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="可用工具列表 (OpenAI function calling 格式)，影响复杂度评估",
    )

    model_config = {"from_attributes": True}


class RoutingDecisionSchema(BaseModel):
    """路由决策 — 包含完整 traceability"""

    provider: str = Field(..., description="选中的 LLM provider")
    model: str = Field(..., description="选中的模型 ID")
    reason: str = Field(default="", description="决策理由")
    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="备选 provider/model 列表",
    )
    estimated_cost: float = Field(default=0.0, ge=0, description="预估费用 (USD)")
    complexity_score: float = Field(default=0.5, ge=0, le=1, description="复杂度评分")
    model_tier: str = Field(default="medium", description="模型等级: light/medium/heavy/expert")
    task_type: str = Field(default="general", description="任务分类结果")

    model_config = {"from_attributes": True}

    @classmethod
    def from_dataclass(cls, dc) -> "RoutingDecisionSchema":
        """从 multi_llm_router.RoutingDecision dataclass 转换"""
        return cls(
            provider=dc.provider,
            model=dc.model,
            reason=dc.reason,
            alternatives=dc.alternatives,
        )


class RouterResponseSchema(BaseModel):
    """路由器完整响应 — 包含 LLM 回复 + 路由元数据"""

    content: str = Field(default="", description="LLM 生成的回复文本")
    provider: str = Field(default="", description="实际使用的 provider")
    model: str = Field(default="", description="实际使用的模型")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
    cost: float = Field(default=0.0, ge=0)
    complexity_score: float = Field(default=0.5, ge=0, le=1)
    model_tier: str = Field(default="medium")
    task_type: str = Field(default="general")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="LLM 返回的工具调用列表",
    )

    model_config = {"from_attributes": True}

    @classmethod
    def from_llm_response(cls, resp, complexity: float = 0.5, tier: str = "medium",
                          task_type: str = "general") -> "RouterResponseSchema":
        """从 multi_llm_router.LLMResponse dataclass 转换"""
        return cls(
            content=resp.content,
            provider=resp.provider,
            model=resp.model,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            latency_ms=resp.latency_ms,
            cost=resp.cost,
            tool_calls=resp.tool_calls,
            complexity_score=complexity,
            model_tier=tier,
            task_type=task_type,
        )


# ───────── Provider 健康状态 ─────────

class ProviderStatusSchema(BaseModel):
    """Provider 健康快照 — Dashboard 和路由引擎共用"""

    provider: str = Field(..., description="Provider 名称")
    status: str = Field(default="unknown", description="healthy / degraded / down / unknown")
    latency_avg_ms: float = Field(default=0.0, ge=0)
    error_rate: float = Field(default=0.0, ge=0, le=1)
    circuit_breaker_state: str = Field(
        default="closed",
        description="closed / open / half_open",
    )
    success_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)

    model_config = {"from_attributes": True}

    @classmethod
    def from_provider_config(cls, cfg) -> "ProviderStatusSchema":
        """从 multi_llm_router.ProviderConfig dataclass 转换"""
        total = cfg.success_count + cfg.error_count
        return cls(
            provider=cfg.name,
            status=cfg.status.value if hasattr(cfg.status, "value") else str(cfg.status),
            latency_avg_ms=cfg.latency_avg_ms,
            error_rate=cfg.error_count / total if total > 0 else 0.0,
            success_count=cfg.success_count,
            error_count=cfg.error_count,
        )
