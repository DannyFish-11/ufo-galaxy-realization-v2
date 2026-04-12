# Product Readiness Audit — Desktop Status Board Positioning

## Desktop status board role (authoritative)

The desktop status board (`windows_client/status_board_v2/`) is **not** merely
read-only or passive observation. It is an **operator-facing runtime surface**
with real operational attributes.

It combines:

- runtime-state projection (`GET /api/v1/projection/runtime`)
- bounded operational control surfaces exposed at the desktop runtime layer

## Truthful boundaries

- The current control scope is intentionally bounded/scoped/staged.
- That bounded scope is a limit of currently exposed authority, **not** a denial
  of operational role.
- Canonical chat ingress remains API-first (`POST /api/v1/chat`); the board does
  not replace that ingress path.
- The board should not be described as having unbounded execution authority.
