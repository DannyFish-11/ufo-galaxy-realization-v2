"""tests/test_pr_package1_posture_contract_canonicalization.py
================================================================
Tests for PR package 1 (MAIN repo side) of the post-533 dual-repo runtime
unification master plan: Posture Contract Canonicalization.

Coverage matrix
---------------
Group A — Authority and policy sentinel presence.
  A01. POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY is a non-empty string.
  A02. POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY is non-empty.
  A03. POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY is non-empty.
  A04. POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY is non-empty.
  A05. POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL is non-empty.
  A06. SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL is non-empty.
  A07. CANONICAL_POSTURE_ADJACENT_FIELDS is a frozenset with expected members.
  A08. Sentinel strings contain expected sub-strings for traceability.

Group B — normalize_posture_for_ingress (public contract-layer API).
  B01. None → "control_only".
  B02. "join_runtime" → "join_runtime".
  B03. "control_only" → "control_only".
  B04. "JOIN_RUNTIME" (upper-case) → "join_runtime".
  B05. "  join_runtime  " (with whitespace) → "join_runtime".
  B06. "bad_value" → "control_only" (safe default).
  B07. Empty string → "control_only".
  B08. Integer input → "control_only" (graceful).
  B09. Never raises.

Group C — canonicalize_posture_in_payload.
  C01. Returns a copy — original dict unchanged.
  C02. Normalises "JOIN_RUNTIME" to "join_runtime".
  C03. Missing key is set to "control_only".
  C04. Unknown value normalised to "control_only".
  C05. Custom key param works.
  C06. Other dict fields are preserved unchanged.
  C07. None value normalised to "control_only".

Group D — validate_posture_field_consistency (boundary check).
  D01. Clean payload → (True, []).
  D02. entry_mode="control_only" → (False, [violation_msg]).
  D03. entry_mode="join_runtime" → (False, [violation_msg]).
  D04. cross_device_enabled="control_only" → (False, [violation_msg]).
  D05. formation_role="join_runtime" → (False, [violation_msg]).
  D06. coordination_role="control_only" → (False, [violation_msg]).
  D07. Multiple violations detected at once.
  D08. entry_mode="cross_device" (non-posture value) → no violation.
  D09. cross_device_enabled=True → no violation (bool, not posture string).
  D10. Absent adjacent fields are not flagged.
  D11. source_runtime_posture itself is never flagged as conflating.

Group E — assert_posture_boundary_compliance.
  E01. Clean payload → does not raise.
  E02. entry_mode="control_only" → raises PostureBoundaryViolation.
  E03. PostureBoundaryViolation is a ValueError subclass.
  E04. PostureBoundaryViolation.violations list is non-empty on raise.
  E05. Clean posture with valid entry_mode → does not raise.

Group F — get_posture_from_payload.
  F01. Key present with "join_runtime" → "join_runtime".
  F02. Key present with "control_only" → "control_only".
  F03. Key absent → default "control_only".
  F04. Key present with bad value → "control_only".
  F05. Custom default param used when key absent.
  F06. Never raises.

Group G — Ingress model (ChatRequest) uses contract layer.
  G01. ChatRequest accepts "control_only".
  G02. ChatRequest accepts "join_runtime".
  G03. ChatRequest rejects invalid value with ValueError.
  G04. ChatRequest accepts None (optional field).
  G05. ChatRequest normalises "JOIN_RUNTIME" to "join_runtime".

Group H — contracts package re-exports (PR package 1 symbols).
  H01. normalize_posture_for_ingress importable from contracts.
  H02. SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL importable.
  H03. CANONICAL_POSTURE_ADJACENT_FIELDS importable from contracts.

Group I — core.runtime re-exports (PR package 1 symbols).
  I01. canonicalize_posture_in_payload importable from core.runtime.
  I02. validate_posture_field_consistency importable from core.runtime.
  I03. assert_posture_boundary_compliance importable from core.runtime.
  I04. PostureBoundaryViolation importable from core.runtime.
  I05. POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL importable from core.runtime.

Group J — Boundary: source_runtime_posture is not entry_mode.
  J01. Payloads with entry_mode="local" and posture="control_only" are clean.
  J02. Payloads with entry_mode="cross_device" and posture="join_runtime" are clean.
  J03. Payloads where entry_mode tries to encode posture are caught.

Group K — Boundary: posture is not cross_device_enabled.
  K01. cross_device_enabled=False with posture="join_runtime" is clean.
  K02. cross_device_enabled=True with posture="control_only" is clean.
  K03. cross_device_enabled="join_runtime" is a violation.

Group L — Consistency with existing PR-533 contract helpers.
  L01. normalize_posture_for_ingress agrees with resolve_source_posture_value.
  L02. normalize_posture_for_ingress agrees with validate_source_posture_value.
  L03. canonicalize_posture_in_payload result passes validate_source_posture_value.

Group M — Backwards compatibility.
  M01. canonicalize_posture_in_payload with already-canonical value is idempotent.
  M02. validate_posture_field_consistency is safe on empty dict.
  M03. get_posture_from_payload on empty dict returns default.
"""

from __future__ import annotations

import pytest
from typing import Any, Dict


# ---------------------------------------------------------------------------
# A — Authority and policy sentinel presence
# ---------------------------------------------------------------------------


class TestSentinels:
    """Group A: sentinel strings are present and non-empty."""

    def test_canonicalization_authority_present(self):
        from core.posture_contract_canonicalization import (
            POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY,
        )
        assert isinstance(POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY, str)
        assert len(POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY) > 0

    def test_no_entry_mode_conflation_policy_present(self):
        from core.posture_contract_canonicalization import (
            POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY,
        )
        assert isinstance(POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY, str)
        assert len(POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY) > 0

    def test_no_cross_device_flag_conflation_policy_present(self):
        from core.posture_contract_canonicalization import (
            POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY,
        )
        assert isinstance(POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY, str)
        assert len(POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY) > 0

    def test_no_formation_role_conflation_policy_present(self):
        from core.posture_contract_canonicalization import (
            POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY,
        )
        assert isinstance(POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY, str)
        assert len(POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY) > 0

    def test_pr_package_1_sentinel_present(self):
        from core.posture_contract_canonicalization import (
            POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL,
        )
        assert isinstance(POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL, str)
        assert len(POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL) > 0

    def test_contract_pr_package_1_canonicalization_sentinel_present(self):
        from contracts.source_posture_contract import (
            SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL,
        )
        assert isinstance(SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL, str)
        assert len(SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL) > 0

    def test_canonical_posture_adjacent_fields_is_frozenset(self):
        from contracts.source_posture_contract import CANONICAL_POSTURE_ADJACENT_FIELDS

        assert isinstance(CANONICAL_POSTURE_ADJACENT_FIELDS, frozenset)
        assert "entry_mode" in CANONICAL_POSTURE_ADJACENT_FIELDS
        assert "cross_device_enabled" in CANONICAL_POSTURE_ADJACENT_FIELDS
        assert "formation_role" in CANONICAL_POSTURE_ADJACENT_FIELDS

    def test_sentinels_contain_traceability_substrings(self):
        from core.posture_contract_canonicalization import (
            POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL,
            POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY,
        )
        assert "PR_PACKAGE_1" in POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL
        assert "post-533" in POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY.lower()


# ---------------------------------------------------------------------------
# B — normalize_posture_for_ingress
# ---------------------------------------------------------------------------


class TestNormalizePostureForIngress:
    """Group B: normalize_posture_for_ingress helper."""

    def _fn(self, raw):
        from contracts.source_posture_contract import normalize_posture_for_ingress
        return normalize_posture_for_ingress(raw)

    def test_none_returns_control_only(self):
        assert self._fn(None) == "control_only"

    def test_join_runtime_passthrough(self):
        assert self._fn("join_runtime") == "join_runtime"

    def test_control_only_passthrough(self):
        assert self._fn("control_only") == "control_only"

    def test_uppercase_normalised(self):
        assert self._fn("JOIN_RUNTIME") == "join_runtime"

    def test_whitespace_stripped(self):
        assert self._fn("  join_runtime  ") == "join_runtime"

    def test_bad_value_returns_control_only(self):
        assert self._fn("bad_value") == "control_only"

    def test_empty_string_returns_control_only(self):
        assert self._fn("") == "control_only"

    def test_integer_input_returns_control_only(self):
        assert self._fn(42) == "control_only"  # type: ignore[arg-type]

    def test_never_raises(self):
        for raw in [None, "", "x", 0, [], {}, object()]:
            result = self._fn(raw)
            assert result in ("control_only", "join_runtime")


# ---------------------------------------------------------------------------
# C — canonicalize_posture_in_payload
# ---------------------------------------------------------------------------


class TestCanonicalizePostureInPayload:
    """Group C: canonicalize_posture_in_payload helper."""

    def _fn(self, payload, **kwargs):
        from core.posture_contract_canonicalization import canonicalize_posture_in_payload
        return canonicalize_posture_in_payload(payload, **kwargs)

    def test_returns_copy_original_unchanged(self):
        original = {"source_runtime_posture": "JOIN_RUNTIME", "other": "val"}
        result = self._fn(original)
        assert original["source_runtime_posture"] == "JOIN_RUNTIME"  # unchanged
        assert result is not original

    def test_normalises_uppercase(self):
        result = self._fn({"source_runtime_posture": "JOIN_RUNTIME"})
        assert result["source_runtime_posture"] == "join_runtime"

    def test_missing_key_defaults_to_control_only(self):
        result = self._fn({})
        assert result["source_runtime_posture"] == "control_only"

    def test_unknown_value_normalised_to_control_only(self):
        result = self._fn({"source_runtime_posture": "unknown_posture"})
        assert result["source_runtime_posture"] == "control_only"

    def test_custom_key(self):
        result = self._fn({"my_posture": "join_runtime"}, key="my_posture")
        assert result["my_posture"] == "join_runtime"

    def test_other_fields_preserved(self):
        payload = {"source_runtime_posture": "control_only", "entry_mode": "local", "x": 42}
        result = self._fn(payload)
        assert result["entry_mode"] == "local"
        assert result["x"] == 42

    def test_none_value_normalised_to_control_only(self):
        result = self._fn({"source_runtime_posture": None})
        assert result["source_runtime_posture"] == "control_only"


# ---------------------------------------------------------------------------
# D — validate_posture_field_consistency
# ---------------------------------------------------------------------------


class TestValidatePostureFieldConsistency:
    """Group D: validate_posture_field_consistency boundary check."""

    def _fn(self, payload, **kwargs):
        from core.posture_contract_canonicalization import validate_posture_field_consistency
        return validate_posture_field_consistency(payload, **kwargs)

    def test_clean_payload_returns_true_empty_violations(self):
        ok, violations = self._fn({"source_runtime_posture": "control_only", "entry_mode": "local"})
        assert ok is True
        assert violations == []

    def test_entry_mode_control_only_is_violation(self):
        ok, violations = self._fn({"entry_mode": "control_only"})
        assert ok is False
        assert len(violations) >= 1
        assert any("entry_mode" in v for v in violations)

    def test_entry_mode_join_runtime_is_violation(self):
        ok, violations = self._fn({"entry_mode": "join_runtime"})
        assert ok is False
        assert any("entry_mode" in v for v in violations)

    def test_cross_device_enabled_control_only_is_violation(self):
        ok, violations = self._fn({"cross_device_enabled": "control_only"})
        assert ok is False
        assert any("cross_device_enabled" in v for v in violations)

    def test_formation_role_join_runtime_is_violation(self):
        ok, violations = self._fn({"formation_role": "join_runtime"})
        assert ok is False
        assert any("formation_role" in v for v in violations)

    def test_coordination_role_control_only_is_violation(self):
        ok, violations = self._fn({"coordination_role": "control_only"})
        assert ok is False
        assert any("coordination_role" in v for v in violations)

    def test_multiple_violations_all_detected(self):
        payload = {"entry_mode": "control_only", "formation_role": "join_runtime"}
        ok, violations = self._fn(payload)
        assert ok is False
        assert len(violations) >= 2

    def test_entry_mode_cross_device_not_violation(self):
        ok, violations = self._fn({"entry_mode": "cross_device"})
        assert ok is True
        assert violations == []

    def test_cross_device_enabled_bool_not_violation(self):
        ok, violations = self._fn({"cross_device_enabled": True})
        assert ok is True
        assert violations == []

    def test_absent_adjacent_fields_not_flagged(self):
        ok, violations = self._fn({"source_runtime_posture": "join_runtime"})
        assert ok is True
        assert violations == []

    def test_source_runtime_posture_itself_never_flagged(self):
        # The posture field itself should never be treated as an adjacent-field
        # violation, even if its value matches a canonical posture string.
        ok, violations = self._fn({"source_runtime_posture": "control_only"})
        assert ok is True
        assert violations == []


# ---------------------------------------------------------------------------
# E — assert_posture_boundary_compliance
# ---------------------------------------------------------------------------


class TestAssertPostureBoundaryCompliance:
    """Group E: assert_posture_boundary_compliance."""

    def test_clean_payload_does_not_raise(self):
        from core.posture_contract_canonicalization import assert_posture_boundary_compliance
        assert_posture_boundary_compliance({"source_runtime_posture": "control_only", "entry_mode": "local"})

    def test_entry_mode_posture_value_raises(self):
        from core.posture_contract_canonicalization import (
            assert_posture_boundary_compliance,
            PostureBoundaryViolation,
        )
        with pytest.raises(PostureBoundaryViolation):
            assert_posture_boundary_compliance({"entry_mode": "control_only"})

    def test_boundary_violation_is_value_error_subclass(self):
        from core.posture_contract_canonicalization import PostureBoundaryViolation
        assert issubclass(PostureBoundaryViolation, ValueError)

    def test_boundary_violation_violations_list_populated(self):
        from core.posture_contract_canonicalization import (
            assert_posture_boundary_compliance,
            PostureBoundaryViolation,
        )
        with pytest.raises(PostureBoundaryViolation) as exc_info:
            assert_posture_boundary_compliance({"entry_mode": "join_runtime"})
        assert len(exc_info.value.violations) >= 1

    def test_valid_entry_mode_does_not_raise(self):
        from core.posture_contract_canonicalization import assert_posture_boundary_compliance
        assert_posture_boundary_compliance({
            "source_runtime_posture": "join_runtime",
            "entry_mode": "cross_device",
        })


# ---------------------------------------------------------------------------
# F — get_posture_from_payload
# ---------------------------------------------------------------------------


class TestGetPostureFromPayload:
    """Group F: get_posture_from_payload extraction helper."""

    def _fn(self, payload, **kwargs):
        from core.posture_contract_canonicalization import get_posture_from_payload
        return get_posture_from_payload(payload, **kwargs)

    def test_join_runtime_present(self):
        assert self._fn({"source_runtime_posture": "join_runtime"}) == "join_runtime"

    def test_control_only_present(self):
        assert self._fn({"source_runtime_posture": "control_only"}) == "control_only"

    def test_key_absent_returns_default_control_only(self):
        assert self._fn({}) == "control_only"

    def test_bad_value_returns_control_only(self):
        assert self._fn({"source_runtime_posture": "bad"}) == "control_only"

    def test_custom_default_used_when_key_absent(self):
        result = self._fn({}, default="join_runtime")
        assert result == "join_runtime"

    def test_never_raises(self):
        for payload in [{}, {"source_runtime_posture": None}, {"source_runtime_posture": 99}]:
            result = self._fn(payload)
            assert result in ("control_only", "join_runtime")


# ---------------------------------------------------------------------------
# G — Ingress model (ChatRequest) uses contract layer
# ---------------------------------------------------------------------------


class TestChatRequestIngressUsesContractLayer:
    """Group G: ChatRequest posture validation delegates to contract layer."""

    def _make_request(self, **kwargs):
        from core.routes._models import ChatRequest
        return ChatRequest(message="hello", **kwargs)

    def test_accepts_control_only(self):
        req = self._make_request(source_runtime_posture="control_only")
        assert req.source_runtime_posture == "control_only"

    def test_accepts_join_runtime(self):
        req = self._make_request(source_runtime_posture="join_runtime")
        assert req.source_runtime_posture == "join_runtime"

    def test_rejects_invalid_value(self):
        with pytest.raises((ValueError, Exception)):
            self._make_request(source_runtime_posture="invalid_posture")

    def test_accepts_none(self):
        req = self._make_request(source_runtime_posture=None)
        assert req.source_runtime_posture is None

    def test_normalises_uppercase_to_lowercase(self):
        req = self._make_request(source_runtime_posture="JOIN_RUNTIME")
        assert req.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# H — contracts package re-exports (PR package 1 symbols)
# ---------------------------------------------------------------------------


class TestContractsReExports:
    """Group H: new PR package 1 symbols are accessible from contracts."""

    def test_normalize_posture_for_ingress_importable(self):
        from contracts import normalize_posture_for_ingress  # noqa: F401
        assert callable(normalize_posture_for_ingress)

    def test_pr_package_1_canonicalization_sentinel_importable(self):
        from contracts import SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL
        assert isinstance(SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL, str)
        assert len(SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL) > 0

    def test_canonical_posture_adjacent_fields_importable(self):
        from contracts import CANONICAL_POSTURE_ADJACENT_FIELDS
        assert isinstance(CANONICAL_POSTURE_ADJACENT_FIELDS, frozenset)


# ---------------------------------------------------------------------------
# I — core.runtime re-exports (PR package 1 symbols)
# ---------------------------------------------------------------------------


class TestCoreRuntimeReExports:
    """Group I: PR package 1 symbols accessible from core.runtime."""

    def test_canonicalize_posture_in_payload_importable(self):
        from core.runtime import canonicalize_posture_in_payload  # noqa: F401
        assert callable(canonicalize_posture_in_payload)

    def test_validate_posture_field_consistency_importable(self):
        from core.runtime import validate_posture_field_consistency  # noqa: F401
        assert callable(validate_posture_field_consistency)

    def test_assert_posture_boundary_compliance_importable(self):
        from core.runtime import assert_posture_boundary_compliance  # noqa: F401
        assert callable(assert_posture_boundary_compliance)

    def test_posture_boundary_violation_importable(self):
        from core.runtime import PostureBoundaryViolation  # noqa: F401
        assert issubclass(PostureBoundaryViolation, ValueError)

    def test_pr_package_1_sentinel_importable(self):
        from core.runtime import POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL
        assert isinstance(POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL, str)
        assert len(POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL) > 0


# ---------------------------------------------------------------------------
# J — Boundary: source_runtime_posture is not entry_mode
# ---------------------------------------------------------------------------


class TestBoundaryPostureNotEntryMode:
    """Group J: posture and entry_mode are orthogonal concepts."""

    def test_local_entry_mode_with_control_only_is_clean(self):
        from core.posture_contract_canonicalization import validate_posture_field_consistency
        ok, violations = validate_posture_field_consistency({
            "source_runtime_posture": "control_only",
            "entry_mode": "local",
        })
        assert ok is True

    def test_cross_device_entry_mode_with_join_runtime_is_clean(self):
        from core.posture_contract_canonicalization import validate_posture_field_consistency
        ok, violations = validate_posture_field_consistency({
            "source_runtime_posture": "join_runtime",
            "entry_mode": "cross_device",
        })
        assert ok is True

    def test_entry_mode_encoding_posture_is_caught(self):
        from core.posture_contract_canonicalization import validate_posture_field_consistency
        ok, violations = validate_posture_field_consistency({
            "source_runtime_posture": "control_only",
            "entry_mode": "control_only",  # overloaded!
        })
        assert ok is False


# ---------------------------------------------------------------------------
# K — Boundary: posture is not cross_device_enabled
# ---------------------------------------------------------------------------


class TestBoundaryPostureNotCrossDeviceEnabled:
    """Group K: posture and cross_device_enabled are orthogonal concepts."""

    def test_false_cross_device_enabled_with_join_runtime_is_clean(self):
        from core.posture_contract_canonicalization import validate_posture_field_consistency
        ok, violations = validate_posture_field_consistency({
            "source_runtime_posture": "join_runtime",
            "cross_device_enabled": False,
        })
        assert ok is True

    def test_true_cross_device_enabled_with_control_only_is_clean(self):
        from core.posture_contract_canonicalization import validate_posture_field_consistency
        ok, violations = validate_posture_field_consistency({
            "source_runtime_posture": "control_only",
            "cross_device_enabled": True,
        })
        assert ok is True

    def test_cross_device_enabled_as_posture_string_is_violation(self):
        from core.posture_contract_canonicalization import validate_posture_field_consistency
        ok, violations = validate_posture_field_consistency({
            "cross_device_enabled": "join_runtime",  # overloaded!
        })
        assert ok is False


# ---------------------------------------------------------------------------
# L — Consistency with existing PR-533 contract helpers
# ---------------------------------------------------------------------------


class TestConsistencyWithPR533:
    """Group L: new helpers agree with existing PR-533 contract helpers."""

    def test_normalize_agrees_with_resolve_source_posture_value(self):
        from contracts.source_posture_contract import (
            normalize_posture_for_ingress,
            resolve_source_posture_value,
            SourcePostureValue,
        )
        for raw in ("control_only", "join_runtime", None, "bad"):
            normalised = normalize_posture_for_ingress(raw)
            resolved = resolve_source_posture_value(raw).value
            assert normalised == resolved, f"Mismatch for raw={raw!r}"

    def test_normalize_agrees_with_validate_source_posture_value(self):
        from contracts.source_posture_contract import (
            normalize_posture_for_ingress,
            validate_source_posture_value,
        )
        for valid in ("control_only", "join_runtime"):
            ok, err = validate_source_posture_value(normalize_posture_for_ingress(valid))
            assert ok is True
            assert err is None

    def test_canonicalized_payload_passes_validate_source_posture_value(self):
        from contracts.source_posture_contract import validate_source_posture_value
        from core.posture_contract_canonicalization import canonicalize_posture_in_payload

        for raw in ("JOIN_RUNTIME", "CONTROL_ONLY", "bad_value", None, ""):
            payload = canonicalize_posture_in_payload({"source_runtime_posture": raw})
            ok, err = validate_source_posture_value(payload["source_runtime_posture"])
            assert ok is True, f"Failed for raw={raw!r}: {err}"


# ---------------------------------------------------------------------------
# M — Backwards compatibility
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    """Group M: new helpers do not break existing behaviour."""

    def test_canonicalize_idempotent_on_canonical_values(self):
        from core.posture_contract_canonicalization import canonicalize_posture_in_payload
        for val in ("control_only", "join_runtime"):
            payload = {"source_runtime_posture": val}
            result = canonicalize_posture_in_payload(payload)
            assert result["source_runtime_posture"] == val

    def test_validate_consistency_safe_on_empty_dict(self):
        from core.posture_contract_canonicalization import validate_posture_field_consistency
        ok, violations = validate_posture_field_consistency({})
        assert ok is True
        assert violations == []

    def test_get_posture_from_empty_dict_returns_default(self):
        from core.posture_contract_canonicalization import get_posture_from_payload
        result = get_posture_from_payload({})
        assert result == "control_only"
