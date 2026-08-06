"""设备准入闸(P3-1 阶段二收尾)决策回归。

锁死 opt-in 语义:GALAXY_REQUIRE_DEVICE_APPROVAL 默认关 → 恒不拦(注册行为与现状
逐字节一致);开启后只拦【未批准】设备(device_approved=False)降为 control_only,
已批准(每设备 token 绑定本 device_id → device_approved=True)放行。

安全要点:approved 判据是 device_approved(令牌须发放给本设备),不是裸 token_valid——
一枚泄露的配对令牌换个 device_id 呈递,token_valid 仍为 True,但 device_approved 为
False,照样被拦。

注:handle_device_register 整条链路依赖 UDM/mesh/session 等重组件,无法纯单测;
此处直击安全相关的【决策】助手 _should_gate_unapproved(承重的 posture 降级即由它驱动)。
"""

import pytest

from galaxy_gateway.android.handlers.registration import _should_gate_unapproved


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GALAXY_REQUIRE_DEVICE_APPROVAL", raising=False)
    yield


def test_default_off_never_gates(monkeypatch):
    monkeypatch.delenv("GALAXY_REQUIRE_DEVICE_APPROVAL", raising=False)
    # 默认关:无论批准与否都不拦 → 现状行为
    assert _should_gate_unapproved({"device_approved": False}) is False
    assert _should_gate_unapproved({"device_approved": True}) is False
    assert _should_gate_unapproved({}) is False


@pytest.mark.parametrize("flag", ["1", "true", "yes", "on", "TRUE", "On"])
def test_on_gates_only_unapproved(monkeypatch, flag):
    monkeypatch.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", flag)
    # 未批准 → 拦(降 control_only)
    assert _should_gate_unapproved({"device_approved": False}) is True
    assert _should_gate_unapproved({}) is True
    # 安全:仅 token_valid 但未绑定本设备(device_approved 缺/False)→ 仍拦
    assert _should_gate_unapproved({"token_valid": True, "device_approved": False}) is True
    # 已批准(配对令牌绑定本设备)→ 放行
    assert _should_gate_unapproved({"device_approved": True}) is False


@pytest.mark.parametrize("flag", ["0", "false", "no", "off", ""])
def test_falsey_flag_values_off(monkeypatch, flag):
    monkeypatch.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", flag)
    assert _should_gate_unapproved({"device_approved": False}) is False


def test_device_approved_binds_the_pairing_token_to_device_id(monkeypatch):
    """安全核心:配对令牌只在【签发给本 device_id】时算已批准;换个 device_id 冒充不算。

    每设备 token 注册表已经删掉,绑定这件事现在由能力令牌自己承担 —— 它签名里带
    subject,入口处拿它和本条消息的 device_id 比对。判据换了实现,但要挡的还是
    同一件事:一枚令牌被抄走后换台设备呈递。
    """
    import core.auth as auth
    from core.capability_token import issue_token
    from galaxy_gateway.android.handlers.registration import _evaluate_ingress_authentication

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(auth, "get_active_tokens", lambda: [])
    # 只认这一串环境 token。**不能**打成恒 True:那样"绑定通过"和"反正 token 有效"
    # 会给出同一个结果,这条测试就再也分不出 subject 绑定还在不在。
    monkeypatch.setattr(auth, "verify_api_token", lambda t: t == "ENVADMIN")

    phone_a = issue_token("phone-A", ["device:status"], ttl_s=300)

    # 本设备就是 phone-A → 绑定通过 → device_approved
    ok = _evaluate_ingress_authentication({"device_id": "phone-A", "token": phone_a})
    assert ok["token_valid"] is True and ok["device_approved"] is True

    # 抄走的令牌换个 device_id 冒充 → 绑定不过 → 当场拒,不回退到"按普通 token 算"。
    bad = _evaluate_ingress_authentication({"device_id": "evil", "token": phone_a})
    assert bad["device_approved"] is False, "抄走的配对令牌换台设备仍被当成已批准"

    # 共享/环境管理员 token(不是配对令牌)→ 按 token_valid 放行
    admin = _evaluate_ingress_authentication({"device_id": "whatever", "token": "ENVADMIN"})
    assert admin["token_valid"] is True and admin["device_approved"] is True

    # 反面:既不是配对令牌也不是环境 token → 两项都不成立
    junk = _evaluate_ingress_authentication({"device_id": "phone-A", "token": "not-a-token"})
    assert junk["token_valid"] is False and junk["device_approved"] is False
