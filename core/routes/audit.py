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

GET  /api/v1/audit/traces/{trace_id}/timeline
    Return events ordered chronologically, annotated with stage labels.
    Stage labels: intent / plan / tool / dispatch / exec / result.

GET  /api/v1/audit/traces/{trace_id}/graph
    Return a rich graph representation (nodes + computed edges) for the trace.

GET  /api/v1/audit/snapshot
    Return a full ledger snapshot (all events, all traces).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API.Audit")

# ---------------------------------------------------------------------------
# Stage aggregation helpers (Phase 4)
# ---------------------------------------------------------------------------

_EVENT_STAGE_MAP: Dict[str, str] = {
    "task_created": "intent",
    "scheduler_decision": "plan",
    "agent_created": "plan",
    "tool_called": "tool",
    "tool_result": "tool",
    "task_dispatched": "dispatch",
    "agent_dispatched": "dispatch",
    "task_started": "exec",
    "agent_executed": "exec",
    "task_completed": "result",
    "task_failed": "result",
    "agent_result_received": "result",
    "approval_requested": "security",
    "approval_granted": "security",
    "approval_denied": "security",
    "approval_timed_out": "security",
}

_STAGE_ORDER = ["intent", "plan", "tool", "dispatch", "exec", "result", "security", "other"]


def _event_stage(event_type_value: str) -> str:
    return _EVENT_STAGE_MAP.get(event_type_value, "other")


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

    @router.get("/api/v1/audit/traces/{trace_id}/timeline")
    async def get_trace_timeline(trace_id: str):
        """Return all events for *trace_id* ordered chronologically with stage labels.

        Each event in the response carries an additional ``stage`` field
        grouping it into one of: intent / plan / tool / dispatch / exec /
        result / security / other.
        """
        try:
            ledger = _ledger()
            events = ledger.query(trace_id=trace_id)
            if not events:
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "error": f"No events found for trace_id '{trace_id}'"},
                )
            # Sort chronologically
            sorted_events = sorted(events, key=lambda e: e.timestamp)
            # Annotate with stage
            annotated = []
            for ev in sorted_events:
                d = ev.model_dump(mode="json")
                d["stage"] = _event_stage(ev.event_type if isinstance(ev.event_type, str) else ev.event_type.value)
                annotated.append(d)
            # Group by stage for the summary
            stages: Dict[str, int] = {}
            for item in annotated:
                stages[item["stage"]] = stages.get(item["stage"], 0) + 1
            return JSONResponse(
                content={
                    "ok": True,
                    "trace_id": trace_id,
                    "count": len(annotated),
                    "stage_summary": stages,
                    "timeline": annotated,
                }
            )
        except Exception as exc:
            logger.error("audit get_trace_timeline failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )

    @router.get("/api/v1/audit/traces/{trace_id}/graph")
    async def get_trace_graph(trace_id: str):
        """Return a rich graph (nodes + computed edges) for *trace_id*.

        The graph format is::

            {
              "ok": true,
              "trace_id": "...",
              "nodes": [{"id": "ev_...", "stage": "...", "event_type": "...", ...}],
              "edges": [{"source": "ev_parent", "target": "ev_child"}]
            }

        Edges are derived from ``parent_ids`` on each event; additional
        sequential edges are inferred between consecutive events within the
        same stage to aid visualisation.
        """
        try:
            ledger = _ledger()
            events = ledger.query(trace_id=trace_id)
            if not events:
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "error": f"No events found for trace_id '{trace_id}'"},
                )
            sorted_events = sorted(events, key=lambda e: e.timestamp)

            # Build nodes
            nodes = []
            for ev in sorted_events:
                d = ev.model_dump(mode="json")
                d["stage"] = _event_stage(ev.event_type if isinstance(ev.event_type, str) else ev.event_type.value)
                nodes.append(d)

            # Build edges from parent_ids
            edges = []
            for ev in sorted_events:
                for parent_id in ev.parent_ids:
                    edges.append({"source": parent_id, "target": ev.event_id})

            # Add inferred sequential edges within the same stage
            stage_last: Dict[str, str] = {}
            for node in nodes:
                stage = node["stage"]
                if stage in stage_last:
                    inferred_edge = {"source": stage_last[stage], "target": node["id"], "inferred": True}
                    # Only add if not already present
                    if inferred_edge not in edges:
                        edges.append(inferred_edge)
                stage_last[stage] = node["id"]

            return JSONResponse(
                content={
                    "ok": True,
                    "trace_id": trace_id,
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "nodes": nodes,
                    "edges": edges,
                }
            )
        except Exception as exc:
            logger.error("audit get_trace_graph failed: %s", exc, exc_info=True)
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
