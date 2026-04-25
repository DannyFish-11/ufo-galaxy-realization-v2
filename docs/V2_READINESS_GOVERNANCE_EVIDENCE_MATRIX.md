# V2 Readiness / Governance Evidence Matrix

> **Repository**: `DannyFish-11/ufo-galaxy-realization-v2`
> **Companion**: `DannyFish-11/ufo-galaxy-android` (PR #255)
> **PR**: `PR-6V2-EVIDENCE` — Make V2 readiness and governance evidence reviewable and release-gate ready
> **Status**: Implemented and test-validated
> **Companion Android PR**: `DannyFish-11/ufo-galaxy-android` PR #255 (in parallel development; V2 consumes Android evidence regardless of companion PR merge state)

---

## 1. Executive Summary

This document is the structured reviewability artifact for PR-6V2-EVIDENCE.
It answers the four questions a reviewer needs without reverse-engineering the
V2 architecture:

1. **What V2-side signals/tests/artifacts count as readiness/governance evidence?**
2. **Which evidence is canonical/gate-worthy vs advisory/observational?**
3. **Where is Android-originated evidence represented and classified in V2?**
4. **How can later release-gating/CI work build on this surface?**

The evidence surface is implemented in
[`core/v2_readiness_governance_evidence_surface.py`](../core/v2_readiness_governance_evidence_surface.py)
and exercised by
[`tests/test_pr535_v2_readiness_governance_evidence_surface.py`](../tests/test_pr535_v2_readiness_governance_evidence_surface.py).

---

## 2. Evidence Classification Legend

| Symbol | Classification | Gate-worthy? |
|--------|---------------|-------------|
| 🔒 **Canonical** | Gate-worthy; produced by authoritative V2 gate modules | ✅ May block release |
| 🔷 **Advisory** | Observational / local-only; useful for debugging but MUST NOT gate release | ❌ Must not block release |
| 🌐 **Companion Repo** | Originates in Android; V2 ingests, classifies, and promotes to canonical gate input | ✅ After V2 ingestion |

---

## 3. Canonical Evidence Matrix

### 3.1 Delegated Flow Readiness Gate (PR-9V2)

| Item | Detail |
|------|--------|
| **Classification** | 🔒 Canonical |
| **Module** | `core.delegated_flow_readiness_gate` |
| **Class** | `DelegatedFlowReadinessGate` |
| **Entry point** | `evaluate_delegated_flow_readiness()` → `DelegatedFlowReadinessReport` |
| **Authority sentinel** | `DELEGATED_FLOW_READINESS_GATE_AUTHORITY` |
| **Gate verdict type** | `DelegatedFlowReadinessVerdict` |
| **Test file** | `tests/test_pr10_v2_delegated_flow_acceptance_gate.py` |
| **What it covers** | Five readiness dimensions: continuity_replay, truth_ownership, result_convergence, operator_surface, compat_legacy |

**Dimensions evaluated:**

| Dimension | Signal Source | Gate-blocking? |
|-----------|--------------|----------------|
| `continuity_replay` | `core.flow_continuity_coordinator.FlowContinuityCoordinator` | ✅ |
| `truth_ownership` | `core.flow_level_truth_ownership.FlowTruthAlignmentRuntime` | ✅ |
| `result_convergence` | `core.flow_aware_result_convergence` | ✅ |
| `operator_surface` | `core.flow_level_operator_surface` | ✅ |
| `compat_legacy` | `core.compat_legacy_path_blocking_canonicalization` | ✅ |

Policy: `ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_POLICY`

---

### 3.2 Delegated Flow Acceptance / Graduation Gate (PR-10V2)

| Item | Detail |
|------|--------|
| **Classification** | 🔒 Canonical |
| **Module** | `core.delegated_flow_acceptance_gate` |
| **Class** | `DelegatedFlowAcceptanceGate` |
| **Entry point** | `evaluate_delegated_flow_acceptance()` → `DelegatedFlowAcceptanceReport` |
| **Authority sentinel** | `DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY` |
| **Gate verdict type** | `DelegatedFlowAcceptanceVerdict` |
| **Test file** | `tests/test_pr10_v2_delegated_flow_acceptance_gate.py` |
| **What it covers** | Six acceptance dimensions: continuity_replay_evidence, truth_ownership_evidence, result_convergence_evidence, operator_visibility_evidence, compat_bypass_evidence, readiness_prerequisite |

**Key policies:**

- `ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY` — all six dimensions must pass; no optional dimensions
- `READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY` — PR-9V2 readiness verdict is evaluated as the `readiness_prerequisite` dimension
- `ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_POLICY` — each dimension references its canonical source module

---

### 3.3 Post-Graduation Governance Evaluator (PR-11V2)

| Item | Detail |
|------|--------|
| **Classification** | 🔒 Canonical |
| **Module** | `core.delegated_flow_post_graduation_governance` |
| **Class** | `DelegatedFlowGovernanceEvaluator` |
| **Entry point** | `evaluate_post_graduation_governance()` → `DelegatedFlowGovernanceReport` |
| **Authority sentinel** | `DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY` |
| **Gate verdict type** | `GovernanceVerdict` |
| **Test file** | `tests/test_pr11_v2_delegated_flow_post_graduation_governance.py` |
| **What it covers** | Five continuous governance dimensions post-graduation: truth_alignment, result_convergence, operator_visibility, compat_bypass, continuity_replay |

**Note:** Graduation is a one-time gate; post-graduation governance is continuous compliance monitoring.

---

### 3.4 Continuity / Recovery / Durability Closure (PR-5V2)

| Item | Detail |
|------|--------|
| **Classification** | 🔒 Canonical |
| **Module** | `core.recovery_durability_closure_validator` |
| **Class** | `RecoveryClosureReport` |
| **Entry point** | `build_recovery_closure_report()` → `RecoveryClosureReport` |
| **Authority sentinel** | `RECOVERY_DURABILITY_CLOSURE_AUTHORITY` |
| **Test file** | `tests/test_pr534_continuity_recovery_durability_closure.py` |
| **What it covers** | 17 recovery scenarios across V2 restart, transport reconnect, stale/duplicate signal guard, in-flight delegated work recovery, runtime restart recovery |

**Deferred (explicit):** RS-16 (offline queue ordering) is documented as deferred with an explicit deferral note.

---

### 3.5 Takeover Request/Response Tracking

| Item | Detail |
|------|--------|
| **Classification** | 🔒 Canonical |
| **Module** | `core.takeover_tracking` |
| **Class** | `TakeoverTrackingRuntime` |
| **Entry point** | `get_takeover_tracking_runtime().snapshot()` |
| **Authority sentinel** | `TAKEOVER_TRACKING_AUTHORITY` |
| **Test files** | `tests/test_android_takeover_protocol.py`, `tests/test_android_delegated_runtime_audit.py` |
| **What it covers** | Persisted accept/reject decisions for every V2-issued takeover request; queryable by `takeover_id` and `session_id` |

---

### 3.6 Compat / Legacy Path Blocking (PR-8V2)

| Item | Detail |
|------|--------|
| **Classification** | 🔒 Canonical |
| **Module** | `core.compat_legacy_path_blocking_canonicalization` |
| **Entry point** | `get_compat_blocking_snapshot()` |
| **Test file** | `tests/test_pr10_v2_delegated_flow_acceptance_gate.py` |
| **What it covers** | Blocking-first gate for all compat/legacy influence vectors; no active bypass is a gate requirement |

---

## 4. Advisory Evidence (not gate-blocking)

### 4.1 Android Delegated Runtime Audit Records

| Item | Detail |
|------|--------|
| **Classification** | 🔷 Advisory |
| **Module** | `core.android_delegated_runtime_audit` |
| **Class** | `AndroidDelegatedRuntimeAuditRecorder` |
| **Entry point** | `android_audit_snapshot()` |
| **Test file** | `tests/test_android_delegated_runtime_audit.py` |
| **What it covers** | Full timeline for every Android-delegated wire event: delegated_execution_signal, handoff_v2_result, takeover_request, takeover_response, reconciliation_signal, participant_truth_terminal_update |
| **Why advisory** | Provides observability and debugging context; the raw ring buffer is not a gate input.  Gate decisions come from TakeoverTrackingRuntime and the delegated-flow readiness/acceptance gates. |

---

### 4.2 Android Participant Session Truth (reconciliation state)

| Item | Detail |
|------|--------|
| **Classification** | 🔷 Advisory |
| **Module** | `core.android_participant_session_state` |
| **Class** | `AndroidParticipantSessionRegistry` |
| **Test file** | `tests/test_android_delegated_runtime_structural_consolidation.py` |
| **What it covers** | Phase-by-phase session bookkeeping (handoff_dispatched → takeover_accepted → execution_complete) |
| **Why advisory** | Phase transitions feed lifecycle coordinator outcomes which are canonical; the raw session registry is observational. |

---

## 5. Companion-Repo (Android-Originated) Evidence

### 5.1 Android Evaluator Artifact Ingestion (PR-4V2-GOV)

| Item | Detail |
|------|--------|
| **Classification** | 🌐 Companion Repo → 🔒 Canonical after V2 ingestion |
| **Origin** | `DannyFish-11/ufo-galaxy-android` runtime evaluators |
| **V2 ingress module** | `core.android_evaluator_artifact_ingress` |
| **V2 registry** | `AndroidEvaluatorArtifactRegistry` |
| **V2 gate visibility** | `DelegatedFlowReadinessGate._evaluate_truth_ownership()` via `FlowTruthAlignmentRuntime` |
| **Test file** | `tests/test_pr03_v2_android_bridge_canonical_ingress.py` |

**Artifact kinds and V2 gate classification:**

| Android Artifact Kind | V2 Truth Kind | V2 Gate Classification |
|-----------------------|--------------|----------------------|
| `governance` evaluator artifact | `governance_artifact` | ✅ Canonical gate input |
| `readiness` evaluator artifact | `governance_artifact` | ✅ Canonical gate input |
| `acceptance` evaluator artifact | `governance_artifact` | ✅ Canonical gate input |
| `strategy` evaluator artifact | `governance_artifact` | ✅ Canonical gate input |
| `readiness_assessment` truth kind (legacy) | `readiness_assessment` | ❌ Advisory / local-only |
| `runtime_state` truth kind | `runtime_state` | ❌ Advisory / local-only |

**Ingestion chain:**

```
Android RuntimeController
  └─ Evaluator produces artifact (DeviceGovernanceArtifact, etc.)
       └─ Android emits ReconciliationSignal (truth_kind=governance_artifact)
            └─ V2 gateway receives message
                 └─ ingest_android_evaluator_artifact(message)
                      └─ AndroidEvaluatorArtifactRegistry.store(artifact)
                      └─ ingest_android_participant_truth_message(msg, truth_kind=governance_artifact)
                           └─ align_and_record(FlowTruthAlignmentContext)
                                └─ FlowTruthAlignmentRuntime.record(FlowTruthDecisionArtifact)
                                     └─ DelegatedFlowReadinessGate._evaluate_truth_ownership()
                                          └─ build_flow_truth_alignment_snapshot()
                                               └─ returns 'ready' if decisions > 0 and no quarantines
```

Policy reference: `GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY`
(see `docs/ANDROID_EVALUATOR_ARTIFACT_GOVERNANCE_INTEGRATION.md`)

---

## 6. Evidence Surface Aggregation Module

The module `core/v2_readiness_governance_evidence_surface.py` provides a
single read-only aggregation surface over all evidence dimensions described
above:

```python
from core.v2_readiness_governance_evidence_surface import (
    build_evidence_surface_report,
    EvidenceClassification,
)

report = build_evidence_surface_report()
print(report.to_json())
# {
#   "report_id": "<uuid>",
#   "generated_at": <timestamp>,
#   "canonical_count": 6,
#   "advisory_count": 2,
#   "companion_repo_count": 1,
#   "all_canonical_present": true,
#   "dimensions": [ ... ],
#   "deferred_notes": [ ... ]
# }
```

**Design properties:**

- **Additive only** — no existing module is modified.
- **Projection-only** — all probes are read-only; no canonical state is mutated.
- **Fail-graceful** — unavailable modules produce `evidence_status="unavailable"` entries; the report is always returned.
- **Stable** — `EvidenceSurfaceReport` is fully JSON-serialisable.
- **Reviewer-friendly** — every dimension entry carries `code_reference` and `test_reference`.

**Policy sentinels (importable for downstream assertion):**

| Sentinel | Policy |
|----------|--------|
| `CANONICAL_EVIDENCE_IS_GATE_INPUT_POLICY` | Only canonical evidence may gate release |
| `ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_POLICY` | Advisory evidence must not block release |
| `COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY` | V2 is authority for Android evidence classification |
| `EVIDENCE_SURFACE_IS_PROJECTION_ONLY_POLICY` | Surface never mutates state |
| `EVIDENCE_SURFACE_IS_REVIEWER_FRIENDLY_POLICY` | Every entry must carry code/test references |

---

## 7. Evidence Dimension → Code → Test Traceability Map

| # | Evidence Dimension | Classification | Code Module | Test File |
|---|-------------------|----------------|-------------|-----------|
| 1 | Delegated Flow Readiness Gate | 🔒 Canonical | `core.delegated_flow_readiness_gate` | `test_pr10_v2_delegated_flow_acceptance_gate.py` |
| 2 | Delegated Flow Acceptance Gate | 🔒 Canonical | `core.delegated_flow_acceptance_gate` | `test_pr10_v2_delegated_flow_acceptance_gate.py` |
| 3 | Post-Graduation Governance | 🔒 Canonical | `core.delegated_flow_post_graduation_governance` | `test_pr11_v2_delegated_flow_post_graduation_governance.py` |
| 4 | Continuity/Recovery Closure | 🔒 Canonical | `core.recovery_durability_closure_validator` | `test_pr534_continuity_recovery_durability_closure.py` |
| 5 | Takeover Tracking | 🔒 Canonical | `core.takeover_tracking` | `test_android_takeover_protocol.py` |
| 6 | Compat/Legacy Blocking | 🔒 Canonical | `core.compat_legacy_path_blocking_canonicalization` | `test_pr10_v2_delegated_flow_acceptance_gate.py` |
| 7 | Android Delegated Audit Ring | 🔷 Advisory | `core.android_delegated_runtime_audit` | `test_android_delegated_runtime_audit.py` |
| 8 | Participant Session Truth | 🔷 Advisory | `core.android_participant_session_state` | `test_android_delegated_runtime_structural_consolidation.py` |
| 9 | Android Evaluator Artifact Ingestion | 🌐 Companion→Canonical | `core.android_evaluator_artifact_ingress` | `test_pr03_v2_android_bridge_canonical_ingress.py` |

---

## 8. What Is Deferred

| # | Deferred Item | Deferral Reason | Future PR |
|---|--------------|-----------------|-----------|
| 1 | Final release-gate CI enforcement (blocking PR merges on evidence failure) | Requires stable evidence surface first (this PR); CI wiring is a separate scope | Later PR |
| 2 | Android offline queue ordering authority | Documented in `RecoveryClosureReport` RS-16 scenario | Later PR |
| 3 | Default-on / rollout promotion policy for delegated canonical path | Acceptance and governance gates provide the evidence foundation; promotion policy is a separate decision | Later PR |

---

## 9. How Later Release-Gating / CI Work Can Build on This Surface

A future CI integration PR can:

1. Import `build_evidence_surface_report()` from
   `core.v2_readiness_governance_evidence_surface`.
2. Assert `report.all_canonical_present is True` as a CI gate.
3. Assert `report.unavailable_count == 0` to ensure all evidence modules
   are importable.
4. Surface `report.to_json()` as a CI artifact for diff and audit.
5. Assert specific canonical dimension sentinels (e.g.
   `DELEGATED_FLOW_READINESS_GATE_AUTHORITY`) are importable.

The `EvidenceSurfaceReport.deferred_notes` list documents what must not yet
be enforced so CI tooling can skip deferred dimensions without guessing.

---

## 10. Relationship to Android PR #255

The companion Android PR (`DannyFish-11/ufo-galaxy-android` PR #255) surfaces
Android-side readiness evidence.  This V2 PR:

- Consumes Android evaluator artifacts via `core.android_evaluator_artifact_ingress`
- Classifies them per `COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY`
- Makes the classification explicit in the evidence surface matrix (section 5)
- Does not implement Android-side logic (that is the companion PR's scope)

V2 remains the **canonical orchestration authority**; it determines how
Android-originated evidence is classified and which dimensions it feeds.
