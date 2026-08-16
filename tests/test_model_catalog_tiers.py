"""tests/test_model_catalog_tiers.py
=======================================

模型目录 SSOT + AB 档位 + 能力驱动 IO + 三份硬编码统一 + API + 档位选择。

核心不变量：
  - 面板(ModelsTab)/config(OLLAMA_MODEL.options)/CLI(model_selection) 三处清单
    统一派生自 core.model_catalog —— 证明不再各存一份会漂移的硬编码。
  - 能力驱动：A 档说走 TTS 桥、B 档全原生；服务门控关时不自欺（声明原生也走桥）。
"""

from __future__ import annotations

import asyncio
import os

import pytest

import core.model_catalog as mc


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    # 隔离统一状态记录 + 旧的迁移文件与环境，避免测试互相污染。
    monkeypatch.setattr(mc, "_STATE_FILE", tmp_path / "runtime" / "model_state.json")
    monkeypatch.setattr(mc, "_LEGACY_TIER_FILE", tmp_path / ".galaxy_tier")
    monkeypatch.setattr(mc, "_LEGACY_MODEL_FILE", tmp_path / ".galaxy_model")
    for k in ("GALAXY_MODEL_TIER", "GALAXY_NATIVE_AUDIO", "OLLAMA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    yield


class TestCatalogStructure:
    def test_tiers_are_ab_single_plus_cd_composite(self):
        """顺序是**按硬件门槛**由低到高，不是字母序 —— D 排在 C 之前是刻意的。

        D 档推理位是稠密 9B(不需专家卸载)，门槛低于 C 档的 35B-A3B。改成字母序
        会让推荐器优先推 D、C 档永远推不出去，见 model_catalog._TIER_KEYS。
        """
        assert [t.key for t in mc.all_tiers()] == ["A", "B", "D", "C"]
        assert [t.kind for t in mc.all_tiers()] == ["single", "single", "composite", "composite"]

    def test_tier_A_is_gemma_single(self):
        t = mc.get_tier("A")
        assert t.kind == "single"
        assert all("gemma" in tag for tag in t.model_tags)

    def test_tier_B_is_minicpm_single(self):
        t = mc.get_tier("B")
        assert t.kind == "single"
        assert t.model_tags == ["openbmb/minicpm-o4.5"]

    def test_no_container_models_remain(self):
        # 容器复合档已删除；目录里不应再有 container 源模型
        assert all(m.source != "container" for m in mc.all_models())

    def test_size_owned_by_catalog_ssot(self):
        # 尺寸现由目录自己拥有(SSOT),不再反向依赖 LocalBrainManager
        spec = mc.get_model("gemma4:e2b")
        assert spec.size_mb() == 1800


class TestCapabilityDrivenIO:
    def test_A_listens_native_speaks_via_bridge(self):
        io = mc.tier_effective_io("A")
        assert io.vision == "native"
        assert io.audio_in == "native"  # Gemma 原生听
        assert io.audio_out == "tts_bridge"  # 但不原生说 → TTS 桥

    def test_B_all_native(self):
        io = mc.tier_effective_io("B")
        assert io.audio_in == "native" and io.audio_out == "native"

    def test_effective_io_takes_union_of_models(self):
        # 多模型集合：任一模型有该能力即 native
        io = mc.effective_io(["gemma4:e2b", "openbmb/minicpm-o4.5"])
        assert io.audio_out == "native"  # 来自 minicpm（gemma 不原生说）
        # 仅 Gemma（不原生说）→ 说要走桥
        io2 = mc.effective_io(["gemma4:e2b"])
        assert io2.audio_out == "tts_bridge"


class TestUnifiedNoHardcode:
    def test_model_selection_derives_from_catalog(self):
        from core.model_selection import list_models

        tags = [t for t, _ in list_models()]
        assert tags == mc.choice_order()

    def test_config_options_derive_from_catalog(self):
        from core.model_catalog import local_choice_options

        # config.py 的 OLLAMA_MODEL.options 现在是空占位，运行时由此填充
        from core.routes.config import CONFIG_SCHEMA

        assert CONFIG_SCHEMA["OLLAMA_MODEL"]["options"] == []
        assert local_choice_options() == mc.choice_order()

    def test_choice_order_is_local_tags_only(self):
        # choice_order 只含本地(Ollama 可拉)模型；无容器模型
        assert mc.choice_order() == [
            "gemma4:e2b",
            "gemma4:e4b",
            "gemma4:12b",
            "openbmb/minicpm-o4.5",
            "qwythos-9b-v2",
            "qwen3.6:35b-a3b",
        ]


class TestTierPersistence:
    def test_save_and_load_tier(self):
        mc.save_tier("B")
        assert mc.load_tier() == "B"

    def test_save_tier_sets_main_brain(self):
        chosen = mc.save_tier("B")
        assert chosen == "openbmb/minicpm-o4.5"
        assert os.environ.get("OLLAMA_MODEL") == "openbmb/minicpm-o4.5"

    def test_single_tier_honors_requested_brain(self):
        chosen = mc.save_tier("A", main_brain="gemma4:e4b")
        assert chosen == "gemma4:e4b"

    def test_infer_tier_from_model(self):
        assert mc.infer_tier_from_model("gemma4:12b") == "A"
        assert mc.infer_tier_from_model("openbmb/minicpm-o4.5") == "B"

    def test_unknown_tier_defaults_A(self):
        assert mc.save_tier("Z") in (mc.choice_order()[0],)
        assert mc.load_tier() == "A"


class TestModalityBridge:
    def test_A_tier_listens_via_asr_bridge(self, monkeypatch):
        # 状态文件已由 autouse fixture 隔离补丁,这里直接用。
        mc.save_tier("A")
        from core.modality_bridge import resolve_audio_in, resolve_audio_out

        assert resolve_audio_in() == "asr_bridge"  # Ollama 不管原生音频 → 桥
        assert resolve_audio_out() == "tts_bridge"

    def test_native_audio_gate_off_stays_bridge_even_for_B(self, monkeypatch):
        mc.save_tier("B")
        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "0")
        from core.modality_bridge import resolve_audio_in

        assert resolve_audio_in() == "asr_bridge"  # 不自欺：服务层没接就走桥

    def test_native_audio_gate_on_enables_native_for_B(self, monkeypatch):
        mc.save_tier("B")
        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
        from core.modality_bridge import resolve_audio_in, resolve_audio_out

        assert resolve_audio_in() == "native"
        assert resolve_audio_out() == "native"

    def test_transcribe_empty_returns_none(self):
        from core.modality_bridge import transcribe_b64

        assert transcribe_b64("") is None


class TestModelsAPI:
    def test_catalog_endpoint_shape(self):
        from core.routes.models import get_catalog

        snap = asyncio.run(get_catalog())
        assert snap["current_tier"] in ("A", "B", "D", "C")
        assert len(snap["tiers"]) == 4
        for t in snap["tiers"]:
            assert "effective_io" in t and "models" in t
            # 槽位要真的出到线上 —— 面板据此显示"哪一位、现在是谁、还能换成谁"。
            assert "slots" in t and t["slots"]
            assert "active_tags" in t
            flat = [c for s in t["slots"] for c in s["candidates"]]
            assert sorted(set(flat)) == sorted({m["tag"] for m in t["models"]}), "候选表与档内模型清单对不上"
            for s in t["slots"]:
                assert s["selected"] in s["candidates"], "选中的那个不在自己的候选里"
                assert s["swappable"] is (len(s["candidates"]) > 1)

    def test_status_endpoint_shape(self):
        from core.routes.models import get_status

        st = asyncio.run(get_status())
        # 本地候选都在（状态可能是 absent，因为测试环境没有 Ollama）
        assert set(st["models"].keys()) == set(mc.choice_order())

    def test_select_tier_endpoint(self, monkeypatch):
        # 屏蔽真实后台拉取与路由刷新
        import core.model_selection as ms
        from core.routes.models import TierSelectRequest, select_tier

        monkeypatch.setattr(ms, "background_pull", lambda tag: None)
        out = asyncio.run(select_tier(TierSelectRequest(tier="B")))
        assert out["success"] is True
        assert out["tier"] == "B"
        assert out["main_brain"] == "openbmb/minicpm-o4.5"

    def test_select_unknown_tier_fails_cleanly(self):
        from core.routes.models import TierSelectRequest, select_tier

        out = asyncio.run(select_tier(TierSelectRequest(tier="Z")))
        assert out["success"] is False
