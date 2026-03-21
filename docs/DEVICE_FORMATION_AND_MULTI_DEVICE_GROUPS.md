# Device Formation & Multi-Device Group Model

**PR-17 (V4) — Additive device-formation layer for the Galaxy runtime**

---

## Overview

Before PR-17, the Galaxy runtime could route tasks across devices and reason
about cross-device roles at a *policy* level (PR-13) and *routing* level
(device router).  However, there was no explicit, serialisable model that
described *which devices are currently participating in the same execution
formation*, *what each device's formation-level responsibility is*, and *what
the intended completion/barrier posture for that group is*.

PR-17 introduces a focused, additive `core/device_formation/` package that
makes multi-device participation **explicit, serialisable, and inspectable**.

---

## Package structure

```
core/device_formation/
├── __init__.py              # Public API + package docstring
├── formation_role.py        # FormationRole enum + FormationMember dataclass
├── formation_group.py       # DeviceFormationGroup (central wire-safe model)
├── formation_policy.py      # BarrierPosture enum + FormationPolicy dataclass
├── formation_resolver.py    # resolve_formation() — derives formation from signals
└── formation_summary.py     # FormationSummary + projection helpers
```

---

## Formation roles

Each device in a formation is assigned exactly one `FormationRole`:

| Role | String value | Meaning |
|------|-------------|---------|
| `SOURCE` | `source_device` | Device that originated the cross-device request |
| `PRIMARY_EXECUTION` | `primary_execution_device` | Device primarily responsible for executing the task |
| `SUPPORT` | `support_device` | Assists the primary with a specific capability |
| `OBSERVER` | `observer_device` | Read-only view of formation progress; no execution |
| `RELAY` | `relay_device` | Forwards commands/data; does not execute itself |
| `FALLBACK` | `fallback_device` | Eligible to take over PRIMARY_EXECUTION |
| `MERGE_OWNER` | `merge_owner_device` | Owns result-merge responsibility |
| `UNASSIGNED` | `unassigned` | In roster but not yet assigned a role |

Role values are stable string identifiers safe for serialisation, logging, and
API responses.  The `FORMATION_ROLE_PRECEDENCE` list orders roles from most
to least authoritative for resolver logic.

---

## How device formation differs from routing posture

| Dimension | Cross-Device Routing Policy (PR-13) | Device Formation (PR-17) |
|-----------|-------------------------------------|--------------------------|
| **Layer** | Routing / dispatch time | Execution / group membership time |
| **Answers** | How should the task be dispatched? | Who is in the group and what is each device's responsibility? |
| **Main type** | `RoutingPosture` + `RoutingPolicy` | `DeviceFormationGroup` + `FormationPolicy` |
| **Key concern** | Route selection, expansion gates | Group membership, barrier posture, merge ownership |
| **Replaces existing code?** | No | No |
| **Can be used together?** | Yes — formation resolver seeds from routing summary | Yes |

**DeviceRole (PR-13) vs FormationRole (PR-17)**

`DeviceRole` (PR-13) describes routing-level intent at dispatch time.
`FormationRole` (PR-17) describes execution-level responsibility inside the
active formation group.  They share common names (e.g. `source_device`,
`primary_execution_device`) but live in separate semantic layers:

- `DeviceRole` is resolved at routing/policy time and governs dispatch.
- `FormationRole` is declared in the formation group and governs execution
  responsibility, merge ownership, and barrier/completion posture.

Using both together is **additive** — they reinforce each other.

---

## DeviceFormationGroup model

The `DeviceFormationGroup` dataclass is the central wire-safe model.  Key
fields:

| Field | Type | Description |
|-------|------|-------------|
| `formation_id` | `str` | Stable unique identifier (UUID) |
| `task_id` | `str \| None` | Task this formation is serving |
| `trace_id` | `str \| None` | Distributed-trace identifier |
| `source_device_id` | `str \| None` | Device that originated the request |
| `members` | `List[FormationMember]` | All participating devices + their roles |
| `merge_owner_device_id` | `str \| None` | Explicit merge owner (falls back to primary) |
| `barrier_posture` | `str` | Barrier/completion posture string |
| `formation_reason` | `str` | Why this formation was assembled |
| `runtime_domain_intent` | `str` | Runtime domain (e.g. `cross_device`) |
| `schema_version` | `int` | Wire-format version (currently `1`) |

Convenience properties: `primary_execution_device_id`, `fallback_device_ids`,
`support_device_ids`, `observer_device_ids`, `relay_device_ids`,
`all_member_device_ids`, `effective_merge_owner_device_id`, `member_count`,
`is_multi_device`.

---

## Barrier / completion postures

| Posture | String value | When to use |
|---------|-------------|-------------|
| `WAIT_ALL` | `wait_all` | All device results required for correctness |
| `WAIT_PRIMARY` | `wait_primary` | Only primary result is required (default) |
| `BEST_EFFORT` | `best_effort` | Fire-and-forget; partial results acceptable |
| `WAIT_MERGE_OWNER` | `wait_merge_owner` | Merge assembly must run on a specific device |

---

## Resolver

`resolve_formation()` derives a `(DeviceFormationGroup, FormationPolicy)` pair
from available runtime signals.  All inputs are optional — the resolver
degrades gracefully when only partial information is present.

Signal consumption order:
1. **Cross-device routing summary (PR-13)** — seeds source/primary device IDs
   and role assignments
2. **Execution policy (PR-11)** — derives `multi_device_required` and
   `merge_confirmation_required` from policy band and gate flags
3. **Direct device lists** — `target_device_ids`, `fallback_device_ids`, etc.
4. **Merge/recovery summary (PR-14)** — seeds merge-owner derivation
5. **Task/trace metadata** — `task_id`, `trace_id`
6. **Runtime domain** — governs whether cross-device formation applies

The resolver never modifies any upstream layer.  It is purely a **read-derive**
function.

---

## How formation relates to existing layers

```
PR-11 ExecutionPolicy     ──► governs risk/budget gates
PR-13 RoutingPolicy       ──► governs dispatch posture + device role at route time
PR-14 MergeSummary        ──► records distributed result merge outcomes
PR-15 TaskSemantics       ──► classifies step kinds

PR-17 DeviceFormationGroup ◄── reads all of the above as optional signals
                           ──► enriches projection payloads
                           ──► exposed via GET /api/v1/projection/device-formation
```

Formation does not replace any of the above.  It *consumes* them as input
signals and produces a complementary, inspectable description of group
membership.

---

## Projection / read-only integration

The `attach_formation_to_projection()` helper adds a `"device_formation"` key
to any projection dict, following the same additive pattern as PR-13, PR-14,
and PR-15.

A new read-only endpoint is registered in `core/routes/projection.py`:

```
GET /api/v1/projection/device-formation
```

Response includes all standard `RuntimeProjection` fields plus:
- `device_formation` — full `FormationSummary` dict
- `formation_hints` — compact scalar hints for quick downstream checks

The endpoint assembles the formation summary from live signals (runtime domain,
cross-device routing summary, execution policy) without writing any state.

---

## Usage example

```python
from core.device_formation import resolve_formation_summary, attach_formation_to_projection

# Resolve a formation from available signals
summary = resolve_formation_summary(
    runtime_domain="cross_device",
    source_device_id="phone_001",
    primary_device_id="desktop_001",
    target_device_ids=["phone_001", "desktop_001", "tablet_002"],
    fallback_device_ids=["tablet_002"],
    task_id="task-abc",
    trace_id="trace-xyz",
    formation_reason="user requested cross-device screenshot capture",
)

# Attach to a projection payload
projection = {"tri_state_phase": "manifest", ...}
enriched = attach_formation_to_projection(projection, summary)
```

---

## What this PR does NOT yet solve

- **Live membership rebalancing** — dynamically reshaping the formation as
  devices join/leave is out of scope for this PR.
- **Health-driven formation reshaping** — automatically promoting FALLBACK
  devices when the PRIMARY becomes unhealthy is a future concern.
- **Cross-formation coordination** — managing multiple concurrent formations
  is not addressed here.
- **Formation lifecycle events** — emitting state events when a formation is
  assembled, changed, or dissolved is a future concern.

---

## How future code should express multi-device formations

When implementing new cross-device execution paths:

1. **Use `resolve_formation()` or `resolve_formation_summary()`** to derive
   the formation context from available signals.  Do not construct
   `DeviceFormationGroup` manually unless you have all required inputs.

2. **Attach the formation to projection payloads** using
   `attach_formation_to_projection()` so that status boards and governance
   layers can observe it.

3. **Do not bypass the existing device router or UDM**.  Formation is a
   description layer, not a replacement for dispatch infrastructure.

4. **Use `FormationRole` values** as stable string constants in APIs and log
   records — they are guaranteed stable across schema versions.

5. **Check `formation_hints`** for quick conditional logic:
   - `hints["is_multi_device"]` — is this actually a multi-device execution?
   - `hints["fallback_available"]` — is there a device to fall back to?
   - `hints["has_merge_owner"]` — is merge responsibility assigned?

---

## Tests

See `tests/test_pr17_device_formation.py` for:
- Enum / schema serialisation stability
- Formation summary generation from representative inputs
- Partial / missing input handling (graceful degradation)
- Projection / read-only integration stability
- Role assignment and merge-owner derivation behaviour
