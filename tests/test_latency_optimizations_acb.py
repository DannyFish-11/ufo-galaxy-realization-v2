"""tests/test_latency_optimizations_acb.py
============================================
延迟整体优化 A→C→B 的回归防护。

  A. Ollama 延迟默认值 —— serve 进程带 KEEP_ALIVE=-1/FLASH_ATTENTION/KV_CACHE
     环境默认(用户显式设置不覆盖);OllamaAdapter 每请求携带 keep_alive
     (数字转 int,时长字符串透传;安装器自启的 serve 也能生效)。
  B. Kokoro 离线引擎 —— 文件门限、CJK 判定、音色挑选、引擎链接入
     (kokoro 显式档、被拉黑跳过)。
  C. 高性能事件循环 —— GALAXY_FAST_LOOP=0 跳过、缺包安全退回默认、
     子进程探针在默认策略下可用。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# A. Ollama 延迟默认值
# ---------------------------------------------------------------------------

class TestOllamaServeEnvDefaults:
    @pytest.mark.asyncio
    async def test_serve_spawned_with_latency_env_defaults(self, monkeypatch):
        import core.local_brain_manager as lbm

        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs

            class _P:
                pid = 12345
            return _P()

        monkeypatch.setattr(lbm.shutil, "which", lambda name: "/usr/bin/ollama")
        monkeypatch.setattr(lbm.subprocess, "Popen", _fake_popen)
        monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)
        monkeypatch.delenv("OLLAMA_FLASH_ATTENTION", raising=False)
        monkeypatch.delenv("OLLAMA_KV_CACHE_TYPE", raising=False)

        mgr = lbm.LocalBrainManager.__new__(lbm.LocalBrainManager)
        ok = await mgr._start_ollama()
        assert ok is True
        env = captured["kwargs"]["env"]
        assert env["OLLAMA_KEEP_ALIVE"] == "-1"      # 模型常驻不卸载(冷启动根治)
        assert env["OLLAMA_FLASH_ATTENTION"] == "1"
        assert env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"

    @pytest.mark.asyncio
    async def test_user_env_overrides_are_respected(self, monkeypatch):
        import core.local_brain_manager as lbm

        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["kwargs"] = kwargs

            class _P:
                pid = 1
            return _P()

        monkeypatch.setattr(lbm.shutil, "which", lambda name: "/usr/bin/ollama")
        monkeypatch.setattr(lbm.subprocess, "Popen", _fake_popen)
        monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "10m")  # 用户显式设置

        mgr = lbm.LocalBrainManager.__new__(lbm.LocalBrainManager)
        await mgr._start_ollama()
        assert captured["kwargs"]["env"]["OLLAMA_KEEP_ALIVE"] == "10m"


class TestOllamaAdapterKeepAlive:
    @pytest.mark.asyncio
    async def test_request_body_carries_keep_alive_as_int(self, monkeypatch):
        from core.multi_llm_router import OllamaAdapter, ProviderConfig

        monkeypatch.delenv("GALAXY_OLLAMA_KEEP_ALIVE", raising=False)
        cfg = ProviderConfig(name="ollama", api_key="",
                             base_url="http://localhost:11434",
                             models=["m"], default_model="m")
        ad = OllamaAdapter(cfg)
        captured = {}

        async def _fake_post(url, headers, body):
            captured["body"] = body

            class _R:
                def json(self):
                    return {"message": {"content": "ok"},
                            "prompt_eval_count": 1, "eval_count": 1}
            return _R()

        ad._post_with_retry = _fake_post
        await ad.chat([{"role": "user", "content": "hi"}], "m")
        assert captured["body"]["keep_alive"] == -1          # JSON number
        assert isinstance(captured["body"]["keep_alive"], int)

    @pytest.mark.asyncio
    async def test_duration_string_passes_through(self, monkeypatch):
        from core.multi_llm_router import OllamaAdapter, ProviderConfig

        monkeypatch.setenv("GALAXY_OLLAMA_KEEP_ALIVE", "30m")
        cfg = ProviderConfig(name="ollama", api_key="",
                             base_url="http://localhost:11434",
                             models=["m"], default_model="m")
        ad = OllamaAdapter(cfg)
        captured = {}

        async def _fake_post(url, headers, body):
            captured["body"] = body

            class _R:
                def json(self):
                    return {"message": {"content": "ok"}}
            return _R()

        ad._post_with_retry = _fake_post
        await ad.chat([{"role": "user", "content": "hi"}], "m")
        assert captured["body"]["keep_alive"] == "30m"


# ---------------------------------------------------------------------------
# C. 高性能事件循环
# ---------------------------------------------------------------------------

class TestFastLoop:
    def test_disabled_by_env(self, monkeypatch):
        import importlib
        import core.fast_loop as fl
        importlib.reload(fl)
        monkeypatch.setenv("GALAXY_FAST_LOOP", "0")
        assert fl.install_fast_loop() == "default"
        assert fl.active_loop_name() == "default"

    def test_missing_package_falls_back_to_default(self, monkeypatch):
        import importlib
        import core.fast_loop as fl
        importlib.reload(fl)
        monkeypatch.setenv("GALAXY_FAST_LOOP", "1")
        # 令 uvloop/winloop 导入失败(不真正换策略,避免污染测试进程)
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def _no_loop_import(name, *a, **k):
            if name in ("uvloop", "winloop"):
                raise ImportError(f"no {name} in test")
            return real_import(name, *a, **k)

        with patch("builtins.__import__", side_effect=_no_loop_import):
            assert fl.install_fast_loop() == "default"

    def test_subprocess_probe_passes_on_default_policy(self):
        from core.fast_loop import _probe_subprocess_support
        assert _probe_subprocess_support() is True


# ---------------------------------------------------------------------------
# B. Kokoro 离线引擎
# ---------------------------------------------------------------------------

class TestKokoroEngine:
    def test_unavailable_without_model_files(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GALAXY_KOKORO_DIR", str(tmp_path / "nope"))
        monkeypatch.setenv("GALAXY_KOKORO_AUTOFETCH", "0")  # 测试不触网
        from core.tts import kokoro_engine as ke
        assert ke.model_files_present() is False
        eng = ke.KokoroTTSEngine()
        assert eng.available() is False  # 缺包或缺文件都不可用,且不抛

    def test_has_cjk(self):
        from core.tts.kokoro_engine import _has_cjk
        assert _has_cjk("今天天气不错") is True
        assert _has_cjk("hello world 3.14") is False

    def test_pick_voice_prefers_chinese_for_cjk_text(self):
        from core.tts.kokoro_engine import KokoroTTSEngine
        eng = KokoroTTSEngine()
        eng._voices = ["af_sarah", "am_adam", "zf_xiaoxiao", "zm_yunxi"]
        assert eng._pick_voice("你好呀") == "zf_xiaoxiao"
        assert eng._pick_voice("hello there") == "af_sarah"

    def test_pick_voice_env_override(self, monkeypatch):
        from core.tts.kokoro_engine import KokoroTTSEngine
        monkeypatch.setenv("GALAXY_KOKORO_VOICE", "zm_yunxi")
        eng = KokoroTTSEngine()
        eng._voices = ["af_sarah", "zm_yunxi"]
        assert eng._pick_voice("anything") == "zm_yunxi"

    def test_inherits_playback_from_edge_engine(self):
        from core.tts.edge_tts_engine import EdgeTTSEngine
        from core.tts.kokoro_engine import KokoroTTSEngine
        assert issubclass(KokoroTTSEngine, EdgeTTSEngine)
        assert "_play_audio" not in KokoroTTSEngine.__dict__
        assert "synthesize" in KokoroTTSEngine.__dict__


class TestKokoroChainIntegration:
    @pytest.fixture(autouse=True)
    def _reset(self):
        import core.speech_output as so
        so._engine = None
        so._engine_failed = False
        so._failed_engine_types.clear()
        yield
        so._engine = None
        so._engine_failed = False
        so._failed_engine_types.clear()

    def test_explicit_kokoro_choice_degrades_gracefully(self, monkeypatch, tmp_path):
        import core.speech_output as so
        monkeypatch.setenv("GALAXY_TTS_ENGINE", "kokoro")
        monkeypatch.setenv("GALAXY_KOKORO_DIR", str(tmp_path / "nope"))
        monkeypatch.setenv("GALAXY_KOKORO_AUTOFETCH", "0")
        eng = so._get_engine()
        # 容器无模型文件/非 Windows:kokoro→sapi 都不可用 → None(不崩);
        # 若在 Windows 真机上跑,则应落到 SapiTTSEngine。
        assert eng is None or type(eng).__name__ in ("KokoroTTSEngine", "SapiTTSEngine")

    def test_blacklisted_kokoro_skipped(self, monkeypatch):
        import core.speech_output as so
        so._failed_engine_types.add("KokoroTTSEngine")
        monkeypatch.setenv("GALAXY_TTS_ENGINE", "kokoro")
        eng = so._get_engine()
        assert eng is None or type(eng).__name__ != "KokoroTTSEngine"
