# V2 Unified State Contract

This document defines the first executable V2-side state contract beneath the
existing top-level readiness/aggregation surface.

Authoritative builder:

- `core/v2_unified_state_contract.py`

Primary outward-facing consumer:

- `core/operational_readiness_surface.py`
- `GET /api/v1/projection/operational-readiness`
- `GET /api/v1/projection/clone-to-use-acceptance`

## Purpose

The existing operational readiness surface already aggregates many useful
signals, but its original emphasis is summary/reporting. The unified state
contract makes the lower-level semantics explicit so later PRs can reuse stable
meaning instead of re-inferring it from top-level summaries.

This contract is intentionally **V2-side only**. It does **not** claim Android
symmetry yet. Android remains a source of evidence and participation truth, not
an already-symmetric evaluator.

## Contract shape

The contract is split into four explicit layers:

1. `raw_signals`
   - direct observational evidence
   - counts, booleans, route presence, runtime verdicts, closure observations
2. `derived_state`
   - registration state
   - capability visibility
   - operational readiness
   - active path
   - compat-only / degraded path
   - recovery-active state
   - main-chain availability
   - cross-device availability
   - session continuity
3. `acceptance_state` and `eligibility_state`
   - what is acceptable on current V2 evidence
   - whether task initiation is currently eligible
4. `closure_quality_state`
   - result closure state
   - success quality
   - verdict quality
   - blocked / waiting-dependency / incomplete flags

This separation is the core semantic rule:

- **observable** = present in `raw_signals`
- **acceptable** = present in `acceptance_state`
- **eligible** = present in `eligibility_state`
- **active** = explicit `active` field on relevant derived decisions
- **complete** = explicit `complete` field on closure decisions

## Source fragments

The contract does not create new truth owners. It derives from existing V2
source fragments:

- `core/operational_registration_path.py`
  - registration kinds
  - onboarding validation
  - path tiers
- `core/runtime_readiness_matrix.py`
  - runtime verdict and blocked/degraded semantics
- `core/system_final_acceptance_verdict.py`
  - acceptance/verdict quality fragment
- `core/device_readiness.py`
  - cross-device ready device fragment
- `core/android_device_state_store.py`
  - capability visibility and degraded Android truth fragment
- `core/attached_runtime_session_registry.py`
  - attached session continuity fragment
- `core/android_participant_session_state.py`
  - task initiation, closure, and recovery/reconciliation fragment
- `core/unified_result_ingress.py`
  - closure-quality companion fragment

Each derived decision also carries its own `sources` list in the payload so
downstream consumers can see exactly which modules contributed to the result.

## Major derivation rules

## Registration state

- `blocked`
  - prerequisite validation fails, or
  - required main-chain kinds are blocked
- `degraded`
  - validation passes only with warnings, or
  - registration evidence is degraded
- `pending`
  - structural layers exist but main-chain exercise is incomplete
- `ready`
  - none of the above

## Capability visibility

- `not_applicable`
  - Android/cross-device path is not engaged
- `waiting_dependency`
  - Android is attached but accepted capability visibility is absent
- `visible`
  - capability visibility is present and not degraded
- `degraded_visible`
  - capability visibility is present but degraded/downgraded

## Operational readiness

- `blocked`
  - main chain unavailable, required API surfaces missing, or runtime verdict is blocked
- `degraded`
  - V2 path is usable but warning/degraded/recovery-qualified
- `ready`
  - canonical V2-side readiness

## Path semantics

- `active_path`
  - one of `main_chain`, `cross_device`, `recovery`, `compat`, `blocked`
- `compat_only_path`
  - distinguishes compat fallback from canonical main-chain success
- `degraded_path`
  - distinguishes canonical vs degraded operation even when still acceptable

## Eligibility semantics

Task initiation is not inferred only from observability.
Task initiation absence alone is also **not** treated as a waiting dependency.
`waiting_dependency` is reserved for missing prerequisites (for example capability
visibility or active session continuity), while `active` indicates whether
execution has actually started.

- `eligible`
  - main chain available
  - capability visibility present
  - active session continuity present
- `waiting_dependency`
  - Android path exists but one or more required dependencies are still absent
- `blocked`
  - main-chain acceptance is not met
- `not_applicable`
  - Android/cross-device path is not engaged

## Closure / quality semantics

- `result_closure`
  - `complete`, `incomplete`, `waiting_dependency`, `not_applicable`
- `success_quality`
  - `canonical_main_chain`, `canonical_cross_device`, `degraded`, `recovery`, `compat`, `blocked`
- `verdict_quality`
  - canonicalized interpretation of acceptance verdict + success quality

The contract explicitly separates:

- a task being observed
- a task being eligible
- a path being active
- a result being complete
- a verdict being canonical vs degraded

## Relationship to the desktop status board

The status board remains an aggregation/consumption layer. This contract is a
lower-level reusable semantic layer that later board/productization PRs can
read without depending on ad hoc interpretation of readiness summaries.

That means later PRs can consume stable names for:

- registration state
- capability visibility
- operational readiness
- active path
- compat-only / degraded path
- recovery-active state
- main-chain availability
- cross-device availability
- session continuity
- task initiation eligibility
- result closure state
- success quality / verdict quality
- blocked / waiting-dependency / incomplete state

## Explicit non-goals for this PR

- full Android/V2 symmetric state evaluation
- full onboarding/access closure hardening
- final desktop status-board productization

This PR only establishes the V2-side contract that those later changes can
depend on.
