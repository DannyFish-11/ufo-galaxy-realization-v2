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

## 6) PR-9 bounded consolidation update

PR-9 adds an incremental composition layer on top of the PR-8 scaffold:

- `normalize_conformance_backbone()` composes lifecycle from adjacent canonical
  surfaces (`lifecycle`, then `transfer`, then `coordination`) when direct
  lifecycle input is unknown.
- cross-profile drift signals are emitted (for example lifecycle vs transfer
  divergence) as reviewable diagnostics, not hard rejection.
- transitional pathways are grouped as `hardening_pathways` to make staged
  compatibility retirement safer and more explicit.

This keeps behavior non-breaking while reducing semantic drift across adjacent
profiles and clarifying one distributed control-plane backbone.
