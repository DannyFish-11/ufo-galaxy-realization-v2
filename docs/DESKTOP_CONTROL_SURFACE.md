# Desktop Control Surface Architecture

> **PR-8** — upgrade `windows_client/status_board_v2` to a canonical desktop
> control surface.

## Overview

As of PR-8, `windows_client/status_board_v2/` is no longer read-only.  It
provides a bounded, safe configuration entry path that routes all writes
through the canonical configuration authority (`ConfigService`) and surfaces
runtime-visible feedback back to the operator via a Config Control panel
rendered inside the board.

This is the final top-layer convergence step after ingress, authority,
transport, protocol, admissibility, and dispatch have been normalized.

## Architecture

```
Operator input (CLI args / future interactive)
        │
        ▼
ConfigControlSurface          (windows_client/status_board_v2/config_control.py)
  STATUS_BOARD_CONFIG_CONTROL_AUTHORITY sentinel
        │
        │ write path (only bounded operations)
        ▼
ConfigService                 (core/config_service.py)
  CONFIG_SERVICE_AUTHORITY sentinel
        │
        ├── set_toggle(provider, enabled)       → runtime/config.json
        └── set_native_mm_policy(mode)          → runtime/config.json
                │
                ▼
          ConfigStore         (core/config_store.py)
          ATOMIC WRITE to runtime/config.json
                │
                ▼ (best-effort after write)
        HotReloadConfigManager (core/config_hot_reload.py)
          load_from_file() → live propagation to runtime subscribers
                │
                ▼
         ControlApplyResult   (windows_client/status_board_v2/config_control.py)
           succeeded, last_applied_key, reload_triggered, reload_supported, reason, error
                │
                ▼
     StatusBoardV2App.render_once()
       └── Config Control panel (when result present)
```

## Design constraints

| Constraint | Enforcement |
|------------|-------------|
| **Canonical writes only** | All configuration writes are delegated to `ConfigService`. No ad-hoc local state is used as the source of truth. |
| **Bounded operations** | Only `TOGGLE_PROVIDER` and `SET_ROUTING_POLICY` are accepted. Unknown operations are rejected before any write. |
| **Safe failure** | Invalid values are rejected by `ConfigService` validation. Rejections return `succeeded=False` with an operator-meaningful `error` string. |
| **No secret leakage** | Secret values are never included in `ControlApplyResult` feedback strings or log output. |
| **Hot-reload** | After a successful write, `HotReloadConfigManager.load_from_file()` is invoked when available. If unavailable, the result reports this clearly. |
| **Explicit feedback** | Every apply action returns a `ControlApplyResult` with success/failure status, reload status, last applied key, and any error reason. |
| **Read behaviour preserved** | Projection/read surfaces are unaffected. `render_once()` continues to render all existing surfaces alongside the optional Config Control panel. |

## Allowed operations

### `TOGGLE_PROVIDER`

Enable or disable a provider by name.

```python
surface.apply_toggle("openai", True)    # enable openai
surface.apply_toggle("anthropic", False) # disable anthropic
```

CLI::

    python -m windows_client.status_board_v2 --apply-toggle openai=true

Delegates to: `ConfigService.set_toggle(provider, enabled)`  
Writes to: `runtime/config.json` → `providers.<name>.enabled`

### `SET_ROUTING_POLICY`

Set the native multimodal routing policy.

```python
surface.apply_routing_policy("strict")
surface.apply_routing_policy("prefer")
surface.apply_routing_policy("allow_fallback")
```

CLI::

    python -m windows_client.status_board_v2 --apply-routing-policy prefer

Delegates to: `ConfigService.set_native_mm_policy(mode)`  
Writes to: `runtime/config.json` → `routing.native_multimodal_policy`

## Feedback model

Every `apply_*` call returns a `ControlApplyResult`:

```python
@dataclass
class ControlApplyResult:
    succeeded: bool
    operation: str
    last_applied_key: str        # e.g. "providers.openai.enabled → True"
    reload_triggered: bool
    reload_supported: bool
    reason: str
    error: str
```

`render_lines()` converts this to operator-readable text.  `to_dict()` returns
a JSON-serialisable dict for programmatic consumers.

The board renders the most recent `ControlApplyResult` as a Config Control
panel at the bottom of the status board frame (only when a result exists).

## Hot-reload path

After a successful write, the surface calls
`core.config_hot_reload.get_existing_manager()` to retrieve the running
`HotReloadConfigManager` singleton.  If the manager is initialised,
`load_from_file(config_path)` is called to propagate the change to runtime
subscribers immediately.  The result of this call is reflected in
`ControlApplyResult.reload_triggered` and `reload_supported`.

If the manager is not available (e.g. cold-boot / test context), the result
clearly reports `reload_supported=False` and `reload_triggered=False` rather
than faking success.  The configuration change is still persisted and will
take effect on the next process startup.

## Non-goals

- This is **not** a freeform configuration editor.  Only the explicitly
  bounded operations listed above are accepted.
- This does **not** introduce a new dashboard or alternate operator UI.
- This does **not** create a parallel configuration persistence layer.
- This does **not** redesign the runtime config model.

## Key files

| File | Role |
|------|------|
| `windows_client/status_board_v2/config_control.py` | ConfigControlSurface, ControlOperation, ControlApplyResult |
| `windows_client/status_board_v2/app.py` | StatusBoardV2App with control_surface parameter; CLI --apply-toggle / --apply-routing-policy |
| `windows_client/status_board_v2/__init__.py` | Package exports for ConfigControlSurface and related symbols |
| `core/config_service.py` | Canonical configuration authority (ConfigService) |
| `core/config_store.py` | Canonical configuration persistence (ConfigStore) |
| `core/config_hot_reload.py` | HotReloadConfigManager + get_existing_manager() |
| `runtime/config.json` | Canonical configuration file written by ConfigStore |
| `tests/test_pr8_status_board_control_surface.py` | PR-8 acceptance criterion tests (40 tests) |
| `tests/test_pr15_status_board_config_control.py` | Comprehensive control surface tests (70 tests) |

## Acceptance criteria (PR-8)

- [x] `status_board_v2` can apply a bounded set of real runtime-relevant
      configuration changes (`TOGGLE_PROVIDER`, `SET_ROUTING_POLICY`).
- [x] All writes flow through the canonical configuration authority
      (`ConfigService → ConfigStore → runtime/config.json`).
- [x] Runtime-visible apply/reload/result feedback is surfaced in the board
      (Config Control panel in `render_once()`).
- [x] `status_board_v2` is materially closer to a true desktop control surface
      rather than a read-only projection board.
- [x] Projection/read behaviour is fully preserved.
