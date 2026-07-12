"""tests/test_tts_fallback_and_verify.py
==========================================
真机"连话都不说了"的根治回归防护 + API Key 保存回执验证端点。

覆盖:
  1. SapiTTSEngine — 平台门限(非 Windows available()=False、synthesize 拒绝)。
  2. speech_output 运行期降级 — demote_current_engine 拉黑当前引擎类型并重选;
     被拉黑的类型在 _get_engine 引擎链里被跳过。
  3. 增量朗读合成失败自愈 — begin_incremental_speech 的 _synth 在引擎运行期
     失败时换引擎重试同句(edge 云端不可达的真机场景)。
  4. IncrementalSpeaker 零句播出升 WARNING(此前逐句失败全按 debug 吞掉,
     真机表现"彻底静默零线索")。
  5. POST /api/v1/models/verify-provider — env_key 反查提供商、1-token 试调
     成功/失败/未启用三态。
"""
from __future__ import annotations

import asyncio
import logging
import platform
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 1. SapiTTSEngine 平台门限
# ---------------------------------------------------------------------------

class TestSapiEngine:
    def test_available_only_on_windows(self):
        from core.tts.sapi_engine import SapiTTSEngine
        eng = SapiTTSEngine()
        assert eng.available() == (platform.system() == "Windows")

    @pytest.mark.asyncio
    async def test_synthesize_rejects_off_windows(self):
        if platform.system() == "Windows":
            pytest.skip("仅在非 Windows 环境验证拒绝路径")
        from core.tts.sapi_engine import SapiTTSEngine
        with pytest.raises(RuntimeError):
            await SapiTTSEngine().synthesize("你好")

    def test_inherits_playback_from_edge_engine(self):
        """播放/打断复用 EdgeTTSEngine 的跨平台实现(继承而非重写)。"""
        from core.tts.edge_tts_engine import EdgeTTSEngine
        from core.tts.sapi_engine import SapiTTSEngine
        assert issubclass(SapiTTSEngine, EdgeTTSEngine)
        assert "_play_audio" not in SapiTTSEngine.__dict__
        assert "synthesize" in SapiTTSEngine.__dict__  # 合成必须覆写


# ---------------------------------------------------------------------------
# 2. 运行期降级换引擎
# ---------------------------------------------------------------------------

class TestEngineDemotion:
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

    def test_demote_blacklists_and_reselects(self, monkeypatch):
        import core.speech_output as so

        class _EngineA:
            pass

        class _EngineB:
            pass

        so._engine = _EngineA()
        # 重选时返回 B(模拟链上的下一个引擎)
        monkeypatch.setattr(so, "_get_engine", lambda: _EngineB())
        new = so.demote_current_engine("模拟云端不可达")
        assert isinstance(new, _EngineB)
        assert "_EngineA" in so._failed_engine_types

    def test_demote_with_no_engine_is_noop(self):
        import core.speech_output as so
        so._engine = None
        assert so.demote_current_engine("x") is None

    def test_blacklisted_edge_is_skipped_in_chain(self, monkeypatch):
        """EdgeTTSEngine 被拉黑后,engine 链不再选它(落到后备或 None)。"""
        import core.speech_output as so
        so._failed_engine_types.add("EdgeTTSEngine")
        monkeypatch.setenv("GALAXY_TTS_ENGINE", "edge")
        eng = so._get_engine()
        assert eng is None or type(eng).__name__ != "EdgeTTSEngine"


# ---------------------------------------------------------------------------
# 3. 增量朗读合成失败 → 换引擎重试同句
# ---------------------------------------------------------------------------

class TestIncrementalSynthFailover:
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
        so._active_speaker = None

    @pytest.mark.asyncio
    async def test_synth_failure_demotes_and_retries_same_sentence(self, monkeypatch):
        import core.speech_output as so

        synth_calls = []

        class _BrokenEdge:
            async def synthesize(self, text):
                synth_calls.append(("edge", text))
                raise ConnectionError("模拟微软 TTS 服务不可达")

            async def _play_audio(self, path):
                pass

            async def stop(self):
                pass

        played = []

        class _WorkingSapi:
            async def synthesize(self, text):
                synth_calls.append(("sapi", text))
                return f"wav:{text}"

            async def _play_audio(self, path):
                played.append(path)

            async def stop(self):
                pass

        monkeypatch.setattr(so, "speak_enabled", lambda: True)
        monkeypatch.setenv("GALAXY_TTS_STREAMING", "1")
        so._engine = _BrokenEdge()
        monkeypatch.setattr(so, "_get_engine", lambda: so._engine)
        # demote 后重选返回可用的 SAPI
        monkeypatch.setattr(
            so, "demote_current_engine", lambda reason="": _WorkingSapi(),
        )
        # os.remove 对假句柄(非真实文件)静默
        monkeypatch.setattr(so.os, "remove", lambda p: None)

        speaker = so.begin_incremental_speech(source="chat")
        assert speaker is not None
        speaker.feed("第一句话。")
        speaker.finish()
        await asyncio.wait_for(speaker._player_task, timeout=5)

        # edge 失败一次 → sapi 同句重试成功并播出
        assert ("edge", "第一句话。") in synth_calls
        assert ("sapi", "第一句话。") in synth_calls
        assert played == ["wav:第一句话。"]
        assert speaker.chunks_spoken == 1


# ---------------------------------------------------------------------------
# 4. 零句播出可见告警
# ---------------------------------------------------------------------------

class TestZeroSpokenWarning:
    @pytest.mark.asyncio
    async def test_all_sentences_failed_emits_warning(self, caplog):
        from core.streaming_speech import IncrementalSpeaker

        async def _synth(text):
            raise RuntimeError("合成必失败")

        async def _play(handle):
            pass

        sp = IncrementalSpeaker(_synth, _play, min_chars=1)
        assert sp.start()
        with caplog.at_level(logging.WARNING, logger="Galaxy.StreamingSpeech"):
            sp.feed("这句合成不出来。")
            sp.finish()
            await asyncio.wait_for(sp._player_task, timeout=5)
        assert any("一句未播出" in r.message for r in caplog.records), (
            "整段零句播出必须升 WARNING(不能再静默)"
        )

    @pytest.mark.asyncio
    async def test_interrupted_zero_spoken_does_not_warn(self, caplog):
        from core.streaming_speech import IncrementalSpeaker

        async def _synth(text):
            await asyncio.sleep(0.05)
            return "h"

        async def _play(handle):
            pass

        sp = IncrementalSpeaker(_synth, _play, min_chars=1)
        assert sp.start()
        sp.feed("第一句。")
        with caplog.at_level(logging.WARNING, logger="Galaxy.StreamingSpeech"):
            await sp.interrupt()
            await asyncio.wait_for(sp._player_task, timeout=5)
        assert not any("一句未播出" in r.message for r in caplog.records), (
            "被打断的零句播出属正常 barge-in,不该告警"
        )


# ---------------------------------------------------------------------------
# 5. verify-provider 端点
# ---------------------------------------------------------------------------

class _FakeVerifyAdapter:
    def __init__(self, ok=True):
        self._ok = ok

    async def chat(self, messages, model, **kwargs):
        from core.multi_llm_router import LLMResponse
        if not self._ok:
            import httpx
            resp = httpx.Response(401, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("unauthorized", request=resp.request, response=resp)
        return LLMResponse(content="p", provider="deepseek", model=model,
                           input_tokens=1, output_tokens=1, latency_ms=210.0)


class _FakeVerifyRouter:
    def __init__(self, ok=True, enabled=True):
        from core.multi_llm_router import ProviderConfig
        if enabled:
            self.adapters = {"deepseek": _FakeVerifyAdapter(ok)}
            self.providers = {"deepseek": ProviderConfig(
                name="deepseek", api_key="k", base_url="u",
                models=["deepseek-chat"], default_model="deepseek-chat",
            )}
        else:
            self.adapters, self.providers = {}, {}


def _mk_models_app():
    from fastapi import FastAPI
    from core.routes.models import router as models_router
    app = FastAPI()
    app.include_router(models_router)
    return app


class TestVerifyProviderEndpoint:
    def _post(self, payload, router):
        from fastapi.testclient import TestClient
        import core.multi_llm_router as mlr
        with patch.object(mlr, "get_llm_router", lambda: router):
            client = TestClient(_mk_models_app())
            return client.post("/api/v1/models/verify-provider", json=payload).json()

    def test_env_key_resolves_and_verifies_ok(self):
        out = self._post({"env_key": "DEEPSEEK_API_KEY"}, _FakeVerifyRouter(ok=True))
        assert out["ok"] is True
        assert out["provider"] == "deepseek"
        assert out["latency_ms"] == 210.0

    def test_bad_key_reports_sanitized_error(self):
        """错误回执脱敏:401 映射为可读文案,绝不透传原始异常串(CodeQL)。"""
        out = self._post({"env_key": "DEEPSEEK_API_KEY"}, _FakeVerifyRouter(ok=False))
        assert out["ok"] is False
        assert "401" in out["error"] and "密钥无效" in out["error"]
        assert "Traceback" not in out["error"] and "unauthorized" not in out["error"]

    def test_unconfigured_provider_reports_disabled(self):
        out = self._post({"provider": "deepseek"}, _FakeVerifyRouter(enabled=False))
        assert out["ok"] is False and "未启用" in out["error"]

    def test_unknown_env_key_reports_unrecognized(self):
        out = self._post({"env_key": "NO_SUCH_KEY"}, _FakeVerifyRouter())
        assert out["ok"] is False and "无法识别" in out["error"]
