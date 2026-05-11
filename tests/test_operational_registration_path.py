"""
tests/test_operational_registration_path.py
============================================
Test suite for core/operational_registration_path.py

Unified Operational Registration Path — aligned with PR993
center-governed distributed intelligent agent system definition.

This test suite validates:

A. Module import and public symbol accessibility.
B. All RegistrationKind enum values have a RegistrationKindInfo record.
C. All OnboardingStepId enum values have an OnboardingStep record.
D. Prerequisite validation returns a structurally correct result.
E. build_operational_registration_path() returns a correct root artifact.
F. Tier classification invariants (main chain, cross-device, compat).
G. Key required kinds are in the expected tiers.
H. Serialisation round-trip (to_dict / to_json).
I. assert_operational_registration_path_invariants() passes.
J. Singleton caching and reset_operational_registration_path() work.
K. System identity contains required PR993 reference.
L. Contract version sentinel format.
"""

from __future__ import annotations

import json

import pytest

from core.operational_registration_path import (
    OPERATIONAL_REGISTRATION_PATH_AUTHORITY,
    OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION,
    OnboardingStep,
    OnboardingStepId,
    OnboardingValidation,
    OperationalRegistrationPath,
    PathTier,
    PrerequisiteCheck,
    RegistrationKind,
    RegistrationKindInfo,
    ValidationStatus,
    assert_operational_registration_path_invariants,
    build_operational_registration_path,
    get_operational_registration_path,
    reset_operational_registration_path,
    validate_registration_prerequisites,
)


# =============================================================================
# Section A — Module import and public symbol sanity
# =============================================================================


class TestModuleImport:
    """All public symbols must be importable from the module."""

    def test_authority_sentinel_is_string(self) -> None:
        assert isinstance(OPERATIONAL_REGISTRATION_PATH_AUTHORITY, str)
        assert len(OPERATIONAL_REGISTRATION_PATH_AUTHORITY) > 0

    def test_contract_version_is_string(self) -> None:
        assert isinstance(OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION, str)
        assert len(OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION) > 0

    def test_authority_mentions_pr993(self) -> None:
        assert "PR993" in OPERATIONAL_REGISTRATION_PATH_AUTHORITY

    def test_contract_version_pr993_ops_tag(self) -> None:
        assert "pr993_ops" in OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION

    def test_registration_kind_enum_accessible(self) -> None:
        assert RegistrationKind.DEVICE_CANONICAL is not None

    def test_onboarding_step_id_enum_accessible(self) -> None:
        assert OnboardingStepId.CLONE is not None

    def test_path_tier_enum_accessible(self) -> None:
        assert PathTier.MAIN_CHAIN is not None

    def test_validation_status_enum_accessible(self) -> None:
        assert ValidationStatus.PASS is not None

    def test_dataclasses_importable(self) -> None:
        assert RegistrationKindInfo is not None
        assert OnboardingStep is not None
        assert PrerequisiteCheck is not None
        assert OnboardingValidation is not None
        assert OperationalRegistrationPath is not None

    def test_functions_importable(self) -> None:
        assert callable(validate_registration_prerequisites)
        assert callable(build_operational_registration_path)
        assert callable(get_operational_registration_path)
        assert callable(reset_operational_registration_path)
        assert callable(assert_operational_registration_path_invariants)


# =============================================================================
# Section B — RegistrationKind enum coverage
# =============================================================================


class TestRegistrationKindCoverage:
    """Every RegistrationKind must have a RegistrationKindInfo record."""

    def _kinds_map(self) -> dict:
        path = build_operational_registration_path()
        return {rk.kind: rk for rk in path.registration_kinds}

    def test_all_registration_kinds_covered(self) -> None:
        kinds_map = self._kinds_map()
        for kind in RegistrationKind:
            assert kind in kinds_map, (
                f"RegistrationKind.{kind.name} has no RegistrationKindInfo record."
            )

    def test_registration_kind_count_matches_enum(self) -> None:
        path = build_operational_registration_path()
        assert len(path.registration_kinds) == len(RegistrationKind)

    def test_every_kind_has_nonempty_canonical_module(self) -> None:
        path = build_operational_registration_path()
        for rk in path.registration_kinds:
            assert rk.canonical_module, (
                f"RegistrationKind.{rk.kind.name} has an empty canonical_module."
            )

    def test_every_kind_has_nonempty_description(self) -> None:
        path = build_operational_registration_path()
        for rk in path.registration_kinds:
            assert rk.description, (
                f"RegistrationKind.{rk.kind.name} has an empty description."
            )

    def test_every_kind_has_nonempty_display_name(self) -> None:
        path = build_operational_registration_path()
        for rk in path.registration_kinds:
            assert rk.display_name, (
                f"RegistrationKind.{rk.kind.name} has an empty display_name."
            )


# =============================================================================
# Section C — OnboardingStepId coverage
# =============================================================================


class TestOnboardingStepCoverage:
    """Every OnboardingStepId must have an OnboardingStep record."""

    def _steps_map(self) -> dict:
        path = build_operational_registration_path()
        return {s.step_id: s for s in path.onboarding_steps}

    def test_all_onboarding_steps_covered(self) -> None:
        steps_map = self._steps_map()
        for step_id in OnboardingStepId:
            assert step_id in steps_map, (
                f"OnboardingStepId.{step_id.name} has no OnboardingStep record."
            )

    def test_onboarding_step_count_matches_enum(self) -> None:
        path = build_operational_registration_path()
        assert len(path.onboarding_steps) == len(OnboardingStepId)

    def test_every_step_has_instructions(self) -> None:
        path = build_operational_registration_path()
        for s in path.onboarding_steps:
            assert s.instructions, (
                f"OnboardingStepId.{s.step_id.name} has empty instructions."
            )

    def test_every_step_has_verification(self) -> None:
        path = build_operational_registration_path()
        for s in path.onboarding_steps:
            assert s.verification, (
                f"OnboardingStepId.{s.step_id.name} has empty verification."
            )

    def test_clone_step_is_blocking(self) -> None:
        steps_map = self._steps_map()
        assert steps_map[OnboardingStepId.CLONE].blocking is True

    def test_start_backend_step_is_blocking(self) -> None:
        steps_map = self._steps_map()
        assert steps_map[OnboardingStepId.START_BACKEND].blocking is True

    def test_register_android_is_cross_device(self) -> None:
        steps_map = self._steps_map()
        assert steps_map[OnboardingStepId.REGISTER_ANDROID].path_tier == PathTier.CROSS_DEVICE

    def test_verify_android_registration_is_cross_device(self) -> None:
        steps_map = self._steps_map()
        assert steps_map[OnboardingStepId.VERIFY_ANDROID_REGISTRATION].path_tier == PathTier.CROSS_DEVICE


# =============================================================================
# Section D — Prerequisite validation
# =============================================================================


class TestPrerequisiteValidation:
    """validate_registration_prerequisites() must return a correct result."""

    def test_returns_onboarding_validation(self) -> None:
        v = validate_registration_prerequisites()
        assert isinstance(v, OnboardingValidation)

    def test_has_at_least_ten_checks(self) -> None:
        v = validate_registration_prerequisites()
        assert len(v.checks) >= 10

    def test_overall_status_is_valid_enum(self) -> None:
        v = validate_registration_prerequisites()
        assert v.overall_status in ValidationStatus

    def test_summary_is_nonempty(self) -> None:
        v = validate_registration_prerequisites()
        assert v.summary

    def test_no_failed_checks_on_clean_install(self) -> None:
        """All core modules must be locatable in this repository."""
        v = validate_registration_prerequisites()
        assert len(v.failed_checks) == 0, (
            f"Unexpected FAIL checks: {[c.name for c in v.failed_checks]}"
        )

    def test_passed_property_reflects_overall_status(self) -> None:
        v = validate_registration_prerequisites()
        if v.overall_status == ValidationStatus.FAIL:
            assert not v.passed
        else:
            assert v.passed

    def test_check_names_are_unique(self) -> None:
        v = validate_registration_prerequisites()
        names = [c.name for c in v.checks]
        assert len(names) == len(set(names)), "Duplicate prerequisite check names."

    def test_every_check_has_message(self) -> None:
        v = validate_registration_prerequisites()
        for c in v.checks:
            assert c.message, f"Check '{c.name}' has an empty message."

    def test_to_dict_round_trip(self) -> None:
        v = validate_registration_prerequisites()
        d = v.to_dict()
        assert isinstance(d, dict)
        assert "checks" in d
        assert "overall_status" in d
        assert "summary" in d

    def test_to_json_round_trip(self) -> None:
        v = validate_registration_prerequisites()
        j = v.to_json()
        assert isinstance(j, str) and len(j) > 0
        parsed = json.loads(j)
        assert "overall_status" in parsed

    def test_specific_checks_present(self) -> None:
        v = validate_registration_prerequisites()
        names = {c.name for c in v.checks}
        required = {
            "system-orchestrator",
            "unified-device-manager",
            "capability-registry",
            "gateway-websocket",
            "android-device-state-store",
            "android-gateway-registration",
            "attached-runtime-session-registry",
            "unified-execution-governance",
            "desktop-presence-runtime",
            "openclawd-core",
        }
        for name in required:
            assert name in names, f"Expected prerequisite check '{name}' not present."


# =============================================================================
# Section E — build_operational_registration_path() structure
# =============================================================================


class TestBuildPath:
    """build_operational_registration_path() must return a correct root artifact."""

    def test_returns_operational_registration_path(self) -> None:
        path = build_operational_registration_path()
        assert isinstance(path, OperationalRegistrationPath)

    def test_registration_kinds_nonempty(self) -> None:
        path = build_operational_registration_path()
        assert len(path.registration_kinds) > 0

    def test_onboarding_steps_nonempty(self) -> None:
        path = build_operational_registration_path()
        assert len(path.onboarding_steps) > 0

    def test_validation_present(self) -> None:
        path = build_operational_registration_path()
        assert path.validation is not None

    def test_system_identity_nonempty(self) -> None:
        path = build_operational_registration_path()
        assert path.system_identity

    def test_contract_version_present(self) -> None:
        path = build_operational_registration_path()
        assert path.contract_version

    def test_authority_present(self) -> None:
        path = build_operational_registration_path()
        assert path.authority


# =============================================================================
# Section F — Tier classification invariants
# =============================================================================


class TestTierClassification:
    """Tier classification invariants must hold."""

    def test_every_kind_in_at_least_one_tier(self) -> None:
        path = build_operational_registration_path()
        all_tiered = (
            set(path.main_chain_kinds)
            | set(path.cross_device_kinds)
            | set(path.compat_kinds)
        )
        for rk in path.registration_kinds:
            assert rk.kind in all_tiered, (
                f"RegistrationKind.{rk.kind.name} not in any tier bucket."
            )

    def test_main_chain_nonempty(self) -> None:
        path = build_operational_registration_path()
        assert len(path.main_chain_kinds) > 0

    def test_cross_device_nonempty(self) -> None:
        path = build_operational_registration_path()
        assert len(path.cross_device_kinds) > 0

    def test_all_tier_kinds_are_registration_kinds(self) -> None:
        path = build_operational_registration_path()
        all_kind_values = {rk.kind for rk in path.registration_kinds}
        for k in path.main_chain_kinds:
            assert k in all_kind_values
        for k in path.cross_device_kinds:
            assert k in all_kind_values
        for k in path.compat_kinds:
            assert k in all_kind_values

    def test_no_kind_in_multiple_tiers(self) -> None:
        path = build_operational_registration_path()
        main = set(path.main_chain_kinds)
        cross = set(path.cross_device_kinds)
        compat = set(path.compat_kinds)
        assert not main & cross, f"Kinds in both main and cross-device: {main & cross}"
        assert not main & compat, f"Kinds in both main and compat: {main & compat}"
        assert not cross & compat, f"Kinds in both cross-device and compat: {cross & compat}"


# =============================================================================
# Section G — Required kinds in expected tiers
# =============================================================================


class TestRequiredKindTiers:
    """Specific required kinds must appear in the correct tier."""

    REQUIRED_MAIN_CHAIN = [
        RegistrationKind.DEVICE_CANONICAL,
        RegistrationKind.CAPABILITY_REGISTRY,
        RegistrationKind.GATEWAY_WEBSOCKET,
        RegistrationKind.GOVERNANCE_UNIFIED,
        RegistrationKind.RUNTIME_SUBJECT,
        RegistrationKind.SESSION_ATTACHED_RUNTIME,
        RegistrationKind.GATEWAY_DEVICE_ROUTER,
    ]

    REQUIRED_CROSS_DEVICE = [
        RegistrationKind.DEVICE_ANDROID_ADMISSION,
        RegistrationKind.DEVICE_ANDROID_STATE,
        RegistrationKind.CAPABILITY_ANDROID_REPORT,
        RegistrationKind.SESSION_ANDROID_PARTICIPANT,
        RegistrationKind.RUNTIME_ANDROID_HOST,
        RegistrationKind.RUNTIME_DISPATCH_BINDING,
        RegistrationKind.GATEWAY_ANDROID_BRIDGE,
    ]

    REQUIRED_COMPAT = [
        RegistrationKind.DEVICE_INDEX,
    ]

    @pytest.mark.parametrize("kind", REQUIRED_MAIN_CHAIN)
    def test_main_chain_kind_present(self, kind: RegistrationKind) -> None:
        path = build_operational_registration_path()
        assert kind in path.main_chain_kinds, (
            f"RegistrationKind.{kind.name} must be in main_chain_kinds."
        )

    @pytest.mark.parametrize("kind", REQUIRED_CROSS_DEVICE)
    def test_cross_device_kind_present(self, kind: RegistrationKind) -> None:
        path = build_operational_registration_path()
        assert kind in path.cross_device_kinds, (
            f"RegistrationKind.{kind.name} must be in cross_device_kinds."
        )

    @pytest.mark.parametrize("kind", REQUIRED_COMPAT)
    def test_compat_kind_present(self, kind: RegistrationKind) -> None:
        path = build_operational_registration_path()
        assert kind in path.compat_kinds, (
            f"RegistrationKind.{kind.name} must be in compat_kinds."
        )


# =============================================================================
# Section H — Serialisation round-trips
# =============================================================================


class TestSerialisation:
    """to_dict() and to_json() must produce valid, round-trippable output."""

    def test_path_to_dict(self) -> None:
        path = build_operational_registration_path()
        d = path.to_dict()
        assert isinstance(d, dict)
        assert "registration_kinds" in d
        assert "onboarding_steps" in d
        assert "validation" in d
        assert "main_chain_kinds" in d
        assert "cross_device_kinds" in d
        assert "compat_kinds" in d
        assert "system_identity" in d
        assert "contract_version" in d
        assert "authority" in d

    def test_path_to_json(self) -> None:
        path = build_operational_registration_path()
        j = path.to_json()
        assert isinstance(j, str) and len(j) > 0
        parsed = json.loads(j)
        assert "registration_kinds" in parsed

    def test_registration_kind_info_to_dict(self) -> None:
        path = build_operational_registration_path()
        rk = path.registration_kinds[0]
        d = rk.to_dict()
        assert "kind" in d
        assert "canonical_module" in d
        assert "path_tier" in d
        assert "description" in d
        assert "prerequisites" in d
        assert "optional" in d

    def test_onboarding_step_to_dict(self) -> None:
        path = build_operational_registration_path()
        s = path.onboarding_steps[0]
        d = s.to_dict()
        assert "step_id" in d
        assert "path_tier" in d
        assert "instructions" in d
        assert "verification" in d
        assert "blocking" in d

    def test_prerequisite_check_to_dict(self) -> None:
        v = validate_registration_prerequisites()
        c = v.checks[0]
        d = c.to_dict()
        assert "name" in d
        assert "status" in d
        assert "message" in d
        assert "module_checked" in d

    def test_json_is_valid(self) -> None:
        path = build_operational_registration_path()
        j = path.to_json()
        # Must not raise
        json.loads(j)

    def test_main_chain_kinds_in_dict_are_strings(self) -> None:
        path = build_operational_registration_path()
        d = path.to_dict()
        for k in d["main_chain_kinds"]:
            assert isinstance(k, str)

    def test_registration_kinds_list_length_in_dict(self) -> None:
        path = build_operational_registration_path()
        d = path.to_dict()
        assert len(d["registration_kinds"]) == len(path.registration_kinds)

    def test_onboarding_steps_list_length_in_dict(self) -> None:
        path = build_operational_registration_path()
        d = path.to_dict()
        assert len(d["onboarding_steps"]) == len(path.onboarding_steps)


# =============================================================================
# Section I — Invariant helper
# =============================================================================


class TestInvariantHelper:
    """assert_operational_registration_path_invariants() must pass."""

    def test_invariants_pass(self) -> None:
        reset_operational_registration_path()
        assert_operational_registration_path_invariants()


# =============================================================================
# Section J — Singleton caching and reset
# =============================================================================


class TestSingletonCaching:
    """Singleton caching and reset must work correctly."""

    def test_get_returns_same_instance_on_repeated_calls(self) -> None:
        reset_operational_registration_path()
        p1 = get_operational_registration_path()
        p2 = get_operational_registration_path()
        assert p1 is p2

    def test_reset_clears_cache(self) -> None:
        p1 = get_operational_registration_path()
        reset_operational_registration_path()
        p2 = get_operational_registration_path()
        assert p1 is not p2

    def test_build_always_returns_new_instance(self) -> None:
        p1 = build_operational_registration_path()
        p2 = build_operational_registration_path()
        assert p1 is not p2

    def test_get_after_reset_is_valid(self) -> None:
        reset_operational_registration_path()
        path = get_operational_registration_path()
        assert isinstance(path, OperationalRegistrationPath)
        assert len(path.registration_kinds) > 0


# =============================================================================
# Section K — System identity and PR993 alignment
# =============================================================================


class TestSystemIdentityAndPR993Alignment:
    """System identity must reflect the PR993 system definition."""

    def test_system_identity_nonempty(self) -> None:
        path = build_operational_registration_path()
        assert path.system_identity

    def test_system_identity_mentions_pr993(self) -> None:
        path = build_operational_registration_path()
        assert "PR993" in path.system_identity or "center-governed" in path.system_identity

    def test_system_identity_mentions_v2(self) -> None:
        path = build_operational_registration_path()
        assert "V2" in path.system_identity or "ufo-galaxy-realization-v2" in path.system_identity

    def test_system_identity_mentions_android(self) -> None:
        path = build_operational_registration_path()
        assert "Android" in path.system_identity

    def test_system_identity_not_passive_executor(self) -> None:
        """Android must not be described as a passive executor."""
        path = build_operational_registration_path()
        # The identity should mention active participation, not pure passivity
        assert (
            "participat" in path.system_identity.lower()
            or "distributed" in path.system_identity.lower()
            or "local intelligence" in path.system_identity.lower()
        )

    def test_authority_sentinel_references_module(self) -> None:
        assert "core/operational_registration_path.py" in OPERATIONAL_REGISTRATION_PATH_AUTHORITY

    def test_contract_version_format(self) -> None:
        # Must be semver-like with pr993_ops prefix
        v = OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION
        assert v.startswith("pr993_ops.")
        parts = v.split(".")
        assert len(parts) >= 2


# =============================================================================
# Section L — Contract version sentinel
# =============================================================================


class TestContractVersionSentinel:
    """Contract version must be stable and well-formed."""

    def test_contract_version_stable(self) -> None:
        p1 = build_operational_registration_path()
        p2 = build_operational_registration_path()
        assert p1.contract_version == p2.contract_version

    def test_contract_version_matches_module_constant(self) -> None:
        path = build_operational_registration_path()
        assert path.contract_version == OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION

    def test_contract_version_pr993_ops_prefix(self) -> None:
        assert OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION.startswith("pr993_ops.")
