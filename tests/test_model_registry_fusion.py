"""tests/test_model_registry_fusion.py
==========================================

域1 · 模型登记融合:model_catalog 成为唯一门 —— 档位 + 主脑合成【一条】记录
(runtime/model_state.json),save_tier / save_choice / save_main_brain 全部收敛到它;
OLLAMA_MODEL / GALAXY_MODEL_TIER 从记录派生;尺寸/默认主脑由目录拥有;旧的
.galaxy_tier / .galaxy_model 一次性迁移。
"""

from __future__ import annotations

import json

import pytest

import core.model_catalog as mc
import core.model_selection as ms


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """把统一记录 + 旧文件隔离到临时目录,并清掉会覆盖记录的 env。"""
    monkeypatch.setattr(mc, "_STATE_FILE", tmp_path / "runtime" / "model_state.json")
    monkeypatch.setattr(mc, "_LEGACY_TIER_FILE", tmp_path / ".galaxy_tier")
    monkeypatch.setattr(mc, "_LEGACY_MODEL_FILE", tmp_path / ".galaxy_model")
    monkeypatch.setattr(ms, "_CHOICE_FILE", tmp_path / ".galaxy_model")
    monkeypatch.delenv("GALAXY_MODEL_TIER", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    yield


# ── 目录拥有尺寸 / 默认 ──


def test_catalog_owns_sizes_and_default():
    assert mc.default_model() == "gemma4:12b"
    sizes = {s.tag: s.size_mb() for s in mc.all_models()}
    assert sizes["gemma4:e2b"] == 1800
    assert sizes["openbmb/minicpm-o4.5"] == 6000
    # ModelSpec.size_mb 不再反向依赖 LocalBrainManager
    assert mc.get_model("gemma4:12b").size_mb() == 8000


def test_local_brain_manager_derives_from_catalog():
    from core.local_brain_manager import LocalBrainManager as L

    assert L.RECOMMENDED_MODELS["default"] == mc.default_model()
    assert L.MODEL_SIZE_ESTIMATE_MB["gemma4:e2b"] == 1800


# ── 一条记录 + 派生 env ──


def test_save_tier_writes_single_record_and_derives_env(monkeypatch):
    chosen = mc.save_tier("B", main_brain="openbmb/minicpm-o4.5")
    assert chosen == "openbmb/minicpm-o4.5"
    # 一条记录 —— 钉的是"**一个**存点装下全部选择",不是"恰好两个键"。
    # 感知位做成可换之后记录里多了 perception_brain 一栏,那仍然是同一条记录;
    # 真正要拦的是它重新分裂成 .galaxy_tier / .galaxy_model 那种多存点(见文末)。
    rec = json.loads(mc._STATE_FILE.read_text(encoding="utf-8"))
    assert rec["tier"] == "B"
    assert rec["main_brain"] == "openbmb/minicpm-o4.5"
    assert set(rec) <= {"tier", "main_brain", "perception_brain"}, f"记录里冒出了没登记的键: {set(rec)}"
    assert len(list(mc._STATE_FILE.parent.glob("model_state*.json"))) == 1, "状态又分裂成多个文件了"
    # 派生 env
    import os

    assert os.environ["GALAXY_MODEL_TIER"] == "B"
    assert os.environ["OLLAMA_MODEL"] == "openbmb/minicpm-o4.5"
    # 不再写旧的分裂文件
    assert not mc._LEGACY_TIER_FILE.exists()
    assert not mc._LEGACY_MODEL_FILE.exists()


def test_save_tier_defaults_main_brain_to_first_local():
    chosen = mc.save_tier("A")  # 未指定主脑 → 档内第一个本地
    assert chosen == "gemma4:e2b"
    assert mc.main_brain() == "gemma4:e2b"


def test_explicit_main_brain_respected_even_if_off_catalog():
    chosen = mc.save_tier("A", main_brain="my/custom-gguf")
    assert chosen == "my/custom-gguf"  # 显式一律尊重,不被静默改回档内第一个
    assert mc.main_brain() == "my/custom-gguf"


# ── model_selection 收敛到同一门 ──


def test_save_choice_routes_to_catalog_record(monkeypatch):
    monkeypatch.setattr(mc, "load_tier", lambda: "A")
    ms.save_choice("gemma4:e4b")
    # 写进统一记录(不再独立写 .galaxy_model)
    rec = json.loads(mc._STATE_FILE.read_text(encoding="utf-8"))
    assert rec["main_brain"] == "gemma4:e4b"
    assert not ms._CHOICE_FILE.exists()
    # load_choice 读回同一记录
    assert ms.load_choice() == "gemma4:e4b"


def test_env_overrides_record(monkeypatch):
    mc.save_tier("A", main_brain="gemma4:e2b")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b")
    monkeypatch.setenv("GALAXY_MODEL_TIER", "B")
    assert mc.main_brain() == "gemma4:12b"  # env 优先
    assert mc.load_tier() == "B"


# ── 迁移:旧的分裂存点 → 一条记录 ──


def test_migration_from_legacy_split_files():
    mc._LEGACY_TIER_FILE.write_text("B", encoding="utf-8")
    mc._LEGACY_MODEL_FILE.write_text("openbmb/minicpm-o4.5", encoding="utf-8")
    # 统一记录不存在 → 从旧文件迁移读入
    assert mc.load_tier() == "B"
    assert mc.main_brain() == "openbmb/minicpm-o4.5"
