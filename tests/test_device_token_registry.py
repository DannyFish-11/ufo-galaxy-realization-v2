"""每设备 token 注册表 + auth 集成的回归测试。

锁死配对发放凭证底座的关键不变量:发放→校验通过、按设备吊销、只存摘要不存明文、
落盘可跨"重启"(重建实例)复活、以及 core.auth.verify_api_token 会接受每设备 token。
"""

import json

import pytest

from core.device_token_registry import DeviceTokenRegistry, _hash_token


def _reg(tmp_path):
    return DeviceTokenRegistry(store_path=tmp_path / "device_tokens.json")


def test_issue_then_verify(tmp_path):
    r = _reg(tmp_path)
    tok = r.issue("dev-1", device_type="android", name="小米17")
    assert isinstance(tok, str) and len(tok) >= 20
    rec = r.verify(tok)
    assert rec is not None
    assert rec["device_id"] == "dev-1"
    assert rec["device_type"] == "android"
    assert rec["last_seen"] is not None  # 校验命中刷新 last_seen


def test_wrong_token_rejected(tmp_path):
    r = _reg(tmp_path)
    r.issue("dev-1")
    assert r.verify("not-a-real-token") is None
    assert r.verify("") is None


def test_revoke_by_device(tmp_path):
    r = _reg(tmp_path)
    tok = r.issue("dev-1")
    assert r.verify(tok) is not None
    n = r.revoke_device("dev-1")
    assert n == 1
    assert r.verify(tok) is None, "吊销后必须拒绝"
    # 其它设备不受影响
    tok2 = r.issue("dev-2")
    assert r.verify(tok2) is not None


def test_only_hash_persisted_never_plaintext(tmp_path):
    p = tmp_path / "device_tokens.json"
    r = DeviceTokenRegistry(store_path=p)
    tok = r.issue("dev-1", name="phone")
    raw = p.read_text(encoding="utf-8")
    assert tok not in raw, "明文 token 绝不能落盘!"
    data = json.loads(raw)
    assert data["tokens"][0]["token_sha256"] == _hash_token(tok)
    # 元数据在,明文不在
    assert data["tokens"][0]["device_id"] == "dev-1"


def test_survives_restart(tmp_path):
    p = tmp_path / "device_tokens.json"
    tok = DeviceTokenRegistry(store_path=p).issue("dev-1")
    # 模拟进程重启:用同一文件重建实例
    r2 = DeviceTokenRegistry(store_path=p)
    assert r2.verify(tok) is not None, "落盘应跨重启复活(env token 无持久化正是被修的洞)"


def test_list_devices_has_no_secrets(tmp_path):
    r = _reg(tmp_path)
    r.issue("dev-1", device_type="wearos", name="watch")
    lst = r.list_devices()
    assert len(lst) == 1
    row = lst[0]
    assert row["device_id"] == "dev-1" and row["device_type"] == "wearos"
    assert "token_sha256" not in row and "token" not in row, "枚举不得含任何凭证"


def test_auth_verify_api_token_accepts_device_token(tmp_path, monkeypatch):
    """core.auth.verify_api_token 应接受每设备 token(经单例注册表)。"""
    import core.auth as auth
    import core.device_token_registry as dtr

    # 把注册表单例指到临时存储,避免碰到真实 ~/.galaxy
    reg = DeviceTokenRegistry(store_path=tmp_path / "device_tokens.json")
    monkeypatch.setattr(dtr, "_registry", reg)

    tok = reg.issue("dev-1", device_type="android")
    # 没有配任何 env 共享 token 时,每设备 token 也应通过
    monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)
    monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
    assert auth.verify_api_token(tok) is True

    # 吊销后应被拒
    reg.revoke_device("dev-1")
    assert auth.verify_api_token(tok) is False
