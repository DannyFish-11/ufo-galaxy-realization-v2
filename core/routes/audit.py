"""
Galaxy – Audit Ledger Routes
=============================

Exposes the Control Plane audit ledger via REST.

Endpoints
---------
GET  /api/v1/audit/traces
    Return the most recent audit events (configurable limit).

GET  /api/v1/audit/traces/{trace_id}
    Export all events for a given trace as a JSON array.

GET  /api/v1/audit/traces/{trace_id}/dag
    Export the causal DAG for a given trace as an adjacency list.

GET  /api/v1/audit/snapshot
    Return a full ledger snapshot (all events, all traces).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API.Audit")


def create_router() -> APIRouter:
    """Create and return the audit routes router."""
    router = APIRouter()

    def _ledger():
        from core.control_plane._globals import get_audit_ledger
        return get_audit_ledger()

    @router.get("/api/v1/audit/traces")
    async def list_recent_events(
        limit: int = Query(default=100, ge=1, le=10_000, description="Maximum events to return"),
        trace_id: Optional[str] = Query(default=None, description="Filter by trace_id"),
        task_id: Optional[str] = Query(default=None, description="Filter by task_id"),
        source: Optional[str] = Query(default=None, description="Filter by source component"),
    ):
        """Return recent audit events with optional filters."""
        try:
            ledger = _ledger()
            events = ledger.query(
                trace_id=trace_id,
                task_id=task_id,
                source=source,
                limit=limit,
            )
            return JSONResponse(
                content={
                    "ok": True,
                    "count": len(events),
                    "events": [ev.model_dump(mode="json") for ev in events],
                }
            )
        except Exception as exc:
            logger.error("audit list_recent_events failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )

    @router.get("/api/v1/audit/traces/{trace_id}")
    async def get_trace_json(trace_id: str):
        """Export all events for *trace_id* as a JSON array."""
        try:
            ledger = _ledger()
            events = ledger.query(trace_id=trace_id)
            if not events:
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "error": f"No events found for trace_id '{trace_id}'"},
                )
            from core.control_plane.audit_ledger import events_to_json
            return JSONResponse(
                content={
                    "ok": True,
                    "trace_id": trace_id,
                    "count": len(events),
                    "events": [ev.model_dump(mode="json") for ev in events],
                }
            )
        except Exception as exc:
            logger.error("audit get_trace_json failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )

    @router.get("/api/v1/audit/traces/{trace_id}/dag")
    async def get_trace_dag(trace_id: str):
        """Export the causal DAG (adjacency list) for *trace_id*."""
        try:
            ledger = _ledger()
            events = ledger.query(trace_id=trace_id)
            if not events:
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "error": f"No events found for trace_id '{trace_id}'"},
                )
            from core.control_plane.audit_ledger import events_to_dag
            dag = events_to_dag(events)
            return JSONResponse(
                content={
                    "ok": True,
                    "trace_id": trace_id,
                    "node_count": len(dag),
                    "dag": dag,
                }
            )
        except Exception as exc:
            logger.error("audit get_trace_dag failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )

    @router.get("/api/v1/audit/snapshot")
    async def get_ledger_snapshot():
        """Return a full snapshot of the audit ledger."""
        try:
            ledger = _ledger()
            snap = ledger.snapshot()
            return JSONResponse(
                content={
                    "ok": True,
                    "snapshot_id": snap.snapshot_id,
                    "captured_at": snap.captured_at.isoformat(),
                    "event_count": snap.event_count,
                    "events": [ev.model_dump(mode="json") for ev in snap.events],
                }
            )
        except Exception as exc:
            logger.error("audit get_ledger_snapshot failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )

    return router
