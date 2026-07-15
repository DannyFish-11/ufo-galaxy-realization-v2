"""tests/test_whisper_asr_simplified.py
==========================================
ASR 中文修复:Whisper 对普通话常吐【繁体】且短语音"识别不清楚"。本测试验证 transcribe:
 - 传入简体 initial_prompt 偏置 + condition_on_previous_text=False(减少跨片段幻觉);
 - 装了 opencc 时把繁体输出【转成简体】(真机反馈"识别出来是繁体")。
不加载真实模型(注入假 model)。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.asr import whisper_asr as w


class _Seg:
    def __init__(self, t):
        self.text = t


class _Info:
    language = "zh"
    language_probability = 0.95


class _FakeModel:
    def __init__(self, text):
        self._text = text
        self.captured = {}

    def transcribe(self, audio, **kw):
        self.captured = kw
        return [_Seg(self._text)], _Info()


def _asr_with(model):
    asr = w.WhisperASR.__new__(w.WhisperASR)  # 跳过 __init__(不加载真实模型)
    asr.model = model
    return asr


def test_passes_simplified_bias_and_hallucination_guard():
    m = _FakeModel("你好")
    asr = _asr_with(m)
    asr.transcribe(np.zeros(1600, dtype=np.float32), language="zh")
    assert m.captured.get("condition_on_previous_text") is False
    assert "initial_prompt" in m.captured  # 中文偏置提示


def test_traditional_output_converted_to_simplified():
    pytest.importorskip("opencc")
    # 重置懒加载缓存,确保用真实 opencc
    w._opencc_converter = None
    w._opencc_tried = False
    m = _FakeModel("開始測試語音識別")  # 繁体
    asr = _asr_with(m)
    out = asr.transcribe(np.zeros(1600, dtype=np.float32), language="zh")
    assert out == "开始测试语音识别"  # 简体


def test_non_chinese_not_converted(monkeypatch):
    # 非中文语言不走繁简转换、也不加中文 initial_prompt
    m = _FakeModel("hello world")
    asr = _asr_with(m)
    out = asr.transcribe(np.zeros(1600, dtype=np.float32), language="en")
    assert out == "hello world"
    assert "initial_prompt" not in m.captured


def test_env_override_initial_prompt(monkeypatch):
    monkeypatch.setenv("GALAXY_ASR_INITIAL_PROMPT", "自定义提示")
    m = _FakeModel("测试")
    asr = _asr_with(m)
    asr.transcribe(np.zeros(1600, dtype=np.float32), language="zh")
    assert m.captured.get("initial_prompt") == "自定义提示"
