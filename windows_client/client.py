# windows_client/client.py — HARD-DISABLED STUB
#
# This module has been hard-disabled.  The legacy bespoke Galaxy Gateway/AIP
# client is no longer an active primary path.
#
# Unified Windows device ingress:
#   windows_aip_client.py → WindowsExecutionArbiter.route_command()
#
# See docs/WINDOWS_EXECUTION_PIPELINE.md.

import warnings

warnings.warn(
    "windows_client/client.py is hard-disabled.  "
    "Use windows_aip_client.py → WindowsExecutionArbiter instead.  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "windows_client/client.py is hard-disabled.  "
    "The legacy bespoke Gateway/AIP handler has been retired.  "
    "All Windows device ingress must use:\n"
    "  windows_aip_client.py → WindowsExecutionArbiter.route_command()\n"
    "See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture."
)
