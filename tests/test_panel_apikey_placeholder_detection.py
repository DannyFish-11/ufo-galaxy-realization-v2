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
            "下划线占位符 'your_...' 被误判为已配置——面板会显示'已连接'," "而真实调用会用这串模板文字去认证,必然失败"
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


@pytest.fixture()
def only_env_layer(monkeypatch):
    """把 ``_get_key()`` 三层解析链的前两层清空,只留环境变量那一层。

    ``MultiLLMRouter._get_key()`` 的优先级是 **面板/UnifiedConfig > CredentialVault >
    环境变量**。这条测试要断言的是"环境变量里的占位符不会被当成真密钥",但它此前
    只 monkeypatch 了环境变量,前两层原样留着 —— 于是在任何配了真 DeepSeek key 的
    机器上(以及本仓库的 ``runtime/secrets.env`` 存在时)它都会假红:

        _get_key('deepseek') -> 'sk-test-galaxy-...'   # 来自第 1 层,行为完全正确

    那不是被测代码有问题,是断言只控制了链的最后一环、却对整条链的结果下判断。
    这里连前两层一起隔离,测试才名副其实。

    第 1 层的存储形态要留意:``.env`` / ``runtime/secrets.env`` 经 ``_load_env()``
    是按**扁平小写**键存进 ``_config`` 的(``DEEPSEEK_API_KEY`` → ``deepseek_api_key``),
    ``get("api_keys.DEEPSEEK_API_KEY")`` 靠"取最后一段"的兜底才命中 —— 所以要清的是
    那个扁平键,清 ``api_keys`` 子字典没有用。
    """
    from core.credential_vault import reset_vault
    from core.unified_config import config as uc

    backing = uc._backend._config
    removed = {}
    for k in list(backing):
        if k.lower() in {"deepseek_api_key", "deepseek"}:
            removed[k] = backing.pop(k)
    reset_vault()
    try:
        yield
    finally:
        backing.update(removed)
        reset_vault()


class TestMultiLLMRouterRejectsUnderscorePlaceholder:
    def test_get_key_rejects_underscore_placeholder_from_env(self, monkeypatch, only_env_layer):
        from core.multi_llm_router import MultiLLMRouter

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "your_deepseek_api_key_here")
        router = MultiLLMRouter()
        val = router._get_key("deepseek")
        assert val in (None, ""), (
            f"路由器把未编辑的占位符 'your_deepseek_api_key_here' 当成真实密钥返回: {val!r}——"
            "provider 会被注册并真的拿这串模板文字去发请求"
        )

    def test_a_real_key_in_env_still_comes_through(self, monkeypatch, only_env_layer):
        """反面:隔离前两层之后,真 key 必须照样取得到。

        没有这条,上面那条可以靠"把整层弄坏、什么都取不到"通过 —— 那是"因为错误的
        理由而通过"。
        """
        from core.multi_llm_router import MultiLLMRouter

        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real-looking-deepseek-key-0987654321")
        assert MultiLLMRouter()._get_key("deepseek") == "sk-real-looking-deepseek-key-0987654321"


@pytest.fixture()
def isolated_vault(monkeypatch):
    """一个空 vault,且把它的环境变量兜底层也清掉。

    ``get_credential()`` 在内存层拿到占位符时会**继续往下找**(占位符不该盖住真值),
    所以只清 vault 是不够的:全量套件里别的测试会把 ``runtime/secrets.env`` 灌进
    ``os.environ``,于是这里断言"应为 None"时会拿到环境变量里那个真 key。单跑绿、
    合并跑红的差别就出在这。三层一起隔离,断言才稳定。
    """
    from core.credential_vault import _ENV_MAPPING, get_vault, reset_vault

    reset_vault()
    monkeypatch.delenv(_ENV_MAPPING.get("deepseek", "DEEPSEEK_API_KEY"), raising=False)
    try:
        yield get_vault()
    finally:
        reset_vault()


class TestCredentialVaultRejectsPlaceholders:
    """CredentialVault 是三层解析链里唯一没过占位符的一层(修复前)。

    ``_get_key()`` 的第 1 层(面板/UnifiedConfig)和第 3 层(环境变量)都拿
    ``PLACEHOLDER_PREFIXES`` 过滤过,唯独中间的 vault 层是 ``if val: return val``。
    而 ``POST /api/v1/vault/credentials`` 会把请求体里的任意 value 原样
    ``set_credential()`` 进去 —— 于是把示例文件里的 ``your_deepseek_api_key_here``
    存进 vault 之后,它会**盖过**第 3 层的过滤被当成真密钥返回,provider 被注册成
    "可用",面板显示"已连接",真实调用必然 401。这正是本文件开头写的那个真机反馈
    (「还是不能正常地保存和使用」)在剩下那一层上的同一个 bug。
    """

    def test_placeholder_stored_in_vault_is_not_served_as_a_credential(self, isolated_vault):
        isolated_vault.set_credential("deepseek", "your_deepseek_api_key_here")
        assert isolated_vault.get_credential("deepseek") is None, "vault 把未编辑的模板值当成真凭证发了出去"

    def test_placeholder_in_vault_is_not_listed_as_configured(self, isolated_vault):
        isolated_vault.set_credential("deepseek", "your_deepseek_api_key_here")
        assert "deepseek" not in isolated_vault.list_credential_keys(), (
            "占位符被列进已配置键名——面板会据此显示'已连接',而 get_credential() " "对同一个键返回 None,两边自相矛盾"
        )

    def test_a_real_credential_is_still_served_and_listed(self, isolated_vault):
        """反面:过滤不能把真凭证一起误伤。"""
        isolated_vault.set_credential("deepseek", "sk-real-looking-key-13579")
        assert isolated_vault.get_credential("deepseek") == "sk-real-looking-key-13579"
        assert "deepseek" in isolated_vault.list_credential_keys()

    def test_router_layer2_no_longer_leaks_a_placeholder(self, monkeypatch, only_env_layer, isolated_vault):
        """端到端:占位符存在 vault 里,``_get_key()`` 也不该拿它去注册 provider。"""
        from core.multi_llm_router import MultiLLMRouter

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        isolated_vault.set_credential("deepseek", "your_deepseek_api_key_here")
        val = MultiLLMRouter()._get_key("deepseek")
        assert val in (None, ""), f"vault 层把占位符漏成了真密钥: {val!r}"

    def test_write_endpoint_rejects_a_placeholder_instead_of_pretending_to_save(self, isolated_vault):
        """写入口当场退回,而不是收下再说。

        收下的话,调用方拿到 success=True、面板显示"已保存",但读出来是 None、
        真实调用一路 401 —— 用户完全看不出问题出在"粘的是模板文字"。
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from core.routes.vault import create_router

        app = FastAPI()
        app.include_router(create_router())
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/vault/credentials",
                json={"key_name": "deepseek", "value": "your_deepseek_api_key_here"},
            )
            assert r.status_code == 400, f"占位符被收下了(status={r.status_code}): {r.text}"
            assert "deepseek" not in isolated_vault.list_credential_keys()


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
            "未编辑的占位符 'your_oneapi_api_key_here' 被当成真实密钥," "OneAPI provider 被错误注册"
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

        assert (
            "OPENAI_API_KEY" not in wiz.config
        ), "未编辑的占位符 'your_openai_api_key_here' 被当成已配置密钥加载进向导状态"

    def test_real_looking_key_loaded_as_configured(self, tmp_path):
        import setup_wizard as sw

        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-real-openai-key-1234567890\n", encoding="utf-8")

        wiz = sw.SetupWizard()
        wiz.env_file = env_file
        wiz.config = {}
        wiz.load_existing_config()

        assert wiz.config.get("OPENAI_API_KEY") == "sk-real-openai-key-1234567890"
