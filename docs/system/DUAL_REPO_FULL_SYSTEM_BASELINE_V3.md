# DUAL_REPO_FULL_SYSTEM_BASELINE_V3

## What this is

`core/full_system_baseline_v3.py` is the canonical V3 full-system baseline for the
Galaxy dual-repo (V2 + Android) architecture.  It aggregates the outputs of all major
existing evaluators into a **single machine-readable report** (`V3BaselineReport`) that
answers the one top-level engineering question:

> *Right now — based on real code — what is the unified state of the entire
> dual-repo system, which subsystems are truly done, and what is still blocking?*

`core/full_system_evidence_closure_gate.py` wraps the report and provides a
pass/fail gate at three closure levels (minimum / standard / strict).

---

## V3 subsystem states

Each subsystem is classified into exactly one of five states:

| State | Meaning |
|---|---|
| `implemented_and_evidenced` | Real code present, end-to-end tests/CI prove it works |
| `implemented_but_not_closed` | Real code present; at least one gap prevents full evidence closure |
| `contract_only` | Interface/schema defined; no runtime implementation yet |
| `test_only` | Tests describe expected behavior; production code is absent |
| `declared_not_proven` | Mentioned in docs/sentinels; no importable code or real evidence |

---

## Twelve tracked subsystems

| Subsystem ID | Module probed |
|---|---|
| `v2_canonical_truth_ingress` | `core.canonical_session_truth` |
| `v2_unified_result_ingress` | `core.unified_result_ingress` |
| `v2_capability_routing_gate` | `core.capability_routing_gate` |
| `v2_recovery_redispatch` | `core.delegated_flow_recovery_coordinator` |
| `v2_governance_readiness_gate` | `core.delegated_flow_readiness_gate` |
| `v2_release_gate` | `core.distributed_release_gate_skeleton` |
| `android_participant_ingress` | `core.android_participant_truth_ingress` |
| `android_evaluator_artifact_ingress` | `core.android_evaluator_artifact_ingress` |
| `cross_repo_evidence_pipeline` | `core.canonical_cross_repo_evidence_pipeline` |
| `cross_repo_contract_schema_gate` | `core.android_nl_semantic_chain_contract` |
| `dual_repo_reality_audit` | `core.dual_repo_system_reality_audit` |
| `system_final_acceptance_verdict` | `core.system_final_acceptance_verdict` |

---

## Android evidence policy

Android cross-repo evidence absence **always** downgrades the top-level verdict
to at most `partially_closed_blocking_gaps` and produces the blocking gap
`android_cross_repo_evidence_absent`.

V2 cannot self-certify cross-repo system closure.  The Android repository must
push real evidence artifacts (via `repository_dispatch` or file-based JSON) for
the `cross_repo_evidence_pipeline` to reach `complete` verdict.

---

## Top-level verdicts

| Verdict | Meaning |
|---|---|
| `closed_and_evidenced` | All 12 subsystems evidenced + Android evidence present |
| `partially_closed_blocking_gaps` | Most implemented but ≥1 critical gap remains |
| `structural_only_runtime_not_closed` | Architecture defined; runtime not closed |
| `insufficient_evidence_to_conclude` | Evaluation could not complete |

---

## Usage

```python
from core.full_system_baseline_v3 import build_v3_baseline_report
report = build_v3_baseline_report()
print(report.overall_verdict.value)
print(report.to_json())
```

```python
from core.full_system_evidence_closure_gate import evaluate_evidence_closure_gate, ClosureLevel
result = evaluate_evidence_closure_gate(ClosureLevel.standard)
if not result.gate_passed:
    print(result.fail_reasons)
```

---

## Underlying reports consumed

- `core.system_final_acceptance_verdict` (PR-17V2)
- `core.dual_repo_system_reality_audit` (PR-537)
- `core.canonical_cross_repo_evidence_pipeline` (PR-05)
- `core.dual_repo_system_completeness_review` (PR-REVIEW)
- `core.distributed_release_gate_skeleton` (PR-7V2)
