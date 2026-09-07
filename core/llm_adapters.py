"""core/llm_adapters.py — 四条传输的适配器:把一次请求真正发出去。

从 ``core/multi_llm_router.py`` 拆出来的(约 980 行)。那个文件同时装着**选路**
(选哪一家、哪个型号、哪条传输)和**发请求**(这条协议的头、体、错误、重试),
两件事各自都在长,合在一起的唯一后果是没人敢动它。

四条传输,一条一个类:

* :class:`OpenAIAdapter`     ``/chat/completions`` —— 绝大多数家讲的那一套
* :class:`ResponsesAdapter`  ``/responses``        —— OpenAI / Meta / DeepSeek 的第二套
* :class:`AnthropicAdapter`  ``/messages``
* :class:`OllamaAdapter`     ``/api/chat``         —— 本机

它们**都不自己判断多模态**:消息该长什么样、这个型号收不收图,统一问
``core.modality.prepare``。一条自己判就会有一天与另外三条不一样,而两边都不报错。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.llm_types import LLMResponse, ProviderConfig

logger = logging.getLogger("Galaxy.LLMRouter")


class BaseProviderAdapter:
    """提供商适配器基类"""

    DEFAULT_TIMEOUT = 30.0  # 默认请求超时
    MAX_RETRIES = 2  # 最大重试次数
    RETRY_BASE_DELAY = 1.0  # 重试基础延迟

    # HTTP status codes that are safe to retry (transient errors)
    _RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

    async def _post_with_retry(
        self,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
    ) -> httpx.Response:
        """POST request with automatic retry on transient failures (timeout, 5xx, 429).

        Uses exponential backoff: RETRY_BASE_DELAY * 2^attempt seconds between retries.
        Falls through to raise on non-retryable errors immediately.
        """
        # 出口闸:这是所有云端 provider POST 的收口点,所以判据放在这里就覆盖了
        # 全部厂商 —— 在每个适配器里各写一遍必然漏掉一家,而漏的表现是"某家突然
        # 连不上",没人会想到是这道闸。判据见 core/egress_guard.py。
        # audit 档(默认)只记账不拦,enforce 档才会抛 EgressBlocked。
        from core.egress_guard import check_egress  # noqa: PLC0415

        check_egress(url, purpose=f"llm:{self.config.name}")

        client = await self._get_client()
        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code in self._RETRYABLE_STATUS_CODES and attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "Retryable HTTP %d from %s (attempt %d/%d), retrying in %.1fs",
                        resp.status_code,
                        self.config.name,
                        attempt + 1,
                        self.MAX_RETRIES + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "Timeout from %s (attempt %d/%d), retrying in %.1fs",
                        self.config.name,
                        attempt + 1,
                        self.MAX_RETRIES + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except httpx.HTTPStatusError:
                # Non-retryable HTTP error, raise immediately
                raise
        # Should not reach here, but just in case
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Exhausted retries for {self.config.name}")

    async def chat(
        self,
        messages: List[Dict],
        model: str,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        **kwargs,
    ) -> LLMResponse:
        raise NotImplementedError(
            f"Provider adapter '{self.config.name}' 未实现 chat()，"
            f"请使用具体的适配器子类 (OpenAI/Anthropic/Google/DeepSeek)"
        )

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class OpenAIAdapter(BaseProviderAdapter):
    """OpenAI / OpenAI-compatible adapter"""

    async def chat(
        self, messages, model, tools=None, temperature=0.7, max_tokens=4096, response_format=None, **kwargs
    ) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        # 无鉴权的自托管服务(llama.cpp server / OpenVINO Model Server 默认不开
        # 鉴权)把 api_key 留空。此时**不能**照发 "Bearer " —— httpx 会在发出前就
        # 抛 LocalProtocolError: Illegal header value b'Bearer '。真实调用实测:
        # 一个 api_key="" 的 OpenAI 兼容 provider 每一次请求都在这一步直接炸,
        # 连不上服务器,报错还长得像网络问题。留空就干脆不带这个头。
        if (self.config.api_key or "").strip():
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        # 过统一的头。OpenAI 的原生形状就是仓内的规范表示,所以翻译那一步是空转;
        # 真正要它的是**另一半**:这一轮选中的型号收不收这些模态。收不了就压成
        # 文字并留痕,而不是发过去让上游安静地忽略掉。
        from core.modality import prepare

        messages = prepare("openai", messages, model=model, provider=self.config.name, cfg=self.config)

        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        if response_format:
            body["response_format"] = response_format

        # ── 型号级怪癖 ──────────────────────────────────────────────────────
        # 有的型号跟同门师兄弟不一样。第一个例子是 gpt-6-astra:它**不接受**
        # temperature / top_p / logprobs,而上面这几行每次都发 temperature ——
        # 不处理的话,把它登记进目录就等于登记了一个每次调用必炸的选项。
        #
        # 判据在 core.provider_registry.MODEL_QUIRKS,**不在这里**。散着写
        # `if model == "..."` 的话,第二个怪癖会写在第二个地方,然后就没人说得清
        # 到底哪些型号有特殊处理。
        from core.provider_registry import quirks_for

        _quirks = quirks_for(model)
        for _param in _quirks.get("omit_params", ()):
            body.pop(_param, None)

        # 工具在这条传输上不工作的型号:**换条路,不是丢工具**。
        #
        # 上一版这里是"丢掉并留痕" —— 那时本仓只有 chat/completions 一条路,
        # 留痕已经是当时能做到的最诚实的处理(至少不是静默地少做一件事)。
        # 补了 ResponsesAdapter 之后,正确的做法是走过去。
        #
        # 兜底仍然留着:选传输那一步在 _pick_adapter(),它已经把这种轮次拦去
        # Responses 了。真走到这里还带着工具,说明有人绕过了 _pick_adapter ——
        # 那时**说出来再丢**,而不是让上游收到一个它不认的字段。
        if tools and _quirks.get("needs_responses_for_tools"):
            body.pop("tools", None)
            logger.warning(
                "型号 %s 带着 %d 个工具走到了 chat/completions —— 它的工具只在 Responses 上工作。"
                "这一轮的工具已丢弃。正常路径不该到这里:选传输在 _pick_adapter(),"
                "说明有调用方绕过了它。依据:%s",
                model,
                len(tools),
                _quirks.get("why", "见 core/provider_registry.MODEL_QUIRKS"),
            )

        # 真流式:消费端挂了 TokenStream 且不是结构化输出请求时,SSE 边生成边吐字。
        # 任何流式失败都作废已流出内容并退回下面的非流式老路径(行为兜底不变)。
        _sink = kwargs.get("stream")
        if _sink is not None and response_format is None:
            try:
                return await self._chat_streaming(
                    headers=headers,
                    body=body,
                    model=model,
                    sink=_sink,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("OpenAI 兼容流式失败,退回非流式: %s", exc)
                try:
                    _sink.reset()
                except Exception:  # noqa: BLE001
                    pass

        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{self.config.base_url}/chat/completions",
            headers=headers,
            body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})
        tool_calls = None
        if choice["message"].get("tool_calls"):
            tool_calls = [tc for tc in choice["message"]["tool_calls"]]

        return LLMResponse(
            content=choice["message"].get("content") or "",
            provider=self.config.name,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency,
            tool_calls=tool_calls,
            raw_response=data,
        )

    @staticmethod
    def _merge_tool_call_delta(acc: Dict[int, Dict[str, Any]], delta_tc: Dict[str, Any]) -> None:
        """把一条流式 tool_call 增量并进按 index 聚合的累积表。

        OpenAI 流式协议:tool_calls 增量按 ``index`` 定位;首个增量带 id/name,
        后续增量只带 ``function.arguments`` 的字符串片段,需按序拼接。
        """
        idx = int(delta_tc.get("index", 0) or 0)
        slot = acc.setdefault(
            idx,
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        if delta_tc.get("id"):
            slot["id"] = delta_tc["id"]
        if delta_tc.get("type"):
            slot["type"] = delta_tc["type"]
        fn = delta_tc.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]

    async def _chat_streaming(self, *, headers, body, model, sink) -> LLMResponse:
        """OpenAI 兼容 SSE 真流式:content 增量喂 sink,tool_calls 增量按 index 组装。

        只把【正文】流出给用户;工具调用参数片段绝不进 sink。usage 仅在服务端支持
        ``stream_options.include_usage`` 时可得,拿不到就记 0(成本统计的已知取舍)。
        """
        stream_body = {**body, "stream": True, "stream_options": {"include_usage": True}}
        client = await self._get_client()
        t0 = time.monotonic()
        content_parts: List[str] = []
        tool_acc: Dict[int, Dict[str, Any]] = {}
        usage: Dict[str, Any] = {}
        async with client.stream(
            "POST",
            f"{self.config.base_url}/chat/completions",
            headers=headers,
            json=stream_body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = (line or "").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except (ValueError, TypeError):
                    continue
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
                    sink.feed(piece)
                for delta_tc in delta.get("tool_calls") or []:
                    if isinstance(delta_tc, dict):
                        self._merge_tool_call_delta(tool_acc, delta_tc)
        latency = (time.monotonic() - t0) * 1000
        tool_calls = [tool_acc[i] for i in sorted(tool_acc)] or None
        return LLMResponse(
            content="".join(content_parts),
            provider=self.config.name,
            model=model,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=latency,
            tool_calls=tool_calls,
            raw_response=None,  # 流式无整包 JSON;下游一律以 LLMResponse 字段为准
        )


class ResponsesAdapter(BaseProviderAdapter):
    """OpenAI **Responses** 格式 —— 本仓的第二条传输。

    ## 为什么需要它

    ``OpenAIAdapter`` 走的是 ``/chat/completions``。那条路够用了很久,直到出现
    **在 chat/completions 上残缺的型号**:``gpt-6-astra`` 支持 chat/completions,
    但**工具调用只能走 Responses**。没有这条适配器时,我们只能在那种型号上把工具
    丢掉并留痕 —— 答得出话,做不了事。

    现在三家都讲这个格式(各自一手文档核实过):

    * **OpenAI** —— 原生;``gpt-6-astra`` 的工具必须走这里
    * **Meta Model API** —— 官方说 Chat Completions 与 Responses 两种格式同一后端
    * **DeepSeek** —— ``api.deepseek.com`` 原生支持 Responses 格式(为 Codex 适配),
      v4-flash / v4-pro 都可以

    ## 与 chat/completions 的三处真差别

    1. **``input`` 不是 ``messages``。** 形状相近(role/content),但字段名不同,
       而且它接受"上一轮的输出条目"直接回灌 —— 本仓暂时只送 role/content,
       多轮仍由上层拼好整段历史传进来,与 chat 那条一致。
    2. **工具是平铺的。** chat 里是 ``{"type":"function","function":{...}}``,
       Responses 里是 ``{"type":"function","name":...,"parameters":...}`` 平一层。
       不转换的话上游会当成没有工具 —— 又是一次"看起来接上了,其实没有"。
    3. **``max_output_tokens``,不是 ``max_tokens``。** 名字不同,发错了会被忽略,
       于是输出长度悄悄变成上游默认值。

    ## 不做的事

    不实现流式。Responses 的 SSE 事件模型与 chat 那条完全不同,而本仓的流式消费端
    (TokenStream)是照 chat 的 delta 写的。硬接一半的话,"流式失败退回非流式"那条
    兜底会被触发得毫无规律 —— 那比不支持更难排查。需要流式的轮次仍走 chat 那条。
    """

    async def chat(
        self, messages, model, tools=None, temperature=0.7, max_tokens=4096, response_format=None, **kwargs
    ) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        if (self.config.api_key or "").strip():
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        # Responses 的部件名与 chat 不同(input_text / input_image),而且 input_image
        # 的 image_url 是字符串不是对象。发成 chat 的形状不会报错,只会被当成没带图。
        from core.modality import prepare

        messages = prepare("responses", messages, model=model, provider=self.config.name, cfg=self.config)

        body: Dict[str, Any] = {
            "model": model,
            "input": [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = self._flatten_tools(tools)

        # 型号级怪癖对两条传输一视同仁:gpt-6-astra 在 Responses 上同样不收
        # temperature / top_p。判据仍在 provider_registry,不在这里另存一份。
        from core.provider_registry import quirks_for

        for _param in quirks_for(model).get("omit_params", ()):
            body.pop(_param, None)

        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{self.config.base_url}/responses",
            headers=headers,
            body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()
        content, tool_calls = self._read_output(data)
        usage = data.get("usage") or {}

        return LLMResponse(
            content=content,
            provider=self.config.name,
            model=model,
            # Responses 用 input_tokens / output_tokens;chat 用 prompt_/completion_。
            # 两个名字都认,取不到就是 0 —— **不猜**,0 在上层是"没拿到用量"。
            input_tokens=int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            latency_ms=latency,
            tool_calls=tool_calls or None,
            raw_response=data,
        )

    @staticmethod
    def _flatten_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """chat 的嵌套工具声明 → Responses 的平铺形状。

        已经是平的就原样放行 —— 调用方可能直接按 Responses 的形状给。
        """
        out: List[Dict[str, Any]] = []
        for tool in tools:
            fn = tool.get("function")
            if not isinstance(fn, dict):
                out.append(tool)
                continue
            flat: Dict[str, Any] = {"type": "function", "name": fn.get("name", "")}
            if fn.get("description"):
                flat["description"] = fn["description"]
            if fn.get("parameters") is not None:
                flat["parameters"] = fn["parameters"]
            out.append(flat)
        return out

    @staticmethod
    def _read_output(data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
        """从 Responses 的 ``output`` 数组里读出文字与工具调用。

        ``output`` 是一串条目,类型混着来:``message`` 里是文字(它自己的 content
        又是一串带 type 的块),``function_call`` 是一次工具调用。**不是**
        ``choices[0].message`` 那种单点结构 —— 照 chat 的形状去读会读到空。

        认不出来的条目类型直接跳过,不抛异常:上游加新类型是常事,为一个不认识的
        条目让整轮失败,代价远大于收益。
        """
        text_parts: List[str] = []
        calls: List[Dict[str, Any]] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "message":
                for block in item.get("content") or []:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        text_parts.append(block["text"])
            elif kind == "function_call":
                # 回填成 chat 那边的形状,让上层只认识一种工具调用结构。
                calls.append(
                    {
                        "id": item.get("call_id") or item.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": item.get("arguments", ""),
                        },
                    }
                )
        # 有的实现同时给一个拼好的 output_text,拿它当兜底(不覆盖已读到的)。
        if not text_parts and isinstance(data.get("output_text"), str):
            text_parts.append(data["output_text"])
        return "".join(text_parts), calls


class AnthropicAdapter(BaseProviderAdapter):
    """Anthropic Claude adapter (Messages API)"""

    async def chat(
        self, messages, model, tools=None, temperature=0.7, max_tokens=4096, response_format=None, **kwargs
    ) -> LLMResponse:
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # 先把规范表示(OpenAI content 数组)翻成 Anthropic 的块,再抽 system。
        # 顺序不能反:翻译之前 content 可能是数组,下面那句字符串拼接会当场 TypeError
        # ——**这条路以前就是炸的**,所以原生多模态一直只敢对 OpenAI 兼容面开。
        from core.modality import prepare, text_of

        messages = prepare("anthropic", messages, model=model, provider=self.config.name, cfg=self.config)

        # 从 messages 提取 system
        system_text = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text += text_of(m.get("content")) + "\n"
            else:
                user_messages.append(m)

        body: Dict[str, Any] = {
            "model": model,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text.strip():
            body["system"] = system_text.strip()
        if tools:
            # 转换 OpenAI tool 格式 → Anthropic tool 格式
            body["tools"] = self._convert_tools(tools)

        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{self.config.base_url}/messages",
            headers=headers,
            body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()

        content = ""
        tool_calls = []
        for block in data.get("content", []):
            if block["type"] == "text":
                content += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append(
                    {
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    }
                )

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            provider=self.config.name,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=latency,
            tool_calls=tool_calls if tool_calls else None,
            raw_response=data,
        )

    @staticmethod
    def _convert_tools(openai_tools: List[Dict]) -> List[Dict]:
        """OpenAI tool format → Anthropic tool format"""
        anthropic_tools = []
        for t in openai_tools:
            if t.get("type") == "function":
                fn = t["function"]
                anthropic_tools.append(
                    {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    }
                )
        return anthropic_tools


class OllamaAdapter(BaseProviderAdapter):
    """Ollama local model adapter

    工具调用双协议:
      1. **原生 function calling**(qwen/minicpm/llama3.1 等带工具模板的模型):
         tools 随请求体,解析 message.tool_calls。
      2. **文本协议兜底**(gemma 系等无工具模板的模型,Ollama 回 400
         "does not support tools"):把工具清单注入系统消息,约定模型用一行
         JSON ``{"tool_call": {"name": ..., "arguments": {...}}}`` 表达调用,
         从回复文本解析并归一成 OpenAI 形状——gemma 也能真正调工具
         (表达力略逊原生,但完整可用)。一旦某模型判定为无模板,按模型名
         缓存,后续请求直接走文本协议,不再吃 400 往返。
    """

    #: 已判定不支持原生工具的模型(进程内缓存,免每次吃 400)
    _text_protocol_models: set = set()

    _TEXT_TOOL_INSTRUCTION = (
        "你可以调用以下工具来完成任务。工具清单(JSON Schema):\n{tool_specs}\n"
        "调用规则:需要调用工具时,只输出一行 JSON(不要任何其它文字、"
        "不要代码围栏):\n"
        '{{"tool_call": {{"name": "<工具名>", "arguments": {{<参数>}}}}}}\n'
        "工具结果会以 [工具结果] 消息回给你;不需要工具时直接正常回答。"
    )

    @classmethod
    def _tools_prompt(cls, tools: List[Dict]) -> str:
        specs = []
        for t in tools or []:
            fn = t.get("function") if isinstance(t, dict) else None
            if isinstance(fn, dict):
                specs.append(
                    {
                        "name": fn.get("name", ""),
                        "description": (fn.get("description") or "")[:200],
                        "parameters": fn.get("parameters") or {},
                    }
                )
        return cls._TEXT_TOOL_INSTRUCTION.format(tool_specs=json.dumps(specs, ensure_ascii=False))

    @classmethod
    def _inject_text_tools(cls, messages: List[Dict], tools: List[Dict]) -> List[Dict]:
        """把工具清单作为系统消息注入(紧跟首条 system 之后,前缀尽量稳定)。"""
        tool_msg = {"role": "system", "content": cls._tools_prompt(tools)}
        out = list(messages)
        idx = 1 if (out and out[0].get("role") == "system") else 0
        out.insert(idx, tool_msg)
        return out

    @staticmethod
    def _textualize_tool_history(messages: List[Dict]) -> List[Dict]:
        """文本协议模型看不懂 role=tool / assistant.tool_calls——把工具轮历史
        转成纯文本(assistant 的调用还原成它当初输出的 JSON 行;tool 结果转
        user 的 [工具结果] 消息),模板不炸、上下文语义不丢。"""
        out: List[Dict] = []
        for m in messages:
            if not isinstance(m, dict):
                out.append(m)
                continue
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                lines = []
                for tc in m["tool_calls"]:
                    fn = (tc or {}).get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (ValueError, TypeError):
                            args = {}
                    lines.append(
                        json.dumps(
                            {"tool_call": {"name": fn.get("name", ""), "arguments": args or {}}}, ensure_ascii=False
                        )
                    )
                content = (m.get("content") or "").strip()
                out.append({"role": "assistant", "content": (content + "\n" if content else "") + "\n".join(lines)})
            elif role == "tool":
                out.append({"role": "user", "content": f"[工具结果] {m.get('content', '')}"})
            else:
                out.append(m)
        return out

    @staticmethod
    def _parse_text_tool_calls(content: str) -> Optional[List[Dict]]:
        """从回复文本解析 {"tool_call": {...}} 调用(容忍前后缀文字/代码围栏),
        归一成 OpenAI 形状。没有合法调用返回 None(当普通回答)。"""
        if not content or '"tool_call"' not in content:
            return None
        calls: List[Dict] = []
        i = 0
        while True:
            k = content.find('"tool_call"', i)
            if k < 0:
                break
            start = content.rfind("{", 0, k)
            if start < 0:
                i = k + 11
                continue
            depth = 0
            end = -1
            for j in range(start, len(content)):
                if content[j] == "{":
                    depth += 1
                elif content[j] == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            if end < 0:
                break
            try:
                obj = json.loads(content[start : end + 1])
                tc = obj.get("tool_call") or {}
                name = tc.get("name", "")
                if name:
                    calls.append(
                        {
                            "id": f"ollama_text_call_{len(calls)}_{name}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                            },
                        }
                    )
            except (ValueError, TypeError):
                pass
            i = end + 1 if end >= 0 else k + 11
        return calls or None

    def _to_ollama_messages(self, messages, model: str = ""):
        """把消息规范成 Ollama 原生格式(图像挂 message 级 ``images``)。

        翻译本身在 ``core.modality.prepare`` —— 四条协议的原生形状、以及"这个型号
        收不收"那一步,都收在同一处,不再一条在这个适配器里、另外三条各在各处。
        这里留一个转调是因为既有测试和调用方都按这个名字找它。
        """
        from core.modality import prepare

        return prepare(
            "ollama",
            messages,
            model=model or self.config.default_model,
            provider=self.config.name,
            cfg=self.config,
        )

    @staticmethod
    def _normalize_tool_calls(raw_calls: Any) -> Optional[List[Dict]]:
        """Ollama 原生 tool_calls → OpenAI 形状(下游 ReAct 统一按此消费)。

        差异:Ollama 的 function.arguments 是 **dict**(OpenAI 是 JSON 字符串),
        且不带 id。这里统一转字符串 + 合成 id,让 openclawd 的
        ``json.loads(fn["arguments"])`` 两家通吃。
        """
        if not raw_calls:
            return None
        out: List[Dict] = []
        for i, tc in enumerate(raw_calls):
            fn = (tc or {}).get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, (dict, list)):
                args = json.dumps(args, ensure_ascii=False)
            elif not isinstance(args, str):
                args = "{}"
            out.append(
                {
                    "id": tc.get("id") or f"ollama_call_{i}_{fn.get('name', '')}",
                    "type": "function",
                    "function": {"name": fn.get("name", ""), "arguments": args},
                }
            )
        return out or None

    @staticmethod
    def _is_tools_unsupported_error(exc: Exception) -> bool:
        """Ollama 对无工具模板的模型(如 gemma 系)回 400 'does not support tools'。"""
        try:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                return exc.response.status_code == 400 and "tool" in exc.response.text.lower()
        except Exception:  # noqa: BLE001
            pass
        return False

    async def chat(
        self, messages, model, tools=None, temperature=0.7, max_tokens=4096, response_format=None, **kwargs
    ) -> LLMResponse:
        # 模型常驻不卸载(-1):Ollama 默认几分钟不用就卸出内存,下次请求整段
        # 冷加载——真机"等待窗口未响应/像冷启动"的来源。按请求带上,即使
        # ollama serve 是安装器自启的(拿不到我们 spawn 时的环境变量)也生效。
        # 纯数字须转 int(JSON number;裸 "-1" 字符串无时长单位会解析失败),
        # "10m" 之类的时长字符串原样透传。
        _keep_alive: Any = os.environ.get("GALAXY_OLLAMA_KEEP_ALIVE", "-1")
        try:
            _keep_alive = int(_keep_alive)
        except (TypeError, ValueError):
            pass
        _options: Dict[str, Any] = {"temperature": temperature, "num_predict": max_tokens}
        # num_ctx 显式设置:系统提示+工具定义+记忆+历史很容易超过模型默认上下文
        # (常为 4096),一旦溢出 Ollama 滑窗截断 → 前缀 KV 缓存每轮全废 → 每轮
        # ReAct 全量重预填,CPU 机上就是"越聊越慢"。设 0/空 则不传(回到模型默认)。
        #
        # 默认值**不再是写死的 8192**。那个数是拍的:本仓库按自己配的预算
        # (GALAXY_TOOLS_MAX 个工具定义 + GALAXY_TOOL_PRUNE_KEEP_ROUNDS 轮工具结果
        # + 系统提示)一次能装配到一万一千多 token —— 8192 同样不够,只是比 llama.cpp
        # 那条路的 4096 好一点。两条加载路径各拍一个数、都没算过实际装配量,正是
        # "同一判据两处各写各的"。现在两边都问 ComputeScheduler.context_budget_for。
        try:
            _env_num_ctx = os.environ.get("GALAXY_OLLAMA_NUM_CTX", "").strip()
            if _env_num_ctx:
                _num_ctx = int(_env_num_ctx)  # 显式指定一律尊重(含 0 = 不传)
            else:
                from core.compute_scheduler import get_compute_scheduler

                _num_ctx, _ctx_why = get_compute_scheduler().context_budget_for(model)
                logger.debug("Ollama 上下文预算: %s → num_ctx=%s(%s)", model, _num_ctx, _ctx_why)
            if _num_ctx > 0:
                _options["num_ctx"] = _num_ctx
        except (TypeError, ValueError, Exception):  # noqa: BLE001 — 算不出来退回原来的保守默认
            _options["num_ctx"] = 8192
        body = {
            "model": model,
            "messages": self._to_ollama_messages(messages, model),
            "stream": False,
            "options": _options,
            "keep_alive": _keep_alive,
        }
        # 原生 function calling:Ollama /api/chat 支持 OpenAI 形状的 tools
        # (qwen/minicpm/llama3.1 等带工具模板的模型)。此前适配器收了 tools
        # 却不发——本地主脑从来"看不到"工具,整个 ReAct 工具层对 Ollama 是哑的。
        if tools:
            body["tools"] = tools

        # 调用点兜底:即使 config.base_url 因某条边缘路径被置空/缺协议头,
        # 也在此归一,绝不把坏 URL 交给 httpx(否则炸 "Request URL is missing
        # an 'http://' or 'https://' protocol")。
        _base = (self.config.base_url or "").strip() or "http://localhost:11434"
        if not _base.startswith(("http://", "https://")):
            _base = f"http://{_base}"

        # 已知无工具模板的模型(gemma 系,进程内缓存):直接走文本协议,
        # 不再吃一次 400 往返。
        if tools and model in type(self)._text_protocol_models:
            return await self._chat_text_protocol(
                base=_base,
                messages=messages,
                model=model,
                tools=tools,
                options=_options,
                keep_alive=_keep_alive,
                sink=kwargs.get("stream"),
            )

        # 真流式:消费端挂了 TokenStream 时走 NDJSON 流(CPU 慢速生成下体感差异
        # 最大的一段——首句几秒就能上屏,不用等整段几十秒)。失败作废已流出内容,
        # 退回下面的非流式老路径。
        _sink = kwargs.get("stream")
        if _sink is not None:
            try:
                return await self._chat_streaming(
                    base=_base,
                    body=body,
                    model=model,
                    sink=_sink,
                )
            except Exception as exc:  # noqa: BLE001
                if self._is_tools_unsupported_error(exc) and "tools" in body:
                    # 模型无工具模板(gemma 系):切文本协议重试——工具清单注入
                    # 提示词、从文本解析 JSON 调用,gemma 也能真正调工具。
                    logger.info(
                        "Ollama 模型 %s 不支持原生工具,切文本协议工具兜底",
                        model,
                    )
                    try:
                        _sink.reset()
                    except Exception:  # noqa: BLE001
                        pass
                    return await self._chat_text_protocol(
                        base=_base,
                        messages=messages,
                        model=model,
                        tools=tools,
                        options=_options,
                        keep_alive=_keep_alive,
                        sink=_sink,
                    )
                logger.info("Ollama 流式失败,退回非流式: %s", exc)
                try:
                    _sink.reset()
                except Exception:  # noqa: BLE001
                    pass

        t0 = time.monotonic()
        try:
            resp = await self._post_with_retry(
                f"{_base}/api/chat",
                headers={"Content-Type": "application/json"},
                body=body,
            )
        except httpx.HTTPStatusError as exc:
            if not (self._is_tools_unsupported_error(exc) and "tools" in body):
                raise
            logger.info(
                "Ollama 模型 %s 不支持原生工具,切文本协议工具兜底",
                model,
            )
            return await self._chat_text_protocol(
                base=_base,
                messages=messages,
                model=model,
                tools=tools,
                options=_options,
                keep_alive=_keep_alive,
                sink=kwargs.get("stream"),
            )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()

        _msg = data.get("message", {}) or {}
        return LLMResponse(
            content=_msg.get("content", ""),
            provider=self.config.name,
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=latency,
            tool_calls=self._normalize_tool_calls(_msg.get("tool_calls")),
            raw_response=data,
        )

    async def _chat_text_protocol(
        self,
        *,
        base,
        messages,
        model,
        tools,
        options,
        keep_alive,
        sink=None,
    ) -> LLMResponse:
        """文本协议工具兜底:无工具模板模型(gemma 系)的完整工具调用通路。

        - 工具清单注入系统消息;工具轮历史文本化(模板不炸);
        - 非流式请求(避免半截 JSON 泄进面板气泡);
        - 回复里解析到 {"tool_call": ...} → 归一成 OpenAI 形状返回给 ReAct;
          没解析到 → 普通回答,整段补喂 sink(伪流式,面板仍有字)。
        """
        type(self)._text_protocol_models.add(model)
        msgs = self._inject_text_tools(self._textualize_tool_history(messages), tools)
        body = {
            "model": model,
            "messages": self._to_ollama_messages(msgs, model),
            "stream": False,
            "options": options,
            "keep_alive": keep_alive,
        }
        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{base}/api/chat",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()
        _msg = data.get("message", {}) or {}
        content = _msg.get("content", "") or ""
        tool_calls = self._parse_text_tool_calls(content)
        if tool_calls is None and sink is not None:
            try:
                sink.feed(content)
            except Exception:  # noqa: BLE001
                pass
        return LLMResponse(
            # 解析到调用时正文置空:JSON 调用行是协议载荷,不是给用户看的话
            content="" if tool_calls else content,
            provider=self.config.name,
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=latency,
            tool_calls=tool_calls,
            raw_response=data,
        )

    async def _chat_streaming(self, *, base, body, model, sink) -> LLMResponse:
        """Ollama /api/chat NDJSON 真流式:每行一个 JSON 块,message.content 是增量;
        末块 done=true 携带 prompt_eval_count/eval_count(token 统计不丢)。"""
        stream_body = {**body, "stream": True}
        client = await self._get_client()
        t0 = time.monotonic()
        content_parts: List[str] = []
        raw_tool_calls: List[Dict] = []
        final: Dict[str, Any] = {}
        async with client.stream(
            "POST",
            f"{base}/api/chat",
            headers={"Content-Type": "application/json"},
            json=stream_body,
        ) as resp:
            if getattr(resp, "status_code", 200) >= 400:
                # 让 chat() 的"模型不支持工具 → 去工具重试"能拿到响应体判因
                await resp.aread()
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except (ValueError, TypeError):
                    continue
                _cmsg = chunk.get("message") or {}
                piece = _cmsg.get("content", "")
                if piece:
                    content_parts.append(piece)
                    sink.feed(piece)
                # 工具调用块:Ollama 流式在(通常是末尾的)块上整只给出
                # message.tool_calls,不是 OpenAI 式碎片增量——直接收集,
                # 绝不喂 sink(工具调用不是正文)。
                if _cmsg.get("tool_calls"):
                    raw_tool_calls.extend(_cmsg["tool_calls"])
                if chunk.get("done"):
                    final = chunk
        latency = (time.monotonic() - t0) * 1000
        return LLMResponse(
            content="".join(content_parts),
            provider=self.config.name,
            model=model,
            input_tokens=int(final.get("prompt_eval_count", 0) or 0),
            output_tokens=int(final.get("eval_count", 0) or 0),
            latency_ms=latency,
            tool_calls=self._normalize_tool_calls(raw_tool_calls),
            raw_response=final or None,
        )


# ───────────────────── 主路由器 ─────────────────────

# L1 收口:协议 → 适配器工厂。此前每个 OpenAI 兼容提供商都有一个空壳子类
# (class DeepSeekAdapter(OpenAIAdapter): pass …共 12 个),纯冗余。现在按【协议】
# 选适配器:openai 兼容全用 OpenAIAdapter、anthropic 用 AnthropicAdapter、
# 本地 ollama 用 OllamaAdapter。新增一个 OpenAI 兼容提供商不再需要建类。
