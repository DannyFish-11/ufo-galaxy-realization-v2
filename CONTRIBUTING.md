# Contributing to Galaxy

Thank you for contributing!

## Setting Up the Dev Environment

1. **Python 3.11+** is required.
2. Clone the repository and create a virtual environment:
   ```bash
   git clone https://github.com/DannyFish-11/galaxy-realization-v2.git
   cd galaxy-realization-v2
   python3.11 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```
3. Install all dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Install dev-only tools (linters, test runner):
   ```bash
   pip install -r requirements-dev.txt
   ```

## Canonical Node Contract

Every node directory under `nodes/` must meet the requirements for its
governance tier.  The audit engine in `scripts/node_audit.py` checks these
requirements automatically.

### Baseline contract (all non-skipped nodes)

The following files are **required** for any node that is not explicitly
marked `skip` or `archive` in `node_dependencies.json`:

| File | Purpose |
|------|---------|
| `main.py` | Node entry point — core logic, FastAPI app, or equivalent |
| `fusion_entry.py` | Fusion-layer integration shim (see pattern below) |
| `README.md` | Human-readable description, port, endpoints, env vars |

A node that exists on disk but is missing any of these three files is
treated as **incomplete** by the audit engine.

### Active-node contract (nodes with `"startup_policy": "auto"` or `"required"`)

Active nodes must additionally satisfy:

| Requirement | Detail |
|-------------|--------|
| `requirements.txt` | All Python runtime dependencies declared |
| `Dockerfile` | Node can be containerised independently |
| `/health` endpoint | `GET /health` returns `{"status": "healthy", "node": "..."}` with HTTP 200 |
| `/status` endpoint | `GET /status` returns at minimum `{"node": "...", "port": ..., "ready": bool}` |
| Registry entry | Listed in `node_dependencies.json` with `port`, `startup_policy`, and `dependencies` |

### `fusion_entry.py` — Execution Adapter Contract

`fusion_entry.py` is the **canonical local execution adapter** for a node.
It is loaded and called exclusively by
`core.node_invocation.UnifiedNodeExecutor` (via `invoke_node()`).

**What `fusion_entry.py` is:**
- A local execution adapter that loads `main.py` in isolation and exposes a
  uniform `execute()` interface.

**What `fusion_entry.py` is NOT:**
- It is **not** a node existence definition.  A node having a
  `fusion_entry.py` on disk does **not** imply active system membership.
- It is **not** a registry or discovery authority.  The canonical runtime
  node registry is `NodeFabricRegistry` (`core/nodes/node_fabric_registry.py`).
- It is **not** a governance eligibility check.  Governance metadata lives in
  `node_dependencies.json` and is evaluated by the governance layer.

**Adapter contract (`FUSION_ENTRY_ADAPTER_CONTRACT_V1`):**

Every `fusion_entry.py` must:

1. Use `importlib.util.spec_from_file_location` to load `main.py` — **never
   mutate `sys.path`** from within `fusion_entry.py`.
2. Expose a `FusionNode` class with an async `execute(command, **params)`
   method that returns `{"success": bool, ...}`.
3. Expose a module-level `get_node_instance()` function that returns a
   `FusionNode`.

The full contract specification is in `core/fusion_entry_adapter.py`.
Callers must use `invoke_node()` from `core.node_invocation` rather than
calling `_load_node` / `_execute_node` from `core.routes._helpers` directly.

### Port and registry fields

Ports are declared in `node_dependencies.json`.  Do **not** hard-code a port
only in `main.py` without also registering it in the JSON.  The JSON entry
for a node should look like:

```json
"Node_XXX_YourNodeName": {
    "port": XXXX,
    "startup_policy": "auto",
    "dependencies": ["Node_YYY_Other"],
    "description": "Short description"
}
```

### Node template

A ready-to-copy baseline template lives at `templates/node_template/`.
Copy the entire directory and rename it before editing:

```bash
cp -r templates/node_template nodes/Node_XXX_YourNodeName
```

Then find-and-replace `Node_XXX_YourNodeName` and `<PORT>` throughout the
copied files.

---

## Adding a New Node

1. Copy the template: `cp -r templates/node_template nodes/Node_XXX_YourName/`
2. Rename all placeholder strings (`Node_XXX_YourNodeName`, `<PORT>`) to match
   your actual node ID and port.
3. Each node directory must contain at minimum:
   - `main.py` – entry point with the node's core logic
   - `fusion_entry.py` – integration shim used by the fusion layer
   - `README.md` – purpose, port, endpoints, env vars, dependencies
4. **Register the node in `node_dependencies.json`.**  This file is the
   machine-readable source of truth for the node registry and startup policy.
   A node that is not listed there is not considered part of the active system,
   regardless of whether its directory exists on disk.
5. For active nodes, also add `requirements.txt` and `Dockerfile` (both are
   included in the template).
6. Run `python scripts/node_audit.py` and confirm the new node shows `keep`
   status with no integrity failures.
7. Run `python scripts/check_repo_hygiene.py` — must exit `0`.

## Authoritative Sources of Truth

Understanding which files are authoritative prevents confusion when sources
appear to disagree.

### Canonical sources (always consult these)

| File | Role |
|------|------|
| `node_dependencies.json` | **Registry SSOT** — the definitive list of active nodes, startup policy, and inter-node dependencies |
| `docs/node_audit_report.json` | **Audit SSOT** — most recent structured integrity assessment for all nodes |
| `docs/NODE_ACTIVE_MANIFEST.md` | Human-readable mirror of the registry and audit outputs |
| `docs/NODE_SYSTEM_AUDIT.md` | Human-readable rendering of the audit JSON; derived, not independent |

### Historical documents (do not rely on for current status)

The following top-level reports are **historical snapshots** and may be
outdated.  They carry a prominent warning banner but are preserved for
context.  Do **not** treat them as current truth and do **not** create new
competing documents of the same kind:

- `SYSTEM_INTEGRITY_REPORT.md` — snapshot from 2026-02-14
- `FULL_SYSTEM_AUDIT.md` — snapshot from 2026-03-08
- `ARCHITECTURE_REVIEW.md` — snapshot from 2026-03-22

### Rules for contributors

- **Node registry changes must be reflected in `node_dependencies.json`.**
  This is the only place that determines whether a node participates in the
  runtime.
- **Current audit status comes from `docs/node_audit_report.json`**, not from
  legacy markdown summaries.
- **Do not introduce new top-level integrity or audit report files.**  Route
  findings into the canonical JSON files instead, then update the human-readable
  views (`docs/NODE_ACTIVE_MANIFEST.md`, `docs/NODE_SYSTEM_AUDIT.md`).
- For full precedence rules and how to resolve discrepancies between sources,
  see `docs/MAINTAINER_RUNBOOK.md § 7. Authoritative Governance Sources`.

## Running Tests

```bash
python -m pytest tests/ -v
```

> **Note:** `pytest` and `pytest-asyncio` live in `requirements-dev.txt`.
> Install them before running tests:
>
> ```bash
> pip install -r requirements-dev.txt
> ```

### Verifying the Three Autonomous Loops

```bash
python -m pytest tests/test_autonomous_loops.py -v
```

### Verifying Capability Registration

```bash
python scripts/verify_capability_registry.py
```

## Branch & PR Conventions

- Work on a feature branch: `feature/<short-description>` or `fix/<short-description>`
- Keep commits small and focused; write meaningful commit messages
- Open a pull request targeting `main`
- All CI checks must pass before merging

## CI Governance Gates

Every pull request automatically runs the **Node Governance** workflow
(`.github/workflows/node-governance.yml`).  This workflow fails CI for
governance-critical regressions before they reach `main`.

### What the workflow checks

| Job | What it enforces |
|-----|-----------------|
| **Canonical Node Audit** | No port conflicts, no invalid `startup_policy` values, no registry drift, no syntax errors in active node entry files |
| **Repository Hygiene** | No forbidden runtime artifacts committed (PID files, bytecode, `__pycache__`, runtime databases in `nodes/`, etc.) |
| **Runtime Structural Validation** | Startup-path coherence, authority chain importable, node registry consistent, critical docs present |
| **Governance Unit Tests** | Tests in `test_pr6_node_audit.py`, `test_pr8_optional_governance.py`, `test_repo_hygiene.py` all pass |

### Running the same checks locally

Before pushing, you can reproduce the full governance check suite with one
command:

```bash
make governance
```

Or step by step:

```bash
# 1. Canonical node audit — exits 1 on critical failures
python scripts/node_audit.py --print-summary --strict

# 2. Repository hygiene — exits 1 on any violation
PYTHONDONTWRITEBYTECODE=1 python scripts/check_repo_hygiene.py

# 3. Runtime structural validation — exits 1 on FAIL results
python scripts/validate_runtime.py

# 4. Governance unit tests
python -m pytest tests/test_pr6_node_audit.py \
  tests/test_pr8_optional_governance.py \
  tests/test_repo_hygiene.py -v --tb=short
```

See `docs/MAINTAINER_RUNBOOK.md § CI Governance Gates` for a detailed
explanation of every failure category and how to resolve common issues.

## Repository Hygiene Policy

### What must never be committed

The following artifact types are **forbidden** from being committed anywhere in
the repository, and are especially prohibited inside `nodes/` directories:

| Category | Examples | Why |
|----------|----------|-----|
| PID files | `*.pid`, `node95.pid` | Runtime state — meaningless outside the running process |
| Runtime databases | `*.db`, `*.sqlite`, `*.sqlite3` inside `nodes/` | Generated at runtime; often large and binary |
| Log files | `*.log` inside `nodes/` | Runtime output — must not accumulate in source control |
| Python bytecode | `*.pyc`, `*.pyo`, `__pycache__/` | Derived artifacts; rebuilt automatically |
| Pytest/tool caches | `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/` | Local dev artefacts |
| Temp / scratch files | `*.tmp`, `*.temp`, `*.bak` | Transient output |

These patterns are enforced in `.gitignore`.  The hygiene checker at
`scripts/check_repo_hygiene.py` can be run at any time to audit the working
tree for violations:

```bash
python scripts/check_repo_hygiene.py          # scan the whole repo
python scripts/check_repo_hygiene.py nodes/   # scan only node dirs
python scripts/check_repo_hygiene.py --json   # machine-readable output
```

The script exits with code `1` when violations are found and prints each
offending path together with the violation category and reason.

### Where test fixtures and example data should live

If a node genuinely needs a small, static fixture file for its unit tests
(e.g. a tiny pre-seeded SQLite database for a test scenario), place it under
a clearly labelled sub-directory such as `nodes/Node_XX_Name/tests/fixtures/`
and add an explicit entry to the `ALLOWLIST` in
`scripts/check_repo_hygiene.py`.  Use the smallest possible fixture and keep
it in a format that makes its purpose clear.  Do not commit runtime-generated
databases or logs under any circumstances.

### Checklist before opening a PR

1. Run `python scripts/check_repo_hygiene.py` — it must exit `0`.
2. Confirm no `.pid`, `.log`, `.db`, or `.sqlite` files appear in `git status`.
3. Confirm no `__pycache__/` or `.pytest_cache/` directories appear in
   `git status`.
4. If you changed `node_dependencies.json` or any `nodes/` directory, run
   `make regen-all` and include the regenerated governance docs in your commit.

## Regenerating Governance Artifacts

The human-readable governance documents (`docs/NODE_SYSTEM_AUDIT.md` and
`docs/NODE_ACTIVE_MANIFEST.md`) are **generated companions** to the canonical
machine-readable sources.  Do not edit them by hand.

| Artifact | Canonical source | How to regenerate |
|----------|-----------------|-------------------|
| `docs/node_audit_report.json` | computed by audit script | `make audit-regen` |
| `docs/NODE_SYSTEM_AUDIT.md` | `docs/node_audit_report.json` | `make audit-regen` |
| `docs/NODE_ACTIVE_MANIFEST.md` | `node_dependencies.json` + `docs/node_audit_report.json` | `make manifest-regen` |

To refresh all three in one step:

```bash
make regen-all
```

See `docs/MAINTAINER_RUNBOOK.md §11` for the full workflow, including when to
regenerate, how to respond to CI failures, and the end-to-end node-addition
workflow.

## Android Client

The Android client code belongs **exclusively** in the
[DannyFish-11/galaxy-android](https://github.com/DannyFish-11/galaxy-android)
repository.  Do **not** add Kotlin, Gradle, or Android-specific build files to
this repository.  The server-side AIP v3.0 bridge lives in
`galaxy_gateway/android_bridge.py`.
