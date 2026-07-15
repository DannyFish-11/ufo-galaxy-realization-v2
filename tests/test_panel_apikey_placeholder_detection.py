"""tests/test_panel_apikey_placeholder_detection.py
=====================================================
面板 API-key "看起来已保存/已连接,实际用不了"回归防护(真机反馈:"还是不能正常地
保存和使用")。

根因(排查确认):`.env.example` 里未编辑的占位符用的是下划线格式
(``your_openai_api_key_here``),但 `GET /api/config` 的 `_is_configured()`
(core/routes/system.py)与 `core/multi_llm_router.py` 判定 provider 是否"已配置"
时,只识别连字符格式 `"your-"`,漏判了下划线格式——于是面板把未编辑的模板值当成
真实密钥显示为"已连接",LLM 路由器也真的拿它去注册 provider(真实调用会 401)。
`core/config_preflight.py`/`core/credential_vault.PLACEHOLDER_PREFIXES` 早就
正确识别两种格式——这里锁定 `_is_configured()` 与路由器改用同一份表之后的行为。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    app = FastAPI()
    from core.api_routes import create_api_routes

    router = create_api_routes()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


class TestIsConfiguredRecognizesUnderscorePlaceholder:
    def test_underscore_placeholder_reported_as_not_configured(self, client, monkeypatch):
        # .env.example 实际发的占位符格式(下划线,不是连字符)。
        monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert data["configured"]["OPENAI_API_KEY"] is False, (
            "下划线占位符 'your_...' 被误判为已配置——面板会显示'已连接',"
            "而真实调用会用这串模板文字去认证,必然失败"
        )
        assert data["status"]["openai"] is False

    def test_hyphen_placeholder_still_recognized(self, client, monkeypatch):
        # 旧格式(连字符)必须继续被正确识别,不能因为改动而回退。
        monkeypatch.setenv("ANTHROPIC_API_KEY", "your-anthropic-key-here")
        r = client.get("/api/config")
        data = r.json()
        assert data["configured"]["ANTHROPIC_API_KEY"] is False

    def test_real_looking_key_reported_as_configured(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-realkeylookingvalue1234567890")
        r = client.get("/api/config")
        data = r.json()
        assert data["configured"]["OPENAI_API_KEY"] is True


class TestMultiLLMRouterRejectsUnderscorePlaceholder:
    def test_get_key_rejects_underscore_placeholder_from_env(self, monkeypatch):
        from core.multi_llm_router import MultiLLMRouter

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "your_deepseek_api_key_here")
        router = MultiLLMRouter()
        val = router._get_key("deepseek")
        assert val in (None, ""), (
            f"路由器把未编辑的占位符 'your_deepseek_api_key_here' 当成真实密钥返回: {val!r}——"
            "provider 会被注册并真的拿这串模板文字去发请求"
        )
