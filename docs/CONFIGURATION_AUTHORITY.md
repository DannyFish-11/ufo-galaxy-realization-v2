# Galaxy — Configuration, Port, and Startup Authority

> **One-stop reference** for understanding which module or file owns each
> piece of Galaxy's configuration and startup logic.
>
> For the environment-variable reference see `docs/CONFIG_GOVERNANCE.md`.
> For the port registry and startup modes see `docs/UNIFIED_STARTUP.md`.

---

## Table of contents

1. [Configuration authority stack](#1-configuration-authority-stack)
2. [Config source precedence](#2-config-source-precedence)
3. [Port authority](#3-port-authority)
4. [Startup authority](#4-startup-authority)
5. [Compatibility facades — what they are and what they are not](#5-compatibility-facades)
6. [Quick-start reading map](#6-quick-start-reading-map)

---

## 1. Configuration authority stack

The canonical configuration authority is a layered stack:

```
┌─────────────────────────────────────────────────────────────────────┐
│  core/config_schema.py     Schema constants, key classification,    │
│                            defaults (data-only, no I/O)            │
├─────────────────────────────────────────────────────────────────────┤
│  core/config_store.py      Low-level I/O                           │
│                            • runtime/config.json  (non-secret)     │
│                            • runtime/secrets.env  (secrets)        │
├─────────────────────────────────────────────────────────────────────┤
│  core/config_service.py    High-level API                          │
│                            set_provider_api_key(), set_toggle(),   │
│                            set_oneapi(), validate()                │
├─────────────────────────────────────────────────────────────────────┤
│  core/config_preflight.py  Pre-flight validation before startup    │
│                            Loads runtime/secrets.env → os.environ  │
├─────────────────────────────────────────────────────────────────────┤
│  core/config_hot_reload.py Live reload on file change              │
│                            Version tracking, subscriber callbacks  │
└─────────────────────────────────────────────────────────────────────┘
```

**All writes to provider settings and API keys must go through
`ConfigService` (or `ConfigStore` for low-level access).** They must
never be written directly to `config.json` (root level) or `.env`.

### Canonical persistence targets

| File | Contains | Managed by |
|------|----------|-----------|
| `runtime/config.json` | Non-secret runtime config (`providers.*`, `routing.*`) | `ConfigStore` / `ConfigService` |
| `runtime/secrets.env` | Secret values (API keys, tokens) | `ConfigStore` / `ConfigService` |

Both files are **`.gitignore`d**.  Commit only the `*.example.*` templates.

### Static application config

`config.json` (repository root) is the **static application defaults** file.
It contains app-level settings such as `web_ui_port`, `log_level`,
`default_llm_model`, and feature-enable flags.  It is not a secrets file and
is safe to commit.  It is read by `core/unified_config.py` (see §5).

---

## 2. Config source precedence

When the same key appears in multiple sources the following order applies
(**highest priority first**):

| Priority | Source | Module/file |
|----------|--------|-------------|
| 1 (highest) | Process environment variables (`os.environ`) | CLI / Docker / CI overrides |
| 2 | `runtime/secrets.env` | `ConfigStore.read_secrets()` |
| 3 | `runtime/config.json` | `ConfigStore.read_config()` |
| 4 | `.env` (legacy) | `UnifiedConfig._load_env()` fallback |
| 5 (lowest) | `config.json` (root, static) | `UnifiedConfig._load_config()` |

**Rule of thumb**:
- Set API keys and secrets via `ConfigService.set_provider_api_key()` — they
  land in `runtime/secrets.env`.
- Set provider-enable toggles via `ConfigService.set_toggle()` — they land in
  `runtime/config.json`.
- Set static app preferences (log level, model names) in `config.json` (root).
- Override anything at deploy time with environment variables.

### Pre-flight check

`core/config_preflight.run_preflight()` is called by `unified_launcher.py`
before the runtime starts.  It loads `runtime/secrets.env` into `os.environ`
(without overwriting already-set env vars) so the rest of startup can read
secrets transparently.

```bash
# Run manually
python -m core.config_preflight --mode all
```

---

## 3. Port authority

**Single source of truth: `config/unified_ports.yaml`**

All port assignments for all 130 nodes and infrastructure services are
defined in this file.  The Python accessor is `core.port_config`:

```python
from core.port_config import get_node_port, get_service_port

port = get_node_port("Node_50_Transformer")     # → 8050
redis = get_service_port("redis")               # → 6379
launcher = get_service_port("unified_launcher") # → 8299
```

### Port override at runtime

Environment variables override the YAML values at the highest priority:

```bash
export GALAXY_PORT_NODE_50_TRANSFORMER=9050   # override a node port
export GALAXY_REDIS_PORT=6380                 # override infrastructure port
```

### Deprecated port sources

The following files contain **stale** port data and must not be used for
authoritative port lookups.  Refer to `config/unified_ports.yaml` instead:

| File | Status |
|------|--------|
| `config/unified_config.json` (node port fields) | Stale — use `core.port_config` |
| `config/topology.json` (api_url fields) | Stale — use `core.port_config` |
| `config/l4_config.json` (gateway.port field) | Stale — use `core.port_config` |
| `launcher/config_manager.py` (hardcoded defaults) | Deprecated — see module header |

---

## 4. Startup authority

### Process entrypoint

**`main.py`** is the canonical process entrypoint.

It performs minimal bootstrap (Python path setup, logging) and delegates
unconditionally to `unified_launcher.py`.  It does **not** contain business
logic or startup decisions beyond routing to the setup wizard when
`--setup` is requested.

### Orchestration entrypoint

**`unified_launcher.py`** is the canonical startup orchestration entrypoint.

Its responsibilities:
1. Load `SystemConfig` (via `launcher/bootstrap.py`) — reads from `UnifiedConfigManager`
   which merges canonical + legacy sources (see §2)
2. Run `core.config_preflight` — validate critical env vars before proceeding
3. Start infrastructure services (NATS, Redis, etc.)
4. Launch core runtime (`OpenClawd` + `DesktopPresenceRuntime`)
5. Start the unified API gateway (FastAPI / uvicorn)
6. Write `runtime/entrypoint.json` — client discovery file
7. Handle graceful shutdown

### Startup wrapper scripts

The following scripts are **bootstrap wrappers**.  They prepare the process
environment (Python venv, NATS, dependencies) and then invoke
`unified_launcher.py`.  They have no startup authority of their own:

| Script | Role |
|--------|------|
| `start.sh` | Linux/macOS bootstrap → installs deps, starts NATS, invokes `unified_launcher.py` |
| `start_unified.sh` | Alternate Linux bootstrap → same as `start.sh` |
| `start.bat` | Windows bootstrap → same role |
| `deploy.sh` | Production deployment via Docker Compose, or local mode via `unified_launcher.py` |

### `system_manager.py`

`system_manager.py` is a **node lifecycle manager**, not a startup authority.
It manages the start/stop/health of individual node processes.  It reads node
metadata from `config/unified_config.json` but defers port resolution to
`core.port_config` (canonical source: `config/unified_ports.yaml`).

---

## 5. Compatibility facades

The following modules exist for backward compatibility.  They are
**facades** — they do not maintain their own configuration truth:

### `core/unified_config.py`

**Role**: Compatibility facade; provides the legacy `config` singleton used
by many modules via `from core.unified_config import config`.

**How it works**:
1. Loads `config.json` (root) into `_config` — static app config (lowest priority)
2. Loads `runtime/config.json` and `runtime/secrets.env` via `ConfigStore` — canonical sources (overrides step 1)
3. Loads `.env` — legacy user file (overrides step 2 where overlapping)
4. Loads `os.environ` — highest priority (overrides everything)

The module also exports `get_config()` and re-exports `UnifiedConfigManager`
for callers that use those names directly.

### `core/unified/config_manager.py` (`UnifiedConfigManager`)

**Role**: Compatibility facade; wraps `UnifiedConfig` and exposes a typed
get/set/save/reload API.  Its backend (`UnifiedConfig`) merges all sources
as described above.

### `launcher/config_manager.py`

**Status**: **Deprecated** (see module header).  Port data is stale.
Use `core.port_config.get_node_port()` for port lookups and
`core.unified.config_manager.get_unified_config_manager()` for general config.

---

## 6. Quick-start reading map

| I need to … | Use |
|-------------|-----|
| Set / read API keys and secrets | `ConfigService.set_provider_api_key()` / `ConfigStore.read_secrets()` |
| Enable / disable a provider | `ConfigService.set_toggle()` |
| Read any config value (legacy compat) | `from core.unified_config import config; config.get(key)` |
| Look up a node port | `core.port_config.get_node_port("Node_XX_Name")` |
| Look up an infrastructure port | `core.port_config.get_service_port("redis")` |
| Validate config before startup | `core.config_preflight.run_preflight()` |
| Start the system | `python main.py` (delegates to `unified_launcher.py`) |
| Start via shell | `./start.sh` or `./start_unified.sh` (delegates to `unified_launcher.py`) |
| Manage individual nodes | `python system_manager.py` |

---

*See also*:
- `docs/CONFIG_GOVERNANCE.md` — full environment variable reference
- `docs/UNIFIED_STARTUP.md` — port registry and Docker startup modes
