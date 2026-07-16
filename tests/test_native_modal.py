"""tests/test_native_modal.py
================================
B 档 MiniCPM-o 官方 server 原生听/说后端 + 档位联动。

验证:切 B 档就绪→注册原生听/说+开门控;依赖没装齐/server 不可达→如实回落桥;
切 A 档→注销+关门控;测试运行期不自动触发真实装包;transcribe_b64 在原生激活时
优先走 server、失败回落 Whisper。全部注入替身,不触网、不真装包。
"""

from __future__ import annotations

import asyncio

import core.native_modal as nm
import core.speech_output as so
from core.native_modal import MiniCPMNativeBackend


class _FakeBackend:
    """鸭子类型的后端替身:全部就绪。"""

    def __init__(self, *, deps_ok=True, reachable=True):
        self.base_url = "http://fake:32550"
        self._deps_ok = deps_ok
        self._reachable = reachable
        self.spoke = []
        self.heard = []

    def ensure_deps(self):
        return self._deps_ok

    def reachable(self, timeout=2.0):
        return self._reachable

    async def speak(self, text, source=""):
        self.spoke.append((text, source))
        return True

    def understand_audio(self, audio_b64, *, mime="audio/webm", language="zh"):
        self.heard.append(audio_b64)
        return "听懂了：" + audio_b64[:4]


def _reset(monkeypatch):
    nm.deactivate()
    monkeypatch.delenv("GALAXY_NATIVE_AUDIO", raising=False)
    so._native_speech_backend = None


def teardown_function():
    nm.deactivate()
    so._native_speech_backend = None


# ── 激活生命周期 ──────────────────────────────────────────────────────────────


def test_activate_ready_registers_and_opens_gate(monkeypatch):
    _reset(monkeypatch)
    be = _FakeBackend()
    nm.activate(be, background=False)
    assert nm.is_native_active() is True
    assert nm.get_active_backend() is be
    assert so.native_speech_backend_registered() is True  # 原生说已注册
    assert __import__("os").environ.get("GALAXY_NATIVE_AUDIO") == "1"  # 门控已开


def test_activate_deps_missing_falls_back(monkeypatch):
    _reset(monkeypatch)
    nm.activate(_FakeBackend(deps_ok=False), background=False)
    assert nm.is_native_active() is False  # 没装齐 → 不激活
    assert so.native_speech_backend_registered() is False


def test_activate_unreachable_falls_back(monkeypatch):
    _reset(monkeypatch)
    nm.activate(_FakeBackend(reachable=False), background=False)
    assert nm.is_native_active() is False  # server 不可达 → 不激活


def test_deactivate_unregisters_and_closes_gate(monkeypatch):
    _reset(monkeypatch)
    nm.activate(_FakeBackend(), background=False)
    assert nm.is_native_active() is True
    nm.deactivate()
    assert nm.is_native_active() is False
    assert so.native_speech_backend_registered() is False
    assert __import__("os").environ.get("GALAXY_NATIVE_AUDIO") is None  # 门控已关


# ── 档位联动 ──────────────────────────────────────────────────────────────────


def test_on_tier_changed_A_deactivates(monkeypatch):
    _reset(monkeypatch)
    nm.activate(_FakeBackend(), background=False)
    nm.on_tier_changed("A")
    assert nm.is_native_active() is False


def test_on_tier_changed_B_gated_off_during_tests(monkeypatch):
    # 测试运行期(PYTEST_CURRENT_TEST 存在)自动激活被禁 → 不触发真实装包
    _reset(monkeypatch)
    nm.on_tier_changed("B")  # 应被 _auto_activation_allowed 挡下
    assert nm.is_native_active() is False


def test_auto_activation_disabled_by_env(monkeypatch):
    monkeypatch.setenv("GALAXY_NATIVE_MODAL_AUTO", "0")
    assert nm._auto_activation_allowed() is False


def test_save_tier_B_does_not_activate_in_tests(monkeypatch):
    # 关键安全:既有 save_tier('B') 单测不能触发原生激活/装包
    _reset(monkeypatch)
    from core import model_catalog as mc

    mc.save_tier("B", main_brain="openbmb/minicpm-o4.5")
    assert nm.is_native_active() is False


# ── transcribe 收口:原生激活时优先 server,失败回落 ──────────────────────────


def test_transcribe_uses_native_when_active(monkeypatch):
    _reset(monkeypatch)
    nm.activate(_FakeBackend(), background=False)
    from core.modality_bridge import transcribe_b64

    out = transcribe_b64("QUJDData")
    assert out == "听懂了：QUJD"  # 走了原生 understand_audio,没碰 Whisper


def test_transcribe_native_empty_falls_back_to_whisper(monkeypatch):
    _reset(monkeypatch)

    class _EmptyNative(_FakeBackend):
        def understand_audio(self, audio_b64, *, mime="audio/webm", language="zh"):
            return None  # 原生听没听出来

    nm.activate(_EmptyNative(), background=False)
    import core.modality_bridge as mb

    monkeypatch.setattr(mb, "_get_asr", lambda: None)  # Whisper 也不可用
    assert mb.transcribe_b64("x") is None  # 回落 Whisper→不可用→None(不抛、不静默丢错)


# ── 后端单元:注入 http/install,不触网不真装 ─────────────────────────────────


def test_backend_reachable_via_injected_http():
    be = MiniCPMNativeBackend(http_get=lambda url, timeout=2.0: True)
    assert be.reachable() is True


def test_backend_speak_via_injected_http():
    posts = []
    be = MiniCPMNativeBackend(http_post=lambda url, json=None: posts.append((url, json)) or True)
    assert asyncio.run(be.speak("你好", "voice")) is True
    assert posts and "/api/speak" in posts[0][0]


def test_backend_understand_via_injected_http():
    be = MiniCPMNativeBackend(http_post=lambda url, json=None: "识别文本")
    assert be.understand_audio("b64") == "识别文本"


def test_backend_ensure_deps_installs_missing_then_reports_present(monkeypatch):
    # 依赖起初全缺 → 调用注入的装包函数 → 装完探测为齐 → ensure_deps True
    present = {"httpx": True, "numpy": True, "soundfile": False, "librosa": False}
    monkeypatch.setattr(nm, "_module_present", lambda p: present.get(p, False))
    installed = []

    def _install(pkgs):
        installed.append(list(pkgs))
        for p in pkgs:
            present[p] = True  # 模拟装成功
        return True

    be = MiniCPMNativeBackend(install_fn=_install)
    assert be.ensure_deps() is True
    assert installed and set(installed[0]) == {"soundfile", "librosa"}  # 只装缺的


def test_backend_ensure_deps_install_fail_returns_false(monkeypatch):
    monkeypatch.setattr(nm, "_module_present", lambda p: False)  # 全缺
    be = MiniCPMNativeBackend(install_fn=lambda pkgs: False)  # 装失败
    assert be.ensure_deps() is False  # 如实回落
