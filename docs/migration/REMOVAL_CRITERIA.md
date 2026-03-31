# Removal Criteria

**Version:** 1.0
**Status:** Canonical — Batch PR-1
**Owner:** Architecture / Governance

---

## Purpose

This document defines the concrete, verifiable criteria that must ALL be met
before any deprecated module, route, shim, or legacy surface can be safely
deleted.

---

## 1. Universal Prerequisites (all removals)

All of the following must be true before anything is deleted:

| # | Criterion | How to verify |
|---|-----------|---------------|
| R1 | **No active callers** — zero imports of the deprecated symbol in `core/`, `galaxy_gateway/`, `enhancements/`, `tests/`, `scripts/`, `launcher/` | `grep -r "from <module>" --include="*.py"` returns empty |
| R2 | **Canonical replacement exists and is tested** — the replacement has passing unit/integration tests | CI green on the replacement module's test file |
| R3 | **Migration documented** — the migration path is described in `LEGACY_SURFACE_INVENTORY.md` and `CHANGELOG.md` | Doc review |
| R4 | **No API contract break** — if the deprecated surface is HTTP-exposed, the route has been removed from OpenAPI spec, and downstream consumers have been notified | API version changelog |
| R5 | **Tombstone or adapter in place ≥ 1 batch cycle** — the shim/tombstone must have existed for at least one full cleanup batch before final deletion | Git log |
| R6 | **Batch PR author sign-off** — the removal PR links back to the deprecation PR and includes a checklist confirming R1–R5 | PR description |

---

## 2. Module-Specific Criteria

### 2.1 Tombstone / Re-export Shims

Additional criteria beyond R1–R6:

| # | Criterion |
|---|-----------|
| T1 | All `__all__` exports from the shim are imported from the canonical module in the shim body (no dangling re-exports). |
| T2 | The shim's import in every consumer has been replaced with the canonical path and the PR contains a commit showing the migration. |

### 2.2 Legacy Adapters (`core/legacy_adapters/`)

| # | Criterion |
|---|-----------|
| A1 | All callers have been migrated to call `EntrypointRouter` or the canonical manager directly. |
| A2 | The adapter's test file (if any) has been deleted or updated to test the canonical path. |
| A3 | `scripts/audit_udm_write_paths.py` reports zero violations after deletion. |

### 2.3 `dashboard/backend/main.py`

| # | Criterion |
|---|-----------|
| D1 | All API routes in `dashboard/backend/main.py` have canonical equivalents in `core/routes/`. |
| D2 | No downstream consumer (Android app, Windows client, scripts) is calling dashboard-only routes. |
| D3 | `dashboard/__init__.py` deprecation notice has been present for ≥ 1 batch cycle. |

### 2.4 Root-level Placeholder Markdown Files

Files like `SQL_FIXES.md`, `EVAL_FIXES.md`, `UI_ASSETS.md`, etc. (< 300 bytes)
at repo root:

| # | Criterion |
|---|-----------|
| P1 | File is a placeholder (< 300 bytes or contains only a redirect/stub notice). |
| P2 | Any meaningful content has been moved to `docs/reports/` or appropriate docs sub-directory. |
| P3 | No external link (in README, QUICKSTART, etc.) still points to the root file. |

### 2.5 `except ImportError` Fallback Patterns

| # | Criterion |
|---|-----------|
| I1 | The guarded import is either made a hard dependency in `requirements.txt` or removed entirely. |
| I2 | Any fallback class/function defined in the `except` block has been deleted, not just the `try/except` wrapper. |

---

## 3. Batch Cleanup Cadence

| Batch | Scope | Target state |
|-------|-------|-------------|
| PR-1 (this PR) | Governance only — no deletions | Inventory complete, guardrails active |
| PR-2 | Decompose `core/openclawd.py` | Tombstone shim in place |
| PR-3 | Decompose `core/api_routes.py`; clean docker-compose | Tombstone shim in place |
| PR-4 | Remove tombstone shims from PR-2 | R1–R6 verified, shims deleted |
| PR-5 | Retire `dashboard/backend/main.py` and `core/legacy_adapters/` | D1–D3 verified |
| PR-6 | Clean root-level placeholder Markdown; fix `except ImportError` patterns | P1–P3 and I1–I2 verified |

---

## 4. Emergency Removal

If a deprecated surface is found to introduce a security vulnerability, it
may be removed immediately without satisfying the R5 "one batch cycle" wait.
The removal PR must:

1. Reference the security advisory or CVE.
2. Include a fix-forward migration if callers exist.
3. Pass CI before merge.
