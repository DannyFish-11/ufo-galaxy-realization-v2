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
| `GALAXY_SYSTEM_MODE` | `desktop-local` | `desktop-local` \| `desktop-cross-device` | Mode selector. The panel's 「跨设备」 button writes it together with `GALAXY_CROSS_DEVICE_ENABLED`. See *Config Precedence* — one rule decides the mode. |
| `GALAXY_NATS_ENABLED` | derived | `false` \| `true` | Override NATS activation. Defaults to `false` in `desktop-local`, `true` in `desktop-cross-device`. |
| `GALAXY_NATS_URL` | _(empty)_ → `nats://localhost:4222` | any URL | NATS server URL. Setting this also implicitly enables NATS. It says *where* the bus is — it never changes the mode. |
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

There are exactly two modes, and **one rule** (`core.system_mode.cross_device_requested`) decides which one the
system is in. The gateway switch, the startup orchestrator, the desktop presence runtime, the startup health check and
`/api/v1/system/mode-status` all call it; none derives the answer again.

The system is in `desktop-cross-device` when **either**

1. `GALAXY_SYSTEM_MODE=desktop-cross-device`, **or**
2. `GALAXY_CROSS_DEVICE_ENABLED=true/1/yes/on`

— otherwise `desktop-local`. "Local" and "false" are the factory defaults (`.env.example` ships them and "save
settings" writes them), so seeing one of them in a file is not a choice and never overrides an explicit opt-in on the
other key. The panel's 「跨设备」 button writes both keys together (`mirrors` in `core/routes/config_bundles.py`), so
turning it off really turns both off.

`GALAXY_NATS_URL` does **not** take part: pointing the bus at another machine while in local mode makes startup say so
("当前是本地模式，要用别的设备请打开跨设备"), but never switches the mode.

The master brain (`GALAXY_MASTER_BRAIN_ENABLED`) and its worker only start in cross-device mode
(`core.system_mode.master_brain_requested`); switched on in local mode they stay off and startup says why.

An agent may *ask* the user to turn cross-device mode on (`devices__request_cross_device`, local mode only); only the user can
approve it — see `core/device_onboarding/mode_request.py`.

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
