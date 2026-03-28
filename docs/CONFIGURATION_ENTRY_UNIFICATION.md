# Configuration Entry Unification

> **Canonical architectural contract** — this document unifies the semantics
> of configuration entry points across the Galaxy runtime.  All docs, surfaces,
> and node contracts must reference configuration using the vocabulary and
> ownership boundaries defined here.
>
> **PR-3 update:** The unified local configuration authority is now
> **implemented**.  The canonical persistence targets, core modules, and entry
> surface are defined in §2A below.  See also
> [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md).
>
> **PR-4 update:** Persisted configuration now **drives runtime provider
> availability**.  The unified config authority is wired into the provider
> inventory and routing candidate-pool formation path.  Configuration changes
> materially affect which providers are considered present, enabled, or absent.
> See §2B below.

---

## 1. Configuration Ownership Tiers

Galaxy configuration is split into **three ownership tiers**:

| Tier | Owner | Description |
|------|-------|-------------|
| **System-level** | `core/unified_config.py` (`UnifiedConfig`) | Global runtime defaults and cross-cutting settings shared by all subsystems |
| **Surface-local** | Individual surface modules | Surface-specific tuning values (poll interval, display options, etc.) that do not affect other subsystems |
| **Node-local** | `templates/node_template/` | Per-node overrides applied only within the boundary of a single node container |

No tier may claim authority over another tier's canonical keys.

---

## 2. Canonical Entry Points

### 2A. Local unified configuration authority (PR-3 — implemented)

The unified local configuration authority is implemented.  The two canonical
persistence targets are:

| Target | Purpose |
|--------|---------|
| `runtime/config.json` | Non-secret system configuration — provider profiles, routing preferences, topology overrides, feature flags |
| `runtime/secrets.env` | Secrets — provider API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, OneAPI token, etc.) |

**Core modules (PR-3):**

| Module | Role |
|--------|------|
| `core/config_schema.py` | Schema constants, known keys, secret/non-secret classification, defaults |
| `core/config_store.py` | Low-level I/O — reads/writes `runtime/config.json` + `runtime/secrets.env`, produces the effective merged view |
| `core/config_service.py` | High-level API — `set_provider_api_key`, `set_toggle`, `set_native_mm_policy`, `set_oneapi`, `validate`, `describe_missing` |

**Example templates** (safe to commit):

- `runtime/config.example.json` — non-secret config template
- `runtime/secrets.example.env` — secret key template

Copy these to `runtime/config.json` and `runtime/secrets.env` and fill in
your values.  The real files are `.gitignore`d.

**Invariants:**

- `runtime/config.json` must be machine-readable structured JSON loaded by
  `core/unified_config.py`.
- `runtime/secrets.env` must follow the same naming conventions as the root
  `.env` / environment (see §3).
- Changes to `runtime/config.json` or `runtime/secrets.env` are
  **system-wide inputs** — they affect provider inventory, routing candidate
  pool, projection output, and status-board topology.  They are not surface-
  local state.
- The `.env` file at the repository root continues to be accepted for
  deployment-mode overrides and CI.  The `runtime/` targets are the canonical
  operator-entry persistence layer during active operation.

**Future operator-facing entry surface:**  Configuration entry through an
interactive UI will be provided by `windows_client/status_board_v2/` in a
future PR (Phase D of the dashboard migration).  Status-board-entered
configuration must write to `runtime/config.json` / `runtime/secrets.env`
and must have system-wide effect.  It must not be stored as surface-local
state.  See [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md).

> **Implementation note:** The config entry UI inside `status_board_v2` is
> **not implemented in this PR**.  This section documents the architectural
> direction so that future implementation PRs have a clear contract to target.

---

### 2B. Config-authority-driven provider inventory (PR-4 — implemented)

The unified config authority is now **wired into the runtime provider
inventory and routing candidate-pool formation path**.  Persisted
configuration materially changes which providers are considered present,
enabled, or absent in the system.

**New module (PR-4):**

| Module | Role |
|--------|------|
| `core/model_topology/inventory_from_config.py` | Builds `ProviderInventory` from `ConfigService` state; applies config-authority flags to entries |

**New inventory entry fields (PR-4):**

Each `ProviderInventoryEntry` now carries config-authority-driven participation
flags:

| Field | Type | Meaning |
|-------|------|---------|
| `config_enabled` | `bool` | Provider is enabled in `runtime/config.json` |
| `config_has_key` | `bool` | Required secret(s) present (env-var or `runtime/secrets.env`) |
| `config_source` | `str` | Authority layer that set these flags (`"config_authority"`, `"env"`, `"unknown"`) |
| `is_candidate_eligible` | `bool` (property) | `config_enabled AND config_has_key` — routing gate |

**New inventory filtering methods (PR-4):**

| Method | Returns |
|--------|---------|
| `ProviderInventory.candidate_pool_entries()` | Entries eligible for routing (enabled + has key) |
| `ProviderInventory.enabled_entries()` | Entries that are enabled (key may be absent) |
| `ProviderInventory.disabled_entries()` | Entries that are explicitly disabled |
| `ProviderInventory.unconfigured_entries()` | Entries enabled but missing required key |

**Candidate-pool semantics (PR-4):**

- **Enabled + key present** → appears in candidate pool (`candidate_pool_entries()`)
- **Disabled** → excluded from candidate pool; visible in diagnostic view
- **Enabled, key absent** → excluded from candidate pool; visible as *unconfigured*

**OneAPI absent/configured semantics (PR-4):**

- `oneapi_state == "absent"` → OneAPI is treated as **absent** from the
  candidate pool.  It is still visible in diagnostic/inventory views.
  This is the default when no OneAPI configuration is present.
- `oneapi_state == "configured"` → OneAPI may enter the candidate pool
  according to existing lower-horizon semantics.
- `oneapi_state == "partial"` → OneAPI is enabled in config but missing
  key or `base_url`; treated as unconfigured (not in candidate pool).

**Key invariants after PR-4:**

- Filling in `runtime/config.json` / `runtime/secrets.env` now has immediate
  effect on provider availability at the inventory layer.
- `TopologyRouter` continues to be the sole routing decision-maker; it
  consumes the config-authority-driven `ProviderInventory` as input.
- OneAPI is not promoted to a top-layer direct peer even when configured.
  Its lower-horizon position is preserved.

### 2.1 Primary runtime configuration

```
config.json           — structured runtime config (machine-readable)
.env / environment    — secret keys and deployment-mode overrides
```

`config.json` is the **canonical structured configuration file**.  It is read
by `core/unified_config.py`.  Do not add parallel config files that duplicate
its keys.

The `.env` file (or environment variables) carries **secrets and deployment
overrides only**:

- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. — LLM provider credentials
- `GALAXY_API_TOKEN` — bearer token for REST / WS authentication
- `GALAXY_AUTH_ENABLED` — auth enforcement toggle
- `GALAXY_MODE` — `production` / `development` / `testing`

See [`docs/CONFIG_GOVERNANCE.md`](CONFIG_GOVERNANCE.md) for the full variable
matrix.

### 2.2 Pre-flight validation

```bash
python -m core.config_preflight --mode all
```

`core/config_preflight.py` is the **canonical pre-flight validator**.  It must
be run before starting any server in production.  No surface or adapter should
duplicate this logic.

### 2.3 Status-board-facing configuration

The status board (`windows_client/status_board_v2/`) currently accepts only
**read-only display parameters**:

| Parameter | Source | Description |
|-----------|--------|-------------|
| `--host` | CLI arg | Galaxy server host (default `127.0.0.1`) |
| `--port` | CLI arg | Galaxy server port (default `8000`) |
| `--interval` | CLI arg | Poll interval in seconds (default `1.0`) |
| `--file` | CLI arg | Read projection from a JSON file (offline / testing) |
| `--stdin` | CLI arg | Read projection from stdin |
| `--no-color` | CLI arg | Disable ANSI colour output |

These parameters do **not** affect system state.  They are surface-local
tuning values and must not be stored in `config.json` or `runtime/config.json`.

**Future direction (Phase D):**  `windows_client/status_board_v2/` will
become the **sole desktop configuration entry surface**, providing an
interactive UI for writing to the local unified configuration authority
(`runtime/config.json` / `runtime/secrets.env`).  When that UI is
implemented, configuration entered through the status board must have
system-wide effect — it must not be stored as per-surface local state.
See [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md).

### 2.4 OneAPI-facing configuration

OneAPI configuration references a **lower-layer aggregator**, not a direct
provider.  It is described in the projection as `oneapi_source` and must not
be promoted to a first-class routing authority.

See [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) for the
canonical position of OneAPI in the routing hierarchy.

---

## 3. Configuration Naming Conventions

| Convention | Rule |
|------------|------|
| Environment variable prefix | `GALAXY_` for all Galaxy-specific vars |
| LLM provider keys | `<PROVIDER>_API_KEY` pattern (e.g., `OPENAI_API_KEY`) |
| Boolean toggles | `_ENABLED` suffix (e.g., `GALAXY_AUTH_ENABLED`) |
| Mode selectors | `_MODE` suffix (e.g., `GALAXY_MODE`) |
| Node-local overrides | Prefixed with `NODE_` in node config files |

---

## 4. What Must Not Happen

- Do not add a second `config.json` at a sub-directory level that overrides
  system-level keys without explicit namespace isolation.
- Do not describe configuration entry points inside surface documentation as
  if they are system-level authorities.
- Do not mix secret keys (`*_API_KEY`, `GALAXY_API_TOKEN`) into `config.json`
  or `runtime/config.json`.  Secrets belong in the environment / `.env` /
  `runtime/secrets.env` only.
- Do not add `--config` flags to surface CLIs that read system-level config.
  Surface CLIs accept only surface-local parameters (see §2.3).
- Do not introduce a new configuration authority without registering it in
  `core/unified_config.py` and documenting it here.
- Do not implement a new operator-facing configuration UI that targets any
  surface other than `windows_client/status_board_v2/`.  The dashboard
  frontend is retired as a configuration entry surface.
- Do not store system configuration written through the status board as
  per-surface local state.  Status-board-entered configuration must write to
  the local unified configuration authority targets (`runtime/config.json` /
  `runtime/secrets.env`) and have system-wide effect.

---

## 5. Legacy Configuration Residue

The following legacy configuration paths are retained for compatibility only:

| Legacy path | Canonical replacement | Notes |
|-------------|-----------------------|-------|
| `dashboard/backend/main.py` config routes | `core/api_routes.py` | Legacy management panel; must not be extended |
| `core/multi_llm_router.py` provider selection | `core/model_topology/topology_router.py` | Routing authority is `CANONICAL_ROUTING_AUTHORITY` |

---

## 6. Cross-References

- [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md) — ADR freezing `status_board_v2` as sole desktop config entry surface
- [`docs/CONFIG_GOVERNANCE.md`](CONFIG_GOVERNANCE.md) — full configuration variable matrix
- [`docs/DESKTOP_SEMANTIC_CLOSURE.md`](DESKTOP_SEMANTIC_CLOSURE.md) — tri-state desktop semantics
- [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) — OneAPI position in routing hierarchy
- [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) — routing authority documentation
- [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md) — dashboard retirement plan
- [`core/config_schema.py`](../core/config_schema.py) — schema constants, key classification, defaults
- [`core/config_store.py`](../core/config_store.py) — low-level I/O for runtime/config.json + runtime/secrets.env
- [`core/config_service.py`](../core/config_service.py) — high-level configuration service API
- [`core/unified_config.py`](../core/unified_config.py) — unified configuration manager (legacy layer)
- [`core/config_preflight.py`](../core/config_preflight.py) — pre-flight validation (loads runtime/secrets.env)
