# Canonical Session Axis v1

> **Scope**: `DannyFish-11/ufo-galaxy-realization-v2` (center authority, **center**)
> and implicitly `DannyFish-11/ufo-galaxy-android` (Android runtime-profile participant, **android**)
>
> **Status**: Canonical session axis baseline — architecture-grounding only.
> Does not claim full cross-repo protocol convergence is already implemented.
>
> **Introduced**: PR-3 (Establish the canonical session axis across control, runtime,
> attached, transfer, and related session families)
>
> **Module authority**: `core.canonical_session_axis`
>
> Related documents:
> - `../architecture/CANONICAL_CONCEPT_MODEL_V1.md` — concept model
> - `../architecture/UNIFIED_GOVERNED_SYSTEM_CONSTITUTION_V1.md` — system constitution
> - `../ugcp/CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md` — cross-repo mapping
> - `../ugcp/UGCP_CANONICAL_VOCABULARY_V1.md` — canonical vocabulary
> - `../ugcp/UGCP_SESSION_AXIS_V1.md` — UGCP-level session axis detail

---

## 1) Purpose and scope

This document establishes the **canonical session axis** for the governed
cross-repository system.  It makes explicit:

- the five canonical session families and their role boundaries
- which identifiers are canonical
- which identifiers are transitional aliases or legacy bare fields
- how Android-side session structures map to center-side structures
- how session continuity should be reasoned about across control, runtime,
  attached, and transfer layers

This is an architecture-grounding document.  It does not redesign runtime
behaviour.  Existing reconnect, recovery, and transfer flows remain governed
by their existing authority modules (listed per family below).

---

## 2) Why a session axis is needed

The system already contains meaningful session-related structures across
multiple layers.  Before this PR, the cross-layer and cross-repository
relationship between those structures was expressed through aliases,
mapping helpers, and documentation-local conventions — visible to someone
who read all related files, but not inspectable from a single canonical
surface.

This created ambiguity in:
- reconnect and recovery flows (which identifier is stable across reconnect?)
- runtime continuity (which session persists, which is request-scoped?)
- transfer and delegation semantics (can a transfer session be recovered?)
- projection and runtime-truth assembly (which session ID anchors the truth record?)
- cross-repository reasoning (which Android field maps to which center field?)

The session axis resolves all of these by providing one canonical catalogue.

---

## 3) The five session families

### Session family hierarchy

```
trace_id
└── task_id
    └── control_session_id         (control session)
        └── runtime_attachment_session_id   (runtime attachment session)
            └── mesh_session_id    (mesh session — optional overlay)

conversation_session_id            (conversation session — user-scoped, cross-device)
delegation_transfer_session_id     (delegation transfer session — handoff lifecycle)
```

The hierarchy expresses containment / correlation, not strict nesting.
A single request may span multiple families simultaneously.

---

### 3.1 Conversation session

| Attribute | Value |
|---|---|
| Canonical identifier | `conversation_session_id` |
| Continuity class | persistent |
| Authority module | `core.session_manager` |
| Recovery allowed | yes |
| Terminal requires new handshake | no |

**Role**: Conversation / history continuity context.  Bound to a `user_id`
and shared across all devices for that user.  Persists across individual
requests until explicitly closed.  Governs conversation history and context
for LLM/agent turns.

**Alias resolution order** (highest priority first):
1. `conversation_session_id` — canonical
2. `control_session_id` — legacy alias (maps here in conversation/chat payloads)
3. `session_id` — legacy bare (context-dependent)

**Normalisation helper**: `normalize_conversation_session_id()` in
`core.schemas.ugcp.shared`.

---

### 3.2 Control session

| Attribute | Value |
|---|---|
| Canonical identifier | `control_session_id` |
| Continuity class | request-scoped |
| Authority module | `core.schemas.ugcp.shared` |
| Recovery allowed | no |
| Terminal requires new handshake | no |

**Role**: Control-plane continuity session.  Scoped to a single request or
command lifecycle.  Associates control ingress, dispatch, and outward truth
compilation.  A new `control_session_id` is generated for each new request.

**Notes**: `control_session_id` also appears as a legacy alias for
`conversation_session_id` in existing control payloads.  On new surfaces,
prefer `conversation_session_id` for conversation continuity and use a
separate `control_session_id` for request-scoped control anchoring.

---

### 3.3 Runtime attachment session

| Attribute | Value |
|---|---|
| Canonical identifier | `runtime_attachment_session_id` |
| Continuity class | persistent |
| Authority module | `core.attached_runtime_session_registry` |
| Recovery allowed | yes |
| Terminal requires new handshake | yes (for `invalidated` / `detached`) |

**Role**: Runtime attachment continuity context.  Tracks the persistent
attach / reconnect relationship between the center runtime and a
cross-device participant.  Persists across individual requests and transport
reconnections.  A `disconnected` session is recoverable via a reconnect
signal without creating a new `runtime_attachment_session_id`.  An
`invalidated` or `detached` session requires a new attach handshake.

**Alias resolution order** (highest priority first):
1. `runtime_attachment_session_id` — canonical
2. `runtime_session_id` — stable opaque registry identity (pre-dates canonical name)
3. `attached_session_id` — Android-side transitional alias
4. `session_id` — legacy bare

**Normalisation helper**: `normalize_runtime_attachment_session_id()` in
`core.schemas.ugcp.shared`.

**Recovery policy**: `RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY` in
`core.attached_runtime_session_registry` — a reconnect must not change the
stable `runtime_session_id`.

---

### 3.4 Delegation transfer session

| Attribute | Value |
|---|---|
| Canonical identifier | `delegation_transfer_session_id` |
| Continuity class | transfer-scoped |
| Authority module | `core.ugcp_control_transfer_profile` |
| Recovery allowed | no |
| Terminal requires new handshake | yes |

**Role**: Delegation / handoff / transfer lifecycle context.  Tracks the
transfer of execution ownership across participants or devices.  Scoped to
one transfer lifecycle.  Terminal states (`completed`, `rejected`,
`cancelled`, `expired`) are non-recoverable.  A new transfer handshake is
required for any subsequent delegation.

**Alias resolution order** (highest priority first):
1. `delegation_transfer_session_id` — canonical
2. `transfer_session_id` — transitional alias
3. `handoff_session_id` — transitional alias

**Normalisation helper**: `normalize_delegation_transfer_session_id()` in
`core.schemas.ugcp.shared`.

---

### 3.5 Mesh session

| Attribute | Value |
|---|---|
| Canonical identifier | `mesh_session_id` |
| Continuity class | overlay |
| Authority module | `contracts.mesh_session` |
| Recovery allowed | yes |
| Terminal requires new handshake | yes |

**Role**: Mesh / staged coordination session.  An optional overlay active
only when multi-participant staged coordination is required.  Governs
membership, assignment, and barrier semantics for staged multi-device
execution.  Absent when single-device or simple delegated execution is used.

**Cross-repo**: Same field name (`mesh_session_id`) is used on both center
and Android sides.  Preserved end-to-end when mesh coordination is active.

---

## 4) Identifier role classification

| Identifier field | Family | Role | Canonical name |
|---|---|---|---|
| `conversation_session_id` | conversation | **canonical** | `conversation_session_id` |
| `control_session_id` | conversation | alias | `conversation_session_id` |
| `session_id` (in conversation context) | conversation | legacy_bare | `conversation_session_id` |
| `runtime_attachment_session_id` | runtime_attachment | **canonical** | `runtime_attachment_session_id` |
| `runtime_session_id` | runtime_attachment | alias | `runtime_attachment_session_id` |
| `attached_session_id` | runtime_attachment | alias | `runtime_attachment_session_id` |
| `session_id` (in attachment context) | runtime_attachment | legacy_bare | `runtime_attachment_session_id` |
| `delegation_transfer_session_id` | delegation_transfer | **canonical** | `delegation_transfer_session_id` |
| `transfer_session_id` | delegation_transfer | alias | `delegation_transfer_session_id` |
| `handoff_session_id` | delegation_transfer | alias | `delegation_transfer_session_id` |
| `mesh_session_id` | mesh | **canonical** | `mesh_session_id` |

Rules:
- Canonical fields take precedence over aliases during resolution.
- Aliases are valid in **existing** contracts; must not be introduced on new surfaces.
- Legacy bare `session_id` must not be introduced on new surfaces.

---

## 5) Android-to-center session mapping

| Android field | Center canonical field | Family | Classification | Notes |
|---|---|---|---|---|
| `session_id` | `control_session_id` | control | TRANSITIONAL_ALIAS | Android primary session field; normalised at ingress |
| `runtime_session_id` | `runtime_attachment_session_id` | runtime_attachment | TRANSITIONAL_ALIAS | Center registry is the resolution authority |
| `attached_session_id` | `runtime_attachment_session_id` | runtime_attachment | TRANSITIONAL_ALIAS | Android-side alias for runtime_session_id |
| `transfer_session_id` | `delegation_transfer_session_id` | delegation_transfer | TRANSITIONAL_ALIAS | Normalised at ingress |
| `handoff_session_id` | `delegation_transfer_session_id` | delegation_transfer | TRANSITIONAL_ALIAS | Normalised at ingress |
| `mesh_session_id` | `mesh_session_id` | mesh | CANONICAL_MATCH | Same name; preserved end-to-end |
| `conversation_session_id` | `conversation_session_id` | conversation | PARTIAL_MATCH | Semantically related; local models not yet unified at protocol level |

**Key principle**: Android-side session identifiers are treated as **claims**
at ingress.  The center-side normalisation helpers in `core.schemas.ugcp.shared`
resolve them to canonical identifiers before they are used in truth, registry,
or dispatch surfaces.

---

## 6) Reconnect, recovery, and transfer semantics

### 6.1 Runtime attachment reconnect

A **reconnect** restores a `disconnected` or `detaching` session to `attached`
state without creating a new `runtime_attachment_session_id`.

A **reattach** (for `detached` or `invalidated` sessions) creates a new
`runtime_attachment_session_id`.

The authority for this distinction is
`core.attached_runtime_session_registry.REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY`.

### 6.2 Delegation transfer non-recoverability

A delegation transfer session in a terminal state (`completed`, `rejected`,
`cancelled`, `expired`) is **non-recoverable**.  A new transfer handshake is
required.  The authority for this is
`core.ugcp_control_transfer_profile.TRANSFER_TERMINAL_REASON_IS_CANONICAL_POLICY`.

### 6.3 Mesh session recovery

A mesh session can be recovered by the coordinator as long as the underlying
participants are still reachable.  The mesh session lifecycle is governed by
`contracts.mesh_session` and `contracts.mesh_session_coordinator`.

### 6.4 Conversation session continuity

The conversation session persists across requests and device changes for a
given user.  It is not terminated by transport reconnections or device
switching.  New devices joining an existing conversation context see the
shared conversation history.

---

## 7) Session continuity across projection and runtime truth

When compiling runtime truth (`core.canonical_session_truth`):
- `runtime_attachment_session_id` anchors the truth record to a specific
  attachment session.
- `control_session_id` anchors it to a specific request lifecycle.
- Both can be present; `runtime_attachment_session_id` is the primary
  attachment anchor, `control_session_id` is the request-scoped anchor.

When compiling a durable runtime session snapshot
(`contracts.runtime_session_snapshot.RuntimeSessionSnapshot`):
- `session_id` in the snapshot maps to `runtime_attachment_session_id`.
- `mesh_session_id` is optionally present as an overlay.
- `trace_id` and `task_id` provide causal traceability.

---

## 8) What is not changed

This document is an architecture-grounding document.  The following are
**not changed** by this PR:

- The behaviour of `core.attached_runtime_session`
- The behaviour of `core.attached_runtime_session_registry`
- The behaviour of `core.canonical_session_truth`
- The behaviour of `core.ugcp_control_transfer_profile`
- The behaviour of `contracts.mesh_session`
- Any existing alias or compatibility field
- Any Android-side protocol contract

All existing aliases, compatibility mappings, and ingress normalisation
helpers remain in place and continue to function as before.

---

## 9) Governance reference

| Surface | Authority |
|---|---|
| Session family catalogue | `core.canonical_session_axis.get_session_family_catalogue()` |
| Session identifier catalogue | `core.canonical_session_axis.get_session_identifier_catalogue()` |
| Android session mapping | `core.canonical_session_axis.get_android_session_mapping_catalogue()` |
| Identifier normalisation | `core.schemas.ugcp.shared.normalize_*_session_id()` |
| Runtime attachment authority | `core.attached_runtime_session_registry` |
| Delegation transfer authority | `core.ugcp_control_transfer_profile` |
| Mesh session authority | `contracts.mesh_session` |
| Conversation session authority | `core.session_manager` |
| Session projection alignment | `core.routes.projection.ProjectionSentinels.CANONICAL_SESSION_AXIS_ALIGNED_PR3` |
