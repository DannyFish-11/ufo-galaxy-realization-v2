#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr14_decision_diff_telemetry.py
==========================================
PR-14 — Decision-Diff Telemetry for Legacy vs Canonical Cross-Device Routing.

Coverage
--------
A) Module structure
   - Module importable from core.decision_diff_telemetry
   - DECISION_DIFF_TELEMETRY_AUTHORITY sentinel is present and non-empty
   - All public API names are exported in __all__

B) DecisionDiffRecord — data model
   - Default construction produces expected field types
   - decisions_differ property: True when decisions differ
   - decisions_differ property: False when decisions match
   - to_dict() produces a JSON-serialisable dict with all expected keys
   - to_dict() includes decisions_differ flag
   - Reason-code constants are importable and non-empty strings

C) Feature flag — is_telemetry_enabled()
   - Default (unset) is disabled
   - GALAXY_DECISION_DIFF_TELEMETRY=0 → disabled
   - GALAXY_DECISION_DIFF_TELEMETRY=1 → enabled
   - GALAXY_DECISION_DIFF_TELEMETRY=true → enabled (case-insensitive)
   - GALAXY_DECISION_DIFF_TELEMETRY=yes → enabled
   - Any other value → disabled

D) record_entry_mode_diff
   - Returns None when telemetry is disabled
   - Returns DecisionDiffRecord when enabled
   - Record has decision_point="entry_mode"
   - Record stored in ring buffer
   - Differing decisions produce non-empty diff_reason_codes
   - Matching decisions produce [REASON_DECISIONS_MATCH]
   - Auto-populates legacy_used_online_presence when decisions differ
   - target_device_not_ready included when target provided and decisions differ
   - Never raises when called with no arguments at all

E) record_candidate_diff
   - Returns None when telemetry is disabled
   - Returns DecisionDiffRecord when enabled
   - Record has decision_point="candidate_selection"
   - Record stored in ring buffer
   - Differing decisions produce non-empty diff_reason_codes
   - Matching decisions produce [REASON_DECISIONS_MATCH]
   - capability_mismatch appended when required_capabilities provided and differ
   - insufficient_orchestration_ready_devices appended when orch count < 2
   - Never raises when called with no arguments at all

F) Ring buffer
   - get_diff_store() returns snapshot list
   - clear_diff_store() empties the store
   - Records accumulate across multiple emit calls
   - Ring buffer is capped at 256 entries

G) No final-decision side effects
   - resolve_entry_mode() returns same value whether telemetry is on or off
   - resolve_entry_mode() returns same value regardless of what telemetry records

H) Graceful degradation
   - record_entry_mode_diff() never raises even when state_event_bus is absent
   - record_candidate_diff() never raises even when state_event_bus is absent
   - record functions never raise when optional subsystem imports fail
   - Telemetry store remains usable after suppressed exceptions

I) Telemetry disabled — clean behaviour
   - No records written to store when disabled
   - get_diff_store() is empty after disable-only calls
   - clear_diff_store() is safe to call on an empty store

J) resolve_entry_mode telemetry integration
   - With GALAXY_DECISION_DIFF_TELEMETRY=1 and legacy path active,
     resolve_entry_mode emits a diff record
   - With GALAXY_DECISION_DIFF_TELEMETRY=0 (default), no diff record emitted
   - Final resolved value is unchanged regardless of telemetry state
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helper: load core.unified.entrypoint_router directly (avoiding heavy deps
# pulled by core/unified/__init__.py such as fastapi / pydantic).
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent

def _load_entrypoint_router():
    """Load core.unified.entrypoint_router via file path, bypassing __init__."""
    mod_name = "core.unified.entrypoint_router"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec_path = _PROJECT_ROOT / "core" / "unified" / "entrypoint_router.py"
    spec = importlib.util.spec_from_file_location(mod_name, spec_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------

MOD = "core.decision_diff_telemetry"


# ===========================================================================
# A) Module structure
# ===========================================================================


class TestModuleStructure:
    def test_module_importable(self):
        import core.decision_diff_telemetry  # noqa: F401

    def test_authority_sentinel_present(self):
        from core.decision_diff_telemetry import DECISION_DIFF_TELEMETRY_AUTHORITY
        assert isinstance(DECISION_DIFF_TELEMETRY_AUTHORITY, str)
        assert len(DECISION_DIFF_TELEMETRY_AUTHORITY) > 0

    def test_authority_sentinel_contains_module_path(self):
        from core.decision_diff_telemetry import DECISION_DIFF_TELEMETRY_AUTHORITY
        assert "core.decision_diff_telemetry" in DECISION_DIFF_TELEMETRY_AUTHORITY

    def test_dunder_all_present(self):
        import core.decision_diff_telemetry as m
        assert hasattr(m, "__all__")
        assert isinstance(m.__all__, list)

    def test_all_exports_importable(self):
        import core.decision_diff_telemetry as m
        for name in m.__all__:
            assert hasattr(m, name), f"__all__ entry {name!r} not found on module"

    def test_decision_diff_record_in_all(self):
        from core.decision_diff_telemetry import __all__
        assert "DecisionDiffRecord" in __all__

    def test_is_telemetry_enabled_in_all(self):
        from core.decision_diff_telemetry import __all__
        assert "is_telemetry_enabled" in __all__

    def test_record_entry_mode_diff_in_all(self):
        from core.decision_diff_telemetry import __all__
        assert "record_entry_mode_diff" in __all__

    def test_record_candidate_diff_in_all(self):
        from core.decision_diff_telemetry import __all__
        assert "record_candidate_diff" in __all__


# ===========================================================================
# B) DecisionDiffRecord — data model
# ===========================================================================


class TestDecisionDiffRecord:
    def test_default_construction(self):
        from core.decision_diff_telemetry import DecisionDiffRecord
        rec = DecisionDiffRecord()
        assert rec.request_id is None
        assert rec.task_id is None
        assert rec.legacy_decision is None
        assert rec.canonical_decision is None
        assert isinstance(rec.legacy_selected_device_ids, list)
        assert isinstance(rec.canonical_selected_device_ids, list)
        assert isinstance(rec.diff_reason_codes, list)
        assert isinstance(rec.sources, dict)
        assert isinstance(rec.timestamp, float)
        assert rec.timestamp > 0

    def test_decisions_differ_true(self):
        from core.decision_diff_telemetry import DecisionDiffRecord
        rec = DecisionDiffRecord(legacy_decision="local", canonical_decision="cross_device")
        assert rec.decisions_differ is True

    def test_decisions_differ_false(self):
        from core.decision_diff_telemetry import DecisionDiffRecord
        rec = DecisionDiffRecord(legacy_decision="local", canonical_decision="local")
        assert rec.decisions_differ is False

    def test_decisions_differ_both_none(self):
        from core.decision_diff_telemetry import DecisionDiffRecord
        rec = DecisionDiffRecord()
        assert rec.decisions_differ is False

    def test_to_dict_contains_all_keys(self):
        from core.decision_diff_telemetry import DecisionDiffRecord
        rec = DecisionDiffRecord(
            request_id="req-1",
            task_id="task-1",
            decision_point="entry_mode",
            requested_target_device="dev-1",
            legacy_decision="local",
            canonical_decision="cross_device",
            legacy_selected_device_ids=["dev-a"],
            canonical_selected_device_ids=["dev-b"],
            ready_device_count=2,
            orchestration_ready_device_count=1,
            required_capabilities=["screen"],
            diff_reason_codes=["canonical_requires_readiness"],
            sources={"layer": "entry_mode_resolution"},
        )
        d = rec.to_dict()
        expected_keys = {
            "request_id", "task_id", "decision_point", "requested_target_device",
            "legacy_decision", "canonical_decision", "legacy_selected_device_ids",
            "canonical_selected_device_ids", "ready_device_count",
            "orchestration_ready_device_count", "required_capabilities",
            "diff_reason_codes", "sources", "timestamp", "decisions_differ",
        }
        for k in expected_keys:
            assert k in d, f"key {k!r} missing from to_dict()"

    def test_to_dict_json_serialisable(self):
        from core.decision_diff_telemetry import DecisionDiffRecord
        rec = DecisionDiffRecord(
            legacy_decision="local",
            canonical_decision="cross_device",
            diff_reason_codes=["legacy_used_online_presence"],
        )
        json.dumps(rec.to_dict())  # must not raise

    def test_to_dict_decisions_differ_flag(self):
        from core.decision_diff_telemetry import DecisionDiffRecord
        rec = DecisionDiffRecord(
            legacy_decision="cross_device",
            canonical_decision="local",
        )
        assert rec.to_dict()["decisions_differ"] is True

    def test_reason_code_constants_importable(self):
        from core.decision_diff_telemetry import (
            REASON_LEGACY_USED_ONLINE_PRESENCE,
            REASON_CANONICAL_REQUIRES_READINESS,
            REASON_TARGET_NOT_READY,
            REASON_TARGET_NOT_ELIGIBLE,
            REASON_CAPABILITY_MISMATCH,
            REASON_INSUFFICIENT_ORCH_READY,
            REASON_FORMATION_UNAVAILABLE,
            REASON_SESSION_UNAVAILABLE,
            REASON_DECISIONS_MATCH,
        )
        for code in (
            REASON_LEGACY_USED_ONLINE_PRESENCE,
            REASON_CANONICAL_REQUIRES_READINESS,
            REASON_TARGET_NOT_READY,
            REASON_TARGET_NOT_ELIGIBLE,
            REASON_CAPABILITY_MISMATCH,
            REASON_INSUFFICIENT_ORCH_READY,
            REASON_FORMATION_UNAVAILABLE,
            REASON_SESSION_UNAVAILABLE,
            REASON_DECISIONS_MATCH,
        ):
            assert isinstance(code, str) and len(code) > 0

    def test_reason_code_constants_in_all(self):
        from core.decision_diff_telemetry import __all__
        reason_code_names = [
            "REASON_LEGACY_USED_ONLINE_PRESENCE",
            "REASON_CANONICAL_REQUIRES_READINESS",
            "REASON_TARGET_NOT_READY",
            "REASON_TARGET_NOT_ELIGIBLE",
            "REASON_CAPABILITY_MISMATCH",
            "REASON_INSUFFICIENT_ORCH_READY",
            "REASON_FORMATION_UNAVAILABLE",
            "REASON_SESSION_UNAVAILABLE",
            "REASON_DECISIONS_MATCH",
        ]
        for name in reason_code_names:
            assert name in __all__, f"reason-code constant {name!r} missing from __all__"


# ===========================================================================
# C) Feature flag
# ===========================================================================


class TestFeatureFlag:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("GALAXY_DECISION_DIFF_TELEMETRY", raising=False)
        from core.decision_diff_telemetry import is_telemetry_enabled
        assert is_telemetry_enabled() is False

    def test_disabled_with_zero(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "0")
        from core.decision_diff_telemetry import is_telemetry_enabled
        assert is_telemetry_enabled() is False

    def test_enabled_with_one(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import is_telemetry_enabled
        assert is_telemetry_enabled() is True

    def test_enabled_with_true(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "true")
        from core.decision_diff_telemetry import is_telemetry_enabled
        assert is_telemetry_enabled() is True

    def test_enabled_with_true_uppercase(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "TRUE")
        from core.decision_diff_telemetry import is_telemetry_enabled
        assert is_telemetry_enabled() is True

    def test_enabled_with_yes(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "yes")
        from core.decision_diff_telemetry import is_telemetry_enabled
        assert is_telemetry_enabled() is True

    def test_disabled_with_other_value(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "enabled")
        from core.decision_diff_telemetry import is_telemetry_enabled
        assert is_telemetry_enabled() is False


# ===========================================================================
# D) record_entry_mode_diff
# ===========================================================================


class TestRecordEntryModeDiff:
    def setup_method(self):
        from core.decision_diff_telemetry import clear_diff_store
        clear_diff_store()

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv("GALAXY_DECISION_DIFF_TELEMETRY", raising=False)
        from core.decision_diff_telemetry import record_entry_mode_diff
        result = record_entry_mode_diff(
            legacy_decision="local",
            canonical_decision="cross_device",
        )
        assert result is None

    def test_returns_record_when_enabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff, DecisionDiffRecord
        result = record_entry_mode_diff(
            request_id="req-1",
            legacy_decision="local",
            canonical_decision="cross_device",
        )
        assert isinstance(result, DecisionDiffRecord)

    def test_decision_point_is_entry_mode(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff
        rec = record_entry_mode_diff(
            legacy_decision="cross_device",
            canonical_decision="local",
        )
        assert rec is not None
        assert rec.decision_point == "entry_mode"

    def test_record_stored_in_ring_buffer(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff, get_diff_store
        record_entry_mode_diff(
            legacy_decision="cross_device",
            canonical_decision="cross_device",
        )
        store = get_diff_store()
        assert len(store) == 1

    def test_differing_decisions_produce_reason_codes(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff
        rec = record_entry_mode_diff(
            legacy_decision="cross_device",
            canonical_decision="local",
        )
        assert rec is not None
        assert len(rec.diff_reason_codes) > 0

    def test_matching_decisions_produce_decisions_match_code(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            REASON_DECISIONS_MATCH,
        )
        rec = record_entry_mode_diff(
            legacy_decision="local",
            canonical_decision="local",
        )
        assert rec is not None
        assert REASON_DECISIONS_MATCH in rec.diff_reason_codes

    def test_auto_legacy_used_online_presence_when_differ(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            REASON_LEGACY_USED_ONLINE_PRESENCE,
        )
        rec = record_entry_mode_diff(
            legacy_decision="cross_device",
            canonical_decision="local",
        )
        assert rec is not None
        assert REASON_LEGACY_USED_ONLINE_PRESENCE in rec.diff_reason_codes

    def test_target_not_ready_included_when_target_provided_and_differ(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            REASON_TARGET_NOT_READY,
        )
        rec = record_entry_mode_diff(
            target_device="dev-xyz",
            legacy_decision="cross_device",
            canonical_decision="local",
        )
        assert rec is not None
        assert REASON_TARGET_NOT_READY in rec.diff_reason_codes

    def test_never_raises_with_no_arguments(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff
        # Must not raise
        record_entry_mode_diff()

    def test_sources_contain_layer_key(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff
        rec = record_entry_mode_diff(legacy_decision="local", canonical_decision="local")
        assert rec is not None
        assert "layer" in rec.sources

    def test_online_count_in_sources_when_provided(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff
        rec = record_entry_mode_diff(
            legacy_decision="cross_device",
            canonical_decision="local",
            online_device_count=3,
        )
        assert rec is not None
        assert rec.sources.get("legacy_online_device_count") == 3


# ===========================================================================
# E) record_candidate_diff
# ===========================================================================


class TestRecordCandidateDiff:
    def setup_method(self):
        from core.decision_diff_telemetry import clear_diff_store
        clear_diff_store()

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv("GALAXY_DECISION_DIFF_TELEMETRY", raising=False)
        from core.decision_diff_telemetry import record_candidate_diff
        result = record_candidate_diff(
            legacy_decision="proceed",
            canonical_decision="gate",
        )
        assert result is None

    def test_returns_record_when_enabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_candidate_diff, DecisionDiffRecord
        result = record_candidate_diff(
            legacy_decision="proceed",
            canonical_decision="gate",
        )
        assert isinstance(result, DecisionDiffRecord)

    def test_decision_point_is_candidate_selection(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_candidate_diff
        rec = record_candidate_diff(
            legacy_decision="proceed",
            canonical_decision="gate",
        )
        assert rec is not None
        assert rec.decision_point == "candidate_selection"

    def test_record_stored_in_ring_buffer(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_candidate_diff, get_diff_store
        record_candidate_diff(legacy_decision="a", canonical_decision="b")
        assert len(get_diff_store()) == 1

    def test_differing_decisions_produce_reason_codes(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_candidate_diff
        rec = record_candidate_diff(
            legacy_selected_device_ids=["dev-a"],
            canonical_selected_device_ids=["dev-b"],
        )
        assert rec is not None
        assert len(rec.diff_reason_codes) > 0

    def test_matching_decisions_produce_decisions_match_code(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_candidate_diff,
            REASON_DECISIONS_MATCH,
        )
        rec = record_candidate_diff(
            legacy_decision="proceed",
            canonical_decision="proceed",
            legacy_selected_device_ids=["dev-a"],
            canonical_selected_device_ids=["dev-a"],
        )
        assert rec is not None
        assert REASON_DECISIONS_MATCH in rec.diff_reason_codes

    def test_capability_mismatch_included_when_capabilities_and_differ(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_candidate_diff,
            REASON_CAPABILITY_MISMATCH,
        )
        rec = record_candidate_diff(
            legacy_decision="proceed",
            canonical_decision="gate",
            required_capabilities=["screen", "audio"],
        )
        assert rec is not None
        assert REASON_CAPABILITY_MISMATCH in rec.diff_reason_codes

    def test_insufficient_orch_ready_included_when_count_low(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_candidate_diff,
            REASON_INSUFFICIENT_ORCH_READY,
        )
        rec = record_candidate_diff(
            legacy_decision="proceed",
            canonical_decision="gate",
            orchestration_ready_device_count=1,
        )
        assert rec is not None
        assert REASON_INSUFFICIENT_ORCH_READY in rec.diff_reason_codes

    def test_never_raises_with_no_arguments(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_candidate_diff
        record_candidate_diff()

    def test_device_ids_stored_correctly(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_candidate_diff
        rec = record_candidate_diff(
            legacy_selected_device_ids=["dev-1", "dev-2"],
            canonical_selected_device_ids=["dev-2"],
        )
        assert rec is not None
        assert rec.legacy_selected_device_ids == ["dev-1", "dev-2"]
        assert rec.canonical_selected_device_ids == ["dev-2"]


# ===========================================================================
# F) Ring buffer
# ===========================================================================


class TestRingBuffer:
    def setup_method(self):
        from core.decision_diff_telemetry import clear_diff_store
        clear_diff_store()

    def test_get_diff_store_returns_list(self):
        from core.decision_diff_telemetry import get_diff_store
        result = get_diff_store()
        assert isinstance(result, list)

    def test_clear_diff_store_empties_buffer(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            get_diff_store,
            clear_diff_store,
        )
        record_entry_mode_diff(legacy_decision="local", canonical_decision="cross_device")
        assert len(get_diff_store()) == 1
        clear_diff_store()
        assert len(get_diff_store()) == 0

    def test_records_accumulate(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            record_candidate_diff,
            get_diff_store,
        )
        record_entry_mode_diff(legacy_decision="local", canonical_decision="local")
        record_candidate_diff(legacy_decision="proceed", canonical_decision="proceed")
        assert len(get_diff_store()) == 2

    def test_ring_buffer_is_capped(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            get_diff_store,
        )
        for i in range(300):
            record_entry_mode_diff(
                request_id=str(i),
                legacy_decision="local",
                canonical_decision="local",
            )
        store = get_diff_store()
        assert len(store) <= 256

    def test_get_diff_store_returns_snapshot(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            get_diff_store,
            clear_diff_store,
        )
        record_entry_mode_diff(legacy_decision="local", canonical_decision="local")
        snap = get_diff_store()
        clear_diff_store()
        # snapshot should not be mutated by clear
        assert len(snap) == 1


# ===========================================================================
# G) No final-decision side effects
# ===========================================================================


class TestNoFinalDecisionSideEffects:
    """The telemetry hooks must never change the resolved entry mode."""

    def _resolve(self, env_enabled: bool, use_readiness: bool, monkeypatch) -> str:
        monkeypatch.setenv(
            "GALAXY_DECISION_DIFF_TELEMETRY", "1" if env_enabled else "0"
        )
        monkeypatch.setenv(
            "GALAXY_ENTRYMODE_USE_READINESS", "1" if use_readiness else "0"
        )
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        resolve_entry_mode = _load_entrypoint_router().resolve_entry_mode
        return resolve_entry_mode(trace_id="test-trace")

    def test_cross_device_disabled_telemetry_on_returns_local(self, monkeypatch):
        result = self._resolve(env_enabled=True, use_readiness=False, monkeypatch=monkeypatch)
        assert result == "local"

    def test_cross_device_disabled_telemetry_off_returns_local(self, monkeypatch):
        result = self._resolve(env_enabled=False, use_readiness=False, monkeypatch=monkeypatch)
        assert result == "local"

    def test_explicit_entry_mode_unchanged_by_telemetry(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        resolve_entry_mode = _load_entrypoint_router().resolve_entry_mode
        result = resolve_entry_mode(explicit_entry_mode="custom_mode")
        assert result == "custom_mode"

    def test_same_result_telemetry_on_vs_off_legacy_path(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        monkeypatch.setenv("GALAXY_ENTRYMODE_USE_READINESS", "0")

        resolve_entry_mode = _load_entrypoint_router().resolve_entry_mode

        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "0")
        result_off = resolve_entry_mode(trace_id="t1")

        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        result_on = resolve_entry_mode(trace_id="t2")

        assert result_off == result_on


# ===========================================================================
# H) Graceful degradation
# ===========================================================================


class TestGracefulDegradation:
    def setup_method(self):
        from core.decision_diff_telemetry import clear_diff_store
        clear_diff_store()

    def test_record_entry_mode_diff_no_crash_when_seb_absent(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        with patch("core.state_event_bus.emit", side_effect=ImportError("no bus")):
            from core.decision_diff_telemetry import record_entry_mode_diff
            # Should not raise
            rec = record_entry_mode_diff(
                legacy_decision="local",
                canonical_decision="cross_device",
            )
        assert rec is not None

    def test_record_candidate_diff_no_crash_when_seb_absent(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        with patch("core.state_event_bus.emit", side_effect=ImportError("no bus")):
            from core.decision_diff_telemetry import record_candidate_diff
            rec = record_candidate_diff(
                legacy_decision="proceed",
                canonical_decision="gate",
            )
        assert rec is not None

    def test_record_entry_mode_diff_with_all_none(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff
        rec = record_entry_mode_diff()
        assert rec is not None

    def test_record_candidate_diff_with_all_none(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_candidate_diff
        rec = record_candidate_diff()
        assert rec is not None

    def test_store_remains_usable_after_failure(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            get_diff_store,
        )
        # Force an exception in state bus; record should still land
        with patch("core.state_event_bus.emit", side_effect=RuntimeError("bus down")):
            record_entry_mode_diff(legacy_decision="local", canonical_decision="local")
        assert len(get_diff_store()) == 1

    def test_record_with_explicit_reason_codes_preserved(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        from core.decision_diff_telemetry import record_entry_mode_diff
        rec = record_entry_mode_diff(
            legacy_decision="cross_device",
            canonical_decision="local",
            diff_reason_codes=["my_custom_reason"],
        )
        assert rec is not None
        assert "my_custom_reason" in rec.diff_reason_codes


# ===========================================================================
# I) Telemetry disabled — clean behaviour
# ===========================================================================


class TestTelemetryDisabled:
    def setup_method(self):
        from core.decision_diff_telemetry import clear_diff_store
        clear_diff_store()

    def test_no_records_when_disabled(self, monkeypatch):
        monkeypatch.delenv("GALAXY_DECISION_DIFF_TELEMETRY", raising=False)
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            record_candidate_diff,
            get_diff_store,
        )
        record_entry_mode_diff(legacy_decision="local", canonical_decision="cross_device")
        record_candidate_diff(legacy_decision="proceed", canonical_decision="gate")
        assert len(get_diff_store()) == 0

    def test_get_diff_store_empty_after_only_disabled_calls(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "0")
        from core.decision_diff_telemetry import (
            record_entry_mode_diff,
            get_diff_store,
        )
        record_entry_mode_diff(legacy_decision="local", canonical_decision="local")
        assert get_diff_store() == []

    def test_clear_diff_store_safe_on_empty(self):
        from core.decision_diff_telemetry import clear_diff_store
        clear_diff_store()
        clear_diff_store()  # second call on empty — must not raise


# ===========================================================================
# J) resolve_entry_mode telemetry integration
# ===========================================================================


class TestResolveEntryModeTelemetryIntegration:
    def setup_method(self):
        from core.decision_diff_telemetry import clear_diff_store
        clear_diff_store()

    def test_no_diff_record_when_telemetry_disabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "0")
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        resolve_entry_mode = _load_entrypoint_router().resolve_entry_mode
        from core.decision_diff_telemetry import get_diff_store

        resolve_entry_mode(trace_id="no-tel")
        assert len(get_diff_store()) == 0

    def test_diff_record_emitted_when_telemetry_enabled_legacy_path(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        monkeypatch.setenv("GALAXY_ENTRYMODE_USE_READINESS", "0")

        # The UDM import will gracefully fail (count=0) in the test environment;
        # we just need to confirm a diff record is emitted.
        mod = _load_entrypoint_router()
        resolve_entry_mode = mod.resolve_entry_mode

        from core.decision_diff_telemetry import get_diff_store
        result = resolve_entry_mode(trace_id="with-tel")

        # Final resolved value must still be the legacy outcome
        assert result in ("local", "cross_device")

        # A diff record should have been emitted
        store = get_diff_store()
        assert len(store) >= 1
        assert store[-1].decision_point == "entry_mode"

    def test_final_result_unchanged_by_telemetry_enabled(self, monkeypatch):
        """Enabling telemetry must not change the final returned entry mode."""
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        monkeypatch.setenv("GALAXY_ENTRYMODE_USE_READINESS", "0")

        resolve_entry_mode = _load_entrypoint_router().resolve_entry_mode

        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "0")
        result_off = resolve_entry_mode(trace_id="off")

        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")
        result_on = resolve_entry_mode(trace_id="on")

        assert result_off == result_on == "local"

    def test_explicit_entry_mode_bypasses_telemetry_hook(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DECISION_DIFF_TELEMETRY", "1")

        resolve_entry_mode = _load_entrypoint_router().resolve_entry_mode
        from core.decision_diff_telemetry import get_diff_store

        result = resolve_entry_mode(explicit_entry_mode="my_override", trace_id="exp")
        assert result == "my_override"
        # Telemetry hook is skipped for explicit overrides
        assert len(get_diff_store()) == 0
