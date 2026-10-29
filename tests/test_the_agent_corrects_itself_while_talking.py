"""边说边核(``core/live_check.py``):先说、同时核、错了当场改 —— 核对不挡第一句话。

所有者的决定(docs/GROUNDED_AGENT_DESIGN.md §0、§3):核出来不对的句子**原句留着、划掉**,后面跟一句更正;
查不到的标「未核实」;念出去的只念实质更正、每轮最多一两处,「未核实」不念;
错话不当事实留在会话与记忆里。这一期接的是快的两级:「做好了」对这一轮**真实的工具结果**核,
「X 在线 / 离线」对连接管理器此刻的在线表核 —— 结论都来自类型化的事实,不从文本里反解结构。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

import core.live_check as lc

# ── 要不要核 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sentence",
    ["我已经帮你打开了客厅灯。", "文件已删除。", "好了，已完成。", "我刚刚把邮件发出去了。", "搞定了，设置好了。"],
)
def test_claims_of_having_done_something_are_checked(sentence):
    assert "completion" in lc.classify(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "要不要我帮你打开客厅灯？",
        "我来打开客厅灯。",
        "我已经知道了。",
        "打开失败了，没有执行。",
        "好的。",
        "我还没删除那个文件。",
    ],
)
def test_plans_questions_failures_and_small_talk_are_not(sentence):
    assert "completion" not in lc.classify(sentence)


def test_sentences_are_split_at_their_ends_and_the_tail_waits():
    done, tail = lc.split_sentences("第一句。第二句！还没说完")
    assert done == ["第一句。", "第二句！"] and tail == "还没说完"


# ── 「做好了」对这一轮真实的工具结果核 ───────────────────────────────────────


def _check(ledger: lc.TurnLedger, text: str):
    async def run():
        with lc.use_turn(ledger):
            return await lc.settle_current(text)

    return asyncio.run(run())


def test_saying_it_is_done_when_the_action_failed_is_refuted():
    ledger = lc.TurnLedger()
    ledger.note("home__control", False, "approval_denied: 没有执行:用户明确拒绝")
    (rev,) = _check(ledger, "我已经帮你打开了客厅灯。")
    assert rev.verdict == lc.REFUTED and "home__control" in rev.note and rev.source == "turn_ledger"


def test_saying_it_is_done_when_it_really_was_is_left_alone():
    ledger = lc.TurnLedger()
    ledger.note("home__control", True)
    assert _check(ledger, "我已经帮你打开了客厅灯。") == []


def test_saying_it_is_done_without_doing_anything_is_unverified():
    ledger = lc.TurnLedger()
    ledger.note("memory__recall", True)  # 只读的查询不算「做了」
    (rev,) = _check(ledger, "已经帮你删除了那个文件。")
    assert rev.verdict == lc.UNVERIFIED and "没有执行" in rev.note


def test_a_failed_read_does_not_refute_a_successful_action():
    ledger = lc.TurnLedger()
    ledger.note("memory__recall", False, "检索失败")
    ledger.note("home__control", True)
    assert _check(ledger, "灯已经打开了。") == []


# ── 「X 在线 / 离线」对在线表核 ─────────────────────────────────────────────


def test_saying_a_device_is_online_when_it_is_offline_is_refuted(monkeypatch):
    monkeypatch.setattr(lc, "_known_devices", lambda: [("watch-01", "我的手表", False)])
    (rev,) = _check(lc.TurnLedger(), "我的手表现在在线，可以直接用。")
    assert rev.verdict == lc.REFUTED and "离线" in rev.note and rev.source == "presence"


def test_an_ambiguous_device_is_not_guessed(monkeypatch):
    monkeypatch.setattr(lc, "_known_devices", lambda: [("a1b2", "手表", False), ("c3d4", "手表二号", True)])
    assert _check(lc.TurnLedger(), "手表二号现在在线。") == []  # 两台都对得上「手表」:不核


# ── 流式:出字即核,修订按帧推出去 ───────────────────────────────────────────


def test_a_refuted_sentence_is_pushed_while_the_answer_is_still_streaming():
    frames = []

    async def run():
        ledger, sink = lc.stream_ledger(frames.append)
        ledger.note("node__Node_06_Filesystem__delete", False, "未获用户确认")
        for chunk in ("好的，", "文件已经删除了。", "还有别的吗"):
            sink.feed(chunk)
        await asyncio.sleep(0.05)  # 核对在后台跑,不等这一轮结束
        revise = [p for k, p in frames if k == "revise"]
        tail = await ledger.settle()
        return revise, tail

    revise, tail = asyncio.run(run())
    assert [k for k, _ in frames if k == "delta"] == ["delta"] * 3, "出字照常,一个字都不挡"
    assert revise and revise[0]["original"] == "好的，文件已经删除了。" and revise[0]["verdict"] == lc.REFUTED
    assert len(tail) == 1


def test_a_reset_throws_away_checks_on_text_that_was_thrown_away():
    frames = []

    async def run():
        ledger, sink = lc.stream_ledger(frames.append)
        ledger.note("x__write", False, "boom")
        sink.feed("已经保存好了。")
        sink.reset()
        await asyncio.sleep(0.05)
        return ledger.revisions()

    assert asyncio.run(run()) == []
    assert not [p for k, p in frames if k == "revise"]


# ── 把修订用到文字上 ─────────────────────────────────────────────────────


def _rev(original, verdict, note):
    return lc.Revision(0, original, verdict, note, "turn_ledger")


def test_the_written_version_keeps_the_original_and_adds_the_correction():
    text = "灯已经打开了。还有别的吗？"
    out = lc.corrected_text(text, [_rev("灯已经打开了。", lc.REFUTED, "home__control 没成功")])
    assert out.startswith("灯已经打开了。（更正：home__control 没成功）")


def test_the_spoken_version_only_says_real_corrections_and_at_most_two():
    revs = [
        _rev("A 做好了。", lc.REFUTED, "a"),
        _rev("B 做好了。", lc.REFUTED, "b"),
        _rev("C 做好了。", lc.REFUTED, "c"),
        _rev("D 做好了。", lc.UNVERIFIED, "d"),
    ]
    spoken = lc.corrected_text("A 做好了。B 做好了。C 做好了。D 做好了。", revs, spoken=True)
    assert spoken.count("更正") == 2 and "未核实" not in spoken


def test_a_finished_turn_carries_its_revisions_and_a_spoken_version():
    ledger = lc.TurnLedger()
    ledger.note("home__control", False, "超时")
    result = {"response": "灯已经打开了。"}

    async def run():
        with lc.use_turn(ledger):
            await lc.attach_revisions(result)

    asyncio.run(run())
    assert result["response"] == "灯已经打开了。", "原文不动:面板拿原文 + 修订画「划掉」"
    assert result["revisions"][0]["verdict"] == lc.REFUTED
    assert "更正" in result["response_spoken"]


# ── 错话不当事实留在会话与记忆里 ─────────────────────────────────────────


def test_what_goes_into_the_session_is_the_corrected_text(monkeypatch):
    import core.session_memory_facade as facade

    written = []

    class _SM:
        async def ensure_session(self, *a, **k):
            return None

        async def add_message(self, sid, role, content, **kw):
            written.append((role, content, kw.get("metadata") or {}))

    monkeypatch.setattr(facade, "get_session_manager", lambda: _SM())
    monkeypatch.setattr(facade, "_is_adjacent_duplicate", lambda *a, **k: False)
    ledger = lc.TurnLedger()
    ledger.note("home__control", False, "没批准")

    async def run():
        with lc.use_turn(ledger):
            await facade.record_session_turn(
                conversation_session_id="s1", role="assistant", content="我已经打开了客厅灯。"
            )

    asyncio.run(run())
    ((role, content, meta),) = written
    assert role == "assistant" and "（更正：" in content
    assert meta["revisions"][0]["original"] == "我已经打开了客厅灯。"


# ── 整条:流式对话的 SSE 里有 revise 帧,done 里有全量 ─────────────────────


def test_the_chat_stream_carries_revise_frames_and_the_done_frame_has_them_all(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import core.desktop_presence_runtime as dpr
    import core.routes.chat as chat_mod

    class _Runtime:
        async def handle_request(self, *a, **k):
            from core.llm_stream import current_stream

            lc.note_tool_outcome("home__control", False, "approval_denied: 用户明确拒绝")
            sink = current_stream()
            for chunk in ("好的。", "我已经帮你打开了客厅灯。"):
                sink.feed(chunk)
                await asyncio.sleep(0.02)
            result = {"success": True, "response": "好的。我已经帮你打开了客厅灯。"}
            await lc.attach_revisions(result)
            return result

    monkeypatch.setenv("GALAXY_SPEAK", "0")
    app = FastAPI()
    app.include_router(chat_mod.create_router(service_manager=None, config=None))
    with patch.object(dpr, "get_desktop_presence_runtime", lambda: _Runtime()):
        with TestClient(app).stream("POST", "/api/v1/chat/stream", json={"message": "开灯", "session_id": "s"}) as r:
            frames = [json.loads(line[6:]) for line in r.iter_lines() if line and line.startswith("data: ")]
    revise = [f for f in frames if f["type"] == "revise"]
    done = next(f for f in frames if f["type"] == "done")
    assert revise and revise[0]["original"] == "我已经帮你打开了客厅灯。" and revise[0]["verdict"] == "refuted"
    assert done["revisions"] and done["revisions"][0]["note"]
    assert done["response"] == "好的。我已经帮你打开了客厅灯。", "原文不动"


def test_device_names_come_from_the_member_view(monkeypatch):
    """名字取自设备登记(成员视图),不是连接管理器 —— 后者的元数据里没有名字(第 8 轮真跑:真连着的设备被说成离线,没核上)。"""
    import asyncio

    import core.device_onboarding.service as svc

    class _Svc:
        def overview(self, include_ignored=False):
            return {"groups": {"members": [{"device_id": "r9-watch-0002", "name": "小米手表", "online": True}]}}

    monkeypatch.setattr(svc, "get_onboarding_service", lambda: _Svc())
    assert lc._known_devices() == [("r9-watch-0002", "小米手表", True)]
    verdict = asyncio.run(lc._verify_device_state("小米手表现在离线，连不上它。"))
    assert verdict == (lc.REFUTED, "小米手表 现在在线", "presence")
