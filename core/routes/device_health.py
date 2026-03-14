#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — Device Health & Circuit-Breaker API
=============================================

Read-only health state endpoints and an unquarantine action.

Routes
------
GET  /api/v1/devices/health
    List health state for all known devices.

GET  /api/v1/devices/{device_id}/health
    Get health state for a specific device.

POST /api/v1/devices/{device_id}/unquarantine
    Manually lift quarantine on a device (requires the device to be
    quarantined; safe to call if it is not).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.API.DeviceHealth")

router = APIRouter(prefix="/api/v1/devices", tags=["device-health"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class DeviceHealthResponse(BaseModel):
    """Serialised view of one device's health state."""

    device_id: str
    circuit_state: str = Field(description="closed | half_open | open")
    health_score: float = Field(description="Composite health score [0, 100].")
    consecutive_failures: int
    heartbeat_latency_ms: float
    recent_error_rate: float = Field(description="EWMA error rate [0, 1].")
    quarantined: bool
    quarantine_reason: str
    last_failure_time: Optional[float] = Field(
        None, description="Monotonic timestamp of last failure, or None."
    )
    last_success_time: Optional[float] = Field(
        None, description="Monotonic timestamp of last success, or None."
    )


class UnquarantineResponse(BaseModel):
    """Response for unquarantine action."""

    device_id: str
    was_quarantined: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_to_response(state) -> DeviceHealthResponse:
    """Convert a :class:`DeviceHealthState` to a response model."""
    return DeviceHealthResponse(
        device_id=state.device_id,
        circuit_state=state.circuit_state.value
        if hasattr(state.circuit_state, "value")
        else str(state.circuit_state),
        health_score=state.health_score,
        consecutive_failures=state.consecutive_failures,
        heartbeat_latency_ms=state.heartbeat_latency_ms,
        recent_error_rate=state.recent_error_rate,
        quarantined=state.quarantined,
        quarantine_reason=state.quarantine_reason,
        last_failure_time=state.last_failure_time or None,
        last_success_time=state.last_success_time or None,
    )


def _get_registry():
    """Return the process-level DeviceHealthRegistry singleton."""
    from core.control_plane._globals import get_health_registry
    return get_health_registry()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health", response_model=List[DeviceHealthResponse])
async def list_device_health() -> List[DeviceHealthResponse]:
    """Return health state for all tracked devices.

    Devices that have never sent a heartbeat or had a task dispatched
    will not appear in this list.
    """
    try:
        registry = _get_registry()
        states = registry.get_all_states()
        return [_state_to_response(s) for s in states.values()]
    except Exception as exc:
        logger.exception("Failed to retrieve device health states: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{device_id}/health", response_model=DeviceHealthResponse)
async def get_device_health(device_id: str) -> DeviceHealthResponse:
    """Return health state for a specific device.

    Raises 404 if the device is not yet tracked by the health registry.
    """
    try:
        registry = _get_registry()
        state = registry.get_state(device_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Device '{device_id}' has no recorded health state.",
            )
        return _state_to_response(state)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to retrieve health state for '%s': %s", device_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{device_id}/unquarantine", response_model=UnquarantineResponse)
async def unquarantine_device(device_id: str) -> UnquarantineResponse:
    """Lift quarantine on *device_id*.

    Resets the circuit breaker to CLOSED and clears recent-failure history
    so the device can receive tasks immediately.

    This operation is idempotent: calling it on a non-quarantined device
    returns ``was_quarantined=False`` but does not raise an error.
    """
    try:
        registry = _get_registry()
        was_quarantined = registry.unquarantine(device_id)

        # Emit audit event
        try:
            from core.control_plane._globals import get_audit_ledger
            from core.control_plane.audit_ledger import EventType, Severity
            get_audit_ledger().append(
                EventType.DEVICE_HEALTH_CHANGED,
                severity=Severity.INFO,
                source="device_health_api",
                device_id=device_id,
                message=f"Device '{device_id}' manually unquarantined via API",
                payload={"was_quarantined": was_quarantined},
            )
        except Exception:
            pass

        msg = (
            f"Device '{device_id}' has been unquarantined."
            if was_quarantined
            else f"Device '{device_id}' was not quarantined (no-op)."
        )
        return UnquarantineResponse(
            device_id=device_id,
            was_quarantined=was_quarantined,
            message=msg,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to unquarantine device '%s': %s", device_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
