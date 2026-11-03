"""开放问题才猜:猜要说出来、事后去核、记在账上,算得出它说「可能」的时候有几成是对的(第六期)。

docs/GROUNDED_AGENT_DESIGN.md §4。账本(``core/conjecture_ledger.py``)只给人看,**不进决策路径**。
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from core import conjecture_ledger as ledger
from core import live_check_late as late

REPO = Path(__file__).resolve().parent.parent


def test_the_ledger_lives_in_the_data_dir():
    assert os.path.abspath(ledger.ledger_path()).startswith(os.path.abspath(os.environ["GALAXY_DATA_DIR"]))


def test_said_then_settled_then_counted():
    before = ledger.calibration()
    a = ledger.record("我猜明天会下雨。", session_id="s")
    b = ledger.record("它可能是 2019 年发布的。", session_id="s")
    c = ledger.record("大概有 300 人。", session_id="s")
    ledger.settle(a, "supported", source="https://w.example", judge="other")
    ledger.settle(b, "refuted", note="是 2020 年", source="https://w.example", judge="other")
    after = ledger.calibration()
    assert after["said"] - before["said"] == 3
    assert after["supported"] - before["supported"] == 1 and after["refuted"] - before["refuted"] == 1
    assert after["open"] - before["open"] == 1
    rows = {r["id"]: r for r in ledger.entries()}
    assert rows[b]["verdict"] == "refuted" and rows[b]["note"] == "是 2020 年"
    assert rows[c]["verdict"] is None


def test_no_verdict_means_no_rate():
    """一条结论都没有时,准确率是 null —— 不编一个数。"""
    open(ledger.ledger_path(), "w").close()
    ledger.record("我猜是这样。")
    assert ledger.calibration()["hit_rate"] is None


def test_the_ledger_is_trimmed():
    open(ledger.ledger_path(), "w").close()
    for i in range(ledger.MAX_LINES + 5):
        ledger._append({"event": "said", "id": f"cj_{i}", "at": i, "text": "x"})
    with open(ledger.ledger_path(), encoding="utf-8") as fh:
        assert sum(1 for _ in fh) == ledger.MAX_LINES


def test_a_spoken_guess_is_recorded_and_checked(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "k")

    async def fake_search(query):
        return [{"title": "t", "url": "https://w.example/1", "text": "x"}], ""

    class _Cfg:
        def is_available(self):
            return True

    class _Router:
        providers = {"answerer": _Cfg(), "other": _Cfg()}
        adapters = {"answerer": 1, "other": 1}
        call_history = [{"provider": "answerer", "timestamp": time.time()}]

        async def chat(self, messages, provider=None, **kw):
            from types import SimpleNamespace

            return SimpleNamespace(
                content='{"verdict": "refuted", "correct": "是 2020 年", "source": "https://w.example/1"}'
            )

    monkeypatch.setattr(late, "_search", fake_search)
    monkeypatch.setattr(late, "_router", lambda: _Router())
    asyncio.run(late.check_turn("它可能是 2019 年发布的。", session_id="s9", started_at=time.time() - 5))
    row = next(r for r in ledger.entries() if r.get("session_id") == "s9")
    assert (row["verdict"], row["judge"], row["source"]) == ("refuted", "other", "https://w.example/1")


def test_an_unchecked_guess_stays_open(monkeypatch):
    """没配联网搜索时猜想记下、但留在「没核」—— 不把「没去核」记成「查不到」。"""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    asyncio.run(late.check_turn("我猜它在 2019 年发布。", session_id="s10"))
    row = next(r for r in ledger.entries() if r.get("session_id") == "s10")
    assert row["verdict"] is None


_DECISION_MODULES = (
    "core/agent/execution_planner.py",
    "core/agent/kernel.py",
    "core/scheduler.py",
    "core/command_router.py",
    "core/cognitive/experience_guidance.py",
    "core/cognitive/memory_bias_layer.py",
    "core/approval_gate.py",
    "core/autonomy_policy.py",
    "core/tool_permissions.py",
    "core/node_invocation.py",
    "core/device_queue.py",
    "core/task_plan.py",
)


@pytest.mark.parametrize("rel", _DECISION_MODULES)
def test_guesses_never_reach_a_decision(rel):
    from core.semantic_anchoring import DECISION_PATH_MODULES

    assert {m.replace(".", "/") + ".py" for m in DECISION_PATH_MODULES} <= set(_DECISION_MODULES)
    path = REPO / rel
    if not path.exists():
        pytest.skip(f"{rel} 不存在")
    src = path.read_text(encoding="utf-8")
    assert "conjecture_ledger" not in src, f"{rel} 读了猜想账本 —— 猜想只给人看,不进决策"


def test_the_genome_asks_for_guesses_to_be_said_as_guesses():
    import core.genome as gm

    rules = gm.load_genome("grounded").component("instructions")["grounding"]
    assert "我猜" in rules and "可能" in rules
    for word in ("我猜", "可能"):
        assert late.late_kinds(f"{word}它是 2019 年发布的。") == ("conjecture",), "规矩教的说法要被核对线认出来"
