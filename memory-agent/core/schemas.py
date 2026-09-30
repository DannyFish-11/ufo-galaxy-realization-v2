"""全部 Pydantic 模型(BUILD_SPEC §1 core/schemas.py、§3 接口契约的数据类型)。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

Modality = Literal["text", "image", "audio"]


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    # OpenAI 兼容:content 允许纯文本或多模态 parts 列表
    content: str | list[dict[str, Any]]


class MultimodalInput(BaseModel):
    """统一多模态输入。text 时 content 为原文;image/audio 时为 base64 编码字节。"""

    type: Modality
    content: str
    mime: str | None = None

    @classmethod
    def text(cls, content: str) -> "MultimodalInput":
        return cls(type="text", content=content)

    @classmethod
    def from_file(cls, path: str | Path, modality: Modality, mime: str | None = None) -> "MultimodalInput":
        data = Path(path).read_bytes()
        return cls(type=modality, content=base64.b64encode(data).decode("ascii"), mime=mime)

    def raw_bytes(self) -> bytes:
        if self.type == "text":
            return self.content.encode("utf-8")
        return base64.b64decode(self.content)


class MemoryHit(BaseModel):
    id: str
    score: float
    content: str
    modality: Modality = "text"
    meta: dict[str, Any] = Field(default_factory=dict)


class ConsolidationReport(BaseModel):
    total_before: int
    total_after: int
    merged_groups: int
    pruned: int
    details: list[str] = Field(default_factory=list)


# ---- L1 嵌入服务 ----

class EmbedRequest(BaseModel):
    inputs: list[MultimodalInput]


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    dim: int
    model: str


# ---- L3 API ----

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    image_base64: str | None = None
    image_mime: str | None = "image/png"


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    memories_used: list[MemoryHit] = Field(default_factory=list)


class MemoryAddRequest(BaseModel):
    input: MultimodalInput
    meta: dict[str, Any] = Field(default_factory=dict)


class MemoryAddResponse(BaseModel):
    ids: list[str]


class MemorySearchRequest(BaseModel):
    query: MultimodalInput
    k: int = 5


class HealthReport(BaseModel):
    status: Literal["ok", "degraded", "down"]
    layers: dict[str, str] = Field(default_factory=dict)
