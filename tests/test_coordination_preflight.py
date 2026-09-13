"""问任何设备之前,本地已经知道的那些事。

这是跨设备协商的相位 0+1:零网络、纯计算、全分支可测。它存在的理由是把一大类
"注定的结论"前移 —— 尤其是 **IoT 设备必须在这里被挡下,而不是在一个注定不会有人
回的超时里**。
"""

from __future__ import annotations

from core.coordination_preflight import (
    STOP_BELOW_EXECUTE,
    STOP_NO_CANDIDATE,
    DeviceFacts,
    evaluate,
    may_be_execution_surface,
)


def _phone(**kw):
    base = dict(device_id="phone", capability_tier="full_runtime", device_type="ANDROID", trust_result="allowed")
    base.update(kw)
    return DeviceFacts(**base)


# ── 相位 0 ────────────────────────────────────────────────────────────────────
def test_below_execute_never_touches_the_network():
    for level in ("observe", "hint", "assist"):
        v = evaluate(action_level=level, devices=[_phone()])
        assert v.proceed is False, level
        assert v.reason == STOP_BELOW_EXECUTE
        assert v.candidates == []


def test_execute_proceeds():
    v = evaluate(action_level="execute", devices=[_phone()])
    assert v.proceed is True and v.candidates == ["phone"]


def test_unknown_action_level_is_not_execute():
    # fail-closed:认不出来的档位不当成 execute。
    assert evaluate(action_level="", devices=[_phone()]).proceed is False
    assert evaluate(action_level="EXECUTE_MAYBE", devices=[_phone()]).proceed is False


def test_action_level_is_case_insensitive():
    assert evaluate(action_level="EXECUTE", devices=[_phone()]).proceed is True


# ── tier 压过设备类型 ─────────────────────────────────────────────────────────
def test_command_only_cannot_be_an_execution_surface():
    assert may_be_execution_surface("command_only") is False


def test_unknown_tier_is_treated_as_command_only():
    # 这是 CapabilityTier 自己的文档语义:"Treated conservatively as command_only"。
    assert may_be_execution_surface("unknown") is False
    assert may_be_execution_surface("") is False
    assert may_be_execution_surface("something_new") is False


def test_both_runtime_tiers_may_execute():
    assert may_be_execution_surface("full_runtime") is True
    assert may_be_execution_surface("partial_runtime") is True


def test_iot_is_excluded_here_not_in_a_timeout():
    """智能灯泡不该进候选池。

    device_policy 把 IOT 放进 PHYSICAL_DEVICE_TYPES,于是 requires_agent_deploy("IOT")
    返回 True —— 按那条,一个灯泡也要先部署 Agent。这里以 tier 为准:类型只知道这是
    什么硬件,tier 知道这台机器此刻能不能跑东西。
    """
    bulb = DeviceFacts(device_id="bulb-1", capability_tier="command_only", device_type="IOT", trust_result="allowed")
    v = evaluate(action_level="execute", devices=[bulb])
    assert v.proceed is False
    assert v.reason == STOP_NO_CANDIDATE
    assert v.excluded["bulb-1"].startswith("tier_cannot_execute")


def test_an_iot_gateway_with_full_runtime_is_allowed():
    # 同为 IOT,跑 Linux 的网关和灯泡差得远。类型那一层分不出来,tier 分得出来。
    hub = DeviceFacts(device_id="hub", capability_tier="full_runtime", device_type="IOT", trust_result="allowed")
    v = evaluate(action_level="execute", devices=[hub])
    assert v.proceed is True and v.candidates == ["hub"]


# ── 信任 ──────────────────────────────────────────────────────────────────────
def test_blocked_is_a_hard_reject_regardless_of_tier():
    dev = _phone(device_id="bad", trust_result="denied")
    v = evaluate(action_level="execute", devices=[dev])
    assert v.proceed is False
    assert v.excluded["bad"] == "peer_trust_blocked"


def test_require_approval_keeps_the_device_but_needs_a_human():
    dev = _phone(trust_result="require_approval")
    v = evaluate(action_level="execute", devices=[dev])
    assert v.proceed is True
    assert v.candidates == ["phone"]
    assert v.needs_human is True
    assert v.reason == "trust_requires_approval"


def test_unrecognised_trust_value_is_conservative():
    # 认不出来 → 当成要人确认,而不是当成放行。
    v = evaluate(action_level="execute", devices=[_phone(trust_result="probably_fine")])
    assert v.needs_human is True


# ── 风险 ──────────────────────────────────────────────────────────────────────
def test_high_risk_needs_a_human_even_on_a_trusted_device():
    for risk in ("dangerous", "critical", "CRITICAL"):
        v = evaluate(action_level="execute", devices=[_phone()], risk_level=risk)
        assert v.needs_human is True, risk
        assert v.reason == "high_risk_action"


def test_low_risk_on_a_trusted_device_needs_nobody():
    v = evaluate(action_level="execute", devices=[_phone()], risk_level="safe")
    assert v.proceed is True and v.needs_human is False and v.reason == ""


def test_high_risk_levels_are_configurable():
    v = evaluate(
        action_level="execute", devices=[_phone()], risk_level="moderate", high_risk_levels=("moderate", "dangerous")
    )
    assert v.needs_human is True


# ── 排除必须有理由 ────────────────────────────────────────────────────────────
def test_every_excluded_device_carries_a_reason():
    """一个静默消失的候选设备,排障时无从查起。"""
    devs = [
        _phone(device_id="ok"),
        _phone(device_id="blocked", trust_result="denied"),
        _phone(device_id="bulb", capability_tier="command_only"),
    ]
    v = evaluate(action_level="execute", devices=devs)
    assert v.candidates == ["ok"]
    assert set(v.excluded) == {"blocked", "bulb"}
    assert all(v.excluded.values()), "有设备被排除却没有写明原因"


def test_blank_device_ids_are_dropped_not_counted():
    v = evaluate(action_level="execute", devices=[DeviceFacts(device_id="   "), _phone()])
    assert v.candidates == ["phone"]


def test_no_devices_at_all_stops_without_guessing():
    v = evaluate(action_level="execute", devices=[])
    assert v.proceed is False and v.reason == STOP_NO_CANDIDATE


def test_verdict_dict_is_json_safe():
    d = evaluate(action_level="execute", devices=[_phone()]).to_dict()
    assert d["proceed"] is True and d["candidates"] == ["phone"] and isinstance(d["excluded"], dict)
