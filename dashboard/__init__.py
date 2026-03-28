"""dashboard — LEGACY UI SURFACE / LEGACY HEADLESS BACKEND (frontend fully retired in PR-1)
=============================================================================================

.. deprecated:: PR-1
   ``dashboard/frontend/`` has been **permanently deleted**.  There is no
   web operator-facing surface here.  ``dashboard/backend/main.py`` is
   retained temporarily as a headless migration/compatibility backend only
   and must not be treated as the active system surface.

   The PR-8 ``LEGACY UI SURFACE`` designation is retained for compatibility.
   The PR-1 designation supersedes it: the frontend has been deleted, not
   merely demoted.  Both markers remain true simultaneously.

**Architectural authority**
---------------------------
- Canonical REST API:       ``core/api_routes.py``, ``core/routes/``
- Canonical status truth:   ``GET /api/v1/projection/runtime``
                            (RuntimeProjection / DesktopStatusProjection)
- Canonical operator surface: ``windows_client/status_board_v2/``

The ``/api/v1/*`` routes defined in ``dashboard/backend/main.py`` are
historical.  In unified-launcher deployments they are superseded by the
routes in ``core/api_routes.py``.  Do not add new status-authority endpoints
here.

See ``core/ui_surface_authority.py`` for the canonical UI surface authority
registry and ``core/orchestration_authority/legacy_paths.py`` for the
legacy path registry entry.
"""
