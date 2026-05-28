> ## ⚠️ SUPERSEDED — NOT AUTHORITATIVE
>
> **This document has been superseded by [`ANDROID_PROTOCOL_MATURITY_MATRIX.md`](ANDROID_PROTOCOL_MATURITY_MATRIX.md).**
> The content below is preserved for historical reference only.
> For the current Android protocol maturity matrix, see [`ANDROID_PROTOCOL_MATURITY_MATRIX.md`](ANDROID_PROTOCOL_MATURITY_MATRIX.md).

---

# Re-Audit: Android Long-Tail Protocol Maturity V2

> **Fresh re-audit pass** — `DannyFish-11/ufo-galaxy-realization-v2` and
> `DannyFish-11/ufo-galaxy-android`.
>
> Supersedes `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md`.
> Companion: `docs/REAUDIT_FRESH_PASS_2.md`

---

## Purpose

This document classifies every Android AIP message type by:
- Current center-side (V2) handling
- Current Android-side handling
- Payload maturity
- Downstream consumers
- Recommended disposition with priority

---

## Classification legend

| Disposition | Meaning |
|-------------|---------|
| **CANONICAL** | Well-supported on both sides; no action needed |
| **PROMOTE** | Implement full runtime consumer path; wire into canonical execution chain |
| **PROMOTE + UNIFY** | Promote to AIP v3 JSON *and* unify duplicate center-side implementations |
| **RETIRE** | Remove after traffic analysis confirms no active clients |
| **DEFER** | Design / dependency not yet clear; keep as-is until prerequisite work |

| Priority | Meaning |
|----------|---------|
| **P0** | Correctness gap; silent failures; address before other protocol work |
| **P1** | High-impact; address in immediate sprint after P0 items |
| **P2** | Medium-impact; address in near-term sprints |
| **P3** | Low-impact or design-pending; can wait |

---

## Protocol context

- **Canonical protocol**: AIP v3.0 (`galaxy_gateway/protocol/aip_v3.py`)
- **Compat layer**: `galaxy_gateway/protocol/compat.py` — normalises AIP/1.0 and AIP/2.0 to v3 at ingress
- **Android entry**: `galaxy_gateway/android_bridge.py` + `galaxy_gateway/android/handlers/`
- **Legacy binary types**: `enhancements/multidevice/device_protocol.py` — `LegacyMessageType` (AIP v2 binary)
- **Cross-reference**: `galaxy_gateway/protocol/message_types.py` — full `MessageType` enum

---

## Section 1: Canonical types (no action needed)

These types are fully supported on both sides and are part of the canonical AIP v3.0
surface.

| AIP type | Direction | Center-side handler | Android-side handler | Status |
|----------|-----------|--------------------|--------------------|--------|
| `device_register` | C→S | `_handle_device_register` | `AgentMessageHandler` | ✅ CANONICAL |
| `heartbeat` | C→S | `_handle_heartbeat` | `AgentWebSocket` | ✅ CANONICAL |
| `task_submit` / `task_execute` | C↔S | `handle_task_execute` | `AgentMessageHandler._handle_task_execute` | ✅ CANONICAL |
| `task_result` | C→S | result handler | `AgentMessageHandler._handle_task_result` | ✅ CANONICAL |
| `task_assign` | S→C | `MessageBuilder` | Android receives | ✅ CANONICAL |
| `action_execute` | S→C | `_handle_forward_log` | `AgentMessageHandler._handle_forward_log` | ✅ CANONICAL |
| `gui_click` / `gui_swipe` / `gui_input` | S→C | AIPMessage sends | Android implements | ✅ CANONICAL |

**Note**: `action_execute` is routed through `_handle_forward_log` on the center
side. This is the canonical path for this type — the center forwards the action to
the device rather than executing it locally. This is correct behavior.

---

## Section 2: Long-tail types — priority classification

### P0 — Correctness gaps (address immediately)

---

#### `task_cancel` / `task_status`

| Field | Value |
|-------|-------|
| **AIP type** | `task_cancel`, `task_status` (`MessageType.TASK_CANCEL`, `TASK_STATUS`) |
| **Direction** | C→S (Android initiates cancel or queries status) |
| **Gap ID** | PROTO-002 |
| **Severity** | HIGH (elevated from prior MEDIUM) |
| **Current center-side behavior** | Received by `android_bridge.py`; routed to `_handle_forward_log`; logged but **not acted upon** |
| **Current Android behavior** | Android sends `task_cancel` when user requests cancellation; awaits confirmation |
| **Real downstream consumers** | None confirmed |
| **Correctness impact** | **Silent correctness failure**: Android user cancels a task; center side ignores the cancel; task continues executing. Android UI shows "cancelled" while the task runs. |
| **Disposition** | **PROMOTE — P0** |
| **Required action** | Implement `_handle_task_cancel` that: (1) looks up active task by task_id, (2) calls `CommandRouter.cancel_envelope()` or equivalent, (3) sends `task_cancel_ack` back to Android |
| **Required action** | Implement `_handle_task_status` that: (1) looks up task state in `TaskGraphRuntime`, (2) returns canonical status via `task_status_response` |

---

### P1 — High-impact protocol gaps

---

#### `session_migrate` / `session_restore`

| Field | Value |
|-------|-------|
| **AIP type** | `session_migrate`, `session_restore` |
| **Direction** | C→S / S→C (device initiates migration; center confirms restore) |
| **Gap ID** | PROTO-001 |
| **Severity** | HIGH |
| **Current center-side behavior** | AIP v2 binary format handled by `galaxy_gateway/session_roaming.py` AND `core/routes/sessions.py` — two separate implementations with divergent semantics |
| **Current Android behavior** | Still uses AIP v2 binary format; AIP v3 path not available |
| **Payload maturity** | AIP v3 JSON schema defined but not wired |
| **Real downstream consumers** | Both legacy implementations; no canonical consumer |
| **Correctness impact** | Split-brain risk: which migration handler wins depends on connection path. Session may be migrated differently by each handler. |
| **Disposition** | **PROMOTE + UNIFY — P1** |
| **Required action** | (1) Define single canonical migration handler in `android_bridge.py` with AIP v3 JSON; (2) delegate `session_roaming.py` OR `core/routes/sessions.py` to this handler; (3) retire or redirect the non-canonical path; (4) update Android to use AIP v3 JSON |

---

#### `wake_event` / `wake_route_result`

| Field | Value |
|-------|-------|
| **AIP type** | `wake_event` (0x70), `wake_route_result` (0x71) |
| **Direction** | C→S (Android wake event triggers routing) |
| **Gap ID** | PROTO-003 |
| **Severity** | MEDIUM |
| **Current center-side behavior** | Binary (hex byte) message types; handled via legacy binary compat layer |
| **Current Android behavior** | Sends binary wake event; no AIP v3 path available |
| **Payload maturity** | AIP v3 `wake_event` and `wake_route_result` types defined in `MessageType` enum; typed payload schema not yet confirmed |
| **Real downstream consumers** | `process_wake_event()` in `core/e2e_orchestrator.py` (confirmed consumer) |
| **Disposition** | **PROMOTE — P1** |
| **Required action** | (1) Define typed AIP v3 JSON payload for `wake_event` with `device_id`, `wake_trigger`, `context` fields; (2) wire Android wake path to use AIP v3; (3) confirm `process_wake_event()` reads from AIP v3 payload |

---

### P2 — Medium-impact protocol gaps

---

#### `ui_tree_request` / `action_sequence_execute` / `app_start`

| Field | Value |
|-------|-------|
| **AIP types** | `ui_tree_request`, `action_sequence_execute`, `app_start` |
| **Direction** | S→C (center sends to Android for execution) |
| **Gap ID** | PROTO-004 |
| **Severity** | MEDIUM |
| **Current center-side behavior** | Sent via `_handle_forward_log`; Android receives and logs but no active execution path confirmed |
| **Current Android behavior** | Handler may exist but not confirmed active for `action_sequence_execute` compound actions |
| **Payload maturity** | Typed payload schemas defined; execution semantics not fully specified |
| **Real downstream consumers** | Unconfirmed — may be emitted by vision-driven task flows but no canonical caller identified |
| **Disposition** | **PROMOTE — P2** |
| **Required action** | (1) Confirm Android-side handlers for compound action sequences; (2) wire `action_sequence_execute` into `TaskGraphRuntime` as a typed task step; (3) implement result reporting back to center via `task_result` |

---

#### AIP v2 binary `ANDROID_SCREEN` (0x60) / `ANDROID_INPUT` (0x61)

| Field | Value |
|-------|-------|
| **AIP type** | `ANDROID_SCREEN` (LegacyMessageType 0x60), `ANDROID_INPUT` (LegacyMessageType 0x61) |
| **Direction** | C→S (screen data from device), S→C (input commands to device) |
| **Gap ID** | PROTO-005 |
| **Severity** | MEDIUM |
| **Current center-side behavior** | Handled via legacy binary compat layer in `galaxy_gateway/protocol/compat.py` |
| **Current Android behavior** | Legacy binary protocol; AIP v3 equivalents (`screen_stream_data`, `action_execute`) defined but not used on Android side |
| **AIP v3 equivalents** | `screen_stream_data`, `action_execute` |
| **Real downstream consumers** | `Node_95_WebRTC_Receiver` consumes screen data; WebRTC path for streaming |
| **Disposition** | **PROMOTE — P2** |
| **Required action** | (1) Update Android to emit `screen_stream_data` / `action_execute` in AIP v3 JSON; (2) set explicit sunset date for binary types (recommend: after 2 sprint cycles); (3) remove legacy binary handlers after confirmed migration |

---

### P3 — Defer / future design

---

#### `HYBRID_EXECUTE` / `HYBRID_RESULT`

| Field | Value |
|-------|-------|
| **AIP type** | `hybrid_execute`, `hybrid_result` (`MessageType.HYBRID_EXECUTE`, `HYBRID_RESULT`) |
| **Direction** | C↔S |
| **Gap ID** | PROTO-006 |
| **Severity** | LOW |
| **Current center-side behavior** | Type defined in `MessageType` enum; no active handler |
| **Current Android behavior** | Uses degrade path (`HYBRID_DEGRADE`) when true hybrid execution unavailable |
| **Design status** | "Hybrid execution" (coordinated center+device execution within a single task) is not yet designed |
| **Disposition** | **DEFER — P3** |
| **Required action** | No immediate action. When hybrid execution architecture is designed, promote to PROMOTE with full handler implementation. |

---

#### `PEER_ANNOUNCE` / `mesh_topology` / `peer_exchange`

| Field | Value |
|-------|-------|
| **AIP types** | `peer_announce`, `mesh_topology`, `peer_exchange` (Phase 5 P2P Mesh) |
| **Direction** | C→S or device-to-device |
| **Severity** | LOW |
| **Current center-side behavior** | Types defined in `MessageType` enum; no dedicated broker/routing handler |
| **Current Android behavior** | Not confirmed; no evidence of P2P mesh participation on Android |
| **Design status** | P2P mesh topology is a future capability; no design or wiring exists |
| **Disposition** | **DEFER — P3** |
| **Required action** | No immediate action. Requires dedicated P2P mesh topology design before promotion. |

---

### Retire

---

#### `/ws/ufo3/{device_id}` legacy WebSocket path

| Field | Value |
|-------|-------|
| **Surface** | WebSocket endpoint `/ws/ufo3/{device_id}` |
| **Gap ID** | PROTO-007 |
| **Severity** | LOW |
| **Current status** | Legacy endpoint still served; no confirmed active client |
| **Risk** | Unmaintained path; future security/protocol changes may not be applied |
| **Disposition** | **RETIRE — P3** |
| **Required action** | (1) Add request logging to `/ws/ufo3/` path to confirm zero active traffic; (2) set 30-day traffic observation window; (3) retire endpoint and return 410 Gone if no traffic observed |

---

## Protocol disposition summary

| Disposition | Priority | Count | Types |
|-------------|----------|-------|-------|
| CANONICAL | — | 7 | Core execution types |
| PROMOTE | P0 | 1 | `task_cancel` / `task_status` |
| PROMOTE + UNIFY | P1 | 1 | `session_migrate` / `session_restore` |
| PROMOTE | P1 | 1 | `wake_event` / `wake_route_result` |
| PROMOTE | P2 | 2 | `ui_tree_request`/`action_sequence_execute`/`app_start`, AIP v2 binary screen/input |
| DEFER | P3 | 2 | `hybrid_execute`/`hybrid_result`, `peer_announce`/`mesh_topology`/`peer_exchange` |
| RETIRE | P3 | 1 | `/ws/ufo3/` legacy path |

---

## Protocol maturity heat map

```
                          CENTER-SIDE
                ┌──────────────────────────────────┐
                │  Handled    │  Ignored   │ Absent │
     ──────────┼─────────────┼────────────┼────────┤
  A  CANONICAL  │ ██████████  │            │        │
  N  ──────────┼─────────────┼────────────┼────────┤
  D  PROMOTE    │             │ ████ P0/P1 │        │
  R  ──────────┼─────────────┼────────────┼────────┤
  O  PROMOTE    │ ░░░░ compat │ ████ P2    │        │
  I  ──────────┼─────────────┼────────────┼────────┤
  D  DEFER      │             │            │ ████   │
     ──────────┼─────────────┼────────────┼────────┤
     RETIRE     │             │ ░░░░ stale │        │
                └──────────────────────────────────┘

  ██ = Active gap / action needed
  ░░ = Legacy / transitional
```
