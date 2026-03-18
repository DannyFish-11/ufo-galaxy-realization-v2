"""Abstract base class and no-op implementation for the system API layer.

All platform-specific adapters (e.g. WindowsAdapter) must subclass
:class:`SystemAPI`.  Non-Windows hosts get :class:`NoOpSystemAPI`, which
returns safe defaults for every method so the rest of the codebase can
call the API unconditionally.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

__all__ = [
    "AppLaunchResult",
    "WindowInfo",
    "HotkeyHandle",
    "TrayHandle",
    "SystemAPI",
    "NoOpSystemAPI",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AppLaunchResult:
    """Result of an :meth:`SystemAPI.launch_app` call."""

    success: bool
    pid: Optional[int] = None
    error: Optional[str] = None


@dataclass
class WindowInfo:
    """Minimal metadata about an OS-level window."""

    hwnd: int
    title: str
    visible: bool = True
    pid: Optional[int] = None


@dataclass
class HotkeyHandle:
    """Opaque handle returned by :meth:`SystemAPI.register_hotkey`."""

    hotkey_id: int
    modifiers: int
    vk_code: int
    active: bool = True


@dataclass
class TrayHandle:
    """Opaque handle for the system-tray icon."""

    active: bool = False
    tooltip: str = ""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class SystemAPI(ABC):
    """Minimal OS control interface consumed by the Galaxy runtime.

    All values exposed to callers must be bounded [0, 1] where applicable.
    Implementations must:
    - Return :class:`AppLaunchResult` with ``success=False`` on failure
      (never raise on permission/not-found errors).
    - Return an empty list from :meth:`enumerate_windows` when access
      is unavailable.
    - Return an inactive :class:`HotkeyHandle` when registration fails.
    - Never contain decision logic: the layer is purely mechanical.
    """

    # ------------------------------------------------------------------
    # App launch
    # ------------------------------------------------------------------

    @abstractmethod
    def launch_app(
        self,
        target: str,
        args: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
    ) -> AppLaunchResult:
        """Launch an application by executable path or URI scheme.

        Parameters
        ----------
        target:
            Executable path, URI (e.g. ``mailto:``) or protocol handler.
        args:
            Optional list of command-line arguments.
        working_dir:
            Optional working directory for the new process.

        Returns
        -------
        AppLaunchResult
            Always returns a result object; never raises on OS errors.
        """

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    @abstractmethod
    def enumerate_windows(
        self, filter_title: Optional[str] = None
    ) -> List[WindowInfo]:
        """Return a list of visible top-level windows.

        Parameters
        ----------
        filter_title:
            Optional substring to filter window titles (case-insensitive).
        """

    @abstractmethod
    def focus_window(self, title_or_hwnd: "str | int") -> bool:
        """Bring a window to the foreground.

        Parameters
        ----------
        title_or_hwnd:
            Window title substring or HWND integer.

        Returns
        -------
        bool
            True if the window was found and focused.
        """

    # ------------------------------------------------------------------
    # Global hotkeys
    # ------------------------------------------------------------------

    @abstractmethod
    def register_hotkey(
        self,
        hotkey_id: int,
        modifiers: int,
        vk_code: int,
        callback: Optional[Callable[[], None]] = None,
    ) -> HotkeyHandle:
        """Register a system-wide hotkey.

        Parameters
        ----------
        hotkey_id:
            Unique integer identifier for this hotkey (caller's domain).
        modifiers:
            Modifier bitmask (MOD_ALT=0x1, MOD_CONTROL=0x2, MOD_SHIFT=0x4,
            MOD_WIN=0x8).
        vk_code:
            Virtual-key code (e.g. 0x41 for 'A').
        callback:
            Optional callable invoked when the hotkey fires.

        Returns
        -------
        HotkeyHandle
            Active handle if registration succeeded; inactive otherwise.
        """

    @abstractmethod
    def unregister_hotkey(self, handle: HotkeyHandle) -> bool:
        """Unregister a previously registered hotkey.

        Returns True if the hotkey was active and has been removed.
        """

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------

    @abstractmethod
    def create_tray_icon(
        self,
        tooltip: str = "Galaxy",
        icon_path: Optional[str] = None,
    ) -> TrayHandle:
        """Create (or update) a system-tray icon.

        Returns an active :class:`TrayHandle` on success.
        On platforms where tray icons are unsupported an inactive handle
        is returned.
        """

    @abstractmethod
    def destroy_tray_icon(self, handle: TrayHandle) -> None:
        """Remove the system-tray icon identified by *handle*."""

    # ------------------------------------------------------------------
    # Platform info
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """True if the platform supports the full API."""


# ---------------------------------------------------------------------------
# No-op fallback for non-Windows platforms
# ---------------------------------------------------------------------------

class NoOpSystemAPI(SystemAPI):
    """Silent no-op implementation for non-Windows hosts.

    Every method returns a safe, empty, or False default so callers do
    not need to guard against platform availability.
    """

    @property
    def is_available(self) -> bool:
        return False

    def launch_app(
        self,
        target: str,
        args: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
    ) -> AppLaunchResult:
        logger.debug("NoOpSystemAPI.launch_app(%r) — no-op on this platform", target)
        return AppLaunchResult(success=False, error="platform not supported")

    def enumerate_windows(
        self, filter_title: Optional[str] = None
    ) -> List[WindowInfo]:
        return []

    def focus_window(self, title_or_hwnd: "str | int") -> bool:
        return False

    def register_hotkey(
        self,
        hotkey_id: int,
        modifiers: int,
        vk_code: int,
        callback: Optional[Callable[[], None]] = None,
    ) -> HotkeyHandle:
        return HotkeyHandle(
            hotkey_id=hotkey_id,
            modifiers=modifiers,
            vk_code=vk_code,
            active=False,
        )

    def unregister_hotkey(self, handle: HotkeyHandle) -> bool:
        return False

    def create_tray_icon(
        self,
        tooltip: str = "Galaxy",
        icon_path: Optional[str] = None,
    ) -> TrayHandle:
        return TrayHandle(active=False, tooltip=tooltip)

    def destroy_tray_icon(self, handle: TrayHandle) -> None:
        pass
