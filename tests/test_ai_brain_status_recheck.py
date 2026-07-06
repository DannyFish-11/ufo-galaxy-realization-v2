"""tests/test_ai_brain_status_recheck.py
==========================================

The "AI 大脑" summary-card entry was computed once, immediately after
select_and_start_brain() returned - but background_pull() (a deliberately
non-blocking daemon thread) and even Ollama's own service startup could
still be in progress at that exact moment. A real machine run showed the
final summary still printing "AI 大脑 → 未安装(拉取失败/未完成)" even
though the model had, moments later, actually finished pulling
successfully ("✓ 本地主脑模型已就绪" was printed right above it) - the
displayed status was a stale snapshot, not the true state.

_recheck_ai_brain_phase() re-probes Ollama right before the summary card
is printed (by which point node startup, L4 modules, Electron, tray, and
voice interaction have all also run, giving the background pull much
more time to finish) and corrects the phases_state entry in place if
the real state has improved.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from unified_launcher import _recheck_ai_brain_phase


def _make_brain(healthy: bool, available_models: list, ping_result: bool = None):
    brain = SimpleNamespace()
    brain._healthy = healthy
    brain.available_models = available_models
    brain.brain_model = "gemma4:e2b"
    brain._ping_ollama = AsyncMock(return_value=ping_result if ping_result is not None else healthy)
    brain._refresh_model_list = AsyncMock()
    return brain


class TestAiBrainStatusRecheck:
    def test_upgrades_warn_to_ok_when_model_now_installed(self):
        """Exactly the real-machine scenario: was unhealthy/uninstalled at
        snapshot time, but Ollama + the model are actually ready by the time
        we recheck."""
        brain = _make_brain(healthy=False, available_models=[], ping_result=True)

        async def refresh():
            brain.available_models = ["gemma4:e2b"]
        brain._refresh_model_list.side_effect = refresh

        phases_state = [("AI 大脑", "warn", "未安装(拉取失败/未完成)")]
        asyncio.run(_recheck_ai_brain_phase(brain, phases_state, 0))

        name, status, hint = phases_state[0]
        assert status == "ok", phases_state
        assert hint is None
        brain._ping_ollama.assert_awaited()
        brain._refresh_model_list.assert_awaited()

    def test_leaves_ok_status_alone(self):
        """Already 'ok' at snapshot time - must not be touched (and shouldn't
        even bother re-probing, since there's nothing to correct)."""
        brain = _make_brain(healthy=True, available_models=["gemma4:e2b"])
        phases_state = [("AI 大脑", "ok", None)]
        asyncio.run(_recheck_ai_brain_phase(brain, phases_state, 0))
        assert phases_state[0] == ("AI 大脑", "ok", None)

    def test_leaves_warn_alone_when_still_genuinely_not_ready(self):
        """If the recheck confirms the same negative result, don't fabricate
        an improvement that isn't real."""
        brain = _make_brain(healthy=False, available_models=[], ping_result=False)
        phases_state = [("AI 大脑", "warn", "未安装(拉取失败/未完成)—— 已配置云端 API Key 可兜底")]
        # "warn" (rather than "fail") requires a configured cloud fallback key.
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("OPENAI_API_KEY", "sk-real-test-key")
            asyncio.run(_recheck_ai_brain_phase(brain, phases_state, 0))
        name, status, hint = phases_state[0]
        assert status == "warn"
        assert hint is not None

    def test_no_brain_is_a_safe_noop(self):
        phases_state = [("AI 大脑", "fail", "启动失败")]
        asyncio.run(_recheck_ai_brain_phase(None, phases_state, 0))
        assert phases_state[0] == ("AI 大脑", "fail", "启动失败")

    def test_out_of_range_index_is_a_safe_noop(self):
        brain = _make_brain(healthy=True, available_models=["gemma4:e2b"])
        phases_state = [("其他阶段", "ok", None)]
        asyncio.run(_recheck_ai_brain_phase(brain, phases_state, 5))
        assert phases_state == [("其他阶段", "ok", None)]

    def test_probe_exception_is_swallowed_non_fatal(self):
        brain = _make_brain(healthy=False, available_models=[])
        brain._ping_ollama.side_effect = RuntimeError("network boom")
        phases_state = [("AI 大脑", "warn", "未安装(拉取失败/未完成)")]
        # Must not raise.
        asyncio.run(_recheck_ai_brain_phase(brain, phases_state, 0))
        assert phases_state[0][1] == "warn"
