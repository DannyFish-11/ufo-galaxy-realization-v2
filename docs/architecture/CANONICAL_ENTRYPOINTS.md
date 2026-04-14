# Canonical Entrypoints

**Version:** 1.2
**Status:** Canonical — Batch PR-5 (command routing and LLM routing decomposition)
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

Route aggregation authority: `core/api_routes.py` (`CANONICAL_API_ROUTES_AUTHORITY`)

#### Domain → Module Mapping (Batch PR-4)

| Route prefix | Module | Domain | Notes |
|--------------|--------|--------|-------|
| `/api/v1/` | `core/api_routes.py` | Aggregation | **Canonical authority** |
| `/api/v1/system/*` | `core/routes/system.py` | System | 系统状态和管理 |
| `/api/v1/devices/*` | `core/routes/devices.py` | Devices | 设备注册和管理 |
| `/api/v1/nodes/*`, `/api/v1/agent/*` | `core/routes/nodes.py` | Agents/Nodes | 节点查询和 Agent 调度 |
| `/api/v1/command/*` | `core/routes/command.py` | Commands | 命令路由引擎 |
| `/api/v1/ai/*` | `core/routes/ai.py` | AI | AI 意图理解 |
| `/api/v1/vision/*` | `core/routes/vision.py` | Vision | 视觉理解 |
| `/api/v1/tasks/*` | `core/routes/tasks.py` | Tasks | 任务管理 |
| `/api/v1/chat` | `core/routes/chat.py` | Chat | Chat ingress → EntrypointRouter |
| **`/api/v1/health/*`** | **`core/routes/health.py`** | **Health** | **统一健康管理 ★ Batch PR-4** |
| `/api/v1/monitoring/*` | `core/routes/monitoring.py` | Monitoring | 监控仪表盘 & 告警 |
| **`/api/v1/concurrency/*`** | **`core/routes/diagnostics.py`** | **Diagnostics** | **系统诊断 ★ Batch PR-4** |
| **`/api/v1/errors/*`** | **`core/routes/diagnostics.py`** | **Diagnostics** | **错误追踪 ★ Batch PR-4** |
| **`/api/v1/discovery/*`** | **`core/routes/diagnostics.py`** | **Diagnostics** | **节点发现 ★ Batch PR-4** |
| **`/api/v1/security/*`** | **`core/routes/diagnostics.py`** | **Diagnostics** | **安全审计 ★ Batch PR-4** |
| **`/api/v1/config/*`** | **`core/routes/diagnostics.py`** | **Diagnostics** | **配置管理 ★ Batch PR-4** |
| `/api/v1/relay/*` | `core/routes/relay.py` | Relay | 代理转发 |
| `/api/v1/rag/*`, `/api/v1/mesh/*` | `core/routes/hybrid.py` | Hybrid | RAG & Mesh |
| `/api/v1/vault/*` | `core/routes/vault.py` | Vault | 凭证管理 |
| `/api/v1/cost/*` | `core/routes/cost.py` | Cost | 成本追踪 |
| `/api/v1/channels/*` | `core/routes/channels.py` | Channels | 渠道插件 |
| `/api/v1/federation/*` | `core/routes/federation.py` | Federation | 多实例联邦 |
| `/api/v1/projection/*` | `core/routes/projection.py` | Projection | 运行时状态投影 |
| `/api/v1/stream` | `core/api_routes.py` (inline) | Stream | SSE 实时推送流 |

### 2.2 Gateway Routes

Served by `galaxy_gateway/app.py` (separate process or sub-app):

| Route prefix | Module | Notes |
|--------------|--------|-------|
| `/gateway/*` | `galaxy_gateway/routes/*` | Gateway-scoped device/task/chat routes |
| `/ws/device/{id}` | `galaxy_gateway/routes/websocket.py` | Device WebSocket |

### 2.3 Legacy / Deprecated Routes

| Route | File | Status | Notes |
|-------|------|--------|-------|
| Dashboard management routes | `dashboard/backend/main.py` | **LEGACY SURFACE** | Non-authoritative; shadowed by canonical API in unified deployment. Authority sentinel: `DASHBOARD_LEGACY_SURFACE_AUTHORITY` |

> **Batch PR-4 note:** `dashboard/backend/main.py` is explicitly demoted.
> Its `/api/v1/*` routes are non-authoritative compatibility routes.
> The canonical route authority is declared in `core/api_routes.py`.

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

### 4.2 Command Routing Layer (★ Batch PR-5)

Command routing is decomposed into explicit submodules under `core/commands/`:

| Module | Authority Sentinel | Responsibility |
|--------|--------------------|----------------|
| `core/commands/__init__.py` | `COMMAND_ROUTING_PACKAGE_AUTHORITY` | Package root — backward-compat re-exports |
| `core/commands/router.py` | `COMMAND_ROUTER_AUTHORITY` | Facade for `CommandRouter` + `get_command_router()` |
| `core/commands/registry.py` | `COMMAND_REGISTRY_AUTHORITY` | `CommandRegistry` — handler registration |
| `core/commands/dispatcher.py` | `COMMAND_DISPATCHER_AUTHORITY` | `CommandDispatcher` — low-level dispatch helpers |
| `core/commands/context.py` | `COMMAND_CONTEXT_AUTHORITY` | `CommandContext` — per-request execution context |
| `core/commands/middleware.py` | `COMMAND_MIDDLEWARE_AUTHORITY` | `CommandMiddleware` ABC — cross-cutting hooks |
| `core/commands/validators/` | `COMMAND_VALIDATOR_AUTHORITY` | `CommandValidator`, `EnvelopeValidator`, `RiskClassificationValidator` |
| `core/commands/handlers/` | `COMMAND_HANDLER_AUTHORITY` | `CommandHandler` ABC, `NoopHandler` |

The canonical implementation remains in `core/command_router.py`.
The `core/commands/` package provides the decomposed import surface.

### 4.3 Multi-LLM Routing Layer (★ Batch PR-5)

LLM routing is decomposed into explicit submodules under `core/llm/`:

| Module | Authority Sentinel | Responsibility |
|--------|--------------------|----------------|
| `core/llm/__init__.py` | `LLM_ROUTING_PACKAGE_AUTHORITY` | Package root — backward-compat re-exports |
| `core/llm/router.py` | `LLM_ROUTER_AUTHORITY` | Facade for `MultiLLMRouter` + `get_llm_router()` |
| `core/llm/policies.py` | `LLM_POLICIES_AUTHORITY` | Provider selection policy (`PolicyBasedSelector`, routing tables) |
| `core/llm/failover.py` | `LLM_FAILOVER_AUTHORITY` | Circuit-breaker + failover strategy (`FailoverStrategy`, `RetryPolicy`) |
| `core/llm/providers/` | `LLM_PROVIDERS_AUTHORITY` | Provider adapter classes (all `*Adapter` classes) |

The canonical implementation remains in `core/multi_llm_router.py`.
The `core/llm/` package provides the decomposed import surface.

### 4.4 Internal / direct callers (legacy pattern — do not add new ones)

Direct calls to `core/openclawd.handle_chat()` bypassing `EntrypointRouter`
are a legacy pattern.  All existing cases are tracked in
`core/legacy_adapters/`.

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
| AIP v3 message ingress | `galaxy_gateway/routes/websocket.py` | CANONICAL (UGCP Runtime WS Profile ingress) |
| AIP v2 compat | `galaxy_gateway/protocol/compat.py` | LEGACY compat layer |
| Android bridge (monolith) | `galaxy_gateway/android_bridge.py` | ACTIVE transport adapter for Android runtime-profile semantics (not independent truth authority) |
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
5. (**Batch PR-5**) New command routing code must import from `core.commands.*` rather than `core.command_router` directly.
6. (**Batch PR-5**) New LLM routing code must import from `core.llm.*` rather than `core.multi_llm_router` directly.
