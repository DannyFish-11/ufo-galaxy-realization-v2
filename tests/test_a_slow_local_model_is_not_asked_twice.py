"""本机模型慢不是故障:超时不重发、不换一条路再算一遍,读期限给够。

所有者 Windows 真机日志(无独显,gemma4:e2b 软件推理)::

    15:27:52 | WARNING | Timeout from ollama (attempt 1/3), retrying in 1.0s

重发等于把同一段提示再排进 Ollama 从头算一遍 —— 上一份还在算,负载翻倍,下一次更慢。
见 core/local_llm_policy.py。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from core.llm_adapters import OllamaAdapter, OpenAIAdapter
from core.llm_types import ProviderConfig
from core.local_llm_policy import READ_TIMEOUT_S

_REAL_SLEEP = asyncio.sleep


async def _no_wait(*_a, **_k):
    await _REAL_SLEEP(0)


def _cfg(name="ollama"):
    return ProviderConfig(name=name, api_key="", base_url="http://127.0.0.1:11434", models=["m"], default_model="m")


class _TimesOut:
    def __init__(self):
        self.calls = 0
        self.is_closed = False

    async def post(self, *a, **kw):
        self.calls += 1
        raise httpx.ReadTimeout("still thinking")


def _run(adapter):
    client = _TimesOut()
    adapter._client = client

    async def go():
        with pytest.raises(httpx.TimeoutException):
            await adapter._post_with_retry("http://127.0.0.1:11434/api/chat", {}, {})

    asyncio.run(go())
    return client.calls


def test_the_local_model_is_asked_once(monkeypatch):
    monkeypatch.setattr("core.llm_adapters.asyncio.sleep", _no_wait)
    assert _run(OllamaAdapter(_cfg())) == 1, "本机模型超时后又把同一段提示发了一遍"


def test_cloud_providers_still_retry_a_timeout(monkeypatch):
    monkeypatch.setattr("core.llm_adapters.asyncio.sleep", _no_wait)
    assert _run(OpenAIAdapter(_cfg("openai"))) == OpenAIAdapter.MAX_RETRIES + 1


def test_the_local_model_gets_a_long_read_and_a_short_connect():
    adapter = OllamaAdapter(_cfg())
    client = asyncio.run(adapter._get_client())
    try:
        assert client.timeout.read >= READ_TIMEOUT_S, "读期限还是 60 秒:一段长提示还没出字就到点了"
        assert client.timeout.connect <= 5.0, "连不上就是没起来 —— 不用等那么久"
    finally:
        asyncio.run(client.aclose())


def test_a_streaming_timeout_does_not_fall_back_to_computing_it_again():
    import inspect

    src = inspect.getsource(OllamaAdapter.chat)
    fallback = src[src.index("退回非流式") - 400 : src.index("退回非流式")]
    assert "isinstance(exc, httpx.TimeoutException)" in fallback and "raise" in fallback
