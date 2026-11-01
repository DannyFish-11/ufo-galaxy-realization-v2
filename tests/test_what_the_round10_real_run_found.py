"""第 10 轮真跑(假模型 + 真后端 + 全接口扫描)从日志里收的两处。

* ``Exception suppressed: TASK_SUCCEEDED`` 每次节点调用成功都记一条:反馈环发「成功」事件用的是
  ``StateEventType.TASK_SUCCEEDED`` —— 枚举里没有这一项(成功叫 ``TASK_DONE``),AttributeError 被吞,
  **每一次成功的反馈事件都没发出去**,只有失败的发得出去。这里顺手把「代码里点名的事件类型都真有」扫一遍。
* ``[LauncherAdapter] FAILED to start Node_58_ModelRouter``:节点进程活着、两秒后就在答话,只是健康检查没在
  5 秒内就绪 —— 启动器自己已经归类为 ``slow_start``(慢不是故障),适配器却照报「FAILED」。
"""

from __future__ import annotations

import ast
import asyncio
import logging
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_a_successful_feedback_event_is_really_emitted(monkeypatch, tmp_path):
    import core.state_event_bus as bus
    from core.feedback_loop import FeedbackEntry, FeedbackLoop

    sent = []
    monkeypatch.setattr(bus, "emit", lambda event_type, **kw: sent.append(event_type))
    loop = FeedbackLoop(path=tmp_path / "feedback.json")
    loop._emit_feedback_event(FeedbackEntry(task_id="t1", device_id="d", action="now", success=True, duration_ms=3))
    loop._emit_feedback_event(FeedbackEntry(task_id="t2", device_id="d", action="now", success=False, duration_ms=3))
    assert sent == [bus.StateEventType.TASK_DONE, bus.StateEventType.TASK_FAILED]


def test_every_named_state_event_type_exists():
    """``StateEventType.X`` 写错了不会在导入时报错,只会在那一行跑到时抛、然后被 ``except`` 吞掉 —— 全仓扫一遍。"""
    from core.state_event_bus import StateEventType

    known = set(StateEventType.__members__)
    missing = []
    for path in sorted((REPO / "core").rglob("*.py")) + sorted((REPO / "galaxy_gateway").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "StateEventType"
                and node.attr not in known
                and not node.attr.startswith("_")
                and node.attr not in ("__members__",)
            ):
                missing.append(f"{path.relative_to(REPO)}:{node.lineno} StateEventType.{node.attr}")
    assert missing == []


def test_a_slow_starting_node_is_not_reported_as_failed(caplog):
    from launcher.launcher_adapter import AdapterMode, LauncherAdapter

    class Launcher:
        async def start_node(self, name):
            return False

        def failure_reason(self, name):
            return "slow_start"

    adapter = LauncherAdapter(Launcher(), mode=AdapterMode.FULL)
    with caplog.at_level(logging.INFO, logger="launcher.launcher_adapter"):
        got = asyncio.run(
            adapter._maybe_start_node(node_name="Node_58_ModelRouter", device_type=None, transport=None, decision=None)
        )
    assert got is None
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "还在起来" in text and "FAILED" not in text


def test_a_node_that_really_did_not_start_is_still_reported(caplog):
    from launcher.launcher_adapter import AdapterMode, LauncherAdapter

    class Launcher:
        async def start_node(self, name):
            return False

        def failure_reason(self, name):
            return "import"

    adapter = LauncherAdapter(Launcher(), mode=AdapterMode.FULL)
    with caplog.at_level(logging.INFO):
        asyncio.run(adapter._maybe_start_node(node_name="Node_X", device_type=None, transport=None, decision=None))
    assert "FAILED to start Node_X" in " ".join(r.getMessage() for r in caplog.records)
