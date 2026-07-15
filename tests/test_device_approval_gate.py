"""设备准入闸(P3-1 阶段二收尾)决策回归。

锁死 opt-in 语义:GALAXY_REQUIRE_DEVICE_APPROVAL 默认关 → 恒不拦(注册行为与现状
逐字节一致);开启后只拦【未批准】设备(device_approved=False)降为 control_only,
已批准(每设备 token 绑定本 device_id → device_approved=True)放行。

安全要点:approved 判据是 device_approved(token 须发放给本设备),不是裸 token_valid——
一枚泄露的每设备 token 换个 device_id 呈递,token_valid 仍为 True,但 device_approved 为
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
    # 已批准(每设备 token 绑定本设备)→ 放行
    assert _should_gate_unapproved({"device_approved": True}) is False


@pytest.mark.parametrize("flag", ["0", "false", "no", "off", ""])
def test_falsey_flag_values_off(monkeypatch, flag):
    monkeypatch.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", flag)
    assert _should_gate_unapproved({"device_approved": False}) is False


def test_device_approved_binds_per_device_token_to_device_id(monkeypatch):
    """安全核心:每设备 token 只在【发放给本 device_id】时算已批准;换个 device_id 冒充不算。"""
    import core.auth as auth
    import core.device_token_registry as dtr
    from galaxy_gateway.android.handlers.registration import _evaluate_ingress_authentication

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(auth, "get_active_tokens", lambda: [])
    monkeypatch.setattr(auth, "verify_api_token", lambda t: True)  # 任何 token 都"有效"
    # 每设备 token "TKN" 发放给 phone-A;"ENVADMIN" 非每设备(注册表查不到)
    monkeypatch.setattr(dtr, "verify_device_token", lambda t: {"device_id": "phone-A"} if t == "TKN" else None)

    # 本设备就是 phone-A → 绑定通过 → device_approved
    ok = _evaluate_ingress_authentication({"device_id": "phone-A", "token": "TKN"})
    assert ok["token_valid"] is True and ok["device_approved"] is True

    # 泄露 token 换个 device_id 冒充 → token_valid 仍 True,但绑定不过 → device_approved False
    bad = _evaluate_ingress_authentication({"device_id": "evil", "token": "TKN"})
    assert bad["token_valid"] is True and bad["device_approved"] is False

    # 共享/环境管理员 token(非每设备)→ 按 token_valid 放行
    admin = _evaluate_ingress_authentication({"device_id": "whatever", "token": "ENVADMIN"})
    assert admin["device_approved"] is True
