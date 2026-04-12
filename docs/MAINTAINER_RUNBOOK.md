# Galaxy Maintainer Runbook

> **PR-10 — Automate Audit/Manifest Generation and Finalize Long-Term Maintainer Workflow**
>
> This runbook is the single concise reference for maintainers joining the
> Galaxy project after the PR-1 through PR-9 structural cleanup sequence.
> It answers: *What is the authoritative startup path? What is active? What is
> legacy? How do I validate the system?  How do I regenerate governance docs?*

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

### Convenience startup scripts

| Script | Status | Notes |
|--------|--------|-------|
| `start.sh` | Active convenience | Calls `main.py` |
| `start.bat` | Active convenience (Windows) | Calls `main.py` |

> **Post-PR-10 cleanup**: `start_galaxy.py` and `start_l4.py` have been fully
> removed.  They were compatibility wrappers that simply delegated to
> `unified_launcher.py` with a `DeprecationWarning`.  All startup logic belongs
> in `launcher/`.  See `docs/LEGACY_PURGE_HARDENING.md` for the complete purge
> audit.  The L4 runtime classes are now canonical in
> `core.galaxy_main_loop_l4_enhanced`.

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
| `windows_client/status_board_v2/` | ACTIVE_DESKTOP_STATUS | Canonical operator-facing runtime status surface; projection-driven with bounded controls |
| `windows_client/autonomy/` | ACTIVE_DESKTOP_SHELL | Windows automation and input simulation layer |

### Outward-facing status truth

```
GET /api/v1/projection/runtime
    contract: contracts.desktop_status_projection.DesktopStatusProjection
    consumer: windows_client/status_board_v2/
```

`status_board_v2/` is the **only** canonical outward-facing desktop runtime
status surface. It is projection-driven with bounded operational controls; it is
not merely passive observation.

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

> **PR-6 normalization**: All 130 registry entries now carry an **explicit**
> `startup_policy` field.  Implicit defaults are no longer accepted as a
> governance practice.

| Policy | Count | Meaning | Launcher behaviour |
|--------|-------|---------|-------------------|
| `active` | 95 | Healthy, orchestrated | Started unconditionally |
| `optional` | 29 | Deliberate governed state (PR-8) | Started if available; failure does not abort system |
| `skip` | 6 | Archived / deleted / stub | **Never started** |

### Startup policy state machine

```
         optional → active
    (promotion checklist complete; governance review)
         ▲                    │
         │                    │ active → optional
    ┌────────┐                │ (drift / known issue; demote for soft-fail)
    │ active │◄───────────────┘
    └────────┘
         │
         │ active → skip          optional → skip
         │ (retired / archived)   (repair abandoned)
         ▼                                ▼
                       ┌──────┐
                       │ skip │  (terminal / holding state)
                       └──────┘
```

### Optional-node governance (PR-8)

`optional` is a **deliberate governance state**.  Every optional node is expected
to meet the optional-node minimum baseline and is tracked toward `active`.

**Optional-node minimum baseline** (all must pass):

| Check | Requirement |
|-------|-------------|
| `registry_present` | In `node_dependencies.json` with `startup_policy: "optional"` |
| `has_main_py` | `main.py` exists |
| `has_fusion_entry` | `fusion_entry.py` exists |
| `syntax_ok` | Entry files pass `py_compile` |
| `has_readme` | `README.md` exists |
| `hygiene_clean` | No runtime artifacts in node root |

**Promotion-gap checks** (tracked; required before promoting to `active`):

| Check | Requirement |
|-------|-------------|
| `has_dockerfile` | `Dockerfile` present |
| `has_requirements` | `requirements.txt` present |
| `has_health_endpoint` | `/health` endpoint declared in `main.py` |
| `has_status_endpoint` | `/status` endpoint declared in `main.py` |

Run the audit to see per-node optional baseline and promotion-gap status:

```bash
python scripts/node_audit.py
# See docs/NODE_SYSTEM_AUDIT.md §Optional-Node Governance for the full table
```

See `docs/NODE_ACTIVE_MANIFEST.md §Optional-Node Governance` for the complete
optional-node list, baseline status, and the formal promotion checklist.

### Promote a node from `optional` → `active`

Use the full promotion checklist in `docs/NODE_ACTIVE_MANIFEST.md`.

Summary:

1. Confirm all optional-baseline checks pass in the audit report.
2. Confirm all promotion-gap checks pass (Dockerfile, requirements.txt, /health, /status).
3. Verify the node starts cleanly and `/health` + `/status` respond over HTTP.
4. Confirm no open issues blocking promotion.
5. Change `startup_policy` in `node_dependencies.json` from `"optional"` to `"active"`.
6. Update counts table in `docs/NODE_ACTIVE_MANIFEST.md`.
7. Run `python scripts/node_audit.py` to regenerate the audit report.
8. Run `python scripts/validate_runtime.py` to confirm no regressions.
9. Open a PR with health-check evidence in the description.

### Demote a node from `active` → `optional`

1. Identify the drift or issue (failing health check, missing dependency, etc.).
2. Open a tracking issue documenting the problem.
3. Change `startup_policy` to `"optional"` and update `description` in `node_dependencies.json`.
4. Update manifest counts in `docs/NODE_ACTIVE_MANIFEST.md`.

### Retire a node (`active` or `optional` → `skip`)

1. Confirm the node has no unique active callers in the orchestration graph.
2. Change `startup_policy` to `"skip"` in `node_dependencies.json`.
3. Update `description` to document the reason (archived / deleted / stub).
4. Keep the registry entry — it serves as audit history.
5. Update manifest counts in `docs/NODE_ACTIVE_MANIFEST.md`.

### What `skip` means operationally

- The node **is never started** by `launcher/node_startup.py` (`should_skip()` returns `True`).
- The registry entry is retained for audit traceability.
- A skipped node's code directory may still exist on disk; it is not deleted automatically.
- To resurrect a skipped node, open a dedicated PR with a full implementation review and change `startup_policy` back to `"optional"` initially.
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

Expected: **all checks PASS** (Section 7 includes startup-tier model validation).

### Startup tier inspection

```bash
# The validator (section 7) checks the startup-tier model automatically.
# For a standalone readiness-baseline report, run:
python -c "
from core.startup_tier_model import build_readiness_baseline
b = build_readiness_baseline()
import json; print(json.dumps(b.summary(), indent=2))
"
```

See `docs/STARTUP_TIER_MODEL.md` for the full startup-tier reference.

### Pytest integration tests

```bash
# Run PR-9 integration validation tests only
pytest tests/test_pr9_integration_validation.py -v

# Run launcher structural tests
pytest tests/test_launcher_refactor.py -v

# Run startup-tier model tests
pytest tests/test_startup_tier_model.py -v
```

### Full smoke check

```bash
# Deployment smoke test (requires live services)
python scripts/smoke_test.py --skip-http --skip-tests

# Port registry validation
python scripts/validate_ports.py
```

---

## 5a. Startup Tier Model

Galaxy defines a canonical 3-tier startup model grounded in the existing
`startup_policy` and `group` metadata.  **Tiers are a read-only view — they
do not replace `startup_policy` governance.**

| Tier | Selection rule | Purpose |
|------|----------------|---------|
| **Core** | `startup_policy="active"` AND `group="core"` | Minimum canonical boot |
| **Standard** | `startup_policy="active"` AND `group` ∈ `{core, development}` | Normal dev/functional boot |
| **Full** | `startup_policy` ∈ `{active, optional}` | Broad runtime boot |

**Key invariant**: Core ⊂ Standard ⊂ Full.

### Using tiers programmatically

```python
from launcher import NodeSystemLauncher

core_nodes     = launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_CORE)
standard_nodes = launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_STANDARD)
full_nodes     = launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_FULL)
```

Full reference: `docs/STARTUP_TIER_MODEL.md`.

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

### 8a. How to add a new node (step-by-step)

This section provides the complete workflow for adding a node that will pass
the canonical audit engine and meet the node contract.

**1. Copy the template**

```bash
cp -r templates/node_template nodes/Node_XXX_YourNodeName
```

The template at `templates/node_template/` contains:

| File | Purpose |
|------|---------|
| `main.py` | Starter FastAPI service with `/health` and `/status` |
| `fusion_entry.py` | Fusion-layer shim using `importlib.util` |
| `README.md` | Structured placeholder (port, endpoints, env vars, …) |
| `requirements.txt` | Minimal dependency starter |
| `Dockerfile` | Minimal container definition |

**2. Rename placeholder strings**

Find and replace every occurrence of `Node_XXX_YourNodeName` and `<PORT>`
inside your new directory:

```bash
# Linux / macOS
cd nodes/Node_XXX_YourNodeName
grep -rl 'Node_XXX_YourNodeName' . | xargs sed -i 's/Node_XXX_YourNodeName/Node_042_Scheduler/g'
grep -rl '<PORT>' .               | xargs sed -i 's/<PORT>/8142/g'
```

**3. Implement your logic in `main.py`**

- Keep `/health` and `/status` endpoints (required by the active-node contract).
- Add your own business-logic routes below the marked section.
- Do **not** remove the `sys.path` fix block at the top of `main.py`.

**4. Register the node**

Add an entry to `node_dependencies.json`:

```json
"Node_XXX_YourNodeName": {
    "port": XXXX,
    "group": "development",
    "startup_policy": "optional",
    "dependencies": [],
    "description": "Short human-readable description"
}
```

Valid `startup_policy` values: `"active"`, `"optional"`, `"skip"`.
New nodes should start as `"optional"` until they have passed integration
testing and a health-check review.  Promote to `"active"` following the
procedure in §5.  Use `"skip"` only for stubs or archived entries.

**5. Fill in `README.md`**

Complete every placeholder section (Purpose, Port, Endpoints, Env Vars,
Dependencies, Startup).  Remove the checklist section before merging.

**6. Verify**

```bash
# Audit engine — new node must show "keep" with no integrity failures
# Also regenerates docs/node_audit_report.json and docs/NODE_SYSTEM_AUDIT.md
make audit-regen

# Hygiene checker — must exit 0
python scripts/check_repo_hygiene.py nodes/Node_XXX_YourNodeName/

# Port registry — ensure no port conflicts
python scripts/validate_ports.py
```

**7. Regenerate governance docs and commit**

```bash
# Full governance doc refresh (audit report + NODE_SYSTEM_AUDIT.md + NODE_ACTIVE_MANIFEST.md)
make regen-all
git add docs/node_audit_report.json docs/NODE_SYSTEM_AUDIT.md docs/NODE_ACTIVE_MANIFEST.md
git commit -m "chore: regenerate governance docs after adding Node_XXX_YourNodeName"
```

### 8b. Canonical node contract summary

| Tier | Required files | Additional requirements |
|------|---------------|------------------------|
| **Baseline** (any non-skip node) | `main.py`, `fusion_entry.py`, `README.md` | Syntax-clean; hygiene-clean; in `node_dependencies.json` |
| **Optional** (`startup_policy: optional`) | same as Baseline | PR-8 optional baseline checks must pass; startup failure does not abort system |
| **Active** (`startup_policy: active`) | above + `requirements.txt`, `Dockerfile` | `/health` + `/status` endpoints; packaging complete; promotion checklist done |

> **PR-8 clarification:** The `optional` contract is weaker than `active`.  Optional nodes
> are **not** required to have Dockerfile, requirements.txt, or runtime-contract endpoints
> as part of the baseline — these are tracked as promotion-gap checks.
> See `docs/NODE_ACTIVE_MANIFEST.md §Optional-Node Governance` for the full optional baseline.

See `CONTRIBUTING.md § Canonical Node Contract` for the full specification.
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
| `docs/NODE_ACTIVE_MANIFEST.md` | Active node set and startup policies (**generated** — see §11) |
| `docs/ENTRYPOINT_AND_SURFACE_DEMOTION.md` | Which surfaces are demoted and why |
| `docs/UNIFIED_STARTUP.md` | Startup path detail and port registry |
| `docs/UNIFIED_SUBJECT_ARCHITECTURE.md` | DesktopPresenceRuntime + OpenClawd unified subject model |
| `dashboard/LEGACY_SURFACE.md` | Dashboard legacy/demotion notice |
| `windows_client/status_board_v2/ACTIVE_SURFACE.md` | Status board v2 active surface notice |
| `CONTRIBUTING.md § Canonical Node Contract` | Baseline and active-node contract specification |
| `templates/node_template/` | Copy-ready node template (baseline + active files) |
| `docs/MAINTAINER_RUNBOOK.md` | **This file** |

---

## 10. CI Governance Gates

The `.github/workflows/node-governance.yml` workflow runs automatically on
every push to `main` and on every pull request.  It enforces the canonical
governance checks so that regressions cannot merge silently.

### Jobs in the workflow

| Job | Script | Fails on |
|-----|--------|----------|
| **Canonical Node Audit** | `scripts/node_audit.py --strict` | Port conflicts, invalid `startup_policy` values, registry drift (config entry without on-disk directory), syntax errors in active node entry files |
| **Repository Hygiene** | `scripts/check_repo_hygiene.py` | Any committed runtime artifacts (`*.pid`, `*.pyc`, `__pycache__`, `*.db` in `nodes/`, etc.) |
| **Runtime Structural Validation** | `scripts/validate_runtime.py` | Startup-path incoherence, unimportable authority chain, node-registry inconsistency, missing critical docs |
| **Governance Unit Tests** | `pytest tests/test_pr6_node_audit.py tests/test_pr8_optional_governance.py tests/test_repo_hygiene.py` | Any test failure in the governance test suite |

### Running governance checks locally

Run the exact same checks as CI with a single command:

```bash
make governance
```

Or run individual checks:

```bash
# Canonical node audit (strict — exits 1 on critical failures)
python scripts/node_audit.py --print-summary --strict

# Repository hygiene (exits 1 on any violation)
PYTHONDONTWRITEBYTECODE=1 python scripts/check_repo_hygiene.py

# Runtime structural validation (exits 1 on FAIL results)
python scripts/validate_runtime.py

# Governance-focused unit tests
python -m pytest tests/test_pr6_node_audit.py \
  tests/test_pr8_optional_governance.py \
  tests/test_repo_hygiene.py -v --tb=short
```

### What counts as governance-critical (`--strict` in node audit)

| Finding | Field in report | Why critical |
|---------|-----------------|--------------|
| Port conflict | `port_conflicts` | Two nodes claim the same port — deployment breaks |
| Invalid `startup_policy` | `policy_violation_nodes` | Registry corruption — launcher behaviour undefined |
| Config entry without on-disk dir | `in_config_not_on_disk` | Registry drift — dead entry references phantom node |
| Syntax error in entry file | `syntax_error_nodes` | Active node cannot be imported — runtime crash |

Non-critical findings (missing packaging files, optional-node promotion gaps,
etc.) appear in the reports and are visible in CI output, but they do **not**
fail the pipeline unless they escalate to one of the above categories.

### Audit report artifacts

After every CI run the `node-audit` job uploads:

- `docs/node_audit_report.json` — machine-readable full audit
- `docs/NODE_SYSTEM_AUDIT.md`   — human-readable Markdown summary

These are available under the **Artifacts** section of the workflow run in
GitHub Actions.

---

## 11. Governance Artifact Regeneration (PR-10)

### Canonical sources vs generated companions

| File | Type | Authority |
|------|------|-----------|
| `node_dependencies.json` | Machine-readable JSON | **Canonical** — authoritative registry; edit by hand |
| `docs/node_audit_report.json` | Machine-readable JSON | **Canonical** — generated by `scripts/node_audit.py`; do not edit by hand |
| `docs/NODE_SYSTEM_AUDIT.md` | Human-readable Markdown | **Generated companion** — rendered by `scripts/node_audit.py`; regenerate with `make audit-regen` |
| `docs/NODE_ACTIVE_MANIFEST.md` | Human-readable Markdown | **Generated companion** — rendered by `scripts/gen_node_active_manifest.py`; regenerate with `make manifest-regen` |

When sources conflict, the **JSON files win**.  The Markdown companions are
regenerated views; never edit them by hand and then treat them as authoritative.

### When to regenerate

| Event | Command |
|-------|---------|
| Any change to `node_dependencies.json` | `make regen-all` |
| Any change to `nodes/` (add/remove/rename node) | `make regen-all` |
| Before opening a PR that touches nodes or registry | `make regen-all` |
| After responding to a CI governance failure | `make governance` then `make regen-all` if docs are stale |

### How to regenerate

```bash
# Full refresh — regenerates all three governance doc outputs in one command
make regen-all

# Or step by step:
make audit-regen       # → docs/node_audit_report.json + docs/NODE_SYSTEM_AUDIT.md
make manifest-regen    # → docs/NODE_ACTIVE_MANIFEST.md

# Then commit the regenerated docs:
git add docs/node_audit_report.json docs/NODE_SYSTEM_AUDIT.md docs/NODE_ACTIVE_MANIFEST.md
git commit -m "chore: regenerate governance docs"
```

### Pre-PR checklist (quick reference)

Run these before opening any PR that touches nodes or registry:

```bash
make regen-all        # regenerate governance docs
make governance       # run full governance gate (mirrors CI)
```

Both commands must succeed with no errors before the PR is ready for review.

### Adding a new node — end-to-end workflow

1. Copy template: `cp -r templates/node_template nodes/Node_XXX_YourName`
2. Rename placeholders in the new directory (node name, port)
3. Implement logic in `main.py` (keep `/health` and `/status`)
4. Register in `node_dependencies.json` with `startup_policy: "optional"`
5. Run `make regen-all` — new node should appear as `keep` in the audit
6. Run `make governance` — all checks must pass
7. Commit implementation + regenerated governance docs in the same PR

### Promoting `optional` → `active`

1. Complete the promotion checklist in `docs/NODE_ACTIVE_MANIFEST.md §Promotion Checklist`
2. Change `startup_policy` to `"active"` in `node_dependencies.json`
3. Run `make regen-all` and `make governance`
4. Commit in a dedicated PR with runtime health-check evidence

### Responding to CI governance failures

| CI job | Common cause | Local command | Fix |
|--------|-------------|---------------|-----|
| Canonical Node Audit | Port conflict, invalid policy, registry drift, syntax error | `make audit-regen` then `make governance` | Fix the violation; re-run audit |
| Repository Hygiene | Committed runtime artifact | `python scripts/check_repo_hygiene.py` | `git rm --cached` the artifact; update `.gitignore` |
| Runtime Structural Validation | Authority chain unimportable, missing critical docs | `python scripts/validate_runtime.py` | Fix the import or add the missing file |
| Governance Unit Tests | Regression in audit/hygiene/registry logic | `python -m pytest tests/test_pr6_node_audit.py tests/test_pr8_optional_governance.py tests/test_repo_hygiene.py -v` | Fix the failing test or the underlying code |

After fixing any CI failure, always run `make governance` locally to confirm
all checks pass before pushing the fix.

---

*Last updated: PR-10 — Automate Audit/Manifest Generation and Finalize Long-Term Maintainer Workflow.*
