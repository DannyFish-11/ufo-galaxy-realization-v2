# Galaxy — System Mode Configuration Baseline

> **Canonical reference**: `core/system_mode.py`

## Overview

Galaxy distinguishes between two explicit startup/fabric modes so that
`desktop-local` startup does not block on infrastructure that is only required
for cross-device operation.

| Mode | Description |
|---|---|
| `desktop-local` | **Default after clone.** Cross-device fabric not assumed. NATS not required. |
| `desktop-cross-device` | Explicit opt-in. Cross-device fabric active. NATS / control-plane in use. |

---

## Environment Variables (canonical contract)

| Variable | Default | Values | Description |
|---|---|---|---|
| `GALAXY_SYSTEM_MODE` | `desktop-local` | `desktop-local` \| `desktop-cross-device` | Primary mode selector. All other fabric config is derived from this. |
| `GALAXY_NATS_ENABLED` | derived | `false` \| `true` | Override NATS activation. Defaults to `false` in `desktop-local`, `true` in `desktop-cross-device`. |
| `GALAXY_NATS_URL` | `nats://localhost:4222` | any URL | NATS server URL. Setting this also implicitly enables NATS. |
| `GALAXY_FABRIC_STRICT` | `false` | `false` \| `true` | When `true`, missing fabric deps (e.g. NATS unreachable) cause hard startup failure. |
| `GALAXY_NETWORK_MODE` | `local` | `local` \| `lan` \| `tailscale` \| `relay` | Intended network topology. |
| `GALAXY_CROSS_DEVICE_ENABLED` | derived | `false` \| `true` | Cross-device routing switch. Derived from `GALAXY_SYSTEM_MODE` when not set. |
| `GALAXY_TAILSCALE_ENABLED` | `false` | `false` \| `true` | Whether Tailscale is available on this host. |
| `GALAXY_TAILSCALE_HOST` | _(empty)_ | hostname | Tailscale hostname for this node. |
| `GALAXY_TRANSPORT_PRIORITY` | derived | comma-separated | Ordered transport preference. Defaults to `lan,internet` (local) or `tailscale,lan,internet` (cross-device). |

---

## Mode Semantics

### `desktop-local` (default)

- This is the **intended mode for first startup after clone**.
- Cross-device fabric is not assumed.
- NATS is **not implicitly required**. The system starts even when NATS is unavailable.
- `GALAXY_NATS_ENABLED` defaults to `false`.
- `GALAXY_CROSS_DEVICE_ENABLED` defaults to `false`.
- `GET /health/nats` reports `"required": false` and a graceful degradation message.

### `desktop-cross-device`

- Explicitly enabled when the user wants the background cross-device fabric.
- `GALAXY_NATS_ENABLED` defaults to `true`.
- `GALAXY_CROSS_DEVICE_ENABLED` defaults to `true`.
- Set `GALAXY_FABRIC_STRICT=true` to make NATS absence a hard failure.
- `GET /health/nats` reports `"required": true` only when `GALAXY_FABRIC_STRICT=true`.

---

## Consuming the Config

```python
from core.system_mode import resolve_fabric_config, SystemMode

cfg = resolve_fabric_config()       # reads os.environ
if cfg.mode == SystemMode.DESKTOP_CROSS_DEVICE:
    # activate fabric paths
    ...

# Or use the module-level singleton (resolved at import time):
from core.system_mode import FABRIC_CONFIG
print(FABRIC_CONFIG.nats_enabled)    # bool
print(FABRIC_CONFIG.nats_required)   # bool (True only when strict+enabled)
print(FABRIC_CONFIG.as_dict())       # JSON-serialisable dict
```

In tests, pass a custom env dict to avoid global side-effects:

```python
from core.system_mode import resolve_fabric_config

cfg = resolve_fabric_config({
    "GALAXY_SYSTEM_MODE": "desktop-cross-device",
    "GALAXY_FABRIC_STRICT": "true",
})
assert cfg.nats_required is True
```

---

## Config Precedence for Mode Derivation

When `GALAXY_SYSTEM_MODE` is **not** set:

1. `GALAXY_CROSS_DEVICE_ENABLED=true/1/yes` → inferred mode = `desktop-cross-device`
2. `GALAXY_CROSS_DEVICE_ENABLED=false/0/no` → inferred mode = `desktop-local`
3. _(absent)_ → default = `desktop-local`

`GALAXY_SYSTEM_MODE` always wins when it is explicitly provided.

---

## Backward Compatibility

All previously supported env vars (`GALAXY_NATS_URL`, `GALAXY_CROSS_DEVICE_ENABLED`,
`GALAXY_TAILSCALE_ENABLED`, `GALAXY_TAILSCALE_HOST`, `GALAXY_TRANSPORT_PRIORITY`)
continue to work.  The new `GALAXY_SYSTEM_MODE` / `GALAXY_NATS_ENABLED` /
`GALAXY_FABRIC_STRICT` / `GALAXY_NETWORK_MODE` variables are **additive**.  Systems
that do not set them continue to behave exactly as before (defaulting to
`desktop-local` with no NATS requirement).

---

## Related Modules

| Module | Role |
|---|---|
| `core/system_mode.py` | **Canonical** mode resolver — source of truth |
| `core/config_preflight.py` | Pre-flight checks for all env vars including mode vars |
| `core/routes/observability.py` | `/health/nats` uses resolved mode for `required` field |
| `galaxy_gateway/cross_device_switch.py` | Legacy `GALAXY_CROSS_DEVICE_ENABLED` switch |
| `.env.example` | Documented defaults for all canonical config vars |
