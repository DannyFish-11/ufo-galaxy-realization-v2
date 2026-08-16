"""tests/test_tts_watermark_v3.py
==================================
Tests for inaudible watermarking of synthesised audio (V3).

为什么这件事值得做
------------------
这个系统能克隆任意音色(``indextts`` 零样本克隆,给一段参考 wav 即可),又能控制
Android 设备。一个既能复刻别人声音、又能实际操作设备的系统,生成完全无标记的音频
是个真实的风险面——不只是合规问题。

本文件最要紧的一组是 B 组
-------------------------
``applied=False`` 单独不构成答案。"策略说不用打"和"想打但打不上"是完全不同的两件事,
把它们混成一句"没有水印",恰恰是本轮改造一路在消除的那类缺陷(读不到 vs 真的没有)。
:attr:`WatermarkResult.failed_despite_wanting` 就是用来把它们分开的。

Coverage matrix
---------------
Group A — Policy sentinels
  A01. SILENT_SKIP_IS_FORBIDDEN_POLICY 要求三态可分。
  A02. NEVER_SILENCES_SPEECH_POLICY 说明默认不阻断,并给出严格档出口。
  A03. CLONED_VOICES_ARE_THE_TARGET_POLICY 说明默认只标克隆音色。

Group B — 三态必须可分(本文件核心)
  B01. 策略跳过:wanted=False,failed_despite_wanting=False。
  B02. 后端缺失:wanted=True,failed_despite_wanting=True。
  B03. 非 wav:明确拒绝且计为"想打没打上",不静默。
  B04. 文件缺失:给出理由。
  B05. to_dict() 暴露 failed_despite_wanting。

Group C — 策略判定
  C01. cloned_only 只对克隆引擎为真。
  C02. always 对任何引擎为真。
  C03. off 恒为假。
  C04. 引擎名与类名两种写法都识别。
  C05. 模式解析:未知值退回默认档而非 off。
  C06. 严格档开关解析。

Group D — 成功路径(mock 后端)
  D01. 后端可用时写回文件并标 applied。
  D02. 失败时不留下 .tmp 残file。
  D03. 编码中途失败不会把原文件截断。

Group E — 与合成路径的接线
  E01. synthesize_to_file 会调用水印。
  E02. 默认档:水印失败不影响返回音频(POLICY_2)。
  E03. 严格档:克隆音色打不上水印 → 丢弃产物并抛出。
  E04. 严格档只作用于"想打没打上",不影响策略跳过的情形。

Group F — flag 登记
  F01. 两个 flag 都已登记。
"""

from __future__ import annotations

import os
import wave

import numpy as np
import pytest

from core.tts.watermark import (
    CLONING_ENGINES,
    MODE_ALWAYS,
    MODE_CLONED_ONLY,
    MODE_OFF,
    apply_watermark,
    get_watermark_mode,
    should_watermark,
    strict_mode_enabled,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GALAXY_TTS_WATERMARK", raising=False)
    monkeypatch.delenv("GALAXY_TTS_WATERMARK_STRICT", raising=False)


@pytest.fixture
def wav_file(tmp_path):
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((np.random.randn(16000) * 3000).astype(np.int16).tobytes())
    return str(path)


# ---------------------------------------------------------------------------
# Group A — Policies
# ---------------------------------------------------------------------------


class TestGroupAPolicies:
    def test_a01_silent_skip_forbidden(self):
        from core.tts.watermark import WATERMARK_SILENT_SKIP_IS_FORBIDDEN_POLICY

        text = WATERMARK_SILENT_SKIP_IS_FORBIDDEN_POLICY
        assert "POLICY_1" in text
        assert "wanted-but-failed" in text

    def test_a02_never_silences_speech(self):
        from core.tts.watermark import WATERMARK_NEVER_SILENCES_SPEECH_POLICY

        text = WATERMARK_NEVER_SILENCES_SPEECH_POLICY
        assert "POLICY_2" in text
        assert "GALAXY_TTS_WATERMARK_STRICT" in text

    def test_a03_cloned_voices_are_the_target(self):
        from core.tts.watermark import WATERMARK_CLONED_VOICES_ARE_THE_TARGET_POLICY

        text = WATERMARK_CLONED_VOICES_ARE_THE_TARGET_POLICY
        assert "POLICY_3" in text
        assert "cloned voices only" in text


# ---------------------------------------------------------------------------
# Group B — Three distinct outcomes
# ---------------------------------------------------------------------------


class TestGroupBThreeStates:
    def test_b01_policy_skip_is_not_a_failure(self, wav_file):
        r = apply_watermark(wav_file, engine_name="EdgeTTSEngine")
        assert r.wanted is False
        assert r.applied is False
        assert r.failed_despite_wanting is False
        assert "策略未要求" in r.skipped_reason

    def test_b02_backend_missing_is_a_failure(self, wav_file, monkeypatch):
        import core.tts.watermark as mod

        monkeypatch.setattr(mod, "watermark_backend_available", lambda: (False, "audioseal 未安装"))
        r = apply_watermark(wav_file, engine_name="IndexTTSEngine")
        assert r.wanted is True
        assert r.applied is False
        assert r.failed_despite_wanting is True, "想打没打上必须是可观测的结果"

    def test_b03_non_wav_is_refused_loudly(self, tmp_path):
        mp3 = tmp_path / "a.mp3"
        mp3.write_bytes(b"ID3")
        r = apply_watermark(str(mp3), engine_name="IndexTTSEngine")
        assert r.failed_despite_wanting is True
        assert "wav" in r.skipped_reason

    def test_b04_missing_file_gives_a_reason(self):
        r = apply_watermark("/definitely/not/here.wav", engine_name="IndexTTSEngine")
        assert r.applied is False
        assert r.skipped_reason

    def test_b05_to_dict_exposes_the_distinction(self, tmp_path):
        mp3 = tmp_path / "a.mp3"
        mp3.write_bytes(b"ID3")
        payload = apply_watermark(str(mp3), engine_name="IndexTTSEngine").to_dict()
        assert payload["failed_despite_wanting"] is True


# ---------------------------------------------------------------------------
# Group C — Policy resolution
# ---------------------------------------------------------------------------


class TestGroupCPolicy:
    def test_c01_cloned_only(self):
        assert should_watermark("IndexTTSEngine", mode=MODE_CLONED_ONLY) is True
        assert should_watermark("EdgeTTSEngine", mode=MODE_CLONED_ONLY) is False

    def test_c02_always(self):
        assert should_watermark("EdgeTTSEngine", mode=MODE_ALWAYS) is True
        assert should_watermark("", mode=MODE_ALWAYS) is True

    def test_c03_off(self):
        assert should_watermark("IndexTTSEngine", mode=MODE_OFF) is False

    def test_c04_both_naming_forms_recognised(self):
        assert "indextts" in CLONING_ENGINES
        assert "IndexTTSEngine" in CLONING_ENGINES
        assert should_watermark("indextts", mode=MODE_CLONED_ONLY) is True

    def test_c05_unknown_mode_falls_back_to_default_not_off(self, monkeypatch):
        """A typo must not silently disable a safety feature."""
        monkeypatch.setenv("GALAXY_TTS_WATERMARK", "enabled")
        assert get_watermark_mode() == MODE_CLONED_ONLY

    @pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("0", False), ("", False)])
    def test_c06_strict_flag(self, monkeypatch, value, expected):
        monkeypatch.setenv("GALAXY_TTS_WATERMARK_STRICT", value)
        assert strict_mode_enabled() is expected


# ---------------------------------------------------------------------------
# Group D — Success path with a stubbed backend
# ---------------------------------------------------------------------------


class _FakeGenerator:
    """Stands in for AudioSeal's generator: returns the input, slightly altered."""

    def __call__(self, tensor, sample_rate=16000, alpha=1.0):
        return tensor * 0.9


class TestGroupDSuccess:
    def _install_fake_backend(self, monkeypatch):
        import sys
        import types

        torch_mod = types.ModuleType("torch")

        class _T:
            def __init__(self, arr):
                self.arr = np.asarray(arr, dtype=np.float32)

            def unsqueeze(self, _dim):
                return self

            def squeeze(self, _dim):
                return self

            def detach(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return self.arr

            def __mul__(self, k):
                return _T(self.arr * k)

        torch_mod.from_numpy = lambda a: _T(a)  # type: ignore[attr-defined]
        audioseal_mod = types.ModuleType("audioseal")
        audioseal_mod.AudioSeal = type(  # type: ignore[attr-defined]
            "AudioSeal", (), {"load_generator": staticmethod(lambda _n: _FakeGenerator())}
        )
        monkeypatch.setitem(sys.modules, "torch", torch_mod)
        monkeypatch.setitem(sys.modules, "audioseal", audioseal_mod)

        import core.tts.watermark as mod

        monkeypatch.setattr(mod, "watermark_backend_available", lambda: (True, ""))

    def test_d01_applies_and_rewrites_the_file(self, wav_file, monkeypatch):
        self._install_fake_backend(monkeypatch)
        before = os.path.getsize(wav_file)
        r = apply_watermark(wav_file, engine_name="IndexTTSEngine")
        assert r.applied is True
        assert r.backend == "audioseal"
        assert os.path.exists(wav_file)
        assert os.path.getsize(wav_file) > 0
        assert before > 0

    def test_d02_no_tmp_file_left_behind(self, wav_file, monkeypatch):
        self._install_fake_backend(monkeypatch)
        apply_watermark(wav_file, engine_name="IndexTTSEngine")
        assert not os.path.exists(f"{wav_file}.wm.tmp.wav")

    def test_d03_failure_leaves_original_intact(self, wav_file, monkeypatch):
        """A mid-encode failure must not leave a truncated audio file behind."""
        import core.tts.watermark as mod

        original = open(wav_file, "rb").read()
        monkeypatch.setattr(mod, "watermark_backend_available", lambda: (True, ""))

        def boom(*a, **k):
            raise RuntimeError("encoder exploded")

        monkeypatch.setattr(mod, "_read_wav_mono_float", boom)
        r = apply_watermark(wav_file, engine_name="IndexTTSEngine")
        assert r.applied is False
        assert open(wav_file, "rb").read() == original
        assert not os.path.exists(f"{wav_file}.wm.tmp.wav")


# ---------------------------------------------------------------------------
# Group E — Wiring into synthesis
# ---------------------------------------------------------------------------


class TestGroupEWiring:
    def test_e01_synthesis_path_invokes_watermarking(self):
        import inspect

        import core.speech_output as so

        assert "_apply_watermark_if_required" in inspect.getsource(so.synthesize_to_file)

    @pytest.mark.asyncio
    async def test_e02_default_mode_does_not_break_synthesis(self, monkeypatch, tmp_path):
        """POLICY_2: a mute assistant is worse than unmarked audio."""
        import core.speech_output as so

        out = tmp_path / "o.wav"
        out.write_bytes(b"RIFF")

        class _Eng:
            async def synthesize(self, text, output_path=None, voice=None):
                return str(out)

        monkeypatch.setattr(so, "_get_engine", lambda: _Eng())
        path = await so.synthesize_to_file("你好")
        assert path == str(out)
        assert os.path.exists(path), "默认档不得因水印失败而丢弃音频"

    @pytest.mark.asyncio
    async def test_e03_strict_mode_discards_unmarked_cloned_audio(self, monkeypatch, tmp_path):
        """宁可没有声音,也不输出无标记的克隆音频。"""
        import core.speech_output as so
        import core.tts.watermark as wm

        out = tmp_path / "o.wav"
        out.write_bytes(b"RIFF")

        class _Clone:
            async def synthesize(self, text, output_path=None, voice=None):
                return str(out)

        _Clone.__name__ = "IndexTTSEngine"
        monkeypatch.setattr(so, "_get_engine", lambda: _Clone())
        monkeypatch.setattr(wm, "watermark_backend_available", lambda: (False, "audioseal 未安装"))
        monkeypatch.setenv("GALAXY_TTS_WATERMARK_STRICT", "1")

        with pytest.raises(RuntimeError, match="严格水印档"):
            await so.synthesize_to_file("你好")
        assert not os.path.exists(out), "严格档必须丢弃未加水印的克隆音频"

    @pytest.mark.asyncio
    async def test_e04_strict_mode_ignores_policy_skips(self, monkeypatch, tmp_path):
        """非克隆引擎本就不该加水印,严格档不能因此把它也毙掉。"""
        import core.speech_output as so

        out = tmp_path / "o.wav"
        out.write_bytes(b"RIFF")

        class _Edge:
            async def synthesize(self, text, output_path=None, voice=None):
                return str(out)

        _Edge.__name__ = "EdgeTTSEngine"
        monkeypatch.setattr(so, "_get_engine", lambda: _Edge())
        monkeypatch.setenv("GALAXY_TTS_WATERMARK_STRICT", "1")
        assert await so.synthesize_to_file("你好") == str(out)


# ---------------------------------------------------------------------------
# Group F — Flags
# ---------------------------------------------------------------------------


class TestGroupFFlags:
    def test_f01_flags_registered(self):
        from flags import get_flag

        mode_flag = get_flag("tts_watermark")
        assert mode_flag is not None
        assert mode_flag.env_var == "GALAXY_TTS_WATERMARK"
        assert mode_flag.default == MODE_CLONED_ONLY

        strict_flag = get_flag("tts_watermark_strict")
        assert strict_flag is not None
        assert strict_flag.env_var == "GALAXY_TTS_WATERMARK_STRICT"
