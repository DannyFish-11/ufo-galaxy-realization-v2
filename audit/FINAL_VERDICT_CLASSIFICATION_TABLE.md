# 最终裁决表 — Final Architecture Verdict Classification Table

> **Repository**: `DannyFish-11/ufo-galaxy-realization-v2` × `DannyFish-11/ufo-galaxy-android`  
> **Date**: 2026-04-30  
> **Basis**: Code-grounded evidence from both repositories. See `FINAL_ARCHITECTURE_VALIDATION_AUDIT.md` for full analysis.  
> **Companion**: `final_validation_probe.py` (run to validate key assumptions against actual code)

---

## How to Read This Table

**Verdict** column uses these five categories:

| Verdict | Meaning |
|---|---|
| ✅ KEEP AS-IS | Correct, on hot path, must not be modified by unification plan |
| 🔌 FUSE (WIRE IN) | Architecturally correct but not yet on hot path; wire into hot path |
| 🔬 BOUNDARY ONLY | Correct as policy/audit/health layer; must NOT be forced into per-request hot path |
| 🗑️ RETIRE | Dead, fake, or redundant; safe to remove |
| 🌐 GENERALIZE | Correct implementation but uses Android-specific naming for a generic concept |

**Priority** column: P0 (fix immediately) → P3 (cleanup/future)

---

## Part I: Authority Closure Modules (V1–V6)

| Module | Role Declared | Hot Path? | Verdict | Priority | Required Action |
|---|---|---|---|---|---|
| **V1** `unified_continuity_legality_authority` | Single 12-dimension continuity legality gate for all inbound-action paths | ❌ Not directly (only via V3 which is also not on hot path) | 🔌 FUSE (via V3 + direct result-ingress pre-check) | P0 (via V3 wiring) + P1 (result-ingress) | Wire V3 into CommandRouter → V1 auto-active for dispatch. Add direct `evaluate_continuity_legality(RESULT_INGRESS)` pre-check in `android_bridge.handle_task_result()` |
| **V2** `task_result_canonical_truth_chain` | 4-step canonical must-run truth chain for every `task_result` | ✅ YES — called in android_bridge | ✅ KEEP AS-IS (with hardening) | P1 | Harden: change `try/except` soft wrapping on steps 1-3 to hard enforcement. Step 4 (CC notification) remains idempotent best-effort |
| **V3** `canonical_dispatch_slot_authority` | 10-dimension single gate for ALL dispatch decisions | ❌ Not called by CommandRouter | 🔌 FUSE INTO CommandRouter | P0 | Wire `get_canonical_dispatch_slots()` into `CommandRouter.route_envelope()` as pre-dispatch step. ~20 lines, additive only |
| **V4** `unified_orchestration_spine` | Single entry point for ALL execution modes (mandatory pre-dispatch gate) | ❌ Not called by OpenClawd or CommandRouter (only by goal_execution handler) | 🔬 BOUNDARY ONLY (scoped to multi-step orchestration) | P2 | Do NOT force into per-request OpenClawd path. Remains the correct entry point for multi-step orchestration (parallel fan-out, delegated, wake-routed). Add assertion doc that V4 governs orchestration sessions, not per-task dispatch |
| **V5** `canonical_group_completion_closure` | Single canonical terminal state for group/delegated/fan-out completion | ✅ YES — called in group/delegated completion contexts | ✅ KEEP AS-IS | — | No change needed. Already correctly integrated |
| **V6** `center_authority_boundary` | Final structural closure declaring V2 as exclusive owner of 4 authority domains | ✅ Importable and callable, but not runtime-enforced | 🔬 BOUNDARY ONLY | — | Use `assert_center_authority_intact()` at: system startup, health endpoint, release gate CI. Do NOT wire into per-request hot path. Update import check to use generic `participant_truth_ingress` not `android_participant_truth_ingress` |

---

## Part II: Cognitive Authority Chain (L1–L4)

| Module | Role Declared | Hot Path? | Verdict | Priority | Required Action |
|---|---|---|---|---|---|
| **L1** `LLMRouteAuthority` | Route selection authority for LLM dispatch | ❌ Not called by OpenClawd or UnifiedLLMRouter | 🔌 FUSE INTO UnifiedLLMRouter | P2 | Add as pre-selection gate in `UnifiedLLMRouter.select_route()`. Do NOT insert into OpenClawd directly |
| **L2** `LLMSupplyAuthority` | LLM supply/availability authority | ❌ Not on hot path | 🔌 FUSE INTO UnifiedLLMRouter | P2 | Add as supply availability check in `UnifiedLLMRouter` before route execution |
| **L3** `CognitiveContextAuthority` | Cognitive context enrichment authority | ❌ Not on hot path | 🔌 FUSE INTO UnifiedLLMRouter | P2 | Add as context enrichment step in `UnifiedLLMRouter` (optional enrichment; degrade gracefully if unavailable) |
| **L4** `GalaxyMainLoopL4Enhanced` | Outer autonomous loop driver | ✅ YES — is the outer autonomous loop | ✅ KEEP AS-IS | — | Do NOT force into per-request OpenClawd.process() path. Is correctly the outer autonomous loop. L4 loop drives goal-level execution; OpenClawd handles per-request cognitive step |

---

## Part III: Android Integration Modules (A1–A4)

| Module | Role Declared | Hot Path? | Verdict | Priority | Required Action |
|---|---|---|---|---|---|
| **A1** `android_participant_truth_ingress` | Participant truth reconciliation into V2 canonical state (Step 1 of V2 chain) | ✅ YES — Step 1 in `run_task_result_truth_chain()` | ✅ KEEP AS-IS + GENERALIZE interface | P3 | Keep Android implementation. Define `ParticipantTruthIngressProtocol` abstract interface. Wire V2 Step 1 to call the generic interface |
| **A2** `android_execution_signal_reconciler` | Execution signal reconciliation (Step 2 of V2 chain) | ✅ YES — Step 2 in `run_task_result_truth_chain()` | ✅ KEEP AS-IS | — | No change needed. Correctly on hot path |
| **A3** `android_delegated_runtime_lifecycle_coordinator` | Single facade for all Android delegated lifecycle events | ✅ YES — called by gateway handlers for handoff/takeover/reconciliation events | ✅ KEEP AS-IS | — | No change needed. Correctly structured as lifecycle event facade |
| **A4** `android_v2_continuity_contract` | Joint Android-V2 continuity verification policy (7 scenarios) | 🔬 Policy document, not runtime hot path | 🔬 BOUNDARY ONLY | — | Keep as verification/test suite. Machine-checkable policy sentinels should be asserted in integration tests. Rename optionally to `participant_v2_continuity_contract.py` (P3) |

---

## Part IV: Core Runtime Spine

| Module | Role Declared | Hot Path? | Verdict | Priority | Required Action |
|---|---|---|---|---|---|
| `OpenClawd.process()` | Cognitive entry point, 4-stage: Ingest → Cognition → Branch → Manifest | ✅ YES — the real cognitive spine | ✅ KEEP AS-IS | P0 (do not modify) | Do NOT restructure. V4 must not replace `_determine_execution_path()`. L4 must not be inserted into Stage 2 or 3. This module is the highest-risk for accidental breakage |
| `CommandRouter.route_envelope()` | Canonical cross-device dispatch substrate | ✅ YES — the real dispatch spine | ✅ KEEP AS-IS + receive V3 pre-check | P0 | Wire V3 as additive pre-dispatch step only. Do not replace existing ACL gate logic. Existing 3 hard gates remain as secondary fallback |
| `DesktopPresenceRuntime` | Outer runtime shell, tri-state lifecycle | ✅ YES — outer runtime shell | ✅ KEEP AS-IS | — | No change needed |
| `galaxy_gateway/android_bridge.py` | AIP v3 center-side bridge | ✅ YES — handles all Android WS messages | ✅ KEEP AS-IS + add V1 pre-check on result ingress | P1 | Add `evaluate_continuity_legality(RESULT_INGRESS)` pre-check in `handle_task_result()` |
| `GalaxyMainLoopL4Enhanced` | Outer L4 autonomous loop | ✅ YES — outer loop | ✅ KEEP AS-IS | — | Is correctly the outer loop. Not a per-request gate |
| `HybridExecutionArbiter` | Three-level local fallback (A2A → GUI → VLM) | ✅ YES — local fallback helper | ✅ KEEP AS-IS | — | Not a parallel authority. Correctly bounded as local execution helper |
| `main.py` → `SystemOrchestrator` | 7-phase startup | ✅ YES — startup authority | ✅ KEEP AS-IS + add V6 check | — | Add `assert_center_authority_intact()` to Phase 7 (READINESS_SUMMARY) |

---

## Part V: Execution Chain Modules

| Module | Role Declared | Hot Path? | Verdict | Priority | Required Action |
|---|---|---|---|---|---|
| `local_execution_chain.py` | Canonical local execution chain documentation | ✅ Documented, chain exists | ✅ KEEP AS-IS | — | Both local and cross-device chains are first-class. Do not collapse into a single chain |
| `cross_device_execution_chain.py` | Canonical cross-device execution chain documentation | ✅ Documented, chain exists | ✅ KEEP AS-IS | — | V3 wiring benefits this chain directly |
| `delegated_flow_acceptance_gate.py` | Dimension 10 of V3 slot gate (delegated/handoff acceptability) | ✅ YES — via V3 composition | ✅ KEEP AS-IS | — | No change needed. V3 already delegates to it |
| `canonical_completion_ingress.py` | Future-based awaiter unblock on every participant result | ✅ YES — Step 4 in V2 chain | ✅ KEEP AS-IS | — | Update docstring: replace "Android handoff result" with "participant result" |
| `multi_device_coordination_authority.py` | Multi-device governance | ✅ YES — multi-device path | ✅ KEEP AS-IS | — | Preserve; V3 wiring will also validate multi-device targets |
| `replay_foundation.py` | Terminal-state event emission | ✅ YES — called from A1 reconciliation | ✅ KEEP AS-IS | — | No change needed |
| `unified_dispatch_readiness_gate.py` | Transport/registration/attachment/capability checks | ✅ YES — dimensions 1-3, 5, 9 of V3 | ✅ KEEP AS-IS | — | Already correctly used as V3 delegate |

---

## Part VI: Participant Model Naming (Generalization)

| Current naming | Problem | Verdict | Action | Priority |
|---|---|---|---|---|
| `android_participant_truth_ingress.py` (authority interface) | Android-named function in a device-agnostic truth chain | 🌐 GENERALIZE | Define `ParticipantTruthIngressProtocol` in new `core/participant_truth_ingress.py`; keep Android impl | P3 |
| `AndroidParticipantTruthKind` enum | Android-named in device-agnostic completion truth model | 🌐 GENERALIZE | Define `ParticipantTruthKind` base enum; extend as `AndroidParticipantTruthKind` | P3 |
| `android_participant_session_state.py` | Android-named state model | 🌐 GENERALIZE | Define `ParticipantSessionState` base dataclass | P3 |
| `android_runtime_host.py` | Android-named for generic runtime-host classification | 🌐 GENERALIZE | Define `ParticipantRuntimeHostClassifier` protocol or rename module | P3 |
| V6 import of `android_participant_truth_ingress` | Android-specific name in authority boundary | 🌐 GENERALIZE | Update to reference generic `participant_truth_ingress` | P3 |
| `canonical_completion_ingress.py` docstring | Says "Android handoff result" in generic Future module | 🌐 GENERALIZE (minor) | Update docstring to "participant result" | P3 |

---

## Part VII: What to Retire

| Element | Retirement reason | Risk if left as-is |
|---|---|---|
| `hybrid_execute` protocol stub (if dead protocol declaration exists with no dispatcher) | Protocol declared but no dispatcher calls it | None (dead code); retire to remove confusion |
| Android governance uplink message types with zero center-side consumers (if any exist) | Dead protocol wire | Low; remove to prevent future confusion |
| Legacy dispatch path declarations in `orchestration_authority/legacy_paths.py` | Formally demoted by `cross_device_execution_chain.py` | Low; retire after V3 is confirmed live |
| Any `try/except: pass` blocks in V2 truth chain steps | Silently absorbs truth chain failures | HIGH — must be replaced by hard enforcement |

---

## Part VIII: Split-Brain Resolution Status After Each Phase

### After Phase 1 (P0 + P1 changes)

| Split-brain | Before | After Phase 1 |
|---|---|---|
| V3 dispatch gate vs. CommandRouter | Shadow authority | **RESOLVED** — V3 live in CommandRouter |
| V1 continuity gate vs. CommandRouter ad-hoc checks | Parallel duplication | **RESOLVED** — V1 active via V3 dimension 4 |
| V1 continuity gate vs. result-ingress (no gate) | Missing gate | **RESOLVED** — direct V1 pre-check on result ingress |
| V2 truth chain soft vs. hard enforcement | Best-effort only | **RESOLVED** — steps 1-3 hard-enforced |

### After Phase 2 (P2 changes)

| Split-brain | Before | After Phase 2 |
|---|---|---|
| L1-L3 cognitive authority vs. UnifiedLLMRouter direct call | Shadow authority | **RESOLVED** — L1-L3 active in UnifiedLLMRouter |
| V4 "all execution modes must use me" vs. per-request dispatch | Control conflict | **RESOLVED** — V4 scoped to multi-step orchestration only; conflict claim removed |

### After Phase 3 (P3 changes)

| Naming issue | Before | After Phase 3 |
|---|---|---|
| Android-named participant truth interface | Android-specific | **RESOLVED** — generic interface with Android implementation |
| V6 boundary check references Android module | Android-coupled | **RESOLVED** — generic reference |

### After Phase 4 (Tests)

All 8 tests listed in `FINAL_ARCHITECTURE_VALIDATION_AUDIT.md` Section 6.6 pass.

### After Phase 5 (Retirement)

Dead protocol stubs and legacy dispatch paths removed.

**System state after all phases: Fully closed, non-split-brain, center-distributed, participant-generic, capability-preserving architecture.**

---

## Compressed Summary (One-Line Per Module)

```
V1 continuity legality    → FUSE (auto via V3) + direct result-ingress pre-check   [P0+P1]
V2 truth chain            → KEEP + harden enforcement                               [P1]
V3 dispatch slot gate     → FUSE INTO CommandRouter (single 20-line wiring change)  [P0]
V4 orchestration spine    → BOUNDARY (multi-step orchestration only, not per-req)   [P2 doc]
V5 group completion       → KEEP AS-IS                                              [done]
V6 center boundary        → BOUNDARY (startup + health + release gate)              [doc]
CC completion ingress     → KEEP AS-IS (update docstring)                           [done]
A1 participant truth      → KEEP + generalize interface                             [P3]
A2 execution reconciler   → KEEP AS-IS                                              [done]
A3 lifecycle coordinator  → KEEP AS-IS                                              [done]
A4 continuity contract    → BOUNDARY (verification/test suite)                     [done]
L1 route authority        → FUSE INTO UnifiedLLMRouter                             [P2]
L2 supply authority       → FUSE INTO UnifiedLLMRouter                             [P2]
L3 context authority      → FUSE INTO UnifiedLLMRouter                             [P2]
L4 main loop enhanced     → KEEP AS-IS (outer loop, not per-request gate)          [done]
CommandRouter             → KEEP + receive V3 pre-check                             [P0]
OpenClawd.process()       → KEEP EXACTLY AS-IS (highest risk if modified)          [PROTECTED]
android_bridge            → KEEP + add V1 result-ingress pre-check                 [P1]
hybrid_executor           → KEEP AS-IS (correctly bounded local fallback)           [done]
multi_device_coordination → KEEP AS-IS                                              [done]
replay_foundation         → KEEP AS-IS                                              [done]
legacy dispatch paths     → RETIRE after V3 confirmed live                         [P5]
hybrid_execute dead stubs → RETIRE                                                  [P5]
participant naming        → GENERALIZE (interface-level, Android impl kept)         [P3]
```
