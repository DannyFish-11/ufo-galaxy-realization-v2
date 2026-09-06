"""第二条传输（Responses）必须真的把工具送到，而不是长得像。

## 背景

``gpt-6-astra`` 支持 chat/completions，但**工具调用只能走 Responses**。
在有这条适配器之前，本仓只能把工具丢掉并留痕 —— 答得出话，做不了事。

三家讲这个格式（各自一手文档核实）：OpenAI（原生）、Meta Model API、DeepSeek。

## 这些门钉什么

Responses 与 chat/completions 有三处**字段名不同**的差别，任何一处写错都不会
当场报错，只会安静地少做一件事：

* ``input`` 不是 ``messages``
* 工具是**平铺**的（``{"type":"function","name":...}``），不是嵌套在 ``function`` 里
* ``max_output_tokens`` 不是 ``max_tokens``

所以这里全部对着**一个真的 Responses 服务器**跑：起 uvicorn，收下请求体，
断言它收到的是 Responses 该有的形状。打桩只能证明代码按我以为的方式执行，
证明不了对面收到的东西是对的。
"""

from __future__ import annotations

import asyncio
import socket
import threading
from typing import Any, Dict, List

import pytest
import uvicorn
from fastapi import FastAPI, Request


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Upstream:
    """一个真的 Responses 端点。把收到的请求体留下来给测试检查。"""

    def __init__(self) -> None:
        self.port = _free_port()
        self.seen: List[Dict[str, Any]] = []
        app = FastAPI()

        @app.post("/v1/responses")
        async def responses(req: Request):  # noqa: ANN202
            body = await req.json()
            self.seen.append(body)
            return {
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "好的"}]},
                    {"type": "function_call", "call_id": "c1", "name": "do_thing", "arguments": '{"a":1}'},
                ],
                "usage": {"input_tokens": 7, "output_tokens": 11},
            }

        @app.post("/v1/chat/completions")
        async def chat(req: Request):  # noqa: ANN202
            body = await req.json()
            self.seen.append(body)
            return {
                "choices": [{"message": {"role": "assistant", "content": "好的"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 11},
            }

        cfg = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def __enter__(self) -> "_Upstream":
        import time

        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("测试上游没起来")

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def _cfg(base_url: str, model: str):
    from core.multi_llm_router import ProviderConfig

    return ProviderConfig(name="openai", api_key="sk-test", base_url=base_url, models=[model], default_model=model)


TOOLS = [
    {
        "type": "function",
        "function": {"name": "do_thing", "description": "做一件事", "parameters": {"type": "object"}},
    }
]


class TestTheWireFormatIsActuallyResponses:
    def test_the_three_renamed_fields_are_all_right(self):
        """三处字段名任何一处写错都不会报错，只会安静地少做一件事。"""
        from core.multi_llm_router import ResponsesAdapter

        with _Upstream() as up:
            adapter = ResponsesAdapter(_cfg(up.base_url, "gpt-6-astra"))
            asyncio.new_event_loop().run_until_complete(
                adapter.chat([{"role": "user", "content": "hi"}], "gpt-6-astra", tools=TOOLS, max_tokens=64)
            )
            body = up.seen[-1]

        assert "input" in body and "messages" not in body, "还在发 messages —— Responses 要的是 input"
        assert (
            "max_output_tokens" in body and "max_tokens" not in body
        ), "还在发 max_tokens —— Responses 会忽略它，输出长度会悄悄变成上游默认值"
        assert body["max_output_tokens"] == 64

    def test_tools_arrive_flattened_not_nested(self):
        """嵌套形状发过去，上游当成没有工具 —— 又一次「看起来接上了，其实没有」。"""
        from core.multi_llm_router import ResponsesAdapter

        with _Upstream() as up:
            adapter = ResponsesAdapter(_cfg(up.base_url, "gpt-6-astra"))
            asyncio.new_event_loop().run_until_complete(
                adapter.chat([{"role": "user", "content": "hi"}], "gpt-6-astra", tools=TOOLS)
            )
            tool = up.seen[-1]["tools"][0]

        assert tool["name"] == "do_thing", f"工具没有平铺：{tool}"
        assert "function" not in tool, "还是 chat 的嵌套形状"

    def test_the_quirks_apply_on_this_transport_too(self):
        """怪癖表对两条传输一视同仁 —— astra 在 Responses 上同样不收 temperature。"""
        from core.multi_llm_router import ResponsesAdapter

        with _Upstream() as up:
            adapter = ResponsesAdapter(_cfg(up.base_url, "gpt-6-astra"))
            asyncio.new_event_loop().run_until_complete(
                adapter.chat([{"role": "user", "content": "hi"}], "gpt-6-astra", tools=TOOLS)
            )
            body = up.seen[-1]

        assert "temperature" not in body, "Responses 这条路上没有执行怪癖表"

    def test_tool_calls_come_back_in_the_shape_the_rest_of_the_repo_knows(self):
        """上游给的是 output[].function_call，上层只认识 chat 那种形状。"""
        from core.multi_llm_router import ResponsesAdapter

        with _Upstream() as up:
            adapter = ResponsesAdapter(_cfg(up.base_url, "gpt-6-astra"))
            resp = asyncio.new_event_loop().run_until_complete(
                adapter.chat([{"role": "user", "content": "hi"}], "gpt-6-astra", tools=TOOLS)
            )

        assert resp.content == "好的"
        assert resp.tool_calls and resp.tool_calls[0]["function"]["name"] == "do_thing"
        assert (
            resp.input_tokens == 7 and resp.output_tokens == 11
        ), "Responses 用 input_tokens/output_tokens，不是 prompt_/completion_ —— 读错就一直是 0"


class TestTheRouterPicksTheRightTransport:
    """换路的判断只有一处（``_pick_adapter``），而且**只在带工具时**换。"""

    @staticmethod
    def _router():
        from core.multi_llm_router import MultiLLMRouter, OpenAIAdapter, ProviderConfig

        r = MultiLLMRouter.__new__(MultiLLMRouter)  # 不跑 __init__:这里只考选路
        cfg = ProviderConfig(
            name="openai",
            api_key="sk-test",
            base_url="https://example.invalid/v1",
            models=["gpt-6-astra"],
            default_model="gpt-6-astra",
        )
        r.providers = {"openai": cfg}
        r.adapters = {"openai": OpenAIAdapter(cfg)}
        return r

    def test_no_tools_stays_on_chat_completions(self):
        """不带工具就别换 —— 换过去会丢掉流式，为一个用不上的能力牺牲每一轮的体感。"""
        from core.multi_llm_router import OpenAIAdapter

        r = self._router()
        assert isinstance(r._pick_adapter("openai", "gpt-6-astra", tools=None), OpenAIAdapter)

    def test_tools_switch_to_responses(self):
        from core.multi_llm_router import ResponsesAdapter

        r = self._router()
        assert isinstance(r._pick_adapter("openai", "gpt-6-astra", tools=TOOLS), ResponsesAdapter)

    def test_an_ordinary_model_never_switches_even_with_tools(self):
        """反面保险:不能靠"带工具就一律换 Responses"来通过上一条。"""
        from core.multi_llm_router import OpenAIAdapter

        r = self._router()
        assert isinstance(r._pick_adapter("openai", "gpt-5.6-sol", tools=TOOLS), OpenAIAdapter)


class TestTheDeclarationsMatchTheDocs:
    def test_exactly_the_three_verified_vendors_declare_responses(self):
        """声明支持 Responses 的必须是核实过的那三家，不多不少。

        多一家 = 某天某轮换过去然后 404；少一家 = 白白用不上。
        """
        from core.provider_registry import PROVIDER_REGISTRY

        declared = {p["name"] for p in PROVIDER_REGISTRY if p.get("supports_responses")}
        assert declared == {"openai", "meta", "deepseek"}, (
            f"声明支持 Responses 的是 {declared}。加一家之前请先拿到那家的一手文档，" "并把出处写进 registry 的注释里。"
        )

    def test_meta_is_the_muse_spark_line_not_llama(self):
        """Meta 有两条线，这条 provider 是**闭源的 Muse Spark**。

        这个坑踩过两次：一次把 muse-spark 换成 Llama-4 并写「muse-spark 并非真实
        模型」；一次拿「Llama API 关停」把整条 meta 删掉。两次的根都是没分清两条线。
        """
        from core.provider_registry import PROVIDER_REGISTRY

        meta = next((p for p in PROVIDER_REGISTRY if p["name"] == "meta"), None)
        assert meta is not None, "meta 条目又没了 —— Muse Spark 线是活的，别拿 Llama 的关停删它"
        assert all(
            m.startswith("muse-spark") for m in meta["models"]
        ), f"meta 的型号变成了 {meta['models']} —— 这条 provider 是 Muse Spark 线，不是 Llama"
        assert "api.meta.ai" in meta["base_url"]
