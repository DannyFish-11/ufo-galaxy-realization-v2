# Legacy Purge and Baseline Hardening

> **PR-10 — Final Legacy Purge and Baseline Hardening**
>
> This document is the authoritative reference for all purge and isolation
> decisions made as part of the 10-PR cleanup/hardening sequence.
>
> Authoritative Python registry: `core/legacy_purge_registry.py`

---

## 1. Purpose

PR-10 is the final cleanup/hardening pass after the architecture cleanup
(PR-1 through PR-9).  Its goal is to:

1. **Eliminate residual dead code paths** that still pointed at hard-disabled
   assets, creating a false impression that retired features were accessible.
2. **Harden legacy wrapper scripts** so they cannot easily be extended with
   new startup logic.
3. **Document the purge decisions** in one machine-readable, human-readable
   place so the cleaned-up architecture is durable.

---

## 2. Purge Decisions (PR-10)

### 2.1 Removed: `start_galaxy.py::_start_desktop()`

| Attribute | Value |
|---|---|
| Status | **DEAD_REFERENCE_REMOVED** |
| Asset | `start_galaxy.py` — function `_start_desktop()` |
| PR | PR-10 |

**Problem**: `_start_desktop()` called
`os.system("python .../enhancements/clients/windows_client/run_ui.py")`, which
has been hard-disabled since PR-3.  The `--desktop` and `--all` flags on
`start_galaxy.py` forwarded to this function, giving the appearance that a
live Windows desktop UI could be launched via this wrapper when in fact it
would immediately raise a `RuntimeError`.

**Resolution**: `_start_desktop()` and the `multiprocessing.Process` launch
block have been removed.  The `--desktop` / `--all` flags are retained as
accepted-but-deprecated stubs that emit a clear `DeprecationWarning` so
existing shell scripts do not break with an unexpected argument error.

**Active Windows direction**:
```
windows_client/status_board_v2/   ← canonical read-only status board
                                     (projection-driven; PROJECTION_DRIVEN role)
windows_client/autonomy/           ← active Windows automation layer
core/desktop_presence_runtime.py   ← DesktopPresenceRuntime tri-state shell
```

### 2.2 Fully removed: `start_galaxy.py`

| Attribute | Value |
|---|---|
| Status | **PERMANENTLY_ISOLATED** (file deleted) |
| Asset | `start_galaxy.py` |
| PR | PR-10 (hardened), post-PR-10 cleanup (removed) |

**History**:
- PR-10: Removed `_start_desktop()` dead path; added LEGACY WRAPPER guard; hardened wrapper.
- Post-PR-10 cleanup: File deleted entirely. There is no remaining use case for the wrapper.

**Migration**: Use `python main.py` or `python unified_launcher.py` directly.

**Invariant**: `start_galaxy.py` must not exist in the active repository tree.

### 2.3 Fully removed: `start_l4.py`

| Attribute | Value |
|---|---|
| Status | **PERMANENTLY_ISOLATED** (file deleted) |
| Asset | `start_l4.py` |
| PR | PR-10 (confirmed/frozen), post-PR-10 cleanup (removed) |

`start_l4.py` was frozen in PR-6 (delegating to `unified_launcher.py`) and
confirmed in PR-10.  The post-PR-10 cleanup deletes it entirely.  L4 lifecycle
is now managed exclusively through `unified_launcher.py`.

**Migration**: Use `python main.py` or `python unified_launcher.py` directly.

**Invariant**: `start_l4.py` must not exist in the active repository tree.

---

## 3. Previously Established Purge Decisions (PR-1 through PR-9)

The following decisions were made in earlier PRs and are carried forward
unchanged.  They are catalogued here for completeness; the machine-readable
records live in `core/legacy_purge_registry.py`.

### 3.1 Hard-disabled Windows client modules (PR-3)

All modules below raise `RuntimeError` on import and emit
`DeprecationWarning`:

| Asset | Canonical replacement |
|---|---|
| `windows_client/client.py` | `windows_client/windows_aip_client.py` |
| `windows_client/ui_sidebar.py` | `windows_client/status_board_v2/` |
| `windows_client/desktop_automation.py` | `windows_client/autonomy/` |
| `windows_client/windows_mcp_server.py` | `galaxy_gateway/` |
| `windows_client/main.py` | `core/desktop_presence_runtime.py` |
| `windows_client/windows_client_integrated.py` | `windows_client/status_board_v2/` |
| `windows_client/key_listener.py` | *(retired; no replacement)* |
| `enhancements/clients/windows_client/run_ui.py` | `python unified_launcher.py` |

Legacy launchers and UI assets have been moved to `windows_client/_legacy/`.

### 3.2 dashboard/ demoted (PR-4)

`dashboard/` is classified as `LEGACY_SURFACE` and carries both
`dashboard/LEGACY_SURFACE.md` and `dashboard/frontend/LEGACY_SURFACE.md`.
The canonical management API is `core/api_routes.py`.

---

## 4. Active Runtime Baseline (Post-PR-10)

After this purge the active runtime baseline is:

```
Canonical startup
─────────────────
python main.py              ← OS-level entry (delegates immediately)
python unified_launcher.py  ← top-level system orchestrator
start.bat                   ← Windows canonical startup (calls main.py)
start.sh                    ← Linux/macOS convenience (calls main.py)
launcher/                   ← authoritative startup modules (PR-5)

L4 runtime classes (canonical location)
────────────────────────────────────────
core/galaxy_main_loop_l4_enhanced.py  ← GalaxyMainLoopL4 base + GalaxyMainLoopL4Enhanced

Authority chain
───────────────
DesktopPresenceRuntime      (core/desktop_presence_runtime.py)
    → OpenClawd             (core/openclawd.py)
    → AgentKernel           (core/agent/kernel.py)
    → CommandRouter         (core/command_router.py)

Active desktop status surface
──────────────────────────────
windows_client/status_board_v2/  ← PROJECTION_DRIVEN (only canonical UI)
windows_client/autonomy/         ← ACTIVE_DESKTOP_SHELL

Fully removed (post-PR-10 cleanup)
────────────────────────────────────────────────
start_galaxy.py     ← deleted; use main.py or unified_launcher.py
start_l4.py         ← deleted; use main.py or unified_launcher.py

Hard-disabled (raise RuntimeError on import)
────────────────────────────────────────────
windows_client/client.py
windows_client/ui_sidebar.py
windows_client/desktop_automation.py
windows_client/windows_mcp_server.py
windows_client/main.py
windows_client/windows_client_integrated.py
windows_client/key_listener.py
enhancements/clients/windows_client/run_ui.py
```

---

## 5. Validation

The purge registry is programmatically accessible:

```python
from core.legacy_purge_registry import (
    PURGE_REGISTRY,
    PurgeStatus,
    get_entries_by_status,
    get_entries_by_pr,
    purge_registry_summary,
)

print(purge_registry_summary())

dead_refs = get_entries_by_status(PurgeStatus.DEAD_REFERENCE_REMOVED)
for entry in dead_refs:
    print(f"[{entry.pr}] {entry.asset_path}: {entry.rationale[:60]}")
```

The validation script also covers PR-10 purge checks:

```bash
python scripts/validate_runtime.py
```

Specific PR-10 regression tests:

```bash
python -m pytest tests/test_pr10_legacy_purge_hardening.py -v
```

---

*This document was produced by PR-10 (Final Legacy Purge and Baseline
Hardening), the closing step of the 10-PR cleanup/hardening sequence.*
