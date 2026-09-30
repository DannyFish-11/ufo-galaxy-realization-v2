"""L0 适配层:LLMClient 协议 + vLLM OpenAI 兼容端点适配器。

核心逻辑只依赖 LLMClient 协议;对 vLLM/OpenAI 协议细节的所有知识收敛在本文件。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx

from core.errors import LayerError
from core.schemas import Message


@runtime_checkable
class LLMClient(Protocol):
    async def chat(self, messages: list[Message], **kw) -> str: ...


class VLLMOpenAIAdapter:
    """通过 OpenAI 兼容 /chat/completions 调用 vLLM 上的 Gemma 4。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            transport=transport,
        )

    async def chat(self, messages: list[Message], **kw: Any) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
        }
        payload.update(kw)
        try:
            resp = await self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LayerError("L0", "vllm", f"推理端点不可达 {self.base_url}: {exc}") from exc
        if resp.status_code != 200:
            raise LayerError("L0", "vllm", f"HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LayerError("L0", "vllm", f"响应结构异常: {data}") from exc
        if content is None:
            raise LayerError("L0", "vllm", f"空回复: {data}")
        return content

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/models")
        except httpx.HTTPError as exc:
            raise LayerError("L0", "vllm", f"健康检查失败 {self.base_url}/models: {exc}") from exc
        if resp.status_code != 200:
            raise LayerError("L0", "vllm", f"健康检查 HTTP {resp.status_code}")
        return True

    async def aclose(self) -> None:
        await self._client.aclose()
