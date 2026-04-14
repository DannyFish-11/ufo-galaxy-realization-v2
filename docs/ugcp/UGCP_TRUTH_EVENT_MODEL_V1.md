# UGCP Truth/Event Model v1 (PR-7, realization-v2 side)

## 1) Scope and intent

This profile hardens one canonical backbone for:
- authoritative truth transitions,
- canonical transition events,
- durable snapshot/read-model surfaces,
- replay/recovery checkpoints,
- runtime-facing observational update streams.

This is an **incremental alignment profile**. It does not claim the repository is already fully event-sourced.

## 2) Canonical boundary: truth vs event vs snapshot

- **Authoritative truth writes**
  - Canonical state transitions are decided by authoritative truth modules (for example `core.canonical_session_truth`).
- **Transient events**
  - Truth writes can be emitted as canonical `TruthEvent` envelopes for propagation and observation.
  - Event streams are notifications and do not become a new source of truth.
- **Durable snapshots / read models**
  - Snapshot surfaces are durable projections derived from truth/event history.
  - Snapshots are read models, not independent truth authorities.

## 3) Frozen canonical transition event vocabulary

Canonical transition event types in PR-7 backbone:
- `ugcp.truth.session.recorded.v1`
- `ugcp.truth.session.snapshot.v1`
- `ugcp.task.lifecycle.transition.v1`
- `ugcp.runtime.lifecycle.transition.v1`
- `ugcp.control_transfer.transition.v1`
- `ugcp.coordination.transition.v1`

## 4) Ordering, idempotency, and replay/recovery expectations

- Canonical events carry an `ordering_key` and optional `event_sequence` when available.
- Replay checkpoints preserve:
  - canonical event type,
  - ordering key,
  - event sequence (if available),
  - stable dedupe key.
- Recovery/reconstruction should replay canonical semantics without introducing profile-specific drift.

## 5) Profile traceability on one backbone

The same model covers profile-driven transitions:
- runtime/session truth transitions,
- control-transfer transitions,
- coordination transitions,
- task/runtime lifecycle transitions.

This keeps cross-profile lifecycle tracing consistent while preserving existing module boundaries.

## 6) Realization-v2 implementation anchor

Canonical module:
- `core/ugcp_truth_event_model.py`

Projection alignment sentinel:
- `core.routes.projection.UGCP_TRUTH_EVENT_MODEL_ALIGNED_PR7`
