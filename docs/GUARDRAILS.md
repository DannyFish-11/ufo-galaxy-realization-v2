# Engineering Guardrails — PR-6

Lightweight but effective guardrails to prevent regressions: type checking,
secret scanning, and architecture/complexity enforcement.

---

## Overview

| Guardrail | Tool | CI job | Failure mode |
|---|---|---|---|
| Type checking | mypy | `type-check` | Strict on selected modules, warn elsewhere |
| Secret scanning | gitleaks | `secret-scan` | Hard fail on any detected secret |
| Import boundaries | `scripts/check_import_boundaries.py` | `import-boundaries` | Hard fail (`--strict` since 2026-08-31) |
| File complexity | `scripts/check_file_complexity.py` | `file-complexity` | Hard fail for new violations |

---

## A. Type checking (mypy)

**Config:** `mypy.ini` (per-module settings), `pyproject.toml` (`[tool.mypy]`)

**Strategy:** gradual adoption.

- `core/canonical_execution_chain.py`, `core/mainline_convergence.py`,
  and `galaxy_gateway/routing/*` are checked **strictly** — mypy errors there
  fail CI.
- All other modules use `ignore_errors = True` or `follow_imports = silent`
  so legacy code doesn't block the PR.

**Run locally:**

```bash
# Check all (gradual baseline — errors in legacy modules are suppressed)
mypy core/ galaxy_gateway/ --config-file mypy.ini

# Check only the strictly-enforced modules
mypy core/canonical_execution_chain.py core/mainline_convergence.py \
     galaxy_gateway/routing/ --config-file mypy.ini
```

**Tightening over time:** To add a module to strict checking, remove its
`ignore_errors = True` entry from `mypy.ini` (or delete the stanza).

---

## B. Secret scanning (gitleaks)

**Config:** `.gitleaks.toml`

Uses the [gitleaks](https://github.com/gitleaks/gitleaks) default ruleset plus
three Galaxy-specific patterns (Galaxy API keys, OpenAI keys, Anthropic keys).

Known-safe false positives (example configs, test fixtures) are allow-listed in
`.gitleaks.toml`.

**Run locally:**

```bash
# Requires gitleaks to be installed: https://github.com/gitleaks/gitleaks#installing
gitleaks detect --config .gitleaks.toml --redact --source .

# Check only staged files (pre-commit style)
gitleaks protect --config .gitleaks.toml --staged
```

---

## C. Structural guardrails

### C1. Import boundaries

**Script:** `scripts/check_import_boundaries.py`

Enforces that lower-level layers do not import from higher-level layers:

| Rule | Source | Forbidden import |
|---|---|---|
| `core` ↛ `galaxy_gateway` | `core/` | `galaxy_gateway.*` |
| `core` ↛ `dashboard` | `core/` | `dashboard.*` |
| `core` ↛ `enhancements` | `core/` | `enhancements.*` |

Runs in **`--strict`** mode since 2026-08-31 — violations block CI.

It used to run warning-only, with 70 pre-existing violations across 30 files
(`core/` → `galaxy_gateway/` 53, `core/` → `enhancements/` 17). A gate that
always warns and never fails is not a gate: it stops distinguishing "this got
worse today" from "it has always been like this", so everyone learns to ignore
it — and genuinely new violations ride in behind the noise.

#### How `core/` reaches the upper layers now

All 70 sites had the same shape — an optional upper-layer component with a
graceful-degradation branch:

```python
try:
    from galaxy_gateway.android_bridge import android_bridge
    ...
except Exception:
    <degrade>
```

They now go through **`core/upper_ports.py`**, which resolves a *port name*
against a binding table in **`config/upper_layer_ports.json`**:

```python
bridge = upper_ports.resolve("gateway.android_bridge.android_bridge")
```

`resolve()` is `importlib.import_module` + `getattr` — byte-for-byte the same
lookup the import statement performed. Failure raises `PortUnavailable`, which
**subclasses `ImportError`**, so every existing `except ImportError` /
`except Exception` degradation branch still catches it unchanged.

**What this buys, and what it does not.** It buys three things: `core/` no
longer names an upper layer in code, so the rule is mechanically checkable;
57 upward dependencies that were scattered across 30 files now sit in one
auditable table; and `upper_ports.register()` lets the gateway — or a test —
inject an implementation, which is the actual inversion seam (the table is just
the default when nobody injects).

It does **not** decouple anything. Those code paths still need the upper layer
at runtime. Late binding is not decoupling; delete `galaxy_gateway/` and the
affected features stop working — they just fail in the existing degradation
branch instead of at import time.

Adding a new upward dependency means adding a row to the binding table, which
is exactly the point: it shows up in review as a table entry instead of hiding
in the middle of a function.

`tests/test_upper_ports_bindings_are_real.py` replaces the compile-time check
the import statement used to provide: every declared port must actually resolve,
every port used in `core/` must be declared, and no declared port may be unused.

**Run locally:**

```bash
python scripts/check_import_boundaries.py --strict
pytest tests/test_upper_ports_bindings_are_real.py
```

### C2. File complexity budget

**Script:** `scripts/check_file_complexity.py`

Thresholds for Python source files in `core/`, `galaxy_gateway/`,
`enhancements/`, and `dashboard/`:

| Level | Lines | Action |
|---|---|---|
| Warning | > 1,000 | Reported; non-blocking |
| Error | > 2,000 | Fails CI (new files only) |

Existing over-budget files are **grandfathered** in `GRANDFATHERED` dict at
their current size — they may not grow, but don't need to be fixed immediately.

**Run locally:**

```bash
# Warning mode
python scripts/check_file_complexity.py

# Strict mode (CI uses this)
python scripts/check_file_complexity.py --strict
```

---

## Tightening the guardrails

1. **Type checking:** Remove `ignore_errors = True` entries from `mypy.ini` one
   module at a time, fix the reported type errors, then commit.

2. **Import boundaries:** Fix the violations listed by
   `check_import_boundaries.py`, then flip the CI job's `--strict` flag.

3. **File complexity:** When refactoring a grandfathered file, lower its
   entry in `GRANDFATHERED` or remove it once it's under 2 000 lines.
