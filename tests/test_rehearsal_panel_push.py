"""阈限态推演过程推到面板（WS ``type="rehearsal"``）。

以前 ``core/liminal_rehearsal.py`` 的文档说「每步推到面板,推演过程可见」，实际只发到 StateEventBus；
面板桥对 ``skill.*`` 只安排一次设备清单推送，步骤内容从没到过面板，面板也没有地方画它。
这组测试钉住补上的那一段：后端推什么、不推什么；面板认这一帧、并且把「模拟」说出来。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core import liminal_rehearsal
from core.rehearsal_panel_push import REHEARSAL_STEPS, push_rehearsal_step, rehearsal_frame

_PANEL = Path(__file__).resolve().parent.parent / "electron" / "renderer" / "panel"


def test_frame_carries_only_typed_truncated_fields() -> None:
    frame = rehearsal_frame(
        "tool_simulated",
        {"attempt": 2, "tool": "send_mail", "simulated": True, "args": {"to": "x@y"}, "response": {"secret": 1}},
    )
    assert frame == {
        "type": "rehearsal",
        "payload": {"step": "tool_simulated", "simulated": True, "attempt": 2, "tool": "send_mail"},
    }, "工具参数与模拟响应不推"

    long = rehearsal_frame("attempt_failed", {"attempt": 1, "feedback": "x" * 500})
    assert len(long["payload"]["feedback"]) == 200


def test_read_only_passthrough_is_marked_not_simulated() -> None:
    assert rehearsal_frame("tool_simulated", {"tool": "read_file", "simulated": False})["payload"]["simulated"] is False
    assert rehearsal_frame("attempt_start", {"attempt": 1})["payload"]["simulated"] is True


def test_unknown_step_is_not_pushed() -> None:
    assert rehearsal_frame("something_else", {}) is None
    assert set(REHEARSAL_STEPS) == {
        "attempt_start",
        "validation_reject",
        "tool_simulated",
        "attempt_success",
        "attempt_failed",
    }


def test_emit_pushes_a_frame_on_the_running_loop() -> None:
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge

    bridge = GalaxyPresenceBridge.get_instance()
    sent = AsyncMock()

    async def _main() -> None:
        liminal_rehearsal._emit_rehearsal_event("tool_simulated", {"attempt": 1, "tool": "search", "simulated": True})
        await asyncio.sleep(0.01)

    with patch.object(bridge, "_ws_broadcast", sent):
        asyncio.run(_main())
    sent.assert_awaited_once_with(
        {"type": "rehearsal", "payload": {"step": "tool_simulated", "simulated": True, "attempt": 1, "tool": "search"}}
    )


def _frames_pushed_for(source: str, device_id, *, attach_before_emit: bool = False) -> int:
    """在一个真的 RuntimeSession（按入口分流判过）里推一步预演，数推到桌面面板的帧。"""
    from core.desktop_presence_runtime import RuntimeSession, TriState
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge
    from core.presence_line import attach_to_host, bind_presence_line

    bridge = GalaxyPresenceBridge.get_instance()
    sent = AsyncMock()

    async def _main() -> None:
        session = RuntimeSession(source=source)
        bind_presence_line(session, source, device_id)
        with patch("core.cross_device_sync.emit_cross_device_phase_sync"):
            session.advance(TriState.LIMINAL)
        if attach_before_emit:
            assert attach_to_host(session, "computer_use", "local")
        token = bind_runtime_session(session)
        try:
            liminal_rehearsal._emit_rehearsal_event("attempt_start", {"attempt": 1, "task": "关灯"})
            await asyncio.sleep(0.01)
        finally:
            unbind_runtime_session(token)

    with patch.object(bridge, "_ws_broadcast", sent):
        asyncio.run(_main())
    return sent.await_count


def test_a_request_from_another_device_is_deliberated_but_not_drawn_on_the_desktop(monkeypatch) -> None:
    """预演是阈限态的表达，只属于电脑发起的请求。手机说一句话，电脑面板上不该演它的推演。"""
    monkeypatch.setenv("GALAXY_DEVICE_ID", "desk-host")
    assert _frames_pushed_for("android_goal_execution", "phone-1") == 0
    assert _frames_pushed_for("wear_voice", "watch-1") == 0
    assert _frames_pushed_for("chat", "tablet-9") == 0  # 带了别的设备号的普通对话
    assert _frames_pushed_for("participant_task", "ipad-1") == 0


def test_a_request_from_the_computer_is_still_drawn(monkeypatch) -> None:
    monkeypatch.setenv("GALAXY_DEVICE_ID", "desk-host")
    assert _frames_pushed_for("chat", None) == 1
    assert _frames_pushed_for("voice", None) == 1
    assert _frames_pushed_for("operator", "phone-1") == 1  # 操作员面板带的是目标设备号，发起方仍是桌面


def test_a_request_that_starts_acting_here_comes_back_to_the_desktop(monkeypatch) -> None:
    """别的设备发起、中途在本机落手 —— 桌面成了在做事的那具身体（与相位同一条规则），之后的步骤照常推。"""
    monkeypatch.setenv("GALAXY_DEVICE_ID", "desk-host")
    assert _frames_pushed_for("android_goal_execution", "phone-1", attach_before_emit=True) == 1


def test_no_loop_means_no_push_and_no_error() -> None:
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge

    sent = AsyncMock()
    with patch.object(GalaxyPresenceBridge.get_instance(), "_ws_broadcast", sent):
        push_rehearsal_step("attempt_start", {"attempt": 1})
    sent.assert_not_called()


def test_panel_consumes_the_frame_and_says_simulated() -> None:
    transport = (_PANEL / "src" / "transport.ts").read_text(encoding="utf-8")
    assert "m['type'] === 'rehearsal'" in transport and "onRehearsal" in transport
    ui = (_PANEL / "src" / "ui" / "rehearsal.ts").read_text(encoding="utf-8")
    assert "模拟 ${s.tool}" in ui and "真查了 ${s.tool}" in ui, "每一行都要说清它是不是真的"
    main = (_PANEL / "src" / "main.ts").read_text(encoding="utf-8")
    assert "onRehearsal:" in main and "rehearsal.root" in main
