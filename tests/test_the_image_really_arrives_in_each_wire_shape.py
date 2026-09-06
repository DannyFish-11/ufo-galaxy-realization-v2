"""四条传输,同一张图,四种原生形状 —— 每一种都对着真服务器验。

## 这一整套要挡的是什么

带图的一轮对话,在发出去之前要经过两个判断:

1. **这一轮选中的型号收不收图**(``core.modality.input_modalities``)
2. **这条协议里图长什么样**(``core.modality.to_native``)

两个判断以前散在六处各说各的,后果不是代码重复,是**判断不一致**:选路那一步
按厂商说"这家能看图",发请求那一步却把图丢了、或者发成对面不认的形状 ——
而两边都不报错。上游收到一个它不认的部件时,绝大多数实现是**安静地忽略它**,
照常作答。于是没有任何人会发现模型其实没看见那张图。

所以这里全部对着**真的服务器**跑:起 uvicorn,把请求体留下来,断言那张图
以这条协议**自己的形状**躺在里面。打桩只能证明代码按我以为的方式执行,
证明不了对面收到的东西是对的。

## 四种形状(差别全在这儿,没有别的)

* openai     ``{"type":"image_url","image_url":{"url":"data:..."}}``
* anthropic  ``{"type":"image","source":{"type":"base64","media_type":..,"data":..}}``
* responses  ``{"type":"input_image","image_url":"data:..."}``  ← image_url 是**字符串**
* ollama     图不在 content 里,挂在 message 级 ``images: ["<纯 base64>"]``
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
from typing import Any, Dict, List

import pytest
import uvicorn
from fastapi import FastAPI, Request

#: 一张真的 1×1 PNG(base64)。用真图而不是 "AAAA":有些实现会校验魔数,
#: 拿假串测出来的"通过"证明不了真图能过。
PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
DATA_URL = f"data:image/png;base64,{PNG_1PX}"

MESSAGES = [
    {"role": "system", "content": "你是助手"},
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "这是什么"},
            {"type": "image_url", "image_url": {"url": DATA_URL}},
        ],
    },
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Upstream:
    """一台同时讲四种协议的服务器。收下请求体给测试检查。"""

    def __init__(self) -> None:
        self.port = _free_port()
        self.seen: List[Dict[str, Any]] = []
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(req: Request):  # noqa: ANN202
            self.seen.append(await req.json())
            return {
                "choices": [{"message": {"role": "assistant", "content": "好"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        @app.post("/v1/messages")
        async def messages(req: Request):  # noqa: ANN202
            self.seen.append(await req.json())
            return {"content": [{"type": "text", "text": "好"}], "usage": {"input_tokens": 1, "output_tokens": 1}}

        @app.post("/v1/responses")
        async def responses(req: Request):  # noqa: ANN202
            self.seen.append(await req.json())
            return {
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "好"}]}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

        @app.post("/api/chat")
        async def ollama(req: Request):  # noqa: ANN202
            self.seen.append(await req.json())
            return {"message": {"role": "assistant", "content": "好"}, "done": True}

        cfg = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def root_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

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


def _cfg(name: str, base_url: str, model: str):
    from core.multi_llm_router import ProviderConfig

    return ProviderConfig(name=name, api_key="sk-test", base_url=base_url, models=[model], default_model=model)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def caplog_at(level: int):
    """收一段日志。用 handler 而不是 pytest 的 caplog fixture:这些用例是类方法,
    带 fixture 参数会与上面几条的写法不一致,而这里只需要"有没有说话"。"""
    import logging

    records: List[logging.LogRecord] = []

    class _H(logging.Handler):
        def emit(self, record):  # noqa: D102
            records.append(record)

    lg = logging.getLogger("Galaxy.Modality")
    h = _H(level=level)
    lg.addHandler(h)
    old = lg.level
    lg.setLevel(level)
    try:
        yield records
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)


class TestTheImageArrivesInTheShapeThisProtocolUnderstands:
    def test_openai_chat_keeps_the_canonical_shape(self):
        from core.multi_llm_router import OpenAIAdapter

        with _Upstream() as up:
            adapter = OpenAIAdapter(_cfg("openai", up.base_url, "m"))
            _run(adapter.chat(MESSAGES, "m"))
            body = up.seen[-1]

        part = body["messages"][1]["content"][1]
        assert part["type"] == "image_url" and part["image_url"]["url"] == DATA_URL

    def test_anthropic_gets_base64_source_blocks_not_image_url(self):
        """Anthropic 不认 ``image_url`` 这种块。而且这条路以前**根本走不到这里**:

        抽 system 时是 ``system_text += m["content"]``,content 是数组就当场 TypeError。
        原生多模态一直只敢对 OpenAI 兼容面开,就是被这一句挡住的。
        """
        from core.multi_llm_router import AnthropicAdapter

        with _Upstream() as up:
            adapter = AnthropicAdapter(_cfg("anthropic", up.base_url, "m"))
            _run(adapter.chat(MESSAGES, "m"))
            body = up.seen[-1]

        assert body["system"].strip() == "你是助手", "system 没被正确抽出来(数组 content 那条路)"
        blocks = body["messages"][0]["content"]
        img = next(b for b in blocks if b["type"] == "image")
        assert img["source"] == {"type": "base64", "media_type": "image/png", "data": PNG_1PX}
        assert not any(b.get("type") == "image_url" for b in blocks), "还在发 OpenAI 的块类型"

    def test_responses_gets_input_image_with_a_string_url(self):
        """``input_image`` 的 image_url 是**字符串**,不是对象。发成对象不会报错,
        只会被当成没带图。"""
        from core.multi_llm_router import ResponsesAdapter

        with _Upstream() as up:
            adapter = ResponsesAdapter(_cfg("openai", up.base_url, "m"))
            _run(adapter.chat(MESSAGES, "m"))
            body = up.seen[-1]

        parts = body["input"][1]["content"]
        img = next(p for p in parts if p["type"] == "input_image")
        assert img["image_url"] == DATA_URL, f"image_url 不是字符串:{img}"
        assert any(p["type"] == "input_text" for p in parts), "文字部件名也要是 Responses 的"

    def test_ollama_gets_message_level_images_without_the_data_prefix(self):
        from core.multi_llm_router import OllamaAdapter

        with _Upstream() as up:
            adapter = OllamaAdapter(_cfg("ollama", up.root_url, "m"))
            _run(adapter.chat(MESSAGES, "m"))
            body = up.seen[-1]

        user = body["messages"][1]
        assert user["images"] == [PNG_1PX], "图没挂到 message 级 images,或者没去掉 data: 前缀"
        assert isinstance(user["content"], str) and "这是什么" in user["content"]


class TestThereIsOnlyOneHead:
    """四条翻译必须都在 ``core.modality`` 里,不许再有第二处各写各的。"""

    def test_every_protocol_the_head_claims_to_support_really_translates(self):
        from core.modality import SUPPORTED_WIRE_PROTOCOLS, to_native

        for proto in SUPPORTED_WIRE_PROTOCOLS:
            out = to_native(proto, MESSAGES)
            assert out and len(out) == len(MESSAGES), f"{proto} 把消息弄丢了"

    def test_an_unknown_protocol_says_so_instead_of_pretending(self, caplog):
        """悄悄按 OpenAI 发出去,是把一个没实现的协议伪装成实现了。"""
        import logging

        from core.modality import to_native

        with caplog.at_level(logging.WARNING, logger="Galaxy.Modality"):
            to_native("wechat", MESSAGES)
        assert any("wechat" in r.getMessage() for r in caplog.records), "不认识的协议被静默当成 OpenAI"

    def test_all_four_adapters_go_through_the_head(self):
        """四条传输都必须问 ``core.modality``,一条也不能自己判、自己翻。

        这条是白盒断言,钉的是"统一"这件事本身:上面那四条黑盒用例只能证明**现在**
        四种形状是对的,证明不了明天有人在某个适配器里又写了一份自己的翻译 ——
        而那一份会在某次改动后与这一份不一样,两边都不报错。
        """
        import inspect

        from core.multi_llm_router import AnthropicAdapter, OllamaAdapter, OpenAIAdapter, ResponsesAdapter

        for adapter in (OpenAIAdapter, ResponsesAdapter, AnthropicAdapter, OllamaAdapter):
            src = inspect.getsource(adapter)
            assert "core.modality" in src, f"{adapter.__name__} 没问统一的头"

        # Ollama 那份翻译是从适配器里搬走的 —— 搬走之后不该再留一份。
        src = inspect.getsource(OllamaAdapter._to_ollama_messages)
        assert "prepare" in src, "Ollama 又自己翻译了一遍"
        assert "image_url" not in src, "适配器里还留着一份翻译细节"

    def test_a_model_that_cannot_see_gets_text_instead_of_a_silently_ignored_image(self):
        """核实过收不了图的型号:压成文字**并留痕**,不是照发。

        照发的后果不是报错 —— 上游多半会忽略掉那个部件、照常作答。于是这一轮
        看起来完全正常,只是模型没看见那张图,而没有任何人会发现。
        """
        import logging

        from core.modality import prepare

        with caplog_at(logging.WARNING) as records:
            out = prepare("openai", MESSAGES, model="gpt-5.3-codex", provider="openai")

        assert isinstance(out[1]["content"], str), "图发给了一个核实过看不见它的型号"
        assert "未发送" in out[1]["content"], "压成文字时没在正文里说明少了什么"
        assert records, "压掉了图却一声不吭"

    def test_an_unverified_endpoint_is_not_treated_as_if_it_cannot_see(self):
        """未知 ≠ 不支持。按"不支持"处理会让每一个用户自建的多模态端点永远收不到图。"""
        from core.modality import prepare

        out = prepare("openai", MESSAGES, model="my-vlm", provider="my-gateway")
        assert isinstance(out[1]["content"], list), "没核实过就被当成看不见图了"


class TestKnowingIsNotTheSameAsGuessing:
    """模态能力三态:型号级核实过 / 从厂商继承 / 没核实过。**不许抹平**。"""

    def test_a_recorded_model_says_it_is_model_level(self):
        from core.modality import IMAGE, input_modalities

        s = input_modalities("gpt-5.3-codex", "openai")
        assert s.source == "model" and not s.can(IMAGE), "纯代码档被当成能看图了"

    def test_an_unrecorded_model_inherits_and_says_it_inherited(self):
        from core.modality import IMAGE, input_modalities

        s = input_modalities("gpt-5.6-terra", "openai")
        assert s.can(IMAGE) and s.source == "provider", "继承来的结论被当成型号级事实"

    def test_a_model_nobody_ever_recorded_is_unknown_not_text_only(self):
        """空与未知是两件事。这里返回 (text,) 但 source 必须是 unknown ——
        读成"只支持文本"会让一个其实能看图的端点永远收不到图。"""
        from core.modality import input_modalities

        s = input_modalities("some-model", "some-gateway-nobody-registered")
        assert s.source == "unknown" and not s.is_known

    def test_a_dated_snapshot_cannot_slip_past_the_table(self):
        """上游常在正式串后挂日期(``gpt-5.3-codex-2026-09-01``)。精确匹配会漏。"""
        from core.modality import IMAGE, input_modalities

        s = input_modalities("gpt-5.3-codex-2026-09-01", "openai")
        assert s.source == "model" and not s.can(IMAGE)

    def test_what_the_messages_actually_carry_beats_what_the_caller_claims(self):
        from core.modality import IMAGE, TEXT, modalities_in

        assert modalities_in(MESSAGES) == (TEXT, IMAGE)
        assert modalities_in([{"role": "user", "content": "纯文字"}]) == (TEXT,)
        assert IMAGE in modalities_in([{"role": "user", "content": "x", "images": [PNG_1PX]}])


class TestRoutingPicksAModelThatCanActuallySee:
    """选路的模态硬过滤必须按**这一轮会选中的那个型号**判,不按厂商判。

    以前读的是 provider 级的 ``multimodal`` 旗标。"这家有能看图的型号"不等于
    "这一轮选中的型号能看图":qwen 声明 multimodal,但它的 CODING 槽指的是
    ``qwen3.8-coder`` —— 一个纯代码档。于是"带着截图问一段代码怎么改"这种最需要
    看图的请求,恰好会选中看不见图的那一个。
    """

    @staticmethod
    def _router(*names: str):
        from core.multi_llm_router import MultiLLMRouter, OpenAIAdapter, ProviderConfig
        from core.provider_registry import PROVIDER_REGISTRY

        r = MultiLLMRouter.__new__(MultiLLMRouter)
        r.providers, r.adapters = {}, {}
        for n in names:
            entry = next(e for e in PROVIDER_REGISTRY if e["name"] == n)
            extra = entry.get("extra") or {}
            cfg = ProviderConfig(
                name=n,
                api_key="sk-test",
                base_url=entry["base_url"],
                models=list(entry["models"]),
                default_model=entry["default_model"],
                multimodal=bool(extra.get("multimodal")),
                supports_vision=bool(extra.get("supports_vision")),
            )
            r.providers[n] = cfg
            r.adapters[n] = OpenAIAdapter(cfg)
        return r

    def test_a_coder_only_model_is_filtered_out_of_an_image_request(self):
        from core.multi_llm_router import TaskType

        r = self._router("qwen")
        assert r._can_see("qwen", TaskType.CODING, 0.5) is False, "带图的编码轮仍然会选中纯代码档"
        assert r._can_see("qwen", TaskType.GENERAL, 0.5) is True, "把整家 qwen 都当成看不见图了"

    def test_the_image_request_lands_on_the_provider_whose_model_can_see(self):
        """两家都声明 multimodal,只有一家在这个任务上会选中能看图的型号。"""
        from core.multi_llm_router import TaskType

        r = self._router("qwen", "google")
        d = r.select_brain_for_task(TaskType.CODING, has_multimodal=True)
        assert d.provider == "google", f"带图的编码轮选中了 {d.provider}/{d.model} —— 它看不见图"

    def test_a_text_only_round_is_not_narrowed_by_the_modality_filter(self):
        """反面保险:不带图时这道过滤不该改变任何结果。"""
        from core.multi_llm_router import TaskType

        r = self._router("qwen", "google")
        assert r.select_brain_for_task(TaskType.CODING, has_multimodal=False).provider in ("qwen", "google")
