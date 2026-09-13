"""动手之前先就「该谁做」达成一致。

这组测试钉的是五个相位的**失败语义** —— 共识层的价值一多半在那张表里:
每一种失败算什么,而不是留给实现者临场发挥。
"""

from __future__ import annotations

from core.coordination_consensus import (
    Commitment,
    DeclineReason,
    decide,
    is_single_local_candidate,
    pick_execution_surface,
    usable_commitments,
)
from core.coordination_preflight import DeviceFacts

NOW = 1_000_000


def _dev(did, tier="full_runtime", trust="allowed"):
    return DeviceFacts(device_id=did, capability_tier=tier, trust_result=trust)


def _ok(did, ttl=5000, level="uia"):
    return Commitment(device_id=did, accepted=True, valid_until_ms=NOW + ttl, best_level=level)


# ── 承诺有效期 ────────────────────────────────────────────────────────────────
def test_an_expired_commitment_does_not_count():
    # 设备说"我能做"时看到的那一屏,几秒之后可能已经不在了。
    stale = Commitment(device_id="a", accepted=True, valid_until_ms=NOW - 1)
    assert stale.is_usable(NOW) is False
    assert usable_commitments([stale], NOW) == []


def test_a_commitment_without_an_expiry_does_not_count():
    """没有有效期 = 让中心去赌。这个模块的立场是不赌。"""
    forever = Commitment(device_id="a", accepted=True, valid_until_ms=0)
    assert forever.is_usable(NOW) is False


def test_expiry_boundary_is_exclusive():
    exact = Commitment(device_id="a", accepted=True, valid_until_ms=NOW)
    assert exact.is_usable(NOW) is False  # 正好到点就不算了
    assert exact.is_usable(NOW - 1) is True


def test_a_decline_never_counts_however_fresh():
    d = Commitment(device_id="a", accepted=False, valid_until_ms=NOW + 99999)
    assert d.is_usable(NOW) is False


# ── 选执行面 ──────────────────────────────────────────────────────────────────
def test_no_usable_commitment_returns_none_not_a_guess():
    assert pick_execution_surface([Commitment(device_id="a")], NOW) is None


def test_without_a_score_the_first_usable_wins_deterministically():
    a, b = _ok("a"), _ok("b")
    assert pick_execution_surface([a, b], NOW).device_id == "a"


def test_score_is_injected_not_invented_here():
    # 仓里已有两处在给设备打分,再写第三份必然会漂。
    a, b = _ok("a"), _ok("b")
    best = pick_execution_surface([a, b], NOW, score=lambda c: 1.0 if c.device_id == "b" else 0.0)
    assert best.device_id == "b"


def test_scoring_only_ranks_usable_ones():
    stale = Commitment(device_id="stale", accepted=True, valid_until_ms=NOW - 1)
    fresh = _ok("fresh")
    best = pick_execution_surface([stale, fresh], NOW, score=lambda c: 99.0 if c.device_id == "stale" else 1.0)
    assert best.device_id == "fresh", "过期的不该因为分高就被选中"


# ── 单设备快路径 ──────────────────────────────────────────────────────────────
def test_local_only_is_the_fast_path():
    for alias in ("local", "self", "this", "LOCALHOST", "  local  "):
        assert is_single_local_candidate([alias]) is True, alias


def test_a_blank_candidate_is_junk_not_a_local_device():
    """空 device_id 在**候选列表里**是垃圾数据,不是"本机"。

    注意它和 ``ui_act.targets_this_machine("")`` 的区别:那里问的是"这次派发的目标
    是不是本机",缺省确实是本机(仲裁器用 device_id="local")。这里问的是"候选池里
    是不是恰好只有本机一台",而一个空串根本不是一台设备。

    同一个别名集合在两个问题上的答案不同 —— 所以不能只看别名,还要先滤掉空白项。
    """
    assert is_single_local_candidate([""]) is False
    assert is_single_local_candidate(["   "]) is False
    assert is_single_local_candidate([]) is False


def test_two_candidates_is_never_the_fast_path():
    assert is_single_local_candidate(["local", "phone"]) is False


def test_a_single_remote_candidate_is_not_the_fast_path():
    # 一台远端设备仍然要问它 —— 它的就位状态本地读不到。
    assert is_single_local_candidate(["phone"]) is False


def test_fast_path_skips_phase_2_entirely():
    called = []

    def _collect(ids):
        called.append(ids)
        return []

    out = decide(action_level="execute", devices=[_dev("local")], collect=_collect, now_ms=NOW)
    assert out.proceed is True and out.fast_path is True and out.selected == "local"
    assert called == [], "单设备时不该发任何提议"


# ── 端到端相位 ────────────────────────────────────────────────────────────────
def test_below_execute_stops_at_preflight():
    out = decide(action_level="hint", devices=[_dev("phone"), _dev("pc")], now_ms=NOW)
    assert out.proceed is False and out.stopped_at == "preflight"


def test_iot_excluded_before_any_proposal_goes_out():
    called = []
    out = decide(
        action_level="execute",
        devices=[DeviceFacts(device_id="bulb", capability_tier="command_only", device_type="IOT")],
        collect=lambda ids: called.append(ids) or [],
        now_ms=NOW,
    )
    assert out.proceed is False and out.stopped_at == "preflight"
    assert called == [], "灯泡不该被问,更不该让协商为它等一个超时"


def test_a_committed_device_is_selected():
    out = decide(
        action_level="execute",
        devices=[_dev("phone"), _dev("pc")],
        collect=lambda ids: [Commitment(device_id="pc", accepted=False, decline_reason="busy"), _ok("phone")],
        now_ms=NOW,
    )
    assert out.proceed is True and out.selected == "phone" and out.stopped_at == "committed"


def test_everyone_declined_stops_and_keeps_every_reason():
    out = decide(
        action_level="execute",
        devices=[_dev("phone"), _dev("pc")],
        collect=lambda ids: [
            Commitment(device_id="phone", accepted=False, decline_reason=DeclineReason.BUSY.value),
            Commitment(device_id="pc", accepted=False, decline_reason=DeclineReason.NOT_READY.value),
        ],
        now_ms=NOW,
    )
    assert out.proceed is False and out.reason == "no_usable_commitment"
    assert out.excluded["phone"] == "busy" and out.excluded["pc"] == "not_ready"


def test_silence_is_recorded_as_no_response_not_as_consent():
    """沉默不是同意 —— 沿用 high_risk_confirmation 已经钉死的原则。"""
    out = decide(
        action_level="execute",
        devices=[_dev("phone"), _dev("pc")],
        collect=lambda ids: [Commitment(device_id="phone", accepted=False)],
        now_ms=NOW,
    )
    assert out.proceed is False
    assert out.excluded["phone"] == DeclineReason.NO_RESPONSE.value


def test_expired_commitment_is_reported_not_silently_used():
    out = decide(
        action_level="execute",
        devices=[_dev("phone"), _dev("pc")],
        collect=lambda ids: [Commitment(device_id="phone", accepted=True, valid_until_ms=NOW - 1)],
        now_ms=NOW,
    )
    assert out.proceed is False and "phone" in out.excluded


def test_missing_transport_with_several_candidates_is_a_wiring_error():
    """静默挑一台会让接线错误永远查不出来。"""
    out = decide(action_level="execute", devices=[_dev("phone"), _dev("pc")], collect=None, now_ms=NOW)
    assert out.proceed is False
    assert out.reason == "no_transport_for_proposal"


def test_a_throwing_transport_does_nothing_rather_than_something():
    def _boom(ids):
        raise ConnectionError("网格断了")

    out = decide(action_level="execute", devices=[_dev("phone"), _dev("pc")], collect=_boom, now_ms=NOW)
    assert out.proceed is False and out.reason == "collect_failed"


def test_needs_human_survives_into_the_outcome():
    # 相位 1 算出来的"要问人"不能在相位 2 被丢掉 —— 丢掉就等于绕过了人确认。
    out = decide(
        action_level="execute",
        devices=[_dev("phone"), _dev("pc")],
        risk_level="critical",
        collect=lambda ids: [_ok("phone")],
        now_ms=NOW,
    )
    assert out.proceed is True and out.needs_human is True and out.reason == "high_risk_action"


def test_needs_human_survives_the_fast_path_too():
    out = decide(action_level="execute", devices=[_dev("local")], risk_level="dangerous", now_ms=NOW)
    assert out.fast_path is True and out.needs_human is True


def test_outcome_dict_is_json_safe():
    d = decide(action_level="execute", devices=[_dev("local")], now_ms=NOW).to_dict()
    assert d["proceed"] is True and d["fast_path"] is True and isinstance(d["excluded"], dict)
