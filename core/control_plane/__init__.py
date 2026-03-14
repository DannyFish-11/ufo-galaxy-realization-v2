"""
Galaxy Control Plane package.

Provides the core scheduling, security, and audit infrastructure for the
Galaxy Control Plane (Supreme Directive V5.2 – Phase 1-4).

Public API
----------
audit_ledger
    Append-only event ledger with DAG serialisation helpers.
smart_scheduler
    Heuristic device scoring and selection engine.
security_interceptor
    Async HITL approval gate with per-task ACK tokens.
swarm_scaler
    Dynamic worker scaler for Swarm-mode Agent teams (Phase 4).
"""

from core.control_plane.audit_ledger import (
    AuditLedger,
    EventType,
    LedgerSnapshot,
    Severity,
    TraceEvent,
    events_to_dag,
    events_to_json,
)
from core.control_plane.swarm_manifest import SwarmAgentManifest
from core.control_plane.smart_scheduler import (
    CapabilityDescriptor,
    DeviceScore,
    DeviceScoreInput,
    DeviceScoringEngine,
    DeviceStatus,
    SandboxLevel,
    ScoringWeights,
)
from core.control_plane.security_interceptor import (
    ApprovalAuditEntry,
    ApprovalDeniedError,
    ApprovalRegistry,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalTimeoutError,
    RiskLevel,
    SecurityInterceptor,
)
from core.control_plane.swarm_scaler import (
    ScalingAction,
    ScalingPolicy,
    SwarmScaler,
)
from core.control_plane._globals import (
    get_audit_ledger,
    get_approval_registry,
    get_scoring_engine,
    get_security_interceptor,
)

__all__ = [
    # audit_ledger
    "AuditLedger",
    "EventType",
    "LedgerSnapshot",
    "Severity",
    "TraceEvent",
    "events_to_dag",
    "events_to_json",
    # swarm_manifest
    "SwarmAgentManifest",
    # smart_scheduler
    "CapabilityDescriptor",
    "DeviceScore",
    "DeviceScoreInput",
    "DeviceScoringEngine",
    "DeviceStatus",
    "SandboxLevel",
    "ScoringWeights",
    # security_interceptor
    "ApprovalAuditEntry",
    "ApprovalDeniedError",
    "ApprovalRegistry",
    "ApprovalRequest",
    "ApprovalStatus",
    "ApprovalTimeoutError",
    "RiskLevel",
    "SecurityInterceptor",
    # swarm_scaler (Phase 4)
    "ScalingAction",
    "ScalingPolicy",
    "SwarmScaler",
    # _globals
    "get_audit_ledger",
    "get_approval_registry",
    "get_scoring_engine",
    "get_security_interceptor",
]
