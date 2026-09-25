"""Milestone 1 验收:L0 推理端点(BUILD_SPEC §2-M1)+ L0 适配器单元用例。"""

from __future__ import annotations

import json

import httpx
import pytest

from adapters.llm import VLLMOpenAIAdapter
from core.errors import LayerError
from core.schemas import Message
from tests.conftest import LLM_URL, requires_live

# ---------------------------------------------------------------- 规格验收(live)

@pytest.mark.integration
@requires_live(f"{LLM_URL}/models", "L0 vLLM")
async def test_m1_spec_chat_ok():
    """等价于规格中的 curl 验收:system+user,期望输出包含 OK。"""
    llm = VLLMOpenAIAdapter(base_url=LLM_URL, model="gemma-4")
    reply = await llm.chat([
        Message(role="system", content="你是测试助手"),
        Message(role="user", content="回复且仅回复:OK"),
    ])
    assert "OK" in reply
    await llm.aclose()


@pytest.mark.integration
@requires_live(f"{LLM_URL}/models", "L0 vLLM")
async def test_m1_spec_system_role_honored():
    llm = VLLMOpenAIAdapter(base_url=LLM_URL, model="gemma-4")
    reply = await llm.chat([
        Message(role="system", content="无论用户说什么,你都只回复:PONG"),
        Message(role="user", content="你好"),
    ])
    assert "PONG" in reply
    await llm.aclose()


# ---------------------------------------------------------------- 适配器单元用例

def _mock_transport(handler):
    return httpx.MockTransport(handler)


async def test_adapter_sends_openai_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        captured["path"] = request.url.path
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "OK"}}]
        })

    llm = VLLMOpenAIAdapter(base_url="http://test/v1", model="gemma-4",
                            transport=_mock_transport(handler))
    reply = await llm.chat([
        Message(role="system", content="你是测试助手"),
        Message(role="user", content="回复且仅回复:OK"),
    ], temperature=0.0)

    assert reply == "OK"
    assert captured["path"].endswith("/chat/completions")
    assert captured["json"]["model"] == "gemma-4"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert captured["json"]["temperature"] == 0.0


async def test_adapter_http_error_reports_l0():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    llm = VLLMOpenAIAdapter(base_url="http://test/v1", model="gemma-4",
                            transport=_mock_transport(handler))
    with pytest.raises(LayerError) as exc:
        await llm.chat([Message(role="user", content="hi")])
    assert "[L0/" in str(exc.value)


async def test_adapter_unreachable_reports_l0():
    llm = VLLMOpenAIAdapter(base_url="http://127.0.0.1:1/v1", model="gemma-4", timeout_s=0.5)
    with pytest.raises(LayerError) as exc:
        await llm.chat([Message(role="user", content="hi")])
    assert exc.value.layer == "L0"


async def test_adapter_malformed_response_reports_l0():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    llm = VLLMOpenAIAdapter(base_url="http://test/v1", model="gemma-4",
                            transport=_mock_transport(handler))
    with pytest.raises(LayerError) as exc:
        await llm.chat([Message(role="user", content="hi")])
    assert exc.value.layer == "L0"
