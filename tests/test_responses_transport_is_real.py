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


class TestTheDeclarationCanActuallyBeReached:
    """声明支持 Responses 的那几家,**必须真的有一条路能走到那条传输上**。

    这一批是补一个真实的缺口:在它之前,``supports_responses`` 只在
    ``_pick_adapter`` 的怪癖分支里间接起作用,而那条分支只认 gpt-6-astra。
    deepseek 和 meta 标着支持,却**一处也到不了** —— 声明摆在那里和没有一样,
    正是本仓最怕的那种形状(看起来接上了,其实没有)。

    现在的路是 ``GALAXY_RESPONSES_PROVIDERS``:用户点名哪几家走 Responses。
    下面既钉"点了名要真的换过去",也钉"点了一家没声明的要被拒",后者同样重要 ——
    换过去只会在真发请求那一刻 404,那时看到的是"这家怎么不回话"。
    """

    @staticmethod
    def _router(provider: str):
        from core.multi_llm_router import MultiLLMRouter, OpenAIAdapter, ProviderConfig

        r = MultiLLMRouter.__new__(MultiLLMRouter)
        cfg = ProviderConfig(
            name=provider,
            api_key="sk-test",
            base_url="https://example.invalid/v1",
            models=["m-1"],
            default_model="m-1",
        )
        r.providers = {provider: cfg}
        r.adapters = {provider: OpenAIAdapter(cfg)}
        return r

    @pytest.mark.parametrize("provider", ["deepseek", "meta"])
    def test_naming_a_declared_vendor_really_switches_transport(self, monkeypatch, provider):
        from core.multi_llm_router import ResponsesAdapter

        monkeypatch.setenv("GALAXY_RESPONSES_PROVIDERS", provider)
        r = self._router(provider)
        picked = r._pick_adapter(provider, "m-1", tools=None)
        assert isinstance(picked, ResponsesAdapter), (
            f"点了名的 {provider} 还走在原来那条传输上 —— " "registry 里的 supports_responses 又变成了一个到不了的声明"
        )

    def test_naming_a_vendor_that_never_declared_it_is_refused_not_attempted(self, monkeypatch, caplog):
        """google 没登记讲 Responses。点它的名要**当场拒绝并说出来**。

        照办的后果是 404 发生在真发请求那一刻,而那时的现象是"这家不回话",
        没人会想到是传输选错了。
        """
        import logging

        from core.multi_llm_router import OpenAIAdapter

        monkeypatch.setenv("GALAXY_RESPONSES_PROVIDERS", "google")
        monkeypatch.setattr("core.multi_llm_router._RESPONSES_REFUSED", set())
        r = self._router("google")
        with caplog.at_level(logging.WARNING, logger="Galaxy.LLMRouter"):
            picked = r._pick_adapter("google", "m-1", tools=None)

        assert isinstance(picked, OpenAIAdapter), "把一家没声明支持的换去了 Responses —— 那是保证在上游 404"
        assert any("GALAXY_RESPONSES_PROVIDERS" in rec.message for rec in caplog.records), "拒绝了却没留痕"

    def test_not_naming_anybody_changes_nothing(self, monkeypatch):
        """反面保险:默认(空)时谁都不换,免得上面两条靠"一律换"通过。"""
        from core.multi_llm_router import OpenAIAdapter

        monkeypatch.delenv("GALAXY_RESPONSES_PROVIDERS", raising=False)
        r = self._router("deepseek")
        assert isinstance(r._pick_adapter("deepseek", "m-1", tools=None), OpenAIAdapter)

    def test_the_key_is_settable_from_the_panel(self):
        """这个键必须在设置面上配得到 —— 只认环境变量的开关等于没有开关。

        **这条判据换过一次形状**,换的原因值得记下来:

        第一版断言它出现在 ``settings_inventory.ts`` 里。后来这个键从 ``agent``
        类挪到了 ``llm`` 类(它说的是厂商的事),而 ``llm`` **不在** KEY_ORDER_HINT
        里 —— 那一类按字母序排,压根不需要顺序提示。于是这条当场红了,而它报的
        "面板上却排不出这一行"是**假的**:设置页的每一行都是拿后端
        ``/api/config/all`` 的返回现算的,进了 CONFIG_SCHEMA 就有那一行。

        第一版把"在顺序提示清单里"当成了"面板上配得到"的判据。那两件事不是
        同一件 —— 29 个 llm 键里有好几个都不在那份清单里,照样配得到。
        所以判据改成真正承重的那一条:它在 CONFIG_SCHEMA 里、归在厂商那一档。
        """
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        meta = CONFIG_SCHEMA.get("GALAXY_RESPONSES_PROVIDERS")
        assert meta is not None, "后端不认这个键 —— 面板上保存它会 400"
        assert meta["category"] == "llm", "它说的是厂商的事,该和密钥在同一档里"

    def test_the_helper_reads_the_registry_and_does_not_keep_a_second_list(self):
        """``speaks_responses`` 只是读 registry。它要是自己存一份就会各说各话。"""
        from core.provider_registry import PROVIDER_REGISTRY, speaks_responses

        for entry in PROVIDER_REGISTRY:
            assert speaks_responses(entry["name"]) is bool(entry.get("supports_responses"))
        assert speaks_responses("some-user-gateway") is False, "没登记过的名字不该被当成讲 Responses"

    def test_a_refused_opt_in_does_not_switch_off_the_quirk_path(self, monkeypatch):
        """点错一个名字,不该顺手关掉另一条本该生效的换路。

        两条判断各管各的:一条是用户点名,一条是"这个型号的工具只在 Responses 上
        工作"。第一版里前者拒绝后直接 return,于是把后者一起短路了 —— 那时的现象
        是工具**静静地**不工作,而人只会怀疑自己填错了那个名字。

        这里的组合(把 openai 的型号挂在别家名下)是人为的,为的是钉住两条判断
        彼此独立,而不是碰巧共用了一条路。
        """
        from core.multi_llm_router import ResponsesAdapter

        monkeypatch.setenv("GALAXY_RESPONSES_PROVIDERS", "mistral")
        monkeypatch.setattr("core.multi_llm_router._RESPONSES_REFUSED", set())
        r = self._router("mistral")
        picked = r._pick_adapter("mistral", "gpt-6-astra", tools=TOOLS)
        assert isinstance(picked, ResponsesAdapter), "被拒的点名把怪癖那条换路一起关掉了 —— 工具会静静地不工作"

    def test_the_refusal_points_a_user_endpoint_at_the_panel_not_at_the_registry(self, monkeypatch, caplog):
        """用户自己加的端点不归 registry 管 —— 指错地方比不指更糟。

        它的协议在面板「我的模型服务」那一条上;让人去翻 provider_registry.py
        只会浪费时间,而且找不到任何跟他有关的东西。
        """
        import logging

        from core.multi_llm_router import MultiLLMRouter, OpenAIAdapter, ProviderConfig

        monkeypatch.setenv("GALAXY_RESPONSES_PROVIDERS", "my-gw")
        monkeypatch.setattr("core.multi_llm_router._RESPONSES_REFUSED", set())
        r = MultiLLMRouter.__new__(MultiLLMRouter)
        cfg = ProviderConfig(
            name="my-gw",
            api_key="",
            base_url="http://127.0.0.1:1/v1",
            models=["m-1"],
            default_model="m-1",
            env_key="",
            source_type="user",
        )
        r.providers = {"my-gw": cfg}
        r.adapters = {"my-gw": OpenAIAdapter(cfg)}
        with caplog.at_level(logging.WARNING, logger="Galaxy.LLMRouter"):
            r._pick_adapter("my-gw", "m-1", tools=None)

        said = " ".join(rec.getMessage() for rec in caplog.records)
        assert "我的模型服务" in said, "让用户去翻 provider_registry.py —— 那里没有他这条端点"
        assert "provider_registry" not in said


class TestTheVerifyScriptCanSettleTheClaimOnTheRealMachine:
    """``supports_responses`` 是照厂商文档写的。真机脚本要能**把它证伪**。

    文档说有、实际没有,是本仓栽过的那类事;而这一条在 CI 上永远验不了(没有真
    key)。所以判据落在 ``scripts/verify_provider_apis.py`` 上:配好 key 跑一次,
    它会拿一个上游认账的型号往 ``/responses`` 发一次 1-token 试调。
    """

    @staticmethod
    def _probe():
        import importlib.util
        import pathlib

        path = pathlib.Path(__file__).resolve().parents[1] / "scripts/verify_provider_apis.py"
        spec = importlib.util.spec_from_file_location("verify_provider_apis", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod._probe_responses

    def test_a_live_responses_endpoint_passes_and_gets_a_responses_body(self):
        probe = self._probe()
        with _Upstream() as up:
            why = probe(up.base_url, "sk-test", "m-1", 10.0)
            body = up.seen[-1]

        assert why == "", f"真的 /responses 端点被判成不通:{why}"
        assert "input" in body and "max_output_tokens" in body, f"发过去的不是 Responses 的形状:{body}"

    def test_a_gateway_without_that_route_is_called_out_in_plain_words(self):
        """404 要说成"这个 base_url 上没有 /responses",不是一个光秃秃的状态码。

        这条门的价值全在措辞上:看到 "HTTP 404" 的人会去查型号、查密钥;看到
        "supports_responses 与实际不符"的人才会去改那个声明。
        """
        import socket
        import threading

        import uvicorn
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/v1/models")
        def models():  # noqa: ANN202
            return {"data": [{"id": "m-1"}]}

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = int(s.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            import time

            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.05)
            why = self._probe()(f"http://127.0.0.1:{port}/v1", "sk-test", "m-1", 10.0)
        finally:
            server.should_exit = True
            thread.join(timeout=5)

        assert "supports_responses" in why, f"没说到点子上:{why}"
