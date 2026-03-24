# windows_client/key_listener.py — HARD-DISABLED STUB
#
# This module has been hard-disabled.  The F12 global hotkey listener was
# part of the legacy chat/sidebar client (windows_client/main.py), which
# has been retired.
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
    "windows_client/key_listener.py is hard-disabled.  "
    "The F12 hotkey listener was part of the retired legacy sidebar client.  "
    "Active Windows direction: DesktopPresenceRuntime + status_board_v2.  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "windows_client/key_listener.py is hard-disabled.  "
    "The F12 hotkey keyboard listener was part of the legacy sidebar/chat client "
    "which has been retired.\n"
    "Active Windows direction:\n"
    "  core/desktop_presence_runtime.py  (DesktopPresenceRuntime tri-state shell)\n"
    "  windows_client/status_board_v2/   (projection-driven desktop status surface)\n"
    "See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture."
)
