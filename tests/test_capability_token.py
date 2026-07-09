"""tests/test_capability_token.py
====================================

Mesh 能力令牌:签名(防篡改)· 作用域(globset)· 过期 · 全局撤销。
"""
from __future__ import annotations

import pytest

import core.capability_token as ct


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_MESH_SECRET", "test-secret-key")
    monkeypatch.setattr(ct, "_revoked_path", lambda: str(tmp_path / "revoked.json"))
    ct.reset_secret_cache()
    ct.reset_revoked_cache()
    yield
    ct.reset_secret_cache()
    ct.reset_revoked_cache()


class TestIssueVerify:
    def test_valid_token_verifies(self):
        tok = ct.issue_token("device-phone", ["device:tap"], ttl_s=3600, now=1000.0)
        v = ct.verify_token(tok, required_scope="device:tap", now=1001.0)
        assert v.valid and v.subject == "device-phone" and "device:tap" in v.scopes

    def test_scope_glob_matches(self):
        tok = ct.issue_token("d", ["node:Node_36_*:*"], now=1000.0)
        assert ct.verify_token(tok, required_scope="node:Node_36_UIAWindows:click", now=1001.0).valid

    def test_scope_miss_rejected(self):
        tok = ct.issue_token("d", ["device:tap"], now=1000.0)
        v = ct.verify_token(tok, required_scope="device:shell", now=1001.0)
        assert not v.valid and "作用域" in v.reason

    def test_no_required_scope_only_checks_validity(self):
        tok = ct.issue_token("d", ["x"], now=1000.0)
        assert ct.verify_token(tok, now=1001.0).valid


class TestExpiryAndTamper:
    def test_expired_rejected(self):
        tok = ct.issue_token("d", ["x"], ttl_s=10, now=1000.0)
        v = ct.verify_token(tok, now=1011.0)
        assert not v.valid and v.reason == "已过期"

    def test_tampered_payload_rejected(self):
        tok = ct.issue_token("d", ["device:tap"], now=1000.0)
        prefix, payload, sig = tok.split(".")
        # 换一个别的令牌的 payload 拼上旧签名 → 签名对不上
        other = ct.issue_token("attacker", ["device:shell"], now=1000.0).split(".")[1]
        forged = f"{prefix}.{other}.{sig}"
        assert not ct.verify_token(forged, now=1001.0).valid

    def test_wrong_secret_rejects(self, monkeypatch):
        tok = ct.issue_token("d", ["x"], now=1000.0)
        monkeypatch.setenv("GALAXY_MESH_SECRET", "different-secret")
        ct.reset_secret_cache()
        v = ct.verify_token(tok, now=1001.0)
        assert not v.valid and "签名" in v.reason

    def test_garbage_rejected(self):
        for junk in ("", "not-a-token", "v1.only-two", "v2.a.b"):
            assert not ct.verify_token(junk).valid


class TestRevocation:
    def test_revoke_invalidates(self):
        tok = ct.issue_token("d", ["device:tap"], now=1000.0)
        v = ct.verify_token(tok, now=1001.0)
        assert v.valid
        ct.revoke(v.jti)
        ct.reset_revoked_cache()  # 模拟另一进程读持久化的撤销表
        v2 = ct.verify_token(tok, now=1002.0)
        assert not v2.valid and v2.reason == "已撤销"
