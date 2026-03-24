"""windows_client — HOST-SPECIFIC LEGACY SHELL
===============================================

.. deprecated:: PR-8  LEGACY SHELL
   ``windows_client/`` is a **host-specific legacy shell** (PR-8).
   It is retained for compatibility but must not:

   - Define the primary desktop interaction philosophy.
   - Act as the outward-facing system status authority.
   - Maintain a parallel authoritative state model for system status.

Active Windows direction
------------------------
The current Windows-facing runtime story is:

1. :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`
   (``core/desktop_presence_runtime.py``) — the desktop **tri-state lifecycle
   runtime shell** (silent / liminal / manifest).  This is the canonical
   Windows runtime surface.

2. :mod:`windows_client.status_board_v2` — the **canonical read-only desktop
   status surface**.  It consumes projection output from::

       GET /api/v1/projection/runtime
       contract: contracts.desktop_status_projection.DesktopStatusProjection

3. :mod:`windows_client.windows_aip_client` — Windows device ingress.
   All Windows command execution routes through::

       windows_aip_client.py → WindowsExecutionArbiter.route_command()

Retired legacy surfaces (hard-disabled, raise RuntimeError on import)
----------------------------------------------------------------------
- ``windows_client/client.py``                — legacy bespoke Gateway/AIP client
- ``windows_client/ui_sidebar.py``            — legacy Tk chat sidebar
- ``windows_client/desktop_automation.py``    — legacy pyautogui automation path
- ``windows_client/windows_mcp_server.py``    — legacy MCP stdio execution path
- ``windows_client/main.py``                  — legacy F12-hotkey chat/sidebar client
- ``windows_client/windows_client_integrated.py`` — legacy PyQt6 integrated client
- ``windows_client/key_listener.py``          — legacy F12 hotkey listener

Launchers and legacy UI assets have been moved to ``windows_client/_legacy/``.

**Canonical outward status surface**
-------------------------------------
``windows_client/status_board_v2/`` is the **canonical read-only desktop
status board**.  It consumes projection output from:

    GET /api/v1/projection/runtime
    contract: contracts.desktop_status_projection.DesktopStatusProjection

All status presentation must be driven by projection.  The legacy
``windows_client/status_board.py`` polls an ad-hoc non-projection endpoint
(``/api/v1/continuum/state``) and is superseded by ``status_board_v2/``.

See ``core/ui_surface_authority.py`` for the canonical UI surface authority
registry and ``core/orchestration_authority/legacy_paths.py`` for the
legacy path registry entry.
"""
