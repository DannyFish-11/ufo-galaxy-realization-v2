# DECISION_EXECUTION_POLICY.md

## Decision Execution Policy — Windows Execution Layer

The **Decision Execution Layer** (`core/execution/decision_executor.py`)
bridges the [Decision Gate](DECISION_GATE_SPEC.md) output to real OS-level
actions on Windows.  It is consumed by
`OpenClawd._run_execution()` immediately after `_run_continuum()` in
`OpenClawd.process()`.

---

## 1. Action Level Mapping

| `action_level`  | Behaviour                                                                      |
|-----------------|--------------------------------------------------------------------------------|
| `observe`       | **No-op.** The system only monitors; no OS call is made.                       |
| `hint`          | **No-op.** Reserved for future lightweight notification stub.                  |
| `assist`        | **Soft action.** Attempt to focus the configured `execution_assist_app` window; launch it if not already running. Falls through to no-op if no target is configured or the target is not in the allowlist. |
| `execute`       | **Explicit app launch.** Launch the target specified in `state_continuum.metadata.execution_target` (or `execution_assist_app` as fallback). Blocked unless the target passes the allowlist check. |

---

## 2. Configuration Keys (`config.json`)

| Key                       | Type          | Default   | Description                                                                                  |
|---------------------------|---------------|-----------|----------------------------------------------------------------------------------------------|
| `enable_system_actions`   | `bool`        | `false`   | **Master switch.** Must be explicitly set to `true` to enable any OS-level action dispatch.  |
| `execution_app_allowlist` | `list[str]`   | `[]`      | Allowed targets (executable paths, names, or URI schemes). Case-insensitive prefix match. An empty list blocks all launches even when the master switch is on. |
| `execution_assist_app`    | `str \| null` | `null`    | Default app to focus/open when `action_level=assist`. Also used as fallback target for `execute` when the continuum state carries no explicit `execution_target`. |

### Example

```json
{
  "enable_system_actions": true,
  "execution_app_allowlist": [
    "notepad.exe",
    "calc.exe",
    "https://",
    "C:\\Users\\User\\Apps\\MyApp.exe"
  ],
  "execution_assist_app": "notepad.exe"
}
```

---

## 3. Policy Gate

The `PolicyGate` class enforces the allowlist check before any OS call:

1. If `enable_system_actions` is `false` → block.
2. If `execution_app_allowlist` is empty → block.
3. If the resolved target does not match any entry in the allowlist
   (case-insensitive prefix match) → block and log at DEBUG level.

All blocked actions return an `ExecutionResult` with `action_taken="noop"` and
a descriptive `skipped_reason` string.

---

## 4. Safety Constraints

- **Disabled by default.** `enable_system_actions` defaults to `false`.
  No OS call is ever made unless explicitly opted in.
- **Allowlist required.** An empty `execution_app_allowlist` blocks all
  launches regardless of the master switch.
- **Exception isolation.** All exceptions inside `DecisionExecutor.execute()`
  are caught and logged at DEBUG level.  The response flow is never
  interrupted by execution errors.
- **Non-Windows hosts.** On non-Windows platforms `get_system_api()` returns
  a `NoOpSystemAPI` that silently ignores all calls.
- **No UI semantics.** The executor operates at the OS process level only;
  it has no knowledge of UI layout, rendering, or visual state.
- **Backward compatible.** All new config keys have safe defaults matching
  the prior behaviour (no execution).

---

## 5. Integration Point

```
OpenClawd.process()
  │
  ├── _run_continuum()           ← produces state_continuum dict
  │                                (action_level inside decision sub-object)
  │
  └── _run_execution(state_continuum)
        │
        └── DecisionExecutor.execute(state_continuum)
              │
              ├── action_level=observe/hint  → noop
              ├── enable_system_actions=false → noop
              ├── action_level=assist        → focus_window / launch_app (allowlist checked)
              └── action_level=execute       → launch_app (allowlist checked)
```

---

## 6. Extending the Executor

To add new action types, subclass `DecisionExecutor` and override
`_dispatch_assist` or `_dispatch_execute`, or add new dispatch branches in
`_execute_inner`.  All new dispatch branches must follow the same
exception-swallowing pattern and must check `PolicyGate.allows()` before
any OS call.
