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

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_audit_ledger: Optional[AuditLedger] = None
_approval_registry: Optional[ApprovalRegistry] = None
_security_interceptor: Optional[SecurityInterceptor] = None
_scoring_engine: Optional[DeviceScoringEngine] = None


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
