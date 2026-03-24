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

## 7. Authoritative Governance Sources

This section defines the **single sources of truth (SSOT)** for node registry
and system governance.  When files disagree, consult them in the precedence
order below.

### 7.1 Canonical sources (authoritative)

| File | Format | Role |
|------|--------|------|
| `node_dependencies.json` | JSON (machine-readable) | **Authoritative registry** — defines every active node, its startup policy, and inter-node dependencies. This is the sole source for which nodes exist and how they start. |
| `docs/node_audit_report.json` | JSON (machine-readable) | **Authoritative audit results** — contains the most recent structured integrity assessment for all nodes. |
| `docs/NODE_ACTIVE_MANIFEST.md` | Markdown (human-readable) | **Active-node view** — human-friendly mirror of the registry and audit outputs. Must stay aligned with the two JSON sources above; if they conflict, the JSON files win. |
| `docs/NODE_SYSTEM_AUDIT.md` | Markdown (human-readable) | **Rendered audit report** — a human-readable rendering of `docs/node_audit_report.json`. Derived from the canonical audit output, not an independent truth. |

### 7.2 Historical / non-authoritative documents (do not rely on for current status)

The following files are **historical snapshots** captured at specific points in
time.  They may be outdated.  They are preserved for archaeological context only
and must not be used as the basis for governance decisions.

| File | Snapshot date | Why non-authoritative |
|------|---------------|----------------------|
| `SYSTEM_INTEGRITY_REPORT.md` | 2026-02-14 | Generated against an older codebase; does not reflect current node registry or audit state |
| `FULL_SYSTEM_AUDIT.md` | 2026-03-08 | Point-in-time full-system audit; superseded by `docs/node_audit_report.json` |
| `ARCHITECTURE_REVIEW.md` | 2026-03-22 | Architecture review snapshot; useful as history but not a governance source |

Each of these files carries a prominent **⚠️ HISTORICAL SNAPSHOT** banner at
the top directing readers to the canonical sources.

### 7.3 Precedence order for resolving discrepancies

When two sources disagree, apply this precedence (highest authority first):

1. `node_dependencies.json` — for registry membership and startup policy
2. `docs/node_audit_report.json` — for audit status and integrity findings
3. `docs/NODE_ACTIVE_MANIFEST.md` — for human-verified active-node descriptions
4. `docs/NODE_SYSTEM_AUDIT.md` — rendered view; update to match sources above
5. **Historical documents** — informational only; never authoritative

### 7.4 Keeping sources in sync

- After any node is added, removed, or renamed, update `node_dependencies.json`
  first, then regenerate or manually update `docs/NODE_ACTIVE_MANIFEST.md`.
- After running an audit, write results to `docs/node_audit_report.json`, then
  re-render `docs/NODE_SYSTEM_AUDIT.md`.
- Do **not** create new top-level markdown reports claiming system-wide
  integrity status.  Route those findings into the canonical JSON files instead.

---

## 8. Adding New Code — Where It Belongs

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

## 10. Repository Hygiene

### Policy summary

Runtime artifacts, generated files, and temporary state must never be
committed to this repository.  This is especially important inside `nodes/`
where hundreds of independent node directories create many opportunities for
accidental pollution.

**Forbidden everywhere:**
- `*.pid` — PID files are runtime state, meaningless outside a live process
- `*.pyc`, `*.pyo`, `__pycache__/` — compiled Python bytecode
- `*.tmp`, `*.temp`, `*.bak` — temp/scratch files
- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/` — local dev caches

**Forbidden inside `nodes/` (stricter policy):**
- `*.log` — runtime log output
- `*.db`, `*.sqlite`, `*.sqlite3` — runtime database files

### Hygiene checker

A static hygiene checker is available at `scripts/check_repo_hygiene.py`.
Run it before merging any PR that touches `nodes/`:

```bash
# Check entire repository
python scripts/check_repo_hygiene.py

# Check only node directories
python scripts/check_repo_hygiene.py nodes/

# Machine-readable JSON output (useful for CI integration)
python scripts/check_repo_hygiene.py --json
```

Exit code `0` = clean.  Exit code `1` = violations found, with each violation
printed as `<path>  [<category>]  <reason>`.

### Allowlisting legitimate fixtures

If a node needs a small static fixture file that happens to match a forbidden
extension (e.g. a tiny pre-seeded `.db` for a unit test), add an explicit
path entry to `ALLOWLIST` in `scripts/check_repo_hygiene.py` and document
the reason in a comment.  Do **not** weaken the global rules.

### Removing a committed artifact

```bash
git rm --cached <path-to-artifact>
# Verify .gitignore covers the pattern so it cannot be re-added
echo "pattern" >> .gitignore
git add .gitignore
git commit -m "chore: remove committed runtime artifact <name>"
```

---

## 9. Key Documentation Index

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
