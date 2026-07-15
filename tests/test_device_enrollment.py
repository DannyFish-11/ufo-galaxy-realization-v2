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


def test_approved_but_unclaimed_expires_claim_window(tmp_path):
    """批准后迟迟不领:超过 claim_ttl 即作废,token 领不到、也不留暂存明文。

    request_id 是"一次性、短时效"能力凭据;批准却无人领取不应永久可领。
    """
    c, reg = _coord(tmp_path, claim_ttl=0.05)
    req = c.submit_enrollment("dev-late")
    tok = c.approve(req.request_id)
    assert tok, "批准应发放 token"
    time.sleep(0.08)
    # 过了领取窗口 → 请求作废,claim 拿不到
    assert c.claim(req.request_id) is None, "过期领取窗口后不得再领"
    assert c.get(req.request_id)["status"] == EXPIRED
    # 暂存明文 token 已清(不残留在内存)
    with c._lock:
        assert c._requests[req.request_id]._token is None


def test_claim_within_window_still_works(tmp_path):
    """回归:领取窗口内 claim 正常(过期逻辑不误伤及时领取)。"""
    c, reg = _coord(tmp_path, claim_ttl=5.0)
    req = c.submit_enrollment("dev-prompt")
    tok = c.approve(req.request_id)
    assert c.claim(req.request_id) == tok, "窗口内应能正常领取"


def test_approve_rejects_expired_request_without_prior_scan(tmp_path):
    """approve() 本身先扫过期:即使没有别的调用触发过清理,超 request_ttl 的请求也不能被批准(TOCTOU)。"""
    c, reg = _coord(tmp_path, request_ttl=0.05)
    req = c.submit_enrollment("dev-x")
    time.sleep(0.08)
    # 不先调用 get()/pending();直接 approve —— 修复前会成功发 token,修复后应拒。
    assert c.approve(req.request_id) is None, "过期请求不得被批准"
    assert c.get(req.request_id)["status"] == EXPIRED


def test_terminal_requests_are_purged_after_retention(tmp_path):
    """终态(denied 等)记录过保留窗口后被清除,防止 _requests 无限堆积(无鉴权 /enroll 的内存 DoS)。"""
    c, reg = _coord(tmp_path, terminal_retention=0.05)
    req = c.submit_enrollment("dev-purge")
    assert c.deny(req.request_id) is True
    time.sleep(0.08)
    c._expire_locked_free()  # 触发清理
    assert c.get(req.request_id) is None, "过保留窗口的终态记录应被清除"
    with c._lock:
        assert req.request_id not in c._requests


def test_requests_dict_is_hard_capped(tmp_path):
    """洪泛兜底:_requests 超过 max_requests 即逐出,绝不无界增长。"""
    c, reg = _coord(tmp_path, max_requests=5, terminal_retention=9999)
    for i in range(50):
        c.submit_enrollment(f"dev-{i}")
    with c._lock:
        # 逐出在 submit 开头的 _expire 里执行,故稳态为 max+1(刚插入的这条);关键是【有界】,
        # 绝不随 /enroll 次数无限增长。
        assert len(c._requests) <= 6, f"_requests 必须被硬上限约束(有界); got {len(c._requests)}"


def test_pairing_code_ttl(tmp_path):
    c, reg = _coord(tmp_path, code_ttl=0.05)
    code = c.create_pairing_code()["code"]
    time.sleep(0.08)
    req = c.submit_enrollment("dev-1", pairing_code=code)
    assert req.code_verified is False, "过期配对码不加信任"
