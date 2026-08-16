"""tests/test_tts_compute_fit_v1.py
====================================
Tests for TTS engine / local-compute fit pre-checking (V1).

要解决的问题
------------
引擎选择只读一个环境变量,合不合得上本机算力**要等到合成那一刻才知道**。
``indextts`` 自己的文档就写着"自回归大模型,纯 CPU 合成一句要数秒到数十秒"——
用户选了它、按下说话、等十几秒,才发现这台机器跑不动。

范围(如实记下,免得读的人以为这里有更多东西)
-------------------------------------------
本仓库的 TTS 引擎**绝大多数本来就是 CPU 设计**:kokoro"纯 CPU 快于实时"、
melo"CPU 秒级"、piper"树莓派都能跑"、edge 云端、sapi 系统自带。
**唯一真正吃算力的是 indextts。** 所以这不是"在一堆引擎间智能调度",
而是更小也更实在的一件事:选择时判断跑不跑得动,跑不动就讲出来。

Coverage matrix
---------------
Group A — Policy sentinels
  A01. IS_ADVISORY_POLICY — 本模块不选引擎、不合成。
  A02. NEVER_OVERRIDES_EXPLICIT_CHOICE_POLICY — 显式选择永远被尝试。
  A03. UNKNOWN_MEANS_UNRESTRICTED_POLICY — 探测不到即不设限。

Group B — Requirements table
  B01. 表覆盖 speech_output 实际会选的全部引擎。
  B02. 每条都注明出处,可核对而非只能相信。
  B03. 只有 indextts 被标为非 CPU 可用——这是结论,不是缺口。
  B04. 云端/系统引擎标为不需要本地算力。

Group C — Fit assessment
  C01. CPU 可用的引擎恒为 fits,且不去探测硬件。
  C02. 显存充足时 indextts fits。
  C03. 显存不足时不 fits,理由里带实测值与需求值。
  C04. 不 fits 时给出的替代方案都是 CPU 可用的。
  C05. 探测不可用(None)时 fits=True 且 probed=False。
  C06. 无 GPU(测得 0)与探测不到(None)是不同结论。
  C07. 未知引擎不设限。
  C08. 硬件画像抛异常时降级为不设限,不外抛。
  C09. to_dict() 可 JSON 序列化。

Group D — Fallback chain filtering
  D01. 非显式的不适配引擎被跳过。
  D02. 显式选择即使不适配也保留(POLICY_2)。
  D03. static 档完全不过滤。
  D04. 过滤后为空时回退到原链——过滤器不该是系统失声的原因。
  D05. 全部适配时链保持不变。

Group E — Wiring
  E01. speech_output 在选择时做预检。
  E02. 预检只告警不改选(不出现赋值给 choice)。
  E03. flag 已登记。
"""

from __future__ import annotations

import inspect
import json

import pytest

from core.tts.compute_fit import (
    ENGINE_COMPUTE_NEEDS,
    MODE_COMPUTE_AWARE,
    MODE_STATIC,
    assess_engine_fit,
    filter_fallback_chain,
    get_tts_routing_mode,
)


@pytest.fixture(autouse=True)
def _default_mode(monkeypatch):
    monkeypatch.delenv("GALAXY_TTS_ROUTING", raising=False)


# ---------------------------------------------------------------------------
# Group A — Policies
# ---------------------------------------------------------------------------


class TestGroupAPolicies:
    def test_a01_advisory(self):
        from core.tts.compute_fit import TTS_COMPUTE_FIT_IS_ADVISORY_POLICY

        text = TTS_COMPUTE_FIT_IS_ADVISORY_POLICY
        assert "POLICY_1" in text
        assert "does not select engines" in text

    def test_a02_never_overrides_explicit(self):
        from core.tts.compute_fit import TTS_COMPUTE_FIT_NEVER_OVERRIDES_EXPLICIT_CHOICE_POLICY

        text = TTS_COMPUTE_FIT_NEVER_OVERRIDES_EXPLICIT_CHOICE_POLICY
        assert "POLICY_2" in text
        assert "ALWAYS attempted" in text
        assert "never a silent substitution" in text

    def test_a03_unknown_means_unrestricted(self):
        from core.tts.compute_fit import TTS_COMPUTE_FIT_UNKNOWN_MEANS_UNRESTRICTED_POLICY

        text = TTS_COMPUTE_FIT_UNKNOWN_MEANS_UNRESTRICTED_POLICY
        assert "POLICY_3" in text
        assert "capability regression" in text


# ---------------------------------------------------------------------------
# Group B — Requirements table
# ---------------------------------------------------------------------------


class TestGroupBTable:
    def test_b01_covers_every_selectable_engine(self):
        """The table must not quietly omit an engine speech_output can pick."""
        import core.speech_output as mod

        src = inspect.getsource(mod._get_engine)
        selectable = {"edge", "kokoro", "melo", "piper", "sapi", "indextts"}
        for name in selectable:
            assert f'"{name}"' in src or f"_try_{name}" in src, f"{name} not selectable?"
            assert name in ENGINE_COMPUTE_NEEDS, f"{name} missing from the requirements table"

    def test_b02_every_claim_cites_a_source(self):
        for need in ENGINE_COMPUTE_NEEDS.values():
            assert need.source, f"{need.name} has no source"
            assert need.cpu_note, f"{need.name} has no cpu_note"

    def test_b03_only_indextts_is_not_cpu_viable(self):
        """This is the finding, not a gap: the repo's engines are CPU-designed."""
        not_cpu_viable = {n for n, e in ENGINE_COMPUTE_NEEDS.items() if not e.cpu_viable}
        assert not_cpu_viable == {"indextts"}

    def test_b04_offbox_engines_need_no_local_compute(self):
        assert ENGINE_COMPUTE_NEEDS["edge"].needs_local_compute is False
        assert ENGINE_COMPUTE_NEEDS["sapi"].needs_local_compute is False


# ---------------------------------------------------------------------------
# Group C — Assessment
# ---------------------------------------------------------------------------


class TestGroupCAssessment:
    @pytest.mark.parametrize("engine", ["edge", "sapi", "piper", "kokoro", "melo"])
    def test_c01_cpu_viable_always_fits_without_probing(self, engine):
        verdict = assess_engine_fit(engine)
        assert verdict.fits is True
        assert verdict.probed is False, "no need to probe hardware for a CPU-viable engine"

    def test_c02_sufficient_vram_fits(self):
        verdict = assess_engine_fit("indextts", free_vram_mb=8000)
        assert verdict.fits is True
        assert verdict.probed is True

    def test_c03_insufficient_vram_reports_both_numbers(self):
        verdict = assess_engine_fit("indextts", free_vram_mb=2000)
        assert verdict.fits is False
        assert "2000" in verdict.reason
        assert "6000" in verdict.reason

    def test_c04_alternatives_are_all_cpu_viable(self):
        verdict = assess_engine_fit("indextts", free_vram_mb=0)
        assert verdict.suggested_alternatives
        for name in verdict.suggested_alternatives:
            assert ENGINE_COMPUTE_NEEDS[name].cpu_viable

    def test_c05_unprobeable_is_unrestricted(self, monkeypatch):
        import core.tts.compute_fit as mod

        monkeypatch.setattr(mod, "_best_free_vram_mb", lambda: None)
        verdict = assess_engine_fit("indextts")
        assert verdict.fits is True
        assert verdict.probed is False

    def test_c06_no_gpu_and_unknown_are_different_answers(self, monkeypatch):
        """0 means "measured, no GPU"; None means "could not measure"."""
        import core.tts.compute_fit as mod

        monkeypatch.setattr(mod, "_best_free_vram_mb", lambda: 0)
        assert assess_engine_fit("indextts").fits is False
        monkeypatch.setattr(mod, "_best_free_vram_mb", lambda: None)
        assert assess_engine_fit("indextts").fits is True

    def test_c07_unknown_engine_is_unrestricted(self):
        assert assess_engine_fit("some_future_engine").fits is True

    def test_c08_probe_failure_degrades(self, monkeypatch):
        import core.hardware_compute_profiler as hw

        def boom():
            raise RuntimeError("no driver")

        monkeypatch.setattr(hw, "get_compute_profile_sync", boom)
        assert assess_engine_fit("indextts").fits is True

    def test_c09_to_dict_json_safe(self):
        json.dumps(assess_engine_fit("indextts", free_vram_mb=1).to_dict())


# ---------------------------------------------------------------------------
# Group D — Chain filtering
# ---------------------------------------------------------------------------


class TestGroupDChain:
    CHAIN = ["indextts", "edge", "kokoro", "sapi"]

    def test_d01_unfit_non_explicit_is_skipped(self, monkeypatch):
        import core.tts.compute_fit as mod

        monkeypatch.setattr(mod, "_best_free_vram_mb", lambda: 0)
        assert filter_fallback_chain(self.CHAIN) == ["edge", "kokoro", "sapi"]

    def test_d02_explicit_choice_is_kept_even_when_unfit(self, monkeypatch):
        import core.tts.compute_fit as mod

        monkeypatch.setattr(mod, "_best_free_vram_mb", lambda: 0)
        assert filter_fallback_chain(self.CHAIN, explicit_choice="indextts") == self.CHAIN

    def test_d03_static_mode_does_not_filter(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TTS_ROUTING", MODE_STATIC)
        assert filter_fallback_chain(self.CHAIN) == self.CHAIN

    def test_d04_never_returns_an_empty_chain(self, monkeypatch):
        """An over-eager filter must not be the reason the system goes mute."""
        import core.tts.compute_fit as mod

        monkeypatch.setattr(mod, "_best_free_vram_mb", lambda: 0)
        assert filter_fallback_chain(["indextts"]) == ["indextts"]

    def test_d05_all_fit_leaves_chain_unchanged(self):
        chain = ["edge", "kokoro", "sapi"]
        assert filter_fallback_chain(chain) == chain

    def test_d06_mode_resolution(self, monkeypatch):
        assert get_tts_routing_mode() == MODE_COMPUTE_AWARE
        monkeypatch.setenv("GALAXY_TTS_ROUTING", MODE_STATIC)
        assert get_tts_routing_mode() == MODE_STATIC
        monkeypatch.setenv("GALAXY_TTS_ROUTING", "nonsense")
        assert get_tts_routing_mode() == MODE_COMPUTE_AWARE


# ---------------------------------------------------------------------------
# Group E — Wiring
# ---------------------------------------------------------------------------


class TestGroupEWiring:
    def test_e01_speech_output_preflights(self):
        import core.speech_output as mod

        src = inspect.getsource(mod._get_engine)
        assert "assess_engine_fit" in src

    def test_e02_preflight_warns_but_does_not_reassign_choice(self):
        """POLICY_2 in code, not just in prose: the pre-check must not pick for you."""
        import core.speech_output as mod

        src = inspect.getsource(mod._get_engine)
        # The pre-flight region runs from where compute_fit is imported to where
        # the engine chains begin. Slice on the *last* mention so the import line
        # itself does not truncate the region being inspected.
        start = src.index("from core.tts.compute_fit import")
        end = src.index("if choice ==", start)
        preflight = src[start:end]
        assert "logger.warning" in preflight, "an unfit engine must produce a visible diagnostic"
        assert "choice =" not in preflight, "pre-check must never reassign the engine choice"
        assert "_engine =" not in preflight, "pre-check must never select an engine"

    def test_e03_flag_registered(self):
        from flags import get_flag

        flag = get_flag("tts_compute_aware_routing")
        assert flag is not None
        assert flag.env_var == "GALAXY_TTS_ROUTING"
        assert flag.rollout_plan and flag.cleanup_condition
