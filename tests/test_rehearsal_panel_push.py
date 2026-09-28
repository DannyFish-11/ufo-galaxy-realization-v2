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
