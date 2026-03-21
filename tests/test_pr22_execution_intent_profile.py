"""
tests/test_pr22_execution_intent_profile.py
=============================================
Focused tests for PR-22: Execution Intent Profile.

Coverage
--------
1. ExecutionIntentProfile
   - creation from minimal inputs (defaults are safe)
   - creation with all fields specified
   - serialisation / deserialisation stability (to_dict / to_json round-trip)
   - compact_summary() contains expected keys

2. IntentMode
   - from_action_level normalisation for all four levels
   - unknown level falls back to advisory

3. build_execution_intent_profile (module-level builder)
   - builds from None continuum (safe defaults)
   - builds from full continuum dict
   - extracts action_level, confidence, target_ref, runtime_domain
   - entry_mode → device_scope mapping (local / cross_device / hybrid)
   - safety_constraints forwarded from metadata
   - origin_state extracted from phase / tri_state_phase
   - graceful handling of malformed / partial continuum dict

4. ExecutionIntentProfile.from_state_continuum (class method)
   - equivalent to build_execution_intent_profile for basic usage
   - exception in internal helpers → falls back to minimal safe profile

5. RuntimeProjection integration
   - execution_intent_summary is None when no profile provided
   - execution_intent_summary populated when intent_profile passed to
     build_runtime_projection()
   - execution_intent_summary survives to_dict() round-trip

6. _run_execution integration (OpenClawd)
   - returned dict includes "execution_intent" key
   - "execution_intent" is a dict with expected keys
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.execution.intent_profile import (
    ExecutionIntentProfile,
    IntentMode,
    build_execution_intent_profile,
    _entry_mode_to_device_scope,
    _runtime_domain_to_device_scope,
    _infer_target_type,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL_CONTINUUM: Dict[str, Any] = {
    "decision": {
        "action_level": "assist",
        "decision_confidence": 0.75,
    },
    "phase": "manifest",
    "runtime_domain": "local",
    "metadata": {
        "execution_target": "notepad.exe",
        "target_type": "app",
    },
}

_FULL_CONTINUUM: Dict[str, Any] = {
    "decision": {
        "action_level": "execute",
        "decision_confidence": 0.92,
    },
    "phase": "manifest",
    "tri_state_phase": "manifest",
    "runtime_domain": "cross_device",
    "metadata": {
        "execution_target": "calc.exe",
        "target_type": "app",
        "target_payload": {"arg": "--debug"},
        "safety_constraints": ["allowlist_required", "user_confirm"],
        "runtime_session_id": "sess-xyz",
    },
}


# ---------------------------------------------------------------------------
# 1. ExecutionIntentProfile — construction and defaults
# ---------------------------------------------------------------------------


class TestExecutionIntentProfileConstruction:
    def test_minimal_defaults(self):
        profile = ExecutionIntentProfile()
        assert profile.action_level == "observe"
        assert profile.intent_mode == IntentMode.ADVISORY
        assert profile.source == "openclawd"
        assert profile.confidence == 0.0
        assert profile.target_ref is None
        assert profile.target_type is None
        assert profile.device_scope is None
        assert profile.runtime_domain is None
        assert profile.safety_constraints == []
        assert profile.origin_state is None
        assert profile.notes is None
        assert profile.degrade_reason is None
        # intent_id should be a valid UUID string
        parsed = uuid.UUID(profile.intent_id)
        assert str(parsed) == profile.intent_id

    def test_unique_intent_ids(self):
        p1 = ExecutionIntentProfile()
        p2 = ExecutionIntentProfile()
        assert p1.intent_id != p2.intent_id

    def test_explicit_fields(self):
        profile = ExecutionIntentProfile(
            runtime_session_id="sess-001",
            source="chat",
            action_level="execute",
            intent_mode=IntentMode.DIRECT,
            target_type="app",
            target_ref="notepad.exe",
            target_payload={"flag": True},
            device_scope="local",
            runtime_domain="local",
            confidence=0.88,
            safety_constraints=["allowlist_required"],
            origin_state="manifest",
            notes="debug note",
            degrade_reason=None,
        )
        assert profile.runtime_session_id == "sess-001"
        assert profile.source == "chat"
        assert profile.action_level == "execute"
        assert profile.intent_mode == IntentMode.DIRECT
        assert profile.target_type == "app"
        assert profile.target_ref == "notepad.exe"
        assert profile.target_payload == {"flag": True}
        assert profile.device_scope == "local"
        assert profile.runtime_domain == "local"
        assert profile.confidence == 0.88
        assert profile.safety_constraints == ["allowlist_required"]
        assert profile.origin_state == "manifest"
        assert profile.notes == "debug note"
        assert profile.degrade_reason is None

    def test_confidence_clamped_by_pydantic(self):
        # pydantic should raise on out-of-range confidence
        with pytest.raises(Exception):
            ExecutionIntentProfile(confidence=1.5)

        with pytest.raises(Exception):
            ExecutionIntentProfile(confidence=-0.1)


# ---------------------------------------------------------------------------
# 2. Serialisation / deserialisation stability
# ---------------------------------------------------------------------------


class TestExecutionIntentProfileSerialisation:
    def test_to_dict_is_json_serialisable(self):
        profile = ExecutionIntentProfile(
            source="openclawd",
            action_level="assist",
            target_ref="notepad.exe",
            confidence=0.75,
        )
        d = profile.to_dict()
        # Should be serialisable without error
        s = json.dumps(d)
        restored = json.loads(s)
        assert restored["action_level"] == "assist"
        assert restored["target_ref"] == "notepad.exe"
        assert restored["confidence"] == 0.75

    def test_to_json_round_trip(self):
        profile = ExecutionIntentProfile(
            source="e2e",
            action_level="execute",
            confidence=0.9,
            safety_constraints=["allowlist_required"],
        )
        j = profile.to_json()
        d = json.loads(j)
        assert d["source"] == "e2e"
        assert d["action_level"] == "execute"
        assert d["confidence"] == 0.9
        assert "allowlist_required" in d["safety_constraints"]

    def test_to_dict_all_expected_keys(self):
        profile = ExecutionIntentProfile()
        d = profile.to_dict()
        expected_keys = {
            "intent_id", "runtime_session_id", "source", "action_level",
            "intent_mode", "target_type", "target_ref", "target_payload",
            "device_scope", "runtime_domain", "confidence", "safety_constraints",
            "origin_state", "notes", "degrade_reason",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_compact_summary_keys(self):
        profile = ExecutionIntentProfile(
            action_level="assist",
            target_ref="notepad.exe",
        )
        s = profile.compact_summary()
        assert "intent_id" in s
        assert "source" in s
        assert "action_level" in s
        assert "intent_mode" in s
        assert "target_type" in s
        assert "target_ref" in s
        assert "device_scope" in s
        assert "runtime_domain" in s
        assert "confidence" in s
        assert "degrade_reason" in s

    def test_compact_summary_values(self):
        profile = ExecutionIntentProfile(
            action_level="execute",
            target_ref="calc.exe",
            device_scope="local",
            confidence=0.9,
        )
        s = profile.compact_summary()
        assert s["action_level"] == "execute"
        assert s["target_ref"] == "calc.exe"
        assert s["device_scope"] == "local"
        assert s["confidence"] == 0.9


# ---------------------------------------------------------------------------
# 3. IntentMode normalisation
# ---------------------------------------------------------------------------


class TestIntentMode:
    @pytest.mark.parametrize("level,expected", [
        ("observe", IntentMode.ADVISORY),
        ("hint", IntentMode.ADVISORY),
        ("assist", IntentMode.ASSISTIVE),
        ("execute", IntentMode.DIRECT),
    ])
    def test_from_action_level(self, level, expected):
        assert IntentMode.from_action_level(level) == expected

    def test_unknown_level_fallback(self):
        assert IntentMode.from_action_level("unknown") == IntentMode.ADVISORY
        assert IntentMode.from_action_level("") == IntentMode.ADVISORY

    def test_case_insensitive(self):
        assert IntentMode.from_action_level("ASSIST") == IntentMode.ASSISTIVE
        assert IntentMode.from_action_level("Execute") == IntentMode.DIRECT


# ---------------------------------------------------------------------------
# 4. build_execution_intent_profile — builder
# ---------------------------------------------------------------------------


class TestBuildExecutionIntentProfile:
    def test_none_continuum_safe(self):
        profile = build_execution_intent_profile(None)
        assert profile.action_level == "observe"
        assert profile.intent_mode == IntentMode.ADVISORY
        assert profile.target_ref is None
        assert profile.confidence == 0.0

    def test_minimal_continuum(self):
        profile = build_execution_intent_profile(
            _MINIMAL_CONTINUUM,
            runtime_session_id="sess-001",
            source="chat",
        )
        assert profile.action_level == "assist"
        assert profile.intent_mode == IntentMode.ASSISTIVE
        assert profile.confidence == 0.75
        assert profile.target_ref == "notepad.exe"
        assert profile.target_type == "app"
        assert profile.runtime_domain == "local"
        assert profile.origin_state == "manifest"
        assert profile.runtime_session_id == "sess-001"
        assert profile.source == "chat"

    def test_full_continuum(self):
        profile = build_execution_intent_profile(_FULL_CONTINUUM)
        assert profile.action_level == "execute"
        assert profile.intent_mode == IntentMode.DIRECT
        assert profile.confidence == 0.92
        assert profile.target_ref == "calc.exe"
        assert profile.runtime_domain == "cross_device"
        assert profile.safety_constraints == ["allowlist_required", "user_confirm"]
        assert profile.target_payload == {"arg": "--debug"}

    def test_entry_mode_local(self):
        profile = build_execution_intent_profile(
            _MINIMAL_CONTINUUM,
            entry_mode="local",
        )
        assert profile.device_scope == "local"

    def test_entry_mode_cross_device(self):
        profile = build_execution_intent_profile(
            _MINIMAL_CONTINUUM,
            entry_mode="cross_device",
        )
        assert profile.device_scope == "remote"

    def test_entry_mode_hybrid(self):
        profile = build_execution_intent_profile(
            _MINIMAL_CONTINUUM,
            entry_mode="hybrid",
        )
        assert profile.device_scope == "multi-device"

    def test_device_scope_inferred_from_runtime_domain(self):
        """When entry_mode is absent, device_scope is inferred from runtime_domain."""
        profile = build_execution_intent_profile(
            _MINIMAL_CONTINUUM,
            entry_mode=None,
        )
        # _MINIMAL_CONTINUUM has runtime_domain=local → device_scope=local
        assert profile.device_scope == "local"

    def test_notes_forwarded(self):
        profile = build_execution_intent_profile(
            None,
            notes="test note",
        )
        assert profile.notes == "test note"

    def test_malformed_continuum_graceful(self):
        """Malformed dicts should not raise."""
        for bad in [{"decision": None}, {"decision": 42}, {"metadata": [1, 2]}, "not a dict"]:
            profile = build_execution_intent_profile(bad)  # type: ignore[arg-type]
            assert profile is not None
            assert profile.action_level == "observe"
            # compact_summary() must always return a dict with the expected keys
            summary = profile.compact_summary()
            assert isinstance(summary, dict)
            assert "action_level" in summary

    def test_origin_state_tri_state_phase_fallback(self):
        """origin_state falls back to tri_state_phase when phase is absent."""
        sc = {
            "decision": {"action_level": "observe", "decision_confidence": 0.0},
            "tri_state_phase": "liminal",
            "metadata": {},
        }
        profile = build_execution_intent_profile(sc)
        assert profile.origin_state == "liminal"

    def test_confidence_bounds(self):
        """Confidence is clamped to [0, 1]."""
        sc = {"decision": {"action_level": "observe", "decision_confidence": 999.0}}
        profile = build_execution_intent_profile(sc)
        assert profile.confidence <= 1.0

        sc2 = {"decision": {"action_level": "observe", "decision_confidence": -5.0}}
        profile2 = build_execution_intent_profile(sc2)
        assert profile2.confidence >= 0.0


# ---------------------------------------------------------------------------
# 5. ExecutionIntentProfile.from_state_continuum
# ---------------------------------------------------------------------------


class TestFromStateContinuum:
    def test_equivalent_to_builder(self):
        p1 = build_execution_intent_profile(
            _MINIMAL_CONTINUUM, runtime_session_id="s1", source="chat"
        )
        p2 = ExecutionIntentProfile.from_state_continuum(
            _MINIMAL_CONTINUUM, runtime_session_id="s1", source="chat"
        )
        # intent_id differs (unique per call); compare all other fields
        d1 = p1.to_dict()
        d2 = p2.to_dict()
        d1.pop("intent_id")
        d2.pop("intent_id")
        assert d1 == d2

    def test_exception_in_build_returns_safe_profile(self):
        """Even if the internal builder raises, from_state_continuum returns a safe profile."""
        with patch(
            "core.execution.intent_profile._build_from_continuum",
            side_effect=RuntimeError("simulated"),
        ):
            profile = ExecutionIntentProfile.from_state_continuum(
                _MINIMAL_CONTINUUM, runtime_session_id="x", source="openclawd"
            )
        assert profile is not None
        assert profile.action_level == "observe"
        assert profile.source == "openclawd"
        assert profile.runtime_session_id == "x"


# ---------------------------------------------------------------------------
# 6. RuntimeProjection integration
# ---------------------------------------------------------------------------


class TestRuntimeProjectionIntegration:
    def _make_continuum_state(self):
        from core.continuum.types import ContinuumPhase, ContinuumState
        return ContinuumState(phase=ContinuumPhase.MANIFEST, coherence=0.7)

    def _make_runtime_projection(self, intent_profile=None):
        """Directly build a RuntimeProjection."""
        from core.continuum.types import TriStatePhase
        from core.projection.runtime_projection import RuntimeProjection
        kwargs = dict(
            tri_state_phase=TriStatePhase.MANIFEST,
            timestamp=1711533600.0,
        )
        if intent_profile is not None:
            kwargs["execution_intent_summary"] = intent_profile.compact_summary()
        return RuntimeProjection(**kwargs)

    def test_projection_without_intent_profile(self):
        proj = self._make_runtime_projection()
        assert proj.execution_intent_summary is None

    def test_projection_with_intent_profile(self):
        profile = build_execution_intent_profile(
            _MINIMAL_CONTINUUM,
            source="openclawd",
        )
        proj = self._make_runtime_projection(intent_profile=profile)
        assert proj.execution_intent_summary is not None
        assert proj.execution_intent_summary["action_level"] == "assist"
        assert proj.execution_intent_summary["target_ref"] == "notepad.exe"

    def test_projection_to_dict_includes_intent_summary(self):
        profile = build_execution_intent_profile(_MINIMAL_CONTINUUM)
        proj = self._make_runtime_projection(intent_profile=profile)
        d = proj.to_dict()
        assert "execution_intent_summary" in d
        assert d["execution_intent_summary"] is not None

    def test_projection_to_dict_without_profile_has_key(self):
        proj = self._make_runtime_projection()
        d = proj.to_dict()
        assert "execution_intent_summary" in d
        assert d["execution_intent_summary"] is None

    def test_projection_json_round_trip_with_intent(self):
        profile = build_execution_intent_profile(_FULL_CONTINUUM)
        proj = self._make_runtime_projection(intent_profile=profile)
        j = proj.to_json()
        restored = json.loads(j)
        assert restored["execution_intent_summary"]["action_level"] == "execute"


# ---------------------------------------------------------------------------
# 7. _run_execution integration via OpenClawd
# ---------------------------------------------------------------------------


class TestOpenClawdRunExecutionIntegration:
    """Verify that _run_execution returns an 'execution_intent' key."""

    def _make_openclawd(self):
        """Create a minimal OpenClawd instance with execution disabled."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        # Set minimal attributes so _run_execution doesn't crash
        oc._decision_executor = None
        oc._config = {}
        return oc

    def test_run_execution_returns_execution_intent_key(self):
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        # Patch _get_decision_executor to return None (executor_unavailable path)
        with patch.object(oc, "_get_decision_executor", return_value=None):
            result = oc._run_execution(None, entry_mode=None)

        assert "execution_intent" in result
        summary = result["execution_intent"]
        assert isinstance(summary, dict)
        assert "intent_id" in summary
        assert "action_level" in summary

    def test_run_execution_intent_reflects_continuum(self):
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        with patch.object(oc, "_get_decision_executor", return_value=None):
            result = oc._run_execution(_MINIMAL_CONTINUUM, entry_mode="local")

        summary = result["execution_intent"]
        assert summary["action_level"] == "assist"
        assert summary["device_scope"] == "local"

    def test_run_execution_does_not_break_existing_keys(self):
        """Existing keys in the result dict must still be present."""
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        with patch.object(oc, "_get_decision_executor", return_value=None):
            result = oc._run_execution(None, entry_mode=None)

        assert "action_taken" in result
        assert "success" in result
        assert "skipped_reason" in result


# ---------------------------------------------------------------------------
# 8. Private helper coverage
# ---------------------------------------------------------------------------


class TestPrivateHelpers:
    @pytest.mark.parametrize("ref,expected", [
        ("https://example.com", "url"),
        ("http://foo.bar/baz", "url"),
        ("notepad.exe", "app"),
        ("setup.bat", "app"),
        ("run.sh", "app"),
        ("device:phone-01", "device"),
        ("dev-phone-02", "device"),
        ("SomeWindow", "app"),
    ])
    def test_infer_target_type(self, ref, expected):
        assert _infer_target_type(ref) == expected

    @pytest.mark.parametrize("mode,expected", [
        ("local", "local"),
        ("cross_device", "remote"),
        ("hybrid", "multi-device"),
        ("unknown", None),
    ])
    def test_entry_mode_to_device_scope(self, mode, expected):
        assert _entry_mode_to_device_scope(mode) == expected

    @pytest.mark.parametrize("domain,expected", [
        ("local", "local"),
        ("cross_device", "remote"),
        ("transition", "local"),
        ("unknown", None),
    ])
    def test_runtime_domain_to_device_scope(self, domain, expected):
        assert _runtime_domain_to_device_scope(domain) == expected
