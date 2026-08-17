#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_long_session_compacts_not_forgets.py

钉住：**长会话要压，不能只是丢；而且压完要能翻回来。**

``core.context_trim`` 做的三件事全是**机械丢弃**：工具结果截断、老轮次换存根、工具表
瘦身。短任务里没问题；长会话里就是"断片" —— 聊到第 40 轮时，第 5 轮定下的约束已经
是 ``…[已修剪]``，模型再也问不回来。而系统这边**一条错误都没有**：丢弃是设计如此的。

上一版补了中间那一层（压缩），但压的方式是**永久删除**：摘要一生成，原文就没了。
这一版把它改成**无损**——原文整段归档、段号可寻址、随时按号取回（见
``tests/test_acm_context_management.py``）。本文件钉的是压缩这一层本身的性质：

* 什么时候压（按窗口占用比例，不是固定条数）；
* 压什么、不压什么（系统头与最近几轮绝不动）；
* 不确定时宁可不压（三条防线）；
* 重启后目录要贴得回来。
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

import core.context_archive as ca
import core.context_compaction as cc


@pytest.fixture(autouse=True)
def isolated_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_ROOT", tmp_path / "context_archive")


def _long_session(rounds: int = 14, size: int = 40):
    msgs = [{"role": "system", "content": "你是 Galaxy 助手。"}]
    for i in range(1, rounds + 1):
        msgs.append({"role": "user", "content": f"第 {i} 轮：请记住约束 C{i}。" * size})
        msgs.append({"role": "assistant", "content": f"好的，记住 C{i}。" * size})
    return msgs


def _summarizer(seen=None):
    def _s(fresh):
        if seen is not None:
            seen.append(fresh)
        return f"- 覆盖 {fresh.count(chr(10)) + 1} 条\n- 本段要点若干"

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


class TestOneSegmentPerCompactionEachSummarizedOnce:
    """上一版把所有摘要并成一条；这一版每段一条、各带段号。

    合并原本是为了防"反复重新摘导致越压越漂"。但每段只从**原文**摘一次，根本不会
    漂 —— 那是上一版自己造出来的问题。而合并的代价是**段号没了**，没有段号就无从
    取回，"无损"也就无从谈起。
    """

    def test_each_compaction_adds_its_own_addressable_segment(self):
        msgs = _long_session()
        cc.compact_messages(msgs, _summarizer(), session_id="s")
        msgs += [{"role": "user", "content": "新的一轮。" * 200} for _ in range(12)]
        cc.compact_messages(msgs, _summarizer(), session_id="s")
        assert cc.visible_segment_ids(msgs) == [1, 2], "两次压缩没有变成两个可寻址的段"

    def test_the_summarizer_only_ever_sees_original_text(self):
        """它拿到的必须是原文，不能是上一条摘要 —— 摘要的摘要就是漂移的来源。"""
        seen = []
        msgs = _long_session()
        cc.compact_messages(msgs, _summarizer(seen), session_id="s")
        msgs += [{"role": "user", "content": "新的一轮。" * 200} for _ in range(12)]
        cc.compact_messages(msgs, _summarizer(seen), session_id="s")
        assert len(seen) == 2
        for fresh in seen:
            assert cc.ANCHOR_MARKER not in fresh, "把上一段的目录又喂给摘要器了 —— 那是摘要的摘要"

    def test_old_segment_markers_are_folded_not_multiplied(self):
        """段目录会随会话线性涨，不封顶的话压缩省下的空间会被目录自己吃回去。"""
        msgs = _long_session()
        for _ in range(cc.MAX_VISIBLE_SEGMENTS + 3):
            cc.compact_messages(msgs, _summarizer(), session_id="s")
            msgs += [{"role": "user", "content": "又一轮。" * 200} for _ in range(12)]
        markers = [m for m in msgs if cc._is_segment_marker(m)]
        assert len(markers) <= cc.MAX_VISIBLE_SEGMENTS + 1, f"目录堆到了 {len(markers)} 条"
        assert any("折叠" in str(m.get("content", "")) for m in markers), "折叠了却没说，模型会以为更早的段不存在了"


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
        assert cc.compact_messages(msgs, _summarizer(), session_id="s", persisted_ok=False) == 0
        assert len(msgs) == before, "拒绝压缩却把消息改了"

    def test_it_refuses_without_a_session_id(self):
        """没有会话 id 就无处归档，而**归档不了的压缩就是不可逆删除**。

        上一版这里是"仍然压，只是重启后不连续"——那时压缩本来就是有损的，所以说得
        过去。现在整套语义建立在"原文还在"之上，压一段没处归档的历史等于对模型撒谎：
        它会以为自己随时能查回来。
        """
        msgs = _long_session()
        before = list(msgs)
        import logging as _logging

        seen = []
        h = _logging.Handler()
        h.emit = lambda r: seen.append(r.getMessage())
        _logging.getLogger("Galaxy.ContextCompaction").addHandler(h)
        try:
            assert cc.compact_messages(msgs, _summarizer(), session_id="") == 0
        finally:
            _logging.getLogger("Galaxy.ContextCompaction").removeHandler(h)
        assert msgs == before
        # 归档层本身也会挡住空会话 id（防线是两层的），所以只断言"没压"是不够的 ——
        # 那样把明说的那一层拆掉，测试照样绿，而现场只剩一次**静默**的不压缩。
        assert any("无处归档" in m for m in seen), "拒绝了却没说为什么 —— 排查时看到的会是「它怎么不压」"

    def test_it_refuses_when_the_archive_cannot_be_written(self, monkeypatch):
        """归档失败还照压，窗口里那条目录就指向一个**不存在的段**。"""
        monkeypatch.setattr(ca, "archive_segment", lambda *a, **k: None)
        msgs = _long_session()
        before = list(msgs)
        assert cc.compact_messages(msgs, _summarizer(), session_id="s") == 0
        assert msgs == before

    def test_a_failing_summarizer_loses_nothing(self):
        def boom(fresh):
            raise RuntimeError("模型挂了")

        msgs = _long_session()
        before = list(msgs)
        assert cc.compact_messages(msgs, boom, session_id="s") == 0
        assert msgs == before, "摘要生成失败却已经把历史丢了"

    def test_an_empty_summary_loses_nothing(self):
        msgs = _long_session()
        before = list(msgs)
        assert cc.compact_messages(msgs, lambda fresh: "   ", session_id="s") == 0
        assert msgs == before


class TestContinuityAcrossRestarts:
    """进程重启后同一个会话不该突然失忆。"""

    def test_the_segments_are_persisted_and_retrievable(self):
        msgs = _long_session()
        cc.compact_messages(msgs, _summarizer(), session_id="sess-42")
        assert ca.list_segments("sess-42") == [1], "段没存下来 —— 重启后这个会话就断了"

    def test_sessions_do_not_bleed_into_each_other(self):
        cc.compact_messages(_long_session(), _summarizer(), session_id="a")
        assert ca.list_segments("a")
        assert ca.list_segments("b") == [], "串会话了"

    def test_the_directory_is_actually_read_back(self):
        """**写侧有、读侧没有**，是这一条要防的东西。

        上一版只调了写侧：摘要在磁盘上安安静静地攒着，而重启后的会话该失忆照样
        失忆 —— 而且不会有任何一条错误。存了从不读，比不存更糟：它给人"连续性已经
        做了"的错觉。
        """
        old = _long_session()
        cc.compact_messages(old, _summarizer(), session_id="sess-restart")

        fresh = [{"role": "system", "content": "你是 Galaxy 助手。"}, {"role": "user", "content": "我们刚才聊到哪了？"}]
        assert cc.restore_segments(fresh, "sess-restart") == 1
        assert cc.visible_segment_ids(fresh) == [1], "重启后没把段目录贴回来"
        assert fresh[0]["role"] == "system" and "Galaxy 助手" in fresh[0]["content"], "贴到系统提示前面去了"

    def test_it_does_not_paste_a_second_version_of_the_past(self):
        """历史本身还在的时候贴目录，等于让模型看到同一段过去的两个版本。"""
        msgs = _long_session()
        cc.compact_messages(msgs, _summarizer(), session_id="sess-live")
        before = list(msgs)
        assert cc.restore_segments(msgs, "sess-live") == 0, "已经有段目录了还往里贴"
        assert msgs == before

        long_no_marker = _long_session()
        assert cc.restore_segments(long_no_marker, "sess-live") == 0, "历史还在（消息很长），不该再贴一份有损副本"

    def test_nothing_stored_means_nothing_pasted(self):
        fresh = [{"role": "system", "content": "你是 Galaxy 助手。"}]
        assert cc.restore_segments(fresh, "从没压过的会话") == 0
        assert cc.restore_segments(fresh, "") == 0
        assert len(fresh) == 1

    def test_the_live_loop_restores_before_it_measures_or_compacts(self):
        import inspect

        import core.openclawd as oc

        src = inspect.getsource(oc.OpenClawd._compact_context_if_needed)
        # 钉**调用**而不是钉名字：只钉名字的话，把调用换成 pass、import 行留着，
        # 这条断言照样绿 —— 反向验证时就是这么发现它没用的。
        assert "restore_segments(messages" in src, "取回段目录这一步没人调 —— 跨重启连续性只做了写侧"
        assert src.index("restore_segments(messages") < src.index("should_compact(")


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


class TestTheArchiveIsNotACache:
    """这里存的是唯一的原文，不是缓存 —— 没有任何自动清理路径。"""

    def test_deletion_only_happens_when_someone_asks_for_it(self):
        cc.compact_messages(_long_session(), _summarizer(), session_id="keep-me")
        cc.compact_messages(_long_session(), _summarizer(), session_id="drop-me")
        assert ca.list_segments("keep-me") and ca.list_segments("drop-me")
        assert ca.drop_session("drop-me") == 1
        assert ca.list_segments("drop-me") == []
        assert ca.list_segments("keep-me"), "只该删被点名的那个会话"

    def test_clearing_a_conversation_must_clear_the_archive_too(self):
        """否则"清除"就是一句假话：用户点了清除，他说过的每一句仍在磁盘上。

        钉的是**那条路真的调了这个函数** —— 新加一处存用户原话的地方却不接进已有的
        清除路径，等于在用户背后留了一份他以为已经删掉的副本。
        """
        import inspect

        import core.routes.ai as ai_routes

        src = inspect.getsource(ai_routes)
        assert "drop_session(session_id)" in src, "清除对话没有清掉上下文归档"

    def test_a_session_id_can_never_escape_the_archive_root(self, tmp_path, monkeypatch):
        """会话 id 来自调用方，直接拼路径就是一条目录穿越。

        这条第一版是**空跑的**：它只在归档根**里面** ``rglob`` 找证据，而穿越写出去的
        文件在根**外面** —— 走不到，于是断言对着一个空集合恒真。反向验证时把
        ``_safe()`` 整个拆掉，它照样绿。

        证据要到**穿越会落地的那个位置**去找。
        """
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "nest" / "archive"
        monkeypatch.setattr(ca, "_ROOT", root)

        cc.compact_messages(_long_session(), _summarizer(), session_id="../../outside/evil")
        assert list(outside.iterdir()) == [], f"写到归档根目录外面去了：{list(outside.iterdir())}"
        assert ca.list_segments("../../outside/evil"), "穿越被挡住了，但这一段也该正常归档（只是名字被消毒）"
