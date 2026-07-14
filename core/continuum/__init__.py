"""
core.continuum — State Continuum Protocol
==========================================

Defines the data structures, configuration, and engines for
OpenClawd's state continuum system.

Two-dimensional public model
------------------------------
The continuum exposes two public dimensions:

1. **Tri-state phase** (:class:`TriStatePhase`) — *what* the system is doing:

       silent   — native multimodal ingress, minimal footprint
       liminal  — intent forming; single-device ↔ cross-device bridge
       manifest — structure formed, action in progress

2. **Runtime domain** (:class:`RuntimeDomain`) — *where* execution runs:

       local        — confined to this single device / process
       cross_device — spanning multiple devices or remote nodes
       transition   — deciding between local and cross-device routing

Internal phase lifecycle (full continuum)
------------------------------------------
    formless → liminal → manifest → receding → formless

``receding`` is an internal return/rollback mechanism and is NOT a
public primary state.  Use :func:`continuum_to_tri_state` to project
any internal phase to its public tri-state equivalent.

Public surface:
  - TriStatePhase            (public enum — tri-state, first dimension)
  - RuntimeDomain            (public enum — local/cross_device, second dimension)
  - ContinuumPhase           (internal enum — four phases)
  - continuum_to_tri_state   (projection helper)
  - ActionLevel              (enum)
  - FormSignature            (enum)
  - SpatialPresence          (enum)
  - HumanFieldState          (Pydantic model)
  - UnifiedState             (Pydantic model)
  - ContinuumState           (Pydantic model; has .tri_state_phase and .runtime_domain)
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

from core.continuum.config import (
    DEFAULT_CONTINUUM_CONFIG,
    ContinuumConfig,
    DwellConfig,
    FeatureFlags,
    HysteresisConfig,
)
from core.continuum.decision_gate import DecisionGate
from core.continuum.expression_engine import ExpressionEngine
from core.continuum.human_field import HumanFieldInferrer, InteractionRhythm
from core.continuum.liminal_field import LiminalFieldEngine, LiminalMetrics
from core.continuum.metrics import ContinuumMetrics, get_continuum_metrics
from core.continuum.orchestrator import ContinuumOrchestrator
from core.continuum.return_engine import ReturnAction, ReturnEngine, ReturnResult, ReturnTrigger
from core.continuum.state_fusion import StateFusion
from core.continuum.temporal_engine import (
    DwellGuard,
    HysteresisGate,
    TemporalEngine,
    apply_decay,
    apply_ema,
    apply_rate_limit,
)
from core.continuum.types import (
    ActionLevel,
    ContinuumPhase,
    ContinuumState,
    DecisionState,
    ExpressionState,
    FormSignature,
    HumanFieldState,
    RuntimeDomain,
    SpatialPresence,
    TriStatePhase,
    UnifiedState,
    continuum_to_tri_state,
)

__all__ = [
    # Public tri-state (use for external APIs/docs)
    "TriStatePhase",
    "continuum_to_tri_state",
    # Public runtime domain (second dimension — local vs cross-device)
    "RuntimeDomain",
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
