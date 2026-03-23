"""windows_client — HOST-SPECIFIC LEGACY SHELL
===============================================

.. deprecated:: PR-8  LEGACY SHELL
   ``windows_client/`` is a **host-specific legacy shell** (PR-8).
   It is retained for compatibility but must not:

   - Define the primary desktop interaction philosophy.
   - Act as the outward-facing system status authority.
   - Maintain a parallel authoritative state model for system status.

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
