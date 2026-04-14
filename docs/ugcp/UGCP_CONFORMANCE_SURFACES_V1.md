# UGCP Conformance Surfaces v1 (PR-8 realization-v2)

## 1) Purpose

This profile introduces bounded conformance scaffolding so center-side flows can
distinguish:

- canonical semantics (long-term contract),
- transitional compatibility semantics (temporarily tolerated),
- unknown/non-conforming semantics (not canonicalized).

It is incremental and non-breaking: compatibility pathways are still accepted in
PR-8 but must be normalized and explicitly classified.

## 2) Canonical conformance surfaces

PR-8 classifies six UGCP surfaces:

1. `schema`
2. `lifecycle`
3. `authority`
4. `transfer`
5. `coordination`
6. `truth_event`

Each surface declares:

- canonical authority source,
- canonical contract reference,
- tolerated transitional aliases.

## 3) Normalization boundary

Compatibility aliases may be normalized into canonical values at conformance
boundaries. Normalization must retain `compatibility_pathway` metadata so later
retirement can be safe and auditable.

Examples:

- `sealed` → `ready` (transfer)
- `waiting` → `awaiting_barrier` (coordination/lifecycle)
- `session_truth_written` → `ugcp.truth.session.recorded.v1` (truth event)
- `projection` truth source → canonical-safe `unknown` (authority)

## 4) Cross-profile invariant surface

PR-8 introduces a reviewable invariant report scaffold for checks such as:

- truth event uses canonical vocabulary
- authority source is not a compat alias
- transfer/coordination/lifecycle state is known

The report is intended for progressive hardening, not immediate strict rejection.

## 5) Compatibility retirement posture

PR-8 does **not** claim strict-mode enforcement or immediate legacy removal.
It provides explicit classification and normalization groundwork so future
retirement can be staged without destabilizing runtime behavior.

## 6) PR-9 bounded hardening additions

PR-9 keeps the same non-breaking posture but tightens cross-profile normalization
and hardening in two bounded ways:

- **profile-adjacent input key normalization** (e.g. `event_type`,
  `control_transfer_state`, `mesh_state`) into canonical conformance fields with
  source-key annotations in `normalization_input_sources`.
- **cross-profile semantic checks** for lifecycle/transfer/coordination
  consistency and truth-event/profile alignment, surfaced as reviewable
  invariants and `transitional_seams` diagnostics (not strict rejection).
