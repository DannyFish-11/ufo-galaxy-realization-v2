"""设备准入闸(P3-1 阶段二收尾)决策回归。

锁死 opt-in 语义:GALAXY_REQUIRE_DEVICE_APPROVAL 默认关 → 恒不拦(注册行为与现状
逐字节一致);开启后只拦【未批准】设备(token_valid=False)降为 control_only,
已批准(持有效每设备 token → token_valid=True)放行。

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
    assert _should_gate_unapproved({"token_valid": False}) is False
    assert _should_gate_unapproved({"token_valid": True}) is False
    assert _should_gate_unapproved({}) is False


@pytest.mark.parametrize("flag", ["1", "true", "yes", "on", "TRUE", "On"])
def test_on_gates_only_unapproved(monkeypatch, flag):
    monkeypatch.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", flag)
    # 未批准 → 拦(降 control_only)
    assert _should_gate_unapproved({"token_valid": False}) is True
    assert _should_gate_unapproved({}) is True
    # 已批准(持有效每设备 token)→ 放行
    assert _should_gate_unapproved({"token_valid": True}) is False


@pytest.mark.parametrize("flag", ["0", "false", "no", "off", ""])
def test_falsey_flag_values_off(monkeypatch, flag):
    monkeypatch.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", flag)
    assert _should_gate_unapproved({"token_valid": False}) is False
