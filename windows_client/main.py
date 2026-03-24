# windows_client/main.py — HARD-DISABLED STUB
#
# This module has been hard-disabled.  The legacy F12-hotkey chat/sidebar
# client is no longer an active Windows execution path.
#
# Active Windows direction:
#   DesktopPresenceRuntime (core/desktop_presence_runtime.py)
#     — desktop tri-state lifecycle runtime shell (silent/liminal/manifest)
#   windows_client/status_board_v2/
#     — canonical read-only desktop status surface, projection-driven
#     — consumes GET /api/v1/projection/runtime
#
# For Windows device ingress:
#   windows_aip_client.py → WindowsExecutionArbiter.route_command()
#
# See docs/WINDOWS_EXECUTION_PIPELINE.md.

import warnings

warnings.warn(
    "windows_client/main.py is hard-disabled.  "
    "The legacy F12-hotkey chat/sidebar client has been retired.  "
    "Active Windows direction: DesktopPresenceRuntime + status_board_v2.  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "windows_client/main.py is hard-disabled.  "
    "The legacy chat/sidebar client (F12 hotkey, ui_sidebar.py, "
    "ui/galaxy_client_ui.py) has been retired.\n"
    "Active Windows direction:\n"
    "  core/desktop_presence_runtime.py  (DesktopPresenceRuntime tri-state shell)\n"
    "  windows_client/status_board_v2/   (projection-driven desktop status surface)\n"
    "For Windows device ingress:\n"
    "  windows_aip_client.py → WindowsExecutionArbiter.route_command()\n"
    "See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture."
)
