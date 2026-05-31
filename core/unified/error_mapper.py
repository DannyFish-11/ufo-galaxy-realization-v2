#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/error_mapper.py
=============================
Block-5: Error Taxonomy — cross-subsystem mapper

Maps raw exceptions and legacy error objects from all major subsystems
(planner, executor, gateway, device, transport) into the canonical
:class:`~core.unified.error_codes.ErrorPayload` / :class:`~core.unified.error_codes.GalaxyErrorCode`
taxonomy.

Usage::

    from core.unified.error_mapper import ErrorMapper

    try:
        await some_device_operation()
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        payload = ErrorMapper.from_exception(exc, trace_id="t-123")
        if payload.retryable:
            schedule_retry(payload)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Type

from .error_codes import (
    ErrorDomain,
    ErrorPayload,
    GalaxyErrorCode,
    Retryable,
    ErrorSeverity,
    _ErrorCodeDef,
)

logger = logging.getLogger("Galaxy.ErrorMapper")


# ---------------------------------------------------------------------------
# Exception-type → code mapping table
# ---------------------------------------------------------------------------
# Keyed by fully-qualified exception class names so we avoid hard-importing
# every possible exception class (some may be optional deps).

_EXCEPTION_NAME_MAP: Dict[str, GalaxyErrorCode] = {
    # core.unified.exceptions
    "DeviceNotFoundError": GalaxyErrorCode.DEVICE_NOT_FOUND,
    "DeviceTimeoutError": GalaxyErrorCode.DEVICE_TIMEOUT,
    "DeviceSendError": GalaxyErrorCode.DEVICE_SEND_FAILED,
    "DeviceAlreadyRegisteredError": GalaxyErrorCode.DEVICE_NOT_FOUND,
    "DeviceRegistrationError": GalaxyErrorCode.DEVICE_NOT_FOUND,
    "DeviceManagerError": GalaxyErrorCode.DEVICE_SEND_FAILED,
    # connection / transport
    "ConnectionError": GalaxyErrorCode.TRANSPORT_CONNECT_FAILED,
    "NATSConnectionError": GalaxyErrorCode.TRANSPORT_CONNECT_FAILED,
    "NATSPublishError": GalaxyErrorCode.TRANSPORT_PUBLISH_FAILED,
    "WebSocketDisconnect": GalaxyErrorCode.TRANSPORT_DISCONNECT,
    # gateway / protocol
    "EnvelopeValidationError": GalaxyErrorCode.GW_ENVELOPE_INVALID,
    "CapabilityContractError": GalaxyErrorCode.GW_PROTOCOL_MISMATCH,
    "PolicyViolationError": GalaxyErrorCode.GW_AUTH_FAILED,
    # planner
    "PlanDecomposeError": GalaxyErrorCode.PLAN_DECOMPOSE_FAILED,
    "GraphCycleError": GalaxyErrorCode.PLAN_CYCLE_DETECTED,
    # executor
    "TaskCancelledError": GalaxyErrorCode.EXEC_CANCELLED,
    "ResourceExhaustedError": GalaxyErrorCode.EXEC_RESOURCE_EXHAUSTED,
    # idempotency
    "DuplicateCommandError": GalaxyErrorCode.IDEMPOTENCY_DUPLICATE,
    "IdempotencyConflictError": GalaxyErrorCode.IDEMPOTENCY_CONFLICT,
    # arbiter
    "ArbiterPreemptedError": GalaxyErrorCode.ARBITER_PREEMPTED,
    "ArbiterQuotaError": GalaxyErrorCode.ARBITER_QUOTA_EXCEEDED,
    # release
    "FeatureDisabledError": GalaxyErrorCode.RELEASE_FEATURE_DISABLED,
    "RolloutBlockedError": GalaxyErrorCode.RELEASE_ROLLOUT_BLOCKED,
    # stdlib
    "TimeoutError": GalaxyErrorCode.EXEC_TASK_TIMEOUT,
    "asyncio.TimeoutError": GalaxyErrorCode.EXEC_TASK_TIMEOUT,
    "asyncio.CancelledError": GalaxyErrorCode.EXEC_CANCELLED,
    "PermissionError": GalaxyErrorCode.GW_AUTH_FAILED,
    "ConnectionRefusedError": GalaxyErrorCode.TRANSPORT_CONNECT_FAILED,
    "ConnectionResetError": GalaxyErrorCode.TRANSPORT_DISCONNECT,
}


def _class_names(exc: Exception) -> list[str]:
    """Return a list of class names in the MRO of *exc* (excluding builtins)."""
    names = []
    for cls in type(exc).__mro__:
        names.append(cls.__name__)
        qname = f"{cls.__module__}.{cls.__name__}"
        names.append(qname)
    return names


# ---------------------------------------------------------------------------
# Error mapper
# ---------------------------------------------------------------------------


class ErrorMapper:
    """Stateless mapper between raw exceptions / legacy payloads and canonical
    :class:`~core.unified.error_codes.ErrorPayload` instances.
    """

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    @staticmethod
    def from_exception(
        exc: Exception,
        *,
        trace_id: str = "",
        task_id: str = "",
        detail: Optional[Dict[str, Any]] = None,
    ) -> ErrorPayload:
        """Map any Python exception to a canonical :class:`ErrorPayload`.

        The mapping logic:
        1. Walk the exception's MRO and match against ``_EXCEPTION_NAME_MAP``.
        2. If the exception itself carries a ``code`` attribute that matches a
           known :class:`GalaxyErrorCode`, use that.
        3. Fall back to :attr:`~GalaxyErrorCode.INTERNAL_UNKNOWN`.
        """
        code = ErrorMapper._resolve_code(exc)
        message = str(exc) or repr(exc)
        extra = dict(detail) if detail else {}
        extra["exception_type"] = type(exc).__name__

        payload = ErrorPayload.from_code(
            code,
            message=message,
            detail=extra,
            trace_id=trace_id,
            task_id=task_id,
        )
        logger.debug(
            "ErrorMapper: mapped %s → %s (retryable=%s)",
            type(exc).__name__, code.value, payload.retryable,
        )
        return payload

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> ErrorPayload:
        """Reconstruct an :class:`ErrorPayload` from a serialised dict."""
        return ErrorPayload.from_dict(raw)

    @staticmethod
    def from_legacy_gateway_error(
        error_type: str,
        message: str = "",
        *,
        trace_id: str = "",
        task_id: str = "",
    ) -> ErrorPayload:
        """Map a legacy gateway error type string to a canonical payload."""
        _legacy_map: Dict[str, GalaxyErrorCode] = {
            "validation_error": GalaxyErrorCode.GW_ENVELOPE_INVALID,
            "route_not_found": GalaxyErrorCode.GW_ROUTE_NOT_FOUND,
            "auth_error": GalaxyErrorCode.GW_AUTH_FAILED,
            "rate_limit": GalaxyErrorCode.GW_RATE_LIMITED,
            "protocol_error": GalaxyErrorCode.GW_PROTOCOL_MISMATCH,
            "timeout": GalaxyErrorCode.EXEC_TASK_TIMEOUT,
            "device_not_found": GalaxyErrorCode.DEVICE_NOT_FOUND,
            "device_offline": GalaxyErrorCode.DEVICE_OFFLINE,
        }
        code = _legacy_map.get(error_type.lower(), GalaxyErrorCode.INTERNAL_UNKNOWN)
        return ErrorPayload.from_code(
            code, message=message, trace_id=trace_id, task_id=task_id,
        )

    @staticmethod
    def from_legacy_device_error(
        device_id: str,
        error_msg: str,
        *,
        trace_id: str = "",
        task_id: str = "",
    ) -> ErrorPayload:
        """Map a legacy device-level error string to a canonical payload."""
        msg_lower = error_msg.lower()
        if "timeout" in msg_lower or "timed out" in msg_lower:
            code = GalaxyErrorCode.DEVICE_TIMEOUT
        elif "offline" in msg_lower or "unreachable" in msg_lower:
            code = GalaxyErrorCode.DEVICE_OFFLINE
        elif "not found" in msg_lower:
            code = GalaxyErrorCode.DEVICE_NOT_FOUND
        elif "capability" in msg_lower:
            code = GalaxyErrorCode.DEVICE_CAPABILITY_MISSING
        else:
            code = GalaxyErrorCode.DEVICE_SEND_FAILED
        return ErrorPayload.from_code(
            code,
            message=error_msg,
            detail={"device_id": device_id},
            trace_id=trace_id,
            task_id=task_id,
        )

    @staticmethod
    def from_legacy_executor_error(
        error_msg: str,
        *,
        trace_id: str = "",
        task_id: str = "",
    ) -> ErrorPayload:
        """Map a legacy executor-level error string to a canonical payload."""
        msg_lower = error_msg.lower()
        if "timeout" in msg_lower or "timed out" in msg_lower:
            code = GalaxyErrorCode.EXEC_TASK_TIMEOUT
        elif "cancel" in msg_lower:
            code = GalaxyErrorCode.EXEC_CANCELLED
        elif "preempt" in msg_lower:
            code = GalaxyErrorCode.EXEC_PREEMPTED
        elif "resource" in msg_lower or "quota" in msg_lower:
            code = GalaxyErrorCode.EXEC_RESOURCE_EXHAUSTED
        else:
            code = GalaxyErrorCode.EXEC_DISPATCH_FAILED
        return ErrorPayload.from_code(
            code, message=error_msg, trace_id=trace_id, task_id=task_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_code(exc: Exception) -> GalaxyErrorCode:
        # 1. Walk MRO names
        for name in _class_names(exc):
            if name in _EXCEPTION_NAME_MAP:
                return _EXCEPTION_NAME_MAP[name]
        # 2. If exception has a 'code' attribute matching a GalaxyErrorCode
        raw_code = getattr(exc, "code", None)
        if raw_code is not None:
            try:
                return GalaxyErrorCode(str(raw_code))
            except ValueError:
                pass
        return GalaxyErrorCode.INTERNAL_UNKNOWN
