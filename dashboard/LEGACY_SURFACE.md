# dashboard/ — LEGACY BACKEND (frontend fully retired in PR-1)

> **Status: LEGACY / NON-PRIMARY HEADLESS BACKEND**
> (frontend retired PR-1; backend demoted PR-8, isolated PR-4)

`dashboard/` is **not** the current active primary system surface.
**`dashboard/frontend/` has been fully deleted as of PR-1.**
There is no longer any web operator-facing management surface here.

## Current system surface direction

The intended outward-facing architecture is:

- **Desktop tri-state runtime layer** — `core/desktop_presence_runtime.py`
- **Desktop status board** — `windows_client/status_board_v2/` (sole operator-facing surface)

System status truth is projection-driven:

- Canonical status projection: `GET /api/v1/projection/runtime`
- Contract: `contracts/desktop_status_projection.py` (`DesktopStatusProjection`)

## What dashboard/ is retained for

`dashboard/backend/main.py` is kept **temporarily** for transition-period
compatibility/migration support only.  It runs **headless** — no frontend
is served.

- `dashboard/backend/main.py` — legacy management convenience panel routes
  (superseded by `core/api_routes.py` as the authoritative REST API layer)

`dashboard/frontend/` has been **permanently deleted**.  Do not recreate it.

## What dashboard/ must NOT do

- Must not define system structure
- Must not claim status authority or maintain a parallel source of truth
- Must not be treated as the architectural source of truth for system state
- Must not present or serve any web operator-facing UI surface
- Must not be the recommended or default primary user-facing surface

## Authority references

- `core/ui_surface_authority.py` — registers `dashboard/` as `LEGACY_UI`
- `core/orchestration_authority/legacy_paths.py` — PR-8 legacy path entries
- `dashboard/__init__.py` — module-level deprecation notice

## Migration

New API endpoints: add to `core/routes/` submodules, not here.
Status truth: read from `GET /api/v1/projection/runtime`.
Operator UI: use `windows_client/status_board_v2/` exclusively.
