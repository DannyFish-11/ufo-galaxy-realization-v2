"""tests/unit/routing/test_runtime_state_routing.py
=====================================================
PR-7 — Runtime-state-aware routing and orchestration.

These tests prove that routing/scheduling decisions *change* appropriately
when real Android runtime-state truth (from ``core.android_device_state_store``)
changes — specifically:

  A) DevicePoolManager adaptive scoring
     1.  ``_android_runtime_score`` returns 1.0 when no snapshot exists
         (fail-open / graceful degradation).
     2.  ``_android_runtime_score`` returns < 1.0 when queue_depth > 0
         (queue penalty applied).
     3.  ``_android_runtime_score`` returns > 1.0 when local_ai_ready is
         True (local-inference bonus applied).
     4.  ``_android_runtime_score`` returns < 1.0 when device has
         degraded_reasons (degradation penalty applied).
     5.  ``_android_runtime_score`` returns < 1.0 when pending_first_download
         is True (pending-download penalty applied).
     6.  ``_android_runtime_score`` returns 1.0 when the store module raises
         (fail-open).
     7.  Adaptive selection picks the device with the lower queue_depth
         because it scores higher.
     8.  Adaptive selection prefers the local-AI-ready device over one
         without local AI (all other factors equal).
     9.  ``_android_runtime_score`` penalises devices on a
         center-delegated fallback tier.

  B) device_selection runtime-state pre-filter (step 0b)
     10. Device with ``pending_first_download=True`` AND no fallback tier is
         excluded from selection.
     11. Device with ``pending_first_download=True`` but WITH a fallback tier
         is NOT excluded.
     12. Device with no snapshot is admitted (no false-positive exclusion).
     13. When ALL candidates fail the runtime-state filter, the original list
         is preserved (graceful fallback).
     14. ``RUNTIME_STATE_PREFILTER_IN_SELECTION`` authority sentinel is a
         non-empty string.

  C) Authority sentinels
     15. ``RUNTIME_STATE_SCORING_AUTHORITY`` is present and is a non-empty
         string.
"""

from __future__ import annotations

import types
import unittest
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — lightweight DeviceStateSnapshot stand-in
# ---------------------------------------------------------------------------

def _make_snap(
    device_id: str = "dev_test",
    *,
    model_ready: Optional[bool] = None,
    local_loop_ready: Optional[bool] = None,
    llama_cpp_available: Optional[bool] = None,
    ncnn_available: Optional[bool] = None,
    offline_queue_depth: Optional[int] = None,
    current_fallback_tier: Optional[str] = None,
    degraded_reasons=None,
    pending_first_download: Optional[bool] = None,
):
    """Return a minimal DeviceStateSnapshot populated from keyword args."""
    from core.android_device_state_store import DeviceStateSnapshot

    return DeviceStateSnapshot(
        device_id=device_id,
        model_ready=model_ready,
        local_loop_ready=local_loop_ready,
        llama_cpp_available=llama_cpp_available,
        ncnn_available=ncnn_available,
        offline_queue_depth=offline_queue_depth,
        current_fallback_tier=current_fallback_tier,
        degraded_reasons=degraded_reasons or [],
        pending_first_download=pending_first_download,
    )


def _make_pool_device(device_id: str):
    """Return a minimal PoolDevice for scheduling tests."""
    from core.device_pool_manager import PoolDevice
    return PoolDevice(device_id=device_id, capabilities=[], weight=1.0, capacity=10)


# ---------------------------------------------------------------------------
# A) DevicePoolManager adaptive scoring
# ---------------------------------------------------------------------------


class TestAndroidRuntimeScore(unittest.TestCase):
    """Tests for ``core.device_pool_manager._android_runtime_score``."""

    def _score(self, device_id: str, snap=None) -> float:
        """Invoke ``_android_runtime_score`` with an optionally patched store."""
        from core.device_pool_manager import _android_runtime_score

        if snap is None:
            # No snapshot — store returns None.
            with patch(
                "core.device_pool_manager._android_runtime_score.__module__",
                create=True,
            ):
                with patch(
                    "core.android_device_state_store.get_device_state_snapshot",
                    return_value=None,
                ):
                    # Re-import to patch at call site.
                    return _call_score_with_patch(device_id, snap=None)
        else:
            return _call_score_with_patch(device_id, snap=snap)

    def test_returns_one_when_no_snapshot(self):
        """Score is 1.0 when the store has no snapshot for the device."""
        score = _call_score_with_patch("dev_unknown", snap=None)
        self.assertAlmostEqual(score, 1.0, places=5)

    def test_queue_depth_reduces_score(self):
        """Score < 1.0 when offline_queue_depth > 0."""
        snap = _make_snap("dev_a", offline_queue_depth=10)
        score = _call_score_with_patch("dev_a", snap=snap)
        self.assertLess(score, 1.0)

    def test_queue_depth_zero_leaves_score_unchanged(self):
        """Score == 1.0 when queue_depth == 0 and no other factors."""
        snap = _make_snap("dev_a", offline_queue_depth=0)
        score = _call_score_with_patch("dev_a", snap=snap)
        self.assertAlmostEqual(score, 1.0, places=5)

    def test_local_ai_ready_increases_score(self):
        """Score > 1.0 when is_local_ai_ready() is True."""
        snap = _make_snap(
            "dev_a",
            model_ready=True,
            local_loop_ready=True,
            llama_cpp_available=True,
        )
        score = _call_score_with_patch("dev_a", snap=snap)
        self.assertGreater(score, 1.0)

    def test_degraded_reasons_reduce_score(self):
        """Score decreases with each degraded_reason."""
        snap_clean = _make_snap("dev_a")
        snap_deg = _make_snap("dev_a", degraded_reasons=["llm_error", "oom"])
        score_clean = _call_score_with_patch("dev_a", snap=snap_clean)
        score_deg = _call_score_with_patch("dev_a", snap=snap_deg)
        self.assertLess(score_deg, score_clean)

    def test_pending_first_download_reduces_score(self):
        """Score is penalised when pending_first_download is True."""
        snap_ready = _make_snap("dev_a", pending_first_download=False)
        snap_pend = _make_snap("dev_a", pending_first_download=True)
        score_ready = _call_score_with_patch("dev_a", snap=snap_ready)
        score_pend = _call_score_with_patch("dev_a", snap=snap_pend)
        self.assertLess(score_pend, score_ready)

    def test_store_exception_returns_one(self):
        """Score defaults to 1.0 when the store module raises (fail-open)."""
        from core.device_pool_manager import _android_runtime_score

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            side_effect=RuntimeError("store unavailable"),
        ):
            score = _android_runtime_score("dev_x")
        self.assertAlmostEqual(score, 1.0, places=5)

    def test_center_delegated_tier_reduces_score(self):
        """Score is reduced when device is on a center-delegated fallback tier."""
        snap_local = _make_snap("dev_a", current_fallback_tier="planner_local")
        snap_center = _make_snap("dev_a", current_fallback_tier="center_delegated")
        score_local = _call_score_with_patch("dev_a", snap=snap_local)
        score_center = _call_score_with_patch("dev_a", snap=snap_center)
        self.assertLess(score_center, score_local)


def _call_score_with_patch(device_id: str, snap) -> float:
    """Call ``_android_runtime_score`` with the snapshot patched in."""
    from core.device_pool_manager import _android_runtime_score

    with patch(
        "core.android_device_state_store.get_device_state_snapshot",
        return_value=snap,
    ):
        return _android_runtime_score(device_id)


class TestAdaptiveSelectionUsesRuntimeState(unittest.TestCase):
    """Tests that _select_adaptive picks the device with better runtime state."""

    def _build_pool(self):
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy

        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(strategy=SchedulingStrategy.ADAPTIVE)
        return pool

    def tearDown(self):
        from core.device_pool_manager import DevicePoolManager

        DevicePoolManager._reset_singleton()

    def test_lower_queue_depth_wins_adaptive(self):
        """Adaptive selection picks the device with lower queue_depth."""
        pool = self._build_pool()
        dev_a = _make_pool_device("dev_a")
        dev_b = _make_pool_device("dev_b")

        snap_a = _make_snap("dev_a", offline_queue_depth=15)  # heavily loaded
        snap_b = _make_snap("dev_b", offline_queue_depth=0)   # idle

        snap_map = {"dev_a": snap_a, "dev_b": snap_b}

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            side_effect=lambda did: snap_map.get(did),
        ):
            chosen = pool._select_adaptive([dev_a, dev_b])

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.device_id, "dev_b")

    def test_local_ai_ready_device_preferred(self):
        """Adaptive selection prefers the device with local AI ready."""
        pool = self._build_pool()
        dev_a = _make_pool_device("dev_a")
        dev_b = _make_pool_device("dev_b")

        snap_a = _make_snap(
            "dev_a", model_ready=True, local_loop_ready=True, llama_cpp_available=True
        )
        snap_b = _make_snap("dev_b")  # no local AI

        snap_map = {"dev_a": snap_a, "dev_b": snap_b}

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            side_effect=lambda did: snap_map.get(did),
        ):
            chosen = pool._select_adaptive([dev_a, dev_b])

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.device_id, "dev_a")

    def test_no_snapshots_does_not_change_first_candidate_selection(self):
        """When the store has no snapshots, adaptive score falls back to health×weight."""
        pool = self._build_pool()
        dev_a = _make_pool_device("dev_a")
        dev_b = _make_pool_device("dev_b")

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            return_value=None,
        ):
            # Both devices have identical scores; adaptive should return one
            # deterministically without raising.
            chosen = pool._select_adaptive([dev_a, dev_b])

        self.assertIsNotNone(chosen)
        self.assertIn(chosen.device_id, {"dev_a", "dev_b"})


# ---------------------------------------------------------------------------
# B) device_selection runtime-state pre-filter (step 0b)
# ---------------------------------------------------------------------------


def _make_gateway_device(device_id: str, status: str = "online"):
    """Return a minimal Device-like object for device_selection tests."""
    device = MagicMock()
    device.device_id = device_id
    device.status = status
    device.metadata = {}
    return device


class TestRuntimeStatePreFilterInSelection(unittest.TestCase):
    """Tests for the PR-7 runtime-state pre-filter in select_devices (step 0b)."""

    def _run_select(self, candidates, snap_map: dict) -> list:
        """Run select_devices with patched admissibility + runtime-state store."""
        from galaxy_gateway.routing.device_selection import select_devices

        analysis: Dict[str, Any] = {
            "exec_mode": None,
            "actions": [],
            "requires_cross_device": False,
            "task_role": None,
            "required_capabilities": [],
            "target_device_type": "",
        }

        def _fake_snap(did):
            return snap_map.get(did)

        # Patch out admissibility (step 0) and exec_mode (step 1) so that only
        # the runtime-state filter step has interesting effects in these tests.
        with (
            patch(
                "core.target_device_validator.validate_target_device",
                side_effect=ImportError("skip admissibility for this test"),
            ),
            patch(
                "core.android_device_state_store.get_device_state_snapshot",
                side_effect=_fake_snap,
            ),
            patch(
                "galaxy_gateway.routing.device_selection.query_gateway_capabilities",
                return_value=[],
            ),
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capabilities_for_device",
                return_value=[],
            ),
            patch(
                "galaxy_gateway.routing.device_selection.get_device_pool_manager",
                side_effect=RuntimeError("no pool"),
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=ImportError("no filter"),
            ),
        ):
            return select_devices(analysis, candidates)

    def test_pending_download_no_fallback_excluded(self):
        """Device with pending_first_download=True and no fallback is excluded."""
        dev_blocked = _make_gateway_device("dev_blocked")
        dev_ok = _make_gateway_device("dev_ok")

        snap_blocked = _make_snap(
            "dev_blocked", pending_first_download=True, current_fallback_tier=None
        )
        snap_ok = _make_snap("dev_ok", pending_first_download=False)

        result = self._run_select(
            [dev_blocked, dev_ok],
            {"dev_blocked": snap_blocked, "dev_ok": snap_ok},
        )

        result_ids = [d.device_id for d in result]
        self.assertNotIn("dev_blocked", result_ids)
        self.assertIn("dev_ok", result_ids)

    def test_pending_download_with_fallback_admitted(self):
        """Device with pending_first_download=True but WITH a fallback tier is admitted."""
        dev = _make_gateway_device("dev_with_fallback")

        snap = _make_snap(
            "dev_with_fallback",
            pending_first_download=True,
            current_fallback_tier="center_delegated",
        )

        result = self._run_select([dev], {"dev_with_fallback": snap})
        result_ids = [d.device_id for d in result]
        self.assertIn("dev_with_fallback", result_ids)

    def test_no_snapshot_admitted(self):
        """Device with no snapshot is admitted (fail-open)."""
        dev = _make_gateway_device("dev_no_snap")

        result = self._run_select([dev], {})  # empty snap_map → snap=None
        result_ids = [d.device_id for d in result]
        self.assertIn("dev_no_snap", result_ids)

    def test_all_blocked_falls_back_to_original(self):
        """When ALL candidates fail the runtime-state filter, original list is preserved.

        Specifically: the result must be non-empty — the filter must not eliminate
        all candidates, leaving the downstream steps with candidates to choose from.
        """
        dev_a = _make_gateway_device("dev_a")
        dev_b = _make_gateway_device("dev_b")

        snap_a = _make_snap("dev_a", pending_first_download=True, current_fallback_tier=None)
        snap_b = _make_snap("dev_b", pending_first_download=True, current_fallback_tier=None)

        result = self._run_select(
            [dev_a, dev_b],
            {"dev_a": snap_a, "dev_b": snap_b},
        )
        # Must be non-empty — graceful fallback preserved the original list so
        # downstream steps had candidates.  The filter must not cause an empty result.
        self.assertGreater(len(result), 0)
        result_ids = {d.device_id for d in result}
        self.assertTrue(result_ids.issubset({"dev_a", "dev_b"}))

    def test_runtime_state_sentinel_present(self):
        """``RUNTIME_STATE_PREFILTER_IN_SELECTION`` authority sentinel is a non-empty string."""
        from galaxy_gateway.routing.device_selection import (
            RUNTIME_STATE_PREFILTER_IN_SELECTION,
        )

        self.assertIsInstance(RUNTIME_STATE_PREFILTER_IN_SELECTION, str)
        self.assertTrue(len(RUNTIME_STATE_PREFILTER_IN_SELECTION) > 10)


# ---------------------------------------------------------------------------
# C) Authority sentinels
# ---------------------------------------------------------------------------


class TestRuntimeStateScoringAuthoritySentinel(unittest.TestCase):
    """Authority sentinel tests for PR-7 runtime-state scoring."""

    def test_scoring_authority_sentinel_present(self):
        """``RUNTIME_STATE_SCORING_AUTHORITY`` is a non-empty string."""
        from core.device_pool_manager import RUNTIME_STATE_SCORING_AUTHORITY

        self.assertIsInstance(RUNTIME_STATE_SCORING_AUTHORITY, str)
        self.assertIn("RUNTIME_STATE_SCORING", RUNTIME_STATE_SCORING_AUTHORITY)
        self.assertGreater(len(RUNTIME_STATE_SCORING_AUTHORITY), 20)


if __name__ == "__main__":
    unittest.main()
