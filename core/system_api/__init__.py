"""Galaxy Windows System API integration.

Provides a minimal OS control layer for:
  - Application launch
  - Window enumeration and focus
  - Global hotkey registration/unregistration
  - System tray / background run hooks (stub interface on non-Windows)

Usage::

    from core.system_api import get_system_api

    api = get_system_api()        # returns platform-appropriate adapter
    api.launch_app("notepad.exe")
    api.focus_window("Notepad")

On non-Windows platforms all methods are no-ops that return safe defaults.
"""

from __future__ import annotations

import platform
from typing import TYPE_CHECKING

from .platform_api import SystemAPI, NoOpSystemAPI

if TYPE_CHECKING:
    pass

__all__ = [
    "SystemAPI",
    "NoOpSystemAPI",
    "get_system_api",
]

_instance: "SystemAPI | None" = None


def get_system_api() -> "SystemAPI":
    """Return the process-level system API singleton.

    On Windows this is a :class:`WindowsAdapter`; on all other platforms
    it is a :class:`NoOpSystemAPI` that silently ignores every call.
    """
    global _instance
    if _instance is None:
        if platform.system() == "Windows":
            from .windows_adapter import WindowsAdapter  # noqa: PLC0415
            _instance = WindowsAdapter()
        else:
            _instance = NoOpSystemAPI()
    return _instance


def reset_system_api() -> None:
    """Reset the singleton (intended for tests only)."""
    global _instance
    _instance = None
