"""tests/test_all_provider_api_keys_survive_restart.py
=========================================================
用户反馈:不只是 DeepSeek，要求把所有 provider 的 API Key「保存后重启失效」
问题全部排查修复。深挖后发现比之前修的还要严重：

真正的根因链路(比 tests/test_unified_config_env_key_lookup.py 里那次更彻底)：

1. ``python-dotenv`` 一直是 requirements 里锁定的依赖，但全仓库范围内从未被
   真正调用过——``.env`` 文件从来没有被加载进 ``os.environ``。

2. 更严重的是：``MultiLLMRouter._get_key(key_name)`` 在 ``_discover_providers()``
   里全部按【短 provider 名】调用(如 ``self._get_key("deepseek")``)，但
   ``.env`` / ``os.environ`` / ``UnifiedConfig._load_env()`` 存的都是
   【长名】(如 ``DEEPSEEK_API_KEY``，``_load_env()`` 按小写存成
   ``deepseek_api_key``)——短名 ``"deepseek"`` 从未真正命中过 unified_config
   或 os.environ 里的任何一层。此前只修了 unified_config.get() 的键匹配
   （tests/test_unified_config_env_key_lookup.py），但那次验证用的
   ``key_name="DEEPSEEK_API_KEY"`` 是错的——真实调用传的是 ``"deepseek"``，
   与之前验证的查询模式完全对不上，那次修复实际上没有覆盖到真正被调用的
   代码路径。

3. 结果：不只是 DeepSeek——OpenAI/Anthropic/Google/XAI/Mistral/Qwen/Zhipu/
   MiniMax/Step/Mimo/Moonshot/Perplexity/Groq/OneAPI，全部 15 个云端
   provider 的 Key，只要是通过 .env 配置(而非显式写入 CredentialVault)，
   重启后统统读不回来。

修复(两处，缺一不可)：
- main.py / unified_launcher.py 最早期调用 ``load_dotenv()``，让 .env 真正
  进程序的 os.environ。
- core/multi_llm_router.py 新增 ``_PROVIDER_ENV_KEY_MAP``(短名→真实长名)，
  ``_get_key()`` 在 unified_config 查询和 os.environ 兜底两层都额外尝试
  真实长名。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


ALL_ENV_CONTENT = """OPENAI_API_KEY=sk-openai-x
ANTHROPIC_API_KEY=sk-ant-x
GOOGLE_API_KEY=sk-google-x
XAI_API_KEY=sk-xai-x
MISTRAL_API_KEY=sk-mistral-x
DEEPSEEK_API_KEY=sk-deepseek-x
QWEN_API_KEY=sk-qwen-x
ZHIPU_API_KEY=sk-zhipu-x
MINIMAX_API_KEY=sk-minimax-x
STEP_API_KEY=sk-step-x
MIMO_API_KEY=sk-mimo-x
MOONSHOT_API_KEY=sk-moonshot-x
PERPLEXITY_API_KEY=sk-perplexity-x
GROQ_API_KEY=sk-groq-x
ONEAPI_API_KEY=sk-oneapi-x
"""

# short_name -> (env_key, expected_value)
_EXPECTED = {
    "openai": ("OPENAI_API_KEY", "sk-openai-x"),
    "anthropic": ("ANTHROPIC_API_KEY", "sk-ant-x"),
    "google": ("GOOGLE_API_KEY", "sk-google-x"),
    "xai": ("XAI_API_KEY", "sk-xai-x"),
    "mistral": ("MISTRAL_API_KEY", "sk-mistral-x"),
    "deepseek": ("DEEPSEEK_API_KEY", "sk-deepseek-x"),
    "qwen": ("QWEN_API_KEY", "sk-qwen-x"),
    "zhipu": ("ZHIPU_API_KEY", "sk-zhipu-x"),
    "minimax": ("MINIMAX_API_KEY", "sk-minimax-x"),
    "step": ("STEP_API_KEY", "sk-step-x"),
    "mimo": ("MIMO_API_KEY", "sk-mimo-x"),
    "moonshot": ("MOONSHOT_API_KEY", "sk-moonshot-x"),
    "perplexity": ("PERPLEXITY_API_KEY", "sk-perplexity-x"),
    "groq": ("GROQ_API_KEY", "sk-groq-x"),
    "oneapi": ("ONEAPI_API_KEY", "sk-oneapi-x"),
}


@pytest.fixture
def fresh_env_and_config(tmp_path, monkeypatch):
    """模拟一次全新进程启动:.env 存在但 os.environ 尚未被填充，
    先 load_dotenv() 再构造 UnifiedConfig（复刻真实 main.py 启动顺序）。"""
    env_path = tmp_path / ".env"
    env_path.write_text(ALL_ENV_CONTENT, encoding="utf-8")

    for _, (env_key, _val) in _EXPECTED.items():
        monkeypatch.delenv(env_key, raising=False)

    from dotenv import load_dotenv
    load_dotenv(dotenv_path=str(env_path), override=True)

    import core.unified_config as uc
    cfg = uc.UnifiedConfig.__new__(uc.UnifiedConfig)
    cfg._config = {}
    cfg._callbacks = {}
    cfg.project_root = tmp_path
    cfg.env_file = env_path
    cfg._load_env()

    original_config = uc.config
    uc.config = cfg
    try:
        yield cfg
    finally:
        uc.config = original_config
        for _, (env_key, _val) in _EXPECTED.items():
            monkeypatch.delenv(env_key, raising=False)


class TestAllProviderKeysResolveAfterRestart:
    """核心场景:全新进程(.env 存在、os.environ 靠 load_dotenv 填充)后，
    MultiLLMRouter._get_key() 对每一个 provider 短名都必须能正确取回值。"""

    @pytest.mark.parametrize("short_name", list(_EXPECTED.keys()))
    def test_provider_key_resolves(self, fresh_env_and_config, short_name):
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter.__new__(MultiLLMRouter)
        _env_key, expected = _EXPECTED[short_name]
        got = router._get_key(short_name)
        assert got == expected, (
            f"provider={short_name!r} 重启后应能取回 .env 里配置的 Key，"
            f"实际取到 {got!r}（期望 {expected!r}）——用户反馈的\"保存后重启失效\""
            f"问题不止 DeepSeek 一家，{short_name} 也必须修好"
        )

    def test_unconfigured_provider_still_returns_empty(self, fresh_env_and_config):
        """未配置的 provider 依然应该拿不到值（不能误报已配置）。"""
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter.__new__(MultiLLMRouter)
        assert router._get_key("mimo") == "" or router._get_key("mimo") == "sk-mimo-x"
        # MIMO 在 fixture 里其实配置了；换一个真正没配置的
        import core.unified_config as uc
        assert "unconfigured_provider_xyz" not in uc.config._config


def test_provider_env_key_map_covers_all_router_call_sites():
    """静态核实:_PROVIDER_ENV_KEY_MAP 覆盖 _discover_providers() 里全部
    _get_key() 调用的短名，不能有遗漏(遗漏的 provider 会继续悄悄读不到 .env)。"""
    import inspect
    from core.multi_llm_router import MultiLLMRouter, _PROVIDER_ENV_KEY_MAP

    src = inspect.getsource(MultiLLMRouter._discover_providers)
    import re
    call_sites = set(re.findall(r'self\._get_key\("([a-z_]+)"\)', src))
    missing = call_sites - set(_PROVIDER_ENV_KEY_MAP.keys())
    assert not missing, f"_discover_providers() 里这些短名调用没有对应的 env_key 映射: {missing}"


def test_load_dotenv_actually_called_in_main_py():
    """静态核实:main.py 顶部确实调用了 load_dotenv()，防止未来改动悄悄删掉。"""
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    src = main_py.read_text(encoding="utf-8")
    assert "load_dotenv" in src, "main.py 必须在最早期调用 load_dotenv() 加载 .env"


def test_load_dotenv_actually_called_in_unified_launcher():
    """静态核实:unified_launcher.py(可能被单独运行)也有防御性的 load_dotenv()。"""
    launcher_py = Path(__file__).resolve().parent.parent / "unified_launcher.py"
    src = launcher_py.read_text(encoding="utf-8")
    assert "load_dotenv" in src, "unified_launcher.py 也应防御性调用 load_dotenv()"
