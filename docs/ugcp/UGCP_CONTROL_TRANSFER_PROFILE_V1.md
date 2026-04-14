# UGCP Control Transfer Profile v1 (PR-5, realization-v2 side)

## 1) Scope and intent

This profile unifies the center-side control-transfer semantics for:
- handoff preparation and handoff contracts,
- target takeover/adoption,
- delegated execution transfer signals,
- transfer terminal outcomes (rejection/cancellation/expiry/failure/timeout),
- adoption/resume progression.

This is an **incremental alignment profile**, not a claim that all transfer code paths are fully converged.

## 2) Frozen control-transfer vocabulary

Canonical family:
- `handoff`
- `takeover`
- `delegated_execution`

Canonical states:
- non-terminal: `not_started`, `preparing`, `ready`, `dispatched`, `adopting`, `resumed`, `in_progress`
- terminal: `completed`, `rejected`, `cancelled`, `expired`, `failed`, `timed_out`
- fallback: `unknown` (compat/parse fallback; no canonical outbound transitions)

Canonical terminal reasons:
- `completed`, `rejected`, `cancelled`, `expired`, `failed`, `timed_out`
- plus canonicalized reasons for transfer-specific gates: `blocked`, `takeover_disallowed_by_policy`, `session_anchor_missing`, `invalid_payload`, `resume_unavailable`.

## 3) Canonical transfer state graph

Allowed progression (high-level):

`not_started → preparing → ready → dispatched → adopting/resumed → in_progress → terminal`

Terminal set:

`completed | rejected | cancelled | expired | failed | timed_out`

Terminals are absorbing (no outbound transitions).

## 4) Existing-family alignment under one profile

| Existing family | Existing state/kind | Canonical transfer state |
|---|---|---|
| Delegated pre-handoff intent | `not_started/preparing/ready/dispatched/cancelled/failed` | same-name mapping |
| Delegated handoff contract | `draft/sealed/dispatched/expired/cancelled` | `preparing/ready/dispatched/expired/cancelled` |
| Target takeover | `pending/adopted/executing/succeeded/failed/blocked/rejected` | `adopting/adopting/in_progress/completed/failed/rejected/rejected` |
| Android delegated signal | `ack/progress/result/timeout/cancelled` (+ result_kind) | `dispatched/in_progress/completed|failed/timed_out/cancelled` |

## 5) Canonical truth-chain entry for transfer transitions

Transfer transitions enter canonical truth via `TruthEvent` records produced by:

- `core.ugcp_control_transfer_profile.build_control_transfer_truth_event(...)`

The event payload includes profile/family/current+previous state/terminal reason/source contract and session identities.
These events are the transfer-side handoff into the canonical truth chain before outward projection surfaces.

## 6) Realization-v2 implementation anchor

Canonical module:
- `core/ugcp_control_transfer_profile.py`

Key profile APIs:
- family/state/reason enums
- canonical transition table + `can_transition(...)`
- cross-family mapping helpers for handoff/takeover/delegated signals
- canonical transfer truth-event builder
