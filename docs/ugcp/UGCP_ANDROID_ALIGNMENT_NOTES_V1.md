# UGCP Android ↔ Center Vocabulary Alignment Notes v1

This note defines how Android-side concepts should align with center-side UGCP semantics.

## 1) Identity/session alignment

| Android-side term (expected/observed) | UGCP canonical term | Alignment rule |
|---|---|---|
| `task_id` | `task_id` | Preserve as-is end-to-end. |
| `trace_id` | `trace_id` | Preserve as-is end-to-end. |
| `session_id` | `control_session_id` | Treat Android `session_id` as control continuity session. |
| `runtime_session_id` | `runtime_session_id` | Treat as runtime identity; center registry is authority for active/non-active resolution. |
| `attached_session_id` (Android naming family) | `runtime_session_id` | Normalize to canonical runtime-session identity semantics. |
| `mesh_session_id` | `mesh_session_id` | Preserve when mesh/staged coordination is active. |

## 2) Control/lifecycle alignment

| Android concept | UGCP canonical term | Alignment rule |
|---|---|---|
| delegated execution signal `signal_kind` | `delegated_signal_kind` | Normalize to canonical kinds (`ack/progress/result/timeout/cancelled`). |
| Android route tags (local/cross-device/delegated/fallback) | `dispatch_mode` / `effective_mode` | Interpret as intended mode + effective mode after fallback. |
| Android completion/failure/cancel outcomes | `terminal_state` / `terminal_reason` | Normalize final states/reasons into canonical terminal vocabulary. |
| Android readiness checks (model/accessibility/overlay) | `readiness_verdict` | Feed readiness as one readiness evidence source, not as independent authority override. |

## 3) Authority direction (cross-repo)

- Android provides signals and capability/readiness evidence.
- Center-side control plane resolves authoritative session state, dispatch outcome, and projection truth.
- Compat aliases are accepted during convergence, but canonical UGCP names are the stable target vocabulary for both repos.

## 4) Non-overclaim note

These alignment rules freeze semantics for convergence work. They do not claim all Android and center modules are already fully renamed or fully unified at protocol level.
