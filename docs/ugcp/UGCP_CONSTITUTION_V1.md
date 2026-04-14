# UGCP Constitution v1 (realization-v2 side)

## 1) Status and scope

This document is the first constitution-level vocabulary and semantics freeze for the UGCP control plane on `ufo-galaxy-realization-v2`.

It is architecture-grounding only:
- It freezes language and intended semantics.
- It does **not** claim all modules already use all frozen terms.

## 2) Constitutional clauses

### Clause A — One canonical control language
The center-side control plane uses one canonical vocabulary for identity, session hierarchy, control decisions, terminal semantics, readiness, and coordination outcomes.

### Clause B — Authority-chain first
Current authority direction remains:
1. Ingress canonicalization (`TaskEnvelope`, gateway handlers, delegated ingress)
2. Dispatch/handoff decisions (`SourceDispatchMode`, handoff/takeover/delegated contracts)
3. Session truth and merge (`canonical_session_truth`, runtime session snapshots)
4. Read-only truth projection (`runtime_truth_compiler`, `outward_runtime_truth`)

### Clause C — Compat is adapter-only
Compat/legacy surfaces are migration shims and must not redefine canonical semantics.

### Clause D — No parallel truth authority
Canonical truth terms (session truth, readiness verdict, coordination outcome) must converge to a single authority chain; side channels may enrich but not override.

### Clause E — Explicit incompleteness
When a canonical term is frozen before universal implementation, documentation must mark it as:
- `active` (implemented as named), or
- `mapped` (implemented through current alias terms).

## 3) Canonical taxonomy (frozen families)

UGCP v1 freezes these families:
- Identity semantics
- Session taxonomy
- Control vocabulary
- Lifecycle/phase vocabulary
- Truth/authority terminology
- Profile taxonomy

Normative field-level freeze is defined in `UGCP_CANONICAL_VOCABULARY_V1.md`.

## 4) Profile taxonomy (v1)

A runtime profile is expressed by the tuple:

`source_runtime_posture + coordination_role + dispatch_mode + effective_mode`

This tuple is the canonical profile surface for cross-device execution intent and effective behavior.
