#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Routing Pydantic Models
======================================

Defines schemas for the intelligent routing layer that selects the optimal
LLM provider / model for a given request, tracks provider health, and
exposes circuit-breaker state.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RoutingRequestSchema(BaseModel):
    """Incoming routing request.

    Describes a user message together with optional hints that the router
    can use to select the best provider and model.
    """

    message: str = Field(
        ...,
        min_length=1,
        description="The user message or prompt to be routed.",
    )
    task_type: str = Field(
        default="auto",
        description=(
            "Task classification hint. Use 'auto' to let the router "
            "decide. Other values: 'chat', 'code', 'analysis', "
            "'creative', 'translation'."
        ),
    )
    preferred_provider: Optional[str] = Field(
        default=None,
        description=(
            "Optional preferred LLM provider (e.g. 'openai', "
            "'anthropic', 'deepseek'). The router will honour this "
            "when the provider is healthy."
        ),
    )

    model_config = {"from_attributes": True}


class RoutingDecisionSchema(BaseModel):
    """Decision produced by the routing engine.

    Contains the selected provider / model, the reasoning behind the
    choice, alternative candidates, and an estimated cost.
    """

    provider: str = Field(
        ...,
        description="Selected LLM provider name.",
    )
    model: str = Field(
        ...,
        description="Selected model identifier.",
    )
    reason: str = Field(
        default="",
        description="Human-readable reason for the routing decision.",
    )
    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Ranked list of alternative provider/model combos. "
            "Each dict should contain at least 'provider' and 'model'."
        ),
    )
    estimated_cost: float = Field(
        default=0.0,
        ge=0,
        description="Estimated cost in USD for processing the request.",
    )

    model_config = {"from_attributes": True}


class ProviderStatusSchema(BaseModel):
    """Health and performance snapshot of an LLM provider.

    Used by the dashboard and the routing engine to evaluate provider
    fitness.
    """

    provider: str = Field(
        ...,
        description="Provider name (e.g. 'openai').",
    )
    status: str = Field(
        default="unknown",
        description="Current status: 'healthy', 'degraded', 'down', 'unknown'.",
    )
    latency_avg_ms: float = Field(
        default=0.0,
        ge=0,
        description="Average response latency in milliseconds.",
    )
    error_rate: float = Field(
        default=0.0,
        ge=0,
        le=1.0,
        description="Error rate as a fraction between 0 and 1.",
    )
    circuit_breaker_state: str = Field(
        default="closed",
        description=(
            "Circuit-breaker state: 'closed' (normal), 'open' "
            "(requests blocked), or 'half_open' (probe mode)."
        ),
    )

    model_config = {"from_attributes": True}
