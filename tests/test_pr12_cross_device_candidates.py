"""
tests/test_pr12_cross_device_candidates.py
===========================================
Tests for PR-12: Unified Cross-Device Execution Candidate Resolution.

Coverage
--------
A) Module structure
   - CROSS_DEVICE_CANDIDATES_AUTHORITY sentinel is importable and has expected value
   - CrossDeviceCandidate is importable and has expected fields
   - CrossDeviceCandidateResolution is importable and has expected fields
   - resolve_cross_device_candidates is importable and callable
   - get_selected_cross_device_candidates is importable and callable

B) CrossDeviceCandidate — data model
   - default construction produces expected field values
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable

C) CrossDeviceCandidateResolution — data model
   - default construction produces expected field values
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable

D) resolve_cross_device_candidates — core resolution logic
   - ready + orchestration-eligible + capability-matching device is selected
   - device excluded when not ready
   - device excluded when not orchestration-eligible
   - device excluded on capability mismatch
   - device excluded when all three gates fail
   - empty device registry returns empty resolution
   - resolution returns CrossDeviceCandidateResolution instance

E) Requested target device handling
   - requested valid target is listed first in selected_device_ids
   - requested invalid (not ready) target is excluded with explicit reasons
   - requested target not in registry is evaluated and excluded with reasons
   - resolution.reasons populated when requested target is excluded
   - resolution still returns other eligible devices when target excluded

F) require_orchestration_eligible=False
   - device passes even when orchestration gate would fail

G) get_selected_cross_device_candidates
   - returns only selected candidates
   - returns empty list when no devices eligible

H) Graceful degradation — missing optional subsystems
   - readiness layer unavailable: device excluded with reason, no crash
   - participation layer unavailable: device excluded with reason, no crash
   - capability layer unavailable: device excluded with reason, no crash
   - device_registry unavailable: empty list, no crash
   - resolve_cross_device_candidates never raises
   - get_selected_cross_device_candidates never raises

I) Observability / logging
   - excluded devices produce INFO logs
   - selected devices produce DEBUG logs
   - candidate reasons populated on exclusion
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: patch internal helpers inside cross_device_candidates directly
# ---------------------------------------------------------------------------
# We always patch the helpers at "core.cross_device_candidates.*" so tests
# never need to reach through the full import chain of real subsystems.
# ---------------------------------------------------------------------------

MOD = "core.cross_device_candidates"


def _patch_enumerate(device_ids: List[str]):
    return patch(f"{MOD}._enumerate_device_ids", return_value=device_ids)


def _patch_readiness(results: Dict[str, bool]):
    def _check(device_id):
        ready = results.get(device_id, False)
        return (ready, [])
    return patch(f"{MOD}._check_readiness", side_effect=_check)


def _patch_participation(results: Dict[str, bool]):
    def _check(device_id):
        eligible = results.get(device_id, False)
        return (eligible, [])
    return patch(f"{MOD}._check_orchestration_eligible", side_effect=_check)


def _patch_capabilities(results: Dict[str, bool], missing_map: Optional[Dict[str, List[str]]] = None):
    if missing_map is None:
        missing_map = {}
    def _check(device_id, required_capabilities):
        matched = results.get(device_id, False)
        missing = missing_map.get(device_id, []) if not matched else []
        reasons = [f"capability mismatch for {device_id!r} — missing: {missing}"] if not matched else []
        return (matched, {}, reasons)
    return patch(f"{MOD}._check_capabilities", side_effect=_check)


# ============================================================================
# A) Module structure
# ============================================================================

class TestModuleStructure:
    def test_authority_sentinel_importable(self):
        from core.cross_device_candidates import CROSS_DEVICE_CANDIDATES_AUTHORITY
        assert isinstance(CROSS_DEVICE_CANDIDATES_AUTHORITY, str)
        assert "PR-12" in CROSS_DEVICE_CANDIDATES_AUTHORITY

    def test_authority_sentinel_identifies_module(self):
        from core.cross_device_candidates import CROSS_DEVICE_CANDIDATES_AUTHORITY
        assert "core.cross_device_candidates" in CROSS_DEVICE_CANDIDATES_AUTHORITY

    def test_cross_device_candidate_importable(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        assert CrossDeviceCandidate is not None

    def test_cross_device_candidate_resolution_importable(self):
        from core.cross_device_candidates import CrossDeviceCandidateResolution
        assert CrossDeviceCandidateResolution is not None

    def test_resolve_cross_device_candidates_importable(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        assert callable(resolve_cross_device_candidates)

    def test_get_selected_cross_device_candidates_importable(self):
        from core.cross_device_candidates import get_selected_cross_device_candidates
        assert callable(get_selected_cross_device_candidates)

    def test_all_exports_in_dunder_all(self):
        import core.cross_device_candidates as m
        for name in [
            "CrossDeviceCandidate",
            "CrossDeviceCandidateResolution",
            "resolve_cross_device_candidates",
            "get_selected_cross_device_candidates",
            "CROSS_DEVICE_CANDIDATES_AUTHORITY",
        ]:
            assert name in m.__all__, f"{name} missing from __all__"


# ============================================================================
# B) CrossDeviceCandidate — data model
# ============================================================================

class TestCrossDeviceCandidateModel:
    def test_default_construction(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="dev-1")
        assert c.device_id == "dev-1"
        assert c.ready is False
        assert c.orchestration_eligible is False
        assert c.capability_match is True  # default True (no caps required)
        assert c.selected is False
        assert isinstance(c.reasons, list)
        assert isinstance(c.sources, dict)

    def test_to_dict_contains_expected_keys(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="dev-1")
        d = c.to_dict()
        for key in ["device_id", "ready", "orchestration_eligible",
                    "capability_match", "selected", "reasons", "sources"]:
            assert key in d, f"key {key!r} missing from to_dict()"

    def test_to_dict_is_json_serialisable(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(
            device_id="dev-x",
            ready=True,
            orchestration_eligible=True,
            capability_match=True,
            selected=True,
            reasons=["all good"],
            sources={"device_registry": ["cap_a"]},
        )
        serialised = json.dumps(c.to_dict())
        parsed = json.loads(serialised)
        assert parsed["device_id"] == "dev-x"
        assert parsed["selected"] is True


# ============================================================================
# C) CrossDeviceCandidateResolution — data model
# ============================================================================

class TestCrossDeviceCandidateResolutionModel:
    def test_default_construction(self):
        from core.cross_device_candidates import CrossDeviceCandidateResolution
        r = CrossDeviceCandidateResolution()
        assert isinstance(r.required_capabilities, list)
        assert r.requested_target_device is None
        assert isinstance(r.candidates, list)
        assert isinstance(r.selected_device_ids, list)
        assert isinstance(r.eligible_device_ids, list)
        assert isinstance(r.reasons, list)

    def test_to_dict_contains_expected_keys(self):
        from core.cross_device_candidates import CrossDeviceCandidateResolution
        r = CrossDeviceCandidateResolution()
        d = r.to_dict()
        for key in ["required_capabilities", "requested_target_device",
                    "candidates", "selected_device_ids", "eligible_device_ids", "reasons"]:
            assert key in d, f"key {key!r} missing from to_dict()"

    def test_to_dict_is_json_serialisable(self):
        from core.cross_device_candidates import CrossDeviceCandidateResolution
        r = CrossDeviceCandidateResolution(
            required_capabilities=["screen"],
            requested_target_device="dev-1",
            selected_device_ids=["dev-1"],
            eligible_device_ids=["dev-1"],
            reasons=["all ok"],
        )
        serialised = json.dumps(r.to_dict())
        parsed = json.loads(serialised)
        assert parsed["selected_device_ids"] == ["dev-1"]


# ============================================================================
# D) resolve_cross_device_candidates — core resolution logic
# ============================================================================

class TestResolveCrossDeviceCandidates:
    def test_returns_resolution_instance(self):
        from core.cross_device_candidates import (
            resolve_cross_device_candidates,
            CrossDeviceCandidateResolution,
        )
        with _patch_enumerate([]):
            result = resolve_cross_device_candidates()
        assert isinstance(result, CrossDeviceCandidateResolution)

    def test_empty_registry_returns_empty_resolution(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate([]):
            result = resolve_cross_device_candidates()
        assert result.selected_device_ids == []
        assert result.eligible_device_ids == []
        assert result.candidates == []

    def test_all_gates_pass_device_is_selected(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-a"]), \
             _patch_readiness({"dev-a": True}), \
             _patch_participation({"dev-a": True}), \
             _patch_capabilities({"dev-a": True}):
            result = resolve_cross_device_candidates(required_capabilities=["screen"])
        assert "dev-a" in result.selected_device_ids
        assert "dev-a" in result.eligible_device_ids
        candidate = result.candidates[0]
        assert candidate.device_id == "dev-a"
        assert candidate.selected is True
        assert candidate.ready is True
        assert candidate.orchestration_eligible is True
        assert candidate.capability_match is True

    def test_device_excluded_when_not_ready(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-b"]), \
             _patch_readiness({"dev-b": False}), \
             _patch_participation({"dev-b": True}):
            result = resolve_cross_device_candidates()
        assert "dev-b" not in result.selected_device_ids
        assert "dev-b" not in result.eligible_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-b")
        assert candidate.ready is False
        assert candidate.selected is False
        assert any("not cross-device ready" in r for r in candidate.reasons)

    def test_device_excluded_when_not_orchestration_eligible(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-c"]), \
             _patch_readiness({"dev-c": True}), \
             _patch_participation({"dev-c": False}):
            result = resolve_cross_device_candidates()
        assert "dev-c" not in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-c")
        assert candidate.ready is True
        assert candidate.orchestration_eligible is False
        assert candidate.selected is False
        assert any("orchestration-eligible" in r for r in candidate.reasons)

    def test_device_excluded_on_capability_mismatch(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-d"]), \
             _patch_readiness({"dev-d": True}), \
             _patch_participation({"dev-d": True}), \
             _patch_capabilities({"dev-d": False}, missing_map={"dev-d": ["camera"]}):
            result = resolve_cross_device_candidates(required_capabilities=["camera"])
        assert "dev-d" not in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-d")
        assert candidate.ready is True
        assert candidate.orchestration_eligible is True
        assert candidate.capability_match is False
        assert candidate.selected is False
        assert any("capability mismatch" in r or "missing" in r for r in candidate.reasons)

    def test_device_excluded_when_readiness_fails(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-e"]), \
             _patch_readiness({"dev-e": False}), \
             _patch_participation({"dev-e": False}):
            result = resolve_cross_device_candidates()
        assert "dev-e" not in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-e")
        assert candidate.selected is False

    def test_mixed_devices_only_passing_selected(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        device_ids = ["dev-pass", "dev-fail-ready", "dev-fail-orch"]
        with _patch_enumerate(device_ids), \
             _patch_readiness({"dev-pass": True, "dev-fail-ready": False, "dev-fail-orch": True}), \
             _patch_participation({"dev-pass": True, "dev-fail-orch": False}):
            result = resolve_cross_device_candidates()
        assert result.selected_device_ids == ["dev-pass"]
        assert len(result.candidates) == 3

    def test_required_capabilities_forwarded(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate([]):
            result = resolve_cross_device_candidates(required_capabilities=["gps", "camera"])
        assert result.required_capabilities == ["gps", "camera"]

    def test_no_capabilities_skips_capability_gate(self):
        """When no capabilities required, capability_match defaults True."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-f"]), \
             _patch_readiness({"dev-f": True}), \
             _patch_participation({"dev-f": True}):
            result = resolve_cross_device_candidates()
        assert "dev-f" in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-f")
        assert candidate.capability_match is True


# ============================================================================
# E) Requested target device handling
# ============================================================================

class TestRequestedTargetDevice:
    def test_valid_target_listed_first(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        device_ids = ["dev-other", "dev-target"]
        with _patch_enumerate(device_ids), \
             _patch_readiness({"dev-other": True, "dev-target": True}), \
             _patch_participation({"dev-other": True, "dev-target": True}):
            result = resolve_cross_device_candidates(requested_target_device="dev-target")
        assert result.selected_device_ids[0] == "dev-target"
        assert "dev-other" in result.selected_device_ids

    def test_invalid_target_excluded_with_reasons(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-target"]), \
             _patch_readiness({"dev-target": False}), \
             _patch_participation({"dev-target": True}):
            result = resolve_cross_device_candidates(requested_target_device="dev-target")
        assert "dev-target" not in result.selected_device_ids
        assert any("dev-target" in r for r in result.reasons)

    def test_target_not_in_registry_evaluated_with_reasons(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        # requested target is not in registry; readiness returns False for it
        with _patch_enumerate([]), \
             _patch_readiness({}), \
             _patch_participation({}):
            result = resolve_cross_device_candidates(requested_target_device="ghost-device")
        assert "ghost-device" not in result.selected_device_ids
        assert any("ghost-device" in r for r in result.reasons)

    def test_target_in_registry_but_not_ready_other_devices_returned(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-target", "dev-good"]), \
             _patch_readiness({"dev-target": False, "dev-good": True}), \
             _patch_participation({"dev-good": True}):
            result = resolve_cross_device_candidates(requested_target_device="dev-target")
        # other eligible device should still be returned
        assert "dev-good" in result.selected_device_ids
        # reason about target exclusion should appear
        assert any("dev-target" in r for r in result.reasons)

    def test_target_capability_mismatch_surfaces_reasons(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-target"]), \
             _patch_readiness({"dev-target": True}), \
             _patch_participation({"dev-target": True}), \
             _patch_capabilities({"dev-target": False}, missing_map={"dev-target": ["gps"]}):
            result = resolve_cross_device_candidates(
                required_capabilities=["gps"],
                requested_target_device="dev-target",
            )
        assert "dev-target" not in result.selected_device_ids
        assert any("dev-target" in r for r in result.reasons)

    def test_no_requested_target_all_eligible_selected(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        device_ids = ["dev-1", "dev-2"]
        with _patch_enumerate(device_ids), \
             _patch_readiness({"dev-1": True, "dev-2": True}), \
             _patch_participation({"dev-1": True, "dev-2": True}):
            result = resolve_cross_device_candidates()
        assert set(result.selected_device_ids) == {"dev-1", "dev-2"}


# ============================================================================
# F) require_orchestration_eligible=False
# ============================================================================

class TestOrchestrationGateDisabled:
    def test_device_passes_when_orchestration_gate_skipped(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        # Participation would say NOT eligible, but gate is off
        with _patch_enumerate(["dev-g"]), \
             _patch_readiness({"dev-g": True}), \
             _patch_participation({"dev-g": False}):
            result = resolve_cross_device_candidates(
                require_orchestration_eligible=False
            )
        assert "dev-g" in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-g")
        assert candidate.selected is True

    def test_readiness_still_required_when_orchestration_gate_off(self):
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-h"]), \
             _patch_readiness({"dev-h": False}), \
             _patch_participation({"dev-h": True}):
            result = resolve_cross_device_candidates(
                require_orchestration_eligible=False
            )
        assert "dev-h" not in result.selected_device_ids


# ============================================================================
# G) get_selected_cross_device_candidates
# ============================================================================

class TestGetSelectedCrossDeviceCandidates:
    def test_returns_list(self):
        from core.cross_device_candidates import get_selected_cross_device_candidates
        with _patch_enumerate([]):
            result = get_selected_cross_device_candidates()
        assert isinstance(result, list)

    def test_returns_only_selected_candidates(self):
        from core.cross_device_candidates import (
            get_selected_cross_device_candidates,
            CrossDeviceCandidate,
        )
        device_ids = ["dev-sel", "dev-no"]
        with _patch_enumerate(device_ids), \
             _patch_readiness({"dev-sel": True, "dev-no": False}), \
             _patch_participation({"dev-sel": True}):
            candidates = get_selected_cross_device_candidates()
        assert all(isinstance(c, CrossDeviceCandidate) for c in candidates)
        assert all(c.selected for c in candidates)
        ids = [c.device_id for c in candidates]
        assert "dev-sel" in ids
        assert "dev-no" not in ids

    def test_returns_empty_when_none_eligible(self):
        from core.cross_device_candidates import get_selected_cross_device_candidates
        with _patch_enumerate(["dev-x"]), \
             _patch_readiness({"dev-x": False}):
            result = get_selected_cross_device_candidates()
        assert result == []


# ============================================================================
# H) Graceful degradation — missing optional subsystems
# ============================================================================

class TestGracefulDegradation:
    def test_readiness_layer_unavailable_no_crash(self):
        """When _check_readiness raises, device is excluded gracefully."""
        from core.cross_device_candidates import resolve_cross_device_candidates

        def _raise(device_id):
            raise RuntimeError("readiness layer down")

        with _patch_enumerate(["dev-i"]), \
             patch(f"{MOD}._check_readiness", side_effect=_raise):
            result = resolve_cross_device_candidates()
        # The top-level try/except catches this; result may be empty
        assert isinstance(result.candidates, list)
        # No exception raised

    def test_participation_layer_unavailable_no_crash(self):
        """When _check_orchestration_eligible raises, device excluded gracefully."""
        from core.cross_device_candidates import resolve_cross_device_candidates

        def _raise(device_id):
            raise RuntimeError("participation layer down")

        with _patch_enumerate(["dev-j"]), \
             _patch_readiness({"dev-j": True}), \
             patch(f"{MOD}._check_orchestration_eligible", side_effect=_raise):
            result = resolve_cross_device_candidates()
        assert isinstance(result.candidates, list)

    def test_capability_layer_unavailable_device_excluded_with_reason(self):
        """When _check_capabilities returns reason list, device is excluded."""
        from core.cross_device_candidates import resolve_cross_device_candidates

        def _degraded(device_id, caps):
            return (False, {}, [f"capability layer unavailable for {device_id!r} — error"])

        with _patch_enumerate(["dev-k"]), \
             _patch_readiness({"dev-k": True}), \
             _patch_participation({"dev-k": True}), \
             patch(f"{MOD}._check_capabilities", side_effect=_degraded):
            result = resolve_cross_device_candidates(required_capabilities=["screen"])
        assert "dev-k" not in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-k")
        assert candidate.selected is False
        assert any("capability layer unavailable" in r for r in candidate.reasons)

    def test_device_registry_unavailable_returns_empty(self):
        """When _enumerate_device_ids returns [], resolution is empty."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate([]):
            result = resolve_cross_device_candidates()
        assert result.selected_device_ids == []
        assert result.candidates == []

    def test_resolve_never_raises(self):
        """resolve_cross_device_candidates must never propagate an exception."""
        from core.cross_device_candidates import resolve_cross_device_candidates

        def _boom():
            raise RuntimeError("boom")

        with patch(f"{MOD}._enumerate_device_ids", side_effect=_boom):
            try:
                result = resolve_cross_device_candidates()
            except Exception as exc:
                pytest.fail(f"resolve_cross_device_candidates raised unexpectedly: {exc}")

    def test_get_selected_never_raises(self):
        """get_selected_cross_device_candidates must never propagate an exception."""
        from core.cross_device_candidates import get_selected_cross_device_candidates

        def _boom():
            raise RuntimeError("boom")

        with patch(f"{MOD}._enumerate_device_ids", side_effect=_boom):
            try:
                result = get_selected_cross_device_candidates()
            except Exception as exc:
                pytest.fail(f"get_selected_cross_device_candidates raised unexpectedly: {exc}")


# ============================================================================
# I) Observability / logging
# ============================================================================

class TestObservability:
    def test_excluded_device_produces_info_log(self, caplog):
        """Not-ready device should produce an INFO-level log."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with caplog.at_level(logging.INFO, logger="Galaxy.CrossDeviceCandidates"), \
             _patch_enumerate(["dev-log"]), \
             _patch_readiness({"dev-log": False}), \
             _patch_participation({"dev-log": True}):
            resolve_cross_device_candidates()
        assert any(
            "EXCLUDED" in r.message
            for r in caplog.records
            if r.name == "Galaxy.CrossDeviceCandidates"
        )

    def test_selected_device_produces_debug_log(self, caplog):
        """Selected device should produce a DEBUG-level log."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with caplog.at_level(logging.DEBUG, logger="Galaxy.CrossDeviceCandidates"), \
             _patch_enumerate(["dev-log2"]), \
             _patch_readiness({"dev-log2": True}), \
             _patch_participation({"dev-log2": True}):
            resolve_cross_device_candidates()
        assert any(
            "SELECTED" in r.message
            for r in caplog.records
            if r.name == "Galaxy.CrossDeviceCandidates"
        )

    def test_candidate_reasons_populated_on_exclusion(self):
        """Excluded candidates must have non-empty reasons."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-reason"]), \
             _patch_readiness({"dev-reason": True}), \
             _patch_participation({"dev-reason": False}):
            result = resolve_cross_device_candidates()
        candidate = next(c for c in result.candidates if c.device_id == "dev-reason")
        assert len(candidate.reasons) > 0
