# Decision-Diff Telemetry

> **Status**: Active  
> **Introduced**: PR-14 (Add decision-diff telemetry for legacy vs canonical cross-device routing)  
> **Scope**: Observability only — no behavior changes to the final request decision path

---

## 1. What it captures

Decision-diff telemetry records **both the legacy and canonical decision
outputs** at key cross-device routing and scheduling decision points, so
maintainers can compare them side-by-side during a rollout.

### Decision points instrumented

| Decision point | Module | Description |
|---|---|---|
| `entry_mode` | `core/unified/entrypoint_router.py` | Whether a request is routed as `local` or `cross_device` |
| `candidate_selection` | Caller-driven via `record_candidate_diff` | Which devices are selected as cross-device execution candidates |

For each decision point, a `DecisionDiffRecord` is produced containing:

- `request_id` — end-to-end correlation / trace ID
- `decision_point` — which gate emitted the record
- `requested_target_device` — explicit target device from the caller, if any
- `legacy_decision` — outcome the **legacy** path would have produced
- `canonical_decision` — outcome the **canonical** (readiness-based) path produced
- `legacy_selected_device_ids` / `canonical_selected_device_ids` — device sets
- `ready_device_count` — devices that passed the canonical readiness gate
- `orchestration_ready_device_count` — devices that passed the orchestration gate
- `required_capabilities` — capability labels required for the request
- `diff_reason_codes` — normalised strings explaining why decisions differ
- `sources` — subsystem labels for auditability
- `timestamp` — Unix float when the record was created
- `decisions_differ` — boolean shortcut

---

## 2. How to enable it

Decision-diff telemetry is **disabled by default** to keep production logs
low-noise.

### Enable via environment variable

```bash
export GALAXY_DECISION_DIFF_TELEMETRY=1
```

Accepted values: `1`, `true`, `yes` (case-insensitive).  Any other value
(including the default of unset / `0`) keeps telemetry disabled.

### Disable again

```bash
unset GALAXY_DECISION_DIFF_TELEMETRY
# or
export GALAXY_DECISION_DIFF_TELEMETRY=0
```

---

## 3. What the telemetry emits

### Structured log entries

When a diff record is created, a log entry is emitted to the
`Galaxy.DecisionDiffTelemetry` logger at:

- **WARNING** level — when `legacy_decision != canonical_decision`
- **DEBUG** level — when both decisions match

Example log line:

```
WARNING Galaxy.DecisionDiffTelemetry decision_diff decision_point=entry_mode
  request_id=abc123 legacy=cross_device canonical=local diff=True
  reason_codes=legacy_used_online_presence,canonical_requires_readiness
```

### In-memory ring buffer

Records are also stored in a capped, in-process ring buffer (256 entries
maximum).  Access it for debugging or integration testing:

```python
from core.decision_diff_telemetry import get_diff_store, clear_diff_store

records = get_diff_store()   # list[DecisionDiffRecord]
clear_diff_store()           # reset (testing only)
```

### State event bus (best-effort)

Each record is also forwarded to the `StateEventBus` with
`event_kind="decision_diff"`.  If the bus is unavailable, this is silently
suppressed.

---

## 4. How to interpret differences during rollout

### `decisions_differ = False`

The legacy and canonical paths agreed.  No action required.

### `decisions_differ = True`

Review `diff_reason_codes` to understand why:

| Reason code | Meaning |
|---|---|
| `legacy_used_online_presence` | Legacy counted UDM online devices; canonical uses readiness |
| `canonical_requires_readiness` | Canonical requires the device to pass all readiness criteria |
| `target_device_not_ready` | The requested target device failed the canonical readiness gate |
| `target_device_not_eligible` | The requested target device failed orchestration eligibility |
| `capability_mismatch` | One or more required capabilities were not matched |
| `insufficient_orchestration_ready_devices` | Fewer candidates passed the orchestration gate than required |
| `formation_unavailable` | Formation/mesh layer returned no usable formation |
| `session_unavailable` | No active session was found for the candidate device |
| `decisions_match` | Both paths produced the same decision (diagnostic only) |

### Interpreting divergence patterns

**Canonical is more strict, legacy was lenient**  
`legacy=cross_device`, `canonical=local`  
→ The canonical path requires genuine readiness; legacy was satisfied by
online presence alone.  This divergence is expected during rollout and is
not a bug.  Verify the device's actual readiness state.

**Canonical is more permissive**  
`legacy=local`, `canonical=cross_device`  
→ Less common.  The canonical path detected a device as ready that the
legacy UDM online-count heuristic missed (e.g. a newly connected device
not yet reflected in the online count).

**Device set differs**  
`legacy_selected_device_ids ≠ canonical_selected_device_ids`  
→ The canonical candidate-resolution layer applied stricter gates (readiness
+ participation + capability).  Devices missing from the canonical set
should be inspected for readiness / capability gaps.

---

## 5. Final decision behavior

**Enabling telemetry does not change the final decision** returned to callers.
The `resolved` value in `resolve_entry_mode()` is computed before the
telemetry hook runs, and the hook is wrapped in a broad `try/except` that
suppresses all errors.

---

## 6. Adding new telemetry hooks

To hook a new decision point:

1. Import and check `is_telemetry_enabled()` at the decision site.
2. Compute what both paths would decide (keep each computation wrapped in
   `try/except`).
3. Call `record_entry_mode_diff()` or `record_candidate_diff()` (or add a
   new helper to `core/decision_diff_telemetry.py` following the same
   pattern).
4. Add tests in `tests/test_pr14_decision_diff_telemetry.py`.

---

## 7. Module reference

**`core/decision_diff_telemetry.py`**  
Authority sentinel: `DECISION_DIFF_TELEMETRY_AUTHORITY`

| Symbol | Purpose |
|---|---|
| `DecisionDiffRecord` | Serialisable diff record dataclass |
| `record_entry_mode_diff(...)` | Hook for entry-mode decision point |
| `record_candidate_diff(...)` | Hook for candidate selection decision point |
| `get_diff_store()` | Return snapshot of ring buffer |
| `clear_diff_store()` | Empty ring buffer (testing) |
| `is_telemetry_enabled()` | Feature flag check |
| `REASON_*` constants | Normalised diff reason code strings |
