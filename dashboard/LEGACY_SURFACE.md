# LEGACY_SURFACE

**Classification**: `LEGACY_SURFACE`

**Status**: Legacy — not the primary operator/user interaction surface.

The canonical operator/user surfaces are:
- `GET /api/v1/panel/unified` — UnifiedPanelPayload (all roles)
- `GET /api/v1/panel/operator` — Operator-only projection
- `GET /api/v1/panel/user` — User-only projection

This dashboard directory is retained for backward compatibility.
New clients MUST consume the canonical panel endpoints above.

See PR-PANEL-CANONICAL for migration guidance.
