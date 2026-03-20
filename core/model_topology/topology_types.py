"""
core/model_topology/topology_types.py
=======================================
Canonical type definitions for the V2 Model Topology Bridge layer.

These types are deliberately additive and repository-aligned.  They do NOT
replace the existing dashboard UI or the live routing/LLM-manager stack; they
define the *normalized schema* that the bridge layer produces so that later V2
PRs (topology core, routing policy, projection surface) can consume a stable,
well-typed contract.

Hierarchy:
  ProviderCategory        – source classification (direct / oneapi / tools / …)
  TopologyRole            – future-role hint per model/provider
  AggregatorKind          – named aggregator/router semantics preserved from
                            the dashboard-era IntentRouter / ExecutionPlanner
  ProviderIdentity        – (provider_id, display_name)
  ModelIdentity           – (model_id, provider_id, alternatives)
  ModalityCapability      – multimodal flags
  ScoringProfile          – speed / quality scores (1-10)
  AvailabilityStatus      – env-key gating and live availability
  NormalizedTopologyEntry – single fully-normalized provider+model record
  AggregatorRouterHint    – extracted router/aggregator semantic annotation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProviderCategory(str, Enum):
    """Source/category classification for a provider, mirroring dashboard-era
    categories (``direct_models``, ``oneapi``, ``tools``) and adding new ones
    needed for topology reasoning.
    """
    DIRECT = "direct_models"    # API key → provider's own endpoint
    ONEAPI = "oneapi"           # Routed through a OneAPI aggregator node
    TOOLS = "tools"             # Tool/service nodes (OCR, search, DB, …)
    NODE_BACKED = "node_backed" # Galaxy node that wraps an LLM service
    LOCAL = "local"             # Locally-running model (Ollama, vLLM, …)
    REMOTE = "remote"           # Remote/third-party endpoint not in the above
    UNKNOWN = "unknown"         # Fallback when category cannot be determined


class TopologyRole(str, Enum):
    """Future-role hint describing the *intended topological position* of a
    provider/model in the V2 supply graph.  These are hints only; the runtime
    routing layer will weight them against live telemetry and tri-state phase.
    """
    MULTIMODAL_CORE = "multimodal_core"   # Preferred primary supply; native multi-modal
    REASONING = "reasoning"               # Slow, deep-reasoning tasks
    EXECUTION = "execution"               # Fast, action-oriented tasks
    MEMORY = "memory"                     # Context compression / long-term memory
    ROUTING = "routing"                   # Meta-routing / arbiter models
    CROSS_DEVICE = "cross_device"         # Cross-device coordination
    GENERAL = "general"                   # No strong role preference
    UNKNOWN = "unknown"


class AggregatorKind(str, Enum):
    """Named aggregator/router semantic hints derived from the dashboard-era
    IntentRouter / ExecutionPlanner / AgentFactory architecture.

    These are *not* tied to the old dashboard UI; they represent logical roles
    that can be mapped onto the new routing graph in later PRs.
    """
    MULTIMODAL_CORE_AGGREGATOR = "multimodal_core_aggregator"
    REASONING_AGGREGATOR = "reasoning_aggregator"
    EXECUTION_AGGREGATOR = "execution_aggregator"
    MEMORY_AGGREGATOR = "memory_aggregator"
    ROUTE_ARBITER = "route_arbiter"
    CROSS_DEVICE_AGGREGATOR = "cross_device_aggregator"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderIdentity:
    """Immutable identity record for a single LLM provider."""
    provider_id: str
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id must not be empty")


@dataclass(frozen=True)
class ModelIdentity:
    """Immutable identity record for a single model within a provider."""
    model_id: str
    provider_id: str
    alternatives: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("model_id must not be empty")
        if not self.provider_id:
            raise ValueError("provider_id must not be empty")


@dataclass(frozen=True)
class ModalityCapability:
    """Describes the multimodal capabilities of a model/provider."""
    native_multimodal: bool = False   # True ↔ provider natively handles images/audio/video
    supports_vision: bool = False
    supports_audio: bool = False
    supports_video: bool = False

    @classmethod
    def from_multimodal_flag(cls, multimodal: bool) -> "ModalityCapability":
        """Construct from the simple boolean used in dashboard-era definitions.
        When the dashboard marks a provider as multimodal, vision is implied.
        """
        return cls(
            native_multimodal=multimodal,
            supports_vision=multimodal,
            supports_audio=False,
            supports_video=False,
        )


@dataclass(frozen=True)
class ScoringProfile:
    """Speed/quality scoring profile (1–10 scale, matching dashboard semantics)."""
    speed_score: int = 5
    quality_score: int = 5

    def __post_init__(self) -> None:
        for name, val in (("speed_score", self.speed_score), ("quality_score", self.quality_score)):
            if not (1 <= val <= 10):
                raise ValueError(f"{name} must be between 1 and 10, got {val}")

    @property
    def composite_score(self) -> float:
        """Simple composite (equal weight) for quick tier sorting."""
        return (self.speed_score + self.quality_score) / 2.0


@dataclass(frozen=True)
class AvailabilityStatus:
    """Captures whether a provider is currently usable and, if not, why."""
    available: bool = False
    missing_env_key: Optional[str] = None   # First required env-var if unavailable
    all_env_keys: List[str] = field(default_factory=list)  # All required env-vars

    @classmethod
    def from_dashboard_entry(
        cls,
        available: bool,
        missing_env_key: Optional[str],
        env_keys: Optional[List[str]] = None,
    ) -> "AvailabilityStatus":
        return cls(
            available=available,
            missing_env_key=None if available else missing_env_key,
            all_env_keys=list(env_keys or ([] if missing_env_key is None else [missing_env_key])),
        )


# ---------------------------------------------------------------------------
# Normalized topology entry  (main output of the bridge)
# ---------------------------------------------------------------------------


@dataclass
class NormalizedTopologyEntry:
    """Single fully-normalized record representing one provider+model slot in
    the topology supply graph.

    This is the canonical output type of ``ConfigBridge``; downstream V2 PRs
    (topology core, routing policy, projection surface) consume this type.
    """
    provider: ProviderIdentity
    model: ModelIdentity
    modality: ModalityCapability
    scoring: ScoringProfile
    availability: AvailabilityStatus
    category: ProviderCategory = ProviderCategory.UNKNOWN
    role_hints: List[TopologyRole] = field(default_factory=list)
    # Raw metadata preserved for forward-compatibility / debugging
    raw_metadata: dict = field(default_factory=dict)

    @property
    def is_multimodal_native(self) -> bool:
        return self.modality.native_multimodal

    @property
    def is_available(self) -> bool:
        return self.availability.available

    def __repr__(self) -> str:
        avail = "✓" if self.is_available else "✗"
        mm = "MM" if self.is_multimodal_native else "--"
        return (
            f"<TopologyEntry {self.provider.provider_id}/{self.model.model_id} "
            f"cat={self.category.value} {mm} {avail} "
            f"S={self.scoring.speed_score} Q={self.scoring.quality_score}>"
        )


# ---------------------------------------------------------------------------
# Aggregator / router hint
# ---------------------------------------------------------------------------


@dataclass
class AggregatorRouterHint:
    """An extracted aggregator/router semantic annotation.

    Represents a named logical role (e.g. "multimodal_core_aggregator") and
    the set of topology entries that should be associated with it.  These are
    *not* wired into runtime routing yet; they give the topology core PR a
    stable, representable concept to build on.
    """
    kind: AggregatorKind
    label: str
    candidate_provider_ids: List[str] = field(default_factory=list)
    notes: str = ""

    def __repr__(self) -> str:
        return (
            f"<AggregatorHint kind={self.kind.value} "
            f"candidates={self.candidate_provider_ids}>"
        )
