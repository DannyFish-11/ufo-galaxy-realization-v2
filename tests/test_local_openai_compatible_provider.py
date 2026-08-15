#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_local_openai_compatible_provider.py

钉住：**Intel 侧那台本地推理服务是"配进来"的，不是"写个新后端"接进来的。**

为什么不写新后端
================
``core/local_model_backends.VLLMBackend`` 名字叫 vllm，实质是**通用 OpenAI 兼容
客户端** —— 只往 ``{base_url}/v1/chat/completions`` 发请求。路由层的
``OpenAIAdapter`` 同理。llama.cpp server 的 SYCL / Vulkan 后端、OpenVINO Model
Server 都讲同一套协议，所以起一个服务、把地址填进配置即可，
``BACKEND_REGISTRY`` 一个字不用加。

（原打算走 IPEX-LLM。查下来那条路是死的：``intel/ipex-llm`` 的 README 第一行是
``THIS PROJECT IS ARCHIVED``，并注明"已被识别为存在已知安全问题"；社区 fork 还在，
但验证模型列表停在 Qwen2.5 / MiniCPM-o-2.6，认不了新架构。）

不注册死端点
============
探不到就不注册 —— 与 ``hf_local`` 那处同源的教训：注册一个没人监听的端点，
偏好列表命中它时拿到的是连接失败，而不是继续往下一个 provider 退，
于是"本地服务没起"会表现成"模型探测失败"，根因看不出来。
"""

from __future__ import annotations

import pytest

from core.multi_llm_router import OPEN_SOURCE_PROVIDERS, MultiLLMRouter


class _Resp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _served(*ids):
    return _Resp(200, {"data": [{"id": i} for i in ids]})


@pytest.fixture
def router(monkeypatch):
    r = MultiLLMRouter.__new__(MultiLLMRouter)
    r.providers = {}
    r.adapters = {}
    for key in (
        "GALAXY_LOCAL_OPENAI_URL",
        "GALAXY_LOCAL_OPENAI_MODEL",
        "GALAXY_LOCAL_OPENAI_KEY",
        "GALAXY_LOCAL_OPENAI_SERVES",
    ):
        monkeypatch.delenv(key, raising=False)
    return r


class TestOptIn:
    def test_nothing_happens_without_the_url(self, router):
        """没配就整段空转 —— 加这条通路不改变任何既有安装的行为。"""
        router._register_local_openai()
        assert "local_openai" not in router.providers

    def test_dead_endpoint_is_not_registered(self, router, monkeypatch):
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", "http://127.0.0.1:9/v1")
        monkeypatch.setattr(MultiLLMRouter, "_probe_openai_compatible", staticmethod(lambda _b: []))
        router._register_local_openai()
        assert "local_openai" not in router.providers, "注册了一个探不到的端点 —— 命中它只会拿到连接失败"


class TestUrlNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("127.0.0.1:8000", "http://127.0.0.1:8000/v1"),
            ("http://127.0.0.1:8000", "http://127.0.0.1:8000/v1"),
            ("http://127.0.0.1:8000/", "http://127.0.0.1:8000/v1"),
            ("http://127.0.0.1:8000/v1", "http://127.0.0.1:8000/v1"),
            ("https://box.local:8443/v1", "https://box.local:8443/v1"),
        ],
    )
    def test_scheme_and_v1_are_filled_in(self, router, monkeypatch, raw, expected):
        """少写 scheme 或 /v1 是最常见的手填错误，不该因此静默连不上。"""
        seen = []
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", raw)
        monkeypatch.setattr(
            MultiLLMRouter,
            "_probe_openai_compatible",
            staticmethod(lambda b: seen.append(b) or ["m"]),
        )
        router._register_local_openai()
        assert seen == [expected]
        assert router.providers["local_openai"].base_url == expected


class TestModelSelection:
    def test_model_id_is_discovered_from_the_service(self, router, monkeypatch):
        """不用手抄模型 id —— 直接问服务它托管的是什么。"""
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", "127.0.0.1:8000")
        monkeypatch.setattr(
            MultiLLMRouter, "_probe_openai_compatible", staticmethod(lambda _b: ["qwen3.6-35b-a3b", "other"])
        )
        router._register_local_openai()
        cfg = router.providers["local_openai"]
        assert cfg.default_model == "qwen3.6-35b-a3b"
        assert cfg.models == ["qwen3.6-35b-a3b", "other"]

    def test_explicit_choice_wins_when_the_service_hosts_several(self, router, monkeypatch):
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", "127.0.0.1:8000")
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_MODEL", "other")
        monkeypatch.setattr(MultiLLMRouter, "_probe_openai_compatible", staticmethod(lambda _b: ["first", "other"]))
        router._register_local_openai()
        assert router.providers["local_openai"].default_model == "other"

    def test_bad_explicit_choice_warns_and_falls_back(self, router, monkeypatch, caplog):
        """填了一个服务并不托管的 id：回落自报值，但**必须说出来**。

        静默改用别的模型，就成了"配置写了却没生效"，而用户看不到任何提示。
        """
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", "127.0.0.1:8000")
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_MODEL", "typo-model")
        monkeypatch.setattr(MultiLLMRouter, "_probe_openai_compatible", staticmethod(lambda _b: ["real-model"]))
        with caplog.at_level("WARNING"):
            router._register_local_openai()
        assert router.providers["local_openai"].default_model == "real-model"
        assert any(
            "typo-model" in r.getMessage() for r in caplog.records
        ), "静默改用了别的模型 —— 配置写了却没生效，用户看不到任何提示"


class TestProbe:
    def test_probe_returns_hosted_ids(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, timeout=0: _served("a", "b"))
        assert MultiLLMRouter._probe_openai_compatible("http://x/v1") == ["a", "b"]

    def test_probe_swallows_errors_and_reports_empty(self, monkeypatch):
        import httpx

        def _boom(*_a, **_kw):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(httpx, "get", _boom)
        assert MultiLLMRouter._probe_openai_compatible("http://x/v1") == []

    def test_non_200_reports_empty(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, timeout=0: _Resp(404, {}))
        assert MultiLLMRouter._probe_openai_compatible("http://x/v1") == []

    def test_blank_ids_are_dropped(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda url, timeout=0: _Resp(200, {"data": [{"id": " "}, {"id": "ok"}]}))
        assert MultiLLMRouter._probe_openai_compatible("http://x/v1") == ["ok"]


class TestItCountsAsLocal:
    def test_registered_as_local_source(self, router, monkeypatch):
        """必须是 ``source_type="local"`` —— 槽位解析按这一栏找托管方，
        标成远端的话 Intel 侧那一位永远进不了本地槽位。"""
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", "127.0.0.1:8000")
        monkeypatch.setattr(MultiLLMRouter, "_probe_openai_compatible", staticmethod(lambda _b: ["m"]))
        router._register_local_openai()
        cfg = router.providers["local_openai"]
        assert cfg.source_type == "local"
        assert router.adapters["local_openai"] is not None
        assert router._provider_serving("m") == ("local_openai", "m")

    def test_counted_as_open_source(self):
        """自托管开源权重 —— 不该被开源优先策略排到专有提供商后面。"""
        assert "local_openai" in OPEN_SOURCE_PROVIDERS

    def test_discovery_actually_calls_it(self):
        """能力装了得有人用：``_discover_providers`` 必须真的调这一步。"""
        import inspect

        src = inspect.getsource(MultiLLMRouter._discover_providers)
        assert "_register_local_openai()" in src, "注册函数没有调用方 —— 配了地址也不会生效"


class TestNoAuthServersWork:
    """真实调用实测发现的：``api_key`` 为空时不能照发 ``Bearer ``。

    自托管的 llama.cpp server / OpenVINO Model Server 默认**不开鉴权**，
    对应的 provider 就该把 ``api_key`` 留空。而 ``OpenAIAdapter`` 原来无条件拼
    ``f"Bearer {api_key}"``，于是 httpx 在**发出请求之前**就抛：

    .. code-block:: text

        httpx.LocalProtocolError: Illegal header value b'Bearer '

    每一次请求都在这一步直接炸，连不上服务器，而报错长得像网络问题。
    """

    @staticmethod
    def _headers_sent(api_key: str) -> dict:
        """真的走一遍 ``OpenAIAdapter.chat``，把它发出的请求头抓下来。

        读源码断言"有没有那一行"是判而不别的 —— 换个写法就失效，而且它证明不了
        真实发出的头长什么样。这里拦在 ``_post_with_retry``，拿到的就是实际值。
        """
        import asyncio

        from core.multi_llm_router import OpenAIAdapter, ProviderConfig

        cfg = ProviderConfig(
            name="local_openai", api_key=api_key, base_url="http://x/v1", models=["m"], default_model="m"
        )
        ad = OpenAIAdapter(cfg)
        seen = {}

        class _R:
            status_code = 200

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}

        async def _fake(url, headers=None, body=None, **kw):
            seen.update(headers or {})
            return _R()

        ad._post_with_retry = _fake
        asyncio.run(ad.chat(messages=[{"role": "user", "content": "hi"}], model="m"))
        return seen

    def test_empty_key_omits_the_authorization_header(self):
        headers = self._headers_sent("")
        assert "Authorization" not in headers, f"空 key 仍然发了 {headers.get('Authorization')!r} —— httpx 会直接拒发"
        assert headers.get("Content-Type") == "application/json"

    def test_whitespace_only_key_counts_as_empty(self):
        assert "Authorization" not in self._headers_sent("   ")

    def test_a_real_key_is_still_sent(self):
        assert self._headers_sent("sk-abc").get("Authorization") == "Bearer sk-abc"

    def test_registration_leaves_the_key_empty_when_unset(self, router, monkeypatch):
        """不许再塞 "not-needed" 之类的占位符 —— 那是在绕开缺陷，不是在描述事实。"""
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", "127.0.0.1:8000")
        monkeypatch.setattr(MultiLLMRouter, "_probe_openai_compatible", staticmethod(lambda _b: ["m"]))
        router._register_local_openai()
        assert router.providers["local_openai"].api_key == ""

    def test_a_configured_key_is_still_sent(self, router, monkeypatch):
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_URL", "127.0.0.1:8000")
        monkeypatch.setenv("GALAXY_LOCAL_OPENAI_KEY", "sk-local-abc")
        monkeypatch.setattr(MultiLLMRouter, "_probe_openai_compatible", staticmethod(lambda _b: ["m"]))
        router._register_local_openai()
        assert router.providers["local_openai"].api_key == "sk-local-abc"
