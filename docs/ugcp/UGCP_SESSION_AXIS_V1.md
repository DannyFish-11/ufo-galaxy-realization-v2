# UGCP Session Axis v1

> **Introduced**: PR-3 (Establish the canonical session axis)
>
> **Module authority**: `core.canonical_session_axis`
>
> Related documents:
> - `../architecture/CANONICAL_SESSION_AXIS_V1.md` — architecture-level overview
> - `CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md` — section 4 (session families)
> - `UGCP_CANONICAL_VOCABULARY_V1.md` — section 1 (identity and session taxonomy)
> - `UGCP_ANDROID_ALIGNMENT_NOTES_V1.md` — Android alignment context

---

## 1) Purpose

This document provides the UGCP-level detail for the canonical session axis,
complementing the architecture-level overview in
`../architecture/CANONICAL_SESSION_AXIS_V1.md`.

It covers:
- The session family definitions in UGCP vocabulary terms
- The identifier role model and alias resolution precedence
- The Android-to-center mapping with UGCP classification symbols
- Policy anchors for continuity, reconnect, and terminal semantics

---

## 2) Session family definitions in UGCP vocabulary

| Session family | Canonical identifier | UGCP layer | Continuity | Recovery |
|---|---|---|---|---|
| conversation | `conversation_session_id` | control/ingress | persistent | yes |
| control | `control_session_id` | control/request | request-scoped | no |
| runtime_attachment | `runtime_attachment_session_id` | runtime truth | persistent | yes (reconnect) |
| delegation_transfer | `delegation_transfer_session_id` | transfer/handoff | transfer-scoped | no (terminal = new handshake) |
| mesh | `mesh_session_id` | coordination overlay | overlay | yes |

The session hierarchy in UGCP vocabulary:

```
trace_id
└── task_id
    └── control_session_id
        └── runtime_attachment_session_id
            └── mesh_session_id (optional overlay)

conversation_session_id (user-scoped, cross-device, cross-request)
delegation_transfer_session_id (per-transfer lifecycle)
```

---

## 3) Identifier role model

### Role classifications

| Symbol | Role | Description |
|---|---|---|
| `C` | canonical | Authoritative identifier for the session family. Use on all new surfaces. |
| `A` | alias | Transitional alias. Recognised and normalised at ingress. Valid in existing contracts only. |
| `M` | transitional_mirror | Mirrors the canonical value for backward compatibility. Not a separate identity. |
| `L` | legacy_bare | Context-dependent bare `session_id`. Resolved by normalisation helpers. Do not introduce on new surfaces. |

### Full identifier role table

| Field name | Family | Role | Canonical name | Alias resolution order |
|---|---|---|---|---|
| `conversation_session_id` | conversation | `C` | `conversation_session_id` | 1 |
| `control_session_id` | conversation | `A` | `conversation_session_id` | 2 |
| `session_id` (conv context) | conversation | `L` | `conversation_session_id` | 3 |
| `runtime_attachment_session_id` | runtime_attachment | `C` | `runtime_attachment_session_id` | 1 |
| `runtime_session_id` | runtime_attachment | `A` | `runtime_attachment_session_id` | 2 |
| `attached_session_id` | runtime_attachment | `A` | `runtime_attachment_session_id` | 3 |
| `session_id` (attachment context) | runtime_attachment | `L` | `runtime_attachment_session_id` | 4 |
| `delegation_transfer_session_id` | delegation_transfer | `C` | `delegation_transfer_session_id` | 1 |
| `transfer_session_id` | delegation_transfer | `A` | `delegation_transfer_session_id` | 2 |
| `handoff_session_id` | delegation_transfer | `A` | `delegation_transfer_session_id` | 3 |
| `mesh_session_id` | mesh | `C` | `mesh_session_id` | 1 |

**Alias resolution policy**: when multiple fields are present, canonical fields
take precedence over aliases.  The `resolution_priority` values in the
`SessionIdentifierRecord` catalogue define the exact precedence.

---

## 4) Normalisation helpers (center-side)

| Helper function | Resolves for family | Canonical result |
|---|---|---|
| `normalize_conversation_session_id(payload)` | conversation / control | `conversation_session_id` |
| `normalize_runtime_attachment_session_id(payload)` | runtime_attachment | `runtime_attachment_session_id` |
| `normalize_delegation_transfer_session_id(payload)` | delegation_transfer | `delegation_transfer_session_id` |

All three helpers are in `core.schemas.ugcp.shared`.

---

## 5) Android-to-center session mapping

Classification symbols follow the homomorphic mapping standard:

| Symbol | Classification | Meaning |
|---|---|---|
| `≡` | CANONICAL_MATCH | Exact equivalence, same name and semantics. |
| `→` | TRANSITIONAL_ALIAS | Android name differs; normalised to canonical at ingress. |
| `≈` | PARTIAL_MATCH | Semantically related; not yet structurally unified. |

### Session mapping table

| Android field | Center canonical field | Family | Symbol | Notes |
|---|---|---|---|---|
| `session_id` | `control_session_id` | control | `→` | Android primary session; normalised at ingress by `normalize_conversation_session_id()` |
| `runtime_session_id` | `runtime_attachment_session_id` | runtime_attachment | `→` | Center registry is the resolution authority |
| `attached_session_id` | `runtime_attachment_session_id` | runtime_attachment | `→` | Android-side alias; normalised at ingress |
| `transfer_session_id` | `delegation_transfer_session_id` | delegation_transfer | `→` | Normalised at ingress |
| `handoff_session_id` | `delegation_transfer_session_id` | delegation_transfer | `→` | Normalised at ingress |
| `mesh_session_id` | `mesh_session_id` | mesh | `≡` | Same name; preserved end-to-end |
| `conversation_session_id` | `conversation_session_id` | conversation | `≈` | Semantically related; local models not yet unified at protocol level |

**Authority principle**: Android-side session identifiers are **claims**.
The center-side normalisation helpers resolve them to canonical identifiers
before they are used in truth, registry, or dispatch surfaces
(per `ANDROID_SESSION_IDS_ARE_CLAIMS_POLICY` in `core.canonical_session_axis`).

---

## 6) Continuity and recovery policy anchors

### Runtime attachment reconnect policy

Reconnect restores a `disconnected` or `detaching` session to `attached` state
**without** creating a new `runtime_attachment_session_id`.

Authority: `core.attached_runtime_session_registry.REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY`

UGCP anchor: `RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY` in `core.canonical_session_axis`

### Delegation transfer terminal policy

A delegation transfer session in a terminal state is **non-recoverable**.
A new transfer handshake is required.

Authority: `core.ugcp_control_transfer_profile.TRANSFER_TERMINAL_REASON_IS_CANONICAL_POLICY`

UGCP anchor: `TRANSFER_SESSION_TERMINAL_IS_NON_RECOVERABLE_POLICY` in `core.canonical_session_axis`

### Mesh session overlay policy

The mesh session is an **optional overlay**.  Its absence does not affect
the other four families.

UGCP anchor: `MESH_SESSION_IS_OPTIONAL_OVERLAY_POLICY` in `core.canonical_session_axis`

### Bare session resolution policy

A bare `session_id` field is **context-dependent** and resolved by the
normalisation helpers.  Its presence in existing contracts is valid; it
must not be introduced on new surfaces.

UGCP anchor: `BARE_SESSION_IS_NOT_CANONICAL_POLICY` in `core.canonical_session_axis`

---

## 7) Session axis invariants

The following invariants define correctness constraints for the session axis.
They are verifiable from the `SessionAxisSnapshot` produced by
`core.canonical_session_axis.build_session_axis_snapshot()`.

1. **Five families**: exactly five session families exist in the catalogue.
2. **Canonical identifier uniqueness**: each family has exactly one canonical
   identifier.
3. **All aliases resolve**: every alias or legacy_bare identifier resolves to
   a canonical name that appears in the catalogue.
4. **Android mappings are non-empty**: the Android mapping catalogue contains
   at least one entry per runtime_attachment, delegation_transfer, and mesh
   families.
5. **Canonical fields have resolution priority 1**: canonical identifiers
   always have the highest resolution priority within their family.

These invariants are asserted in `tests/test_pr3_canonical_session_axis.py`.
