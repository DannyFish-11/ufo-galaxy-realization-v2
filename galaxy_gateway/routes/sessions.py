"""
galaxy_gateway/routes/sessions.py — Session roaming REST endpoints.

Routes:
  GET  /api/v1/sessions                          - List sessions (optional state filter)
  GET  /api/v1/sessions/{session_id}             - Get session details
  POST /api/v1/sessions/{session_id}/migrate     - Trigger session migration
  POST /api/v1/sessions/{session_id}/close       - Close a roaming session (frees its device mapping)
  GET  /api/v1/sessions/stats                    - Session statistics
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from core.auth import require_auth as _require_auth
except ImportError:

    async def _require_auth():  # type: ignore[misc]
        return {"authenticated": True, "dev_mode": True}


logger = logging.getLogger(__name__)

router = APIRouter()


class SessionMigrateRequest(BaseModel):
    target_device_id: str


@router.get("/api/v1/sessions")
async def list_sessions(
    state: Optional[str] = None,
    auth: dict = Depends(_require_auth),
):
    """List all sessions, optionally filtered by state."""
    try:
        from galaxy_gateway.session_roaming import SessionState, session_roaming

        filter_state = None
        if state:
            try:
                filter_state = SessionState(state)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid state: {state}")

        sessions = session_roaming.list_sessions(state=filter_state)
        return {"sessions": sessions, "total": len(sessions)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/sessions/stats")
async def session_stats(auth: dict = Depends(_require_auth)):
    """Return session statistics."""
    try:
        from galaxy_gateway.session_roaming import session_roaming

        return session_roaming.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/sessions/{session_id}")
async def get_session(session_id: str, auth: dict = Depends(_require_auth)):
    """Return details for a single session."""
    try:
        from galaxy_gateway.session_roaming import session_roaming

        session = session_roaming.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/sessions/{session_id}/close")
async def close_session(session_id: str, auth: dict = Depends(_require_auth)):
    """Close a roaming session: state → closed, device mapping released, persisted."""
    from core.session_migration import close_roaming_session

    result = close_roaming_session(session_id)
    if not result["success"]:
        raise HTTPException(status_code=int(result["status_code"]), detail="Session not found")
    return result["session"]


@router.post("/api/v1/sessions/{session_id}/migrate")
async def migrate_session(
    session_id: str,
    request: SessionMigrateRequest,
    auth: dict = Depends(_require_auth),
):
    """Trigger session migration to a target device."""
    try:
        from core.session_migration import migrate_session as migrate_via_canonical_surface

        result = await migrate_via_canonical_surface(
            session_id=session_id,
            target_device=request.target_device_id,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=int(result.get("status_code", 400)),
                detail=result.get(
                    "error",
                    "Migration failed (session not found or canonical path rejected the request)",
                ),
            )
        return {
            "success": True,
            "session_id": session_id,
            "target_device_id": request.target_device_id,
            "history_count": result.get("history_count", 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
