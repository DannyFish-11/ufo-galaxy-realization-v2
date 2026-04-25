# Android Evaluator Artifact Governance Integration

> **Repository**: `DannyFish-11/ufo-galaxy-realization-v2`
> **Companion**: `DannyFish-11/ufo-galaxy-android`
> **PR**: `PR-4V2-GOV` — Wire Android evaluator artifacts into canonical readiness and governance flow
> **Status**: Implemented and test-validated

---

## 1. Executive Summary

This document is the structured validation artifact required by the PR-4V2-GOV
acceptance criteria (requirement 4).  It describes which Android-originated
evaluator/runtime artifacts are now integrated into canonical V2 readiness/governance
flow, which are canonical gate inputs vs observation-only evidence, and what remains
deferred.

| Artifact Kind | V2 Gate Visibility | Classification | Status |
|---------------|-------------------|----------------|--------|
| `governance_artifact` (truth kind) | ✅ Canonical gate | Authoritative upward | ✅ INTEGRATED |
| `governance` evaluator artifact | ✅ Canonical gate | Authoritative | ✅ INTEGRATED |
| `readiness` evaluator artifact | ✅ Canonical gate | Authoritative | ✅ INTEGRATED |
| `acceptance` evaluator artifact | ✅ Canonical gate | Authoritative | ✅ INTEGRATED |
| `strategy` evaluator artifact | ✅ Canonical gate | Authoritative | ✅ INTEGRATED |
| `readiness_assessment` (truth kind) | ❌ Advisory only | Local-only | ✅ CORRECT (by design) |
| `runtime_state` (truth kind) | ❌ Advisory only | Local-only | ✅ CORRECT (by design) |

---

## 2. Artifact → V2 Integration Chain

### 2.1 Full chain (PR-4V2-GOV closing the gap)

```
Android RuntimeController
  └─ Android evaluator runs (governance / readiness / acceptance / strategy)
       └─ Evaluator produces artifact (DeviceGovernanceArtifact etc.)
            └─ [Path A] Android emits reconciliation_signal with truth_kind=governance_artifact
                 └─ V2 gateway receives message
                      └─ handle_reconciliation_signal() or truth ingress entry-point
                           └─ ingest_android_participant_truth_message(msg)
                                └─ extract_participant_truth_envelope(msg)
                                     └─ truth_kind = AndroidParticipantTruthKind.governance_artifact
                                          └─ reconcile_android_participant_truth(envelope)
                                               └─ _reconcile_governance_artifact(envelope)
                                                    └─ align_and_record(FlowTruthAlignmentContext)
                                                         └─ FlowTruthAlignmentRuntime.record(FlowTruthDecisionArtifact)
                                                              └─ DelegatedFlowReadinessGate._evaluate_truth_ownership()
                                                                   └─ build_flow_truth_alignment_snapshot()
                                                                        └─ returns 'ready' if decisions > 0 and no quarantines

            └─ [Path B] ingest_android_evaluator_artifact(msg) [dedicated ingress module]
                 └─ extract_evaluator_artifact(msg)
                      └─ AndroidEvaluatorArtifactRegistry.record(artifact)  ← projection storage
                           └─ ingest_android_participant_truth_message(truth_msg with governance_artifact kind)
                                └─ _reconcile_governance_artifact(envelope)
                                     └─ align_and_record(FlowTruthAlignmentContext)
                                          └─ FlowTruthAlignmentRuntime.record(FlowTruthDecisionArtifact)
                                               └─ [same gate consumption as Path A]
```

### 2.2 Chain component map

| Step | Module | Function | Status |
|------|--------|----------|--------|
| Truth kind | `core/android_participant_truth_ingress.py` | `AndroidParticipantTruthKind.governance_artifact` | ✅ Added |
| Policy sentinel | `core/android_participant_truth_ingress.py` | `GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY` | ✅ Added |
| Reconcile helper | `core/android_participant_truth_ingress.py` | `_reconcile_governance_artifact()` | ✅ Added |
| Flow truth classification | `core/flow_level_truth_ownership.py` | `_AUTHORITATIVE_TRUTH_KINDS` | ✅ Updated |
| Alignment + record | `core/flow_level_truth_ownership.py` | `align_and_record()` | ✅ Existing, now called |
| Artifact projection storage | `core/android_evaluator_artifact_ingress.py` | `AndroidEvaluatorArtifactRegistry` | ✅ New module |
| Dedicated ingress entry-point | `core/android_evaluator_artifact_ingress.py` | `ingest_android_evaluator_artifact()` | ✅ New module |
| Gate consumption | `core/delegated_flow_readiness_gate.py` | `_evaluate_truth_ownership()` | ✅ Existing, now reads governance artifacts |

---

## 3. Canonical Gate Inputs vs Observation-Only Evidence

### 3.1 Canonical gate inputs (first-class)

| Signal / Artifact | Truth Kind | Classification | V2 Module | Gate Dimension |
|-------------------|-----------|----------------|-----------|----------------|
| Android governance evaluator artifact | `governance_artifact` | `accept_as_authoritative` | `_reconcile_governance_artifact()` → `align_and_record()` | `truth_ownership` |
| Android readiness evaluator artifact | `governance_artifact` | `accept_as_authoritative` | same | `truth_ownership` |
| Android acceptance evaluator artifact | `governance_artifact` | `accept_as_authoritative` | same | `truth_ownership` |
| Android strategy evaluator artifact | `governance_artifact` | `accept_as_authoritative` | same | `truth_ownership` |
| Android cancel signal | `cancel` | `accept_as_authoritative` | `_reconcile_terminal_signal()` | `truth_ownership` |
| Android failure signal | `failure` | `accept_as_authoritative` | `_reconcile_terminal_signal()` | `truth_ownership` |
| Android result signal | `result` | `accept_as_authoritative` | `_reconcile_terminal_signal()` | `truth_ownership` |
| Android reconciliation_signal | `reconciliation_signal` | `accept_as_authoritative` | `_reconcile_reconciliation_signal()` | `truth_ownership` |

### 3.2 Observation-only evidence (advisory / local-only)

| Signal / Artifact | Truth Kind | Classification | Policy |
|-------------------|-----------|----------------|--------|
| Android readiness assessment | `readiness_assessment` | Advisory / `local_only=True` | `READINESS_ASSESSMENT_IS_ADVISORY_POLICY` |
| Android runtime state | `runtime_state` | Audit-only / `local_only=True` | `RUNTIME_STATE_IS_AUDIT_ONLY_POLICY` |
| Android session snapshot | `session_snapshot` | Session continuity validation only | `SESSION_SNAPSHOT_VALIDATES_REGISTRY_CONTINUITY_POLICY` |
| Android status signal | `status` | Progress signal only | `STATUS_SIGNAL_EMITS_PROGRESS_EVENT_POLICY` |

**Design invariant**: `readiness_assessment` (pre-existing truth kind) remains advisory by
policy because it carries device-scope assessment, not a terminal execution outcome.  The new
`governance_artifact` truth kind is distinct: it carries evaluator-produced governance/readiness/
acceptance/strategy artifacts from Android evaluators, which are treated as authoritative
upward per `GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY`.

---

## 4. Storage / Projection Locations

Android-originated evaluator artifacts are stored/projected in two locations:

### 4.1 FlowTruthAlignmentRuntime (gate-visible)

**Module**: `core/flow_level_truth_ownership.py`
**Class**: `FlowTruthAlignmentRuntime`
**Populated by**: `align_and_record()` called from `_reconcile_governance_artifact()`
**Read by**: `DelegatedFlowReadinessGate._evaluate_truth_ownership()` via `build_flow_truth_alignment_snapshot()`

Every `governance_artifact` truth reconciliation writes a `FlowTruthDecisionArtifact` to
`FlowTruthAlignmentRuntime` with `decision=accept_as_authoritative`.  The gate reads this
runtime's snapshot to evaluate `truth_ownership` readiness dimension.

### 4.2 AndroidEvaluatorArtifactRegistry (operator-visible projection)

**Module**: `core/android_evaluator_artifact_ingress.py`
**Class**: `AndroidEvaluatorArtifactRegistry`
**Populated by**: `ingest_android_evaluator_artifact()` → `registry.record(artifact)`
**Read by**: Operator surfaces, audit tools, and diagnostic endpoints via `list_recent()`,
`get_latest_for_device_kind()`, `build_snapshot()`

This dedicated projection stores typed `AndroidEvaluatorArtifact` records (with `kind`,
`device_id`, `is_compliant`, `verdict_label`, etc.) in a ring buffer for introspection
without requiring re-derivation from raw signals.

---

## 5. Verdict Influence — Test Evidence

| Test ID | What it proves | AC |
|---------|---------------|-----|
| `test_F01` | `governance_artifact` truth kind exists in `AndroidParticipantTruthKind` | AC1 |
| `test_F02` | `governance_artifact` `affects_canonical_state()` = True | AC4 |
| `test_F03` | `governance_artifact` ingestion returns `local_only=False` (not advisory) | AC4 |
| `test_F04` | `readiness_assessment` remains `local_only=True` (advisory, by design) | AC4 |
| `test_G02` | After `align_and_record()` with governance_artifact, `FlowTruthAlignmentRuntime.total_decisions` increases | AC2 |
| `test_G03` | governance_artifact is classified as `accept_as_authoritative` by `align_and_record()` | AC4 |
| `test_H01` | `readiness_assessment` is classified as `accept_as_advisory` (advisory) | AC4 |
| `test_I01` | `DelegatedFlowReadinessGate` report includes `truth_ownership` dimension | AC3 |
| `test_I02` | After recording governance_artifact decision, gate report includes `truth_ownership` | AC3 |
| `test_I03` | `truth_ownership` is not `unknown` when `FlowTruthAlignmentRuntime` has decisions | AC3 |
| `test_J01` | `ingest_android_evaluator_artifact()` writes to `FlowTruthAlignmentRuntime` | AC1 + AC2 |
| `test_J02` | All four evaluator kinds (governance/readiness/acceptance/strategy) are ingested | AC1 |
| `test_J03` | After ingesting governance artifact, gate `truth_ownership` dimension is not `unknown` | AC3 |

---

## 6. Deferred to Later PRs

Per `DEFERRED_TO_LATER_PRS_POLICY` in `core/android_evaluator_artifact_ingress.py`:

| Item | Reason | Scope |
|------|--------|-------|
| CI/release blocking on governance artifact verdict | Gate evaluates but does not auto-block CI | PR-8V2 follow-up |
| Full default-on release readiness based on governance artifacts | Requires all five gate dimensions to be ready | PR-9V2 follow-up |
| Android-side dedicated message type for evaluator artifact upload | Currently routed via `ReconciliationSignal` with `governance_artifact` kind | Android companion PR |
| Multi-device governance verdict aggregation | Requires `multi_device_truth_convergence` integration | Later PR |
| `readiness_assessment` → canonical gate integration | By design advisory; would require new protocol extension | Explicitly deferred |

---

## 7. Canonical Path Chain Verification

Run the following command to verify the full chain end-to-end:

```bash
python -m pytest tests/test_pr4v2_android_evaluator_artifact_governance_flow.py -v
```

Expected: 47 tests pass.

For the full cross-repo signal closure health check:

```bash
python -m pytest \
  tests/test_pr4v2_android_evaluator_artifact_governance_flow.py \
  tests/test_pr4v2_android_participant_truth_ingress.py \
  tests/test_e2e_cross_repo_signal_closure.py \
  -v --ignore-glob="*test_r1*"
```

---

## 8. How This PR Closes the Identified Gap

Prior state (from `CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md` section 5):

> **Gap**: `readiness_assessment` / `runtime_state` advisory kinds do not feed truth_ownership gate
> **Severity**: 📝 Known, by design
> **Path to Close**: Android would need to emit a terminal/result truth kind carrying the evaluator outcome, or a dedicated protocol extension (e.g., a new truth kind for governance artifact upload).

This PR implements the "dedicated protocol extension" path:

1. Added `governance_artifact` truth kind to `AndroidParticipantTruthKind`
2. `governance_artifact` routes through `_reconcile_governance_artifact()` which calls `align_and_record()`
3. `align_and_record()` classifies it as `accept_as_authoritative` (not advisory) and writes to `FlowTruthAlignmentRuntime`
4. `DelegatedFlowReadinessGate._evaluate_truth_ownership()` reads `FlowTruthAlignmentRuntime` and now reflects Android governance artifacts
5. `AndroidEvaluatorArtifactRegistry` provides a dedicated operator-visible projection for all four evaluator kinds
6. `ingest_android_evaluator_artifact()` is the canonical entry-point for Android-side artifact upload

The previous `readiness_assessment` advisory path is preserved unchanged per policy.

---

*Last updated: PR-4V2-GOV implementation*
