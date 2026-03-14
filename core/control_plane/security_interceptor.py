#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Control Plane — Security Interceptor
=============================================

Implements a **Human-In-The-Loop (HITL)** approval gate for high-risk
Control Plane actions.  Any component may call
:meth:`SecurityInterceptor.require_approval` to suspend task execution
until an operator ACKs or NACKs the action (or a timeout elapses).

Design notes
-------------
* **No ``time.sleep``** – suspension is achieved via ``asyncio.Event``
  so the event loop is never blocked.
* **Per-request tokens** – each approval request gets a cryptographically
  random ACK token.  Approvers must supply the correct token; replay or
  forged tokens are rejected.
* **Audit trail** – every state transition (requested → granted / denied /
  timed-out) is recorded in the in-memory :class:`ApprovalRegistry` and
  can be exported for auditing.
* **Timeout** – ``require_approval`` raises :class:`ApprovalTimeoutError`
  if no decision arrives within ``timeout_seconds``.

Usage
-----
    import asyncio
    from core.control_plane.security_interceptor import (
        SecurityInterceptor,
        ApprovalRegistry,
        RiskLevel,
    )

    registry = ApprovalRegistry()
    interceptor = SecurityInterceptor(registry=registry, default_timeout=30.0)

    async def my_dangerous_action():
        token = await interceptor.require_approval(
            task_id="task_abc",
            action="delete_all_data",
            risk_level=RiskLevel.HIGH,
            requestor="scheduler",
            context={"target": "device_xyz"},
        )
        print(f"Approved with token {token}")
        # … proceed with the action …

    # In a separate coroutine / operator handler:
    async def operator_panel():
        pending = registry.list_pending()
        req = pending[0]
        registry.ack(req.request_id, req.ack_token)   # grant

    asyncio.run(main())   # wire both coroutines together
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ApprovalTimeoutError(TimeoutError):
    """Raised when an approval request is not resolved within the timeout."""

    def __init__(self, request_id: str, timeout_seconds: float) -> None:
        self.request_id = request_id
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Approval request '{request_id}' timed out after {timeout_seconds}s."
        )


class ApprovalDeniedError(PermissionError):
    """Raised when an approval request is explicitly denied by an operator."""

    def __init__(self, request_id: str, reason: str = "") -> None:
        self.request_id = request_id
        self.reason = reason
        super().__init__(
            f"Approval request '{request_id}' was denied. Reason: {reason or 'none given'}"
        )


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Qualitative risk classification for approval-gated actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, Enum):
    """Lifecycle state of an approval request."""

    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ApprovalRequest(BaseModel):
    """Represents a single HITL approval gate request."""

    request_id: str = Field(
        default_factory=lambda: f"apv_{uuid.uuid4().hex[:16]}",
        description="Unique identifier for this approval request.",
    )
    ack_token: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description=(
            "Cryptographically random token.  Operators must supply this "
            "exact value to grant the request, preventing replay attacks."
        ),
    )
    task_id: Optional[str] = Field(None, description="Associated task ID.")
    action: str = Field(..., description="Human-readable name of the gated action.")
    risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM)
    requestor: str = Field(
        default="",
        description="Component or agent requesting the approval.",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary context data surfaced to the operator.",
    )
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Optional[datetime] = Field(None)
    resolved_by: Optional[str] = Field(
        None,
        description="Identifier of the operator who resolved the request.",
    )
    deny_reason: Optional[str] = Field(None)

    model_config = {"frozen": False}  # status is mutable until resolved


class ApprovalAuditEntry(BaseModel):
    """Immutable record of a resolved approval request for audit purposes."""

    entry_id: str = Field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:12]}")
    request_id: str
    task_id: Optional[str]
    action: str
    risk_level: RiskLevel
    requestor: str
    status: ApprovalStatus
    requested_at: datetime
    resolved_at: Optional[datetime]
    resolved_by: Optional[str]
    deny_reason: Optional[str]

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Approval registry
# ---------------------------------------------------------------------------

class ApprovalRegistry:
    """In-memory store for pending and resolved approval requests.

    The registry is the single source of truth for operator decisions.
    It is separate from :class:`SecurityInterceptor` so it can be injected,
    shared across interceptor instances, and queried independently.
    """

    def __init__(self) -> None:
        # request_id → (ApprovalRequest, asyncio.Event, denied_flag)
        self._pending: Dict[str, tuple] = {}
        # Immutable audit log
        self._audit: List[ApprovalAuditEntry] = []

    # ------------------------------------------------------------------
    # Internal helpers called by SecurityInterceptor
    # ------------------------------------------------------------------

    def _register(self, request: ApprovalRequest) -> asyncio.Event:
        """Register a new pending request and return its resolution event."""
        event = asyncio.Event()
        self._pending[request.request_id] = (request, event, [False])
        return event

    def _resolve(
        self,
        request_id: str,
        new_status: ApprovalStatus,
        resolved_by: str = "",
        deny_reason: str = "",
    ) -> None:
        """Transition a request to a terminal state and signal waiters."""
        if request_id not in self._pending:
            return
        request, event, denied_flag = self._pending[request_id]
        request.status = new_status
        request.resolved_at = datetime.now(timezone.utc)
        request.resolved_by = resolved_by or None
        request.deny_reason = deny_reason or None
        if new_status in (ApprovalStatus.DENIED, ApprovalStatus.TIMED_OUT, ApprovalStatus.CANCELLED):
            denied_flag[0] = True
        self._audit.append(
            ApprovalAuditEntry(
                request_id=request.request_id,
                task_id=request.task_id,
                action=request.action,
                risk_level=request.risk_level,
                requestor=request.requestor,
                status=new_status,
                requested_at=request.requested_at,
                resolved_at=request.resolved_at,
                resolved_by=request.resolved_by,
                deny_reason=request.deny_reason,
            )
        )
        event.set()  # unblock the waiting coroutine

    # ------------------------------------------------------------------
    # Operator-facing API
    # ------------------------------------------------------------------

    def ack(self, request_id: str, ack_token: str, operator: str = "") -> bool:
        """Grant an approval request using the correct ACK token.

        Parameters
        ----------
        request_id:
            The request to approve.
        ack_token:
            Must match :attr:`ApprovalRequest.ack_token` exactly.
        operator:
            Optional identifier of the approving operator.

        Returns
        -------
        bool
            ``True`` if the request was found, token matched, and was granted.
            ``False`` otherwise (wrong token, already resolved, not found).
        """
        entry = self._pending.get(request_id)
        if entry is None:
            return False
        request, _event, _denied = entry
        if request.status != ApprovalStatus.PENDING:
            return False
        # Constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(request.ack_token, ack_token):
            return False
        self._resolve(request_id, ApprovalStatus.GRANTED, resolved_by=operator)
        return True

    def deny(self, request_id: str, operator: str = "", reason: str = "") -> bool:
        """Deny an approval request.

        Parameters
        ----------
        request_id:
            The request to deny.
        operator:
            Optional identifier of the denying operator.
        reason:
            Human-readable reason for the denial.

        Returns
        -------
        bool
            ``True`` if the request was found and denied.
        """
        entry = self._pending.get(request_id)
        if entry is None:
            return False
        request, _event, _denied = entry
        if request.status != ApprovalStatus.PENDING:
            return False
        self._resolve(
            request_id, ApprovalStatus.DENIED,
            resolved_by=operator, deny_reason=reason
        )
        return True

    def list_pending(self) -> List[ApprovalRequest]:
        """Return all currently pending (unresolved) approval requests."""
        return [
            req
            for req, _ev, _d in self._pending.values()
            if req.status == ApprovalStatus.PENDING
        ]

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Retrieve an approval request by ID (pending or resolved)."""
        entry = self._pending.get(request_id)
        return entry[0] if entry else None

    def audit_log(self) -> List[ApprovalAuditEntry]:
        """Return an immutable view of all resolved audit entries."""
        return list(self._audit)


# ---------------------------------------------------------------------------
# Security interceptor
# ---------------------------------------------------------------------------

class SecurityInterceptor:
    """Async HITL gate that suspends execution pending operator approval.

    Parameters
    ----------
    registry:
        Shared :class:`ApprovalRegistry`.  A new registry is created if
        not provided (useful for isolated testing).
    default_timeout:
        Seconds to wait for operator approval before raising
        :class:`ApprovalTimeoutError`.  Can be overridden per request.
    """

    def __init__(
        self,
        registry: Optional[ApprovalRegistry] = None,
        default_timeout: float = 60.0,
    ) -> None:
        self.registry = registry or ApprovalRegistry()
        self.default_timeout = default_timeout

    async def require_approval(
        self,
        action: str,
        *,
        task_id: Optional[str] = None,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        requestor: str = "",
        context: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Suspend execution until an operator ACKs the action or a timeout.

        This coroutine creates an :class:`ApprovalRequest`, registers it in
        the shared registry (making it visible to operator dashboards), and
        then waits on an ``asyncio.Event``.  The event is set when
        :meth:`ApprovalRegistry.ack` or :meth:`ApprovalRegistry.deny` is
        called by an operator.

        Parameters
        ----------
        action:
            Human-readable name of the action requiring approval.
        task_id:
            Optional task identifier for correlation.
        risk_level:
            Qualitative risk classification.
        requestor:
            Component requesting the approval.
        context:
            Arbitrary key-value data surfaced to the operator panel.
        timeout:
            Override the instance-level ``default_timeout`` for this call.

        Returns
        -------
        str
            The ``ack_token`` of the granted request.  Callers can log this
            as evidence that approval was obtained.

        Raises
        ------
        ApprovalTimeoutError
            If no decision arrives within *timeout* seconds.
        ApprovalDeniedError
            If an operator explicitly denies the request.
        """
        request = ApprovalRequest(
            action=action,
            task_id=task_id,
            risk_level=risk_level,
            requestor=requestor,
            context=context or {},
        )
        event = self.registry._register(request)
        effective_timeout = timeout if timeout is not None else self.default_timeout

        try:
            await asyncio.wait_for(event.wait(), timeout=effective_timeout)
        except asyncio.TimeoutError:
            # Transition to timed-out state so the registry stays consistent
            self.registry._resolve(
                request.request_id,
                ApprovalStatus.TIMED_OUT,
                deny_reason="Approval window elapsed.",
            )
            raise ApprovalTimeoutError(request.request_id, effective_timeout)

        # Check whether the resolved state is a denial
        resolved = self.registry.get_request(request.request_id)
        if resolved is not None and resolved.status in (
            ApprovalStatus.DENIED,
            ApprovalStatus.CANCELLED,
        ):
            raise ApprovalDeniedError(
                request.request_id,
                resolved.deny_reason or "",
            )

        return request.ack_token

    async def bypass(
        self,
        action: str,
        *,
        task_id: Optional[str] = None,
        risk_level: RiskLevel = RiskLevel.LOW,
        requestor: str = "system",
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Auto-approve an action without waiting for a human.

        **Use only for low-risk, automated actions** where HITL overhead is
        undesirable (e.g. heartbeat recording, telemetry uploads).

        Returns
        -------
        str
            The auto-generated ACK token.
        """
        request = ApprovalRequest(
            action=action,
            task_id=task_id,
            risk_level=risk_level,
            requestor=requestor,
            context=context or {},
        )
        self.registry._register(request)
        self.registry._resolve(
            request.request_id,
            ApprovalStatus.GRANTED,
            resolved_by="system:bypass",
        )
        return request.ack_token
