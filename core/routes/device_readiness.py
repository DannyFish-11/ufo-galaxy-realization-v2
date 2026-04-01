"""
core/routes/device_readiness.py
================================
Read-only inspection endpoints for device readiness and participation.

Design constraints
------------------
- **Read-only** — this router never writes state, sends commands, or triggers
  actions.
- **Additive** — does not modify any existing module behaviour.
- **Graceful degradation** — if readiness or participation sources are
  unavailable, returns partial summaries with reasons rather than failing.

Routes
------
GET /api/v1/devices/readiness
    List readiness summaries for all known devices.
    Optional query parameters: ``only_ready``, ``only_connected``,
    ``only_routable``.

GET /api/v1/devices/{device_id}/readiness
    Return a single :class:`~core.device_readiness.DeviceReadinessSummary`.

GET /api/v1/devices/participation
    List participation/orchestration summaries for all known devices.
    Optional query parameter: ``only_ready``.

GET /api/v1/devices/{device_id}/participation
    Return a single participation summary derived from
    :func:`~core.device_selection.assess_device_participation`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.DeviceReadiness")

DEVICE_READINESS_ROUTES_AUTHORITY: str = "DEVICE_READINESS_ROUTES_V1"


# ---------------------------------------------------------------------------
# Internal helpers — defensive imports
# ---------------------------------------------------------------------------


def _get_readiness_module():
    """Return the device_readiness module, or None on import failure."""
    try:
        import core.device_readiness as dr_mod
        return dr_mod
    except Exception as exc:
        logger.debug("device_readiness module unavailable: %s", exc)
        return None


def _get_udm():
    """Return UnifiedDeviceManager singleton, or None on failure."""
    try:
        from core.unified.device_manager import get_unified_device_manager
        return get_unified_device_manager()
    except Exception as exc:
        logger.debug("UDM unavailable: %s", exc)
        return None


def _get_participation_for_device(device_id: str) -> Dict[str, Any]:
    """Return a participation summary dict for *device_id*.

    Uses :func:`~core.device_selection.assess_device_participation` when the
    device can be resolved from UDM.  Degrades gracefully if unavailable.
    """
    result: Dict[str, Any] = {
        "device_id": device_id,
        "registered": False,
        "cross_device_eligible": False,
        "orchestration_eligible": False,
        "participation_reason": "not_assessed",
        "sources": [],
    }
    try:
        udm = _get_udm()
        if udm is None:
            result["participation_reason"] = "udm_unavailable"
            return result

        device = udm.get_device(device_id)
        if device is None:
            result["participation_reason"] = "device_not_found"
            return result

        from core.device_selection import assess_device_participation
        status = assess_device_participation(device)
        participation_dict = status.to_dict()
        result.update(participation_dict)
        result["device_id"] = device_id
        result["sources"].append("canonical_device_selector")
    except Exception as exc:
        logger.warning(
            "DeviceReadinessRoutes: participation assessment failed for %s: %s",
            device_id,
            exc,
        )
        result["participation_reason"] = f"assessment_error: {exc}"
    return result


def _list_all_device_ids() -> List[str]:
    """Return all device_ids from UDM, or empty list on failure."""
    try:
        udm = _get_udm()
        if udm is None:
            return []
        devices = udm.list_devices()
        return [str(getattr(d, "device_id", "")) for d in devices if getattr(d, "device_id", None)]
    except Exception as exc:
        logger.warning("DeviceReadinessRoutes: list_devices failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the device readiness/participation inspection router.

    The ``service_manager`` and ``config`` parameters follow the same
    convention used by all other ``core/routes/`` modules and are accepted
    to allow uniform registration in ``core/api_routes.py``, but are not
    required by this read-only router.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/devices/readiness  (list — must be before the {device_id} route)
    # ------------------------------------------------------------------

    @router.get("/api/v1/devices/readiness")
    async def list_device_readiness(
        only_ready: bool = Query(False, description="Return only fully ready devices"),
        only_connected: bool = Query(False, description="Return only connected devices"),
        only_routable: bool = Query(False, description="Return only routable devices"),
    ) -> JSONResponse:
        """Return readiness summaries for all known devices.

        Each summary is a :class:`~core.device_readiness.DeviceReadinessSummary`
        serialised to a JSON object.  Filters are applied additively (AND logic).
        If the readiness subsystem is unavailable, returns an empty list with a
        diagnostic message.
        """
        dr_mod = _get_readiness_module()
        if dr_mod is None:
            return JSONResponse(
                content={
                    "summaries": [],
                    "authority": DEVICE_READINESS_ROUTES_AUTHORITY,
                    "error": "device_readiness_module_unavailable",
                },
                status_code=200,
            )

        device_ids = _list_all_device_ids()
        summaries: List[Dict[str, Any]] = []
        for device_id in device_ids:
            try:
                rs = dr_mod.get_device_readiness(device_id)
                if only_ready and not (rs.registered and rs.online and rs.connected and rs.routable):
                    continue
                if only_connected and not rs.connected:
                    continue
                if only_routable and not rs.routable:
                    continue
                summaries.append(rs.to_dict())
            except Exception as exc:
                logger.warning(
                    "DeviceReadinessRoutes: readiness eval failed for %s: %s",
                    device_id,
                    exc,
                )
                summaries.append({
                    "device_id": device_id,
                    "error": str(exc),
                    "registered": False,
                    "online": False,
                    "connected": False,
                    "routable": False,
                })

        return JSONResponse(
            content={
                "summaries": summaries,
                "total": len(summaries),
                "authority": DEVICE_READINESS_ROUTES_AUTHORITY,
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/devices/{device_id}/readiness
    # ------------------------------------------------------------------

    @router.get("/api/v1/devices/{device_id}/readiness")
    async def get_device_readiness_endpoint(device_id: str) -> JSONResponse:
        """Return a single readiness summary for *device_id*.

        Degrades gracefully: if the underlying readiness subsystem is
        unavailable, returns a partial summary with ``reasons`` explaining
        what could not be determined.  A 404 is returned only when UDM
        explicitly reports the device as not registered.
        """
        dr_mod = _get_readiness_module()
        if dr_mod is None:
            return JSONResponse(
                content={
                    "device_id": device_id,
                    "registered": False,
                    "error": "device_readiness_module_unavailable",
                    "authority": DEVICE_READINESS_ROUTES_AUTHORITY,
                },
                status_code=200,
            )

        try:
            rs = dr_mod.get_device_readiness(device_id)
        except Exception as exc:
            logger.warning(
                "DeviceReadinessRoutes: get_device_readiness failed for %s: %s",
                device_id,
                exc,
            )
            return JSONResponse(
                content={
                    "device_id": device_id,
                    "registered": False,
                    "error": str(exc),
                    "authority": DEVICE_READINESS_ROUTES_AUTHORITY,
                },
                status_code=200,
            )

        payload = rs.to_dict()
        payload["authority"] = DEVICE_READINESS_ROUTES_AUTHORITY
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/devices/participation  (list — must be before {device_id})
    # ------------------------------------------------------------------

    @router.get("/api/v1/devices/participation")
    async def list_device_participation(
        only_ready: bool = Query(
            False,
            description="Return only orchestration-eligible devices",
        ),
    ) -> JSONResponse:
        """Return participation summaries for all known devices.

        Each entry reports the five participation flags derived from
        :func:`~core.device_selection.assess_device_participation`:
        ``registered``, ``runtime_present``, ``routable``,
        ``cross_device_eligible``, ``orchestration_eligible``.
        If ``only_ready=true``, only orchestration-eligible devices are returned.
        """
        device_ids = _list_all_device_ids()
        summaries: List[Dict[str, Any]] = []
        for device_id in device_ids:
            summary = _get_participation_for_device(device_id)
            if only_ready and not summary.get("orchestration_eligible", False):
                continue
            summaries.append(summary)

        return JSONResponse(
            content={
                "summaries": summaries,
                "total": len(summaries),
                "authority": DEVICE_READINESS_ROUTES_AUTHORITY,
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/devices/{device_id}/participation
    # ------------------------------------------------------------------

    @router.get("/api/v1/devices/{device_id}/participation")
    async def get_device_participation_endpoint(device_id: str) -> JSONResponse:
        """Return a participation/orchestration summary for *device_id*.

        Uses :func:`~core.device_selection.assess_device_participation` to
        derive the five participation flags from the canonical
        ``RegisteredRuntimeDevice`` contract.  If the device is unknown,
        returns a partial summary with ``participation_reason`` explaining
        the failure rather than raising a 404, to allow safe inspection by
        operators and automated tests.
        """
        summary = _get_participation_for_device(device_id)
        summary["authority"] = DEVICE_READINESS_ROUTES_AUTHORITY
        return JSONResponse(content=summary)

    return router
