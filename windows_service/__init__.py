"""
windows_service -- Galaxy V2 Windows Persistent Runtime
=======================================================

Provides Windows-specific components for running Galaxy AI
as a persistent background system:

- :mod:`windows_service.galaxy_service` -- Windows Service wrapper (pywin32)
- :mod:`windows_service.tray_icon`      -- System tray icon (pystray)
- :mod:`windows_service.autostart`      -- Registry auto-start registration

Quick Start::

    # Install as Windows service (admin required)
    python -m windows_service.galaxy_service install
    python -m windows_service.galaxy_service start

    # Or register for auto-start (no admin required)
    python -m windows_service.autostart

    # Launch system tray
    python -m windows_service.tray_icon
"""

__all__ = [
    "galaxy_service",
    "tray_icon",
    "autostart",
]
