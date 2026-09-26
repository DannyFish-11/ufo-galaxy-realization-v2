"""tests/test_agent_runs_apart_from_the_desktop.py — 智能体与桌面三态分开运行，有需要才进。

钉住的性质（规则本体见 tests/test_presence_line.py）：

* 智能体自己发起的工作（定时心跳）不进三态、不朗读；它若在本机落手，照样交还桌面；
* 没带设备号的请求按连接来源判：别的机器 → 不进；本机 → 进；桌面外壳显式声明自己 → 进；
* 回复归发起方：别的设备发起、中途在本机落手的请求，桌面显出它在动手，但回答不在电脑上念；
* 流式对话：不是电脑发起的，不在电脑上边生成边念、不推进桌面实时对话视图；
* ``GET /api/v1/agent/activity`` 列出智能体在处理的全部请求，含不进三态的。
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import presence_line
from core.desktop_presence_runtime import DesktopPresenceRuntime
from core.presence_line import decide_presence_line, is_local_address


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("GALAXY_DEVICE_ID", "desk-host")
    monkeypatch.setattr(presence_line, "_registered_local_ids", set())


@pytest.fixture
def seb_events(monkeypatch) -> List[str]:
    seen: List[str] = []
    monkeypatch.setattr(
        "core.state_event_bus.emit",
        lambda event_type, source, payload=None, **kw: seen.append(str(getattr(event_type, "value", event_type))),
    )
    return seen


@pytest.fixture
def spoken(monkeypatch) -> List[str]:
    said: List[str] = []
    monkeypatch.setattr("core.speech_output.speak_response", lambda text, source="": said.append(source))
    return said


@pytest.fixture(autouse=True)
def _quiet_side_channels(monkeypatch):
    monkeypatch.setattr("core.phase_transition_ledger.record_transition", lambda *a, **k: True)
    monkeypatch.setattr("core.cross_device_sync.emit_cross_device_phase_sync", lambda **kw: None)


def _phases(events: List[str]) -> List[str]:
    return [e for e in events if e.startswith("phase.")]


# ---------------------------------------------------------------------------
# 请求来源
# ---------------------------------------------------------------------------


def test_local_address_is_decided_by_whether_this_machine_can_bind_it():
    assert is_local_address("127.0.0.1") is True
    assert is_local_address("::1") is True
    assert is_local_address("::ffff:127.0.0.1") is True
    assert is_local_address("192.0.2.9") is False, "TEST-NET 地址不可能是本机网卡"
    assert is_local_address("testclient") is None, "不是 IP：说不清，不下结论"
    own = socket.gethostbyname(socket.gethostname())
    assert is_local_address(own) is True, "本机网卡上的地址也是本机"


@pytest.mark.parametrize(
    "device_id, client_host, client_surface, host_bound, reason",
    [
        (None, "192.0.2.9", None, False, "other_address"),  # 手机浏览器，没带设备号
        (None, "127.0.0.1", None, True, "no_device"),
        (None, "testclient", None, True, "no_device"),
        (None, "192.0.2.9", "desktop_shell", True, "desktop_shell"),  # 容器部署里的桌面外壳
        ("phone-1", "127.0.0.1", None, False, "other_device"),  # 设备号优先于地址
        ("desk-host", "192.0.2.9", None, True, "desktop_origin"),
    ],
)
def test_requests_without_a_device_id_are_decided_by_where_they_come_from(
    device_id, client_host, client_surface, host_bound, reason
):
    decision = decide_presence_line("chat", device_id, client_host=client_host, client_surface=client_surface)
    assert (decision.host_bound, decision.reason) == (host_bound, reason)


def test_control_surfaces_are_not_affected_by_the_client_address():
    assert decide_presence_line("operator", "phone-1", client_host="192.0.2.9").host_bound is True


# ---------------------------------------------------------------------------
# 智能体自己发起的工作
# ---------------------------------------------------------------------------


def test_autonomous_work_stays_out_of_the_tri_state(seb_events):
    runtime = DesktopPresenceRuntime()

    async def _work():
        async with runtime.autonomous_session("heartbeat") as session:
            assert session.host_bound is False and session.desktop_originated is False
            assert session.origin_device_id == "" and session.presence_line_reason == "agent_autonomous"
            snapshot = runtime.agent_activity()
            assert [r["source"] for r in snapshot["sessions"]] == ["heartbeat"]
            assert snapshot["outside_tri_state"] == 1 and snapshot["in_tri_state"] == 0
            return session

    session = asyncio.run(_work())
    assert _phases(seb_events) == []
    assert [s.value for s, _ in session.transitions] == ["liminal", "manifest", "silent"], "自己的生命周期照走"
    assert runtime.agent_activity()["sessions"] == [], "结束即摘除"


def test_autonomous_work_enters_the_tri_state_when_it_acts_on_this_machine(seb_events):
    from core.liminal_activity import note_local_actuation

    runtime = DesktopPresenceRuntime()

    async def _work():
        async with runtime.autonomous_session("heartbeat") as session:
            with patch.object(session, "_on_advance_tick"):
                assert note_local_actuation("computer_use") is True
            assert runtime.agent_activity()["in_tri_state"] == 1
            return session

    session = asyncio.run(_work())
    assert _phases(seb_events) == ["phase.liminal", "phase.manifest", "phase.silent"], "落手后桌面补放并收尾"
    assert session.desktop_originated is False


def test_heartbeat_runs_inside_an_autonomous_session():
    from core.liminal_activity import current_runtime_session
    from core.openclawd_heartbeat import HeartbeatScheduler

    seen: Dict[str, Any] = {}

    async def _process(**kwargs):
        session = current_runtime_session()
        seen.update(source=session.source, host_bound=session.host_bound)
        return {"response": "HEARTBEAT_OK", "success": True}

    clawd = MagicMock()
    clawd.process = AsyncMock(side_effect=_process)
    scheduler = HeartbeatScheduler(openclawd=clawd)
    with patch("core.openclawd_heartbeat.load_heartbeat_tasks", return_value="- 检查磁盘"):
        asyncio.run(scheduler._run_cycle())
    assert seen == {"source": "heartbeat", "host_bound": False}


# ---------------------------------------------------------------------------
# 回复归发起方
# ---------------------------------------------------------------------------


def _run(runtime: DesktopPresenceRuntime, process, **kwargs) -> Dict[str, Any]:
    with patch("core.openclawd.get_openclawd") as get_clawd:
        clawd = MagicMock()
        clawd.process = AsyncMock(side_effect=process)
        get_clawd.return_value = clawd
        return asyncio.run(runtime.handle_request(message="帮我点一下电脑上的按钮", **kwargs))


def test_a_phone_request_that_acts_here_shows_on_the_desktop_but_answers_the_phone(seb_events, spoken):
    from core.liminal_activity import current_runtime_session, note_local_actuation

    async def _process(**_kw):
        with patch.object(current_runtime_session(), "_on_advance_tick"):
            note_local_actuation("computer_use")
        return {"success": True, "response": "点好了", "metadata": {}}

    runtime = DesktopPresenceRuntime()
    result = _run(runtime, _process, source="chat", device_id="phone-1")
    assert result.get("success") is True
    assert "phase.liminal" in _phases(seb_events), "在本机动手，桌面要显出来"
    assert spoken == [], "回答回到手机，不在电脑上念"


def test_a_request_from_another_address_is_not_spoken_here(seb_events, spoken):
    async def _process(**_kw):
        return {"success": True, "response": "ok", "metadata": {}}

    runtime = DesktopPresenceRuntime()
    _run(runtime, _process, source="chat", client_host="192.0.2.9")
    assert _phases(seb_events) == [] and spoken == []
    _run(runtime, _process, source="chat", client_host="192.0.2.9", client_surface="desktop_shell")
    assert _phases(seb_events) == ["phase.liminal", "phase.manifest", "phase.silent"] and spoken == ["chat"]


def test_client_origin_is_not_forwarded_to_the_agent():
    runtime = DesktopPresenceRuntime()
    seen: Dict[str, Any] = {}

    async def _process(**kw):
        seen.update(kw)
        return {"success": True, "response": "ok", "metadata": {}}

    _run(runtime, _process, source="chat", client_host="127.0.0.1", client_surface="desktop_shell")
    assert seen, "请求到了智能体"
    assert "client_host" not in seen and "client_surface" not in seen


# ---------------------------------------------------------------------------
# HTTP 入口
# ---------------------------------------------------------------------------


def _chat_app():
    from fastapi import FastAPI

    from core.routes.chat import create_router

    app = FastAPI()
    app.include_router(create_router())
    return app


@pytest.mark.parametrize(
    "client, body, on_desktop",
    [
        (("192.0.2.9", 5000), {"message": "hi"}, False),
        (("127.0.0.1", 5000), {"message": "hi"}, True),
        (("192.0.2.9", 5000), {"message": "hi", "client_surface": "desktop_shell"}, True),
        (("127.0.0.1", 5000), {"message": "hi", "device_id": "phone-1"}, False),
    ],
)
def test_stream_only_speaks_and_mirrors_desktop_requests(monkeypatch, client, body, on_desktop):
    from fastapi.testclient import TestClient

    handle = AsyncMock(return_value={"success": True, "response": "ok"})
    speech = MagicMock(return_value=None)
    mirrored: List[str] = []
    monkeypatch.setattr("core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request", handle)
    monkeypatch.setattr("core.speech_output.begin_incremental_speech", speech)
    monkeypatch.setattr("core.lumiv_websocket_bridge.emit_conversation", lambda role, *a, **k: mirrored.append(role))

    resp = TestClient(_chat_app(), client=client).post("/api/v1/chat/stream", json=body)
    assert resp.status_code == 200
    assert speech.called is on_desktop, "只在电脑发起时边生成边念"
    assert ("user" in mirrored) is on_desktop, "只把电脑上的对话推进桌面实时视图"
    kwargs = handle.await_args.kwargs
    assert kwargs["client_host"] == client[0] and kwargs["client_surface"] == body.get("client_surface")


def test_plain_chat_passes_the_client_origin(monkeypatch):
    from fastapi.testclient import TestClient

    handle = AsyncMock(return_value={"success": True, "response": "ok"})
    monkeypatch.setattr("core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request", handle)
    TestClient(_chat_app(), client=("192.0.2.9", 5000)).post("/api/v1/chat", json={"message": "hi"})
    assert handle.await_args.kwargs["client_host"] == "192.0.2.9"


def test_the_desktop_shell_declares_itself():
    from pathlib import Path

    main = (Path(__file__).resolve().parents[1] / "electron/renderer/panel/src/main.ts").read_text(encoding="utf-8")
    assert "const IN_DESKTOP_SHELL = Boolean((window as { galaxyShell?: unknown }).galaxyShell);" in main
    assert "client_surface: 'desktop_shell'" in main


def test_activity_endpoint_lists_requests_outside_the_tri_state(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes import system

    runtime = DesktopPresenceRuntime()
    monkeypatch.setattr("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: runtime)
    detached = runtime._create_session("participant_task")
    presence_line.bind_presence_line(detached, "participant_task", "ipad-1")
    attached = runtime._create_session("chat")
    presence_line.bind_presence_line(attached, "chat", None)

    app = FastAPI()
    app.include_router(system.create_router())
    body = TestClient(app).get("/api/v1/agent/activity").json()
    rows = {r["source"]: r for r in body["sessions"]}
    assert (body["in_tri_state"], body["outside_tri_state"]) == (1, 1)
    assert (
        rows["participant_task"]["origin_device_id"] == "ipad-1" and rows["participant_task"]["in_tri_state"] is False
    )
    assert rows["chat"]["desktop_originated"] is True and rows["chat"]["phase"] == "silent"


def test_activity_endpoint_requires_api_auth():
    """它挂在 system 路由下，而 system 路由在权威组装里整组套了 API 鉴权。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "core/api_routes.py").read_text(encoding="utf-8")
    assert "system.create_router(service_manager=service_manager, config=config), dependencies=_auth_deps" in src
