"""tests/test_input_validation_loopback_exemption.py
======================================================
真机复现排查(用户"填了 API Key 保存还是失败")时发现:core/security_middleware.py
的 InputValidationMiddleware(SQL 注入/XSS/命令注入/路径穿越正则扫描)之前没有
像 RateLimitMiddleware 那样做本机回环豁免。这个仓库是本机可信单用户桌面应用,
用户在「模型」tab 填的 URL 类字段(OneAPI/vLLM/自定义 API 地址,允许任意字符串)
一旦包含 `../`、反引号、`$(...)` 等字符,会被误判成"疑似注入攻击"直接 400,
现象同样是笼统的"保存失败"，跟限流误伤长得不一样但一样难自证。

验证:回环地址即使发送命中检测规则的内容也应放行;外部(非回环)IP 的检测能力
不受影响;GALAXY_INPUT_VALIDATION_LOOPBACK=1 可强制对回环地址也校验。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.security_middleware import InputValidator, create_input_validation_middleware


def _make_app():
    app = FastAPI()

    @app.post("/api/config")
    async def save_config(payload: dict):
        return {"success": True}

    create_input_validation_middleware(app, InputValidator())
    return app


class TestInputValidationLoopbackExemption:
    def test_loopback_traffic_with_suspicious_chars_is_not_blocked(self, monkeypatch):
        monkeypatch.delenv("GALAXY_INPUT_VALIDATION_LOOPBACK", raising=False)
        app = _make_app()
        client = TestClient(app, client=("127.0.0.1", 12345))

        # 命中命令注入模式(反引号)——真实场景类比:用户填的自定义 API 地址
        # 或备注字段里恰好带了这类字符。
        resp = client.post("/api/config", json={"config": {"LOCAL_VLLM_URL": "http://x/`whoami`"}})
        assert resp.status_code == 200, (
            "本机回环地址的请求不该被输入校验误伤——这类字段允许任意字符串，" "命中检测规则不代表真的是攻击"
        )

    def test_loopback_path_traversal_pattern_not_blocked(self, monkeypatch):
        monkeypatch.delenv("GALAXY_INPUT_VALIDATION_LOOPBACK", raising=False)
        app = _make_app()
        client = TestClient(app, client=("127.0.0.1", 12345))

        resp = client.post("/api/config", json={"config": {"NODE09_SANDBOX_URL": "http://x/../y"}})
        assert resp.status_code == 200

    def test_external_ip_still_blocked_on_suspicious_input(self, monkeypatch):
        """修复不能削弱对真实外部客户端的输入校验保护。"""
        monkeypatch.delenv("GALAXY_INPUT_VALIDATION_LOOPBACK", raising=False)
        app = _make_app()
        client = TestClient(app, client=("203.0.113.7", 54321))

        resp = client.post("/api/config", json={"config": {"x": "`whoami`"}})
        assert resp.status_code == 400
        assert resp.json()["threat_type"] == "command_injection"

    def test_env_override_forces_loopback_validation(self, monkeypatch):
        monkeypatch.setenv("GALAXY_INPUT_VALIDATION_LOOPBACK", "1")
        app = _make_app()
        client = TestClient(app, client=("127.0.0.1", 12345))

        resp = client.post("/api/config", json={"config": {"x": "`whoami`"}})
        assert resp.status_code == 400

    def test_loopback_normal_config_save_unaffected(self, monkeypatch):
        """基线:正常保存(不含任何可疑字符)本来就该放行,不因这次改动而变化。"""
        monkeypatch.delenv("GALAXY_INPUT_VALIDATION_LOOPBACK", raising=False)
        app = _make_app()
        client = TestClient(app, client=("127.0.0.1", 12345))

        resp = client.post("/api/config", json={"config": {"DEEPSEEK_API_KEY": "sk-abc123"}})
        assert resp.status_code == 200
