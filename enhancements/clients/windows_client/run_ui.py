#!/usr/bin/env python3
# enhancements/clients/windows_client/run_ui.py — HARD-DISABLED STUB
#
# This launcher has been hard-disabled.  It previously delegated to
# windows_client/main.py (the legacy F12-hotkey chat/sidebar client),
# which has been retired.
#
# Active Windows direction:
#   DesktopPresenceRuntime (core/desktop_presence_runtime.py)
#     — desktop tri-state lifecycle runtime shell (silent/liminal/manifest)
#   windows_client/status_board_v2/
#     — canonical read-only desktop status surface, projection-driven
#
# Authoritative startup path:
#   python unified_launcher.py
#   (or on Windows: start.bat)
#
# See docs/WINDOWS_EXECUTION_PIPELINE.md.

import warnings

warnings.warn(
    "enhancements/clients/windows_client/run_ui.py is hard-disabled.  "
    "It targeted the retired legacy chat/sidebar client.  "
    "Active Windows direction: DesktopPresenceRuntime + status_board_v2.  "
    "Authoritative startup path: python unified_launcher.py  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "enhancements/clients/windows_client/run_ui.py is hard-disabled.  "
    "This launcher targeted windows_client/main.py (legacy chat/sidebar client), "
    "which has been retired.\n"
    "Active Windows direction:\n"
    "  core/desktop_presence_runtime.py  (DesktopPresenceRuntime tri-state shell)\n"
    "  windows_client/status_board_v2/   (projection-driven desktop status surface)\n"
    "Authoritative startup path: python unified_launcher.py\n"
    "See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture."
)
