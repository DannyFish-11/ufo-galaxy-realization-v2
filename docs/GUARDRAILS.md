# Engineering Guardrails — PR-6

Lightweight but effective guardrails to prevent regressions: type checking,
secret scanning, and architecture/complexity enforcement.

---

## Overview

| Guardrail | Tool | CI job | Failure mode |
|---|---|---|---|
| Type checking | mypy | `type-check` | Strict on selected modules, warn elsewhere |
| Secret scanning | gitleaks | `secret-scan` | Hard fail on any detected secret |
| Import boundaries | `scripts/check_import_boundaries.py` | `import-boundaries` | Warning (strict mode available) |
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

Currently runs in **warning mode** (CI reports violations but doesn't block).
Once existing violations are resolved, switch the CI step to use `--strict`.

**Run locally:**

```bash
# Warning mode (default)
python scripts/check_import_boundaries.py

# Strict mode (exits 1 on violations)
python scripts/check_import_boundaries.py --strict
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
