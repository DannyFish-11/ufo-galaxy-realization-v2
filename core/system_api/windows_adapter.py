"""Windows system API adapter.

Provides concrete implementations of the :class:`~core.system_api.platform_api.SystemAPI`
interface using Win32 APIs via ``ctypes``.  When a Win32 call fails the
adapter logs the error and returns a safe default — it never raises.

Supported operations
--------------------
- **launch_app**: ``ShellExecuteW`` with subprocess fallback.
- **enumerate_windows**: ``EnumWindows`` + ``GetWindowText``.
- **focus_window**: ``SetForegroundWindow`` / ``ShowWindow``.
- **close_window**: ``WM_CLOSE`` message via ``PostMessage``.
- **register_hotkey** / **unregister_hotkey**: ``RegisterHotKey`` / ``UnregisterHotKey``
  with a background message-pump thread.
- **create_tray_icon** / **destroy_tray_icon**: minimal ``Shell_NotifyIcon``
  stub (interface-complete; functional only when a message loop is running).
- **open_file**: ``ShellExecuteW`` with "open" verb.
- **move_file** / **delete_file**: stdlib ``shutil`` / ``os`` operations.
- **list_processes** / **kill_process**: ``psutil`` with ``os.kill`` fallback.
- **get_clipboard** / **set_clipboard**: ``ctypes`` CF_UNICODETEXT clipboard access.
- **send_notification**: ``Shell_NotifyIcon`` balloon tip.

This module must only be imported on Windows.  :func:`core.system_api.get_system_api`
guards the import so non-Windows hosts never load it.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import shutil
import subprocess
import threading
from typing import Callable, Dict, List, Optional

from .platform_api import (
    AppLaunchResult,
    ClipboardResult,
    FileOpResult,
    HotkeyHandle,
    NoOpSystemAPI,
    NotificationResult,
    ProcessInfo,
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

    # ------------------------------------------------------------------
    # App/window close
    # ------------------------------------------------------------------

    def close_window(self, title_or_hwnd: "str | int") -> bool:
        """Send WM_CLOSE to a window by title substring or HWND."""
        _WM_CLOSE = 0x0010
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
            _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            return True
        except Exception as exc:
            logger.debug("close_window error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def open_file(self, path: str) -> FileOpResult:
        """Open *path* with its default application via ShellExecuteW."""
        if not path:
            return FileOpResult(success=False, error="empty path")
        try:
            if _WIN32_AVAILABLE:
                rc = _shell32.ShellExecuteW(None, "open", path, None, None, _SW_SHOW)
                if rc > 32:
                    return FileOpResult(success=True, path=path)
                return FileOpResult(success=False, path=path, error=f"ShellExecuteW rc={rc}")
            # Non-win32 fallback (should not reach here due to guard in get_system_api)
            os.startfile(path)  # type: ignore[attr-defined]
            return FileOpResult(success=True, path=path)
        except Exception as exc:
            logger.debug("open_file error: %s", exc)
            return FileOpResult(success=False, path=path, error=str(exc))

    def move_file(self, src: str, dst: str) -> FileOpResult:
        """Move or rename a file using :func:`shutil.move`."""
        try:
            result = shutil.move(src, dst)
            return FileOpResult(success=True, path=str(result))
        except FileNotFoundError:
            return FileOpResult(success=False, error=f"not found: {src}")
        except PermissionError as exc:
            return FileOpResult(success=False, error=f"permission denied: {exc}")
        except Exception as exc:
            logger.debug("move_file error: %s", exc)
            return FileOpResult(success=False, error=str(exc))

    def delete_file(self, path: str) -> FileOpResult:
        """Delete *path*, preferring recycle-bin (SHFileOperationW) when available."""
        try:
            if _WIN32_AVAILABLE:
                # Use SHFileOperationW to send to recycle bin
                _FO_DELETE = 0x0003
                _FOF_ALLOWUNDO = 0x0040
                _FOF_NOCONFIRMATION = 0x0010
                _FOF_SILENT = 0x0004

                class _SHFILEOPSTRUCT(ctypes.Structure):
                    _fields_ = [
                        ("hwnd", ctypes.c_void_p),
                        ("wFunc", ctypes.c_uint),
                        ("pFrom", ctypes.c_wchar_p),
                        ("pTo", ctypes.c_wchar_p),
                        ("fFlags", ctypes.c_ushort),
                        ("fAnyOperationsAborted", ctypes.c_bool),
                        ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", ctypes.c_wchar_p),
                    ]

                op = _SHFILEOPSTRUCT()
                op.wFunc = _FO_DELETE
                op.pFrom = path + "\x00"
                op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT
                rc = _shell32.SHFileOperationW(ctypes.byref(op))
                if rc == 0:
                    return FileOpResult(success=True, path=path)
                # Fall through to os.remove on SHFileOperation failure
            os.remove(path)
            return FileOpResult(success=True, path=path)
        except FileNotFoundError:
            return FileOpResult(success=False, error=f"not found: {path}")
        except PermissionError as exc:
            return FileOpResult(success=False, error=f"permission denied: {exc}")
        except Exception as exc:
            logger.debug("delete_file error: %s", exc)
            return FileOpResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Process queries
    # ------------------------------------------------------------------

    def list_processes(self) -> List[ProcessInfo]:
        """Return a snapshot of running processes using psutil or WMIC fallback."""
        try:
            import psutil  # type: ignore[import]
            result: List[ProcessInfo] = []
            for proc in psutil.process_iter(["pid", "name", "status"]):
                try:
                    info = proc.info
                    result.append(
                        ProcessInfo(
                            pid=info["pid"],
                            name=info.get("name") or "",
                            status=info.get("status") or "running",
                        )
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return result
        except ImportError:
            pass
        # WMIC fallback
        try:
            out = subprocess.check_output(
                ["wmic", "process", "get", "ProcessId,Name"],
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).decode(errors="replace")
            procs: List[ProcessInfo] = []
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        procs.append(ProcessInfo(pid=int(parts[-1]), name=" ".join(parts[:-1])))
                    except ValueError:
                        continue
            return procs
        except Exception as exc:
            logger.debug("list_processes error: %s", exc)
            return []

    def kill_process(self, pid: int) -> bool:
        """Terminate process *pid* using psutil or os.kill fallback."""
        try:
            import psutil  # type: ignore[import]
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                return True
            except psutil.NoSuchProcess:
                return False
            except psutil.AccessDenied as exc:
                logger.debug("kill_process psutil denied pid=%d: %s", pid, exc)
                return False
        except ImportError:
            pass
        try:
            os.kill(pid, 15)  # SIGTERM
            return True
        except ProcessLookupError:
            return False
        except Exception as exc:
            logger.debug("kill_process error pid=%d: %s", pid, exc)
            return False

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    def get_clipboard(self) -> ClipboardResult:
        """Read plain-text content from the Windows clipboard."""
        _CF_UNICODETEXT = 13
        if not _WIN32_AVAILABLE:
            return ClipboardResult(success=False, error="Win32 not available")
        try:
            if not _user32.OpenClipboard(None):
                return ClipboardResult(success=False, error="OpenClipboard failed")
            try:
                h_mem = _user32.GetClipboardData(_CF_UNICODETEXT)
                if not h_mem:
                    return ClipboardResult(success=True, text="")
                _kernel32.GlobalLock.restype = ctypes.c_void_p
                ptr = _kernel32.GlobalLock(h_mem)
                if not ptr:
                    return ClipboardResult(success=False, error="GlobalLock failed")
                try:
                    text = ctypes.wstring_at(ptr)
                finally:
                    _kernel32.GlobalUnlock(h_mem)
                return ClipboardResult(success=True, text=text)
            finally:
                _user32.CloseClipboard()
        except Exception as exc:
            logger.debug("get_clipboard error: %s", exc)
            return ClipboardResult(success=False, error=str(exc))

    def set_clipboard(self, text: str) -> ClipboardResult:
        """Write *text* to the Windows clipboard as CF_UNICODETEXT."""
        _CF_UNICODETEXT = 13
        _GMEM_MOVEABLE = 0x0002
        if not _WIN32_AVAILABLE:
            return ClipboardResult(success=False, error="Win32 not available")
        try:
            encoded = (text + "\x00").encode("utf-16-le")
            size = len(encoded)
            h_mem = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
            if not h_mem:
                return ClipboardResult(success=False, error="GlobalAlloc failed")
            _kernel32.GlobalLock.restype = ctypes.c_void_p
            ptr = _kernel32.GlobalLock(h_mem)
            if not ptr:
                _kernel32.GlobalFree(h_mem)
                return ClipboardResult(success=False, error="GlobalLock failed")
            try:
                ctypes.memmove(ptr, encoded, size)
            finally:
                _kernel32.GlobalUnlock(h_mem)
            if not _user32.OpenClipboard(None):
                _kernel32.GlobalFree(h_mem)
                return ClipboardResult(success=False, error="OpenClipboard failed")
            try:
                _user32.EmptyClipboard()
                _user32.SetClipboardData(_CF_UNICODETEXT, h_mem)
                return ClipboardResult(success=True)
            finally:
                _user32.CloseClipboard()
        except Exception as exc:
            logger.debug("set_clipboard error: %s", exc)
            return ClipboardResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def send_notification(
        self,
        title: str,
        body: str,
        icon_path: Optional[str] = None,
    ) -> NotificationResult:
        """Show a balloon tooltip via Shell_NotifyIcon NIIF_INFO."""
        _NIIF_INFO = 0x00000001
        _NIF_INFO = 0x00000010
        _NIM_MODIFY = 0x00000001

        if not _WIN32_AVAILABLE:
            return NotificationResult(success=False, error="Win32 not available")
        try:
            class _NOTIFYICONDATAEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("hWnd", ctypes.c_void_p),
                    ("uID", ctypes.c_uint),
                    ("uFlags", ctypes.c_uint),
                    ("uCallbackMessage", ctypes.c_uint),
                    ("hIcon", ctypes.c_void_p),
                    ("szTip", ctypes.c_wchar * 128),
                    ("dwState", ctypes.c_ulong),
                    ("dwStateMask", ctypes.c_ulong),
                    ("szInfo", ctypes.c_wchar * 256),
                    ("uTimeout", ctypes.c_uint),
                    ("szInfoTitle", ctypes.c_wchar * 64),
                    ("dwInfoFlags", ctypes.c_ulong),
                ]

            data = _NOTIFYICONDATAEX()
            data.cbSize = ctypes.sizeof(_NOTIFYICONDATAEX)
            data.uID = 1
            data.uFlags = _NIF_INFO
            data.szInfoTitle = title[:63]
            data.szInfo = body[:255]
            data.dwInfoFlags = _NIIF_INFO
            data.uTimeout = 5000

            # NIM_ADD first (may already exist — ignore failure), then modify
            _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data))
            rc = _shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(data))
            return NotificationResult(success=bool(rc), notification_id=1)
        except Exception as exc:
            logger.debug("send_notification error: %s", exc)
            return NotificationResult(success=False, error=str(exc))
