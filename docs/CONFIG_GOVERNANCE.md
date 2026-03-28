# Galaxy — Configuration Governance (PR-G3 / PR-3)

> **Scope** — this document covers the full configuration surface for the
> Galaxy runtime, including the Galaxy Gateway, Android / WebSocket bridge,
> core LLM runtime, and the SecretVault secrets back-end.
>
> **PR-3 update:** The local unified configuration authority is now
> implemented.  See §10 for the runtime config file model.

---

## Table of contents

1. [Quick-start minimal config](#1-quick-start-minimal-config)
2. [Configuration matrix — Core runtime](#2-configuration-matrix--core-runtime)
3. [Configuration matrix — Galaxy Gateway](#3-configuration-matrix--galaxy-gateway)
4. [Configuration matrix — Android / WebSocket bridge](#4-configuration-matrix--android--websocket-bridge)
5. [Configuration matrix — SecretVault back-end](#5-configuration-matrix--secretvault-back-end)
6. [Configuration matrix — Optional features](#6-configuration-matrix--optional-features)
7. [Pre-flight check](#7-pre-flight-check)
8. [Migrating secrets to SecretVault](#8-migrating-secrets-to-secretvault)
9. [Environment variable reference (all)](#9-environment-variable-reference-all)
10. [Local unified configuration authority (runtime/)](#10-local-unified-configuration-authority-runtime)

---

## 1. Quick-start minimal config

Copy `.env.example` to `.env` and fill in **at least** these four values:

```bash
# 1. At least one LLM provider key
OPENAI_API_KEY=sk-...

# 2. A random bearer token (protects the REST + WS API)
GALAXY_API_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# 3. Enable auth enforcement (strongly recommended in production)
GALAXY_AUTH_ENABLED=true

# 4. Runtime mode
GALAXY_MODE=production
```

Then run the pre-flight check before starting the server:

```bash
python -m core.config_preflight --mode all
```

---

## 2. Configuration matrix — Core runtime

| Variable | Required | Default | Description |
|---|---|---|---|
| `GALAXY_MODE` | No | `production` | `production` \| `development` \| `testing` |
| `GALAXY_LOG_LEVEL` | No | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `OPENAI_API_KEY` | **Yes*** | — | OpenAI API key (`sk-…`). |
| `ANTHROPIC_API_KEY` | No | — | Anthropic Claude key. Required when `GALAXY_LLM_PROVIDER=anthropic`. |
| `GEMINI_API_KEY` | No | — | Google Gemini key. |
| `DEEPSEEK_API_KEY` | No | — | DeepSeek API key. |
| `GROQ_API_KEY` | No | — | Groq API key. |
| `OPENROUTER_API_KEY` | No | — | OpenRouter key (multi-model proxy). |
| `GALAXY_API_TOKEN` | **Yes** | — | Bearer token for REST + WS authentication. |
| `GALAXY_AUTH_ENABLED` | No | `false` | Set `true` to enforce bearer-token auth. |
| `GALAXY_SECRET_BACKEND` | No | `env` | `env` \| `vault` \| `kms` (see §8). |
| `PICKLE_SECRET_KEY` | No | — | HMAC key for pickle serialisation. |

> \* At least one LLM provider key is required to run agents.

### Minimal working example (core only)

```bash
OPENAI_API_KEY=sk-proj-abc123
GALAXY_API_TOKEN=super-secret-token-here
GALAXY_AUTH_ENABLED=true
GALAXY_MODE=production
```

---

## 3. Configuration matrix — Galaxy Gateway

| Variable | Required | Default | Description |
|---|---|---|---|
| `GALAXY_CROSS_DEVICE_ENABLED` | No | `1` (enabled) | Set `0` to disable cross-device routing. HTTP 403 / WS 4001 when OFF. |
| `GALAXY_TLS_CERT` | No | — | Path to TLS certificate. Both cert + key required to enable HTTPS. |
| `GALAXY_TLS_KEY` | No | — | Path to TLS private key. |
| `GALAXY_NATS_URL` | No | `nats://localhost:4222` | NATS control-plane URL. Unset → NATS disabled (no-op). |
| `GALAXY_MASTER_BRAIN_ENABLED` | No | `1` | Enable the master brain coordinator. |
| `GALAXY_TRACE_SAMPLE_RATE` | No | `1.0` | Fraction of requests to trace (0.0 – 1.0). |
| `GALAXY_ENABLE_LEGACY_PROTOCOLS` | No | `0` | Enable AIP v2 legacy protocol support. |
| `GALAXY_ENABLE_WEBRTC` | No | `1` | Enable WebRTC signalling proxy. |
| `GALAXY_ENABLE_MQTT` | No | `0` | Enable MQTT bridge. |
| `GALAXY_TRANSPORT_PRIORITY` | No | `ws` | Preferred transport: `ws` \| `nats` \| `http`. |

### Minimal working example (gateway)

```bash
GALAXY_API_TOKEN=super-secret-token-here
GALAXY_AUTH_ENABLED=true
GALAXY_CROSS_DEVICE_ENABLED=1
# TLS — leave blank for development
GALAXY_TLS_CERT=
GALAXY_TLS_KEY=
```

---

## 4. Configuration matrix — Android / WebSocket bridge

| Variable | Required | Default | Description |
|---|---|---|---|
| `GALAXY_AUTH_ENABLED` | **Yes** (prod) | `false` | Enforce token auth on all WS endpoints. |
| `GALAXY_API_TOKEN` | **Yes** (prod) | — | Token Android clients must include as `?token=<token>`. |
| `GALAXY_SIGNALING_TIMEOUT_S` | No | `30` | WebRTC signalling handshake timeout (seconds). |
| `GALAXY_STUN_URLS` | No | Google STUN | Comma-separated STUN server URLs. |
| `GALAXY_TURN_URLS` | No | — | Comma-separated TURN server URLs (for NAT traversal). |
| `GALAXY_TURN_USERNAME` | No | — | TURN server username. |
| `GALAXY_TURN_CREDENTIAL` | No | — | TURN server credential (password). |
| `GALAXY_TAILSCALE_ENABLED` | No | `0` | Enable Tailscale overlay network for device mesh. |
| `GALAXY_TAILSCALE_HOST` | No | — | Tailscale host for this node. |
| `GALAXY_ENABLE_SCRCPY` | No | `0` | Enable scrcpy screen-mirror over WS. |

### Minimal working example (Android bridge)

```bash
# Server side
GALAXY_API_TOKEN=super-secret-token-here
GALAXY_AUTH_ENABLED=true

# Android client — set WS URL in the app:
#   ws://<server-ip>:8765/ws/android?token=super-secret-token-here
```

> **Important**: Without `GALAXY_AUTH_ENABLED=true` any Android device on the
> network can send commands to the Galaxy server.

---

## 5. Configuration matrix — SecretVault back-end

| Variable | Required | Default | Description |
|---|---|---|---|
| `GALAXY_SECRET_BACKEND` | No | `env` | Back-end for `CredentialVault`: `env` \| `vault` \| `kms`. |
| `SECRETVAULT_URL` | When `vault` | `http://localhost:8003` | Base URL of Node_03 (SecretVault). |
| `SECRETVAULT_MASTER_KEY` | When `vault` | (auto-generated) | Fernet master key for Node_03 encryption. |
| `SECRETVAULT_FILE` | No | `/tmp/secretvault.json` | Persistence file path for Node_03. |

### Back-end descriptions

| Back-end | Behaviour |
|---|---|
| `env` | Default. Secrets read from environment variables; stored in process memory. No persistence beyond the process lifetime. |
| `vault` | Delegates `get`/`set` to Node_03 (SecretVault HTTP API). Encrypted at rest, audit-logged. Recommended for production. |
| `kms` | Placeholder — currently falls back to `env` with a warning. Future: AWS KMS / GCP KMS / HashiCorp Vault. |

---

## 6. Configuration matrix — Optional features

| Variable | Required | Default | Description |
|---|---|---|---|
| `GALAXY_NATS_URL` | No | — | NATS URL. Unset = NATS disabled. |
| `GALAXY_RUNTIME_URL` | No | `http://localhost:8200` | Galaxy agent-runtime URL (AgentBridge). |
| `GALAXY_RUNTIME_ENABLED` | No | `1` | Enable AgentBridge. Set `0` to disable. |
| `GALAXY_RUNTIME_TIMEOUT` | No | `30` | AgentBridge HTTP timeout (seconds). |
| `KB_VECTOR_BACKEND` | No | `local` | Vector engine: `local` \| `chroma` \| `qdrant`. |
| `GITHUB_TOKEN` | No | — | GitHub PAT (raises rate limit for skill installer). |
| `GALAXY_PLUGIN_DIR` | No | `./plugins` | Plugin directory for Node_28/29/31/32. |

---

## 7. Pre-flight check

The pre-flight checker (`core/config_preflight.py`) validates critical
environment variables before the server starts.  It prints actionable hints
for anything that is missing or still set to a placeholder value.

### Running manually

```bash
# Check all groups (recommended before first deploy)
python -m core.config_preflight --mode all

# Check only the gateway-specific variables
python -m core.config_preflight --mode gateway

# Dry-run (report only, never fail)
python -m core.config_preflight --mode all --dry-run
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All critical checks passed (warnings may still be present). |
| `1` | One or more CRITICAL variables are missing. |
| `2` | Unexpected error during the check. |

### Integrating into startup

Add the check to your entrypoint **before** importing other Galaxy modules:

```python
# galaxy_main.py (or any entrypoint)
from core.config_preflight import run_preflight
run_preflight(mode="auto", fail_fast=True)  # raises ConfigPreflightError on missing CRITICAL vars
```

### Check groups

| Group | Variables checked |
|---|---|
| `core` | `OPENAI_API_KEY`, `GALAXY_API_TOKEN` |
| `gateway` | `GALAXY_API_TOKEN`, `GALAXY_AUTH_ENABLED`, `GALAXY_CROSS_DEVICE_ENABLED`, `GALAXY_TLS_CERT`, `GALAXY_NATS_URL`, `GALAXY_RUNTIME_URL` |
| `android` | `GALAXY_AUTH_ENABLED` |
| `ws` | `GALAXY_SIGNALING_TIMEOUT_S`, `GALAXY_TLS_CERT` |
| `vault` | `SECRETVAULT_MASTER_KEY` |
| `all` | All of the above |

---

## 8. Migrating secrets to SecretVault

### Step 1 — Start Node_03

```bash
# Generate a Fernet key
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
# → base64-url-encoded key, e.g. "gAAAAAB…"

export SECRETVAULT_MASTER_KEY="<the key above>"
cd nodes/Node_03_SecretVault
uvicorn main:app --port 8003
```

### Step 2 — Select the vault back-end

In your `.env` file:

```bash
GALAXY_SECRET_BACKEND=vault
SECRETVAULT_URL=http://localhost:8003    # default
SECRETVAULT_MASTER_KEY=<the key above>  # used by Node_03, not CredentialVault directly
```

### Step 3 — Migrate existing ENV secrets

Run the one-shot migration helper:

```python
from core.credential_vault import migrate_env_to_vault

# Dry run first to see what would be migrated
results = migrate_env_to_vault(dry_run=True)
print(results)

# Actually migrate
results = migrate_env_to_vault(dry_run=False)
```

Or from the command line:

```bash
python3 -c "
from core.credential_vault import migrate_env_to_vault
results = migrate_env_to_vault()
ok = sum(v for v in results.values())
print(f'Migrated {ok}/{len(results)} credentials')
"
```

### Step 4 — Remove plain-text secrets from `.env`

After verifying that the vault is serving the credentials correctly, remove or
blank out the sensitive values in `.env`:

```bash
# Before
OPENAI_API_KEY=sk-proj-abc123

# After (key is now in SecretVault)
OPENAI_API_KEY=
```

Keep non-sensitive variables (`GALAXY_MODE`, `GALAXY_LOG_LEVEL`, etc.) in
`.env` as usual.

### Verifying the migration

```python
from core.credential_vault import get_vault
vault = get_vault()
print(vault.backend_name)           # → "vault"
print(vault.get_credential("openai"))  # should return your key from Node_03
```

### Rollback

Set `GALAXY_SECRET_BACKEND=env` and restore the API keys in `.env`.  The
vault back-end is never required — `env` mode is always the safe fallback.

---

## 9. Environment variable reference (all)

> For a complete, always-up-to-date list run:
>
> ```bash
> grep -rn "os.getenv\|os.environ.get" core/ galaxy_gateway/ \
>   --include="*.py" | grep -oP '(?<=["\x27])[A-Z][A-Z0-9_]+(?=["\x27])' | sort -u
> ```

The table below consolidates the variables most commonly needed:

| Variable | Module | Severity | Default |
|---|---|---|---|
| `GALAXY_MODE` | core | INFO | `production` |
| `GALAXY_LOG_LEVEL` | core | INFO | `INFO` |
| `GALAXY_API_TOKEN` | core / gateway | **CRITICAL** | — |
| `GALAXY_AUTH_ENABLED` | core / gateway | WARNING | `false` |
| `GALAXY_SECRET_BACKEND` | core | INFO | `env` |
| `OPENAI_API_KEY` | core | WARNING | — |
| `ANTHROPIC_API_KEY` | core | WARNING | — |
| `SECRETVAULT_MASTER_KEY` | Node_03 | WARNING | (generated) |
| `SECRETVAULT_URL` | core | INFO | `http://localhost:8003` |
| `GALAXY_CROSS_DEVICE_ENABLED` | gateway | INFO | `1` |
| `GALAXY_TLS_CERT` | gateway | INFO | — |
| `GALAXY_TLS_KEY` | gateway | INFO | — |
| `GALAXY_NATS_URL` | gateway | INFO | `nats://localhost:4222` |
| `GALAXY_SIGNALING_TIMEOUT_S` | gateway / ws | INFO | `30` |
| `GALAXY_RUNTIME_URL` | gateway | INFO | `http://localhost:8200` |
| `GALAXY_TRACE_SAMPLE_RATE` | gateway | INFO | `1.0` |
| `GALAXY_TRANSPORT_PRIORITY` | gateway | INFO | `ws` |
| `GALAXY_TAILSCALE_ENABLED` | gateway | INFO | `0` |
| `GALAXY_ENABLE_WEBRTC` | gateway | INFO | `1` |
| `GALAXY_ENABLE_MQTT` | gateway | INFO | `0` |
| `GALAXY_ENABLE_SCRCPY` | gateway | INFO | `0` |
| `KB_VECTOR_BACKEND` | core | INFO | `local` |
| `GITHUB_TOKEN` | core | INFO | — |

---

## 10. Local unified configuration authority (runtime/)

> **Implemented in PR-3.**

The canonical local persistence targets for operator-entered configuration are:

| File | Contains | Module |
|------|----------|--------|
| `runtime/config.json` | Non-secret system configuration | `core/config_store.py` |
| `runtime/secrets.env` | Secret values (API keys, tokens) | `core/config_store.py` |

Both files are **`.gitignore`d**.  Commit only the `*.example.*` templates.

### Quick start

```bash
# 1. Copy the templates
cp runtime/config.example.json runtime/config.json
cp runtime/secrets.example.env runtime/secrets.env

# 2. Edit runtime/config.json — enable/disable providers, set routing policy
# 3. Edit runtime/secrets.env — fill in your API keys

# 4. Validate
python -m core.config_preflight --mode all
```

### Core module reference

| Module | Role |
|--------|------|
| `core/config_schema.py` | Schema constants, key classification (`classify_key`), defaults (`ConfigDefaults`) |
| `core/config_store.py` | Low-level I/O; `read_config()`, `read_secrets()`, `write_config()`, `write_secret()`, `get_effective_config()` |
| `core/config_service.py` | High-level API: `set_provider_api_key()`, `set_toggle()`, `set_native_mm_policy()`, `set_oneapi()`, `validate()`, `describe_missing()` |

### Non-secret config fields (`runtime/config.json`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `providers.<id>.enabled` | bool | varies | Enable/disable a provider |
| `providers.oneapi.base_url` | string | `""` | OneAPI aggregator HTTP URL (non-secret) |
| `routing.native_multimodal_policy` | string | `"prefer"` | `"strict"` \| `"prefer"` \| `"allow_fallback"` |
| `routing.default_provider` | string | `"openai"` | Default routing target |

### Secret fields (`runtime/secrets.env`)

| Key | Provider |
|-----|----------|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` | Google Gemini |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `GROQ_API_KEY` | Groq |
| `OPENROUTER_API_KEY` | OpenRouter |
| `ONEAPI_API_KEY` | OneAPI aggregator |
| `GALAXY_API_TOKEN` | Galaxy REST / WS auth |

### Merge priority (highest → lowest)

1. Process environment variables (`os.environ`) — deployment / CI overrides
2. `runtime/secrets.env` — persisted local secrets
3. `runtime/config.json` — persisted non-secret config

### Invariants

- Secrets must **not** appear in `runtime/config.json`.  `ConfigStore.write_config()` enforces this.
- Non-secret config values must **not** appear in `runtime/secrets.env`.  `ConfigStore.write_secret()` enforces this.
- `core/config_preflight.py` automatically loads `runtime/secrets.env` before running checks.

### Future direction

Interactive configuration entry via `windows_client/status_board_v2` is planned for Phase D.
When that UI is implemented, all writes must target `runtime/config.json` / `runtime/secrets.env`
through `core/config_service.ConfigService`.  This PR provides the store/service foundation;
the UI surface is out of scope for PR-3.
