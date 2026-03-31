# Canonical Entrypoints

**Version:** 1.0
**Status:** Canonical — Batch PR-1
**Owner:** Architecture / Governance

---

## Purpose

This document enumerates every **canonical entrypoint** into the Galaxy-Nexus
system — both for operators starting the process and for code paths that
enter the subject core.  It also records all **deprecated/legacy entrypoints**
so that follow-on PRs can safely retire them.

---

## 1. Process Entrypoints (Startup)

### 1.1 Canonical

| Command | File | Notes |
|---------|------|-------|
| `python main.py` | `main.py` | **Preferred** — delegates via subprocess to `unified_launcher.py` |
| `python unified_launcher.py` | `unified_launcher.py` | Equivalent to `main.py`; direct launcher call |

### 1.2 Deprecated / Legacy

| Command | File | Reason | Canonical replacement |
|---------|------|--------|----------------------|
| `python start_galaxy.py` | `start_galaxy.py` (if present) | Compatibility wrapper | `python main.py` |
| `python start_l4.py` | `start_l4.py` (if present) | Compatibility wrapper | `python main.py` |
| `python galaxy_main_loop_l4.py` | `galaxy_main_loop_l4.py` | Root tombstone shim | `python main.py` |

### 1.3 Shell / Bat Launchers

| Script | Platform | Status |
|--------|----------|--------|
| `start.sh` | Linux/macOS | Development convenience — **canonical dev launcher** |
| `start.bat` | Windows | Development convenience — **canonical dev launcher** |
| `deploy/scripts/start_unified.sh` | Linux/macOS | Extended start with env setup |
| `installer/start_galaxy.bat` | Windows | Installer-bundled starter |

These scripts ultimately call `python main.py` or `python unified_launcher.py`.
They are tolerated; new platform launchers must follow this delegation pattern.

---

## 2. HTTP API Entrypoints

### 2.1 Canonical REST API

All routes served by the FastAPI app assembled in `unified_launcher.py`
(`UnifiedWebUI`), with route handlers in `core/routes/` sub-modules.

| Route prefix | Module | Notes |
|--------------|--------|-------|
| `/api/v1/` | `core/api_routes.py` + `core/routes/*` | **Canonical** |
| `/api/v1/projection/*` | `core/routes/projection.py` | Desktop status projection |
| `/api/v1/chat` | `core/routes/chat.py` | Chat ingress → `EntrypointRouter` |
| `/api/v1/devices/*` | `core/routes/devices.py` | Device management |
| `/api/v1/commands/*` | `core/routes/command.py` | Command dispatch |
| `/health` | `core/routes/health.py` (or inline) | Health check |

### 2.2 Gateway Routes

Served by `galaxy_gateway/app.py` (separate process or sub-app):

| Route prefix | Module | Notes |
|--------------|--------|-------|
| `/gateway/*` | `galaxy_gateway/routes/*` | Gateway-scoped device/task/chat routes |
| `/ws/device/{id}` | `galaxy_gateway/routes/websocket.py` | Device WebSocket |

### 2.3 Legacy / Deprecated Routes

| Route | File | Status |
|-------|------|--------|
| Dashboard management routes | `dashboard/backend/main.py` | **LEGACY** — headless, retirement pending |

---

## 3. WebSocket Entrypoints

| Endpoint | Handler | Status |
|----------|---------|--------|
| `/ws/device/{device_id}` | `galaxy_gateway/routes/websocket.py` | CANONICAL |
| `/ws/status` | `core/api_routes.py` or inline | CANONICAL (status push) |

---

## 4. Subject-Core Code Entrypoints

### 4.1 Canonical request ingress path

```
All request sources (HTTP, WS, Android AIP, internal)
   └─► core/unified/entrypoint_router.py  (EntrypointRouter)
          └─► core/openclawd.py  (OpenClawd.handle_chat / handle_command)
```

Every external request MUST pass through `EntrypointRouter` so that
`entry_path`, `via_legacy_adapter`, and `trace_id` are stamped before
any business logic runs.

### 4.2 Internal / direct callers (legacy pattern — do not add new ones)

Direct calls to `core/openclawd.handle_chat()` bypassing `EntrypointRouter`
are a legacy pattern.  All existing cases are tracked in
`core/legacy_adapters/` and will be migrated by Batch PR-5.

---

## 5. Deployment Surface Entrypoints

| Surface | File | Notes |
|---------|------|-------|
| Docker (main) | `Dockerfile` | Builds the primary service image |
| Docker (gateway) | `Dockerfile.gateway` | Builds the gateway sub-service image |
| Docker Compose (dev) | `docker-compose.yml` | Single-host development stack |
| Docker Compose (production) | `deploy/compose/production.yml` | Production-grade overrides |
| Docker Compose (full) | `deploy/compose/full.yml` | 130-node complete system |
| Makefile | `Makefile` | Developer shortcuts |
| systemd unit | `systemd/` | Linux daemon deployment |

---

## 6. Android Entrypoints

| Path | File | Status |
|------|------|--------|
| AIP v3 message ingress | `galaxy_gateway/routes/websocket.py` | CANONICAL |
| AIP v2 compat | `galaxy_gateway/protocol/compat.py` | LEGACY compat layer |
| Android bridge (monolith) | `galaxy_gateway/android_bridge.py` | LEGACY — partially migrated to `galaxy_gateway/android/` |
| Granular adapter | `galaxy_gateway/android_granular_adapter.py` | ACTIVE — targeted for merge into `android/` package |

---

## 7. Windows Desktop Entrypoints

| Surface | File | Status |
|---------|------|--------|
| Status board v2 | `windows_client/status_board_v2/` | **CANONICAL** operator surface |
| Legacy status board | `windows_client/status_board.py` | LEGACY |
| MCP server | `windows_client/windows_mcp_server.py` | ACTIVE |
| AIP client | `windows_client/windows_aip_client.py` | ACTIVE |

---

## 8. Policy

1. **No new root-level entrypoints** may be added without updating this document.
2. **No new bypass paths** into `OpenClawd` may be added without an approved adapter in `core/legacy_adapters/`.
3. **Deprecated entrypoints** listed above may not receive new feature code.
4. New deployment targets must be based on existing `Dockerfile` / Compose patterns and listed here.
