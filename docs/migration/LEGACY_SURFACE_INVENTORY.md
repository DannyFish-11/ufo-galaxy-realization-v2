# Legacy Surface Inventory

**Version:** 1.0
**Status:** Canonical — Batch PR-1
**Owner:** Architecture / Governance
**Last updated:** 2026-03-31

---

## Purpose

This document is the **structured inventory of all legacy, deprecated, and
compatibility surfaces** in the Galaxy-Nexus codebase.  It is the primary
input for all Batch cleanup PRs.  Every entry carries a deprecation level
(per `DEPRECATION_POLICY.md`) and a target removal batch.

---

## Deprecation Level Key

| Level | Label | Meaning |
|-------|-------|---------|
| D0 | `ACTIVE` | Fully supported |
| D1 | `SOFT_DEPRECATED` | No new features; migration in progress |
| D2 | `HARD_DEPRECATED` | Will be removed next batch |
| D3 | `TOMBSTONE` | Re-export shim only; no logic |
| D4 | `DELETED` | Already removed |

---

## 1. Deprecated Modules

| Module | Level | Canonical Replacement | Target Removal | Notes |
|--------|-------|-----------------------|---------------|-------|
| `galaxy_main_loop_l4.py` | D3 | `core.galaxy_main_loop_l4_enhanced` | Batch PR-4 | Root-level tombstone re-export shim; exports `_PRIVATE_AVAILABLE` flags in `__all__` (anti-pattern) |
| `galaxy_gateway/aip_protocol_v2.py` | D3 | `galaxy_gateway.protocol.aip_v3` + `galaxy_gateway.protocol.compat` | Batch PR-4 | Hard `raise ImportError` on import; v3 protocol guard enforced in CI |
| `galaxy_gateway/task_decomposer.py` | D1 | `galaxy_gateway/orchestrator/` | Batch PR-5 | Marked deprecated in docstring |
| `galaxy_gateway/capability_registry.py` | D1 | `core/capability_bus.py` | Batch PR-5 | Deprecated docstring; moved to `galaxy_gateway/legacy/` |
| `galaxy_gateway/task_router.py` | D1 | `galaxy_gateway/routing/` package | Batch PR-5 | Deprecated docstring |
| `core/capability_manager.py` | D1 | `core/capability_bus.py` | Batch PR-5 | Deprecated docstring |
| `core/capability_orchestrator.py` | D1 | `core/capability_bus.py` | Batch PR-5 | Deprecated docstring; compat shim present |
| `dashboard/backend/main.py` | D2 | `core/routes/*` (canonical REST API) | Batch PR-5 | Legacy headless backend; marked in `dashboard/LEGACY_SURFACE.md` |
| `fusion/unified_orchestrator.py` | D1 | `core/unified/entrypoint_router.py` | Batch PR-5 | Deprecated docstring |
| `galaxy_gateway/orchestrator/task_orchestrator.py` | D1 | `galaxy_gateway/orchestrator/galaxy_orchestrator.py` | Batch PR-5 | Deprecated docstring |

---

## 2. Legacy Paths / Surfaces

| Surface | Path | Level | Status Note |
|---------|------|-------|-------------|
| Dashboard backend | `dashboard/backend/main.py` | D2 | Headless; frontend deleted PR-1; backend retirement pending |
| Dashboard frontend | `dashboard/frontend/` | D4 | **Permanently deleted** in PR-1; do not recreate |
| Legacy status board | `windows_client/status_board.py` | D1 | Superseded by `windows_client/status_board_v2/` |
| Legacy Windows client | `windows_client/_legacy/` | D1 | Archived; read-only |
| Core legacy adapters | `core/legacy_adapters/` | D1 | Transition adapters for connection_manager, device_agent_manager |
| Core legacy dir | `core/legacy/` | D1 | Retired code; no new features allowed |
| Gateway legacy dir | `galaxy_gateway/legacy/` | D1 | Retired capability_registry, task_decomposer copies |
| AIP v2 compat layer | `galaxy_gateway/protocol/compat.py` | D1 | Translation layer; will be removed when v2 callers are gone |

---

## 3. Startup Surfaces

| Surface | File | Level | Notes |
|---------|------|-------|-------|
| **Canonical launcher** | `main.py` → `unified_launcher.py` | D0 | Active; `main.py` delegates via `subprocess.call` |
| Direct launcher call | `unified_launcher.py` | D0 | Equivalent; used by CI |
| L4 root shim | `galaxy_main_loop_l4.py` | D3 | Tombstone; delegates to `core.galaxy_main_loop_l4_enhanced` |
| Legacy start scripts (if present) | `start_galaxy.py`, `start_l4.py` | D2 | Compatibility wrappers; `main.py` is canonical |
| Shell launchers | `start.sh`, `start_unified.sh`, `start.bat` | D0 | Dev convenience; all ultimately call `main.py` |

---

## 4. Deployment Surfaces

| Surface | File | Level | Notes |
|---------|------|-------|-------|
| Primary Dockerfile | `Dockerfile` | D0 | Canonical main service image |
| Gateway Dockerfile | `Dockerfile.gateway` | D0 | Canonical gateway image |
| Node Dockerfile | `Dockerfile.node` | D0 | Canonical node image |
| Dev compose | `docker-compose.yml` | D0 | Standard dev stack (14 KB) |
| Production compose | `docker-compose.production.yml` | D0 | Production overrides (6 KB) |
| Full compose | `docker-compose.full.yml` | D1 | **OVERSIZED** (144 KB); targeted for decomposition in Batch PR-3 |
| Kimi compose | `docker-compose.kimi.yml` | D1 | Kimi-model-specific variant; review for merge or deletion |
| systemd units | `systemd/*.service` | D0 | Linux daemon deployment |

---

## 5. Import Fallback (`except ImportError`) Cases

These are locations where an `except ImportError` block defines substitute
symbols inline.  All are D1 debt — no new cases may be added.

| File | Approx. line | Guarded import | Action |
|------|-------------|----------------|--------|
| `unified_launcher.py` | ~60 | `nodes.common.cors_config` | Extract to optional-deps declaration |
| `core/scheduler.py` | ~323 | (runtime scheduling lib) | Make hard dep or remove fallback |
| `core/openclawd_heartbeat.py` | ~62 | (heartbeat lib) | Make hard dep or remove fallback |
| `core/nodes/node_fabric_registry.py` | ~497, ~579 | (fabric libs) | Make hard dep or remove fallback |
| `core/academic_retrieval.py` | ~78 | (retrieval lib) | Make hard dep or remove fallback |
| `core/mcp_gateway.py` | ~262 | (MCP lib) | Make hard dep or remove fallback |
| `core/routes/protocols.py` | 11+ locations | (protocol libs) | Audit and consolidate |
| `core/routes/ai.py` | 4 locations | (AI provider libs) | Declare as optional extras |
| `core/routes/devices.py` | ~600 | (device lib) | Make hard dep or remove fallback |
| `core/routes/vision.py` | ~72 | (vision lib) | Declare as optional extra |
| `core/routes/command.py` | ~56 | (command lib) | Make hard dep or remove fallback |
| `core/openclawd_memory_backflow.py` | ~41, ~52 | (memory libs) | Make hard dep or remove fallback |
| `core/openclawd.py` | 3 locations | (internal modules) | Refactor as part of Batch PR-2 decomposition |
| `core/monitoring.py` | ~429 | (monitoring lib) | Declare as optional extra |
| `dashboard/backend/main.py` | 5+ locations | (core modules) | Retire entire file in Batch PR-5 |

---

## 6. Compatibility Shims

| Shim | Location | Points to | Level | Target Batch |
|------|----------|-----------|-------|-------------|
| `galaxy_main_loop_l4.py` | repo root | `core.galaxy_main_loop_l4_enhanced` | D3 | PR-4 |
| `galaxy_gateway/aip_protocol_v2.py` | `galaxy_gateway/` | Raises `ImportError` (guard) | D3 | PR-4 (verify no callers first) |
| `core/legacy_adapters/connection_manager_adapter.py` | `core/legacy_adapters/` | `core/unified/connection_manager.py` | D1 | PR-5 |
| `core/legacy_adapters/device_agent_manager_adapter.py` | `core/legacy_adapters/` | `core/unified/device_manager.py` | D1 | PR-5 |
| `core/orchestration_authority/legacy_paths.py` | `core/orchestration_authority/` | Various canonical paths | D1 | PR-5 |
| `core/routes/compat.py` | `core/routes/` | Canonical route handlers | D1 | PR-5 |
| `galaxy_gateway/legacy/capability_registry.py` | `galaxy_gateway/legacy/` | `core/capability_bus.py` | D1 | PR-5 |
| `galaxy_gateway/legacy/task_decomposer.py` | `galaxy_gateway/legacy/` | `galaxy_gateway/orchestrator/` | D1 | PR-5 |

---

## 7. Oversized Files Targeted for Decomposition

Files that exceed the current grandfathered line-count budget and are
targeted for splitting in upcoming batches.

| File | Lines (approx) | Budget | Batch | Strategy |
|------|---------------|--------|-------|----------|
| `core/openclawd.py` | ~7120 | 7500 (grandfathered) | PR-2 | Split into domain sub-modules: `request_handler`, `model_dispatch`, `agent_runner`, `state_machine` |
| `core/routes/projection.py` | ~3172 | 3500 (grandfathered) | PR-3 | Split by projection type: `runtime_projection`, `topology_projection`, `canonicalization` |
| `core/api_routes.py` | ~2758 | 3000 (grandfathered) | PR-3 | All new routes go to `core/routes/`; existing routes migrated progressively |
| `core/command_router.py` | ~2621 | 3000 (grandfathered) | PR-3 | Split: `command_parser`, `device_dispatch_bridge`, `orchestration_policy` |
| `core/multi_llm_router.py` | ~1847 | 2000 (grandfathered) | PR-4 | Split: `provider_selector`, `failover_policy`, `llm_state` |
| `docker-compose.full.yml` | N/A (144 KB) | N/A | PR-3 | Decompose into profile-scoped compose files using `extends` or Compose profiles |

---

## 8. Root-Level Placeholder Report Files

Files < 300 bytes at repo root that are stubs or redirect notices.  These
will be merged into `docs/reports/` in Batch PR-6 once confirmed as pure
placeholders.

| File | Size (bytes) | Action |
|------|-------------|--------|
| `SQL_FIXES.md` | 103 | Move content to `docs/reports/` then delete |
| `UI_ASSETS.md` | 103 | Move content to `docs/reports/` then delete |
| `EVAL_FIXES.md` | 105 | Move content to `docs/reports/` then delete |
| `SECURITY_FIXES.md` | 113 | Move content to `docs/reports/` then delete |
| `FULL_SYSTEM_AUDIT.md` | 119 | Move content to `docs/reports/` then delete |
| `ARCHITECTURE_REVIEW.md` | 123 | Move content to `docs/reports/` then delete |
| `IMPLEMENTATION_SUMMARY.md` | 129 | Move content to `docs/reports/` then delete |
| `L4_SYSTEM_STATUS_REPORT.md` | 131 | Move content to `docs/reports/` then delete |
| `SYSTEM_INTEGRITY_REPORT.md` | 131 | Move content to `docs/reports/` then delete |
| `README_UI_L4_INTEGRATION.md` | 133 | Move content to `docs/reports/` then delete |
| `UI_L4_INTEGRATION_REPORT.md` | 133 | Move content to `docs/reports/` then delete |
| `R4_IMPLEMENTATION_SUMMARY.md` | 135 | Move content to `docs/reports/` then delete |
| `SYSTEM_DESIGN_INTEGRATION_SUMMARY.md` | 151 | Move content to `docs/reports/` then delete |

---

## 9. How to Update This Inventory

When a surface is **deprecated**, add it with level D1 and a target batch.

When a surface is **removed**, change its level to D4 and note the batch PR.

Raise a PR to update this file whenever the inventory changes.  The CI
`debt-freeze` job validates that newly detected surfaces are listed here.
