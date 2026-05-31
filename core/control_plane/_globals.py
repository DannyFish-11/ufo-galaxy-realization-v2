"""
Galaxy Control Plane — Global Singletons
=========================================

Process-level singletons for the three Control Plane pillars.  Import from
here whenever you need the shared instances so every component operates on
the same ledger / registry / engine.

Usage
-----
    from core.control_plane._globals import (
        get_audit_ledger,
        get_security_interceptor,
        get_approval_registry,
        get_scoring_engine,
        get_health_registry,
    )
"""

from __future__ import annotations

from typing import Optional

from core.control_plane.audit_ledger import AuditLedger
from core.control_plane.smart_scheduler import DeviceScoringEngine
from core.control_plane.security_interceptor import (
    ApprovalRegistry,
    SecurityInterceptor,
)
from core.control_plane.device_health_registry import DeviceHealthRegistry

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_audit_ledger: Optional[AuditLedger] = None
_approval_registry: Optional[ApprovalRegistry] = None
_security_interceptor: Optional[SecurityInterceptor] = None
_scoring_engine: Optional[DeviceScoringEngine] = None
_health_registry: Optional[DeviceHealthRegistry] = None


def get_audit_ledger() -> AuditLedger:
    """Return the process-level :class:`AuditLedger` singleton."""
    global _audit_ledger
    if _audit_ledger is None:
        _audit_ledger = AuditLedger()
    return _audit_ledger


def get_approval_registry() -> ApprovalRegistry:
    """Return the process-level :class:`ApprovalRegistry` singleton."""
    global _approval_registry
    if _approval_registry is None:
        _approval_registry = ApprovalRegistry()
    return _approval_registry


def get_security_interceptor(default_timeout: float = 60.0) -> SecurityInterceptor:
    """Return the process-level :class:`SecurityInterceptor` singleton."""
    global _security_interceptor
    if _security_interceptor is None:
        _security_interceptor = SecurityInterceptor(
            registry=get_approval_registry(),
            default_timeout=default_timeout,
        )
    return _security_interceptor


def get_scoring_engine() -> DeviceScoringEngine:
    """Return the process-level :class:`DeviceScoringEngine` singleton."""
    global _scoring_engine
    if _scoring_engine is None:
        _scoring_engine = DeviceScoringEngine()
    return _scoring_engine


def get_health_registry() -> DeviceHealthRegistry:
    """Return the process-level :class:`DeviceHealthRegistry` singleton.

    On first call, wires up audit-ledger callbacks so that circuit-state
    changes are automatically recorded as :class:`TraceEvent` objects.
    """
    global _health_registry
    if _health_registry is None:
        _health_registry = DeviceHealthRegistry()
        _wire_health_audit_callback(_health_registry)
    return _health_registry


def _wire_health_audit_callback(registry: DeviceHealthRegistry) -> None:
    """Connect *registry* events to the shared audit ledger."""
    from core.control_plane.audit_ledger import EventType, Severity

    _EVENT_MAP = {
        "DEVICE_HEALTH_CHANGED": EventType.DEVICE_HEALTH_CHANGED,
        "DEVICE_CIRCUIT_OPEN": EventType.DEVICE_CIRCUIT_OPEN,
        "DEVICE_CIRCUIT_HALF_OPEN": EventType.DEVICE_CIRCUIT_HALF_OPEN,
        "DEVICE_CIRCUIT_CLOSED": EventType.DEVICE_CIRCUIT_CLOSED,
    }

    def _callback(event_name: str, device_id: str, **kwargs) -> None:
        ev_type = _EVENT_MAP.get(event_name)
        if ev_type is None:
            return
        try:
            severity = (
                Severity.WARNING
                if ev_type == EventType.DEVICE_CIRCUIT_OPEN
                else Severity.INFO
            )
            get_audit_ledger().append(
                ev_type,
                severity=severity,
                source="device_health_registry",
                device_id=device_id,
                message=f"{event_name} for device '{device_id}'",
                payload=kwargs,
            )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    registry.set_event_callback(_callback)
