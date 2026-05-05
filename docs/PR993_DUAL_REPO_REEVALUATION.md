# PR #993 Dual-Repo Code-Grounded Reevaluation

> **Document type**: Code-grounded dual-repo reassessment.  
> **Methodology**: All conclusions derive from live import checks against real implementation code in both repositories. No markdown docs, PR descriptions, or architectural narratives are treated as evidence.  
> **Repositories covered**: `DannyFish-11/ufo-galaxy-realization-v2` (V2 center) + `DannyFish-11/ufo-galaxy-android` (Android participant).  
> **Companion module**: `core/pr993_dual_repo_reevaluation.py` — machine-checkable Python module that implements and validates all claims and paths described here.  
> **Companion tests**: `tests/test_pr993_dual_repo_reevaluation.py` — 57 tests validating the reevaluation module.

---

## 1. Purpose and Scope

PR #993 established a Chinese baseline cognition document (`docs/GALAXY_SYSTEM_FORMAL_BASELINE_COGNITION_ZH.md`) grounded in real code at time of authorship. That document is a narrative artifact and cannot self-validate as the code evolves.

This document and its companion code module (`core/pr993_dual_repo_reevaluation.py`) close four gaps left by PR #993:

1. No **explicit validation matrix** mapping each claim to specific code evidence or labeled gaps.
2. No **canonical-path review** distinguishing strongly established runtime behavior from schema/store/surface alignment.
3. No **true-closure vs surface-alignment breakdown**.
4. No **prioritized next-PR roadmap** based on code reality rather than narrative assumptions.

---

## 2. Dual-Repo Code-Level System Characterization

### 2.1 What the system actually is

Based on live code inspection across both repositories:

| Dimension | Code Evidence | Status |
|---|---|---|
| **System identity** | `core.device_types.DeviceType`, `core.command_router.CommandRouter`, `core.openclawd.OpenClawd`, `core.desktop_presence_runtime.TriState` | Center-governed distributed AI body network — confirmed by import |
| **V2 governance authority** | `galaxy_gateway.device_router.DeviceRouter`, `core.agent.capability_registry.CapabilityRegistry`, `core.canonical_task`, `core.operator_surface`, `core.routes.operator`, `galaxy_gateway.routes.websocket` | 8-dimension governance authority — structurally confirmed |
| **Android as runtime node** | `galaxy_gateway.android.handlers.registration`, `galaxy_gateway.android.handlers.capability_report`, `galaxy_gateway.android.handlers.delegated_signal`, `core.android_device_state_store`, `core.android_runtime_host`, `core.delegated_flow_entity` | Execution/carrier node — strongly established in V2 code |
| **Network as body** | `core.hybrid_orchestration_continuity`, `core.hybrid_executor`, `core.mesh_coordinator`, capability resolver, registration admission | Body/mesh framing — structurally confirmed |
| **Governance enforcement** | `core.distributed_release_gate_skeleton` (`is_enforcing=True`), CI workflows `governance_gate_enforcement.yml`, `dual_repo_reality_audit.yml` | CI-enforcing, not advisory |

### 2.2 Authority boundary

The authority boundary is explicitly machine-declared in `core.android_v2_continuity_contract`:

- **V2**: sole canonical orchestration authority (scheduling, routing, task truth, config, device admission, operator aggregation, gateway).
- **Android**: durable participant runtime — executes delegated tasks, reports execution truth. NOT the orchestration authority.

This boundary is enforced structurally by CI gates and protocol contracts, not just stated in documentation.

---

## 3. PR #993 Claim Validation Matrix

### Claim 1: System Identity — Galaxy is a center-governed distributed AI body network

**Evidence strength**: `STRONGLY_ESTABLISHED`

| Code anchor | Role |
|---|---|
| `core.device_types.DeviceType` | Differentiates device roles in the mesh |
| `core.command_router.CommandRouter` | Cross-device execution substrate |
| `core.openclawd.OpenClawd` | Four-stage center control-plane process flow |
| `core.desktop_presence_runtime.TriState` | SILENT/LIMINAL/MANIFEST tri-state lifecycle |
| `galaxy_gateway.websocket_handler` | Internal execution substrate (not a primary entrypoint) |
| `core.mesh_coordinator` | Body mesh registry |

**Android-side evidence**: `GalaxyConnectionService.kt` registers as participant; `BootReceiver.kt` starts service on boot for persistent network membership.

**Gap**: None for structural claim. *(CI does not have emulator-backed multi-device runtime evidence — but the structural claim is code-confirmed.)*

---

### Claim 2: V2 is the Sole Governance Authority (8 Dimensions)

**Evidence strength**: `STRONGLY_ESTABLISHED`

| Dimension | Code anchor |
|---|---|
| Scheduling | `core.scheduler.Scheduler` / `core.canonical_capability_scheduling_basis` |
| Routing | `galaxy_gateway.device_router.DeviceRouter` |
| Capability network | `core.agent.capability_registry.CapabilityRegistry` + `core.unified.capability_resolver.CapabilityResolver` |
| Task truth | `core.canonical_task` + `core.task_result_canonical_truth_chain` |
| Config | `core.unified_config.UnifiedConfig` |
| Operator aggregation | `core.operator_surface` + `core.routes.operator` |
| Device admission | `galaxy_gateway.android.handlers.registration` |
| Gateway | `galaxy_gateway.routes.websocket` |
| Authority contract | `core.android_v2_continuity_contract` (`V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY`) |

**Android-side evidence**: `ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY` declared in `core.android_v2_continuity_contract`. Android receives commands; V2 dispatches them.

**Gap**: None for structural claim.

---

### Claim 3: Android is a Runtime Carrier/Node, Not a Client

**Evidence strength**: `STRONGLY_ESTABLISHED`

| Code anchor | Role |
|---|---|
| `galaxy_gateway.android.handlers.registration` | Device registers as participant |
| `galaxy_gateway.android.handlers.capability_report` | Android reports real runtime capabilities |
| `galaxy_gateway.android.handlers.delegated_signal` | Android executes delegated tasks |
| `core.android_device_state_store` | V2 persists Android runtime state |
| `core.android_runtime_host` | V2-side runtime host for Android participant |
| `core.delegated_flow_entity` | Android can run delegated flows |

**Android-side evidence**: `GalaxyConnectionService.kt` sends `device_register` + `capability_report` on connect; `OfflineTaskQueue.kt` buffers results when disconnected; `ReconciliationSignal.kt` sends reconciliation signals (PR-51); `BootReceiver.kt` starts service on boot; native LLM runtime (llamaCpp/NCNN) on-device AI.

**Gap note**: `cross_device_enabled=false` is the build-time default in `config.properties` — every deployment requires manual activation. CI does not run an Android emulator, so activation evidence is deployment-conditional.

---

### Claim 4: Network is the Real Body (5 Code-Level Proofs)

**Evidence strength**: `STRONGLY_ESTABLISHED`

| Proof | Code anchor |
|---|---|
| Registration = network admission | `galaxy_gateway.android.handlers.registration` |
| Body mesh registry | `core.mesh_coordinator` |
| Hybrid execution spanning physical endpoints | `core.hybrid_executor` / `core.hybrid_execution_policy` |
| HybridOrchestrationContinuityRegistry | `core.hybrid_orchestration_continuity` |
| Capability queries spanning all nodes | `core.unified.capability_resolver.CapabilityResolver` |

**Android-side evidence**: Android is always a mesh participant: perpetual reconnect watchdog (PR-Block1) keeps it in the mesh indefinitely. Contributes native AI capabilities (llamaCpp/NCNN) to the body.

**Partial note**: Hybrid execution proof is **structural** — the code spans multiple physical endpoints by design, but no CI test runs a real 2-device hybrid task end-to-end.

---

### Claim 5: System is Beyond PoC (10+ Subsystems, 4 Execution Chains)

**Evidence strength**: `STRONGLY_ESTABLISHED`

The 4 execution chains cited in PR #993 are confirmed by module import:

| Chain | Code anchor |
|---|---|
| Registration | `galaxy_gateway.android.handlers.registration` |
| Capability report | `galaxy_gateway.android.handlers.capability_report` |
| Delegated execution signal | `galaxy_gateway.android.handlers.delegated_signal` |
| HandoffV2 result uplink | `galaxy_gateway.android.handlers.handoff_v2_result` |

Additional confirmed subsystems (sampled): `core.command_router`, `core.openclawd`, `core.agent.capability_registry`, `core.flow_continuity_coordinator`, `core.desktop_presence_runtime`, `galaxy_gateway.websocket_handler`, `core.distributed_release_gate_skeleton`, `core.system_final_acceptance_verdict`.

**Partial note**: "Confirmed" means the handler/module code exists and wire format is aligned. CI does not have emulator-backed end-to-end proof for all 4 chains. Chains 1 and 2 are best evidenced by unit tests (`test_android_capability_assimilation_ingress.py`). Chain 4 (HandoffV2 uplink) is structurally complete; runtime proof gap remains.

---

### Claim 6: Remaining Work is Closure/Consolidation, Not Capability Gaps

**Evidence strength**: `PARTIALLY_ESTABLISHED` ⚠️

This is the **only claim that cannot be called STRONGLY_ESTABLISHED**. Here's why:

PR #993 named 4 closure axes:

| Axis | Status |
|---|---|
| 1. Unified ingress | `core.unified_result_ingress` / `core.unified_runtime_truth_ingress` — EXISTS |
| 2. Android→V2 runtime state transparency | Store EXISTS (`core.android_device_state_store`), handler EXISTS (`galaxy_gateway.android.handlers.device_state_snapshot`), but **NO CI CROSS-REPO PROOF that a real Android emission fills the store** |
| 3. Unified multi-device orchestration | Structure present (`core.multi_device_canonical_governance`); no e2e multi-device CI test |
| 4. Unified manifestation surface | `core.desktop_presence_runtime.TriState` exists; no unified cross-device presence aggregation |

**Axis 2 is the critical issue**: PR #993 itself acknowledged "wire path incomplete" for Android→V2 runtime state transparency. This is still true. The store and handler exist (importable), but there is no machine-verifiable CI evidence that a real Android device's `device_state_snapshot` emission reaches the store and becomes visible through the operator surface.

**Verdict**: This claim is partially correct — the architecture supports a closure framing, but Axes 2 and 3 have meaningful **implementation/evidence gaps** rather than pure consolidation work.

---

### Claim 7: Direction Should be Toward Unified AI-Body Network

**Evidence strength**: `STRONGLY_ESTABLISHED`

| Code anchor | Role |
|---|---|
| `core.distributed_release_gate_skeleton` | CI gate with `is_enforcing=True` — blocks regressions |
| `core.android_v2_continuity_contract` | Authority boundary contract: Android = participant, V2 = orchestration authority |
| `core.dual_repo_system_map` | `DUAL_REPO_MAIN_CHAIN` declaration |
| `core.cross_repo_consistency_gates` | Prevents protocol drift between repos |

**Android-side evidence**: `CrossRepoConsistencyGate.kt` + `CrossRepoSignalClosureValidationTest.kt` confirm Android-side protocol alignment is also tested. Android never claims orchestration authority; the partition is code-enforced.

**Note**: Direction enforcement is structural/CI-level. It does not directly prove runtime capability closure — only that the architecture is consistently oriented toward the AI-body network framing.

---

## 4. Dual-Repo Canonical-Path Review

### Path 1: Android Registration

**V2 implemented**: ✅  **Android implemented**: ✅  **Runtime closed**: ⚠️ (unit tests, no CI emulator)

| V2 code anchors |
|---|
| `galaxy_gateway.android.handlers.registration.handle_device_register` |
| `galaxy_gateway.android_bridge.AndroidBridge` |
| `core.capability_assimilation.CapabilityAssimilationLayer` |

**Gap**: CI does not run a real Android emulator. Final activation evidence relies on unit tests (`test_android_capability_assimilation_ingress.py`) rather than cross-repo integration test.

**Closure label**: `partially_established` (best-evidenced among all 6 paths)

---

### Path 2: Android Runtime Snapshot Uplink

**V2 implemented**: ✅  **Android implemented**: ✅  **Runtime closed**: ❌

| V2 code anchors |
|---|
| `galaxy_gateway.android.handlers.device_state_snapshot` |
| `core.android_device_state_store.absorb_device_state_snapshot` |
| `core.operator_surface` (ecosystem surface) |
| `core.routes.operator` (`GET /api/v1/operator/devices/ecosystem`) |

**Critical gap**: No CI cross-repo test proves that a real Android device emission fills `android_device_state_store` to non-empty, and that the operator/ecosystem surface then returns Android-derived values. **This is the highest-priority evidence gap (PR-A).**

**Closure label**: `surface_alignment_only`

---

### Path 3: Android Execution Event Uplink

**V2 implemented**: ✅  **Android implemented**: ✅  **Runtime closed**: ❌

| V2 code anchors |
|---|
| `galaxy_gateway.android.handlers.device_state_snapshot` (handles `device_execution_event`) |
| `core.android_device_state_store.absorb_device_execution_event` |
| `core.flow_level_operator_surface` (flow projection) |
| `core.routes.operator` (`GET /api/v1/operator/devices/execution-events`) |

**Critical gap**: No CI test exercises the full path from real Android execution event emission through to non-empty `list_recent_execution_events()`. Shares the same CI evidence gap as the snapshot uplink path.

**Closure label**: `surface_alignment_only`

---

### Path 4: Task Dispatch → Android Execute → Result → Truth Chain

**V2 implemented**: ✅  **Android implemented**: ✅  **Runtime closed**: ⚠️ (unit tests, no CI emulator e2e)

| V2 code anchors |
|---|
| `galaxy_gateway.device_router.DeviceRouter.route_task` |
| `galaxy_gateway.android.handlers.task_lifecycle` (result ingestion) |
| `galaxy_gateway.android.handlers.handoff_v2_result` (handoff_result / handoff_failure / handoff_ack) |
| `core.task_result_canonical_truth_chain` |
| `galaxy_gateway.pending_delivery_buffer` (TTL=60s durable buffer + flush on reconnect) |
| `core.durable_result_idempotency` (idempotency guard) |

**Gap**: Unit tests exercise result ingestion path, but no CI emulator-backed test executes a real task dispatch from V2 → Android → result uplink → truth chain completion. Legality gates (`DelegatedFlowReadinessGate`) operate in **ADVISORY mode**, not blocking production dispatch paths. **(PR-B)**

**Closure label**: `partially_established`

---

### Path 5: Reconnect / Resume / Continuity Semantics

**V2 implemented**: ✅  **Android implemented**: ✅  **Runtime closed**: ❌

| V2 code anchors |
|---|
| `core.android_v2_continuity_contract` (7 reconnect/reattach scenario policies) |
| `core.flow_continuity_coordinator.FlowContinuityCoordinator` |
| `core.canonical_session_axis` |
| `core.attached_runtime_session` |

**Gap**: `android_v2_continuity_contract.py` declares all 7 scenario policies. Android perpetual reconnect watchdog (PR-Block1) is in place. BUT: V2 continuity coordinator does not yet systematically bridge Android `durable_session_id` / `session_continuity_epoch` fields into reconnect classification. Reconnects may be misclassified as fresh sessions. **(PR-C V2 + PR-C Android)**

**Closure label**: `partially_established`

---

### Path 6: Orchestration Consumes Android Runtime Truth

**V2 implemented**: ✅  **Android implemented**: ✅ (emits)  **Runtime closed**: ❌

| V2 code anchors |
|---|
| `core.operator_surface` (`OperatorSnapshot.android_ecosystem`) |
| `core.android_device_state_store.get_device_ecosystem_summary` |
| `galaxy_gateway.routing.device_selection` (exec-mode filtering) |
| `core.unified.gateway_capability_projection` (canonical read path) |

**Critical gap**: The read path exists but `android_device_state_store` is never filled by real Android emissions in CI. All orchestration decisions nominally referencing Android runtime truth are effectively reading from an empty store. This gap is resolved by closing PR-A first.

**Closure label**: `surface_alignment_only`

---

## 5. True-Closure vs Surface-Alignment Breakdown

| Claim | Evidence Strength | Closure Label |
|---|---|---|
| System identity (distributed AI body network) | STRONGLY_ESTABLISHED | Structural confirmation |
| V2 sole governance authority (8 dimensions) | STRONGLY_ESTABLISHED | Structural confirmation |
| Android is runtime carrier, not client | STRONGLY_ESTABLISHED | Structural + deployment-conditional |
| Network is the body (5 proofs) | STRONGLY_ESTABLISHED | Structural confirmation |
| System is beyond PoC (4 chains) | STRONGLY_ESTABLISHED | Structural + partial CI evidence |
| Remaining work is closure, not capability gaps | **PARTIALLY_ESTABLISHED** ⚠️ | Axes 2+3 have evidence gaps |
| Direction toward unified AI body | STRONGLY_ESTABLISHED | CI-enforced direction |

| Canonical Path | Closure Label |
|---|---|
| Android registration | `partially_established` (best-evidenced, unit-tested) |
| Runtime snapshot uplink | `surface_alignment_only` ⚠️ (no CI cross-repo proof) |
| Execution event uplink | `surface_alignment_only` ⚠️ (no CI cross-repo proof) |
| Task dispatch → execute → result | `partially_established` (unit-tested, no CI e2e) |
| Reconnect / continuity | `partially_established` (contract declared, not CI-proven) |
| Orchestration consumes Android truth | `surface_alignment_only` ⚠️ (store empty in CI) |

### Summary

- **3 paths** that are `surface_alignment_only` — the store/schema/route/handler exists but no real Android data flows through in CI.
- **2 paths** that are `partially_established` — real code on both sides, unit tests exist, but no CI emulator-backed end-to-end proof.
- **1 path** that is `partially_established` (registration) — best-evidenced, capability assimilation tested.

The overall system is **STRUCTURALLY_COMPLETE_BUT_PARTIALLY_EVIDENCED**:
- All 6 canonical paths have code on both V2 and Android sides.
- The protocol wire format is aligned (`fresh_dual_repo_code_audit.py` confirmed `TRANSPORT_OVERALL = COMPLETE`).
- The evidence gap is CI runtime activation: no cross-repo test proves real Android data flows through any of the three `surface_alignment_only` paths.

---

## 6. Prioritized Next-PR Roadmap

### P0 — Runtime Evidence Blockers (highest priority)

#### P0-1: `P0-ANDROID-RUNTIME-CI-EVIDENCE` (PR-A)
**Establish real Android→V2 runtime evidence in CI (emulator-backed snapshot verification)**

**Rationale**: `android_device_state_store` and snapshot handler exist. Operator/ecosystem surface reads from the store. No CI test proves real Android emission fills it. Until closed: runtime snapshot uplink, execution event uplink, and orchestration-consumes-Android-truth all remain `surface_alignment_only`.

**Repos**: V2 + Android  
**Work**: Add CI workflow with Android emulator (or high-fidelity stub); exercise canonical path: Android register → emit `device_state_snapshot` → V2 absorbs → store non-empty → operator surface returns Android-derived values.

#### P0-2: `P0-DELEGATED-EXEC-RUNTIME-CLOSURE` (PR-B)
**Verify delegated Android execution runtime closure on the canonical V2 truth chain**

**Rationale**: `DeviceRouter`, `task_lifecycle` handler, `handoff_v2_result` handler, and `task_result_canonical_truth_chain` all exist. No CI test exercises the full chain: V2 dispatch → Android execution → result uplink → truth chain completion. Until closed, task dispatch path remains `partially_established` rather than `strongly_established`.

**Repos**: V2 + Android  
**Work**: Add/strengthen e2e verification: V2 dispatch → Android emulator execute → result uplink → V2 truth chain complete. Assert runtime closure evidence becomes positive.

---

### P1 — Canonical Closure Gaps

#### P1-1: `P1-CONTINUITY-BRIDGE` (PR-C V2 + PR-C Android)
**Bridge Android durable continuity identity into V2 continuity coordination**

**Rationale**: `android_v2_continuity_contract.py` declares all 7 reconnect/reattach scenario policies. Android perpetual reconnect watchdog (PR-Block1) in place. BUT V2 continuity coordinator doesn't bridge `durable_session_id` / `session_continuity_epoch` into reconnect classification. Reconnects may be misclassified as fresh sessions.

**Repos**: V2 (extend continuity coordinator) + Android (persist/resend durable identity)  
**Depends on**: P0-1

#### P1-2: `P1-LEGALITY-GATE-ENFORCEMENT`
**Promote delegated flow legality gates from ADVISORY to BLOCKING**

**Rationale**: `DelegatedFlowReadinessGate`, `DelegatedFlowAcceptanceGate`, and `CapabilityRoutingGate` operate in ADVISORY mode — they log verdicts but do NOT block dispatch in production paths. Illegal/unready tasks can still reach Android.

**Repos**: V2  
**Depends on**: P0-2

---

### P2 — Surface Alignment Upgrades

#### P2-1: `P2-MULTI-DEVICE-ORCHESTRATION-E2E`
**Establish e2e CI evidence for multi-device hybrid orchestration (minimum 2-device)**

**Rationale**: `multi_device_canonical_governance`, `hybrid_executor`, and `HybridOrchestrationContinuityRegistry` are importable. Claim 4 (network is the body) cites hybrid execution as structural proof. No CI test runs a 2-device hybrid task end-to-end.

**Repos**: V2 + Android  
**Depends on**: P0-1, P0-2

#### P2-2: `P2-ZERO-CONFIG-PROVISIONING`
**Add zero-config provisioning / QR-code pairing for fresh Android installs**

**Rationale**: `MULTI_DEVICE_PLUG_AND_RUN = MISSING`. `cross_device_enabled=false` by default. Default gateway URL is a Tailscale placeholder. Every deployment requires two manual steps.

**Repos**: Android

---

### P3 — Deployment Hardening

#### P3-1: `P3-UNIFIED-MANIFESTATION-SURFACE`
**Unify Android + desktop manifestation/presence surface into single operator-observable truth**

**Rationale**: `TriState` lifecycle exists in `DesktopPresenceRuntime`. Android presence expressed through runtime snapshots. No unified cross-device manifestation surface aggregates both into single operator-observable truth (Axis 4 from PR #993).

**Repos**: V2  
**Depends on**: P0-1, P1-1

---

## 7. Overall Dual-Repo Verdict

```
PR993_DUAL_REPO_REEVALUATION_VERDICT:
STRUCTURALLY_COMPLETE_BUT_PARTIALLY_EVIDENCED

The Galaxy dual-repo system architecture is strongly code-confirmed.
All 7 PR #993 claims have at least PARTIALLY_ESTABLISHED evidence.
6 of 7 claims are STRONGLY_ESTABLISHED.

The honest characterization is:
  - Core protocol, transport, registration, task dispatch, result ingestion,
    governance gates, and authority boundaries: code-confirmed.
  - Android is a real runtime node, not a UI client: code-confirmed.
  - V2 is the sole governance authority across 8 dimensions: code-confirmed.
  
  BUT:
  - 3 of 6 canonical paths are surface_alignment_only:
    the read path exists but no real Android data flows through in any CI test.
  - Claim 6 (remaining work is closure) is only PARTIALLY_ESTABLISHED:
    Axes 2 and 3 have meaningful implementation/evidence gaps,
    not just consolidation work.

Next priorities:
  P0 (must close first):
    1. PR-A: CI cross-repo Android→V2 snapshot activation evidence
    2. PR-B: Delegated execution runtime closure CI evidence

  After P0 closes:
    P1: Continuity bridge + legality gate enforcement
    P2: Multi-device e2e + zero-config provisioning
    P3: Unified manifestation surface
```

---

## 8. Machine-Checkable Evidence

All validations in this document are implemented as live import checks in:

- **`core/pr993_dual_repo_reevaluation.py`** — programmatic companion module
- **`tests/test_pr993_dual_repo_reevaluation.py`** — 57-test validation suite

To verify:
```python
from core.pr993_dual_repo_reevaluation import assert_pr993_reevaluation_invariants
assert_pr993_reevaluation_invariants()
```

To get the full report:
```python
from core.pr993_dual_repo_reevaluation import build_pr993_reevaluation
report = build_pr993_reevaluation()
print(report.to_json())
```
