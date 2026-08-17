#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_long_session_compacts_not_forgets.py

钉住：**长会话要压，不能只是丢。**

修的是什么
==========
``core.context_trim`` 做的三件事全是**机械丢弃**：工具结果截断、老轮次换存根、工具表
瘦身。短任务里没问题；长会话里就是"断片" —— 聊到第 40 轮时，第 5 轮定下的约束已经
是 ``…[已修剪]``，模型再也问不回来。而系统这边**一条错误都没有**：丢弃是设计如此的。

缺的是中间那一层：丢之前先压成摘要。做法取自 2026 年这一批 Agent 的共识：

* **锚定式增量摘要**：全程只维护一条摘要，新的一段**并进**它，而不是拿全部历史重新
  生成。重新生成每次都在重新解释旧内容，越压越漂；
* **按窗口占用比例触发**，不是固定条数 —— 窗口现在是按机器算的，同一套代码在 24 GB
  卡上十几万 token、9 GB 卡上两千，写死条数在两头都不对；
* **先落库再压缩**：压缩不可逆，持久层没拿到之前不许压。
"""

from __future__ import annotations

import pytest

import core.context_compaction as cc


@pytest.fixture(autouse=True)
def isolated_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "_ANCHOR_FILE", tmp_path / "context_anchors.json")


def _long_session(rounds: int = 14, size: int = 40):
    msgs = [{"role": "system", "content": "你是 Galaxy 助手。"}]
    for i in range(1, rounds + 1):
        msgs.append({"role": "user", "content": f"第 {i} 轮：请记住约束 C{i}。" * size})
        msgs.append({"role": "assistant", "content": f"好的，记住 C{i}。" * size})
    return msgs


def _summarizer(seen=None):
    def _s(prior, fresh):
        if seen is not None:
            seen.append((prior, fresh))
        return (prior + " | " if prior else "") + f"[并入 {fresh.count(chr(10)) + 1} 条]"

    return _s


class TestItFiresOnUtilizationNotOnCount:
    """写死"超过 N 条就压"在大窗口上压太早、在小窗口上压太晚。"""

    def test_a_short_session_is_left_alone(self):
        assert not cc.should_compact(_long_session(rounds=2), 128000)

    def test_the_same_session_compacts_on_a_small_window_only(self):
        msgs = _long_session()
        assert cc.should_compact(msgs, 4096), "小窗口上早就该压了"
        assert not cc.should_compact(msgs, 1_000_000), "大窗口上压是浪费"

    def test_an_unknown_window_never_triggers(self):
        """窗口算不出来时一律不压 —— 判不了不动手。"""
        assert not cc.should_compact(_long_session(), 0)


class TestTheSummaryIsAnchoredNotRegenerated:
    """锚定的前提是能认出上一条摘要，否则压几次就有几条互相矛盾的过去。"""

    def test_there_is_never_more_than_one_summary(self):
        msgs = _long_session()
        cc.compact_messages(msgs, _summarizer(), session_id="s")
        msgs += [{"role": "user", "content": "新的一轮。" * 200} for _ in range(12)]
        cc.compact_messages(msgs, _summarizer(), session_id="s")
        anchors = [m for m in msgs if cc.ANCHOR_MARKER in str(m.get("content", ""))]
        assert len(anchors) == 1, f"摘要变成了 {len(anchors)} 条 —— 那不是锚定，是每次新插一条"

    def test_the_second_pass_merges_into_the_first(self):
        seen = []
        msgs = _long_session()
        cc.compact_messages(msgs, _summarizer(seen), session_id="s")
        msgs += [{"role": "user", "content": "新的一轮。" * 200} for _ in range(12)]
        cc.compact_messages(msgs, _summarizer(seen), session_id="s")
        assert seen[0][0] == "", "第一次压缩不该有已有摘要"
        assert seen[1][0], "第二次压缩没拿到上一条摘要 —— 那是重新生成，不是并入"


class TestWhatMustSurviveDoesSurvive:
    """压缩会改变模型看到的东西，有几样绝不能动。"""

    def test_the_system_prompt_is_never_compacted(self):
        """人格与工具契约压掉了不是"省空间"，是换了个 Agent。"""
        msgs = _long_session()
        cc.compact_messages(msgs, _summarizer(), session_id="s")
        assert msgs[0]["role"] == "system" and "Galaxy 助手" in msgs[0]["content"]

    def test_the_most_recent_turns_stay_verbatim(self):
        """最近几轮是模型正在推理的现场，压掉等于让它忘记自己刚在做什么。"""
        msgs = _long_session()
        tail_before = [m["content"] for m in msgs[-cc.KEEP_RECENT_MESSAGES :]]
        cc.compact_messages(msgs, _summarizer(), session_id="s")
        assert [m["content"] for m in msgs[-cc.KEEP_RECENT_MESSAGES :]] == tail_before

    def test_it_actually_gets_shorter(self):
        msgs = _long_session()
        before = len(msgs)
        assert cc.compact_messages(msgs, _summarizer(), session_id="s") > 0
        assert len(msgs) < before


class TestItRefusesRatherThanLoses:
    """压缩不可逆。任何一处不确定，宁可占着窗口也不动手。"""

    def test_it_refuses_when_the_store_has_not_confirmed(self):
        """先落库再压缩：持久层没拿到这一段之前压，等于拿用户说过的话去赌摘要写得够全。"""
        msgs = _long_session()
        before = len(msgs)
        assert cc.compact_messages(msgs, _summarizer(), persisted_ok=False) == 0
        assert len(msgs) == before, "拒绝压缩却把消息改了"

    def test_a_failing_summarizer_loses_nothing(self):
        def boom(prior, fresh):
            raise RuntimeError("模型挂了")

        msgs = _long_session()
        before = list(msgs)
        assert cc.compact_messages(msgs, boom, session_id="s") == 0
        assert msgs == before, "摘要生成失败却已经把历史丢了"

    def test_an_empty_summary_loses_nothing(self):
        msgs = _long_session()
        before = list(msgs)
        assert cc.compact_messages(msgs, lambda p, f: "   ", session_id="s") == 0
        assert msgs == before


class TestContinuityAcrossRestarts:
    """进程重启后同一个会话不该突然失忆。"""

    def test_the_anchor_is_persisted_and_retrievable(self):
        msgs = _long_session()
        cc.compact_messages(msgs, _summarizer(), session_id="sess-42")
        assert cc.load_anchor("sess-42"), "摘要没存下来 —— 重启后这个会话就断了"

    def test_sessions_do_not_bleed_into_each_other(self):
        cc.compact_messages(_long_session(), _summarizer(), session_id="a")
        assert cc.load_anchor("a")
        assert cc.load_anchor("b") == "", "串会话了"

    def test_no_session_id_still_compacts_but_does_not_persist(self):
        """没有会话 id 时仍然要压（本次有效），只是重启后不连续。"""
        msgs = _long_session()
        assert cc.compact_messages(msgs, _summarizer(), session_id="") > 0


class TestItIsWiredIntoTheLiveLoop:
    """判据接上了但没人调，等于没接。"""

    def test_the_react_loop_compacts_after_pruning(self):
        import inspect

        import core.openclawd as oc

        src = inspect.getsource(oc.OpenClawd._react_loop)
        assert "_compact_context_if_needed" in src, "ReAct 循环没接压缩层"
        assert src.index("prune_stale_tool_results") < src.index(
            "_compact_context_if_needed"
        ), "压缩要在机械修剪之后 —— 先把便宜的省掉，再花一次模型调用去压"

    def test_the_window_size_comes_from_the_scheduler(self):
        """窗口大小不在这里重算 —— 那是 context_budget_for 的判据。"""
        import inspect

        import core.openclawd as oc

        src = inspect.getsource(oc.OpenClawd._compact_context_if_needed)
        assert "context_budget_for" in src
        assert "4096" not in src, "又把窗口大小写死了"
