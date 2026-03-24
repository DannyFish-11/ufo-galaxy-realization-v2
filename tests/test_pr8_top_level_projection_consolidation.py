"""tests/test_pr8_top_level_projection_consolidation.py
==========================================================
PR-8 — Top-level multi-device runtime projection consolidation tests.

Coverage:
  1.  CANONICAL_TOP_LEVEL_PROJECTION sentinel is True.
  2.  __canonical_authority__ string is present and non-empty.
  3.  MultiDeviceRuntimeProjection is importable as canonical top-level model.
  4.  from_registered_runtime_device builds entry from RegisteredRuntimeDevice dict.
  5.  from_registered_runtime_device builds entry from RegisteredRuntimeDevice object.
  6.  from_registered_runtime_device extracts device_id correctly.
  7.  from_registered_runtime_device extracts platform correctly.
  8.  from_registered_runtime_device extracts form_factor correctly.
  9.  from_registered_runtime_device extracts status correctly.
  10. from_registered_runtime_device extracts connection_state from flat field.
  11. from_registered_runtime_device extracts connection_state from connection sub-dict.
  12. from_registered_runtime_device extracts health_score correctly.
  13. from_registered_runtime_device sets runtime_capable True by default.
  14. from_registered_runtime_device respects explicit runtime_capable=False.
  15. from_registered_runtime_device raises ValueError on None input.
  16. from_registered_runtime_device raises ValueError on empty dict.
  17. from_registered_runtime_device propagates metadata.
  18. from_registered_runtime_device returns RuntimeProjectionDeviceEntry instance.
  19. project_runtime_devices uses canonical entries from RegisteredRuntimeDevice dicts.
  20. project_runtime_devices handles mixed valid/invalid items gracefully.
  21. build_multi_device_runtime_projection assembles canonical device entries.
  22. build_multi_device_runtime_projection device entries have correct device_ids.
  23. build_multi_device_runtime_projection with RegisteredRuntimeDevice objects.
  24. Full multi-device projection round-trip with canonical devices.
  25. projection_from_registered_runtime_device exported from contracts package.
  26. CANONICAL_TOP_LEVEL_PROJECTION exported from contracts package.
  27. Anti-drift: _AntiDriftVisitor detects parallel single-device schema.
  28. Anti-drift: _AntiDriftVisitor detects parallel multi-device projection.
  29. Anti-drift: _AntiDriftVisitor detects parallel device registry field.
  30. Anti-drift: _AntiDriftVisitor passes clean class.
  31. Anti-drift: _is_anti_drift_allowed allows canonical contract files.
  32. Anti-drift: _is_anti_drift_allowed allows test files.
  33. Anti-drift: _is_anti_drift_allowed rejects unknown files.
  34. Anti-drift: _check_anti_drift returns empty list for empty file list.
  35. Anti-drift: _check_anti_drift detects RuntimeDevice pattern in synthetic source.
  36. Anti-drift: _check_anti_drift detects MultiDeviceProjection pattern in synthetic source.
  37. Anti-drift: AuditResult has anti_drift_findings field.
  38. Anti-drift: AuditResult.to_dict includes anti_drift_findings key.
  39. End-to-end: registration → canonical single-device projection.
  40. End-to-end: canonical single-device projection → top-level multi-device projection.
  41. End-to-end: top-level projection device_id matches registration device_id.
  42. End-to-end: top-level projection platform matches registration platform.
  43. End-to-end: top-level projection status matches registration status.
  44. End-to-end: projection_id is unique per build call.
  45. End-to-end: generated_at is populated (non-zero).
  46. End-to-end: to_dict/from_dict round-trip preserves device entry count.
  47. End-to-end: to_dict/from_dict round-trip preserves device_ids.
  48. End-to-end: full flow with multiple devices.
  49. End-to-end: health_score propagated through full flow.
  50. End-to-end: metadata propagated through full flow.
"""

from __future__ import annotations

import ast
import json
import tempfile
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rrd_dict(
    device_id: str = "dev_001",
    platform: str = "android",
    form_factor: str = "phone",
    status: str = "online",
    connection_state: str = "connected",
    runtime_capable: bool = True,
    health_score: float = 0.9,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a dict matching RegisteredRuntimeDevice field names."""
    return {
        "device_id": device_id,
        "platform": platform,
        "form_factor": form_factor,
        "status": status,
        "connection_state": connection_state,
        "runtime_capable": runtime_capable,
        "health_score": health_score,
        "metadata": metadata or {},
    }


def _make_rrd_with_connection_summary(
    device_id: str = "dev_cs_001",
    state: str = "connected",
) -> Dict[str, Any]:
    """Build a dict with connection as a sub-dict (canonical connection_summary pattern)."""
    return {
        "device_id": device_id,
        "platform": "windows",
        "connection": {"state": state, "protocol": "websocket"},
    }


# ---------------------------------------------------------------------------
# 1–2: Module-level canonical markers
# ---------------------------------------------------------------------------


class TestCanonicalMarkers:
    """CANONICAL_TOP_LEVEL_PROJECTION and __canonical_authority__ are present."""

    def test_canonical_top_level_projection_sentinel(self):
        from contracts.multi_device_runtime_projection import CANONICAL_TOP_LEVEL_PROJECTION
        assert CANONICAL_TOP_LEVEL_PROJECTION is True

    def test_canonical_authority_string_present(self):
        from contracts.multi_device_runtime_projection import __canonical_authority__
        assert isinstance(__canonical_authority__, str)
        assert len(__canonical_authority__) > 20
        assert "MultiDeviceRuntimeProjection" in __canonical_authority__

    def test_module_is_importable(self):
        import contracts.multi_device_runtime_projection as m
        assert hasattr(m, "MultiDeviceRuntimeProjection")

    def test_canonical_top_level_projection_exported_from_contracts(self):
        from contracts import CANONICAL_TOP_LEVEL_PROJECTION
        assert CANONICAL_TOP_LEVEL_PROJECTION is True


# ---------------------------------------------------------------------------
# 4–18: from_registered_runtime_device
# ---------------------------------------------------------------------------


class TestFromRegisteredRuntimeDevice:
    """from_registered_runtime_device builds canonical device entries."""

    def _adapter(self):
        from contracts.multi_device_runtime_projection import from_registered_runtime_device
        return from_registered_runtime_device

    def test_builds_from_dict(self):
        adapter = self._adapter()
        d = _make_rrd_dict()
        entry = adapter(d)
        assert entry.device_id == "dev_001"

    def test_builds_from_pydantic_object(self):
        adapter = self._adapter()
        from contracts.registered_runtime_device import build_registered_runtime_device
        obj = build_registered_runtime_device(
            device_id="rrd_test_obj",
            platform="android",
            status="online",
        )
        entry = adapter(obj)
        assert entry.device_id == "rrd_test_obj"

    def test_extracts_device_id(self):
        adapter = self._adapter()
        entry = adapter(_make_rrd_dict(device_id="my_device_xyz"))
        assert entry.device_id == "my_device_xyz"

    def test_extracts_platform(self):
        adapter = self._adapter()
        entry = adapter(_make_rrd_dict(platform="ios"))
        assert entry.platform == "ios"

    def test_extracts_form_factor(self):
        adapter = self._adapter()
        entry = adapter(_make_rrd_dict(form_factor="tablet"))
        assert entry.form_factor == "tablet"

    def test_extracts_status(self):
        adapter = self._adapter()
        entry = adapter(_make_rrd_dict(status="offline"))
        assert entry.status == "offline"

    def test_extracts_connection_state_flat(self):
        adapter = self._adapter()
        entry = adapter(_make_rrd_dict(connection_state="disconnected"))
        assert entry.connection_state == "disconnected"

    def test_extracts_connection_state_from_sub_dict(self):
        adapter = self._adapter()
        d = _make_rrd_with_connection_summary(state="reconnecting")
        entry = adapter(d)
        assert entry.connection_state == "reconnecting"

    def test_extracts_health_score(self):
        adapter = self._adapter()
        entry = adapter(_make_rrd_dict(health_score=0.75))
        assert entry.health_score == pytest.approx(0.75)

    def test_runtime_capable_default_true(self):
        adapter = self._adapter()
        d = {"device_id": "dev_rc_default"}
        entry = adapter(d)
        assert entry.runtime_capable is True

    def test_runtime_capable_false_explicit(self):
        adapter = self._adapter()
        entry = adapter(_make_rrd_dict(runtime_capable=False))
        assert entry.runtime_capable is False

    def test_raises_on_none(self):
        adapter = self._adapter()
        with pytest.raises(ValueError):
            adapter(None)

    def test_raises_on_empty_dict(self):
        adapter = self._adapter()
        with pytest.raises(ValueError):
            adapter({})

    def test_propagates_metadata(self):
        adapter = self._adapter()
        entry = adapter(_make_rrd_dict(metadata={"env": "prod", "region": "us-east-1"}))
        assert entry.metadata.get("env") == "prod"
        assert entry.metadata.get("region") == "us-east-1"

    def test_returns_runtime_projection_device_entry(self):
        from contracts.multi_device_runtime_projection import (
            RuntimeProjectionDeviceEntry,
            from_registered_runtime_device,
        )
        entry = from_registered_runtime_device(_make_rrd_dict())
        assert isinstance(entry, RuntimeProjectionDeviceEntry)


# ---------------------------------------------------------------------------
# 19–25: Projection assembly with canonical entries
# ---------------------------------------------------------------------------


class TestProjectionAssemblyWithCanonicalDevices:
    """build_multi_device_runtime_projection assembles canonical device entries."""

    def test_project_runtime_devices_returns_canonical_entries(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices
        devices = [
            _make_rrd_dict(device_id="d1"),
            _make_rrd_dict(device_id="d2"),
        ]
        entries = project_runtime_devices(devices)
        assert len(entries) == 2
        ids = {e.device_id for e in entries}
        assert ids == {"d1", "d2"}

    def test_project_runtime_devices_handles_bad_items(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices
        devices = [
            _make_rrd_dict(device_id="good_1"),
            None,
            42,
            _make_rrd_dict(device_id="good_2"),
        ]
        entries = project_runtime_devices(devices)
        # Bad items are skipped; at least the good ones are present
        ids = {e.device_id for e in entries}
        assert "good_1" in ids
        assert "good_2" in ids

    def test_build_projection_assembles_device_entries(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        devices = [
            _make_rrd_dict(device_id="phone_001"),
            _make_rrd_dict(device_id="tablet_002", form_factor="tablet"),
        ]
        proj = build_multi_device_runtime_projection(runtime_devices=devices)
        assert len(proj.runtime_devices) == 2

    def test_build_projection_device_ids_correct(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        devices = [_make_rrd_dict(device_id="phone_A"), _make_rrd_dict(device_id="desktop_B")]
        proj = build_multi_device_runtime_projection(runtime_devices=devices)
        ids = {e.device_id for e in proj.runtime_devices}
        assert ids == {"phone_A", "desktop_B"}

    def test_build_projection_with_rrd_objects(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        from contracts.registered_runtime_device import build_registered_runtime_device
        rrd = build_registered_runtime_device(
            device_id="obj_dev_001",
            platform="windows",
            status="online",
        )
        proj = build_multi_device_runtime_projection(runtime_devices=[rrd])
        assert len(proj.runtime_devices) == 1
        assert proj.runtime_devices[0].device_id == "obj_dev_001"

    def test_full_round_trip_with_canonical_devices(self):
        from contracts.multi_device_runtime_projection import (
            MultiDeviceRuntimeProjection,
            build_multi_device_runtime_projection,
        )
        devices = [_make_rrd_dict(device_id="rt_dev_001")]
        proj = build_multi_device_runtime_projection(runtime_devices=devices)
        d = proj.to_dict()
        proj2 = MultiDeviceRuntimeProjection.from_dict(d)
        assert len(proj2.runtime_devices) == 1
        assert proj2.runtime_devices[0].device_id == "rt_dev_001"

    def test_projection_from_registered_runtime_device_exported_from_contracts(self):
        from contracts import projection_from_registered_runtime_device
        assert callable(projection_from_registered_runtime_device)
        entry = projection_from_registered_runtime_device(_make_rrd_dict(device_id="exp_dev"))
        assert entry.device_id == "exp_dev"


# ---------------------------------------------------------------------------
# 27–38: Anti-drift guards
# ---------------------------------------------------------------------------


class TestAntiDriftVisitor:
    """_AntiDriftVisitor detects and ignores the right patterns."""

    def _visitor(self, source: str):
        from scripts.audit_udm_write_paths import _AntiDriftVisitor
        tree = ast.parse(source)
        lines = source.splitlines()
        v = _AntiDriftVisitor(lines)
        v.visit(tree)
        return v.findings

    def test_detects_parallel_single_device_schema(self):
        source = textwrap.dedent("""\
            class MyRuntimeDevice:
                device_id: str = ""
        """)
        findings = self._visitor(source)
        kinds = [f[1] for f in findings]
        assert "parallel_single_device_schema" in kinds

    def test_detects_parallel_multi_device_projection(self):
        source = textwrap.dedent("""\
            class AllDevicesMultiDeviceProjection:
                devices: list = []
        """)
        findings = self._visitor(source)
        kinds = [f[1] for f in findings]
        assert "parallel_multi_device_projection" in kinds

    def test_detects_parallel_device_registry_field(self):
        source = textwrap.dedent("""\
            class SomeManager:
                _devices: dict
        """)
        findings = self._visitor(source)
        kinds = [f[1] for f in findings]
        assert "parallel_device_registry" in kinds

    def test_clean_class_produces_no_findings(self):
        source = textwrap.dedent("""\
            class UserSession:
                session_id: str = ""
                user: str = ""
        """)
        findings = self._visitor(source)
        assert findings == []

    def test_clean_handler_class_no_findings(self):
        source = textwrap.dedent("""\
            class MessageHandler:
                def handle(self, msg):
                    pass
        """)
        findings = self._visitor(source)
        assert findings == []


class TestAntiDriftAllowList:
    """_is_anti_drift_allowed respects the allow list."""

    def _allowed(self, path: str) -> bool:
        from scripts.audit_udm_write_paths import _is_anti_drift_allowed
        return _is_anti_drift_allowed(path)

    def test_canonical_single_device_contract_allowed(self):
        assert self._allowed("contracts/registered_runtime_device.py") is True

    def test_canonical_multi_device_projection_allowed(self):
        assert self._allowed("contracts/multi_device_runtime_projection.py") is True

    def test_udm_device_manager_allowed(self):
        assert self._allowed("core/unified/device_manager.py") is True

    def test_test_files_allowed(self):
        assert self._allowed("tests/test_something.py") is True

    def test_scripts_allowed(self):
        assert self._allowed("scripts/some_script.py") is True

    def test_unknown_file_not_allowed(self):
        assert self._allowed("some_random_module.py") is False

    def test_galaxy_gateway_not_allowed(self):
        assert self._allowed("galaxy_gateway/device_router.py") is False


class TestCheckAntiDrift:
    """_check_anti_drift function works on synthetic files."""

    def test_empty_file_list_returns_empty(self):
        from scripts.audit_udm_write_paths import _check_anti_drift
        findings = _check_anti_drift(Path("/nonexistent"), py_files=[])
        assert findings == []

    def test_detects_runtime_device_in_synthetic_file(self):
        from scripts.audit_udm_write_paths import _check_anti_drift
        source = textwrap.dedent("""\
            class NewRuntimeDevice:
                device_id: str = ""
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "some_module.py"
            fpath.write_text(source, encoding="utf-8")
            findings = _check_anti_drift(Path(tmpdir), py_files=[fpath])
        kinds = [f["kind"] for f in findings]
        assert "parallel_single_device_schema" in kinds

    def test_detects_multi_device_projection_in_synthetic_file(self):
        from scripts.audit_udm_write_paths import _check_anti_drift
        source = textwrap.dedent("""\
            class MyMultiDeviceProjection:
                runtime_devices: list = []
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "parallel_proj.py"
            fpath.write_text(source, encoding="utf-8")
            findings = _check_anti_drift(Path(tmpdir), py_files=[fpath])
        kinds = [f["kind"] for f in findings]
        assert "parallel_multi_device_projection" in kinds


class TestAuditResultAntiDrift:
    """AuditResult correctly stores anti_drift_findings."""

    def test_audit_result_has_anti_drift_field(self):
        from scripts.audit_udm_write_paths import AuditResult
        result = AuditResult()
        assert hasattr(result, "anti_drift_findings")
        assert isinstance(result.anti_drift_findings, list)

    def test_audit_result_to_dict_includes_anti_drift_key(self):
        from scripts.audit_udm_write_paths import AuditResult
        result = AuditResult(anti_drift_findings=[{"kind": "test", "file": "x.py", "line": 1, "detail": "d"}])
        d = result.to_dict()
        assert "anti_drift_findings" in d
        assert len(d["anti_drift_findings"]) == 1


# ---------------------------------------------------------------------------
# 39–50: End-to-end unified device flow
# ---------------------------------------------------------------------------


class TestEndToEndUnifiedDeviceFlow:
    """End-to-end: registration → canonical single-device projection → top-level projection."""

    def _register_and_project(
        self,
        device_id: str = "e2e_dev_001",
        platform: str = "android",
        form_factor: str = "phone",
        status: str = "online",
        health_score: float = 0.8,
    ):
        """Simulate registration → single-device projection → top-level projection."""
        from contracts.registered_runtime_device import build_registered_runtime_device
        from contracts.multi_device_runtime_projection import (
            build_multi_device_runtime_projection,
            from_registered_runtime_device,
        )
        # Step 1: registration → canonical single-device projection
        rrd = build_registered_runtime_device(
            device_id=device_id,
            platform=platform,
            form_factor=form_factor,
            status=status,
        )
        # Step 2: single-device projection → canonical device entry (PR-8 adapter)
        entry = from_registered_runtime_device(rrd)
        # Step 3: device entry → top-level multi-device projection
        proj = build_multi_device_runtime_projection(runtime_devices=[rrd])
        return rrd, entry, proj

    def test_registration_produces_rrd(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        rrd = build_registered_runtime_device(device_id="e2e_basic", platform="android")
        assert rrd.device_id == "e2e_basic"

    def test_canonical_single_device_projection_device_id(self):
        _, entry, _ = self._register_and_project(device_id="e2e_id_check")
        assert entry.device_id == "e2e_id_check"

    def test_top_level_projection_contains_device(self):
        _, _, proj = self._register_and_project(device_id="e2e_proj_dev")
        ids = {e.device_id for e in proj.runtime_devices}
        assert "e2e_proj_dev" in ids

    def test_top_level_projection_platform_matches(self):
        _, _, proj = self._register_and_project(device_id="e2e_plat", platform="ios")
        assert proj.runtime_devices[0].platform == "ios"

    def test_top_level_projection_status_matches(self):
        _, _, proj = self._register_and_project(device_id="e2e_stat", status="offline")
        assert proj.runtime_devices[0].status == "offline"

    def test_projection_id_unique_per_build(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        p1 = build_multi_device_runtime_projection()
        p2 = build_multi_device_runtime_projection()
        assert p1.projection_id != p2.projection_id

    def test_generated_at_is_populated(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        proj = build_multi_device_runtime_projection()
        assert proj.generated_at > 0

    def test_round_trip_preserves_device_count(self):
        from contracts.multi_device_runtime_projection import (
            MultiDeviceRuntimeProjection,
            build_multi_device_runtime_projection,
        )
        from contracts.registered_runtime_device import build_registered_runtime_device
        devices = [
            build_registered_runtime_device(device_id=f"rt_{i}", platform="android")
            for i in range(3)
        ]
        proj = build_multi_device_runtime_projection(runtime_devices=devices)
        d = proj.to_dict()
        proj2 = MultiDeviceRuntimeProjection.from_dict(d)
        assert len(proj2.runtime_devices) == 3

    def test_round_trip_preserves_device_ids(self):
        from contracts.multi_device_runtime_projection import (
            MultiDeviceRuntimeProjection,
            build_multi_device_runtime_projection,
        )
        from contracts.registered_runtime_device import build_registered_runtime_device
        ids_in = ["alpha", "beta", "gamma"]
        devices = [build_registered_runtime_device(device_id=did) for did in ids_in]
        proj = build_multi_device_runtime_projection(runtime_devices=devices)
        d = proj.to_dict()
        proj2 = MultiDeviceRuntimeProjection.from_dict(d)
        ids_out = {e.device_id for e in proj2.runtime_devices}
        assert set(ids_in) == ids_out

    def test_full_flow_multiple_devices(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        devices = [
            build_registered_runtime_device(device_id="phone_01", platform="android", status="online"),
            build_registered_runtime_device(device_id="tablet_02", platform="ios", status="online"),
            build_registered_runtime_device(device_id="desktop_03", platform="windows", status="offline"),
        ]
        proj = build_multi_device_runtime_projection(runtime_devices=devices)
        assert len(proj.runtime_devices) == 3
        statuses = {e.device_id: e.status for e in proj.runtime_devices}
        assert statuses["desktop_03"] == "offline"

    def test_health_score_propagated(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        # health_score is a first-class field on RuntimeProjectionDeviceEntry
        # and is passed via a compatible dict (health_score comes from device data)
        device_dict = _make_rrd_dict(device_id="e2e_hs", health_score=0.42)
        proj = build_multi_device_runtime_projection(runtime_devices=[device_dict])
        assert proj.runtime_devices[0].health_score == pytest.approx(0.42)

    def test_metadata_propagated(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        rrd = build_registered_runtime_device(
            device_id="e2e_meta",
            metadata={"region": "eu-west"},
        )
        proj = build_multi_device_runtime_projection(runtime_devices=[rrd])
        assert proj.runtime_devices[0].metadata.get("region") == "eu-west"
