"""
tests/test_device_participation.py
====================================
Focused tests for ``core.device_participation`` — the canonical participation
and orchestration readiness summary layer.

Coverage:
  - ParticipationSummary serialises correctly via ``to_dict()``.
  - ``get_device_participation`` returns assessed=True / orchestration_eligible
    when selector data is available.
  - Missing device returns assessed=False / not-ready style summary gracefully.
  - Missing optional mesh/session sources do not crash summary generation.
  - ``get_orchestration_ready_devices()`` filters consistently by
    orchestration readiness.
  - ``is_device_orchestration_ready()`` mirrors the filter correctly.
  - Authority sentinel is importable and non-empty.
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.device_participation import (
    ParticipationSummary,
    DEVICE_PARTICIPATION_AUTHORITY,
    PARTICIPATION_BUILDS_ON_READINESS,
    get_device_participation,
    get_orchestration_ready_devices,
    is_device_orchestration_ready,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_selector_status(
    registered: bool = True,
    runtime_present: bool = True,
    routable: bool = True,
    orchestration_eligible: bool = True,
    reason: str = "all-eligible",
):
    """Build a minimal mock DeviceParticipationStatus."""
    status = MagicMock()
    status.registered = registered
    status.runtime_present = runtime_present
    status.routable = routable
    status.orchestration_eligible = orchestration_eligible
    status.participation_reason = reason
    status.to_dict.return_value = {
        "registered": registered,
        "runtime_present": runtime_present,
        "routable": routable,
        "orchestration_eligible": orchestration_eligible,
        "participation_reason": reason,
    }
    return status


def _make_readiness_summary(
    registered: bool = True,
    online: bool = True,
    routable: bool = True,
    device_id: str = "dev",
):
    """Build a minimal mock DeviceReadinessSummary for Layer-1 canonical readiness."""
    rs = MagicMock()
    rs.device_id = device_id
    rs.registered = registered
    rs.online = online
    rs.routable = routable
    rs.connected = online
    rs.to_dict.return_value = {
        "device_id": device_id,
        "registered": registered,
        "online": online,
        "routable": routable,
    }
    return rs


def _patch_canonical_readiness(device_id: str, readiness):
    """Return a context manager that patches ``_get_canonical_readiness`` for *device_id*."""
    return patch(
        "core.device_participation._get_canonical_readiness",
        side_effect=lambda did: readiness if did == device_id else None,
    )


def _make_udm_device(device_id: str):
    device = MagicMock()
    device.device_id = device_id
    return device


def _make_udm(device_ids=None):
    udm = MagicMock()
    devices = [_make_udm_device(d) for d in (device_ids or [])]
    udm.list_devices.return_value = devices
    udm.get.side_effect = lambda did: next(
        (d for d in devices if d.device_id == did), None
    )
    return udm


# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------


class TestAuthoritySentinel(unittest.TestCase):
    def test_sentinel_is_non_empty_string(self):
        self.assertIsInstance(DEVICE_PARTICIPATION_AUTHORITY, str)
        self.assertTrue(len(DEVICE_PARTICIPATION_AUTHORITY) > 0)

    def test_sentinel_value(self):
        self.assertEqual(DEVICE_PARTICIPATION_AUTHORITY, "DEVICE_PARTICIPATION_LAYER_V2")

    def test_participation_builds_on_readiness_sentinel(self):
        self.assertTrue(PARTICIPATION_BUILDS_ON_READINESS)


# ---------------------------------------------------------------------------
# ParticipationSummary model
# ---------------------------------------------------------------------------


class TestParticipationSummaryModel(unittest.TestCase):
    def test_to_dict_contains_all_required_keys(self):
        ps = ParticipationSummary(device_id="dev1")
        d = ps.to_dict()
        for key in (
            "device_id", "assessed", "registered", "runtime_present",
            "routable", "orchestration_eligible", "mesh_member", "session_id",
            "roles", "authority_scope", "routing_intent",
            "is_primary", "is_source", "is_support", "is_relay",
            "reasons", "sources",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_default_values(self):
        ps = ParticipationSummary(device_id="dev2")
        d = ps.to_dict()
        self.assertEqual(d["device_id"], "dev2")
        self.assertFalse(d["assessed"])
        self.assertFalse(d["registered"])
        self.assertFalse(d["runtime_present"])
        self.assertFalse(d["routable"])
        self.assertFalse(d["orchestration_eligible"])
        self.assertFalse(d["mesh_member"])
        self.assertIsNone(d["session_id"])
        self.assertEqual(d["roles"], [])
        self.assertIsNone(d["authority_scope"])
        self.assertIsNone(d["routing_intent"])
        self.assertFalse(d["is_primary"])
        self.assertFalse(d["is_source"])
        self.assertFalse(d["is_support"])
        self.assertFalse(d["is_relay"])
        self.assertEqual(d["reasons"], [])
        self.assertEqual(d["sources"], {})

    def test_to_dict_custom_values(self):
        ps = ParticipationSummary(
            device_id="dev3",
            assessed=True,
            registered=True,
            runtime_present=True,
            routable=True,
            orchestration_eligible=True,
            mesh_member=True,
            session_id="sess-1",
            roles=["primary", "source"],
            authority_scope="mesh_authority",
            routing_intent="local_preferred",
            is_primary=True,
            is_source=True,
            is_support=False,
            is_relay=False,
            reasons=["all-eligible"],
            sources={"selector": {"registered": True}},
        )
        d = ps.to_dict()
        self.assertEqual(d["device_id"], "dev3")
        self.assertTrue(d["assessed"])
        self.assertTrue(d["orchestration_eligible"])
        self.assertEqual(d["session_id"], "sess-1")
        self.assertEqual(d["roles"], ["primary", "source"])
        self.assertTrue(d["is_primary"])
        self.assertTrue(d["is_source"])

    def test_to_dict_returns_copies_not_references(self):
        """Mutating the original after to_dict should not affect the dict."""
        ps = ParticipationSummary(device_id="dev4", roles=["relay"])
        d = ps.to_dict()
        ps.roles.append("extra")
        self.assertEqual(d["roles"], ["relay"])


# ---------------------------------------------------------------------------
# get_device_participation — selector data available
# ---------------------------------------------------------------------------


class TestGetDeviceParticipationWithSelectorData(unittest.TestCase):
    """Summary is populated when selector data is available."""

    def _patch_selector(self, device_id, status):
        """Patch _get_selector_status to return *status* for *device_id*."""
        return patch(
            "core.device_participation._get_selector_status",
            side_effect=lambda did: status if did == device_id else None,
        )

    def test_assessed_true_when_selector_available(self):
        status = _make_selector_status(orchestration_eligible=True)
        rs = _make_readiness_summary(registered=True, online=True, routable=True, device_id="dev-a")
        with self._patch_selector("dev-a", status), \
             _patch_canonical_readiness("dev-a", rs), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev-a")
        self.assertTrue(ps.assessed)

    def test_flags_propagated_from_canonical_readiness(self):
        # registered/runtime_present/routable come from Layer-1 canonical readiness.
        status = _make_selector_status(
            registered=True,
            runtime_present=True,
            routable=True,
            orchestration_eligible=True,
        )
        rs = _make_readiness_summary(registered=True, online=True, routable=True, device_id="dev-b")
        with self._patch_selector("dev-b", status), \
             _patch_canonical_readiness("dev-b", rs), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev-b")
        self.assertTrue(ps.registered)
        self.assertTrue(ps.runtime_present)
        self.assertTrue(ps.routable)
        self.assertTrue(ps.orchestration_eligible)

    def test_selector_source_recorded(self):
        status = _make_selector_status()
        rs = _make_readiness_summary(registered=True, online=True, routable=True, device_id="dev-c")
        with self._patch_selector("dev-c", status), \
             _patch_canonical_readiness("dev-c", rs), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev-c")
        self.assertIn("selector", ps.sources)

    def test_orchestration_ineligible_when_selector_says_so(self):
        status = _make_selector_status(
            registered=True,
            runtime_present=False,
            routable=False,
            orchestration_eligible=False,
        )
        rs = _make_readiness_summary(registered=True, online=True, routable=True, device_id="dev-d")
        with self._patch_selector("dev-d", status), \
             _patch_canonical_readiness("dev-d", rs), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev-d")
        self.assertFalse(ps.orchestration_eligible)

    def test_orchestration_ineligible_when_readiness_not_routable(self):
        # Selector says eligible, but Layer-1 readiness says not routable — must NOT be eligible.
        status = _make_selector_status(orchestration_eligible=True)
        rs = _make_readiness_summary(registered=True, online=True, routable=False, device_id="dev-e")
        with self._patch_selector("dev-e", status), \
             _patch_canonical_readiness("dev-e", rs), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev-e")
        self.assertFalse(ps.orchestration_eligible)

    def test_readiness_source_recorded(self):
        # Layer-1 readiness facts must be captured in sources["readiness"].
        status = _make_selector_status()
        rs = _make_readiness_summary(registered=True, online=True, routable=True, device_id="dev-f")
        with self._patch_selector("dev-f", status), \
             _patch_canonical_readiness("dev-f", rs), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev-f")
        self.assertIn("readiness", ps.sources)


# ---------------------------------------------------------------------------
# get_device_participation — missing device
# ---------------------------------------------------------------------------


class TestGetDeviceParticipationMissingDevice(unittest.TestCase):
    """Missing / unknown device returns assessed=False gracefully."""

    def test_empty_device_id_returns_not_assessed(self):
        ps = get_device_participation("")
        self.assertFalse(ps.assessed)
        self.assertIn("empty-device-id", ps.reasons)

    def test_unknown_device_returns_not_assessed(self):
        # Readiness returns None (unknown device) — registered/routable must be False.
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("ghost-device")
        self.assertFalse(ps.assessed)
        self.assertFalse(ps.registered)
        self.assertFalse(ps.orchestration_eligible)

    def test_selector_error_does_not_crash(self):
        rs = _make_readiness_summary(registered=False, online=False, routable=False, device_id="bad-device")
        with _patch_canonical_readiness("bad-device", rs), \
             patch(
                "core.device_participation._get_selector_status",
                side_effect=RuntimeError("selector exploded"),
             ), patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("bad-device")
        # Must return a ParticipationSummary, not raise
        self.assertIsInstance(ps, ParticipationSummary)
        self.assertFalse(ps.assessed)

    def test_unknown_device_id_preserved_in_summary(self):
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("unknown-xyz")
        self.assertEqual(ps.device_id, "unknown-xyz")


# ---------------------------------------------------------------------------
# get_device_participation — missing optional subsystems
# ---------------------------------------------------------------------------


class TestGetDeviceParticipationMissingSubsystems(unittest.TestCase):
    """Missing mesh/session sources should not crash summary generation."""

    def _ready_selector(self):
        return _make_selector_status(orchestration_eligible=True)

    def _ready_readiness(self, device_id="dev1"):
        return _make_readiness_summary(registered=True, online=True, routable=True, device_id=device_id)

    def test_mesh_membership_unavailable_does_not_crash(self):
        rs = self._ready_readiness("dev1")
        with patch(
            "core.device_participation._get_canonical_readiness", return_value=rs
        ), patch(
            "core.device_participation._get_selector_status",
            return_value=self._ready_selector(),
        ), patch(
            "core.device_participation._get_mesh_membership",
            side_effect=ImportError("no mesh"),
        ), patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertIsInstance(ps, ParticipationSummary)
        self.assertTrue(ps.assessed)

    def test_mesh_session_unavailable_does_not_crash(self):
        rs = self._ready_readiness("dev2")
        with patch(
            "core.device_participation._get_canonical_readiness", return_value=rs
        ), patch(
            "core.device_participation._get_selector_status",
            return_value=self._ready_selector(),
        ), patch(
            "core.device_participation._get_mesh_membership", return_value=None
        ), patch(
            "core.device_participation._get_mesh_session",
            side_effect=RuntimeError("session exploded"),
        ):
            ps = get_device_participation("dev2")
        self.assertIsInstance(ps, ParticipationSummary)
        self.assertTrue(ps.assessed)

    def test_all_subsystems_unavailable_returns_not_assessed(self):
        with patch(
            "core.device_participation._get_canonical_readiness", return_value=None
        ), patch(
            "core.device_participation._get_selector_status", return_value=None
        ), patch(
            "core.device_participation._get_mesh_membership", return_value=None
        ), patch(
            "core.device_participation._get_mesh_session", return_value=None
        ):
            ps = get_device_participation("dev3")
        self.assertFalse(ps.assessed)
        self.assertFalse(ps.orchestration_eligible)

    def test_mesh_membership_error_recorded_in_reasons(self):
        rs = self._ready_readiness("dev4")
        with patch(
            "core.device_participation._get_canonical_readiness", return_value=rs
        ), patch(
            "core.device_participation._get_selector_status",
            return_value=self._ready_selector(),
        ), patch(
            "core.device_participation._get_mesh_membership",
            side_effect=RuntimeError("mesh boom"),
        ), patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev4")
        # Should contain a reason mentioning the mesh error
        mesh_reasons = [r for r in ps.reasons if "mesh-error" in r]
        self.assertTrue(len(mesh_reasons) > 0)

    def test_session_unavailable_reason_recorded(self):
        rs = self._ready_readiness("dev5")
        with patch(
            "core.device_participation._get_canonical_readiness", return_value=rs
        ), patch(
            "core.device_participation._get_selector_status",
            return_value=self._ready_selector(),
        ), patch(
            "core.device_participation._get_mesh_membership", return_value=None
        ), patch(
            "core.device_participation._get_mesh_session", return_value=None
        ):
            ps = get_device_participation("dev5")
        self.assertIn("mesh-session-unavailable", ps.reasons)


# ---------------------------------------------------------------------------
# Mesh membership integration in summary
# ---------------------------------------------------------------------------


class TestMeshMembershipIntegration(unittest.TestCase):
    """When mesh membership is present, summary reflects it."""

    def _make_membership(self, device_id, roles=None, authority_scope=None, routing_intent=None):
        m = MagicMock()
        m.member_device_id = device_id
        m.roles = roles or []
        m.authority_scope = authority_scope
        m.routing_intent = routing_intent
        m.to_dict.return_value = {"member_device_id": device_id}
        return m

    def test_mesh_member_true_when_membership_present(self):
        m = self._make_membership("dev1")
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=m), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev1")
        self.assertTrue(ps.mesh_member)

    def test_roles_extracted_from_membership(self):
        role_a = MagicMock()
        role_a.value = "primary"
        role_b = MagicMock()
        role_b.value = "source"
        m = self._make_membership("dev2", roles=[role_a, role_b])
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=m), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev2")
        self.assertIn("primary", ps.roles)
        self.assertIn("source", ps.roles)

    def test_is_primary_set_from_roles(self):
        role = MagicMock()
        role.value = "primary"
        m = self._make_membership("dev3", roles=[role])
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=m), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev3")
        self.assertTrue(ps.is_primary)

    def test_authority_scope_extracted(self):
        scope = MagicMock()
        scope.value = "mesh_authority"
        m = self._make_membership("dev4", authority_scope=scope)
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=m), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev4")
        self.assertEqual(ps.authority_scope, "mesh_authority")

    def test_routing_intent_extracted(self):
        intent = MagicMock()
        intent.value = "local_preferred"
        m = self._make_membership("dev5", routing_intent=intent)
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=m), \
             patch("core.device_participation._get_mesh_session", return_value=None):
            ps = get_device_participation("dev5")
        self.assertEqual(ps.routing_intent, "local_preferred")


# ---------------------------------------------------------------------------
# Mesh session integration in summary
# ---------------------------------------------------------------------------


class TestMeshSessionIntegration(unittest.TestCase):
    """When mesh session is present, summary reflects it."""

    def _make_session(self, session_id, primary_id="", source_id="", participants=None):
        s = MagicMock()
        s.session_id = session_id
        s.primary_device_id = primary_id
        s.source_device_id = source_id
        s.participants = participants or []
        return s

    def _make_participant(self, device_id, roles=None):
        p = MagicMock()
        p.device_id = device_id
        p.roles = roles or []
        return p

    def test_session_id_recorded(self):
        sess = self._make_session("sess-abc", primary_id="dev1", source_id="dev1")
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=sess):
            ps = get_device_participation("dev1")
        self.assertEqual(ps.session_id, "sess-abc")

    def test_is_primary_from_session(self):
        sess = self._make_session("sess-1", primary_id="dev2")
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=sess):
            ps = get_device_participation("dev2")
        self.assertTrue(ps.is_primary)

    def test_is_source_from_session(self):
        sess = self._make_session("sess-2", source_id="dev3")
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=sess):
            ps = get_device_participation("dev3")
        self.assertTrue(ps.is_source)

    def test_session_roles_merged(self):
        p = self._make_participant("dev4", roles=["support"])
        sess = self._make_session("sess-3", participants=[p])
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=sess):
            ps = get_device_participation("dev4")
        self.assertIn("support", ps.roles)
        self.assertTrue(ps.is_support)

    def test_session_source_recorded(self):
        sess = self._make_session("sess-4", primary_id="dev5")
        with patch("core.device_participation._get_canonical_readiness", return_value=None), \
             patch("core.device_participation._get_selector_status", return_value=None), \
             patch("core.device_participation._get_mesh_membership", return_value=None), \
             patch("core.device_participation._get_mesh_session", return_value=sess):
            ps = get_device_participation("dev5")
        self.assertIn("mesh_session", ps.sources)


# ---------------------------------------------------------------------------
# get_orchestration_ready_devices
# ---------------------------------------------------------------------------


class TestGetOrchestrationReadyDevices(unittest.TestCase):
    """get_orchestration_ready_devices() filters consistently by orchestration readiness."""

    def _build_ps(self, device_id: str, eligible: bool) -> ParticipationSummary:
        ps = ParticipationSummary(device_id=device_id)
        ps.assessed = True
        ps.registered = True
        ps.orchestration_eligible = eligible
        return ps

    def test_returns_only_eligible_devices(self):
        udm = _make_udm(["dev-a", "dev-b"])
        ready_a = self._build_ps("dev-a", eligible=True)
        not_ready_b = self._build_ps("dev-b", eligible=False)

        def _fake_participation(device_id):
            return ready_a if device_id == "dev-a" else not_ready_b

        with patch("core.device_participation._get_udm", return_value=udm), \
             patch("core.device_participation.get_device_participation",
                   side_effect=_fake_participation):
            result = get_orchestration_ready_devices()

        ids = [ps.device_id for ps in result]
        self.assertIn("dev-a", ids)
        self.assertNotIn("dev-b", ids)

    def test_udm_unavailable_returns_empty(self):
        with patch("core.device_participation._get_udm", return_value=None):
            result = get_orchestration_ready_devices()
        self.assertEqual(result, [])

    def test_udm_list_fails_returns_empty(self):
        udm = MagicMock()
        udm.list_devices.side_effect = RuntimeError("db crash")
        with patch("core.device_participation._get_udm", return_value=udm):
            result = get_orchestration_ready_devices()
        self.assertEqual(result, [])

    def test_empty_device_list_returns_empty(self):
        udm = _make_udm([])
        with patch("core.device_participation._get_udm", return_value=udm):
            result = get_orchestration_ready_devices()
        self.assertEqual(result, [])

    def test_per_device_error_does_not_abort(self):
        """One device failing evaluation should not abort the whole scan."""
        udm = _make_udm(["dev-a", "dev-b"])
        ready_a = self._build_ps("dev-a", eligible=True)

        def _fake_participation(device_id):
            if device_id == "dev-b":
                raise RuntimeError("per-device crash")
            return ready_a

        with patch("core.device_participation._get_udm", return_value=udm), \
             patch("core.device_participation.get_device_participation",
                   side_effect=_fake_participation):
            result = get_orchestration_ready_devices()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].device_id, "dev-a")

    def test_all_devices_eligible(self):
        udm = _make_udm(["dev-1", "dev-2", "dev-3"])
        ready = {did: self._build_ps(did, eligible=True) for did in ["dev-1", "dev-2", "dev-3"]}

        with patch("core.device_participation._get_udm", return_value=udm), \
             patch("core.device_participation.get_device_participation",
                   side_effect=lambda did: ready[did]):
            result = get_orchestration_ready_devices()

        self.assertEqual(len(result), 3)

    def test_no_devices_eligible(self):
        udm = _make_udm(["dev-x", "dev-y"])
        not_ready = {did: self._build_ps(did, eligible=False) for did in ["dev-x", "dev-y"]}

        with patch("core.device_participation._get_udm", return_value=udm), \
             patch("core.device_participation.get_device_participation",
                   side_effect=lambda did: not_ready[did]):
            result = get_orchestration_ready_devices()

        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# is_device_orchestration_ready
# ---------------------------------------------------------------------------


class TestIsDeviceOrchestrationReady(unittest.TestCase):
    """is_device_orchestration_ready mirrors orchestration_eligible from summary."""

    def _ps(self, eligible: bool) -> ParticipationSummary:
        ps = ParticipationSummary(device_id="d1")
        ps.orchestration_eligible = eligible
        return ps

    def test_true_when_eligible(self):
        with patch(
            "core.device_participation.get_device_participation",
            return_value=self._ps(eligible=True),
        ):
            self.assertTrue(is_device_orchestration_ready("d1"))

    def test_false_when_not_eligible(self):
        with patch(
            "core.device_participation.get_device_participation",
            return_value=self._ps(eligible=False),
        ):
            self.assertFalse(is_device_orchestration_ready("d1"))

    def test_exception_returns_false(self):
        with patch(
            "core.device_participation.get_device_participation",
            side_effect=RuntimeError("crash"),
        ):
            self.assertFalse(is_device_orchestration_ready("d1"))

    def test_empty_device_id_returns_false(self):
        self.assertFalse(is_device_orchestration_ready(""))


# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------


class TestModuleImportable(unittest.TestCase):
    def test_all_public_symbols_importable(self):
        import core.device_participation as dp
        for name in (
            "ParticipationSummary",
            "DEVICE_PARTICIPATION_AUTHORITY",
            "get_device_participation",
            "get_orchestration_ready_devices",
            "is_device_orchestration_ready",
        ):
            self.assertTrue(hasattr(dp, name), f"Missing symbol: {name}")

    def test_get_device_participation_callable(self):
        import core.device_participation as dp
        self.assertTrue(callable(dp.get_device_participation))

    def test_get_orchestration_ready_devices_callable(self):
        import core.device_participation as dp
        self.assertTrue(callable(dp.get_orchestration_ready_devices))

    def test_is_device_orchestration_ready_callable(self):
        import core.device_participation as dp
        self.assertTrue(callable(dp.is_device_orchestration_ready))


if __name__ == "__main__":
    unittest.main()
