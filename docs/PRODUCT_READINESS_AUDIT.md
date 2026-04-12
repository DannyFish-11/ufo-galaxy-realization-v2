# Product Readiness Audit — Desktop Status Board Positioning

## Desktop status board role (current authoritative framing)

The desktop status board (`windows_client/status_board_v2/`) is **not merely a
passive or read-only dashboard**. It is an **operator-facing runtime surface**
with real operational attributes.

It combines:

- runtime-state projection from canonical runtime truth surfaces
- bounded operational control surfaces suitable for operator workflows
- tri-state lifecycle visibility (`silent / liminal / manifest`) tied to
  `DesktopPresenceRuntime`

## Truthful boundaries

- The board does **not** replace canonical chat ingress (`POST /api/v1/chat`).
- The board does **not** claim unbounded execution authority.
- Current exposed control scope is intentionally staged and bounded.

Those limits describe **scope of exposed authority**, not a denial of the
board's operational role.
