#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_c_tier_has_a_second_reasoning_candidate.py

钉住：**Agents-A1 是 C 档推理位的第二候选，不是新的一档；而且没量过的驻留量
不许跟邻居借。**

为什么是候选不是档
==================
``model_catalog`` 自己写下的定义：档是**硬件门槛**的单位（``_TIER_KEYS`` 的
"由低到高"指的就是门槛），候选是同门槛内的选择。D 档单列，是因为 9B 稠密
**不欠专家卸载这张票**，门槛差着一整级；Agents-A1 与现任同为 35B-A3B、同样
靠专家卸载、同样 262144 —— 门槛一模一样。两个门槛相同的档会让
``recommend_tier`` 分不出来、``tier_is_runnable`` 对两者给同一个答案。

本文件钉四件
============
1. **默认一个字没动** —— 候选表第一个仍是现任，加一个候选不改变任何既有行为；
2. **加候选不抬高门槛** —— 足迹按"在岗的"算，不按"全部候选"算；
3. **没量过的驻留量不许跟同架构邻居借** —— 这条正是 ``runtime_mb_val`` 存在的
   理由，而借来的数会让准入把放不下的判成放得下；
4. **每个型号的专家卸载拆分各算各的** —— 目录里那句警告，在这张表只有一个元素
   时**没有对手**，今天才第一次真的有。
"""

from __future__ import annotations

import asyncio

import pytest

import core.model_catalog as mc

INCUMBENT = "qwen3.6:35b-a3b"
NEWCOMER = "agents-a1:35b-a3b"


class TestTheDefaultDidNotMove:
    """加一个候选，是加法不是改法。"""

    def test_the_first_candidate_is_still_the_incumbent(self):
        slot = mc._TIERS["C"].slot_for(mc.SLOT_REASONING)
        assert slot.candidates[0] == INCUMBENT, "默认换人了 —— BrainSlot.tag 取的就是第一个"
        assert NEWCOMER in slot.candidates

    def test_nobody_selected_means_the_incumbent_runs(self, monkeypatch):
        monkeypatch.setattr(mc, "main_brain", lambda: "")
        assert mc.model_for_role(mc.SLOT_REASONING, "C") == INCUMBENT
        assert mc.active_tags("C") == ["openbmb/minicpm-o4.5", INCUMBENT]

    def test_a_stale_or_foreign_pick_falls_back_to_the_incumbent(self, monkeypatch):
        """选中的那个不在本位候选里（改过目录 / 旧版状态 / 从别的档带过来）。"""
        for stale in ("不存在的型号", "qwythos-9b-v2", "gemma4:e2b"):
            monkeypatch.setattr(mc, "main_brain", lambda s=stale: s)
            assert mc.model_for_role(mc.SLOT_REASONING, "C") == INCUMBENT, f"{stale} 被当成了 C 档推理位"


class TestAddingACandidateDoesNotRaiseTheBarrier:
    """候选表里没被选中的那几个根本不会加载，计进来就是把门槛虚高一大截。"""

    def test_the_tier_footprint_counts_only_who_is_on_duty(self, monkeypatch):
        monkeypatch.setattr(mc, "main_brain", lambda: "")
        lo, hi = mc.tier_runtime_footprint_range_mb("C")

        # 若改成按全部候选求和，新来的 21 GB 会整个加进去 —— 这是那次回归的形状
        all_candidates_sum = sum(
            mc.exact_model(t).runtime_mb() for slot in mc._TIERS["C"].slots for t in slot.candidates
        )
        assert hi < all_candidates_sum, f"足迹({hi})把没在岗的候选也算进来了(全算是 {all_candidates_sum})"
        assert lo == 18300 and hi == 29000, f"默认选择下的足迹变了：({lo},{hi})"

    def test_selecting_the_newcomer_does_change_the_footprint(self, monkeypatch):
        """反面：真选中了就必须反映出来，否则上面那条也说明不了问题。"""
        monkeypatch.setattr(mc, "main_brain", lambda: NEWCOMER)
        assert mc.model_for_role(mc.SLOT_REASONING, "C") == NEWCOMER
        assert mc.tier_runtime_footprint_range_mb("C") != (18300, 29000)


class TestAnUnmeasuredResidentIsNotBorrowed:
    """**这条是最要紧的。** 同架构同尺寸的邻居就在隔壁，抄过来最省事也最危险。"""

    def test_it_did_not_copy_the_neighbours_measured_number(self):
        spec = mc.exact_model(NEWCOMER)
        incumbent = mc.exact_model(INCUMBENT)
        assert incumbent.runtime_mb_val > 0, "现任那个数是实测的，前提没了这条测试就没意义"
        assert spec.runtime_mb_val != incumbent.runtime_mb_val, (
            "把邻居实测的驻留量抄了过来 —— 同架构不等于同一份实测，" "而抄错的方向恰好是'判成放得下、加载到一半 OOM'"
        )

    def test_unmeasured_falls_back_to_the_whole_weight(self):
        spec = mc.exact_model(NEWCOMER)
        if spec.runtime_mb_val == 0:
            assert spec.runtime_mb() == spec.size_mb(), "没量过就该退回整权重（保守但不是编的）"

    def test_the_two_opposite_consequences_hold_while_it_is_unmeasured(self, monkeypatch):
        """留 0 的两个后果方向相反，读的人必须一起知道 —— 所以一起钉。

        写成"只要还没量就……"的形状：等有人量出真值填进来，这条不会假红，
        而是自动去断言另一半。
        """
        spec = mc.exact_model(NEWCOMER)
        monkeypatch.setattr(mc, "main_brain", lambda: NEWCOMER)
        lo, hi = mc.tier_runtime_footprint_range_mb("C")

        if spec.runtime_mb_val == 0:
            # ① 准入侧：没量过就不声称放得下 —— 乐观与悲观重合
            assert lo == hi, f"没量过却报出了一个乐观值：({lo},{hi})"
            # ② 加载侧：判据"MoE 且 runtime < 整权重"取假 → 不会因缺 --n-cpu-moe 改判 llama_server
            assert not (spec.runtime_mb() < mc.effective_weight_mb(NEWCOMER))
        else:
            # 量过之后两条一起归位
            assert lo < hi, "量过了却还报成一个点 —— 专家卸载的便宜没体现出来"
            assert spec.runtime_mb() < mc.effective_weight_mb(NEWCOMER)

    def test_the_family_fallback_cannot_answer_a_vram_question(self):
        """``get_model`` 会按 root 兜底，``exact_model`` 不会 —— 显存一律走后者。"""
        assert mc.get_model("agents-a1:随便什么").tag == NEWCOMER
        assert mc.exact_model("agents-a1:随便什么") is None
        assert mc.runtime_footprint_mb("agents-a1:随便什么") == 0


class TestBothCandidatesShareOneLoaderPath:
    """门槛一样，正是它该当候选而不是新开一档的理由。"""

    @pytest.mark.parametrize("tag", [INCUMBENT, NEWCOMER])
    def test_same_source_same_moe_same_context(self, tag):
        spec = mc.exact_model(tag)
        assert spec.source == "llama_cpp"
        assert spec.is_moe is True, "目录必须**明确**填 True，不能靠命名惯例猜"
        assert mc.resolve_is_moe(tag) is True
        assert spec.max_ctx() == 262144
        assert spec.caps.tools is True

    @pytest.mark.parametrize("tag", [INCUMBENT, NEWCOMER])
    def test_the_reasoning_slot_stays_text_only(self, tag):
        """看/听是感知位的活。推理位多一份视觉塔只是白占显存，还会让能力聚合算错。"""
        spec = mc.exact_model(tag)
        assert spec.caps.vision is False
        assert spec.caps.audio_in is False and spec.caps.audio_out is False


class TestTheSplitIsRecomputedPerModel:
    """目录里那句"换完必须重走 _split_moe"，在候选表只有一个元素时**没有对手**。"""

    def test_each_model_is_scheduled_with_its_own_numbers(self, monkeypatch):
        from core.compute_scheduler import ComputeScheduler

        seen: list[tuple] = []

        async def _fake_schedule(self, tag, size_mb, **kw):
            seen.append((tag, size_mb, kw.get("is_moe"), kw.get("runtime_mb")))
            return None

        class _Backend:
            async def load_model(self, _tag):
                return True

            async def unload_model(self, _tag):
                return True

        monkeypatch.setattr(ComputeScheduler, "schedule_model", _fake_schedule, raising=True)
        monkeypatch.setattr(ComputeScheduler, "_create_backend", lambda self, name: _Backend())
        monkeypatch.setattr(mc, "main_brain", lambda: NEWCOMER)

        sched = ComputeScheduler()
        asyncio.run(sched.reconcile_tier("C"))

        got = {t: (size, moe, rt) for t, size, moe, rt in seen}
        assert NEWCOMER in got, f"新候选选中了却没被换档加载：{list(got)}"
        size, moe, rt = got[NEWCOMER]
        spec = mc.exact_model(NEWCOMER)
        assert size == spec.size_mb() and rt == spec.runtime_mb(), (
            f"传的不是它自己的数({size},{rt})，而 spec 是({spec.size_mb()},{spec.runtime_mb()}) "
            "—— 沿用上一位的分配正是目录里警告的那件事"
        )
        assert moe is True, "换档加载没认出它是 MoE —— 专家卸载会静默失效"
        # 反面：现任没被选中，就不该被拉起来占显存
        assert INCUMBENT not in got, "没在岗的候选也被加载了"


class TestTheGgufChainDoesNotSmuggleInSomethingElse:
    """回退不该悄悄把用户换成另一个东西 —— 与 qwythos 不列 abliterated 同一条。"""

    def test_the_official_build_comes_first(self):
        import core.hf_ollama_import_fallback as fb

        chain = fb.HF_GGUF_CANDIDATES[NEWCOMER]
        assert chain[0].startswith("InternScience/"), f"官方 GGUF 不在第一位：{chain}"

    def test_no_vision_build_in_the_chain(self):
        import core.hf_ollama_import_fallback as fb

        for repo in fb.HF_GGUF_CANDIDATES[NEWCOMER]:
            low = repo.lower()
            assert (
                "vision" not in low and "-vl" not in low
            ), f"{repo} 会让推理位悄悄多出视觉能力 —— 能力聚合会把'看'算到它头上"
