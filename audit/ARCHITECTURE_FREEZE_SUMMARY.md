# Architecture Freeze Summary

> **Status**: FROZEN  
> **Date**: 2026-04-30  
> **Full document**: `docs/architecture/UNIFIED_CENTER_DISTRIBUTED_RUNTIME_ARCHITECTURE_FREEZE_V1.md`  
> **Guardrails**: `docs/architecture/ARCHITECTURE_FREEZE_IMPLEMENTATION_GUARDRAILS.md`  
> **Basis**: `FINAL_ARCHITECTURE_VALIDATION_AUDIT.md`, `FINAL_VERDICT_CLASSIFICATION_TABLE.md`, `CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md`

---

## System Identity (frozen)

> One **Unified Center-Distributed Runtime**: one governing center, one unified authority model, one unified completion truth, multiple coexisting execution domains, participant model generalized above its first concrete Android implementation.

---

## Confirmed Execution Domains

```
Unified Center-Distributed Runtime
├── Center Governance and Cognition    [main.py → SystemOrchestrator → OpenClawd]
├── Local Execution Domain             [HybridExecutionArbiter → DecisionExecutor]
└── Distributed Participant Domain     [CommandRouter → gateway → participant runtime]
      First implementation: Android
      Architecture: participant-generic above Android
```

---

## Final Layer Model (frozen)

| # | Layer | Governing Module(s) | Key Rule |
|---|---|---|---|
| 1 | Cognitive Subject | `OpenClawd.process()` | Sole cognitive entry; must not be wrapped or replaced |
| 2 | Execution Decision | `_determine_execution_path()` / V4 (orchestration sessions only) | V4 ≠ per-request gate |
| 3 | Dispatch Authority | V3 fused into `CommandRouter.route_envelope()` | V3 is the single 10-dim legality gate |
| 4a | Local Execution | `HybridExecutionArbiter`, `DecisionExecutor` | First-class; must remain runnable |
| 4b | Distributed Participant | `android_bridge`, participant runtimes | Android = first impl, not the only one |
| 5 | Completion Truth | V2 chain + CC + V5 | V2 must be hardened; CC = sole resolution point |
| 6 | Boundary / Integrity | V6 startup/health/CI only | Must NOT enter request hot path |
| 7 | Protocol Truth | AIP protocol schema | All declared paths must be consumed or retired |

---

## Role Assignments (frozen)

### Cognitive spine
- `OpenClawd.process()` — cognitive entry point (do not modify structure)
- `UnifiedLLMRouter` — LLM route selection (receives L1/L2/L3 as fused gates)
- `L4 GalaxyMainLoopL4Enhanced` — outer autonomous loop (NOT per-request gate)

### Dispatch authority chain
- `V3 canonical_dispatch_slot_authority` — dispatch legality (10 dimensions, P0: wire into CommandRouter)
- `CommandRouter.route_envelope()` — dispatch substrate (receives V3, not replaced)
- `V1 unified_continuity_legality_authority` — continuity legality (via V3 + direct result-ingress P1)
- `V4 unified_orchestration_spine` — multi-step orchestration sessions ONLY

### Completion truth backbone
- `V2 task_result_canonical_truth_chain` — 4-step truth chain (P1: harden steps 1–3)
- `CanonicalCompletionIngress` — sole completion resolution point
- `V5 canonical_group_completion_closure` — group/delegated terminal semantics

### Cognitive authority chain (fuse into `UnifiedLLMRouter`, P2)
- `L1 LLMRouteAuthority` → route selection gate
- `L2 LLMSupplyAuthority` → supply availability gate
- `L3 CognitiveContextAuthority` → context enrichment gate

### Android participant truth and lifecycle
- `A1 android_participant_truth_ingress` — V2 Step 1 (keep + generalize interface P3)
- `A2 android_execution_signal_reconciler` — V2 Step 2 (keep as-is)
- `A3 android_delegated_runtime_lifecycle_coordinator` — delegated lifecycle facade (keep as-is)
- `A4 android_v2_continuity_contract` — continuity policy / test layer (boundary only)

### Boundary / startup integrity
- `V6 center_authority_boundary` — startup Phase 7 + health endpoint + CI gate only

---

## Confirmed Capabilities (must be preserved)

| Capability | Confirmed By |
|---|---|
| Local execution | `local_execution_chain.py`, `hybrid_executor.py` |
| Cross-device execution | `cross_device_execution_chain.py`, `command_router.py`, `android_bridge.py` |
| Delegated / handoff / takeover | `android_bridge` handlers, `A3` coordinator |
| Multi-device grouped | `multi_device_coordination_authority.py`, V5, `MultiDeviceCoordinator.kt` |
| Replay / recovery | `replay_foundation.py`, `runtime_restart_recovery.py` |
| Session continuity | `conversation_continuity_truth.py`, `android_v2_continuity_contract.py` |

---

## Implementation Priority Queue

| Priority | Item | Action |
|---|---|---|
| P0 | V3 → `CommandRouter` fusion | Wire `get_canonical_dispatch_slots()` as pre-dispatch step (~20 lines, additive) |
| P0 | V4 scope enforcement | Confirm V4 NOT in `OpenClawd.process()` hot path; scope to orchestration sessions |
| P1 | V2 truth chain hardening | Replace `try/except` Steps 1–3 with hard enforcement |
| P1 | V1 result-ingress pre-check | Add `evaluate_continuity_legality(RESULT_INGRESS)` before V2 chain in `handle_task_result()` |
| P2 | L1/L2/L3 → `UnifiedLLMRouter` fusion | Fuse as pre-selection gates inside `UnifiedLLMRouter.select_route()` |
| P2 | V6 startup call | Add `assert_center_authority_intact()` to `SystemOrchestrator` Phase 7 |
| P3 | Participant interface generalization | Define `ParticipantTruthIngressProtocol`; A1 implements it |
| P3 | `ParticipantTruthKind` base enum | Android enum extends it |
| P3 | V6 import update | Reference generic `participant_truth_ingress` |
| P3 | `CanonicalCompletionIngress` docstring | "participant result" not "Android handoff result" |

---

## Non-Negotiable Rules (summary)

1. System remains center-distributed (center holds dispatch/session/completion truth).
2. Local and cross-device execution are both first-class, both preserved.
3. Multi-device, delegated, replay, continuity capabilities are production features — not removable.
4. Participant model is architecturally generic; Android is a concrete realization, not the definition.
5. `OpenClawd.process()` is the cognitive spine — do not replace, wrap, or bypass.
6. `CommandRouter.route_envelope()` is the dispatch substrate — do not replace.
7. V3 is the canonical dispatch legality authority — fuse into `CommandRouter`, not alongside it.
8. V4 governs multi-step orchestration sessions — not a per-request gate.
9. V6 is a boundary/startup/health layer — not a per-request gate.
10. L4 is the outer autonomous loop — not a per-request cognitive gate.
11. V2/V5/`CanonicalCompletionIngress` form the completion truth backbone — harden, do not weaken.
12. Protocol truth must equal runtime truth — retire dead declared protocol paths.

---

## Prohibited Patterns

| Prohibited | Reason |
|---|---|
| New wrapper around `OpenClawd.process()` | Splits cognitive entry point |
| V4 as synchronous per-request gate | Wrong scope — creates hot-path bloat and split-brain |
| V6 in request hot path | Category error — V6 is structural integrity, not runtime authority |
| New dispatch router claiming to replace `CommandRouter` | Destroys dispatch substrate |
| Android-only guards in dispatch admission | Violates participant generalizability |
| Removing local execution domain | Destroys local-first runtime capability |
| Removing multi-device / replay / handoff flows | Destroys confirmed production capabilities |
| New meta-authority coordinator above V3 + `CommandRouter` | Creates third authority layer |
| L4 inside `OpenClawd.process()` Stage 2 or 3 | L4 is outer loop, not inner cognitive gate |

---

*Frozen as of terminal dual-repository audit, 2026-04-30.*
