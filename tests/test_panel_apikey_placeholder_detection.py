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


class TestOneApiFallbackRejectsUnderscorePlaceholder:
    """OneAPI 供应商注册是漏改的第 4 个调用点(修复前:env 兜底直接绕开
    _get_key() 的 PLACEHOLDER_PREFIXES 过滤,且最终判断仍是老的 'your-' 连字符
    检查)。runtime/secrets.example.env 实际发的占位符就是下划线格式
    'your_oneapi_api_key_here',这里锁定它不会被注册成"可用 provider"。
    """

    def test_underscore_placeholder_env_fallback_not_registered(self, monkeypatch):
        from core.multi_llm_router import MultiLLMRouter

        monkeypatch.delenv("ONEAPI_API_KEY", raising=False)
        monkeypatch.delenv("ONEAPI_URL", raising=False)
        monkeypatch.setenv("ONEAPI_API_KEY", "your_oneapi_api_key_here")
        monkeypatch.setenv("ONEAPI_URL", "https://oneapi.example.com")
        router = MultiLLMRouter()
        assert "oneapi" not in router.providers, (
            "未编辑的占位符 'your_oneapi_api_key_here' 被当成真实密钥,"
            "OneAPI provider 被错误注册"
        )

    def test_real_looking_env_fallback_still_registers(self, monkeypatch):
        from core.multi_llm_router import MultiLLMRouter

        monkeypatch.delenv("ONEAPI_API_KEY", raising=False)
        monkeypatch.delenv("ONEAPI_URL", raising=False)
        monkeypatch.setenv("ONEAPI_API_KEY", "sk-real-oneapi-key-1234567890")
        monkeypatch.setenv("ONEAPI_URL", "https://oneapi.example.com")
        router = MultiLLMRouter()
        assert "oneapi" in router.providers, "真实密钥不应被占位符过滤误伤"


class TestAiBrainReadinessRejectsUnderscorePlaceholder:
    """unified_launcher.ai_brain_readiness() 的启动横幅 cloud_key_set 判断——
    同款漏改,只影响显示文案(未安装本地模型时是否声称"已配置云端 API Key 可兜底"),
    不影响真实功能,但同样的误导性质。"""

    def test_underscore_placeholder_not_treated_as_cloud_key_set(self):
        from unified_launcher import ai_brain_readiness

        status, model_installed, label = ai_brain_readiness(
            chosen_model="gemma4:e2b",
            available_models=[],
            ollama_healthy=True,
            env={"DEEPSEEK_API_KEY": "your_deepseek_api_key_here"},
        )
        assert status == "fail", f"占位符不该被当成'已配置云端 Key 可兜底',实际 status={status}"
        assert "已配置云端 API Key 可兜底" not in label
        assert "无云端 API Key" in label

    def test_real_looking_key_treated_as_cloud_key_set(self):
        from unified_launcher import ai_brain_readiness

        status, model_installed, label = ai_brain_readiness(
            chosen_model="gemma4:e2b",
            available_models=[],
            ollama_healthy=True,
            env={"DEEPSEEK_API_KEY": "sk-real-deepseek-key-1234567890"},
        )
        assert status == "warn"
        assert "已配置云端 API Key 可兜底" in label


class TestSetupWizardRejectsUnderscorePlaceholder:
    """setup_wizard.py::load_existing_config() —— 命令行首启向导的同款漏改。
    误判会导致向导认为某个 key "已配置"而跳过提示用户输入真密钥。"""

    def test_underscore_placeholder_not_loaded_as_configured(self, tmp_path):
        import setup_wizard as sw

        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=your_openai_api_key_here\n", encoding="utf-8")

        wiz = sw.SetupWizard()
        wiz.env_file = env_file
        wiz.config = {}
        wiz.load_existing_config()

        assert "OPENAI_API_KEY" not in wiz.config, (
            "未编辑的占位符 'your_openai_api_key_here' 被当成已配置密钥加载进向导状态"
        )

    def test_real_looking_key_loaded_as_configured(self, tmp_path):
        import setup_wizard as sw

        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-real-openai-key-1234567890\n", encoding="utf-8")

        wiz = sw.SetupWizard()
        wiz.env_file = env_file
        wiz.config = {}
        wiz.load_existing_config()

        assert wiz.config.get("OPENAI_API_KEY") == "sk-real-openai-key-1234567890"
