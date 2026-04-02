# Multi-Device Control Integrity — Residual Gap Map

> **PR-517**: Cross-Device / Multi-Device Control Integrity Audit
> **Status**: Active — residual gaps for follow-up
> **Authority module**: `core/multi_device_control_integrity.py`

---

## Overview

This document is the **residual integrity map** produced by the PR-517
cross-device / multi-device control integrity audit.  It summarises:

1. What was audited and the key findings per area.
2. The gaps that are **open** (not closed in this PR) and require follow-up.
3. The target modules and recommended actions for each gap.

The machine-readable gap catalog lives in
`core/multi_device_control_integrity.py` (`_RESIDUAL_GAPS`).
Use `get_residual_integrity_gaps()` to retrieve it programmatically.

---

## Architecture Summary

The canonical multi-device control flow is:

```
User / device entry (any device)
    │
    ▼
TaskAdapter.adapt_to_canonical_task()  ← normalise to canonical task
    │
    ▼
CommandRouter.route_envelope()   ← SOLE canonical cross-device dispatcher
    │
    ├─ local path ──────────────────────────────────────────────────────►
    │       TaskGraphRuntime ← record
    │       Local executor
    │
    └─ cross-device path ────────────────────────────────────────────────►
            DeviceFormation.resolve_formation()  ← formation descriptor
            │
            ▼
            Gateway substrate (DeviceRouter / CrossDeviceCoordinator)
            │   (execution plumbing only; does not make routing decisions)
            │
            ▼
            Remote device executor
            │
            ▼
            ResultEnvelope  ← canonical result container
            │
            ▼
            CrossDeviceExecutionChain.record_chain_execution()
            │
            ├─ TaskGraphRuntime.complete_from_result_envelope()
            ├─ ReplayFoundation.record_task_execution()
            ├─ OperatorSurface (inspector reads)
            └─ Projection / StatusBoard (display)
```

---

## Audit Area 1: Entry Unification

**Governance invariant**: All device-originated entry flows converge onto
`CommandRouter → TaskEnvelope → canonical execution spine`.

**Policy sentinel**: `ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY`

### Findings

| # | Module | Status | Note |
|---|--------|--------|------|
| ✅ | `core/routes/tasks.py` | Canonical | `CANONICAL_TASK_*_FRONT_LOADED` sentinel; calls `adapt_to_canonical_task()` |
| ✅ | `galaxy_gateway/orchestrator/task_orchestrator.py` | Canonical | `CANONICAL_TASK_*_FRONT_LOADED` sentinel |
| ✅ | `core/scheduler.py` | Canonical | `SCHEDULER_ROUTES_COMMAND_ROUTER` sentinel |
| ✅ | `core/agent/kernel.py` | Canonical | `CANONICAL_TASK_*_FRONT_LOADED` sentinel |
| ⚠️ | `core/routes/devices.py` → `/api/v1/devices/cross-device` | **GAP** | Calls `CrossDeviceCoordinator` directly — **GAP-517-001** |
| ⚠️ | `core/routes/devices.py` → `/api/v1/devices/parallel` | **GAP** | Parallel dispatch without `CommandRouter` admission — **GAP-517-002** |

### Open Gaps

#### GAP-517-001 · HIGH
**Module**: `core/routes/devices.py`  
**Description**: The `/api/v1/devices/cross-device` endpoint calls
`CrossDeviceCoordinator.execute_cross_device_task()` directly, bypassing
`CommandRouter` and `TaskEnvelope` normalisation.

**Recommended action**: Normalise the incoming request to a `TaskEnvelope` and
route through `CommandRouter.route_envelope()` instead.  The coordinator
remains valid as internal substrate invoked by `CommandRouter`; it must not be
a primary entry target.

#### GAP-517-002 · MEDIUM
**Module**: `core/routes/devices.py`  
**Description**: The `/api/v1/devices/parallel` endpoint dispatches individual
device commands in parallel without `CommandRouter` admission.

**Recommended action**: Create a `TaskEnvelope` for the top-level parallel
request and use `CommandRouter` to fan out sub-envelopes.

---

## Audit Area 2: Dispatch Authority

**Governance invariant**: `CommandRouter.route_envelope()` is the sole
canonical cross-device dispatcher.

**Policy sentinel**: `NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY`

### Findings

| # | Dispatcher | Classification | Note |
|---|-----------|---------------|------|
| ✅ | `core.command_router.CommandRouter` | Canonical | Sole authorised dispatcher |
| ⚠️ | `galaxy_gateway.device_router.DeviceRouter._dispatch_cross_device_task` | Substrate | Acceptable as CommandRouter substrate; not as independent authority |
| ⚠️ | `galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator` | Substrate | Same constraint as DeviceRouter |
| ⚠️ | Direct REST-route dispatch | **GAP** | Routes can call coordinator without going through CommandRouter — **GAP-517-003** |

### Open Gaps

#### GAP-517-003 · HIGH
**Modules**: `galaxy_gateway/device_router.py`, `galaxy_gateway/cross_device_coordinator.py`, `core/routes/devices.py`  
**Description**: `DeviceRouter._dispatch_cross_device_task()` and
`CrossDeviceCoordinator.execute_cross_device_task()` are callable as
independent dispatch authorities from outside the gateway substrate.

**Recommended action**: Add an access-control sentinel or assertion that
records/warns when these methods are called without being invoked through
`CommandRouter`.  Gate the canonical path so that direct callers log a
`LEGACY_DISPATCH` warning and record a `DispatchAuthorityRecord` with
`dispatch_path=COORDINATOR_LEGACY`.

---

## Audit Area 3: Formation / Participation Truth

**Governance invariant**: `DeviceFormationGroup` is the canonical formation
descriptor; participation and readiness facts come exclusively from the
admissibility chain (Layers 1–3).

**Policy sentinel**: `FORMATION_TRUTH_SINGLE_SOURCE_POLICY`

### Findings

| # | Module | Status | Note |
|---|--------|--------|------|
| ✅ | `core/device_readiness.py` | Layer 1 | Transport-presence / routability |
| ✅ | `core/device_participation.py` | Layer 2 | Orchestration eligibility |
| ✅ | `core/target_device_validator.py` | Layer 3 | Per-device validation |
| ✅ | `core/cross_device_candidates.py` | Layer 6 | Candidate resolution (Layers 1+2+4) |
| ✅ | `core/device_formation/` | PR-17 | Formation group + resolver |
| ✅ | `galaxy_gateway/device_router.py` | **Resolved** | `resolve_formation()` called before dispatch — **GAP-517-004 closed (PR-520)** |
| ✅ | `core/constellation_runtime.py` | **Resolved** | Deny-by-default fallback when participation unavailable — **GAP-517-005 closed (PR-520)** |

### Open Gaps

#### GAP-517-004 · MEDIUM · ✅ RESOLVED (PR-520)
**Modules**: `galaxy_gateway/device_router.py`, `galaxy_gateway/cross_device_coordinator.py`  
**Description**: Cross-device execution proceeds without producing or attaching
a `DeviceFormationGroup`, making formation truth implicit and
non-inspectable.

**Resolution (PR-520)**: `DeviceRouter._dispatch_cross_device_task()` and
`CrossDeviceCoordinator.execute_cross_device_task()` now call
`resolve_formation()` from `core.device_formation` at the start of every
cross-device dispatch / execution.  The resolved `DeviceFormationGroup`
captures source device, primary execution device, all participating members,
and their role assignments.  A `FormationTruthRecord` is emitted to the
integrity runtime for audit visibility.  The formation descriptor is attached
to the result payload under the `"formation"` key.  Sentinels:
`DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED` and
`CROSS_DEVICE_COORDINATOR_FORMATION_DESCRIPTOR_ATTACHED`.

#### GAP-517-005 · MEDIUM · ✅ RESOLVED (PR-520)
**Module**: `core/constellation_runtime.py`  
**Description**: `ConstellationRuntime._is_orchestration_ready()` returns
`True` (permissive fallback) when `device_participation` is unavailable,
allowing devices that haven't passed the admissibility chain to enter
constellation orchestration.

**Resolution (PR-520)**: The fallback is now `False` (deny-by-default).
When the participation layer raises or is not importable the method returns
`False` and emits a structured `WARNING` log including `device_id` and the
error details so operators can identify when the gate is not functioning.
Sentinel: `CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT`.

---

## Audit Area 4: Local-vs-Cross-Device Control Semantics

**Governance invariant**: Every cross-device control flow explicitly
distinguishes `source_device_id`, `target_device_id`, `is_local`,
`is_remote_dispatch`, and `is_takeover`.

**Policy sentinel**: `SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY`

### Findings

| # | Semantic | Status | Note |
|---|---------|--------|------|
| ✅ | `CanonicalTask.TaskIntent.entry_device_id` | Set at entry | Canonical task carries entry device |
| ✅ | `CrossDeviceExecutionChain.ChainExecutionRecord.device_id` | Tracked | Per-execution device tracking |
| ✅ | `DeviceFormationGroup.source_device_id` + `primary_execution_device_id` | Explicit | Formation group separates source/primary |
| ✅ | `DeviceRouter.route_task()` context | **RESOLVED (PR-521)** | Explicit `source_device_id`/`target_device_id` + `ControlSemanticRecord` — **GAP-517-006** |

### Resolved Gaps

#### GAP-517-006 · MEDIUM · ✅ RESOLVED (PR-521)
**Module**: `galaxy_gateway/device_router.py`  
**Description**: The task context in `route_task()` previously used `device_id`
for both the originating device and the target device, causing semantic
ambiguity.

**Resolution (PR-521)**:
- `route_task()` now extracts an explicit `source_device_id` from the inbound
  context, preferring the dedicated `source_device_id` key and falling back to
  `device_id` for legacy callers.
- `target_device_id` is derived from the routing decision (`_select_devices`).
- Both fields are propagated into the task dict and the `TaskEnvelope` metadata.
- A `ControlSemanticRecord` is emitted to the integrity runtime after every
  routing decision, with execution mode (`LOCAL_EXECUTION`, `REMOTE_DISPATCH`,
  `TAKEOVER`, `HYBRID`) derived automatically.
- `dispatch_task()` also carries `source_device_id` and `target_device_id` in
  its `TaskEnvelope` metadata.
- Sentinel: `DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION`.

---

## Audit Area 5: Result / State Return into Canonical Surfaces

**Governance invariant**: Cross-device execution results are normalised into
`ResultEnvelope` and surfaced through `OperatorSurface`, `TaskGraphRuntime`,
`ReplayFoundation`, and the projection / status board layers.

**Policy sentinel**: `CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY`

### Findings

| # | Surface | Status | Note |
|---|---------|--------|------|
| ✅ | `CrossDeviceExecutionChain.ResultEnvelope` | Defined | Canonical result container exists |
| ✅ | `TaskGraphRuntime.complete_from_result_envelope()` | Available | Can receive ResultEnvelope |
| ✅ | `OperatorSurface` | Available | Inspectable via REST API (PR-510) |
| ✅ | Projection `enrich_runtime_projection()` | Available | PR-511 bridge wired into projection routes |
| ⚠️ | `CrossDeviceCoordinator` result path | **GAP** | Returns raw dicts without ResultEnvelope/chain recording — **GAP-517-007** |
| ⚠️ | Multi-device projection endpoint | **GAP** | Projection built from raw registry data, not from canonical chain state — **GAP-517-008** |

### Open Gaps

#### GAP-517-007 · HIGH · ✅ RESOLVED (PR-519)
**Modules**: `galaxy_gateway/cross_device_coordinator.py`, `galaxy_gateway/device_router.py`  
**Description**: Cross-device results are returned as raw dicts without being
normalised into `ResultEnvelope` or recorded via `record_chain_execution()`.
This means outcomes remain in transport-local state without
`OperatorSurface`, `TaskGraphRuntime`, or `ReplayFoundation` exposure.

**Resolution (PR-519)**: `core/cross_device_result_surface.py` introduces
`surface_cross_device_result()` which:
- Normalises raw dicts into `ResultEnvelope` via `build_result_envelope()`
- Records a `ChainExecutionRecord` in `CrossDeviceChainSingleton`
- Calls `TaskGraphRuntime.complete_from_result_envelope()`
- Emits a `ReplayFoundation` runtime event (`TASK_COMPLETED` / `TASK_FAILED`)
- Returns a `ResultSurfaceRecord` tracking surface coverage

Wired into `CrossDeviceCoordinator.execute_cross_device_task()` and
`DeviceRouter.route_task()` on all representative result paths (success +
failure).  Sentinel: `CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED`.

#### GAP-517-008 · MEDIUM · ⚠️ PARTIALLY RESOLVED (PR-519)
**Modules**: `core/routes/projection.py`, `contracts/multi_device_runtime_projection.py`  
**Description**: The multi-device runtime projection endpoint builds its
payload from raw registry/session data rather than consuming state from the
canonical `CrossDeviceChainSingleton` or `TaskGraphRuntime`.

**Partial resolution (PR-519)**: The `/api/v1/projection/runtime/multi-device`
endpoint now enriches the projection `metadata` with:
- `cross_device_chain_snapshot`: recent canonical chain records + counts
- `task_graph_snapshot`: recent task graph runtime records + node count

A full rewrite of the projection body (`merged_results` field) to directly
consume canonical chain state is deferred to a future PR per PR-519 non-goals.

---

## Summary Table

| Gap ID | Area | Severity | Status |
|--------|------|----------|--------|
| GAP-517-001 | entry_unification | HIGH | ✅ **Resolved (PR-518)** |
| GAP-517-002 | entry_unification | MEDIUM | ⚠️ **Open (deferred — see PR-523)** |
| GAP-517-003 | dispatch_authority | HIGH | ✅ **Resolved (PR-518)** |
| GAP-517-004 | formation_truth | MEDIUM | ✅ Resolved (PR-520) |
| GAP-517-005 | formation_truth | MEDIUM | ✅ Resolved (PR-520) |
| GAP-517-006 | control_semantics | MEDIUM | ✅ Resolved (PR-521) |
| GAP-517-007 | result_surface | HIGH | ✅ Resolved (PR-519) |
| GAP-517-008 | result_surface | MEDIUM | ✅ **Resolved (PR-522)** |

**Remaining high severity gaps after PR-523 acceptance pass**: None.  
**Open gaps after PR-523 acceptance pass**: 1 (GAP-517-002, MEDIUM severity, explicitly deferred).

---

## PR-523 Integrated Acceptance Closure Accounting

> This section was added by PR-523 after the end-to-end acceptance and
> verification pass.

### What PR-523 verifies

PR-523 established the end-to-end acceptance and verification layer that
proves the post-PR-517 multi-device control architecture now behaves
coherently as a whole.  The following closure accounting confirms the state
of each gap after PR-518 through PR-522:

| Gap ID | Closed by | Resolution summary |
|--------|-----------|-------------------|
| GAP-517-001 | **PR-518** | `/api/v1/devices/cross-device` now normalises to `TaskEnvelope` and dispatches through `CommandRouter.route_envelope()`.  Sentinel: `CROSS_DEVICE_REST_INGRESS_CANONICAL`. |
| GAP-517-002 | **Deferred** | `/api/v1/devices/parallel` still fans out without canonical admission.  Explicitly documented as open; not hidden.  Tracked in `_RESIDUAL_GAPS` with `is_resolved=False`. |
| GAP-517-003 | **PR-518** | `CrossDeviceCoordinator` and `DeviceRouter` are now substrate-only; `CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY` and `DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY` sentinels enforce the boundary. |
| GAP-517-004 | **PR-520** | `DeviceFormationGroup` is now resolved and attached at cross-device execution entry.  Sentinel: `DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED`. |
| GAP-517-005 | **PR-520** | `ConstellationRuntime._is_orchestration_ready()` now returns `False` (deny-by-default) when participation layer is unavailable.  Sentinel: `CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT`. |
| GAP-517-006 | **PR-521** | `source_device_id` is explicitly extracted and propagated in `DeviceRouter.route_task()` and `dispatch_task()`.  Sentinel: `DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION`. |
| GAP-517-007 | **PR-519** | `surface_cross_device_result()` is the single canonical exit point; updates `CrossDeviceChainSingleton`, `TaskGraphRuntime`, `ReplayFoundation`, and `OperatorSurface`.  Sentinel: `CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED`. |
| GAP-517-008 | **PR-522** | `enrich_multi_device_projection()` consumes `CrossDeviceChainSingleton`, `TaskGraphRuntime`, `OperatorSurface`, and `MultiDeviceControlIntegrityRuntime`.  Sentinel: `MULTI_DEVICE_PROJECTION_GAP008_RESOLVED`. |

### Verification artifacts

- **Test harness**: `tests/test_pr523_e2e_multi_device_acceptance.py` — 99 tests, all passing.
- **Acceptance matrix**: `docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md`
- **Closure accounting sentinel**: `PR523_RESIDUAL_CLOSURE_ACCOUNTING` in `core/multi_device_control_integrity.py`
- **Coverage sentinel**: `MULTI_DEVICE_ACCEPTANCE_MATRIX_COVERAGE` in `core/multi_device_control_integrity.py`
- **Acceptance verified sentinel**: `MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED` in `core/multi_device_control_integrity.py`

---

## Recommended Follow-Up PR Order

> ✅ = completed by PR-518 through PR-522.

1. ✅ **Close GAP-517-001 and GAP-517-003** (PR-518) — entry unification + dispatch authority.

2. ✅ **Close GAP-517-007** (PR-519) — result surface closure.

3. ✅ **Close GAP-517-005** (PR-520) — constellation deny-by-default gate.

4. ✅ **Close GAP-517-004** (PR-520) — formation truth descriptor.

5. ✅ **Close GAP-517-006** (PR-521) — source/target control semantic separation.

6. ✅ **Close GAP-517-008** (PR-522) — projection canonicalization.

7. ⚠️ **Close GAP-517-002** (future) — `/api/v1/devices/parallel` canonical admission.
   Create a `TaskEnvelope` for the top-level parallel request and fan out
   sub-envelopes through `CommandRouter`.

---

## What This PR Establishes

PR-517 establishes the **integrity governance layer** (`core/multi_device_control_integrity.py`) with:

- **5 authority sentinels** covering entry unification, dispatch authority,
  formation truth, control semantic separation, and result canonical surfacing.
- **5 policy sentinels** expressing the governance invariants.
- **5 record types** (`EntryUnificationRecord`, `DispatchAuthorityRecord`,
  `FormationTruthRecord`, `ControlSemanticRecord`, `ResultSurfaceRecord`) for
  instrumenting and observing multi-device control flows.
- **`ResidualIntegrityGap`** type and a static catalog of 8 known gaps.
- **`MultiDeviceControlIntegrityRuntime`** singleton for bounded in-memory
  integrity event logging.
- **`record_integrity_event()`** helper for emitting structured integrity
  observations with appropriate log-level warnings for legacy paths.
- **135 tests** covering all record types, factory helpers, singleton
  management, ring-buffer overflow, counters, and representative
  end-to-end scenarios for all 5 audit areas.

PR-523 adds the **end-to-end acceptance and verification layer** on top of the
PR-517 governance layer, with 3 new sentinels
(`MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED`, `MULTI_DEVICE_ACCEPTANCE_MATRIX_COVERAGE`,
`PR523_RESIDUAL_CLOSURE_ACCOUNTING`), 99 acceptance tests, and this updated
residual map.  See `docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md` for the full
acceptance matrix.
