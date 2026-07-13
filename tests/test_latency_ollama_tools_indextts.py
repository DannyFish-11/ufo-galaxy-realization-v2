"""延迟优化批次 + Ollama 原生工具 + IndexTTS 质量档 测试
============================================================

覆盖:
  1. OllamaAdapter 原生 function calling:tools 进请求体、tool_calls 归一
     (dict 参数→JSON 字符串、合成 id)、模型不支持工具时去工具重试。
  2. num_ctx 显式设置(默认 8192,env 可调,0 不传)。
  3. context_trim:工具结果头尾截断、ReAct 老轮次修剪、工具定义 auto 瘦身。
  4. IndexTTS 质量档:默认不自动拉取权重、缺参考音频不可用、
     GALAXY_TTS_ENGINE=indextts 不可用时落回默认链。
"""
import json
from types import SimpleNamespace
import httpx
import pytest


def _mk_ollama_adapter():
    from core.multi_llm_router import OllamaAdapter, ProviderConfig
    cfg = ProviderConfig(
        name="ollama", api_key="", base_url="http://localhost:11434",
        models=["qwen3:4b"], default_model="qwen3:4b",
    )
    return OllamaAdapter(cfg)


def _ok_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200, json=payload, request=httpx.Request("POST", "http://t/api/chat"),
    )


TOOLS = [{"type": "function",
          "function": {"name": "node__06__list",
                       "parameters": {"type": "object", "properties": {}}}}]


# ---------------------------------------------------------------------------
# 1/2. Ollama 原生工具 + num_ctx
# ---------------------------------------------------------------------------

class TestOllamaNativeTools:
    @pytest.mark.asyncio
    async def test_tools_and_num_ctx_enter_body(self, monkeypatch):
        monkeypatch.setenv("GALAXY_OLLAMA_NUM_CTX", "8192")
        ad = _mk_ollama_adapter()
        seen = {}

        async def _fake_post(url, headers, body):
            seen.update(body)
            return _ok_response({"message": {"content": "好"},
                                 "prompt_eval_count": 1, "eval_count": 1})

        ad._post_with_retry = _fake_post
        resp = await ad.chat([{"role": "user", "content": "q"}],
                             model="qwen3:4b", tools=TOOLS)
        assert seen.get("tools") == TOOLS, "tools 必须随请求体发给 Ollama"
        assert seen["options"]["num_ctx"] == 8192
        assert resp.content == "好"

    @pytest.mark.asyncio
    async def test_num_ctx_zero_means_model_default(self, monkeypatch):
        monkeypatch.setenv("GALAXY_OLLAMA_NUM_CTX", "0")
        ad = _mk_ollama_adapter()
        seen = {}

        async def _fake_post(url, headers, body):
            seen.update(body)
            return _ok_response({"message": {"content": "ok"}})

        ad._post_with_retry = _fake_post
        await ad.chat([{"role": "user", "content": "q"}], model="m")
        assert "num_ctx" not in seen["options"]

    @pytest.mark.asyncio
    async def test_tool_calls_normalized_to_openai_shape(self):
        """Ollama 的 arguments 是 dict 且无 id → 归一成 JSON 字符串 + 合成 id,
        下游 ReAct 的 json.loads(arguments) 两家通吃。"""
        ad = _mk_ollama_adapter()

        async def _fake_post(url, headers, body):
            return _ok_response({"message": {
                "content": "",
                "tool_calls": [{"function": {"name": "node__06__list",
                                             "arguments": {"path": "/a"}}}],
            }})

        ad._post_with_retry = _fake_post
        resp = await ad.chat([{"role": "user", "content": "q"}],
                             model="m", tools=TOOLS)
        assert resp.tool_calls and len(resp.tool_calls) == 1
        tc = resp.tool_calls[0]
        assert tc["id"]
        assert tc["type"] == "function"
        assert json.loads(tc["function"]["arguments"]) == {"path": "/a"}

    @pytest.mark.asyncio
    async def test_tools_unsupported_model_retries_without_tools(self):
        """gemma 系无工具模板 → 400 'does not support tools':去工具重试,
        宁可本轮无工具也不整个请求哑掉。"""
        ad = _mk_ollama_adapter()
        bodies = []

        async def _fake_post(url, headers, body):
            bodies.append(body)
            if "tools" in body:
                req = httpx.Request("POST", url)
                resp = httpx.Response(
                    400, text='{"error":"gemma3 does not support tools"}',
                    request=req)
                raise httpx.HTTPStatusError("400", request=req, response=resp)
            return _ok_response({"message": {"content": "无工具回答"}})

        ad._post_with_retry = _fake_post
        resp = await ad.chat([{"role": "user", "content": "q"}],
                             model="gemma3:4b", tools=TOOLS)
        assert len(bodies) == 2
        assert "tools" in bodies[0] and "tools" not in bodies[1]
        assert resp.content == "无工具回答"

    @pytest.mark.asyncio
    async def test_unrelated_400_still_raises(self):
        ad = _mk_ollama_adapter()

        async def _fake_post(url, headers, body):
            req = httpx.Request("POST", url)
            resp = httpx.Response(400, text='{"error":"invalid model"}', request=req)
            raise httpx.HTTPStatusError("400", request=req, response=resp)

        ad._post_with_retry = _fake_post
        with pytest.raises(httpx.HTTPStatusError):
            await ad.chat([{"role": "user", "content": "q"}], model="m", tools=TOOLS)

    def test_normalize_tool_calls_edge_shapes(self):
        from core.multi_llm_router import OllamaAdapter
        norm = OllamaAdapter._normalize_tool_calls
        assert norm(None) is None
        assert norm([]) is None
        out = norm([{"function": {"name": "t", "arguments": "已是字符串"}}])
        assert out[0]["function"]["arguments"] == "已是字符串"
        out = norm([{"function": {"name": "t"}}])  # 无 arguments
        assert out[0]["function"]["arguments"] == "{}"


# ---------------------------------------------------------------------------
# 3. context_trim
# ---------------------------------------------------------------------------

class TestContextTrim:
    def test_clip_short_passthrough(self):
        from core.context_trim import clip_tool_result
        assert clip_tool_result("短结果", max_chars=100) == "短结果"

    def test_clip_keeps_head_and_tail(self):
        from core.context_trim import clip_tool_result
        text = "开头" + "x" * 5000 + "结尾成功exit0"
        out = clip_tool_result(text, max_chars=1000)
        assert len(out) < len(text)
        assert out.startswith("开头")
        assert out.endswith("结尾成功exit0")
        assert "已修剪" in out and str(len(text)) in out

    def _mk_round(self, i, tool_len):
        return [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": f"c{i}", "type": "function",
                             "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": "R" * tool_len},
        ]

    def test_prune_keeps_recent_rounds_and_small_results(self):
        from core.context_trim import prune_stale_tool_results
        messages = [{"role": "system", "content": "s"},
                    {"role": "user", "content": "u"}]
        for i in range(5):  # 5 轮:前 2 轮该剪(大),第 3 轮小不剪,后 2 轮保留
            messages += self._mk_round(i, 2000 if i < 2 else (100 if i == 2 else 2000))

        n = prune_stale_tool_results(messages, keep_rounds=2, min_chars=500)
        assert n == 2  # 只有前两轮的大结果被剪(第 3 轮太小,最后 2 轮受保护)
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        assert "已修剪" in tool_msgs[0]["content"]
        assert "已修剪" in tool_msgs[1]["content"]
        assert tool_msgs[2]["content"] == "R" * 100        # 小结果原样
        assert tool_msgs[3]["content"] == "R" * 2000       # 最近轮完整
        assert tool_msgs[4]["content"] == "R" * 2000

    def test_prune_disabled_or_few_rounds_noop(self):
        from core.context_trim import prune_stale_tool_results
        messages = self._mk_round(0, 9000)
        assert prune_stale_tool_results(messages, keep_rounds=0) == 0
        assert prune_stale_tool_results(messages, keep_rounds=3) == 0
        assert messages[1]["content"] == "R" * 9000

    def _mk_tools(self, n):
        return [{"type": "function",
                 "function": {"name": f"node__{i:02d}__act{i}",
                              "description": f"desc {i}"}} for i in range(n)]

    def test_slim_under_threshold_returns_unchanged(self, monkeypatch):
        from core.context_trim import slim_tools
        monkeypatch.setenv("GALAXY_TOOLS_SLIM", "auto")
        tools = self._mk_tools(10)
        assert slim_tools(tools, "随便问问", max_tools=24) is tools

    def test_slim_over_threshold_prefers_relevant_and_core(self, monkeypatch):
        from core.context_trim import slim_tools
        monkeypatch.setenv("GALAXY_TOOLS_SLIM", "auto")
        tools = self._mk_tools(30)
        tools.append({"type": "function", "function": {
            "name": "node__fs__截图屏幕", "description": "截取当前屏幕画面"}})
        tools.append({"type": "function", "function": {
            "name": "memory__recall", "description": "记忆召回"}})
        out = slim_tools(tools, "帮我截图屏幕看看", max_tools=5)
        names = [t["function"]["name"] for t in out]
        assert len(out) == 5
        assert "node__fs__截图屏幕" in names   # 相关工具入选
        assert "memory__recall" in names       # 核心工具永不裁

    def test_slim_off_switch(self, monkeypatch):
        from core.context_trim import slim_tools
        monkeypatch.setenv("GALAXY_TOOLS_SLIM", "off")
        tools = self._mk_tools(50)
        assert slim_tools(tools, "q", max_tools=5) is tools


# ---------------------------------------------------------------------------
# 4. IndexTTS 质量档
# ---------------------------------------------------------------------------

class TestIndexTTSEngine:
    def test_autofetch_default_off(self, monkeypatch):
        """数 GB 权重绝不静默下载:默认关,显式 =1 才拉。"""
        import core.tts.indextts_engine as ie
        monkeypatch.delenv("GALAXY_INDEXTTS_AUTOFETCH", raising=False)
        monkeypatch.setattr(ie, "_fetch_started", False)
        started = []
        monkeypatch.setattr(ie.threading, "Thread",
                            lambda **kw: started.append(kw) or SimpleNamespace(start=lambda: None))
        ie.kick_background_fetch()
        assert not started

    def test_unavailable_without_ref_audio(self, monkeypatch, tmp_path):
        """包在、模型在、但没配参考音频 → 不可用(零样本克隆必须有音色来源)。"""
        import sys
        import core.tts.indextts_engine as ie
        monkeypatch.setitem(sys.modules, "indextts", SimpleNamespace())
        monkeypatch.setenv("GALAXY_INDEXTTS_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text("ok")
        monkeypatch.delenv("GALAXY_INDEXTTS_REF_AUDIO", raising=False)
        eng = ie.IndexTTSEngine()
        assert eng.available() is False

    def test_available_when_all_present(self, monkeypatch, tmp_path):
        import sys
        import core.tts.indextts_engine as ie
        monkeypatch.setitem(sys.modules, "indextts", SimpleNamespace())
        monkeypatch.setenv("GALAXY_INDEXTTS_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text("ok")
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"RIFF")
        monkeypatch.setenv("GALAXY_INDEXTTS_REF_AUDIO", str(ref))
        eng = ie.IndexTTSEngine()
        assert eng.available() is True

    @pytest.mark.asyncio
    async def test_synthesize_passes_clone_and_emotion(self, monkeypatch, tmp_path):
        import core.tts.indextts_engine as ie
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"RIFF")
        monkeypatch.setenv("GALAXY_INDEXTTS_REF_AUDIO", str(ref))
        monkeypatch.setenv("GALAXY_INDEXTTS_EMO_TEXT", "平静而温柔")
        monkeypatch.setenv("GALAXY_INDEXTTS_EMO_ALPHA", "0.7")

        calls = {}

        class _FakeTTS:
            def infer(self, **kw):
                calls.update(kw)

        eng = ie.IndexTTSEngine()
        eng._tts = _FakeTTS()
        out = await eng.synthesize("你好世界")
        assert calls["spk_audio_prompt"] == str(ref)
        assert calls["text"] == "你好世界"
        assert calls["emo_text"] == "平静而温柔"
        assert calls["use_emo_text"] is True
        assert calls["emo_alpha"] == 0.7
        assert out  # 产出路径

    @pytest.mark.asyncio
    async def test_signature_drift_falls_back_to_minimal(self, monkeypatch, tmp_path):
        """v1 无情绪参数:TypeError → 最小参数集重试,宁丢情绪也要出声。"""
        import core.tts.indextts_engine as ie
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"RIFF")
        monkeypatch.setenv("GALAXY_INDEXTTS_REF_AUDIO", str(ref))
        monkeypatch.setenv("GALAXY_INDEXTTS_EMO_TEXT", "开心")

        calls = []

        class _V1TTS:
            def infer(self, spk_audio_prompt=None, text=None, output_path=None, **extra):
                if extra:
                    raise TypeError("unexpected keyword")
                calls.append((spk_audio_prompt, text, output_path))

        eng = ie.IndexTTSEngine()
        eng._tts = _V1TTS()
        await eng.synthesize("测试")
        assert calls and calls[0][1] == "测试"

    def test_engine_choice_falls_back_when_unavailable(self, monkeypatch):
        """GALAXY_TTS_ENGINE=indextts 但引擎不可用 → 落回默认链,绝不整段哑。"""
        import core.speech_output as so
        monkeypatch.setenv("GALAXY_TTS_ENGINE", "indextts")
        monkeypatch.setattr(so, "_engine", None)
        monkeypatch.setattr(so, "_engine_failed", False)
        monkeypatch.setattr(so, "_failed_engine_types", set())

        sentinel = object()
        import core.tts.indextts_engine as ie
        monkeypatch.setattr(ie.IndexTTSEngine, "available", lambda self: False)
        # 默认链第一站 edge 直接给假引擎,证明链条接上了
        import core.tts as tts_pkg
        monkeypatch.setattr(tts_pkg, "EdgeTTSEngine",
                            lambda voice=None: sentinel, raising=False)
        import sys
        monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace())

        eng = so._get_engine()
        assert eng is sentinel
