"""模型路由节点（Node_58）从不编一句回答：问到了模型就是模型的话，一个模型都没有就说没有（503）。

全面排查第 7 轮把辩论接口接通之后，回来的是这样一份辩论：每位辩手都答「[Mock Response] Processed by llama2」，
结论「达成共识」。查下去：Node_58 的云端那一档是桩 —— 从不调用任何模型，回一句「[Mock Cloud Response] Processed
by gpt-4」；本地 Ollama 调不通也回一句「[Mock Response] …」。谁问它都会拿到一句像是回答的假话。

现在两档都走系统自己的路由器（``core.multi_llm_router``，与对话主链同一个：人在面板上配的那几家，本地优先）；
它说一个模型都没有，节点就回 503 并带上原因，辩论接口原样转给调用方。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from core.llm_types import LLMResponse

REPO_ROOT = Path(__file__).resolve().parents[1]


def _node():
    main_py = REPO_ROOT / "nodes" / "Node_58_ModelRouter" / "main.py"
    spec = importlib.util.spec_from_file_location("_node_58_main", main_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Router:
    def __init__(self, response: LLMResponse):
        self.response = response
        self.asked = []

    async def chat(self, messages, **kw):
        self.asked.append(messages)
        return self.response


@pytest.fixture()
def node(tmp_path, monkeypatch):
    mod = _node()
    # 本地 Ollama 指向一个没人听的端口：本地那一档调不通
    router = mod.ModelRouter("http://127.0.0.1:9", "", mod.DatabaseManager(str(tmp_path / "router.db")))
    return mod, router


def _ask(mod, router, model):
    return asyncio.run(router.chat(mod.ChatRequest(prompt="1+1 等于几？", model=model, max_tokens=20)))


@pytest.mark.parametrize("model", ["gpt-4", "llama2"])  # 云端那一档 / 本地那一档调不通之后
def test_an_answer_comes_from_a_real_model(node, monkeypatch, model):
    mod, router = node
    real = _Router(LLMResponse(content="2", provider="deepseek", model="deepseek-chat", output_tokens=1))
    monkeypatch.setattr("core.multi_llm_router.get_llm_router", lambda: real)
    out = _ask(mod, router, model)
    assert out.response == "2" and "Mock" not in out.response
    assert real.asked == [[{"role": "user", "content": "1+1 等于几？"}]]


@pytest.mark.parametrize("model", ["gpt-4", "llama2"])
def test_no_model_at_all_is_a_503_with_the_reason(node, monkeypatch, model):
    mod, router = node
    none = _Router(LLMResponse(content="还没有可用的 AI 服务：没有配置任何 API Key……", provider="none", model="none"))
    monkeypatch.setattr("core.multi_llm_router.get_llm_router", lambda: none)
    with pytest.raises(HTTPException) as caught:
        _ask(mod, router, model)
    assert caught.value.status_code == 503 and "还没有可用的 AI 服务" in caught.value.detail


def test_nothing_in_the_node_makes_up_a_reply():
    src = (REPO_ROOT / "nodes" / "Node_58_ModelRouter" / "main.py").read_text(encoding="utf-8")
    assert 'return f"[Mock' not in src
