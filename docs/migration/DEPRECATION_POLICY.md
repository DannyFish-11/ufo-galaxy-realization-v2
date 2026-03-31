# Deprecation Policy

**Version:** 1.0
**Status:** Canonical — Batch PR-1
**Owner:** Architecture / Governance

---

## Purpose

This policy governs how code is deprecated and eventually removed in the
Galaxy-Nexus codebase.  It applies to all modules, API routes, CLI entry
points, scripts, and configuration paths.

---

## 1. Deprecation Levels

| Level | Label | Meaning |
|-------|-------|---------|
| **D0** | `ACTIVE` | Current, supported, may receive new features |
| **D1** | `SOFT_DEPRECATED` | Still functional; new code must not call it; migration in progress |
| **D2** | `HARD_DEPRECATED` | Will be removed in the next cleanup batch; callers must migrate |
| **D3** | `TOMBSTONE` | Module is a re-export shim only; contains no logic; scheduled for deletion |
| **D4** | `DELETED` | Removed; any lingering references are bugs |

---

## 2. Deprecation Process

### Step 1 — Mark
Add a module-level docstring annotation:

```python
"""
.. deprecated:: <PR or version>
    Reason: <why deprecated>.
    Use :mod:`<canonical.module>` instead.
"""
```

And set the appropriate marker in `core/legacy_purge_registry.py` (if the
module is registered there).

### Step 2 — Notify
- Update `docs/migration/LEGACY_SURFACE_INVENTORY.md` with the new status.
- Add an entry in `CHANGELOG.md` under the PR that performs the deprecation.
- If the deprecated surface has external consumers, emit a `DeprecationWarning`
  at import time (D2+ only).

### Step 3 — Freeze
Once a module reaches D1:
- No new feature code may be added.
- Bug fixes are allowed only if they prevent data corruption or security issues.
- The CI debt-freeze guardrail will flag attempts to add business logic.

### Step 4 — Remove
Apply the removal criteria defined in
[`REMOVAL_CRITERIA.md`](REMOVAL_CRITERIA.md).  Removal happens in a
dedicated cleanup PR, not mixed with feature work.

---

## 3. Compatibility Shims

A **compatibility shim** is a module that exists solely to re-export symbols
from a new canonical location so that old import paths continue to work
during a transition period.

### Approved shim zones

Shims MUST reside in one of these approved zones:

```
core/legacy/
core/legacy_adapters/
galaxy_gateway/legacy/
windows_client/_legacy/
```

### Shim policy

- Every shim MUST carry a `.. deprecated::` docstring identifying its target.
- Shims MUST NOT contain business logic — only `from canonical.module import *`
  or delegating wrappers.
- New shims outside approved zones are **forbidden** and will be flagged by CI.
- Shims must be listed in `docs/migration/LEGACY_SURFACE_INVENTORY.md`.

---

## 4. `except ImportError` Fallback Pattern

Inline `except ImportError` fallbacks (defining substitute classes/functions
inside the `except` block) are an **anti-pattern** that obscures runtime
dependency state.  New code MUST NOT use this pattern.

Existing cases are inventoried in
[`LEGACY_SURFACE_INVENTORY.md`](LEGACY_SURFACE_INVENTORY.md).
They are tracked as D1 debt and will be resolved by Batch PR-5.

**Allowed alternative:**

```python
# Declare the optional dependency explicitly at module top:
try:
    from optional_lib import Feature
    _FEATURE_AVAILABLE = True
except ImportError:
    _FEATURE_AVAILABLE = False

# Guard usage:
if _FEATURE_AVAILABLE:
    ...
```

This is permitted only when the guarded feature is genuinely optional and
the availability flag is exported for introspection.

---

## 5. API Route Deprecation

1. Add `deprecated=True` to the FastAPI route decorator.
2. Return a `Deprecation` header in the response.
3. Suppress the route from generated OpenAPI docs after 2 cleanup batches.
4. Remove with the cleanup batch that retires the corresponding module.

---

## 6. Configuration Path Deprecation

1. Add the old key to `core/unified_config.py`'s `DEPRECATED_KEYS` mapping.
2. Log a `DeprecationWarning` when the old key is read.
3. Remove after one batch cycle.

---

## 7. Enforcement

The CI `debt-freeze` job (`.github/workflows/guardrails.yml`) will:

- **Warn** when new `except ImportError` fallback patterns are added outside
  approved files.
- **Warn** when new compatibility shims appear outside approved zones.
- **Warn** when new root-level placeholder Markdown report files are added.
- **Fail** (strict) when new files exceed the line-count budget defined in
  `scripts/check_file_complexity.py`.

Warnings become failures in Batch PR-3 once the baseline is clean.
