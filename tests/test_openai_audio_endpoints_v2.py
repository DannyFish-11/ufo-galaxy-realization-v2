"""tests/test_openai_audio_endpoints_v2.py
===========================================
Tests for the OpenAI-compatible audio endpoints (V2).

为什么补这两个端点
------------------
仓库已经有 OpenAI 兼容的 ``/v1/chat/completions``(Node_01_OneAPI、Node_79_LocalLLM),
却没有音频那两个——于是 6 个 TTS 引擎和 2 个 ASR 引擎只能被内部调用。补上之后,
任何用 OpenAI SDK 写的脚本改一行 base_url 就能指过来。

最要紧的一条约束(C 组钉住)
--------------------------
**不另起一套引擎选择。** 说走 ``core.speech_output``(引擎链与降级的权威),
听走 ``core.modality_bridge.transcribe_b64``——后者文档把自己称作"听的收口",
并且专门记录过绕开它的真实后果:语音循环直连 Whisper,导致 B 档"原生听"从未生效、
且毫无报错。在这里另开一条 ASR 调用就是重犯那个错。

Coverage matrix
---------------
Group A — Policy sentinels
  A01. REUSES_EXISTING_AUTHORITIES_POLICY 点名两个收口。
  A02. REPORTS_WHAT_IT_ACTUALLY_USED_POLICY 存在。

Group B — Route surface
  B01. 三个端点都在 OpenAPI 里。
  B02. 路径与 OpenAI 对齐(/v1/audio/speech、/v1/audio/transcriptions)。
  B03. create_router() 与其它 core/routes/* 形状一致。
  B04. 已挂进 core/api_routes.py。

Group C — 不绕开既有权威(本文件最重要的一组)
  C01. speech 走 speech_output,不自己选引擎。
  C02. transcriptions 走 transcribe_b64,不直接调 ASR。
  C03. 源码里不出现直接的 ASR 类调用。

Group D — /v1/audio/speech
  D01. 空 input → 400。
  D02. 超长 input → 400。
  D03. 非法 response_format → 400。
  D04. 合成不可用 → 503(不是 500)。
  D05. 成功时返回音频文件与如实的引擎/格式响应头。
  D06. voice 透传给 speech_output。
  D07. 请求格式与实际格式不符时如实上报,不假装满足。

Group E — /v1/audio/transcriptions
  E01. 空文件 → 400。
  E02. 链路不可用(None)→ 503。
  E03. 成功返回 {"text": ...}。
  E04. response_format=text 返回纯文本。
  E05. language 透传。
  E06. 听出空串与链路不可用是两种不同结果。

Group F — /v1/audio/capabilities
  F01. 如实上报当前引擎与降级原因。
  F02. 含各引擎的算力适配判定(接 V1)。
  F03. 任一探测失败都不让整个端点 500。
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.routes import openai_audio


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(openai_audio.create_router())
    return TestClient(app)


# ---------------------------------------------------------------------------
# Group A — Policies
# ---------------------------------------------------------------------------


class TestGroupAPolicies:
    def test_a01_reuses_existing_authorities(self):
        text = openai_audio.OPENAI_AUDIO_REUSES_EXISTING_AUTHORITIES_POLICY
        assert "POLICY_1" in text
        assert "core.speech_output" in text
        assert "transcribe_b64" in text
        assert "MUST NOT select engines" in text

    def test_a02_reports_actual_usage(self):
        text = openai_audio.OPENAI_AUDIO_REPORTS_WHAT_IT_ACTUALLY_USED_POLICY
        assert "POLICY_2" in text
        assert "actually used" in text


# ---------------------------------------------------------------------------
# Group B — Route surface
# ---------------------------------------------------------------------------


class TestGroupBSurface:
    def test_b01_endpoints_in_openapi(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert "/v1/audio/speech" in paths
        assert "/v1/audio/transcriptions" in paths
        assert "/v1/audio/capabilities" in paths

    def test_b02_paths_match_openai(self):
        registered = {r.path for r in openai_audio.router.routes}
        assert {"/v1/audio/speech", "/v1/audio/transcriptions"} <= registered

    def test_b03_factory_shape_matches_other_routes(self):
        sig = inspect.signature(openai_audio.create_router)
        assert "service_manager" in sig.parameters
        assert "config" in sig.parameters

    def test_b04_mounted_in_api_routes(self):
        src = inspect.getsource(__import__("core.api_routes", fromlist=["x"]))
        assert "openai_audio" in src, "route module exists but is never mounted"


# ---------------------------------------------------------------------------
# Group C — Must not bypass existing authorities
# ---------------------------------------------------------------------------


class TestGroupCNoBypass:
    def test_c01_speech_delegates_to_speech_output(self):
        src = inspect.getsource(openai_audio.create_speech)
        assert "synthesize_to_file" in src
        assert "_get_engine" not in src, "must not reach into speech_output internals"
        assert "EdgeTTSEngine" not in src and "KokoroTTSEngine" not in src

    def test_c02_transcription_uses_the_documented_entry_point(self):
        src = inspect.getsource(openai_audio.create_transcription)
        assert "transcribe_b64" in src

    def test_c03_no_direct_asr_invocation(self):
        """Bypassing 听的收口 is the documented defect this must not repeat."""
        src = inspect.getsource(openai_audio.create_transcription)
        assert "WhisperASR" not in src
        assert "SenseVoiceASR" not in src
        assert ".transcribe(" not in src


# ---------------------------------------------------------------------------
# Group D — speech
# ---------------------------------------------------------------------------


class TestGroupDSpeech:
    def test_d01_empty_input(self, client):
        assert client.post("/v1/audio/speech", json={"input": ""}).status_code == 400

    def test_d02_too_long(self, client):
        assert client.post("/v1/audio/speech", json={"input": "x" * 5000}).status_code == 400

    def test_d03_bad_format(self, client):
        r = client.post("/v1/audio/speech", json={"input": "你好", "response_format": "ogg"})
        assert r.status_code == 400

    def test_d04_unavailable_is_503_not_500(self, client, monkeypatch):
        """ "引擎链跑完仍出不了声"是能力不可用,不是请求错误。"""
        import core.speech_output as so

        async def _none(text, **kw):
            return None

        monkeypatch.setattr(so, "synthesize_to_file", _none)
        assert client.post("/v1/audio/speech", json={"input": "你好"}).status_code == 503

    def test_d05_success_returns_audio_with_honest_headers(self, client, monkeypatch, tmp_path):
        import core.speech_output as so

        wav = tmp_path / "out.wav"
        wav.write_bytes(b"RIFF0000WAVEfmt ")

        async def _ok(text, **kw):
            return str(wav)

        monkeypatch.setattr(so, "synthesize_to_file", _ok)
        monkeypatch.setattr(so, "current_engine_name", lambda: "FakeEngine")
        r = client.post("/v1/audio/speech", json={"input": "你好"})
        assert r.status_code == 200
        assert r.content.startswith(b"RIFF")
        assert r.headers["x-galaxy-tts-engine"] == "FakeEngine"
        assert r.headers["x-galaxy-audio-format"] == "wav"

    def test_d06_voice_is_passed_through(self, client, monkeypatch, tmp_path):
        import core.speech_output as so

        wav = tmp_path / "out.wav"
        wav.write_bytes(b"RIFF")
        seen = {}

        async def _capture(text, *, voice=None, output_path=None):
            seen["voice"] = voice
            return str(wav)

        monkeypatch.setattr(so, "synthesize_to_file", _capture)
        monkeypatch.setattr(so, "current_engine_name", lambda: "E")
        client.post("/v1/audio/speech", json={"input": "你好", "voice": "zh-CN-XiaoxiaoNeural"})
        assert seen["voice"] == "zh-CN-XiaoxiaoNeural"

    def test_d07_format_mismatch_is_reported_not_faked(self, client, monkeypatch, tmp_path):
        import core.speech_output as so

        wav = tmp_path / "out.wav"
        wav.write_bytes(b"RIFF")

        async def _ok(text, **kw):
            return str(wav)

        monkeypatch.setattr(so, "synthesize_to_file", _ok)
        monkeypatch.setattr(so, "current_engine_name", lambda: "E")
        r = client.post("/v1/audio/speech", json={"input": "你好", "response_format": "mp3"})
        assert r.status_code == 200
        # Actual format is reported as wav, and the request is echoed — no pretending.
        assert r.headers["x-galaxy-audio-format"] == "wav"
        assert r.headers["x-galaxy-requested-format"] == "mp3"


# ---------------------------------------------------------------------------
# Group E — transcriptions
# ---------------------------------------------------------------------------


class TestGroupETranscription:
    def _post(self, client, data=b"AUDIO", fmt="json", language="zh"):
        return client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.wav", data, "audio/wav")},
            data={"response_format": fmt, "language": language},
        )

    def test_e01_empty_file(self, client):
        assert self._post(client, data=b"").status_code == 400

    def test_e02_unavailable_chain_is_503(self, client, monkeypatch):
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "transcribe_b64", lambda *a, **k: None)
        assert self._post(client).status_code == 503

    def test_e03_success_returns_text(self, client, monkeypatch):
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "transcribe_b64", lambda *a, **k: "你好世界")
        r = self._post(client)
        assert r.status_code == 200
        assert r.json()["text"] == "你好世界"

    def test_e04_text_format(self, client, monkeypatch):
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "transcribe_b64", lambda *a, **k: "纯文本")
        r = self._post(client, fmt="text")
        assert r.status_code == 200
        assert "纯文本" in r.text

    def test_e05_language_passed_through(self, client, monkeypatch):
        import core.modality_bridge as mb

        seen = {}

        def _capture(b64, *, mime="", language="zh"):
            seen["language"] = language
            return "ok"

        monkeypatch.setattr(mb, "transcribe_b64", _capture)
        self._post(client, language="en")
        assert seen["language"] == "en"

    def test_e06_heard_nothing_differs_from_chain_unavailable(self, client, monkeypatch):
        """空串 = 听了但没内容;None = 链路不可用。混同会让排查失去方向。"""
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "transcribe_b64", lambda *a, **k: "")
        r = self._post(client)
        assert r.status_code == 200
        assert r.json()["text"] == ""

        monkeypatch.setattr(mb, "transcribe_b64", lambda *a, **k: None)
        assert self._post(client).status_code == 503


# ---------------------------------------------------------------------------
# Group F — capabilities
# ---------------------------------------------------------------------------


class TestGroupFCapabilities:
    def test_f01_reports_engine_and_degradation(self, client):
        body = client.get("/v1/audio/capabilities").json()
        assert "tts" in body and "asr" in body
        assert "active_engine" in body["tts"]

    def test_f02_includes_compute_fit(self, client):
        body = client.get("/v1/audio/capabilities").json()
        engines = body["tts"].get("engines") or {}
        assert "indextts" in engines
        assert "fits" in engines["indextts"]

    def test_f03_probe_failure_does_not_500(self, client, monkeypatch):
        import core.speech_output as so

        def boom():
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(so, "current_engine_name", boom)
        r = client.get("/v1/audio/capabilities")
        assert r.status_code == 200
        assert "error" in r.json()["tts"]
