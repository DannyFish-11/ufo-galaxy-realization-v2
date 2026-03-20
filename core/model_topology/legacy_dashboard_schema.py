"""
core/model_topology/legacy_dashboard_schema.py
================================================
Read-only mirror types for dashboard-era provider/router/node-API concepts.

PURPOSE
-------
This module captures the *shape* of the existing dashboard configuration
exactly as it is produced by ``dashboard/backend/main.py``.  It does NOT
import from the dashboard at runtime; instead it provides typed dataclasses
that the bridge can populate from either:

  a) a live ``/api/v1/llm/providers`` JSON response, or
  b) a static snapshot dict extracted from the dashboard backend source.

What is preserved
-----------------
- ``LegacyLLMProviderSnapshot``:  the per-provider record with provider /
  model / models / speed_score / quality_score / available / multimodal /
  missing_env_key.
- ``LegacyNodeAPIEntry``:  a node-API record from ``NODE_API_REQUIREMENTS``
  with node_id / name / category / keys / all_configured.
- ``LegacyProviderHealthDetail``:  the optional runtime health record that
  the dashboard exposes when a provider has been probed.
- ``LegacyRouterSemantics``:  a lightweight descriptor for the IntentRouter /
  ExecutionPlanner / AgentFactory conceptual roles present in
  ``dashboard/README.md``.

What is NOT preserved
---------------------
- Dashboard HTML/JS/TS front-end code – irrelevant to the bridge.
- FastAPI route handlers / session state – not imported or reproduced here.
- Any dashboard UI layout or form-factor – this bridge is headless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# LLM provider snapshot (mirrors dashboard backend llm_provider_defs output)
# ---------------------------------------------------------------------------


@dataclass
class LegacyLLMProviderSnapshot:
    """Typed mirror of one record returned by ``GET /api/v1/llm/providers``.

    Field names are kept *identical* to the dashboard API response so that
    the bridge can accept raw JSON dicts without name-mangling.
    """
    provider: str                  # e.g. "openai"
    model: str                     # default model ID
    models: List[str]              # all supported model IDs
    speed_score: int               # 1-10
    quality_score: int             # 1-10
    available: bool                # True if env key is present
    multimodal: bool = False
    missing_env_key: Optional[str] = None  # first required env-var if unavailable
    # Internal detail: all env vars the provider accepts (not always present
    # in the API response, but populated by the bridge from provider defs)
    env_keys: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LegacyLLMProviderSnapshot":
        """Construct from a raw dashboard-API dict, with safe defaults."""
        return cls(
            provider=data["provider"],
            model=data.get("model", ""),
            models=list(data.get("models") or []),
            speed_score=int(data.get("speed_score", 5)),
            quality_score=int(data.get("quality_score", 5)),
            available=bool(data.get("available", False)),
            multimodal=bool(data.get("multimodal", False)),
            missing_env_key=data.get("missing_env_key"),
            env_keys=list(data.get("env_keys") or []),
        )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "models": self.models,
            "speed_score": self.speed_score,
            "quality_score": self.quality_score,
            "available": self.available,
            "multimodal": self.multimodal,
        }
        if not self.available and self.missing_env_key:
            d["missing_env_key"] = self.missing_env_key
        if self.env_keys:
            d["env_keys"] = self.env_keys
        return d


# ---------------------------------------------------------------------------
# Node-API entry (mirrors NODE_API_REQUIREMENTS and /api/v1/config/node-apis)
# ---------------------------------------------------------------------------


@dataclass
class LegacyNodeAPIKeySpec:
    """One key requirement within a node-API entry."""
    env_var: str
    label: str
    configured: bool = False


@dataclass
class LegacyNodeAPIEntry:
    """Typed mirror of one record returned by ``GET /api/v1/config/node-apis``.

    Fields correspond 1-to-1 with the dashboard backend output.
    """
    node_id: str          # e.g. "01", "15", "79"
    name: str             # e.g. "OneAPI 聚合器"
    category: str         # e.g. "llm", "vision", "local_llm"
    keys: List[LegacyNodeAPIKeySpec] = field(default_factory=list)
    all_configured: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LegacyNodeAPIEntry":
        raw_keys = data.get("keys") or []
        keys = [
            LegacyNodeAPIKeySpec(
                env_var=k.get("env_var", ""),
                label=k.get("label", ""),
                configured=bool(k.get("configured", False)),
            )
            for k in raw_keys
        ]
        return cls(
            node_id=data["node_id"],
            name=data.get("name", ""),
            category=data.get("category", "unknown"),
            keys=keys,
            all_configured=bool(data.get("all_configured", False)),
        )


# ---------------------------------------------------------------------------
# Optional runtime health snapshot (mirrors ProviderHealthDetail in types.ts)
# ---------------------------------------------------------------------------


@dataclass
class LegacyProviderHealthDetail:
    """Optional runtime health snapshot for a provider.

    In the dashboard this is populated from circuit-breaker / telemetry state.
    The bridge accepts it as optional input; if absent it defaults to
    "unknown" health.
    """
    provider: str
    status: str = "unknown"       # "healthy" | "degraded" | "down" | "unknown"
    latency_avg_ms: float = 0.0
    error_rate: float = 0.0
    circuit_breaker_state: str = "closed"
    supports_tools: bool = False
    supports_json_mode: bool = False
    supports_vision: bool = False
    calls_count: int = 0
    tokens_used: int = 0
    total_cost: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LegacyProviderHealthDetail":
        return cls(
            provider=data["provider"],
            status=data.get("status", "unknown"),
            latency_avg_ms=float(data.get("latency_avg_ms", 0.0)),
            error_rate=float(data.get("error_rate", 0.0)),
            circuit_breaker_state=data.get("circuit_breaker_state", "closed"),
            supports_tools=bool(data.get("supports_tools", False)),
            supports_json_mode=bool(data.get("supports_json_mode", False)),
            supports_vision=bool(data.get("supports_vision", False)),
            calls_count=int(data.get("calls_count", 0)),
            tokens_used=int(data.get("tokens_used", 0)),
            total_cost=float(data.get("total_cost", 0.0)),
        )


# ---------------------------------------------------------------------------
# Dashboard-era router semantics descriptor
# ---------------------------------------------------------------------------


@dataclass
class LegacyRouterSemantics:
    """Captures the logical router/aggregator roles described in
    ``dashboard/README.md``:
      - IntentRouter: routes incoming intent to the right sub-agent/strategy
      - ExecutionPlanner: plans multi-step task execution
      - AgentFactory: dynamically creates agents from task intent
      - TwinModel: maintains digital-twin shadow state
      - Multi-LLM Router: selects provider/model at runtime

    This descriptor is used by ``ConfigBridge.extract_aggregator_hints()`` to
    generate ``AggregatorRouterHint`` objects for the normalized topology.
    """
    intent_router_providers: List[str] = field(default_factory=list)
    execution_planner_providers: List[str] = field(default_factory=list)
    agent_factory_providers: List[str] = field(default_factory=list)
    twin_model_providers: List[str] = field(default_factory=list)
    multi_llm_router_providers: List[str] = field(default_factory=list)
    memory_providers: List[str] = field(default_factory=list)
    cross_device_providers: List[str] = field(default_factory=list)
