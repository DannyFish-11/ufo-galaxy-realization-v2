# V2 Canonical Android Truth Contract

> Maintainer reference for the Android-originated evidence that V2 governance
> is allowed to trust after the PR-5 / PR-7A / PR-8 / PR-13 / PR-14 hardening
> work.
>
> Primary modules:
> `core/unified_execution_governance.py`,
> `core/android_mode_gate_policy.py`,
> `core/unified_governance_semantics.py`,
> `core/android_evidence_integration_pipeline.py`,
> `core/closed_loop_governance_consolidation.py`,
> `core/execution_governance_audit_authority.py`,
> `galaxy_gateway/android/models.py`
>
> Primary regression suites:
> `tests/test_pr5_execution_runtime_truth_binding.py`,
> `tests/test_pr7a_android_governance_truth_hardening.py`,
> `tests/test_pr8_android_evidence_integration_e2e.py`,
> `tests/test_pr9_canonical_proof_input_diagnosis.py`,
> `tests/integration/test_pr6a_real_android_execution_governance_regression.py`,
> `tests/test_pr13_closed_loop_governance_consolidation.py`,
> `tests/test_pr14_governance_audit_authority.py`

## 1. Contract summary

V2 remains the canonical governance authority. Android supplies evidence; V2
classifies that evidence and decides whether it is strong enough to influence
canonical readiness or execution decisions.

After the recent hardening work, Android truth is only trusted through explicit,
reviewable contracts:

1. **Capability truth** — what Android claims it can do right now.
2. **Lifecycle truth** — whether Android has actually confirmed the execution
   lifecycle V2 believes is active.
3. **Execution runtime truth** — the canonical per-device snapshot that V2
   builds from Android runtime semantics, freshness metadata, reconciliation
   state, and active execution state.
4. **Governance evidence integration** — the PR-8 final gate that combines
   capability truth, lifecycle truth, audit authority, and closed-loop
   invariants.

The important governance change is that **missing, stale, conflicting, or
otherwise degraded Android truth is not treated as positive evidence anymore**.

## 2. Evidence V2 expects from Android

| Surface | What Android must supply | Where V2 models it | Passing shape | Degraded shape |
|---|---|---|---|---|
| Capability truth | Explicit registration capabilities plus runtime semantics fields such as `android_reported_mode`, execution eligibility flags, local inference flags, `android_semantics_contract_state`, freshness metadata, conflict lists, and downgrade reasons | `AndroidDevice.from_registration()`, `classify_canonical_proof_input_diagnosis()`, `resolve_android_execution_gate_decision()` | `proof_input_class="complete"` | `missing`, `partial`, `malformed`, `unknown`, `downgraded`, `stale`, or `conflicting` |
| Lifecycle truth | Android execution events that let V2 compare active local executions with recent remote lifecycle evidence | `get_execution_lifecycle_truth_binding()` and `get_execution_runtime_snapshot()` | `android_remote_confirmed` | `missing_remote`, `stale_remote`, or `conflicting_remote` |
| Execution runtime truth | A current runtime snapshot that carries Android semantics, freshness, reconciliation, busy state, fallback tier, and latest execution-event metadata | `get_execution_runtime_snapshot()` and `build_unified_governance_state()` | Snapshot fields are present and internally consistent | Missing/stale/conflicting fields remain explicit in `proof_input_diagnosis` and `decision_causality` |
| Real Android participation evidence | For real-device regressions, an artifact referenced by `REAL_ANDROID_GOVERNANCE_EVIDENCE_PATH` containing a real device claim plus `device_state_snapshot` and `device_execution_event` payloads | `tests/integration/test_pr6a_real_android_execution_governance_regression.py` | `verification_kind=real_device` or equivalent marker; usable snapshot + execution payloads | Missing real-device claim or missing payloads skips/fails the real-device regression path |

### Capability truth details

- `galaxy_gateway/android/models.py` hardens registration so absent
  `capabilities` become `DeviceCapability.NONE` and
  `capabilities_explicitly_reported=False`.
- `core/unified_execution_governance.py::classify_canonical_proof_input_diagnosis()`
  is the canonical classifier for Android capability/runtime semantics.
- `core/android_mode_gate_policy.py::resolve_android_execution_gate_decision()`
  treats `missing`, `stale`, `conflicting`, and `downgraded` capability truth as
  immediate deny conditions.

This means V2 does **not** infer readiness from device registration alone, and
does **not** collapse degraded Android semantics into a generic denial reason.

### Lifecycle truth details

`get_execution_lifecycle_truth_binding(device_id)` compares V2-local active
executions with the latest Android execution event:

- `v2_local_only` — clean idle only when V2 has no active execution and Android
  has no event to confirm.
- `android_remote_confirmed` — V2 active execution agrees with recent Android
  lifecycle evidence.
- `missing_remote` — V2 is tracking active work but Android has supplied no
  lifecycle evidence.
- `stale_remote` — Android lifecycle evidence exists but is too old.
- `conflicting_remote` — V2-local and Android-remote lifecycle state disagree.

Those fields are embedded in both `get_execution_runtime_snapshot()` output and
`build_unified_governance_state(...).devices[*].governance_precedence[*].decision_causality`.

### Execution runtime truth details

The runtime snapshot is where maintainers should look when verifying whether V2
is using Android truth correctly. The per-device snapshot includes:

- Android-reported mode / readiness / eligibility / local inference fields
- Android semantics contract completeness, freshness, conflicts, unknown keys,
  malformed keys, and downgrade reasons
- latest execution event phase / age
- reconciliation and snapshot continuity fields
- `android_lifecycle_truth_*`
- the exact `proof_input_diagnosis` and canonical gate outcome later threaded
  into `decision_causality`

If a future change hides one of those fields, converts it to an implicit default,
or stops propagating it into causality, it is changing the truth contract.

`build_unified_governance_state()` also exposes the PR-8 integration summary per
device (`android_evidence_integration`) and mirrors its key diagnostics in
`decision_causality`:

- `android_evidence_integration_execution_id`
- `android_evidence_integration_decision`
- `android_evidence_integration_allowed`
- `android_evidence_integration_grade`
- `android_evidence_integration_degradation_causes`

This keeps capability/lifecycle/runtime diagnostics and final integration
diagnostics aligned in one canonical governance view.

## 3. Missing, stale, and conflicting truth handling

### Capability truth

`classify_canonical_proof_input_diagnosis()` returns one stable
`proof_input_class` with explicit causes:

- `conflicting` — semantic contradiction inside Android-reported fields
- `malformed` — required canonical gate metadata present but invalid
- `unknown` — unknown keys indicate contract drift
- `downgraded` — Android explicitly reports degraded truth
- `stale` — freshness state is stale or authority was downgraded
- `partial` — required metadata keys are missing
- `missing` — no Android capability semantics were reported
- `complete` — all required semantics present, fresh, and conflict-free

Only `complete` is positive evidence. Degraded classes are preserved in
`proof_input_diagnosis`, and PR-7A additionally upgrades `missing`, `stale`,
`conflicting`, and `downgraded` into canonical gate denials.

### Lifecycle truth

Lifecycle truth is degraded whenever V2 cannot prove that Android remotely
confirmed the execution it is governing:

- active execution + no Android lifecycle event → `missing_remote`
- active execution + old Android lifecycle event → `stale_remote`
- contradictory local vs remote lifecycle state → `conflicting_remote`

These states are not advisory-only; they become explicit governance impact in
runtime snapshots and decision causality.

### Integration behavior

`evaluate_android_evidence_integration()` is the final PR-8 check. It evaluates
four dimensions:

1. capability truth
2. lifecycle truth
3. audit authority
4. closed-loop invariants

If **any** dimension is absent or degraded, `integration_allowed=False` and
`degradation_causes` lists the exact reasons. There is no optimistic “best
effort allow” path here.

## 4. Governance fallback semantics that are now explicitly bounded

`OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY` documents the fallback paths
that V2 no longer treats as success:

| Bounded fallback | Meaning now |
|---|---|
| Capability truth absent fallback | No Android capability snapshot means degraded capability truth; V2 must not infer readiness from registration defaults |
| Lifecycle V2-local-only fallback | V2-local bookkeeping without Android lifecycle confirmation is not execution truth when work is active |
| Audit chain absent fallback | Missing lifecycle/uplink history means audit authority is absent or degraded, not silently clean |
| Closed-loop unknown fallback | `unknown` loop stage or broken invariants is degraded governance evidence, not an idle/healthy default |

Two implementation rules follow from this:

- functions are written to return diagnosable fallback objects instead of
  raising, but those fallback objects are **safe** fallbacks (`missing`,
  `v2_local_only`, `absent`, `degraded`) rather than optimistic passes;
- V2-owned canonical state still wins on conflicts, especially for terminal
  lifecycle truth and post-terminal uplinks.

## 5. Invariants regression tests are protecting

These suites are the maintainer guardrails for future refactors:

| Test suite | Invariants protected |
|---|---|
| `tests/test_pr9_canonical_proof_input_diagnosis.py` | Proof-input classes stay distinguishable; conflicts and degradation causes remain explicit and stable |
| `tests/test_pr7a_android_governance_truth_hardening.py` | Absent/stale/conflicting/downgraded capability truth denies the canonical Android gate; absent registration capabilities stay `NONE` and explicitly unreported; causality exposes truth-quality fields |
| `tests/test_pr5_execution_runtime_truth_binding.py` | Runtime snapshots and causality must expose lifecycle truth quality; `missing_remote`, `stale_remote`, and `conflicting_remote` remain diagnosable governance degradation |
| `tests/test_pr8_android_evidence_integration_e2e.py` | All four dimensions are evaluated together; degraded evidence denies integration; optimistic fallback paths remain closed; verdicts stay JSON-serialisable and isolated per device |
| `tests/integration/test_pr6a_real_android_execution_governance_regression.py` | A claimed “real Android” path must actually provide real-device evidence and drive the V2 governance path with Android payloads, not Python-only stubs |
| `tests/test_pr13_closed_loop_governance_consolidation.py` | Closed-loop stage ordering and cross-stage invariants (activation → execution → observation → reconciliation → completion) remain enforced |
| `tests/test_pr14_governance_audit_authority.py` | Audit authority chain remains monotonic and center-authoritative; terminal truth cannot be overridden by uplink observations; cross-device isolation remains absolute |

## 6. Reviewer checklist for future changes

When reviewing Android governance changes, confirm:

1. Android evidence still arrives as explicit data, not synthesized defaults.
2. Missing/stale/conflicting truth still degrades diagnostics and final gate
   outputs instead of being normalized away.
3. `decision_causality` still carries the same truth-quality and degradation
   fields that operators and tests use.
4. PR-8 integration still denies when any evidence dimension is degraded.
   For capability truth, only `proof_input_class="complete"` is a passing
   integration input; all other classes are non-passing.
5. PR-13 / PR-14 invariants still make V2-owned terminal and authority truth win
   over late or conflicting Android observations.

If a change breaks one of those rules, it is not just a refactor; it is a
contract change and should be reviewed as governance behavior.
