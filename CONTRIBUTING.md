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

## Adding a New Node

1. Create a directory under `nodes/` following the naming convention `Node_XX_Name/`.
2. Each node directory must contain at minimum:
   - `main.py` – entry point with the node's core logic
   - `fusion_entry.py` – integration shim used by the fusion layer
3. **Register the node in `node_dependencies.json`.**  This file is the
   machine-readable source of truth for the node registry and startup policy.
   A node that is not listed there is not considered part of the active system,
   regardless of whether its directory exists on disk.

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

## Android Client

The Android client code belongs **exclusively** in the
[DannyFish-11/galaxy-android](https://github.com/DannyFish-11/galaxy-android)
repository.  Do **not** add Kotlin, Gradle, or Android-specific build files to
this repository.  The server-side AIP v3.0 bridge lives in
`galaxy_gateway/android_bridge.py`.
