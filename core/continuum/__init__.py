"""
core.continuum — State Continuum Protocol
==========================================

Defines the data structures, configuration, and engines for
OpenClawd's state continuum system.

Public-facing tri-state model
------------------------------
External APIs and documentation use :class:`TriStatePhase`:

    silent   — native multimodal ingress, minimal footprint
    liminal  — intent forming; single-device ↔ cross-device bridge
    manifest — structure formed, action in progress

Internal phase lifecycle (full continuum)
------------------------------------------
    formless → liminal → manifest → receding → formless

``receding`` is an internal return/rollback mechanism and is NOT a
public primary state.  Use :func:`continuum_to_tri_state` to project
any internal phase to its public tri-state equivalent.

Public surface:
  - TriStatePhase            (public enum — use for external APIs/docs)
  - ContinuumPhase           (internal enum — four phases)
  - continuum_to_tri_state   (projection helper)
  - ActionLevel              (enum)
  - FormSignature            (enum)
  - SpatialPresence          (enum)
  - HumanFieldState          (Pydantic model)
  - UnifiedState             (Pydantic model)
  - ContinuumState           (Pydantic model; has .tri_state_phase property)
  - DecisionState            (Pydantic model)
  - ExpressionState          (Pydantic model)
  - ContinuumConfig          (Pydantic model)
  - HysteresisConfig         (Pydantic model)
  - DwellConfig              (Pydantic model)
  - FeatureFlags             (Pydantic model)
  - TemporalEngine           (engine class)
  - HysteresisGate           (component class)
  - DwellGuard               (component class)
  - apply_ema                (signal helper)
  - apply_rate_limit         (signal helper)
  - apply_decay              (signal helper)
  - HumanFieldInferrer       (engine class)
  - InteractionRhythm        (data class)
  - StateFusion              (engine class)
  - LiminalFieldEngine       (engine class)
  - LiminalMetrics           (data class)
  - DecisionGate             (engine class)
  - ReturnEngine             (engine class)
  - ReturnTrigger            (enum)
  - ReturnAction             (enum)
  - ReturnResult             (data class)
  - ExpressionEngine         (engine class)
  - ContinuumOrchestrator    (orchestrator class)
  - ContinuumMetrics         (metrics class)
  - get_continuum_metrics    (singleton accessor)
"""

from core.continuum.types import (
    TriStatePhase,
    ContinuumPhase,
    continuum_to_tri_state,
    HumanFieldState,
    UnifiedState,
    ContinuumState,
    DecisionState,
    ExpressionState,
    ActionLevel,
    FormSignature,
    SpatialPresence,
)
from core.continuum.config import (
    ContinuumConfig,
    HysteresisConfig,
    DwellConfig,
    FeatureFlags,
    DEFAULT_CONTINUUM_CONFIG,
)
from core.continuum.temporal_engine import (
    TemporalEngine,
    HysteresisGate,
    DwellGuard,
    apply_ema,
    apply_rate_limit,
    apply_decay,
)
from core.continuum.human_field import HumanFieldInferrer, InteractionRhythm
from core.continuum.state_fusion import StateFusion
from core.continuum.liminal_field import LiminalFieldEngine, LiminalMetrics
from core.continuum.decision_gate import DecisionGate
from core.continuum.return_engine import ReturnEngine, ReturnTrigger, ReturnAction, ReturnResult
from core.continuum.expression_engine import ExpressionEngine
from core.continuum.orchestrator import ContinuumOrchestrator
from core.continuum.metrics import ContinuumMetrics, get_continuum_metrics

__all__ = [
    # Public tri-state (use for external APIs/docs)
    "TriStatePhase",
    "continuum_to_tri_state",
    # Internal enums
    "ContinuumPhase",
    "ActionLevel",
    "FormSignature",
    "SpatialPresence",
    # State models
    "HumanFieldState",
    "UnifiedState",
    "ContinuumState",
    "DecisionState",
    "ExpressionState",
    # Config models
    "ContinuumConfig",
    "HysteresisConfig",
    "DwellConfig",
    "FeatureFlags",
    "DEFAULT_CONTINUUM_CONFIG",
    # Temporal engine
    "TemporalEngine",
    "HysteresisGate",
    "DwellGuard",
    "apply_ema",
    "apply_rate_limit",
    "apply_decay",
    # Human field engine
    "HumanFieldInferrer",
    "InteractionRhythm",
    # State fusion
    "StateFusion",
    # Liminal field engine
    "LiminalFieldEngine",
    "LiminalMetrics",
    # Decision gate
    "DecisionGate",
    # Return engine
    "ReturnEngine",
    "ReturnTrigger",
    "ReturnAction",
    "ReturnResult",
    # Expression engine
    "ExpressionEngine",
    # Orchestrator
    "ContinuumOrchestrator",
    # Metrics / observability
    "ContinuumMetrics",
    "get_continuum_metrics",
]
