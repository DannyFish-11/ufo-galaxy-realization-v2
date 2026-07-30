"""B 档原生【听】没有接进主语音循环 —— 说是原生的,听永远是 Whisper。

被修的问题
----------
``core/modality_bridge.py`` 里 ``transcribe_b64()`` 的 docstring 自称是"听的收口",实现
也确实正确:原生后端激活时先让全模态模型自己听懂,拿不到再回落 Whisper。

但 ``core/voice_loop.py`` **对 modality_bridge 和 native_modal 的引用数是 0** —— 它直接
``self.asr.transcribe(audio_np, ...)``,完全绕过收口。

于是 B 档切过去之后:

* **说** 走原生 —— ``native_modal.activate()`` 调
  ``speech_output.register_native_speech_backend()``,这条是通的;
* **听** 永远是 Whisper —— 主语音循环压根不问原生后端在不在。

一半原生一半桥,而且**没有任何报错**:用户切到 B 档、看到"原生已就绪",以为全模态模型在
听自己说话,其实模型从来没收到过音频。B 档最核心的卖点就是模型自己听,这一条没生效等于
这个档位废了一半。

判定这是漏接而非有意
--------------------
1. ``transcribe_b64`` 的 docstring 明写自己是"收口",且已实现原生优先 —— 意图明确;
2. ``modality_bridge.audio_in_mode()`` 会在门控开启时返回 ``"native"``,也就是系统对外
   **声称**听是原生的,而主循环的实际行为与之矛盾;
3. 说那一头接了,听这一头没接 —— 不对称本身就是遗漏的迹象。

形状不匹配才是它被漏掉的原因
----------------------------
``transcribe_b64`` 收 base64 容器化音频,而语音循环手里是裸 PCM(numpy float32)。所以
本次补的是收口的 PCM 入口 ``transcribe_pcm()``,而不是让调用方自己去 base64 —— 收口就该
把两种形状都收进来。

回落用的 ASR 由调用方传入(``fallback=``),这样接原生只是"在前面加一次尝试",voice_loop
既有的 ``model_size`` 行为一字不改。而且 ASR 的构造放在 fallback 里惰性执行:原生走通时
Whisper 权重根本不必加载。
"""

from __future__ import annotations

import base64
import io
import wave

import pytest

np = pytest.importorskip("numpy")

from core.modality_bridge import _pcm_to_wav_b64, transcribe_pcm  # noqa: E402


@pytest.fixture
def pcm():
    """1 秒 440Hz 正弦,float32 [-1,1] 单声道 —— 与仓库的 PCM 约定一致。"""
    t = np.linspace(0, 1, 16000, endpoint=False, dtype=np.float32)
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


@pytest.fixture(autouse=True)
def _no_real_native(monkeypatch):
    """默认把原生后端摘掉,免得测试受本机状态影响;要用的测试自己注入替身。"""
    import core.native_modal as nm

    monkeypatch.setattr(nm, "_active_backend", None)
    yield


class TestPcmToWav:
    def test_produces_a_valid_16bit_mono_wav(self, pcm):
        raw = base64.b64decode(_pcm_to_wav_b64(pcm, 16000))
        with wave.open(io.BytesIO(raw), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == len(pcm)

    def test_clipping_does_not_wrap_around(self):
        """越界样本必须**夹紧**,不能溢出回绕 —— 回绕会把削顶变成刺耳爆音。"""
        loud = np.array([2.0, -2.0, 0.0], dtype=np.float32)
        raw = base64.b64decode(_pcm_to_wav_b64(loud, 16000))
        with wave.open(io.BytesIO(raw), "rb") as wf:
            got = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        assert got[0] == 32767 and got[1] == -32767, f"发生了回绕: {got}"

    def test_empty_returns_none(self):
        assert _pcm_to_wav_b64(np.array([], dtype=np.float32), 16000) is None

    def test_int_input_is_accepted(self):
        assert _pcm_to_wav_b64(np.array([1, -1, 0], dtype=np.int16), 16000) is not None


class TestNativeIsPreferred:
    def test_native_backend_gets_the_audio(self, pcm, monkeypatch):
        """核心:原生后端在场时,音频必须真的送到它手里。"""
        import core.native_modal as nm

        seen = {}

        class _Backend:
            def understand_audio(self, audio_b64, *, mime="audio/webm", language="zh"):
                seen["b64"] = audio_b64
                seen["mime"] = mime
                seen["language"] = language
                return "原生听到的文字"

        monkeypatch.setattr(nm, "_active_backend", _Backend())
        called = []
        out = transcribe_pcm(pcm, language="zh", fallback=lambda *a: called.append(a) or "whisper 的文字")

        assert out == "原生听到的文字"
        assert not called, "原生成功了还去调 Whisper —— 白跑一次重活"
        assert seen["mime"] == "audio/wav"
        assert seen["language"] == "zh"
        raw = base64.b64decode(seen["b64"])
        assert raw[:4] == b"RIFF", "送过去的不是 WAV"

    def test_fallback_is_not_even_constructed_when_native_works(self, pcm, monkeypatch):
        """原生走通时不该加载 Whisper —— 那是几百 MB 权重和可观的启动时间。"""
        import core.native_modal as nm

        class _Backend:
            def understand_audio(self, audio_b64, **kw):
                return "原生文字"

        monkeypatch.setattr(nm, "_active_backend", _Backend())
        boom = lambda *a: (_ for _ in ()).throw(AssertionError("不该构造/调用 ASR"))  # noqa: E731
        assert transcribe_pcm(pcm, fallback=boom) == "原生文字"


class TestFallbackIsHonest:
    """原生失败绝不能丢句 —— 必须如实回落,不能静默返回空。"""

    def test_no_backend_falls_back(self, pcm):
        assert transcribe_pcm(pcm, fallback=lambda *a: "whisper 的文字") == "whisper 的文字"

    def test_native_returning_empty_falls_back(self, pcm, monkeypatch):
        import core.native_modal as nm

        class _Empty:
            def understand_audio(self, audio_b64, **kw):
                return ""

        monkeypatch.setattr(nm, "_active_backend", _Empty())
        assert transcribe_pcm(pcm, fallback=lambda *a: "whisper 的文字") == "whisper 的文字"

    def test_native_raising_falls_back(self, pcm, monkeypatch):
        import core.native_modal as nm

        class _Boom:
            def understand_audio(self, audio_b64, **kw):
                raise RuntimeError("server down")

        monkeypatch.setattr(nm, "_active_backend", _Boom())
        assert transcribe_pcm(pcm, fallback=lambda *a: "whisper 的文字") == "whisper 的文字"

    def test_fallback_raising_returns_none_not_crash(self, pcm):
        """听不清是预期情形,不该把整个语音循环炸掉。"""

        def _boom(*a):
            raise RuntimeError("asr down")

        assert transcribe_pcm(pcm, fallback=_boom) is None

    def test_none_audio_returns_none(self):
        assert transcribe_pcm(None) is None

    def test_whitespace_only_result_is_none(self, pcm):
        assert transcribe_pcm(pcm, fallback=lambda *a: "   ") is None


class TestVoiceLoopActuallyGoesThroughTheChokepoint:
    """白盒:语音循环必须真的走收口,而不是又绕回去直接调 ASR。

    这一组是本次改动的要害 —— 上面那些都在测 transcribe_pcm 本身,但这个 bug 的本体是
    **调用方没用它**。不钉住的话,下次有人"顺手优化"又直接调 self.asr 就白修了。
    """

    def _code(self):
        import ast
        import inspect

        import core.voice_loop as mod

        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    if isinstance(body[0].value.value, str):
                        body.pop(0)
        return ast.unparse(tree)

    def test_voice_loop_calls_the_chokepoint(self):
        assert "transcribe_pcm(" in self._code(), "语音循环没有走听的收口"

    def test_voice_loop_no_longer_calls_asr_directly_for_the_main_leg(self):
        """主链路不许再出现裸的 self.asr.transcribe(...) —— 除了收口的 fallback 里那次。"""
        code = self._code()
        assert code.count("self.asr.transcribe(") <= 1, "主链路仍在直接调 ASR,绕过了原生听"

    def test_the_asr_is_constructed_lazily_inside_the_fallback(self):
        """构造 ASR 必须在 fallback 内部,否则原生走通时仍然白加载 Whisper。"""
        import ast
        import inspect

        import core.voice_loop as mod

        src = inspect.getsource(mod)
        tree = ast.parse(src)
        fallbacks = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and "fallback" in n.name.lower()]
        assert fallbacks, "找不到 fallback 函数 —— 本测试的前提需重核"
        assert any("WhisperASR" in ast.unparse(f) for f in fallbacks), "ASR 不是在 fallback 里惰性构造的"

    def test_module_now_references_the_bridge(self):
        """回归发现时的那个事实:此前引用数是 0。"""
        import inspect

        import core.voice_loop as mod

        assert "modality_bridge" in inspect.getsource(mod)
