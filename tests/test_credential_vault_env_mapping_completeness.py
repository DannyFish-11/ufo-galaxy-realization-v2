"""tests/test_credential_vault_env_mapping_completeness.py
=============================================================
延续"全部 API Key 排查"这条线索:core.credential_vault._ENV_MAPPING 之前只
覆盖 8 个 provider(openai/openai_base/anthropic/deepseek/groq/ollama/oneapi/
oneapi_url)，漏了 google/xai/mistral/qwen/zhipu/minimax/step/mimo/moonshot/
perplexity 共 10 个——MultiLLMRouter._get_key() 的第 2 层(CredentialVault)
对这些 provider 会静默查不到值，直接落到第 3 层(环境变量)。目前第 3 层
已用真实长名兜底(core.multi_llm_router._PROVIDER_ENV_KEY_MAP)，不算致命，
但这一层形同虚设、且任何其它直接调用 get_credential() 的代码路径对这些
provider 一样拿不到值。

修复:_ENV_MAPPING 补齐到跟 _PROVIDER_ENV_KEY_MAP 完全一致的 15 个 provider。
"""

from __future__ import annotations

import os

import pytest

from core.credential_vault import CredentialVault, _ENV_MAPPING
from core.multi_llm_router import _PROVIDER_ENV_KEY_MAP


def test_env_mapping_matches_router_provider_map():
    """两处独立维护的 短名→长名 映射必须完全一致，不能有一处遗漏。"""
    router_keys = set(_PROVIDER_ENV_KEY_MAP.keys())
    vault_keys = set(_ENV_MAPPING.keys())
    missing_in_vault = router_keys - vault_keys
    assert not missing_in_vault, (
        f"credential_vault._ENV_MAPPING 缺少这些 provider(router 里有、vault 里没有): "
        f"{missing_in_vault}"
    )
    for short_name in router_keys & vault_keys:
        assert _ENV_MAPPING[short_name] == _PROVIDER_ENV_KEY_MAP[short_name], (
            f"provider={short_name!r} 两处映射的真实 env key 不一致: "
            f"vault={_ENV_MAPPING[short_name]!r} router={_PROVIDER_ENV_KEY_MAP[short_name]!r}"
        )


@pytest.mark.parametrize(
    "short_name,env_key",
    [
        ("google", "GOOGLE_API_KEY"),
        ("xai", "XAI_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"),
        ("qwen", "QWEN_API_KEY"),
        ("zhipu", "ZHIPU_API_KEY"),
        ("minimax", "MINIMAX_API_KEY"),
        ("step", "STEP_API_KEY"),
        ("mimo", "MIMO_API_KEY"),
        ("moonshot", "MOONSHOT_API_KEY"),
        ("perplexity", "PERPLEXITY_API_KEY"),
    ],
)
def test_previously_missing_providers_now_resolve_via_env_fallback(monkeypatch, short_name, env_key):
    """之前遗漏的 10 个 provider，现在 CredentialVault.get_credential() 的
    环境变量回退层必须能正确取到值(不再静默落空)。"""
    monkeypatch.setenv(env_key, f"sk-{short_name}-test-key")
    vault = CredentialVault()
    assert vault.get_credential(short_name) == f"sk-{short_name}-test-key"
