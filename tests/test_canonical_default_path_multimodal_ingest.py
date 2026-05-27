"""tests/test_canonical_default_path_multimodal_ingest.py
============================================================
Behavioral tests proving that continuous host perception (multimodal ingest)
has been promoted from default-off / optional to the canonical default runtime
path.

These tests address the requirements of the canonical default path promotion PR:

A. Default path behavior change
   - Verify that config.json now has enable_multimodal_ingest=True.
   - Verify the resolved runtime profile is FULL_DEPLOYMENT (not SAFE_DEFAULT).
   - These are real runtime behavior differences, not doc/config changes.

B. Canonical vs compat/fallback path distinction
   - Verify that SAFE_DEFAULT (disabled) is now explicitly an opt-out path,
     not the default.
   - Verify that the canonical default path sentinel exists and is
     machine-verifiable.
   - Verify that the compat/fallback opt-out (explicit False) works correctly
     and is distinct from the canonical default.

C. Default capability activation
   - Verify multimodal_ingest and continuous_host_perception are ACTIVE_MAINLINE
     in the capability status registry.
   - Previously these capabilities were absent from the registry (treated as
     UNKNOWN / non-mainline).

D. User-visible default output
   - Verify the runtime profile summary exposed to callers reflects
     FULL_DEPLOYMENT and enable_multimodal_ingest=True.
   - Verify the ingest bus CAN be started with the canonical default config
     (start_ingest_bus returns True).

Test classes
-------------
1. TestDefaultPathBehaviorChange
   - Proves config.json changed (enable_multimodal_ingest=True).
   - Proves resolved profile is FULL_DEPLOYMENT by default.

2. TestDefaultCapabilityActivation
   - Proves multimodal_ingest and continuous_host_perception are ACTIVE_MAINLINE.
   - Proves the MULTIMODAL_INGEST_IS_ACTIVE_MAINLINE_STATUS sentinel exists.

3. TestCanonicalVsCompatPathDistinction
   - Proves MULTIMODAL_INGEST_CANONICAL_DEFAULT_PATH sentinel exists.
   - Proves SAFE_DEFAULT opt-out path is distinct and explicitly labeled.
   - Proves canonical default != compat/fallback (different profile, different flag).

4. TestUserVisibleDefaultOutput
   - Proves build_multimodal_runtime_profile_summary() reports FULL_DEPLOYMENT.
   - Proves start_ingest_bus() returns True with canonical default config.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict
from unittest.mock import patch

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.json"


def _load_canonical_config() -> Dict[str, Any]:
    """Load the canonical runtime config.json."""
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


# ===========================================================================
# 1. Default path behavior change
# ===========================================================================


class TestDefaultPathBehaviorChange:
    """Prove config.json changed and the resolved profile is FULL_DEPLOYMENT.

    These tests verify the actual default runtime behavior changed, not just
    documentation or comment changes.
    """

    def test_config_json_enable_multimodal_ingest_is_true(self):
        """config.json must have enable_multimodal_ingest=True (canonical default).

        This is the direct behavior change: before this PR, config.json had
        enable_multimodal_ingest=false (SAFE_DEFAULT posture).  After this PR,
        it is true (FULL_DEPLOYMENT canonical default posture).
        """
        cfg = _load_canonical_config()
        assert "enable_multimodal_ingest" in cfg, (
            "config.json must contain enable_multimodal_ingest key"
        )
        assert cfg["enable_multimodal_ingest"] is True, (
            "config.json must have enable_multimodal_ingest=True — "
            "continuous host perception is the canonical default runtime path. "
            "If this assertion fails, the canonical default path promotion has been "
            "reversed; check config.json."
        )

    def test_resolved_profile_is_full_deployment_by_default(self):
        """resolve_multimodal_runtime_profile() must return FULL_DEPLOYMENT by default.

        Before this PR: default resolved to SAFE_DEFAULT (ingest disabled).
        After this PR: default resolves to FULL_DEPLOYMENT (ingest enabled).
        This is a real runtime behavior difference.
        """
        from core.multimodal_runtime_profile import (
            MultimodalRuntimeProfile,
            resolve_multimodal_runtime_profile,
        )

        snapshot = resolve_multimodal_runtime_profile()
        assert snapshot.profile == MultimodalRuntimeProfile.FULL_DEPLOYMENT, (
            "Default runtime profile must be FULL_DEPLOYMENT — "
            "multimodal ingest is the canonical default.  "
            "Got: %s" % snapshot.profile
        )

    def test_resolved_snapshot_enable_multimodal_ingest_true_by_default(self):
        """resolve_multimodal_runtime_profile() must return enable_multimodal_ingest=True."""
        from core.multimodal_runtime_profile import resolve_multimodal_runtime_profile

        snapshot = resolve_multimodal_runtime_profile()
        assert snapshot.enable_multimodal_ingest is True, (
            "Default runtime snapshot must have enable_multimodal_ingest=True. "
            "Got: %s" % snapshot.enable_multimodal_ingest
        )

    def test_default_profile_is_not_safe_default(self):
        """Default resolved profile must NOT be SAFE_DEFAULT.

        Before this PR: SAFE_DEFAULT was the default.
        After this PR: SAFE_DEFAULT is an explicit opt-out only.
        This regression test catches any accidental reversion.
        """
        from core.multimodal_runtime_profile import (
            MultimodalRuntimeProfile,
            resolve_multimodal_runtime_profile,
        )

        snapshot = resolve_multimodal_runtime_profile()
        assert snapshot.profile != MultimodalRuntimeProfile.SAFE_DEFAULT, (
            "Default runtime profile must NOT be SAFE_DEFAULT — "
            "SAFE_DEFAULT is now an explicit opt-out posture, not the default. "
            "Got: %s" % snapshot.profile
        )


# ===========================================================================
# 2. Default capability activation
# ===========================================================================


class TestDefaultCapabilityActivation:
    """Prove multimodal_ingest and continuous_host_perception are ACTIVE_MAINLINE.

    Before this PR: these capabilities were absent from the registry (treated
    as UNKNOWN, non-mainline).
    After this PR: both are explicitly registered as ACTIVE_MAINLINE.
    """

    def test_multimodal_ingest_capability_is_active_mainline(self):
        """multimodal_ingest must be ACTIVE_MAINLINE in the capability status registry."""
        from core.canonical_capability_status import (
            CapabilityRuntimeStatus,
            get_canonical_capability_status_registry,
            is_mainline_active,
        )

        registry = get_canonical_capability_status_registry()
        assert "multimodal_ingest" in registry, (
            "multimodal_ingest must be present in the canonical capability status "
            "registry.  Before this PR it was absent (UNKNOWN).  After this PR "
            "it must be explicitly registered."
        )
        record = registry["multimodal_ingest"]
        assert record.status == CapabilityRuntimeStatus.ACTIVE_MAINLINE, (
            "multimodal_ingest must be ACTIVE_MAINLINE.  Got: %s" % record.status
        )
        assert is_mainline_active("multimodal_ingest"), (
            "is_mainline_active('multimodal_ingest') must return True"
        )

    def test_continuous_host_perception_capability_is_active_mainline(self):
        """continuous_host_perception must be ACTIVE_MAINLINE in the registry."""
        from core.canonical_capability_status import (
            CapabilityRuntimeStatus,
            get_canonical_capability_status_registry,
            is_mainline_active,
        )

        registry = get_canonical_capability_status_registry()
        assert "continuous_host_perception" in registry, (
            "continuous_host_perception must be present in the canonical capability "
            "status registry."
        )
        record = registry["continuous_host_perception"]
        assert record.status == CapabilityRuntimeStatus.ACTIVE_MAINLINE, (
            "continuous_host_perception must be ACTIVE_MAINLINE.  Got: %s" % record.status
        )
        assert is_mainline_active("continuous_host_perception"), (
            "is_mainline_active('continuous_host_perception') must return True"
        )

    def test_active_mainline_status_sentinel_exists(self):
        """MULTIMODAL_INGEST_IS_ACTIVE_MAINLINE_STATUS sentinel must be present."""
        from core.canonical_capability_status import MULTIMODAL_INGEST_IS_ACTIVE_MAINLINE_STATUS

        assert isinstance(MULTIMODAL_INGEST_IS_ACTIVE_MAINLINE_STATUS, str), (
            "MULTIMODAL_INGEST_IS_ACTIVE_MAINLINE_STATUS must be a string sentinel"
        )
        assert "ACTIVE_MAINLINE" in MULTIMODAL_INGEST_IS_ACTIVE_MAINLINE_STATUS, (
            "MULTIMODAL_INGEST_IS_ACTIVE_MAINLINE_STATUS must contain 'ACTIVE_MAINLINE'"
        )

    def test_webrtc_remains_experimental_not_promoted(self):
        """WebRTC must still be EXPERIMENTAL — this PR only promotes multimodal_ingest."""
        from core.canonical_capability_status import (
            CapabilityRuntimeStatus,
            get_canonical_capability_status_registry,
        )

        registry = get_canonical_capability_status_registry()
        assert registry["webrtc"].status == CapabilityRuntimeStatus.EXPERIMENTAL, (
            "webrtc must remain EXPERIMENTAL — this PR only promotes "
            "multimodal_ingest and continuous_host_perception to ACTIVE_MAINLINE."
        )


# ===========================================================================
# 3. Canonical vs compat/fallback path distinction
# ===========================================================================


class TestCanonicalVsCompatPathDistinction:
    """Prove canonical default path is explicitly distinct from compat/fallback.

    The key distinction introduced by this PR:
    - Canonical default path: enable_multimodal_ingest=True (config.json), FULL_DEPLOYMENT
    - Compat/fallback opt-out: explicit enable_multimodal_ingest=False, SAFE_DEFAULT
    """

    def setup_method(self):
        # Reset singleton before each test, consistent with TestIngestRuntimeModule
        # in test_pr10_multimodal_ingest_wiring.py.
        import core.multimodal.ingest_runtime as _ir
        _ir._ingest_bus = None
        _ir._ingest_task = None

    def teardown_method(self):
        import core.multimodal.ingest_runtime as _ir
        _ir._ingest_bus = None
        _ir._ingest_task = None

    def test_canonical_default_path_sentinel_exists(self):
        """MULTIMODAL_INGEST_CANONICAL_DEFAULT_PATH sentinel must be importable."""
        from core.multimodal.ingest_runtime import MULTIMODAL_INGEST_CANONICAL_DEFAULT_PATH

        assert isinstance(MULTIMODAL_INGEST_CANONICAL_DEFAULT_PATH, str), (
            "MULTIMODAL_INGEST_CANONICAL_DEFAULT_PATH must be a string sentinel"
        )
        assert "CANONICAL_DEFAULT_PATH" in MULTIMODAL_INGEST_CANONICAL_DEFAULT_PATH, (
            "Sentinel must contain 'CANONICAL_DEFAULT_PATH' for machine-verifiability"
        )

    def test_explicit_disable_produces_safe_default_not_full_deployment(self):
        """Explicit opt-out (enable_multimodal_ingest=False) must resolve SAFE_DEFAULT.

        This test distinguishes the compat/fallback path from canonical default:
        - Canonical default: FULL_DEPLOYMENT (ingest True)
        - Explicit opt-out: SAFE_DEFAULT (ingest False)
        """
        from core.multimodal_runtime_profile import (
            MultimodalRuntimeProfile,
            resolve_multimodal_runtime_profile,
        )

        opt_out = resolve_multimodal_runtime_profile(
            config={
                "enable_multimodal_ingest": False,
                "enable_webrtc_session_manager": False,
                "debug_desktop_presence_runtime": False,
                "state_event_bus_log_all": False,
            },
            env={},
        )
        assert opt_out.profile == MultimodalRuntimeProfile.SAFE_DEFAULT, (
            "Explicit opt-out must resolve SAFE_DEFAULT, not FULL_DEPLOYMENT"
        )
        assert opt_out.enable_multimodal_ingest is False, (
            "Explicit opt-out must have enable_multimodal_ingest=False"
        )

    def test_canonical_vs_compat_profiles_are_distinct(self):
        """Canonical default profile must differ from compat/fallback profile."""
        from core.multimodal_runtime_profile import (
            MultimodalRuntimeProfile,
            resolve_multimodal_runtime_profile,
        )

        canonical = resolve_multimodal_runtime_profile()
        compat = resolve_multimodal_runtime_profile(
            config={"enable_multimodal_ingest": False, "enable_webrtc_session_manager": False},
            env={},
        )

        assert canonical.profile != compat.profile, (
            "Canonical default profile (%s) must differ from compat/fallback "
            "profile (%s)" % (canonical.profile, compat.profile)
        )
        assert canonical.enable_multimodal_ingest is True
        assert compat.enable_multimodal_ingest is False

    def test_safe_default_profile_enum_preserved_as_opt_out(self):
        """SAFE_DEFAULT profile enum must still exist as a named opt-out posture."""
        from core.multimodal_runtime_profile import MultimodalRuntimeProfile

        assert hasattr(MultimodalRuntimeProfile, "SAFE_DEFAULT"), (
            "MultimodalRuntimeProfile must still have SAFE_DEFAULT — "
            "it is preserved as an explicit opt-out posture"
        )
        assert MultimodalRuntimeProfile.SAFE_DEFAULT.value == "safe_default"

    def test_start_ingest_bus_skips_on_explicit_disable(self):
        """start_ingest_bus() must return False when explicitly disabled (compat path)."""
        from core.multimodal.ingest_runtime import start_ingest_bus, get_ingest_bus

        with patch("core.unified_config.config", {"enable_multimodal_ingest": False}):
            result = start_ingest_bus()

        assert result is False, (
            "start_ingest_bus() must return False when enable_multimodal_ingest=False "
            "(explicit compat/fallback opt-out path)"
        )
        assert get_ingest_bus() is None, (
            "Ingest bus must not be started on the explicit opt-out (compat) path"
        )

    def test_start_ingest_bus_starts_on_canonical_default(self):
        """start_ingest_bus() must start when called with canonical default config (True)."""
        from core.multimodal.ingest_runtime import start_ingest_bus, get_ingest_bus

        with patch("core.unified_config.config", {"enable_multimodal_ingest": True}):
            with patch("core.multimodal.ingest_runtime._schedule_pipeline"):
                result = start_ingest_bus()

        assert result is True, (
            "start_ingest_bus() must return True on canonical default path "
            "(enable_multimodal_ingest=True)"
        )
        assert get_ingest_bus() is not None, (
            "Ingest bus must be started on the canonical default path"
        )


# ===========================================================================
# 4. User-visible default output
# ===========================================================================


class TestUserVisibleDefaultOutput:
    """Prove the default user-path output reflects the canonical default change.

    The runtime profile summary is the user-facing / operator-facing signal
    about the current runtime posture.  These tests verify the default output
    changed in a meaningful, observable way.
    """

    def test_runtime_profile_summary_reports_full_deployment_by_default(self):
        """build_multimodal_runtime_profile_summary() must report FULL_DEPLOYMENT by default."""
        from core.multimodal_runtime_profile import build_multimodal_runtime_profile_summary

        summary = build_multimodal_runtime_profile_summary()
        assert summary["profile"] == "full_deployment", (
            "Default runtime profile summary must report 'full_deployment'. "
            "Got: %s" % summary["profile"]
        )
        assert summary["enable_multimodal_ingest"] is True, (
            "Default runtime profile summary must have enable_multimodal_ingest=True"
        )
        assert summary["is_full_deployment"] is True, (
            "Default runtime profile summary must have is_full_deployment=True"
        )
        assert summary["is_safe_default"] is False, (
            "Default runtime profile summary must have is_safe_default=False — "
            "SAFE_DEFAULT is no longer the canonical default posture"
        )

    def test_runtime_profile_summary_reports_safe_default_on_explicit_opt_out(self):
        """Profile summary must report SAFE_DEFAULT when explicitly disabled."""
        from core.multimodal_runtime_profile import build_multimodal_runtime_profile_summary

        summary = build_multimodal_runtime_profile_summary(
            config={
                "enable_multimodal_ingest": False,
                "enable_webrtc_session_manager": False,
                "debug_desktop_presence_runtime": False,
                "state_event_bus_log_all": False,
            },
            env={},
        )
        assert summary["profile"] == "safe_default", (
            "Explicit opt-out profile summary must report 'safe_default'"
        )
        assert summary["enable_multimodal_ingest"] is False
        assert summary["is_safe_default"] is True
        assert summary["is_full_deployment"] is False

    def test_multimodal_ingest_is_mainline_active_predicate(self):
        """is_mainline_active('multimodal_ingest') must return True."""
        from core.canonical_capability_status import is_mainline_active

        assert is_mainline_active("multimodal_ingest") is True, (
            "is_mainline_active('multimodal_ingest') must return True — "
            "this capability has been promoted to ACTIVE_MAINLINE"
        )

    def test_continuous_host_perception_is_mainline_active_predicate(self):
        """is_mainline_active('continuous_host_perception') must return True."""
        from core.canonical_capability_status import is_mainline_active

        assert is_mainline_active("continuous_host_perception") is True, (
            "is_mainline_active('continuous_host_perception') must return True — "
            "this capability has been promoted to ACTIVE_MAINLINE"
        )

    def test_capability_registry_rationale_references_canonical_default(self):
        """multimodal_ingest registry entry rationale must mention canonical default."""
        from core.canonical_capability_status import get_canonical_capability_status_registry

        registry = get_canonical_capability_status_registry()
        record = registry["multimodal_ingest"]
        rationale_lower = record.rationale.lower()
        assert "canonical" in rationale_lower or "default" in rationale_lower, (
            "multimodal_ingest registry rationale must mention canonical/default — "
            "the rationale must document the promotion, not just the capability. "
            "Got: %s" % record.rationale
        )
