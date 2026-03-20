"""
windows_client/windows_mcp_server.py — HARD-DISABLED STUB
===========================================================

.. deprecated::
    This module has been **hard-disabled** and is no longer part of the active
    Windows execution pipeline.

    The unified Windows execution pipeline is::

        AIP ingress (windows_aip_client.py)
            ↓
        WindowsExecutionArbiter.route_command()
            ↓  fallback chain: system_api → UIA → GUI → VLM
        WindowsAutonomyManager

    Attempting to import or execute this module will raise a ``RuntimeError``.
    See ``docs/WINDOWS_EXECUTION_PIPELINE.md`` for the current architecture.
"""

import warnings

warnings.warn(
    "windows_mcp_server.py is deprecated and hard-disabled.  "
    "Use windows_aip_client.py → WindowsExecutionArbiter instead.  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "windows_client/windows_mcp_server.py is hard-disabled and must not be "
    "imported in production.  The MCP stdio execution path has been retired.  "
    "All Windows command execution must go through:\n"
    "  windows_aip_client.py → WindowsExecutionArbiter.route_command()\n"
    "See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture."
)
