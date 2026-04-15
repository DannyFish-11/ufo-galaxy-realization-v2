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

### Android runtime host relationship clarification

- Android **device** identity remains the registration/transport anchor.
- Android **runtime host participant** is the execution actor attached on top of that device identity.
- Android **runtime attachment session** continuity (attach/reconnect) is distinct from conversation/history continuity.
- Android **delegation transfer session** events describe ownership transfer/handoff semantics and are not conversation sessions.
- Android **capability reporting** remains evidence for scheduling/readiness, not participant identity replacement.

## 4) Non-overclaim note

These alignment rules freeze semantics for convergence work. They do not claim all Android and center modules are already fully renamed or fully unified at protocol level.

## 5) PR-4B center-side runtime WS profile treatment (incremental)

Android AIP/WS ingress is now explicitly treated as a **UGCP Runtime WS Profile** on the gateway side:

| Android ingress family | Center ingress handling | Canonical mapping posture |
|---|---|---|
| `device_register` | `android_bridge` registration handler + UDM registration write | Canonical |
| `heartbeat` / `device_status` / `agent_status` | Heartbeat/status handlers patch runtime/session evidence into UDM/UCM and router session cache | Canonical (readiness/posture evidence) |
| `capability_report` | Capability handler syncs gateway capability registry + CapabilityRegistry | Canonical |
| `delegated_execution_signal` | Dedicated canonical ingress via `core.android_delegated_signal_ingress` | Canonical |
| `file_transfer` | Explicitly recognized runtime transfer-family ingress, currently bounded through gateway generic-forward ACK path | Compat-forwarded (bounded) |
| `peer_announce` / `peer_exchange` / `mesh_topology` | Explicitly recognized runtime mesh-family ingress, currently bounded through gateway generic-forward ACK path | Compat-forwarded (bounded) |

Center-side expectations for this profile:

- **Session continuity/reconnect:** reconnect + heartbeat are expected continuity signals; center-side truth remains authoritative.
- **Readiness/capability/posture:** Android reports are evidence inputs, not parallel truth authority.
- **Transfer/delegation:** delegated execution signals are canonicalized first; transfer-family compat signals are explicitly bounded and reviewable.
- **Mesh participation:** mesh-family ingress is explicitly accepted and labeled as transport-coordination input, pending deeper canonical mesh-routing convergence.
