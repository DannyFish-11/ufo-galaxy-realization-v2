"""手表可打扰性接进常驻注意力循环的契约。

所有者拍板的隐私边界:心率/运动/睡眠**只在手表本地参与运算**,上来的
只有一个标量报告。因此这一侧的责任不是"解读生理数据",而是三件事:

1. **UNKNOWN ≠ FREE** —— "没有传感证据"不是"可以打扰";
2. **陈旧即不存在** —— 手表掉线后最后一条报告不能被无限期当成现状;
3. **有界延迟不是丢弃** —— BLOCKED 只压制**自发**开口,不影响委托,
   更不影响用户显式发起的请求。

这三条只要有一条松了,「克制是美德」就又退回成一句无法执行的祈使句。
"""

from __future__ import annotations

import pytest

from core.ambient_attention_loop import (
    AmbientAction,
    AmbientDecision,
    AmbientObservation,
    LLMRouterDecider,
    _apply_interruptibility_gate,
)
from core.interruptibility_registry import (
    KNOWN_BANDS,
    STALE_AFTER_S,
    InterruptibilityRegistry,
    get_interruptibility_registry,
    reset_interruptibility_registry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_interruptibility_registry()
    yield
    reset_interruptibility_registry()


def _payload(band="free", score=0.8, confidence=1.0, reasons=("calm",)):
    return {
        "score": score,
        "band": band,
        "reasons": list(reasons),
        "confidence": confidence,
        "device": "wear_os",
        "timestamp": 1_700_000_000_000,
    }


# ── 1. 收报与校验 ────────────────────────────────────────────────────────


def test_records_a_valid_report():
    reg = InterruptibilityRegistry()
    snap = reg.record(_payload(), device_id="watch-1", now=100.0)

    assert snap is not None
    assert snap.band == "free"
    assert snap.score == pytest.approx(0.8)
    assert snap.reasons == ("calm",)
    assert snap.device_id == "watch-1"


def test_unknown_band_is_rejected_loudly_not_silently_coerced(caplog):
    """手表侧新增档位而这里没跟上,是必须被人看见的协议漂移。

    静默把它当成 neutral 收下,才是最坏的处理 —— 漂移会一直藏着。
    """
    reg = InterruptibilityRegistry()
    with caplog.at_level("WARNING"):
        assert reg.record(_payload(band="super_busy")) is None
    assert any("协议漂移" in r.message or "band" in r.message for r in caplog.records)
    assert reg.current(now=100.0) is None


def test_malformed_fields_are_coerced_not_crashing():
    """畸形报文不该炸掉 WS 主流程,但也不该被原样信任。"""
    reg = InterruptibilityRegistry()
    snap = reg.record(
        {
            "band": "busy",
            "score": "not-a-number",
            "confidence": 99.0,  # 越界
            "reasons": "high_motion",  # 不是列表
        },
        now=100.0,
    )

    assert snap is not None
    assert snap.score == pytest.approx(0.5)  # 转不动 → 中性默认
    assert snap.confidence == pytest.approx(1.0)  # 钳到 [0,1]
    assert snap.reasons == ()  # 不是列表 → 丢弃,不猜


def test_reason_list_is_bounded():
    """一条畸形报文不该把提示词撑爆。"""
    reg = InterruptibilityRegistry()
    snap = reg.record(_payload(reasons=[f"tag_{i}" for i in range(100)]), now=100.0)

    assert snap is not None
    assert len(snap.reasons) <= 8
    assert all(len(r) <= 32 for r in snap.reasons)


# ── 2. 陈旧即不存在 ──────────────────────────────────────────────────────


def test_stale_report_is_treated_as_absent():
    """手表掉线后,最后一条报告不能被无限期当成现状。"""
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="free"), now=100.0)

    assert reg.current(now=100.0 + STALE_AFTER_S - 1) is not None
    assert reg.current(now=100.0 + STALE_AFTER_S + 1) is None


def test_stale_blocked_report_stops_blocking():
    """反向同样要成立:掉线的手表不该永久封住主动开口。"""
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="blocked", score=0.0), now=100.0)

    assert reg.is_blocked(now=200.0) is True
    assert reg.is_blocked(now=100.0 + STALE_AFTER_S + 1) is False


def test_stale_after_exceeds_watch_heartbeat():
    """过期窗口必须容得下手表的心跳周期(10 分钟),否则一次丢包就误判掉线。"""
    assert STALE_AFTER_S >= 2 * 10 * 60


def test_freshest_device_wins():
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="busy"), device_id="old-watch", now=100.0)
    reg.record(_payload(band="free"), device_id="new-watch", now=200.0)

    snap = reg.current(now=250.0)
    assert snap is not None and snap.device_id == "new-watch"


# ── 3. UNKNOWN ≠ FREE(整个设计的安全阀)──────────────────────────────


def test_unknown_band_is_not_a_green_light():
    """ "没有传感证据"既不构成放行,也不构成阻拦。"""
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="unknown", score=0.5, confidence=0.0, reasons=["no_sensor_data"]), now=100.0)

    snap = reg.current(now=100.0)
    assert snap is not None  # 手表在线这件事本身是真的
    assert snap.usable is False  # 但说不出个所以然
    assert reg.is_blocked(now=100.0) is False  # 不阻拦
    assert reg.prompt_line(now=100.0) == ""  # 也不写进提示词误导模型


def test_zero_confidence_is_never_usable_even_with_a_confident_looking_band():
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="free", score=0.95, confidence=0.0), now=100.0)

    assert reg.current(now=100.0).usable is False
    assert reg.prompt_line(now=100.0) == ""


def test_no_watch_at_all_produces_no_line_and_no_block():
    reg = InterruptibilityRegistry()

    assert reg.current(now=100.0) is None
    assert reg.is_blocked(now=100.0) is False
    assert reg.prompt_line(now=100.0) == ""


# ── 4. 提示词一行 ────────────────────────────────────────────────────────


def test_blocked_line_tells_the_model_to_stay_silent():
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="blocked", score=0.0, reasons=["dnd"]), now=100.0)

    line = reg.prompt_line(now=100.0)
    assert "不宜打扰" in line and "SILENT" in line
    assert "已开勿扰" in line  # 粗粒度标签被译成人话


def test_neutral_writes_nothing_because_it_says_nothing():
    """NEUTRAL 的信息量是零,写进提示词只会占 token、还可能被当成暗示。"""
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="neutral", score=0.5), now=100.0)

    assert reg.prompt_line(now=100.0) == ""


def test_low_confidence_line_hedges_instead_of_asserting():
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="busy", score=0.2, confidence=0.4), now=100.0)

    assert "证据不足" in reg.prompt_line(now=100.0)


def test_unregistered_reason_tag_passes_through_verbatim():
    """手表侧新增标签时不该被吞掉 —— 未登记的原样透传,前向兼容。"""
    reg = InterruptibilityRegistry()
    reg.record(_payload(band="busy", reasons=["driving"]), now=100.0)

    assert "driving" in reg.prompt_line(now=100.0)


def test_prompt_line_reaches_the_decider_prompt():
    """光有一行不够,得真的进模型看到的那段文本。"""
    obs = AmbientObservation(interruptibility_note="（手表：此刻明确不宜打扰。）")
    messages = LLMRouterDecider()._build_messages(obs)

    content = messages[0]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    assert "此刻明确不宜打扰" in text


def test_empty_note_adds_nothing_to_the_prompt():
    obs = AmbientObservation(interruptibility_note="")
    messages = LLMRouterDecider()._build_messages(obs)

    content = messages[0]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    assert "手表" not in text


# ── 5. 硬闸:提示词只是建议,勿扰时主动开口是不可接受的失败模式 ────────


def test_blocked_downgrades_speak_to_silent():
    get_interruptibility_registry().record(_payload(band="blocked", score=0.0, reasons=["likely_asleep"]))

    gated = _apply_interruptibility_gate(
        AmbientDecision(action=AmbientAction.SPEAK, utterance="你回来了", salient=True)
    )

    assert gated.action == AmbientAction.SILENT
    assert gated.salient is False
    # 原本要说的话必须留在理由里:事后查日志能看出"它本来想说什么、为什么没说"。
    assert "你回来了" in gated.rationale


def test_blocked_does_not_stop_delegation():
    """ "别吵我"不等于"别干活" —— 委托是后台静默执行,正是此刻最该做的事。"""
    get_interruptibility_registry().record(_payload(band="blocked", score=0.0))

    decision = AmbientDecision(action=AmbientAction.DELEGATE, task="查一下那个报错")
    assert _apply_interruptibility_gate(decision) is decision


def test_busy_does_not_hard_gate_speak():
    """BUSY 只进提示词让模型权衡,硬拦太钝 —— 要紧的事仍该说。"""
    get_interruptibility_registry().record(_payload(band="busy", score=0.2))

    decision = AmbientDecision(action=AmbientAction.SPEAK, utterance="服务器挂了")
    assert _apply_interruptibility_gate(decision).action == AmbientAction.SPEAK


def test_no_watch_leaves_behaviour_identical_to_before():
    """没接手表时,整条链路的行为必须与接手表之前一模一样。"""
    decision = AmbientDecision(action=AmbientAction.SPEAK, utterance="随便说点什么")
    assert _apply_interruptibility_gate(decision) is decision


def test_gate_is_bounded_deferral_not_permanent_drop():
    """降级是有界延迟:勿扰一解除,同样的情形重新有机会 SPEAK。"""
    reg = get_interruptibility_registry()
    reg.record(_payload(band="blocked", score=0.0))
    assert _apply_interruptibility_gate(AmbientDecision(action=AmbientAction.SPEAK, utterance="x")).action == (
        AmbientAction.SILENT
    )

    reg.record(_payload(band="free", score=0.9))
    assert _apply_interruptibility_gate(AmbientDecision(action=AmbientAction.SPEAK, utterance="x")).action == (
        AmbientAction.SPEAK
    )


# ── 6. 跨仓协议 ──────────────────────────────────────────────────────────


def test_known_bands_match_the_watch_side_contract():
    """与 galaxy-wearos 的 InterruptibilityBand.wire 一一对应。

    手表侧由 `InterruptibilityWireContractTest` 钉死同一份字符串;
    任何一侧单独改动都会让这两个测试之一变红。
    """
    assert set(KNOWN_BANDS) == {"unknown", "blocked", "busy", "neutral", "free"}


def test_snapshot_all_exposes_staleness_instead_of_hiding_it():
    reg = InterruptibilityRegistry()
    reg.record(_payload(), device_id="watch-1", now=100.0)

    view = reg.snapshot_all(now=100.0 + STALE_AFTER_S + 1)
    assert view["devices"][0]["stale"] is True
    assert view["stale_after_s"] == STALE_AFTER_S


def test_wire_payload_carries_no_biometric_fields():
    """隐私契约的这一侧:就算手表被改坏了往上塞生物数据,也进不了登记处。"""
    reg = InterruptibilityRegistry()
    snap = reg.record(
        {**_payload(), "heart_rate_bpm": 132, "resting_bpm": 58, "hrv_rmssd": 21},
        now=100.0,
    )

    assert snap is not None
    assert not any("heart" in k or "bpm" in k or "hrv" in k for k in snap.to_dict())
