# LEGACY_SURFACE

**Classification**: `LEGACY_SURFACE`

**Status**: Legacy frontend — not the primary user interaction surface.

The canonical user surface is the panel API:
- `GET /api/v1/panel/unified?mode=chat`
- `GET /api/v1/panel/user`

This frontend is retained for backward compatibility.
New clients MUST use the canonical panel endpoints.

See PR-PANEL-CANONICAL for migration guidance.
