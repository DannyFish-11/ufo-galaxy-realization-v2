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

import pytest

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


# ── 停本地主脑时只停自己拉起的 Ollama(本地全量两次被打断,查到的) ─────────────────────────────
#
# 原先 ``LocalBrainManager.stop()`` 跑 ``pkill -f ollama``(Windows 上 ``taskkill /IM ollama.exe``):命令行里**任何地方**
# 带 ollama 的进程都被杀 —— 人自己开的 Ollama、打开着 ollama.log 的编辑器,以及命令行里带着
# ``tests/test_local_brain_ollama_readiness.py`` 的那个测试分片(SIGTERM,第 10 轮本地全量两次)。


def _sleeper(*extra: str, new_session: bool = False):
    import subprocess
    import sys

    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", *extra], start_new_session=new_session
    )


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="进程组语义按 POSIX 测")
def test_stopping_the_local_brain_only_stops_the_ollama_it_started():
    from core.local_brain_manager import LocalBrainManager

    bystander = _sleeper("ollama-bystander")  # 命令行里带 ollama 的别人的进程
    ours = _sleeper("serve", new_session=True)  # 像 _start_ollama 那样起在自己的会话里
    try:
        mgr = LocalBrainManager(backend="ollama", ollama_url="http://127.0.0.1:9")
        mgr._ollama_proc = ours
        asyncio.run(mgr.stop())
        assert ours.wait(timeout=15) is not None, "我们拉起的那个要停掉"
        assert bystander.poll() is None, "命令行里带 ollama 的别人的进程不许碰"
        assert mgr._ollama_proc is None
    finally:
        for p in (bystander, ours):
            if p.poll() is None:
                p.kill()


def test_stopping_without_having_started_ollama_kills_nothing(monkeypatch):
    import subprocess

    from core.local_brain_manager import LocalBrainManager

    ran = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    asyncio.run(LocalBrainManager(backend="ollama", ollama_url="http://127.0.0.1:9").stop())
    assert ran == [], "人自己开的 Ollama 不归我们停"


def test_nothing_in_core_or_launcher_kills_by_a_loose_command_line_pattern():
    import re

    hits = []
    for base in ("core", "launcher"):
        for path in sorted((REPO / base).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"""["']pkill["']\s*,\s*["']-f["']""", text):
                hits.append(f"{path.relative_to(REPO)}:{text[: m.start()].count(chr(10)) + 1}")
    assert hits == [], "按 PID / 自己的进程组停,别按命令行里的一个词停:" + ", ".join(hits)
