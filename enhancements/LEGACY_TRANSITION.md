# enhancements/ — LEGACY TRANSITION DIRECTORY

> **Status: TRANSITIONAL** (classified PR-8-layout)
>
> Role: `TRANSITIONAL`

`enhancements/` is a **transitional directory** containing enhancement overlays,
bridges, and adapter modules that were developed alongside the core system.

## Current state

Most sub-modules in `enhancements/` provide bridges or perception adapters that
are candidates for integration into `core/` or retirement.

The following path is **hard-disabled** (PR-3):

| Path | Status |
|------|--------|
| `enhancements/clients/windows_client/run_ui.py` | **HARD-DISABLED** — targeted the retired legacy chat/sidebar client. Raises `DeprecationWarning` on import. |

## Active Windows direction

The canonical Windows-facing runtime assets are:

- `core/desktop_presence_runtime.py` — `DesktopPresenceRuntime` (tri-state lifecycle)
- `windows_client/status_board_v2/` — canonical read-only desktop status surface
- `windows_client/autonomy/` — active Windows automation layer

## What this directory must NOT do

- Must not define the primary desktop interaction philosophy
- Must not maintain a parallel source of truth for system state
- Must not be treated as the canonical replacement for `core/`
- Clients sub-directory (`enhancements/clients/`) must not be revived for
  legacy Windows client use cases

## Migration guidance

New enhancement logic should be integrated directly into `core/` rather than
added here.  If a sub-module in `enhancements/` has proven stable and canonical,
it should be promoted into `core/` and this directory entry updated accordingly.

## Authority references

- `core/repo_layout_registry.py` — classifies `enhancements/` as `TRANSITIONAL`
- `core/ui_surface_authority.py` — surface authority registry
- `core/orchestration_authority/legacy_paths.py` — legacy path entries
- `docs/REPO_LAYOUT.md` — full repository layout overview
