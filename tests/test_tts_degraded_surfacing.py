"""tests/test_tts_degraded_surfacing.py
========================================
语音"太僵/机器人音"的诚实告知回归防护。

edge-tts 云端不可达 + 离线神经引擎(kokoro)模型未就绪时,TTS 链会静默落到 SAPI
系统音(机器人音),而用户毫无线索(所有者反馈"语音太僵、不知为何")。修复让
speech_output 在落到 SAPI 时【如实置一个可查询的降级原因】(并打醒目日志),用上神经
引擎时清除。本测试锁死这个"落 SAPI→有降级态 / 用神经引擎→无降级态"的诚实语义。
"""

from __future__ import annotations

import core.speech_output as so


# 类名即判据(_note_engine_choice 用 type(eng).__name__,须与真实引擎类同名)。
class SapiTTSEngine:
    pass


class EdgeTTSEngine:
    pass


def _reset():
    so._tts_degraded_reason = None


def test_sapi_fallback_sets_degraded_reason():
    _reset()
    so._note_engine_choice(SapiTTSEngine())
    reason = so.get_tts_degraded_reason()
    assert reason, "落到 SAPI 系统音时必须置降级原因(不再无声降级)"
    assert "系统音" in reason and "SAPI" in reason


def test_neural_engine_clears_degraded_reason():
    _reset()
    so._tts_degraded_reason = "先前的降级态"
    so._note_engine_choice(EdgeTTSEngine())
    assert so.get_tts_degraded_reason() is None, "用上神经引擎(edge/kokoro)后应清除降级态"


def test_none_engine_is_noop():
    _reset()
    so._note_engine_choice(None)
    assert so.get_tts_degraded_reason() is None
