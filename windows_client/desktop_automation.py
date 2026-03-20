# windows_client/desktop_automation.py — HARD-DISABLED STUB
#
# This module has been hard-disabled.  The legacy pyautogui-based desktop
# automation path is no longer an active primary execution path.
#
# GUI coordinate automation is handled as a fallback level inside
# WindowsExecutionArbiter (not as a standalone module).
#
# Active Windows execution path:
#   windows_aip_client.py → WindowsExecutionArbiter → WindowsAutonomyManager
#
# See docs/WINDOWS_EXECUTION_PIPELINE.md.

import warnings

warnings.warn(
    "desktop_automation.py is hard-disabled.  GUI automation is a fallback "
    "level inside WindowsExecutionArbiter.  Use windows_aip_client.py.  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "windows_client/desktop_automation.py is hard-disabled.  "
    "The legacy pyautogui-based automation path has been retired.  "
    "GUI automation is now a fallback level inside WindowsExecutionArbiter.  "
    "All Windows command execution must use:\n"
    "  windows_aip_client.py → WindowsExecutionArbiter.route_command()\n"
    "See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture."
)
