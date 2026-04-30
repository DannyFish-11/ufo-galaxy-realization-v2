# Architecture Freeze — Implementation Guardrails

> **Status**: FROZEN — binding enforcement rules for all follow-up implementation PRs  
> **Version**: V1.0  
> **Date**: 2026-04-30  
> **Parent document**: `UNIFIED_CENTER_DISTRIBUTED_RUNTIME_ARCHITECTURE_FREEZE_V1.md`  
> **Scope**: Rules that every implementation PR in the unification sequence must satisfy

---

## Purpose

This document provides the concrete per-PR guardrails derived from the architecture freeze. It translates the high-level architectural principles into specific, checkable rules. Any PR reviewer can use this document to determine whether a proposed change complies with the frozen architecture.

These rules are not suggestions. They are binding constraints derived from the terminal dual-repository audit.

---

## Rule Set 1 — Spine Preservation

### R1.1 — Do not modify `OpenClawd.process()` structural stages

The four-stage structure of `OpenClawd.process()` (Ingest → Cognition → Branch → Manifest) must not be altered by any PR that is not explicitly approved as a cognitive-spine change. Changes to `OpenClawd` require explicit justification explaining why no alternative was possible.

**Check**: Diff must not restructure the stage sequence or remove `_determine_execution_path()`.

### R1.2 — Do not replace `CommandRouter.route_envelope()`

`CommandRouter.route_envelope()` is the dispatch substrate. No PR may introduce a new dispatch entry point that claims to replace or supersede it. New dispatch logic must be fused into `route_envelope()` as additive steps, not placed in a new parallel router.

**Check**: Diff must not introduce a new class with `route_` methods claiming to own dispatch authority.

### R1.3 — Fuse authority into existing substrates; do not replace them

When adding authority enforcement (V3, L1/L2/L3, V1), the enforcement must be added as an additive step inside the existing substrate module. It must not be placed in a new wrapper class that intercepts calls before reaching the substrate.

**Check**: New authority calls appear inside existing method bodies, not as new outer interceptors.

---

## Rule Set 2 — Layer Boundary Enforcement

### R2.1 — V4 must not appear in `OpenClawd.process()` or `CommandRouter.route_envelope()`

V4 (`unified_orchestration_spine`) governs multi-step orchestration sessions. It must not be called synchronously as a per-request gate in `OpenClawd.process()` or `CommandRouter.route_envelope()`.

**Check**: Search for `unified_orchestration_spine` or `UnifiedOrchestrationSpine` in diffs affecting `openclawd.py` or `command_router.py`. Any such import or call is a guardrail violation.

### R2.2 — V6 must not appear in request hot paths

V6 (`center_authority_boundary`) must only be called at system startup (Phase 7), health endpoints, and CI release gates. It must not be called inside `OpenClawd.process()`, `CommandRouter.route_envelope()`, or any per-request handler.

**Check**: Search for `center_authority_boundary` or `assert_center_authority_intact` in diffs affecting hot-path modules. Calls inside request handlers are violations.

### R2.3 — L4 must not appear in `OpenClawd.process()` stages 1–3

L4 (`GalaxyMainLoopL4Enhanced`) is the outer autonomous loop. It drives goal-level execution from outside. It must not be imported into or called from within `OpenClawd.process()` stages 1–3.

**Check**: Search for `GalaxyMainLoopL4Enhanced` or `galaxy_main_loop_l4` imports in `openclawd.py`. Any such import is a violation.

---

## Rule Set 3 — Execution Domain Preservation

### R3.1 — Do not remove local execution capability

No PR may stub out, disable, or remove `HybridExecutionArbiter` or the `_determine_execution_path() → "local"` branch. The local execution domain must remain runnable.

**Check**: `_determine_execution_path()` must still contain a branch that routes to `DecisionExecutor` / `HybridExecutionArbiter`.

### R3.2 — Do not remove cross-device dispatch

No PR may disable or stub out `CommandRouter.route_envelope()` or the `galaxy_gateway/android_bridge.py` handlers. Cross-device dispatch must remain runnable.

**Check**: `android_bridge.handle_task_result()` must not be removed or turned into a no-op.

### R3.3 — Do not remove multi-device, delegated, handoff, replay, or continuity flows

No PR may stub out or remove:
- `android_bridge.handle_handoff_envelope_v2()`
- `android_bridge.handle_takeover_response()`
- `android_bridge.handle_reconciliation_signal()`
- `canonical_group_completion_closure.py` (V5)
- `replay_foundation.py`
- `multi_device_coordination_authority.py`

**Check**: These functions must remain present and non-stub in any PR diff.

---

## Rule Set 4 — Authority Model Integrity

### R4.1 — V3 must be the single dispatch legality authority

Once V3 is wired into `CommandRouter`, no second dispatch legality check may be introduced in any other location claiming to own dispatch legality. The only permitted addition is additive V3 sub-dimension delegates.

**Check**: After V3 wiring PR, no new `is_dispatch_legal()` / `check_dispatch_eligibility()` functions may appear outside V3 or its declared delegates.

### R4.2 — Do not create a new meta-authority coordinator above V3 + `CommandRouter`

No PR may introduce a new class that wraps both V3 and `CommandRouter` and claims to be the "true" dispatch authority. This would create a third authority layer.

**Check**: Diffs must not introduce `*Authority` / `*Coordinator` / `*Spine` classes that import both `canonical_dispatch_slot_authority` and `CommandRouter` and call them in sequence.

### R4.3 — Completion truth must flow through `CanonicalCompletionIngress`

No PR may introduce an alternative completion resolution path that bypasses `CanonicalCompletionIngress.notify()`. All result paths must eventually call `notify()` to resolve the associated Future.

**Check**: New result-handling paths in `android_bridge.py` or any future participant bridge must include a `CanonicalCompletionIngress.notify()` call.

---

## Rule Set 5 — Participant Model Rules

### R5.1 — Do not hardcode "Android" at the participant interface level

New code that reasons about participant truth ingress, participant session state, or participant runtime classification must use or define participant-generic abstractions. Android-specific implementations must remain as concrete implementations below a generic interface.

**Check**: New modules in `core/` with `android_` prefixes that claim to own participant-generic authority are violations. Refactors of existing Android modules must first define the generic protocol.

### R5.2 — Do not narrow participant runtime admission to Android-only

Dispatch decision logic, target admissibility checks, and readiness evaluation must not add Android-specific guards that prevent non-Android participant runtimes from being admitted.

**Check**: New capability/readiness checks must not include `device_type == "android"` as a hard filter.

### R5.3 — Generalize before renaming concrete implementations

When generalizing Android-named modules (A1, A4, session state, runtime host classifier), the following order must be followed:
1. Define the generic abstract interface / protocol.
2. Wire the hot path to call the generic interface.
3. Ensure Android implementation conforms to the generic interface.
4. Only then optionally rename or refactor the Android-specific module.

**Check**: PRs that rename `android_participant_truth_ingress.py` without first introducing a `ParticipantTruthIngressProtocol` are violations.

---

## Rule Set 6 — Protocol Truth Rules

### R6.1 — Do not declare new protocol message types without a corresponding consumer

Every new message type added to the AIP protocol schema must have a corresponding handler on the receiving end. The handler must be present in the same PR or a tracked follow-up PR with an explicit tracking issue.

**Check**: New entries in `AipModels.kt` or `android_bridge.py` message-type routing tables must have corresponding handler stubs or implementations.

### R6.2 — Do not leave retired protocol paths active

When a protocol path is confirmed dead (emitter present, consumer absent), the PR that retires it must remove both the emission point and the declared protocol entry. Dead stubs must not remain.

**Check**: "Dead protocol path" retirement PRs must touch both sides: the emitting end and the receiving end.

---

## Rule Set 7 — Additive-Only Rule for P0 Fusions

The P0 fusion items (V3 wiring into `CommandRouter`, V2 hardening, V1 result-ingress pre-check) must be implemented as additive changes only.

### R7.1 — V3 wiring is additive

The V3 pre-dispatch step in `CommandRouter.route_envelope()` must be placed before the existing ACL gate. The existing ACL gate, circuit-breaker, and retry logic must be preserved unchanged. If V3 returns a rejection, `route_envelope()` must return an error before reaching the existing gate — but the existing gate must not be removed.

### R7.2 — V2 hardening is additive

Hardening the V2 truth chain means replacing `try/except` soft wraps with hard enforcement on Steps 1–3. Step 4 (CC notification) remains idempotent best-effort. The chain structure (4 steps, same modules) must not change.

### R7.3 — V1 result-ingress pre-check is additive

The V1 `evaluate_continuity_legality(RESULT_INGRESS)` call in `handle_task_result()` must be placed before entering `run_task_result_truth_chain()`. If V1 rejects the result, the chain must return early. The V2 chain itself must not be modified to embed V1 logic.

---

## Checklist for PR Authors

Before submitting a unification PR, verify:

- [ ] I did not modify the structure of `OpenClawd.process()` without explicit justification.
- [ ] I did not replace `CommandRouter.route_envelope()` with a new dispatcher.
- [ ] I did not insert V4 as a synchronous gate in `OpenClawd.process()` or `CommandRouter`.
- [ ] I did not insert V6 into any per-request handler.
- [ ] I did not insert L4 into `OpenClawd.process()` stages 1–3.
- [ ] Local execution capability (`_determine_execution_path() → "local"`) is still present.
- [ ] `android_bridge.handle_task_result()`, `handle_handoff_envelope_v2()`, `handle_takeover_response()`, `handle_reconciliation_signal()` are still present and functional.
- [ ] V5, `replay_foundation.py`, and `multi_device_coordination_authority.py` are still present.
- [ ] New participant-level code uses or defines participant-generic abstractions.
- [ ] New protocol message types have corresponding consumers.
- [ ] My changes are additive to existing substrates, not replacements.
- [ ] `CanonicalCompletionIngress.notify()` remains the sole completion resolution point for any new result path I introduced.

---

## Checklist for PR Reviewers

When reviewing a unification PR:

- [ ] Check that no new wrapper class intercepts `OpenClawd.process()` or `CommandRouter.route_envelope()`.
- [ ] Check that V4, V6, L4 do not appear in per-request hot-path diffs.
- [ ] Check that the local execution branch is still present in `_determine_execution_path()`.
- [ ] Check that multi-device, delegated, handoff, and replay handlers are still present.
- [ ] Check that new participant-level abstractions follow the generalize-then-rename order.
- [ ] Check that new protocol entries have declared consumers.
- [ ] Verify that the PR's changes are additive and do not remove existing authority or substrate logic.

---

*These guardrails are frozen as of the terminal dual-repository audit dated 2026-04-30. They are binding for all PRs in the unification sequence.*
