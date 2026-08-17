#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_acm_context_management.py

钉住 ACM（Agentic Context Management）这一层：**压缩要无损、要能翻回来、时机要让
模型看得见，而且不是所有档位都该交给模型。**

上一版做的是什么
================
上一版的压缩是**永久删除**：摘要一生成，原文就从消息列表里删掉了，磁盘上只留一条
摘要文本。模型再也没有任何办法翻回去。

那正是 ACM 论文里被单列出来做消融的退化变体（源码中的 ``disable_query_memory`` /
``MANAGE_CONTEXT_TOOL_NOQUERY``）——**关掉检索之后，"压缩"就退化成"删除"**。也就是
说：上一版做的就是那个变体，缺的正是让"无损"两个字成立的另一半。

本文件钉四件
============
1. **无损**：原文整段归档，字段一个不少（``tool_calls`` / ``tool_call_id`` 尤其）；
2. **可取回**：按段号能把原文调回来，且取回不依赖目录还在不在窗口里；
3. **油表**：模型看得见自己有多满，且这个数与装配下限用的是**同一个**回复留白；
4. **档位门控**：A 档（2B/4B）不暴露这两个工具 —— ACM 自己的消融证明那个尺度
   学不会"何时记笔记"，挂上去只会让工具表变长、窗口反而更紧。

以及一条最要紧的：**自动压缩是地板，一条都不能撤。** ACM 靠后训练让模型学会节奏，
这个仓库跑的是现成权重、没有那条训练链路 —— 一个只在模型开口时才压缩的系统，会被
一个从不开口的模型撑爆。
"""

from __future__ import annotations

import pytest

import core.context_archive as ca
import core.context_compaction as cc
import core.context_trim as ct
import core.openclawd as oc


@pytest.fixture(autouse=True)
def isolated_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_ROOT", tmp_path / "context_archive")
    monkeypatch.delenv("GALAXY_MAX_TOKENS_ANSWER", raising=False)


def _session_with_tool_calls(rounds: int = 12):
    msgs = [{"role": "system", "content": "你是 Galaxy 助手。"}]
    for i in range(rounds):
        msgs.append({"role": "user", "content": f"第{i}轮：约束 C{i} 的确切措辞是「不得超过 {i * 7} 毫秒」。" * 20})
        msgs.append(
            {"role": "assistant", "content": "", "tool_calls": [{"id": f"call_{i}", "function": {"name": "probe"}}]}
        )
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": f"探测结果 {i}：延迟 {i * 7} ms。" * 20})
    return msgs


def _summarizer(fresh):
    return "- 本段讨论了若干约束\n- 有工具探测结果"


# ────────────────────── ① 无损：原文整段留着 ──────────────────────


class TestCompressionIsLosslessNotDeletion:
    """ "压缩"与"删除"的区别全在这一条上。"""

    def test_the_original_text_survives_verbatim(self):
        msgs = _session_with_tool_calls()
        needle = "不得超过 21 毫秒"
        assert any(needle in str(m.get("content", "")) for m in msgs)

        cc.compact_messages(msgs, _summarizer, session_id="s")
        assert not any(needle in str(m.get("content", "")) for m in msgs), "没压掉，这条测的就不是压缩了"

        seg = ca.load_segment("s", 1)
        assert seg is not None
        assert any(needle in str(e.get("content", "")) for e in seg["entries"]), "原文没了 —— 这是删除，不是压缩"

    def test_tool_call_plumbing_is_archived_too(self):
        """少了 tool_calls / tool_call_id，归档下来的就不是一段可理解的对话。

        谁调了什么、这条结果回的是哪一次调用，全都对不上 —— 取回来的会是一堆
        彼此无关的文本片段。
        """
        msgs = _session_with_tool_calls()
        cc.compact_messages(msgs, _summarizer, session_id="s")
        entries = ca.load_segment("s", 1)["entries"]
        assert any("tool_calls" in e for e in entries), "assistant 的 tool_calls 丢了"
        assert any("tool_call_id" in e for e in entries), "tool 结果的 tool_call_id 丢了"

    def test_each_compaction_is_its_own_segment(self):
        msgs = _session_with_tool_calls()
        cc.compact_messages(msgs, _summarizer, session_id="s")
        msgs += [{"role": "user", "content": "新的一段。" * 200} for _ in range(12)]
        cc.compact_messages(msgs, _summarizer, session_id="s")
        assert ca.list_segments("s") == [1, 2]

    def test_the_placeholder_carries_the_segment_number(self):
        """没有段号，模型就无从取回 —— 那正是上一版"合并成一条摘要"丢掉的东西。"""
        msgs = _session_with_tool_calls()
        cc.compact_messages(msgs, _summarizer, session_id="s")
        assert cc.visible_segment_ids(msgs) == [1]


# ────────────────────── ② 可取回 ──────────────────────


class TestRetrievalGoesToTheOriginal:
    """检索的是原文，不是摘要 —— "无损"是靠这一条成立的。"""

    def test_a_folded_segment_is_still_retrievable(self):
        """目录被折叠只是不占窗口了，原文一条不少。

        取回按段号读归档文件，**不看目录还在不在窗口里** —— 否则"折叠"就等于
        "丢失"，而模型只会看到一行"已折叠"，以为东西还在。
        """
        msgs = _session_with_tool_calls()
        for _ in range(cc.MAX_VISIBLE_SEGMENTS + 2):
            cc.compact_messages(msgs, _summarizer, session_id="s")
            msgs += [{"role": "user", "content": "又一段。" * 200} for _ in range(12)]
        assert 1 not in cc.visible_segment_ids(msgs), "第 1 段还没被折叠，这条测不到东西"
        assert ca.load_segment("s", 1) is not None, "折叠掉的段取不回来了 —— 那就是丢了"

    def test_an_oversized_segment_is_truncated_from_the_front_and_says_so(self):
        """截掉了要说出来，否则提取模型会以为自己看到的是全部。"""
        big = {"entries": [{"role": "user", "content": "x" * 5000} for _ in range(20)], "summary": ""}
        text = ca.render_segment_text(big, max_chars=12000)
        assert len(text) < 20 * 5000
        assert "未载入" in text, "截断了却没说"
        assert text.rstrip().endswith("x"), "应当保留靠后的部分（结论通常在后面）"

    def test_a_missing_segment_is_an_error_not_an_empty_answer(self):
        assert ca.load_segment("s", 999) is None

    def test_the_extraction_call_is_fed_the_original_not_the_summary(self):
        """**这条是整层的支点。**

        取回时把摘要喂给提取模型，整套东西就退回成"有损压缩"了 —— 而且退得毫无声息：
        它照样返回一段看起来合理的文字，只是那段文字里的细节是摘要转述的，不是原话。
        反向验证时把 ``render_segment_text`` 换成读 ``summary``，本文件原来一条都不红。
        """
        import asyncio

        msgs = _session_with_tool_calls()
        needle = "不得超过 21 毫秒"
        cc.compact_messages(msgs, _summarizer, session_id="s")

        seen = {}

        class _Router:
            def chat(self, prompt):
                seen["prompt"] = prompt
                return "原话是「不得超过 21 毫秒」"

        agent = oc.OpenClawd.__new__(oc.OpenClawd)
        agent._react_messages = msgs
        agent._current_session_id = "s"
        agent._get_router = lambda: _Router()

        out = asyncio.run(agent._execute_context_tool("query_memory", {"segment_id": 1, "query": "21 毫秒"}))
        assert out["success"], out
        assert needle in seen["prompt"], "提取调用拿到的不是原文 —— 那就是拿摘要在冒充原话"
        assert "本段讨论了若干约束" not in seen["prompt"], "喂进去的是摘要"


# ────────────────────── ③ 油表 ──────────────────────


class TestTheModelCanSeeHowFullItIs:
    """没有这个数，"何时该压"对模型就是不可判定的。"""

    def test_the_gauge_reports_usage_against_the_window(self):
        gauge = cc.fuel_gauge(_session_with_tool_calls(), 32768, 4096)
        assert "当前上下文 token" in gauge and "窗口 32768" in gauge

    def test_it_counts_the_reply_headroom_too(self):
        """ACM 那边加的是 max_new_tokens，理由一样：N 要能直接跟窗口比。

        少加这一项，模型会在"看起来还剩一点"的时候撞上截断。
        """
        msgs = _session_with_tool_calls()
        without = cc.fuel_gauge(msgs, 32768, 0)
        with_room = cc.fuel_gauge(msgs, 32768, 4096)
        assert without != with_room, "回复留白没算进去"

    def test_the_headroom_is_the_same_number_the_floor_uses(self):
        """两处必须同源，否则油表报的"还剩多少"和下限算的不是一回事。"""
        import inspect

        src = inspect.getsource(oc.OpenClawd._fuel_gauge_suffix)
        assert "reply_headroom_tokens" in src
        assert ct.reply_headroom_tokens() > 0

    def test_an_unknown_window_reports_nothing_rather_than_a_wrong_number(self):
        assert cc.fuel_gauge(_session_with_tool_calls(), 0, 4096) == ""

    def test_it_says_out_loud_when_past_the_threshold(self):
        msgs = _session_with_tool_calls()
        used = cc.estimate_tokens(msgs)
        assert "该整理上下文了" in cc.fuel_gauge(msgs, int(used / 0.9), 0)

    def test_the_gauge_is_attached_to_tool_results(self):
        """挂在工具结果尾部，因为那正是上下文增长最快的地方。"""
        import inspect

        src = inspect.getsource(oc.OpenClawd._react_loop)
        assert "_fuel_gauge_suffix(messages)" in src, "油表没接到工具结果上"


# ────────────────────── ④ 档位门控 ──────────────────────


class TestOnlyBigEnoughModelsGetTheTools:
    """ACM 自己的消融：4B 做完同样训练也只有 3.4%，9B 是 57.3%。

    原因不是它不会调工具，是它**只跑两轮就终止**，轨迹根本没长到需要管理上下文。
    """

    @pytest.mark.parametrize("tier,expected", [("A", False), ("B", True), ("C", True), ("D", True)])
    def test_the_gate_follows_the_tier(self, tier, expected):
        assert cc.model_manages_own_context(tier) is expected

    def test_an_unknown_tier_does_not_get_them(self):
        """问不出档位就不给 —— 宁可少一个工具，不要凭空多一个成本。"""
        assert cc.model_manages_own_context("说不上来") is False

    def test_the_tools_are_gated_at_collection_time(self):
        import inspect

        src = inspect.getsource(oc.OpenClawd._collect_tools)
        assert "model_manages_own_context()" in src, "工具无条件挂上去了，A 档也会看到"
        assert "_CONTEXT_BUILTIN_TOOLS" in src

    def test_both_tools_exist_and_are_dispatchable(self):
        names = [t["function"]["name"] for t in oc._CONTEXT_BUILTIN_TOOLS]
        assert names == ["context__manage", "context__query_memory"]
        assert "context__" in oc.OpenClawd._dispatch_tool_call.__code__.co_consts[1]

    def test_they_are_never_slimmed_away(self):
        """``slim_tools`` 在工具表过大时才裁 —— 而那恰恰是最需要上下文管理的时刻。"""
        assert "context__" in ct._CORE_TOOL_MARKERS


# ────────────────────── ⑤ 自动压缩是地板 ──────────────────────


class TestTheAutomaticFloorIsNeverRemoved:
    """一个只在模型开口时才压缩的系统，会被一个从不开口的模型撑爆。"""

    def test_the_threshold_trigger_still_runs_regardless_of_tier(self):
        import inspect

        src = inspect.getsource(oc.OpenClawd._compact_context_if_needed)
        assert "should_compact(" in src, "自动阈值被撤了"
        assert "model_manages_own_context" not in src, "自动压缩被档位门控住了 —— 那是地板，不该有条件"

    def test_the_model_driven_path_ignores_the_threshold(self):
        """模型开口时不该再被阈值拦住 —— 它开口的理由往往正是阈值看不见的那种。"""
        import inspect

        src = inspect.getsource(oc.OpenClawd._context_tool_manage)
        assert "should_compact" not in src
        assert "compact_messages(" in src

    def test_the_tool_handle_is_released_when_the_loop_ends(self):
        """留着的话，下一次不在循环里的调用会对一份陈旧列表做压缩，还回一句"已归档"。"""
        import inspect

        src = inspect.getsource(oc.OpenClawd._react_loop)
        assert "self._react_messages = None" in src
        assert "finally:" in src

    def test_the_tool_refuses_outside_the_loop(self):
        import asyncio

        agent = oc.OpenClawd.__new__(oc.OpenClawd)
        agent._react_messages = None
        out = asyncio.run(agent._execute_context_tool("manage", {}))
        assert out["success"] is False and "ReAct" in out["error"]

    def test_query_rejects_a_bad_segment_id_instead_of_guessing(self):
        import asyncio

        agent = oc.OpenClawd.__new__(oc.OpenClawd)
        agent._react_messages = [{"role": "system", "content": "x"}]
        agent._current_session_id = "s"
        assert asyncio.run(agent._execute_context_tool("query_memory", {"query": "x"}))["success"] is False
        assert asyncio.run(agent._execute_context_tool("query_memory", {"segment_id": 1}))["success"] is False
        out = asyncio.run(agent._execute_context_tool("query_memory", {"segment_id": 99, "query": "x"}))
        assert out["success"] is False and "不存在" in out["error"]
