# LEGACY SURFACE — dashboard/frontend

> **Status**: LEGACY_SURFACE (demoted by PR-4)  
> **Canonical replacement**: `core/api_routes.py`

This directory is a legacy frontend surface.  It has been demoted from the
active primary system surface as part of the PR-4 / PR-8 structural cleanup
sequence.

**Do not add new runtime logic here.**  Use `core/api_routes.py` for all
active API and routing functionality.

See `docs/ENTRYPOINT_AND_SURFACE_DEMOTION.md` and `docs/MAINTAINER_RUNBOOK.md`
§ 4 for the full demotion policy.
