# Observability and History Layer (PR-14)

This document describes the observability and history layer introduced in
PR-14, which builds on the PR-9 adapter, PR-11 topology layout, PR-12 topology
renderer, and PR-13 diagnostics/inspection layer to make the desktop topology /
status board not only readable and investigable, but **observable over time**.

---

## Overview

After PR-13 introduced an inspection surface for the *current* topology state,
PR-14 adds the ability to understand **recent changes, transitions, and
stability** — making it possible to answer questions like:

- Did the topology recently transition from `canonical` to `degraded`?
- Has the primary provider changed since the last observation?
- How stable has the topology been over the last N readings?
- Was a recent `degraded` state re-promoted as authoritative?  (It must not be.)
- What is the OneAPI lower-horizon status history?

The history/observability layer provides:

| Component | Description |
|-----------|-------------|
| `TopologyHistoryRecorder` | Main recorder — derives history entries and snapshots from the PR-9/PR-11/PR-13 pipeline |
| `TopologyHistoryEntry` | Single timestamped change record |
| `TopologySnapshot` | Point-in-time topology state snapshot (diffable) |
| `TopologyHistoryBuffer` | Bounded in-memory buffer for history entries |
| `ReadinessTransitionRecord` | Records a readiness label transition |
| `AuthorityChangeRecord` | Records an authority (authoritative ↔ non-authoritative) change |
| `RoutingChangeRecord` | Records a provider/routing selection change |
| `OneAPIHistorySummary` | OneAPI lower-horizon historical summary (always `is_lower_horizon_only=True`) |
| `TopologyChangeKind` | Enumeration of recognisable change event types |

---

## Module location

```
windows_client/status_board_v2/topology_history.py
```

The module is also importable from the package:

```python
from windows_client.status_board_v2 import (
    TopologyHistoryRecorder,
    TOPOLOGY_HISTORY_AUTHORITY,
    TopologyChangeKind,
    ReadinessTransitionRecord,
    AuthorityChangeRecord,
    RoutingChangeRecord,
    OneAPIHistorySummary,
    TopologyHistoryEntry,
    TopologySnapshot,
    TopologyHistoryBuffer,
)
```

---

## Public API

### Authority sentinel

```python
TOPOLOGY_HISTORY_AUTHORITY: str
# = "windows_client.status_board_v2.topology_history.TopologyHistoryRecorder"
```

Confirms that a `TopologyHistoryEntry` or `TopologySnapshot` was produced by
the canonical PR-14 recorder (not assembled ad-hoc).

---

### TopologyChangeKind

```python
class TopologyChangeKind(str, Enum):
    readiness_transition    # readiness label changed
    authority_changed       # is_authoritative flag flipped
    provider_changed        # primary provider changed
    routing_changed         # routing authority source changed
    oneapi_status_changed   # OneAPI lower-horizon summary changed
    topology_degraded       # entered degraded/partial/unavailable state
    topology_recovered      # recovered back to canonical state
    snapshot_only           # periodic observability snapshot (no specific change)
```

---

### ReadinessTransitionRecord

Records a readiness state transition (e.g. `"canonical"` → `"degraded"`).

```python
class ReadinessTransitionRecord:
    from_readiness: str         # label before transition
    to_readiness: str           # label after transition
    was_authoritative: bool     # was previous state authoritative?
    became_authoritative: bool  # is new state authoritative?
    transition_note: str        # human-readable note; explicitly flags non-authoritative transitions
```

**Semantic guarantee:** When `became_authoritative` is `False`, `transition_note`
explicitly states that the new state is NOT authoritative and that
degraded/fallback history must not be treated as authoritative truth.

---

### AuthorityChangeRecord

Records a change in topology authority.

```python
class AuthorityChangeRecord:
    from_authoritative: bool
    to_authoritative: bool
    from_label: str
    to_label: str
    change_note: str    # explicitly notes when authority is lost
```

---

### RoutingChangeRecord

Records a provider or routing selection change.

```python
class RoutingChangeRecord:
    from_provider: Optional[str]
    to_provider: Optional[str]
    from_source: Optional[str]
    to_source: Optional[str]
    change_note: str
```

---

### OneAPIHistorySummary

Historical OneAPI lower-horizon status summary.

```python
class OneAPIHistorySummary:
    horizon_status: str             # "present" | "absent" | ...
    is_lower_horizon_only: bool     # ALWAYS True — invariant
    summary_note: str               # explicitly states lower-horizon-only constraint
```

**Invariant:** `is_lower_horizon_only` is **always `True`**.  OneAPI is never
represented as a canonical routing peer in any historical view.

---

### TopologyHistoryEntry

A single timestamped history record.

```python
class TopologyHistoryEntry:
    entry_id: str                                       # UUID
    change_kind: TopologyChangeKind
    readiness_label: str                                # "canonical" | "degraded" | "partial" | "unavailable"
    is_authoritative: bool                              # False for all degraded/fallback entries
    is_degraded: bool
    is_partial: bool
    is_unavailable: bool
    readiness_transition: Optional[ReadinessTransitionRecord]
    authority_change: Optional[AuthorityChangeRecord]
    routing_change: Optional[RoutingChangeRecord]
    oneapi_summary: Optional[OneAPIHistorySummary]      # always is_lower_horizon_only=True
    source_authority: str                               # TOPOLOGY_HISTORY_AUTHORITY

    def to_dict(self) -> Dict[str, Any]: ...
    def to_json(self, **kwargs) -> str: ...
```

---

### TopologySnapshot

A point-in-time snapshot, suitable for diffing.

```python
class TopologySnapshot:
    snapshot_id: str                        # UUID
    readiness_label: str
    is_authoritative: bool
    is_degraded: bool
    is_partial: bool
    is_unavailable: bool
    provider_id: Optional[str]
    routing_authority_source: Optional[str]
    oneapi_horizon_present: bool
    oneapi_is_lower_horizon_only: bool      # ALWAYS True — invariant
    stability_indicator: str                # "stable" | "degraded" | "partial" | "unavailable"
    source_authority: str

    def to_dict(self) -> Dict[str, Any]: ...
    def to_json(self, **kwargs) -> str: ...
```

**`stability_indicator` values:**

| Value | Condition |
|-------|-----------|
| `"stable"` | `is_authoritative=True` and not degraded/partial/unavailable |
| `"degraded"` | `is_degraded=True` or non-authoritative |
| `"partial"` | `is_partial=True` |
| `"unavailable"` | `is_unavailable=True` |

---

### TopologyHistoryBuffer

Bounded in-memory buffer for history entries (FIFO eviction when full).

```python
class TopologyHistoryBuffer:
    max_size: int                           # default 100
    entries: List[TopologyHistoryEntry]     # insertion order

    def add_entry(entry: TopologyHistoryEntry) -> None: ...
    def clear() -> None: ...

    @property
    def latest() -> Optional[TopologyHistoryEntry]: ...   # most recent
    @property
    def oldest() -> Optional[TopologyHistoryEntry]: ...   # first / oldest

    def to_list() -> List[Dict[str, Any]]: ...
    def __len__() -> int: ...
```

---

### TopologyHistoryRecorder

The main observability surface.

```python
class TopologyHistoryRecorder:
    # From InspectionReport (preferred — richest source)
    def record_from_inspection_report(report) -> Optional[TopologyHistoryEntry]: ...
    def snapshot_from_inspection_report(report) -> TopologySnapshot: ...

    # From TopologyConstellationLayout
    def record_from_layout(layout) -> Optional[TopologyHistoryEntry]: ...
    def snapshot_from_layout(layout) -> TopologySnapshot: ...

    # From DesktopClientViewModel
    def record_from_view_model(vm) -> Optional[TopologyHistoryEntry]: ...
    def snapshot_from_view_model(vm) -> TopologySnapshot: ...

    # Comparison and analysis
    def compare_snapshots(before, after) -> Dict[str, Any]: ...
    def stability_summary(buf: TopologyHistoryBuffer) -> Dict[str, Any]: ...
```

All methods handle `None` gracefully — `record_from_*` returns `None` for
`None` inputs; `snapshot_from_*` returns an unavailable snapshot for `None`
inputs.

#### `compare_snapshots` return dict keys

| Key | Type | Description |
|-----|------|-------------|
| `readiness_changed` | `bool` | `readiness_label` changed |
| `authority_changed` | `bool` | `is_authoritative` changed |
| `provider_changed` | `bool` | `provider_id` changed |
| `routing_source_changed` | `bool` | `routing_authority_source` changed |
| `oneapi_presence_changed` | `bool` | `oneapi_horizon_present` changed |
| `stability_changed` | `bool` | `stability_indicator` changed |
| `readiness_transition` | `Optional[ReadinessTransitionRecord]` | present if readiness changed |
| `authority_change` | `Optional[AuthorityChangeRecord]` | present if authority changed |
| `routing_change` | `Optional[RoutingChangeRecord]` | present if provider/routing changed |
| `any_change` | `bool` | `True` if any flag above is `True` |
| `before_authority` | `str` | `TOPOLOGY_HISTORY_AUTHORITY` sentinel |

#### `stability_summary` return dict keys

| Key | Type | Description |
|-----|------|-------------|
| `total_entries` | `int` | total entries in buffer |
| `canonical_count` | `int` | entries with `readiness_label == "canonical"` |
| `degraded_count` | `int` | entries with `is_degraded == True` |
| `partial_count` | `int` | entries with `is_partial == True` |
| `unavailable_count` | `int` | entries with `is_unavailable == True` |
| `authoritative_count` | `int` | entries with `is_authoritative == True` |
| `non_authoritative_count` | `int` | entries with `is_authoritative == False` |
| `stability_ratio` | `float` | `authoritative_count / total_entries` (0.0–1.0) |
| `overall_stability` | `str` | `"stable"` / `"mostly_stable"` / `"unstable"` / `"unknown"` |
| `source_authority` | `str` | `TOPOLOGY_HISTORY_AUTHORITY` sentinel |

`overall_stability` values:

| Value | Condition |
|-------|-----------|
| `"stable"` | `stability_ratio == 1.0` |
| `"mostly_stable"` | `stability_ratio >= 0.75` |
| `"unstable"` | `stability_ratio < 0.75` |
| `"unknown"` | empty buffer |

---

## Usage examples

### Recording from an inspection report (preferred)

```python
from windows_client.status_board_v2.topology_history import (
    TopologyHistoryRecorder,
    TopologyHistoryBuffer,
    TOPOLOGY_HISTORY_AUTHORITY,
)
from windows_client.status_board_v2.topology_inspector import TopologyInspector
from windows_client.status_board_v2.topology_layout import build_constellation_layout
from core.desktop_consumption_adapter import adapt_integration_payload

vm = adapt_integration_payload(payload)
layout = build_constellation_layout(vm)
inspector = TopologyInspector()
report = inspector.inspect_layout(layout)

recorder = TopologyHistoryRecorder()
buf = TopologyHistoryBuffer(max_size=50)

# Record a history entry
entry = recorder.record_from_inspection_report(report)
if entry:
    buf.add_entry(entry)
    print(entry.readiness_label)            # "canonical"
    print(entry.is_authoritative)           # True
    print(entry.change_kind)               # "snapshot_only"
    print(entry.oneapi_summary.is_lower_horizon_only)  # True

# Take a snapshot
snap = recorder.snapshot_from_inspection_report(report)
print(snap.stability_indicator)            # "stable"
print(snap.oneapi_is_lower_horizon_only)   # True
```

### Comparing snapshots to detect changes

```python
snap_before = recorder.snapshot_from_inspection_report(report_t1)
snap_after  = recorder.snapshot_from_inspection_report(report_t2)

diff = recorder.compare_snapshots(snap_before, snap_after)
if diff["any_change"]:
    if diff["readiness_changed"]:
        tr = diff["readiness_transition"]
        print(f"Readiness: {tr.from_readiness} → {tr.to_readiness}")
        print(f"Became authoritative: {tr.became_authoritative}")
        # transition_note explicitly warns when new state is non-authoritative
        print(tr.transition_note)
    if diff["authority_changed"]:
        print(diff["authority_change"].change_note)
    if diff["provider_changed"]:
        print(diff["routing_change"].change_note)
```

### Stability summary over a buffer

```python
buf = TopologyHistoryBuffer(max_size=100)
# ... add entries over time ...

summary = recorder.stability_summary(buf)
print(summary["overall_stability"])     # "stable" / "mostly_stable" / "unstable"
print(summary["stability_ratio"])       # fraction of authoritative entries
print(summary["degraded_count"])        # how many were degraded
```

### Starting from the view-model directly

```python
entry = recorder.record_from_view_model(vm)
snap  = recorder.snapshot_from_view_model(vm)
```

---

## Semantic invariants

These invariants are enforced and tested:

1. `OneAPIHistorySummary.is_lower_horizon_only` is **always `True`** — OneAPI
   is never represented as a canonical routing peer in any historical view.

2. `TopologySnapshot.oneapi_is_lower_horizon_only` is **always `True`**.

3. Degraded/fallback entries always have `is_authoritative = False`.  They are
   never re-promoted to authoritative truth.

4. When `compare_snapshots` produces a `ReadinessTransitionRecord` into a
   non-authoritative state, `became_authoritative` is `False` and
   `transition_note` explicitly states the non-authoritative constraint.

5. `snapshot_from_*` methods always return a `TopologySnapshot` — `None` input
   produces an unavailable snapshot (`is_unavailable=True`,
   `is_authoritative=False`, `readiness_label="unavailable"`).

6. `record_from_*` methods return `None` when given `None` input (no exception).

7. The recorder builds exclusively on the PR-9/PR-11/PR-12/PR-13 pipeline and
   never bypasses it to reconstruct truth from raw nested payload dicts.

8. Every `TopologyHistoryEntry` and `TopologySnapshot` carries a
   `source_authority` equal to `TOPOLOGY_HISTORY_AUTHORITY`.

9. `stability_summary` on an empty buffer returns `overall_stability = "unknown"`.

10. `stability_ratio` is the fraction of `authoritative_count / total_entries`;
    degraded/fallback entries are always counted in `non_authoritative_count`.

---

## Integration with PR-9 through PR-13

```
PR-9  DesktopClientViewModel
         │
         ▼
PR-11 build_constellation_layout()  → TopologyConstellationLayout
         │
         ▼
PR-12 TopologyRenderer  (visual rendering)
         │
         ▼
PR-13 TopologyInspector → InspectionReport  (live inspection)
         │
         ▼
PR-14 TopologyHistoryRecorder  (observability / history)
         │
         ├─→ TopologyHistoryEntry  (change record)
         ├─→ TopologySnapshot      (point-in-time snapshot)
         ├─→ compare_snapshots()   (diff between two snapshots)
         └─→ stability_summary()   (aggregate stability over buffer)
```

The history recorder can be used at any level of the pipeline:
- `record_from_inspection_report` / `snapshot_from_inspection_report` — richest
- `record_from_layout` / `snapshot_from_layout` — intermediate
- `record_from_view_model` / `snapshot_from_view_model` — base level

---

## Related documents

- [`docs/DIAGNOSTICS_INSPECTION_INTERACTION.md`](DIAGNOSTICS_INSPECTION_INTERACTION.md) — PR-13
- [`docs/TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md`](TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md) — PR-12
- [`docs/TOPOLOGY_CONSTELLATION_LAYOUT.md`](TOPOLOGY_CONSTELLATION_LAYOUT.md) — PR-11
- [`docs/DESKTOP_STATUS_BOARD_UI.md`](DESKTOP_STATUS_BOARD_UI.md) — PR-10
- [`docs/DESKTOP_CONSUMPTION_ADAPTER.md`](DESKTOP_CONSUMPTION_ADAPTER.md) — PR-9
- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — overall status board V2 design
