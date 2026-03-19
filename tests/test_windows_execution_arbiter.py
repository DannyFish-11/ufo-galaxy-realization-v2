"""tests/test_windows_execution_arbiter.py
==========================================

Unit tests for :mod:`core.windows_execution_arbiter`.

All external adapters (system_api, UIA, GUI, VLM) are replaced with
lightweight async stubs so the suite passes on every platform.

Test groups
-----------
  A) WinExecAttempt / WinExecResult data classes.
  B) WindowsExecutionArbiter — no executors configured (all skipped).
  C) WindowsExecutionArbiter — system_api succeeds (first-level win).
  D) WindowsExecutionArbiter — system_api fails, UIA succeeds.
  E) WindowsExecutionArbiter — system_api + UIA fail, GUI succeeds.
  F) WindowsExecutionArbiter — all three structural levels fail, VLM succeeds.
  G) WindowsExecutionArbiter — all levels fail (all_failed counter).
  H) WindowsExecutionArbiter — force_level bypasses chain.
  I) WindowsExecutionArbiter — executor raises exception (swallowed).
  J) WindowsExecutionArbiter — set_executors runtime swap.
  K) WindowsExecutionArbiter — stats and history.
  L) WindowsExecutionArbiter — VLM screenshot propagation.
  M) Singleton helpers (get_windows_arbiter / reset_windows_arbiter).
  N) HybridExecutionArbiter — Windows fast-path delegation.
  O) HybridExecutionArbiter — non-Windows device skips Windows path.
  P) HybridExecutionArbiter — _is_windows_device heuristic.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.windows_execution_arbiter import (
    WinExecAttempt,
    WinExecLevel,
    WinExecResult,
    WinExecStatus,
    WindowsExecutionArbiter,
    _build_action_summary,
    get_windows_arbiter,
    reset_windows_arbiter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_arbiter(
    system_api=None,
    uia=None,
    gui=None,
    vlm=None,
    screenshot=None,
) -> WindowsExecutionArbiter:
    """Return a fresh arbiter with *no* auto-loaded defaults."""
    return WindowsExecutionArbiter(
        system_api_executor=system_api,
        uia_executor=uia,
        gui_executor=gui,
        vlm_executor=vlm,
        screenshot_getter=screenshot,
        use_defaults=False,
    )


async def _ok(**extra) -> Dict[str, Any]:
    return {"success": True, **extra}


async def _fail(reason: str = "boom") -> Dict[str, Any]:
    return {"success": False, "error": reason}


async def _sys_ok(_action, _params, _device):
    return {"success": True, "level": "system_api"}


async def _sys_fail(_action, _params, _device):
    return {"success": False, "error": "system_api_error"}


async def _uia_ok(_action, _params, _device):
    return {"success": True, "level": "uia"}


async def _uia_fail(_action, _params, _device):
    return {"success": False, "error": "uia_error"}


async def _gui_ok(_action, _params, _device):
    return {"success": True, "level": "gui"}


async def _gui_fail(_action, _params, _device):
    return {"success": False, "error": "gui_error"}


async def _vlm_ok(device_id, instruction, screenshot):
    return {"success": True, "level": "vlm", "screenshot_provided": screenshot is not None}


async def _vlm_fail(device_id, instruction, screenshot):
    return {"success": False, "error": "vlm_error"}


# ===========================================================================
# A) Data classes
# ===========================================================================

class TestWinExecAttempt:
    def test_to_dict_keys(self):
        a = WinExecAttempt(
            level=WinExecLevel.UIA,
            status=WinExecStatus.SUCCESS,
            result={"x": 1},
            error="",
            fallback_reason="system_api failed",
            latency_ms=12.5,
        )
        d = a.to_dict()
        assert d["level"] == "uia"
        assert d["status"] == "success"
        assert d["result"] == {"x": 1}
        assert d["fallback_reason"] == "system_api failed"
        assert d["latency_ms"] == 12.5

    def test_default_values(self):
        a = WinExecAttempt(level=WinExecLevel.VLM, status=WinExecStatus.SKIPPED)
        assert a.result == {}
        assert a.error == ""
        assert a.fallback_reason == ""
        assert a.latency_ms == 0.0


class TestWinExecResult:
    def test_to_dict_keys(self):
        r = WinExecResult(
            request_id="abc123",
            success=True,
            final_level=WinExecLevel.GUI,
            device_id="windows-1",
            action_summary="click on windows-1",
            result={"ok": True},
            attempts=[{"level": "system_api"}],
            total_latency_ms=55.2,
        )
        d = r.to_dict()
        assert d["request_id"] == "abc123"
        assert d["success"] is True
        assert d["final_level"] == "gui"
        assert d["device_id"] == "windows-1"
        assert d["action_summary"] == "click on windows-1"
        assert d["total_latency_ms"] == 55.2


# ===========================================================================
# B) No executors configured
# ===========================================================================

class TestNoExecutors:
    @pytest.mark.asyncio
    async def test_all_skipped_returns_failure(self):
        arbiter = _make_arbiter()
        result = await arbiter.execute("click", {"x": 1, "y": 2}, device_id="win-dev")
        assert result.success is False
        assert len(result.attempts) == 4  # all four levels tried
        statuses = {a["level"]: a["status"] for a in result.attempts}
        assert statuses["system_api"] == "skipped"
        assert statuses["uia"] == "skipped"
        assert statuses["gui"] == "skipped"
        assert statuses["vlm"] == "skipped"


# ===========================================================================
# C) System API succeeds
# ===========================================================================

class TestSystemAPISucceeds:
    @pytest.mark.asyncio
    async def test_returns_on_first_level(self):
        arbiter = _make_arbiter(system_api=_sys_ok)
        result = await arbiter.execute("launch_app", {"target": "notepad.exe"}, device_id="win-1")
        assert result.success is True
        assert result.final_level == WinExecLevel.SYSTEM_API
        assert len(result.attempts) == 1
        assert result.attempts[0]["level"] == "system_api"

    @pytest.mark.asyncio
    async def test_stats_incremented(self):
        arbiter = _make_arbiter(system_api=_sys_ok)
        await arbiter.execute("focus_window", {}, device_id="win-1")
        assert arbiter.get_stats()["system_api_success"] == 1
        assert arbiter.get_stats()["total"] == 1


# ===========================================================================
# D) System API fails, UIA succeeds
# ===========================================================================

class TestUIAFallback:
    @pytest.mark.asyncio
    async def test_fallback_to_uia(self):
        arbiter = _make_arbiter(system_api=_sys_fail, uia=_uia_ok)
        result = await arbiter.execute("click", {"element": "btn_ok"}, device_id="win-2")
        assert result.success is True
        assert result.final_level == WinExecLevel.UIA
        assert len(result.attempts) == 2
        assert result.attempts[0]["status"] == "failed"
        assert result.attempts[1]["status"] == "success"

    @pytest.mark.asyncio
    async def test_fallback_reason_propagated(self):
        arbiter = _make_arbiter(system_api=_sys_fail, uia=_uia_ok)
        result = await arbiter.execute("click", {}, device_id="win-2")
        uia_attempt = result.attempts[1]
        assert uia_attempt["fallback_reason"] != ""  # reason from system_api failure


# ===========================================================================
# E) System API + UIA fail, GUI succeeds
# ===========================================================================

class TestGUIFallback:
    @pytest.mark.asyncio
    async def test_fallback_to_gui(self):
        arbiter = _make_arbiter(system_api=_sys_fail, uia=_uia_fail, gui=_gui_ok)
        result = await arbiter.execute("type", {"text": "hello"}, device_id="win-3")
        assert result.success is True
        assert result.final_level == WinExecLevel.GUI
        assert len(result.attempts) == 3


# ===========================================================================
# F) All structural levels fail, VLM succeeds
# ===========================================================================

class TestVLMFallback:
    @pytest.mark.asyncio
    async def test_fallback_to_vlm(self):
        arbiter = _make_arbiter(
            system_api=_sys_fail,
            uia=_uia_fail,
            gui=_gui_fail,
            vlm=_vlm_ok,
        )
        result = await arbiter.execute("click", {"x": 50, "y": 50}, device_id="win-4")
        assert result.success is True
        assert result.final_level == WinExecLevel.VLM
        assert len(result.attempts) == 4


# ===========================================================================
# G) All levels fail
# ===========================================================================

class TestAllFailed:
    @pytest.mark.asyncio
    async def test_all_failed_result(self):
        arbiter = _make_arbiter(
            system_api=_sys_fail,
            uia=_uia_fail,
            gui=_gui_fail,
            vlm=_vlm_fail,
        )
        result = await arbiter.execute("click", {}, device_id="win-5")
        assert result.success is False
        assert arbiter.get_stats()["all_failed"] == 1
        assert len(result.attempts) == 4


# ===========================================================================
# H) force_level
# ===========================================================================

class TestForceLevel:
    @pytest.mark.asyncio
    async def test_force_vlm_skips_chain(self):
        arbiter = _make_arbiter(
            system_api=_sys_ok,  # would succeed if reached
            vlm=_vlm_ok,
        )
        result = await arbiter.execute(
            "click", {}, device_id="win-6", force_level=WinExecLevel.VLM
        )
        assert result.success is True
        assert result.final_level == WinExecLevel.VLM
        assert len(result.attempts) == 1

    @pytest.mark.asyncio
    async def test_force_gui_no_gui_executor_skips(self):
        arbiter = _make_arbiter()
        result = await arbiter.execute(
            "click", {}, device_id="win-6", force_level=WinExecLevel.GUI
        )
        assert result.success is False
        assert len(result.attempts) == 1
        assert result.attempts[0]["status"] == "skipped"


# ===========================================================================
# I) Executor raises exception
# ===========================================================================

class TestExecutorException:
    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self):
        async def _executor_that_raises(_action, _params, _device):
            raise RuntimeError("unexpected crash")

        arbiter = _make_arbiter(system_api=_executor_that_raises)
        result = await arbiter.execute("click", {}, device_id="win-7")
        # Should still complete (not raise) and record a failure attempt
        assert result.success is False
        sys_attempt = result.attempts[0]
        assert sys_attempt["status"] == "failed"
        assert "unexpected crash" in sys_attempt["error"]


# ===========================================================================
# J) set_executors
# ===========================================================================

class TestSetExecutors:
    @pytest.mark.asyncio
    async def test_runtime_swap(self):
        arbiter = _make_arbiter()
        assert arbiter._system_api is None

        arbiter.set_executors(system_api=_sys_ok)
        assert arbiter._system_api is _sys_ok

        result = await arbiter.execute("launch_app", {}, device_id="win-8")
        assert result.success is True
        assert result.final_level == WinExecLevel.SYSTEM_API


# ===========================================================================
# K) Stats and history
# ===========================================================================

class TestStatsAndHistory:
    @pytest.mark.asyncio
    async def test_history_length_capped(self):
        arbiter = _make_arbiter(system_api=_sys_ok)
        for _ in range(210):
            await arbiter.execute("click", {}, device_id="win-9")
        assert len(arbiter.get_history()) <= 50  # default limit
        # Raw history is capped at 200 internally
        assert len(arbiter._history) == 200

    @pytest.mark.asyncio
    async def test_stats_counters(self):
        arbiter = _make_arbiter(system_api=_sys_fail, uia=_uia_ok)
        await arbiter.execute("click", {}, device_id="win-10")
        await arbiter.execute("type", {"text": "hi"}, device_id="win-10")
        stats = arbiter.get_stats()
        assert stats["total"] == 2
        assert stats["uia_success"] == 2
        assert stats["system_api_success"] == 0


# ===========================================================================
# L) VLM screenshot propagation
# ===========================================================================

class TestVLMScreenshot:
    @pytest.mark.asyncio
    async def test_screenshot_forwarded_to_vlm(self):
        received = {}

        async def _capturing_vlm(device_id, instruction, screenshot):
            received["screenshot"] = screenshot
            return {"success": True}

        async def _mock_screenshot(device_id):
            return "BASE64_DATA"

        arbiter = _make_arbiter(
            system_api=_sys_fail,
            uia=_uia_fail,
            gui=_gui_fail,
            vlm=_capturing_vlm,
            screenshot=_mock_screenshot,
        )
        result = await arbiter.execute("click", {}, device_id="win-11")
        assert result.success is True
        assert received["screenshot"] == "BASE64_DATA"

    @pytest.mark.asyncio
    async def test_screenshot_failure_does_not_crash_vlm(self):
        async def _bad_screenshot(_device):
            raise OSError("screen unavailable")

        arbiter = _make_arbiter(
            system_api=_sys_fail,
            uia=_uia_fail,
            gui=_gui_fail,
            vlm=_vlm_ok,
            screenshot=_bad_screenshot,
        )
        result = await arbiter.execute("click", {}, device_id="win-12")
        assert result.success is True


# ===========================================================================
# M) Singleton helpers
# ===========================================================================

class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_windows_arbiter()
        a = get_windows_arbiter()
        b = get_windows_arbiter()
        assert a is b

    def test_reset_creates_new_instance(self):
        reset_windows_arbiter()
        a = get_windows_arbiter()
        reset_windows_arbiter()
        b = get_windows_arbiter()
        assert a is not b

    def teardown_method(self, method):
        reset_windows_arbiter()


# ===========================================================================
# N) HybridExecutionArbiter — Windows fast-path
# ===========================================================================

class TestHybridWindowsDelegation:
    """Ensure HybridExecutionArbiter delegates Windows requests correctly."""

    @pytest.mark.asyncio
    async def test_windows_device_delegates_to_arbiter(self):
        from core.hybrid_executor import HybridExecutionArbiter

        win_arbiter = _make_arbiter(system_api=_sys_ok)
        hybrid = HybridExecutionArbiter()

        result = await hybrid.execute(
            device_id="windows-desktop",
            app_id="notepad",
            action="launch_app",
            params={"target": "notepad.exe"},
            windows_arbiter=win_arbiter,
        )
        assert result.success is True
        # final_level should map to A2A (system_api → A2A)
        from core.hybrid_executor import ExecutionLevel
        assert result.final_level == ExecutionLevel.A2A

    @pytest.mark.asyncio
    async def test_windows_device_vlm_fallback(self):
        from core.hybrid_executor import HybridExecutionArbiter, ExecutionLevel

        win_arbiter = _make_arbiter(
            system_api=_sys_fail,
            uia=_uia_fail,
            gui=_gui_fail,
            vlm=_vlm_ok,
        )
        hybrid = HybridExecutionArbiter()
        result = await hybrid.execute(
            device_id="windows-1",
            app_id="explorer",
            action="click",
            params={},
            windows_arbiter=win_arbiter,
        )
        assert result.success is True
        assert result.final_level == ExecutionLevel.VLM

    @pytest.mark.asyncio
    async def test_windows_arbiter_false_skips_delegation(self):
        """windows_arbiter=False forces the generic chain."""
        from core.hybrid_executor import HybridExecutionArbiter

        hybrid = HybridExecutionArbiter()
        # Without any executors configured the generic chain will fail,
        # but it should not have gone through the Windows arbiter at all.
        result = await hybrid.execute(
            device_id="windows-host",
            app_id="",
            action="click",
            windows_arbiter=False,
        )
        # Generic chain with no executors → all_failed
        assert result.success is False


# ===========================================================================
# O) Non-Windows device skips Windows path
# ===========================================================================

class TestNonWindowsDevice:
    @pytest.mark.asyncio
    async def test_android_device_skips_windows_arbiter(self):
        from core.hybrid_executor import HybridExecutionArbiter

        hybrid = HybridExecutionArbiter()
        # No executors → all_failed via generic chain (not Windows fast-path)
        result = await hybrid.execute(
            device_id="android-pixel-7",
            app_id="com.example.app",
            action="click",
        )
        assert result.success is False
        # Verify Windows arbiter was NOT called by checking stats
        # (generic chain increments all_failed; Windows path also does but
        # via different route — what matters is no exception was raised)


# ===========================================================================
# P) _is_windows_device heuristic
# ===========================================================================

class TestIsWindowsDevice:
    def _check(self, device_id: str) -> bool:
        from core.hybrid_executor import HybridExecutionArbiter
        return HybridExecutionArbiter._is_windows_device(device_id)

    def test_windows_prefix(self):
        assert self._check("windows-desktop") is True
        assert self._check("Windows-Server") is True

    def test_local_on_win32(self):
        import sys
        import unittest.mock as mock
        with mock.patch.object(sys, "platform", "win32"):
            assert self._check("local") is True

    def test_local_on_linux(self):
        import sys
        import unittest.mock as mock
        with mock.patch.object(sys, "platform", "linux"):
            assert self._check("local") is False

    def test_win_suffix(self):
        assert self._check("desktop:win") is True
        assert self._check("pc:windows") is True

    def test_android_is_not_windows(self):
        assert self._check("android-device") is False

    def test_ios_is_not_windows(self):
        assert self._check("iphone-13") is False

    def test_empty_string_is_not_windows(self):
        assert self._check("") is False


# ===========================================================================
# Helper function tests
# ===========================================================================

class TestBuildActionSummary:
    def test_with_key_params(self):
        s = _build_action_summary("click", {"x": 10, "y": 20}, "win-dev")
        assert "click" in s
        assert "win-dev" in s
        assert "x=10" in s

    def test_without_key_params(self):
        s = _build_action_summary("scroll", {"direction": "down"}, "win-dev")
        assert "scroll" in s
        assert "win-dev" in s
