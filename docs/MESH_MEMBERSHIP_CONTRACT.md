# Mesh Membership Contract

> PR-32 — Mesh Membership Contract

## Overview

The **Mesh Membership Contract** (`contracts/mesh_membership.py`) is the canonical, serialisable schema that answers:

> *"How does a runtime-capable device belong to a mesh/body, and what is its formal role, authority, and routing intent within that mesh?"*

It is the fourth step in the Galaxy contract chain:

| PR | Contract | Answers |
|----|----------|---------|
| PR-29 | `RegisteredRuntimeDevice` | What a registered runtime-capable device **is** |
| PR-30 | `LocalRuntimeHost` | What a local runtime host must **expose** |
| PR-31 | `HandoffEnvelopeV2` | What a cross-device runtime handoff **carries** |
| **PR-32** | **`MeshMembership`** | How a device **participates** in a mesh/body |
| PR-33 *(upcoming)* | `MeshSession` | How a mesh **session** is coordinated |

---

## What Mesh Membership Means

A **Mesh Membership** record formalises a single device's participation in a named mesh/body. It captures:

- **Which roles** the device plays (source, primary, support, fallback, observer, relay, merge\_owner)
- **What authority** the device holds within the mesh (full mesh authority, execution authority, observe-only, relay-only, none)
- **What routing intent** is intended for task dispatch (local preferred, expand, remote required, split, mirrored)
- **Which other devices** participate as fallback / support / observer / relay / merge\_owner
- **Participation hints** — compact boolean flags for quick downstream checks
- **Health and online status** — optional live signals from device health scoring

One `MeshMembership` object exists per device per mesh context. A device may appear in multiple mesh contexts (e.g. once per active session).

---

## How Mesh Membership Differs From Related Concepts

| Concept | Location | Purpose | Relationship to MeshMembership |
|---------|----------|---------|-------------------------------|
| `BodyEntry` / `BodyMeshRegistry` | `core/mesh/body_mesh_registry.py` | Tracks devices with **capability** roles (PERCEPTION / ACTION / PRESENCE) and a body score | Source for `from_body_mesh_entry()` adapter; MeshMembership normalises capability roles into mesh-participation roles |
| `DeviceFormationGroup` / `FormationSummary` | `core/device_formation/` | Describes a **group of devices** at execution time with formation roles | Source for `from_device_formation_summary()` adapter; MeshMembership produces one per-device record from the formation |
| `CrossDeviceAssignmentSummary` | `core/cross_device_policy/` | Describes **routing posture and role assignments** at dispatch time | Source for `from_cross_device_routing_summary()` adapter; MeshMembership maps routing roles and posture into the stable contract |
| `RegisteredRuntimeDevice` (PR-29) | `contracts/registered_runtime_device.py` | Describes what a device **is** (capability profile, platform, etc.) | Identity source; `RuntimeParticipationHints` in PR-29 is a lightweight preview of full membership |
| `LocalRuntimeHost` (PR-30) | `contracts/local_runtime_host.py` | Describes a device's **local runtime-host posture** | Host-side posture; MeshMembership is the mesh-participation view of the same device |

**In short:**
- `BodyMeshRegistry` tells you *what capabilities a device has* in the mesh.
- `DeviceFormationGroup` tells you *how a group of devices is organised* for a task.
- `CrossDeviceAssignmentSummary` tells you *how to route a specific task* across devices.
- **`MeshMembership`** tells you *how a device formally participates in the mesh*, unifying the role/authority/routing-intent view into one stable, serialisable contract.

---

## Contract Structure

### Top-level: `MeshMembership`

```python
class MeshMembership(BaseModel):
    membership_id: str          # Auto UUID-hex if not supplied
    mesh_id: str                # Identifies the mesh/body
    member_device_id: str       # Physical device identifier
    member_runtime_id: Optional[str]  # Runtime instance on the device

    roles: List[MeshMemberRole]        # Roles in this mesh
    authority_scope: MeshAuthorityScope  # Authority within mesh
    routing_intent: MeshRoutingIntent  # Task-dispatch intent

    source_device_id: Optional[str]    # Request-originating device
    primary_device_id: Optional[str]   # Primary executor
    fallback_device_ids: List[str]
    support_device_ids: List[str]
    observer_device_ids: List[str]
    relay_device_ids: List[str]
    merge_owner_device_id: Optional[str]
    barrier_posture: Optional[str]

    multi_device_required: bool
    merge_confirmation_required: bool
    member_online: Optional[bool]
    member_health_score: Optional[float]

    hints: MeshParticipationHints   # Compact boolean flags
    metadata: Dict[str, Any]
    created_at: float               # Unix timestamp
```

### Role enum: `MeshMemberRole`

| Value | Meaning |
|-------|---------|
| `source` | Device that originated the current request/task |
| `primary` | Primary execution device; anchors the session |
| `support` | Support / co-execution device |
| `fallback` | Fallback device; promoted if primary fails |
| `observer` | Observer; receives events but does not act |
| `relay` | Relay node; forwards tasks/results |
| `merge_owner` | Device responsible for merging distributed results |
| `unassigned` | Registered but no role assigned yet |

### Authority enum: `MeshAuthorityScope`

| Value | Meaning |
|-------|---------|
| `mesh_authority` | May initiate, coordinate, and commit mesh actions |
| `execution_authority` | May execute tasks; cannot coordinate other members |
| `observe_only` | Read-only participation |
| `relay_only` | May only relay; no direct execution authority |
| `none` | Registered but not yet authorised |

### Routing intent enum: `MeshRoutingIntent`

| Value | Meaning |
|-------|---------|
| `local_preferred` | Prefer local execution; cross-device only as needed |
| `local_then_expand` | Start local; expand cross-device when needed |
| `remote_required` | Must dispatch to a remote device |
| `split_execution` | Task split across multiple devices in parallel |
| `mirrored_observation` | Mirrors another member for observability |
| `undecided` | Routing intent not yet determined |

### Hints sub-contract: `MeshParticipationHints`

Compact boolean flags for quick downstream checks without inspecting the full contract:

```python
class MeshParticipationHints(BaseModel):
    is_primary: bool
    is_source: bool
    is_fallback: bool
    is_relay: bool
    is_observer: bool
    has_execution_authority: bool
    multi_device_required: bool
    merge_confirmation_required: bool
```

---

## Adapters / Builders

### `from_body_mesh_entry(entry, mesh_id, primary_device_id)`

Builds a single `MeshMembership` from a `BodyEntry` (core.mesh.body_mesh_registry).

BodyMeshRegistry uses capability roles (PERCEPTION / ACTION / PRESENCE). These are mapped conservatively to the `SUPPORT` mesh role, preserving the original capability roles in `metadata["body_mesh_roles"]` for traceability.

```python
from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
from contracts.mesh_membership import from_body_mesh_entry

registry = BodyMeshRegistry()
registry.register("phone_001", roles=[DeviceRole.PERCEPTION, DeviceRole.ACTION])
entry = registry.get("phone_001")
membership = from_body_mesh_entry(entry, mesh_id="session_abc")
print(membership.to_dict())
```

### `from_device_formation_summary(summary, mesh_id)`

Builds a list of `MeshMembership` objects — one per unique device — from a `FormationSummary` (core.device_formation).

```python
from core.device_formation import resolve_formation_summary
from contracts.mesh_membership import from_device_formation_summary

summary = resolve_formation_summary()
memberships = from_device_formation_summary(summary)
```

### `from_cross_device_routing_summary(summary, mesh_id)`

Builds a list of `MeshMembership` objects from a `CrossDeviceAssignmentSummary` (core.cross_device_policy). Routing posture is mapped to `MeshRoutingIntent`.

```python
from core.cross_device_policy import build_assignment_summary, DEFAULT_LOCAL_ROUTING_POLICY
from contracts.mesh_membership import from_cross_device_routing_summary

routing = build_assignment_summary(DEFAULT_LOCAL_ROUTING_POLICY)
memberships = from_cross_device_routing_summary(routing)
```

### `build_mesh_membership(mesh_id, member_device_id, **kwargs)`

Generic convenience factory. All parameters map directly to `MeshMembership` fields.

```python
from contracts.mesh_membership import build_mesh_membership, MeshMemberRole, MeshAuthorityScope, MeshRoutingIntent

membership = build_mesh_membership(
    mesh_id="mesh_beta",
    member_device_id="tablet_002",
    roles=[MeshMemberRole.PRIMARY],
    authority_scope=MeshAuthorityScope.MESH_AUTHORITY,
    routing_intent=MeshRoutingIntent.LOCAL_PREFERRED,
    primary_device_id="tablet_002",
    source_device_id="phone_001",
    member_online=True,
    member_health_score=0.95,
)
```

### `BodyMeshRegistry.get_mesh_memberships(mesh_id, session_id)`

Convenience method on `BodyMeshRegistry` that normalises all registered entries into `MeshMembership` contracts in one call. The primary device is identified by highest `body_score`.

```python
from core.mesh.body_mesh_registry import get_body_mesh_registry

registry = get_body_mesh_registry()
memberships = registry.get_mesh_memberships(mesh_id="my_session")
for m in memberships:
    print(m.member_device_id, m.roles, m.authority_scope)
```

---

## API Endpoint

PR-32 adds one new **read-only** endpoint:

```
GET /api/v1/mesh/memberships
```

Response:

```json
{
  "mesh_id": "default_mesh",
  "total": 2,
  "memberships": [
    {
      "membership_id": "...",
      "mesh_id": "default_mesh",
      "member_device_id": "phone_001",
      "roles": ["support"],
      "authority_scope": "execution_authority",
      "routing_intent": "undecided",
      "source_device_id": null,
      "primary_device_id": "phone_001",
      "fallback_device_ids": [],
      "support_device_ids": [],
      "observer_device_ids": [],
      "relay_device_ids": [],
      "merge_owner_device_id": null,
      "barrier_posture": null,
      "multi_device_required": false,
      "merge_confirmation_required": false,
      "member_online": null,
      "member_health_score": 0.0,
      "hints": {
        "is_primary": false,
        "is_source": false,
        "is_fallback": false,
        "is_relay": false,
        "is_observer": false,
        "has_execution_authority": true,
        "multi_device_required": false,
        "merge_confirmation_required": false
      },
      "metadata": { "body_mesh_roles": ["action", "perception"] },
      "created_at": 1700000000.0
    }
  ]
}
```

---

## Exports

The contract is available from both the `contracts` package and `core.unified`:

```python
# From contracts package
from contracts.mesh_membership import (
    MeshMembership,
    MeshMemberRole,
    MeshAuthorityScope,
    MeshRoutingIntent,
    MeshParticipationHints,
    from_body_mesh_entry,
    from_device_formation_summary,
    from_cross_device_routing_summary,
    build_mesh_membership,
)

# From contracts package root
from contracts import MeshMembership, build_mesh_membership

# From core.unified
from core.unified import MeshMembership, build_mesh_membership
```

---

## What This PR Explicitly Does NOT Do

- **No Mesh Session contract** — that is PR-33. This PR only defines membership.
- **No target runtime local takeover execution path** — planned for PR-34.
- **No handoff protocol redesign** — already in PR-31.
- **No full registration-flow rewrite** — the registration process is unchanged.
- **No write/cmd semantics** — all new API endpoints are read-only.
- **No UI/dashboard redesign** — no changes to existing dashboard surfaces.
- **No persistence/streaming redesign** — this contract is in-memory only.

---

## Relevant PRs

| PR | Title |
|----|-------|
| PR-25 / #280 | Execution Trace Contract |
| PR-26 / #281 | Projection Assembly Governance |
| PR-27 / #282 | Runtime Governance Snapshot |
| PR-28 / #283 | Execution Policy Alignment Surface |
| PR-29 / #284 | Unified Registered Runtime Device Contract |
| PR-30 / #285 | Local Runtime Host Contract |
| PR-31 / #286 | Unified Handoff Envelope v2 |
| **PR-32** | **Mesh Membership Contract** *(this PR)* |
| PR-33 *(upcoming)* | Mesh Session Contract |
