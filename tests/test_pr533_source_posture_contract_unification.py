"""tests/test_pr533_source_posture_contract_unification.py
===========================================================
Regression tests for PR-533 / PR-1 dual-repo unification track:
MAIN-repo source runtime posture contract surface.

Coverage matrix
---------------
Group A — SourcePostureValue enum (contract layer)
  A01. Both canonical values are present and match the wire format.
  A02. Enum is a str subclass (JSON-serialisable without extra steps).

Group B — Validation helpers
  B01. validate_source_posture_value accepts 'control_only'.
  B02. validate_source_posture_value accepts 'join_runtime'.
  B03. validate_source_posture_value rejects unknown values.
  B04. validate_source_posture_value rejects None.
  B05. validate_source_posture_value returns (bool, Optional[str]) tuple.

Group C — resolve_source_posture_value helper
  C01. None resolves to CONTROL_ONLY (default safe posture).
  C02. 'join_runtime' resolves to JOIN_RUNTIME.
  C03. 'control_only' resolves to CONTROL_ONLY.
  C04. Unknown string resolves to CONTROL_ONLY (safe default).
  C05. Whitespace and mixed-case are normalised.

Group D — SourcePostureContractField model
  D01. Default posture is 'control_only'.
  D02. Accepts 'join_runtime'.
  D03. Rejects invalid values with ValueError.
  D04. Normalises to lower-case.
  D05. is_control_only / is_join_runtime properties work correctly.
  D06. posture_enum property returns SourcePostureValue.
  D07. to_dict() includes source_runtime_posture and authority.

Group E — build_source_posture_field builder
  E01. None hint → default CONTROL_ONLY field.
  E02. 'join_runtime' hint → JOIN_RUNTIME field.
  E03. Unknown hint → default CONTROL_ONLY field (graceful).
  E04. Builder never raises.

Group F — Policy / authority sentinels
  F01. SOURCE_POSTURE_CONTRACT_AUTHORITY is a non-empty string.
  F02. SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY is a non-empty string.
  F03. SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY is non-empty.
  F04. SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL is non-empty.
  F05. SOURCE_POSTURE_VALID_VALUES contains exactly the two canonical values.

Group G — HandoffEnvelopeV2 posture integration
  G01. HandoffEnvelopeV2 has a 'source_runtime_posture' field.
  G02. Default value is 'control_only'.
  G03. build_handoff_envelope_v2() propagates 'join_runtime'.
  G04. from_bridge_inputs() propagates 'join_runtime'.
  G05. HandoffSourceSummary has 'source_runtime_posture' field.
  G06. build_handoff_envelope_v2() populates HandoffSourceSummary.source_runtime_posture.
  G07. to_compact_summary() includes 'source_runtime_posture'.
  G08. Unknown posture hint falls back to 'control_only' in builders.
  G09. Round-trip to_dict → from_dict preserves source_runtime_posture.
  G10. Existing tests still pass (no-posture construction still works).

Group H — SourceDispatchDecision posture integration
  H01. SourceDispatchDecision has 'source_runtime_posture' field.
  H02. Default is 'control_only'.
  H03. build_source_dispatch_decision() propagates 'join_runtime'.
  H04. to_compact_summary() includes 'source_runtime_posture'.
  H05. Round-trip to_dict → from_dict preserves posture.

Group I — SourceDispatchPlan posture integration
  I01. SourceDispatchPlan has 'source_runtime_posture' field.
  I02. Default is 'control_only'.
  I03. build_source_dispatch_plan() propagates from decision.
  I04. build_source_dispatch_plan() accepts explicit posture override.
  I05. Round-trip to_dict → from_dict preserves posture.

Group J — SourceDispatchResult posture integration
  J01. SourceDispatchResult has 'source_runtime_posture' field.
  J02. Default is 'control_only'.
  J03. build_source_dispatch_result() propagates 'join_runtime'.
  J04. to_compact_summary() includes 'source_runtime_posture'.
  J05. Round-trip to_dict → from_dict preserves posture.

Group K — Propagation chain Decision → Plan → Result
  K01. Posture flows: decision → plan (via build_source_dispatch_plan).
  K02. Posture flows: plan is independent from result when explicitly set.

Group L — contracts package root re-exports
  L01. SourcePostureValue importable from contracts.
  L02. SourcePostureContractField importable from contracts.
  L03. Sentinel constants importable from contracts.
  L04. build_source_posture_field importable from contracts.

Group M — Backwards compatibility / additive-only guarantees
  M01. HandoffEnvelopeV2 without posture kwarg still constructs.
  M02. SourceDispatchDecision without posture kwarg still constructs.
  M03. SourceDispatchResult without posture kwarg still constructs.
  M04. from_bridge_inputs() without source_runtime_posture still works.
  M05. Existing compact-summary fields not removed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Subject imports
# ---------------------------------------------------------------------------

from contracts.source_posture_contract import (
    SOURCE_POSTURE_CONTRACT_AUTHORITY,
    SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL,
    SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY,
    SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY,
    SOURCE_POSTURE_VALID_VALUES,
    SourcePostureContractField,
    SourcePostureValue,
    build_source_posture_field,
    posture_value_to_str,
    resolve_source_posture_value,
    validate_source_posture_value,
)
from contracts.handoff_envelope_v2 import (
    HandoffEnvelopeV2,
    HandoffSourceSummary,
    build_handoff_envelope_v2,
    from_bridge_inputs,
)
from contracts.source_dispatch import (
    SourceDispatchDecision,
    SourceDispatchMode,
    SourceDispatchPlan,
    SourceDispatchResult,
    build_source_dispatch_decision,
    build_source_dispatch_plan,
    build_source_dispatch_result,
)


# ===========================================================================
# Group A — SourcePostureValue enum (contract layer)
# ===========================================================================


def test_A01_enum_values_are_canonical() -> None:
    assert SourcePostureValue.CONTROL_ONLY.value == "control_only"
    assert SourcePostureValue.JOIN_RUNTIME.value == "join_runtime"


def test_A02_enum_is_str_subclass() -> None:
    assert isinstance(SourcePostureValue.CONTROL_ONLY, str)
    assert isinstance(SourcePostureValue.JOIN_RUNTIME, str)
    assert json.dumps(SourcePostureValue.CONTROL_ONLY) == '"control_only"'


# ===========================================================================
# Group B — Validation helpers
# ===========================================================================


def test_B01_validate_accepts_control_only() -> None:
    ok, err = validate_source_posture_value("control_only")
    assert ok is True
    assert err is None


def test_B02_validate_accepts_join_runtime() -> None:
    ok, err = validate_source_posture_value("join_runtime")
    assert ok is True
    assert err is None


def test_B03_validate_rejects_unknown() -> None:
    ok, err = validate_source_posture_value("hybrid_mode")
    assert ok is False
    assert err is not None
    assert "hybrid_mode" in err


def test_B04_validate_rejects_none() -> None:
    ok, err = validate_source_posture_value(None)
    assert ok is False
    assert err is not None


def test_B05_validate_returns_tuple() -> None:
    result = validate_source_posture_value("control_only")
    assert isinstance(result, tuple)
    assert len(result) == 2


# ===========================================================================
# Group C — resolve_source_posture_value helper
# ===========================================================================


def test_C01_none_resolves_to_control_only() -> None:
    assert resolve_source_posture_value(None) == SourcePostureValue.CONTROL_ONLY


def test_C02_join_runtime_resolves() -> None:
    assert resolve_source_posture_value("join_runtime") == SourcePostureValue.JOIN_RUNTIME


def test_C03_control_only_resolves() -> None:
    assert resolve_source_posture_value("control_only") == SourcePostureValue.CONTROL_ONLY


def test_C04_unknown_resolves_to_control_only() -> None:
    assert resolve_source_posture_value("something_random") == SourcePostureValue.CONTROL_ONLY


def test_C05_normalises_whitespace_and_case() -> None:
    assert resolve_source_posture_value("  JOIN_RUNTIME  ") == SourcePostureValue.JOIN_RUNTIME
    assert resolve_source_posture_value("  CONTROL_ONLY  ") == SourcePostureValue.CONTROL_ONLY


# ===========================================================================
# Group D — SourcePostureContractField model
# ===========================================================================


def test_D01_default_posture_is_control_only() -> None:
    field = SourcePostureContractField()
    assert field.source_runtime_posture == "control_only"


def test_D02_accepts_join_runtime() -> None:
    field = SourcePostureContractField(source_runtime_posture="join_runtime")
    assert field.source_runtime_posture == "join_runtime"


def test_D03_rejects_invalid_value() -> None:
    with pytest.raises((ValueError, Exception)):
        SourcePostureContractField(source_runtime_posture="bad_value")


def test_D04_normalises_to_lower_case() -> None:
    field = SourcePostureContractField(source_runtime_posture="JOIN_RUNTIME")
    assert field.source_runtime_posture == "join_runtime"


def test_D05_is_control_only_is_join_runtime_properties() -> None:
    co = SourcePostureContractField(source_runtime_posture="control_only")
    jr = SourcePostureContractField(source_runtime_posture="join_runtime")
    assert co.is_control_only is True
    assert co.is_join_runtime is False
    assert jr.is_control_only is False
    assert jr.is_join_runtime is True


def test_D06_posture_enum_property() -> None:
    field = SourcePostureContractField(source_runtime_posture="join_runtime")
    assert field.posture_enum == SourcePostureValue.JOIN_RUNTIME
    assert isinstance(field.posture_enum, SourcePostureValue)


def test_D07_to_dict_contains_authority() -> None:
    field = SourcePostureContractField()
    d = field.to_dict()
    assert "source_runtime_posture" in d
    assert "contract_authority" in d
    assert SOURCE_POSTURE_CONTRACT_AUTHORITY in d["contract_authority"]


# ===========================================================================
# Group E — build_source_posture_field builder
# ===========================================================================


def test_E01_none_hint_produces_control_only() -> None:
    field = build_source_posture_field(None)
    assert field.source_runtime_posture == "control_only"


def test_E02_join_runtime_hint_works() -> None:
    field = build_source_posture_field("join_runtime")
    assert field.source_runtime_posture == "join_runtime"


def test_E03_unknown_hint_falls_back_gracefully() -> None:
    field = build_source_posture_field("not_a_posture")
    assert field.source_runtime_posture == "control_only"


def test_E04_builder_never_raises() -> None:
    for bad in [None, "", "garbage", 42, {}, []]:  # type: ignore[list-item]
        field = build_source_posture_field(bad)  # type: ignore[arg-type]
        assert field is not None


# ===========================================================================
# Group F — Policy / authority sentinels
# ===========================================================================


def test_F01_authority_sentinel_non_empty() -> None:
    assert isinstance(SOURCE_POSTURE_CONTRACT_AUTHORITY, str)
    assert len(SOURCE_POSTURE_CONTRACT_AUTHORITY) > 0


def test_F02_no_entrymode_overload_policy_non_empty() -> None:
    assert isinstance(SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY, str)
    assert len(SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY) > 0


def test_F03_no_cross_device_enabled_overload_policy_non_empty() -> None:
    assert isinstance(SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY, str)
    assert len(SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY) > 0


def test_F04_pr1_unification_sentinel_non_empty() -> None:
    assert isinstance(SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL, str)
    assert len(SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL) > 0


def test_F05_valid_values_set_contains_exactly_two() -> None:
    assert "control_only" in SOURCE_POSTURE_VALID_VALUES
    assert "join_runtime" in SOURCE_POSTURE_VALID_VALUES
    assert len(SOURCE_POSTURE_VALID_VALUES) == 2


# ===========================================================================
# Group G — HandoffEnvelopeV2 posture integration
# ===========================================================================


def test_G01_handoff_envelope_has_posture_field() -> None:
    env = HandoffEnvelopeV2(trace_id="t1")
    assert hasattr(env, "source_runtime_posture")


def test_G02_handoff_envelope_default_is_control_only() -> None:
    env = HandoffEnvelopeV2(trace_id="t1")
    assert env.source_runtime_posture == "control_only"


def test_G03_build_handoff_envelope_v2_propagates_join_runtime() -> None:
    env = build_handoff_envelope_v2(
        trace_id="t2",
        source_device_id="phone_01",
        source_runtime_posture="join_runtime",
    )
    assert env.source_runtime_posture == "join_runtime"


def test_G04_from_bridge_inputs_propagates_join_runtime() -> None:
    env = from_bridge_inputs(
        trace_id="t3",
        task={"tool_name": "screenshot"},
        source_runtime_posture="join_runtime",
    )
    assert env.source_runtime_posture == "join_runtime"


def test_G05_handoff_source_summary_has_posture_field() -> None:
    summary = HandoffSourceSummary()
    assert hasattr(summary, "source_runtime_posture")
    assert summary.source_runtime_posture == "control_only"


def test_G06_build_handoff_env_populates_source_summary_posture() -> None:
    env = build_handoff_envelope_v2(
        trace_id="t4",
        source_runtime_posture="join_runtime",
    )
    assert env.source.source_runtime_posture == "join_runtime"


def test_G07_to_compact_summary_includes_posture() -> None:
    env = build_handoff_envelope_v2(
        trace_id="t5",
        source_runtime_posture="join_runtime",
    )
    summary = env.to_compact_summary()
    assert "source_runtime_posture" in summary
    assert summary["source_runtime_posture"] == "join_runtime"


def test_G08_unknown_posture_falls_back_to_control_only() -> None:
    env = build_handoff_envelope_v2(
        trace_id="t6",
        source_runtime_posture="invalid_posture",
    )
    assert env.source_runtime_posture == "control_only"


def test_G09_round_trip_to_dict_from_dict_preserves_posture() -> None:
    env = build_handoff_envelope_v2(
        trace_id="t7",
        source_runtime_posture="join_runtime",
    )
    d = env.to_dict()
    assert d["source_runtime_posture"] == "join_runtime"
    env2 = HandoffEnvelopeV2.from_dict(d)
    assert env2.source_runtime_posture == "join_runtime"


def test_G10_no_posture_kwarg_still_constructs() -> None:
    env = build_handoff_envelope_v2(trace_id="t8")
    assert env.source_runtime_posture == "control_only"
    assert env.trace_id == "t8"


# ===========================================================================
# Group H — SourceDispatchDecision posture integration
# ===========================================================================


def test_H01_decision_has_posture_field() -> None:
    dec = SourceDispatchDecision()
    assert hasattr(dec, "source_runtime_posture")


def test_H02_decision_default_is_control_only() -> None:
    dec = SourceDispatchDecision()
    assert dec.source_runtime_posture == "control_only"


def test_H03_build_decision_propagates_join_runtime() -> None:
    dec = build_source_dispatch_decision(
        trace_id="tr1",
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.local,
    )
    assert dec.source_runtime_posture == "join_runtime"


def test_H04_decision_compact_summary_includes_posture() -> None:
    dec = build_source_dispatch_decision(
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.remote_handoff,
    )
    s = dec.to_compact_summary()
    assert "source_runtime_posture" in s
    assert s["source_runtime_posture"] == "join_runtime"


def test_H05_decision_round_trip() -> None:
    dec = build_source_dispatch_decision(
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.local,
    )
    d = dec.to_dict()
    assert d["source_runtime_posture"] == "join_runtime"
    dec2 = SourceDispatchDecision.from_dict(d)
    assert dec2.source_runtime_posture == "join_runtime"


# ===========================================================================
# Group I — SourceDispatchPlan posture integration
# ===========================================================================


def test_I01_plan_has_posture_field() -> None:
    plan = SourceDispatchPlan(mode=SourceDispatchMode.local)
    assert hasattr(plan, "source_runtime_posture")


def test_I02_plan_default_is_control_only() -> None:
    plan = SourceDispatchPlan(mode=SourceDispatchMode.local)
    assert plan.source_runtime_posture == "control_only"


def test_I03_plan_inherits_posture_from_decision() -> None:
    dec = build_source_dispatch_decision(
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.local,
    )
    plan = build_source_dispatch_plan(decision=dec)
    assert plan.source_runtime_posture == "join_runtime"


def test_I04_plan_accepts_explicit_posture_override() -> None:
    dec = build_source_dispatch_decision(
        source_runtime_posture="control_only",
        mode=SourceDispatchMode.local,
    )
    plan = build_source_dispatch_plan(
        decision=dec,
        source_runtime_posture="join_runtime",
    )
    assert plan.source_runtime_posture == "join_runtime"


def test_I05_plan_round_trip() -> None:
    plan = build_source_dispatch_plan(source_runtime_posture="join_runtime")
    d = plan.to_dict()
    assert d["source_runtime_posture"] == "join_runtime"
    plan2 = SourceDispatchPlan.from_dict(d)
    assert plan2.source_runtime_posture == "join_runtime"


# ===========================================================================
# Group J — SourceDispatchResult posture integration
# ===========================================================================


def test_J01_result_has_posture_field() -> None:
    res = SourceDispatchResult()
    assert hasattr(res, "source_runtime_posture")


def test_J02_result_default_is_control_only() -> None:
    res = SourceDispatchResult()
    assert res.source_runtime_posture == "control_only"


def test_J03_build_result_propagates_join_runtime() -> None:
    res = build_source_dispatch_result(
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.local,
        success=True,
    )
    assert res.source_runtime_posture == "join_runtime"


def test_J04_result_compact_summary_includes_posture() -> None:
    res = build_source_dispatch_result(
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.remote_handoff,
        success=True,
    )
    s = res.to_compact_summary()
    assert "source_runtime_posture" in s
    assert s["source_runtime_posture"] == "join_runtime"


def test_J05_result_round_trip() -> None:
    res = build_source_dispatch_result(
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.local,
    )
    d = res.to_dict()
    assert d["source_runtime_posture"] == "join_runtime"
    res2 = SourceDispatchResult.from_dict(d)
    assert res2.source_runtime_posture == "join_runtime"


# ===========================================================================
# Group K — Propagation chain Decision → Plan → Result
# ===========================================================================


def test_K01_posture_flows_decision_to_plan() -> None:
    dec = build_source_dispatch_decision(
        trace_id="chain_trace",
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.local,
    )
    plan = build_source_dispatch_plan(decision=dec)
    assert dec.source_runtime_posture == "join_runtime"
    assert plan.source_runtime_posture == "join_runtime"


def test_K02_result_posture_independent_when_explicitly_set() -> None:
    dec = build_source_dispatch_decision(
        source_runtime_posture="join_runtime",
        mode=SourceDispatchMode.local,
    )
    plan = build_source_dispatch_plan(decision=dec)
    res = build_source_dispatch_result(
        dispatch_id=dec.dispatch_id,
        source_runtime_posture="control_only",  # explicit override
        mode=SourceDispatchMode.local,
        success=True,
    )
    assert plan.source_runtime_posture == "join_runtime"
    assert res.source_runtime_posture == "control_only"


# ===========================================================================
# Group L — contracts package root re-exports
# ===========================================================================


def test_L01_source_posture_value_importable_from_contracts() -> None:
    from contracts import SourcePostureValue as SPV  # noqa: PLC0415
    assert SPV.CONTROL_ONLY.value == "control_only"


def test_L02_source_posture_contract_field_importable() -> None:
    from contracts import SourcePostureContractField as SPCF  # noqa: PLC0415
    field = SPCF()
    assert field.source_runtime_posture == "control_only"


def test_L03_sentinel_constants_importable_from_contracts() -> None:
    from contracts import (  # noqa: PLC0415
        SOURCE_POSTURE_CONTRACT_AUTHORITY,
        SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL,
        SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY,
    )
    assert len(SOURCE_POSTURE_CONTRACT_AUTHORITY) > 0
    assert len(SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL) > 0
    assert len(SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY) > 0


def test_L04_build_source_posture_field_importable() -> None:
    from contracts import build_source_posture_field as bspf  # noqa: PLC0415
    field = bspf("join_runtime")
    assert field.source_runtime_posture == "join_runtime"


# ===========================================================================
# Group M — Backwards compatibility / additive-only guarantees
# ===========================================================================


def test_M01_handoff_env_without_posture_kwarg_constructs() -> None:
    env = HandoffEnvelopeV2(trace_id="compat_t1")
    assert env.trace_id == "compat_t1"
    assert env.source_runtime_posture == "control_only"  # safe default


def test_M02_dispatch_decision_without_posture_constructs() -> None:
    dec = SourceDispatchDecision(mode=SourceDispatchMode.local)
    assert dec.mode == SourceDispatchMode.local
    assert dec.source_runtime_posture == "control_only"


def test_M03_dispatch_result_without_posture_constructs() -> None:
    res = SourceDispatchResult(success=True)
    assert res.success is True
    assert res.source_runtime_posture == "control_only"


def test_M04_from_bridge_inputs_without_posture_works() -> None:
    env = from_bridge_inputs(
        trace_id="compat_t2",
        task={"tool_name": "screenshot"},
    )
    assert env.source_runtime_posture == "control_only"


def test_M05_existing_compact_summary_fields_not_removed() -> None:
    env = build_handoff_envelope_v2(trace_id="compat_t3")
    s = env.to_compact_summary()
    for field in ("handoff_id", "trace_id", "capability", "exec_mode", "schema_version"):
        assert field in s, f"Expected field '{field}' in compact summary"

    dec = build_source_dispatch_decision(mode=SourceDispatchMode.local)
    ds = dec.to_compact_summary()
    for field in ("dispatch_id", "trace_id", "mode", "decision_reason", "has_target"):
        assert field in ds, f"Expected field '{field}' in dispatch compact summary"

    res = build_source_dispatch_result(mode=SourceDispatchMode.local, success=True)
    rs = res.to_compact_summary()
    for field in ("result_id", "dispatch_id", "mode", "success", "error_count"):
        assert field in rs, f"Expected field '{field}' in result compact summary"
