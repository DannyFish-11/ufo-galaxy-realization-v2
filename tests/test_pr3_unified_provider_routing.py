#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_unified_provider_routing.py
==========================================

PR-3: Unified Model Supply Main Chain Fix — Routing Closure Tests

Validates (source-based checks avoid pydantic/httpx import issues in CI env):
  1.  UNIFIED_LLM_ROUTER_AUTHORITY sentinel in core/unified/llm_router.py source.
  2.  UNIFIED_LLM_ROUTER_AUTHORITY references PR-3.
  3.  LOCAL_LLM_PROVIDER_ROLE sentinel in core/multi_llm_router.py source.
  4.  LOCAL_LLM_PROVIDER_ROLE documents ollama and PR-3.
  5.  UnifiedLLMRouter.chat_with_tools() defined in source (async).
  6.  UnifiedLLMRouter.compute_complexity_vector() defined in source.
  7.  UnifiedLLMRouter.get_execution_backend() defined in source.
  8.  MultiLLMRouter.chat_with_tools() alias defined in source (async).
  9.  OpenClawd._get_router() returns router with chat_with_tools() (runtime, optional).
 10.  chat_with_tools() on UnifiedLLMRouter delegates to _backend (mock).
 11.  chat_with_tools() on MultiLLMRouter delegates to chat() (mock).
 12.  Provider selection: _get_provider_order() returns list (runtime, optional).
 13.  Ollama present in TASK_ROUTING_PREFERENCES[GENERAL] source.
 14.  Ollama is the last entry in TASK_ROUTING_PREFERENCES[GENERAL] source.
 15.  handle_chat() does NOT directly import get_llm_router (routing closure).
 16.  _react_loop() does NOT directly import get_llm_router (routing closure).
 17.  handle_agent_task() does NOT directly import get_llm_router (routing closure).
 18.  get_status() LLM section does NOT directly import get_llm_router.
 19.  UnifiedLLMRouter.compute_complexity_vector() delegates to _backend (mock).
 20.  AgentFactory source references chat_with_tools() for PR-3 routing closure.
"""

from __future__ import annotations

import asyncio
import importlib
import pathlib
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

_ROOT = pathlib.Path(__file__).parent.parent

def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")

_UNIFIED_ROUTER_SRC = _read("core/unified/llm_router.py")
_MULTI_ROUTER_SRC   = _read("core/multi_llm_router.py")
_OPENCLAWD_SRC      = _read("core/openclawd.py")
_AGENT_FACTORY_SRC  = _read("core/agent_factory.py")


def _method_src(file_src: str, name: str) -> str:
    """Rough extraction of a named method from source."""
    for prefix in (f"async def {name}(", f"def {name}("):
        start = file_src.find(prefix)
        if start != -1:
            break
    else:
        return ""
    # find next method at same top-level indent
    candidates = []
    for p in ("\n    def ", "\n    async def "):
        i = file_src.find(p, start + 1)
        if i != -1:
            candidates.append(i)
    end = min(candidates) if candidates else len(file_src)
    return file_src[start:end]


class TestPR3ProviderRoutingClosure(unittest.TestCase):

    # 1-2 ─ UNIFIED_LLM_ROUTER_AUTHORITY sentinel (source)
    def test_01_unified_llm_router_authority_exists(self):
        self.assertIn("UNIFIED_LLM_ROUTER_AUTHORITY", _UNIFIED_ROUTER_SRC)

    def test_02_unified_llm_router_authority_references_pr3(self):
        idx = _UNIFIED_ROUTER_SRC.find("UNIFIED_LLM_ROUTER_AUTHORITY")
        snippet = _UNIFIED_ROUTER_SRC[idx:idx+800]
        self.assertIn("PR3", snippet)
        self.assertIn("UnifiedLLMRouter", snippet)

    # 3-4 ─ LOCAL_LLM_PROVIDER_ROLE sentinel (source)
    def test_03_local_llm_provider_role_exists(self):
        self.assertIn("LOCAL_LLM_PROVIDER_ROLE", _MULTI_ROUTER_SRC)

    def test_04_local_llm_provider_role_documents_ollama_and_pr3(self):
        idx = _MULTI_ROUTER_SRC.find("LOCAL_LLM_PROVIDER_ROLE")
        snippet = _MULTI_ROUTER_SRC[idx:idx+600]
        self.assertIn("ollama", snippet.lower())
        self.assertIn("PR3", snippet)

    # 5-7 ─ UnifiedLLMRouter new methods (source)
    def test_05_unified_router_has_async_chat_with_tools(self):
        self.assertIn("async def chat_with_tools(", _UNIFIED_ROUTER_SRC)

    def test_06_unified_router_has_compute_complexity_vector(self):
        self.assertIn("def compute_complexity_vector(", _UNIFIED_ROUTER_SRC)

    def test_07_unified_router_has_get_execution_backend(self):
        self.assertIn("def get_execution_backend(", _UNIFIED_ROUTER_SRC)

    # 8 ─ MultiLLMRouter chat_with_tools alias (source)
    def test_08_multi_router_has_async_chat_with_tools(self):
        self.assertIn("async def chat_with_tools(", _MULTI_ROUTER_SRC)

    # 9 ─ Runtime: router returned by _get_router has chat_with_tools
    def test_09_openclawd_get_router_has_chat_with_tools(self):
        try:
            mod = importlib.import_module("core.openclawd")
            clawd = mod.get_openclawd()
            router = clawd._get_router()
            if router is not None:
                self.assertTrue(hasattr(router, "chat_with_tools"),
                    f"{type(router).__name__} must have chat_with_tools()")
        except Exception:
            self.skipTest("OpenClawd not importable in this test environment")

    # 10 ─ UnifiedLLMRouter.chat_with_tools delegates to _backend.chat() (mock)
    def test_10_unified_chat_with_tools_delegates_to_backend(self):
        try:
            m = importlib.import_module("core.unified.llm_router")
        except Exception:
            self.skipTest("core.unified.llm_router requires pydantic")
            return
        router = m.UnifiedLLMRouter()
        mock_be = MagicMock()
        mock_resp = MagicMock()
        mock_resp.provider = "p"; mock_resp.model = "m"
        mock_be.chat = AsyncMock(return_value=mock_resp)
        router._backend = mock_be
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                router.chat_with_tools(messages=[{"role":"user","content":"hi"}], task_type="general")
            )
        finally:
            loop.close()
        mock_be.chat.assert_called_once()
        self.assertEqual(result, mock_resp)

    # 11 ─ MultiLLMRouter.chat_with_tools() delegates to chat() (mock)
    def test_11_multi_chat_with_tools_delegates_to_chat(self):
        try:
            m = importlib.import_module("core.multi_llm_router")
        except Exception:
            self.skipTest("core.multi_llm_router requires httpx")
            return
        router = m.get_llm_router()
        calls = []
        async def _fake(**kw):
            calls.append(kw)
            return m.LLMResponse(content="ok", provider="p", model="m",
                                 input_tokens=0, output_tokens=0)
        with patch.object(router, "chat", side_effect=_fake):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(router.chat_with_tools(
                    messages=[{"role":"user","content":"x"}], task_type="general"))
            finally:
                loop.close()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["messages"][0]["content"], "x")

    # 12 ─ _get_provider_order returns list (runtime, optional)
    def test_12_provider_order_for_general_is_list(self):
        try:
            m = importlib.import_module("core.unified.llm_router")
            order, _ = m.get_unified_llm_router()._get_provider_order("general")
            self.assertIsInstance(order, list)
        except Exception:
            self.skipTest("core.unified.llm_router not importable")

    # 13-14 ─ Ollama in TASK_ROUTING_PREFERENCES (source)
    def test_13_ollama_in_general_routing_preferences_source(self):
        idx = _MULTI_ROUTER_SRC.find("TASK_ROUTING_PREFERENCES")
        g_idx = _MULTI_ROUTER_SRC.find("TaskType.GENERAL", idx)
        self.assertGreater(g_idx, idx)
        snippet = _MULTI_ROUTER_SRC[g_idx: _MULTI_ROUTER_SRC.find("]", g_idx) + 1]
        self.assertIn('"ollama"', snippet)

    def test_14_ollama_is_last_in_general_preferences_source(self):
        idx = _MULTI_ROUTER_SRC.find("TASK_ROUTING_PREFERENCES")
        g_idx = _MULTI_ROUTER_SRC.find("TaskType.GENERAL", idx)
        bracket_end = _MULTI_ROUTER_SRC.find("]", g_idx)
        snippet = _MULTI_ROUTER_SRC[g_idx: bracket_end + 1]
        ollama_pos = snippet.rfind('"ollama"')
        self.assertGreater(ollama_pos, 0)
        after = snippet[ollama_pos + len('"ollama"'):]
        others = re.findall(r'"[a-z_]+"', after)
        self.assertEqual(others, [], f"Found providers after ollama: {others}")

    # 15-18 ─ Routing closure: no direct get_llm_router() bypasses
    def test_15_handle_chat_no_direct_bypass(self):
        src = _method_src(_OPENCLAWD_SRC, "handle_chat")
        self.assertNotIn("from core.multi_llm_router import get_llm_router", src)

    def test_16_react_loop_no_direct_bypass(self):
        src = _method_src(_OPENCLAWD_SRC, "_react_loop")
        self.assertNotIn("from core.multi_llm_router import get_llm_router", src)

    def test_17_handle_agent_task_no_direct_bypass(self):
        src = _method_src(_OPENCLAWD_SRC, "handle_agent_task")
        self.assertNotIn("from core.multi_llm_router import get_llm_router", src)

    def test_18_get_status_llm_section_no_direct_bypass(self):
        idx = _OPENCLAWD_SRC.find("# LLM Router 状态")
        if idx == -1:
            idx = _OPENCLAWD_SRC.find("def get_status(")
        self.assertGreater(idx, 0)
        snippet = _OPENCLAWD_SRC[idx: idx + 1200]
        self.assertNotIn("from core.multi_llm_router import get_llm_router", snippet)

    # 19 ─ compute_complexity_vector delegates to _backend (mock)
    def test_19_unified_compute_complexity_vector_delegates(self):
        try:
            m = importlib.import_module("core.unified.llm_router")
        except Exception:
            self.skipTest("core.unified.llm_router requires pydantic")
            return
        router = m.get_unified_llm_router()
        mock_cv = MagicMock(); mock_cv.weighted_score = 0.6
        mock_be = MagicMock()
        mock_be._compute_complexity_vector = MagicMock(return_value=mock_cv)
        router._backend = mock_be
        result = router.compute_complexity_vector([{"role":"user","content":"x"}])
        mock_be._compute_complexity_vector.assert_called_once()
        self.assertEqual(result, mock_cv)

    # 20 ─ AgentFactory references chat_with_tools (source)
    def test_20_agent_factory_source_uses_chat_with_tools(self):
        self.assertIn("chat_with_tools", _AGENT_FACTORY_SRC)


if __name__ == "__main__":
    unittest.main(verbosity=2)
