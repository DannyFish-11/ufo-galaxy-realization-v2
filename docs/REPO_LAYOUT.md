# Repository Layout — Galaxy Active Architecture

> **PR-8 (repo-layout)** — Repository organisation to separate active runtime
> assets, desktop-status assets, and legacy/transitional assets.
>
> Authoritative Python registry: `core/repo_layout_registry.py`

---

## 1. Active Runtime Directories

These directories contain canonical, actively-maintained runtime code.
New functionality belongs here.

| Directory | Role | Description |
|-----------|------|-------------|
| `core/` | **ACTIVE_RUNTIME** | Canonical runtime authority — OpenClawd AI authority, `DesktopPresenceRuntime` tri-state lifecycle, perception pipeline, multi-LLM router, cross-device chain, all canonical singletons. |
| `launcher/` | **ACTIVE_RUNTIME** | Authoritative startup modules (PR-5 refactor): `bootstrap`, `service_manager`, `core_services`, `node_startup`, `health_checks`, `shutdown`, `config_manager`, `dependency_resolver`. |
| `nodes/` | **ACTIVE_RUNTIME** | Active node system — 130+ canonical nodes (`Node_00` through `Node_130`), classified in PR-6 and unified in PR-7. Orchestration config: `node_dependencies.json`. |
| `contracts/` | **ACTIVE_RUNTIME** | Canonical data contracts — `DesktopStatusProjection`, `MultiDeviceRuntimeProjection`, proto definitions. |
| `galaxy_gateway/` | **ACTIVE_RUNTIME** | Active gateway / cross-device routing substrate — AIP v3 protocol, device router, NATS adapter, WebSocket handler. |
| `desktop_projection/` | **ACTIVE_RUNTIME** | Tri-state liminal-space / manifest-stage projection engine (silent → liminal → manifest state transitions). |
| `worker/` | **ACTIVE_RUNTIME** | Background task worker pool for async job execution. |

### Primary startup paths

```
python unified_launcher.py          # canonical startup (Linux/Mac)
start.bat                            # Windows canonical startup
python main.py                       # thin stub that delegates to unified_launcher.py
```

---

## 2. Active Desktop Status Surface

These directories are the **canonical outward-facing status and interaction layer**
for the Windows desktop runtime.

| Directory | Role | Description |
|-----------|------|-------------|
| `windows_client/status_board_v2/` | **ACTIVE_DESKTOP_STATUS** | Canonical read-only desktop status board. Consumes `GET /api/v1/projection/runtime` (contract: `contracts.desktop_status_projection.DesktopStatusProjection`). Renders tri-state phase surfaces: silent / liminal / manifest. |
| `windows_client/autonomy/` | **ACTIVE_DESKTOP_SHELL** | Active Windows automation and input-simulation layer (UI automation, comtypes bootstrap, input simulator). |

### Canonical status projection contract

```
GET /api/v1/projection/runtime
contract: contracts.desktop_status_projection.DesktopStatusProjection
```

The `status_board_v2/` surface is the **only** canonical outward-facing status
display.  It is projection-driven and read-only with respect to system truth.

---

## 3. Desktop Tri-State Runtime Layer

The active Windows-facing runtime lifecycle is managed by:

- `core/desktop_presence_runtime.py` — `DesktopPresenceRuntime`
  (tri-state lifecycle: **silent** / **liminal** / **manifest**)
- `core/continuum/` — continuum state machine
- `desktop_projection/` — liminal-space and manifest-stage engine

Status is consumed downstream by `windows_client/status_board_v2/`.

---

## 4. Legacy and Transitional Directories

These directories are **retained for compatibility only**.  They must not be
extended with new runtime logic, must not maintain a parallel source of truth,
and must not define system structure.

| Directory | Role | Status | Canonical Replacement |
|-----------|------|--------|-----------------------|
| `dashboard/` | **LEGACY_HEADLESS_BACKEND** | Frontend deleted PR-1; backend headless | `core/api_routes.py` |
| ~~`dashboard/frontend/`~~ | ~~**LEGACY_SURFACE**~~ | **DELETED PR-1** — directory no longer exists | `windows_client/status_board_v2/` |
| `windows_client/` (root modules) | **LEGACY_SHELL** | Hard-disabled stubs (PR-3) | `windows_client/status_board_v2/` |
| `enhancements/` | **TRANSITIONAL** | Overlays; `clients/` hard-disabled (PR-3) | `core/` |

### Hard-disabled modules (raise `RuntimeError` on import)

The following modules in `windows_client/` are hard-disabled stubs:

- `windows_client/client.py` — legacy bespoke Gateway/AIP client
- `windows_client/ui_sidebar.py` — legacy Tk chat sidebar
- `windows_client/desktop_automation.py` — legacy pyautogui automation path
- `windows_client/windows_mcp_server.py` — legacy MCP stdio execution path
- `windows_client/main.py` — legacy F12-hotkey chat/sidebar client
- `windows_client/windows_client_integrated.py` — legacy PyQt6 integrated client
- `windows_client/key_listener.py` — legacy F12 hotkey listener

Launchers and legacy UI assets have been moved to `windows_client/_legacy/`.

The following enhancement launcher is hard-disabled:

- `enhancements/clients/windows_client/run_ui.py` — targeted the retired legacy
  chat/sidebar client; emits `DeprecationWarning` on import.

### Authority references

- `core/ui_surface_authority.py` — registers `dashboard/` as `LEGACY_UI` and
  `windows_client/` as `LEGACY_SHELL`
- `core/orchestration_authority/legacy_paths.py` — PR-8 legacy path entries
- `core/repo_layout_registry.py` — full directory classification registry
- `dashboard/LEGACY_SURFACE.md` — legacy marker for `dashboard/` (headless backend)
- `windows_client/status_board_v2/ACTIVE_SURFACE.md` — active marker for status board
- `enhancements/LEGACY_TRANSITION.md` — transitional marker for `enhancements/`

---

## 5. Infrastructure Directories

Supporting directories that are not part of the active runtime code path.

| Directory | Purpose |
|-----------|---------|
| `docs/` | Documentation — architecture, API, operational, migration guides |
| `tests/` | Test suite — unit, integration, conformance, chaos tests |
| `scripts/` | Operational scripts — audits, health checks, dependency pinning |
| `deployment/` | Deployment assets — Kubernetes, nginx, Docker configurations |
| `config/` | Runtime configuration files and Grafana dashboards |
| `data/` | Persistent data directory |
| `static/` | Static web assets served by the API layer |
| `systemd/` | systemd unit files for Linux service management |
| `android_client/` | Android client implementation |
| `cli/` | Command-line interface entrypoints |
| `daemon/` | Background daemon process assets |
| `external/` | External integrations (AgentCPM, Microsoft UFO, channels) |
| `fusion/` | Data fusion utilities |
| `hardware/` | Hardware interface layer |
| `installer/` | Installation packaging assets |
| `knowledge_db/` | Knowledge database assets |
| `mcp_bridge/` | MCP (Model Context Protocol) bridge |
| `skills/` | Skill packages (SKILL.md format) |
| `tools/` | Developer tooling |
| `examples/` | Usage examples and sample configurations |

---

## 6. Repository Root Key Files

| File | Purpose |
|------|---------|
| `unified_launcher.py` | Canonical Python startup entrypoint |
| `main.py` | Thin stub forwarding to `unified_launcher.py` |
| `start.bat` | Windows canonical startup script |
| `start.sh` | Linux/Mac startup script |
| `node_dependencies.json` | Canonical node orchestration registry |
| `config.json` | Runtime configuration |
| `pyproject.toml` | Python project metadata |
| `requirements.txt` | Runtime dependencies |
| `requirements-dev.txt` | Development dependencies |

---

## 7. Architecture Authority Chain

```
core/desktop_presence_runtime.py   (DesktopPresenceRuntime — tri-state lifecycle)
  └─► core/openclawd.py            (OpenClawd — AI authority, final routing)
       └─► core/routes/            (RuntimeProjection — canonical state projection)
            └─► GET /api/v1/projection/runtime
                 └─► windows_client/status_board_v2/   (canonical status display)
```

For UI surface authority, see `core/ui_surface_authority.py`.
For orchestration path legacy status, see `core/orchestration_authority/legacy_paths.py`.
For full directory classification, see `core/repo_layout_registry.py`.

---

*Generated by PR-8 (repo-layout) — Galaxy repository organisation.*
