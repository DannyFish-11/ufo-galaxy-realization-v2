# Center-Governed Distributed Intelligent Agent System — Complete System Review

**Repositories:**
- `DannyFish-11/ufo-galaxy-realization-v2` (V2) — center governance / orchestration / truth authority
- `DannyFish-11/ufo-galaxy-android` (Android) — distributed runtime node / local intelligence bearer

**This document supersedes the prior dual-repo completeness review (PR-866) by
establishing the correct system identity and providing a more complete capability picture.**

---

## Why This Review Was Necessary

The prior review artifact (PR-866) correctly measured structural completeness but
under-represented the system's actual architecture in two important ways:

1. **System identity was under-specified.**  The prior review described a binary
   "V2 control plane + Android execution end" model.  This is incomplete: Galaxy is
   a **center-governed distributed intelligent agent system (中心分布式智能体系统)**,
   where Android is not a passive executor but a full distributed runtime node.

2. **Android's local capabilities were under-represented.**  The prior review focused
   mainly on the delegated path (V2 → Android → result back to V2) while treating
   Android's local networking, local inference, local planning, local grounding, and
   GUI interaction capabilities as secondary footnotes rather than as independent
   capability axes.

This review corrects both issues while preserving honest gap reporting.

---

## Section 1: What This System Actually Is

### System Identity

> **Galaxy is a center-governed distributed intelligent agent system.**
>
> V2 (`ufo-galaxy-realization-v2`) is the **center governance, orchestration, truth
> convergence, and acceptance authority**.
>
> Android (`ufo-galaxy-android`) is a **distributed runtime node with local
> intelligence, local networking, local task execution, and cross-device
> participation capability**.

This is NOT:
- A simple "control panel + remote control" system
- A binary "master + slave" system
- A system where Android is a passive receiver of commands

This IS:
- A center-governed architecture where V2 holds canonical task routing, session
  truth, capability assimilation, and release governance
- A distributed execution architecture where Android acts as an autonomous runtime
  node with its own local capability surface, local acceptance evaluation, and local
  execution loop
- A system with multiple execution paths, not just one delegated path

### Code Anchors for System Identity

| Claim | Code Anchor |
|-------|-------------|
| V2 is center governance authority | `core/dual_repo_system_map.py` — `SystemPlane.CONTROL_PLANE` registry; `core/system_final_acceptance_verdict.py` — `SystemFinalAcceptanceEvaluator` |
| V2 holds truth convergence | `core/multi_device_truth_convergence.py`; `core/truth_integration_layer.py` |
| V2 holds release governance | `core/release_governance_taxonomy.py`; `core/distributed_release_gate_skeleton.py`; `core/v2_readiness_governance_evidence_surface.py` |
| Android is distributed runtime node | `core/android_participant_evidence_ingress.py`; `core/android_delegated_runtime_audit.py`; `core/android_runtime_host.py` (V2-side ingress/audit); Android-side: `GalaxyConnectionService` (145KB), `LoopController` (46KB), `DelegatedRuntimeAcceptanceEvaluator` (33KB) |
| System has center-distributed identity | `core/center_distributed_agent_system_review.py` — `CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL` |

---

## Section 2: Execution Path Inventory

The system has MULTIPLE execution paths.  The delegated path is ONE of them.

### Path 1: Delegated Path (V2 → Android, main cross-device path)

```
[V2 side]
  main.py → core.openclawd.OpenClawd (orchestration hub)
    → core.command_router.CommandRouter (command dispatch)
      → galaxy_gateway.routing.device_router.DeviceRouter (device routing)
        → routing/device_selection.py (4-step: validator → capability gate → autonomous → pool)
          → routing/dispatch.py (AIP v3 message build + WebSocket send)

[Cross-device WebSocket — /ws/device/{device_id}]

[Android side]
  GalaxyConnectionService.handleTaskAssign()
    → DelegatedRuntimeAcceptanceEvaluator.evaluate()  ← LOCAL DECISION
    → executeLocalTaskAssign()
      → AccessibilityScreenshotProvider.captureJpeg()  ← LOCAL PERCEPTION
      → (if local AI active) MobileVlmPlanner.plan()   ← LOCAL INFERENCE
      → (if local AI active) SeeClickGroundingEngine.ground() ← LOCAL GROUNDING
      → AccessibilityActionExecutor.execute()          ← LOCAL GUI INTERACTION
    → sendTaskResult() → V2 result ingress

[V2 result ingress]
  handlers/task_lifecycle.py → android_execution_signal_reconciler
    → task_envelope_lifecycle_registry (future resolved)
```

**Status:** Substantially established.  Transport path has CI verification
(`dual_repo_integration.yml`).  Runtime closure observation requires real device.

### Path 2: Android Local Execution Path

Android does not only passively receive from V2.  It has a local execution loop:

```
[Android — local execution]
  LoopController.step()           ← local step-level orchestration
    → perceive (AccessibilityScreenshotProvider)
    → plan (MobileVlmPlanner or NoOpPlannerService)
    → ground (SeeClickGroundingEngine or NoOp)
    → act (AccessibilityActionExecutor)
    → observe result
    → decide: continue loop or signal completion
```

**Status:** Architecture is real.  `LoopController` (46KB) is a real local execution
orchestrator.  Local AI (planning + grounding) is code-complete but non-default —
requires external inference server.

### Path 3: Android Local Networking Path

Android maintains network connectivity independently:

```
[Android networking]
  GalaxyWebSocketClient (OkHttp WebSocket, out-bound to V2)
    → reconnect logic (handles disconnection + reconnect)
    → OfflineTaskQueue (commands queued during disconnect, replayed on reconnect)
  TailscaleAdapter (alternative network path, additive)
```

**Status:** `GalaxyWebSocketClient` is real and is the main cross-device transport.
`OfflineTaskQueue` is real (queue + replay).  `TailscaleAdapter` is additive.

### Path 4: V2 Windows-Local Execution Path

```
[V2 — Windows-local]
  DecisionExecutor → WindowsExecutionArbiter
    → Windows Accessibility / UI automation
```

**Status:** Exists for V2-local Windows execution, separate from Android path.

---

## Section 3: Six-Layer Maturity Assessment

Maturity must be assessed across six distinct layers.  Conflating them produces
misleading conclusions.

### Layer 1: Architecture / System Model Maturity

**Status: Substantially Closed**

The center-distributed agent architecture is correctly modeled in code:
- `core/dual_repo_system_map.py` — five-plane system registry, dual-repo main chain
- `core/dual_repo_system_reality_audit.py` — code-grounded maturity audit
- `core/center_distributed_agent_system_review.py` — this review (center-distributed identity)
- `core/system_final_acceptance_verdict.py` — top-level system acceptance
- `core/v2_readiness_governance_evidence_surface.py` — evidence aggregation
- `docs/DUAL_REPO_COGNITIVE_MAP.md` — reviewer-facing cognitive map
- `docs/JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2.md` — code-grounded joint review

**What this means:** Reviewers and tools have a correct, code-anchored understanding
of what this system is.  The architecture modeling layer is mature.

---

### Layer 2: Android Local Intelligence / Runtime Host Maturity

**Status: Code Implemented (partially activated)**

Android is a distributed runtime node.  The code evidence:

| Capability | Android Code | Status |
|------------|-------------|--------|
| Local networking | `GalaxyWebSocketClient.kt` (OkHttp WS) | ✅ MAIN_CHAIN |
| Offline resilience | `OfflineTaskQueue.kt` (queue + replay) | ✅ Real |
| Persistent runtime host | `GalaxyConnectionService.kt` (145KB background Service) | ✅ MAIN_CHAIN |
| Local task execution | `AccessibilityActionExecutor.kt` (Accessibility API) | ✅ MAIN_CHAIN |
| Local GUI interaction | `AccessibilityActionExecutor.kt` (tap/scroll/type) | ✅ MAIN_CHAIN |
| Local visual perception | `AccessibilityScreenshotProvider.kt` (JPEG capture) | ✅ MAIN_CHAIN |
| Local acceptance evaluation | `DelegatedRuntimeAcceptanceEvaluator.kt` (33KB, multi-dim) | ✅ Real |
| Local planning loop | `LoopController.kt` (46KB, plan→ground→act loop) | ✅ Real |
| Local inference (code) | `MobileVlmPlanner.kt` (HTTP → llama.cpp/MLC-LLM) | ✅ Code real |
| Local inference (active) | Requires external server + model weights | ❌ Non-default |
| Local grounding (code) | `SeeClickGroundingEngine.kt` (HTTP → grounding server) | ✅ Code real |
| Local grounding (active) | Requires external server | ❌ Non-default |
| Inference lifecycle mgmt | `LocalInferenceRuntimeManager.kt` (Stopped/Running/Failed/SafeMode) | ✅ Architecture real |
| Alternative network | `TailscaleAdapter.kt` | ✅ Additive |

**Critical distinction:** Local AI (inference/planning/grounding) is architecture-real
but non-default.  `NoOpPlannerService` is the default.  `MobileVlmPlanner` activates
only with external llama.cpp/MLC-LLM server running on `127.0.0.1:8080`.

**This does NOT mean Android has no local intelligence.**  It means local AI
requires additional deployment steps.  The architecture, code, and lifecycle
management are all real.

**V2-side evidence anchors:**
- `core/android_participant_evidence_ingress.py`
- `core/android_delegated_runtime_audit.py`
- `core/android_participant_truth_ingress.py`
- `core/android_execution_signal_reconciler.py`
- `core/android_runtime_host.py`

---

### Layer 3: Cross-Device / Delegated Path Maturity

**Status: Partially Closed (substantially established)**

The delegated path (V2 → Android) has strong structural coverage:

| Component | Module | Evidence Level |
|-----------|--------|---------------|
| Readiness gate | `core/delegated_flow_readiness_gate.py` | Importable + tested |
| Acceptance gate | `core/delegated_flow_acceptance_gate.py` | Importable + tested |
| Post-graduation governance | `core/delegated_flow_post_graduation_governance.py` | Importable |
| Decision history | `core/delegated_flow_decision_history.py` | Importable |
| Recovery coordinator | `core/delegated_flow_recovery_coordinator.py` | Importable |
| Continuity coordinator | `core/flow_continuity_coordinator.py` | Importable |
| Recovery truth surface | `core/recovery_truth_surface.py` | Importable |
| Attached runtime recovery | `core/attached_runtime_recovery_readiness.py` | Importable |
| Transport CI | `.github/workflows/dual_repo_integration.yml` | CI-verified |
| Protocol regression | `tests/integration/test_v2_android_protocol_regression.py` | Test-verified |

**Gap:** Formal `DelegatedFlowDecisionHistory.runtime_closure_established = True`
observation requires a real end-to-end run with Android device.  The transport
path is CI-verified; the full runtime closure observation is deferred.

---

### Layer 4: Cross-Repo Evidence Maturity

**Status: Code Implemented (wire gap present)**

Android-originated evidence can reach V2 via ingress modules:

| Ingress Module | Status |
|----------------|--------|
| `core/android_participant_evidence_ingress.py` | Importable |
| `core/android_evaluator_artifact_ingress.py` | Importable |
| `core/android_delegated_runtime_audit.py` | Importable |
| `core/android_participant_truth_ingress.py` | Importable |
| `core/android_execution_signal_reconciler.py` | Importable |
| `core/android_handoff_v2_response_ingress.py` | Importable |
| `core/v2_readiness_governance_evidence_surface.py` | Importable |

**Known gaps (preserved honestly):**

1. **ReconciliationSignal AIP wire gap:** Android's readiness/acceptance/governance
   evidence (`ReconciliationSignal`) is not formally registered as a `MsgType` in
   the AIP v3 wire layer.  Ingress modules exist structurally, but live wire delivery
   of governance evidence from Android to V2 is not confirmed.

2. **HandoffEnvelopeV2 response handler:** The handoff result uplink from Android back
   to V2 may have an incomplete response handler, meaning the result round-trip for
   handoff envelopes is not fully closed.

**These gaps do NOT mean:**
- Android has no evidence surface (it does, via ingress modules)
- Android's local capabilities don't exist (they do)
- V2 has no ability to receive Android evidence (it has ingress modules)

They mean: the AIP wire path for governance-class evidence delivery has a structural
gap that needs explicit wire registration.

---

### Layer 5: Governance / Release Readiness Maturity

**Status: Partially Closed (enforcement is advisory)**

V2's governance framework is architecturally complete:

| Component | Module | Status |
|-----------|--------|--------|
| Governance taxonomy | `core/release_governance_taxonomy.py` | Importable, comprehensive |
| Governance validation gate | `core/governance_validation_gate.py` | Importable |
| Release gate skeleton | `core/distributed_release_gate_skeleton.py` | Importable |
| System acceptance verdict | `core/system_final_acceptance_verdict.py` | Importable |
| Evidence surface | `core/v2_readiness_governance_evidence_surface.py` | Importable |

**Known gap (preserved honestly):**
- `distributed_release_gate_skeleton.is_enforcing = False` — the release gate is
  currently advisory/reporting, not CI-blocking.  This is an explicit design
  decision in PR-7V2 (skeleton PR); promotion to enforcing is deferred.

**What this means:** Governance ARCHITECTURE is strong.  Governance ENFORCEMENT
is currently advisory.  This is an honest maturity gap, not evidence that governance
is absent.

---

### Layer 6: Real-Device / Multi-Device Operational Closure

**Status: Structural Only (gaps significant)**

Multi-device coordination infrastructure exists:

| Component | Status |
|-----------|--------|
| `core/multi_device_coordination_authority.py` | Importable |
| `core/multi_device_truth_convergence.py` | Importable |
| `core/multi_device_runtime_harness.py` | Importable |
| `core/cross_device_execution_chain.py` | Importable |
| `core/recovery_truth_surface.py` | Importable |

**Significant gaps:**
- No Android emulator or real-device CI workflow exists
- No real Android device acceptance evidence artifacts in V2 repo
- Multi-device simultaneous reconnect ordering is not automatically verified
- `docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md` documents the framework but
  real-device closure is not confirmed

**This is the least mature layer.**  All major items here are deferred to future
work or require real-device testing infrastructure.

---

## Section 4: Honest Maturity Summary

| Layer | Status | Key Evidence | Key Gap |
|-------|--------|-------------|---------|
| Architecture / system model | Substantially closed | 6+ importable governance modules; dual-repo map; system identity sentinel | — |
| Android local intelligence / runtime host | Code implemented (partial activation) | Real code for networking, execution, GUI, local AI architecture | Local AI non-default; requires inference server |
| Cross-device / delegated path | Partially closed | Readiness/acceptance/governance gates; CI transport verification | Runtime closure observation requires real device |
| Cross-repo evidence | Code implemented | 6+ ingress modules importable | ReconciliationSignal AIP wire gap; handoff response handler |
| Governance / release readiness | Partially closed | Full taxonomy + verdict + gate skeleton + evidence surface | Release gate is advisory, not CI-blocking |
| Real-device / multi-device | Structural only | Multi-device modules importable | No device CI; no real-device evidence artifacts |

**Overall system verdict: `partial_closure_gaps_present`**

This verdict means:
- The system is NOT a skeleton or proof-of-concept
- The system IS architecturally mature with real execution paths
- The system HAS real Android local capabilities
- The system DOES have governance and acceptance frameworks
- Some execution paths have evidence gaps (cross-repo wire, runtime closure)
- Real-device operational closure is the most significant remaining work

---

## Section 5: What This System Has Achieved (Evidence-Based)

The following capabilities are confirmed by real code, importable modules, and CI:

### ✅ V2 Center Governance Architecture
- Canonical orchestration chain (OpenClawd → CommandRouter → DeviceRouter)
- Capability routing gate (hard enforcement in device_selection)
- Full governance taxonomy and evidence surface
- System-level acceptance verdict aggregation

### ✅ Android Distributed Runtime Node Identity
- Persistent background service (GalaxyConnectionService, 145KB)
- Real local GUI interaction (AccessibilityActionExecutor)
- Real local visual perception (AccessibilityScreenshotProvider)
- Real local planning loop (LoopController, 46KB)
- Real local acceptance evaluation (DelegatedRuntimeAcceptanceEvaluator, 33KB)
- Real local inference ARCHITECTURE (non-default, requires server)

### ✅ Cross-Device Transport Closure
- WebSocket canonical path (`/ws/device/{device_id}`, AIP v3) — CI-verified
- Protocol regression tests for reconnect, offline queue, duplicate results
- Transport-level dual-repo CI verification

### ✅ Delegated Path Infrastructure
- Readiness, acceptance, and governance gates for delegated flow
- Recovery coordinator and continuity coordinator
- Recovery truth surface

### ✅ Honest Gap Documentation
- Known gaps are registered in code (`core/dual_repo_system_map.py` WORKSTREAM_GAP_REGISTRY)
- Deferred items are formally declared with DEFERRED:: policy strings
- No false "fully operational" inflation

---

## Section 6: What Remains Deferred / Unresolved

### Deferred (by design, not blocking)
- Android local inference default activation (requires deployment of inference server)
- Release gate promotion from advisory to CI-blocking
- ReconciliationSignal AIP wire layer formal registration
- HandoffEnvelopeV2 response handler completion
- Real-device CI workflow (Android emulator E2E)
- Multi-device acceptance matrix closure

### Evidence Gaps (need closing)
- `DelegatedFlowDecisionHistory.runtime_closure_established` observation from
  real end-to-end run
- Canonical session truth durable audit store default activation
- In-flight task lifecycle cross-restart persistence

### Structural Gaps (acknowledged)
- Multi-device simultaneous reconnect ordering enforcement
- Android E2E protocol verification (no emulator CI)

---

## Section 7: Prohibited Characterizations

Per `HONEST_GAP_PRESERVATION_POLICY` and system identity review, the following
characterizations are **prohibited** because they are factually incorrect:

| Prohibited | Why Incorrect |
|------------|---------------|
| "Android is a passive execution endpoint" | Android has local acceptance evaluation, local planning loop, local GUI interaction, and local AI architecture |
| "This is just a control plane + passive executor" | Android is a distributed runtime node with genuine local intelligence |
| "The system is only built around the delegated path" | Multiple execution paths exist: local execution, local inference, cross-device, V2-local |
| "The system has no local AI" | Local AI architecture is code-real; it is non-default but architecturally complete |
| "Evidence gaps mean the system is a skeleton" | Structural and code maturity is high; specific wire and enforcement gaps exist but are bounded and documented |
| "The system is fully operational" | Real-device CI, runtime closure observation, and some wire gaps are not yet closed |

---

## Section 8: Code Anchors Index

| Concept | Primary Code Anchor |
|---------|-------------------|
| Center-distributed system identity | `core/center_distributed_agent_system_review.py` |
| System plane registry | `core/dual_repo_system_map.py` |
| Code-grounded maturity audit | `core/dual_repo_system_reality_audit.py` |
| System acceptance verdict | `core/system_final_acceptance_verdict.py` |
| V2 evidence surface | `core/v2_readiness_governance_evidence_surface.py` |
| Governance taxonomy | `core/release_governance_taxonomy.py` |
| Release gate skeleton | `core/distributed_release_gate_skeleton.py` |
| Multi-device coordination | `core/multi_device_coordination_authority.py` |
| Multi-device truth convergence | `core/multi_device_truth_convergence.py` |
| Recovery truth surface | `core/recovery_truth_surface.py` |
| Android evidence ingress | `core/android_participant_evidence_ingress.py` |
| Android delegated audit | `core/android_delegated_runtime_audit.py` |
| Android signal reconciler | `core/android_execution_signal_reconciler.py` |
| Dual-repo cognitive map | `docs/DUAL_REPO_COGNITIVE_MAP.md` |
| Joint system review (2026 Q2) | `docs/JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2.md` |
| Transport CI | `.github/workflows/dual_repo_integration.yml` |
| Protocol regression tests | `tests/integration/test_v2_android_protocol_regression.py` |

---

## Machine-Checkable Verification

This review document is backed by a machine-runnable review module:

```python
from core.center_distributed_agent_system_review import (
    get_center_distributed_agent_system_review,
    CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL,
    ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_POLICY,
    DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_POLICY,
)

report = get_center_distributed_agent_system_review()
assert report.system_is_center_distributed_agent
assert report.delegated_path_is_one_path_not_whole_system
assert report.android_capability_profile.local_task_execution_capability
assert len(report.deferred_items) > 0  # gaps preserved honestly
```

Tests enforcing correct system characterization:
- `tests/test_center_distributed_agent_system_review.py`
