"""tests/test_presence_line.py — 入口分流：只有电脑这边发起的请求进桌面三态。

钉住的性质：

* 判据只读类型化事实（入口、发起设备标识）：本机感官与桌面控制面进；其余入口看发起设备，
  没带或是本机自己的标识才进 —— 别的设备不看类型、不看是否登记，一律不进；
* 电脑发起的跨设备 / 混合任务（带目标设备、操作员派发给手机）照样进；
* 没有开关：环境变量改不了这条规则；
* 不进的会话相位**照常推进**，但不发 ``phase.*``、不落桌面相位账、不起 tick、不在电脑上
  朗读回复，只推给发起设备；
* 本机对话逐位不变；
* 不进的请求一旦在本机落手就交还桌面，补放的相位序完整；落在别的设备上不交还；
* 分流模块在热路径守卫 G10 的名单里。
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import presence_line
from core.desktop_presence_runtime import DesktopPresenceRuntime, RuntimeSession, TriState
from core.presence_line import attach_to_host, bind_presence_line, decide_presence_line


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("GALAXY_DEVICE_ID", "desk-host")
    monkeypatch.setattr(presence_line, "_registered_local_ids", set())


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


@pytest.fixture
def spoken(monkeypatch) -> List[str]:
    said: List[str] = []
    monkeypatch.setattr("core.speech_output.speak_response", lambda text, source="": said.append(source))
    return said


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


@pytest.mark.parametrize("source", sorted(presence_line.LOCAL_BODY_SOURCES))
def test_local_senses_are_the_desktop(source):
    assert decide_presence_line(source, None).host_bound is True


@pytest.mark.parametrize("source", sorted(presence_line.DESKTOP_CONTROL_SOURCES))
def test_desktop_control_surfaces_stay_on_the_desktop_even_when_the_id_is_a_target(source):
    """操作员把任务派给手机时带的 device_id 是**目标**：发起方仍是电脑。"""
    decision = decide_presence_line(source, "phone-1")
    assert decision.host_bound is True and decision.reason == "desktop_control_source"


@pytest.mark.parametrize(
    "device_id, host_bound",
    [
        (None, True),  # 桌面面板发请求不带 device_id
        ("", True),
        ("desk-host", True),  # 本机标识（GALAXY_DEVICE_ID / 主机名）
        ("local", True),
        ("phone-1", False),
        ("iphone", False),
        ("watch-1", False),
        ("other-pc", False),  # 另一台电脑也是别的设备
        ("ipad-1", False),
        ("linux-box", False),
        ("unregistered", False),  # 不看是否登记
    ],
)
def test_other_entries_are_decided_by_who_started_them(device_id, host_bound):
    assert decide_presence_line("chat", device_id).host_bound is host_bound


def test_the_device_type_does_not_matter(monkeypatch):
    """登记成什么类型都一样：不是这台电脑就不进。"""
    fake_udm = SimpleNamespace(get_device=lambda did: SimpleNamespace(device_type=SimpleNamespace(value="windows")))
    monkeypatch.setattr("core.unified.device_manager.get_unified_device_manager", lambda: fake_udm)
    assert decide_presence_line("chat", "other-pc").host_bound is False


def test_the_desktop_runtime_identity_counts_as_this_machine():
    """在场运行时开跨设备时铸的 ``galaxy_desktop_*`` 就是这台电脑：带着它来的请求进三态。"""
    runtime = DesktopPresenceRuntime()
    runtime._device_id = "galaxy_desktop_box_1234abcd"
    kwargs = {"client_host": "192.0.2.9", "client_surface": None, "other": 1}
    session = runtime._create_bound_session("chat", "galaxy_desktop_box_1234abcd", kwargs)
    assert session.host_bound is True and session.presence_line_reason == "desktop_origin"
    assert kwargs == {"other": 1}, "分流参数在建会话时取走，不往下传给智能体"
    assert decide_presence_line("chat", "galaxy_desktop_box_1234abcd").host_bound is True


def test_there_is_no_switch(monkeypatch):
    """这是架构，不是偏好：曾经的两个回退开关设了也没用，模块根本不读环境变量。"""
    monkeypatch.setenv("GALAXY_PRESENCE_LINE", "off")
    monkeypatch.setenv("GALAXY_PRESENCE_LINE_LEGACY_SOURCES", "wear_voice,chat")
    assert decide_presence_line("wear_voice", "watch-1").host_bound is False
    assert decide_presence_line("chat", "phone-1").host_bound is False
    source = inspect.getsource(presence_line)
    assert "os.environ" not in source and "getenv" not in source


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


@pytest.mark.parametrize("target", ["phone-2", "linux-box", "other-pc"])
def test_actuation_on_another_device_does_not_attach(phase_pushes, target):
    session = RuntimeSession(source="android_goal_execution")
    bind_presence_line(session, "android_goal_execution", "phone-1")
    assert attach_to_host(session, "hybrid_executor", target) is False
    assert session.host_bound is False


def test_actuation_on_this_machine_by_name_attaches(phase_pushes):
    session = RuntimeSession(source="participant_task")
    bind_presence_line(session, "participant_task", "ipad-1")
    with patch.object(session, "_on_advance_tick"):
        assert attach_to_host(session, "hybrid_executor", "local") is True


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
    """交还桌面挂在 ``acting()`` 上：两个本机落手入口都进它，缺了任何一个就只在一半路径上生效。"""
    import inspect

    from core import computer_use_loop, hybrid_executor, liminal_activity

    assert "note_local_actuation(reason)" in inspect.getsource(liminal_activity.acting)
    assert '_acting("computer_use")' in inspect.getsource(computer_use_loop.ComputerUseLoop.run)
    assert '_acting("hybrid_executor") if on_this_machine' in inspect.getsource(
        hybrid_executor.HybridExecutionArbiter.execute
    )


def test_acting_hands_a_detached_request_to_the_desktop_before_marking_it(seb_events, phase_pushes, ledger):
    from core.liminal_activity import acting, bind_runtime_session, unbind_runtime_session

    session = RuntimeSession(source="participant_task")
    bind_presence_line(session, "participant_task", "ipad-1")
    order: List[str] = []
    token = bind_runtime_session(session)
    try:
        with (
            patch.object(session, "_on_advance_tick"),
            patch.object(session, "enter_acting", side_effect=lambda r: order.append(f"acting:{session.host_bound}")),
            patch.object(session, "exit_acting"),
        ):
            with acting("computer_use") as entered:
                assert entered is True
    finally:
        unbind_runtime_session(token)
    assert order == ["acting:True"], "先交还桌面，再登记在动手"
    assert _phase_events(seb_events) == ["phase.liminal"]


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source": "chat", "device_id": "phone-1", "entry_mode": "cross_device"},
        {"source": "chat", "device_id": "linux-box"},  # 通用接入的参与方、未登记设备同样不进
        {"source": "participant_task", "device_id": "ipad-1"},
        {"source": "wear_voice", "device_id": "watch-1"},
    ],
)
def test_other_devices_do_not_drive_the_desktop(seb_events, phase_pushes, ledger, spoken, kwargs):
    runtime = DesktopPresenceRuntime()
    mode_before = runtime._presence_state_machine.mode
    result = _run(runtime, **kwargs)

    assert result.get("success") is True, "不进三态不等于不处理：请求照样交给智能体"
    assert _phase_events(seb_events) == []
    assert ledger == []
    assert runtime._presence_state_machine.mode == mode_before
    assert spoken == [], "别的设备发起的请求不该在电脑上念回复"
    assert {p["target_device_id"] for p in phase_pushes} == {kwargs["device_id"]}
    assert [p["new_phase"] for p in phase_pushes] == ["liminal", "manifest", "silent"]


def test_local_chat_drives_the_desktop_shell_as_before(seb_events, phase_pushes, ledger, spoken):
    runtime = DesktopPresenceRuntime()
    _run(runtime, source="chat")
    assert _phase_events(seb_events) == ["phase.liminal", "phase.manifest", "phase.silent"]
    assert [row[1] for row in ledger] == ["liminal", "manifest", "silent"]
    assert all("target_device_id" not in p for p in phase_pushes)
    assert spoken == ["chat"]


@pytest.mark.parametrize(
    "kwargs",
    [
        # 桌面面板发起的跨设备：不带 device_id，目标走 target_device / entry_mode
        {"source": "chat", "entry_mode": "cross_device", "target_device": "phone-1"},
        {"source": "chat", "entry_mode": "hybrid"},
        # 操作员把任务派给手机：device_id 是目标
        {"source": "operator", "device_id": "phone-1", "entry_mode": "cross_device"},
    ],
)
def test_cross_device_started_on_the_desktop_goes_through_the_tri_state(seb_events, phase_pushes, ledger, kwargs):
    runtime = DesktopPresenceRuntime()
    _run(runtime, **kwargs)
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
