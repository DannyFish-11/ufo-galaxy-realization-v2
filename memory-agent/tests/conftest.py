"""测试公共设施。

两类用例并存(BUILD_SPEC 执行纪律:不为通过测试而弱化断言):
- 逻辑/单元用例:用 config 显式选择的 fake 嵌入后端 + verbatim 抽取 + 内存/本地
  Qdrant,离线可跑,验证本项目自身的存储/检索/编排/接口逻辑;
- 规格验收(integration)用例:按 BUILD_SPEC 原文断言,依赖真实 L0/L1/L2 服务,
  服务不可达时显式 SKIP 并注明原因(在目标硬件上必须全绿)。
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import (  # noqa: E402
    AgentSettings,
    AppConfig,
    EmbedderSettings,
    LLMSettings,
    MemorySettings,
    ServiceSettings,
    VectorDBSettings,
)
from core.schemas import Message  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

LLM_URL = os.environ.get("MEMORY_AGENT_LLM__BASE_URL", "http://localhost:8000/v1")
EMBED_URL = os.environ.get("MEMORY_AGENT_EMBEDDER__BASE_URL", "http://localhost:8001")
API_URL = os.environ.get("MEMORY_AGENT_API_URL", "http://localhost:8002")


@functools.cache
def service_up(url: str) -> bool:
    try:
        httpx.get(url, timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


def requires_live(url: str, name: str):
    return pytest.mark.skipif(
        not service_up(url),
        reason=f"规格验收用例:{name} ({url}) 不可达 —— 须在目标硬件上运行",
    )


def make_fake_config(tmp_path: Path | None = None, vect_mode: str = "memory") -> AppConfig:
    vdb = VectorDBSettings(mode=vect_mode, collection="test_memories")  # type: ignore[arg-type]
    if vect_mode == "local":
        assert tmp_path is not None
        vdb = VectorDBSettings(mode="local", path=str(tmp_path / "qdrant"), collection="test_memories")
    return AppConfig(
        llm=LLMSettings(base_url="http://127.0.0.1:1/v1", model="test-model"),
        embedder=EmbedderSettings(backend="fake", dim=64, model_name="fake-deterministic"),
        vectordb=vdb,
        memory=MemorySettings(extraction="verbatim"),
        services=ServiceSettings(),
        agent=AgentSettings(top_k=5),
    )


class ScriptedLLM:
    """按脚本回复的 LLMClient;记录全部调用供断言。"""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[list[Message]] = []

    async def chat(self, messages: list[Message], **kw) -> str:
        self.calls.append(messages)
        if self.replies:
            return self.replies.pop(0)
        return "OK"


class EchoMemoryLLM(ScriptedLLM):
    """把 system prompt 中「相关记忆」块原样复述 —— 用于离线验证记忆注入链路。"""

    async def chat(self, messages: list[Message], **kw) -> str:
        self.calls.append(messages)
        system = next((m for m in messages if m.role == "system"), None)
        if system and isinstance(system.content, str) and "## 相关记忆" in system.content:
            return "根据我的记忆:" + system.content.split("## 相关记忆", 1)[1]
        return "(无记忆)"


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=True))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


@pytest.fixture(scope="session", autouse=True)
def ensure_fixtures() -> None:
    if not (FIXTURES / "white_cat.png").exists():
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import make_fixtures

        make_fixtures.main()
