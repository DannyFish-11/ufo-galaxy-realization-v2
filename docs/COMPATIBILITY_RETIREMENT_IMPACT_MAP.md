# Compatibility / Transitional Surface Retirement Impact Map

> **Full re-audit pass** — fresh standalone review produced as part of the complete
> dual-repo architecture re-audit.
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2`.
> Cross-repo reference: `DannyFish-11/ufo-galaxy-android`.
>
> Companion documents: `DUAL_REPO_FULL_REAUDIT.md`, `DUAL_REPO_GAP_MATRIX.md`.

---

## Purpose

This document audits every remaining compatibility, transitional, legacy, and
adapter/facade surface across both repos. For each surface, it classifies:

| Classification | Meaning |
|---------------|---------|
| **Harmless residue** | Surface exists but is unreachable or has no callers; removal is safe and low-risk |
| **Still meaningful path** | Surface is used in at least one path; removal requires migration work |
| **High misuse risk** | Surface exists, has callers, and wrong use produces divergent behavior or silent failures |
| **Immediately retireable** | Surface can be retired now (or after brief traffic analysis) with no cross-repo coordination |
| **Retireable after coordination** | Surface requires explicit sync with `ufo-galaxy-android` before retirement |
| **Blocked on missing canonical replacement** | Cannot retire because the canonical replacement does not yet exist |

---

## Domain 1: V2 routing and scheduling legacy surfaces

### 1.1 `galaxy_gateway/task_router.py` — TaskRouter / TaskScheduler

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/task_router.py` |
| **Prior status** | RETIRED in PR-516 |
| **Classification** | **Harmless residue** (if file removed) / **High misuse risk** (if file still present with callers) |
| **Risk** | If the file still exists on disk, developers may import `TaskRouter` and route tasks through it, bypassing `CommandRouter` authority. |
| **Action** | Confirm file is removed from disk. `grep -r "TaskRouter\|TaskScheduler" --include="*.py"` to verify no remaining callers. |
| **Cross-repo coordination** | Not required. |

### 1.2 `core/capability_registry.py` — CapabilityRegistry

| Field | Value |
|-------|-------|
| **Module** | `core/capability_registry.py` |
| **Prior status** | GATED in PR-516; permitted for device-local bookkeeping only |
| **Classification** | **High misuse risk** |
| **Risk** | Routing decisions that query `CapabilityRegistry` instead of `CapabilityAssimilationLayer` bypass the unified capability graph. Devices may be selected without canonical capability verification. Silent correctness failure. |
| **Active callers** | Capability registry is used in some node self-registration paths and local device tracking. The key constraint is: **no routing decision may use CapabilityRegistry as its capability authority**. |
| **Action** | Add a routing-context guard: any `CapabilityRegistry` read in a routing context should raise/warn. Add test: `test_capability_registry_not_used_in_routing_context`. |
| **Cross-repo coordination** | Not required (V2-internal). |

### 1.3 `galaxy_gateway/cross_device_coordinator.py` — CrossDeviceCoordinator

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/cross_device_coordinator.py` |
| **Prior status** | Substrate-only with sentinel enforcement (PR-518); `LEGACY_DISPATCH` warning on incorrect use |
| **Classification** | **Still meaningful path** |
| **Risk** | Sentinel enforcement gates incorrect use, but sentinel can be bypassed by calling `_dispatch_cross_device_task()` directly (internal method). `LEGACY_DISPATCH` warnings are emitted to logs only — no monitoring/alerting exists in production. |
| **Active use** | Used as a substrate fallback when `AgentBridge` import fails. This path is active. |
| **Action 1** | Add a `LEGACY_DISPATCH` counter to the observability surface (Prometheus counter or status board metric). |
| **Action 2** | Audit whether the `_dispatch_cross_device_task()` direct-call bypass path is reachable from outside `DeviceRouter`. |
| **Cross-repo coordination** | Not required. |

### 1.4 `galaxy_gateway/device_router.py` — DeviceRouter policy residue

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/device_router.py` — `route_task._analyze_command()` and `route_task._select_devices()` |
| **Classification** | **High misuse risk** |
| **Risk** | `_analyze_command()` derives `exec_mode` and `task_type` — classification policy that belongs in `CommandRouter`. `_select_devices()` performs an independent device selection — a parallel selection path that can diverge from the admissibility chain result. If `CommandRouter` calls `DeviceRouter.route_task()` after already selecting targets, DeviceRouter's `_select_devices()` may re-select different targets. |
| **Action** | Extract `_analyze_command()` logic to `CommandRouter` pre-dispatch. Make `_select_devices()` accept externally resolved targets from `CommandRouter` rather than self-resolving. This is Gap SCHED-003. |
| **Cross-repo coordination** | Not required (V2-internal). |

### 1.5 `galaxy_gateway/agent_bridge.py` — AgentBridge

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/agent_bridge.py` |
| **Prior status** | Transitional — preferred over `CrossDeviceCoordinator` but not fully canonical |
| **Classification** | **Still meaningful path** |
| **Risk** | Agent bridge may not walk the full admissibility chain (Gates 1–3). Direct bridge invocations can dispatch to a device without canonical eligibility verification. |
| **Action** | Audit whether `AgentBridge` calls pass through `CommandRouter.route_envelope()` or bypass it. If bypass exists, add `CommandRouter` as a mandatory pre-step. |
| **Cross-repo coordination** | Not required. |

---

## Domain 2: Android compat REST and WebSocket paths

### 2.1 Android REST compat aliases

| Field | Value |
|-------|-------|
| **Paths** | `POST /api/devices/register`, `GET /api/devices/list` |
| **Classification** | **Immediately retireable after traffic analysis** |
| **Risk** | These alias paths duplicate canonical API paths. They are not the canonical paths. If active Android clients use them, retiring them breaks those clients. |
| **Traffic analysis** | Check access logs for caller identity and volume. If no active clients, retire immediately. If active, emit deprecation headers and set a retirement timeline with the Android team. |
| **Cross-repo coordination** | **Required** — Android client SDK must be updated to use canonical paths before retirement. |

### 2.2 Legacy WebSocket path `/ws/ufo3/{device_id}`

| Field | Value |
|-------|-------|
| **Path** | `galaxy_gateway/android_bridge.py` or `galaxy_gateway/websocket_handler.py` — `/ws/ufo3/{device_id}` |
| **Classification** | **Immediately retireable after traffic analysis** |
| **Risk** | If active Android client versions still connect via this path, retiring it disconnects them. |
| **Action** | Verify in access logs whether any clients are connecting via `/ws/ufo3/`. If none, retire. If some, set migration timeline. |
| **Cross-repo coordination** | **Required** — all Android client versions connecting via `/ws/ufo3/` must be updated or EOL'd. |

---

## Domain 3: Desktop / Windows legacy surfaces

### 3.1 `LocalAgentRuntime` (server-side planning role)

| Field | Value |
|-------|-------|
| **Module** | `core/local_agent_runtime.py` |
| **Prior status** | GATED; server-side planning role retired |
| **Classification** | **Harmless residue** |
| **Risk** | LOW. Boundary confusion only — developers may be unclear whether `LocalAgentRuntime` is still a valid server-side path. |
| **Action** | Add a class-level docstring clarifying that the server-side planning role is retired and only the device-side sandbox use case remains. |
| **Cross-repo coordination** | Not required. |

### 3.2 `desktop_projection/projection_engine.py` — ProjectionEngine

| Field | Value |
|-------|-------|
| **Module** | `desktop_projection/projection_engine.py` |
| **Prior status** | GATED; must delegate to `ProjectionSurfaceBridge` |
| **Classification** | **Transitional** |
| **Risk** | Gating is declared but runtime enforcement is not confirmed. If `ProjectionEngine` still assembles projections independently, display surfaces may diverge from canonical truth. |
| **Action** | Verify that all `ProjectionEngine` entry points call `ProjectionSurfaceBridge.enrich_runtime_projection()`. Add a test that fails if `ProjectionEngine` returns a projection without calling `enrich_runtime_projection()`. |
| **Cross-repo coordination** | Not required. |

---

## Domain 4: Protocol compat layer surfaces

### 4.1 `galaxy_gateway/protocol/compat.py` — AIP v1/v2 → v3 normalisation

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/protocol/compat.py` |
| **Classification** | **Still meaningful path** |
| **Risk** | LOW. This is the intended compat normalisation point. It should remain until all clients are confirmed to send AIP v3. Premature removal silently drops messages from older clients. |
| **Action** | Keep. Add a counter tracking normalisation events by source protocol version. This enables traffic analysis for retirement planning. |
| **Cross-repo coordination** | Required before removal — Android clients sending AIP v2 binary types must migrate. |

### 4.2 `galaxy_gateway/aip_protocol_v2.py` — AIP v2 binary protocol

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/aip_protocol_v2.py` |
| **Classification** | **Retireable after coordination** |
| **Risk** | Retiring AIP v2 binary before Android clients have migrated to AIP v3 JSON drops all messages from those clients. |
| **Action** | Keep until Android client migration is confirmed. Then retire in coordination with Android team. Set a concrete retirement date. |
| **Cross-repo coordination** | **Required**. |

### 4.3 `enhancements/multidevice/device_protocol.py` — LegacyMessageType

| Field | Value |
|-------|-------|
| **Module** | `enhancements/multidevice/device_protocol.py` — `LegacyMessageType` enum (AIP v2 binary) |
| **Classification** | **Retireable after coordination** |
| **Risk** | Same as above. Binary types `ANDROID_SCREEN` (0x60), `ANDROID_INPUT` (0x61), `SESSION_MIGRATE` (0x72), etc. are still in use on the Android side. |
| **Action** | Migrate Android clients to AIP v3 JSON equivalents. Then retire `LegacyMessageType` entries one by one. |
| **Cross-repo coordination** | **Required for each type**. |

---

## Domain 5: Long-tail compat registries

### 5.1 Capability-local registries in nodes

Many individual nodes maintain their own capability registries as local bookkeeping.
These are **harmless residue** as long as:

1. No routing decision reads from them (routing must use `CapabilityAssimilationLayer`)
2. They are populated from `CapabilityAssimilationLayer` state (not the reverse)

**Action**: Document the boundary clearly in `docs/CANONICAL_CAPABILITY_SCHEDULING_BASIS.md`.
Add a lint/test rule that flags `CapabilityRegistry` access in routing-context files.

### 5.2 `_handle_forward_log` catch-all pattern in AndroidBridge

The `_handle_forward_log` pattern in `galaxy_gateway/android_bridge.py` acts as a
catch-all for message types with no dedicated handler. This is a **compatibility
side-path** that logs and discards unrecognized messages. For message types that
should have real handlers (see ANDROID_PROTOCOL_MATURITY_MATRIX.md), `_handle_forward_log`
masks missing functionality — the system appears to accept the message, but nothing happens.

| Classification | **High misuse risk** |
|----------------|----------------------|
| **Risk** | `task_cancel` routed to `_handle_forward_log` means cancellation silently fails. |
| **Action** | Enumerate all types currently hitting `_handle_forward_log`. For each HIGH/MEDIUM priority type, add a dedicated handler. Remove the type from the catch-all once handled. |

---

## Domain 6: Observability gaps on compat surfaces

The following compat surfaces emit warnings or errors when invoked incorrectly, but
these signals are not observable in production:

| Surface | Warning type | Observability gap |
|---------|-------------|------------------|
| `CrossDeviceCoordinator` | `LEGACY_DISPATCH` structured warning | Logs only; no metric counter |
| `CapabilityRegistry` (routing context) | No warning emitted | No enforcement at all |
| `_handle_forward_log` | Log message only | No metric; no alerting |
| AIP v2 normalisation | Log message only (if added) | No metric; see action above |

**Action**: Add Prometheus counters (or equivalent) for `LEGACY_DISPATCH`, compat
normalisation events, and `_handle_forward_log` invocations. Wire to alerting if
counts exceed expected baseline.

---

## Impact summary table

| Surface | Classification | Cross-repo coord? | Priority |
|---------|---------------|-------------------|---------|
| `TaskRouter` / `TaskScheduler` | Harmless residue (if removed) | No | P3 — confirm removed |
| `CapabilityRegistry` in routing context | High misuse risk | No | P2 — add routing guard |
| `CrossDeviceCoordinator` | Still meaningful path | No | P2 — add observability |
| `DeviceRouter` policy residue | High misuse risk | No | P1 — extract to CommandRouter |
| `AgentBridge` | Still meaningful path | No | P2 — audit bypass risk |
| Android REST compat aliases | Immediately retireable after traffic analysis | **Yes** | P3 |
| `/ws/ufo3/` legacy WebSocket | Immediately retireable after traffic analysis | **Yes** | P3 |
| `LocalAgentRuntime` | Harmless residue | No | P4 — docstring only |
| `ProjectionEngine` | Transitional | No | P2 — verify delegation |
| `protocol/compat.py` | Still meaningful path (keep) | Yes (remove only with coordination) | Keep |
| `aip_protocol_v2.py` | Retireable after coordination | **Yes** | P3 |
| `LegacyMessageType` | Retireable after coordination | **Yes** | P3 |
| `_handle_forward_log` pattern | High misuse risk | No (server-side only) | P1 — add handlers |
| Observability gaps on all compat surfaces | — | No | P2 — add counters |

---

## Answer to acceptance criterion 7

**AC7 — Which compatibility surfaces still materially affect the architecture?**

> **Four surfaces carry material architectural risk today:**
>
> 1. **`DeviceRouter` policy residue** (SCHED-003, High misuse risk) — `_analyze_command()` and
>    `_select_devices()` create a second parallel device selection path that can diverge from
>    the canonical admissibility chain. This is the highest-risk surface.
>
> 2. **`CapabilityRegistry` in routing context** (High misuse risk) — routing decisions that
>    accidentally read from `CapabilityRegistry` instead of `CapabilityAssimilationLayer`
>    bypass the unified capability graph. No enforcement guard exists.
>
> 3. **`CrossDeviceCoordinator` without observability** (Still meaningful path) — the sentinel
>    is enforced, but `LEGACY_DISPATCH` warnings disappear into logs silently. Production
>    misuse is not detectable.
>
> 4. **`_handle_forward_log` for HIGH-severity types** (High misuse risk) — `task_cancel`
>    and `task_status` silently fail when they hit the catch-all. This is a correctness gap.
>
> Remaining surfaces (REST aliases, legacy WebSocket, AIP v2 binary) are lower-risk
> because they are clearly separated from canonical paths and can be retired on a
> planned timeline with client coordination.
