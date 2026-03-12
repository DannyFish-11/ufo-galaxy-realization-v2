# Galaxy Gateway — Auth Token Key Rotation

This document describes how to rotate the Bearer auth tokens used by the
Galaxy Gateway without disrupting connected clients.

---

## Overview

The gateway supports **multiple simultaneously-active tokens** via the
`GALAXY_API_TOKENS` environment variable (comma-separated).  During a
rotation, both the outgoing and the incoming token are listed together so
that clients can migrate at their own pace before the old token is removed.

Key-rotation variables (all optional — the legacy `GALAXY_API_TOKEN` still
works):

| Variable | Description |
|---|---|
| `GALAXY_API_TOKEN` | Primary token (legacy single-token variable, backward-compatible). |
| `GALAXY_API_TOKEN_EXPIRY` | ISO-8601 UTC expiry for `GALAXY_API_TOKEN`. After this time the primary token is refused. |
| `GALAXY_API_TOKENS` | Comma-separated list of additional active tokens for rotation overlap. |
| `GALAXY_REVOKED_TOKENS` | Comma-separated list of tokens to reject immediately, even if still listed above. |

---

## Rotation Procedure (Zero-Downtime)

### Step 1 — Add the new token alongside the old one

Set `GALAXY_API_TOKENS` to include both the **old** and **new** tokens:

```bash
GALAXY_AUTH_ENABLED=true
GALAXY_API_TOKEN=old-secret-key
GALAXY_API_TOKENS=new-secret-key
```

Both tokens are valid during this **overlap window**.  Clients using the
old key continue to work.

### Step 2 — Roll out the new token to all clients

Update every client, service, and CI/CD secret to use the **new key**
(`new-secret-key`).  Verify that all traffic uses the new key before
proceeding.

### Step 3 — Remove the old token

Once all clients have migrated, remove `GALAXY_API_TOKEN` (or add it to
`GALAXY_REVOKED_TOKENS` for immediate rejection) and restart the gateway:

```bash
GALAXY_AUTH_ENABLED=true
GALAXY_API_TOKENS=new-secret-key
GALAXY_REVOKED_TOKENS=old-secret-key   # instantly revoke if needed
```

### Step 4 — (Optional) Set an expiry on the current token

If your security policy requires time-bound tokens, set
`GALAXY_API_TOKEN_EXPIRY` so the primary token is automatically rejected
after the given date, even if it is not explicitly removed:

```bash
GALAXY_API_TOKEN=current-secret-key
GALAXY_API_TOKEN_EXPIRY=2026-09-01T00:00:00Z   # UTC ISO-8601
```

When the expiry time arrives the gateway will log a warning and start
rejecting the primary token.  Ensure `GALAXY_API_TOKENS` contains a valid
replacement before the expiry date.

---

## Instant Revocation

To revoke a token immediately without restarting:

1. Add the compromised token to `GALAXY_REVOKED_TOKENS` and restart the
   gateway process (or reload the configuration):

```bash
GALAXY_REVOKED_TOKENS=compromised-token-value
```

2. Confirm the token is rejected by calling any protected endpoint with
   the old token and verifying you receive `HTTP 401`.

---

## Backward Compatibility

Existing deployments that use only `GALAXY_API_TOKEN` require **no
changes**.  The rotation variables (`GALAXY_API_TOKENS`,
`GALAXY_API_TOKEN_EXPIRY`, `GALAXY_REVOKED_TOKENS`) are all optional and
default to no-op.

---

## Verification Checklist

After completing a rotation:

- [ ] Old token returns `HTTP 401` on all gateway endpoints.
- [ ] New token returns `HTTP 200` on a protected endpoint.
- [ ] `/health` returns `HTTP 200` without any token (exempt endpoint).
- [ ] Gateway startup log shows the correct number of active tokens:
      `🔒 Bearer token auth: ENABLED (N active token(s))`.
- [ ] No errors in the gateway log related to missing or expired tokens.

---

## Related Configuration

See also:

- [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) — general environment-variable reference.
- `GALAXY_AUTH_ENABLED` — master switch; must be `true` to enforce auth.
- `GALAXY_TLS_CERT` / `GALAXY_TLS_KEY` — TLS configuration for the gateway.
