#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_participation_enrich_only.py
==========================================
PR-5: Participation enrich-only tests.

Validates that ``core.device_participation`` is strictly an enrichment layer:

  * ``PARTICIPATION_ENRICH_ONLY = True``
  * ``PARTICIPATION_CANNOT_OVERRIDE_CANONICAL_TRUTH`` is a non-empty governance string.
  * ``registered``, ``runtime_present``, ``routable`` in ``ParticipationSummary``
    are populated from Layer-1 readiness (``core.device_readiness``), NOT from
    selector/session/mesh data.
  * Mesh/session enrichment populates role fields but does NOT change the
    canonical readiness-sourced truth fields.
  * A device that the selector marks eligible but fails Layer-1 readiness
    must NOT be ``orchestration_eligible``.

Test classes
------------
1. TestParticipationEnrichOnlySentinels
       PARTICIPATION_ENRICH_ONLY and PARTICIPATION_CANNOT_OVERRIDE_CANONICAL_TRUTH
       are importable and have expected values.

2. TestRegisteredSourcedFromReadiness
       registered in ParticipationSummary always reflects Layer-1 readiness.
       Selector returning eligible cannot set registered=True when readiness
       says registered=False.

3. TestRoutableSourcedFromReadiness
       routable in ParticipationSummary always reflects Layer-1 readiness.
       Mesh membership cannot set routable=True when readiness says False.

4. TestRuntimePresentSourcedFromReadiness
       runtime_present in ParticipationSummary always reflects Layer-1 online.

5. TestOrchestrationEligibilityGatedOnReadiness
       A device that passes the selector but fails Layer-1 readiness
       is NOT orchestration_eligible.

6. TestMeshSessionEnrichesRolesNotTruth
       Mesh/session data may enrich roles/session_id but must not change
       registered/runtime_present/routable.

7. TestParticipationSummaryNoOverride
       Direct construction: setting registered=True via mesh alone is
       structurally impossible because the field comes only from readiness step.
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.device_participation import (
    ParticipationSummary,
    get_device_participation,
    DEVICE_PARTICIPATION_AUTHORITY,
    PARTICIPATION_BUILDS_ON_READINESS,
    PARTICIPATION_ENRICH_ONLY,
    PARTICIPATION_CANNOT_OVERRIDE_CANONICAL_TRUTH,
    PARTICIPATION_TRUTH_SOURCE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_readiness(
    device_id="dev1",
    registered=True,
    online=True,
    connected=True,
    routable=True,
):
    rs = MagicMock()
    rs.registered = registered
    rs.online = online
    rs.connected = connected
    rs.routable = routable
    rs.to_dict = lambda: {
        "device_id": device_id,
        "registered": registered,
        "online": online,
        "connected": connected,
        "routable": routable,
    }
    return rs


# ---------------------------------------------------------------------------
# 1. TestParticipationEnrichOnlySentinels
# ---------------------------------------------------------------------------


class TestParticipationEnrichOnlySentinels(unittest.TestCase):
    def test_participation_enrich_only_is_true(self):
        self.assertTrue(PARTICIPATION_ENRICH_ONLY)

    def test_participation_cannot_override_is_nonempty_string(self):
        self.assertIsInstance(PARTICIPATION_CANNOT_OVERRIDE_CANONICAL_TRUTH, str)
        self.assertTrue(len(PARTICIPATION_CANNOT_OVERRIDE_CANONICAL_TRUTH) > 0)

    def test_governance_string_mentions_enrich_only(self):
        self.assertIn("ENRICH_ONLY", PARTICIPATION_CANNOT_OVERRIDE_CANONICAL_TRUTH)

    def test_builds_on_readiness_still_true(self):
        self.assertTrue(PARTICIPATION_BUILDS_ON_READINESS)

    def test_authority_sentinel_stable(self):
        self.assertEqual(DEVICE_PARTICIPATION_AUTHORITY, "DEVICE_PARTICIPATION_LAYER_V2")

    def test_sentinels_in_exports(self):
        from core.device_participation import __all__ as exports
        self.assertIn("PARTICIPATION_ENRICH_ONLY", exports)
        self.assertIn("PARTICIPATION_CANNOT_OVERRIDE_CANONICAL_TRUTH", exports)


# ---------------------------------------------------------------------------
# 2. TestRegisteredSourcedFromReadiness
# ---------------------------------------------------------------------------


class TestRegisteredSourcedFromReadiness(unittest.TestCase):
    def test_registered_false_when_readiness_says_false(self):
        rs = _make_readiness(registered=False, routable=False)
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertFalse(ps.registered)

    def test_registered_true_when_readiness_says_true(self):
        rs = _make_readiness(registered=True)
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertTrue(ps.registered)

    def test_selector_eligible_cannot_set_registered_when_readiness_false(self):
        """Selector saying eligible must not make registered=True via participation."""
        rs = _make_readiness(registered=False, routable=False)
        sel = MagicMock()
        sel.orchestration_eligible = True
        sel.to_dict = lambda: {"orchestration_eligible": True}
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=sel), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertFalse(ps.registered)


# ---------------------------------------------------------------------------
# 3. TestRoutableSourcedFromReadiness
# ---------------------------------------------------------------------------


class TestRoutableSourcedFromReadiness(unittest.TestCase):
    def test_routable_false_when_readiness_says_false(self):
        rs = _make_readiness(registered=True, routable=False)
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertFalse(ps.routable)

    def test_routable_true_when_readiness_says_true(self):
        rs = _make_readiness(registered=True, routable=True)
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertTrue(ps.routable)

    def test_mesh_membership_cannot_override_routable_false(self):
        """Mesh membership must not set routable=True when readiness says False."""
        rs = _make_readiness(registered=True, routable=False)
        mesh = MagicMock()
        mesh.roles = ["primary"]
        mesh.authority_scope = None
        mesh.routing_intent = None
        mesh.to_dict = lambda: {"member_device_id": "dev1"}
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=mesh), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        # routable must still be False despite mesh membership
        self.assertFalse(ps.routable)


# ---------------------------------------------------------------------------
# 4. TestRuntimePresentSourcedFromReadiness
# ---------------------------------------------------------------------------


class TestRuntimePresentSourcedFromReadiness(unittest.TestCase):
    def test_runtime_present_false_when_offline(self):
        rs = _make_readiness(registered=True, online=False, routable=True)
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertFalse(ps.runtime_present)

    def test_runtime_present_true_when_online(self):
        rs = _make_readiness(registered=True, online=True, routable=True)
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertTrue(ps.runtime_present)


# ---------------------------------------------------------------------------
# 5. TestOrchestrationEligibilityGatedOnReadiness
# ---------------------------------------------------------------------------


class TestOrchestrationEligibilityGatedOnReadiness(unittest.TestCase):
    def test_selector_eligible_but_not_registered_means_ineligible(self):
        rs = _make_readiness(registered=False, routable=False)
        sel = MagicMock()
        sel.orchestration_eligible = True
        sel.to_dict = lambda: {"orchestration_eligible": True}
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=sel), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertFalse(ps.orchestration_eligible)

    def test_selector_eligible_but_not_routable_means_ineligible(self):
        rs = _make_readiness(registered=True, routable=False)
        sel = MagicMock()
        sel.orchestration_eligible = True
        sel.to_dict = lambda: {"orchestration_eligible": True}
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=sel), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertFalse(ps.orchestration_eligible)

    def test_selector_eligible_and_readiness_ok_means_eligible(self):
        rs = _make_readiness(registered=True, routable=True)
        sel = MagicMock()
        sel.orchestration_eligible = True
        sel.to_dict = lambda: {"orchestration_eligible": True}
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=sel), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertTrue(ps.orchestration_eligible)


# ---------------------------------------------------------------------------
# 6. TestMeshSessionEnrichesRolesNotTruth
# ---------------------------------------------------------------------------


class TestMeshSessionEnrichesRolesNotTruth(unittest.TestCase):
    def test_mesh_adds_roles_but_not_registered(self):
        rs = _make_readiness(registered=False, routable=False)
        mesh = MagicMock()
        mesh.roles = ["primary", "source"]
        mesh.authority_scope = None
        mesh.routing_intent = None
        mesh.to_dict = lambda: {}
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=mesh), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        # Mesh enriches roles but cannot set registered=True
        self.assertFalse(ps.registered)
        # Roles are still enriched from mesh
        self.assertTrue(len(ps.roles) > 0 or ps.mesh_member)

    def test_session_sets_session_id_but_not_routable(self):
        rs = _make_readiness(registered=True, routable=False)
        session = MagicMock()
        session.session_id = "sess-abc"
        session.participants = []
        session.primary_device_id = "other"
        session.source_device_id = "other"
        with patch("core.device_participation._get_canonical_readiness", return_value=rs), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=session):
            ps = get_device_participation("dev1")
        # Session enriches session_id but routable stays False
        self.assertFalse(ps.routable)
        self.assertEqual(ps.session_id, "sess-abc")


# ---------------------------------------------------------------------------
# 7. TestParticipationSummaryNoOverride
# ---------------------------------------------------------------------------


class TestParticipationSummaryNoOverride(unittest.TestCase):
    def test_participation_summary_default_truth_fields_are_false(self):
        """Default ParticipationSummary has canonical truth fields as False."""
        ps = ParticipationSummary(device_id="dev1")
        self.assertFalse(ps.registered)
        self.assertFalse(ps.runtime_present)
        self.assertFalse(ps.routable)
        self.assertFalse(ps.orchestration_eligible)

    def test_truth_source_string_mentions_readiness_layer(self):
        self.assertIn("DEVICE_READINESS_LAYER", PARTICIPATION_TRUTH_SOURCE)


if __name__ == "__main__":
    unittest.main()
