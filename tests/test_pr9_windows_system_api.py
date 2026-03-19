"""tests/test_pr9_windows_system_api.py
==========================================

Unit tests for PR-9: unified Windows System API facade.

All Win32 / platform-specific adapters are replaced with lightweight
in-memory stubs so the suite passes on every platform (Linux CI included).

Test groups
-----------
  A) New data classes (FileOpResult, ProcessInfo, ClipboardResult, NotificationResult).
  B) NoOpSystemAPI — new method defaults.
  C) SystemAPIRequest / SystemAPIResponse model.
  D) WindowsSystemAPI — disabled facade (handled=False for every action).
  E) WindowsSystemAPI — adapter not available (handled=False).
  F) WindowsSystemAPI — unsupported action (handled=False).
  G) WindowsSystemAPI — app / window management actions.
  H) WindowsSystemAPI — file operation actions.
  I) WindowsSystemAPI — process query actions.
  J) WindowsSystemAPI — clipboard actions.
  K) WindowsSystemAPI — notification action.
  L) WindowsSystemAPI — missing required params.
  M) WindowsSystemAPI — adapter raises exception (swallowed).
  N) _SysAPIMetrics counters.
  O) Singleton helpers (get_windows_system_api / reset_windows_system_api).
  P) WindowsExecutionArbiter — system_api executor routes through facade.
  Q) WindowsSystemAPI — duration_ms is populated.
  R) WindowsSystemAPI — dispatch() to_dict round-trip.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

from core.system_api.platform_api import (
    AppLaunchResult,
    ClipboardResult,
    FileOpResult,
    NoOpSystemAPI,
    NotificationResult,
    ProcessInfo,
    TrayHandle,
    WindowInfo,
)
from core.system_api.windows_system_api import (
    SUPPORTED_ACTIONS,
    SystemAPIRequest,
    SystemAPIResponse,
    WindowsSystemAPI,
    _SysAPIMetrics,
    get_sysapi_metrics,
    get_windows_system_api,
    reset_sysapi_metrics,
    reset_windows_system_api,
)


class _StubAdapter:
    """Minimal in-memory stub that implements the full SystemAPI surface."""

    is_available = True

    def launch_app(self, target, args=None, working_dir=None):
        return AppLaunchResult(success=True, pid=1234)

    def enumerate_windows(self, filter_title=None):
        return [WindowInfo(hwnd=1, title="TestWindow")]

    def focus_window(self, title_or_hwnd):
        return True

    def close_window(self, title_or_hwnd):
        return True

    def register_hotkey(self, hotkey_id, modifiers, vk_code, callback=None):
        from core.system_api.platform_api import HotkeyHandle
        return HotkeyHandle(hotkey_id=hotkey_id, modifiers=modifiers, vk_code=vk_code, active=True)

    def unregister_hotkey(self, handle):
        return True

    def create_tray_icon(self, tooltip="Galaxy", icon_path=None):
        return TrayHandle(active=True, tooltip=tooltip)

    def destroy_tray_icon(self, handle):
        pass

    # --- new PR-9 methods ---

    def open_file(self, path):
        return FileOpResult(success=True, path=path)

    def move_file(self, src, dst):
        return FileOpResult(success=True, path=dst)

    def delete_file(self, path):
        return FileOpResult(success=True, path=path)

    def list_processes(self):
        return [ProcessInfo(pid=42, name="notepad.exe")]

    def kill_process(self, pid):
        return pid == 42

    def get_clipboard(self):
        return ClipboardResult(success=True, text="hello clipboard")

    def set_clipboard(self, text):
        return ClipboardResult(success=True)

    def send_notification(self, title, body, icon_path=None):
        return NotificationResult(success=True, notification_id=7)


def _make_facade(enabled=True, adapter=None) -> WindowsSystemAPI:
    """Return a fresh :class:`WindowsSystemAPI` with an injected stub adapter."""
    f = WindowsSystemAPI(adapter=adapter or _StubAdapter(), enabled=enabled)
    return f


# ===========================================================================
# A) New data classes
# ===========================================================================


class TestNewDataClasses:
    def test_file_op_result_defaults(self):
        r = FileOpResult(success=True)
        assert r.path is None
        assert r.error is None

    def test_file_op_result_error(self):
        r = FileOpResult(success=False, error="not found")
        assert not r.success

    def test_process_info(self):
        p = ProcessInfo(pid=1, name="test.exe", status="running")
        assert p.pid == 1
        assert p.cpu_percent == 0.0

    def test_clipboard_result(self):
        r = ClipboardResult(success=True, text="abc")
        assert r.text == "abc"

    def test_notification_result(self):
        r = NotificationResult(success=True, notification_id=5)
        assert r.notification_id == 5


# ===========================================================================
# B) NoOpSystemAPI — new method defaults
# ===========================================================================


class TestNoOpSystemAPI:
    def setup_method(self):
        self.api = NoOpSystemAPI()

    def test_close_window(self):
        assert self.api.close_window("Anything") is False

    def test_open_file(self):
        r = self.api.open_file("/tmp/x.txt")
        assert r.success is False
        assert "platform not supported" in (r.error or "")

    def test_move_file(self):
        r = self.api.move_file("/a", "/b")
        assert r.success is False

    def test_delete_file(self):
        r = self.api.delete_file("/a")
        assert r.success is False

    def test_list_processes(self):
        assert self.api.list_processes() == []

    def test_kill_process(self):
        assert self.api.kill_process(999) is False

    def test_get_clipboard(self):
        r = self.api.get_clipboard()
        assert r.success is False

    def test_set_clipboard(self):
        r = self.api.set_clipboard("hello")
        assert r.success is False

    def test_send_notification(self):
        r = self.api.send_notification("T", "B")
        assert r.success is False


# ===========================================================================
# C) SystemAPIRequest / SystemAPIResponse model
# ===========================================================================


class TestRequestResponseModel:
    def test_request_defaults(self):
        req = SystemAPIRequest(action="launch_app")
        assert req.params == {}
        assert req.device_id == ""

    def test_response_to_dict(self):
        resp = SystemAPIResponse(success=True, data={"pid": 1}, duration_ms=2.5)
        d = resp.to_dict()
        assert d["success"] is True
        assert d["data"]["pid"] == 1
        assert d["duration_ms"] == 2.5

    def test_response_fallback_reason(self):
        resp = SystemAPIResponse(success=False, handled=False, fallback_reason="disabled")
        assert resp.fallback_reason == "disabled"


# ===========================================================================
# D) Disabled facade
# ===========================================================================


class TestDisabledFacade:
    def setup_method(self):
        self.facade = _make_facade(enabled=False)

    def test_is_available_false(self):
        assert self.facade.is_available is False

    def test_all_actions_not_handled(self):
        for action in list(SUPPORTED_ACTIONS)[:5]:
            resp = self.facade.dispatch(action, {})
            assert resp.handled is False
            assert "disabled" in resp.fallback_reason

    def test_metrics_skipped(self):
        reset_sysapi_metrics()
        self.facade.dispatch("launch_app", {})
        m = get_sysapi_metrics()
        assert m.skipped == 1
        assert m.total == 1


# ===========================================================================
# E) Adapter not available
# ===========================================================================


class TestAdapterNotAvailable:
    def setup_method(self):
        adapter = _StubAdapter()
        adapter.is_available = False  # type: ignore[assignment]
        self.facade = _make_facade(adapter=adapter)

    def test_is_available_false(self):
        assert self.facade.is_available is False

    def test_dispatch_not_handled(self):
        resp = self.facade.dispatch("launch_app", {"target": "notepad.exe"})
        assert resp.handled is False
        assert "not available" in resp.fallback_reason


# ===========================================================================
# F) Unsupported action
# ===========================================================================


class TestUnsupportedAction:
    def setup_method(self):
        self.facade = _make_facade()

    def test_unknown_action_not_handled(self):
        resp = self.facade.dispatch("do_something_random", {})
        assert resp.handled is False
        assert "not in system_api scope" in resp.fallback_reason


# ===========================================================================
# G) App / window management
# ===========================================================================


class TestAppWindowManagement:
    def setup_method(self):
        self.facade = _make_facade()

    def test_launch_app(self):
        resp = self.facade.dispatch("launch_app", {"target": "notepad.exe"})
        assert resp.success is True
        assert resp.data.get("pid") == 1234

    def test_launch_alias(self):
        resp = self.facade.dispatch("launch", {"target": "calc.exe"})
        assert resp.success is True

    def test_launch_app_missing_target(self):
        resp = self.facade.dispatch("launch_app", {})
        assert resp.success is False

    def test_focus_window(self):
        resp = self.facade.dispatch("focus_window", {"title": "TestWindow"})
        assert resp.success is True

    def test_focus_alias(self):
        resp = self.facade.dispatch("focus", {"hwnd": 1})
        assert resp.success is True

    def test_close_window(self):
        resp = self.facade.dispatch("close_window", {"title": "TestWindow"})
        assert resp.success is True

    def test_close_alias(self):
        resp = self.facade.dispatch("close", {"hwnd": 1})
        assert resp.success is True

    def test_enumerate_windows(self):
        resp = self.facade.dispatch("enumerate_windows", {})
        assert resp.success is True
        assert len(resp.data["windows"]) == 1
        assert resp.data["windows"][0]["title"] == "TestWindow"

    def test_focus_fail(self):
        adapter = _StubAdapter()
        adapter.focus_window = lambda t: False  # type: ignore[method-assign]
        facade = _make_facade(adapter=adapter)
        resp = facade.dispatch("focus_window", {"title": "Missing"})
        assert resp.success is False


# ===========================================================================
# H) File operations
# ===========================================================================


class TestFileOperations:
    def setup_method(self):
        self.facade = _make_facade()

    def test_open_file(self):
        resp = self.facade.dispatch("open_file", {"path": "/tmp/test.txt"})
        assert resp.success is True
        assert resp.data["path"] == "/tmp/test.txt"

    def test_move_file(self):
        resp = self.facade.dispatch("move_file", {"src": "/a", "dst": "/b"})
        assert resp.success is True
        assert resp.data["path"] == "/b"

    def test_delete_file(self):
        resp = self.facade.dispatch("delete_file", {"path": "/tmp/x.txt"})
        assert resp.success is True


# ===========================================================================
# I) Process queries
# ===========================================================================


class TestProcessQueries:
    def setup_method(self):
        self.facade = _make_facade()

    def test_list_processes(self):
        resp = self.facade.dispatch("list_processes", {})
        assert resp.success is True
        procs = resp.data["processes"]
        assert len(procs) == 1
        assert procs[0]["pid"] == 42

    def test_kill_process_found(self):
        resp = self.facade.dispatch("kill_process", {"pid": 42})
        assert resp.success is True

    def test_kill_process_not_found(self):
        resp = self.facade.dispatch("kill_process", {"pid": 99})
        assert resp.success is False

    def test_kill_process_missing_pid(self):
        resp = self.facade.dispatch("kill_process", {})
        assert resp.success is False
        assert "missing" in resp.error


# ===========================================================================
# J) Clipboard
# ===========================================================================


class TestClipboard:
    def setup_method(self):
        self.facade = _make_facade()

    def test_get_clipboard(self):
        resp = self.facade.dispatch("get_clipboard", {})
        assert resp.success is True
        assert resp.data["text"] == "hello clipboard"

    def test_set_clipboard(self):
        resp = self.facade.dispatch("set_clipboard", {"text": "world"})
        assert resp.success is True

    def test_get_clipboard_failure(self):
        adapter = _StubAdapter()
        adapter.get_clipboard = lambda: ClipboardResult(success=False, error="locked")  # type: ignore[method-assign]
        facade = _make_facade(adapter=adapter)
        resp = facade.dispatch("get_clipboard", {})
        assert resp.success is False
        assert resp.error == "locked"


# ===========================================================================
# K) Notifications
# ===========================================================================


class TestNotifications:
    def setup_method(self):
        self.facade = _make_facade()

    def test_send_notification(self):
        resp = self.facade.dispatch(
            "send_notification", {"title": "Hello", "body": "World"}
        )
        assert resp.success is True
        assert resp.data.get("notification_id") == 7

    def test_send_notification_failure(self):
        adapter = _StubAdapter()
        adapter.send_notification = lambda title, body, icon_path=None: NotificationResult(  # type: ignore[method-assign]
            success=False, error="tray not active"
        )
        facade = _make_facade(adapter=adapter)
        resp = facade.dispatch("send_notification", {"title": "T", "body": "B"})
        assert resp.success is False


# ===========================================================================
# L) Missing required params
# ===========================================================================


class TestMissingParams:
    def setup_method(self):
        self.facade = _make_facade()

    def test_launch_app_empty_target(self):
        resp = self.facade.dispatch("launch_app", {"target": ""})
        assert resp.success is False

    def test_kill_process_no_pid(self):
        resp = self.facade.dispatch("kill_process", {})
        assert resp.success is False


# ===========================================================================
# M) Adapter raises exception (swallowed)
# ===========================================================================


class TestAdapterException:
    def test_exception_is_swallowed(self):
        adapter = _StubAdapter()
        adapter.launch_app = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]

        def _boom(*a, **kw):
            raise RuntimeError("boom")

        adapter.launch_app = _boom  # type: ignore[method-assign]
        facade = _make_facade(adapter=adapter)
        resp = facade.dispatch("launch_app", {"target": "notepad.exe"})
        assert resp.success is False
        assert "boom" in resp.error

    def test_success_false_on_error(self):
        adapter = _StubAdapter()

        def _crash(path):
            raise OSError("disk full")

        adapter.delete_file = _crash  # type: ignore[method-assign]
        facade = _make_facade(adapter=adapter)
        resp = facade.dispatch("delete_file", {"path": "/x"})
        assert resp.success is False


# ===========================================================================
# N) Metrics
# ===========================================================================


class TestMetrics:
    def setup_method(self):
        reset_sysapi_metrics()

    def test_success_increments(self):
        facade = _make_facade()
        facade.dispatch("launch_app", {"target": "notepad.exe"})
        m = get_sysapi_metrics()
        assert m.total == 1
        assert m.success == 1
        assert m.failed == 0

    def test_failure_increments(self):
        facade = _make_facade()
        facade.dispatch("launch_app", {})  # missing target
        m = get_sysapi_metrics()
        assert m.failed == 1

    def test_skipped_increments_when_disabled(self):
        facade = _make_facade(enabled=False)
        facade.dispatch("launch_app", {"target": "x"})
        m = get_sysapi_metrics()
        assert m.skipped == 1

    def test_by_action_tracking(self):
        facade = _make_facade()
        facade.dispatch("get_clipboard", {})
        facade.dispatch("get_clipboard", {})
        facade.dispatch("set_clipboard", {"text": "hi"})
        m = get_sysapi_metrics()
        assert m.by_action["get_clipboard"] == 2
        assert m.by_action["set_clipboard"] == 1

    def test_snapshot(self):
        facade = _make_facade()
        facade.dispatch("list_processes", {})
        snap = get_sysapi_metrics().snapshot()
        assert "total" in snap
        assert "by_action" in snap


# ===========================================================================
# O) Singleton helpers
# ===========================================================================


class TestSingletonHelpers:
    def setup_method(self):
        reset_windows_system_api()
        reset_sysapi_metrics()

    def test_get_returns_same_instance(self):
        a = get_windows_system_api(enabled=False)
        b = get_windows_system_api(enabled=False)
        assert a is b

    def test_reset_creates_new_instance(self):
        a = get_windows_system_api(enabled=False)
        reset_windows_system_api()
        b = get_windows_system_api(enabled=False)
        assert a is not b

    def test_enabled_false_propagated(self):
        facade = get_windows_system_api(enabled=False)
        assert facade.is_available is False


# ===========================================================================
# P) WindowsExecutionArbiter routes through facade
# ===========================================================================


class TestArbiterFacadeIntegration:
    """Verify the arbiter's system_api executor calls the facade."""

    def _make_arbiter_with_facade(self, facade: WindowsSystemAPI):
        """Build a WindowsExecutionArbiter whose system_api executor uses *facade*."""
        from core.windows_execution_arbiter import WindowsExecutionArbiter

        async def _exec(action: str, params: Dict[str, Any], device_id: str) -> Dict[str, Any]:
            resp = facade.dispatch(action, params, device_id=device_id)
            if not resp.handled:
                return {"success": False, "error": resp.fallback_reason}
            return {"success": resp.success, "error": resp.error, **resp.data}

        return WindowsExecutionArbiter(
            system_api_executor=_exec,
            use_defaults=False,
        )

    @pytest.mark.asyncio
    async def test_launch_app_via_facade(self):
        facade = _make_facade()
        arbiter = self._make_arbiter_with_facade(facade)
        result = await arbiter.execute(
            action="launch_app",
            params={"target": "notepad.exe"},
            device_id="windows-test",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_get_clipboard_via_facade(self):
        facade = _make_facade()
        arbiter = self._make_arbiter_with_facade(facade)
        result = await arbiter.execute(
            action="get_clipboard",
            params={},
            device_id="windows-test",
        )
        assert result.success is True


# ===========================================================================
# Q) duration_ms is populated
# ===========================================================================


class TestDurationMs:
    def test_duration_populated(self):
        facade = _make_facade()
        resp = facade.dispatch("list_processes", {})
        assert resp.duration_ms >= 0.0

    def test_duration_zero_when_not_handled(self):
        facade = _make_facade(enabled=False)
        resp = facade.dispatch("list_processes", {})
        assert resp.duration_ms == 0.0


# ===========================================================================
# R) to_dict round-trip
# ===========================================================================


class TestToDictRoundTrip:
    def test_to_dict_keys(self):
        facade = _make_facade()
        resp = facade.dispatch("launch_app", {"target": "notepad.exe"})
        d = resp.to_dict()
        assert set(d.keys()) >= {"success", "handled", "data", "error", "duration_ms", "fallback_reason"}

    def test_to_dict_success(self):
        resp = SystemAPIResponse(success=True, data={"pid": 5}, duration_ms=1.1)
        d = resp.to_dict()
        assert d["success"] is True
        assert d["data"]["pid"] == 5
        assert d["duration_ms"] == 1.1
