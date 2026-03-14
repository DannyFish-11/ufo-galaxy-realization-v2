"""
Galaxy Control Plane package.

Provides the core scheduling, security, and audit infrastructure for the
Galaxy Control Plane (Supreme Directive V5.2 – Phase 1).

Public API
----------
audit_ledger
    Append-only event ledger with DAG serialisation helpers.
smart_scheduler
    Heuristic device scoring and selection engine.
security_interceptor
    Async HITL approval gate with per-task ACK tokens.
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

__all__ = [
    # audit_ledger
    "AuditLedger",
    "EventType",
    "LedgerSnapshot",
    "Severity",
    "TraceEvent",
    "events_to_dag",
    "events_to_json",
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
]
