"""Tests for the Windows system API adapter (PR-7).

All Win32 calls are mocked so these tests pass on any platform.
Platform-specific branches are exercised via monkeypatching.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Callable, List, Optional
from unittest.mock import MagicMock, call, patch

import pytest

from core.system_api.platform_api import (
    AppLaunchResult,
    HotkeyHandle,
    NoOpSystemAPI,
    TrayHandle,
    WindowInfo,
)
from core.system_api import get_system_api, reset_system_api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_windows_adapter():
    """Return a WindowsAdapter with Win32 calls mocked out."""
    from core.system_api.windows_adapter import WindowsAdapter
    import core.system_api.windows_adapter as mod

    adapter = WindowsAdapter.__new__(WindowsAdapter)
    adapter.__init__()
    return adapter, mod


# ===========================================================================
# NoOpSystemAPI
# ===========================================================================

class TestNoOpSystemAPI:
    def test_is_available_false(self):
        api = NoOpSystemAPI()
        assert api.is_available is False

    def test_launch_app_returns_failure(self):
        api = NoOpSystemAPI()
        result = api.launch_app("notepad.exe")
        assert isinstance(result, AppLaunchResult)
        assert result.success is False

    def test_enumerate_windows_empty(self):
        api = NoOpSystemAPI()
        windows = api.enumerate_windows()
        assert windows == []

    def test_focus_window_false(self):
        api = NoOpSystemAPI()
        assert api.focus_window("anything") is False

    def test_register_hotkey_inactive_handle(self):
        api = NoOpSystemAPI()
        h = api.register_hotkey(1, 0x2, 0x41)
        assert isinstance(h, HotkeyHandle)
        assert h.active is False
        assert h.hotkey_id == 1

    def test_unregister_hotkey_false(self):
        api = NoOpSystemAPI()
        h = HotkeyHandle(hotkey_id=1, modifiers=0, vk_code=0x41, active=True)
        assert api.unregister_hotkey(h) is False

    def test_create_tray_icon_inactive(self):
        api = NoOpSystemAPI()
        handle = api.create_tray_icon("Galaxy")
        assert isinstance(handle, TrayHandle)
        assert handle.active is False
        assert handle.tooltip == "Galaxy"

    def test_destroy_tray_icon_no_error(self):
        api = NoOpSystemAPI()
        handle = TrayHandle(active=False)
        api.destroy_tray_icon(handle)  # must not raise


# ===========================================================================
# get_system_api factory
# ===========================================================================

class TestGetSystemAPI:
    def setup_method(self):
        reset_system_api()

    def teardown_method(self):
        reset_system_api()

    def test_returns_noop_on_non_windows(self):
        with patch("core.system_api.platform.system", return_value="Linux"):
            api = get_system_api()
        assert isinstance(api, NoOpSystemAPI)

    def test_singleton_returns_same_instance(self):
        with patch("core.system_api.platform.system", return_value="Linux"):
            api1 = get_system_api()
            api2 = get_system_api()
        assert api1 is api2

    def test_reset_clears_singleton(self):
        with patch("core.system_api.platform.system", return_value="Linux"):
            api1 = get_system_api()
        reset_system_api()
        with patch("core.system_api.platform.system", return_value="Linux"):
            api2 = get_system_api()
        assert api1 is not api2

    def test_returns_windows_adapter_on_windows(self):
        mock_adapter = MagicMock()
        mock_cls = MagicMock(return_value=mock_adapter)

        with patch("core.system_api.platform.system", return_value="Windows"), \
             patch("core.system_api.WindowsAdapter", mock_cls, create=True):
            # Reimport get_system_api with patched platform
            import core.system_api as _mod
            original = _mod._instance
            _mod._instance = None
            try:
                # Patch the import inside get_system_api
                with patch.dict("sys.modules", {
                    "core.system_api.windows_adapter": MagicMock(
                        WindowsAdapter=mock_cls
                    )
                }):
                    api = _mod.get_system_api()
                    assert api is mock_adapter
            finally:
                _mod._instance = original


# ===========================================================================
# WindowsAdapter — mocked Win32 environment
# ===========================================================================

class TestWindowsAdapterLaunchApp:
    """Tests for WindowsAdapter.launch_app — Win32 is fully mocked."""

    def _make_adapter_with_win32(self):
        from core.system_api.windows_adapter import WindowsAdapter
        import core.system_api.windows_adapter as mod
        adapter = WindowsAdapter.__new__(WindowsAdapter)
        adapter.__init__()
        return adapter, mod

    def test_empty_target_returns_failure(self):
        adapter, mod = self._make_adapter_with_win32()
        with patch.object(mod, "_WIN32_AVAILABLE", True):
            result = adapter.launch_app("")
        assert result.success is False
        assert "empty" in (result.error or "")

    def test_shell_execute_success(self):
        adapter, mod = self._make_adapter_with_win32()
        mock_shell32 = MagicMock()
        mock_shell32.ShellExecuteW.return_value = 42  # > 32 → success

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_shell32", mock_shell32):
            result = adapter.launch_app("notepad.exe")

        assert result.success is True
        mock_shell32.ShellExecuteW.assert_called_once()

    def test_shell_execute_failure_falls_back_to_subprocess(self):
        adapter, mod = self._make_adapter_with_win32()
        mock_shell32 = MagicMock()
        mock_shell32.ShellExecuteW.return_value = 2  # ≤ 32 → failure

        mock_proc = MagicMock()
        mock_proc.pid = 9999

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_shell32", mock_shell32), \
             patch("subprocess.Popen", return_value=mock_proc):
            result = adapter.launch_app("myapp.exe", args=["--flag"])

        assert result.success is True
        assert result.pid == 9999

    def test_subprocess_file_not_found(self):
        adapter, mod = self._make_adapter_with_win32()
        mock_shell32 = MagicMock()
        mock_shell32.ShellExecuteW.return_value = 2

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_shell32", mock_shell32), \
             patch("subprocess.Popen", side_effect=FileNotFoundError):
            result = adapter.launch_app("doesnotexist.exe")

        assert result.success is False
        assert "not found" in (result.error or "")

    def test_subprocess_permission_denied(self):
        adapter, mod = self._make_adapter_with_win32()
        mock_shell32 = MagicMock()
        mock_shell32.ShellExecuteW.return_value = 5  # ERROR_ACCESS_DENIED

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_shell32", mock_shell32), \
             patch("subprocess.Popen", side_effect=PermissionError):
            result = adapter.launch_app("restricted.exe")

        assert result.success is False
        assert "permission" in (result.error or "").lower()

    def test_no_win32_falls_back_to_subprocess(self):
        adapter, mod = self._make_adapter_with_win32()
        mock_proc = MagicMock()
        mock_proc.pid = 1234

        with patch.object(mod, "_WIN32_AVAILABLE", False), \
             patch("subprocess.Popen", return_value=mock_proc):
            result = adapter.launch_app("app.exe")

        assert result.success is True


class TestWindowsAdapterWindowManagement:
    def _make(self):
        from core.system_api.windows_adapter import WindowsAdapter
        import core.system_api.windows_adapter as mod
        a = WindowsAdapter.__new__(WindowsAdapter)
        a.__init__()
        return a, mod

    def test_enumerate_windows_returns_list(self):
        adapter, mod = self._make()
        with patch.object(mod, "_WIN32_AVAILABLE", False):
            windows = adapter.enumerate_windows()
        assert isinstance(windows, list)
        assert windows == []

    def test_enumerate_windows_with_mock_enum(self):
        adapter, mod = self._make()

        # Simulate two visible windows
        fake_windows = [
            WindowInfo(hwnd=1001, title="Notepad", visible=True, pid=100),
            WindowInfo(hwnd=1002, title="Calculator", visible=True, pid=200),
        ]

        with patch.object(mod, "_collect_windows", return_value=fake_windows):
            windows = adapter.enumerate_windows()

        assert len(windows) == 2
        assert windows[0].title == "Notepad"
        assert windows[1].hwnd == 1002

    def test_enumerate_windows_with_filter(self):
        adapter, mod = self._make()

        fake_windows = [
            WindowInfo(hwnd=1001, title="Notepad", visible=True),
        ]

        with patch.object(mod, "_collect_windows", return_value=fake_windows):
            windows = adapter.enumerate_windows(filter_title="notepad")

        assert len(windows) == 1

    def test_focus_window_by_hwnd_success(self):
        adapter, mod = self._make()
        mock_user32 = MagicMock()
        mock_user32.SetForegroundWindow.return_value = True

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_user32", mock_user32):
            result = adapter.focus_window(1001)

        assert result is True
        mock_user32.SetForegroundWindow.assert_called_once_with(1001)

    def test_focus_window_by_title_found(self):
        adapter, mod = self._make()
        mock_user32 = MagicMock()
        mock_user32.SetForegroundWindow.return_value = True

        fake_windows = [WindowInfo(hwnd=2001, title="Notepad")]

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_user32", mock_user32), \
             patch.object(mod, "_collect_windows", return_value=fake_windows):
            result = adapter.focus_window("Notepad")

        assert result is True
        mock_user32.SetForegroundWindow.assert_called_once_with(2001)

    def test_focus_window_not_found_returns_false(self):
        adapter, mod = self._make()
        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_collect_windows", return_value=[]):
            result = adapter.focus_window("NonExistent")
        assert result is False

    def test_focus_window_noop_without_win32(self):
        adapter, mod = self._make()
        with patch.object(mod, "_WIN32_AVAILABLE", False):
            assert adapter.focus_window("anything") is False


class TestWindowsAdapterHotkeys:
    def _make(self):
        from core.system_api.windows_adapter import WindowsAdapter
        import core.system_api.windows_adapter as mod
        a = WindowsAdapter.__new__(WindowsAdapter)
        a.__init__()
        return a, mod

    def test_register_hotkey_success(self):
        adapter, mod = self._make()
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = True

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_user32", mock_user32):
            handle = adapter.register_hotkey(42, 0x2, 0x41)

        assert isinstance(handle, HotkeyHandle)
        assert handle.active is True
        assert handle.hotkey_id == 42
        mock_user32.RegisterHotKey.assert_called_once_with(None, 42, 0x2, 0x41)

    def test_register_hotkey_with_callback_starts_pump(self):
        adapter, mod = self._make()
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = True

        cb = MagicMock()
        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_user32", mock_user32):
            handle = adapter.register_hotkey(1, 0x0, 0x42, callback=cb)

        assert handle.active is True
        assert adapter._hotkey_pump is not None

    def test_register_hotkey_failure_returns_inactive(self):
        adapter, mod = self._make()
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = False
        mock_kernel32 = MagicMock()
        mock_kernel32.GetLastError.return_value = 1409  # ERROR_HOTKEY_ALREADY_REGISTERED

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_user32", mock_user32), \
             patch.object(mod, "_kernel32", mock_kernel32):
            handle = adapter.register_hotkey(99, 0x2, 0x41)

        assert handle.active is False

    def test_register_hotkey_no_win32_inactive(self):
        adapter, mod = self._make()
        with patch.object(mod, "_WIN32_AVAILABLE", False):
            handle = adapter.register_hotkey(1, 0x0, 0x41)
        assert handle.active is False

    def test_unregister_hotkey_success(self):
        adapter, mod = self._make()
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = True
        mock_user32.UnregisterHotKey.return_value = True

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_user32", mock_user32):
            handle = adapter.register_hotkey(5, 0x2, 0x41)
            result = adapter.unregister_hotkey(handle)

        assert result is True
        assert handle.active is False
        mock_user32.UnregisterHotKey.assert_called_once_with(None, 5)

    def test_unregister_inactive_handle_returns_false(self):
        adapter, mod = self._make()
        handle = HotkeyHandle(hotkey_id=1, modifiers=0, vk_code=0x41, active=False)
        assert adapter.unregister_hotkey(handle) is False


class TestWindowsAdapterTray:
    def _make(self):
        from core.system_api.windows_adapter import WindowsAdapter
        import core.system_api.windows_adapter as mod
        a = WindowsAdapter.__new__(WindowsAdapter)
        a.__init__()
        return a, mod

    def test_create_tray_no_win32_returns_inactive(self):
        adapter, mod = self._make()
        with patch.object(mod, "_WIN32_AVAILABLE", False):
            handle = adapter.create_tray_icon("TestApp")
        assert handle.active is False
        assert handle.tooltip == "TestApp"

    def test_create_tray_win32_success(self):
        adapter, mod = self._make()
        mock_shell32 = MagicMock()
        mock_shell32.Shell_NotifyIconW.return_value = 1  # success

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_shell32", mock_shell32):
            handle = adapter.create_tray_icon("Galaxy")

        assert handle.active is True

    def test_create_tray_win32_failure_returns_inactive(self):
        adapter, mod = self._make()
        mock_shell32 = MagicMock()
        mock_shell32.Shell_NotifyIconW.return_value = 0  # failure (headless)

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_shell32", mock_shell32):
            handle = adapter.create_tray_icon("Galaxy")

        assert handle.active is False

    def test_destroy_tray_noop_when_inactive(self):
        adapter, mod = self._make()
        handle = TrayHandle(active=False)
        adapter.destroy_tray_icon(handle)  # must not raise

    def test_destroy_tray_win32(self):
        adapter, mod = self._make()
        mock_shell32 = MagicMock()

        with patch.object(mod, "_WIN32_AVAILABLE", True), \
             patch.object(mod, "_shell32", mock_shell32):
            handle = TrayHandle(active=True, tooltip="x")
            adapter.destroy_tray_icon(handle)

        mock_shell32.Shell_NotifyIconW.assert_called_once()
        assert handle.active is False


# ===========================================================================
# Data classes / contracts
# ===========================================================================

class TestDataClasses:
    def test_app_launch_result_defaults(self):
        r = AppLaunchResult(success=True)
        assert r.pid is None
        assert r.error is None

    def test_window_info_fields(self):
        w = WindowInfo(hwnd=1, title="Test")
        assert w.visible is True
        assert w.pid is None

    def test_hotkey_handle_fields(self):
        h = HotkeyHandle(hotkey_id=7, modifiers=0x2, vk_code=0x46)
        assert h.active is True  # default

    def test_tray_handle_defaults(self):
        t = TrayHandle()
        assert t.active is False
        assert t.tooltip == ""
