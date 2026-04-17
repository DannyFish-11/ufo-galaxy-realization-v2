# Android Protocol Maturity Matrix

> **Dual-repo audit document** — produced as part of the complete unresolved audit PR.
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2`.
> Cross-repo reference: `DannyFish-11/ufo-galaxy-android`.

---

## Purpose

This document audits Android-side minimal-compat / placeholder / long-tail
message types and classifies each one's current runtime behavior, payload
maturity, downstream consumers, and recommended disposition.

---

## Classification legend

| Disposition | Meaning |
|-------------|---------|
| **PROMOTE** | Promote to full runtime consumer path in Android; wire into canonical task lifecycle |
| **RETIRE** | Remove from protocol surface after verifying no callers remain |
| **DEFER** | Keep as-is; design / dependency not yet clear; revisit after other work |
| **REPLACE** | Replace with a canonical alternative that already exists |

---

## Protocol context

- **Canonical protocol**: AIP v3.0 (`galaxy_gateway/protocol/aip_v3.py`)
- **Compat layer**: `galaxy_gateway/protocol/compat.py` — normalises AIP/1.0 and AIP/2.0 messages to v3 at ingress
- **Android entry**: `galaxy_gateway/android_bridge.py` + `galaxy_gateway/android/handlers/`
- **Legacy binary types**: `enhancements/multidevice/device_protocol.py` — `LegacyMessageType` (AIP v2 binary)

---

## Section 1: Core task / execution types (well-supported)

These types have full server-side and Android-side handler implementations and
are part of the canonical AIP v3.0 surface. They are listed here for completeness.

| Type | Direction | Server handler | Android handler | Status |
|------|-----------|----------------|-----------------|--------|
| `device_register` | C→S | `_handle_device_register` | `AgentMessageHandler` | ✅ Canonical |
| `heartbeat` | C→S | `_handle_heartbeat` | `AgentWebSocket` | ✅ Canonical |
| `task_submit` / `task_execute` | C↔S | `handle_task_execute` | `AgentMessageHandler._handle_task_execute` | ✅ Canonical |
| `task_result` | C→S | result handler | `AgentMessageHandler._handle_task_result` | ✅ Canonical |
| `task_assign` | S→C | MessageBuilder | Android receives | ✅ Canonical |
| `action_execute` | S→C | `_handle_forward_log` | `AgentMessageHandler._handle_forward_log` | ✅ Canonical |
| `gui_click` / `gui_swipe` / `gui_input` | S→C | AIPMessage sends | Android implements | ✅ Canonical |

---

## Section 2: Long-tail / transitional / placeholder types

### `HYBRID_EXECUTE`

| Field | Value |
|-------|-------|
| **AIP type** | `hybrid_execute` (Phase 3, `MessageType.HYBRID_EXECUTE`) |
| **Direction** | S→C |
| **Current server behavior** | Available in AIP v3 `MessageType` enum; `exec_mode` field in `DeviceRouter.route_task()` distinguishes `hybrid` mode |
| **Current Android behavior** | Handled via `HYBRID_DEGRADE` fallback path — minimal-compat degrade, not full hybrid execution |
| **Typed payload maturity** | `HYBRID_EXECUTE` payload structure exists in protocol; Android-side typed payload deserialization unverified |
| **Real downstream consumers** | `DeviceRouter` routes tasks with `exec_mode="hybrid"` but Android degrade path means true hybrid execution is not active |
| **Disposition** | **DEFER → PROMOTE** when Android multi-device co-execution is ready |
| **Center-side coordination required?** | Yes — hybrid execution requires center-side task decomposition (`CommandRouter` + `formation_resolver`) before Android can co-execute |

---

### `RAG_QUERY`

| Field | Value |
|-------|-------|
| **AIP type** | `rag_query` (Phase 4, `MessageType.RAG_QUERY`) |
| **Direction** | C→S (Android initiates RAG query) or S→C (center dispatches RAG task to Android) |
| **Current server behavior** | Type defined in enum; no dedicated handler found in `galaxy_gateway/android/handlers/` |
| **Current Android behavior** | Not confirmed — no evidence of Android-side RAG query consumer in accessible code paths |
| **Typed payload maturity** | Payload structure referenced but no schema enforcement found |
| **Real downstream consumers** | `knowledge_db/` and RAG nodes (Node_30, etc.) handle center-side RAG; Android path not wired |
| **Disposition** | **DEFER** — Android-side RAG execution is not a current priority; defer until mobile VLM/RAG capability is designed |
| **Center-side coordination required?** | Yes — RAG execution requires knowledge backend routing |

---

### `CODE_EXECUTE`

| Field | Value |
|-------|-------|
| **AIP type** | `code_execute` (Phase 4, `MessageType.CODE_EXECUTE`) |
| **Direction** | S→C |
| **Current server behavior** | Type defined; no dedicated Android bridge handler found for code execution routing to Android |
| **Current Android behavior** | No evidence of a sandboxed code execution runtime on Android |
| **Typed payload maturity** | Low — no payload schema enforced |
| **Real downstream consumers** | Center-side code execution nodes (Node_50, etc.) handle this locally; Android path is placeholder |
| **Disposition** | **DEFER** — Android sandboxed code execution is a future capability; not a current requirement |
| **Center-side coordination required?** | Not blocked on center-side; Android sandbox design needed first |

---

### `SESSION_MIGRATE`

| Field | Value |
|-------|-------|
| **AIP type** | `SESSION_MIGRATE = 0x72` in `LegacyMessageType` (AIP v2 binary) |
| **Direction** | S→C or C→S |
| **Current server behavior** | `SessionRoamingManager.migrate_session()` sends `session_restore` via WebSocket; `core/routes/sessions.py` sends `session_migrated` + `session_sync` — two parallel implementations |
| **Current Android behavior** | Android receives `session_restore` message; handling unverified as fully wired into canonical task lifecycle |
| **Typed payload maturity** | AIP v2 binary — not modernised to AIP v3 JSON |
| **Real downstream consumers** | `SessionRoamingManager._push_context_to_device()` sends `session_restore`; Android `AgentMessageHandler` expected to handle it |
| **Disposition** | **PROMOTE + REPLACE** — migrate `SESSION_MIGRATE` / `session_restore` to an AIP v3 JSON message type with explicit payload schema; unify the two center-side implementations into one canonical path |
| **Center-side coordination required?** | Yes — dual center-side implementations must be unified before promotion |

---

### `RELAY`

| Field | Value |
|-------|-------|
| **AIP type** | Not a named `MessageType` enum value; relay semantics expressed via `route_mode` / task routing |
| **Direction** | S→C (center relays a task to another device via this device) |
| **Current behavior** | `formation_resolver` assigns `FormationRole.RELAY` to relay devices; relay execution on Android is not a confirmed runtime capability |
| **Typed payload maturity** | No explicit `relay` message type in AIP v3 |
| **Real downstream consumers** | None confirmed on Android side |
| **Disposition** | **DEFER** — relay role is declared in formation; Android-side relay execution engine does not exist yet |
| **Center-side coordination required?** | Yes — relay topology requires center-side formation orchestration |

---

### `FORWARD`

| Field | Value |
|-------|-------|
| **AIP type** | No canonical `forward` type in `MessageType` enum |
| **Direction** | S→C or inter-device |
| **Current behavior** | `_handle_forward_log` is used as a catch-all handler in `AndroidBridge` for many message types — it logs and forwards, it does not execute |
| **Typed payload maturity** | Low — `forward_log` is a passthrough, not a typed execution path |
| **Real downstream consumers** | Log sinks; no confirmed execution consumer |
| **Disposition** | **RETIRE** the catch-all `_handle_forward_log` pattern for types that should have dedicated handlers; retain only for types explicitly designed as advisory/log |
| **Center-side coordination required?** | No |

---

### `REPLY`

| Field | Value |
|-------|-------|
| **AIP type** | Not a distinct `MessageType` — responses use `task_result` or `command_result` |
| **Current behavior** | No standalone `reply` type; `task_result` is the canonical response |
| **Disposition** | **N/A** — subsumed by `task_result`; no separate action needed |

---

### `BROADCAST`

| Field | Value |
|-------|-------|
| **AIP type** | Not a named `MessageType`; broadcast semantics expressed via `CommandRouter._route_parallel_fanout_envelope()` |
| **Direction** | S→C (center broadcasts to multiple devices) |
| **Current behavior** | Parallel fanout is handled canonically via `CommandRouter` (PR-532); Android receives individual `task_assign` messages |
| **Typed payload maturity** | Handled as per-device `task_assign` at delivery; no explicit broadcast message type on wire |
| **Real downstream consumers** | Per-device `task_assign` handlers on Android |
| **Disposition** | **N/A** — broadcast is implemented as fan-out at the routing layer; no Android-side broadcast message type needed |

---

### `WAKE_EVENT`

| Field | Value |
|-------|-------|
| **AIP type** | `WAKE_EVENT = 0x70` in `LegacyMessageType` (AIP v2 binary) |
| **Direction** | C→S (Android device wake trigger) |
| **Current server behavior** | `test_wake_system.py` exists with tests for wake event handling; `SessionRoamingManager` has `auto_migrate_on_attention_shift()` hook |
| **Current Android behavior** | Android sends wake event when device attention is triggered |
| **Typed payload maturity** | AIP v2 binary format — not modernised; `WAKE_ROUTE_RESULT = 0x71` is the companion |
| **Real downstream consumers** | Session roaming manager, wake routing system |
| **Disposition** | **PROMOTE** — migrate `WAKE_EVENT` / `WAKE_ROUTE_RESULT` to AIP v3 JSON with typed payload; wire into canonical device presence / session routing |
| **Center-side coordination required?** | Yes — wake routing connects to session selection and device attention models |

---

### `PEER_ANNOUNCE`

| Field | Value |
|-------|-------|
| **AIP type** | `peer_announce` (Phase 5 P2P Mesh, `MessageType.PEER_ANNOUNCE`) |
| **Direction** | C→S or device-to-device |
| **Current server behavior** | Type defined in `MessageType` enum; no dedicated broker/routing handler found in accessible code paths |
| **Current Android behavior** | Not confirmed — no evidence of P2P mesh participation on Android |
| **Typed payload maturity** | Companion `peer_exchange` and `mesh_topology` types defined; no payload schema found |
| **Real downstream consumers** | None confirmed |
| **Disposition** | **DEFER** — P2P mesh topology is a future capability; not yet designed or wired |
| **Center-side coordination required?** | Yes — mesh topology requires a dedicated center-side mesh broker/coordinator |

---

### `LOCK` / `UNLOCK`

| Field | Value |
|-------|-------|
| **AIP type** | Not found in `MessageType` enum |
| **Direction** | S→C (center locks/unlocks device for exclusive use) |
| **Current behavior** | No `lock`/`unlock` message type found in AIP v3 enum or Android bridge handlers |
| **Typed payload maturity** | Not defined |
| **Real downstream consumers** | None found |
| **Disposition** | **DEFER** — device locking semantics should be designed explicitly if needed; likely replaced by formation role (`PRIMARY_EXECUTION` exclusive allocation) |
| **Center-side coordination required?** | Yes — exclusive device allocation requires formation / capability assimilation changes |

---

### `DELEGATED_EXECUTION_SIGNAL`

| Field | Value |
|-------|-------|
| **AIP type** | `delegated_execution_signal` (PR-16, `MessageType.DELEGATED_EXECUTION_SIGNAL`) |
| **Direction** | C→S (Android reports progress/result of delegated execution) |
| **Current server behavior** | Full ingress pipeline: `ingest_delegated_execution_signal()` → PR-18 guard → reconciler → tracking runtime → PR-22 registry gate |
| **Current Android behavior** | Android sends `delegated_execution_signal` after completing delegated tasks |
| **Typed payload maturity** | High — `DelegatedExecutionSignalEnvelope`, reconciler, tracking runtime all well-defined |
| **Real downstream consumers** | `DelegatedExecutionTrackingRuntime`, `AndroidSignalReconcileOutcome` |
| **Disposition** | ✅ **Already canonical** — no action needed |
| **Center-side coordination required?** | N/A — fully wired |

---

## Section 3: Deprecated REST register / heartbeat paths

| Endpoint | Status | Action |
|----------|--------|--------|
| `POST /api/devices/register` | Compat alias → `/api/v1/devices/register` | **RETIRE when no Android clients use it** — confirmed compat shim; monitor traffic |
| `GET /api/devices/list` | Compat alias → `GET /api/v1/devices` | Same |
| `POST /api/devices/heartbeat` | Compat alias | Same |
| `/ws/device/{device_id}` | Compat WS path | **RETAIN** as compat alias; `/ws/android/{device_id}` is preferred |
| `/ws/ufo3/{device_id}` | Legacy UFO3 path | **RETIRE after confirming no UFO3 clients** |
| `/ws/android` (broadcast) | Compat broadcast path | **RETIRE** — `device_id` should always be explicit |

---

## Section 4: AIP v2 binary protocol residuals

| `LegacyMessageType` | Hex | Status | Action |
|--------------------|-----|--------|--------|
| `RECOVERY_REQUEST` | 0x51 | Binary only | **PROMOTE** to AIP v3 JSON or **REPLACE** with recovery session endpoint |
| `RECOVERY_RESPONSE` | 0x52 | Binary only | Same |
| `ANDROID_SCREEN` | 0x60 | Binary only | **PROMOTE** — screen data should use AIP v3 `screen_stream_data` |
| `ANDROID_INPUT` | 0x61 | Binary only | **PROMOTE** — map to `action_execute` / `gui_*` |
| `ANDROID_INSTALL` | 0x62 | Binary only | **DEFER** — app install semantics not fully designed |
| `WAKE_EVENT` | 0x70 | Binary only | **PROMOTE** (see above) |
| `WAKE_ROUTE_RESULT` | 0x71 | Binary only | **PROMOTE** (see above) |
| `SESSION_MIGRATE` | 0x72 | Binary only | **PROMOTE + REPLACE** (see above) |
| `SESSION_RESTORE` | 0x73 | Binary only | **PROMOTE + REPLACE** (see above) |

---

## Section 5: Message types with `_handle_forward_log` catch-all handling

The following message types are currently handled by the catch-all
`_handle_forward_log` in `AndroidBridge`. This means they are received,
logged, and not acted upon. They should be explicitly reviewed:

| Type | Current server-side handling | Recommended action |
|------|------------------------------|-------------------|
| `task_cancel` | `_handle_forward_log` | **PROMOTE** — dedicated cancellation handler; propagate to `CommandRouter` cancel path |
| `task_status` | `_handle_forward_log` | **PROMOTE** — query `TaskGraphRuntime` for status and respond with structured data |
| `agent_config_update` | `_handle_forward_log` | **DEFER** — config update path needs canonical design |
| `agent_restart` | `_handle_forward_log` | **DEFER** — agent restart semantics need explicit design |
| `ui_tree_request` | `_handle_forward_log` | **PROMOTE** — should invoke UI tree capture on Android |
| `action_sequence_execute` | `_handle_forward_log` | **PROMOTE** — should execute as batched action sequence |
| `app_start` | `_handle_forward_log` | **PROMOTE** — should invoke app launch |
| `system_command` | `_handle_forward_log` | **DEFER** — arbitrary system commands need sandbox design |

---

## Summary: Disposition matrix

| Type | Disposition | Priority |
|------|-------------|----------|
| `HYBRID_EXECUTE` | DEFER → PROMOTE | Medium |
| `RAG_QUERY` | DEFER | Low |
| `CODE_EXECUTE` | DEFER | Low |
| `SESSION_MIGRATE` / `session_restore` | PROMOTE + REPLACE | High |
| `RELAY` | DEFER | Low |
| `FORWARD` (catch-all) | RETIRE pattern | Medium |
| `WAKE_EVENT` / `WAKE_ROUTE_RESULT` | PROMOTE | Medium |
| `PEER_ANNOUNCE` | DEFER | Low |
| `LOCK` / `UNLOCK` | DEFER | Low |
| `DELEGATED_EXECUTION_SIGNAL` | ✅ Already canonical | — |
| Legacy REST register/heartbeat | RETIRE (gradual) | Low |
| `/ws/ufo3/` | RETIRE | Low |
| AIP v2 binary `RECOVERY_*` | PROMOTE | Medium |
| AIP v2 binary `ANDROID_SCREEN` | PROMOTE | Medium |
| AIP v2 binary `ANDROID_INPUT` | PROMOTE | Medium |
| `task_cancel` (forward_log) | PROMOTE | High |
| `task_status` (forward_log) | PROMOTE | High |
| `ui_tree_request` (forward_log) | PROMOTE | Medium |
| `action_sequence_execute` (forward_log) | PROMOTE | Medium |
| `app_start` (forward_log) | PROMOTE | Medium |

---

## Answer to acceptance criterion 4

**AC4 — Which Android long-tail message types should be promoted / retired / deferred?**

**High-priority PROMOTE:**
- `SESSION_MIGRATE` / `session_restore` → promote to AIP v3 JSON with unified center-side path
- `task_cancel` / `task_status` → promote from catch-all to dedicated handlers with canonical routing

**Medium-priority PROMOTE:**
- `WAKE_EVENT` / `WAKE_ROUTE_RESULT` → promote to AIP v3 JSON
- AIP v2 binary `ANDROID_SCREEN` / `ANDROID_INPUT` → migrate to `screen_stream_data` / `action_execute`
- `ui_tree_request` / `action_sequence_execute` / `app_start` → promote from catch-all

**DEFER:**
- `HYBRID_EXECUTE` (until Android co-execution designed)
- `RAG_QUERY`, `CODE_EXECUTE` (low mobile priority)
- `PEER_ANNOUNCE`, `LOCK/UNLOCK` (future capabilities)

**RETIRE:**
- `/ws/ufo3/` legacy path
- Legacy REST compat aliases (after client migration confirmed)
- `_handle_forward_log` catch-all pattern for types that should have real handlers
