"""windows_client._legacy — LEGACY WINDOWS CLIENT ARCHIVE
==========================================================

This package holds the retired legacy Windows client surfaces.  None of the
modules in this package are part of the active Windows runtime.

**Do not import from this package in production code.**

Retired surfaces — fully deleted (PR-8)
-----------------------------------------
- ``START_CLIENT.bat``             — Deleted.  Was: legacy F12 sidebar launcher.
  Canonical replacement: ``start.bat`` or ``python main.py``.
- ``start_galaxy_client.bat``      — Deleted.  Was: legacy Gateway WebSocket
  client launcher.  Canonical replacement: ``python main.py``.

Retired surfaces archived here
--------------------------------
- ``ui/galaxy_client_ui.py``       — Legacy tkinter/PyQt6 chat UI

Hard-disabled stubs that remain at their original paths
-------------------------------------------------------
The following modules remain at ``windows_client/`` (not here) because tests
verify their hard-disabled behaviour.  They raise ``RuntimeError`` on import:

- ``windows_client.client``             — Legacy bespoke Gateway/AIP client
- ``windows_client.ui_sidebar``         — Legacy Tk chat sidebar
- ``windows_client.desktop_automation`` — Legacy pyautogui automation path
- ``windows_client.windows_mcp_server`` — Legacy MCP stdio execution path
- ``windows_client.main``               — Legacy F12-hotkey chat/sidebar client
- ``windows_client.windows_client_integrated`` — Legacy PyQt6 integrated client
- ``windows_client.key_listener``       — Legacy F12 hotkey listener

Active Windows direction
------------------------
- :mod:`core.desktop_presence_runtime` — ``DesktopPresenceRuntime``
  (desktop tri-state lifecycle shell: silent / liminal / manifest)
- :mod:`windows_client.status_board_v2` — projection-driven desktop status
  surface (read-only, consumes ``GET /api/v1/projection/runtime``)
- :mod:`windows_client.windows_aip_client` — Windows device ingress
  (``WindowsExecutionArbiter.route_command()``)

See ``docs/WINDOWS_EXECUTION_PIPELINE.md`` for the current architecture.
"""
