# dashboard/frontend/ — LEGACY FRONTEND SURFACE

> **Status: LEGACY / NON-PRIMARY** (demoted in PR-8, isolated in PR-4)

`dashboard/frontend/` is **not** the current active primary UI surface.

## Current system surface direction

The current outward-facing runtime model is:

- **Desktop tri-state runtime layer** (`core/desktop_presence_runtime.py`)
- **Desktop status board** (`windows_client/status_board_v2/`)

The frontend in this directory is a historical web UI that is **no longer
the primary system surface**.  It is preserved here only as a transitional
legacy artifact.

## What this directory contains

- `package.json` / `ts/` — legacy TypeScript/React frontend source
- `public/` — legacy static assets (if built)
- `dist/` — legacy build output (if present)

None of these files participate in the current active runtime path.
The Galaxy API server (`unified_launcher.py`) no longer requires this
frontend to be built in order to function.

## Do not build or deploy this frontend as primary UI

Do not run `npm install && npm run build` here expecting to get the
current primary system UI.  This is a legacy surface.

## Authority references

- `core/ui_surface_authority.py` — `dashboard/` registered as `LEGACY_UI`
- `dashboard/LEGACY_SURFACE.md` — parent directory legacy notice
- `dashboard/__init__.py` — module-level deprecation notice (PR-8)
