"""tests/test_pr8v2_unified_carrier_execution_surface.py
==========================================================

PR-8 V2 — Unified Carrier Execution Surface (R8 closure)
---------------------------------------------------------

Validates that desktop carrier and Android carrier are now projected at
the same semantic level via ``CarrierSurfaceEntry`` / ``UnifiedCarrierSurface``
inside ``core.desktop_existence_surface``, closing the R8 gap identified in
``core.complete_joint_system_review`` (P10 / R8).

Test groups
-----------
Group A — Sentinel and constants: PR8 sentinel present, carrier type
          constants defined, schema version bumped to 1.1.
Group B — CarrierSurfaceEntry: construction, defaults, to_dict().
Group C — UnifiedCarrierSurface: construction, defaults, to_dict(),
          carrier list operations.
Group D — Builder: _build_unified_carrier_surface() derives correct
          desktop carrier entry from family-1/2 snapshots.
Group E — Builder: Android carrier entries built from device snapshots.
Group F — DesktopExistenceSurface: unified_carrier_surface field present,
          to_dict() includes it, schema_version is "1.1".
Group G — ExistenceProjection evidence includes carrier context.
Group H — complete_joint_system_review: P10 probe and R8 closure.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ===========================================================================
# A — Sentinel and constants
# ===========================================================================


class TestSentinelAndConstants(unittest.TestCase):
    """PR8 sentinel and carrier-type constants must be importable and correct."""

    def test_A01_pr8_sentinel_importable(self):
        from core.desktop_existence_surface import PR8_UNIFIED_CARRIER_SURFACE_SENTINEL
        self.assertIsInstance(PR8_UNIFIED_CARRIER_SURFACE_SENTINEL, str)

    def test_A02_pr8_sentinel_contains_pr8_marker(self):
        from core.desktop_existence_surface import PR8_UNIFIED_CARRIER_SURFACE_SENTINEL
        self.assertIn("PR8_V2", PR8_UNIFIED_CARRIER_SURFACE_SENTINEL)

    def test_A03_pr8_sentinel_mentions_unified_carrier_surface(self):
        from core.desktop_existence_surface import PR8_UNIFIED_CARRIER_SURFACE_SENTINEL
        self.assertIn("UnifiedCarrierSurface", PR8_UNIFIED_CARRIER_SURFACE_SENTINEL)

    def test_A04_carrier_type_desktop_is_desktop(self):
        from core.desktop_existence_surface import CARRIER_TYPE_DESKTOP
        self.assertEqual(CARRIER_TYPE_DESKTOP, "desktop")

    def test_A05_carrier_type_android_is_android(self):
        from core.desktop_existence_surface import CARRIER_TYPE_ANDROID
        self.assertEqual(CARRIER_TYPE_ANDROID, "android")

    def test_A06_schema_version_is_1_1(self):
        from core.desktop_existence_surface import EXISTENCE_SURFACE_SCHEMA_VERSION
        self.assertEqual(EXISTENCE_SURFACE_SCHEMA_VERSION, "1.1")

    def test_A07_authority_mentions_unified_carrier(self):
        from core.desktop_existence_surface import DESKTOP_EXISTENCE_SURFACE_AUTHORITY
        self.assertIn("UnifiedCarrierSurface", DESKTOP_EXISTENCE_SURFACE_AUTHORITY)


# ===========================================================================
# B — CarrierSurfaceEntry
# ===========================================================================


class TestCarrierSurfaceEntry(unittest.TestCase):
    """CarrierSurfaceEntry must be constructable with correct defaults."""

    def test_B01_importable(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry
        entry = CarrierSurfaceEntry()
        self.assertIsNotNone(entry)

    def test_B02_default_carrier_type_is_desktop(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry, CARRIER_TYPE_DESKTOP
        entry = CarrierSurfaceEntry()
        self.assertEqual(entry.carrier_type, CARRIER_TYPE_DESKTOP)

    def test_B03_default_carrier_id_is_desktop(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry
        entry = CarrierSurfaceEntry()
        self.assertEqual(entry.carrier_id, "desktop")

    def test_B04_default_execution_surface_state_is_unavailable(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry
        entry = CarrierSurfaceEntry()
        self.assertEqual(entry.execution_surface_state, "unavailable")

    def test_B05_default_is_execution_ready_is_false(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry
        entry = CarrierSurfaceEntry()
        self.assertFalse(entry.is_execution_ready)

    def test_B06_default_carrier_semantic_role_is_primary(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry
        entry = CarrierSurfaceEntry()
        self.assertEqual(entry.carrier_semantic_role, "primary")

    def test_B07_to_dict_has_required_keys(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry
        entry = CarrierSurfaceEntry(
            carrier_type="android",
            carrier_id="device_001",
            execution_surface_state="active",
            is_execution_ready=True,
            carrier_semantic_role="delegated",
        )
        d = entry.to_dict()
        for key in (
            "carrier_type",
            "carrier_id",
            "execution_surface_state",
            "is_execution_ready",
            "carrier_semantic_role",
            "_source",
        ):
            self.assertIn(key, d, f"to_dict() missing key: {key!r}")

    def test_B08_to_dict_values_correct(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry
        entry = CarrierSurfaceEntry(
            carrier_type="android",
            carrier_id="device_001",
            execution_surface_state="ready",
            is_execution_ready=True,
            carrier_semantic_role="delegated",
        )
        d = entry.to_dict()
        self.assertEqual(d["carrier_type"], "android")
        self.assertEqual(d["carrier_id"], "device_001")
        self.assertEqual(d["execution_surface_state"], "ready")
        self.assertTrue(d["is_execution_ready"])
        self.assertEqual(d["carrier_semantic_role"], "delegated")

    def test_B09_android_entry_construction(self):
        from core.desktop_existence_surface import CarrierSurfaceEntry, CARRIER_TYPE_ANDROID
        entry = CarrierSurfaceEntry(
            carrier_type=CARRIER_TYPE_ANDROID,
            carrier_id="dev_abc",
            execution_surface_state="active",
            is_execution_ready=True,
            carrier_semantic_role="delegated",
        )
        self.assertEqual(entry.carrier_type, CARRIER_TYPE_ANDROID)
        self.assertEqual(entry.carrier_id, "dev_abc")
        self.assertTrue(entry.is_execution_ready)


# ===========================================================================
# C — UnifiedCarrierSurface
# ===========================================================================


class TestUnifiedCarrierSurface(unittest.TestCase):
    """UnifiedCarrierSurface must be constructable with correct defaults."""

    def test_C01_importable(self):
        from core.desktop_existence_surface import UnifiedCarrierSurface
        surface = UnifiedCarrierSurface()
        self.assertIsNotNone(surface)

    def test_C02_default_carriers_is_empty_list(self):
        from core.desktop_existence_surface import UnifiedCarrierSurface
        surface = UnifiedCarrierSurface()
        self.assertIsInstance(surface.carriers, list)
        self.assertEqual(len(surface.carriers), 0)

    def test_C03_default_dominant_carrier_type_is_none(self):
        from core.desktop_existence_surface import UnifiedCarrierSurface
        surface = UnifiedCarrierSurface()
        self.assertEqual(surface.dominant_carrier_type, "none")

    def test_C04_default_active_carrier_count_is_zero(self):
        from core.desktop_existence_surface import UnifiedCarrierSurface
        surface = UnifiedCarrierSurface()
        self.assertEqual(surface.active_carrier_count, 0)

    def test_C05_default_execution_ready_carrier_count_is_zero(self):
        from core.desktop_existence_surface import UnifiedCarrierSurface
        surface = UnifiedCarrierSurface()
        self.assertEqual(surface.execution_ready_carrier_count, 0)

    def test_C06_to_dict_has_required_keys(self):
        from core.desktop_existence_surface import UnifiedCarrierSurface
        surface = UnifiedCarrierSurface()
        d = surface.to_dict()
        for key in (
            "carriers",
            "dominant_carrier_type",
            "active_carrier_count",
            "execution_ready_carrier_count",
            "_source",
        ):
            self.assertIn(key, d, f"to_dict() missing key: {key!r}")

    def test_C07_to_dict_carriers_is_list(self):
        from core.desktop_existence_surface import UnifiedCarrierSurface, CarrierSurfaceEntry
        entry = CarrierSurfaceEntry(carrier_type="desktop", carrier_id="desktop",
                                   execution_surface_state="active",
                                   is_execution_ready=True,
                                   carrier_semantic_role="primary")
        surface = UnifiedCarrierSurface(
            carriers=[entry],
            dominant_carrier_type="desktop",
            active_carrier_count=1,
            execution_ready_carrier_count=1,
        )
        d = surface.to_dict()
        self.assertIsInstance(d["carriers"], list)
        self.assertEqual(len(d["carriers"]), 1)
        self.assertEqual(d["carriers"][0]["carrier_type"], "desktop")

    def test_C08_carrier_entries_serialise_correctly(self):
        import json
        from core.desktop_existence_surface import UnifiedCarrierSurface, CarrierSurfaceEntry
        entries = [
            CarrierSurfaceEntry(carrier_type="desktop", carrier_id="desktop",
                               execution_surface_state="ready", is_execution_ready=True,
                               carrier_semantic_role="primary"),
            CarrierSurfaceEntry(carrier_type="android", carrier_id="dev_001",
                               execution_surface_state="active", is_execution_ready=True,
                               carrier_semantic_role="delegated"),
        ]
        surface = UnifiedCarrierSurface(
            carriers=entries,
            dominant_carrier_type="android",
            active_carrier_count=1,
            execution_ready_carrier_count=2,
        )
        raw = json.dumps(surface.to_dict())
        self.assertIsInstance(raw, str)
        d = json.loads(raw)
        self.assertEqual(len(d["carriers"]), 2)


# ===========================================================================
# D — Builder: desktop carrier entry derivation
# ===========================================================================


class TestBuilderDesktopCarrier(unittest.TestCase):
    """Builder._build_unified_carrier_surface() must produce correct desktop
    carrier entries from family-1/2 snapshots."""

    def _make_builder(self):
        from core.desktop_existence_surface import DesktopExistenceSurfaceBuilder
        return DesktopExistenceSurfaceBuilder()

    def _make_fam1(self, tristate: str = "silent", sessions: int = 0):
        from core.desktop_existence_surface import SubjectLifecycleSnapshot
        return SubjectLifecycleSnapshot(dominant_tristate=tristate,
                                       active_session_count=sessions)

    def _make_fam2(self, shell: str = "dormant"):
        from core.desktop_existence_surface import ShellClothingSnapshot
        return ShellClothingSnapshot(shell_state=shell)

    def test_D01_silent_dormant_yields_unavailable_desktop_carrier(self):
        builder = self._make_builder()
        with patch("core.android_device_state_store.list_device_state_snapshots", return_value=[]):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1("silent", 0), self._make_fam2("dormant")
            )
        self.assertEqual(len(surface.carriers), 1)
        desktop = surface.carriers[0]
        self.assertEqual(desktop.carrier_type, "desktop")
        self.assertEqual(desktop.execution_surface_state, "unavailable")
        self.assertFalse(desktop.is_execution_ready)

    def test_D02_manifest_yields_active_desktop_carrier(self):
        builder = self._make_builder()
        with patch("core.android_device_state_store.list_device_state_snapshots", return_value=[]):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1("manifest", 1), self._make_fam2("fullagent")
            )
        desktop = surface.carriers[0]
        self.assertEqual(desktop.execution_surface_state, "active")
        self.assertTrue(desktop.is_execution_ready)

    def test_D03_liminal_yields_ready_desktop_carrier(self):
        builder = self._make_builder()
        with patch("core.android_device_state_store.list_device_state_snapshots", return_value=[]):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1("liminal", 1), self._make_fam2("sidesheet")
            )
        desktop = surface.carriers[0]
        self.assertEqual(desktop.execution_surface_state, "ready")
        self.assertTrue(desktop.is_execution_ready)

    def test_D04_desktop_carrier_role_is_primary(self):
        builder = self._make_builder()
        with patch("core.android_device_state_store.list_device_state_snapshots", return_value=[]):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1("manifest"), self._make_fam2("fullagent")
            )
        desktop = surface.carriers[0]
        self.assertEqual(desktop.carrier_semantic_role, "primary")
        self.assertEqual(desktop.carrier_id, "desktop")
        self.assertEqual(desktop.carrier_type, "desktop")

    def test_D05_dominant_carrier_type_is_desktop_when_only_desktop_active(self):
        builder = self._make_builder()
        with patch("core.android_device_state_store.list_device_state_snapshots", return_value=[]):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1("manifest"), self._make_fam2("fullagent")
            )
        self.assertEqual(surface.dominant_carrier_type, "desktop")
        self.assertEqual(surface.active_carrier_count, 1)

    def test_D06_android_read_failure_still_returns_desktop_entry(self):
        """If Android device_state_store is unavailable, the surface still contains
        the desktop carrier entry (graceful degradation)."""
        builder = self._make_builder()
        with patch(
            "core.android_device_state_store.list_device_state_snapshots",
            side_effect=RuntimeError("store unavailable"),
        ):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1("manifest"), self._make_fam2("fullagent")
            )
        self.assertEqual(len(surface.carriers), 1)
        self.assertEqual(surface.carriers[0].carrier_type, "desktop")


# ===========================================================================
# E — Builder: Android carrier entries
# ===========================================================================


class TestBuilderAndroidCarriers(unittest.TestCase):
    """Builder must add one CarrierSurfaceEntry per Android device snapshot."""

    def _make_builder(self):
        from core.desktop_existence_surface import DesktopExistenceSurfaceBuilder
        return DesktopExistenceSurfaceBuilder()

    def _make_snap(self, device_id: str, local_loop: bool, model_ready: bool) -> MagicMock:
        snap = MagicMock()
        snap.device_id = device_id
        snap.local_loop_ready = local_loop
        snap.model_ready = model_ready
        return snap

    def _make_fam1(self, tristate: str = "silent"):
        from core.desktop_existence_surface import SubjectLifecycleSnapshot
        return SubjectLifecycleSnapshot(dominant_tristate=tristate)

    def _make_fam2(self, shell: str = "dormant"):
        from core.desktop_existence_surface import ShellClothingSnapshot
        return ShellClothingSnapshot(shell_state=shell)

    def test_E01_one_android_device_adds_one_android_entry(self):
        builder = self._make_builder()
        snaps = [self._make_snap("dev_001", True, True)]
        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=snaps):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1(), self._make_fam2()
            )
        android_entries = [c for c in surface.carriers if c.carrier_type == "android"]
        self.assertEqual(len(android_entries), 1)
        self.assertEqual(android_entries[0].carrier_id, "dev_001")

    def test_E02_fully_ready_android_device_is_active(self):
        builder = self._make_builder()
        snaps = [self._make_snap("dev_001", True, True)]
        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=snaps):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1(), self._make_fam2()
            )
        android_entries = [c for c in surface.carriers if c.carrier_type == "android"]
        self.assertEqual(android_entries[0].execution_surface_state, "active")
        self.assertTrue(android_entries[0].is_execution_ready)

    def test_E03_model_ready_only_android_device_is_ready(self):
        builder = self._make_builder()
        snaps = [self._make_snap("dev_002", False, True)]
        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=snaps):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1(), self._make_fam2()
            )
        android_entries = [c for c in surface.carriers if c.carrier_type == "android"]
        self.assertEqual(android_entries[0].execution_surface_state, "ready")
        self.assertTrue(android_entries[0].is_execution_ready)

    def test_E04_not_ready_android_device_is_unavailable(self):
        builder = self._make_builder()
        snaps = [self._make_snap("dev_003", False, False)]
        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=snaps):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1(), self._make_fam2()
            )
        android_entries = [c for c in surface.carriers if c.carrier_type == "android"]
        self.assertEqual(android_entries[0].execution_surface_state, "unavailable")
        self.assertFalse(android_entries[0].is_execution_ready)

    def test_E05_android_carrier_semantic_role_is_delegated(self):
        builder = self._make_builder()
        snaps = [self._make_snap("dev_001", True, True)]
        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=snaps):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1(), self._make_fam2()
            )
        android_entries = [c for c in surface.carriers if c.carrier_type == "android"]
        self.assertEqual(android_entries[0].carrier_semantic_role, "delegated")

    def test_E06_two_android_devices_add_two_android_entries(self):
        builder = self._make_builder()
        snaps = [
            self._make_snap("dev_001", True, True),
            self._make_snap("dev_002", False, True),
        ]
        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=snaps):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1(), self._make_fam2()
            )
        android_entries = [c for c in surface.carriers if c.carrier_type == "android"]
        self.assertEqual(len(android_entries), 2)

    def test_E07_active_android_device_wins_dominant_carrier(self):
        """When an Android device is active but desktop is not, dominant = android."""
        builder = self._make_builder()
        snaps = [self._make_snap("dev_001", True, True)]
        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=snaps):
            surface = builder._build_unified_carrier_surface(
                self._make_fam1("silent"), self._make_fam2("dormant")
            )
        self.assertEqual(surface.dominant_carrier_type, "android")

    def test_E08_active_carrier_count_reflects_all_active_carriers(self):
        """active_carrier_count includes both desktop and android active carriers."""
        from core.desktop_existence_surface import SubjectLifecycleSnapshot, ShellClothingSnapshot
        builder = self._make_builder()
        snaps = [self._make_snap("dev_001", True, True)]
        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=snaps):
            surface = builder._build_unified_carrier_surface(
                SubjectLifecycleSnapshot(dominant_tristate="manifest"),
                ShellClothingSnapshot(shell_state="fullagent"),
            )
        self.assertGreaterEqual(surface.active_carrier_count, 2)


# ===========================================================================
# F — DesktopExistenceSurface: unified_carrier_surface field
# ===========================================================================


class TestDesktopExistenceSurfaceCarrierField(unittest.TestCase):
    """DesktopExistenceSurface must include unified_carrier_surface field."""

    def test_F01_default_instance_has_unified_carrier_surface(self):
        from core.desktop_existence_surface import DesktopExistenceSurface, UnifiedCarrierSurface
        s = DesktopExistenceSurface()
        self.assertIsInstance(s.unified_carrier_surface, UnifiedCarrierSurface)

    def test_F02_to_dict_includes_unified_carrier_surface_key(self):
        from core.desktop_existence_surface import DesktopExistenceSurface
        s = DesktopExistenceSurface()
        d = s.to_dict()
        self.assertIn("unified_carrier_surface", d)

    def test_F03_to_dict_unified_carrier_surface_has_carriers(self):
        from core.desktop_existence_surface import DesktopExistenceSurface
        s = DesktopExistenceSurface()
        d = s.to_dict()
        self.assertIn("carriers", d["unified_carrier_surface"])

    def test_F04_schema_version_is_1_1(self):
        from core.desktop_existence_surface import DesktopExistenceSurface
        s = DesktopExistenceSurface()
        self.assertEqual(s.schema_version, "1.1")
        self.assertEqual(s.to_dict()["schema_version"], "1.1")

    def test_F05_build_desktop_existence_surface_includes_carrier_surface(self):
        from core.desktop_existence_surface import (
            build_desktop_existence_surface,
            reset_desktop_existence_surface_builder,
            UnifiedCarrierSurface,
        )
        reset_desktop_existence_surface_builder()
        surface = build_desktop_existence_surface()
        self.assertIsInstance(surface.unified_carrier_surface, UnifiedCarrierSurface)
        reset_desktop_existence_surface_builder()

    def test_F06_built_surface_carrier_surface_has_at_least_desktop_entry(self):
        """build_desktop_existence_surface() must always include at least the desktop carrier."""
        from core.desktop_existence_surface import (
            build_desktop_existence_surface,
            reset_desktop_existence_surface_builder,
            CARRIER_TYPE_DESKTOP,
        )
        reset_desktop_existence_surface_builder()
        surface = build_desktop_existence_surface()
        carriers = surface.unified_carrier_surface.carriers
        desktop_carriers = [c for c in carriers if c.carrier_type == CARRIER_TYPE_DESKTOP]
        self.assertGreaterEqual(len(desktop_carriers), 1,
                                "Expected at least one desktop carrier entry")
        reset_desktop_existence_surface_builder()

    def test_F07_to_dict_is_json_serialisable_with_carrier_surface(self):
        import json
        from core.desktop_existence_surface import (
            build_desktop_existence_surface,
            reset_desktop_existence_surface_builder,
        )
        reset_desktop_existence_surface_builder()
        surface = build_desktop_existence_surface()
        raw = json.dumps(surface.to_dict())
        self.assertIsInstance(raw, str)
        d = json.loads(raw)
        self.assertIn("unified_carrier_surface", d)
        reset_desktop_existence_surface_builder()


# ===========================================================================
# G — ExistenceProjection evidence includes carrier context
# ===========================================================================


class TestExistenceProjectionCarrierEvidence(unittest.TestCase):
    """ExistenceProjection evidence must include carrier context when carrier
    surface is provided."""

    def _build_surface_with_manifest_tristate(self):
        """Build a surface stub with manifest tri-state and a mock Android device."""
        from core.desktop_existence_surface import (
            DesktopExistenceSurfaceBuilder,
            SubjectLifecycleSnapshot,
            ShellClothingSnapshot,
            ContinuumPostureSnapshot,
            CognitiveFieldSnapshot,
            AndroidPresenceSignals,
        )
        builder = DesktopExistenceSurfaceBuilder()

        snap = MagicMock()
        snap.device_id = "test_dev"
        snap.local_loop_ready = True
        snap.model_ready = True

        with patch("core.android_device_state_store.list_device_state_snapshots",
                   return_value=[snap]):
            fam1 = SubjectLifecycleSnapshot(dominant_tristate="manifest",
                                            active_session_count=1)
            fam2 = ShellClothingSnapshot(shell_state="fullagent")
            fam3 = ContinuumPostureSnapshot(tri_state_phase="manifest")
            fam4 = CognitiveFieldSnapshot(activation=0.9, is_running=True)
            fam5 = AndroidPresenceSignals(total_devices_with_snapshot=1,
                                          local_loop_ready_count=1)
            carrier_surface = builder._build_unified_carrier_surface(fam1, fam2)
            proj = builder._derive_existence_projection(fam1, fam2, fam3, fam4, fam5,
                                                        carrier_surface)
        return proj, carrier_surface

    def test_G01_projection_evidence_has_carrier_context(self):
        proj, _ = self._build_surface_with_manifest_tristate()
        self.assertIn("dominant_carrier_type", proj.evidence)

    def test_G02_projection_evidence_has_carrier_active_count(self):
        proj, _ = self._build_surface_with_manifest_tristate()
        self.assertIn("carrier_active_count", proj.evidence)

    def test_G03_projection_evidence_has_carrier_ready_count(self):
        proj, _ = self._build_surface_with_manifest_tristate()
        self.assertIn("carrier_ready_count", proj.evidence)

    def test_G04_projection_evidence_carrier_active_count_is_non_negative(self):
        proj, carrier_surface = self._build_surface_with_manifest_tristate()
        self.assertGreaterEqual(proj.evidence.get("carrier_active_count", -1), 0)

    def test_G05_projection_without_carrier_surface_still_works(self):
        """_derive_existence_projection without carrier_surface arg must not raise."""
        from core.desktop_existence_surface import (
            DesktopExistenceSurfaceBuilder,
            SubjectLifecycleSnapshot,
            ShellClothingSnapshot,
            ContinuumPostureSnapshot,
            CognitiveFieldSnapshot,
            AndroidPresenceSignals,
        )
        builder = DesktopExistenceSurfaceBuilder()
        proj = builder._derive_existence_projection(
            SubjectLifecycleSnapshot(),
            ShellClothingSnapshot(),
            ContinuumPostureSnapshot(),
            CognitiveFieldSnapshot(),
            AndroidPresenceSignals(),
        )
        self.assertIsNotNone(proj)
        self.assertIn(proj.presence_verdict, ("dormant", "background", "active", "expressing"))


# ===========================================================================
# H — complete_joint_system_review P10 / R8 closure
# ===========================================================================


class TestCompleteJointSystemReviewR8Closure(unittest.TestCase):
    """complete_joint_system_review must report P10 HARD_ESTABLISHED and
    R8 evidence HARD_ESTABLISHED when UnifiedCarrierSurface is present."""

    def test_H01_module_importable(self):
        import importlib
        mod = importlib.import_module("core.complete_joint_system_review")
        self.assertIsNotNone(mod)

    def test_H02_build_review_returns_result(self):
        from core.complete_joint_system_review import build_complete_joint_system_review
        report = build_complete_joint_system_review()
        self.assertIsNotNone(report)

    def test_H03_p10_verdict_is_hard_established(self):
        """P10 must be HARD_ESTABLISHED because UnifiedCarrierSurface is now present."""
        from core.complete_joint_system_review import (
            build_complete_joint_system_review,
            PropositionVerdict,
        )
        report = build_complete_joint_system_review()
        p10 = next((p for p in report.propositions if p.prop_id == "P10"), None)
        self.assertIsNotNone(p10, "P10 proposition must be present in the report")
        self.assertEqual(
            p10.verdict,
            PropositionVerdict.HARD_ESTABLISHED,
            f"P10 expected HARD_ESTABLISHED, got {p10.verdict!r}. "
            "UnifiedCarrierSurface must be present in core.desktop_existence_surface.",
        )

    def test_H04_p10_open_gap_ids_does_not_contain_r8(self):
        """Once UnifiedCarrierSurface is present, P10 must no longer list R8 as open."""
        from core.complete_joint_system_review import build_complete_joint_system_review
        report = build_complete_joint_system_review()
        p10 = next((p for p in report.propositions if p.prop_id == "P10"), None)
        self.assertIsNotNone(p10)
        self.assertNotIn(
            "R8",
            p10.open_gap_ids,
            "P10 must not list R8 as open once UnifiedCarrierSurface is present.",
        )

    def test_H05_r8_remaining_issue_has_hard_established_evidence(self):
        """R8 remaining issue evidence_state must be HARD_ESTABLISHED."""
        from core.complete_joint_system_review import (
            build_complete_joint_system_review,
            EvidenceState,
        )
        report = build_complete_joint_system_review()
        r8 = next(
            (ri for ri in report.remaining_issues if ri.issue_id == "R8"), None
        )
        self.assertIsNotNone(r8, "R8 must be present in remaining_issues")
        self.assertEqual(
            r8.evidence_state,
            EvidenceState.HARD_ESTABLISHED,
            f"R8 evidence_state expected HARD_ESTABLISHED, got {r8.evidence_state!r}.",
        )


if __name__ == "__main__":
    unittest.main()
