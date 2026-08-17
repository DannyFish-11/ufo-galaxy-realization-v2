#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_context_runway.py

钉住：**水位管"现在多满"，跑道管"还剩多远" —— 两个触发器盯的是不同的失败形态。**

只有水位补不上的那个洞
======================
油表解决了"模型看不见自己有多满"。但撞墙是个**速率**问题::

    第 9 轮：占用 58%          ← 水位触发器（七成）不响
    第 10 轮：一个工具返回 30 KB 日志
    第 10 轮末：占用 118%      ← 已经被 llama.cpp 静默截断了

水位在 58% 和 118% 之间**没有采样点**，它从来没有机会响。而这**不是**把阈值从 0.7
调到 0.5 能解决的：调低只是把同一个洞往前挪，遇到更大的单次增量照样跨过去。

本文件钉四件：

1. 烧率是**量**出来的，不是拍的；
2. 压缩造成的**负增量绝不能算进烧率**（否则压完一次就再也不压了）；
3. 判不了就说判不了 —— **不猜一个跑道出来**（编出来的"还能跑 20 轮"比没有更危险）；
4. 速率触发器真的接进了压缩判据，而水位那条一条没撤。
"""

from __future__ import annotations

import pytest

import core.context_archive as ca
import core.context_compaction as cc
import core.context_runway as cr


@pytest.fixture(autouse=True)
def isolated_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_ROOT", tmp_path / "context_archive")
    monkeypatch.delenv("GALAXY_MAX_TOKENS_ANSWER", raising=False)


def _msgs(n: int = 200, size: int = 300):
    """够大的一段会话。

    **窗口不能取小**：``_runway_is_short`` 里的占用含回复留白（4096），窗口只有几千
    的话，光留白就把窗口占满了 —— 那时无论烧率多少跑道都是 0，测出来的是"已经超了"
    而不是"跑道短"。第一版就踩了这个：两条断言一条假过、一条假败。
    """
    out = [{"role": "system", "content": "你是 Galaxy 助手。"}]
    for i in range(n):
        out.append({"role": "user", "content": f"第{i}轮" + "问" * size})
    return out


class TestTheBurnRateIsMeasured:
    """没人能凭空写出"一轮烧多少 token" —— 它取决于这个任务调什么工具。"""

    def test_it_takes_the_worst_recent_round_not_the_average(self):
        """估小 → 跑道估长 → **撞墙被静默截断**；估大 → 提前压一次 → 丢一点细节。

        方向性后果不对称，所以取最大。
        """
        assert cr.burn_per_round([0, 100, 200, 5000, 5100]) == 4800

    def test_a_compaction_dip_is_never_counted_as_burn(self):
        """**这条是最要紧的。**

        压缩让占用大幅回落。把那个负差值算进烧率，烧率会被拉到接近 0，跑道变成
        "还能跑很远"，于是**压完一次就再也不压了** —— 一个会自己失效的闭环。
        """
        marks = [1000, 2000, 3000, 400, 1400]  # 第 4 个是压缩后的回落
        assert cr.burn_per_round(marks) == 1000, "把压缩造成的回落算进烧率了"

    def test_it_forgets_old_rounds(self):
        """任务节奏会变（前半程读文件、后半程纯推理，差一个数量级）。"""
        spike_then_calm = [0, 90000] + [90000 + i * 10 for i in range(1, cr.BURN_WINDOW_ROUNDS + 2)]
        assert cr.burn_per_round(spike_then_calm) == 10, "早期的异常值把烧率永久钉死了"

    def test_too_few_observations_is_unknown_not_zero(self):
        """两个观测点只能得到一个差值，那不是"速率"是"一个样本"。"""
        assert cr.burn_per_round([100, 200]) == 0
        assert cr.burn_per_round(None) == 0

    def test_a_flat_stretch_is_unknown_not_a_zero_burn_rate(self):
        """几轮没调工具 ≠ 烧率为 0 —— 那是"这段时间没有可用于估速率的样本"。"""
        assert cr.burn_per_round([500, 500, 500, 500]) == 0

    def test_the_observation_list_cannot_grow_without_bound(self):
        marks = []
        for i in range(200):
            cr.record_mark(marks, i * 10)
        assert len(marks) <= cr.BURN_WINDOW_ROUNDS + 1


class TestItRefusesToGuessARunway:
    """一个编出来的"还能跑 20 轮"比没有更危险 —— 模型会据此决定不整理上下文。"""

    def test_an_unknown_runway_is_not_an_infinite_one(self):
        r = cr.project(1000, 8192, marks=None)
        assert not r.known
        assert r.rounds_left < 0, "判不了却报了一个非负的轮数"
        assert r.render() == ""

    def test_an_unknown_window_yields_unknown(self):
        assert not cr.project(1000, 0, [0, 100, 200, 300]).known

    def test_an_unknown_runway_never_triggers_compaction(self):
        """判不了不动手 —— 与 should_compact / effective_tier 同一个立场。"""
        assert cr.UNKNOWN.is_short is False

    def test_a_known_runway_reports_both_the_rate_and_the_rounds(self):
        r = cr.project(used_tokens=4000, n_ctx=10000, marks=[0, 1000, 2000, 3000])
        assert r.known and r.burn_per_round == 1000 and r.rounds_left == 6
        assert "1000" in r.render() and "6" in r.render()

    def test_it_says_out_loud_when_the_next_round_overflows(self):
        r = cr.project(used_tokens=9900, n_ctx=10000, marks=[0, 5000, 10000, 15000])
        assert r.rounds_left == 0
        assert "下一轮就会溢出" in r.render()


class TestTheRateTriggerCatchesWhatTheLevelTriggerCannot:
    """水位从来没有机会响的那种形态。"""

    def test_a_session_well_under_the_threshold_still_compacts_when_the_runway_is_short(self):
        msgs = _msgs()
        n_ctx = int(cc.estimate_tokens(msgs) / 0.5)  # 占用约五成，远不到七成
        assert cc.context_utilization(msgs, n_ctx) < cc.COMPACT_AT_UTILIZATION
        assert not cc.should_compact(msgs, n_ctx), "水位没到，不该由水位触发"
        assert not cc.should_compact(msgs, n_ctx, [0, 10, 20, 30]), "烧得很慢也不该触发 —— 否则下一条断言说明不了问题"

        # 每轮烧掉窗口的三成 —— 再跑一轮就溢出了
        burn = int(n_ctx * 0.3)
        marks = [burn * i for i in range(4)]
        assert cc.should_compact(msgs, n_ctx, marks), "跑道只够一轮了，却还在等水位"

    def test_a_roomy_session_is_still_left_alone(self):
        """跑道长就不该压 —— 提前压是白丢细节。"""
        msgs = _msgs()
        n_ctx = int(cc.estimate_tokens(msgs) / 0.5)
        assert not cc.should_compact(msgs, n_ctx, [0, 10, 20, 30])

    def test_without_observations_it_falls_back_to_the_level_trigger_only(self):
        """不给观测 ≠ 假装跑道很长；就是退回只看水位。"""
        msgs = _msgs()
        tight = int(cc.estimate_tokens(msgs) / 0.9)
        assert cc.should_compact(msgs, tight, None), "水位到了却因为没有跑道数据而不压"

    def test_the_level_trigger_was_not_removed(self):
        import inspect

        src = inspect.getsource(cc.should_compact)
        assert "COMPACT_AT_UTILIZATION" in src, "水位那条被速率触发器取代了 —— 两个盯的不是同一种失败"


class TestItIsWiredIntoTheLiveLoop:
    """判据接上了但没人喂观测，等于没接。"""

    def test_the_gauge_records_an_observation_per_tool_result(self):
        import inspect

        import core.openclawd as oc

        src = inspect.getsource(oc.OpenClawd._fuel_gauge_suffix)
        assert "record_mark(" in src, "没有人记观测点，烧率永远算不出来"
        assert "marks)" in src, "记了却没交给油表"

    def test_the_compaction_check_receives_the_same_observations(self):
        import inspect

        import core.openclawd as oc

        src = inspect.getsource(oc.OpenClawd._compact_context_if_needed)
        assert "_react_token_marks" in src, "压缩判据没拿到观测 —— 速率触发器不生效"

    def test_the_observations_are_cleared_when_the_loop_ends(self):
        """烧率是**这一次任务**的速率：一个读大文件、一个纯推理，差一个数量级。"""
        import inspect

        import core.openclawd as oc

        src = inspect.getsource(oc.OpenClawd._react_loop)
        assert "self._react_token_marks = []" in src

    def test_the_runway_reaches_the_model(self):
        msgs = _msgs()
        gauge = cc.fuel_gauge(msgs, 100000, 0, marks=[0, 20000, 40000, 60000])
        assert "还能跑" in gauge or "只够再跑" in gauge, f"油表里没有跑道：{gauge}"

    def test_the_tool_description_tells_the_model_to_watch_it(self):
        """判据摆在眼前但没人告诉模型那是判据，它不会用。"""
        import core.openclawd as oc

        desc = oc._CONTEXT_BUILTIN_TOOLS[0]["function"]["description"]
        assert "只够再跑几轮" in desc
