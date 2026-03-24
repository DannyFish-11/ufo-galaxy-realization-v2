# Galaxy Maintainer Runbook

> **PR-9 — Integration Validation & Authoritative Architecture Documentation**
>
> This runbook is the single concise reference for maintainers joining the
> Galaxy project after the PR-1 through PR-8 structural cleanup sequence.
> It answers: *What is the authoritative startup path? What is active? What is
> legacy? How do I validate the system?*

---

## 1. Authoritative Startup Path

```
python main.py              ← canonical OS entry (delegates immediately)
        │
        ▼
python unified_launcher.py  ← top-level system orchestrator
        │   (imports launcher/ sub-modules)
        ▼
launcher/                   ← authoritative startup package (PR-5)
  ├── bootstrap.py          — enums, SystemConfig, entrypoint writer, display helpers
  ├── service_manager.py    — ServiceInfo, ServiceManager lifecycle controller
  ├── core_services.py      — CoreServiceLauncher (Device Agent, Device Status API, UFO)
  ├── node_startup.py       — NodeSystemLauncher (discovery, health polling, registry)
  ├── health_checks.py      — run_startup_health_check (post-startup probe)
  └── shutdown.py           — async_shutdown (graceful NATS + subsystem teardown)
```

### Compatibility wrappers (not authoritative)

| Script | Status | Authority |
|--------|--------|-----------|
| `start_galaxy.py` | **PR-10 hardened** legacy wrapper | Delegates to `unified_launcher.py`; `_start_desktop()` dead path removed |
| `start_l4.py` | **PR-10 confirmed** legacy wrapper | Delegates to `unified_launcher.py`; frozen since PR-6 |
| `start.sh` | Shell convenience | Calls `main.py` |
| `start.bat` | Windows convenience | Calls `main.py` |

**Never extend `start_galaxy.py` or `start_l4.py` with new logic.**  
New startup functionality belongs in `launcher/`.

> **PR-10 note**: `start_galaxy.py --desktop` / `--all` are accepted as no-op
> stubs for backward compatibility but do **not** start any UI.  The legacy
> `run_ui.py` launcher they targeted has been permanently retired.  Active
> Windows direction: `windows_client/status_board_v2/`.
> See `docs/LEGACY_PURGE_HARDENING.md` for the complete purge audit.

---

## 2. Authority Chain

The runtime authority chain is fixed.  Do not bypass it.

```
DesktopPresenceRuntime          (core/desktop_presence_runtime.py)
    role: runtime_shell_authority
    owns: tri-state lifecycle (silent → liminal → manifest),
          runtime_session_id, perception source registry
        │
        ▼
OpenClawd                       (core/openclawd.py)
    role: subject_decision_authority
    owns: multimodal route selection, operator overrides,
          projection assembly, canonical response
        │
        ▼
AgentKernel                     (core/agent/kernel.py)
    role: cognition_planning_layer
    note: LLM planning only — NOT final authority
        │
        ▼
CommandRouter                   (core/command_router.py)
    role: execution_substrate
    owns: LOCAL_MANIFESTATION + REMOTE_COMMAND/REMOTE_AGENT routing
```

> **Key invariants**
> - `OpenClawd` is the primary subject/routing decision authority.
> - `AgentKernel` is cognition/planning only — never final authority.
> - `CommandRouter` is the canonical router — it is not an authority layer.

---

## 3. Active System Surface

### Active runtime directories

| Directory | Role | Description |
|-----------|------|-------------|
| `core/` | ACTIVE_RUNTIME | Canonical runtime: OpenClawd, DesktopPresenceRuntime, multimodal engine, all canonical singletons |
| `launcher/` | ACTIVE_RUNTIME | Authoritative startup modules |
| `nodes/` | ACTIVE_RUNTIME | 130 canonical nodes (PR-6 audit, PR-7 unified) |
| `contracts/` | ACTIVE_RUNTIME | Canonical data contracts |
| `galaxy_gateway/` | ACTIVE_RUNTIME | Cross-device routing substrate |
| `desktop_projection/` | ACTIVE_RUNTIME | Tri-state liminal/manifest projection engine |
| `worker/` | ACTIVE_RUNTIME | Background task worker pool |

### Active desktop status surface

| Directory | Role | Description |
|-----------|------|-------------|
| `windows_client/status_board_v2/` | ACTIVE_DESKTOP_STATUS | Canonical read-only desktop status board; projection-driven |
| `windows_client/autonomy/` | ACTIVE_DESKTOP_SHELL | Windows automation and input simulation layer |

### Outward-facing status truth

```
GET /api/v1/projection/runtime
    contract: contracts.desktop_status_projection.DesktopStatusProjection
    consumer: windows_client/status_board_v2/
```

`status_board_v2/` is the **only** canonical outward-facing status display.  
It is projection-driven and read-only with respect to system truth.

---

## 4. Legacy and Demoted Surfaces

These directories are **retained for compatibility only**.  
**Do not extend them with new runtime logic.**

| Surface | Status | Demoted by | Canonical replacement |
|---------|--------|------------|-----------------------|
| `dashboard/` | LEGACY_SURFACE | PR-4, PR-8 | `core/api_routes.py` |
| `dashboard/frontend/` | LEGACY_SURFACE | PR-4 | `core/api_routes.py` |
| `windows_client/` (root modules) | LEGACY_SHELL | PR-3 | `windows_client/status_board_v2/` |
| `enhancements/clients/windows_client/` | LEGACY_SHELL | PR-3 | Hard-disabled stubs |

### How to recognise a legacy surface

1. The directory contains a `LEGACY_SURFACE.md` or `LEGACY_SHELL.md` marker.
2. `core.repo_layout_registry.is_legacy_directory(path)` returns `True`.
3. The `core.ui_surface_authority.UISurfaceAuthorityRegistry` classifies it as
   `LEGACY_UI` or `LEGACY_SHELL`.

### Legacy path guardrail policy

Any legacy code path that is still callable must:
- Emit a `LEGACY PATH GUARDRAIL` log warning on invocation.
- Carry a `superseded_by` pointer to the canonical replacement.
- Be registered in `core.orchestration_authority.legacy_paths.LEGACY_PATH_REGISTRY`.

---

## 5. Node Model

### Source of truth

- **Machine-readable**: `node_dependencies.json` (`nodes` key, 130 entries)
- **Human-readable**: `docs/NODE_ACTIVE_MANIFEST.md`
- **Raw audit data**: `docs/node_audit_report.json`

### `startup_policy` values

| Policy | Meaning | Launcher behaviour |
|--------|---------|-------------------|
| `active` (95 nodes) | Healthy, orchestrated | Started unconditionally |
| `optional` (29 nodes) | Valid role, config-drift resolved (PR-7) | Started if available; failure does not abort system |
| `skip` (6 nodes) | Archived / deleted / stub | **Never started** |

### Promote a node from `optional` → `active`

1. Verify the node starts cleanly and passes its health check.
2. Change `startup_policy` in `node_dependencies.json` from `"optional"` to `"active"`.
3. Update `docs/NODE_ACTIVE_MANIFEST.md` counts.
4. Run `python scripts/validate_runtime.py` to confirm no regressions.

---

## 6. How to Validate the System

### Quick validation (no live services needed)

```bash
# Human-readable report
python scripts/validate_runtime.py

# JSON output (suitable for CI)
python scripts/validate_runtime.py --json

# Strict mode — exits 1 even for warnings
python scripts/validate_runtime.py --strict
```

Expected: **34 checks, all PASS**.

### Pytest integration tests

```bash
# Run PR-9 integration validation tests only
pytest tests/test_pr9_integration_validation.py -v

# Run launcher structural tests
pytest tests/test_launcher_refactor.py -v
```

### Full smoke check

```bash
# Deployment smoke test (requires live services)
python scripts/smoke_test.py --skip-http --skip-tests

# Port registry validation
python scripts/validate_ports.py
```

---

## 7. Adding New Code — Where It Belongs

| What you're adding | Where it goes |
|--------------------|---------------|
| New runtime logic | `core/` |
| New startup step | `launcher/` sub-module |
| New canonical node | `nodes/Node_XXX_Name/` + `node_dependencies.json` |
| New data contract | `contracts/` |
| New cross-device logic | `galaxy_gateway/` (substrate) or `core/` (authority) |
| New desktop status display | `windows_client/status_board_v2/` (read-only projection consumer) |
| New docs | `docs/` |
| New validation / integration check | `scripts/` + `tests/` |

**Never add new logic to `dashboard/`, legacy `windows_client/` roots, or `enhancements/clients/`.**

---

## 8. Key Documentation Index

| Document | Purpose |
|----------|---------|
| `docs/ARCHITECTURE_BASELINE.md` | Authoritative post-PR-009 architecture baseline |
| `docs/REPO_LAYOUT.md` | Repository zone classification (active vs legacy) |
| `docs/NODE_ACTIVE_MANIFEST.md` | Active node set and startup policies |
| `docs/ENTRYPOINT_AND_SURFACE_DEMOTION.md` | Which surfaces are demoted and why |
| `docs/UNIFIED_STARTUP.md` | Startup path detail and port registry |
| `docs/UNIFIED_SUBJECT_ARCHITECTURE.md` | DesktopPresenceRuntime + OpenClawd unified subject model |
| `dashboard/LEGACY_SURFACE.md` | Dashboard legacy/demotion notice |
| `windows_client/status_board_v2/ACTIVE_SURFACE.md` | Status board v2 active surface notice |
| `docs/MAINTAINER_RUNBOOK.md` | **This file** |

---

*Last updated: PR-9 — integration validation + authoritative documentation.*
