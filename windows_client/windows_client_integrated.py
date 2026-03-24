# windows_client/windows_client_integrated.py — HARD-DISABLED STUB
#
# This module has been hard-disabled.  The legacy PyQt6 integrated client
# (L4 main-loop UI) is no longer an active Windows surface.
#
# Active Windows direction:
#   DesktopPresenceRuntime (core/desktop_presence_runtime.py)
#     — desktop tri-state lifecycle runtime shell (silent/liminal/manifest)
#   windows_client/status_board_v2/
#     — canonical read-only desktop status surface, projection-driven
#
# See docs/WINDOWS_EXECUTION_PIPELINE.md.

import warnings

warnings.warn(
    "windows_client/windows_client_integrated.py is hard-disabled.  "
    "The legacy PyQt6 integrated client has been retired.  "
    "Active Windows direction: DesktopPresenceRuntime + status_board_v2.  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "windows_client/windows_client_integrated.py is hard-disabled.  "
    "The legacy PyQt6 Galaxy client (L4-loop integrated UI) has been retired.\n"
    "Active Windows direction:\n"
    "  core/desktop_presence_runtime.py  (DesktopPresenceRuntime tri-state shell)\n"
    "  windows_client/status_board_v2/   (projection-driven desktop status surface)\n"
    "See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture."
)
