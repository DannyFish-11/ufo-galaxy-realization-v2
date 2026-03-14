"""
tests/test_smart_scheduler.py
===============================

Unit tests for core.control_plane.smart_scheduler.
"""

import pytest

from core.control_plane.smart_scheduler import (
    CapabilityDescriptor,
    DeviceScore,
    DeviceScoreInput,
    DeviceScoringEngine,
    DeviceStatus,
    SandboxLevel,
    ScoringWeights,
)


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_device_score_input_defaults(self):
        d = DeviceScoreInput(device_id="d1")
        assert d.status == DeviceStatus.ONLINE
        assert d.ping_latency_ms == 0.0
        assert d.load_pct == 0.0
        assert d.sandbox_level == SandboxLevel.NONE
        assert d.capabilities == []

    def test_scoring_weights_defaults(self):
        w = ScoringWeights()
        assert abs(w.capability - 0.40) < 1e-9
        assert abs(w.latency - 0.25) < 1e-9
        assert abs(w.load - 0.25) < 1e-9
        assert abs(w.sandbox - 0.10) < 1e-9

    def test_scoring_weights_zero_raises(self):
        with pytest.raises(Exception):
            ScoringWeights(capability=0.0, latency=0.0, load=0.0, sandbox=0.0)

    def test_scoring_weights_negative_raises(self):
        with pytest.raises(Exception):
            ScoringWeights(capability=-1.0)

    def test_capability_descriptor(self):
        cap = CapabilityDescriptor(name="screen", version="1.0", metadata={"res": "1080p"})
        assert cap.name == "screen"
        assert cap.metadata["res"] == "1080p"

    def test_sandbox_level_ordering(self):
        assert SandboxLevel.NONE < SandboxLevel.BASIC
        assert SandboxLevel.BASIC < SandboxLevel.STANDARD
        assert SandboxLevel.STRICT < SandboxLevel.MAXIMUM


# ---------------------------------------------------------------------------
# Component score helpers
# ---------------------------------------------------------------------------

class TestComponentScores:
    def setup_method(self):
        self.engine = DeviceScoringEngine()

    def test_capability_score_perfect_match(self):
        s = self.engine._capability_score(["screen", "touch"], ["screen", "touch", "camera"])
        assert s == 1.0

    def test_capability_score_partial(self):
        s = self.engine._capability_score(["screen", "touch"], ["screen"])
        assert abs(s - 0.5) < 1e-9

    def test_capability_score_empty_required(self):
        assert self.engine._capability_score([], ["screen"]) == 1.0

    def test_capability_score_no_match(self):
        assert self.engine._capability_score(["gps"], ["screen"]) == 0.0

    def test_latency_score_zero_ms(self):
        assert self.engine._latency_score(0.0) == 1.0

    def test_latency_score_ceiling(self):
        assert self.engine._latency_score(self.engine.latency_ceiling_ms) == 0.0

    def test_latency_score_over_ceiling(self):
        assert self.engine._latency_score(9999.0) == 0.0

    def test_latency_score_midpoint(self):
        s = self.engine._latency_score(self.engine.latency_ceiling_ms / 2)
        assert abs(s - 0.5) < 1e-6

    def test_load_score_zero(self):
        assert self.engine._load_score(0.0) == 1.0

    def test_load_score_full(self):
        assert self.engine._load_score(100.0) == 0.0

    def test_load_score_half(self):
        assert abs(self.engine._load_score(50.0) - 0.5) < 1e-9

    def test_sandbox_score_none(self):
        assert self.engine._sandbox_score(SandboxLevel.NONE) == 1.0

    def test_sandbox_score_maximum(self):
        assert self.engine._sandbox_score(SandboxLevel.MAXIMUM) == 0.0

    def test_sandbox_score_standard(self):
        s = self.engine._sandbox_score(SandboxLevel.STANDARD)
        assert 0.0 < s < 1.0


# ---------------------------------------------------------------------------
# score_device tests
# ---------------------------------------------------------------------------

class TestScoreDevice:
    def setup_method(self):
        self.engine = DeviceScoringEngine()

    def _perfect_device(self, device_id="d1") -> DeviceScoreInput:
        return DeviceScoreInput(
            device_id=device_id,
            status=DeviceStatus.ONLINE,
            ping_latency_ms=0.0,
            load_pct=0.0,
            sandbox_level=SandboxLevel.NONE,
            capabilities=["screen", "touch", "keyboard"],
        )

    def test_perfect_device_high_score(self):
        score = self.engine.score_device(
            self._perfect_device(), required_capabilities=["screen"]
        )
        assert score.eligible
        assert score.total > 0.8

    def test_offline_device_ineligible(self):
        d = self._perfect_device()
        d.status = DeviceStatus.OFFLINE
        score = self.engine.score_device(d)
        assert not score.eligible
        assert score.total == 0.0
        assert score.disqualify_reason is not None

    def test_maintenance_device_ineligible(self):
        d = self._perfect_device()
        d.status = DeviceStatus.MAINTENANCE
        score = self.engine.score_device(d)
        assert not score.eligible

    def test_missing_required_capability_ineligible(self):
        d = DeviceScoreInput(
            device_id="d2",
            capabilities=["screen"],
        )
        score = self.engine.score_device(d, required_capabilities=["screen", "gps"])
        assert not score.eligible
        assert "gps" in score.disqualify_reason

    def test_partial_capability_allowed_when_not_strict(self):
        engine = DeviceScoringEngine(require_all_capabilities=False)
        d = DeviceScoreInput(
            device_id="d3",
            capabilities=["screen"],
        )
        score = engine.score_device(d, required_capabilities=["screen", "gps"])
        assert score.eligible
        assert score.capability_score == 0.5

    def test_no_required_capabilities(self):
        score = self.engine.score_device(self._perfect_device())
        assert score.eligible
        assert score.capability_score == 1.0

    def test_high_latency_lowers_score(self):
        low_lat = DeviceScoreInput(
            device_id="low", ping_latency_ms=50.0, capabilities=["screen"]
        )
        high_lat = DeviceScoreInput(
            device_id="high", ping_latency_ms=1500.0, capabilities=["screen"]
        )
        s_low = self.engine.score_device(low_lat, required_capabilities=["screen"])
        s_high = self.engine.score_device(high_lat, required_capabilities=["screen"])
        assert s_low.total > s_high.total

    def test_high_load_lowers_score(self):
        idle = DeviceScoreInput(device_id="idle", load_pct=5.0, capabilities=["x"])
        busy = DeviceScoreInput(device_id="busy", load_pct=90.0, capabilities=["x"])
        s_idle = self.engine.score_device(idle, required_capabilities=["x"])
        s_busy = self.engine.score_device(busy, required_capabilities=["x"])
        assert s_idle.total > s_busy.total

    def test_score_fields_bounded(self):
        d = self._perfect_device()
        score = self.engine.score_device(d, required_capabilities=["screen"])
        assert 0.0 <= score.capability_score <= 1.0
        assert 0.0 <= score.latency_score <= 1.0
        assert 0.0 <= score.load_score <= 1.0
        assert 0.0 <= score.sandbox_score <= 1.0

    def test_deterministic(self):
        d = self._perfect_device()
        s1 = self.engine.score_device(d, required_capabilities=["screen"])
        s2 = self.engine.score_device(d, required_capabilities=["screen"])
        assert s1.total == s2.total


# ---------------------------------------------------------------------------
# select_best_device tests
# ---------------------------------------------------------------------------

class TestSelectBestDevice:
    def setup_method(self):
        self.engine = DeviceScoringEngine()

    def test_select_best_empty_list(self):
        assert self.engine.select_best_device([]) is None

    def test_select_best_single_eligible(self):
        d = DeviceScoreInput(device_id="d1", capabilities=["screen"])
        best = self.engine.select_best_device([d], required_capabilities=["screen"])
        assert best is not None
        assert best.device_id == "d1"

    def test_select_best_among_multiple(self):
        fast = DeviceScoreInput(
            device_id="fast", ping_latency_ms=10.0, load_pct=5.0,
            capabilities=["screen", "touch"],
        )
        slow = DeviceScoreInput(
            device_id="slow", ping_latency_ms=1000.0, load_pct=80.0,
            capabilities=["screen", "touch"],
        )
        best = self.engine.select_best_device(
            [fast, slow], required_capabilities=["screen"]
        )
        assert best is not None
        assert best.device_id == "fast"

    def test_select_best_no_eligible(self):
        d = DeviceScoreInput(device_id="d_off", status=DeviceStatus.OFFLINE)
        assert self.engine.select_best_device([d]) is None

    def test_select_best_tie_break_is_deterministic(self):
        # Two identical devices — lexicographically larger device_id wins
        d_a = DeviceScoreInput(device_id="device_a", capabilities=["x"])
        d_b = DeviceScoreInput(device_id="device_b", capabilities=["x"])
        best_ab = self.engine.select_best_device(
            [d_a, d_b], required_capabilities=["x"]
        )
        best_ba = self.engine.select_best_device(
            [d_b, d_a], required_capabilities=["x"]
        )
        # Same winner regardless of input order
        assert best_ab.device_id == best_ba.device_id


# ---------------------------------------------------------------------------
# rank_devices tests
# ---------------------------------------------------------------------------

class TestRankDevices:
    def test_rank_order(self):
        engine = DeviceScoringEngine()
        fast = DeviceScoreInput(
            device_id="fast", ping_latency_ms=10.0, capabilities=["s"]
        )
        slow = DeviceScoreInput(
            device_id="slow", ping_latency_ms=1800.0, capabilities=["s"]
        )
        ranked = engine.rank_devices([fast, slow], required_capabilities=["s"])
        assert ranked[0].device_id == "fast"
        assert ranked[1].device_id == "slow"

    def test_ineligible_appended_last(self):
        engine = DeviceScoringEngine()
        good = DeviceScoreInput(device_id="good", capabilities=["s"])
        bad = DeviceScoreInput(
            device_id="bad", status=DeviceStatus.OFFLINE, capabilities=["s"]
        )
        ranked = engine.rank_devices([bad, good], required_capabilities=["s"])
        assert ranked[0].device_id == "good"
        assert ranked[-1].device_id == "bad"
        assert not ranked[-1].eligible

    def test_custom_weights(self):
        # Heavily weight latency; other factors minimal
        weights = ScoringWeights(
            capability=0.01, latency=0.97, load=0.01, sandbox=0.01
        )
        engine = DeviceScoringEngine(weights=weights)
        nearby = DeviceScoreInput(
            device_id="near", ping_latency_ms=1.0, load_pct=90.0,
            capabilities=["x"],
        )
        far = DeviceScoreInput(
            device_id="far", ping_latency_ms=1900.0, load_pct=0.0,
            capabilities=["x"],
        )
        ranked = engine.rank_devices([nearby, far], required_capabilities=["x"])
        assert ranked[0].device_id == "near"
