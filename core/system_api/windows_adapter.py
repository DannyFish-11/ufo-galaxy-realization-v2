"""Windows system API adapter.

Provides concrete implementations of the :class:`~core.system_api.platform_api.SystemAPI`
interface using Win32 APIs via ``ctypes``.  When a Win32 call fails the
adapter logs the error and returns a safe default — it never raises.

Supported operations
--------------------
- **launch_app**: ``ShellExecuteW`` with subprocess fallback.
- **enumerate_windows**: ``EnumWindows`` + ``GetWindowText``.
- **focus_window**: ``SetForegroundWindow`` / ``ShowWindow``.
- **register_hotkey** / **unregister_hotkey**: ``RegisterHotKey`` / ``UnregisterHotKey``
  with a background message-pump thread.
- **create_tray_icon** / **destroy_tray_icon**: minimal ``Shell_NotifyIcon``
  stub (interface-complete; functional only when a message loop is running).

This module must only be imported on Windows.  :func:`core.system_api.get_system_api`
guards the import so non-Windows hosts never load it.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import threading
from typing import Callable, Dict, List, Optional

from .platform_api import (
    AppLaunchResult,
    HotkeyHandle,
    NoOpSystemAPI,
    SystemAPI,
    TrayHandle,
    WindowInfo,
)

__all__ = ["WindowsAdapter"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------

_SW_RESTORE = 9
_SW_SHOW = 5
_WM_HOTKEY = 0x0312
_WM_USER = 0x0400

# Shell_NotifyIcon message codes
_NIM_ADD = 0x00000000
_NIM_DELETE = 0x00000002
_NIF_MESSAGE = 0x00000001
_NIF_ICON = 0x00000002
_NIF_TIP = 0x00000004

# ---------------------------------------------------------------------------
# ctypes helpers (lazily resolved so import succeeds without Win32)
# ---------------------------------------------------------------------------

try:
    _user32 = ctypes.windll.user32       # type: ignore[attr-defined]
    _kernel32 = ctypes.windll.kernel32   # type: ignore[attr-defined]
    _shell32 = ctypes.windll.shell32     # type: ignore[attr-defined]
    _WIN32_AVAILABLE = True
except AttributeError:
    _WIN32_AVAILABLE = False
    _user32 = None
    _kernel32 = None
    _shell32 = None


# ---------------------------------------------------------------------------
# Helper: NOTIFYICONDATA ctypes structure (minimal fields)
# ---------------------------------------------------------------------------

class _NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
    ]


# ---------------------------------------------------------------------------
# Helper: window enumeration callback
# ---------------------------------------------------------------------------

if _WIN32_AVAILABLE:
    _EnumWindowsProc = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
else:
    _EnumWindowsProc = None  # type: ignore[assignment]


def _collect_windows(
    filter_title: Optional[str],
) -> List[WindowInfo]:
    """Return visible top-level windows, optionally filtered by title."""
    results: List[WindowInfo] = []
    if not _WIN32_AVAILABLE:
        return results

    buf = ctypes.create_unicode_buffer(512)
    pid_buf = ctypes.c_ulong(0)

    def _cb(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        _user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if filter_title and filter_title.lower() not in title.lower():
            return True
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        results.append(
            WindowInfo(
                hwnd=hwnd,
                title=title,
                visible=True,
                pid=pid_buf.value or None,
            )
        )
        return True

    proc = _EnumWindowsProc(_cb)
    _user32.EnumWindows(proc, 0)
    return results


# ---------------------------------------------------------------------------
# Hotkey message-pump thread
# ---------------------------------------------------------------------------

class _HotkeyPump(threading.Thread):
    """Background thread that drives the Win32 hotkey message pump.

    The pump translates WM_HOTKEY messages into registered Python callbacks.
    It is started lazily the first time a hotkey is registered and stops
    when the WindowsAdapter is garbage-collected (daemon=True).
    """

    def __init__(self) -> None:
        super().__init__(daemon=True, name="galaxy-hotkey-pump")
        self._callbacks: Dict[int, Callable[[], None]] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def add_callback(self, hotkey_id: int, cb: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks[hotkey_id] = cb

    def remove_callback(self, hotkey_id: int) -> None:
        with self._lock:
            self._callbacks.pop(hotkey_id, None)

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        u32 = _user32
        if not _WIN32_AVAILABLE or u32 is None:
            return
        msg = ctypes.wintypes.MSG()
        while not self._stop_event.is_set():
            result = u32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, 1  # PM_REMOVE
            )
            if result:
                if msg.message == _WM_HOTKEY:
                    hid = int(msg.wParam)
                    with self._lock:
                        cb = self._callbacks.get(hid)
                    if cb is not None:
                        try:
                            cb()
                        except Exception as exc:  # pragma: no cover
                            logger.debug("Hotkey callback %d raised: %s", hid, exc)
            else:
                self._stop_event.wait(timeout=0.05)


# ---------------------------------------------------------------------------
# Windows adapter
# ---------------------------------------------------------------------------

class WindowsAdapter(SystemAPI):
    """Concrete system API adapter for Windows hosts.

    All Win32 failures are caught, logged at DEBUG level, and translated
    into safe return values.  No exception escapes this class.
    """

    def __init__(self) -> None:
        self._hotkey_pump: Optional[_HotkeyPump] = None
        self._pump_lock = threading.Lock()
        self._registered_hotkeys: Dict[int, HotkeyHandle] = {}

    # ------------------------------------------------------------------
    # Platform info
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        return _WIN32_AVAILABLE

    # ------------------------------------------------------------------
    # App launch
    # ------------------------------------------------------------------

    def launch_app(
        self,
        target: str,
        args: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
    ) -> AppLaunchResult:
        """Launch *target* via ShellExecuteW with subprocess fallback."""
        if not target:
            return AppLaunchResult(success=False, error="empty target")

        # --- ShellExecuteW path (handles URIs, file associations, etc.) ---
        if _WIN32_AVAILABLE:
            params = " ".join(args) if args else None
            rc = _shell32.ShellExecuteW(
                None,
                "open",
                target,
                params,
                working_dir,
                _SW_SHOW,
            )
            if rc > 32:
                logger.debug("ShellExecuteW launched %r → rc=%d", target, rc)
                return AppLaunchResult(success=True)
            logger.debug(
                "ShellExecuteW failed for %r (rc=%d); falling back to subprocess",
                target, rc,
            )

        # --- subprocess fallback ---
        cmd = [target] + (args or [])
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=working_dir,
                creationflags=subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
                if hasattr(subprocess, "DETACHED_PROCESS")
                else 0,
            )
            return AppLaunchResult(success=True, pid=proc.pid)
        except FileNotFoundError:
            return AppLaunchResult(success=False, error=f"not found: {target}")
        except PermissionError:
            return AppLaunchResult(success=False, error=f"permission denied: {target}")
        except Exception as exc:
            return AppLaunchResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def enumerate_windows(
        self, filter_title: Optional[str] = None
    ) -> List[WindowInfo]:
        try:
            return _collect_windows(filter_title)
        except Exception as exc:
            logger.debug("enumerate_windows error: %s", exc)
            return []

    def focus_window(self, title_or_hwnd: "str | int") -> bool:
        if not _WIN32_AVAILABLE:
            return False
        try:
            hwnd: Optional[int] = None
            if isinstance(title_or_hwnd, int):
                hwnd = title_or_hwnd
            else:
                windows = _collect_windows(filter_title=title_or_hwnd)
                if windows:
                    hwnd = windows[0].hwnd

            if hwnd is None:
                return False

            _user32.ShowWindow(hwnd, _SW_RESTORE)
            result = bool(_user32.SetForegroundWindow(hwnd))
            return result
        except Exception as exc:
            logger.debug("focus_window error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Global hotkeys
    # ------------------------------------------------------------------

    def _ensure_pump(self) -> _HotkeyPump:
        with self._pump_lock:
            if self._hotkey_pump is None or not self._hotkey_pump.is_alive():
                self._hotkey_pump = _HotkeyPump()
                self._hotkey_pump.start()
            return self._hotkey_pump

    def register_hotkey(
        self,
        hotkey_id: int,
        modifiers: int,
        vk_code: int,
        callback: Optional[Callable[[], None]] = None,
    ) -> HotkeyHandle:
        handle = HotkeyHandle(
            hotkey_id=hotkey_id,
            modifiers=modifiers,
            vk_code=vk_code,
            active=False,
        )
        if not _WIN32_AVAILABLE:
            return handle

        try:
            success = bool(
                _user32.RegisterHotKey(None, hotkey_id, modifiers, vk_code)
            )
            if success:
                handle.active = True
                self._registered_hotkeys[hotkey_id] = handle
                if callback is not None:
                    pump = self._ensure_pump()
                    pump.add_callback(hotkey_id, callback)
                logger.debug(
                    "Registered hotkey id=%d mod=0x%x vk=0x%x",
                    hotkey_id, modifiers, vk_code,
                )
            else:
                err = _kernel32.GetLastError()
                logger.debug(
                    "RegisterHotKey failed id=%d (error %d)", hotkey_id, err
                )
        except Exception as exc:
            logger.debug("register_hotkey error: %s", exc)

        return handle

    def unregister_hotkey(self, handle: HotkeyHandle) -> bool:
        if not handle.active:
            return False
        if not _WIN32_AVAILABLE:
            return False

        try:
            success = bool(_user32.UnregisterHotKey(None, handle.hotkey_id))
            if success:
                handle.active = False
                self._registered_hotkeys.pop(handle.hotkey_id, None)
                pump = self._hotkey_pump
                if pump is not None:
                    pump.remove_callback(handle.hotkey_id)
            return success
        except Exception as exc:
            logger.debug("unregister_hotkey error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # System tray (stub — interface-complete)
    # ------------------------------------------------------------------

    def create_tray_icon(
        self,
        tooltip: str = "Galaxy",
        icon_path: Optional[str] = None,
    ) -> TrayHandle:
        """Create a system-tray icon stub.

        On Windows with a running message loop this calls Shell_NotifyIcon.
        In headless/server contexts this returns an inactive handle so
        callers can proceed without checking the platform.
        """
        handle = TrayHandle(active=False, tooltip=tooltip)
        if not _WIN32_AVAILABLE:
            return handle

        try:
            data = _NOTIFYICONDATA()
            data.cbSize = ctypes.sizeof(_NOTIFYICONDATA)
            data.uID = 1
            data.uFlags = _NIF_TIP
            data.szTip = tooltip[:127]

            rc = _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data))
            if rc:
                handle.active = True
                logger.debug("System tray icon created: %r", tooltip)
            else:
                logger.debug(
                    "Shell_NotifyIconW(NIM_ADD) returned 0 "
                    "(headless or no message loop) — tray stub inactive"
                )
        except Exception as exc:
            logger.debug("create_tray_icon error: %s", exc)

        return handle

    def destroy_tray_icon(self, handle: TrayHandle) -> None:
        if not handle.active or not _WIN32_AVAILABLE:
            return
        try:
            data = _NOTIFYICONDATA()
            data.cbSize = ctypes.sizeof(_NOTIFYICONDATA)
            data.uID = 1
            _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(data))
            handle.active = False
        except Exception as exc:
            logger.debug("destroy_tray_icon error: %s", exc)
