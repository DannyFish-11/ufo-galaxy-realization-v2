from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeCommandRouter:
    def __init__(self) -> None:
        self.envelopes = []

    async def route_envelope(self, envelope):
        self.envelopes.append(envelope)
        return {
            "success": True,
            "request_id": envelope.metadata.get("request_id", envelope.task_id),
            "task_id": envelope.task_id,
            "trace_id": envelope.trace_id,
            "result": {"echo": envelope.tool_name},
        }

    async def get_result(self, request_id: str):  # pragma: no cover - compatibility stub
        return None

    async def cancel(self, request_id: str):  # pragma: no cover - compatibility stub
        return False

    def get_stats(self):  # pragma: no cover - compatibility stub
        return {}

    def set_executor(self, executor):  # pragma: no cover - compatibility stub
        self._executor = executor


def _make_client(monkeypatch):
    from core.routes import command as command_routes
    import core.command_router as command_router_mod

    fake_router = _FakeCommandRouter()
    monkeypatch.setattr(command_router_mod, "get_command_router", lambda **_: fake_router)

    app = FastAPI()
    app.include_router(command_routes.create_router())
    return TestClient(app), fake_router


def test_unified_command_routes_through_route_envelope(monkeypatch):
    client, fake_router = _make_client(monkeypatch)

    response = client.post(
        "/api/v1/command/unified",
        json={
            "command": "ping",
            "targets": ["device-a"],
            "mode": "sync",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert len(fake_router.envelopes) == 1
    envelope = fake_router.envelopes[0]
    assert envelope.tool_name == "ping"
    assert envelope.targets == ["device-a"]


def test_unified_command_marks_multi_target_as_cross_device(monkeypatch):
    client, fake_router = _make_client(monkeypatch)

    response = client.post(
        "/api/v1/command/unified",
        json={
            "command": "ping",
            "targets": ["device-a", "device-b"],
            "mode": "sync",
        },
    )

    assert response.status_code == 200
    assert len(fake_router.envelopes) == 1
    envelope = fake_router.envelopes[0]
    assert envelope.metadata.get("cross_device") == "true"
