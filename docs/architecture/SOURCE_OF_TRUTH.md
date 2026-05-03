# Architecture Source of Truth

**Version:** 1.0
**Status:** Canonical — Batch PR-1
**Owner:** Architecture / Governance

---

## Purpose

This document is the **single authoritative reference** for the Galaxy-Nexus
system's canonical components, authority holders, and decision-making
surfaces.  Every pull request that touches architectural boundaries must
remain consistent with what is declared here, or must update this document
as part of the change.

---

## 1. Canonical Startup Chain

```
main.py  (bootstrap launcher — subprocess delegation only)
   └─► unified_launcher.py  (process bootstrap, service init, HTTP server)
          └─► core/desktop_presence_runtime.DesktopPresenceRuntime  (runtime shell)
                 └─► core/openclawd.OpenClawd  (subject core)
```

| Layer | File | Role | Authority |
|-------|------|------|-----------|
| Bootstrap shim | `main.py` | CLI entry, delegates via `subprocess.call` | None — pure delegation |
| Bootstrap launcher | `unified_launcher.py` | Process env, service start, uvicorn | Launcher only |
| Runtime shell | `core/desktop_presence_runtime.py` | Tri-state lifecycle, desktop readiness | `DESKTOP_PRESENCE_RUNTIME_AUTHORITY` |
| Subject core | `core/openclawd.py` | Request handling, model routing, agent dispatch | `OPENCLAWD_SUBJECT_AUTHORITY` |

**Rules:**
- `main.py` MUST remain a thin delegation shim.  No business logic here.
- `unified_launcher.py` MUST NOT handle requests or own lifecycle state beyond startup/shutdown.
- The subject lifecycle is owned exclusively by `DesktopPresenceRuntime` → `OpenClawd`.

---

## 2. Canonical API Authority

| Surface | File | Status |
|---------|------|--------|
| **Canonical REST API** | `core/api_routes.py` + `core/routes/` sub-modules | **CANONICAL** |
| Legacy management panel | `dashboard/backend/main.py` | LEGACY — transition compatibility only |
| Gateway HTTP surface | `galaxy_gateway/app.py` | CANONICAL — gateway-scoped routes |

**Rule:** New API endpoints MUST be added to `core/routes/` sub-modules.
`dashboard/backend/main.py` is deleted and MUST NOT be recreated.

---

## 3. Canonical Desktop / Status Surface

| Surface | Location | Status |
|---------|----------|--------|
| **Active Windows status board** | `windows_client/status_board_v2/` | **CANONICAL** |
| Legacy Windows shell | `windows_client/main.py` | **DELETED** — do not recreate |
| Legacy status board | `windows_client/status_board.py` | **DELETED** — do not recreate |
| Dashboard package | `dashboard/` | **DELETED** — do not recreate |

Authoritative status projection endpoint: `GET /api/v1/projection/runtime`
Contract: `contracts/desktop_status_projection.py` (`DesktopStatusProjection`)

---

## 4. Canonical Configuration Authority

| Config surface | File | Status |
|----------------|------|--------|
| **Runtime config** | `core/unified_config.py` | CANONICAL |
| Runtime example | `runtime/config.example.json` | Reference template |
| Project config | `config.json` | Tolerated for local dev — must not contain secrets |
| Environment secrets | `.env` (runtime only, not committed) | `.env.example` is the template |

**Rule:** New configuration keys MUST be registered in `core/unified_config.py`.
Hard-coded or file-scattered config paths are forbidden in new code.

---

## 5. Canonical Execution Chain

```
Ingress (HTTP / WS / Android)
   └─► EntrypointRouter  (core/unified/entrypoint_router.py)
          └─► OpenClawd  (core/openclawd.py — OPENCLAWD_SUBJECT_AUTHORITY)
                 └─► CommandRouter  (core/command_router.py — COMMAND_ROUTER_ORCHESTRATION_AUTHORITY)
                        └─► DeviceRouter  (galaxy_gateway/device_router.py — DEVICE_ROUTER_DISPATCH_AUTHORITY)
                               └─► Device  (WebSocket / AIP v3)
```

Declared in: `core/canonical_execution_chain.py`
Convergence stages: `core/mainline_convergence.py` (11 stages)

---

## 6. Known Legacy / Deprecated Surfaces

See [`LEGACY_SURFACE_INVENTORY.md`](../migration/LEGACY_SURFACE_INVENTORY.md) for the full structured inventory.

Summary:
- `galaxy_main_loop_l4.py` — root tombstone shim → `core/galaxy_main_loop_l4_enhanced`
- `galaxy_gateway/aip_protocol_v2.py` — AIP v2 compat shim → `galaxy_gateway/protocol/aip_v3.py`
- `core/architecture_*.py` shims → `tools/architecture/`
- `dashboard/backend/main.py` — legacy headless backend, retirement pending
- `core/legacy_adapters/` — transition-period adapters, scheduled for removal
- `core/legacy/` — retired code, must not receive new features

---

## 7. Approved Legacy Zones

The following directories are **approved legacy zones** and may contain
compatibility shims during the active cleanup program:

```
core/legacy/
core/legacy_adapters/
galaxy_gateway/legacy/
windows_client/_legacy/
```

Compatibility shims placed **outside** these zones without explicit approval
constitute new technical debt and will be flagged by CI.

---

## 8. CI Guardrail References

| Guardrail | Workflow job | Mode |
|-----------|-------------|------|
| File size budget | `guardrails.yml / file-complexity` | Strict (new files) |
| Import boundaries | `guardrails.yml / import-boundaries` | Warning |
| Root placeholder reports | `guardrails.yml / debt-freeze` | Warning |
| Forbidden `except ImportError` fallbacks | `guardrails.yml / debt-freeze` | Warning |
| Compatibility shims outside approved zones | `guardrails.yml / debt-freeze` | Warning |
| Secret scanning | `guardrails.yml / secret-scan` | Strict |
| Type checking | `guardrails.yml / type-check` | Strict (new modules) |

---

## 9. Next Steps (Batch PR-2 and beyond)

- **Batch PR-2**: Decompose `core/openclawd.py` (325 KB god object) into domain sub-modules.
- **Batch PR-3**: Decompose `core/api_routes.py` into `core/routes/` sub-router pattern.
- **Batch PR-4**: Remove tombstone shims after import migration is complete.
- **Batch PR-5**: Retire `dashboard/backend/main.py` and `core/legacy_adapters/`.
