# windows_client/ui_sidebar.py — HARD-DISABLED STUB
#
# This module has been hard-disabled.  The legacy Tk chat sidebar is no longer
# an active Windows execution or input path.
#
# The Windows desktop UI is now a read-only status board:
#   windows_client/status_board.py
#
# All command execution routes through:
#   windows_aip_client.py → WindowsExecutionArbiter → WindowsAutonomyManager
#
# See docs/WINDOWS_STATUS_BOARD.md and docs/WINDOWS_EXECUTION_PIPELINE.md.

import warnings

warnings.warn(
    "ui_sidebar.py is hard-disabled and must not be used as a Windows "
    "execution or chat-input path.  Use windows_aip_client.py instead.  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "windows_client/ui_sidebar.py is hard-disabled.  "
    "The legacy Tk chat sidebar has been retired.  "
    "For the canonical desktop status board use:\n"
    "  python -m windows_client.status_board_v2\n"
    "For command execution use:\n"
    "  windows_aip_client.py → WindowsExecutionArbiter.route_command()\n"
    "See docs/WINDOWS_STATUS_BOARD.md and docs/WINDOWS_EXECUTION_PIPELINE.md."
)
