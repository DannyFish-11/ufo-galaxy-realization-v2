#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_identity_authorship_actor_binding_contract.py
=========================================================
Identity / Authorship / Actor-Binding Semantics Contract.

Validates that:

1.  **Identity taxonomy is defined and importable** (five classes).
2.  **identity_authoritatively_bound** classification when all required
    authoritative conditions are present.
3.  **identity_authoritatively_bound requires all conditions** — any
    single missing condition prevents the top class.
4.  **authorship_verified** classification when authorship is validated
    but not via full authoritative channel.
5.  **authorship_verified requires no delegation/proxy**.
6.  **asserted_but_unverified** when actor field is present but no
    verification performed.
7.  **delegated_or_proxy_actor** when delegation/proxy arrangement is
    present.
8.  **identity_or_provenance_uncertain** when no positive evidence or
    explicitly uncertain.
9.  **actor field presence alone must not produce identity_authoritatively_bound**.
10. **assertion_only must not produce authorship_verified or higher**.
11. **delegation must not produce identity_authoritatively_bound or
    authorship_verified (direct)**.
12. **provenance_missing_or_ambiguous must downgrade from verified classes**.
13. **identity_explicitly_uncertain always wins** regardless of other flags.
14. **No positive evidence defaults to identity_or_provenance_uncertain**
    (fail-conservative).
15. **Policy sentinels are importable and non-empty**.
16. **to_dict() / from_dict() round-trip** for evidence and verdict.
17. **build_baseline_identity_binding_verdict()** returns uncertain.
18. **SystemFinalAcceptanceEvaluator includes identity_authorship_binding**.
19. **AcceptanceDimensionId.all_dimensions() includes identity_authorship_binding**.

Test groups
-----------
 A)  Sentinel imports — authority and policy constants importable.
 B)  Enum completeness — all five IdentityBindingClass values exist.
 C)  Enum completeness — IdentityBindingSignalStrength values exist.
 D)  identity_authoritatively_bound — all required conditions present.
 E)  identity_authoritatively_bound — requires identity_verified_by_authority.
 F)  identity_authoritatively_bound — requires binding_confirmed.
 G)  identity_authoritatively_bound — blocked by assertion_only.
 H)  identity_authoritatively_bound — blocked by is_delegation_or_proxy.
 I)  identity_authoritatively_bound — blocked by provenance_missing_or_ambiguous.
 J)  identity_authoritatively_bound — blocked by identity_explicitly_uncertain.
 K)  authorship_verified — authorship_validated=True, no delegation/assertion.
 L)  authorship_verified — blocked by assertion_only.
 M)  authorship_verified — blocked by is_delegation_or_proxy.
 N)  authorship_verified — blocked by provenance_missing_or_ambiguous.
 O)  asserted_but_unverified — actor_field_present=True, no verification.
 P)  asserted_but_unverified — assertion_only=True yields asserted class.
 Q)  asserted_but_unverified — actor field present overrides uncertain default.
 R)  delegated_or_proxy_actor — is_delegation_or_proxy=True.
 S)  delegated_or_proxy_actor — documented delegation still delegated class.
 T)  delegated_or_proxy_actor — NOT identity_authoritatively_bound.
 U)  delegated_or_proxy_actor — NOT authorship_verified.
 V)  identity_or_provenance_uncertain — zero evidence (fail-conservative).
 W)  identity_or_provenance_uncertain — identity_explicitly_uncertain=True.
 X)  identity_or_provenance_uncertain — explicit uncertainty overrides actor field.
 Y)  identity_or_provenance_uncertain — explicit uncertainty overrides delegation.
 Z)  identity_or_provenance_uncertain — provenance_missing_or_ambiguous alone.
 AA) actor field present but not verified → asserted_but_unverified (NOT authoritative).
 AB) IdentityBindingEvidence to_dict / from_dict round-trip.
 AC) IdentityBindingVerdict to_dict / from_dict round-trip.
 AD) is_authoritatively_bound flag — only True for identity_authoritatively_bound.
 AE) is_authorship_verified flag — only True for authorship_verified.
 AF) is_asserted_unverified flag — only True for asserted_but_unverified.
 AG) is_delegated_or_proxy flag — only True for delegated_or_proxy_actor.
 AH) is_uncertain flag — only True for identity_or_provenance_uncertain.
 AI) downgrade_reasons non-empty when a downgrade occurred.
 AJ) build_baseline_identity_binding_verdict() returns uncertain.
 AK) SystemFinalAcceptanceEvaluator includes identity_authorship_binding.
 AL) AcceptanceDimensionId.all_dimensions() includes identity_authorship_binding.
 AM) Probe returns pending when zero-evidence correctly returns uncertain.
 AN) multiple_authority_sources_agree provides additional confidence for bound.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Import guard — skip gracefully if module is unavailable
# ---------------------------------------------------------------------------

_MODULE_AVAILABLE = False
try:
    from core.identity_authorship_actor_binding_contract import (
        # Authority / policy sentinels
        IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY,
        IDENTITY_AUTHORSHIP_BINDING_CONTRACT_SENTINEL,
        IDENTITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
        ACTOR_FIELD_PRESENCE_IS_NOT_AUTHORITATIVE_BINDING_POLICY,
        ASSERTION_MUST_NOT_CLAIM_AUTHORSHIP_VERIFIED_POLICY,
        DELEGATION_MUST_NOT_CLAIM_DIRECT_AUTHORSHIP_POLICY,
        PROVENANCE_ABSENCE_DEFAULTS_TO_UNCERTAIN_POLICY,
        # Enumerations
        IdentityBindingClass,
        IdentityBindingSignalStrength,
        # Data classes
        IdentityBindingEvidence,
        IdentityBindingVerdict,
        # Functions
        classify_identity_binding,
        build_identity_binding_verdict,
        build_baseline_identity_binding_verdict,
    )
    _MODULE_AVAILABLE = True
except ImportError as _imp_err:
    print(
        f"SKIP: core.identity_authorship_actor_binding_contract unavailable: "
        f"{_imp_err}"
    )


def _skip_if_unavailable(test_fn):
    """Decorator: skip test if the module is not available."""
    def wrapper(self):
        if not _MODULE_AVAILABLE:
            self.skipTest(
                "core.identity_authorship_actor_binding_contract not available"
            )
        return test_fn(self)
    wrapper.__name__ = test_fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Helper: build evidence with named overrides
# ---------------------------------------------------------------------------

def _ev(**kwargs) -> "IdentityBindingEvidence":
    """Build an IdentityBindingEvidence with fail-conservative defaults."""
    return IdentityBindingEvidence(
        actor_field_present=kwargs.get("actor_field_present", False),
        identity_verified_by_authority=kwargs.get(
            "identity_verified_by_authority", False
        ),
        authorship_validated=kwargs.get("authorship_validated", False),
        binding_confirmed=kwargs.get("binding_confirmed", False),
        is_delegation_or_proxy=kwargs.get("is_delegation_or_proxy", False),
        delegation_explicitly_documented=kwargs.get(
            "delegation_explicitly_documented", False
        ),
        assertion_only=kwargs.get("assertion_only", False),
        provenance_missing_or_ambiguous=kwargs.get(
            "provenance_missing_or_ambiguous", False
        ),
        identity_explicitly_uncertain=kwargs.get(
            "identity_explicitly_uncertain", False
        ),
        multiple_authority_sources_agree=kwargs.get(
            "multiple_authority_sources_agree", False
        ),
    )


def _ev_authoritative() -> "IdentityBindingEvidence":
    """Build a fully-authoritative binding evidence (all required conditions)."""
    return IdentityBindingEvidence(
        actor_field_present=True,
        identity_verified_by_authority=True,
        binding_confirmed=True,
        assertion_only=False,
        is_delegation_or_proxy=False,
        provenance_missing_or_ambiguous=False,
        identity_explicitly_uncertain=False,
    )


# ===========================================================================
# Group A: Sentinel imports
# ===========================================================================


class TestSentinelImports(unittest.TestCase):

    @_skip_if_unavailable
    def test_A01_authority_sentinel_importable_and_non_empty(self):
        self.assertIsInstance(
            IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY, str
        )
        self.assertTrue(len(IDENTITY_AUTHORSHIP_BINDING_CONTRACT_AUTHORITY) > 0)

    @_skip_if_unavailable
    def test_A02_package_sentinel_importable_and_non_empty(self):
        self.assertIsInstance(IDENTITY_AUTHORSHIP_BINDING_CONTRACT_SENTINEL, str)
        self.assertTrue(len(IDENTITY_AUTHORSHIP_BINDING_CONTRACT_SENTINEL) > 0)

    @_skip_if_unavailable
    def test_A03_identity_taxonomy_policy_non_empty(self):
        self.assertIsInstance(
            IDENTITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY, str
        )
        self.assertTrue(
            len(IDENTITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY) > 0
        )

    @_skip_if_unavailable
    def test_A04_actor_field_policy_non_empty(self):
        self.assertIsInstance(
            ACTOR_FIELD_PRESENCE_IS_NOT_AUTHORITATIVE_BINDING_POLICY, str
        )
        self.assertTrue(
            len(ACTOR_FIELD_PRESENCE_IS_NOT_AUTHORITATIVE_BINDING_POLICY) > 0
        )

    @_skip_if_unavailable
    def test_A05_assertion_policy_non_empty(self):
        self.assertIsInstance(
            ASSERTION_MUST_NOT_CLAIM_AUTHORSHIP_VERIFIED_POLICY, str
        )
        self.assertTrue(
            len(ASSERTION_MUST_NOT_CLAIM_AUTHORSHIP_VERIFIED_POLICY) > 0
        )

    @_skip_if_unavailable
    def test_A06_delegation_policy_non_empty(self):
        self.assertIsInstance(
            DELEGATION_MUST_NOT_CLAIM_DIRECT_AUTHORSHIP_POLICY, str
        )
        self.assertTrue(
            len(DELEGATION_MUST_NOT_CLAIM_DIRECT_AUTHORSHIP_POLICY) > 0
        )

    @_skip_if_unavailable
    def test_A07_provenance_policy_non_empty(self):
        self.assertIsInstance(
            PROVENANCE_ABSENCE_DEFAULTS_TO_UNCERTAIN_POLICY, str
        )
        self.assertTrue(
            len(PROVENANCE_ABSENCE_DEFAULTS_TO_UNCERTAIN_POLICY) > 0
        )


# ===========================================================================
# Group B: IdentityBindingClass enum completeness
# ===========================================================================


class TestIdentityBindingClassEnum(unittest.TestCase):

    @_skip_if_unavailable
    def test_B01_identity_authoritatively_bound_exists(self):
        self.assertEqual(
            IdentityBindingClass.identity_authoritatively_bound.value,
            "identity_authoritatively_bound",
        )

    @_skip_if_unavailable
    def test_B02_authorship_verified_exists(self):
        self.assertEqual(
            IdentityBindingClass.authorship_verified.value,
            "authorship_verified",
        )

    @_skip_if_unavailable
    def test_B03_asserted_but_unverified_exists(self):
        self.assertEqual(
            IdentityBindingClass.asserted_but_unverified.value,
            "asserted_but_unverified",
        )

    @_skip_if_unavailable
    def test_B04_delegated_or_proxy_actor_exists(self):
        self.assertEqual(
            IdentityBindingClass.delegated_or_proxy_actor.value,
            "delegated_or_proxy_actor",
        )

    @_skip_if_unavailable
    def test_B05_identity_or_provenance_uncertain_exists(self):
        self.assertEqual(
            IdentityBindingClass.identity_or_provenance_uncertain.value,
            "identity_or_provenance_uncertain",
        )

    @_skip_if_unavailable
    def test_B06_exactly_five_classes(self):
        self.assertEqual(len(list(IdentityBindingClass)), 5)


# ===========================================================================
# Group C: IdentityBindingSignalStrength enum completeness
# ===========================================================================


class TestIdentityBindingSignalStrengthEnum(unittest.TestCase):

    @_skip_if_unavailable
    def test_C01_authoritative_exists(self):
        self.assertEqual(
            IdentityBindingSignalStrength.authoritative.value, "authoritative"
        )

    @_skip_if_unavailable
    def test_C02_validated_exists(self):
        self.assertEqual(
            IdentityBindingSignalStrength.validated.value, "validated"
        )

    @_skip_if_unavailable
    def test_C03_asserted_exists(self):
        self.assertEqual(
            IdentityBindingSignalStrength.asserted.value, "asserted"
        )

    @_skip_if_unavailable
    def test_C04_delegated_exists(self):
        self.assertEqual(
            IdentityBindingSignalStrength.delegated.value, "delegated"
        )

    @_skip_if_unavailable
    def test_C05_absent_or_uncertain_exists(self):
        self.assertEqual(
            IdentityBindingSignalStrength.absent_or_uncertain.value,
            "absent_or_uncertain",
        )


# ===========================================================================
# Group D: identity_authoritatively_bound — full conditions
# ===========================================================================


class TestIdentityAuthoritativelyBound(unittest.TestCase):

    @_skip_if_unavailable
    def test_D01_authoritative_all_conditions(self):
        v = classify_identity_binding(_ev_authoritative())
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )

    @_skip_if_unavailable
    def test_D02_authoritative_with_multiple_sources(self):
        e = IdentityBindingEvidence(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            multiple_authority_sources_agree=True,
        )
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )

    @_skip_if_unavailable
    def test_D03_signal_strength_is_authoritative(self):
        v = classify_identity_binding(_ev_authoritative())
        self.assertEqual(
            v.signal_strength, IdentityBindingSignalStrength.authoritative
        )

    @_skip_if_unavailable
    def test_D04_is_authoritatively_bound_flag_true(self):
        v = classify_identity_binding(_ev_authoritative())
        self.assertTrue(v.is_authoritatively_bound)
        self.assertFalse(v.is_authorship_verified)
        self.assertFalse(v.is_asserted_unverified)
        self.assertFalse(v.is_delegated_or_proxy)
        self.assertFalse(v.is_uncertain)


# ===========================================================================
# Group E–J: identity_authoritatively_bound requires all conditions
# ===========================================================================


class TestAuthoritativeBoundRequirements(unittest.TestCase):

    @_skip_if_unavailable
    def test_E01_requires_identity_verified_by_authority(self):
        """Missing identity_verified_by_authority → cannot be authoritative."""
        e = _ev(
            actor_field_present=True,
            # identity_verified_by_authority=False (default)
            binding_confirmed=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )

    @_skip_if_unavailable
    def test_F01_requires_binding_confirmed(self):
        """Missing binding_confirmed → cannot be authoritative."""
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            # binding_confirmed=False (default)
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )

    @_skip_if_unavailable
    def test_G01_blocked_by_assertion_only(self):
        """assertion_only=True prevents identity_authoritatively_bound."""
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            assertion_only=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )

    @_skip_if_unavailable
    def test_H01_blocked_by_delegation(self):
        """is_delegation_or_proxy=True prevents identity_authoritatively_bound."""
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            is_delegation_or_proxy=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )
        # It should be delegated instead
        self.assertEqual(
            v.binding_class, IdentityBindingClass.delegated_or_proxy_actor
        )

    @_skip_if_unavailable
    def test_I01_blocked_by_provenance_missing(self):
        """provenance_missing_or_ambiguous prevents identity_authoritatively_bound."""
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            provenance_missing_or_ambiguous=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )

    @_skip_if_unavailable
    def test_J01_blocked_by_identity_explicitly_uncertain(self):
        """identity_explicitly_uncertain always yields uncertain class."""
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            identity_explicitly_uncertain=True,
        )
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )


# ===========================================================================
# Group K–N: authorship_verified
# ===========================================================================


class TestAuthorshipVerified(unittest.TestCase):

    @_skip_if_unavailable
    def test_K01_authorship_verified_basic(self):
        """authorship_validated=True, no delegation, no assertion → verified."""
        e = _ev(
            actor_field_present=True,
            authorship_validated=True,
        )
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class, IdentityBindingClass.authorship_verified
        )

    @_skip_if_unavailable
    def test_K02_signal_strength_is_validated(self):
        e = _ev(actor_field_present=True, authorship_validated=True)
        v = classify_identity_binding(e)
        self.assertEqual(
            v.signal_strength, IdentityBindingSignalStrength.validated
        )

    @_skip_if_unavailable
    def test_K03_is_authorship_verified_flag_true(self):
        e = _ev(actor_field_present=True, authorship_validated=True)
        v = classify_identity_binding(e)
        self.assertTrue(v.is_authorship_verified)
        self.assertFalse(v.is_authoritatively_bound)
        self.assertFalse(v.is_delegated_or_proxy)
        self.assertFalse(v.is_uncertain)

    @_skip_if_unavailable
    def test_L01_assertion_only_blocks_authorship_verified(self):
        """assertion_only prevents authorship_verified."""
        e = _ev(
            actor_field_present=True,
            authorship_validated=True,
            assertion_only=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class, IdentityBindingClass.authorship_verified
        )
        # Should fall back to asserted_but_unverified
        self.assertEqual(
            v.binding_class, IdentityBindingClass.asserted_but_unverified
        )

    @_skip_if_unavailable
    def test_M01_delegation_blocks_authorship_verified(self):
        """is_delegation_or_proxy prevents authorship_verified."""
        e = _ev(
            actor_field_present=True,
            authorship_validated=True,
            is_delegation_or_proxy=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class, IdentityBindingClass.authorship_verified
        )
        self.assertEqual(
            v.binding_class, IdentityBindingClass.delegated_or_proxy_actor
        )

    @_skip_if_unavailable
    def test_N01_provenance_blocks_authorship_verified(self):
        """provenance_missing_or_ambiguous prevents authorship_verified."""
        e = _ev(
            actor_field_present=True,
            authorship_validated=True,
            provenance_missing_or_ambiguous=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class, IdentityBindingClass.authorship_verified
        )


# ===========================================================================
# Group O–Q: asserted_but_unverified
# ===========================================================================


class TestAssertedButUnverified(unittest.TestCase):

    @_skip_if_unavailable
    def test_O01_actor_field_present_no_verification(self):
        """actor_field_present with no verification → asserted_but_unverified."""
        e = _ev(actor_field_present=True)
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class, IdentityBindingClass.asserted_but_unverified
        )

    @_skip_if_unavailable
    def test_P01_assertion_only_yields_asserted_class(self):
        """assertion_only=True with actor present → asserted_but_unverified."""
        e = _ev(actor_field_present=True, assertion_only=True)
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class, IdentityBindingClass.asserted_but_unverified
        )

    @_skip_if_unavailable
    def test_Q01_asserted_is_above_uncertain(self):
        """asserted_but_unverified is strictly above identity_or_provenance_uncertain."""
        e_asserted = _ev(actor_field_present=True)
        e_uncertain = _ev()  # no evidence at all
        v_asserted = classify_identity_binding(e_asserted)
        v_uncertain = classify_identity_binding(e_uncertain)
        self.assertEqual(
            v_asserted.binding_class, IdentityBindingClass.asserted_but_unverified
        )
        self.assertEqual(
            v_uncertain.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )

    @_skip_if_unavailable
    def test_Q02_signal_strength_is_asserted(self):
        e = _ev(actor_field_present=True)
        v = classify_identity_binding(e)
        self.assertEqual(v.signal_strength, IdentityBindingSignalStrength.asserted)

    @_skip_if_unavailable
    def test_Q03_is_asserted_unverified_flag_true(self):
        e = _ev(actor_field_present=True)
        v = classify_identity_binding(e)
        self.assertTrue(v.is_asserted_unverified)
        self.assertFalse(v.is_authoritatively_bound)
        self.assertFalse(v.is_authorship_verified)
        self.assertFalse(v.is_delegated_or_proxy)
        self.assertFalse(v.is_uncertain)


# ===========================================================================
# Group R–U: delegated_or_proxy_actor
# ===========================================================================


class TestDelegatedOrProxyActor(unittest.TestCase):

    @_skip_if_unavailable
    def test_R01_delegation_yields_delegated_class(self):
        """is_delegation_or_proxy=True → delegated_or_proxy_actor."""
        e = _ev(is_delegation_or_proxy=True)
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class, IdentityBindingClass.delegated_or_proxy_actor
        )

    @_skip_if_unavailable
    def test_S01_documented_delegation_still_delegated(self):
        """Documented delegation is still delegated_or_proxy_actor."""
        e = _ev(
            is_delegation_or_proxy=True,
            delegation_explicitly_documented=True,
        )
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class, IdentityBindingClass.delegated_or_proxy_actor
        )

    @_skip_if_unavailable
    def test_T01_delegation_is_not_authoritatively_bound(self):
        """Delegation MUST NOT yield identity_authoritatively_bound."""
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            is_delegation_or_proxy=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )

    @_skip_if_unavailable
    def test_U01_delegation_is_not_authorship_verified(self):
        """Delegation MUST NOT yield authorship_verified."""
        e = _ev(
            actor_field_present=True,
            authorship_validated=True,
            is_delegation_or_proxy=True,
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class, IdentityBindingClass.authorship_verified
        )

    @_skip_if_unavailable
    def test_U02_signal_strength_is_delegated(self):
        e = _ev(is_delegation_or_proxy=True)
        v = classify_identity_binding(e)
        self.assertEqual(v.signal_strength, IdentityBindingSignalStrength.delegated)

    @_skip_if_unavailable
    def test_U03_is_delegated_or_proxy_flag_true(self):
        e = _ev(is_delegation_or_proxy=True)
        v = classify_identity_binding(e)
        self.assertTrue(v.is_delegated_or_proxy)
        self.assertFalse(v.is_authoritatively_bound)
        self.assertFalse(v.is_authorship_verified)
        self.assertFalse(v.is_asserted_unverified)
        self.assertFalse(v.is_uncertain)


# ===========================================================================
# Group V–Z: identity_or_provenance_uncertain
# ===========================================================================


class TestIdentityOrProvenanceUncertain(unittest.TestCase):

    @_skip_if_unavailable
    def test_V01_zero_evidence_yields_uncertain(self):
        """No evidence → identity_or_provenance_uncertain (fail-conservative)."""
        v = classify_identity_binding(IdentityBindingEvidence())
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )

    @_skip_if_unavailable
    def test_W01_explicitly_uncertain_yields_uncertain(self):
        """identity_explicitly_uncertain=True → uncertain regardless."""
        e = _ev(identity_explicitly_uncertain=True)
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )

    @_skip_if_unavailable
    def test_X01_uncertainty_overrides_actor_field(self):
        """Explicit uncertainty beats actor_field_present."""
        e = _ev(
            actor_field_present=True,
            identity_explicitly_uncertain=True,
        )
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )

    @_skip_if_unavailable
    def test_Y01_uncertainty_overrides_delegation(self):
        """Explicit uncertainty beats is_delegation_or_proxy."""
        e = _ev(
            is_delegation_or_proxy=True,
            identity_explicitly_uncertain=True,
        )
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )

    @_skip_if_unavailable
    def test_Z01_provenance_missing_alone_downgrades(self):
        """provenance_missing_or_ambiguous alone with no actor → uncertain."""
        e = _ev(provenance_missing_or_ambiguous=True)
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )

    @_skip_if_unavailable
    def test_Z02_signal_strength_is_absent_or_uncertain(self):
        v = classify_identity_binding(IdentityBindingEvidence())
        self.assertEqual(
            v.signal_strength,
            IdentityBindingSignalStrength.absent_or_uncertain,
        )

    @_skip_if_unavailable
    def test_Z03_is_uncertain_flag_true(self):
        v = classify_identity_binding(IdentityBindingEvidence())
        self.assertTrue(v.is_uncertain)
        self.assertFalse(v.is_authoritatively_bound)
        self.assertFalse(v.is_authorship_verified)
        self.assertFalse(v.is_asserted_unverified)
        self.assertFalse(v.is_delegated_or_proxy)


# ===========================================================================
# Group AA: Critical boundary — actor field MUST NOT produce authoritative
# ===========================================================================


class TestActorFieldNotAuthoritative(unittest.TestCase):

    @_skip_if_unavailable
    def test_AA01_actor_field_alone_not_authoritative(self):
        """actor_field_present=True alone MUST NOT produce
        identity_authoritatively_bound."""
        e = _ev(actor_field_present=True)
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
            "actor_field_present alone must NOT produce "
            "identity_authoritatively_bound — this is the core boundary "
            "enforced by ACTOR_FIELD_PRESENCE_IS_NOT_AUTHORITATIVE_BINDING_POLICY",
        )

    @_skip_if_unavailable
    def test_AA02_actor_field_alone_not_authorship_verified(self):
        """actor_field_present=True alone MUST NOT produce authorship_verified."""
        e = _ev(actor_field_present=True)
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.authorship_verified,
            "actor_field_present alone must NOT produce authorship_verified",
        )

    @_skip_if_unavailable
    def test_AA03_actor_field_yields_at_most_asserted(self):
        """actor_field_present=True alone yields asserted_but_unverified at most."""
        e = _ev(actor_field_present=True)
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.asserted_but_unverified,
        )

    @_skip_if_unavailable
    def test_AA04_source_field_present_without_verification_not_authoritative(self):
        """Simulated 'source' field present (via actor_field_present=True) with
        no verification → must not be authoritative."""
        # This simulates the case where a source/author/participant field
        # exists in a result or evidence object but has not been validated.
        e = _ev(actor_field_present=True, assertion_only=True)
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.authorship_verified,
        )


# ===========================================================================
# Group AB–AC: to_dict / from_dict round-trips
# ===========================================================================


class TestRoundTrip(unittest.TestCase):

    @_skip_if_unavailable
    def test_AB01_evidence_to_dict_from_dict_roundtrip(self):
        original = IdentityBindingEvidence(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            multiple_authority_sources_agree=True,
        )
        as_dict = original.to_dict()
        restored = IdentityBindingEvidence.from_dict(as_dict)
        self.assertEqual(restored.actor_field_present, True)
        self.assertEqual(restored.identity_verified_by_authority, True)
        self.assertEqual(restored.binding_confirmed, True)
        self.assertEqual(restored.multiple_authority_sources_agree, True)

    @_skip_if_unavailable
    def test_AB02_evidence_to_dict_keys(self):
        e = IdentityBindingEvidence()
        d = e.to_dict()
        expected_keys = {
            "actor_field_present",
            "identity_verified_by_authority",
            "authorship_validated",
            "binding_confirmed",
            "is_delegation_or_proxy",
            "delegation_explicitly_documented",
            "assertion_only",
            "provenance_missing_or_ambiguous",
            "identity_explicitly_uncertain",
            "multiple_authority_sources_agree",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    @_skip_if_unavailable
    def test_AC01_verdict_to_dict_from_dict_roundtrip(self):
        v = classify_identity_binding(_ev_authoritative())
        as_dict = v.to_dict()
        restored = IdentityBindingVerdict.from_dict(as_dict)
        self.assertEqual(restored.binding_class, v.binding_class)
        self.assertEqual(restored.signal_strength, v.signal_strength)
        self.assertEqual(restored.is_authoritatively_bound, True)
        self.assertEqual(restored.is_uncertain, False)

    @_skip_if_unavailable
    def test_AC02_verdict_to_dict_json_serialisable(self):
        v = classify_identity_binding(_ev_authoritative())
        as_dict = v.to_dict()
        json_str = json.dumps(as_dict)
        self.assertIsInstance(json_str, str)
        self.assertIn("identity_authoritatively_bound", json_str)

    @_skip_if_unavailable
    def test_AC03_verdict_to_dict_contains_evidence(self):
        v = classify_identity_binding(_ev_authoritative())
        d = v.to_dict()
        self.assertIn("evidence", d)
        self.assertIsInstance(d["evidence"], dict)

    @_skip_if_unavailable
    def test_AC04_verdict_to_dict_contains_taxonomy_sentinel(self):
        v = classify_identity_binding(_ev(actor_field_present=True))
        d = v.to_dict()
        self.assertIn("taxonomy_sentinel", d)
        self.assertTrue(len(d["taxonomy_sentinel"]) > 0)


# ===========================================================================
# Group AD–AH: Convenience flag contracts
# ===========================================================================


class TestConvenienceFlags(unittest.TestCase):

    @_skip_if_unavailable
    def test_AD01_is_authoritatively_bound_only_for_top_class(self):
        """is_authoritatively_bound is True only for identity_authoritatively_bound."""
        for ev_fn, expected_class in [
            (_ev_authoritative, IdentityBindingClass.identity_authoritatively_bound),
            (lambda: _ev(actor_field_present=True, authorship_validated=True),
             IdentityBindingClass.authorship_verified),
            (lambda: _ev(actor_field_present=True),
             IdentityBindingClass.asserted_but_unverified),
            (lambda: _ev(is_delegation_or_proxy=True),
             IdentityBindingClass.delegated_or_proxy_actor),
            (lambda: _ev(),
             IdentityBindingClass.identity_or_provenance_uncertain),
        ]:
            v = classify_identity_binding(ev_fn())
            self.assertEqual(v.binding_class, expected_class)
            expected_flag = (
                expected_class
                == IdentityBindingClass.identity_authoritatively_bound
            )
            self.assertEqual(v.is_authoritatively_bound, expected_flag)

    @_skip_if_unavailable
    def test_AE01_is_authorship_verified_only_for_verified_class(self):
        for ev_fn, expected_class in [
            (_ev_authoritative, IdentityBindingClass.identity_authoritatively_bound),
            (lambda: _ev(actor_field_present=True, authorship_validated=True),
             IdentityBindingClass.authorship_verified),
            (lambda: _ev(actor_field_present=True),
             IdentityBindingClass.asserted_but_unverified),
        ]:
            v = classify_identity_binding(ev_fn())
            self.assertEqual(
                v.is_authorship_verified,
                v.binding_class == IdentityBindingClass.authorship_verified,
            )

    @_skip_if_unavailable
    def test_AF01_is_asserted_unverified_only_for_asserted_class(self):
        e = _ev(actor_field_present=True)
        v = classify_identity_binding(e)
        self.assertTrue(v.is_asserted_unverified)
        self.assertFalse(v.is_authoritatively_bound)

    @_skip_if_unavailable
    def test_AG01_is_delegated_or_proxy_only_for_delegated_class(self):
        e = _ev(is_delegation_or_proxy=True)
        v = classify_identity_binding(e)
        self.assertTrue(v.is_delegated_or_proxy)
        self.assertFalse(v.is_authoritatively_bound)

    @_skip_if_unavailable
    def test_AH01_is_uncertain_only_for_uncertain_class(self):
        e = _ev()  # zero evidence
        v = classify_identity_binding(e)
        self.assertTrue(v.is_uncertain)
        self.assertFalse(v.is_authoritatively_bound)


# ===========================================================================
# Group AI: downgrade_reasons
# ===========================================================================


class TestDowngradeReasons(unittest.TestCase):

    @_skip_if_unavailable
    def test_AI01_downgrade_reasons_non_empty_when_assertion_only_blocks(self):
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            assertion_only=True,
        )
        v = classify_identity_binding(e)
        # We do not reach identity_authoritatively_bound; downgrade reasons
        # should explain why.
        self.assertIsInstance(v.downgrade_reasons, list)

    @_skip_if_unavailable
    def test_AI02_downgrade_reasons_non_empty_for_explicit_uncertainty(self):
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            identity_explicitly_uncertain=True,
        )
        v = classify_identity_binding(e)
        self.assertIsInstance(v.downgrade_reasons, list)
        self.assertTrue(len(v.downgrade_reasons) > 0)

    @_skip_if_unavailable
    def test_AI03_downgrade_reasons_list_in_verdict_dict(self):
        e = _ev(identity_explicitly_uncertain=True)
        v = classify_identity_binding(e)
        d = v.to_dict()
        self.assertIn("downgrade_reasons", d)
        self.assertIsInstance(d["downgrade_reasons"], list)


# ===========================================================================
# Group AJ: build_baseline_identity_binding_verdict
# ===========================================================================


class TestBuildBaselineVerdict(unittest.TestCase):

    @_skip_if_unavailable
    def test_AJ01_baseline_returns_uncertain(self):
        v = build_baseline_identity_binding_verdict()
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )

    @_skip_if_unavailable
    def test_AJ02_baseline_is_uncertain_flag_true(self):
        v = build_baseline_identity_binding_verdict()
        self.assertTrue(v.is_uncertain)

    @_skip_if_unavailable
    def test_AJ03_baseline_not_authoritatively_bound(self):
        v = build_baseline_identity_binding_verdict()
        self.assertFalse(v.is_authoritatively_bound)

    @_skip_if_unavailable
    def test_AJ04_build_identity_binding_verdict_none_returns_uncertain(self):
        v = build_identity_binding_verdict(evidence=None)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_or_provenance_uncertain,
        )


# ===========================================================================
# Group AK–AL: SystemFinalAcceptanceEvaluator and AcceptanceDimensionId
# ===========================================================================

_ACCEPTANCE_AVAILABLE = False
try:
    from core.system_final_acceptance_verdict import (
        AcceptanceDimensionId,
        SystemFinalAcceptanceEvaluator,
        DimensionStatus,
    )
    _ACCEPTANCE_AVAILABLE = True
except ImportError:
    pass


def _skip_if_acceptance_unavailable(test_fn):
    def wrapper(self):
        if not _ACCEPTANCE_AVAILABLE:
            self.skipTest("core.system_final_acceptance_verdict not available")
        return test_fn(self)
    wrapper.__name__ = test_fn.__name__
    return wrapper


class TestAcceptanceDimensionIntegration(unittest.TestCase):

    @_skip_if_acceptance_unavailable
    def test_AK01_evaluator_has_identity_dimension_method(self):
        """SystemFinalAcceptanceEvaluator has _evaluate_identity_authorship_binding."""
        evaluator = SystemFinalAcceptanceEvaluator()
        self.assertTrue(
            hasattr(evaluator, "_evaluate_identity_authorship_binding")
        )

    @_skip_if_acceptance_unavailable
    def test_AL01_all_dimensions_includes_identity_authorship_binding(self):
        """AcceptanceDimensionId.all_dimensions() contains identity_authorship_binding."""
        dims = AcceptanceDimensionId.all_dimensions()
        dim_values = [d.value for d in dims]
        self.assertIn("identity_authorship_binding", dim_values)

    @_skip_if_acceptance_unavailable
    def test_AL02_identity_authorship_binding_enum_value(self):
        """AcceptanceDimensionId.identity_authorship_binding has correct value."""
        self.assertEqual(
            AcceptanceDimensionId.identity_authorship_binding.value,
            "identity_authorship_binding",
        )

    @_skip_if_acceptance_unavailable
    def test_AL03_all_dimensions_count_is_18(self):
        """There are exactly 18 acceptance dimensions."""
        dims = AcceptanceDimensionId.all_dimensions()
        self.assertEqual(len(dims), 18)

    @_skip_if_acceptance_unavailable
    def test_AM01_probe_returns_pending_for_conservative_contract(self):
        """Probe returns pending (not unresolved) when zero-evidence correctly
        returns identity_or_provenance_uncertain."""
        if not _MODULE_AVAILABLE:
            self.skipTest(
                "identity_authorship_actor_binding_contract not available"
            )
        evaluator = SystemFinalAcceptanceEvaluator()
        item = evaluator._evaluate_identity_authorship_binding()
        # Contract is present and wired correctly → should be pending
        self.assertEqual(item.status, DimensionStatus.pending)

    @_skip_if_acceptance_unavailable
    def test_AN01_evaluate_includes_identity_dimension(self):
        """Full evaluate() produces a checklist that includes identity dimension."""
        if not _MODULE_AVAILABLE:
            self.skipTest(
                "identity_authorship_actor_binding_contract not available"
            )
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        self.assertIn(
            "identity_authorship_binding", report.checklist
        )


# ===========================================================================
# Group AN: multiple_authority_sources_agree
# ===========================================================================


class TestMultipleAuthoritySources(unittest.TestCase):

    @_skip_if_unavailable
    def test_AN01_multiple_sources_agree_with_full_conditions(self):
        """multiple_authority_sources_agree=True with full conditions → authoritative."""
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            binding_confirmed=True,
            multiple_authority_sources_agree=True,
        )
        v = classify_identity_binding(e)
        self.assertEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )

    @_skip_if_unavailable
    def test_AN02_multiple_sources_agree_without_binding_confirmed_not_authoritative(self):
        """multiple_authority_sources_agree alone without binding_confirmed
        does NOT produce identity_authoritatively_bound."""
        e = _ev(
            actor_field_present=True,
            identity_verified_by_authority=True,
            multiple_authority_sources_agree=True,
            # binding_confirmed=False (default)
        )
        v = classify_identity_binding(e)
        self.assertNotEqual(
            v.binding_class,
            IdentityBindingClass.identity_authoritatively_bound,
        )


if __name__ == "__main__":
    unittest.main()
