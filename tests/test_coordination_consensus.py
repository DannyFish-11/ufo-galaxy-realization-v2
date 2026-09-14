"""在候选中选一个之前,先问问它们本人。

相位 0/1/3/4 都已经有主(decision_gate / unified_dispatch_readiness_gate 的七道闸 /
high_risk_confirmation / CommandRouter)。**只有相位 2 是缺的**:中心从自己这边知道的
一切都查过了,但从没问过设备本人 —— 而设备知道一些中心查不到、且过几百毫秒就变的事。

这组测试钉的是失败语义,那是共识层价值的一多半。
"""

from __future__ import annotations

import asyncio

from core.coordination_consensus import (
    DEFAULT_COMMITMENT_TTL_MS,
    Commitment,
    DeclineReason,
    consensus_required,
    narrow_candidates,
    narrow_devices,
    pick_execution_surface,
    usable_commitments,
)

NOW = 1_000_000


def _ok(did, ttl=5000, level="uia"):
    return Commitment(device_id=did, accepted=True, valid_until_ms=NOW + ttl, best_level=level)


# ── 只在多候选时才问 ──────────────────────────────────────────────────────────
def test_a_single_candidate_needs_no_consensus():
    """一台时没有什么可达成一致的 —— 七道闸已经回答了"这一台能不能接"。"""
    assert consensus_required(1) is False
    assert consensus_required(0) is False


def test_two_or_more_candidates_do():
    assert consensus_required(2) is True
    assert consensus_required(5) is True


# ── 承诺有效期 ────────────────────────────────────────────────────────────────
def test_an_expired_commitment_does_not_count():
    stale = Commitment(device_id="a", accepted=True, valid_until_ms=NOW - 1)
    assert stale.is_usable(NOW) is False


def test_a_commitment_without_an_expiry_does_not_count():
    """没有有效期 = 让中心去赌。这个模块的立场是不赌。"""
    assert Commitment(device_id="a", accepted=True, valid_until_ms=0).is_usable(NOW) is False


def test_the_expiry_boundary_is_exclusive():
    c = Commitment(device_id="a", accepted=True, valid_until_ms=NOW)
    assert c.is_usable(NOW) is False and c.is_usable(NOW - 1) is True


def test_a_decline_never_counts_however_fresh():
    assert Commitment(device_id="a", accepted=False, valid_until_ms=NOW + 99999).is_usable(NOW) is False


def test_the_default_ttl_is_documented_as_a_guess():
    """这个数是推的不是量的 —— 真机数据出来之后该被替换,而不是被默默沿用。"""
    import core.coordination_consensus as cc

    assert DEFAULT_COMMITMENT_TTL_MS == 5_000
    doc = cc.__dict__["__doc__"] or ""
    src = __import__("inspect").getsource(cc)
    assert "推的,不是量的" in src, "默认有效期没有注明它是推断值"


# ── 从 wire 还原:fail-closed ─────────────────────────────────────────────────
def test_missing_accepted_field_means_not_accepted():
    """老版本设备不认识这条消息 → 按"不接"处理,而不是按"接"。"""
    assert Commitment.from_payload({"device_id": "a"}).accepted is False


def test_a_truthy_but_not_true_accepted_is_still_refused():
    for bad in ("yes", 1, "true", [1]):
        assert Commitment.from_payload({"device_id": "a", "accepted": bad}).accepted is False, bad


def test_a_real_acceptance_round_trips():
    c = Commitment.from_payload(
        {"device_id": "pc", "accepted": True, "valid_until_ms": NOW + 1000, "best_level": "uia"}
    )
    assert c.accepted is True and c.is_usable(NOW) is True and c.best_level == "uia"


def test_a_garbage_expiry_does_not_crash_and_does_not_count():
    c = Commitment.from_payload({"device_id": "a", "accepted": True, "valid_until_ms": None})
    assert c.valid_until_ms == 0 and c.is_usable(NOW) is False


# ── 选执行面 ──────────────────────────────────────────────────────────────────
def test_no_usable_commitment_is_a_choice_with_reasons_not_a_guess():
    out = pick_execution_surface(
        [
            Commitment(device_id="a", accepted=False, decline_reason=DeclineReason.BUSY.value),
            Commitment(device_id="b", accepted=False, decline_reason=DeclineReason.NOT_READY.value),
        ],
        NOW,
    )
    assert out.ok is False and out.chosen is None
    assert out.declined == {"a": "busy", "b": "not_ready"}


def test_silence_is_recorded_as_no_response_not_as_consent():
    out = pick_execution_surface([Commitment(device_id="a", accepted=False)], NOW)
    assert out.declined["a"] == DeclineReason.NO_RESPONSE.value


def test_without_a_score_the_first_usable_wins_deterministically():
    assert pick_execution_surface([_ok("a"), _ok("b")], NOW).chosen.device_id == "a"


def test_score_is_injected_not_invented_here():
    """仓里已有两处在给设备打分,再写第三份必然会漂。"""
    out = pick_execution_surface([_ok("a"), _ok("b")], NOW, score=lambda c: c.device_id == "b")
    assert out.chosen.device_id == "b"


def test_scoring_only_ranks_the_usable_ones():
    stale = Commitment(device_id="stale", accepted=True, valid_until_ms=NOW - 1)
    out = pick_execution_surface([stale, _ok("fresh")], NOW, score=lambda c: 99 if c.device_id == "stale" else 1)
    assert out.chosen.device_id == "fresh", "过期的不该因为分高被选中"
    assert "stale" in out.declined


def test_the_choice_keeps_both_the_winner_and_the_reasons():
    out = pick_execution_surface([_ok("win"), Commitment(device_id="lose", accepted=False, decline_reason="busy")], NOW)
    d = out.to_dict()
    assert d["ok"] is True and d["chosen"] == "win" and d["declined"] == {"lose": "busy"}


# ── 接线:DeviceRouter 真的会走这一轮 ─────────────────────────────────────────
class _FakeDevice:
    def __init__(self, did):
        self.device_id = did


def _narrow(devices, ctx):
    return asyncio.run(narrow_devices(devices, "x", ctx))


def test_skips_the_round_trip_for_a_single_candidate():
    asked = []

    async def _collect(ids, command):
        asked.append(ids)
        return []

    out = _narrow([_FakeDevice("a")], {"_commitment_collector": _collect})
    assert [d.device_id for d in out] == ["a"]
    assert asked == [], "单候选不该发提议"


def test_narrows_to_the_committed_device():
    async def _collect(ids, command):
        return [Commitment(device_id="b", accepted=True, valid_until_ms=int(9e18))]

    out = _narrow([_FakeDevice("a"), _FakeDevice("b")], {"_commitment_collector": _collect})
    assert [d.device_id for d in out] == ["b"]


def test_returns_empty_when_everyone_declines():
    """全部谢绝是**有信息的失败** —— 比盲目派给第一台强,那一台刚亲口说它接不了。"""

    async def _collect(ids, command):
        return [Commitment(device_id=i, accepted=False, decline_reason="busy") for i in ids]

    out = _narrow([_FakeDevice("a"), _FakeDevice("b")], {"_commitment_collector": _collect})
    assert out == []


def test_does_not_block_dispatch_when_there_is_no_collector():
    """这一步是对既有选择的**精化**,不是新增的必过闸。

    做成必过闸,"协商通道还没接好"就直接变成"跨设备派发不可用" ——
    那是拿可用性换一个尚未验证的机制。
    """
    out = _narrow([_FakeDevice("a"), _FakeDevice("b")], {})
    assert [d.device_id for d in out] == ["a", "b"]


def test_a_throwing_collector_does_not_block_dispatch_either():
    async def _boom(ids, command):
        raise ConnectionError("网格断了")

    out = _narrow([_FakeDevice("a"), _FakeDevice("b")], {"_commitment_collector": _boom})
    assert [d.device_id for d in out] == ["a", "b"]


def test_a_commitment_for_an_unknown_device_does_not_silently_drop_everything():
    """承诺里的 device_id 不在候选里 —— 退回原候选,而不是返回空(那会当成全员谢绝)。"""

    async def _collect(ids, command):
        return [Commitment(device_id="ghost", accepted=True, valid_until_ms=int(9e18))]

    out = _narrow([_FakeDevice("a"), _FakeDevice("b")], {"_commitment_collector": _collect})
    assert [d.device_id for d in out] == ["a", "b"]


def test_route_task_actually_calls_this_round():
    """接线是真的:``DeviceRouter.route_task`` 里确实有这一次调用。

    用 AST 查而不是 grep 源码字符串 —— 注释里、文档串里出现同一个名字不算接线。
    这条测试存在的原因:这一轮如果只是"写好了但没人调",它的全部成本(一次往返)
    都白付,而收益(设备本人的判断)一分也拿不到,且没有任何现象会暴露这件事。
    """
    import ast
    import inspect

    from galaxy_gateway import device_router as dr

    assert dr.narrow_devices is narrow_devices, "路由器导的不是同一个函数"

    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(dr.DeviceRouter.route_task)))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "narrow_devices" in called, "route_task 没有真的调用这一轮协商"


def test_a_room_of_silence_is_not_a_room_of_refusals():
    """全场 no_response → 按"没问过"放行,而不是"都拒绝"清空候选。

    这条守的是一个具体的坏结局:协商这一轮默认开着,而现有固件没有一版会回
    execution_commitment。若沉默 == 拒绝,上线当天所有多候选跨设备派发静默消失。
    """
    silent = [
        Commitment(device_id=d, accepted=False, decline_reason=DeclineReason.NO_RESPONSE.value) for d in ("a", "b")
    ]
    r = narrow_candidates(["a", "b"], silent)
    assert r.outcome == "unchanged" and r.device_ids == ["a", "b"]


def test_one_explicit_refusal_among_the_silence_is_enough_to_count_as_an_answer():
    mixed = [
        Commitment(device_id="a", accepted=False, decline_reason=DeclineReason.NO_RESPONSE.value),
        Commitment(device_id="b", accepted=False, decline_reason=DeclineReason.POLICY_DECLINED.value),
    ]
    r = narrow_candidates(["a", "b"], mixed)
    assert r.outcome == "all_declined" and r.device_ids == []


def test_the_round_can_be_turned_off_without_changing_anything_else(monkeypatch):
    """``GALAXY_CONSENSUS_ROUND=0`` 之后,行为与接入之前逐字相同。"""
    import core.coordination_consensus as m

    monkeypatch.setenv("GALAXY_CONSENSUS_ROUND", "0")
    assert m._default_collector() is None

    monkeypatch.delenv("GALAXY_CONSENSUS_ROUND", raising=False)
    assert m._default_collector() is not None, "默认必须是开的 —— 要人另外打开的机制等于没接"
