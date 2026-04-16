# Legacy Surfaces — Authoritative Registry

> **PR-8** — Remove retired legacy surfaces, finalize documentation, and
> enforce non-regression architecture rules.
>
> **PR-10** — Compatibility-surface retirement plan: explicit inventory,
> tier classification, and governed convergence roadmap.
> See [`core/compat_surface_retirement.py`](../core/compat_surface_retirement.py)
> for the machine-checkable authority module.

This document is the authoritative registry of all legacy, deprecated, and
compatibility-only surfaces in the repository.  Every entry is categorised by
its current lifecycle status and lists the canonical replacement.

---

## Status definitions

| Status | Meaning |
|--------|---------|
| **DELETED** | File has been physically removed from the repository.  Must not be reintroduced.  Non-regression CI checks enforce this. |
| **DEPRECATED** | File still exists but emits `DeprecationWarning` on import / use.  Scheduled for deletion in a future batch PR.  Do not add new callers. |
| **LEGACY_COMPAT** | File still exists and is actively required by callers that have not yet been migrated.  Must not be used for new work. |
| **ACTIVE** | File is part of the canonical runtime surface. |

---

## 1. Fully deleted in PR-8

These files were physically removed.  Non-regression CI (`scripts/check_legacy_regression.py`) will fail if they are re-added.

| Deleted file | Was | Canonical replacement |
|---|---|---|
| `windows_client/_legacy/START_CLIENT.bat` | Legacy F12 sidebar launcher (hard-errored on execution) | `start.bat` or `python unified_launcher.py` |
| `windows_client/_legacy/start_galaxy_client.bat` | Legacy Gateway WebSocket client launcher (hard-errored on execution) | `python unified_launcher.py`; configure `GALAXY_GATEWAY_URL` via `.env` |

---

## 2. Deprecated — present but must not be extended

These files still exist, emit `DeprecationWarning`, and have no remaining
runtime callers outside tests.  They may be deleted in a future batch PR.

| File | Deprecation level | Canonical replacement | Notes |
|---|---|---|---|
| `launcher/config_manager.py` | **D2 (HARD_DEPRECATED)** — removal target was Batch PR-5 | `core.unified.config_manager.get_unified_config_manager()` for general config; `core.port_config.get_node_port()` for port lookups | Emits `DeprecationWarning` on import.  No production callers remain; only referenced in deprecation tests. |
| `fusion/unified_orchestrator.py` | **DEPRECATED** | `galaxy_gateway.orchestrator.GalaxyOrchestrator` | Still imported by `fusion/start_fusion.py` and `fusion/demo_e2e.py` (demo/integration area).  Registered in `core/orchestration_authority/legacy_paths.py`. |

---

## 3. Legacy-compat surfaces — still active, explicitly bounded

These surfaces still carry production traffic but must not be extended and
are explicitly bounded as compatibility layers.

| Surface | Status | Canonical replacement | Removal condition |
|---|---|---|---|
| `core/routes/compat.py` | **LEGACY_COMPAT (D1)** | `core/routes/devices.py` (`/api/v1/devices/*`) | Remove only when all legacy Android/device callers are confirmed migrated to `/api/v1/devices/*`. |
| `dashboard/backend/main.py` | **LEGACY_COMPAT** — headless only | `core/api_routes.py` (canonical REST authority); `windows_client/status_board_v2/` (canonical status UI) | Dashboard frontend deleted in PR-1.  Backend retained headless for transition-period compatibility only.  Must NOT define system structure or claim status authority. |

---

## 4. Canonical runtime surfaces (reference)

Use these as the authoritative targets when migrating away from legacy surfaces.

### Startup
| Surface | Path | Notes |
|---|---|---|
| **Canonical startup** | `main.py` → `unified_launcher.py` | Single authoritative entry point |
| **Windows bootstrap** | `start.bat` | Delegates to `unified_launcher.py` |

### API authority
| Surface | Path | Notes |
|---|---|---|
| **Canonical REST API** | `core/api_routes.py` | `CANONICAL_API_ROUTES_AUTHORITY` sentinel |
| **Domain routes** | `core/routes/{health,devices,nodes,command,...}.py` | One module per domain |

### Configuration authority
| Surface | Path | Notes |
|---|---|---|
| **Canonical config** | `core/unified_config.py` | `get_unified_config_manager()` |
| **Port config** | `core/port_config.py` | `get_node_port()` |

### Orchestration authority
| Surface | Path | Notes |
|---|---|---|
| **Canonical orchestration** | `core/e2e_orchestrator.py` | `process_user_input()` |
| **OpenClawd** | `openclawd.py` | Top-level kernel |
| **CommandRouter** | `core/command_router.py` | Command dispatch |
| **DeviceRouter** | `galaxy_gateway/device_router.py` | Terminal WebSocket sender |

### Desktop status surface
| Surface | Path | Notes |
|---|---|---|
| **Canonical desktop status** | `windows_client/status_board_v2/` | Projection-driven; reads `GET /api/v1/projection/runtime` |

---

## 5. Non-regression guardrails

The following CI checks prevent reintroduction of removed legacy paths:

| Script | CI job | Checks |
|---|---|---|
| `scripts/check_legacy_regression.py` | `legacy-regression-guard` (guardrails.yml) | Deleted files are not reintroduced; no new `.bat` launchers in `windows_client/`; no new compat shims outside approved zones |
| `scripts/check_debt_freeze.py` | `debt-freeze` (guardrails.yml) | New root-level placeholder docs; new compat shims outside approved zones; forbidden `except ImportError` fallback patterns |

---

## 6. Legacy path registry

All legacy and deleted paths are also registered in:

```
core/orchestration_authority/legacy_paths.py
```

This module provides `LEGACY_PATH_REGISTRY`, `LEGACY_ORCHESTRATOR_PATHS`, and
`PR8_DELETED_PATHS` for programmatic queries.  The non-regression script reads
`PR8_DELETED_PATHS` directly to enumerate files that must not reappear.

---

## 7. PR-10 Compatibility-surface retirement roadmap

**Authority module:** `core/compat_surface_retirement.py`
(`COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY` sentinel)

PR-10 introduces an explicit, machine-checkable retirement plan for all
high-risk compatibility surfaces.  The goal is **governed convergence**:
the compat footprint must shrink, not grow, with each batch PR.

### Retirement tier key

| Tier | Meaning |
|------|---------|
| **TIER_1** | Immediate retirement target.  Minimal active callers; canonical replacement fully available.  Remove in next cleanup batch. |
| **TIER_2** | Near-term retirement target.  Some active callers; migration underway.  Must not receive new features.  Remove within 1–2 batches. |
| **TIER_3** | Long-term retirement target.  Active callers present; canonical replacement exists; migration must be tracked. |

### High-risk compatibility surfaces (PR-10 inventory)

The following surfaces carry `CompatSurfaceRisk.HIGH` — they are prominent
enough to be mistaken for canonical governance layers and must receive
earliest retirement attention.

| Surface | Status | Tier | Canonical replacement |
|---------|--------|------|-----------------------|
| `core/routes/compat.py` | LEGACY_COMPAT | **TIER_2** | `core/routes/devices.py` (`/api/v1/devices/*`) |
| `core/node_registry.NodeRegistry` | COMPAT_ONLY | **TIER_2** | `core.nodes.node_fabric_registry.NodeFabricRegistry` |
| `dashboard/backend/main.py` | LEGACY_COMPAT | **TIER_2** | `core/api_routes.py`; `windows_client/status_board_v2/` |
| `core.multi_llm_router.MultiLLMRouter` | LEGACY_COMPAT | **TIER_2** | `core.model_topology.topology_router.TopologyRouter` |

### TIER_1 surfaces (immediate retirement targets)

| Surface | Status | Removal condition |
|---------|--------|-------------------|
| `core/routes/_shared.node_status_cache` | COMPAT_ONLY | Remove when `core/routes/compat.py` is deleted |
| `galaxy_gateway/legacy/capability_registry.py` | HARD_DEPRECATED | No production callers remain; remove when deprecation tests are cleaned up |
| `galaxy_gateway/legacy/task_decomposer.py` | HARD_DEPRECATED | No production callers remain; remove when deprecation tests are cleaned up |
| `fusion/unified_orchestrator.py` | HARD_DEPRECATED | Remove when `fusion/start_fusion.py` and `fusion/demo_e2e.py` are migrated |
| `launcher/config_manager.py` | HARD_DEPRECATED | No production callers remain; remove when deprecation tests are cleaned up |

### Policy sentinels (PR-10)

- `HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY`
- `COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY`
- `RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY`
- `COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY`

---

*Last updated: PR-10 — Compatibility-surface retirement plan.*
