from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_canonical_session_migration_helper_updates_session_manager_state() -> None:
    from core.routes.sessions import migrate_session_via_canonical_manager
    from core.session_manager import Session

    session = Session(id="session_1", user_id="u1", devices=["phone_1"], active_device="phone_1")
    manager = MagicMock()
    manager.get_session.return_value = session
    manager.get_full_history.return_value = [{"role": "user", "content": "hello"}]
    manager._persist_state = MagicMock()

    ws = MagicMock()
    ws.send_to_device = AsyncMock(return_value=True)

    result = await migrate_session_via_canonical_manager(
        session_id="session_1",
        source_device="phone_1",
        target_device="desktop_1",
        context_override={"cursor": "keep"},
        session_manager=manager,
        ws_connection_manager=ws,
    )

    assert result["success"] is True
    assert session.active_device == "desktop_1"
    assert "desktop_1" in session.devices
    assert session.metadata["migration_context"]["cursor"] == "keep"
    assert ws.send_to_device.await_count == 2


@pytest.mark.asyncio
async def test_gateway_session_route_uses_canonical_helper() -> None:
    module_path = (
        Path(__file__).resolve().parent.parent
        / "galaxy_gateway"
        / "routes"
        / "sessions.py"
    )
    spec = importlib.util.spec_from_file_location("gateway_sessions_module", module_path)
    assert spec and spec.loader
    gateway_sessions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gateway_sessions)

    fake_result = {"success": True, "history_count": 3}
    with pytest.MonkeyPatch.context() as mp:
        async def _fake_migrate_session_via_canonical_manager(**kwargs):
            return dict(fake_result)

        mp.setattr(
            "core.routes.sessions.migrate_session_via_canonical_manager",
            _fake_migrate_session_via_canonical_manager,
        )
        response = await gateway_sessions.migrate_session(
            "session_2",
            gateway_sessions.SessionMigrateRequest(target_device_id="desktop_2"),
            auth={"authenticated": True},
        )

    assert response["success"] is True
    assert response["history_count"] == 3
