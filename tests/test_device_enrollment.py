"""设备入伙协调器(配对/发放 + 智能体准入)回归测试。

锁死:请求→pending→批准发 token→设备 claim 一次;拒绝;TTL 过期;配对码一次性 +
增强信任信号;策略钩子(智能体预判)只建议不绑定;终裁前 token 不存在。
"""

import time

from core.device_enrollment import (
    CLAIMED,
    DENIED,
    EXPIRED,
    PENDING,
    DeviceEnrollmentCoordinator,
)
from core.device_token_registry import DeviceTokenRegistry


def _coord(tmp_path, **kw):
    reg = DeviceTokenRegistry(store_path=tmp_path / "device_tokens.json")
    return DeviceEnrollmentCoordinator(registry=reg, **kw), reg


def test_submit_then_approve_then_claim(tmp_path):
    c, reg = _coord(tmp_path)
    req = c.submit_enrollment("dev-1", device_type="android", name="小米17")
    assert req.status == PENDING
    # pending 列表能看到,且不含 token
    p = c.pending()
    assert len(p) == 1 and p[0]["device_id"] == "dev-1"
    assert "token" not in p[0] and "_token" not in p[0]

    # 批准 → 发 token
    tok = c.approve(req.request_id)
    assert tok, "批准应发放明文 token"
    # 这个 token 在注册表里能校验通过(闭环)
    assert reg.verify(tok) is not None
    # 设备 claim 一次
    claimed = c.claim(req.request_id)
    assert claimed == tok
    # 第二次 claim 拿不到(一次性)
    assert c.claim(req.request_id) is None
    assert c.get(req.request_id)["status"] == CLAIMED


def test_deny(tmp_path):
    c, reg = _coord(tmp_path)
    req = c.submit_enrollment("dev-1")
    assert c.deny(req.request_id, reason="不认识这台") is True
    assert c.get(req.request_id)["status"] == DENIED
    assert c.approve(req.request_id) is None, "已拒绝不能再批准"
    assert c.claim(req.request_id) is None


def test_token_absent_before_approval(tmp_path):
    c, reg = _coord(tmp_path)
    req = c.submit_enrollment("dev-1")
    assert c.claim(req.request_id) is None, "未批准前不得有 token"


def test_pairing_code_one_time_and_trust_signal(tmp_path):
    c, reg = _coord(tmp_path)
    code = c.create_pairing_code()["code"]
    req = c.submit_enrollment("dev-1", pairing_code=code)
    assert req.code_verified is True, "有效配对码应标记增强信任"
    # 码是一次性的:再用同一个码提交,code_verified=False
    req2 = c.submit_enrollment("dev-2", pairing_code=code)
    assert req2.code_verified is False


def test_bad_or_missing_code_does_not_block(tmp_path):
    c, reg = _coord(tmp_path)
    req = c.submit_enrollment("dev-1", pairing_code="ZZZZZZ")
    assert req.status == PENDING and req.code_verified is False, "无效码不阻断,只是不加信任"


def test_policy_suggests_but_not_binding(tmp_path):
    # 智能体预判:有配对码就建议 approve
    def policy(req):
        return "approve" if req.code_verified else "deny"

    c, reg = _coord(tmp_path, policy=policy)
    code = c.create_pairing_code()["code"]
    req = c.submit_enrollment("dev-1", pairing_code=code)
    assert req.suggested_verdict == "approve"
    # 但仍是 pending(建议非绑定,须显式终裁)
    assert req.status == PENDING
    req2 = c.submit_enrollment("dev-2")  # 无码
    assert req2.suggested_verdict == "deny" and req2.status == PENDING


def test_request_ttl_expiry(tmp_path):
    c, reg = _coord(tmp_path, request_ttl=0.05)
    req = c.submit_enrollment("dev-1")
    time.sleep(0.08)
    # 触发过期扫描
    assert c.get(req.request_id)["status"] == EXPIRED
    assert c.approve(req.request_id) is None, "过期请求不能批准"


def test_pairing_code_ttl(tmp_path):
    c, reg = _coord(tmp_path, code_ttl=0.05)
    code = c.create_pairing_code()["code"]
    time.sleep(0.08)
    req = c.submit_enrollment("dev-1", pairing_code=code)
    assert req.code_verified is False, "过期配对码不加信任"
