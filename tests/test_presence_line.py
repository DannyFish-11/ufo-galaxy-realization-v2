"""tests/test_presence_line.py — 入口分流（R3）：远端身体发起的请求不外显到桌面。

钉住的性质：

* 判据只读类型化事实（入口、设备注册类型），未知一律按旧行为（宿主）处理；
* 游离会话的相位**照常推进**，但不发 ``phase.*``、不落桌面相位账、不起 tick，只推给发起设备；
* 本机对话逐位不变；
* 游离请求一旦在本机落手就交还桌面，补放的相位序完整；
* 两个开关都能把行为整体 / 按入口退回旧样子；
* 分流模块在热路径守卫 G10 的名单里。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import presence_line
from core.desktop_presence_runtime import DesktopPresenceRuntime, RuntimeSession, TriState
from core.presence_line import attach_to_host, bind_presence_line, decide_presence_line


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(presence_line.PRESENCE_LINE_ENV, raising=False)
    monkeypatch.delenv(presence_line.PRESENCE_LINE_LEGACY_SOURCES_ENV, raising=False)
    monkeypatch.setenv("GALAXY_DEVICE_ID", "desk-host")


def _kinds(mapping: Dict[str, str]):
    return patch.object(presence_line, "registered_device_kind", side_effect=lambda did: mapping.get(did, ""))


@pytest.fixture
def seb_events(monkeypatch) -> List[Dict[str, Any]]:
    seen: List[Dict[str, Any]] = []

    def _record(event_type, source, payload=None, **kwargs):
        seen.append({"type": getattr(event_type, "value", event_type), "payload": payload or {}, **kwargs})

    monkeypatch.setattr("core.state_event_bus.emit", _record)
    return seen


@pytest.fixture
def phase_pushes(monkeypatch) -> List[Dict[str, Any]]:
    pushes: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        "core.cross_device_sync.emit_cross_device_phase_sync", lambda **kwargs: pushes.append(dict(kwargs))
    )
    return pushes


@pytest.fixture
def ledger(monkeypatch) -> List[tuple]:
    rows: List[tuple] = []
    monkeypatch.setattr(
        "core.phase_transition_ledger.record_transition", lambda old, new, **kw: rows.append((old, new)) or True
    )
    return rows


def _phase_events(events: List[Dict[str, Any]]) -> List[str]:
    return [e["type"] for e in events if str(e["type"]).startswith("phase.")]


# ---------------------------------------------------------------------------
# 判据
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", sorted(presence_line.REMOTE_SOURCES))
def test_remote_sources_are_detached(source):
    decision = decide_presence_line(source, "phone-1")
    assert decision.host_bound is False and decision.reason == "remote_source"
    assert decision.origin_device_id == "phone-1"


@pytest.mark.parametrize("source", ["voice", "ambient", "operator", "active_perception"])
def test_host_sources_stay_on_the_desktop_even_with_a_phone_id(source):
    with _kinds({"phone-1": "android"}):
        assert decide_presence_line(source, "phone-1").host_bound is True


@pytest.mark.parametrize(
    "device_id, kind, host_bound",
    [
        (None, "", True),
        ("", "", True),
        ("desk-host", "android", True),  # 本机标识优先于注册类型
        ("local", "", True),
        ("phone-1", "android", False),
        ("iphone", "ios", False),
        ("watch-1", "wear_os", False),
        ("other-pc", "windows", True),  # 另一台 PC 不算远端：宁可漏分，不可错分
        ("browser-tab", "browser", True),
        ("unregistered", "", True),
    ],
)
def test_chat_is_decided_by_the_registered_device_kind(device_id, kind, host_bound):
    with _kinds({device_id or "": kind}):
        assert decide_presence_line("chat", device_id).host_bound is host_bound


def test_registered_device_kind_reads_udm_first(monkeypatch):
    fake_udm = SimpleNamespace(get_device=lambda did: SimpleNamespace(device_type=SimpleNamespace(value="android")))
    monkeypatch.setattr("core.unified.device_manager.get_unified_device_manager", lambda: fake_udm)
    assert presence_line.registered_device_kind("phone-1") == "android"
    assert presence_line.is_remote_device("phone-1") is True


def test_registered_device_kind_falls_back_to_compat_cache_for_watches(monkeypatch):
    monkeypatch.setattr(
        "core.unified.device_manager.get_unified_device_manager",
        lambda: SimpleNamespace(get_device=lambda did: None),
    )
    monkeypatch.setitem(
        __import__("core.routes._shared", fromlist=["registered_devices"]).registered_devices,
        "watch-9",
        {"device_type": "wear_os"},
    )
    assert presence_line.registered_device_kind("watch-9") == "wear_os"


def test_kill_switch_makes_everything_host_bound(monkeypatch):
    monkeypatch.setenv(presence_line.PRESENCE_LINE_ENV, "off")
    decision = decide_presence_line("android_goal_execution", "phone-1")
    assert decision.host_bound is True and decision.reason == "presence_line_off"


def test_per_source_legacy_list(monkeypatch):
    monkeypatch.setenv(presence_line.PRESENCE_LINE_LEGACY_SOURCES_ENV, "wear_voice, android_vision")
    assert decide_presence_line("wear_voice", "w").host_bound is True
    assert decide_presence_line("android_vision", "p").host_bound is True
    assert decide_presence_line("android_goal_execution", "p").host_bound is False


def test_decision_failure_falls_back_to_host():
    session = RuntimeSession(source="chat")
    with patch.object(presence_line, "decide_presence_line", side_effect=RuntimeError("boom")):
        decision = bind_presence_line(session, "chat", "phone-1")
    assert decision.host_bound is True and session.host_bound is True


# ---------------------------------------------------------------------------
# 游离会话的相位推进
# ---------------------------------------------------------------------------


def test_detached_session_keeps_its_phases_but_does_not_surface(seb_events, phase_pushes, ledger):
    session = RuntimeSession(source="android_goal_execution")
    bind_presence_line(session, "android_goal_execution", "phone-1")
    with patch.object(session, "_on_advance_tick") as tick:
        session.advance(TriState.LIMINAL)
        session.advance(TriState.MANIFEST)
        session.advance(TriState.SILENT)

    assert [s for s, _ in session.transitions] == [TriState.LIMINAL, TriState.MANIFEST, TriState.SILENT]
    assert _phase_events(seb_events) == [], "游离会话不该在总线上发 phase.*（桌面外壳订阅的就是它）"
    assert ledger == [], "桌面的相位账记的是桌面这具身体"
    tick.assert_not_called()
    assert [p["target_device_id"] for p in phase_pushes] == ["phone-1"] * 3
    assert [p["new_phase"] for p in phase_pushes] == ["liminal", "manifest", "silent"]


def test_detached_session_still_carries_liminal_content():
    """认知段的阈限内容与预演闸门不受分流影响。"""
    session = RuntimeSession(source="wear_voice")
    bind_presence_line(session, "wear_voice", "watch-1")
    with patch("core.cross_device_sync.emit_cross_device_phase_sync"):
        session.advance(TriState.LIMINAL)
    assert session.liminal_activity == "understanding"


def test_host_session_is_unchanged(seb_events, phase_pushes, ledger):
    session = RuntimeSession(source="chat")
    bind_presence_line(session, "chat", None)
    with patch.object(session, "_on_advance_tick") as tick:
        session.advance(TriState.LIMINAL)
    assert _phase_events(seb_events) == ["phase.liminal"]
    assert ledger == [("silent", "liminal")]
    tick.assert_called_once_with(TriState.LIMINAL)
    assert phase_pushes and "target_device_id" not in phase_pushes[0], "宿主会话照旧广播给所有设备"


# ---------------------------------------------------------------------------
# 落手即归位
# ---------------------------------------------------------------------------


def test_local_actuation_hands_the_request_back_to_the_desktop(seb_events, phase_pushes, ledger):
    session = RuntimeSession(source="android_goal_execution")
    bind_presence_line(session, "android_goal_execution", "phone-1")
    with patch.object(session, "_on_advance_tick"):
        session.advance(TriState.LIMINAL)
        session.advance(TriState.MANIFEST)
        assert _phase_events(seb_events) == []
        assert attach_to_host(session, "hybrid_executor", "") is True
        session.advance(TriState.SILENT)

    assert session.host_bound is True and session.presence_line_reason == "attached:hybrid_executor"
    assert _phase_events(seb_events) == ["phase.liminal", "phase.manifest", "phase.silent"]
    assert ledger == [("silent", "liminal"), ("liminal", "manifest"), ("manifest", "silent")]
    assert attach_to_host(session, "hybrid_executor", "") is False, "归位只发生一次"


def test_attach_during_liminal_keeps_the_deliberation_content(seb_events, phase_pushes, ledger):
    session = RuntimeSession(source="wear_voice")
    bind_presence_line(session, "wear_voice", "watch-1")
    with patch.object(session, "_on_advance_tick"):
        session.advance(TriState.LIMINAL)
        session.enter_liminal_activity("rehearsing", {"candidate_paths": ["A"]})
        attach_to_host(session, "computer_use")
    assert session.tristate is TriState.LIMINAL
    assert session.liminal_activity == "rehearsing" and session.simulation_summary == {"candidate_paths": ["A"]}
    assert _phase_events(seb_events) == ["phase.liminal"]


def test_actuation_on_a_remote_body_does_not_attach(phase_pushes):
    session = RuntimeSession(source="android_goal_execution")
    bind_presence_line(session, "android_goal_execution", "phone-1")
    with _kinds({"phone-2": "android"}):
        assert attach_to_host(session, "hybrid_executor", "phone-2") is False
    assert session.host_bound is False


def test_note_local_actuation_goes_through_the_request_context():
    from core.liminal_activity import bind_runtime_session, note_local_actuation, unbind_runtime_session

    assert note_local_actuation("computer_use") is False, "不在请求里就是空操作"
    session = RuntimeSession(source="android_vision")
    bind_presence_line(session, "android_vision", "phone-1")
    token = bind_runtime_session(session)
    try:
        with patch("core.cross_device_sync.emit_cross_device_phase_sync"), patch.object(session, "_on_advance_tick"):
            session.advance(TriState.LIMINAL)
            assert note_local_actuation("computer_use") is True
    finally:
        unbind_runtime_session(token)
    assert session.host_bound is True


def test_actuation_entry_points_announce_themselves():
    """两个本机落手入口都接了线 —— 缺了任何一个，交还桌面就只在一半路径上生效。"""
    import inspect

    from core import computer_use_loop, hybrid_executor

    assert 'note_local_actuation("computer_use")' in inspect.getsource(computer_use_loop.run_computer_use_task)
    assert 'note_local_actuation("hybrid_executor", device_id)' in inspect.getsource(
        hybrid_executor.HybridExecutionArbiter.execute
    )


# ---------------------------------------------------------------------------
# 端到端：handle_request
# ---------------------------------------------------------------------------


def _run(runtime: DesktopPresenceRuntime, **kwargs) -> Dict[str, Any]:
    async def _process(**_kw):
        return {"success": True, "response": "ok", "metadata": {}}

    with patch("core.openclawd.get_openclawd") as get_clawd:
        clawd = MagicMock()
        clawd.process = AsyncMock(side_effect=_process)
        get_clawd.return_value = clawd
        return asyncio.run(runtime.handle_request(message="帮我查快递", **kwargs))


def test_phone_task_does_not_drive_the_desktop_shell(seb_events, phase_pushes, ledger):
    runtime = DesktopPresenceRuntime()
    mode_before = runtime._presence_state_machine.mode
    with _kinds({"phone-1": "android"}):
        result = _run(runtime, source="chat", device_id="phone-1", entry_mode="cross_device")

    assert result.get("success") is True
    assert _phase_events(seb_events) == []
    assert ledger == []
    assert runtime._presence_state_machine.mode == mode_before
    assert {p["target_device_id"] for p in phase_pushes} == {"phone-1"}
    assert [p["new_phase"] for p in phase_pushes] == ["liminal", "manifest", "silent"]


def test_local_chat_drives_the_desktop_shell_as_before(seb_events, phase_pushes, ledger):
    runtime = DesktopPresenceRuntime()
    _run(runtime, source="chat")
    assert _phase_events(seb_events) == ["phase.liminal", "phase.manifest", "phase.silent"]
    assert [row[1] for row in ledger] == ["liminal", "manifest", "silent"]
    assert all("target_device_id" not in p for p in phase_pushes)


def test_kill_switch_restores_the_old_broadcast(monkeypatch, seb_events, phase_pushes, ledger):
    monkeypatch.setenv(presence_line.PRESENCE_LINE_ENV, "off")
    runtime = DesktopPresenceRuntime()
    _run(runtime, source="android_goal_execution", device_id="phone-1", entry_mode="cross_device")
    assert _phase_events(seb_events) == ["phase.liminal", "phase.manifest", "phase.silent"]
    assert all("target_device_id" not in p for p in phase_pushes)


def test_presence_summary_counts_only_desktop_sessions():
    runtime = DesktopPresenceRuntime()
    detached = runtime._create_session("wear_voice")
    bind_presence_line(detached, "wear_voice", "watch-1")
    detached.tristate = TriState.MANIFEST
    summary = runtime.presence_summary()
    assert summary["dominant_tristate"] == "silent"
    assert summary["active_session_count"] == 0


# ---------------------------------------------------------------------------
# 跨设备推送的目标过滤
# ---------------------------------------------------------------------------


def test_targeted_phase_push_reaches_only_the_origin(monkeypatch):
    from core import cross_device_sync

    sent: List[str] = []

    async def _one(did, dev, msg):
        sent.append(did)
        return True

    bridge = SimpleNamespace(
        _devices={
            "phone-1": SimpleNamespace(websocket=object(), connected=True),
            "phone-2": SimpleNamespace(websocket=object(), connected=True),
        }
    )
    wear_sent: List[str] = []
    conn = SimpleNamespace(
        get_connected_devices=AsyncMock(return_value=["watch-1", "phone-1"]),
        send_to_device=AsyncMock(side_effect=lambda did, msg: wear_sent.append(did)),
    )
    resolved = {
        "gateway.android_bridge.android_bridge": bridge,
        "gateway.websocket_handler.connection_manager": conn,
        "gateway.android.handlers.wearos_sync.is_wearos_device": lambda kind: kind == "wear_os",
    }
    monkeypatch.setattr(cross_device_sync.upper_ports, "resolve", lambda name: resolved[name])
    monkeypatch.setattr(cross_device_sync, "_push_to_one_device", _one)
    monkeypatch.setitem(
        __import__("core.routes._shared", fromlist=["registered_devices"]).registered_devices,
        "watch-1",
        {"device_type": "wear_os"},
    )

    asyncio.run(
        cross_device_sync._async_push_phase_to_all_devices(
            "silent", "liminal", "s", "wear_voice", "t", target_device_id="phone-1"
        )
    )
    assert sent == ["phone-1"] and wear_sent == []

    sent.clear()
    asyncio.run(
        cross_device_sync._async_push_phase_to_all_devices(
            "silent", "liminal", "s", "wear_voice", "t", target_device_id="watch-1"
        )
    )
    assert sent == [] and wear_sent == ["watch-1"]

    wear_sent.clear()
    asyncio.run(cross_device_sync._async_push_phase_to_all_devices("silent", "liminal", "s", "chat", "t"))
    assert sorted(sent) == ["phone-1", "phone-2"] and wear_sent == ["watch-1"], "不带目标时照旧全量广播"


# ---------------------------------------------------------------------------
# 守卫
# ---------------------------------------------------------------------------


def test_presence_line_is_on_the_hot_path_list():
    from core.meta.guards import HOT_PATH_MODULES, direct_meta_imports

    assert "core/presence_line.py" in HOT_PATH_MODULES
    source = open(presence_line.__file__, encoding="utf-8").read()
    assert direct_meta_imports(source) == []
