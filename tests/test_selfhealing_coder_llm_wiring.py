"""tests/test_selfhealing_coder_llm_wiring.py
================================================

AutonomousCoder's generate→execute→feed-errors-back→regenerate loop is only a
real closed loop if an LLM client is wired in. The single production call site
(Node_112_SelfHealing's AutoFixer._code_fix) used to construct
``AutonomousCoder()`` bare, so ``llm_client`` was None:

- ``_optimize_code`` short-circuited (``if not self.llm_client: return code``)
  — the "fix based on the error" step silently returned the code unchanged;
- ``_generate_code_with_llm`` fell back to a static template.

The iteration loop still spun 3 times, but nothing ever learned from the
captured stderr. These tests prove the wiring end-to-end.
"""
from __future__ import annotations

import asyncio
from typing import Dict, List
from unittest.mock import patch

from enhancements.reasoning.autonomous_coder import (
    AutonomousCoder,
    CodingTask,
    GalaxyRouterClient,
    LLMClient,
)


class _RecordingClient(LLMClient):
    """按 prompt 内容分流,贴合 AutonomousCoder 的真实调用序列:
    需求分析(要 JSON)→ 初始生成(给坏代码)→ 基于报错的优化(给修复版)。"""

    def __init__(self) -> None:
        self.generate_prompts: List[str] = []
        self.optimize_prompts: List[str] = []

    def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        self.generate_prompts.append(prompt)
        if "错误信息" in prompt:
            # _optimize_code 的修复调用:必须带着真实运行报错
            self.optimize_prompts.append(prompt)
            return "```python\nprint('fixed ok')\n```"
        if "请根据以下需求生成" in prompt or "只返回代码" in prompt:
            # 初始代码生成:故意给必炸的坏代码,错误文本可辨识
            return "```python\nraise RuntimeError('BOOM_MARKER')\n```"
        # 需求分析调用(期待 JSON)
        return "{}"

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        return ""


class TestSelfHealingCoderLLMWiring:
    def test_error_text_is_fed_back_to_llm_and_fix_is_applied(self):
        client = _RecordingClient()
        coder = AutonomousCoder(llm_client=client)
        task = CodingTask(
            requirement="print something",
            language="python",
            target_type="fix",
            constraints=[],
            expected_output=None,
            context_code=None,
        )
        result = coder.generate_and_execute(task)

        # 优化调用必须发生,且 prompt 携带真实运行报错(闭环的"喂报错"一步)
        assert client.optimize_prompts, (
            "从未走到 _optimize_code 的 LLM 修复调用 — 闭环断了",
            client.generate_prompts,
        )
        assert "BOOM_MARKER" in client.optimize_prompts[0]
        # 修复版真的被执行并通过
        assert result.success, result.errors
        assert "fixed ok" in (result.test_output or "")
        assert result.iterations >= 2

    def test_node112_code_fix_wires_a_real_llm_client(self):
        """Node_112 的 _code_fix 必须以非 None 的 llm_client 构造 AutonomousCoder。"""
        import nodes.Node_112_SelfHealing.main as n112

        captured = {}
        real_init = AutonomousCoder.__init__

        def spy_init(self, llm_client=None, use_docker=False):
            captured["llm_client"] = llm_client
            real_init(self, llm_client=llm_client, use_docker=use_docker)

        fixer = n112.AutoFixer()
        diagnosis = n112.DiagnosisResult(
            issue_type=n112.IssueType.UNKNOWN,
            severity=n112.HealthStatus.CRITICAL,
            description="test",
            affected_components=[],
            recommendation="写一个修复脚本 print hello",
        )
        with patch.object(AutonomousCoder, "__init__", spy_init), \
             patch.object(AutonomousCoder, "generate_and_execute",
                          return_value=None):
            fixer._code_fix(diagnosis)

        assert captured.get("llm_client") is not None, (
            "Node_112 _code_fix 仍在裸构造 AutonomousCoder()——自愈闭环的 LLM 修复步会静默失效"
        )
        assert isinstance(captured["llm_client"], GalaxyRouterClient)

    def test_router_client_bridges_async_router_sync(self):
        """GalaxyRouterClient 在无事件循环的线程里能同步调用异步路由。"""

        class _FakeResp:
            content = "hello from router"

        class _FakeRouter:
            async def chat(self, messages, temperature=0.7, max_tokens=4096, **kw):
                await asyncio.sleep(0)
                return _FakeResp()

        client = GalaxyRouterClient()
        client._router = _FakeRouter()
        assert client.generate("hi") == "hello from router"
        assert client.chat([{"role": "user", "content": "hi"}]) == "hello from router"
