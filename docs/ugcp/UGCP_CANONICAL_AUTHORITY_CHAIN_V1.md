# UGCP Canonical Authority Chain v1 (PR-3 realization-v2)

This document freezes the **canonical control-plane authority chain** for realization-v2 and explicitly demotes known compat/bypass surfaces.

## 1) Canonical authority sequence

Control-plane semantics must flow in this order:

1. **Canonical ingress + normalization**
   - `core.execution_spine.normalize_ingress_to_envelope`
   - `core.execution_spine.route_via_spine`
   - `core.command_router.CommandRouter.route_envelope`
2. **Command routing + source dispatch**
   - `core.command_router.CommandRouter.route_envelope`
   - `core.runtime.source_dispatch_orchestrator`
3. **Takeover / handoff execution authority**
   - `core.runtime.target_takeover`
   - canonical handoff contract/envelope path
   - transfer-profile transition mapping (`core.ugcp_control_transfer_profile`)
   - coordination-profile mapping for mesh/coordinator lifecycle + authority (`core.ugcp_coordination_profile`)
4. **Session truth authority**
   - `core.canonical_session_truth.record_session_truth`
   - transfer transition truth events (`TruthEvent` via `build_control_transfer_truth_event(...)`)
   - coordination transition truth events (`TruthEvent` via `build_coordination_truth_event(...)`)
5. **Durable snapshot + read-model surfaces**
   - `contracts.runtime_session_snapshot.RuntimeSessionSnapshot`
   - coordination durable snapshots (`build_coordination_durable_snapshot(...)`) for mesh/coordinator read models
   - projection/read APIs remain read-only surfaces

## 2) Ingress expectations (normative)

- New control-plane entry paths MUST enter `CommandRouter.route_envelope` (directly or through `route_via_spine`).
- Compat entry paths may remain temporarily, but must:
  - emit structured legacy guardrails, and
  - be documented as non-authoritative adapter surfaces.

## 3) Bypass fencing status (incremental)

- `CommandRouter.route_command` is a **compat shim** only.
- `core.routes.tasks.create_task` is a **compat route adapter** only.
- Both are explicitly registered in `core.orchestration_authority.legacy_paths`.

## 4) Truth boundary (normative)

- `canonical_session_truth` is the write authority for control-plane truth semantics.
- Projection / interop / compat / bridge labels are non-authoritative surfaces and must not become truth origins.
- Non-canonical `truth_source` labels are downgraded to canonical-safe `unknown`.

## 5) Scope note

This is an incremental hardening step. It does not claim all historical bypass paths are fully removed yet; it freezes and enforces the canonical chain while explicitly fencing remaining compat surfaces.
