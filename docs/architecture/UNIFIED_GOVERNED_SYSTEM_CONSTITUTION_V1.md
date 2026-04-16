# Unified Governed System Constitution v1

## 1) Constitutional scope

This document is the canonical architecture constitution for the governed cross-repository system formed by:

- `DannyFish-11/ufo-galaxy-realization-v2` (center orchestration + governance runtime)
- `DannyFish-11/ufo-galaxy-android` (Android runtime-profile participant)

This is a definition freeze, not a behavior redesign.

## 2) Governing authority model

1. The center runtime is the global orchestration and governance authority.
2. Authoritative control decisions, dispatch decisions, session truth resolution, and outward truth projection are center-governed.
3. Participant runtimes (including Android) contribute capability/readiness/runtime evidence and execute delegated work, but are not parallel global truth authorities.

## 3) Canonical planes and relationships

### 3.1 Truth / projection / registry chain

- **Truth plane:** authoritative control/runtime/session execution truth.
- **Projection plane:** outward read models compiled from truth-plane authority.
- **Registry plane:** canonical identity/capability/participation indexing used by dispatch and continuity logic.

Projection surfaces consume truth; they do not redefine truth authority.

### 3.2 Dispatch and session continuity

- Dispatch chooses local, delegated, transfer, fallback, or multi-device execution paths under governance policy.
- Session continuity is explicit and classed (control continuity, runtime attachment continuity, transfer continuity, mesh/session coordination continuity).
- Cross-device delegation and transfer must preserve continuity semantics and terminal-state integrity.

## 4) Device domain vs node domain

Device domain and node domain are related but distinct subdomains inside one governed system:

- **Device domain:** registered endpoints, runtime hosting context, transport/readiness/capability evidence, cross-device participation.
- **Node domain:** executable/planning/coordination graph and invocation abstractions.

Device identity is not equivalent to node identity; node abstractions are not a replacement for device/runtime participant identity.

## 5) Runtime-hosted execution and capability hosting

- Runtime hosts execute capabilities on behalf of governed dispatch.
- Capability hosting and readiness evidence inform routing and eligibility.
- Capability publication does not create independent truth authority.

## 6) Android constitutional role

Android is a runtime-profile participant in the same governed system:

- Android device identity anchors transport/registration.
- Android runtime host identity participates in runtime attachment and delegated execution.
- Android reports readiness/capability/continuity evidence to the center-governed truth chain.
- Android is not a parallel global orchestrator.

## 7) Canonical vs transitional surfaces

### 7.1 Canonical architecture surfaces

- governance/orchestration authority chain
- truth finalization and projection compilation chain
- canonical registries used for identity/capability/participation and dispatch
- canonical dispatch and continuity semantics for delegated/transfer/multi-device execution

### 7.2 Transitional compatibility-era surfaces

- legacy aliases and compatibility field mappings
- adapter/facade bridges kept for migration continuity
- compat caches/supplemental mirrors that are non-authoritative

Transitional surfaces may normalize or bridge; they must not claim canonical authority.

## 8) Layer boundary rules

- **Truth** defines authority.
- **Projection** compiles read models from truth.
- **Registry** indexes canonical identity/capability/participation signals.
- **Cache** accelerates reads and may be stale; never upgrades authority.
- **Compatibility layer** preserves old contracts during convergence.
- **Adapter layer** translates ingress/egress and legacy interfaces into canonical semantics.

## 9) Cross-repository constitutional alignment requirement

This constitution requires a matching Android-side alignment constitution in `ufo-galaxy-android` with equivalent system definitions and non-conflicting authority claims.

