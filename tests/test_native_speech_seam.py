"""tests/test_native_speech_seam.py
=====================================
"说"按档自适配:B 档(说=原生)且注册了原生后端 → 走原生;A 档(说=TTS 桥)或
原生后端未注册 → 走 TTS。核心保证:未注册原生后端(当前默认)时行为与既有完全
一致(_maybe_speak_native 恒 False),零回归。

只测协商→分流的接缝(_maybe_speak_native),不触发真实 TTS/不触网。
"""

from __future__ import annotations

import os

import pytest

import core.speech_output as so


def _reset():
    so._native_speech_backend = None


@pytest.fixture(autouse=True)
def _hermetic_native_state():
    """铁律:本模块【绝不】把"原生说后端 + GALAXY_NATIVE_AUDIO 门控"泄漏到后续
    用例。任何一个测试注册了原生说 / 开了门控,teardown 一律复位——否则 TTS 覆盖层
    测试会误判"该走原生"而彻底跳过 TTS(CI 里 got [False] 的根因类）。"""
    saved = os.environ.get("GALAXY_NATIVE_AUDIO")
    try:
        yield
    finally:
        so._native_speech_backend = None
        if saved is None:
            os.environ.pop("GALAXY_NATIVE_AUDIO", None)
        else:
            os.environ["GALAXY_NATIVE_AUDIO"] = saved


def teardown_function():
    _reset()


# ── 零回归:默认无原生后端 → 一律走 TTS ─────────────────────────────────────


def test_no_backend_returns_false(monkeypatch):
    _reset()
    monkeypatch.setattr("core.modality_bridge.resolve_audio_out", lambda: "native")
    # 即便协商判定原生,只要没注册后端,也必须回落 TTS(返回 False)
    assert so._maybe_speak_native("你好", "chat") is False
    assert so.native_speech_backend_registered() is False


# ── B 档:注册后端 + 协商判定原生 → 走原生 ───────────────────────────────────


def test_backend_native_selected_speaks(monkeypatch):
    _reset()
    called = []

    async def _backend(text, source):
        called.append((text, source))
        return True

    so.register_native_speech_backend(_backend)
    assert so.native_speech_backend_registered() is True
    monkeypatch.setattr("core.modality_bridge.resolve_audio_out", lambda: "native")
    # 无运行中的事件循环 → 同步兜底路径会真正执行后端
    assert so._maybe_speak_native("你好", "voice") is True
    assert called == [("你好", "voice")]


# ── A 档:注册了后端,但协商判定桥 → 仍走 TTS ────────────────────────────────


def test_backend_registered_but_bridge_selected(monkeypatch):
    _reset()

    async def _backend(text, source):
        raise AssertionError("A 档不该调用原生后端")

    so.register_native_speech_backend(_backend)
    monkeypatch.setattr("core.modality_bridge.resolve_audio_out", lambda: "tts_bridge")
    assert so._maybe_speak_native("你好", "chat") is False


# ── 韧性:协商异常 → 按非原生(走 TTS),不因原生路径影响朗读 ──────────────────


def test_negotiator_error_falls_to_bridge(monkeypatch):
    _reset()

    async def _backend(text, source):
        return True

    so.register_native_speech_backend(_backend)

    def _boom():
        raise RuntimeError("negotiator down")

    monkeypatch.setattr("core.modality_bridge.resolve_audio_out", _boom)
    assert so._maybe_speak_native("你好", "chat") is False


def test_native_backend_failure_is_reported_not_silent(monkeypatch):
    # 原生后端返回 False → 如实告警(不静默丢句);接缝仍返回 True(已接管)
    _reset()

    async def _backend(text, source):
        return False

    so.register_native_speech_backend(_backend)
    monkeypatch.setattr("core.modality_bridge.resolve_audio_out", lambda: "native")
    warned = []
    monkeypatch.setattr(so, "_log_speak_failure", lambda kind, exc: warned.append(kind))
    assert so._maybe_speak_native("你好", "chat") is True
    assert warned and "原生" in warned[0]


# ── 关键:原生说失败 → 回落 TTS 兜底,绝不哑火 ───────────────────────────────


def test_native_failure_falls_back_to_tts(monkeypatch):
    # 原生后端返回 False → _run_native_speech 必须回落到 TTS 引擎链(不让用户听不到)
    import asyncio

    _reset()

    async def _backend(text, source):
        return False

    fell_back = []
    monkeypatch.setattr(so, "_log_speak_failure", lambda kind, exc: None)

    async def _fake_tts(spoken, source=""):
        fell_back.append((spoken, source))

    monkeypatch.setattr(so, "_speak_via_tts_engine", _fake_tts)
    asyncio.run(so._run_native_speech(_backend, "你好", "voice"))
    assert fell_back == [("你好", "voice")]  # 原生没出声 → TTS 兜底真的被调用


def test_native_exception_falls_back_to_tts(monkeypatch):
    # 原生后端抛异常(server 掉线)→ 同样回落 TTS 兜底
    import asyncio

    _reset()

    async def _backend(text, source):
        raise RuntimeError("server down")

    fell_back = []
    monkeypatch.setattr(so, "_log_speak_failure", lambda kind, exc: None)

    async def _fake_tts(spoken, source=""):
        fell_back.append(spoken)

    monkeypatch.setattr(so, "_speak_via_tts_engine", _fake_tts)
    asyncio.run(so._run_native_speech(_backend, "在吗", "chat"))
    assert fell_back == ["在吗"]


def test_native_success_does_not_fall_back(monkeypatch):
    # 原生说成功 → 绝不再走 TTS(否则重复出声两遍)
    import asyncio

    _reset()

    async def _backend(text, source):
        return True

    called = []

    async def _fake_tts(spoken, source=""):
        called.append(spoken)

    monkeypatch.setattr(so, "_speak_via_tts_engine", _fake_tts)
    asyncio.run(so._run_native_speech(_backend, "好的", "voice"))
    assert called == []  # 原生已出声,不重复
