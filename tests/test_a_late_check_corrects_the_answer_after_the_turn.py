"""一轮结束之后,慢的两级在后台核:联网搜索 + 换一个模型裁决;驳倒的给那条回答挂晚到的勘误。

docs/GROUNDED_AGENT_DESIGN.md §3.2 后两行、§3.3「这一轮已经结束」、第五期「联网核对」。核心约束:

* 回答用过的厂商不当裁判(提出者自报不算);
* 裁判说「驳倒」却指不出搜索结果里的出处 → 当没核(查不到不等于驳倒);
* 没配联网搜索就什么都不改,并且照实说缺什么;
* 后台任务不在这一轮的上下文里跑(裁判的字不流进人的对话);
* 勘误落三处:会话里的文字、面板的 WS ``revise`` 帧、岛上一张卡。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from types import SimpleNamespace

import pytest

from core import live_check
from core import live_check_late as late
from core.live_check import REFUTED, SUPPORTED, UNVERIFIED, Revision


def test_what_gets_checked_after_the_turn():
    assert late.late_kinds("我猜明天上海会下雨。") == ("conjecture",)
    assert late.late_kinds("它大概是 2019 年发布的。") == ("conjecture",)
    assert late.late_kinds("你可能需要先重启一下。") == (), "给人的建议不是对事实的猜"
    assert late.late_kinds("目前最新的版本是 3.13。") == ("current_fact",)
    assert late.late_kinds("目前一切正常。") == (), "没有数字的「目前」不值得联网核"
    assert late.late_kinds("你说的是哪一个？") == ()


def test_at_most_two_sentences_and_guesses_first():
    text = "目前最新版本是 3.13。今年发布了 5 个版本。我猜下个月还会发布。现在价格是 99 元。"
    picked = late.candidates(text)
    assert len(picked) == late.MAX_LATE_CHECKS == 2
    assert picked[0][2] == "conjecture"


def test_sentences_the_fast_tier_already_checked_are_skipped():
    text = "目前最新版本是 3.13。"
    assert late.candidates(text, already=["目前最新版本是 3.13。"]) == []


def test_a_refutation_needs_a_source_from_the_results():
    urls = ["https://a.example/x"]
    good = '{"verdict": "refuted", "correct": "最新版本是 3.14", "source": "https://a.example/x"}'
    assert late._parse_verdict(good, urls) == (REFUTED, "最新版本是 3.14", "https://a.example/x")
    made_up = '{"verdict": "refuted", "correct": "最新版本是 3.14", "source": "https://elsewhere.example"}'
    assert late._parse_verdict(made_up, urls)[0] == UNVERIFIED
    no_fix = '{"verdict": "refuted", "correct": "", "source": "https://a.example/x"}'
    assert late._parse_verdict(no_fix, urls)[0] == UNVERIFIED
    assert late._parse_verdict("不是 JSON", urls)[0] == UNVERIFIED


class _Cfg:
    def is_available(self):
        return True


class _FakeRouter:
    def __init__(self, used=("answerer",), reply=""):
        self.providers = {"answerer": _Cfg(), "other": _Cfg()}
        self.adapters = {"answerer": object(), "other": object()}
        self.call_history = [{"provider": p, "timestamp": time.time()} for p in used]
        self.asked = []
        self.reply = reply

    async def chat(self, messages, provider=None, **kw):
        self.asked.append(provider)
        return SimpleNamespace(content=self.reply)


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    evidence = [{"title": "Python 3.14 released", "url": "https://py.example/314", "text": "3.14 is out"}]

    async def fake_search(query):
        return evidence, ""

    monkeypatch.setattr(late, "_search", fake_search)
    return evidence


def test_the_model_that_answered_is_not_the_judge(monkeypatch, web):
    router = _FakeRouter(
        reply='{"verdict": "refuted", "correct": "最新版本是 3.14", "source": "https://py.example/314"}'
    )
    monkeypatch.setattr(late, "_router", lambda: router)
    revs = asyncio.run(late.check_turn("目前最新的版本是 3.13。", started_at=time.time() - 5))
    assert router.asked == ["other"], "回答用过的厂商不当裁判"
    assert [(r.verdict, r.note, r.source) for r in revs] == [(REFUTED, "最新版本是 3.14", "web:https://py.example/314")]


def test_with_only_the_answering_model_there_is_no_verdict(monkeypatch, web):
    router = _FakeRouter(used=("answerer", "other"))
    monkeypatch.setattr(late, "_router", lambda: router)
    assert asyncio.run(late.check_turn("目前最新的版本是 3.13。", started_at=time.time() - 5)) == []
    assert router.asked == []


def test_without_web_search_nothing_changes_and_it_says_why(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    router = _FakeRouter()
    monkeypatch.setattr(late, "_router", lambda: router)
    assert asyncio.run(late.check_turn("目前最新的版本是 3.13。")) == []
    ready, why = late.web_search_ready()
    assert not ready and "BRAVE_API_KEY" in why
    assert router.asked == []


def test_a_confirmed_guess_comes_back_as_supported(monkeypatch, web):
    router = _FakeRouter(reply='{"verdict": "supported", "correct": "", "source": "https://py.example/314"}')
    monkeypatch.setattr(late, "_router", lambda: router)
    revs = asyncio.run(late.check_turn("我猜 3.14 已经发布了。", started_at=time.time() - 5))
    assert [r.verdict for r in revs] == [SUPPORTED]
    assert live_check.corrected_text("我猜 3.14 已经发布了。", revs).endswith("（已核实：搜索结果支持这个说法）")


def test_a_supported_plain_fact_is_left_alone(monkeypatch, web):
    router = _FakeRouter(reply='{"verdict": "supported", "correct": "", "source": "https://py.example/314"}')
    monkeypatch.setattr(late, "_router", lambda: router)
    assert asyncio.run(late.check_turn("目前最新的版本是 3.14。", started_at=time.time() - 5)) == []


def test_the_correction_lands_in_the_session_the_panel_and_the_island(monkeypatch):
    from core import island_cards
    from core.session_manager import get_session_manager

    sm = get_session_manager()
    frames, cards = [], []

    class _Bridge:
        async def _ws_broadcast(self, frame):
            frames.append(frame)

    import core.lumiv_websocket_bridge as bridge

    monkeypatch.setattr(bridge.GalaxyPresenceBridge, "get_instance", classmethod(lambda cls: _Bridge()))
    monkeypatch.setattr(island_cards, "post_card", lambda cid, **f: cards.append((cid, f)))
    rev = Revision(0, "目前最新的版本是 3.13。", REFUTED, "最新版本是 3.14", "web:https://py.example/314")

    async def go():
        sid = f"late-test-{time.time_ns()}"
        await sm.ensure_session(sid, user_id="u")
        await sm.add_message(sid, "assistant", "目前最新的版本是 3.13。还要别的吗？")
        await late.deliver(sid, [rev])
        return sid, sm.get_full_history(sid)[-1]

    sid, msg = asyncio.run(go())
    assert msg["content"].startswith("目前最新的版本是 3.13。（更正：最新版本是 3.14）")
    assert msg["metadata"]["revisions"][-1]["late"] is True
    assert frames and frames[0]["type"] == "revise" and frames[0]["payload"]["session_id"] == sid
    assert frames[0]["payload"]["revisions"][0]["verdict"] == REFUTED
    assert cards and cards[0][0] == f"late-revise:{sid}" and "更正" in cards[0][1]["title"]


def test_background_sources_are_not_checked():
    assert late.after_turn("目前最新的版本是 3.13。", session_id="s", source="ambient", started_at=0) is False
    assert late.after_turn("你好呀。", session_id="s", source="chat", started_at=0) is False


def test_the_background_check_does_not_run_inside_the_turn(monkeypatch):
    """裁判在一个空上下文里跑:这一轮的账、这一轮的令牌流,它都看不见。"""
    seen = {}

    async def fake_run(text, sid, started, already):
        seen["turn"] = live_check._TURN.get()

    monkeypatch.setattr(late, "_run", fake_run)

    async def go():
        with live_check.use_turn(live_check.TurnLedger()):
            assert late.after_turn("目前最新的版本是 3.13。", session_id="s", source="chat", started_at=0)
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert seen == {"turn": None}


def test_the_presence_runtime_hands_the_turn_over_before_closing_it():
    from core import desktop_presence_runtime as rt

    src = inspect.getsource(rt)
    assert src.index("_live_check.late_check(") < src.index("_live_check.close_turn(_turn_token)")


def test_late_check_skips_what_the_fast_tier_already_said(monkeypatch):
    got = {}
    monkeypatch.setattr(late, "after_turn", lambda text, **kw: got.update(text=text, **kw) or True)
    ledger = live_check.TurnLedger()
    ledger._revisions[0] = Revision(0, "已经打开了。", REFUTED, "没做成", "turn_ledger")
    with live_check.use_turn(ledger):
        assert live_check.late_check({"response": "已经打开了。目前最新版本是 3.13。"}, session_id="s", source="chat")
    assert got["already"] == ["已经打开了。"] and got["started_at"] == ledger.started_at


def test_the_status_says_what_is_missing(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr(late, "_router", lambda: _FakeRouter())
    st = late.status()
    assert st["web_search"]["available"] is False and "BRAVE_API_KEY" in st["web_search"]["detail"]
    assert st["judge"]["available"] is True and set(st["judge"]["providers"]) == {"answerer", "other"}
    assert st["conjectures"]["hit_rate"] is None or isinstance(st["conjectures"]["hit_rate"], float)
