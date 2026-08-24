#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_brain_roster_slots.py

钉住：**主脑名册 —— 一个档里可以是一个模型，也可以是两个，上层不必分两套写法。**

背景
====
``Tier.kind`` 早就写着 ``"single" | "composite"``，但注释里跟着一句
"当前无复合档"，而 ``kind`` 全仓只在一处被读到（``catalog_snapshot`` 导给面板），
**没有任何逻辑分支**。也就是说复合档是个声明出来的空壳。

真要跑两个模型，缺的不是"能不能同时加载"（``compute_scheduler`` 本就允许
``max_gpu_models=3``，``reconcile_tier`` 本就会把整档模型逐个加载），缺的是
**谁是谁**：两个模型进来之后，没有任何地方说得清"哪个是感知位、哪个是推理位、
各自落在哪块加速器上、谁不许被踢"。

于是本文件钉三件事：

1. 槽位是档位构成的**唯一定义处**，``model_tags`` 由它派生（不许两处各存一份）；
2. 单模型档的槽位角色是 ``both`` —— 于是"问感知位是谁"和"问推理位是谁"得到
   同一个答案，**跑一个还是两个，上层代码一模一样**；
3. **可插拔**：槽位持有候选表，换型号就是在同一位里换一个候选 —— 角色、落位、
   常驻策略、上层怎么问它，全都不变。常驻的是**推理位**（重载最贵那位），
   感知位随时可换（见 tests/test_reasoning_slot_stays_resident.py 的判据说明）。
"""

from __future__ import annotations

import pytest

import core.model_catalog as mc
from core.model_catalog import SLOT_BOTH, SLOT_PERCEPTION, SLOT_REASONING


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    """隔离统一状态记录与环境 —— 与 tests/test_model_catalog_tiers.py 同一个范式。

    **本文件此前一个 fixture 都没有**，于是两件事同时成立：

    * 它读的是仓库里那份真的 ``runtime/model_state.json`` —— 别的进程（或人）
      在里面留下的选择会直接改变本文件的结论；
    * 它自己还 ``save_tier("C")`` **往那份真文件里写**，把选择留给后面所有人。

    以前看不出来：推理位候选表只有一个元素，``model_for_role`` 读到什么状态都
    回落到同一个 tag，于是"没隔离"与"隔离了"没有可观测差别。C 档推理位变成
    二选一之后，这个洞立刻变成"上一个进程选过 Agents-A1 → 本文件红"——实测就是
    这么红的。

    ``_STATE_FILE`` 在 ``runtime/`` 下，而 ``GALAXY_DATA_DIR`` 管的是 ``data/`` ——
    设那个环境变量**不隔离这份状态**，必须像这里一样直接改指针。
    """
    monkeypatch.setattr(mc, "_STATE_FILE", tmp_path / "runtime" / "model_state.json")
    monkeypatch.setattr(mc, "_LEGACY_TIER_FILE", tmp_path / ".galaxy_tier")
    monkeypatch.setattr(mc, "_LEGACY_MODEL_FILE", tmp_path / ".galaxy_model")
    for k in ("GALAXY_MODEL_TIER", "GALAXY_NATIVE_AUDIO", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
        monkeypatch.delenv(k, raising=False)
    yield


class TestSlotsAreTheSingleDefinition:
    def test_model_tags_is_derived_from_slots(self):
        """两处各存一份必然漂：改了槽位忘了改 tags，档位就自相矛盾。"""
        for tier in mc.all_tiers():
            flat = [t for s in tier.slots for t in s.candidates]
            assert tier.model_tags == list(dict.fromkeys(flat))

    def test_every_candidate_exists_in_the_catalog(self):
        for tier in mc.all_tiers():
            for slot in tier.slots:
                assert slot.candidates, f"{tier.key} 档的 {slot.role} 位没有任何候选"
                for tag in slot.candidates:
                    assert mc.get_model(tag) is not None, f"{tier.key} 档 {slot.role} 位的候选 {tag} 在目录里查不到"

    def test_slot_roles_are_from_the_known_set(self):
        known = {SLOT_PERCEPTION, SLOT_REASONING, SLOT_BOTH}
        for tier in mc.all_tiers():
            for slot in tier.slots:
                assert slot.role in known, f"{tier.key} 档冒出一个没人认识的角色 {slot.role!r}"


class TestOneModelAndTwoModelsLookTheSameFromAbove:
    def test_single_tier_answers_both_roles_with_the_same_model(self):
        """这条正是"选一个或选两个"的落点：上层按角色问，不必先问"配了几个"。"""
        for key in ("A", "B"):
            tier = mc.get_tier(key)
            assert tier.kind == "single"
            perception = tier.slot_for(SLOT_PERCEPTION)
            reasoning = tier.slot_for(SLOT_REASONING)
            assert perception is not None and reasoning is not None
            assert perception.tag == reasoning.tag, f"{key} 档只有一个模型，两个角色却指到了不同型号"

    def test_composite_tier_answers_the_two_roles_with_two_models(self):
        tier = mc.get_tier("C")
        assert tier.kind == "composite"
        assert tier.slot_for(SLOT_PERCEPTION).tag == "openbmb/minicpm-o4.5"
        assert tier.slot_for(SLOT_REASONING).tag == "qwen3.6:35b-a3b"

    def test_module_level_helper_follows_the_active_tier(self, monkeypatch):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "A")
        assert mc.model_for_role(SLOT_PERCEPTION) == mc.model_for_role(SLOT_REASONING)
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        assert mc.model_for_role(SLOT_PERCEPTION) != mc.model_for_role(SLOT_REASONING)
        assert mc.model_for_role(SLOT_REASONING) == "qwen3.6:35b-a3b"


class TestPlacementKeepsTheTwoModelsOffEachOthersMemory:
    def test_composite_slots_land_on_different_accelerators(self):
        """两个模型挤同一块卡，8 GB 显存装不下 —— 分开落位是双模型成立的前提。"""
        tier = mc.get_tier("C")
        placements = {s.role: s.placement for s in tier.slots}
        assert placements[SLOT_PERCEPTION] == "intel_igpu"
        assert placements[SLOT_REASONING] == "cuda"
        assert placements[SLOT_PERCEPTION] != placements[SLOT_REASONING]

    def test_single_tier_leaves_placement_to_the_scheduler(self):
        for key in ("A", "B"):
            for slot in mc.get_tier(key).slots:
                assert slot.placement == "auto", "单模型档写死落位等于替调度器做了它该按实测硬件做的决定"


class TestResidency:
    def test_reasoning_slot_is_resident_and_perception_is_swappable(self):
        """判据是重载代价：35B 重载几十秒起，感知位最小的只有 1.8 GB 且心跳会再要它。"""
        tier = mc.get_tier("C")
        assert tier.slot_for(SLOT_REASONING).resident is True, "推理位不常驻 —— 每次显存一紧就重做最贵的那步"
        assert tier.slot_for(SLOT_PERCEPTION).resident is False, "感知位钉住就换不动了，与可插拔冲突"

    def test_resident_tags_and_is_resident_agree(self, monkeypatch):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        monkeypatch.delenv("GALAXY_PERCEPTION_MODEL", raising=False)
        assert mc.resident_tags() == ["qwen3.6:35b-a3b"]
        assert mc.is_resident("qwen3.6:35b-a3b") is True
        assert mc.is_resident("openbmb/minicpm-o4.5") is False

    def test_unknown_tag_is_not_resident(self, monkeypatch):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        assert mc.is_resident("") is False
        assert mc.is_resident("some-model-nobody-registered") is False


class TestCompositeTierMainBrainIsTheReasoningSlot:
    def test_save_tier_c_points_ollama_model_at_the_reasoning_slot(self, monkeypatch, tmp_path):
        """``OLLAMA_MODEL`` 这个派生量只能指一个，它代表**文本主脑**。

        若按"档内第一个 source=local 的模型"取，C 档会指到感知位（MiniCPM 是
        ``local``、推理位是 ``llama_cpp``），于是所有文本请求都落到感知位上。
        """
        monkeypatch.setattr(mc, "_STATE_FILE", tmp_path / "model_state.json")
        monkeypatch.delenv("GALAXY_MODEL_TIER", raising=False)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        chosen = mc.save_tier("C")
        assert chosen == "qwen3.6:35b-a3b"

    def test_explicit_main_brain_still_wins(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mc, "_STATE_FILE", tmp_path / "model_state.json")
        monkeypatch.delenv("GALAXY_MODEL_TIER", raising=False)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        assert mc.save_tier("C", main_brain="openbmb/minicpm-o4.5") == "openbmb/minicpm-o4.5"
