"""
Agnes AI 提供商接入 —— 契约测试
================================

Agnes AI(agnes-ai.com):全模态免费 API,OpenAI 兼容协议。
接入方式为 L1 声明式提供商注册表加一行,零胶水代码。本套件钉住:

1. PROVIDER_REGISTRY 条目形状(base_url / 模型 / 免费成本 / 能力位)。
2. 给 AGNES_API_KEY 即完成注册,适配器为 OpenAIAdapter(协议兼容)。
3. 面板保存 Key 后 verify_provider 能按 env_key 反解出提供商名。
4. credential_vault/_PROVIDER_ENV_KEY_MAP 短名映射与配置白名单齐全。
"""

from __future__ import annotations


class TestRegistryEntry:
    def test_entry_shape(self):
        from core.multi_llm_router import PROVIDER_REGISTRY

        spec = next(s for s in PROVIDER_REGISTRY if s["name"] == "agnes")
        assert spec["env_key"] == "AGNES_API_KEY"
        assert spec["base_url"] == "https://apihub.agnes-ai.com/v1"
        assert spec["default_model"] == "agnes-2.0-flash"
        assert spec["default_model"] in spec["models"]
        # 免费 API:成本为 0,级联 cheap-first 才会正确排序
        assert spec["cost_in"] == 0.0 and spec["cost_out"] == 0.0
        extra = spec["extra"]
        assert extra["supports_tools"] is True
        assert extra["supports_vision"] is True

    def test_adapter_map_has_agnes(self):
        from core.multi_llm_router import ADAPTER_MAP, OpenAIAdapter

        assert ADAPTER_MAP["agnes"] is OpenAIAdapter


class TestRegistration:
    def test_key_present_registers_openai_adapter(self, monkeypatch):
        monkeypatch.setenv("AGNES_API_KEY", "test-key-contract")
        from core.multi_llm_router import MultiLLMRouter, OpenAIAdapter

        r = MultiLLMRouter()
        assert "agnes" in r.providers
        cfg = r.providers["agnes"]
        assert cfg.base_url == "https://apihub.agnes-ai.com/v1"
        assert cfg.default_model == "agnes-2.0-flash"
        assert isinstance(r.adapters["agnes"], OpenAIAdapter)

    def test_no_key_not_registered(self, monkeypatch):
        monkeypatch.delenv("AGNES_API_KEY", raising=False)
        from core.multi_llm_router import MultiLLMRouter

        r = MultiLLMRouter()
        assert "agnes" not in r.providers

    def test_placeholder_key_skipped(self, monkeypatch):
        """占位 key(your- 前缀)不得注册 —— 与全表提供商同一诚实语义。"""
        monkeypatch.setenv("AGNES_API_KEY", "your-agnes-key-here")
        from core.multi_llm_router import MultiLLMRouter

        r = MultiLLMRouter()
        assert "agnes" not in r.providers


class TestPanelWiring:
    def test_env_key_resolves_provider_name(self):
        """verify_provider 按 env_key 反解:AGNES_API_KEY → agnes。"""
        from core.multi_llm_router import PROVIDER_REGISTRY

        matches = [s["name"] for s in PROVIDER_REGISTRY if s["env_key"] == "AGNES_API_KEY"]
        assert matches == ["agnes"]

    def test_router_env_key_map_aligned(self):
        """credential_vault 注释要求与 _PROVIDER_ENV_KEY_MAP 内容对齐。"""
        from core.multi_llm_router import _PROVIDER_ENV_KEY_MAP

        assert _PROVIDER_ENV_KEY_MAP.get("agnes") == "AGNES_API_KEY"

    def test_credential_vault_short_name(self):
        from core.credential_vault import _ENV_MAPPING

        assert _ENV_MAPPING.get("agnes") == "AGNES_API_KEY"

    def test_config_registry_whitelisted(self):
        from core.routes.config import CONFIG_SCHEMA

        assert "AGNES_API_KEY" in CONFIG_SCHEMA
        assert CONFIG_SCHEMA["AGNES_API_KEY"]["category"] == "llm"


class TestRoutingPolicy:
    def test_yaml_priorities_include_agnes(self):
        import yaml

        with open("config/llm_routing_policy.yaml", encoding="utf-8") as f:
            policy = yaml.safe_load(f)
        fast = policy["task_routing"]["fast_response"]["priorities"]
        general = policy["task_routing"]["general"]["priorities"]
        assert "agnes" in fast
        assert "agnes" in general
        # 免费但能力未经本栈实证:general 档不得越过主力(openai/anthropic)
        assert general.index("agnes") > general.index("anthropic")
