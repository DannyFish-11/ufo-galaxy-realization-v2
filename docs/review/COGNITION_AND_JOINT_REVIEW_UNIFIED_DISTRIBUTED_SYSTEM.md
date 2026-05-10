# Authoritative Cognition & Joint Review Plan  
## Unified Distributed Center-Network System — V2 × Android × Multi-Device  
### Repositories: `DannyFish-11/ufo-galaxy-realization-v2` (V2) · `DannyFish-11/ufo-galaxy-android` (Android)

> **Document class**: Authoritative engineering cognition and joint cross-repository review plan.  
> **Supersedes**: All prior single-pass review documents and all partial problem lists in PR-9A through PR-14B.  
> **Acceptance bar**: Real code capability, real runtime behavior, real dual-runtime or multi-runtime
> validation — not stub-backed, protocol-only, or local-only simulation.  
> **Date**: 2026-05-10  

---

## Table of Contents

1. [System Model That Governs This Review](#1-system-model-that-governs-this-review)  
2. [Complete Structured Issue Inventory](#2-complete-structured-issue-inventory)  
   2.1 [Truth Adjudication](#21-truth-adjudication)  
   2.2 [Lifecycle Coordination](#22-lifecycle-coordination)  
   2.3 [Tracking Convergence](#23-tracking-convergence)  
   2.4 [Ownership Convergence and Resumed Ownership Transfer](#24-ownership-convergence-and-resumed-ownership-transfer)  
   2.5 [Takeover Completion and Ownership Return](#25-takeover-completion-and-ownership-return)  
   2.6 [Proof Quality — Stale, Conflicting, Unresolved State](#26-proof-quality--stale-conflicting-unresolved-state)  
   2.7 [Canonical Diagnosis Reconciliation](#27-canonical-diagnosis-reconciliation)  
   2.8 [Android-Originated and Other-Device-Originated Diagnostics](#28-android-originated-and-other-device-originated-diagnostics)  
   2.9 [Audit Provenance, Trust, Freshness, Inferred vs. Confirmed](#29-audit-provenance-trust-freshness-inferred-vs-confirmed)  
   2.10 [Readiness and Closure Semantics](#210-readiness-and-closure-semantics)  
   2.11 [Distributed-Center Coordination Semantics](#211-distributed-center-coordination-semantics)  
   2.12 [Local-Link vs. Cross-Device Path Consistency](#212-local-link-vs-cross-device-path-consistency)  
   2.13 [Mesh/Network Participation and Degraded Partial Participation](#213-meshnetwork-participation-and-degraded-partial-participation)  
   2.14 [Recovery Semantics After Interruption, Partition, Reconnect, Restart](#214-recovery-semantics-after-interruption-partition-reconnect-restart)  
   2.15 [Multi-Device Simultaneous or Conflicting Takeover Conditions](#215-multi-device-simultaneous-or-conflicting-takeover-conditions)  
   2.16 [Authoritative Source Selection and Convergence Under Disagreement](#216-authoritative-source-selection-and-convergence-under-disagreement)  
   2.17 [True Two-Runtime / Multi-Runtime Cross-Repository Validation](#217-true-two-runtime--multi-runtime-cross-repository-validation)  
   2.18 [Elimination of Fake Proof — Stubs, Protocol-Only, Local-Only](#218-elimination-of-fake-proof--stubs-protocol-only-local-only)  
   2.19 [Additional Systemic Gaps](#219-additional-systemic-gaps)  
3. [Complete Integrated PR Plan](#3-complete-integrated-pr-plan)  
   3.1 [Problem-to-Responsibility Mapping](#31-problem-to-responsibility-mapping)  
   3.2 [Sequencing and Dependencies](#32-sequencing-and-dependencies)  
   3.3 [What Counts as Real Proof vs. Insufficient Proof](#33-what-counts-as-real-proof-vs-insufficient-proof)  
   3.4 [Regression and Validation Expectations](#34-regression-and-validation-expectations)  
   3.5 [Path to Complete Fully Integrated Solution](#35-path-to-complete-fully-integrated-solution)  
4. [Joint Cross-Repository Review Prompt and Instruction Set](#4-joint-cross-repository-review-prompt-and-instruction-set)  
   4.1 [Mandatory Pre-Review Declarations](#41-mandatory-pre-review-declarations)  
   4.2 [Code Path Verification Checklist](#42-code-path-verification-checklist)  
   4.3 [Distributed-Center Semantics Checklist](#43-distributed-center-semantics-checklist)  
   4.4 [Local-Link and Cross-Device Parity Checklist](#44-local-link-and-cross-device-parity-checklist)  
   4.5 [Takeover, Ownership, Recovery, Readiness Checklist](#45-takeover-ownership-recovery-readiness-checklist)  
   4.6 [Canonical Truth and Evidence Quality Checklist](#46-canonical-truth-and-evidence-quality-checklist)  
   4.7 [Diagnostics and Audit Surface Checklist](#47-diagnostics-and-audit-surface-checklist)  
   4.8 [True Integration Checklist](#48-true-integration-checklist)  
   4.9 [Rejection Criteria — What Must Be Rejected](#49-rejection-criteria--what-must-be-rejected)  
5. [Appendix: Canonical Module Cross-Reference](#5-appendix-canonical-module-cross-reference)  

---

## 1. System Model That Governs This Review

### 1.1 Authoritative System Identity

This is a **center-distributed intelligent agent system** (中心分布式智能体系统).  
It is NOT a single-center/single-client model.  
It is NOT a binary master/slave model.  
It is NOT a pure peer-to-peer mesh.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              GALAXY CENTER-DISTRIBUTED NETWORK SYSTEM                        │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  V2 — Canonical Authority Center (ufo-galaxy-realization-v2)         │   │
│  │  • Canonical truth convergence, task routing, session governance      │   │
│  │  • Ownership adjudication, readiness gate, release governance         │   │
│  │  • Audit authority, proof quality assessment, evidence canonicalization│   │
│  │  • Mesh coordination anchor, cross-device truth arbitration           │   │
│  └────────────┬────────────────────────────────────────┬─────────────┘   │
│               │ AIP v3.0 WebSocket (local-link AND WAN) │                  │
│    ┌──────────▼──────────┐               ┌─────────────▼──────────┐       │
│    │  Android Device(s)   │               │  Other Capable Devices  │       │
│    │  (ufo-galaxy-android) │               │  (PC clients, tablets, │       │
│    │  • Full local-link   │               │   IoT, desktop agents)  │       │
│    │  • Cross-device path │               │  • Full local-link      │       │
│    │  • Takeover-capable  │               │  • Cross-device path    │       │
│    │  • Mesh participant  │               │  • Takeover-capable     │       │
│    │  • Ownership capable │               │  • Mesh participant     │       │
│    │  • Recovery capable  │               │  • Ownership capable    │       │
│    └──────────────────────┘               └─────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Core Architectural Invariants

Every problem, plan, and review instruction in this document is governed by the following
invariants. Any implementation or review that violates them must be rejected:

| ID | Invariant |
|----|-----------|
| **INV-01** | V2 is the canonical truth authority. No Android or other-device assertion may override V2 truth without going through V2 adjudication. |
| **INV-02** | All devices — V2, Android, and any other class — have both local-link paths and cross-device interaction paths. Neither path may be assumed absent. |
| **INV-03** | All devices — V2, Android, and any other class — possess the ability to participate in the full takeover, ownership, mesh, and recovery capability set. Role assignment is runtime, not architectural lock. |
| **INV-04** | Ownership, canonical truth, readiness, recovery, diagnostics, mesh participation, and audit must be reasoned about as truly distributed, multi-runtime, multi-device, and cross-repository behaviors. |
| **INV-05** | Simulated proof (protocol stubs, local-only mocks, single-runtime assertions) does not count as proof. Real code capability with real runtime evidence is the acceptance bar. |
| **INV-06** | Every capability gap must be traceable to a specific missing code path in a specific repository (V2 or Android) and closed by real code, not by documentation assertion. |
| **INV-07** | Cross-repository validation means actual two-runtime behavior observed by an independent verifier — not V2-side mocks of Android behavior. |

### 1.3 Roles of V2, Android, and Other Devices

| Dimension | V2 | Android | Other Devices |
|-----------|-----|---------|---------------|
| Truth authority | Canonical adjudicator | Evidence emitter + local-verified emitter | Evidence emitter (same class as Android for ingest) |
| Local-link path | Self (localhost routing) | Yes — AccessibilityService, local inference | Yes — depends on device class |
| Cross-device path | Dispatch AND receive | Receive AND uplink | Same capability class as Android |
| Takeover role | Accept handoff, re-delegate, return ownership | Initiate takeover, execute, return | Same capability class as Android |
| Mesh participation | Coordinator anchor | Full participant | Full participant |
| Recovery | Canonical recovery authority | Local recovery emitter | Same capability class as Android |
| Audit surface | Authoritative audit store | Evidence contributor | Evidence contributor |
| Readiness gate | Canonical gate keeper | Readiness signal emitter | Readiness signal emitter |

---

## 2. Complete Structured Issue Inventory

> Status legend:  
> 🔴 **OPEN** — No real code backing. Must be resolved.  
> 🟡 **PARTIAL** — Partial implementation exists; real closure missing.  
> 🟠 **SIMULATED** — Protocol/stub exists; real runtime path does not.  
> ✅ **CLOSED** — Real code + real test + runtime evidence confirm closure.  

---

### 2.1 Truth Adjudication

#### TRUTH-001 — Multi-source truth conflict resolution is not canonicalized for all device classes
**Status**: 🟡 PARTIAL  
**Description**: `core/multi_device_truth_convergence.py` and `core/truth_integration_layer.py` provide V2-side
truth convergence for registered Android devices. However, the adjudication logic does not generalize to
arbitrary device classes. When a third device class (tablet, desktop agent, IoT node) emits contradicting
truth for the same task, the adjudication path is undefined.  
**Impact**: Canonical truth can diverge silently when more than two device classes participate simultaneously.  
**Required closure**: Extend `TruthIntegrationLayer` to accept an open device class registry;
add adjudication tests with ≥3 simultaneous contradicting sources.

#### TRUTH-002 — Truth freshness decay is not enforced at ingest
**Status**: 🔴 OPEN  
**Description**: There is no TTL or staleness policy on evidence ingested from Android or other devices.
An Android that replays a stale result after reconnect injects stale data into the canonical state with
no freshness check.  
**Impact**: V2 canonical state may reflect observations from minutes or hours ago as if they were current.  
**Required closure**: Implement ingress freshness gate; stale evidence must be classified as
`proof_input_class='stale'` and rejected from canonical truth update.

#### TRUTH-003 — Conflicting truth from two simultaneous Android sessions for the same task
**Status**: 🔴 OPEN  
**Description**: If two Android sessions emit truth signals for the same `task_id` concurrently (e.g., after
a reconnect during active execution), V2 has no defined policy for selecting the authoritative result.  
**Impact**: Non-deterministic canonical state under concurrent reconnect + result uplink scenario.  
**Required closure**: Define and implement conflict arbitration policy in `TruthIntegrationLayer`; expose
conflict resolution decision in audit trail.

#### TRUTH-004 — Inferred truth is not distinguished from confirmed truth in canonical state
**Status**: 🟡 PARTIAL  
**Description**: `decision_causality` fields include `canonical_truth_*` and `cross_repo_truth_*`
provenance markers (PR-14), but the confirmed vs. inferred distinction is not enforced at the storage
boundary. Callers reading canonical state cannot reliably determine if a truth value was directly observed
or inferred from incomplete evidence.  
**Required closure**: Add `truth_confirmation_mode` enum (`confirmed`, `inferred`, `absent`) to all
canonical device state objects and enforce it at write time.

#### TRUTH-005 — Cross-device truth is not validated against local-link truth for the same device
**Status**: 🔴 OPEN  
**Description**: When a device that has both a local-link session and a cross-device session emits
truth from both paths for the same task, V2 does not reconcile the two observations. The local-link
truth may contradict cross-device truth without detection.  
**Required closure**: Implement per-device dual-path truth reconciliation: if `local_link_truth ≠ cross_device_truth`
for the same task/device/session, raise a conflict and require explicit resolution.

---

### 2.2 Lifecycle Coordination

#### LIFE-001 — Task lifecycle events are not synchronized across all participating device runtimes
**Status**: 🟡 PARTIAL  
**Description**: V2 tracks task lifecycle through `TaskGraphRuntime` and `AttachedSessionRegistry`.
Android emits lifecycle signals via AIP v3.0. However, there is no synchronization mechanism to
ensure that all devices that have participated in a task see consistent lifecycle transitions.
A device that was briefly offline during a `task_complete` event has no way to reconcile its local
state with the canonical outcome.  
**Required closure**: Implement lifecycle event log with per-device delivery receipt; offline devices
must receive missed transitions upon reconnect.

#### LIFE-002 — Session lifecycle does not have a canonical close confirmation from all participants
**Status**: 🔴 OPEN  
**Description**: `AttachedSessionRegistry` tracks sessions from V2's perspective. There is no confirmation
path that requires participating devices to acknowledge session closure before V2 marks the session closed.
Devices may remain in an open-session state while V2 considers the session closed.  
**Required closure**: Define multi-party session close protocol; V2 must collect acks or apply a
timeout-based forced-close policy with audit record.

#### LIFE-003 — Reconnect during active task does not resume lifecycle state correctly
**Status**: 🟠 SIMULATED  
**Description**: `core/v2_android_recovery_continuity_hardening.py` (PR-7A) classifies reconnect scenarios
but the actual lifecycle state resume path for mid-task reconnect is not implemented as a real execution
path — it relies on Android re-sending the full evidence set rather than incrementally merging with
V2's checkpoint.  
**Required closure**: Implement real checkpoint-resume in `TaskGraphRuntime`; Android must be able to
receive a V2-side checkpoint and continue from it without replaying stale evidence.

#### LIFE-004 — Parallel task lifecycle on multiple devices is not tracked as a unified lifecycle
**Status**: 🔴 OPEN  
**Description**: When the same logical task is executed in parallel across multiple devices (e.g.,
multi-device formation execution), each device's subtask lifecycle is tracked independently with no
parent lifecycle container.  
**Required closure**: Introduce `DistributedTaskLifecycle` that wraps per-device subtask lifecycles;
all devices' subtask completions must be aggregated before the parent task is marked complete.

---

### 2.3 Tracking Convergence

#### TRACK-001 — Device tracking state is not convergent under concurrent mutation
**Status**: 🟡 PARTIAL  
**Description**: `test_pr13_concurrent_mutation_conflict_contract.py` verifies conflict detection, but
the actual convergence mechanism (CRDT, last-writer-wins with vector clock, or lease-based locking)
is not implemented. Conflict detection without a defined resolution strategy leaves the system in an
open inconsistency.  
**Required closure**: Implement a defined convergence strategy for device tracking state; the strategy
must be documented and tested under concurrent mutation.

#### TRACK-002 — Android tracking state is not observable from V2 diagnostics surface
**Status**: 🟡 PARTIAL  
**Description**: V2's `build_unified_governance_state()` exposes Android evidence integration fields but
does not expose Android-side tracking state (local task queue depth, pending retries, in-flight operations).
V2 cannot distinguish "Android is idle" from "Android is tracking but has not uplinked yet."  
**Required closure**: Android must emit tracking state as a periodic signal; V2 must integrate it into
`unified_governance_state`.

#### TRACK-003 — Tracking convergence across three or more simultaneous devices is untested
**Status**: 🔴 OPEN  
**Description**: All tracking convergence tests (PR-13) assume at most two participating devices.
No test exercises tracking state convergence under three or more simultaneous Android/other-device
participants.  
**Required closure**: Add convergence tests with ≥3 simultaneous participants; verify that V2's
tracking state remains consistent across all participant views.

---

### 2.4 Ownership Convergence and Resumed Ownership Transfer

#### OWN-001 — Ownership transfer is not tracked as a distributed operation with receipts
**Status**: 🟡 PARTIAL  
**Description**: `core/ownership_transfer_proof_quality.py` (PR-16) classifies proof quality for
ownership transfer events. However, the transfer itself is not tracked as a distributed operation:
there is no receipt from the receiving device confirming that it has accepted ownership, and no
rollback path if the receipt is not received.  
**Required closure**: Implement two-phase ownership transfer: V2 proposes transfer, receiving device
must ack (or timeout triggers rollback); V2 records receipt in audit trail.

#### OWN-002 — Resumed ownership transfer after interruption has no defined re-entry point
**Status**: 🔴 OPEN  
**Description**: If V2 proposes an ownership transfer and the target device goes offline before
acknowledging, the transfer is abandoned. There is no re-entry protocol for when the device comes
back online.  
**Required closure**: Implement ownership transfer resume: upon reconnect, V2 checks for pending
transfers and re-proposes; device must handle idempotent re-proposal.

#### OWN-003 — Ownership convergence is defined for V2→Android but not for Android→other-device
**Status**: 🔴 OPEN  
**Description**: The current ownership model assumes V2 as the transfer initiator and Android as the
receiver. The system model requires that any device can transfer ownership to any other device (through
V2 as the canonical coordinator). This path is not implemented.  
**Required closure**: Generalize ownership transfer to allow any device-class pair, with V2 as the
coordinating authority that validates and records all transfers.

#### OWN-004 — Ownership state is not persisted across V2 restarts
**Status**: 🔴 OPEN  
**Description**: Ownership state is held in-memory in V2. If V2 restarts during an active ownership
transfer or while ownership is delegated to an Android device, the ownership map is lost.  
**Required closure**: Persist ownership state to durable storage; upon V2 restart, recover ownership
map from storage and emit recovery events to all affected devices.

---

### 2.5 Takeover Completion and Ownership Return

#### TAKE-001 — Takeover completion is not confirmed with a canonical receipt
**Status**: 🟡 PARTIAL  
**Description**: `core/takeover_tracking.py` tracks takeover state and adjudicates ownership
convergence (PR-14A). However, takeover completion is declared by V2 unilaterally based on evidence
received from Android. There is no explicit completion confirmation sent back to Android, and Android
may not know that V2 has accepted the takeover as complete.  
**Required closure**: Implement takeover completion ack from V2 to taking-over device; device must
handle ack to transition out of takeover-active state.

#### TAKE-002 — Ownership return after takeover completion is not implemented as a real code path
**Status**: 🔴 OPEN  
**Description**: After a takeover completes, the expectation is that ownership returns to the
original holder (or to V2 as coordinator). There is no code path for this return: neither V2-side
return initiation nor Android-side return acceptance is implemented.  
**Required closure**: Implement ownership return protocol: V2 initiates return after receiving
takeover-complete signal; original owner (or V2) accepts ownership back; audit trail records
full takeover-complete-return cycle.

#### TAKE-003 — Partial takeover (takeover begins but not all subtasks transfer) is not handled
**Status**: 🔴 OPEN  
**Description**: If a multi-subtask task is undergoing takeover and only some subtasks transfer
successfully, the system has no defined state for "partial takeover." V2 may declare takeover
complete while some subtasks remain with the original owner.  
**Required closure**: Define partial takeover state; V2 must track per-subtask takeover status and
only declare full takeover-complete when all subtasks have confirmed transfer.

#### TAKE-004 — Competing takeover requests from multiple devices are not adjudicated
**Status**: 🔴 OPEN  
**Description**: There is no defined policy for what happens when two devices simultaneously
request to take over the same task. The first request may be accepted while the second is silently
dropped, with no notification to the second requester.  
**Required closure**: Implement competing takeover arbitration; rejected requests must receive an
explicit refusal with reason; the winning device must be notified of concurrent requests.

---

### 2.6 Proof Quality — Stale, Conflicting, Unresolved State

#### PROOF-001 — Stale proof detection does not cover all proof classes
**Status**: 🟡 PARTIAL  
**Description**: `OwnershipTransferProofClass` (PR-16) includes `degraded_stale`. However, stale
detection for capability truth, lifecycle truth, and audit authority proof classes is not uniformly
implemented. Only ownership transfer proof has comprehensive stale detection.  
**Required closure**: Extend stale detection to all proof classes: capability, lifecycle, audit,
recovery, mesh participation, and readiness. Stale evidence in any class must trigger a classified
degradation, not silent fallthrough.

#### PROOF-002 — Conflicting proof from multiple sources has no defined winner selection rule
**Status**: 🔴 OPEN  
**Description**: When two devices emit contradicting proof for the same fact (e.g., Android reports
task as "complete" while another device reports it as "in-progress"), V2 has no defined rule for
selecting the winner. The current implementation favors the most-recently-received proof, which is
a timing-dependent and non-deterministic policy.  
**Required closure**: Define explicit conflict resolution policy (e.g., prefer device with lower
latency, prefer device closer to the task execution, prefer confirmed over inferred); implement and
test the policy.

#### PROOF-003 — Unresolved proof state is not surfaced to the operator
**Status**: 🟡 PARTIAL  
**Description**: `CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY` in `core/unified_execution_governance.py`
enumerates 8 proof-input classes including `unknown` and `conflicting`. However, when proof
enters an `unknown` or `conflicting` state, the system does not surface an operator-visible alert
or block further execution that depends on the unresolved proof.  
**Required closure**: When any proof class enters `unknown` or `conflicting` state, block dependent
execution and emit an operator-visible diagnostic with the specific conflicting sources identified.

#### PROOF-004 — Proof quality degradation history is not preserved
**Status**: 🔴 OPEN  
**Description**: Proof quality assessments (PR-16) are point-in-time. There is no history of proof
quality changes for a given device/task pair. It is impossible to determine whether a current
`confirmed_strong` proof replaced a previous `degraded_stale` proof or was always strong.  
**Required closure**: Implement proof quality history log with timestamps and reasons for each transition.

---

### 2.7 Canonical Diagnosis Reconciliation

#### DIAG-001 — Diagnosis from Android and from V2 are not reconciled into a single canonical diagnosis
**Status**: 🟡 PARTIAL  
**Description**: V2's `build_unified_governance_state()` emits `android_originated_canonical_diagnosis`
fields (PR-17) alongside V2's own diagnostic assessment. These two assessments are not reconciled:
the combined canonical diagnosis is the union of both, but contradictions between them are not
flagged or resolved.  
**Required closure**: Implement canonical diagnosis reconciliation: when V2-generated diagnosis and
Android-originated diagnosis disagree, the reconciler must flag the disagreement, apply a resolution
policy, and record the reconciliation decision in the audit trail.

#### DIAG-002 — Other-device diagnostics are not ingested into canonical diagnosis
**Status**: 🔴 OPEN  
**Description**: The canonical diagnosis system handles V2-side and Android-side diagnostics. Other
device classes (desktop agents, IoT, tablets) have no ingest path into canonical diagnosis.  
**Required closure**: Generalize the diagnostic ingest path to accept device-class-agnostic diagnostic
envelopes; route all device-class diagnostics through the same reconciliation pipeline.

#### DIAG-003 — Diagnostic causality chain is not preserved across device boundaries
**Status**: 🔴 OPEN  
**Description**: A diagnostic event on Android (e.g., "accessibility service failed") may cause a
downstream diagnostic event on V2 (e.g., "task execution blocked"). There is no causal link between
these two events in the diagnostic record. A reviewer cannot determine that the V2 diagnostic was
caused by the Android diagnostic.  
**Required closure**: Implement cross-device diagnostic causality chain using trace IDs; each
diagnostic event must carry the `parent_trace_id` of the causing event on any device.

#### DIAG-004 — Diagnosis produced during recovery and reconnect is not specifically classified
**Status**: 🟡 PARTIAL  
**Description**: `android_evidence_recovery_truth_*` fields exist (PR-8 integration) but the
diagnostic classification during recovery phases does not distinguish "diagnosis produced during
normal operation" from "diagnosis produced during a recovery sequence." This distinction matters
because recovery-phase diagnostics may be partially inconsistent by design.  
**Required closure**: Add `diagnosis_phase` enum to all diagnostic records (`normal`, `recovery`,
`reconnect`, `replay`, `degraded_participation`).

---

### 2.8 Android-Originated and Other-Device-Originated Diagnostics

#### ADIAG-001 — Android-originated runtime diagnostics are not validated against V2 runtime observations
**Status**: 🟡 PARTIAL  
**Description**: `android_originated_canonical_diagnosis` (PR-17) includes runtime/capability/recovery/
takeover/mesh diagnostic fields emitted by Android. V2 does not validate these against its own
observations of Android's runtime behavior. Android could emit incorrect self-diagnostics without
detection.  
**Required closure**: V2 must cross-validate Android self-diagnostics against independently observable
signals (heartbeat frequency, task uplink frequency, capability advertisement matches).

#### ADIAG-002 — Android capability diagnostics do not include local-link vs. cross-device breakdown
**Status**: 🔴 OPEN  
**Description**: Android capability diagnostics report aggregate capability status without distinguishing
which capabilities are available via local-link vs. which require cross-device coordination. A reviewer
cannot determine whether a reported capability degradation is a local-link issue or a cross-device issue.  
**Required closure**: Android must include `path_type` (`local_link` | `cross_device` | `both`) in
every capability diagnostic event.

#### ADIAG-003 — Other-device diagnostic formats are not standardized
**Status**: 🔴 OPEN  
**Description**: Only Android has a defined diagnostic message format understood by V2's ingest pipeline.
Other device classes must emit diagnostics, but the expected format is not defined.  
**Required closure**: Define a device-class-agnostic diagnostic envelope format; extend V2's ingest
pipeline to accept it from any registered device class.

---

### 2.9 Audit Provenance, Trust, Freshness, Inferred vs. Confirmed

#### AUDIT-001 — Audit records do not carry trust level of the contributing source
**Status**: 🟡 PARTIAL  
**Description**: `get_governance_audit_summary()` (PR-14) includes `cross_repo_truth_*` provenance
fields. However, audit records do not carry a trust level (`trusted_device`, `provisional_device`,
`unregistered_device`) for the contributing source.  
**Required closure**: Add `source_trust_level` to all audit records; ingest pipeline must classify
contributing device's trust level at the time of the contribution.

#### AUDIT-002 — Freshness timestamps on audit records are not validated against wall-clock drift
**Status**: 🔴 OPEN  
**Description**: Audit records carry timestamps from contributing devices. These timestamps are not
validated against V2's wall clock. A device with a drifted clock can inject audit records with
arbitrary timestamps, corrupting the audit timeline.  
**Required closure**: Implement clock skew detection at audit ingest; reject or quarantine records
with excessive clock skew (configurable threshold); record skew detection events in the audit trail.

#### AUDIT-003 — Inferred audit entries are not distinguished from confirmed audit entries
**Status**: 🟡 PARTIAL  
**Description**: `canonical_truth_*` fields distinguish confirmed from inferred at the truth layer.
The audit layer does not propagate this distinction: audit entries generated from inferred truth are
indistinguishable from entries generated from confirmed truth.  
**Required closure**: Add `entry_basis` (`confirmed` | `inferred` | `reconstructed` | `assumed`)
to all audit entries; enforcement must prevent `confirmed`-basis entries from being created from
inferred truth.

#### AUDIT-004 — Audit trail does not capture device reconnect and state-recovery events
**Status**: 🔴 OPEN  
**Description**: When a device reconnects after a partition and V2 processes its replay sequence,
the audit trail does not record a reconnect event or a state-recovery sequence event. An auditor
reviewing the trail cannot determine when a device was offline or what state was recovered.  
**Required closure**: Emit explicit audit events for: device-disconnect, device-reconnect, replay-
start, replay-complete, recovery-accepted, recovery-rejected.

#### AUDIT-005 — Audit provenance chain is broken when V2 restarts mid-audit
**Status**: 🔴 OPEN  
**Description**: If V2 restarts while an audit sequence is in progress, the audit trail resumes
from the new V2 process context with no indication of the restart. An auditor cannot determine
the restart boundary.  
**Required closure**: Emit a V2-restart audit event at startup; include the recovery point from
which V2 rebuilt its state; link the new audit session to the prior one.

---

### 2.10 Readiness and Closure Semantics

#### READY-001 — Readiness gate does not require confirmation from all participating devices
**Status**: 🟡 PARTIAL  
**Description**: `core/v2_readiness_governance_evidence_surface.py` and related modules establish
V2's readiness gate. The gate evaluates V2's internal readiness and the registered Android device's
last-known readiness signal. However:  
1. The gate does not require a fresh readiness confirmation from Android — it accepts stale signals.  
2. Other device classes have no readiness ingest path.  
3. The gate does not define a quorum requirement for multi-device readiness.  
**Required closure**: Implement freshness requirement for readiness signals from all registered
participants; define quorum semantics for multi-device readiness.

#### READY-002 — Closure semantics are not defined for tasks that terminate abnormally on a device
**Status**: 🔴 OPEN  
**Description**: If a device crashes while executing a task subtask, the task remains open from
V2's perspective until a timeout fires. There are no closure semantics for abnormal termination:
no partial-result capture, no cleanup notification to other participating devices, no operator alert.  
**Required closure**: Define abnormal closure semantics: upon device crash detection (heartbeat
timeout), V2 must: (a) capture partial results if any, (b) notify all other participants, (c) emit
operator diagnostic, (d) attempt recovery or mark task as failed.

#### READY-003 — Readiness state is not versioned — a device cannot claim it is in the same state as before
**Status**: 🔴 OPEN  
**Description**: Readiness signals carry no version or epoch identifier. A device that restarts and
re-emits a readiness signal is indistinguishable from a device that has been ready continuously.
V2 cannot determine if a readiness signal represents fresh readiness or is a carryover of a
pre-restart state.  
**Required closure**: Add `readiness_epoch` (monotonic counter, incremented at each device restart)
to all readiness signals; V2 must detect epoch changes and re-validate readiness upon epoch change.

---

### 2.11 Distributed-Center Coordination Semantics

#### COORD-001 — V2 does not have a coordination protocol for split-brain scenarios
**Status**: 🔴 OPEN  
**Description**: If V2 loses network connectivity to all devices simultaneously (network partition),
devices continue operating locally. When connectivity is restored, V2 and devices may have diverged
in their view of task state, ownership, and session state. There is no defined protocol for
reconciling these diverged views.  
**Required closure**: Define split-brain reconciliation protocol: V2 declares a reconciliation
epoch upon reconnect; all devices must submit their local state; V2 adjudicates the canonical
outcome and notifies all devices.

#### COORD-002 — Distributed-center coordination does not have a defined leader-election fallback
**Status**: 🔴 OPEN  
**Description**: If V2 itself becomes unavailable (process crash, host failure), the distributed
devices have no defined behavior. They cannot elect a temporary coordinator because no protocol
exists for this scenario. The system's center-distributed model assumes V2 continuous availability.  
**Required closure**: Define V2-unavailability response for each device class: (a) continue local
execution within defined safe limits, (b) preserve local state for reconnect, (c) do not attempt
to elect an alternative coordinator (which would violate INV-01). Document the availability SLA.

#### COORD-003 — Coordination heartbeat is not bidirectional
**Status**: 🟡 PARTIAL  
**Description**: V2 monitors Android heartbeat to detect liveness. Android does not monitor V2
heartbeat. If V2 hangs (process alive but unresponsive), Android continues sending messages into
a deaf server.  
**Required closure**: Implement V2→Android heartbeat; Android must detect V2 unresponsiveness and
enter a defined "center unavailable" operational mode.

#### COORD-004 — Cross-device coordination state is not observable from a unified view
**Status**: 🟡 PARTIAL  
**Description**: `build_unified_governance_state()` provides V2's view of cross-device coordination.
There is no reciprocal "distributed coordination view" that shows the state from all participants'
perspectives simultaneously. An operator cannot tell if a coordination disagreement exists between
any two participants.  
**Required closure**: Implement distributed coordination view: V2 aggregates self-reported
coordination state from all registered participants and exposes a unified contradiction map.

---

### 2.12 Local-Link vs. Cross-Device Path Consistency

#### PATH-001 — Local-link path and cross-device path for the same capability are not validated to produce consistent results
**Status**: 🔴 OPEN  
**Description**: A device that has both local-link and cross-device paths to a capability (e.g.,
Android accessing a local model endpoint AND a V2-routed model endpoint) has no guarantee that both
paths produce the same result. The system does not validate cross-path consistency.  
**Required closure**: For capabilities accessible via both paths, implement consistency validation
at least at registration time; document which capabilities are expected to produce different
results per path (and why).

#### PATH-002 — Path failover from cross-device to local-link (and vice versa) is not implemented
**Status**: 🔴 OPEN  
**Description**: If the cross-device path becomes unavailable (V2 unreachable), the expectation
implied by INV-03 is that devices can fall back to local-link paths. However, there is no
failover logic: devices that lose the cross-device path either stop or retry indefinitely.  
**Required closure**: Implement path failover with defined semantics: when cross-device path is
unavailable, device switches to local-link mode with a flag indicating "operating in local-link
mode"; V2 must detect this mode change upon reconnect.

#### PATH-003 — Local-link path capability advertisement is not distinguished from cross-device capability advertisement
**Status**: 🔴 OPEN  
**Description**: When Android registers its capabilities with V2, the registration does not distinguish
which capabilities are available locally (always available regardless of connectivity) vs. which
require a cross-device connection.  
**Required closure**: Add `path_availability` field to all capability advertisements:
`{local_link: true/false, cross_device: true/false}`.

#### PATH-004 — Android's local-link path to V2 (same-network localhost routing) is not tested end-to-end
**Status**: 🟠 SIMULATED  
**Description**: Documentation references local-link path (same-network WebSocket connection).
All E2E tests use mocked connections, not real local-network routing. The local-link path is not
tested under real network conditions (latency, MTU, packet loss).  
**Required closure**: Add local-link E2E tests using real loopback or LAN connections; validate
that protocol behavior is identical on local-link vs. WAN paths.

---

### 2.13 Mesh/Network Participation and Degraded Partial Participation

#### MESH-001 — Mesh participation quorum is not defined
**Status**: 🔴 OPEN  
**Description**: The system model requires devices to participate in a mesh. There is no defined
quorum for mesh operation: how many participants are required for the mesh to be considered
operational? What happens if quorum is not met?  
**Required closure**: Define mesh quorum (minimum participant count); implement quorum-loss detection
and operational degradation response.

#### MESH-002 — Partial mesh participation (device participates in some mesh functions but not others) is not classified
**Status**: 🔴 OPEN  
**Description**: A device that has joined the mesh but can only participate in some functions (e.g.,
can receive tasks but cannot emit results due to uplink failure) is currently classified as either
fully participatory or fully absent. There is no partial participation state.  
**Required closure**: Define partial participation states for mesh members; expose partial
participation in the unified governance view; route tasks away from partially participating devices
when their limitation is relevant to the task.

#### MESH-003 — Mesh membership transitions are not audited
**Status**: 🔴 OPEN  
**Description**: Devices joining and leaving the mesh are recorded in the device registry but
not audited as mesh-membership events with the full context (reason for join/leave, last known
state, pending tasks at time of departure).  
**Required closure**: Emit audited mesh membership events with full context for all join/leave
transitions.

#### MESH-004 — Mesh recovery after a simultaneous multi-device departure is not defined
**Status**: 🔴 OPEN  
**Description**: If multiple devices leave the mesh simultaneously (e.g., network outage), the
mesh may not have a recovery path. V2 may be unable to maintain task continuity because no devices
are available.  
**Required closure**: Define multi-device departure recovery protocol: V2 queues tasks, emits
operator alert, and upon first device reconnect, resumes execution in priority order.

---

### 2.14 Recovery Semantics After Interruption, Partition, Reconnect, Restart, or Stale Replay

#### REC-001 — Recovery after V2 restart does not restore in-flight task state
**Status**: 🔴 OPEN  
**Description**: V2 holds task state in-memory. A V2 restart loses all in-flight task state.
Android devices that were executing tasks have no recovery path: they may complete their subtasks
and attempt to uplink results to a V2 that has no record of the tasks.  
**Required closure**: Implement V2-side task state persistence; upon restart, V2 must recover
in-flight tasks and accept result uplinks from devices that continued executing during the restart.

#### REC-002 — Retry semantics after failed evidence delivery are not defined for all evidence types
**Status**: 🟡 PARTIAL  
**Description**: `classify_evidence_ingress()` (PR-7A) classifies evidence ingress quality. Retry
semantics exist for some evidence types (capability truth) but not for all (audit authority evidence,
lifecycle truth evidence, mesh participation evidence).  
**Required closure**: Define retry semantics for all evidence types; implement idempotent evidence
delivery to prevent duplicate evidence injection on retry.

#### REC-003 — Stale replay is not distinguished from fresh evidence in V2's ingest pipeline
**Status**: 🟡 PARTIAL  
**Description**: `interpret_replay_sequence()` (PR-7A) classifies replay sequences. However, the
classification result is not used to gate whether replayed evidence updates canonical state or is
recorded separately as historical evidence.  
**Required closure**: Stale replay evidence must be recorded as historical evidence with a replay
flag; it must not update canonical task or ownership state unless specifically authorized by a
reconciliation step.

#### REC-004 — Recovery after partition leaves no evidence trail of what was missed
**Status**: 🔴 OPEN  
**Description**: When a device reconnects after a partition, V2 resumes communication but does not
record what events were missed during the partition window. An auditor cannot determine the partition
duration or the events that were missed.  
**Required closure**: Upon reconnect, V2 must emit a partition-gap audit record containing:
start time, end time, list of tasks active during partition, and list of ownership changes that
occurred without the reconnecting device's participation.

#### REC-005 — Recovery from partial observation (device saw some but not all events) is not handled
**Status**: 🔴 OPEN  
**Description**: A device that partially observed a sequence of events (e.g., observed task
assignment but not completion due to transient interruption) may operate on an inconsistent local
view. V2 does not detect or correct partial-observation states.  
**Required closure**: Implement partial-observation detection: V2 tracks per-device event delivery
receipts; upon reconnect, V2 identifies the partial-observation gap and sends missing events.

---

### 2.15 Multi-Device Simultaneous or Conflicting Takeover Conditions

#### MTAKE-001 — Two devices requesting simultaneous takeover of the same task
**Status**: 🔴 OPEN  
*(Details above in TAKE-004; referenced here as multi-device specific)*  
**Supplement**: The adjudication algorithm must be resistant to race conditions at the network level
(both requests arriving within milliseconds) and must produce a deterministic winner.

#### MTAKE-002 — A device attempting takeover of a task that is already in takeover from another device
**Status**: 🔴 OPEN  
**Description**: If Device A has successfully initiated takeover of Task T, and Device B subsequently
requests takeover of the same Task T (possibly due to a partition or stale view), V2 must reject
Device B's request with an explanation that Task T is already under takeover by Device A.  
**Required closure**: Implement takeover-in-progress guard; rejected devices receive the current
takeover holder's identity (or an anonymized status).

#### MTAKE-003 — Takeover state is not propagated to all mesh participants
**Status**: 🔴 OPEN  
**Description**: When a takeover is initiated, only V2 and the taking-over device know about it.
Other mesh participants that may have visibility into the task are not notified.  
**Required closure**: Upon takeover initiation, V2 must broadcast a takeover notification to all
registered participants that have registered interest in the affected task.

#### MTAKE-004 — Conflicting takeover requests are not recorded in audit
**Status**: 🔴 OPEN  
**Description**: When a takeover request is rejected due to a conflict, the rejection and the reason
are not recorded in the audit trail.  
**Required closure**: All takeover requests — accepted and rejected — must be recorded in the audit
trail with full context (requesting device, reason for acceptance or rejection, competing request
details if applicable).

---

### 2.16 Authoritative Source Selection and Convergence Under Disagreement

#### SRC-001 — Source selection policy is not defined for capability truth from multiple devices
**Status**: 🔴 OPEN  
**Description**: When multiple devices report different capability values for the same capability
class, V2 has no defined policy for which source is authoritative. This is distinct from conflict
detection (TRUTH-003): even when a conflict is detected, the resolution rule is undefined.  
**Required closure**: Define source selection policy for each proof class; publish the policy in
a canonicalized configuration that is readable at runtime.

#### SRC-002 — Convergence under persistent disagreement is not defined
**Status**: 🔴 OPEN  
**Description**: If two devices persistently disagree on a fact (e.g., one device always reports
a capability as available, another always reports it as unavailable), V2 has no defined behavior
beyond flagging the conflict. The system does not converge.  
**Required closure**: Define convergence timeout: if disagreement persists beyond a configured
duration, V2 applies a defined fallback (e.g., conservative assumption: treat capability as
unavailable) and emits an operator alert.

#### SRC-003 — Cross-repository disagreement between V2 and Android canonical records is not detected
**Status**: 🟡 PARTIAL  
**Description**: `docs/CODE_EVIDENCE_DUAL_REPO_SYSTEM_AUDIT.md` acknowledges cross-repo truth
consistency. `core/cross_repo_signal_closure_validation_matrix.py` provides validation tooling.
However, there is no runtime path that detects active disagreement between V2's canonical record
and Android's local record during live operation.  
**Required closure**: Implement runtime cross-repo disagreement detection: V2 and Android must
periodically exchange hash-signed state summaries; any mismatch triggers an active reconciliation
request.

---

### 2.17 True Two-Runtime / Multi-Runtime Cross-Repository Validation

#### XVAL-001 — All dual-runtime "validation" tests are V2-side mocks of Android behavior
**Status**: 🟠 SIMULATED  
**Description**: Every test in `tests/integration/test_pr13a_dual_runtime_cross_repo_regression.py`
and related files runs exclusively in V2's Python runtime, using `AndroidBridge` replay stubs.
No test exercises actual Android Kotlin runtime alongside V2 Python runtime.  
**Impact**: The "dual-runtime regression" label is misleading. Failures in Android's actual runtime
are invisible to this test suite.  
**Required closure**: Implement at minimum one true two-runtime integration test: real V2 process
+ real Android process (or a high-fidelity Android emulator with real Kotlin code execution).
The test must capture V2→Android→V2 round trips with real network I/O.

#### XVAL-002 — CI does not require cross-repository test passage before merge
**Status**: 🔴 OPEN  
**Description**: V2's CI runs V2-side tests only. Android's CI (if any) runs Android-side tests
only. There is no joint CI gate that requires both repositories' tests to pass before either
repository can merge.  
**Required closure**: Implement joint CI gate: a PR in either repository must trigger tests in
the other repository; both must pass before merge is permitted.

#### XVAL-003 — No end-to-end test exercises the full lifecycle from V2 dispatch to Android execution to V2 result ingestion
**Status**: 🟠 SIMULATED  
**Description**: Existing tests exercise isolated segments of the lifecycle. No test covers the
complete path: V2 receives user input → dispatches to Android → Android executes → Android
uplinks result → V2 ingests and closes the task lifecycle.  
**Required closure**: Implement full-lifecycle E2E test with real (or high-fidelity emulated)
Android runtime.

#### XVAL-004 — Multi-runtime recovery tests exist only as V2-side simulations
**Status**: 🟠 SIMULATED  
**Description**: Recovery path tests (PR-7A, PR-13A) use simulated reconnect and replay. No test
exercises real reconnect (actual TCP disconnection and reconnection) between real V2 and real Android
processes.  
**Required closure**: Implement real reconnect test: programmatically disconnect the V2→Android
WebSocket, verify both sides detect the disconnect, verify the reconnect and state recovery
proceeds correctly.

---

### 2.18 Elimination of Fake Proof — Stubs, Protocol-Only, Local-Only

#### FAKE-001 — Protocol conformance tests are accepted as proof of runtime behavior
**Status**: 🟠 SIMULATED  
**Description**: Multiple PR acceptance criteria cite "protocol test passes" as evidence that
a capability works end-to-end. Protocol conformance (correct message format, correct field names)
does not prove that the runtime behavior behind the protocol is correct.  
**Required closure**: Any capability claim must include a runtime behavior test, not just a
protocol conformance test. Protocol tests remain valuable as a precondition but are not sufficient.

#### FAKE-002 — Stub implementations in Android-bridge modules are counted as real capability
**Status**: 🟠 SIMULATED  
**Description**: Several `core/android_*` modules in V2 repository implement behavior that would
be performed by Android but is simulated by V2-side stubs (e.g., `AndroidBridge.replay_evidence()`).
These stubs are counted in acceptance criteria as demonstrating Android capability.  
**Required closure**: All stub-backed capability claims must be explicitly marked as `[STUB]`
in acceptance criteria and must not count toward real-capability acceptance.

#### FAKE-003 — Local-only assumptions in truth convergence tests
**Status**: 🟠 SIMULATED  
**Description**: Truth convergence tests run with all participating "devices" as in-process objects.
They do not simulate network latency, out-of-order delivery, or partial connectivity — all of
which are normal in a real distributed system.  
**Required closure**: Add network-realistic truth convergence tests that inject latency, out-of-order
delivery, and packet loss; verify that truth converges to the correct canonical state under these
conditions.

---

### 2.19 Additional Systemic Gaps

#### SYS-001 — No defined device class registry for non-Android, non-V2 devices
**Status**: 🔴 OPEN  
**Description**: The system model (INV-03) requires that other device classes participate in the
full capability set. There is no device class registry that defines what "other devices" are,
what capabilities they are expected to have, and how they register.  
**Required closure**: Define and implement a device class registry; all device classes must
self-describe their capability profile upon registration.

#### SYS-002 — Security: device authentication does not verify device class claims
**Status**: 🔴 OPEN  
**Description**: A device can register as any device class without cryptographic proof of its
identity or its claimed capabilities. A malicious device can impersonate a trusted device class.  
**Required closure**: Implement device class attestation using public-key cryptography or
token-based attestation; V2 must verify attestation before granting full participation rights.

#### SYS-003 — Configuration drift between V2 and Android is not detected
**Status**: 🔴 OPEN  
**Description**: V2 and Android have separate configuration systems. If their configurations
drift (e.g., V2 expects AIP v3.1 while Android still uses AIP v3.0), the incompatibility may
not be detected until runtime, causing protocol failures.  
**Required closure**: Implement configuration version negotiation at connection establishment;
incompatible configurations must be rejected with a clear error rather than silently degrading.

#### SYS-004 — No cross-device resource contention management
**Status**: 🔴 OPEN  
**Description**: Multiple devices may simultaneously request the same shared resource (e.g., a
model endpoint, a hardware interface). There is no resource contention management system to
prevent resource starvation or priority inversion.  
**Required closure**: Implement resource contention management for shared resources; define
priority order for concurrent requests.

#### SYS-005 — Observability surface is V2-centric; no Android-native observability export
**Status**: 🟡 PARTIAL  
**Description**: V2's observability surface (Prometheus metrics, logs, governance state) provides
V2's view of system health. There is no Android-native observability export that could be
consumed by the same monitoring system.  
**Required closure**: Implement Android observability export (metrics, health signals) in a
format that V2's monitoring stack can consume; ensure Android health is visible in the same
monitoring dashboard as V2 health.

---

## 3. Complete Integrated PR Plan

### 3.1 Problem-to-Responsibility Mapping

#### Group A: Truth Adjudication and Proof Quality (V2-primary)

| Problem | V2 Responsibility | Android Responsibility | Other Device Role |
|---------|------------------|----------------------|-------------------|
| TRUTH-001: Multi-source conflict | Extend `TruthIntegrationLayer` for open device classes | Emit structured truth envelopes | Same format as Android |
| TRUTH-002: Freshness decay | Implement ingress freshness gate | Emit `evidence_timestamp` + `evidence_ttl` | Same as Android |
| TRUTH-003: Concurrent session conflict | Implement conflict arbitration in `TruthIntegrationLayer` | Emit session ID with every truth signal | Same as Android |
| TRUTH-004: Confirmed vs. inferred | Add `truth_confirmation_mode` to state objects | Emit `confirmation_mode` field | Same as Android |
| TRUTH-005: Dual-path truth reconciliation | Implement per-device dual-path reconciler | Emit separate local-link and cross-device truth signals | Same as Android |
| PROOF-001: Stale detection coverage | Extend stale detection to all proof classes | Emit freshness metadata for all proof classes | Same as Android |
| PROOF-002: Conflict winner selection | Define and implement conflict resolution policy | N/A (consumer of policy) | N/A |
| PROOF-003: Unresolved proof surface | Block execution on unresolved proof; emit operator alert | N/A | N/A |
| PROOF-004: Proof quality history | Implement proof quality history log | N/A | N/A |
| SRC-001 to SRC-003: Source selection | Define and implement source selection policy | Exchange hash-signed state summaries | Same as Android |

#### Group B: Lifecycle Coordination (V2-primary with Android confirmation)

| Problem | V2 Responsibility | Android Responsibility | Other Device Role |
|---------|------------------|----------------------|-------------------|
| LIFE-001: Lifecycle sync | Implement lifecycle event log with delivery receipts | Confirm lifecycle event receipt | Same as Android |
| LIFE-002: Session close confirmation | Implement multi-party session close protocol | Send session close ack | Same as Android |
| LIFE-003: Reconnect lifecycle resume | Implement checkpoint-resume in `TaskGraphRuntime` | Accept V2 checkpoint; resume from it | Same as Android |
| LIFE-004: Parallel task lifecycle | Implement `DistributedTaskLifecycle` wrapper | Report subtask lifecycle per formation | Same as Android |

#### Group C: Ownership, Takeover, and Return (V2 coordination, device execution)

| Problem | V2 Responsibility | Android Responsibility | Other Device Role |
|---------|------------------|----------------------|-------------------|
| OWN-001: Two-phase transfer | Implement two-phase ownership transfer protocol | Send transfer ack | Same as Android |
| OWN-002: Resume after interruption | Implement re-proposal upon reconnect | Handle idempotent re-proposal | Same as Android |
| OWN-003: Android→other device transfer | Generalize transfer for all device class pairs | Initiate transfer request to V2 | Receive transfer via V2 |
| OWN-004: Ownership persistence | Persist ownership map to durable storage | N/A | N/A |
| TAKE-001: Takeover completion ack | Send takeover-complete ack to device | Consume ack; exit takeover-active state | Same as Android |
| TAKE-002: Ownership return | Implement return protocol | Accept return | Same as Android |
| TAKE-003: Partial takeover | Track per-subtask takeover status | Report per-subtask transfer status | Same as Android |
| TAKE-004, MTAKE-001–004: Competing takeover | Implement arbitration; broadcast notifications | Receive rejection or win notification | Same as Android |

#### Group D: Diagnostics, Audit, and Readiness (V2 store, device emit)

| Problem | V2 Responsibility | Android Responsibility | Other Device Role |
|---------|------------------|----------------------|-------------------|
| DIAG-001: V2/Android diagnosis reconciliation | Implement reconciliation pipeline | N/A | N/A |
| DIAG-002: Other-device diagnostics | Generalize ingest path | N/A | Emit standard diagnostic envelope |
| DIAG-003: Cross-device causality chain | Accept `parent_trace_id` in diagnostic records | Emit `parent_trace_id` | Same as Android |
| DIAG-004: Recovery-phase diagnosis | Add `diagnosis_phase` enum | Emit `diagnosis_phase` | Same as Android |
| ADIAG-001: Android self-diagnostic validation | Cross-validate against observable signals | Emit self-diagnostics | Same as Android |
| ADIAG-002: Local-link vs. cross-device breakdown | Accept `path_type` in capability diagnostics | Emit `path_type` per capability | Same as Android |
| ADIAG-003: Other-device diagnostic format | Define standard envelope; extend ingest | N/A | Implement standard envelope |
| AUDIT-001–005: Audit provenance | Implement trust level, clock skew detection, entry basis, reconnect events, restart events | Emit trust attestation + timestamps | Same as Android |
| READY-001–003: Readiness gate | Require fresh signals; define quorum; implement versioned readiness | Emit `readiness_epoch` | Same as Android |

#### Group E: Recovery, Mesh, and Network (distributed)

| Problem | V2 Responsibility | Android Responsibility | Other Device Role |
|---------|------------------|----------------------|-------------------|
| COORD-001–004: Coordination semantics | Split-brain protocol; V2-unavailability policy; bidirectional heartbeat | Enter "center unavailable" mode; send V2 heartbeat response | Same as Android |
| MESH-001–004: Mesh participation | Define quorum; classify partial participation; emit membership events; multi-departure recovery | Report partial participation state; emit membership events | Same as Android |
| REC-001–005: Recovery semantics | Persist task state; define retry semantics; gate stale replay; emit partition-gap records; send missing events | Accept V2 checkpoint; send missed events | Same as Android |
| PATH-001–004: Path consistency | Validate cross-path consistency; define failover semantics | Emit path availability per capability; implement failover | Same as Android |

#### Group F: Cross-Repository Validation and Anti-Fake-Proof (joint)

| Problem | V2 Responsibility | Android Responsibility | Other Device Role |
|---------|------------------|----------------------|-------------------|
| XVAL-001–004: True two-runtime validation | Implement joint CI gate; provide V2 test harness for real Android integration | Provide Android test harness; expose test control API | N/A at this stage |
| FAKE-001–003: Eliminate fake proof | Mark all stub-backed claims as `[STUB]`; add network-realistic tests | Implement real runtime test targets | N/A |

#### Group G: Systemic Gaps (V2-primary, joint)

| Problem | V2 Responsibility | Android Responsibility | Other Device Role |
|---------|------------------|----------------------|-------------------|
| SYS-001: Device class registry | Define and implement registry | Register with class descriptor | Same as Android |
| SYS-002: Device authentication | Implement attestation verification | Implement attestation emission | Same as Android |
| SYS-003: Configuration drift | Implement version negotiation | Negotiate at connect | Same as Android |
| SYS-004: Resource contention | Implement resource contention manager | Declare resource requirements | Same as Android |
| SYS-005: Android observability | Define export format; consume Android metrics | Implement metrics export | Same as Android |

---

### 3.2 Sequencing and Dependencies

```
Phase 1 — Foundation (must complete before any other phase)
  ├── SYS-001: Device class registry   [V2]
  ├── SYS-002: Device authentication   [V2 + Android]
  ├── SYS-003: Configuration negotiation [V2 + Android]
  └── PATH-003: Path availability in capability advertisement [V2 + Android]

Phase 2 — Truth and Proof (depends on Phase 1)
  ├── TRUTH-001 to TRUTH-005        [V2, with Android evidence format changes]
  ├── PROOF-001 to PROOF-004        [V2]
  └── SRC-001 to SRC-003            [V2 + Android]

Phase 3 — Lifecycle and Coordination (depends on Phase 1)
  ├── LIFE-001 to LIFE-004          [V2 + Android]
  ├── COORD-001 to COORD-004        [V2 + Android]
  └── COORD-003: Bidirectional heartbeat [V2 + Android] ← must be before Mesh

Phase 4 — Ownership and Takeover (depends on Phase 2 and 3)
  ├── OWN-001 to OWN-004            [V2 + Android]
  ├── TAKE-001 to TAKE-004          [V2 + Android]
  └── MTAKE-001 to MTAKE-004        [V2 + Android]

Phase 5 — Recovery and Mesh (depends on Phase 3 and 4)
  ├── REC-001 to REC-005            [V2 + Android]
  ├── MESH-001 to MESH-004          [V2 + Android]
  └── PATH-001, PATH-002, PATH-004  [V2 + Android]

Phase 6 — Diagnostics, Audit, Readiness (depends on Phase 2 through 5)
  ├── DIAG-001 to DIAG-004          [V2]
  ├── ADIAG-001 to ADIAG-003        [V2 + Android]
  ├── AUDIT-001 to AUDIT-005        [V2 + Android]
  └── READY-001 to READY-003        [V2 + Android]

Phase 7 — Cross-Runtime Validation (depends on Phase 1 through 6)
  ├── XVAL-001 to XVAL-004          [V2 + Android joint CI]
  ├── FAKE-001 to FAKE-003          [V2 + Android]
  └── SYS-004, SYS-005              [V2 + Android]
```

**Critical path**: Phase 1 → Phase 2/3 (parallel) → Phase 4 → Phase 5 → Phase 6 → Phase 7.  
No phase may be closed until all items in that phase have real code + real test backing.

---

### 3.3 What Counts as Real Proof vs. Insufficient Proof

#### Real Proof (ACCEPTED)

| Proof Type | Minimum Requirement |
|-----------|---------------------|
| Code capability | A callable function or class in V2 or Android codebase (not a stub) with real logic that performs the stated operation |
| Runtime behavior | A test or observation that exercises the real code path in a running process with real I/O |
| Two-runtime validation | A test that spawns or connects to both a real V2 process AND a real Android process (or high-fidelity Android emulator executing real Kotlin code) and validates the interaction |
| Audit record | A real audit entry in a real audit store (not just a log line) that can be retrieved and verified by an independent query |
| Recovery proof | A test that introduces a real interruption (process kill, TCP drop, timeout) and verifies the recovery path executes to completion |
| Convergence proof | A test with ≥2 concurrent conflicting inputs that demonstrates the resolution matches the defined policy |

#### Insufficient Proof (REJECTED)

| Proof Type | Why Insufficient |
|-----------|-----------------|
| Protocol conformance test only | Proves message format, not runtime behavior |
| V2-side mock of Android behavior | Does not test Android's actual Kotlin code |
| Single-runtime in-process "distributed" test | Does not expose real network I/O, latency, or disconnection behavior |
| Documentation assertion ("this will work because...") | Not evidence of capability |
| Stub function with `pass` or `raise NotImplementedError` | Not a capability |
| Test that only passes because it tests the stub, not the real path | Circular |
| Local-only test with no distributed component | Does not validate distributed semantics |

---

### 3.4 Regression and Validation Expectations

#### Mandatory Regression Gates (must pass on every PR in both repositories)

1. **V2 unit tests**: All existing `tests/test_pr*` files must continue to pass.
2. **V2 integration tests**: All existing `tests/integration/` files must continue to pass.
3. **V2 governance regression**: `test_pr14_governance_audit_authority.py`, `test_unified_governance_semantics.py`,
   `test_pr12_android_truth_final_audit.py` must all pass.
4. **Proof class coverage**: All 8 proof-input classes (`complete`, `stale`, `conflicting`, `malformed`,
   `unknown`, `downgraded`, `partial`, `missing`) must be exercised in every PR that touches proof classification.
5. **Sentinel registry**: All PR-series sentinels must remain accessible and return correct contract versions.
6. **Android regression** (upon Android CI implementation): All Android unit tests for changed modules must pass.
7. **Cross-repository gate** (upon joint CI implementation): Any PR in either repo must pass the joint CI gate.

#### New Validation Requirements (from this plan)

1. **Truth convergence with ≥3 sources**: Any PR touching truth adjudication must include a test with ≥3
   simultaneous sources.
2. **Stale evidence rejection**: Any PR touching evidence ingest must demonstrate stale evidence is rejected
   under a configurable TTL.
3. **Two-phase protocol tests**: Any PR touching ownership transfer must include a test for the two-phase
   protocol including abort-on-no-ack.
4. **Partial participation classification**: Any PR touching mesh participation must include a test for
   all defined partial participation states.
5. **Recovery interruption tests**: Any PR touching recovery must introduce a real (not simulated) interruption
   and verify the recovery path.

---

### 3.5 Path to Complete Fully Integrated Solution

The following milestones define the path from current state to complete integration:

**Milestone 1 — Honest capability baseline**: All stub-backed capability claims are marked `[STUB]`.
All acceptance criteria explicitly distinguish real from simulated proof. Duration: 1 sprint.

**Milestone 2 — Foundation layer**: Phase 1 items complete. Device class registry, authentication,
configuration negotiation, and path advertisement are real code in both repositories. Duration: 2 sprints.

**Milestone 3 — Truth and lifecycle hardening**: Phase 2 and 3 items complete. Truth adjudication,
proof quality, lifecycle coordination, and distributed-center coordination have real code and real tests.
Duration: 3 sprints.

**Milestone 4 — Ownership and takeover completeness**: Phase 4 items complete. Full two-phase ownership
transfer, takeover arbitration, and competing takeover resolution are implemented and tested. Duration: 2 sprints.

**Milestone 5 — Recovery and mesh completeness**: Phase 5 items complete. Task state persistence,
retry semantics, stale replay gating, mesh quorum, and multi-device departure recovery are implemented.
Duration: 3 sprints.

**Milestone 6 — Diagnostics, audit, and readiness hardening**: Phase 6 items complete. Canonical diagnosis
reconciliation, audit provenance, trust levels, and readiness versioning are implemented and tested.
Duration: 2 sprints.

**Milestone 7 — True two-runtime validation**: Phase 7 items complete. Joint CI gate, real two-runtime
integration tests, and network-realistic convergence tests are operational. Duration: 3 sprints.

**Total estimated path**: 16 sprints (assuming 2-week sprints, ~8 months).  
Items within the same phase can be parallelized across teams.

---

## 4. Joint Cross-Repository Review Prompt and Instruction Set

> **Purpose**: This section is a reusable, rigorous review prompt for every future implementation PR
> in `ufo-galaxy-realization-v2` and `ufo-galaxy-android`. Reviewers must apply this checklist to
> every PR, not just to PRs that explicitly touch distributed systems.

---

### 4.1 Mandatory Pre-Review Declarations

Before reviewing any PR, the reviewer must confirm the following:

- [ ] **Repository scope**: I know which repository (V2, Android, or both) this PR modifies.
- [ ] **System model**: I have read and understood Section 1 of this document (Invariants INV-01 through INV-07).
- [ ] **Proof standard**: I am applying the "Real Proof vs. Insufficient Proof" standard from Section 3.3.
- [ ] **Counterpart awareness**: I have checked whether this PR requires a corresponding change in the other repository, and if so, that the counterpart PR exists and is linked.

---

### 4.2 Code Path Verification Checklist

For every claimed capability in this PR:

- [ ] **Is the code path callable?** Identify the entry point (function, endpoint, handler) and confirm it is wired to a real caller — not just defined.
- [ ] **Is the code path tested?** Identify the test that exercises the real code path (not a mock of the path).
- [ ] **Does the test use real I/O?** Confirm the test uses real network, real file system, or real process communication — not in-process mocks.
- [ ] **Is the stub count zero or explicitly declared?** If any stub (`pass`, `raise NotImplementedError`, mock that returns hardcoded values) remains in the code path, it must be flagged as `[STUB]` and must NOT be counted toward capability acceptance.
- [ ] **Are all branches covered?** Confirm that error paths, degraded paths, and timeout paths are tested — not just the happy path.

---

### 4.3 Distributed-Center Semantics Checklist

- [ ] **V2 is the canonical authority**: Does this PR introduce any path where a device other than V2 makes a canonical decision without V2 adjudication? If yes, reject.
- [ ] **No single-node assumption**: Does this PR assume that only one device participates at a time? If yes, reject or require N≥3 device tests.
- [ ] **Center-distributed coordination**: Does this PR correctly model the fact that V2 coordinates but does not directly execute on devices? Verify that execution remains on the appropriate device.
- [ ] **Distributed state**: Does this PR modify state that is distributed across V2 and device runtimes? If yes, verify that the modification protocol is atomic from the system's perspective (two-phase or equivalent).
- [ ] **Quorum semantics**: If this PR involves a decision that requires multi-device agreement (readiness, ownership transfer, session close), is a quorum defined and enforced?

---

### 4.4 Local-Link and Cross-Device Parity Checklist

- [ ] **Both paths considered**: Does this PR's change apply equally to the local-link path and the cross-device path? If one path behaves differently, is the difference intentional and documented?
- [ ] **Path failover**: Does this PR introduce or modify any code that uses a specific path? Verify that path failover is handled (or that the PR explicitly defers failover to a linked issue).
- [ ] **Path advertisement**: If this PR adds a new capability, does it include a `path_availability` declaration specifying which paths the capability is available on?
- [ ] **Path-specific tests**: Does this PR include tests that exercise the capability on both the local-link path and the cross-device path (or explicitly document why one path is deferred)?

---

### 4.5 Takeover, Ownership, Recovery, and Readiness Checklist

- [ ] **Takeover completeness**: If this PR touches takeover, does it cover: initiation, progress tracking, completion ack, competing request arbitration, partial takeover state, and post-completion ownership return?
- [ ] **Ownership transfer completeness**: Is the transfer two-phase (propose + ack)? Is there an abort path for no-ack? Is the transfer recorded in the audit trail?
- [ ] **Recovery completeness**: If this PR touches recovery, does it cover: interruption detection, state preservation, reconnect handling, stale replay gating, and partition-gap recording?
- [ ] **Readiness freshness**: If this PR touches readiness, does it use a freshness-validated readiness signal with `readiness_epoch`? Stale readiness signals must not be accepted.
- [ ] **Closure under real conditions**: Are there tests that introduce real interruptions (process kill, TCP drop) rather than simulated ones? If not, why not? (Document if deferring to a linked issue.)

---

### 4.6 Canonical Truth and Evidence Quality Checklist

- [ ] **Proof class coverage**: Does this PR touch proof classification? If so, all 8 proof-input classes must be tested: `complete`, `stale`, `conflicting`, `malformed`, `unknown`, `downgraded`, `partial`, `missing`.
- [ ] **Confirmed vs. inferred distinction**: Does this PR write to canonical state? If so, does it correctly set `truth_confirmation_mode` based on the evidence type?
- [ ] **Freshness enforcement**: Does this PR accept evidence from devices? If so, is there a freshness TTL check? Stale evidence must be classified, not silently accepted.
- [ ] **Conflict detection and resolution**: Does this PR accept evidence from multiple sources? If so, is there a conflict detection step, a resolution policy, and a test for the conflicting case?
- [ ] **Source trust level**: Is the contributing source's trust level recorded with the evidence?

---

### 4.7 Diagnostics and Audit Surface Checklist

- [ ] **Diagnostic causality chain**: Does this PR emit diagnostic events? If so, do they carry `parent_trace_id` linking to the causing event (if any)?
- [ ] **Diagnosis phase annotation**: Are diagnostic events annotated with `diagnosis_phase` (`normal`, `recovery`, `reconnect`, `replay`, `degraded_participation`)?
- [ ] **Audit entry basis**: Are audit entries annotated with `entry_basis` (`confirmed` | `inferred` | `reconstructed` | `assumed`)?
- [ ] **Reconnect/restart audit events**: If this PR touches connection or startup lifecycle, does it emit the required reconnect/restart audit events?
- [ ] **Clock skew detection**: Does this PR accept timestamps from external devices? If so, is there a clock skew validation step?
- [ ] **Audit provenance completeness**: Can an auditor who reads only the audit trail reconstruct the full history of: who did what, from which device, with what evidence quality, at what time, in what phase?

---

### 4.8 True Integration Checklist

- [ ] **V2–Android integration**: Does this PR claim to implement a feature that involves both V2 and Android? Is there a corresponding Android PR? Does the combined change produce a real two-runtime integration test?
- [ ] **Other device class integration**: If this PR changes the device participation model, does it consider other device classes (not just Android)?
- [ ] **Joint CI gate**: Has the counterpart repository's CI been triggered by this PR (or is there a documented plan for when joint CI will be implemented)?
- [ ] **Contract version**: If this PR changes any cross-repo contract (message format, protocol version, sentinel value), has the contract version been incremented and has the counterpart repository been updated?
- [ ] **No isolated fix**: Is this PR's change complete in isolation, or does it leave a gap that requires a follow-up PR? If a gap remains, is it tracked in an issue with a link from this PR?

---

### 4.9 Rejection Criteria — What Must Be Rejected

A PR **MUST BE REJECTED** (not approved with comments) if it:

1. Claims a capability is "complete" while the only evidence is a stub implementation or a mock-based test.
2. Claims "dual-runtime validation" while all tests run in a single V2-side Python process.
3. Claims "distributed" behavior while all participating "devices" are in-process objects.
4. Modifies canonical truth adjudication without tests for all 8 proof classes.
5. Modifies ownership or takeover without implementing the two-phase protocol.
6. Modifies evidence ingest without a freshness TTL check.
7. Adds a new capability without specifying its `path_availability` (local-link vs. cross-device).
8. Claims "recovery" behavior without a test that introduces a real interruption.
9. Introduces a new code path that assumes a single device participant when the system model allows multiple.
10. Modifies the audit trail without maintaining provenance, trust level, and entry-basis fields.
11. Does not have a linked counterpart PR in the other repository when the change spans both repositories.
12. Uses documentation or comments to claim capability that is not backed by callable, tested code.

---

## 5. Appendix: Canonical Module Cross-Reference

| Concern | V2 Primary Module(s) | Android Primary Location |
|---------|---------------------|-------------------------|
| Canonical truth | `core/multi_device_truth_convergence.py`, `core/truth_integration_layer.py` | `GalaxyConnectionService.kt` (evidence emission) |
| Proof quality | `core/ownership_transfer_proof_quality.py`, `core/unified_execution_governance.py` | Capability advertisement builder |
| Evidence ingest | `core/android_evidence_integration_pipeline.py`, `core/android_participant_truth_ingress.py` | `GalaxyWebSocketClient.kt` (uplink) |
| Ownership tracking | `core/takeover_tracking.py` | `LoopController.kt` |
| Governance semantics | `core/unified_governance_semantics.py` | `DelegatedRuntimeAcceptanceEvaluator.kt` |
| Audit authority | `core/execution_governance_audit_authority.py` | Audit signal emitter |
| Recovery hardening | `core/v2_android_recovery_continuity_hardening.py` | Reconnect handler in `GalaxyWebSocketClient.kt` |
| Android diagnostics | `core/unified_governance_semantics.py` (ingestion side) | Runtime diagnostics emitter |
| Cross-repo contract | `core/android_v2_continuity_contract.py` | `GalaxyConnectionService.kt` |
| Session registry | `core/attached_session_registry.py` | Session ID tracker |
| Mesh coordination | `core/live_mesh_session_coordinator.py` | Mesh participant interface |
| Readiness governance | `core/v2_readiness_governance_evidence_surface.py` | Readiness signal emitter |
| Lifecycle governance | `core/android_delegated_runtime_lifecycle_coordinator.py` | `LoopController.kt`, `TaskExecutor` |
| Cross-device routing | `core/command_router.py`, `galaxy_gateway/routing/device_router.py` | (consumer only) |
| Device registry | `core/device_registry.py` | Registration protocol in `GalaxyWebSocketClient.kt` |
| Protocol layer | `galaxy_gateway/protocol/aip_v3.py` | `AgentMessageHandler.kt` |

---

*Document classification: Authoritative engineering review artifact.*  
*This document must be updated to reflect changes in system model, capability status, or review
criteria whenever a Phase milestone is completed.*  
*All future implementation PRs for this system must cite this document's issue IDs when claiming closure
of identified gaps.*
