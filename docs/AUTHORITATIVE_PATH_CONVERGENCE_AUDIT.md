# Authoritative Path Convergence Audit
## PR-convergence — Enforce Single Authoritative Path and Default-Off Legacy Behavior

**Repository:** `DannyFish-11/ufo-galaxy-realization-v2`  
**Companion context:** `DannyFish-11/ufo-galaxy-android`  
**PR goal:** Make the canonical path the real default authoritative runtime path and
ensure legacy/compat paths are default-off.

---

## 1. Summary

This audit covers the convergence of the Galaxy V2 runtime to a **single
authoritative path** and the enforcement of **default-off legacy behavior**.
Prior PRs (PR-8 through PR-M) established blocking machinery and legacy
registries.  This PR proves that the canonical path is the actual default and
that legacy paths are default-off by providing a machine-readable path inventory
and enforcement helpers.

---

## 2. Canonical Path Inventory

All paths are recorded in `core/canonical_authoritative_path_convergence.py ::
CANONICAL_PATH_INVENTORY`.  The five roles are:

| Role | Meaning |
|---|---|
| `canonical` | The one legitimate default authority path |
| `compat_allowed` | Explicitly bounded compat path, limited scope |
| `observation_only` | Read-only observer; MUST NOT write canonical state |
| `deprecated_live` | Default-off; executing for compat only, pending removal |
| `fully_blocked` | Blocked; must not reach canonical surfaces |

### 2.1 Canonical paths (the authoritative default)

| Path ID | Description |
|---|---|
| `core.command_router.CommandRouter.route_envelope` | Canonical dispatch spine — sole routing authority |
| `core.e2e_orchestrator.process_user_input` | Canonical user-request ingress |
| `galaxy_gateway.device_router.DeviceRouter.route_task` | Canonical single dispatch entry for device-bound tasks (PR-S3) |
| `core.android_participant_truth_ingress.ingest_android_participant_truth_message` | Canonical Android truth ingress gate (sole write authority for Android → V2 truth) |
| `core.android_participant_truth_ingress.reconcile_android_participant_truth` | Canonical reconciler for Android participant truth (closes TRUTH-005) |
| `core.android_delegated_signal_ingress.ingest_delegated_execution_signal` | Canonical ingress for delegated_execution_signal messages (post-PR-16) |
| `core.android_execution_signal_reconciler.reconcile_android_execution_signal` | Canonical reconciler for execution signals (ACK/PROGRESS/RESULT/ERROR) |
| `core.delegated_flow_acceptance_gate.DelegatedFlowAcceptanceGate` | Canonical accept/reject gate for delegated flows |
| `core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate` | Canonical readiness gate for delegated flows |

### 2.2 Compat-allowed paths (bounded scope)

| Path ID | Scope | Canonical Replacement |
|---|---|---|
| `core.android_execution_signal_reconciler.compat_extract_signal_kind` | Pre-PR-16 Android clients only; MUST NOT be default for post-PR-16 clients | `core.android_delegated_signal_ingress.ingest_delegated_execution_signal` |
| `core.android_handoff_v2_response_ingress.ingest_android_handoff_response` | Bounded to HandoffEnvelopeV2 response handling | `core.delegated_flow_entity.DelegatedFlowEntity (result convergence)` |

### 2.3 Observation-only paths (non-authoritative)

| Path ID | What it observes |
|---|---|
| `core.android_delegated_runtime_audit.AndroidDelegatedRuntimeAuditRecord` | Lifecycle milestones for Android delegated runtime events |
| `core.operator_surface.OperatorSurface` | Canonical state for monitoring |
| `core.replay_foundation.ReplayFoundation` | Canonical state transitions for audit/replay |

**Policy:** Observation-only paths MUST NOT write to canonical task truth,
session truth, readiness verdict, or delegated-flow state.

### 2.4 Deprecated-live paths (default-off, pending removal)

| Path ID | PR | Canonical Replacement |
|---|---|---|
| `galaxy_gateway.task_router.TaskRouter` | PR-S6 | `DeviceRouter.route_task` |
| `galaxy_gateway.handlers.message_handler.MessageHandler` | PR-S6 | websocket_handler → DeviceRouter (chain A) |
| `galaxy_gateway.task_decomposer.TaskDecomposer` | PR-S7 / PR-516 | `core.task_graph.TaskGraph` |
| `galaxy_gateway.task_decomposer.IntelligentTaskPlanner` | PR-S7 / PR-516 | `core.e2e_orchestrator.process_user_input` |
| `galaxy_gateway.smart_transport_router.SmartTransportRouter` | PR-M | `DeviceRouter.route_task` |
| `galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2` | PR-M | `core.e2e_orchestrator.process_user_input` |
| `galaxy_gateway.session_roaming.SessionRoamingManager` | PR-M | `core.canonical_session_axis + core.attached_runtime_session` |

**Policy (DEFAULT_OFF_LEGACY_BEHAVIOR_V1):** These paths are off by default.
`is_legacy_default_off(path_id)` returns `True` for all of them.  They may
only execute when the canonical path is explicitly unavailable AND a formal
`CompatLegacyBlockingRecord` artifact has been produced by the PR-8 gate.

### 2.5 Fully blocked paths

| Path ID | Block Reason |
|---|---|
| `galaxy_gateway.task_router.TaskRouter.direct_http_dispatch` | Raw-HTTP inner loop must not reach canonical routing surfaces |
| `core.android_participant_truth_ingress.direct_canonical_state_write_from_compat_signal` | Android compat signals must not directly write V2 canonical state (bypass of ingress gate) |
| `galaxy_gateway.orchestrator.task_orchestrator.TaskOrchestrator.direct_dispatch` | Direct dispatch bypassing DeviceRouter and CommandRouter |

**Policy (LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_V1):** Any invocation of a
fully-blocked path at a canonical surface produces a `block_due_to_legacy_dispatch`
artifact from the PR-8 gate and must not proceed.

---

## 3. Blocking Enforcement Evidence

### 3.1 PR-8 gate (compat_legacy_path_blocking_canonicalization.py)
- `enforce_canonical_gate()` is the runtime gate that every compat/legacy
  influence must cross.
- Blocking-first by default: silence is denial.
- Produces `CompatLegacyBlockingRecord` for every decision.
- Five outcomes: `canonical_path_confirmed`, `allow_for_observation_only`,
  `block_due_to_legacy_dispatch`, `block_due_to_compat_truth_influence`,
  `quarantine_due_to_ambiguous_contract`.

### 3.2 PR-convergence gate (canonical_authoritative_path_convergence.py)
- `enforce_canonical_selection()` MUST be called at every canonical routing,
  truth, and delegated-flow handoff decision surface.
- Returns `CanonicalSelectionRecord` with `enforcement_active=True` when
  legacy paths were present and the canonical path was correctly preferred.
- `is_legacy_default_off(path_id)` returns `True` for deprecated_live and
  fully_blocked paths — confirming the default-off property.

### 3.3 Legacy dispatch registry (legacy_dispatch_registry.py)
- `check_dispatch_blocked(module)` integrates PR-8 blocking gate with the
  legacy dispatch registry.
- Every registered legacy dispatch path that reaches a canonical surface must
  produce a `CompatLegacyBlockingRecord`.

---

## 4. Android Companion Compat Influence Review

### 4.1 How Android-side compat/legacy influence reaches V2
Android-side compat/legacy participant signals enter V2 through three channels:

1. **`delegated_execution_signal` messages** (post-PR-16 canonical path) →
   `ingest_delegated_execution_signal()` → `reconcile_android_execution_signal()`.
2. **Legacy message types** (`task_result`, `task_end`, `goal_execution_result`)
   for pre-PR-16 clients → `compat_extract_signal_kind()` (compat-allowed,
   bounded fallback) → `reconcile_android_execution_signal()`.
3. **Participant/session/runtime truth** (`session_snapshot`, `readiness_assessment`,
   `task_phase`, `runtime_state`) → `ingest_android_participant_truth_message()` →
   `reconcile_android_participant_truth()`.

### 4.2 V2-side safeguards for Android compat influence

| Safeguard | Description |
|---|---|
| **Participant truth ingress gate** | `ingest_android_participant_truth_message()` is the sole write authority for Android → V2 truth; direct writes bypassing this gate are fully blocked |
| **compat_extract_signal_kind boundary** | Bounded to pre-PR-16 clients only; post-PR-16 clients must use `ingest_delegated_execution_signal()` |
| **PR-8 blocking gate** | All Android compat influence crossing a canonical surface produces a `CompatLegacyBlockingRecord` |
| **Observation-only audit records** | `AndroidDelegatedRuntimeAuditRecord` is classified observation-only; it may not write canonical state |

### 4.3 V2 assumptions about Android-side behavior
- Android post-PR-16 clients emit `delegated_execution_signal` with structured
  `signal_kind`, `result_kind`, `signal_id`, and `emission_seq` fields.
- Android sends `reconciliation_signal` for readiness/governance artifact reporting
  (wire path established PR-7V2).
- Android uses `handoff_envelope_v2` as the canonical downlink type; `handoff_dispatch`
  is the legacy type that must not be the default V2 output.
- Android compat participants report compat influence through
  `reconciliation_signal` → V2 participant truth ingress → canonical gate.

---

## 5. What was tightened or blocked in this PR

| Area | Change |
|---|---|
| **Canonical path inventory** | Created `CANONICAL_PATH_INVENTORY` — first machine-readable single surface classifying all runtime paths |
| **Default-off legacy** | `is_legacy_default_off()` function proves 7 deprecated_live paths and 3 fully_blocked paths are default-off |
| **Android compat boundary** | `ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY` formally codifies the V2 truth ingress gate requirement |
| **Observation-only classification** | 3 audit/monitoring paths explicitly classified as non-authoritative |
| **Legacy dispatch registry** | Added PR-convergence entries for Android ingress gates, delegated flow gates, and observation-only surfaces |
| **Purge registry** | Added 4 PR-convergence entries recording convergence decisions |
| **Enforcement helper** | `enforce_canonical_selection()` provides a runtime primitive that MUST be called at canonical surfaces |

---

## 6. What remains intentionally deferred

| Area | Deferred Work | Reason |
|---|---|---|
| **E2E test matrix** | Full ReconciliationSignal, HandoffEnvelopeV2, and delegated execution round-trip tests | Requires live device / Android simulator; out of scope for this PR |
| **CI/release blocking** | Readiness verdict integration into CI release pipeline | Depends on readiness gate E2E verification (later PR) |
| **Governance auto-rollback** | Governance violation → automatic rollback | Post-graduation governance PR |
| **Full takeover executor** | `AipModels.kt pr3 — full takeover executor deferred to PR-5` | Android-side implementation; not V2 primary |
| **Legacy path deletion** | Physical removal of deprecated_live paths | Requires all callers to have migrated; tracked separately |
| **Offline durability recovery** | Signal replay → V2 canonical state re-convergence validation | Requires offline test harness |

---

## 7. How a reviewer can verify

1. **Canonical path is the default** →
   `CANONICAL_PATH_INVENTORY["core.command_router.CommandRouter.route_envelope"].role == CanonicalPathRole.canonical`

2. **Legacy paths are default-off** →
   `is_legacy_default_off("galaxy_gateway.task_router.TaskRouter") is True` (and similarly for all 7 deprecated_live + 3 fully_blocked paths)

3. **Blocking is actually enforced** →
   `enforce_canonical_gate()` in `core/compat_legacy_path_blocking_canonicalization.py`
   is blocking-first; `check_dispatch_blocked()` in `core/legacy_dispatch_registry.py`
   is the convenience connector; `enforce_canonical_selection()` in this PR is the
   canonical surface enforcement primitive.

4. **Canonical truth less vulnerable to legacy influence** →
   `ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY` blocks direct Android
   compat writes; `direct_canonical_state_write_from_compat_signal` is `fully_blocked`.

5. **What is deferred** → Section 6 above and `PURGE_REGISTRY` entries with `pr="PR-convergence"`.

---

*Generated by PR-convergence (enforce-single-authoritative-path).*
