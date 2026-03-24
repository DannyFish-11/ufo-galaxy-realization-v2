# dashboard/ — LEGACY UI SURFACE

> **Status: LEGACY / NON-PRIMARY** (demoted in PR-8, isolated in PR-4)

`dashboard/` is **not** the current active primary system surface.

## Current system surface direction

The intended outward-facing architecture is:

- **Desktop tri-state runtime layer** — `core/desktop_presence_runtime.py`
- **Desktop status board** — `windows_client/status_board_v2/`

System status truth is projection-driven:

- Canonical status projection: `GET /api/v1/projection/runtime`
- Contract: `contracts/desktop_status_projection.py` (`DesktopStatusProjection`)

## What dashboard/ is retained for

`dashboard/` is kept **temporarily** for transition-period compatibility only:

- `dashboard/backend/main.py` — legacy management convenience panel routes
  (superseded by `core/api_routes.py` as the authoritative REST API layer)
- `dashboard/frontend/` — legacy frontend static assets (non-primary UI surface)

## What dashboard/ must NOT do

- Must not define system structure
- Must not claim status authority or maintain a parallel source of truth
- Must not be treated as the architectural source of truth for system state
- Must not be the recommended or default primary user-facing surface

## Authority references

- `core/ui_surface_authority.py` — registers `dashboard/` as `LEGACY_UI`
- `core/orchestration_authority/legacy_paths.py` — PR-8 legacy path entries
- `dashboard/__init__.py` — module-level deprecation notice

## Migration

New API endpoints: add to `core/routes/` submodules, not here.
Status truth: read from `GET /api/v1/projection/runtime`.
