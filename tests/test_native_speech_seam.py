"""tests/test_native_speech_seam.py
=====================================
"说"按档自适配:B 档(说=原生)且注册了原生后端 → 走原生;A 档(说=TTS 桥)或
原生后端未注册 → 走 TTS。核心保证:未注册原生后端(当前默认)时行为与既有完全
一致(_maybe_speak_native 恒 False),零回归。

只测协商→分流的接缝(_maybe_speak_native),不触发真实 TTS/不触网。
"""

from __future__ import annotations

import core.speech_output as so


def _reset():
    so._native_speech_backend = None


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
