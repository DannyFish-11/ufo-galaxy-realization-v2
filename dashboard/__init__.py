"""dashboard — LEGACY UI SURFACE
================================

.. deprecated:: PR-8
   ``dashboard/`` is a **legacy UI surface**.  It is retained for
   compatibility (static-file service, management convenience panel) but is
   **not** the architectural source of truth for system state and must not be
   treated as such.

**Architectural authority**
---------------------------
- Canonical REST API:       ``core/api_routes.py``, ``core/routes/``
- Canonical status truth:   ``GET /api/v1/projection/runtime``
                            (RuntimeProjection / DesktopStatusProjection)
- Canonical status board:   ``windows_client/status_board_v2/``

The ``/api/v1/*`` routes defined in ``dashboard/backend/main.py`` are
historical.  In unified-launcher deployments they are superseded by the
routes in ``core/api_routes.py``.  Do not add new status-authority endpoints
here.

See ``core/ui_surface_authority.py`` for the canonical UI surface authority
registry and ``core/orchestration_authority/legacy_paths.py`` for the
legacy path registry entry.
"""
